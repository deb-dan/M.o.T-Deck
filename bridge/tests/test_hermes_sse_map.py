"""Unit tests for the PURE Hermes-event → panel-SSE mapper (bridge/app.py
hermes_event_to_frames). Run directly: python3 bridge/tests/test_hermes_sse_map.py

The mapper is extracted by source (ast) so the test needs neither fastapi nor
websockets installed — it exercises only the pure function.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_mapper():
    src = (ROOT / "bridge" / "app.py").read_text()
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
                                        "choices": ["once", "session", "always",
                                                    "deny"]}}])
fr, act = F({"type": "approval.request", "payload": {"command": "ls"}})
check("approval no choices → conservative [once, deny] default",
      act == "" and fr == [{"type": "approval",
                            "request": {"command": "ls",
                                        "choices": ["once", "deny"]}}])
fr, act = F({"type": "approval.request",
             "payload": {"command": "x", "choices": "once"}})
check("approval non-list choices → default",
      fr[0]["request"]["choices"] == ["once", "deny"])
fr, act = F({"type": "approval.request", "payload": {}})
check("approval empty payload safe",
      act == "" and fr == [{"type": "approval",
                            "request": {"command": "",
                                        "choices": ["once", "deny"]}}])
fr, act = F({"type": "approval.request",
             "payload": {"command": "x", "choices": [1, "deny"]}})
check("approval choices coerced to strings",
      fr[0]["request"]["choices"] == ["1", "deny"])

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
      fr == [{"type": "tool_output", "tool": "write_file"}])
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

# defensive: malformed payloads never raise
fr, act = F({"type": "message.delta", "payload": None})
check("null payload safe", fr == [] and act == "")
fr, act = F({})
check("empty event safe", fr == [] and act == "")

print(f"PASS {PASS}/{PASS}")
sys.exit(0)
