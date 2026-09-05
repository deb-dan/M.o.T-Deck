"""U74 recovery hardening — fixture-only lifecycle seams, never live components.

Run:
    data/bridge-venv/bin/python -m pytest bridge/tests/test_u74_recovery_hardening.py -q
"""
import os
import shutil
import stat
import subprocess
import sys

import yaml  # noqa: F401 -- this interpreter is the resolver's known-good candidate


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
START = os.path.join(ROOT, "scripts", "start_component.sh")
SHIP = os.path.join(ROOT, "scripts", "ship.sh")


def _run_start(*args, cwd=ROOT, env=None):
    return subprocess.run(["bash", START, *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=30)


def test_scalar_normalizer_handles_yaml_null_spellings_byte_for_byte():
    for raw in ("", "   \t", "~", "null", "Null", "NULL", "''", '\"\"'):
        got = _run_start("--normalize-yaml-scalar", raw)
        assert got.returncode == 0, got.stderr
        assert got.stdout == ""
    for raw in ("Qwen3.5-9B", "/Applications/LM Studio/llama-server", "'null'", '\"null\"'):
        got = _run_start("--normalize-yaml-scalar", raw)
        assert got.returncode == 0, got.stderr
        assert got.stdout == raw


def _runner_fixture(tmp_path, model):
    root = tmp_path / "fixture"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(START, root / "scripts" / "start_component.sh")
    (root / "bridge" / "core").mkdir(parents=True)
    shutil.copy2(os.path.join(ROOT, "bridge", "core", "modelreg.py"),
                 root / "bridge" / "core" / "modelreg.py")
    (root / "data" / "logs").mkdir(parents=True)
    (root / "data" / "fake.gguf").write_bytes(b"fixture")
    (root / "data" / "models.json").write_text(
        '{"models": [{"id": "fixture-model", "path": "data/fake.gguf", "format": "gguf"}]}')
    foreign = (root / "home" / "Library" / "Application Support" / "Jan" / "data"
               / "llamacpp" / "backends" / "fixture" / "macos-arm64" / "build" / "bin")
    foreign.mkdir(parents=True)
    server = foreign / "llama-server"
    server.write_text("#!/bin/sh\necho 'llama.cpp build 0'\n")
    server.chmod(server.stat().st_mode | stat.S_IXUSR)
    (root / "harness.yaml").write_text(
        "runner:\n"
        "  adapter: llamacpp\n"
        "  port: 6767\n"
        "  api_key: fixture-key\n"
        "  ctx_size: 4096\n"
        f"  model: {model}\n"
        "  binary: null\n")
    home = root / "home"
    return root, dict(os.environ, HOME=str(home))


def test_runner_binary_null_uses_auto_discovery_not_literal_path(tmp_path):
    root, env = _runner_fixture(tmp_path, "fixture-model")
    got = subprocess.run(["bash", "scripts/start_component.sh", "runner"], cwd=root,
                         env=env, capture_output=True, text=True, timeout=30)
    assert got.returncode != 0
    assert "runner.binary is not executable: null" not in got.stdout + got.stderr
    assert "refusing to start the runner on Jan's llama-server" in got.stdout


def test_runner_model_null_refuses_as_unset_not_model_named_null(tmp_path):
    root, env = _runner_fixture(tmp_path, "null")
    got = subprocess.run(["bash", "scripts/start_component.sh", "runner"], cwd=root,
                         env=env, capture_output=True, text=True, timeout=30)
    assert got.returncode != 0
    assert "runner.model not set in harness.yaml" in got.stdout
    assert "model 'null'" not in got.stdout + got.stderr


def test_yaml_python_resolver_skips_bad_candidate_and_preserves_spaced_path(tmp_path):
    bad = tmp_path / "python without yaml"
    bad.write_text("#!/bin/sh\nexit 1\n")
    bad.chmod(bad.stat().st_mode | stat.S_IXUSR)
    good_dir = tmp_path / "python with yaml"
    good_dir.mkdir()
    good = good_dir / "python"
    good.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
    good.chmod(good.stat().st_mode | stat.S_IXUSR)

    got = _run_start("--yaml-python", str(bad), str(good))
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == str(good)

    none = _run_start("--yaml-python", str(bad))
    assert none.returncode == 1
    assert "no Python interpreter able to import PyYAML" in none.stderr


def test_yaml_seeders_share_one_resolver_while_odysseus_keeps_its_venv_python():
    src = open(START, encoding="utf-8").read()
    deepseek = src[src.index("\n  deepseek)"):src.index("\n  opencode)")]
    hermes = src[src.index("\n  hermes)"):]
    assert 'DS_PY="$(_yaml_python || true)"' in deepseek
    assert 'H_PY="$(_yaml_python || true)"' in hermes
    assert '"$DS_PY" scripts/seed_deepseek_config.py' in deepseek
    assert '"$H_PY" scripts/seed_hermes_provider.py' in hermes
    assert "python3 scripts/seed_hermes_provider.py" not in hermes
    assert 'python "$ROOT/scripts/seed_odysseus_jan.py"' in src


def test_ship_green_health_is_control_api_only_and_failure_precedes_app_open():
    src = open(SHIP, encoding="utf-8").read()
    wait = src[src.index('SHIP_WAIT_S=90'):src.index('open "$APP"', src.index('SHIP_WAIT_S=90'))]
    assert 'http://127.0.0.1:8700/api/status' in wait
    assert 'http://127.0.0.1:8700/status' not in wait
    assert 'http://127.0.0.1:8700/"' not in wait
    assert 'if [[ "$UP" -ne 1 ]]' in wait
    assert "BRIDGE CONTROL API DID NOT ANSWER GET /api/status" in wait
