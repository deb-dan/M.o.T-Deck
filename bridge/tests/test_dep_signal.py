"""THE DEPENDENCY SIGNAL (S22) — the derivation, EXECUTED, and its shell renderer.

docs/research/2026-08-29-isolation-mode.md §6 found that "restart rebinds" is already
true everywhere and that the missing half is the SIGNAL. This suite is the gate on that
signal, and it is journey-shaped rather than function-shaped (doctrine §6): every case
below is a state a real user's machine actually reaches.

What each group guards:

1. THE HEALTHY STATE IS SILENT. The single most important property: with everything up
   and correctly bound, the derivation returns NOTHING. A banner that is always on
   screen is not a signal, it is furniture, and the user stops reading it.
2. THE FOUR UNMET STATES, each with the ONE action that actually fixes it — including
   `swapped`, which is the LIE this whole slice exists to catch: Hermes still wired to
   a model the runner stopped serving, so its dashboard is healthy and every new chat
   fails. (Measured live on Debi's Mac 2026-08-29: config said Qwen3.6-27B…, the runner
   was serving gemma-4-31B… — the first run of this code found it.)
3. THE TWO SILENCE GATES — a component that is not running says nothing (its tab already
   shows "Not reachable yet"), and a dependency that was never INSTALLED says nothing
   (Debi's partial-install principle, ledger S23).
4. THE COPY. Every sentence names the component, the dependency and the fix, in the
   user's words (the tab titles), and every action is one the bridge actually serves.
5. THE WIRING — the route exists, the restart route it points at exists and is a
   COMPOSITION of the audited stop/start, and the Swift shell renders it.

Run: python3 bridge/tests/test_dep_signal.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge.routers.components import (                         # noqa: E402
    NEEDS_SOFT, needs_derive, needs_message, start_failure_reason)
from bridge.core.health import (                                # noqa: E402
    MODEL_FILE_MISS_GONE, file_state_forget, file_state_track, path_present)

SWIFT = (ROOT / "app" / "main.swift").read_text()

FAILS = []
CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("FAIL " + label)


# The dependency graph as harness.yaml actually declares it (read once, so a future
# edit to the manifest is caught here rather than in production).
import yaml                                                     # noqa: E402
_CFG = yaml.safe_load((ROOT / "harness.yaml").read_text())
HARD = {n: (c.get("depends_on") or []) for n, c in (_CFG.get("components") or {}).items()}


def up(**kw):
    d = {"installed": True, "running": True}
    d.update(kw)
    return d


def healthy():
    """Everything installed, running, runner loaded — the ordinary Tuesday."""
    return {
        "runner": up(port_up=True, loaded=True),
        "hermes": up(), "odysseus": up(), "searxng": up(), "opencode": up(),
        # S34: the DeepSeek lane. Added to the FIXTURE as well as to the loop below,
        # because a component missing from `healthy()` is a component every state test
        # in this file skips in silence.
        "deepseek": up(),
    }


def bound(model="m1", live="m1", ep="http://127.0.0.1:6767/v1",
          live_ep="http://127.0.0.1:6767/v1"):
    return {"hermes": {"model": model, "live_model": live,
                       "endpoint": ep, "live_endpoint": live_ep}}


def derive(comps, bindings=None):
    return needs_derive(comps, HARD, NEEDS_SOFT, bindings or {})


# ── 1. the healthy state is SILENT ───────────────────────────────────────────
def test_silent_when_well():
    ok(derive(healthy(), bound()) == {},
       "everything up and correctly bound derives NO needs at all")
    # …and with no binding readable either: an unreadable config is "no claim",
    # never a claim of trouble. (A Hermes that has never been started has no
    # model.default at all — that must not paint a banner.)
    ok(derive(healthy(), {}) == {}, "an unreadable binding derives nothing")
    ok(derive(healthy(), {"hermes": {"model": None, "live_model": "m1"}}) == {},
       "a half-known binding derives nothing")


# ── 2. the four unmet states ─────────────────────────────────────────────────
def test_runner_down():
    c = healthy()
    c["runner"] = {"installed": True, "running": False, "port_up": False, "loaded": False}
    out = derive(c, bound())
    # ⚠️ A HARDCODED TUPLE, NOT `NEEDS_SOFT.keys()`, AND THAT IS THE POINT: this list
    # is the fence, so a new soft-dep component is NOT covered until somebody adds it
    # here on purpose. `deepseek` joined at S34 (2026-09-03).
    for who in ("hermes", "odysseus", "opencode", "deepseek"):
        ok(who in out, f"{who} signals when the runner is down")
        n = out[who]["needs"][0]
        ok(n["state"] == "down" and n["action"] == "start" and n["target"] == "runner",
           f"{who}'s offered action is to START the runner")
    # OpenCode is here BY THE SOFT TABLE, and that matters: harness.yaml deliberately
    # gives it depends_on: [] so a Start never drags the runner up. The signal and the
    # start closure are allowed to disagree; only this table may make them.
    ok(HARD.get("opencode") == [], "harness.yaml still declares opencode depends_on: []")
    ok("opencode" in NEEDS_SOFT, "…and the SOFT table is what puts it in the signal")
    # …and the DeepSeek lane, on exactly the same two terms.
    ok(HARD.get("deepseek") == [], "harness.yaml still declares deepseek depends_on: []")
    ok("deepseek" in NEEDS_SOFT, "…and the SOFT table is what puts IT in the signal too")
    # THE SENTENCE ITSELF, in her words rather than ours: the banner must lead with the
    # tab title the strip shows, never the internal id.
    m = needs_message("deepseek", "runner", "down", {})
    ok(m["text"].startswith("DeepSeek"), "the sentence leads with the tab name")
    ok("the Runner" in m["text"], "…and names the dependency in her words")
    ok("deepseek" not in m["text"], "…and never leaks the internal id")


def test_runner_has_no_model():
    c = healthy()
    c["runner"] = up(port_up=True, loaded=False)
    out = derive(c, bound())
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "no-model", "a live port with nothing loaded is 'no-model', not 'down'")
    ok(n["action"] == "open" and n["target"] == "mc",
       "…and it sends the user to MOT Deck to load one (there is nothing to START)")
    ok("nothing is loaded" in n["text"], "…and the sentence says why")


def test_swapped_is_the_lie_this_catches():
    out = derive(healthy(), bound(model="qwen-x", live="gemma-y"))
    ok("hermes" in out, "a stale model binding IS a need")
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "swapped", "…reported as 'swapped'")
    ok(n["action"] == "restart" and n["target"] == "hermes",
       "…and the fix is restarting HERMES (the Start re-patches its config)")
    ok("qwen-x" in n["text"] and "gemma-y" in n["text"],
       "…and the sentence names BOTH models, so the user can check it themselves")
    # The precision that makes it safe to show: identical ids never fire.
    ok(derive(healthy(), bound(model="same", live="same")) == {},
       "an identical binding is silent (no false 'swapped')")


def test_moved_endpoint():
    out = derive(healthy(), bound(ep="http://127.0.0.1:6767/v1",
                                  live_ep="http://127.0.0.1:6868/v1"))
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "moved" and n["action"] == "restart",
       "a runner that moved ports is 'moved', fixed by a restart")
    ok(derive(healthy(), bound(ep="http://127.0.0.1:6767/v1/",
                               live_ep="http://127.0.0.1:6767/v1")) == {},
       "a trailing slash is not a moved endpoint")


def test_a_dep_that_is_not_the_runner():
    c = healthy()
    c["searxng"] = {"installed": True, "running": False}
    out = derive(c, bound())
    ok("odysseus" in out, "odysseus signals when SearXNG (its other dep) is down")
    n = out["odysseus"]["needs"][0]
    ok(n["dep"] == "searxng" and n["action"] == "start" and n["target"] == "searxng",
       "…and offers to start SearXNG")
    ok("hermes" not in out, "…and Hermes, which does not depend on it, stays silent")


# ── 3. the two silence gates ─────────────────────────────────────────────────
def test_a_stopped_component_says_nothing():
    c = healthy()
    c["runner"] = {"installed": True, "running": False, "port_up": False, "loaded": False}
    c["hermes"] = {"installed": True, "running": False}
    out = derive(c, bound())
    ok("hermes" not in out,
       "a component that is not running gets no banner (its tab already says so)")
    ok("odysseus" in out, "…while the ones that ARE running still speak")


def test_an_uninstalled_dep_says_nothing():
    c = healthy()
    c["searxng"] = {"installed": False, "running": False}
    out = derive(c, bound())
    ok("odysseus" not in out,
       "a dependency the user never installed is not nagged about (S23)")


def test_a_dep_this_build_does_not_know():
    out = needs_derive(healthy(), {"hermes": ["atlantis"]}, {}, {})
    ok(out == {}, "an unknown dependency name is skipped, never crashed on")


# ── 4. the copy ──────────────────────────────────────────────────────────────
def test_every_sentence_is_written_for_her():
    seen = []
    for state in ("down", "no-model", "swapped", "moved", "wat"):
        m = needs_message("hermes", "runner", state,
                          {"bound": "a", "live": "b"})
        seen.append(m)
        ok(m["text"].startswith("Hermes"), f"[{state}] the sentence leads with the tab name")
        ok("the Runner" in m["text"], f"[{state}] …and names the dependency in her words")
        ok(m["action"] in ("start", "restart", "open"),
           f"[{state}] …and offers an action the shell knows")
        ok(m["action_label"] and len(m["action_label"]) < 24,
           f"[{state}] …with a button label that fits a thin banner")
    ok(all("hermes\"" not in m["text"] and "gooseui" not in m["text"] for m in seen),
       "no internal id ever reaches the user's sentence")
    ok("Goose UI" == __import__("bridge.routers.components", fromlist=["x"])
       ._needs_title("gooseui"),
       "…and the title table spells the lanes the way the tab strip does")


# ── 5. the wiring ────────────────────────────────────────────────────────────
def test_routes_exist():
    ok('@app.get("/api/deps")' in _APP_SOURCE, "GET /api/deps is served")
    ok('@app.post("/api/components/{name}/restart")' in _APP_SOURCE,
       "POST /api/components/{name}/restart is served")
    # The restart route must stay a COMPOSITION of the audited stop/start rather than
    # grow its own kill logic — that is the whole safety argument for shipping it.
    body = _APP_SOURCE.split('@app.post("/api/components/{name}/restart")')[1]
    body = body.split("@app.post")[0]
    ok("r = stop(name)" in body and "start(name)" in body,
       "restart composes stop() and start()")
    ok("pkill" not in body and "os.kill" not in body and "_kill_port_listener" not in body,
       "…and contains NO kill logic of its own")
    ok("r.status_code != 200" in body,
       "…and a refused stop (409) does NOT go on to start a second process")


def test_the_shell_renders_it():
    ok("api/deps" in SWIFT, "the shell fetches /api/deps")
    ok("DepsBanner" in SWIFT, "…and has a banner view for it")
    # ADVISORY: the banner must SHORTEN the page, never cover it, and never gate it.
    ok("depsBannerHeight" in SWIFT, "…whose height is a named constant")
    ok('appendingPathComponent("api/components")' in SWIFT
       and 'req.httpMethod = "POST"' in SWIFT,
       "…and its button POSTs to the component lifecycle routes")
    ok('need.action == "restart" ? "restart" : "start"' in SWIFT,
       "…choosing the verb the BRIDGE named, never one of its own")
    # The one thing a future edit must not do: make the banner a modal/blocker.
    for banned in ("NSAlert", "beginSheetModal", "runModal"):
        ok(banned not in SWIFT.split("DepsBanner")[1][:6000],
           f"the banner never becomes a {banned} (it is advisory, always)")


# ══ 6. U15 — RUNNER STATUS HONESTY ═══════════════════════════════════════════
#
# THE INCIDENT (Debi, live, 2026-08-29): she deleted the resident 27B's weights in LM
# Studio. MOT Deck stayed GREEN for a long time; the runner then stopped and the FAILED
# card still printed the model's name as if it existed; and FIVE Retry clicks failed
# with the only honest sentence ("model … not in registry", which the start script also
# emits when the FILE at a registered path is gone) visible only in a subprocess's
# stderr. Three lies at once, the worst class.
#
# A fourth arrived the same day and shares the root: the start script's readiness poll
# sends no Authorization header, so on llama.cpp b10662+ it 401s for its whole budget
# and reports failure for a runner that came up in a second (ledger U16). Everything
# below is the app refusing to repeat a claim it can check for itself.

def test_a_dead_model_file_never_offers_a_dead_button():
    c = healthy()
    c["runner"] = {"installed": True, "running": False, "port_up": False,
                   "loaded": False, "model_file": "gone",
                   "model_path": "/Users/d/.lmstudio/models/x/y.gguf",
                   "pin_intent": "the-27b"}
    out = derive(c, bound())
    n = out["hermes"]["needs"][0]
    ok(n["state"] == "model-gone",
       "a runner that is down BECAUSE its model file is gone says so")
    ok(n["action"] != "start",
       "…and never offers Start — that is the button she pressed five times")
    ok("/Users/d/.lmstudio/models/x/y.gguf" in n["text"],
       "…and the sentence names the path, so she can check it herself")
    ok("pick another model" in n["text"], "…and names the fix")
    # The registry-row-missing variant is a DIFFERENT fix (rescan), so a different
    # sentence. Saying "not in your registry" about a deleted file sends her to the
    # wrong place, and saying "file missing" about a pruned row names a path we do
    # not have.
    c["runner"]["model_file"] = "unregistered"
    n2 = derive(c, bound())["hermes"]["needs"][0]
    ok(n2["state"] == "model-unregistered" and "registry" in n2["text"],
       "a pruned registry row gets its own sentence and its own fix")
    ok("the-27b" in n2["text"], "…which names the model that vanished")


def test_a_runner_that_is_merely_down_is_unchanged():
    # THE REGRESSION GUARD. The overwhelmingly common case — a runner that is simply
    # not started — must keep its old sentence and its old Start button. A new state
    # that swallowed the ordinary one would be a worse bug than the one it fixed.
    c = healthy()
    for mf in (None, "ok", "checking", "unknown"):
        c["runner"] = {"installed": True, "running": False, "port_up": False,
                       "loaded": False, "model_file": mf}
        n = derive(c, bound())["hermes"]["needs"][0]
        ok(n["state"] == "down" and n["action"] == "start",
           f"[model_file={mf}] a plain stopped runner still offers Start")
    ok(True, "…including 'checking', which is the FIRST missed stat (see the debounce)")


def test_two_strikes_before_we_accuse_a_disk():
    """THE ADVERSARIAL FINDING, PINNED. os.stat() on a sleeping network mount or a
    spun-down external disk answers ENOENT rather than raising, so ONE sample is not
    evidence. Telling Debi her model file is gone when it is merely slow is the same
    class of lie this slice removes, one direction over."""
    file_state_forget()
    p = "/definitely/not/here/model.gguf"
    first = file_state_track("t", p)
    ok(first["state"] == "checking" and first["misses"] == 1,
       "one missed stat is 'checking' — a state that renders as NOTHING")
    second = file_state_track("t", p)
    ok(second["state"] == "gone" and second["misses"] == 2,
       "the SECOND consecutive miss is what earns the claim")
    ok(MODEL_FILE_MISS_GONE == 2, "…and the threshold is a named constant")
    # A single good sample forgets the whole streak: a mount that comes back must not
    # stay accused, and a file that blips twice a day must never accumulate.
    ok(file_state_track("t", str(ROOT / "harness.yaml"))["state"] == "ok",
       "a file that IS there reads ok")
    file_state_forget("t")
    ok(file_state_track("t", p)["state"] == "checking",
       "…and the next miss starts the streak over from one")
    # A path CHANGE (a re-pin, or a rescan that rewrote the entry) also resets: the
    # misses belonged to the old path and say nothing about the new one.
    file_state_track("t", p)
    ok(file_state_track("t", "/some/other/path.gguf")["state"] == "checking",
       "a streak never transfers from one path to another")
    file_state_forget()


def test_we_never_claim_what_the_os_would_not_tell_us():
    ok(path_present("") is None, "no path at all is 'unknown', never 'missing'")
    ok(path_present(None) is None, "…and so is a null path")
    ok(path_present(str(ROOT / "harness.yaml")) is True, "a real file reads present")
    ok(path_present(str(ROOT)) is False,
       "a DIRECTORY where a gguf should be is not a present gguf")
    ok(path_present(str(ROOT), fmt="mlx") is True,
       "…while an mlx entry wants exactly that directory (start_component.sh's rule)")
    ok(file_state_track("u", "")["state"] == "unknown",
       "an unknown never becomes an accusation, however many times it is sampled")
    ok(file_state_track("u", "")["state"] == "unknown", "…twice")
    file_state_forget()


def test_the_failure_sentence_is_a_sentence():
    """FIX 1. The reason lived in a subprocess's stderr; what reached the screen was
    either nothing or a raw llama.cpp log line. Both are the same defect."""
    reg_err = ("ERROR: model 'Q27B' not in registry — run scripts/seed_registry.py "
               "or pick another model")
    gone = start_failure_reason(reg_err, model="Q27B", path="/m/q.gguf",
                                file_state="gone")
    ok(gone["text"] == "model file missing at /m/q.gguf — pick another model",
       "a registered model whose FILE is gone says exactly that, with the path")
    ok(gone["action_label"] == "Open Models",
       "…and offers the place where a different model can be picked")
    pruned = start_failure_reason(reg_err, model="Q27B")
    ok("not in your model registry" in pruned["text"],
       "the SAME stderr means something different when we have no path — and says so")
    ok(pruned["text"] != gone["text"],
       "…so one script sentence cannot flatten two different fixes into one")
    unknown = start_failure_reason(reg_err, model="Q27B", path="/m/q.gguf",
                                   file_state="unknown")
    ok("could not read" in unknown["text"],
       "an unreadable path is reported as unreadable, never as deleted")
    nomodel = start_failure_reason("ERROR: runner.model not set in harness.yaml")
    ok("no model is pinned" in nomodel["text"], "the un-pinned case has its own line")
    # TOTALITY: whatever the script says, the card gets a non-empty sentence, and it is
    # never the raw multi-line vomit.
    for junk in ("", "   ", "\n\n", "boom", "ERROR: something we never anticipated",
                 "2.49.854.040 W srv    operator(): unauthorized: Invalid API Key"):
        r = start_failure_reason(junk)
        ok(bool(r["text"]) and "\n" not in r["text"],
           f"[{junk[:24]!r}] always ONE readable line, never a log dump")
        ok(r["detail"] == junk.strip()[-1500:],
           f"[{junk[:24]!r}] …with the raw text still carried for View log")


def test_the_bridge_stops_repeating_an_exit_code_it_can_check():
    """FIX 1b / the sticky-Failed half of the incident: `ps` and an authenticated curl
    both showed the runner serving Parable-Qwen3-4B while the card said Failed."""
    src = _APP_SOURCE
    ok("def runner_serving(" in src,
       "the bridge has an AUTHENTICATED way to ask what the runner is serving")
    prov = src[src.index("def _provision(", src.index("appsrc: bridge/routers/component_lifecycle.py")):]
    ok("served = runner_serving(c)" in prov,
       "…and _provision asks it before believing a non-zero exit for the runner")
    ok("served and want and served == want" in prov,
       "…and only believes it when the runner serves the model that was PINNED — "
       "'something is up' is not the claim a Start makes")
    ok("rc_code, output = 0, \"\"" in prov,
       "…and treats a serving runner as the success it observably is")
    ok("except subprocess.TimeoutExpired" in prov,
       "a start that HANGS is recorded as a failure, not left frozen on Starting…")
    st = src[src.index("async def status() -> dict:"):]
    st = st[:st.index("# ══ THE DEPENDENCY SIGNAL")]
    ok('out["prov"].pop(n, None)' in st and 'row.get("running")' in st,
       "a `failed` overlay is dropped the moment the component is observably running")
    ok('row["last_error"]["stale"] = True' in st,
       "…and nothing is lost: the sentence survives, marked stale")


def test_the_card_can_tell_intent_from_fact():
    """FIX 2 + FIX 3, on the wire. The panel cannot write "pinned X" instead of
    "serving X" unless /api/status hands it both."""
    src = _APP_SOURCE
    st = src[src.index('out["components"]["runner"] = {'):]
    st = st[:st.index("try:")]
    for key in ('"pin_intent"', '"live_id"', '"model_path"', '"model_file"',
                '"model_note"', '"last_error"'):
        ok(key in st, f"the runner row publishes {key}")
    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    ok("c.loaded ? 'serving' : 'pinned'" in panel,
       "the card labels the name as an INTENT whenever nothing is loaded")
    ok("Online — model file gone" in panel,
       "…and has a state for 'up, serving a file that no longer exists'")
    ok('class="why"' in panel, "…and a place on the card for the reason")
    ok("showView('models')" in panel and "Open Models" in panel,
       "…and an Open Models action wherever the reason points at the library")
    ok("rescanFromCard" in panel and "rescanModels" in panel,
       "…and reuses the Models pane's EXISTING rescan rather than a second one")
    ok("m.file === 'gone'" in panel and "file missing" in panel,
       "the Models rows carry a 'file missing' chip on the bridge's debounced verdict")
    ok("m.file === 'checking'" not in panel,
       "…and deliberately draw NOTHING for 'checking' (the un-earned claim)")


# ══ §7 THE COHERENCE WAVE (S28) ═════════════════════════════════════════════
#
# The post-switch coherence audit (docs/research/2026-08-29-post-switch-audit.md) is
# the fixture for this whole section: the runner served Parable-Qwen3-4B while
# Odysseus's default, the Goose UI chip, OpenCode's catalog and our own Chat lane's
# turn labels all named a 27B whose weights were deleted — and /api/deps answered
# {"components":{}}. Every test below is one of those surfaces, as a user story.

def test_the_three_missing_bindings_can_be_read_from_a_file():
    """§2 of the audit: the S24 note ('Odysseus's binding lives behind its admin API')
    was STALE — all three are ordinary files. Each reader is exercised against a real
    temp tree, because 'we could read it' was the claim that went untested."""
    import json as _json
    import tempfile
    from bridge.routers import components as C
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "vendor" / "odysseus" / "data").mkdir(parents=True)
        (root / "vendor" / "odysseus" / "data" / "settings.json").write_text(_json.dumps(
            {"default_endpoint_id": "local-jan", "default_model": "ghost-27B"}))
        gdir = root / "data" / "goose" / "ui-home" / "goose" / "config"
        gdir.mkdir(parents=True)
        (gdir / "config.yaml").write_text(
            "providers:\n  custom_mot_deck__local:\n    enabled: true\n"
            "    model: ghost-27B\n    configured: true\n"
            "active_provider: custom_mot_deck__local\n")
        odir = root / "data" / "opencode" / "xdg" / "config" / "opencode"
        odir.mkdir(parents=True)
        (odir / "opencode.json").write_text(_json.dumps({"model": "llama.cpp/ghost-27B"}))
        # S29 — `_dangling_only` asks the SHARED enumerator what we offer, and that
        # answer now excludes rows whose file is gone. So this fixture must supply a
        # registry with a REAL artifact: reading it off the dev tree (whose models.json
        # long outlived its weights) made the test depend on one machine's disk, which
        # is exactly how it went red here. An empty `offered` is deliberately NOT
        # information — dangles() repairs nothing then — so the fixture has to mean
        # something for the readers below to have anything to say.
        live_art = root / "live-4B.gguf"
        live_art.write_bytes(b"")
        other_art = root / "another-9B.gguf"
        other_art.write_bytes(b"")
        old_reg = C._registry_models
        old = C.ROOT
        try:
            C.ROOT = root
            C._registry_models = lambda: [
                {"id": "live-4B", "format": "gguf", "path": str(live_art)},
                {"id": "another-9B", "format": "gguf", "path": str(other_art)}]
            ody, goo, opc = (C._ody_binding("live-4B"), C._goose_binding("live-4B"),
                             C._opencode_binding("live-4B"))
            ok(ody.get("model") == "ghost-27B", "Odysseus's default_model is readable")
            ok(goo.get("model") == "ghost-27B", "the Goose UI chip's binding is readable")
            ok(opc.get("model") == "ghost-27B",
               "OpenCode's default is readable, with OUR provider prefix stripped")
            for name, b in (("odysseus", ody), ("gooseui", goo), ("opencode", opc)):
                ok(b.get("live_model") == "live-4B", f"{name} carries the live id too")
            # …and each of the three DECLINES to claim anything when the app is wired
            # somewhere that is not us. A sentence about somebody else's endpoint is a
            # sentence about nothing.
            (root / "vendor" / "odysseus" / "data" / "settings.json").write_text(
                _json.dumps({"default_endpoint_id": "someone-else",
                             "default_model": "theirs"}))
            (gdir / "config.yaml").write_text(
                "providers:\n  anthropic:\n    model: claude\nactive_provider: anthropic\n")
            (odir / "opencode.json").write_text(_json.dumps({"model": "openai/gpt-x"}))
            ok(C._ody_binding("live-4B") == {},
               "Odysseus pointed at another endpoint makes NO claim")
            ok(C._goose_binding("live-4B") == {},
               "goose on somebody else's provider makes NO claim")
            ok(C._opencode_binding("live-4B") == {},
               "OpenCode on another provider makes NO claim")
            # …and NO CLAIM about a default the seeder has decided to HONOUR: the
            # banner's only action is "Restart Odysseus", the restart re-runs the
            # seeder, and the seeder honours it again — a button that provably cannot
            # work is the S20 dead-button defect (found in the S28 live walk).
            (root / "vendor" / "odysseus" / "data" / "settings.json").write_text(
                _json.dumps({"default_endpoint_id": "local-jan",
                             "default_model": "hers-27B"}))
            (root / "data").mkdir(exist_ok=True)
            (root / "data" / "ody_seed_state.json").write_text(
                _json.dumps({"local-jan": {"default_model_honoured": "hers-27B"}}))
            ok(C._ody_binding("live-4B") == {},
               "a default the seeder HONOURS derives no sentence (no dead button)")
            (root / "data" / "ody_seed_state.json").write_text(
                _json.dumps({"local-jan": {"default_model_honoured": "something-else"}}))
            ok(C._ody_binding("live-4B").get("model") == "hers-27B",
               "…but a value that is NOT the honoured one is still reported")
            # ⚠️ THE INVARIANT: a `swapped` sentence is only ever derived when the
            # component's OWN Restart could clear it. goose and OpenCode both HONOUR a
            # stale-but-valid pick at Start, so reporting one would paint a permanent
            # banner over a button that provably does nothing (S20). Only a DANGLING
            # value — which their rebind does repair — may be reported.
            _real = [m.get("id") for m in C._registry_models()
                     if isinstance(m, dict) and m.get("id")
                     and m.get("kind") != "audio" and not m.get("hidden")]
            if len(_real) >= 2:
                _valid, _live2 = _real[0], _real[1]
                (gdir / "config.yaml").write_text(
                    "providers:\n  custom_mot_deck__local:\n    model: " + _valid
                    + "\nactive_provider: custom_mot_deck__local\n")
                (odir / "opencode.json").write_text(
                    _json.dumps({"model": "llama.cpp/" + _valid}))
                ok(C._goose_binding(_live2) == {},
                   "a stale-but-VALID goose pick derives nothing (Restart honours it)")
                ok(C._opencode_binding(_live2) == {},
                   "…and the same for OpenCode's default")
            # …and an absent file is silence, never an accusation.
            C.ROOT = root / "nope"
            ok(C._ody_binding("x") == {} and C._goose_binding("x") == {}
               and C._opencode_binding("x") == {},
               "an unreadable file is NO CLAIM, not a problem")
        finally:
            C.ROOT = old
            C._registry_models = old_reg


def test_two_strikes_before_we_accuse_an_app():
    """The health.py discipline, moved onto files. Every one of these files is
    REWRITTEN by a seeder during a Start — exactly when a poll is most likely to land —
    so one stale read may be a torn write."""
    from bridge.routers.components import bind_confirmed
    s1, say1 = bind_confirmed(None, "old", "new")
    ok(not say1, "one mismatched read is not yet an accusation")
    s2, say2 = bind_confirmed(s1, "old", "new")
    ok(say2, "…the SECOND consecutive one is")
    s3, _ = bind_confirmed(s2, "new", "new")
    ok(s3 is None, "agreement forgets the streak instantly")
    # A binding that CHANGES between polls is a component mid-restart, not a stale
    # binding: its streak starts over rather than inheriting the previous one's.
    _s, say = bind_confirmed(s2, "other", "new")
    ok(not say, "a DIFFERENT mismatch starts its own streak")
    ok(bind_confirmed(None, "", "new")[1] is False
       and bind_confirmed(None, "old", "")[1] is False,
       "we never accuse when either half is unreadable")


def test_the_goose_ui_gets_a_sentence_with_a_working_button():
    """S28b warned that deriving a need for a bridge-supervised child would render a
    button with nothing behind it. Both halves are checked here."""
    from bridge.routers.components import NEEDS_SOFT, _LANE_RESTART, needs_derive
    ok("gooseui" in NEEDS_SOFT, "the Goose UI is in the signal at all")
    comps = healthy(); comps["gooseui"] = up()
    out = needs_derive(comps, HARD, NEEDS_SOFT,
                       {"gooseui": {"model": "ghost-27B", "live_model": "live-4B"}})
    need = out["gooseui"]["needs"][0]
    ok(need["state"] == "swapped", "a stale Goose UI chip derives `swapped`")
    ok(need["action"] == "restart" and need["target"] == "gooseui",
       "…and offers Restart Goose UI")
    ok("Goose UI" in need["text"], "…in her words, not ours")
    ok("gooseui" in _LANE_RESTART,
       "…and restart() accepts the lane name, so the button is not dead")
    src = (ROOT / "bridge" / "routers" / "components.py").read_text()
    ok("gooseui_stop" in src and "gooseui_start" in src,
       "…by delegating to the lane's OWN audited stop/start (never a kill by name)")
    # And the silence gate still holds for a lane that is not running.
    comps["gooseui"] = {"installed": True, "running": False}
    ok("gooseui" not in needs_derive(comps, HARD, NEEDS_SOFT,
                                     {"gooseui": {"model": "a", "live_model": "b"}}),
       "a Goose UI that is not running says nothing")


def test_every_stale_app_in_the_incident_now_derives_a_sentence():
    """THE WHOLE POINT, as one assertion: replay the incident's binding map and check
    that the banner that reported all-healthy now names all four surfaces."""
    from bridge.routers.components import NEEDS_SOFT, needs_derive
    comps = healthy(); comps["gooseui"] = up()
    live = "Parable-Qwen3-4B-Claude-Fable-5-GGUF-Q4_K_M"
    ghost = "Qwen3.6-27B-Fable-Fus-711-UnHeretic-NM-DAU-NEO-MAX-NEO-Q4_K_S"
    out = needs_derive(comps, HARD, NEEDS_SOFT,
                       {n: {"model": ghost, "live_model": live}
                        for n in ("hermes", "odysseus", "gooseui", "opencode")})
    for n in ("hermes", "odysseus", "gooseui", "opencode"):
        ok(out.get(n, {}).get("needs", [{}])[0].get("state") == "swapped",
           f"{n} is no longer silent while it names a model nobody is serving")
        ok(ghost in out[n]["needs"][0]["text"] and live in out[n]["needs"][0]["text"],
           f"…and {n}'s sentence names BOTH ids")


def test_the_pin_affordance_exists_end_to_end():
    """Audit §5.5, the wall Debi hit: with pin ≠ served the drift state was STABLE."""
    src = (ROOT / "bridge" / "routers" / "models.py").read_text()
    ok('@app.post("/api/models/pin")' in src, "there is a route that ends the drift")
    ok("_set_runner_model(live)" in src,
       "…and it writes the pin to the model the runner is ACTUALLY serving")
    ok("only the model the runner is actually serving can be pinned" in src,
       "…and refuses to pin anything else, which would just move the drift")
    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    ok("pinServedModel" in panel, "the panel has ONE implementation of the click")
    ok(panel.count("pinServedModel()") >= 2,
       "…reachable from more than one surface (card + models/popover)")
    ok("Pin this model" in panel, "…and it is called what it does")
    ok("const drift = isRunner" in panel,
       "…driven by pin ≠ served, hoisted out of the deleted-file branch")


def test_the_chat_lane_stops_labelling_turns_with_the_pin():
    """U18's named echo, closed. The composer chip read LIVE while the wire, the
    model_info frame, the transcript metadata and log_turn all read the PIN."""
    src = (ROOT / "bridge" / "routers" / "chat.py").read_text()
    ok('model = live or rc.get("model", "")' in src,
       "the direct lane is live-first with the pin as the runner-down fallback")
    ok('key, model = rc.get("api_key", ""), rc.get("model", "")' not in src,
       "…and the pin-only line is GONE, not merely shadowed")
    ok("_live_model_id" in src and "asyncio.to_thread" in src,
       "…probed off the event loop, once per turn")


def test_the_seeders_agree_on_what_dangles():
    """Audit §5.2: the three-state rule (seed when unset · replace when it DANGLES ·
    honour otherwise) existed in two places and nowhere else. One definition now."""
    from bridge.gooseprov import dangles, provider_model, set_provider_model
    ok(dangles("ghost", ["a", "b"]), "a name nothing offers dangles")
    ok(not dangles("a", ["a", "b"]), "a name we offer does not")
    ok(not dangles("ghost", ["a"], served="ghost"),
       "…and one the runner is SERVING never does, registry or not")
    ok(not dangles("", ["a"]), "unset is 'seed me', not 'repair me'")
    ok(not dangles("ghost", []),
       "an empty offer list is ABSENCE OF INFORMATION and never makes anything dangle")
    y = ("providers:\n  openai:\n    model: keep-me\n  custom_mot_deck__local:\n"
         "    enabled: true\n    model: ghost\nactive_provider: custom_mot_deck__local\n")
    ok(provider_model(y) == "ghost", "goose's own nested key is readable")
    n = set_provider_model(y, "live")
    ok("model: live" in n and "model: keep-me" in n,
       "…and repairable IN PLACE without touching the neighbouring provider")
    ok(set_provider_model("extensions:\n  todo:\n    enabled: true\n", "live")
       == "extensions:\n  todo:\n    enabled: true\n",
       "…and a config with no block of ours comes back BYTE-IDENTICAL (never invented)")


def test_a_switch_re_seeds_every_dependent():
    """S28's core: the seeders were all correct and only ever ran at component START.
    A runner switch is not a component start — which is why four surfaces kept the old
    name for a week."""
    src = (ROOT / "bridge" / "routers" / "models.py").read_text()
    ok("def _rebind_dependents(" in src, "the fan-out exists as ONE named function")
    ok(src.count("_rebind_dependents(") >= 3,
       "…and BOTH success paths call it — including the believe-the-probe arm, which "
       "is the path the real incident's switch actually took")
    for who in ("hermes", "odysseus", "goose"):
        ok(who in src.split("def _rebind_dependents(")[1][:1400]
           or f"_rebind_{who}" in src, f"{who} is named in the fan-out")
    ok("HARNESS_WIRE_MODEL" in src,
       "…and the Odysseus seed is finally CALLED through its zero-caller seam")
    ok("repair_config_model" in src,
       "…and goose's dangling model choice is repaired file-side")
    ok("GOOSE_MODEL" in src and "respawn" in src,
       "…with the honest limit stated where it lives: a live goosed's env cannot "
       "change without a respawn, so the banner covers that half")


# ══ §8 A FAILURE REASON IS RETRACTED WHEN THE THING IS OBSERVABLY UP (U60) ═══
#
# THE INCIDENT (Debi, screenshot, 2026-09-02, and the reason this is not just more of
# §6): the runner card read "Online · serving Qwen3.5-9B-Q4_0" with "no model is pinned
# — pick one in Models" on the line below it. /api/status agreed with the green half in
# every field — pin = pin_intent = live_id = Qwen3.5-9B-Q4_0, running true, health ok —
# and carried the red half anyway, in `last_error`, with stale: false, model: "",
# path: "". The sentence was TRUE about a start attempt made while harness.yaml had no
# runner.model; it was published as though it described now.
#
# REPRODUCED before it was fixed, on a scratch bridge on a free port with the runner
# stood in for by a scratch listener: unpin → Start (fails, "runner.model not set",
# reason recorded) → bring the runner up → Start → prov = {"state": "on", "detail":
# "already running"} and the reason standing beside running: true / health: ok, poll
# after poll. That prov detail is the fingerprint: _provision's `_running_sync`
# short-circuit was the one success path in the file that cleared nothing — and it is
# not even the only door, because models.py's _do_switch (a Load from the Models pane)
# runs start_component.sh itself and never touches the dict at all.
#
# THE CLASS is §6's, one field over — v1.5.57 killed "a failed OVERLAY persists while
# observably running"; this is "a failed SENTENCE persists while observably running".
# Which is why the retraction lives on the READ, over every component's row, rather than
# on one starter's success path: a rule each new start path has to remember is a rule
# one of them will forget.


def test_a_recorded_failure_is_retracted_once_the_thing_is_up():
    """THE CONTRACT, executed: present while stopped+failed, GONE once running+ok."""
    from bridge.routers.components import (FAIL_RETRACT_OK, clear_start_failure,
                                           fail_note_to_publish)
    note = {"text": "no model is pinned — pick one in Models", "stale": False}
    clear_start_failure("t")
    # STOPPED + FAILED: the reason is what the card is FOR. Any number of polls.
    for _ in range(5):
        pub = fail_note_to_publish("t", False, note)
        ok(pub is not None and pub["text"] == note["text"] and pub["stale"] is False,
           "while it is down, the reason is published as the current state")
    # RUNNING + OK: one poll of history, then gone — and gone stays gone.
    first = fail_note_to_publish("t", True, note)
    ok(first is not None and first["stale"] is True,
       "the first good poll publishes it as HISTORY, never as a bare failure")
    ok(note["stale"] is False,
       "…and publishes a COPY: the stored record is not rewritten to say so")
    ok(fail_note_to_publish("t", True, note) is None,
       f"the {FAIL_RETRACT_OK}nd consecutive running+ok poll retracts it entirely")
    ok(fail_note_to_publish("t", True, note) is None, "…and it does not come back")
    clear_start_failure("t")


def test_a_flapping_component_keeps_the_sentence_that_explains_it():
    """THE DEBOUNCE, and why it is health.py's shape rather than "clear immediately":
    a component that comes up for ONE poll and dies must not erase the reason it keeps
    dying. Walked live on the scratch bridge as well as executed here."""
    from bridge.routers.components import clear_start_failure, fail_note_to_publish
    note = {"text": "the runner binary is missing", "stale": False}
    clear_start_failure("f")
    ok(fail_note_to_publish("f", False, note)["stale"] is False, "down: the reason")
    ok(fail_note_to_publish("f", True, note)["stale"] is True, "up for one poll: history")
    ok(fail_note_to_publish("f", False, note)["stale"] is False,
       "…and back down: the streak is forgotten and the reason is current again")
    ok(fail_note_to_publish("f", True, note)["stale"] is True,
       "a second flap starts the count over — it cannot accumulate its way to silence")
    clear_start_failure("f")


def test_every_start_path_clears_it_and_the_read_is_the_backstop():
    src = _APP_SOURCE
    prov = src[src.index("def _provision(", src.index("appsrc: bridge/routers/component_lifecycle.py")):]
    ok(prov.count("clear_start_failure(") >= 2,
       "BOTH of _provision's success arms clear the record — including the "
       "`already running` short-circuit, the arm the live bug came through")
    already = prov[prov.index("if _running_sync(n, c):"):][:900]
    ok("clear_start_failure(" in already,
       "…and it is in the short-circuit specifically, not only on the rc == 0 path")
    ok("_FAIL_OK_STREAK.pop(" in prov,
       "a FRESH failure resets the debounce, so it always gets its full grace")
    st = src[src.index("async def status() -> dict:"):]
    st = st[:st.index("# ══ THE DEPENDENCY SIGNAL")]
    ok('fail_note_to_publish(n, running_ok, row.get("last_error"))' in st,
       "the read-side backstop runs over EVERY component's row, not the runner's only "
       "— the echo IS the loop, so no component can be left out of it")
    ok('row.get("health") == "ok"' in st,
       "…and takes the DEBOUNCED health verdict, not one probe, as its evidence")


def test_the_card_can_never_pair_a_green_dot_with_a_bare_failure():
    """THE PANEL HALF. The lie was VISIBLE here, so this surface must not depend on the
    bridge being right about something it can check for itself."""
    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    card = panel[panel.index("function cardHTML("):]
    card = card[:card.index("\nfunction rescanFromCard")]
    ok("const upOk = !!c.running && h === 'ok';" in card,
       "the card derives 'observably up and healthy' for itself")
    ok("le.stale || upOk ? 'last start attempt: '" in card,
       "…and a component that is up NEVER gets an unlabelled failure sentence")
    ok("le.target === 'models' && !upOk" in card,
       "…nor an Open Models button hung off a start that is over")
    ok(card.split("const wantsModels")[1][:40].find("fileGone") >= 0,
       "…while a dead model FILE is a now-fact and keeps every button it had")


for fn in (test_silent_when_well, test_runner_down, test_runner_has_no_model,
           test_swapped_is_the_lie_this_catches, test_moved_endpoint,
           test_a_dep_that_is_not_the_runner, test_a_stopped_component_says_nothing,
           test_an_uninstalled_dep_says_nothing, test_a_dep_this_build_does_not_know,
           test_every_sentence_is_written_for_her, test_routes_exist,
           test_the_shell_renders_it,
           test_a_dead_model_file_never_offers_a_dead_button,
           test_a_runner_that_is_merely_down_is_unchanged,
           test_two_strikes_before_we_accuse_a_disk,
           test_we_never_claim_what_the_os_would_not_tell_us,
           test_the_failure_sentence_is_a_sentence,
           test_the_bridge_stops_repeating_an_exit_code_it_can_check,
           test_the_card_can_tell_intent_from_fact,
           # §7 — the coherence wave (S28)
           test_the_three_missing_bindings_can_be_read_from_a_file,
           test_two_strikes_before_we_accuse_an_app,
           test_the_goose_ui_gets_a_sentence_with_a_working_button,
           test_every_stale_app_in_the_incident_now_derives_a_sentence,
           test_the_pin_affordance_exists_end_to_end,
           test_the_chat_lane_stops_labelling_turns_with_the_pin,
           test_the_seeders_agree_on_what_dangles,
           test_a_switch_re_seeds_every_dependent,
           # §8 — the stale failure sentence (U60)
           test_a_recorded_failure_is_retracted_once_the_thing_is_up,
           test_a_flapping_component_keeps_the_sentence_that_explains_it,
           test_every_start_path_clears_it_and_the_read_is_the_backstop,
           test_the_card_can_never_pair_a_green_dot_with_a_bare_failure):
    fn()

if FAILS:
    print(f"\nFAILED {len(FAILS)} of {CHECKS[0]}:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"\ndependency signal: {CHECKS[0]} checks passed")
