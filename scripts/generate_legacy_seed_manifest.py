#!/usr/bin/env python3
"""Regenerate the exact-digest inventory for FAT releases that shipped tests.

This is an authoring utility, not a runtime cleanup heuristic.  The immutable commit
list below is evidence from release records; each path/digest pair is read from Git's
object database, never from the current checkout or a live installation.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys


SEED_RELEASES = (
    ("970df3b", "v1.5.75 clean FAT release"),
    ("5729c9f", "v1.5.81 verified clean FAT release"),
    ("c484561", "v1.5.84 verified clean FAT release"),
)
PREFIXES = ("bridge/tests/", "bridge/contract_tests/")


def git(*args: str) -> bytes:
    proc = subprocess.run(("git", *args), capture_output=True, check=False)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip()
                           or "git command failed")
    return proc.stdout


def manifest() -> dict:
    files: dict[str, set[str]] = {}
    evidence = []
    for short_ref, label in SEED_RELEASES:
        full_ref = git("rev-parse", "--verify", short_ref + "^{commit}").decode().strip()
        evidence.append(f"{label} at {full_ref}")
        names = git("ls-tree", "-r", "--name-only", full_ref,
                    "bridge/tests", "bridge/contract_tests").decode().splitlines()
        for path in names:
            if not path.startswith(PREFIXES):
                continue
            payload = git("show", f"{full_ref}:{path}")
            files.setdefault(path, set()).add(hashlib.sha256(payload).hexdigest())
    rendered = {path: (next(iter(values)) if len(values) == 1 else sorted(values))
                for path, values in sorted(files.items())}
    return {"algorithm": "sha256", "evidence": evidence, "files": rendered,
            "format": 1}


if __name__ == "__main__":
    try:
        json.dump(manifest(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    except (OSError, RuntimeError) as exc:
        print(f"legacy seed manifest: {exc}", file=sys.stderr)
        raise SystemExit(2)
