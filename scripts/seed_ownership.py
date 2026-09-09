#!/usr/bin/env python3
"""Create and enforce MOT Deck FAT-seed file ownership manifests.

The manifest is evidence, not permission by directory.  Cleanup removes an
individual regular file only when its current SHA-256 is one of the digests a
known seed recorded for that exact relative path.  Symlinks, special files,
unknown paths, and modified bytes are preserved and reported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath

MANIFEST_NAME = "SEED_FILES.json"
FORMAT = 1
LEGACY_TEST_PREFIXES = ("bridge/tests/", "bridge/contract_tests/")
FORBIDDEN_RUNTIME_NAMES = {".DS_Store"}


def _safe_rel(value: object) -> str | None:
    text = str(value or "").replace("\\", "/")
    path = PurePosixPath(text)
    if not text or text.startswith("/") or ".." in path.parts or "." in path.parts:
        return None
    return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def build_manifest(root: Path) -> dict:
    root = root.resolve(strict=True)
    files: dict[str, str] = {}
    for base, dirs, names in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not Path(base, d).is_symlink())
        for name in sorted(names):
            if name in FORBIDDEN_RUNTIME_NAMES or name.startswith("._"):
                raise ValueError(f"runtime seed contains macOS metadata: {name}")
            path = Path(base, name)
            rel = path.relative_to(root).as_posix()
            if rel == MANIFEST_NAME or path.is_symlink():
                continue
            try:
                mode = path.lstat().st_mode
            except OSError:
                continue
            if stat.S_ISREG(mode):
                files[rel] = _sha256(path)
    return {"format": FORMAT, "algorithm": "sha256", "files": files}


def write_manifest(root: Path, output: Path) -> int:
    _atomic_json(output, build_manifest(root))
    print(f"[seed-ownership] wrote {output} ({len(json.loads(output.read_text())['files'])} files)")
    return 0


def _load_known(path: Path) -> dict[str, set[str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") != FORMAT or raw.get("algorithm") != "sha256":
        raise ValueError("unsupported seed ownership manifest")
    out: dict[str, set[str]] = {}
    for rel_raw, digest_raw in (raw.get("files") or {}).items():
        rel = _safe_rel(rel_raw)
        if rel is None:
            raise ValueError(f"unsafe manifest path: {rel_raw!r}")
        digests = digest_raw if isinstance(digest_raw, list) else [digest_raw]
        good = {str(d).lower() for d in digests
                if isinstance(d, str) and len(d) == 64
                and all(c in "0123456789abcdefABCDEF" for c in d)}
        if not good:
            raise ValueError(f"no valid digest for {rel}")
        out[rel] = good
    return out


def _under_no_symlink(root: Path, rel: str) -> bool:
    current = root
    for part in PurePosixPath(rel).parts[:-1]:
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                return False
        except FileNotFoundError:
            return True
    return True


def clean_known_tests(root: Path, manifest: Path) -> int:
    root = root.resolve(strict=True)
    known = _load_known(manifest)
    removed: list[str] = []
    preserved: list[dict[str, str]] = []
    reported: set[str] = set()
    for rel, digests in sorted(known.items()):
        if not rel.startswith(LEGACY_TEST_PREFIXES):
            raise ValueError(f"legacy-test manifest exceeds its authority: {rel}")
        target = root / rel
        if not target.exists() and not target.is_symlink():
            continue
        if not _under_no_symlink(root, rel):
            preserved.append({"path": rel, "reason": "symlinked parent"})
            reported.add(rel)
            continue
        try:
            mode = target.lstat().st_mode
        except OSError as exc:
            preserved.append({"path": rel, "reason": f"could not inspect: {exc}"})
            reported.add(rel)
            continue
        if not stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            preserved.append({"path": rel, "reason": "not a regular no-follow file"})
            reported.add(rel)
            continue
        actual = _sha256(target)
        if actual not in digests:
            preserved.append({"path": rel, "reason": "digest differs from every known seed"})
            reported.add(rel)
            continue
        target.unlink()
        removed.append(rel)

    # A path absent from the historical manifest is not ours. Name every such
    # survivor so the operator knows why the directory remains instead of seeing an
    # unexplained residue or, worse, having it guessed away.
    for prefix in LEGACY_TEST_PREFIXES:
        start = root / prefix.rstrip("/")
        if not start.is_dir() or start.is_symlink():
            continue
        for base, dirs, names in os.walk(start, topdown=True, followlinks=False):
            for dirname in list(dirs):
                child = Path(base, dirname)
                if child.is_symlink():
                    rel = child.relative_to(root).as_posix()
                    if rel not in reported:
                        preserved.append({"path": rel, "reason": "unknown symlinked directory"})
                        reported.add(rel)
                    dirs.remove(dirname)
            for name in names:
                rel = Path(base, name).relative_to(root).as_posix()
                if rel not in known and rel not in reported:
                    preserved.append({"path": rel, "reason": "not recorded by a known seed"})
                    reported.add(rel)

    # Empty directories are not user data. Work bottom-up, never following links.
    for prefix in LEGACY_TEST_PREFIXES:
        start = root / prefix.rstrip("/")
        if not start.is_dir() or start.is_symlink():
            continue
        for base, dirs, _ in os.walk(start, topdown=False, followlinks=False):
            for dirname in dirs:
                child = Path(base, dirname)
                if not child.is_symlink():
                    try:
                        child.rmdir()
                    except OSError:
                        pass
            try:
                Path(base).rmdir()
            except OSError:
                pass

    print(f"[seed-ownership] removed {len(removed)} proven legacy test file(s)")
    for row in preserved:
        print(f"[seed-ownership] preserved {row['path']}: {row['reason']}")
    for prefix in LEGACY_TEST_PREFIXES:
        kept = root / prefix.rstrip("/")
        if kept.exists() or kept.is_symlink():
            print(f"[seed-ownership] retained {prefix.rstrip('/')}: contains preserved entries")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    write = sub.add_parser("write")
    write.add_argument("root", type=Path)
    write.add_argument("output", type=Path)
    clean = sub.add_parser("clean-known-tests")
    clean.add_argument("root", type=Path)
    clean.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "write":
            return write_manifest(args.root, args.output)
        return clean_known_tests(args.root, args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[seed-ownership] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
