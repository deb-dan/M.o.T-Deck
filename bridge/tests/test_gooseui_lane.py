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

  ── v1.5.49, THE NAMED PROVIDER (S-ISO-4). Journeys walked 2026-08-29 ──
  J6  ⚠️ THE CENSUS ITSELF WAS A JOURNEY. goose's own Settings → Models → Configure
      providers → Configure manually form was DRIVEN in this very UI (Provider Type =
      OpenAI Compatible, "MOT Deck (local)", http://127.0.0.1:6767, two real registry
      ids) and the file GOOSE wrote was read off disk. That file is the schema; nothing
      about it is guessed. See bridge/gooseprov.py. It closes v1.5.40's honest limit
      ("three on-disk custom layouts all 'Unknown provider'").
  J7  THE MIGRATION, FROM THE REAL PRE-SLICE STATE. The fenced config was restored to
      its pre-slice bytes (GOOSE_PROVIDER/GOOSE_MODEL top-level, active_provider:
      openai), the lane restarted, and: the provider file appeared with ALL 16 registry
      chat models, the two legacy keys were removed, active_provider became ours, and
      NO secrets.yaml was written.
  J8  THE PICKER, AND A REAL TURN. goose's own provider dropdown lists "MOT Deck
      (local)"; its model dropdown under it lists 16 rows (6 of them MLX paths);
      switching says "using … from MOT Deck (local)"; the turn answered
      "NAMED-PROVIDER-UI-OK". ⚠️ The picker showed SIXTEEN models while llama-server
      serves exactly ONE — which is the proof that the list is CONFIG-RESIDENT, not
      probed, i.e. that it survives the runner being down.
  J9  THE CLI LANE, SAME PROVIDER. /goose → Start → the session banner reads
      "new session · custom_mot_deck__local …" and the turn answered "CLI-NAMED-OK"
      in 2.57s. Its provider file lives in the XDG-fenced home; two homes, two files.
  J10 NEVER-CLOBBER, LIVE. `display_name` hand-edited to "Debi hand-edited this" plus a
      custom header, lane restarted → BOTH survived while the model list refreshed.
  J11 THE USER'S CHOICE, LIVE. active_provider set to `anthropic` by hand, lane
      restarted → the child got NO GOOSE_PROVIDER and NO GOOSE_MODEL, the config was
      untouched, and our provider stayed SEEDED as an option (16 models).

THE ADVERSARIAL FINDINGS THIS FILE FENCES (all fixed):

  A5  ⚠️ THE PIDFILE WAS ERASED BEFORE IT WAS READ. The bridge restarted between a
      /start and a /stop; the new process had no Popen handle, _stop_locked cleared the
      pidfile and answered "gone", and a live fenced goosed of ours kept its port and
      its session DB with its only cross-restart handle deleted — two of ours listening
      at once. The no-handle path now reaps THROUGH the pidfile first. Found by walking,
      not by reading.
  A6  ⚠️ THE PROVIDER OVERRIDE (pre-existing, both lanes, LIE-TO-USER class by outcome).
      env GOOSE_PROVIDER BEATS config active_provider — measured both ways on the pinned
      binary. So `GOOSE_PROVIDER=openai` on every launch silently undid any provider the
      user had picked inside goose, right after goose's own toast said "Successfully
      switched models". Now seeded-not-enforced (gooseprov.provider_choice).

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
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge import gooseui as G                                      # noqa: E402
from bridge import gooseprov as PR                                   # noqa: E402
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
        ok(f"active_provider: {PR.PROVIDER_NAME}" in got,
           "the MAIN PROVIDER is seeded — which is what makes onboarding never appear — "
           "and it is our NAMED one, not the anonymous stock `openai` (v1.5.49)")
        ok("GOOSE_PROVIDER:" not in got and "GOOSE_MODEL:" not in got,
           "…through goose's OWN key, not the legacy top-level pair: goose deletes those "
           "two the moment a user switches provider in its UI (measured), so writing "
           "them back would leave two sources of truth for one setting")
        # Idempotent: a second seed must not grow the file.
        before = p.read_text()
        G.seed_config(td, "http://127.0.0.1:6767/v1", "my-model", 6767)
        ok(p.read_text() == before, "re-seeding is idempotent")


# ── THE NAMED PROVIDER, AND THE NEVER-CLOBBER MATRIX ─────────────────────────
def test_named_provider_file_matches_what_goose_itself_wrote():
    """J6 (walked live in this very UI): goose's own Add-custom-provider form created
    the provider; we read the file IT wrote; this is that file's shape, pinned.

    Every field below was copied off disk, not designed. See bridge/gooseprov.py for the
    method and for the four facts that killed v1.5.40's three guessed layouts.
    """
    ok(PR.slugify(PR.DISPLAY_NAME) == PR.PROVIDER_NAME,
       "our provider NAME is goose's own slug for our display name — which is what makes "
       "a provider the user later edits in goose's form still be ours")
    ok(PR.PROVIDER_NAME == "custom_mot_deck__local",
       "…and the DOUBLE underscore is real: goose maps each non-alphanumeric character "
       "to one '_', so the space AND the '(' each contribute (a collapsing slugifier "
       "would write a file goose's form could never match)")
    ok(PR.api_key_env() == "CUSTOM_MOT_DECK__LOCAL_API_KEY",
       "the key env var is DERIVED from the provider name by goose, not chosen by us")
    doc = PR.provider_doc("http://127.0.0.1:6767",
                          PR.model_entries([{"id": "m1"}]))
    ok(doc["engine"] == "openai",
       "the FILE's engine is `openai` — the form's `openai_compatible` is a UI enum "
       "goose maps down on the way to disk")
    ok(doc["base_url"] == "http://127.0.0.1:6767" and doc["base_path"] is None,
       "base_url is the ORIGIN and base_path stays null: goose appends its own "
       "v1/chat/completions, so a `…/v1` base would produce /v1/v1/… (the 404 that "
       "reads as 'the model is broken')")
    for k in ("name", "engine", "display_name", "description", "api_key_env",
              "base_url", "models", "headers", "timeout_seconds", "supports_streaming",
              "requires_auth", "catalog_provider_id", "base_path", "env_vars",
              "dynamic_models", "skip_canonical_filtering", "model_doc_link",
              "setup_steps", "fast_model", "preserves_thinking", "emit_clear_thinking",
              "setup"):
        ok(k in doc, f"the file carries goose's own field `{k}` — we write the FULL "
                     "document its editor round-trips, so a user pressing Update in "
                     "goose's form does not silently lose fields")
    # S29 — the MLX fixture is a REAL directory now: model_entries enumerates through
    # the shared rule (core/modelreg.offerable), which drops a row whose artifact is
    # provably gone. A fixture naming a path that never existed would be asserting the
    # OLD behaviour — the one that kept goose's picker offering the models Debi deleted
    # in LM Studio days earlier.
    import tempfile as _tf
    _mlxdir = _tf.mkdtemp(prefix="gooseui-mlx-")
    open(os.path.join(_mlxdir, "config.json"), "w").write('{"model_type":"unit-test"}')
    _header = json.dumps({"weight": {"dtype": "F32", "shape": [1],
                          "data_offsets": [0, 4]}}, separators=(",", ":")).encode()
    open(os.path.join(_mlxdir, "model.safetensors"), "wb").write(
        len(_header).to_bytes(8, "little") + _header + b"\0\0\0\0")
    m = PR.model_entries([{"id": "g", "format": "gguf"},
                          {"id": "x", "format": "mlx", "path": _mlxdir},
                          {"id": "a", "kind": "audio"},
                          {"id": "h", "hidden": True},
                          {"id": "deleted-in-lmstudio", "format": "gguf",
                           "path": os.path.join(_mlxdir, "gone.gguf"),
                               "artifact_evidence": {"v": 1, "real_path": os.path.realpath(os.path.join(_mlxdir, "gone.gguf")),
                                                 "device": os.stat("/").st_dev, "mount_root": "/",
                                                 "manifest": {"kind": "gguf", "files": ["gone.gguf"]}}},
                          {"id": "flagged-absent", "format": "gguf", "absent": True},
                          {"id": "g", "format": "gguf"}])
    ok([e["name"] for e in m] == ["g", _mlxdir],
       "chat models only, WIRE identifiers (an MLX row is its path, because goose's "
       "model object has ONE identifier slot and a pretty label that 400s is a lie), "
       "audio/hidden excluded, duplicates collapsed — and S29: a row whose FILE is gone, "
       "or one carrying the persisted `absent` flag, is not offered either")
    ok(all(e["context_limit"] > 0 for e in m),
       "…and every row carries a context limit — goose's own form always writes one")


def test_never_clobber_matrix():
    """THE WALKED JOURNEY: rename the provider by hand in the fenced config, re-seed,
    the rename is still there. Plus the rest of the merge table."""
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        cd = G.config_dir(td)
        reg = [{"id": "m1"}, {"id": "m2"}]
        p, changed, err = PR.seed_provider(cd, "http://127.0.0.1:6767/v1", reg)
        ok(changed and not err, "first seed writes the file")
        ok(p == G.provider_path(td) == PR.provider_path(cd),
           "…at ONE path, agreed on by the lane module and the provider module")
        ok(PR.seed_provider(cd, "http://127.0.0.1:6767/v1", reg)[1] is False,
           "a second seed with nothing changed rewrites NOTHING (idempotent)")

        doc = _json.load(open(p))
        doc["display_name"] = "Debi's runner"
        doc["headers"] = {"X-Mine": "1"}
        doc["requires_auth"] = False
        doc["supports_streaming"] = False
        doc["some_future_goose_key"] = 42
        _json.dump(doc, open(p, "w"), indent=2)
        PR.seed_provider(cd, "http://127.0.0.1:6767/v1", reg + [{"id": "m3"}])
        after = _json.load(open(p))
        ok(after["display_name"] == "Debi's runner",
           "NEVER-CLOBBER: the hand-edited display name SURVIVES a re-seed")
        ok(after["headers"] == {"X-Mine": "1"}, "…so do the user's headers")
        ok(after["requires_auth"] is False and after["supports_streaming"] is False,
           "…and their auth/streaming choices")
        ok(after["some_future_goose_key"] == 42,
           "…and a key a FUTURE goose adds that we have never heard of")
        ok(len(after["models"]) == 3 and after["base_url"] == "http://127.0.0.1:6767",
           "while the keys we own — the model list and where it points — ARE refreshed, "
           "because a provider naming a dead endpoint is a lie, not a preference")
        ok(sorted(PR.OWNED_KEYS) == ["api_key_env", "base_url", "engine", "models"],
           "…and the owned set is exactly those four, stated rather than implied")

        # A corrupt file is treated as absent, never as a reason to refuse.
        open(p, "w").write("{not json")
        PR.seed_provider(cd, "http://127.0.0.1:6767/v1", reg)
        ok(_json.load(open(p))["name"] == PR.PROVIDER_NAME,
           "an unreadable provider file is REPLACED rather than left broken — the lane "
           "lands on something usable")


def test_the_main_model_setting_is_seeded_not_enforced():
    """⚠️ THE PRE-EXISTING OVERRIDE THIS SLICE FIXES. Measured on the pinned binary:
    env GOOSE_PROVIDER BEATS config active_provider. So the old unconditional
    `GOOSE_PROVIDER=openai` silently undid, at every spawn, a provider the user had
    chosen in goose's own UI — right after the UI said "Successfully switched models"."""
    ok(PR.provider_choice("") == (PR.PROVIDER_NAME, True),
       "a fresh config: seed ours (there is nothing of theirs to preserve)")
    ok(PR.provider_choice("active_provider: openai\n") == (PR.PROVIDER_NAME, True),
       "`openai` is OUR OWN older anonymous seeding — migrating it is the deliberate "
       "one-time change (same endpoint, same key, same wire model, better label)")
    ok(PR.provider_choice(f"active_provider: {PR.PROVIDER_NAME}\n")
       == (PR.PROVIDER_NAME, True), "already ours: unchanged")
    for theirs in ("anthropic", "custom_something_else", "'ollama'", '"xai"'):
        ok(PR.provider_choice(f"active_provider: {theirs}\n") == ("", False),
           f"{theirs} is the USER'S choice — we set NEITHER env var and touch nothing")
    env = G.serve_env({}, "/r", "tok", "", "k", "wire",
                      config_text="active_provider: anthropic\n")
    ok("GOOSE_PROVIDER" not in env and "GOOSE_MODEL" not in env,
       "…proven on the real env builder: neither key is set when the choice is theirs "
       "(the MODEL travels with the provider — forcing it onto somebody else's provider "
       "is the same override wearing a different name)")
    ok(G.serve_env({"GOOSE_PROVIDER": "sneaky"}, "/r", "t", "", "k", "w",
                   config_text="active_provider: anthropic\n").get("GOOSE_PROVIDER")
       is None,
       "…and an INHERITED GOOSE_PROVIDER is stripped too, or the operator's shell would "
       "do the overriding we just stopped doing")
    env2 = G.serve_env({}, "/r", "tok", "", "k", "wire")
    ok(env2["GOOSE_PROVIDER"] == PR.PROVIDER_NAME and env2["GOOSE_MODEL"] == "wire",
       "with no choice of theirs, ours is set — the lane still arrives pre-configured")
    ok(env2["OPENAI_HOST"] and env2["OPENAI_API_KEY"] and env2["OPENAI_BASE_PATH"],
       "and the STOCK openai wiring stays beside it, so a session recorded before this "
       "slice (provider_name: openai) still resolves at replay time")


def test_a_provider_with_no_models_is_still_a_working_provider():
    """ADVERSARIAL, walked on the real binary: a MOT Deck with nothing in the registry
    yet (first boot, no models downloaded). We write `models: []`.

    ⚠️ AND GOOSE DOES NOT DELETE IT — measured: `goose run` under a provider whose file
    lists NO models resolved it and answered. That is the opposite of OpenCode, where an
    empty models map makes the provider VANISH from Settings and the picker
    (provider.ts:1686), which is why the OpenCode seeder ships a placeholder row. Copying
    that workaround here would have been cargo cult; the measurement says it is not
    needed, and this test is what would tell us if that ever changed."""
    ok(PR.model_entries([]) == [], "an empty registry yields an empty model list")
    doc = PR.provider_doc("http://127.0.0.1:6767", PR.model_entries([]))
    ok(doc["models"] == [] and doc["name"] == PR.PROVIDER_NAME,
       "…and the provider is still a complete, nameable document, so the tab shows a "
       "row that explains itself rather than nothing at all")


def test_the_pidfile_is_consulted_before_it_is_cleared():
    """⚠️ A5 — WALKED, NOT IMAGINED. The bridge restarted between /start and /stop; the
    new process had no Popen handle, _stop_locked cleared the pidfile and answered
    "gone", and a LIVE fenced goosed of ours kept its port and its sqlite session store
    with its only cross-restart handle deleted. Two of ours were then listening at once —
    the two-writers-on-one-DB story _reap_orphan exists to prevent.

    The pidfile IS the cross-restart handle, so the no-handle branch must consult it
    (through the identity-verified reaper) BEFORE anything erases it."""
    import ast
    src = (ROOT / "bridge" / "routers" / "gooseui.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_stop_locked")
    seg = ast.get_source_segment(src, fn) or ""
    head = seg.split("_clear_pidfile(")[0]
    ok("_reap_orphan()" in head,
       "A5: the no-handle path reaps through the pidfile BEFORE the pidfile is cleared")
    ok(seg.index("_reap_orphan()") < seg.index("_clear_pidfile("),
       "…in that order, which is the whole fix")
    ok('"reaped"' in seg,
       "…and the caller is TOLD a process was terminated: answering \"gone\" while one "
       "was in fact reaped is a small lie in the family this project ranks worst")
    import inspect
    from bridge.routers import gooseui as R
    # `from __future__ import annotations` keeps annotations as strings — compare text.
    ok(str(inspect.signature(R._reap_orphan).return_annotation) in ("bool", "<class 'bool'>"),
       "the reaper reports whether it signalled, rather than leaving the caller to guess")


def test_both_lanes_seed_their_OWN_config_layout():
    """⚠️ TWO FENCES, TWO LAYOUTS. The embed is GOOSE_PATH_ROOT-fenced
    (<ui-home>/goose/config) and the CLI is XDG-fenced (<home>/.config/goose). Both were
    walked live with a real provider file and a real `goose run` turn before the seeder
    was written; assuming one layout for both is how a lane silently gets no provider."""
    ui, cli = G.config_dir("/r"), P.config_dir("/r")
    ok(ui.endswith(os.path.join("goose", "ui-home", "goose", "config")),
       "the embed lane's config dir is the GOOSE_PATH_ROOT one")
    ok(cli.endswith(os.path.join("goose", "home", ".config", "goose")),
       "the CLI lane's is the XDG one")
    ok(ui != cli and PR.provider_path(ui) != PR.provider_path(cli),
       "…so the two provider files are two files: one runner, two fenced homes, no "
       "shared state (the whole no-collision guarantee of this lane)")
    for d in (ui, cli):
        ok(PR.providers_dir(d).endswith("custom_providers"),
           "…each under goose's own custom_providers/ directory (ONE JSON PER PROVIDER — "
           "never a custom_providers: key inside config.yaml, which is one of the three "
           "layouts v1.5.40 guessed and got 'Unknown provider' for)")


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


# ── v1.5.64: the per-chat delete the SIDEBAR never had ──────────────────────
def _fake(results, err):
    """An awaitable stand-in for gooseui.acp_calls."""
    async def _run():
        return results, err
    return _run()


def test_the_sidebar_delete_speaks_gooses_own_protocol():
    """Debi asked twice for a per-chat delete in the CHATS list. Upstream has none there
    (the row component renders a name and status dots; deletion lives on the Session
    History page behind a hover-revealed trash). The ✕ we inject calls this bridge, and
    the bridge sends goose's OWN ACP `session/delete` to the goosed we supervise."""
    for good in ("20260829_1", "20260829_42", "19991231_9"):
        ok(G.valid_session_id(good), f"{good} is goose's own id shape")
    for bad in ("", None, "nope", "../../etc/passwd", "20260829_1; rm -rf /",
                " 20260829_1 x", "2026089_1"):
        ok(not G.valid_session_id(bad),
           f"{bad!r} never reaches a protocol call — the id crosses a process boundary")
    ok(G._session_titles({"sessions": [{"sessionId": "20260829_1", "title": "hi"},
                                       {"sessionId": "", "title": "x"},
                                       "junk", {"nope": 1}]}) == {"20260829_1": "hi"},
       "a list result is read totally: a junk row costs THAT row, never the answer")
    ok(G._session_titles(None) == {} and G._session_titles({}) == {},
       "…and nothing at all is {}, not a crash")

    # The four honest answers, with the transport substituted (the LIVE walk against a
    # real goosed is in the report; this pins the decision table forever).
    import asyncio
    real = G.acp_calls
    try:
        G.acp_calls = lambda *_a, **_k: _fake([{"sessions": []}], "")
        okr, msg = asyncio.run(G.delete_session("ws://x", "o", "20260829_1"))
        ok(okr is False and "does not have that chat" in msg,
           "an id goose does not list is refused with a sentence, not attempted")

        G.acp_calls = lambda *_a, **_k: _fake([], "goose refused session/list")
        okr, msg = asyncio.run(G.delete_session("ws://x", "o", "20260829_1"))
        ok(okr is False and "refused" in msg, "goose's own words are passed through")

        state = {"n": 0}

        def still_there(*_a, **_k):
            state["n"] += 1
            rows = [{"sessionId": "20260829_1", "title": "keeper"}]
            if state["n"] == 1:
                return _fake([{"sessions": rows}], "")
            return _fake([{}, {"sessions": rows}], "")
        G.acp_calls = still_there
        okr, msg = asyncio.run(G.delete_session("ws://x", "o", "20260829_1"))
        ok(okr is False and "still in its list" in msg,
           "⚠️ `session/delete` answers an EMPTY {} (measured): a re-list is the receipt, "
           "and a chat still listed is reported as a FAILURE rather than a success")

        state2 = {"n": 0}

        def gone(*_a, **_k):
            state2["n"] += 1
            if state2["n"] == 1:
                return _fake([{"sessions": [{"sessionId": "20260829_1",
                                             "title": "the tax thing"}]}], "")
            return _fake([{}, {"sessions": []}], "")
        G.acp_calls = gone
        okr, msg = asyncio.run(G.delete_session("ws://x", "o", "20260829_1"))
        ok(okr is True and "the tax thing" in msg,
           "…and success names the chat, so the user knows WHICH one went")
    finally:
        G.acp_calls = real


def test_the_sidebar_delete_is_wired_and_fenced():
    ok("/api/gooseui/session/delete" in _APP_SOURCE,
       "the route exists in the app-layer source view")
    ok('"pin_bundle_sha256"' in _APP_SOURCE,
       "…and /api/gooseui/status publishes the sha the injected script fences on")
    swift = (ROOT / "app" / "main.swift").read_text()
    ok("gooseSidebarDeleteScript" in swift and 'if t.id == "gooseui"' in swift,
       "the user script is attached to the gooseui tab and nowhere else")
    ok("goosePin()" in swift and "goose_pin:" in swift,
       "FENCE 1: the pin is read from harness.yaml, and an unreadable pin means no "
       "injection at all")
    ok(r'goose_pin:\s*"?v?[0-9][0-9A-Za-z.\-]*"?' in swift,
       "…with the quotes OPTIONAL — ship.sh's pyyaml merge writes the snapshot's copy "
       "unquoted, and a quote-only regex would make the feature not exist on a fat "
       "install (the v1.5.59 lesson, pinned)")
    ok("j.bundle_sha256 !== j.pin_bundle_sha256" in swift,
       "FENCE 2: a bundle that is not the one whose DOM we measured gets nothing")
    ok("fiberSession" in swift and "p.session.id" in swift,
       "FENCE 3: the row's id comes from its OWN props — their DOM carries no session "
       "id anywhere, and matching on the text 'New Chat' would be indefensible")
    ok('wrap.addEventListener("click", function (ev) { ev.stopPropagation(); }, false)'
       in swift,
       "the row guard is BUBBLE phase: in capture it stopped the event before it "
       "reached our own buttons and the ✕ did nothing (caught on the live walk)")
    ok('class="ask"' in swift and "delete?" in swift and "armedRow" in swift,
       "one click never deletes: the ✕ arms a two-step, because their own confirm "
       "dialog cannot be raised from the sidebar")
    ok('CustomEvent("session-deleted"' in swift,
       "the list refresh is THEIR OWN event — we do not re-implement their list")
    ok("function showing(id)" in swift and "resumeSessionId=" in swift
       and "if (showing(id)) newChat();" in swift,
       "deleting the chat you are LOOKING AT lands on a new chat — walked live: without "
       "this the main pane kept rendering the transcript of a chat that no longer "
       "exists, which is a screen full of something that is gone")
    ok('String(b.className).indexOf("w-full") < 0' in swift,
       "…and the New Chat it presses is THEIR nav item, told apart from the titlebar "
       "chip of the same name by the class only the nav row carries")
    ok("hgdel-note" in swift and "Nothing was deleted — " in swift,
       "a refusal renders goose's sentence next to the row…")
    ok("d.title = raw" in swift and '"HTTP " + res.status' in swift,
       "…with the status code behind the hover, never as the message")


def main():
    for fn in (test_entry_document, test_route_shapes_are_registered,
               test_the_lane_is_REACHABLE,
               test_no_kill_by_port_or_pattern, test_the_two_lanes_cannot_collide,
               test_env_fence_survives_a_hostile_environment,
               test_endpoint_composition, test_config_seed_preserves_what_the_user_added,
               test_named_provider_file_matches_what_goose_itself_wrote,
               test_never_clobber_matrix,
               test_the_main_model_setting_is_seeded_not_enforced,
               test_a_provider_with_no_models_is_still_a_working_provider,
               test_the_pidfile_is_consulted_before_it_is_cleared,
               test_both_lanes_seed_their_OWN_config_layout,
               test_acp_url_and_argv, test_bundle_containment,
               test_media_types_are_forced,
               test_absent_dependency_lands_on_something_usable,
               test_the_shim_is_complete_and_honest,
               test_the_sidebar_delete_speaks_gooses_own_protocol,
               test_the_sidebar_delete_is_wired_and_fenced):
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"goose UI lane: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
