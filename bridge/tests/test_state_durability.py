"""U61/U62 journeys: atomic live YAML and exact bridge-claim lifecycle."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
import yaml

from bridge import yamlfile
from bridge.core import singleton
from scripts.merge_manifest import merge_text


ROOT = Path(__file__).resolve().parents[2]


def test_yaml_noop_preserves_bytes_inode_and_mtime(tmp_path):
    target = tmp_path / "motdeck.yaml"
    target.write_text("# live\nrunner:\n  binary:\n")
    before = target.stat()
    yamlfile.transform_file(target, lambda text: text)
    after = target.stat()
    assert target.read_text() == "# live\nrunner:\n  binary:\n"
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_yaml_replace_failure_keeps_original_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "motdeck.yaml"
    target.write_text("runner:\n  model: old\n")
    monkeypatch.setattr(yamlfile.os, "replace",
                        lambda *_: (_ for _ in ()).throw(OSError("simulated replace failure")))
    with pytest.raises(OSError, match="simulated"):
        yamlfile.transform_file(target, lambda text: text.replace("old", "new"))
    assert target.read_text() == "runner:\n  model: old\n"
    assert not list(tmp_path.glob(".motdeck-yaml-*.tmp"))


@pytest.mark.parametrize("suffix", ["", ".lock"])
def test_yaml_state_and_lock_symlinks_never_touch_external_target(tmp_path, suffix):
    target = tmp_path / "motdeck.yaml"
    outside = tmp_path / "outside"
    outside.write_text("runner:\n  model: outside\n")
    if suffix:
        target.write_text("runner:\n  model: local\n")
        (tmp_path / f"motdeck.yaml{suffix}").symlink_to(outside)
    else:
        target.symlink_to(outside)
    with pytest.raises((OSError, ValueError)):
        yamlfile.transform_file(target, lambda text: text.replace("outside", "changed"))
    assert outside.read_text() == "runner:\n  model: outside\n"


def test_concurrent_threads_never_expose_partial_yaml(tmp_path):
    target = tmp_path / "motdeck.yaml"
    first = "# keep\nrunner:\n  model: alpha\naux:\n  model:\n"
    second = "# keep\nrunner:\n  model: beta\naux:\n  model:\n"
    target.write_text(first)
    stop = threading.Event()
    bad = []

    def reader():
        while not stop.is_set():
            observed = target.read_text()
            if observed not in (first, second):
                bad.append(observed)
                stop.set()
                return
            yaml.safe_load(observed)

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for index in range(500):
            expected = second if index % 2 == 0 else first
            yamlfile.transform_file(target, lambda _old, value=expected: value)
    finally:
        stop.set()
        thread.join(timeout=2)
    assert bad == []


def test_two_process_writers_retain_both_changes(tmp_path):
    target = tmp_path / "motdeck.yaml"
    target.write_text("# live\nrunner:\n  model: old\naux:\n  model: old\n")
    helper = str(ROOT / "bridge" / "yamlfile.py")
    code = r'''
import importlib.util, sys, time
spec=importlib.util.spec_from_file_location("yf", sys.argv[1]); yf=importlib.util.module_from_spec(spec); spec.loader.exec_module(yf)
path, old, new = sys.argv[2:]
def edit(text):
    time.sleep(.08)
    return text.replace(old, new)
yf.transform_file(path, edit)
'''
    one = subprocess.Popen([sys.executable, "-c", code, helper, str(target),
                            "runner:\n  model: old", "runner:\n  model: runner-new"])
    two = subprocess.Popen([sys.executable, "-c", code, helper, str(target),
                            "aux:\n  model: old", "aux:\n  model: aux-new"])
    assert one.wait(timeout=5) == 0
    assert two.wait(timeout=5) == 0
    text = target.read_text()
    assert "runner-new" in text and "aux-new" in text
    assert text.startswith("# live\n")


def test_manifest_merge_preserves_live_bytes_and_adds_only_missing_keys():
    source = ("runner:\n  binary:\ncomponents:\n  kept:\n    installed: false\n"
              "  added:\n    installed: true\n    enabled: true\nbuild:\n  node_pin: v24\n")
    live = ("# irreplaceable comment\nrunner:\n  binary:\ncomponents:\n  kept:\n"
            "    installed: true # live state\nbuild:\n  old_pin: retained\n")
    merged, added = merge_text(source, live)
    assert "# irreplaceable comment" in merged
    assert "installed: true # live state" in merged
    assert "  binary:\n" in merged and "binary: null" not in merged
    assert "components.added" in added and "build.node_pin" in added
    parsed = yaml.safe_load(merged)
    assert parsed["components"]["added"]["installed"] is False
    assert parsed["components"]["added"]["enabled"] is False


def test_manifest_merge_migrates_only_the_known_floating_searxng_default():
    pin = "9fea41204fdfa7a5cfa15b0ebd12904c520478ce"
    source = ("components:\n  searxng:\n    repo: https://github.com/searxng/searxng.git\n"
              f"    pin: {pin}  # exact source commit\n    installed: true\n"
              "runner:\n  model: repo-default\n")
    live = ("# live comment\ncomponents:\n  searxng:\n"
            "    repo: https://github.com/searxng/searxng.git\n"
            "    pin: main  # historical floating default\n"
            "    installed: true # machine state\nrunner:\n  model: user-choice\n")
    merged, changed = merge_text(source, live)
    assert f"    pin: {pin}  # exact source commit\n" in merged
    assert "installed: true # machine state" in merged
    assert "model: user-choice" in merged and "# live comment" in merged
    assert changed == [f"components.searxng.pin(main→{pin[:12]})"]

    again, changed_again = merge_text(source, merged)
    assert again == merged and changed_again == []

    custom = live.replace("pin: main", "pin: operator-branch")
    untouched, custom_changed = merge_text(source, custom)
    assert untouched == custom and custom_changed == []


def test_release_is_idempotent_and_never_deletes_replaced_claim(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    me = os.getpid()
    monkeypatch.setattr(singleton._ownership, "process_birth",
                        lambda pid: f"birth-{pid}")
    (data / "bridge.pid").write_text(f"{me}\n")
    (data / "bridge.owner").write_text(f"v1\t{me}\tbirth-{me}\n")
    assert singleton.release_claim(tmp_path, me) is True
    assert singleton.release_claim(tmp_path, me) is False

    newer = me + 1
    (data / "bridge.pid").write_text(f"{newer}\n")
    (data / "bridge.owner").write_text(f"v1\t{newer}\tbirth-{newer}\n")
    assert singleton.release_claim(tmp_path, me) is False
    assert (data / "bridge.pid").read_text() == f"{newer}\n"
    assert (data / "bridge.owner").exists()


def test_graceful_retire_never_deletes_a_replacement_claim(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(singleton._ownership, "process_birth",
                        lambda pid: f"birth-{pid}")
    (data / "worker.pid").write_text("202\n")
    (data / "worker.owner").write_text("v1\t202\tbirth-202\n")
    assert singleton._ownership.retire_owned(tmp_path, "worker", 101, "old") is False
    assert (data / "worker.pid").read_text() == "202\n"
    assert (data / "worker.owner").read_text() == "v1\t202\tbirth-202\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="M.O.T bridge lifecycle is macOS-only")
def test_real_scratch_uvicorn_sigterm_releases_both_claim_files(tmp_path):
    package = tmp_path / "bridge"
    core = package / "core"
    core.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (core / "__init__.py").write_text("")
    shutil.copy2(ROOT / "bridge" / "core" / "ownership.py", core / "ownership.py")
    shutil.copy2(ROOT / "bridge" / "core" / "singleton.py", core / "singleton.py")
    (package / "app.py").write_text(
        "import os\nfrom pathlib import Path\nfrom fastapi import FastAPI\n"
        "from .core import singleton\nROOT=Path(__file__).resolve().parents[1]\n"
        "singleton.claim_or_exit(ROOT)\napp=FastAPI()\n"
        "app.router.on_shutdown.append(lambda: singleton.release_claim(ROOT, os.getpid()))\n"
        "@app.get('/ok')\ndef ok(): return {'ok': True}\n")

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bridge.app:app", "--host", "127.0.0.1",
         "--port", str(port), "--timeout-graceful-shutdown", "2"], cwd=tmp_path,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    data = tmp_path / "data"
    data.mkdir()
    try:
        for _ in range(40):
            birth = singleton._ownership.process_birth(proc.pid)
            if birth:
                break
            time.sleep(.02)
        assert birth
        (data / "bridge.owner").write_text(f"v1\t{proc.pid}\t{birth}\n")
        (data / "bridge.pid").write_text(f"{proc.pid}\n")
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ok", timeout=.2) as reply:
                    if reply.status == 200:
                        break
            except OSError:
                time.sleep(.05)
        else:
            pytest.fail("scratch bridge did not listen:\n" + (proc.stdout.read() or ""))
        time.sleep(.25)
        os.kill(proc.pid, signal.SIGTERM)  # exact child handle created by this test
        rc = proc.wait(timeout=6)
        output = proc.stdout.read() or ""
        assert rc in (0, -signal.SIGTERM), f"scratch bridge rc={rc}:\n{output}"
        assert "Application shutdown complete" in output
        assert not (data / "bridge.pid").exists()
        assert not (data / "bridge.owner").exists()
    finally:
        if proc.poll() is None:
            os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
