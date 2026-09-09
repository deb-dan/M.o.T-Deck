"""QUIT EVERYTHING — the lane, driven through the real ASGI app (U55).

The contract gate (bridge/contract_tests/test_quitall_contract.py) pins the decision
table and the fences. THIS file drives the actual routes, because the two things a
source assertion cannot check are (a) that the routes are really mounted on the app the
bridge serves, and (b) that the read-only doors are genuinely read-only.

⚠️ NOTHING HERE STOPS A REAL PROCESS. Every test either hits a read-only route or
monkeypatches `_stop` / `_is_running` / `schedule_bridge_exit`, because a suite that can
take the developer's own stack down is a suite nobody runs twice. The one full sweep of
the live stack was WALKED by hand on the real machine (see the slice report), which is
the only place that test can honestly live.
"""
import json

import pytest
from fastapi.testclient import TestClient

from bridge import app as A
from bridge.routers import quitall as Q

client = TestClient(A.app)


# ── the read-only door ───────────────────────────────────────────────────────
def test_plan_is_mounted_and_changes_nothing(monkeypatch):
    seen = []
    monkeypatch.setattr(Q, "_stop", lambda n: seen.append(n) or (True, ""))
    r = client.get("/api/quitall/plan")
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True
    assert b["order"][-1] == "runner", "the plan must show the real stop order"
    assert set(b["running"]) | set(b["not_running"]) == set(b["order"])
    assert not seen, "the plan route stopped something — it is a preview, not an action"


def test_dry_run_stops_nothing_and_says_so(monkeypatch):
    seen = []
    monkeypatch.setattr(Q, "_stop", lambda n: seen.append(n) or (True, ""))
    monkeypatch.setattr(Q, "schedule_bridge_exit",
                        lambda *a, **k: pytest.fail("dry_run scheduled a bridge exit"))
    r = client.post("/api/quitall", json={"dry_run": True})
    assert r.status_code == 200
    b = r.json()
    assert b["dry_run"] is True and b["bridge_exiting"] is False
    assert not seen


# ── the acting door, with the actual stopping stubbed out ────────────────────
def _fake(monkeypatch, running, still, exits):
    monkeypatch.setattr(Q, "_is_running", lambda n, c: n in running)
    monkeypatch.setattr(Q, "_stop", lambda n: (True, "stub"))
    monkeypatch.setattr(Q, "_still_running", lambda n, c: n in still)
    monkeypatch.setattr(Q, "schedule_bridge_exit", lambda *a, **k: exits.append(True))


def test_a_clean_sweep_returns_200_and_schedules_the_bridge_exit(monkeypatch):
    exits = []
    _fake(monkeypatch, running={"hermes", "runner"}, still=set(), exits=exits)
    r = client.post("/api/quitall", json={})
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["bridge_exiting"] is True
    assert b["stopped"] == ["hermes", "runner"]
    assert exits == [True], "a verified-clean sweep must schedule the bridge's own exit"


def test_a_survivor_returns_409_and_the_bridge_stays_up(monkeypatch):
    """The status code is not decoration: app/main.swift branches on it, and this is the
    path where the app must NOT close."""
    exits = []
    _fake(monkeypatch, running={"hermes", "runner"}, still={"runner"}, exits=exits)
    r = client.post("/api/quitall", json={})
    assert r.status_code == 409
    b = r.json()
    assert b["ok"] is False and b["bridge_exiting"] is False
    assert b["failed"] == ["runner"]
    assert exits == [], "the bridge must not exit while something is still running"


def test_keep_bridge_stops_the_components_and_leaves_the_bridge(monkeypatch):
    exits = []
    _fake(monkeypatch, running={"hermes"}, still=set(), exits=exits)
    r = client.post("/api/quitall", json={"keep_bridge": True})
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] is True and b["bridge_exiting"] is False
    assert exits == []


def test_a_missing_or_junk_body_is_a_normal_full_quit(monkeypatch):
    """The app posts `{}`; curl users post nothing at all. Neither may 422."""
    exits = []
    _fake(monkeypatch, running=set(), still=set(), exits=exits)
    for kw in ({}, {"data": "not json at all"}, {"json": []}):
        exits.clear()
        r = client.post("/api/quitall", **kw)
        assert r.status_code == 200, f"{kw} -> {r.status_code} {r.text[:120]}"
        assert r.json()["bridge_exiting"] is True


def test_a_stop_that_raises_is_reported_not_swallowed(monkeypatch):
    """`_stop` catching its own exception is what keeps ONE broken lane from aborting the
    sweep — but the failure has to reach the user, not the log."""
    monkeypatch.setattr(Q, "_is_running", lambda n, c: n == "hermes")
    monkeypatch.setattr(Q, "_still_running", lambda n, c: True)
    monkeypatch.setattr(Q, "_component_stop",
                        lambda n: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(Q, "schedule_bridge_exit",
                        lambda *a, **k: pytest.fail("exited on a failed sweep"))
    r = client.post("/api/quitall", json={})
    assert r.status_code == 409
    b = r.json()
    assert b["failed"] == ["hermes"]
    assert any("RuntimeError" in s and "boom" in s for s in b["sentences"]), \
        f"the raised error must appear in the sentence: {b['sentences']}"


def test_a_second_concurrent_sweep_is_refused_not_interleaved(monkeypatch):
    """Adversarial pass: ⌥⌘Q twice, or the app plus a curl. The second caller must get a
    409 that says so — NOT a serene ok assembled from pidfiles the first sweep deleted."""
    import threading

    started, release = threading.Event(), threading.Event()

    def slow_stop(_n):
        started.set()
        release.wait(10)
        return True, "slow"

    monkeypatch.setattr(Q, "_is_running", lambda n, c: n == "hermes")
    monkeypatch.setattr(Q, "_stop", slow_stop)
    monkeypatch.setattr(Q, "_still_running", lambda n, c: False)
    monkeypatch.setattr(Q, "schedule_bridge_exit", lambda *a, **k: None)

    first = {}
    t = threading.Thread(target=lambda: first.update(
        code=client.post("/api/quitall", json={}).status_code))
    t.start()
    assert started.wait(10), "the first sweep never got going"
    second = client.post("/api/quitall", json={})
    release.set()
    t.join(20)

    assert second.status_code == 409, "the overlapping sweep was not refused"
    b = second.json()
    assert b["ok"] is False and b["bridge_exiting"] is False
    assert b["stopped"] == [] and "already running" in " ".join(b["sentences"])
    assert first.get("code") == 200, "refusing the second must not disturb the first"


def test_the_lock_is_released_even_when_a_sweep_raises(monkeypatch):
    """A wedged lock would make Quit Everything permanently impossible for the life of
    the bridge — the failure mode that turns one bad sweep into a dead feature."""
    monkeypatch.setattr(Q, "_is_running", lambda n, c: True)
    monkeypatch.setattr(Q, "_sweep",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        client.post("/api/quitall", json={})
    assert not Q._SWEEP.locked(), "the sweep lock was left held after a raise"


def test_the_openapi_surface_carries_both_routes():
    paths = json.loads(client.get("/openapi.json").text)["paths"]
    assert "/api/quitall" in paths and "post" in paths["/api/quitall"]
    assert "/api/quitall/plan" in paths and "get" in paths["/api/quitall/plan"]
    assert "get" not in paths["/api/quitall"], (
        "the acting route must be POST-only — a GET is something a browser prefetch, a "
        "link checker or ⌘R can fire by accident")
