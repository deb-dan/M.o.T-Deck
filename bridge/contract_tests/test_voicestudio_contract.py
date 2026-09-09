"""VoiceStudio contract — pin-bump gate for the optional voice component.

VoiceStudio (github.com/debpalash/VoiceStudio, AGPL-3.0-only, pinned in motdeck.yaml)
is composed over HTTP only — we never modify it. But scripts/start_component.sh and
bridge/app.py hard-depend on four upstream facts that VoiceStudio does not promise:

  1. the ASGI entrypoint is `app` in `backend/main.py` (we launch
     `uvicorn backend.main:app` with cwd=vendor/voicestudio)
  2. the bind host / port are overridable via OMNIVOICE_BIND_HOST / OMNIVOICE_PORT
     (the project was renamed from "OmniVoice Studio"; internals keep the prefix)
  3. `GET /health` exists — it is the readiness probe the start script polls
  4. the built SPA is mounted from `frontend/dist`, and the MCP server is mounted at
     `/mcp` (Phase 3 registers that endpoint with Hermes/Odysseus)

Purely static: greps the vendored source — the package's own deps (torch, whisperx…)
are NOT importable from the bridge venv, so nothing here imports it.

Run: pytest bridge/contract_tests/
"""
import pytest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VS = ROOT / "vendor" / "voicestudio"
MAIN = VS / "backend" / "main.py"


def _present() -> bool:
    """The component is OPTIONAL — skip cleanly when it isn't checked out."""
    return MAIN.exists()


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def test_voicestudio_pinned_in_motdeck_yaml():
    """Always runs: the pin/port/optionality contract is ours, not upstream's."""
    c = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    comp = c["components"].get("voicestudio")
    assert comp, "components.voicestudio disappeared from motdeck.yaml"
    assert comp["pin"] and comp["pin"] != "main", (
        "voicestudio must be pinned to a release tag, never a branch")
    assert int(comp["port"]) == 3900, (
        "voicestudio port changed — start_component.sh reads it from motdeck.yaml but "
        "the plan text / notes in bridge/app.py still say 3900")
    assert comp.get("depends_on") in (None, []), (
        "voicestudio must stay dependency-free — it is optional and must never be "
        "pulled into another component's start closure")


def test_asgi_entrypoint_exists():
    if not _present():
        pytest.skip("optional upstream source is absent: not _present()")
    src = _read(MAIN)
    assert "app = FastAPI(" in src or "app: FastAPI" in src or "\napp = " in src, (
        "backend/main.py no longer defines a module-level `app` — "
        "start_component.sh launches `uvicorn backend.main:app`")


def test_bind_env_vars_still_honoured():
    if not _present():
        pytest.skip("optional upstream source is absent: not _present()")
    src = _read(MAIN)
    for var in ("OMNIVOICE_BIND_HOST", "OMNIVOICE_PORT"):
        assert var in src, (
            f"backend/main.py no longer reads {var} — start_component.sh sets it to pin "
            "the process to 127.0.0.1 and motdeck.yaml port. (The project was "
            "renamed from OmniVoice Studio; a rename of the env prefix breaks us.)")


def test_health_route_registered():
    if not _present():
        pytest.skip("optional upstream source is absent: not _present()")
    src = _read(MAIN)
    assert '"/health"' in src or "'/health'" in src, (
        "GET /health is gone — it is the readiness probe start_component.sh polls "
        "for up to ~5 minutes before declaring the component failed")


def test_spa_mounted_from_frontend_dist():
    if not _present():
        pytest.skip("optional upstream source is absent: not _present()")
    src = _read(MAIN)
    assert "frontend" in src and "dist" in src, (
        "backend/main.py no longer references frontend/dist — the install script "
        "builds the SPA there and the backend is what serves it on the same port")


def test_mcp_mounted():
    if not _present():
        pytest.skip("optional upstream source is absent: not _present()")
    src = _read(MAIN)
    assert '"/mcp"' in src or "'/mcp'" in src or "OMNIVOICE_MCP_DISABLE" in src, (
        "the in-process MCP server at /mcp is gone — Phase 3 registers exactly that "
        "endpoint with Hermes and Odysseus")


# ── Phase 3: the exact MCP endpoint + LLM env we wire ────────────────────────

MCP_SRV = VS / "backend" / "mcp_server.py"
LLM_PROVIDERS = VS / "backend" / "services" / "llm_providers.py"


def test_mcp_endpoint_is_exactly_slash_mcp():
    """bridge/app.py VOICE_MCP registers http://127.0.0.1:<port>/mcp verbatim in both
    hosts. That is only correct because upstream sets FastMCP's own
    streamable_http_path to "/" before sub-mounting the app at "/mcp" — without that
    the real endpoint would be /mcp/mcp and every agent call would 404."""
    if not _present() or not MCP_SRV.exists():
        pytest.skip("optional upstream source is absent: not _present() or not MCP_SRV.exists()")
    src = _read(MCP_SRV)
    assert 'app.mount("/mcp"' in src, (
        "mount_mcp no longer mounts the MCP app at /mcp — update VOICE_MCP['voicestudio']"
        "['path'] in bridge/app.py")
    assert "streamable_http_path" in src, (
        "the streamable_http_path override is gone — the endpoint may now be /mcp/mcp; "
        "re-derive the url in bridge/app.py voice_mcp_spec()")


def test_mcp_tools_still_named_as_advertised():
    """The Capabilities panel lists these names for the VoiceStudio row (display
    only — the hosts discover the real list themselves), so a rename is cosmetic
    drift we still want to hear about at pin-bump."""
    if not _present() or not MCP_SRV.exists():
        pytest.skip("optional upstream source is absent: not _present() or not MCP_SRV.exists()")
    src = _read(MCP_SRV)
    for tool in ("generate_speech", "clone_voice", "transcribe", "list_voices",
                 "list_personalities", "list_languages", "check_health"):
        assert f"def {tool}(" in src, (
            f"MCP tool '{tool}' disappeared — update VOICE_MCP['voicestudio']['tools']")


def test_mcp_callback_base_url_env():
    """The MCP tools call BACK into this same backend over HTTP and default to
    http://localhost:3900. start_component.sh pins OMNIVOICE_API_URL to the port we
    actually bound, so a non-default port can't silently break every tool call."""
    if not _present() or not MCP_SRV.exists():
        pytest.skip("optional upstream source is absent: not _present() or not MCP_SRV.exists()")
    assert "OMNIVOICE_API_URL" in _read(MCP_SRV), (
        "OMNIVOICE_API_URL is no longer how the MCP tools find their own backend — "
        "the env export in start_component.sh's voicestudio branch needs updating")


def test_per_agent_voice_binding_is_header_only():
    """Documented honest limit: the per-agent voice binding is read from a REQUEST
    HEADER, and neither Hermes nor Odysseus lets us attach custom headers to an http
    MCP entry — so our calls use the global default voice. If upstream ever accepts
    the client id another way (a query param, a tool arg), revisit VOICE_MCP's note."""
    if not _present() or not MCP_SRV.exists():
        pytest.skip("optional upstream source is absent: not _present() or not MCP_SRV.exists()")
    assert "x-omnivoice-client-id" in _read(MCP_SRV).lower(), (
        "the X-OmniVoice-Client-Id binding header changed — the caveat shown in the "
        "Capabilities panel (VOICE_MCP['voicestudio']['note']) is now wrong")


def test_llm_custom_provider_env_triplet():
    """start_component.sh points VoiceStudio's optional LLM at OUR runner by exporting
    the `custom` (OpenAI-compatible) provider's env triplet. All three names, plus the
    resolution order, are upstream's — pin them."""
    if not _present() or not LLM_PROVIDERS.exists():
        pytest.skip("optional upstream source is absent: not _present() or not LLM_PROVIDERS.exists()")
    src = _read(LLM_PROVIDERS)
    for env in ("TRANSLATE_BASE_URL", "TRANSLATE_API_KEY", "TRANSLATE_MODEL"):
        assert env in src, (
            f"{env} is no longer a recognised env override — start_component.sh's "
            "voicestudio branch exports it to aim the LLM at MOT Deck runner")
    assert "def resolve_base_url" in src and "def resolve_model" in src, (
        "the provider field resolver moved — env-first precedence is what makes our "
        "start-time export work at all")
    assert "def stored_active_provider_id" in src, (
        "the stored-selection accessor is gone. We deliberately do NOT set "
        "LLM_DEFAULT_PROVIDER so a provider chosen in VoiceStudio's own Settings "
        "still outranks our TRANSLATE_BASE_URL default — that precedence just changed.")
