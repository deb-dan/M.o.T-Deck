"""U89: every models.json producer uses one durable transaction writer."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bridge.core import modelreg
from bridge.routers import downloads
from bridge.routers import models as models_router
from bridge.tests.model_fixture import gguf_bytes


ROOT = Path(__file__).resolve().parents[2]


def test_registry_writer_failure_preserves_original_and_cleans_temp(tmp_path, monkeypatch):
    registry = tmp_path / "models.json"
    registry.write_text('{"models":[{"id":"old"}]}\n')
    monkeypatch.setattr(modelreg.os, "replace",
                        lambda *_: (_ for _ in ()).throw(OSError("simulated replace failure")))
    with pytest.raises(OSError, match="simulated"):
        modelreg.write_registry(str(registry), {"models": [{"id": "new"}]})
    assert registry.read_text() == '{"models":[{"id":"old"}]}\n'
    assert not list(tmp_path.glob(".models-*.tmp"))


@pytest.mark.parametrize("suffix", ["", ".lock"])
def test_registry_and_lock_symlinks_never_touch_external_target(tmp_path, suffix):
    registry = tmp_path / "models.json"
    outside = tmp_path / "outside.json"
    outside.write_text('{"models":[{"id":"outside"}]}\n')
    if suffix:
        registry.write_text('{"models":[]}\n')
        (tmp_path / f"models.json{suffix}").symlink_to(outside)
    else:
        registry.symlink_to(outside)
    with pytest.raises((OSError, ValueError)):
        modelreg.write_registry(str(registry), {"models": [{"id": "changed"}]})
    assert outside.read_text() == '{"models":[{"id":"outside"}]}\n'


def test_real_seed_and_download_writer_do_not_lose_each_other(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "models").mkdir(parents=True)
    registry = data / "models.json"
    registry.write_text(json.dumps({"models": []}) + "\n")
    jan_path = data / "models" / "jan" / "model.gguf"
    jan_path.parent.mkdir()
    jan_path.write_bytes(gguf_bytes())
    download_path = tmp_path / "download.gguf"
    download_path.write_bytes(gguf_bytes())
    downloaded = {"id": "download", "format": "gguf", "path": str(download_path),
                  "source": "download"}
    # Run the actual standalone seeder in another process, with the same module
    # layout it has in the app. This matters: POSIX flock is process-scoped, while
    # synthetic same-process copies of modelreg would not test the production seam.
    (tmp_path / "scripts").mkdir()
    (tmp_path / "bridge" / "core").mkdir(parents=True)
    for relative in ("scripts/seed_registry.py", "scripts/model_sources.py",
                     "bridge/core/modelreg.py", "bridge/modeltools.py"):
        destination = tmp_path / relative
        shutil.copy2(ROOT / relative, destination)
    monkeypatch.setattr(downloads, "ROOT", tmp_path)
    env = dict(os.environ, HARNESS_JAN_MODELS_DIR=str(tmp_path / "no-jan"),
               HARNESS_LMSTUDIO_DIR=str(tmp_path / "no-lms"))
    process = subprocess.Popen([sys.executable, "scripts/seed_registry.py"], cwd=tmp_path,
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    downloads._registry_add(downloaded)
    out, err = process.communicate(timeout=10)
    assert process.returncode == 0, out + err
    saved = json.loads(registry.read_text())
    assert {row["id"] for row in saved["models"]} == {"jan", "download"}
    assert registry.read_text().endswith("\n")
    assert not list(data.glob(".models-*.tmp"))


def test_real_absent_writer_uses_the_same_durable_transaction(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    registry = data / "models.json"
    registry.write_text(json.dumps({"models": [{
        "id": "gone", "format": "gguf", "path": "/missing/model.gguf",
    }]}) + "\n")
    monkeypatch.setattr(models_router, "ROOT", tmp_path)
    monkeypatch.setattr(models_router, "artifact_probe",
                        lambda row: {"state": "missing"})
    monkeypatch.setattr(models_router, "source_availability",
                        lambda row, probe: {"state": "available"})

    models_router._persist_absent({"gone": "gone"})

    saved = json.loads(registry.read_text())
    assert saved["models"][0][modelreg.ABSENT_KEY] is True
    assert registry.read_text().endswith("\n")
    assert not list(data.glob(".models-*.tmp"))


def _child(code: str, *args: object) -> subprocess.Popen:
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.Popen(
        [sys.executable, "-c", code, *(str(arg) for arg in args)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _finish(*children: subprocess.Popen) -> None:
    failures = []
    for child in children:
        out, err = child.communicate(timeout=15)
        if child.returncode:
            failures.append(out + err)
    assert not failures, "\n".join(failures)


def test_delete_and_download_transactions_cannot_lose_each_other(tmp_path):
    """Exercise two real writer families in separate processes behind one held lock."""
    data = tmp_path / "data"
    target = data / "models" / "old"
    target.mkdir(parents=True)
    artifact = target / "model.gguf"
    artifact.write_bytes(gguf_bytes())
    registry = data / "models.json"
    registry.write_text(json.dumps({"models": [{
        "id": "old", "format": "gguf", "path": str(artifact), "source": "download",
    }]}) + "\n")
    downloaded = {"id": "new", "format": "gguf", "path": str(tmp_path / "new.gguf"),
                  "source": "download"}

    delete_code = """
import sys
from pathlib import Path
from bridge.core.modeldelete import delete_owned_model_transaction
error = delete_owned_model_transaction(root=Path(sys.argv[1]), mid='old',
    expected_target=sys.argv[2], assignments=[])
raise SystemExit(error or 0)
"""
    download_code = """
import json, sys
from pathlib import Path
from bridge.routers import downloads
downloads.ROOT = Path(sys.argv[1])
downloads._registry_add(json.loads(sys.argv[2]))
"""
    # Holding the production lock ensures both children reach the same contention
    # point before either transaction can commit. The kernel may choose either order.
    with modelreg.registry_lock(str(registry)):
        deleting = _child(delete_code, tmp_path, target)
        adding = _child(download_code, tmp_path, json.dumps(downloaded))
    _finish(deleting, adding)

    saved = json.loads(registry.read_text())
    assert {row["id"] for row in saved["models"]} == {"new"}
    assert not target.exists()
    assert not list(data.glob(".models-*.tmp"))


def test_absent_and_download_transactions_cannot_lose_each_other(tmp_path):
    """A polled absent transition cannot overwrite a simultaneous new download."""
    data = tmp_path / "data"
    data.mkdir()
    registry = data / "models.json"
    registry.write_text(json.dumps({"models": [{
        "id": "gone", "format": "gguf", "path": "/missing/model.gguf",
    }]}) + "\n")
    downloaded = {"id": "new", "format": "gguf", "path": str(tmp_path / "new.gguf"),
                  "source": "download"}
    absent_code = """
import sys
from pathlib import Path
from bridge.routers import models
models.ROOT = Path(sys.argv[1])
models.artifact_probe = lambda row: {'state': 'missing'}
models.source_availability = lambda row, probe: {'state': 'available'}
models._persist_absent({'gone': 'gone'})
"""
    download_code = """
import json, sys
from pathlib import Path
from bridge.routers import downloads
downloads.ROOT = Path(sys.argv[1])
downloads._registry_add(json.loads(sys.argv[2]))
"""
    with modelreg.registry_lock(str(registry)):
        marking = _child(absent_code, tmp_path)
        adding = _child(download_code, tmp_path, json.dumps(downloaded))
    _finish(marking, adding)

    saved = {row["id"]: row for row in json.loads(registry.read_text())["models"]}
    assert set(saved) == {"gone", "new"}
    assert saved["gone"][modelreg.ABSENT_KEY] is True
    assert not list(data.glob(".models-*.tmp"))


def test_all_production_registry_writers_delegate_to_shared_writer():
    locations = [
        ROOT / "scripts" / "seed_registry.py",
        ROOT / "bridge" / "routers" / "downloads.py",
        ROOT / "bridge" / "routers" / "models.py",
        ROOT / "bridge" / "core" / "modeldelete.py",
    ]
    for path in locations:
        text = path.read_text()
        assert "write_registry" in text, f"{path.name} bypasses the shared durable writer"
        assert ".harness-tmp" not in text and 'with_suffix(".json.tmp")' not in text
