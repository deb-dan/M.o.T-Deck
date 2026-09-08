from pathlib import Path
import inspect
import os

from fastapi.testclient import TestClient
import pytest

from bridge import app as facade
from bridge.core import storageops as S
from bridge.routers import storage as R


client = TestClient(facade.app)


def test_broad_reset_preview_never_recursively_sizes_the_live_support_root():
    source = inspect.getsource(R._reset_plan)
    assert "_tree_bytes(ROOT)" not in source
    assert '"bytes": None' in source
    assert '"size_note"' in source


def _manifest(root: Path, installed: str = "true") -> None:
    (root / "motdeck.yaml").write_text(
        "components:\n"
        "  opencode:\n"
        "    pin: v1\n"
        f"    installed: {installed}  # keep this comment\n"
        "    enabled: false\n"
        "  deepseek:\n"
        "    installed: true\n",
        encoding="utf-8")


def test_runtime_plan_is_exact_and_preserves_user_state(tmp_path):
    root = tmp_path / "MOT Deck"
    runtime = root / "data/opencode/bin/opencode"
    state = root / "data/opencode/xdg/session.json"
    workspace = root / "data/opencode-workspace/project.txt"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"runtime")
    state.parent.mkdir(parents=True)
    state.write_text("state")
    workspace.parent.mkdir(parents=True)
    workspace.write_text("user")
    _manifest(root)

    plan = S.runtime_plan(root, "opencode")
    assert [row["path"] for row in plan["paths"]] == [str(runtime)]
    assert plan["bytes"] == len(b"runtime")
    assert "data/opencode/xdg" in plan["preserve"]
    assert "data/opencode-workspace" in plan["preserve"]

    trash = tmp_path / "Trash"
    trash.mkdir()
    result = S.apply_runtime_plan(root, plan, trash_root=trash)
    assert result["moved"] == 1 and result["space_reclaimed"] is False
    assert not runtime.exists()
    assert state.read_text() == "state"
    assert workspace.read_text() == "user"
    text = (root / "motdeck.yaml").read_text()
    assert "installed: false  # keep this comment" in text
    assert "deepseek:\n    installed: true" in text
    moved = list(Path(result["trash"]).iterdir())
    assert len(moved) == 1 and moved[0].read_bytes() == b"runtime"


def test_optional_source_checkout_is_preserved_when_ownership_is_not_file_manifested(tmp_path):
    root = tmp_path / "root"
    venv = root / "data/voicestudio-venv"
    source = root / "vendor/voicestudio"
    venv.mkdir(parents=True)
    source.mkdir(parents=True)
    (venv / "python").write_text("runtime")
    (source / "backend.py").write_text("pinned upstream source")
    plan = S.runtime_plan(root, "voicestudio")
    assert [row["path"] for row in plan["paths"]] == [str(venv)]
    assert "vendor/voicestudio source/build tree" in plan["preserve"]
    assert not any(row["path"] == str(source) for row in plan["paths"])


def test_stale_preview_is_refused_without_moving_anything(tmp_path):
    root = tmp_path / "root"
    runtime = root / "data/deepseek/npm"
    runtime.mkdir(parents=True)
    (runtime / "package-lock.json").write_text("one")
    _manifest(root)
    plan = S.runtime_plan(root, "deepseek")
    (runtime / "package-lock.json").write_text("changed")
    trash = tmp_path / "Trash"
    trash.mkdir()
    with pytest.raises(S.StorageRefusal, match="changed after preview"):
        S.apply_runtime_plan(root, plan, trash_root=trash)
    assert runtime.is_dir()
    assert not list(trash.iterdir())


def test_stale_runtime_preview_is_refused_before_component_stop(tmp_path, monkeypatch):
    root = tmp_path / "root"
    runtime = root / "data/opencode/bin/opencode"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("one")
    _manifest(root)
    monkeypatch.setattr(R, "ROOT", root)
    stopped = []
    monkeypatch.setattr(R, "_stop_for_runtime",
                        lambda target, component: stopped.append((target, component)))
    preview = client.post("/api/storage/runtime/plan", json={"target": "opencode"}).json()
    runtime.write_text("changed after the user reviewed it")
    result = client.post("/api/storage/runtime/apply", json={"token": preview["token"]})
    assert result.status_code == 409
    assert "changed after preview" in result.json()["error"]
    assert stopped == []


def test_partial_move_failure_rolls_back_prior_target(tmp_path, monkeypatch):
    root = tmp_path / "root"
    first = root / "data/goose/ui"
    second = root / "data/goose/ui.sha256"
    first.mkdir(parents=True)
    (first / "index.html").write_text("ui")
    second.write_text("hash")
    plan = S.runtime_plan(root, "gooseui")
    trash = tmp_path / "Trash"
    trash.mkdir()
    real_replace = os.replace
    calls = 0

    def fail_second(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected move failure")
        return real_replace(src, dst)

    monkeypatch.setattr(S.os, "replace", fail_second)
    with pytest.raises(OSError, match="injected"):
        S.apply_runtime_plan(root, plan, trash_root=trash)
    assert first.is_dir() and (first / "index.html").read_text() == "ui"
    assert second.read_text() == "hash"


def test_goose_cli_refuses_while_goose_ui_depends_on_binary(tmp_path):
    root = tmp_path / "root"
    (root / "data/goose/bin").mkdir(parents=True)
    (root / "data/goose/bin/goose").write_text("bin")
    (root / "data/goose/ui").mkdir(parents=True)
    with pytest.raises(S.StorageRefusal, match="remove Goose UI first"):
        S.runtime_plan(root, "goose")


def test_runtime_target_root_symlink_is_moved_as_link_not_followed(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    target = root / "data/acestep"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    plan = S.runtime_plan(root, "acestep")
    assert plan["paths"][0]["kind"] == "symlink"
    trash = tmp_path / "Trash"
    trash.mkdir()
    result = S.apply_runtime_plan(root, plan, trash_root=trash)
    assert not os.path.lexists(target)
    assert (outside / "keep.txt").read_text() == "keep"
    moved = next(Path(result["trash"]).iterdir())
    assert moved.is_symlink()


def test_manifest_update_refuses_unknown_component(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _manifest(root)
    before = (root / "motdeck.yaml").read_text()
    with pytest.raises(S.StorageRefusal, match="no components.missing"):
        S.set_manifest_installed(root / "motdeck.yaml", "missing", False)
    assert (root / "motdeck.yaml").read_text() == before


def test_artifact_plan_accepts_exact_children_and_preserves_siblings(tmp_path):
    models = tmp_path / "comfy" / "models"
    chosen = models / "checkpoints" / "chosen.safetensors"
    sibling = models / "checkpoints" / "user.safetensors"
    chosen.parent.mkdir(parents=True)
    chosen.write_bytes(b"chosen")
    sibling.write_bytes(b"user")
    plan = S.artifact_plan(
        "remove-generate-assets", "workflow:test", "Test workflow files", (chosen,),
        owned_roots=(models,), preserve=("user workflows",),
        impact=({"file": "checkpoints/chosen.safetensors", "shared": False},),
    )
    trash = tmp_path / "Trash"
    trash.mkdir()
    result = S.apply_artifact_plan(plan, trash_root=trash)
    assert result["moved"] == 1
    assert not chosen.exists()
    assert sibling.read_bytes() == b"user"
    assert result["impact"][0]["shared"] is False


def test_artifact_plan_refuses_owned_root_and_escape(tmp_path):
    models = tmp_path / "comfy" / "models"
    models.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(S.StorageRefusal, match="outside every owned root"):
        S.artifact_plan("remove", "x", "x", (outside,), owned_roots=(models,))
    with pytest.raises(S.StorageRefusal, match="root itself"):
        S.artifact_plan("remove", "x", "x", (models,), owned_roots=(models,))


def test_artifact_symlink_is_moved_without_following_destination(tmp_path):
    cache = tmp_path / "hub"
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("yes")
    link = cache / "models--org--model"
    link.symlink_to(outside, target_is_directory=True)
    plan = S.artifact_plan("remove-music-assets", "minimax", "MiniMax", (link,),
                           owned_roots=(cache,))
    trash = tmp_path / "Trash"
    trash.mkdir()
    S.apply_artifact_plan(plan, trash_root=trash)
    assert not os.path.lexists(link)
    assert (outside / "keep").read_text() == "yes"


def test_generate_workflow_plan_names_every_shared_file_consumer(tmp_path, monkeypatch):
    from bridge.core import comfycur
    base = tmp_path / "comfy-models"
    file = base / "diffusion_models/shared.safetensors"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"model")
    monkeypatch.setattr(comfycur, "models_dir", lambda: str(base))
    shared = {"name": file.name, "directory": "diffusion_models", "present": True}
    cat = {"models": [
        {"id": "one", "title": "One", "workflows": [
            {"id": "w1", "title": "Text", "files": [shared]}]},
        {"id": "two", "title": "Two", "workflows": [
            {"id": "w2", "title": "Image", "files": [shared]}]},
    ]}
    plan = R._generate_asset_plan(cat, "workflow", "w1")
    assert [row["path"] for row in plan["paths"]] == [str(file)]
    assert plan["impact"][0]["shared"] is True
    assert {row["workflow_id"] for row in plan["impact"][0]["workflows"]} == {"w1", "w2"}
    assert "workflow catalogue metadata" in " ".join(plan["preserve"])


def test_generate_model_plan_removes_present_files_only_and_never_the_model_root(tmp_path, monkeypatch):
    from bridge.core import comfycur
    base = tmp_path / "models"
    present = base / "checkpoints/present.safetensors"
    present.parent.mkdir(parents=True)
    present.write_bytes(b"present")
    monkeypatch.setattr(comfycur, "models_dir", lambda: str(base))
    cat = {"models": [{"id": "m", "title": "Model", "workflows": [{"id": "w",
        "files": [{"name": present.name, "directory": "checkpoints", "present": True},
                  {"name": "missing.vae", "directory": "vae", "present": False}]}]}]}
    plan = R._generate_asset_plan(cat, "model", "m")
    assert [row["path"] for row in plan["paths"]] == [str(present)]
    assert str(base) not in [row["path"] for row in plan["paths"]]


def test_generate_plan_refuses_a_workflow_with_no_downloaded_files(tmp_path, monkeypatch):
    from bridge.core import comfycur
    base = tmp_path / "models"
    base.mkdir()
    monkeypatch.setattr(comfycur, "models_dir", lambda: str(base))
    cat = {"models": [{"id": "m", "title": "Model", "workflows": [{"id": "w",
        "files": [{"name": "missing.safetensors", "directory": "checkpoints",
                   "present": False}]}]}]}
    with pytest.raises(S.StorageRefusal, match="no downloaded files"):
        R._generate_asset_plan(cat, "workflow", "w")


def test_runtime_parent_link_cannot_grant_ownership_of_standalone_binary(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "standalone"
    (root / "data").mkdir(parents=True)
    (outside / "bin").mkdir(parents=True)
    binary = outside / "bin/opencode"
    binary.write_bytes(b"standalone binary")
    (root / "data/opencode").symlink_to(outside, target_is_directory=True)
    with pytest.raises(S.StorageRefusal, match="symbolic link"):
        S.runtime_plan(root, "opencode")
    assert binary.read_bytes() == b"standalone binary"


def test_artifact_parent_link_cannot_grant_ownership_of_external_models(tmp_path):
    models, outside = tmp_path / "models", tmp_path / "other-manager"
    models.mkdir()
    outside.mkdir()
    model = outside / "chosen.safetensors"
    model.write_bytes(b"external model")
    (models / "checkpoints").symlink_to(outside, target_is_directory=True)
    with pytest.raises(S.StorageRefusal, match="symbolic link"):
        S.artifact_plan("remove", "x", "x", (models / "checkpoints" / model.name,),
                        owned_roots=(models,))
    assert model.read_bytes() == b"external model"


def test_parent_replaced_by_link_after_preview_is_refused_before_stop(tmp_path, monkeypatch):
    root = tmp_path / "root"
    parent = root / "data/opencode"
    binary = parent / "bin/opencode"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"runtime")
    _manifest(root)
    monkeypatch.setattr(R, "ROOT", root)
    stopped = []
    monkeypatch.setattr(R, "_stop_for_runtime", lambda *args: stopped.append(args))
    token = client.post("/api/storage/runtime/plan", json={"target": "opencode"}).json()["token"]
    outside = tmp_path / "moved-to-standalone"
    parent.rename(outside)
    parent.symlink_to(outside, target_is_directory=True)
    result = client.post("/api/storage/runtime/apply", json={"token": token})
    assert result.status_code == 409
    assert stopped == []
    assert (outside / "bin/opencode").read_bytes() == b"runtime"


def test_rollback_retains_recovery_bytes_and_does_not_overwrite_a_new_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    first = root / "data/goose/ui.sha256"
    second = root / "data/goose/UI-SOURCES.txt"
    first.parent.mkdir(parents=True)
    first.write_text("old digest")
    second.write_text("sources")
    plan = S.runtime_plan(root, "gooseui")
    trash = tmp_path / "Trash"
    trash.mkdir()
    real_replace = os.replace

    def fail_second(src, dst):
        if Path(src) == second:
            first.write_text("new user file")
            raise OSError("injected second move failure")
        return real_replace(src, dst)

    monkeypatch.setattr(S.os, "replace", fail_second)
    with pytest.raises(S.StorageRefusal, match="rollback incomplete") as error:
        S.apply_runtime_plan(root, plan, trash_root=trash)
    assert first.read_text() == "new user file"
    assert second.read_text() == "sources"
    batch = next(trash.iterdir())
    assert str(batch) in str(error.value)
    assert next(batch.iterdir()).read_text() == "old digest"


def test_slow_preview_inventory_does_not_block_other_bridge_requests(monkeypatch):
    import asyncio
    import threading

    async def journey():
        inventory_entered = threading.Event()
        allow_inventory = threading.Event()

        def slow_plan(root, target):
            inventory_entered.set()
            # Bounded even on the unfixed implementation, so the regression cannot
            # hang pytest. Another request must run while inventory is still waiting.
            allow_inventory.wait(1)
            return {"operation": "uninstall-runtime", "target": target}

        class Request:
            async def json(self):
                return {"target": "opencode"}

        monkeypatch.setattr(R, "runtime_plan", slow_plan)
        task = asyncio.create_task(R.storage_runtime_plan(Request()))
        while not inventory_entered.is_set():
            await asyncio.sleep(0)
        try:
            assert not task.done(), "inventory blocked the event loop until it finished"
            # This handler is the same simple async read needed by SSE/turn controls.
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            allow_inventory.set()
            response = await task
            assert response.status_code == 200

    asyncio.run(journey())
