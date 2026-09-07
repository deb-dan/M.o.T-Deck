#!/usr/bin/env python3
"""AIDER LANE slice 1 — the decision tables + a REAL websocket/PTY round trip.

Built to docs/research/2026-08-20-aider-recon.md. Three things in here are load-bearing
rather than decorative:

1. THE ORIGIN GATE. WebSockets are not subject to CORS, so this function is the only
   thing between a random web page and a process on the user's Mac. It is table-tested
   in both directions AND exercised for real through the mounted app (the refusal must
   arrive as close code 4403 with nothing spawned).
2. THE ARGV. Every lockdown flag present, and `--yes-always` / `--no-git` asserted
   ABSENT — the first would delete aider's own approval prompt (the entire reason a PTY
   is the honest surface here), the second would delete /undo while keeping every bit of
   the write power.
3. THE RESIZE ESCAPE. Consumed server-side, never written to the PTY, always clamped.
   An escape that reached the terminal would render as text; an unclamped ioctl wedges
   the renderer.

The session manager is NOT mocked: it is run against /bin/cat and /bin/sh, so the fd
handling, the EOF-on-child-exit path and the process-GROUP teardown are proven rather
than argued. Only the aider binary itself is substituted (it is not installed here).

Run: python3 bridge/tests/test_aider_lane.py
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

from bridge import pty_aider as P                                   # noqa: E402

CHECKS = 0


def ok(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, f"FAIL: {label}"


# ── 1. the origin gate ───────────────────────────────────────────────────────
def test_origin_gate():
    for good in ("http://127.0.0.1:8700", "http://localhost:8700",
                 "http://127.0.0.1:8700/", "  http://localhost:8700  "):
        ok(P.origin_allowed(good, 8700), f"allowed: {good!r}")
    bad = [
        "http://evil.example",              # the actual attack
        "https://127.0.0.1:8700",           # scheme must match — no https page of ours
        "http://127.0.0.1:8701",            # another port on the same host
        "http://127.0.0.1",                 # portless
        "http://127.0.0.1:8700.evil.com",   # prefix trick
        "http://evil.com/http://127.0.0.1:8700",
        "http://127.0.0.1:8700@evil.com",
        "file://",
        "null",                             # a sandboxed iframe's opaque origin
        "", None, 0, [], {}, b"http://127.0.0.1:8700",
    ]
    for b in bad:
        ok(not P.origin_allowed(b, 8700), f"refused: {b!r}")
    # A MISSING header is refused — a browser page always sends one.
    ok(not P.origin_allowed(None, 8700), "missing Origin is refused")
    # The allowlist follows the configured port, so a re-ported bridge is not locked out.
    ok(P.origin_allowed("http://127.0.0.1:9000", 9000), "port comes from config")
    ok(not P.origin_allowed("http://127.0.0.1:8700", 9000), "old port not grandfathered")
    ok(len(P.allowed_origins(8700)) == 2, "exactly two origins, no wildcards")


# ── 2. the resize control message ────────────────────────────────────────────
def test_resize():
    clean, sizes = P.split_resize(b"hello\x1b[RESIZE:120;40]world")
    ok(clean == b"helloworld", "escape stripped from the middle")
    ok(sizes == [(120, 40)], "cols;rows parsed in that order")
    # NEVER written to the PTY, in any position.
    for payload in (b"\x1b[RESIZE:80;24]", b"\x1b[RESIZE:80;24]x", b"y\x1b[RESIZE:80;24]"):
        c, s = P.split_resize(payload)
        ok(b"RESIZE" not in c, f"escape never reaches the pty: {payload!r}")
        ok(s == [(80, 24)], f"size read: {payload!r}")
    c, s = P.split_resize(b"a\x1b[RESIZE:10;5]b\x1b[RESIZE:11;6]c")
    ok(c == b"abc" and s == [(10, 5), (11, 6)], "several escapes in one message")
    # Clamping — WSL2-style nonsense and zero/negative must not reach the ioctl.
    _c, s = P.split_resize(b"\x1b[RESIZE:131072;99999]")
    ok(s == [(P.MAX_COLS, P.MAX_ROWS)], "absurd dimensions clamped to the ceiling")
    _c, s = P.split_resize(b"\x1b[RESIZE:0;0]")
    ok(s == [(P.MIN_COLS, P.MIN_ROWS)], "zero clamped to the floor")
    # Junk totality — the regex only matches digits, so a malformed escape is DATA.
    for junk in (b"\x1b[RESIZE:abc;def]", b"\x1b[RESIZE:;]", b"\x1b[RESIZE:80]",
                 b"\x1b[RESIZE 80;24]", b"[RESIZE:80;24]"):
        c, s = P.split_resize(junk)
        ok(s == [] and c == junk, f"malformed escape passes through as data: {junk!r}")
    ok(P.split_resize(b"") == (b"", []), "empty message")
    ok(P.split_resize(None) == (b"", []), "None is not a crash")
    # Raw bytes are otherwise untouched — a terminal stream is not text.
    raw = bytes(range(256))
    ok(P.split_resize(raw)[0] == raw, "arbitrary bytes pass through byte-for-byte")
    # clamp_dim totality
    for junk in (None, "", "x", [], {}, object(), float("nan")):
        ok(P.clamp_dim(junk, 2, 200, 100) == 100, f"clamp falls back: {junk!r}")
    ok(P.clamp_dim("80", 2, 200, 100) == 80, "numeric string accepted")
    ok(P.clamp_dim(3.9, 2, 200, 100) == 3, "float truncates, never raises")


# ── 3. the launch line ───────────────────────────────────────────────────────
def test_argv():
    argv = P.aider_argv("/h", "gemma-4-31B-q4")
    ok(argv[0] == "/h/data/aider-venv/bin/aider", "explicit venv path, never PATH lookup")
    ok(argv[1] == "--model" and argv[2] == "openai/gemma-4-31B-q4",
       "the openai/ prefix is what routes litellm at our runner")
    ok("--edit-format" in argv and argv[argv.index("--edit-format") + 1] == "whole",
       "whole is the only format a 4B reliably produces")
    for flag in P.LOCKDOWN_FLAGS:
        ok(flag in argv, f"lockdown flag present: {flag}")
    # THE TWO NEGATIVES. These are the assertions with teeth.
    for forbidden in P.FORBIDDEN_FLAGS:
        ok(forbidden not in argv, f"NEVER passed: {forbidden}")
    ok("--yes-always" in P.FORBIDDEN_FLAGS and "--no-git" in P.FORBIDDEN_FLAGS,
       "the forbidden set names both")
    ok("--analytics-disable" in argv and "--no-analytics" not in argv,
       "the PERMANENT opt-out, not the session-only one (mixpanel+posthog are core deps)")
    ok("--disable-playwright" in argv,
       "without it aider can block on stdin asking to install playwright, inside our tab")
    ok("--no-auto-commits" in argv, "edits stay uncommitted")
    # git stays ON: --no-git would remove /undo and /diff, the only undo aider has.
    ok(not any(a == "--no-git" for a in argv), "git is left enabled deliberately")
    # MLX: the wire id is a PATH, and it must survive verbatim into the argv.
    mlx = P.aider_argv("/h", "/Users/d/data/models/Qwen3-mlx")
    ok(mlx[2] == "openai//Users/d/data/models/Qwen3-mlx",
       "an MLX path goes on the wire unchanged (mlx_lm.server resolves it as a load)")
    # Totality: an empty/None model still produces a well-formed (if useless) line.
    for m in ("", None):
        a = P.aider_argv("/h", m)
        ok(a[2] == "openai/", f"empty model does not corrupt the argv: {m!r}")
    ok(P.aider_argv("/h", "x", "")[4] == "whole", "empty edit format -> the default")
    ok(P.aider_argv("/h", "x", "diff")[4] == "diff", "an explicit format is honoured")


def test_env():
    env = P.aider_env({"PATH": "/usr/bin", "COLUMNS": "999", "LINES": "9"},
                      "http://127.0.0.1:6767/v1", "motdeck-local")
    ok(env["OPENAI_API_BASE"] == "http://127.0.0.1:6767/v1", "base url")
    ok(env["OPENAI_API_KEY"] == "motdeck-local", "key forwarded")
    ok(env["TERM"] == "xterm-256color", "a real TERM (rich + prompt_toolkit need one)")
    ok("COLUMNS" not in env and "LINES" not in env,
       "COLUMNS/LINES removed — the winsize ioctl owns the size")
    ok(env["PATH"] == "/usr/bin", "the rest of the environment is inherited")
    # A provisioned key is mandatory: silently restoring the retired repository
    # default would make the lane disagree with the runner after secret rotation.
    for empty in ("", "   ", None):
        try:
            P.aider_env({}, "u", empty)
        except ValueError as exc:
            ok("not provisioned" in str(exc), f"empty key refused: {empty!r}")
        else:
            ok(False, f"empty key must be refused: {empty!r}")
    ok(P.aider_env(None, "u", "k")["OPENAI_API_KEY"] == "k", "None base env is fine")


# ── 4. install detection, from disk ──────────────────────────────────────────
def test_installed():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        ok(P.is_installed(d)[0] is False, "empty tree = not installed")
        binp = Path(d) / P.VENV_DIR / "bin"
        binp.mkdir(parents=True)
        (binp / "aider").write_text("#!/bin/sh\n")
        ok(P.is_installed(d)[0] is False, "present but not executable = not installed")
        os.chmod(binp / "aider", 0o755)
        okk, path, _r = P.is_installed(d)
        ok(okk and path == str(binp / "aider"), "executable = installed, with its path")
        # It is read FROM DISK every time — never a cached flag.
        os.remove(binp / "aider")
        ok(P.is_installed(d)[0] is False, "a deleted venv reads as not-installed at once")
        ok(P.workspace_path(d).endswith("data/aider-workspace"), "workspace path")
        ok("aider-workspace" in P.workspace_path(d) and
           not P.workspace_path(d).rstrip("/").endswith(os.path.expanduser("~")),
           "the workspace is never $HOME")


# ── 5. the session, run for real ─────────────────────────────────────────────
def test_session_roundtrip():
    sess = P.PtySession(["/bin/cat"], cwd="/tmp", env={"TERM": "dumb", "PATH": "/usr/bin:/bin"})
    sess.start(cols=90, rows=24)
    try:
        ok(sess.alive(), "child is running on the pty")
        sess.write(b"ping\n")
        got = b""
        deadline = time.time() + 5
        while b"ping" not in got and time.time() < deadline:
            got += sess.read()
        ok(b"ping" in got, "bytes go in and come back out of the pty")
        sess.resize(120, 40)          # must not raise on a live master fd
        ok(True, "resize on a live session is a no-throw ioctl")
    finally:
        how = sess.close()
    ok(how in ("term", "kill"), f"teardown killed the child ({how})")
    ok(not sess.alive(), "child is gone after close")
    ok(sess.close() == "gone", "close is idempotent")


def test_session_eof_and_group_kill():
    # 1. a child that exits on its own must produce b"" (EOF), or the reader thread in
    #    app.py would never end and the socket would hang open forever.
    sess = P.PtySession(["/bin/sh", "-c", "printf done; exit 0"], "/tmp",
                        {"PATH": "/bin:/usr/bin"})
    sess.start()
    out, deadline = b"", time.time() + 5
    while time.time() < deadline:
        chunk = sess.read()
        out += chunk
        if not chunk:
            break
    ok(b"done" in out, "the child's output arrived")
    ok(chunk == b"", "read() returns b'' when the child is gone (EOF, not an exception)")
    sess.close()

    # 2. THE PROCESS GROUP. aider spawns children (/run, linters); a dropped socket must
    #    take them with it. Without start_new_session=True this grandchild would survive.
    marker = f"/tmp/motdeck-aider-test-{os.getpid()}.pid"
    sess = P.PtySession(
        ["/bin/sh", "-c", f"sleep 300 & echo $! > {marker}; sleep 300"],
        "/tmp", {"PATH": "/bin:/usr/bin"})
    sess.start()
    deadline = time.time() + 5
    while not os.path.exists(marker) and time.time() < deadline:
        time.sleep(0.05)
    ok(os.path.exists(marker), "the grandchild started")
    gpid = int(open(marker).read().strip())
    sess.close()
    time.sleep(0.4)
    alive = subprocess.run(["/bin/ps", "-p", str(gpid)],
                           capture_output=True).returncode == 0
    ok(not alive, "the GRANDCHILD died too — the whole process group is killed")
    os.remove(marker)


def test_one_at_a_time():
    P.kill_current()
    a = P.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin"})
    a.start()
    try:
        ok(P.claim(a) is True, "the first session claims the slot")
        ok(P.busy() is True, "busy while it runs")
        b = P.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin"})
        ok(P.claim(b) is False, "a second claim is REFUSED (no queue)")
        ok(P.current() is a, "the slot still holds the first session")
    finally:
        a.close()
        P.release(a)
    ok(P.busy() is False, "released after teardown")
    c = P.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin"})
    ok(P.claim(c) is True, "the slot is reusable once free")
    P.release(c)
    # A dead-but-unreleased session must not block the next one forever.
    d = P.PtySession(["/bin/sh", "-c", "exit 0"], "/tmp", {"PATH": "/bin"})
    d.start()
    P.claim(d)
    time.sleep(0.3)
    e = P.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin"})
    ok(P.claim(e) is True, "a session whose child exited does not hold the slot")
    P.release(e)
    d.close()


# ── 6. the routes, through the real app ──────────────────────────────────────
def test_routes_live():
    """Mount the actual FastAPI app and drive the websocket. The only thing faked is
    aider_spawn_spec (aider is not installed in the sandbox); the origin gate, the byte
    relay, the resize consumption and the busy refusal are all the real code paths."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live route tests — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A

    ok(A._pty is not None, f"app imported pty_aider ({A._PTY_ERR})")
    P.kill_current()
    client = TestClient(A.app)

    # status
    r = client.get("/api/aider/status")
    ok(r.status_code == 200, "GET /api/aider/status is 200")
    body = r.json()
    for key in ("installed", "running", "model", "model_ready", "workspace"):
        ok(key in body, f"status carries {key}")
    ok(body["workspace"].endswith("data/aider-workspace"), "status names the workspace")
    # ⚠️ THE SHADOW FENCE (adversarial, caught on the goose lane's live walk
    # 2026-08-29 — the same two lines were here). The detach block added a local named
    # `live` on top of the model id, so `"model": live or ""` rendered "" and the tab
    # said NO MODEL LOADED while the runner was serving: the LIE class, from one
    # variable name.
    from bridge.core.modelid import _live_model_id as _lmi
    from bridge.core.procs import cfg as _cfg
    _p = int((_cfg().get("runner") or {}).get("port") or 6767)
    ok(body["model"] == (_lmi(_p) or ""),
       f"status reports the LIVE model, never a shadowed bool (got {body['model']!r})")
    ok(body["model_ready"] is bool(body["model"]), "…and model_ready agrees with it")

    # the page exists and loads the pinned assets by the names the fetch script writes
    page = (ROOT / "bridge" / "panel" / "aider.html").read_text()
    ok("/assets/vendor/xterm.js" in page, "the page loads self-hosted xterm.js")
    ok("/assets/vendor/xterm.css" in page, "…and its css")
    ok("/assets/vendor/xterm-addon-fit.js" in page, "…and the fit addon")
    ok("cdn." not in page and "https://" not in page, "no runtime CDN anywhere (offline)")
    ok("/api/pty/aider" in page and "\\x1b[RESIZE:" in page,
       "the page speaks the one control message")

    # THE ORIGIN GATE, live. A cross-origin handshake must be closed 4403 and must not
    # spawn anything — which is proved by the spec never being called.
    called = {"n": 0}
    real_spec = A.aider_spawn_spec

    def fake_spec():
        called["n"] += 1
        return (["/bin/cat"], {"PATH": "/bin:/usr/bin", "TERM": "xterm-256color"},
                "/tmp", "")
    A.aider_spawn_spec = fake_spec
    try:
        from starlette.testclient import WebSocketDenialResponse       # noqa: F401
    except Exception:                                                  # noqa: BLE001
        pass
    try:
        for bad_origin in ("http://evil.example", "http://127.0.0.1:9999"):
            with client.websocket_connect(
                    "/api/pty/aider", headers={"origin": bad_origin}) as ws:
                closed = ws.receive()
            ok(closed.get("type") == "websocket.close", f"{bad_origin} closed immediately")
            ok(closed.get("code") == P.CLOSE_ORIGIN,
               f"{bad_origin} refused with 4403 (got {closed.get('code')})")
        ok(called["n"] == 0, "NOTHING was spawned for a refused origin")

        good = {"origin": "http://127.0.0.1:8700"}
        with client.websocket_connect("/api/pty/aider?cols=90&rows=30",
                                      headers=good) as ws:
            ok(called["n"] == 1, "an allowed origin reaches the spawn path")
            ws.send_bytes(b"hello\n")
            got, deadline = b"", time.time() + 5
            while got.count(b"hello") < 1 and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"hello" in got, "bytes relayed through the websocket into the pty and back")

            # A resize message must be CONSUMED: /bin/cat echoes everything it is given,
            # so if the escape reached the pty it would come straight back at us.
            ws.send_bytes(b"\x1b[RESIZE:100;30]")
            ws.send_bytes(b"after\n")
            got, deadline = b"", time.time() + 5
            while b"after" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"RESIZE" not in got, "the resize escape never reached the pty")
            ok(b"after" in got, "…and the next real keystroke still arrived")

            # ══ DEBI'S SCREENSHOT, WALKED (2026-08-29, ledger U10) ═════════════
            # ⚠️ THIS JOURNEY IS INVERTED ON PURPOSE. It used to assert a 4409 refusal —
            # and that refusal IS her screenshot: THIS tab saying "aider is already
            # running in another window" under a NOT CONNECTED chip, beside a Start
            # button that could only produce the same refusal. A second window now TAKES
            # THE SESSION OVER, and the displaced one is told rather than stranded.
            with client.websocket_connect("/api/pty/aider", headers=good) as ws2:
                ws2.send_bytes(b"secondwindow\n")
                got2, deadline = b"", time.time() + 5
                while b"secondwindow" not in got2 and time.time() < deadline:
                    got2 += ws2.receive_bytes()
                ok(b"secondwindow" in got2,
                   "a second window GETS the session — a live terminal, not a refusal")
                ok(b"hello" in got2,
                   "…with the scrollback replayed: the SAME conversation")
                ok(called["n"] == 1,
                   "…and nothing was spawned: one process, whichever window holds it")
                displaced, closes = [], []
                for _ in range(40):
                    m = ws.receive()
                    displaced.append(m)
                    if m.get("type") == "websocket.close":
                        closes.append(m)
                        break
                text = b"".join(m.get("bytes") or b"" for m in displaced)
                ok(b"another window took this session" in text,
                   "the displaced window is TOLD, in the terminal it is looking at")
                ok(b"Take over" in text, "…and told what to press to get it back")
                ok(closes and closes[0].get("reason") == "takeover",
                   f"…and the close reason says takeover, not 'ended' (got {closes})")

        # ══ THE ⌘R FIX, ECHOED FROM THE GOOSE LANE (doctrine 6b) ═══════════════
        # ⚠️ THIS ASSERTION IS INVERTED ON PURPOSE. It used to read "a dropped socket
        # ends the session" — which was TRUE, and was the bug: the two lanes share this
        # pty machinery, so a ⌘R in the Aider tab killed a running aider mid-edit
        # exactly as it did in Goose. A closing socket is what a reload looks like from
        # in here, and it must no longer be fatal.
        time.sleep(0.6)
        ok(P.busy() is True,
           "a dropped socket does NOT end the session — the child outlives the socket")
        sess = P.current()
        ok(sess is not None and not sess.attached(), "…it is sitting DETACHED")
        st = client.get("/api/aider/status").json()
        ok(st["running"] and st["detached"] and st["grace_left"] > 0,
           "…and the status route says so, with the countdown")

        # reconnecting REATTACHES the same child and replays the scrollback
        spawns_before = called["n"]
        with client.websocket_connect("/api/pty/aider", headers=good) as ws:
            replay, deadline = b"", time.time() + 5
            while b"reattached" not in replay and time.time() < deadline:
                replay += ws.receive_bytes()
            ok(called["n"] == spawns_before, "the reload spawned NOTHING")
            ok(b"hello" in replay, "…and the terminal came back with its scrollback")
            ws.send_bytes(b"stillhere\n")
            got, deadline = b"", time.time() + 5
            while b"stillhere" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"stillhere" in got, "…and it is a live terminal, not a transcript")

        # a DELIBERATE end is still an end
        time.sleep(0.3)
        r = client.post("/api/aider/end")
        ok(r.status_code == 200 and r.json()["running"] is False,
           "POST /api/aider/end reports the session gone")
        ok(P.busy() is False, "…and the child really is dead (End kills the PROCESS)")

        # PRECONDITION refusal: the spec's error text is delivered INTO the terminal,
        # then 4412 — the page must never sit at a blank prompt with no explanation.
        A.aider_spawn_spec = lambda: (None, None, None, "no model is loaded")
        with client.websocket_connect("/api/pty/aider", headers=good) as ws:
            first = ws.receive()
            second = ws.receive()
        ok(b"no model is loaded" in (first.get("bytes") or b""),
           "the reason is written to the terminal")
        ok(second.get("code") == P.CLOSE_PRECONDITION, "…and the close code says 4412")
    finally:
        A.aider_spawn_spec = real_spec
        P.kill_current()


# ── 6b. THE INSTALL PATH (the 2026-08-21 "Install does nothing" regression) ──
#
# Two independent defects made one silent failure, and each gets its own fence:
#
#   1. scripts/install_aider.sh shipped at mode 100644. The bridge runs installers as
#      subprocess.run([<path>]), so the thread died with PermissionError before the
#      script's first line — the install could never start on any machine.
#   2. The page hid #msg with a stylesheet `display:none` and re-showed it with
#      `style.display = ''`, which removes the inline declaration and falls straight
#      back to that rule. EVERY message on the page was structurally invisible, so
#      defect 1 (which does record install_error) rendered as nothing at all.
def test_install_script_is_executable():
    p = ROOT / "scripts" / "install_aider.sh"
    ok(p.is_file(), "the installer exists")
    ok(os.access(p, os.X_OK),
       "install_aider.sh is EXECUTABLE — the bridge runs it directly (chmod +x)")
    # And in the index, or a fresh clone / the fat seed ships the broken mode again.
    r = subprocess.run(["git", "ls-files", "-s", "--", "scripts/install_aider.sh"],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        ok(r.stdout.startswith("100755"),
           f"…and committed 100755, not 100644 (got {r.stdout.split()[0]})")


def test_script_runner_survives_a_missing_exec_bit():
    """Defence in depth for the same class: a script without its bit is run via bash
    rather than raising. This branch is only reachable where today we hard-crash."""
    import tempfile
    from bridge import app as A
    real_root = A.ROOT
    with tempfile.TemporaryDirectory() as d:
        sdir = Path(d) / "scripts"
        sdir.mkdir()
        probe = sdir / "probe.sh"
        probe.write_text("#!/usr/bin/env bash\necho ran-anyway\n")
        os.chmod(probe, 0o644)
        A.ROOT = Path(d)
        try:
            r = A._script("probe.sh")
            ok(r.returncode == 0 and "ran-anyway" in r.stdout,
               "a non-executable script still runs (bash fallback), never PermissionError")
            os.chmod(probe, 0o755)
            r = A._script("probe.sh")
            ok(r.returncode == 0 and "ran-anyway" in r.stdout,
               "…and the normal executable path is unchanged")
        finally:
            A.ROOT = real_root


def test_install_endpoint_live():
    """POST /api/aider/install, driven through the real app with a fake installer."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live install test — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A

    client = TestClient(A.app)
    real_script = A._script

    class Fake:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def wait_done(limit=6.0):
        deadline = time.time() + limit
        while time.time() < deadline:
            s = client.get("/api/aider/status").json()
            if not s.get("installing"):
                return s
            time.sleep(0.05)
        return client.get("/api/aider/status").json()

    try:
        # 1. HAPPY PATH — the endpoint answers 200 and the flag flips.
        seen = {"n": 0}

        def slow_ok(name, *a, **k):
            seen["n"] += 1
            ok(name == "install_aider.sh", "the endpoint runs install_aider.sh")
            time.sleep(0.4)
            return Fake(0, "[aider] installed")
        A._script = slow_ok
        r = client.post("/api/aider/install")
        ok(r.status_code == 200, f"install accepted (got {r.status_code})")
        ok(r.json().get("installing") is True, "…and says so in the body")
        mid = client.get("/api/aider/status").json()
        ok(mid.get("installing") is True, "status reports installing while it runs")
        # 2. A SECOND CLICK is 409 — and the page now surfaces that instead of
        #    swallowing it (v1's bare `await fetch` ignored the status entirely).
        r2 = client.post("/api/aider/install")
        ok(r2.status_code == 409, f"a concurrent install is refused 409 (got {r2.status_code})")
        ok((r2.json().get("error") or "") != "", "…with a reason the page can print")
        done = wait_done()
        ok(done.get("installing") is False, "the flag clears when the thread ends")
        ok(not done.get("install_error"), "a successful install records no error")
        ok(seen["n"] == 1, "the refused second click never spawned a second installer")

        # 3. A FAILING installer must land in install_error, verbatim enough to act on.
        A._script = lambda *a, **k: Fake(1, "pip install failed — no network")
        client.post("/api/aider/install")
        s = wait_done()
        ok("pip install failed" in (s.get("install_error") or ""),
           "the installer's own output reaches the status payload")

        # 4. A CRASHING launcher (the PermissionError shape) is reported, not lost.
        def boom(*a, **k):
            raise PermissionError(13, "Permission denied")
        A._script = boom
        client.post("/api/aider/install")
        s = wait_done()
        ok("Permission denied" in (s.get("install_error") or ""),
           "a launcher crash is reported instead of vanishing into the thread")
    finally:
        A._script = real_script
        with A._AIDER_INSTALL_LOCK:
            A._AIDER_INSTALLING.clear()

    # the install log the page tails is a REAL, already-allowlisted log source
    r = client.get("/api/logs/aider-install?lines=5")
    ok(r.status_code == 200 and "lines" in r.json(),
       "GET /api/logs/aider-install is served (no new endpoint was needed)")


def test_page_cannot_fail_silently():
    """The page half of the same bug. These assertions are the reason 'nothing
    happened' can never be the whole story again."""
    page = (ROOT / "bridge" / "panel" / "aider.html").read_text()
    js = page.split("<script>")[-1].split("</script>")[0]

    # (a) the status line is toggled by CLASS. `style.display=''` cannot beat a
    #     stylesheet rule, which is exactly how v1 muted itself.
    ok("#msg.show{display:block}" in page.replace(" ", ""),
       "#msg has an explicit .show rule")
    say_body = js.split("function say(", 1)[1].split("\n}", 1)[0]
    ok("classList" in say_body or "className" in say_body,
       "say() toggles a class")
    ok("style.display" not in say_body,
       "say() NEVER uses style.display (the defect that muted the whole page)")

    # (a2) ⚠️ THE END BUTTON MUST NOT BE sock.close(). Since the reattach slice,
    #      closing the socket is EXACTLY what a ⌘R does and the bridge deliberately
    #      reads it as "the page went away" — so the old handler would have turned End
    #      into a detach: a control that promises to stop an agent and leaves it
    #      running with the workspace. Same fence as the Goose page's.
    ok("/api/aider/end" in page, "End posts the deliberate-end route")
    ok("btn-stop').onclick = () => { if (sock) sock.close(); }" not in page,
       "…and is NOT the old socket-close, which would now silently mean 'detach'")
    ok("s.model_ready || s.detached" in page,
       "a reloaded tab reconnects even when the runner has since been unloaded — a "
       "live session must never be strandable behind a precondition check")
    ok("'detached'" in page,
       "a detached close is never printed to the user as 'session ended'")
    ok("reattaches" in page,
       "…and the note states the reload rule instead of leaving it to be discovered")
    # ── DEBI'S SCREENSHOT, the page half (ledger U10) ──
    ok("Take over" in page,
       "the button SAYS what it will do when another window holds the session — "
       "'Start' beside a running session was half the dead end")
    ok("running · another window" in page,
       "…and the chip has a word for that state, instead of contradicting the "
       "terminal below it with NOT CONNECTED")
    ok("already running in another tab or window" not in page,
       "…and the refusal copy that produced the dead end is gone from the page")

    # (b) every request checks its status. Exactly one bare fetch( exists: jfetch's own.
    #     Comments are stripped first — prose about the bug is not a call site.
    code = re.sub(r"^\s*//.*$", "", js, flags=re.M)
    bare = len(re.findall(r"(?<!j)fetch\(", code))
    ok(bare == 1, f"exactly one bare fetch(), inside jfetch (found {bare})")
    ok("if (!r.ok) throw" in js, "a non-2xx response raises instead of reading as success")
    ok("jfetch('/api/aider/install'" in js and "catch (e)" in js,
       "the install POST goes through jfetch and its failure is caught")
    ok("could not start the install: " in js, "…and the reason is shown to the user")

    # (c) the log is reachable FROM THIS PAGE (it is not the panel, so it cannot open
    #     the panel's log dialog).
    ok("/api/logs/aider-install" in js, "the page tails the install log inline")
    ok("id=\"logbox\"" in page and "id=\"lnk-log\"" in page, "the log surface exists")
    ok("showLog(true)" in js, "a failure opens the log without a second click")

    # (d) the visible states of the button.
    ok("'installing…'" in js and "'Install aider'" in js,
       "the button wears the state it is in")
    ok("install failed:" in js, "a failed install says so, with the error text")

    # (e) the absence of a Mission Control card is stated as intent, not left as a gap.
    ok("lane, not a component" in page, "the footer explains why there is no card")

    # (f) ⚠️ NO HARDCODED INK ON A TOKENISED FILL (bug-echo W-06, the v1.5.13 .ap-cmd
    #     class). This page copies the panel's palette into its own :root because a
    #     separate document cannot inherit one, so a literal that HAPPENS to equal a
    #     token today is a colour no palette can reach tomorrow: in the light theme
    #     --cream is DARK ink (#221d14), and a near-black literal on a --cream fill is an
    #     empty rectangle. The pin is on the SHAPE, not on one property.
    css = page.split("<style>", 1)[1].split("</style>", 1)[0]
    # Comments first — prose ABOUT a rule (including the one that explains this fix) is
    # not a rule, and a grep that cannot tell them apart finds the bug in its own note.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    prim = re.findall(r"button\.primary\s*\{[^}]*\}", css, flags=re.S)
    ok(len(prim) == 2,
       f"the primary has one base and one intentional Studio refinement (found {len(prim)})")
    ok(all("color:var(--bg)" in rule.replace(" ", "") for rule in prim),
       "both primary rules ink the cream fill with var(--bg), never a hardcoded near-black")
    ok("#171420" not in css,
       "…and the old literal is gone from the whole stylesheet")
    # And the general form, so the next copied literal is caught rather than re-found:
    # no rule that fills with a token may set its ink with a hex.
    for ln in css.splitlines():
        flat = ln.replace(" ", "")
        if "background:var(--" in flat and re.search(r"color:#[0-9a-fA-F]{3,8}", flat):
            ok(False, f"a tokenised fill with hardcoded ink: {ln.strip()}")
    ok(True, "no rule fills with a token and inks with a hex")


def test_page_is_theme_aware():
    """S10: Aider follows the same read-only terminal-skin contract as Goose CLI."""
    page = (ROOT / "bridge" / "panel" / "aider.html").read_text()
    head = page.split("</head>", 1)[0]
    css = head.split("<style>", 1)[1].split("</style>", 1)[0]
    for theme in ("light", "gold", "cyber"):
        ok(f'html[data-theme="{theme}"]' in css,
           f"Aider carries the {theme} palette in its own document")
    ok('html[data-chrome="studio"]' in css, "Aider carries the Studio chrome axis")
    ok(head.index("window.syncSkin") < head.index("<style>"),
       "the saved skin is applied before first paint")
    ok("motdeck-theme" in head and "motdeck-chrome" in head,
       "the page reads the two canonical preference keys")
    ok("localStorage.setItem" not in page,
       "the lane never writes app appearance preferences")
    ok("theme === 'light' || theme === 'gold' || theme === 'cyber'" in head,
       "unknown theme values fail to Editorial instead of half-painting")
    ok("addEventListener('storage'" in page
       and "addEventListener('focus'" in page
       and "addEventListener('visibilitychange'" in page,
       "live, focused and resumed tabs all reconcile appearance")
    ok(css.index(':where(html[data-chrome="studio"]) button{')
       > css.index("\n  button{"),
       "zero-specificity Studio button refinements follow the base rule")
    ok(css.index(':where(html[data-chrome="studio"]) .pill{')
       > css.index("\n  .pill{"),
       "zero-specificity Studio pill refinements follow the base rule")
    term_block = page.split("term = new TermCtor({", 1)[1].split("});", 1)[0]
    ok("background: '#0b0910'" in term_block and "foreground: '#efe9dc'" in term_block,
       "Aider's ANSI terminal stays on its deliberate dark canvas in every palette")


# ── 7. wiring greps (the seams that live outside this module) ────────────────
def test_wiring():
    appsrc = _APP_SOURCE
    ok('@app.websocket("/api/pty/aider")' in appsrc, "the websocket route exists")
    ok('@app.get("/aider")' in appsrc, "the page route exists")
    ok('@app.get("/api/aider/status")' in appsrc, "status route")
    ok('@app.post("/api/aider/install")' in appsrc, "install route")
    ok("origin_allowed" in appsrc, "the handler consults the origin gate")
    # The gate must run BEFORE the spawn — order is the whole point.
    ok(appsrc.index("origin_allowed") < appsrc.index("aider_spawn_spec()"),
       "the origin gate is checked before anything is spawned")
    ok('"aider", "aider-install"' in appsrc, "both logs are viewable in-panel")
    ok("wire_model_id(live" in appsrc, "the model id goes through wire_model_id")
    ok("_live_model_id(" in appsrc, "the live runner is the authority on the model")

    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    ok("{n:'aider', label:'aider'}" in panel, "panel log source: aider")
    ok("{n:'aider-install'" in panel, "panel log source: aider install")

    fetch = (ROOT / "scripts" / "fetch_vendor_assets.sh").read_text()
    ok('XTERM_V="6.0.0"' in fetch, "xterm pinned to 6.0.0 (the version Hermes ships)")
    ok('XTERM_FIT_V="0.11.0"' in fetch, "addon-fit pinned")
    ok("xterm.js|" in fetch and "xterm.css|" in fetch and "xterm-addon-fit.js|" in fetch,
       "all three assets are fetched")

    yml = (ROOT / "motdeck.yaml").read_text()
    m = re.search(r'^  aider_pin:\s*"([0-9a-f]{40})"', yml, re.M)
    ok(bool(m), "build.aider_pin is a full 40-char commit sha")
    inst = (ROOT / "scripts" / "install_aider.sh").read_text()
    ok("_yb aider_pin" in inst, "the installer reads the pin from motdeck.yaml")
    ok("Aider-AI/aider.git" in inst, "upstream, not the cecli fork")
    ok("cecli" not in inst, "the fork is not what gets cloned")
    ok("-m pip install" in inst and "/bin/pip" not in inst,
       "python -m pip everywhere, never bin/pip (a uv-seeded venv may lack the script)")
    ok("data/aider-venv" in inst, "its own venv")

    sw = (ROOT / "app" / "main.swift").read_text()
    ok('MOTDeckTab(id: "aider", title: "Aider"' in sw, "the tab row exists")
    ok('http://127.0.0.1:8700/aider' in sw, "…pointing at the bridge page")
    ok("NSSize(width: 1160" in sw, "minSize.width raised for the 9th tab")
    ok(sw.count("MOTDeckTab(title:") == len(re.findall(r"MOTDeckTab\(title:", sw)),
       "tabs are declared only in the table")


def main():
    for fn in (test_origin_gate, test_resize, test_argv, test_env, test_installed,
               test_session_roundtrip, test_session_eof_and_group_kill,
               test_one_at_a_time, test_routes_live,
               test_install_script_is_executable,
               test_script_runner_survives_a_missing_exec_bit,
               test_install_endpoint_live, test_page_cannot_fail_silently,
               test_page_is_theme_aware, test_wiring):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"aider lane: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
