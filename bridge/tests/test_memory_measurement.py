from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.core import memoryprefs as P
from bridge.core import runnermeasure as R


TRACE = """
0.00 I srv load_model: loading model '/models/a.gguf'
0.01 I load_tensors: CPU_Mapped model buffer size = 304.28 MiB
0.01 I load_tensors: MTL0_Mapped model buffer size = 2.00 GiB
0.02 I llama_context: n_ctx = 4096
0.02 I llama_context: CPU output buffer size = 512.00 KiB
0.03 I llama_kv_cache: MTL0 KV buffer size = 144.00 MiB
0.03 I llama_kv_cache: size = 144 MiB, K (q8_0): 72 MiB, V (f16): 72 MiB
0.04 I sched_reserve: MTL0 compute buffer size = 68.01 MiB
0.04 I sched_reserve: CPU compute buffer size = 11.01 MiB
0.05 I srv llama_server: model loaded
"""


def test_parse_exact_categories_and_units():
    got = R.parse_latest(TRACE)
    assert got is not None
    assert got["model_bytes"] == round(304.28 * 1024 ** 2) + 2 * 1024 ** 3
    assert got["context_bytes"] == 144 * 1024 ** 2
    assert got["working_bytes"] == (round(68.01 * 1024 ** 2)
                                     + round(11.01 * 1024 ** 2) + 512 * 1024)
    assert got["allocation_bytes"] == (got["model_bytes"] + got["context_bytes"]
                                        + got["working_bytes"])
    assert got["ctx"] == 4096
    assert got["kv_k"] == "q8_0"
    assert got["kv_v"] == "f16"


@pytest.mark.parametrize("text", ["", "llama_server: model loaded",
                                    "load_model: loading model x\nmodel buffer size = 1 MiB"])
def test_partial_or_unframed_logs_are_not_measurements(text):
    assert R.parse_latest(text) is None


def test_last_failed_start_does_not_fall_back_to_old_success():
    text = TRACE + "\nload_model: loading model '/models/b.gguf'\n" \
                   "CPU_Mapped model buffer size = 99 MiB\nERROR load failed\n"
    assert R.parse_latest(text) is None


def test_last_success_wins():
    newer = TRACE.replace("304.28 MiB", "400.00 MiB").replace("n_ctx = 4096",
                                                               "n_ctx = 8192")
    got = R.parse_latest(TRACE + newer)
    assert got["ctx"] == 8192
    assert any(row["bytes"] == 400 * 1024 ** 2 for row in got["buffers"])


def test_capture_requires_exact_llamacpp_launch(monkeypatch, tmp_path):
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "data" / "logs" / "runner.log").write_text(TRACE)
    monkeypatch.setattr(R, "_runner_launch_record", lambda: None)
    assert R.capture({"id": "a"}, tmp_path) is None
    monkeypatch.setattr(R, "_runner_launch_record",
                        lambda: {"engine": "mlxlm", "model": "a", "pid": 1,
                                 "birth": "b"})
    assert R.capture({"id": "a"}, tmp_path) is None
    monkeypatch.setattr(R, "_runner_launch_record",
                        lambda: {"engine": "llamacpp", "model": "a", "pid": 1,
                                 "birth": "b"})
    assert R.capture({"id": "different"}, tmp_path) is None


def test_capture_persists_bounded_attributed_sample(monkeypatch, tmp_path):
    (tmp_path / "data" / "logs").mkdir(parents=True)
    (tmp_path / "data" / "logs" / "runner.log").write_text(TRACE)
    monkeypatch.setattr(R, "_runner_launch_record",
                        lambda: {"engine": "llamacpp", "model": "a", "pid": 123,
                                 "birth": "456.7"})
    monkeypatch.setattr(R, "_prediction", lambda entry, parsed: {
        "known": True, "total_bytes": parsed["allocation_bytes"] - 1024,
        "delta_bytes": 1024, "delta_pct": 0.1})
    got = R.capture({"id": "a"}, tmp_path)
    assert got["model"] == "a" and got["pid"] == 123 and got["birth"] == "456.7"
    assert got["provenance"] == "runner-startup-log"
    assert R.recorded("a", tmp_path)["allocation_bytes"] == got["allocation_bytes"]
    disk = json.loads((tmp_path / "data" / R.STORE_NAME).read_text())
    assert disk["version"] == 1 and set(disk["models"]) == {"a"}
    monkeypatch.setattr(R, "_read_regular_tail",
                        lambda *_args, **_kwargs: pytest.fail("same launch reread its growing log"))
    assert R.capture({"id": "a"}, tmp_path) == got


def test_log_and_store_symlinks_are_refused(monkeypatch, tmp_path):
    (tmp_path / "data" / "logs").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text(TRACE)
    (tmp_path / "data" / "logs" / "runner.log").symlink_to(outside)
    monkeypatch.setattr(R, "_runner_launch_record",
                        lambda: {"engine": "llamacpp", "model": "a", "pid": 1,
                                 "birth": "b"})
    assert R.capture({"id": "a"}, tmp_path) is None

    store_outside = tmp_path / "store-outside"
    store_outside.write_text("sentinel")
    (tmp_path / "data" / R.STORE_NAME).symlink_to(store_outside)
    with pytest.raises(ValueError):
        R._write_store({"version": 1, "models": {}}, tmp_path)
    assert store_outside.read_text() == "sentinel"


def test_preferences_defaults_and_modes(tmp_path):
    assert P.read(tmp_path) == P.DEFAULTS
    assert P.needs_confirmation("over", prefs={"mode": "advise"})
    assert not P.needs_confirmation("tight", prefs={"mode": "advise"})
    assert P.needs_confirmation("tight", prefs={"mode": "early"})
    assert not P.needs_confirmation("over", prefs={"mode": "quiet"})
    assert P.needs_confirmation("over", prefs={"mode": "custom"})


def test_custom_headroom_changes_only_custom_budget():
    base = {"budget_bytes": 10 * 1024 ** 3}
    advise = P.apply_headroom(base, {"mode": "advise", "custom_headroom_gb": 4})
    custom = P.apply_headroom(base, {"mode": "custom", "custom_headroom_gb": 4})
    assert advise["budget_bytes"] == 10 * 1024 ** 3
    assert advise["custom_headroom_bytes"] == 0
    assert custom["base_budget_bytes"] == 10 * 1024 ** 3
    assert custom["budget_bytes"] == 6 * 1024 ** 3
    assert custom["custom_headroom_bytes"] == 4 * 1024 ** 3


def test_preferences_atomic_roundtrip_and_validation(tmp_path):
    got = P.write({"mode": "early", "custom_headroom_gb": 7.25,
                   "remember_overrides": False, "overridden_models": []}, tmp_path)
    assert P.read(tmp_path) == got
    assert (tmp_path / "data" / P.STORE_NAME).stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        P.write({"mode": "block", "custom_headroom_gb": 4,
                 "remember_overrides": True, "overridden_models": []}, tmp_path)
    with pytest.raises(ValueError):
        P.write({"mode": "custom", "custom_headroom_gb": -1,
                 "remember_overrides": True, "overridden_models": []}, tmp_path)


def test_override_acknowledgement_is_persistent_bounded_and_user_owned(tmp_path):
    P.acknowledge("first", tmp_path)
    assert not P.needs_confirmation("over", "first", P.read(tmp_path))
    assert P.needs_confirmation("over", "other", P.read(tmp_path))
    P.update({"remember_overrides": False}, tmp_path)
    assert P.read(tmp_path)["overridden_models"] == []
    P.acknowledge("ignored", tmp_path)
    assert P.read(tmp_path)["overridden_models"] == []


def test_preferences_refuse_symlink_destination(tmp_path):
    (tmp_path / "data").mkdir()
    outside = tmp_path / "outside"
    outside.write_text("sentinel")
    (tmp_path / "data" / P.STORE_NAME).symlink_to(outside)
    with pytest.raises(ValueError):
        P.write(P.DEFAULTS, tmp_path)
    assert outside.read_text() == "sentinel"
