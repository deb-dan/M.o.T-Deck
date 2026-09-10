from __future__ import annotations

import json
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from bridge.core.appctx import ROOT, app
from bridge.routers import storage


def test_idle_prefs_get_and_post(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ROOT", tmp_path)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    client = TestClient(app)

    # Initial get when file does not exist
    res = client.get("/api/storage/idle_prefs")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "prefs": {}}

    # Update one idle policy
    res = client.post("/api/storage/idle_prefs", json={"id": "hermes", "policy": "awake"})
    assert res.status_code == 200
    assert res.json()["prefs"]["hermes"] == "awake"

    # Verify persisted on disk
    saved = json.loads((tmp_path / "data" / "idle_prefs.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["prefs"]["hermes"] == "awake"

    # Update another to sleep
    res = client.post("/api/storage/idle_prefs", json={"id": "odysseus", "policy": "sleep"})
    assert res.status_code == 200
    assert res.json()["prefs"]["odysseus"] == "sleep"
    assert res.json()["prefs"]["hermes"] == "awake"

    # Invalid policy rejected / ignored
    res = client.post("/api/storage/idle_prefs", json={"id": "odysseus", "policy": "invalid_val"})
    assert res.status_code == 200
    assert res.json()["prefs"]["odysseus"] == "sleep"

    # Verify in runtimes endpoint
    res = client.get("/api/storage/runtimes")
    assert res.status_code == 200
    runtimes = res.json()["runtimes"]
    hermes_row = next((r for r in runtimes if r["id"] == "hermes"), None)
    assert hermes_row is not None
    assert hermes_row["idle_policy"] == "awake"
