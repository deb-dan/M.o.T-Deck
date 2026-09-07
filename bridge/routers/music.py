"""ROUTER — the MUSIC lane (see bridge/music.py for everything it decides)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from ..core.appctx import PANEL, ROOT, _MUSIC_ERR, _music, app
from ..core.events import publish
from ..core.procs import _script, cfg
from .hf import license_override
from .models import _budget_bytes, _loaded_models_bytes


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


@app.get("/compose")
def compose_page() -> FileResponse:
    """COMPOSE — the alternative music surface (docs/FABLE-MUSIC-COMPOSE-SPEC.md).

    Its OWN document, for /comfy's and /aider's reason: it plays audio and watches a
    long render, so it has no business carrying the panel's poll loops. It drives THESE
    routes, unchanged — there is no second music backend and there never will be.

    ⚠️ IT DOES NOT REPLACE THE MUSIC VIEW. The panel's Music view (index.html
    #view-music) is untouched by this slice, on purpose: Debi compares the two surfaces
    live and decides later which survives. Deleting either one takes a real surface
    away from the user.
    """
    return FileResponse(
        PANEL / "compose.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"})


@app.post("/api/music/title")
async def music_title(req: Request) -> JSONResponse:
    """Name a track. THE ONE ROUTE THIS SLICE ADDED, and it exists because the library
    had no concept of a name at all: a track's identity was `minimax-20260820-235921.
    wav`, which is a timestamp.

    The file on disk is NOT renamed (see music.set_track_title): the title is sidecar
    metadata, so the folder and the library can never disagree about what a file is
    called. Both surfaces read it; the Music view simply does not display it yet.
    """
    if _music is None:
        return _music_unavailable()
    try:
        body = await req.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    name = ((body or {}).get("name") or "").strip()
    title = (body or {}).get("title")
    ok, reason = await asyncio.to_thread(_music.set_track_title, ROOT, name, title)
    if not ok:
        print(f"[music] title reject {name!r}: {reason}", flush=True)
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    print(f"[music] titled {name} -> {str(title or '')[:120]!r}", flush=True)
    publish("music", what="library", state="titled", id=name)
    return JSONResponse({"ok": True, "tracks": _music.library_entries(ROOT)})


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
    publish("music", what="install", engine=engine,
            state="failed" if err else "done")
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
    publish("music", what="install", engine=engine, state="starting")
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
    def _job_changed(state, current):
        publish("music", what="job", state=state,
                id=(current or {}).get("id") or "")
    job, err = _music.start_job(ROOT, params, snapshot=snap,
                                on_state=_job_changed)
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
    publish("music", what="job", state="cancelling")
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
    publish("music", what="templates", state="saved", id=t.get("id") or "")
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
    publish("music", what="templates", state="deleted", id=tid)
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
        publish("music", what="settings", state="reset")
        return JSONResponse({"ok": True, "output_dir": _music.music_dir(ROOT)})
    path, reason = _music.validate_output_dir(ROOT, want)
    if not path:
        return JSONResponse({"ok": False, "error": reason}, status_code=400)
    s = _music.read_settings(ROOT)
    s["output_dir"] = path
    _music.write_settings(ROOT, s)
    print(f"[music] output dir -> {path}", flush=True)
    publish("music", what="settings", state="changed")
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
    publish("music", what="library", state="converted", id=made)
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


@app.get("/api/music/analysis/{name}")
async def music_analysis(name: str) -> JSONResponse:
    """The waveform data for ONE track — bars, and the runs of loudness they fall into.

    THE SECOND ROUTE THIS LANE'S REDESIGN ADDED, and the gap that forced it is real:
    Compose's waveform is coloured by the song's SHAPE, and nothing in this lane knows
    a shape. Neither engine reports musical structure and a sidecar carries a prompt, a
    seed and a wall time — so the alternative to measuring the audio was painting
    invented sections, which is the lie class this project ranks worst.

    It is therefore a DERIVED answer and says so in its own payload: `derived: true`
    and `method` travel with the numbers, the labels are the measured ones ("quiet",
    "steady", "loud") and never musical roles, and a track whose audio does not
    segment comes back as mode "ramp" so the page paints one hue instead of drawing
    boundaries that are not there. Computed once per track and cached in its sidecar,
    keyed on the file's own size+mtime; ffmpeg does the decode in a worker thread.
    """
    if _music is None:
        return _music_unavailable()
    data, reason = await asyncio.to_thread(_music.track_analysis, ROOT, name)
    if not data:
        return JSONResponse({"ok": False, "error": reason}, status_code=404)
    return JSONResponse({"ok": True, "name": name, "analysis": data})


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
    publish("music", what="library", state="deleted", id=name)
    return JSONResponse({"ok": True})
