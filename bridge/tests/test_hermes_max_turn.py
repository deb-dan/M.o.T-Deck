"""Unit tests for the Hermes MAX-GENERATION-SEGMENT guard (2026-08-14h).

REVISED from the 2026-08-14g total-turn cap after sample's objection: capping TOTAL
turn time punishes exactly the work MOT Deck exists for — an hour-long research
turn that keeps making tool calls. What must be bounded is ONE UNBROKEN GENERATION
SEGMENT, so the clock RESETS on tool.start / tool.complete and on card resolution
(and still PAUSES while a card is pending).

Covers the PURE half (config read / segment clock / reset table / overrun decision /
message) plus the WIRING facts that make the guard actually bite: it must be checked
on the EVENT path (a runaway loop keeps emitting, so every silence-based watchdog is
blind to it) and it must call session.interrupt (kill the GENERATION, not the stream).

Run directly:  python3 bridge/tests/test_hermes_max_turn.py

The pure functions are extracted by source (ast) so the test needs neither fastapi
nor websockets installed.
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
SRC = _APP_SOURCE
SHIP = (ROOT / "scripts" / "ship.sh").read_text()

PURE = ("hermes_max_turn_s", "hermes_segment_spent", "hermes_segment_overrun",
        "hermes_segment_resets", "hermes_overrun_error")


def _load():
    tree = ast.parse(SRC)
    body = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in PURE]
    _CONSTS = ("HERMES_MAX_TURN_S_DEFAULT", "HERMES_SEGMENT_RESET_EVENTS")
    consts = [n for n in tree.body
              if isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") in _CONSTS for t in n.targets)]
    assert len(body) == len(PURE), f"missing pure fns: {[n.name for n in body]}"
    assert len(consts) == 2, "module-level guard constants not found"
    ns: dict = {}
    exec(compile(ast.Module(body=consts + body, type_ignores=[]),
                 "hermes_max_turn", "exec"), ns)
    return ns


NS = _load()
max_turn_s = NS["hermes_max_turn_s"]
spent = NS["hermes_segment_spent"]
overrun = NS["hermes_segment_overrun"]
resets = NS["hermes_segment_resets"]
err = NS["hermes_overrun_error"]
DEFAULT = NS["HERMES_MAX_TURN_S_DEFAULT"]
RESET_EVENTS = NS["HERMES_SEGMENT_RESET_EVENTS"]

PASS = 0
FAIL = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}")


# ── the default itself ────────────────────────────────────────────────────────
check("default is 600s", DEFAULT == 600.0)

# ── hermes_max_turn_s: config read ───────────────────────────────────────────
check("reads a plain int", max_turn_s({"hermes": {"max_turn_s": 120}}) == 120.0)
check("reads a float", max_turn_s({"hermes": {"max_turn_s": 12.5}}) == 12.5)
check("reads a yaml string number", max_turn_s({"hermes": {"max_turn_s": "45"}}) == 45.0)
check("0 disables", max_turn_s({"hermes": {"max_turn_s": 0}}) == 0.0)
check("'0' disables", max_turn_s({"hermes": {"max_turn_s": "0"}}) == 0.0)
check("negative disables", max_turn_s({"hermes": {"max_turn_s": -5}}) == 0.0)
# a safety guard must not be switched off by accident: only a deliberate 0 does it
check("missing block → default", max_turn_s({}) == DEFAULT)
check("missing key → default", max_turn_s({"hermes": {}}) == DEFAULT)
check("null value → default", max_turn_s({"hermes": {"max_turn_s": None}}) == DEFAULT)
check("junk string → default", max_turn_s({"hermes": {"max_turn_s": "soon"}}) == DEFAULT)
check("list → default", max_turn_s({"hermes": {"max_turn_s": [1]}}) == DEFAULT)
check("dict → default", max_turn_s({"hermes": {"max_turn_s": {"a": 1}}}) == DEFAULT)
check("nan → default", max_turn_s({"hermes": {"max_turn_s": float("nan")}}) == DEFAULT)
check("inf → default", max_turn_s({"hermes": {"max_turn_s": float("inf")}}) == DEFAULT)
check("bool True → default (not 1s)",
      max_turn_s({"hermes": {"max_turn_s": True}}) == DEFAULT)
check("hermes not a dict → default", max_turn_s({"hermes": 600}) == DEFAULT)
check("hermes is a list → default", max_turn_s({"hermes": []}) == DEFAULT)
check("None config → default", max_turn_s(None) == DEFAULT)
check("non-dict config → default", max_turn_s("nope") == DEFAULT)
check("components.hermes is NOT read",
      max_turn_s({"components": {"hermes": {"max_turn_s": 5}}}) == DEFAULT)

# ── hermes_segment_spent: the clock ───────────────────────────────────────────
check("plain elapsed", spent(100.0, 40.0) == 60.0)
check("no pause args", spent(10.0, 10.0) == 0.0)
check("never negative (clock skew)", spent(5.0, 10.0) == 0.0)
check("closed pause subtracted", spent(100.0, 0.0, paused_total=30.0) == 70.0)
check("open pause subtracted",
      spent(100.0, 0.0, paused_total=0.0, paused_since=60.0) == 60.0)
check("closed + open pause",
      spent(100.0, 0.0, paused_total=10.0, paused_since=80.0) == 70.0)
check("pause longer than the segment floors at 0",
      spent(100.0, 0.0, paused_total=500.0) == 0.0)
check("a pause that started in the future contributes nothing",
      spent(100.0, 0.0, paused_since=120.0) == 100.0)
check("None paused_total tolerated", spent(100.0, 0.0, paused_total=None) == 100.0)
# THE invariant: a card on screen freezes the budget
_a = spent(200.0, 0.0, paused_total=0.0, paused_since=50.0)
_b = spent(900.0, 0.0, paused_total=0.0, paused_since=50.0)
check("time under a pending card does NOT accrue", _a == 50.0 and _b == 50.0)

# ── hermes_segment_overrun: the decision ─────────────────────────────────────
check("under budget", overrun(599.0, 600.0) is False)
check("exactly at budget fires", overrun(600.0, 600.0) is True)
check("over budget fires", overrun(601.0, 600.0) is True)
check("budget 0 = disabled", overrun(99999.0, 0.0) is False)
check("negative budget = disabled", overrun(99999.0, -1.0) is False)
check("junk budget = disabled", overrun(99999.0, "x") is False)
check("junk spent = disabled", overrun("x", 600.0) is False)
check("zero spent never fires", overrun(0.0, 600.0) is False)
# a paused segment can never trip it, by construction of the two fns together
check("a segment paused from second 1 stays at 1s spent",
      spent(10_000.0, 0.0, paused_since=1.0) == 1.0
      and overrun(1.0, 600.0) is False)

# ── the message ──────────────────────────────────────────────────────────────
check("exact wording",
      err(600.0) == "generation exceeded 600s without a tool call or output — likely "
                    "a deliberation loop; interrupted server-side (hermes.max_turn_s)")
check("names the config key", "hermes.max_turn_s" in err(120))
check("says server-side", "interrupted server-side" in err(120))
check("blames the deliberation loop, not the turn's length",
      "deliberation loop" in err(120) and "turn exceeded" not in err(120))
check("integral budget prints without a decimal point", "120s" in err(120.0))
check("fractional budget survives", "12.5s" in err(12.5))

# ── WIRING: bridge/app.py ────────────────────────────────────────────────────
def between(start_marker, end_marker):
    i = SRC.index(start_marker)
    j = SRC.index(end_marker, i)
    return SRC[i:j]


_END = "@app.post(\"/api/hermes/stop\")"
# anchor on the LAST `async def gen():` before the stop endpoint — app.py has several
# streaming generators, and starting at the first one swallowed the pure functions
# and made source-ORDER assertions meaningless (found 2026-08-14h).
relay = SRC[SRC.rindex("async def gen():", 0, SRC.index(_END)):SRC.index(_END)]

check("budget read once, at submit, inside the relay",
      relay.count("hermes_max_turn_s(cfg())") == 1)
check("budget read is failsafe (yaml hiccup → default, not a dead turn)",
      "except Exception:" in relay and "max_turn = HERMES_MAX_TURN_S_DEFAULT" in relay)
check("segment clock armed from the loop clock",
      "seg_started = asyncio.get_running_loop().time()" in relay)
check("checked in BOTH the timeout tick and the event path",
      relay.count("hermes_segment_overrun(_spent, max_turn)") == 2)
check("both checks call the interrupt",
      relay.count("_hermes_kill_segment(sid, _spent, max_turn)") == 2)
check("both checks emit the exact proxy_error",
      relay.count("hermes_overrun_error(max_turn)") == 4)   # status + error, twice

# the event-path check must sit AFTER the done-break (a completed turn is never
# reported as an overrun) and inside the same loop
i_done = relay.index('if action == "done":')
i_evt_check = relay.index("hermes_segment_overrun(_spent, max_turn)",
                          relay.index("hermes_segment_overrun(_spent, max_turn)") + 1)
check("event-path check runs after the done-break", i_evt_check > i_done)

# the tick check must precede the silence guards so the guard that also stops
# Hermes wins when two come due on the same tick
i_tick_check = relay.index("hermes_segment_overrun(_spent, max_turn)")
check("tick check precedes the 60s first-event guard",
      i_tick_check < relay.index("silent >= 60.0"))
check("tick check precedes the 600s silence guard",
      i_tick_check < relay.index("silent >= 600.0"))

check("pause opens when a card appears",
      "if approval_pending and not _was_pending:" in relay
      and "pause_since = _now" in relay)
check("pause closes when the card resolves",
      "pause_total += max(0.0, _now - pause_since)" in relay)
check("pause bookkeeping keys off the SAME approval/clarify set the cards use",
      relay.count('("approval.request", "clarify.request")') == 1)

# the RESET wiring: on a tool event OR a resolved card, and BEFORE the end-of-body
# overrun check (a resetting event must never be judged against the pre-reset clock)
check("the relay resets the segment on a tool event or a resolved card",
      'if _resolved or hermes_segment_resets((ev or {}).get("type")):' in relay)
check("the reset re-arms the clock AND drops the accrued pause",
      "seg_started = _now" in relay and "pause_total = 0.0" in relay)
check("a resolved card is what sets _resolved",
      "_resolved = True" in relay
      and "elif _was_pending and not approval_pending:" in relay)
check("the reset runs BEFORE the event-path overrun check",
      relay.index("hermes_segment_resets(")
      < relay.index("hermes_segment_overrun(_spent, max_turn)",
                    relay.index("hermes_segment_overrun(_spent, max_turn)") + 1))
check("the reset runs AFTER the pause bookkeeping (so a closed pause is not lost "
      "before it is zeroed deliberately)",
      relay.index("pause_total += max(0.0, _now - pause_since)")
      < relay.index("hermes_segment_resets("))
# NEGATIVE: deltas must NOT reset, or the guard is blind to the only thing it catches
check("no reset on message deltas",
      "message.delta" not in relay.split("hermes_segment_resets(")[0][-800:])

# NEGATIVES — the pre-existing guards must be untouched
check("60s first-event guard still present",
      "no response from Hermes within 60s of submit" in relay)
check("600s total-silence hard guard still present (relay-dead case)",
      "hermes turn idle >10min" in relay)
check("the 20s heartbeat still fires on every tick",
      '{"type":"hermes_ping"}' in relay)
check("the fail-safe liveness probe is unchanged",
      "_hermes_session_working(sid)" in relay)
check("panel Stop path untouched",
      "q.request_stop()" in SRC and '"_stop_requested"' in SRC and "stop_at = " in relay)

kill = between("async def _hermes_kill_segment", "async def _hermes_session_working")
check("kill uses session.interrupt, not a stream close",
      '"session.interrupt"' in kill and '{"session_id": sid}' in kill)
check("kill logs to the bridge log",
      "[hermes] generation segment exceeded max_turn_s" in kill)
check("kill is best-effort (an unreachable gateway still ends the turn)",
      "except Exception" in kill)
check("kill never raises into the relay", "raise" not in kill)

# ── the RESET table (the 2026-08-14h revision) ────────────────────────────────
check("tool.start resets the segment", resets("tool.start") is True)
check("tool.complete resets the segment", resets("tool.complete") is True)
check("the reset set is exactly those two", tuple(RESET_EVENTS) == ("tool.start", "tool.complete"))
# THE POINT OF THE REVISION: a research turn must be able to run forever.
for ev in ("message.delta", "message.complete", "agent.step", "thinking.delta",
           "approval.request", "clarify.request", "clarify.expire", "hermes_ping",
           "_stop_requested", "prompt.submit", "tool", "tool.startx", ""):
    check(f"{ev or '(empty)'} does NOT reset the segment", resets(ev) is False)
check("junk types never reset (None)", resets(None) is False)
check("junk types never reset (int)", resets(7) is False)
check("junk types never reset (list)", resets(["tool.start"]) is False)
check("whitespace is tolerated", resets("  tool.start  ") is True)
# a reset makes the clock unable to fire, which IS the guarantee sample asked for
check("a segment reset at t=590 cannot overrun at t=600",
      overrun(spent(600.0, 590.0), 600.0) is False)
check("no reset for 601s DOES overrun",
      overrun(spent(601.0, 0.0), 600.0) is True)

# ── WIRING: motdeck.yaml ─────────────────────────────────────────────────────
YML = (ROOT / "motdeck.yaml").read_text()
check("motdeck.yaml carries a TOP-LEVEL hermes block",
      any(l.rstrip() == "hermes:" for l in YML.splitlines()))
check("motdeck.yaml default is 600",
      any(l.strip().startswith("max_turn_s: 600") for l in YML.splitlines()))
try:
    import yaml as _yaml
    _c = _yaml.safe_load(YML)
    check("motdeck.yaml parses and the guard reads 600 from it",
          max_turn_s(_c) == 600.0)
except ImportError:
    print("  --  pyyaml absent: skipping the live motdeck.yaml read")

# ── WIRING: ship.sh hardening (task 2) ───────────────────────────────────────
# NOTE (2026-08-21 ops slice): ship.sh also gained a contract gate, --restart and a
# reminder line. Those are pinned in bridge/tests/test_ops_hardening.py, not here —
# the checks below stay scoped to the wait-loop/fingerprint hardening this file added.
check("ship waits 90s", "SHIP_WAIT_S=90" in SHIP)
check("ship no longer waits only 30", "seq 1 30" not in SHIP)
check("ship tracks whether the bridge actually came up", 'UP=1; break' in SHIP)
check("ship reports the timeout loudly",
      "BRIDGE CONTROL API DID NOT ANSWER GET /api/status" in SHIP)
check("ship tails the snapshot bridge.log on timeout",
      'tail -15 "$DST/data/logs/bridge.log"' in SHIP)
_ship_timeout = SHIP.index("BRIDGE CONTROL API DID NOT ANSWER GET /api/status")
check("ship says the app was not opened before the timeout exit",
      "The app was not opened" in SHIP
      and SHIP.index("The app was not opened", _ship_timeout)
      < SHIP.index("exit 1", _ship_timeout))
check("ship never claims 'bridge is up' before the UP check",
      SHIP.index('if [[ "$UP" -ne 1 ]]') < SHIP.index("bridge is up"))
check("empty openapi body is NOT hashed",
      'if [[ -z "$API_JSON" ]]' in SHIP
      and "fingerprint unavailable (bridge still starting?)" in SHIP)
# The additive merge moved to one line-preserving transaction helper. Pin both the
# call and the reason the old PyYAML null representer must not return.
check("manifest merge still present",
      'scripts/merge_manifest.py"' in SHIP and '"$ROOT/motdeck.yaml" "$DST/motdeck.yaml"' in SHIP)
check("manifest merge no longer serializes live YAML through a null representer",
      "tag:yaml.org,2002:null" not in SHIP and "safe_dump" not in SHIP)
check("ship never guesses that a Git lock is stale",
      ".git/HEAD.lock" not in SHIP and ".git/index.lock" not in SHIP)
check("recompile rule still newer-than-binary",
      '"$ROOT/app/main.swift" -nt "$APP/Contents/MacOS/MOTDeck"' in SHIP)
check("listener-scoped port kill still present", "-sTCP:LISTEN" in SHIP)
check("motdeck.yaml still never copied wholesale",
      'cp "$ROOT/motdeck.yaml"' not in SHIP)

print(f"\n{PASS} checks passed" + (f", {len(FAIL)} FAILED: {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)
