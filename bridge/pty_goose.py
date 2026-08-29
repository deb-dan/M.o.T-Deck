"""goose agent lane — the PTY seam (slice 1, 2026-08-29).

Built to docs/research/2026-08-28-goose-source-verify.md (BUILD-READY, pins at its
bottom). goose is NOT a component: no port, no manifest card, no daemon. It is a
terminal program we run in a pseudo-terminal for exactly as long as a browser tab
holds a websocket open, in ONE chosen workspace dir — the aider lane's shape, because
the research verified at source that goose HAS NO BROWSER UI (no `web`, no `ui`
subcommand; `goose serve` is an ACP client API, secret-key-gated, that serves no page).

⚠️ WHY THIS FILE IS NOT A COPY OF pty_aider.py. Everything generic about running a
program on a pty — the session object, the winsize ioctl, the RESIZE control message,
the process-GROUP kill, the origin gate — is IDENTICAL between the two lanes and is
IMPORTED from pty_aider rather than duplicated. What is goose-specific lives here: the
confinement fence, the config seeding, the launch line, and this lane's OWN one-at-a-
time claim. The claim is deliberately separate state: aider and goose are different
programs in different workspaces, and one running must not refuse the other.

WHAT IS LOAD-BEARING IN HERE:

1. **THE CONFINEMENT FENCE IS $HOME *AND* ALL FOUR XDG_* DIRS.** goose reads its config
   from `$HOME/.config/goose/config.yaml` and writes logs to
   `$HOME/.local/state/goose/logs`, session history to `$HOME/.local/share/goose`
   (all three observed empirically, research item 6 and again during this build). HOME
   alone is not enough: an XDG_CONFIG_HOME inherited from whoever launched the app
   would win over it. Setting all five is what makes "nothing lands in a shared
   dotfolder" true rather than hoped-for — the ~/.unsloth lesson, stated as a fence
   rather than as a cleanup.

   ⚠️ AND THE SAME FENCE APPLIES TO ONE-SHOT PROBES, NOT ONLY TO SESSIONS. goose opens
   a per-invocation log file BEFORE it parses argv, so even `goose --version` writes.
   scripts/install_goose.sh carries the identical env for exactly that reason (it
   leaked three empty files into ~/.local/state/goose during this build, which is how
   we know). Any future code path that execs this binary must go through the same env.

2. **TELEMETRY IS KILLED TWICE, IN TWO INDEPENDENT MECHANISMS.** Upstream's PostHog
   client is opt-IN already (`is_telemetry_enabled()` "returns true only if the user
   has explicitly opted in"), so this is belt-and-braces on purpose — the same
   discipline the opencode lane applies to auto-update. `GOOSE_TELEMETRY_OFF=1` in the
   env AND `GOOSE_TELEMETRY_ENABLED: false` in the seeded config. The single egress
   endpoint those two gate is `https://us.i.posthog.com/capture/` (the only telemetry
   URL in the pinned binary's strings), and bridge/tests/test_goose_lane.py asserts
   both switches are on every launch.

3. **`GOOSE_DISABLE_SESSION_NAMING=true`, AND IT IS NOT A PREFERENCE.** goose fires a
   SECOND completion — "generate a short title (four words or less)" — concurrently
   with the real turn. Our runner is llama-server, which serves ONE request at a time,
   and on a REASONING model that title call thinks without bound: measured on
   2026-08-29 against the resident Qwen3.6-27B, the title request streamed 2,797 chunks
   and had not finished after 10 minutes while the real turn sat queued behind it. To a
   user that is "goose hangs forever on hello" — a dead end, not a slow lane. Turning
   session naming off removes the second request entirely; sessions are then named by
   timestamp, which is what `session list` shows anyway.

4. **`GOOSE_DISABLE_KEYRING=true`.** A macOS Keychain prompt raised behind a WKWebView
   tab is a hang, not a question. Secrets come from env/config instead.

5. **THE APPROVAL PROMPT IS TURNED ON, NOT MERELY LEFT ALONE.** goose's default
   `GOOSE_MODE` at this pin is `auto` — it writes files and runs commands with no
   prompt at all, which was measured on the walked journey while this very page claimed
   the opposite. `GOOSE_MODE=smart_approve` is set on every launch. See the constant
   below for the finding, the proof, and the general rule it records.

6. **THE PIDFILE IS THE MEMORY LEDGER'S HANDLE.** bridge/core/memory.py builds one row
   per `data/<name>.pid`, so writing data/goose.pid for the life of the session is what
   makes goose appear BY NAME in /api/memory components with its real footprint. It is
   removed on close, so the row exists exactly while goose does — never a ghost. This
   is also what makes `./scripts/stop.sh` stop goose, which is correct.

⚠️ GUARDRAIL, said out loud: the harness path-guard fence does NOT cover goose (that is
a Hermes plugin on Hermes's own pre_tool_call hook). The WORKSPACE DIRECTORY is the
entire boundary — which is why it is never $HOME and never the harness repo.

Everything decision-shaped is a PURE function so it can be table-tested; the session
manager is exercised for real against /bin/cat in bridge/tests/test_goose_lane.py.
"""
from __future__ import annotations

import os
import threading

# The NAMED PROVIDER, shared by both goose lanes. Its module docstring carries the whole
# empirical census (the file goose's own form wrote) — read it before touching anything
# provider-shaped in here. One writer, two lanes: the CLI lane and the embed lane must
# not drift into two different ideas of what "MOT Deck (local)" is.
from . import gooseprov as _prov

# The GENERIC pty machinery, imported and not re-implemented. If this import fails the
# whole module fails, which the router already handles the same way it handles a missing
# aider module: the tab says the lane is unavailable and offers nothing that cannot work.
from .pty_aider import (                                          # noqa: F401
    CLOSE_BUSY, CLOSE_ENDED, CLOSE_ORIGIN, CLOSE_PRECONDITION,
    DEFAULT_COLS, DEFAULT_ROWS, MAX_COLS, MAX_ROWS, MIN_COLS, MIN_ROWS,
    PtySession, allowed_origins, clamp_dim, kill_process_group, origin_allowed,
    set_winsize, split_resize,
)

# ── constants ────────────────────────────────────────────────────────────────
GOOSE_DIR = "data/goose"
BIN_REL = "data/goose/bin/goose"
HOME_REL = "data/goose/home"                # $HOME and every XDG_* dir for this lane
WORKSPACE_DIR = "data/goose-workspace"      # the only boundary on what it edits
PIDFILE_REL = "data/goose.pid"              # → the memory ledger's "Goose" row
CONFIG_REL = "data/goose/home/.config/goose/config.yaml"
LOG_NAME = "goose"

# The pin, mirrored from scripts/install_goose.sh so the panel can SAY what is
# installed without shelling out. The installer is the authority; a drift between the
# two is caught by bridge/contract_tests/test_goose_contract.py.
PIN_TAG = "v1.48.0"
PIN_SRC_SHA = "25021517f12cab87c94bed0874fe7d28168dc264"
PIN_ASSET_SHA256 = "d502945fca78d8e58c8f56932973f454ad57d0754b272f5d44f696a4722da49a"
PIN_BIN_SHA256 = "e900f1b96662818791ee599c58ea0e44204ca29579dd182ecc238b732ef5d768"

# The ONE telemetry egress in the pinned binary. Named here so the test that proves the
# kill switches can name what it is proving the absence of.
TELEMETRY_ENDPOINT = "https://us.i.posthog.com/capture/"

# ⚠️ GOOSE_MODE IS SET, NOT LEFT ALONE, AND THAT IS THE MOST IMPORTANT LINE IN THIS FILE.
#
# THE FINDING (live journey, 2026-08-29, LIE-TO-USER class — the worst class this
# project ranks). This page and the Help explainer both told the user "goose asks before
# each tool call, and that prompt is in the terminal below". It does not: at this pin
# `GooseMode` DEFAULTS TO `auto`, and the walked journey — "create a file containing
# GOOSE-WROTE-THIS" — produced the file in six seconds with NO prompt of any kind. The
# safety story the surface told was fiction, in a lane whose agent can also run shell
# commands. The copy was not the bug; the behaviour was.
#
# `smart_approve` is upstream's own considered middle ground and it is REAL: proven by
# running the same write headlessly under it, which refused outright with "Tool approval
# required in non-interactive mode … Approve/SmartApprove modes require an interactive
# terminal." Our lane is ALWAYS a real pty running `goose session`, so that requirement
# is satisfied by construction — which is also why a pty is the honest surface here at
# all, exactly as it is for aider.
#
# The general rule: WHEN A SURFACE PROMISES A SAFETY STEP, THE SAFETY STEP IS THE
# DELIVERABLE — walk it and see the prompt, or change the promise. A dependency's
# default is not a fact about our product until it has been executed.
GOOSE_MODE = "smart_approve"
# …and this is the value that must NEVER be on the line, in either direction: inherited
# from the operator's shell or set by us. `auto` is what produced the finding above.
FORBIDDEN_MODE = "auto"
# Settings that must never appear on this lane's launch at all:
#   GOOSE_TOOLSHIM         emulates tool calls through an interpreter model whose only
#                          backends are ollama / goose's own bundled llama.cpp — it
#                          CANNOT point at our :6767 runner, so switching it on would
#                          silently degrade the lane to an unusable third path.
FORBIDDEN_ENV = ("GOOSE_TOOLSHIM",)

# The config file we seed. Values are the research doc's verified ConfigKeys.
# ⚠️ OPENAI_BASE_PATH's upstream DEFAULT is already `v1/chat/completions`; it is written
# anyway, because a default is a fact about a version and a pin is a fact about us.
CONFIG_KEYS = ("GOOSE_DISABLE_KEYRING", "GOOSE_TELEMETRY_ENABLED",
               "OPENAI_HOST", "OPENAI_BASE_PATH")


# ── pure: paths ──────────────────────────────────────────────────────────────
def goose_bin(root) -> str:
    return os.path.join(str(root), BIN_REL)


def goose_home(root) -> str:
    return os.path.join(str(root), HOME_REL)


def workspace_path(root) -> str:
    return os.path.join(str(root), WORKSPACE_DIR)


def config_path(root) -> str:
    return os.path.join(str(root), CONFIG_REL)


def config_dir(root) -> str:
    """THE CLI LANE'S CONFIG DIR — `data/goose/home/.config/goose`, i.e. the XDG-fenced
    layout, which is a DIFFERENT shape from the embed lane's GOOSE_PATH_ROOT one
    (`data/goose/ui-home/goose/config`). Both were walked live before this was written;
    assuming one layout for both is how a lane silently ends up with no provider."""
    return os.path.dirname(config_path(root))


def provider_path(root) -> str:
    return _prov.provider_path(config_dir(root))


def pidfile_path(root) -> str:
    return os.path.join(str(root), PIDFILE_REL)


def is_installed(root) -> tuple:
    """(ok, path, reason). Read FROM DISK every time — never a stored flag, so a
    deleted binary reads as not-installed immediately instead of offering a Start that
    cannot work (the music lane's rule, and the reason this lane needs no manifest
    `installed:` flag and therefore no flip_installed.py call)."""
    p = goose_bin(root)
    if os.path.isfile(p) and os.access(p, os.X_OK):
        return True, p, ""
    return False, "", "goose is not installed yet"


# ── pure: the tool-calling verdict ───────────────────────────────────────────
# goose REQUIRES tool calling and has NO text-edit fallback — verified at source
# (documentation/.../providers.md:53 "o1-mini and o1-preview are not supported because
# goose uses tool calling"; goose-provider-types/src/base.rs:584 filters models without
# the `tool_call` capability). On a model that cannot emit one, the lane looks BROKEN
# rather than slow, which is the surprise this warning exists to move BEFORE the user
# types instead of after.
#
# ⚠️ WARN, NEVER REFUSE (the advisory-gates ruling): these are sentences on a pill, not
# a locked Start. And an UNKNOWN verdict is its own sentence, not a silent pass —
# "we don't know" and "it works" are different claims.
#
# ⚠️ WHY THIS IS NOT routers/models.py::opencode_tools_warning. The DECISION TABLE is
# deliberately identical (one product, one grammar), but that function's four constants
# spell "OpenCode" into the user's face, and a Goose tab telling the user what OpenCode
# needs is a small lie in the same class as a wrong model label. Queued shape: give that
# function a lane-label parameter and have both lanes call it.
TOOLS_OK = ""
TOOLS_UNKNOWN = (
    "⚠ the loaded model %s does not say whether it supports tool calling — "
    "goose needs it (look for the green `tools` pill in Models)")
TOOLS_BAD = (
    "⚠ the loaded model %s has NO tool-calling support — goose requires it and has no "
    "text-edit fallback, so it will look broken rather than merely worse. Load a model "
    "with the green `tools` pill.")
TOOLS_NONE = (
    "⚠ no model is loaded — goose needs a running runner with a tool-capable model")


def tools_warning(entry) -> str:
    """'' when the live model is tool-capable, else the sentence to show. PURE.

    `entry` is the live model's REGISTRY ENTRY (a dict), or None when nothing is
    loaded — not the id string. Passing the id would make every model read as
    'unknown', which is the quiet-wrong-answer shape this project ranks worst."""
    if not isinstance(entry, dict):
        return TOOLS_NONE
    name = str(entry.get("id") or entry.get("name") or "?")
    t = entry.get("tools")
    if t is True:
        return TOOLS_OK
    if t is False:
        return TOOLS_BAD % name
    return TOOLS_UNKNOWN % name


# ── pure: the runner's endpoint → goose's two halves ─────────────────────────
def openai_host(endpoint, port=6767) -> str:
    """PURE. goose composes its URL as OPENAI_HOST + '/' + OPENAI_BASE_PATH, so it wants
    the ORIGIN, while runner.endpoint in harness.yaml is the OpenAI-compatible BASE
    (…:6767/v1). Handing goose the base verbatim would produce /v1/v1/chat/completions —
    a 404 that looks exactly like "the model is broken".

    Total: anything unusable falls back to the loopback origin on the runner's port,
    which is the only thing this harness ever points at."""
    # TOTAL: this reads a manifest a human edits, so a number, a list or None must cost
    # the VALUE and never the launch.
    s = (endpoint if isinstance(endpoint, str) else "").strip().rstrip("/")
    if s.endswith("/v1"):
        s = s[: -len("/v1")]
    if not s.startswith("http://") and not s.startswith("https://"):
        try:
            return f"http://127.0.0.1:{int(port)}"
        except (TypeError, ValueError):
            return "http://127.0.0.1:6767"
    return s


# ── pure: the launch line ────────────────────────────────────────────────────
def goose_argv(root) -> list:
    """PURE (given root). `goose session` is the interactive chat entrypoint (alias
    `s`); `run` is the headless one and would exit immediately in a tab.

    NOTHING ELSE GOES ON THIS LINE ON PURPOSE. Every setting goose takes is available
    as an env var or a config key, and putting them there instead means the same launch
    works for `--resume` later without re-deriving a flag table."""
    return [goose_bin(root), "session"]


def goose_env(base_env: dict, root, endpoint: str, api_key: str,
              wire_model: str, port=6767, config_text: str = "") -> dict:
    """PURE. The child's environment: the fence, the two kill switches, the runner.

    `wire_model` is the WIRE identifier, i.e. the output of bridge.core.modelid.
    wire_model_id — the registry id for a gguf model (llama-server is launched with
    `--alias <id>`) but the local PATH for an MLX model (mlx_lm.server resolves the
    request's `model` field as a model to LOAD, so a registry id 404s on huggingface.co
    and the runner answers 400). Reinventing that rule here is how the lane would
    silently break on MLX. goose passes GOOSE_MODEL through VERBATIM — verified at
    source, no `provider/model` splitting anywhere on the OpenAI path — so an MLX
    absolute path survives it.

    ⚠️ A REAL KEY, NOT A DUMMY. The recon's `OPENAI_API_KEY=dummy` got
    `401 Invalid API Key` from our own runner: llama.cpp b10662 validates the bearer
    token. The caller passes runner.api_key; the fallback matches harness.yaml's
    shipped value so a manifest with the key omitted still works.

    COLUMNS/LINES are deliberately REMOVED: the winsize ioctl owns the size, and a
    stale inherited COLUMNS would fight it.
    """
    home = goose_home(root)
    env = dict(base_env or {})
    # ── the fence (all five, see the header) ──
    env["HOME"] = home
    env["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
    env["XDG_STATE_HOME"] = os.path.join(home, ".local", "state")
    env["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    # ── the kill switches ──
    env["GOOSE_TELEMETRY_OFF"] = "1"
    env["GOOSE_TELEMETRY_ENABLED"] = "false"
    env["GOOSE_DISABLE_KEYRING"] = "true"
    env["GOOSE_DISABLE_SESSION_NAMING"] = "true"
    # THE APPROVAL PROMPT — see GOOSE_MODE above. Set explicitly, every launch, so an
    # upstream default change cannot silently remove it.
    env["GOOSE_MODE"] = GOOSE_MODE
    # ── the provider ──
    #
    # ⚠️ THE NAMED PROVIDER, AND THE OVERRIDE WE STOPPED DOING (v1.5.49).
    #
    # goose now sees our runner as "MOT Deck (local)" — a real, named row in its own
    # `/model` and `/configure` pickers, with EVERY registry model listed — because
    # gooseprov.seed_provider() writes the declarative file goose's own form writes.
    # See bridge/gooseprov.py for the empirical census; nothing about it is guessed.
    #
    # ⚠️ AND THE PROVIDER IS SEEDED, NOT ENFORCED. Measured on the pinned binary: env
    # `GOOSE_PROVIDER` OVERRIDES the config's `active_provider`, so the old
    # unconditional `= "openai"` silently undid, at every single launch, any provider
    # the user had chosen inside goose. provider_choice() reads their config and
    # returns "" when the choice is theirs — and the MODEL travels with the provider,
    # because forcing GOOSE_MODEL onto somebody else's provider is the same override
    # wearing a different name.
    key = (api_key or "").strip() or "harness-local"
    chosen, _migrate = _prov.provider_choice(config_text)
    if chosen:
        env["GOOSE_PROVIDER"] = chosen
        env["GOOSE_MODEL"] = (wire_model or "").strip()
    else:
        for k in ("GOOSE_PROVIDER", "GOOSE_MODEL"):
            env.pop(k, None)
    # The key goose actually reads for the named provider (gooseprov F3: `api_key_env`
    # names an ENV VAR, and the process env BEATS secrets.yaml — measured). Setting it
    # here is what lets us never write the user's secret store.
    env[_prov.api_key_env()] = key
    # ⚠️ THE STOCK openai WIRING STAYS. It is not redundancy: a session recorded before
    # this slice carries `provider_name: openai`, and goose resolves it at replay time.
    # Removing these three would break exactly the histories the migration promises not
    # to touch.
    env["OPENAI_HOST"] = openai_host(endpoint, port)
    env["OPENAI_BASE_PATH"] = "v1/chat/completions"
    env["OPENAI_API_KEY"] = key
    env["TERM"] = "xterm-256color"
    for k in ("COLUMNS", "LINES", *FORBIDDEN_ENV):
        env.pop(k, None)
    return env


# ── pure: the seeded config ──────────────────────────────────────────────────
def upsert_config(text: str, pairs, drop=()) -> str:
    """PURE. Set each `key: value` at the top level of a config.yaml, preserving every
    other line byte-for-byte. `drop` removes top-level keys outright — used for exactly
    one thing, the legacy GOOSE_PROVIDER/GOOSE_MODEL lines our own older seeding wrote
    and that goose itself deletes when the user switches provider in its UI.

    A TEXT EDIT, NEVER A YAML ROUND-TRIP — flip_installed.py's rule, for its reason:
    `yaml.safe_dump` rewrites comments away and turns an empty scalar into the literal
    string `null`. It also matters HERE for a second reason: the user may run
    `/configure` inside the tab and add extensions, and a round-trip through our
    writer would be a fine way to lose them.
    """
    lines = (text or "").splitlines()
    out = list(lines)
    # ⚠️ REMOVE-THEN-SET, and the removals come first so a key that is BOTH dropped and
    # set (never today, but the next editor will try it) ends up set exactly once.
    if drop:
        want_gone = tuple(f"{k}:" for k in drop)
        out = [ln for ln in out if not ln.startswith(want_gone)]
    for key, value in pairs:
        want = f"{key}: {value}"
        for i, line in enumerate(out):
            # top level only: a nested `  OPENAI_HOST:` belongs to something else
            if line.startswith(f"{key}:"):
                out[i] = want
                break
        else:
            out.append(want)
    return "\n".join(out).strip("\n") + "\n"


def config_pairs(endpoint: str, port=6767) -> tuple:
    """PURE. The four keys we own in config.yaml, in a stable order."""
    return (("GOOSE_DISABLE_KEYRING", "true"),
            ("GOOSE_TELEMETRY_ENABLED", "false"),
            ("OPENAI_HOST", openai_host(endpoint, port)),
            ("OPENAI_BASE_PATH", "v1/chat/completions"))


def read_config(root) -> str:
    """The fenced config.yaml as text, '' when absent/unreadable. '' means NO OPINION,
    which provider_choice() reads as "nothing of the user's to preserve" — the correct
    first-run answer, and the safe one for a file we simply cannot see."""
    try:
        with open(config_path(root), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def seed_config(root, endpoint: str, port=6767, registry=None) -> str:
    """Write our keys into the confined config.yaml AND our declarative provider file,
    keeping whatever else is there. Returns the config path.

    ⚠️ TWO WRITES, ONE CALL, AND NEITHER MAY CLOBBER:
      * `custom_providers/custom_mot_deck__local.json` — OUR file, by name, merged so a
        display name the user edited in goose's own form survives (OWNED_KEYS only).
      * `active_provider:` — set ONLY when there is no user choice to overwrite (absent,
        or still our own older `openai` seeding). See gooseprov.provider_choice.

    Best-effort by design: env carries the same settings, so a read-only config directory
    degrades to "the env wins" rather than to a dead lane."""
    p = config_path(root)
    cur = read_config(root)
    chosen, migrate = _prov.provider_choice(cur)
    _prov.seed_provider(config_dir(root), endpoint, registry or [], port)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        pairs = list(config_pairs(endpoint, port))
        drop = ()
        if migrate:
            pairs.append(("active_provider", chosen))
            drop = _prov.LEGACY_CONFIG_KEYS
        new = upsert_config(cur, pairs, drop)
        if new != cur:
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(new)
            os.replace(tmp, p)
    except OSError:                                              # noqa: BLE001
        pass
    return p


# ── the pidfile (the memory ledger's handle) ─────────────────────────────────
def write_pidfile(root, pid: int) -> None:
    try:
        p = pidfile_path(root)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(str(int(pid)))
    except (OSError, TypeError, ValueError):                     # noqa: BLE001
        pass


def clear_pidfile(root) -> None:
    try:
        os.unlink(pidfile_path(root))
    except OSError:
        pass


# ── the one-at-a-time claim (this lane's OWN state) ──────────────────────────
# Deliberately NOT pty_aider's globals: a live aider session must not refuse a goose
# session. Two programs, two workspaces, two claims.
_LOCK = threading.Lock()
_SESSION = None


def claim(session) -> bool:
    """Become THE goose session, or refuse. A second PTY would be a second claimant on
    one workspace directory — the VoiceBusy precedent, not a queue."""
    global _SESSION
    with _LOCK:
        if _SESSION is not None and _SESSION.alive():
            return False
        _SESSION = session
        return True


def release(session) -> None:
    global _SESSION
    with _LOCK:
        if _SESSION is session:
            _SESSION = None


def current():
    with _LOCK:
        return _SESSION


def busy() -> bool:
    s = current()
    return bool(s is not None and s.alive())


def kill_current() -> str:
    """Used by the status/teardown paths; harmless when nothing runs."""
    s = current()
    if s is None:
        return "gone"
    how = s.close()
    release(s)
    return how
