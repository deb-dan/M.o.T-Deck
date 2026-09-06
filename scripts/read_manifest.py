#!/usr/bin/env python3
"""Read one typed value from motdeck.yaml with real YAML semantics.

The shell launcher uses this instead of ad-hoc awk.  Null is empty, while the quoted
string ``"null"`` remains the four characters ``null``; comments, spaces, colons and
escapes are interpreted by PyYAML rather than truncated by shell text processing.
Nothing is written and secret values are never included in an error.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys

import yaml


def _read_regular(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("manifest is not a regular file")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    finally:
        if fd >= 0:
            os.close(fd)


def value(root: Path, dotted: str, kind: str):
    data = yaml.safe_load(_read_regular(root / "motdeck.yaml"))
    if not isinstance(data, dict):
        raise ValueError("manifest root must be a mapping")
    # The launcher's typed YAML boundary is also the one secret-overlay boundary;
    # shell never sources/evals the file and therefore cannot execute its contents.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from bridge.core.localsecrets import overlay_config
    data = overlay_config(data, root)
    cur = data
    for part in dotted.split("."):
        if not part or not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if cur is None:
        return None
    if kind == "str":
        if not isinstance(cur, str):
            raise ValueError("expected a string")
        return cur
    if kind == "int":
        if isinstance(cur, bool) or not isinstance(cur, int):
            raise ValueError("expected an integer")
        return str(cur)
    if kind == "bool":
        if not isinstance(cur, bool):
            raise ValueError("expected a boolean")
        return "true" if cur else "false"
    raise ValueError("unsupported value type")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("path")
    parser.add_argument("kind", choices=("str", "int", "bool"))
    args = parser.parse_args()
    try:
        result = value(args.root, args.path, args.kind)
    except Exception as exc:  # noqa: BLE001 -- CLI boundary; never print the value
        print(f"ERROR: invalid motdeck.yaml value at {args.path}: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        sys.stdout.write(str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
