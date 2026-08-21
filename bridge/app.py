"""Harness bridge — control panel + component lifecycle API.

M0/M1 scope: status, install (with plan → approve → execute), start/stop.
Gearbox (M2) and adapter/self-heal (M3) are stubs; see gearbox.py / adapter.py.
"""
from __future__ import annotations

import asyncio
import base64
import functools
import os
import random
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
PANEL = Path(__file__).resolve().parent / "panel"

# Harness-native voice capability (Phase B). Imported DEFENSIVELY: ship.sh has
# historically copied only bridge/app.py into the fat snapshot, so a snapshot that
# predates voice.py must still boot a working bridge — it just loses /api/voice/tts
# (which reports the import error) and treats every registry entry as a chat model,
# i.e. exactly today's behaviour. ship.sh now copies every bridge/*.py.
_VOICE_ERR = ""
try:
    from . import voice as _voice           # normal: loaded as the package bridge.app
except Exception:                            # noqa: BLE001
    try:
        from bridge import voice as _voice   # loaded as a top-level module
    except Exception as _e:                  # noqa: BLE001
        _voice, _VOICE_ERR = None, str(_e)[:200]
        print(f"[voice] module unavailable — TTS disabled ({_VOICE_ERR})", flush=True)

# Harness-native MUSIC lane (FABLE-MUSIC-LANE-SPEC). Same defensive import as voice,
# for the same reason: a snapshot missing this file must still boot a bridge that
# works, minus /api/music/*.
_MUSIC_ERR = ""
try:
    from . import music as _music
except Exception:                                # noqa: BLE001
    try:
        from bridge import music as _music
    except Exception as _e:                      # noqa: BLE001
        _music, _MUSIC_ERR = None, str(_e)[:200]
        print(f"[music] module unavailable — music lane disabled ({_MUSIC_ERR})", flush=True)

# The AIDER coding-agent lane (PTY over a websocket). Same defensive import for the
# same reason: a snapshot missing this file must still boot a bridge that works, minus
# /aider and /api/pty/aider.
_PTY_ERR = ""
try:
    from . import pty_aider as _pty
except Exception:                                # noqa: BLE001
    try:
        from bridge import pty_aider as _pty
    except Exception as _e:                      # noqa: BLE001
        _pty, _PTY_ERR = None, str(_e)[:200]
        print(f"[aider] module unavailable — the aider tab is disabled ({_PTY_ERR})",
              flush=True)

# The OFFICE lane (spreadsheets over vendored Univer). Same defensive import for the
# same reason: a snapshot missing this file — or a bridge venv without openpyxl —
# must still boot a bridge that works, minus /office and /api/office/*.
_OFFICE_ERR = ""
try:
    from . import office as _office
except Exception:                                # noqa: BLE001
    try:
        from bridge import office as _office
    except Exception as _e:                      # noqa: BLE001
        _office, _OFFICE_ERR = None, str(_e)[:200]
        print(f"[office] module unavailable — the Office tab is disabled ({_OFFICE_ERR})",
              flush=True)

# NAV — the sidebar/tab-strip customization model (FABLE-STUDIO-PHASE2-SPEC §A). Same
# defensive import for the same reason: without it the panel falls back to its own
# default layout and the shell keeps its built-in tab order, i.e. exactly the
# behaviour before this slice.
_NAV_ERR = ""
try:
    from . import nav as _nav
except Exception:                                # noqa: BLE001
    try:
        from bridge import nav as _nav
    except Exception as _e:                      # noqa: BLE001
        _nav, _NAV_ERR = None, str(_e)[:200]
        print(f"[nav] module unavailable — default layout only ({_NAV_ERR})", flush=True)

# MODELTOOLS — the per-model tool-calling verdict (the OpenCode slice). Same
# defensive import for the same reason: without it every model simply reports
# `tools: null`, i.e. no pill and no warning — never a broken Models pane.
# scripts/seed_registry.py loads the SAME file by path, so there is one implementation.
_MODELTOOLS_ERR = ""
try:
    from . import modeltools as _modeltools
except Exception:                                # noqa: BLE001
    try:
        from bridge import modeltools as _modeltools
    except Exception as _e:                      # noqa: BLE001
        _modeltools, _MODELTOOLS_ERR = None, str(_e)[:200]
        print(f"[models] modeltools unavailable — no tool-calling pills "
              f"({_MODELTOOLS_ERR})", flush=True)

app = FastAPI(title="AI Harness Bridge")

# Serve the panel's self-hosted assets (Phase 2 artifact renderer: babel/react/prism/
# markdown-it/dompurify) same-origin at /assets/vendor/*. Fully offline — no runtime CDN.
# The vendor dir is gitignored + fetched by scripts/fetch_vendor_assets.sh (run once on
# the Mac / at FAT build). Ensure the mount point exists so startup never errors when the
# libs haven't been fetched yet (the renderer degrades gracefully in that case).
(PANEL / "assets" / "vendor").mkdir(parents=True, exist_ok=True)


class _WatchedStatic(StaticFiles):
    """StaticFiles that LOGS the Univer bundles, and nothing else.

    ⚠️ WHY THIS IS A StaticFiles SUBCLASS AND NOT `@app.middleware("http")`. It exists
    to answer one question — when LOffice's boot trace stops after a given bundle, was
    that file NEVER REQUESTED (the parser died before the tag, or the page never got
    that far) or REQUESTED AND NEVER FINISHED (a stalled transfer)? Those are different
    faults with the same symptom and nothing else in the stack distinguishes them:
    uvicorn's access log is not on in our launch line and a StaticFiles hit is
    otherwise silent.

    A `BaseHTTPMiddleware` would answer it too — and would also wrap EVERY response in
    the harness, including the SSE chat relays, in a queue-and-pump that is documented
    to interfere with streaming and background tasks. The whole Hermes lane rides those
    streams (a 20s heartbeat frame the panel's stall watchdog counts on), so a
    diagnostic for the spreadsheet tab may not go anywhere near them. This subclass
    touches exactly the one mount, and logs only the prefix below.
    """

    # ⚠️ MATCHED AS A SUBSTRING, DELIBERATELY, AND THE FIRST DRAFT GOT THIS WRONG.
    # It watched `scope["path"].startswith("/vendor/univer/")` on the reasoning that a
    # Mount rewrites the path to be relative to itself. This Starlette does NOT: it
    # leaves `path` as the FULL "/assets/vendor/univer/x.js" and puts "/assets" in
    # `root_path` — so the branch never fired and the whole diagnostic was a no-op that
    # looked correct in review. It was caught by driving the real page in a real
    # browser and finding zero lines in the log. A substring is true under BOTH
    # conventions, which is the point.
    #
    # The set is exactly what bridge/panel/office.html's VENDOR list loads: the five
    # univer files plus React and React-DOM, which live one directory up because the
    # artifact renderer already vendored them. ⚠️ Those two are therefore ALSO logged
    # when an artifact opens — two lines, and arguably useful there too.
    WATCH = ("/vendor/univer/", "/vendor/react.production.min.js",
             "/vendor/react-dom.production.min.js")

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if not any(w in path for w in self.WATCH):
            return await super().__call__(scope, receive, send)
        t0 = time.time()
        _office_log(f"loffice-asset → {scope.get('method', '?')} {path}")
        sent = {"status": 0, "bytes": 0}

        async def _send(msg):
            if msg.get("type") == "http.response.start":
                sent["status"] = msg.get("status", 0)
            elif msg.get("type") == "http.response.body":
                sent["bytes"] += len(msg.get("body") or b"")
            await send(msg)

        try:
            await super().__call__(scope, receive, _send)
        except Exception as e:                                   # noqa: BLE001
            _office_log(f"loffice-asset ✗ {path} raised {type(e).__name__}: {e}")
            raise
        # A `→` with no matching `←` is the stalled case, spelled out rather than
        # inferred from a gap in the trace.
        _office_log(f"loffice-asset ← {sent['status']} {path} {sent['bytes']}B "
                    f"{int((time.time() - t0) * 1000)}ms")


app.mount("/assets", _WatchedStatic(directory=str(PANEL / "assets")), name="assets")


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
            if n == "runner":
                _record_load_launch((c.get("runner", {}) or {}).get("model") or "")
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


# ── COMPONENT HEALTH: one probe budget per component, ONE debounced verdict ───
# Debi 2026-08-21: the activity feed said `opencode degraded — health lost` while the
# opencode CARD still read Online. Those two surfaces are drawn from the SAME field
# on the SAME poll (panel/index.html:1854-1856), so they never disagreed at a single
# instant — the card is repainted from scratch every poll and shows NOW, while the
# feed is a permanent scrollback line about a PAST instant that nothing ever
# retracted. A one-poll blip therefore left a scary line sitting beside a green card.
#
# Two entirely healthy things produce exactly that one-poll blip:
#   1. A CLI RESTART. `ship.sh --restart opencode` runs the snapshot's
#      start_component.sh (ship.sh:230), whose opencode arm clears the listener and
#      only writes the NEW pid about a second later (start_component.sh:1016-1033).
#      Nothing on that path touches data/<name>.expected — only the panel's Start
#      writes it (_mark_expected, _provision) and only Stop clears it — so for that
#      window the component is "expected-up, no listener, and a pid file naming a
#      process that has just been killed", i.e. degraded by the letter of the rule.
#   2. PROBE CONGESTION. `asyncio.wait_for(open_connection, 0.5)` can fire because
#      our own event loop was busy, not because the port was gone. /api/status probes
#      every component SEQUENTIALLY on that loop, which it shares with the SSE chat
#      relays and LOffice's ~10MB static reads.
#
# So: let a component that needs it have its OWN probe budget, and require a miss to
# PERSIST before calling it lost — the shape the panel already uses for the bridge
# itself (index.html:1820, three consecutive misses before BRIDGE UNREACHABLE).
PROBE_TIMEOUT_DEFAULT = 0.5
# opencode is a ~144MB Bun executable that does real work on its first requests.
# The probe stays a TCP handshake and is DELIBERATELY NOT an HTTP GET to its own
# /global/health (start_component.sh:1040 uses that for the readiness poll, and
# global.ts:66 defines it): a handshake is completed by the KERNEL from the listen
# backlog and needs nothing from the server's event loop, whereas an HTTP probe does
# — which makes an HTTP probe strictly MORE likely to time out on a busy server,
# i.e. the exact false negative being fixed here. The wider budget is insurance
# against OUR loop, and costs nothing at all when the port answers (sub-millisecond).
PROBE_TIMEOUT_S = {"opencode": 2.0}
HEALTH_MISS_LOST = 3            # consecutive failed probes before "lost"
_HEALTH_MISS: dict = {}         # component -> consecutive failed probes


def _probe_timeout(name: str, expected: bool = True) -> float:
    """Probe budget for one component. Everything not named in PROBE_TIMEOUT_S keeps
    the historical 0.5s exactly — and so does a component we are NOT expecting to be
    up (Stop clears data/<name>.expected), because a component with no alarm to raise
    is not worth making every /api/status poll 1.5s slower for. The wide budget is
    only ever spent where it can PREVENT a false alarm."""
    if not expected:
        return PROBE_TIMEOUT_DEFAULT
    return PROBE_TIMEOUT_S.get(name, PROBE_TIMEOUT_DEFAULT)


def health_verdict(expected: bool, running: bool, misses: int,
                   lost_at: int = HEALTH_MISS_LOST) -> str:
    """PURE (unit-tested). ok | transient | lost.
         running, or never started by us   -> ok
         expected-up and missing, briefly  -> transient  (restart window / busy loop)
         expected-up and missing, N times  -> lost       (it really is gone)
    Total: a junk miss count degrades to 'transient', never to a false 'lost' — and
    the type check is STRICT rather than an int() coercion on purpose, so no value
    arriving as a string can ever escalate an alarm."""
    if running or not expected:
        return "ok"

    def _int(v, fallback, floor=None):
        ok = isinstance(v, int) and not isinstance(v, bool)
        return v if ok and (floor is None or v >= floor) else fallback
    m = _int(misses, 0)
    # A threshold below 1 is nonsense (it would mean "declare lost before a probe has
    # even missed"), so it falls back to the default rather than being clamped into
    # the most alarming possible behaviour.
    n = _int(lost_at, HEALTH_MISS_LOST, floor=1)
    return "lost" if m >= n else "transient"


def _health_track(name: str, expected: bool, running: bool) -> tuple:
    """Advance the consecutive-miss counter for `name`; return (verdict, misses).
    A recovery (or a clean Stop, which clears .expected) forgets the streak, so a
    component that blips twice an hour never accumulates its way to 'lost'."""
    if running or not expected:
        _HEALTH_MISS.pop(name, None)
        return ("ok", 0)
    m = _HEALTH_MISS.get(name, 0) + 1
    _HEALTH_MISS[name] = m
    return (health_verdict(expected, running, m), m)


@app.get("/api/status")
async def status() -> dict:
    import shutil
    c = cfg()
    du = shutil.disk_usage(ROOT)
    out = {
        "bridge": "ok",
        "disk": {"free_gb": round(du.free / 1e9, 1), "total_gb": round(du.total / 1e9, 1)},
        # How many times WE have changed Hermes's configuration this process. The
        # Swift shell records it when the Hermes webview loads and reloads that
        # webview when it has increased, because Hermes's own Skills page never
        # refreshes itself (see the _HERMES_CFG_GEN block). Costs nothing to
        # publish here and needs no new route.
        "hermes_config_gen": hermes_cfg_gen(),
        # …and the same carrier for the NAV layout: the shell rebuilds its tab strip
        # when this moves (see the _NAV_GEN block). One int, no new route.
        "nav_gen": nav_gen(),
        "components": {},
    }
    for name, comp in c["components"].items():
        port = comp.get("port") or comp.get("mcp_port")
        expected = _expected_path(name).exists()
        running = ((await _port_alive(int(port), _probe_timeout(name, expected))
                    if port else False) or _pid_alive(name))
        verdict, misses = _health_track(name, expected, running)
        out["components"][name] = {
            "installed": bool(comp.get("installed")),
            "pin": str(comp.get("pin")),
            "running": running,
            # UNCHANGED: the instantaneous fact (expected-up and THIS probe missed).
            "degraded": expected and not running,
            # …and the DEBOUNCED verdict, which is what the panel renders on both the
            # card and the feed, so those two can never tell Debi opposite things.
            "health": verdict,
            "misses": misses,
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
        # The runner's health is keyed on PORT_UP, exactly as its `degraded` is: a live
        # port with no model yet is "loading", not dead. Same debounce as everything
        # else, so a model switch (port down for a moment) reads as reconnecting rather
        # than painting a permanent "health lost" line in the feed.
        r_verdict, r_misses = _health_track(
            "runner", _expected_path("runner").exists(), port_up)
        out["components"]["runner"] = {
            "installed": True,
            "pin": str(live_id or rc.get("model") or rc.get("adapter") or "auto"),
            "running": loaded,
            "loaded": loaded,
            "port_up": port_up,          # process holds the port but may still be loading
            # degraded = the process actually died (not merely mid-load): expected-up
            # AND the port is gone. A live port with no model yet = "loading", not degraded.
            "degraded": _expected_path("runner").exists() and not port_up,
            "health": r_verdict,
            "misses": r_misses,
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
    if name not in _LOG_NAMES:
        raise HTTPException(404, "unknown log")
    f = ROOT / "data" / "logs" / f"{name}.log"
    if not f.exists():
        return {"lines": []}
    return {"lines": f.read_text(errors="replace").splitlines()[-lines:]}


_LOG_NAMES = ("bridge", "hermes", "odysseus", "searxng", "runner", "guard",
              "voicestudio", "voicebox",
              # install-time log (voicebox's fragile dep graph writes here — must be
              # viewable in-panel, not just from a terminal; Fable QA fix 2026-08-07)
              "voicebox-install",
              # the resident TTS worker's stderr — the ONLY place the engine's own
              # traceback lands now that stdout is protocol-only
              "voice-worker",
              # music-engine install (multi-GB downloads + a cmake build) — same
              # rule as voicebox-install: an install log for a slow, fragile step
              # must be readable in-panel, not only from a terminal
              "music-install",
              # the two optional creative/training tabs (2026-08-20). Both are
              # multi-GB online-only installs, so their install logs follow the
              # voicebox-install rule and must be viewable in-panel too.
              "comfyui", "comfyui-install",
              "unsloth", "unsloth-install",
              # the aider lane: one line per PTY session (start/exit/teardown) plus the
              # online-only install log — same voicebox-install rule.
              "aider", "aider-install",
              # the OpenCode tab: its server log + the online-only binary install
              # (same voicebox-install rule — a download install must be readable
              # in-panel, not only from a terminal).
              "opencode", "opencode-install",
              # LOffice's boot beacon (bridge/office.py DIAG_LOG_NAME). The page phones
              # home at every step of its own boot; this is where that trace lands, and
              # it must be readable in-panel because the tab it describes may be showing
              # nothing at all.
              "loffice-boot")


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
        "voicestudio": [
            "OPTIONAL voice component — license AGPL-3.0-only (composed over HTTP, never modified)",
            "Shallow-clone vendor/voicestudio at the pinned tag (not a submodule)",
            "Create venv data/voicestudio-venv + install its deps: torch, transformers, "
            "whisperx, pyannote, demucs, sherpa-onnx, mlx — roughly 5-8GB, needs ~10GB free",
            "Provide ffmpeg with NO Homebrew: reuse yours if you have one, else install "
            "the imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and "
            "copy the binary to data/ffmpeg/",
            "Build its web UI with bun: reuse a bun already on your PATH, else download "
            "the pinned bun release (~35MB) into data/bun/ — never Homebrew, never sudo, "
            "nothing written outside this project folder (if that download fails the "
            "backend still boots and serves a stub page)",
            "Serve on 127.0.0.1:3900 when started (API + UI on one port, loopback only, no auth)",
            "Speech models (~2.4GB) download later, on first use",
        ],
        "voicebox": [
            "OPTIONAL voice component — license MIT (composed over HTTP, never modified)",
            "Shallow-clone vendor/voicebox at the pinned tag (not a submodule)",
            "Create venv data/voicebox-venv and mirror upstream's own pip recipe: "
            "requirements.txt, then chatterbox-tts + hume-tada --no-deps, then (Apple "
            "Silicon) the MLX extras + mlx-audio --no-deps, then Qwen3-TTS from git",
            "KNOWN-FRAGILE: five dependencies need --no-deps / git URLs / a custom "
            "package index — this install is ONLINE-ONLY and can fail on upstream pin "
            "conflicts (upstream last shipped 2026-04-26); failures print the log path",
            "Provide ffmpeg with NO Homebrew: reuse yours if you have one, else install "
            "the imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and "
            "copy the binary to data/ffmpeg/ (the start script puts it on its PATH)",
            "Build its web UI with bun and copy web/dist → frontend/: reuse a bun already "
            "on your PATH, else download the pinned bun release (~35MB) into data/bun/ — "
            "never Homebrew, never sudo, nothing written outside this project folder "
            "(if that download fails the JSON API and /mcp still work)",
            "Serve on 127.0.0.1:17493 when started — NO AUTHENTICATION: /speak, "
            "/transcribe and /mcp are open to anything reaching the port, loopback only",
        ],
        "comfyui": [
            "OPTIONAL image/video component — license GPL-3.0. Composed at ARM'S LENGTH "
            "ONLY: a separate process reached over HTTP, never modified, never lifted "
            "from (the same posture the harness takes with SearXNG's AGPL)",
            "Shallow-clone vendor/comfyui at the pinned tag (not a submodule)",
            "Create venv data/comfyui-venv + install its deps: torch, torchvision, "
            "torchaudio, transformers, safetensors and its SPA (which ships as a pip "
            "package — no npm/bun build) — roughly 4-6GB of wheels, ONLINE ONLY",
            "On Apple Silicon, install a PyTorch NIGHTLY build first because upstream's "
            "own README says to; falls back to stable PyPI torch if that index is "
            "unreachable. A nightly is a FLOATING build, not a pin we control",
            "Create data/comfyui/ as its base directory (models, output, input, user) so "
            "it never writes into vendor/",
            "Serve on 127.0.0.1:8188 when started (UI + API on one port, loopback only, "
            "no authentication)",
            "Its models load in ITS process, so their RAM is OUTSIDE the harness "
            "model-RAM ledger (memory.budget_gb) — the same known limit the voice "
            "components have",
            "Image/video models are NOT downloaded here; you add them later, on first use",
        ],
        "unsloth": [
            "OPTIONAL training/serving studio — Unsloth Studio is AGPL-3.0-only (the "
            "training library is Apache-2.0). Composed at ARM'S LENGTH ONLY: a separate "
            "process reached over HTTP, never modified",
            "Shallow-clone vendor/unsloth at the pinned tag (not a submodule)",
            "Create venv data/unsloth-venv and pip install -e vendor/unsloth[studio] — "
            "upstream's own declared server stack (fastapi, uvicorn, datasets, pandas, "
            "matplotlib, pymupdf, fastmcp …), a few hundred MB. The heavy training "
            "extras are NOT installed: the tab only needs the Studio server",
            "Build its React SPA with bun: reuse a bun already on your PATH, else "
            "download the pinned bun release (~35MB) into data/bun/ — never Homebrew, "
            "never sudo, nothing written outside this project folder",
            "UNLIKE the voice components a missing SPA build is FATAL — Unsloth refuses "
            "a web-UI launch without it. The install still finishes, but Start says so "
            "and points at data/logs/unsloth-install.log",
            "We deliberately do NOT run upstream's install.sh (it builds its own install "
            "root, writes shell shims and downloads a forked, floating-tag llama.cpp plus "
            "its own Node) and never run 'unsloth start' — that is its agent-wiring path "
            "and it would relocate HERMES_HOME; your ~/.hermes is never touched",
            "Serve on 127.0.0.1:8899 when started. Studio has its OWN bearer login, "
            "handled inside its own UI; on a loopback launch its page auto-fills the "
            "bootstrap credential",
            "It can download its own llama.cpp and models into its own dirs — contained, "
            "but those weights are invisible to the harness model-RAM ledger",
        ],
        "opencode": [
            "OPTIONAL second coding lane — license MIT. Not a source checkout and not a "
            "venv: upstream ships a PREBUILT native binary per platform on npm, so this "
            "downloads two npm tarballs (~46MB), verifies npm's own sha1, and extracts "
            "ONE ~144MB executable to data/opencode/bin/",
            "⚠ IT REQUIRES A TOOL-CALLING MODEL. Every edit it makes is a native tool "
            "call and there is NO text fallback — on a model without tool support it "
            "will look BROKEN rather than merely worse. Use a model showing the green "
            "'tools' pill in Models (aider is the lane that works without one)",
            "ONLINE-ONLY, and it stays online-ish: it installs its provider package "
            "(@ai-sdk/openai-compatible) on first use with npm's own resolver. That "
            "download is UNPINNED — it is the one floating dependency in this lane",
            "Everything it writes is redirected into data/opencode/xdg (config, cache, "
            "session db) by the XDG variables the start script sets — your ~/.config and "
            "~/.cache are never touched",
            "On Start it is pointed at the harness runner (127.0.0.1:6767) with every "
            "model in your registry listed, exactly like Hermes and Odysseus. The "
            "provider it writes is called `llama.cpp` and shows up in OpenCode's own "
            "Settings → Providers as CONNECTED (tag: config); its model picker should "
            "then list your models by their registry names. If it instead offers "
            "OpenCode's own Zen models (Big Pickle, gpt-5…), the config did not reach "
            "it — the Start log says so in one line, see the opencode log",
            "The provider is written TWICE on purpose — into its private global config "
            "(data/opencode/xdg/config/opencode/opencode.json) and into "
            "data/opencode-workspace/opencode.json — so one of the two landing is "
            "enough. Only the global copy carries the default model, because OpenCode "
            "writes your own model choice back to that same file",
            "Its auto-updater is disabled two ways (config key + environment flag) "
            "because the version is pinned in harness.yaml — never use its in-app upgrade",
            "Serve on 127.0.0.1:4096 when started (its own web UI + API on one port, "
            "loopback only, NO authentication)",
            "It is started in data/opencode-workspace, which is the ONLY boundary on "
            "what it edits — the Hermes path-guard does not reach this lane",
            "data/opencode-workspace is git-initialised with one empty commit: that is "
            "the only thing that makes a directory a PROJECT to OpenCode rather than "
            "part of its shared 'global' one, and the tab then opens straight onto a "
            "new session there instead of its 'Add project' home screen. If you ever "
            "do land on that screen: Add project -> data/opencode-workspace, once",
            "Its Settings → Servers list is the TAB's own browser storage, not ours. "
            "Removing 127.0.0.1:4096 from it cannot strand you: the served page always "
            "re-adds the server it was loaded from, so ⌘R brings it back. To re-add it "
            "by hand, Add server wants only the address http://127.0.0.1:4096 — leave "
            "name, username and password empty (this server has no password)",
        ],
    }
    if name not in plans:
        raise HTTPException(404, "unknown component")
    return {"component": name, "plan": plans[name],
            "note": "Nothing runs until you click Approve."}


@app.post("/api/components/{name}/install")
def install(name: str) -> JSONResponse:
    """Execute the install after the panel's approve step."""
    if name not in ("hermes", "odysseus", "searxng", "voicestudio", "voicebox",
                    "comfyui", "unsloth", "opencode"):
        raise HTTPException(404, "unknown component")
    # opencode is a BINARY download, not a clone+venv, so it has its own installer —
    # the same shape searxng's exception already has.
    script = {"searxng": "install_searxng.sh",
              "opencode": "install_opencode.sh"}.get(name, "install_component.sh")
    args = () if name in ("searxng", "opencode") else (name, "--yes")
    # voicestudio pulls ~5-8GB of wheels (torch/whisperx/mlx) + a bun SPA build, which
    # can outrun the default 30-minute budget on a slow link — give it 2h and surface a
    # timeout as a readable message instead of an unhandled 500. voicebox is the same
    # class (torch + kokoro + git-sourced engines, several GB) plus a bun build.
    # comfyui (torch + diffusion stack) and unsloth (its studio extra + a bun SPA build)
    # are the same class again.
    timeout = 7200 if name in ("voicestudio", "voicebox", "comfyui", "unsloth") else 1800
    try:
        r = _script(script, *args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"ok": False, "log": f"install timed out after {timeout // 60} min — "
                                 f"run it in a terminal: ./scripts/{script} "
                                 + " ".join(args)},
            status_code=500)
    ok = r.returncode == 0
    return JSONResponse(
        {"ok": ok, "log": (r.stdout + r.stderr)[-4000:]},
        status_code=200 if ok else 500)


_NOTES = {
    "runner": "launches the llama.cpp/MLX runner + loads the model (~60–90s)",
    # OPTIONAL, AGPL-3.0-only. Backend + built SPA on one loopback port, no auth.
    "voicestudio": "voice studio on :3900 — first boot loads speech models (can take minutes)",
    # OPTIONAL, MIT. JSON API + /mcp (+ the SPA when built) on one loopback port.
    # NO AUTH of any kind, and upstream has been stale since 2026-04-26.
    "voicebox": "voicebox on :17493 — no auth, loopback only; first boot loads models (minutes)",
    # OPTIONAL, GPL-3.0. UI + API on one loopback port, no auth. Torch import is slow.
    "comfyui": "comfyui on :8188 — loopback only, no auth; first boot imports torch (slow)",
    # OPTIONAL, AGPL-3.0-only (Studio). Its own bearer login lives in its own UI.
    "unsloth": "unsloth studio on :8899 — loopback only; it has its own login screen",
    # OPTIONAL, MIT. Its own UI + API on one loopback port, no auth. The tools warning
    # is appended per-request by start_plan (it depends on the LIVE model).
    "opencode": ("opencode on :4096 — loopback only, no auth. The tab opens its "
                 "new-session composer for data/opencode-workspace (the bridge's "
                 "/opencode redirect), not its own 'Add project' home screen. "
                 "Start seeds the `llama.cpp` provider -> the harness runner, so its "
                 "model picker lists YOUR models (if it offers Big Pickle instead, the "
                 "config did not reach it — the log says so). "
                 "Needs a TOOL-CALLING model — look for the green 'tools' pill."),
}


@app.get("/api/components/{name}/start-plan")
async def start_plan(name: str) -> dict:
    """The dependency-ordered list that a Start of `name` will bring up."""
    c = cfg()
    steps = []
    for n in _closure(name, c, []):
        note = _NOTES.get(n, "")
        # OpenCode is the one component whose usefulness depends on the LOADED
        # MODEL, so the plan says so before anything starts. A warning, never a
        # refusal (see opencode_tools_warning).
        if n == "opencode":
            warn = _opencode_live_warning(c)
            if warn:
                note = (note + " · " + warn) if note else warn
        steps.append({"name": n, "running": await _running(n, c), "note": note})
    return {"target": name, "steps": steps,
            "to_start": [s["name"] for s in steps if not s["running"]]}


def _opencode_live_warning(c: dict) -> str:
    """The tools warning for whatever the runner is CURRENTLY serving. Never raises
    (a plan must render even with no registry and no runner)."""
    try:
        port = (c.get("runner", {}) or {}).get("port")
        live = _live_model_id(int(port)) if port else None
        entry = next((m for m in _registry_models() if m.get("id") == live), None) \
            if live else None
        return opencode_tools_warning(entry)
    except Exception:                                            # noqa: BLE001
        return ""


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
        refused = _kill_port_listener(int(port), force=True, component="runner")
        (ROOT / "data" / "runner.pid").unlink(missing_ok=True)
        if refused:
            return JSONResponse({"ok": False, "log": "; ".join(refused)}, status_code=409)
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
            refused = _kill_port_listener(int(port), component=name)
            notes.append("; ".join(refused) if refused
                         else f"port :{port} still held — killed listener")
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
        _attachment_forget(sid)  # …and any stored image bytes for that session
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
                # Image sidecar: same story for the USER turns — Odysseus keeps
                # only the "[image attached]" marker, so hand the panel back an
                # {id, name} handle it can render as the original thumbnail.
                attach_images(out["history"], _attachment_rows(sid))
        except Exception:
            pass
        return JSONResponse(out)
    except Exception:
        return JSONResponse({"history": []})


# ── Per-message actions (LM-Studio parity) ───────────────────────────────────
# Thin proxies over Odysseus's per-message ops. Both Mission-Control chat lanes
# (direct Chat + Agent) share the Odysseus session store, so delete/edit/fork all
# work for either. The Hermes lane keeps its own store and gets Copy only.
#   • delete → POST /api/session/{sid}/delete-messages {msg_ids}
#   • edit   → POST /api/session/{sid}/edit-message   {msg_id, content}
#              (content-only: upstream stamps metadata.edited and does NOT
#               truncate the tail — matches LM Studio's edit semantics)
#   • fork   → POST /api/session/{sid}/fork {keep_count}
# GOTCHA (recon): fork's keep_count indexes the UNFILTERED in-memory history —
# which is exactly what GET /api/history returns (the unpaged handler), so an
# index computed from that same payload is correct.

def fork_keep_count(history, msg_id):
    """Pure: keep_count that forks a session UP TO AND INCLUDING `msg_id`.

    Returns index+1 of the message whose metadata._db_id matches, or None when
    the id isn't in this history (stale panel state → the caller 404s rather
    than forking the wrong slice). Ids are compared as strings: the db id is an
    int in some rows and a str in others, and it round-trips through JSON/DOM
    datasets as text.
    """
    if msg_id is None or msg_id == "":
        return None
    target = str(msg_id)
    for i, m in enumerate(history or []):
        meta = m.get("metadata") if isinstance(m, dict) else None
        if not isinstance(meta, dict):
            continue
        did = meta.get("_db_id")
        if did is not None and str(did) == target:
            return i + 1
    return None


@app.post("/api/ody/session/{sid}/msg-delete")
async def ody_msg_delete(sid: str, req: Request) -> JSONResponse:
    """Delete ONE message (by its Odysseus db id) from a session."""
    try:
        msg_id = (await req.json()).get("msg_id")
    except Exception:
        msg_id = None
    if msg_id in (None, ""):
        return JSONResponse({"ok": False, "error": "msg_id required"}, status_code=400)
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/delete-messages",
                           json={"msg_ids": [msg_id]})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        j = r.json() if r.content else {}
        return JSONResponse({"ok": True, "deleted": j.get("deleted", 0)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


@app.post("/api/ody/session/{sid}/msg-edit")
async def ody_msg_edit(sid: str, req: Request) -> JSONResponse:
    """Edit ONE message's text. Content-only — the model is NOT re-run."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    msg_id, content = body.get("msg_id"), body.get("content")
    if msg_id in (None, "") or content is None:
        return JSONResponse({"ok": False, "error": "msg_id and content required"},
                            status_code=400)
    try:
        r = await _ody_req("POST", f"/api/session/{sid}/edit-message",
                           json={"msg_id": msg_id, "content": content})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


@app.post("/api/ody/session/{sid}/fork-from")
async def ody_fork_from(sid: str, req: Request) -> JSONResponse:
    """Fork a new session containing everything up to (and incl.) `msg_id`."""
    try:
        msg_id = (await req.json()).get("msg_id")
    except Exception:
        msg_id = None
    if msg_id in (None, ""):
        return JSONResponse({"ok": False, "error": "msg_id required"}, status_code=400)
    try:
        hr = await _ody_req("GET", f"/api/history/{sid}")
        if hr.status_code != 200:
            return JSONResponse({"ok": False, "error": hr.text[:500]}, status_code=502)
        keep = fork_keep_count(hr.json().get("history") or [], msg_id)
        if keep is None:
            return JSONResponse({"ok": False, "error": "message not found in session"},
                                status_code=404)
        r = await _ody_req("POST", f"/api/session/{sid}/fork", json={"keep_count": keep})
        if r.status_code != 200:
            return JSONResponse({"ok": False, "error": r.text[:500]}, status_code=502)
        j = r.json() if r.content else {}
        return JSONResponse({"ok": True, "id": j.get("id"), "name": j.get("name"),
                             "kept": j.get("kept", keep)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Odysseus unreachable: {e}"},
                            status_code=502)


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


# ── Direct-lane image sidecar (2026-08-07) ───────────────────────────────────
# Same problem/shape as the thinking sidecar above: the direct lane persists
# {role, content} strings to Odysseus, so an attached image survives a reopen
# only as the "\n[image attached]" marker line. This sidecar keeps the BYTES
# locally (data/attachments.db) keyed by (session id, hash of the user text) and
# re-attaches an {id, name} handle on history read, so the panel can rehydrate
# the same thumbnail it showed at send time.
#
# Discipline is identical: one lock, every read/write wrapped — this must NEVER
# raise into the chat path. Storing bytes rather than the dataURL keeps the file
# ~33% smaller and lets GET /api/attachment/{id} serve it with its real mime.
_attach_lock = threading.Lock()
ATTACH_MAX_ROWS = 300      # global cap (blobs are heavy — far tighter than thinking's 5000)
ATTACH_MARKER = "\n[image attached]"   # appended by chat_direct when persisting the user turn


def user_key(text: str) -> str:
    """Stable join key for a USER turn: sha1 of its first 2048 characters.

    Parallel to answer_hash, with one extra normalization: chat_direct persists
    the user message with ATTACH_MARKER appended, so the string we store at send
    time and the string history hands back differ by exactly that suffix. Strip
    it on both sides and the two always agree. Pure — unit-tested.
    """
    import hashlib
    t = text or ""
    if t.endswith(ATTACH_MARKER):
        t = t[:-len(ATTACH_MARKER)]
    return hashlib.sha1(t[:2048].encode("utf-8", "replace")).hexdigest()


def parse_data_url(s, max_chars: int):
    """PURE: 'data:<mime>;base64,<payload>' → (mime, bytes), else (None, None).

    Total: any malformed / oversize / non-image input yields (None, None) so the
    caller simply skips storing. Never raises.
    """
    try:
        if not isinstance(s, str) or not s.startswith("data:"):
            return (None, None)
        if max_chars and len(s) > max_chars:
            return (None, None)
        head, _, payload = s.partition(",")
        if not payload:
            return (None, None)
        meta = head[5:]                      # drop 'data:'
        if not meta.endswith(";base64"):
            return (None, None)
        mime = meta[:-len(";base64")].strip().lower()
        if not mime.startswith("image/"):
            return (None, None)
        import base64
        raw = base64.b64decode(payload, validate=True)
        if not raw:
            return (None, None)
        return (mime, raw)
    except Exception:
        return (None, None)


def _attach_conn():
    import sqlite3
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "attachments.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS attachments("
              "id INTEGER PRIMARY KEY, ts REAL, sid TEXT, key TEXT, "
              "name TEXT, mime TEXT, bytes BLOB)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_attachments_sid_key ON attachments(sid, key)")
    return c


def log_attachment(sid: str, key: str, name: str, mime: str, blob) -> None:
    """Store one turn's image. Best-effort; never raises."""
    try:
        if not (sid and key and mime and blob):
            return
        import time as _t
        with _attach_lock:
            c = _attach_conn()
            c.execute("INSERT INTO attachments(ts, sid, key, name, mime, bytes) "
                      "VALUES(?,?,?,?,?,?)",
                      (_t.time(), sid, key, (name or "image"), mime, blob))
            # Global retention cap: drop the oldest rows beyond ATTACH_MAX_ROWS.
            c.execute("DELETE FROM attachments WHERE id NOT IN "
                      "(SELECT id FROM attachments ORDER BY ts DESC, id DESC LIMIT ?)",
                      (ATTACH_MAX_ROWS,))
            c.commit(); c.close()
    except Exception:
        pass


def _attachment_rows(sid: str) -> list:
    """All (key, id, name) rows for a session, oldest first. Never raises."""
    try:
        if not sid:
            return []
        with _attach_lock:
            c = _attach_conn()
            rows = c.execute("SELECT key, id, name FROM attachments WHERE sid=? "
                             "ORDER BY ts ASC, id ASC", (sid,)).fetchall()
            c.close()
        return [(r[0], r[1], r[2]) for r in rows]
    except Exception:
        return []


def _attachment_get(aid: int):
    """(name, mime, bytes) for one row, or None. Never raises."""
    try:
        with _attach_lock:
            c = _attach_conn()
            row = c.execute("SELECT name, mime, bytes FROM attachments WHERE id=?",
                            (int(aid),)).fetchone()
            c.close()
        return (row[0], row[1], row[2]) if row else None
    except Exception:
        return None


def _attachment_delete(aid: int) -> bool:
    """Remove one stored image ('remove from the app'). NEVER touches any source
    file on disk — this store is the only copy the harness owns. Never raises."""
    try:
        with _attach_lock:
            c = _attach_conn()
            cur = c.execute("DELETE FROM attachments WHERE id=?", (int(aid),))
            n = cur.rowcount
            c.commit(); c.close()
        return bool(n)
    except Exception:
        return False


def _attachment_forget(sid: str) -> None:
    """Drop a deleted session's stored images. Best-effort; never raises."""
    try:
        if not sid:
            return
        with _attach_lock:
            c = _attach_conn()
            c.execute("DELETE FROM attachments WHERE sid=?", (sid,))
            c.commit(); c.close()
    except Exception:
        pass


def attach_images(history_rows, att_rows):
    """PURE: attach stored image handles to user messages, consuming IN ORDER.

    Mirrors attach_thinking exactly: rows are bucketed by key and popped from the
    front, so a session that sent "test" twice with two different images gets
    them back 1:1 in the order they were sent. Malformed rows/messages are
    skipped — this must never raise.
    """
    try:
        buckets: dict = {}
        for row in (att_rows or []):
            try:
                k, aid, nm = row[0], row[1], row[2]
            except Exception:
                continue
            if not k or aid is None:
                continue
            buckets.setdefault(str(k), []).append((aid, nm))
        if not buckets:
            return history_rows
        for m in (history_rows or []):
            try:
                if not isinstance(m, dict) or m.get("role") != "user":
                    continue
                if m.get("attachment"):
                    continue          # never overwrite an already-populated handle
                content = m.get("content")
                if not isinstance(content, str) or not content:
                    continue
                b = buckets.get(user_key(content))
                if b:
                    aid, nm = b.pop(0)
                    m["attachment"] = {"id": aid, "name": nm or "image"}
            except Exception:
                continue
    except Exception:
        pass
    return history_rows


@app.get("/api/attachment/{aid}")
async def api_attachment(aid: int):
    """Serve one stored image's bytes with its own mime. 404 when it's gone
    (pruned / deleted) so a stale thumbnail simply fails to load."""
    from fastapi.responses import Response
    row = await asyncio.to_thread(_attachment_get, aid)
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    name, mime, blob = row
    return Response(content=blob, media_type=mime or "application/octet-stream",
                    headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/attachment/{aid}/delete")
async def api_attachment_delete(aid: int) -> JSONResponse:
    """'Remove this image from the app' — drops the sidecar row only. The user's
    original file on disk is never read again and never touched."""
    ok = await asyncio.to_thread(_attachment_delete, aid)
    return JSONResponse({"ok": ok})


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


def _set_yaml_scalar(block: str, key: str, value: str) -> None:
    """Rewrite <block>.<key> in harness.yaml IN PLACE (same line-scan idiom as
    _set_yaml_model, so every comment / ordering in the file survives — a full yaml
    round-trip would strip them, which we only ever accept for ~/.hermes/config.yaml).
    An empty value writes a bare `key:` (= null = off). If the block or the key is
    missing (e.g. an older snapshot manifest that ship.sh's merge hasn't touched yet)
    they are appended rather than silently dropped."""
    import re
    p = ROOT / "harness.yaml"
    text = p.read_text()
    lines = text.split("\n")
    inside, block_at, last_in_block = False, -1, -1
    for i, ln in enumerate(lines):
        if re.match(rf'^{re.escape(block)}:\s*$', ln):
            inside, block_at = True, i
            continue
        if inside and re.match(r'^\S', ln):
            inside = False
        if inside:
            if ln.strip():
                last_in_block = i
            if re.match(rf'^  {re.escape(key)}:', ln):
                suffix = ""
                m = re.search(r'\s(#.*)$', ln)      # keep any trailing comment
                if m:
                    suffix = "  " + m.group(1)
                lines[i] = (f"  {key}: {value}" if value else f"  {key}:") + suffix
                p.write_text("\n".join(lines))
                return
    new_line = f"  {key}: {value}" if value else f"  {key}:"
    if block_at < 0:
        lines.append(f"{block}:")
        lines.append(new_line)
    else:
        lines.insert((last_in_block if last_in_block >= 0 else block_at) + 1, new_line)
    p.write_text("\n".join(lines))


# ── hidden models ───────────────────────────────────────────────────────────────
# Debi's ask: the HF cache and LM Studio hand us models that will never be used here,
# and the list is the worse for them. HIDE is deliberately NOT delete: the files
# belong to another app, so the only honest operation is to stop listing them.
#
# Only IMPORTED / CACHED sources may be hidden. An app-owned model (source
# download/local) already has a real Delete, and offering both would give the same
# row two different ways to disappear — one of which does not free any disk.
HIDEABLE_SOURCES = ("lmstudio-import", "jan-import", "audio-hf-cache")


def _is_hidden(m: object) -> bool:
    return bool(isinstance(m, dict) and m.get("hidden"))


def _hideable(m: object) -> bool:
    """PURE. True when this entry may be hidden from the lists."""
    return bool(isinstance(m, dict)
                and str(m.get("source") or "") in HIDEABLE_SOURCES)


def _hidden_view(m: dict) -> dict:
    """The minimum a hidden row needs: enough to name it and to unhide it."""
    return {"id": m.get("id"), "name": m.get("name") or m.get("id"),
            "source": m.get("source"),
            "kind": ("audio" if (_voice is not None and _voice.is_audio_entry(m))
                     else "chat")}


@app.post("/api/models/hide")
async def api_models_hide(req: Request) -> JSONResponse:
    """{id, hidden} → hide/unhide one imported model from every list.

    Writes `hidden:true` onto the registry entry through the SAME atomic
    _registry_update the voice pins use, and seed_registry.merge carries it across a
    RESCAN (a rescan reads FILES and hiding is a user decision that lives nowhere on
    disk — exactly the bug the voice-pin carry-forward already fixed once)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    want = bool(body.get("hidden", True))
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    # Unhiding is always allowed — otherwise a source change could strand a row.
    if want and not _hideable(entry):
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is app-owned — delete it instead of "
                                   f"hiding it (hiding is for read-only imports)"},
            status_code=400)
    # A model that is IN USE must not be hidden: it would vanish from every picker
    # while still being the thing the harness runs, which is the one state a user
    # cannot reason about. Refuse and say which role holds it.
    if want:
        c = cfg()
        v = _voice_cfg()
        in_use = {"the chat runner": (c.get("runner", {}) or {}).get("model"),
                  "the aux runner": (c.get("aux", {}) or {}).get("model"),
                  "the default TTS": v["tts_model"], "the default STT": v["stt_model"]}
        for role, held in in_use.items():
            if held and held == mid:
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is {role} right now — clear it "
                                           f"there first, then hide it"},
                    status_code=400)
    _registry_update(mid, {"hidden": True if want else None})
    print(f"[models] {'hid' if want else 'unhid'} {mid}", flush=True)
    return JSONResponse({"ok": True, "id": mid, "hidden": want})


def _split_audio(models: list) -> tuple:
    """(chat, audio) partition of a registry list. Degrades to 'everything is a chat
    model' when bridge/voice.py is unavailable — never crashes the Models pane."""
    if _voice is not None:
        return _voice.split_audio(models)
    return list(models or []), []


def _voice_cfg() -> dict:
    """The harness.yaml `voice:` block, normalised. Empty string = capability off."""
    v = (cfg().get("voice") or {}) if isinstance(cfg().get("voice"), dict) else {}
    return {"tts_model": str(v.get("tts_model") or "").strip(),
            "stt_model": str(v.get("stt_model") or "").strip()}


def _reject_if_audio(mid: str) -> "JSONResponse | None":
    """Guard for the CHAT slots (runner switch / aux). Loading a TTS backbone into
    llama-server or mlx_lm.server fails in a confusing way — refuse it by name."""
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is not None and _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse(
            {"ok": False, "log": f"'{mid}' is a voice model — set it in Models → Audio, "
                                 f"not as a chat/aux model"}, status_code=400)
    return None


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


def _resident_voice_bytes() -> int:
    """RAM claimed by a RESIDENT voice model, approximated the same way chat models
    are (weight file size). Zero whenever no worker is alive.

    This closes the recorded "the ledger ignores voice models" item — and it only
    became true-able when the persistent worker landed. One-shot renders really are
    transient (the process dies with the request), so counting them would have made
    the budget lie; a worker that holds 3.6GB until it is unloaded is exactly the
    persistent slot the earlier verdict said to revisit for."""
    if _voice is None:
        return 0
    try:
        return int((_voice.worker_resident() or {}).get("size_bytes") or 0)
    except Exception:                                            # noqa: BLE001
        return 0


def _loaded_models_bytes(exclude_slot: str | None = None) -> int:
    """Approx RAM (by file size) used by models currently SERVED: main runner's
    active model (if its port is up) + aux model (if its port is up) + a resident
    voice worker. exclude_slot ('main'|'aux'|'voice') omits that slot — used to get
    'other-slot usage' for a switch of that slot (so its own current usage isn't
    double-counted against the candidate)."""
    c = cfg()
    # Chat models ONLY: an audio entry must never be able to claim ledger budget
    # (voice weights are transient by design — spec §Architecture 1), and if an
    # audio id ever ended up in runner.model/aux.model the lookup must miss, not
    # silently account for it.
    models, _ = _split_audio(_registry_models())
    total = 0
    rc = c.get("runner", {}) or {}
    if exclude_slot != "main" and rc.get("port") and _port_alive_sync(int(rc["port"])):
        total += _model_size(models, rc.get("model") or "")
    ax = c.get("aux", {}) or {}
    if exclude_slot != "aux" and ax.get("port") and _port_alive_sync(int(ax["port"])):
        total += _model_size(models, ax.get("model") or "")
    if exclude_slot != "voice":
        total += _resident_voice_bytes()
    return total


def _voice_spawn_guard(size_bytes: int) -> "str | None":
    """Ledger gate handed to voice.get_worker(). None = spawn allowed, else the
    refusal text. Same shape as the runner/aux switch gates, and deliberately owned
    HERE: voice.py must not learn to read harness.yaml."""
    other = _loaded_models_bytes(exclude_slot="voice")
    budget = _budget_bytes()
    if size_bytes and not _within_budget(int(size_bytes), other, budget):
        return (f"loading that voice model would exceed the model-RAM budget "
                f"({(int(size_bytes) + other) / 1024**3:.1f} > {budget / 1024**3:.0f} GB) "
                f"— eject a chat model first")
    return None


def _within_budget(candidate_bytes: int, other_slot_bytes: int, budget_bytes: int) -> bool:
    """Pure predicate (unit-testable): does loading `candidate` alongside the other
    slot's current usage stay within budget? True = OK to load."""
    return (candidate_bytes + other_slot_bytes) <= budget_bytes


def _model_caps(m: dict) -> list:
    """The `capabilities` list for one registry entry. PURE.

    `vision` is unchanged. `tools` joins it ONLY on an explicit True — a null
    verdict (unreadable template, a shape modeltools does not know) must never be
    reported as an absent capability, because the panel and the OpenCode gate both
    read the absence as "this model cannot do it"."""
    caps = []
    if m.get("vision") or m.get("mmproj"):
        caps.append("vision")
    if m.get("tools") is True:
        caps.append("tools")
    return caps


# ── the OpenCode start gate ──────────────────────────────────────────────────
# OpenCode has NO text-edit fallback: every mutation is a native tool call
# (docs/research/2026-08-21-opencode-omnigent-recon.md §1). On a model that cannot
# emit one it does not degrade, it looks broken. So starting it against such a model
# WARNS — loudly, by name — and never refuses: the verdict is a template heuristic,
# and a heuristic may not stand between the user and a program they asked to run.
OPENCODE_TOOLS_OK = ""
OPENCODE_TOOLS_UNKNOWN = (
    "⚠ the loaded model %s does not say whether it supports tool calling — "
    "OpenCode needs it (look for the green `tools` pill in Models)")
OPENCODE_TOOLS_BAD = (
    "⚠ the loaded model %s has NO tool-calling support — OpenCode requires it and "
    "will look broken, not merely worse. Load a model with the green `tools` pill.")
OPENCODE_TOOLS_NONE = (
    "⚠ no model is loaded — OpenCode needs a running runner with a tool-capable model")


def opencode_tools_warning(entry) -> str:
    """'' when the live model is tool-capable, else the sentence to show. PURE.

    `entry` is the live model's registry entry, or None when nothing is loaded."""
    if not isinstance(entry, dict):
        return OPENCODE_TOOLS_NONE
    name = str(entry.get("id") or entry.get("name") or "?")
    t = entry.get("tools")
    if t is True:
        return OPENCODE_TOOLS_OK
    if t is False:
        return OPENCODE_TOOLS_BAD % name
    return OPENCODE_TOOLS_UNKNOWN % name


# ── the OpenCode LANDING ─────────────────────────────────────────────────────
# THE COMPLAINT THIS ANSWERS: the tab opened OpenCode's home screen, which read
# "Nothing here yet — Create a session to get started" beside a Projects rail whose
# only entry was "Add project". Everything was running; being useful was gated on a
# setup step, which is indistinguishable from broken.
#
# There is nothing to seed. Read at pin 1.18.19: the Projects rail is CLIENT state,
# persisted in the webview's own localStorage under `opencode.global.dat:server`
# (packages/app/src/context/server.tsx:263-274, utils/persist.ts:491-494) — an
# internal, migrating format inside WebKit's storage that we have no business writing.
# The home session list is filtered by that same local rail
# (pages/home/home-sessions-controller.tsx:248-256), so pre-creating a session
# server-side would not clear the empty screen either.
#
# What DOES work is its own routing: `/:dir` is a DirectoryLayout whose `:dir` is the
# base64url of an absolute path (packages/app/src/app.tsx:633-636,
# pages/directory-layout.tsx:80-84, core/src/util/encode.ts:1-5), and `/:dir/session`
# with no session id opens a NEW-SESSION composer for that directory (app.tsx:94-101).
# So the tab is pointed straight at our workspace and the home screen never appears.
#
# ⚠️ THIS IS A DEEP LINK INTO A THIRD-PARTY SPA'S INTERNAL ROUTE SHAPE. The downside is
# bounded and was checked: an undecodable `:dir` toasts and navigates to "/"
# (directory-layout.tsx:97-111), i.e. the worst case is exactly today's behaviour. A
# contract test pins the route and the encoder so a pin bump trips instead of quietly
# regressing to the empty home.
#
# ⚠️ It is a BRIDGE route rather than a URL baked into app/main.swift because only the
# bridge knows both ROOT (repo vs snapshot) and the configured port, and because a
# route can be tested here. Cost: the tab needs the bridge up — which it always is,
# since the bridge is what the app launches and Mission Control is served from it.
def opencode_landing_url(root, port) -> str:
    """PURE. The URL the OpenCode tab should open. base64url, no padding, exactly as
    upstream's own `base64Encode` produces it (core/src/util/encode.ts)."""
    ws = os.path.join(str(root), "data", "opencode-workspace")
    b64 = base64.urlsafe_b64encode(ws.encode("utf-8")).decode("ascii").rstrip("=")
    try:
        p = int(port)
    except (TypeError, ValueError):
        p = 4096
    if not (0 < p < 65536):
        p = 4096
    return f"http://127.0.0.1:{p}/{b64}/session"


@app.get("/opencode")
def opencode_landing() -> Response:
    """307 → OpenCode's new-session composer for data/opencode-workspace."""
    port = ((cfg().get("components") or {}).get("opencode") or {}).get("port") or 4096
    return Response(status_code=307,
                    headers={"Location": opencode_landing_url(ROOT, port),
                             "Cache-Control": "no-store"})


@app.get("/api/models")
def api_models() -> JSONResponse:
    """Installed models (from OUR registry data/models.json — the only source since
    jan was retired), the active runner model + state, aux state, and the
    model-RAM ledger (approx by file size).

    AUDIO models (kind:"audio") are partitioned OUT of `installed` and returned under
    `audio` instead. This is load-bearing: `installed` feeds the runner switch, the
    aux picker and the chat model popover, and a TTS backbone in any of those would
    wedge the runner. The partition lives in ONE place (bridge/voice.split_audio)."""
    import json as _json
    installed, audio, hidden, err = [], [], [], None
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
        models, _audio_models = _split_audio(models)
        # HIDDEN: a read-only import the user does not want in their lists (Debi's
        # ask — the HF cache and LM Studio both hand us models we will never use).
        # They are filtered out of `installed` and `audio` at the BRIDGE, not in the
        # panel, so a hidden model cannot leak into the chat popover, the runner
        # switch, or the aux picker through a renderer that forgot to filter.
        hidden = [_hidden_view(m) for m in (models + _audio_models) if _is_hidden(m)]
        models = [m for m in models if not _is_hidden(m)]
        _audio_models = [m for m in _audio_models if not _is_hidden(m)]
        if _voice is not None:
            audio = [_voice.audio_entry_view(m) for m in _audio_models]
        for m in models:
            installed.append({
                "id": m.get("id"), "name": m.get("name") or m.get("id"),
                "size_bytes": m.get("size_bytes"),
                "engine": ("mlx" if m.get("format") == "mlx" else "llamacpp"),
                "embedding": False,
                "capabilities": _model_caps(m),
                # TOOL-CALLING (the OpenCode slice): True / False / None, derived
                # from the model's own chat template by bridge/modeltools.py.
                # `None` = we could not tell, and the panel draws NOTHING for it —
                # a missing pill must never read as "this model cannot".
                "tools": (m.get("tools") if isinstance(m.get("tools"), bool) else None),
                "format": m.get("format", "gguf"),
                "ctx": m.get("ctx"), "source": m.get("source"), "path": m.get("path"),
                # Per-model sampling: the READ side of /api/models/settings lives
                # here (one key on a payload the panel already polls) rather than in
                # a second route. `sampling` is the rendered view (engine-filtered
                # fields + harness defaults + overrides); `settings` is the raw pin.
                "settings": (m.get("settings") if isinstance(m.get("settings"), dict)
                             else None),
                "sampling": sampling_view(m),
                # Same pattern for the LOAD group (v2): raw pin + rendered view.
                "load": (m.get("load") if isinstance(m.get("load"), dict) else None),
                "loadview": load_view(m),
                # v2.1: the shared Apply & reload row — sampling floors + load, in
                # one claim, so an MLX model (no Load fields) still gets the chip.
                "launch": launch_view(m, _LOAD_AT_LAUNCH.get(m.get("id")))})
    except Exception as e:
        err = str(e)[:200]
        hidden = []
    port = rc.get("port")
    # Authoritative "live" = what the runner is ACTUALLY serving (ISSUE C), not just
    # "runner.model is set + port answers". runner_up is now gated on a real load, so
    # the Models pane and MC agree; live_id names the loaded model for the "live" pill.
    live_id = _live_model_id(int(port)) if port else None
    ax = c.get("aux", {}) or {}
    aux = {"model": ax.get("model") or "", "port": ax.get("port"),
           "up": _port_alive_sync(int(ax["port"])) if ax.get("port") else False}
    ledger = {"used_bytes": _loaded_models_bytes(), "budget_bytes": _budget_bytes()}
    vcfg = _voice_cfg()
    return JSONResponse({
        "installed": installed, "active": rc.get("model"),
        "runner_up": bool(live_id), "live_id": live_id,
        "aux": aux, "adapter": adapter, "ledger": ledger, "error": err,
        # Phase A (Models → Audio tab) reads these; the chat lists above never see them.
        "audio": audio, "voice": vcfg,
        # The models the user hid — a light view, only ever used to draw the
        # "N hidden — show" affordance and to unhide them again.
        "hidden": hidden})


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
        # The runner is now running with whatever `load` was saved at this moment —
        # record it so the panel can say "not applied yet" only when it is TRUE.
        _record_load_launch(new_id)
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
    _bad = _reject_if_audio(new_id)
    if _bad is not None:
        return _bad
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
        _kill_port_listener(int(port), force=True, component="runner")
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
    # If it was a VOICE default, clear that slot too — leaving harness.yaml pointing at
    # deleted weights would only fail later, at speak time, far from this click.
    vc = _voice_cfg()
    was_voice = [k for k in ("tts_model", "stt_model") if vc.get(k) == mid]
    # …and if it is RESIDENT in the persistent worker, kill that first: the process
    # holds the weights open, and on a re-download the same path would then serve a
    # deleted checkpoint from memory.
    if _voice is not None:
        _voice.worker_stop_if_model(mid, "model deleted")
    for k in was_voice:
        _set_yaml_scalar("voice", k, "")

    if _os.path.isdir(target):
        _shutil.rmtree(target, ignore_errors=True)
    _registry_drop(mid)
    print(f"[delete] removed {mid!r} (dir {target}, was_live={was_live}, "
          f"was_aux={was_aux}, was_voice={was_voice or 'no'})", flush=True)
    return JSONResponse({"ok": True, "id": mid, "was_live": was_live,
                         "was_aux": was_aux, "was_voice": was_voice})


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
    _kill_port_listener(port, force=True, component="runner")
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
    _bad = _reject_if_audio(new_id)
    if _bad is not None:
        return _bad
    _set_yaml_model("aux", new_id)
    return JSONResponse({"ok": True, "model": new_id})


def _aux_kill(port: int) -> None:
    for pat in (f'jan serve.*port[= ]{port}', f'llama-server.*--port {port}',
                f'mlx_lm.server.*--port {port}', f'mlx_vlm.server.*--port {port}'):
        subprocess.run(f'pkill -f "{pat}"', shell=True, check=False)
    _kill_port_listener(port, force=True, component="aux")


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
# No base_url: the starter-voice fetch talks to datasets-server.huggingface.co AND to
# whatever signed CDN host it hands back, so this one takes absolute URLs only.
_HF_ANY = httpx.AsyncClient(timeout=httpx.Timeout(20, read=60), follow_redirects=True)


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


# ── Audio HF search (T2) ──────────────────────────────────────────────────────
# WHY: the Audio tab shipped with five curated starters and Debi asked the obvious
# question — "why are there only these models". This is the discovery half. It is a
# SEPARATE surface from /api/models/hf because voice discovery is nothing like chat
# discovery: the useful axis is pipeline_tag + framework, not a quant filename, and
# the RESULT of a search must be probed before it can be trusted (see below).
#
# THREE web-verified facts drive the shape of this code (2026-08-08 research):
#   1. `?library=` on the models API is SILENTLY IGNORED. Never send it; `?filter=`
#      is the parameter that actually narrows.
#   2. TTS discovery must be a UNION of `filter=mlx-audio` and `filter=mlx` — the
#      mlx-audio tag alone MISSES Kokoro, the best quality-per-MB model we offer.
#   3. TAGS LIE. `openai/whisper-medium` carries every whisper token and is a
#      TRANSFORMERS checkpoint that mlx_whisper cannot load (it died with
#      "ModelDimensions.__init__() unexpected keyword '_name_or_path'" on Debi's
#      machine). Only config.json settles it — hence the probe endpoint.
AUDIO_SEARCH_KINDS = ("tts", "tts-gguf", "stt")

# ⚠️ PENDING FABLE QA: the kind vocabulary is THREE, not the brief's two. The GGUF
# TTS lane is a different query shape (filter=gguf + a text term, no pipeline_tag —
# GGUF repos are not pipeline-tagged) and mixing its hits into the MLX list would
# make one result list whose rows mean different things. A third chip is cheaper
# than a heterogeneous list.
AUDIO_SEARCH_QUERIES = {
    "tts": ({"filter": "mlx-audio", "pipeline_tag": "text-to-speech"},
            {"filter": "mlx", "pipeline_tag": "text-to-speech"}),
    "stt": ({"filter": "mlx", "pipeline_tag": "automatic-speech-recognition"},),
    "tts-gguf": ({"filter": "gguf"},),
}
# The GGUF lane has no pipeline tag to lean on, so an empty box still needs a term.
AUDIO_GGUF_DEFAULT_TERM = "tts"

# Licences we will NOT offer a Get for. Non-commercial covers the whole cc-by-nc
# family (Spark-TTS = cc-by-nc-sa, Voxtral-TTS = cc-by-nc with 20 tempting named
# voices). The row is still SHOWN — hiding a model would be a worse lie than
# showing it with the reason its button is off.
_NC_PREFIXES = ("cc-by-nc", "cc-nc")
_NC_SUBSTRINGS = ("noncommercial", "non-commercial")
_UNKNOWN_LICENSES = ("", "other", "unknown", "none")
# OpenRAIL is NOT non-commercial — it permits commercial use with behavioural
# use-restrictions. Blocking it would cost real models for no legal reason on a
# personal machine, so it gets an honest amber badge instead (Fable fix 2026-08-13).
_RESTRICTED_PREFIXES = ("creativeml-openrail", "openrail", "bigscience-openrail")

LICENSE_NC_REASON = "non-commercial licence"

# ── known-mistagged repos ─────────────────────────────────────────────────────
# Some upstreams tag the CODE licence on a repo whose WEIGHTS carry a different
# one. Our licence gate reads the tag, so a mistag defeats it silently. This table
# is the honest correction, consulted BEFORE the tag-derived badge at BOTH call
# sites (the search rows and the single-repo probe).
#
# OmniVoice: k2-fsa's own README says verbatim — "Our code is released under the
# Apache 2.0 License. The pre-trained model is licensed under the CC-BY-NC due to
# constraints from its training data (e.g. Emilia)."
#   https://huggingface.co/k2-fsa/OmniVoice   (see docs/research/2026-08-14-omnivoice-provenance.md)
# The k2 repo itself carries NO licence tag; every mlx-community/OmniVoice* repo
# tags itself apache-2.0 — the code licence, not the weights licence. Every one of
# them declares base_model k2-fsa/OmniVoice with the identical 612,577,280 params,
# i.e. a format conversion, so the weights term follows the conversion.
#
# ⚠️ PENDING FABLE QA: the badge is AMBER and **Get stays ENABLED**, unlike the
# unambiguous cc-by-nc-TAGGED rows (Spark-TTS, Voxtral-TTS) which stay disabled.
# Rationale: this is Debi's own machine and personal use is unaffected by CC-BY-NC;
# the honest thing is to SAY the weights term, not to hide the model behind a
# button we turn off. Same verdict shape as the recorded unknown-licence and
# OpenRAIL calls — honesty over gatekeeping. Flipping this to "nc" would disable
# Get on a model the harness already ships as its recommended TTS.
OMNIVOICE_LICENSE_REASON = ("weights CC-BY-NC per upstream README; code Apache-2.0")

# MiniMax-Music3: the SECOND confirmed instance of the same defect class, on a new
# model family (docs/research/2026-08-20-music-video-gen.md § Corrections #1) — i.e.
# this table is structural, not a one-off patch.
# `Abiray/MiniMax-Music3-GGUF` declares `license: apache-2.0` and its README claims it
# "Inherits the Apache-2.0 License from the original release" — FALSE. Upstream
# `MiniMaxAI/MiniMax-Music3` ships a custom "MiniMax-Music3 COMMUNITY LICENSE" with
# attribution duties on commercial surfaces, a $20M-revenue written-authorization
# trigger, a safeguards clause, and a 19-clause acceptable-use policy.
#   https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE
# The contrast that proves the tag cannot be trusted, only the file:
# `PocketAiHub/MiniMax-Music3-MLX` tags itself `license: other` +
# `license_name: minimax-music3-community` and links the real LICENSE (verified live
# via the HF API, 2026-08-20) — one repackager was honest, one was not. The key covers
# the whole family (upstream, the honest MLX port, the Comfy-Org repack, every quant)
# because the weights term follows a format conversion, exactly as for OmniVoice.
#
# ⚠️ PENDING FABLE QA: amber, Get ENABLED — same verdict shape as OmniVoice and
# OpenRAIL. This licence is NOT non-commercial; personal use is unaffected and the
# duties bite only on commercial surfaces, so the honest move is to SAY the term
# rather than switch off a button.
MINIMAX_MUSIC3_LICENSE_REASON = (
    "weights under the MiniMax-Music3 Community License (attribution on commercial "
    "surfaces, written authorization above $20M revenue); some repacks mistag apache-2.0")

_MINIMAX_MUSIC3_RECORD = {
    "license": "minimax-community (weights)",
    "badge": "unknown",
    "reason": MINIMAX_MUSIC3_LICENSE_REASON,
    "source_url": "https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE",
}

# key = a lowercase SUBSTRING matched against the repo id (so every fork/quant of a
# family is covered without listing them all — the mlx-community set alone is six
# repos and theoracleguy has a seventh).
LICENSE_OVERRIDES = {
    "omnivoice": {
        "license": "cc-by-nc (weights)",
        "badge": "unknown",
        "reason": OMNIVOICE_LICENSE_REASON,
        "source_url": "https://huggingface.co/k2-fsa/OmniVoice",
    },
    "minimax-music3": _MINIMAX_MUSIC3_RECORD,
    # Comfy-Org spells the repack `MiniMax-Music-3` (extra hyphen) and every GGUF
    # quant of it inherits that spelling, so BOTH forms are listed rather than
    # relying on one substring to catch a name we do not control.
    "minimax-music-3": _MINIMAX_MUSIC3_RECORD,
}


def license_override(repo: object) -> dict:
    """PURE: the override record for a repo id, or {} when nothing is known.

    Substring match, case-insensitive, on the whole `org/name` string.
    """
    if not isinstance(repo, str) or not repo.strip():
        return {}
    low = repo.strip().lower()
    for key, rec in LICENSE_OVERRIDES.items():
        if key in low:
            return dict(rec)
    return {}


def audio_license_row(repo: object, meta: object) -> dict:
    """PURE: the licence record for one repo — override FIRST, tag second.

    This is the ONE seam both the search rows and the probe go through, so a
    known mistag can never reach the UI through one path and not the other.
    """
    ov = license_override(repo)
    return ov if ov else audio_license_badge(hf_license(meta))


def hf_license(meta: object) -> str:
    """PURE: the licence id for a model, from cardData.license or a `license:*` tag.

    The list API returns tags but usually no cardData; the single-model API returns
    both. Reading either means one function serves both call sites.
    """
    if not isinstance(meta, dict):
        return ""
    card = meta.get("cardData")
    lic = card.get("license") if isinstance(card, dict) else None
    if isinstance(lic, (list, tuple)):
        lic = lic[0] if lic else None
    if not isinstance(lic, str) or not lic.strip():
        lic = meta.get("license") if isinstance(meta.get("license"), str) else None
    if isinstance(lic, str) and lic.strip():
        return lic.strip().lower()
    for t in (meta.get("tags") or []):
        if isinstance(t, str) and t.lower().startswith("license:"):
            return t.split(":", 1)[1].strip().lower()
    return ""


def audio_license_badge(license_id: object) -> dict:
    """PURE: {"license", "badge", "reason"} for one licence id.

    badge ∈ ok | unknown | nc.
      nc      → Get DISABLED, reason shown on the row.
      unknown → amber badge, Get STILL ENABLED. ⚠️ PENDING FABLE QA: this is Debi's
                own machine and a missing license tag is extremely common on model
                repos (kitten, soprano, the ggml-org GGUF mirrors all lack one);
                refusing them would hide half of HuggingFace over metadata hygiene.
                We badge the uncertainty instead of pretending to know.
      ok      → apache/mit/etc.
    """
    lic = (license_id or "").strip().lower() if isinstance(license_id, str) else ""
    if lic in _UNKNOWN_LICENSES:
        return {"license": lic, "badge": "unknown", "reason": "licence unknown"}
    if lic.startswith(_NC_PREFIXES) or any(s in lic for s in _NC_SUBSTRINGS):
        return {"license": lic, "badge": "nc", "reason": LICENSE_NC_REASON}
    if lic.startswith(_RESTRICTED_PREFIXES):
        # amber like unknown, but with the true reason; Get stays ENABLED
        return {"license": lic, "badge": "unknown", "reason": "use-restricted licence"}
    return {"license": lic, "badge": "ok", "reason": ""}


# Replicated from scripts/seed_registry.py (the bridge does not import scripts/).
# bridge/tests/test_audio_search.py asserts these are BYTE-IDENTICAL to the seed
# copy, so the two can never drift apart silently.
AUDIO_WHISPER_REQUIRED = ("n_mels", "n_audio_state", "n_audio_head",
                          "n_audio_layer", "n_vocab", "n_text_state")
AUDIO_WHISPER_VETO = ("_name_or_path", "architectures", "transformers_version",
                      "num_mel_bins", "d_model", "encoder_layers",
                      "decoder_layers", "is_encoder_decoder")


def is_mlx_whisper_cfg(cfg: object) -> bool:
    """PURE: True only for a config.json that is an mlx-whisper ModelDimensions."""
    if not isinstance(cfg, dict):
        return False
    if any(k in cfg for k in AUDIO_WHISPER_VETO):
        return False
    return all(k in cfg for k in AUDIO_WHISPER_REQUIRED)


# Replicated the same way, for the SECOND STT engine (mlx-audio / Parakeet). See
# scripts/seed_registry.py::is_parakeet_config for the reasoning; the test asserts
# these four are byte-identical to the seed copy too, so the pair cannot drift.
AUDIO_PARAKEET_SHAPE_KEYS = ("preprocessor", "encoder", "decoder")
AUDIO_PARAKEET_TARGET_PREFIX = "nemo."
AUDIO_PARAKEET_MIN_NEMO_BLOCKS = 2
AUDIO_PARAKEET_MODEL_TYPES = ("parakeet",)


def is_parakeet_cfg(cfg: object) -> bool:
    """PURE: True only for a NeMo/Parakeet config mlx-audio's STT loader can drive.
    The transformers veto is NOT applied to the shape rule — a positive `nemo.`
    fingerprint is stronger evidence than the absence of transformers keys."""
    if not isinstance(cfg, dict):
        return False
    n = 0
    for k in AUDIO_PARAKEET_SHAPE_KEYS:
        blk = cfg.get(k)
        if isinstance(blk, dict):
            tgt = blk.get("_target_")
            if isinstance(tgt, str) and tgt.startswith(AUDIO_PARAKEET_TARGET_PREFIX):
                n += 1
    if n >= AUDIO_PARAKEET_MIN_NEMO_BLOCKS:
        return True
    mt = cfg.get("model_type")
    if isinstance(mt, str) and mt.strip().lower() in AUDIO_PARAKEET_MODEL_TYPES:
        return not any(k in cfg for k in AUDIO_WHISPER_VETO)
    return False


_TTS_TOKENS = ("tts", "text-to-speech", "speech", "voice", "kokoro", "outetts")


def _file_pairs(files: object) -> list:
    """Coerce a caller's `files` into [(path:str, size:int)]. Third-party JSON goes
    through every one of these functions; a TypeError here would blank the Audio tab."""
    out = []
    for it in (files if isinstance(files, (list, tuple)) else []):
        if isinstance(it, (list, tuple)) and len(it) == 2 and isinstance(it[0], str):
            out.append((it[0], it[1] if isinstance(it[1], int) else 0))
    return out


def gguf_tts_pair(files: object) -> tuple:
    """PURE: (backbone, mmproj) from [(path, size)] — or (None, None).

    llama-tts needs BOTH halves; a repo with only one is not a usable TTS model.
    Preference mirrors the curated starter exactly (Q4_K_M backbone, Q8_0 projector)
    so a searched Qwen3-TTS lands byte-identical to the offered one.
    """
    import os as _os
    ggufs = [(p, s) for p, s in _file_pairs(files) if p.lower().endswith(".gguf")]
    mm = [p for p, _ in ggufs if "mmproj" in _os.path.basename(p).lower()]
    back = [(p, s or 0) for p, s in ggufs
            if "mmproj" not in _os.path.basename(p).lower()]
    if not mm or not back:
        return (None, None)
    pick = next((p for p, _ in back if "q4_k_m" in p.lower()),
                min(back, key=lambda t: t[1])[0])
    proj = next((p for p in mm if "q8_0" in p.lower()), mm[0])
    return (pick, proj)


def audio_probe_verdict(repo: object, cfg: object, files: object,
                        tags: object = (), pipeline: object = "") -> dict:
    """PURE: classify one HF repo for the Audio tab. Never raises.

    Returns {format, warn, file, mmproj, can_get, block_reason} where format ∈
      tts-mlx | stt-mlx | tts-gguf   → a lane the harness can actually drive
      transformers                   → the whisper-medium class: LOOKS right, is not
      unknown                        → we could not tell; Get stays off

    ORDER MATTERS. The transformers veto is applied ONLY on the ASR lane: a TTS
    config that happens to carry `architectures` (several mlx-audio conversions do)
    must not be condemned by a rule written for whisper.
    """
    import os as _os
    repo = repo if isinstance(repo, str) else ""
    pipeline = (pipeline or "").lower() if isinstance(pipeline, str) else ""
    # tags/files are third-party JSON: a surprise type here must not take out the tab.
    tagset = {t.lower() for t in (tags if isinstance(tags, (list, tuple)) else [])
              if isinstance(t, str)}
    pairs = _file_pairs(files)
    paths = [p for p, _ in pairs]
    lowp = [p.lower() for p in paths]
    has_weights = any(p.endswith((".safetensors", ".npz")) for p in lowp)
    has_cfg = any(_os.path.basename(p) == "config.json" for p in paths)
    cfgd = cfg if isinstance(cfg, dict) else {}
    asr_lane = ("whisper" in repo.lower()
                or pipeline == "automatic-speech-recognition"
                or "automatic-speech-recognition" in tagset)

    def _out(fmt, warn="", file=None, mmproj=None):
        # An MLX verdict with no weights/config in the tree would send the Get into
        # whole-repo mode, which 400s ("not an MLX model"). Better to say we do not
        # know than to hand the user a button that cannot work.
        if fmt in ("tts-mlx", "stt-mlx", "stt-mlx-audio") and not (has_weights and has_cfg):
            fmt, warn = "unknown", ("looks like a voice model but ships no "
                                    "safetensors/npz weights + config.json")
        blocked = {"transformers": "transformers checkpoint — not an MLX conversion; "
                                   "mlx_whisper cannot load it",
                   "unknown": "the harness could not identify an engine for this repo"}
        reason = blocked.get(fmt, "")
        if fmt == "unknown" and warn:
            reason = warn                      # the specific miss beats the generic one
        return {"format": fmt, "warn": warn, "file": file, "mmproj": mmproj,
                "can_get": fmt not in blocked, "block_reason": reason}

    # 1. The checkpoint says it is a TTS model (strongest possible evidence).
    if "tts_model_type" in cfgd or isinstance(cfgd.get("talker_config"), dict):
        return _out("tts-mlx")
    # 2. mlx-audio's own tag.
    if "mlx-audio" in tagset:
        return _out("tts-mlx")
    # 3/4. The whisper lane — shape decides, name never does.
    if is_mlx_whisper_cfg(cfgd):
        return _out("stt-mlx")
    # 3b. The OTHER ASR lane: mlx-audio's NeMo/Parakeet family. Checked BEFORE the
    #     transformers veto, because a NeMo config legitimately carries
    #     `model_defaults`/`target` keys and the veto would condemn every real
    #     Parakeet repo — the positive `nemo._target_` fingerprint decides instead.
    if is_parakeet_cfg(cfgd):
        return _out("stt-mlx-audio")
    if asr_lane and cfgd and any(k in cfgd for k in AUDIO_WHISPER_VETO):
        return _out("transformers")
    # 5. GGUF TTS pair (backbone + projector). A TTS token is required: every
    #    vision chat model is also a gguf+mmproj pair and must not land here.
    back, proj = gguf_tts_pair(pairs)
    if back and (any(t in repo.lower() for t in _TTS_TOKENS)
                 or any(t in tagset for t in _TTS_TOKENS)):
        return _out("tts-gguf", file=back, mmproj=proj)
    # 6/7. Tag-only fallbacks for a correctly-shaped MLX repo we cannot fingerprint.
    if has_weights and has_cfg:
        if pipeline == "text-to-speech" or "text-to-speech" in tagset:
            return _out("tts-mlx", warn="not tagged mlx-audio — engine support is "
                                        "unverified for this repo")
        if asr_lane:
            return _out("transformers" if cfgd else "unknown")
    return _out("unknown")


def audio_probe_size(fmt: object, files: object, back=None, proj=None) -> int:
    """PURE: bytes the Get would actually download for this verdict."""
    pairs = _file_pairs(files)
    if fmt == "tts-gguf":
        want = {back, proj}
        return sum(s for p, s in pairs if p in want)
    if fmt in ("tts-mlx", "stt-mlx", "stt-mlx-audio"):
        return sum(s for _, s in _mlx_repo_files(
            [{"path": p, "size": s, "type": "file"} for p, s in pairs]))
    return 0


def audio_probe_voices(cfg: object, files: object) -> list:
    """PURE: named voices this repo declares — config.json spk_id, or Kokoro's
    voices/*.pt stems. Same two mechanisms voices_for_entry resolves on disk, read
    here from the HF tree so the count is visible BEFORE downloading."""
    names = []
    if _voice is not None:
        try:
            names = list(_voice.voices_from_config(cfg).get("voices") or [])
        except Exception:                                  # noqa: BLE001
            names = []
    if names:
        return names
    out = []
    for p, _ in _file_pairs(files):
        low = p.lower().replace("\\", "/")
        if low.startswith("voices/") and low.endswith(".pt"):
            out.append(p.split("/")[-1][:-3])
    return sorted(out)


async def _hf_json(path: str, params=None):
    """GET a HuggingFace JSON endpoint; None on any non-200/exception."""
    try:
        r = await _HF.get(path, params=params or {})
        return r.json() if r.status_code == 200 else None
    except Exception:                                      # noqa: BLE001
        return None


@app.get("/api/models/hf/audio")
async def hf_audio_search(q: str = "", kind: str = "tts", limit: int = 25) -> JSONResponse:
    """Search HuggingFace for VOICE models. kind ∈ tts | tts-gguf | stt.

    The tts kind is the documented UNION of two queries (mlx-audio ∪ mlx) deduped
    by repo id — mlx-audio alone misses Kokoro.
    """
    kind = (kind or "tts").strip().lower()
    if kind not in AUDIO_SEARCH_KINDS:
        return JSONResponse({"error": f"unknown kind {kind!r}"}, status_code=400)
    q = (q or "").strip()
    term = q or (AUDIO_GGUF_DEFAULT_TERM if kind == "tts-gguf" else "")
    seen, out = set(), []
    for base in AUDIO_SEARCH_QUERIES[kind]:
        params = dict(base, limit=limit, sort="downloads", direction="-1")
        if term:
            params["search"] = term
        rows = await _hf_json("/api/models", params)
        if rows is None:
            continue
        for m in rows:
            repo = m.get("id") or m.get("modelId")
            if not repo or repo in seen:
                continue
            seen.add(repo)
            lic = audio_license_row(repo, m)
            out.append({"repo": repo, "downloads": m.get("downloads", 0),
                        "likes": m.get("likes", 0),
                        "pipeline": m.get("pipeline_tag"),
                        "updated": m.get("lastModified") or m.get("createdAt"),
                        **lic})
    if not out and not seen:
        return JSONResponse({"error": "HuggingFace search failed"}, status_code=502)
    out.sort(key=lambda r: r.get("downloads") or 0, reverse=True)
    return JSONResponse(out[:limit * 2])


@app.get("/api/models/hf/audio/probe")
async def hf_audio_probe(repo: str) -> JSONResponse:
    """Config-probe ONE repo: what engine (if any) can drive it, how big the Get is,
    how many named voices it declares, and whether its licence lets us offer it.

    This is the whisper-medium fix generalised: a row is never Get-able because of
    what it is CALLED, only because of what its config.json and file tree say."""
    repo = (repo or "").strip()
    if not repo:
        return JSONResponse({"error": "repo required"}, status_code=400)
    meta = await _hf_json(f"/api/models/{repo}") or {}
    tree = await _hf_json(f"/api/models/{repo}/tree/main",
                          {"recursive": "true"}) or []
    files = [(it.get("path", ""), it.get("size") or 0) for it in tree
             if isinstance(it, dict) and (it.get("type") or "file") == "file"
             and it.get("path")]
    cfg = None
    if any(os.path.basename(p) == "config.json" for p, _ in files):
        try:
            r = await _HF.get(f"/{repo}/raw/main/config.json")
            if r.status_code == 200:
                import json as _json
                cfg = _json.loads(r.text)
                if not isinstance(cfg, dict):
                    cfg = None
        except Exception:                                  # noqa: BLE001
            cfg = None
    v = audio_probe_verdict(repo, cfg, files, meta.get("tags") or [],
                            meta.get("pipeline_tag") or "")
    lic = audio_license_row(repo, meta)
    if lic["badge"] == "nc":
        v["can_get"] = False
        v["block_reason"] = lic["reason"]
    voices = audio_probe_voices(cfg, files)
    return JSONResponse({"repo": repo, **v, **lic,
                         "size_bytes": audio_probe_size(v["format"], files,
                                                        v.get("file"), v.get("mmproj")),
                         "voices": voices, "voice_count": len(voices),
                         "downloads": meta.get("downloads", 0),
                         "likes": meta.get("likes", 0),
                         "files": len(files)})


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


def _registry_update(mid: str, patch: dict) -> "dict | None":
    """Read data/models.json, merge `patch` into the entry with id `mid`, atomic
    write (tmp + os.replace — the SAME shape as _registry_add/_registry_drop).
    Returns the updated entry, or None when the id is not in the registry.

    A key whose patch value is None is REMOVED rather than stored as null: the
    voice picker's "model default" is the absence of a `voice` key, not a null."""
    import json as _json, os as _os
    reg = ROOT / "data" / "models.json"
    try:
        data = _json.loads(reg.read_text())
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            return None
    except Exception:
        return None
    out = None
    for m in data["models"]:
        if isinstance(m, dict) and m.get("id") == mid:
            for k, v in (patch or {}).items():
                if v is None:
                    m.pop(k, None)
                else:
                    m[k] = v
            out = m
            break
    if out is None:
        return None
    tmp = str(reg) + ".harness-tmp"
    with open(tmp, "w") as f:
        _json.dump(data, f, indent=2)
    _os.replace(tmp, reg)
    return out


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
        base = (_mlx_registry_entry(e) if e.get("kind") == "mlx"
                else _gguf_registry_entry(e))
        # Phase A: an AUDIO download carries an explicit format hint from the Get
        # button (never sniffed from the filename — see voice.audio_download_entry).
        vf = e.get("voice_format")
        if vf and _voice is not None:
            try:
                base = _voice.audio_download_entry(base, vf)
            except Exception as ex:                              # noqa: BLE001
                # A bad hint must not lose the download: register the chat-shaped
                # entry and say so, rather than dropping the model on the floor.
                print(f"[dl] audio hint {vf!r} rejected ({ex}) — "
                      f"registering {base.get('id')!r} as a chat model", flush=True)
        # TOOL-CALLING verdict, read from the freshly-downloaded files (the GGUF
        # header / the MLX tokenizer_config). Done HERE rather than inside the two
        # pure builders so those stay filesystem-free — and done at all so a model
        # that just landed shows its `tools` pill without a Rescan. Never raises:
        # `tools: None` is a legitimate "we could not tell".
        if _modeltools is not None and base.get("kind") != "audio":
            try:
                base["tools"] = _modeltools.tools_for_entry(base)
            except Exception:                                    # noqa: BLE001
                base["tools"] = None
        _registry_add(base)
        e["state"] = "done"
    except Exception as ex:
        e["state"] = "error"
        e["error"] = str(ex)[:300]


# Files a model NEVER needs at runtime. Everything else in the repo is fetched.
# DENYLIST, not an allowlist: the old allowlist (*.safetensors / tokenizer* / *.json)
# silently skipped `merges.txt`, so Qwen3-TTS downloaded a vocab with no merges and
# died at generate time with "vocab and merges must be both be from memory or both
# filenames". Every new model family would have re-broken an allowlist the same way;
# a denylist fails toward downloading a few KB too much instead of a dead model.
_MLX_SKIP_EXACT = {".gitattributes", ".gitignore", ".ds_store", "license", "notice"}
_MLX_SKIP_EXT = (".md", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".mp3",
                 ".wav", ".pdf", ".gguf")


def _mlx_repo_files(tree: list) -> list:
    """From an HF tree, return [(relpath, size)] for everything an MLX model needs —
    i.e. the whole repo minus docs/images/licences (see _MLX_SKIP_*). Weights,
    config, tokenizer assets (tokenizer.json OR vocab.json + merges.txt), sentencepiece
    models and nested dirs (e.g. speech_tokenizer/) all come down."""
    import os as _os
    out = []
    for it in tree:
        if (it.get("type") or "file") != "file":
            continue                                   # skip tree/dir entries
        p = it.get("path", "")
        if not p:
            continue
        b = _os.path.basename(p).lower()
        stem = b.rsplit(".", 1)[0]
        if b in _MLX_SKIP_EXACT or stem in _MLX_SKIP_EXACT:
            continue
        if b.endswith(_MLX_SKIP_EXT):
            continue
        out.append((p, it.get("size") or 0))
    return out


def _mk_download(repo: str, files: list, model_id: str, kind: str,
                 model_dir=None, voice_format: "str | None" = None) -> dict:
    """Register a new DOWNLOADS entry + spawn its task. `files` = the
    _run_download file-dict list already built by the caller. `voice_format` (Phase A)
    is the audio hint carried through to the registry entry on completion."""
    _DL_SEQ["n"] += 1
    dl_id = str(_DL_SEQ["n"])
    entry = {"id": dl_id, "repo": repo, "files": files, "state": "downloading",
             "error": None, "rate": 0.0, "model_id": model_id, "kind": kind,
             "model_dir": model_dir, "voice_format": voice_format, "task": None}
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
                                  data/models/<repo-leaf>/ via the same machinery.

    Phase A (voice) adds two OPTIONAL body keys, both only ever set by the Audio tab's
    Get buttons — the chat paths are byte-identical without them:
      • voice_format ∈ tts-gguf | tts-mlx | stt-mlx → the completed download is
        registered as an AUDIO entry (kind:"audio") instead of a chat model.
      • mmproj = "<file>.gguf" → fetched ALONGSIDE the backbone into the SAME model
        dir, so the pair lands as ONE tts-gguf entry. Needed because the existing
        lone-sibling heuristic only fires when the repo has exactly one mmproj, and
        the Qwen3-TTS GGUF repo ships several quants of it."""
    import os as _os
    body = await req.json()
    repo = (body.get("repo") or "").strip()
    filename = (body.get("filename") or "").strip()
    voice_format = (body.get("voice_format") or "").strip().lower() or None
    mmproj_req = _os.path.basename((body.get("mmproj") or "").strip())
    if not repo:
        return JSONResponse({"ok": False, "log": "repo required"}, status_code=400)
    if voice_format and (_voice is None
                         or voice_format not in _voice.AUDIO_FORMATS):
        return JSONResponse(
            {"ok": False, "log": f"unknown voice format {voice_format!r}"},
            status_code=400)
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
        # weights.npz is the older MLX weight format — mlx-community's whisper-base/
        # small conversions ship it INSTEAD of safetensors (recon-flagged; Debi hit it:
        # the Get button 400'd invisibly). Both are MLX weights; accept either.
        has_st = any(p.lower().endswith((".safetensors", ".npz")) for p in paths)
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
        entry = _mk_download(repo, files, model_id, "mlx", model_dir=str(dest_dir),
                             voice_format=voice_format)
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
    # An EXPLICIT mmproj (Audio tab) always wins over the lone-sibling heuristic —
    # a TTS repo carries several mmproj quants, so the heuristic silently fetches
    # nothing and llama-tts would then have no projector to load.
    if mmproj_req:
        mmproj_name = next((p for p in mmprojs
                            if _os.path.basename(p) == mmproj_req), mmproj_req)
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
    entry = _mk_download(repo, files, model_id, "gguf", voice_format=voice_format)
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

# ── Vision attachments (direct lane only) ────────────────────────────────────
# Both serving engines accept OpenAI-style image parts on /v1/chat/completions:
# llama-server with an mmproj projector, and mlx-vlm. The registry already knows
# which models are vision-capable (mmproj sibling for gguf, vision_config /
# image_token_id for mlx — see _gguf_registry_entry / _mlx_registry_entry), so the
# gate below is a registry lookup, never a probe of the model itself.
IMAGE_MAX_CHARS = 12 * 1024 * 1024   # dataURL length cap (~9MB of image bytes)


def build_user_content(text: str, image, vision: bool):
    """PURE: the user turn's `content` for the runner. Returns (content, error).

    no image                 → the plain string (legacy shape, byte-identical)
    image + vision model     → OpenAI parts [{text}, {image_url}]
    image + non-vision model → (None, reason)  → caller streams one proxy_error
    malformed / oversize     → (None, reason)

    Order matters: a malformed or oversize payload is reported as such even on a
    vision model, so the user learns what is actually wrong.
    """
    if not image:
        return text, None
    if not isinstance(image, str) or not image.startswith("data:image/"):
        return None, "attachment is not an image data URL — attach removed"
    if len(image) > IMAGE_MAX_CHARS:
        return None, "image too large — attach removed"
    if not vision:
        return None, "active model has no vision — attach removed"
    return ([{"type": "text", "text": text},
             {"type": "image_url", "image_url": {"url": image}}], None)


def _vision_capable(mid: str) -> bool:
    """Registry truth for one model id — the same flag the Models pane's VISION
    pill and the mlx-vlm engine dispatch read."""
    m = next((x for x in _registry_models() if x.get("id") == mid), None)
    return bool(m and (m.get("vision") or m.get("mmproj")))


def turn_metadata(model, usage, timings, elapsed=None):
    """Pure: the per-message metadata the DIRECT lane stamps on its assistant turn.

    The Agent lane gets server-written metrics for free (Odysseus writes
    response_time / input_tokens / output_tokens / tokens_per_second into the
    message row), so a reopened agent transcript can show per-reply stats. The
    direct lane persists via inject_messages, which accepts an optional
    per-message `metadata` — so the SAME keys, from the same usage/timings frame
    the analytics capture already parses, give the direct lane parity.

    Only keys we actually know are included (a runner build that reports no
    timings simply yields fewer stats, never zeros or nulls). Never raises.
    """
    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    u = usage if isinstance(usage, dict) else {}
    tm = timings if isinstance(timings, dict) else {}
    out = {}
    if model:
        out["model"] = model
    tps = _num(tm.get("predicted_per_second"))
    if tps is not None:
        out["tokens_per_second"] = round(tps, 2)
    el = _num(elapsed)
    if el is not None:
        out["response_time"] = round(el, 2)
    itok = _num(u.get("prompt_tokens"))
    if itok is not None:
        out["input_tokens"] = int(itok)
    otok = _num(u.get("completion_tokens"))
    if otok is not None:
        out["output_tokens"] = int(otok)
    return out


# ── Model sampling settings (per-model, DIRECT LANE) ─────────────────────────
# Spec basis: docs/research/2026-08-20-model-settings.md §0.1-0.5.
#
# THREE facts shape this block:
#  (1) Until now the direct lane sent NO sampling fields at all — every generation
#      ran on whatever the engine's own defaults were, and those differ per engine.
#  (2) mlx_lm.server defaults `max_tokens` to 512 and mlx_vlm to 2048 when the body
#      omits it, so every MLX reply was SILENTLY TRUNCATED. llama.cpp's -1 is
#      unbounded, which is why the gguf lane never showed it. `max_tokens` is
#      therefore ALWAYS sent now, for every model, whether or not it has overrides.
#  (3) `--repeat-penalty 1.1 --repeat-last-n 256` on the llama-server launch line
#      (scripts/start_component.sh) was a buried constant. It STAYS as the engine
#      default floor — that is the only thing reaching the Agent/Hermes lanes, which
#      build their own request bodies — but the same two numbers are now the VISIBLE
#      defaults here, and a request body overrides argv (Fable D2: body wins).
#
# LANE HONESTY (Fable D1): this is a DIRECT-LANE feature. Odysseus sends only
# temperature (from its own global admin preset) and Hermes structurally cannot send
# a temperature at all, so there is deliberately no fan-out. The panel says so.
SAMPLING_DEFAULTS = {
    "temperature": 0.7,       # llama.cpp's own is 0.8 (creative-completion tuned);
    "top_p": 0.95,            # 0.7 is the conventional assistant setting and is
    "top_k": 40,              # gentler on heavily-quantized local models.
    "min_p": 0.05,
    "repeat_penalty": 1.1,    # promoted verbatim from the argv constant (2026-08-06
    "repeat_last_n": 256,     # loop incident) — the one number here with evidence.
    "max_tokens": 4096,       # see (2): omitting this truncated every MLX reply.
    "seed": -1,               # -1 = random; never sent (MLX has no -1 convention).
}
# Display order for the UI (dict order is stable, but the UI must not depend on it).
SAMPLING_ORDER = ("temperature", "top_p", "top_k", "min_p",
                  "repeat_penalty", "repeat_last_n", "max_tokens", "seed")
# canonical key -> the BODY key that engine actually reads. The two penalty keys are
# genuinely named differently on the MLX servers; the numeric meaning is the same
# (logits of repeated tokens divided by the value, 1.0 = no-op), only the "disabled"
# sentinel differs (llama.cpp 1.0, MLX 0.0) — which is why we never write 0 here.
_S_MLX = {"temperature": "temperature", "top_p": "top_p", "top_k": "top_k",
          "min_p": "min_p", "repeat_penalty": "repetition_penalty",
          "repeat_last_n": "repetition_context_size",
          "max_tokens": "max_tokens", "seed": "seed"}
SAMPLING_WIRE = {
    "llamacpp": {k: k for k in SAMPLING_ORDER},
    "mlxlm": dict(_S_MLX),
    "mlxvlm": dict(_S_MLX),
}
# (min, max, coercer). Ranges are the union of what both engines accept; MLX
# publishes its own in mlx_lm/server.py:1229-1251 and these sit inside them.
SAMPLING_RANGES = {
    "temperature": (0.0, 2.0, float),
    "top_p": (0.0, 1.0, float),
    "top_k": (0, 500, int),          # 0 = off
    "min_p": (0.0, 1.0, float),      # 0 = off
    "repeat_penalty": (1.0, 2.0, float),   # 1.0 = off on BOTH scales
    "repeat_last_n": (-1, 8192, int),      # llama.cpp: -1 = whole ctx, 0 = off
    "max_tokens": (1, 262144, int),        # v2.1: no default change (4096 IS the MLX
    "seed": (-1, 2147483647, int),         # truncation fix) — only the ceiling moved.
}
# v2.1 (Debi ask, LM Studio reference): every row explains itself on hover. ONE source
# — the bridge computes the string, the panel only prints it — so a field can never be
# drawn without an explanation, and the explanation can never disagree with the range.
SAMPLING_HELP = {
    "temperature": ("Randomness. Lower is more predictable and repetitive, higher is "
                    "more varied. Near 0 is almost deterministic."),
    "top_p": ("Nucleus sampling — only consider the most likely tokens whose "
              "probabilities add up to this. 1.0 considers everything."),
    "top_k": "Only consider this many candidates per token. 0 = no limit.",
    "min_p": ("Drop candidates less likely than this fraction of the best one — "
              "a gentler filter than top_p."),
    "repeat_penalty": ("Divides the score of tokens already used, to break loops. "
                       "1.0 = off. 1.1 is the value that fixed the 'C-C-C…' loop here."),
    "repeat_last_n": ("How many recent tokens the repeat penalty looks back over. "
                      "-1 = the whole context."),
    "max_tokens": ("Longest single reply, in tokens — NOT the context window. The cap "
                   "exists because MLX otherwise silently stops replies at 512."),
    "seed": ("Fixes the random draw so the same prompt gives the same reply. "
             "-1 = random every time (nothing is sent to the engine)."),
}
SAMPLING_STOP_MAX = 4          # stop strings, storage/merge only — no UI row in v1
# v2 (2026-08-20, Debi ruling): the same saved values ALSO become the engine's launch
# defaults (scripts/start_component.sh, SAMPLING_FLOOR_WIRE below), so the Agent and
# Hermes lanes — which build their own bodies and send no sampling at all — inherit
# them. Only EXPLICIT overrides travel: a model with nothing saved keeps the engine's
# own defaults on those lanes, exactly as before.
SAMPLING_LANE_NOTE = ("Applies to CHAT immediately. Values you set here also become "
                      "the model's launch defaults for the Agent and Hermes lanes — "
                      "those pick them up the next time the model loads.")
# Which canonical sampling keys the engine accepts on its LAUNCH LINE (a different
# question from the request body: SAMPLING_WIRE). Evidence, re-read this session:
#   llama.cpp b10427 data/llama-server.help.txt:234,240,241,243,244,249,251
#   mlx_lm.server  data/mlx-venv/.../mlx_lm/server.py:1818-1848 (--temp/--top-p/
#                  --top-k/--min-p/--max-tokens; NO seed, NO repeat flags)
#   mlx_vlm.server mlx_vlm/server/cli.py:105 — --max-tokens ONLY of this set.
# Documentation of the seam; start_component.sh does the emitting (it owns the
# per-flag support gate). A flag that cannot be evidenced is never emitted.
SAMPLING_FLOOR_WIRE = {
    "llamacpp": {"temperature": "--temp", "top_p": "--top-p", "top_k": "--top-k",
                 "min_p": "--min-p", "repeat_penalty": "--repeat-penalty",
                 "repeat_last_n": "--repeat-last-n", "seed": "--seed"},
    "mlxlm": {"temperature": "--temp", "top_p": "--top-p", "top_k": "--top-k",
              "min_p": "--min-p", "max_tokens": "--max-tokens"},
    "mlxvlm": {"max_tokens": "--max-tokens"},
}


def sampling_engine(entry: dict) -> str:
    """PURE. Which request dialect this registry entry's server speaks. Mirrors
    start_component.sh:64-66 (format mlx + vision → mlx-vlm, mlx → mlx-lm, else
    llama.cpp). Anything unrecognisable falls back to llamacpp, whose key names are
    the OpenAI-ish ones every engine here tolerates."""
    e = entry if isinstance(entry, dict) else {}
    if str(e.get("format") or "").strip().lower() == "mlx":
        return "mlxvlm" if (e.get("vision") or e.get("mmproj")) else "mlxlm"
    return "llamacpp"


def _sampling_num(key: str, raw):
    """PURE. Coerce one value, or None when it is junk / out of range. Total: any
    input type is safe. Booleans are rejected (True == 1 would silently pass)."""
    spec = SAMPLING_RANGES.get(key)
    if spec is None or isinstance(raw, bool) or raw is None:
        return None
    lo, hi, cast = spec
    try:
        v = cast(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):     # NaN / inf
        return None
    if v < lo or v > hi:
        return None
    return v


def _sampling_stop(raw):
    """PURE. A stop list, or None. Accepts a list/tuple of strings or one string."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None
    out = [s[:64] for s in raw if isinstance(s, str) and s.strip()][:SAMPLING_STOP_MAX]
    return out or None


def sampling_saved(entry: dict) -> dict:
    """PURE. The per-model overrides, cleaned. Junk keys and junk values are dropped
    rather than surfaced — a hand-edited registry can never break a turn."""
    e = entry if isinstance(entry, dict) else {}
    raw = e.get("settings")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if k == "stop":
            s = _sampling_stop(v)
            if s:
                out["stop"] = s
            continue
        n = _sampling_num(k, v)
        if n is not None:
            out[k] = n
    return out


def sampling_merge(entry: dict) -> dict:
    """PURE. harness defaults → per-model overrides → engine key translation.
    Returns the request-body fragment the direct lane merges in. NEVER raises, and
    ALWAYS contains a `max_tokens` (that absence is the MLX truncation bug).

    `seed` is omitted unless explicitly set to >= 0: -1 means "random" to
    llama.cpp but is not a documented MLX sentinel, so we send nothing instead."""
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    vals = dict(SAMPLING_DEFAULTS)
    vals.update(sampling_saved(entry))
    out = {}
    for canon in SAMPLING_ORDER:
        if canon not in wire:
            continue                     # engine cannot honour it — send nothing
        v = vals.get(canon)
        if v is None:
            continue
        if canon == "seed" and v < 0:
            continue
        out[wire[canon]] = v
    stop = vals.get("stop")
    if stop:
        out["stop"] = list(stop)
    return out


def sampling_view(entry: dict) -> dict:
    """PURE. What the Models detail pane renders: the engine, and one row per field
    this engine can actually honour, carrying its wire name (the honest label), the
    harness default, and the per-model override (None = running the default).

    Engine-conditional by construction: a field the engine cannot honour is ABSENT,
    not greyed out — a control that cannot work must not be drawn."""
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    saved = sampling_saved(entry)
    fields = []
    for canon in SAMPLING_ORDER:
        if canon not in wire:
            continue
        lo, hi, _c = SAMPLING_RANGES[canon]
        fields.append({"key": canon, "label": wire[canon],
                       "default": SAMPLING_DEFAULTS.get(canon),
                       "value": saved.get(canon), "min": lo, "max": hi,
                       # v2.1: plain-language tooltip, single-sourced here.
                       "help": SAMPLING_HELP.get(canon, "")})
    return {"engine": eng, "fields": fields,
            "changed": sum(1 for f in fields if f["value"] is not None),
            "note": SAMPLING_LANE_NOTE}


@app.post("/api/models/settings")
async def api_model_settings(req: Request) -> JSONResponse:
    """{id, settings:{key: value|null}} → per-model sampling overrides.

    ⚠️ SEAM CHOICE: there is deliberately no GET here. `/api/models` already
    carries every installed entry and the panel already polls it, so the read side
    is one extra key on that payload (`sampling`) rather than a second route.

    A null value REMOVES that key (the _registry_update grammar the voice pins
    established: a reset is the ABSENCE of a key, never a stored null), and an
    empty result removes `settings` entirely. `{id, reset:true}` resets all."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    if _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse({"ok": False, "error": f"'{mid}' is a voice model — "
                                                   f"sampling settings are for chat models"},
                            status_code=400)
    if body.get("reset"):
        _registry_update(mid, {"settings": None})
        print(f"[models] sampling reset {mid}", flush=True)
        upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
        return JSONResponse({"ok": True, "id": mid, "settings": {},
                             "sampling": sampling_view(upd),
                             "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})
    patch = body.get("settings")
    if not isinstance(patch, dict) or not patch:
        return JSONResponse({"ok": False, "error": "settings must be a non-empty object"},
                            status_code=400)
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    new = sampling_saved(entry)
    for k, v in patch.items():
        if k == "stop":
            if v is None:
                new.pop("stop", None)
                continue
            s = _sampling_stop(v)
            if s is None:
                return JSONResponse({"ok": False, "error": "stop must be a list of strings"},
                                    status_code=400)
            new["stop"] = s
            continue
        if k not in SAMPLING_RANGES or k not in wire:
            return JSONResponse(
                {"ok": False, "error": f"'{k}' is not a sampling field this engine "
                                       f"({eng}) can honour"}, status_code=400)
        if v is None or v == "":
            new.pop(k, None)
            continue
        n = _sampling_num(k, v)
        if n is None:
            lo, hi, _c = SAMPLING_RANGES[k]
            return JSONResponse({"ok": False,
                                 "error": f"{k} must be a number between {lo} and {hi}"},
                                status_code=400)
        new[k] = n
    _registry_update(mid, {"settings": new or None})
    print(f"[models] sampling {mid} -> {new or 'defaults'}", flush=True)
    upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
    return JSONResponse({"ok": True, "id": mid, "settings": new,
                         "sampling": sampling_view(upd),
                         # A sampling change can move the LAUNCH claim too (floors).
                         "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})


# ── Model LOAD settings (per-model, LAUNCH LINE) ──────────────────────────────
# Sampling v1 was deliberately request-body only (Fable D3) because every field here
# costs a 60-90s model reload. That is the whole difference: these are written the
# same way (an optional `load` dict on the registry entry, through _registry_update,
# None removes the key, carried across a RESCAN via seed_registry.USER_KEYS), but
# they only take effect when the runner relaunches — which is what the panel's
# "Apply & reload" chip does, via the EXISTING /api/models/switch on the same id.
#
# ENGINE HONESTY: all four are llama.cpp launch flags. `mlx_lm.server` has no
# context, gpu-layer, flash-attn or KV-quant flag at all (research §1.3: "Confirmed
# absent: --api-key and any --ctx-size"), and `mlx_vlm.server`'s KV suite is a
# BIT-COUNT/scheme API (--kv-bits/--kv-quant-scheme), not llama.cpp's `q8_0` type
# names — mapping one onto the other would be inventing a translation, so an MLX
# model's Load group is simply ABSENT rather than drawn with dead controls.
#
# v2.1 (2026-08-20, Debi ask): the group is filled out with the rest of llama.cpp's
# load-time surface. EVERY new flag was read out of this pinned binary's own
# `data/llama-server.help.txt` before it was added (line refs on each row below) —
# the same evidence discipline as the MTP flags. Nothing was added for MLX, because
# nothing exists there to add.
LOAD_ORDER = ("ctx", "gpu_layers", "flash_attn", "kv_quant", "threads",
              "batch", "ubatch", "mlock", "mmap",
              "rope_freq_base", "rope_freq_scale")
# canonical key -> the LAUNCH FLAG that engine reads. Empty dict = no Load group.
#   help refs: --ctx-size :23, -ngl/--n-gpu-layers :117, -fa/--flash-attn :39,
#   -ctk/-ctv :75-82, -t/--threads :7, -b/--batch-size :29, -ub/--ubatch-size :31,
#   --mlock :87, --mmap/--no-mmap :89, --rope-freq-base :51, --rope-freq-scale :54.
LOAD_WIRE = {
    "llamacpp": {"ctx": "--ctx-size", "gpu_layers": "--n-gpu-layers",
                 "flash_attn": "--flash-attn", "kv_quant": "--cache-type-k/v",
                 "threads": "--threads", "batch": "--batch-size",
                 "ubatch": "--ubatch-size", "mlock": "--mlock",
                 "mmap": "--mmap/--no-mmap",
                 "rope_freq_base": "--rope-freq-base",
                 "rope_freq_scale": "--rope-freq-scale"},
    "mlxlm": {},
    "mlxvlm": {},
}
# Displayed as the "default" beside each row. These are what the runner does TODAY
# with nothing saved, not a harness opinion: ctx falls back to the registry entry's
# own ctx (start_component.sh:89-91), and the rest are llama.cpp's own documented
# defaults (help :117 auto, :39 auto, :75-82 f16, :7 -1/auto, :29 2048, :31 512,
# :87 off, :89 enabled, :51/:54 loaded from the model).
LOAD_DEFAULTS = {"ctx": "registry / 65536", "gpu_layers": "auto",
                 "flash_attn": "auto", "kv_quant": "f16", "threads": "auto",
                 "batch": "2048", "ubatch": "512", "mlock": "off", "mmap": "on",
                 "rope_freq_base": "from the model",
                 "rope_freq_scale": "from the model"}
LOAD_RANGES = {"ctx": (1024, 262144, int), "gpu_layers": (-1, 999, int),
               "threads": (1, 32, int), "batch": (1, 32768, int),
               "ubatch": (1, 32768, int),
               "rope_freq_base": (0.0, 10000000.0, float),
               "rope_freq_scale": (0.0, 100.0, float)}
# ⚠️ -1 is the conventional "all layers" value users type; start_component.sh
# translates it to llama.cpp's own documented `all` token at the argv seam.
LOAD_BOOLS = ("flash_attn", "mlock", "mmap")
# Which int rows deserve an LM-Studio-style slider beside the box (step, in the
# field's own unit). Only the three a user genuinely drags; the rest stay numbers.
LOAD_SLIDER_STEP = {"ctx": 1024, "gpu_layers": 1, "threads": 1}
LOAD_KV_TYPES = ("off", "q8_0", "q4_0")   # a SUBSET of the 9 the engine accepts —
# the three that are actually useful decisions (off = leave the f16 default alone).
LOAD_NOTE = ("These change how the model is LOADED — Apply & reload restarts the "
             "runner (60–90s). Your sampling values are applied on the same reload.")
LOAD_HELP = {
    "ctx": ("How much conversation the model can see at once, in tokens. "
            "Bigger = more RAM, and a slower first reply on a long chat."),
    "gpu_layers": ("How many layers run on the GPU. -1 = all of them — on Apple "
                   "unified memory that is almost always what you want."),
    "flash_attn": ("Faster, lower-memory attention. 'auto' lets the engine decide; "
                   "turn it off only if a model misbehaves with it on."),
    "kv_quant": ("Compresses the attention cache — much less RAM at long context, "
                 "for a slight quality cost. q8_0 is the safe one, q4_0 the small one."),
    "threads": ("CPU threads used for generation. The engine picks a sensible number "
                "on its own; set this only to leave cores free for other work."),
    "batch": ("How many prompt tokens are queued for processing at a time. Bigger can "
              "prefill a long prompt faster and uses more memory."),
    "ubatch": ("How many tokens are actually computed in one pass. Lower it if a very "
               "long prompt runs the machine out of memory."),
    "mlock": ("Keep the whole model pinned in RAM so macOS can never swap it out. "
              "Costs the model's full size in RAM the entire time it is loaded."),
    "mmap": ("Memory-map the weights instead of reading them in. On = faster start "
             "(the default); off = slower load but fewer page-outs."),
    "rope_freq_base": ("Advanced: RoPE base frequency, used to stretch a model past "
                       "the context it was trained on. Leave empty unless the model "
                       "card gives you a number."),
    "rope_freq_scale": ("Advanced: RoPE frequency scale — 0.5 doubles the usable "
                        "context. Leave empty unless the model card gives you a "
                        "number."),
}


def _load_val(key: str, raw):
    """PURE. Coerce one load value, or None when it is junk / out of range. Total:
    any input type is safe. Mirrors _sampling_num, plus the two non-numeric kinds."""
    if raw is None:
        return None
    if key in LOAD_BOOLS:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("on", "true", "1", "yes"):
            return True
        if s in ("off", "false", "0", "no"):
            return False
        return None
    if key == "kv_quant":
        s = str(raw).strip().lower() if not isinstance(raw, bool) else ""
        return s if s in LOAD_KV_TYPES else None
    spec = LOAD_RANGES.get(key)
    if spec is None or isinstance(raw, bool):
        return None
    lo, hi, cast = spec
    try:
        v = cast(raw)                       # OverflowError: int(inf); ValueError: int(nan)
    except (TypeError, ValueError, OverflowError):
        return None
    if v != v:
        return None
    return None if (v < lo or v > hi) else v


def load_saved(entry: dict) -> dict:
    """PURE. The per-model load overrides, cleaned. Junk keys and junk values are
    dropped rather than surfaced — a hand-edited registry can never fail a launch."""
    e = entry if isinstance(entry, dict) else {}
    raw = e.get("load")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k in LOAD_ORDER:
        if k not in raw:
            continue
        v = _load_val(k, raw.get(k))
        if v is not None:
            out[k] = v
    return out


def load_view(entry: dict) -> dict:
    """PURE. One row per field THIS engine can honour — absent, never greyed out.

    ⚠️ v2.1: the `applied` claim MOVED OUT of here to `launch_view`. It never
    belonged to the Load group alone: an MLX model has no load fields at all, yet
    its saved sampling values DO ride its launch line, so it had pending-launch
    changes with no group to host the Apply chip. See launch_saved/launch_view."""
    eng = sampling_engine(entry)
    wire = LOAD_WIRE.get(eng, {})
    saved = load_saved(entry)
    fields = []
    for canon in LOAD_ORDER:
        if canon not in wire:
            continue
        row = {"key": canon, "label": wire[canon],
               "default": LOAD_DEFAULTS.get(canon), "value": saved.get(canon),
               "help": LOAD_HELP.get(canon, "")}
        if canon in LOAD_RANGES:
            row["min"], row["max"], cast = LOAD_RANGES[canon]
            row["kind"] = "int" if cast is int else "float"
            if canon in LOAD_SLIDER_STEP:
                row["slider"] = LOAD_SLIDER_STEP[canon]
        elif canon in LOAD_BOOLS:
            row["kind"] = "bool"
        else:
            row["kind"] = "enum"
            row["choices"] = list(LOAD_KV_TYPES)
        fields.append(row)
    return {"engine": eng, "fields": fields,
            "changed": sum(1 for f in fields if f["value"] is not None),
            "note": LOAD_NOTE}


# ── The UNIFIED launch snapshot (v2.1) ───────────────────────────────────────
# What a relaunch would change is NOT only the Load group: the sampling FLOORS ride
# the same launch line (SAMPLING_FLOOR_WIRE), and on an MLX model they are the ONLY
# thing that does. So the record of "what the runner was actually started with" is
# both halves together, and the Apply & reload affordance hangs off THAT — which is
# what makes it appear for an MLX model, whose Load group is empty by construction.
LAUNCH_NOTE = ("Sampling applies to CHAT on your next message. Apply & reload "
               "restarts the runner (60–90s) so these also become the launch "
               "defaults the Agent and Hermes lanes inherit.")


def floor_saved(entry: dict) -> dict:
    """PURE. The saved sampling values that actually reach THIS engine's launch
    line — the rest cannot change a relaunch and must not make it look pending."""
    wire = SAMPLING_FLOOR_WIRE.get(sampling_engine(entry), {})
    return {k: v for k, v in sampling_saved(entry).items() if k in wire}


def launch_saved(entry: dict) -> dict:
    """PURE. Everything a relaunch would carry, in one comparable record."""
    return {"load": load_saved(entry), "floors": floor_saved(entry)}


def launch_view(entry: dict, launched=None) -> dict:
    """PURE. The shared Apply & reload row.

    `applied` is a three-state claim, and the third state matters: None means the
    bridge never launched this model itself and therefore has NO opinion (it must
    not tell the user their change is unapplied when it cannot know). False = the
    saved set differs from what the runner was actually launched with."""
    saved = launch_saved(entry)
    eng = sampling_engine(entry)
    applied = None
    if isinstance(launched, dict):
        prev = {"load": launched.get("load") if isinstance(launched.get("load"), dict) else {},
                "floors": launched.get("floors") if isinstance(launched.get("floors"), dict) else {}}
        applied = (saved == prev)
    return {"engine": eng, "applied": applied, "note": LAUNCH_NOTE,
            # How many saved values a relaunch would actually carry — the honest
            # count for "there is something to apply here".
            "changed": len(saved["load"]) + len(saved["floors"]),
            # Whether this engine has ANY launch-line surface at all. True for all
            # three today (mlx-vlm still takes --max-tokens), but the panel asks
            # rather than assumes, so a future engine with none draws no chip.
            "appliable": bool(LOAD_WIRE.get(eng, {})
                              or SAMPLING_FLOOR_WIRE.get(eng, {}))}


# Process-lifetime record of the launch set the runner was ACTUALLY launched with,
# written only where WE launch it (_do_switch / the runner start path). A model the
# bridge never started has no entry — and therefore launch_view makes no claim.
_LOAD_AT_LAUNCH: dict = {}


def _record_load_launch(model_id: str) -> None:
    """Best-effort: never raises into a start path."""
    try:
        if not model_id:
            return
        e = next((m for m in _registry_models() if m.get("id") == model_id), None)
        _LOAD_AT_LAUNCH[model_id] = launch_saved(e or {})
    except Exception:
        pass


@app.post("/api/models/load-settings")
async def api_model_load_settings(req: Request) -> JSONResponse:
    """{id, load:{key: value|null}} → per-model LOAD overrides (+ {id, reset:true}).

    Same seam choice as sampling: no GET — `/api/models` already carries `load`
    (the raw pin) and `loadview` (the rendered, engine-filtered view)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    if _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse({"ok": False, "error": f"'{mid}' is a voice model — "
                                                   f"load settings are for chat models"},
                            status_code=400)
    if body.get("reset"):
        _registry_update(mid, {"load": None})
        print(f"[models] load reset {mid}", flush=True)
        upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
        return JSONResponse({"ok": True, "id": mid, "load": {},
                             "loadview": load_view(upd),
                             "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})
    patch = body.get("load")
    if not isinstance(patch, dict) or not patch:
        return JSONResponse({"ok": False, "error": "load must be a non-empty object"},
                            status_code=400)
    eng = sampling_engine(entry)
    wire = LOAD_WIRE.get(eng, {})
    new = load_saved(entry)
    for k, v in patch.items():
        if k not in LOAD_ORDER or k not in wire:
            return JSONResponse(
                {"ok": False, "error": f"'{k}' is not a load setting this engine "
                                       f"({eng}) can honour"}, status_code=400)
        if v is None or v == "":
            new.pop(k, None)
            continue
        val = _load_val(k, v)
        if val is None:
            if k == "kv_quant":
                msg = f"kv_quant must be one of {', '.join(LOAD_KV_TYPES)}"
            elif k in LOAD_BOOLS:
                msg = f"{k} must be on or off"
            else:
                lo, hi, cast = LOAD_RANGES[k]
                kind = "a whole number" if cast is int else "a number"
                msg = f"{k} must be {kind} between {lo} and {hi}"
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        new[k] = val
    _registry_update(mid, {"load": new or None})
    print(f"[models] load {mid} -> {new or 'engine defaults'}", flush=True)
    upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
    return JSONResponse({"ok": True, "id": mid, "load": new,
                         "loadview": load_view(upd),
                         "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})


@app.post("/api/chat/direct")
async def chat_direct(req: Request) -> StreamingResponse:
    body = await req.json()
    sid = body.get("session", "")
    user_msg = (body.get("message") or "").strip()
    image = body.get("image") or ""
    image_name = (body.get("image_name") or "")[:200]
    rc = cfg().get("runner", {})
    base = (rc.get("endpoint") or "http://127.0.0.1:6767/v1").rstrip("/")
    key, model = rc.get("api_key", ""), rc.get("model", "")
    # `model` stays our REGISTRY ID (labels/analytics); `wire` is what the runner
    # accepts — identical for llama.cpp (--alias), the model PATH for MLX servers
    # (which would otherwise try to resolve our id on HF → 404 → runner 400).
    _reg = _registry_models()
    wire = wire_model_id(model, _reg)
    # Per-model sampling, engine-translated. Read here (once per turn) rather than
    # cached so an edit in the Models pane lands on the NEXT message with no reload.
    # An unknown model still gets the harness defaults — which is what guarantees an
    # explicit max_tokens on every single turn (see SAMPLING_DEFAULTS).
    sampling = sampling_merge(next((m for m in _reg if m.get("id") == model), None) or {})

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

    # An attached image only rides along when the LIVE model can see it. The live id
    # (not just runner.model) is the same source the composer's VISION chip uses, so
    # the UI's promise and the gate here can't disagree. Probed only when an image is
    # actually attached — no extra work on ordinary turns.
    vision = False
    if image:
        live = None
        try:
            if rc.get("port"):
                live = await asyncio.to_thread(_live_model_id, int(rc["port"]))
        except Exception:
            live = None
        vision = _vision_capable(live or model)
    content, cerr = build_user_content(user_msg, image, vision)
    messages.append({"role": "user", "content": content if not cerr else user_msg})

    async def gen():
        import json as _json, time as _t
        if cerr:   # never call the runner with an attachment it can't use
            yield f'data: {_json.dumps({"type": "proxy_error", "error": cerr})}\n\n'
            yield "data: [DONE]\n\n"
            return
        full, think_open = [], False
        think = []        # thinking sidecar (both reasoning_content + inline <think>)
        t0 = _t.monotonic(); stats = {}   # for best-effort usage analytics
        try:
            async with _RUNNER.stream(
                "POST", f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": wire, "messages": messages,
                      "stream": True, "cache_prompt": True,
                      "stream_options": {"include_usage": True},
                      **sampling},
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
            stats["elapsed"] = _t.monotonic() - t0     # per-reply stats stamp
            answer = "".join(full).strip()
            if sid and user_msg:
                persisted = injected = False
                try:
                    # New Odysseus main removed POST /api/session/{sid}/message;
                    # append via the bulk inject_messages endpoint (user before assistant).
                    # TEXT only: the store (and the thinking sidecar's answer-hash
                    # join) stay string-shaped; the attachment is recorded as a marker
                    # so a reopened transcript still shows an image was sent.
                    msgs = [{"role": "user",
                             "content": user_msg + ("\n[image attached]" if image else "")}]
                    if answer:
                        am = {"role": "assistant", "content": answer}
                        # per-reply stats (tok/s · tokens · time) so a reopened
                        # direct-lane transcript stamps the same line the Agent
                        # lane gets from Odysseus's own metrics. Best-effort:
                        # an empty dict is simply not sent.
                        try:
                            meta = turn_metadata(model, stats.get("usage"),
                                                 stats.get("timings"),
                                                 stats.get("elapsed"))
                            if meta:
                                am["metadata"] = meta
                        except Exception:
                            pass
                        msgs.append(am)
                    await _ody_req("POST", f"/api/session/{sid}/inject_messages",
                                   json={"messages": msgs})
                    injected = True
                    if answer:
                        persisted = True
                except Exception:
                    pass
                if injected and image:
                    # Image sidecar: keep the BYTES locally, keyed by (sid, user
                    # text hash), so reopening the session rehydrates the same
                    # thumbnail instead of just the marker line. A malformed or
                    # oversize dataURL is simply not stored — never fails a turn.
                    _mime, _raw = parse_data_url(image, IMAGE_MAX_CHARS)
                    if _raw:
                        log_attachment(sid, user_key(user_msg), image_name,
                                       _mime, _raw)
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
        if t == "clarify.request":
            # INTERACTIVE ASK CARD (2026-08-14). The `clarify` tool blocks the
            # agent thread on a gateway prompt (tui_gateway/server.py:5376-5390
            # clarify_callback → _block("clarify.request", …)); the payload is
            # {question, choices?, multi_select? (only when True)} plus the
            # request_id _block injects at server.py:2861. Without a surface for
            # it the turn simply sat "working" until something timed out — the
            # exact class approval cards already solved.
            #
            # allows_free_text is ALWAYS true and that is upstream's own rule,
            # not our guess: every renderer appends an "Other (type your answer)"
            # option (tools/clarify_tool.py:22, schema :233), and a clarify with
            # NO choices is open-ended by construction (:157 empty list → None).
            # The answer is a plain STRING either way — the tool returns it
            # verbatim as user_response (clarify_tool.py:170).
            ch = p.get("choices")
            opts = [str(c) for c in ch if str(c or "").strip()] if isinstance(ch, list) else []
            return ([{"type": "ask",
                      "request": {"request_id": str(p.get("request_id") or ""),
                                  "question": str(p.get("question") or ""),
                                  "options": opts,
                                  "multi_select": bool(p.get("multi_select")),
                                  "allows_free_text": True}}], "")
        if t == "clarify.expire":
            # Upstream gave up waiting (server.py:2886-2896 emits `<x>.expire`
            # for every blocking bridge whose respond tolerates a late reply).
            # The card must stop pretending it is still answerable.
            return ([{"type": "ask_expire",
                      "request_id": str(p.get("request_id") or "")}], "")
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


# ── MAX TURN TIME (2026-08-14) ────────────────────────────────────────────────
# A 4B thinking model can spiral into a deliberation loop that never terminates:
# it keeps EMITTING, so the relay's 20s-silence watchdogs never fire and the only
# remaining bound was the 600s TOTAL-SILENCE hard guard — which such a turn never
# trips either (it is not silent). Even when a guard did fire, only the RELAY gave
# up: Hermes kept generating and kept cooking the CPU. So this guard is armed at
# prompt.submit, measures TOTAL turn time (not silence), is checked on the EVENT
# path as well as on the timeout tick, and its remedy is session.interrupt — it
# kills the GENERATION, not just the stream.
HERMES_MAX_TURN_S_DEFAULT = 600.0


def hermes_max_turn_s(conf) -> float:
    """Resolve `hermes.max_turn_s` (seconds). PURE.

    0 (or negative) = DISABLED. Absent OR unparseable = the 600s default: this is
    a safety guard, so a typo must not silently switch it off — disabling has to be
    a deliberate `0`. Top-level `hermes:` block (NOT components.hermes) because
    ship.sh's manifest merge is additive at the TOP level only: a new sub-key under
    the already-present components.hermes would never reach the app snapshot.
    """
    try:
        h = (conf or {}).get("hermes")
    except Exception:
        return HERMES_MAX_TURN_S_DEFAULT
    if not isinstance(h, dict) or "max_turn_s" not in h:
        return HERMES_MAX_TURN_S_DEFAULT
    v = h.get("max_turn_s")
    if isinstance(v, bool) or v is None:
        return HERMES_MAX_TURN_S_DEFAULT
    try:
        f = float(v)
    except (TypeError, ValueError):
        return HERMES_MAX_TURN_S_DEFAULT
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return HERMES_MAX_TURN_S_DEFAULT
    return 0.0 if f <= 0 else f


# SEGMENT, NOT TURN (2026-08-14h, Fable revision after Debi's objection): a cap on
# TOTAL turn time punishes exactly the work the harness exists for — a research turn
# that legitimately spends an hour making tool call after tool call. What must be
# bounded is an UNBROKEN GENERATION STRETCH: the model talking to itself with nothing
# to show for it. So the clock is a SEGMENT clock — it restarts every time the turn
# makes visible progress (a tool starts or completes) and every time an interactive
# card is answered — and only one continuous deliberation stretch longer than the
# budget is interrupted. A turn with a tool call every few minutes runs forever.
HERMES_SEGMENT_RESET_EVENTS = ("tool.start", "tool.complete")


def hermes_segment_resets(ev_type) -> bool:
    """PURE. Does this gateway event END the current unbroken-generation segment?

    Deliberately NOT message deltas: a spiralling model emits deltas continuously,
    so resetting on them would make the guard blind to the only failure it exists
    to catch. Tool lifecycle events are the honest "the turn is getting somewhere"
    signal (card resolution is the other, handled by the relay's pause bookkeeping).
    """
    return isinstance(ev_type, str) and ev_type.strip() in HERMES_SEGMENT_RESET_EVENTS


def hermes_segment_spent(now: float, started_at: float,
                         paused_total: float = 0.0, paused_since=None) -> float:
    """Segment time that COUNTS against the budget. PURE.

    Wall clock since the segment began (prompt.submit, or the last reset) MINUS
    every interval spent waiting on an interactive card (approval / clarify): a card
    that legitimately waits for Debi must never be shot. `paused_total` is the sum of
    closed pauses; `paused_since` is the start of the pause still open (None if not
    paused). Never negative.
    """
    spent = float(now) - float(started_at) - float(paused_total or 0.0)
    if paused_since is not None:
        spent -= max(0.0, float(now) - float(paused_since))
    return spent if spent > 0 else 0.0


def hermes_segment_overrun(spent_s: float, budget_s: float) -> bool:
    """Has this generation segment blown its budget? PURE.
    budget <= 0 = disabled = never."""
    try:
        b = float(budget_s)
        s = float(spent_s)
    except (TypeError, ValueError):
        return False
    if not (b > 0):
        return False
    return s >= b


def hermes_overrun_error(budget_s: float) -> str:
    """The exact user-facing line for an over-budget generation segment. PURE."""
    n = int(budget_s) if float(budget_s) == int(float(budget_s)) else float(budget_s)
    return (f"generation exceeded {n}s without a tool call or output — likely a "
            "deliberation loop; interrupted server-side (hermes.max_turn_s)")


async def _hermes_kill_segment(sid: str, spent_s: float, budget_s: float) -> None:
    """Stop the GENERATION for an over-budget segment + leave a durable trace.

    Best-effort by design: whether or not the RPC lands, the relay ends the turn
    (an unreachable gateway is exactly the case where the stream must still close).
    """
    print(f"[hermes] generation segment exceeded max_turn_s "
          f"({spent_s:.0f}s >= {budget_s:.0f}s) "
          f"— sending session.interrupt for {sid or '?'}", flush=True)
    try:
        await _HERMES.rpc("session.interrupt", {"session_id": sid}, timeout=10.0)
        print("[hermes] session.interrupt acknowledged", flush=True)
    except Exception as e:
        print(f"[hermes] session.interrupt FAILED: {str(e)[:200]}", flush=True)


async def _hermes_session_working(sid: str) -> bool:
    """Best-effort probe: is this gateway session still running a turn?

    Uses session.active_list (methods_session.py:942 → _session_live_item,
    server.py:8072, status ∈ waiting/starting/working/idle via _session_live_status,
    server.py:8040). Returns True on ANY doubt — a probe failure must never kill a
    live stream. A session that is absent or "idle" while our relay still waits means
    the turn ended WITHOUT a terminal event reaching us (e.g. interrupted from the
    Hermes dashboard) → the caller ends the turn.

    The status vocabulary is upstream-INTERNAL and a silent addition to it would cut
    live turns off, so it is now contract-pinned as an exact set
    (`test_active_list_status_vocabulary_is_unchanged`), closing the gap this
    docstring used to just flag. Re-verified unchanged at v2026.8.13.
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
                res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
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
                res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
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
            #   • hard guard: 600s of TOTAL silence still aborts (unchanged);
            #   • MAX GENERATION SEGMENT (hermes.max_turn_s, default 600s, 0 = off):
            #     time in ONE unbroken generation stretch — armed at submit, RESET on
            #     every tool.start / tool.complete and on every card resolution, and
            #     PAUSED while a card is pending. So a long research turn with tool
            #     calls runs forever; only a model talking to itself with nothing to
            #     show for it is cut. Checked on the EVENT path too — a runaway
            #     deliberation loop keeps emitting, so every silence-based guard is
            #     blind to it. Remedy is session.interrupt: the generation stops,
            #     not just the stream.
            got_any = False
            silent = 0.0
            noted_slow = False
            # Read ONCE, at submit: a config edit mid-turn must not retune a live
            # turn (same rule as the voice hangover read at capture time).
            try:
                max_turn = hermes_max_turn_s(cfg())
            except Exception:
                max_turn = HERMES_MAX_TURN_S_DEFAULT
            seg_started = asyncio.get_running_loop().time()
            pause_total = 0.0
            pause_since = None
            # An INTERACTIVE CARD awaits the user: a Phase-2 approval, or (2026-08-14)
            # a clarify/ask card. Both block the agent thread on a gateway prompt, so
            # neither is "silence" — the watchdogs must not read them as a dead turn.
            approval_pending = False
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
                    # HEARTBEAT (2026-08-14): one tiny frame per ~20s tick, in
                    # EVERY waiting branch (including a pending approval card,
                    # which can legitimately wait minutes). The panel does not
                    # render it — it exists so the panel's own last-resort stall
                    # watchdog can tell "the model is slow" from "the relay is
                    # gone". Without it the panel could only wait out the 600s
                    # hard guard, which is what "stuck forever" felt like.
                    yield 'data: {"type":"hermes_ping"}\n\n'
                    # Segment guard FIRST: it is the only one that also stops
                    # Hermes, so when two guards come due on the same tick the one
                    # that kills the generation should win.
                    _spent = hermes_segment_spent(
                        asyncio.get_running_loop().time(), seg_started,
                        pause_total, pause_since)
                    if hermes_segment_overrun(_spent, max_turn):
                        await _hermes_kill_segment(sid, _spent, max_turn)
                        yield ('data: {"type":"hermes_status","text":'
                               + _json.dumps(hermes_overrun_error(max_turn))
                               + '}\n\n')
                        yield ('data: '
                               + _json.dumps({"type": "proxy_error",
                                              "error": hermes_overrun_error(max_turn)})
                               + '\n\n')
                        break
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
                        # Phase 2 / ask cards: the card IS the status — suppress the
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
                # An approval.request OR a clarify.request opens a pending card;
                # ANY other event means the wait resolved (post-decision tool/turn
                # events only flow once resolve_gateway_approval / clarify.respond
                # unblocked the agent thread). clarify.expire is "any other event",
                # which is exactly right: an expired card is no longer pending.
                _was_pending = approval_pending
                approval_pending = ((ev or {}).get("type")
                                    in ("approval.request", "clarify.request"))
                # PAUSE the segment clock for the whole time a card is on screen:
                # a user deciding is not the model burning CPU, and shooting a turn
                # that is WAITING FOR DEBI would be the worst failure of this guard.
                _now = asyncio.get_running_loop().time()
                _resolved = False
                if approval_pending and not _was_pending:
                    pause_since = _now
                elif _was_pending and not approval_pending:
                    if pause_since is not None:
                        pause_total += max(0.0, _now - pause_since)
                        pause_since = None
                    _resolved = True
                # RESET the segment on visible progress: a tool starting or finishing,
                # or a card being answered, both mean this is not one unbroken
                # deliberation stretch. Runs BEFORE the end-of-body overrun check, so
                # a resetting event is never judged against the pre-reset clock.
                if _resolved or hermes_segment_resets((ev or {}).get("type")):
                    seg_started = _now
                    pause_total = 0.0
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
                # THE branch that matters for a runaway loop: a spiralling model
                # emits continuously, so this is the only place the guard can see
                # it (the timeout tick above never fires while events flow).
                _spent = hermes_segment_spent(asyncio.get_running_loop().time(),
                                              seg_started, pause_total, pause_since)
                if hermes_segment_overrun(_spent, max_turn):
                    await _hermes_kill_segment(sid, _spent, max_turn)
                    yield ('data: {"type":"hermes_status","text":'
                           + _json.dumps(hermes_overrun_error(max_turn)) + '}\n\n')
                    yield ('data: '
                           + _json.dumps({"type": "proxy_error",
                                          "error": hermes_overrun_error(max_turn)})
                           + '\n\n')
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


ASK_ANSWER_MAX = 4000   # chars accepted from the panel's free-text box


@app.post("/api/hermes/answer")
async def hermes_answer(req: Request) -> JSONResponse:
    """Answer a pending clarify/ask card.

    UNLIKE approvals, clarify prompts ARE addressed by id: _block mints a
    request_id and stamps it into the emitted payload
    (tui_gateway/server.py:2856-2862), and clarify.respond resolves purely on
    it — `_respond(rid, params, "answer", allow_expired=True)`
    (methods_prompt.py:836-842) reads params["request_id"] + params["answer"]
    and never looks at a session (server.py:9981-9992). So {request_id, answer}
    is the complete address; session_id is accepted for symmetry with
    /api/hermes/approve and for logging only.

    The ANSWER IS A PLAIN STRING — upstream stores it verbatim and the clarify
    tool returns it as user_response (tools/clarify_tool.py:170). There is no
    index protocol on the wire, so the panel sends the chosen option's LABEL.
    ⚠ PENDING FABLE QA: the brief said `choice_index?|text?`; there is no
    choice_index, because resolving one would mean the BRIDGE keeping a copy of
    the option list — duplicated gateway state whose staleness could answer a
    different question than the card on screen shows. The panel holds the list
    it rendered and sends the label, so what is answered is what was displayed.

    cancel:true sends the empty string, which is exactly what upstream's own
    cancel path does (_clear_pending sets the answer to "" — server.py:2922-2926).

    Result: {"ok":true,"status":"ok"|"expired"} — "expired" means the prompt was
    already gone gateway-side (timeout / interrupt), so the panel must stamp the
    card honestly instead of claiming the answer landed.
    """
    body = await req.json()
    rid = str(body.get("request_id") or "").strip()
    if not rid:
        return JSONResponse({"error": "request_id required"}, status_code=400)
    if body.get("cancel"):
        answer = ""
    else:
        answer = body.get("answer")
        if not isinstance(answer, str):
            return JSONResponse({"error": "answer must be a string"}, status_code=400)
        answer = answer.strip()
        if not answer:
            return JSONResponse({"error": "empty answer — use cancel:true to skip"},
                                status_code=400)
        if len(answer) > ASK_ANSWER_MAX:
            return JSONResponse({"error": f"answer too long (max {ASK_ANSWER_MAX})"},
                                status_code=400)
    try:
        res = await _HERMES.rpc("clarify.respond",
                                {"request_id": rid, "answer": answer}, timeout=10.0)
        return JSONResponse({"ok": True, "status": res.get("status") or "ok"})
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
        res = await _HERMES.rpc("session.create", {"source": HERMES_SESSION_SOURCE})
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
                                {"session_id": stored, "source": HERMES_SESSION_SOURCE},
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


async def _ody_mcp_list() -> list:
    """Odysseus's registered MCP servers. Raises when Odysseus is unreachable (the
    callers distinguish 'not registered' from 'we couldn't ask')."""
    r = await _ody_req("GET", "/api/mcp/servers")
    lst = r.json() if r.status_code == 200 else []
    return lst if isinstance(lst, list) else []


async def _ody_find_mcp(name: str):
    return next((s for s in await _ody_mcp_list() if s.get("name") == name), None)


# ── NAV generation (FABLE-STUDIO-PHASE2-SPEC §A) ─────────────────────────────
# The SAME carrier and the SAME shape as the Hermes generation below, for the same
# reason and with the same failure mode: the Swift shell cannot read the panel's
# localStorage, so it needs to know when the layout it drew is out of date. It reads
# `nav_gen` off /api/status (a route it already polls) and re-fetches /api/nav only
# when the number moved.
#
# PROCESS-LIFETIME again, and again deliberately: a bridge restart resets it to 0,
# which the shell records silently as a DECREASE rather than treating as a change —
# and it cannot be wrong to skip a refetch there, because nav.json on disk did not
# move while the bridge was down and the shell fetches it once at launch anyway.
_NAV_GEN = 0


def _nav_bump() -> int:
    global _NAV_GEN
    _NAV_GEN += 1
    return _NAV_GEN


def nav_gen() -> int:
    return _NAV_GEN


@app.get("/api/nav")
def api_nav_get() -> JSONResponse:
    """The layout the SHELL draws its tab strip from, and the panel's shared copy."""
    if _nav is None:
        return JSONResponse({"ok": False, "error": "nav module unavailable: " + _NAV_ERR},
                            status_code=503)
    return JSONResponse({"ok": True, "nav": _nav.read(ROOT), "gen": nav_gen(),
                         "max_topbar": _nav.NAV_TOPBAR_MAX, "ids": list(_nav.NAV_IDS)})


@app.post("/api/nav")
async def api_nav_set(req: Request) -> JSONResponse:
    """Save a layout. STRICT: normalize drops what this build cannot render, then
    validate REFUSES (400, with the reason) rather than quietly repairing — a save
    that silently did something else is how a customisation loses an entry."""
    if _nav is None:
        return JSONResponse({"ok": False, "error": "nav module unavailable: " + _NAV_ERR},
                            status_code=503)
    try:
        body = await req.json()
    except Exception:                                    # noqa: BLE001
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    raw = body.get("nav") if isinstance(body, dict) else None
    if raw is None:
        raw = body
    model = _nav.normalize(raw)
    err = _nav.validate(model)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        _nav.write(ROOT, model)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not save: {e}"}, status_code=500)
    gen = _nav_bump()
    return JSONResponse({"ok": True, "nav": model, "gen": gen})


# ── Hermes config generation ────────────────────────────────────────────────
# Hermes's own dashboard fetches its toolset/skill lists ONCE on mount
# (web/src/pages/SkillsPage.tsx:155-174 — the useEffect is keyed only on the
# profile) and patches its local state optimistically when ITS OWN switches are
# used (:180-186). A write made from THIS panel therefore leaves that page
# showing the state it had when it opened, and the shell's only reload rule was
# "backgrounded longer than staleAfter (600s)" — so within ten minutes of
# switching tabs the user is reading a frozen page and our lever looks broken.
#
# This counter is the signal that closes it: a monotonically increasing
# PROCESS-LIFETIME integer, bumped on every write WE make to Hermes's config
# surface, published on the EXISTING /api/status (the one endpoint the Swift
# shell already fetches — see portOpen in app/main.swift — so no new route and
# no new client). The shell records it when the Hermes webview loads and reloads
# that webview when it has increased since.
#
# PROCESS-LIFETIME is deliberate and sufficient: a bridge restart resets it to 0,
# which the shell reads as a DECREASE and records silently rather than treating
# as a change — so a restart can never cause a spurious reload. The shell also
# treats an absent/unparseable field as "no change", so an older bridge (or a
# bridge that is down) degrades to exactly today's behaviour.
_HERMES_CFG_GEN = 0


def _hermes_cfg_bump() -> int:
    """Record that we just changed Hermes's configuration; returns the new
    generation. Deliberately trivial: it is called immediately after a write that
    has ALREADY succeeded, so it must never be able to fail that write."""
    global _HERMES_CFG_GEN
    _HERMES_CFG_GEN += 1
    return _HERMES_CFG_GEN


def hermes_cfg_gen() -> int:
    """The current generation. 0 = we have written nothing this process."""
    return _HERMES_CFG_GEN


def _hermes_config_path() -> str:
    import os
    return os.path.join(os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes"),
                        "config.yaml")


def _hermes_write_mcp(name: str, entry: "dict | None") -> bool:
    """Add (entry) or remove (entry=None) ONE server in ~/.hermes/config.yaml's
    `mcp_servers`. No CLI (its prompts + live-connect would hang) and no connection
    attempt — Hermes reads the config at use-time, so it applies to NEW chats.
    Returns whether `name` is present afterwards.

    IDEMPOTENT: a no-op toggle doesn't rewrite the file at all, so the one write that
    does happen is the only one that loses comments/ordering (the accepted property of
    the yaml round-trip)."""
    import os
    home = os.path.dirname(_hermes_config_path())
    path = _hermes_config_path()
    if not os.path.exists(path):
        if entry is None:
            return False
        os.makedirs(home, exist_ok=True)
        data = {}
    else:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    servers = data.get("mcp_servers") or {}
    if entry is None:
        if name not in servers:
            return False                      # already absent — don't touch the file
        servers.pop(name, None)
    else:
        if servers.get(name) == entry:
            return True                       # already exact — don't touch the file
        servers[name] = dict(entry)
    data["mcp_servers"] = servers
    # Fable QA hardening: atomic write (temp + os.replace) so a concurrent save from
    # Hermes's own dashboard can never observe a half-written config.
    tmp = path + ".harness-tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)
    os.replace(tmp, path)
    # Reached ONLY on a real write (both no-op branches return above), so an
    # idempotent toggle does not move the generation and cannot cause a reload.
    _hermes_cfg_bump()
    return name in servers


def _hermes_set_mcp(enable: bool) -> bool:
    """Browse toggle: add/remove the browsermcp stdio server (unchanged behaviour —
    now expressed through the shared single-server writer)."""
    return _hermes_write_mcp(
        "browsermcp",
        {"command": "npx", "args": ["@browsermcp/mcp"]} if enable else None)


def _hermes_get_mcp(name: str) -> "dict | None":
    try:
        with open(_hermes_config_path()) as f:
            data = yaml.safe_load(f) or {}
        srv = (data.get("mcp_servers") or {}).get(name)
        return srv if isinstance(srv, dict) else ({} if srv is not None else None)
    except Exception:
        return None


def _hermes_has_mcp(name: str = "browsermcp") -> bool:
    return _hermes_get_mcp(name) is not None


# ── Hermes TOOLSET TRIMMING LEVER ────────────────────────────────────────────
# WHY: the Hermes lane hands the model every enabled toolset's schema PLUS the whole
# skill index, which on a small local model is minutes of prefill before a single
# token comes back. Trimming the toolset list is the lever.
#
# THE MECHANISM, read out of the pin (v2026.8.13), not guessed:
#   • Our lane is the dashboard's JSON-RPC gateway (tui_gateway). It resolves the
#     model's toolsets in `_load_enabled_toolsets()` (tui_gateway/server.py:4267),
#     consumed per session build at server.py:6708 — via
#     `_get_platform_tools(cfg, "cli", include_default_mcp_servers=True)`
#     (server.py:4399). So the key is `platform_toolsets.cli`, NOT some `tools.*`
#     key: `tools.disabled_toolsets` / `enabled_toolsets` / `toolsets.enabled` DO
#     NOT EXIST. (Top-level `toolsets:` exists but is vestigial — only kanban and
#     `hermes dump` read it.)
#   • ⚠️ v2026.8.13 PARAMETERISED that resolver — `_load_enabled_toolsets(platform)`
#     — and the argument is a TRAP for a reader skimming it: it is the SESSION'S
#     SOURCE (`session.create`'s `source` field, resolved by `_resolve_agent_platform`
#     → `_resolve_session_source`, server.py:3685-3699), NOT the
#     `platform_toolsets.<x>` config key. The config read on line 4399 is still
#     HARDCODED `"cli"`. The session source only picks the CLIENT-SURFACE toolsets
#     folded in on top (`_gui_surface_toolsets`, server.py:4246 — see
#     HERMES_GATEWAY_ALWAYS_TOOLSET below). So this lever's key is unchanged.
#   • `_get_platform_tools` (hermes_cli/tools_config.py:2262) has NO memoisation and
#     `load_config()` is mtime+size keyed (hermes_cli/config.py:3105), and
#     `get_tool_definitions`'s own memo key includes the config mtime
#     (model_tools.py:320-336) — so a config edit takes effect on the NEXT CHAT
#     with NO Hermes restart. That is why this endpoint never asks for one.
#   • `agent.disabled_toolsets` (default [], config_defaults.py:228) is subtracted
#     LAST (tools_config.py:2530) — we never write it, but we REPORT it,
#     because a name sitting in there can never be re-enabled from this panel.
#   • `agent.coding_context: "focus"` (default "auto", config_defaults.py:131) makes
#     `coding_selection()` return a toolset list and `_load_enabled_toolsets()`
#     RETURNS EARLY (server.py:4285-4293) — the config list is then never read at
#     all. Only `focus` does this (agent/coding_context.py:517-521), so the default
#     is safe, but we detect it and say so rather than showing dead switches.
#
# WRITES GO THROUGH HERMES'S OWN WRITER, not our yaml round-trip:
#   `PUT /api/tools/toolsets/{name}` (hermes_cli/web_routers/tools.py:123) does
#   load_config → `_get_platform_tools(..., include_default_mcp_servers=False)` →
#   add/discard → `_save_platform_tools` (tools_config.py:2560) → `save_config`
#   (strip_defaults=True, atomic_yaml_write). That helper is the only thing that
#   knows to preserve MCP-server names parked in the same list, to route
#   platform-restricted toolsets (discord → platform_toolsets.discord), and to keep
#   the `known_*_toolsets` bookkeeping coherent. Reimplementing it here would be a
#   SECOND writer of the same key that could drift from upstream at any pin bump.
#   The price is that writing needs Hermes RUNNING — the same precedent the voice
#   MCP rows already set (a switch that cannot work is disabled, not silently
#   ineffective).
HERMES_MINIMAL_TOOLSETS = ("file", "terminal", "clarify")

# ── WHICH ROWS THIS LEVER ACTUALLY GOVERNS ───────────────────────────────────
# `GET /api/tools/toolsets` returns EVERY configurable toolset, but three kinds of
# row live in that one list and only one of them reaches this harness's chat lane:
#
#  1. ordinary rows — `platform: "cli"`, persisted to `platform_toolsets.cli`,
#     which is exactly what our lane resolves (`_get_platform_tools(cfg, "cli")`,
#     tui_gateway/server.py:4399). THESE are the lever.
#  2. platform-restricted rows — `_TOOLSET_PLATFORM_RESTRICTIONS`
#     (tools_config.py:216-220) pins `discord`/`discord_admin` to the discord
#     platform, so `_toolset_configuration_platform` (tools_config.py:231) makes
#     their row `platform: "discord"` and their PUT writes
#     `platform_toolsets.discord`. `_toolset_allowed_for_platform` (:222) means
#     they can NEVER be enabled for cli — the model in this lane cannot get their
#     tools no matter what the switch says.
#  3. config-only rows — `_CONFIG_ONLY_TOOLSETS` (tools_config.py:165). `stt` is
#     not a model toolset at all: its row's `enabled` is read from `config.stt.
#     enabled` and its PUT writes that key (web_routers/tools.py:97-104, 148-158).
#     It ships ZERO tool schemas, so switching it off saves nothing in the prompt
#     — and switching it off breaks Hermes's speech-to-text.
#
# Presets, the headline count and the Check card are all scoped to (1). Rows of
# kind (2)/(3) still RENDER — hiding a switch Hermes shows would be its own lie —
# but they are labelled for what they are and no preset touches them.
HERMES_LEVER_PLATFORM = "cli"

# Mirrors `_CONFIG_ONLY_TOOLSETS` (hermes_cli/tools_config.py:165). Contract-pinned
# byte-identical, so a pin bump that adds one trips instead of silently letting a
# preset write a config section.
HERMES_CONFIG_ONLY_TOOLSETS = ("stt",)

# Mirrors `_DEFAULT_OFF_TOOLSETS` (hermes_cli/tools_config.py:156) — the toolsets
# upstream deliberately keeps OFF on a fresh install, subtracted from the composite
# expansion in `_get_platform_tools` (tools_config.py:2336-2344 mixed-config branch,
# 2386-2411 implicit branch).
#
# This exists because "Everything back on" was NOT "back on": it sent every name in
# the catalog, which turned on seven toolsets Hermes had never had on — Video
# Analysis among them. Debi's report ("our rows showed video-analysis ON while I
# never enabled it") is exactly that button. The preset now restores HERMES'S OWN
# default set; anything in here stays an explicit, per-row opt-in.
#
# Contract-pinned byte-identical against upstream's set, so a release that adds or
# removes a default-off toolset trips a test rather than drifting quietly — and at
# the v2026.7.30 → v2026.8.13 bump it DID: upstream added `a2a`. Left stale, the
# "Hermes's defaults" preset would have switched a2a ON, which is the same defect
# this constant exists to prevent, one release later.
#
# `a2a` is a BUNDLED PLATFORM PLUGIN (vendor/hermes/plugins/platforms/a2a/), not a
# built-in toolset — it is absent from both `toolsets.py` and CONFIGURABLE_TOOLSETS,
# and reaches the catalog only through `_get_effective_configurable_toolsets`
# (tools_config.py:245-268), which appends whatever plugin toolsets are LOADED.
# Bundled platform plugins are registered as DEFERRED loaders (plugins.py:3855) and
# only import on first use, so the row is normally absent — the staleness was latent,
# not live. The mirror is corrected anyway: "normally absent" is not "cannot appear",
# and a preset must never be able to go past Hermes's own defaults.
HERMES_DEFAULT_OFF_TOOLSETS = ("homeassistant", "spotify", "discord",
                               "discord_admin", "video", "video_gen", "x_search",
                               "a2a")

# `platform_toolsets.cli: []` is a FOOTGUN, not a "no tools" setting: with an empty
# list `has_explicit_config` is False (tools_config.py:2301), the else-branch expands
# nothing, and `_load_enabled_toolsets` turns an empty result into `return None`
# (server.py:4402-4403) — which `get_tool_definitions` reads as ENABLE EVERYTHING.
# Disabling the last toolset would therefore hand the model MORE tools than it had.
HERMES_TOOLSETS_EMPTY_REASON = (
    "at least one toolset must stay on — Hermes reads an empty list as "
    "“all toolsets”, so this would give the model more tools, not fewer")


def hermes_toolset_names(rows) -> list:
    """PURE. Toolset names out of a /api/tools/toolsets payload, order preserved."""
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if isinstance(r, dict):
            n = r.get("name")
            if isinstance(n, str) and n.strip():
                out.append(n.strip())
    return out


def hermes_toolsets_enabled(rows) -> list:
    """PURE. The subset currently reported ENABLED (upstream already accounted for
    _DEFAULT_OFF_TOOLSETS and agent.disabled_toolsets when it built this)."""
    return [r.get("name").strip() for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str)
            and r["name"].strip() and r.get("enabled")]


def hermes_toolset_platform(row) -> str:
    """PURE. A row's CONFIGURATION platform — the `platform_toolsets.<x>` key its
    PUT writes (web_routers/tools.py:100, from `_toolset_configuration_platform`).

    Fails OPEN to `cli`: a build that omits the field is far more likely to be an
    ordinary cli row than a platform-restricted one, and treating an unknown row as
    out-of-scope would silently drop it from the preset and the count."""
    if not isinstance(row, dict):
        return HERMES_LEVER_PLATFORM
    p = str(row.get("platform") or "").strip()
    return p or HERMES_LEVER_PLATFORM


def hermes_toolset_is_lever(row) -> bool:
    """PURE. Does this row control the toolsets THIS lane hands the model?

    True only for rows persisted to `platform_toolsets.cli` that are real model
    toolsets. See the HERMES_LEVER_PLATFORM block above for the three row kinds."""
    if not isinstance(row, dict) or not isinstance(row.get("name"), str):
        return False
    name = row["name"].strip()
    if not name or name in set(HERMES_CONFIG_ONLY_TOOLSETS):
        return False
    return hermes_toolset_platform(row) == HERMES_LEVER_PLATFORM


def hermes_lever_names(rows) -> list:
    """PURE. The subset of names this lever governs, in payload order."""
    return [r["name"].strip() for r in (rows if isinstance(rows, list) else [])
            if hermes_toolset_is_lever(r)]


def hermes_lever_enabled(rows) -> list:
    """PURE. Lever rows currently reported ENABLED — the honest "what is on in this
    lane" set. `hermes_toolsets_enabled` (all rows) is kept for the raw report."""
    return [r["name"].strip() for r in (rows if isinstance(rows, list) else [])
            if hermes_toolset_is_lever(r) and r.get("enabled")]


def hermes_preset_desired(rows, preset: str):
    """PURE. Resolve a preset chip to a desired-enabled set over the LEVER rows only
    (never a discord-platform row, never the config-only `stt` switch), INTERSECTED
    with what this Hermes build actually offers (so a renamed/removed toolset
    upstream cannot make a preset write a name the dashboard would 400 on).

    `all` means HERMES'S OWN DEFAULT SET, not every row: `_DEFAULT_OFF_TOOLSETS`
    (tools_config.py:155) is what upstream subtracts when it expands the `hermes-cli`
    composite, so "restore Hermes's full surface" has to subtract it too. Sending
    every name instead is what silently turned Video Analysis on.

    Returns None for an unknown preset — callers must treat that as a 400, never as
    'no change' (silently doing nothing to a tool surface is the wrong failure)."""
    names = hermes_lever_names(rows)
    p = (preset or "").strip().lower()
    if p == "minimal":
        return [n for n in names if n in set(HERMES_MINIMAL_TOOLSETS)]
    if p in ("all", "everything", "default", "defaults"):
        return [n for n in names if n not in set(HERMES_DEFAULT_OFF_TOOLSETS)]
    return None


def hermes_toolset_result(rows, desired, scope=None) -> set:
    """PURE. The LEVER set that would be enabled after applying `desired` within
    `scope` — i.e. what `platform_toolsets.cli` would report next read.

    Rows outside `scope` keep whatever Hermes reports today; rows inside it take
    their membership of `desired`. This is what the empty-list guard has to test:
    the old guard tested `desired` against ALL known names, so an enabled `stt`
    row (config-only, zero schemas) or a discord row was enough to satisfy it while
    every real cli toolset went off — the exact footgun it exists to prevent."""
    lever = set(hermes_lever_names(rows))
    want = {n for n in (desired or []) if isinstance(n, str)}
    sc = lever if scope is None else ({str(s) for s in scope} & lever)
    return (set(hermes_lever_enabled(rows)) - sc) | (want & sc)


def hermes_toolsets_valid(rows, desired, scope=None) -> str:
    """PURE. '' when `desired` is a safe target, else the honest reason string.
    Unknown names are NOT fatal here (they are dropped + reported by the plan)."""
    if not hermes_toolset_names(rows):
        return "Hermes reported no configurable toolsets"
    if not hermes_lever_names(rows):
        return "Hermes reported no toolsets for this chat lane"
    if not hermes_toolset_result(rows, desired, scope):
        return HERMES_TOOLSETS_EMPTY_REASON
    return ""


def hermes_toolset_plan(rows, desired, scope=None):
    """PURE. The minimal set of upstream PUTs to reach `desired`.

    Returns {"plan": [(name, enabled), ...], "unknown": [...], "unchanged": n}.
    Only toolsets whose state actually CHANGES are in the plan, so re-applying a
    preset is zero writes and each write is one atomic upstream save.

    `scope` bounds which rows may change. Default = the LEVER rows, so a preset can
    never reach a discord-platform row (whose PUT writes `platform_toolsets.discord`)
    or the config-only `stt` switch (whose PUT writes `config.stt.enabled` and would
    disable Hermes's speech-to-text for zero prompt saving). A single-row toggle
    passes its own name as the scope, so those rows stay flippable ON PURPOSE."""
    want = {n for n in (desired or []) if isinstance(n, str)}
    known = set(hermes_toolset_names(rows))
    now = set(hermes_toolsets_enabled(rows))
    lever = hermes_lever_names(rows)
    names = lever if scope is None else [n for n in hermes_toolset_names(rows)
                                         if n in {str(s) for s in scope}]
    plan, unchanged = [], 0
    for name in names:                            # stable, payload order
        target = name in want
        if target == (name in now):
            unchanged += 1
        else:
            plan.append((name, target))
    return {"plan": plan, "unknown": sorted(want - known), "unchanged": unchanged}


def hermes_toolset_view(rows, skills=None, cfg=None) -> dict:
    """PURE. Panel-shaped view of the probe: per-row tool COUNTS (real, from the
    payload's own resolved tool list) and the aggregate.

    Deliberately NO token estimate: the probe carries tool NAMES, not schemas, so
    any per-toolset token figure would be invented. Counts are the honest proxy.

    Also carries `needs_setup` — see the field comment below for its provenance and
    its one honest weakness (it is upstream's optimistic bool, not upstream's own
    accurate `_toolset_needs_configuration_prompt`, which is not exposed over HTTP)."""
    out, en_tools, all_tools = [], 0, 0
    for r in (rows if isinstance(rows, list) else []):
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        tools = [t for t in (r.get("tools") or []) if isinstance(t, str)]
        on = bool(r.get("enabled"))
        lever = hermes_toolset_is_lever(r)
        # The headline totals are about THIS lane's prompt, so only lever rows count:
        # a discord-platform row's tools can never reach a cli session
        # (`_toolset_allowed_for_platform`, tools_config.py:222) and the config-only
        # `stt` row has no schemas at all. Counting them made the number bigger than
        # anything the model would ever see.
        if lever:
            all_tools += len(tools)
            if on:
                en_tools += len(tools)
        out.append({"name": r["name"].strip(),
                    "label": str(r.get("label") or r["name"]).strip(),
                    "description": str(r.get("description") or "").strip(),
                    "platform": hermes_toolset_platform(r),
                    "platform_label": str(r.get("platform_label")
                                          or hermes_toolset_platform(r)).strip(),
                    "lever": lever,
                    "config_only": r["name"].strip() in set(HERMES_CONFIG_ONLY_TOOLSETS),
                    "default_off": r["name"].strip() in set(HERMES_DEFAULT_OFF_TOOLSETS),
                    "enabled": on, "tools": tools, "tool_count": len(tools),
                    # UPSTREAM's OWN setup signal, mirrored not invented: the row's
                    # `configured` bool (web_routers/tools.py:107, produced by
                    # tools_config._toolset_has_keys:2589) is the same field Hermes's
                    # Skills→TOOLSETS page shows its amber "Setup needed" caption from
                    # (web/src/pages/SkillsPage.tsx:606). Fail OPEN — only an EXPLICIT
                    # False is a warning, so a build that omits the key (or a probe
                    # shape we do not know) can never invent a scary pill.
                    "needs_setup": r.get("configured") is False,
                    # Filled in below from the persisted intent; "" = agrees.
                    "drift": ""})
    off = {d["name"] for d in hermes_toolset_drift(rows, cfg)}
    for t in out:
        if t["name"] in off:
            t["drift"] = "off"
    sk = skills if isinstance(skills, dict) else {}
    return {"toolsets": out,
            "platform": HERMES_LEVER_PLATFORM,
            "enabled_count": sum(1 for r in out if r["enabled"] and r["lever"]),
            "total": sum(1 for r in out if r["lever"]),
            "other_count": sum(1 for r in out if not r["lever"]),
            "tool_count_enabled": en_tools,
            "tool_count_total": all_tools,
            "out_of_sync": sorted(off),
            "skills": {"count": int(sk.get("count") or 0),
                       "disabled_count": int(sk.get("disabled_count") or 0)}}


# ── DO OUR SWITCHES MATCH WHAT HERMES HANDS THE MODEL? ───────────────────────
# The reason this exists: a switch that reports OUR intent rather than Hermes's
# behaviour is exactly the doubt this panel has to kill. Every row above already
# RENDERS Hermes's own `enabled` field (web_routers/tools.py:97, computed by
# `_get_platform_tools`, tools_config.py:2262) — never our last write — so the
# switch itself cannot lie. What was missing is the WHY when the two disagree.

# The gateway folds CLIENT-SURFACE toolsets in on the resolve path our lane takes,
# on top of whatever `platform_toolsets.cli` says — so their tools are in the
# model's schema no matter what this panel does, and the summary reports them
# SEPARATELY rather than quietly under-reporting.
#
# ⚠️ v2026.8.13 replaced the flat `return sorted(enabled | {"project"})` with
# `return sorted(enabled | _gui_surface_toolsets(session_platform))`
# (tui_gateway/server.py:4410; the focus-mode early return folds the same set at
# :4293). `_gui_surface_toolsets` (server.py:4246-4264) is:
#
#     surfaces = {"project"}
#     if platform == "desktop": surfaces.add("desktop_ui")
#
# i.e. `project` is STILL unconditional, and `desktop_ui` is added ONLY for a
# session whose SOURCE is the desktop app. Ours is not: every session.create /
# session.resume this bridge issues sends `source: HERMES_SESSION_SOURCE`
# ("harness"), and `_resolve_session_source` (server.py:3685-3695) returns an
# explicit source VERBATIM. So our lane's fold is exactly {"project"} and the
# count below is still complete.
#
# That is worth stating plainly because it is load-bearing and NOT obvious:
# `start_component.sh` launches the dashboard with HERMES_DESKTOP=1 (for the cron
# ticker), and HERMES_DESKTOP=1 is precisely what `_resolve_session_platform`
# (server.py:3659-3682) turns into "desktop" when no source is given. Our explicit
# source is the ONLY thing keeping this lane off the desktop surface — which is the
# right side to be on twice over: those 8 tools (read_terminal, open_preview,
# focus_pane, …) need a GUI renderer our panel does not implement, so inheriting
# them would both break the count and hand the model tools it cannot use.
# Contract-pinned in both directions.
#
# `project` is NOT in CONFIGURABLE_TOOLSETS (tools_config.py:95-122), so it has no
# row and no switch. (toolsets.py:260-264.)
HERMES_GATEWAY_ALWAYS_TOOLSET = "project"
HERMES_GATEWAY_ALWAYS_TOOLS = ("project_list", "project_create", "project_switch")

# The `source` every Hermes session this bridge opens is tagged with. Named rather
# than repeated as a literal because it is not cosmetic: it selects the session's
# PLATFORM (server.py:3685-3699), which decides the client-surface fold above.
HERMES_SESSION_SOURCE = "harness"

# Upstream gates the ENTIRE <available_skills> block on these three tool names
# being in the schema — `has_skills_tools` (agent/system_prompt.py:412), else
# `skills_prompt = ""` (:440). Hermes's own banner uses the toolset name for the
# same purpose (`"skills" in _enabled_ts`, hermes_cli/banner.py:1058, which then
# reports `0 skills` and "Skills toolset disabled"). We test the TOOL NAMES, so
# a rename of the toolset key cannot make us claim an index that is not there.
HERMES_SKILL_INDEX_TOOLS = ("skills_list", "skill_view", "skill_manage")


def hermes_toolset_drift(rows, cfg) -> list:
    """PURE. Toolsets we ASKED Hermes for that Hermes does NOT report as enabled.

    INTENT is the PERSISTED one: every write goes through Hermes's own
    `PUT /api/tools/toolsets/{name}` → `_save_platform_tools` (tools_config.py:2560),
    so `platform_toolsets.cli` on disk IS the record of what this panel asked for.
    TRUTH is the probe's `enabled`. A disagreement is real and is worth naming —
    `agent.disabled_toolsets` is subtracted LAST (tools_config.py:2530) and
    `agent.coding_context: "focus"` short-circuits the list entirely
    (tui_gateway/server.py:4285) — both of which silently override a switch.

    ONE DIRECTION ONLY, and that is deliberate: "listed but Hermes says off" is
    unambiguous, while "enabled but not in our list" has legitimate causes we
    cannot distinguish from the payload — a composite name like `hermes-cli`
    sitting in the same list expands to more toolsets (tools_config.py:2315-2344),
    and the config-only toolsets (`_CONFIG_ONLY_TOOLSETS = {"stt"}`,
    tools_config.py:165) are enabled by their own config section and never appear
    in the list at all. Flagging those would be a false alarm, and a false
    "out of sync" pill is worse than none. The other direction is covered
    panel-side by our own in-session intent, which cannot be wrong about itself.

    Fails OPEN in every unknown: no saved list (None = never configured) ⇒ no
    claim; a row this lever does not govern ⇒ skipped, because a platform-restricted
    toolset persists to its own key (`_toolset_configuration_platform`,
    tools_config.py:231) and a config-only row (`stt`) is not in
    `platform_toolsets` at all — its `enabled` comes from `config.stt.enabled`
    (web_routers/tools.py:97-104), so comparing it against the cli list would flag
    every install that has ever saved one."""
    cfg = cfg if isinstance(cfg, dict) else {}
    cli = cfg.get("platform_toolsets_cli")
    if not isinstance(cli, list):
        return []
    want = {str(x).strip() for x in cli if str(x).strip()}
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if not hermes_toolset_is_lever(r):
            continue
        name = r["name"].strip()
        if name not in want:
            continue
        if not r.get("enabled"):
            out.append({"name": name, "intent": True, "reported": False})
    return out


def hermes_tool_summary(rows, skills=None) -> dict:
    """PURE. "What will Hermes actually hand the model?" — computed from the same
    payload Hermes's own Skills→TOOLSETS page renders, so it can be checked in one
    click without cross-referencing two apps.

    The union is de-duplicated because toolsets overlap (`resolve_toolset`,
    toolsets.py:756, composes and dedups the same way), and the gateway's
    client-surface fold is reported SEPARATELY rather than hidden inside the
    number — it is real, it is in the prompt, and no switch here controls it. For
    this lane that fold is exactly `project`; see HERMES_GATEWAY_ALWAYS_TOOLSET
    above for why `desktop_ui` is not in it.

    Counts the LEVER rows only, and that is a correction not a narrowing: this lane
    resolves `_get_platform_tools(cfg, "cli")` (tui_gateway/server.py:4399), so a
    row whose configuration platform is `discord` can never contribute a schema here
    (`_toolset_allowed_for_platform`, tools_config.py:222) and the config-only `stt`
    row ships none at all (tools_config.py:165). Counting them made the card claim
    tools the model would never see.

    HONEST LIMIT carried in the payload as `excludes_mcp`: the listing endpoint
    resolves with `include_default_mcp_servers=False` (web_routers/tools.py:82)
    while the runtime resolve uses True (tui_gateway/server.py:4399), so tools
    coming from connected MCP servers are NOT counted here."""
    en, tools = [], []
    seen = set()
    for r in (rows if isinstance(rows, list) else []):
        if not hermes_toolset_is_lever(r):
            continue
        if not r.get("enabled"):
            continue
        en.append(r["name"].strip())
        for t in (r.get("tools") or []):
            if isinstance(t, str) and t.strip() and t.strip() not in seen:
                seen.add(t.strip())
                tools.append(t.strip())
    extra = [t for t in HERMES_GATEWAY_ALWAYS_TOOLS if t not in seen]
    sk = skills if isinstance(skills, dict) else {}
    return {
        "toolsets": sorted(en),
        "tools": sorted(tools),
        "platform": HERMES_LEVER_PLATFORM,
        "tool_count": len(tools) + len(extra),
        "from_toolsets_count": len(tools),
        "always": {"toolset": HERMES_GATEWAY_ALWAYS_TOOLSET,
                   "tools": list(extra)},
        # Exactly upstream's own predicate, on tool NAMES not a toolset name.
        "skill_index": any(t in seen for t in HERMES_SKILL_INDEX_TOOLS),
        "skill_count": int(sk.get("count") or 0),
        "excludes_mcp": True,
    }


def hermes_skills_summary(payload) -> dict:
    """PURE. Count skills out of the dashboard's /api/skills payload. Accepts a bare
    list or {"skills": [...]} and never raises on a surprise shape — a broken count
    must not blank the group."""
    rows = payload.get("skills") if isinstance(payload, dict) else payload
    rows = rows if isinstance(rows, list) else []
    rows = [r for r in rows if isinstance(r, dict)]
    return {"count": len(rows),
            "disabled_count": sum(1 for r in rows if r.get("enabled") is False)}


# ── PER-SKILL TRIMMING — THE FINE INSTRUMENT BESIDE THE `skills` SWITCH ───────
# The `skills` TOOLSET switch above is the blunt one: it drops three tool schemas
# and with them the ENTIRE <available_skills> block (upstream gates the block on
# skills_list/skill_view/skill_manage being in the schema, agent/system_prompt.py:412).
# This lever shrinks that block instead of removing it — disable the skills the
# model does not need and the index gets smaller, one line at a time.
#
# WRITES GO THROUGH HERMES'S OWN API, exactly like the toolset lever:
#   `PUT /api/skills/toggle {"name": ..., "enabled": bool}`
#   (hermes_cli/web_routers/skills.py:426-437 → `get_disabled_skills` /
#    `save_disabled_skills`, hermes_cli/skills_config.py:44-72; body model
#    `SkillToggle`, hermes_cli/web_models.py:604-607). Same reasoning recorded for
#   the toolsets: upstream's writer is the only thing that keeps its own key
#   coherent, and a second writer of `skills.disabled` would drift at a pin bump.
#   The price is identical too — writing needs Hermes RUNNING.
#
# THE RECORDED NAME GOTCHA IS DISCHARGED BY NEVER MAPPING A NAME.
#   Memory records "the names stored there are frontmatter names not directory
#   names". Re-read at this pin, the picture is both softer and simpler:
#     • the listing's `name` IS `frontmatter.get("name", skill_dir.name)`
#       (tools/skills_tool.py:737) — frontmatter name, falling back to the dir name;
#     • the prompt builder skips a skill when EITHER matches —
#       `if frontmatter_name in disabled or skill_name in disabled`
#       (agent/prompt_builder.py:1654 snapshot path, :1676 cold path, :1759).
#   So the only safe rule is the one we already follow for toolsets: take every
#   name off upstream's OWN listing and post it back verbatim. We never derive a
#   name from a path, a label or a heuristic, and therefore cannot get this wrong.
#
# SCOPE IS GLOBAL, NOT `cli` — AND THAT IS UPSTREAM'S CHOICE, NOT OURS.
#   `SkillToggle` carries no platform and the handler calls
#   `save_disabled_skills(config, disabled)` with no platform argument, which
#   writes `skills.disabled` (skills_config.py:64-72) — the GLOBAL list. Hermes
#   does have a per-platform list (`skills.platform_disabled.<platform>`,
#   agent/skill_utils.py:448-455) but its dashboard never writes it, and neither
#   do we: a second writer for a key upstream's own UI cannot produce would be the
#   drift this whole approach exists to avoid. The consequence is real and is
#   NAMED in the UI — a skill switched off here is off on every Hermes surface,
#   not just this chat lane. The global list is unioned into every platform's
#   resolution (`global_disabled | platform_disabled`, skill_utils.py:454), so a
#   global write always reaches our lane; it just reaches the others too.
HERMES_SKILL_TOGGLE_PATH = "/api/skills/toggle"

# Upstream's DEFAULT disabled-skill set. `config_defaults.py:1682`'s `skills`
# block has external_dirs / template_vars / inline_shell / inline_shell_timeout /
# guard_agent_created / write_approval and NO `disabled` key at all, so
# `get_disabled_skills` returns an empty set on a fresh install: Hermes ships
# every installed skill ENABLED.
#
# This constant exists so "restore Hermes's defaults" restores UPSTREAM's set
# rather than our idea of one. It is contract-pinned: the day a release ships a
# default `skills.disabled`, the test trips and this chip gets fixed instead of
# quietly switching on skills Hermes deliberately keeps off — which is exactly
# the bug "Everything back on" had on the toolset lever.
HERMES_SKILL_DEFAULT_DISABLED = ()


def hermes_skill_rows(payload) -> list:
    """PURE. Normalise `GET /api/skills` into panel rows.

    Shape read from hermes_cli/web_routers/skills.py:394-423 — the handler returns
    a bare LIST of `_find_all_skills` dicts (name/description/category) annotated
    with `enabled` (:416), `usage` (:417) and `provenance` (:418-422). A dict
    wrapper is accepted too, so a future envelope does not blank the list.

    Total by construction: a surprise element type is dropped, a nameless row is
    dropped, and nothing raises — a broken row must not take the group with it."""
    rows = payload.get("skills") if isinstance(payload, dict) else payload
    out = []
    for r in (rows if isinstance(rows, list) else []):
        if not isinstance(r, dict) or not isinstance(r.get("name"), str):
            continue
        name = r["name"].strip()
        if not name:
            continue
        out.append({
            "name": name,
            "description": str(r.get("description") or "").strip(),
            "category": str(r.get("category") or "").strip() or "uncategorized",
            "provenance": str(r.get("provenance") or "").strip(),
            # Upstream computes this as `name not in disabled` (skills.py:416), so
            # it is Hermes's own answer and is re-read on every load — never our
            # last write. Fail OPEN: only an explicit False is "off", so a build
            # that omits the field can never make the whole library look disabled.
            "enabled": r.get("enabled") is not False,
        })
    return out


def hermes_skill_names(rows) -> list:
    """PURE. Every skill name in the payload, order preserved."""
    return [r["name"] for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]]


def hermes_skills_on(rows) -> list:
    """PURE. The subset Hermes reports ENABLED (i.e. not in `skills.disabled`)."""
    return [r["name"] for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"]
            and r.get("enabled") is not False]


def hermes_skill_lane_off(rows, cfg) -> list:
    """PURE. Skills the listing reports ENABLED that this lane will NOT see.

    `GET /api/skills` computes `enabled` from `get_disabled_skills(config)` with NO
    platform (skills.py:406) — the GLOBAL list only. Our lane resolves
    `get_disabled_skill_names(platform)` = global ∪ `platform_disabled[platform]`
    (agent/skill_utils.py:448-455), so a name parked in
    `skills.platform_disabled.cli` is absent from THIS prompt while Hermes's own
    page shows it on. That is exactly the class of silent disagreement the toolset
    lever was built to surface, so it is surfaced here too.

    ONE DIRECTION ONLY, for the same reason as `hermes_toolset_drift`: "the
    listing says on, our lane says off" is unambiguous, while the reverse cannot
    happen at all (the platform list only ADDS). Fails OPEN in every unknown —
    no key, a non-list, a junk cfg ⇒ NO claim, because a scary pill on a healthy
    install is worse than none."""
    cfg = cfg if isinstance(cfg, dict) else {}
    pd = cfg.get("skills_platform_disabled_cli")
    if not isinstance(pd, list):
        return []
    hidden = {str(x).strip() for x in pd if str(x).strip()}
    if not hidden:
        return []
    return [n for n in hermes_skills_on(rows) if n in hidden]


def hermes_skill_preset_desired(rows, preset: str):
    """PURE. Resolve a preset chip to a desired-enabled set over the real catalog.

    `defaults` = HERMES'S OWN default set (every installed skill minus
    HERMES_SKILL_DEFAULT_DISABLED, which is empty at this pin and contract-pinned
    so it stays honest), NOT "everything we can think of".
    `none` = the empty set, which is legal here: unlike `platform_toolsets.cli`
    (where `[]` means ENABLE EVERYTHING — the footgun HERMES_TOOLSETS_EMPTY_REASON
    exists for), a fully-populated `skills.disabled` just means an empty index.

    Returns None for an unknown preset — the caller must 400, never treat it as
    'no change'."""
    names = hermes_skill_names(rows)
    p = (preset or "").strip().lower()
    if p in ("all", "defaults", "default", "everything"):
        return [n for n in names if n not in set(HERMES_SKILL_DEFAULT_DISABLED)]
    if p in ("none", "off"):
        return []
    return None


def hermes_skills_valid(rows, desired, scope=None) -> str:
    """PURE. '' when `desired` is a safe target, else the honest reason.

    Deliberately has NO empty-set refusal (see hermes_skill_preset_desired): with
    skills, "none enabled" is a legitimate, reversible state that makes the index
    empty. The only refusal is an empty CATALOG — writing names against a listing
    we never got would be writing blind."""
    if not hermes_skill_names(rows):
        return "Hermes reported no skills"
    return ""


def hermes_skill_plan(rows, desired, scope=None):
    """PURE. The minimal set of upstream PUTs to reach `desired`.

    Returns {"plan": [(name, enabled), ...], "unknown": [...], "unchanged": n}.
    Only skills whose state actually CHANGES are written, so re-applying a preset
    costs zero upstream calls and a bulk action over a filtered list only touches
    the rows that were not already in the wanted state.

    `scope` bounds which rows may change (a single switch passes its own name; a
    bulk action passes the names it displayed). Default = the whole catalog."""
    def _seq(x):
        return x if isinstance(x, (list, tuple, set, frozenset)) else []
    want = {n for n in _seq(desired) if isinstance(n, str)}
    known = hermes_skill_names(rows)
    kset = set(known)
    now = set(hermes_skills_on(rows))
    names = known if scope is None else [n for n in known
                                         if n in {str(s) for s in _seq(scope)}]
    plan, unchanged = [], 0
    for name in names:                                # stable, payload order
        target = name in want
        if target == (name in now):
            unchanged += 1
        else:
            plan.append((name, target))
    return {"plan": plan, "unknown": sorted(want - kset), "unchanged": unchanged}


def hermes_skill_view(rows, cfg=None) -> dict:
    """PURE. Panel-shaped view: the rows plus the two counts that matter.

    `in_prompt` is deliberately NOT just `enabled`: it also subtracts the
    lane-hidden set, so the headline number is what THIS lane's index will carry
    rather than what Hermes's global page shows. When there is no
    `platform_disabled.cli` (the normal install) the two are identical."""
    # `hermes_skill_rows` is idempotent on its own output, so normalise
    # unconditionally rather than sniffing the shape — one code path, and a
    # hand-built or already-normalised row is handled identically.
    rr = hermes_skill_rows(rows)
    off = set(hermes_skill_lane_off(rr, cfg))
    out = []
    for r in rr:
        out.append({**r, "lane_off": r["name"] in off})
    cats = []
    for r in out:
        if r["category"] not in cats:
            cats.append(r["category"])
    return {"skills": out,
            "total": len(out),
            "enabled_count": sum(1 for r in out if r["enabled"]),
            "in_prompt": sum(1 for r in out if r["enabled"] and not r["lane_off"]),
            "lane_off": sorted(off),
            "categories": cats,
            # Named so the panel never has to guess which key it is editing, and
            # so the "this is global, not just this lane" sentence has a source.
            "scope": "global"}


def _hermes_toolset_config() -> dict:
    """Raw truth off disk for the three keys that decide the lane's tool surface.
    Readable with Hermes STOPPED, so the panel can still say what is configured."""
    try:
        with open(_hermes_config_path()) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    pts = data.get("platform_toolsets")
    cli = (pts or {}).get("cli") if isinstance(pts, dict) else None
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    dis = agent.get("disabled_toolsets")
    sk = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    skd = sk.get("disabled")
    spd = sk.get("platform_disabled")
    spc = (spd or {}).get(HERMES_LEVER_PLATFORM) if isinstance(spd, dict) else None
    return {
        # None = never saved → Hermes falls back to the hermes-cli composite.
        "platform_toolsets_cli": ([str(x) for x in cli] if isinstance(cli, list) else None),
        "disabled_toolsets": ([str(x) for x in dis] if isinstance(dis, list) else []),
        "coding_context": str(agent.get("coding_context") or "auto").strip().lower(),
        # The GLOBAL disabled-skill list — the key Hermes's own dashboard writes
        # (skills_config.py:68). Readable with Hermes stopped, so the panel can
        # still say what is configured. `[]`/absent are the same thing here (unlike
        # platform_toolsets.cli, where the distinction is load-bearing).
        "skills_disabled": ([str(x) for x in skd] if isinstance(skd, list) else []),
        # Read-ONLY, never written by us: upstream's dashboard cannot produce it,
        # so writing it would make us a second, divergent writer. It can only ADD
        # to the disabled set (skill_utils.py:454), so it is the one thing that can
        # make our lane's index smaller than Hermes's own page claims — surfaced
        # per-row rather than silently subtracted.
        "skills_platform_disabled_cli": ([str(x) for x in spc]
                                         if isinstance(spc, list) else None),
    }


async def _hermes_dash(method: str, path: str, **kw):
    """One REST call to Hermes's own dashboard on loopback (token-gated, same header
    as the session-rename call). Raises on transport failure; callers decide."""
    import httpx
    tok = _hermes_token()
    if not tok:
        raise RuntimeError("no Hermes dashboard token")
    async with httpx.AsyncClient(timeout=15.0) as c:
        return await c.request(method, f"http://127.0.0.1:{_hermes_port()}{path}",
                               headers={"X-Hermes-Session-Token": tok}, **kw)


async def _hermes_toolset_rows() -> list:
    r = await _hermes_dash("GET", "/api/tools/toolsets")
    if r.status_code >= 400:
        raise RuntimeError(f"toolsets probe {r.status_code}")
    rows = r.json()
    return rows if isinstance(rows, list) else []


@app.get("/api/hermes/toolsets")
async def hermes_toolsets_get() -> JSONResponse:
    """The lever's read side. The CATALOG is always PROBED from the running Hermes
    (GET /api/tools/toolsets) rather than hardcoded, so a pin bump that adds or
    renames a toolset cannot leave a stale table in our source; when Hermes is down
    we report `running:false` + the raw config and invent nothing."""
    cfgv = _hermes_toolset_config()
    base = {"config": cfgv,
            # focus mode makes _load_enabled_toolsets return BEFORE reading the
            # config list — the switches below would be cosmetic. Say so.
            "focus_override": cfgv["coding_context"] == "focus",
            "restart_required": False}
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({**base, "running": False, "source": "config",
                             **hermes_toolset_view([]), "error": str(e)[:200]})
    skills = {}
    try:                                  # best-effort: a skill count is a nicety
        rs = await _hermes_dash("GET", "/api/skills")
        if rs.status_code < 400:
            skills = hermes_skills_summary(rs.json())
    except Exception:
        skills = {}
    return JSONResponse({**base, "running": True, "source": "probe",
                         **hermes_toolset_view(rows, skills, cfgv)})


@app.get("/api/hermes/toolsets/summary")
async def hermes_toolsets_summary() -> JSONResponse:
    """The VERIFY affordance: read LIVE from Hermes and answer the one question the
    switches cannot answer on their own — "what will Hermes hand the model?".

    Deliberately a FRESH probe rather than the panel's snapshot: the whole point is
    that Debi does not have to trust our cached view (or open Hermes's own Skills →
    TOOLSETS page) to check. 409 when Hermes is down — a summary computed off a
    stale config would be exactly the kind of confident-but-wrong number this slice
    exists to remove."""
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)
    skills = {}
    try:
        rs = await _hermes_dash("GET", "/api/skills")
        if rs.status_code < 400:
            skills = hermes_skills_summary(rs.json())
    except Exception:
        skills = {}
    # In `agent.coding_context: "focus"` the lane's resolver RETURNS ITS OWN toolset
    # list before the config list is read (tui_gateway/server.py:4285-4293), so this
    # listing's enabled set is not what the model gets. Say so on the card rather
    # than print a confident number that does not apply — the exact failure mode
    # this whole affordance exists to remove.
    cfgv = _hermes_toolset_config()
    return JSONResponse({"ok": True, "focus_override": cfgv["coding_context"] == "focus",
                         **hermes_tool_summary(rows, skills)})


@app.post("/api/hermes/toolsets")
async def hermes_toolsets_set(req: Request) -> JSONResponse:
    """The lever's write side. Body is ONE of:
        {"preset": "minimal"|"all"}   — the chips
        {"enabled": ["file", ...]}    — an explicit desired-enabled set
        {"name": "web", "on": false}  — one row's switch

    Every change is an upstream `PUT /api/tools/toolsets/{name}` (see the block
    comment above) and only CHANGED toolsets are written, so re-applying a preset
    costs zero writes. Takes effect on the NEXT Hermes chat — no restart
    (`restart_required` is reported so the panel never has to assume)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    # Shape first, so a malformed body is always the specific 400 and never gets
    # masked by a 409 just because Hermes happens to be stopped.
    if not (body.get("preset") is not None
            or isinstance(body.get("enabled"), list)
            or (isinstance(body.get("name"), str) and body["name"].strip())):
        return JSONResponse({"ok": False, "error": "preset, enabled or name required"},
                            status_code=400)
    try:
        rows = await _hermes_toolset_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)

    # `scope` = which rows this request may change. None = the LEVER rows (every
    # preset), so a preset can never write `platform_toolsets.discord` or flip
    # `config.stt.enabled`. A single-row switch scopes to its own name, so those
    # rows stay flippable when the user aims at them deliberately.
    scope = None
    if body.get("preset") is not None:
        desired = hermes_preset_desired(rows, str(body.get("preset")))
        if desired is None:
            return JSONResponse({"ok": False, "error": "unknown preset"},
                                status_code=400)
    elif isinstance(body.get("enabled"), list):
        desired = [str(x) for x in body["enabled"]]
    elif isinstance(body.get("name"), str) and body["name"].strip():
        nm = body["name"].strip()
        scope = [nm]
        desired = [nm] if body.get("on") else []
    else:                                     # unreachable — the shape gate above
        return JSONResponse({"ok": False, "error": "preset, enabled or name required"},
                            status_code=400)

    bad = hermes_toolsets_valid(rows, desired, scope)
    if bad:
        return JSONResponse({"ok": False, "error": bad}, status_code=400)

    p = hermes_toolset_plan(rows, desired, scope)
    changed, failed = [], []
    for name, on in p["plan"]:
        try:
            r = await _hermes_dash("PUT", f"/api/tools/toolsets/{name}",
                                   json={"enabled": bool(on)})
            if r.status_code >= 400:
                failed.append(f"{name}:{r.status_code}")
            else:
                changed.append(name)
                # Per SUCCESSFUL write, so a partially-failed request still signals
                # the part that landed. The shell only compares > and records, so a
                # multi-write request costs exactly one reload, not one per name.
                _hermes_cfg_bump()
        except Exception as e:
            failed.append(f"{name}:{str(e)[:60]}")

    # Re-probe and report the TRUTH rather than our intent. A name that refuses to
    # turn on is almost always sitting in agent.disabled_toolsets, which upstream
    # subtracts last (tools_config.py:2530) — so name that cause instead of leaving
    # the user staring at a switch that snaps back.
    stuck = []
    try:
        after = await _hermes_toolset_rows()
        now = set(hermes_toolsets_enabled(after))
        stuck = sorted({n for n in desired if n in set(hermes_toolset_names(after))
                        and n not in now})
    except Exception:
        after = rows
    view = hermes_toolset_view(after)
    print(f"[hermes-tools] {len(changed)} changed, {len(p['plan'])} planned, "
          f"{view['enabled_count']}/{view['total']} toolsets on "
          f"({view['tool_count_enabled']} tools) failed={failed} stuck={stuck}",
          flush=True)
    return JSONResponse({
        "ok": not failed, "changed": changed, "failed": failed,
        "unknown": p["unknown"], "stuck": stuck,
        # The LANE's set, so this list and `enabled_count` can never disagree.
        "enabled": sorted(hermes_lever_enabled(after)),
        "platform": HERMES_LEVER_PLATFORM,
        "enabled_count": view["enabled_count"], "total": view["total"],
        "tool_count_enabled": view["tool_count_enabled"],
        "restart_required": False,
        "note": ("takes effect on the next Hermes chat" if not failed else
                 "some toolsets could not be written — " + " · ".join(failed)),
    }, status_code=200 if not failed else 502)


async def _hermes_skill_rows() -> list:
    r = await _hermes_dash("GET", "/api/skills")
    if r.status_code >= 400:
        raise RuntimeError(f"skills probe {r.status_code}")
    return hermes_skill_rows(r.json())


@app.get("/api/hermes/skills")
async def hermes_skills_get() -> JSONResponse:
    """The per-skill lever's read side. The catalog is always PROBED from the
    running Hermes (`GET /api/skills`) — never a table in our source — so a skill
    installed, renamed or removed upstream cannot leave a stale row here.

    With Hermes stopped we report `running:false` and the raw configured list off
    disk, and invent nothing."""
    cfgv = _hermes_toolset_config()
    base = {"config": {"skills_disabled": cfgv["skills_disabled"],
                       "skills_platform_disabled_cli":
                           cfgv["skills_platform_disabled_cli"]},
            "scope": "global"}
    try:
        rows = await _hermes_skill_rows()
    except Exception as e:
        return JSONResponse({**base, "running": False, "source": "config",
                             **hermes_skill_view([], cfgv), "error": str(e)[:200]})
    return JSONResponse({**base, "running": True, "source": "probe",
                         **hermes_skill_view(rows, cfgv)})


@app.post("/api/hermes/skills")
async def hermes_skills_set(req: Request) -> JSONResponse:
    """The per-skill lever's write side. Body is ONE of:
        {"preset": "defaults"|"none"}      — the chips
        {"name": "pdf", "on": false}       — one row's switch
        {"names": [...], "on": false}      — a bulk action over the rows shown
        {"enabled": [...]}                 — an explicit desired-enabled set

    Every change is an upstream `PUT /api/skills/toggle` (see the block comment
    above `hermes_skill_rows`) and only CHANGED skills are written, so re-applying
    a preset costs zero writes. Takes effect on the NEXT Hermes chat — the skill
    index is rebuilt per prompt from a cache keyed on the disabled set
    (agent/prompt_builder.py:1618-1625), so no restart is needed.

    ⚠️ The writes are SEQUENTIAL because upstream offers no bulk route (there is
    exactly one `/api/skills/toggle` at this pin) and each one is its own atomic
    save — so a bulk action over many rows takes visibly longer than one click,
    and a mid-way failure leaves the earlier writes landed and names the rest."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    # Shape first, so a malformed body is always the specific 400 and is never
    # masked by a 409 just because Hermes happens to be stopped.
    if not (body.get("preset") is not None
            or isinstance(body.get("enabled"), list)
            or isinstance(body.get("names"), list)
            or (isinstance(body.get("name"), str) and body["name"].strip())):
        return JSONResponse({"ok": False,
                             "error": "preset, enabled, names or name required"},
                            status_code=400)
    try:
        rows = await _hermes_skill_rows()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Hermes is not reachable — "
                             f"start it first ({str(e)[:120]})"}, status_code=409)

    scope = None
    if body.get("preset") is not None:
        desired = hermes_skill_preset_desired(rows, str(body.get("preset")))
        if desired is None:
            return JSONResponse({"ok": False, "error": "unknown preset"},
                                status_code=400)
    elif isinstance(body.get("enabled"), list):
        desired = [str(x) for x in body["enabled"]]
    elif isinstance(body.get("names"), list):
        # A bulk action may only move the rows it named — never the rest of the
        # catalog. Turning off "the 12 shown" must not turn off the other 66.
        scope = [str(x) for x in body["names"]]
        desired = list(scope) if body.get("on") else []
    else:
        nm = body["name"].strip()
        scope = [nm]
        desired = [nm] if body.get("on") else []

    bad = hermes_skills_valid(rows, desired, scope)
    if bad:
        return JSONResponse({"ok": False, "error": bad}, status_code=400)

    p = hermes_skill_plan(rows, desired, scope)
    changed, failed = [], []
    for name, on in p["plan"]:
        try:
            r = await _hermes_dash("PUT", HERMES_SKILL_TOGGLE_PATH,
                                   json={"name": name, "enabled": bool(on)})
            if r.status_code >= 400:
                failed.append(f"{name}:{r.status_code}")
            else:
                changed.append(name)
                _hermes_cfg_bump()          # same rule as the toolset lever above
        except Exception as e:
            failed.append(f"{name}:{str(e)[:60]}")

    # Re-probe and report the TRUTH rather than our intent — the same rule the
    # toolset lever follows. A name that refuses to move is worth naming.
    cfgv = _hermes_toolset_config()
    try:
        after = await _hermes_skill_rows()
    except Exception:
        after = rows
    now = set(hermes_skills_on(after))
    stuck = sorted({n for n in desired
                    if n in set(hermes_skill_names(after)) and n not in now})
    view = hermes_skill_view(after, cfgv)
    print(f"[hermes-skills] {len(changed)} changed, {len(p['plan'])} planned, "
          f"{view['in_prompt']}/{view['total']} skills in the prompt "
          f"failed={failed} stuck={stuck}", flush=True)
    return JSONResponse({
        "ok": not failed, "changed": changed, "failed": failed,
        "unknown": p["unknown"], "stuck": stuck,
        "enabled_count": view["enabled_count"], "in_prompt": view["in_prompt"],
        "total": view["total"], "scope": "global", "restart_required": False,
        "note": ("takes effect on the next Hermes chat" if not failed else
                 "some skills could not be written — " + " · ".join(failed)),
    }, status_code=200 if not failed else 502)


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


# ── Voice components: register their in-process MCP servers ──────────────────
# Both optional voice components mount an MCP server IN-PROCESS on their own port
# (streamable HTTP at <base>/mcp), so wiring them into the agents is EXACTLY the
# browse-toggle mechanism — Odysseus via its live admin API, Hermes via the yaml
# round-trip of ~/.hermes/config.yaml. The helpers above were generalised for this
# rather than copy-pasted twice.
#
# The `tools` lists are DISPLAY ONLY (each host discovers the real list itself over
# MCP). VoiceStudio's are read from vendor backend/mcp_server.py @v0.4.2; Voicebox's
# come from the Phase-0 recon notes. ⚠️ PENDING FABLE QA.
VOICE_MCP = {
    "voicestudio": {
        "label": "VoiceStudio",
        "path": "/mcp",
        "tools": ["generate_speech", "clone_voice", "transcribe", "list_voices",
                  "list_personalities", "list_languages", "check_health"],
        # mount_mcp() sets streamable_http_path="/" and mounts the sub-app at "/mcp",
        # so the endpoint is exactly <base>/mcp (upstream's own comment says so).
        # Upstream resolves a per-agent voice binding from an X-OmniVoice-Client-Id
        # REQUEST HEADER; neither host lets us attach custom headers to an http MCP
        # entry, so our calls fall back to the GLOBAL default voice. Graceful, but
        # VoiceStudio's Settings → MCP per-agent binding will not apply to us.
        "note": "per-agent voice binding (X-OmniVoice-Client-Id) can't be sent — "
                "generate_speech uses VoiceStudio's global default voice",
    },
    "voicebox": {
        "label": "Voicebox",
        "path": "/mcp",
        "tools": ["voicebox.speak", "voicebox.transcribe",
                  "voicebox.list_captures", "voicebox.list_profiles"],
        "note": "no auth of any kind — keep it on 127.0.0.1 (never expose via M5)",
    },
}


def voice_mcp_spec(name: str, port) -> "dict | None":
    """PURE: (component name, port) → the registration payloads for BOTH hosts, or
    None for an unknown component / unusable port. Kept pure so the wire shapes are
    unit-testable without a live Odysseus or a ~/.hermes on disk.

      odysseus_form — mcp_routes.add_server is FORM-encoded and takes
                      name/transport/command/args/env/url; http transport needs `url`.
      hermes_entry  — Hermes's url-only shape (mcp_config.cmd_mcp_add:
                      `server_config["url"] = url`) = streamable HTTP.
    """
    meta = VOICE_MCP.get(name)
    if not meta:
        return None
    try:
        p = int(port)
    except (TypeError, ValueError):
        return None
    if p <= 0 or p > 65535:
        return None
    url = f"http://127.0.0.1:{p}{meta['path']}"
    return {
        "name": name,
        "label": meta["label"],
        "url": url,
        "tools": list(meta["tools"]),
        "note": meta["note"],
        "odysseus_form": {"name": name, "transport": "http", "url": url,
                          "args": "[]", "env": "{}"},
        "hermes_entry": {"url": url},
    }


def _voice_comp(name: str) -> dict:
    return (cfg().get("components", {}) or {}).get(name) or {}


@app.get("/api/voice/status")
async def voice_status() -> JSONResponse:
    """Per-host registration state for every voice component. Mirrors browse_status's
    honesty contract: `odysseus` and `hermes` are reported SEPARATELY so the panel can
    show a partial registration instead of a single lying switch. `odysseus_known` is
    False when Odysseus couldn't be asked at all (down ≠ not registered)."""
    try:
        ody = await _ody_mcp_list()
    except Exception:
        ody = None
    out = {"ok": True, "components": {}}
    for name in VOICE_MCP:
        comp = _voice_comp(name)
        port = comp.get("port")
        spec = voice_mcp_spec(name, port)
        srv = None
        if ody is not None:
            srv = next((s for s in ody if s.get("name") == name), None)
        try:
            running = bool(await _port_alive(int(port))) if port else False
        except (TypeError, ValueError):
            running = False
        hermes = _hermes_has_mcp(name)
        out["components"][name] = {
            "label": VOICE_MCP[name]["label"],
            "url": (spec or {}).get("url"),
            "tools": VOICE_MCP[name]["tools"],
            "note": VOICE_MCP[name]["note"],
            "port": port,
            "installed": bool(comp.get("installed")),
            "running": running,
            "odysseus": bool(srv),
            "odysseus_known": ody is not None,
            "hermes": hermes,
            "connected": (srv or {}).get("status") == "connected",
            "on": bool(srv) or hermes,
        }
    return JSONResponse(out)


@app.post("/api/voice/toggle")
async def voice_toggle(req: Request) -> JSONResponse:
    """Register/remove a voice component's MCP server in BOTH Odysseus (live API) and
    Hermes (config.yaml → new Hermes chats). One control → both components, exactly
    like the Browse toggle.

    Idempotent: enabling an already-registered server is a no-op on both hosts (a
    stale URL — e.g. the port changed in harness.yaml — is re-registered); disabling
    an absent one likewise. Turning ON is REFUSED when the component isn't installed
    or isn't listening, because registering a dead URL only buys connection errors in
    every subsequent turn. Turning OFF is always allowed (it is the cleanup path)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name") or "").strip()
    on = bool(body.get("on"))
    if name not in VOICE_MCP:
        return JSONResponse({"ok": False, "error": f"unknown voice component '{name}'"},
                            status_code=400)
    comp = _voice_comp(name)
    spec = voice_mcp_spec(name, comp.get("port"))
    if spec is None:
        return JSONResponse({"ok": False,
                             "error": f"components.{name}.port is missing or invalid in harness.yaml"},
                            status_code=400)
    if on:
        if not comp.get("installed"):
            return JSONResponse({"ok": False, "error":
                                 f"{spec['label']} isn't installed yet — install it in MOT Main first"},
                                status_code=409)
        if not await _port_alive(int(comp["port"])):
            return JSONResponse({"ok": False, "error":
                                 f"{spec['label']} isn't running — start it in MOT Main first "
                                 f"(nothing is listening on :{comp['port']})"},
                                status_code=409)
    log, ody_on, hermes_on = [], None, None   # None = the host couldn't be reached
    try:
        existing = await _ody_find_mcp(name)
        if on:
            if existing and (existing.get("url") or "") != spec["url"]:
                r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
                log.append(f"odysseus-stale-del:{r.status_code}")
                existing = None
            if existing:
                log.append("odysseus:already")
                ody_on = True
            else:
                r = await _ody_req("POST", "/api/mcp/servers", data=spec["odysseus_form"])
                log.append(f"odysseus:{r.status_code}")
                ody_on = r.status_code == 200
        else:
            if existing:
                r = await _ody_req("DELETE", f"/api/mcp/servers/{existing['id']}")
                log.append(f"odysseus-del:{r.status_code}")
                ody_on = r.status_code != 200      # still registered iff the delete failed
            else:
                log.append("odysseus:absent")
                ody_on = False
    except Exception as e:
        log.append(f"odysseus-err:{str(e)[:120]}")
    try:
        hermes_on = _hermes_write_mcp(name, spec["hermes_entry"] if on else None)
        log.append("hermes:ok")
    except Exception as e:
        log.append(f"hermes-err:{str(e)[:120]}")
        hermes_on = _hermes_has_mcp(name)
    line = " · ".join(log)
    print(f"[voice] {name} mcp {'on' if on else 'off'} → {line}", flush=True)
    # ok = at least one host reached the requested state; `partial` says the other
    # didn't, and the panel renders both per-host pills so nothing is hidden.
    reached = [(ody_on is on), (hermes_on is on)]
    return JSONResponse({"ok": any(reached), "on": on, "partial": not all(reached),
                         "odysseus": bool(ody_on), "hermes": bool(hermes_on),
                         "log": line})


# ── Harness-native VOICE capability (FABLE-VOICE-CAPABILITY-SPEC, Phase B) ───────
# Distinct from /api/voice/status|toggle above (those register the two OPTIONAL
# voice COMPONENTS' MCP servers). These three own the all-MIT agents-can-speak path:
# one-shot llama-tts / mlx-audio subprocesses, no port, no card.
def _voice_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the voice module failed to load: {_VOICE_ERR}"},
        status_code=503)


@app.get("/api/voice/config")
def voice_config_get() -> JSONResponse:
    """Current defaults + every audio model in the registry (Phase A/C read this)."""
    v = _voice_cfg()
    available = []
    if _voice is not None:
        _, audio = _split_audio(_registry_models())
        # Hidden models are filtered here too, not only in /api/models — this list
        # feeds the composer's AUDIO popover, and a model hidden from the Models page
        # that still appeared in the composer would make "hide" mean two things.
        available = [_voice.audio_entry_view(m) for m in audio if not _is_hidden(m)]
    return JSONResponse({
        "ok": _voice is not None,
        "tts_model": v["tts_model"], "stt_model": v["stt_model"],
        "available": available,
        "max_chars": (_voice.VOICE_MAX_CHARS if _voice else 0),
        # What is loaded IN MEMORY right now (persistent worker). None = nothing
        # resident, so the next ▶ speak pays the load. The Audio tab shows this as a
        # `resident` pill + an Unload action.
        "resident": (_voice.worker_resident() if _voice else None),
        "error": _VOICE_ERR or None,
    })


@app.post("/api/voice/config")
async def voice_config_set(req: Request) -> JSONResponse:
    """Set the default TTS and/or STT model. Only keys PRESENT in the body are
    touched, so the panel can set one without clobbering the other. An empty string
    clears the slot (= capability off). The id must exist in the registry AND be of
    the right role — writing an unusable default would only fail later, at speak
    time, far from the click that caused it."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    _, audio = _split_audio(_registry_models())
    v_before = _voice_cfg()
    changed = []
    for field, key, pred, label in (
            ("tts_model", "tts_model", _voice.is_tts_entry, "TTS"),
            ("stt_model", "stt_model", _voice.is_stt_entry, "STT")):
        if field not in body:
            continue
        mid = str(body.get(field) or "").strip()
        if mid:
            entry = _voice.find_entry(audio, mid)
            if entry is None:
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is not an audio model in the registry "
                                           f"— rescan or download it in Models → Audio"},
                    status_code=400)
            if not pred(entry):
                return JSONResponse(
                    {"ok": False, "error": f"'{mid}' is a {_voice.audio_entry_view(entry)['role']} "
                                           f"model — it cannot be the default {label} model"},
                    status_code=400)
        if key == "tts_model" and mid != v_before["tts_model"]:
            # The resident worker holds exactly one checkpoint. Clearing the default
            # must free that RAM immediately (Debi's ratified lifecycle), and a SWITCH
            # would otherwise leave the old model resident — charged to the ledger —
            # until someone happened to speak again. ⚠️ PENDING FABLE QA: the spec
            # named only the clear case; killing on a switch too is strictly tidier.
            _voice.worker_stop("tts default " + ("cleared" if not mid else f"→ {mid}"))
        _set_yaml_scalar("voice", key, mid)
        changed.append(f"{key}={mid or '(off)'}")
    if changed:
        print(f"[voice] config {' · '.join(changed)}", flush=True)
    v = _voice_cfg()
    return JSONResponse({"ok": True, "tts_model": v["tts_model"],
                         "stt_model": v["stt_model"], "changed": changed})


@app.post("/api/voice/entry-voice")
async def voice_entry_voice(req: Request) -> JSONResponse:
    """{id, voice} → pin a NAMED VOICE onto one audio registry entry.

    The voice lives ON the registry entry, not in harness.yaml: a voice is a
    property of a model choice (Chelsie only means anything for Qwen3-TTS), so
    two installed TTS models can each remember their own. tts_argv already reads
    `entry["voice"]` and emits `--voice` only when it is set — this endpoint is
    the only writer. An empty string CLEARS it (back to the engine's own default,
    which for mlx-audio means a random name per render — that is the bug this
    whole slice exists to let the user opt out of)."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    voice = body.get("voice", "")
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    err = _voice.validate_voice_choice(entry, voice)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    v = _voice.normalize_voice(voice)
    updated = _registry_update(mid, {"voice": v or None})
    if updated is None:
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is no longer in the registry"},
            status_code=400)
    print(f"[voice] entry-voice {mid} → {v or '(model default)'}", flush=True)
    return JSONResponse({"ok": True, "entry": _voice.audio_entry_view(updated)})


async def _transcribe_clip(path: str, audio: list) -> str:
    """Transcribe ONE reference clip with the harness's own default STT model, or ''.

    THE POINT (root-caused 2026-08-13 from Debi's 30s-per-render report): mlx-audio's
    `generate_audio`, handed a ref_audio with NO ref_text, loads
    whisper-large-v3-turbo (~1.6GB) to transcribe the clip on EVERY render and then
    discards it (generate.py: "Ref_text not found. Transcribing ref_audio…"). Doing it
    ONCE here with whisper-base (sub-second, Gate-2 measured) makes every subsequent
    render skip that path entirely.

    Best-effort by design: no STT default, an unreadable clip or a failed
    transcription all return '' — the render still works, it is just slow, which is
    strictly better than refusing to pin a clip because dictation is not set up.
    """
    if _voice is None:
        return ""
    try:
        vc = cfg().get("voice")
        v = vc if isinstance(vc, dict) else {}
        stt_id = str(v.get("stt_model") or "").strip()
        stt_entry = _voice.find_entry(audio, stt_id) if stt_id else None
        if not stt_entry:
            return ""
        with open(path, "rb") as f:
            clip_bytes = f.read()
        sfx = os.path.splitext(path)[1].lstrip(".").lower() or "wav"
        return (await asyncio.to_thread(functools.partial(
            _voice.stt_transcribe, stt_entry, clip_bytes, sfx, root=ROOT)) or "").strip()
    except Exception as e:                                      # noqa: BLE001
        print(f"[voice] clip transcription skipped: {e}", flush=True)
        return ""


async def _heal_ref_text(entry: dict, audio: list) -> "dict | None":
    """Fill in a MISSING ref_text on an already-pinned entry and persist it.

    Returns the updated entry, or None when nothing could be healed. This is the
    self-heal for clips pinned BEFORE pin-time transcription existed: without it the
    fix would only ever apply to clips pinned after the upgrade, and Debi's existing
    pin would keep paying whisper-large on every single render forever.
    """
    path = str(entry.get("ref_audio") or "").strip()
    if not path or _voice is None:
        return None
    text = await _transcribe_clip(path, audio)
    if not text:
        return None
    updated = _registry_update(entry.get("id"), {"ref_text": text[:_voice.REF_TEXT_MAX]})
    if updated is None:
        return None
    print(f"[voice] ref_text self-healed for {entry.get('id')}: {text[:60]!r}",
          flush=True)
    return updated


def _trim_ref_clip(ff: "str | None", src: str) -> tuple:
    """(path to a ≤REF_CLIP_TRIM_SECS copy, "") or (None, reason). Never raises.

    The copy lives in data/voices/trimmed/ and is what gets PINNED; the source file is
    only read. Re-trimming the same source is skipped when a non-empty copy is already
    there, so pinning the same long clip twice costs one ffmpeg run, not two.
    """
    if not ff or _voice is None:
        return None, "no ffmpeg"
    try:
        dst = _voice.trimmed_clip_path(src, ROOT)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0 \
                and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst, ""
        argv = _voice.ffmpeg_trim_argv(ff, src, dst, _voice.REF_CLIP_TRIM_SECS)
        c = subprocess.run(argv, capture_output=True, text=True, cwd=str(ROOT),
                           timeout=120)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return dst, ""
        return None, ((c.stderr or "").strip()[-160:] or "ffmpeg produced no wav")
    except Exception as e:                                   # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:120]}"


@app.post("/api/voice/entry-ref")
async def voice_entry_ref(req: Request) -> JSONResponse:
    """{id, path|name, ref_text?} → pin a REFERENCE CLIP onto one audio entry.

    A zero-shot ("cloning") model such as OmniVoice has no speaker table at all —
    `model.generate()` takes ref_audio/ref_text and nothing else — so it renders a
    different random voice every time unless it is handed the same clip every time.
    This endpoint is that pin, and it lives on the registry entry beside `voice` for
    the same reason: it is a property of THIS model choice.

    `name` resolves inside the voice library (data/voices); `path` accepts any clip
    on disk (⚠️ PENDING FABLE QA: deliberately not confined to data/voices — Debi may
    point at a clip they already have; it is only ever READ, never deleted). An empty
    path/name CLEARS the pin (the key is removed, never stored as null).

    The resident worker is deliberately NOT restarted: the reference travels per
    request, exactly like the voice name, so a clip change costs no reload.
    """
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    ref_text = body.get("ref_text", "")
    if not isinstance(ref_text, str):
        ref_text = ""
    name = str(body.get("name") or "").strip()
    path = str(body.get("path") or "").strip()
    if name and not path:
        path, why = _voice.library_target(name, ROOT)
        if not path:
            return JSONResponse({"ok": False, "error": why}, status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    err = _voice.validate_ref_choice(entry, path, ref_text)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    ref_text = ref_text.strip()
    # ── LENGTH GUARD (2026-08-14, from Debi's 7.28 MB / ~30s mp3) ────────────────
    # The engine reads only the first ~10s of a reference clip (OmniVoice's
    # ref_audio_max_duration_s=10), so everything past that is render time bought for
    # nothing — and a long clip ALSO makes the pin-time transcription below far more
    # expensive. When we can measure the clip and we have ffmpeg, pin a bounded COPY
    # instead; without ffmpeg, an over-long clip is refused with the reason and the
    # limit named. The original file is never touched either way.
    length_note = ""
    if path:
        secs, method = _voice.estimate_clip_secs(path)
        ff = _voice.ffmpeg_bin(ROOT)
        action, msg = _voice.clip_length_verdict(secs, bool(ff), method)
        if action == "refuse":
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        if action == "trim":
            trimmed, why = _trim_ref_clip(ff, path)
            if trimmed:
                path, length_note = trimmed, msg
                # A trimmed clip is a DIFFERENT clip, so a transcript supplied for the
                # original no longer describes it. Dropping it costs one whisper pass
                # and keeps the ref_text honest.
                ref_text = ""
                print(f"[voice] entry-ref trimmed to {_voice.REF_CLIP_TRIM_SECS}s → "
                      f"{path}", flush=True)
            else:
                length_note = f"{msg} (the trim failed: {why} — pinning it as it is)"
        elif action == "warn":
            length_note = msg
    if path and not ref_text:
        # A STARTER clip comes WITH its ground-truth transcript (the corpus utterance
        # text), so it never pays a transcription — not the whisper-per-render one
        # below, and not even the one-off pin-time one. Checked BEFORE the STT call
        # because it is free and it is more accurate than any ASR result would be.
        ref_text = _voice.starter_ref_text(path, ROOT)
        if ref_text:
            print(f"[voice] entry-ref starter transcript used (no STT): "
                  f"{ref_text[:60]!r}", flush=True)
    if path and not ref_text:
        # AUTO-TRANSCRIBE ONCE AT PIN TIME (Fable fix 2026-08-13, root-caused from
        # Debi's 30s-per-render report): mlx-audio's generate_audio, handed a clip
        # with NO ref_text, loads whisper-large-v3-turbo (~1.6GB) to transcribe the
        # clip on EVERY render, then discards it (generate.py: "Ref_text not found.
        # Transcribing ref_audio..."). Transcribing once HERE with the harness's own
        # default STT (whisper-base, sub-second — Gate-2 measured) and storing the
        # text makes every render skip that path. Best-effort: no STT default or a
        # failed transcription just leaves ref_text empty (slow but working). ONE
        # implementation, shared with the /api/voice/tts self-heal.
        ref_text = await _transcribe_clip(path, audio)
        if ref_text:
            print(f"[voice] entry-ref transcribed clip once: {ref_text[:60]!r}",
                  flush=True)
    patch = {"ref_audio": path or None,
             # Clearing the clip clears its transcript too: a caption with no audio
             # is not a voice, it is a stray sentence prepended to every render.
             "ref_text": (ref_text[:500] or None) if path else None}
    updated = _registry_update(mid, patch)
    if updated is None:
        return JSONResponse(
            {"ok": False, "error": f"'{mid}' is no longer in the registry"},
            status_code=400)
    print(f"[voice] entry-ref {mid} → {os.path.basename(path) if path else '(cleared)'}",
          flush=True)
    return JSONResponse({"ok": True, "entry": _voice.audio_entry_view(updated),
                         "note": length_note})


@app.get("/api/voice/library")
def voice_library(folder: str = "") -> JSONResponse:
    """The reference clips in data/voices — the voice library. A plain directory
    listing: name, absolute path and size, sorted, never raising when the dir does
    not exist yet (it is created on the first save).

    `?folder=<abs path>` lists an EXTRA source instead (non-recursive, capped). The
    folder must be one the user has already added: this endpoint reads a directory
    named by a query parameter, so an allowlist of exact configured directories is
    the whole boundary — no prefix matching, no descent into children.
    """
    if _voice is None:
        return _voice_unavailable()
    if folder:
        folders = _voice.load_folders(ROOT)
        if not _voice.folder_allowed(folder, folders):
            return JSONResponse(
                {"ok": False, "error": "that folder is not one of your clip folders "
                                       "— add it first"}, status_code=400)
        clips = _voice.folder_entries(folder)
        return JSONResponse({"ok": True, "dir": _voice.normalize_folder(folder),
                             "clips": clips, "folder": True,
                             "capped": len(clips) >= _voice.FOLDER_CLIPS_CAP})
    clips = _voice.library_entries(ROOT)
    return JSONResponse({"ok": True, "dir": _voice.voices_dir(ROOT), "clips": clips,
                         # The starter set's own metadata travels with the listing so
                         # the picker can render the CC BY attribution without a
                         # second round-trip — an attribution nobody fetched is an
                         # attribution nobody sees, and CC BY requires it be visible.
                         "starter_dir": _voice.starter_dir(ROOT),
                         "starter_total": len(_voice.STARTER_VOICES),
                         "starter_license": _voice.VCTK_LICENSE,
                         "starter_attribution": _voice.VCTK_ATTRIBUTION,
                         "voice_notice": _voice.VOICE_AI_NOTICE})


_VCTK_TRIES = 4                 # 1 attempt + 3 retries; ~0.8/1.6/3.2s apart
_VCTK_PACE_SECS = 0.06          # a small gap between requests — see below


async def _vctk_rows(offset: int, length: int, tries: int = _VCTK_TRIES) -> tuple:
    """One page of the VCTK datasets-server listing as (rows, total, error).

    On success: (list, num_rows_total, ""). On failure: (None, 0, reason) — and the
    REASON is carried out, because the whole point of this rewrite is that the caller
    must be able to tell "the mirror does not have this speaker" from "we were rate
    limited". Never raises.

    RETRY + PACING (the second half of the 2026-08-14 bug): one full run of thirteen
    slots is ~200 anonymous requests to a service the research itself flagged as
    rate-limiting, and the first build had no retry, no backoff and no gap between
    requests at all — so a single 429 anywhere in the run cost a voice and reported it
    as a missing speaker. Retries are exponential with jitter (`vctk_retry_delay`, pure
    and unit-tested), and 4xx that are NOT 429 fail immediately: a 404 will not become a
    200 no matter how long we wait.
    """
    last = "unknown error"
    for attempt in range(max(1, int(tries))):
        if attempt:
            await asyncio.sleep(_voice.vctk_retry_delay(attempt - 1,
                                                        jitter=random.random() * 0.4))
        try:
            r = await _HF_ANY.get(_voice.VCTK_ROWS_URL, params={
                "dataset": _voice.VCTK_DATASET, "config": "default", "split": "train",
                "offset": int(offset), "length": int(length)})
        except Exception as e:                              # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:120]}"
            continue
        if r.status_code == 200:
            try:
                j = r.json()
            except Exception:                               # noqa: BLE001
                last = "the mirror returned a body that is not JSON"
                continue
            rows = j.get("rows") if isinstance(j, dict) else None
            if not isinstance(rows, list):
                last = "the mirror returned no rows"
                continue
            await asyncio.sleep(_VCTK_PACE_SECS)
            return rows, _voice.vctk_total_rows(j), ""
        if r.status_code == 429:
            last = "rate limited by the dataset mirror (HTTP 429)"
            continue
        if 400 <= r.status_code < 500:
            return None, 0, f"the dataset mirror refused the request (HTTP {r.status_code})"
        last = f"the dataset mirror is having trouble (HTTP {r.status_code})"
    return None, 0, last


@app.post("/api/voice/library/starter")
async def voice_library_starter() -> JSONResponse:
    """Fetch the 13-clip VCTK starter voice set into data/voices/starter/.

    WHY a bespoke endpoint and not the download manager: the download manager is built
    around whole-HF-REPO model downloads that end in a registry entry. Thirteen loose
    wavs totalling ~3 MB are not a model, would never get a registry row, and would
    have to be taught to skip every step that makes that machine worth having.

    FETCH PLAN (research §6.3, followed exactly): the canonical VCTK release is a
    10.94 GB zip with no per-speaker path, so clips come from the HF datasets-server
    `/rows` endpoint against the `sanchit-gandhi/vctk` parquet mirror. Rows are
    speaker-ordered, so each speaker's first offset is found by BINARY SEARCH (pure,
    unit-tested with an injected probe) and then one page is read from there. Signed
    asset URLs EXPIRE, so metadata and audio are fetched in one pass and nothing is
    cached. `/filter?where=` is deliberately not used — re-confirmed live on
    2026-08-14: it still returns an empty body for this dataset.

    PARTIAL SUCCESS IS THE DESIGN: each slot lands independently and a failure is
    reported per-slot with its reason. Re-running only fetches what is missing, and
    now costs almost no probes either — the offset index it learned is persisted.

    ⚠️ FIXED 2026-08-14 after Debi's Mac reported "2 added — 11 failed". Two defects,
    both in the LOOKUP half:

      1. the slots were walked in ACCENT-SLOT order (p311, p334, p345, p294, …) while
         the `lo` floor carried forward monotonically. The floor is only sound if the
         speakers ascend, so from the fourth slot on, every lower-numbered speaker was
         searched exclusively in the region ABOVE p345 and reported absent. Nine slots
         failed this way on every single run, deterministically. FIX:
         `starter_fetch_order()` walks by speaker id; the table keeps its reading order.
      2. a probe that FAILED (429 / timeout) was cached as None and read as "speaker
         absent" — a false statement that also poisoned that offset for every later
         search. FIX: `VctkProbeUnavailable` separates the two outcomes, failures are
         never cached, and `_vctk_rows` retries with backoff + jitter and paces itself.

    A live probe the same day found all thirteen speakers present and the column
    contiguous (p225 … p376 then s5), so no substitution was needed to fix this — the
    `alt` lists exist for a mirror that changes later, and a substitution is always
    reported, never silent.
    """
    if _voice is None:
        return _voice_unavailable()
    ff = _voice.ffmpeg_bin(ROOT)
    d = _voice.starter_dir(ROOT)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not create {d}: {e}"},
                            status_code=500)
    man = _voice.read_starter_manifest(ROOT)
    saved, failed, skipped, substituted = [], [], [], []
    deadline = time.time() + _voice.STARTER_BUDGET_SECS

    # The probe cache, seeded from what earlier runs learned. Only SUCCESSFUL answers
    # ever go in: caching a failure is what turned one 429 into a permanently missing
    # voice. The thirteen searches overlap heavily (speakers ascend and so do their
    # offsets), so a remembered offset turns ~13 independent 17-step searches into far
    # fewer requests — and a re-run into almost none.
    known = _voice.read_starter_offsets(ROOT)
    probes: dict = {v: k for k, v in known.items()}

    class _PastEnd(Exception):
        """The mirror answered, and the answer was 'there is nothing at that row'."""

    # PRIME the row count from one real page before any search runs. The binary search's
    # upper bound has to be right BEFORE the first probe, and a hardcoded total that the
    # mirror has since shrunk would send that probe past the end of the data — where the
    # server returns a perfectly good 200 with an empty list, which is not a failure and
    # so cannot be retried out of. Caught in a synthetic run of this exact walk.
    _first, _tot, _err = await _vctk_rows(0, 1)
    total_rows = _tot or _voice.VCTK_ROWS_TOTAL
    if _first is None:
        return JSONResponse({"ok": False, "saved": [], "skipped": [], "substituted": [],
                             "ffmpeg": bool(ff), "attribution": _voice.VCTK_ATTRIBUTION,
                             "failed": [{"slot": s["slot"], "speaker": s["speaker"],
                                         "reason": f"could not reach the dataset "
                                                   f"mirror: {_err}"}
                                        for s in _voice.STARTER_VOICES]},
                            status_code=502)

    async def probe_async(off: int) -> str:
        """The speaker at `off`. Raises rather than lying: VctkProbeUnavailable when the
        mirror could not answer, _PastEnd when it answered 'nothing there'."""
        nonlocal total_rows
        if off in probes:
            return probes[off]
        rows, tot, err = await _vctk_rows(off, 1)
        if tot:
            total_rows = tot
        if rows is None:
            raise _voice.VctkProbeUnavailable(err or "the mirror gave no answer")
        sid = ""
        if rows and isinstance(rows[0], dict):
            row = rows[0].get("row")
            if isinstance(row, dict):
                sid = str(row.get("speaker_id") or "")
        if not sid:
            total_rows = min(total_rows, off)   # the data ends before here
            raise _PastEnd(off)
        probes[off] = sid
        return sid

    async def find_offset(spk: str, lo: int) -> "int | None":
        """The pure binary search, pumped: run it against the cache, and when it asks
        for an offset we have not seen, fetch that one and start over. Bounded by the
        search depth (~18 probes over 88k rows), 60 rounds of headroom."""
        if spk in known:
            return known[spk]
        for _round in range(60):
            missing = []

            def sync_probe(o, _m=missing):
                if o in probes:
                    return probes[o]
                _m.append(o)
                return None                # aborts the search; we fetch and retry
            try:
                return _voice.vctk_speaker_bounds(spk, sync_probe, total_rows, lo)
            except _voice.VctkProbeUnavailable:
                if not missing:
                    raise
            try:
                await probe_async(missing[0])
            except _PastEnd:
                continue        # total_rows just shrank; re-run with the real bound
        raise _voice.VctkProbeUnavailable("the offset search did not converge")

    lo = 0
    for spec in _voice.starter_fetch_order(_voice.STARTER_VOICES):
        slot, spk = spec["slot"], spec["speaker"]
        name = _voice.starter_clip_name(slot, spk)
        dst = os.path.join(d, name)
        # RE-RUNNABLE: a slot already on disk is skipped. Checks BOTH suffixes, because
        # the no-ffmpeg degrade writes .flac and the old wav-only test meant a machine
        # without ffmpeg re-downloaded everything it already had on every click.
        have = _voice.starter_present(slot, spk, ROOT)
        if have and man.get(os.path.basename(have)):
            skipped.append(os.path.basename(have))
            continue
        if time.time() > deadline:
            failed.append({"slot": slot, "speaker": spk,
                           "reason": "ran out of time for this run — click again to "
                                     "carry on with the slots that are still missing"})
            continue
        try:
            # The primary speaker, then the research's named alternates for this accent
            # slot. Only a genuine ABSENCE moves to the next candidate; a probe failure
            # fails the slot with its real reason, because retrying a rate limit under a
            # different speaker id would just spend the budget faster.
            offset, used = None, spk
            for cand in _voice.starter_candidates(spec):
                offset = await find_offset(cand, lo if cand >= spk else 0)
                if offset is not None:
                    used = cand
                    break
            if offset is None:
                cands = _voice.starter_candidates(spec)
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"not present in the dataset mirror "
                                         f"(tried {', '.join(cands)}) — fill this slot "
                                         f"by hand with ⊕ add clip file"})
                continue
            if used != spk:
                # ⚠️ A SUBSTITUTION CHANGES THE VOICE, keeping only the accent slot.
                substituted.append({"slot": slot, "wanted": spk, "used": used})
                print(f"[voice] starter {slot}: {spk} absent — substituting {used} "
                      f"({spec.get('accent')})", flush=True)
            spk = used
            name = _voice.starter_clip_name(slot, spk)
            dst = os.path.join(d, name)
            known[spk] = offset
            if used == spec["speaker"]:
                # The floor advances ONLY on a primary hit. The walk is sorted by
                # PRIMARY speaker, so a primary offset is a sound floor for the next
                # primary — an alternate's offset is not (p376's alternate is p248,
                # which sits near the very start), and this is exactly the class of
                # mistake that caused the bug being fixed.
                lo = max(lo, offset)
            rows, tot, err = await _vctk_rows(offset, _voice.STARTER_PAGE)
            if tot:
                total_rows = tot
            if rows is None:
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"could not read this speaker's rows: {err}"})
                continue
            picks = _voice.vctk_pick_utterances(rows, spk)
            if not picks:
                failed.append({"slot": slot, "speaker": spk,
                               "reason": "no mic1 utterances returned for this speaker"})
                continue
            parts = []
            for i, p in enumerate(picks):
                # Same retry discipline as the row pages — the asset host is the same
                # rate-limited service, and losing one of three utterances costs the
                # whole slot.
                r, why = None, "unknown error"
                for attempt in range(_VCTK_TRIES):
                    if attempt:
                        await asyncio.sleep(_voice.vctk_retry_delay(
                            attempt - 1, jitter=random.random() * 0.4))
                    try:
                        r = await _HF_ANY.get(p["src"])
                    except Exception as e:                   # noqa: BLE001
                        r, why = None, f"{type(e).__name__}: {str(e)[:100]}"
                        continue
                    if r.status_code == 200 and r.content:
                        break
                    why = f"HTTP {r.status_code}"
                    r = None
                if r is None:
                    failed.append({"slot": slot, "speaker": spk,
                                   "reason": f"clip download failed: {why}"})
                    parts = []
                    break
                src = os.path.join(d, f".{slot}-{i}.flac")
                with open(src, "wb") as f:
                    f.write(r.content)
                parts.append(src)
            if not parts:
                continue
            try:
                if ff and len(parts) >= 1:
                    argv = _voice.ffmpeg_concat_argv(ff, parts, dst)
                    c = subprocess.run(argv, capture_output=True, text=True,
                                       cwd=str(ROOT), timeout=120)
                    ok = os.path.isfile(dst) and os.path.getsize(dst) > 0
                    if not ok:
                        raise RuntimeError((c.stderr or "")[-300:] or "ffmpeg produced no wav")
                    text = " ".join(p["text"] for p in picks)
                else:
                    # ⚠️ NO ffmpeg: keep the SINGLE longest utterance as flac rather
                    # than fail. flac is in REF_AUDIO_SUFFIXES and mlx-audio reads it
                    # with miniaudio — no external tool — so the clip still works; it
                    # is just ~3.6s instead of ~10s. Honest degrade, not a silent one.
                    best = max(range(len(parts)), key=lambda i: os.path.getsize(parts[i]))
                    dst = os.path.join(d, os.path.splitext(name)[0] + ".flac")
                    os.replace(parts[best], dst)      # same dir ⇒ same filesystem
                    parts = [p for i, p in enumerate(parts) if i != best]
                    text = picks[best]["text"]
            except Exception as e:                           # noqa: BLE001
                failed.append({"slot": slot, "speaker": spk,
                               "reason": f"could not assemble the clip: {e}"})
                continue
            finally:
                for p in parts:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            key = os.path.basename(dst)
            man[key] = {"text": text[:_voice.REF_TEXT_MAX], "slot": slot,
                        "speaker": spk, "sex": spec.get("sex", ""),
                        "accent": spec.get("accent", ""),
                        "region": spec.get("region", ""),
                        "source": "VCTK 0.92 (CC BY 4.0)"}
            _voice.write_starter_manifest(man, ROOT)
            saved.append(key)
        except _voice.VctkProbeUnavailable as e:
            # The honest reason, NOT "speaker not found". This distinction is the whole
            # point of the class: it tells Debi to click again rather than to believe a
            # voice is gone.
            failed.append({"slot": slot, "speaker": spk,
                           "reason": f"could not reach the dataset mirror: {e} "
                                     f"— click again in a minute"})
        except Exception as e:                               # noqa: BLE001
            failed.append({"slot": slot, "speaker": spk,
                           "reason": f"{type(e).__name__}: {str(e)[:160]}"})
    # Persist whatever offsets this run learned even if it failed part-way: the next
    # click then spends its requests on the missing clips, not on re-deriving offsets.
    try:
        _voice.write_starter_offsets(known, ROOT)
    except OSError as e:
        print(f"[voice] starter offset index not written: {e}", flush=True)
    for f in failed:
        print(f"[voice] starter {f['slot']} ({f['speaker']}) failed: {f['reason']}",
              flush=True)
    print(f"[voice] starter voices: {len(saved)} saved, {len(skipped)} already there, "
          f"{len(failed)} failed, {len(substituted)} substituted "
          f"({len(probes)} offsets known)", flush=True)
    return JSONResponse({"ok": bool(saved or skipped) or not failed,
                         "saved": saved, "skipped": skipped, "failed": failed,
                         "substituted": substituted, "ffmpeg": bool(ff),
                         "attribution": _voice.VCTK_ATTRIBUTION})


@app.get("/api/voice/library/folders")
def voice_library_folders() -> JSONResponse:
    """The configured extra clip folders + the suggested ones that exist on this Mac.

    A folder is a POINTER, never a copy: nothing is imported and nothing is moved, so
    removing one only forgets the pointer. `missing:true` marks a folder that has since
    been deleted or unmounted — shown rather than silently dropped, because a folder
    that vanished is information."""
    if _voice is None:
        return _voice_unavailable()
    folders = _voice.load_folders(ROOT)
    out = []
    for p in folders:
        real = _voice.normalize_folder(p)
        out.append({"path": p, "real": real, "missing": real is None,
                    "count": len(_voice.folder_entries(p)) if real else 0})
    return JSONResponse({"ok": True, "folders": out,
                         "suggested": _voice.suggested_folders(ROOT),
                         "max": _voice.FOLDER_LIST_MAX})


@app.post("/api/voice/library/folders/add")
async def voice_library_folder_add(req: Request) -> JSONResponse:
    """{path} → remember one more clip folder. Idempotent; validates that it IS a
    directory (a typo must fail here, not later as an empty chip)."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = str(body.get("path") or "").strip()
    if not raw:
        return JSONResponse({"ok": False, "error": "no folder path given"},
                            status_code=400)
    real = _voice.normalize_folder(raw)
    if not real:
        return JSONResponse(
            {"ok": False, "error": f"no such folder: {raw[:200]}"}, status_code=400)
    folders = _voice.load_folders(ROOT)
    if any(_voice.normalize_folder(f) == real for f in folders):
        return JSONResponse({"ok": True, "folders": folders, "added": False})
    if len(folders) >= _voice.FOLDER_LIST_MAX:
        return JSONResponse(
            {"ok": False, "error": f"that is {_voice.FOLDER_LIST_MAX} folders already "
                                   f"— remove one first"}, status_code=400)
    folders = folders + [real]
    _voice.save_folders(folders, ROOT)
    print(f"[voice] clip folder added: {real}", flush=True)
    return JSONResponse({"ok": True, "folders": folders, "added": True})


@app.post("/api/voice/library/folders/remove")
async def voice_library_folder_remove(req: Request) -> JSONResponse:
    """{path} → forget one clip folder. The FILES ARE NEVER TOUCHED — this endpoint
    has no delete in it at all, which is why it can safely accept an arbitrary path."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    raw = str(body.get("path") or "").strip()
    real = _voice.normalize_folder(raw)
    folders = _voice.load_folders(ROOT)
    kept = [f for f in folders
            if f != raw and (real is None or _voice.normalize_folder(f) != real)]
    if len(kept) != len(folders):
        _voice.save_folders(kept, ROOT)
        print(f"[voice] clip folder removed (files untouched): {raw}", flush=True)
    return JSONResponse({"ok": True, "folders": kept,
                         "removed": len(kept) != len(folders)})


@app.post("/api/voice/library/save")
async def voice_library_save(req: Request) -> JSONResponse:
    """RAW audio body + ?name=&fmt= → save a recorded clip into data/voices.

    Same body shape as /api/voice/stt (the panel already holds a Blob from
    MediaRecorder; multipart would buy nothing for a single part). The name is
    sanitized to a basename with a suffix forced from ?fmt=, and an existing file is
    NEVER clobbered — a recording cannot be re-made, so ' (n)' is the only safe
    policy. The bytes are not decoded or transcoded here: mlx-audio's own loader
    reads the container at render time.
    """
    if _voice is None:
        return _voice_unavailable()
    raw = await req.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "no audio received"}, status_code=400)
    if len(raw) > _voice.REF_AUDIO_MAX_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that clip is too large "
                                   f"({len(raw) // (1024 * 1024)} MB) — the cap is "
                                   f"{_voice.REF_AUDIO_MAX_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    fmt = (req.query_params.get("fmt") or "").strip() or req.headers.get("content-type", "")
    name = _voice.sanitize_clip_name(req.query_params.get("name") or "", fmt)
    if not name:
        return JSONResponse(
            {"ok": False, "error": f"give the clip a short name and a supported format "
                                   f"({', '.join(_voice.REF_AUDIO_SUFFIXES)})"},
            status_code=400)
    d = _voice.voices_dir(ROOT)
    os.makedirs(d, exist_ok=True)
    path = _voice.unique_clip_path(d, name)
    try:
        with open(path, "wb") as f:
            f.write(raw)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not save the clip: {str(e)[:200]}"},
                            status_code=500)
    # LENGTH GUARD, save side. The library keeps what it was given — trimming a stored
    # recording behind the user's back would be a worse surprise than a slow render —
    # so this only REFUSES the case we could neither use nor shorten (over-long AND no
    # ffmpeg anywhere), and otherwise reports the estimate so the pin can say what it
    # is about to do. The file is removed again on refusal: a clip the harness has just
    # told the user it will not accept must not be left sitting in the library.
    note = ""
    if _voice is not None:
        secs, method = _voice.estimate_clip_secs(path)
        action, msg = _voice.clip_length_verdict(secs, bool(_voice.ffmpeg_bin(ROOT)),
                                                 method)
        if action == "refuse":
            try:
                os.remove(path)
            except OSError:
                pass
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        if action in ("trim", "warn"):
            note = msg
    print(f"[voice] library saved {len(raw)} bytes → {path}"
          + (f" ({note})" if note else ""), flush=True)
    return JSONResponse({"ok": True, "name": os.path.basename(path), "path": path,
                         "size": len(raw), "note": note})


@app.post("/api/voice/library/delete")
async def voice_library_delete(req: Request) -> JSONResponse:
    """{name} → remove one clip from data/voices. Containment-guarded (realpath must
    land strictly inside the library dir), and any registry entry pinned to it is
    un-pinned in the same breath — a pin at a deleted file would only fail later, at
    speak time, far from the click that caused it."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    path, why = _voice.library_target(body.get("name"), ROOT)
    if not path:
        return JSONResponse({"ok": False, "error": why}, status_code=400)
    try:
        os.remove(path)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not delete: {str(e)[:200]}"},
                            status_code=500)
    unpinned = []
    for m in _registry_models():
        if str(m.get("ref_audio") or "") == path:
            _registry_update(m.get("id"), {"ref_audio": None, "ref_text": None})
            unpinned.append(m.get("id"))
    print(f"[voice] library deleted {os.path.basename(path)}"
          f"{' (unpinned ' + ', '.join(unpinned) + ')' if unpinned else ''}", flush=True)
    return JSONResponse({"ok": True, "deleted": os.path.basename(path),
                         "unpinned": unpinned})


@app.post("/api/voice/tts")
async def voice_tts(req: Request) -> Response:
    """{text, model_id?} → audio/wav bytes. model_id defaults to voice.tts_model.

    Never hangs: the subprocess carries a hard 120s timeout and a second render is
    refused (409) rather than queued. Failures are JSON carrying the engine's log
    tail — the engines exit 0 on failure, so 'no wav' IS the failure signal."""
    if _voice is None:
        return _voice_unavailable()
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    text = body.get("text")
    if isinstance(text, str) and len(text) > _voice.VOICE_MAX_CHARS:
        return JSONResponse(
            {"ok": False, "error": f"text is too long ({len(text)} characters) — the cap "
                                   f"is {_voice.VOICE_MAX_CHARS} per render"},
            status_code=413)
    _, audio = _split_audio(_registry_models())
    mid = str(body.get("model_id") or "").strip() or _voice_cfg()["tts_model"]
    entry = _voice.find_entry(audio, mid) if mid else None
    if mid and entry is None:
        return JSONResponse(
            {"ok": False, "error": f"voice model '{mid}' is not in the registry"},
            status_code=400)
    err = _voice.validate_tts_request(text, entry)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)

    # SELF-HEAL (1c): an entry pinned BEFORE the pin-time transcription shipped still
    # has a clip and no transcript, and mlx-audio reacts to that by loading
    # whisper-large-v3-turbo on EVERY render and throwing it away again. Heal it here,
    # once, before the render that would otherwise pay for it — same best-effort guard
    # as the pin-time path (no STT default ⇒ the old slow-but-working behaviour).
    if _voice.needs_ref_text(entry):
        healed = await _heal_ref_text(entry, audio)
        if healed is not None:
            entry = healed

    # REPLAY CACHE (1a): a second ▶ speak of the same reply, with the same model,
    # voice and clip, is the same wav. The key covers all of them (plus the clip's
    # stat), so there is nothing to invalidate.
    ckey = _voice.entry_cache_key(entry, text)
    hit = _voice.cache_get(ckey)
    if hit is not None:
        print(f"[voice] render CACHED ({len(hit)} bytes) model={mid}", flush=True)
        return Response(content=hit, media_type="audio/wav", headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="speech.wav"',
            "X-Harness-Voice-Model": mid,
            "X-Harness-Voice-Cached": "1",
        })

    stats, t0 = {}, time.time()
    try:
        # spawn_guard is the ledger gate: it runs ONLY when a worker is actually
        # about to be spawned (an already-resident model is already accounted for).
        wav = await asyncio.to_thread(
            functools.partial(_voice.tts_render, entry, text, ROOT,
                              spawn_guard=_voice_spawn_guard, stats=stats))
    except _voice.VoiceBudget as e:
        print(f"[voice] tts refused ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceBusy as e:
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceError as e:
        print(f"[voice] tts FAILED ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message, "log": e.log_tail},
                            status_code=500)
    except Exception as e:                                   # noqa: BLE001
        print(f"[voice] tts crashed ({mid}): {str(e)[:200]}", flush=True)
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)
    _voice.cache_put(ckey, wav)
    # TIMING (1b): one line per render, so "why was that slow" is answerable from the
    # log alone — a cold spawn, a re-load, or the model's own generation time.
    print(f"[voice] render {time.time() - t0:.1f}s "
          f"(engine {float(stats.get('engine_secs') or 0.0):.1f}s, "
          f"load {float(stats.get('load_secs') or 0.0):.1f}s, "
          f"worker={'SPAWNED' if stats.get('spawned') else 'reused'}, "
          f"path={stats.get('path') or '?'}) "
          f"model={mid} voice={stats.get('voice') or '(default)'} "
          f"ref={stats.get('ref') or '(none)'} chars={len(text)}", flush=True)
    return Response(content=wav, media_type="audio/wav", headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'inline; filename="speech.wav"',
        "X-Harness-Voice-Model": mid,
        "X-Harness-Voice-Cached": "0",
    })


@app.post("/api/voice/stt")
async def voice_stt(req: Request) -> JSONResponse:
    """RAW audio body → {"text": …}. Phase D (dictation).

    Body shape is deliberately the SIMPLEST thing that works: the recording is the
    whole request body, and the container comes from `?fmt=` (falling back to the
    Content-Type). Multipart would buy nothing here — there is exactly one part, and
    the panel already has the blob in hand from MediaRecorder.

    Status codes mirror /api/voice/tts so the panel's error handling is one path:
    400 unusable request (no STT default, bad format), 413 over the size cap,
    409 a render already holds the global lock, 500 with the engine's log tail.
    """
    if _voice is None:
        return _voice_unavailable()
    raw = await req.body()
    if len(raw) > _voice.VOICE_MAX_AUDIO_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that recording is too large "
                                   f"({len(raw) // (1024 * 1024)} MB) — the cap is "
                                   f"{_voice.VOICE_MAX_AUDIO_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    # ?fmt= wins: MediaRecorder's mimeType is authoritative on the panel side, while a
    # Content-Type can arrive as a generic application/octet-stream from curl.
    fmt = (req.query_params.get("fmt") or "").strip() or req.headers.get("content-type", "")
    mid = (req.query_params.get("model_id") or "").strip() or _voice_cfg()["stt_model"]
    if not mid:
        return JSONResponse(
            {"ok": False, "error": "set a default STT model in Models → Audio"},
            status_code=400)
    _, audio = _split_audio(_registry_models())
    entry = _voice.find_entry(audio, mid)
    if entry is None:
        return JSONResponse(
            {"ok": False, "error": f"voice model '{mid}' is not in the registry"},
            status_code=400)
    err = _voice.validate_stt_request(raw, fmt, entry)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        text = await asyncio.to_thread(_voice.stt_transcribe, entry, raw, fmt, ROOT)
    except _voice.VoiceBusy as e:
        return JSONResponse({"ok": False, "error": e.message}, status_code=409)
    except _voice.VoiceError as e:
        print(f"[voice] stt FAILED ({mid}): {e.message}", flush=True)
        return JSONResponse({"ok": False, "error": e.message, "log": e.log_tail},
                            status_code=500)
    except Exception as e:                                   # noqa: BLE001
        print(f"[voice] stt crashed ({mid}): {str(e)[:200]}", flush=True)
        return JSONResponse({"ok": False, "error": str(e)[:300]}, status_code=500)
    print(f"[voice] stt {mid}: {len(raw)} bytes → {len(text)} chars", flush=True)
    return JSONResponse({"ok": True, "text": text, "model_id": mid})


@app.post("/api/voice/unload")
def voice_unload() -> JSONResponse:
    """Kill the resident TTS worker, freeing its weights (and its ledger claim).

    Deliberately does NOT clear the default: this is 'give me the RAM back', not
    'turn voice off'. The next ▶ speak simply pays the load again — which is also
    the honest way to verify the worker is doing its job."""
    if _voice is None:
        return _voice_unavailable()
    before = _voice.worker_resident()
    stopped = _voice.worker_stop("unload requested")
    return JSONResponse({"ok": True, "stopped": bool(stopped),
                         "was": (before or {}).get("model"),
                         "resident": _voice.worker_resident()})


# ══ MUSIC LANE (FABLE-MUSIC-LANE-SPEC, 2026-08-20) ═══════════════════════════
# A native bridge lane like voice: no component card, no port, no daemon. Renders
# are one-shot subprocesses run as background JOBS, one at a time, gated by the same
# model-RAM ledger every other loader answers to.

_MUSIC_INSTALLING: dict = {}          # engine -> {"since": ts, "error": str|None}
_MUSIC_INSTALL_LOCK = threading.Lock()
_MUSIC_INSTALL_TIMEOUT = 7200         # 2h: ~12GB of weights + a cmake build


def _music_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the music module failed to load: {_MUSIC_ERR}"},
        status_code=503)


def _music_pin(key: str) -> str:
    return str((cfg().get("build", {}) or {}).get(key) or "")


def _music_engine_state(engine: str) -> dict:
    """One engine's row for /api/music/status. `installed` is read FROM DISK every
    time — never a stored flag, so a deleted HF cache or a wiped build tells the
    truth immediately."""
    rev = _music_pin("music_minimax_pin") if engine == "minimax" else ""
    ok, snap, reason = _music.engine_installed(ROOT, engine, rev)
    gb, est = _music.engine_size_gb(ROOT, engine, ok, snap)
    with _MUSIC_INSTALL_LOCK:
        inst = dict(_MUSIC_INSTALLING.get(engine) or {})
    row = {"engine": engine, "label": _music.ENGINE_LABEL.get(engine, engine),
           "note": _music.ENGINE_NOTE.get(engine, ""), "installed": bool(ok),
           "reason": "" if ok else reason, "size_gb": gb, "size_estimated": bool(est),
           "ram_gb": _music.MUSIC_RAM_GB.get(engine, 0),
           "default_steps": _music.DEFAULT_STEPS.get(engine),
           "max_steps": _music.MAX_STEPS.get(engine),
           "installing": bool(inst.get("since") and not inst.get("done")),
           "install_error": inst.get("error") or ""}
    # The licence line comes from the SAME table the HF search rows read, so a known
    # mistag can never be honest on one surface and wrong on another.
    row["license"] = (license_override("MiniMaxAI/MiniMax-Music3") if engine == "minimax"
                      else dict(_music.ENGINE_LICENSE.get(engine) or {}))
    return row


def _music_history(limit: int = 40) -> list:
    """What renders have ACTUALLY cost on this machine, newest first — the input to
    the ETA. Best-effort: an unreadable library simply means the calibration numbers
    are used instead."""
    try:
        rows = _music.library_entries(ROOT)[:limit]
    except Exception:                                            # noqa: BLE001
        return []
    return [{"engine": r.get("engine"), "seconds": r.get("seconds"),
             "wall": r.get("wall")} for r in rows if r.get("wall")]


def _music_job_view() -> dict:
    """The live job with its progress folded in (never a second job dict)."""
    job = _music.current_job()
    if not job:
        return None
    tail = _music.job_log_tail(job)   # read BEFORE the path is dropped
    job.pop("log", None)              # a temp path is not the panel's business
    job["progress_view"] = _music.progress_view(job, tail, _music_history())
    return job


@app.get("/api/music/status")
def music_status() -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    engines = [_music_engine_state(e) for e in _music.ENGINES]
    return JSONResponse({"ok": True, "engines": engines,
                         "busy": _music.job_busy(), "job": _music_job_view(),
                         "dir": _music.music_dir(ROOT),
                         "default_dir": _music.music_base_dir(ROOT),
                         "seconds_min": _music.SECONDS_MIN,
                         "seconds_max": _music.SECONDS_MAX,
                         "seconds_default": _music.SECONDS_DEFAULT,
                         "prompt_max": _music.PROMPT_MAX,
                         "seed_max": _music.SEED_MAX,
                         "seed_help": _music.SEED_HELP,
                         "formats": {e: list(f) for e, f in _music.ENGINE_FORMATS.items()},
                         "format_default": dict(_music.DEFAULT_FORMAT),
                         "format_label": dict(_music.FORMAT_LABEL),
                         "convert_formats": _music.convert_formats(),
                         "templates": _music.all_templates(ROOT)})


def _music_install_thread(engine: str) -> None:
    try:
        r = _script("install_music.sh", engine, timeout=_MUSIC_INSTALL_TIMEOUT)
        err = "" if r.returncode == 0 else (r.stdout + r.stderr)[-1200:]
    except subprocess.TimeoutExpired:
        err = (f"install timed out after {_MUSIC_INSTALL_TIMEOUT // 3600}h — "
               f"run it in a terminal: ./scripts/install_music.sh {engine}")
    except Exception as e:                                       # noqa: BLE001
        err = f"install crashed: {e}"[:1200]
    with _MUSIC_INSTALL_LOCK:
        _MUSIC_INSTALLING[engine] = {"since": None, "done": True, "error": err}
    print(f"[music] install {engine}: {'ok' if not err else 'FAILED'}", flush=True)


@app.post("/api/music/install")
async def music_install(req: Request) -> JSONResponse:
    """Install a music engine in the background (multi-GB; the panel polls status).

    The cmake precondition is checked HERE, before anything is spawned: a missing
    toolchain must cost zero bytes and say exactly what to type."""
    if _music is None:
        return _music_unavailable()
    engine = ((await req.json()).get("engine") or "").strip()
    if engine not in _music.ENGINES:
        return JSONResponse({"ok": False, "error": "unknown engine"}, status_code=400)
    if engine == "acestep" and not _music.cmake_bin():
        return JSONResponse(
            {"ok": False, "error": "acestep is built from source and needs cmake — "
                                   "run: brew install cmake"}, status_code=400)
    with _MUSIC_INSTALL_LOCK:
        cur = _MUSIC_INSTALLING.get(engine) or {}
        if cur.get("since") and not cur.get("done"):
            return JSONResponse({"ok": False, "error": "that engine is already installing"},
                                status_code=409)
        _MUSIC_INSTALLING[engine] = {"since": time.time(), "done": False, "error": None}
    threading.Thread(target=_music_install_thread, args=(engine,), daemon=True).start()
    print(f"[music] install {engine} started", flush=True)
    return JSONResponse({"ok": True, "installing": True, "engine": engine})


@app.post("/api/music/generate")
async def music_generate(req: Request) -> JSONResponse:
    """Start ONE render. Validates, then answers to the model-RAM ledger, then claims
    the single job slot. Never queues: a second Metal render would fight the first."""
    if _music is None:
        return _music_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = None
    installed = [e for e in _music.ENGINES
                 if _music.engine_installed(
                     ROOT, e, _music_pin("music_minimax_pin") if e == "minimax" else "")[0]]
    params, err = _music.validate_generate(body, installed)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    # THE LEDGER IS A WARNING, NOT A WALL (Debi's ruling). The first POST gets the
    # numbers and a needs_confirm flag; a second POST carrying confirm:true spends
    # the memory anyway. The warning is never skipped silently — a caller that does
    # not send confirm can never start an over-budget render by accident.
    warning = _music.ram_gate(params["engine"], _loaded_models_bytes(), _budget_bytes())
    if warning and not _music.wants_confirm(body):
        print(f"[music] warned {params['engine']}: {warning}", flush=True)
        return JSONResponse({"ok": False, "needs_confirm": True, "error": warning},
                            status_code=409)
    if warning:
        print(f"[music] over-budget render confirmed by the user: {warning}", flush=True)
    snap = ""
    if params["engine"] == "minimax":
        _ok, snap, _r = _music.minimax_installed(ROOT, _music_pin("music_minimax_pin"))
    job, err = _music.start_job(ROOT, params, snapshot=snap)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=409)
    print(f"[music] render {params['engine']} start — {params['seconds']}s, "
          f"{params['steps']} steps, seed {params['seed']}", flush=True)
    return JSONResponse({"ok": True, "job": job})


@app.post("/api/music/cancel")
async def music_cancel() -> JSONResponse:
    """Stop the render in flight. v1 claimed this could not be done; that was
    over-caution, not a finding — the engines are ordinary one-shot children, they are
    started in their own process group, and killing that group is the correct
    mechanism. The job then cleans up its own partial output."""
    if _music is None:
        return _music_unavailable()
    ok, reason = await asyncio.to_thread(_music.cancel_job)
    if not ok:
        return JSONResponse({"ok": False, "error": reason}, status_code=409)
    return JSONResponse({"ok": True})


@app.get("/api/music/jobs")
def music_jobs() -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    return JSONResponse({"ok": True, "job": _music_job_view(),
                         "busy": _music.job_busy()})


@app.get("/api/music/templates")
def music_templates() -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    return JSONResponse({"ok": True, "templates": _music.all_templates(ROOT)})


@app.post("/api/music/templates")
async def music_template_save(req: Request) -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = None
    t, err = _music.save_template(ROOT, body)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    print(f"[music] template saved: {t['name']}", flush=True)
    return JSONResponse({"ok": True, "template": t,
                         "templates": _music.all_templates(ROOT)})


@app.post("/api/music/templates/delete")
async def music_template_delete(req: Request) -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    tid = ((await req.json()).get("id") or "").strip()
    ok, reason = _music.delete_template(ROOT, tid)
    if not ok:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    return JSONResponse({"ok": True, "templates": _music.all_templates(ROOT)})


@app.get("/api/music/settings")
def music_settings() -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    return JSONResponse({"ok": True, "output_dir": _music.music_dir(ROOT),
                         "default_dir": _music.music_base_dir(ROOT)})


@app.post("/api/music/settings")
async def music_settings_set(req: Request) -> JSONResponse:
    """Point the library somewhere else. The library then lists THAT folder only —
    tracks left behind in the old one are untouched and reappear if it is set back."""
    if _music is None:
        return _music_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    want = (body or {}).get("output_dir")
    if isinstance(want, str) and not want.strip():
        want = None                       # empty = back to the default
    if want is None:
        s = _music.read_settings(ROOT)
        s.pop("output_dir", None)
        _music.write_settings(ROOT, s)
        print("[music] output dir reset to the default", flush=True)
        return JSONResponse({"ok": True, "output_dir": _music.music_dir(ROOT)})
    path, reason = _music.validate_output_dir(ROOT, want)
    if not path:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    s = _music.read_settings(ROOT)
    s["output_dir"] = path
    _music.write_settings(ROOT, s)
    print(f"[music] output dir -> {path}", flush=True)
    return JSONResponse({"ok": True, "output_dir": path})


@app.post("/api/music/convert")
async def music_convert(req: Request) -> JSONResponse:
    """Convert one finished track to mp3/m4a beside itself, with the ffmpeg the voice
    lane already resolves. A format this build cannot write is never offered, so a
    refusal here means the library changed under the panel."""
    if _music is None:
        return _music_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    name = ((body or {}).get("name") or "").strip()
    fmt = ((body or {}).get("fmt") or "").strip().lower()
    made, reason = await asyncio.to_thread(_music.convert_track, ROOT, name, fmt)
    if not made:
        print(f"[music] convert {name!r} -> {fmt}: {reason}", flush=True)
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    print(f"[music] converted {name} -> {made}", flush=True)
    return JSONResponse({"ok": True, "name": made})


@app.get("/api/music/library")
def music_library() -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    return JSONResponse({"ok": True, "dir": _music.music_dir(ROOT),
                         "tracks": _music.library_entries(ROOT)})


@app.get("/api/music/file/{name}")
def music_file(name: str) -> Response:
    """Serve one finished track for the panel's <audio> player. Same containment as
    delete — the name comes from a request, so it is a basename under data/music or
    it is nothing."""
    if _music is None:
        return _music_unavailable()
    target, reason = _music.library_target(ROOT, name)
    if not target:
        raise HTTPException(404, reason)
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4"}.get(os.path.splitext(target)[1].lower(), "audio/wav")
    return FileResponse(target, media_type=mime)


@app.post("/api/music/delete")
async def music_delete(req: Request) -> JSONResponse:
    if _music is None:
        return _music_unavailable()
    name = ((await req.json()).get("name") or "").strip()
    ok, reason = _music.delete_track(ROOT, name)
    if not ok:
        print(f"[music] delete reject {name!r}: {reason}", flush=True)
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    print(f"[music] deleted {name}", flush=True)
    return JSONResponse({"ok": True})


# ══ AIDER CODING-AGENT LANE (docs/research/2026-08-20-aider-recon.md, slice 1) ═══
#
# A terminal program in a pseudo-terminal, for exactly as long as the Aider tab holds
# its websocket open. No port of its own, no component card, no daemon — so nothing
# here belongs in harness.yaml's `components`.
#
# THE SECURITY LINE IS THE ORIGIN GATE (pty_aider.origin_allowed). WebSockets are NOT
# subject to CORS: without it, any page in any browser on this Mac could open
# ws://127.0.0.1:8700/api/pty/aider and get a process. Loopback binding is not enough.

_AIDER_INSTALLING: dict = {}          # {"since": ts|None, "done": bool, "error": str}
_AIDER_INSTALL_LOCK = threading.Lock()
_AIDER_INSTALL_TIMEOUT = 3600         # 1h: an online pip resolve of litellm + grammars


def _aider_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the aider module failed to load: {_PTY_ERR}"},
        status_code=503)


def _aider_log(msg: str) -> None:
    """One line per session event into data/logs/aider.log — so a failed spawn is
    diagnosable without the panel having been open (the music-lane rule)."""
    line = f"[aider] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        p = ROOT / "data" / "logs" / "aider.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(line + "\n")
    except Exception:                                            # noqa: BLE001
        pass


def _bridge_port() -> int:
    try:
        return int((cfg().get("bridge") or {}).get("port") or 8700)
    except Exception:                                            # noqa: BLE001
        return 8700


def aider_spawn_spec() -> tuple:
    """(argv, env, cwd, error). The whole precondition set in one place, so the
    websocket handler has exactly one refusal path and the tests have exactly one
    seam to substitute.

    The MODEL is resolved the same way the v2.1 lane-label fix established: the live
    runner is the authority (_live_model_id probes it), and the identifier that goes on
    the wire is wire_model_id's — the registry id for gguf, the local PATH for MLX.
    """
    if _pty is None:
        return None, None, None, "the aider module is not loaded on this bridge"
    ok, _path, _reason = _pty.is_installed(ROOT)
    if not ok:
        return None, None, None, ("aider is not installed yet — use the Install button "
                                  "on this page (it is an online, one-time install).")
    rc = cfg().get("runner") or {}
    live = _live_model_id(int(rc.get("port") or 6767))
    if not live:
        return None, None, None, ("no model is loaded — load one in MOT Main → "
                                  "Models, then reopen this tab.")
    wire = wire_model_id(live, _registry_models())
    cwd = _pty.workspace_path(ROOT)
    try:
        os.makedirs(cwd, exist_ok=True)
    except OSError as e:
        return None, None, None, f"cannot create the workspace dir: {e}"
    argv = _pty.aider_argv(ROOT, wire)
    env = _pty.aider_env(os.environ, rc.get("endpoint") or "", rc.get("api_key") or "")
    return argv, env, cwd, ""


@app.get("/aider")
def aider_page() -> FileResponse:
    """The Aider tab's own document — deliberately NOT the panel. It is a terminal, it
    loads xterm.js, and it has no business carrying the panel's poll loops."""
    return FileResponse(
        PANEL / "aider.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


@app.get("/api/aider/status")
def aider_status() -> JSONResponse:
    if _pty is None:
        return _aider_unavailable()
    installed, path, _reason = _pty.is_installed(ROOT)
    rc = cfg().get("runner") or {}
    live = _live_model_id(int(rc.get("port") or 6767))
    with _AIDER_INSTALL_LOCK:
        inst = dict(_AIDER_INSTALLING)
    return JSONResponse({
        "ok": True,
        "installed": bool(installed),
        "bin": path,
        "running": _pty.busy(),
        # `model` is what aider will be launched with (display id — the wire id can be a
        # long filesystem path for MLX and is nobody's idea of a label).
        "model": live or "",
        "model_ready": bool(live),
        "workspace": _pty.workspace_path(ROOT),
        "edit_format": _pty.DEFAULT_EDIT_FORMAT,
        "installing": bool(inst.get("since") and not inst.get("done")),
        "install_error": inst.get("error") or "",
    })


def _aider_install_thread() -> None:
    try:
        r = _script("install_aider.sh", timeout=_AIDER_INSTALL_TIMEOUT)
        err = "" if r.returncode == 0 else (r.stdout + r.stderr)[-1200:]
    except subprocess.TimeoutExpired:
        err = ("install timed out after 1h — run it in a terminal: "
               "./scripts/install_aider.sh")
    except Exception as e:                                       # noqa: BLE001
        err = f"install crashed: {e}"[:1200]
    with _AIDER_INSTALL_LOCK:
        _AIDER_INSTALLING.update({"since": None, "done": True, "error": err})
    _aider_log(f"install: {'ok' if not err else 'FAILED'}")


@app.post("/api/aider/install")
def aider_install() -> JSONResponse:
    """Clone + venv + editable install in the background (online-only, several
    minutes). The page polls /api/aider/status; the log is viewable in-panel."""
    if _pty is None:
        return _aider_unavailable()
    with _AIDER_INSTALL_LOCK:
        if _AIDER_INSTALLING.get("since") and not _AIDER_INSTALLING.get("done"):
            return JSONResponse({"ok": False, "error": "already installing"},
                                status_code=409)
        _AIDER_INSTALLING.clear()
        _AIDER_INSTALLING.update({"since": time.time(), "done": False, "error": None})
    threading.Thread(target=_aider_install_thread, daemon=True).start()
    _aider_log("install started")
    return JSONResponse({"ok": True, "installing": True})


@app.websocket("/api/pty/aider")
async def aider_pty(ws: WebSocket) -> None:
    """Raw bytes both ways. The ONLY control message is `\\x1b[RESIZE:<cols>;<rows>]`,
    which is consumed here and never written to the PTY.

    ⚠️ The origin check happens BEFORE anything is spawned, and a refusal is
    accept-then-close so the page gets a code it can explain (4403) rather than an
    opaque handshake failure. Nothing is read, written or spawned on that path.
    """
    if _pty is None:
        await ws.accept()
        await ws.close(code=1011, reason="aider module unavailable")
        return
    origin = ws.headers.get("origin")
    if not _pty.origin_allowed(origin, _bridge_port()):
        _aider_log(f"REFUSED websocket from origin {origin!r} — not our own page")
        await ws.accept()
        await ws.close(code=_pty.CLOSE_ORIGIN, reason="origin not allowed")
        return

    await ws.accept()

    def _q(name, default):
        return _pty.clamp_dim(ws.query_params.get(name), *default)

    cols = _q("cols", (_pty.MIN_COLS, _pty.MAX_COLS, _pty.DEFAULT_COLS))
    rows = _q("rows", (_pty.MIN_ROWS, _pty.MAX_ROWS, _pty.DEFAULT_ROWS))

    argv, env, cwd, err = aider_spawn_spec()
    if err:
        await ws.send_bytes(f"\r\n{err}\r\n".encode())
        await ws.close(code=_pty.CLOSE_PRECONDITION, reason="not ready")
        return

    sess = _pty.PtySession(argv, cwd, env)
    if not _pty.claim(sess):
        await ws.send_bytes("\r\naider is already running in another tab or window — "
                            "only one session at a time.\r\n".encode())
        await ws.close(code=_pty.CLOSE_BUSY, reason="busy")
        return

    try:
        sess.start(cols=cols, rows=rows)
    except Exception as e:                                       # noqa: BLE001
        _pty.release(sess)
        _aider_log(f"spawn FAILED: {e}")
        await ws.send_bytes(f"\r\ncould not start aider: {e}\r\n".encode())
        await ws.close(code=_pty.CLOSE_PRECONDITION, reason="spawn failed")
        return

    _aider_log(f"session start pid={sess.proc.pid} cwd={cwd} "
               f"model={' '.join(argv[1:3])} {cols}x{rows}")

    loop = asyncio.get_running_loop()
    outq: asyncio.Queue = asyncio.Queue()

    def _reader() -> None:
        # A THREAD, not loop.add_reader: this must behave identically under asyncio and
        # uvloop, and a blocking read on a master fd is the simplest correct thing.
        while True:
            data = sess.read()
            try:
                loop.call_soon_threadsafe(outq.put_nowait, data)
            except RuntimeError:
                return              # the loop went away first (socket already torn down)
            if not data:            # b"" = the child is gone
                return

    threading.Thread(target=_reader, daemon=True).start()

    async def _pump() -> None:
        while True:
            data = await outq.get()
            if not data:
                return
            await ws.send_bytes(data)

    async def _recv() -> None:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            raw = msg.get("bytes")
            if raw is None and msg.get("text") is not None:
                raw = msg["text"].encode()
            clean, sizes = _pty.split_resize(raw or b"")
            for c, r in sizes:
                sess.resize(c, r)
            if clean:
                sess.write(clean)

    pump = asyncio.create_task(_pump())
    recv = asyncio.create_task(_recv())
    try:
        await asyncio.wait({pump, recv}, return_when=asyncio.FIRST_COMPLETED)
    except Exception:                                            # noqa: BLE001
        pass
    finally:
        for t in (pump, recv):
            t.cancel()
        how = sess.close()          # SIGTERM → SIGKILL the whole process GROUP
        _pty.release(sess)
        _aider_log(f"session end ({how})")
        try:
            await ws.close(code=_pty.CLOSE_ENDED, reason="session ended")
        except Exception:                                        # noqa: BLE001
            pass


# ══ OFFICE LANE — slice 1, SHEETS ONLY (office-lane-recon §5/§7, 2026-08-21) ═════
#
# Not a component: Univer is vendored JS our own /assets mount already serves, and
# this is the .xlsx round-trip behind it (bridge/office.py). No port, no card, no
# daemon. Every route takes a NAME off the wire, so every route goes through
# office.doc_target — the `library_target`/`_deletable_target` containment rule.
#
# THE FIDELITY CONTRACT is single-sourced from office.FIDELITY_NOTE and printed on
# the page: a save writes a NEW workbook from the snapshot, so a file that came from
# Excel gets a `.bak` taken first (once per day, before the first save of the day).

def _office_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the office module failed to load: {_OFFICE_ERR}"},
        status_code=503)


def _office_log(msg: str) -> None:
    print(f"[office] {msg}", flush=True)


@app.get("/office")
def office_page() -> FileResponse:
    """The Office tab's own document — deliberately not the panel: it loads ~10MB of
    Univer UMD and must not carry the panel's poll loops (the /aider precedent)."""
    return FileResponse(
        PANEL / "office.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


@app.post("/api/office/diag")
async def office_diag(req: Request) -> Response:
    """THE BOOT BEACON. `{stage, detail, boot, ms}` → the bridge log + its own file.

    Written after LOffice failed twice on a Mac none of us can reach, where the whole
    report a person can give is "the tab is blank" — a description that fits a stale
    cached document, a 404'd bundle, a JS engine that refused to parse ten megabytes,
    a mount into a zero-sized box and a web content process killed by jetsam, all
    equally. The page now says which one it is, while it happens, and the answer is a
    grep instead of a hypothesis.

    THREE RULES, all deliberate:
      * it NEVER fails. 204 for everything — junk body, wrong content-type, no body.
        A beacon endpoint that 4xx's would make the page's own error handling fire,
        i.e. the diagnostic would become a second fault to diagnose.
      * it works with `_office` UNAVAILABLE. That case (openpyxl missing, a syntax
        error in office.py) is one of the failures worth reporting, so the reporting
        path cannot depend on the module being importable — it degrades to the bridge
        log alone.
      * the body is parsed leniently. `navigator.sendBeacon` is the transport of
        choice precisely because it survives a page being torn down, and it sends
        text/plain or a Blob, never a tidy JSON content-type.
    """
    # `req.json()` — NOT `json.loads`: this module has no module-level `json` import
    # (every other body-reading route here uses `await req.json()` or a local alias),
    # and Starlette's own parser ignores the content-type, which is exactly what a
    # text/plain sendBeacon needs. ⚠️ The first draft of this route DID write
    # `json.loads`, the NameError was swallowed by the except below, and every single
    # beacon logged as "unparseable" — caught by driving the real page in a real
    # browser, which is the only reason this line is right.
    try:
        body = await req.json()
        if not isinstance(body, dict):
            body = {"stage": "malformed-beacon", "detail": str(body)[:200]}
    except Exception:                                            # noqa: BLE001
        body = {"stage": "unparseable-beacon"}
    stage, detail = body.get("stage"), body.get("detail")
    boot, ms = body.get("boot"), body.get("ms")
    if _office is not None:
        line = _office.write_diag(ROOT, stage, detail, boot, ms)
    else:
        line = f"(office module unavailable) stage={stage} detail={detail}"
    # ⚠️ THE TAG IS `loffice-diag`, NOT `diag`, AND THAT ONE WORD COST A ROUND.
    # These lines used to be logged as `[office] diag …`, and the instruction given to
    # Debi was `grep loffice <bridge.log>`. Only ONE stage — script-start, whose detail
    # happens to contain the build stamp `loffice-2026-08-21x` — carried the string
    # "loffice" at all, so the grep returned exactly one line on a PERFECT boot. That
    # single line was then read as "the document stopped dead after the head script",
    # and a whole round went into a failure that may never have happened. Every line
    # is greppable by one stable token now.
    _office_log(f"loffice-diag {line}")
    return Response(status_code=204)


@app.get("/api/office/files")
def office_files() -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    err = _office.openpyxl_error()
    return JSONResponse({"ok": True, "dir": _office.office_dir(ROOT),
                         "files": _office.list_docs(ROOT),
                         "fidelity": _office.FIDELITY_NOTE,
                         "ext": _office.DOC_EXT,
                         "roundtrip": not err,
                         "roundtrip_error": err})


@app.post("/api/office/new")
async def office_new(req: Request) -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    name, reason = await asyncio.to_thread(
        _office.create_doc, ROOT, ((body or {}).get("name") or ""))
    if not name:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"created {name}")
    return JSONResponse({"ok": True, "name": name})


@app.get("/api/office/open/{name}")
async def office_open(name: str) -> JSONResponse:
    """The .xlsx as an IWorkbookData snapshot the Univer facade can take directly."""
    if _office is None:
        return _office_unavailable()
    snap, reason = await asyncio.to_thread(_office.open_doc, ROOT, name)
    if snap is None:
        _office_log(f"open reject {name!r}: {reason}")
        return JSONResponse({"ok": False, "error": reason},
                            status_code=404 if "no such" in (reason or "") else 400)
    return JSONResponse({"ok": True, "name": name, "snapshot": snap})


@app.post("/api/office/save")
async def office_save(req: Request) -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    name = ((body or {}).get("name") or "").strip()
    snapshot = (body or {}).get("snapshot")
    report, reason = await asyncio.to_thread(_office.save_doc, ROOT, name, snapshot)
    if report is None:
        _office_log(f"save reject {name!r}: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"saved {report['name']} ({report['cells']} cells, "
                f"{report['sheets']} sheet(s))"
                + (f" — backup {report['backup']}" if report.get("backup") else ""))
    return JSONResponse({"ok": True, **report})


@app.post("/api/office/delete")
async def office_delete(req: Request) -> JSONResponse:
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    ok, reason = await asyncio.to_thread(
        _office.delete_doc, ROOT, ((body or {}).get("name") or ""))
    if not ok:
        _office_log(f"delete reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log("deleted a workbook")
    return JSONResponse({"ok": True})


@app.post("/api/office/rename")
async def office_rename(req: Request) -> JSONResponse:
    """{name, to} → the workbook under a new name. Never clobbers (office.rename_doc)."""
    if _office is None:
        return _office_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    if not isinstance(body, dict):        # a JSON body can legally be a list or a string
        body = {}
    name, reason = await asyncio.to_thread(
        _office.rename_doc, ROOT, (body.get("name") or ""), (body.get("to") or ""))
    if not name:
        _office_log(f"rename reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"renamed a workbook to {name}")
    return JSONResponse({"ok": True, "name": name})


@app.post("/api/office/upload")
async def office_upload(req: Request) -> JSONResponse:
    """RAW .xlsx body + ?name= → import a workbook into data/office.

    Same body shape as /api/voice/library/save: one part, so multipart would buy
    nothing. The name is sanitized by office.valid_name like every other route here,
    the bytes are VERIFIED as a workbook before they are kept, and an existing file is
    never clobbered — the import comes back under ' (n)' and says so.
    """
    if _office is None:
        return _office_unavailable()
    raw = await req.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "no file received"}, status_code=400)
    if len(raw) > _office.UPLOAD_MAX_BYTES:
        return JSONResponse(
            {"ok": False, "error": f"that file is {len(raw) // (1024 * 1024)} MB — "
                                   f"the import cap is "
                                   f"{_office.UPLOAD_MAX_BYTES // (1024 * 1024)} MB"},
            status_code=413)
    report, reason = await asyncio.to_thread(
        _office.import_doc, ROOT, (req.query_params.get("name") or ""), raw)
    if report is None:
        _office_log(f"import reject: {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    _office_log(f"imported {report['name']} ({report['bytes']} bytes)")
    return JSONResponse({"ok": True, **report})


@app.get("/api/office/download/{name}")
def office_download(name: str) -> Response:
    """The real file, for Save-a-copy out of the tab. Same containment as delete."""
    if _office is None:
        return _office_unavailable()
    target, reason = _office.doc_target(ROOT, name)
    if not target:
        raise HTTPException(404, reason)
    return FileResponse(
        target,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(target))
