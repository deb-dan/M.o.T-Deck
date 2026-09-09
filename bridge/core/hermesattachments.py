"""Safe display projection for Hermes's persisted ``@image:`` directives (A3).

Hermes stores real host paths so its own desktop can reopen an image turn.  The MOT
Deck panel cannot navigate those paths, and the bridge must not turn the convention
into an arbitrary-file server.  This module recognizes the upstream grammar but
registers only small, regular image files inside Hermes's managed ``images`` root.
The browser receives an opaque token and basename; it never receives the host path.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import re
import stat
import threading


MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_TOKENS = 256
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})
IMAGE_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
_DIRECTIVE = re.compile(r"^@image:(?:`([^`\r\n]+)`|(\S+))\s*$")
_TOKENS: "OrderedDict[str, tuple[Path, int, int, int, int]]" = OrderedDict()
_LOCK = threading.RLock()


def _image_root() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return (Path(home).expanduser() / "images").resolve()


def _safe_image(raw: str) -> tuple[Path, os.stat_result] | None:
    candidate = Path(str(raw or "")).expanduser()
    try:
        # Reject the reference itself when it is a symlink. Resolving and then opening
        # it would otherwise turn a link planted under ~/.hermes/images into a host read.
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            return None
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(_image_root())
        info = resolved.stat()
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0
            or info.st_size > MAX_IMAGE_BYTES
            or resolved.suffix.lower() not in IMAGE_SUFFIXES):
        return None
    return resolved, info


def _register(path: Path, info: os.stat_result) -> str:
    raw = f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}".encode()
    token = hashlib.sha256(raw).hexdigest()[:32]
    with _LOCK:
        _TOKENS[token] = (path, int(info.st_dev), int(info.st_ino),
                          int(info.st_size), int(info.st_mtime_ns))
        _TOKENS.move_to_end(token)
        while len(_TOKENS) > MAX_TOKENS:
            _TOKENS.popitem(last=False)
    return token


def project_message(content: str) -> tuple[str, list[dict], list[str]]:
    """Return display text, safe image handles, and basename-only unavailable rows."""
    kept: list[str] = []
    attachments: list[dict] = []
    unavailable: list[str] = []
    for line in str(content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _DIRECTIVE.fullmatch(line)
        if not match:
            kept.append(line)
            continue
        raw = match.group(1) or match.group(2) or ""
        name = Path(raw).name or "image"
        safe = _safe_image(raw)
        if safe is None:
            unavailable.append(name)
            continue
        path, info = safe
        attachments.append({"hermes_id": _register(path, info), "name": path.name,
                            "kind": "image"})
    # Hermes appends directives after the caption. Remove only newline slack exposed by
    # taking those trailing lines away; preserve all meaningful interior whitespace.
    return "\n".join(kept).rstrip("\n"), attachments, unavailable


def open_image(token: str) -> tuple[bytes, str, str] | None:
    """Read the exact registered inode without following links; fail closed on change."""
    with _LOCK:
        record = _TOKENS.get(str(token or ""))
    if record is None:
        return None
    path, expected_dev, expected_ino, expected_size, expected_mtime = record
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_dev != expected_dev or info.st_ino != expected_ino
                    or info.st_size != expected_size or info.st_mtime_ns != expected_mtime
                    or info.st_size <= 0
                    or info.st_size > MAX_IMAGE_BYTES):
                return None
            remaining = int(info.st_size)
            chunks = []
            while remaining:
                chunk = os.read(fd, min(remaining, 256 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if remaining:
                return None
        finally:
            os.close(fd)
    except OSError:
        return None
    raw = b"".join(chunks)
    suffix = path.suffix.lower()
    signatures = {
        ".png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": raw.startswith(b"\xff\xd8\xff"),
        ".jpeg": raw.startswith(b"\xff\xd8\xff"),
        ".gif": raw.startswith((b"GIF87a", b"GIF89a")),
        ".webp": len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        ".bmp": raw.startswith(b"BM"),
    }
    if not signatures.get(suffix, False):
        return None
    return raw, IMAGE_MIMES.get(suffix, "application/octet-stream"), path.name
