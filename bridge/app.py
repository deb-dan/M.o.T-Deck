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
            "pip install vendor/hermes (a few hundred MB of dependencies)",
            "Build Hermes's own web dashboard UI (npm --workspace web → web_dist, gitignored)",
            "Model provider points at the runner endpoint (patched on Start)",
            "Serve on port 9119 when started (hermes dashboard: web UI + JSON-RPC/WS API)",
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


# ── Rung D: native chat pane — Bridge-side proxy to Odysseus's API ────────────
# The panel (:8700) cannot call Odysseus (:7860) from the browser (CORS default
# allows only portless localhost origins), so the Bridge proxies server-to-server,
# holding an admin login session (cookie `odysseus_session`, 7-day TTL, re-login on 401).
from fastapi import Request
from fastapi.responses import StreamingResponse

ODY_BASE = "http://127.0.0.1:7860"
_ody = httpx.AsyncClient(base_url=ODY_BASE, timeout=httpx.Timeout(30, read=None))


async def _ody_login() -> bool:
    comp = cfg().get("components", {}).get("odysseus", {})
    r = await _ody.post("/api/auth/login", json={
        "username": comp.get("admin_user", "admin"),
        "password": comp.get("admin_password", "admin123"),
        "remember": True, "totp_code": None})
    return r.status_code == 200 and r.json().get("ok") is True


async def _ody_req(method: str, path: str, **kw) -> httpx.Response:
    r = await _ody.request(method, path, **kw)
    if r.status_code in (401, 403):          # session expired/absent → login once, retry
        if await _ody_login():
            r = await _ody.request(method, path, **kw)
    return r


@app.get("/api/ody/health")
async def ody_health() -> dict:
    try:
        r = await _ody_req("GET", "/api/sessions")
        return {"up": r.status_code == 200}
    except Exception:
        return {"up": False}


@app.post("/api/ody/ensure-session")
async def ody_ensure_session(req: Request) -> JSONResponse:
    """Find (by name) or create the pane's chat session, bound to the default endpoint."""
    body = await req.json()
    name = body.get("name") or "Mission Control"
    try:
        r = await _ody_req("GET", "/api/sessions")
        if r.status_code == 200:
            for s in r.json():
                if s.get("name") == name and not s.get("archived"):
                    return JSONResponse({"id": s["id"], "model": s.get("model"), "reused": True})
        r = await _ody_req("POST", "/api/session",
                           data={"name": name, "endpoint_id": "local-jan"})
        if r.status_code == 200:
            j = r.json()
            return JSONResponse({"id": j["id"], "model": j.get("model"), "reused": False})
        return JSONResponse({"error": r.text[:500]}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.get("/api/ody/sessions")
async def ody_sessions() -> JSONResponse:
    """List the user's chat sessions (newest first) for the pane's session rail."""
    try:
        r = await _ody_req("GET", "/api/sessions")
        if r.status_code != 200:
            return JSONResponse([])
        out = [{
            "id": s.get("id"),
            "name": (s.get("name") or "Untitled"),
            "model": s.get("model"),
            "updated_at": s.get("last_message_at") or s.get("updated_at") or s.get("created_at"),
            "message_count": s.get("message_count", 0),
        } for s in r.json() if s.get("id")]
        out.sort(key=lambda x: x["updated_at"] or "", reverse=True)
        return JSONResponse(out)
    except Exception:
        return JSONResponse([])


@app.post("/api/ody/session/new")
async def ody_session_new(req: Request) -> JSONResponse:
    """Create a fresh chat session bound to the default (local-jan) endpoint."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body.get("name") or "New chat").strip() or "New chat"
    try:
        r = await _ody_req("POST", "/api/session", data={"name": name, "endpoint_id": "local-jan"})
        if r.status_code == 200:
            j = r.json()
            return JSONResponse({"id": j["id"], "name": name, "model": j.get("model")})
        return JSONResponse({"error": r.text[:500]}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/session/{sid}/rename")
async def ody_session_rename(sid: str, req: Request) -> JSONResponse:
    try:
        name = (await req.json()).get("name", "").strip()
    except Exception:
        name = ""
    if not name:
        return JSONResponse({"ok": False, "log": "empty name"}, status_code=400)
    try:
        r = await _ody_req("PATCH", f"/api/session/{sid}", data={"name": name})
        return JSONResponse({"ok": r.status_code == 200, "name": name})
    except Exception:
        return JSONResponse({"ok": False})


@app.post("/api/ody/session/{sid}/duplicate")
async def ody_session_duplicate(sid: str, req: Request) -> JSONResponse:
    """Duplicate a session (Odysseus fork, copying all messages), then name it '<src> (copy)'."""
    try:
        name = (await req.json()).get("name", "").strip()
    except Exception:
        name = ""
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/fork", json={"keep_count": 1_000_000})
        if r.status_code != 200:
            return JSONResponse({"error": r.text[:500]}, status_code=502)
        new_id = r.json().get("id")
        if new_id and name:
            await _ody_req("PATCH", f"/api/session/{new_id}", data={"name": name})
        return JSONResponse({"id": new_id, "name": name})
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/session/{sid}/delete")
async def ody_session_delete(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/delete")
        return JSONResponse({"ok": r.status_code == 200})
    except Exception:
        return JSONResponse({"ok": False})


@app.get("/api/ody/history/{sid}")
async def ody_history(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("GET", f"/api/history/{sid}")
        return JSONResponse(r.json() if r.status_code == 200 else {"history": []})
    except Exception:
        return JSONResponse({"history": []})


@app.post("/api/ody/chat")
async def ody_chat(req: Request) -> StreamingResponse:
    """Stream a chat turn: re-emit Odysseus's SSE (delta / tool events / [DONE]) to the panel."""
    body = await req.json()
    fields = {
        "session": body.get("session", ""),
        "message": body.get("message", ""),
        "mode": body.get("mode", "agent"),
        "allow_web_search": "true" if body.get("allow_web_search", True) else "false",
        "allow_bash": "true" if body.get("allow_bash", False) else "false",
    }

    async def gen():
        try:
            async with _ody.stream("POST", "/api/chat_stream", data=fields,
                                   headers={"X-Tz-Offset": str(body.get("tz_offset", 0))}) as r:
                if r.status_code in (401, 403):
                    await _ody_login()
                    yield 'data: {"type":"retry"}\n\n'
                    async with _ody.stream("POST", "/api/chat_stream", data=fields) as r2:
                        async for chunk in r2.aiter_raw():
                            yield chunk
                    return
                async for chunk in r.aiter_raw():
                    yield chunk
        except Exception as e:
            yield f'data: {{"type":"proxy_error","error":"{str(e)[:200]}"}}\n\n'
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Models pane (M2) — list installed via `jan models list`, switch the runner ──
def _jan_bin() -> str:
    import os, shutil
    for p in (shutil.which("jan"), os.path.expanduser("~/.local/bin/jan"), "/usr/local/bin/jan"):
        if p and os.path.exists(p):
            return p
    return "jan"


def _set_runner_model(new_id: str) -> None:
    """Rewrite runner.model in harness.yaml (line-scan, preserves everything else)."""
    import re
    p = ROOT / "harness.yaml"
    lines = p.read_text().split("\n")
    in_runner = False
    for i, ln in enumerate(lines):
        if re.match(r'^runner:\s*$', ln):
            in_runner = True; continue
        if in_runner and re.match(r'^\S', ln):
            in_runner = False
        if in_runner and re.match(r'^  model:', ln):
            lines[i] = f"  model: {new_id}"
            break
    p.write_text("\n".join(lines))


@app.get("/api/models")
def api_models() -> JSONResponse:
    """Installed models (`jan models list` → JSON), plus the active runner model + state."""
    import json as _json
    installed, err = [], None
    try:
        r = subprocess.run([_jan_bin(), "models", "list"],
                           capture_output=True, text=True, timeout=25)
        for m in _json.loads(r.stdout or "[]"):
            installed.append({
                "id": m.get("id"), "name": m.get("name") or m.get("id"),
                "size_bytes": m.get("size_bytes"), "engine": m.get("engine"),
                "embedding": bool(m.get("embedding")),
                "capabilities": m.get("capabilities") or []})
    except Exception as e:
        err = str(e)[:200]
    rc = cfg().get("runner", {})
    port = rc.get("port")
    return JSONResponse({
        "installed": installed, "active": rc.get("model"),
        "runner_up": _port_alive_sync(int(port)) if port else False,
        "error": err})


_SWITCH = {"busy": False, "log": ""}


def _do_switch(new_id: str, restart_hermes: bool, restart_ody: bool) -> None:
    try:
        _SWITCH.update(busy=True, log=f"loading {new_id}…")
        _script("start_component.sh", "runner")
        if restart_hermes:
            _SWITCH["log"] = "re-wiring Hermes…"; _script("start_component.sh", "hermes")
        if restart_ody:
            _SWITCH["log"] = "re-wiring Odysseus…"; _script("start_component.sh", "odysseus")
        _SWITCH["log"] = f"active: {new_id}"
    except Exception as e:
        _SWITCH["log"] = f"switch error: {str(e)[:200]}"
    finally:
        _SWITCH["busy"] = False


@app.post("/api/models/switch")
async def api_switch_model(req: Request) -> JSONResponse:
    """Switch the runner's model (also loads/downloads it), then re-fan-out the new
    model NAME to any running Hermes/Odysseus (their configs bind the name). Runs in
    the background — poll /api/models/switch-status. `id` may be a local id OR a
    HuggingFace repo id (jan serve auto-downloads)."""
    if _SWITCH["busy"]:
        return JSONResponse({"ok": False, "log": "a switch is already in progress"}, status_code=409)
    new_id = ((await req.json()).get("id") or "").strip()
    if not new_id:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    c = cfg()
    hermes_up, ody_up = _running_sync("hermes", c), _running_sync("odysseus", c)
    _set_runner_model(new_id)
    threading.Thread(target=_do_switch, args=(new_id, hermes_up, ody_up), daemon=True).start()
    return JSONResponse({"ok": True, "log": "switch started"})


@app.get("/api/models/switch-status")
def api_switch_status() -> JSONResponse:
    return JSONResponse(dict(_SWITCH))


# ── Slice 2: HuggingFace model browser (Bridge runs on the Mac → real internet) ──
_HF = httpx.AsyncClient(base_url="https://huggingface.co", timeout=httpx.Timeout(20, read=30))


@app.get("/api/models/hf")
async def hf_search(q: str = "", limit: int = 20) -> JSONResponse:
    """Search HuggingFace for GGUF models, most-downloaded first."""
    q = (q or "").strip()
    if not q:
        return JSONResponse([])
    try:
        r = await _HF.get("/api/models", params={
            "search": q, "filter": "gguf", "sort": "downloads", "limit": limit})
        out = [{"repo": m.get("id") or m.get("modelId"),
                "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                "pipeline": m.get("pipeline_tag"), "updated": m.get("createdAt")}
               for m in (r.json() if r.status_code == 200 else []) if (m.get("id") or m.get("modelId"))]
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.get("/api/models/hf/files")
async def hf_files(repo: str) -> JSONResponse:
    """GGUF files (name + size) in a repo, for the LM-Studio-style detail + fit pill."""
    try:
        meta = await _HF.get(f"/api/models/{repo}")
        tree = await _HF.get(f"/api/models/{repo}/tree/main")
        files = []
        if tree.status_code == 200:
            for it in tree.json():
                path = it.get("path", "")
                if path.lower().endswith(".gguf"):
                    files.append({"filename": path, "size_bytes": it.get("size")})
        m = meta.json() if meta.status_code == 200 else {}
        return JSONResponse({"repo": repo, "files": files,
                             "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                             "tags": m.get("tags", [])})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.post("/api/open")
async def open_external(req: Request) -> JSONResponse:
    """Open an http(s) URL in the user's default browser (panel links inside the app's webview)."""
    url = (await req.json()).get("url", "")
    if not (url.startswith("http://") or url.startswith("https://")):
        return JSONResponse({"ok": False, "log": "only http(s) urls"}, status_code=400)
    subprocess.run(["open", url], check=False)
    return JSONResponse({"ok": True})


@app.post("/api/ody/stop/{sid}")
async def ody_stop(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("POST", f"/api/chat/stop/{sid}")
        return JSONResponse({"ok": r.status_code == 200})
    except Exception:
        return JSONResponse({"ok": False})
