"""A targeted stop and a source selection must affect exactly what was selected."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from bridge.routers import comfy


@pytest.mark.parametrize('status,payload', [(500, {}), (200, {'cancelled': False}),
                                          (200, {})])
def test_unconfirmed_cancel_does_not_interrupt_other_work(monkeypatch, status, payload):
    calls = []

    async def post(url, **kwargs):
        calls.append(url)
        return httpx.Response(status, json=payload, request=httpx.Request('POST', url))

    monkeypatch.setattr(comfy, '_CX', SimpleNamespace(post=post))
    monkeypatch.setattr(comfy, 'comfy_url', lambda path: 'http://127.0.0.1:8188' + path)
    monkeypatch.setattr(comfy, 'publish', lambda *args, **kwargs: None)
    job = {'id': 'selected-job', 'state': 'running'}
    monkeypatch.setattr(comfy, 'JOBS', {'selected-job': job})
    response = asyncio.run(comfy.api_comfy_job_cancel('selected-job'))
    assert calls == ['http://127.0.0.1:8188/api/jobs/selected-job/cancel']
    assert job['state'] == 'running'
    assert json.loads(response.body)['ok'] is False


@pytest.mark.parametrize('existing', [b'others', b'longer other image'])
def test_gallery_source_collision_preserves_both_images(tmp_path, monkeypatch, existing):
    output, inputs = tmp_path / 'output', tmp_path / 'input'
    output.mkdir(); inputs.mkdir()
    (output / 'frame.png').write_bytes(b'chosen')
    (inputs / 'frame.png').write_bytes(existing)
    monkeypatch.setattr(comfy, 'output_dir', lambda: output)
    monkeypatch.setattr(comfy, 'input_dir', lambda: inputs)
    staged = comfy.stage_source({'filename': 'frame.png', 'origin': 'gallery'})
    assert staged is not None
    assert (inputs / staged).read_bytes() == b'chosen'
    assert (inputs / 'frame.png').read_bytes() == existing


def test_input_source_cannot_escape_its_directory(tmp_path, monkeypatch):
    inputs = tmp_path / 'input'
    inputs.mkdir()
    (tmp_path / 'outside.png').write_bytes(b'outside')
    monkeypatch.setattr(comfy, 'input_dir', lambda: inputs)
    assert comfy.stage_source({'filename': '../outside.png', 'origin': 'input'}) is None


def test_repeated_gallery_selection_reuses_identical_content(tmp_path, monkeypatch):
    output, inputs = tmp_path / 'output', tmp_path / 'input'
    output.mkdir()
    (output / 'frame.png').write_bytes(b'chosen image')
    monkeypatch.setattr(comfy, 'output_dir', lambda: output)
    monkeypatch.setattr(comfy, 'input_dir', lambda: inputs)
    source = {'filename': 'frame.png', 'origin': 'gallery'}
    assert comfy.stage_source(source) == comfy.stage_source(source) == 'frame.png'
    assert [p.name for p in inputs.iterdir()] == ['frame.png']


@pytest.mark.parametrize('during_verify', [False, True])
def test_download_cancel_closes_the_writer_before_reporting_completion(
        tmp_path, monkeypatch, during_verify):
    entered, closed = asyncio.Event(), []
    dest = tmp_path / 'model'

    class Transfer:
        status_code = 200
        headers = {'content-length': '3'}
        history = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

        async def aiter_bytes(self, size):
            yield b'abc'
            if not during_verify:
                entered.set()
                await asyncio.Event().wait()

    async def digest(path):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(comfy, '_DL', SimpleNamespace(stream=lambda *a, **kw: Transfer()))
    monkeypatch.setattr(comfy, '_sha256', digest)
    monkeypatch.setattr(comfy, 'publish', lambda *a, **kw: None)
    entry = {'id': 'cancel-test', 'state': 'downloading', 'files': [{
        'name': 'model', 'url': 'https://example.invalid/model', 'dest': str(dest),
        'bytes': 3, 'done': 0, 'sha256': 'a' * 64 if during_verify else None,
    }]}
    monkeypatch.setattr(comfy, 'CDL', {'cancel-test': entry})

    async def journey():
        task = entry['task'] = asyncio.create_task(comfy._run_cdl('cancel-test'))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await comfy.api_comfy_download_cancel('cancel-test')
            assert task.done(), 'Cancel returned while its writer was still active'
            assert closed
            assert entry['state'] == 'cancelled'
            assert not dest.exists()
            assert (tmp_path / 'model.part').read_bytes() == b'abc'
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(journey())
