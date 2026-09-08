"""A render owns its scratch output, never an existing library track."""
from pathlib import Path

import pytest

from bridge import music


@pytest.fixture
def render_case(tmp_path, monkeypatch):
    monkeypatch.setattr(music, '_JOB', None)
    monkeypatch.setattr(music, 'track_name', lambda *a, **kw: 'song.wav')
    params = {'engine': 'minimax', 'prompt': 'piano', 'seconds': 60,
              'steps': 30, 'seed': 7, 'format': 'wav'}
    job, error = music.claim_job(params)
    assert not error
    return tmp_path, params, job, Path(music.music_dir(tmp_path))


def test_failed_render_never_publishes_partial_audio(render_case):
    root, params, job, library = render_case

    def render(root, params, scratch, output):
        Path(output).write_bytes(b'incomplete')
        assert not list(library.glob('*.wav')), 'partial render is visible in the library'
        raise music.MusicError('engine failed after opening its output')

    result = music.run_job(root, params, job, render=render, log=lambda *a, **kw: None)
    assert result['state'] == 'failed'
    assert not list(library.glob('*.wav'))


def test_same_timestamp_preserves_existing_song_and_metadata(render_case):
    root, params, job, library = render_case
    (library / 'song.wav').write_bytes(b'previous song')
    (library / 'song.json').write_text('{"title":"Previous song"}')

    def render(root, params, scratch, output):
        Path(output).write_bytes(b'new song')

    result = music.run_job(root, params, job, render=render, log=lambda *a, **kw: None)
    assert result['state'] == 'done'
    assert (library / result['out']).read_bytes() == b'new song'
    assert (library / 'song.wav').read_bytes() == b'previous song'
    assert (library / 'song.json').read_text() == '{"title":"Previous song"}'


def test_cancel_before_worker_starts_does_not_render(render_case):
    root, params, job, library = render_case
    music.cancel_job(log=lambda *a, **kw: None)
    calls = []

    def render(root, params, scratch, output):
        calls.append(True)
        Path(output).write_bytes(b'should not be generated')

    result = music.run_job(root, params, job, render=render, log=lambda *a, **kw: None)
    assert result['state'] == 'cancelled'
    assert not calls and not list(library.glob('*.wav'))


def test_scratch_failure_releases_the_job_slot(render_case, monkeypatch):
    root, params, job, library = render_case

    def fail(**kwargs):
        raise OSError('scratch volume is full')

    monkeypatch.setattr(music.tempfile, 'mkdtemp', fail)
    try:
        result = music.run_job(root, params, job, log=lambda *a, **kw: None)
    except OSError:
        result = music.current_job()
    assert result['state'] == 'failed'
    assert not music.job_busy()
