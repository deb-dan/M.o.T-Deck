"""U39: explicit Rescan refreshes only the proven managed Odysseus picker."""
from __future__ import annotations

import asyncio
import json


def _row(**changes):
    row = {
        "id": "local-jan",
        "name": "Local runner",
        "base_url": "http://127.0.0.1:6767/v1",
        "api_key": "key",
        "is_enabled": True,
        "model_type": "llm",
        "endpoint_kind": "local",
        "model_refresh_mode": "auto",
        "supports_tools": True,
        "pinned_models": ["old"],
        "cached_models": ["old"],
        "hidden_models": [],
    }
    row.update(changes)
    return row


def test_live_plan_requires_all_three_ownership_facts():
    from bridge.routers import model_rescan as route

    marker = {"pinned_models": ["old"]}
    plan = route._ody_live_catalog_plan([_row()], ["new"], marker,
                                        "http://127.0.0.1:6767/v1")
    assert plan == {"action": "patch", "id": "local-jan",
                    "pinned_models": ["new"]}

    assert route._ody_live_catalog_plan(
        [_row(id="user-row")], ["new"], marker,
        "http://127.0.0.1:6767/v1")["action"] == "refuse"
    assert route._ody_live_catalog_plan(
        [_row(base_url="http://user-box:9000/v1")], ["new"], marker,
        "http://127.0.0.1:6767/v1")["action"] == "honour"
    assert route._ody_live_catalog_plan(
        [_row(is_enabled=False)], ["new"], marker,
        "http://127.0.0.1:6767/v1")["action"] == "honour"
    assert route._ody_live_catalog_plan(
        [_row()], [], marker, "http://127.0.0.1:6767/v1")["action"] == "refuse"


def test_human_curated_picker_is_not_replaced():
    from bridge.routers import model_rescan as route

    plan = route._ody_live_catalog_plan(
        [_row(pinned_models=["mine", "other"])], ["new"],
        {"pinned_models": ["old"]}, "http://127.0.0.1:6767/v1")
    assert plan["action"] == "honour"
    assert "honoured your" in plan["reason"]


def test_acknowledged_live_patch_is_read_back_before_marker_moves(tmp_path, monkeypatch):
    from bridge.routers import model_rescan as route

    seed = route._ody_seed_module()
    state_path = tmp_path / "ody_seed_state.json"
    monkeypatch.setattr(seed, "STATE_PATH", str(state_path))
    seed._save_state({"local-jan": {"pinned_models": ["old"]}})
    monkeypatch.setattr(route, "_rescan_wire_inventory", lambda: (["new-a", "new-b"], "new-a"))
    monkeypatch.setattr(route, "_port_alive_sync", lambda _port: True)
    monkeypatch.setattr(route, "cfg", lambda: {
        "runner": {"endpoint": "http://127.0.0.1:6767/v1"},
        "components": {"odysseus": {"port": 7860}},
    })

    current = _row()
    calls = []

    class Response:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body

        def json(self):
            return self._body

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PATCH":
            current["pinned_models"] = list(kwargs["json"]["pinned_models"])
            return Response(200, {"id": "local-jan", "pinned_count": 2})
        return Response(200, [dict(current)])

    import bridge.routers.ody as ody
    monkeypatch.setattr(ody, "_ody_req", request)
    result = asyncio.run(route._rebind_odysseus_after_rescan())
    assert result == "Odysseus: live picker refreshed (2 models)"
    assert [call[:2] for call in calls] == [
        ("GET", "/api/model-endpoints"),
        ("PATCH", "/api/model-endpoints/local-jan/models"),
        ("GET", "/api/model-endpoints"),
    ]
    assert json.loads(state_path.read_text())["local-jan"]["pinned_models"] \
        == ["new-a", "new-b"]


def test_unacknowledged_patch_never_advances_ownership_marker(tmp_path, monkeypatch):
    from bridge.routers import model_rescan as route

    seed = route._ody_seed_module()
    state_path = tmp_path / "ody_seed_state.json"
    monkeypatch.setattr(seed, "STATE_PATH", str(state_path))
    seed._save_state({"local-jan": {"pinned_models": ["old"]}})
    monkeypatch.setattr(route, "_rescan_wire_inventory", lambda: (["new"], "new"))
    monkeypatch.setattr(route, "_port_alive_sync", lambda _port: True)
    monkeypatch.setattr(route, "cfg", lambda: {
        "runner": {"endpoint": "http://127.0.0.1:6767/v1"},
        "components": {"odysseus": {"port": 7860}},
    })

    class Response:
        status_code = 200

        def json(self):
            return [_row()] if not hasattr(self, "posted") else {}

    calls = 0

    async def request(method, _path, **_kwargs):
        nonlocal calls
        calls += 1
        if method == "PATCH":
            response = Response()
            response.posted = True
            return response
        return Response()

    import bridge.routers.ody as ody
    monkeypatch.setattr(ody, "_ody_req", request)
    result = asyncio.run(route._rebind_odysseus_after_rescan())
    assert "not acknowledged exactly" in result
    assert calls == 2
    assert json.loads(state_path.read_text())["local-jan"]["pinned_models"] == ["old"]
