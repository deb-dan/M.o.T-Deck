"""Contract tests — the gate every upstream update must pass (docs §6.1).

Run: pytest bridge/contract_tests/ (from harness root, bridge venv active).
M0: structural checks only. M1 adds live seam tests (MCP round-trip, smoke chat).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_harness_yaml_parses():
    c = yaml.safe_load((ROOT / "harness.yaml").read_text())
    # voicestudio + voicebox (2026-08-07) and comfyui + unsloth (2026-08-20) are
    # OPTIONAL — present in the manifest, installed:false by default, depended on by
    # nothing, and never cloned by bootstrap (install_component.sh shallow-clones them
    # itself, the searxng precedent).
    assert set(c["components"]) == {
        "hermes", "odysseus", "searxng", "voicestudio", "voicebox",
        "comfyui", "unsloth"}
    for comp in c["components"].values():
        assert comp["pin"], "every component must be pinned"
    for name in ("voicestudio", "voicebox", "comfyui", "unsloth"):
        comp = c["components"][name]
        assert comp["installed"] is False, f"{name} is OPTIONAL — it must ship installed:false"
        assert comp["depends_on"] == [], f"{name} must not be a dependency edge"
        assert isinstance(comp["port"], int), f"{name} needs a port the start script can read"
    # Ports are single-sourced here and read by start_component.sh's awk; a collision
    # would make two components fight over one listener.
    ports = [comp["port"] for comp in c["components"].values() if comp.get("port")]
    assert len(ports) == len(set(ports)), f"duplicate component port in harness.yaml: {ports}"


def test_optional_components_are_not_submodules():
    """The four optional components must NEVER be in .gitmodules: bootstrap clones its
    submodule list unconditionally, so a multi-GB optional dep listed there would be
    dragged into every fresh clone (the searxng precedent, restated as a gate)."""
    gm = ROOT / ".gitmodules"
    if not gm.exists():
        return
    src = gm.read_text(errors="replace")
    for name in ("voicestudio", "voicebox", "comfyui", "unsloth"):
        assert f"vendor/{name}" not in src, (
            f"{name} became a submodule — it must stay a shallow clone made by "
            "install_component.sh, or bootstrap will pull it for everyone")


def test_comfyui_entrypoint_and_flags_contract():
    """Pins what scripts/start_component.sh's comfyui branch depends on. Skips cleanly
    until the optional component is installed."""
    vendor = ROOT / "vendor" / "comfyui"
    if not (vendor / "main.py").exists():
        return
    args = (vendor / "comfy" / "cli_args.py").read_text(errors="replace")
    for flag in ('"--listen"', '"--port"', '"--disable-auto-launch"'):
        assert flag in args, f"ComfyUI no longer accepts {flag} — the start script passes it"
    assert '"--base-directory"' in args, (
        "ComfyUI dropped --base-directory: without it models/output/input/user are "
        "created next to main.py, i.e. INSIDE vendor/ (the voicebox --data-dir trap)")
    server = (vendor / "server.py").read_text(errors="replace")
    assert '"/system_stats"' in server, (
        "the /system_stats route is gone — it is the start script's health probe")


def test_unsloth_studio_entrypoint_contract():
    """Pins what scripts/start_component.sh's unsloth branch depends on. Skips cleanly
    until the optional component is installed."""
    vendor = ROOT / "vendor" / "unsloth"
    run = vendor / "studio" / "backend" / "run.py"
    if not run.exists():
        return
    pyproject = (vendor / "pyproject.toml").read_text(errors="replace")
    assert 'unsloth = "unsloth_cli:app"' in pyproject, (
        "the `unsloth` console script moved — the start script runs `unsloth studio` "
        "and falls back to `python -m unsloth_cli`")
    assert "studio = [" in pyproject, (
        "the [studio] optional-dependency extra is gone — install_component.sh installs "
        "exactly `vendor/unsloth[studio]` and nothing heavier")
    studio_cli = (vendor / "unsloth_cli" / "commands" / "studio.py").read_text(errors="replace")
    assert "@studio_app.callback(invoke_without_command = True)" in studio_cli, (
        "`unsloth studio` with no subcommand no longer starts the server — that plain "
        "form is chosen deliberately over `unsloth studio run`, which installs a "
        "process-global tools-ON policy")
    src = run.read_text(errors="replace")
    assert "def _missing_frontend_is_fatal" in src, (
        "the fatal-missing-frontend rule moved; start_component.sh refuses up front "
        "when studio/frontend/dist/index.html is absent because of it")
    assert '@app.get("/api/health")' in (
        vendor / "studio" / "backend" / "main.py").read_text(errors="replace"), (
        "/api/health is gone — it is the start script's health probe")
    # The password gate / bootstrap auto-shutdown must stay scoped to a PUBLISHED launch:
    # our loopback launch has no terminal, and if that ever became a hard gate the tab
    # would silently never come up.
    assert "if not tunnel_will_start:" in src, (
        "the terminal password gate is no longer scoped to a tunnelled launch — a "
        "headless loopback start may now block on a prompt")


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
