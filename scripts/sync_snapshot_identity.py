#!/usr/bin/env python3
"""Synchronize the small, repo-owned identity surface retained in a FAT snapshot.

This is deliberately not a directory mirror.  The snapshot also contains generated
and user-owned state, so only the explicit files below may be replaced or retired.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path


OWNED_FILES = (
    Path("README.md"),
    Path("CLAUDE.md"),
    Path("skills/README.md"),
    Path("app/main.swift"),
    Path("app/make_icon.swift"),
    Path("app/MOTDeck.icns"),
)

RETIRED_FILES = {
    Path("app/Harness.icns"): Path("app/MOTDeck.icns"),
    Path("docs/HARNESS-INTERNALS.md"): Path("docs/MOT-DECK-INTERNALS.md"),
    Path("docs/harness-architecture.md"): Path("docs/mot-deck-architecture.md"),
}

RETIRED_GUARD = Path("guards/harness-path-guard")
CURRENT_GUARD = Path("guards/motdeck-path-guard")
GUARD_SOURCE_FILES = {"README.md", "__init__.py", "plugin.yaml", "policy.yaml"}


class SyncError(RuntimeError):
    pass


def _direct_dir(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise SyncError(f"missing {label}: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise SyncError(f"{label} must be a direct directory: {path}")


def _regular_nofollow(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise SyncError(f"missing {label}: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise SyncError(f"{label} must be a direct regular file: {path}")


def _atomic_copy(source: Path, target: Path) -> None:
    _regular_nofollow(source, "repo-owned source")
    _direct_dir(target.parent, "snapshot destination directory")
    if target.exists() or target.is_symlink():
        _regular_nofollow(target, "snapshot repo-owned destination")
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.ship-", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary_path, stat.S_IMODE(source.lstat().st_mode))
        os.replace(temporary_path, target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    if source.read_bytes() != target.read_bytes():
        raise SyncError(f"snapshot copy did not match source: {target}")


def _plugin_name(path: Path) -> str:
    _regular_nofollow(path, "plug-in manifest")
    match = re.search(r"(?m)^name:\s*['\"]?([^'\"#\s]+)", path.read_text())
    return match.group(1) if match else ""


def _retire_guard(snapshot: Path) -> tuple[bool, str]:
    old = snapshot / RETIRED_GUARD
    if not old.exists() and not old.is_symlink():
        return False, ""
    current = snapshot / CURRENT_GUARD
    try:
        _direct_dir(old, "retired snapshot guard")
        _direct_dir(current, "replacement snapshot guard")
        if _plugin_name(old / "plugin.yaml") != "harness-path-guard":
            raise SyncError("retired guard does not identify the managed old plug-in")
        if _plugin_name(current / "plugin.yaml") != "motdeck-path-guard":
            raise SyncError("replacement guard does not identify the managed current plug-in")
        for root, dirs, files in os.walk(old, followlinks=False):
            root_path = Path(root)
            for name in dirs:
                candidate = root_path / name
                if candidate.is_symlink() or name != "__pycache__":
                    raise SyncError(f"unexpected directory in retired guard: {candidate}")
            for name in files:
                candidate = root_path / name
                if candidate.is_symlink():
                    raise SyncError(f"symlink in retired guard: {candidate}")
                relative_parent = candidate.parent.relative_to(old).as_posix()
                allowed = (relative_parent == "." and name in GUARD_SOURCE_FILES) or (
                    relative_parent == "__pycache__" and name.endswith(".pyc"))
                if not allowed:
                    raise SyncError(f"unexpected file in retired guard: {candidate}")
    except (OSError, SyncError) as exc:
        return False, str(exc)
    shutil.rmtree(old)
    return True, ""


def sync(repo: Path, snapshot: Path) -> dict[str, list[str]]:
    repo = repo.absolute()
    snapshot = snapshot.absolute()
    _direct_dir(repo, "repository root")
    _direct_dir(snapshot, "snapshot root")

    copied: list[str] = []
    retired: list[str] = []
    preserved: list[str] = []
    for relative in OWNED_FILES:
        source = repo / relative
        target = snapshot / relative
        _atomic_copy(source, target)
        copied.append(relative.as_posix())

    # A retired name is removed only after its exact replacement exists in both the
    # repo and snapshot and those replacement bytes agree.  Unexpected file shapes
    # fail closed; no broad glob or recursive deletion is permitted here.
    for old_relative, replacement_relative in RETIRED_FILES.items():
        repo_replacement = repo / replacement_relative
        snapshot_replacement = snapshot / replacement_relative
        _regular_nofollow(repo_replacement, "replacement source")
        _regular_nofollow(snapshot_replacement, "replacement snapshot file")
        if repo_replacement.read_bytes() != snapshot_replacement.read_bytes():
            raise SyncError(
                f"refusing to retire {old_relative}: replacement bytes differ")
        old = snapshot / old_relative
        if not old.exists() and not old.is_symlink():
            continue
        _regular_nofollow(old, "retired snapshot file")
        old.unlink()
        retired.append(old_relative.as_posix())

    guard_retired, guard_reason = _retire_guard(snapshot)
    if guard_retired:
        retired.append(RETIRED_GUARD.as_posix())
    elif guard_reason:
        preserved.append(f"{RETIRED_GUARD.as_posix()}: {guard_reason}")

    return {"copied": copied, "retired": retired, "preserved": preserved}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    try:
        result = sync(args.repo, args.snapshot)
    except (OSError, SyncError) as exc:
        print(f"[ship] ERROR: snapshot identity sync refused: {exc}")
        return 1
    print("[ship] snapshot identity: "
          f"{len(result['copied'])} owned files synced; "
          f"{len(result['retired'])} retired names removed")
    for warning in result["preserved"]:
        print(f"[ship] WARNING: preserved unverified retired-name object: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
