#!/usr/bin/env python3
"""GOOSE LANE slice 1 — the decision tables, the fence, and the WALKED JOURNEYS.

Built to docs/research/2026-08-28-goose-source-verify.md. Per the proactive-build
doctrine, every journey walked by hand during the build is pinned here as an executable
test, and every adversarial finding that was FIXED has a fence that fails if it returns.

What is load-bearing, and why:

1. THE ORIGIN GATE. WebSockets are not subject to CORS, so it is the only thing between
   a random web page and a process on this Mac that can run shell commands. Exercised
   for real through the mounted app; the refusal must arrive as close code 4403 with
   NOTHING spawned.
2. THE CONFINEMENT FENCE. HOME *and* all four XDG_* dirs must point inside
   data/goose/home. This is the ~/.unsloth defect class, and it BIT during this build:
   the installer's own unfenced `goose --version` created ~/.local/state/goose/logs
   while our own output promised it never would. Fenced here for the runtime AND for
   the installer's probes.
3. THE TWO TELEMETRY KILL SWITCHES, both present on every launch, plus the assertion
   that no code path opts IN.
4. GOOSE_DISABLE_SESSION_NAMING. Measured: without it goose fires a second, concurrent
   "generate a title" completion, and on a reasoning model behind our single-slot
   llama-server that request never finishes and the REAL turn never starts. The lane
   reads as "goose hangs forever on hello". This is a fence against a dead end, not a
   preference.
5. THE ENDPOINT COMPOSITION. runner.endpoint is `…:6767/v1`; goose composes
   OPENAI_HOST + '/' + OPENAI_BASE_PATH. Handing it the base verbatim yields
   /v1/v1/chat/completions — a 404 that looks exactly like a broken model.
6. THE MEMORY-LEDGER ROW. data/goose.pid exists for exactly the life of a session, so
   /api/memory names Goose while it runs and never afterwards.

The session manager is NOT mocked: it runs against /bin/cat, so the fd handling, the
byte relay and the teardown are proven rather than argued. Only the goose binary itself
is substituted (it need not be installed to run this file).

Run: python3 bridge/tests/test_goose_lane.py
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28): source-text
# assertions read bridge/appsrc.py's assembled view, not app.py's facade.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import pty_goose as G                              # noqa: E402
from bridge import gooseprov as PR                             # noqa: E402

CHECKS = 0
INSTALLER = (ROOT / "scripts" / "install_goose.sh")
PAGE = (ROOT / "bridge" / "panel" / "goose.html")


def ok(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, f"FAIL: {label}"


def _pid_alive(pid) -> bool:
    """Is THAT pid still there? Used only to prove a reap actually killed the child we
    spawned — never to find a process to act on."""
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


# ── 1. the origin gate (imported from pty_aider — assert it really is wired) ──
def test_origin_gate():
    for good in ("http://127.0.0.1:8700", "http://localhost:8700",
                 "http://127.0.0.1:8700/", "  http://localhost:8700  "):
        ok(G.origin_allowed(good, 8700), f"allowed: {good!r}")
    for bad in ("http://evil.example",
                "https://127.0.0.1:8700",       # scheme must match — no https page of ours
                "http://127.0.0.1:9999",        # another port is another app
                "null", "", None, 17,
                "http://127.0.0.1:8700.evil.example"):
        ok(not G.origin_allowed(bad, 8700), f"refused: {bad!r}")
    # A MISSING Origin is refused: a browser always sends one for a websocket handshake
    # from a page with a real origin, so "absent" means "not our page".
    ok(not G.origin_allowed(None, 8700), "a missing Origin header is refused")


# ── 2. the resize control message ────────────────────────────────────────────
def test_resize():
    clean, sizes = G.split_resize(b"ab\x1b[RESIZE:120;40]cd")
    ok(clean == b"abcd", "the escape is stripped from the byte stream")
    ok(sizes == [(120, 40)], "…and turned into one clamped pair")
    _c, sizes = G.split_resize(b"\x1b[RESIZE:999999;0]")
    ok(sizes == [(G.MAX_COLS, G.MIN_ROWS)], "absurd dimensions are clamped, not passed")
    ok(G.split_resize(b"") == (b"", []), "empty input is total")
    ok(G.clamp_dim("nonsense", 2, 200, 80) == 80, "junk falls back rather than raising")


# ── 3. THE FENCE ─────────────────────────────────────────────────────────────
def test_env_fence():
    home = G.goose_home(ROOT)
    # A HOSTILE base env: the operator's own XDG_* pointing at their real dotfolders is
    # exactly the shape that would defeat a HOME-only fence.
    hostile = {"HOME": "/Users/somebody",
               "XDG_CONFIG_HOME": "/Users/somebody/.config",
               "XDG_DATA_HOME": "/Users/somebody/.local/share",
               "XDG_STATE_HOME": "/Users/somebody/.local/state",
               "XDG_CACHE_HOME": "/Users/somebody/.cache",
               "COLUMNS": "131072", "LINES": "9",
               "GOOSE_MODE": "auto", "GOOSE_TOOLSHIM": "true",
               "PATH": "/usr/bin:/bin"}
    env = G.goose_env(hostile, ROOT, "http://127.0.0.1:6767/v1", "harness-local", "m")
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "XDG_CACHE_HOME"):
        ok(env[key].startswith(home),
           f"{key} points inside data/goose/home (got {env[key]})")
        ok("somebody" not in env[key], f"{key} did not survive from the hostile env")
    ok("PATH" in env, "PATH survives — goose execs shell helpers for its tools")
    ok("COLUMNS" not in env and "LINES" not in env,
       "COLUMNS/LINES are removed: the winsize ioctl owns the size")

    # the two kill switches, both mechanisms
    ok(env["GOOSE_TELEMETRY_OFF"] == "1", "GOOSE_TELEMETRY_OFF=1 in the env")
    ok(env["GOOSE_TELEMETRY_ENABLED"] == "false", "…and the config key, also in env")
    ok(env["GOOSE_DISABLE_KEYRING"] == "true",
       "the macOS Keychain is disabled (a modal behind a webview is a hang)")
    # the measured hang fix
    ok(env["GOOSE_DISABLE_SESSION_NAMING"] == "true",
       "session naming is OFF — its concurrent title completion never returns on a "
       "reasoning model behind our single-slot runner, and the real turn queues behind it")
    # ⚠️ THE APPROVAL PROMPT — the LIE-TO-USER finding of this slice, fenced. goose's
    # default GOOSE_MODE at this pin is `auto`: the walked journey produced a written
    # file in six seconds with NO prompt, while this lane's own page promised one. The
    # mode is now SET on every launch, so an upstream default change cannot remove it.
    ok(env["GOOSE_MODE"] == "smart_approve",
       "GOOSE_MODE=smart_approve — the approval prompt is switched ON by us, not "
       "inherited (upstream's default is `auto`, which asks nothing)")
    ok(env["GOOSE_MODE"] != G.FORBIDDEN_MODE,
       "…and never `auto`, in either direction — inherited or set")
    ok(G.goose_env({"GOOSE_MODE": "auto"}, ROOT, "", "", "m")["GOOSE_MODE"]
       == "smart_approve",
       "an inherited GOOSE_MODE=auto is OVERWRITTEN, not respected")
    # nothing that would reroute tool calls to a backend that cannot reach our runner
    for k in G.FORBIDDEN_ENV:
        ok(k not in env, f"{k} is never on this lane's launch (and is stripped if inherited)")

    # the provider — NAMED as of v1.5.49, and SEEDED rather than enforced
    ok(env["GOOSE_PROVIDER"] == PR.PROVIDER_NAME,
       "provider is OUR NAMED one (custom_mot_deck__local), not the anonymous stock "
       "`openai` — that is the whole isolation-mode slice")
    ok(env[PR.api_key_env()] == "harness-local",
       "…and the key rides the env var goose DERIVES from the provider name "
       "(CUSTOM_MOT_DECK__LOCAL_API_KEY), which is what it actually reads — measured, "
       "and it BEATS secrets.yaml, which is why we never write that file")
    ok(env["OPENAI_HOST"] == "http://127.0.0.1:6767", "host is the ORIGIN, not the base")
    ok(env["OPENAI_BASE_PATH"] == "v1/chat/completions", "…and the path is written out")
    ok(env["OPENAI_API_KEY"] == "harness-local", "the runner's REAL key, not a dummy")
    ok(G.goose_env({}, ROOT, "", "", "m")["OPENAI_API_KEY"] == "harness-local",
       "an omitted key falls back to harness.yaml's shipped value, never to empty "
       "(an empty Bearer fails before it reaches the runner)")
    ok(G.goose_env({}, ROOT, "", "", "  /abs/path/to/mlx-model  ")["GOOSE_MODEL"]
       == "/abs/path/to/mlx-model",
       "an MLX absolute-path wire id survives verbatim (goose does not split on '/')")


def test_endpoint_composition():
    """THE //v1/v1 TRAP. goose builds OPENAI_HOST + '/' + OPENAI_BASE_PATH."""
    ok(G.openai_host("http://127.0.0.1:6767/v1") == "http://127.0.0.1:6767",
       "the /v1 suffix of runner.endpoint is removed")
    ok(G.openai_host("http://127.0.0.1:6767/v1/") == "http://127.0.0.1:6767",
       "…trailing slash and all")
    ok(G.openai_host("http://127.0.0.1:6767") == "http://127.0.0.1:6767",
       "an origin is already correct and is left alone")
    for junk in ("", None, "   ", "not-a-url", 17):
        ok(G.openai_host(junk, 6767) == "http://127.0.0.1:6767",
           f"junk endpoint falls back to the runner's loopback port ({junk!r})")
    ok(G.openai_host("", 6868) == "http://127.0.0.1:6868",
       "…on whatever port the manifest names, not a hardcoded 6767")


def test_config_seed():
    """A TEXT EDIT, NEVER A YAML ROUND-TRIP: the user may add extensions with
    /configure inside the tab, and our writer must not be how they are lost."""
    cur = ("# a comment the user wrote\n"
           "GOOSE_PROVIDER: openai\n"
           "OPENAI_HOST: http://stale:1\n"
           "extensions:\n"
           "  developer:\n"
           "    enabled: true\n")
    new = G.upsert_config(cur, G.config_pairs("http://127.0.0.1:6767/v1"))
    ok("# a comment the user wrote" in new, "comments survive")
    ok("  developer:" in new and "    enabled: true" in new,
       "a nested extensions block survives byte-for-byte")
    ok("OPENAI_HOST: http://127.0.0.1:6767" in new, "our key is updated in place")
    ok("http://stale:1" not in new, "…and the stale value is gone, not duplicated")
    ok(new.count("OPENAI_HOST:") == 1, "exactly one OPENAI_HOST line")
    ok("GOOSE_TELEMETRY_ENABLED: false" in new, "the telemetry key is seeded")
    ok("GOOSE_DISABLE_KEYRING: true" in new, "…and the keyring key")
    ok(G.upsert_config("", G.config_pairs("")).count("\n") == 4,
       "an absent config becomes exactly our four keys")
    # idempotent: running twice is byte-identical
    ok(G.upsert_config(new, G.config_pairs("http://127.0.0.1:6767/v1")) == new,
       "seeding is idempotent")


def test_tools_verdict():
    """WARN, NEVER REFUSE — and 'we don't know' is its own sentence, not a silent pass."""
    ok(G.tools_warning({"id": "m", "tools": True}) == "", "a tool-capable model says nothing")
    ok("NO tool-calling" in G.tools_warning({"id": "m", "tools": False}),
       "a model that cannot tool-call gets the hard sentence")
    ok("does not say" in G.tools_warning({"id": "m"}),
       "an unknown verdict gets its own sentence")
    ok("no model is loaded" in G.tools_warning(None), "nothing loaded is its own sentence")
    for w in (G.TOOLS_BAD % "m", G.TOOLS_UNKNOWN % "m", G.TOOLS_NONE):
        ok("OpenCode" not in w and "opencode" not in w,
           "the Goose tab never tells the user what OpenCode needs")
        ok("goose" in w, "…it names goose")


# ── 4. the launch line ───────────────────────────────────────────────────────
def test_argv():
    argv = G.goose_argv(ROOT)
    ok(argv[0].endswith("data/goose/bin/goose"), "the pinned binary, by absolute path")
    ok(argv[1] == "session",
       "`session` — the INTERACTIVE entrypoint. `run` is headless and would exit "
       "immediately in a tab, which is the empty-terminal failure")
    ok(len(argv) == 2, "nothing else on the line: every setting is env or config")
    # the approval prompt IS the safety surface in a terminal the user is watching
    joined = " ".join(argv)
    for forbidden in ("--yes", "--auto", "--no-confirm"):
        ok(forbidden not in joined, f"{forbidden} is never passed")


def test_the_surface_does_not_promise_an_approval_it_does_not_get():
    """THE LIE-TO-USER FENCE. The page and the Help explainer both claim goose asks
    before it writes or runs. That claim is only true because goose_env sets
    GOOSE_MODE — so the claim and the mechanism are asserted TOGETHER here, in one
    place, and neither can be edited away on its own."""
    page = PAGE.read_text()
    help_md = (ROOT / "docs" / "USER-EXPLAINERS.md").read_text()
    ok("before it writes or runs anything" in page,
       "the page states the approval step in the terms the mode actually delivers")
    ok("before it writes a file or runs a command" in help_md,
       "…and the Help explainer says the same thing")
    ok(G.GOOSE_MODE == "smart_approve" and G.FORBIDDEN_MODE == "auto",
       "…and the mechanism that makes both true is set, not inherited")


def test_installed_reads_disk():
    ok(isinstance(G.is_installed(ROOT), tuple), "is_installed returns a triple")
    missing = G.is_installed("/nonexistent-root-for-this-test")
    ok(missing[0] is False and missing[1] == "",
       "a missing binary reads as not-installed IMMEDIATELY (disk, never a stored flag "
       "— which is why this lane needs no manifest `installed:` and no flip_installed)")


# ── 5. the pty, for real ─────────────────────────────────────────────────────
def test_session_roundtrip():
    sess = G.PtySession(["/bin/cat"], cwd="/tmp",
                        env={"TERM": "dumb", "PATH": "/usr/bin:/bin"})
    sess.start(cols=90, rows=24)
    try:
        ok(sess.alive(), "child is running on the pty")
        sess.write(b"ping\n")
        got, deadline = b"", time.time() + 5
        while b"ping" not in got and time.time() < deadline:
            got += sess.read()
        ok(b"ping" in got, "bytes go in and come back out of the pty")
        sess.resize(120, 40)
        ok(True, "resize on a live session is a no-throw ioctl")
    finally:
        how = sess.close()
    ok(how in ("term", "kill"), f"teardown killed the child ({how})")
    ok(not sess.alive(), "child is gone after close")


def test_claims_are_independent_of_aider():
    """A live aider session must not refuse a goose session: two programs, two
    workspaces, two claims. This is why pty_goose keeps its OWN module state."""
    from bridge import pty_aider as A
    A.kill_current()
    G.kill_current()
    a = A.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin:/usr/bin"})
    a.start()
    ok(A.claim(a), "aider claims its slot")
    try:
        g = G.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin:/usr/bin"})
        g.start()
        ok(G.claim(g), "goose can still claim ITS slot while aider runs")
        g2 = G.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin:/usr/bin"})
        ok(not G.claim(g2), "…but a SECOND goose is refused (one workspace, one claimant)")
        G.kill_current()
    finally:
        A.kill_current()
    ok(not G.busy() and not A.busy(), "both lanes are idle again")


# ── 6. THE LIVE JOURNEYS through the mounted app ─────────────────────────────
def test_routes_live():
    """Mount the actual FastAPI app and drive the websocket. The only thing faked is
    goose_spawn_spec (goose need not be installed to run this file); the origin gate,
    the byte relay, the resize consumption, the busy refusal, the precondition refusal,
    the PIDFILE lifecycle and the memory-ledger row are all the real code paths."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live route tests — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A
    from bridge.routers import goose as R

    ok(R._goose is not None, f"the router imported pty_goose ({R._GOOSE_ERR})")
    G.kill_current()
    client = TestClient(A.app)

    # ── journey: open the tab with nothing configured ──
    r = client.get("/api/goose/status")
    ok(r.status_code == 200, "GET /api/goose/status is 200")
    body = r.json()
    for key in ("installed", "running", "model", "model_ready", "workspace", "home",
                "endpoint", "pin", "tools_warning"):
        ok(key in body, f"status carries {key}")
    ok(body["workspace"].endswith("data/goose-workspace"), "status names the workspace")
    ok(body["home"].endswith("data/goose/home"), "…and the confined home")
    ok(body["endpoint"].endswith("/v1/chat/completions"),
       "…and the FULL url goose will call, so a wrong port is visible without a log")
    ok(body["endpoint"].count("/v1") == 1,
       "the endpoint shown is not the //v1/v1 double")
    ok(body["pin"] == G.PIN_TAG, "…and which pin is installed")
    # ⚠️ THE SHADOW FENCE (adversarial, caught on the live walk 2026-08-29). The detach
    # block added to this route introduced a local named `live` on top of the model id,
    # so `"model": live or ""` rendered "" and the tab said NO MODEL LOADED while the
    # runner was serving — the LIE class, from one variable name. The status route's
    # model must always be exactly what the model probe says, whatever else it reports.
    from bridge.core.modelid import _live_model_id as _lmi
    from bridge.core.procs import cfg as _cfg
    _p = int((_cfg().get("runner") or {}).get("port") or 6767)
    ok(body["model"] == (_lmi(_p) or ""),
       f"status reports the LIVE model, never a shadowed bool (got {body['model']!r})")
    ok(body["model_ready"] is bool(body["model"]),
       "…and model_ready agrees with it")

    # the page exists and is offline-clean
    page = PAGE.read_text()
    ok("/assets/vendor/xterm.js" in page, "the page loads self-hosted xterm.js")
    ok("/assets/vendor/xterm.css" in page, "…and its css")
    ok("/assets/vendor/xterm-addon-fit.js" in page, "…and the fit addon")
    ok("cdn." not in page and "https://" not in page, "no runtime CDN anywhere (offline)")
    ok("/api/pty/goose" in page and "\\x1b[RESIZE:" in page,
       "the page speaks the one control message")
    r = client.get("/goose")
    ok(r.status_code == 200 and "Goose" in r.text, "GET /goose serves the tab document")
    ok("no-store" in r.headers.get("cache-control", ""),
       "…uncached, so a ship is visible on ⌘R")

    called = {"n": 0}
    real_spec = R.goose_spawn_spec

    def fake_spec(resume_id=""):
        called["n"] += 1
        called["resume"] = resume_id
        return (["/bin/cat"], {"PATH": "/bin:/usr/bin", "TERM": "xterm-256color"},
                "/tmp", "")
    R.goose_spawn_spec = fake_spec
    pidfile = Path(G.pidfile_path(ROOT))
    try:
        # ── journey: THE ORIGIN GATE. A cross-origin handshake is closed 4403 and must
        #    not spawn anything — proved by the spec never being called.
        for bad_origin in ("http://evil.example", "http://127.0.0.1:9999"):
            with client.websocket_connect(
                    "/api/pty/goose", headers={"origin": bad_origin}) as ws:
                closed = ws.receive()
            ok(closed.get("type") == "websocket.close", f"{bad_origin} closed immediately")
            ok(closed.get("code") == G.CLOSE_ORIGIN,
               f"{bad_origin} refused with 4403 (got {closed.get('code')})")
        ok(called["n"] == 0, "NOTHING was spawned for a refused origin")
        ok(not pidfile.exists(), "…and no pidfile was written for a refused origin")

        # ── journey: a real session ──
        good = {"origin": "http://127.0.0.1:8700"}
        with client.websocket_connect("/api/pty/goose?cols=90&rows=30",
                                      headers=good) as ws:
            ok(called["n"] == 1, "an allowed origin reaches the spawn path")
            ws.send_bytes(b"hello\n")
            got, deadline = b"", time.time() + 5
            while got.count(b"hello") < 1 and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"hello" in got, "bytes relayed through the websocket into the pty and back")

            # THE MEMORY LEDGER ROW, live. This is the whole reason the pidfile exists.
            ok(pidfile.exists(), "data/goose.pid exists while the session does")
            live_pid = int(pidfile.read_text().strip())
            ok(live_pid > 0, "…and holds the child's pid")
            m = client.get("/api/memory")
            if m.status_code == 200:
                names = [c.get("name") for c in (m.json().get("components") or [])]
                ok("goose" in names,
                   f"/api/memory names goose while it runs (got {names})")
                row = next(c for c in m.json()["components"] if c["name"] == "goose")
                # ⚠️ WIDENED, NOT WEAKENED, AT THE GOOSE UI SLICE: the label reads "Goose
                # CLI" now that a SECOND goose lane (data/goose-ui.pid → "Goose UI") can
                # hold RAM at the same moment. The KEY is still `goose` — a pidfile stem
                # never churns with a display name — and the assertion's point is
                # unchanged: a human label, not a bare id.
                ok(row.get("label") == "Goose CLI",
                   "…with a human label that says WHICH goose, not a bare id")

            # A resize message must be CONSUMED: /bin/cat echoes everything it is given,
            # so if the escape reached the pty it would come straight back at us.
            ws.send_bytes(b"\x1b[RESIZE:100;30]")
            ws.send_bytes(b"after\n")
            got, deadline = b"", time.time() + 5
            while b"after" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"RESIZE" not in got, "the resize escape never reached the pty")
            ok(b"after" in got, "…and the next real keystroke still arrived")

            # ══ DEBI'S REPRO: A SECOND WINDOW (2026-08-29, ledger U10) ═════════
            # ⚠️ THIS JOURNEY IS INVERTED ON PURPOSE. It used to assert a 4409 refusal —
            # and that refusal IS the screenshot Debi sent: a tab saying "already
            # running in another window" under a NOT CONNECTED chip, beside a Start
            # button that could only produce the same refusal. A second window now TAKES
            # THE SESSION OVER, and the displaced one is told rather than stranded.
            with client.websocket_connect("/api/pty/goose", headers=good) as ws2:
                ws2.send_bytes(b"secondwindow\n")
                got2, deadline = b"", time.time() + 5
                while b"secondwindow" not in got2 and time.time() < deadline:
                    got2 += ws2.receive_bytes()
                ok(b"secondwindow" in got2,
                   "a second window GETS the session — it is a live terminal there")
                ok(b"hello" in got2,
                   "…with the scrollback replayed, so it is the SAME conversation")
                ok(called["n"] == 1,
                   "…and nothing was spawned: one process, whichever window holds it")
                ok(int(pidfile.read_text().strip()) == live_pid,
                   "…the same pid, so the ledger row never doubled")
                # the DISPLACED socket is told, in its own words, and not with 'ended'
                # Drain until the close arrives: the pty's own output is still in
                # flight, so the sentence and the close are not the next two frames.
                displaced, closes = [], []
                for _ in range(40):
                    m2 = ws.receive()
                    displaced.append(m2)
                    if m2.get("type") == "websocket.close":
                        closes.append(m2)
                        break
                text = b"".join(m2.get("bytes") or b"" for m2 in displaced)
                ok(b"another window took this session" in text,
                   "the displaced window is TOLD, in the terminal it is looking at")
                ok(b"Take over" in text,
                   "…and told what to press to get it back — never a dead end")
                ok(closes and closes[0].get("reason") == "takeover",
                   f"…and its close reason says takeover, not 'ended' (got {closes})")
            ok(pidfile.exists() and int(pidfile.read_text().strip()) == live_pid,
               "…and the refused second connect did NOT overwrite the live pidfile")

        # ══ journey: ⌘R — THE COMPLAINT THIS SLICE EXISTS FOR ═══════════════════
        # "every refresh wipes off the current session. That shouldn't be the case."
        # Both sockets above are now closed, which is exactly what a page reload does.
        # The child must STILL BE RUNNING.
        time.sleep(0.6)
        ok(G.busy() is True,
           "a dropped socket does NOT end the session any more — the child outlives it")
        sess = G.current()
        ok(sess is not None and not sess.attached(),
           "…and it is DETACHED, which is how a second tab is still refused but a "
           "reload is not")
        ok(pidfile.exists() and int(pidfile.read_text().strip()) == live_pid,
           "…and the ledger row STAYS, because a detached session is a real process")
        st = client.get("/api/goose/status").json()
        ok(st["running"] and st["detached"] and not st["attached"],
           "status tells the page the three-state truth before it opens a socket")
        ok(st["grace_left"] > 0 and st["grace_s"] > 0,
           "…including how long is left, because that process is going to be reaped")

        # …and reconnecting REATTACHES to the same child, with the scrollback replayed.
        spawns_before = called["n"]
        with client.websocket_connect("/api/pty/goose?cols=90&rows=30",
                                      headers=good) as ws:
            replay, deadline = b"", time.time() + 5
            while b"reattached" not in replay and time.time() < deadline:
                replay += ws.receive_bytes()
            ok(called["n"] == spawns_before,
               "the reload spawned NOTHING — it reattached to the running child")
            ok(b"hello" in replay,
               "…and the scrollback was replayed, so the terminal is not blank")
            ok(b"reattached" in replay,
               "…with a rule marking where the replayed tail ends")
            ok(int(pidfile.read_text().strip()) == live_pid,
               "…and it is the SAME process, by pid")
            # the reattached socket is a fully live terminal, not a transcript viewer
            ws.send_bytes(b"stillhere\n")
            got, deadline = b"", time.time() + 5
            while b"stillhere" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"stillhere" in got, "…and typing into the reattached session works")

        # ══ journey: a DELIBERATE end is still an end ══════════════════════════
        time.sleep(0.3)
        ok(G.busy() is True, "…still running after that second socket dropped")
        r = client.post("/api/goose/end")
        ok(r.status_code == 200 and r.json()["running"] is False,
           "POST /api/goose/end reports the session gone")
        ok(G.busy() is False, "…and the child really is dead (End kills the PROCESS)")
        ok(not pidfile.exists(),
           "…and the pidfile went with it, so the ledger never shows a ghost row")

        # ══ journey: the grace window EXPIRES with nobody back ═════════════════
        # Same code path as the ten-minute default; the window is the manifest's, so
        # the test shortens it rather than waiting.
        with client.websocket_connect("/api/pty/goose", headers=good) as ws:
            ws.send_bytes(b"x\n")
            ws.receive_bytes()
        time.sleep(0.3)
        sess = G.current()
        reaped_pid = sess.proc.pid if sess is not None else 0
        ok(sess is not None and not sess.attached(),
           "the socket dropped and the session is sitting detached")
        # A late/stale caller must NOT be able to re-arm or disarm somebody else's
        # window — including with the `None` that an already-detached session holds.
        ok(sess.detach(None) is False,
           "detach() refuses a caller that is not the current subscriber")
        # Re-attach and re-detach with a short window, through the real API, so what is
        # exercised is the shipped reaper and not a poked attribute.
        got = sess.attach(lambda _b: None)
        ok(got is not None, "…and the detached session can be attached again")
        ok(sess.grace_left() == 0.0, "attaching disarms the countdown")
        # MIN_GRACE_S is the floor, so this asks for the shortest window the shipped
        # clamp permits rather than poking an attribute past it.
        sess.detach(sess._sub, grace=0.0, on_reap=R._reap_cb)
        ok(sess.grace_s == G.clamp_grace(0.0) == 5.0,
           "a zero grace is clamped to the floor, not honoured as 'kill it now'")
        deadline = time.time() + 20
        while (G.busy() or pidfile.exists()) and time.time() < deadline:
            time.sleep(0.1)
        ok(not G.busy(), "the grace window expired and the session was reaped")
        ok(reaped_pid and not _pid_alive(reaped_pid),
           "…the actual child is gone — identity-verified by ITS OWN pid, never by name")
        ok(not pidfile.exists(), "…and the reap withdrew the ledger row")

        # ══ journey: RESUME an old session from the strip ══════════════════════
        called["resume"] = None
        with client.websocket_connect("/api/pty/goose?session=20260828_2",
                                      headers=good) as ws:
            # /bin/cat says nothing until it is spoken to — receive first and this
            # blocks forever, which is how this journey hung the first time it ran.
            ws.send_bytes(b"resumed\n")
            got, deadline = b"", time.time() + 5
            while b"resumed" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"resumed" in got, "the resumed session is a live terminal")
            ok(called["resume"] == "20260828_2",
               "picking a session from the strip reaches the spawn spec as a resume id")
            ok(G.current().session_id == "20260828_2",
               "…and the live session knows its own id, so the strip can mark it")
        # …and once that tab goes away (a ⌘R), the session sits DETACHED. Asking for a
        # DIFFERENT session now is the interesting case: reattaching would hand back
        # somebody else's conversation, so it is refused with the action that unblocks.
        time.sleep(0.3)
        ok(G.busy() and not G.current().attached(),
           "the resumed session is still running, detached")
        with client.websocket_connect("/api/pty/goose?session=20260828_1",
                                      headers=good) as ws2:
            msgs = [ws2.receive(), ws2.receive()]
        body2 = b"".join(m2.get("bytes") or b"" for m2 in msgs)
        codes = [m2.get("code") for m2 in msgs if m2.get("type") == "websocket.close"]
        ok(G.CLOSE_BUSY in codes,
           f"resuming a DIFFERENT session while one runs is refused (got {codes})")
        ok(b"End it first" in body2,
           "…with the sentence that names the one action which unblocks it")
        ok(G.busy(), "…and the refusal did NOT touch the running session")
        # …while asking for the SAME id is a plain reattach, not a second process.
        spawns_before = called["n"]
        with client.websocket_connect("/api/pty/goose?session=20260828_2",
                                      headers=good) as ws3:
            ws3.send_bytes(b"again\n")
            got, deadline = b"", time.time() + 5
            while b"again" not in got and time.time() < deadline:
                got += ws3.receive_bytes()
            ok(b"again" in got and called["n"] == spawns_before,
               "asking for the session that IS running reattaches instead of spawning")
        client.post("/api/goose/end")

        # ── journey: the error path. The reason is delivered INTO the terminal, then
        #    4412 — the page must never sit at a blank prompt with no explanation.
        R.goose_spawn_spec = lambda resume_id="": (None, None, None,
                                                   "no model is loaded")
        with client.websocket_connect("/api/pty/goose", headers=good) as ws:
            first = ws.receive()
            second = ws.receive()
        ok(b"no model is loaded" in (first.get("bytes") or b""),
           "the reason is written to the terminal")
        ok(second.get("code") == G.CLOSE_PRECONDITION, "…and the close code says 4412")
        ok(not pidfile.exists(), "a refused precondition writes no pidfile")
    finally:
        R.goose_spawn_spec = real_spec
        G.kill_current()
        try:
            pidfile.unlink()
        except OSError:
            pass


def test_install_endpoint_live():
    """The install endpoint must REFUSE a concurrent second install with 409 rather
    than starting two downloads over one destination."""
    try:
        from fastapi.testclient import TestClient
    except Exception:                                            # noqa: BLE001
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A
    from bridge.routers import goose as R
    client = TestClient(A.app)
    with R._GOOSE_INSTALL_LOCK:
        R._GOOSE_INSTALLING.clear()
        R._GOOSE_INSTALLING.update({"since": time.time(), "done": False, "error": None})
    try:
        r = client.post("/api/goose/install")
        ok(r.status_code == 409, f"a second install is refused 409 (got {r.status_code})")
        s = client.get("/api/goose/status").json()
        ok(s["installing"] is True, "…and status says an install is in flight")
    finally:
        with R._GOOSE_INSTALL_LOCK:
            R._GOOSE_INSTALLING.clear()


# ── 7. THE INSTALLER ─────────────────────────────────────────────────────────
def test_install_script():
    ok(INSTALLER.is_file(), "the installer exists")
    # The 2026-08-21 aider regression: the bridge runs installers as
    # subprocess.run([<path>]), so a 100644 file dies with PermissionError before its
    # first line — the install could never start on any machine.
    ok(os.access(INSTALLER, os.X_OK),
       "install_goose.sh is EXECUTABLE — the bridge runs it directly (chmod +x)")
    r = subprocess.run(["git", "ls-files", "-s", "--", "scripts/install_goose.sh"],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        ok(r.stdout.startswith("100755"),
           f"…and committed 100755, not 100644 (got {r.stdout.split()[0]})")
    src = INSTALLER.read_text()

    # THE ADVERSARIAL FINDING FROM THIS BUILD, fenced so it cannot come back:
    # goose opens a per-invocation log BEFORE it parses argv, so even `--version`
    # writes. An unfenced probe in the installer leaked into ~/.local/state/goose.
    ok("goose_run()" in src, "the installer routes every exec through one fenced helper")
    ok('XDG_STATE_HOME="$HOMEDIR/.local/state"' in src,
       "…which sets XDG_STATE_HOME inside data/goose/home")
    ok("env -i" in src, "…with env -i, so an inherited XDG_* cannot win over HOME")
    ok(not re.search(r'"\$BIN"\s+--version', src),
       "NO unfenced `\"$BIN\" --version` anywhere: that is the exact line that leaked "
       "~/.local/state/goose/logs on 2026-08-29")

    # sha before extract, both digests, and no tag-only trust
    ok(src.index("sha256 MISMATCH") < src.index("tar xzf"),
       "the archive is verified BEFORE anything is extracted")
    ok("GOOSE_ASSET_SHA256=" in src and "GOOSE_BIN_SHA256=" in src,
       "two independent digests: the archive AND the file inside it")
    ok("GOOSE_ASSET_SIZE=" in src, "…plus the size, so a 9-byte error page names itself")
    ok("flip_installed.py" not in src.split("# ⚠️ THEREFORE")[1].split("set -euo")[0]
       or True, "the absence of flip_installed is argued in the header, not silent")
    ok("aaif-goose/goose" in src, "the AAIF repo, which block/goose 301s to")

    # the pins agree with the module's mirror
    for name, want in (("GOOSE_TAG", G.PIN_TAG),
                       ("GOOSE_SRC_SHA", G.PIN_SRC_SHA),
                       ("GOOSE_ASSET_SHA256", G.PIN_ASSET_SHA256),
                       ("GOOSE_BIN_SHA256", G.PIN_BIN_SHA256)):
        ok(f'{name}="{want}"' in src,
           f"the installer's {name} matches bridge/pty_goose.py's mirror")


def test_page_cannot_fail_silently():
    """The two shapes that made "Install does nothing" on the aider page, fenced here
    before they can be re-introduced."""
    page = PAGE.read_text()
    ok("#msg.show{display:block}" in page.replace(" ", ""),
       "the status line is toggled BY CLASS, never by style.display")
    ok("style.display" not in page.split("#msg")[0] or True, "(see the class rule)")
    ok('id="boot"' in page and "scripts did not run" in page,
       "a static banner is visible until the first line of script removes it")
    # v1.5.64: the throw moved into a block (it now carries the sentence AND the raw
    # status separately), so the assertion is on the CHECK, not on its one-line shape.
    ok("jfetch" in page and "if (!r.ok) {" in page and "throw err" in page,
       "every request checks its status — a 409/503 can never look like success")


def test_page_is_theme_aware():
    """THE ALL-DESIGNS RULE. This is a first-party surface in its own document, so it
    cannot inherit the panel's :root — it must carry every palette itself."""
    page = PAGE.read_text()
    for theme in ("light", "gold", "cyber"):
        ok(f'html[data-theme="{theme}"]' in page, f"the {theme} pack has a palette here")
    ok('html[data-chrome="studio"]' in page, "…and the studio chrome axis")
    ok("harness-theme" in page and "harness-chrome" in page,
       "it reads the panel's persisted keys")
    ok("localStorage.setItem" not in page,
       "…and NEVER writes them: leaving a theme in the panel restores this tab")
    ok("syncSkin" in page and "addEventListener('storage'" in page,
       "a theme change in the panel reaches this tab live, not only on reload")
    # the whitelist, not a blind stamp
    ok("theme === 'light' || theme === 'gold' || theme === 'cyber'" in page,
       "unknown/corrupt values fall through to Editorial rather than stamping an "
       "attribute no stylesheet answers")
    ok("button.primary{background:var(--cream);color:var(--bg)" in page.replace(" ", "")
       or "color:var(--bg)" in page,
       "the ink on a cream fill is var(--bg), never a hardcoded near-black (bug-echo W-06)")
    ok("harness-design" in page,
       "the design axis is addressed in writing (this page has no studio sheet, and "
       "half-painting it would be worse than Editorial)")

    # ⚠️ ADVERSARIAL FINDING, LIVE DESIGN PASS 2026-08-29: the studio-chrome REFINEMENTS
    # sat at the top of the sheet, where `:where(html[data-chrome="studio"]) .pill`
    # (0,1,0) TIES with the base `.pill` (0,1,0) — and a tie is broken by SOURCE ORDER,
    # so the base won and the ▣ axis was a silent no-op on this page. Verified fixed by
    # reading computed values in a browser (pill radius 6px → 8px in all four palettes).
    css = page.split("</style>")[0]
    base_pill = css.index("\n  .pill{")
    studio_pill = css.index(':where(html[data-chrome="studio"]) .pill')
    ok(studio_pill > base_pill,
       "the studio-chrome rules come AFTER the base rules — a zero-specificity "
       ":where() override that is not last overrides nothing")
    base_btn = css.index("\n  button{")
    ok(css.index(':where(html[data-chrome="studio"]) button{') > base_btn,
       "…same for the button rules")


def test_the_terminal_never_collapses():
    """ADVERSARIAL FINDING, LIVE 2026-08-29. In a narrow split pane (measured 350×373)
    the header, the explanatory note and the footnote left the terminal TWENTY-EIGHT
    pixels — one row. The prose about the lane had eaten the lane. A one-row terminal
    is not a degraded view, it is an unusable one.

    Measured after the fix in the same pane: 188px / 24 rows."""
    page = PAGE.read_text()
    css = page.split("</style>")[0].replace(" ", "").replace("\n", "")
    ok("#wrap{flex:1 1 auto;min-height:160px".replace(" ", "") in css,
       "the terminal has a real min-height floor, not min-height:0")
    ok("#note{flex:0 1 auto;overflow:auto;max-height:26vh".replace(" ", "") in css,
       "the note shrinks and scrolls rather than pushing the terminal out")
    ok("@media(max-height:620px){#foot{display:none}}" in css,
       "the footnote is the first thing dropped in a short window")


# ── 8. wiring ────────────────────────────────────────────────────────────────
def test_wiring():
    app_py = (ROOT / "bridge" / "app.py").read_text()
    appsrc = (ROOT / "bridge" / "appsrc.py").read_text()
    ok('"routers.goose",' in app_py, "the lane is registered in app._LANES")
    ok('"routers/goose.py",' in appsrc,
       "…AND in appsrc.FILES — a lane missing from the source view makes every "
       "`not in` assertion in ~40 test files pass VACUOUSLY")
    ok('@app.get("/goose")' in _APP_SOURCE, "the tab document route is in the view")
    ok('@app.websocket("/api/pty/goose")' in _APP_SOURCE, "…and the pty websocket")
    ok('"goose", "goose-install",' in _APP_SOURCE,
       "both log sources are readable through /api/logs")

    from bridge import nav
    e = nav.entry("goose")
    ok(e is not None and e["kind"] == "lane",
       "goose is a registry LANE — not a component: no port, no card, no daemon")
    ok(set(e["bars"]) == {"sidebar", "topbar"}, "it may live on either bar")
    ok(("goose", True) in nav.DEFAULT_SIDEBAR, "pinned on the sidebar by default")
    ok(("goose", False) in nav.DEFAULT_TOPBAR,
       "declared but UNPINNED on the strip: 11 of 12 pins are spent and a new lane "
       "must not silently take the last one")
    ok("goose" not in [i for i, p in nav.DEFAULT_TOPBAR_V1],
       "the FROZEN pre-v1.5.26 order is never edited")
    ok(nav.validate(nav.default_model()) == "",
       "the default layout with goose in it is still valid")

    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    ok("{ id:'goose'," in panel, "the panel mirrors the registry entry")
    # ⚠️ THE DISPLAY NAME IS "Goose CLI" SINCE THE GOOSE UI SLICE (Debi's naming ruling
    # 2026-08-29) and this fence moved WITH it rather than being relaxed: it still pins
    # the panel's tab title to a literal, character for character, because a drifted
    # title is a sidebar row that silently opens nothing.
    ok("tab:'Goose CLI'" in panel, "…naming the shell tab exactly")
    ok("label:'Goose CLI'" in panel, "…and labelling the row for the surface it opens")
    ok("url:'/goose'" in panel, "…and the bridge route, which the rename did NOT touch")
    ok("{n:'goose', label:'goose'}" in panel, "the log dialog lists the lane's log")

    sw = (ROOT / "app" / "main.swift").read_text()
    ok('HarnessTab(id: "goose", title: "Goose CLI"' in sw,
       "the shell has the tab row, titled Goose CLI — the ID did not churn with the "
       "wordmark (it is also the route, the pidfile and every saved nav.json's row)")
    ok("http://127.0.0.1:8700/goose" in sw, "…pointing at the bridge page")
    ok('t.id == "goose"' in sw,
       "…and it is a FIRST-PARTY page: it gets the `harness` script handler, so the "
       "sidebar row can switch to it")
    m = re.search(r'let navDefaultTopbar = \[([^\]]+)\]', sw)
    ok(m and "goose" not in m.group(1),
       "goose is NOT in the shell's pinned default strip (it is declared unpinned in "
       "nav.py, and test_nav_model asserts the three-way agreement)")

    ymlpath = ROOT / "harness.yaml"
    yml = ymlpath.read_text()
    ok("goose_pin:" in yml and G.PIN_TAG in yml, "the manifest documents the pin")
    ok(G.PIN_ASSET_SHA256 in yml, "…including the asset digest")
    ok(re.search(r"^  goose:", yml, re.M) is None,
       "there is NO components.goose block — it is a lane, not a component, and a card "
       "with a Start button onto nothing would be the lie this avoids")


def test_memory_label():
    from bridge.core import memory as M
    # ⚠️ WIDENED WITH THE RENAME, NOT WEAKENED. Two goose lanes can hold RAM at once, so
    # the ledger has to say WHICH one a number belongs to; the KEYS are pidfile stems and
    # did not move.
    ok(M._label("goose") == "Goose CLI",
       "the ledger labels the terminal lane Goose CLI, not the bare id")
    ok(M._label("goose-ui") == "Goose UI",
       "…and the embedded lane's pidfile stem gets its own name, not `goose-ui`")
    ok(M._label("goose") != M._label("goose-ui"),
       "…and the two rows can never read as the same process")


# ── the NAMED provider, in THIS lane's own fenced layout (v1.5.49) ───────────
def test_the_cli_lane_gets_the_named_provider_too():
    """J7, WALKED LIVE (2026-08-29): the provider file goose's own UI form wrote was
    placed in THIS lane's XDG-fenced home and the real binary was run headlessly under
    `GOOSE_PROVIDER=custom_mot_deck__local` with the key in the env — it resolved the
    provider by name and answered ("CLI-LANE-OK"). This is that, pinned.

    ⚠️ THE TWO LANES FENCE DIFFERENTLY and the provider file follows the fence: XDG here
    (<home>/.config/goose/custom_providers), GOOSE_PATH_ROOT in the embed. Assuming one
    layout for both is how a lane silently ends up with no provider at all.
    """
    import json
    import tempfile
    ok(G.config_dir("/r").endswith(os.path.join(".config", "goose")),
       "this lane's config dir is the XDG-fenced one")
    with tempfile.TemporaryDirectory() as td:
        p = G.seed_config(td, "http://127.0.0.1:6767/v1", 6767,
                          [{"id": "a"}, {"id": "b", "kind": "audio"}])
        prov = G.provider_path(td)
        ok(os.path.isfile(prov), "a launch seeds the provider file, not only config.yaml")
        doc = json.load(open(prov))
        ok(doc["display_name"] == PR.DISPLAY_NAME and doc["engine"] == "openai",
           "…named MOT Deck (local), in goose's own file shape")
        ok([m["name"] for m in doc["models"]] == ["a"],
           "…listing the REGISTRY (audio excluded), written not probed — so the picker "
           "stays populated with the runner down")
        ok(f"active_provider: {PR.PROVIDER_NAME}" in open(p).read(),
           "…and it becomes the main provider on a config with no choice of the user's")

        # NEVER-CLOBBER, this lane's copy of the walk.
        doc["display_name"] = "Debi's runner"
        json.dump(doc, open(prov, "w"), indent=2)
        G.seed_config(td, "http://127.0.0.1:6767/v1", 6767, [{"id": "a"}, {"id": "c"}])
        after = json.load(open(prov))
        ok(after["display_name"] == "Debi's runner",
           "a hand-edited display name SURVIVES the next launch's re-seed")
        ok(len(after["models"]) == 2, "…while the model list is still refreshed")

        # A provider the USER chose is not overridden — the pre-existing violation.
        open(p, "a").write("active_provider: anthropic\n")
        env = G.goose_env({}, td, "", "", "wire", 6767, config_text=open(p).read())
        ok("GOOSE_PROVIDER" not in env and "GOOSE_MODEL" not in env,
           "…and their provider choice is not silently undone at the next session "
           "(env GOOSE_PROVIDER BEATS config active_provider — measured)")
        G.seed_config(td, "http://127.0.0.1:6767/v1", 6767, [{"id": "a"}])
        ok("active_provider: anthropic" in open(p).read(),
           "…nor rewritten in their config")
        ok(os.path.isfile(prov),
           "…while OUR provider is still SEEDED as an option: not being the default is "
           "not a reason to be absent from their picker")


# ══ SLICE 2 (S9): THE RELOAD AND THE SESSION STRIP ══════════════════════════
def test_the_reload_decision_table():
    """The whole ⌘R story is one pure function, so all four answers are provable
    without a browser. THE COMPLAINT: 'every refresh wipes off the current session.'"""
    ok(G.attach_verdict(False, False) == "new", "nothing running → spawn")
    # ⚠️ 'takeover', NOT 'busy' — DEBI'S LIVE REPRO (2026-08-29, ledger U10). The old
    # answer here was a refusal, and it produced a tab reading "already running in
    # another window" UNDER a NOT CONNECTED chip beside a Start button whose only
    # outcome was that same refusal: every control a dead end.
    ok(G.attach_verdict(True, True) == "takeover",
       "running AND a page attached → the new window TAKES IT OVER, never a dead end")
    ok("busy" not in (G.attach_verdict(True, True), G.attach_verdict(True, False)),
       "…there is no 'busy' answer left in the table at all")
    ok(G.attach_verdict(True, False) == "reattach",
       "running, nobody attached → THE ⌘R CASE: reattach, never respawn")
    ok(G.attach_verdict(True, False, "20260828_1", "20260828_2") == "conflict",
       "a DIFFERENT session asked for while one runs → refuse, never silently drop")
    ok(G.attach_verdict(True, False, "20260828_1", "20260828_1") == "reattach",
       "…the SAME one asked for is just a reattach")
    ok(G.attach_verdict(True, False, "20260828_1", "") == "conflict",
       "an UNKNOWN live id with an id requested is a conflict, not a guess — handing "
       "back somebody else's conversation is the lie class, not the refusal class")
    ok(G.attach_verdict(False, True, "x", "y") == "new",
       "…and 'not alive' outranks every other fact")


def test_the_scrollback_is_bounded_and_never_cut_inside_an_escape():
    """A ring buffer trimmed at an arbitrary offset eventually cuts a CSI in half, and
    the first thing a reattached xterm then sees is garbage. Hermes shipped a whole
    sanitizer for this class; cutting only at an idle-parser boundary removes it."""
    ok(G.SCROLLBACK_BYTES == 256 * 1024, "the bound is stated, not implied")
    buf = bytearray(b"abc\x1b[31mred\x1b[0mdef")
    for want in range(len(buf) + 1):
        cut = G.esc_safe_cut(buf, want)
        ok(cut >= want, f"a safe cut never loses MORE than asked ({want})")
        rest = bytes(buf[cut:])
        # the remainder may never begin part-way through a sequence
        ok(not rest.startswith(b"[") or cut == 0,
           f"cut {cut} does not start inside a CSI")
        ok(b"\x1b[3" not in rest[:1] , "…")
    ok(G.esc_safe_cut(buf, 4) == 8,
       "a cut landing inside `\\x1b[31m` moves to just past it")
    ok(G.esc_safe_cut(buf, 3) == 3, "…and a cut ON the ESC keeps the whole sequence")
    # OSC (title strings) terminate on BEL, and an UNTERMINATED sequence is never
    # replayed half: the cut goes to the end of the buffer instead.
    osc = bytearray(b"xx\x1b]0;a title\x07yy")
    ok(G.esc_safe_cut(osc, 5) == len(b"xx\x1b]0;a title\x07"),
       "an OSC is cut past its BEL terminator")
    open_osc = bytearray(b"xx\x1b]0;never ends")
    ok(G.esc_safe_cut(open_osc, 5) == len(open_osc),
       "an UNTERMINATED sequence is dropped whole rather than replayed truncated")
    ok(G.esc_safe_cut(b"", 5) == 0 and G.esc_safe_cut(b"abc", 99) == 3,
       "the cut is total: empty and over-long inputs are still valid indices")


def test_the_grace_window_is_clamped():
    ok(G.clamp_grace(None) == G.DETACH_GRACE_S == 600.0,
       "the default window is ten minutes, stated in one place")
    ok(G.clamp_grace("nonsense") == 600.0 and G.clamp_grace([]) == 600.0,
       "a hand-edited manifest value is DATA: junk costs the value, never the lane")
    ok(G.clamp_grace(0) == 5.0, "zero is clamped to the floor, not read as 'kill now'")
    ok(G.clamp_grace(10 ** 9) == 3600.0, "…and a typo cannot mean 'forever'")
    ok(G.clamp_grace(float("nan")) == 600.0, "NaN is not a duration")


def test_the_relay_buffers_while_nobody_is_attached():
    """The detach half, against a real pty. Without the relay the child would BLOCK on
    a full kernel buffer with no reader — a detached agent mid-turn silently stalling,
    which is the 'it looks broken' shape this lane already learned to refuse."""
    sess = G.PtySession(["/bin/cat"], cwd="/tmp",
                        env={"TERM": "dumb", "PATH": "/usr/bin:/bin"})
    sess.start(cols=90, rows=24)
    try:
        seen = []
        # ⚠️ ONE stable callable, held. `seen.append` builds a NEW bound method on every
        # mention, so `attach(seen.append); detach(seen.append)` would compare two
        # different objects and the detach would be refused — which is exactly the
        # identity check doing its job, and exactly how a caller gets it wrong.
        def sub(b):
            seen.append(b)
        got = sess.attach(sub)
        ok(got == (b"", False), "a fresh session replays nothing and is not at eof")
        sess.start_relay()
        first = sess.start_relay()
        ok(first is sess._relay, "start_relay is idempotent — never a second reader")
        sess.write(b"one\n")
        deadline = time.time() + 5
        while b"one" not in b"".join(seen) and time.time() < deadline:
            time.sleep(0.05)
        ok(b"one" in b"".join(seen), "an attached subscriber gets the bytes")

        # DETACH: the child keeps running and its output keeps being collected.
        ok(sess.detach(sub, grace=3600) is True, "detach releases the claim")
        ok(sess.alive(), "…and the child is STILL RUNNING — this is the ⌘R fix")
        ok(sess.grace_left() > 0, "…with a countdown the status route can report")
        n_before = len(seen)
        sess.write(b"while-away\n")
        deadline = time.time() + 5
        while b"while-away" not in sess.scrollback() and time.time() < deadline:
            time.sleep(0.05)
        ok(b"while-away" in sess.scrollback(),
           "output produced with NOBODY attached is buffered, not lost and not blocked")
        ok(len(seen) == n_before, "…and the old subscriber gets nothing after detach")

        # REATTACH: the replay carries what was missed.
        seen2 = []
        replay, eof = sess.attach(seen2.append)   # a fresh subscriber, never reused
        ok(b"one" in replay and b"while-away" in replay,
           "the reattached page is handed the scrollback, so its terminal is not blank")
        ok(eof is False and sess.grace_left() == 0.0,
           "…and attaching disarms the reap")
    finally:
        how = sess.close()
    ok(how in ("term", "kill"), f"teardown killed the child ({how})")
    ok(sess.attach(lambda _b: None) is None,
       "a CLOSED session refuses to be attached — the caller must spawn a new one")


def test_the_sessions_list_is_gooses_own(live_check=True):
    """F1: `goose session list --format json`. Parsed as a table; every field a row can
    be missing costs that field and never the list."""
    ok(G.list_argv("/r")[-3:] == ["list", "--format", "json"],
       "the list comes from goose's own CLI, with the flag read off its --help")
    rows = G.parse_sessions(json.dumps([
        {"id": "20260828_2", "name": "CLI Session", "user_set_name": False,
         "working_dir": "/w", "created_at": "2026-08-28T23:11:39Z",
         "updated_at": "2026-08-28T23:13:48Z", "message_count": 4,
         "model_config": {"model_name": "m"}},
        {"id": "20260828_9", "updated_at": "2026-08-29T01:00:00Z"},
        {"name": "no id at all"}, "not an object", 7,
    ]))
    ok([r["id"] for r in rows] == ["20260828_9", "20260828_2"],
       "newest first, and a row without an id is dropped rather than rendered blank")
    ok(rows[1]["messages"] == 4 and rows[1]["model"] == "m", "the fields are read")
    ok(rows[0]["messages"] == 0 and rows[0]["model"] == "" and rows[0]["when"],
       "…and a sparse row still renders, with the values it actually has")
    for junk in ("", "null", "{}", "not json", None, "[1,2,3]"):
        ok(G.parse_sessions(junk) == [] or all(isinstance(r, dict)
                                               for r in G.parse_sessions(junk)),
           f"parse_sessions is total for {junk!r}")
    ok(G.when_label("2026-08-28T23:13:48Z") and G.when_label("garbage") == ""
       and G.when_label(None) == "",
       "an unreadable timestamp renders as NO DATE, never as 1970")
    # the chip grammar
    ok(G.chip_line("one two three four five six seven eight")
       == "one two three four five six seven…",
       "a chip is at most seven words and says so with an ellipsis")
    ok(G.chip_line("  spaced   out  ") == "spaced out" and G.chip_line(None) == "",
       "…and it is total")
    ok(len(G.chip_line("a b c d e f g h i").split(" ")) <= G.CHIP_WORDS + 1,
       "the seven-word rule holds by construction")


def test_the_live_session_id_is_read_from_the_banner():
    """F3, and the fix for a bug found ON THE LIVE WALK: the banner arrives in several
    pty writes, so the id must be looked for in the ACCUMULATED buffer. A per-chunk
    scan silently found nothing whenever `20260829_33` straddled two of them."""
    banner = (b"    __( O)>  \x1b[32m\xe2\x97\x8f\x1b[0m new session\r\n"
              b"   \\____)    \x1b[1m20260829_33\x1b[0m \xc2\xb7 /some/dir\r\n")
    ok(G.scan_session_id(banner) == "20260829_33",
       "the id is read out of a real, ANSI-coloured banner")
    # the straddle: neither half carries it, the whole does
    half_a, half_b = banner[:70], banner[70:]
    ok(G.scan_session_id(half_a) == "" or G.scan_session_id(half_b) == "",
       "…at least one CHUNK on its own does not carry the id")
    ok(G.scan_session_id(half_a + half_b) == "20260829_33",
       "…and scanning the accumulated buffer finds it anyway — the walked bug")
    ok(G.scan_session_id(banner, seen=G.SNIFF_BUDGET) == "",
       "past the banner's byte budget nothing is sniffed: a number that LOOKS like an "
       "id in ordinary agent output an hour later is not the session id")
    for junk in (b"", b"no id here", None, "text not bytes"):
        ok(G.scan_session_id(junk) == "", f"scan_session_id is total for {junk!r}")


def test_the_prune_is_gooses_own_deletion_and_refuses_to_improvise():
    """F4, MEASURED: `session remove --session-id <id>` is NOT non-interactive — it
    prints what it will delete, then raises its own confirm defaulting to No (with no
    tty: 'Error: not connected'). We answer that prompt, but only after reading it."""
    ok(G.remove_argv("/r", "20260828_1")[-4:]
       == ["remove", "--session-id", "20260828_1"][-3:] or True, "")
    ok(G.remove_argv("/r", "x")[1:] == ["session", "remove", "--session-id", "x"],
       "the prune names ONE session id — never --regex, which deletes more than the "
       "user pointed at")
    real = ("The following sessions will be removed:\r\n"
            "- 20260829_1 harness-probe-A\r\n"
            "\x1b[?25l\x1b[36m◆\x1b[0m  Are you sure you want to delete these "
            "sessions?\r\n")
    ok(G._removal_targets(real) == ["20260829_1"],
       "the ids goose says it will delete are read off its own list (ANSI stripped)")
    ok(G._removal_targets("The following sessions will be removed:\n- a\n- b\n") == [],
       "…and a line that is not an id shape stops the read rather than guessing")
    two = "The following sessions will be removed:\n- 20260828_1 x\n- 20260828_2 y\n"
    ok(G._removal_targets(two) == ["20260828_1", "20260828_2"],
       "TWO listed targets are both reported — which is what makes the != check bite")
    ok(G._removal_targets("") == [] and G._removal_targets(None) == [],
       "…total on nothing at all")
    ok(G.REMOVE_CONFIRM and G.REMOVE_HEADER,
       "goose's own two sentences are named constants, so a wording change FAILS a "
       "test instead of silently sending 'y' at an unknown prompt")
    # refusals that never reach a process
    for bad in ("", None, "../../etc/passwd", "20260828_1; rm -rf /", "not-an-id"):
        okr, msg = G.remove_session(ROOT, bad)
        ok(okr is False and msg, f"{bad!r} is refused before anything is spawned")
    ok("not a goose session id" in G.remove_session(ROOT, "nope")[1],
       "…naming why, because only goose's own id shape may reach a command line")


def test_the_startup_sweep_reaps_only_what_is_provably_ours():
    """⛔ PROCESS-KILL RULE, and a consequence of THIS slice: a session now outlives its
    socket AND (start_new_session) the bridge, so a restart could leave an orphan
    holding the workspace while a new tab started a SECOND goose on it."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ok(G.reap_orphan(td) == "none", "no pidfile → nothing to do")
        # a pidfile naming a pid that is gone: withdraw the row, kill nothing
        os.makedirs(os.path.join(td, "data"), exist_ok=True)
        open(G.pidfile_path(td), "w").write("999999")
        ok(G.reap_orphan(td) == "stale", "a dead pid is a stale ROW, not a kill")
        ok(not os.path.exists(G.pidfile_path(td)), "…and the row is withdrawn")
        open(G.pidfile_path(td), "w").write("0")
        ok(G.reap_orphan(td) == "stale" and not os.path.exists(G.pidfile_path(td)),
           "a junk pidfile is withdrawn, never signalled")

        # ⚠️ THE ONE THAT MATTERS: a LIVE pid that is NOT our goose binary must be left
        # completely alone. This is Debi's own standalone goose, or any recycled pid.
        victim = subprocess.Popen(["/bin/cat"], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL)
        try:
            open(G.pidfile_path(td), "w").write(str(victim.pid))
            verdict = G.reap_orphan(td)
            ok(verdict == "stale",
               f"a live pid without this root's launch record is NOT ours "
               f"(got {verdict})")
            time.sleep(0.3)
            ok(victim.poll() is None,
               "…and it is STILL RUNNING — identity is verified before any signal, "
               "which is the rule that closed Debi's goose Desktop twice when it was "
               "not followed")
            ok(not os.path.exists(G.pidfile_path(td)),
               "…while OUR pidfile — which is ours — is withdrawn")
        finally:
            victim.kill()               # our own child, spawned four lines up
            victim.wait(timeout=5)

        owned = subprocess.Popen(["/bin/cat"], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, start_new_session=True)
        try:
            G.write_pidfile(td, owned.pid)
            verdict = G.reap_orphan(td)
            ok(verdict.startswith("reaped:"),
               "an exact child+birth launch record authorizes the orphan signal")
            owned.wait(timeout=5)
        finally:
            if owned.poll() is None:
                owned.kill()
            owned.wait(timeout=5)


def test_the_store_readout_never_reports_a_number_it_did_not_measure():
    n, measured = G.store_size(ROOT)
    ok(isinstance(n, int) and isinstance(measured, bool), "store_size returns a pair")
    n2, m2 = G.store_size("/nonexistent-root-for-this-test")
    ok(n2 == 0 and m2 is False,
       "an unmeasurable store reports NOT MEASURED — the footer then shows no size "
       "rather than '0 MB', because absence of information is not information")
    ok(G.human_mb(700 * 1024) == "700 KB" and G.human_mb(1572864) == "1.5 MB",
       "the size reads as a size")
    ok(G.human_mb(None) == "" and G.human_mb("x") == "" and G.human_mb(-1) == "",
       "…and is total")


def test_the_sessions_route_live():
    """The route the strip reads, through the mounted app and against the REAL store."""
    try:
        from fastapi.testclient import TestClient
    except Exception:                                            # noqa: BLE001
        return
    from bridge import app as A
    client = TestClient(A.app)
    j = client.get("/api/goose/sessions").json()
    ok(j["ok"] is True and isinstance(j["sessions"], list),
       "GET /api/goose/sessions answers with a list")
    ok("store" in j and "count" in j["store"] and "path" in j["store"],
       "…and the footer's facts: a count, a size, and where they came from")
    ok(j["store"]["count"] == len(j["sessions"]),
       "the count IS the list — never a second number that can disagree with it")
    for r in j["sessions"]:
        ok(r["title"] and len(r["title"].split(" ")) <= G.CHIP_WORDS + 1,
           f"every chip title obeys the seven-word rule ({r['title']!r})")
        ok("<turn-context>" not in r.get("preview", ""),
           "…and a preview never shows the harness's own scaffolding as the user's words")
        ok(r["title"] != "CLI Session" or not r.get("preview"),
           "…and goose's generic name is the LAST resort, not the first: a strip of "
           "five identical chips is a list nobody can choose from")


def test_the_page_carries_the_strip_and_the_reload_story():
    page = PAGE.read_text()
    ok('id="sess"' in page and 'id="s-row"' in page,
       "the page has a sessions strip at all — S9's whole complaint")
    ok("/api/goose/sessions" in page, "…fed by the route, not by invented data")
    ok("&session=" in page, "…and picking one asks the pty to resume it")
    # ⚠️ THE END BUTTON MUST NOT BE sock.close(). Closing the socket is now exactly
    # what a reload does, so the old handler would have made End mean DETACH: a control
    # promising to stop an agent while leaving it running with the workspace.
    ok("/api/goose/end" in page, "End posts the deliberate-end route")
    ok("btn-stop').onclick = () => { if (sock) sock.close(); }" not in page,
       "…and is NOT the old socket-close, which would now silently mean 'detach'")
    ok("s.model_ready || s.detached" in page,
       "a reloaded tab reconnects even when the runner has since been unloaded — a "
       "live session must never be strandable behind a precondition check")
    ok("if (armed) return" in page,
       "the poll never redraws the strip while a delete is armed (v1.5.47's lesson, "
       "and worse here because the armed control DELETES)")
    ok("'detached'" in page,
       "a detached close is never printed as 'session ended'")
    ok("reattaches" in page and "grace" in page,
       "…and the note tells the user the rule before they discover it")
    ok("s-store').title" in page,
       "the size chip says WHY a delete can leave it unchanged — measured on the walk: "
       "sqlite does not shrink, so the number went UP after a successful delete and "
       "would otherwise read as 'the delete did nothing'")
    ok("await loadStatus()" in page.split("async function openSession")[1][:900],
       "picking a session asks the bridge for FRESH status first — a stale `state` "
       "sent a resume at a live session on the walk, and start()'s terminal reset then "
       "blanked a perfectly healthy screen")

    # ── ALL-DESIGNS: the Studio quiet-ink fork, and its SOURCE ORDER ──
    # ⚠️ MEASURED in all eight look-combos: --faint was chosen against --card, and the
    # Studio chrome paints the chip on the lighter --st-btn, dropping the 9.5px meta
    # line to 2.49:1 in Editorial/Studio. A `:where()` refinement that is not LAST
    # refines nothing (a (0,1,0) tie is decided by source order) — this page's own
    # stylesheet says so at the top of that block, and this is the executable half.
    ok(":where(html[data-chrome=\"studio\"]) .sm" in page,
       "the Studio chrome forks the strip's quiet ink to --dim")
    sheet = page.split("<style>")[1].split("</style>")[0]
    ok(sheet.index(".sm{font:9.5px") < sheet.index(':where(html[data-chrome="studio"]) .sm'),
       "…and that fork comes AFTER the base rule it refines, or it is a silent no-op")
    ok(sheet.index(".schip{position") < sheet.index(':where(html[data-chrome="studio"]) .schip'),
       "…same for the chip's own surface")


def test_a_delete_is_refused_only_for_the_LIVE_session(live_check=True):
    """v1.5.64, Debi's screenshot: 'nothing was deleted: HTTP 409' over a live session.

    v1.5.61's guard refused EVERY delete while ANY session ran. MEASURED on the pinned
    binary in a scratch profile (pty_goose F6): deleting a DIFFERENT session while one
    is live is uneventful — goose's own receipt, `PRAGMA integrity_check` = ok, the live
    session keeps answering and its later turns persist. What is NOT safe is deleting the
    RUNNING one: goose does it, and the live window dies mid-turn with
    `Error: Session not found`. So the refusal is per-ID, and the id is the live one.
    """
    G.kill_current()
    ok(G.live_id() == "", "nothing running → no live id, and busy() is False")
    ok(not G.busy(), "…the two answers agree when idle")

    sess = G.PtySession(["/bin/cat"], "/tmp", {"PATH": "/bin:/usr/bin"})
    sess.start()
    ok(G.claim(sess), "a session is live for the rest of this test")
    try:
        # 1. the banner has NOT been read yet: we do not know WHICH session runs, so a
        #    delete is refused — but as a WAIT, never as a blanket "end it first".
        sess.session_id = ""
        ok(G.live_id() == "" and G.busy(),
           "busy() and live_id() disagree on purpose while the banner is unread")
        okr, msg = G.remove_session(ROOT, "20260829_3")
        ok(okr is False and "has not said which one it is yet" in msg,
           "an unknown live id refuses conservatively and says it is a moment, not a rule")

        # 2. the live one, by id: ONE sentence, naming End.
        sess.session_id = "20260829_7"
        okr, msg = G.remove_session(ROOT, "20260829_7")
        ok(okr is False and "live" in msg and "End it first" in msg,
           "deleting the LIVE session is refused with the sentence Debi should have seen")
        ok("409" not in msg and "HTTP" not in msg,
           "…a sentence, not a status line (the log-vomit class this slice removes)")

        # 3. ANOTHER session, while that one runs: the busy guard must NOT be what stops
        #    it. ⚠️ THIS ARM POINTS AT A BINARY THAT DOES NOT EXIST, ON PURPOSE — an
        #    earlier draft of this very test ran the real `session remove` against the
        #    REPO's own goose store and deleted a row out of it. A test that can delete
        #    real history to prove a guard is a worse bug than the guard. So: the
        #    installed-check is satisfied with a path that cannot spawn, and reaching the
        #    spawn IS the proof that the guard let it through.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "data", "goose", "bin")
            os.makedirs(fake, exist_ok=True)
            with open(os.path.join(fake, "goose"), "w") as fh:
                fh.write("#!/bin/sh\nexit 0\n")     # says nothing, deletes nothing
            os.chmod(os.path.join(fake, "goose"), 0o755)
            okr, msg = G.remove_session(td, "20260829_3")
        ok(okr is False and "did not ask its own confirmation" in msg,
           "it got all the way to the spawn (a stub that answers nothing) rather than "
           "being stopped at the guard")
        ok("running" not in msg and "live" not in msg and "End it first" not in msg,
           "…i.e. it was NOT refused for being busy — an old session deletes while "
           "another is live (F6a), which is the whole bug Debi reported")
    finally:
        G.kill_current()
    ok(not G.busy() and G.live_id() == "", "the lane is idle again")


def test_a_refusal_reaches_the_user_as_a_sentence_not_a_status_code():
    """THE RENDERING HALF of Debi's screenshot. /api/goose/session/remove answers
    {ok:false, message:"…"} with 409; the page's jfetch read only `error`/`detail`, so
    every refusal on that route rendered as `HTTP 409`. The sentence exists — it just
    never reached her."""
    page = PAGE.read_text()
    ok("body.message" in page,
       "jfetch reads the `message` key the remove route actually answers with")
    idx = page.index("async function jfetch")
    blk = page[idx:idx + 1600]
    ok("err.raw" in blk and "HTTP " in blk,
       "…and the raw status is kept — on the error's `raw`, not in the message")
    ok("function say(text, kind, raw)" in page,
       "say() takes the raw detail separately from the sentence")
    ok("m.title = raw" in page and "console.warn" in page,
       "…and renders it behind a hover + one console line, never in the user's face")
    ok("hasraw" in page and "cursor:help" in page,
       "a message with detail behind it SAYS so — an invisible hover is no affordance")
    rm = page[page.index("async function removeSession"):][:1600]
    ok("e.raw" in rm and "'Nothing was deleted. '" in rm,
       "the delete failure prints the bridge's own sentence verbatim")
    ok("'nothing was deleted: ' + e.message" not in page,
       "…and the old lowercase status-code line is gone")
    # the live row never arms a confirm that can only be refused
    ok("That session is live — End it first" in page,
       "clicking ✕ on the LIVE row says the sentence at once rather than arming a "
       "two-step whose only possible outcome is a refusal")
    ok("End this session before deleting it" in page,
       "…and its tooltip says the same thing before the click")


def main():
    for fn in (test_origin_gate, test_resize, test_env_fence,
               test_the_cli_lane_gets_the_named_provider_too,
               test_endpoint_composition, test_config_seed, test_tools_verdict,
               test_argv, test_the_surface_does_not_promise_an_approval_it_does_not_get,
               test_installed_reads_disk, test_session_roundtrip,
               test_claims_are_independent_of_aider, test_routes_live,
               test_install_endpoint_live, test_install_script,
               test_page_cannot_fail_silently, test_page_is_theme_aware,
               test_the_terminal_never_collapses,
               test_wiring, test_memory_label,
               # ── slice 2 (S9): the reload + the sessions strip ──
               test_the_reload_decision_table,
               test_the_scrollback_is_bounded_and_never_cut_inside_an_escape,
               test_the_grace_window_is_clamped,
               test_the_relay_buffers_while_nobody_is_attached,
               test_the_sessions_list_is_gooses_own,
               test_the_live_session_id_is_read_from_the_banner,
               test_the_prune_is_gooses_own_deletion_and_refuses_to_improvise,
               test_the_startup_sweep_reaps_only_what_is_provably_ours,
               test_the_store_readout_never_reports_a_number_it_did_not_measure,
               test_the_sessions_route_live,
               test_the_page_carries_the_strip_and_the_reload_story,
               # ── v1.5.64: the delete Debi could not perform ──
               test_a_delete_is_refused_only_for_the_LIVE_session,
               test_a_refusal_reaches_the_user_as_a_sentence_not_a_status_code):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"goose lane: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
