from fastapi.testclient import TestClient
import pytest

from bridge import app as facade
from bridge.routers import storage as S


client = TestClient(facade.app)


@pytest.fixture(autouse=True)
def _plans_clean():
    with S._PLAN_LOCK:
        S._PLANS.clear()
    yield
    with S._PLAN_LOCK:
        S._PLANS.clear()


def test_clear_all_refuses_when_the_previewed_session_set_changes(monkeypatch):
    rows = [{"id": "a", "updated_at": 1, "message_count": 2}]

    async def current(_lane):
        return list(rows)

    called = []
    async def delete(lane, sid):
        called.append((lane, sid))
        return True, "deleted"

    monkeypatch.setattr(S, "_chat_rows", current)
    monkeypatch.setattr(S, "_delete_one_chat", delete)
    preview = client.post("/api/storage/chats/plan", json={"lane": "odysseus"}).json()
    rows.append({"id": "b", "updated_at": 2, "message_count": 1})
    result = client.post("/api/storage/chats/apply", json={"token": preview["token"]})
    assert result.status_code == 409
    assert "session list changed" in result.json()["error"]
    assert called == []


def test_clear_all_reports_partial_per_session_receipts(monkeypatch):
    rows = [{"id": "a", "updated_at": 1, "message_count": 2},
            {"id": "b", "updated_at": 2, "message_count": 3}]

    async def current(_lane):
        return list(rows)

    async def delete(_lane, sid):
        return (True, "deleted") if sid == "a" else (False, "upstream refused")

    monkeypatch.setattr(S, "_chat_rows", current)
    monkeypatch.setattr(S, "_delete_one_chat", delete)
    preview = client.post("/api/storage/chats/plan", json={"lane": "hermes"}).json()
    result = client.post("/api/storage/chats/apply", json={"token": preview["token"]})
    assert result.status_code == 409
    data = result.json()
    assert data["deleted"] == 1 and data["count"] == 2 and data["atomic"] is False
    assert data["receipts"] == [
        {"id": "a", "ok": True, "detail": "deleted"},
        {"id": "b", "ok": False, "detail": "upstream refused"},
    ]


def test_preview_token_is_one_use(monkeypatch):
    async def current(_lane):
        return [{"id": "a", "updated_at": 1, "message_count": 2}]

    async def delete(_lane, _sid):
        return True, "deleted"

    monkeypatch.setattr(S, "_chat_rows", current)
    monkeypatch.setattr(S, "_delete_one_chat", delete)
    token = client.post("/api/storage/chats/plan", json={"lane": "odysseus"}).json()["token"]
    assert client.post("/api/storage/chats/apply", json={"token": token}).status_code == 200
    again = client.post("/api/storage/chats/apply", json={"token": token})
    assert again.status_code == 409 and "expired or was already used" in again.json()["error"]


def test_connection_loss_keeps_receipts_for_completed_and_remaining_sessions(monkeypatch):
    async def current(_lane):
        return [{"id": sid} for sid in ("a", "b", "c")]

    async def delete(_lane, sid):
        if sid == "b":
            raise ConnectionError("response lost")
        return True, "deleted"

    monkeypatch.setattr(S, "_chat_rows", current)
    monkeypatch.setattr(S, "_delete_one_chat", delete)
    token = client.post("/api/storage/chats/plan", json={"lane": "odysseus"}).json()["token"]
    response = client.post("/api/storage/chats/apply", json={"token": token})
    assert response.status_code == 409
    result = response.json()
    assert result["deleted"] == 2 and result["count"] == 3
    assert [r["ok"] for r in result["receipts"]] == [True, False, True]
    assert "could not confirm" in result["receipts"][1]["detail"]
