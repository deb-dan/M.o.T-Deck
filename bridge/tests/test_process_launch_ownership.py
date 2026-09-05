"""U24/U25/U66: only a recorded child + matching birth stamp may be signalled."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from bridge.core import procs
from bridge.routers import component_lifecycle


def _alive(proc):
    return proc.poll() is None


def test_plain_pid_path_cwd_and_engine_name_never_establish_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    foreign = subprocess.Popen(["/bin/sleep", "30"], cwd=tmp_path)
    try:
        (tmp_path / "data" / "runner.pid").write_text(str(foreign.pid))
        assert procs._cmd_is_under_root(f"{tmp_path}/data/llamacpp/llama-server", str(tmp_path))
        notes = procs.reap_pidfile("runner", force=True)
        assert notes and "no matching M.O.T launch record" in notes[0]
        assert _alive(foreign), "path/CWD/name plus a planted PID file authorized a signal"
        assert not (tmp_path / "data" / "runner.pid").exists()
    finally:
        foreign.terminate(); foreign.wait()


def test_exact_child_record_allows_signal_even_for_external_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    child = subprocess.Popen(["/bin/sleep", "30"], cwd="/")
    try:
        procs.write_pidfile("aux", child.pid)
        assert procs._ownership_matches(child.pid, "aux")
        assert procs.reap_pidfile("aux", force=True) == []
        child.wait(timeout=3)
        assert not (tmp_path / "data" / "aux.pid").exists()
        assert not (tmp_path / "data" / "aux.owner").exists()
    finally:
        if _alive(child): child.kill(); child.wait()


def test_public_generic_stop_executes_with_real_module_namespace(tmp_path, monkeypatch):
    """The public route must import every ownership helper it calls."""
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    monkeypatch.setattr(component_lifecycle, "ROOT", tmp_path)
    monkeypatch.setattr(component_lifecycle, "cfg",
                        lambda: {"components": {"sample": {}}})
    monkeypatch.setattr(component_lifecycle, "publish", lambda *args, **kwargs: None)
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs.write_pidfile("sample", child.pid)
        response = component_lifecycle.stop("sample")
        assert response.status_code == 200
        child.wait(timeout=3)
        assert not (tmp_path / "data" / "sample.owner").exists()
    finally:
        if _alive(child): child.kill(); child.wait()


def test_stop_owned_component_stops_a_prebind_child_without_using_a_port(
        tmp_path, monkeypatch):
    """A loading runner is owned before it listens; Stop must still reach it."""
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_port_listener_pids", lambda _port: [])
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs.write_pidfile("runner", child.pid)
        assert procs.stop_owned_component("runner", 6767, wait_seconds=2) == []
        child.wait(timeout=3)
        assert not (tmp_path / "data" / "runner.owner").exists()
        assert not (tmp_path / "data" / "runner.pid").exists()
    finally:
        if _alive(child): child.kill(); child.wait()


def test_stop_owned_component_treats_a_stranger_port_only_as_a_refusal(
        tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_port_listener_pids", lambda _port: ["4242"])
    monkeypatch.setattr(procs, "_proc_cmdline", lambda _pid: "manual llama-server")
    notes = procs.stop_owned_component("runner", 6767, wait_seconds=0)
    assert len(notes) == 1 and "without a matching live M.O.T launch record" in notes[0]


def test_stop_owned_component_retains_claim_when_the_exact_child_survives_signal(
        tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    monkeypatch.setattr(procs, "_port_listener_pids", lambda _port: [])
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs.write_pidfile("runner", child.pid)
        real_kill = procs._ownership.os.kill
        monkeypatch.setattr(procs._ownership.os, "kill",
                            lambda pid, sig: None if pid == child.pid else real_kill(pid, sig))
        notes = procs.stop_owned_component("runner", 6767, wait_seconds=0)
        assert notes and "survived SIGKILL" in notes[0]
        assert (tmp_path / "data" / "runner.owner").exists()
        assert (tmp_path / "data" / "runner.pid").exists()
    finally:
        monkeypatch.setattr(procs._ownership.os, "kill", real_kill)
        if _alive(child): child.kill(); child.wait()


@pytest.mark.parametrize("mutation", ["birth", "pid", "version", "missing"])
def test_stale_malformed_or_recycled_record_refuses_without_signal(tmp_path, monkeypatch, mutation):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs.write_pidfile("component", child.pid)
        owner = tmp_path / "data" / "component.owner"
        version, pid, birth = owner.read_text().rstrip().split("\t", 2)
        if mutation == "birth": owner.write_text(f"v1\t{pid}\tMon Jan 1 00:00:00 1900\n")
        elif mutation == "pid": owner.write_text(f"v1\t{child.pid + 1}\t{birth}\n")
        elif mutation == "version": owner.write_text(f"v2\t{pid}\t{birth}\n")
        else: owner.unlink()
        notes = procs.reap_pidfile("component", force=True)
        assert notes and _alive(child)
    finally:
        if _alive(child): child.terminate(); child.wait()


def test_symlinked_owner_record_cannot_manufacture_signal_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    child = subprocess.Popen(["/bin/sleep", "30"])
    outside = tmp_path / "outside-owner"
    try:
        birth = procs._ownership.process_birth(child.pid)
        outside.write_text(f"v1\t{child.pid}\t{birth}\n")
        data = tmp_path / "data"; data.mkdir()
        (data / "runner.owner").symlink_to(outside)
        (data / "runner.pid").write_text(f"{child.pid}\n")
        notes = procs.reap_pidfile("runner", force=True)
        assert notes and _alive(child)
        assert outside.read_text() == f"v1\t{child.pid}\t{birth}\n"
    finally:
        if _alive(child): child.terminate(); child.wait()


def test_symlinked_pid_report_is_never_read_as_process_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    outside = tmp_path / "outside-pid"
    outside.write_text(str(os.getpid()))
    data = tmp_path / "data"; data.mkdir()
    (data / "runner.pid").symlink_to(outside)
    notes = procs.reap_pidfile("runner", force=True)
    assert notes and "no complete" in notes[0]
    assert outside.read_text() == str(os.getpid())
    assert not (data / "runner.pid").exists()


def test_symlinked_ownership_lock_refuses_before_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(procs, "ROOT", tmp_path)
    child = subprocess.Popen(["/bin/sleep", "30"])
    outside = tmp_path / "outside-lock"; outside.write_text("kept")
    try:
        procs.write_pidfile("runner", child.pid)
        lock = tmp_path / "data" / ".runner.owner.lock"
        lock.unlink(); lock.symlink_to(outside)
        with pytest.raises(OSError):
            procs.reap_pidfile("runner", force=True)
        assert _alive(child) and outside.read_text() == "kept"
    finally:
        if _alive(child): child.terminate(); child.wait()


def test_port_listener_needs_exact_component_record_and_force_never_weakens_it(monkeypatch):
    calls = []
    monkeypatch.setattr(procs, "_port_listener_pids", lambda _: ["4242"])
    monkeypatch.setattr(procs, "_proc_cmdline", lambda _: "/inside/root/data/llama-server")
    monkeypatch.setattr(procs._ownership, "signal_owned",
                        lambda *a, **k: (False, "no exact claim"))
    refused = procs._kill_port_listener(6767, force=True, component="runner")
    assert len(refused) == 1 and calls == []
    assert "without a matching M.O.T launch record" in refused[0]

    def signal(root, component, *, expected_pid, expected_birth, force, retire):
        calls.append((root, component, expected_pid, expected_birth, force, retire))
        return True, "signalled"
    monkeypatch.setattr(procs._ownership, "signal_owned", signal)
    monkeypatch.setattr(procs, "_read_ownership", lambda _: (4242, "birth-4242"))
    assert procs._kill_port_listener(6767, force=True, component="runner") == []
    assert calls == [(procs.ROOT, "runner", 4242, "birth-4242", True, True)]


def test_graceful_signal_retains_authority_until_exact_completion_cleanup(tmp_path):
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs._ownership.record_child(tmp_path, "slow", child.pid)
        sent, _ = procs._ownership.signal_owned(
            tmp_path, "slow", expected_pid=child.pid, retire=False)
        assert sent
        assert (tmp_path / "data" / "slow.owner").exists(), \
            "graceful signal discarded the authority needed for the shutdown wait"
        child.wait(timeout=3)
        claim = procs._ownership.read_claim(tmp_path, "slow")
        assert claim and procs._ownership.retire_owned(
            tmp_path, "slow", child.pid, claim[1])
        assert not (tmp_path / "data" / "slow.owner").exists()
        assert not (tmp_path / "data" / "slow.pid").exists()
    finally:
        if _alive(child):
            child.kill(); child.wait()


def test_shell_and_python_owner_records_share_the_same_birth_contract(tmp_path):
    root = tmp_path / "root"; scripts = root / "scripts"; scripts.mkdir(parents=True)
    core = root / "bridge" / "core"; core.mkdir(parents=True)
    shell = scripts / "start_component.sh"
    shutil.copy2(os.path.join(os.path.dirname(__file__), "..", "..", "scripts",
                              "start_component.sh"), shell)
    shutil.copy2(os.path.join(os.path.dirname(__file__), "..", "core", "ownership.py"),
                 core / "ownership.py")
    run = subprocess.run(["bash", str(shell), "--ownership-selftest", "shellprobe",
                          "/bin/sleep", "30"], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    pid = int(run.stdout.strip().splitlines()[-1])
    try:
        assert subprocess.run(["bash", str(shell), "--ownership-record-check",
                               "shellprobe", str(pid)]).returncode == 0
        owner = root / "data" / "shellprobe.owner"
        version, recorded, birth = owner.read_text().rstrip().split("\t", 2)
        assert version == "v1" and int(recorded) == pid and birth
        owner.write_text(f"v1\t{pid}\tThu Jan 1 00:00:00 1970\n")
        assert subprocess.run(["bash", str(shell), "--ownership-record-check",
                               "shellprobe", str(pid)]).returncode != 0
        os.kill(pid, 0), time.sleep(0.02)
    finally:
        try: os.kill(pid, 9)
        except ProcessLookupError: pass


def test_reaper_cannot_erase_a_new_claim_during_signal_cleanup(tmp_path, monkeypatch):
    """The claim lock covers verify, signal and cleanup as one operation.

    A second recorder must wait and then publish its complete claim after the old
    signal retires; the old stop must never unlink that new claim.
    """
    import threading

    monkeypatch.setattr(procs, "ROOT", tmp_path)
    old = subprocess.Popen(["/bin/sleep", "30"])
    new = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs.write_pidfile("race", old.pid)
        started = threading.Event()
        real_kill = procs._ownership.os.kill

        def delayed_kill(pid, sig):
            if pid == old.pid and sig != 0:
                started.set()
                time.sleep(0.15)
            return real_kill(pid, sig)

        monkeypatch.setattr(procs._ownership.os, "kill", delayed_kill)
        result = []
        stopper = threading.Thread(target=lambda: result.extend(
            procs.reap_pidfile("race", force=True)))
        stopper.start()
        assert started.wait(2)
        recorder = threading.Thread(target=lambda: procs.write_pidfile("race", new.pid))
        recorder.start()
        stopper.join(3); recorder.join(3)
        assert result == []
        assert procs._ownership_matches(new.pid, "race")
        assert (tmp_path / "data" / "race.pid").read_text().strip() == str(new.pid)
    finally:
        for child in (old, new):
            if child.poll() is None:
                child.kill()
            child.wait()


def test_graceful_retire_cannot_erase_reused_pid_with_a_new_birth(tmp_path):
    owner = tmp_path / "data" / "same.owner"
    pidfile = tmp_path / "data" / "same.pid"
    owner.parent.mkdir(parents=True)
    owner.write_text("v1\t4242\tnew-birth\n")
    pidfile.write_text("4242\n")
    assert not procs._ownership.retire_owned(tmp_path, "same", 4242, "old-birth")
    assert owner.read_text() == "v1\t4242\tnew-birth\n"
    assert pidfile.read_text() == "4242\n"


def test_stop_script_component_argument_never_stops_sibling_claims(tmp_path):
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "bridge" / "core").mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[2] / "scripts" / "stop.sh",
                 root / "scripts" / "stop.sh")
    shutil.copy2(Path(__file__).parents[1] / "core" / "ownership.py",
                 root / "bridge" / "core" / "ownership.py")
    first = subprocess.Popen(["/bin/sleep", "30"])
    sibling = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs._ownership.record_child(root, "first", first.pid)
        procs._ownership.record_child(root, "sibling", sibling.pid)
        done = subprocess.run(
            ["bash", str(root / "scripts" / "stop.sh"), "first"],
            capture_output=True, text=True, timeout=10)
        assert done.returncode == 0, done.stdout + done.stderr
        first.wait(timeout=3)
        assert sibling.poll() is None
        assert procs._ownership.ownership_matches(root, "sibling", sibling.pid)
    finally:
        for child in (first, sibling):
            if child.poll() is None:
                child.kill()
            child.wait()


def test_stop_script_uses_owner_claim_when_pid_report_is_missing(tmp_path):
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "bridge" / "core").mkdir(parents=True)
    shutil.copy2(Path(__file__).parents[2] / "scripts" / "stop.sh",
                 root / "scripts" / "stop.sh")
    shutil.copy2(Path(__file__).parents[1] / "core" / "ownership.py",
                 root / "bridge" / "core" / "ownership.py")
    child = subprocess.Popen(["/bin/sleep", "30"])
    try:
        procs._ownership.record_child(root, "owner-only", child.pid)
        (root / "data" / "owner-only.pid").unlink()
        done = subprocess.run(
            ["bash", str(root / "scripts" / "stop.sh"), "owner-only"],
            capture_output=True, text=True, timeout=10)
        assert done.returncode == 0, done.stdout + done.stderr
        child.wait(timeout=3)
        assert not (root / "data" / "owner-only.owner").exists()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
