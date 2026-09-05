"""ROUTER — QUIT EVERYTHING: stop every running component, then the bridge itself.

WHY THIS EXISTS (U55, Debi's ruling 2026-09-02, verbatim: *"i think we should have an
option that fully quits everything too"*).

Since v1.5.69 quitting MOT Deck deliberately leaves the bridge and every component
running: ship.sh starts the bridge in its own session and every component is setsid'd,
so `applicationWillTerminate` has nothing of ours to terminate. That is what makes
"components stay up" across a ship TRUE, and it is the behaviour Debi wants to keep as
the default — reopening the app reuses the live stack and starts instantly.

THE RULING IS **BOTH DOORS**, not a replacement:
  · ⌘Q  "Quit MOT Deck"        — unchanged. The window closes; the stack keeps serving.
  · ⌥⌘Q "Quit Everything"      — this route, then the app.

WHAT THIS ROUTE WILL NOT DO
---------------------------
1. **It never invents a stop.** Every component is stopped through the EXACT function
   the panel's own per-component Stop button calls — `routers.components.stop`, which is
   pidfile-first and identity-verified, and whose port fallback is listener-scoped AND
   ownership-checked (`_kill_port_listener`). Nothing here matches a process by name, and
   nothing here clears a port it cannot prove is ours. (CLAUDE.md PROCESS-KILL RULE; the
   fence is bridge/contract_tests/test_no_name_kills_contract.py.)

2. **It never reports a stop it did not observe.** A component is `stopped` only if
   `_running_sync` — the same oracle /api/status renders green — says it is down
   AFTERWARDS. A stop route that returned ok:True and left a listener up is the
   LIE-TO-USER class, and it is exactly the bug the runner arm of `stop()` was carrying
   until 2026-08-29 (SIGKILL returns before the kernel tears the socket down).

3. **It never quits the bridge on a partial stop.** If anything is still up, the bridge
   STAYS UP, `ok` is false, `bridge_exiting` is false, and the failures are named — so
   the app can show them instead of vanishing and leaving orphans behind a closed door.
   A quit-everything that quietly leaves half a stack running is worse than one that
   refuses, because there is then no surface left to see it from.

THE BRIDGE'S OWN EXIT
---------------------
Scheduled, never immediate: the response has to reach the app first. A daemon thread
waits ~1.2s and then sends OUR OWN pid a SIGTERM, which is uvicorn's graceful shutdown —
the same signal ship.sh and stop.sh send, so there is one shutdown path, not two.

⚠️ AND IT CARRIES THE ZOMBIE FALLBACK, because this is the one route that creates the
exact condition the 2026-08-30 incident was made of. uvicorn's graceful shutdown waits
for in-flight responses, `/api/events` is an infinite text/event-stream, and the panel
is holding one at the moment the user picks Quit Everything. That is how three bridges
ended up alive with no listening socket. `--timeout-graceful-shutdown 10` (main.swift +
ship.sh) bounds it, but this route must not DEPEND on a flag on someone else's launch
line: if the process is still here 15s after the SIGTERM, it releases its pidfile and
calls os._exit(0). "Quit Everything" may not be the thing that leaves a zombie.

SCOPE, STATED SO IT IS NOT ASSUMED
----------------------------------
The targets are the nine things Mission Control shows as green — the eight harness.yaml
components plus the runner — in DEPENDENCY-REVERSE order (a consumer before what it
consumes: hermes and odysseus before the runner and searxng), computed from the manifest
rather than hardcoded. Two extras are included when, and only when, they are actually up:
the aux model server (`aux`, its own port) and the goose UI sidecar (`goose-ui`, whose
own stop is env-fenced with `is_ours`). Anything else on the machine — Debi's standalone
Hermes, her own Unsloth, goose Desktop — is not ours and is not touched.
"""
from __future__ import annotations

import os
import signal
import threading
import time
from typing import Callable, Iterable, Sequence

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.appctx import ROOT, app
from ..core.procs import _port_alive_sync, _running_sync, cfg
from ..core.singleton import release_claim
from .components import stop as _component_stop

# ── extras: not manifest components, but real processes of ours ───────────────
# Modelled as synthetic nodes that depend on the runner, so the ordering below puts them
# ahead of it for the same reason hermes goes ahead of it: stop the consumer first.
EXTRA_DEPS: dict[str, list[str]] = {
    "aux": ["runner"],
    "goose-ui": ["runner"],
}


# ── 1. THE ORDER (pure, fully unit-testable) ─────────────────────────────────
def stop_order(components: dict, extras: dict[str, list[str]] | None = None) -> list[str]:
    """Names in the order they must be STOPPED: every node before the nodes it
    depends_on.

    Why not a hardcoded list: harness.yaml owns the dependency graph (odysseus →
    runner + searxng, hermes → runner) and a second copy of it here would be a copy that
    can disagree. A new component with a new edge gets the right position for free.

    Ties break on MANIFEST ORDER, not on dict iteration luck, so the sequence is
    reproducible and a test can assert on it. `runner` is a synthetic node: it is a
    dependency target in the manifest but not a `components:` entry.
    """
    extras = dict(extras or {})
    deps: dict[str, list[str]] = {}
    rank: dict[str, int] = {}
    for i, (name, spec) in enumerate(components.items()):
        deps[name] = [d for d in (spec.get("depends_on") or []) if isinstance(d, str)]
        rank[name] = i
    for name, dl in extras.items():
        deps.setdefault(name, list(dl))
        rank.setdefault(name, len(rank))
    # every referenced dependency is a node, even if it has no manifest entry (runner)
    for dl in list(deps.values()):
        for d in dl:
            if d not in deps:
                deps[d] = []
                rank.setdefault(d, len(rank) + 1000)   # providers last among equals

    # Kahn over the edge "X must be stopped before Y" for each Y in depends_on(X).
    blockers = {n: 0 for n in deps}                    # how many nodes must precede n
    for n, dl in deps.items():
        for d in dl:
            if d in blockers:
                blockers[d] += 1
    ready = sorted([n for n, b in blockers.items() if b == 0], key=lambda n: rank[n])
    out: list[str] = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for d in deps.get(n, ()):
            if d in blockers:
                blockers[d] -= 1
                if blockers[d] == 0:
                    ready.append(d)
        ready.sort(key=lambda x: rank[x])
    # A CYCLE MUST NOT SILENTLY DROP NODES. depends_on is hand-written; if it ever
    # contains a loop, the nodes in it still have to be stopped. Append them in manifest
    # order rather than losing them — a stop we skipped is a process left running while
    # the response says everything is down.
    out += sorted([n for n in deps if n not in out], key=lambda n: rank[n])
    return out


# ── 2. THE DECISION TABLE (pure given its callbacks — this is what tests drive) ──
def quitall_run(order: Sequence[str],
                running_fn: Callable[[str], bool],
                stop_fn: Callable[[str], tuple[bool, str]],
                verify_fn: Callable[[str], bool]) -> dict:
    """Walk `order`, stopping what is up, and assemble the honest answer.

    `stop_fn(name)` -> (the stop call claimed success, its own sentence)
    `verify_fn(name)` -> True if the component is STILL RUNNING after the stop

    The claim and the verification are separate on purpose: `stop()` can legitimately
    answer ok:True while a listener is still tearing down, and it is the verification —
    not the claim — that decides whether this route says "stopped".
    """
    stopped: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    sentences: list[str] = []
    for name in order:
        if not running_fn(name):
            skipped.append(name)
            sentences.append(f"{name} — was not running")
            continue
        claimed, why = stop_fn(name)
        still = verify_fn(name)
        if still:
            failed.append(name)
            sentences.append(
                f"{name} — STILL RUNNING after the stop"
                + (f" ({why})" if why else "")
                + (" — the stop reported success, which was wrong" if claimed else ""))
        elif claimed:
            stopped.append(name)
            sentences.append(f"{name} — stopped" + (f" ({why})" if why else ""))
        else:
            # The stop refused but the thing is down anyway. Honest, and common: "no pid
            # file and no port to kill by" on a component that had already exited.
            stopped.append(name)
            sentences.append(
                f"{name} — down, though the stop did not claim it"
                + (f" ({why})" if why else ""))
    ok = not failed
    return {
        "ok": ok,
        "stopped": stopped,
        "failed": failed,
        "skipped": skipped,
        "sentences": sentences,
        "bridge_exiting": ok,
        "bridge": (
            "exiting: SIGTERM to this bridge in ~1.2s (uvicorn graceful shutdown, "
            "hard exit at 15s if a stream wedges it)"
            if ok else
            "LEFT RUNNING on purpose — " + ", ".join(failed)
            + (" is" if len(failed) == 1 else " are") + " still up, so there is still a "
            "panel to see it from"),
    }


# ── 3. THE LIVE WIRING ───────────────────────────────────────────────────────
def _gooseui():
    """The goose-UI lane, or None. Imported lazily: it owns an optional satellite
    (`_ui`) and a route that answers 503 when that satellite is missing, so a bridge
    without it must still be able to quit everything else."""
    try:
        from . import gooseui as g                          # noqa: PLC0415
        return g
    except Exception:                                       # noqa: BLE001
        return None


def _is_running(name: str, c: dict) -> bool:
    if name == "aux":
        p = (c.get("aux") or {}).get("port")
        return _port_alive_sync(int(p)) if p else False
    if name == "goose-ui":
        g = _gooseui()
        try:
            return bool(g and g._alive())
        except Exception:                                   # noqa: BLE001
            return False
    return _running_sync(name, c)


def _body(resp) -> dict:
    """The dict inside a JSONResponse, without re-parsing JSON when we do not have to."""
    try:
        import json                                         # noqa: PLC0415
        return json.loads(resp.body.decode("utf-8"))
    except Exception:                                       # noqa: BLE001
        return {}


def _stop(name: str) -> tuple[bool, str]:
    """Stop ONE target through its own existing, identity-verified stop path.

    ⚠️ NO NEW KILL CODE LIVES HERE, AND THAT IS THE POINT. Every branch delegates to the
    function the panel's own button calls. A second implementation of "stop hermes" is a
    second thing that can drift out of the PROCESS-KILL RULE.
    """
    try:
        if name == "aux":
            from .models import aux_stop                     # noqa: PLC0415
            r = aux_stop()
            b = _body(r)
            return bool(b.get("ok", r.status_code < 400)), str(b.get("log") or "aux model server")
        if name == "goose-ui":
            g = _gooseui()
            if g is None:
                return False, "the goose-UI lane is not loaded in this bridge"
            r = g.gooseui_stop()
            b = _body(r)
            return bool(b.get("ok")), f"goose-ui: {b.get('stopped') or b.get('error') or '?'}"
        r = _component_stop(name)
        b = _body(r)
        return bool(b.get("ok")) and r.status_code < 400, str(b.get("log") or "")
    except Exception as e:                                  # noqa: BLE001
        return False, f"the stop call raised {type(e).__name__}: {e}"


def _still_running(name: str, c: dict) -> bool:
    """Is it STILL up? Give a just-signalled listener the same ~1.5s grace `stop()`
    gives itself — asking once, immediately, would fail a stop that is merely finishing.
    """
    for _ in range(6):
        if not _is_running(name, c):
            return False
        time.sleep(0.25)
    return _is_running(name, c)


def schedule_bridge_exit(delay: float = 1.2, grace: float = 15.0) -> None:
    """SIGTERM ourselves after `delay`, and hard-exit if graceful shutdown wedges.

    delay: the response must be on the wire before the listener closes.
    grace: see the module docstring — an open /api/events stream is exactly what made
    the 2026-08-30 zombies, and this route is the one most likely to be invoked while
    the panel holds one.
    """
    def _go() -> None:
        time.sleep(delay)
        me = os.getpid()
        try:
            os.kill(me, signal.SIGTERM)
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(grace)
        # Still alive → uvicorn is waiting on something that will not finish.
        release_claim(ROOT, me)
        os._exit(0)

    threading.Thread(target=_go, daemon=True, name="quitall-bridge-exit").start()


def _order(c: dict) -> list[str]:
    return stop_order(c.get("components") or {}, EXTRA_DEPS)


# ⚠️ ONE SWEEP AT A TIME (adversarial pass, 2026-09-02). Two overlapping sweeps is not a
# theoretical race: ⌥⌘Q twice in a second, an impatient retry against a slow stop, or the
# app plus a curl. They would interleave over the SAME pidfiles — the second sweep reads
# a pidfile the first has already unlinked, sees "not running", and reports a component
# as stopped that the first sweep is still killing. Both then answer ok. A non-blocking
# lock turns that into an honest 409 instead.
_SWEEP = threading.Lock()


@app.get("/api/quitall/plan")
def quitall_plan() -> JSONResponse:
    """What Quit Everything WOULD stop, right now, and in what order. Changes nothing.

    It exists so the confirmation the user sees can name real processes instead of a
    generic warning, and so the ordering can be verified on a live stack without
    stopping the live stack.
    """
    c = cfg()
    order = _order(c)
    return JSONResponse({
        "ok": True,
        "order": order,
        "running": [n for n in order if _is_running(n, c)],
        "not_running": [n for n in order if not _is_running(n, c)],
        "note": "POST /api/quitall performs this, then exits the bridge if everything stopped",
    })


@app.post("/api/quitall")
async def quitall(request: Request) -> JSONResponse:
    """Stop every running component, then schedule this bridge's own clean exit.

    Body (all optional): {"dry_run": true} — plan only, nothing is stopped;
                         {"keep_bridge": true} — stop the components, leave the bridge up
                         (the honest answer for "stop my stack" without closing the app).

    Status codes are distinct because the app branches on them: 200 = everything asked
    for is down; 409 = something is STILL RUNNING and the bridge deliberately stayed up.
    """
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
    except Exception:                                       # noqa: BLE001
        payload = {}                                        # no body at all is normal

    c = cfg()
    order = _order(c)

    if payload.get("dry_run"):
        return JSONResponse({
            "ok": True, "dry_run": True, "order": order,
            "running": [n for n in order if _is_running(n, c)],
            "bridge_exiting": False,
            "bridge": "untouched (dry_run)",
        })

    if not _SWEEP.acquire(blocking=False):
        return JSONResponse({
            "ok": False, "stopped": [], "failed": [], "skipped": [],
            "sentences": ["a Quit Everything sweep is already running — this one did "
                          "nothing rather than racing it over the same pidfiles"],
            "bridge_exiting": False,
            "bridge": "left to the sweep already in progress",
        }, status_code=409)
    try:
        return _sweep(order, c, payload)
    finally:
        _SWEEP.release()


def _sweep(order: Sequence[str], c: dict, payload: dict) -> JSONResponse:
    result = quitall_run(
        order,
        running_fn=lambda n: _is_running(n, c),
        stop_fn=_stop,
        verify_fn=lambda n: _still_running(n, c),
    )
    result["order"] = list(order)

    # ⚠️ THE SENTENCES GO TO THE LOG, NOT ONLY TO THE RESPONSE — and this is the one
    # route where that is not belt-and-braces. The client that asked is the app, and the
    # app QUITS the moment it reads this; the bridge then exits too. Two seconds later
    # the only account of what was stopped, what refused, and why has left the building
    # with both processes. If Debi opens the stack tomorrow and something is off, this is
    # the only place the answer can still be. (Ordinary routes can rely on the panel
    # still being there to show their errors. This one cannot, by construction.)
    print(f"[quitall] {'ok' if result['ok'] else 'REFUSED'}: "
          f"{len(result['stopped'])} stopped, {len(result['failed'])} still up, "
          f"{len(result['skipped'])} were not running", flush=True)
    for _s in result["sentences"]:
        print(f"[quitall]   {_s}", flush=True)
    print(f"[quitall] bridge: {result['bridge']}", flush=True)

    if payload.get("keep_bridge"):
        result["bridge_exiting"] = False
        result["bridge"] = ("left running (keep_bridge) — components only"
                           if result["ok"] else result["bridge"])
        return JSONResponse(result, status_code=200 if result["ok"] else 409)

    if result["bridge_exiting"]:
        schedule_bridge_exit()
        return JSONResponse(result)
    return JSONResponse(result, status_code=409)
