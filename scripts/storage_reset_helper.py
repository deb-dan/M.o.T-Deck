#!/usr/bin/env python3
"""Detached factory-reset/full-uninstall mover.

This helper never discovers targets after launch. The bridge passes literal, validated
paths and their device/inode identities; the helper waits for the bridge to exit, checks
those identities again, then renames the targets into one recoverable Trash batch.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tarfile
import time


BUNDLE_ID = "local.motdeck.app"
EXECUTABLE = "MOTDeck"


class ResetRefusal(RuntimeError):
    pass


def canonical_support_root(home: Path | None = None) -> Path:
    return (Path(home) if home is not None else Path.home()) / "Library/Application Support/MOT Deck"


def validate_support_root(path: Path, *, home: Path | None = None) -> Path:
    path = Path(os.path.abspath(path))
    expected = Path(os.path.abspath(canonical_support_root(home)))
    if path != expected or path in (Path(path.anchor), Path.home(), Path(home or Path.home())):
        raise ResetRefusal("support root is not the canonical MOT Deck Application Support directory")
    if path.is_symlink() or not path.is_dir():
        raise ResetRefusal("the canonical MOT Deck support root is not a real directory")
    return path


def validate_bundle(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    try:
        with (path / "Contents/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise ResetRefusal("the installed app bundle has no readable Info.plist") from exc
    binary = path / "Contents/MacOS" / EXECUTABLE
    if (path.is_symlink() or not path.is_dir()
            or info.get("CFBundleIdentifier") != BUNDLE_ID
            or info.get("CFBundleExecutable") != EXECUTABLE
            or not binary.is_file() or not os.access(binary, os.X_OK)):
        raise ResetRefusal("the installed app does not match local.motdeck.app / MOTDeck")
    return path


def validate_factory_seed(app: Path, expected_version: str) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", expected_version or ""):
        raise ResetRefusal("factory reset has no valid expected release version")
    resources = app / "Contents/Resources"
    seed = resources / "motdeck-seed-fat.tar.gz"
    provisioner = resources / "firstrun_fat.sh"
    if seed.is_symlink() or not seed.is_file() or provisioner.is_symlink() \
            or not provisioner.is_file():
        raise ResetRefusal("the installed app has no complete offline factory-reset seed")
    try:
        with tarfile.open(seed, "r:gz") as archive:
            member = next((archive.getmember(name) for name in ("./VERSION", "VERSION")
                           if name in archive.getnames()), None)
            if member is None or not member.isfile() or member.size > 64:
                raise ResetRefusal("the installed factory-reset seed has no valid VERSION")
            handle = archive.extractfile(member)
            raw = handle.read(65) if handle is not None else b""
    except (OSError, tarfile.TarError) as exc:
        raise ResetRefusal("the installed factory-reset seed is unreadable") from exc
    try:
        version = raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise ResetRefusal("the installed factory-reset seed has an invalid VERSION") from exc
    if version != expected_version:
        raise ResetRefusal(
            f"factory-reset seed v{version} does not match live v{expected_version}")


def verify_identity(path: Path, dev: int, ino: int) -> None:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise ResetRefusal(f"target disappeared before removal: {path}") from exc
    if int(st.st_dev) != int(dev) or int(st.st_ino) != int(ino):
        raise ResetRefusal(f"target identity changed after preview: {path}")


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def trash_batch(home: Path, stamp: str) -> Path:
    trash = home / ".Trash"
    if not trash.is_dir() or trash.is_symlink():
        raise ResetRefusal("the current user's Trash directory is unavailable")
    batch = trash / f"MOT-Deck-{stamp}-{int(time.time())}-{os.getpid()}"
    batch.mkdir(mode=0o700)
    return batch


def execute(args) -> dict:
    home = Path(args.home) if args.home else Path.home()
    root = validate_support_root(Path(args.root), home=home)
    app = validate_bundle(Path(args.app))
    if args.mode == "factory-reset":
        validate_factory_seed(app, args.expected_version)
    verify_identity(root, args.root_dev, args.root_ino)
    verify_identity(app, args.app_dev, args.app_ino)
    if args.mode == "factory-reset":
        validate_factory_seed(app, args.expected_version)
    if args.dry_run:
        return {"ok": True, "dry_run": True, "mode": args.mode,
                "root": str(root), "app": str(app)}
    subprocess.run(["/usr/bin/osascript", "-e",
                    'tell application id "local.motdeck.app" to quit'],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 30
    while pid_alive(args.bridge_pid) and time.time() < deadline:
        time.sleep(0.2)
    if pid_alive(args.bridge_pid):
        raise ResetRefusal("the bridge did not exit; no files were moved")
    verify_identity(root, args.root_dev, args.root_ino)
    verify_identity(app, args.app_dev, args.app_ino)
    batch = trash_batch(home, args.mode)
    moved: list[tuple[Path, Path]] = []
    try:
        root_dst = batch / "MOT Deck Application Support"
        os.replace(root, root_dst)
        moved.append((root, root_dst))
        if args.mode == "full-uninstall":
            app_dst = batch / app.name
            os.replace(app, app_dst)
            moved.append((app, app_dst))
    except Exception:
        for src, dst in reversed(moved):
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dst, src)
            except Exception:
                pass
        raise
    if args.mode == "factory-reset":
        subprocess.Popen(["/usr/bin/open", str(app)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "mode": args.mode, "trash": str(batch),
            "moved": [str(dst) for _src, dst in moved]}


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser()
    out.add_argument("--mode", choices=("factory-reset", "full-uninstall"), required=True)
    out.add_argument("--root", required=True)
    out.add_argument("--app", required=True)
    out.add_argument("--root-dev", type=int, required=True)
    out.add_argument("--root-ino", type=int, required=True)
    out.add_argument("--app-dev", type=int, required=True)
    out.add_argument("--app-ino", type=int, required=True)
    out.add_argument("--bridge-pid", type=int, required=True)
    out.add_argument("--expected-version", default="")
    out.add_argument("--home", default="")
    out.add_argument("--dry-run", action="store_true")
    return out


def main() -> int:
    args = parser().parse_args()
    try:
        result = execute(args)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - final detached evidence surface
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
