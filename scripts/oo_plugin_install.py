"""Process-death recovery for MOT Deck's unmodified Office plugin installation.

The shell still verifies upstream pins and prepares the complete candidate. This
helper owns only publication. A kernel lock survives exec (and is released after
the last installer child exits); a durable journal precedes every asset mutation.
Interrupted publication rolls back, and interrupted rollback resumes idempotently.
No upstream file is patched. This is process-crash recovery, not a power-loss claim.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

ITEMS = ("ai", "v1", "SOURCES.txt", "INSTALLED")
LOCK = ".install.lock"
JOURNAL = "publication.json"
PREFIX = ".plugin-install."


def _identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)]


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write(stage, record):
    fd, raw = tempfile.mkstemp(prefix=".journal-", dir=stage)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(record, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(raw, stage / JOURNAL)
        _sync(stage)
    finally:
        Path(raw).unlink(missing_ok=True)


def _read(dest, stage):
    if stage.parent != dest or not stage.name.startswith(PREFIX):
        raise ValueError("plugin staging path is outside its installation")
    if not stat.S_ISDIR(stage.lstat().st_mode):
        raise ValueError("plugin staging path is not a real directory")
    fd = os.open(stage / JOURNAL, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd) as inp:
        if not stat.S_ISREG(os.fstat(inp.fileno()).st_mode):
            raise ValueError("plugin publication journal is not a regular file")
        record = json.load(inp)
    if (not isinstance(record, dict) or record.get("schema") != 1
            or record.get("root") != str(dest)
            or record.get("phase") not in ("preparing", "prepared", "committed")):
        raise ValueError("invalid plugin publication journal")
    if record["phase"] != "preparing":
        for key in ("original", "candidate"):
            rows = record.get(key)
            if not isinstance(rows, dict) or set(rows) != set(ITEMS):
                raise ValueError("incomplete plugin publication journal")
            for value in rows.values():
                if value is None and key == "original":
                    continue
                if not (isinstance(value, list) and len(value) == 3
                        and all(type(n) is int and n >= 0 for n in value)):
                    raise ValueError("invalid plugin publication identity")
    return record


def _move(source, destination):
    os.replace(source, destination)
    _sync(source.parent)
    if source.parent != destination.parent:
        _sync(destination.parent)


def _remove(path):
    if stat.S_ISDIR(path.lstat().st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    _sync(path.parent)


def _rollback(dest, stage, record):
    # A successor receipt must disappear before any asset changes. The original
    # receipt is restored last, including when recovery itself was interrupted.
    stamp = dest / "INSTALLED"
    if _identity(stamp) == record["candidate"]["INSTALLED"]:
        _remove(stamp)
    for name in ITEMS:
        target, saved = dest / name, stage / "old" / name
        original, candidate = record["original"][name], record["candidate"][name]
        current, backup = _identity(target), _identity(saved)
        if backup is not None:
            if backup != original:
                raise ValueError(f"saved plugin {name} changed; recovery retained at {stage}")
            if current is not None:
                if current != candidate:
                    raise ValueError(f"plugin {name} changed outside this install; retained at {stage}")
                _remove(target)
            _move(saved, target)
        elif original is not None:
            if current != original:
                raise ValueError(f"original plugin {name} cannot be located; retained at {stage}")
        elif current is not None:
            if current != candidate:
                raise ValueError(f"new plugin {name} changed outside this install; retained at {stage}")
            _remove(target)


def cleanup(dest, stage):
    record = _read(dest, stage)
    if record["phase"] == "prepared":
        _rollback(dest, stage, record)
    # Mark cleanup before deleting anything: a kill part-way through rmtree must
    # not strand an unreadable transaction or discard rollback's final receipt.
    retired = stage.with_name(".plugin-cleanup." + stage.name[len(PREFIX):])
    _move(stage, retired)
    shutil.rmtree(retired)
    _sync(dest)


def recover(dest):
    for stage in sorted(dest.glob(PREFIX + "*")):
        # A kill between mkdtemp and journal creation precedes every mutation.
        # Only an empty directory is safe to retire without a journal.
        if not (stage / JOURNAL).exists() and stage.is_dir() and not stage.is_symlink():
            for temporary in stage.iterdir():
                if not (temporary.name.startswith(".journal-")
                        and stat.S_ISREG(temporary.lstat().st_mode)):
                    raise ValueError(f"unrecognized plugin staging content retained at {stage}")
            for temporary in stage.iterdir():
                temporary.unlink()
            stage.rmdir()
            continue
        cleanup(dest, stage)
    for retired in dest.glob(".plugin-cleanup.*"):
        if not stat.S_ISDIR(retired.lstat().st_mode):
            raise ValueError("retired plugin staging path is not a real directory")
        shutil.rmtree(retired)
    _sync(dest)


def prepare(dest):
    stage = Path(tempfile.mkdtemp(prefix=PREFIX, dir=dest))
    _write(stage, {"schema": 1, "root": str(dest), "phase": "preparing"})
    (stage / "new").mkdir()
    (stage / "old").mkdir()
    return stage


def publish(dest, stage):
    record = _read(dest, stage)
    if record["phase"] != "preparing":
        raise ValueError("plugin publication has already begun")
    original = {name: _identity(dest / name) for name in ITEMS}
    candidate = {name: _identity(stage / "new" / name) for name in ITEMS}
    if any(value is None for value in candidate.values()):
        raise ValueError("plugin candidate is incomplete")
    record.update(phase="prepared", original=original, candidate=candidate)
    _write(stage, record)
    try:
        for name in ("INSTALLED", "ai", "v1", "SOURCES.txt"):
            if original[name] is not None:
                _move(dest / name, stage / "old" / name)
        for name in ITEMS:
            _move(stage / "new" / name, dest / name)
        record["phase"] = "committed"
        _write(stage, record)
    except BaseException:
        # Read the durable phase, since a journal write could have completed just
        # before its directory sync failed. Never infer it from Python memory.
        cleanup(dest, stage)
        raise


def _lock_fd(dest):
    fd = os.open(dest / LOCK, os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("plugin installation lock is not a regular file")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError("another plugin installation is still active") from None
    return fd


def main():
    command, raw_dest, *args = sys.argv[1:]
    dest = Path(raw_dest).absolute()
    if command == "run":
        dest.mkdir(parents=True, exist_ok=True)
        fd = _lock_fd(dest)
        os.set_inheritable(fd, True)
        env = dict(os.environ, OOP_INSTALL_LOCK_FD=str(fd))
        os.execve("/bin/bash", ["/bin/bash", *args], env)
    # All helper children share the lock held by the invoking shell. Validate
    # both the descriptor and pathname, and acquire if the caller supplied an
    # unlocked descriptor. Never unlink a kernel-lock file (split-lock race).
    fd = int(os.environ["OOP_INSTALL_LOCK_FD"])
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or [info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)] != _identity(dest / LOCK):
        raise ValueError("plugin installer lock identity changed")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if command == "recover":
        recover(dest)
    elif command == "stage":
        print(prepare(dest))
    elif command == "publish":
        publish(dest, Path(args[0]))
    elif command == "cleanup":
        stage = Path(args[0])
        if stage.exists():
            cleanup(dest, stage)
    else:
        raise ValueError("unknown plugin publication command")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[oo-ai-plugin] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
