"""U36: Goose UI survives a bridge restart only through exact launch provenance."""
from __future__ import annotations

import os
import subprocess
import sys

from bridge.core import ownership
from bridge.routers import gooseui


def _reset_runtime_globals():
    gooseui._PROC = None
    gooseui._PROC_BIRTH = ""
    gooseui._TOKEN = ""
    gooseui._PORT = 0


def test_matching_private_runtime_and_owner_claim_are_adopted(tmp_path, monkeypatch):
    monkeypatch.setattr(gooseui, "ROOT", tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    try:
        _, birth = ownership.record_child(tmp_path, "goose-ui", child.pid)
        gooseui._write_runtime(child.pid, birth, 32123, "t" * 32)
        _reset_runtime_globals()  # the exact state after a bridge interpreter restart

        assert gooseui._alive()
        assert gooseui._PROC is None, "adoption must not fabricate a Popen handle"
        assert gooseui._PROC_BIRTH == birth
        assert gooseui._PORT == 32123
        assert gooseui._TOKEN == "t" * 32
        assert (os.stat(gooseui._runtime_path()).st_mode & 0o777) == 0o600
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)
        gooseui._clear_runtime(child.pid, birth)
        ownership.retire_owned(tmp_path, "goose-ui", child.pid, birth)
        _reset_runtime_globals()


def test_runtime_metadata_never_establishes_ownership_by_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(gooseui, "ROOT", tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    try:
        birth = ownership.process_birth(child.pid)
        gooseui._write_runtime(child.pid, birth, 32124, "u" * 32)
        _reset_runtime_globals()

        assert not gooseui._alive()
        assert child.poll() is None, "an unowned runtime row affected a foreign process"
    finally:
        child.terminate()
        child.wait(timeout=5)
        gooseui._clear_runtime(child.pid, birth)
        _reset_runtime_globals()


def test_stop_after_adoption_signals_only_the_recorded_process_group(
        tmp_path, monkeypatch):
    monkeypatch.setattr(gooseui, "ROOT", tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    _, birth = ownership.record_child(tmp_path, "goose-ui", child.pid)
    gooseui._write_runtime(child.pid, birth, 32125, "v" * 32)
    _reset_runtime_globals()
    try:
        assert gooseui._alive()
        with gooseui._LOCK:
            result = gooseui._stop_locked("test-adopted")
        assert result == "reaped"
        child.wait(timeout=5)
        assert ownership.read_claim(tmp_path, "goose-ui") is None
        assert not gooseui._runtime_path().exists()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        _reset_runtime_globals()


def test_world_readable_or_mismatched_runtime_is_not_adopted(tmp_path, monkeypatch):
    monkeypatch.setattr(gooseui, "ROOT", tmp_path)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True)
    try:
        _, birth = ownership.record_child(tmp_path, "goose-ui", child.pid)
        gooseui._write_runtime(child.pid, birth, 32126, "w" * 32)
        os.chmod(gooseui._runtime_path(), 0o644)
        _reset_runtime_globals()
        assert not gooseui._alive()

        os.chmod(gooseui._runtime_path(), 0o600)
        gooseui._write_runtime(child.pid, birth + "-wrong", 32126, "w" * 32)
        assert not gooseui._alive()
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)
        gooseui._runtime_path().unlink(missing_ok=True)
        ownership.retire_owned(tmp_path, "goose-ui", child.pid, birth)
        _reset_runtime_globals()
