"""Contain and stage Generate inputs without overwriting existing media."""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path


def stage_source(src: dict, input_root: Path, output_root: Path) -> "str | None":
    """Put a chosen source file where LoadImage/LoadVideo can see it, and return the
    name to write into the widget. A gallery file is COPIED (never moved: the gallery
    keeps everything), and a file already in input/ is used where it lies."""
    fn = str((src or {}).get("filename") or "")
    if not fn:
        return None
    if (src.get("origin") or "gallery") == "input":
        try:
            root = input_root.resolve()
            selected = (root / fn).resolve()
            selected.relative_to(root)
            return str(selected.relative_to(root)) if selected.is_file() else None
        except (ValueError, OSError):
            return None
    root = output_root.resolve()
    try:
        p = (root / (src.get("subfolder") or "") / fn).resolve()
        p.relative_to(root)
    except (ValueError, OSError):
        return None
    if not p.is_file():
        return None
    temporary = None
    try:
        input_root.mkdir(parents=True, exist_ok=True)
        # Publish a complete copy exclusively. Existing inputs belong to the user,
        # and equal byte counts do not establish that two images are the same.
        fd, temporary = tempfile.mkstemp(prefix=".motdeck-source-", dir=input_root)
        os.close(fd)
        shutil.copy2(p, temporary)
        for n in range(10000):
            name = p.name if n == 0 else f"{p.stem} ({n}){p.suffix}"
            dest = input_root / name
            try:
                os.link(temporary, dest)
                return dest.name
            except FileExistsError:
                if _same_source_bytes(Path(temporary), dest):
                    return dest.name
    except OSError:
        return None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return None


def _same_source_bytes(source: Path, dest: Path) -> bool:
    """Reuse only a regular input containing the exact selected bytes."""
    fd = -1
    try:
        fd = os.open(dest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != source.stat().st_size:
            return False
        existing = os.fdopen(fd, "rb")
        fd = -1
        with existing, source.open("rb") as selected:
            while True:
                chunk = selected.read(1 << 20)
                if existing.read(1 << 20) != chunk:
                    return False
                if not chunk:
                    return True
    except OSError:
        return False
    finally:
        if fd >= 0:
            os.close(fd)
