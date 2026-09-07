"""Persistent, source-qualified remote metadata for ComfyUI model downloads.

This is one cache keyed by the exact download URL.  It deliberately stores a richer
record only when the remote source supplies content identity; it is not a second model
registry and it never decides whether a workflow or artifact exists.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .appctx import ROOT


SIZES: dict = {}


def _sizes_path() -> Path:
    return ROOT / "data" / "comfy" / "sizes.json"


def sizes_load() -> None:
    try:
        data = json.loads(_sizes_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        for url, value in data.items():
            # v1 cache entries were integers. Preserve them: a richer schema is not a
            # reason to forget already measured sizes and flicker cards to "unknown".
            if isinstance(value, int) and value > 0:
                SIZES[url] = value
            elif isinstance(value, dict) and isinstance(value.get("bytes"), int):
                item = {"bytes": int(value["bytes"])}
                digest = str(value.get("sha256") or "").lower()
                if re.fullmatch(r"[0-9a-f]{64}", digest):
                    item.update(sha256=digest,
                                source=str(value.get("source") or "")[:40])
                SIZES[url] = item
    except (OSError, ValueError):
        pass


def sizes_save() -> None:
    try:
        path = _sizes_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(path) + ".motdeck-tmp"
        with open(tmp, "w") as stream:
            json.dump(SIZES, stream, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def size_known(url: "str | None") -> "int | None":
    if not url:
        return None
    value = SIZES.get(url)
    if isinstance(value, int):
        return value
    if isinstance(value, dict) and isinstance(value.get("bytes"), int):
        return int(value["bytes"])
    return None


def digest_known(url: "str | None") -> "str | None":
    """An authoritative remote content SHA-256, never a CDN/Xet object hash."""
    value = SIZES.get(url) if url else None
    if not isinstance(value, dict) or value.get("source") != "huggingface-lfs":
        return None
    digest = str(value.get("sha256") or "").lower()
    return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None


sizes_load()
