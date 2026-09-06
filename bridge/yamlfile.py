"""One transaction primitive for the live ``motdeck.yaml`` document (stdlib only)."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
import stat
import tempfile
import threading


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _require_regular(path: str, *, absent_ok: bool = False) -> os.stat_result | None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if absent_ok:
            return None
        raise
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"refusing non-regular motdeck.yaml state file: {path}")
    return info


def _read_regular(path: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"refusing non-regular motdeck.yaml state file: {path}")
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return fh.read()
    finally:
        if fd >= 0:
            os.close(fd)


@contextmanager
def _locked(path: str):
    absolute = os.path.abspath(path)
    with _LOCKS_GUARD:
        mutex = _LOCKS.setdefault(absolute, threading.RLock())
    with mutex:
        lock_path = absolute + ".lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"refusing non-regular motdeck.yaml lock: {lock_path}")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield absolute
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def transform_file(path, transform):
    """Serialize read/transform/replace; return transform's optional result.

    Readers need no lock: replacement means they see the complete old or new inode.
    ``transform`` receives the latest text after both locks are held and may return
    either new text or ``(new_text, result)``. An identical edit does not replace.
    """
    with _locked(os.fspath(path)) as absolute:
        old = _read_regular(absolute)
        changed = transform(old)
        if isinstance(changed, tuple):
            new, result = changed
        else:
            new, result = changed, None
        if not isinstance(new, str):
            raise TypeError("motdeck.yaml transform must return text")
        if new == old:
            return result
        directory = os.path.dirname(absolute) or "."
        mode = stat.S_IMODE(_require_regular(absolute).st_mode)
        fd, temporary = tempfile.mkstemp(prefix=".motdeck-yaml-", suffix=".tmp",
                                         dir=directory)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
                fh.flush()
                os.fsync(fh.fileno())
            _require_regular(absolute)
            os.replace(temporary, absolute)
            temporary = ""
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass  # replacement is complete; directory fsync is best-effort on macOS
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
        return result
