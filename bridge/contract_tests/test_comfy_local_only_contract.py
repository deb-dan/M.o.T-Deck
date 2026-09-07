"""Executable local-only contracts for Comfy catalogue and direct submission."""
from __future__ import annotations

import asyncio
import json

from bridge.routers import comfy


HOSTED_UI_GRAPH = {
    "nodes": [{"id": 1, "type": "HostedNode", "mode": 0}],
    "links": [],
}
HOSTED_INFO = {
    "HostedNode": {
        "input": {"required": {}},
        "python_module": "comfy_api_nodes.partner",
        "api_node": True,
    }
}


def _catalog(*, complete: bool) -> dict:
    return {"ok": True, "models": [{
        "id": "m:hybrid", "title": "Hybrid", "refused": None,
        "workflows": [{
            "id": "hybrid", "template": "hybrid", "title": "Hybrid",
            "complete": complete,
            "files": [{"name": "local-weight.safetensors", "directory": "diffusion_models",
                       "present": complete, "bytes": 123, "state": "present" if complete else "absent"}],
        }],
    }]}


def test_catalogue_offline_does_not_offer_an_unclassified_download(monkeypatch):
    async def offline():
        return {}

    monkeypatch.setattr(comfy, "catalog", lambda: _catalog(complete=False))
    monkeypatch.setattr(comfy, "object_info", offline)
    monkeypatch.setattr(comfy, "template_graph", lambda _name: HOSTED_UI_GRAPH)
    comfy._CAT.update(at=0.0, data=None)

    result = asyncio.run(comfy.catalog_live(force=True))
    workflow = result["models"][0]["workflows"][0]
    assert workflow["local_only"] is None
    assert workflow["runnable"] is None
    assert "local-only boundary has not been checked" in workflow["run_reason"]


def test_direct_submit_rejects_hosted_node_before_missing_model_response(monkeypatch):
    async def cat():
        return _catalog(complete=False)

    async def info():
        return HOSTED_INFO

    monkeypatch.setattr(comfy, "catalog_live", cat)
    monkeypatch.setattr(comfy, "object_info", info)
    monkeypatch.setattr(comfy, "template_graph", lambda _name: HOSTED_UI_GRAPH)

    response = asyncio.run(comfy._generate_workflow({"workflow": "hybrid"}))
    body = json.loads(response.body)
    assert response.status_code == 409
    assert "outside MOT Deck's local-only Generate surface" in body["error"]
    assert "validation" not in body
    assert "missing_models" not in body
