"""Harness bridge — control panel + component lifecycle API.

M0/M1 scope: status, install (with plan → approve → execute), start/stop.
Gearbox (M2) and adapter/self-heal (M3) are stubs; see gearbox.py / adapter.py.
"""
from __future__ import annotations

import asyncio
import socket
import subprocess
import threading
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parent.parent
PANEL = Path(__file__).resolve().parent / "panel"

app = FastAPI(title="AI Harness Bridge")


def cfg() -> dict:
    return yaml.safe_load((ROOT / "harness.yaml").read_text())


def _script(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(ROOT / "scripts" / name), *args],
        capture_output=True, text=True, cwd=ROOT, timeout=1800,
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


async def _port_alive(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), timeout=0.5)
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


def _provision(target: str) -> None:
    """Run the dependency closure in order, publishing live state into PROV.
    Runs in a background thread so /api/status can report progress meanwhile."""
    c = cfg()
    order = _closure(target, c, [])
    PROV.clear()
    for n in order:
        PROV[n] = {"state": "pending", "detail": "queued"}
    for i, n in enumerate(order):
        if _running_sync(n, c):
            PROV[n] = {"state": "on", "detail": "already running"}
            _mark_expected(n)
            continue
        PROV[n] = {"state": "starting", "detail": _NOTES.get(n, "starting…")}
        r = _script("start_component.sh", n)
        if r.returncode == 0:
            PROV[n] = {"state": "on", "detail": "started"}
            _mark_expected(n)   # expected-up now; if it later dies → degraded
        else:
            PROV[n] = {"state": "failed", "detail": (r.stdout + r.stderr)[-1500:]}
            for m in order[i + 1:]:
                PROV[m] = {"state": "blocked", "detail": f"blocked by {n} failure"}
            return


@app.get("/")
def panel() -> FileResponse:
    return FileResponse(PANEL / "index.html")


@app.get("/api/status")
async def status() -> dict:
    import shutil
    c = cfg()
    du = shutil.disk_usage(ROOT)
    out = {
        "bridge": "ok",
        "disk": {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)},
        "components": {},
    }
    for name, comp in c["components"].items():
        port = comp.get("port") or comp.get("mcp_port")
        running = (await _port_alive(int(port)) if port else False) or _pid_alive(name)
        out["components"][name] = {
            "installed": bool(comp.get("installed")),
            "pin": str(comp.get("pin")),
            "running": running,
            "degraded": _expected_path(name).exists() and not running,
            "port": port,
        }
    # M1 runner slot: a managed component, but launched via the jan CLI (no git install).
    rc = c.get("runner")
    if rc:
        rport = rc.get("port")
        rrunning = await _port_alive(int(rport)) if rport else False
        out["components"]["runner"] = {
            "installed": True,  # the jan CLI is the "install"; always available once Jan ran once
            "pin": str(rc.get("model") or rc.get("adapter") or "jan"),
            "running": rrunning,
            "degraded": _expected_path("runner").exists() and not rrunning,
            "port": rport,
            "kind": "runner",
        }
    try:  # snapshot; a background provision thread may mutate PROV concurrently
        out["prov"] = {k: dict(v) for k, v in list(PROV.items())}
    except RuntimeError:
        out["prov"] = {}
    return out


@app.get("/api/logs/{name}")
def logs(name: str, lines: int = 40) -> dict:
    if name not in ("bridge", "hermes", "odysseus", "searxng", "runner"):
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    if not f.exists():
        return {"lines": []}
    return {"lines": f.read_text(errors="replace").splitlines()[-lines:]}


@app.get("/api/components/{name}/plan")
def install_plan(name: str) -> dict:
    """Dry-run: return the install plan text without executing anything."""
    plans = {
        "hermes": [
            "Create isolated venv at data/hermes-venv",
            "pip install vendor/hermes-agent (a few hundred MB of dependencies)",
            "Point Hermes model provider at the gearbox endpoint",
            "Expose Hermes MCP server on port 8721 when started",
        ],
        "odysseus": [
            "Create isolated venv at data/odysseus-venv",
            "pip install vendor/odysseus requirements (+ ddgs for web search)",
            "Run Odysseus setup (creates admin account, prints temp password to log)",
            "Serve natively on port 7860 (Metal-accelerated Cookbook)",
        ],
        "searxng": [
            "Clone searxng source into vendor/searxng (not on PyPI)",
            "Create venv data/searxng-venv + editable install (compiles some deps)",
            "Write localhost settings.yml (port 8080, JSON API on, limiter off)",
            "Serve privately on 127.0.0.1:8080 — Odysseus prefers it over DuckDuckGo automatically",
        ],
    }
    if name not in plans:
        raise HTTPException(404, "unknown component")
    return {"component": name, "plan": plans[name],
            "note": "Nothing runs until you click Approve."}


@app.post("/api/components/{name}/install")
def install(name: str) -> JSONResponse:
    """Execute the install after the panel's approve step."""
    if name not in ("hermes", "odysseus", "searxng"):
        raise HTTPException(404, "unknown component")
    script = "install_searxng.sh" if name == "searxng" else "install_component.sh"
    args = () if name == "searxng" else (name, "--yes")
    r = _script(script, *args)
    ok = r.returncode == 0
    return JSONResponse(
        {"ok": ok, "log": (r.stdout + r.stderr)[-4000:]},
        status_code=200 if ok else 500)


_NOTES = {"runner": "launches headless Jan + loads the model (~60–90s)"}


@app.get("/api/components/{name}/start-plan")
async def start_plan(name: str) -> dict:
    """The dependency-ordered list that a Start of `name` will bring up."""
    c = cfg()
    steps = []
    for n in _closure(name, c, []):
        steps.append({"name": n, "running": await _running(n, c), "note": _NOTES.get(n, "")})
    return {"target": name, "steps": steps,
            "to_start": [s["name"] for s in steps if not s["running"]]}


@app.post("/api/components/{name}/start")
def start(name: str) -> JSONResponse:
    """One-switch start: provision the whole dependency closure in a background thread,
    publishing live per-component state into PROV (read by /api/status). Returns at once."""
    threading.Thread(target=_provision, args=(name,), daemon=True).start()
    return JSONResponse({"ok": True, "log": "provisioning started"})


@app.post("/api/components/{name}/stop")
def stop(name: str) -> JSONResponse:
    _clear_expected(name)   # intentional stop → not "degraded", just "stopped"
    PROV.pop(name, None)    # drop any stale provisioning overlay for this component
    # Runner (jan) must be stopped by PORT — its child router survives a PID kill (spike learning).
    if name == "runner":
        rc = cfg().get("runner", {})
        port = rc.get("port")
        subprocess.run(f"lsof -ti tcp:{int(port)} | xargs kill -9", shell=True, check=False)
        (ROOT / "data" / "runner.pid").unlink(missing_ok=True)
        return JSONResponse({"ok": True})
    pid = ROOT / "data" / f"{name}.pid"
    if pid.exists():
        subprocess.run(["kill", pid.read_text().strip()], check=False)
        pid.unlink(missing_ok=True)
        return JSONResponse({"ok": True})
    # No pid file (e.g. the process was started outside the panel) — fall back to
    # killing whatever holds the component's port. Same lesson as the runner.
    comp = cfg().get("components", {}).get(name, {})
    port = comp.get("port") or comp.get("mcp_port")
    if port:
        subprocess.run(f"lsof -ti tcp:{int(port)} | xargs kill 2>/dev/null", shell=True, check=False)
        return JSONResponse({"ok": True, "log": f"no pid file — killed by port :{port}"})
    return JSONResponse({"ok": False, "log": "no pid file and no port to kill by"})


@app.post("/api/components/{name}/update")
def update(name: str) -> JSONResponse:
    """M1: blue-green update with contract tests. Stub for now."""
    return JSONResponse(
        {"ok": False, "log": "updater lands in M1 — see docs/harness-architecture.md §6.1"},
        status_code=501)
