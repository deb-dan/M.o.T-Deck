"""Hermes /api/ws JSON-RPC contract — pin-bump gate for the Hermes chat lane.

The bridge's Hermes lane (bridge/app.py, FABLE-HERMES-LANE-SPEC.md PATH A)
speaks Hermes's UPSTREAM-INTERNAL TUI-gateway protocol over the dashboard's
/api/ws WebSocket. Upstream makes no stability promise for these method /
event names, so every Hermes pin-bump MUST pass this purely-static check —
it greps the vendored source for each name the adapter depends on and fails
loudly if a future tag renames or removes one.

Run: pytest bridge/contract_tests/ (from harness root). No network, no build.
"""
import re
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
    "clarify.respond",    # methods_prompt.py  — ask-card answer (clarify tool)
    "session.interrupt",  # methods_session.py — panel Stop + the max-turn guard
    "session.active_list",# methods_session.py — the relay's liveness probe
    "image.attach_bytes", # methods_prompt.py  — the lane's ⊕ (2026-08-28); its params
                          # and its queue-onto-the-session behaviour are pinned in
                          # test_attach_lanes_contract.py
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
    "clarify.request",
    # NOTE: "clarify.expire" is deliberately NOT listed here — upstream never
    # writes that literal, it BUILDS it (`f"{event.removesuffix('.request')}.expire"`,
    # server.py:2892-2896). Pinned structurally in test_clarify_protocol_contract.
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


def test_active_list_status_vocabulary_is_unchanged():
    """The relay's liveness probe (`_hermes_session_working`, bridge/app.py) treats a
    session as ALIVE only when `session.active_list` reports one of
    waiting/starting/working — anything else (or absent) ends the turn with
    `· interrupted`. That vocabulary is upstream-INTERNAL, and a silent addition to
    it is a live-turn killer: a genuinely busy session reporting a status we do not
    recognise would be cut off mid-answer after the 20s silence tick.

    Our own source carried this as a recorded gap ("cover in pin-bump contract tests
    alongside the RPC names"); this is that cover. Verified unchanged at v2026.8.13.
    """
    if not HERMES.exists():
        return
    src = (HERMES / "tui_gateway" / "server.py").read_text(
        encoding="utf-8", errors="replace")
    i = src.index("def _session_live_status(")
    body = src[i:]
    body = body[:body.index("\ndef ", 10)]
    returned = set(re.findall(r'return "([a-z_]+)"', body))
    assert returned == {"waiting", "starting", "working", "idle"}, (
        f"session.active_list's status vocabulary changed: {sorted(returned)}. The "
        "bridge's liveness probe only accepts waiting/starting/working as ALIVE — a "
        "new busy status would make it end live turns; a removed one would make it "
        "hang. Reconcile _hermes_session_working before shipping this pin.")
    # and it is still what active_list actually reports
    ms = (HERMES / "tui_gateway" / "methods_session.py").read_text(
        encoding="utf-8", errors="replace")
    assert '@method("session.active_list")' in ms
    assert "_session_live_item(sid, session, current)" in ms, \
        "session.active_list no longer builds its rows from _session_live_item"
    assert '"status": status' in src, "the live-session row lost its status field"
    assert '"id": sid' in src, \
        "the live-session row lost its `id` — the probe matches our sid on it"


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


def test_clarify_protocol_contract():
    """ASK-CARD contract (bridge/app.py ask frames + panel chatAsk cards).

    The `clarify` tool BLOCKS the agent thread on a gateway prompt; without a
    surface for it a Hermes turn silently sits "working" until something times
    out (the live repro). Everything the card leans on is upstream-internal:

      * emit   — server.py:5376-5390 `clarify_callback` → `_block("clarify.request",
                 sid, {"question": q, "choices": c[, "multi_select": True]})`;
      * id     — `_block` mints one and stamps `payload["request_id"] = rid`
                 (server.py:2856-2862). UNLIKE approvals this IS on the wire, and
                 the whole card addressing depends on it;
      * expire — a timed-out prompt emits `<event>.expire` with {"request_id"}
                 (server.py:2886-2896), for the four blocking bridges whose
                 respond handler tolerates a late reply;
      * answer — `clarify.respond` → `_respond(rid, params, "answer",
                 allow_expired=True)` (methods_prompt.py:836-842), which resolves
                 on params["request_id"] alone and returns status ok|expired
                 (server.py:9981-9992). No session_id is involved;
      * free text — ALWAYS available: every renderer appends "Other (type your
                 answer)" (tools/clarify_tool.py:22) and a choice-less clarify is
                 open-ended by construction (:156-157).
    """
    if not HERMES.exists():
        return
    server = (HERMES / "tui_gateway" / "server.py").read_text(errors="replace")
    assert '"clarify_callback"' in server, (
        "the clarify_callback gateway wiring moved — ask cards have no source")
    assert '{"question": q, "choices": c}' in server, (
        "clarify.request payload keys changed (question/choices) — ask card blind")
    assert 'payload["request_id"] = rid' in server, (
        "_block no longer stamps request_id into the emitted payload — ask cards "
        "would have nothing to answer with (approvals-style FIFO is NOT available "
        "for clarify)")
    assert 'f"{event.removesuffix(\'.request\')}.expire"' in server, (
        "the *.expire notification for timed-out blocking prompts is gone — an "
        "expired ask card would keep claiming it is answerable")
    assert '"clarify.request",' in server, (
        "clarify.request dropped out of the expire-eligible blocking-bridge set")
    prompt = (HERMES / "tui_gateway" / "methods_prompt.py").read_text(errors="replace")
    assert re.search(r'@method\("clarify\.respond"\)', prompt), (
        "clarify.respond JSON-RPC method gone — ask cards cannot answer")
    assert '_respond(rid, params, "answer", allow_expired=True)' in prompt, (
        "clarify.respond's answer key / allow_expired tolerance changed — the "
        "bridge sends params.answer and relies on the 'expired' status")
    assert 'return _ok(rid, {"status": "expired"})' in server, (
        "_respond no longer reports an expired prompt as status=expired — the "
        "panel would stamp a late answer as delivered")
    assert 'params.get("request_id", "")' in server, (
        "_respond no longer addresses prompts by request_id")
    # Panel Stop with a card open: session.interrupt must release the pending
    # prompt (scoped to that session), or a Stop during an ask would wedge the
    # agent thread until the clarify timeout — the exact hang this card fixes.
    #
    # ⚠️ MOVED AT v0.20.6 (2026-08-28 pin bump), and the RESOLUTION IS A MIRROR
    # UPDATE, NOT A RELAXATION. Up to v0.20.1 the `session.interrupt` handler in
    # methods_session.py contained the release inline (`_clear_pending(sid)`).
    # v0.20.6 hoisted the whole interrupt body into ONE shared helper,
    # `server._interrupt_session_turn(sid, session, *, request_id=None)`
    # (server.py:1112-1157), because the WS orphan reaper now has to apply the
    # identical contract when a dead client's reconnect grace expires. The
    # handler calls that helper on BOTH of its branches (compute-host at
    # methods_session.py:3338 and in-process at :3345), and the helper still does
    # `_clear_pending(sid)` AND `resolve_gateway_approval(..., "deny",
    # resolve_all=True)`. So the guarantee is unchanged — and it is now pinned in
    # BOTH shapes, which is stronger than the old single literal: wherever the body
    # lives, it must still release the prompt AND deny in-flight approvals, and the
    # handler must reach it. (Written 2026-08-28 while bumping to v0.20.6; that bump
    # was ROLLED BACK, so the INLINE branch is the live one today and the helper
    # branch arms itself when this pin next moves.)
    msess = (HERMES / "tui_gateway" / "methods_session.py").read_text(errors="replace")
    _interrupt = msess.split('@method("session.interrupt")', 1)
    assert len(_interrupt) == 2, "the session.interrupt handler is gone"
    _interrupt = _interrupt[1].split('\n@method(', 1)[0]
    if "_clear_pending(sid)" in _interrupt:
        _body = _interrupt                      # pre-v0.20.6: released inline
    else:
        assert "_interrupt_session_turn(" in _interrupt, (
            "session.interrupt neither clears pending prompts inline nor routes "
            "through _interrupt_session_turn — panel Stop during an open ask card "
            "would no longer end the turn")
        _helper = server.split("def _interrupt_session_turn(", 1)
        assert len(_helper) == 2, (
            "server._interrupt_session_turn is gone — find where session.interrupt "
            "now releases pending gateway prompts")
        _body = _helper[1].split("\ndef ", 1)[0]
        assert "_clear_pending(sid)" in _body, (
            "the shared interrupt helper no longer releases pending gateway prompts "
            "— panel Stop during an open ask card would no longer end the turn")
    assert "resolve_gateway_approval(" in _body and '"deny"' in _body, (
        "the interrupt path no longer denies in-flight approvals — a Stop with an "
        "approval card open would leave the agent thread blocked on it")
    ctool = (HERMES / "tools" / "clarify_tool.py").read_text(errors="replace")
    assert '"user_response": user_response' in ctool, (
        "clarify no longer returns the raw user_response string — the card sends "
        "the chosen LABEL, not an index, precisely because of this")
    assert "Other (type your answer)" in ctool, (
        "the always-appended free-text escape hatch is gone from the clarify "
        "contract — the card's free-text box may no longer be honoured")


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
    # The escalation seam: resolve_pre_tool_block must IMPORT request_tool_approval
    # from tools.approval AND actually CALL it. Both forms of the import count —
    # v2026.7.30 wrote it on one line, v2026.8.13 reformatted it to a parenthesised
    # multi-line import (hermes_cli/plugins.py:5884). That reformat is cosmetic and
    # the old literal-string assertion failed on it; this replacement is STRICTLY
    # STRONGER, because it also pins the CALL SITE inside resolve_pre_tool_block —
    # which is the thing that actually opens the approval card. Widened 2026-08-14
    # for the v2026.7.30 → v2026.8.13 bump; passes at BOTH tags.
    assert re.search(
        r"from\s+tools\.approval\s+import\s+(?:\(\s*(?:[\w,\s]*?,\s*)?)?request_tool_approval",
        plugins), (
        "plugins.py no longer imports request_tool_approval from tools.approval — "
        "plugin escalations would not open an approval card")
    #
    # ⚠️ WIDENED AGAIN AT v0.20.6 (2026-08-28 pin bump) — A MIRROR UPDATE, NOT A
    # RELAXATION. v0.20.6 hoisted the escalation body out of
    # `resolve_pre_tool_block` into `_resolve_block_from_details(details,
    # tool_name, *, turn_id, tool_call_id, session_id)` (plugins.py:6603-6660), so
    # that the NEW `_dispatch_pre_tool_call_hooks` (which also handles `modify`
    # directives) shares the identical fail-closed logic instead of copying it.
    # `resolve_pre_tool_block` now ends in a call to that helper (:6597).
    # So the seam still runs, one hop further down, and this check follows it
    # rather than loosening: the resolver must reach the helper, the helper must
    # call the gate, and the helper must still FAIL CLOSED — which is the property
    # the path-guard fence actually depends on and which the old single literal
    # never pinned at all.
    _resolver = plugins.split("def resolve_pre_tool_block", 1)[1].split("\ndef ", 1)[0]
    _gate = "request_tool_approval(" in _resolver
    if not _gate:
        assert "_resolve_block_from_details(" in _resolver, (
            "resolve_pre_tool_block neither calls request_tool_approval nor "
            "delegates to _resolve_block_from_details — an 'approve' directive "
            "from the path-guard would never reach the human gate")
        _helper = plugins.split("def _resolve_block_from_details", 1)
        assert len(_helper) == 2, "_resolve_block_from_details is gone"
        _helper = _helper[1].split("\ndef ", 1)[0]
        assert "request_tool_approval(" in _helper, (
            "the shared pre_tool_call resolver no longer CALLS "
            "request_tool_approval — an 'approve' directive from the path-guard "
            "would never reach the human gate")
        assert 'if details.action == "approve":' in _helper, (
            "the shared resolver no longer branches on the 'approve' directive")
        # FAIL-CLOSED. A gate that errors must BLOCK, never proceed: this is the
        # difference between a fence and a decoration.
        assert 'return f"BLOCKED: plugin approval gate failed for {tool_name}"' in _helper, (
            "the shared resolver no longer fails CLOSED when the approval gate "
            "raises — a path-guard escalation whose gate errors would now be "
            "allowed to write")
        assert 'if not result.get("approved"):' in _helper, (
            "the shared resolver no longer blocks on a DENIED approval")
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
    #
    # ⚠️ RENAMED AT v0.20.6 (2026-08-28 pin bump) — MIRROR UPDATE. The dashboard
    # dispatch path in model_tools.py:1384-1401 switched its ONE call from
    # `resolve_pre_tool_block` to `_dispatch_pre_tool_call_hooks`, which fires the
    # hook once and returns `(block_message, modified_args)` instead of just the
    # block message — the same single-fire contract, same fail-closed resolver
    # (`_resolve_block_from_details`, pinned above), plus the new `modify`
    # directive. Either name satisfies the fence; NEITHER does not.
    assert ("resolve_pre_tool_block" in mtools
            or "_dispatch_pre_tool_call_hooks" in mtools), (
        "model_tools no longer resolves pre_tool_call directives — writes unfenced")
    assert "skip_pre_tool_call_hook" in mtools, (
        "the single-fire opt-out is gone — the hook may now fire twice per tool "
        "call (two path-guard cards for one write) or not at all")
    # the two tools the fence gates must still exist under these names
    ftools = (HERMES / "tools" / "file_tools.py").read_text(errors="replace")
    assert 'registry.register(name="write_file"' in ftools
    assert 'registry.register(name="patch"' in ftools, (
        "the patch tool was renamed — path-guard's GATED_TOOLS needs updating")


def test_the_new_modify_directive_can_rewrite_args_the_guard_already_judged():
    """FOUND WHILE BUMPING TO v0.20.6 (2026-08-28). A NEW upstream hazard, recorded
    here rather than left to be rediscovered.

    v0.20.6 added a third `pre_tool_call` directive: `{"action": "modify", "args":
    {...}}`, which shallow-merges into the tool's arguments before dispatch
    (hermes_cli/plugins.py:6485-6495) and is returned ALONGSIDE a block/approve
    directive from the SAME single hook pass (`_PreToolCallDirective.modified_args`).
    model_tools.py then applies `modified_args` and, if there is no block, runs the
    tool (:1398-1400).

    SO THE ORDERING IS: our path-guard judges the ORIGINAL `file_path`, Debi
    approves THAT path on the card, and a `modify` directive from ANY OTHER enabled
    pre_tool_call plugin can then replace `file_path` with a different one that
    nothing re-checked. That is a fence bypass by construction.

    WHY IT IS NOT A LIVE HOLE IN THIS HARNESS, TODAY, AND WHAT WOULD MAKE IT ONE:
      · no plugin BUNDLED with Hermes returns a `modify` directive (asserted below);
      · user plugins are opt-in through `plugins.enabled`, and the only name
        scripts/start_component.sh ever adds there is `harness-path-guard`, which
        returns block/approve and never modify.
    A SECOND enabled pre_tool_call plugin is therefore the precondition, and it is
    a deliberate act. If this test ever fails because a bundled plugin gained a
    modify directive, the path-guard must move to re-judging `modified_args` — do
    NOT relax this.
    """
    if not HERMES.exists():
        return
    plugins = (HERMES / "hermes_cli" / "plugins.py").read_text(errors="replace")
    if 'result.get("action") == "modify"' not in plugins:
        return          # upstream dropped the directive — the hazard is gone
    assert "modified_args" in plugins, "modify exists but carries no args channel"
    guard = ROOT / "guards" / "harness-path-guard" / "__init__.py"
    if guard.exists():
        assert '"modify"' not in guard.read_text(errors="replace"), (
            "our own path-guard now emits modify directives — it must then also "
            "judge the merged args, which nothing currently does")
    bundled = sorted((HERMES / "plugins").rglob("__init__.py"))
    offenders = [str(p.relative_to(HERMES)) for p in bundled
                 if '"action": "modify"' in p.read_text(errors="replace")
                 or "'action': 'modify'" in p.read_text(errors="replace")]
    assert not offenders, (
        "a BUNDLED Hermes plugin now returns a pre_tool_call `modify` directive: "
        + ", ".join(offenders) + ". Combined with our path-guard's approve "
        "directive, that plugin can rewrite the very file_path Debi approved on "
        "the card. The fence must start re-judging modified_args before this pin "
        "ships.")


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
