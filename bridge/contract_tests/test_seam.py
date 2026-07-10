"""Contract tests — the gate every upstream update must pass (docs §6.1).

Run: pytest bridge/contract_tests/ (from harness root, bridge venv active).
M0: structural checks only. M1 adds live seam tests (MCP round-trip, smoke chat).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_harness_yaml_parses():
    c = yaml.safe_load((ROOT / "harness.yaml").read_text())
    assert set(c["components"]) == {"hermes", "odysseus"}
    for comp in c["components"].values():
        assert comp["pin"], "every component must be pinned"


def test_hermes_mcp_entrypoint_exists():
    """The adapter depends on hermes mcp_serve.py — fail loudly if upstream moves it."""
    vendor = ROOT / "vendor" / "hermes"
    if not vendor.exists():
        return  # not installed yet — skip in M0
    assert (vendor / "mcp_serve.py").exists(), (
        "hermes-agent no longer ships mcp_serve.py at repo root — adapter needs updating")


def test_odysseus_app_entrypoint_exists():
    vendor = ROOT / "vendor" / "odysseus"
    if not vendor.exists():
        return
    assert (vendor / "app.py").exists(), (
        "odysseus no longer ships app.py at repo root — start_component.sh needs updating")
