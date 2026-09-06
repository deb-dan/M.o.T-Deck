"""U71: generated local credentials, one secured overlay, no tracked defaults."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

import pytest
import yaml

from bridge.core import localsecrets


ROOT = Path(__file__).resolve().parents[2]


def manifest(root: Path, runner="", aux="", user="", password="") -> None:
    (root / "motdeck.yaml").write_text(yaml.safe_dump({
        "runner": {"api_key": runner}, "aux": {"api_key": aux},
        "components": {"odysseus": {"admin_user": user,
                                       "admin_password": password}},
    }))


def test_fresh_install_generates_every_value_and_overlays_without_yaml_secret(tmp_path):
    manifest(tmp_path, "motdeck-local", "motdeck-aux", "admin", "admin123")
    values = localsecrets.ensure(tmp_path, fresh=True)
    assert set(values) == set(localsecrets.SECRET_PATHS.values())
    assert all(values[key] != weak for key, weak in localsecrets.WEAK_DEFAULTS.items())
    assert len(values["MOT_DECK_RUNNER_API_KEY"]) >= 40
    store = tmp_path / "data" / ".env.local"
    assert stat.S_IMODE(store.stat().st_mode) == 0o600
    config = yaml.safe_load((tmp_path / "motdeck.yaml").read_text())
    localsecrets.overlay_config(config, tmp_path)
    assert config["runner"]["api_key"] == values["MOT_DECK_RUNNER_API_KEY"]
    assert config["components"]["odysseus"]["admin_password"] \
        == values["MOT_DECK_ODYSSEUS_ADMIN_PASSWORD"]


def test_nonfresh_staging_preserves_custom_values_until_live_migration(tmp_path):
    manifest(tmp_path, "my.runner!$key", "my aux:#key", "debi", "long$password!")
    values = localsecrets.ensure(tmp_path)
    assert values == {
        "MOT_DECK_RUNNER_API_KEY": "my.runner!$key",
        "MOT_DECK_AUX_API_KEY": "my aux:#key",
        "MOT_DECK_ODYSSEUS_ADMIN_USER": "debi",
        "MOT_DECK_ODYSSEUS_ADMIN_PASSWORD": "long$password!",
    }
    assert "my.runner" not in (tmp_path / "data" / ".env.local").read_text()


def test_partial_store_is_never_overlaid(tmp_path):
    manifest(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    store = data / ".env.local"
    store.write_text("MOT_DECK_RUNNER_API_KEY_B64=YWJj\n")
    store.chmod(0o600)
    with pytest.raises(ValueError, match="incomplete"):
        localsecrets.read(tmp_path)
    with pytest.raises(ValueError, match="incomplete"):
        localsecrets.overlay_config({"runner": {}}, tmp_path)


def test_manifest_scrub_preserves_every_unrelated_byte_and_comments(tmp_path):
    text = """# exact header
runner:
  api_key: 'a:# secret'  # keep runner comment
  model: untouched
aux:
  api_key: aux-secret
components:
  odysseus:
    admin_user: admin # keep user comment
    admin_password: \"p#word\"
  hermes:
    installed: true
"""
    (tmp_path / "motdeck.yaml").write_text(text)
    localsecrets.scrub_manifest(tmp_path)
    after = (tmp_path / "motdeck.yaml").read_text()
    expected = text.replace("'a:# secret'", "").replace("aux-secret", "") \
        .replace("admin #", " #").replace('"p#word"', "")
    assert after == expected
    assert localsecrets.manifest_secret_values(tmp_path) == {
        key: "" for key in localsecrets.SECRET_PATHS.values()
    }


def test_insecure_or_symlink_store_is_refused(tmp_path):
    manifest(tmp_path)
    localsecrets.ensure(tmp_path, fresh=True)
    store = tmp_path / "data" / ".env.local"
    store.chmod(0o644)
    with pytest.raises(PermissionError, match="0600"):
        localsecrets.read(tmp_path)
    store.unlink()
    outside = tmp_path / "outside"
    outside.write_text("MOT_DECK_RUNNER_API_KEY=do-not-read\n")
    store.symlink_to(outside)
    with pytest.raises(OSError):
        localsecrets.read(tmp_path)


def test_failed_replace_preserves_existing_secret_file(tmp_path, monkeypatch):
    manifest(tmp_path)
    original = localsecrets.ensure(tmp_path, fresh=True)
    before = (tmp_path / "data" / ".env.local").read_bytes()
    monkeypatch.setattr(localsecrets.os, "replace",
                        lambda *_: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        localsecrets.write(tmp_path, localsecrets.generate())
    assert (tmp_path / "data" / ".env.local").read_bytes() == before
    assert localsecrets.read(tmp_path) == original
    assert not list((tmp_path / "data").glob(".env-local-*.tmp"))


def test_repo_and_production_code_carry_no_weak_secret_literal():
    manifest_text = (ROOT / "motdeck.yaml").read_text()
    production = "\n".join(path.read_text(errors="replace") for base in
        (ROOT / "bridge", ROOT / "scripts") for path in base.rglob("*")
        if path.suffix in (".py", ".sh")
        and not any(part.endswith("tests") for part in path.parts)
        and path.name != "localsecrets.py")
    for weak in ("motdeck-local", "motdeck-aux", "admin123"):
        assert weak not in manifest_text
        assert weak not in production


def test_reader_never_reports_a_value_on_parse_error(tmp_path):
    manifest(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    secret = "NeverPrintThisSecret"
    store = data / ".env.local"
    store.write_text("MOT_DECK_RUNNER_API_KEY=" + secret + "!\n")
    store.chmod(0o600)
    with pytest.raises(ValueError) as error:
        localsecrets.read(tmp_path)
    assert secret not in str(error.value)


def test_odysseus_installer_seeds_runner_through_the_secret_overlay():
    source = (ROOT / "scripts" / "install_component.sh").read_text()
    arm = source.split('else\n  uv venv "data/odysseus-venv"', 1)[1].split(
        '# flip installed: true', 1)[0]
    assert re.search(r'read_manifest\.py"\s+\\?\s*"\$ROOT" runner\.endpoint str', arm)
    assert re.search(r'read_manifest\.py"\s+\\?\s*"\$ROOT" runner\.api_key str', arm)
    assert 'JAN_BASE_URL="$RUNNER_ENDPOINT" JAN_API_KEY="$RUNNER_KEY"' in arm
    assert 'runner.api_key is not provisioned; Odysseus was not seeded' in arm
    assert 'JAN_API_KEY="motdeck-local"' not in arm


def test_runner_secret_never_appears_in_process_argv():
    source = (ROOT / "scripts" / "start_component.sh").read_text()
    assert 'ARGS+=(--api-key "$R_KEY")' not in source
    assert 'ARGS+=(--api-key-file "$LAUNCH_KEYFILE")' in source
    assert 'LAUNCH_KEYFILE="$ROOT_ABS/data/.runner-api.keys"' in source
