"""A quiet socket does not prove that an owned launch stopped."""
import json
from types import SimpleNamespace

import pytest

from bridge.core import ownership, procs
from bridge.routers import aux
from bridge.tests.model_fixture import gguf_bytes


@pytest.mark.parametrize('action', ['start', 'stop'])
def test_aux_refusal_survives_a_quiet_port(tmp_path, monkeypatch, action):
    model = tmp_path / 'model.gguf'
    model.write_bytes(gguf_bytes())
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/models.json').write_text(json.dumps({'models': [
        {'id': 'fixture', 'format': 'gguf', 'path': str(model)}]}))
    monkeypatch.setattr(aux, 'ROOT', tmp_path)
    monkeypatch.setattr(aux, 'cfg', lambda: {
        'aux': {'model': 'fixture', 'api_key': 'fixture-key', 'port': 12345},
        'runner': {'binary': str(tmp_path / 'unavailable-server')}})
    monkeypatch.setattr(aux, 'foreign_runner_gate',
                        lambda *args: ('', 'fixture binary unavailable'))
    monkeypatch.setattr(aux, '_fit_advice', lambda *a, **k: None)
    monkeypatch.setattr(aux, '_aux_kill', lambda port: ['owned child could not be stopped'])
    monkeypatch.setattr(aux, '_port_alive_sync', lambda port: False)
    response = (aux.aux_start(SimpleNamespace(query_params={}))
                if action == 'start' else aux.aux_stop())
    assert response.status_code == 409
    assert json.loads(response.body)['ok'] is False
    assert 'owned child could not be stopped' in json.loads(response.body)['log']


def test_tracked_script_retires_its_completed_launch(tmp_path, monkeypatch):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    script = scripts / 'fixture.sh'
    # Keep the actual child alive until its launch identity has been recorded.
    script.write_text('#!/bin/bash\nwhile [ ! -f data/recorded ]; do sleep .01; done\necho complete\n')
    monkeypatch.setattr(procs, 'ROOT', tmp_path)
    record = procs.write_pidfile

    def recorded(*args):
        identity = record(*args)
        (tmp_path / 'data/recorded').touch()
        return identity

    monkeypatch.setattr(procs, 'write_pidfile', recorded)
    result = procs._script_tracked('fixture.sh', track='fixture', timeout=5)
    assert result.returncode == 0 and result.stdout == 'complete\n'
    assert ownership.read_claim(tmp_path, 'fixture') is None
    assert not (tmp_path / 'data/fixture.pid').exists()
