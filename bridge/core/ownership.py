"""Locked launch-provenance records shared by the bridge and shell launchers.

The ``.owner`` record is the authority. ``.pid`` remains a compatibility/reporting
file, but losing or replacing it never grants signal authority. Every cooperating
record, signal, release, and stale-cleanup operation holds the same advisory lock so
an old stop cannot erase a newly launched child's claim between verification and
cleanup.

This module is stdlib-only and has a small CLI because Bash 3.2 has no built-in
``flock``. ``scripts/start_component.sh`` and ``scripts/stop.sh`` call the exact same
implementation imported by Python routes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import ctypes.util
import fcntl
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time


class ClaimConflict(RuntimeError):
    """A different live child already owns this component claim."""


def _paths(root: Path, component: str) -> tuple[Path, Path, Path]:
    if not component or component in {".", ".."} or "/" in component or "\0" in component:
        raise ValueError("component must be one path-safe name")
    data = Path(root) / "data"
    return (data / f"{component}.owner", data / f"{component}.pid",
            data / f".{component}.owner.lock")


@contextmanager
def _locked(root: Path, component: str, *, shared: bool = False):
    owner, pidfile, lockfile = _paths(Path(root), component)
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lockfile, os.O_CREAT | os.O_RDWR
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"refusing non-regular launch-record lock: {lockfile}")
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield owner, pidfile
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def process_birth(pid: int) -> str:
    """High-resolution kernel birth identity, or empty when it cannot be proved.

    macOS ``ps lstart`` is only second-resolution: two processes launched in the same
    second can share it. ``proc_pidinfo`` exposes the kernel's microsecond timestamp.
    Linux uses the procfs start-time tick. There is deliberately no weak fallback.
    """
    pid = int(pid)
    try:
        if sys.platform == "darwin":
            maxcomlen = 16
            class ProcBSDInfo(ctypes.Structure):
                _fields_ = [
                    (name, ctypes.c_uint32) for name in (
                        "pbi_flags", "pbi_status", "pbi_xstatus", "pbi_pid",
                        "pbi_ppid", "pbi_uid", "pbi_gid", "pbi_ruid", "pbi_rgid",
                        "pbi_svuid", "pbi_svgid", "rfu_1")
                ] + [
                    ("pbi_comm", ctypes.c_char * maxcomlen),
                    ("pbi_name", ctypes.c_char * (2 * maxcomlen)),
                ] + [
                    (name, ctypes.c_uint32) for name in (
                        "pbi_nfiles", "pbi_pgid", "pbi_pjobc", "e_tdev", "e_tpgid")
                ] + [
                    ("pbi_nice", ctypes.c_int32),
                    ("pbi_start_tvsec", ctypes.c_uint64),
                    ("pbi_start_tvusec", ctypes.c_uint64),
                ]
            libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "/usr/lib/libproc.dylib")
            libproc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int,
                                             ctypes.c_uint64, ctypes.c_void_p,
                                             ctypes.c_int]
            libproc.proc_pidinfo.restype = ctypes.c_int
            info = ProcBSDInfo()
            got = libproc.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
            if got != ctypes.sizeof(info) or info.pbi_pid != pid or info.pbi_status == 5:
                return ""                         # 5 = SZOMB
            return f"darwin:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}"
        if sys.platform.startswith("linux"):
            raw = Path(f"/proc/{pid}/stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            if len(fields) < 20 or fields[0] == "Z":
                return ""
            return f"linux:{fields[19]}"          # field 22: kernel start-time tick
        return ""
    except Exception:  # noqa: BLE001 -- unverifiable must fail closed
        return ""


def _parse(raw: bytes | None):
    try:
        version, raw_pid, birth = (raw or b"").decode("utf-8").rstrip("\n").split("\t", 2)
        pid = int(raw_pid)
        return (pid, birth) if version == "v1" and pid > 0 and birth else None
    except Exception:  # noqa: BLE001 -- malformed records authorize nothing
        return None


def _read(path: Path) -> bytes | None:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            return handle.read()
    except OSError:
        return None
    finally:
        if fd >= 0:
            os.close(fd)


def _pid_report_matches(path: Path, pid: int) -> bool:
    """Read the compatibility PID report without following links."""
    try:
        return int((_read(path) or b"").decode("ascii").strip()) == int(pid)
    except (UnicodeError, ValueError):
        return False


def _path_present(path: Path) -> bool:
    """Return whether a directory entry exists without following a symlink.

    Errors other than a proven absence are deliberately treated as presence so a
    caller cannot turn unreadable ownership evidence into signal authority.
    """
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def read_pid_report(root: Path, component: str) -> int | None:
    """Return the non-authoritative PID report only when it is a regular file."""
    _owner, pidfile, _lockfile = _paths(Path(root), component)
    try:
        value = int((_read(pidfile) or b"").decode("ascii").strip())
        return value if value > 0 else None
    except (UnicodeError, ValueError):
        return None


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary: Path | None = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_dir(path.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _restore(path: Path, raw: bytes | None) -> None:
    if raw is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, raw)


def read_claim(root: Path, component: str):
    """Return ``(pid, birth)`` from the authoritative owner record, if valid."""
    with _locked(root, component, shared=True) as (owner, _pidfile):
        return _parse(_read(owner))


def ownership_matches(root: Path, component: str, pid: int) -> bool:
    """Reverify the exact claim under its shared lock."""
    with _locked(root, component, shared=True) as (owner, _pidfile):
        claim = _parse(_read(owner))
        return bool(claim and claim[0] == int(pid)
                    and process_birth(int(pid)) == claim[1])


def record_child(root: Path, component: str, pid: int) -> tuple[int, str]:
    """Atomically replace a stale claim; refuse a different still-live incumbent."""
    pid = int(pid)
    birth = process_birth(pid)
    if not birth:
        raise RuntimeError(f"could not fingerprint spawned {component} pid {pid}")
    owner_payload = f"v1\t{pid}\t{birth}\n".encode()
    pid_payload = f"{pid}\n".encode()
    with _locked(root, component) as (owner, pidfile):
        old_owner, old_pid = _read(owner), _read(pidfile)
        incumbent = _parse(old_owner)
        if (incumbent and incumbent[0] != pid
                and process_birth(incumbent[0]) == incumbent[1]):
            raise ClaimConflict(
                f"{component} already has a live M.O.T launch record for pid {incumbent[0]}")
        try:
            # PID is reporting only. Publish the authoritative owner record last so
            # observers see either the old complete claim or the new complete claim.
            _atomic_write(pidfile, pid_payload)
            _atomic_write(owner, owner_payload)
        except BaseException:
            _restore(pidfile, old_pid)
            _restore(owner, old_owner)
            raise
    return pid, birth


def signal_owned(root: Path, component: str, *, expected_pid: int | None = None,
                 expected_birth: str | None = None, force: bool = False,
                 retire: bool = True, group: bool = False) -> tuple[bool, str]:
    """Verify and signal one exact child while holding the claim's exclusive lock.

    Returns ``(signalled, detail)``. A valid-but-stale claim is cleaned only while the
    lock proves no cooperating relaunch has replaced it. Missing or malformed owner
    evidence and legacy PID reports are retained for explicit operator inspection;
    inability to prove authority must never destroy the evidence needed to recover it.
    """
    with _locked(root, component) as (owner, pidfile):
        claim_raw = _read(owner)
        claim = _parse(claim_raw)
        if not claim:
            return False, ("no complete M.O.T launch record; signalled nothing; "
                           "unverifiable owner/PID evidence was retained")
        pid, birth = claim
        if expected_pid is not None and pid != int(expected_pid):
            return False, f"launch record names pid {pid}, not observed pid {int(expected_pid)}"
        if expected_birth is not None and birth != expected_birth:
            return False, "launch record birth identity changed; signalled nothing"
        if process_birth(pid) != birth:
            owner.unlink(missing_ok=True)
            if _pid_report_matches(pidfile, pid):
                pidfile.unlink(missing_ok=True)
            return False, f"launch record for pid {pid} is stale or unverifiable; signalled nothing"
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            if group:
                if os.getpgid(pid) != pid:
                    return False, "recorded child is not its process-group leader; signalled nothing"
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except ProcessLookupError:
            owner.unlink(missing_ok=True)
            if _pid_report_matches(pidfile, pid):
                pidfile.unlink(missing_ok=True)
            return False, f"recorded pid {pid} already exited; signalled nothing"
        if retire:
            # The signal was sent to the verified child. Retire only this claim while
            # a concurrent record_child remains excluded by the lock. A graceful
            # escalation path may deliberately keep the claim until exit/KILL.
            owner.unlink(missing_ok=True)
            if _pid_report_matches(pidfile, pid):
                pidfile.unlink(missing_ok=True)
        return True, f"signalled recorded {component} pid {pid}"


def release_owned(root: Path, component: str, pid: int) -> bool:
    """Remove only the exact still-live claim, without signalling its process."""
    with _locked(root, component) as (owner, pidfile):
        claim = _parse(_read(owner))
        if not claim or claim[0] != int(pid) or process_birth(int(pid)) != claim[1]:
            return False
        owner.unlink(missing_ok=True)
        if _pid_report_matches(pidfile, int(pid)):
            pidfile.unlink(missing_ok=True)
        return True


def retire_owned(root: Path, component: str, pid: int, birth: str) -> bool:
    """Remove only the exact ``pid`` + ``birth`` claim after that child exited.

    This is the completion half of a graceful stop: ``signal_owned(retire=False)``
    keeps authority while the child drains, the caller observes shutdown, and this
    exact-PID cleanup cannot erase a concurrently published replacement claim.
    """
    pid = int(pid)
    birth = str(birth or "")
    if not birth:
        return False
    with _locked(root, component) as (owner, pidfile):
        claim = _parse(_read(owner))
        if not claim or claim != (pid, birth):
            return False
        owner.unlink(missing_ok=True)
        if _pid_report_matches(pidfile, pid):
            pidfile.unlink(missing_ok=True)
        return True


def terminate_legacy(root: Path, component: str, pid: int, birth: str,
                     *, timeout: float = 5.0,
                     allow_missing_pid_report: bool = False) -> tuple[bool, str]:
    """Terminate one explicitly acknowledged pre-provenance process.

    This is intentionally *not* ownership inference.  The operator must supply the
    exact PID and kernel birth value printed by the separate inspection command.  We
    then hold the normal ownership lock while rechecking the legacy PID report, the
    absence of a valid owner claim, and the birth identity immediately before one
    SIGTERM. If an earlier unsafe stop already erased the report, a *second* explicit
    acknowledgement can permit the exact inspected PID + birth pair. An existing
    malformed or mismatched report can never be bypassed. There is no name/path/port
    match and no SIGKILL escalation.
    """
    pid = int(pid)
    birth = str(birth or "")
    if pid <= 0 or not birth:
        return False, "an exact positive PID and kernel birth identity are required"
    with _locked(Path(root), component) as (owner, pidfile):
        if _path_present(owner):
            if _parse(_read(owner)):
                return False, ("an authoritative M.O.T launch record now exists; use "
                               "scripts/stop.sh instead")
            return False, ("an owner record exists but is malformed, unreadable, or "
                           "non-regular; resolve it explicitly; signalled nothing")
        report_present = _path_present(pidfile)
        if report_present and not _pid_report_matches(pidfile, pid):
            return False, "the legacy PID report changed; inspect again; signalled nothing"
        if not report_present and not allow_missing_pid_report:
            return False, ("the legacy PID report is absent; the additional missing-report "
                           "acknowledgement is required; signalled nothing")
        if process_birth(pid) != birth:
            return False, "the process birth identity changed; inspect again; signalled nothing"
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            if _pid_report_matches(pidfile, pid):
                pidfile.unlink(missing_ok=True)
            return True, f"legacy pid {pid} had already exited; retired its matching report"
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline and process_birth(pid) == birth:
            time.sleep(0.05)
        if process_birth(pid) == birth:
            return False, (f"legacy pid {pid} survived SIGTERM; its report was retained; "
                           "no escalation was attempted")
        if _pid_report_matches(pidfile, pid):
            pidfile.unlink(missing_ok=True)
        owner.unlink(missing_ok=True)
        return True, f"terminated explicitly acknowledged legacy {component} pid {pid}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("claim", "record", "matches", "signal",
                                            "release", "retire"))
    parser.add_argument("root", type=Path)
    parser.add_argument("component")
    parser.add_argument("pid", type=int, nargs="?")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-claim", action="store_true")
    parser.add_argument("--birth")
    parser.add_argument("--group", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "claim":
            claim = read_claim(args.root, args.component)
            if not claim:
                return 3
            print(f"{claim[0]}\t{claim[1]}")
            return 0
        if args.pid is None:
            parser.error(f"{args.action} requires pid")
        if args.action == "record":
            record_child(args.root, args.component, args.pid)
            return 0
        if args.action == "matches":
            return 0 if ownership_matches(args.root, args.component, args.pid) else 1
        if args.action == "release":
            return 0 if release_owned(args.root, args.component, args.pid) else 1
        if args.action == "retire":
            return 0 if retire_owned(
                args.root, args.component, args.pid, args.birth or "") else 1
        signalled, detail = signal_owned(
            args.root, args.component, expected_pid=args.pid,
            expected_birth=args.birth, force=args.force,
            retire=not args.keep_claim, group=args.group)
        print(detail)
        return 0 if signalled else 3
    except ClaimConflict as exc:
        print(str(exc))
        return 4
    except Exception as exc:  # noqa: BLE001 -- CLI boundary must be an honest sentence
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
