"""Hermes /api/ws JSON-RPC contract — pin-bump gate for the Hermes chat lane.

The bridge's Hermes lane (bridge/app.py, FABLE-HERMES-LANE-SPEC.md PATH A)
speaks Hermes's UPSTREAM-INTERNAL TUI-gateway protocol over the dashboard's
/api/ws WebSocket. Upstream makes no stability promise for these method /
event names, so every Hermes pin-bump MUST pass this purely-static check —
it greps the vendored source for each name the adapter depends on and fails
loudly if a future tag renames or removes one.

Run: pytest bridge/contract_tests/ (from harness root). No network, no build.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "vendor" / "hermes"

# JSON-RPC methods the bridge adapter calls (dispatched via tui_gateway).
WS_METHODS = [
    "session.create",     # methods_session.py — new gateway session
    "session.list",       # methods_session.py — stored-session list (Phase 3 rail)
    "session.history",    # methods_session.py — transcript read (Phase 3 hook)
    "prompt.submit",      # methods_prompt.py  — start a turn (returns status: streaming)
    "approval.respond",   # methods_prompt.py  — Phase-1 auto-deny / Phase-2 chip
]

# Event types the bridge translates into panel SSE frames (emitted via
# server.py _emit / _event_frame with params {type, session_id, payload}).
WS_EVENTS = [
    "message.delta",
    "reasoning.delta",
    "thinking.delta",
    "tool.start",
    "tool.complete",
    "approval.request",
    "message.complete",
    "status.update",
    "gateway.ready",
]


def _gateway_source() -> str:
    """Concatenated tui_gateway sources (the whole protocol lives there)."""
    parts = []
    for f in sorted((HERMES / "tui_gateway").glob("*.py")):
        parts.append(f.read_text(errors="replace"))
    return "\n".join(parts)


def test_ws_route_and_token_env_exist():
    if not HERMES.exists():
        return  # submodule not checked out — nothing to gate
    ws_server = (HERMES / "hermes_cli" / "web_server.py").read_text(errors="replace")
    assert '@app.websocket("/api/ws")' in ws_server, (
        "Hermes no longer mounts the JSON-RPC gateway at /api/ws — "
        "the bridge Hermes lane needs rewiring")
    assert "HERMES_DASHBOARD_SESSION_TOKEN" in ws_server, (
        "Hermes no longer seeds _SESSION_TOKEN from HERMES_DASHBOARD_SESSION_TOKEN — "
        "start_component.sh's deterministic-token trick is broken")
    # the loopback WS auth path the bridge uses: ?token=<_SESSION_TOKEN>
    assert 'ws.query_params.get("token"' in ws_server, (
        "the ?token= WS auth query param disappeared from web_server.py")


def test_ws_methods_still_registered():
    if not HERMES.exists():
        return
    src = _gateway_source()
    missing = [m for m in WS_METHODS if f'"{m}"' not in src]
    assert not missing, f"tui_gateway lost JSON-RPC method(s): {missing}"


def test_ws_events_still_emitted():
    if not HERMES.exists():
        return
    src = _gateway_source()
    missing = [e for e in WS_EVENTS if f'"{e}"' not in src]
    assert not missing, f"tui_gateway lost event type(s): {missing}"


def test_event_frame_shape_unchanged():
    """The adapter multiplexes on params.session_id of {"method": "event"} frames."""
    if not HERMES.exists():
        return
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    assert '"method": "event"' in server, (
        "gateway event frames no longer use method=event — bridge demux broken")
    assert '"session_id": sid' in server, (
        "gateway event frames no longer carry params.session_id — bridge demux broken")
