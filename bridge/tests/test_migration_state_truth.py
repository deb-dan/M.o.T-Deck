"""Migration must preserve values and honor a fresh explicit action after recovery."""
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts import migrate_motdeck_identity as identity
from scripts import reconcile_hermes_whatsapp as whatsapp

ROOT = Path(__file__).resolve().parents[2]


def test_secret_identity_migration_changes_keys_only(tmp_path):
    path = tmp_path / '.env.local'
    original = (b'# MOT_RUNNER_API_KEY is a historical comment\n'
                b'MOT_RUNNER_API_KEY="value-containing-MOT_AUX_API_KEY"\n'
                b'MOT_AUX_API_KEY="unchanged"\n'
                b'export MOT_RUNNER_API_KEY_B64=c2VjcmV0\n'
                b'MOT_AUX_API_KEY_B64=YXV4\n'
                b'MOT_RUNNER_API_KEY_CUSTOM="leave this name alone"\n')
    path.write_bytes(original)
    identity._rewrite_tokens(path, identity.SECRET_KEY_MIGRATIONS, [])
    assert path.read_bytes() == (b'# MOT_RUNNER_API_KEY is a historical comment\n'
                                 b'MOT_DECK_RUNNER_API_KEY="value-containing-MOT_AUX_API_KEY"\n'
                                 b'MOT_DECK_AUX_API_KEY="unchanged"\n'
                                 b'export MOT_DECK_RUNNER_API_KEY_B64=c2VjcmV0\n'
                                 b'MOT_DECK_AUX_API_KEY_B64=YXV4\n'
                                 b'MOT_RUNNER_API_KEY_CUSTOM="leave this name alone"\n')


def test_whatsapp_new_action_runs_after_pending_recovery(tmp_path):
    (tmp_path / 'config.yaml').write_text('platforms:\n  whatsapp:\n    enabled: false\n')
    (tmp_path / '.env').write_text('WHATSAPP_ENABLED=true\n')
    (tmp_path / whatsapp.JOURNAL).write_text(json.dumps({'version': 1, 'enabled': False}))
    result = whatsapp.reconcile(tmp_path, True)
    assert result['enabled'] is True
    assert whatsapp.status(tmp_path)['config_enabled'] is True
    assert whatsapp.status(tmp_path)['env_enabled'] is True
    assert not (tmp_path / whatsapp.JOURNAL).exists()


def test_secret_migration_cli_does_not_echo_invalid_yaml(tmp_path):
    credential = 'private-test-credential-do-not-print'
    (tmp_path / 'motdeck.yaml').write_text('runner:\n  api_key: [' + credential + '\n')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/migrate_local_secrets.py'),
                             'plan', str(tmp_path)], env=dict(os.environ, PYTHONPATH=str(ROOT)),
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert credential not in result.stdout + result.stderr
