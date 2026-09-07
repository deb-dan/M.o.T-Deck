from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "normalize_ledger.py"


def _module():
    spec = importlib.util.spec_from_file_location("normalize_ledger", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_status_is_exhaustive_unique_and_matches_roadmap():
    module = _module()
    ledger = (ROOT / "docs" / "UNFORGET.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    groups = module.validate(ledger, roadmap)
    assert len(module.row_ids(ledger)) >= 205
    assert "P4" not in {item for group in groups.values() for item in group}
    assert "S31" not in {item for group in groups.values() for item in group}
    assert groups["next"][0] == "P6"


def test_visible_targets_are_the_normalized_current_status():
    module = _module()
    ledger = (ROOT / "docs" / "UNFORGET.md").read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{len(module.row_ids(ledger))} rows" in result.stdout
