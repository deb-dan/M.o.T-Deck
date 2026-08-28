"""CORE — the component health verdict: one probe budget, one debounced answer."""
from __future__ import annotations



# ── COMPONENT HEALTH: one probe budget per component, ONE debounced verdict ───
# Debi 2026-08-21: the activity feed said `opencode degraded — health lost` while the
# opencode CARD still read Online. Those two surfaces are drawn from the SAME field
# on the SAME poll (panel/index.html:1854-1856), so they never disagreed at a single
# instant — the card is repainted from scratch every poll and shows NOW, while the
# feed is a permanent scrollback line about a PAST instant that nothing ever
# retracted. A one-poll blip therefore left a scary line sitting beside a green card.
#
# Two entirely healthy things produce exactly that one-poll blip:
#   1. A CLI RESTART. `ship.sh --restart opencode` runs the snapshot's
#      start_component.sh (ship.sh:230), whose opencode arm clears the listener and
#      only writes the NEW pid about a second later (start_component.sh:1016-1033).
#      Nothing on that path touches data/<name>.expected — only the panel's Start
#      writes it (_mark_expected, _provision) and only Stop clears it — so for that
#      window the component is "expected-up, no listener, and a pid file naming a
#      process that has just been killed", i.e. degraded by the letter of the rule.
#   2. PROBE CONGESTION. `asyncio.wait_for(open_connection, 0.5)` can fire because
#      our own event loop was busy, not because the port was gone. /api/status probes
#      every component SEQUENTIALLY on that loop, which it shares with the SSE chat
#      relays and LOffice's ~10MB static reads.
#
# So: let a component that needs it have its OWN probe budget, and require a miss to
# PERSIST before calling it lost — the shape the panel already uses for the bridge
# itself (index.html:1820, three consecutive misses before BRIDGE UNREACHABLE).
PROBE_TIMEOUT_DEFAULT = 0.5
# opencode is a ~144MB Bun executable that does real work on its first requests.
# The probe stays a TCP handshake and is DELIBERATELY NOT an HTTP GET to its own
# /global/health (start_component.sh:1040 uses that for the readiness poll, and
# global.ts:66 defines it): a handshake is completed by the KERNEL from the listen
# backlog and needs nothing from the server's event loop, whereas an HTTP probe does
# — which makes an HTTP probe strictly MORE likely to time out on a busy server,
# i.e. the exact false negative being fixed here. The wider budget is insurance
# against OUR loop, and costs nothing at all when the port answers (sub-millisecond).
PROBE_TIMEOUT_S = {"opencode": 2.0}
HEALTH_MISS_LOST = 3            # consecutive failed probes before "lost"
_HEALTH_MISS: dict = {}         # component -> consecutive failed probes


def _probe_timeout(name: str, expected: bool = True) -> float:
    """Probe budget for one component. Everything not named in PROBE_TIMEOUT_S keeps
    the historical 0.5s exactly — and so does a component we are NOT expecting to be
    up (Stop clears data/<name>.expected), because a component with no alarm to raise
    is not worth making every /api/status poll 1.5s slower for. The wide budget is
    only ever spent where it can PREVENT a false alarm."""
    if not expected:
        return PROBE_TIMEOUT_DEFAULT
    return PROBE_TIMEOUT_S.get(name, PROBE_TIMEOUT_DEFAULT)


def health_verdict(expected: bool, running: bool, misses: int,
                   lost_at: int = HEALTH_MISS_LOST) -> str:
    """PURE (unit-tested). ok | transient | lost.
         running, or never started by us   -> ok
         expected-up and missing, briefly  -> transient  (restart window / busy loop)
         expected-up and missing, N times  -> lost       (it really is gone)
    Total: a junk miss count degrades to 'transient', never to a false 'lost' — and
    the type check is STRICT rather than an int() coercion on purpose, so no value
    arriving as a string can ever escalate an alarm."""
    if running or not expected:
        return "ok"

    def _int(v, fallback, floor=None):
        ok = isinstance(v, int) and not isinstance(v, bool)
        return v if ok and (floor is None or v >= floor) else fallback
    m = _int(misses, 0)
    # A threshold below 1 is nonsense (it would mean "declare lost before a probe has
    # even missed"), so it falls back to the default rather than being clamped into
    # the most alarming possible behaviour.
    n = _int(lost_at, HEALTH_MISS_LOST, floor=1)
    return "lost" if m >= n else "transient"


def _health_track(name: str, expected: bool, running: bool) -> tuple:
    """Advance the consecutive-miss counter for `name`; return (verdict, misses).
    A recovery (or a clean Stop, which clears .expected) forgets the streak, so a
    component that blips twice an hour never accumulates its way to 'lost'."""
    if running or not expected:
        _HEALTH_MISS.pop(name, None)
        return ("ok", 0)
    m = _HEALTH_MISS.get(name, 0) + 1
    _HEALTH_MISS[name] = m
    return (health_verdict(expected, running, m), m)
