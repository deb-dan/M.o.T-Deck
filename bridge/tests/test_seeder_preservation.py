"""Real seeder entry points must not replace unknown configuration with defaults."""
import json
from pathlib import Path
import stat

import pytest

from scripts import seed_opencode_config as oc
from scripts import seed_hermes_provider as hermes
from scripts import seed_deepseek_config as deepseek
from scripts import seed_registry as registry
from bridge import gooseprov


def _oc_env(monkeypatch, tmp_path):
    monkeypatch.setenv('MOT_DECK_ROOT', str(tmp_path))
    monkeypatch.setenv('OC_CFG', str(tmp_path / 'opencode.json'))
    monkeypatch.setenv('OC_PCFG', '')
    monkeypatch.setenv('OC_BASE', 'http://127.0.0.1:6767/v1')
    monkeypatch.setenv('OC_KEY', 'test-key')


@pytest.mark.parametrize('raw', ['{"theme": "mine",', '[{"theme":"mine"}]'])
def test_opencode_unknown_config_is_preserved(tmp_path, monkeypatch, raw):
    _oc_env(monkeypatch, tmp_path)
    path = tmp_path / 'opencode.json'
    path.write_text(raw)
    try:
        oc.main()
    except ValueError:
        pass
    assert path.read_text() == raw


def test_opencode_seed_is_private_and_idempotent(tmp_path, monkeypatch):
    _oc_env(monkeypatch, tmp_path)
    path = tmp_path / 'opencode.json'
    path.write_text('{"theme":"mine"}')
    assert oc.main() == 0
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert oc.main() == 0
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def _hermes_env(monkeypatch, tmp_path):
    monkeypatch.setenv('HERMES_CFG', str(tmp_path / 'config.yaml'))
    monkeypatch.setenv('BASE_URL', 'http://127.0.0.1:6767/v1')
    monkeypatch.setenv('MOT_DECK_ROOT', str(tmp_path))
    monkeypatch.setenv('KEY', 'test-key')
    monkeypatch.setenv('MODEL', 'test-model')


def test_hermes_non_mapping_config_is_preserved(tmp_path, monkeypatch):
    _hermes_env(monkeypatch, tmp_path)
    path = tmp_path / 'config.yaml'
    raw = '- custom-setting: mine\n'
    path.write_text(raw)
    hermes.main()
    assert path.read_text() == raw


def test_hermes_honoured_key_is_never_logged_or_saved_in_verdict():
    _, notes = hermes.model_block_plan(
        {'api_key': 'private-credential'}, {'api_key': 'old-managed'},
        {'api_key': 'new-managed'}, set(), seeded_before=True)
    assert notes and all('private-credential' not in note for note in notes)


def test_deepseek_preserves_invalid_provider_namespace(tmp_path, monkeypatch):
    path = tmp_path / 'settings.yaml'
    raw = 'llm-pi-ai:\n  providers:\n    - id: my-old-route\n      apiKey: preserve-me\n'
    path.write_text(raw)
    monkeypatch.setenv('DS_SETTINGS', str(path))
    monkeypatch.setenv('DS_BASE', 'http://127.0.0.1:6767/v1')
    monkeypatch.setenv('MOT_DECK_ROOT', str(tmp_path))
    monkeypatch.setattr(deepseek, 'catalog', lambda _: [{'id': 'test-model'}])
    deepseek.main()
    assert path.read_text() == raw


def test_registry_seed_refuses_corrupt_existing_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/models.json'
    raw = '{"models": [{"id":"my-model"},'
    path.write_text(raw)
    monkeypatch.setattr(registry, 'local_entries_for', lambda _: [])
    monkeypatch.setattr(registry, 'scan_audio_hf_cache', lambda _: [])
    monkeypatch.setattr(registry, 'scan_jan', lambda _: [])
    try:
        registry.main([])
    except ValueError:
        pass
    assert path.read_text() == raw


def test_registry_seed_retains_top_level_metadata(tmp_path):
    path = tmp_path / 'models.json'
    path.write_text(json.dumps({'models': [], 'user_metadata': {'keep': True}}))
    registry.write(str(path), [{'id': 'model'}])
    assert json.loads(path.read_text()) == {
        'models': [{'id': 'model'}], 'user_metadata': {'keep': True}}


@pytest.mark.parametrize('raw', [b'{"headers":', b'[]', b'null', b'\xff'])
def test_goose_unknown_provider_is_preserved(tmp_path, raw):
    path = Path(gooseprov.provider_path(tmp_path))
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    _, changed, error = gooseprov.seed_provider(tmp_path, 'http://127.0.0.1:6767/v1', [])
    assert not changed and error
    assert path.read_bytes() == raw


def test_goose_provider_publish_failure_preserves_customizations(tmp_path, monkeypatch):
    path = Path(gooseprov.provider_path(tmp_path))
    path.parent.mkdir(parents=True)
    raw = '{"display_name":"My runner","headers":{"X-Mine":"keep"}}'
    path.write_text(raw)
    def refuse(*args):
        raise OSError('disk refused replacement')
    monkeypatch.setattr(gooseprov.os, 'replace', refuse)
    _, changed, error = gooseprov.seed_provider(tmp_path, 'http://127.0.0.1:6767/v1', [])
    assert not changed and error
    assert path.read_text() == raw
    assert list(path.parent.iterdir()) == [path]


def test_goose_provider_fifo_refused_without_waiting(tmp_path):
    import os
    import subprocess
    import sys
    path = Path(gooseprov.provider_path(tmp_path))
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    code = ('from bridge import gooseprov as g; import sys; '
            '_, changed, error = g.seed_provider(sys.argv[1], "http://127.0.0.1:6767/v1", []); '
            'assert not changed and error')
    subprocess.run([sys.executable, '-c', code, str(tmp_path)], check=True, timeout=5)
    assert stat.S_ISFIFO(path.stat().st_mode)
