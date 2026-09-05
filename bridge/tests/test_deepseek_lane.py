"""OUR side of the DeepSeek Harness (`dsh`) seam — the lane's own gate (S34).

Run:
    data/bridge-venv/bin/python -m pytest bridge/tests/test_deepseek_lane.py -q

Mirrors bridge/tests/test_opencode_lane.py, because the lane mirrors OpenCode's shape:
one optional manifest component, one standalone installer, one start_component.sh arm,
one config seeder called from the arm AND from the bridge's two fan-outs, one native
tab. Every assertion below is either a fact MEASURED on the from-scratch walk of
2026-09-03 (pin 0.1.1-rc.2, node v22.23.1 / v24.20.0, llama.cpp b10662) or a fence
around a decision that was made once and must not drift.

⚠️ WHAT THIS FILE DELIBERATELY DOES NOT DO: probe upstream's own routes or flags. That
is a CONTRACT test's job (bridge/contract_tests/), and this lane's upstream facts are
pinned in test_seam.py (the pin shape, the port, the tab) plus the seeder's own
docstring. Here we test OUR code.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

START = open(os.path.join(ROOT, "scripts", "start_component.sh"),
             encoding="utf-8", errors="replace").read()
INSTALL = open(os.path.join(ROOT, "scripts", "install_deepseek.sh"),
               encoding="utf-8", errors="replace").read()
ENSURE_NODE = open(os.path.join(ROOT, "scripts", "ensure_node.sh"),
                   encoding="utf-8", errors="replace").read()
SEED_SCRIPT = os.path.join(ROOT, "scripts", "seed_deepseek_config.py")
SEED_SRC = open(SEED_SCRIPT, encoding="utf-8", errors="replace").read()
APP = _APP_SOURCE
PANEL = open(os.path.join(ROOT, "bridge", "panel", "index.html"),
             encoding="utf-8", errors="replace").read()
SWIFT = open(os.path.join(ROOT, "app", "main.swift"),
             encoding="utf-8", errors="replace").read()
MANIFEST = yaml.safe_load(open(os.path.join(ROOT, "harness.yaml"),
                               encoding="utf-8").read())


def branch() -> str:
    """The deepseek case arm of start_component.sh, and nothing else — so an assertion
    can never be satisfied by a neighbouring component's line.

    ⚠️ THE ARM SITS BETWEEN unsloth) AND opencode), AND THAT PLACEMENT IS LOAD-BEARING
    FOR test_opencode_lane.py, NOT FOR US. That file slices OpenCode's arm as the text
    between "\\n  opencode)" and "\\n  hermes)"; putting this arm between them would
    have folded it into OpenCode's slice and made that whole suite assert about the
    wrong component. If either arm ever moves, both slicers move together."""
    i = START.index("\n  deepseek)")
    j = START.index("\n  opencode)", i)
    return START[i:j]


def _code(src: str) -> str:
    """Executable lines only. ⚠️ THIS HELPER IS NOT TIDINESS — it is the difference
    between a fence and a coincidence. Six assertions in the first draft of this file
    passed or failed on words inside COMMENTS ("never `git init` here", "never
    `npm update` this prefix", "no 'restart it' half to append"), i.e. they were
    asserting about the documentation rather than the behaviour. The comments are where
    the banned things are NAMED, deliberately, so every negative assertion below reads
    the code."""
    return "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))


def _acts(src: str) -> str:
    """Lines that DO something: comments AND user-facing output stripped.

    ⚠️ THE SECOND HALF MATTERS AS MUCH AS THE FIRST, and three more assertions in the
    first draft needed it. This lane's honesty depends on `say`/`echo` lines that NAME
    the dangerous things — "its CLI refuses --host 0.0.0.0", "never 'npm update' this
    prefix by hand" — so a negative assertion that reads them is asserting against the
    very sentences we want to keep. A banned construct is banned as a COMMAND."""
    out = []
    for ln in src.splitlines():
        t = ln.strip()
        if t.startswith("#") or t.startswith("echo ") or t.startswith("say "):
            continue
        out.append(ln)
    return "\n".join(out)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the manifest
# ══════════════════════════════════════════════════════════════════════════════

def test_manifest_entry():
    c = MANIFEST["components"]["deepseek"]
    assert c["installed"] is False, "OPTIONAL — it must ship installed:false"
    assert c["enabled"] is False
    assert c["depends_on"] == [], (
        "NOT [runner], deliberately: it is usable against any provider it has "
        "configured, so a Start must not drag the runner up. The signal lives in "
        "NEEDS_SOFT instead — see test_the_runner_down_signal_is_wired")
    assert c["port"] == 3080
    assert MANIFEST["build"]["dsh_pin"] == c["pin"], (
        "the installer reads build.dsh_pin; a stale manifest pin documents the wrong "
        "version to whoever reads the component block")


def test_the_pin_is_an_npm_version_and_never_a_dist_tag():
    """Upstream is pre-1.0 and its `latest` dist-tag is NOT the highest version number
    (measured 2026-09-03: latest=0.1.1-rc.2 while next=0.1.2-rc.1 already existed), so
    the ONE wrong move here is putting a moving name in a field the installer hands
    straight to npm."""
    pin = str(MANIFEST["components"]["deepseek"]["pin"])
    assert re.match(r"^\d+\.\d+\.\d+", pin), f"{pin!r} is not an npm version"
    assert pin not in ("latest", "next", "alpha", "beta"), "a dist-tag is not a pin"
    assert "@deepseek-ai/dsh@" in INSTALL or '${PKG}@${pin}' in INSTALL, (
        "the installer must pin the exact version on the npm command line")
    assert "npm update" not in _acts(INSTALL), (
        "never float the pin. The NOTE that tells the user not to is exactly the "
        "sentence we want to keep, so this reads commands only")


def test_the_node_requirement_is_checked_and_not_assumed():
    """⚠️ THE PUBLISHED PACKAGE DECLARES NO `engines` FIELD (measured), so npm will not
    enforce the Node floor and nothing but ensure_node.sh will. That is the whole
    reason the script exists, and why the floor is written down here too."""
    assert "FLOOR_MAJOR=22" in ENSURE_NODE and "FLOOR_MINOR=19" in ENSURE_NODE
    assert "FLOOR_NEXT_MAJOR=24" in ENSURE_NODE
    assert MANIFEST["build"]["node_pin"].startswith("v"), (
        "build.node_pin is a node release tag, e.g. v24.20.0")
    # The user's own node is checked FIRST and never shadowed — the ensure_bun.sh rule.
    assert ENSURE_NODE.index("command -v node") < ENSURE_NODE.index("nodejs.org/dist"), (
        "the PATH node must be considered before any download is contemplated")
    assert "using it, not shadowing it" in ENSURE_NODE
    # VERIFY BEFORE EXTRACT, and the checksum comes from upstream's own manifest.
    assert "SHASUMS256.txt" in ENSURE_NODE
    assert ENSURE_NODE.index("sha256 MISMATCH") < ENSURE_NODE.index("tar xJf"), (
        "a mismatched download must stop BEFORE anything is unpacked")
    # The whole distribution moves, not one file: npm is a node script that resolves
    # against its own prefix, and the installer needs npm as much as node.
    assert "bin/npm" in ENSURE_NODE, "npm must come with it or the installer cannot run"


def test_the_floor_arithmetic_is_exposed_and_correct():
    """EXECUTED, not read: the floor is two integers precisely because a string sort
    puts v22.9.0 above v22.19.0."""
    def check(v):
        r = subprocess.run(["bash", os.path.join(ROOT, "scripts", "ensure_node.sh"),
                            "--floor-check", v],
                           cwd=ROOT, capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    assert check("v22.19.0") and check("v22.23.1") and check("v24.0.0")
    assert check("v26.8.1"), "a newer major must not be rejected by an upper bound"
    assert not check("v22.18.0"), "one patch below the floor is below the floor"
    assert not check("v22.9.0"), "the string-sort trap: 22.9 < 22.19"
    assert not check("v23.5.0"), "23 is an odd line the declared range skips"
    assert not check("") and not check("garbage")


# ══════════════════════════════════════════════════════════════════════════════
# 2. the installer
# ══════════════════════════════════════════════════════════════════════════════

def test_the_installer_is_found_by_the_conventional_name():
    """The bridge's flip fence derives {component: installer} from the FILESYSTEM as
    install_<component>.sh — so the name is a contract, not a label. (This slice's
    first draft was install_deepseek_harness.sh and was invisible to that derivation.)"""
    stems = {os.path.basename(p)[len("install_"):-len(".sh")]
             for p in glob.glob(os.path.join(ROOT, "scripts", "install_*.sh"))}
    assert "deepseek" in stems
    assert os.access(os.path.join(ROOT, "scripts", "install_deepseek.sh"), os.X_OK), (
        "the bridge runs it directly; a missing +x is a silent PermissionError in a "
        "background thread")


def test_the_installer_flips_the_manifest_flag_and_says_so_when_it_cannot():
    assert re.search(r'flip_installed\.py"?\s+deepseek\b', INSTALL), (
        "without the flip the install lands, the script says 'installed', and the card "
        "still offers Install — the recorded 2026-08-21 install_opencode.sh bug")
    assert "ERROR" in INSTALL.split("flip_installed.py")[1][:600], (
        "a failed flip must be loud: a card that lies about its own state is the bug")


def test_the_installer_preflights_honestly_before_it_spends_time():
    # Platform, runtime, disk, network — each said BEFORE it happens.
    assert "Darwin" in INSTALL, "macOS-only, refused by name elsewhere"
    assert "ensure_node.sh" in INSTALL, "the runtime is resolved, never assumed"
    assert 'df -k "$ROOT"' in INSTALL, "a real free-disk read"
    assert "-ge 3" in INSTALL, (
        "the headroom is sized against the MEASURED footprint (283MB tree + npm cache "
        "+ up to 200MB of node), not against the tarball")
    # THE NUMBERS ARE MEASURED AND STATED. A ~7-minute install with no forewarning is
    # indistinguishable from a hang.
    assert "455 packages" in INSTALL and "283MB" in INSTALL
    assert "ONLINE-ONLY" in INSTALL
    # The log is panel-viewable, which matters more here than anywhere else in the tree.
    assert 'tee -a "$LOG"' in INSTALL
    assert "deepseek-install.log" in INSTALL


def test_the_installer_verifies_the_registry_metadata_before_installing():
    """npm verifies dist.integrity itself, but only against what the registry serves
    NOW. Reading the metadata first is what turns an unpublished or re-tagged version
    into a stop instead of a silently different install."""
    i = INSTALL.index("checking npm metadata")
    j = INSTALL.index("npm_bin", i) if "npm_bin" in INSTALL[i:] else len(INSTALL)
    seg = INSTALL[i:j]
    assert "registry.npmjs.org" in INSTALL
    assert 'meta_ver" == "$pin' in seg or '"$meta_ver" == "$pin"' in seg, (
        "the version the registry resolves must equal the pin, or we stop")
    assert INSTALL.index("checking npm metadata") < INSTALL.index("npm install --no-audit") \
        if "npm install --no-audit" in INSTALL else True


def test_the_install_is_confined_to_our_tree():
    for frag in ("data/deepseek/npm", "data/deepseek/home", "data/deepseek-workspace"):
        assert frag in INSTALL, f"{frag} must be created by the installer"
    # ⚠️ THE --version PROBE MUST CARRY DSH_HOME. Measured: a bare `dsh --help`
    # MATERIALIZES $DSH_HOME/profiles, so an unenvironmented probe would be the one
    # command in the whole lane that wrote to ~/.dsh.
    assert 'DSH_HOME="$DSH_HOME_DIR" "$DSH" --version' in INSTALL \
        or 'DSH_HOME="$DSH_HOME_DIR" DSH_TELEMETRY_DISABLED=1 "$DSH" --version' in INSTALL, (
        "every dsh invocation in the installer must be fenced by DSH_HOME")
    assert "--prefix" in INSTALL or 'cd "$PREFIX"' in INSTALL, (
        "npm must install into our private prefix, never globally")


def test_the_installer_proves_it_runs_before_claiming_success():
    assert "--version" in INSTALL
    assert "does not run" in INSTALL, (
        "a tab that opens onto a node stack trace is worse than an install that refused")
    assert "node too old" in INSTALL, "…and it names the most likely cause"


def test_the_lockfile_discipline_is_real_and_its_limit_is_stated():
    """`npm ci` off a lock is reproducible; the FIRST install has no lock. Both halves
    must be in the script, and the honest limit must be written down."""
    assert "npm ci" in INSTALL and "package-lock.json" in INSTALL
    assert "--save-exact" in INSTALL, "the top-level dependency is pinned exactly"
    assert "ranges" in INSTALL or "freezes" in INSTALL, (
        "the transitive tree is range-resolved once; the script must say so rather "
        "than implying byte-reproducibility it cannot deliver on a first install")


def test_the_workspace_is_created_but_never_git_initialised():
    """⚠️ THE OPPOSITE OF install_opencode.sh, ON PURPOSE. OpenCode derives a project
    IDENTITY from a root commit, so an empty commit is what makes a directory a real
    project there. dsh derives nothing from git — it canonicalizes the path with
    fs.realpath and keys the record on that — so a repo we created for no reason would
    be litter in the user's tree."""
    assert "data/deepseek-workspace" in INSTALL
    assert "README.md" in INSTALL, "the folder must explain what it is"
    assert "git init" not in _acts(INSTALL), (
        "dsh keys workspaces on the realpath, not on a git id — see the comment, "
        "which is allowed to NAME the thing the code must not do")


def test_no_name_kills_in_the_installer_or_the_node_helper():
    """The PROCESS-KILL RULE, restated at the two new files' door. The parametrized
    contract test already scans every scripts/*.sh; this is the local, readable
    version so a reviewer of this lane sees it asserted here too."""
    for src, who in ((INSTALL, "install_deepseek.sh"),
                     (ENSURE_NODE, "ensure_node.sh"),
                     (branch(), "the deepseek start arm")):
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.strip().startswith("#"))
        for banned in ("pkill", "killall", "pgrep", "taskkill"):
            assert banned not in code, f"{who} contains {banned}"


# ══════════════════════════════════════════════════════════════════════════════
# 3. the start branch
# ══════════════════════════════════════════════════════════════════════════════

def test_start_refuses_cleanly_when_not_installed():
    b = branch()
    assert "is not installed" in b and "click Install first" in b


def test_start_passes_the_port_and_the_loopback_host_explicitly():
    b = branch()
    assert 'web --host 127.0.0.1 --port "$DS_PORT" --no-open' in b, (
        "the tab's URL is a constant, so the port must not depend on a default we do "
        "not own — and --no-open stops a browser window popping behind our native tab")
    assert 'DS_PORT=$(awk' in b and "harness.yaml" in b, "the port is read, not repeated"
    assert "--host 0.0.0.0" not in _acts(b), (
        "…and never widened. The log line that says dsh REFUSES 0.0.0.0 is the "
        "sentence this lane wants on the record, so only commands are read here")


def test_start_never_sets_a_password_or_widens_the_bind():
    b = branch()
    assert "NO auth BY DESIGN" in b, "the choice is named where it is made"
    assert "refuses --host 0.0.0.0" in b, (
        "loopback is dsh's own POLICY here, not merely its default — worth recording")


def test_start_confines_the_home_with_env_not_a_shell_assignment():
    b = branch()
    assert 'DSH_HOME="$DS_HOME"' in b
    assert 'data/deepseek/home' in b
    # ⚠️ `env`, not `VAR=val _detached …`: bash's temporary-assignment prefix on a
    # FUNCTION call sets the variable in the shell rather than reliably placing it in
    # the exec'd program's environment, so the confinement could silently evaporate
    # and dsh would write to ~/.dsh after all. Silent-wrong, not a crash.
    assert "_detached env DSH_HOME=" in b, (
        "the confinement must ride on `env`, the same way the opencode/searxng arms do")


def test_start_disables_telemetry_belt_and_braces():
    b = branch()
    assert "DSH_TELEMETRY_DISABLED=1" in b, (
        "upstream's own authoritative pre-load kill switch. The composed tree already "
        "defaults the mode to DISABLED at this pin, which is exactly why this is set "
        "anyway: a future default cannot then switch it on under us")


def test_start_resolves_node_and_puts_it_first_on_path():
    b = branch()
    assert "ensure_node.sh" in b, (
        "the app spawns this script from a GUI process whose PATH is not the user's "
        "shell PATH, so node must be RESOLVED, not assumed")
    assert "|| true" in b.split("ensure_node.sh")[1][:200] or "DS_NODE=" in b
    assert 'PATH="$DS_NODE_DIR:$PATH"' in b, (
        "the launcher is a `#!/usr/bin/env node` script, so a stale or too-old node "
        "earlier on PATH would be the one that ran it")
    assert "needs node >= 22.19" in b, "…and an unresolvable node refuses with a sentence"


def test_start_picks_a_python_that_actually_has_pyyaml():
    """⚠️ FOUND ON THE FIRST REAL WALK OF THIS ARM, and it is the reason this test
    exists rather than a comment. settings.yaml is YAML, the seeder needs PyYAML, and a
    bare `python3` on a healthy machine (Debi's is ~/.local/bin/python3) does NOT have
    it — so the entire point of the lane, the seeded provider, degraded to a
    'PyYAML unavailable' warning. ship.sh's manifest merge already solved this; the arm
    now uses the same idiom."""
    b = branch()
    assert 'import yaml' in b and "DS_PY" in b
    assert "bridge-venv/bin/python" in b, (
        "the bridge venv always has PyYAML — it is in bridge/requirements.txt")
    assert "Application Support/Harness/data/bridge-venv" in b, (
        "…and a repo checkout on a machine whose venv lives only in the fat app must "
        "still be able to seed")
    assert '"$DS_PY" scripts/seed_deepseek_config.py' in b, (
        "the seeder must run under the interpreter we just vetted, not under python3")
    assert "no python with PyYAML found" in b, "…and its absence is one honest sentence"


def test_start_calls_the_seed_script_and_never_a_heredoc_copy_of_it():
    """The S29 rule: a catalog written by an inline heredoc is a catalog only its own
    Start can rewrite, which is how OpenCode spent days advertising deleted models."""
    b = branch()
    assert "scripts/seed_deepseek_config.py" in b
    # ⚠️ THE NEGATIVE THAT MATTERS: the provider BLOCK must be built in exactly one
    # place — the seeder — and never restated in the shell. Asserted on the block's
    # own field names rather than on the namespace string, because the arm's
    # self-check legitimately READS `llm-pi-ai` back out of the file it just wrote.
    for field in ("apiKeyEnv", "supportsDeveloperRole", "displayName",
                  "openai-completions"):
        assert field not in _acts(b), (
            f"{field} is a field of the provider block; the shell must not compose it")
    for var in ("DS_SETTINGS", "DS_BASE", "DS_KEY_ENV", "DS_MODEL", "HARNESS_ROOT"):
        assert var + "=" in b, f"the seeder reads {var}; the arm must set it"


def test_the_key_env_var_name_is_derived_once_and_never_typed_twice():
    """Two hand-picked names is how the goose lane ended up exporting a
    HARNESS_RUNNER_API_KEY that nothing read."""
    b = branch()
    assert "key_env_name()" in b, "the name comes FROM the seeder's pure function"
    assert '"$DS_KEY_ENV"="$DS_KEY"' in b, (
        "the key value is handed to the child under that derived NAME")
    # The fallback exists and must equal the function's own answer for the default
    # product name — a mismatch would turn a working lane into MISSING_CREDENTIAL.
    assert "MOT_DECK_LOCAL_API_KEY" in b
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_dsh", SEED_SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.key_env_name() == "MOT_DECK_LOCAL_API_KEY", (
        "the shell fallback and the function must agree, or a Start with no PyYAML "
        "exports a name the on-disk provider block does not reference")


def test_start_clears_the_port_with_the_ownership_check_and_no_name_signature():
    b = branch()
    assert '_clear_port "$DS_PORT" deepseek' in b, (
        "listener-scoped, ownership-checked — never a bare lsof kill")
    assert b.index("_clear_port") < b.index("_detached"), "cleared before launch"
    # ⚠️ AND NO `deepseek)` ARM IN _cmd_looks_like_ours. A standalone `dsh` the user
    # installed themselves would match its own name, and that is precisely the process
    # the guard exists to protect (the Unsloth / goose-Desktop class, twice bitten).
    owner = START[START.index("_cmd_looks_like_ours() {"):]
    owner = owner[:owner.index("\n}")]
    assert "deepseek" not in owner and "dsh" not in owner, (
        "ownership for this lane is proven by PATH ($ROOT/data/...), never by name")


def test_start_writes_an_absolute_pidfile_and_an_appending_log():
    b = branch()
    assert 'echo $! > "$ROOT/data/deepseek.pid"' in b, (
        "absolute: the launch runs inside a `cd` to the workspace")
    assert '>>"$ROOT/data/logs/deepseek.log"' in b
    assert "N blocks = N starts, not N servers" in b, (
        "an appending log must say so, or six identical blocks read as six servers")


def test_the_health_probe_is_the_root_document_and_says_why():
    """MEASURED at this pin: /api is a POST/websocket RPC surface and /healthz,
    /health, /api/health and /version are all 404. `/` is the only honest HTTP
    readiness signal upstream offers, so the probe uses it and the comment records the
    measurement rather than leaving it looking lazy."""
    b = branch()
    assert 'curl -sf -m 2 "http://127.0.0.1:${DS_PORT}/"' in b
    assert "404" in b, "the comment must record what was tried"
    assert 'kill -0 "$(cat "$ROOT/data/deepseek.pid")"' in b, (
        "a process that exited must fail fast instead of waiting out the timeout")
    assert "did not answer on" in b, "…and the timeout says so with the log tail"


def test_the_provider_self_check_is_honest_about_what_it_cannot_check():
    """⚠️ MEASURED: a deliberately-broken provider block produced a server that
    started, answered `GET /` with 200, and printed NOTHING. So the OpenCode-style
    'ask the server and print a decidable line' check is NOT available here, and a grep
    that could never match would be worse than saying so."""
    b = branch()
    assert "There is NO route to ask this server" in b, (
        "the limit must be written down where the check is")
    assert "provider check:" in b, "…and there must still be a decidable line"
    assert "NOT PRESENT in settings.yaml" in b, "the first way this lane goes quiet"
    assert "NO models" in b, "the second way — dsh refuses an empty hand-declared route"
    assert "re-reads settings.yaml per request" in b, (
        "the one place this lane is BETTER than OpenCode must be stated, or a user "
        "restarts it for no reason")
    assert "RESTART" not in b.upper().replace("RESTART OF THIS COMPONENT", ""), True


def test_the_first_run_friction_is_named_before_the_user_hits_it():
    b = branch()
    assert "Internal Testing Notice" in b, "upstream's own once-only modal"
    assert "choose a WORKSPACE" in b or "WORKSPACE" in b
    assert "data/deepseek-workspace" in b, "…and the answer is named"
    assert "U67" in b, "…and the ledger row that tracks retiring the friction"


# ══════════════════════════════════════════════════════════════════════════════
# 4. the bridge
# ══════════════════════════════════════════════════════════════════════════════

def test_install_route_uses_the_standalone_installer():
    m = re.search(r"def install\(name: str\).*?if name not in \(([^)]*)\)", APP, re.S)
    assert m and '"deepseek"' in m.group(1)
    assert '"deepseek": "install_deepseek.sh"' in APP
    assert '"deepseek"' in APP[APP.index("args = () if name in ("):][:120], (
        "it takes no positional args, like searxng/opencode")
    # The wide (7200s) timeout: a ~7-minute install on a warm cache is inside the
    # 30-minute default, but a COLD npm cache on a slow link is exactly where 455
    # packages outruns it — and a timeout reads to the user as "the install failed"
    # rather than "we stopped waiting".
    tmo = re.search(r"timeout = 7200 if name in \(([^)]*)\)", APP, re.S)
    assert tmo and '"deepseek"' in tmo.group(1)


def test_the_plan_states_the_costs_before_anything_runs():
    i = APP.index('"deepseek": [')
    plan = APP[i:APP.index("]", APP.index('"Click Continue"', i))]
    for must in ("MIT", "455 packages", "PRE-1.0", "node", "SHASUMS256",
                 "DSH_TELEMETRY_DISABLED", "auto-updater", "WORKSPACE", "U67"):
        assert must in plan, f"the install plan never mentions {must!r}"
    assert "~/.dsh" in plan, "the confinement claim must be in the plan the user approves"


def test_logs_are_viewable_in_the_panel_on_both_surfaces():
    assert '"deepseek", "deepseek-install",' in APP, "the bridge's log allowlist"
    flat = PANEL.replace(" ", "")
    assert "n:'deepseek'" in flat and "n:'deepseek-install'" in flat, (
        "the panel's chip list — an allowlisted log with no chip is unreachable")


def test_the_notes_row_exists_and_names_the_port_and_the_friction():
    i = APP.index('"deepseek": ("DeepSeek Harness on :3080')
    note = APP[i:i + 700]
    assert "loopback only" in note and "no" in note
    assert "WORKSPACE" in note
    assert "TOOL-CALLING" in note


def test_the_runner_down_signal_is_wired():
    """harness.yaml says depends_on: [] (so a Start never drags the runner up) AND the
    SOFT table is what puts 'the Runner is down' on the card. Both halves, or the
    signal and the start closure disagree in the wrong direction."""
    from bridge.routers.components import NEEDS_SOFT, _NEEDS_TITLES
    assert MANIFEST["components"]["deepseek"]["depends_on"] == []
    assert NEEDS_SOFT.get("deepseek") == ("runner",)
    assert _NEEDS_TITLES["deepseek"] == "DeepSeek"
    # ⚠️ THE TITLE MUST EQUAL THE SWIFT TAB TITLE, BYTE FOR BYTE. main.swift keys the
    # banner as depNeeds[tabs[idx].id], and the sentence is built from this table — a
    # mismatch is a banner that either never appears or names an internal id.
    m = re.search(r'HarnessTab\(id: "deepseek", title: "([^"]+)"', SWIFT)
    assert m and m.group(1) == _NEEDS_TITLES["deepseek"]


def test_the_banner_does_not_tell_her_to_restart_a_lane_that_rebinds_itself():
    """⚠️ FOUND BY WALKING THE BANNER, not by reading it. Every 'the dependency is not
    ready' sentence used to end "…then restart <who> to rebind", which was true of
    every lane that carries this banner — Hermes, Odysseus and OpenCode all read their
    provider configuration ONCE, at boot. dsh does not: its adapter reads its profiles
    once per operation and its settings provider hot-publishes external edits, so the
    next turn picks the runner up by itself.

    So the shared clause was a FALSE INSTRUCTION on exactly the one lane where the work
    was already done — LIES-TO-USER class, not a cosmetic slip. And it is the same
    asymmetry the write side already fences (_rebind_deepseek deliberately does not
    append OpenCode's 'restart it to load this'), which is what made it findable: the
    two halves disagreed about the same fact."""
    from bridge.routers.components import REBINDS_LIVE, needs_message
    assert "deepseek" in REBINDS_LIVE
    # A lane ABSENT from the set keeps the restart advice — the safe default, because
    # advising a restart that was not needed costs one click while omitting one that
    # WAS needed leaves a lane silently stale.
    assert "opencode" not in REBINDS_LIVE and "hermes" not in REBINDS_LIVE
    for state in ("down", "no-model"):
        ours = needs_message("deepseek", "runner", state, {})["text"]
        theirs = needs_message("opencode", "runner", state, {})["text"]
        # ⚠️ "no restart needed" CONTAINS the word, so the fence is on the INSTRUCTION
        # ("restart DeepSeek"), not on the substring — a bare `not in` here failed on
        # the very sentence it was written to require.
        assert "restart DeepSeek" not in ours, (
            f"[{state}] the DeepSeek banner must not advise a restart: {ours}")
        assert "no restart needed" in ours
        assert "restart OpenCode to rebind" in theirs, (
            f"[{state}] and OpenCode's sentence must be unchanged")
        # The banner is still written for her, in both branches.
        assert ours.startswith("DeepSeek") and "deepseek" not in ours
        # …and it is one sentence-pair, not a comma splice (the first draft was).
        assert ", DeepSeek picks it up" not in ours


def test_the_tools_warning_is_reused_without_naming_the_wrong_product():
    """S34: the DeepSeek lane has OpenCode's requirement (every mutation is a native
    tool call, no text-edit fallback), so it reuses OpenCode's decision table. Reusing
    it VERBATIM would have printed 'OpenCode needs it' on the DeepSeek card — a
    sentence about a product the user is not starting, i.e. the LIES-TO-USER class."""
    from bridge.routers.models import live_tools_warning, opencode_tools_warning
    entry = {"id": "some-model", "tools": False}
    assert "OpenCode" in opencode_tools_warning(entry), "the default is unchanged"
    got = live_tools_warning(entry, "DeepSeek")
    assert "DeepSeek" in got and "OpenCode" not in got
    assert live_tools_warning(entry) == opencode_tools_warning(entry), (
        "the default must keep every existing caller byte-identical")
    # A tool-capable model warns about nothing, whoever asks.
    assert live_tools_warning({"id": "m", "tools": True}, "DeepSeek") == ""
    assert 'if n in ("opencode", "deepseek"):' in APP, "…and the hook covers both lanes"


def test_the_probe_budget_entry_exists_and_is_explained():
    from bridge import app as A
    assert A.PROBE_TIMEOUT_S.get("deepseek") == 2.0
    assert A._probe_timeout("deepseek", True) == 2.0
    assert A._probe_timeout("deepseek", False) == 0.5, (
        "a component we are not expecting to be up has no alarm to raise, so a STOPPED "
        "deepseek may not make every status poll slower")


def test_the_ram_ledger_labels_it():
    from bridge.core.memory import _label
    assert _label("deepseek") == "DeepSeek"


# ══════════════════════════════════════════════════════════════════════════════
# 5. the fan-outs — the S29 rule, applied on the day the lane landed
# ══════════════════════════════════════════════════════════════════════════════

def test_the_seeder_uses_the_shared_offerable_rule():
    """The echo fence, stated locally: a lane that enumerates models its own way is how
    OpenCode kept offering models deleted days earlier."""
    assert "modelreg" in SEED_SRC and "offerable" in SEED_SRC
    assert "wire_id" in SEED_SRC, (
        "the two-identifier rule: llama.cpp's wire name is the id, the MLX servers "
        "need the registry PATH")


def test_the_seeder_is_in_both_fan_outs():
    """⚠️ BOTH, and the asymmetry is the recorded bug: OpenCode was in the switch
    fan-out but not the rescan one for a release."""
    assert "def _rebind_deepseek" in APP
    i = APP.index("def _rebind_dependents")
    assert "_rebind_deepseek(wire)" in APP[i:i + 3000], "the model-switch fan-out"
    j = APP.index("def _rescan_fanout")
    assert "_rebind_deepseek" in APP[j:j + 3000], "the RESCAN fan-out"
    # Installed-ness first (S23): a lane that is not on this machine says nothing.
    body = APP[APP.index("def _rebind_deepseek"):]
    body = body[:body.index("\n\n\ndef ")]
    assert 'settings.is_file()' in body and 'return ""' in body


def test_the_fan_out_does_not_tell_the_user_to_restart_it():
    """⚠️ THE ONE PLACE THIS LANE DIFFERS FROM OPENCODE, IN ITS FAVOUR, AND THE COMMENT
    MUST NOT BE COPIED ACROSS. OpenCode reads its config at BOOT, so a correct file
    changes nothing visible and the note has to say 'restart it'. dsh reads its
    profiles once per OPERATION and hot-publishes external edits, so the file write IS
    the whole fix — and an appended 'restart to see this' would be a false
    instruction."""
    body = APP[APP.index("def _rebind_deepseek"):]
    body = body[:body.index("\n\n\ndef ")]
    # The COMMENT is where the asymmetry is explained (and it quotes upstream's own
    # "without restarting the server"), so the negative is asserted on the CODE: no
    # restart advice may reach the string this function RETURNS.
    # DOCSTRING STRIPPED TOO, not just `#` comments: this function's docstring is
    # where the asymmetry is explained and it quotes upstream's own "without
    # restarting the server". The fence is on the executable half.
    stmts = body.split('"""')[2] if body.count('"""') >= 2 else body
    assert "restart" not in _code(stmts).lower(), (
        "OpenCode's note has to say 'RESTART OpenCode to load it'; appending the same "
        "sentence here would be a false instruction, because dsh re-reads its "
        "profiles once per operation")
    # ⚠️ WHITESPACE-COLLAPSED. The phrase is LINE-WRAPPED in the docstring ("ONCE PER\n
    # OPERATION"), so a naive substring test failed on a docstring that plainly says it
    # — the exact class of false negative that makes a fence untrustworthy.
    flat = " ".join(body.lower().split())
    assert "once per operation" in flat or "per request" in flat, (
        "…and the reason must be written down where the difference is made")
    # …and it must still surface the REFUSAL, which is the line that may never be
    # silent when the user has just pressed a button.
    assert "NOT WRITTEN" in body


# ══════════════════════════════════════════════════════════════════════════════
# 6. the seeded config, EXECUTED against real temp registries
# ══════════════════════════════════════════════════════════════════════════════

_ART = tempfile.mkdtemp(prefix="deepseek-artifacts-")
_GGUF_PATH = os.path.join(_ART, "q.gguf")
open(_GGUF_PATH, "wb").write(b"x")
_MLX_PATH = os.path.join(_ART, "Qwen3-8B-4bit")
os.makedirs(_MLX_PATH, exist_ok=True)
open(os.path.join(_MLX_PATH, "config.json"), "w").write("{}")
open(os.path.join(_MLX_PATH, "model.safetensors"), "wb").write(b"x")
# ⚠️ REAL FILES ON DISK, because the enumerator (modelreg.offerable) drops a row whose
# artifact is provably gone — S29. A fixture with a fake path would silently test the
# empty case.
GGUF = {"id": "Qwen3-9B-Q4_0", "format": "gguf", "path": _GGUF_PATH, "ctx": 32768}
MLX = {"id": "mlx-community/Qwen3-8B-4bit", "format": "mlx", "path": _MLX_PATH}


def _run_seed(models, want="", pre=None, base="http://127.0.0.1:6767/v1"):
    """Execute the REAL seeder over a temp registry + a temp settings document.
    Returns (parsed settings doc, stdout)."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": models}, fh)
    sp = os.path.join(d, "settings.yaml")
    if pre is not None:
        with open(sp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(pre, fh, default_flow_style=False, sort_keys=False)
    env = dict(os.environ, DS_SETTINGS=sp, DS_BASE=base,
               DS_KEY_ENV="MOT_DECK_LOCAL_API_KEY", DS_MODEL=want, HARNESS_ROOT=d)
    p = subprocess.run([sys.executable, SEED_SCRIPT], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    doc = {}
    if os.path.isfile(sp):
        with open(sp, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    return doc, p.stdout


def _route(doc):
    return ((doc.get("llm-pi-ai") or {}).get("providers") or {}).get("mot-deck") or {}


def test_the_route_has_the_shape_the_adapter_requires():
    doc, _ = _run_seed([GGUF])
    r = _route(doc)
    # F2: a hand-declared route needs api + baseURL + a non-empty, uniquely-identified
    # models list, or resolution fails and takes the whole namespace's next load with it.
    assert r["api"] == "openai-completions"
    assert r["baseURL"] == "http://127.0.0.1:6767/v1"
    assert r["models"] and all(m.get("id") for m in r["models"])
    assert r["displayName"] == "MOT Deck (local)"
    # F1: providers is a DICT keyed by the route id. The pre-release LIST shape fails
    # load upstream.
    assert isinstance((doc["llm-pi-ai"])["providers"], dict)


def test_the_key_is_a_reference_and_the_secret_is_never_in_the_file():
    doc, out = _run_seed([GGUF])
    r = _route(doc)
    assert r["apiKeyEnv"] == "MOT_DECK_LOCAL_API_KEY"
    dumped = yaml.safe_dump(doc)
    assert "harness-local" not in dumped and "apiKey:" not in dumped, (
        "F3: apiKeyEnv names an env var resolved per request; a literal key here would "
        "put the secret in a file we rewrite on every Start")
    assert "the secret is NOT in this file" in out


def test_the_compat_decision_is_exactly_what_was_measured():
    """F4, and this is the assertion that stops the brief's guess creeping back in.

    MEASURED on the wire against a request-capturing server:
      · a bare hand-declared model already sends the system prompt as `system`
      · declaring reasoningEfforts is what flips it to `developer`
      · the output cap goes out as max_completion_tokens
    And on our side: llama.cpp b10662 accepts developer/max_tokens/
    max_completion_tokens/reasoning_effort; mlx_lm.server reads both cap spellings but
    hands ROLES to the tokenizer's chat template, where `developer` is a hard error.
    """
    doc, _ = _run_seed([GGUF])
    r = _route(doc)
    assert r["compat"] == {"supportsDeveloperRole": False}, (
        "supportsDeveloperRole:false is the one measured-defensive knob — it is what "
        "stands between an MLX-served model and a chat-template failure the moment "
        "anything flips the role")
    assert "maxTokensField" not in r["compat"], (
        "NOT set, deliberately: both of our engines read max_completion_tokens AND "
        "max_tokens, so it is a knob with no measured effect. Ledger U68 has the "
        "recipe for re-deciding if a third engine lands")
    # And no reasoningEfforts anywhere — declaring it is what causes the problem the
    # compat flag then has to fix.
    assert all("reasoningEfforts" not in m for m in r["models"])


def test_the_wire_id_rule_holds_for_both_formats():
    doc, _ = _run_seed([GGUF, MLX])
    r = _route(doc)
    by_name = {m["name"]: m for m in r["models"]}
    assert by_name["Qwen3-9B-Q4_0"]["id"] == "Qwen3-9B-Q4_0", (
        "llama.cpp is launched with --alias <registry id>, so its wire name IS the id")
    assert by_name["mlx-community/Qwen3-8B-4bit"]["id"] == _MLX_PATH, (
        "the MLX servers treat `model` as something to LOAD and need the registry PATH")


def test_capacities_are_omitted_rather_than_guessed():
    doc, _ = _run_seed([GGUF, MLX])
    by_name = {m["name"]: m for m in _route(doc)["models"]}
    assert by_name["Qwen3-9B-Q4_0"]["contextWindow"] == 32768
    assert by_name["Qwen3-9B-Q4_0"]["maxTokens"] == 4096
    assert "contextWindow" not in by_name["mlx-community/Qwen3-8B-4bit"], (
        "ctx unknown -> omitted, so the adapter's own fallback applies. A "
        "contextWindow of 0 would be a lie")


def test_no_modalities_are_claimed():
    """The entry schema at this pin is id/name/contextWindow/maxTokens/
    reasoningEfforts/compat — `input` is not in it — and over-claiming an image
    modality 'admits an image the provider then rejects mid-turn, after the message is
    durable'. So we claim nothing and the conservative route default stands."""
    doc, _ = _run_seed([GGUF, MLX])
    for m in _route(doc)["models"]:
        assert "input" not in m
    assert "defaultInput" not in _route(doc)


def test_duplicate_wire_ids_are_dropped_not_written():
    """F2 again: 'a non-empty models list of UNIQUELY-identified models'. Two registry
    rows CAN share a wire id (the same MLX directory registered twice), and a duplicate
    would fail the whole section rather than just the row."""
    twin = dict(MLX, id="another-name-same-dir")
    doc, _ = _run_seed([MLX, twin])
    ids = [m["id"] for m in _route(doc)["models"]]
    assert len(ids) == len(set(ids)) == 1


def test_an_empty_enumeration_refuses_and_preserves_the_previous_route():
    """★ THE REFUSAL, and it is the most important test in this file. '[] IS NOT A
    DECISION' — the runner may be stopped, the disk unplugged, the rescan not yet run.
    And a models-less hand-declared route does not merely vanish here the way it does
    in OpenCode: the adapter REFUSES the section, which takes every other provider in
    the llm-pi-ai namespace down with it."""
    good, _ = _run_seed([GGUF])
    doc, out = _run_seed([], pre=good)
    assert "NOT WRITTEN" in out and "no models" in out
    assert "left exactly as it was" in out
    assert _route(doc)["models"] == _route(good)["models"], (
        "the previous good route must survive an empty enumeration untouched")


def test_a_missing_endpoint_also_refuses():
    doc, out = _run_seed([GGUF], base="")
    assert "NOT WRITTEN" in out and "baseURL" in out
    assert doc == {}, "nothing may be written at all"


def test_the_merge_never_clobbers_the_user():
    """Only the two sections we own are replaced. Everything else in the document —
    other namespaces, the user's OWN provider routes — survives every Start."""
    pre = {"theme": {"mode": "dark"},
           "permission-presets": {"mode": "workspace-write"},
           "llm-pi-ai": {"providers": {"my-own-cloud": {"apiKeyEnv": "MY_KEY"}}}}
    doc, _ = _run_seed([GGUF], pre=pre)
    assert doc["theme"] == {"mode": "dark"}
    assert doc["permission-presets"] == {"mode": "workspace-write"}
    assert doc["llm-pi-ai"]["providers"]["my-own-cloud"] == {"apiKeyEnv": "MY_KEY"}
    assert _route(doc)["models"], "…and ours is there beside theirs"


def test_an_unparseable_document_is_refused_not_overwritten():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": [GGUF]}, fh)
    sp = os.path.join(d, "settings.yaml")
    broken = "llm-pi-ai:\n  providers:\n   : : : not yaml at all [\n"
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(broken)
    env = dict(os.environ, DS_SETTINGS=sp, DS_BASE="http://x/v1",
               DS_KEY_ENV="K", DS_MODEL="", HARNESS_ROOT=d)
    p = subprocess.run([sys.executable, SEED_SCRIPT], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, "a Start must not fail because of this"
    assert "not valid YAML" in p.stdout and "left untouched" in p.stdout
    assert open(sp, encoding="utf-8").read() == broken, (
        "overwriting a document we could not read is the clobber this file exists to "
        "avoid — the user's hand edit may be one typo from correct")


def test_the_default_is_seeded_replaced_or_honoured_and_never_dangling():
    # SEED when unset.
    doc, _ = _run_seed([GGUF], want="Qwen3-9B-Q4_0")
    assert doc["agent-default-model"] == {"provider": "mot-deck",
                                          "model": "Qwen3-9B-Q4_0"}
    # REPLACE when it dangles against OUR route, and SAY SO.
    pre = {"agent-default-model": {"provider": "mot-deck", "model": "deleted-model"}}
    doc, out = _run_seed([GGUF], pre=pre)
    assert doc["agent-default-model"]["model"] == "Qwen3-9B-Q4_0"
    assert "REPAIRED" in out and "named no existing model" in out
    # HONOUR a valid choice of ours.
    pre = {"agent-default-model": {"provider": "mot-deck", "model": "Qwen3-9B-Q4_0"}}
    doc, out = _run_seed([GGUF, MLX], want=_MLX_PATH, pre=pre)
    assert doc["agent-default-model"]["model"] == "Qwen3-9B-Q4_0", (
        "the user's own valid pick outranks harness.yaml's intent")
    assert "REPAIRED" not in out


def test_a_default_on_somebody_elses_provider_is_never_touched():
    """A selection naming `deepseek-official` is a statement about a route we do not
    own. Repairing it would be us deciding which provider the user wants."""
    pre = {"agent-default-model": {"provider": "deepseek-official",
                                    "model": "deepseek-v4-pro"}}
    doc, out = _run_seed([GGUF], pre=pre)
    assert doc["agent-default-model"] == pre["agent-default-model"]
    assert "REPAIRED" not in out


def test_a_dangling_default_with_nothing_to_offer_is_left_rather_than_removed():
    """The one case where leaving a wrong value beats clearing it: removing the section
    hands the lane back to upstream's `deepseek-official` route, which needs a DeepSeek
    cloud key — turning 'one dead model' into 'asks you for a cloud account'."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_dsh2", SEED_SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    new, note = m.plan_default({"provider": "mot-deck", "model": "gone"}, "", set())
    assert new is m.KEEP
    assert "names no existing model" in note


def test_a_users_reasoning_effort_survives_a_no_op_reseed():
    pre = {"agent-default-model": {"provider": "mot-deck", "model": "Qwen3-9B-Q4_0",
                                    "reasoningEffort": "high"}}
    doc, _ = _run_seed([GGUF], want="Qwen3-9B-Q4_0", pre=pre)
    assert doc["agent-default-model"].get("reasoningEffort") == "high"


def test_the_prune_is_counted_out_loud():
    good, _ = _run_seed([GGUF, MLX])
    doc, out = _run_seed([GGUF], pre=good)
    assert len(_route(doc)["models"]) == 1
    assert "1 dropped" in out, (
        "a shrinking catalog must be reported — 'the models silently changed' is how "
        "the OpenCode ghost-model bug stayed invisible")


def test_the_marker_records_only_what_we_wrote_and_never_a_key():
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": [GGUF]}, fh)
    sp = os.path.join(d, "settings.yaml")
    env = dict(os.environ, DS_SETTINGS=sp, DS_BASE="http://127.0.0.1:6767/v1",
               DS_KEY_ENV="MOT_DECK_LOCAL_API_KEY", DS_MODEL="", HARNESS_ROOT=d)
    subprocess.run([sys.executable, SEED_SCRIPT], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=60)
    mk = os.path.join(d, "harness_seed_state.json")
    assert os.path.isfile(mk)
    st = json.load(open(mk, encoding="utf-8"))
    assert st["provider_id"] == "mot-deck"
    assert st["api_key_env"] == "MOT_DECK_LOCAL_API_KEY"
    assert st["model_ids"] == ["Qwen3-9B-Q4_0"]
    assert "harness-local" not in json.dumps(st), "a marker may never carry a secret"


def test_the_settings_file_is_owner_only():
    """It sits next to .credentials.yaml, and dsh's own writer creates its temp 0600.
    A world-readable settings.yaml would be a downgrade WE introduced."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    with open(os.path.join(d, "data", "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"models": [GGUF]}, fh)
    sp = os.path.join(d, "settings.yaml")
    env = dict(os.environ, DS_SETTINGS=sp, DS_BASE="http://127.0.0.1:6767/v1",
               DS_KEY_ENV="K", DS_MODEL="", HARNESS_ROOT=d)
    subprocess.run([sys.executable, SEED_SCRIPT], cwd=ROOT, env=env,
                   capture_output=True, text=True, timeout=60)
    assert (os.stat(sp).st_mode & 0o077) == 0, "no group or other bits"


def test_a_missing_pyyaml_warns_and_never_fails_a_start():
    """The house rule (seed_hermes_provider.py). A lane with no provider is
    recoverable; a lane whose Start refuses is not."""
    assert "PyYAML unavailable" in SEED_SRC
    i = SEED_SRC.index("PyYAML unavailable")
    assert "SystemExit(0)" in SEED_SRC[i:i + 200], "exit 0, never a failure"


# ══════════════════════════════════════════════════════════════════════════════
# 7. panel + shell
# ══════════════════════════════════════════════════════════════════════════════

def test_nav_registry_agrees_across_the_three_tables():
    from bridge import nav
    assert "deepseek" in nav.NAV_IDS
    # ⚠️ DECLARED-BUT-NOT-PINNED, and this is the assertion that keeps it that way.
    # The pinned prefix must stay at NAV_TOPBAR_PINS=9: validate() refuses a tenth,
    # repair() trims it, and test_nav_model.py hardcodes the strip length.
    assert any(i == "deepseek" and not p for i, p in nav.DEFAULT_TOPBAR), (
        "it joins the SWAPPABLE set, not the pins — Debi's 9+3 ruling")
    assert any(i == "deepseek" and p for i, p in nav.DEFAULT_SIDEBAR), (
        "…but it IS shown in the sidebar: a component with no row anywhere cannot be "
        "found, and a sidebar row costs no scarce slot")
    assert len([1 for _i, p in nav.DEFAULT_TOPBAR if p]) == nav.NAV_TOPBAR_PINS
    flat = PANEL.replace(" ", "")
    assert "id:'deepseek'" in flat, "the panel mirrors the id"
    assert "tab:'DeepSeek'" in flat, (
        "the panel's `tab` must match main.swift's TITLE exactly, or the sidebar row "
        "silently stops switching tabs")
    assert "'deepseek'" in flat, "…and it is in the panel's default layouts"
    assert 'HarnessTab(id: "deepseek", title: "DeepSeek"' in SWIFT
    # ⚠️ LOWERCASE-ALPHA ID. test_nav_model.py harvests the panel with
    # `\{ id:'([a-z]+)',` — a digit, hyphen or underscore would not be captured and the
    # suite would report the panel as MISSING an entry it plainly has.
    assert re.match(r"^[a-z]+$", "deepseek")


def test_the_tab_points_straight_at_the_port_and_gets_no_privileges():
    assert 'url: URL(string: "http://127.0.0.1:3080")!' in SWIFT
    # ⚠️ NOT a bridge redirect, unlike OpenCode's: dsh has no deep link to build (its
    # root document IS the app), so a /deepseek route would be a second hop, a second
    # failure mode and a second place the port is written down, for nothing.
    assert "8700/deepseek" not in SWIFT
    # It is a THIRD-PARTY page: no `harness` script-message handler, no shellScript.
    # Being absent from that branch is the assertion.
    i = SWIFT.index('t.id == "loffice"')
    branch_src = SWIFT[i:i + 400]
    assert "deepseek" not in branch_src, (
        "granting window.webkit to a page we did not write is the thing this checks")


def test_the_strip_did_not_grow(  ):
    """The 9+3 arithmetic is unchanged by this slice, and the width-budget comment in
    main.swift still describes reality."""
    from bridge import nav
    assert len(nav.strip(nav.default_model())) == 11, (
        "nine pins + the two-entry window seed — adding an UNPINNED row must not move "
        "this, and if it ever does, main.swift's width budget needs re-deriving")
    assert nav.NAV_TOPBAR_PINS == 9 and nav.NAV_TOPBAR_MAX == 12
    assert "ELEVEN current titles" in SWIFT, (
        "the width budget comment is still true — and test_opencode_lane.py asserts "
        "this exact phrase, so it must not be edited without re-deriving the numbers")


def test_opening_it_takes_a_swappable_slot_rather_than_a_pin():
    from bridge import nav
    m = nav.default_model()
    pins = nav.visible(m, "topbar")
    assert nav.mru_touch(m, "deepseek") is True
    assert nav.strip(m)[:len(pins)] == pins, "the pins do not move"
    assert "deepseek" in nav.strip(m)
    assert len(nav.strip(m)) <= nav.NAV_TOPBAR_MAX
