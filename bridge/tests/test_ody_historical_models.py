"""U35: old Odysseus chats are labelled from current model evidence, not guesses."""
from __future__ import annotations

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


def test_other_provider_session_gets_no_mot_claim():
    got = historical_model_availability(
        "their-model", "https://api.example.test/v1", [], CFG)
    assert got == {"status": "", "note": ""}


def test_missing_evidence_gets_no_claim():
    assert historical_model_availability("", CFG["runner"]["endpoint"], [], CFG) \
        == {"status": "", "note": ""}
    assert historical_model_availability("x", "", [], CFG) \
        == {"status": "", "note": ""}
