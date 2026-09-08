import time

import pytest

from bridge.core.storageops import StorageRefusal
from bridge.routers import storage as S


@pytest.fixture(autouse=True)
def _clean_job():
    with S._OPTIONAL_LOCK:
        S._OPTIONAL_JOB.clear()
        S._OPTIONAL_JOB.update({"running": False, "queue": [], "receipts": [], "current": ""})
    yield
    with S._OPTIONAL_LOCK:
        S._OPTIONAL_JOB["running"] = False


def test_selection_is_allowlisted_dependency_ordered_and_skips_installed(monkeypatch):
    installed = {"opencode"}
    monkeypatch.setattr(S, "_option_installed", lambda key: key in installed)
    assert S._expand_optional_selection(["gooseui", "opencode", "aider"]) == [
        "goose", "gooseui", "aider"]
    with pytest.raises(StorageRefusal, match="unknown optional"):
        S._expand_optional_selection(["../../outside"])
    with pytest.raises(StorageRefusal, match="select at least one"):
        S._expand_optional_selection([])


def test_worker_runs_sequentially_and_keeps_per_item_receipts(monkeypatch):
    seen = []

    def install(key):
        seen.append(key)
        return {"id": key, "label": key, "ok": key != "voicebox",
                "returncode": 0 if key != "voicebox" else 1,
                "seconds": 0.01, "installed": key != "voicebox", "tail": "evidence"}

    monkeypatch.setattr(S, "_install_one", install)
    job_id = "job-test"
    with S._OPTIONAL_LOCK:
        S._OPTIONAL_JOB.clear()
        S._OPTIONAL_JOB.update({"id": job_id, "running": True,
                                "queue": ["voicestudio", "voicebox", "aider"],
                                "receipts": [], "current": "", "completed": 0})
    S._optional_worker(job_id, ["voicestudio", "voicebox", "aider"])
    snap = S._optional_snapshot()
    assert seen == ["voicestudio", "voicebox", "aider"]
    assert snap["running"] is False and snap["completed"] == 3
    assert [row["ok"] for row in snap["receipts"]] == [True, False, True]
    assert snap["finished_at"] <= time.time()


def test_installer_receipt_is_bounded_and_uses_existing_script_runner(monkeypatch):
    class Result:
        returncode = 0
        stdout = "x" * 6000
        stderr = ""

    calls = []
    from bridge.core import procs
    monkeypatch.setattr(procs, "_script", lambda name, *args, timeout: (
        calls.append((name, args, timeout)) or Result()))
    monkeypatch.setattr(S, "_option_installed", lambda key: True)
    receipt = S._install_one("opencode")
    assert calls == [("install_opencode.sh", (), 1800)]
    assert receipt["ok"] is True and receipt["installed"] is True
    assert len(receipt["tail"]) == 4000


def test_zero_exit_without_the_disk_contract_is_not_reported_as_success(monkeypatch):
    class Result:
        returncode = 0
        stdout = "claimed success"
        stderr = ""

    from bridge.core import procs
    monkeypatch.setattr(procs, "_script", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(S, "_option_installed", lambda _key: False)
    receipt = S._install_one("opencode")
    assert receipt["ok"] is False and receipt["installed"] is False
    assert "on-disk install contract is still incomplete" in receipt["tail"]
