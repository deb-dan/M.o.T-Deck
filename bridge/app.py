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


def _runner_engine(rc: dict) -> str:
    """Human label for the engine the active model will run on (mirrors the
    start script's dispatch: gguf→llama.cpp, mlx→mlx-lm, mlx+vision→mlx-vlm)."""
    adapter = (rc.get("adapter") or "jan").strip()
    if adapter == "jan":
        return "jan"
    if adapter == "lmstudio":
        return "lmstudio"
    try:
        import json as _json
        models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
        m = next((x for x in models if x.get("id") == rc.get("model")), None)
    except Exception:
        m = None
    if adapter in ("auto", "mlx") and m and m.get("format") == "mlx":
        return "mlx-vlm · vision" if m.get("vision") else "mlx-lm"
    if adapter == "mlx":
        return "mlx-lm"
    return "llama.cpp"


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
    # M1 runner slot: a managed component (engine per model format since the llamacpp/mlx shift).
    rc = c.get("runner")
    if rc:
        rport = rc.get("port")
        rrunning = await _port_alive(int(rport)) if rport else False
        out["components"]["runner"] = {
            "installed": True,
            "pin": str(rc.get("model") or rc.get("adapter") or "jan"),
            "running": rrunning,
            "degraded": _expected_path("runner").exists() and not rrunning,
            "port": rport,
            "kind": "runner",
            "engine": _runner_engine(rc),
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
        # kill the jan supervisor too — it survives port-kills and accumulates
        subprocess.run(f'pkill -f "jan serve.*port[= ]{int(port)}"', shell=True, check=False)
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


def _set_yaml_model(block: str, new_id: str) -> None:
    """Rewrite <block>.model in harness.yaml (line-scan, preserves everything else)."""
    import re
    p = ROOT / "harness.yaml"
    lines = p.read_text().split("\n")
    inside = False
    for i, ln in enumerate(lines):
        if re.match(rf'^{block}:\s*$', ln):
            inside = True; continue
        if inside and re.match(r'^\S', ln):
            inside = False
        if inside and re.match(r'^  model:', ln):
            lines[i] = f"  model: {new_id}"
            break
    p.write_text("\n".join(lines))


def _set_runner_model(new_id: str) -> None:
    _set_yaml_model("runner", new_id)


@app.get("/api/models")
def api_models() -> JSONResponse:
    """Installed models (`jan models list` → JSON), plus the active runner model + state."""
    import json as _json
    installed, err = [], None
    c = cfg()
    rc = c.get("runner", {})
    adapter = (rc.get("adapter") or "jan")
    if adapter in ("llamacpp", "mlx", "auto"):
        def _load_registry():
            reg = ROOT / "data" / "models.json"
            if not reg.exists():
                subprocess.run(["python3", "scripts/seed_registry.py"],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=60, check=False)
            return _json.loads(reg.read_text()).get("models", [])
        try:
            try:
                models = _load_registry()
            except Exception:
                # missing/invalid → seed once and retry
                subprocess.run(["python3", "scripts/seed_registry.py"],
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=60, check=False)
                models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
            for m in models:
                installed.append({
                    "id": m.get("id"), "name": m.get("name") or m.get("id"),
                    "size_bytes": m.get("size_bytes"),
                    "engine": ("mlx" if m.get("format") == "mlx" else "llamacpp"),
                    "embedding": False,
                    "capabilities": (["vision"] if (m.get("vision") or m.get("mmproj")) else []),
                    "format": m.get("format", "gguf")})
        except Exception as e:
            err = str(e)[:200]
    else:
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
    port = rc.get("port")
    ax = c.get("aux", {}) or {}
    aux = {"model": ax.get("model") or "", "port": ax.get("port"),
           "up": _port_alive_sync(int(ax["port"])) if ax.get("port") else False}
    return JSONResponse({
        "installed": installed, "active": rc.get("model"),
        "runner_up": _port_alive_sync(int(port)) if port else False,
        "aux": aux, "adapter": adapter, "error": err})


_SWITCH = {"busy": False, "log": ""}
_JAN_DATA = None


def _jan_data_dir() -> str:
    global _JAN_DATA
    if _JAN_DATA is None:
        import os
        _JAN_DATA = os.path.expanduser("~/Library/Application Support/Jan/data")
    return _JAN_DATA


def _download_progress(since_ts: float):
    """Bytes Jan has written since the switch began (its models tree + HF cache):
    returns (sum, newest_name, {name_lower: size}) so status can match the growing
    file against the repo's known file sizes → real percentage + ETA."""
    import os
    total, newest = 0, ""
    newest_ts = 0.0
    fresh = {}
    for root in (os.path.join(_jan_data_dir(), "llamacpp"),
                 os.path.expanduser("~/.cache/huggingface")):
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                try:
                    st = os.stat(os.path.join(dirpath, fn))
                except OSError:
                    continue
                if st.st_mtime >= since_ts - 5:
                    total += st.st_size
                    fresh[fn.lower()] = max(fresh.get(fn.lower(), 0), st.st_size)
                    if st.st_mtime > newest_ts:
                        newest_ts, newest = st.st_mtime, fn
    return total, newest, fresh


def _do_switch(new_id: str, old_id: str, restart_hermes: bool, restart_ody: bool) -> None:
    """Fable QA hardening: check exit codes (a failed load must NOT report success),
    and roll harness.yaml back to the previous model on failure so the next Start
    uses a known-good model instead of retrying a broken one."""
    try:
        _SWITCH["log"] = (f"downloading + loading {new_id} — large downloads take minutes…"
                          if "/" in new_id else f"loading {new_id}…")
        r = _script("start_component.sh", "runner")
        if r.returncode != 0:
            _set_runner_model(old_id)   # rollback pin; runner is down but recoverable
            tail = (r.stdout + r.stderr)[-400:]
            _SWITCH["log"] = f"FAILED to load {new_id} — reverted to {old_id}. {tail}"
            return
        if restart_hermes:
            _SWITCH["log"] = "re-wiring Hermes…"
            if _script("start_component.sh", "hermes").returncode != 0:
                _SWITCH["log"] = f"active: {new_id} — but Hermes restart FAILED (see logs)"
                return
        if restart_ody:
            _SWITCH["log"] = "re-wiring Odysseus…"
            if _script("start_component.sh", "odysseus").returncode != 0:
                _SWITCH["log"] = f"active: {new_id} — but Odysseus restart FAILED (see logs)"
                return
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
    if (c.get("runner", {}) or {}).get("adapter") in ("llamacpp", "mlx", "auto") and "/" in new_id:
        return JSONResponse(
            {"ok": False, "log": "downloads arrive with the download manager (next slice) — this adapter loads only installed models"},
            status_code=400)
    old_id = (c.get("runner", {}) or {}).get("model") or ""
    hermes_up, ody_up = _running_sync("hermes", c), _running_sync("odysseus", c)
    import time as _t
    # set BEFORE the thread: no double-switch race; downloading flag drives live progress
    _SWITCH.update(busy=True, log="starting…", started=_t.time(),
                   downloading=("/" in new_id), prev_bytes=0, prev_ts=0.0, files={})
    if "/" in new_id:
        # Fetch the repo's file sizes so the growing file can be matched → % + ETA.
        try:
            import os as _os
            r = await _HF.get(f"/api/models/{new_id}/tree/main")
            if r.status_code == 200:
                _SWITCH["files"] = {
                    _os.path.basename(it.get("path", "")).lower(): it.get("size") or 0
                    for it in r.json()
                    if it.get("path", "").lower().endswith((".gguf", ".safetensors"))}
        except Exception:
            pass
    _set_runner_model(new_id)
    threading.Thread(target=_do_switch, args=(new_id, old_id, hermes_up, ody_up), daemon=True).start()
    return JSONResponse({"ok": True, "log": "switch started"})


@app.get("/api/models/switch-status")
def api_switch_status() -> JSONResponse:
    """Poll target. During an HF download, adds live bytes-on-disk + rate, computed
    from Jan's own files — real progress, not a 'be patient' string."""
    import time as _t
    out = {k: _SWITCH.get(k) for k in ("busy", "log")}
    if _SWITCH.get("busy") and _SWITCH.get("downloading"):
        try:
            total_fresh, fname, fresh = _download_progress(_SWITCH.get("started") or _t.time())
            repo_files = _SWITCH.get("files") or {}
            # Match the file(s) Jan is fetching against the repo's known sizes → % + ETA.
            done = total_fresh
            matches = [(repo_files[n], fresh[n]) for n in fresh if n in repo_files]
            dl_total = 0
            if matches:
                dl_total = sum(m[0] for m in matches)
                done = sum(m[1] for m in matches)
            now = _t.time()
            prev_b, prev_t = _SWITCH.get("prev_bytes") or 0, _SWITCH.get("prev_ts") or 0.0
            rate = (done - prev_b) / (now - prev_t) if prev_t and now > prev_t and done >= prev_b else 0
            _SWITCH.update(prev_bytes=done, prev_ts=now)
            out.update(dl_bytes=done, dl_rate=max(0, rate), dl_file=fname,
                       dl_phase=("downloading" if rate > 1e5 or done < 1e6 else "loading"))
            if dl_total:
                out["dl_total"] = dl_total
                if rate > 1e5 and dl_total > done:
                    out["dl_eta"] = int((dl_total - done) / rate)
        except Exception:
            pass
    return JSONResponse(out)


@app.post("/api/models/switch-cancel")
def api_switch_cancel() -> JSONResponse:
    """Cancel an in-flight download/switch: kill the jan serve processes AND the
    waiting start script — _do_switch then sees the failure and rolls the model
    pin back to the previous one automatically."""
    if not _SWITCH.get("busy"):
        return JSONResponse({"ok": False, "log": "no switch in progress"}, status_code=400)
    port = int((cfg().get("runner", {}) or {}).get("port") or 6767)
    subprocess.run(f'pkill -f "jan serve.*port[= ]{port}"', shell=True, check=False)
    subprocess.run(f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null", shell=True, check=False)
    subprocess.run('pkill -f "start_component.sh runner"', shell=True, check=False)
    return JSONResponse({"ok": True, "log": "cancelling — pin will revert to the previous model"})


# ── Aux runner (optional): a small second model on its own port for Odysseus's
# Background Tasks (titles, search-query gen, memory extraction) so they stop
# hogging the main runner's single slot. Model is user-chosen from installed
# models ("Set aux" in the Models pane) — never hardcoded.
@app.post("/api/aux/set")
async def aux_set(req: Request) -> JSONResponse:
    new_id = ((await req.json()).get("id") or "").strip()
    if not new_id:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    _set_yaml_model("aux", new_id)
    return JSONResponse({"ok": True, "model": new_id})


def _aux_kill(port: int) -> None:
    for pat in (f'jan serve.*port[= ]{port}', f'llama-server.*--port {port}',
                f'mlx_lm.server.*--port {port}', f'mlx_vlm.server.*--port {port}'):
        subprocess.run(f'pkill -f "{pat}"', shell=True, check=False)
    subprocess.run(f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null", shell=True, check=False)


@app.post("/api/aux/start")
def aux_start() -> JSONResponse:
    """Launch the aux model on its own port using the SAME engine dispatch as the
    main runner (registry format: gguf→llama-server, mlx→mlx servers). The old
    `jan serve` path knew nothing about harness-downloaded models."""
    import json as _json, os as _os, glob as _glob
    ax = cfg().get("aux", {}) or {}
    model, port = ax.get("model") or "", int(ax.get("port") or 6768)
    key = ax.get("api_key", "harness-aux")
    if not model:
        return JSONResponse({"ok": False, "log": "no aux model set — use 'Set aux' on an installed model"}, status_code=400)
    try:
        models = _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        models = []
    m = next((x for x in models if x.get("id") == model), None)
    if not m or not m.get("path"):
        return JSONResponse({"ok": False, "log": f"aux model '{model}' not in registry"}, status_code=400)
    fmt, path, mmproj = m.get("format", "gguf"), m["path"], m.get("mmproj")
    _aux_kill(port)
    if fmt == "mlx":
        venv = ROOT / "data" / "mlx-venv"
        if not (venv / "bin" / "python").exists():
            return JSONResponse({"ok": False, "log": "mlx runtime missing — run scripts/install_mlx.sh"}, status_code=500)
        mod = "mlx_vlm.server" if m.get("vision") else "mlx_lm.server"
        srv = venv / "bin" / mod
        cmd = ([str(srv)] if srv.exists() else [str(venv / "bin" / "python"), "-m", mod])
        cmd += ["--model", path, "--host", "127.0.0.1", "--port", str(port)]
    else:
        binp = (cfg().get("runner") or {}).get("binary") or ""
        if not binp:
            # SHARED binary-discovery order (keep identical in start_component.sh):
            #   explicit runner.binary → OUR pin (data/llamacpp) → Jan backends → LM Studio.
            pin_bin = str(ROOT / "data" / "llamacpp" / "build" / "bin" / "llama-server")
            if _os.path.isfile(pin_bin) and _os.access(pin_bin, _os.X_OK):
                binp = pin_bin
            else:
                cands = (sorted(_glob.glob(_os.path.expanduser(
                            "~/Library/Application Support/Jan/data/llamacpp/backends/*/macos-arm64/build/bin/llama-server")),
                            key=_os.path.getmtime, reverse=True)
                         or sorted(_glob.glob(_os.path.expanduser("~/.lmstudio/extensions/backends/*/llama-server")),
                            key=_os.path.getmtime, reverse=True))
                if not cands:
                    return JSONResponse({"ok": False, "log": "no llama-server binary found — run scripts/install_llamacpp.sh"}, status_code=500)
                binp = cands[0]
        helptxt = ""
        try:
            hp = subprocess.run([binp, "--help"], capture_output=True, text=True, timeout=15)
            helptxt = (hp.stdout or "") + (hp.stderr or "")
        except Exception:
            pass
        # Aux tasks are short — small ctx keeps the second model light in RAM.
        ctx = m.get("ctx") or 8192
        cmd = [binp, "--no-context-shift", "--host", "127.0.0.1", "--port", str(port),
               "--alias", model, "--ctx-size", str(ctx), "--no-cont-batching",
               "--cache-ram", "-1", "--fit", "off", "--model", path, "--parallel", "1"]
        if mmproj:
            cmd += ["--mmproj", mmproj]
        if "--api-key" in helptxt:
            cmd += ["--api-key", key]
    logf = open(ROOT / "data" / "logs" / "aux.log", "ab")
    subprocess.Popen(cmd, stdout=logf, stderr=logf, start_new_session=True)
    return JSONResponse({"ok": True, "log": "loading in background — refresh in ~20-60s"})


@app.post("/api/aux/stop")
def aux_stop() -> JSONResponse:
    ax = cfg().get("aux", {}) or {}
    _aux_kill(int(ax.get("port") or 6768))
    return JSONResponse({"ok": True})


# ── Slice 2: HuggingFace model browser (Bridge runs on the Mac → real internet) ──
_HF = httpx.AsyncClient(base_url="https://huggingface.co", timeout=httpx.Timeout(20, read=30))


@app.get("/api/models/hf")
async def hf_search(q: str = "", sort: str = "downloads", fmt: str = "gguf",
                    limit: int = 25) -> JSONResponse:
    """Search HuggingFace. sort: downloads | recent | match. fmt: gguf | mlx."""
    q = (q or "").strip()
    if not q:
        return JSONResponse([])
    params = {"search": q, "limit": limit}
    if fmt in ("gguf", "mlx"):
        params["filter"] = fmt
    if sort == "downloads":
        params["sort"] = "downloads"; params["direction"] = "-1"
    elif sort == "recent":
        params["sort"] = "lastModified"; params["direction"] = "-1"
    # sort == "match" → HuggingFace relevance ranking (no sort param)
    try:
        r = await _HF.get("/api/models", params=params)
        out = [{"repo": m.get("id") or m.get("modelId"),
                "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                "pipeline": m.get("pipeline_tag"),
                "updated": m.get("lastModified") or m.get("createdAt")}
               for m in (r.json() if r.status_code == 200 else []) if (m.get("id") or m.get("modelId"))]
        return JSONResponse(out)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.get("/api/models/hf/files")
async def hf_files(repo: str) -> JSONResponse:
    """Weight files + sizes for the detail/fit view. GGUF → per-file (each a model);
    else MLX (.safetensors) → the whole repo is one model (summed size)."""
    try:
        meta = await _HF.get(f"/api/models/{repo}")
        tree = await _HF.get(f"/api/models/{repo}/tree/main")
        gguf, mlx = [], []
        if tree.status_code == 200:
            for it in tree.json():
                p = it.get("path", ""); low = p.lower()
                if low.endswith(".gguf"):
                    gguf.append({"filename": p, "size_bytes": it.get("size")})
                elif low.endswith(".safetensors"):
                    mlx.append({"filename": p, "size_bytes": it.get("size")})
        m = meta.json() if meta.status_code == 200 else {}
        base = {"repo": repo, "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0), "tags": m.get("tags", [])}
        if gguf:
            return JSONResponse({**base, "kind": "gguf", "files": gguf})
        return JSONResponse({**base, "kind": "mlx", "files": mlx,
                             "total_size": sum((f["size_bytes"] or 0) for f in mlx)})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=502)


@app.get("/api/models/hf/card")
async def hf_card(repo: str) -> JSONResponse:
    """The model's README (front-matter stripped), rendered in-app instead of the browser."""
    try:
        r = await _HF.get(f"/{repo}/raw/main/README.md")
        text = r.text if r.status_code == 200 else ""
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                text = parts[2]
        return JSONResponse({"repo": repo, "markdown": text[:20000]})
    except Exception as e:
        return JSONResponse({"repo": repo, "markdown": "", "error": str(e)[:200]})


# ── Download manager (Bridge-owned, no Jan) ──────────────────────────────────
# Download the EXACT HuggingFace file the user clicks, into the harness's own
# models dir (data/models/<model-id>/), with visible progress, pause/resume/cancel
# and parallelism. HF `resolve` URLs 302 to a CDN off huggingface.co, so a
# follow_redirects client is used against the absolute URL.
import re as _dl_re

DOWNLOADS: dict = {}
_DL_SEQ = {"n": 0}
_DL = httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True)

_SPLIT_RE = _dl_re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$")


def _safe_dir(name: str) -> str:
    """Keep [A-Za-z0-9._-]; replace anything else with '-'."""
    return _dl_re.sub(r"[^A-Za-z0-9._-]", "-", name)


def _model_id_from_filename(filename: str) -> str:
    """Model id = filename stem minus '.gguf', with a trailing split suffix
    (-NNNNN-of-MMMMM) stripped. 'foo-Q4_K_M.gguf'→'foo-Q4_K_M';
    'bar-00001-of-00002.gguf'→'bar'."""
    stem = filename[:-5] if filename.lower().endswith(".gguf") else filename
    m = _dl_re.match(r"^(.*)-(\d{5})-of-(\d{5})$", stem)
    return m.group(1) if m else stem


def _split_files(filename: str) -> list:
    """If filename is a split part (…-NNNNN-of-MMMMM.gguf) return all parts in
    order (same prefix, 1..M); else just [filename]."""
    m = _SPLIT_RE.match(filename)
    if not m:
        return [filename]
    prefix, total = m.group(1), m.group(3)
    return [f"{prefix}-{i:05d}-of-{total}.gguf" for i in range(1, int(total) + 1)]


def _registry_add(entry: dict) -> None:
    """Read data/models.json, drop any model with the same id, append `entry`,
    atomic write (tmp + os.replace)."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or "models" not in data:
            data = {"models": []}
    except Exception:
        data = {"models": []}
    models = [m for m in data.get("models", []) if m.get("id") != entry.get("id")]
    models.append(entry)
    data["models"] = models
    reg.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)


def _dl_json(e: dict) -> dict:
    """JSON-safe view of a DOWNLOADS entry (drops the asyncio Task)."""
    return {k: v for k, v in e.items() if k != "task"}


def _dl_cleanup(e: dict) -> None:
    """Delete every file's .part and the model dir if it is left empty."""
    import os as _os
    last_dir = None
    for f in e["files"]:
        part = f["dest"] + ".part"
        try:
            if _os.path.exists(part):
                _os.remove(part)
        except OSError:
            pass
        last_dir = _os.path.dirname(f["dest"])
    try:
        if last_dir and _os.path.isdir(last_dir) and not _os.listdir(last_dir):
            _os.rmdir(last_dir)
    except OSError:
        pass


async def _run_download(dl_id: str) -> None:
    import os as _os, time as _t
    e = DOWNLOADS.get(dl_id)
    if not e:
        return
    try:
        for f in e["files"]:
            dest, total = f["dest"], f["total"]
            part = dest + ".part"
            # Already complete? (full-size dest present)
            if _os.path.exists(dest) and (total == 0 or _os.path.getsize(dest) == total):
                f["done"] = _os.path.getsize(dest)
                continue
            _os.makedirs(_os.path.dirname(dest), exist_ok=True)
            existing = _os.path.getsize(part) if _os.path.exists(part) else 0
            f["done"] = existing
            headers = {}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            url = "https://huggingface.co" + f["url"]
            last_ts, last_done = _t.time(), existing
            async with _DL.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    snip = ""
                    try:
                        snip = (await resp.aread())[:200].decode("utf-8", "replace")
                    except Exception:
                        pass
                    e["state"] = "error"
                    e["error"] = f"HTTP {resp.status_code}: {snip}"[:300]
                    return
                # A 200 to a Range request means the server ignored it → restart file.
                mode = "ab" if (existing > 0 and resp.status_code == 206) else "wb"
                if mode == "wb":
                    f["done"] = last_done = 0
                with open(part, mode) as out:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        st = e["state"]
                        if st == "paused":
                            return                     # keep .part; resume re-streams
                        if st == "cancelled":
                            break
                        out.write(chunk)
                        f["done"] += len(chunk)
                        now = _t.time()
                        dt = now - last_ts
                        if dt > 0:
                            inst = (f["done"] - last_done) / dt
                            e["rate"] = 0.7 * e["rate"] + 0.3 * inst
                            last_ts, last_done = now, f["done"]
            if e["state"] == "cancelled":
                break
            _os.replace(part, dest)
        if e["state"] == "cancelled":
            _dl_cleanup(e)
            return
        # All files complete → register the model.
        main_dest = e["files"][0]["dest"]
        mmproj_dest, nonmm = None, 0
        for f in e["files"]:
            if "mmproj" in _os.path.basename(f["dest"]).lower():
                mmproj_dest = f["dest"]
            else:
                nonmm += f["total"] or (_os.path.getsize(f["dest"])
                                        if _os.path.exists(f["dest"]) else 0)
        _registry_add({
            "id": e["model_id"], "name": e["model_id"], "format": "gguf",
            "path": main_dest, "mmproj": mmproj_dest, "size_bytes": nonmm,
            "ctx": None, "source": "download", "vision": bool(mmproj_dest)})
        e["state"] = "done"
    except Exception as ex:
        e["state"] = "error"
        e["error"] = str(ex)[:300]


@app.post("/api/dl/start")
async def dl_start(req: Request) -> JSONResponse:
    import os as _os
    body = await req.json()
    repo = (body.get("repo") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not repo or not filename:
        return JSONResponse({"ok": False, "log": "repo and filename required"}, status_code=400)
    model_id = _model_id_from_filename(filename)
    # Duplicate-start guard (Fable QA): a second Get on the same model while one is
    # in flight would spawn two tasks appending to the same .part → corruption.
    for other in DOWNLOADS.values():
        if other.get("model_id") == model_id and other.get("state") in ("downloading", "paused"):
            return JSONResponse(_dl_json(other))
    file_names = _split_files(filename)
    # Look up sizes + a single mmproj sibling from the repo tree.
    sizes, mmproj_name = {}, None
    try:
        r = await _HF.get(f"/api/models/{repo}/tree/main")
        if r.status_code == 200:
            tree = r.json()
            for it in tree:
                p = it.get("path", "")
                sizes[_os.path.basename(p)] = it.get("size") or 0
            mmprojs = [it.get("path", "") for it in tree
                       if "mmproj" in _os.path.basename(it.get("path", "")).lower()
                       and it.get("path", "").lower().endswith(".gguf")]
            if len(mmprojs) == 1:
                mmproj_name = mmprojs[0]
    except Exception:
        pass
    if mmproj_name and mmproj_name not in file_names:
        file_names.append(mmproj_name)
    dest_dir = ROOT / "data" / "models" / _safe_dir(model_id)
    files = []
    for name in file_names:
        base = _os.path.basename(name)
        dest = str(dest_dir / base)
        part = dest + ".part"
        done = _os.path.getsize(part) if _os.path.exists(part) else 0
        files.append({"name": name, "url": f"/{repo}/resolve/main/{name}",
                      "dest": dest, "total": int(sizes.get(base, 0)), "done": done})
    _DL_SEQ["n"] += 1
    dl_id = str(_DL_SEQ["n"])
    entry = {"id": dl_id, "repo": repo, "files": files, "state": "downloading",
             "error": None, "rate": 0.0, "model_id": model_id, "task": None}
    DOWNLOADS[dl_id] = entry
    entry["task"] = asyncio.create_task(_run_download(dl_id))
    return JSONResponse(_dl_json(entry))


@app.post("/api/dl/{dl_id}/pause")
async def dl_pause(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    if e["state"] == "downloading":
        e["state"] = "paused"        # the task returns on its next chunk
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/resume")
async def dl_resume(dl_id: str) -> JSONResponse:
    import os as _os
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    if e["state"] == "paused":
        for f in e["files"]:
            part = f["dest"] + ".part"
            f["done"] = (_os.path.getsize(part) if _os.path.exists(part)
                         else (_os.path.getsize(f["dest"]) if _os.path.exists(f["dest"]) else 0))
        e["rate"] = 0.0
        e["state"] = "downloading"
        e["task"] = asyncio.create_task(_run_download(dl_id))
    return JSONResponse(_dl_json(e))


@app.post("/api/dl/{dl_id}/cancel")
async def dl_cancel(dl_id: str) -> JSONResponse:
    e = DOWNLOADS.get(dl_id)
    if not e:
        return JSONResponse({"ok": False}, status_code=404)
    was = e["state"]
    e["state"] = "cancelled"
    task = e.get("task")
    # If nothing is actively streaming (paused/finished), clean up the partials here.
    if was in ("paused", "done", "error") or task is None or task.done():
        _dl_cleanup(e)
    return JSONResponse(_dl_json(e))


@app.get("/api/dl")
async def dl_list() -> JSONResponse:
    items = [_dl_json(e) for e in DOWNLOADS.values()]
    items.sort(key=lambda x: int(x["id"]), reverse=True)
    return JSONResponse(items)


# ── Direct chat lane (Fable, 2026-07-23) ─────────────────────────────────────
# Chat mode goes straight to the runner (Jan :6767), bypassing Odysseus's per-turn
# machinery AND its in-process model lock — root-caused: Odysseus fires auxiliary
# LLM calls (titles/memory/search-queries, logged 5-38s each) at the same single-slot
# runner, so chat turns queue behind them and lose the prompt cache. Agent mode
# still routes via Odysseus (tools live there). History is read from and persisted
# back to the Odysseus session, so the rail/history stay coherent.
_RUNNER = httpx.AsyncClient(timeout=httpx.Timeout(20, read=None))


@app.post("/api/chat/direct")
async def chat_direct(req: Request) -> StreamingResponse:
    body = await req.json()
    sid = body.get("session", "")
    user_msg = (body.get("message") or "").strip()
    rc = cfg().get("runner", {})
    base = (rc.get("endpoint") or "http://127.0.0.1:6767/v1").rstrip("/")
    key, model = rc.get("api_key", ""), rc.get("model", "")

    # Build messages: session history (if reachable) + the new user turn.
    messages = []
    if sid:
        try:
            h = await _ody_req("GET", f"/api/history/{sid}")
            if h.status_code == 200:
                for m in (h.json().get("history") or [])[-30:]:
                    if m.get("role") in ("user", "assistant") and m.get("content"):
                        messages.append({"role": m["role"], "content": m["content"]})
        except Exception:
            pass  # degrade: direct chat works even with Odysseus down
    messages.append({"role": "user", "content": user_msg})

    async def gen():
        import json as _json
        full, think_open = [], False
        try:
            async with _RUNNER.stream(
                "POST", f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": messages,
                      "stream": True, "cache_prompt": True},
            ) as r:
                if r.status_code != 200:
                    yield f'data: {{"type":"proxy_error","error":"runner {r.status_code}"}}\n\n'
                    yield "data: [DONE]\n\n"
                    return
                yield f'data: {_json.dumps({"type": "model_info", "model": model})}\n\n'
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        d = _json.loads(payload)["choices"][0]["delta"]
                    except Exception:
                        continue
                    # thinking arrives either as reasoning_content or inline <think> tags
                    rsn = d.get("reasoning_content")
                    if rsn:
                        yield f'data: {_json.dumps({"delta": rsn, "thinking": True})}\n\n'
                        continue
                    chunk = d.get("content") or ""
                    if not chunk:
                        continue
                    while chunk:
                        if think_open:
                            end = chunk.find("</think>")
                            if end == -1:
                                yield f'data: {_json.dumps({"delta": chunk, "thinking": True})}\n\n'
                                chunk = ""
                            else:
                                if chunk[:end]:
                                    yield f'data: {_json.dumps({"delta": chunk[:end], "thinking": True})}\n\n'
                                chunk = chunk[end + 8:]
                                think_open = False
                        else:
                            start = chunk.find("<think>")
                            if start == -1:
                                full.append(chunk)
                                yield f'data: {_json.dumps({"delta": chunk})}\n\n'
                                chunk = ""
                            else:
                                if chunk[:start]:
                                    full.append(chunk[:start])
                                    yield f'data: {_json.dumps({"delta": chunk[:start]})}\n\n'
                                chunk = chunk[start + 7:]
                                think_open = True
        except Exception as e:
            yield f'data: {{"type":"proxy_error","error":"{str(e)[:200]}"}}\n\n'
        finally:
            # Persist the exchange into the Odysseus session (best-effort).
            answer = "".join(full).strip()
            if sid and user_msg:
                try:
                    await _ody_req("POST", f"/api/session/{sid}/message",
                                   json={"role": "user", "content": user_msg})
                    if answer:
                        await _ody_req("POST", f"/api/session/{sid}/message",
                                       json={"role": "assistant", "content": answer})
                except Exception:
                    pass
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


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


# ── Browse: register the stdio Browser MCP (browsermcp.io) in Odysseus so the
# chat's agent mode gains browser control. The user installs the Chrome extension
# once; the MCP shows "connected" after they connect a tab. (Hermes + the http
# jan-browser-mcp are follow-up slices — see CLAUDE.md.)
_BROWSERMCP = {"name": "browsermcp", "transport": "stdio",
               "command": "npx", "args": '["@browsermcp/mcp"]'}


async def _ody_find_mcp(name: str):
    r = await _ody_req("GET", "/api/mcp/servers")
    lst = r.json() if r.status_code == 200 else []
    if not isinstance(lst, list):
        lst = []
    return next((s for s in lst if s.get("name") == name), None)


def _hermes_set_mcp(enable: bool) -> bool:
    """Add/remove the browsermcp stdio server in ~/.hermes/config.yaml (mcp_servers).
    No CLI (its prompts + live-connect would hang) and no connection attempt — Hermes
    picks it up on new chats. Returns whether browsermcp is present afterwards."""
    import os
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    path = os.path.join(home, "config.yaml")
    if not os.path.exists(path):
        if not enable:
            return False
        os.makedirs(home, exist_ok=True)
        data = {}
    else:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    servers = data.get("mcp_servers") or {}
    if enable:
        servers["browsermcp"] = {"command": "npx", "args": ["@browsermcp/mcp"]}
    else:
        servers.pop("browsermcp", None)
    data["mcp_servers"] = servers
    # Fable QA hardening: atomic write (temp + os.replace) so a concurrent save from
    # Hermes's own dashboard can never observe a half-written config.
    tmp = path + ".harness-tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp, path)
    return "browsermcp" in servers


def _hermes_has_mcp() -> bool:
    import os
    path = os.path.join(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"), "config.yaml")
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return "browsermcp" in (data.get("mcp_servers") or {})
    except Exception:
        return False


@app.get("/api/browse/status")
async def browse_status() -> JSONResponse:
    try:
        s = await _ody_find_mcp("browsermcp")
    except Exception:
        s = None
    hermes = _hermes_has_mcp()
    return JSONResponse({"on": bool(s) or hermes, "odysseus": bool(s),
                         "hermes": hermes, "connected": (s or {}).get("status") == "connected"})


@app.post("/api/browse/toggle")
async def browse_toggle(req: Request) -> JSONResponse:
    """Register/remove the stdio Browser MCP in BOTH Odysseus (live API) and Hermes
    (config.yaml, applies to new Hermes chats). One control → both components."""
    on = bool((await req.json()).get("on"))
    log = []
    try:
        existing = await _ody_find_mcp("browsermcp")
        if on and not existing:
            r = await _ody_req("POST", "/api/mcp/servers", data=_BROWSERMCP)
            log.append(f"odysseus:{r.status_code}")
        elif not on and existing:
            r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
            log.append(f"odysseus-del:{r.status_code}")
    except Exception as e:
        log.append(f"odysseus-err:{str(e)[:120]}")
    try:
        _hermes_set_mcp(on)
        log.append("hermes:ok")
    except Exception as e:
        log.append(f"hermes-err:{str(e)[:120]}")
    return JSONResponse({"ok": True, "on": on, "log": " · ".join(log)})
