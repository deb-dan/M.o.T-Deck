"""U130: explicit pre-provenance migration never infers ownership."""

from pathlib import Path
import os
import signal
import subprocess
import sys
import time

from bridge.core import ownership


def _child():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])


def test_exact_pid_and_birth_are_required_and_one_sigterm_is_sent(tmp_path):
    child = _child()
    try:
        data = tmp_path / "data"
        data.mkdir()
        (data / "legacy.pid").write_text(f"{child.pid}\n")
        birth = ownership.process_birth(child.pid)
        assert birth
        ok, detail = ownership.terminate_legacy(
            tmp_path, "legacy", child.pid, birth, timeout=3)
        assert ok, detail
        child.wait(timeout=3)
        assert not (data / "legacy.pid").exists()
        assert not (data / "legacy.owner").exists()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)


def test_wrong_pid_or_birth_signals_nothing_and_retains_report(tmp_path):
    child = _child()
    try:
        data = tmp_path / "data"
        data.mkdir()
        (data / "legacy.pid").write_text(f"{child.pid}\n")
        birth = ownership.process_birth(child.pid)
        ok, _ = ownership.terminate_legacy(tmp_path, "legacy", child.pid, birth + "x")
        assert not ok and child.poll() is None
        assert (data / "legacy.pid").read_text().strip() == str(child.pid)
        ok, _ = ownership.terminate_legacy(tmp_path, "legacy", child.pid + 1, birth)
        assert not ok and child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_existing_authoritative_claim_must_use_normal_stop(tmp_path):
    child = _child()
    try:
        ownership.record_child(tmp_path, "owned", child.pid)
        birth = ownership.process_birth(child.pid)
        ok, detail = ownership.terminate_legacy(tmp_path, "owned", child.pid, birth)
        assert not ok and "authoritative" in detail
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_ambiguous_owner_record_fails_closed(tmp_path):
    child = _child()
    try:
        data = tmp_path / "data"
        data.mkdir()
        (data / "legacy.pid").write_text(f"{child.pid}\n")
        birth = ownership.process_birth(child.pid)
        for payload in ("", "not-a-claim\n"):
            (data / "legacy.owner").write_text(payload)
            ok, detail = ownership.terminate_legacy(
                tmp_path, "legacy", child.pid, birth, timeout=0)
            assert not ok and "malformed" in detail
            assert child.poll() is None
        (data / "legacy.owner").unlink()
        (data / "target").write_text("not an owner")
        (data / "legacy.owner").symlink_to(data / "target")
        ok, detail = ownership.terminate_legacy(
            tmp_path, "legacy", child.pid, birth, timeout=0)
        assert not ok and "non-regular" in detail
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_signal_without_valid_claim_preserves_legacy_evidence(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    pidfile = data / "legacy.pid"
    owner = data / "legacy.owner"
    pidfile.write_text("12345\n")
    owner.write_text("not-a-claim\n")
    sent, detail = ownership.signal_owned(tmp_path, "legacy", expected_pid=0)
    assert not sent and "retained" in detail
    assert pidfile.read_text() == "12345\n"
    assert owner.read_text() == "not-a-claim\n"


def test_missing_report_requires_second_acknowledgement(tmp_path):
    child = _child()
    try:
        birth = ownership.process_birth(child.pid)
        ok, detail = ownership.terminate_legacy(
            tmp_path, "legacy", child.pid, birth, timeout=3)
        assert not ok and "additional missing-report" in detail
        assert child.poll() is None
        ok, detail = ownership.terminate_legacy(
            tmp_path, "legacy", child.pid, birth, timeout=3,
            allow_missing_pid_report=True)
        assert ok, detail
        child.wait(timeout=3)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)


def test_missing_report_ack_cannot_bypass_existing_mismatch(tmp_path):
    child = _child()
    try:
        data = tmp_path / "data"
        data.mkdir()
        (data / "legacy.pid").write_text(f"{child.pid + 1}\n")
        birth = ownership.process_birth(child.pid)
        ok, detail = ownership.terminate_legacy(
            tmp_path, "legacy", child.pid, birth, timeout=0,
            allow_missing_pid_report=True)
        assert not ok and "changed" in detail
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=3)


def test_exact_dead_legacy_report_can_be_retired_without_signal(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "legacy.pid").write_text("999999\n")
    ok, detail = ownership.retire_stale_legacy_report(tmp_path, "legacy", 999999)
    assert ok and "signalled nothing" in detail
    assert not (data / "legacy.pid").exists()


def test_stale_report_retirement_refuses_live_mismatch_and_any_owner(tmp_path):
    child = _child()
    try:
        data = tmp_path / "data"
        data.mkdir()
        (data / "legacy.pid").write_text(f"{child.pid}\n")
        ok, detail = ownership.retire_stale_legacy_report(
            tmp_path, "legacy", child.pid + 1)
        assert not ok and "changed" in detail
        ok, detail = ownership.retire_stale_legacy_report(
            tmp_path, "legacy", child.pid)
        assert not ok and "alive" in detail
        (data / "legacy.owner").write_text("not-a-claim\n")
        child.terminate()
        child.wait(timeout=3)
        ok, detail = ownership.retire_stale_legacy_report(
            tmp_path, "legacy", child.pid)
        assert not ok and "owner record exists" in detail
        assert (data / "legacy.pid").exists()
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)


def test_operator_command_requires_the_explicit_acknowledgement():
    src = (Path(__file__).resolve().parents[2] / "scripts"
           / "migrate_legacy_process.py").read_text()
    assert "--acknowledge-unowned-process" in src
    assert "--acknowledge-missing-pid-report" in src
    assert "--acknowledge-stale-report" in src
    assert "os.killpg(" not in src and "signal.SIGKILL" not in src
    assert "corroborating evidence only" in src
