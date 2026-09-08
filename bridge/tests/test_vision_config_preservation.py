"""Vision setup preserves user choices when a read fails or a default name changes."""
import asyncio

import httpx
import pytest

from bridge.core import modelid, procs
from bridge.routers import ody, odyvision


@pytest.fixture
def vision(monkeypatch, tmp_path):
    monkeypatch.setattr(ody, 'ROOT', tmp_path)
    monkeypatch.setattr(ody, 'cfg', lambda: {'runner': {'port': 12345}})
    monkeypatch.setattr(odyvision, 'cfg', lambda: {})
    monkeypatch.setattr(modelid, '_live_model_id', lambda port: 'vision')
    monkeypatch.setattr(procs, '_registry_models', lambda: [{'id': 'vision', 'vision': True}])
    monkeypatch.setattr(ody, '_ody_live_vision_model', lambda: ('vision', 'vision'))
    monkeypatch.setattr(odyvision, '_SHIM_STATE', {})


@pytest.mark.parametrize('operation', ['autowire', 'prepare', 'ensure'])
def test_failed_settings_read_cannot_trigger_writes(vision, monkeypatch, operation):
    writes = []

    async def request(method, path, **kwargs):
        if method != 'GET':
            writes.append((method, path))
        return httpx.Response(503, json={'error': 'fixture unavailable'})

    async def describe(*args, **kwargs):
        writes.append(('describe', 'runner'))
        return 'description', 'vision', '', {}

    monkeypatch.setattr(ody, '_ody_req', request)
    monkeypatch.setattr(ody, '_ody_vision_describe', describe)
    if operation == 'prepare':
        result = asyncio.run(ody.ody_vision_prepare('file', b'fixture', 'image/png', 'image'))
        assert result['source'] == 'none'
    else:
        result = asyncio.run(ody.ody_vision_autowire() if operation == 'autowire'
                             else odyvision.ody_vision_shim_ensure())
        assert not result.get('wired', result.get('ok'))
    assert not writes


def test_failed_endpoint_inventory_cannot_be_treated_as_empty(vision, monkeypatch):
    writes = []

    async def request(method, path, **kwargs):
        if method != 'GET':
            writes.append((method, path))
        return httpx.Response(503, json={})

    monkeypatch.setattr(ody, '_ody_req', request)
    result = asyncio.run(odyvision.ody_vision_shim_ensure({}))
    assert not result['ok']
    assert not writes


@pytest.mark.parametrize('enabled', [False, True])
def test_legacy_endpoint_name_never_deletes_or_reenables_the_endpoint(vision, monkeypatch, enabled):
    row = {'id': 'same-id', 'name': 'MOT Deck image describer',
           'base_url': odyvision.ody_shim_base(8700), 'is_enabled': enabled}
    writes = []

    async def request(method, path, **kwargs):
        if method != 'GET':
            writes.append((method, path, kwargs))
        if method == 'PATCH':
            row.update(kwargs['json'])
        return httpx.Response(200, json=[dict(row)] if method == 'GET' else dict(row))

    monkeypatch.setattr(ody, '_ody_req', request)
    result = asyncio.run(odyvision.ody_vision_shim_ensure({}))
    assert all(method == 'PATCH' for method, _, _ in writes)
    assert result['endpoint_id'] == 'same-id'
    assert row['is_enabled'] is enabled
    if enabled:
        assert row['name'] == odyvision.ODY_VLSHIM_EP_NAME
        assert result['ok']
    else:
        assert not writes and not result['ok']


def test_stale_endpoint_cleanup_requires_a_loopback_host():
    rows = [{'id': str(i), 'name': 'MOT Deck image describer', 'base_url': url}
            for i, url in enumerate([
                'https://localhost.example.com/odyvision/v1',
                'https://example.com/127.0.0.1/odyvision/v1',
                'http://127.0.0.1:9999/odyvision/v1'])]
    assert odyvision.ody_shim_stale_rows(rows, odyvision.ody_shim_base(8700)) == ['2']
