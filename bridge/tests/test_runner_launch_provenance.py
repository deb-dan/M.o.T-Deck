"""U37: live model identity comes from exact runner launch provenance."""
from __future__ import annotations

import json

from bridge.core import modelid
from bridge.core import procs


def test_exact_owned_launch_record_is_accepted(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "runner.active.json").write_text(json.dumps({
        "v": 1, "pid": 42, "birth": "born", "engine": "mlxvlm",
        "model": "active-mlx", "wire": "/models/active-mlx",
    }))
    monkeypatch.setattr(modelid, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_read_ownership", lambda name: (42, "born"))
    monkeypatch.setattr(procs, "_ownership_matches",
                        lambda pid, name: pid == 42 and name == "runner")
    assert modelid._runner_launch_record()["model"] == "active-mlx"


def test_stale_or_unowned_launch_record_is_rejected(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "runner.active.json").write_text(json.dumps({
        "v": 1, "pid": 42, "birth": "old", "engine": "mlxlm",
        "model": "wrong", "wire": "/models/wrong",
    }))
    monkeypatch.setattr(modelid, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_read_ownership", lambda name: (42, "new"))
    monkeypatch.setattr(procs, "_ownership_matches", lambda pid, name: False)
    assert modelid._runner_launch_record() is None


def test_symlinked_launch_marker_is_never_live_truth(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({
        "v": 1, "pid": 42, "birth": "born", "engine": "mlxlm",
        "model": "fabricated", "wire": "/models/fabricated"}))
    (data / "runner.active.json").symlink_to(outside)
    monkeypatch.setattr(modelid, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_read_ownership", lambda name: (42, "born"))
    monkeypatch.setattr(procs, "_ownership_matches", lambda pid, name: True)
    assert modelid._runner_launch_record() is None


def test_mlx_cache_order_cannot_override_launch_provenance(monkeypatch):
    rows = [{"id": "active-mlx", "format": "mlx", "path": "/models/active-mlx"}]
    monkeypatch.setattr(modelid, "_runner_loaded_id", lambda port: "cached/unrelated")
    monkeypatch.setattr(modelid, "_registry_models", lambda: rows)
    monkeypatch.setattr(modelid, "cfg", lambda: {"runner": {"port": 6767,
                                                              "model": "active-mlx"}})
    monkeypatch.setattr(modelid, "_runner_launch_record", lambda: {
        "v": 1, "pid": 7, "birth": "born", "engine": "mlxlm",
        "model": "active-mlx", "wire": "/models/active-mlx",
    })
    assert modelid._live_model_id(6767) == "active-mlx"


def test_ambiguous_mlx_probe_without_provenance_is_not_called_live(monkeypatch):
    rows = [{"id": "saved-mlx", "format": "mlx", "path": "/models/saved-mlx"}]
    monkeypatch.setattr(modelid, "_runner_loaded_id", lambda port: "cached/unrelated")
    monkeypatch.setattr(modelid, "_registry_models", lambda: rows)
    monkeypatch.setattr(modelid, "cfg", lambda: {"runner": {"port": 6767,
                                                              "model": "saved-mlx"}})
    monkeypatch.setattr(modelid, "_runner_launch_record", lambda: None)
    assert modelid._live_model_id(6767) is None


def test_aux_probe_never_uses_runner_launch_record(monkeypatch):
    monkeypatch.setattr(modelid, "_runner_loaded_id", lambda port: "aux-alias")
    monkeypatch.setattr(modelid, "_registry_models", lambda: [])
    monkeypatch.setattr(modelid, "cfg", lambda: {"runner": {"port": 6767}})
    monkeypatch.setattr(modelid, "_runner_launch_record",
                        lambda: (_ for _ in ()).throw(AssertionError("runner record read")))
    assert modelid._live_model_id(6768) == "aux-alias"
