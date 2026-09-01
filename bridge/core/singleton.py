"""THE BRIDGE SINGLETON — one bridge per harness root, and never a kill to get there.

WHY THIS EXISTS (the 2026-08-30 incident, second find). Three bridge processes were
alive at once against the same snapshot: pids 15166 (18:25), 87620 (22:15) and the
real one, 25183, on :8700. The first framing was "nothing prevents N bridges". That
framing is WRONG and the corrected mechanism matters, because it changes the fix:

  · The kernel already prevents two LISTENERS. A second `uvicorn … --port 8700`
    cannot bind while another holds the socket; it dies with "address already in
    use". There has never been a race for the port itself.

  · What actually leaked was bridges stuck in a graceful shutdown that never ends.
    On SIGTERM uvicorn closes the LISTENING socket first (which is why the next
    bridge binds happily) and then waits for in-flight responses to finish. Our
    `/api/events` route is an infinite `text/event-stream`. Measured on the two
    survivors: each still held exactly one ESTABLISHED `127.0.0.1:8700->…` socket
    and NO listening socket, and lsof named the peer — the Claude desktop app,
    pid 3167, holding an SSE stream open across both. uvicorn will wait for that
    forever, so the process lives on, keeps its background health poller running,
    and keeps appending to the same data/logs/bridge.log.

  So there are two distinct fixes, and this file is only the second one:
    1. `--timeout-graceful-shutdown` on every bridge launch (app/main.swift and
       scripts/ship.sh) so SIGTERM actually ends the process. That is what stops
       new zombies being created.
    2. This guard, so that even when a lingering bridge HAS released the port, a
       newly launched one notices the incumbent and stands down honestly instead of
       both of them running application code against the same data/ directory.

THE RULE WE DO NOT BREAK (CLAUDE.md PROCESS-KILL RULE): the incumbent WINS. We never
signal it, never clear the port, never escalate. The newcomer prints one honest
sentence and exits 0 — 0, not 1, because standing down in favour of a working bridge
is a correct outcome, not a failure, and ship.sh/the app should not treat it as one.

IMPORT SAFETY. This runs at bridge boot, and ~40 test files import bridge.app in
process. `claim_or_exit()` is therefore a no-op unless argv says we really are
`python -m uvicorn bridge.app:app` — a pytest run can never be exited by it.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
from pathlib import Path


def _pidfile(root: Path) -> Path:
    return root / "data" / "bridge.pid"


def _cmdline(pid: int) -> str:
    """The full command line of `pid`, or "" if it is gone/unreadable."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5)
        return " ".join(out.stdout.split())
    except Exception:                                    # noqa: BLE001
        return ""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                                      # exists, not ours to signal
    except Exception:                                    # noqa: BLE001
        return False


def is_our_bridge(cmd: str, root: Path, port: str) -> bool:
    """Identity, never a name. A command line is OUR bridge only if it names THIS
    harness root's venv python, the uvicorn module, the bridge app target AND the
    same port. Debi runs standalone copies of the things we embed, and 'python' or
    'uvicorn' appearing in a command line is evidence of nothing at all.

    Pure string logic so the contract suite can exercise every branch without
    needing a live process.
    """
    if not cmd:
        return False
    root_s = str(root)
    return (f"{root_s}/data/bridge-venv/bin/python" in cmd
            and "uvicorn" in cmd
            and "bridge.app:app" in cmd
            and f"--port {port}" in cmd)


def _our_port(default: str = "8700") -> str:
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--port="):
            return a.split("=", 1)[1]
    return default


def _launched_as_bridge_server() -> bool:
    """True only for a real `python -m uvicorn bridge.app:app` boot. Anything else —
    pytest, a REPL, a tooling import — gets a no-op, so importing the bridge can
    never terminate the importer."""
    return any("bridge.app:app" in str(a) for a in sys.argv)


def _listener_pid(port: str) -> int:
    """The pid LISTENING on `port`, or 0. Degrades to nothing when lsof is absent —
    the pidfile check is the primary signal and this is only belt-and-braces."""
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5)
        for line in out.stdout.split():
            n = int(line)
            if n != os.getpid():
                return n
    except Exception:                                    # noqa: BLE001
        return 0
    return 0


def claim_or_exit(root: Path, *, _exit=None) -> str:
    """Stand down if a verified incumbent bridge is already running; otherwise take
    ownership of data/bridge.pid. Returns a one-line sentence describing what it
    decided (also printed), so the contract test can assert on the decision without
    parsing logs. `_exit` is injectable for the tests; production uses os._exit.

    os._exit and not sys.exit: sys.exit raises SystemExit, which uvicorn's own
    machinery would catch and turn into a traceback plus a nonzero status. We want a
    clean, immediate 0 with no interpreter teardown — and crucially no atexit hook
    firing, which would delete the INCUMBENT's pidfile on the way out.
    """
    if not _launched_as_bridge_server():
        return "singleton: not a uvicorn bridge boot - guard skipped"

    port = _our_port()
    pf = _pidfile(root)
    me = os.getpid()

    # 1. THE PIDFILE — the primary signal, written by the bridge itself since v1.5.16.
    incumbent, why = 0, ""
    try:
        raw = pf.read_text().strip()
        pid = int("".join(c for c in raw if c.isdigit()) or "0")
    except Exception:                                    # noqa: BLE001
        pid = 0
    if pid and pid != me:
        if not _alive(pid):
            why = f"data/bridge.pid named pid {pid}, which is not running - ignoring the stale file"
        else:
            cmd = _cmdline(pid)
            if is_our_bridge(cmd, root, port):
                incumbent = pid
            else:
                why = (f"data/bridge.pid named pid {pid}, which is NOT this harness's bridge "
                       f"({cmd[:90] or 'no command line'}) - ignoring the stale file, and "
                       f"leaving that process alone")

    # 2. THE LISTENER — belt-and-braces for the transition (a bridge started before
    #    this guard shipped wrote no pidfile) and for the ship/app launch race. Only
    #    an incumbent VERIFIED as ours defers us; a stranger on the port is left to
    #    uvicorn's own bind error, because clearing a port we do not own is banned.
    if not incumbent:
        lp = _listener_pid(port)
        if lp and is_our_bridge(_cmdline(lp), root, port):
            incumbent = lp

    if incumbent:
        msg = (f"[bridge] singleton: pid {incumbent} is already serving this harness on "
               f":{port} (verified: same root, same venv python, same uvicorn target). "
               f"This bridge (pid {me}) is standing down and exiting 0 - the running one "
               f"keeps the port and is never signalled.")
        print(msg, flush=True)
        (_exit or os._exit)(0)
        return msg

    if why:
        print(f"[bridge] singleton: {why}.", flush=True)

    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(me))
    except Exception as e:                               # noqa: BLE001
        msg = (f"[bridge] singleton: could not write {pf} ({e}) - this bridge runs "
               f"anyway, but a second one will not be able to see it and stand down.")
        print(msg, flush=True)
        return msg

    def _release() -> None:
        # Only ever remove a pidfile that still names US. A bridge that lost a race
        # and had its file overwritten must not delete the winner's claim.
        try:
            if _pidfile(root).read_text().strip() == str(me):
                _pidfile(root).unlink()
        except Exception:                                # noqa: BLE001
            pass

    atexit.register(_release)
    msg = f"[bridge] singleton: pid {me} claimed :{port} for this harness ({pf})."
    print(msg, flush=True)
    return msg
