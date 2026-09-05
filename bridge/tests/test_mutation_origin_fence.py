"""U63: browser cross-site writes are refused without buffering SSE responses."""
from __future__ import annotations

from bridge.core.appctx import mutation_origin_allowed


def test_pure_origin_table():
    allowed = mutation_origin_allowed
    assert allowed("GET", "https://evil.example", "cross-site", 8700)
    assert not allowed("POST", "https://evil.example", "cross-site", 8700)
    assert not allowed("DELETE", "https://evil.example", None, 8700)
    assert allowed("POST", "http://127.0.0.1:8700", "same-origin", 8700)
    assert allowed("POST", "http://localhost:8700", "same-site", 8700)
    assert not allowed("POST", "http://127.0.0.1:9999", "same-site", 8700)
    assert not allowed("POST", "null", None, 8700)
    assert allowed("POST", None, None, 8700)  # curl/native client


def test_cross_site_request_is_stopped_before_handler():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bridge.core.appctx import MutationFencedRoute

    sample = FastAPI()
    sample.router.route_class = MutationFencedRoute
    called = []

    @sample.post("/mutate")
    async def mutate():
        called.append(True)
        return {"ok": True}

    client = TestClient(sample)
    response = client.post("/mutate", headers={
        "Origin": "https://evil.example",
        "Sec-Fetch-Site": "cross-site",
    })
    assert response.status_code == 403
    assert called == []


def test_same_origin_and_headerless_clients_still_reach_handler():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bridge.core.appctx import MutationFencedRoute

    sample = FastAPI()
    sample.router.route_class = MutationFencedRoute

    @sample.post("/mutate")
    async def mutate():
        return {"ok": True}

    client = TestClient(sample)
    assert client.post("/mutate").status_code == 200
    assert client.post("/mutate", headers={
        "Origin": "http://testserver",
        "Sec-Fetch-Site": "same-origin",
    }).status_code == 403  # testserver is not an allowed product origin
