"""Unit tests for the per-message actions slice (bridge/app.py + the panel).

Two pure helpers carry the whole slice's judgement:
  • fork_keep_count(history, msg_id) — turns a clicked message's db id into the
    keep_count Odysseus's /fork expects (index+1 of the UNFILTERED history, so
    hidden messages count — the recon gotcha).
  • turn_metadata(model, usage, timings, elapsed) — the direct lane's per-reply
    stats stamp; only keys we actually know may appear.
Both are ast-extracted from bridge/app.py (no fastapi / websockets import), the
same shape as test_thinking_sidecar.py / test_image_sidecar.py.

The panel's matching stats formatter (statsLine) is extracted from
bridge/panel/index.html and run under node so the SHIPPED function is the one
under test. Skipped (not failed) when node is unavailable.

Run directly: python3 bridge/tests/test_msg_actions.py
"""
import ast
import json
import re
import shutil
import subprocess
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
PANEL = ROOT / "bridge" / "panel" / "index.html"

PASS = 0


def check(name, cond):
    global PASS
    assert cond, name
    PASS += 1
    print(f"  ok  {name}")


def _load():
    tree = ast.parse(_APP_SOURCE)
    want = ("fork_keep_count", "turn_metadata")
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in want]
    missing = set(want) - {n.name for n in body}
    assert not missing, f"missing in bridge/app.py: {sorted(missing)}"
    ns = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), "msgacts", "exec"), ns)
    return ns


NS = _load()
fork_keep_count = NS["fork_keep_count"]
turn_metadata = NS["turn_metadata"]


def msg(role, content, db_id=None, **meta):
    m = {"role": role, "content": content}
    if db_id is not None or meta:
        m["metadata"] = dict(meta)
        if db_id is not None:
            m["metadata"]["_db_id"] = db_id
    return m


# ── fork_keep_count ──────────────────────────────────────────────────────────
print("fork_keep_count")

HIST = [
    msg("user", "one", 11),
    msg("assistant", "two", 12),
    msg("user", "three", 13),
    msg("assistant", "four", 14),
]

check("first message → keep 1", fork_keep_count(HIST, 11) == 1)
check("second message → keep 2", fork_keep_count(HIST, 12) == 2)
check("last message → keep len", fork_keep_count(HIST, 14) == len(HIST))
check("clicked message is INCLUDED (index+1)", fork_keep_count(HIST, 13) == 3)

check("absent id → None", fork_keep_count(HIST, 99) is None)
check("None id → None", fork_keep_count(HIST, None) is None)
check("empty id → None", fork_keep_count(HIST, "") is None)
check("empty history → None", fork_keep_count([], 11) is None)
check("None history → None", fork_keep_count(None, 11) is None)

# int/str tolerance — the id round-trips through JSON and a DOM dataset as text
check("str id matches int row", fork_keep_count(HIST, "12") == 2)
check("int id matches str row",
      fork_keep_count([msg("user", "a", "77"), msg("user", "b", "78")], 78) == 2)

# hidden / metadata-less rows still occupy an index (the recon gotcha: keep_count
# indexes the UNFILTERED history, which is exactly what GET /api/history returns)
HID = [
    msg("user", "visible", 1),
    {"role": "system", "content": "hidden, no metadata"},
    msg("assistant", "answer", 3),
]
check("row without metadata still counts toward the index",
      fork_keep_count(HID, 3) == 3)
check("row with non-dict metadata is skipped, not fatal",
      fork_keep_count([{"role": "user", "content": "x", "metadata": "nope"},
                       msg("user", "y", 5)], 5) == 2)
check("row that is not a dict is skipped, not fatal",
      fork_keep_count(["junk", msg("user", "y", 5)], 5) == 2)
check("metadata without _db_id is skipped",
      fork_keep_count([msg("user", "x", None, edited=True), msg("user", "y", 5)], 5) == 2)
check("first match wins", fork_keep_count([msg("u", "a", 1), msg("u", "b", 1)], 1) == 1)


# ── turn_metadata ────────────────────────────────────────────────────────────
print("turn_metadata")

full = turn_metadata("qwen-9b",
                     {"prompt_tokens": 120, "completion_tokens": 45},
                     {"predicted_per_second": 56.4321}, 3.14159)
check("full frame keys",
      set(full) == {"model", "tokens_per_second", "response_time",
                    "input_tokens", "output_tokens"})
check("model passed through", full["model"] == "qwen-9b")
check("tok/s rounded to 2dp", full["tokens_per_second"] == 56.43)
check("response_time rounded to 2dp", full["response_time"] == 3.14)
check("input_tokens int", full["input_tokens"] == 120 and isinstance(full["input_tokens"], int))
check("output_tokens int", full["output_tokens"] == 45)

check("no timings → no tok/s key",
      "tokens_per_second" not in turn_metadata("m", {"completion_tokens": 3}, {}, 1.0))
check("no usage → only model/time keys",
      set(turn_metadata("m", None, None, 2.0)) == {"model", "response_time"})
check("nothing known at all → empty dict", turn_metadata(None, None, None, None) == {})
check("zero values are omitted, never stamped as 0",
      turn_metadata("m", {"prompt_tokens": 0, "completion_tokens": 0},
                    {"predicted_per_second": 0}, 0) == {"model": "m"})
check("garbage values are dropped, never raise",
      turn_metadata("m", {"prompt_tokens": "abc", "completion_tokens": None},
                    {"predicted_per_second": []}, "nope") == {"model": "m"})
check("non-dict usage/timings tolerated",
      turn_metadata("m", "junk", 7, 1.5) == {"model": "m", "response_time": 1.5})
check("string numbers are accepted (json is loose)",
      turn_metadata(None, {"completion_tokens": "45"}, {}, None) == {"output_tokens": 45})


# ── panel statsLine (the shipped JS, run under node) ─────────────────────────
print("statsLine (panel JS under node)")


def _extract_stats_line():
    src = PANEL.read_text()
    i = src.index("function statsLine(")
    depth, j = 0, src.index("{", i)
    k = j
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1]


node = shutil.which("node")
if not node:
    print("  -- node unavailable, statsLine cases skipped")
else:
    fn = _extract_stats_line()
    cases = [
        ({"tokens_per_second": 56.43, "output_tokens": 412, "response_time": 7.25},
         "56.4 tok/s · 412 tok · 7.3s"),
        ({"tokens_per_second": 56.43}, "56.4 tok/s"),
        ({"output_tokens": 9}, "9 tok"),
        ({}, ""),
        (None, ""),
        ({"tokens_per_second": 0, "output_tokens": 0, "response_time": 0}, ""),
        ({"tokens_per_second": "n/a", "output_tokens": 5}, "5 tok"),
        ({"_db_id": 4, "model": "m"}, ""),
    ]
    script = fn + "\nconst cases = " + json.dumps(cases) + ";\n" \
        "console.log(JSON.stringify(cases.map(c => statsLine(c[0]))));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for (inp, want), g in zip(cases, got):
        check(f"statsLine({json.dumps(inp)}) → {want!r}", g == want)
    check("statsLine is pure (no DOM/global refs)",
          not re.search(r"\bdocument\b|\bwindow\b|\bfetch\b", fn))


print(f"\n{PASS}/{PASS} checks passed")
