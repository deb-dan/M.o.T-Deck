"""M.O.T-owned lifecycle controls for Hermes messaging channels.

The vendored Hermes dashboard remains unmodified. This narrow adapter exists because
Hermes currently persists WhatsApp enablement to two authorities but its generic
toggle updates only one of them.
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import subprocess
from pathlib import Path

from fastapi import HTTPException

from ..core.appctx import ROOT, app
from ..core import ownership as _ownership
from ..core.hermescfg import _hermes_config_path
from ..core.procs import (
    _ownership_matches,
    _ownership_path,
    _port_alive_sync,
    _read_ownership,
    cfg,
    _script,
)


def _hermes_launch_state() -> str:
    """Return ``owned-running``, ``stopped``, or ``ambiguous``.

    The owner record is authority and the PID file is only corroborating evidence.
    In particular, losing the reporting PID file while an exact child is still in
    pre-bind startup must not make the configuration safe to edit. Conversely, a
    legacy/live PID report without a valid owner record is observable uncertainty,
    not permission to race that process.
    """
    claim = _read_ownership("hermes")
    owner_path = _ownership_path("hermes")
    owner_exists = owner_path.exists() or getattr(owner_path, "is_symlink", lambda: False)()
    if claim:
        return "owned-running" if _ownership_matches(claim[0], "hermes") else "stopped"
    if owner_exists:
        return "ambiguous"  # malformed authority record; fail closed

    reported_pid = _ownership.read_pid_report(ROOT, "hermes")
    try:
        if reported_pid is None:
            return "ambiguous" if os.path.lexists(ROOT / "data" / "hermes.pid") else "stopped"
        os.kill(reported_pid, 0)  # existence probe only; never a signal decision
        return "ambiguous"
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        return "ambiguous"
    except OSError as exc:
        # Only ESRCH proves absence. Permission failures and every other kernel
        # response leave a possibly live process which M.O.T cannot identify.
        return "stopped" if exc.errno == errno.ESRCH else "ambiguous"


def _whatsapp_helper(*args: str) -> dict:
    helper = ROOT / "scripts" / "reconcile_hermes_whatsapp.py"
    if not helper.is_file():
        raise RuntimeError("the WhatsApp state helper is missing from this snapshot")
    python = ROOT / "data" / "hermes-venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("the pinned Hermes Python environment is missing")
    home = str(Path(_hermes_config_path()).parent)
    result = subprocess.run(
        [str(python), str(helper), "--home", home, *args],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "state transaction failed").strip()
        raise RuntimeError(detail[:1000])
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("the WhatsApp state helper returned unreadable output") from exc
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeError("the WhatsApp state helper did not confirm its transaction")
    return value


@app.get("/api/hermes/channels/whatsapp")
async def hermes_whatsapp_status():
    try:
        return await asyncio.to_thread(_whatsapp_helper, "--status")
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/hermes/channels/whatsapp/disable")
async def hermes_whatsapp_disable():
    """Quiesce Hermes, disable both authorities, preserve login, then restart.

    Stopping first is part of the transaction boundary: Hermes itself writes
    ``config.yaml``, so editing while its exact owned child is live would leave an
    uncoordinated writer racing the two-file reconciliation.
    """
    launch_state = _hermes_launch_state()
    was_running = launch_state == "owned-running"
    port = ((cfg().get("components") or {}).get("hermes") or {}).get("port")
    if launch_state == "ambiguous" or (
            port and _port_alive_sync(int(port)) and not was_running):
        raise HTTPException(
            409, "WhatsApp was not changed because Hermes process state is observable "
                 "but lacks an exact M.O.T launch claim. Stop that process explicitly, "
                 "then retry.")
    if was_running:
        stopped = await asyncio.to_thread(_script, "stop.sh", "hermes", timeout=60)
        if stopped.returncode:
            raise HTTPException(500, "WhatsApp was not changed because M.O.T could not stop its Hermes child: "
                                + (stopped.stderr or stopped.stdout or "no output")[-800:])

    try:
        state = await asyncio.to_thread(_whatsapp_helper, "--set", "disabled")
    except Exception as exc:
        recovery = ""
        if was_running:
            restored = await asyncio.to_thread(
                _script, "start_component.sh", "hermes", timeout=180)
            recovery = (" Hermes was restarted with the prior on-disk state."
                        if restored.returncode == 0 else
                        " Hermes was stopped and its recovery restart also failed: "
                        + (restored.stderr or restored.stdout or "no output")[-600:])
        raise HTTPException(500, "WhatsApp state was not changed: " + str(exc) + recovery) from exc

    restarted = False
    if was_running:
        started = await asyncio.to_thread(_script, "start_component.sh", "hermes", timeout=180)
        if started.returncode:
            raise HTTPException(500, "WhatsApp is disabled on disk and Hermes stopped, but restart failed: "
                                + (started.stderr or started.stdout or "no output")[-800:])
        restarted = True
    return {**state, "restarted": restarted, "credentials_preserved": True}
