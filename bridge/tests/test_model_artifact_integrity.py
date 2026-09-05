"""U75 journeys: one cheap artifact verdict drives discovery and every new load."""
import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from bridge.core import modelreg as MR  # noqa: E402
from bridge.core.health import file_state_forget, file_state_track  # noqa: E402
from bridge.tests.model_fixture import (gguf_bytes as valid_gguf_bytes,
                                        safetensors_bytes)  # noqa: E402

_spec = importlib.util.spec_from_file_location("u75_seed", os.path.join(ROOT, "scripts", "seed_registry.py"))
SR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SR)


def gguf_bytes(version=3):
    if version not in (2, 3):
        return b"GGUF" + int(version).to_bytes(4, "little") + b"\0" * 32
    return valid_gguf_bytes(version=version)


def gguf(tmp_path, name="model.gguf", data=None, **extra):
    p = tmp_path / name
    p.write_bytes(gguf_bytes() if data is None else data)
    return {"id": p.stem, "format": "gguf", "path": str(p), **extra}


def mlx(tmp_path, *, config='{"model_type":"unit-test"}', weights=("model.safetensors",)):
    d = tmp_path / "model-mlx"
    d.mkdir()
    if config is not None:
        (d / "config.json").write_text(config)
    for name in weights:
        (d / name).write_bytes(safetensors_bytes())
    return {"id": "mlx", "format": "mlx", "path": str(d)}


def test_gguf_single_split_projection_and_lmstudio_grouping(tmp_path):
    single = MR.artifact_probe(gguf(tmp_path))
    assert single["state"] == "ready"
    assert single["evidence"]["manifest"] == {"kind": "gguf", "files": ["model.gguf"]}
    assert MR.artifact_probe(gguf(tmp_path, "zero.gguf", b""))["state"] == "incomplete"
    d = tmp_path / "split"; d.mkdir()
    for n in (1, 2, 3): (d / f"q-0000{n}-of-00003.gguf").write_bytes(gguf_bytes())
    split = {"id": "q", "format": "gguf", "path": str(d / "q-00001-of-00003.gguf")}
    assert MR.artifact_probe(split)["state"] == "ready"
    (d / "q-00002-of-00003.gguf").unlink()
    assert MR.artifact_probe(split)["reason"] == "missing-shard"
    (d / "q-00002-of-00003.gguf").write_bytes(b"")
    assert MR.artifact_probe(split)["reason"] == "invalid-shard"
    projection = tmp_path / "mmproj.gguf"
    projected = gguf(tmp_path, "vision.gguf", mmproj=str(projection))
    assert MR.artifact_probe(projected)["reason"] == "missing-mmproj"
    projection.write_bytes(b"")
    assert MR.artifact_probe(projected)["reason"] == "invalid-mmproj"
    projection.write_bytes(gguf_bytes())
    assert MR.artifact_probe(projected)["state"] == "ready"
    for invalid in (True, [], {}):
        assert MR.artifact_probe(gguf(tmp_path, f"bad-{type(invalid).__name__}.gguf", mmproj=invalid))["reason"] == "invalid-mmproj"
    lms = tmp_path / "lms" / "pub" / "q"; lms.mkdir(parents=True)
    for n in (1, 2): (lms / f"q-0000{n}-of-00002.gguf").write_bytes(gguf_bytes())
    rows = SR.scan_lmstudio(str(tmp_path / "lms"))
    assert [(r["id"], r["size_bytes"]) for r in rows] == [("q", len(gguf_bytes()) * 2)]


def test_structural_probe_rejects_nonempty_garbage_and_malformed_headers(tmp_path):
    assert MR.artifact_probe(gguf(tmp_path, "one-byte.gguf", b"x"))["reason"] == "invalid-header"
    assert MR.artifact_probe(gguf(tmp_path, "bad-magic.gguf", b"NOPE" + gguf_bytes()[4:]))["reason"] == "invalid-header"
    assert MR.artifact_probe(gguf(tmp_path, "future.gguf", gguf_bytes(99)))["reason"] == "invalid-header"
    empty_inventory = b"GGUF" + (3).to_bytes(4, "little") + (0).to_bytes(8, "little") * 2
    assert MR.artifact_probe(gguf(tmp_path, "empty-inventory.gguf", empty_inventory))["reason"] == "invalid-header"
    truncated_inventory = (b"GGUF" + (3).to_bytes(4, "little")
                           + (1).to_bytes(8, "little") * 2 + b"x")
    assert MR.artifact_probe(gguf(tmp_path, "truncated.gguf", truncated_inventory))["reason"] == "invalid-header"
    outside = valid_gguf_bytes(tensor_offset=4096)
    assert MR.artifact_probe(gguf(tmp_path, "outside.gguf", outside))["reason"] == "invalid-header"
    for removed_or_unknown in (4, 5, 31, 32, 33, 36, 37, 38, 43, 1024):
        data = valid_gguf_bytes(tensor_type=removed_or_unknown)
        assert MR.artifact_probe(gguf(
            tmp_path, f"type-{removed_or_unknown}.gguf", data))["reason"] == "invalid-header"
    for supported in sorted(MR._PINNED_GGML_TYPES):
        data = valid_gguf_bytes(tensor_type=supported)
        assert MR.artifact_probe(gguf(
            tmp_path, f"supported-type-{supported}.gguf", data))["state"] == "ready"

    bad_weight = mlx(tmp_path)
    weight = tmp_path / "model-mlx" / "model.safetensors"
    weight.write_bytes(b"x")
    assert MR.artifact_probe(bad_weight)["reason"] == "invalid-weight"
    weight.write_bytes((999).to_bytes(8, "little") + b"{}")
    assert MR.artifact_probe(bad_weight)["reason"] == "invalid-weight"
    malformed = json.dumps({"weight": {
        "dtype": "F32", "shape": [2], "data_offsets": [0, 4],
    }}, separators=(",", ":")).encode()
    weight.write_bytes(len(malformed).to_bytes(8, "little") + malformed + b"\0\0\0\0")
    assert MR.artifact_probe(bad_weight)["reason"] == "invalid-weight"
    weight.write_bytes(safetensors_bytes())
    (tmp_path / "model-mlx" / "config.json").write_text("{}")
    assert MR.artifact_probe(bad_weight)["reason"] == "invalid-config"


def test_structural_probe_is_single_flight_and_invalidates_on_identity_change(tmp_path, monkeypatch):
    row = gguf(tmp_path, "shared.gguf")
    MR._PROBE_CACHE.clear()
    real = MR._artifact_probe_uncached
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def slow(entry):
        calls.append(entry["path"])
        entered.set()
        assert release.wait(2)
        return real(entry)

    monkeypatch.setattr(MR, "_artifact_probe_uncached", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(MR.artifact_probe(row)))
               for _ in range(8)]
    for thread in threads:
        thread.start()
    assert entered.wait(1)
    time.sleep(0.05)  # give every peer time to reach the guarded cache lookup
    release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert len(calls) == 1
    assert [result["state"] for result in results] == ["ready"] * 8

    # A cached result is a copy: a caller cannot poison every later consumer.
    results[0]["evidence"]["manifest"]["files"].append("poison")
    assert MR.artifact_probe(row)["evidence"]["manifest"]["files"] == ["shared.gguf"]

    # Same path, new bytes, caller-restored mtime: ctime/size/inode identity still
    # invalidates the ready verdict and the real validator sees the corruption.
    before = os.stat(row["path"])
    with open(row["path"], "r+b") as fh:
        fh.seek(0)
        fh.write(b"NOPE")
    os.utime(row["path"], ns=(before.st_atime_ns, before.st_mtime_ns))
    release.set()
    assert MR.artifact_probe(row)["reason"] == "invalid-header"
    assert len(calls) == 2


def test_structural_probe_mlx_manifest_change_invalidates_cache(tmp_path):
    row = mlx(tmp_path)
    MR._PROBE_CACHE.clear()
    assert MR.artifact_probe(row)["state"] == "ready"
    weight = tmp_path / "model-mlx" / "model.safetensors"
    weight.write_bytes(b"x")
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"
    weight.write_bytes(safetensors_bytes())
    extra = tmp_path / "model-mlx" / "extra.safetensors"
    extra.write_bytes(b"x")
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"


def test_structural_probe_cache_separates_projector_semantics_and_unstable_bytes(tmp_path, monkeypatch):
    row = gguf(tmp_path, "projected.gguf")
    MR._PROBE_CACHE.clear()
    assert MR.artifact_probe(row)["state"] == "ready"
    assert MR.artifact_probe(dict(row, mmproj=True))["reason"] == "invalid-mmproj"

    real = MR._artifact_probe_uncached
    changed = False

    def mutate_during_probe(entry):
        nonlocal changed
        verdict = real(entry)
        if not changed:
            changed = True
            with open(entry["path"], "r+b") as fh:
                fh.seek(0)
                fh.write(b"NOPE")
        return verdict

    other = gguf(tmp_path, "moving.gguf")
    monkeypatch.setattr(MR, "_artifact_probe_uncached", mutate_during_probe)
    assert MR.artifact_probe(other)["reason"] == "changed-during-probe"
    assert MR.artifact_probe(other)["reason"] == "invalid-header"


def test_structural_probe_different_artifacts_do_not_share_a_flight(tmp_path, monkeypatch):
    first = gguf(tmp_path, "first.gguf")
    second = gguf(tmp_path, "second.gguf")
    MR._PROBE_CACHE.clear()
    real = MR._artifact_probe_uncached
    first_entered = threading.Event()
    release_first = threading.Event()

    def slow_first(entry):
        if entry["path"] == first["path"]:
            first_entered.set()
            assert release_first.wait(2)
        return real(entry)

    monkeypatch.setattr(MR, "_artifact_probe_uncached", slow_first)
    one = threading.Thread(target=lambda: MR.artifact_probe(first))
    one.start()
    assert first_entered.wait(1)
    # The second model must complete while the first model's validator is deliberately
    # suspended. A global lock would turn one slow external source into app-wide pain.
    two = threading.Thread(target=lambda: MR.artifact_probe(second))
    two.start()
    two.join(1)
    assert not two.is_alive()
    release_first.set()
    one.join(2)
    assert not one.is_alive()


@pytest.mark.parametrize("dtype,shape,payload_bytes", [
    ("F4", (2,), 1),
    ("F6_E2M3", (4,), 3),
    ("F6_E3M2", (4,), 3),
    ("F8_E4M3FNUZ", (1,), 1),
    ("F8_E5M2FNUZ", (1,), 1),
    ("C64", (1,), 8),
])
def test_current_safetensors_dtypes_use_their_real_packed_widths(
        tmp_path, dtype, shape, payload_bytes):
    row = mlx(tmp_path)
    weight = tmp_path / "model-mlx" / "model.safetensors"
    weight.write_bytes(safetensors_bytes(
        dtype=dtype, shape=shape, payload_bytes=payload_bytes))
    assert MR.artifact_probe(row)["state"] == "ready"


def test_packed_safetensors_reject_fractional_or_mismatched_storage(tmp_path):
    row = mlx(tmp_path)
    weight = tmp_path / "model-mlx" / "model.safetensors"
    weight.write_bytes(safetensors_bytes(dtype="F4", shape=(1,), payload_bytes=1))
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"
    weight.write_bytes(safetensors_bytes(dtype="F6_E2M3", shape=(4,), payload_bytes=2))
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"
    weight.write_bytes(safetensors_bytes(dtype="F128", shape=(1,), payload_bytes=16))
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"


@pytest.mark.parametrize("config,weights,reason", [
    (None, (), "missing-config"), ("", ("model.safetensors",), "invalid-config"),
    ("[]", ("model.safetensors",), "invalid-config"), ("{", ("model.safetensors",), "invalid-config"),
    ("{}", (), "invalid-config"), ("{}", ("model.safetensors",), "invalid-config"),
    ('{"model_type":"unit-test"}', (), "missing-weight"),
    ('{"model_type":"unit-test"}', ("model.safetensors",), "structurally-ready"),
])
def test_mlx_config_and_weight_matrix(tmp_path, config, weights, reason):
    assert MR.artifact_probe(mlx(tmp_path, config=config, weights=weights))["reason"] == reason


def test_mlx_indexes_shards_and_ordinary_multifile(tmp_path):
    row = mlx(tmp_path, weights=("a.safetensors", "b.safetensors"))
    d = tmp_path / "model-mlx"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "a.safetensors", "y": "b.safetensors"}}))
    ready = MR.artifact_probe(row)
    assert ready["state"] == "ready"
    assert ready["evidence"]["manifest"] == {
        "kind": "mlx",
        "files": ["a.safetensors", "b.safetensors", "config.json", "model.safetensors.index.json"],
    }
    (d / "b.safetensors").unlink()
    assert MR.artifact_probe(row)["reason"] == "missing-indexed-shard"
    (d / "b.safetensors").write_bytes(b"")
    assert MR.artifact_probe(row)["reason"] == "invalid-indexed-shard"
    (d / "b.safetensors").write_bytes(safetensors_bytes())
    (d / "model.safetensors.index.json").write_text("{")
    assert MR.artifact_probe(row)["reason"] == "invalid-index"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {}}))
    assert MR.artifact_probe(row)["reason"] == "invalid-weight-map"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "../x.safetensors"}}))
    assert MR.artifact_probe(row)["reason"] == "invalid-index-target"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "/x.safetensors"}}))
    assert MR.artifact_probe(row)["reason"] == "invalid-index-target"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "nested/x.safetensors"}}))
    assert MR.artifact_probe(row)["reason"] == "invalid-index-target"
    for bad in ([], {}, None, 1, r"bad\\x.safetensors", ".", ".."):
        (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": bad}}))
        assert MR.artifact_probe(row)["reason"] == "invalid-index-target"
    (d / "model.safetensors.index.json").unlink()
    (d / "a.safetensors").unlink(); (d / "b.safetensors").unlink()
    for n in (1, 2): (d / f"w-0000{n}-of-00002.safetensors").write_bytes(safetensors_bytes())
    assert MR.artifact_probe(row)["state"] == "ready"
    (d / "w-00002-of-00002.safetensors").write_bytes(b"")
    assert MR.artifact_probe(row)["reason"] == "invalid-shard"


def test_mlx_zero_weight_is_incomplete(tmp_path):
    row = mlx(tmp_path)
    (tmp_path / "model-mlx" / "model.safetensors").write_bytes(b"")
    assert MR.artifact_probe(row)["reason"] == "invalid-weight"


def test_wrong_root_kind_invalid_shard_names_and_unreadable_metadata(tmp_path, monkeypatch):
    wrong_gguf = tmp_path / "wrong.gguf"; wrong_gguf.mkdir()
    assert MR.artifact_probe({"format": "gguf", "path": str(wrong_gguf)})["reason"] == "wrong-kind"
    wrong_mlx = tmp_path / "wrong-mlx"; wrong_mlx.write_bytes(safetensors_bytes())
    assert MR.artifact_probe({"format": "mlx", "path": str(wrong_mlx)})["reason"] == "wrong-kind"
    for name in ("q-00000-of-00003.gguf", "q-00004-of-00003.gguf", "q-00001-of-00000.gguf"):
        assert MR.artifact_probe(gguf(tmp_path, name))["reason"] == "invalid-shard-name"
    invalid_lms = tmp_path / "lms" / "pub" / "bad"; invalid_lms.mkdir(parents=True)
    (invalid_lms / "q-00000-of-00003.gguf").write_bytes(gguf_bytes())
    assert SR.scan_lmstudio(str(tmp_path / "lms")) == []
    row = mlx(tmp_path)
    real_stat = MR.os.stat
    monkeypatch.setattr(MR.os, "stat", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError())
                        if str(p).endswith("config.json") else real_stat(p, *a, **k))
    assert MR.artifact_probe(row)["state"] == "unknown"
    monkeypatch.undo()
    d = tmp_path / "model-mlx"
    (d / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"x": "model.safetensors"}}))
    monkeypatch.setattr(MR.os, "stat", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError())
                        if str(p).endswith(".index.json") else real_stat(p, *a, **k))
    assert MR.artifact_probe(row)["state"] == "unknown"


def test_mlx_invalid_numbered_shards_are_incomplete(tmp_path):
    for name in ("w-00000-of-00003.safetensors", "w-00004-of-00003.safetensors", "w-00001-of-00000.safetensors"):
        row = mlx(tmp_path, weights=(name,))
        assert MR.artifact_probe(row)["reason"] == "invalid-shard-name"
        shutil.rmtree(tmp_path / "model-mlx")


def test_unknown_incomplete_and_missing_have_distinct_catalog_and_health_rules(tmp_path, monkeypatch):
    ready = gguf(tmp_path, "ready.gguf")
    broken = gguf(tmp_path, "broken.gguf", b"")
    missing = {"id": "missing", "format": "gguf", "path": str(tmp_path / "gone.gguf")}
    assert [m["id"] for m in MR.offerable([ready, broken])] == ["ready"]
    assert MR.offerable([broken]) == []             # U76 fallback never resurrects incomplete
    assert [m["id"] for m in MR.offerable([missing])] == ["missing"]
    assert [m["id"] for m in MR.offerable([broken, missing])] == ["missing"]
    file_state_forget()
    st = file_state_track("broken", broken)
    assert st["state"] == "incomplete" and st["reason"] == "empty-file"
    monkeypatch.setattr(MR.os, "stat", lambda *_: (_ for _ in ()).throw(PermissionError()))
    assert MR.artifact_probe(ready)["state"] == "unknown"


def test_switch_and_aux_refuse_broken_before_side_effects(tmp_path, monkeypatch):
    from bridge.routers import aux, models
    broken = gguf(tmp_path, "broken.gguf", b"")
    broken["id"] = "broken"
    monkeypatch.setattr(models, "_registry_models", lambda: [broken])
    monkeypatch.setattr(models, "cfg", lambda: {"runner": {"adapter": "auto", "model": "old"}})
    monkeypatch.setattr(models, "_set_runner_model", lambda *_: pytest.fail("pin mutated"))
    models._SWITCH.update(busy=False, log="")
    class Request:
        async def json(self): return {"id": "broken"}
    response = asyncio.run(models.api_switch_model(Request()))
    assert response.status_code == 409 and b"incomplete" in response.body
    root = tmp_path / "aux-root"; (root / "data").mkdir(parents=True)
    (root / "data" / "models.json").write_text(json.dumps({"models": [broken]}))
    monkeypatch.setattr(aux, "ROOT", root)
    monkeypatch.setattr(aux, "cfg", lambda: {"aux": {
        "model": "broken", "port": 6768, "api_key": "fixture-key"}})
    monkeypatch.setattr(aux, "_aux_kill", lambda *_: pytest.fail("port cleared"))
    class AuxRequest: query_params = {}
    assert aux.aux_start(AuxRequest()).status_code == 400
    async def set_body(mid): return {"id": mid}
    monkeypatch.setattr(aux, "_set_yaml_model", lambda *_: pytest.fail("aux YAML mutated"))
    class SetRequest:
        async def json(self): return {"id": "broken"}
    assert asyncio.run(aux.aux_set(SetRequest())).status_code == 409
    missing = {"id": "missing", "format": "gguf", "path": str(tmp_path / "gone.gguf")}
    (root / "data" / "models.json").write_text(json.dumps({"models": [missing]}))
    class MissingSetRequest:
        async def json(self): return {"id": "missing"}
    assert asyncio.run(aux.aux_set(MissingSetRequest())).status_code == 400
    monkeypatch.setattr(models, "_registry_models", lambda: [missing])
    assert asyncio.run(models.api_switch_model(Request())).status_code == 400
    monkeypatch.setattr(MR.os, "stat", lambda *_: (_ for _ in ()).throw(PermissionError()))
    (root / "data" / "models.json").write_text(json.dumps({"models": [broken]}))
    monkeypatch.setattr(models, "_registry_models", lambda: [broken])
    assert asyncio.run(models.api_switch_model(Request())).status_code == 409
    assert asyncio.run(aux.aux_set(SetRequest())).status_code == 409
    assert models._SWITCH["busy"] is False


def test_merge_keeps_unknown_rescanned_row_and_helper_absence_writes_nothing(tmp_path, monkeypatch):
    unknown = {"id": "unknown", "format": "gguf", "path": str(tmp_path / "x.gguf"), "source": "lmstudio-import"}
    missing = {"id": "missing", "format": "gguf", "path": str(tmp_path / "gone.gguf"), "source": "lmstudio-import"}
    audio = {"id": "audio", "kind": "audio", "format": "stt-mlx", "path": str(tmp_path / "gone-audio"), "source": "audio-hf-cache"}
    incomplete = {"id": "incomplete", "format": "gguf", "path": str(tmp_path / "empty.gguf"), "source": "lmstudio-import"}
    (tmp_path / "empty.gguf").write_bytes(b"")
    class Probe:
        @staticmethod
        def artifact_probe(row):
            return {"state": {"unknown": "unknown", "incomplete": "incomplete", "audio": "unknown"}.get(row["id"], "missing")}
    monkeypatch.setattr(SR, "MODELREG", Probe())
    assert [m["id"] for m in SR.merge([unknown, incomplete, missing, audio], [], [], [])] == ["unknown", "incomplete", "missing"]
    fresh_unknown = dict(unknown, path="fresh")
    fresh_incomplete = dict(incomplete, path="fresh-empty")
    merged = SR.merge([unknown, incomplete], [], [fresh_unknown, fresh_incomplete], [])
    assert [(m["id"], m["path"]) for m in merged] == [("unknown", "fresh"), ("incomplete", "fresh-empty")]
    registry = tmp_path / "models.json"; registry.write_bytes(b'{"models":["keep"]}\n')
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "MODELREG", None)
    with pytest.raises(SystemExit, match="integrity helper unavailable"):
        SR.main()
    assert registry.read_bytes() == b'{"models":["keep"]}\n'


def test_lmstudio_child_listdir_race_is_nonfatal_and_preserves_existing(tmp_path, monkeypatch):
    lms = tmp_path / "lms"; child = lms / "pub" / "model"; child.mkdir(parents=True)
    existing = {"id": "model", "format": "mlx", "path": str(child), "source": "lmstudio-import"}
    real_listdir = SR.os.listdir
    monkeypatch.setattr(SR.os, "listdir", lambda p: (_ for _ in ()).throw(PermissionError())
                        if str(p) == str(child) else real_listdir(p))
    assert SR.scan_lmstudio(str(lms)) == []
    assert SR.merge([existing], [], [], []) == [existing]


def test_main_resolver_refuses_the_same_broken_artifact_before_launch(tmp_path):
    root = tmp_path / "runner-fixture"
    (root / "scripts").mkdir(parents=True)
    (root / "bridge" / "core").mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copy2(os.path.join(ROOT, "scripts", "start_component.sh"),
                 root / "scripts" / "start_component.sh")
    shutil.copy2(os.path.join(ROOT, "scripts", "read_manifest.py"),
                 root / "scripts" / "read_manifest.py")
    shutil.copy2(os.path.join(ROOT, "bridge", "core", "modelreg.py"),
                 root / "bridge" / "core" / "modelreg.py")
    shutil.copy2(os.path.join(ROOT, "bridge", "core", "localsecrets.py"),
                 root / "bridge" / "core" / "localsecrets.py")
    shutil.copy2(os.path.join(ROOT, "bridge", "yamlfile.py"),
                 root / "bridge" / "yamlfile.py")
    (root / "data" / "broken.gguf").write_bytes(b"")
    (root / "data" / "models.json").write_text(json.dumps({"models": [{
        "id": "broken", "format": "gguf", "path": "data/broken.gguf"}]}))
    (root / "harness.yaml").write_text(
        "runner:\n  adapter: llamacpp\n  port: 6767\n  api_key: x\n  ctx_size: 4096\n"
        "  model: broken\n  binary: null\n")
    got = subprocess.run(["bash", "scripts/start_component.sh", "runner"], cwd=root,
                         capture_output=True, text=True, timeout=30)
    assert got.returncode != 0
    assert "model 'broken' is incomplete: GGUF model file is empty" in got.stderr
    assert "Rescan or pick another model" in got.stderr
    assert "runner binary" not in got.stdout + got.stderr
    assert not (root / "data" / "logs" / "runner.log").exists()


def test_shell_resolver_names_the_shared_probe_and_panel_excludes_incomplete():
    shell = open(os.path.join(ROOT, "scripts", "start_component.sh")).read()
    panel = open(os.path.join(ROOT, "bridge", "panel", "index.html"), errors="replace").read()
    assert "modelreg.artifact_probe(m)" in shell and "Rescan or pick another model" in shell
    assert "m.file === 'incomplete'" in panel and "model incomplete" in panel
