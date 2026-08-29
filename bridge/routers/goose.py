"""ROUTER — the GOOSE agent lane, including the PTY websocket.

Built to docs/research/2026-08-28-goose-source-verify.md. Same shape as routers/aider.py
and for the same reasons; read bridge/pty_goose.py's header for what is load-bearing.

A terminal program in a pseudo-terminal, for exactly as long as the Goose tab holds its
websocket open. No port of its own, no daemon — so nothing here belongs in
harness.yaml's `components`, and there is no Mission Control card. It DOES appear in
the memory ledger by name, because the session writes data/goose.pid for its lifetime
and bridge/core/memory.py builds one row per pidfile.

THE SECURITY LINE IS THE ORIGIN GATE (pty_aider.origin_allowed, imported by pty_goose).
WebSockets are NOT subject to CORS: without it, any page in any browser on this Mac
could open ws://127.0.0.1:8700/api/pty/goose and get a process that can run shell
commands. Loopback binding is not enough.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from fastapi import WebSocket
from fastapi.responses import FileResponse, JSONResponse
from ..core.appctx import PANEL, ROOT, app
from ..core.modelid import _live_model_id, wire_model_id
from ..core.procs import _registry_models, _script, cfg

# Defensive, exactly like appctx does for pty_aider: a snapshot that predates this file
# must still boot, with the tab saying the lane is unavailable rather than the whole
# bridge 500ing on import.
_GOOSE_ERR = ""
try:
    from .. import pty_goose as _goose
except Exception as _e:                                          # noqa: BLE001
    try:
        from bridge import pty_goose as _goose                    # type: ignore
    except Exception as _e2:                                      # noqa: BLE001
        _goose, _GOOSE_ERR = None, (str(_e2) or str(_e))[:200]
        print(f"[goose] module unavailable — the Goose tab is disabled ({_GOOSE_ERR})",
              flush=True)

_GOOSE_INSTALLING: dict = {}          # {"since": ts|None, "done": bool, "error": str}
_GOOSE_INSTALL_LOCK = threading.Lock()
# 30 min: ONE 90MB download plus two sha256 passes over 360MB. Nothing here compiles,
# nothing here resolves a dependency graph — this is generous, not hopeful.
_GOOSE_INSTALL_TIMEOUT = 1800


def _goose_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the goose module failed to load: {_GOOSE_ERR}"},
        status_code=503)


def _goose_log(msg: str) -> None:
    """One line per session event into data/logs/goose.log — so a failed spawn is
    diagnosable without the tab having been open (the music-lane rule)."""
    line = f"[goose] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        p = ROOT / "data" / "logs" / "goose.log"
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


def goose_spawn_spec() -> tuple:
    """(argv, env, cwd, error). The whole precondition set in one place, so the
    websocket handler has exactly one refusal path and the tests have exactly one seam
    to substitute.

    The MODEL is resolved the way the v2.1 lane-label fix established: the LIVE RUNNER
    is the authority (_live_model_id probes it) and the identifier that goes on the wire
    is wire_model_id's — the registry id for gguf, the local PATH for MLX.
    """
    if _goose is None:
        return None, None, None, "the goose module is not loaded on this bridge"
    ok, _path, _reason = _goose.is_installed(ROOT)
    if not ok:
        return None, None, None, ("goose is not installed yet — use the Install button "
                                  "on this page (one 90MB download, verified against "
                                  "the pinned sha256 before anything is extracted).")
    rc = cfg().get("runner") or {}
    port = int(rc.get("port") or 6767)
    live = _live_model_id(port)
    if not live:
        return None, None, None, ("no model is loaded — load one in MOT Deck → "
                                  "Models, then reopen this tab.")
    wire = wire_model_id(live, _registry_models())
    cwd = _goose.workspace_path(ROOT)
    try:
        os.makedirs(cwd, exist_ok=True)
        os.makedirs(_goose.goose_home(ROOT), exist_ok=True)
    except OSError as e:
        return None, None, None, f"cannot create the goose workspace/home: {e}"
    endpoint = rc.get("endpoint") or ""
    # Re-seeded on EVERY launch, not once at install: the runner's port or endpoint can
    # change between sessions, and a config that was right in July is a 404 in August.
    _goose.seed_config(ROOT, endpoint, port)
    argv = _goose.goose_argv(ROOT)
    env = _goose.goose_env(os.environ, ROOT, endpoint, rc.get("api_key") or "",
                           wire, port)
    return argv, env, cwd, ""


@app.get("/goose")
def goose_page() -> FileResponse:
    """The Goose tab's own document — deliberately NOT the panel. It is a terminal, it
    loads xterm.js, and it has no business carrying the panel's poll loops."""
    return FileResponse(
        PANEL / "goose.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


@app.get("/api/goose/status")
def goose_status() -> JSONResponse:
    if _goose is None:
        return _goose_unavailable()
    installed, path, _reason = _goose.is_installed(ROOT)
    rc = cfg().get("runner") or {}
    port = int(rc.get("port") or 6767)
    live = _live_model_id(port)
    # The `tools` verdict, best-effort — see pty_goose.tools_warning for why goose
    # needs one and why an unknown verdict is its own sentence. WARN, NEVER REFUSE
    # (the advisory-gates ruling). A verdict we could not compute at all is SILENCE,
    # not a red pill: the entry lookup is what can fail, and "no registry" is not
    # evidence about the model.
    #
    # ⚠️ THE REGISTRY ENTRY, NOT THE ID. _live_model_id returns a string; the verdict
    # lives on the registry row. Handing the string over would make every model on the
    # machine read "does not say whether it supports tool calling" — a warning that is
    # always shown is a warning nobody reads.
    tools = ""
    try:
        entry = next((m for m in _registry_models() if m.get("id") == live), None) \
            if live else None
        tools = _goose.tools_warning(entry)
    except Exception:                                            # noqa: BLE001
        tools = ""
    with _GOOSE_INSTALL_LOCK:
        inst = dict(_GOOSE_INSTALLING)
    return JSONResponse({
        "ok": True,
        "installed": bool(installed),
        "bin": path,
        "pin": _goose.PIN_TAG,
        "running": _goose.busy(),
        # `model` is what goose will be launched with (display id — the wire id can be a
        # long filesystem path for MLX and is nobody's idea of a label).
        "model": live or "",
        "model_ready": bool(live),
        "tools_warning": tools or "",
        "workspace": _goose.workspace_path(ROOT),
        "home": _goose.goose_home(ROOT),
        "endpoint": _goose.openai_host(rc.get("endpoint") or "", port)
                    + "/v1/chat/completions",
        "installing": bool(inst.get("since") and not inst.get("done")),
        "install_error": inst.get("error") or "",
    })


def _goose_install_thread() -> None:
    try:
        r = _script("install_goose.sh", timeout=_GOOSE_INSTALL_TIMEOUT)
        err = "" if r.returncode == 0 else (r.stdout + r.stderr)[-1200:]
    except subprocess.TimeoutExpired:
        err = ("install timed out after 30min — run it in a terminal: "
               "./scripts/install_goose.sh")
    except Exception as e:                                       # noqa: BLE001
        err = f"install crashed: {e}"[:1200]
    with _GOOSE_INSTALL_LOCK:
        _GOOSE_INSTALLING.update({"since": None, "done": True, "error": err})
    _goose_log(f"install: {'ok' if not err else 'FAILED'}")


@app.post("/api/goose/install")
def goose_install() -> JSONResponse:
    """Download + sha-verify + extract in the background (online-only, ~1 minute on a
    fast line). The page polls /api/goose/status; the log is viewable in-tab."""
    if _goose is None:
        return _goose_unavailable()
    with _GOOSE_INSTALL_LOCK:
        if _GOOSE_INSTALLING.get("since") and not _GOOSE_INSTALLING.get("done"):
            return JSONResponse({"ok": False, "error": "already installing"},
                                status_code=409)
        _GOOSE_INSTALLING.clear()
        _GOOSE_INSTALLING.update({"since": time.time(), "done": False, "error": None})
    threading.Thread(target=_goose_install_thread, daemon=True).start()
    _goose_log("install started")
    return JSONResponse({"ok": True, "installing": True})


@app.websocket("/api/pty/goose")
async def goose_pty(ws: WebSocket) -> None:
    """Raw bytes both ways. The ONLY control message is `\\x1b[RESIZE:<cols>;<rows>]`,
    which is consumed here and never written to the PTY.

    ⚠️ The origin check happens BEFORE anything is spawned, and a refusal is
    accept-then-close so the page gets a code it can explain (4403) rather than an
    opaque handshake failure. Nothing is read, written or spawned on that path.
    """
    if _goose is None:
        await ws.accept()
        await ws.close(code=1011, reason="goose module unavailable")
        return
    origin = ws.headers.get("origin")
    if not _goose.origin_allowed(origin, _bridge_port()):
        _goose_log(f"REFUSED websocket from origin {origin!r} — not our own page")
        await ws.accept()
        await ws.close(code=_goose.CLOSE_ORIGIN, reason="origin not allowed")
        return

    await ws.accept()

    def _q(name, default):
        return _goose.clamp_dim(ws.query_params.get(name), *default)

    cols = _q("cols", (_goose.MIN_COLS, _goose.MAX_COLS, _goose.DEFAULT_COLS))
    rows = _q("rows", (_goose.MIN_ROWS, _goose.MAX_ROWS, _goose.DEFAULT_ROWS))

    argv, env, cwd, err = goose_spawn_spec()
    if err:
        await ws.send_bytes(f"\r\n{err}\r\n".encode())
        await ws.close(code=_goose.CLOSE_PRECONDITION, reason="not ready")
        return

    sess = _goose.PtySession(argv, cwd, env)
    if not _goose.claim(sess):
        await ws.send_bytes("\r\ngoose is already running in another tab or window — "
                            "only one session at a time.\r\n".encode())
        await ws.close(code=_goose.CLOSE_BUSY, reason="busy")
        return

    try:
        sess.start(cols=cols, rows=rows)
    except Exception as e:                                       # noqa: BLE001
        _goose.release(sess)
        _goose_log(f"spawn FAILED: {e}")
        await ws.send_bytes(f"\r\ncould not start goose: {e}\r\n".encode())
        await ws.close(code=_goose.CLOSE_PRECONDITION, reason="spawn failed")
        return

    # THE MEMORY-LEDGER HANDLE. Written after the spawn succeeded and removed in the
    # finally below, so /api/memory shows a "Goose CLI" row for exactly as long as this
    # lane's goose is alive — and never a ghost row for a process that is gone. (The
    # embedded lane writes data/goose-ui.pid and earns its own "Goose UI" row the same
    # way; core/memory.py's _label maps both pidfile stems to their display names.)
    _goose.write_pidfile(ROOT, sess.proc.pid)
    _goose_log(f"session start pid={sess.proc.pid} cwd={cwd} "
               f"model={env.get('GOOSE_MODEL')} host={env.get('OPENAI_HOST')} "
               f"{cols}x{rows}")

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
            clean, sizes = _goose.split_resize(raw or b"")
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
        _goose.release(sess)
        _goose.clear_pidfile(ROOT)
        _goose_log(f"session end ({how})")
        try:
            await ws.close(code=_goose.CLOSE_ENDED, reason="session ended")
        except Exception:                                        # noqa: BLE001
            pass
