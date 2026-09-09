"""Voice settings and delayed clip preparation cannot overwrite newer choices."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from bridge import voice
from bridge.core import yamlset
from bridge.routers import downloads as D, voice as V


class Request:
    def __init__(self, body):
        self.value = body

    async def json(self):
        return self.value


@pytest.fixture
def state(tmp_path, monkeypatch):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'motdeck.yaml').write_text('voice:\n  tts_model: old # keep\n  stt_model: stt\n')
    rows = [{'id': 'on', 'kind': 'audio', 'format': 'tts-mlx', 'path': '/models/on'},
            {'id': 'stt', 'kind': 'audio', 'format': 'stt-mlx', 'path': '/models/stt'}]
    (tmp_path / 'data/models.json').write_text(json.dumps({'models': rows}))
    for module in (V, D, yamlset):
        monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(V, '_registry_models', lambda: rows)
    monkeypatch.setattr(V, '_voice_cfg', lambda: yaml.safe_load((tmp_path / 'motdeck.yaml').read_text())['voice'])
    stopped = []
    monkeypatch.setattr(voice, 'worker_stop', stopped.append)
    return tmp_path, rows, stopped


def test_invalid_second_default_has_no_side_effects(state):
    root, _, stopped = state
    before = (root / 'motdeck.yaml').read_bytes()
    result = asyncio.run(V.voice_config_set(Request({'tts_model': 'on', 'stt_model': 'missing'})))
    assert result.status_code == 400
    assert (root / 'motdeck.yaml').read_bytes() == before
    assert stopped == []


def test_defaults_commit_once_and_keep_literal_model_id(state, monkeypatch):
    root, _, stopped = state
    writes = []
    original = yamlset.transform_file
    def transform(path, edit):
        writes.append(path)
        return original(path, edit)
    monkeypatch.setattr(yamlset, 'transform_file', transform)
    result = asyncio.run(V.voice_config_set(Request({'tts_model': 'on', 'stt_model': ''})))
    assert result.status_code == 200 and len(writes) == 1
    assert yaml.safe_load((root / 'motdeck.yaml').read_text())['voice'] == {'tts_model': 'on', 'stt_model': None}
    assert '# keep' in (root / 'motdeck.yaml').read_text() and len(stopped) == 1


def test_failed_config_write_does_not_unload(state, monkeypatch):
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(V, '_set_yaml_scalars', fail)
    assert asyncio.run(V.voice_config_set(Request({'tts_model': 'on'}))).status_code == 500
    assert state[2] == []


def test_late_transcription_does_not_caption_replacement_clip(state, monkeypatch):
    root, rows, _ = state
    original = dict(rows[0], ref_audio='/old.wav')
    (root / 'data/models.json').write_text(json.dumps({'models': [original]}))
    async def transcribe(*args):
        D._registry_update('on', {'ref_audio': '/new.wav', 'ref_text': 'new words'})
        return 'old words'
    monkeypatch.setattr(V, '_transcribe_clip', transcribe)
    assert asyncio.run(V._heal_ref_text(original, rows)) is None
    assert json.loads((root / 'data/models.json').read_text())['models'][0]['ref_text'] == 'new words'


def test_failed_trim_never_publishes_partial_audio(state, monkeypatch):
    root, _, _ = state
    src = root / 'source.wav'
    src.write_bytes(b'original')
    dst = root / 'trimmed/copy.wav'
    monkeypatch.setattr(voice, 'trimmed_clip_path', lambda *args: str(dst))
    def fail(argv, **kwargs):
        Path(argv[-1]).write_bytes(b'incomplete WAV')
        return SimpleNamespace(returncode=1, stderr='decoder failed')
    monkeypatch.setattr(V.subprocess, 'run', fail)
    path, reason = V._trim_ref_clip('ffmpeg', str(src))
    assert path is None and 'decoder failed' in reason
    assert not dst.exists() and list(dst.parent.iterdir()) == []


def test_exhausted_recording_names_never_return_existing_file(tmp_path):
    for n in range(100):
        (tmp_path / ('clip.wav' if n == 0 else f'clip ({n}).wav')).write_bytes(b'original')
    with pytest.raises(FileExistsError):
        voice.unique_clip_path(str(tmp_path), 'clip.wav')
    assert all(p.read_bytes() == b'original' for p in tmp_path.iterdir())


def test_dangling_recording_link_counts_as_occupied(tmp_path):
    (tmp_path / 'clip.wav').symlink_to(tmp_path / 'missing')
    assert Path(voice.unique_clip_path(str(tmp_path), 'clip.wav')).name == 'clip (1).wav'


@pytest.mark.parametrize('failure', ['registry', 'remove'])
def test_delete_failure_preserves_recording_and_pins(state, monkeypatch, failure):
    root, rows, _ = state
    path = root / 'data/voices/clip.wav'
    path.parent.mkdir()
    path.write_bytes(b'irreplaceable recording')
    pinned = dict(rows[0], ref_audio=str(path), ref_text='words')
    registry = root / 'data/models.json'
    registry.write_text(json.dumps({'models': [pinned]}))
    def fail(*args):
        raise OSError('simulated failure')
    if failure == 'registry':
        monkeypatch.setattr(V, 'write_registry', fail)
    else:
        monkeypatch.setattr(V.os, 'remove', fail)
    result = asyncio.run(V.voice_library_delete(Request({'name': 'clip.wav'})))
    assert result.status_code == 500
    assert path.read_bytes() == b'irreplaceable recording'
    assert json.loads(registry.read_text())['models'] == [pinned]


def test_delete_unpins_every_matching_entry_and_preserves_neighbors(state):
    root, rows, _ = state
    path = root / 'data/voices/clip.wav'
    path.parent.mkdir()
    path.write_bytes(b'recording')
    registry = root / 'data/models.json'
    first = dict(rows[0], ref_audio=str(path), ref_text='first transcript')
    second = dict(first, id='another', ref_text='second transcript')
    neighbor = dict(rows[1], ref_audio=str(path.with_name('keep.wav')), ref_text='keep')
    registry.write_text(json.dumps({'models': [first, second, neighbor], 'metadata': 'keep'}))
    result = asyncio.run(V.voice_library_delete(Request({'name': 'clip.wav'})))
    assert result.status_code == 200
    assert json.loads(result.body)['unpinned'] == ['on', 'another']
    saved = json.loads(registry.read_text())
    assert saved['metadata'] == 'keep' and saved['models'][2] == neighbor
    assert all('ref_audio' not in row and 'ref_text' not in row for row in saved['models'][:2])
    assert not path.exists()


def test_trim_cache_separates_same_names_and_source_replacements(tmp_path):
    first, second = tmp_path / 'one/clip.wav', tmp_path / 'two/clip.wav'
    for p in (first, second):
        p.parent.mkdir()
        p.write_bytes(b'voice')
    before = voice.trimmed_clip_path(first, tmp_path)
    assert before != voice.trimmed_clip_path(second, tmp_path)
    first.write_bytes(b'a replacement voice')
    assert before != voice.trimmed_clip_path(first, tmp_path)
