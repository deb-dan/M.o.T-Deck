#!/usr/bin/env python3
"""Advance a FAT-seeded vendor tree without guessing ownership.

FAT seeds intentionally omit ``.git``.  A plain rsync --delete would therefore
delete untracked runtime/user files along with retired upstream files.  This tool
uses the exact old and new Git trees as the ownership manifest: it updates only
paths Git owned at either revision, refuses locally modified/colliding paths, backs
up every replaced byte, and leaves every untracked path untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


class Refusal(RuntimeError):
    pass


def _safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise Refusal(f"unsafe archive path: {name!r}")
    return path.as_posix()


def _tree(repo: Path, revision: str) -> dict[str, dict[str, object]]:
    try:
        archive = subprocess.check_output(
            ["git", "-C", str(repo), "archive", "--format=tar", revision],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.output.decode("utf-8", "replace").strip()
        raise Refusal(f"cannot read Git tree {revision}: {detail}") from exc
    result: dict[str, dict[str, object]] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        for member in bundle:
            name = _safe_name(member.name.rstrip("/"))
            if member.isdir():
                continue
            if member.isreg():
                stream = bundle.extractfile(member)
                if stream is None:
                    raise Refusal(f"Git archive yielded no bytes for {name}")
                result[name] = {
                    "kind": "file",
                    "mode": member.mode & 0o777,
                    "data": stream.read(),
                }
            elif member.issym():
                result[name] = {
                    "kind": "symlink",
                    "mode": 0o777,
                    "data": member.linkname,
                }
            else:
                raise Refusal(f"unsupported Git archive member for {name}")
    return result


def _fingerprint_entry(entry: dict[str, object]) -> str:
    data = entry["data"]
    raw = data if isinstance(data, bytes) else str(data).encode()
    return f"{entry['kind']}:{hashlib.sha256(raw).hexdigest()}:{int(entry['mode']):o}"


def _read_live(path: Path) -> dict[str, object] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return {"kind": "symlink", "mode": 0o777, "data": os.readlink(path)}
    if stat.S_ISREG(info.st_mode):
        return {"kind": "file", "mode": stat.S_IMODE(info.st_mode), "data": path.read_bytes()}
    raise Refusal(f"tracked path has unsupported live type: {path}")


def _same(left: dict[str, object] | None, right: dict[str, object] | None) -> bool:
    if left is None or right is None:
        return left is right
    # Git cares only about executable versus non-executable, not every POSIX mode bit.
    left_exec = bool(int(left["mode"]) & 0o111)
    right_exec = bool(int(right["mode"]) & 0o111)
    return (left["kind"], left_exec, left["data"]) == (
        right["kind"], right_exec, right["data"])


def _assert_safe_parent(root: Path, target: Path) -> None:
    relative = target.relative_to(root)
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Refusal(f"tracked path crosses a non-directory/symlink parent: {cursor}")


def _atomic_write(path: Path, entry: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if entry["kind"] == "symlink":
        temp = path.parent / f".{path.name}.motdeck-link-{os.getpid()}"
        try:
            os.symlink(str(entry["data"]), temp)
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
        return
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.motdeck-", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(entry["data"])
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, int(entry["mode"]))
        os.replace(temp, path)
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _copy_for_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        os.symlink(os.readlink(source), destination)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def plan(repo: Path, destination: Path, old: str, new: str):
    if not repo.is_dir() or not (repo / ".git").exists():
        raise Refusal(f"source is not a Git checkout: {repo}")
    if not destination.is_dir() or destination.is_symlink():
        raise Refusal(f"destination must be a real directory: {destination}")
    old_tree, new_tree = _tree(repo, old), _tree(repo, new)
    changed = sorted(
        path for path in set(old_tree) | set(new_tree)
        if not _same(old_tree.get(path), new_tree.get(path))
    )
    live_before: dict[str, dict[str, object] | None] = {}
    refusals = []
    for name in changed:
        target = destination / name
        _assert_safe_parent(destination, target)
        live = _read_live(target)
        live_before[name] = live
        old_entry, new_entry = old_tree.get(name), new_tree.get(name)
        if old_entry is not None:
            if live is not None and not _same(live, old_entry) and not _same(live, new_entry):
                refusals.append(name)
        elif live is not None and not _same(live, new_entry):
            refusals.append(name)
    if refusals:
        sample = ", ".join(refusals[:8])
        extra = f" (+{len(refusals) - 8} more)" if len(refusals) > 8 else ""
        raise Refusal(
            "locally modified/untracked paths collide with the upstream transition: "
            f"{sample}{extra}"
        )
    return old_tree, new_tree, changed, live_before


def apply(repo: Path, destination: Path, old: str, new: str, backup_root: Path, check: bool):
    old_tree, new_tree, changed, live_before = plan(repo, destination, old, new)
    summary = {
        "old": old,
        "new": new,
        "changed_paths": len(changed),
        "replaced": sum(1 for p in changed if live_before[p] is not None and p in new_tree),
        "added": sum(1 for p in changed if live_before[p] is None and p in new_tree),
        "retired": sum(1 for p in changed if live_before[p] is not None and p not in new_tree),
    }
    if check:
        return summary, None

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = backup_root / f"{destination.name}-{stamp}"
    if backup.exists() or backup.is_symlink():
        raise Refusal(f"backup target already exists: {backup}")
    backup.mkdir(parents=True)
    for name in changed:
        if live_before[name] is not None:
            _copy_for_backup(destination / name, backup / "files" / name)
    manifest = {
        **summary,
        "destination": str(destination),
        "paths": {
            name: {
                "before": None if live_before[name] is None else _fingerprint_entry(live_before[name]),
                "old": None if name not in old_tree else _fingerprint_entry(old_tree[name]),
                "new": None if name not in new_tree else _fingerprint_entry(new_tree[name]),
            }
            for name in changed
        },
    }
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    completed = []
    try:
        for name in changed:
            target = destination / name
            if name in new_tree:
                _atomic_write(target, new_tree[name])
            elif target.exists() or target.is_symlink():
                target.unlink()
            completed.append(name)
    except Exception:
        # Restore every touched path to its precise pre-transaction state. Newly
        # introduced paths are removed; replaced/retired paths come from the backup.
        for name in reversed(completed):
            target = destination / name
            before = live_before[name]
            if target.exists() or target.is_symlink():
                target.unlink()
            if before is not None:
                _atomic_write(target, before)
        raise

    # Postcondition: all Git-owned new bytes match, while untracked paths were never
    # enumerated for mutation in the first place.
    for name in changed:
        if not _same(_read_live(destination / name), new_tree.get(name)):
            raise Refusal(f"post-write verification failed for {name}; backup: {backup}")
    return summary, backup


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--backup-root", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv[1:])
    try:
        summary, backup = apply(
            args.source.resolve(), args.destination.resolve(), args.old, args.new,
            args.backup_root.resolve(), not args.apply,
        )
        mode = "apply" if args.apply else "check"
        print(f"[vendor-update] {mode}: " + ", ".join(f"{k}={v}" for k, v in summary.items()))
        if backup:
            print(f"[vendor-update] backup: {backup}")
        return 0
    except (OSError, Refusal) as exc:
        print(f"[vendor-update] REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
