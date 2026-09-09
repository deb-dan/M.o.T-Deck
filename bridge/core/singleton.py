"""One bridge per root, proved by launch provenance rather than paths or names.

The process that launches the bridge (the Swift shell or ``ship.sh``) owns the real
child handle. It records ``PID + kernel birth stamp`` in ``data/bridge.{pid,owner}``
before the bridge may finish importing this module. This module never adopts a
listener, a matching command line, a working directory, or a bare PID file.

That distinction is load-bearing: a user may manually run the same Python executable
from the same checkout. M.O.T did not spawn that process and therefore may neither
claim nor later signal it. A launch without the matching record fails closed.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import time
from pathlib import Path

from . import ownership as _ownership


def _pidfile(root: Path) -> Path:
    return Path(root) / "data" / "bridge.pid"


def _ownerfile(root: Path) -> Path:
    return Path(root) / "data" / "bridge.owner"


def _cmdline(pid: int) -> str:
    """Diagnostic text only. Its contents never authorize a signal or claim."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))],
                             capture_output=True, text=True, timeout=5)
        return " ".join(out.stdout.split())
    except Exception:                                    # noqa: BLE001
        return ""


def _birth(pid: int) -> str:
    return _ownership.process_birth(pid)


def _alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:                                    # noqa: BLE001
        return False


def _read_owner(root: Path):
    return _ownership.read_claim(Path(root), "bridge")


def ownership_matches(root: Path, pid: int) -> bool:
    """True only for the exact child and birth stamp recorded by its launcher."""
    try:
        return _ownership.ownership_matches(Path(root), "bridge", int(pid))
    except Exception:                                    # noqa: BLE001
        return False


def is_our_bridge(cmd: str, root: Path, port: str) -> bool:
    """Legacy diagnostic predicate, deliberately insufficient for ownership."""
    if not cmd:
        return False
    root_s = str(root)
    return (f"{root_s}/data/bridge-venv/bin/python" in cmd
            and "uvicorn" in cmd and "bridge.app:app" in cmd
            and f"--port {port}" in cmd)


def _our_port(default: str = "8700") -> str:
    for index, arg in enumerate(sys.argv):
        if arg == "--port" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith("--port="):
            return arg.split("=", 1)[1]
    return default


def _launched_as_bridge_server() -> bool:
    return any("bridge.app:app" in str(arg) for arg in sys.argv)


def release_claim(root: Path, pid: int | None = None) -> bool:
    """Idempotently release only this exact live process's complete launch claim."""
    owner_pid = int(os.getpid() if pid is None else pid)
    return _ownership.release_owned(Path(root), "bridge", owner_pid)


def claim_or_exit(root: Path, *, _exit=None, _wait_seconds: float = 2.0) -> str:
    """Validate the spawner's record or stand down without adopting anything."""
    if not _launched_as_bridge_server():
        return "singleton: not a uvicorn bridge boot - guard skipped"

    root = Path(root)
    me = os.getpid()
    deadline = time.monotonic() + max(0.0, _wait_seconds)
    while True:
        owner = _read_owner(root)
        if owner and owner[0] != me and ownership_matches(root, owner[0]):
            incumbent = owner[0]
            msg = (f"[bridge] singleton: pid {incumbent} already owns this MOT Deck root "
                   f"(exact launch record). This bridge pid {me} is standing down; "
                   "the incumbent is never signalled.")
            print(msg, flush=True)
            (_exit or os._exit)(0)
            return msg
        if ownership_matches(root, me):
            atexit.register(release_claim, root, me)
            msg = (f"[bridge] singleton: pid {me} accepted its launcher-owned claim "
                   f"for :{_our_port()} ({_pidfile(root)}).")
            print(msg, flush=True)
            return msg
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)

    owner = _read_owner(root)
    detail = "no complete launch record"
    if owner:
        detail = f"record names pid {owner[0]} but its birth fingerprint does not match"
    msg = (f"[bridge] singleton: refusing unowned bridge pid {me}: {detail}. "
           "Start it through M.O.T or scripts/ship.sh; paths, names and ports are not ownership.")
    print(msg, flush=True)
    (_exit or os._exit)(1)
    return msg
