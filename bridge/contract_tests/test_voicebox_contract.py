"""Voicebox contract — pin-bump gate for the second optional voice component.

Voicebox (github.com/jamiepine/voicebox, MIT, pinned in motdeck.yaml) is composed
over HTTP only — we never modify it. But scripts/start_component.sh and bridge/app.py
hard-depend on upstream facts Voicebox does not promise:

  1. `backend/main.py` is the launch module — we run `python -m backend.main`
     (NOT plain uvicorn) because that entry point calls config.set_data_dir() and
     database.init_db() before serving. It re-exports the ASGI app from backend/app.py.
  2. it accepts `--host`, `--port` and `--data-dir`. ⚠️ Its argparse default port is
     **8000**, not 17493 — 17493 is only a project convention (the justfile / CORS
     allow-list). start_component.sh therefore ALWAYS passes --port explicitly.
     `--data-dir` is equally load-bearing: the default is Path("data") resolved against
     the CWD, which would write the DB + audio into vendor/voicebox.
  3. `GET /health` exists — it is the readiness probe the start script polls.
  4. the MCP server is mounted at `/mcp` (Phase 3 registers exactly that endpoint) and
     the built SPA is served from `<repo-root>/frontend` (the install script copies
     web/dist there — no non-Docker path of upstream's own creates that directory).

Purely static: greps the vendored source — the package's own deps (torch, kokoro…)
are NOT importable from the bridge venv, so nothing here imports it.

Run: pytest bridge/contract_tests/
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VB = ROOT / "vendor" / "voicebox"
MAIN = VB / "backend" / "main.py"
APP = VB / "backend" / "app.py"


def _present() -> bool:
    """The component is OPTIONAL — skip cleanly when it isn't checked out."""
    return MAIN.exists()


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def test_voicebox_pinned_in_motdeck_yaml():
    """Always runs: the pin/port/optionality contract is ours, not upstream's."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    comp = c["components"].get("voicebox")
    assert comp, "components.voicebox disappeared from motdeck.yaml"
    assert comp["pin"] and comp["pin"] not in ("main", "master"), (
        "voicebox must be pinned to a release tag, never a branch")
    assert int(comp["port"]) == 17493, (
        "voicebox port changed — start_component.sh reads it from motdeck.yaml but the "
        "plan text / notes in bridge/app.py still say 17493, and upstream's CORS "
        "allow-list only whitelists 17493")
    assert comp.get("depends_on") in (None, []), (
        "voicebox must stay dependency-free — it is optional and must never be pulled "
        "into another component's start closure")
    assert comp.get("installed") is False, (
        "voicebox ships NOT installed: it is optional, several GB, and its dependency "
        "graph is known-fragile")


def test_launch_module_exists_and_reexports_app():
    if not _present():
        return  # optional component not installed — nothing to gate
    src = _read(MAIN)
    assert "app" in src, "backend/main.py no longer references the ASGI app"
    assert APP.exists(), (
        "backend/app.py is gone — backend/main.py re-exports its `app` and "
        "start_component.sh launches `python -m backend.main`")
    assert "app = create_app()" in _read(APP) or "\napp = " in _read(APP), (
        "backend/app.py no longer defines a module-level `app`")


def test_main_is_runnable_as_a_module():
    if not _present():
        return
    src = _read(MAIN)
    assert '__name__ == "__main__"' in src or "__name__ == '__main__'" in src, (
        "backend/main.py lost its __main__ block — start_component.sh runs "
        "`python -m backend.main`, which would then serve nothing")


def test_host_port_and_data_dir_flags_exist():
    if not _present():
        return
    src = _read(MAIN)
    for flag in ("--host", "--port", "--data-dir"):
        assert flag in src, (
            f"backend/main.py no longer accepts {flag} — start_component.sh passes all "
            "three (port because the default is 8000, data-dir because the default "
            "resolves against the CWD and would write inside vendor/)")
    assert "default=8000" in src.replace(" ", "") or "default=17493" in src.replace(" ", ""), (
        "the --port default changed shape; we pass --port explicitly either way, but "
        "this pin documents that 17493 is OUR choice and not upstream's default")


def test_health_route_registered():
    if not _present():
        return
    health = VB / "backend" / "routes" / "health.py"
    src = _read(health) if health.exists() else ""
    assert '"/health"' in src or "'/health'" in src, (
        "GET /health is gone (backend/routes/health.py) — it is the readiness probe "
        "start_component.sh polls for up to ~5 minutes before declaring a failure")


def test_mcp_mounted():
    if not _present():
        return
    src = _read(APP) if APP.exists() else ""
    assert '"/mcp"' in src or "'/mcp'" in src, (
        "the in-process MCP server at /mcp is gone — Phase 3 registers exactly that "
        "endpoint with Hermes and Odysseus")


def test_mcp_is_streamable_http_at_the_mount_root():
    """bridge/app.py VOICE_MCP registers http://127.0.0.1:<port>/mcp verbatim with both
    hosts, over the streamable-HTTP transport. Two upstream facts hold that up: the
    app is FastMCP-based, and the ASGI app it mounts is the streamable-HTTP one (an
    SSE-only mount would need transport='sse' in the Odysseus form instead)."""
    if not _present():
        return
    src = _read(APP) if APP.exists() else ""
    hay = src + "".join(
        _read(p) for p in (VB / "backend").rglob("*mcp*.py") if p.is_file())
    assert "FastMCP" in hay or "fastmcp" in hay, (
        "voicebox no longer builds its MCP server with FastMCP — re-derive the "
        "endpoint + transport in bridge/app.py voice_mcp_spec()")
    assert "streamable_http" in hay or "streamable-http" in hay, (
        "the streamable-HTTP transport is gone — voice_mcp_spec sends transport=http "
        "to Odysseus and a url-only entry to Hermes, both of which mean streamable HTTP")


def test_mcp_tool_names_for_the_panel():
    """Display-only: the Capabilities row lists these names. Recon reported the
    `voicebox.` prefix; this trips if that changes so the panel stops lying.
    ⚠️ Unverifiable until the component is actually checked out (skips otherwise)."""
    if not _present():
        return
    hay = "".join(_read(p) for p in (VB / "backend").rglob("*mcp*.py") if p.is_file())
    if not hay:
        return
    for tool in ("speak", "transcribe", "list_captures", "list_profiles"):
        assert tool in hay, (
            f"MCP tool '{tool}' disappeared — update VOICE_MCP['voicebox']['tools'] "
            "in bridge/app.py")


def test_spa_served_from_repo_root_frontend():
    if not _present():
        return
    src = _read(APP) if APP.exists() else ""
    assert "frontend" in src, (
        "backend/app.py no longer mounts a frontend directory — the install script "
        "copies web/dist to <repo-root>/frontend precisely because that is the only "
        "place this backend looks for a built SPA")


def test_no_auth_assumption_still_holds():
    """We bind loopback-only BECAUSE there is no auth. If upstream ever adds one this
    trips, and the note/plan wording in bridge/app.py should be revisited."""
    if not _present():
        return
    src = _read(APP) if APP.exists() else ""
    assert "AuthenticationMiddleware" not in src and "HTTPBearer" not in src, (
        "voicebox appears to have gained authentication — update the NO AUTH warnings "
        "in motdeck.yaml / install_component.sh / bridge/app.py _NOTES")
