"""Completing one download cannot erase an unreadable library or user settings."""
import json

import pytest

from bridge.routers import downloads
from bridge.tests.model_fixture import gguf_bytes


@pytest.mark.parametrize('original', [b'{broken', b'{"other":"keep"}', b'{"models":null}', b'\xff'])
def test_corrupt_registry_is_preserved_when_a_download_finishes(tmp_path, monkeypatch, original):
    (tmp_path / 'data').mkdir()
    registry = tmp_path / 'data/models.json'
    registry.write_bytes(original)
    monkeypatch.setattr(downloads, 'ROOT', tmp_path)
    with pytest.raises((ValueError, UnicodeError)):
        downloads._registry_add({'id': 'new'})
    assert registry.read_bytes() == original


def test_downloading_same_artifact_keeps_user_choices(tmp_path, monkeypatch):
    model = tmp_path / 'data/models/fixture.gguf'
    model.parent.mkdir(parents=True)
    model.write_bytes(gguf_bytes())
    registry = tmp_path / 'data/models.json'
    preferences = {'voice': 'chosen', 'ref_audio': '/chosen.wav', 'ref_text': 'words',
                   'hidden': True, 'settings': {'temperature': .25},
                   'load': {'ctx': 4096}, 'ctx': 8192, 'name': 'My model'}
    entry = {'id': 'fixture', 'path': str(model), 'source': 'download',
             'format': 'gguf', 'absent': True, **preferences}
    registry.write_text(json.dumps({'models': [entry], 'custom': 'keep'}))
    monkeypatch.setattr(downloads, 'ROOT', tmp_path)
    downloads._registry_add({'id': 'fixture', 'path': str(model), 'source': 'download',
                              'format': 'gguf', 'name': 'fixture', 'ctx': None})
    saved = json.loads(registry.read_text())
    assert saved['custom'] == 'keep'
    assert all(saved['models'][0].get(k) == v for k, v in preferences.items())
    assert not saved['models'][0].get('absent')
