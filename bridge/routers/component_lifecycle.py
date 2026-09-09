"""ROUTER — component lifecycle: plan, start, stop, restart, update, and provision."""
from __future__ import annotations

import subprocess
import threading
import time

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..core.appctx import ROOT, app
from ..core.events import publish
from ..core.modelid import _live_model_id
from ..core import ownership as _ownership
from ..core.procs import PROV, _clear_expected, _closure, _kill_port_listener, _mark_expected, _port_alive_sync, _port_listener_pids, _read_ownership, _registry_models, _running, _running_sync, _script, cfg, reap_pidfile, stop_owned_component
from .models import live_tools_warning
from .sampling import _record_load_launch


_NOTES = {
    "runner": "launches the llama.cpp/MLX runner + loads the model (~60–90s)",
    # OPTIONAL, AGPL-3.0-only. Backend + built SPA on one loopback port, no auth.
    "voicestudio": "voice studio on :3900 — first boot loads speech models (can take minutes)",
    # OPTIONAL, MIT. JSON API + /mcp (+ the SPA when built) on one loopback port.
    # NO AUTH of any kind, and upstream has been stale since 2026-04-26.
    "voicebox": "voicebox on :17493 — no auth, loopback only; first boot loads models (minutes)",
    # OPTIONAL, GPL-3.0. UI + API on one loopback port, no auth. Torch import is slow.
    "comfyui": "comfyui on :8188 — loopback only, no auth; first boot imports torch (slow)",
    # OPTIONAL, AGPL-3.0-only (Studio). Its own bearer login lives in its own UI.
    "unsloth": "unsloth studio on :8899 — loopback only; it has its own login screen",
    # OPTIONAL, MIT. Its own UI + API on one loopback port, no auth. The tools warning
    # is appended per-request by start_plan (it depends on the LIVE model).
    "opencode": ("opencode on :4096 — loopback only, no auth. The tab opens its "
                 "new-session composer for data/opencode-workspace (the bridge's "
                 "/opencode redirect), not its own 'Add project' home screen. "
                 "Start seeds the `llama.cpp` provider -> MOT Deck runner, so its "
                 "model picker lists YOUR models (if it offers Big Pickle instead, the "
                 "config did not reach it — the log says so). "
                 "Needs a TOOL-CALLING model — look for the green 'tools' pill."),
    # OPTIONAL, MIT, pre-1.0. Its own SPA + API on one loopback port, no auth. The
    # tools warning is appended per-request by start_plan (it depends on the LIVE
    # model), the same way OpenCode's is.
    "deepseek": ("DeepSeek Harness on :3080 — loopback only (by its own policy), no "
                 "auth. Start seeds the 'MOT Deck (local)' provider -> MOT Deck "
                 "runner, and it re-reads that file per request, so a model switch "
                 "reaches it with no restart. FIRST RUN asks you to pick a WORKSPACE "
                 "before it will take a message: 'Add workspace' -> "
                 "data/deepseek-workspace. Needs a TOOL-CALLING model, like the other "
                 "agent lanes."),
}


@app.get("/api/components/{name}/start-plan")
async def start_plan(name: str) -> dict:
    """The dependency-ordered list that a Start of `name` will bring up."""
    from .components import _needs_title

    c = cfg()
    steps = []
    for n in _closure(name, c, []):
        note = _NOTES.get(n, "")
        # OpenCode and DeepSeek are the components whose usefulness depends on the
        # LOADED MODEL, so the plan says so before anything starts. A warning, never a
        # refusal (see opencode_tools_warning).
        # ⚠️ The wording of that warning names OpenCode by product; it is reused here
        # verbatim rather than duplicated per component because the FACT it reports —
        # "the loaded model cannot emit a tool call" — is one fact about the runner,
        # not a claim about either lane. A second copy is a second answer.
        if n in ("opencode", "deepseek"):
            warn = _opencode_live_warning(c, _needs_title(n))
            if warn:
                note = (note + " · " + warn) if note else warn
        steps.append({"name": n, "running": await _running(n, c), "note": note})
    return {"target": name, "steps": steps,
            "to_start": [s["name"] for s in steps if not s["running"]]}


def _opencode_live_warning(c: dict, who: str = "OpenCode") -> str:
    """The tools warning for whatever the runner is CURRENTLY serving. Never raises
    (a plan must render even with no registry and no runner).

    `who` names the product the sentence is FOR — see models.live_tools_warning. The
    default keeps this function's existing single-argument behaviour identical."""
    try:
        port = (c.get("runner", {}) or {}).get("port")
        live = _live_model_id(int(port)) if port else None
        entry = next((m for m in _registry_models() if m.get("id") == live), None) \
            if live else None
        return live_tools_warning(entry, who)
    except Exception:                                            # noqa: BLE001
        return ""


@app.post("/api/components/{name}/start")
def start(name: str) -> JSONResponse:
    """One-switch start: provision the whole dependency closure in a background thread,
    publishing live per-component state into PROV (read by /api/status). Returns at once."""
    threading.Thread(target=_provision, args=(name,), daemon=True).start()
    return JSONResponse({"ok": True, "log": "provisioning started"})




@app.post("/api/components/{name}/stop")
def stop(name: str) -> JSONResponse:
    _clear_expected(name)   # intentional stop → not "degraded", just "stopped"
    PROV.pop(name, None)    # drop any stale provisioning overlay for this component
    # SSE (2026-08-28): the stop transition, at its source. Emitted BEFORE the kill
    # rather than after — a stop that goes on to fail returns 409 and the panel's own
    # refresh (which this event triggers) reads the truth from /api/status either way,
    # whereas an emit placed after an early `return` path would be skipped.
    publish("component", name=name, state="stopping")
    # Runner must be stopped by PORT — a child router can survive a PID kill (spike learning).
    if name == "runner":
        rc = cfg().get("runner", {})
        port = rc.get("port")
        # ⛔ U64: a `pkill -f "jan serve.*port[= ]N"` sweep stood here, described as a
        # harmless legacy no-op. Jan was retired 2026-07-23, so it could no longer
        # match OUR process — only somebody else's, which is the one thing a kill by
        # pattern is actually good at. Deleted, not replaced: the ownership-checked
        # listener kill below is what has been stopping the runner all along.
        # The launch record—not the socket—is the authority. A runner can spend a
        # long time loading before it binds :6767; stopping only a listener would
        # strand that exact child and then clear the user's pin beneath it.
        refused = stop_owned_component("runner", int(port), force=True)
        if refused:
            return JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)
        # ⚠️ WAIT FOR THE PORT TO ACTUALLY RELEASE BEFORE SAYING THE STOP IS DONE.
        # THE BUG THIS CLOSES (found by walking the S32 API page's own Restart button,
        # 2026-08-29, reproduced on the live stack): restart() is stop()-then-start(),
        # and start()'s background thread asks `_running_sync` FIRST. `_running_sync`
        # for the runner is "is anything LISTENING on :6767". SIGKILL returns the
        # instant the signal is delivered, not when the kernel has torn the socket
        # down — so start() read the dying listener as "already running", set PROV to
        # `on / already running`, skipped the launch, and left the runner DOWN while
        # /api/status reported it up. That is the LIE-TO-USER class: :6767 dead, the
        # card green. Every component's Restart rides this route, so it was never only
        # the API page's button.
        #
        # THE FIX IS THIS FUNCTION'S OWN EXISTING PATTERN — the non-runner branch below
        # has waited for the listener to release since the hermes stale-pid incident
        # (~1.5s in 0.25s ticks). The runner branch was the one arm that skipped it.
        #
        # ⚠️ BUT IT WAITS ON `_port_alive_sync`, **NOT** ON `_port_listener_pids`, AND
        # THAT DIFFERENCE IS THE WHOLE BUG. Draft one of this fix used the lsof-based
        # `_port_listener_pids` the branch below uses, shipped, and the runner STILL
        # came back down — measured, with a 100ms port sampler running across a live
        # restart. Two liveness oracles disagree for a few milliseconds after a
        # SIGKILL: lsof stops listing the process as soon as it is reaped, while a TCP
        # connect to the port can still succeed while the kernel finishes tearing the
        # socket down. stop() was waiting on the first and start() was asking the
        # second, so stop() returned "released" into a window where `_running_sync`
        # still answered "alive". A wait is only a wait if it consults the ORACLE THE
        # NEXT STEP WILL USE; anything else is a race with extra steps. Hence
        # `_port_alive_sync` here, which is literally what `_running_sync(runner)`
        # calls.
        #
        # If the port is STILL answering after the budget we report it rather than
        # returning a serene ok: a stop that did not stop must not read as success,
        # and a second runner launched on top of a live one is the worse failure.
        for _ in range(12):
            if not _port_alive_sync(int(port)):
                return JSONResponse({"ok": True})
            time.sleep(0.25)
        return JSONResponse(
            {"ok": False,
             "log": f"port :{port} still answers 3s after the listener was killed — "
                    f"refusing to start a second runner on top of it"},
            status_code=409)
    # ── THE GENERIC STOP: PIDFILE-FIRST **AND IDENTITY-VERIFIED** ─────────────
    # ⛔ U64's sixth site, found by the sweep rather than by the ledger. This arm was
    # pidfile-FIRST, which is the right half, and it verified NOTHING: it read
    # data/<name>.pid and signalled that number, with an explicit
    #     except PermissionError:  alive = True   # exists but not ours — still kill
    # branch that signalled a process it had just established was somebody ELSE'S.
    # Pids are recycled (and this file has been observed stale — see the hermes note
    # below), so on a machine where sample runs standalone copies of the very components
    # we embed, a stale number was a stranger's death warrant with our name on it.
    # It now goes through core/procs.reap_pidfile: the exact child PID plus kernel-birth
    # launch record we wrote, no signal at all when that cannot be proven — the same
    # helper and the same sentences the shell's _reap_pidfile uses.
    notes = []
    pidf = ROOT / "data" / f"{name}.pid"
    _claim = _read_ownership(name)
    _was = str(_claim[0]) if _claim else ""
    _birth = _claim[1] if _claim else ""
    if pidf.exists() or _claim:
        # Keep the exact launch claim while SIGTERM drains. If the listener remains,
        # the port path can still reverify the same child; retiring the claim at signal
        # time would turn our own slow shutdown into an unowned-listener refusal.
        _refused = reap_pidfile(name, retire=False)
        notes += _refused or [f"stopped pid {_was} (identity verified as ours)"]
    # ALWAYS verify the port afterwards — a stale/absent pid file must never mask a
    # live process (observed: hermes.pid held 36254 while the real hermes was 41584 →
    # Stop was a silent no-op). If a LISTENER still holds the port, kill it by port.
    comp = cfg().get("components", {}).get(name, {})
    port = comp.get("port") or comp.get("mcp_port")
    if port:
        for _ in range(12):             # up to ~3s for process + listener to release
            still_owned = bool(_was) and _ownership.ownership_matches(ROOT, name, int(_was))
            if not _port_listener_pids(int(port)) and not still_owned:
                break
            time.sleep(0.25)
        listeners = _port_listener_pids(int(port))
        still_owned = bool(_was) and _ownership.ownership_matches(ROOT, name, int(_was))
        if listeners:
            refused = _kill_port_listener(int(port), component=name)
            if refused:
                return JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)
            # A second graceful signal was delivered under the still-live claim.
            for _ in range(12):
                if (not _port_listener_pids(int(port))
                        and not _ownership.ownership_matches(ROOT, name, int(_was))):
                    break
                time.sleep(0.25)
            listeners = _port_listener_pids(int(port))
            still_owned = _ownership.ownership_matches(ROOT, name, int(_was))
        if listeners or still_owned:
            return JSONResponse(
                {"ok": False,
                 "log": f"{name} is still shutting down after 6s; its exact launch "
                        "claim was retained and no replacement was started"},
                status_code=409)
        if _was:
            # Shutdown completed. Remove only the claim that still names this exact
            # child; a concurrently launched replacement is left intact.
            _ownership.retire_owned(ROOT, name, int(_was), _birth)
    elif _was:
        # A component without a listener still owns a real child. The first candidate
        # retained its claim forever because retirement happened only inside the port
        # branch. Wait on the same PID+birth identity and retire that generation only.
        for _ in range(24):
            if not _ownership.ownership_matches(ROOT, name, int(_was)):
                break
            time.sleep(0.25)
        if _ownership.ownership_matches(ROOT, name, int(_was)):
            return JSONResponse(
                {"ok": False,
                 "log": f"{name} is still shutting down after 6s; its exact launch "
                        "claim was retained"}, status_code=409)
        _ownership.retire_owned(ROOT, name, int(_was), _birth)
    if notes:
        return JSONResponse({"ok": True, "log": "; ".join(notes)})
    if port:
        return JSONResponse({"ok": True, "log": f"nothing running on :{port}"})
    return JSONResponse({"ok": False, "log": "no ownership claim and no port to stop"})


@app.post("/api/components/{name}/restart")
def restart(name: str) -> JSONResponse:
    """Stop, then start — the ONE action the dependency banner offers for "restart to
    rebind", because that is exactly what rebinds a component (every Start re-derives
    its wiring: the Hermes config patch, the Odysseus seed, the OpenCode provider
    rewrite — docs/research/2026-08-29-isolation-mode.md §6).

    ⚠️ IT IS A COMPOSITION, NOT NEW MACHINERY. It calls the stop() and start() route
    functions above verbatim — no second copy of the kill logic, no second copy of the
    provisioning thread — so a component can only ever be stopped the one audited way
    (pidfile identity first, port listener second, refusals honoured). If stop() refuses
    (409), NOTHING is started: a half-restart that leaves the old process holding the
    port is worse than the state we were asked to fix, and the caller is told why.

    Returns at once, like start(): the closure runs in start()'s background thread and
    the panel/shell watch it through /api/status's `prov` overlay exactly as they watch
    a Start pressed on the card."""
    from .components import _LANE_RESTART

    if name in _LANE_RESTART:
        # A LANE, NOT A COMPONENT (S28). Same composition rule as below: its own stop
        # route (pidfile identity, then port listener, refusals honoured) then its own
        # start route. Nothing new kills anything.
        import importlib
        mod, stop_fn, start_fn = _LANE_RESTART[name]
        if name == "gooseui":
            # …and REPAIR BEFORE RESPAWNING, so the button clears the sentence that
            # summoned it. goose's own seed_config deliberately never touches
            # `providers.<slug>.model`; only the dangling-choice repair does, and the
            # banner is only ever raised for a dangling value (see the invariant by
            # _ody_binding). A restart that leaves the complaint standing is the dead
            # button this slice is closing, not shipping.
            from .models import _rebind_goose
            from ..core.modelid import _live_model_id, wire_model_id
            try:
                _rc = cfg().get("runner", {}) or {}
                _live = _live_model_id(int(_rc["port"])) if _rc.get("port") else None
                _rebind_goose(wire_model_id(_live or "", _registry_models()) or "")
            except Exception as e:                                   # noqa: BLE001
                print(f"[deps] goose rebind before restart: {e}", flush=True)
        m = importlib.import_module(mod)
        r = getattr(m, stop_fn)()
        if getattr(r, "status_code", 200) != 200:
            return JSONResponse({"ok": False, "phase": "stop",
                                 "log": (r.body or b"").decode("utf-8", "replace")[:400]},
                                status_code=r.status_code)
        return getattr(m, start_fn)()
    if name != "runner" and name not in (cfg().get("components") or {}):
        raise HTTPException(404, "unknown component")
    r = stop(name)
    if r.status_code != 200:
        return JSONResponse(
            {"ok": False, "phase": "stop",
             "log": (r.body or b"").decode("utf-8", "replace")[:400]},
            status_code=r.status_code)
    start(name)
    return JSONResponse({"ok": True, "log": f"restarting {name}"})


@app.post("/api/components/{name}/update")
def update(name: str) -> JSONResponse:
    """M1: blue-green update with contract tests. Stub for now."""
    return JSONResponse(
        {"ok": False, "log": "updater lands in M1 — see docs/motdeck-architecture.md §6.1"},
        status_code=501)


# ⚠️ MOVED HERE from app.py:338-362 by the router/core split (2026-08-28).
#    _provision runs the start closure for POST /api/components/{name}/start and
#    is called from nowhere else; it reads _NOTES and _record_load_launch, both
#    of which are router-side, so keeping it in core would invert the dependency.

def _prov_set(n: str, state: str, detail: str) -> None:
    """THE single writer of the provisioning overlay — and therefore the single place
    the SSE hub is told a component moved (2026-08-28).

    This function exists so the emit is at the SOURCE OF TRUTH rather than sprinkled
    over six call sites: every phase the panel used to discover on its next /api/status
    tick (pending · starting · on · failed · blocked) now leaves here as a push. The
    event carries the name and the state as a HINT ONLY — the panel's handler is the
    poll handler it already had, so a lost or stale event costs nothing but latency.

    ⚠️ Runs in _provision's daemon THREAD. events.publish() is thread-safe by design
    (it hands off through the serving loop) and never raises."""
    PROV[n] = {"state": state, "detail": detail}
    publish("component", name=n, state=state)


def _provision(target: str) -> None:
    """Run the dependency closure in order, publishing live state into PROV.
    Runs in a background thread so /api/status can report progress meanwhile."""
    # These still belong to the status/dependency lane; keep the ownership seam acyclic.
    from .components import (LAST_START_FAIL, _FAIL_OK_STREAK, clear_start_failure,
                             runner_model_view, runner_serving, start_failure_reason)

    c = cfg()
    order = _closure(target, c, [])
    PROV.clear()
    for n in order:
        _prov_set(n, "pending", "queued")
    for i, n in enumerate(order):
        if _running_sync(n, c):
            # U60 — THE BRANCH THAT KEPT sample'S STALE SENTENCE ALIVE. This arm reports
            # a component UP, which is exactly the observation that retracts a recorded
            # failure; before this line it was the one success path in the file that
            # did not clear it, and `prov.runner = {"state": "on", "detail": "already
            # running"}` was the live fingerprint on the screenshot. status() retracts
            # it on the read too — this is the source-side half, so the dict is not
            # carrying a lie between polls.
            clear_start_failure(n)
            _prov_set(n, "on", "already running")
            _mark_expected(n)
            continue
        _prov_set(n, "starting", _NOTES.get(n, "starting…"))
        # ⚠️ A HANG IS A FAILURE TOO (U15). _script raises TimeoutExpired out of this
        # daemon thread; before this try/except that killed the thread with the card
        # frozen on "Starting…" forever — a third way to say nothing while being wrong.
        try:
            r = _script("start_component.sh", n)
            rc_code, output = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            rc_code, output = 124, (f"ERROR: start_component.sh {n} did not finish in "
                                    f"time and was given up on")
        except Exception as e:                                       # noqa: BLE001
            rc_code, output = 1, f"ERROR: could not run start_component.sh: {str(e)[:200]}"
        if rc_code != 0 and n == "runner":
            # THE EXIT CODE IS A REPORT; THE AUTHENTICATED PROBE IS THE FACT. The start
            # script's own readiness poll sends no Authorization header, so on llama.cpp
            # b10662+ (where /v1/models requires the key) it 401s for its whole ~3-minute
            # budget and reports failure for a runner that came up in one second. That
            # is the live incident of 2026-08-29; the script is another builder's WIP so
            # the fix there is ledgered (U16), and this is the bridge refusing to repeat
            # a claim it can check for itself.
            #
            # ⚠️ AND IT MUST BE SERVING THE MODEL WE ASKED FOR. "The runner is up" is
            # NOT the claim a Start makes; "the model you pinned is loaded" is. Caught
            # in the adversarial pass on the live machine, where the runner was happily
            # serving Parable-Qwen3-4B while the pin had been reverted to a 27B whose
            # file is deleted: a bare truthiness check would have reported that Start a
            # success and put the deleted model's name on a green card. That is the
            # incident's own lie, re-created by its fix.
            want = ((c.get("runner") or {}) if isinstance(c.get("runner"), dict)
                    else {}).get("model") or ""
            served = runner_serving(c)
            if served and want and served == want:
                print(f"[components] start_component.sh {n} exited {rc_code} but the "
                      f"runner is serving “{served}” — believing the probe, not the "
                      f"exit code (see U16)", flush=True)
                rc_code, output = 0, ""
            elif served:
                print(f"[components] start_component.sh {n} exited {rc_code}; the "
                      f"runner is serving “{served}” but the pin asks for “{want}” — "
                      f"this start really did fail", flush=True)
        if rc_code == 0:
            clear_start_failure(n)
            if n == "runner":
                _record_load_launch((c.get("runner", {}) or {}).get("model") or "")
            _prov_set(n, "on", "started")
            _mark_expected(n)   # expected-up now; if it later dies → degraded
        else:
            mv = runner_model_view(c) if n == "runner" else {}
            why = start_failure_reason(output, model=mv.get("pin", ""),
                                       path=mv.get("path", ""),
                                       file_state=mv.get("file", ""))
            LAST_START_FAIL[n] = {"at": time.time(), "rc": rc_code,
                                  "model": mv.get("pin", ""), "path": mv.get("path", ""),
                                  "stale": False, **why}
            # A FRESH failure gets the FULL debounce (U60). Without this reset a
            # component that was reading running+ok when the start failed (the runner
            # still serving the OLD model is exactly that state) would arrive with a
            # streak already part-way to retraction and lose its brand-new sentence on
            # the next poll. The counter measures "up since the failure", not "up".
            _FAIL_OK_STREAK.pop(n, None)
            # PROV's detail stays the RAW tail (View log has always shown it verbatim
            # and people diagnose from it); the sentence travels in last_error.
            _prov_set(n, "failed", output[-1500:])
            for m in order[i + 1:]:
                _prov_set(m, "blocked", f"blocked by {n} failure")
            return
