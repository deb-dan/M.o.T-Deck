"""U27 bulk cleanup remains exact, live-safe, and owned by Goose's CLI."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from bridge import app as facade
from bridge.routers import goose


class _FakeGoose:
    SESSION_ID_RE = __import__("re").compile(r"\d{8}_\d+")

    def __init__(self):
        self.rows = []
        self.removed = []
        self.live = ""

    def list_sessions(self, _root):
        return self.rows, ""

    def current(self):
        return SimpleNamespace(session_id=self.live, alive=lambda: bool(self.live)) \
            if self.live else None

    def remove_session(self, _root, sid):
        self.removed.append(sid)
        return True, f"session {sid} deleted"


def test_exact_empty_set_uses_goose_remove_for_each(monkeypatch):
    fake = _FakeGoose()
    fake.rows = [{"id": "20260901_1", "messages": 0},
                 {"id": "20260901_2", "messages": 3},
                 {"id": "20260901_3", "messages": 0}]
    monkeypatch.setattr(goose, "_goose", fake)
    response = TestClient(facade.app).post(
        "/api/goose/sessions/prune-empty",
        json={"ids": ["20260901_3", "20260901_1"]})
    assert response.status_code == 200
    assert fake.removed == ["20260901_1", "20260901_3"]
    assert response.json()["deleted"] == fake.removed


def test_changed_confirmation_set_refuses_without_deletion(monkeypatch):
    fake = _FakeGoose()
    fake.rows = [{"id": "20260901_1", "messages": 0},
                 {"id": "20260901_4", "messages": 0}]
    monkeypatch.setattr(goose, "_goose", fake)
    response = TestClient(facade.app).post(
        "/api/goose/sessions/prune-empty", json={"ids": ["20260901_1"]})
    assert response.status_code == 409
    assert fake.removed == []
    assert response.json()["current_ids"] == ["20260901_1", "20260901_4"]


def test_live_empty_session_is_never_a_prune_target(monkeypatch):
    fake = _FakeGoose()
    fake.live = "20260901_9"
    fake.rows = [{"id": "20260901_1", "messages": 0},
                 {"id": "20260901_9", "messages": 0}]
    monkeypatch.setattr(goose, "_goose", fake)
    response = TestClient(facade.app).post(
        "/api/goose/sessions/prune-empty",
        json={"ids": ["20260901_1", "20260901_9"]})
    assert response.status_code == 409
    assert fake.removed == []
