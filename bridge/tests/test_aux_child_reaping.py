"""U65: every directly spawned Aux child is retained and reaped exactly once."""
from __future__ import annotations

import subprocess
import sys
import threading

from bridge.core import ownership
from bridge import pty_aider
from bridge.routers import aux


def test_aux_waiter_reaps_child_and_retires_only_its_exact_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(aux, "ROOT", tmp_path)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    pid, birth = ownership.record_child(tmp_path, "aux", child.pid)
    aux._AUX_PROC, aux._AUX_BIRTH = child, birth

    waiter = threading.Thread(target=aux._reap_aux_child, args=(child, birth))
    waiter.start()
    waiter.join(timeout=5)

    assert not waiter.is_alive()
    assert child.returncode == 0, "wait() did not reap the exact child"
    assert ownership.read_claim(tmp_path, "aux") is None
    assert not (tmp_path / "data" / "aux.pid").exists()
    assert aux._AUX_PROC is None and aux._AUX_BIRTH == ""
    assert pid == child.pid


def test_old_waiter_cannot_clear_a_replacement_handle(tmp_path, monkeypatch):
    monkeypatch.setattr(aux, "ROOT", tmp_path)
    old = subprocess.Popen([sys.executable, "-c", "pass"])
    _, old_birth = ownership.record_child(tmp_path, "aux", old.pid)
    old.wait(timeout=5)
    ownership.retire_owned(tmp_path, "aux", old.pid, old_birth)

    replacement = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _, replacement_birth = ownership.record_child(tmp_path, "aux", replacement.pid)
        aux._AUX_PROC, aux._AUX_BIRTH = replacement, replacement_birth
        aux._reap_aux_child(old, old_birth)

        assert aux._AUX_PROC is replacement
        assert aux._AUX_BIRTH == replacement_birth
        assert ownership.read_claim(tmp_path, "aux") == (
            replacement.pid, replacement_birth)
    finally:
        replacement.terminate()
        replacement.wait(timeout=5)
        ownership.retire_owned(tmp_path, "aux", replacement.pid, replacement_birth)
        aux._AUX_PROC, aux._AUX_BIRTH = None, ""


def test_shared_pty_forced_kill_is_reaped_not_left_as_a_zombie():
    child = subprocess.Popen(
        [sys.executable, "-c",
         "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"],
        start_new_session=True)
    try:
        # Let the child install its SIGTERM handler before exercising forced shutdown.
        import time
        time.sleep(0.15)
        assert pty_aider.kill_process_group(
            child, grace=0.0, sleep=time.sleep) == "kill"
        assert child.poll() is not None, "the forced PTY child was signalled but not reaped"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
