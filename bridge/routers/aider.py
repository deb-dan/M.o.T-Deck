"""ROUTER — the AIDER coding-agent lane, including the PTY websocket."""
from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from fastapi import WebSocket
from fastapi.responses import FileResponse, JSONResponse
from ..core.appctx import PANEL, ROOT, _PTY_ERR, _pty, app
from ..core.modelid import _live_model_id, wire_model_id
from ..core.procs import _registry_models, _script, cfg


# ══ AIDER CODING-AGENT LANE (docs/research/2026-08-20-aider-recon.md, slice 1) ═══
#
# A terminal program in a pseudo-terminal, for exactly as long as the Aider tab holds
# its websocket open. No port of its own, no component card, no daemon — so nothing
# here belongs in motdeck.yaml's `components`.
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


def _grace_s() -> float:
    """The detach window, in seconds — how long an aider child keeps running with no
    page attached. Manifest key `aider.detach_grace_s`; clamped in pty_aider."""
    try:
        return _pty.clamp_grace((cfg().get("aider") or {}).get("detach_grace_s"))
    except Exception:                                            # noqa: BLE001
        return _pty.DETACH_GRACE_S


def _reap_cb(sess) -> None:
    """The grace window expired with nobody back. The session has already closed OUR
    OWN child; this is the lane's bookkeeping. (No pidfile here: unlike goose, the aider
    lane has never written one, so there is no ledger row to withdraw.)"""
    _pty.release(sess)
    _aider_log(f"session reaped — {int(getattr(sess, 'grace_s', 0))}s grace expired "
               f"with no page attached (pid {getattr(sess.proc, 'pid', '?')})")


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
        return None, None, None, ("no model is loaded — load one in MOT Deck → "
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
    # THE DETACH FACTS — the same three the Goose tab needs, for the same reason: a
    # reloading page must be able to say "still here, reattaching" rather than guess.
    # ⚠️ `sess_live`, NOT `live` — `live` is ALREADY the model id six lines up. The first
    # draft shadowed it with a bool here, so `"model": live or ""` rendered "" on every
    # poll and the tab said NO MODEL LOADED while the runner was serving. Caught on the
    # goose lane's live walk; the same two lines existed here.
    sess = _pty.current()
    sess_live = bool(sess is not None and sess.alive())
    detached = bool(sess_live and not sess.attached())
    return JSONResponse({
        "ok": True,
        "installed": bool(installed),
        "bin": path,
        "running": sess_live,
        "attached": bool(sess_live and sess.attached()),
        "detached": detached,
        "grace_left": int(sess.grace_left()) if detached else 0,
        "grace_s": int(_grace_s()),
        "scrollback_kb": int(_pty.SCROLLBACK_BYTES / 1024),
        # `model` is what aider will be launched with (display id — the wire id can be a
        # long filesystem path for MLX and is nobody's idea of a label).
        "model": live or "",
        "model_ready": bool(live),
        "workspace": _pty.workspace_path(ROOT),
        "edit_format": _pty.DEFAULT_EDIT_FORMAT,
        "installing": bool(inst.get("since") and not inst.get("done")),
        "install_error": inst.get("error") or "",
    })


@app.post("/api/aider/end")
def aider_end() -> JSONResponse:
    """THE DELIBERATE END. Killing the process is what makes 'ended' distinguishable
    from 'the page went away' without a bit on the wire that a drop could forge."""
    if _pty is None:
        return _aider_unavailable()
    sess = _pty.current()
    if sess is None or not sess.alive():
        return JSONResponse({"ok": True, "how": "gone", "running": False})
    how = sess.close()                       # our OWN child handle, process group
    _pty.release(sess)
    _aider_log(f"session end (deliberate, {how})")
    return JSONResponse({"ok": True, "how": how, "running": False})


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

    # ══ THE RELOAD DECISION — the goose lane's fix, echoed here (doctrine 6b) ═══
    # ⚠️ THE VERDICT ON THIS LANE, stated rather than assumed: aider had the SAME bug.
    # The two lanes share pty_aider's machinery, and the old `finally: sess.close()`
    # killed the child on any socket close — so a ⌘R in the Aider tab ended a running
    # aider mid-edit exactly as it did in Goose. Only the reattach HALF applies here:
    # aider has no resume store to list (its history is a workspace file it reloads by
    # itself), so this lane gets no sessions strip. See attach_verdict for the table.
    live = _pty.current()
    verdict = _pty.attach_verdict(bool(live is not None and live.alive()),
                                  bool(live is not None and live.attached()))
    # ⚠️ THERE IS NO 'busy' REFUSAL ANY MORE — this is sample's live repro (2026-08-29,
    # ledger U10) and the reason attach is a takeover. Her tab showed BOTH "aider is
    # already running in another window" AND a NOT CONNECTED chip beside a Start button
    # that could only produce the same refusal: every control a dead end. Both
    # 'reattach' and 'takeover' now attach to the running child; whoever held it is told
    # and is one click from taking it back.
    reattached = verdict in ("reattach", "takeover")
    if reattached:
        sess = live
    else:
        argv, env, cwd, err = aider_spawn_spec()
        if err:
            await ws.send_bytes(f"\r\n{err}\r\n".encode())
            await ws.close(code=_pty.CLOSE_PRECONDITION, reason="not ready")
            return
        sess = _pty.PtySession(argv, cwd, env)
        if not _pty.claim(sess):
            # The claim is LIVENESS-VERIFIED (`_SESSION.alive()` polls the child) and
            # in-process, so it can neither go stale nor outlive the process. Reaching
            # here means one was spawned in the microseconds since the verdict.
            await ws.send_bytes("\r\nan aider session started in another window a "
                                "moment ago — press Start to join it.\r\n".encode())
            await ws.close(code=_pty.CLOSE_BUSY, reason="raced")
            return
        try:
            sess.start(cols=cols, rows=rows)
        except Exception as e:                                   # noqa: BLE001
            _pty.release(sess)
            _aider_log(f"spawn FAILED: {e}")
            await ws.send_bytes(f"\r\ncould not start aider: {e}\r\n".encode())
            await ws.close(code=_pty.CLOSE_PRECONDITION, reason="spawn failed")
            return
        _aider_log(f"session start pid={sess.proc.pid} cwd={cwd} "
                   f"model={' '.join(argv[1:3])} {cols}x{rows}")

    loop = asyncio.get_running_loop()
    outq: asyncio.Queue = asyncio.Queue()

    # `None` off the relay is the DISPLACE SENTINEL — another window took the session.
    # Deliberately not b"", which means the child is GONE.
    state = {"displaced": False}

    def _on_bytes(data) -> None:
        # Called on the SESSION's relay thread, which outlives this socket.
        if data is None:
            state["displaced"] = True
            data = b""                       # end this socket's pump, not the child
        try:
            loop.call_soon_threadsafe(outq.put_nowait, data)
        except RuntimeError:
            pass

    attached = sess.attach(_on_bytes)
    if attached is None:
        await ws.send_bytes("\r\nthe previous session was just reaped — press Start "
                            "for a new one.\r\n".encode())
        await ws.close(code=_pty.CLOSE_ENDED, reason="reaped")
        return
    replay, eof = attached
    pump = recv = None
    try:
        sess.start_relay()               # idempotent: a reattach starts no second reader
        if reattached:
            _aider_log(f"session {'TAKEOVER' if verdict == 'takeover' else 'REATTACH'} "
                       f"pid={sess.proc.pid} replay={len(replay)}B")
            if replay:
                await ws.send_bytes(replay)
                await ws.send_bytes(
                    ("\r\n\x1b[2m— reattached · last "
                     f"{int(_pty.SCROLLBACK_BYTES / 1024)}KB replayed —\x1b[0m\r\n")
                    .encode())
            sess.resize(cols, rows)

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
        if eof:                # the child died while nobody was attached
            pump.cancel()
        await asyncio.wait({pump, recv}, return_when=asyncio.FIRST_COMPLETED)
    except Exception:                                            # noqa: BLE001
        pass
    finally:
        tasks = [t for t in (pump, recv) if t is not None]
        for t in tasks:
            t.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            # ASGI shutdown may cancel this join too. The subscription still has
            # to be detached below, or its live child never gets a grace timer.
            pass
        # DELIBERATE-VS-DROP, decided by the child and not by the wire — see the goose
        # router for the full note. End posts /api/aider/end (which kills the process);
        # `/exit` inside aider does the same from the other side.
        if state["displaced"]:
            _aider_log(f"session TAKEN OVER from this socket pid={sess.proc.pid}")
            try:
                await ws.send_bytes(
                    b"\r\n\x1b[2m\xe2\x80\x94 another window took this session "
                    b"\xe2\x80\x94 press Take over to bring it back \xe2\x80\x94"
                    b"\x1b[0m\r\n")
                await ws.close(code=_pty.CLOSE_ENDED, reason="takeover")
            except Exception:                                    # noqa: BLE001
                pass
            return
        if sess.alive():
            armed = sess.detach(_on_bytes, grace=_grace_s(), on_reap=_reap_cb)
            _aider_log(f"session DETACHED pid={sess.proc.pid} — still running, "
                       f"{int(_grace_s())}s to reattach" if armed else
                       f"socket closed but it no longer held pid={sess.proc.pid}")
            try:
                await ws.close(code=_pty.CLOSE_ENDED, reason="detached")
            except Exception:                                    # noqa: BLE001
                pass
            return
        how = sess.close()          # idempotent; the child is already gone
        _pty.release(sess)
        _aider_log(f"session end ({how})")
        try:
            await ws.close(code=_pty.CLOSE_ENDED, reason="session ended")
        except Exception:                                        # noqa: BLE001
            pass
