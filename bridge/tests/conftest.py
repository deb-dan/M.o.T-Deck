"""Collection adapter for the legacy standalone corpus (U95)."""

from pathlib import Path
import subprocess
import sys

import pytest

from bridge.tests.standalone_manifest import STANDALONE_SUITES


class StandaloneSuite(pytest.File):
    def collect(self):
        yield StandaloneItem.from_parent(self, name=self.path.name)


class StandaloneItem(pytest.Item):
    def runtest(self):
        root = Path(__file__).resolve().parents[2]
        proc = subprocess.run(
            [sys.executable, str(self.path)], cwd=root, text=True,
            capture_output=True, timeout=180,
        )
        if proc.returncode:
            raise AssertionError(
                f"{self.path.name} failed as a standalone suite (rc={proc.returncode})\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )

    def reportinfo(self):
        return self.path, 0, f"standalone suite: {self.path.name}"


def pytest_pycollect_makemodule(module_path, parent):
    """Replace Python import/collection with one real subprocess item per suite."""
    if module_path.name in STANDALONE_SUITES:
        return StandaloneSuite.from_parent(parent, path=module_path)
    return None
