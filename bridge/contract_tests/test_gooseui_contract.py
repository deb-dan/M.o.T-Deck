"""UPSTREAM's side of the GOOSE UI (embed) seam — the gate a goose bump must pass.

Built to docs/research/2026-08-29-goose-desktop-ui.md. This lane serves goose Desktop's
OWN renderer bundle and supplies the Electron preload contract ourselves, which makes it
the most drift-exposed thing in the tree: upstream can add a `window.electron.<x>` call
in any release and our page would then die on `x is not a function` inside a tab, with
no server-side error anywhere. So the contract is pinned four ways, and every part that
needs the vendored bundle SKIPS CLEANLY when it is not extracted (a checkout without
goose Desktop installed must not turn the gate red):

  1. BY DIGEST — the vendored bundle's sha manifest is RECOMPUTED from the files on disk
     and compared to the BUNDLE line. This is what makes "unmodified" a checked claim
     rather than a promise in a comment.
  2. BY CENSUS — every `window.electron.<name>` the REAL renderer bundle calls must be a
     name our shim defines. This is the test that earns its keep: it reads upstream's
     shipped JavaScript, so a bump that adds a preload method fails HERE instead of in
     Debi's tab.
  3. BY SHAPE — the ACP route (`ws://…/acp?token=…`), the `serve` argv, and the fence's
     two homes. The URL builder is main.js's own; the two homes are the whole reason the
     PTY lane and this one can coexist.
  4. BY REGISTRATION — the lane is in BOTH bridge/app.py's _LANES and bridge/appsrc.py's
     FILES. A lane missing from appsrc's view makes every `not in` assertion in ~40 test
     files pass VACUOUSLY, which is the manifest rule this repo already learned once.

Run: pytest bridge/contract_tests/test_gooseui_contract.py -q
"""
import hashlib
import glob
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UI = os.path.join(ROOT, "data", "goose", "ui")
MANIFEST = os.path.join(ROOT, "data", "goose", "ui.sha256")
INSTALLER = os.path.join(ROOT, "scripts", "install_goose_ui.sh")

# The pin, restated here so this file reads on its own. ASSERTED against the module and
# the extractor below rather than trusted.
PIN_APP_VERSION = "1.48.0"
PIN_ASAR_SHA256 = "9f9f9db4a0d47a1774c86a109f19a2fd0257401726eabc0237dcb0e9b2ad9903"
PIN_BUNDLE_SHA256 = "342d291ddc8c41d923e15760e56164ef8e331a2dcde0769b0c476e6907d8acd0"

import sys
sys.path.insert(0, ROOT)
from bridge import gooseui as G                                      # noqa: E402

_HAVE_BUNDLE = os.path.isfile(os.path.join(UI, "index.html"))
_needs_bundle = pytest.mark.skipif(
    not _HAVE_BUNDLE,
    reason="the goose UI bundle is not installed here — run scripts/install_goose_ui.sh")


# ── 1. the pin, in all three places ──────────────────────────────────────────
def test_pin_matches_the_installer():
    """The module quotes the pin so the status route can name it without shelling out.
    A drift between the two would let a re-extraction land a DIFFERENT app's renderer
    while every surface still claims 1.48.0."""
    src = open(INSTALLER, encoding="utf-8").read()
    assert f'APP_VERSION="{PIN_APP_VERSION}"' in src
    assert f'ASAR_SHA256="{PIN_ASAR_SHA256}"' in src
    assert f'UI_ASSET_SHA256="{G.PIN_ASSET_SHA256}"' in src
    assert f'UI_ASSET_SIZE="{G.PIN_ASSET_SIZE}"' in src
    assert f'UI_ASSET="{G.PIN_ASSET}"' in src
    assert f'BUNDLE_SHA256="{PIN_BUNDLE_SHA256}"' in src
    assert G.PIN_APP_VERSION == PIN_APP_VERSION
    assert G.PIN_ASAR_SHA256 == PIN_ASAR_SHA256
    assert G.PIN_BUNDLE_SHA256 == PIN_BUNDLE_SHA256
    # ⚠️ doctrine 2b: the installer must NOT source the artifact from a copy already on
    # this Mac. A local source silently exempts the install journey from ever running —
    # which is exactly what happened in this spike's first hour.
    code = _code_only(INSTALLER)
    for local in ("Downloads", "/Applications", "PlistBuddy"):
        assert local not in code, (
            f"install_goose_ui.sh reads a local copy ({local!r}) — doctrine 2b forbids "
            "provisioning from anything but the pinned upstream artifact")
    assert "releases/download" in code, "the artifact must come from the pinned release"


@_needs_bundle
def test_manifest_records_the_pinned_bundle():
    head = open(MANIFEST, encoding="utf-8").read().splitlines()[:3]
    assert any(PIN_ASAR_SHA256 in ln for ln in head), head
    assert f"BUNDLE {PIN_BUNDLE_SHA256}" in head
    assert G.bundle_sha(ROOT) == PIN_BUNDLE_SHA256


@_needs_bundle
def test_vendored_bundle_is_unmodified():
    """Recompute the manifest from disk. This is the ONLY thing standing between
    "we serve goose's UI unmodified" and a quiet local edit that makes the Apache-2.0
    §4b statement in data/goose/UI-SOURCES.txt false."""
    lines = []
    for line in open(MANIFEST, encoding="utf-8"):
        if line.startswith("#") or line.startswith("BUNDLE "):
            continue
        want, _, rel = line.rstrip("\n").partition("  ")
        p = os.path.join(UI, rel[2:] if rel.startswith("./") else rel)
        assert os.path.isfile(p), f"missing vendored file {rel}"
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        assert got == want, f"MODIFIED vendored file: {rel}"
        lines.append(line.rstrip("\n"))
    # …and nothing EXTRA on disk either: a file we added to the "unmodified" tree is
    # exactly as much of a lie as a file we edited.
    on_disk = set()
    for p in glob.glob(os.path.join(UI, "**", "*"), recursive=True):
        if os.path.isfile(p):
            on_disk.add("./" + os.path.relpath(p, UI))
    named = {ln.split("  ", 1)[1] for ln in lines}
    assert on_disk == named, f"untracked files under data/goose/ui: {on_disk - named}"


# ── 2. the census: upstream's calls vs our shim ──────────────────────────────
def _renderer_electron_calls() -> set:
    out = set()
    for f in glob.glob(os.path.join(UI, "assets", "*.js")):
        src = open(f, encoding="utf-8", errors="replace").read()
        out |= set(re.findall(r"electron\.([A-Za-z_$][\w$]*)", src))
    return out


@_needs_bundle
def test_every_preload_method_the_renderer_calls_is_shimmed():
    """⚠️ THE ONE THAT EARNS ITS KEEP. Reads upstream's shipped renderer and demands a
    shim for every `window.electron.*` it invokes. A goose bump that adds one fails
    HERE — loudly, at the gate — instead of as `undefined is not a function` in a tab
    with no server-side trace at all."""
    called = _renderer_electron_calls()
    assert called, "found no window.electron.* calls — the bundle layout changed"
    missing = sorted(called - set(G.PRELOAD_METHODS))
    assert not missing, (
        "goose's renderer calls window.electron methods our shim does not define: "
        f"{missing}. Add each to SHIMMED / STUBBED / DEGRADED in bridge/gooseui.py "
        "and implement it in _PRELOAD_TEMPLATE.")


@_needs_bundle
def test_appconfig_keys_the_renderer_reads_are_supplied():
    keys = set()
    for f in glob.glob(os.path.join(UI, "assets", "*.js")):
        src = open(f, encoding="utf-8", errors="replace").read()
        keys |= set(re.findall(r"appConfig\.get\([`'\"]([A-Z_]+)", src))
    assert keys, "found no appConfig.get() calls — the bundle layout changed"
    supplied = set(G.app_config("1.48.0", "/tmp/ws")) | set(G.APPCONFIG_DELIBERATELY_ABSENT)
    assert not (keys - supplied), (
        f"appConfig keys the renderer reads that we neither supply nor have decided to "
        f"leave absent: {sorted(keys - supplied)}")
    # A key listed as deliberately absent must NOT also be supplied — otherwise the
    # comment explaining why it is absent is describing something that is not true.
    assert not (set(G.APPCONFIG_DELIBERATELY_ABSENT)
                & set(G.app_config("1.48.0", "/tmp/ws")))


def test_the_shim_source_defines_every_catalogued_method():
    """The three catalogues are the SPEC; the generated JavaScript is the artefact. A
    name in a catalogue that the template forgets is a promise the status endpoint makes
    and the page breaks."""
    js = G.preload_js({"acp_url": "ws://x/acp?token=t", "secret": "t",
                       "app_config": G.app_config("1.48.0", "/tmp/ws")})
    for name in G.PRELOAD_METHODS:
        assert re.search(rf"\b{re.escape(name)}\s*:", js), f"shim omits {name}"
    # …and the connection-critical one carries the real URL, not a placeholder.
    assert "ws://x/acp?token=t" in js
    # Buckets must be disjoint: a method in two buckets means two different promises
    # about the same call, and the catalogues are what the report quotes to Debi.
    assert not (set(G.SHIMMED) & set(G.STUBBED))
    assert not (set(G.SHIMMED) & set(G.DEGRADED))
    assert not (set(G.STUBBED) & set(G.DEGRADED))
    # Every degradation is a SENTENCE, because the report owes Debi one per lost feature.
    for name, why in G.DEGRADED.items():
        assert len(why) > 15, f"{name} has no honest degradation sentence"


# ── 3. the ACP route and the launch line ─────────────────────────────────────
def test_acp_url_is_main_js_own_shape():
    """`ws://127.0.0.1:<port>/acp?token=<secret>` — read out of the pinned app.asar's
    main.js (`he(port, secret, scheme)`), not invented. `getAcpUrl` has NO fallback in
    acpConnection.ts, so a wrong shape here is a blank page."""
    assert G.acp_url(3287, "abc") == "ws://127.0.0.1:3287/acp?token=abc"
    assert G.status_url(3287) == "http://127.0.0.1:3287/status"
    # Total on junk: a bad port must cost the DEFAULT, never a traceback in a route.
    assert G.acp_url(None, "t").endswith(f":{G.DEFAULT_ACP_PORT}/acp?token=t")


def test_serve_argv_is_the_desktop_platform():
    argv = G.serve_argv("/r", 3287)
    assert argv[1:] == ["serve", "--platform", "desktop", "--enable-scheduler",
                        "--host", "127.0.0.1", "--port", "3287"]
    assert argv[0].endswith("data/goose/bin/goose"), "must be the ONE pinned binary"


def test_allowed_origins_cover_both_loopback_spellings():
    """`--allowed-origin` REPLACES the default loopback set, so passing a partial list
    is worse than passing none: 127.0.0.1 and localhost are different Origins and a user
    who types the other one gets a socket that refuses with no explanation."""
    o = G.allowed_origins(8700)
    assert "http://127.0.0.1:8700" in o and "http://localhost:8700" in o


def test_the_two_goose_lanes_cannot_collide():
    """The PTY lane (bridge/pty_goose.py) and this one must not share a home, a config
    file or a pidfile — otherwise one lane's sessions appear in the other's history and
    stopping one stops both."""
    from bridge import pty_goose as P
    assert G.ui_home("/r") != P.goose_home("/r")
    assert G.config_path("/r") != P.config_path("/r")
    assert G.pidfile_path("/r") != P.pidfile_path("/r")
    # …and this lane's home must not be INSIDE the PTY lane's (or a `rm -rf` of one
    # takes the other with it).
    assert not G.ui_home("/r").startswith(P.goose_home("/r") + os.sep)
    assert not P.goose_home("/r").startswith(G.ui_home("/r") + os.sep)


def test_the_fence_and_the_kill_switches_are_on_every_launch():
    env = G.serve_env({"HOME": "/Users/nobody"}, "/r", "tok",
                      "http://127.0.0.1:6767/v1", "key", "m", 6767)
    assert env["GOOSE_PATH_ROOT"] == G.path_root("/r")
    assert env["HOME"] == G.ui_home("/r")
    assert env["HOME"] != "/Users/nobody", "the operator's HOME must not survive"
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert env[k].startswith(G.ui_home("/r"))
    assert env["HF_HOME"].startswith(G.ui_home("/r")), "the HF cache is the named leak"
    assert env["GOOSE_TELEMETRY_OFF"] == "1"
    assert env["GOOSE_TELEMETRY_ENABLED"] == "false"
    assert env["GOOSE_DISABLE_KEYRING"] == "true"
    assert env["GOOSE_DISABLE_AUTO_DOWNLOAD"] == "1"
    assert env["GOOSE_SERVER__SECRET_KEY"] == "tok"
    # ⚠️ THE CONSENT STEP. Measured in the spike: with GOOSE_MODE unset the embedded
    # agent created a file on the real disk with no prompt at all (upstream's default at
    # this pin is `auto`). An agent that can also run shell commands must ask; on the
    # desktop platform the ask travels over ACP as session/request_permission and the
    # vendored renderer draws the card.
    assert env["GOOSE_MODE"] == G.GOOSE_MODE == "smart_approve"
    assert env["GOOSE_MODE"] != G.FORBIDDEN_MODE
    # The /v1/v1 trap: goose composes HOST + '/' + BASE_PATH.
    assert env["OPENAI_HOST"] == "http://127.0.0.1:6767"
    assert env["OPENAI_BASE_PATH"] == "v1/chat/completions"
    assert "GOOSE_TOOLSHIM" not in env


# ── 4. registration ──────────────────────────────────────────────────────────
def test_lane_is_registered_in_both_manifests():
    app_src = open(os.path.join(ROOT, "bridge", "app.py"), encoding="utf-8").read()
    src_src = open(os.path.join(ROOT, "bridge", "appsrc.py"), encoding="utf-8").read()
    assert '"routers.gooseui"' in app_src, "not in bridge/app.py _LANES"
    assert '"routers/gooseui.py"' in src_src, "not in bridge/appsrc.py FILES"
    from bridge import appsrc
    assert "routers/gooseui.py" in appsrc.FILES
    assert "/gooseui" in appsrc.APP_SOURCE


def test_the_page_injects_the_shim_before_the_module_script():
    """A module script is deferred BY DEFINITION, so a classic tag placed above it is
    guaranteed to run first — and `window.electron` must exist before any renderer code
    does. Placing the shim after (or as a module) is a race that passes on localhost."""
    doc = ('<html><head><title>Goose</title>'
           '<script type="module" crossorigin src="./assets/index-x.js"></script>'
           '</head><body></body></html>')
    out = G.page_html(doc, "/gooseui/harness-preload.js")
    assert out.index("harness-preload.js") < out.index('type="module"')
    assert 'type="module"' not in out.split("harness-preload.js")[0].rsplit("<script", 1)[-1]
    # …and OUR surface is named per Debi's 2026-08-29 ruling, while nothing inside the
    # vendored bundle is renamed.
    assert f"<title>{G.SURFACE_NAME}</title>" in out
    assert G.SURFACE_NAME == "Goose UI"


def _code_only(path: str) -> str:
    """The file's EXECUTABLE text: comments and string literals removed.

    A source-text gate has to distinguish "does this" from "explains why it must not do
    this" — otherwise the only way to pass it is to delete the explanation, which is the
    part that stops the mistake recurring."""
    if path.endswith(".py"):
        import io
        import tokenize
        out = []
        try:
            for tok in tokenize.generate_tokens(io.StringIO(
                    open(path, encoding="utf-8").read()).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING):
                    continue
                out.append(tok.string)
        except (tokenize.TokenError, IndentationError):             # pragma: no cover
            return open(path, encoding="utf-8").read()
        return " ".join(out)
    return "\n".join(ln for ln in open(path, encoding="utf-8").read().splitlines()
                     if not ln.strip().startswith("#"))


def test_no_pattern_or_port_scoped_kills_anywhere_in_this_lane():
    """⚠️ READ IDENTITY BEFORE KILL — the standing rule, as a gate.

    THE INCIDENT (example, not the rule): Debi runs the standalone goose Desktop app on
    this Mac, and it spawns its own `goose serve` child on a port it chooses at runtime.
    A throwaway restart helper used during this spike did
    `lsof -ti tcp:3287 | xargs kill -9` to clear "our" ACP port, and closed her Desktop
    app TWICE. Same shape as the recorded Unsloth incident.

    THE GENERAL RULE THIS PINS: a process may be signalled only when its own IDENTITY
    says it is ours — our child handle, or our pidfile confirmed by reading the live
    process's command line AND its GOOSE_PATH_ROOT. A port, a name, or a pattern is
    never identity. So this lane's files may not contain pkill/killall, may not pipe
    lsof into kill, and every signal must be gated on is_ours().
    """
    for rel in ("bridge/gooseui.py", "bridge/routers/gooseui.py",
                "scripts/install_goose_ui.sh"):
        code = _code_only(os.path.join(ROOT, rel)).lower()
        for banned in ("pkill", "killall"):
            # …in CODE ONLY. The word appears in the prose above precisely because the
            # prose is what stops the next person reintroducing it; a gate that banned
            # the WORD would ban its own explanation.
            assert banned not in code, f"{rel}: {banned} appears in executable code"
        assert not re.search(r"lsof[^\n]*kill", code), f"{rel}: lsof-piped-to-kill"

    router = open(os.path.join(ROOT, "bridge", "routers", "gooseui.py"),
                  encoding="utf-8").read()
    assert "def is_ours(" in router
    # EVERY function that signals must ALSO consult is_ours — asserted structurally
    # (ast), not by text order: "the guard is written above the kill" is a property of
    # the file's layout, while "this function checks before it kills" is the property
    # that matters and survives a reshuffle.
    import ast
    tree = ast.parse(router)
    signalling = [fn for fn in ast.walk(tree)
                  if isinstance(fn, ast.FunctionDef)
                  and "killpg" in ast.get_source_segment(router, fn)]
    assert signalling, "no signalling function found — did the stop path move?"
    for fn in signalling:
        seg = ast.get_source_segment(router, fn)
        assert "is_ours(" in seg, f"{fn.name}() signals without an identity check"
    # …and the identity check demands BOTH facts: our binary AND our fenced path root.
    assert "goose_bin(ROOT) in out" in router
    assert 'f"GOOSE_PATH_ROOT={_ui.path_root(ROOT)}" in out' in router


def test_bundle_target_refuses_traversal():
    got, why = G.bundle_target(ROOT, "../../../etc/passwd")
    assert got is None and "outside" in why
    assert G.bundle_target(ROOT, "")[0] is None
    assert G.bundle_target(ROOT, "a\x00b")[0] is None
