"""CORE — config, the script runner, and the process/port primitives.

The bottom of the stack: motdeck.yaml access (`cfg`), the registry read
(`_registry_models`), scripts/ invocation (`_script`), liveness probes in both async and
sync flavours, the dependency closure, and the port-kill machinery with its ownership
guard. Nothing here knows a route exists, and nothing here may import bridge/routers.

⚠️ TWO GROUPS MOVED IN HERE from further down the old app.py, and both moves are
load-bearing rather than tidying — see the block comments where they land.
"""
from __future__ import annotations

from pathlib import Path
import asyncio
import os
import socket
import subprocess
import time
import yaml
from .appctx import ROOT
from . import ownership as _ownership
from .localsecrets import overlay_config



def cfg() -> dict:
    data = yaml.safe_load((ROOT / "motdeck.yaml").read_text())
    if not isinstance(data, dict):
        raise ValueError("motdeck.yaml root must be a mapping")
    return overlay_config(data, ROOT)


# ── THE RELEASE VERSION: ONE FILE, AND IT IS `VERSION` (U56, 2026-09-02) ──────
# There were two version numbers and the app displayed the dead one. `motdeck.yaml`
# carried `version: "0.1.0"` with a comment saying "bump on release"; nothing bumped it
# in 72 releases, and it was the ONLY thing /api/version ever read. Meanwhile the
# top-level `VERSION` file — which QA bumps in the same commit as every slice, which
# ship.sh and every commit message name, and which build_app.sh has seeded into the fat
# app since v1.5.70 — was read by NO runtime code at all.
#
# So the Version tile said 0.1.0 at release 1.5.72 (measured), and the update check
# compared GitHub tags against 0.1.0, which makes ANY tag newer for ever. Two lies out
# of one duplicated fact.
#
# THE FIX IS SINGLE-SOURCING, NOT SYNCING: `VERSION` is the release truth, the runtime
# READS it, and `motdeck.yaml version:` is GONE from the repo manifest. A syncing step
# would only have moved the drift somewhere harder to see.
#
# ⚠️ AND IT IS ALLOWED TO BE ABSENT. Fat installs from before v1.5.70 have no VERSION in
# their snapshot, and ROOT for the app IS the snapshot. That case gets an HONEST
# SENTENCE, never a made-up number: an unknown version is displayed as unknown, and it
# DISABLES the update comparison rather than guessing at it.
VERSION_UNKNOWN_NOTE = (
    "this install carries no VERSION file — it predates v1.5.70, which is when the fat "
    "seed started shipping one. Run ./scripts/ship.sh from the repo to stamp it."
)


def motdeck_version() -> str:
    """The release version from ROOT/VERSION, or "" when it is absent/unreadable.

    NEVER raises: the version tile and the update check both hang off it and neither may
    take the status page down."""
    try:
        raw = (ROOT / "VERSION").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    # First line only, and never the quoting a hand-edit might leave behind.
    for line in raw.splitlines():
        v = line.strip().strip('"').strip("'").strip()
        if v:
            return v
    return ""


def _script(name: str, *args: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    # A script that lost its execute bit is a recorded gotcha ("new scripts need
    # chmod +x") and it bit install_aider.sh, which shipped 100644: subprocess.run
    # raised PermissionError, the install could never start, and the page showed
    # nothing. Running it through bash is strictly additive — this branch is only
    # reachable where today we hard-crash — and it self-heals a snapshot whose copy
    # arrived without the bit. bridge/tests/test_script_hygiene.py is the real fence.
    p = ROOT / "scripts" / name
    argv = [str(p), *args]
    if p.is_file() and not os.access(p, os.X_OK):
        print(f"[bridge] {name} is not executable — running it via bash "
              f"(fix with: chmod +x scripts/{name})", flush=True)
        argv = ["/bin/bash", str(p), *args]
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=ROOT, timeout=timeout,
    )


def _pid_alive(name: str) -> bool:
    f = ROOT / "data" / f"{name}.pid"
    try:
        pid = int(f.read_text().strip())
        os.kill(pid, 0)
        return _ownership_matches(pid, name)
    except Exception:
        return False


async def _port_alive(port: int, timeout: float = 0.5) -> bool:
    # `timeout` is defaulted so every existing call site keeps its 0.5s budget
    # byte-for-byte; only /api/status passes a per-component value (see
    # PROBE_TIMEOUT_S — a component whose probe legitimately needs longer must not
    # be able to widen everybody else's).
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=timeout)
        writer.close()
        return True
    except Exception:
        return False


async def _running(name: str, c: dict) -> bool:
    """Is a component (or the runner) currently up?"""
    if name == "runner":
        rc = c.get("runner") or {}
        rport = rc.get("port")
        return await _port_alive(int(rport)) if rport else False
    comp = c.get("components", {}).get(name, {})
    port = comp.get("port") or comp.get("mcp_port")
    return (await _port_alive(int(port)) if port else False) or _pid_alive(name)


def _deps(name: str, c: dict) -> list:
    if name == "runner":
        return (c.get("runner") or {}).get("depends_on", [])
    return c.get("components", {}).get(name, {}).get("depends_on", [])


def _closure(name: str, c: dict, acc: list) -> list:
    """Dependency-ordered list ending with `name` (deps first, deduped)."""
    for d in _deps(name, c):
        _closure(d, c, acc)
    if name not in acc:
        acc.append(name)
    return acc


# ── One-switch provisioning: background runner + observable per-component state ──
# PROV maps component name -> {"state": pending|starting|on|failed|blocked, "detail": str}.
# The panel reads it from /api/status and animates cards live during a start-closure.
PROV: dict = {}


def _port_alive_sync(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=0.5)
        s.close()
        return True
    except Exception:
        return False


def _expected_path(name: str) -> Path:
    return ROOT / "data" / f"{name}.expected"


def _mark_expected(name: str) -> None:
    try:
        _expected_path(name).write_text("1")
    except Exception:
        pass


def _clear_expected(name: str) -> None:
    try:
        _expected_path(name).unlink(missing_ok=True)
    except Exception:
        pass


def _running_sync(name: str, c: dict) -> bool:
    if name == "runner":
        rc = c.get("runner") or {}
        p = rc.get("port")
        return _port_alive_sync(p) if p else False
    comp = c.get("components", {}).get(name, {})
    p = comp.get("port") or comp.get("mcp_port")
    return (_port_alive_sync(p) if p else False) or _pid_alive(name)




# ⚠️ MOVED HERE from app.py:1047-1140 by the router/core split (2026-08-28).
#    Port kills + port OWNERSHIP: process/port primitives, and the models lane
#    needs _kill_port_listener as much as the components lane does — leaving them
#    in the components router made components and models mutually dependent.

# ── Port kills: LISTENER-scoped only (live-incident fix, 2026-07-31) ──────────
# `lsof -ti tcp:PORT` matches EVERY process with a socket on that port — including
# CLIENTS with established connections. The bridge itself holds persistent httpx
# keep-alive connections to Odysseus (:7860) and the runner (:6767), so an unscoped
# port-kill from start_component.sh/stop SIGTERMed the BRIDGE (graceful "Shutting
# down" right after POST start). Every port-kill must target ONLY the listener.

# ⚠️ `_port_kill_cmd` AND `MOT_DECK_PORT_TAKEOVER` ARE GONE. No environment switch may
# turn a configured port into authority over a process. A collision is resolved by the
# user stopping the other application, never by M.O.T killing an unowned listener.


def _proc_cmdline(pid) -> str:
    """The full command line of a pid, whitespace-normalised ('' when unknown)."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))],
                             capture_output=True, text=True, check=False).stdout
        return " ".join(out.split())
    except Exception:
        return ""


def _cmd_is_under_root(cmd: str, root: str) -> bool:
    """Corroborating path evidence only; never sufficient signal authority."""
    if not cmd:
        return False
    r = str(root).rstrip("/")
    return bool(r) and (f"{r}/data/" in cmd or f"{r}/vendor/" in cmd)


def _proc_cwd(pid) -> str:
    """The working directory of a pid ('' when unknown). One lsof, best-effort."""
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(int(pid)), "-d", "cwd", "-Fn"],
                             capture_output=True, text=True, check=False).stdout
    except Exception:
        return ""
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:].strip()
    return ""


# ⚠️ AND THE COMMAND LINE IS NOT ALWAYS ENOUGH — MEASURED ON THE LIVE STACK, 2026-09-02.
# An audit of every pidfile against the path rule above turned up a component whose
# command line contains NO path at all:
#
#     odysseus  pid=18959  `python -m uvicorn app:app --host 127.0.0.1 --port 7860`
#
# start_component.sh cd's into vendor/odysseus and launches a RELATIVE command, so there
# is nothing in `ps` output to match — and the runner is the same shape
# (`data/llamacpp/build/bin/llama-server …`, relative to ROOT). A path-only reaper would
# therefore have REFUSED to stop Odysseus at all: the generic component Stop would have
# become a no-op with a polite sentence, which is a regression on a button Debi presses.
# (`_clear_port` in the shell survives this only because it checks the pidfile pid FIRST.)
#
# That observation once motivated a CWD fallback. The launch-provenance doctrine later
# rejected it: a user can manually start a process from this checkout. `_proc_cwd` and
# `_cmd_is_under_root` remain diagnostic compatibility helpers only; neither participates
# in a signal decision.
def _proc_birth(pid) -> str:
    """Kernel-reported process start stamp used to detect PID reuse."""
    return _ownership.process_birth(pid)


def _ownership_path(component: str) -> Path:
    return ROOT / "data" / f"{component}.owner"


def _read_ownership(component: str):
    """Read `v1<TAB>pid<TAB>birth`; malformed/legacy records authorize nothing."""
    return _ownership.read_claim(ROOT, component)


def _ownership_matches(pid, component) -> bool:
    """Exact child-handle record + exact kernel birth stamp; paths/names are irrelevant."""
    try:
        return _ownership.ownership_matches(ROOT, component, int(pid))
    except Exception:
        return False


def _kill_port_listener(port: int, force: bool = False, component=None) -> list:
    """Signal only listeners covered by an exact M.O.T launch-provenance claim.

    Paths and process names are diagnostic context, never authority. The returned
    list contains refusal messages; an empty list means nothing was refused.
    """
    port = int(port)
    refused = []
    for pid in _port_listener_pids(port):
        cmd = _proc_cmdline(pid)
        claim = _read_ownership(component) if component else None
        expected_birth = claim[1] if claim and claim[0] == int(pid) else ""
        try:
            signalled, detail = _ownership.signal_owned(
                ROOT, component, expected_pid=int(pid),
                expected_birth=expected_birth, force=force,
                # Graceful callers need the same claim for their post-signal wait and
                # possible retry. A force signal may retire immediately.
                retire=force)
        except Exception as exc:
            signalled, detail = False, str(exc)
        if not signalled:
            refused.append(
                f"port :{port} is held by pid {pid} ({cmd}) without a matching M.O.T "
                f"launch record — refusing to kill it; stop that application explicitly"
                + (f" ({detail})" if detail else ""))
    return refused


def _port_listener_pids(port: int) -> list:
    """PIDs currently LISTENING on tcp:port (empty list when the port is free)."""
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{int(port)}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, check=False).stdout
        return [p for p in out.split() if p.strip()]
    except Exception:
        return []


# ── PIDFILE-FIRST, IDENTITY-VERIFIED STOPS IN PYTHON (U64, 2026-09-02) ────────
# The PROCESS-KILL RULE was fenced in the shell and UNFENCED in Python, so five
# `pkill -f` calls were still living in bridge/routers/ — including `_aux_kill` running
# the EXACT `llama-server.*--port <port>` pattern U19 tore out of start_component.sh,
# and `pkill -f "start_component.sh runner"`, which reaches the start script of ANY
# motdeck root on the machine (the repo's included). A pattern is not an identity.
#
# This is the shell's `_reap_pidfile` (scripts/start_component.sh) in Python, with the
# same semantics on purpose — one discipline, two languages:
#
#   1. THE PIDFILE NAMES THE PID. We never search for a process; we read the pid we
#      ourselves wrote down.
#   2. IDENTITY IS RE-VERIFIED BEFORE THE SIGNAL. Pids are recycled, so a stale pidfile
#      must never become a stranger's death warrant: the launch record's PID and
#      kernel birth fingerprint must still match. Names, paths and CWD are not proof.
#   3. NO PIDFILE, OR IDENTITY FAILS → WE REFUSE, IN A SENTENCE. There is no fallback
#      to a name sweep. A refusal the user can read outranks a kill they did not ask
#      for; that ranking is the doctrine's, and it is the whole point of the rule.
#
# Returns a list of NOTES (the sentences). An EMPTY list means the signal was sent.
# The absent-pidfile sentence, named so a caller that has a SECOND legitimate identity
# route (the ownership-checked port kill) can drop it: "there was no pidfile" is not a
# refusal, it is nothing-to-do, and printing it after "nothing was listening on :6768"
# is noise on the one path a user hits by accident. An IDENTITY REFUSAL is never
# dropped — that one is the whole point.
NO_PIDFILE_NOTE = "nothing we can prove is ours to stop"


def reap_pidfile(component: str, force: bool = False, *, retire: bool = True) -> list:
    """Stop exactly the recorded child, only while its birth fingerprint still matches."""
    pf = ROOT / "data" / f"{component}.pid"
    record = _read_ownership(component)
    if not record:
        # The compatibility pidfile cannot authorize a signal on its own. The shared
        # locked primitive discards it without racing a cooperating relaunch.
        raw_pid = _ownership.read_pid_report(ROOT, component) or 0
        if os.path.lexists(pf):
            # No owner claim means no signal can be sent. This call exists only to
            # discard the legacy/non-regular report under the shared claim lock.
            _ownership.signal_owned(
                ROOT, component, expected_pid=raw_pid, expected_birth="", force=force)
        if raw_pid:
            return [f"data/{component}.pid names pid {raw_pid} but has no matching "
                    "M.O.T launch record; leaving the process alone and discarding "
                    "only the legacy reporting file"]
        return [f"no complete data/{component}.owner claim — {NO_PIDFILE_NOTE} "
                "(refusing to search for one by name)"]
    pid = record[0]
    cmd = _proc_cmdline(pid)
    try:
        signalled, detail = _ownership.signal_owned(
            ROOT, component, expected_pid=pid, expected_birth=record[1],
            force=force, retire=retire)
    except Exception as exc:
        signalled, detail = False, str(exc)
    if not signalled:
        return [f"data/{component}.pid names pid {pid} ({cmd}) but has no matching "
                f"M.O.T launch record (legacy/stale/recycled); leaving it alone"
                + (f" ({detail})" if detail else "")]
    return []


def stop_owned_component(component: str, port: "int | None" = None,
                         *, force: bool = True, wait_seconds: float = 3.0) -> list:
    """Stop and verify one exact M.O.T-launched generation.

    The launch record is checked even before the child has opened its socket.  The
    claim is retained through the signal/wait transaction, then retired only after
    that exact PID+birth is gone.  A port is a postcondition and collision detector;
    it never supplies ownership authority.

    Returns refusal/failure sentences.  An empty list means the exact child is gone
    (or no child/listener existed) and the configured port is not held by a stranger.
    """
    component = str(component or "")
    claim = _read_ownership(component)
    pidfile = ROOT / "data" / f"{component}.pid"
    if not claim:
        if os.path.lexists(pidfile) or os.path.lexists(_ownership_path(component)):
            # This also discards only legacy/stale bookkeeping under the shared lock.
            return reap_pidfile(component, force=force)
    else:
        pid, birth = claim
        try:
            signalled, detail = _ownership.signal_owned(
                ROOT, component, expected_pid=pid, expected_birth=birth,
                force=force, retire=False)
        except Exception as exc:
            signalled, detail = False, str(exc)
        if not signalled:
            return [f"recorded {component} pid {pid} was not signalled; its exact "
                    f"launch claim was retained ({detail})"]

        deadline = time.monotonic() + max(0.0, float(wait_seconds))
        while time.monotonic() < deadline:
            if _ownership.process_birth(pid) != birth:
                break
            time.sleep(0.05)
        if _ownership.process_birth(pid) == birth:
            return [f"recorded {component} pid {pid} survived "
                    f"{'SIGKILL' if force else 'SIGTERM'}; its exact launch claim "
                    "was retained and no replacement was started"]
        _ownership.retire_owned(ROOT, component, pid, birth)

    if port is not None:
        listeners = _port_listener_pids(int(port))
        if listeners:
            detail = []
            for raw_pid in listeners:
                cmd = _proc_cmdline(raw_pid)
                detail.append(f"pid {raw_pid} ({cmd})")
            return [f"port :{int(port)} is still held by " + ", ".join(detail)
                    + " without a matching live M.O.T launch record — refusing to "
                      "signal it; stop that application explicitly"]
    return []


def write_pidfile(component: str, pid: int) -> None:
    """Record an actual child handle with a PID-reuse-resistant birth fingerprint."""
    _ownership.record_child(ROOT, component, int(pid))


def _script_tracked(name: str, *args: str, track: str, timeout: int = 1800):
    """`_script`, but the child's pid is recorded in data/<track>.pid while it runs.

    Exists so a LONG-RUNNING script can be cancelled by identity instead of by name:
    /api/models/switch-cancel used to `pkill -f "start_component.sh runner"`, which
    matches that script in EVERY motdeck root on the machine, the repo's included."""
    p = ROOT / "scripts" / name
    argv = [str(p), *args]
    if p.is_file() and not os.access(p, os.X_OK):
        print(f"[bridge] {name} is not executable — running it via bash "
              f"(fix with: chmod +x scripts/{name})", flush=True)
        argv = ["/bin/bash", str(p), *args]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=ROOT)
    try:
        write_pidfile(track, proc.pid)
    except Exception:
        proc.terminate()                  # exact child handle; no inferred ownership
        proc.communicate()
        raise
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()                       # OUR OWN child handle — no name, no pattern
        out, err = proc.communicate()
        raise
    finally:
        # If cancellation already retired the claim this is a no-op. If a new child
        # somehow claimed the same track name, exact release cannot erase it.
        _ownership.release_owned(ROOT, track, proc.pid)
    return subprocess.CompletedProcess(argv, proc.returncode, out or "", err or "")


# ⚠️ MOVED HERE from app.py:2484-2489 by the router/core split (2026-08-28).
#    _registry_models is a manifest read (data/models.json) that the model-
#    identity core needs; it sat under the RAM-ledger comment but is not part of
#    the ledger.

def _registry_models() -> list:
    import json as _json
    try:
        return _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        return []
