"""U35: old Odysseus chats are labelled from current model evidence, not guesses."""
from __future__ import annotations

import asyncio
import json

from bridge.routers import ody
from bridge.routers.ody import historical_model_availability
from bridge.tests.model_fixture import gguf_bytes


CFG = {"runner": {"endpoint": "http://127.0.0.1:6767/v1"}}


def test_current_registry_id_is_available(tmp_path):
    artifact = tmp_path / "model.gguf"
    artifact.write_bytes(gguf_bytes())
    row = {"id": "current", "format": "gguf", "path": str(artifact)}
    got = historical_model_availability("current", CFG["runner"]["endpoint"], [row], CFG)
    assert got == {"status": "available", "note": ""}


def test_absent_local_model_is_unavailable_not_called_deleted():
    got = historical_model_availability(
        "old-model", CFG["runner"]["endpoint"], [], CFG)
    assert got["status"] == "unavailable"
    assert "not available" in got["note"]
    assert "deleted" not in got["note"].lower()


def test_odysseus_concrete_chat_route_matches_runner_base():
    got = historical_model_availability(
        "old-model", CFG["runner"]["endpoint"] + "/chat/completions", [], CFG)
    assert got["status"] == "unavailable"


def test_endpoint_comparison_does_not_claim_aliases_or_neighboring_routes():
    for endpoint in (
        "http://localhost:6767/v1/chat/completions",
        "http://127.0.0.1:6768/v1/chat/completions",
        "http://127.0.0.1:6767/other/chat/completions",
        "http://127.0.0.1:6767/v1/chat/completions?tenant=other",
        "http://user:secret@127.0.0.1:6767/v1/chat/completions",
        "http://127.0.0.1:6767/v1/models",
        "http://127.0.0.1:6767/v1/responses",
    ):
        assert historical_model_availability("old-model", endpoint, [], CFG) == {
            "status": "", "note": ""}


def test_other_provider_session_gets_no_mot_claim():
    got = historical_model_availability(
        "their-model", "https://api.example.test/v1", [], CFG)
    assert got == {"status": "", "note": ""}


def test_missing_evidence_gets_no_claim():
    assert historical_model_availability("", CFG["runner"]["endpoint"], [], CFG) \
        == {"status": "", "note": ""}
    assert historical_model_availability("x", "", [], CFG) \
        == {"status": "", "note": ""}


def test_sessions_route_uses_only_persisted_owned_endpoint_evidence(monkeypatch, tmp_path):
    artifact = tmp_path / "current.gguf"
    artifact.write_bytes(gguf_bytes())
    registry = [{"id": "current", "format": "gguf", "path": str(artifact)}]

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return [
                {"id": "historic", "name": "Old chat", "model": "withdrawn-model",
                 "endpoint_url": CFG["runner"]["endpoint"] + "/chat/completions",
                 "updated_at": "2026-09-05T12:00:00", "message_count": 2},
                {"id": "current", "name": "Current chat", "model": "current",
                 "endpoint_url": CFG["runner"]["endpoint"] + "/chat/completions",
                 "updated_at": "2026-09-05T11:00:00", "message_count": 2},
                {"id": "foreign", "name": "Foreign chat", "model": "their-model",
                 "endpoint_url": "https://api.example.test/v1/chat/completions",
                 "updated_at": "2026-09-05T10:00:00", "message_count": 2},
                {"id": "unknown", "name": "Unknown endpoint", "model": "old",
                 "endpoint_url": "", "updated_at": "2026-09-05T09:00:00",
                 "message_count": 2},
            ]

    async def request(*_args, **_kwargs):
        return Response()

    monkeypatch.setattr(ody, "_ody_req", request)
    monkeypatch.setattr(ody, "_registry_models", lambda: registry)
    monkeypatch.setattr(ody, "cfg", lambda: CFG)
    response = asyncio.run(ody.ody_sessions())
    rows = json.loads(response.body)
    assert rows[0]["model_status"] == "unavailable"
    assert "not available" in rows[0]["model_note"]
    assert rows[1]["model_status"] == "available"
    assert rows[2]["model_status"] == ""
    assert rows[3]["model_status"] == ""
