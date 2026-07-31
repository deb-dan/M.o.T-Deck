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
    "session.history",    # methods_session.py — transcript read (live sessions)
    "session.resume",     # methods_session.py — reopen a STORED session (Phase 3)
    "session.delete",     # methods_session.py — delete a stored session (Phase 3)
    "session.close",      # methods_session.py — close a live session pre-delete (Phase 3)
    "prompt.submit",      # methods_prompt.py  — start a turn (returns status: streaming)
    "approval.respond",   # methods_prompt.py  — Phase-2 approval card answer
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


def test_approval_protocol_contract():
    """Phase-2 approval chip contract (bridge/app.py + panel approval cards).

    The card renders approval.request payload.command + payload.choices, and
    /api/hermes/approve sends approval.respond {session_id, choice}. Gate the
    exact key names + the two safety behaviors the UX leans on: upstream
    command redaction (#48456) and interrupt-auto-denies-pending (#8697).
    """
    if not HERMES.exists():
        return
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    # payload keys the panel card consumes
    assert "_emit_approval_request" in server, (
        "approval.request emit seam (_emit_approval_request) moved — re-recon")
    assert 'payload["choices"]' in server, (
        "approval.request payload no longer carries a choices list")
    assert "_redact_approval_command" in server, (
        "approval command redaction seam gone — the WS egress could echo "
        "credentials verbatim (#48456); re-verify before bumping")
    prompt = (HERMES / "tui_gateway" / "methods_prompt.py").read_text(errors="replace")
    # approval.respond params: {session_id (via _sess), choice, all?}
    assert 'params.get("choice"' in prompt, (
        "approval.respond no longer reads params.choice")
    assert 'params.get("all"' in prompt, (
        "approval.respond lost its resolve-all flag (bridge doesn't send it, "
        "but the param shape changed — re-recon)")
    assert "resolve_gateway_approval" in prompt, (
        "approval.respond no longer resolves via resolve_gateway_approval")
    appr = (HERMES / "tools" / "approval.py").read_text(errors="replace")
    assert "resolve_gateway_approval" in appr
    assert "is_interrupted()" in appr, (
        "approval wait no longer checks is_interrupted() — panel Stop during a "
        "pending card would wedge until the approval timeout (#8697 regressed)")


def test_event_frame_shape_unchanged():
    """The adapter multiplexes on params.session_id of {"method": "event"} frames."""
    if not HERMES.exists():
        return
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    assert '"method": "event"' in server, (
        "gateway event frames no longer use method=event — bridge demux broken")
    assert '"session_id": sid' in server, (
        "gateway event frames no longer carry params.session_id — bridge demux broken")


def test_session_rail_contract():
    """Phase-3 session-rail parity — the exact result-shape keys the bridge reads.

    session.list rows: {id,title,preview,started_at,message_count,source}
    (methods_session.py ~196-206; hermes_sessions_normalize consumes them).
    session.resume: the bridge reads session_id / session_key / resumed /
    messages / running from every branch (lazy, deferred, live-reuse via
    _live_session_payload). Rename has NO WS method for stored sessions — the
    bridge uses REST PATCH /api/sessions/{id} with the X-Hermes-Session-Token
    header (web_routers/sessions.py:650, web_server.py:305)."""
    if not HERMES.exists():
        return
    msess = (HERMES / "tui_gateway" / "methods_session.py").read_text(errors="replace")
    # session.list row keys
    for key in ('"title"', '"preview"', '"started_at"', '"message_count"', '"source"'):
        assert key in msess, f"session.list row key {key} gone — rail normalizer broken"
    # session.resume result keys (lazy/deferred branches build these dicts)
    for key in ('"session_id"', '"resumed"', '"messages"', '"running"', '"session_key"'):
        assert key in msess, f"session.resume payload key {key} gone — resume flow broken"
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    assert "_history_to_messages" in server, (
        "transcript projection (_history_to_messages) moved — "
        "hermes_messages_to_panel's input shape needs re-recon")
    assert "def _live_session_payload" in server, (
        "live-reuse resume payload builder gone — re-recon resume fast path")
    # stored-session rename = REST PATCH (the lane's one REST call)
    rest = (HERMES / "hermes_cli" / "web_routers" / "sessions.py").read_text(errors="replace")
    assert '@manage_router.patch("/api/sessions/{session_id}")' in rest, (
        "REST rename endpoint gone — Hermes rail rename broken")
    ws_server = (HERMES / "hermes_cli" / "web_server.py").read_text(errors="replace")
    assert 'X-Hermes-Session-Token' in ws_server, (
        "REST session-token header renamed — bridge rename call broken")


def test_approvals_default_mode_contract():
    """Upstream's DEFAULT approvals.mode governs whether dangerous commands are
    silently guardian-approved (smart) or always carded (manual). A silent
    upstream default change would alter the gate without any code change on our
    side (live incident 2026-07-31: rm -rf auto-approved under default smart).
    Flag it at pin-bump time."""
    import re
    src = (HERMES / "hermes_cli" / "config_defaults.py").read_text()
    m = re.search(r'"approvals"\s*:\s*\{.*?"mode"\s*:\s*"(\w+)"', src, re.S)
    assert m, "approvals.mode default missing from config_defaults.py"
    assert m.group(1) == "smart", (
        f"upstream default approvals.mode changed: now {m.group(1)!r} (was 'smart') — "
        "re-check the approval-card flow + docs")
