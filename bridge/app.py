"""Harness bridge — control panel + component lifecycle API.

M0/M1 scope: status, install (with plan → approve → execute), start/stop.
Gearbox (M2) and adapter/self-heal (M3) are stubs; see gearbox.py / adapter.py.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
PANEL = Path(__file__).resolve().parent / "panel"

app = FastAPI(title="AI Harness Bridge")

# Serve the panel's self-hosted assets (Phase 2 artifact renderer: babel/react/prism/
# markdown-it/dompurify) same-origin at /assets/vendor/*. Fully offline — no runtime CDN.
# The vendor dir is gitignored + fetched by scripts/fetch_vendor_assets.sh (run once on
# the Mac / at FAT build). Ensure the mount point exists so startup never errors when the
# libs haven't been fetched yet (the renderer degrades gracefully in that case).
(PANEL / "assets" / "vendor").mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=str(PANEL / "assets")), name="assets")


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
    # no-store: the panel HTML must never be cached by the WKWebView, else code
    # edits silently don't appear after a relaunch (heuristic caching served a
    # stale index.html — the cause of "changes didn't show" during iteration).
    return FileResponse(
        PANEL / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


def _runner_engine(rc: dict) -> str:
    """Human label for the engine the active model will run on (mirrors the
    start script's dispatch: gguf→llama.cpp, mlx→mlx-lm, mlx+vision→mlx-vlm)."""
    adapter = (rc.get("adapter") or "auto").strip()
    if adapter == "lmstudio":
        return "lmstudio"   # reserved-but-unimplemented fallback
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


# ── Wire identifier vs registry id (Fable, 2026-08-06 — MLX "runner 400" fix) ─
# Our REGISTRY ID is the internal key everywhere (harness.yaml runner.model, the
# RAM ledger, panel labels/selects). But the identifier that goes ON THE WIRE to
# the runner is engine-dependent:
#   • llama.cpp — start_component.sh launches with `--alias <registry id>`, so the
#     registry id IS the served model name. Unchanged.
#   • MLX (mlx_lm.server / mlx_vlm.server) — the request's `model` field is treated
#     as A MODEL TO LOAD (server.py ModelProvider.load → mlx_lm.utils.load), so an
#     unresolvable name is looked up on HuggingFace → 404 → the server answers 400
#     ("Failed to load model: … Repository Not Found"). Neither server has an
#     alias/served-model-name flag (recon: mlx-lm 0.31.3 + mlx-vlm 0.6.10 argv).
#     Therefore the wire identifier is the model's LOCAL PATH, byte-identical to the
#     `--model` argument used at launch (both read the same registry `path`), so the
#     provider's model_key matches and it does NOT reload the weights.
def wire_model_id(model_id: "str | None", models: list) -> str:
    """PURE. Registry id → the identifier to put on the wire for the runner.
    gguf/unknown format → the id unchanged; mlx → the registry path (falls back to
    the id when the entry has no path). Empty id → "". Unknown id → unchanged
    (safe fallback = previous behavior)."""
    mid = (model_id or "").strip()
    if not mid:
        return ""
    m = next((x for x in (models or []) if x.get("id") == mid), None)
    if not m:
        return mid
    if str(m.get("format") or "gguf").strip().lower() == "mlx":
        return str(m.get("path") or "").strip() or mid
    return mid


def display_model_id(wire: "str | None", models: list) -> str:
    """PURE inverse of wire_model_id, for LABELS ONLY: a wire identifier (for MLX a
    long filesystem path — which is also what Odysseus stores as a session's model)
    → our registry id when we can recognise it, else the input unchanged. Matches on
    exact id, then exact path, then trailing-slash-insensitive path, then path
    basename (covers a resolved/symlinked path reported by the runner probe)."""
    w = (wire or "").strip()
    if not w:
        return ""
    ms = [x for x in (models or []) if x.get("id")]
    if any(x.get("id") == w for x in ms):
        return w
    paths = [(x, str(x.get("path") or "").strip()) for x in ms]
    for x, p in paths:
        if p and p == w:
            return x["id"]
    wn = w.rstrip("/")
    for x, p in paths:
        if p and p.rstrip("/") == wn:
            return x["id"]
    base = os.path.basename(wn)
    if base:
        for x, p in paths:
            if p and os.path.basename(p.rstrip("/")) == base:
                return x["id"]
    return w


def runner_wire_model() -> str:
    """The wire identifier for the ACTIVE runner model (harness.yaml runner.model)."""
    return wire_model_id((cfg().get("runner", {}) or {}).get("model") or "",
                         _registry_models())


def _display_model(name):
    """Label-safe wrapper for values we hand back to the panel: keeps falsy values
    as-is (Odysseus may report null) and never raises."""
    if not name:
        return name
    try:
        return display_model_id(name, _registry_models())
    except Exception:
        return name


# ── Single source of truth for "live" (Fable ISSUE C) ────────────────────────
# harness.yaml's runner.model records INTENT, not reality — which is why MC could
# show a runner "green + model" while nothing was actually loaded. The authoritative
# signal is the runner ITSELF: ask what it is serving (GET :port/v1/models). Both
# MC (/api/status) and the Models pane (/api/models) key off this so they agree.
def _runner_loaded_id(port: int) -> "str | None":
    """Probe the runner for the model it is actually serving. Returns the loaded
    model id, or None if the runner is down / has nothing loaded. Short timeout;
    /v1/models needs no api-key on llama-server or the loopback MLX servers."""
    import json as _json
    from urllib.request import urlopen
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/v1/models", timeout=0.8) as resp:
            data = _json.loads(resp.read().decode() or "{}").get("data") or []
        return (data[0].get("id") or None) if data else None
    except Exception:
        return None


def _reconcile_live(probed: "str | None", registry_ids: set, intent_model: "str | None",
                    models: "list | None" = None) -> "str | None":
    """Pure (unit-tested) reconciliation of the runner probe against our registry.
      probed None            → nothing is loaded → nothing is live (None).
      probed in registry_ids → exact truth (llama.cpp launches with --alias <our id>).
      probed maps to a registry PATH → that model (MLX servers report a path).
      otherwise              → the runner reports something we can't map (MLX's
                               /v1/models enumerates the whole HuggingFace CACHE, so
                               data[0] is often an unrelated repo id) → fall back to
                               the model we intended to launch (harness.yaml
                               runner.model). NEVER trust an unmappable probe."""
    if not probed:
        return None
    if probed in registry_ids:
        return probed
    if models:
        mapped = display_model_id(probed, models)
        if mapped and mapped != probed:
            return mapped
    return intent_model or probed


def _live_model_id(port: int) -> "str | None":
    """Authoritative live id: probe the runner, reconcile against the registry +
    harness.yaml intent. None ⇒ nothing loaded (single source of truth for 'live')."""
    probed = _runner_loaded_id(port)
    if not probed:
        return None
    models = _registry_models()
    ids = {m.get("id") for m in models}
    intent = (cfg().get("runner", {}) or {}).get("model") or None
    return _reconcile_live(probed, ids, intent, models)


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
        # Probe the runner off the event loop (item D: no blocking on the async loop).
        # `running` (green) now means a model is ACTUALLY loaded, not merely that the
        # port answers — so MC can never show green while nothing is loaded (ISSUE C).
        port_up = await _port_alive(int(rport)) if rport else False
        live_id = (await asyncio.to_thread(_live_model_id, int(rport))) if rport else None
        loaded = bool(live_id)
        out["components"]["runner"] = {
            "installed": True,
            "pin": str(live_id or rc.get("model") or rc.get("adapter") or "auto"),
            "running": loaded,
            "loaded": loaded,
            "port_up": port_up,          # process holds the port but may still be loading
            # degraded = the process actually died (not merely mid-load): expected-up
            # AND the port is gone. A live port with no model yet = "loading", not degraded.
            "degraded": _expected_path("runner").exists() and not port_up,
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
    # "guard" = the path-guard audit trail (one JSON line per out-of-allowlist write).
    if name not in ("bridge", "hermes", "odysseus", "searxng", "runner", "guard"):
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    if not f.exists():
        return {"lines": []}
    return {"lines": f.read_text(errors="replace").splitlines()[-lines:]}


_LOG_NAMES = ("bridge", "hermes", "odysseus", "searxng", "runner", "guard")


@app.post("/api/logs/{name}/clear")
def logs_clear(name: str) -> JSONResponse:
    """Truncate a log file (Debi request 2026-08-06: clear/export on every source).
    Truncate-not-delete: a component holding the fd keeps appending to the same
    inode, so deletion would silently orphan its future output."""
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    try:
        if f.exists():
            with open(f, "w"):
                pass
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


@app.post("/api/logs/{name}/export")
def logs_export(name: str) -> JSONResponse:
    """Copy a log to ~/Downloads/harness-logs/<name>-<UTC ts>.log and return the
    path (the panel then offers Show-in-Folder via the existing /api/open gate)."""
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    src = ROOT / "data" / "logs" / f"{name}.log"
    try:
        import shutil, datetime as _dt
        outdir = Path.home() / "Downloads" / "harness-logs"
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        dest = outdir / f"{name}-{stamp}.log"
        if src.exists():
            shutil.copyfile(src, dest)
        else:
            dest.write_text("")
        return JSONResponse({"ok": True, "path": str(dest)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)


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


_NOTES = {"runner": "launches the llama.cpp/MLX runner + loads the model (~60–90s)"}


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


def _kill_port_listener(port: int, force: bool = False) -> None:
    subprocess.run(_port_kill_cmd(port, force), shell=True, check=False)


def _port_listener_pids(port: int) -> list:
    """PIDs currently LISTENING on tcp:port (empty list when the port is free)."""
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{int(port)}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, check=False).stdout
        return [p for p in out.split() if p.strip()]
    except Exception:
        return []


@app.post("/api/components/{name}/stop")
def stop(name: str) -> JSONResponse:
    _clear_expected(name)   # intentional stop → not "degraded", just "stopped"
    PROV.pop(name, None)    # drop any stale provisioning overlay for this component
    # Runner must be stopped by PORT — a child router can survive a PID kill (spike learning).
    if name == "runner":
        rc = cfg().get("runner", {})
        port = rc.get("port")
        # legacy jan-supervisor sweep (harmless once Jan is uninstalled — no-op if none match)
        subprocess.run(f'pkill -f "jan serve.*port[= ]{int(port)}"', shell=True, check=False)
        _kill_port_listener(int(port), force=True)
        (ROOT / "data" / "runner.pid").unlink(missing_ok=True)
        return JSONResponse({"ok": True})
    notes = []
    pidf = ROOT / "data" / f"{name}.pid"
    if pidf.exists():
        pid = None
        try:
            pid = int(pidf.read_text().strip())
        except ValueError:
            notes.append("unreadable pid file")
        pidf.unlink(missing_ok=True)
        if pid is not None:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False           # stale: that process is gone (or pid reused+gone)
            except PermissionError:
                alive = True            # exists but not ours — still attempt the kill
            if alive:
                subprocess.run(["kill", str(pid)], check=False)
                notes.append(f"killed pid {pid}")
            else:
                notes.append(f"stale pid file (pid {pid} not running)")
    # ALWAYS verify the port afterwards — a stale/absent pid file must never mask a
    # live process (observed: hermes.pid held 36254 while the real hermes was 41584 →
    # Stop was a silent no-op). If a LISTENER still holds the port, kill it by port.
    comp = cfg().get("components", {}).get(name, {})
    port = comp.get("port") or comp.get("mcp_port")
    if port:
        for _ in range(6):              # up to ~1.5s for a just-SIGTERMed listener to release
            if not _port_listener_pids(int(port)):
                break
            time.sleep(0.25)
        if _port_listener_pids(int(port)):
            _kill_port_listener(int(port))
            notes.append(f"port :{port} still held — killed listener")
    if notes:
        return JSONResponse({"ok": True, "log": "; ".join(notes)})
    if port:
        return JSONResponse({"ok": True, "log": f"nothing running on :{port}"})
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
                    # `model` is Odysseus's stored session model = the WIRE id, which
                    # for MLX is a filesystem path — map it back to our registry id
                    # so the chat header/composer show a model NAME, not a path.
                    return JSONResponse({"id": s["id"], "model": _display_model(s.get("model")),
                                         "reused": True})
        r = await _ody_req("POST", "/api/session",
                           data={"name": name, "endpoint_id": "local-jan"})
        if r.status_code == 200:
            j = r.json()
            return JSONResponse({"id": j["id"], "model": _display_model(j.get("model")),
                                 "reused": False})
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
            "model": _display_model(s.get("model")),   # wire id (MLX = path) → our id
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
            return JSONResponse({"id": j["id"], "name": name,
                                 "model": _display_model(j.get("model"))})
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
    """Duplicate a session by copying its messages into a fresh session, then name it
    '<src> (copy)'. New Odysseus main removed POST /api/session/{sid}/fork, so we replicate
    it: read history → create session → inject_messages → rename."""
    try:
        name = (await req.json()).get("name", "").strip()
    except Exception:
        name = ""
    try:
        # (a) fetch the source session's messages
        hr = await _ody_req("GET", f"/api/history/{sid}")
        if hr.status_code != 200:
            return JSONResponse({"error": hr.text[:500]}, status_code=502)
        hist = hr.json().get("history", []) or []
        msgs = [{"role": m.get("role"), "content": m.get("content", "")}
                for m in hist if m.get("role")]
        # (b) create the new session (same params as the "new session" path)
        cr = await _ody_req("POST", "/api/session",
                            data={"name": name or "New chat", "endpoint_id": "local-jan"})
        if cr.status_code != 200:
            return JSONResponse({"error": cr.text[:500]}, status_code=502)
        new_id = cr.json().get("id")
        # (c) copy the messages across
        if new_id and msgs:
            await _ody_req("POST", f"/api/session/{new_id}/inject_messages",
                           json={"messages": msgs})
        # (d) final rename to '<src> (copy)' (panel passes the copy name)
        if new_id and name:
            await _ody_req("PATCH", f"/api/session/{new_id}", data={"name": name})
        return JSONResponse({"id": new_id, "name": name})
    except Exception as e:
        return JSONResponse({"error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/session/{sid}/delete")
async def ody_session_delete(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/delete")
        _thinking_forget(sid)   # drop the direct-lane thinking sidecar rows too
        return JSONResponse({"ok": r.status_code == 200})
    except Exception:
        return JSONResponse({"ok": False})


@app.get("/api/ody/history/{sid}")
async def ody_history(sid: str) -> JSONResponse:
    try:
        r = await _ody_req("GET", f"/api/history/{sid}")
        out = r.json() if r.status_code == 200 else {"history": []}
        try:
            # Direct-lane thinking sidecar: Odysseus stores {role,content} only, so
            # re-attach any locally stored reasoning for this session's assistant
            # turns (matched by answer hash, consumed in order). Best-effort — a
            # sidecar miss just means no thinking disclosure, never a broken history.
            if isinstance(out, dict) and isinstance(out.get("history"), list):
                attach_thinking(out["history"], _thinking_rows(sid))
        except Exception:
            pass
        return JSONResponse(out)
    except Exception:
        return JSONResponse({"history": []})


# ── Capabilities panel (Phase 1): aggregate Odysseus settings + route writes ──────
# One snapshot for the panel to render; one router for writes. Mirrors the _ody_req
# proxy style. Odysseus is the source of truth (shared with the Odysseus tab).

# The Phase-1 subset of app-settings the panel is allowed to see/edit. Kept explicit
# so we never leak the whole settings bag (which can hold *_api_key secrets).
CAPS_SETTING_KEYS = (
    "search_provider", "search_fallback_chain", "search_safesearch",
    "search_result_count", "agent_max_rounds", "agent_max_tool_calls",
    # Phase 3 — model pickers (Background-tasks + Utility). Empty string = "same
    # as chat" (Odysseus DEFAULT_SETTINGS defaults all four to "").
    "task_endpoint_id", "task_model", "utility_endpoint_id", "utility_model",
)


def caps_map_write(group: str, key: str, value):
    """PURE mapping: (group, key, value) → (method, path, body, encoding) for a caps
    write, or ("__error__", message, None, None) to reject. `encoding` is "json" or
    "form" (Odysseus's MCP toggle is form-encoded, everything else is JSON). Routes:
      feature       → POST /api/auth/features         (bool)          [Phase 1]
      setting       → POST /api/auth/settings         (allowlist)     [Phase 1]
      mcp_server    → PATCH /api/mcp/servers/{id}      form is_enabled [Phase 2]
      mcp_tools     → PATCH /api/mcp/servers/{id}/tools {disabled:[]} [Phase 2]
      builtin_tools → POST  /api/tools                 {disabled:[]}   [Phase 2]
    Secrets (`*_api_key`) are never forwarded; `setting` writes are confined to the
    Phase-1 allowlist so the panel can't reach arbitrary settings keys."""
    if not isinstance(key, str) or not key:
        return ("__error__", "missing key", None, None)
    if key.endswith("_api_key") or "api_key" in key:
        return ("__error__", "refusing to write a secret key", None, None)
    if group == "feature":
        return ("POST", "/api/auth/features", {key: bool(value)}, "json")
    if group == "setting":
        if key not in CAPS_SETTING_KEYS:
            return ("__error__", f"setting '{key}' not writable in Phase 1", None, None)
        return ("POST", "/api/auth/settings", {key: value}, "json")
    if group == "mcp_server":
        # key = server id; value = desired enabled state. Odysseus expects a form
        # field is_enabled="true"/"false" (see mcp_routes.toggle_server).
        return ("PATCH", f"/api/mcp/servers/{key}",
                {"is_enabled": "true" if value else "false"}, "form")
    if group == "mcp_tools":
        # key = server id; value = the FULL list of disabled tool names (replace).
        if not isinstance(value, list):
            return ("__error__", "mcp_tools value must be a list of tool names", None, None)
        return ("PATCH", f"/api/mcp/servers/{key}/tools", {"disabled": value}, "json")
    if group == "builtin_tools":
        # key is a placeholder (write is global); value = FULL list of disabled
        # built-in tool ids (replace). Writes settings["disabled_tools"].
        if not isinstance(value, list):
            return ("__error__", "builtin_tools value must be a list of tool ids", None, None)
        return ("POST", "/api/tools", {"disabled": value}, "json")
    if group == "skill_builtin":
        # key = built-in skill (TOOL_SECTIONS) name. IMPORTANT: Odysseus's
        # /api/skills/builtin is a TEXT-OVERRIDE store (PUT {text}) + a reset
        # (DELETE) — it is NOT an on/off switch. The real enable/disable of a
        # built-in tool lives in group 'builtin_tools' (→ POST /api/tools). So the
        # only boolean-safe write here is RESET (DELETE the override → shipped
        # default); enabling an override would need override TEXT the panel never
        # collects. Accept only a falsy value = "reset this override".
        # ⚠️ PENDING FABLE QA: built-in skills have no true on/off by design here.
        if value:
            return ("__error__",
                    "built-in skills have no on/off — send value:false to reset the "
                    "override; enable/disable is the Tools section", None, None)
        return ("DELETE", f"/api/skills/builtin/{key}", None, "none")
    return ("__error__", f"group '{group}' not supported", None, None)


@app.get("/api/ody/caps")
async def ody_caps() -> JSONResponse:
    """Aggregate the Phase-1 capabilities snapshot. Each sub-fetch is isolated so a
    partial failure still returns the rest. Phase 2/3 keys (mcp_servers,
    model_endpoints) are omitted for now."""
    out = {"features": {}, "settings": {}, "search_providers": [],
           "mcp_servers": [], "builtin_tools": [],
           "skills_builtin": [], "skills_user": [],
           "model_endpoints": [], "models": [], "errors": {}}
    try:
        r = await _ody_req("GET", "/api/auth/features")
        if r.status_code == 200 and isinstance(r.json(), dict):
            out["features"] = r.json()
        else:
            out["errors"]["features"] = r.text[:200]
    except Exception as e:
        out["errors"]["features"] = str(e)
    try:
        r = await _ody_req("GET", "/api/auth/settings")
        if r.status_code == 200 and isinstance(r.json(), dict):
            full = r.json()
            # only surface the Phase-1 subset — never leak the whole bag / secrets
            out["settings"] = {k: full.get(k) for k in CAPS_SETTING_KEYS if k in full}
        else:
            out["errors"]["settings"] = r.text[:200]
    except Exception as e:
        out["errors"]["settings"] = str(e)
    try:
        r = await _ody_req("GET", "/api/search/providers")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["search_providers"] = r.json()
        else:
            out["errors"]["search_providers"] = r.text[:200]
    except Exception as e:
        out["errors"]["search_providers"] = str(e)
    # Phase 2 — connected tools (MCP servers) + built-in agent tools.
    try:
        r = await _ody_req("GET", "/api/mcp/servers")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["mcp_servers"] = r.json()
        else:
            out["errors"]["mcp_servers"] = r.text[:200]
    except Exception as e:
        out["errors"]["mcp_servers"] = str(e)
    try:
        r = await _ody_req("GET", "/api/tools")
        doc = r.json() if r.status_code == 200 else None
        # Odysseus returns {"tools": [{"id","enabled"}]} (flat — no server-side
        # categories; the panel groups them for display).
        if isinstance(doc, dict) and isinstance(doc.get("tools"), list):
            out["builtin_tools"] = doc["tools"]
        else:
            out["errors"]["builtin_tools"] = r.text[:200]
    except Exception as e:
        out["errors"]["builtin_tools"] = str(e)
    # Skills — built-in tool-instruction blocks (name/description/is_overridden;
    # text-override + reset only) and the user's learned SKILL.md skills (read-only
    # here — full CRUD lives in the Odysseus tab).
    try:
        r = await _ody_req("GET", "/api/skills/builtin")
        doc = r.json() if r.status_code == 200 else None
        if isinstance(doc, dict) and isinstance(doc.get("builtin"), list):
            out["skills_builtin"] = doc["builtin"]
        else:
            out["errors"]["skills_builtin"] = r.text[:200]
    except Exception as e:
        out["errors"]["skills_builtin"] = str(e)
    try:
        r = await _ody_req("GET", "/api/skills")
        doc = r.json() if r.status_code == 200 else None
        # Odysseus returns {"skills": [...], "count": N}; be tolerant of a bare list.
        if isinstance(doc, dict) and isinstance(doc.get("skills"), list):
            out["skills_user"] = doc["skills"]
        elif isinstance(doc, list):
            out["skills_user"] = doc
        else:
            out["errors"]["skills_user"] = (r.text[:200] if r is not None else "no response")
    except Exception as e:
        out["errors"]["skills_user"] = str(e)
    # Phase 3 — model endpoints + models (for the Background-tasks / Utility pickers).
    # /api/model-endpoints (admin-only, reachable via our admin cookie) returns a
    # list of {id, name, models:[...], is_enabled, ...} — this is the primary
    # source for the pickers (endpoint id/name + its model ids). We also carry the
    # /api/models {items:[{endpoint_id, models, models_extra, ...}]} view for
    # completeness / cross-check. ⚠️ PENDING FABLE QA: shapes read from
    # vendor/odysseus/routes/model_routes.py @25c9e73.
    try:
        r = await _ody_req("GET", "/api/model-endpoints")
        if r.status_code == 200 and isinstance(r.json(), list):
            out["model_endpoints"] = r.json()
        else:
            out["errors"]["model_endpoints"] = r.text[:200]
    except Exception as e:
        out["errors"]["model_endpoints"] = str(e)
    try:
        r = await _ody_req("GET", "/api/models")
        doc = r.json() if r.status_code == 200 else None
        # /api/models returns {"hosts":[], "items":[...]}; be tolerant of a bare list.
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            out["models"] = doc["items"]
        elif isinstance(doc, list):
            out["models"] = doc
        else:
            out["errors"]["models"] = (r.text[:200] if r is not None else "no response")
    except Exception as e:
        out["errors"]["models"] = str(e)
    return JSONResponse(out)


@app.get("/api/ody/mcp/{server_id}/tools")
async def ody_mcp_tools(server_id: str) -> JSONResponse:
    """Per-server MCP tool list with is_disabled state (fetched on-demand when a
    server row is expanded — kept out of the /caps snapshot so opening Capabilities
    doesn't fan out to every server's tools). ⚠️ PENDING FABLE QA."""
    try:
        r = await _ody_req("GET", f"/api/mcp/servers/{server_id}/tools")
        if r.status_code == 200 and isinstance(r.json(), list):
            return JSONResponse({"ok": True, "tools": r.json()})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/mcp/add")
async def ody_mcp_add(req: Request) -> JSONResponse:
    """Register a new MCP server in Odysseus. Forwards to Odysseus's admin-only
    form endpoint (POST /api/mcp/servers). The panel sends JSON; we translate to the
    form fields Odysseus expects (name, transport, command, args JSON, env JSON, url).
    Adding a stdio server runs an arbitrary binary on the host — same trust surface as
    the Odysseus tab's own MCP page. ⚠️ PENDING FABLE QA: form field names mirror
    mcp_routes.add_server (@25c9e73)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body.get("name") or "").strip()
    transport = (body.get("transport") or "stdio").strip()
    command = (body.get("command") or "").strip()
    url = (body.get("url") or "").strip()
    # args/env may arrive as a JSON string OR as a list/dict — normalise to a JSON string.
    def _as_json_str(v, default):
        if v is None or v == "":
            return default
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v)
        except Exception:
            return default
    args = _as_json_str(body.get("args"), "[]")
    env = _as_json_str(body.get("env"), "{}")
    if not name:
        return JSONResponse({"ok": False, "error": "name is required"}, status_code=400)
    if transport == "stdio" and not command:
        return JSONResponse({"ok": False, "error": "command is required for stdio transport"}, status_code=400)
    if transport in ("sse", "http") and not url:
        return JSONResponse({"ok": False, "error": f"url is required for {transport} transport"}, status_code=400)
    form = {"name": name, "transport": transport, "args": args, "env": env}
    if command:
        form["command"] = command
    if url:
        form["url"] = url
    try:
        r = await _ody_req("POST", "/api/mcp/servers", data=form)
        if r.status_code == 200:
            return JSONResponse({"ok": True, "server": r.json()})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/mcp/{server_id}/remove")
async def ody_mcp_remove(server_id: str) -> JSONResponse:
    """Delete an MCP server from Odysseus (DELETE /api/mcp/servers/{id})."""
    try:
        r = await _ody_req("DELETE", f"/api/mcp/servers/{server_id}")
        if r.status_code == 200:
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


@app.post("/api/ody/caps/set")
async def ody_caps_set(req: Request) -> JSONResponse:
    """Route a single capability write to the right Odysseus endpoint. Odysseus
    validates/clamps server-side (e.g. agent_max_rounds 1-200)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    group = body.get("group")
    key = body.get("key")
    value = body.get("value")
    method, path, jbody, enc = caps_map_write(group, key, value)
    if method == "__error__":
        return JSONResponse({"ok": False, "error": path}, status_code=400)
    try:
        if enc == "form":
            r = await _ody_req(method, path, data=jbody)
        elif enc == "none":            # DELETE with no body (e.g. reset a skill override)
            r = await _ody_req(method, path)
        else:
            r = await _ody_req(method, path, json=jbody)
        if r.status_code == 200:
            # echo the value Odysseus actually stored (it may clamp/coerce)
            stored = value
            try:
                doc = r.json()
                if isinstance(doc, dict) and key in doc:
                    stored = doc[key]
            except Exception:
                pass
            return JSONResponse({"ok": True, "group": group, "key": key, "value": stored})
        return JSONResponse({"ok": False, "error": r.text[:300]}, status_code=502)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"}, status_code=502)


# ── usage analytics (doc-09): best-effort per-turn log → SQLite. NEVER raises into chat. ──
_analytics_lock = threading.Lock()
_analytics_pruned = False   # retention prune runs once per process (Fable QA: cap growth)

def _analytics_conn():
    import sqlite3
    global _analytics_pruned
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "analytics.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS turns("
              "ts REAL, day TEXT, lane TEXT, model TEXT, "
              "in_tok INTEGER, out_tok INTEGER, cached_tok INTEGER, tps REAL, ttft REAL)")
    if not _analytics_pruned:   # callers already hold _analytics_lock
        _analytics_pruned = True
        try:   # best-effort: keep the newest 5000 turns (tiny rows; unbounded otherwise)
            c.execute("DELETE FROM turns WHERE rowid NOT IN "
                      "(SELECT rowid FROM turns ORDER BY ts DESC LIMIT 5000)")
            c.commit()
        except Exception:
            pass
    return c

def log_turn(lane, model, in_tok, out_tok, cached_tok, tps, ttft):
    try:
        import time as _t
        with _analytics_lock:
            c = _analytics_conn()
            c.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?)",
                      (_t.time(), _t.strftime("%Y-%m-%d"), lane, model or "",
                       int(in_tok or 0), int(out_tok or 0), int(cached_tok or 0),
                       float(tps or 0), float(ttft or 0)))
            c.commit(); c.close()
    except Exception:
        pass  # analytics must never break the chat path

def _log_ody_metrics(tail, lane):
    # Extract the last `{"type":"metrics","data":{...}}` SSE frame from the stream tail.
    try:
        import json as _json
        for line in reversed(tail.split("\n")):
            s = line.strip()
            if s.startswith("data:"):
                s = s[5:].strip()
            if s.startswith("{") and '"metrics"' in s:
                obj = _json.loads(s)
                if obj.get("type") == "metrics":
                    d = obj.get("data") or {}
                    log_turn(lane, d.get("model"), d.get("input_tokens"),
                             d.get("output_tokens"), d.get("cached_tokens") or 0,
                             d.get("tokens_per_second"), d.get("time_to_first_token"))
                    return
    except Exception:
        pass

@app.get("/api/analytics")
def api_analytics() -> JSONResponse:
    import time as _t
    day = _t.strftime("%Y-%m-%d")
    out = {"tokens_today": 0, "turns_today": 0, "avg_tps": 0, "cache_hit_pct": None}
    try:
        with _analytics_lock:
            c = _analytics_conn()
            row = c.execute("SELECT COALESCE(SUM(out_tok),0), COUNT(*) FROM turns WHERE day=?", (day,)).fetchone()
            out["tokens_today"], out["turns_today"] = int(row[0] or 0), int(row[1] or 0)
            r2 = c.execute("SELECT AVG(tps) FROM (SELECT tps FROM turns WHERE tps>0 ORDER BY ts DESC LIMIT 20)").fetchone()
            out["avg_tps"] = round(r2[0], 1) if r2 and r2[0] else 0
            r3 = c.execute("SELECT COALESCE(SUM(cached_tok),0), COALESCE(SUM(in_tok),0) FROM turns WHERE cached_tok>0").fetchone()
            if r3 and (r3[1] or 0) > 0:
                out["cache_hit_pct"] = round(r3[0] / r3[1] * 100)
            c.close()
    except Exception as e:
        out["error"] = str(e)[:120]
    return JSONResponse(out)


# ── Direct-lane thinking sidecar (Fable, 2026-08-06) ─────────────────────────
# The direct chat lane persists only {role, content} to Odysseus (inject_messages),
# so a reopened session loses the turn's thinking. The Hermes lane rehydrates from
# Hermes's own store and the Odysseus agent lane keeps its own — this local sidecar
# gives the DIRECT lane parity.
#
# Keyed by (session id, hash of the assistant answer) rather than a message id:
# inject_messages returns no ids, and the answer text is what the panel renders
# back, so the hash is the only join we own. Same discipline as analytics above:
# one lock, every read/write wrapped — this must NEVER raise into the chat path.
_thinking_lock = threading.Lock()
_thinking_pruned = False   # global retention prune runs once per process


def answer_hash(text: str) -> str:
    """Stable join key: sha1 of the answer's first 2048 characters (utf-8).

    Truncated so a long answer that Odysseus stores/returns with trailing
    differences still matches, and so hashing stays cheap. Pure — unit-tested.
    """
    import hashlib
    return hashlib.sha1((text or "")[:2048].encode("utf-8", "replace")).hexdigest()


def _thinking_conn():
    import sqlite3
    global _thinking_pruned
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "thinking.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS thoughts("
              "sid TEXT, chash TEXT, reasoning TEXT, ts REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_thoughts_sid_chash ON thoughts(sid, chash)")
    if not _thinking_pruned:   # callers already hold _thinking_lock
        _thinking_pruned = True
        try:   # best-effort global cap (mirrors the analytics prune-once pattern)
            c.execute("DELETE FROM thoughts WHERE rowid NOT IN "
                      "(SELECT rowid FROM thoughts ORDER BY ts DESC LIMIT 5000)")
            c.commit()
        except Exception:
            pass
    return c


def log_thinking(sid: str, answer: str, reasoning: str) -> None:
    """Store one direct-lane turn's thinking. Best-effort; never raises."""
    try:
        if not (sid and answer and reasoning):
            return
        import time as _t
        with _thinking_lock:
            c = _thinking_conn()
            c.execute("INSERT INTO thoughts VALUES(?,?,?,?)",
                      (sid, answer_hash(answer), reasoning, _t.time()))
            # Per-session cap: keep the newest 200 rows for this sid.
            c.execute("DELETE FROM thoughts WHERE sid=? AND rowid NOT IN "
                      "(SELECT rowid FROM thoughts WHERE sid=? ORDER BY ts DESC LIMIT 200)",
                      (sid, sid))
            c.commit(); c.close()
    except Exception:
        pass


def _thinking_rows(sid: str) -> list:
    """All (chash, reasoning) rows for a session, oldest first. Never raises."""
    try:
        if not sid:
            return []
        with _thinking_lock:
            c = _thinking_conn()
            rows = c.execute("SELECT chash, reasoning FROM thoughts WHERE sid=? "
                             "ORDER BY ts ASC, rowid ASC", (sid,)).fetchall()
            c.close()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []


def _thinking_forget(sid: str) -> None:
    """Drop a deleted session's sidecar rows. Best-effort; never raises."""
    try:
        if not sid:
            return
        with _thinking_lock:
            c = _thinking_conn()
            c.execute("DELETE FROM thoughts WHERE sid=?", (sid,))
            c.commit(); c.close()
    except Exception:
        pass


def attach_thinking(history_rows, thought_rows):
    """PURE: attach stored reasoning to assistant messages, consuming IN ORDER.

    Each stored row is used at most once per response: rows are bucketed by hash
    and popped from the front, so a session that answered the same text twice
    gets its two distinct thinkings back in the order they were produced.
    Malformed rows/messages are skipped — this must never raise.
    """
    try:
        buckets: dict = {}
        for row in (thought_rows or []):
            try:
                h, rsn = row[0], row[1]
            except Exception:
                continue
            if not (h and rsn):
                continue
            buckets.setdefault(str(h), []).append(rsn)
        if not buckets:
            return history_rows
        for m in (history_rows or []):
            try:
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                if m.get("reasoning"):
                    continue          # never overwrite a lane that already has it
                content = m.get("content")
                if not isinstance(content, str) or not content:
                    continue
                b = buckets.get(answer_hash(content))
                if b:
                    m["reasoning"] = b.pop(0)
            except Exception:
                continue
    except Exception:
        pass
    return history_rows


# --- Version / update notice (PART 4) -------------------------------------------
# NOTICE ONLY: shows the local harness version + component pins, and best-effort
# checks GitHub for a newer new-harness release. NO auto-download / auto-apply /
# git ops — updates happen via the CLAUDE.md pin+bump discipline only.
#
# HONESTY NOTE: github.com/Debkbas/new-harness is a PRIVATE repo, so the
# unauthenticated GitHub API call below will almost always 404. We deliberately do
# NOT bundle or require any token. In practice `update.available` will be false /
# "unavailable" — that's expected. The tile's real job is to SHOW the version.
# It only surfaces an "Update available" line if the repo is ever made public and
# a release tag newer than the local version exists.

def _assemble_update(local_version, gh_result):
    """Pure helper (unit-testable, no network): build the `update` dict.

    gh_result is either a dict parsed from the GitHub releases/latest response,
    or None (404 / timeout / error / no network)."""
    if not gh_result or not gh_result.get("tag_name"):
        return {"available": False, "latest": None, "note": "unavailable"}
    latest = str(gh_result.get("tag_name") or "")
    url = gh_result.get("html_url") or ""
    local_norm = str(local_version or "").lstrip("vV")
    latest_norm = latest.lstrip("vV")
    # Simple, conservative comparison: "available" only when the tags differ AND
    # the latest sorts after the local one (tuple-compare numeric dotted parts;
    # fall back to a plain string inequality if either isn't cleanly numeric).
    def _parts(s):
        try:
            return tuple(int(x) for x in s.split(".") if x != "")
        except Exception:
            return None
    lp, rp = _parts(local_norm), _parts(latest_norm)
    if lp is not None and rp is not None:
        available = rp > lp
    else:
        available = latest_norm != local_norm
    return {"available": available, "latest": latest, "url": url}


def _fetch_latest_release():
    """Best-effort, blocking (run via asyncio.to_thread). Returns the parsed JSON
    dict on success, or None on any 404 / timeout / error / no network."""
    try:
        from urllib.request import Request, urlopen
        import json as _json
        req = Request(
            "https://api.github.com/repos/Debkbas/new-harness/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "harness-bridge"},
        )
        with urlopen(req, timeout=3) as resp:   # NO auth by design (private repo → 404)
            return _json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None


@app.get("/api/version")
async def api_version() -> JSONResponse:
    """Local versions instantly + a best-effort update check. Never raises."""
    out = {"harness": None, "hermes": None, "odysseus": None,
           "searxng": None, "update": {"available": False, "latest": None, "note": "unavailable"}}
    local_version = None
    try:
        c = cfg()
        local_version = c.get("version")
        comps = c.get("components", {}) or {}
        out["harness"] = local_version
        out["hermes"] = (comps.get("hermes") or {}).get("pin")
        out["odysseus"] = (comps.get("odysseus") or {}).get("pin")
        out["searxng"] = (comps.get("searxng") or {}).get("pin")
    except Exception:
        pass  # still return whatever we have; the version check must never crash
    try:
        gh = await asyncio.to_thread(_fetch_latest_release)   # off the event loop, 3s cap
        out["update"] = _assemble_update(local_version, gh)
    except Exception:
        pass  # keep the default "unavailable" update dict
    return JSONResponse(out)


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
        tail = ""   # rolling tail of the stream, for best-effort metrics logging
        try:
            async with _ody.stream("POST", "/api/chat_stream", data=fields,
                                   headers={"X-Tz-Offset": str(body.get("tz_offset", 0))}) as r:
                if r.status_code in (401, 403):
                    await _ody_login()
                    yield 'data: {"type":"retry"}\n\n'
                    async with _ody.stream("POST", "/api/chat_stream", data=fields) as r2:
                        async for chunk in r2.aiter_raw():
                            yield chunk
                            tail = (tail + chunk.decode("utf-8", "ignore"))[-16000:]
                    return
                async for chunk in r.aiter_raw():
                    yield chunk
                    tail = (tail + chunk.decode("utf-8", "ignore"))[-16000:]
        except Exception as e:
            yield f'data: {{"type":"proxy_error","error":"{str(e)[:200]}"}}\n\n'
            yield "data: [DONE]\n\n"
        finally:
            _log_ody_metrics(tail, fields.get("mode", "agent"))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Models pane (M2) — list installed from OUR registry, switch the runner ──
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


# ── Model-memory ledger (Fable verdict, promoted) ─────────────────────────────
# Bridge-side RAM accounting so main + aux (+ future voice) loads can't blow past
# the box's memory. APPROXIMATION: a model's RAM footprint ≈ its weight file size
# (real usage adds KV-cache/overhead; the budget headroom below covers that).
def _registry_models() -> list:
    import json as _json
    try:
        return _json.loads((ROOT / "data" / "models.json").read_text()).get("models", [])
    except Exception:
        return []


def _model_size(models: list, mid: str) -> int:
    m = next((x for x in models if x.get("id") == mid), None)
    return int((m or {}).get("size_bytes") or 0)


def _budget_bytes() -> int:
    mem = cfg().get("memory", {}) or {}
    try:
        gb = float(mem.get("budget_gb"))
    except (TypeError, ValueError):
        gb = 48.0
    return int(gb * (1024 ** 3))


def _loaded_models_bytes(exclude_slot: str | None = None) -> int:
    """Approx RAM (by file size) used by models currently SERVED: main runner's
    active model (if its port is up) + aux model (if its port is up). exclude_slot
    ('main'|'aux') omits that slot — used to get 'other-slot usage' for a switch of
    that slot (so its own current usage isn't double-counted against the candidate)."""
    c = cfg()
    models = _registry_models()
    total = 0
    rc = c.get("runner", {}) or {}
    if exclude_slot != "main" and rc.get("port") and _port_alive_sync(int(rc["port"])):
        total += _model_size(models, rc.get("model") or "")
    ax = c.get("aux", {}) or {}
    if exclude_slot != "aux" and ax.get("port") and _port_alive_sync(int(ax["port"])):
        total += _model_size(models, ax.get("model") or "")
    return total


def _within_budget(candidate_bytes: int, other_slot_bytes: int, budget_bytes: int) -> bool:
    """Pure predicate (unit-testable): does loading `candidate` alongside the other
    slot's current usage stay within budget? True = OK to load."""
    return (candidate_bytes + other_slot_bytes) <= budget_bytes


@app.get("/api/models")
def api_models() -> JSONResponse:
    """Installed models (from OUR registry data/models.json — the only source since
    jan was retired), the active runner model + state, aux state, and the
    model-RAM ledger (approx by file size)."""
    import json as _json
    installed, err = [], None
    c = cfg()
    rc = c.get("runner", {})
    adapter = (rc.get("adapter") or "auto")

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
                "format": m.get("format", "gguf"),
                "ctx": m.get("ctx"), "source": m.get("source"), "path": m.get("path")})
    except Exception as e:
        err = str(e)[:200]
    port = rc.get("port")
    # Authoritative "live" = what the runner is ACTUALLY serving (ISSUE C), not just
    # "runner.model is set + port answers". runner_up is now gated on a real load, so
    # the Models pane and MC agree; live_id names the loaded model for the "live" pill.
    live_id = _live_model_id(int(port)) if port else None
    ax = c.get("aux", {}) or {}
    aux = {"model": ax.get("model") or "", "port": ax.get("port"),
           "up": _port_alive_sync(int(ax["port"])) if ax.get("port") else False}
    ledger = {"used_bytes": _loaded_models_bytes(), "budget_bytes": _budget_bytes()}
    return JSONResponse({
        "installed": installed, "active": rc.get("model"),
        "runner_up": bool(live_id), "live_id": live_id,
        "aux": aux, "adapter": adapter, "ledger": ledger, "error": err})


@app.post("/api/models/rescan")
def api_models_rescan() -> JSONResponse:
    """Re-run the registry seed the same way api_models / start_component.sh do it
    (subprocess to scripts/seed_registry.py). seed_registry.merge() prunes the
    re-scanned sets ('local'/'jan-import'/'lmstudio-import') by replacing them with a
    fresh scan, so models the user deleted in LM Studio (or Jan) drop out; source
    "download" entries + known ctx are preserved. Does NOT touch the runner/live
    model. Returns {ok, count} (models after rescan); never raises into the caller."""
    import json as _json
    try:
        r = subprocess.run(["python3", "scripts/seed_registry.py"],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=120, check=False)
        if r.returncode != 0:
            return JSONResponse(
                {"ok": False, "error": (r.stderr or r.stdout or "seed failed")[:300]},
                status_code=500)
        reg = ROOT / "data" / "models.json"
        count = len(_json.loads(reg.read_text()).get("models", []))
        return JSONResponse({"ok": True, "count": count})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)


_SWITCH = {"busy": False, "log": ""}


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
    """Switch the runner's model (loads it via the engine dispatch), then re-fan-out
    the new model NAME to any running Hermes/Odysseus (their configs bind the name).
    Runs in the background — poll /api/models/switch-status. `id` must be an INSTALLED
    registry model (HF repo ids are rejected — downloads go via the download manager)."""
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
    # Model-RAM ledger gate: candidate + the OTHER slot (aux) must fit the budget.
    # Switching the MAIN slot replaces its own usage → exclude "main" from "other".
    _models = _registry_models()
    _cand = _model_size(_models, new_id)
    _other = _loaded_models_bytes(exclude_slot="main")
    _budget = _budget_bytes()
    if _cand and not _within_budget(_cand, _other, _budget):
        _g = lambda b: round(b / (1024 ** 3), 1)
        msg = (f"would exceed model-RAM budget: {_g(_cand)} + {_g(_other)} > "
               f"{_g(_budget)} GB — eject something first")
        return JSONResponse({"ok": False, "log": msg}, status_code=409)
    hermes_up, ody_up = _running_sync("hermes", c), _running_sync("odysseus", c)
    # set BEFORE the thread: no double-switch race. (Download progress lives in the
    # download manager now — "/" repo ids are rejected above, so no HF fetch here.)
    _SWITCH.update(busy=True, log="starting…")
    _set_runner_model(new_id)
    threading.Thread(target=_do_switch, args=(new_id, old_id, hermes_up, ody_up), daemon=True).start()
    return JSONResponse({"ok": True, "log": "switch started"})


def _eject_runner() -> None:
    """Stop the main runner by PORT AND clear the active-model designation
    (runner.model → empty) so a later Start does NOT silently resurrect the model.
    Shared by the eject endpoint and the delete endpoint (deleting a live model)."""
    rc = cfg().get("runner", {}) or {}
    port = rc.get("port")
    if port:
        # legacy jan-supervisor sweep (harmless no-op post-Jan) + kill whatever holds the port
        subprocess.run(f'pkill -f "jan serve.*port[= ]{int(port)}"', shell=True, check=False)
        _kill_port_listener(int(port), force=True)
    (ROOT / "data" / "runner.pid").unlink(missing_ok=True)
    _clear_expected("runner")     # intentional → "stopped", not "degraded"
    PROV.pop("runner", None)
    _set_runner_model("")         # no active model — Start must route the user to pick


@app.post("/api/models/eject")
def api_eject_model() -> JSONResponse:
    """Eject the live model (Fable ISSUE 2 state machine): stop the runner by PORT
    AND clear the active-model designation. Going live again requires an explicit
    Load from the Models pane. Frees the main slot's RAM in the ledger."""
    _eject_runner()
    return JSONResponse({"ok": True})


# ── Delete an APP-OWNED model (files live under data/models/) ──────────────────
# App-owned = source in {download, local}: the harness downloaded these or holds the
# local files under data/models/<folder>/, so we may delete both the files and the
# registry entry. Read-only imports (lmstudio-import, jan-import) point at files the
# harness does NOT own (e.g. the user's LM Studio library) — deleting those would
# nuke the user's data, so they are HARD-refused here (the panel hides Delete for
# them too). Pure predicate factored out + unit-tested (see bridge/tests).
_DELETABLE_SOURCES = ("download", "local")


def _deletable_target(entry: dict, models_root: str):
    """Return (target_dir, None) if `entry` is an app-owned model whose files live
    strictly UNDER models_root and may be safely deleted; else (None, reason).

    Pure/testable: uses only os.path (realpath normalizes even non-existent paths,
    so tests don't need real files). The target is the model's OWN folder — the
    first path segment beneath models_root — regardless of whether the registry
    `path` points at a file (…/model.gguf) or the model dir itself (MLX). Any path
    that resolves outside models_root (traversal, symlink escape, an import pointing
    elsewhere) fails the containment check and is refused."""
    import os as _os
    src = (entry or {}).get("source")
    if src not in _DELETABLE_SOURCES:
        return None, (f"'{src or 'unknown'}' models are read-only imports the harness "
                      f"does not own — remove them in the app that manages them")
    path = (entry or {}).get("path")
    if not path:
        return None, "no file path on record for this model"
    real_root = _os.path.realpath(_os.path.expanduser(str(models_root)))
    real_path = _os.path.realpath(_os.path.expanduser(str(path)))
    # Must sit strictly under the harness models dir (never the dir itself, never outside).
    if real_path != real_root and not real_path.startswith(real_root + _os.sep):
        return None, "model path is outside the harness models directory"
    rel = _os.path.relpath(real_path, real_root)
    first = rel.split(_os.sep)[0]
    if first in ("", ".", ".."):
        return None, "could not resolve a model folder under the models directory"
    return _os.path.join(real_root, first), None


@app.post("/api/models/delete")
async def api_delete_model(req: Request) -> JSONResponse:
    """Delete an app-owned model: remove its folder under data/models/ + its registry
    entry. HARD-guarded — only source in {download, local} AND a realpath strictly
    under data/models/ is ever deleted (never an LM Studio / Jan import, never a path
    outside our dir). If the model is currently live (main runner or aux), it is
    ejected/stopped first."""
    import os as _os, shutil as _shutil
    mid = ((await req.json()).get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "log": "no model id"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if not entry:
        return JSONResponse({"ok": False, "log": f"model '{mid}' not in registry"}, status_code=404)
    models_root = str(ROOT / "data" / "models")
    target, reason = _deletable_target(entry, models_root)
    if not target:
        print(f"[delete] reject {mid!r}: {reason}", flush=True)
        return JSONResponse({"ok": False, "log": reason}, status_code=400)
    # Belt-and-suspenders: re-affirm containment on the resolved target itself.
    real_root = _os.path.realpath(models_root)
    if not (target == _os.path.join(real_root, _os.path.basename(target))
            and target.startswith(real_root + _os.sep)):
        print(f"[delete] reject {mid!r}: target {target} not under {real_root}", flush=True)
        return JSONResponse({"ok": False, "log": "refused: unsafe target path"}, status_code=400)

    c = cfg()
    rc = c.get("runner", {}) or {}
    port = rc.get("port")
    live = _live_model_id(int(port)) if port else None
    was_live = (live == mid) or ((rc.get("model") or "") == mid)
    if was_live:
        _eject_runner()   # stop the runner + clear runner.model before removing files
    # If it's the aux model, stop aux (if up) + clear the aux designation.
    ax = c.get("aux", {}) or {}
    was_aux = (ax.get("model") or "") == mid
    if was_aux:
        if ax.get("port"):
            _aux_kill(int(ax["port"]))
        _set_yaml_model("aux", "")

    if _os.path.isdir(target):
        _shutil.rmtree(target, ignore_errors=True)
    _registry_drop(mid)
    print(f"[delete] removed {mid!r} (dir {target}, was_live={was_live}, was_aux={was_aux})", flush=True)
    return JSONResponse({"ok": True, "id": mid, "was_live": was_live, "was_aux": was_aux})


@app.get("/api/models/switch-status")
def api_switch_status() -> JSONResponse:
    """Poll target: busy flag + human-readable log line. (Download progress moved to
    the download manager — this endpoint tracks model LOADS only.)"""
    return JSONResponse({k: _SWITCH.get(k) for k in ("busy", "log")})


@app.post("/api/models/switch-cancel")
def api_switch_cancel() -> JSONResponse:
    """Cancel an in-flight switch: kill the runner on its port AND the waiting start
    script (legacy jan-serve sweep kept, harmless) — _do_switch then sees the failure
    and rolls the model pin back to the previous one automatically."""
    if not _SWITCH.get("busy"):
        return JSONResponse({"ok": False, "log": "no switch in progress"}, status_code=400)
    port = int((cfg().get("runner", {}) or {}).get("port") or 6767)
    subprocess.run(f'pkill -f "jan serve.*port[= ]{port}"', shell=True, check=False)
    _kill_port_listener(port, force=True)
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
    _kill_port_listener(port, force=True)


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
    # Model-RAM ledger gate: aux candidate + the OTHER slot (main) must fit budget.
    _cand = int(m.get("size_bytes") or 0)
    _other = _loaded_models_bytes(exclude_slot="aux")
    _budget = _budget_bytes()
    if _cand and not _within_budget(_cand, _other, _budget):
        _g = lambda b: round(b / (1024 ** 3), 1)
        return JSONResponse(
            {"ok": False, "log": (f"would exceed model-RAM budget: {_g(_cand)} + "
                                  f"{_g(_other)} > {_g(_budget)} GB — eject something first")},
            status_code=409)
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
        tree = await _HF.get(f"/api/models/{repo}/tree/main", params={"recursive": "true"})
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


def _registry_drop(mid: str) -> None:
    """Read data/models.json, drop the model with id `mid`, atomic write. Used by the
    delete endpoint — note re-seeding would NOT remove a source="download" entry
    (merge preserves non-rescanned sources), so we drop it explicitly here."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or "models" not in data:
            return
    except Exception:
        return
    data["models"] = [m for m in data.get("models", []) if m.get("id") != mid]
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)


def _mlx_registry_entry(e: dict) -> dict:
    """Build the source="download" registry entry for a completed MLX download.
    path = the model DIR; size = summed .safetensors bytes; vision read from the
    now-present config.json (vision_config or image_token_id). Pure/testable."""
    import os as _os, json as _json
    model_dir = e.get("model_dir") or _os.path.dirname(e["files"][0]["dest"])
    size = sum((f["total"] or (_os.path.getsize(f["dest"])
                               if _os.path.exists(f["dest"]) else 0))
               for f in e["files"] if f["dest"].lower().endswith(".safetensors"))
    vision = False
    try:
        cfgp = _os.path.join(model_dir, "config.json")
        if _os.path.isfile(cfgp):
            cj = _json.loads(open(cfgp).read())
            vision = ("vision_config" in cj) or ("image_token_id" in cj)
    except Exception:
        vision = False
    return {"id": e["model_id"], "name": e["model_id"], "format": "mlx",
            "path": model_dir, "mmproj": None, "size_bytes": size,
            "ctx": None, "source": "download", "vision": vision,
            "repo": e.get("repo") or None}   # provenance (mirrors the gguf entry)


def _gguf_registry_entry(e: dict) -> dict:
    """Build the source="download" registry entry for a completed GGUF download.
    path = the primary .gguf (files[0] = part-1 for split models — llama-server
    auto-loads the sibling parts); size = summed non-mmproj bytes; a lone mmproj
    sibling → vision. Pure/testable (mirrors _mlx_registry_entry) so the
    completion→library path can be unit-checked without the network."""
    import os as _os
    main_dest = e["files"][0]["dest"]
    mmproj_dest, nonmm = None, 0
    for f in e["files"]:
        if "mmproj" in _os.path.basename(f["dest"]).lower():
            mmproj_dest = f["dest"]
        else:
            nonmm += f["total"] or (_os.path.getsize(f["dest"])
                                    if _os.path.exists(f["dest"]) else 0)
    return {"id": e["model_id"], "name": e["model_id"], "format": "gguf",
            "path": main_dest, "mmproj": mmproj_dest, "size_bytes": nonmm,
            "ctx": None, "source": "download", "vision": bool(mmproj_dest),
            # Persist the SOURCE REPO: MTP models are commonly named
            # "<repo>/…-MTP-GGUF" while the per-file registry id carries no MTP
            # marker (e.g. Qwen3.5-9B-Q4_0). start_component.sh's speculative-
            # decoding gate matches id OR repo, so without this the MTP flags
            # never engage and you get MTP-without-acceleration.
            "repo": e.get("repo") or None}


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
                # 1 MB read buffer (was 64 KB). Bigger chunks cut per-chunk Python
                # overhead on multi-GB weights; no per-chunk flush/fsync (the OS page
                # cache batches writes) — ISSUE 3 local perf. The observed ~1.4 MB/s
                # average vs a 59 MB/s peak is HF-CDN-side throttling, not this loop
                # (a 64 KB loop already sustains >>100 MB/s locally). ⚠️ unmeasurable
                # in-sandbox (no network) — the safe local improvements are applied.
                with open(part, mode) as out:
                    async for chunk in resp.aiter_bytes(1 << 20):
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
        if e.get("kind") == "mlx":
            _registry_add(_mlx_registry_entry(e))
            e["state"] = "done"
            return
        _registry_add(_gguf_registry_entry(e))
        e["state"] = "done"
    except Exception as ex:
        e["state"] = "error"
        e["error"] = str(ex)[:300]


def _mlx_repo_files(tree: list) -> list:
    """From an HF tree, return [(relpath, size)] for the files an MLX model needs:
    every *.safetensors weight/split, plus config.json/tokenizer*/*.json metadata.
    (config.json is covered by *.json; tokenizer.model — sentencepiece, no .json —
    by the tokenizer* prefix.)"""
    import os as _os
    out = []
    for it in tree:
        p = it.get("path", "")
        low = p.lower()
        b = _os.path.basename(p).lower()
        if (low.endswith(".safetensors") or b.startswith("tokenizer")
                or low.endswith(".json")):
            out.append((p, it.get("size") or 0))
    return out


def _mk_download(repo: str, files: list, model_id: str, kind: str,
                 model_dir=None) -> dict:
    """Register a new DOWNLOADS entry + spawn its task. `files` = the
    _run_download file-dict list already built by the caller."""
    _DL_SEQ["n"] += 1
    dl_id = str(_DL_SEQ["n"])
    entry = {"id": dl_id, "repo": repo, "files": files, "state": "downloading",
             "error": None, "rate": 0.0, "model_id": model_id, "kind": kind,
             "model_dir": model_dir, "task": None}
    DOWNLOADS[dl_id] = entry
    entry["task"] = asyncio.create_task(_run_download(dl_id))
    return entry


def _dl_inflight(model_id: str):
    """Return an in-flight (downloading/paused) DOWNLOADS entry for model_id, or None
    — the duplicate-start guard (two Gets → two tasks on one .part → corruption)."""
    for other in DOWNLOADS.values():
        if other.get("model_id") == model_id and other.get("state") in ("downloading", "paused"):
            return other
    return None


@app.post("/api/dl/start")
async def dl_start(req: Request) -> JSONResponse:
    """Unified acquisition for BOTH formats (Fable PART 0):
      • filename = "<x>.gguf"  → GGUF single-file (split-aware, + lone mmproj sibling).
      • filename = ""          → whole-MLX-repo mode: enqueue every model file into
                                  data/models/<repo-leaf>/ via the same machinery."""
    import os as _os
    body = await req.json()
    repo = (body.get("repo") or "").strip()
    filename = (body.get("filename") or "").strip()
    if not repo:
        return JSONResponse({"ok": False, "log": "repo required"}, status_code=400)
    # One tree fetch feeds both modes. recursive=true so nested files are seen.
    tree = []
    try:
        r = await _HF.get(f"/api/models/{repo}/tree/main", params={"recursive": "true"})
        if r.status_code == 200:
            tree = r.json()
    except Exception:
        tree = []

    if filename == "":
        # ── Whole-MLX-repo mode ──────────────────────────────────────────────
        paths = [it.get("path", "") for it in tree]
        has_gguf = any(p.lower().endswith(".gguf") for p in paths)
        has_st = any(p.lower().endswith(".safetensors") for p in paths)
        has_cfg = any(_os.path.basename(p) == "config.json" for p in paths)
        if has_gguf or not (has_st and has_cfg):
            return JSONResponse(
                {"ok": False, "log": "empty filename = MLX-repo mode, but this repo is "
                 "not an MLX model (needs *.safetensors + config.json, no *.gguf) — "
                 "pick a specific .gguf file instead"}, status_code=400)
        model_id = repo.split("/")[-1]
        dup = _dl_inflight(model_id)
        if dup:
            return JSONResponse(_dl_json(dup))
        dest_dir = ROOT / "data" / "models" / _safe_dir(model_id)
        files = []
        for relpath, size in _mlx_repo_files(tree):
            dest = str(dest_dir / relpath)      # preserve relative layout (usually flat)
            part = dest + ".part"
            done = _os.path.getsize(part) if _os.path.exists(part) else 0
            files.append({"name": relpath, "url": f"/{repo}/resolve/main/{relpath}",
                          "dest": dest, "total": int(size), "done": done})
        entry = _mk_download(repo, files, model_id, "mlx", model_dir=str(dest_dir))
        return JSONResponse(_dl_json(entry))

    # ── GGUF single-file (existing behavior) ─────────────────────────────────
    model_id = _model_id_from_filename(filename)
    dup = _dl_inflight(model_id)
    if dup:
        return JSONResponse(_dl_json(dup))
    file_names = _split_files(filename)
    # Look up sizes + a single mmproj sibling from the repo tree.
    sizes, mmproj_name = {}, None
    for it in tree:
        p = it.get("path", "")
        sizes[_os.path.basename(p)] = it.get("size") or 0
    mmprojs = [it.get("path", "") for it in tree
               if "mmproj" in _os.path.basename(it.get("path", "")).lower()
               and it.get("path", "").lower().endswith(".gguf")]
    if len(mmprojs) == 1:
        mmproj_name = mmprojs[0]
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
    entry = _mk_download(repo, files, model_id, "gguf")
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
    # `model` stays our REGISTRY ID (labels/analytics); `wire` is what the runner
    # accepts — identical for llama.cpp (--alias), the model PATH for MLX servers
    # (which would otherwise try to resolve our id on HF → 404 → runner 400).
    wire = wire_model_id(model, _registry_models())

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
        import json as _json, time as _t
        full, think_open = [], False
        think = []        # thinking sidecar (both reasoning_content + inline <think>)
        t0 = _t.monotonic(); stats = {}   # for best-effort usage analytics
        try:
            async with _RUNNER.stream(
                "POST", f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": wire, "messages": messages,
                      "stream": True, "cache_prompt": True,
                      "stream_options": {"include_usage": True}},
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
                        obj = _json.loads(payload)
                    except Exception:
                        continue
                    # final usage frame (stream_options.include_usage) has empty choices
                    if obj.get("usage") or obj.get("timings"):
                        stats["usage"] = obj.get("usage") or stats.get("usage") or {}
                        stats["timings"] = obj.get("timings") or stats.get("timings") or {}
                    _ch = obj.get("choices") or []
                    if not _ch:
                        continue
                    d = _ch[0].get("delta") or {}
                    if "ttft" not in stats and (d.get("reasoning_content") or d.get("content")):
                        stats["ttft"] = _t.monotonic() - t0
                    # thinking arrives either as reasoning_content or inline <think> tags
                    rsn = d.get("reasoning_content")
                    if rsn:
                        think.append(rsn)
                        yield f'data: {_json.dumps({"delta": rsn, "thinking": True})}\n\n'
                        continue
                    chunk = d.get("content") or ""
                    if not chunk:
                        continue
                    while chunk:
                        if think_open:
                            end = chunk.find("</think>")
                            if end == -1:
                                think.append(chunk)
                                yield f'data: {_json.dumps({"delta": chunk, "thinking": True})}\n\n'
                                chunk = ""
                            else:
                                if chunk[:end]:
                                    think.append(chunk[:end])
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
                persisted = False
                try:
                    # New Odysseus main removed POST /api/session/{sid}/message;
                    # append via the bulk inject_messages endpoint (user before assistant).
                    msgs = [{"role": "user", "content": user_msg}]
                    if answer:
                        msgs.append({"role": "assistant", "content": answer})
                    await _ody_req("POST", f"/api/session/{sid}/inject_messages",
                                   json={"messages": msgs})
                    if answer:
                        persisted = True
                except Exception:
                    pass
                if persisted:
                    # Thinking sidecar: Odysseus stores {role,content} only, so keep
                    # this turn's reasoning locally keyed by (sid, answer hash) →
                    # /api/ody/history rehydrates it on reopen. Never raises.
                    log_thinking(sid, answer, "".join(think).strip())
                if persisted:
                    # Best-effort auto-title: the direct lane skips Odysseus's post-turn
                    # tasks (incl. auto-name), so sessions still called "New chat" get a
                    # local title from the first user message. NEVER affects the stream.
                    try:
                        rs = await _ody_req("GET", "/api/sessions")
                        cur = next((s for s in rs.json() if s.get("id") == sid), None) \
                            if rs.status_code == 200 else None
                        if cur and cur.get("name") == "New chat":
                            t = " ".join(user_msg.split())
                            if len(t) > 42:
                                cut = t[:42]
                                if " " in cut:
                                    cut = cut[:cut.rfind(" ")]
                                t = cut
                            if t:
                                await _ody_req("PATCH", f"/api/session/{sid}",
                                               data={"name": t})
                    except Exception:
                        pass
            try:   # best-effort usage analytics (never breaks the turn)
                u = stats.get("usage") or {}; tm = stats.get("timings") or {}
                cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")
                          or tm.get("cache_n") or 0)
                itok, otok = u.get("prompt_tokens"), u.get("completion_tokens")
                if itok or otok:
                    log_turn("direct", model, itok, otok, cached,
                             tm.get("predicted_per_second"), stats.get("ttft"))
            except Exception:
                pass
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ── Hermes chat lane (Phase 1) — the dashboard's /api/ws JSON-RPC gateway re-emitted
#    as panel SSE (FABLE-HERMES-LANE-SPEC, PATH A). ONE shared WebSocket, multiplexed
#    by session_id; token deltas / thinking / tool events map onto the SAME frame
#    shapes the panel's existing stream renderer already handles; approvals
#    (Phase 2) surface as an interactive panel card answered via
#    POST /api/hermes/approve → approval.respond.
#    ⚠ The /api/ws protocol is upstream-INTERNAL (no stability promise) —
#    bridge/contract_tests/test_hermes_ws_contract.py gates every Hermes pin-bump
#    on the exact method/event names used below.
try:
    import websockets  # bridge/requirements.txt — used ONLY by this lane
except Exception:      # missing dep degrades the lane with a clear error, never the bridge
    websockets = None


def _hermes_token() -> str:
    """Dashboard session token, matching start_component.sh's resolution order:
    harness.yaml components.hermes.dashboard_token override → else the
    generate-once file (data/hermes.token) the start script writes."""
    try:
        tok = str((cfg().get("components", {}).get("hermes", {}) or {})
                  .get("dashboard_token") or "").strip()
        if tok:
            return tok
    except Exception:
        pass
    try:
        return (ROOT / "data" / "hermes.token").read_text().strip()
    except Exception:
        return ""


def _hermes_port() -> int:
    try:
        return int(cfg().get("components", {}).get("hermes", {}).get("port") or 9119)
    except Exception:
        return 9119


# ── PATH-GUARD audit tier (C) ────────────────────────────────────────────────
# Detect-only twin of the guards/harness-path-guard plugin (B1 = the enforcement).
# The plugin can be disabled or misconfigured in ~/.hermes; this tier reads the
# SAME policy roots straight from the repo and flags any COMPLETED write that
# landed outside the allowlist, so the panel shows a faint warning line even when
# the fence is off. Deny roots are irrelevant here (a deny is never written).
_GUARD_ROOTS: list | None = None


def _guard_allow_roots() -> list:
    """Resolved allow roots from guards/harness-path-guard/policy.yaml (cached).

    Placeholders resolve the same way the plugin resolves them: {HARNESS_ROOT} =
    this repo, {TMPDIR} = env, {HERMES_CWD} = the bridge's cwd — which IS the
    Hermes launch cwd (start_component.sh runs both from the repo root).
    ⚠ PENDING FABLE QA: if Hermes is ever launched from a different cwd than the
    bridge, this tier's workspace root drifts (it would over-flag, never under-flag).
    """
    global _GUARD_ROOTS
    if _GUARD_ROOTS is not None:
        return _GUARD_ROOTS
    roots: list = []
    try:
        pol = yaml.safe_load(
            (ROOT / "guards" / "harness-path-guard" / "policy.yaml").read_text()) or {}
        raw = pol.get("allow") if isinstance(pol.get("allow"), list) else []
        home = os.path.expanduser("~")
        subs = {"{HARNESS_ROOT}": str(ROOT), "{TMPDIR}": os.environ.get("TMPDIR", ""),
                "{HERMES_CWD}": os.getcwd()}
        for entry in raw:
            r = str(entry or "").strip()
            if not r:
                continue
            bad = False
            for token, value in subs.items():
                if token in r:
                    if not value:
                        bad = True
                        break
                    r = r.replace(token, value)
            if bad or "{" in r:
                continue
            if r.startswith("~"):
                r = home + r[1:] if r == "~" or r.startswith("~/") else os.path.expanduser(r)
            if not os.path.isabs(r):
                continue
            roots.append(os.path.realpath(r).rstrip(os.sep) or os.sep)
    except Exception as exc:
        print(f"[guard] policy unreadable ({exc}) — audit tier disabled", flush=True)
        roots = []
    _GUARD_ROOTS = roots
    return roots


def guard_path_outside(path: str, roots=None) -> bool:
    """True iff *path* resolves OUTSIDE every allow root (containment via
    commonpath — never string prefixes). Unknown/empty roots → False (the tier
    stays silent rather than crying wolf on every write)."""
    try:
        roots = _guard_allow_roots() if roots is None else roots
        if not roots:
            return False
        p = str(path or "").strip()
        if not p:
            return False
        if p.startswith("~"):
            p = os.path.expanduser(p)
        if not os.path.isabs(p):
            return False       # relative legacy path — cwd unknown here, stay quiet
        t = os.path.realpath(p).rstrip(os.sep) or os.sep
        for r in roots:
            try:
                if os.path.commonpath([t, r]) == r:
                    return False
            except Exception:
                continue
        return True
    except Exception:
        return False


def _guard_flag(path: str, tool: str) -> bool:
    """Audit hook used by the mapper: log ONE warning line and report whether the
    panel should render the faint out-of-workspace notice."""
    if not guard_path_outside(path):
        return False
    print(f"[guard] {tool} wrote OUTSIDE the path-guard allowlist: {path}", flush=True)
    return True


def _guard_audit(path, tool, sid="", stored_sid="") -> None:
    """Durable audit trail: one JSON line per flagged write in data/logs/guard.log.

    The python-log warning above is transient (rotates with bridge.log noise) and
    the SSE guard_flag frame is gone on reload; this file is what the Logs pane's
    `path-guard` source reads. Best-effort — an audit write must NEVER affect the
    stream.
    """
    try:
        import json as _json, datetime as _dt
        d = ROOT / "data" / "logs"
        d.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": str(path or ""), "tool": str(tool or ""), "sid": str(sid or ""),
        }
        # The live gateway sid dies with the session; the STORED id is what the
        # panel's rail can reopen — recorded when the panel supplies it, so an
        # audit entry can jump back to the exact conversation.
        if stored_sid:
            rec["stored_sid"] = str(stored_sid)
        line = _json.dumps(rec, ensure_ascii=False)
        with open(d / "guard.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def hermes_event_to_frames(ev):
    """PURE mapper: one Hermes gateway event → (panel SSE frame dicts, action).

    action: "" = keep streaming, "done" = the turn is over (caller emits [DONE]).
    Stays pure so it can be unit-tested standalone (bridge/tests/
    test_hermes_sse_map.py extracts it by ast; keep it dependency-free).
    Malformed events must NEVER raise.
    """
    try:
        t = (ev or {}).get("type") or ""
        p = (ev or {}).get("payload")
        if not isinstance(p, dict):
            p = {}
        if t == "message.delta":
            txt = p.get("text") or ""
            return ([{"delta": txt}] if txt else [], "")
        if t in ("reasoning.delta", "thinking.delta"):
            txt = p.get("text") or ""
            return ([{"delta": txt, "thinking": True}] if txt else [], "")
        if t == "tool.start":
            return ([{"type": "tool_start", "tool": p.get("name") or "tool"}], "")
        if t == "tool.complete":
            # Slim: never forward the (potentially huge) raw result to the panel.
            fr = {"type": "tool_output", "tool": p.get("name") or "tool"}
            if p.get("summary"):
                fr["summary"] = p.get("summary")
            frames = [fr]
            # §F file cards: a SUCCESSFUL write_file/patch also emits one
            # file_card frame per file touched, so the panel can render a
            # produced-file card (Open / Show in Folder via /api/open).
            # tool.complete payload (tui_gateway/server.py:5044-5088):
            # {tool_id, name, args, result(json-parsed when possible), summary?}.
            # Success = result is a dict WITHOUT "error" (file_tools.py returns
            # json dicts; tool_error always carries "error"). Paths: prefer
            # result.files_modified (ABSOLUTE, file_tools.py:1632/1787 — handles
            # multi-file V4A patches), then result.resolved_path (:1630/1789),
            # then args.path (legacy-resolution fallback :1601-1608 — may be
            # relative/~; forwarded as-is, the relay expands ~ and the panel
            # skips non-absolute ⚠ PENDING FABLE QA). Kept inline (not a helper)
            # so the ast-extracted mapper stays self-contained for the tests.
            if p.get("name") in ("write_file", "patch"):
                res = p.get("result")
                args = p.get("args") if isinstance(p.get("args"), dict) else {}
                if isinstance(res, dict) and not res.get("error"):
                    paths = res.get("files_modified")
                    if not (isinstance(paths, list) and paths):
                        one = res.get("resolved_path") or args.get("path")
                        paths = [one] if one else []
                    seen = set()
                    for fp in paths:
                        fp = str(fp or "").strip()
                        if not fp or fp in seen:
                            continue
                        seen.add(fp)
                        frames.append({"type": "file_card", "path": fp,
                                       "tool": p.get("name")})
                        # Audit tier C: flag a write that landed outside the
                        # path-guard allowlist (detect-only; the plugin enforces).
                        # The inner try keeps the mapper self-contained for the
                        # ast-extracted unit test, where _guard_flag is absent →
                        # NameError → no guard_flag frame (tested separately in
                        # bridge/tests/test_path_guard.py).
                        try:
                            if _guard_flag(fp, p.get("name") or "write"):
                                frames.append({"type": "guard_flag", "path": fp,
                                               "tool": p.get("name")})
                        except Exception:
                            pass
            return (frames, "")
        if t == "approval.request":
            # Phase 2: interactive approval card. NO auto-deny — the relay keeps
            # draining while the panel POSTs /api/hermes/approve → approval.respond.
            # The gateway keys approvals purely by SESSION (FIFO, no request_id on
            # the wire — vendor/hermes/apps/desktop/src/store/prompts.ts:71,
            # tools/approval.py resolve_gateway_approval), so none is forwarded.
            # The command arrives already credential-redacted upstream
            # (tui_gateway/server.py:1592 _emit_approval_request, #48456).
            ch = p.get("choices")
            if not (isinstance(ch, list) and ch):
                # Upstream omits choices only when neither smart_denied nor
                # allow_permanent is set (server.py:1600-1606). Conservative
                # default: never OFFER a persistence scope upstream didn't
                # declare. ⚠ PENDING FABLE QA: ["once","deny"] as the fallback.
                ch = ["once", "deny"]
            # description is forwarded too: for a PLUGIN-escalated approval (the
            # path-guard fence) upstream sets command to the synthetic label
            # "<write_file> (plugin approval rule)" (tools/approval.py
            # request_tool_approval → _run_approval_gate display_target) and puts
            # the real reason — including the target PATH — in description. Without
            # it the card could not show what is being written.
            # ⚠ PENDING FABLE QA: adding description to the existing card (one faint
            # line above the command block), not a new surface.
            return ([{"type": "approval",
                      "request": {"command": p.get("command") or "",
                                  "description": str(p.get("description") or ""),
                                  "choices": [str(c) for c in ch]}}], "")
        if t == "message.complete":
            # Final text is NOT re-emitted — the deltas already built the bubble.
            # ANY message.complete ends the turn: complete / error / interrupted
            # (Phase 1.1 — a dashboard-side interrupt emits status:"interrupted";
            # the panel turn must end, with a short in-stream note).
            if (p.get("status") == "error") or p.get("error"):
                return ([{"type": "proxy_error",
                          "error": str(p.get("error") or "turn failed")[:300]}], "done")
            if p.get("status") == "interrupted":
                return ([{"delta": "\n· interrupted"}], "done")
            return ([], "done")
        if t == "error":
            return ([{"type": "proxy_error",
                      "error": str(p.get("message") or p.get("error")
                                   or "hermes error")[:300]}], "done")
        if t == "_ws_closed":
            # Adapter-injected close sentinel — the shared WS died mid-turn.
            return ([{"type": "proxy_error", "error": "Hermes connection lost"}], "done")
        if t == "status.update":
            return ([{"type": "status", "kind": p.get("kind") or "",
                      "text": p.get("text") or ""}], "")
        return ([], "")  # session.info / gateway.ready / unknown — inspect-only noise, drop
    except Exception:
        return ([], "")


class _HermesWS:
    """ONE shared JSON-RPC client over the dashboard's /api/ws WebSocket.

    - lazy connect on first use; reconnect attempts are spaced by a capped backoff
      so a down Hermes can't hot-loop the bridge;
    - RPCs are id-correlated (id → Future);
    - gateway events (method=event) fan out to per-session asyncio.Queues keyed
      by params.session_id;
    - on connection loss every pending RPC fails and every open queue gets the
      {"type": "_ws_closed"} sentinel so relaying turns terminate cleanly.
    """

    def __init__(self) -> None:
        self._ws = None
        self._lock = asyncio.Lock()
        self._pending: dict = {}      # rpc id → Future
        self._queues: dict = {}       # session_id → asyncio.Queue
        self._next_id = 1
        self._backoff = 0.5

    async def _ensure(self) -> None:
        async with self._lock:
            if self._ws is not None:
                return
            if websockets is None:
                raise RuntimeError("websockets not installed in the bridge venv "
                                   "(pip install websockets)")
            tok = _hermes_token()
            if not tok:
                raise RuntimeError("no Hermes dashboard token — start Hermes from "
                                   "the panel first (it mints data/hermes.token)")
            url = f"ws://127.0.0.1:{_hermes_port()}/api/ws?token={tok}"
            try:
                ws = await websockets.connect(url, max_size=32 * 1024 * 1024,
                                              ping_interval=20, ping_timeout=20,
                                              open_timeout=8)
            except Exception as e:
                delay, self._backoff = self._backoff, min(self._backoff * 2, 8.0)
                await asyncio.sleep(delay)
                raise RuntimeError(f"Hermes dashboard unreachable on "
                                   f":{_hermes_port()}/api/ws — {str(e)[:160]}")
            self._backoff = 0.5
            self._ws = ws
            asyncio.get_running_loop().create_task(self._read_loop(ws))

    async def _read_loop(self, ws) -> None:
        try:
            async for raw in ws:
                # Wire = newline-delimited JSON-RPC (identical to Hermes's stdio
                # transport); one WS text message MAY carry a coalesced token batch.
                for line in str(raw).splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        import json as _json
                        obj = _json.loads(line)
                    except Exception:
                        continue
                    if obj.get("method") == "event":
                        prm = obj.get("params") or {}
                        q = self._queues.get(prm.get("session_id") or "")
                        if q is not None:
                            q.put_nowait({"type": prm.get("type"),
                                          "session_id": prm.get("session_id"),
                                          "payload": prm.get("payload")})
                    elif obj.get("id") is not None:
                        fut = self._pending.pop(obj.get("id"), None)
                        if fut is not None and not fut.done():
                            fut.set_result(obj)
        except Exception:
            pass
        finally:
            self._ws = None
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("Hermes connection lost"))
            self._pending.clear()
            for q in list(self._queues.values()):
                try:
                    q.put_nowait({"type": "_ws_closed"})
                except Exception:
                    pass

    async def rpc(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        import json as _json
        await self._ensure()
        rid = self._next_id
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            await self._ws.send(_json.dumps({"jsonrpc": "2.0", "id": rid,
                                             "method": method, "params": params}))
            resp = await asyncio.wait_for(fut, timeout)
        except Exception:
            self._pending.pop(rid, None)
            raise
        if resp.get("error"):
            raise RuntimeError(str((resp.get("error") or {}).get("message")
                                   or "hermes rpc error"))
        return resp.get("result") or {}

    def open_queue(self, sid: str) -> "asyncio.Queue":
        q: asyncio.Queue = asyncio.Queue()
        self._queues[sid] = q
        return q

    def close_queue(self, sid: str) -> None:
        self._queues.pop(sid, None)


_HERMES = _HermesWS()


def _hermes_stale_sid(err: Exception) -> bool:
    s = str(err).lower()
    return "session" in s and ("not found" in s or "unknown" in s or "no such" in s)


async def _hermes_session_working(sid: str) -> bool:
    """Best-effort probe: is this gateway session still running a turn?

    Uses session.active_list (methods_session.py:726 → _session_live_item status
    ∈ waiting/starting/working/idle). Returns True on ANY doubt — a probe failure
    must never kill a live stream. A session that is absent or "idle" while our
    relay still waits means the turn ended WITHOUT a terminal event reaching us
    (e.g. interrupted from the Hermes dashboard) → the caller ends the turn.
    ⚠ PENDING FABLE QA: text-free structured probe, but the status vocabulary is
    upstream-internal (cover in pin-bump contract tests alongside the RPC names).
    """
    try:
        res = await _HERMES.rpc("session.active_list", {}, timeout=8.0)
        for row in (res.get("sessions") or []):
            if str(row.get("id") or "") == sid:
                return str(row.get("status") or "") in ("working", "starting", "waiting")
        return False  # gone from the gateway → definitely not running
    except Exception:
        return True


@app.post("/api/hermes/chat")
async def hermes_chat(req: Request) -> StreamingResponse:
    """Stream one Hermes turn to the panel as SSE (same protocol as the other lanes).

    Body: {"session_id": <sid or empty>, "message": <text>}. No sid → session.create
    first, and the NEW sid is announced early via {"type":"hermes_session","id":…}
    so the panel can persist it before any tokens arrive. One stale-sid retry.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    msg = (body.get("message") or "").strip()
    stored_sid = (body.get("stored_sid") or "").strip()   # durable id, for the guard audit

    async def gen():
        import json as _json
        nonlocal sid, stored_sid
        q = None
        try:
            if not msg:
                yield 'data: {"type":"proxy_error","error":"empty message"}\n\n'
                return
            if not sid:
                res = await _HERMES.rpc("session.create", {"source": "harness"})
                sid = str(res.get("session_id") or "")
                if not sid:
                    yield 'data: {"type":"proxy_error","error":"session.create returned no id"}\n\n'
                    return
                # stored_id (Phase 3): lets the rail mark the matching stored row.
                stored_sid = stored_sid or str(res.get("stored_session_id") or "")
                yield f'data: {_json.dumps({"type": "hermes_session", "id": sid, "stored_id": str(res.get("stored_session_id") or "")})}\n\n'
            # Open the fan-out queue BEFORE submitting so no early event is missed.
            q = _HERMES.open_queue(sid)
            try:
                await _HERMES.rpc("prompt.submit", {"session_id": sid, "text": msg})
            except RuntimeError as e:
                if not _hermes_stale_sid(e):
                    raise
                # ONE retry: the persisted sid points at a dead gateway session
                # (dashboard restarted) — mint a fresh one and resubmit.
                _HERMES.close_queue(sid)
                res = await _HERMES.rpc("session.create", {"source": "harness"})
                sid = str(res.get("session_id") or "")
                if not sid:
                    raise RuntimeError("session.create returned no id")
                stored_sid = stored_sid or str(res.get("stored_session_id") or "")
                yield f'data: {_json.dumps({"type": "hermes_session", "id": sid, "stored_id": str(res.get("stored_session_id") or "")})}\n\n'
                q = _HERMES.open_queue(sid)
                await _HERMES.rpc("prompt.submit", {"session_id": sid, "text": msg})
            # Relay gateway events until the turn completes. Watchdogs (Phase 1.1):
            #   • first-event: NOTHING within 60s of prompt.submit → end with a clear
            #     error (⚠ PENDING FABLE QA: 60s is a judgment call — local prefill
            #     normally emits status kaomoji well before that);
            #   • liveness: 20s of mid-turn silence → panel-visible "working…" note
            #     (large-prompt prefill on local models reads as dead otherwise) + a
            #     best-effort session.active_list probe — if Hermes says the session
            #     is no longer working, the turn ended without a terminal event
            #     (e.g. interrupted from the dashboard) → end cleanly;
            #   • stop fallback: /api/hermes/stop nudges this queue with a
            #     _stop_requested sentinel; if no terminal event lands within ~3s
            #     the relay ends the turn itself;
            #   • hard guard: 600s of TOTAL silence still aborts (unchanged).
            got_any = False
            silent = 0.0
            noted_slow = False
            approval_pending = False  # Phase 2: an approval card awaits the user
            stop_at = None  # monotonic deadline once a panel Stop was requested
            while True:
                if stop_at is not None:
                    timeout = max(0.25, stop_at - asyncio.get_running_loop().time())
                else:
                    timeout = 20.0
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    if stop_at is not None:
                        # Stop was requested but no terminal event arrived — end anyway.
                        yield f"data: {_json.dumps({'delta': chr(10) + '· interrupted'})}\n\n"
                        break
                    silent += timeout
                    if not got_any and silent >= 60.0:
                        yield ('data: {"type":"proxy_error","error":'
                               '"no response from Hermes within 60s of submit — '
                               'check the Hermes dashboard / model config"}\n\n')
                        break
                    if silent >= 600.0:
                        yield ('data: {"type":"proxy_error","error":'
                               '"hermes turn idle >10min — giving up"}\n\n')
                        break
                    if approval_pending:
                        # Phase 2: the approval card IS the status — suppress the
                        # 20s working note AND the liveness probe while the user
                        # decides (the agent thread is blocked in
                        # _await_gateway_decision; upstream's own 300s approval
                        # timeout resolves it, and the 600s hard guard above
                        # stays). Panel Stop still works: session.interrupt
                        # auto-denies the pending approval (tools/approval.py:
                        # 3326-3335, #8697) → message.complete(interrupted).
                        # ⚠ PENDING FABLE QA: probe skipped too, not just the
                        # note — a probe misread must never kill a pending card.
                        continue
                    if got_any and not await _hermes_session_working(sid):
                        # Turn ended upstream with no terminal event reaching us
                        # (dashboard-side interrupt was the live repro) — close it.
                        yield f"data: {_json.dumps({'delta': chr(10) + '· interrupted'})}\n\n"
                        break
                    if not noted_slow:
                        noted_slow = True
                        yield ('data: {"type":"hermes_status","text":'
                               '"hermes is working — large prompt prefill can take '
                               'a while on local models"}\n\n')
                    continue
                got_any = True
                silent = 0.0
                noted_slow = False
                if (ev or {}).get("type") == "_stop_requested":
                    # Panel Stop: session.interrupt was issued — give the mapped
                    # message.complete(status=interrupted) ~3s to land, then force-end.
                    if stop_at is None:
                        stop_at = asyncio.get_running_loop().time() + 3.0
                    continue
                # Phase 2: an approval.request opens a pending card; ANY other
                # event means the wait resolved (post-decision tool/turn events
                # only flow once resolve_gateway_approval unblocked the agent).
                approval_pending = ((ev or {}).get("type") == "approval.request")
                frames, action = hermes_event_to_frames(ev)
                for fr in frames:
                    if fr.get("type") == "file_card":
                        # §F: mapper stays pure — expand ~ here (Hermes runs as
                        # this same user). Relative paths pass through as-is
                        # (session cwd not on the wire ⚠ PENDING FABLE QA); the
                        # panel only renders absolute/home paths.
                        try:
                            fp = str(fr.get("path") or "")
                            if fp.startswith("~"):
                                fr["path"] = os.path.expanduser(fp)
                        except Exception:
                            pass
                    elif fr.get("type") == "guard_flag":
                        _guard_audit(fr.get("path"), fr.get("tool"), sid, stored_sid)
                    yield f"data: {_json.dumps(fr, ensure_ascii=False)}\n\n"
                if action == "done":
                    break
        except Exception as e:
            yield f'data: {_json.dumps({"type": "proxy_error", "error": str(e)[:300]})}\n\n'
        finally:
            if q is not None:
                _HERMES.close_queue(sid)
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/hermes/stop")
async def hermes_stop(req: Request) -> JSONResponse:
    """Interrupt a running Hermes turn (panel Stop button).

    Nudges the relay FIRST via a _stop_requested queue sentinel (arms its ~3s
    force-end fallback even if the RPC below stalls), then issues the gateway's
    session.interrupt (vendor/hermes/tui_gateway/methods_session.py:2705) — the
    normal path is that Hermes then emits message.complete(status="interrupted"),
    which the mapper turns into a clean turn end.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    q = _HERMES._queues.get(sid)
    if q is not None:
        try:
            q.put_nowait({"type": "_stop_requested"})
        except Exception:
            pass
    try:
        res = await _HERMES.rpc("session.interrupt", {"session_id": sid}, timeout=10.0)
        return JSONResponse({"ok": True,
                             "status": res.get("status") or "interrupted"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/approve")
async def hermes_approve(req: Request) -> JSONResponse:
    """Answer a pending approval card (Phase 2 chip UX).

    The gateway keys approvals purely by SESSION — resolve_gateway_approval
    (vendor/hermes/tools/approval.py:2198) pops the oldest pending entry FIFO;
    there is no request id on the wire (desktop store/prompts.ts:71) — so
    {session_id, choice} is the complete address. approval.respond params:
    {session_id, choice, all?} (tui_gateway/methods_prompt.py:864-883); the
    optional resolve-all flag is deliberately NOT exposed to the panel.
    """
    body = await req.json()
    sid = (body.get("session_id") or "").strip()
    choice = (body.get("choice") or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    if choice not in ("once", "session", "always", "deny"):
        return JSONResponse({"error": "invalid choice"}, status_code=400)
    try:
        res = await _HERMES.rpc("approval.respond",
                                {"session_id": sid, "choice": choice}, timeout=10.0)
        # resolved=0 → nothing was pending (card raced a timeout/interrupt);
        # surface it so the panel can stamp the card instead of lying "approved".
        return JSONResponse({"ok": True, "resolved": res.get("resolved")})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=502)


def hermes_sessions_normalize(rows):
    """PURE (unit-tested standalone): gateway session.list rows → the panel
    rail shape [{id, name, updated_at, message_count, source}].

    session.list rows (methods_session.py:196-206): {id, title, preview,
    started_at, message_count, source}. NOTE the WS projection forwards
    started_at ONLY — list_sessions_rich's last_active is dropped upstream —
    so the rail's relative time is the session START time; the ORDERING from
    the gateway IS by last activity. ⚠ PENDING FABLE QA (honest-but-odd stamp).
    started_at may be epoch seconds or ms; both → ISO-8601 UTC ('' if absent).
    Untitled rows fall back to the preview snippet (Hermes's own picker does
    the same). Malformed rows are dropped, never raise."""
    out = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        iso = ""
        try:
            ts = float(r.get("started_at") or 0)
            if ts > 1e12:          # milliseconds epoch
                ts = ts / 1000.0
            if ts > 0:
                from datetime import datetime, timezone
                iso = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except Exception:
            iso = ""
        try:
            mc = int(r.get("message_count") or 0)
        except Exception:
            mc = 0
        title = str(r.get("title") or "").strip()
        preview = str(r.get("preview") or "").strip()
        out.append({"id": rid,
                    "name": title or preview or "Untitled",
                    "updated_at": iso,
                    "message_count": mc,
                    "source": str(r.get("source") or "")})
    return out


def hermes_messages_to_panel(messages):
    """PURE (unit-tested standalone): gateway _history_to_messages rows →
    the panel history shape [{role, content}] the Odysseus loader renders.

    Gateway rows (server.py:6645 _history_to_messages): user/assistant carry
    {role, text, reasoning*…}; tool rows are {role:'tool', name, context};
    system rows possible. Only user/assistant rows survive — tool rows are
    dropped (tool detail isn't reconstructible on reopen).

    THINKING REHYDRATION (2026-08-06, Fable QA pass): unlike the direct lane —
    which persists {role, content} to Odysseus and therefore has NOTHING stored
    to restore — Hermes's own store DOES keep the reasoning, so a reopened
    session shows its thinking again as the same collapsed disclosure.

    Aligned with the UPSTREAM projection (server.py _history_to_messages):
    (1) its reasoning keys are exactly reasoning / reasoning_content /
        reasoning_details / codex_reasoning_items — the structured ones are
        flattened defensively (list items: strings, or dicts with a text-ish
        field); a surprise type must never break a transcript.
    (2) reasoning-ONLY assistant turns (thinking with no visible answer) are
        KEPT, mirroring upstream's own #44022 fix — dropping them made
        extended-thinking turns vanish from reopened sessions."""
    def _flatten_reasoning(v):
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, list):
            parts = []
            for it in v:
                if isinstance(it, str) and it.strip():
                    parts.append(it.strip())
                elif isinstance(it, dict):
                    for tk in ("text", "reasoning", "content", "summary"):
                        tv = it.get(tk)
                        if isinstance(tv, str) and tv.strip():
                            parts.append(tv.strip())
                            break
            return "\n".join(parts)
        return ""

    out = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        txt = m.get("text")
        txt = txt if isinstance(txt, str) else ""
        reasoning = ""
        if role == "assistant":
            for k in ("reasoning", "reasoning_content",
                      "reasoning_details", "codex_reasoning_items"):
                reasoning = _flatten_reasoning(m.get(k))
                if reasoning:
                    break
        if not txt.strip() and not reasoning:
            continue    # truly empty row — nothing to show
        row = {"role": role, "content": txt}
        if reasoning:
            row["reasoning"] = reasoning
        out.append(row)
    return out


@app.get("/api/hermes/sessions")
async def hermes_sessions() -> JSONResponse:
    """Stored Hermes sessions for the rail (Phase 3; WS-based, no REST token dance).

    session.list (methods_session.py:162) reads state.db ordered by last
    activity; rows are normalized bridge-side (pure hermes_sessions_normalize).
    NOTE: a freshly created EMPTY session has no DB row yet (the write is
    deferred to the first prompt — methods_session.py:895-904 comment), so it
    won't appear here until its first turn. ⚠ PENDING FABLE QA."""
    try:
        res = await _HERMES.rpc("session.list", {"limit": 100})
        return JSONResponse(hermes_sessions_normalize(res.get("sessions") or []))
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/new")
async def hermes_session_new() -> JSONResponse:
    try:
        res = await _HERMES.rpc("session.create", {"source": "harness"})
        return JSONResponse({"id": res.get("session_id"),
                             "stored_id": res.get("stored_session_id")})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/resume")
async def hermes_session_resume(req: Request) -> JSONResponse:
    """Reopen a STORED Hermes session: transcript + a LIVE sid to continue it.

    session.resume (methods_session.py:305) is the real mechanism — it returns
    a NEW live session_id bound to the stored conversation plus the full display
    transcript (every branch of it includes `messages`: lazy :453, deferred
    :533, eager/live-reuse via _live_session_payload server.py:7588-7597, which
    also carries session_key). prompt.submit on the returned live sid continues
    the conversation — full parity, not read-only. The deferred (default) path
    schedules the agent build OFF the response path, so this returns quickly;
    re-clicking an already-open row hits the live-reuse fast path (:392-396).
    """
    body = await req.json()
    stored = (body.get("id") or "").strip()
    if not stored:
        return JSONResponse({"error": "id required"}, status_code=400)
    try:
        res = await _HERMES.rpc("session.resume",
                                {"session_id": stored, "source": "harness"},
                                timeout=30.0)
        return JSONResponse({
            "id": res.get("session_id") or "",
            "stored_id": str(res.get("session_key") or res.get("resumed") or stored),
            "history": hermes_messages_to_panel(res.get("messages") or []),
            "running": bool(res.get("running")),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/{sid}/rename")
async def hermes_session_rename(sid: str, req: Request) -> JSONResponse:
    """Rename a STORED Hermes session.

    The WS gateway has no stored-session rename (session.title is live-session-
    gated via _sess_nowait, methods_session.py:838-840), but the dashboard REST
    router does: PATCH /api/sessions/{id} {title} (web_routers/sessions.py:650),
    auth = the same session token, header X-Hermes-Session-Token
    (web_server.py:305/368-398). ⚠ PENDING FABLE QA: this is the lane's ONE
    REST call amid an otherwise WS-only adapter (mixed transport, contract-
    tested at pin-bump)."""
    body = await req.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    tok = _hermes_token()
    if not tok:
        return JSONResponse({"error": "no Hermes dashboard token"}, status_code=502)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.patch(
                f"http://127.0.0.1:{_hermes_port()}/api/sessions/{sid}",
                json={"title": name},
                headers={"X-Hermes-Session-Token": tok})
        if r.status_code >= 400:
            return JSONResponse({"error": f"rename failed ({r.status_code})"},
                                status_code=502)
        return JSONResponse({"ok": True, "name": name})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/hermes/session/{sid}/delete")
async def hermes_session_delete(sid: str, req: Request) -> JSONResponse:
    """Delete a STORED Hermes session (WS session.delete, methods_session.py:788).

    The gateway refuses to delete a session that is LIVE in-process (4023 —
    correct: the live agent is still writing to it). If the panel is deleting
    the row it currently has open, it passes the live sid as `live_id` and the
    bridge closes that gateway session first (session.close,
    methods_session.py:2561) so the stored row becomes deletable."""
    live_id = ""
    try:
        body = await req.json()
        live_id = (body.get("live_id") or "").strip()
    except Exception:
        pass
    try:
        if live_id:
            try:
                await _HERMES.rpc("session.close", {"session_id": live_id},
                                  timeout=15.0)
            except Exception:
                pass   # close is best-effort; delete below reports the truth
        res = await _HERMES.rpc("session.delete", {"session_id": sid})
        return JSONResponse({"ok": True, "deleted": res.get("deleted") or sid})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.get("/api/hermes/history/{sid}")
async def hermes_history(sid: str) -> JSONResponse:
    """Transcript of a LIVE gateway session (session.history is live-gated via
    _sess_nowait — methods_session.py:2258-2260; stored sessions go through
    /api/hermes/session/resume instead, which returns the transcript too)."""
    try:
        res = await _HERMES.rpc("session.history", {"session_id": sid})
        return JSONResponse({"history": res.get("messages") or [],
                             "count": res.get("count") or 0})
    except Exception as e:
        return JSONResponse({"error": str(e)[:300]}, status_code=502)


@app.post("/api/open")
async def open_external(req: Request) -> JSONResponse:
    """Open an http(s) URL in the default browser, OR open/reveal a local file.

    Two modes:
      {"url": "https://…"}                       → open in default browser (http(s) only).
      {"path": "~/…", "action": "open"|"reveal"} → open a local FILE with the default app,
                                                    or reveal it in Finder (`open -R`).

    File path-allowlist (Fable-authored §F gate): the resolved realpath must EXIST and live
    UNDER $HOME — nothing outside the user's home is ever opened. `file://` is never accepted
    in the url field. Rejections are logged.
    """
    import os
    data = await req.json()
    path = data.get("path", "")
    url = data.get("url", "")

    if path:
        action = (data.get("action") or "open").lower()
        real = os.path.realpath(os.path.expanduser(path))
        home = os.path.expanduser("~") + os.sep
        if not os.path.exists(real):
            print(f"[open] reject (missing): {real}", flush=True)
            return JSONResponse({"ok": False, "log": "path does not exist"}, status_code=400)
        if not real.startswith(home):
            print(f"[open] reject (outside $HOME): {real}", flush=True)
            return JSONResponse({"ok": False, "log": "path must be under your home folder"}, status_code=403)
        args = ["open", "-R", real] if action == "reveal" else ["open", real]
        subprocess.run(args, check=False)
        return JSONResponse({"ok": True})

    # url mode — http(s) only; never `file://` (that would bypass the path gate above).
    if not (url.startswith("http://") or url.startswith("https://")):
        return JSONResponse({"ok": False, "log": "only http(s) urls"}, status_code=400)
    subprocess.run(["open", url], check=False)
    return JSONResponse({"ok": True})


# ── Canvas: save an edited artifact to disk (Fable canvas spec, 2026-07-31) ──
# Extensions the artifact viewer holds as TEXT (mirrors the panel's artifactKind
# EXT map minus the binary kinds image/pdf, plus txt). Anything else → reject.
_ARTIFACT_SAVE_EXTS = {
    "html", "htm", "svg", "jsx", "tsx", "js", "mjs", "cjs",
    "md", "markdown", "mdown", "mmd", "mermaid", "csv", "tsv", "json",
    "py", "ts", "go", "rs", "sh", "bash", "zsh", "yaml", "yml", "toml", "ini",
    "xml", "env", "c", "h", "cpp", "cc", "hpp", "cs", "java", "rb", "php",
    "css", "scss", "sql", "swift", "kt", "lua", "r", "pl", "txt",
}
_ARTIFACT_SAVE_MAX = 5 * 1024 * 1024   # ~5MB content cap (spec)


def sanitize_artifact_filename(name) -> str | None:
    """PURE (unit-tested: bridge/tests/test_artifact_save.py).

    Reduce an UNTRUSTED filename to a safe basename, or return None (reject).
    Guarantees: no path separators / traversal, printable ASCII-safe charset,
    no leading dot (no dotfiles), non-empty bounded stem, whitelisted extension.
    The caller builds the path server-side as SAVE_DIR/<returned basename> —
    NEVER from raw client input.
    """
    import re
    s = str(name or "")
    if len(s) > 512:                                    # absurd input → reject outright
        return None
    s = s.replace("\\", "/").rsplit("/", 1)[-1]         # basename only (both separators)
    s = "".join(ch for ch in s if ch.isprintable())     # drop control/format chars (NUL, \n, RLO…)
    s = re.sub(r"[^A-Za-z0-9._ -]+", "_", s)            # ASCII-safe charset; unicode → _
    s = re.sub(r"\.{2,}", ".", s)                       # collapse dot runs ('..' remnants)
    s = re.sub(r"\s+", " ", s).strip(" .")              # tidy spaces; no edge dots (no dotfiles)
    m = re.fullmatch(r"(.+)\.([A-Za-z0-9]+)", s)
    if not m:
        return None                                     # empty / no extension
    stem, ext = m.group(1)[:80].strip(" ."), m.group(2).lower()   # overlong → cap stem
    if not stem or ext not in _ARTIFACT_SAVE_EXTS:
        return None
    return f"{stem}.{ext}"


@app.post("/api/artifact/save")
async def artifact_save(req: Request) -> JSONResponse:
    """Save an edited artifact buffer to ~/Downloads/harness-artifacts/ (canvas Save).

    SECURITY (Fable spec, non-negotiable): the client sends {filename, content}
    ONLY — never a path. The filename is reduced to a sanitized, extension-
    whitelisted basename; the path is constructed server-side under the fixed
    save dir; content is size-capped (~5MB). Existing files are never clobbered
    (' (n)' suffix). Writes and rejections are logged.
    """
    import os
    data = await req.json()
    content = data.get("content")
    if not isinstance(content, str):
        return JSONResponse({"ok": False, "log": "content must be a string"},
                            status_code=400)
    if len(content.encode("utf-8", errors="ignore")) > _ARTIFACT_SAVE_MAX:
        print("[artifact] reject save: content over the 5MB cap", flush=True)
        return JSONResponse({"ok": False, "log": "content exceeds the 5MB cap"},
                            status_code=413)
    name = sanitize_artifact_filename(data.get("filename", ""))
    if not name:
        print(f"[artifact] reject save: bad filename {data.get('filename')!r}", flush=True)
        return JSONResponse({"ok": False, "log": "invalid or non-whitelisted filename"},
                            status_code=400)
    save_dir = os.path.join(os.path.expanduser("~"), "Downloads", "harness-artifacts")
    os.makedirs(save_dir, exist_ok=True)
    stem, ext = name.rsplit(".", 1)
    path = os.path.join(save_dir, name)
    n = 1
    while os.path.exists(path) and n < 100:     # never clobber (⚠ PENDING FABLE QA: suffix policy)
        path = os.path.join(save_dir, f"{stem} ({n}).{ext}")
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[artifact] saved {len(content)} chars → {path}", flush=True)
    return JSONResponse({"ok": True, "path": path})


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
