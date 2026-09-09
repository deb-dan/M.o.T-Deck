"""ROUTER — status, logs, and the component lifecycle: plan → install → start → stop."""
from __future__ import annotations

from pathlib import Path
import asyncio
import os
import subprocess
import threading
import time
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from ..core.appctx import (BRIDGE_LAUNCH_NONCE, BRIDGE_SCHEMA_VERSION, ROOT, app)
from ..core.events import publish
from ..core.health import _health_track, _probe_timeout, file_state_track
from ..core.hermescfg import hermes_cfg_gen
from ..core.modelid import _live_model_id, _read_regular_json, _runner_engine
from ..core.procs import PROV, _clear_expected, _closure, _expected_path, _kill_port_listener, _mark_expected, _ownership_matches, _pid_alive, _port_alive, _port_alive_sync, _port_listener_pids, _read_ownership, _registry_models, _running, _running_sync, _script, cfg, reap_pidfile
from .nav import nav_gen
from .sampling import _record_load_launch


# ══ RUNNER STATUS HONESTY (U15) ═════════════════════════════════════════════
#
# THE INCIDENT, IN FULL (sample, live, 2026-08-29 — two halves, one root):
#
#   HALF 1. She deleted the resident 27B's weights in LM Studio. MOT Deck stayed GREEN
#   (llama.cpp had it mmap'd and kept serving — true, but not the whole truth); the
#   runner later stopped; the FAILED card still printed the model's name as if it
#   existed; and five Retry clicks failed with the only honest sentence — "model … not
#   in registry", which start_component.sh ALSO emits when the FILE at a registered
#   path is gone — buried in a subprocess's stderr where no surface showed it.
#
#   HALF 2 (found while fixing half 1, and it is the same lie wearing a different hat):
#   she switched to Parable-Qwen3-4B. llama-server loaded it in 1.3s and served it
#   happily. The START SCRIPT nonetheless reported failure, because its readiness poll
#   (start_component.sh's `curl -sf .../v1/models`, no Authorization header) has been
#   401ing against every b10662 runner since that build made /v1/models require the key
#   — 90 tries × 2s = a three-minute wall of "unauthorized: Invalid API Key" in
#   runner.log and a non-zero exit for a runner that was up. On that false failure the
#   switch watcher REVERTED motdeck.yaml's pin to the 27B whose file she had deleted —
#   a revert that could not possibly work — and the card sat on a sticky Failed while
#   `ps` and an authenticated curl both proved the process healthy.
#
# The general lesson, recorded in its general form: AN EXIT CODE IS A REPORT, NOT A
# FACT. Where the app can observe the thing itself — a stat() for a file, an
# authenticated probe for a server — the observation outranks the report, and any
# claim we make to the user must be the observation. Everything below is that rule
# applied three times: to the failure sentence, to the pin, and to the model's file.


LAST_START_FAIL: dict = {}
"""component -> {"at", "rc", "reason", "detail", "model", "path"} for the LAST start
attempt that reported failure. Separate from PROV on purpose: PROV is an overlay that
_provision().clear()s at the top of every run, and the reason a Retry failed must
outlive the Retry that replaced it — that is precisely what sample never got to see."""


def _fail_note(name: str) -> "dict | None":
    """The last recorded start failure for `name`, or None. Cheap dict copy."""
    r = LAST_START_FAIL.get(name)
    return dict(r) if isinstance(r, dict) else None


# ══ U60 — A FAILURE REASON IS RETRACTED WHEN THE THING IS OBSERVABLY UP ══════
#
# THE LIVE BUG (sample, screenshot, 2026-09-02). The runner card read
# "Online · serving Qwen3.5-9B-Q4_0" and, one line below it,
# "no model is pinned — pick one in Models". /api/status agreed with the GREEN half
# of that card in every field — pin = pin_intent and served_id = live_id =
# Qwen3.5-9B-Q4_0,
# running true, health ok — and carried the red half anyway, in `last_error`, with
# `stale: false`, `model: ""`, `path: ""`. So the card was not confused: it was
# faithfully rendering a sentence about a DIFFERENT, EARLIER start attempt, one that
# ran while motdeck.yaml had no runner.model at all, as though it described now.
#
# WHY IT SURVIVED. rc == 0 in _provision pops LAST_START_FAIL — but that is only ONE
# of the ways this app starts something, and it was not the way the runner came up.
# The evidence on the live stack was `prov.runner == {"state": "on", "detail":
# "already running"}`: _provision's `if _running_sync(n, c)` short-circuit, which
# marks the component on and `continue`s WITHOUT clearing anything. The other doors
# in are models.py's _do_switch (a Load from the Models pane runs
# start_component.sh itself and never touches this dict at all) and any start that
# happened outside this process. Every one of them left the sentence standing.
#
# THE GENERAL FORM, and it is the same rule the U15 header already states one field
# over — AN EXIT CODE IS A REPORT, NOT A FACT: a recorded failure is a report about a
# past instant, and it is retracted by the OBSERVATION that the component is up. So
# the retraction cannot live on the success path of one starter; it lives HERE, on
# the read, where every start path's outcome is observed the same way and no future
# starter can forget to call it. That also makes the echo automatic: it runs over
# EVERY component's row in the same loop, not just the runner's.
#
# THE DEBOUNCE is health.py's, for health.py's reason: one probe is not evidence. A
# component must read running-and-ok on FAIL_RETRACT_OK consecutive /api/status polls
# before the reason is thrown away, so a runner that flaps up for one poll cannot
# erase the sentence that explains why it keeps dying. In the window between the
# first good poll and the retraction the sentence is published `stale: true`, which
# the card renders as history ("last start attempt: …") rather than as the current
# state — so at no point is a bare failure sentence shown beside a green dot.
FAIL_RETRACT_OK = 2
_FAIL_OK_STREAK: dict = {}      # component -> consecutive running+ok observations


def clear_start_failure(name: str) -> None:
    """Forget `name`'s recorded start failure and its recovery streak. Call this from
    any path that has just brought a component up; the read-side retraction in
    status() is the backstop for the paths that forget."""
    LAST_START_FAIL.pop(name, None)
    _FAIL_OK_STREAK.pop(name, None)


def fail_note_to_publish(name: str, running_ok: bool,
                         note: "dict | None") -> "dict | None":
    """THE WHOLE RULE, IN ONE CALLABLE (so the gate can execute it rather than read it).
    Given a component's CURRENT observed state, the failure note a card may render:

        stopped / unhealthy          -> the note, as recorded            (stale: False)
        running+ok, first poll       -> the note, marked HISTORY         (stale: True)
        running+ok, FAIL_RETRACT_OK  -> None, and the record is dropped

    Advances the debounce as a side effect — call it once per component per poll."""
    if _retract_track(name, running_ok):
        return None
    if not isinstance(note, dict):
        return None
    if running_ok:
        note = dict(note)
        note["stale"] = True
    return note


def _retract_track(name: str, running_ok: bool) -> bool:
    """Advance `name`'s consecutive running+ok counter; True once the recorded failure
    has been retracted (and it is popped here). A single bad observation forgets the
    streak, exactly as _health_track forgets a miss streak on recovery."""
    if not running_ok:
        _FAIL_OK_STREAK.pop(name, None)
        return False
    n = _FAIL_OK_STREAK.get(name, 0) + 1
    _FAIL_OK_STREAK[name] = n
    if n >= FAIL_RETRACT_OK:
        # ⚠️ THE STREAK IS KEPT (CLAMPED), NOT FORGOTTEN — found by the gate test
        # "…and it does not come back". Popping it here restarts the count at 1 on the
        # very next poll, so a note that reappears for any reason (a re-record, a
        # second reader) would be re-published as history instead of staying retracted.
        # It is only ever cleared by clear_start_failure, i.e. by a START — which is
        # exactly the event that should give a new sentence its full grace again.
        _FAIL_OK_STREAK[name] = FAIL_RETRACT_OK
        LAST_START_FAIL.pop(name, None)
        return True
    return False


def start_failure_reason(output: str, model: str = "", path: str = "",
                         file_state: str = "") -> dict:
    """PURE (unit-tested). A failed start's script output → the ONE sentence the card
    shows, plus the one action that fixes it.

    ⚠️ THIS EXISTS BECAUSE THE ALTERNATIVE SHIPPED AND WAS AWFUL. The switch modal used
    to paste the raw tail, so what sample actually read on screen was
    `2.49.854.040 W srv    operator(): unauthorized: Invalid API Key` — log vomit that
    names no cause, no file and no fix. The raw text is still carried (as `detail`, one
    click away behind View log); what the CARD gets is a sentence.

    `file_state` is health.file_state_track()'s debounced verdict for the pinned model's
    path, and it is what lets the same "not in registry" stderr become two different,
    both-true sentences: the entry is missing from data/models.json, or the entry is
    fine and the FILE it points at is gone. Those want different fixes.

    Returns {"text", "detail", "action", "target", "action_label"}; `target` is a PANEL
    view id, and `action: "open"` never asks the bridge for anything."""
    raw = (output or "").strip()
    tail = raw[-1500:]
    models_action = {"action": "open", "target": "models",
                     "action_label": "Open Models"}

    def out(text, **kw):
        d = {"text": text, "detail": tail}
        d.update(models_action)
        d.update(kw)
        return d

    low = raw.lower()
    who = model or "the pinned model"
    if "not in registry" in low:
        # start_component.sh emits ONE sentence for two different states — see its
        # PYRESOLVE block: `ok = bool(m and path) and isfile/isdir(path)`. So a
        # registered model whose file was deleted lands here too, and saying "not in
        # your registry" about it would send the user to fix the wrong thing.
        if file_state == "gone" and path:
            return out(f"model file missing at {path} — pick another model")
        if file_state == "unknown" and path:
            return out(f"the runner could not read {path} — check the disk it is on, "
                       f"or pick another model")
        if path:
            return out(f"“{who}” did not resolve on disk ({path}) — pick another model")
        return out(f"“{who}” is not in your model registry — rescan, or pick another model")
    if "runner.model not set" in low:
        return out("no model is pinned — pick one in Models")
    if "did not become ready" in low:
        return out("the runner started but never answered its readiness probe — "
                   "see the log for what it said",
                   action="open", target="mc", action_label="Open MOT Deck")
    if "no llama-server binary" in low or "not executable" in low:
        return out("the runner binary is missing — run scripts/install_llamacpp.sh",
                   action="open", target="mc", action_label="Open MOT Deck")
    if "refusing to start the runner on" in low:
        return out("the only llama-server on this machine belongs to another app and "
                   "its build is not the one we are pinned to — run "
                   "scripts/install_llamacpp.sh",
                   action="open", target="mc", action_label="Open MOT Deck")
    # Unknown failure: say the most specific TRUE line we have rather than invent one.
    # An "ERROR:" line is the script's own summary; otherwise the last non-empty line.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    err = next((ln for ln in lines if ln.startswith("ERROR:")), "")
    pick = err[6:].strip() if err else (lines[-1] if lines else "")
    return out(pick[:240] or "it failed without saying why — see the log",
               action="open", target="mc", action_label="Open MOT Deck")


def runner_model_view(c: "dict | None" = None) -> dict:
    """What motdeck.yaml PINS, what the registry says its file is, and whether that
    file is still there — the whole answer in one cheap dict.

    ONE stat() per call, debounced two-strikes by health.file_state_track (a sleeping
    network mount answers ENOENT rather than raising, so a single sample is not
    evidence and must never flip a claim).

    Keys: pin · path · format · file
          ("ok"|"checking"|"gone"|"incomplete"|"unknown"|"unregistered")
          · note (the user-facing sentence, or "")."""
    c = c if isinstance(c, dict) else cfg()
    rc = (c.get("runner") or {}) if isinstance(c.get("runner"), dict) else {}
    pin = str(rc.get("model") or "")
    if not pin:
        return {"pin": "", "path": "", "format": "", "file": "unknown", "note": ""}
    try:
        entry = next((m for m in _registry_models() if m.get("id") == pin), None)
    except Exception:                                                # noqa: BLE001
        entry = None
    if entry is None:
        return {"pin": pin, "path": "", "format": "", "file": "unregistered",
                "note": f"“{pin}” is no longer in your model registry — "
                        f"rescan in Models, or pick another model"}
    path = str(entry.get("path") or "")
    fmt = str(entry.get("format") or "gguf")
    st = file_state_track(f"runner:{pin}", entry)
    note = ""
    if st["state"] == "gone":
        note = (f"model file gone (deleted outside MOT Deck — LM Studio?) — {path}. "
                f"The runner will not start again until you pick another model.")
    elif st["state"] == "incomplete":
        note = (f"model incomplete: {st.get('detail') or 'artifact is structurally broken'}. "
                "The running model may keep serving, but it will not restart until you pick another model.")
    return {"pin": pin, "path": path, "format": fmt, "file": st["state"],
            "reason": st.get("reason"), "detail": st.get("detail"), "note": note}


def runner_serving(c: "dict | None" = None) -> "str | None":
    """The AUTHENTICATED answer to "what is this runner serving right now", or None.

    Wraps core.modelid._live_model_id, which sends runner.api_key — the one probe in
    this app that has been correct since b10662 made /v1/models require it. Used to
    OVERRULE a start script's exit code: a process that answers with a model loaded is
    up, whatever the script that launched it decided to report."""
    c = c if isinstance(c, dict) else cfg()
    port = ((c.get("runner") or {}) if isinstance(c.get("runner"), dict) else {}).get("port")
    if not port:
        return None
    try:
        return _live_model_id(int(port))
    except Exception:                                                # noqa: BLE001
        return None


@app.get("/api/status")
async def status() -> dict:
    import shutil
    c = cfg()
    du = shutil.disk_usage(ROOT)
    out = {
        "bridge": "ok",
        "bridge_schema": BRIDGE_SCHEMA_VERSION,
        "launch_nonce": BRIDGE_LAUNCH_NONCE,
        "disk": {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)},
        # How many times WE have changed Hermes's configuration this process. The
        # Swift shell records it when the Hermes webview loads and reloads that
        # webview when it has increased, because Hermes's own Skills page never
        # refreshes itself (see the _HERMES_CFG_GEN block). Costs nothing to
        # publish here and needs no new route.
        "hermes_config_gen": hermes_cfg_gen(),
        # …and the same carrier for the NAV layout: the shell rebuilds its tab strip
        # when this moves (see the _NAV_GEN block). One int, no new route.
        "nav_gen": nav_gen(),
        "components": {},
    }
    for name, comp in c["components"].items():
        port = comp.get("port") or comp.get("mcp_port")
        expected = _expected_path(name).exists()
        running = ((await _port_alive(int(port), _probe_timeout(name, expected))
                    if port else False) or _pid_alive(name))
        verdict, misses = _health_track(name, expected, running)
        out["components"][name] = {
            "installed": bool(comp.get("installed")),
            "pin": str(comp.get("pin")),
            "running": running,
            # UNCHANGED: the instantaneous fact (expected-up and THIS probe missed).
            "degraded": expected and not running,
            # …and the DEBOUNCED verdict, which is what the panel renders on both the
            # card and the feed, so those two can never tell sample opposite things.
            "health": verdict,
            "misses": misses,
            "port": port,
            # U15: the reason the LAST start attempt failed, as a sentence. None in
            # the ordinary case. It is published even when the component is now up,
            # flagged `stale`, so "it failed, I clicked Retry, it worked" leaves a
            # readable trail instead of a card that silently forgets.
            "last_error": _fail_note(name),
        }
    # M1 runner slot: a managed component (engine per model format since the llamacpp/mlx shift).
    rc = c.get("runner")
    if rc:
        rport = rc.get("port")
        # Probe the runner off the event loop (item D: no blocking on the async loop).
        # `running` (green) now means a model is ACTUALLY loaded, not merely that the
        # port answers — so MC can never show green while nothing is loaded (ISSUE C).
        port_up = await _port_alive(int(rport)) if rport else False
        live_id = (await asyncio.to_thread(_live_model_id, int(rport))) if rport else None
        loaded = bool(live_id)
        # The runner's health is keyed on PORT_UP, exactly as its `degraded` is: a live
        # port with no model yet is "loading", not dead. Same debounce as everything
        # else, so a model switch (port down for a moment) reads as reconnecting rather
        # than painting a permanent "health lost" line in the feed.
        r_verdict, r_misses = _health_track(
            "runner", _expected_path("runner").exists(), port_up)
        # U15/S30 — THE PIN IS AN INTENT, THE SERVED ID IS A FACT.  `pin` now has the
        # same configured-pin meaning as every other component row; `served_id` is the
        # authenticated live answer.  Keep `live_id` as a compatibility alias while
        # first-party readers move to the explicit name.
        mv = await asyncio.to_thread(runner_model_view, c)
        out["components"]["runner"] = {
            "installed": True,
            "pin": mv["pin"],              # configured runner.model — same semantics as peers
            "pin_intent": mv["pin"],       # motdeck.yaml runner.model — INTENT, always
            "served_id": live_id or "",    # authenticated live FACT, or ""
            "live_id": live_id or "",      # compatibility alias; do not add new readers
            "model_path": mv["path"],
            "model_file": mv["file"],      # ok | checking | gone | incomplete | unknown | unregistered
            "model_note": mv["note"],
            "last_error": _fail_note("runner"),
            "running": loaded,
            "loaded": loaded,
            "port_up": port_up,          # process holds the port but may still be loading
            # degraded = the process actually died (not merely mid-load): expected-up
            # AND the port is gone. A live port with no model yet = "loading", not degraded.
            "degraded": _expected_path("runner").exists() and not port_up,
            "health": r_verdict,
            "misses": r_misses,
            "port": rport,
            "kind": "runner",
            "engine": _runner_engine(rc),
        }
    try:  # snapshot; a background provision thread may mutate PROV concurrently
        out["prov"] = {k: dict(v) for k, v in list(PROV.items())}
    except RuntimeError:
        out["prov"] = {}
    # ⚠️ A `failed` OVERLAY IS A REPORT ABOUT A PAST INSTANT. THE PROBE IS NOW (U15).
    # sample's card sat on "Failed" while `ps` and an authenticated curl both showed the
    # runner serving Parable-Qwen3-4B at that very moment — because a start attempt
    # three minutes earlier had (wrongly, see the header block) exited non-zero and
    # nothing ever retracted it. The panel renders `prov.state === 'failed'` ahead of
    # every health signal, so the overlay wins forever.
    #
    # The rule, and it belongs HERE rather than in the panel so every reader gets it:
    # a failure overlay is dropped the moment the component is observably RUNNING.
    # Nothing is lost — the sentence and the raw log move to `last_error`, which the
    # card still shows, marked stale.
    #
    # …and the SENTENCE follows the overlay (U60, above): a component that reads
    # running-and-ok for two polls running has its recorded failure RETRACTED, so no
    # card can ever pair a green dot with a bare failure sentence. One poll of grace
    # publishes it as history instead. This loop is the whole echo sweep: it is keyed
    # on nothing runner-specific, so every component gets the same honesty.
    for n, row in out["components"].items():
        if (out["prov"].get(n) or {}).get("state") == "failed" and row.get("running"):
            out["prov"].pop(n, None)
            if isinstance(row.get("last_error"), dict):
                row["last_error"]["stale"] = True
        running_ok = bool(row.get("running")) and row.get("health") == "ok"
        row["last_error"] = fail_note_to_publish(n, running_ok, row.get("last_error"))
    return out


# ══ THE DEPENDENCY SIGNAL (S22 — docs/research/2026-08-29-isolation-mode.md §6) ══
#
# The research's finding was that "restart rebinds" is ALREADY TRUE everywhere: every
# Start re-derives a component's wiring to the runner (Hermes config patch, Odysseus
# seed, OpenCode provider rewrite, goose env+config per spawn). What was missing is the
# SIGNAL — nothing in the app ever said "this tab is pointed at a runner that is gone,
# or at a model that is no longer loaded", so the tab looked alive while every turn in
# it failed. That is the LIE-TO-USER class, and this block is the answer to it.
#
# EVERYTHING HERE IS DERIVED. It reads what status() above already computed plus
# motdeck.yaml's own `depends_on` and (for Hermes) the binding the component itself has
# on disk. It starts nothing, writes nothing, and issues no probe status() did not
# already issue.
#
# ⚠️ ADVISORY, ALWAYS — sample's advisory-gates ruling (CLAUDE.md) applies verbatim.
# Everything here produces a sentence and ONE suggested action. No caller may use it to
# block, refuse or gate a lane; the shell renders it as a thin dismissable banner ABOVE
# the page (it shortens the webview by 30pt, it never covers it), and the banner
# disappears on its own the moment the need is met.

# HARD deps = motdeck.yaml `depends_on`, which is the START CLOSURE ("bring these up
# first"). SOFT deps are the other half of the truth: a component whose closure is
# deliberately EMPTY can still be useless without the runner. OpenCode is the recorded
# case — motdeck.yaml says `depends_on: []` on purpose ("usable against any provider it
# has configured"), which is right for Start and wrong for a user staring at a picker
# full of local models that cannot answer. Kept as a SEPARATE table on purpose: nothing
# in this file may change what a Start brings up.
#
# ⚠️ ONLY COMPONENTS status() ANSWERS FOR MAY APPEAR HERE. The two goose lanes and
# aider are bridge-supervised CHILDREN, not motdeck.yaml components: they have no row
# in /api/status and their own lifecycle routes are /api/gooseui/* and the PTY sockets,
# so a soft dep on them would derive `needs` that nothing could act on. They are named
# in ledger S24 with the exact seam each one still wants.
NEEDS_SOFT: dict = {
    "opencode": ("runner",),
    # S34: the DeepSeek Harness lane joins the signal, for the SAME reason and by the
    # same reading. motdeck.yaml gives it `depends_on: []` on purpose (it is usable
    # against any provider it has configured), so a Start never drags the runner up —
    # but its seeded 'MOT Deck (local)' route points at :6767, and a picker full of
    # local models that cannot answer is exactly the state this table exists to name.
    # It IS a real motdeck.yaml component with a /api/status row, so it clears the
    # "only components status() answers for" fence above.
    "deepseek": ("runner",),
    # S28: the Goose UI joins the signal. Its status row is SYNTHESISED in deps() from
    # its own lane (it is a bridge-supervised child, not a motdeck.yaml component) and
    # its Restart button is served by restart()'s lane branch — the two things S28b said
    # had to exist first, so this is a sentence with a working action behind it.
    "gooseui": ("runner",),
}

# Lane names restart() accepts even though they are not motdeck.yaml components. The
# value is the lane's OWN pair of audited routes — the only way any of these processes
# is ever stopped (identity-checked pidfile first; never a kill by name).
_LANE_RESTART = {"gooseui": ("bridge.routers.gooseui", "gooseui_stop", "gooseui_start")}

# The names the SENTENCES use. Deliberately the tab titles the user reads in the strip
# (app/main.swift's tabRegistry), not the internal ids — a banner that says "gooseui"
# is a banner written for us rather than for her.
_NEEDS_TITLES = {
    "hermes": "Hermes", "odysseus": "Odysseus", "opencode": "OpenCode",
    "gooseui": "Goose UI", "goose": "Goose CLI", "aider": "Aider",
    "runner": "the Runner", "searxng": "SearXNG", "unsloth": "Unsloth",
    # ⚠️ MUST stay byte-identical to app/main.swift's tab TITLE for this id, or the
    # banner on that tab reads "deepseek" — a sentence written for us, not for her.
    "deepseek": "DeepSeek",
}


def _needs_title(name: str) -> str:
    return _NEEDS_TITLES.get(name, name)


# ── WHICH LANES ACTUALLY NEED A RESTART TO REBIND (S34) ──────────────────────
# Every sentence below used to end "…then restart <who> to rebind", because until now
# it was true of every lane that carries this banner: Hermes, Odysseus and OpenCode all
# read their provider configuration ONCE, at boot. The DeepSeek lane does not — its
# adapter "reads its profiles through a thunk once per operation" and its settings
# provider hot-publishes external edits, so the next turn picks the runner up by itself.
#
# ⚠️ SO THE SHARED CLAUSE BECAME A FALSE INSTRUCTION FOR ONE LANE, and that is the
# LIES-TO-USER class rather than a cosmetic slip: it tells her to do work that cannot
# help, on the one lane where the fix has already happened. The same asymmetry is
# fenced on the write side in routers/models._rebind_deepseek, which deliberately does
# NOT append OpenCode's "restart it to load this" note — this table is that decision
# applied to the READ side, where she actually sees it.
#
# A lane absent from this set is assumed to need a restart, which is the safe default:
# advising a restart that was not needed costs one click, while omitting one that WAS
# needed leaves a lane silently stale.
REBINDS_LIVE = frozenset({"deepseek"})


def _rebind_tail(who: str, comp: str) -> str:
    """PURE. The tail of a 'the dependency is not ready' sentence, for this lane.

    ⚠️ IT OWNS ITS OWN SEPARATOR, and that is not fussiness: the first version
    returned only the clause and the call sites supplied a comma, which produced
    "Start the Runner, DeepSeek picks it up on its next message" — a comma splice in
    a sentence the user reads in a thin banner. One function, one punctuation
    decision, both branches legible."""
    if comp in REBINDS_LIVE:
        return f" — {who} picks it up on its next message, no restart needed."
    return f", then restart {who} to rebind."


def needs_message(comp: str, dep: str, state: str, detail: dict) -> dict:
    """PURE. One unmet dependency → the sentence and the ONE action offered for it.

    The copy lives here rather than in the Swift shell for the reason every other
    user-facing string in this app does: it is testable, it is in one place, and the
    shell that renders it stays dumb enough that a wording fix never needs a rebuild
    of the binary.

    `action` is what the shell does when the button is pressed:
       start   -> POST /api/components/<target>/start
       restart -> POST /api/components/<target>/restart
       open    -> switch to the MOT Deck tab (no request at all)
    """
    who, what = _needs_title(comp), _needs_title(dep)
    if state == "down":
        return {"dep": dep, "state": state,
                "text": f"{who} needs {what} — it isn't running. "
                        f"Start {what}" + _rebind_tail(who, comp),
                "action": "start", "target": dep,
                "action_label": f"Start {what}"}
    if state == "model-gone":
        # U15. The runner is down AND the model it is pinned to has no file on disk, so
        # "Start the Runner" — the sentence this state replaces — is an offer that
        # cannot work. Five clicks proved it. The action is therefore the panel, where
        # a different model can be picked; the shell's `open` lands on MOT Deck, whose
        # runner card carries the Open Models button (see U22 for the deep link).
        where = detail.get("path") or ""
        return {"dep": dep, "state": state,
                "text": (f"{who} needs {what}, and the model {what} is pinned to has no "
                         f"file left on disk"
                         + (f" ({where})" if where else "")
                         + " — pick another model in MOT Deck → Models."),
                "action": "open", "target": "mc",
                "action_label": "Open MOT Deck"}
    if state == "model-unregistered":
        return {"dep": dep, "state": state,
                "text": (f"{who} needs {what}, and the model {what} is pinned to "
                         f"(“{detail.get('bound') or '?'}”) is no longer in the model "
                         f"registry — rescan or pick another model in MOT Deck → Models."),
                "action": "open", "target": "mc",
                "action_label": "Open MOT Deck"}
    if state == "model-unavailable":
        return {"dep": dep, "state": state,
                "text": f"{who} needs {what}, but its pinned model cannot start: "
                        f"{detail.get('detail') or 'artifact unavailable'} — pick another model in MOT Deck → Models.",
                "action": "open", "target": "mc", "action_label": "Open MOT Deck"}
    if state == "no-model":
        return {"dep": dep, "state": state,
                "text": f"{who} needs a model — {what} is up but nothing is loaded. "
                        f"Load one in MOT Deck" + _rebind_tail(who, comp),
                "action": "open", "target": "mc",
                "action_label": "Open MOT Deck"}
    if state == "swapped":
        return {"dep": dep, "state": state,
                "text": f"{who} is still wired to “{detail.get('bound') or '?'}” — "
                        f"{what} is now serving “{detail.get('live') or '?'}”. "
                        f"Restart {who} to rebind.",
                "action": "restart", "target": comp,
                "action_label": f"Restart {who}"}
    if state == "catalog-stale":
        return {"dep": dep, "state": state,
                "text": f"{who} is still using {detail.get('bound') or 'an older catalog'}; "
                        f"M.O.T now has {detail.get('live') or 'a different catalog'}. "
                        f"Restart {who} to load the current model list.",
                "action": "restart", "target": comp,
                "action_label": f"Restart {who}"}
    if state == "substituted":
        return {"dep": dep, "state": state,
                "text": f"{who} requests “{detail.get('bound') or '?'}”, but the "
                        f"single-model runner serves “{detail.get('live') or '?'}”. "
                        "llama.cpp will answer as the loaded model — load the requested "
                        "one in Models, or select the loaded one.",
                "action": "open", "target": "models",
                "action_label": "Open Models"}
    if state == "moved":
        return {"dep": dep, "state": state,
                "text": f"{who} is still wired to {detail.get('bound') or '?'} — "
                        f"{what} now answers on {detail.get('live') or '?'}. "
                        f"Restart {who} to rebind.",
                "action": "restart", "target": comp,
                "action_label": f"Restart {who}"}
    # Unknown state: say the true, minimal thing rather than invent a sentence.
    return {"dep": dep, "state": state,
            "text": f"{who} needs {what}.",
            "action": "open", "target": "mc", "action_label": "Open MOT Deck"}


def needs_derive(comps: dict, hard: dict, soft: dict, bindings: dict) -> dict:
    """PURE. The whole derivation, over plain dicts, so it is unit-testable against
    every state without a runner, a component or a network.

      comps    — status()["components"]: name -> {installed, running, port_up, loaded, …}
      hard     — name -> list of motdeck.yaml depends_on
      soft     — name -> tuple of usefulness deps (NEEDS_SOFT)
      bindings — name -> {"model": <wire id the app is wired to>,
                          "endpoint": <base_url the app is wired to>,
                          "live_model": …, "live_endpoint": …} when we can read the
                 component's OWN config; absent when we cannot (never guessed).

    Returns {name: {"needs": [...]}} for components that HAVE an unmet need, and
    nothing at all for the rest — an empty map is the healthy state and the shell
    draws nothing for it.

    TWO GATES, both deliberate:
      * a component that is NOT RUNNING gets no needs. Its tab already shows the
        shell's own "Not reachable yet" page; a second sentence about its runner is
        noise stacked on a state the user can already see.
      * a dependency that is NOT INSTALLED is skipped. sample's partial-install
        principle (ledger S23): "not everyone will install everything", and nagging
        about a component someone deliberately never installed is the same defect as
        a lie, one notch quieter.
    """
    out: dict = {}
    names = set(hard) | set(soft)
    for name in sorted(names):
        me = comps.get(name) or {}
        if not me.get("running"):
            continue
        needs = []
        deps = list(hard.get(name) or ()) + [d for d in (soft.get(name) or ())
                                             if d not in (hard.get(name) or ())]
        for dep in deps:
            d = comps.get(dep)
            if d is None:
                continue                      # a dep this build does not know about
            if dep == "runner":
                if not d.get("port_up"):
                    # U15: WHY it is down changes what we may offer. A runner whose
                    # pinned model has no file cannot be started, so offering Start is
                    # a dead end — the exact dead end sample clicked five times.
                    mf = d.get("model_file")
                    if mf == "gone":
                        needs.append(needs_message(
                            name, dep, "model-gone",
                            {"path": d.get("model_path") or "",
                             "bound": d.get("pin_intent") or ""}))
                    elif mf == "unregistered":
                        needs.append(needs_message(
                            name, dep, "model-unregistered",
                            {"bound": d.get("pin_intent") or ""}))
                    elif mf in ("incomplete", "unknown"):
                        needs.append(needs_message(
                            name, dep, "model-unavailable",
                            {"detail": d.get("model_note") or "model artifact is unavailable"}))
                    else:
                        needs.append(needs_message(name, dep, "down", {}))
                    continue
                if not d.get("loaded"):
                    needs.append(needs_message(name, dep, "no-model", {}))
                    continue
                b = bindings.get(name) or {}
                catalog, live_catalog = b.get("catalog"), b.get("live_catalog")
                if catalog and live_catalog and catalog != live_catalog:
                    needs.append(needs_message(name, dep, "catalog-stale",
                                               {"bound": catalog, "live": live_catalog}))
                    continue
                bound, live = b.get("model"), b.get("live_model")
                if bound and live and bound != live:
                    state = ("substituted" if b.get("mismatch") == "substituted"
                             else "swapped")
                    needs.append(needs_message(name, dep, state,
                                               {"bound": bound, "live": live}))
                    continue
                ep, live_ep = b.get("endpoint"), b.get("live_endpoint")
                if ep and live_ep and ep.rstrip("/") != live_ep.rstrip("/"):
                    needs.append(needs_message(name, dep, "moved",
                                               {"bound": ep, "live": live_ep}))
                continue
            if not d.get("installed"):
                continue                      # partial-install honesty (S23)
            if not d.get("running"):
                needs.append(needs_message(name, dep, "down", {}))
        if needs:
            out[name] = {"needs": needs}
    return out


def _hermes_binding(c: dict, live_model: "str | None") -> dict:
    """What Hermes's OWN config says it is wired to, read-only, never guessed.

    This is the one component whose binding we can read cheaply and exactly: Start
    patches `model.default` / `model.base_url` in ~/.hermes/config.yaml and Hermes
    reads them at use-time, so a mismatch against the live runner is not a heuristic —
    it is the reason every new Hermes chat would fail. Anything unreadable returns {},
    which the derivation treats as "no claim" rather than as a problem.

    Odysseus's equivalent binding lives inside its sqlite DB behind its admin API and
    is NOT read here — see ledger S24."""
    from ..core.hermescfg import _hermes_config_path
    from ..core.modelid import wire_model_id
    try:
        import yaml
        raw = yaml.safe_load(Path(_hermes_config_path()).read_text()) or {}
        m = raw.get("model") or {}
    except Exception:                                                # noqa: BLE001
        return {}
    rc = c.get("runner") or {}
    try:
        live_wire = wire_model_id(live_model or "", _registry_models())
    except Exception:                                                # noqa: BLE001
        live_wire = live_model or ""
    return {
        "model": str(m.get("default") or "") or None,
        "live_model": live_wire or None,
        "mismatch": "substituted",
        "endpoint": str(m.get("base_url") or "") or None,
        "live_endpoint": (f"http://127.0.0.1:{rc.get('port')}/v1"
                          if rc.get("port") else None),
    }


# ══ THE OTHER THREE BINDINGS (S28, the post-switch coherence audit §2 slice 2) ══
#
# THE COVERAGE GAP, IN ONE SENTENCE: `bindings` had exactly ONE reader (Hermes), and
# Hermes is the one app whose Start arm already prefers the live runner over the pin —
# so the signal built to catch a stale binding could only ever fire for the app that
# self-heals. On 2026-08-29 the runner served Parable while Odysseus's default, the
# Goose UI chip and OpenCode's picker all named a 27B whose file had been deleted, and
# /api/deps answered `{"components":{}}`. All-healthy, and every word of it wrong.
#
# ⚠️ CHEAP READS ONLY, AND NO APP HAS TO BE RUNNING. The S24 note ("Odysseus's binding
# lives behind its admin API") was stale: all three of these are ordinary files this
# audit read in place — a settings.json, a config.yaml, an opencode.json. No admin API,
# no probe, no lock. An unreadable file returns {} = NO CLAIM, never a problem: the
# derivation only ever accuses when it can name BOTH sides.
#
# ⚠️ TWO STRIKES BEFORE WE ACCUSE (the health.py discipline, applied to files instead of
# probes). Every one of these files is REWRITTEN by a seeder during a component Start —
# the exact moment a poll is most likely to land — so a single read showing a stale
# value can be a torn write or a file caught mid-rename. `_bind_track` requires the SAME
# mismatch on two consecutive polls before it derives a sentence; a value that agrees
# forgets the streak instantly. Hermes deliberately keeps its un-debounced behaviour:
# its binding has been shipped and gate-tested that way since v1.5.55, and its patcher
# writes through a temp file it does not rename mid-key.
BIND_MISS_ACCUSE = 2                 # consecutive mismatched reads before we say so
_BIND_MISS: dict = {}                # component -> (bound, live, consecutive misses)


def bind_confirmed(prev, bound, live, at: int = BIND_MISS_ACCUSE) -> tuple:
    """PURE (unit-tested). (next_state, say_it) for one component's binding read.

    `prev` is the tuple this function last returned's first element, or None. A miss
    only counts toward the accusation while it is the SAME pair — a binding that
    changes between polls is a component mid-restart, not a stale binding, and its
    streak starts over. Anything unreadable (either side falsy) forgets the streak."""
    if not bound or not live or bound == live:
        return None, False
    if prev and prev[0] == bound and prev[1] == live:
        n = prev[2] + 1
    else:
        n = 1
    return (bound, live, n), n >= at


def _bind_track(name: str, b: dict) -> dict:
    """Apply the two-strike gate to a model or runtime-catalog comparison.

    Returns the binding unchanged once confirmed, or suppresses the mismatched half
    on the first observation. Endpoint drift is left alone: it is not sourced from a
    seeder rewrite and therefore is not vulnerable to a torn-read window.
    """
    bound = b.get("model") or b.get("catalog")
    live = b.get("live_model") or b.get("live_catalog")
    state, say = bind_confirmed(_BIND_MISS.get(name), bound, live)
    if state is None:
        _BIND_MISS.pop(name, None)
    else:
        _BIND_MISS[name] = state
    if state is not None and not say:
        b = dict(b)
        if b.get("model"):
            b["model"] = None        # seen once — not yet something we will say aloud
        if b.get("catalog"):
            b["catalog"] = None
    return b


# ⚠️ THE INVARIANT EVERY READER BELOW OBEYS, AND THE ONE THE LIVE WALK ADDED:
# A COMPONENT ONLY GETS A `swapped` SENTENCE WHEN ITS OWN RESTART CAN CLEAR IT.
# `swapped`'s single action is "Restart X to rebind"; if X's Start would HONOUR the
# value we are complaining about, the banner is permanent and the button provably does
# nothing (S20's dead-button defect, and this slice nearly shipped three of them).
# A valid picker choice that Start honours is different: it gets a `substituted`
# sentence with an Open Models action, never the dead-end Restart action.
# Here the three persistent pickers are requests, not wiring that a restart repairs:
#   odysseus  — the seeder deliberately honours an existing default.
#   gooseui   — `providers.<slug>.model` is goose's user-owned selection.
#   opencode  — `/config` is the running child's current default selection.
# Their mismatch is therefore `substituted`, never `swapped`. OpenCode's separate
# `/provider` catalogue can still be stale; that state really is repaired by Restart.


def _ody_binding(live_wire: str) -> dict:
    """Odysseus's OWN binding: vendor/odysseus/data/settings.json → `default_model`.

    Compared ONLY when `default_endpoint_id` is our own `local-jan` row: a user who
    pointed Odysseus at somebody else's endpoint is not wired to our runner at all, and
    telling them their model disagrees with ours would be a sentence about nothing."""
    import json as _json
    try:
        s = _json.loads((ROOT / "vendor" / "odysseus" / "data" / "settings.json")
                        .read_text())
    except Exception:                                                # noqa: BLE001
        return {}
    if not isinstance(s, dict):
        return {}
    if str(s.get("default_endpoint_id") or "").strip() != "local-jan":
        return {}
    cur = str(s.get("default_model") or "").strip()
    # The seeder may deliberately honour this value. That means Restart cannot repair
    # a mismatch; it does NOT mean llama.cpp stops substituting the resident model.
    return {"model": cur or None, "live_model": live_wire or None,
            "mismatch": "substituted"}


def _goose_binding(live_wire: str) -> dict:
    """The Goose UI (embed lane) binding: its fenced config.yaml
    `providers.<active_provider>.model` — the key goose itself writes when a model is
    picked, and the one the chip renders.

    Read only while the active provider IS ours: goose's own picker holding another
    provider's model is that provider's business."""
    from .. import gooseprov as _p
    try:
        text = (ROOT / "data" / "goose" / "ui-home" / "goose" / "config"
                / "config.yaml").read_text()
    except Exception:                                                # noqa: BLE001
        return {}
    active = _p.active_provider(text)
    if active not in (_p.PROVIDER_NAME, _p.LEGACY_PROVIDER):
        return {}
    cur = _p.provider_model(text, active)
    if not cur:
        return {}
    return {"model": cur, "live_model": live_wire or None,
            "mismatch": "substituted"}


def _opencode_model_from_config(data) -> str:
    """PURE: return OpenCode's default only when it belongs to our provider."""
    if not isinstance(data, dict):
        return ""
    value = str(data.get("model") or "").strip()
    prefix = "llama.cpp/"
    return value[len(prefix):] if value.startswith(prefix) else ""


def _opencode_runtime_model(port: int) -> str:
    """Read the running child's own /config, bound to its launch provenance.

    The file on disk is not authority for an already-running OpenCode. Ownership is
    rechecked after the response so a process replacement cannot turn a foreign
    listener's JSON into a claim shown by this app.
    """
    from urllib.request import Request, urlopen
    owner = _read_ownership("opencode")
    if not owner or not _ownership_matches(owner[0], "opencode"):
        return ""
    try:
        import json as _json
        req = Request(f"http://127.0.0.1:{int(port)}/config",
                      headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.5) as response:
            if getattr(response, "status", 200) != 200:
                return ""
            data = _json.loads(response.read(1024 * 1024).decode("utf-8"))
    except Exception:                                                # noqa: BLE001
        return ""
    after = _read_ownership("opencode")
    if after != owner or not _ownership_matches(owner[0], "opencode"):
        return ""
    return _opencode_model_from_config(data)


def _opencode_binding(live_wire: str, requested_model: str = "") -> dict:
    """OpenCode's live catalog, bound to the exact child that reported it.

    The config on disk may already be fresh while an older process still holds its
    boot-time catalog. ``start_component.sh`` records the real ``/provider`` response
    after launch and binds it to the process ownership stamp; that is the evidence a
    Restart can actually change.
    """
    try:
        d = _read_regular_json(ROOT / "data" / "opencode.runtime-catalog.json")
    except Exception:                                                # noqa: BLE001
        return {}
    owner = _read_ownership("opencode")
    if (not isinstance(d, dict) or d.get("v") != 1
            or isinstance(d.get("pid"), bool) or not isinstance(d.get("pid"), int)
            or not isinstance(d.get("birth"), str)
            or not owner or (d["pid"], d["birth"]) != owner
            or not _ownership_matches(d["pid"], "opencode")
            or not isinstance(d.get("models"), list)
            or any(not isinstance(k, str) for k in d["models"])):
        return {}
    try:
        from ..core.modelreg import offerable, opencode_model_key
        expected = sorted(opencode_model_key(m.get("id"))
                          for m in offerable(_registry_models()))
    except Exception:                                                # noqa: BLE001
        return {}
    if not expected:
        expected = ["motdeck-runner"]
    actual = sorted(set(d["models"]))
    connected = d.get("connected") is True
    out = {}
    if not connected or actual != expected:
        missing = sorted(set(expected) - set(actual))
        stale = sorted(set(actual) - set(expected))
        out.update({
            "catalog": "OpenCode runtime " + ("connected" if connected else "disconnected")
                       + f" · {len(actual)} model(s)",
            "live_catalog": f"M.O.T registry · {len(expected)} model(s)",
            "catalog_missing": missing[:3], "catalog_stale": stale[:3],
        })
    if requested_model:
        out.update({"model": requested_model, "live_model": live_wire or None,
                    "mismatch": "substituted"})
    return out


@app.get("/api/deps")
async def deps() -> dict:
    """The dependency signal: per-component UNMET needs, derived from /api/status.

    It calls status(), then performs one provenance-bound loopback read from a running
    OpenCode child's `/config`; an on-disk config cannot describe an already-running
    process. The read runs off the event loop and fails to silence. The Swift shell
    polls this only while a tab that CAN carry a banner is on screen, at the same slow
    cadence as its other polls (app/main.swift's depsPoll).

    `components` is empty in the healthy state — that is the whole contract the shell
    needs, and an older shell that has never heard of this route is unaffected."""
    st = await status()
    c = cfg()
    hard = {n: (comp.get("depends_on") or [])
            for n, comp in (c.get("components") or {}).items()}
    # S30: the dependency graph follows the authenticated served identity, never the
    # configured pin.  The two may differ during a switch, failed restart, or explicit
    # pin drift and that distinction is the whole reason this field exists.
    live = (st.get("components", {}).get("runner") or {}).get("served_id")
    loaded = (st.get("components", {}).get("runner") or {}).get("loaded")
    comps = dict(st.get("components", {}))
    bindings = {}
    hb = _hermes_binding(c, live if loaded else None)
    if hb:
        bindings["hermes"] = hb
    # The other three, S28/U38/U13-U20. Odysseus and Goose read their own persisted
    # bindings; OpenCode reads its exact-child `/provider` catalogue plus `/config`
    # default. Each is two-strike gated and returns {} rather than guessing when its
    # evidence cannot be validated.
    live_wire = ""
    if loaded and live:
        from ..core.modelid import wire_model_id
        try:
            live_wire = wire_model_id(live, _registry_models())
        except Exception:                                            # noqa: BLE001
            live_wire = live
    opencode_port = int(((c.get("components") or {}).get("opencode") or {})
                        .get("port") or 0)
    opencode_model = (await asyncio.to_thread(_opencode_runtime_model, opencode_port)
                      if opencode_port and (comps.get("opencode") or {}).get("running")
                      else "")
    for _name, _read in (("odysseus", _ody_binding), ("gooseui", _goose_binding),
                         ("opencode", lambda lm: _opencode_binding(lm, opencode_model))):
        try:
            b = _read(live_wire)
        except Exception:                                            # noqa: BLE001
            b = {}
        if b:
            bindings[_name] = _bind_track(_name, b)
    # THE GOOSE UI IS A BRIDGE-SUPERVISED CHILD, NOT A motdeck.yaml COMPONENT — it has
    # no /api/status row, which is exactly why S28b warned that deriving a need for it
    # would render a button with nothing behind it. Both halves are supplied here: a
    # synthetic row (installed + alive, read from its own lane, no probe of ours) and a
    # restart() that accepts the lane name and delegates to the lane's OWN audited
    # stop/start routes (never a kill by name — the process-kill rule).
    if "gooseui" not in comps:
        try:
            from . import gooseui as _gui
            comps["gooseui"] = {"installed": bool(_gui._ui and
                                                  _gui._ui.is_installed(ROOT)[0]),
                                "running": bool(_gui._alive())}
        except Exception:                                            # noqa: BLE001
            pass
    return {"components": needs_derive(comps, hard, NEEDS_SOFT, bindings)}


@app.get("/api/logs/{name}")
def logs(name: str, lines: int = 40) -> dict:
    # "guard" = the path-guard audit trail (one JSON line per out-of-allowlist write).
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    if not f.exists():
        return {"lines": []}
    return {"lines": f.read_text(errors="replace").splitlines()[-lines:]}


_LOG_NAMES = ("bridge", "hermes", "odysseus", "searxng", "runner", "guard",
              "voicestudio", "voicebox",
              # install-time log (voicebox's fragile dep graph writes here — must be
              # viewable in-panel, not just from a terminal; Fable QA fix 2026-08-07)
              "voicebox-install",
              # the resident TTS worker's stderr — the ONLY place the engine's own
              # traceback lands now that stdout is protocol-only
              "voice-worker",
              # music-engine install (multi-GB downloads + a cmake build) — same
              # rule as voicebox-install: an install log for a slow, fragile step
              # must be readable in-panel, not only from a terminal
              "music-install",
              # the two optional creative/training tabs (2026-08-20). Both are
              # multi-GB online-only installs, so their install logs follow the
              # voicebox-install rule and must be viewable in-panel too.
              "comfyui", "comfyui-install",
              "unsloth", "unsloth-install",
              # the aider lane: one line per PTY session (start/exit/teardown) plus the
              # online-only install log — same voicebox-install rule.
              "aider", "aider-install",
              # the goose lane: identical shape to aider's — one line per PTY session
              # plus the online-only, sha-verified binary install.
              "goose", "goose-install",
              # Goose UI has three distinct failure seams: bridge-owned lifecycle,
              # the renderer server's stderr, and its online-only build/install.
              # Its own failure page names these files, so the panel must expose the
              # same narrowly allowlisted names rather than sending the user to shell.
              "gooseui", "gooseui-serve", "goose-ui-install",
              # the OpenCode tab: its server log + the online-only binary install
              # (same voicebox-install rule — a download install must be readable
              # in-panel, not only from a terminal).
              "opencode", "opencode-install",
              # the DeepSeek Harness tab: its server log + the online-only npm install.
              # The install log matters MORE here than anywhere else in this tuple: it
              # is a ~7-minute, 455-package npm resolve, and without a panel-viewable
              # log the user watches a spinner with no way to tell slow from stuck.
              "deepseek", "deepseek-install",
              # LOffice's boot beacon (bridge/office.py DIAG_LOG_NAME). The page phones
              # home at every step of its own boot; this is where that trace lands, and
              # it must be readable in-panel because the tab it describes may be showing
              # nothing at all.
              "loffice-boot")


@app.post("/api/logs/{name}/clear")
def logs_clear(name: str) -> JSONResponse:
    """Truncate a log file (sample request 2026-08-06: clear/export on every source).
    Truncate-not-delete: a component holding the fd keeps appending to the same
    inode, so deletion would silently orphan its future output."""
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    try:
        if f.exists():
            with open(f, "w"):
                pass
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


@app.post("/api/logs/{name}/export")
def logs_export(name: str) -> JSONResponse:
    """Copy a log to ~/Downloads/motdeck-logs/<name>-<UTC ts>.log and return the
    path (the panel then offers Show-in-Folder via the existing /api/open gate)."""
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    src = ROOT / "data" / "logs" / f"{name}.log"
    try:
        import shutil, datetime as _dt
        outdir = Path.home() / "Downloads" / "motdeck-logs"
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = outdir / f"{name}-{stamp}.log"
        if src.exists():
            shutil.copyfile(src, dest)
        else:
            dest.write_text("")
        return JSONResponse({"ok": True, "path": str(dest)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


@app.get("/api/components/{name}/plan")
def install_plan(name: str) -> dict:
    """Dry-run: return the install plan text without executing anything."""
    plans = {
        "hermes": [
            "Create isolated venv at data/hermes-venv",
            "pip install vendor/hermes (a few hundred MB of dependencies)",
            "Build Hermes's own web dashboard UI (npm --workspace web → web_dist, gitignored)",
            "Model provider points at the runner endpoint (patched on Start)",
            "Serve on port 9119 when started (hermes dashboard: web UI + JSON-RPC/WS API)",
        ],
        "odysseus": [
            "Create isolated venv at data/odysseus-venv",
            "pip install vendor/odysseus requirements (+ ddgs for web search)",
            "Run Odysseus setup (creates admin account, prints temp password to log)",
            "Serve natively on port 7860 (Metal-accelerated Cookbook)",
        ],
        "searxng": [
            "Clone searxng source into vendor/searxng (not on PyPI)",
            "Create venv data/searxng-venv + editable install (compiles some deps)",
            "Write localhost settings.yml (port 8080, JSON API on, limiter off)",
            "Serve privately on 127.0.0.1:8080 — Odysseus prefers it over DuckDuckGo automatically",
        ],
        "voicestudio": [
            "OPTIONAL voice component — license AGPL-3.0-only (composed over HTTP, never modified)",
            "Shallow-clone vendor/voicestudio at the pinned tag (not a submodule)",
            "Create venv data/voicestudio-venv + install its deps: torch, transformers, "
            "whisperx, pyannote, demucs, sherpa-onnx, mlx — roughly 5-8GB, needs ~10GB free",
            "Provide ffmpeg with NO Homebrew: reuse yours if you have one, else install "
            "the imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and "
            "copy the binary to data/ffmpeg/",
            "Build its web UI with bun: reuse a bun already on your PATH, else download "
            "the pinned bun release (~35MB) into data/bun/ — never Homebrew, never sudo, "
            "nothing written outside this project folder (if that download fails the "
            "backend still boots and serves a stub page)",
            "Serve on 127.0.0.1:3900 when started (API + UI on one port, loopback only, no auth)",
            "Speech models (~2.4GB) download later, on first use",
        ],
        "voicebox": [
            "OPTIONAL voice component — license MIT (composed over HTTP, never modified)",
            "Shallow-clone vendor/voicebox at the pinned tag (not a submodule)",
            "Create venv data/voicebox-venv and mirror upstream's own pip recipe: "
            "requirements.txt, then chatterbox-tts + hume-tada --no-deps, then (Apple "
            "Silicon) the MLX extras + mlx-audio --no-deps, then Qwen3-TTS from git",
            "KNOWN-FRAGILE: five dependencies need --no-deps / git URLs / a custom "
            "package index — this install is ONLINE-ONLY and can fail on upstream pin "
            "conflicts (upstream last shipped 2026-04-26); failures print the log path",
            "Provide ffmpeg with NO Homebrew: reuse yours if you have one, else install "
            "the imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and "
            "copy the binary to data/ffmpeg/ (the start script puts it on its PATH)",
            "Build its web UI with bun and copy web/dist → frontend/: reuse a bun already "
            "on your PATH, else download the pinned bun release (~35MB) into data/bun/ — "
            "never Homebrew, never sudo, nothing written outside this project folder "
            "(if that download fails the JSON API and /mcp still work)",
            "Serve on 127.0.0.1:17493 when started — NO AUTHENTICATION: /speak, "
            "/transcribe and /mcp are open to anything reaching the port, loopback only",
        ],
        "comfyui": [
            "OPTIONAL image/video component — license GPL-3.0. Composed at ARM'S LENGTH "
            "ONLY: a separate process reached over HTTP, never modified, never lifted "
            "from (the same posture MOT Deck takes with SearXNG's AGPL)",
            "Shallow-clone vendor/comfyui at the pinned tag (not a submodule)",
            "Create venv data/comfyui-venv + install its deps: torch, torchvision, "
            "torchaudio, transformers, safetensors and its SPA (which ships as a pip "
            "package — no npm/bun build) — roughly 4-6GB of wheels, ONLINE ONLY",
            "On Apple Silicon, install a PyTorch NIGHTLY build first because upstream's "
            "own README says to; falls back to stable PyPI torch if that index is "
            "unreachable. A nightly is a FLOATING build, not a pin we control",
            "Create data/comfyui/ as its base directory (models, output, input, user) so "
            "it never writes into vendor/",
            "Serve on 127.0.0.1:8188 when started (UI + API on one port, loopback only, "
            "no authentication)",
            "Its models load in ITS process, so their RAM is OUTSIDE MOT Deck "
            "model-RAM ledger (memory.budget_gb) — the same known limit the voice "
            "components have",
            "Image/video models are NOT downloaded here; you add them later, on first use",
        ],
        "unsloth": [
            "OPTIONAL training/serving studio — Unsloth Studio is AGPL-3.0-only (the "
            "training library is Apache-2.0). Composed at ARM'S LENGTH ONLY: a separate "
            "process reached over HTTP, never modified",
            "Shallow-clone vendor/unsloth at the pinned tag (not a submodule)",
            "Create venv data/unsloth-home/unsloth_studio and pip install -e "
            "vendor/unsloth[studio] — upstream's own declared server stack (fastapi, "
            "uvicorn, datasets, pandas, matplotlib, pymupdf, fastmcp …), a few hundred "
            "MB. The heavy training extras are NOT installed: the tab only needs the "
            "Studio server",
            "data/unsloth-home is this component's ISOLATED home (UNSLOTH_STUDIO_HOME "
            "at launch): its engines, login state and outputs live there — never in "
            "~/.unsloth, which belongs to the standalone Unsloth app on :8888",
            "Build its React SPA with bun: reuse a bun already on your PATH, else "
            "download the pinned bun release (~35MB) into data/bun/ — never Homebrew, "
            "never sudo, nothing written outside this project folder",
            "UNLIKE the voice components a missing SPA build is FATAL — Unsloth refuses "
            "a web-UI launch without it. The install still finishes, but Start says so "
            "and points at data/logs/unsloth-install.log",
            "We deliberately do NOT run upstream's install.sh (it builds its own install "
            "root, writes shell shims and downloads a forked, floating-tag llama.cpp plus "
            "its own Node) and never run 'unsloth start' — that is its agent-wiring path "
            "and it would relocate HERMES_HOME; your ~/.hermes is never touched",
            "Serve on 127.0.0.1:8899 when started. Studio has its OWN bearer login, "
            "handled inside its own UI; on a loopback launch its page auto-fills the "
            "bootstrap credential",
            "It can download its own llama.cpp and models into its own dirs — contained, "
            "but those weights are invisible to MOT Deck model-RAM ledger",
        ],
        "opencode": [
            "OPTIONAL second coding lane — license MIT. Not a source checkout and not a "
            "venv: upstream ships a PREBUILT native binary per platform on npm, so this "
            "downloads two npm tarballs (~46MB), verifies npm's own sha1, and extracts "
            "ONE ~144MB executable to data/opencode/bin/",
            "⚠ IT REQUIRES A TOOL-CALLING MODEL. Every edit it makes is a native tool "
            "call and there is NO text fallback — on a model without tool support it "
            "will look BROKEN rather than merely worse. Use a model showing the green "
            "'tools' pill in Models (aider is the lane that works without one)",
            "ONLINE-ONLY, and it stays online-ish: it installs its provider package "
            "(@ai-sdk/openai-compatible) on first use with npm's own resolver. That "
            "download is UNPINNED — it is the one floating dependency in this lane",
            "Everything it writes is redirected into data/opencode/xdg (config, cache, "
            "session db) by the XDG variables the start script sets — your ~/.config and "
            "~/.cache are never touched",
            "On Start it is pointed at MOT Deck runner (127.0.0.1:6767) with every "
            "model in your registry listed, exactly like Hermes and Odysseus. The "
            "provider it writes is called `llama.cpp` and shows up in OpenCode's own "
            "Settings → Providers as CONNECTED (tag: config); its model picker should "
            "then list your models by their registry names. If it instead offers "
            "OpenCode's own Zen models (Big Pickle, gpt-5…), the config did not reach "
            "it — the Start log says so in one line, see the opencode log",
            "The provider is written TWICE on purpose — into its private global config "
            "(data/opencode/xdg/config/opencode/opencode.json) and into "
            "data/opencode-workspace/opencode.json — so one of the two landing is "
            "enough. Only the global copy carries the default model, because OpenCode "
            "writes your own model choice back to that same file",
            "Its auto-updater is disabled two ways (config key + environment flag) "
            "because the version is pinned in motdeck.yaml — never use its in-app upgrade",
            "Serve on 127.0.0.1:4096 when started (its own web UI + API on one port, "
            "loopback only, NO authentication)",
            "It is started in data/opencode-workspace, which is the ONLY boundary on "
            "what it edits — the Hermes path-guard does not reach this lane",
            "data/opencode-workspace is git-initialised with one empty commit: that is "
            "the only thing that makes a directory a PROJECT to OpenCode rather than "
            "part of its shared 'global' one, and the tab then opens straight onto a "
            "new session there instead of its 'Add project' home screen. If you ever "
            "do land on that screen: Add project -> data/opencode-workspace, once",
            "Its Settings → Servers list is the TAB's own browser storage, not ours. "
            "Removing 127.0.0.1:4096 from it cannot strand you: the served page always "
            "re-adds the server it was loaded from, so ⌘R brings it back. To re-add it "
            "by hand, Add server wants only the address http://127.0.0.1:4096 — leave "
            "name, username and password empty (this server has no password)",
        ],
        "deepseek": [
            "OPTIONAL third coding lane — DeepSeek AI's own agent harness (`dsh`), "
            "license MIT. It is a TAB: `dsh web` serves its own UI and its own API on "
            "one loopback port (:3080), the same shape as OpenCode",
            "⚠ THIS IS THE SLOWEST OPTIONAL INSTALL AFTER THE TORCH STACKS. Not a "
            "binary and not a checkout: it is an npm dependency tree. MEASURED at this "
            "pin — 455 packages, 283MB, about 6-7 minutes. Watch the 'deepseek install' "
            "log in Logs; the install prints why before it starts",
            "⚠ PRE-1.0 DEVELOPER PREVIEW, and upstream says so itself: its SAFETY.md "
            "reads \"experimental developer-preview software … has not undergone a "
            "security audit\". Fifteen npm releases to date, every one an -rc or "
            "-alpha. Pinned hard at build.dsh_pin, and the pin is upstream's own "
            "`latest` dist-tag rather than the highest version number",
            "It needs NODE >= 22.19 (or >= 24) at RUN time. Your own node always wins "
            "and is never shadowed; if it is missing or too old, a pinned Node LTS is "
            "fetched into data/node (verified against nodejs.org's own SHASUMS256.txt, "
            "no sudo, nothing written outside data/)",
            "Everything it writes stays inside our tree: the npm prefix in "
            "data/deepseek/npm, its ENTIRE config+session home in data/deepseek/home "
            "(exported as $DSH_HOME at spawn). Walked from scratch — ~/.dsh, "
            "~/.cache/dsh and ~/.config/dsh are never created",
            "data/deepseek-workspace is the directory it is STARTED in, and therefore "
            "the boundary on what it edits by default — the same boundary the Aider and "
            "OpenCode lanes have. (The Hermes path-guard is a Hermes plugin hook and "
            "does NOT cover this lane.)",
            "Start seeds ONE provider named 'MOT Deck (local)' into its settings.yaml, "
            "pointing at MOT Deck runner, with your registry's models enumerated. It "
            "re-reads that file per request, so a model switch or a Rescan reaches it "
            "with no restart",
            "Telemetry: OFF. Verified at this pin rather than assumed — its composed "
            "plugin tree defaults the telemetry mode to DISABLED, and we additionally "
            "export upstream's own DSH_TELEMETRY_DISABLED=1 kill switch at spawn so a "
            "future default cannot switch it on. It has no auto-updater at all "
            "(grepped), so nothing moves under the pin on its own",
            "Loopback by POLICY, not just by default: its CLI refuses --host 0.0.0.0. "
            "No auth, by design — exactly like the OpenCode server and the Hermes "
            "dashboard",
            "⚠ FIRST RUN asks you for a WORKSPACE before it will accept a message. "
            "Click 'Add workspace' in its sidebar and pick data/deepseek-workspace "
            "(the installer creates it, with a README saying what it is). That opens "
            "macOS's own folder chooser, launched by dsh itself — if it does not come "
            "forward, click the MOT Deck icon in the Dock. There is nothing we can seed "
            "instead: a workspace record lives in a package-private store whose own "
            "docs say a hand-made mismatch \"fails loud\". Ledger U67",
            "It also shows an 'Internal Testing Notice' modal once, upstream's own. "
            "Click Continue",
        ],
    }
    if name not in plans:
        raise HTTPException(404, "unknown component")
    return {"component": name, "plan": plans[name],
            "note": "Nothing runs until you click Approve."}


@app.post("/api/components/{name}/install")
def install(name: str) -> JSONResponse:
    """Execute the install after the panel's approve step."""
    if name not in ("hermes", "odysseus", "searxng", "voicestudio", "voicebox",
                    "comfyui", "unsloth", "opencode", "deepseek"):
        raise HTTPException(404, "unknown component")
    # opencode is a BINARY download, not a clone+venv, so it has its own installer —
    # the same shape searxng's exception already has. deepseek is a third shape again
    # (an npm dependency tree into a private prefix), so it has its own too.
    script = {"searxng": "install_searxng.sh",
              "opencode": "install_opencode.sh",
              "deepseek": "install_deepseek.sh"}.get(name,
                                                             "install_component.sh")
    args = () if name in ("searxng", "opencode", "deepseek") else (name, "--yes")
    # voicestudio pulls ~5-8GB of wheels (torch/whisperx/mlx) + a bun SPA build, which
    # can outrun the default 30-minute budget on a slow link — give it 2h and surface a
    # timeout as a readable message instead of an unhandled 500. voicebox is the same
    # class (torch + kokoro + git-sourced engines, several GB) plus a bun build.
    # comfyui (torch + diffusion stack) and unsloth (its studio extra + a bun SPA build)
    # are the same class again.
    # deepseek joins them: MEASURED 6m0s for its npm resolve on a WARM cache, which is
    # inside the 30-minute default — but a cold npm cache on a slow link is exactly the
    # case where 455 packages outruns it, and a timeout here reads to the user as "the
    # install failed" rather than "we stopped waiting".
    timeout = 7200 if name in ("voicestudio", "voicebox", "comfyui", "unsloth",
                               "deepseek") else 1800
    try:
        r = _script(script, *args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"ok": False, "log": f"install timed out after {timeout // 60} min — "
                                 f"run it in a terminal: ./scripts/{script} "
                                 + " ".join(args)},
            status_code=500)
    ok = r.returncode == 0
    return JSONResponse(
        {"ok": ok, "log": (r.stdout + r.stderr)[-4000:]},
        status_code=200 if ok else 500)


# ── Lifecycle ownership (U77) ────────────────────────────────────────────────
# Routes and their provisioning write path live in component_lifecycle.py. Keep these
# lazy compatibility forwarders because bridge.app's facade remains public to tests and
# existing internal callers; they deliberately carry no route decorators.

async def start_plan(name: str) -> dict:
    from .component_lifecycle import start_plan as _owner
    return await _owner(name)


def _opencode_live_warning(c: dict, who: str = "OpenCode") -> str:
    from .component_lifecycle import _opencode_live_warning as _owner
    return _owner(c, who)


def start(name: str) -> JSONResponse:
    from .component_lifecycle import start as _owner
    return _owner(name)


def stop(name: str) -> JSONResponse:
    from .component_lifecycle import stop as _owner
    return _owner(name)


def restart(name: str) -> JSONResponse:
    from .component_lifecycle import restart as _owner
    return _owner(name)


def update(name: str) -> JSONResponse:
    from .component_lifecycle import update as _owner
    return _owner(name)


def _prov_set(n: str, state: str, detail: str) -> None:
    from .component_lifecycle import _prov_set as _owner
    _owner(n, state, detail)


def _provision(target: str) -> None:
    from .component_lifecycle import _provision as _owner
    _owner(target)
