"""Unit tests for the direct-lane thinking sidecar (bridge/app.py).

The lane persists {role, content} to Odysseus, so the turn's reasoning is kept
locally in data/thinking.db keyed by (session id, answer hash) and re-attached
when the panel reopens the session. Both the pure join helpers AND the sqlite
store are exercised here — extracted from bridge/app.py by ast so neither
fastapi nor websockets is required.

Run directly: python3 bridge/tests/test_thinking_sidecar.py
"""
import ast
import os
import sys
import tempfile
import threading
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
APP = ROOT / "bridge" / "appsrc.py"

PASS = 0


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


def _load(tmp_root):
    """Extract the sidecar functions and bind them to a throwaway data root."""
    tree = ast.parse(_APP_SOURCE)
    want = ("answer_hash", "_thinking_conn", "log_thinking", "_thinking_rows",
            "_thinking_forget", "attach_thinking")
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    missing = set(want) - {n.name for n in body}
    assert not missing, f"missing in bridge/app.py: {sorted(missing)}"
    ns = {"ROOT": Path(tmp_root), "threading": threading,
          "_thinking_lock": threading.Lock(), "_thinking_pruned": False}
    exec(compile(ast.Module(body=body, type_ignores=[]), "sidecar", "exec"), ns)
    return ns


NS = _load(tempfile.mkdtemp())
answer_hash = NS["answer_hash"]
log_thinking = NS["log_thinking"]
thinking_rows = NS["_thinking_rows"]
thinking_forget = NS["_thinking_forget"]
attach = NS["attach_thinking"]

# ── answer_hash: stable, truncating, total ───────────────────────────────────
check("hash is stable", answer_hash("hello") == answer_hash("hello"))
check("hash differs for different text", answer_hash("a") != answer_hash("b"))
check("hash is a sha1 hexdigest", len(answer_hash("x")) == 40)
check("hash truncates at 2048 chars (tail ignored)",
      answer_hash("z" * 2048) == answer_hash("z" * 2048 + "TAIL"))
check("hash below the cap still discriminates",
      answer_hash("z" * 2047) != answer_hash("z" * 2048))
check("empty text hashes without raising", isinstance(answer_hash(""), str))
check("None hashes without raising", isinstance(answer_hash(None), str))
check("non-ascii hashes without raising", isinstance(answer_hash("café ✳ 日本"), str))
check("lone surrogate never raises (replace)",
      isinstance(answer_hash("bad \ud800 char"), str))

# ── attach_thinking: order-consuming join ────────────────────────────────────
h1, h2 = answer_hash("A1"), answer_hash("A2")

hist = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "A1"}]
attach(hist, [(h1, "thought one")])
check("match attaches reasoning", hist[1].get("reasoning") == "thought one")
check("user messages are never touched", "reasoning" not in hist[0])

hist = [{"role": "assistant", "content": "A1"}, {"role": "assistant", "content": "A1"}]
attach(hist, [(h1, "first"), (h1, "second")])
check("duplicate answers consume rows IN ORDER",
      hist[0]["reasoning"] == "first" and hist[1]["reasoning"] == "second")

hist = [{"role": "assistant", "content": "A1"}, {"role": "assistant", "content": "A1"}]
attach(hist, [(h1, "only")])
check("a single row is used at most once",
      hist[0]["reasoning"] == "only" and "reasoning" not in hist[1])

hist = [{"role": "assistant", "content": "A2"}]
attach(hist, [(h1, "unrelated")])
check("no match → passthrough, no reasoning key", "reasoning" not in hist[0])

hist = [{"role": "assistant", "content": "A1", "reasoning": "already here"}]
attach(hist, [(h1, "from store")])
check("an existing .reasoning is never overwritten",
      hist[0]["reasoning"] == "already here")

hist = [{"role": "assistant", "content": "A2"}, {"role": "assistant", "content": "A1"}]
attach(hist, [(h1, "for A1"), (h2, "for A2")])
check("rows match by hash, not position",
      hist[0]["reasoning"] == "for A2" and hist[1]["reasoning"] == "for A1")

check("no rows → history returned unchanged",
      attach([{"role": "assistant", "content": "A1"}], []) == [
          {"role": "assistant", "content": "A1"}])
check("None history never raises", attach(None, [(h1, "x")]) is None)
check("None rows never raises", attach([], None) == [])

# malformed inputs must never raise
hist = [None, "nonsense", 42, {"role": "assistant"},
        {"role": "assistant", "content": None}, {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "A1"}]
attach(hist, [None, (), ("onlyhash",), (h1, None), ("", "orphan"), (h1, "good")])
check("malformed rows/messages skipped, real match still lands",
      hist[-1].get("reasoning") == "good")

# ── sqlite store: insert, read back, per-session isolation, prune, forget ────
log_thinking("s1", "A1", "deep thoughts")
check("stored row reads back", thinking_rows("s1") == [(answer_hash("A1"), "deep thoughts")])
check("other sessions see nothing", thinking_rows("s2") == [])
check("unknown session → empty list", thinking_rows("nope") == [])
check("empty sid → empty list", thinking_rows("") == [])

log_thinking("s1", "A2", "second thought")
check("rows come back oldest-first",
      [r[1] for r in thinking_rows("s1")] == ["deep thoughts", "second thought"])

log_thinking("s1", "", "no answer")
log_thinking("s1", "A3", "")
log_thinking("", "A4", "no session")
check("blank answer / reasoning / sid are not stored", len(thinking_rows("s1")) == 2)

# end-to-end: store → read → attach
hist = [{"role": "assistant", "content": "A2"}, {"role": "assistant", "content": "A1"}]
attach(hist, thinking_rows("s1"))
check("store → attach round-trips",
      hist[0]["reasoning"] == "second thought" and hist[1]["reasoning"] == "deep thoughts")

for i in range(230):
    log_thinking("big", f"answer {i}", f"thought {i}")
rows = thinking_rows("big")
check("per-session prune caps at 200 rows", len(rows) == 200)
check("prune drops the OLDEST rows", rows[-1][1] == "thought 229")
check("prune left other sessions alone", len(thinking_rows("s1")) == 2)

thinking_forget("s1")
check("forget removes that session's rows", thinking_rows("s1") == [])
check("forget left other sessions alone", len(thinking_rows("big")) == 200)
thinking_forget("")
check("forget with empty sid is a no-op", len(thinking_rows("big")) == 200)

# an unwritable data root must degrade silently, never raise into the chat path
BAD = _load("/proc/nonexistent-harness-root")
BAD["log_thinking"]("s", "A", "T")
check("unwritable store: log_thinking never raises", True)
check("unwritable store: rows → []", BAD["_thinking_rows"]("s") == [])
BAD["_thinking_forget"]("s")
check("unwritable store: forget never raises", True)

print(f"\n{PASS}/{PASS} thinking-sidecar checks passed")
