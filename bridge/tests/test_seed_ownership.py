#!/usr/bin/env python3
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "seed_ownership.py"
GENERATOR = ROOT / "scripts" / "generate_legacy_seed_manifest.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_cleanup_removes_only_exact_known_seed_files():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "root"
        tests = root / "bridge" / "tests"
        tests.mkdir(parents=True)
        exact = tests / "exact.py"
        changed = tests / "changed.py"
        unknown = tests / "unknown.py"
        exact.write_bytes(b"seed\n")
        changed.write_bytes(b"user edit\n")
        unknown.write_bytes(b"unknown\n")
        manifest = Path(td) / "known.json"
        manifest.write_text(json.dumps({
            "format": 1, "algorithm": "sha256", "files": {
                "bridge/tests/exact.py": sha(b"seed\n"),
                "bridge/tests/changed.py": sha(b"old seed\n"),
            }}))
        result = subprocess.run(
            [str(TOOL), "clean-known-tests", str(root), str(manifest)],
            text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        assert not exact.exists()
        assert changed.read_bytes() == b"user edit\n"
        assert unknown.read_bytes() == b"unknown\n"
        assert "preserved bridge/tests/changed.py" in result.stdout
        assert "preserved bridge/tests/unknown.py: not recorded by a known seed" in result.stdout
        assert "retained bridge/tests: contains preserved entries" in result.stdout


def test_manifest_records_relative_paths_and_digests():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "seed"
        root.mkdir()
        (root / "a.txt").write_text("a")
        output = root / "SEED_FILES.json"
        result = subprocess.run([str(TOOL), "write", str(root), str(output)],
                                text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
        payload = json.loads(output.read_text())
        assert payload["files"] == {"a.txt": sha(b"a")}


def test_repository_legacy_manifest_is_valid_and_test_scoped():
    payload = json.loads((ROOT / "scripts/seed_manifests/legacy-runtime-tests.json").read_text())
    assert payload["files"]
    assert all(path.startswith(("bridge/tests/", "bridge/contract_tests/"))
               for path in payload["files"])
    generated = subprocess.run([str(GENERATOR)], cwd=ROOT, text=True,
                               capture_output=True, check=False)
    assert generated.returncode == 0, generated.stderr
    assert json.loads(generated.stdout) == payload
