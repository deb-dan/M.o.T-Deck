"""OUR side of the OpenCode seam (bridge/contract_tests/test_opencode_contract.py
pins UPSTREAM's).

Everything asserted here is a decision that is silent when wrong:
  * `serve` rather than `web`  — `web` calls open() on the URL and would pop a browser
    window behind the native tab on every Start;
  * an EXPLICIT --port         — upstream's own default is 0, an ephemeral port, so
    without this the tab points at a port nothing holds;
  * the four XDG_* variables   — the ONLY thing keeping its config, its session db and
    the provider packages it installs at runtime out of ~/.config and ~/.cache;
  * autoupdate off, twice      — upstream's updater is ON by default and would move the
    binary out from under the pin;
  * the tools warning          — OpenCode has no text fallback, so a model without tool
    calling makes it look broken rather than slower.

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_opencode_lane.py -q
"""
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

START = open(os.path.join(ROOT, "scripts", "start_component.sh"),
             encoding="utf-8", errors="replace").read()
INSTALL = open(os.path.join(ROOT, "scripts", "install_opencode.sh"),
               encoding="utf-8", errors="replace").read()
APP = open(os.path.join(ROOT, "bridge", "app.py"),
           encoding="utf-8", errors="replace").read()
PANEL = open(os.path.join(ROOT, "bridge", "panel", "index.html"),
             encoding="utf-8", errors="replace").read()
SWIFT = open(os.path.join(ROOT, "app", "main.swift"),
             encoding="utf-8", errors="replace").read()
MANIFEST = yaml.safe_load(open(os.path.join(ROOT, "harness.yaml"),
                               encoding="utf-8").read())


def branch() -> str:
    """The opencode case arm of start_component.sh, and nothing else — so an
    assertion can never be satisfied by a neighbouring component's line."""
    i = START.index("\n  opencode)")
    j = START.index("\n  hermes)", i)
    return START[i:j]


# ── the manifest ─────────────────────────────────────────────────────────────
def test_manifest_entry():
    c = MANIFEST["components"]["opencode"]
    assert c["installed"] is False, "OPTIONAL — it must ship uninstalled"
    assert c["enabled"] is False
    assert c["depends_on"] == [], (
        "opencode must not be a dependency edge: it is usable against any provider it "
        "has configured, and our runner fan-out is best-effort")
    assert c["port"] == 4096
    assert MANIFEST["build"]["opencode_pin"] == "1.18.19"


def test_pin_is_an_npm_version_not_a_git_ref():
    """The pin is deliberately NOT a sha: upstream ships prebuilt binaries and npm's
    version is the only unambiguous handle (its git org moved under `anomalyco` while
    sst/opencode still serves)."""
    pin = str(MANIFEST["build"]["opencode_pin"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin), f"not a semver: {pin!r}"


# ── the installer ────────────────────────────────────────────────────────────
def test_installer_verifies_before_it_extracts():
    assert "dist" in INSTALL and "shasum" in INSTALL, (
        "npm's published sha1 must be checked — a mismatch is a corrupt or substituted "
        "artifact and either way we stop")
    assert INSTALL.index("sha1 mismatch") < INSTALL.index("tar xzf"), (
        "the hash is verified BEFORE extraction, not after")
    assert "optionalDependencies" in INSTALL, (
        "the platform package's version is read out of opencode-ai's own metadata "
        "rather than assumed — an upstream re-pin must trip here, not silently install "
        "a mismatched binary")


def test_installer_extracts_exactly_one_file():
    assert "package/bin/opencode" in INSTALL
    assert "--strip-components 2" in INSTALL, (
        "npm wraps everything in package/; the binary must land at data/opencode/bin/")
    assert "chmod +x" in INSTALL


def test_installer_proves_the_binary_runs():
    assert "--version" in INSTALL, (
        "a tab that opens onto a dyld error is worse than an install that refused")


def test_installer_is_macos_only_and_arch_aware():
    assert "opencode-darwin-arm64" in INSTALL and "opencode-darwin-x64" in INSTALL
    assert "uname -m" in INSTALL


def test_installer_creates_the_private_home_and_workspace():
    for d in ("xdg/config", "xdg/cache", "xdg/data", "xdg/state"):
        assert d in INSTALL, f"data/opencode/{d} must exist before the first Start"
    assert "data/opencode-workspace" in INSTALL


# ── the start branch ─────────────────────────────────────────────────────────
def test_start_uses_serve_not_web():
    b = branch()
    assert "serve --hostname 127.0.0.1 --port" in b, (
        "`opencode serve` is the launch: at the pin `serve` and `web` share the same "
        "Server.listen, the same network options and the same embedded SPA — `web` "
        "only adds an open() call that pops a browser behind the native tab")
    assert re.search(r'"\$OC_BIN"\s+web\b', b) is None, "the `web` subcommand must not be used"


def test_start_passes_the_port_explicitly():
    b = branch()
    assert 'OC_PORT=4096' in b, "the awk fallback must mirror the manifest"
    assert '--port "$OC_PORT"' in b
    assert "default is 0" in b, (
        "the reason must stay in the file: upstream's --port default is an EPHEMERAL "
        "port, so omitting it is not a cosmetic shortcut")


def test_start_never_passes_the_dangerous_flags():
    b = branch()
    for flag in ("--cors", "--mdns"):
        assert flag not in b, (
            f"{flag} must never be passed: --cors widens the origin allowlist and "
            "--mdns flips the hostname to 0.0.0.0 on a server with NO auth")
    assert "--auto" not in b, (
        "--auto auto-approves every tool call — the same rule as aider's --yes-always")


def test_start_confines_every_write_with_xdg():
    b = branch()
    for v in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        assert v in b, (
            f"{v} is missing — packages/core/src/global.ts derives config/cache/data/"
            "state from xdg-basedir, so all four are what keep its session db and its "
            "runtime npm installs inside data/opencode")
        assert f'{v}="$OC_HOME' in b, f"{v} must point INTO data/opencode/xdg"


def test_start_disables_autoupdate_both_ways():
    b = branch()
    assert "OPENCODE_DISABLE_AUTOUPDATE=1" in b, "the env half"
    assert '"autoupdate"' in b and "False" in b, "the config half"


def test_start_clears_the_port_with_the_ownership_check():
    b = branch()
    assert "_clear_port \"$OC_PORT\" opencode" in b, (
        "the listener-scoped, ownership-checked clear — never a bare lsof kill")
    assert b.index("_clear_port") < b.index("nohup"), "cleared before launch"


def test_start_runs_in_the_workspace():
    b = branch()
    assert 'cd "$OC_WS"' in b, (
        "the cwd IS the boundary: upstream resolves a request with no "
        "x-opencode-directory header to process.cwd()")
    assert 'OC_WS="$ROOT/data/opencode-workspace"' in b


def test_start_writes_pid_and_log_absolutely():
    b = branch()
    assert '"$ROOT/data/opencode.pid"' in b and '"$ROOT/data/logs/opencode.log"' in b, (
        "absolute paths — the launch happens inside a `cd` subshell")


def test_start_health_probe_has_a_fallback():
    b = branch()
    assert "/global/health" in b, "its own JSON health route"
    assert b.count("curl -sf") >= 2, (
        "a `/` fallback so a route rename at a future pin degrades to 'the tab has "
        "something to show' rather than a Start that refuses")


def test_config_fan_out_merges_and_seeds():
    b = branch()
    assert "opencode.json" in b
    assert "@ai-sdk/openai-compatible" in b, "the provider package upstream documents"
    assert "baseURL" in b and "apiKey" in b
    # MERGE, not overwrite: a user's own keys in that file must survive a restart.
    assert "json.load(fh)" in b and "cfg.setdefault" in b or "cfg[\"provider\"]" in b
    # The MLX wire-id rule, the same one hermes and seed_odysseus_jan use.
    assert '"mlx"' in b and "m.get(\"path\")" in b, (
        "MLX needs the model PATH as the wire id (the MLX servers treat `model` as a "
        "model to LOAD and would resolve a bare id on HuggingFace)")
    # The default model is SEEDED, never enforced.
    assert "stale" in b, (
        "the default model is replaced only when it points at one of OUR provider's "
        "models that no longer exists — a choice made inside OpenCode must survive")
    assert "hidden" in b, "a model the user hid must not be offered here either"


# ── the bridge ───────────────────────────────────────────────────────────────
def test_bridge_install_route_uses_the_standalone_installer():
    assert '"opencode": "install_opencode.sh"' in APP
    assert '"comfyui", "unsloth", "opencode"' in APP, "the install allowlist"


def test_bridge_plan_states_the_tool_calling_requirement():
    i = APP.index('"opencode": [')
    plan = APP[i:i + 2500]
    assert "REQUIRES A TOOL-CALLING MODEL" in plan
    assert "MIT" in plan
    assert "ONLINE-ONLY" in plan
    assert "data/opencode/xdg" in plan, "where its writes go must be said before install"
    assert "auto-updater is disabled" in plan


def test_bridge_logs_are_viewable_in_panel():
    assert '"opencode", "opencode-install",' in APP
    for n in ("opencode", "opencode-install", "loffice-boot"):
        assert f"{{n:'{n}'," in PANEL, f"{n} is missing from the panel's LOG_SOURCES"


def test_bridge_notes_row():
    from bridge import app as A
    note = A._NOTES["opencode"]
    assert note.startswith("opencode on :4096")
    assert "no auth" in note
    assert "Add project" in note, (
        "the note carries the one manual fallback, so a user who somehow lands on "
        "OpenCode's own empty home screen is not left guessing")


# ── the tools warning (PURE) ─────────────────────────────────────────────────
def test_tools_warning_table():
    from bridge import app as A
    assert A.opencode_tools_warning({"id": "m", "tools": True}) == "", (
        "a tool-capable model produces NO warning")
    bad = A.opencode_tools_warning({"id": "gemma", "tools": False})
    assert "gemma" in bad and "NO tool-calling" in bad
    unk = A.opencode_tools_warning({"id": "mystery", "tools": None})
    assert "mystery" in unk and "does not say" in unk, (
        "an UNKNOWN verdict is its own message — it may not be reported as a 'no'")
    assert A.opencode_tools_warning({"id": "x"}) == A.OPENCODE_TOOLS_UNKNOWN % "x", (
        "a MISSING tools key is the same 'unknown' case as an explicit null")
    for junk in (None, "x", 3, [], ()):
        assert A.opencode_tools_warning(junk) == A.OPENCODE_TOOLS_NONE, (
            f"no live model ({junk!r}) has its own message")


def test_the_warning_is_a_warning_not_a_refusal():
    """A template heuristic may not stand between the user and a program they asked to
    run — so the gate appends to the plan's NOTE and nothing raises or 409s."""
    i = APP.index("def _opencode_live_warning")
    body = APP[i:i + 900]
    assert "HTTPException" not in body and "status_code" not in body
    assert 'if n == "opencode":' in APP and "note = (note" in APP


def test_capabilities_only_carry_an_explicit_true():
    from bridge import app as A
    assert A._model_caps({"tools": True}) == ["tools"]
    assert A._model_caps({"tools": False}) == []
    assert A._model_caps({"tools": None}) == []
    assert A._model_caps({}) == [], (
        "an unknown verdict must NOT appear as a capability — the panel and the gate "
        "both read absence as 'cannot', and 'unknown' is not 'cannot'")
    assert A._model_caps({"vision": True, "tools": True}) == ["vision", "tools"]
    assert A._model_caps({"mmproj": "/x.gguf"}) == ["vision"], "vision is unchanged"


def test_installed_view_carries_a_three_valued_tools_key():
    assert '"tools": (m.get("tools") if isinstance(m.get("tools"), bool) else None)' in APP, (
        "the wire value must be true/false/null — a junk registry value has to collapse "
        "to null, never to a truthy string")
    assert '"capabilities": _model_caps(m)' in APP


def test_download_completion_sets_the_verdict():
    assert "base[\"tools\"] = _modeltools.tools_for_entry(base)" in APP, (
        "a model that just landed must show its pill without a Rescan")
    i = APP.index('base["tools"] = _modeltools.tools_for_entry(base)')
    assert APP.index("_registry_add(base)", i) > i, "…before it is registered"


# ── panel + shell ────────────────────────────────────────────────────────────
def test_panel_draws_the_pill_at_all_three_sites_through_one_predicate():
    assert PANEL.count("modelHasTools(") >= 4, (
        "one predicate, used by the rows, the popover and the detail pane — three "
        "independent truthiness checks could disagree")
    assert "function modelHasTools(m){" in PANEL
    # …and the predicate is the absent-not-greyed rule in code.
    i = PANEL.index("function modelHasTools(m){")
    fn = PANEL[i:i + 260]
    assert "m.tools === true" in fn, "STRICT true — a null must not be truthy-tested"


def test_panel_never_draws_a_negative_pill():
    """A false OR unknown verdict must render as NOTHING. So every place that emits a
    tools pill must be guarded by the predicate, and no pill text may be a negation."""
    for m in re.finditer(r"[^\n]*>tools<[^\n]*", PANEL):
        line = m.group(0)
        assert "modelHasTools(" in line, (
            f"a tools pill is drawn without the predicate: {line.strip()[:140]}")
    # The popover builds its pill through a DOM helper rather than an HTML string, so
    # it is pinned separately — same rule, different grammar.
    assert "if (modelHasTools(m)) pill('vision', 'tools');" in PANEL, (
        "the chat model popover's tools pill must be guarded by the same predicate")
    for neg in (">no tools<", ">tools ✗<", ">no-tools<"):
        assert neg not in PANEL, f"a negative pill ({neg}) contradicts absent-not-greyed"


def test_nav_registry_agrees_across_the_three_tables():
    from bridge import nav
    assert "opencode" in nav.NAV_IDS
    assert any(i == "opencode" and p for i, p in nav.DEFAULT_TOPBAR), (
        "pinned on the strip by default")
    assert any(i == "opencode" and p for i, p in nav.DEFAULT_SIDEBAR)
    assert len([1 for _i, p in nav.DEFAULT_TOPBAR if p]) <= nav.NAV_TOPBAR_MAX, (
        "the default layout must itself satisfy Debi's 12-pin cap")
    flat = PANEL.replace(" ", "")
    assert "id:'opencode'" in flat, "the panel mirrors the id"
    assert "tab:'OpenCode'" in flat, (
        "the panel's `tab` must match main.swift's TITLE exactly, or the sidebar row "
        "silently stops switching tabs")
    assert "'opencode'];" in flat.replace("\n", "") or "'opencode'," in flat, (
        "opencode is in the panel's default layouts")
    assert 'HarnessTab(id: "opencode", title: "OpenCode"' in SWIFT
    assert '"loffice", "opencode"' in SWIFT, "the shell's default strip carries it"


def test_swift_width_budget_was_rechecked():
    assert "ELEVEN current titles" in SWIFT, (
        "the tab-strip width budget comment must be re-derived whenever a tab lands — "
        "it is the only thing standing between a new tab and a strip that collides "
        "with the ⫽ button")


# ══ THE LANDING (2026-08-21) ═════════════════════════════════════════════════
# Debi's report: everything running, and the tab shows "Nothing here yet — Create a
# session to get started" beside a Projects rail whose only entry is "Add project".
# Two halves fix that, and both are silent when wrong — an unregistered workspace and
# a wrong deep link both look exactly like the bug they replace.

def test_the_workspace_is_made_a_real_git_project_at_install():
    """A directory is only a PROJECT to OpenCode if git discovery yields an ID, and an
    id needs a remote, a cached id, or a ROOT COMMIT. `git init` alone leaves it in the
    shared 'global' project — which is exactly the empty Projects rail Debi saw."""
    assert "seed_workspace_project" in INSTALL
    body = INSTALL[INSTALL.index("seed_workspace_project() {"):]
    body = body[:body.index("\npost_install() {")]
    assert "git init" in body
    assert "--allow-empty" in body, (
        "git init WITHOUT a commit leaves the project id as 'global' — upstream's own "
        "test asserts this (test/project/migrate-global.test.ts:64-72)")
    assert '-c user.name=' in body and '-c user.email=' in body, (
        "identity must be REPO-LOCAL: this may never touch the user's global git "
        "config, and a machine with no user.email set would otherwise fail the commit")
    assert "git config --global" not in INSTALL
    assert '[[ -d "$ws/.git" ]] && ' in body, "idempotent — a re-run must not re-init"
    assert "command -v git" in body, "a machine without git must warn, not fail"
    # It runs on the already-installed path too, so a stale install self-heals by
    # clicking Install again — the same reasoning as the manifest flag beside it.
    pi = INSTALL[INSTALL.index("post_install() {"):]
    assert "seed_workspace_project" in pi[:pi.index("\n}")]


def test_the_tab_lands_on_a_session_not_on_the_empty_home():
    from bridge.app import opencode_landing_url
    url = opencode_landing_url("/Users/x/Library/Application Support/Harness", 4096)
    # base64url, unpadded — upstream's own encoder (core/src/util/encode.ts:1-5).
    assert url == ("http://127.0.0.1:4096/"
                   "L1VzZXJzL3gvTGlicmFyeS9BcHBsaWNhdGlvbiBTdXBwb3J0L0hhcm5lc3MvZGF0YS9vcGVuY29kZS13b3Jrc3BhY2U"
                   "/session"), url
    assert "=" not in url.split("/")[3], "padding is stripped, as upstream strips it"
    assert "+" not in url and " " not in url, "url-safe alphabet, and no raw space"
    # A junk port can never produce a URL pointing at something else.
    for junk in (None, "", "junk", 0, -1, 70000, [4096]):
        assert opencode_landing_url("/x", junk).startswith("http://127.0.0.1:4096/")
    assert opencode_landing_url("/x", "4200").startswith("http://127.0.0.1:4200/")
    # The path it encodes is the workspace the start script actually cd's into.
    assert "/data/opencode-workspace" in __import__("base64").urlsafe_b64decode(
        opencode_landing_url("/x", 1)[len("http://127.0.0.1:1/"):-len("/session")]
        + "==").decode()


def test_the_landing_route_is_a_redirect_and_the_shell_points_at_it():
    assert '@app.get("/opencode")' in APP
    route = APP[APP.index('@app.get("/opencode")'):]
    route = route[:route.index('@app.get("/api/models")')]
    assert "status_code=307" in route and "Location" in route
    assert "no-store" in route, "a redirect that depends on ROOT may not be cached"
    assert "opencode_landing_url(ROOT, port)" in route, (
        "the URL is built in ONE place, so the test above is the whole guard")
    # The shell asks the bridge rather than baking a URL: only the bridge knows ROOT
    # (repo vs snapshot) and the configured port.
    assert 'HarnessTab(id: "opencode", title: "OpenCode",' in SWIFT
    tab = SWIFT[SWIFT.index('HarnessTab(id: "opencode"'):]
    tab = tab[:tab.index("\n    //", 10) if "\n    //" in tab[10:] else 400]
    assert "127.0.0.1:8700/opencode" in tab, (
        "the OpenCode tab must open the bridge's landing redirect, not :4096 directly "
        "— :4096/ IS the empty home screen")


def test_the_start_warms_the_project_row_without_leaving_litter():
    br = START[START.index("\n  opencode)"):]
    br = br[:br.index("\n  hermes)")]
    assert "/project/current" in br, (
        "one READ registers the project server-side before the first page load")
    # Comments are stripped first: this is about what the script RUNS, and the reason
    # for the choice is written in a comment right beside it.
    code = "\n".join(ln for ln in br.splitlines() if not ln.strip().startswith("#"))
    assert "--get" in code, "the warm-up is a READ"
    assert "/session" not in code and "-XPOST" not in code and "--request POST" not in code, (
        "deliberately NOT POST /session: one empty timestamped session per Start would "
        "be litter, not a landing")
    assert "|| echo" in br, "best-effort — a failed warm-up may never fail the Start"
    assert "Add project" in br, (
        "the honest fallback is named in the start output: if the deep link ever stops "
        "working, one click on Add project is the manual equivalent")
    assert "Add project" in APP, "and in the install plan / component note"


# ── the seeded config, EXECUTED ──────────────────────────────────────────────
# Everything above greps the shell. These run the seeding block for real against a
# temp tree and assert the exact shape upstream requires, because "the file exists"
# and "the file makes the provider CONNECTED" are different claims and only the
# second one is what Debi saw fail.
#
# THE UPSTREAM RULES BEING PINNED (opencode 1.18.19, file:line):
#   * a config provider lands in the runtime provider map, and the v1 route reports
#     `connected = Object.keys(providers).filter(id => id in connected || creds[id])`
#     — packages/opencode/src/server/routes/instance/httpapi/handlers/provider.ts:51-60;
#   * the models map KEY is the id used in every `provider/model` string, while the
#     entry's `id` becomes `api.id` (provider.ts:1465) which is what is literally sent
#     on the wire (provider.ts:1886 `sdk.languageModel(model.api.id)`);
#   * `options.baseURL` wins over the derived api url (provider.ts:1731);
#   * a provider whose models map is EMPTY is deleted outright (provider.ts:1684-1687);
#   * the desktop splits `provider/model` with a bare destructure
#     (app/src/hooks/provider-catalog.ts:31-36), so a key containing "/" yields an
#     EMPTY model id — which is why MLX paths may never be keys.
import json
import subprocess
import tempfile


def _seed_block() -> str:
    """The python heredoc the opencode branch runs, extracted verbatim."""
    b = branch()
    i = b.index("<<'PYOC'\n") + len("<<'PYOC'\n")
    j = b.index("\nPYOC\n", i)
    return b[i:j]


def _run_seed(models, want="", extra_global=None, extra_project=None):
    """Execute the real seeding block over a temp registry. Returns (global, project)."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"))
    os.makedirs(os.path.join(d, "ws"))
    with open(os.path.join(d, "data", "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": models}, fh)
    gp = os.path.join(d, "xdg", "config", "opencode", "opencode.json")
    pp = os.path.join(d, "ws", "opencode.json")
    for path, seed in ((gp, extra_global), (pp, extra_project)):
        if seed is not None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(seed, fh)
    script = os.path.join(d, "seed.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_seed_block())
    env = dict(os.environ, OC_CFG=gp, OC_PCFG=pp, OC_MODEL=want,
               OC_BASE="http://127.0.0.1:6767/v1", OC_KEY="harness-key")
    p = subprocess.run([sys.executable, script], cwd=d, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return (json.load(open(gp, encoding="utf-8")),
            json.load(open(pp, encoding="utf-8")))


GGUF = {"id": "Qwen3-9B-Q4_0", "format": "gguf", "path": "/m/q.gguf", "ctx": 32768}
MLX = {"id": "mlx-community/Qwen3-8B-4bit", "format": "mlx",
       "path": "/Users/d/models/Qwen3-8B-4bit"}


def test_seeded_provider_has_every_key_upstream_requires():
    g, _ = _run_seed([GGUF])
    p = g["provider"]["llama.cpp"]
    assert p["npm"] == "@ai-sdk/openai-compatible", (
        "without npm, opencode has no client for a provider it has never heard of")
    assert p["options"]["baseURL"] == "http://127.0.0.1:6767/v1", (
        "options.baseURL is what provider.ts:1731 prefers over the derived api url")
    assert p["options"]["apiKey"] == "harness-key"
    assert p["name"], "the display name shown in Settings -> Providers"
    assert p["models"], (
        "a provider whose models map is empty is DELETED by provider.ts:1684-1687 — "
        "it would never appear as connected")
    assert g["$schema"] == "https://opencode.ai/config.json"
    assert g["autoupdate"] is False, "the pin rule, in the file as well as the env"


def test_a_model_key_is_never_a_path_and_the_wire_id_always_is():
    """THE MLX DEFECT. The key is what `llama.cpp/<key>` and the picker use; the
    entry's `id` is what goes on the wire. Conflating them left the desktop with an
    empty model id for every MLX model."""
    g, _ = _run_seed([MLX], want=MLX["id"])
    models = g["provider"]["llama.cpp"]["models"]
    key, = models.keys()
    assert "/" not in key, (
        "a key containing '/' is destructured to an EMPTY model id by the desktop "
        "(app/src/hooks/provider-catalog.ts:31-36)")
    assert models[key]["id"] == MLX["path"], (
        "the MLX servers treat `model` as a model to LOAD — the wire id must be the "
        "registry PATH, and it belongs in `id` (api.id), not in the key")
    assert models[key]["name"] == MLX["id"], "the picker still shows the real name"
    assert g["model"] == "llama.cpp/" + key
    assert g["model"].count("/") == 1, (
        "the default-model string is split with a bare `.split('/')` destructure")


def test_a_gguf_model_keeps_its_registry_id_on_both_sides():
    g, _ = _run_seed([GGUF], want=GGUF["id"])
    m = g["provider"]["llama.cpp"]["models"][GGUF["id"]]
    assert m["id"] == GGUF["id"], (
        "llama-server is launched with `--alias <registry id>`, so the id IS the "
        "served name — key and wire id coincide and both must be the plain id")
    assert g["model"] == "llama.cpp/" + GGUF["id"]


def test_the_context_limit_is_carried_only_when_it_is_known():
    g, _ = _run_seed([GGUF, dict(GGUF, id="noctx", ctx=None)])
    ms = g["provider"]["llama.cpp"]["models"]
    assert ms[GGUF["id"]]["limit"]["context"] == 32768
    assert ms[GGUF["id"]]["limit"]["output"] <= 32768
    assert "limit" not in ms["noctx"], (
        "an unknown context must be ABSENT, never 0 — a 0 limit is worse than none")


def test_tool_call_is_declared_only_when_the_registry_actually_knows():
    g, _ = _run_seed([dict(GGUF, id="yes", tools=True),
                      dict(GGUF, id="no", tools=False),
                      dict(GGUF, id="unknown", tools=None)])
    ms = g["provider"]["llama.cpp"]["models"]
    assert ms["yes"]["tool_call"] is True
    assert ms["no"]["tool_call"] is False
    assert "tool_call" not in ms["unknown"], (
        "bridge/modeltools.py is three-valued; unknown must stay absent so upstream's "
        "own default applies rather than us asserting something unmeasured")


def test_audio_and_hidden_models_are_never_offered():
    g, _ = _run_seed([GGUF, dict(GGUF, id="tts", kind="audio"),
                      dict(GGUF, id="gone", hidden=True)])
    ms = g["provider"]["llama.cpp"]["models"]
    assert set(ms) == {GGUF["id"]}


def test_an_empty_registry_still_produces_a_loadable_provider():
    """A provider with no models is deleted upstream, so the fallback entry is what
    keeps 'Settings -> Providers' honest on a machine with nothing downloaded yet."""
    g, _ = _run_seed([])
    ms = g["provider"]["llama.cpp"]["models"]
    assert ms and all("/" not in k for k in ms)


def test_the_project_copy_carries_the_provider_but_never_the_model():
    """config.ts:406-409 merges the project file AFTER the global one, and the desktop
    writes a model choice back to the GLOBAL file (PATCH /global/config) — so a `model`
    key here would stomp the user's own pick on every single load."""
    g, p = _run_seed([GGUF], want=GGUF["id"])
    assert p["provider"]["llama.cpp"] == g["provider"]["llama.cpp"], (
        "two independent paths to the same fact: if the XDG redirect ever fails to "
        "land, the project config still carries the provider")
    assert "model" not in p
    assert "autoupdate" not in p


def test_both_files_merge_rather_than_overwrite():
    g, p = _run_seed(
        [GGUF],
        extra_global={"theme": "mine", "provider": {"openai": {"npm": "x"}}},
        extra_project={"permission": {"edit": "ask"}})
    assert g["theme"] == "mine", "a user's own keys survive a restart"
    assert "openai" in g["provider"], "and their own providers"
    assert "llama.cpp" in g["provider"]
    assert p["permission"] == {"edit": "ask"}
    assert "llama.cpp" in p["provider"]


def test_a_user_model_choice_survives_but_a_deleted_one_does_not():
    keep, _ = _run_seed([GGUF], want=GGUF["id"],
                        extra_global={"model": "llama.cpp/" + GGUF["id"]})
    assert keep["model"] == "llama.cpp/" + GGUF["id"]
    other, _ = _run_seed([GGUF], want=GGUF["id"],
                         extra_global={"model": "anthropic/claude"})
    assert other["model"] == "anthropic/claude", (
        "a choice made INSIDE opencode, on another provider, must never be rewritten")
    stale, _ = _run_seed([GGUF], want=GGUF["id"],
                         extra_global={"model": "llama.cpp/deleted-model"})
    assert stale["model"] == "llama.cpp/" + GGUF["id"], (
        "but a pointer at one of OUR models that no longer exists is repaired")


def test_a_broken_config_file_is_replaced_not_inherited():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"))
    gp = os.path.join(d, "g.json")
    with open(gp, "w", encoding="utf-8") as fh:
        fh.write("{ this is not json")
    script = os.path.join(d, "seed.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(_seed_block())
    env = dict(os.environ, OC_CFG=gp, OC_PCFG=os.path.join(d, "p.json"), OC_MODEL="",
               OC_BASE="http://127.0.0.1:6767/v1", OC_KEY="k")
    p = subprocess.run([sys.executable, script], cwd=d, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert "llama.cpp" in json.load(open(gp, encoding="utf-8"))["provider"]


# ── the self-check: the line that makes a silent failure decidable ───────────
def test_the_start_verifies_the_provider_and_says_so():
    b = branch()
    code = "\n".join(ln for ln in b.splitlines() if not ln.strip().startswith("#"))
    assert '/provider"' in code, (
        "GET /provider is exactly what the desktop calls on the v1 protocol "
        "(bootstrap.ts:232-234) — asking it is asking the same question the UI asks")
    assert "provider check" in code, "one decidable line per Start"
    assert "NOT CONNECTED" in code and "CONNECTED" in code, (
        "both outcomes must be printable — a check that can only say 'ok' is not one")
    assert "Big Pickle" in code, (
        "the failure line names the symptom the user actually sees, so the next "
        "report is a diagnosis rather than an excavation")
    # It may never fail the Start: a diagnostic that can take a working component down
    # is worse than no diagnostic.
    assert "|| true" in code or "|| :" in code


def test_the_server_list_recovery_is_written_down():
    """Debi removed 127.0.0.1:4096 from Settings -> Servers and could not re-add it.
    resolveServerList seeds from the props the served page passes BEFORE merging
    stored entries (app/src/context/server.tsx:148-177, entry.tsx:156-172), so the
    current server is re-added on every load — the recovery is a reload. Add server
    itself asks only for an address (i18n/en.ts:354-365)."""
    for needle in ("Settings → Servers", "⌘R", "http://127.0.0.1:4096"):
        assert needle in APP, f"the recovery note must name {needle!r}"


# ── THE TWO WAYS A CONFIGURED PROVIDER DISAPPEARS ────────────────────────────
# Everything below was MEASURED against the real opencode 1.18.19 binary
# (opencode-linux-arm64, the same build as darwin-arm64 from the same npm version),
# run with our own start_component.sh seeding, by curling GET /provider:
#
#   config shape                         | connected | in `all`
#   -------------------------------------|-----------|---------
#   our provider block, as seeded        | YES       | YES
#   + disabled_providers: ["llama.cpp"]  | NO        | NO      <- Debi's exact symptom
#   + a dangling `model` key             | YES       | YES     (provider fine, default is not)
#   models map keyed by an MLX path      | YES       | YES     (server keeps it; the DESKTOP
#                                        |           |          splits the key and breaks)
#   models: {}                           | NO        | NO
#   project config only, no global       | YES       | YES     (the redundancy works)
#
# So a provider that IS in the config can only vanish two ways, and both are now
# repaired by the Start rather than merely reported.
def test_a_stuck_disable_is_repaired_rather_than_inherited():
    """MEASURED: with `disabled_providers: ["llama.cpp"]` the real server drops us from
    BOTH `all` and `connected` (deleted at provider/provider.ts:1644, before the models
    loop) — which renders as literally "No connected providers" in Settings and an empty
    local picker. One click on Disconnect writes it, and our merge only ever replaces the
    keys we own, so without this it would survive every restart forever."""
    g, _ = _run_seed([GGUF], extra_global={"disabled_providers": ["llama.cpp"]})
    assert "llama.cpp" not in (g.get("disabled_providers") or []), (
        "a disable of OUR provider must not survive a Start — it has no other cure")


def test_repairing_our_own_disable_leaves_everyone_elses_alone():
    g, _ = _run_seed([GGUF],
                     extra_global={"disabled_providers": ["openai", "llama.cpp"]})
    assert g["disabled_providers"] == ["openai"], (
        "we own exactly one id in that list; the user's other choices are theirs")


def test_a_non_empty_allowlist_that_omits_us_gains_us():
    """The mirror image: `enabled_providers` filters at the same site
    (provider.ts:1415-1422 `if (enabled && !enabled.has(id)) return false`)."""
    g, _ = _run_seed([GGUF], extra_global={"enabled_providers": ["openai"]})
    assert g["enabled_providers"] == ["openai", "llama.cpp"], (
        "add ourselves, never empty the list — the other entries are the user's")


def test_an_empty_allowlist_is_left_exactly_as_it_was():
    """⚠️ deliberately untouched: an empty array's meaning was inferred, never measured,
    and if it means "no allowlist" then writing one entry would disable everything else."""
    g, _ = _run_seed([GGUF], extra_global={"enabled_providers": []})
    assert g["enabled_providers"] == []


# ── the default model may never name something that does not exist ───────────
def _default_key(cfg):
    m = cfg.get("model")
    assert isinstance(m, str) and m.startswith("llama.cpp/"), f"unexpected default {m!r}"
    return m.split("/", 1)[1]


def test_a_default_model_is_never_written_dangling():
    """THE "Big Pickle" PATH. harness.yaml's runner.model is an INTENT — it can easily
    name something the registry does not carry. `defaultModel()` returns
    `parseModel(cfg.model)` UNVALIDATED when the key is set (provider.ts:1980-1981), so a
    dangling id is passed on as if it were real, and the desktop's own fallback ordering
    (`priority = ["gpt-5", "claude-sonnet-4", "big-pickle", ...]`, provider.ts:2017) is
    where OpenCode's Zen models come from."""
    g, _ = _run_seed([GGUF], want="a-model-that-was-deleted-last-week")
    assert _default_key(g) in g["provider"]["llama.cpp"]["models"], (
        "we may seed a default or leave it unset, but never point it at nothing")


def test_a_default_left_over_from_a_deleted_model_is_replaced():
    g, _ = _run_seed([GGUF], want=GGUF["id"],
                     extra_global={"model": "llama.cpp/gone-in-a-rescan"})
    assert _default_key(g) in g["provider"]["llama.cpp"]["models"]


def test_an_empty_registry_still_names_a_model_that_exists():
    """MEASURED: `models: {}` deletes the provider outright (provider.ts:1686), so the
    fallback entry is load-bearing — and the default must name IT, not a runner model
    that was never registered."""
    g, _ = _run_seed([], want="gemma-4-31B-it-uncensored-biproj-q4_k_m")
    models = g["provider"]["llama.cpp"]["models"]
    assert models, "an empty models map would delete the whole provider"
    assert _default_key(g) in models


def test_a_valid_choice_of_our_own_models_is_left_alone():
    """The seed is a seed, not an enforcement: a model the user picked inside OpenCode
    must survive a restart."""
    g, _ = _run_seed([GGUF, MLX], want=MLX["id"],
                     extra_global={"model": "llama.cpp/" + GGUF["id"]})
    assert g["model"] == "llama.cpp/" + GGUF["id"]


def test_a_choice_of_someone_elses_provider_is_left_alone():
    g, _ = _run_seed([GGUF], want=GGUF["id"],
                     extra_global={"model": "anthropic/claude-sonnet-4"})
    assert g["model"] == "anthropic/claude-sonnet-4", (
        "we only ever adjudicate defaults inside our own provider")


def test_the_repair_preserves_the_rest_of_the_users_config():
    g, _ = _run_seed([GGUF], extra_global={
        "disabled_providers": ["llama.cpp"], "theme": "opencode",
        "keybinds": {"leader": "ctrl+x"}})
    assert g["theme"] == "opencode" and g["keybinds"] == {"leader": "ctrl+x"}, (
        "the repair is a merge like every other key we touch")


def test_every_repair_announces_itself():
    """A config we silently rewrite under the user is worse than one we refuse to."""
    code = _seed_block()
    assert "REPAIRED" in code, "a repair the user cannot see is a surprise, not a fix"


# ── the self-check asks in the scope the UI asks in ──────────────────────────
def test_the_provider_check_is_directory_scoped_and_patient():
    b = branch()
    i = b.index("PROVIDER SELF-CHECK")
    seg = b[i:b.index("PYOCCHK", i)]
    assert "--data-urlencode" in seg and "directory=" in seg, (
        "the settings dialog is directory-scoped (hooks/use-providers.ts:26-32 passes "
        "explicit:true whenever a directory is known), so ask in that scope")
    assert "-m 25" in seg, (
        "MEASURED: /provider answers with the WHOLE catalogue — 193 providers, 5.2MB — "
        "so an 8s budget was one slow moment from reporting a healthy lane as broken")


def test_the_failure_line_names_the_restart_that_is_actually_needed():
    """A running OpenCode reads its config at BOOT, and ship.sh deliberately leaves
    components up — so the commonest cause of a stale answer is that this component was
    never restarted after the config changed."""
    b = branch()
    seg = b[b.index("PROVIDER SELF-CHECK"):]
    assert "not restarting" in seg or "Stop and Start" in seg
