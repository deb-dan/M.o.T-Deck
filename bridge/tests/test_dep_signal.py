"""THE DEPENDENCY SIGNAL (S22) — the derivation, EXECUTED, and its shell renderer.

docs/research/2026-08-29-isolation-mode.md §6 found that "restart rebinds" is already
true everywhere and that the missing half is the SIGNAL. This suite is the gate on that
signal, and it is journey-shaped rather than function-shaped (doctrine §6): every case
below is a state a real user's machine actually reaches.

What each group guards:

1. THE HEALTHY STATE IS SILENT. The single most important property: with everything up
   and correctly bound, the derivation returns NOTHING. A banner that is always on
   screen is not a signal, it is furniture, and the user stops reading it.
2. THE FOUR UNMET STATES, each with the ONE action that actually fixes it — including
   `swapped`, which is the LIE this whole slice exists to catch: Hermes still wired to
   a model the runner stopped serving, so its dashboard is healthy and every new chat
   fails. (Measured live on Debi's Mac 2026-08-29: config said Qwen3.6-27B…, the runner
   was serving gemma-4-31B… — the first run of this code found it.)
3. THE TWO SILENCE GATES — a component that is not running says nothing (its tab already
   shows "Not reachable yet"), and a dependency that was never INSTALLED says nothing
   (Debi's partial-install principle, ledger S23).
4. THE COPY. Every sentence names the component, the dependency and the fix, in the
   user's words (the tab titles), and every action is one the bridge actually serves.
5. THE WIRING — the route exists, the restart route it points at exists and is a
   COMPOSITION of the audited stop/start, and the Swift shell renders it.

Run: python3 bridge/tests/test_dep_signal.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge.routers.components import (                         # noqa: E402
    NEEDS_SOFT, needs_derive, needs_message)

SWIFT = (ROOT / "app" / "main.swift").read_text()

FAILS = []
CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("FAIL " + label)


# The dependency graph as harness.yaml actually declares it (read once, so a future
# edit to the manifest is caught here rather than in production).
import yaml                                                     # noqa: E402
_CFG = yaml.safe_load((ROOT / "harness.yaml").read_text())
HARD = {n: (c.get("depends_on") or []) for n, c in (_CFG.get("components") or {}).items()}


def up(**kw):
    d = {"installed": True, "running": True}
    d.update(kw)
    return d


def healthy():
    """Everything installed, running, runner loaded — the ordinary Tuesday."""
    return {
        "runner": up(port_up=True, loaded=True),
        "hermes": up(), "odysseus": up(), "searxng": up(), "opencode": up(),
    }


def bound(model="m1", live="m1", ep="http://127.0.0.1:6767/v1",
          live_ep="http://127.0.0.1:6767/v1"):
    return {"hermes": {"model": model, "live_model": live,
                       "endpoint": ep, "live_endpoint": live_ep}}


def derive(comps, bindings=None):
    return needs_derive(comps, HARD, NEEDS_SOFT, bindings or {})


# ── 1. the healthy state is SILENT ───────────────────────────────────────────
def test_silent_when_well():
    ok(derive(healthy(), bound()) == {},
       "everything up and correctly bound derives NO needs at all")
    # …and with no binding readable either: an unreadable config is "no claim",
    # never a claim of trouble. (A Hermes that has never been started has no
    # model.default at all — that must not paint a banner.)
    ok(derive(healthy(), {}) == {}, "an unreadable binding derives nothing")
    ok(derive(healthy(), {"hermes": {"model": None, "live_model": "m1"}}) == {},
       "a half-known binding derives nothing")


# ── 2. the four unmet states ─────────────────────────────────────────────────
def test_runner_down():
    c = healthy()
    c["runner"] = {"installed": True, "running": False, "port_up": False, "loaded": False}
    out = derive(c, bound())
    for who in ("hermes", "odysseus", "opencode"):
        ok(who in out, f"{who} signals when the runner is down")
        n = out[who]["needs"][0]
        ok(n["state"] == "down" and n["action"] == "start" and n["target"] == "runner",
           f"{who}'s offered action is to START the runner")
    # OpenCode is here BY THE SOFT TABLE, and that matters: harness.yaml deliberately
    # gives it depends_on: [] so a Start never drags the runner up. The signal and the
    # start closure are allowed to disagree; only this table may make them.
    ok(HARD.get("opencode") == [], "harness.yaml still declares opencode depends_on: []")
    ok("opencode" in NEEDS_SOFT, "…and the SOFT table is what puts it in the signal")


def test_runner_has_no_model():
    c = healthy()
    c["runner"] = up(port_up=True, loaded=False)
    out = derive(c, bound())
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "no-model", "a live port with nothing loaded is 'no-model', not 'down'")
    ok(n["action"] == "open" and n["target"] == "mc",
       "…and it sends the user to MOT Deck to load one (there is nothing to START)")
    ok("nothing is loaded" in n["text"], "…and the sentence says why")


def test_swapped_is_the_lie_this_catches():
    out = derive(healthy(), bound(model="qwen-x", live="gemma-y"))
    ok("hermes" in out, "a stale model binding IS a need")
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "swapped", "…reported as 'swapped'")
    ok(n["action"] == "restart" and n["target"] == "hermes",
       "…and the fix is restarting HERMES (the Start re-patches its config)")
    ok("qwen-x" in n["text"] and "gemma-y" in n["text"],
       "…and the sentence names BOTH models, so the user can check it themselves")
    # The precision that makes it safe to show: identical ids never fire.
    ok(derive(healthy(), bound(model="same", live="same")) == {},
       "an identical binding is silent (no false 'swapped')")


def test_moved_endpoint():
    out = derive(healthy(), bound(ep="http://127.0.0.1:6767/v1",
                                  live_ep="http://127.0.0.1:6868/v1"))
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "moved" and n["action"] == "restart",
       "a runner that moved ports is 'moved', fixed by a restart")
    ok(derive(healthy(), bound(ep="http://127.0.0.1:6767/v1/",
                               live_ep="http://127.0.0.1:6767/v1")) == {},
       "a trailing slash is not a moved endpoint")


def test_a_dep_that_is_not_the_runner():
    c = healthy()
    c["searxng"] = {"installed": True, "running": False}
    out = derive(c, bound())
    ok("odysseus" in out, "odysseus signals when SearXNG (its other dep) is down")
    n = out["odysseus"]["needs"][0]
    ok(n["dep"] == "searxng" and n["action"] == "start" and n["target"] == "searxng",
       "…and offers to start SearXNG")
    ok("hermes" not in out, "…and Hermes, which does not depend on it, stays silent")


# ── 3. the two silence gates ─────────────────────────────────────────────────
def test_a_stopped_component_says_nothing():
    c = healthy()
    c["runner"] = {"installed": True, "running": False, "port_up": False, "loaded": False}
    c["hermes"] = {"installed": True, "running": False}
    out = derive(c, bound())
    ok("hermes" not in out,
       "a component that is not running gets no banner (its tab already says so)")
    ok("odysseus" in out, "…while the ones that ARE running still speak")


def test_an_uninstalled_dep_says_nothing():
    c = healthy()
    c["searxng"] = {"installed": False, "running": False}
    out = derive(c, bound())
    ok("odysseus" not in out,
       "a dependency the user never installed is not nagged about (S23)")


def test_a_dep_this_build_does_not_know():
    out = needs_derive(healthy(), {"hermes": ["atlantis"]}, {}, {})
    ok(out == {}, "an unknown dependency name is skipped, never crashed on")


# ── 4. the copy ──────────────────────────────────────────────────────────────
def test_every_sentence_is_written_for_her():
    seen = []
    for state in ("down", "no-model", "swapped", "moved", "wat"):
        m = needs_message("hermes", "runner", state,
                          {"bound": "a", "live": "b"})
        seen.append(m)
        ok(m["text"].startswith("Hermes"), f"[{state}] the sentence leads with the tab name")
        ok("the Runner" in m["text"], f"[{state}] …and names the dependency in her words")
        ok(m["action"] in ("start", "restart", "open"),
           f"[{state}] …and offers an action the shell knows")
        ok(m["action_label"] and len(m["action_label"]) < 24,
           f"[{state}] …with a button label that fits a thin banner")
    ok(all("hermes\"" not in m["text"] and "gooseui" not in m["text"] for m in seen),
       "no internal id ever reaches the user's sentence")
    ok("Goose UI" == __import__("bridge.routers.components", fromlist=["x"])
       ._needs_title("gooseui"),
       "…and the title table spells the lanes the way the tab strip does")


# ── 5. the wiring ────────────────────────────────────────────────────────────
def test_routes_exist():
    ok('@app.get("/api/deps")' in _APP_SOURCE, "GET /api/deps is served")
    ok('@app.post("/api/components/{name}/restart")' in _APP_SOURCE,
       "POST /api/components/{name}/restart is served")
    # The restart route must stay a COMPOSITION of the audited stop/start rather than
    # grow its own kill logic — that is the whole safety argument for shipping it.
    body = _APP_SOURCE.split('@app.post("/api/components/{name}/restart")')[1]
    body = body.split("@app.post")[0]
    ok("r = stop(name)" in body and "start(name)" in body,
       "restart composes stop() and start()")
    ok("pkill" not in body and "os.kill" not in body and "_kill_port_listener" not in body,
       "…and contains NO kill logic of its own")
    ok("r.status_code != 200" in body,
       "…and a refused stop (409) does NOT go on to start a second process")


def test_the_shell_renders_it():
    ok("api/deps" in SWIFT, "the shell fetches /api/deps")
    ok("DepsBanner" in SWIFT, "…and has a banner view for it")
    # ADVISORY: the banner must SHORTEN the page, never cover it, and never gate it.
    ok("depsBannerHeight" in SWIFT, "…whose height is a named constant")
    ok('appendingPathComponent("api/components")' in SWIFT
       and 'req.httpMethod = "POST"' in SWIFT,
       "…and its button POSTs to the component lifecycle routes")
    ok('need.action == "restart" ? "restart" : "start"' in SWIFT,
       "…choosing the verb the BRIDGE named, never one of its own")
    # The one thing a future edit must not do: make the banner a modal/blocker.
    for banned in ("NSAlert", "beginSheetModal", "runModal"):
        ok(banned not in SWIFT.split("DepsBanner")[1][:6000],
           f"the banner never becomes a {banned} (it is advisory, always)")


for fn in (test_silent_when_well, test_runner_down, test_runner_has_no_model,
           test_swapped_is_the_lie_this_catches, test_moved_endpoint,
           test_a_dep_that_is_not_the_runner, test_a_stopped_component_says_nothing,
           test_an_uninstalled_dep_says_nothing, test_a_dep_this_build_does_not_know,
           test_every_sentence_is_written_for_her, test_routes_exist,
           test_the_shell_renders_it):
    fn()

if FAILS:
    print(f"\nFAILED {len(FAILS)} of {CHECKS[0]}:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"\ndependency signal: {CHECKS[0]} checks passed")
