import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.migrate_motdeck_identity import MigrationError, migrate
from scripts.sync_snapshot_identity import SyncError, sync


ROOT = Path(__file__).resolve().parents[2]


OLD = "/Users/example/Library/Application Support/Harness"
NEW = "/Users/example/Library/Application Support/MOT Deck"


def _old_root(tmp_path: Path) -> Path:
    root = tmp_path / "Library/Application Support/Harness"
    root.mkdir(parents=True)
    (root / "harness.yaml").write_text("runner:\n  binary:\n")
    (root / "harness.yaml.bak-1").write_text("live backup\n")
    return root


def test_live_root_manifest_generated_paths_and_webkit_move_together(tmp_path):
    old = _old_root(tmp_path)
    new = old.with_name("MOT Deck")
    actual_old = str(old)
    actual_new = str(new)

    models = old / "data/models.json"
    models.parent.mkdir()
    models.write_text('{"path": "' + actual_old + '/data/models/x"}\n')
    secret_store = old / "data/.env.local"
    secret_store.write_text("MOT_RUNNER_API_KEY_B64=c2VjcmV0\nMOT_AUX_API_KEY_B64=YXV4\n")
    secret_store.chmod(0o600)
    nested = old / "data/unsloth-home/unsloth_studio"
    (nested / "bin").mkdir(parents=True)
    (nested / "pyvenv.cfg").write_text("home = " + actual_old + "/data/python-standalone/bin\n")
    launcher = nested / "bin/unsloth"
    launcher.write_text("#!/bin/sh\n'''exec' \"" + actual_old +
                        "/data/unsloth-home/unsloth_studio/bin/python\" \"$0\" \"$@\"\n")
    python_link = nested / "bin/python"
    python_link.symlink_to(actual_old + "/data/python-standalone/bin/python3")
    site = nested / "lib/python3.12/site-packages"
    site.mkdir(parents=True)
    (site / "editable-source.pth").write_text(actual_old + "/vendor/unsloth\n")
    untouched_log = old / "data/logs/history.log"
    untouched_log.parent.mkdir()
    untouched_log.write_text("historical " + actual_old)

    webkit = tmp_path / "Library/WebKit/local.harness.app"
    webkit.mkdir(parents=True)
    (webkit / "state").write_text("preserved")

    result = migrate(old, new, tmp_path)
    assert result["status"] == "migrated"
    assert not old.exists()
    assert (new / "motdeck.yaml").is_file()
    assert (new / "motdeck.yaml.bak-1").read_text() == "live backup\n"
    assert actual_new in (new / "data/models.json").read_text()
    migrated_secrets = (new / "data/.env.local").read_text()
    assert "MOT_DECK_RUNNER_API_KEY_B64=c2VjcmV0" in migrated_secrets
    assert "MOT_DECK_AUX_API_KEY_B64=YXV4" in migrated_secrets
    assert "MOT_RUNNER_API_KEY" not in migrated_secrets
    assert (new / "data/.env.local").stat().st_mode & 0o777 == 0o600
    assert actual_new in (new / "data/unsloth-home/unsloth_studio/bin/unsloth").read_text()
    assert actual_new in (new / "data/unsloth-home/unsloth_studio/pyvenv.cfg").read_text()
    assert actual_new in (new / "data/unsloth-home/unsloth_studio/bin/python").readlink().as_posix()
    assert (new / "data/unsloth-home/unsloth_studio/lib/python3.12/site-packages/editable-source.pth").read_text() == actual_new + "/vendor/unsloth\n"
    assert actual_old in (new / "data/logs/history.log").read_text(), "history is evidence, not active config"
    assert (tmp_path / "Library/WebKit/local.motdeck.app/state").read_text() == "preserved"


def test_both_roots_or_both_webkit_domains_refuse_without_mutation(tmp_path):
    old = _old_root(tmp_path)
    new = old.with_name("MOT Deck")
    new.mkdir()
    with pytest.raises(MigrationError, match="both old and new live roots"):
        migrate(old, new, tmp_path)
    assert old.is_dir() and new.is_dir()

    new.rmdir()
    (tmp_path / "Library/WebKit/local.harness.app").mkdir(parents=True)
    (tmp_path / "Library/WebKit/local.motdeck.app").mkdir(parents=True)
    with pytest.raises(MigrationError, match="both old and new WebKit"):
        migrate(old, new, tmp_path)
    assert old.is_dir() and not new.exists()


def test_symlink_root_refuses_and_an_already_migrated_root_is_idempotent(tmp_path):
    real = _old_root(tmp_path)
    alias = tmp_path / "old-link"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(MigrationError, match="direct directory"):
        migrate(alias, tmp_path / "new-link-target", tmp_path)

    new = real.with_name("MOT Deck")
    real.rename(new)
    (new / "harness.yaml").rename(new / "motdeck.yaml")
    result = migrate(real, new, tmp_path)
    assert result == {"status": "already-migrated", "rewritten": 0,
                      "retargeted_links": 0, "state_dirs": 0}


def test_unrelated_content_and_external_model_paths_are_not_rewritten(tmp_path):
    old = _old_root(tmp_path)
    new = old.with_name("MOT Deck")
    models = old / "data/models.json"
    models.parent.mkdir()
    models.write_text('{"path":"/Volumes/Models/model.gguf","note":"' + OLD + ' is prose"}')
    user = old / "data/user-note.txt"
    user.write_text(OLD)
    migrate(old, new, tmp_path)
    assert "/Volumes/Models/model.gguf" in (new / "data/models.json").read_text()
    assert (new / "data/user-note.txt").read_text() == OLD


def test_mid_migration_manifest_collision_rolls_the_root_and_names_back(tmp_path):
    old = _old_root(tmp_path)
    new = old.with_name("MOT Deck")
    (old / "motdeck.yaml.bak-1").write_text("collision\n")
    with pytest.raises(MigrationError, match="rolled back"):
        migrate(old, new, tmp_path)
    assert old.is_dir() and not new.exists()
    assert (old / "harness.yaml").is_file()
    assert (old / "harness.yaml.bak-1").read_text() == "live backup\n"


def _run_path_guard_seed(tmp_path: Path, config_text: str,
                         retired_name: str = "harness-path-guard"):
    start = (ROOT / "scripts/start_component.sh").read_text()
    match = re.search(r"<<'PYGUARD'\n([\s\S]*?)\nPYGUARD\n", start)
    assert match, "Hermes path-guard seed program is missing"
    home = tmp_path / "hermes"
    retired = home / "plugins/harness-path-guard"
    retired.mkdir(parents=True)
    (retired / "plugin.yaml").write_text(
        f"name: {retired_name}\nversion: 0.1.0\n")
    (retired / "generated-copy.txt").write_text("generated")
    config = home / "config.yaml"
    config.write_text(config_text)
    destination = home / "plugins/motdeck-path-guard"
    env = dict(os.environ, HGUARD_SRC=str(ROOT / "guards/motdeck-path-guard"),
               HGUARD_DST=str(destination), MOT_DECK_ROOT=str(ROOT), HCFG=str(config))
    result = subprocess.run([sys.executable, "-c", match.group(1)], env=env,
                            capture_output=True, text=True, timeout=30)
    return result, config, retired, destination


def test_hermes_guard_identity_replaces_duplicate_hook_and_retires_owned_copy(tmp_path):
    original = {
        "plugins": {
            "enabled": ["user-neighbour", "harness-path-guard",
                        "motdeck-path-guard", "harness-path-guard"],
            "disabled": ["harness-path-guard", "motdeck-path-guard", "other"],
        },
        "unrelated": {"preserved": True},
    }
    result, config, retired, destination = _run_path_guard_seed(
        tmp_path, yaml.safe_dump(original, sort_keys=False))
    assert result.returncode == 0, result.stderr
    migrated = yaml.safe_load(config.read_text())
    assert migrated["plugins"]["enabled"] == ["user-neighbour", "motdeck-path-guard"]
    assert migrated["plugins"]["disabled"] == ["other"]
    assert migrated["unrelated"] == original["unrelated"]
    assert not retired.exists()
    assert (destination / "plugin.yaml").is_file()
    assert "retired old plugin id and generated directory" in result.stdout


def test_hermes_guard_identity_never_deletes_a_foreign_lookalike(tmp_path):
    original = {"plugins": {"enabled": ["harness-path-guard"]}}
    result, config, retired, _destination = _run_path_guard_seed(
        tmp_path, yaml.safe_dump(original), retired_name="some-user-plugin")
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(config.read_text())["plugins"]["enabled"] == [
        "motdeck-path-guard"]
    assert retired.is_dir()
    assert "not a verified MOT Deck-owned plugin" in result.stdout


def _identity_sync_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    snapshot = tmp_path / "snapshot"
    for root in (repo, snapshot):
        for directory in ("app", "docs", "skills"):
            (root / directory).mkdir(parents=True, exist_ok=True)
    owned = {
        "README.md": "current readme\n",
        "CLAUDE.md": "current doctrine\n",
        "skills/README.md": "current skills guide\n",
        "app/main.swift": "// current shell\n",
        "app/make_icon.swift": "// current icon maker\n",
        "app/MOTDeck.icns": "current icon bytes\n",
    }
    for relative, payload in owned.items():
        (repo / relative).write_text(payload)
        (snapshot / relative).write_text("stale\n")
    replacements = {
        "docs/MOT-DECK-INTERNALS.md": "current internals\n",
        "docs/mot-deck-architecture.md": "current architecture\n",
    }
    for relative, payload in replacements.items():
        (repo / relative).write_text(payload)
        (snapshot / relative).write_text(payload)
    for relative in ("app/Harness.icns", "docs/HARNESS-INTERNALS.md",
                     "docs/harness-architecture.md"):
        (snapshot / relative).write_text("retired\n")
    (snapshot / "skills/user-created-skill.md").write_text("user material\n")
    (snapshot / "docs/handoff-history.md").write_text("forensic history\n")
    return repo, snapshot


def test_snapshot_identity_sync_is_allowlisted_and_retires_only_exact_names(tmp_path):
    repo, snapshot = _identity_sync_fixture(tmp_path)
    result = sync(repo, snapshot)
    assert len(result["copied"]) == 6
    assert set(result["retired"]) == {
        "app/Harness.icns", "docs/HARNESS-INTERNALS.md",
        "docs/harness-architecture.md",
    }
    assert (snapshot / "app/main.swift").read_text() == "// current shell\n"
    assert (snapshot / "skills/README.md").read_text() == "current skills guide\n"
    assert (snapshot / "skills/user-created-skill.md").read_text() == "user material\n"
    assert (snapshot / "docs/handoff-history.md").read_text() == "forensic history\n"


def test_snapshot_identity_sync_refuses_symlink_and_keeps_retired_name(tmp_path):
    repo, snapshot = _identity_sync_fixture(tmp_path)
    target = snapshot / "outside"
    target.write_text("outside\n")
    destination = snapshot / "app/main.swift"
    destination.unlink()
    destination.symlink_to(target)
    with pytest.raises(SyncError, match="direct regular file"):
        sync(repo, snapshot)
    assert destination.is_symlink()
    assert (snapshot / "app/Harness.icns").is_file()
    assert target.read_text() == "outside\n"


def test_snapshot_identity_sync_retires_only_verified_generated_guard(tmp_path):
    repo, snapshot = _identity_sync_fixture(tmp_path)
    old = snapshot / "guards/harness-path-guard"
    current = snapshot / "guards/motdeck-path-guard"
    for path, name in ((old, "harness-path-guard"),
                       (current, "motdeck-path-guard")):
        path.mkdir(parents=True)
        (path / "plugin.yaml").write_text(f"name: {name}\n")
        for filename in ("README.md", "__init__.py", "policy.yaml"):
            (path / filename).write_text("managed\n")
    cache = old / "__pycache__"
    cache.mkdir()
    (cache / "__init__.cpython-311.pyc").write_bytes(b"generated")
    result = sync(repo, snapshot)
    assert "guards/harness-path-guard" in result["retired"]
    assert not old.exists()
    assert current.is_dir()


def test_snapshot_identity_sync_preserves_guard_with_foreign_neighbor(tmp_path):
    repo, snapshot = _identity_sync_fixture(tmp_path)
    old = snapshot / "guards/harness-path-guard"
    current = snapshot / "guards/motdeck-path-guard"
    old.mkdir(parents=True)
    current.mkdir(parents=True)
    (old / "plugin.yaml").write_text("name: harness-path-guard\n")
    (old / "user-note.txt").write_text("not ours\n")
    (current / "plugin.yaml").write_text("name: motdeck-path-guard\n")
    result = sync(repo, snapshot)
    assert old.is_dir()
    assert result["preserved"] and "user-note.txt" in result["preserved"][0]
