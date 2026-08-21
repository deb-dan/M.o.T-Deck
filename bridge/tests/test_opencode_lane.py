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
    assert '"opencode": "opencode on :4096' in APP


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
