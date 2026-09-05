"""Unit tests for the PURE Hermes-event → panel-SSE mapper (bridge/app.py
hermes_event_to_frames). Run directly: python3 bridge/tests/test_hermes_sse_map.py

The mapper is extracted by source (ast) so the test needs neither fastapi nor
websockets installed — it exercises only the pure function.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402


def _load_mapper():
    src = _APP_SOURCE
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "hermes_event_to_frames")
    mod = ast.Module(body=[fn], type_ignores=[])
    ns: dict = {}
    exec(compile(mod, "hermes_event_to_frames", "exec"), ns)
    return ns["hermes_event_to_frames"]


F = _load_mapper()
PASS = 0


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


# token deltas → the direct-lane {"delta"} shape
fr, act = F({"type": "message.delta", "session_id": "s", "payload": {"text": "hi"}})
check("delta text", fr == [{"delta": "hi"}] and act == "")
fr, act = F({"type": "message.delta", "payload": {"text": ""}})
check("empty delta dropped", fr == [] and act == "")

# thinking protocol (both reasoning + thinking delta names)
fr, _ = F({"type": "reasoning.delta", "payload": {"text": "hm"}})
check("reasoning → thinking", fr == [{"delta": "hm", "thinking": True}])
fr, _ = F({"type": "thinking.delta", "payload": {"text": "hm2"}})
check("thinking.delta → thinking", fr == [{"delta": "hm2", "thinking": True}])

# tool lifecycle → the statusline shapes the panel already renders
fr, _ = F({"type": "tool.start", "payload": {"tool_id": "t1", "name": "web_search"}})
check("tool.start → tool_start", fr == [{"type": "tool_start", "tool": "web_search"}])
fr, _ = F({"type": "tool.start", "payload": {}})
check("tool.start no name → 'tool'", fr == [{"type": "tool_start", "tool": "tool"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "shell", "summary": "ran ls", "result": "x" * 99999}})
check("tool.complete slimmed", fr == [{"type": "tool_output", "tool": "shell",
                                       "summary": "ran ls"}])
fr, _ = F({"type": "tool.complete", "payload": {"name": "shell"}})
check("tool.complete no summary", fr == [{"type": "tool_output", "tool": "shell"}])

# approvals (Phase 2): ONE structured frame → the panel's interactive card; the
# turn keeps streaming (act ""), the answer comes back via POST /api/hermes/approve
fr, act = F({"type": "approval.request",
             "payload": {"command": "rm -rf /tmp/x",
                         "choices": ["once", "session", "always", "deny"]}})
check("approval → card frame, turn keeps streaming",
      act == "" and fr == [{"type": "approval",
                            "request": {"command": "rm -rf /tmp/x",
                                        "description": "",
                                        "choices": ["once", "session", "always",
                                                    "deny"]}}])
# Path-guard fence: a PLUGIN-escalated approval labels command synthetically and
# carries the real reason (with the target path) in description — forwarded so the
# card can show WHAT is being written.
fr, act = F({"type": "approval.request",
             "payload": {"command": "<write_file> (plugin approval rule)",
                         "description": "path-guard: write outside workspace: "
                                        "/Users/debik/Desktop/a.txt",
                         "choices": ["once", "session", "always", "deny"]}})
check("plugin approval → description forwarded (the path)",
      fr[0]["request"]["description"].endswith("/Users/debik/Desktop/a.txt"))
fr, act = F({"type": "approval.request", "payload": {"command": "ls"}})
check("approval no choices → conservative [once, deny] default",
      act == "" and fr == [{"type": "approval",
                            "request": {"command": "ls", "description": "",
                                        "choices": ["once", "deny"]}}])
fr, act = F({"type": "approval.request",
             "payload": {"command": "x", "choices": "once"}})
check("approval non-list choices → default",
      fr[0]["request"]["choices"] == ["once", "deny"])
fr, act = F({"type": "approval.request", "payload": {}})
check("approval empty payload safe",
      act == "" and fr == [{"type": "approval",
                            "request": {"command": "", "description": "",
                                        "choices": ["once", "deny"]}}])
fr, act = F({"type": "approval.request",
             "payload": {"command": "x", "choices": [1, "deny"]}})
check("approval choices coerced to strings",
      fr[0]["request"]["choices"] == ["1", "deny"])

# ASK CARDS (the `clarify` tool, 2026-08-14): ONE structured frame → the panel's
# interactive picker; the turn KEEPS STREAMING (the agent thread is blocked on the
# gateway prompt, not finished).
fr, act = F({"type": "clarify.request",
             "payload": {"question": "What should I test?",
                         "choices": ["Functionality", "Performance", "Integration"],
                         "request_id": "ab12cd34"}})
check("clarify → ask frame, turn keeps streaming",
      act == "" and fr == [{"type": "ask",
                            "request": {"request_id": "ab12cd34",
                                        "question": "What should I test?",
                                        "options": ["Functionality", "Performance",
                                                    "Integration"],
                                        "multi_select": False,
                                        "allows_free_text": True}}])
# open-ended clarify (no choices) — upstream drops an empty list to None
fr, act = F({"type": "clarify.request",
             "payload": {"question": "Name the file?", "request_id": "r1"}})
check("clarify with no choices → open-ended, free text still offered",
      act == "" and fr[0]["request"]["options"] == []
      and fr[0]["request"]["allows_free_text"] is True)
# free text is NEVER withheld: upstream appends "Other (type your answer)" always
check("allows_free_text is unconditional",
      F({"type": "clarify.request",
         "payload": {"question": "q", "choices": ["a"]}})[0][0]
      ["request"]["allows_free_text"] is True)
# multi_select is only present upstream when True
fr, _ = F({"type": "clarify.request",
           "payload": {"question": "q", "choices": ["a", "b"], "multi_select": True}})
check("clarify multi_select forwarded", fr[0]["request"]["multi_select"] is True)
# hostile / malformed payloads must never raise and never invent options
fr, act = F({"type": "clarify.request", "payload": {}})
check("clarify empty payload safe",
      act == "" and fr == [{"type": "ask",
                            "request": {"request_id": "", "question": "",
                                        "options": [], "multi_select": False,
                                        "allows_free_text": True}}])
fr, _ = F({"type": "clarify.request",
           "payload": {"question": "q", "choices": "Functionality"}})
check("clarify non-list choices → no options (never split a string)",
      fr[0]["request"]["options"] == [])
fr, _ = F({"type": "clarify.request",
           "payload": {"question": "q", "choices": [1, "b", None, "  ", ""]}})
check("clarify options coerced to strings, blanks dropped",
      fr[0]["request"]["options"] == ["1", "b"])
# expiry: upstream gave up waiting → the card must stop claiming it is answerable
fr, act = F({"type": "clarify.expire", "payload": {"request_id": "ab12cd34"}})
check("clarify.expire → ask_expire, turn keeps streaming",
      act == "" and fr == [{"type": "ask_expire", "request_id": "ab12cd34"}])
fr, act = F({"type": "clarify.expire", "payload": {}})
check("clarify.expire without id safe",
      act == "" and fr == [{"type": "ask_expire", "request_id": ""}])
# an ask NEVER ends the turn
check("ask never ends a turn",
      F({"type": "clarify.request", "payload": {"question": "q"}})[1] == ""
      and F({"type": "clarify.expire", "payload": {}})[1] == "")

# turn terminators
fr, act = F({"type": "message.complete", "payload": {"text": "final answer"}})
check("complete → done, text NOT re-emitted", fr == [] and act == "done")
fr, act = F({"type": "message.complete",
             "payload": {"status": "error", "error": "boom", "text": "Error: boom"}})
check("complete error → proxy_error + done",
      act == "done" and fr == [{"type": "proxy_error", "error": "boom"}])
# Phase 1.1 turn-enders: interrupted turns END the stream with a visible note
fr, act = F({"type": "message.complete",
             "payload": {"text": "", "status": "interrupted"}})
check("complete interrupted → note + done",
      act == "done" and fr == [{"delta": "\n· interrupted"}])
fr, act = F({"type": "message.complete",
             "payload": {"text": "partial answer", "usage": {"total": 5},
                         "status": "interrupted"}})
check("interrupted with partial text → note + done (text NOT re-emitted)",
      act == "done" and fr == [{"delta": "\n· interrupted"}])
fr, act = F({"type": "message.complete",
             "payload": {"status": "interrupted", "error": "boom"}})
check("interrupted + error field → error wins",
      act == "done" and fr == [{"type": "proxy_error", "error": "boom"}])
# the relay's stop sentinel is handled BEFORE the mapper; if it ever leaks
# through it must be inert (unknown-type fall-through, never a raise)
fr, act = F({"type": "_stop_requested"})
check("_stop_requested sentinel inert in mapper", fr == [] and act == "")

fr, act = F({"type": "error", "payload": {"message": "agent init failed"}})
check("error event → proxy_error + done",
      act == "done" and fr == [{"type": "proxy_error", "error": "agent init failed"}])
fr, act = F({"type": "_ws_closed"})
check("ws-closed sentinel → done", act == "done"
      and fr == [{"type": "proxy_error", "error": "Hermes connection lost"}])

# soft events pass to inspect-only shapes / are dropped
fr, act = F({"type": "status.update", "payload": {"kind": "process", "text": "Summarizing…"}})
check("status.update → status", fr == [{"type": "status", "kind": "process",
                                        "text": "Summarizing…"}] and act == "")
fr, act = F({"type": "session.info", "payload": {"model": "x"}})
check("session.info ignored", fr == [] and act == "")
fr, act = F({"type": "gateway.ready", "payload": {}})
check("gateway.ready ignored", fr == [] and act == "")
fr, act = F({"type": "message.start"})
check("message.start ignored (no payload key)", fr == [] and act == "")

# §F file cards: successful write_file/patch tool.complete → file_card frames
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file", "args": {"path": "cards-test.txt"},
                       "result": {"bytes_written": 5,
                                  "resolved_path": "/Users/debik/Desktop/cards-test.txt",
                                  "files_modified": ["/Users/debik/Desktop/cards-test.txt"]}}})
check("write_file success → tool_output + file_card",
      fr == [{"type": "tool_output", "tool": "write_file"},
             {"type": "file_card", "path": "/Users/debik/Desktop/cards-test.txt",
              "tool": "write_file"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "patch", "args": {"path": "a.py"},
                       "result": {"files_modified": ["/Users/d/a.py", "/Users/d/b.py",
                                                     "/Users/d/a.py"]}}})
check("patch multi-file V4A → one card per file, deduped",
      [f["path"] for f in fr if f.get("type") == "file_card"]
      == ["/Users/d/a.py", "/Users/d/b.py"])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file",
                       "result": {"error": "Refusing to write"},
                       "args": {"path": "/Users/d/x.txt"}}})
check("write_file error → NO file_card",
      [f for f in fr if f.get("type") == "file_card"] == [])
# ⚠️ AND THE FAILURE IS NOW ON THE WIRE, which is the half of the 2026-08-27 LOffice
# consent incident that was not about consent at all: a tool returned an error, the panel
# rendered nothing, and the model's "Done" stood unchallenged. Every failure path lands
# in ONE shape — tool_error() returns {"error": …} (tools/registry.py:1282) and an MCP
# result with isError:true is converted to exactly that (tools/mcp_tool.py:5442) — so a
# single test on the parsed result covers native tools and every MCP server alike.
check("…but the ERROR is forwarded, so a failed tool cannot render as a silent success",
      fr[0] == {"type": "tool_output", "tool": "write_file",
                "is_error": True, "error": "Refusing to write"})
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "office_stage_changes", "summary": "refused",
                       "result": '{"error": "no such workbook"}'}})
check("a STRING result that is a JSON error object is read as an error too — the MCP "
      "path can hand back either",
      fr == [{"type": "tool_output", "tool": "office_stage_changes",
              "summary": "refused", "is_error": True,
              "error": "no such workbook"}])
# ⚠️ THE DOUBLE-ENCODED CASE, WHICH IS WHAT THE REAL MCP LANE PRODUCES. Our server
# answers isError with its OWN json body; Hermes takes the text off the content block and
# passes it to tool_error(), which wraps it again. Without the unwrap the panel's ✗ chip
# is a wall of braces instead of the tool's sentence — seen live on 2026-08-28.
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "office_stage_changes",
                       "result": {"error": '{"ok": false, "error": "operation 3: '
                                           '\\"values\\" is not a row-major grid"}'}}})
check("a double-encoded MCP refusal is unwrapped to the tool's own sentence",
      fr == [{"type": "tool_output", "tool": "office_stage_changes", "is_error": True,
              "error": 'operation 3: "values" is not a row-major grid'}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "shell", "result": {"error": "{not json at all"}}})
check("…and an error that only LOOKS like json is left exactly as it is",
      fr[0]["error"] == "{not json at all")
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "office_read", "result": {"ok": True, "cells": []}}})
check("…and a result with no error field says nothing about errors",
      fr == [{"type": "tool_output", "tool": "office_read"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "shell", "result": "plain text, not json"}})
check("…nor does a plain string result", fr == [{"type": "tool_output", "tool": "shell"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file", "args": {"path": "~/Desktop/rel.txt"},
                       "result": {"bytes_written": 3}}})
check("legacy resolution (no resolved_path) → args.path fallback",
      fr[-1] == {"type": "file_card", "path": "~/Desktop/rel.txt",
                 "tool": "write_file"})
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file", "args": {"path": "x"},
                       "result": "unparsed string result"}})
check("string result (unparseable) → conservative, NO file_card",
      fr == [{"type": "tool_output", "tool": "write_file"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "read_file", "args": {"path": "/Users/d/a.py"},
                       "result": {"content": "hi"}}})
check("non-file-producing tool → NO file_card",
      fr == [{"type": "tool_output", "tool": "read_file"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file", "args": None, "result": {}}})
check("file-card branch malformed args safe",
      fr == [{"type": "tool_output", "tool": "write_file"}])
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "patch", "args": {},
                       "result": {"files_modified": [None, "", "  "]}}})
check("blank/None paths dropped → no cards",
      fr == [{"type": "tool_output", "tool": "patch"}])
# Path-guard audit tier (C): the guard_flag frame is emitted by the LIVE mapper via
# the module-level _guard_flag helper. Here the mapper is ast-extracted into a bare
# namespace, so that lookup NameErrors inside its own try → no guard_flag frame and
# the exact-equality checks above stay stable. The helper's containment logic is
# unit-tested in bridge/tests/test_path_guard.py.
fr, _ = F({"type": "tool.complete",
           "payload": {"name": "write_file", "args": {"path": "/Users/d/out.txt"},
                       "result": {"resolved_path": "/Users/d/out.txt"}}})
check("guard_flag absent in the extracted mapper (helper unavailable, never raises)",
      [f.get("type") for f in fr] == ["tool_output", "file_card"])

# defensive: malformed payloads never raise
fr, act = F({"type": "message.delta", "payload": None})
check("null payload safe", fr == [] and act == "")
fr, act = F({})
check("empty event safe", fr == [] and act == "")

# ── wiring greps: the pure mapper is only half the ask-card path ────────────
_APP = _APP_SOURCE
check("answer endpoint exists", '@app.post("/api/hermes/answer")' in _APP)
check("answer endpoint calls clarify.respond",
      '"clarify.respond"' in _APP and '"answer": answer' in _APP)
check("answer endpoint addresses by request_id (not session FIFO)",
      '{"request_id": rid, "answer": answer}' in _APP)
check("answer endpoint requires a request_id",
      '"request_id required"' in _APP)
check("cancel sends the empty string upstream (upstream's own skip)",
      'if body.get("cancel"):' in _APP and 'answer = ""' in _APP)
check("expired status surfaced to the panel, not swallowed",
      '"status": res.get("status") or "ok"' in _APP)
# The watchdog suppression is what stops a pending card being read as a dead turn.
check("a pending clarify suppresses the working-note/probe like an approval",
      'in ("approval.request", "clarify.request")' in _APP)
_PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
_PANEL_STREAM = (ROOT / "bridge" / "panel" / "assets" / "turn-stream.js").read_text()
check("panel renders the ask frame", "j.type === 'ask'" in _PANEL
      or ("j.type === 'ask'" in _PANEL_STREAM and "chatAsk(holder" in _PANEL_STREAM))
check("panel handles ask_expire per request_id",
      (("j.type === 'ask_expire'" in _PANEL and "expireAskCard(holder" in _PANEL)
       or ("j.type === 'ask_expire'" in _PANEL_STREAM
           and "expireAskCard(holder" in _PANEL_STREAM)))
check("ask cards reuse the approval grammar (so expireApprovals freezes them)",
      "className = 'approval ask'" in _PANEL
      and "querySelectorAll('.approval')" in _PANEL)
check("ask card offers a cancel that posts cancel:true",
      "answerHermes(card, '', {cancel: true})" in _PANEL)
check("ask card free-text box exists and sends on Enter",
      "ask-text" in _PANEL and "e.key === 'Enter'" in _PANEL)
check("expired ask stamps instead of claiming an answer",
      "j.status === 'expired'" in _PANEL and "expireApprovalCard(card)" in _PANEL)
# NEGATIVE: nothing in the ask path may answer on the user's behalf — in
# conversation mode the mic is gated because the turn never ends, and an
# auto-answer would make the harness talk to itself.
_ASK = _PANEL.split("function chatAsk(", 1)[1].split("\nfunction expireAskCard", 1)[0]
check("ask path never auto-answers or auto-sends",
      "convSend" not in _ASK and "sendChat" not in _ASK
      and "setTimeout" not in _ASK)

# ── MULTI-SELECT v2 (2026-08-14): toggleable chips + a confirm ───────────────
# v1 rendered multi_select as a faint hint and made the user do the joining by hand.
check("multi_select is decided from the frame, not assumed",
      "const multi = !!(req && req.multi_select) && opts.length > 0;" in _ASK)
check("multi-select chips TOGGLE instead of answering",
      "b.classList.toggle('on'," in _ASK and "picked.splice(i, 1)" in _ASK)
check("a single-select chip still answers on the first click",
      "b.onclick = () => answerHermes(card, o);" in _ASK)
# Indexes, not labels: two choices may legitimately carry the same text and must then
# toggle independently — keying on the label would move them as one.
check("picks are tracked by option INDEX (duplicate labels stay independent)",
      "const picked = [];" in _ASK and "picked.indexOf(idx)" in _ASK
      and "picked.map(i => opts[i])" in _ASK)
check("the confirm chip names the count and is dead until something is picked",
      "'answer with ' + picked.length + ' selected'" in _ASK
      and "goBtn.disabled = picked.length === 0;" in _ASK)
check("the confirm chip is an ordinary .ap-btn (frozen by expire/disable like the rest)",
      "goBtn.className = 'ap-btn ask-go'" in _ASK)
check("a frozen card cannot be toggled or confirmed",
      "if (card._done || b.disabled) return;" in _ASK
      and "if (card._done || !picked.length) return;" in _ASK)
check("the selected look reuses the gold .on grammar (one new CSS rule, outline only)",
      ".cmsg .approval .ap-btn.on { color:var(--gold); border-color:var(--gold); }" in _PANEL)
check("the collapsed card shows the labels, not the wire string",
      "{label: labels.join(', ')}" in _PANEL and "esc(shown)" in _PANEL)
# NEGATIVE: still nothing automatic, and the free-text/cancel paths are untouched.
check("multi-select adds no timer and no auto-confirm",
      "setTimeout" not in _ASK and "click()" not in _ASK)

# ── askJoin (the shipped panel JS, run under node) ───────────────────────────
# The join is the whole wire contract with upstream's _parse_multi_select_response
# (vendor/hermes/tools/clarify_tool.py:86), so it is EXECUTED, not grepped.
import shutil, subprocess, json as _json
_node = shutil.which("node")
if not _node:
    print("  -- node unavailable, askJoin cases skipped")
else:
    _src = _PANEL.split("function askJoin(", 1)[1]
    _src = "function askJoin(" + _src[:_src.index("\n}") + 2]
    _cases = [
        (["Functionality"], "Functionality"),
        (["Functionality", "Performance"], "Functionality, Performance"),
        ([], ""),
        (["a", "b", "c"], "a, b, c"),
        # a label containing a comma would be re-split by upstream → JSON-array form
        (["Speed, latency", "Cost"], '["Speed, latency","Cost"]'),
        (["one"], "one"),
    ]
    _script = _src + "\nconsole.log(JSON.stringify(" + _json.dumps(
        [c[0] for c in _cases]) + ".map(askJoin)));"
    _out = subprocess.run([_node, "-e", _script], capture_output=True, text=True)
    assert _out.returncode == 0, _out.stderr
    _got = _json.loads(_out.stdout.strip())
    for (_inp, _want), _g in zip(_cases, _got):
        check(f"askJoin({_inp!r}) -> {_want!r}", _g == _want)
    # totality: junk must not throw (a hostile frame can reach here)
    _script2 = _src + "\nconsole.log(JSON.stringify([askJoin(null), askJoin(undefined)]));"
    _out2 = subprocess.run([_node, "-e", _script2], capture_output=True, text=True)
    check("askJoin is total (null/undefined -> '')",
          _out2.returncode == 0 and _json.loads(_out2.stdout.strip()) == ["", ""])

print(f"PASS {PASS}/{PASS}")
sys.exit(0)
