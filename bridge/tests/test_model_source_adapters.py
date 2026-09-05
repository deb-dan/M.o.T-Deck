"""U82: manager membership and filesystem structure are independent evidence."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MS = _load("u82_sources", "scripts/model_sources.py")
SR = _load("u82_seed", "scripts/seed_registry.py")


def _gguf(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little") * 2)


def _catalog_row(relative, key="model", **extra):
    return {"type": "llm", "format": "gguf", "path": relative,
            "modelKey": key, "displayName": key, **extra}


def _completed(rows, returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(rows), stderr=stderr)


def test_adapter_ignores_non_llm_and_preserves_supported_metadata(tmp_path, monkeypatch):
    root = tmp_path / "models"
    artifact = root / "publisher" / "model" / "model.gguf"
    _gguf(artifact)
    binary = tmp_path / "lms"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    monkeypatch.setattr(MS, "_lms_binary", lambda: str(binary))
    rows = [_catalog_row("publisher/model/model.gguf", "publisher/model",
                         sizeBytes=24, maxContextLength=32768, vision=True,
                         trainedForToolUse=False),
            {"type": "embedding", "format": "gguf", "path": "embed/e.gguf",
             "modelKey": "embed/e"}]
    got = MS.lmstudio_inventory(str(root), run=lambda *a, **k: _completed(rows))
    assert got["state"] == "available" and len(got["members"]) == 1
    member = got["members"][0]
    assert member["path"] == os.path.realpath(artifact)
    assert (member["ctx"], member["vision"], member["tools"]) == (32768, True, False)
    assert set(MS.source_observation(member, got["root"])) == {
        "v", "adapter", "root", "member_key", "format", "path"}


@pytest.mark.parametrize("rows", [
    [{"type": "llm", "format": "future", "path": "a", "modelKey": "a"}],
    [{"type": "llm", "format": "gguf", "path": "/absolute.gguf", "modelKey": "a"}],
    [{"type": "llm", "format": "gguf", "path": "../escape.gguf", "modelKey": "a"}],
    [{"type": "llm", "format": "gguf", "path": "a/../b.gguf", "modelKey": "a"}],
    [{"type": "llm", "format": "gguf", "path": "a.gguf", "modelKey": ""}],
    ["not-an-object"],
])
def test_unknown_or_unsafe_whole_catalog_has_no_deletion_authority(tmp_path, monkeypatch, rows):
    binary = tmp_path / "lms"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    monkeypatch.setattr(MS, "_lms_binary", lambda: str(binary))
    got = MS.lmstudio_inventory(str(tmp_path / "models"), run=lambda *a, **k: _completed(rows))
    assert got["state"] == "unsupported" and got["members"] == []


def test_duplicate_and_symlink_escape_reject_the_whole_observation(tmp_path, monkeypatch):
    binary = tmp_path / "lms"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    monkeypatch.setattr(MS, "_lms_binary", lambda: str(binary))
    root = tmp_path / "models"; root.mkdir()
    outside = tmp_path / "outside.gguf"; _gguf(outside)
    (root / "escape.gguf").symlink_to(outside)
    escaped = MS.lmstudio_inventory(str(root), run=lambda *a, **k: _completed([
        _catalog_row("escape.gguf")]))
    assert escaped["state"] == "unsupported"
    duplicate = MS.lmstudio_inventory(str(root), run=lambda *a, **k: _completed([
        _catalog_row("same.gguf", "one"), _catalog_row("same.gguf", "two")]))
    assert duplicate["state"] == "unsupported"
    duplicate_key = MS.lmstudio_inventory(str(root), run=lambda *a, **k: _completed([
        _catalog_row("one.gguf", "same"), _catalog_row("two.gguf", "same")]))
    assert duplicate_key["state"] == "unsupported"


def test_cli_failure_timeout_and_malformed_output_never_become_empty_catalog(tmp_path, monkeypatch):
    root = str(tmp_path / "models")
    monkeypatch.setattr(MS, "_lms_binary", lambda: None)
    assert MS.lmstudio_inventory(root)["state"] == "unavailable"
    binary = tmp_path / "lms"; binary.write_text("#!/bin/sh\n"); binary.chmod(0o755)
    monkeypatch.setattr(MS, "_lms_binary", lambda: str(binary))
    failed = MS.lmstudio_inventory(root, run=lambda *a, **k: _completed([], 2, "failed"))
    assert failed["state"] == "unavailable" and failed["members"] == []
    timed = MS.lmstudio_inventory(root, run=lambda *a, **k: (_ for _ in ()).throw(
        subprocess.TimeoutExpired("lms", 20)))
    assert timed["state"] == "unavailable" and timed["members"] == []
    malformed = MS.lmstudio_inventory(root, run=lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="warning\n{}", stderr=""))
    assert malformed["state"] == "unsupported" and malformed["members"] == []


def test_explicit_rescan_reconciles_eleven_files_to_eight_manager_rows(tmp_path, monkeypatch, capsys):
    """The screenshot class: discover the set difference, never name a row by hand."""
    root = tmp_path / "lmstudio"
    all_rows, existing = [], []
    for number in range(11):
        rel = f"publisher/model-{number}/model-{number}.gguf"
        path = root / rel
        _gguf(path)
        all_rows.append(_catalog_row(rel, f"publisher/model-{number}"))
        existing.append({"id": f"model-{number}", "name": f"model-{number}",
                         "format": "gguf", "path": str(path),
                         "source": "lmstudio-import"})
    catalog = tmp_path / "catalog.json"; catalog.write_text(json.dumps(all_rows[:8]))
    binary = tmp_path / "lms"
    binary.write_text('#!/bin/sh\ncat "$FAKE_LMS_CATALOG"\n'); binary.chmod(0o755)
    registry = tmp_path / "models.json"
    registry.write_text(json.dumps({"models": existing}) + "\n")
    empty = tmp_path / "empty"; empty.mkdir()
    monkeypatch.setenv("HARNESS_LMS_BIN", str(binary))
    monkeypatch.setenv("FAKE_LMS_CATALOG", str(catalog))
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "LMSTUDIO_MODELS_DIR", str(root))
    monkeypatch.setattr(SR, "LOCAL_MODELS_DIR", str(empty))
    monkeypatch.setattr(SR, "JAN_MODELS_DIR", str(empty / "jan"))
    monkeypatch.setattr(SR, "AUDIO_HF_CACHE_DIR", str(empty / "audio"))
    assert SR.main(["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    saved = json.loads(registry.read_text())["models"]
    assert len(saved) == 8 and len(result["manager_removed"]) == 3
    assert all(row["source_membership"] == "listed" for row in saved)
    assert len(list(root.rglob("*.gguf"))) == 11, "registry reconciliation never deletes weights"
    assert not (tmp_path / "lmstudio-catalog.json").exists(), "models.json remains the only registry"

    before = registry.read_bytes()
    monkeypatch.setattr(SR.MODEL_SOURCES, "lmstudio_inventory", lambda *_: {
        "state": "unavailable", "members": [], "detail": "manager offline"})
    assert SR.main(["--json"]) == 0
    partial = json.loads(capsys.readouterr().out)
    assert partial["partial"] is True and partial["source_warnings"] == ["manager offline"]
    assert registry.read_bytes() == before, "adapter failure cannot masquerade as an empty catalog"


def test_protected_manager_removed_row_is_explanatory_but_not_offerable(tmp_path):
    artifact = tmp_path / "model.gguf"; _gguf(artifact)
    old = {"id": "live", "format": "gguf", "path": str(artifact),
           "source": "lmstudio-import"}
    inventory = {"state": "available", "root": str(tmp_path), "members": []}
    rows, removed, unlisted = SR.reconcile_lmstudio([old], [old], inventory, protect=["live"])
    assert removed == [] and unlisted == ["live"]
    assert rows[0]["source_membership"] == "unlisted"
    assert SR.MODELREG.offerable(rows) == []


def test_new_same_basename_members_receive_unique_stable_registry_ids(tmp_path):
    members = []
    for publisher in ("one", "two", "three"):
        path = tmp_path / publisher / "same.gguf"; _gguf(path)
        members.append({"format": "gguf", "path": os.path.realpath(path),
                        "relative_path": f"{publisher}/same.gguf",
                        "member_key": publisher, "display_name": publisher,
                        "size_bytes": 24, "ctx": None, "vision": False, "tools": None})
    inventory = {"state": "available", "root": os.path.realpath(tmp_path), "members": members}
    listed, _, _ = SR.reconcile_lmstudio([], [], inventory)
    merged = SR.merge([], [], listed, [], [], refreshed_sources={"lmstudio-import"},
                      authoritative_sources={"lmstudio-import"})
    assert [row["id"] for row in merged] == ["same", "same-lms", "same-lms-2"]


def test_nonexplicit_existing_registry_never_queries_or_resurrects_manager(tmp_path, monkeypatch):
    registry = tmp_path / "models.json"
    kept = {"id": "kept", "format": "gguf", "path": str(tmp_path / "kept.gguf"),
            "source": "lmstudio-import", "source_membership": "listed"}
    _gguf(tmp_path / "kept.gguf")
    registry.write_text(json.dumps({"models": [kept]}) + "\n")
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "local_entries_for", lambda _: [])
    monkeypatch.setattr(SR, "scan_jan", lambda _: [])
    monkeypatch.setattr(SR, "scan_audio_hf_cache", lambda _: [])
    monkeypatch.setattr(SR.MODEL_SOURCES, "lmstudio_inventory",
                        lambda *_: pytest.fail("ordinary startup queried the manager"))
    assert SR.main([]) == 0
    saved = json.loads(registry.read_text())["models"]
    assert len(saved) == 1 and all(saved[0][key] == value for key, value in kept.items())
