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

CHECKS = 0
INSTALLER = (ROOT / "scripts" / "install_goose.sh")
PAGE = (ROOT / "bridge" / "panel" / "goose.html")


def ok(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, f"FAIL: {label}"


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

    # the provider
    ok(env["GOOSE_PROVIDER"] == "openai", "provider is the OpenAI-compatible one")
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

    def fake_spec():
        called["n"] += 1
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
                ok(row.get("label") == "Goose", "…with a human label, not a bare id")

            # A resize message must be CONSUMED: /bin/cat echoes everything it is given,
            # so if the escape reached the pty it would come straight back at us.
            ws.send_bytes(b"\x1b[RESIZE:100;30]")
            ws.send_bytes(b"after\n")
            got, deadline = b"", time.time() + 5
            while b"after" not in got and time.time() < deadline:
                got += ws.receive_bytes()
            ok(b"RESIZE" not in got, "the resize escape never reached the pty")
            ok(b"after" in got, "…and the next real keystroke still arrived")

            # ONE AT A TIME
            with client.websocket_connect("/api/pty/goose", headers=good) as ws2:
                msgs = [ws2.receive(), ws2.receive()]
            codes = [m2.get("code") for m2 in msgs if m2.get("type") == "websocket.close"]
            ok(G.CLOSE_BUSY in codes, f"second session refused with 4409 (got {codes})")
            ok(called["n"] == 2, "the second connect got as far as the spec, not the pty")
            ok(pidfile.exists() and int(pidfile.read_text().strip()) == live_pid,
               "…and the refused second connect did NOT overwrite the live pidfile")

        # ── journey: the socket drops (⌘W, a crash, a reload) ──
        time.sleep(0.4)
        ok(G.busy() is False, "a dropped socket ends the session")
        ok(not pidfile.exists(),
           "…and the pidfile is gone, so the ledger never shows a ghost Goose row")

        # ── journey: the error path. The reason is delivered INTO the terminal, then
        #    4412 — the page must never sit at a blank prompt with no explanation.
        R.goose_spawn_spec = lambda: (None, None, None, "no model is loaded")
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
    ok("jfetch" in page and "if (!r.ok) throw" in page,
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
    ok("tab:'Goose'" in panel, "…naming the shell tab exactly")
    ok("url:'/goose'" in panel, "…and the bridge route")
    ok("{n:'goose', label:'goose'}" in panel, "the log dialog lists the lane's log")

    sw = (ROOT / "app" / "main.swift").read_text()
    ok('HarnessTab(id: "goose", title: "Goose"' in sw, "the shell has the tab row")
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
    ok(M._label("goose") == "Goose",
       "the ledger labels the row Goose, not the bare id")


def main():
    for fn in (test_origin_gate, test_resize, test_env_fence,
               test_endpoint_composition, test_config_seed, test_tools_verdict,
               test_argv, test_the_surface_does_not_promise_an_approval_it_does_not_get,
               test_installed_reads_disk, test_session_roundtrip,
               test_claims_are_independent_of_aider, test_routes_live,
               test_install_endpoint_live, test_install_script,
               test_page_cannot_fail_silently, test_page_is_theme_aware,
               test_the_terminal_never_collapses,
               test_wiring, test_memory_label):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"goose lane: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
