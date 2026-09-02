"""CORE — config, the script runner, and the process/port primitives.

The bottom of the stack: harness.yaml access (`cfg`), the registry read
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
import yaml
from .appctx import ROOT



def cfg() -> dict:
    return yaml.safe_load((ROOT / "harness.yaml").read_text())


# ── THE RELEASE VERSION: ONE FILE, AND IT IS `VERSION` (U56, 2026-09-02) ──────
# There were two version numbers and the app displayed the dead one. `harness.yaml`
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
# READS it, and `harness.yaml version:` is GONE from the repo manifest. A syncing step
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


def harness_version() -> str:
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
    import os
    f = ROOT / "data" / f"{name}.pid"
    try:
        pid = int(f.read_text().strip())
        os.kill(pid, 0)
        return True
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

# ⚠️ `_port_kill_cmd` IS GONE (U64, 2026-09-02). It returned the shell string
#   lsof -ti tcp:PORT -sTCP:LISTEN | xargs kill
# for the HARNESS_PORT_TAKEOVER=1 branch of _kill_port_listener — an unowned port clear,
# which is the exact move that closed Debi's standalone Unsloth (2026-08-28) and goose
# Desktop (2026-08-29), and which the no-name-kills contract bans from every shell file
# in the tree with no exception list. An override does not need a second, uglier
# implementation: the takeover branch now walks the SAME listener-scoped pid list every
# other path walks (`_port_listener_pids`) and signals those pids directly, so there is
# exactly one way this layer finds a process and exactly one way it signals one. The
# only thing the env var still switches off is the OWNERSHIP CHECK, which is all it ever
# claimed to do.


# ── Port OWNERSHIP (ops slice, 2026-08-21) ───────────────────────────────────
# Listener-scoped is necessary but not sufficient: when a port collides with another
# app's server (Debi's STANDALONE Unsloth on :8888), a listener-scoped kill still kills
# a stranger. So a kill now needs positive evidence that the process is OURS.
# Signature names are kept narrow ON PURPOSE: a component's own NAME is never a
# signature, because a standalone install of that same component is exactly what this
# guard exists to protect.
_PORT_OWNER_SIGS = {
    # runner.binary may point at a backend outside the tree (the LM Studio fallback),
    # so the engine name is the honest signature here.
    "runner": ("llama-server", "mlx_lm.server", "mlx_vlm.server"),
    "aux": ("llama-server", "mlx_lm.server", "mlx_vlm.server"),
    # hermes may already be running from a different root (repo vs snapshot).
    "hermes": ("hermes dashboard", "hermes serve"),
}


def _proc_cmdline(pid) -> str:
    """The full command line of a pid, whitespace-normalised ('' when unknown)."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))],
                             capture_output=True, text=True, check=False).stdout
        return " ".join(out.split())
    except Exception:
        return ""


def _port_owner_verdict(cmd: str, root: str, component=None) -> bool:
    """Pure (unit-tested): does this command line look like a process WE launched?

    An EMPTY cmd means the process vanished between the probe and the check — there is
    nothing left to protect, so it is not treated as a foreign process."""
    if not cmd:
        return True
    r = str(root).rstrip("/")
    if r and (f"{r}/data/" in cmd or f"{r}/vendor/" in cmd):
        return True
    for sig in _PORT_OWNER_SIGS.get(component or "", ()):
        if sig in cmd:
            return True
    return False


# ── PATH-ONLY OWNERSHIP: THE QUESTION A PIDFILE ASKS (U64, 2026-09-02) ───────
# `_port_owner_verdict` answers "WHO MAY HOLD THIS PORT", and for runner/aux it accepts
# an ENGINE NAME, because our own launch legitimately runs a binary from outside the
# tree (the LM Studio / Jan fallback). That is a deliberate, ledgered widening (U19c) of
# a PORT decision.
#
# A PIDFILE asks a different question — "is the pid I wrote down still MY process?" —
# and the engine name is a catastrophic answer to it. MEASURED, on the live stack, with
# the first draft of reap_pidfile (2026-09-02): a foreign `llama-server` outside our
# ROOT, whose pid was planted in data/aux.pid to stand in for a RECYCLED pid, was
# SIGKILLed by POST /api/aux/stop — because the name matched. That is the exact class
# U64 exists to remove, rebuilt inside its own fix, and the adversarial pass caught it
# only because it was walked on real processes.
#
# So the reaper gets its own verdict, and it is PATH EVIDENCE ONLY: a command line that
# names a location inside our tree. No product name, no engine name, no exceptions. When
# our engine genuinely lives outside the tree, the pidfile reap REFUSES and the
# ownership-checked PORT kill (which may use the engine name) is what stops it — the
# layering the two questions deserved all along.
def _cmd_is_under_root(cmd: str, root: str) -> bool:
    """Pure. Does this command line name a path inside our tree? ('' = the process
    vanished between the probe and the check — nothing left to protect.)"""
    if not cmd:
        return True
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
# THE SECOND FACTOR IS THE PROCESS'S WORKING DIRECTORY, and it is the same KIND of
# evidence: a path inside our tree, observed on the live process, impossible to spoof by
# being named like one of our components. Debi's standalone Unsloth/Hermes/goose run out
# of their own installs, never with a cwd inside this harness.
def _pid_is_ours(pid, cmd: str, root: str) -> bool:
    """Is this live pid provably one of OUR processes? PATHS ONLY — command line first
    (cheap), then its working directory (one lsof). Never a product or engine NAME."""
    if _cmd_is_under_root(cmd, root):
        return True
    cwd = _proc_cwd(pid)
    r = str(root).rstrip("/")
    return bool(cwd) and bool(r) and (cwd == r or cwd.startswith(r + "/"))


def _port_owner_pidfile_match(pid, component) -> bool:
    """True when data/<component>.pid names exactly this pid (our own launch record)."""
    if not component:
        return False
    try:
        return (ROOT / "data" / f"{component}.pid").read_text().strip() == str(pid)
    except Exception:
        return False


def _kill_port_listener(port: int, force: bool = False, component=None) -> list:
    """Kill the listener(s) on tcp:port that look like OURS. Returns a list of refusal
    messages for listeners that did not (empty list = nothing was refused)."""
    port = int(port)
    takeover = os.environ.get("HARNESS_PORT_TAKEOVER") == "1"
    refused = []
    for pid in _port_listener_pids(port):
        cmd = _proc_cmdline(pid)
        if (takeover
                or _port_owner_pidfile_match(pid, component)
                or _port_owner_verdict(cmd, str(ROOT), component)):
            subprocess.run(["kill"] + (["-9"] if force else []) + [str(pid)], check=False)
        else:
            refused.append(
                f"port :{port} is held by pid {pid} ({cmd}) which does not look like "
                f"ours — refusing to kill it (set HARNESS_PORT_TAKEOVER=1 to override)")
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
# harness root on the machine (the repo's included). A pattern is not an identity.
#
# This is the shell's `_reap_pidfile` (scripts/start_component.sh) in Python, with the
# same semantics on purpose — one discipline, two languages:
#
#   1. THE PIDFILE NAMES THE PID. We never search for a process; we read the pid we
#      ourselves wrote down.
#   2. IDENTITY IS RE-VERIFIED BEFORE THE SIGNAL. Pids are recycled, so a stale pidfile
#      must never become a stranger's death warrant: the live command line has to be
#      provably OURS — A PATH INSIDE OUR TREE AND NOTHING ELSE (_pid_is_ours; the two
#      blocks above it record both measured incidents behind that rule).
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


def reap_pidfile(component: str, force: bool = False, sigs=()) -> list:
    """Stop the process data/<component>.pid names, if it is provably ours.

    `sigs`: extra command-line substrings that also prove ownership. Callers pass only
    ABSOLUTE paths under ROOT (e.g. the start script's own path) — never a product name,
    which is the thing this helper exists to protect."""
    pf = ROOT / "data" / f"{component}.pid"
    if not pf.exists():
        return [f"no data/{component}.pid — {NO_PIDFILE_NOTE} "
                f"(refusing to search for one by name)"]
    try:
        pid = int("".join(ch for ch in pf.read_text() if ch.isdigit()) or 0)
    except Exception:
        pid = 0
    if not pid:
        pf.unlink(missing_ok=True)
        return [f"data/{component}.pid held no readable pid — discarded it, signalled nothing"]
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pf.unlink(missing_ok=True)
        return [f"data/{component}.pid named pid {pid}, which is not running — "
                f"discarded the stale pidfile"]
    except PermissionError:
        # It exists and belongs to ANOTHER USER, so it cannot be a process we spawned.
        pf.unlink(missing_ok=True)
        return [f"data/{component}.pid names pid {pid}, which belongs to another user — "
                f"that is not our {component}; leaving it alone"]
    except Exception:
        pass
    cmd = _proc_cmdline(pid)
    # ⛔ PATH EVIDENCE ONLY (_pid_is_ours: our tree in the command line, or our tree as
    # its working directory) — never _port_owner_verdict, whose runner/aux arm accepts
    # an ENGINE NAME. See the two blocks above _pid_is_ours for both measured incidents.
    ours = (_pid_is_ours(pid, cmd, str(ROOT))
            or any(s and s in cmd for s in sigs))
    if not ours:
        pf.unlink(missing_ok=True)
        return [f"data/{component}.pid names pid {pid} ({cmd}) — that is NOT our "
                f"{component} (recycled pid?); leaving it alone and discarding the "
                f"stale pidfile"]
    subprocess.run(["kill"] + (["-9"] if force else []) + [str(pid)], check=False)
    pf.unlink(missing_ok=True)
    return []


def write_pidfile(component: str, pid: int) -> None:
    """Record OUR OWN child's pid so reap_pidfile has an identity to verify later.

    ⛔ Only ever called with a pid we just spawned. The pidfile is the one input
    reap_pidfile trusts on sight, so writing a pid we did not launch would turn this
    into a way to kill Debi's own copy of the same app (the shell says the same thing
    over _stamp_pidfile_from_port)."""
    try:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / f"{component}.pid").write_text(str(int(pid)))
    except Exception:
        pass


def _script_tracked(name: str, *args: str, track: str, timeout: int = 1800):
    """`_script`, but the child's pid is recorded in data/<track>.pid while it runs.

    Exists so a LONG-RUNNING script can be cancelled by identity instead of by name:
    /api/models/switch-cancel used to `pkill -f "start_component.sh runner"`, which
    matches that script in EVERY harness root on the machine, the repo's included."""
    p = ROOT / "scripts" / name
    argv = [str(p), *args]
    if p.is_file() and not os.access(p, os.X_OK):
        print(f"[bridge] {name} is not executable — running it via bash "
              f"(fix with: chmod +x scripts/{name})", flush=True)
        argv = ["/bin/bash", str(p), *args]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=ROOT)
    write_pidfile(track, proc.pid)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()                       # OUR OWN child handle — no name, no pattern
        out, err = proc.communicate()
        raise
    finally:
        (ROOT / "data" / f"{track}.pid").unlink(missing_ok=True)
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
