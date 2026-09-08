#!/usr/bin/env python3
"""One-time, rollback-safe live-root migration for U150.

This moves only the installed MOT Deck state. It never reads another project tree,
never copies the repository manifest over live state, and never signals a process.
The operator must stop the old, provenance-owned stack before invoking ``apply``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Iterable


OLD_BUNDLE_ID = "local.harness.app"
NEW_BUNDLE_ID = "local.motdeck.app"
OLD_MANIFEST = "harness.yaml"
NEW_MANIFEST = "motdeck.yaml"

OWNED_VENVS = (
    "aider-venv", "bridge-venv", "comfyui-venv", "hermes-venv", "mlx-venv",
    "music-venv", "odysseus-venv", "searxng-venv", "voicebox-venv",
    "voicestudio-venv",
)
NESTED_VENVS = (Path("data/unsloth-home/unsloth_studio"),)
ACTIVE_PATH_FILES = (
    Path("data/models.json"),
    Path("data/goose/ui-home/goose/data/models/registry.json"),
    Path("vendor/odysseus/data/uploads/uploads.json"),
    Path("vendor/odysseus/data/uploads/uploads.json.bak"),
)
SECRET_STORE = Path("data/.env.local")
SECRET_KEY_MIGRATIONS = {
    b"MOT_RUNNER_API_KEY": b"MOT_DECK_RUNNER_API_KEY",
    b"MOT_AUX_API_KEY": b"MOT_DECK_AUX_API_KEY",
    b"MOT_ODYSSEUS_ADMIN_USER": b"MOT_DECK_ODYSSEUS_ADMIN_USER",
    b"MOT_ODYSSEUS_ADMIN_PASSWORD": b"MOT_DECK_ODYSSEUS_ADMIN_PASSWORD",
}
STATE_DIRS = ("WebKit", "HTTPStorages")


class MigrationError(RuntimeError):
    pass


def _direct_dir(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as exc:
        raise MigrationError(f"missing {label}: {path}") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise MigrationError(f"{label} must be a direct directory, not a link: {path}")


def _regular(path: Path, label: str) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise MigrationError(f"{label} must be a direct regular file: {path}")


def _atomic_bytes(path: Path, payload: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.u150-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, stat.S_IMODE(mode))
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _rewrite_path(path: Path, old: bytes, new: bytes,
                  changed: list[tuple[Path, bytes, int]]) -> None:
    if not path.exists():
        return
    _regular(path, "active generated path file")
    original = path.read_bytes()
    if b"\0" in original or old not in original:
        return
    replacement = original.replace(old, new)
    mode = path.lstat().st_mode
    _atomic_bytes(path, replacement, mode)
    changed.append((path, original, mode))


def _rewrite_tokens(path: Path, migrations: dict[bytes, bytes],
                    changed: list[tuple[Path, bytes, int]]) -> None:
    if not path.exists():
        return
    _regular(path, "identity token file")
    original = path.read_bytes()
    replacement = original
    for old, new in migrations.items():
        # These are environment variable names, never substitutions inside values.
        # A user-chosen credential can itself contain a legacy identifier.
        replacement = re.sub(rb"(?m)^(\s*(?:export[ \t]+)?)" + re.escape(old)
                             + rb"(_B64)?(?=[ \t]*=)",
                             lambda match: match.group(1) + new + (match.group(2) or b""),
                             replacement)
    if replacement == original:
        return
    mode = path.lstat().st_mode
    _atomic_bytes(path, replacement, mode)
    changed.append((path, original, mode))


def _rewrite_python_link(path: Path, old: str, new: str,
                         changed: list[tuple[Path, str]]) -> None:
    """Retarget only an explicitly enumerated venv interpreter symlink.

    Console launchers are text, but uv/venv commonly makes ``bin/python`` or
    ``bin/python3`` an absolute symlink into the bundled interpreter. Moving the root
    leaves that link dangling, so text-only relocation is not a complete migration.
    """
    if not path.is_symlink():
        return
    original = os.readlink(path)
    if old not in original:
        return
    replacement = original.replace(old, new)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.u150-link-", dir=path.parent)
    os.close(fd)
    temporary_path = Path(temporary)
    temporary_path.unlink()
    try:
        os.symlink(replacement, temporary_path)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    changed.append((path, original))


def _restore_rewrites(changed: list[tuple[Path, bytes, int]],
                      changed_links: list[tuple[Path, str]]) -> list[str]:
    errors: list[str] = []
    for path, original, mode in reversed(changed):
        try:
            _atomic_bytes(path, original, mode)
        except Exception as exc:
            errors.append(str(exc))
    for path, original in reversed(changed_links):
        try:
            temporary = path.with_name(path.name + ".u150-rollback")
            temporary.unlink(missing_ok=True)
            os.symlink(original, temporary)
            os.replace(temporary, path)
        except Exception as exc:
            errors.append(str(exc))
    return errors


def _generated_path_files(root: Path) -> Iterable[Path]:
    venvs = [root / "data" / name for name in OWNED_VENVS]
    venvs.extend(root / rel for rel in NESTED_VENVS)
    for venv in venvs:
        if not venv.exists():
            continue
        _direct_dir(venv, "owned virtual environment")
        yield venv / "pyvenv.cfg"
        bindir = venv / "bin"
        if bindir.is_dir() and not bindir.is_symlink():
            for entry in sorted(bindir.iterdir()):
                if entry.is_file() and not entry.is_symlink():
                    yield entry
        lib = venv / "lib"
        if lib.is_dir() and not lib.is_symlink():
            yield from sorted(lib.glob("python*/site-packages/__editable__*_finder.py"))
            # Editable installs also use plain .pth files containing an absolute source
            # root. The VoiceStudio environment on the real stack uses this form.
            yield from sorted(lib.glob("python*/site-packages/*.pth"))

    for relative in ACTIVE_PATH_FILES:
        yield root / relative
    snapshot = root / "data/opencode/xdg/data/opencode/snapshot"
    if snapshot.is_dir() and not snapshot.is_symlink():
        yield from sorted(snapshot.glob("**/config"))
        yield from sorted(snapshot.glob("**/objects/info/alternates"))


def _rename_manifests(root: Path, renamed: list[tuple[Path, Path]]) -> None:
    source = root / OLD_MANIFEST
    target = root / NEW_MANIFEST
    if target.exists() or target.is_symlink():
        raise MigrationError(f"new manifest already exists during old-root migration: {target}")
    _regular(source, "live manifest")
    os.rename(source, target)
    renamed.append((source, target))

    for candidate in sorted(root.glob(OLD_MANIFEST + ".bak*")):
        _regular(candidate, "live manifest backup")
        replacement = candidate.with_name(NEW_MANIFEST + candidate.name[len(OLD_MANIFEST):])
        if replacement.exists() or replacement.is_symlink():
            raise MigrationError(f"manifest-backup target already exists: {replacement}")
        os.rename(candidate, replacement)
        renamed.append((candidate, replacement))


def _state_moves(state_home: Path) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    library = state_home / "Library"
    for family in STATE_DIRS:
        source = library / family / OLD_BUNDLE_ID
        target = library / family / NEW_BUNDLE_ID
        if (source.exists() or source.is_symlink()) and (target.exists() or target.is_symlink()):
            raise MigrationError(f"both old and new {family} state exist; refusing to merge")
        if source.exists() or source.is_symlink():
            _direct_dir(source, f"old {family} state")
            moves.append((source, target))
    return moves


def migrate(old_root: Path, new_root: Path, state_home: Path) -> dict:
    old_root = old_root.expanduser().absolute()
    new_root = new_root.expanduser().absolute()
    state_home = state_home.expanduser().absolute()

    old_exists = old_root.exists() or old_root.is_symlink()
    new_exists = new_root.exists() or new_root.is_symlink()
    if old_exists and new_exists:
        raise MigrationError("both old and new live roots exist; refusing to merge or overwrite")
    if not old_exists and new_exists:
        _direct_dir(new_root, "new live root")
        if not (new_root / NEW_MANIFEST).is_file():
            raise MigrationError("new live root exists without motdeck.yaml")
        # Idempotence also resumes a migration interrupted after the root/manifest move.
        # Every participant remains explicitly enumerated; this is not a tree-wide
        # search-and-replace over live state.
        changed: list[tuple[Path, bytes, int]] = []
        changed_links: list[tuple[Path, str]] = []
        old_text, new_text = str(old_root), str(new_root)
        try:
            for path in _generated_path_files(new_root):
                _rewrite_path(path, os.fsencode(old_text), os.fsencode(new_text), changed)
            for venv in [new_root / "data" / name for name in OWNED_VENVS] + [
                    new_root / rel for rel in NESTED_VENVS]:
                bindir = venv / "bin"
                if bindir.is_dir() and not bindir.is_symlink():
                    for link in sorted(bindir.iterdir()):
                        if link.name == "python" or link.name == "python3" or link.name.startswith("python3."):
                            _rewrite_python_link(link, old_text, new_text, changed_links)
            _rewrite_tokens(new_root / SECRET_STORE, SECRET_KEY_MIGRATIONS, changed)
            for path, _original in changed_links:
                if old_text in os.readlink(path):
                    raise MigrationError(f"old live root remains in interpreter link: {path}")
        except Exception as exc:
            rollback_errors = _restore_rewrites(changed, changed_links)
            message = f"continued migration failed and was rolled back: {exc}"
            if rollback_errors:
                message += "; ROLLBACK ERRORS: " + " | ".join(rollback_errors)
            raise MigrationError(message) from exc
        return {"status": "already-migrated", "rewritten": len(changed),
                "retargeted_links": len(changed_links), "state_dirs": 0}
    if not old_exists:
        raise MigrationError("old live root is absent and no migrated root exists")
    _direct_dir(old_root, "old live root")
    _regular(old_root / OLD_MANIFEST, "old live manifest")
    if old_root.stat().st_dev != new_root.parent.stat().st_dev:
        raise MigrationError("old and new roots are on different filesystems; atomic move unavailable")

    planned_state = _state_moves(state_home)
    journal_path = new_root.parent / ".motdeck-u150-migration.json"
    moved_root = False
    renamed: list[tuple[Path, Path]] = []
    changed: list[tuple[Path, bytes, int]] = []
    changed_links: list[tuple[Path, str]] = []
    moved_state: list[tuple[Path, Path]] = []
    try:
        os.rename(old_root, new_root)
        moved_root = True
        _rename_manifests(new_root, renamed)
        old_bytes = os.fsencode(str(old_root))
        new_bytes = os.fsencode(str(new_root))
        for path in _generated_path_files(new_root):
            _rewrite_path(path, old_bytes, new_bytes, changed)
        for venv in [new_root / "data" / name for name in OWNED_VENVS] + [
                new_root / rel for rel in NESTED_VENVS]:
            bindir = venv / "bin"
            if bindir.is_dir() and not bindir.is_symlink():
                for link in sorted(bindir.iterdir()):
                    if link.name == "python" or link.name == "python3" or link.name.startswith("python3."):
                        _rewrite_python_link(link, str(old_root), str(new_root), changed_links)
        _rewrite_tokens(new_root / SECRET_STORE, SECRET_KEY_MIGRATIONS, changed)
        for source, target in planned_state:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source, target)
            moved_state.append((source, target))

        if not (new_root / NEW_MANIFEST).is_file():
            raise MigrationError("post-migration manifest verification failed")
        for path, _original, _mode in changed:
            if old_bytes in path.read_bytes():
                raise MigrationError(f"old live root remains in rewritten active file: {path}")
        for path, _original in changed_links:
            if str(old_root) in os.readlink(path):
                raise MigrationError(f"old live root remains in interpreter link: {path}")
        result = {
            "status": "migrated", "old_root": str(old_root), "new_root": str(new_root),
            "rewritten": len(changed), "renamed_manifests": len(renamed),
            "retargeted_links": len(changed_links), "state_dirs": len(moved_state),
        }
        _atomic_bytes(journal_path, (json.dumps(result, indent=2) + "\n").encode(), 0o600)
        return result
    except Exception as exc:
        rollback_errors: list[str] = []
        for source, target in reversed(moved_state):
            try:
                os.rename(target, source)
            except Exception as rollback:
                rollback_errors.append(str(rollback))
        rollback_errors.extend(_restore_rewrites(changed, changed_links))
        for source, target in reversed(renamed):
            try:
                os.rename(target, source)
            except Exception as rollback:
                rollback_errors.append(str(rollback))
        if moved_root:
            try:
                os.rename(new_root, old_root)
            except Exception as rollback:
                rollback_errors.append(str(rollback))
        message = f"migration failed and was rolled back: {exc}"
        if rollback_errors:
            message += "; ROLLBACK ERRORS: " + " | ".join(rollback_errors)
        raise MigrationError(message) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "apply"))
    parser.add_argument("--old-root", default=str(Path.home() / "Library/Application Support/Harness"))
    parser.add_argument("--new-root", default=str(Path.home() / "Library/Application Support/MOT Deck"))
    parser.add_argument("--state-home", default=str(Path.home()))
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            old = Path(args.old_root)
            new = Path(args.new_root)
            print(json.dumps({"old_exists": old.exists(), "new_exists": new.exists(),
                              "old_manifest": (old / OLD_MANIFEST).is_file(),
                              "new_manifest": (new / NEW_MANIFEST).is_file()}, indent=2))
            return 0
        result = migrate(Path(args.old_root), Path(args.new_root), Path(args.state_home))
    except MigrationError as exc:
        print(f"[motdeck-migration] ERROR: {exc}", file=sys.stderr)
        return 1
    print("[motdeck-migration] " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
