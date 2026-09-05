"""Executable transaction journeys for Hermes WhatsApp enablement."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "mot_whatsapp_state", ROOT / "scripts" / "reconcile_hermes_whatsapp.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def test_start_reconciles_only_after_the_prior_owned_hermes_is_stopped():
    shell = (ROOT / "scripts" / "start_component.sh").read_text()
    arm = shell.split("  hermes)", 1)[1]
    stop_at = arm.index('_clear_port "$PORT" hermes force')
    reconcile_at = arm.index('scripts/reconcile_hermes_whatsapp.py')
    assert stop_at < reconcile_at, \
        "Hermes itself can write config.yaml; reconciliation must run after quiescence"


def write(home: Path, config: str, env: str) -> None:
    home.mkdir()
    (home / "config.yaml").write_text(config)
    (home / ".env").write_text(env)


def test_recovery_never_guesses_which_unjournaled_authority_is_newer(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: false\n",
          "WHATSAPP_ENABLED=true\nWHATSAPP_MODE=bot\nTOKEN=keep-me\n")

    before = ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes())
    result = module.recover(home)

    assert result == {"ok": True, "changed": False, "recovery_pending": False}
    assert ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes()) == before
    assert module.status(home)["aligned"] is False


def test_explicit_disable_changes_both_authorities_and_preserves_credentials(tmp_path):
    home = tmp_path / "hermes"
    write(home, "model:\n  default: local\nplatforms:\n  whatsapp:\n    enabled: true\n",
          "# credentials stay\nWHATSAPP_ENABLED=true\nWHATSAPP_ALLOWED_USERS=123\n")

    module.reconcile(home, False)

    state = module.status(home)
    assert state["config_enabled"] is False and state["env_enabled"] is False
    assert "default: local" in (home / "config.yaml").read_text()
    env = (home / ".env").read_text()
    assert "# credentials stay" in env and "WHATSAPP_ALLOWED_USERS=123" in env


def test_explicit_disable_preserves_yaml_comments_order_quotes_and_unicode(tmp_path):
    home = tmp_path / "hermes"
    write(home,
          "# user's header\nmodel:\n  default: 'local/model'  # keep quote\n"
          "platforms:\n  whatsapp:\n    # keep this explanation\n"
          "    enabled: true\ndisplay:\n  personality: '猫'\n",
          "WHATSAPP_ENABLED=true\n")

    module.reconcile(home, False)

    text = (home / "config.yaml").read_text()
    assert "# user's header" in text and "# keep quote" in text
    assert "# keep this explanation" in text
    assert "default: 'local/model'" in text and "personality: '猫'" in text
    assert text.index("model:") < text.index("platforms:") < text.index("display:")


def test_recovery_does_not_promote_legacy_env_only_state(tmp_path):
    home = tmp_path / "hermes"
    write(home, "model:\n  default: local\n", "WHATSAPP_ENABLED=true\n")

    before = ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes())
    module.recover(home)

    assert ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes()) == before
    assert module.status(home)["config_enabled"] is None


def test_duplicate_env_keys_collapse_to_one_canonical_value(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: true\n",
          "WHATSAPP_ENABLED=false\nA=1\nWHATSAPP_ENABLED=true\n")
    module.reconcile(home, False)
    env = (home / ".env").read_text()
    assert env.count("WHATSAPP_ENABLED=") == 1
    assert "A=1" in env


def test_failure_after_first_file_restores_both_originals(tmp_path):
    home = tmp_path / "hermes"
    config = "platforms:\n  whatsapp:\n    enabled: true\n"
    env = "WHATSAPP_ENABLED=true\nKEEP=1\n"
    write(home, config, env)
    real = module._atomic_write
    failed = False

    def fail_once(path, payload, mode):
        nonlocal failed
        if path.name == ".env" and not failed:
            failed = True
            raise OSError("injected env replacement failure")
        return real(path, payload, mode)

    try:
        module.reconcile(home, False, writer=fail_once)
    except OSError as exc:
        assert "injected" in str(exc)
    else:
        raise AssertionError("injected write failure did not escape")
    assert (home / "config.yaml").read_text() == config
    assert (home / ".env").read_text() == env
    assert not (home / module.JOURNAL).exists()


def test_crash_journal_rolls_forward_on_next_start(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: true\n", "WHATSAPP_ENABLED=true\n")
    (home / module.JOURNAL).write_text(json.dumps({"version": 1, "enabled": False}))

    result = module.recover(home)

    assert result["enabled"] is False
    assert module.status(home)["aligned"] is True
    assert module.status(home)["config_enabled"] is False


def test_failed_roll_forward_retains_journal_and_retries_same_intent(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: false\n", "WHATSAPP_ENABLED=true\n")
    journal = home / module.JOURNAL
    journal.write_text(json.dumps({"version": 1, "enabled": False}))
    real = module._atomic_write

    def fail_env(path, payload, mode):
        if path.name == ".env":
            raise OSError("injected recovery failure")
        return real(path, payload, mode)

    with pytest.raises(OSError, match="injected recovery failure"):
        module.recover(home, writer=fail_env)
    assert json.loads(journal.read_text()) == {"version": 1, "enabled": False}
    assert module.status(home)["recovery_pending"] is True

    result = module.recover(home)
    assert result["enabled"] is False
    assert module.status(home)["aligned"] is True
    assert not journal.exists()


def test_aligned_state_is_byte_and_mtime_stable(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: false\n",
          "WHATSAPP_ENABLED=false\nKEEP=1\n")
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (home / "config.yaml", home / ".env")]
    assert module.reconcile(home, False)["changed"] is False
    after = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (home / "config.yaml", home / ".env")]
    assert after == before


def test_pairing_session_files_are_outside_the_transaction(tmp_path):
    home = tmp_path / "hermes"
    write(home, "platforms:\n  whatsapp:\n    enabled: true\n", "WHATSAPP_ENABLED=true\n")
    session = home / "whatsapp" / "session"
    session.mkdir(parents=True)
    creds = session / "creds.json"
    creds.write_text('{"private":"keep"}')
    module.reconcile(home, False)
    assert creds.read_text() == '{"private":"keep"}'


@pytest.mark.parametrize("name", ["config.yaml", ".env", module.JOURNAL])
def test_state_files_must_be_regular_and_never_follow_symlinks(tmp_path, name):
    home = tmp_path / "hermes"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("WHATSAPP_ENABLED=true\n")
    (home / name).symlink_to(outside)

    with pytest.raises((OSError, ValueError)):
        module.status(home) if name != module.JOURNAL else module.recover(home)
    assert outside.read_text() == "WHATSAPP_ENABLED=true\n"


def test_lock_file_symlink_is_refused_without_touching_target(tmp_path):
    home = tmp_path / "hermes"
    home.mkdir()
    outside = tmp_path / "outside-lock"
    outside.write_text("keep")
    (home / module.LOCK).symlink_to(outside)
    with pytest.raises(OSError):
        module.status(home)
    assert outside.read_text() == "keep"


@pytest.mark.parametrize("config", [
    "platforms:\n  whatsapp:\n    enabled: true\nplatforms:\n  whatsapp:\n    enabled: false\n",
    "platforms:\n  whatsapp:\n    enabled: true\n  whatsapp:\n    enabled: false\n",
    "platforms:\n  whatsapp:\n    enabled: true\n    enabled: false\n",
])
def test_ambiguous_duplicate_yaml_shapes_are_refused_without_writes(tmp_path, config):
    home = tmp_path / "hermes"
    write(home, config, "WHATSAPP_ENABLED=true\n")
    before = ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes())
    with pytest.raises(ValueError):
        module.reconcile(home, False)
    assert ((home / "config.yaml").read_bytes(), (home / ".env").read_bytes()) == before
