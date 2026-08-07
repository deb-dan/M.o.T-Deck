"""Contract tests — the gate every upstream update must pass (docs §6.1).

Run: pytest bridge/contract_tests/ (from harness root, bridge venv active).
M0: structural checks only. M1 adds live seam tests (MCP round-trip, smoke chat).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_harness_yaml_parses():
    c = yaml.safe_load((ROOT / "harness.yaml").read_text())
    # voicestudio + voicebox (2026-08-07) are OPTIONAL — present in the manifest,
    # installed:false by default and depended on by nothing.
    assert set(c["components"]) == {
        "hermes", "odysseus", "searxng", "voicestudio", "voicebox"}
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


# ── MCP registration seam ────────────────────────────────────────────────────
# The Browse toggle AND both voice components (Phase 3) register an MCP server the
# same two ways: Odysseus's form endpoint, and a yaml entry in ~/.hermes/config.yaml.
# These pin the exact wire shapes bridge/app.py emits (voice_mcp_spec + _BROWSERMCP
# + _hermes_write_mcp) so a pin-bump that renames a field trips HERE, not silently in
# a chat turn six weeks later.

def test_odysseus_mcp_register_form_contract():
    routes = ROOT / "vendor" / "odysseus" / "routes" / "mcp_routes.py"
    if not routes.exists():
        return
    src = routes.read_text(errors="replace")
    assert '@router.post("/servers")' in src, (
        "POST /api/mcp/servers is gone — bridge voice_toggle / browse_toggle / "
        "ody_mcp_add all register through it")
    assert '@router.delete("/servers/{server_id}")' in src, (
        "DELETE /api/mcp/servers/{id} is gone — it is how we UNregister a server")
    assert 'APIRouter(prefix="/api/mcp"' in src, (
        "the /api/mcp prefix moved — every bridge MCP call hard-codes it")
    # The exact Form fields we send for an http-transport server.
    for field in ("name: str = Form(", "transport: str = Form(", "url: str = Form("):
        assert field in src, (
            f"add_server no longer takes `{field.split(':')[0]}` as a form field — "
            "bridge/app.py posts name/transport/url (+args/env) form-encoded")
    assert 'transport == "http"' in src, (
        "the 'http' transport value is gone — voice_mcp_spec sends transport=http "
        "with the component's streamable-HTTP /mcp url")
    assert '"url": srv.url' in src, (
        "GET /api/mcp/servers no longer reports each server's url — voice_toggle "
        "compares it to detect a STALE registration (port changed in harness.yaml)")


def test_hermes_mcp_url_entry_contract():
    cfgmod = ROOT / "vendor" / "hermes" / "hermes_cli" / "mcp_config.py"
    if not cfgmod.exists():
        return
    src = cfgmod.read_text(errors="replace")
    assert 'server_config["url"] = url' in src, (
        "Hermes no longer accepts a url-only mcp_servers entry — _hermes_write_mcp "
        "writes {'url': 'http://127.0.0.1:<port>/mcp'} for the voice components")
    assert "mcp_servers" in src, (
        "the mcp_servers config key moved — the whole yaml round-trip depends on it")
    tool = ROOT / "vendor" / "hermes" / "tools" / "mcp_tool.py"
    if tool.exists():
        t = tool.read_text(errors="replace")
        assert "streamable_http" in t, (
            "Hermes dropped the streamable-HTTP MCP client — both voice components "
            "mount FastMCP's streamable-HTTP transport at /mcp (no stdio option we use)")
