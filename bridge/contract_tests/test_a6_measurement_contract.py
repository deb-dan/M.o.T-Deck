"""Executable contracts for the A6 instrument and the model-eject seam it exercises."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

from bridge.routers import models


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "measure_fit_real.py"


def _load_measurement_module():
    spec = importlib.util.spec_from_file_location("motdeck_measure_fit_real", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eject_waits_for_the_owned_runner_then_clears_state(monkeypatch):
    """Reproduce the v1.5.87 NameError instead of merely checking an import string."""
    alive = iter((True, False, False))
    calls: list[tuple] = []
    monkeypatch.setattr(models, "cfg", lambda: {"runner": {"port": 6767}})
    monkeypatch.setattr(models, "stop_owned_component",
                        lambda *a, **k: calls.append((a, k)) or [])
    monkeypatch.setattr(models, "_port_alive_sync", lambda _port: next(alive))
    monkeypatch.setattr(models.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(models, "_clear_expected", lambda name: calls.append((name,)))
    monkeypatch.setattr(models, "_set_runner_model", lambda value: calls.append(("pin", value)))
    monkeypatch.setattr(models, "publish", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(models, "PROV", {"runner": {"pid": 123}})

    assert models._eject_runner() == []
    assert (("runner", 6767), {"force": True}) in calls
    assert ("pin", "") in calls
    assert "runner" not in models.PROV


def test_measurement_refuses_an_occupied_port_and_never_stops_it(monkeypatch, tmp_path):
    measurement = _load_measurement_module()
    monkeypatch.setattr(measurement, "_port_is_free", lambda _port: False)
    monkeypatch.setattr(measurement.subprocess, "Popen",
                        lambda *_a, **_k: pytest.fail("occupied port must prevent spawn"))
    args = argparse.Namespace(port=6799)
    with pytest.raises(RuntimeError, match="already occupied; nothing was stopped"):
        measurement.measure(args)


def test_measurement_uses_the_real_engine_specific_wire_identity():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'wire_model = str(model) if args.engine == "mlx" else args.model_id' in text
    assert '"wire_model_shape"' in text
    assert 'os.killpg(process.pid, signal.SIGTERM)' in text
    assert 'os.killpg(process.pid, signal.SIGKILL)' in text
    assert 'start_new_session=True' in text
    assert 'os.replace(temporary, destination)' in text
