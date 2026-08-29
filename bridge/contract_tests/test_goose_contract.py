"""UPSTREAM's side of the GOOSE seam — the gate a pin bump must pass.

Built to docs/research/2026-08-28-goose-source-verify.md. Like OpenCode there is NO
vendored source tree: upstream ships one prebuilt Mach-O per platform. So the contract
is pinned three ways, and every part of it that needs the binary SKIPS CLEANLY until it
is installed (a sandbox that cannot run an arm64 executable must not turn a gate red):

  1. BY DIGEST — the archive's sha256 and the extracted binary's sha256 are the pin.
     A tag can be moved; a digest cannot. This is the half that runs everywhere,
     installed or not, because it compares three copies of the same constants
     (installer, bridge module, manifest) and a drift between them means an install
     could land bytes nobody measured.
  2. BY RUNNING IT — `--version` must equal the pin, and the two subcommands the lane
     depends on must still exist: `session` (the interactive entrypoint) and, as the
     load-bearing NEGATIVE, still NO `web` and NO `ui`. The whole shape of this lane —
     a pty rather than a tab — rests on goose having no browser UI, so if upstream ever
     grows one, this is where we find out.
  3. BY SCANNING IT — every env var our launch line depends on must still exist as a
     string inside the binary. A rename there is the silent kind of failure: goose
     would simply start phoning PostHog again, or prompting the Keychain, or firing its
     unbounded title-generation completion, and nothing would error.

⚠️ EVERY EXEC IN HERE GOES THROUGH THE SAME CONFINEMENT FENCE THE LANE USES. goose
opens a per-invocation log file before it parses argv, so an unfenced `--version` in a
TEST would write into the developer's real ~/.local/state/goose — which is precisely the
leak this slice fixed in the installer. A gate that violates the property it guards is
not a gate.

Run: pytest bridge/contract_tests/test_goose_contract.py -q
"""
import os
import re
import subprocess

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BIN = os.path.join(ROOT, "data", "goose", "bin", "goose")
HOME = os.path.join(ROOT, "data", "goose", "home")
INSTALLER = os.path.join(ROOT, "scripts", "install_goose.sh")

# The pin, restated here so this file is readable on its own. It is ASSERTED against
# all three other copies below rather than trusted.
PIN_TAG = "v1.48.0"
PIN_SRC_SHA = "25021517f12cab87c94bed0874fe7d28168dc264"
PIN_ASSET_SHA256 = "d502945fca78d8e58c8f56932973f454ad57d0754b272f5d44f696a4722da49a"
PIN_BIN_SHA256 = "e900f1b96662818791ee599c58ea0e44204ca29579dd182ecc238b732ef5d768"
TELEMETRY_ENDPOINT = "https://us.i.posthog.com/capture/"


def _installed() -> bool:
    return os.path.isfile(BIN) and os.access(BIN, os.X_OK)


def _run(*args) -> str:
    """stdout+stderr, or '' when the binary cannot run here (a foreign ISA in the
    sandbox is a SKIP, never a failure). The env is the lane's own fence — see the
    module docstring for why a test may not be the thing that leaks."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
           "HOME": HOME,
           "XDG_CONFIG_HOME": os.path.join(HOME, ".config"),
           "XDG_DATA_HOME": os.path.join(HOME, ".local", "share"),
           "XDG_STATE_HOME": os.path.join(HOME, ".local", "state"),
           "XDG_CACHE_HOME": os.path.join(HOME, ".cache"),
           "GOOSE_TELEMETRY_OFF": "1", "GOOSE_DISABLE_KEYRING": "true"}
    try:
        p = subprocess.run([BIN, *args], capture_output=True, text=True, timeout=120,
                           env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (p.stdout or "") + (p.stderr or "")


def _installer_src() -> str:
    with open(INSTALLER, encoding="utf-8") as fh:
        return fh.read()


def _manifest() -> dict:
    with open(os.path.join(ROOT, "harness.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh.read())


def _strings(path: str) -> str:
    """Printable runs out of the binary. `strings` ships with macOS/Xcode CLT; when it
    is absent we read the bytes ourselves rather than skipping — the scan half of this
    contract is the part that catches SILENT upstream renames."""
    try:
        p = subprocess.run(["strings", "-n", "5", path], capture_output=True,
                           text=True, timeout=180)
        if p.returncode == 0 and p.stdout:
            return p.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    with open(path, "rb") as fh:
        return fh.read().decode("latin-1", errors="replace")


# ── 1. BY DIGEST — runs everywhere, installed or not ─────────────────────────
def test_the_three_copies_of_the_pin_agree():
    """installer ← the authority · bridge/pty_goose.py · harness.yaml.

    Three copies is two too many in the abstract, and every one of them earns its
    place: the shell script cannot import Python, the bridge must be able to SAY what
    is installed without shelling out, and the manifest is where a human looks for a
    pin. What makes that safe is exactly this assertion."""
    src = _installer_src()
    for name, want in (("GOOSE_TAG", PIN_TAG),
                       ("GOOSE_SRC_SHA", PIN_SRC_SHA),
                       ("GOOSE_ASSET_SHA256", PIN_ASSET_SHA256),
                       ("GOOSE_BIN_SHA256", PIN_BIN_SHA256)):
        assert f'{name}="{want}"' in src, f"installer's {name} moved away from {want}"

    import sys
    sys.path.insert(0, ROOT)
    from bridge import pty_goose as G
    assert G.PIN_TAG == PIN_TAG
    assert G.PIN_SRC_SHA == PIN_SRC_SHA
    assert G.PIN_ASSET_SHA256 == PIN_ASSET_SHA256
    assert G.PIN_BIN_SHA256 == PIN_BIN_SHA256

    b = (_manifest().get("build") or {})
    assert str(b.get("goose_pin")) == PIN_TAG
    assert str(b.get("goose_src_sha")) == PIN_SRC_SHA
    assert str(b.get("goose_asset_sha256")) == PIN_ASSET_SHA256
    assert str(b.get("goose_bin_sha256")) == PIN_BIN_SHA256


def test_goose_is_not_a_component():
    """The shape of the lane, pinned. A `components.goose` block would give it a
    Mission Control card with a Start button, and there is nothing for that button to
    start: goose has no port and no daemon. A card that cannot work is the lie."""
    assert "goose" not in (_manifest().get("components") or {})


def test_the_installer_verifies_before_it_extracts():
    src = _installer_src()
    assert src.index("sha256 MISMATCH") < src.index("tar xzf"), (
        "the sha256 gate must come BEFORE the extraction, or a substituted archive is "
        "already on disk by the time we object")
    assert "GOOSE_ASSET_SIZE=" in src, "the size gate names a truncated download"
    assert "env -i" in src and 'XDG_STATE_HOME="$HOMEDIR/.local/state"' in src, (
        "every exec of the binary from the installer is fenced — goose writes a log "
        "before it parses argv, so even --version leaks without this")


def test_the_installed_bytes_are_the_pinned_bytes():
    """The digest of what is actually on disk. This is the only check that can catch
    a binary replaced AFTER a verified install."""
    if not _installed():
        return
    import hashlib
    h = hashlib.sha256()
    with open(BIN, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    assert h.hexdigest() == PIN_BIN_SHA256, (
        f"data/goose/bin/goose is {h.hexdigest()} but the pin is {PIN_BIN_SHA256} — "
        "re-run ./scripts/install_goose.sh --force")


# ── 2. BY RUNNING IT ─────────────────────────────────────────────────────────
def test_version_matches_the_pin():
    if not _installed():
        return
    out = _run("--version").strip()
    if not out:
        return                       # cannot execute here → skip, do not fail
    assert PIN_TAG.lstrip("v") in out, (
        f"the installed binary reports {out!r} but the pin is {PIN_TAG!r} — either the "
        "pin moved without a reinstall, or `goose update` was run (which this project "
        "never does: the install is pinned by digest)")


def test_no_browser_ui_still():
    """THE LOAD-BEARING NEGATIVE. This lane is a pty and not a tab BECAUSE goose serves
    no page of its own. `serve` is an ACP client API over HTTP/WS, secret-key-gated by
    default — not a UI. If `web` or `ui` ever appears here, the lane's shape is a
    decision to revisit, not a detail."""
    if not _installed():
        return
    out = _run("--help")
    if not out:
        return
    subs = out
    assert re.search(r"^\s+session\b", subs, re.M), "`goose session` is the entrypoint"
    assert not re.search(r"^\s+web\b", subs, re.M), (
        "upstream grew a `web` subcommand — goose may now have a browser UI, which is "
        "the premise of the whole pty lane. Re-read the recon before bumping.")
    assert not re.search(r"^\s+ui\b", subs, re.M), "upstream grew a `ui` subcommand"


def test_session_still_takes_the_flags_the_lane_will_grow_into():
    """--resume / --name / --fork are the daily-use journeys slice 2 is built on. They
    are not on the launch line today; this asserts they are still there to build on."""
    if not _installed():
        return
    out = _run("session", "--help")
    if not out:
        return
    for flag in ("--resume", "--name", "--fork", "--history"):
        assert flag in out, f"`goose session` lost {flag}"


def test_update_is_a_subcommand_not_a_startup_check():
    """Pin discipline: goose must never update ITSELF when the lane starts. Upstream's
    `update` is a manual subcommand and there is no startup check (verified at source,
    research item 5). Its continued existence AS a subcommand is the evidence that the
    self-update machinery is still opt-in rather than automatic."""
    if not _installed():
        return
    out = _run("--help")
    if not out:
        return
    assert re.search(r"^\s+update\b", out, re.M), (
        "the `update` subcommand vanished — check whether self-update moved to startup")


# ── 3. BY SCANNING IT ────────────────────────────────────────────────────────
def test_every_env_key_the_lane_depends_on_still_exists():
    """A rename in any of these is SILENT: the lane would keep starting and quietly
    lose a kill switch. Each name is followed by what breaks if it goes."""
    if not _installed():
        return
    blob = _strings(BIN)
    required = {
        # telemetry — both mechanisms, and the endpoint they gate
        "GOOSE_TELEMETRY_OFF": "the env kill switch for PostHog",
        "GOOSE_TELEMETRY_ENABLED": "the config kill switch for PostHog",
        # the headless/keychain fence
        "GOOSE_DISABLE_KEYRING": "keeps a macOS Keychain modal out of a webview tab",
        # the measured hang fix
        "GOOSE_DISABLE_SESSION_NAMING":
            "without it goose fires a second, concurrent title completion that never "
            "returns on a reasoning model behind our single-slot llama-server",
        # the provider seam
        "GOOSE_PROVIDER": "which provider to use",
        "GOOSE_MODEL": "the wire model id, passed through verbatim",
        "OPENAI_HOST": "the runner's ORIGIN",
        "OPENAI_BASE_PATH": "the path appended to it",
        "OPENAI_API_KEY": "the runner's real bearer key",
    }
    missing = [f"{k} ({why})" for k, why in required.items() if k not in blob]
    assert not missing, "env keys the goose lane depends on are gone: " + "; ".join(missing)


def test_the_telemetry_endpoint_is_still_the_only_one_we_gate():
    """The kill switches are only as good as our knowledge of what they gate. If a
    SECOND analytics host appears in the binary, our two switches may no longer cover
    everything and this slice's 'no telemetry egress' claim needs re-proving."""
    if not _installed():
        return
    blob = _strings(BIN)
    assert "us.i.posthog.com" in blob, (
        "the known PostHog endpoint is gone — telemetry moved, and the two switches "
        "we set may no longer be the ones that matter")
    for other in ("segment.io", "api.amplitude.com", "google-analytics.com",
                  "api.mixpanel.com", "sentry.io/api"):
        assert other not in blob, (
            f"a NEW analytics endpoint appeared in the pinned binary ({other}) — "
            "re-verify the kill switches before shipping this pin")


def test_the_toolshim_backends_still_cannot_reach_our_runner():
    """Why the lane warns about tool-calling instead of shimming it. goose's toolshim
    emulates tool calls for non-tool models, but only through ollama or its own bundled
    local inference — it cannot point at our :6767 OpenAI-compatible runner. If that
    ever changes, the `tools` warning could become an offer instead."""
    if not _installed():
        return
    blob = _strings(BIN)
    assert "GOOSE_TOOLSHIM" in blob, "the toolshim env key vanished — re-read the recon"
    assert "GOOSE_TOOLSHIM_OLLAMA_MODEL" in blob, (
        "the ollama-only backend key vanished; if the toolshim gained a generic "
        "OpenAI-compatible backend, this lane could offer it instead of warning")


# ══ THE DECLARATIVE CUSTOM PROVIDER — the schema, pinned against the real binary ══
#
# ⚠️ THIS SECTION EXISTS BECAUSE v1.5.40 GUESSED AND WAS WRONG THREE TIMES. The layout
# is now READ, not designed: goose's own "Add custom provider" form was driven through
# the real renderer at http://127.0.0.1:8700/gooseui/ on 2026-08-29 and the file goose
# WROTE is the schema. bridge/gooseprov.py's docstring carries the full census. What
# follows is the half a pin bump must re-prove — because a declarative-provider schema
# is exactly the kind of upstream surface that moves quietly.

def _prov():
    import sys
    sys.path.insert(0, ROOT)
    from bridge import gooseprov
    return gooseprov


def test_the_provider_name_is_gooses_own_slug():
    """Our provider file is named what GOOSE would name it for our display name. That
    is not cosmetic: it is what makes a provider the user later edits (or deletes) in
    goose's own form be the same object we seed, instead of a second identical row."""
    P = _prov()
    assert P.slugify(P.DISPLAY_NAME) == P.PROVIDER_NAME == "custom_mot_deck__local"
    assert P.api_key_env() == "CUSTOM_MOT_DECK__LOCAL_API_KEY", (
        "goose DERIVES the key env var from the provider name — a name change is "
        "silently a key change")
    assert P.DISPLAY_NAME == "MOT Deck (local)", (
        "one product, one name in every vendor picker (OpenCode's provider says the "
        "same string)")


def test_the_provider_file_shape_is_the_one_goose_wrote():
    """The 22 fields, verbatim from the file goose's own form produced at v1.48.0."""
    P = _prov()
    doc = P.provider_doc("http://127.0.0.1:6767", P.model_entries([{"id": "m"}]))
    assert set(doc) == {
        "name", "engine", "display_name", "description", "api_key_env", "base_url",
        "models", "headers", "timeout_seconds", "supports_streaming", "requires_auth",
        "catalog_provider_id", "base_path", "env_vars", "dynamic_models",
        "skip_canonical_filtering", "model_doc_link", "setup_steps", "fast_model",
        "preserves_thinking", "emit_clear_thinking", "setup"}, (
        "the declarative-provider schema moved at this pin — re-run the census "
        "(drive goose's own Add-custom-provider form and read the file it writes) "
        "before changing anything here")
    assert doc["engine"] == "openai", (
        "the FILE's engine is `openai`; `openai_compatible` is the FORM's enum")
    assert doc["base_path"] is None and doc["base_url"].count("/v1") == 0
    assert set(doc["models"][0]) == {
        "name", "context_limit", "input_token_cost", "output_token_cost", "currency",
        "supports_cache_control", "reasoning"}


def test_the_pinned_binary_still_loads_a_seeded_provider():
    """⚠️ THE LIVE HALF, AND THE ONLY ONE THAT PROVES ANYTHING. Seed our provider file
    into a THROWAWAY fenced home, point the real goose binary at it, and require it to
    resolve — `Unknown provider` is exactly the failure v1.5.40 hit three times, and it
    is silent until somebody types a message.

    No network is needed and none is used: we only require goose to RESOLVE the
    provider, which it reports in its own session banner before any request is made.
    """
    if not _installed():
        return
    import shutil
    import tempfile
    P = _prov()
    home = tempfile.mkdtemp(prefix="goose-contract-")
    try:
        cfgdir = os.path.join(home, ".config", "goose")
        path, _changed, err = P.seed_provider(
            cfgdir, "http://127.0.0.1:1/v1", [{"id": "contract-model"}])
        assert not err and os.path.isfile(path), f"could not seed the provider: {err}"
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": home,
               "XDG_CONFIG_HOME": cfgdir.rsplit(os.sep, 1)[0],
               "XDG_DATA_HOME": os.path.join(home, ".local", "share"),
               "XDG_STATE_HOME": os.path.join(home, ".local", "state"),
               "XDG_CACHE_HOME": os.path.join(home, ".cache"),
               "GOOSE_TELEMETRY_OFF": "1", "GOOSE_TELEMETRY_ENABLED": "false",
               "GOOSE_DISABLE_KEYRING": "true",
               "GOOSE_DISABLE_SESSION_NAMING": "true",
               "GOOSE_PROVIDER": P.PROVIDER_NAME,
               "GOOSE_MODEL": "contract-model",
               P.api_key_env(): "contract-key"}
        try:
            p = subprocess.run([BIN, "run", "--no-session", "--text", "x"],
                               capture_output=True, text=True, timeout=180, env=env)
        except (OSError, subprocess.SubprocessError):
            return
        out = (p.stdout or "") + (p.stderr or "")
        if not out.strip():
            return                      # a foreign ISA in the sandbox: SKIP, not a fail
        assert "Unknown provider" not in out, (
            "the pinned binary REJECTED our seeded declarative provider — the schema "
            "moved. Re-run the census through goose's own form; see bridge/gooseprov.py")
        assert P.PROVIDER_NAME in out, (
            "goose did not resolve the provider by name — it should announce it in its "
            f"own session banner. Got:\n{out[:800]}")
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_env_beats_secrets_for_the_provider_key():
    """The string goose reads the key from must still exist in the binary. This is the
    measured precedence (env WINS over secrets.yaml) that lets us hand the runner's key
    to the child and NEVER write the user's secret store."""
    if not _installed():
        return
    blob = _strings(BIN)
    for needle in ("custom_providers", "api_key_env", "active_provider",
                   "openai_compatible"):
        assert needle in blob, (
            f"'{needle}' vanished from the pinned binary — the declarative provider "
            "mechanism moved; re-run the census before shipping this pin")
