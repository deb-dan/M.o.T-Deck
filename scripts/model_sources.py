#!/usr/bin/env python3
"""Read-only membership adapters for external model managers.

Filesystem probes answer whether bytes look structurally usable.  A manager adapter
answers a different question: whether that manager still lists the artifact.  The two
signals are intentionally never collapsed into one guess.

This module stores nothing.  ``data/models.json`` remains the sole persisted inventory;
successful observations are carried on the rows they describe.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess


ADAPTER = "lmstudio-cli-v1"
SUPPORTED_FORMATS = {"gguf": "gguf", "safetensors": "mlx", "mlx": "mlx"}


def _result(state: str, root: str, members=(), detail: str = "") -> dict:
    return {"adapter": ADAPTER, "state": state, "root": root,
            "members": list(members), "detail": detail}


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except (TypeError, ValueError):
        return False


def _lms_binary() -> str | None:
    candidates = [os.environ.get("MOT_DECK_LMS_BIN"),
                  os.path.expanduser("~/.lmstudio/bin/lms"), shutil.which("lms")]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.realpath(candidate)
    return None


def _json_list(stdout: str):
    decoder = json.JSONDecoder()
    for offset, char in enumerate(stdout or ""):
        if char != "[":
            continue
        try:
            value, end = decoder.raw_decode(stdout[offset:])
        except (TypeError, ValueError):
            continue
        if isinstance(value, list) and not stdout[offset + end:].strip():
            return value
    raise ValueError("the CLI did not return one JSON list")


def lmstudio_inventory(models_root: str, *, run=subprocess.run) -> dict:
    """Return one whole-catalog observation; never infer deletion on failure.

    ``available`` means every LLM row matched the v1 schema and is safe to use as
    membership evidence. ``unavailable`` means the command could not answer.
    ``unsupported`` means it answered in a shape this adapter does not understand.
    Both non-available states carry zero deletion authority.
    """
    root = os.path.realpath(os.path.abspath(os.path.expanduser(models_root)))
    binary = _lms_binary()
    if not binary:
        return _result("unavailable", root, detail="LM Studio CLI is not installed or executable")
    try:
        completed = run([binary, "ls", "--json"], capture_output=True, text=True,
                        timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return _result("unavailable", root,
                       detail=f"LM Studio CLI could not be read: {str(exc)[:160]}")
    if getattr(completed, "returncode", 1) != 0:
        tail = (getattr(completed, "stderr", "") or getattr(completed, "stdout", ""))[-160:]
        return _result("unavailable", root,
                       detail="LM Studio CLI exited unsuccessfully" + (f": {tail}" if tail else ""))
    try:
        rows = _json_list(getattr(completed, "stdout", ""))
        members, identities, member_keys = [], set(), set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("a catalog row is not an object")
            if row.get("type") != "llm":
                continue
            raw_format, rel, key = row.get("format"), row.get("path"), row.get("modelKey")
            if raw_format not in SUPPORTED_FORMATS:
                raise ValueError(f"unknown LLM format {raw_format!r}")
            if not isinstance(rel, str) or not rel or os.path.isabs(rel):
                raise ValueError("an LLM path is absent or absolute")
            if os.path.normpath(rel) != rel or rel in (".", ".."):
                raise ValueError("an LLM path is not canonical")
            if not isinstance(key, str) or not key.strip():
                raise ValueError("an LLM modelKey is absent")
            if key.strip() in member_keys:
                raise ValueError("two catalog rows have the same modelKey")
            real = os.path.realpath(os.path.join(root, rel))
            if not _inside(real, root):
                raise ValueError("an LLM path escapes the configured library")
            fmt = SUPPORTED_FORMATS[raw_format]
            identity = (fmt, real)
            if identity in identities:
                raise ValueError("two catalog rows identify the same artifact")
            identities.add(identity)
            member_keys.add(key.strip())
            members.append({
                "format": fmt, "path": real, "relative_path": rel,
                "member_key": key.strip(),
                "display_name": str(row.get("displayName") or "").strip(),
                "size_bytes": row.get("sizeBytes") if isinstance(row.get("sizeBytes"), int) else None,
                "ctx": (row.get("maxContextLength")
                        if isinstance(row.get("maxContextLength"), int) else None),
                "vision": row.get("vision") if isinstance(row.get("vision"), bool) else None,
                "tools": (row.get("trainedForToolUse")
                          if isinstance(row.get("trainedForToolUse"), bool) else None),
            })
        members.sort(key=lambda item: (item["relative_path"], item["format"]))
        return _result("available", root, members)
    except (TypeError, ValueError) as exc:
        return _result("unsupported", root,
                       detail=f"LM Studio returned an unsupported catalog: {str(exc)[:160]}")


def source_observation(member: dict, root: str) -> dict:
    """Stable row-local membership evidence; no timestamp or second registry."""
    return {"v": 1, "adapter": ADAPTER, "root": root,
            "member_key": member["member_key"], "format": member["format"],
            "path": member["relative_path"]}
