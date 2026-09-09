"""U71 existing-install cutover: redacted, resumable, and fail-closed."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
import yaml

from bridge.core import localsecrets
from scripts import migrate_local_secrets as migration


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


class AuthState:
    def __init__(self, password="admin123", fail_change=False):
        self.user = "admin"
        self.password = password
        self.fail_change = fail_change


def clients(state: AuthState):
    class Client:
        def __init__(self, **_kwargs):
            self.authed = False

        def post(self, path, json):
            if path.endswith("/login"):
                ok = json["username"] == state.user and json["password"] == state.password
                self.authed = ok
                return Response(200, {"ok": True}) if ok else Response(401, {})
            if path.endswith("/change-password"):
                if state.fail_change:
                    return Response(500, {})
                if not self.authed or json["current_password"] != state.password:
                    return Response(400, {})
                state.password = json["new_password"]
                return Response(200, {"ok": True})
            raise AssertionError(path)

        def close(self):
            pass
    return Client


def make_manifest(root: Path, *, installed=True):
    (root / "motdeck.yaml").write_text(yaml.safe_dump({
        "runner": {"api_key": "motdeck-local", "model": "m"},
        "aux": {"api_key": "motdeck-aux"},
        "components": {"odysseus": {
            "installed": installed, "port": 7860,
            "admin_user": "admin", "admin_password": "admin123",
        }, "hermes": {"installed": True}},
    }, sort_keys=False))


def generated():
    return {
        "MOT_DECK_RUNNER_API_KEY": "runner.new!$key",
        "MOT_DECK_AUX_API_KEY": "aux new:#key",
        "MOT_DECK_ODYSSEUS_ADMIN_USER": "generated-user",
        "MOT_DECK_ODYSSEUS_ADMIN_PASSWORD": "new$password!",
    }


def test_rotating_existing_install_verifies_odysseus_then_scrubs(monkeypatch, tmp_path):
    make_manifest(tmp_path)
    monkeypatch.setattr(localsecrets, "generate", generated)
    state = AuthState()
    result = migration.apply_migration(tmp_path, rotate=True,
                                       client_factory=clients(state))
    assert result["ok"] is True
    assert state.password == "new$password!"
    stored = localsecrets.read(tmp_path)
    assert stored["MOT_DECK_RUNNER_API_KEY"] == "runner.new!$key"
    # Aux has a user-owned Odysseus Background Tasks consumer.  Migration moves its
    # key into the protected store but cannot rotate it without a managed endpoint
    # transaction that proves the dependent setting was changed too.
    assert stored["MOT_DECK_AUX_API_KEY"] == "motdeck-aux"
    assert stored["MOT_DECK_ODYSSEUS_ADMIN_USER"] == "admin"
    assert result["credentials"] == "rotated-managed-secrets; aux-preserved"
    assert result["restart_required"] == ["runner", "odysseus", "hermes"]
    assert all(not value for value in localsecrets.manifest_secret_values(tmp_path).values())


def test_auth_cutover_failure_restores_yaml_owned_state(monkeypatch, tmp_path):
    make_manifest(tmp_path)
    before = (tmp_path / "motdeck.yaml").read_bytes()
    monkeypatch.setattr(localsecrets, "generate", generated)
    state = AuthState(fail_change=True)
    with pytest.raises(RuntimeError, match="password cutover"):
        migration.apply_migration(tmp_path, rotate=True,
                                   client_factory=clients(state))
    assert not (tmp_path / "data" / ".env.local").exists()
    assert (tmp_path / "motdeck.yaml").read_bytes() == before
    assert state.password == "admin123"


def test_uninstalled_odysseus_needs_no_network_and_custom_values_survive(tmp_path):
    make_manifest(tmp_path, installed=False)
    result = migration.apply_migration(tmp_path, rotate=False,
        client_factory=lambda **_: (_ for _ in ()).throw(AssertionError("network")))
    assert result["ok"] is True
    assert localsecrets.read(tmp_path)["MOT_DECK_RUNNER_API_KEY"] == "motdeck-local"
    assert all(not value for value in localsecrets.manifest_secret_values(tmp_path).values())


def test_plan_only_names_installed_managed_consumers(tmp_path):
    make_manifest(tmp_path, installed=False)
    data = yaml.safe_load((tmp_path / "motdeck.yaml").read_text())
    data["components"]["deepseek"] = {"installed": True}
    data["components"]["opencode"] = {"installed": False}
    (tmp_path / "motdeck.yaml").write_text(yaml.safe_dump(data, sort_keys=False))

    result = migration.plan(tmp_path, rotate=True)

    assert result["restart_required"] == ["runner", "deepseek", "hermes"]
    assert result["aux_key"].startswith("preserve-existing:")


def test_completed_migration_is_idempotent_and_recommends_no_restarts(
        monkeypatch, tmp_path):
    make_manifest(tmp_path)
    monkeypatch.setattr(localsecrets, "generate", generated)
    state = AuthState()
    first = migration.apply_migration(
        tmp_path, rotate=True, client_factory=clients(state))
    assert first["restart_required"] == ["runner", "odysseus", "hermes"]

    second_plan = migration.plan(tmp_path, rotate=True)
    assert second_plan["store"] == "already-provisioned"
    assert second_plan["yaml"] == "already-scrubbed"
    assert second_plan["rotate"] is False
    assert second_plan["aux_key"] == "already-provisioned"
    assert second_plan["restart_required"] == []

    second = migration.apply_migration(
        tmp_path, rotate=True, client_factory=clients(state))
    assert second["credentials"] == "preserved"
    assert second["aux_key"] == "already-provisioned"
    assert second["restart_required"] == []


def test_active_managed_rotation_preserves_aux_and_identity(monkeypatch, tmp_path):
    make_manifest(tmp_path)
    monkeypatch.setattr(localsecrets, "generate", generated)
    state = AuthState()
    migration.apply_migration(tmp_path, rotate=False,
                               client_factory=clients(state))
    before = localsecrets.read(tmp_path)
    assert before["MOT_DECK_AUX_API_KEY"] == "motdeck-aux"

    result = migration.apply_migration(
        tmp_path, rotate=False, rotate_active_managed=True,
        client_factory=clients(state))
    after = localsecrets.read(tmp_path)
    assert after["MOT_DECK_RUNNER_API_KEY"] == "runner.new!$key"
    assert after["MOT_DECK_ODYSSEUS_ADMIN_PASSWORD"] == "new$password!"
    assert after["MOT_DECK_AUX_API_KEY"] == before["MOT_DECK_AUX_API_KEY"]
    assert after["MOT_DECK_ODYSSEUS_ADMIN_USER"] == before["MOT_DECK_ODYSSEUS_ADMIN_USER"]
    assert result["credentials"] == "rotated-managed-secrets; aux-preserved"
    assert result["restart_required"] == ["runner", "odysseus", "hermes"]


def test_failed_active_rotation_restores_existing_store(monkeypatch, tmp_path):
    make_manifest(tmp_path)
    state = AuthState()
    migration.apply_migration(tmp_path, rotate=False,
                               client_factory=clients(state))
    before = localsecrets.read(tmp_path)
    monkeypatch.setattr(localsecrets, "generate", generated)
    state.fail_change = True
    with pytest.raises(RuntimeError, match="password cutover"):
        migration.apply_migration(
            tmp_path, rotate=False, rotate_active_managed=True,
            client_factory=clients(state))
    assert localsecrets.read(tmp_path) == before
    assert state.password == "admin123"


def test_operator_entrypoint_bootstraps_its_root_python():
    script = Path(migration.__file__).resolve()
    result = subprocess.run([str(script), "--help"], text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "--rotate-active-managed" in result.stdout
