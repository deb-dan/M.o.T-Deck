"""ROUTER — status, logs, and the component lifecycle: plan → install → start → stop."""
from __future__ import annotations

from pathlib import Path
import asyncio
import os
import subprocess
import threading
import time
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, app
from ..core.events import publish
from ..core.health import _health_track, _probe_timeout
from ..core.hermescfg import hermes_cfg_gen
from ..core.modelid import _live_model_id, _runner_engine
from ..core.procs import PROV, _clear_expected, _closure, _expected_path, _kill_port_listener, _mark_expected, _pid_alive, _port_alive, _port_listener_pids, _registry_models, _running, _running_sync, _script, cfg
from .models import opencode_tools_warning
from .nav import nav_gen
from .sampling import _record_load_launch


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
            "Create venv data/unsloth-home/unsloth_studio and pip install -e "
            "vendor/unsloth[studio] — upstream's own declared server stack (fastapi, "
            "uvicorn, datasets, pandas, matplotlib, pymupdf, fastmcp …), a few hundred "
            "MB. The heavy training extras are NOT installed: the tab only needs the "
            "Studio server",
            "data/unsloth-home is this component's ISOLATED home (UNSLOTH_STUDIO_HOME "
            "at launch): its engines, login state and outputs live there — never in "
            "~/.unsloth, which belongs to the standalone Unsloth app on :8888",
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




@app.post("/api/components/{name}/stop")
def stop(name: str) -> JSONResponse:
    _clear_expected(name)   # intentional stop → not "degraded", just "stopped"
    PROV.pop(name, None)    # drop any stale provisioning overlay for this component
    # SSE (2026-08-28): the stop transition, at its source. Emitted BEFORE the kill
    # rather than after — a stop that goes on to fail returns 409 and the panel's own
    # refresh (which this event triggers) reads the truth from /api/status either way,
    # whereas an emit placed after an early `return` path would be skipped.
    publish("component", name=name, state="stopping")
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


# ⚠️ MOVED HERE from app.py:338-362 by the router/core split (2026-08-28).
#    _provision runs the start closure for POST /api/components/{name}/start and
#    is called from nowhere else; it reads _NOTES and _record_load_launch, both
#    of which are router-side, so keeping it in core would invert the dependency.

def _prov_set(n: str, state: str, detail: str) -> None:
    """THE single writer of the provisioning overlay — and therefore the single place
    the SSE hub is told a component moved (2026-08-28).

    This function exists so the emit is at the SOURCE OF TRUTH rather than sprinkled
    over six call sites: every phase the panel used to discover on its next /api/status
    tick (pending · starting · on · failed · blocked) now leaves here as a push. The
    event carries the name and the state as a HINT ONLY — the panel's handler is the
    poll handler it already had, so a lost or stale event costs nothing but latency.

    ⚠️ Runs in _provision's daemon THREAD. events.publish() is thread-safe by design
    (it hands off through the serving loop) and never raises."""
    PROV[n] = {"state": state, "detail": detail}
    publish("component", name=n, state=state)


def _provision(target: str) -> None:
    """Run the dependency closure in order, publishing live state into PROV.
    Runs in a background thread so /api/status can report progress meanwhile."""
    c = cfg()
    order = _closure(target, c, [])
    PROV.clear()
    for n in order:
        _prov_set(n, "pending", "queued")
    for i, n in enumerate(order):
        if _running_sync(n, c):
            _prov_set(n, "on", "already running")
            _mark_expected(n)
            continue
        _prov_set(n, "starting", _NOTES.get(n, "starting…"))
        r = _script("start_component.sh", n)
        if r.returncode == 0:
            if n == "runner":
                _record_load_launch((c.get("runner", {}) or {}).get("model") or "")
            _prov_set(n, "on", "started")
            _mark_expected(n)   # expected-up now; if it later dies → degraded
        else:
            _prov_set(n, "failed", (r.stdout + r.stderr)[-1500:])
            for m in order[i + 1:]:
                _prov_set(m, "blocked", f"blocked by {n} failure")
            return
