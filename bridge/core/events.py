"""CORE — THE EVENT HUB. A push channel for the state the panel used to discover
only by asking, and `GET /api/events` (SSE) to read it.

Ratified in docs/research/2026-08-28-gemini-research-verdict.md §3 as an ADOPT-LATER,
with a rider that is the whole design of this file: our polling was a DELIBERATE
accepted ruling (2026-08-20), so this is a REVISIT, not a fix. Push is added for
LIVENESS; the poll is DEMOTED to a slow reconnect-backstop and is NEVER REMOVED.

⚠️ THE ONE RULE THIS FILE EXISTS TO ENFORCE: A DEAD PUSH STREAM DEGRADES TO
YESTERDAY'S BEHAVIOUR, NOT TO A FROZEN UI. Everything below is written so that the
worst thing a broken hub can do is stop talking. It holds no state anybody reads, it
answers no question, it is never awaited by a route that has work to do, and every
publish site is a fire-and-forget call inside a `try`. Delete this module and the
panel keeps working at its old cadence — that property is asserted, panel-side, by
bridge/tests/test_sse_hybrid.js (the cadence machine's SSE-dead branch IS the old
number), and bridge-side by test_events_hub.py's "publish with no subscribers and no
running loop is a no-op" case.

WHAT IT IS NOT:
  * not a state store. An event carries a KIND and, at most, a hint. It never
    carries the answer. The panel's reaction to every event is to run the poll
    handler it already had — so the payload cannot go stale, cannot disagree with
    /api/status, and cannot become a second source of truth. A dropped event is
    therefore survivable by construction: the next heartbeat poll fixes it.
  * not a queue with delivery guarantees. See BACKPRESSURE.
  * not a middleware. bridge/app.py:94-111 spells out why this codebase may not add
    a BaseHTTPMiddleware (it queue-and-pumps every response and would break the chat
    relays' streaming and their 20s heartbeat). This is one route and one asyncio
    primitive.

BACKPRESSURE — A SLOW CLIENT MUST NOT BLOCK THE BRIDGE.
Each subscriber gets its OWN bounded queue. `publish()` uses put_nowait and, on a
full queue, DROPS THE OLDEST event and increments that subscriber's `missed` counter;
the next frame it does receive carries `missed`, which the panel reads as "you are
behind, refetch everything" — which is exactly what it does with every event anyway.
So the slow path is: bounded memory, no await in the publisher, no head-of-line
blocking of any other subscriber, and a client that recovers by doing the one thing
it already knows how to do. The alternative — an unbounded queue — turns a wedged
WKWebView into a memory leak, and `await queue.put()` turns it into a stalled route.

THREADS. Two of the four state machines that matter run in daemon THREADS
(`_provision` in routers/components.py and `_do_switch` in routers/models.py both
spawn one), so `publish()` is safe to call from any thread: it captures the serving
loop the first time the SSE route runs and hands the work to
`loop.call_soon_threadsafe`. With no loop captured yet — a unit test, or a publish
during boot before any client ever connected — it returns 0 and does nothing.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .appctx import app

# ── tunables, all in one place ───────────────────────────────────────────────
QUEUE_MAX = 64          # events buffered per subscriber before the oldest is dropped
PING_S = 25.0           # server → client keepalive. Also the client's staleness clock:
                        # a WKWebView can hold a zombie socket that never fires
                        # onerror, so the panel treats "no frame for a while" as dead
                        # (bridge/panel/index.html, SSE_STALE_MS) — which only works
                        # if something arrives on a quiet stream.
RETRY_MS = 3000         # the SSE `retry:` hint — EventSource's own reconnect delay

# EVERY kind this hub may emit, and the panel handler each one is wired to. Written
# down HERE, next to the emitters, because the failure shape of a typo'd kind is
# silent: the panel ignores what it does not know and the poll quietly covers for it,
# so a misrouted event looks exactly like a working one that is 30s late.
#   component  → a component's lifecycle moved (start/stop/provision phase)
#   health     → the debounced health verdict changed for some component
#   model      → the runner's model changed (switch phase, eject, registry edit)
#   download   → a download was created, ticked, paused, resumed, cancelled or
#                finished  (progress is THROTTLED at the emitter, see DL_TICK_S)
#   config     → the Hermes config generation bumped
#   nav        → the nav layout was saved
#   memory     → the memory ledger moved enough to matter. DELTA-SUPPRESSED at the
#                emitter (core/memory.py): a component's footprint moving >2% AND
#                >32MB, or a change of pressure / swap-used / free-percentage — plus a
#                60s keepalive so a client can tell "nothing changed" from "the
#                sampler died". Sampled only while somebody is subscribed.
#   comfy      → the ComfyUI generate surface moved: a model download changed state,
#                or a generation job did. It carries `what` ("download" | "job") plus
#                an id and a state, and NEVER any numbers — /comfy's handler refetches
#                /api/comfy/state, so a frame can never disagree with the list. The
#                PANEL has no handler for this kind and needs none: an unknown type
#                falls through index.html's dispatch table harmlessly, and the only
#                subscriber that acts on it is /comfy itself.
#   hello      → sent once per connection, never emitted by a state transition
#   ping       → the keepalive above
KINDS = ("component", "health", "model", "download", "config", "nav", "memory",
         "comfy")


class Hub:
    """Fan-out to N SSE subscribers with per-subscriber bounded queues."""

    def __init__(self, queue_max: int = QUEUE_MAX) -> None:
        self._subs: dict[asyncio.Queue, dict] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue_max = queue_max
        self.published = 0
        self.dropped = 0

    # ── subscriber side ──────────────────────────────────────────────────────
    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Remember the serving loop so a worker thread can publish into it."""
        self._loop = loop or asyncio.get_running_loop()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        self._subs[q] = {"missed": 0, "since": time.time()}
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.pop(q, None)

    @property
    def subscribers(self) -> int:
        return len(self._subs)

    def missed(self, q: asyncio.Queue) -> int:
        return int((self._subs.get(q) or {}).get("missed") or 0)

    def clear_missed(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs[q]["missed"] = 0

    # ── publisher side ───────────────────────────────────────────────────────
    def _deliver(self, ev: dict) -> int:
        n = 0
        for q, meta in list(self._subs.items()):
            try:
                q.put_nowait(ev)
                n += 1
            except asyncio.QueueFull:
                # DROP THE OLDEST, KEEP THE NEWEST. An event is a nudge to refetch, so
                # the freshest nudge is the valuable one; and `missed` tells the client
                # it is behind, which makes the drop visible rather than silent.
                meta["missed"] = int(meta.get("missed") or 0) + 1
                self.dropped += 1
                try:
                    q.get_nowait()
                    q.put_nowait(ev)
                    n += 1
                except Exception:                                   # noqa: BLE001
                    pass
            except Exception:                                       # noqa: BLE001
                pass
        return n

    def publish(self, kind: str, **data: Any) -> int:
        """Fire-and-forget. Returns how many subscribers were reached (0 is fine).

        NEVER raises, from any thread, in any state. A publish site is a diagnostic
        line's worth of code inside a route that has real work to do; if this can
        throw, the hub becomes a way to break start/stop/switch/download, which is a
        far worse bug than a panel that refreshes 30s late.
        """
        try:
            ev = {"type": str(kind), "t": round(time.time(), 3)}
            for k, v in (data or {}).items():
                if v is not None:
                    ev[k] = v
            self.published += 1
            if not self._subs:
                return 0
            loop = self._loop
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not None and (loop is None or running is loop):
                return self._deliver(ev)
            if loop is None or loop.is_closed():
                return 0                     # nobody is serving: nothing to deliver
            loop.call_soon_threadsafe(self._deliver, ev)
            return len(self._subs)
        except Exception:                                           # noqa: BLE001
            return 0


HUB = Hub()


def publish(kind: str, **data: Any) -> int:
    """Module-level publish — what every emitter imports. See Hub.publish."""
    return HUB.publish(kind, **data)


def _frame(ev: dict, missed: int = 0) -> str:
    """One SSE frame: `data:` only, with the kind INSIDE the JSON.

    ⚠️ THERE IS NO `event:` LINE, AND THE FIRST DRAFT HAD ONE — CAUGHT BY DRIVING THE
    REAL PANEL, not by any test. `event: component` makes it a NAMED event, and
    `EventSource.onmessage` fires ONLY for unnamed events (`event:` absent, or exactly
    `message`). A named event needs addEventListener(kind, …) per kind. So the bridge
    happily streamed, the panel showed 4 subscribers on /api/events/stats, and the page
    received ZERO frames — it sat in `connecting` for ever while looking connected from
    both ends. The panel deliberately uses ONE onmessage dispatch table (seven
    listeners are seven things to forget when a kind is added), so the frame must be
    unnamed. bridge/tests/test_events_hub.py pins the absence explicitly."""
    body = dict(ev)
    if missed:
        body["missed"] = int(missed)
    return f"data: {json.dumps(body)}\n\n"


def _is_loopback(req: Request) -> bool:
    """The bridge binds 127.0.0.1 (scripts/start.sh), so this can only ever be true in
    practice. It is asserted anyway because this route is the one thing in MOT Deck
    that hands out a live feed of what the machine is doing, and 'the bind is the
    fence' is a fact about a sibling file that a future launch line could change
    without anyone rereading this one."""
    h = (getattr(req.client, "host", "") or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost", "") or h.startswith("127.")


@app.get("/api/events")
async def api_events(req: Request):
    """SSE: every state transition the panel used to poll for.

    Liveness only — see the module docstring. The panel's reaction to each frame is
    to run the poll handler it already had.
    """
    if not _is_loopback(req):
        return JSONResponse({"ok": False, "error": "loopback only"}, status_code=403)

    HUB.bind_loop()
    q = HUB.subscribe()

    async def gen():
        try:
            # `retry:` first, so a client that reconnects mid-handshake still gets the
            # backoff hint; then a hello, so the panel knows the stream is REALLY open
            # (EventSource's onopen fires on headers, which a proxy can produce for a
            # stream that then delivers nothing).
            yield f"retry: {RETRY_MS}\n\n"
            yield _frame({"type": "hello", "t": round(time.time(), 3),
                          "kinds": list(KINDS), "ping_s": PING_S})
            while True:
                if await req.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=PING_S)
                except asyncio.TimeoutError:
                    # A REAL FRAME, not a `: comment`. A comment keeps the socket warm
                    # but does not fire onmessage, so a client that uses silence as its
                    # staleness signal could not tell a healthy quiet stream from a
                    # zombie one.
                    yield _frame({"type": "ping", "t": round(time.time(), 3)})
                    continue
                missed = HUB.missed(q)
                HUB.clear_missed(q)
                yield _frame(ev, missed)
        finally:
            HUB.unsubscribe(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        # ⚠️ HEADERS THE CHAT RELAYS DO NOT SET, AND WHY THIS ONE DOES. Those are
        # POSTs consumed by hand off fetch(); this is a long-lived GET read by
        # EventSource through WKWebView's cache layer. `no-cache` + `no-store` stop a
        # cached replay of a finished stream, and `X-Accel-Buffering: no` is the
        # standing instruction to any reverse proxy that a future deployment puts in
        # front of the bridge not to buffer it into uselessness.
        headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                 "Connection": "keep-alive",
                 "X-Accel-Buffering": "no"})


@app.get("/api/events/stats")
def api_events_stats() -> JSONResponse:
    """What the hub has done since boot. Diagnostics for the degradation proof — the
    only way to answer 'is the panel on push or on the backstop right now' without
    reading the panel's console."""
    return JSONResponse({"ok": True, "subscribers": HUB.subscribers,
                         "published": HUB.published, "dropped": HUB.dropped,
                         "queue_max": QUEUE_MAX, "ping_s": PING_S,
                         "kinds": list(KINDS)})
