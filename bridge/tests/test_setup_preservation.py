"""Run setup scripts with inert runtimes against temporary installations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYTHON_STUB = '''#!{python}
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['SETUP_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if args[:2] == ['-m', 'venv']:
    target = pathlib.Path(args[2]) / 'bin'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'python').write_bytes(pathlib.Path(__file__).read_bytes())
    (target / 'python').chmod(0o755)
elif args == ['--version']:
    print('Python 3.12.0')
elif args[:1] == ['-c']:
    print('generated-test-secret')
'''


def _archive(source, destination):
    with tarfile.open(destination, 'w:gz') as archive:
        archive.add(source, arcname='.')


def _fat_run(tmp_path, existing=None):
    res, dest, seed = [tmp_path / name for name in ('resources', 'runtime', 'seed')]
    for path in (res, dest, seed, res / 'wheelhouse'):
        path.mkdir()
    for rel, body in {
        'motdeck.yaml': 'components:\n  hermes:\n    installed: true\nbuild:\n  mlx_lm_pin: "1.1"\n  mlx_vlm_pin: "2.2"\n  mlx_audio_pin: "3.3"\n  mlx_whisper_pin: "4.4"\n',
        'SEED_STAMP': 'date=2026-09-08T00:00:00Z\n',
        'SEED_FILES.json': '{}',
        'bridge/requirements.txt': '',
        'vendor/hermes/hermes_cli/web_dist/index.html': 'bundled',
        'vendor/odysseus/data/user.txt': 'seed content',
        'scripts/seed_registry.py': '',
        'data/models.json': '{"models": []}',
        'data/nav.json': '{}',
        'data/.env.local': 'bundled secret',
    }.items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    _archive(seed, res / 'motdeck-seed-fat.tar.gz')
    pyroot = tmp_path / 'python'
    (pyroot / 'bin').mkdir(parents=True)
    binary = pyroot / 'bin/python3'
    binary.write_text(PYTHON_STUB.format(python=Path(sys.executable).resolve()))
    binary.chmod(0o755)
    _archive(pyroot, res / 'python-standalone.tar.gz')
    for rel, body in (existing or {}).items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    calls = tmp_path / 'calls.jsonl'
    result = subprocess.run(['bash', str(ROOT / 'scripts/firstrun_fat.sh'), str(res), str(dest)],
                            env=dict(os.environ, SETUP_CALLS=str(calls)),
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return dest, [json.loads(line) for line in calls.read_text().splitlines()]


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS offline provisioner')
def test_fat_retry_preserves_existing_runtime_state(tmp_path):
    existing = {
        'motdeck.yaml': 'components:\n  hermes:\n    installed: true\nrunner:\n  model: my-selected-model\n',
        'data/models.json': '{"models": [{"id":"mine"}]}',
        'data/nav.json': '{"theme":"luxury-gold"}',
        'data/.env.local': 'my protected credentials',
        'vendor/odysseus/data/user.txt': 'my conversation',
        '.seed_stamp': 'original seed receipt',
        '.seed_files.json': 'original ownership receipt',
    }
    dest, _ = _fat_run(tmp_path, existing)
    assert {rel: (dest / rel).read_text() for rel in existing} == existing
    assert (dest / 'bridge/requirements.txt').is_file()
    assert (dest / '.provisioned').is_file()


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS offline provisioner')
def test_fat_installs_all_existing_mlx_engines_at_their_pins(tmp_path):
    _, calls = _fat_run(tmp_path)
    installed = {arg for call in calls if call[:3] == ['-m', 'pip', 'install'] for arg in call}
    assert {'mlx-lm==1.1', 'mlx-vlm==2.2', 'mlx-audio==3.3', 'mlx-whisper==4.4'} <= installed


def test_searx_reinstall_preserves_settings(tmp_path):
    (tmp_path / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/install_searxng.sh', tmp_path / 'scripts')
    (tmp_path / 'motdeck.yaml').write_text('components:\n  searxng:\n    repo: https://github.com/searxng/searxng.git\n    pin: ' + 'a' * 40 + '\n')
    (tmp_path / 'vendor/searxng/.git').mkdir(parents=True)
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name, body in {
        'git': '#!/bin/bash\nif [[ "$*" == *get-url* ]]; then echo https://github.com/searxng/searxng.git; else echo ' + 'a' * 40 + '; fi\n',
        'uv': '#!/bin/bash\nexit 0\n',
        'python3.13': '#!/bin/bash\nexit 0\n',
        'python3': '#!/bin/bash\necho generated-test-secret\n',
    }.items():
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    venv = tmp_path / 'data/searxng-venv/bin'
    venv.mkdir(parents=True)
    (venv / 'activate').write_text('deactivate() { :; }\n')
    (venv / 'pip').write_text('#!/bin/bash\nexit 0\n')
    (venv / 'pip').chmod(0o755)
    settings = tmp_path / 'data/searxng/settings.yml'
    settings.parent.mkdir()
    original = 'server:\n  secret_key: keep-this\nengines:\n  - name: custom-engine\n'
    settings.write_text(original)
    result = subprocess.run(['bash', str(tmp_path / 'scripts/install_searxng.sh')],
                            env=dict(os.environ, PATH=str(bindir) + ':/usr/bin:/bin'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert settings.read_text() == original


def test_goose_ui_fresh_install_reaches_download(tmp_path):
    (tmp_path / 'scripts').mkdir()
    shutil.copy2(ROOT / 'scripts/install_goose_ui.sh', tmp_path / 'scripts')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    for name, body in {
        'curl': '#!/bin/bash\necho download-was-attempted\nexit 42\n',
        'df': '#!/bin/bash\necho header\necho "disk 1 1 10485760"\n',
    }.items():
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    destination = tmp_path / 'new-install/goose'
    result = subprocess.run(['bash', str(tmp_path / 'scripts/install_goose_ui.sh')],
                            env=dict(os.environ, PATH=str(bindir) + ':/usr/bin:/bin',
                                     GOOSE_UI_DEST=str(destination)),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'download-was-attempted' in result.stdout + result.stderr
    assert 'another install is already running' not in result.stdout + result.stderr
    assert not (destination / '.ui-install').exists()
