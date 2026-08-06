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


def test_file_card_signal_contract():
    """§F file-card auto-trigger — the exact upstream keys the bridge mapper
    reads from tool.complete to emit {"type":"file_card"} frames.

    tool.complete payload carries name/args/result (server.py _on_tool_complete
    ~5044-5088: payload["result"] = json.loads(result) when parseable). On a
    SUCCESSFUL write_file/patch, file_tools.py stamps the ABSOLUTE path(s) into
    result: resolved_path (:1630 write / :1789 single-file patch) and
    files_modified (:1632 / :1787, list — multi-file V4A). Errors carry an
    "error" key (tool_error). If any of these move, the panel silently stops
    showing produced-file cards — fail loudly at pin-bump instead."""
    if not HERMES.exists():
        return
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    assert "def _on_tool_complete" in server, (
        "tool.complete emit seam (_on_tool_complete) moved — re-recon file cards")
    assert '"name": name, "args": args' in server, (
        "tool.complete payload no longer carries name/args — file-card mapper broken")
    assert 'payload["result"] = json.loads(result)' in server, (
        "tool.complete result is no longer json-parsed — success detection broken")
    ftools = (HERMES / "tools" / "file_tools.py").read_text(errors="replace")
    assert 'result_dict["resolved_path"]' in ftools, (
        "write_file/patch no longer report resolved_path — file-card path source gone")
    assert 'result_dict["files_modified"]' in ftools, (
        "write_file/patch no longer report files_modified — file-card path source gone")
    assert 'registry.register(name="write_file"' in ftools, (
        "write_file tool registration moved/renamed — re-recon")


def test_path_guard_hook_contract():
    """PATH-GUARD FENCE (guards/harness-path-guard + bridge audit tier).

    Our plugin enforces write-path policy through upstream's ``pre_tool_call``
    hook: an ``{"action": "approve"}`` directive escalates the call into the SAME
    human gate dangerous shell commands use, so the panel's Phase-2 card renders
    it. That seam is upstream-internal — if a pin-bump renames the hook, drops the
    directive vocabulary, or stops resolving it on the dashboard tool path, the
    fence silently stops fencing. Fail loudly here instead.
    """
    if not HERMES.exists():
        return
    plugins = (HERMES / "hermes_cli" / "plugins.py").read_text(errors="replace")
    assert '"pre_tool_call",' in plugins, (
        "pre_tool_call is no longer a VALID_HOOKS entry — path-guard has no seam")
    # directive vocabulary the plugin returns
    assert 'action not in ("block", "approve")' in plugins, (
        "pre_tool_call directive vocabulary changed (block/approve) — re-recon")
    assert 'result.get("action")' in plugins, (
        "directive is no longer read from the hook's returned dict['action']")
    assert 'result.get("message")' in plugins, (
        "directive 'message' key gone — block/approve reasons would vanish")
    assert 'result.get("rule_key")' in plugins, (
        "directive 'rule_key' key gone — 'Always' approvals lose their grain")
    # the resolver that turns an approve directive into the human gate
    assert "def resolve_pre_tool_block" in plugins, (
        "resolve_pre_tool_block gone — approve directives would no longer reach "
        "the approval gate")
    assert "from tools.approval import request_tool_approval" in plugins, (
        "resolve_pre_tool_block no longer calls request_tool_approval — plugin "
        "escalations would not open an approval card")
    appr = (HERMES / "tools" / "approval.py").read_text(errors="replace")
    assert "def request_tool_approval" in appr, (
        "request_tool_approval gone from tools/approval.py — fence has no gate")
    assert "plugin_rule:" in appr, (
        "plugin-rule allowlist namespace changed — 'Always' persistence grain moved")
    # user-plugin discovery + the opt-in allow-list key start_component.sh writes
    assert 'get_hermes_home() / "plugins"' in plugins, (
        "user plugins are no longer discovered under ~/.hermes/plugins — the "
        "seeding step in start_component.sh needs rewiring")
    assert "def _get_enabled_plugins" in plugins and '"enabled" not in plugins_cfg' in plugins, (
        "plugins.enabled allow-list handling changed — the seeded plugin may not load")
    assert 'ctx.register_hook("pre_tool_call"' in (
        HERMES / "plugins" / "security-guidance" / "__init__.py").read_text(errors="replace"), (
        "the bundled reference plugin no longer registers pre_tool_call via "
        "ctx.register_hook — our register(ctx) shape may be stale")
    # the tool-dispatch path the dashboard uses must still resolve the hook
    mtools = (HERMES / "model_tools.py").read_text(errors="replace")
    assert "discover_plugins" in mtools, (
        "model_tools no longer discovers plugins on import — the dashboard path "
        "would never load the path-guard plugin")
    assert "resolve_pre_tool_block" in mtools, (
        "model_tools no longer resolves pre_tool_call directives — writes unfenced")
    # the two tools the fence gates must still exist under these names
    ftools = (HERMES / "tools" / "file_tools.py").read_text(errors="replace")
    assert 'registry.register(name="write_file"' in ftools
    assert 'registry.register(name="patch"' in ftools, (
        "the patch tool was renamed — path-guard's GATED_TOOLS needs updating")


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
