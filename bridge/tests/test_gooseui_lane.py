#!/usr/bin/env python3
"""GOOSE UI (embed) SPIKE — the decision tables and the WALKED JOURNEYS.

Built to docs/research/2026-08-29-goose-desktop-ui.md. Per the proactive-build doctrine
every journey walked by hand during the spike is pinned here as an executable test, and
every adversarial finding that was FIXED has a fence that fails if it returns.

THE JOURNEYS THAT WERE ACTUALLY WALKED ON THE REAL STACK (2026-08-29, this Mac):

  J1  FIRST-EVER USE — open http://127.0.0.1:8700/gooseui/ in a plain browser. The goose
      UI renders, the shim installs, the ACP socket connects, and because the fenced
      config is pre-seeded there is NO onboarding: the composer already names our model
      and the goose-workspace directory. PROVEN by screenshot + DOM.
  J2  ONE REAL CHAT TURN — "Reply with exactly: SPIKE-OK" → "SPIKE-OK", 4.42 tok/s,
      4.9k tok, against llama-server on :6767 through goose's own OpenAI provider.
  J3  THE SAME PAGE IN WKWebView — the app's own web engine, same bridge origin. Loads,
      shim installs, ACP connects, AND completes its own real turn ("WK-SPIKE-OK",
      12.1 tok/s) with an EMPTY console-error list.
  J4  THE TWO LANES COEXIST — a PTY `goose session` (data/goose.pid) and the embedded
      goosed (data/goose-ui.pid) alive at the same instant, different homes, different
      session stores, and the embed stayed healthy throughout.
  J0  ⚠️ JOURNEY ZERO, THE INSTALL — a CLEAN data/goose/ui, the real 209MB download of
      the pinned upstream Goose.zip, all three digests firing, 89 files unpacked, in
      15.9s. Then the tab's own empty state: Install (with the size on the button) →
      progress → the UI. Walked for real; the ~/Downloads shortcut the spike started
      with is DELETED (doctrine 2b).
  J5  THE ERROR PATH — bundle absent → the Install empty state, never a blank tab and
      never the goose UI with a dead socket behind it.

THE ADVERSARIAL FINDINGS THIS FILE FENCES (all fixed):

  A1  ⚠️ THE TRAILING SLASH. Served at `/gooseui`, the vendored document's RELATIVE
      `./assets/index-*.js` resolved to `/assets/…` — a real, OCCUPIED mount in this
      harness (the panel's vendor tree). The page did not fail into an obvious hole: it
      asked our own asset route for goose's bundle, got 404s, and rendered a black
      rectangle. Fixed with a 308 to `/gooseui/`. LIE-TO-USER class by outcome: the
      surface looked like "goose is broken".
  A2  ⚠️ READ IDENTITY BEFORE KILL. A restart helper cleared "our" ACP port with
      `lsof -ti tcp:N | xargs kill -9` and closed Debi's own standalone goose Desktop
      TWICE. Every signal is now gated on is_ours() — the live process's command line
      AND its GOOSE_PATH_ROOT. A busy port is answered by choosing another port, never
      by clearing it. (Same shape as the recorded Unsloth incident; the general rule is
      in the function's name.)
  A4  ⚠️ THE CONSENT STEP. With GOOSE_MODE unset the embedded agent was asked to create
      a file and DID — no card, no prompt (upstream defaults to `auto` at this pin). The
      terminal lane had already recorded this once; inheriting the default here shipped
      it twice. Fixed with GOOSE_MODE=smart_approve in BOTH the env and the seeded
      config, and re-walked: the write now raises a permission card in the UI, because
      on the desktop platform the ask travels over ACP (session/request_permission).
  A3  The locale. appConfig carried "en-US"; the bundle ships its catalogue as `en`, so
      every load logged a fallback warning. A warning that always prints is a warning
      nobody reads.

Run: python3 bridge/tests/test_gooseui_lane.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge import gooseui as G                                      # noqa: E402
from bridge import pty_goose as P                                    # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE                  # noqa: E402

CHECKS = 0


def ok(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, f"FAIL: {label}"


# ── A1: the trailing slash, and the shim's position ──────────────────────────
def test_entry_document():
    doc = ('<!doctype html><html><head><meta charset="UTF-8" />'
           '<title>Goose</title>'
           '<script type="module" crossorigin src="./assets/index-x.js"></script>'
           '<link rel="stylesheet" href="./assets/index-x.css">'
           '</head><body><div id="root"></div></body></html>')
    out = G.page_html(doc, "/gooseui/harness-preload.js")
    ok(out.index("harness-preload.js") < out.index('type="module"'),
       "the shim tag precedes the module script (a module is deferred by definition, so "
       "a classic tag above it is the only guaranteed ordering)")
    ok('type="module"' not in out.split("harness-preload.js")[0],
       "the shim is NOT a module — that would defer it into the same queue and make the "
       "ordering depend on fetch timing")
    ok("./assets/index-x.js" in out,
       "A1: the vendored document's own relative refs are UNCHANGED — the fix is the "
       "308 to /gooseui/, not a rewrite of upstream's markup")
    ok(f"<title>{G.SURFACE_NAME}</title>" in out and G.SURFACE_NAME == "Goose UI",
       "OUR surface is named Goose UI (Debi 2026-08-29); the bundle is not rebranded")
    # Total: a bundle without the entry tag still gets a shim rather than a blank page.
    ok("/x.js" in G.page_html("<html><head></head></html>", "/x.js"),
       "a reshuffled bundle still gets the shim (in <head>) rather than nothing")
    ok("/x.js" in G.page_html("no html at all", "/x.js"),
       "…and so does a document with no <head>")
    ok(G.retitle("<html><body>x</body></html>") == "<html><body>x</body></html>",
       "a document with no <title> is returned UNTOUCHED, not guessed at")


def test_route_shapes_are_registered():
    for needle in ("/gooseui", "/api/gooseui/status", "/api/gooseui/start",
                   "/api/gooseui/stop", "harness-preload.js"):
        ok(needle in _APP_SOURCE, f"{needle} is in the app-layer source view")
    ok("status_code=308" in _APP_SOURCE,
       "A1: the slashless URL redirects rather than serving a document whose relative "
       "asset refs would resolve into the panel's /assets mount")


# ── A2: read identity before kill ────────────────────────────────────────────
def test_no_kill_by_port_or_pattern():
    from bridge.routers import gooseui as R
    ok(callable(R.is_ours), "the identity gate exists as a function, not a habit")
    for junk in (None, "x", 0, 1, -3, 10 ** 9):
        ok(R.is_ours(junk) is False, f"is_ours refuses {junk!r} — no doubt is 'ours'")
    router = (ROOT / "bridge" / "routers" / "gooseui.py").read_text()
    # ⚠️ EXECUTABLE TEXT ONLY — comments and docstrings removed. The banned words appear
    # in the prose above on purpose, because the prose is what stops the next person
    # reintroducing them; a gate that banned the WORD would ban its own explanation.
    import io
    import tokenize
    code = " ".join(t.string for t in tokenize.generate_tokens(io.StringIO(router).readline)
                    if t.type not in (tokenize.COMMENT, tokenize.STRING))
    ok("pkill" not in code and "killall" not in code,
       "A2: no pattern-scoped kill anywhere in the lane")
    ok(not re.search(r"lsof[^\n]*kill", code),
       "A2: no port-scoped kill anywhere in the lane — a busy port is answered by "
       "choosing another, because the process holding it may be Debi's own goose")
    import ast
    for fn in ast.walk(ast.parse(router)):
        if isinstance(fn, ast.FunctionDef):
            seg = ast.get_source_segment(router, fn) or ""
            if "killpg" in seg:
                ok("is_ours(" in seg,
                   f"{fn.name}() signals only after an identity check")
            if fn.name == "_free_port":
                body = " ".join(ast.get_source_segment(router, st) or ""
                                for st in fn.body
                                if not (isinstance(st, ast.Expr)
                                        and isinstance(st.value, ast.Constant)))
                ok("kill" not in body,
                   "the port chooser MOVES ASIDE; it never clears a held port")


# ── the fence: two lanes, two homes ──────────────────────────────────────────
def test_the_two_lanes_cannot_collide():
    ok(G.ui_home("/r") != P.goose_home("/r"), "different homes")
    ok(G.config_path("/r") != P.config_path("/r"), "different config files")
    ok(G.pidfile_path("/r") != P.pidfile_path("/r"), "different pidfiles")
    ok(not G.ui_home("/r").startswith(P.goose_home("/r") + os.sep)
       and not P.goose_home("/r").startswith(G.ui_home("/r") + os.sep),
       "neither home is inside the other — a rm -rf of one must not take the other")
    ok(G.workspace_path("/r") == P.workspace_path("/r"),
       "…but the WORKSPACE is deliberately shared: it is the user's project directory, "
       "not lane state, and two 'my files' for one product is the surprise")


def test_env_fence_survives_a_hostile_environment():
    hostile = {"HOME": "/Users/somebody",
               "XDG_CONFIG_HOME": "/Users/somebody/.config",
               "XDG_DATA_HOME": "/Users/somebody/.local/share",
               "XDG_STATE_HOME": "/Users/somebody/.local/state",
               "XDG_CACHE_HOME": "/Users/somebody/.cache",
               "HF_HOME": "/Users/somebody/.cache/huggingface",
               "GOOSE_TOOLSHIM": "true", "COLUMNS": "500",
               "GOOSE_PATH_ROOT": "/Users/somebody/goose"}
    env = G.serve_env(hostile, "/r", "tok", "http://127.0.0.1:6767/v1", "k", "m")
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
                "XDG_CACHE_HOME", "HF_HOME", "GOOSE_PATH_ROOT"):
        ok("somebody" not in env[key], f"{key} did not survive from the hostile env")
    ok(env["GOOSE_PATH_ROOT"] == G.path_root("/r"),
       "GOOSE_PATH_ROOT is the fence goose itself honours (verified with `goose info` "
       "on the pinned binary: config/, data/sessions/, state/logs all move)")
    ok("GOOSE_TOOLSHIM" not in env,
       "the toolshim can only talk to ollama or goose's bundled llama.cpp, never our "
       ":6767 runner — leaving it on would silently degrade the lane")
    ok("COLUMNS" not in env, "no inherited terminal geometry on a server process")
    for k, v in (("GOOSE_TELEMETRY_OFF", "1"), ("GOOSE_TELEMETRY_ENABLED", "false"),
                 ("GOOSE_DISABLE_KEYRING", "true"),
                 ("GOOSE_DISABLE_AUTO_DOWNLOAD", "1"),
                 ("GOOSE_MODE", "smart_approve")):
        ok(env[k] == v, f"{k}={v} on every launch")
    # A4 (adversarial, LIE-TO-USER class by outcome): with GOOSE_MODE unset the embedded
    # agent wrote GOOSEUI-WROTE-THIS.txt to the real workspace with NO prompt — the exact
    # defect bridge/pty_goose.py recorded for the terminal lane, inherited by default.
    ok(env["GOOSE_MODE"] != G.FORBIDDEN_MODE,
       "A4: `auto` must never be on the line, inherited or set")
    hostile2 = dict(hostile); hostile2["GOOSE_MODE"] = "auto"
    ok(G.serve_env(hostile2, "/r", "t", "", "", "m")["GOOSE_MODE"] == "smart_approve",
       "…and an operator shell exporting GOOSE_MODE=auto cannot win either")


def test_endpoint_composition():
    """The /v1/v1 trap: goose composes OPENAI_HOST + '/' + OPENAI_BASE_PATH, while
    harness.yaml's runner.endpoint is the OpenAI BASE (…:6767/v1)."""
    ok(G._openai_host("http://127.0.0.1:6767/v1") == "http://127.0.0.1:6767", "strips /v1")
    ok(G._openai_host("http://127.0.0.1:6767/v1/") == "http://127.0.0.1:6767", "…and a slash")
    for junk in (None, 17, [], "", "   ", "not a url"):
        ok(G._openai_host(junk, 6767) == "http://127.0.0.1:6767",
           f"junk endpoint {junk!r} costs the VALUE, never the launch")


# ── the seeded config: no onboarding, nothing else lost ──────────────────────
def test_config_seed_preserves_what_the_user_added():
    with tempfile.TemporaryDirectory() as td:
        p = Path(G.config_path(td))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# my notes\nextensions:\n  developer:\n    enabled: true\n"
                     "OPENAI_HOST: http://stale:1\n")
        G.seed_config(td, "http://127.0.0.1:6767/v1", "my-model", 6767)
        got = p.read_text()
        ok("# my notes" in got, "comments survive — this is a TEXT edit, not a yaml "
                                "round-trip (a dumper eats comments and writes `null`)")
        ok("  developer:" in got, "the user's extensions survive a re-seed")
        ok("OPENAI_HOST: http://127.0.0.1:6767" in got, "our key is UPDATED in place")
        ok("stale" not in got, "…not appended alongside the stale one")
        ok("GOOSE_PROVIDER: openai" in got and "GOOSE_MODEL: my-model" in got,
           "provider+model seeded, which is what makes onboarding never appear")
        # Idempotent: a second seed must not grow the file.
        before = p.read_text()
        G.seed_config(td, "http://127.0.0.1:6767/v1", "my-model", 6767)
        ok(p.read_text() == before, "re-seeding is idempotent")


# ── the ACP endpoint ─────────────────────────────────────────────────────────
def test_acp_url_and_argv():
    ok(G.acp_url(3287, "tok") == "ws://127.0.0.1:3287/acp?token=tok",
       "main.js's own builder shape — getAcpUrl has NO fallback in acpConnection.ts")
    ok(G.serve_argv("/r", 3287)[1:5] == ["serve", "--platform", "desktop",
                                         "--enable-scheduler"],
       "--platform desktop is what the Desktop's own main process passes")
    ok(G.allowed_origins(8700) == ["http://127.0.0.1:8700", "http://localhost:8700"],
       "--allowed-origin REPLACES the default loopback set, so a partial list is worse "
       "than none")
    ok(len(G.new_token()) >= 32 and G.new_token() != G.new_token(),
       "a fresh secret per process, never a constant")


# ── containment ──────────────────────────────────────────────────────────────
def test_bundle_containment():
    for bad in ("../../../etc/passwd", "/etc/passwd", "", "   ", None, 17, "a\x00b",
                "assets/../../../../etc/passwd"):
        target, why = G.bundle_target(ROOT, bad)
        ok(target is None, f"refused {bad!r}")
        ok(isinstance(why, str) and why, "…with a reason (the route turns them all "
                                         "into an identical 404 — free reconnaissance "
                                         "is not a debugging aid)")
    if (ROOT / "data" / "goose" / "ui" / "index.html").is_file():
        t, why = G.bundle_target(ROOT, "index.html")
        ok(t is not None and why is None, "a real bundle file resolves")


def test_media_types_are_forced():
    ok(G.media_type_for("a/b.js").startswith("text/javascript"),
       "a module script served as octet-stream is refused by the browser")
    ok(G.media_type_for("a/b.woff2") == "font/woff2", "fonts")
    ok(G.media_type_for("a/b.unknown") == "application/octet-stream", "unknown is safe")


# ── J5: graceful absence ─────────────────────────────────────────────────────
def test_absent_dependency_lands_on_something_usable():
    from bridge.routers import gooseui as R
    with tempfile.TemporaryDirectory() as td:
        installed, reason = G.is_installed(td)
        ok(not installed, "an empty tree reads as not-installed (from DISK, every time)")
        ok("install_goose.sh" in reason or "install_goose_ui.sh" in reason,
           "…and the reason names the script that fixes it")
    page = R._fallback_page("the bundle is not installed yet")
    ok("<h2>" in page and "install_goose_ui.sh" in page,
       "J5: the failure page is READABLE and actionable, never a blank tab or raw JSON")
    ok("/goose" in page, "…and points at the terminal lane, which is unaffected")
    # J0: the EMPTY STATE is an ACTION, not an apology — Install, with the real size on
    # the button, then progress, then the UI (Debi's house-component ruling).
    st = dict(G.install_state(ROOT)); st["binary"] = st["bundle"] = False
    st["ready"] = False
    empty = R._empty_state_page(st)
    ok("Install (" in empty and str(st["asset_mb"]) in empty,
       "J0: the button states the download size BEFORE the user commits to it")
    ok(st["asset_sha256"][:16] in empty,
       "…and names the digest everything is verified against")
    ok("/api/gooseui/install" in empty and "/api/gooseui/status" in empty,
       "…and drives the same API the rest of the lane reports through — one source of "
       "truth about whether this thing is installed")
    ok("poll()" in empty,
       "a tab REOPENED mid-install shows progress rather than a button that would start "
       "a second download")


# ── the shim catalogue ───────────────────────────────────────────────────────
def test_the_shim_is_complete_and_honest():
    js = G.preload_js({"acp_url": "ws://x/acp?token=t", "secret": "t",
                       "app_config": G.app_config("1.48.0", "/ws", "m")})
    for name in G.PRELOAD_METHODS:
        ok(re.search(rf"\b{re.escape(name)}\s*:", js), f"the shim defines {name}")
    ok("getAcpUrl" in G.SHIMMED, "the one connection-critical method is a REAL shim")
    ok(len(G.DEGRADED) >= 10, "the honest degradations are enumerated, not glossed")
    for name, why in G.DEGRADED.items():
        ok(name in js and len(why) > 15, f"{name} degrades with a sentence")
    ok("console.warn" in js,
       "a degraded call SAYS what was lost — silence is how a stub becomes a lie")
    ok("writable: false" in js,
       "window.electron is non-writable, like contextBridge's own exposure")
    ok('"GOOSE_LOCALE": "en"' in js or "'GOOSE_LOCALE': 'en'" in js
       or '"GOOSE_LOCALE":"en"' in js,
       "A3: the locale is the one the bundle actually ships a catalogue for")


def test_the_lane_is_REACHABLE():
    """S14 — THE WIRING. v1.5.40 shipped a surface with NO WAY TO GET TO IT: the page
    existed at /gooseui/ and nothing in the product pointed at it, so it was reachable
    only by typing a URL. This is the fence for every party that has to agree about that
    row — nav.py (the authority), the panel (the mirror the sidebar renders) and the
    shell (the tab the row asks for). A disagreement between any two of them is a dead
    sidebar click, which is exactly the failure the Generate slice caught live.
    """
    from bridge import nav
    e = nav.entry("gooseui")
    ok(e is not None and e["kind"] == "lane",
       "nav.py knows `gooseui` as a lane (no port, no card — the page owns its goosed)")
    ok(e and set(e["bars"]) == {"sidebar", "topbar"}, "…allowed on either bar")
    ok(("gooseui", True) in nav.DEFAULT_SIDEBAR, "pinned on the sidebar by default")
    ok(("gooseui", False) in nav.DEFAULT_TOPBAR,
       "declared but UNPINNED on the strip: 11 of 12 pins are spent, and pinning the "
       "embedded lane while the terminal one waits behind ⋯ would pick a winner between "
       "two lanes Debi's ruling says coexist")
    ok("gooseui" not in [i for i, _p in nav.DEFAULT_TOPBAR_V1],
       "the FROZEN pre-v1.5.26 order is never edited")
    ok(nav.validate(nav.default_model()) == "",
       "the default layout with gooseui in it is still valid")
    nids = list(nav.NAV_IDS)
    ok(nids.index("gooseui") == nids.index("goose") + 1,
       "…and it sits DIRECTLY after the terminal lane: one product, two surfaces")

    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    ok("{ id:'gooseui'," in panel, "the panel mirrors the registry entry")
    ok("tab:'Goose UI'" in panel, "…naming the shell tab exactly")
    ok("label:'Goose UI'" in panel, "…and labelling the row")
    # ⚠️ A1 AGAIN, ONE LAYER UP. The route fix was a 308; a nav row pointing at the
    # slashless form takes that redirect on every browser-fallback open, and any future
    # caller that skips the redirect is back to the black rectangle.
    ok("url:'/gooseui/'" in panel,
       "…and its URL carries the trailing slash the vendored bundle needs (A1)")

    sw = (ROOT / "app" / "main.swift").read_text()
    ok('HarnessTab(id: "gooseui", title: "Goose UI"' in sw, "the shell has the tab row")
    ok("http://127.0.0.1:8700/gooseui/" in sw,
       "…pointing at the bridge page, trailing slash included (A1)")
    ok('t.id == "gooseui"' in sw,
       "…and it is served from OUR origin with OUR preload, so it gets the `harness` "
       "script handler and the sidebar row can switch to it")
    m = re.search(r'let navDefaultTopbar = \[([^\]]+)\]', sw)
    ok(m and "gooseui" not in m.group(1),
       "gooseui is NOT in the shell's pinned default strip (declared unpinned in nav.py, "
       "and test_nav_model asserts the three-way agreement)")

    # THE RENAME (Debi's naming ruling 2026-08-29): every place the PTY lane's label is
    # DISPLAYED now says "Goose CLI", and no route, id or pty path moved with it.
    goose_page = (ROOT / "bridge" / "panel" / "goose.html").read_text()
    ok("<title>Goose CLI" in goose_page and ">Goose CLI<" in goose_page,
       "the terminal lane's own page wears the new name in its title and its header")
    ok("document.title = 'Goose CLI" in goose_page,
       "…including the title its boot script sets once the scripts have run")
    ok('HarnessTab(id: "goose", title: "Goose CLI"' in sw
       and "http://127.0.0.1:8700/goose\"" in sw,
       "the shell titles it Goose CLI while its ROUTE is untouched")
    ok("/api/pty/goose" in goose_page,
       "…and the pty path did not churn with the wordmark either")

    # THE MEMORY LEDGER (v1.5.40's own named honest limit, closed here). The pidfile
    # already existed; what was missing was a NAME for the row it produces.
    from bridge.core import memory as M
    ok(os.path.basename(G.PIDFILE_REL) == "goose-ui.pid",
       "the embed's pidfile is data/goose-ui.pid — the ledger keys on the STEM")
    ok(M._label("goose-ui") == "Goose UI",
       "…and core/memory.py gives that stem its own name, so the row is not a filename")
    ok(M._label("goose") == "Goose CLI" and M._label("goose") != M._label("goose-ui"),
       "…while the terminal lane's row says which goose IT is: two lanes, two names")
    # The own-pidfile exclusion is what stops this row being swallowed by "Bridge" — the
    # measured v1.5.37 bug, which silently attributed a whole agent's footprint to the
    # bridge. The exclusion must keep running BEFORE the bridge row is built.
    src = (ROOT / "bridge" / "core" / "memory.py").read_text()
    ok(re.search(r"owned = \{p for p in pf\.values\(\)\}[\s\S]{0,400}"
                 r"p not in owned[\s\S]{0,200}add\(\"bridge\"", src),
       "the bridge row still EXCLUDES every pid that has a pidfile of its own — the more "
       "specific claimant first, or this row comes out empty and is dropped")


def main():
    for fn in (test_entry_document, test_route_shapes_are_registered,
               test_the_lane_is_REACHABLE,
               test_no_kill_by_port_or_pattern, test_the_two_lanes_cannot_collide,
               test_env_fence_survives_a_hostile_environment,
               test_endpoint_composition, test_config_seed_preserves_what_the_user_added,
               test_acp_url_and_argv, test_bundle_containment,
               test_media_types_are_forced,
               test_absent_dependency_lands_on_something_usable,
               test_the_shim_is_complete_and_honest):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"goose UI lane: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
