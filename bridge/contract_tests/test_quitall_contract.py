"""QUIT EVERYTHING CONTRACT — U55, both doors, and the honesty of the second one.

Debi's ruling (2026-09-02, verbatim): *"i think we should have an option that fully quits
everything too"*. The ruling is BOTH doors: ⌘Q keeps the v1.5.69 behaviour (bridge and
components keep serving), ⌥⌘Q stops everything.

What this file pins, and why each fence exists rather than being obvious:

  1. THE ORDER comes from motdeck.yaml, not from a list in the router. A consumer is
     stopped before what it consumes (hermes and odysseus before the runner and searxng),
     and the runner goes last. A hardcoded order is a second copy of the dependency graph
     that can silently disagree with the manifest.

  2. NO PARTIAL LIES. `quitall_run` may only report `stopped` for a target VERIFIED down
     afterwards, and a single failure must clear `bridge_exiting` — the app reads exactly
     that field to decide whether to close. A quit-everything that reports success while
     a listener is still up is the LIE-TO-USER class, and it is the precise bug the
     runner arm of `stop()` carried until 2026-08-29.

  3. NO NEW KILL CODE. The route stops things ONLY through the existing identity-verified
     paths (routers.components.stop, models.aux_stop, gooseui.gooseui_stop). The only
     signal the router may send itself is a SIGTERM to `os.getpid()` — its own graceful
     shutdown. (CLAUDE.md PROCESS-KILL RULE; the shell-layer half of the same rule lives
     in test_no_name_kills_contract.py.)

  4. THE ZOMBIE FALLBACK is present. This is the route most likely to be invoked while
     the panel holds an open `/api/events` stream, which is exactly what produced three
     surviving bridges on 2026-08-30. A hard exit after a bounded grace is required, and
     it may not be left to a flag on someone else's launch line.

  5. THE APP SIDE actually exists: a menu item, on ⌥⌘Q and not on macOS's Log Out
     shortcut ⇧⌘Q, with the plain ⌘Q quit left alone; a REAL NSAlert (alert()/confirm()
     are silent no-ops in this WKWebView shell); and no unconditional terminate on the
     failure path.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_quitall_contract.py -q
"""
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from bridge.appsrc import FILES as APPSRC_FILES          # noqa: E402
from bridge.routers.quitall import (                     # noqa: E402
    EXTRA_DEPS, quitall_run, schedule_bridge_exit, stop_order)

ROUTER = os.path.join(ROOT, "bridge", "routers", "quitall.py")
APP_PY = os.path.join(ROOT, "bridge", "app.py")
SWIFT = os.path.join(ROOT, "app", "main.swift")


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(path):
    """Executable lines only.

    ⚠️ DOCSTRINGS ARE STRIPPED TOO, NOT JUST `#` COMMENTS, and that is the same principle
    the shell-layer fence states: *"the banned commands are NAMED in the comments on
    purpose — a fix nobody can read gets re-introduced"*. This module's docstring has to
    be able to say the word SIGKILL while explaining why this route never sends one. A
    grep that cannot tell prose from code forces the explanation out of the file, which
    is how the fence ends up outliving the understanding of it.
    """
    src = re.sub(r'(?s)"""(?:.*?)"""', "", _read(path))
    src = re.sub(r"(?s)'''(?:.*?)'''", "", src)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


# ── 1. the order comes from the manifest ─────────────────────────────────────
MANIFEST = {
    "hermes": {"depends_on": ["runner"]},
    "odysseus": {"depends_on": ["runner", "searxng"]},
    "searxng": {"depends_on": None},
    "voicebox": {"depends_on": []},
}


def test_consumers_are_stopped_before_what_they_consume():
    order = stop_order(MANIFEST, EXTRA_DEPS)
    pos = {n: i for i, n in enumerate(order)}
    assert pos["hermes"] < pos["runner"], "hermes must go down before the runner it uses"
    assert pos["odysseus"] < pos["runner"]
    assert pos["odysseus"] < pos["searxng"], "odysseus must go down before searxng"
    assert order[-1] == "runner", (
        "the runner is every consumer's dependency — it must be stopped LAST or the "
        "components above it spend their last seconds talking to a dead model server")


def test_every_node_appears_exactly_once_including_synthetic_ones():
    order = stop_order(MANIFEST, EXTRA_DEPS)
    assert len(order) == len(set(order)), f"a target is listed twice: {order}"
    for n in list(MANIFEST) + ["runner"] + list(EXTRA_DEPS):
        assert n in order, f"{n} would never be stopped"


def test_order_is_deterministic_not_dict_luck():
    """Ties break on MANIFEST ORDER. Without this, the sequence the report claims was
    walked is not the sequence the next run performs."""
    assert stop_order(MANIFEST, EXTRA_DEPS) == stop_order(dict(MANIFEST), dict(EXTRA_DEPS))
    assert stop_order(MANIFEST, EXTRA_DEPS).index("searxng") \
        < stop_order(MANIFEST, EXTRA_DEPS).index("voicebox")


def test_a_dependency_cycle_still_stops_everything():
    """depends_on is hand-written. A loop must not make targets DISAPPEAR from the sweep
    — a skipped stop is a live process under a response that says everything is down."""
    cyc = {"a": {"depends_on": ["b"]}, "b": {"depends_on": ["a"]}, "c": {"depends_on": []}}
    order = stop_order(cyc, {})
    assert set(order) == {"a", "b", "c"}, f"a cycle dropped a target: {order}"


def test_the_real_manifest_orders_the_live_nine():
    import yaml
    c = yaml.safe_load(_read(os.path.join(ROOT, "motdeck.yaml")))
    order = stop_order(c["components"], EXTRA_DEPS)
    assert order[-1] == "runner"
    for name in c["components"]:
        assert name in order, f"{name} is in the manifest but would never be stopped"
    pos = {n: i for i, n in enumerate(order)}
    assert pos["aux"] < pos["runner"] and pos["goose-ui"] < pos["runner"], (
        "the extras ride the runner — they must be stopped ahead of it")


# ── 2. no partial lies ───────────────────────────────────────────────────────
def _run(names, running, claims, still):
    return quitall_run(names,
                       running_fn=lambda n: running[n],
                       stop_fn=lambda n: (claims[n], f"why-{n}"),
                       verify_fn=lambda n: still[n])


def test_all_down_means_ok_and_the_bridge_exits():
    r = _run(["a", "b"], {"a": True, "b": True}, {"a": True, "b": True},
             {"a": False, "b": False})
    assert r["ok"] is True and r["bridge_exiting"] is True
    assert r["stopped"] == ["a", "b"] and r["failed"] == []


def test_one_survivor_blocks_the_bridge_exit_and_is_named():
    r = _run(["a", "b"], {"a": True, "b": True}, {"a": True, "b": True},
             {"a": False, "b": True})
    assert r["ok"] is False, "a surviving component may not report success"
    assert r["bridge_exiting"] is False, (
        "the bridge must stay up on a partial stop — it is the only surface left from "
        "which the user can see and stop the survivor")
    assert r["failed"] == ["b"]
    assert any("b" in s and "STILL RUNNING" in s for s in r["sentences"])
    assert "b" in r["bridge"], "the bridge sentence must name why it stayed up"


def test_a_stop_that_claims_success_but_did_not_stop_is_called_out():
    """The claim and the verification are separate signals, and when they disagree the
    VERIFICATION wins and the disagreement is stated. This is the 2026-08-29 runner bug
    in general form: SIGKILL returns before the socket is gone."""
    r = _run(["a"], {"a": True}, {"a": True}, {"a": True})
    assert r["ok"] is False
    assert any("which was wrong" in s for s in r["sentences"]), (
        "a stop that reported success while the process lived must say so — silently "
        "trusting the claim is how a false green ships")


def test_not_running_is_skipped_not_failed():
    r = _run(["a"], {"a": False}, {"a": True}, {"a": False})
    assert r["ok"] is True and r["skipped"] == ["a"] and r["failed"] == []
    assert any("was not running" in s for s in r["sentences"])


def test_a_refused_stop_on_an_already_dead_target_is_honest_not_a_failure():
    """`stop()` legitimately answers ok:False with "no pid file and no port to kill by"
    for a component that had already exited. That is not a failure to stop."""
    r = _run(["a"], {"a": True}, {"a": False}, {"a": False})
    assert r["ok"] is True and r["failed"] == []
    assert any("did not claim it" in s for s in r["sentences"]), (
        "the discrepancy must still be visible — 'stopped' with no qualifier would be "
        "claiming a stop that never reported one")


def test_every_target_gets_a_sentence():
    order = ["a", "b", "c"]
    r = _run(order, {n: True for n in order}, {n: True for n in order},
             {"a": False, "b": True, "c": False})
    assert len(r["sentences"]) == len(order), "per-component sentences, for every one"


# ── 3. no new kill code ──────────────────────────────────────────────────────
BANNED = [
    (r"\bpkill\b", "pkill — a name match, not identity"),
    (r"\bkillall\b", "killall — a name match"),
    (r"\bpgrep\b", "pgrep — one pipe from a name kill"),
    (r"SIGKILL", "SIGKILL — the delegated stop paths escalate; this route may not"),
    (r"lsof", "lsof — a port sweep belongs behind the ownership check, not here"),
    (r"subprocess", "subprocess — every stop must be a call into the existing lane"),
]


@pytest.mark.parametrize("pat,why", BANNED, ids=[b[1].split(" ")[0] for b in BANNED])
def test_the_router_contains_no_kill_of_its_own(pat, why):
    hits = [m.group(0) for m in re.finditer(pat, _code(ROUTER))]
    assert not hits, (
        f"bridge/routers/quitall.py must not contain {pat!r}: {why}. It stops things "
        "ONLY through routers.components.stop / models.aux_stop / gooseui.gooseui_stop, "
        "which already hold the identity evidence (CLAUDE.md PROCESS-KILL RULE).")


def test_the_only_signal_it_sends_is_to_its_own_pid():
    code = _code(ROUTER)
    for m in re.finditer(r"os\.kill\(([^,]+),", code):
        assert m.group(1).strip() in ("me", "os.getpid()"), (
            f"os.kill({m.group(1)!r}) — this route may signal NOTHING but the bridge "
            "process it is running inside")
    assert "signal.SIGTERM" in code, "the bridge's own exit must be a graceful SIGTERM"


def test_it_delegates_to_the_panels_own_stop_function():
    code = _code(ROUTER)
    assert "from .components import stop as _component_stop" in code, (
        "the per-component stop must be THE stop the panel's Stop button calls — a "
        "second implementation is a second thing that can drift out of the kill rule")
    assert "aux_stop" in code and "gooseui_stop" in code, (
        "the extras must ride their own existing stop routes too")


# ── 4. the zombie fallback ───────────────────────────────────────────────────
def test_the_bridge_exit_is_scheduled_after_the_response_not_during():
    import inspect
    src = inspect.getsource(schedule_bridge_exit)
    assert "threading.Thread" in src and "daemon=True" in src, (
        "the exit must be scheduled off-thread — signalling inside the handler kills the "
        "response the app is waiting for")
    assert "time.sleep(delay)" in src, "the response needs to be on the wire first"


def test_the_hard_exit_fallback_exists_and_releases_the_pidfile():
    """2026-08-30, in general form: uvicorn's graceful shutdown waits for in-flight
    responses and /api/events never finishes. This is the route most likely to be called
    while the panel holds one, so it may not rely on --timeout-graceful-shutdown being
    present on whatever launch line started this bridge."""
    import inspect
    src = inspect.getsource(schedule_bridge_exit)
    assert "os._exit(0)" in src, "no hard exit — a wedged stream would leave a zombie"
    assert "release_claim(ROOT, me)" in src, (
        "the hard exit must use the shared exact-owner release before os._exit")
    assert src.index("os.kill") < src.index("os._exit"), \
        "graceful first, hard exit only as the fallback"


def test_only_one_sweep_can_run_at_a_time():
    """Adversarial pass, 2026-09-02: two overlapping sweeps walk the SAME pidfiles, and
    the second reads a file the first already unlinked — so it reports "not running" for
    a component the first is still killing, and both answer ok. A non-blocking lock turns
    the overlap into an honest 409."""
    code = _code(ROUTER)
    assert "_SWEEP = threading.Lock()" in code
    assert "_SWEEP.acquire(blocking=False)" in code, (
        "the second sweep must be REFUSED, not queued — a caller that waits behind a "
        "60-second sweep looks hung, and the app is already showing progress")
    assert "_SWEEP.release()" in code and "finally:" in code, \
        "a raising sweep must not wedge the lock for the life of the bridge"


def test_the_app_refuses_a_second_quit_while_one_is_in_flight():
    src = _read(SWIFT)
    assert "var quitAllInFlight = false" in src
    body = src[src.index("@objc func quitEverything"):src.index("func confirmQuitEverything")]
    assert "if quitAllInFlight" in body, \
        "⌥⌘Q during a sweep must do nothing, not stack a second confirmation"
    # …and every non-terminating exit clears it, or the menu item is dead for the session
    for marker in ("quitAllInFlight = false", "self.quitAllInFlight = false"):
        assert marker in src
    assert src.count("quitAllInFlight = false") >= 4, (
        "each path that ends WITHOUT quitting (no bridge + cancel, cancel, stay open, "
        "and the initial value) must clear the flag")


def test_the_route_is_registered_in_both_places():
    """A lane missing from app.py's _LANES is unreachable through the facade; one missing
    from appsrc.FILES makes every source-text assertion about it pass VACUOUSLY — which,
    for a lane whose fences are almost all negative, would be a gate that cannot fail."""
    assert '"routers.quitall"' in _read(APP_PY), "not in app.py's _LANES"
    assert "routers/quitall.py" in APPSRC_FILES, "not in bridge/appsrc.py's FILES"
    assert APPSRC_FILES.index("routers/quitall.py") > APPSRC_FILES.index("routers/components.py"), \
        "quitall imports the components lane — it must come after it"


# ── 5. the app side ──────────────────────────────────────────────────────────
def test_the_menu_carries_both_doors():
    src = _read(SWIFT)
    # The LABEL is not this fence's business — the app's display name became "M.O.T" on
    # 2026-09-02 (Debi: the Dock hover), and test_app_identity_contract.py is what keeps
    # this item's wording in step with it. What matters HERE is that plain ⌘Q is still
    # bound to the UNCHANGED terminate (v1.5.69 behaviour is the default door).
    assert re.search(r'addItem\(withTitle: "Quit [^"]+", '
                     r'action: #selector\(NSApplication\.terminate\(_:\)\), '
                     r'keyEquivalent: "q"\)', src), \
        "plain ⌘Q must still be the UNCHANGED quit (v1.5.69 behaviour is the default)"
    assert "Quit Everything (stop all components)" in src, "the second door is missing"
    assert "#selector(AppDelegate.quitEverything(_:))" in src


def test_quit_everything_is_on_option_command_q_and_never_shift_command_q():
    src = _read(SWIFT)
    item = src[src.index("let quitAllItem = NSMenuItem"):]
    item = item[:item.index("appMenu.addItem(quitAllItem)")]
    assert 'keyEquivalent: "q"' in item
    assert "[.command, .option]" in item, "⌥⌘Q is the chosen binding"
    assert ".shift" not in item, (
        "⇧⌘Q is macOS's LOG OUT shortcut — an app action bound there logs the user out "
        "of the Mac when they reach for it")


def test_the_confirmation_is_a_real_nsalert_and_names_what_is_running():
    """alert()/confirm() are silent no-ops in this WKWebView shell, so a panel-side
    confirm returns instantly and always false. And a warning that cannot be checked
    ('this stops everything') is not informed consent."""
    src = _read(SWIFT)
    body = src[src.index("func confirmQuitEverything"):src.index("func showQuitAllSheet")]
    assert "NSAlert()" in body and "runModal()" in body
    assert "running.joined" in body, "the confirmation must list the live processes"
    assert "api/quitall/plan" in src, "the list must be read live from the bridge"


def test_the_app_does_not_quit_on_a_partial_stop():
    src = _read(SWIFT)
    body = src[src.index("func performQuitEverything"):src.index("func applicationWillTerminate")]
    # the only unconditional terminate is on the verified-success branch
    assert '(obj["ok"] as? Bool) == true' in body, \
        "the app must gate its own quit on the bridge's verified ok"
    assert "Stay Open" in body, "the failure path needs a door that is not 'quit anyway'"
    # Again: the second button's wording carries the app's display name (M.O.T since
    # 2026-09-02) and is fenced in test_app_identity_contract.py. The ORDER is what this
    # asserts — the first button added is the default one.
    _anyway = re.search(r'addButton\(withTitle: "Quit [^"]+ Anyway"\)', body)
    assert _anyway, "the 'quit anyway' door disappeared from the partial-stop alert"
    assert body.index("Stay Open") < _anyway.start(), \
        "Stay Open must be the DEFAULT button on a partial stop"
    assert "Lost contact with the bridge" in body, \
        "a dropped connection mid-quit is UNKNOWN, and must not be reported as success"
