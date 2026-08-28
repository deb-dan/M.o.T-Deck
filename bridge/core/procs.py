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

def _port_kill_cmd(port: int, force: bool = False) -> str:
    """Pure (unit-tested): shell command that kills ONLY the listener on tcp:port."""
    sig = "-9 " if force else ""
    return f"lsof -ti tcp:{int(port)} -sTCP:LISTEN | xargs kill {sig}2>/dev/null"


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
    if os.environ.get("HARNESS_PORT_TAKEOVER") == "1":
        subprocess.run(_port_kill_cmd(port, force), shell=True, check=False)
        return []
    refused = []
    for pid in _port_listener_pids(port):
        cmd = _proc_cmdline(pid)
        if (_port_owner_pidfile_match(pid, component)
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
