"""ROUTER — the GOOSE agent lane, including the PTY websocket.

Built to docs/research/2026-08-28-goose-source-verify.md. Same shape as routers/aider.py
and for the same reasons; read bridge/pty_goose.py's header for what is load-bearing.

A terminal program in a pseudo-terminal, for exactly as long as the Goose tab holds its
websocket open. No port of its own, no daemon — so nothing here belongs in
motdeck.yaml's `components`, and there is no Mission Control card. It DOES appear in
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
from fastapi import Request, WebSocket
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

# ⚠️ ONE ORPHAN SWEEP AT BRIDGE START, and it is the price of the detach fix. A session
# now outlives its socket AND (start_new_session=True) the bridge, so a restart could
# leave a live goose holding the workspace with nothing pointing at it — while a new tab
# claimed the empty slot and started a SECOND one on the same directory. Identity is
# verified against the pidfile's own command line before anything is signalled; see
# pty_goose.reap_orphan for the rule in full.
if _goose is not None:
    try:
        _orphan = _goose.reap_orphan(ROOT)
        if _orphan not in ("none",):
            print(f"[goose] startup pidfile sweep: {_orphan}", flush=True)
    except Exception as _oe:                                     # noqa: BLE001
        print(f"[goose] startup pidfile sweep skipped: {_oe}", flush=True)

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


def _grace_s() -> float:
    """The detach window, in seconds. A manifest key so an operator can shorten it
    without a code change; clamped in pty_aider so a typo cannot mean 'forever'."""
    try:
        return _goose.clamp_grace((cfg().get("goose") or {}).get("detach_grace_s"))
    except Exception:                                            # noqa: BLE001
        return _goose.DETACH_GRACE_S


def _reap_cb(sess) -> None:
    """The grace window expired with nobody back. Called from the session's own timer
    thread AFTER it has closed OUR OWN child; all that is left is the bookkeeping the
    lane owns — and the pidfile is cleared only if it is still OURS (a pidfile holding
    somebody else's number is not ours to remove)."""
    _goose.release(sess)
    _clear_our_pidfile(sess)
    _goose_log(f"session reaped — {int(getattr(sess, 'grace_s', 0))}s grace expired "
               f"with no page attached (pid {getattr(sess.proc, 'pid', '?')})")


def _clear_our_pidfile(sess) -> None:
    """⛔ PROCESS-KILL RULE, the bookkeeping half. data/goose.pid is removed only when it
    still names the pid of the session that is ending. Two sessions cannot overlap
    today, but a stale clear would make the memory ledger lose a LIVE row — and the
    class (act on a handle without checking whose it is) is the one that closed Debi's
    own goose Desktop twice."""
    try:
        pid = int(getattr(sess.proc, "pid", 0) or 0)
    except (TypeError, ValueError):
        return
    birth = str(getattr(sess, "_mot_owner_birth", "") or "")
    if pid and birth:
        _goose.clear_pidfile(ROOT, pid, birth)


def _sniff_id(sess, data) -> None:
    """F3 — learn the LIVE session's own id from goose's startup banner, so the strip
    can mark which persisted row is the running one instead of guessing (and so a
    resume request for that same session reattaches instead of being refused)."""
    sess._sniff_seen = getattr(sess, "_sniff_seen", 0) + len(data)
    if sess.session_id:
        sess.on_chunk = None
        return
    # ⚠️ THE WHOLE BUFFER SO FAR, not this chunk. Measured on the live walk: goose
    # writes its banner in several pty writes and `20260829_33` straddled two of them,
    # so a per-chunk scan found nothing and the strip could not mark the live row. See
    # pty_goose.scan_session_id for the general form of the lesson.
    sid = _goose.scan_session_id(sess.scrollback(), 0)
    if sid:
        sess.session_id = sid
        sess.on_chunk = None
        _goose_log(f"session id {sid}")
    elif sess._sniff_seen >= _goose.SNIFF_BUDGET:
        # Past the banner and no id: we simply do not know, and we say so by leaving
        # session_id empty rather than by guessing the newest row in the store.
        sess.on_chunk = None


def goose_spawn_spec(resume_id: str = "") -> tuple:
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
    # ⚠️ READ THE USER'S CONFIG *BEFORE* WE SEED IT, and hand the SAME text to the env
    # builder. Both halves of the migration decision (does `active_provider` already
    # carry a choice of theirs?) must come from ONE snapshot: seeding first and reading
    # after would read our own write back and conclude the choice was always ours.
    before = _goose.read_config(ROOT)
    # Re-seeded on EVERY launch, not once at install: the runner's port or endpoint can
    # change between sessions, and a config that was right in July is a 404 in August.
    # The registry goes with it so "MOT Deck (local)" lists EVERY model rather than the
    # loaded one — the picker then holds facts and stays populated with the runner down.
    _goose.seed_config(ROOT, endpoint, port, _registry_models())
    argv = _goose.goose_argv(ROOT, resume_id)
    env = _goose.goose_env(os.environ, ROOT, endpoint, rc.get("api_key") or "",
                           wire, port, config_text=before)
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
    # THE DETACH FACTS. A page that reloads must be able to tell "your session is still
    # here, reattaching" from "there is nothing to come back to" BEFORE it opens the
    # socket — otherwise the pills lie for the half-second in between.
    # ⚠️ `sess_live`, NOT `live` — `live` is ALREADY the model id four lines up, and the
    # first draft of this block shadowed it with a bool. `"model": live or ""` then
    # rendered "" on every poll: the tab said NO MODEL LOADED and disabled Start while
    # the runner was serving. Caught on the live walk, and it is the LIE class, which is
    # why the name is deliberate rather than incidental.
    sess = _goose.current()
    sess_live = bool(sess is not None and sess.alive())
    detached = bool(sess_live and not sess.attached())
    return JSONResponse({
        "ok": True,
        "installed": bool(installed),
        "bin": path,
        "pin": _goose.PIN_TAG,
        "running": sess_live,
        "attached": bool(sess_live and sess.attached()),
        "detached": detached,
        # Seconds left before an unattended session is reaped — surfaced, not implied.
        "grace_left": int(sess.grace_left()) if detached else 0,
        "grace_s": int(_grace_s()),
        # '' when the banner did not give us one: honest silence, never a guess.
        "live_session": (sess.session_id if sess_live else "") or "",
        "resumed_from": (sess.resumed_from if sess_live else "") or "",
        "scrollback_kb": int(_goose.SCROLLBACK_BYTES / 1024),
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


@app.get("/api/goose/sessions")
def goose_sessions() -> JSONResponse:
    """The persisted history, from goose's OWN `session list --format json`, plus a
    best-effort one-line preview and the store's size.

    S9's complaint in one route: the sessions were always there and there was no way in.
    """
    if _goose is None:
        return _goose_unavailable()
    rows, err = _goose.list_sessions(ROOT)
    prev = _goose.previews(ROOT, [r["id"] for r in rows]) if rows else {}
    for r in rows:
        # THE CHIP TITLE, in preference order, and every branch is honest:
        #   1. a name the USER set inside goose (user_set_name) — their words win;
        #   2. the first thing they typed in that session (the preview);
        #   3. goose's own generic name ("CLI Session"), which distinguishes nothing
        #      and is therefore the LAST resort rather than the first.
        line = prev.get(r["id"], "")
        r["preview"] = line
        r["title"] = _goose.chip_line(
            r["name"] if r.get("named") and r["name"] else (line or r["name"] or r["id"]))
    nbytes, measured = _goose.store_size(ROOT)
    sess = _goose.current()
    return JSONResponse({
        "ok": True,
        "sessions": rows,
        "error": err,
        "live_session": (sess.session_id if sess is not None and sess.alive() else "")
                        or "",
        "running": _goose.busy(),
        "store": {"count": len(rows),
                  "bytes": nbytes if measured else None,
                  "human": _goose.human_mb(nbytes) if measured else "",
                  "path": _goose.sessions_dir(ROOT)},
    })


@app.post("/api/goose/end")
def goose_end() -> JSONResponse:
    """THE DELIBERATE END, and the reason the reload fix does not need a flag on the
    wire. Ending kills the PROCESS; the socket then closes because the child is gone.
    So the websocket handler's rule can be structural — child alive at close ⇒ the page
    merely went away (grace); child dead ⇒ the session was ended (reap now) — and there
    is no 'was that deliberate?' bit that a dropped connection could forge."""
    if _goose is None:
        return _goose_unavailable()
    sess = _goose.current()
    if sess is None or not sess.alive():
        return JSONResponse({"ok": True, "how": "gone", "running": False})
    how = sess.close()                       # our OWN child handle, process group
    _goose.release(sess)
    _clear_our_pidfile(sess)
    _goose_log(f"session end (deliberate, {how})")
    return JSONResponse({"ok": True, "how": how, "running": False})


@app.post("/api/goose/session/remove")
async def goose_session_remove(request: Request) -> JSONResponse:
    """Delete ONE session through goose's own `session remove` — see
    pty_goose.remove_session for the measured protocol and why nothing under the store
    is ever touched by hand. The page arms this behind a two-step confirm; this route
    reports only what goose itself confirmed.

    ⚠️ The refusal is PER-SESSION, not per-lane (v1.5.64): an old session deletes
    normally while another one is live — measured, F6 in pty_goose — and only the LIVE
    id is refused. The 409 body always carries `message`, the human sentence; any
    consumer that renders `HTTP 409` instead is showing the status line of a refusal
    that had words."""
    if _goose is None:
        return _goose_unavailable()
    try:
        body = await request.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    sid = str((body or {}).get("id") or "").strip()
    ok, msg = _goose.remove_session(ROOT, sid)
    _goose_log(f"session remove {sid!r}: {'ok' if ok else 'REFUSED'} — {msg}")
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 409)


@app.post("/api/goose/sessions/prune-empty")
async def goose_sessions_prune_empty(request: Request) -> JSONResponse:
    """Remove the exact confirmed historical zero-message sessions through Goose.

    This is intentionally not described as atomic: Goose exposes one confirmed remove
    operation per session. We re-list before starting, refuse if the confirmed set has
    changed, exclude the live session, and report any partial completion precisely.
    """
    if _goose is None:
        return _goose_unavailable()
    try:
        body = await request.json()
    except Exception:                                            # noqa: BLE001
        body = {}
    supplied = (body or {}).get("ids")
    if (not isinstance(supplied, list) or not supplied
            or any(not isinstance(sid, str) or not _goose.SESSION_ID_RE.fullmatch(sid)
                   for sid in supplied)
            or len(set(supplied)) != len(supplied)):
        return JSONResponse({"ok": False, "message": "exact empty-session ids required"},
                            status_code=400)
    rows, err = await asyncio.to_thread(_goose.list_sessions, ROOT)
    if err:
        return JSONResponse({"ok": False,
                             "message": f"Goose could not confirm its session list: {err}"},
                            status_code=409)
    sess = _goose.current()
    live = (sess.session_id if sess is not None and sess.alive() else "") or ""
    current = sorted(r["id"] for r in rows
                     if int(r.get("messages") or 0) == 0 and r.get("id") != live)
    wanted = sorted(supplied)
    if wanted != current:
        return JSONResponse({
            "ok": False,
            "message": "The empty-session list changed; refresh and confirm the new list.",
            "current_ids": current,
        }, status_code=409)
    deleted, failed = [], []
    for sid in wanted:
        ok, message = await asyncio.to_thread(_goose.remove_session, ROOT, sid)
        if ok:
            deleted.append(sid)
        else:
            failed.append({"id": sid, "message": message})
            break
    if failed:
        return JSONResponse({
            "ok": False, "deleted": deleted, "failed": failed,
            "message": (f"Removed {len(deleted)} empty session(s), then Goose refused "
                        f"{failed[0]['id']}: {failed[0]['message']}"),
        }, status_code=409)
    return JSONResponse({"ok": True, "deleted": deleted,
                         "message": f"Removed {len(deleted)} empty session(s)."})


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

    want = (ws.query_params.get("session") or "").strip()

    # ══ THE RELOAD DECISION ═════════════════════════════════════════════════
    # ⌘R does not end a session any more. The four answers are pty_aider's pure
    # attach_verdict table; everything below just carries them out.
    live = _goose.current()
    verdict = _goose.attach_verdict(
        bool(live is not None and live.alive()),
        bool(live is not None and live.attached()),
        want,
        (live.session_id if live is not None else "") or "")

    if verdict == "conflict":
        await ws.send_bytes(
            ("\r\na goose session is still running here. End it first, then pick the "
             "session you want — resuming another one would drop the live "
             "conversation without asking.\r\n").encode())
        await ws.close(code=_goose.CLOSE_BUSY, reason="a session is live")
        return

    # 'takeover' and 'reattach' are the SAME code path from here: both attach to the
    # running child. The only difference is whether somebody had to be displaced, and
    # PtySession.attach handles that by telling them.
    reattached = verdict in ("reattach", "takeover")
    if reattached:
        sess = live
    else:
        argv, env, cwd, err = goose_spawn_spec(want)
        if err:
            await ws.send_bytes(f"\r\n{err}\r\n".encode())
            await ws.close(code=_goose.CLOSE_PRECONDITION, reason="not ready")
            return
        sess = _goose.PtySession(argv, cwd, env)
        sess.resumed_from = want
        if want:
            sess.session_id = want      # a resume already knows its own id
        else:
            sess.on_chunk = _sniff_id
        if not _goose.claim(sess):
            # The claim is LIVENESS-VERIFIED (`_SESSION.alive()` polls the child), so it
            # cannot go stale — and it is in-process, so it cannot outlive the process
            # either. Reaching here means a session was spawned in the microseconds
            # since the verdict; say so and let the page reconnect, never dead-end.
            await ws.send_bytes("\r\na goose session started in another window a "
                                "moment ago — press Start to join it.\r\n".encode())
            await ws.close(code=_goose.CLOSE_BUSY, reason="raced")
            return
        try:
            sess.start(cols=cols, rows=rows)
        except Exception as e:                                   # noqa: BLE001
            _goose.release(sess)
            _goose_log(f"spawn FAILED: {e}")
            await ws.send_bytes(f"\r\ncould not start goose: {e}\r\n".encode())
            await ws.close(code=_goose.CLOSE_PRECONDITION, reason="spawn failed")
            return
        # THE MEMORY-LEDGER HANDLE. Written after the spawn succeeded and removed when
        # the session actually ENDS — not when a socket drops, which is the whole point
        # of this slice: /api/memory shows a "Goose CLI" row for exactly as long as this
        # lane's goose is alive, INCLUDING while it sits detached between two page
        # loads, because a detached session is a real running process and pretending
        # otherwise would be the ghost-row bug wearing the opposite sign. (The embedded
        # lane writes data/goose-ui.pid and earns its own "Goose UI" row the same way.)
        try:
            _, sess._mot_owner_birth = _goose.write_pidfile(ROOT, sess.proc.pid)
        except Exception as exc:
            _goose.release(sess)
            sess.close()  # exact in-memory child handle; no PID/name discovery
            _goose_log(f"ownership record FAILED: {exc}")
            await ws.send_bytes(
                f"\r\ncould not record goose launch ownership: {exc}\r\n".encode())
            await ws.close(code=_goose.CLOSE_PRECONDITION, reason="ownership failed")
            return
        _goose_log(f"session {'resume ' + want if want else 'start'} "
                   f"pid={sess.proc.pid} cwd={cwd} model={env.get('GOOSE_MODEL')} "
                   f"host={env.get('OPENAI_HOST')} {cols}x{rows}")

    loop = asyncio.get_running_loop()
    outq: asyncio.Queue = asyncio.Queue()

    # `None` off the relay is the DISPLACE SENTINEL: another window took the session.
    # It is deliberately not b"" — that means the child is gone, and telling a user
    # their agent died when it is alive and answering somebody else's tab would be the
    # LIE class.
    state = {"displaced": False}

    def _on_bytes(data) -> None:
        # Called on the SESSION's relay thread — which outlives this socket. The
        # RuntimeError guard is what makes a torn-down loop a no-op rather than a
        # traceback on every detach.
        if data is None:
            state["displaced"] = True
            data = b""                       # end this socket's pump, not the child
        try:
            loop.call_soon_threadsafe(outq.put_nowait, data)
        except RuntimeError:
            pass

    attached = sess.attach(_on_bytes)
    if attached is None:
        # The grace timer committed to reaping this session in the microsecond we spent
        # deciding to reattach to it. Say so and let the page press Start — the one
        # thing we must not do is hand back a terminal that is being killed.
        await ws.send_bytes("\r\nthe previous session was just reaped — press Start "
                            "for a new one.\r\n".encode())
        await ws.close(code=_goose.CLOSE_ENDED, reason="reaped")
        return
    replay, eof = attached
    # ONE relay per session, started here rather than in start(): it is idempotent, and
    # a reattach must not spawn a second reader for the same fd.
    sess.start_relay()
    if reattached:
        _goose_log(f"session {'TAKEOVER' if verdict == 'takeover' else 'REATTACH'} "
                   f"pid={sess.proc.pid} replay={len(replay)}B "
                   f"id={sess.session_id or '?'}")
        if replay:
            await ws.send_bytes(replay)
            # A rule, so the user can SEE where the replayed tail ends and live output
            # begins. A scrollback that silently pretends to be the whole transcript is
            # the quiet-wrong-answer shape this project ranks worst.
            await ws.send_bytes(
                ("\r\n\x1b[2m— reattached · last "
                 f"{int(_goose.SCROLLBACK_BYTES / 1024)}KB replayed —\x1b[0m\r\n")
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
            clean, sizes = _goose.split_resize(raw or b"")
            for c, r in sizes:
                sess.resize(c, r)
            if clean:
                sess.write(clean)

    pump = asyncio.create_task(_pump())
    recv = asyncio.create_task(_recv())
    if eof:                # the child died while nobody was attached: nothing to pump
        pump.cancel()
    try:
        await asyncio.wait({pump, recv}, return_when=asyncio.FIRST_COMPLETED)
    except Exception:                                            # noqa: BLE001
        pass
    finally:
        for t in (pump, recv):
            t.cancel()
        # ══ DELIBERATE-VS-DROP, DECIDED BY THE CHILD AND NOT BY THE WIRE ═══════
        # Ending is an explicit act that kills the PROCESS: the End button posts
        # /api/goose/end, and `/exit` inside goose does the same thing from the other
        # side. So the rule here is structural rather than a flag a dropped connection
        # could forge —
        #   child gone  ⇒ the session ENDED: reap, drop the pidfile, say so.
        #   child alive ⇒ the PAGE went away (⌘R, a closed tab, a dead socket): keep
        #                 the process, keep the ledger row, arm the grace window, and
        #                 wait to be reattached.
        if state["displaced"]:
            # Another window took the session. This socket is finished; the CHILD is
            # not, and neither is the user's work — the page says which and offers to
            # take it straight back.
            _goose_log(f"session TAKEN OVER from this socket pid={sess.proc.pid}")
            try:
                await ws.send_bytes(
                    b"\r\n\x1b[2m\xe2\x80\x94 another window took this session "
                    b"\xe2\x80\x94 press Take over to bring it back \xe2\x80\x94"
                    b"\x1b[0m\r\n")
                await ws.close(code=_goose.CLOSE_ENDED, reason="takeover")
            except Exception:                                    # noqa: BLE001
                pass
            return
        if sess.alive():
            armed = sess.detach(_on_bytes, grace=_grace_s(), on_reap=_reap_cb)
            _goose_log(f"session DETACHED pid={sess.proc.pid} — still running, "
                       f"{int(_grace_s())}s to reattach" if armed else
                       f"socket closed but it no longer held pid={sess.proc.pid}")
            try:
                await ws.close(code=_goose.CLOSE_ENDED, reason="detached")
            except Exception:                                    # noqa: BLE001
                pass
            return
        how = sess.close()          # idempotent; the child is already gone
        _goose.release(sess)
        _clear_our_pidfile(sess)
        _goose_log(f"session end ({how})")
        try:
            await ws.close(code=_goose.CLOSE_ENDED, reason="session ended")
        except Exception:                                        # noqa: BLE001
            pass
