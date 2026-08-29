"""ROUTER — the GOOSE EMBED lane: goose Desktop's own UI, served by us.

SPIKE, 2026-08-29. Built to docs/research/2026-08-29-goose-desktop-ui.md §2a (the embed
shape), §3 (pointing it at :6767) and §5 (isolation). Every decision lives in
bridge/gooseui.py; these routes are wiring.

THE WHOLE LANE IN FIVE LINES:
  GET  /gooseui                     OUR entry document = the vendored index.html + one
                                    <script> tag. Starts goosed if it is not up.
  GET  /gooseui/harness-preload.js  OUR window.electron / window.appConfig shim.
  GET  /gooseui/<rel>               the vendored bundle, read-only, contained.
  GET  /api/gooseui/status          installed? serving? which pin, which model, which acp
  POST /api/gooseui/start|stop      supervise our own `goose serve --platform desktop`

⚠️ THIS IS A SECOND GOOSE LANE, NOT A REPLACEMENT. routers/goose.py's PTY lane is
untouched and keeps its own home (data/goose/home), its own pidfile (data/goose.pid) and
its own one-at-a-time claim. This one uses data/goose/ui-home and data/goose-ui.pid.
Both can run at once; bridge/tests/test_gooseui_lane.py walks exactly that.

⚠️ NO TAB WIRING IN THE SPIKE, ON PURPOSE. bridge/panel/index.html, bridge/nav.py and
app/main.swift are deliberately not touched: the page is reachable by URL, Debi looks at
it, and the chrome comes with the full slice.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request

from fastapi import Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)

from ..core.appctx import ROOT, app
from ..core.modelid import _live_model_id, wire_model_id
from ..core.procs import _registry_models, _script, cfg

# Defensive, exactly like routers/goose.py: a snapshot that predates gooseui.py must
# still boot, with this lane's routes saying why rather than the whole bridge 500ing.
_UI_ERR = ""
try:
    from .. import gooseui as _ui
except Exception as _e:                                              # noqa: BLE001
    try:
        from bridge import gooseui as _ui                            # type: ignore
    except Exception as _e2:                                         # noqa: BLE001
        _ui, _UI_ERR = None, (str(_e2) or str(_e))[:200]
        print(f"[gooseui] module unavailable — the embed lane is disabled ({_UI_ERR})",
              flush=True)

# ── the supervised goosed ────────────────────────────────────────────────────
# ONE process for the whole bridge, not one per tab. Desktop spawns a goosed per WINDOW
# because each window is a separate lease; we have one page and one fenced home, and two
# goosed on one sqlite session store is a corruption story rather than a feature.
_LOCK = threading.Lock()
_PROC: subprocess.Popen | None = None
_TOKEN = ""
_PORT = 0
_START_ERR = ""

# 40s: the pinned binary is a 270MB Mach-O whose first run pages in cold and builds the
# session DB. Measured cold start on this Mac was ~3-6s; this is generous, not hopeful.
_READY_TIMEOUT_S = 40.0


def _log(msg: str) -> None:
    """One line per lifecycle event into data/logs/gooseui.log — so a failed spawn is
    diagnosable without the tab having been open (the music-lane rule)."""
    line = f"[gooseui] {time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        p = ROOT / "data" / "logs" / "gooseui.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(line + "\n")
    except Exception:                                                # noqa: BLE001
        pass


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the goose UI module failed to load: {_UI_ERR}"},
        status_code=503)


def _bridge_port() -> int:
    try:
        return int((cfg().get("bridge") or {}).get("port") or 8700)
    except Exception:                                                # noqa: BLE001
        return 8700


def _runner() -> tuple:
    """(endpoint, api_key, port, live_id, wire_id). Best-effort — a runner that is down
    must cost the MODEL, never the page: goose's own provider UI is reachable without
    one and telling the user "no model loaded" inside a working UI beats a 503."""
    rc = cfg().get("runner") or {}
    port = int(rc.get("port") or 6767)
    live = ""
    try:
        live = _live_model_id(port) or ""
    except Exception:                                                # noqa: BLE001
        live = ""
    wire = ""
    if live:
        try:
            wire = wire_model_id(live, _registry_models()) or live
        except Exception:                                            # noqa: BLE001
            wire = live
    return (rc.get("endpoint") or ""), (rc.get("api_key") or ""), port, live, wire


def _alive() -> bool:
    return bool(_PROC is not None and _PROC.poll() is None)


def _probe(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(_ui.status_url(port), timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _free_port(preferred: int) -> int:
    """The preferred port if nothing holds it, else an ephemeral one.

    ⚠️ NOT a bare bind-and-close race-free claim, and it does not need to be: if
    something takes the port between the check and the spawn, `goose serve` fails to
    bind and _ensure() reports that failure with its stderr. What this avoids is the
    much likelier and much more confusing case — OUR OWN previous goosed still listening
    after a bridge restart, which would make the new one die and the tab blame goose.

    ⚠️ AND IT MOVES ASIDE — IT NEVER CLEARS. A held port is somebody's, and on this Mac
    that somebody is very often Debi's standalone goose Desktop, whose backend picks a
    port at runtime. `lsof -ti tcp:N | xargs kill` is the move that closed her app twice
    during this spike. The correct answer to a busy port is another port; see is_ours().
    """
    import socket
    for p in (int(preferred), 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            got = s.getsockname()[1]
            return got
        except OSError:
            continue
        finally:
            s.close()
    return int(preferred)


def _write_pidfile(pid: int) -> None:
    """THE MEMORY LEDGER'S HANDLE. core/memory.py builds one row per data/<name>.pid, so
    this is what makes the embedded goosed appear BY NAME with its real footprint — and
    what makes ./scripts/stop.sh stop it. Removed on exit, so never a ghost row."""
    try:
        p = _ui.pidfile_path(ROOT)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(str(int(pid)))
    except (OSError, TypeError, ValueError):                         # noqa: BLE001
        pass


def _clear_pidfile() -> None:
    try:
        os.unlink(_ui.pidfile_path(ROOT))
    except OSError:
        pass


def _reap_orphan() -> bool:
    """True when we actually signalled an orphan of ours. A goosed WE started that
    outlived the bridge that started it.

    ⚠️ THE RETURN VALUE IS NOT DECORATION. _stop_locked answers the user with it, and
    "gone" when a process was in fact terminated is a small lie in the same family as
    every other silently-wrong answer this project ranks worst.

    The bridge restarts far more often than a supervised child needs to, and without
    this the old one keeps its port and its sqlite session store while the new one opens
    a second store — two writers, one DB. So: read our own pidfile, and act ONLY if
    is_ours() confirms the pid is our fenced goosed. Anything else (recycled pid, a
    stale file, Debi's Desktop) gets the pidfile deleted and NOT A SIGNAL.
    """
    try:
        with open(_ui.pidfile_path(ROOT)) as fh:
            pid = int((fh.read() or "0").strip() or 0)
    except (OSError, ValueError):
        return False
    if not is_ours(pid):
        _log(f"stale pidfile for pid {pid} (not provably ours) — cleared, not signalled")
        _clear_pidfile()
        return False
    done = False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        _log(f"reaped our orphaned goosed pid={pid}")
        done = True
    except (OSError, ProcessLookupError):
        pass
    _clear_pidfile()
    return done


def _ensure() -> tuple:
    """(acp_url, error). Start the supervised goosed if it is not already up, and wait
    for /status. Idempotent and serialised — two tabs opening at once must not race two
    goosed onto one session DB.

    ⚠️ EVERY CALLER GETS THE SAME ONE REFUSAL PATH. The page route, the status route and
    the explicit start button all come through here, so there is exactly one place where
    "not installed", "no port", "did not become ready" are worded — and exactly one seam
    for the tests to substitute.
    """
    global _PROC, _TOKEN, _PORT, _START_ERR
    if _ui is None:
        return "", f"the goose UI module failed to load: {_UI_ERR}"
    with _LOCK:
        if _alive() and _probe(_PORT):
            return _ui.acp_url(_PORT, _TOKEN), ""
        if _alive():
            # The process is up but not answering /status yet (or has wedged). Give it
            # the remainder of the readiness budget rather than spawning a second one.
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if _probe(_PORT):
                    return _ui.acp_url(_PORT, _TOKEN), ""
                time.sleep(0.2)
            _stop_locked("wedged")

        _reap_orphan()

        ok, reason = _ui.is_installed(ROOT)
        if not ok:
            _START_ERR = reason
            return "", reason

        endpoint, api_key, rport, _live, wire = _runner()
        workspace = _ui.workspace_path(ROOT)
        try:
            os.makedirs(workspace, exist_ok=True)
            os.makedirs(_ui.path_root(ROOT), exist_ok=True)
        except OSError as e:
            _START_ERR = f"cannot create the goose UI workspace/home: {e}"
            return "", _START_ERR
        # ⚠️ READ THE USER'S CONFIG *BEFORE* SEEDING IT, and hand the SAME text to the
        # env builder. Both halves of the migration decision (has the user already
        # chosen a provider inside goose?) must come from ONE snapshot: seeding first
        # and reading after would read our own write back and conclude the choice was
        # always ours.
        before = _ui.read_config(ROOT)
        # Re-seeded on EVERY start, not once: the runner's port, key or loaded model can
        # change between sessions, and a config that was right in July is a 404 now. The
        # registry goes with it so "MOT Deck (local)" lists EVERY model rather than the
        # loaded one — the picker then holds facts and stays populated with the runner
        # down, which is OpenCode's property and the whole point of isolation mode.
        _ui.seed_config(ROOT, endpoint, wire, rport, _registry_models())

        _TOKEN = _ui.new_token()
        _PORT = _free_port(_ui.DEFAULT_ACP_PORT)
        argv = _ui.serve_argv(ROOT, _PORT)
        for origin in _ui.allowed_origins(_bridge_port()):
            argv += ["--allowed-origin", origin]
        env = _ui.serve_env(os.environ, ROOT, _TOKEN, endpoint, api_key, wire, rport,
                            config_text=before)
        logp = ROOT / "data" / "logs" / "gooseui-serve.log"
        try:
            logp.parent.mkdir(parents=True, exist_ok=True)
            fh = open(logp, "ab")
            _PROC = subprocess.Popen(argv, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                     stdout=fh, stderr=fh, start_new_session=True)
        except Exception as e:                                       # noqa: BLE001
            _PROC = None
            _START_ERR = f"could not start goose serve: {e}"
            _log(_START_ERR)
            return "", _START_ERR

        deadline = time.time() + _READY_TIMEOUT_S
        while time.time() < deadline:
            if _PROC.poll() is not None:
                _START_ERR = (f"goose serve exited immediately (code {_PROC.returncode}) "
                              "— see data/logs/gooseui-serve.log")
                _log(_START_ERR)
                _PROC = None
                return "", _START_ERR
            if _probe(_PORT):
                _write_pidfile(_PROC.pid)
                _START_ERR = ""
                _log(f"serve ready pid={_PROC.pid} port={_PORT} model={wire or '(none)'} "
                     f"path_root={_ui.path_root(ROOT)}")
                return _ui.acp_url(_PORT, _TOKEN), ""
            time.sleep(0.25)

        _stop_locked("timeout")
        _START_ERR = (f"goose serve did not answer {_ui.status_url(_PORT)} within "
                      f"{int(_READY_TIMEOUT_S)}s — see data/logs/gooseui-serve.log")
        _log(_START_ERR)
        return "", _START_ERR


def is_ours(pid) -> bool:
    """⚠️ READ IDENTITY BEFORE KILL. THE RULE, AND WHY IT IS A FUNCTION AND NOT A HABIT.

    Debi runs the STANDALONE goose Desktop app on this same Mac, and it spawns its own
    `goose serve --platform desktop` child on a port it picks at runtime. Anything that
    kills "the process on port N", or `pkill -f goose`, can therefore terminate HER
    backend — which shows up as her Desktop window dying with "This window's Goose
    backend stopped". It happened twice during this spike, from a throwaway restart
    helper that did `lsof -ti tcp:3287 | xargs kill -9`. It is the SAME incident as the
    Unsloth one, and the general lesson is the one in the name: a process is only ours
    if its IDENTITY says so — never if a port, a name, or a pattern says so.

    Identity here is two facts read off the live process with `ps -Eww` (which prints
    the environment): the executable is OUR pinned binary under this ROOT, and its
    GOOSE_PATH_ROOT is OUR fenced home. Debi's app satisfies neither — it runs the copy
    inside Goose.app (an App-Translocated path) and carries no GOOSE_PATH_ROOT at all.

    False on ANY doubt: a pid we cannot positively identify is a pid we do not kill.
    Losing our own orphan costs a port; killing hers costs her work.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 1:
        return False
    try:
        out = subprocess.run(["ps", "-Eww", "-o", "command=", "-p", str(pid)],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    if not out.strip():
        return False
    return (_ui is not None
            and _ui.goose_bin(ROOT) in out
            and f"GOOSE_PATH_ROOT={_ui.path_root(ROOT)}" in out)


def _stop_locked(why: str) -> str:
    """Caller holds _LOCK. SIGTERM then SIGKILL the whole process GROUP — goosed spawns
    MCP extension children, and killing only the parent leaves them holding the port.

    ⚠️ EVERY SIGNAL IN HERE IS GATED ON is_ours(). We hold a real Popen handle, so this
    is belt-and-braces — but a pid can be recycled after a crash, and `killpg` on a
    recycled pid's GROUP is about the widest-blast-radius mistake available. See the
    docstring above for the incident this exists after.
    """
    global _PROC
    p = _PROC
    _PROC = None
    if p is None or p.poll() is not None:
        # ⚠️ A5 — WALKED, NOT IMAGINED (2026-08-29). The bridge restarted between a
        # /start and a /stop; the new process had no Popen handle, this branch cleared
        # the pidfile and answered "gone" — and a LIVE, fenced goosed of ours kept its
        # port and its sqlite session store with the ONLY handle to it just deleted.
        # (Two of our goosed were then listening at once, which is the two-writers-on-
        # one-DB story _reap_orphan exists to prevent.) The pidfile IS the cross-restart
        # handle, so "no handle in memory" must consult it BEFORE erasing it — and
        # _reap_orphan is already the identity-verified way to do exactly that.
        return "reaped" if _reap_orphan() else "gone"
    _clear_pidfile()
    if not is_ours(p.pid):
        _log(f"REFUSED to signal pid {p.pid}: it is not provably our goosed "
             f"(no {_ui.path_root(ROOT) if _ui else '?'} in its env). Left running.")
        return "not-ours"
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        p.wait(timeout=5)
        _log(f"serve stopped ({why}, SIGTERM)")
        return "term"
    except subprocess.TimeoutExpired:
        pass
    if not is_ours(p.pid):
        return "term"
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    _log(f"serve stopped ({why}, SIGKILL)")
    return "kill"


# ── routes ───────────────────────────────────────────────────────────────────
@app.get("/gooseui")
def gooseui_page_redirect() -> Response:
    """⚠️ THE TRAILING SLASH IS LOAD-BEARING, AND THE FIRST DRAFT SHIPPED WITHOUT IT.

    The vendored entry document references its bundle RELATIVELY —
    `<script type="module" src="./assets/index-YGtEK3wY.js">`. Served at `/gooseui`,
    `./assets/…` resolves against the PARENT, i.e. `/assets/…` — which in this harness is
    a real, occupied mount (bridge/panel/assets, the Univer/React vendor tree). So the
    page did not 404 into an obvious hole: it asked OUR OWN asset route for goose's
    bundle, got 404s, and rendered a black rectangle with no error a user could act on.
    Measured in a real browser; nothing in review would have caught it.

    A 308 to the slash form is the fix, and it is preferred over injecting a `<base>`
    tag: `<base>` silently re-bases every relative URL in the app — anchors, form
    actions, `new URL('…', import.meta.url)` — for the benefit of two script tags. The
    redirect changes nothing about the document.
    """
    return RedirectResponse(f"{_ui.ROUTE_PREFIX}/" if _ui is not None else "/gooseui/",
                            status_code=308)


@app.get("/gooseui/")
def gooseui_page() -> Response:
    """OUR entry document: the vendored index.html with ONE extra <script> tag.

    ⚠️ IT STARTS goosed. A page that loaded and then said "click Start" would be a dead
    click for a lane whose only precondition is a process WE own — the graceful-absence
    rule, applied to a dependency we can satisfy ourselves. What it must never do is lie:
    if the start fails, this returns a readable page saying exactly what failed and how
    to fix it, NOT the goose UI with a broken socket behind it (which reads as "goose is
    broken" and sends the user upstream).
    """
    if _ui is None:
        return HTMLResponse(_fallback_page(f"the goose UI module failed to load: "
                                           f"{_UI_ERR}"), status_code=503)
    # ⚠️ THE EMPTY STATE COMES FIRST, AND IT IS AN ACTION, NOT AN APOLOGY (Debi's ruling,
    # 2026-08-29 — the house component pattern). A tab opened before anything is
    # provisioned shows an INSTALL button with the download size on it, then progress,
    # then Start. Telling the user to go and run a shell script is the shape this
    # replaces: every component in this product self-provisions.
    st = _ui.install_state(ROOT)
    if not st["ready"]:
        return HTMLResponse(_empty_state_page(st), status_code=200)
    acp, err = _ensure()
    if err:
        return HTMLResponse(_fallback_page(err), status_code=503)
    try:
        with open(os.path.join(_ui.ui_dir(ROOT), _ui.ENTRY_HTML), encoding="utf-8") as fh:
            index_html = fh.read()
    except OSError as e:
        return HTMLResponse(_fallback_page(f"the vendored bundle is unreadable: {e}"),
                            status_code=503)
    html = _ui.page_html(index_html, f"{_ui.ROUTE_PREFIX}/{_ui.PRELOAD_NAME}")
    return HTMLResponse(html, headers={"Cache-Control": _ui.NO_CACHE, "Pragma": "no-cache"})


def _fallback_page(reason: str) -> str:
    """Graceful absence, spelled out. Every state this lane can reach lands on something
    a human can read and act on — never a blank tab and never a raw JSON blob."""
    safe = (reason or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # The literal is duplicated ONCE, here, so a gooseui.py that failed to import can
    # still name the surface correctly — the same reasoning as routers/oo.py's
    # _OO_FALLBACK_HEADERS.
    name = _ui.SURFACE_NAME if _ui is not None else "Goose UI"
    return (f"<!doctype html><meta charset=utf-8><title>{name}</title>"
            "<style>body{font:14px/1.6 -apple-system,system-ui,sans-serif;margin:0;"
            "padding:48px;background:#111;color:#eee}code{background:#222;padding:2px 6px;"
            "border-radius:4px}a{color:#8bf}</style>"
            f"<h2>{name} cannot start</h2>"
            f"<p>{safe}</p>"
            "<p>What usually fixes it:</p><ul>"
            "<li>the goose binary: <code>./scripts/install_goose.sh</code></li>"
            "<li>the UI bundle: <code>./scripts/install_goose_ui.sh</code></li>"
            "<li>the log: <code>data/logs/gooseui-serve.log</code></li></ul>"
            "<p>The terminal lane is unaffected: <a href='/goose'>/goose</a>.</p>")


_PAGE_CSS = (
    "body{font:14px/1.6 -apple-system,system-ui,sans-serif;margin:0;padding:48px;"
    "background:#0b0a10;color:#eee}code{background:#1c1b24;padding:2px 6px;"
    "border-radius:4px;font:12px/1.5 ui-monospace,Menlo,monospace}a{color:#8bf}"
    "h2{font-weight:600;margin:0 0 6px}p{color:#bdbac6;max-width:62ch}"
    "button{font:inherit;font-weight:600;padding:10px 20px;border-radius:9px;"
    "border:0;background:#6f5bff;color:#fff;cursor:pointer}"
    "button[disabled]{opacity:.55;cursor:default}"
    ".sub{color:#7d7a89;font-size:12px}.row{display:flex;gap:12px;align-items:center;"
    "margin:22px 0}pre{background:#131219;padding:12px;border-radius:8px;"
    "max-height:240px;overflow:auto;font-size:11px;color:#a9a6b6;white-space:pre-wrap}")


def _empty_state_page(st: dict) -> str:
    """THE EMPTY STATE: Install (with the real size on the button) → progress → Start.

    ⚠️ THE TWO ARTIFACTS ARE NAMED SEPARATELY AND SIZED HONESTLY. The 209MB is stated up
    front with what survives it (7MB), because a button that quietly starts a
    quarter-gigabyte download is the surprise this product does not ship. A user who
    already installed the terminal lane's goose binary sees only the bundle step.

    ⚠️ AND IT POLLS THE SAME /api/gooseui/status THE REST OF THE LANE USES — there is no
    second source of truth about whether this thing is installed, so the page cannot
    disagree with the API about what the user is looking at.
    """
    need = []
    if not st["binary"]:
        need.append("the goose binary (~270MB extracted, shared with the Goose CLI tab)")
    if not st["bundle"]:
        need.append(f"the goose UI bundle ({st['asset_mb']}MB download, "
                    f"{st['kept_mb']}MB kept)")
    what = " and ".join(need)
    return f"""<!doctype html><meta charset=utf-8><title>{_ui.SURFACE_NAME}</title>
<style>{_PAGE_CSS}</style>
<h2>{_ui.SURFACE_NAME}</h2>
<p>goose Desktop's own interface, served here and wired to your local runner. It needs
{what} before it can open.</p>
<p class=sub>Everything is verified against a pinned sha256 before a byte is unpacked:
{st['asset']} &nbsp;<code>{st['asset_sha256'][:16]}…</code> from goose
{st['app_version']}. The bundle is served unmodified.</p>
<div class=row><button id=go>Install ({st['asset_mb']} MB download)</button>
<span id=msg class=sub></span></div>
<pre id=log hidden></pre>
<p class=sub>The terminal lane is unaffected either way: <a href="/goose">/goose</a>.</p>
<script>
var go=document.getElementById('go'),msg=document.getElementById('msg'),
    log=document.getElementById('log'),t0=0;
function poll(){{
  fetch('/api/gooseui/status').then(function(r){{return r.json()}}).then(function(s){{
    if(s.install_error){{
      go.disabled=false; go.textContent='Try again';
      msg.textContent='install failed';
      log.hidden=false; log.textContent=s.install_error; return;
    }}
    if(s.installed){{ msg.textContent='installed — starting…'; location.reload(); return; }}
    if(s.installing){{
      var secs=Math.round((Date.now()-t0)/1000);
      msg.textContent='downloading and verifying… '+secs+'s';
      setTimeout(poll,1500); return;
    }}
    go.disabled=false; msg.textContent='';
  }}).catch(function(){{ setTimeout(poll,2000); }});
}}
go.onclick=function(){{
  go.disabled=true; t0=Date.now(); msg.textContent='starting…'; log.hidden=true;
  fetch('/api/gooseui/install',{{method:'POST'}}).then(function(){{setTimeout(poll,800)}})
    .catch(function(){{ go.disabled=false; msg.textContent='could not reach the bridge'; }});
}};
// A tab reopened DURING an install must show the progress, not an Install button that
// would start a second one. The status call answers that before the user can click.
poll();
</script>"""


@app.get("/gooseui/harness-preload.js")
def gooseui_preload() -> Response:
    """OUR window.electron / window.appConfig shim — GENERATED, never a file on disk.

    ⚠️ NEVER CACHED. It carries the ACP url and the per-process token, which change every
    time goosed restarts; a cached copy would point a fresh page at a dead socket, which
    is the "it worked yesterday" class of bug.
    """
    if _ui is None:
        return Response(f"/* {_UI_ERR} */", media_type="text/javascript",
                        status_code=503)
    acp, err = _ensure()
    _endpoint, _key, _rport, live, wire = _runner()
    src = _ui.preload_js({
        "acp_url": acp,
        "secret": _TOKEN,
        "app_config": _ui.app_config(_ui.PIN_APP_VERSION, _ui.workspace_path(ROOT),
                                     wire, "openai" if wire else ""),
    })
    if err:
        # The shim still installs — with no ACP url. The renderer's own error path then
        # says "ACP URL is not available" IN ITS OWN UI, which is a better place for the
        # message than a console. Our reason goes to the console beside it.
        src = (f"console.error('[goose-embed] backend not started: '"
               f" + {json.dumps(err)});\n" + src)
    return Response(src, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": _ui.NO_CACHE})


@app.get("/gooseui/{rel:path}")
def gooseui_asset(rel: str, request: Request) -> Response:
    """The vendored bundle, read-only: containment + forced MIME + immutable cache.

    Deliberately NOT a StaticFiles mount, for the /oo/* precedent's reason: a mount
    cannot set per-response headers without a middleware wrapper, and this route's whole
    job is per-response.
    """
    if _ui is None:
        return _unavailable()
    target, reason = _ui.bundle_target(ROOT, rel)
    if not target:
        # 404 for everything, refused traversals included — telling a caller which of its
        # guesses was "outside the bundle" is free reconnaissance.
        return JSONResponse({"ok": False, "error": reason}, status_code=404)
    return FileResponse(target, media_type=_ui.media_type_for(target),
                        headers={"Cache-Control": _ui.IMMUTABLE_CACHE})


def _provider_status() -> dict:
    """The named provider, as facts read off disk — never a stored flag.

    ⚠️ `provider_models` counts what is IN THE FILE, not what a probe returned. That is
    the number the picker will actually show, including with the runner down, and
    reporting anything else here would be this project's worst class of bug in its
    smallest possible form.
    """
    try:
        from .. import gooseprov as _p
    except Exception:                                                # noqa: BLE001
        return {}
    doc = _p.read_provider(_ui.config_dir(ROOT))
    cfg_text = _ui.read_config(ROOT)
    chosen, migrate = _p.provider_choice(cfg_text)
    return {
        "provider_name": _p.PROVIDER_NAME,
        "provider_display": (doc or {}).get("display_name") or _p.DISPLAY_NAME,
        "provider_file": _ui.provider_path(ROOT),
        "provider_seeded": bool(doc),
        "provider_models": len((doc or {}).get("models") or []),
        "provider_key_env": _p.api_key_env(),
        # '' when the user has picked something of their own — which is the case in
        # which we deliberately set no GOOSE_PROVIDER at all.
        "active_provider": _p.active_provider(cfg_text),
        "provider_is_ours": bool(migrate and chosen),
    }


@app.get("/api/gooseui/status")
def gooseui_status() -> JSONResponse:
    """Everything the tab (and a human in a terminal) needs to know in ONE body."""
    if _ui is None:
        return _unavailable()
    installed, reason = _ui.is_installed(ROOT)
    _endpoint, _key, rport, live, wire = _runner()
    running = _alive()
    with _INSTALL_LOCK:
        inst = dict(_INSTALLING)
    return JSONResponse({
        "ok": True,
        "installed": bool(installed),
        "reason": reason,
        "installing": bool(inst.get("since") and not inst.get("done")),
        "install_error": inst.get("error") or "",
        **{f"have_{k}": v for k, v in _ui.install_state(ROOT).items()
           if k in ("binary", "bundle")},
        "asset": _ui.PIN_ASSET,
        "asset_size": _ui.PIN_ASSET_SIZE,
        "asset_sha256": _ui.PIN_ASSET_SHA256,
        "app_version": _ui.PIN_APP_VERSION,
        "asar_sha256": _ui.PIN_ASAR_SHA256,
        "bundle_sha256": _ui.bundle_sha(ROOT),
        "running": running,
        "acp_port": _PORT if running else 0,
        # ⚠️ THE URL WITHOUT THE TOKEN. A status endpoint is the wrong place to hand out
        # a live credential; the page gets the real one through the preload route.
        "acp_url": _ui.acp_url(_PORT, "REDACTED") if running else "",
        "healthy": bool(running and _probe(_PORT)),
        "start_error": _START_ERR,
        "model": live or "",
        "wire_model": wire or "",
        "runner_port": rport,
        "path_root": _ui.path_root(ROOT),
        "workspace": _ui.workspace_path(ROOT),
        # THE NAMED PROVIDER, answerable from the API rather than only from a report:
        # what it is called, where its file is, whether it is on disk, how many models
        # it lists, and whose choice the main provider currently is.
        **_provider_status(),
        # Named out loud so "do the two lanes collide?" is answerable from the API and
        # not only from a builder's report.
        "pty_lane_home": os.path.join(str(ROOT), "data", "goose", "home"),
        "page": _ui.ROUTE_PREFIX,
        "shimmed": list(_ui.SHIMMED),
        "stubbed": list(_ui.STUBBED),
        "degraded": dict(_ui.DEGRADED),
    })


_INSTALLING: dict = {}          # {"since": ts|None, "done": bool, "error": str}
_INSTALL_LOCK = threading.Lock()
# 30 min: one 209MB download, three sha256 passes and an unpack. Nothing compiles and
# nothing resolves a dependency graph — this is generous, not hopeful.
_INSTALL_TIMEOUT = 1800


def _install_thread() -> None:
    """Provision what is missing, in order, and report the FIRST failure honestly.

    ⚠️ THE BINARY INSTALLER IS REUSED, NOT REIMPLEMENTED. scripts/install_goose.sh
    already pins the binary by two digests and the terminal lane already ships it; a
    second copy of that logic here would be a second pin to keep in step.
    """
    err = ""
    try:
        if not _ui.has_binary(ROOT):
            r = _script(_ui.BIN_INSTALLER, timeout=_INSTALL_TIMEOUT)
            if r.returncode != 0:
                err = (r.stdout + r.stderr)[-1500:]
        if not err and not _ui.has_bundle(ROOT):
            r = _script(_ui.INSTALLER, timeout=_INSTALL_TIMEOUT)
            if r.returncode != 0:
                err = (r.stdout + r.stderr)[-1500:]
    except subprocess.TimeoutExpired:
        err = ("the install timed out after 30 minutes — run it in a terminal to see "
               f"where it stalls: ./scripts/{_ui.INSTALLER}")
    except Exception as e:                                           # noqa: BLE001
        err = f"the install crashed: {e}"[:1500]
    with _INSTALL_LOCK:
        _INSTALLING.update({"since": None, "done": True, "error": err})
    _log(f"install: {'ok' if not err else 'FAILED'}")


@app.post("/api/gooseui/install")
def gooseui_install() -> JSONResponse:
    """Download + digest-verify + unpack in the background; the page polls /status.

    A second POST while one is running is a 409, not a second download — the installer
    itself refuses on its staging lock too, so this is belt-and-braces rather than the
    only guard (two writers on one partial download is the comfy A-10 defect).
    """
    if _ui is None:
        return _unavailable()
    with _INSTALL_LOCK:
        if _INSTALLING.get("since") and not _INSTALLING.get("done"):
            return JSONResponse({"ok": False, "error": "already installing"},
                                status_code=409)
        _INSTALLING.clear()
        _INSTALLING.update({"since": time.time(), "done": False, "error": ""})
    threading.Thread(target=_install_thread, daemon=True).start()
    _log("install started")
    return JSONResponse({"ok": True, "installing": True})


@app.post("/api/gooseui/start")
def gooseui_start() -> JSONResponse:
    if _ui is None:
        return _unavailable()
    acp, err = _ensure()
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=503)
    return JSONResponse({"ok": True, "running": True, "acp_port": _PORT,
                         "acp_url": _ui.acp_url(_PORT, "REDACTED")})


@app.post("/api/gooseui/stop")
def gooseui_stop() -> JSONResponse:
    if _ui is None:
        return _unavailable()
    with _LOCK:
        how = _stop_locked("requested")
    return JSONResponse({"ok": True, "stopped": how})
