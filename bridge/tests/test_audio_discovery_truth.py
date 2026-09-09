"""Search and engine selection distinguish an empty result from a broken query."""
import asyncio
import json

import pytest

from bridge.routers import hf


@pytest.mark.parametrize(('config', 'expected'), [
    ({'model_type': 'parakeet'}, 'stt-mlx-audio'),
    ({key: 1 for key in hf.AUDIO_WHISPER_REQUIRED}, 'stt-mlx'),
    ({'architectures': ['WhisperForConditionalGeneration']}, 'transformers'),
])
def test_asr_engine_evidence_outranks_the_shared_mlx_audio_tag(config, expected):
    result = hf.audio_probe_verdict(
        'fixture/speech-model', config,
        [('config.json', 100), ('model.safetensors', 1000)],
        ['mlx-audio', 'automatic-speech-recognition'], 'automatic-speech-recognition')
    assert result['format'] == expected


def test_successful_search_with_no_matches_is_empty_not_failed(monkeypatch):
    async def fetch(*args):
        return []

    monkeypatch.setattr(hf, '_hf_json', fetch)
    response = asyncio.run(hf.hf_audio_search(q='no-matching-model', kind='tts'))
    assert response.status_code == 200
    assert json.loads(response.body) == []


def test_search_failure_still_reports_an_error(monkeypatch):
    async def fetch(*args):
        return None

    monkeypatch.setattr(hf, '_hf_json', fetch)
    response = asyncio.run(hf.hf_audio_search(q='query', kind='tts'))
    assert response.status_code == 502
    assert json.loads(response.body)['error']
