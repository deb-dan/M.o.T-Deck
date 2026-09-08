"""Transcripts, replay identity, and worker replacement reflect the current request."""
import io
import json
import os
from types import SimpleNamespace

import pytest

from bridge import voice


def test_fallback_reads_nested_transcript_after_warning(tmp_path):
    payload = {'text': 'The complete transcript', 'segments': [{'text': 'The complete transcript'}]}
    assert voice.stt_read_output(str(tmp_path), 'in', 'Warning: optional decoder\n' + json.dumps(payload)) == payload['text']


def test_cache_fields_cannot_impersonate_boundaries():
    assert voice.render_cache_key('m', 'a\0b', 'c', '', 'text') != voice.render_cache_key('m', 'a', 'b\0c', '', 'text')


@pytest.mark.parametrize('change', [
    {'path': '/models/replacement.gguf'}, {'mmproj': '/models/replacement-projector.gguf'},
    {'lang': 'fr'}, {'max_frames': 100}, {'format': 'tts-mlx'},
])
def test_replay_changes_with_engine_arguments(change):
    entry = {'id': 'voice', 'format': 'tts-gguf', 'path': '/models/voice.gguf',
             'mmproj': '/models/projector.gguf', 'voice': 'speaker'}
    assert voice.entry_cache_key(entry, 'Hello') != voice.entry_cache_key(dict(entry, **change), 'Hello')


def test_clip_replacement_within_one_second_changes_stamp(tmp_path):
    path = tmp_path / 'clip.wav'
    path.write_bytes(b'first')
    os.utime(path, ns=(10_100_000_000, 10_100_000_000))
    before = voice.ref_stamp(path)
    path.write_bytes(b'other')
    os.utime(path, ns=(10_200_000_000, 10_200_000_000))
    assert voice.ref_stamp(path) != before


class Worker:
    def __init__(self, model_id, model_path, *args, **kwargs):
        self.model_id, self.model_path = model_id, model_path
        self.stopped = False
        self.load_secs = 0

    def alive(self):
        return not self.stopped

    def stop(self):
        self.stopped = True

    def start(self):
        pass


def test_same_registry_id_with_new_path_replaces_worker(monkeypatch):
    old = Worker('voice', '/old')
    monkeypatch.setattr(voice, '_WORKER', old)
    monkeypatch.setattr(voice, 'VoiceWorker', Worker)
    current = voice.get_worker({'id': 'voice', 'path': '/new'})
    assert current.model_path == '/new' and old.stopped


def test_stop_rechecks_model_after_acquiring_swap_lock(monkeypatch):
    old, replacement = Worker('old', '/old'), Worker('new', '/new')

    class SwapBeforeLock:
        def __enter__(self):
            voice._WORKER = replacement

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(voice, '_WORKER', old)
    monkeypatch.setattr(voice, '_WORKER_MUTEX', SwapBeforeLock())
    assert voice.worker_stop_if_model('old') is False
    assert voice._WORKER is replacement and not replacement.stopped


def test_stale_replies_cannot_extend_deadline(monkeypatch):
    worker = voice.VoiceWorker('voice', '/model')
    worker.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    ticks = iter(range(100))
    monkeypatch.setattr(voice.time, 'monotonic', lambda: next(ticks))
    replies = iter([json.dumps({'id': 999, 'ok': True})] * 5 + [None])
    worker._q = SimpleNamespace(get=lambda **kwargs: next(replies))
    monkeypatch.setattr(worker, 'stop', lambda: None)
    with pytest.raises(voice.VoiceError, match='did not answer'):
        worker._request({'cmd': 'tts'}, 2)
