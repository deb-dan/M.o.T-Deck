"""U30: LOffice reload uses Hermes's read-only stored-history endpoint."""
from __future__ import annotations

from fastapi.testclient import TestClient

from bridge import app as facade
from bridge.routers import hermes


class _Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Client:
    response = _Response()
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_stored_history_is_read_only_and_normalized(monkeypatch):
    import httpx
    _Client.calls = []
    _Client.response = _Response(payload={
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "tool", "content": "not reconstructible"},
            {"role": "assistant", "content": "answer", "reasoning": "thought"},
        ],
        "pagination": {"returned": 3},
    })
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hermes, "_hermes_token", lambda: "secret")
    monkeypatch.setattr(hermes, "_hermes_port", lambda: 8642)
    response = TestClient(facade.app).get("/api/hermes/session/stored-1/history")
    assert response.status_code == 200
    assert response.json() == {
        "history": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "answer", "reasoning": "thought"},
        ],
        "count": 2, "limit_reached": False, "page_limit": 500,
    }
    assert _Client.calls == [(
        "http://127.0.0.1:8642/api/sessions/stored-1/messages",
        {"params": {"limit": 500, "offset": 0, "order": "latest",
                    "include_compacted": "true"},
         "headers": {"X-Hermes-Session-Token": "secret"}},
    )]


def test_limit_is_reported_as_possible_not_certain_truncation(monkeypatch):
    import httpx
    _Client.response = _Response(payload={"messages": [], "pagination": {"returned": 500}})
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hermes, "_hermes_token", lambda: "secret")
    response = TestClient(facade.app).get("/api/hermes/session/stored-2/history")
    assert response.status_code == 200
    assert response.json()["limit_reached"] is True


def test_history_does_not_fall_back_to_gateway_resume(monkeypatch):
    import httpx
    _Client.response = _Response(status=404)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hermes, "_hermes_token", lambda: "secret")
    monkeypatch.setattr(hermes._HERMES, "rpc",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("resume called")))
    response = TestClient(facade.app).get("/api/hermes/session/missing/history")
    assert response.status_code == 404


def test_unknown_dashboard_response_shape_fails_instead_of_showing_empty_history(monkeypatch):
    import httpx
    _Client.response = _Response(payload={"data": [{"role": "user", "content": "hidden"}]})
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setattr(hermes, "_hermes_token", lambda: "secret")
    response = TestClient(facade.app).get("/api/hermes/session/stored-3/history")
    assert response.status_code == 502
    assert "unsupported response shape" in response.json()["error"]
