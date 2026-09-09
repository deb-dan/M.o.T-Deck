"""Completeness checks for the U95 standalone collection adapter."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from bridge.tests.standalone_manifest import STANDALONE_SUITES


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def test_every_non_manifest_python_suite_is_directly_pytest_collectable() -> None:
    """A new script-style module may not fall between raw and adapted collection."""
    excluded = set(STANDALONE_SUITES) | {
        Path(__file__).name,
    }
    failures = []
    for path in sorted(HERE.glob("test_*.py")):
        if path.name in excluded:
            continue
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", str(path)],
            cwd=ROOT, text=True, capture_output=True, timeout=60,
        )
        if proc.returncode != 0 or "collected" not in (proc.stdout + proc.stderr):
            failures.append(
                f"{path.name}: rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
            )
    assert not failures, (
        "A non-manifest test is not safely pytest-collectable. Convert it to ordinary "
        "test functions or add it to the standalone adapter deliberately:\n"
        + "\n".join(failures)
    )
