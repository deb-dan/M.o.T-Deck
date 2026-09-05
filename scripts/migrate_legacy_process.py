#!/usr/bin/env python3
"""Inspect or explicitly terminate one pre-launch-provenance M.O.T process.

This command exists for installations created before ``data/<component>.owner``.
Inspection never writes or signals.  Termination requires the operator to repeat the
exact PID and kernel birth fingerprint and spell the acknowledgement flag; it then
revalidates both under the same lock used by normal launch/stop operations.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bridge.core import ownership  # noqa: E402


def _run(*args: str) -> str:
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=3,
                              check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _redact_command(command: str) -> str:
    command = " ".join((command or "").split())
    # Inspection evidence is operator-facing, but a future component may put a secret
    # on argv. Preserve the flag while hiding its following value.
    return re.sub(r"(?i)(--?(?:api[-_]?key|token|password)(?:=|\s+))\S+",
                  r"\1<redacted>", command)[:1000]


def _evidence(pid: int) -> tuple[str, str, list[str]]:
    command = _redact_command(_run("/bin/ps", "-o", "command=", "-p", str(pid)))
    raw_cwd = _run("/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn")
    cwd = next((line[1:] for line in raw_cwd.splitlines() if line.startswith("n")), "")
    raw_ports = _run("/usr/sbin/lsof", "-nP", "-a", "-p", str(pid),
                     "-iTCP", "-sTCP:LISTEN", "-Fn")
    listeners = sorted({line[1:] for line in raw_ports.splitlines()
                        if line.startswith("n")})
    return command, cwd, listeners


def inspect(component: str, explicit_pid: int | None = None) -> int:
    owner, pidfile, _lockfile = ownership._paths(ROOT, component)
    if ownership.read_claim(ROOT, component):
        print(f"[migration] {component} already has an authoritative launch record.")
        print(f"[migration] Use: ./scripts/stop.sh {component}")
        return 3
    if ownership._path_present(owner):
        print(f"[migration] {owner} exists but is malformed, unreadable, or non-regular;")
        print("[migration] resolve it explicitly; signalled nothing")
        return 3
    pid = ownership.read_pid_report(ROOT, component)
    missing_report = False
    if pid:
        if explicit_pid is not None and explicit_pid != pid:
            print(f"[migration] supplied pid {explicit_pid} disagrees with the retained "
                  f"legacy report {pid}; signalled nothing")
            return 3
    elif ownership._path_present(pidfile):
        print(f"[migration] {pidfile} exists but is malformed, unreadable, or non-regular;")
        print("[migration] it cannot be bypassed; signalled nothing")
        return 3
    elif explicit_pid is not None and explicit_pid > 0:
        pid = explicit_pid
        missing_report = True
    else:
        print(f"[migration] no legacy PID report remains for {component}.")
        print("[migration] If an earlier tool erased it, re-run inspect with the exact")
        print("[migration] listener PID as --pid; no name, path, cwd, or port proves ownership.")
        return 3
    birth = ownership.process_birth(pid)
    if not birth:
        print(f"[migration] pid {pid} is gone or its kernel birth cannot be proven; signalled nothing")
        return 3
    command, cwd, listeners = _evidence(pid)
    print(f"[migration] component: {component}")
    print(f"[migration] pid:       {pid}")
    print(f"[migration] birth:     {birth}")
    print(f"[migration] command:   {command or '(unavailable)'}")
    print(f"[migration] cwd:       {cwd or '(unavailable)'}")
    print(f"[migration] listeners: {', '.join(listeners) if listeners else '(none observed)'}")
    print("[migration] The command, cwd and ports are corroborating evidence only; they do")
    print("[migration] not prove M.O.T ownership. Review them, then explicitly name this")
    if missing_report:
        print("[migration] WARNING: the legacy PID report is absent. This is a stricter")
        print("[migration] recovery path and requires a second explicit acknowledgement.")
    print("[migration] exact process if you authorize one SIGTERM (never SIGKILL):")
    missing_ack = " --acknowledge-missing-pid-report" if missing_report else ""
    print(f"  ./scripts/migrate_legacy_process.py terminate {component} --pid {pid} "
          f"--birth {birth} --acknowledge-unowned-process{missing_ack}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("inspect", "terminate"))
    parser.add_argument("component")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--birth")
    parser.add_argument("--acknowledge-unowned-process", action="store_true")
    parser.add_argument("--acknowledge-missing-pid-report", action="store_true")
    args = parser.parse_args()
    try:
        ownership._paths(ROOT, args.component)  # validation only; grants no authority
    except ValueError as exc:
        parser.error(str(exc))
    if args.action == "inspect":
        return inspect(args.component, args.pid)
    if not args.acknowledge_unowned_process:
        parser.error("terminate requires --acknowledge-unowned-process")
    if args.pid is None or not args.birth:
        parser.error("terminate requires the exact --pid and --birth printed by inspect")
    ok, detail = ownership.terminate_legacy(
        ROOT, args.component, args.pid, args.birth,
        allow_missing_pid_report=args.acknowledge_missing_pid_report)
    print(f"[migration] {detail}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
