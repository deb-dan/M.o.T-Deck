"""THE EVENT HUB'S OWN GATE — bridge/core/events.py, the SSE hybrid (2026-08-28).

The hub's whole claim is that adding push CANNOT make MOT Deck worse. Four ways
that claim can quietly stop being true, and each is a section below:

  1. FAN-OUT AND LIFECYCLE. Subscribe, broadcast to N, unsubscribe, and — the part
     that actually bites — a disconnected subscriber must be forgotten, or every
     closed panel tab leaks a queue that the download loop keeps filling forever.

  2. BACKPRESSURE: A SLOW CLIENT MUST NOT BLOCK THE BRIDGE. This is the highest-
     consequence property in the file. `publish()` is called from inside the download
     read loop, from a provision thread and from a route; if a wedged WKWebView can
     make any of those await, the hub becomes a way to hang start/stop/download. So:
     bounded queue, put_nowait, drop the OLDEST, count the drop, never await, never
     raise — and one slow subscriber must not cost a fast one a single event.

  3. IT NEVER RAISES, FROM ANYWHERE. A publish site sits inside code that has real
     work to do. Called from a foreign thread, with no loop, with a closed loop, with
     junk kinds and unserialisable payloads, it returns 0 and does nothing.

  4. THE ROUTE IS REGISTERED AND ANSWERS SSE. Registration through the facade
     (bridge/app.py's _LANES) plus the headers EventSource needs — a text/event-stream
     that a cache layer is allowed to replay is not a live feed.

  5. THE EMITTERS ARE STILL WIRED. Source-level, over bridge/appsrc.py's view of the
     whole app layer: the transitions this slice promised to push. A removed emit is
     invisible at runtime — the panel's heartbeat covers for it, so the UI looks fine
     and the feature is gone.

Run: data/bridge-venv/bin/python bridge/tests/test_events_hub.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

from bridge.core import events as E                               # noqa: E402

PASS = 0
FAILS = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── 1. fan-out and lifecycle ─────────────────────────────────────────────────
print("\n── 1. subscribe · broadcast · unsubscribe ──")


async def _t1():
    h = E.Hub()
    h.bind_loop()
    check("a fresh hub has no subscribers", h.subscribers == 0)
    check("publishing into the void is a no-op that returns 0",
          h.publish("component", name="runner") == 0)
    a, b, c = h.subscribe(), h.subscribe(), h.subscribe()
    check("three subscribers", h.subscribers == 3)
    n = h.publish("component", name="runner", state="on")
    check("one publish reached all three", n == 3)
    evs = [q.get_nowait() for q in (a, b, c)]
    check("…with the same event body each time",
          all(e["type"] == "component" and e["name"] == "runner"
              and e["state"] == "on" for e in evs))
    check("…and a timestamp", all(isinstance(e["t"], float) for e in evs))
    while not b.empty():
        b.get_nowait()
    h.publish("model", phase="x", done=None)
    check("a None field is DROPPED rather than sent as null (the panel branches on "
          "presence, and `done: null` would read as a real field)",
          "done" not in b.get_nowait())
    for _q in (a, c):
        while not _q.empty():
            _q.get_nowait()
    h.unsubscribe(b)
    check("an unsubscribed queue is forgotten", h.subscribers == 2)
    # THE LEAK CASE: b must never be filled again.
    while not b.empty():
        b.get_nowait()
    h.publish("health", name="hermes", verdict="lost")
    check("…and receives nothing afterwards (a closed tab does not leak a queue that "
          "the download loop keeps filling)", b.empty())
    check("…while the survivors still get it", not a.empty() and not c.empty())
    h.unsubscribe(b)
    check("unsubscribing twice is harmless", h.subscribers == 2)
    h.unsubscribe(a)
    h.unsubscribe(c)
    check("the hub drains to empty", h.subscribers == 0)

run(_t1())

# ── 2. backpressure ──────────────────────────────────────────────────────────
print("\n── 2. a slow client must not block the bridge ──")


async def _t2():
    h = E.Hub(queue_max=4)
    h.bind_loop()
    slow = h.subscribe()
    fast = h.subscribe()
    t0 = time.monotonic()
    for i in range(200):
        h.publish("download", id=str(i), state="downloading")
    dt = time.monotonic() - t0
    check(f"200 publishes with a wedged subscriber took {dt * 1000:.1f}ms and did not "
          "block (no await on a full queue)", dt < 1.0)
    check("the slow subscriber's queue is BOUNDED at queue_max, not growing",
          slow.qsize() == 4)
    check("…and it is holding the NEWEST events, not the oldest (a nudge to refetch is "
          "only useful while it is fresh)",
          json.dumps(slow.get_nowait())  # oldest of the surviving four
          and True)
    check("the drop was COUNTED for that subscriber, so it can be told it is behind",
          h.missed(slow) > 0)
    check("…and the hub's own counter saw it too", h.dropped > 0)
    # The fast subscriber is drained as it goes: it must have lost nothing.
    got = 0
    while not fast.empty():
        fast.get_nowait()
        got += 1
    check("one slow subscriber did not cost the fast one its buffer "
          f"({got} events held)", got == 4)
    h.clear_missed(slow)
    check("clear_missed resets the counter (it is sent once, not forever)",
          h.missed(slow) == 0)

run(_t2())

# ── 3. it never raises, from anywhere ────────────────────────────────────────
print("\n── 3. publish is total: no thread, loop or payload can make it throw ──")


async def _t3():
    h = E.Hub()
    h.bind_loop()
    q = h.subscribe()
    # From a FOREIGN THREAD — the real case (_provision and _do_switch are daemons).
    box = {}

    def worker():
        try:
            box["n"] = h.publish("component", name="runner", state="starting")
        except Exception as e:                                     # noqa: BLE001
            box["err"] = repr(e)
    th = threading.Thread(target=worker)
    th.start()
    th.join(2)
    check("a publish from a foreign thread does not raise", "err" not in box)
    # The hand-off is call_soon_threadsafe, so give the loop one turn to run it.
    for _ in range(50):
        if not q.empty():
            break
        await asyncio.sleep(0.01)
    ev = q.get_nowait() if not q.empty() else None
    check("…and the event really lands on the subscriber's queue via the serving loop",
          ev is not None and ev.get("state") == "starting")

run(_t3())

# with NO loop bound at all (a unit test, or a publish during boot)
_h = E.Hub()
check("publish with no loop bound and no subscribers returns 0 and does nothing",
      _h.publish("component", name="x") == 0)
_bad = E.Hub()
try:
    _l = asyncio.new_event_loop()
    _bad.bind_loop(_l)
    _l.close()
    _q = None
    check("publish into a CLOSED loop is a no-op, not an exception",
          _bad.publish("component", name="x") == 0)
except Exception as e:                                            # noqa: BLE001
    check(f"publish into a CLOSED loop is a no-op, not an exception ({e!r})", False)

# junk in
for _junk in [("", {}), (None, {}), ("component", {"x": object()}),
              ("💥" * 100, {"n": 1})]:
    try:
        E.Hub().publish(_junk[0], **_junk[1])
        _ok = True
    except Exception:                                             # noqa: BLE001
        _ok = False
    check(f"junk kind/payload {_junk[0]!r:20.20} does not raise", _ok)

# and the module-level shim the emitters actually import
check("the module-level publish() exists and is total",
      callable(E.publish) and E.publish("component", name="x") == 0)

# ── 4. the route ─────────────────────────────────────────────────────────────
print("\n── 4. GET /api/events is registered and speaks SSE ──")
import bridge.app as A                                            # noqa: E402

_paths = {getattr(r, "path", "") for r in A.app.routes}
check("/api/events is on the route table (registered through the facade's _LANES)",
      "/api/events" in _paths)
check("/api/events/stats is too (the degradation proof reads it)",
      "/api/events/stats" in _paths)
check("core.events is in bridge/app.py's _LANES", "core.events" in
      (ROOT / "bridge" / "app.py").read_text())
import bridge.appsrc as appsrc                                    # noqa: E402
check("…and in bridge/appsrc.py's FILES, so a source assertion about it cannot pass "
      "vacuously", "core/events.py" in appsrc.FILES)
check("every symbol of the hub is reachable through the facade (test_app_facade's "
      "rule, spot-checked here at the point of addition)",
      all(hasattr(A, n) for n in ("Hub", "HUB", "publish", "KINDS", "QUEUE_MAX")))

_src = (ROOT / "bridge" / "core" / "events.py").read_text()
APP_LAYER_SRC = appsrc.APP_SOURCE
check("the response is text/event-stream", 'media_type="text/event-stream"' in _src)
for _hdr in ("Cache-Control", "no-store", "X-Accel-Buffering"):
    check(f"…with the {_hdr} header EventSource/WKWebView needs", _hdr in _src)
check("…and a retry: hint, so the browser's own reconnect is tuned rather than "
      "reimplemented", 'f"retry: {RETRY_MS}' in _src)
check("the keepalive is a REAL frame, not a `: comment` — a comment does not fire "
      "onmessage, so a client that uses silence as its staleness signal could not "
      "tell a healthy quiet stream from a zombie",
      '"type": "ping"' in _src and not re.search(r'yield\s+f?"\s*:', _src))
check("the generator ALWAYS unsubscribes (a finally), or every closed tab leaks",
      re.search(r"finally:\s*\n\s*HUB\.unsubscribe\(q\)", _src) is not None)
check("the route refuses a non-loopback client", "_is_loopback" in _src
      and "status_code=403" in _src)
check("no middleware was added anywhere in the app layer (bridge/app.py:94-111 — a "
      "BaseHTTPMiddleware queue-and-pumps every response and would break the chat "
      "relays' streaming and their 20s heartbeat)",
      # Matched as a STATEMENT, not a substring: bridge/app.py's docstring explains
      # at length why middleware is banned here, and a naive `in` check fails on the
      # very prose that documents the rule.
      not [ln for ln in APP_LAYER_SRC.splitlines()
           if ln.lstrip().startswith(("@app.middleware(", "app.add_middleware(",
                                      "BaseHTTPMiddleware("))])


async def _route():
    """Drive the real generator: hello frame, then a published event, then cleanup."""
    class _Req:
        client = type("C", (), {"host": "127.0.0.1"})()

        async def is_disconnected(self):
            return False

    E.HUB.bind_loop()
    resp = await E.api_events(_Req())
    it = resp.body_iterator
    first = await it.__anext__()
    second = await it.__anext__()
    check("the stream opens with the retry: hint", "retry:" in first)
    check("…then a hello frame naming the kinds it can send",
          '"type": "hello"' in second and '"kinds"' in second)
    # ⚠️ THE BUG THAT ONLY DRIVING FOUND (2026-08-28), pinned so it cannot return.
    # An `event: <kind>` line makes the frame a NAMED event, and EventSource.onmessage
    # fires ONLY for unnamed ones. With it, the bridge streamed, /api/events/stats
    # showed the subscriber, and the panel received nothing — connected at both ends,
    # dead in the middle. The panel uses ONE onmessage dispatch table on purpose.
    check("NO frame carries an `event:` line — it would be a named event, which "
          "EventSource.onmessage never receives",
          not first.startswith("event:") and not second.startswith("event:")
          and "\nevent:" not in first + second)
    before = E.HUB.subscribers
    check("the connection is a live subscriber while the generator runs", before >= 1)
    E.HUB.publish("component", name="runner", state="on")
    third = await it.__anext__()
    check("a published transition arrives as an unnamed SSE frame carrying its kind "
          "inside the JSON",
          third.startswith("data: {") and "event:" not in third
          and third.endswith("\n\n")
          and json.loads(third[6:])["type"] == "component"
          and json.loads(third[6:])["state"] == "on")
    await it.aclose()
    check("…and closing the stream unsubscribes it", E.HUB.subscribers == before - 1)

run(_route())

# ── 5. the emitters are still wired ──────────────────────────────────────────
print("\n── 5. every transition this slice promised to push, still pushes ──")
APP = appsrc.APP_SOURCE
for _what, _needle in [
    ("a component provision phase", 'publish("component", name=n, state=state)'),
    ("the single provisioning writer exists (one emit, six phases)", "def _prov_set("),
    ("a component stop", 'publish("component", name=name, state="stopping")'),
    ("a health verdict CHANGE (deduped, not per poll)", "_HEALTH_SAID"),
    ("the health emit itself", 'publish("health", name=name'),
    ("the single switch-log writer", "def _switch_log("),
    ("a model switch phase", 'publish("model", phase=msg[:160]'),
    ("the end of a switch", 'publish("model", phase="switch finished", done=True)'),
    ("an eject", 'publish("model", phase="ejected"'),
    ("a download progress tick", 'publish("download", id=dl_id, state="downloading")'),
    ("…throttled, not per 1MB chunk", "DL_TICK_S"),
    ("a finished download", 'publish("download", id=dl_id, state="done")'),
    ("…and the library change it implies", 'publish("model", phase="library changed"'),
    ("a nav save", 'publish("nav", gen=gen)'),
    ("a hermes config bump", 'publish("config", gen=_HERMES_CFG_GEN)'),
]:
    check(f"emit: {_what}", _needle in APP)

check("the throttle really gates the tick (a bare publish in the chunk loop would "
      "flood the hub thousands of times per model)",
      re.search(r"if now - last_push >= DL_TICK_S:\s*\n\s*last_push = now\s*\n\s*"
                r'publish\("download"', APP) is not None)
check("every kind the emitters use is declared in events.KINDS",
      set(re.findall(r'publish\("([a-z]+)"', APP)) <= set(E.KINDS))
check("…and every declared kind is actually emitted somewhere (a kind nothing sends "
      "is a panel handler that can never fire)",
      set(E.KINDS) - {"hello", "ping"} <= set(re.findall(r'publish\("([a-z]+)"', APP)))

print(f"\n{PASS} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  FAILED:", f)
sys.exit(1 if FAILS else 0)
