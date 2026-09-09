"""Destructive model actions honor exact-process stop failures before mutation."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bridge.core import modeldelete
from bridge.routers import models


ROOT = Path(__file__).resolve().parents[2]


class _Request:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def test_eject_refusal_never_clears_the_pin(monkeypatch):
    writes = []
    monkeypatch.setattr(models, "cfg", lambda: {"runner": {"port": 6767, "model": "m"}})
    monkeypatch.setattr(models, "stop_owned_component",
                        lambda *args, **kwargs: ["unowned listener"])
    monkeypatch.setattr(models, "_set_runner_model", lambda value: writes.append(value))
    response = models.api_eject_model()
    assert response.status_code == 409
    assert writes == []


def test_delete_live_model_refusal_never_removes_files_or_registry(tmp_path, monkeypatch):
    root = tmp_path
    target = root / "data" / "models" / "owned" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"kept")
    entry = {"id": "m", "source": "local", "path": str(target), "format": "gguf"}
    monkeypatch.setattr(models, "ROOT", root)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "m"}, "aux": {"model": ""}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "m")
    monkeypatch.setattr(models, "_eject_runner",
                        lambda **_kwargs: ["unowned listener"])
    response = asyncio.run(models.api_delete_model(_Request({"id": "m"})))
    assert response.status_code == 409
    assert target.read_bytes() == b"kept"


def test_delete_aux_model_refusal_never_removes_files_or_clears_aux(tmp_path, monkeypatch):
    root = tmp_path
    target = root / "data" / "models" / "owned" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"kept")
    entry = {"id": "m", "source": "local", "path": str(target), "format": "gguf"}
    yaml_writes = []
    monkeypatch.setattr(models, "ROOT", root)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "other"},
        "aux": {"port": 6768, "model": "m"}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "other")
    monkeypatch.setattr(models, "_aux_kill", lambda _port: ["unowned aux listener"])
    monkeypatch.setattr(models, "_set_yaml_model",
                        lambda block, value: yaml_writes.append((block, value)))
    response = asyncio.run(models.api_delete_model(_Request({"id": "m"})))
    assert response.status_code == 409
    assert target.read_bytes() == b"kept"
    assert yaml_writes == []


def _write_registry(root, entries):
    path = root / "data" / "models.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": entries}))
    return path


def test_delete_failure_restores_artifact_registry_and_saved_pin(tmp_path, monkeypatch):
    target = tmp_path / "data" / "models" / "owned" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"kept")
    entry = {"id": "m", "source": "local", "path": str(target), "format": "gguf"}
    registry = _write_registry(tmp_path, [entry])
    pin_writes = []
    monkeypatch.setattr(models, "ROOT", tmp_path)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "m"}, "aux": {"model": ""}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "m")
    monkeypatch.setattr(models, "_eject_runner", lambda **_kwargs: [])
    monkeypatch.setattr(models, "_set_runner_model", lambda value: pin_writes.append(value))
    monkeypatch.setattr(models, "_voice", None)

    def fail_delete(_path):
        raise PermissionError("read-only child")

    monkeypatch.setattr(shutil, "rmtree", fail_delete)
    response = asyncio.run(models.api_delete_model(_Request({"id": "m"})))
    assert response.status_code == 500
    assert "revalidated before loading" in response.body.decode()
    assert target.read_bytes() == b"kept"
    assert json.loads(registry.read_text())["models"] == [entry]
    assert pin_writes == ["", "m"]
    assert list(target.parent.parent.glob(".deleting-*")) == []


def test_delete_refuses_shared_target_before_stopping_or_mutating(tmp_path, monkeypatch):
    target = tmp_path / "data" / "models" / "shared" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"kept")
    entry = {"id": "m", "source": "local", "path": str(target)}
    other = {"id": "other", "source": "lmstudio-import", "path": str(target.parent)}
    stops = []
    monkeypatch.setattr(models, "ROOT", tmp_path)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry, other])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "m"}, "aux": {"model": ""}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "m")
    monkeypatch.setattr(models, "_eject_runner", lambda **_kwargs: stops.append(True) or [])
    response = asyncio.run(models.api_delete_model(_Request({"id": "m"})))
    assert response.status_code == 409
    assert "other" in response.body.decode()
    assert target.read_bytes() == b"kept"
    assert stops == []


def test_delete_guard_refuses_symlinked_model_path(tmp_path):
    models_root = tmp_path / "data" / "models"
    real = models_root / "real"
    real.mkdir(parents=True)
    (real / "model.gguf").write_bytes(b"kept")
    (models_root / "alias").symlink_to(real, target_is_directory=True)
    target, reason = models._deletable_target(
        {"id": "m", "source": "local", "path": str(models_root / "alias" / "model.gguf")},
        str(models_root))
    assert target is None
    assert "symbolic link" in reason


def test_delete_exact_file_target_removes_bytes_and_registry_row(tmp_path, monkeypatch):
    target = tmp_path / "data" / "models" / "one.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"owned")
    entry = {"id": "m", "source": "download", "path": str(target), "format": "gguf"}
    registry = _write_registry(tmp_path, [entry])
    monkeypatch.setattr(models, "ROOT", tmp_path)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "other"}, "aux": {"model": ""}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "other")
    monkeypatch.setattr(models, "_voice", None)
    response = asyncio.run(models.api_delete_model(_Request({"id": "m"})))
    assert response.status_code == 200
    assert not target.exists()
    assert json.loads(registry.read_text())["models"] == []


def test_delete_routes_never_reach_the_repository_yaml_when_router_root_is_a_fixture(
        tmp_path, monkeypatch):
    """A router-root fixture is not enough if imported YAML writers retain appctx.ROOT.

    Exercise the successful assignment path with explicit writer doubles so a future
    deletion test cannot silently turn the repository's shipped model pin into its
    one-letter fixture id.
    """
    target = tmp_path / "data" / "models" / "owned" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"owned")
    entry = {"id": "fixture-model", "source": "local", "path": str(target),
             "format": "gguf"}
    _write_registry(tmp_path, [entry])
    writes = []
    monkeypatch.setattr(models, "ROOT", tmp_path)
    monkeypatch.setattr(models, "_registry_models", lambda: [entry])
    monkeypatch.setattr(models, "cfg", lambda: {
        "runner": {"port": 6767, "model": "fixture-model"}, "aux": {"model": ""}})
    monkeypatch.setattr(models, "_live_model_id", lambda _port: "fixture-model")
    monkeypatch.setattr(models, "_eject_runner", lambda **_kwargs: [])
    monkeypatch.setattr(models, "_set_runner_model", lambda value: writes.append(value))
    monkeypatch.setattr(models, "_voice", None)
    response = asyncio.run(models.api_delete_model(_Request({"id": "fixture-model"})))
    assert response.status_code == 200 and writes == [""]


@pytest.mark.parametrize("boundary", [
    "journal", "quarantine", "registry", "assignments", "cleanup",
])
def test_crash_at_each_delete_boundary_recovers_by_registry_commit_state(
        tmp_path, boundary):
    target = tmp_path / "data" / "models" / "owned" / "model.gguf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"owned")
    entry = {"id": "m", "source": "local", "path": str(target), "format": "gguf"}
    registry = _write_registry(tmp_path, [entry])
    assignment = tmp_path / "assignment"
    assignment.write_text("m")
    code = textwrap.dedent("""
        import os
        import sys
        from pathlib import Path
        from bridge.core import modeldelete

        root, boundary = Path(sys.argv[1]), sys.argv[2]
        target = root / "data" / "models" / "owned" / "model.gguf"
        assignment = root / "assignment"
        def clear(): assignment.write_text("")
        def restore(): assignment.write_text("m")
        def crash(stage):
            if stage == boundary:
                os._exit(71)
        result = modeldelete.delete_owned_model_transaction(
            root=root, mid="m", expected_target=str(target.parent),
            assignments=[("runner.model", "m", clear, restore)], crash_hook=crash)
        raise SystemExit(0 if result is None else 2)
    """)
    child = subprocess.run([sys.executable, "-c", code, str(tmp_path), boundary],
                           cwd=ROOT, capture_output=True, text=True)
    assert child.returncode == 71, child.stderr
    journal = tmp_path / "data" / "models" / modeldelete.DELETE_JOURNAL
    assert journal.is_file()

    def resolver(label, old):
        assert (label, old) == ("runner.model", "m")
        return (lambda: assignment.write_text(""), lambda: assignment.write_text(old))

    assert modeldelete.recover_owned_model_transaction(
        root=tmp_path, assignment_resolver=resolver) is None
    row_present = boundary in {"journal", "quarantine"}
    assert json.loads(registry.read_text())["models"] == ([entry] if row_present else [])
    assert target.exists() is row_present
    assert assignment.read_text() == ("m" if row_present else "")
    assert not journal.exists()
    assert list((tmp_path / "data" / "models").glob(".deleting-*")) == []


def test_delete_recovery_refuses_a_symlink_journal_without_touching_its_target(tmp_path):
    models_root = tmp_path / "data" / "models"
    models_root.mkdir(parents=True)
    _write_registry(tmp_path, [])
    outside = tmp_path / "outside.json"
    outside.write_text('{"do":"not trust"}')
    (models_root / modeldelete.DELETE_JOURNAL).symlink_to(outside)
    calls = []
    detail = modeldelete.recover_owned_model_transaction(
        root=tmp_path,
        assignment_resolver=lambda *_: calls.append(True))
    assert "requires attention" in detail
    assert outside.read_text() == '{"do":"not trust"}'
    assert calls == []


def test_delete_recovery_refuses_reused_model_identity(tmp_path):
    models_root = tmp_path / "data" / "models"
    old_target = models_root / "old"
    models_root.mkdir(parents=True)
    old_entry = {"id": "same", "source": "local",
                 "path": str(old_target / "model.gguf")}
    new_entry = {"id": "same", "source": "download",
                 "path": str(models_root / "different" / "model.gguf")}
    registry = _write_registry(tmp_path, [new_entry])
    quarantine = models_root / ".deleting-same-fixed"
    quarantine.mkdir()
    (quarantine / "model.gguf").write_bytes(b"old")
    journal = models_root / modeldelete.DELETE_JOURNAL
    modeldelete._write_journal(journal, {
        "version": 1, "model_id": "same", "registry_entry": old_entry,
        "target": str(old_target), "quarantine": str(quarantine),
        "artifact_existed": True, "assignments": [],
    })

    detail = modeldelete.recover_owned_model_transaction(
        root=tmp_path, assignment_resolver=lambda *_: pytest.fail("no assignment work"))
    assert "identity was reused" in detail
    assert json.loads(registry.read_text())["models"] == [new_entry]
    assert quarantine.is_dir() and not old_target.exists()
    assert journal.is_file()
