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

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

# The NAMED PROVIDER, shared by both goose lanes. Its module docstring carries the whole
# empirical census (the file goose's own form wrote) — read it before touching anything
# provider-shaped in here. One writer, two lanes: the CLI lane and the embed lane must
# not drift into two different ideas of what "MOT Deck (local)" is.
from . import gooseprov as _prov
from .core import ownership as _ownership

# The GENERIC pty machinery, imported and not re-implemented. If this import fails the
# whole module fails, which the router already handles the same way it handles a missing
# aider module: the tab says the lane is unavailable and offers nothing that cannot work.
from .pty_aider import (                                          # noqa: F401
    CLOSE_BUSY, CLOSE_ENDED, CLOSE_ORIGIN, CLOSE_PRECONDITION,
    DEFAULT_COLS, DEFAULT_ROWS, DETACH_GRACE_S, MAX_COLS, MAX_ROWS,
    MIN_COLS, MIN_ROWS, SCROLLBACK_BYTES,
    PtySession, allowed_origins, attach_verdict, clamp_dim, clamp_grace,
    esc_safe_cut, kill_process_group, origin_allowed, set_winsize, split_resize,
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


# ── pure: THE FENCE, on its own, for EVERY exec of this binary ───────────────
def fence_env(base_env: dict, root) -> dict:
    """PURE. HOME + all four XDG_* dirs + the kill switches, and nothing else.

    ⚠️ EXTRACTED, NOT INVENTED (2026-08-29). The header has said since slice 1 that "any
    future code path that execs this binary must go through the same env" — and slice 2
    added three of them (`session list`, `session remove`, and the resume launch). A
    rule that is only written down is a rule that the next caller re-implements four
    fifths of; this is that rule as a function, so an unfenced `goose` invocation would
    have to be written on purpose rather than by omission.
    """
    home = goose_home(root)
    env = dict(base_env or {})
    env["HOME"] = home
    env["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    env["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
    env["XDG_STATE_HOME"] = os.path.join(home, ".local", "state")
    env["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    env["GOOSE_TELEMETRY_OFF"] = "1"
    env["GOOSE_TELEMETRY_ENABLED"] = "false"
    env["GOOSE_DISABLE_KEYRING"] = "true"
    env["GOOSE_DISABLE_SESSION_NAMING"] = "true"
    return env


# ── pure: the launch line ────────────────────────────────────────────────────
def goose_argv(root, resume_id: str = "") -> list:
    """PURE (given root). `goose session` is the interactive chat entrypoint (alias
    `s`); `run` is the headless one and would exit immediately in a tab.

    NOTHING ELSE GOES ON THIS LINE ON PURPOSE — except the resume triple, which is the
    whole of slice 2's "pick an old session and it continues where it left off".

    ⚠️ EVERY FLAG HERE WAS READ OFF THE PINNED BINARY'S OWN `--help` AND WALKED, not
    guessed (`goose session --help`, v1.48.0, measured 2026-08-29):

      --resume            "Continue from a previous session. If --name or --session-id
                           is provided, resumes that specific session."
      --session-id <ID>   "Specify a session ID to resume. **Requires --resume.**"  ← the
                          reason these two are never emitted apart.
      --history           "Show previous messages when resuming a session."  ← without
                          it a resumed session opens on an EMPTY screen and the user
                          cannot tell a resume from a fresh start. The conversation is
                          in the model's context either way; --history is what makes
                          that visible, which is the difference between the feature
                          working and the feature merely being implemented.

    ⚠️ AND `--name` IS DELIBERATELY *NOT* HERE. Measured on the same binary: `--name`
    sets the DISPLAY NAME and the id stays goose's own timestamp (`--name harness-probe-A`
    → id `20260829_1`). Naming every session ourselves would overwrite the only field a
    user can meaningfully set from inside goose, to buy a handle we already have.
    """
    sid = (resume_id or "").strip()
    if not sid:
        return [goose_bin(root), "session"]
    return [goose_bin(root), "session", "--resume", "--session-id", sid, "--history"]


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
    env = fence_env(base_env, root)
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


# ══ THE SESSION STORE — slice 2 (S9) ════════════════════════════════════════
#
# goose persists every session; before this slice the tab offered no way in, so the
# history existed and was unreachable ("it's not possible to surface any old/previous
# sessions" — Debi, 2026-08-29). Everything below was MEASURED against the pinned
# v1.48.0 binary on 2026-08-29; the measurements are pinned in
# bridge/contract_tests/test_goose_contract.py so an upstream change fails loudly
# instead of quietly emptying the strip.
#
#   F1  `goose session list --format json` → a JSON ARRAY of session objects carrying
#       id, name, user_set_name, working_dir, created_at, updated_at, message_count,
#       provider_name and model_config.model_name. (`--format` is the flag; the default
#       is `text`, whose one-line-per-session shape we do NOT parse.)
#   F2  `goose session --resume --session-id <id> --history` resumes; see goose_argv.
#   F3  The startup banner prints the session id verbatim: `20260829_1 · <cwd>`.
#       Measured on a real run. That is how we learn which persisted row is the LIVE
#       one without naming sessions ourselves.
#   F4  `goose session remove --session-id <id>` is NOT non-interactive: it prints the
#       list it is about to delete, then raises its own confirm defaulting to **No**,
#       and with no tty it dies with "Error: not connected". On a pty, `y` confirms and
#       it prints the receipt ``Session `<id>` removed.`` (rc 0). See remove_session.
#   F5  The store is ONE SQLITE FILE, `$XDG_DATA_HOME/goose/sessions/sessions.db`
#       (+ -wal/-shm). That is what the size readout measures.
#   F6  ⚠️ THE CONCURRENCY FACTS, MEASURED 2026-08-29 on the pinned binary in a scratch
#       profile (three real sessions, real turns against the live runner) — because
#       v1.5.61 shipped a guard that refused EVERY delete while ANY session ran, and
#       "one sqlite file" was an assumption, not a measurement:
#         F6a  Removing a session that is NOT the running one, while another session is
#              live, WORKS: goose prints its own receipt, `PRAGMA integrity_check` = ok,
#              the live session keeps answering, and the turns it takes AFTER the delete
#              persist (messages 5 → 8). Nothing about the store is corrupted. So the
#              old blanket refusal was over-broad and cost the user a real capability.
#         F6b  Removing the session that IS running does NOT refuse and does NOT
#              corrupt either — it DELETES, and the live window then dies mid-turn with
#              `Error: Session not found`, taking the in-flight answer with it. goose
#              has no guard of its own here. THAT is why exactly one refusal survives:
#              the live id. It protects work in progress, not the file.
#       The consequence for this module: the guard discriminates BY ID (see
#       remove_session) instead of by "is anything running".
#
# ⚠️ WHAT THIS MODULE WILL NOT DO: delete, move or rewrite anything under the store by
# hand. A live goose holds that sqlite open in WAL mode, and "delete the rows for a
# session" is a schema commitment we have no business making. Deletion goes through
# goose's own subcommand or it does not happen.

SESSIONS_REL = "data/goose/home/.local/share/goose/sessions"
SESSIONS_DB = "sessions.db"
LIST_TIMEOUT_S = 20.0
REMOVE_TIMEOUT_S = 30.0

# F3: the banner's session id. Deliberately anchored on the shape goose has used since
# it existed (YYYYMMDD_N) rather than on the surrounding decoration, which is ANSI-
# coloured and reflows with the terminal width.
SESSION_ID_RE = re.compile(r"\b(\d{8}_\d+)\b")
# Only the first slice of a session's output is sniffed. A number that merely LOOKS like
# a session id can appear in ordinary agent output an hour later; the banner is printed
# before anything else, so anything past this budget is not the banner.
SNIFF_BUDGET = 8192

# F4: goose's own words, matched literally. If either of these two sentences stops
# appearing, the prune REFUSES rather than improvising a keystroke at an unknown prompt.
REMOVE_HEADER = "The following sessions will be removed:"
REMOVE_CONFIRM = "Are you sure you want to delete these sessions?"
REMOVE_RECEIPT = "removed."

# The chip grammar (Debi's rule): a chip is at most SEVEN WORDS and never a sentence.
CHIP_WORDS = 7


def sessions_dir(root) -> str:
    return os.path.join(str(root), SESSIONS_REL)


def sessions_db_path(root) -> str:
    return os.path.join(sessions_dir(root), SESSIONS_DB)


def list_argv(root) -> list:
    """PURE. F1."""
    return [goose_bin(root), "session", "list", "--format", "json"]


def remove_argv(root, session_id: str) -> list:
    """PURE. F4. `--session-id` only — never `--regex`, which is a way to delete more
    than the user pointed at."""
    return [goose_bin(root), "session", "remove",
            "--session-id", (session_id or "").strip()]


# ── pure: the chip ───────────────────────────────────────────────────────────
def _iso_to_epoch(s) -> float:
    """PURE. goose writes RFC3339 UTC with a Z (`2026-08-29T14:04:21Z`, measured).
    Returns a real epoch. Total: anything unreadable is 0.0, which every caller renders
    as NO DATE rather than as 1970 — a wrong date on a history row is worse than none."""
    t = (s or "").strip()
    if not t:
        return 0.0
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(t.replace(" ", "T"))
    except (ValueError, TypeError, ImportError):
        return 0.0
    try:
        if dt.tzinfo is None:                # no offset at all: it is UTC by F1
            from datetime import timezone
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return 0.0


def when_label(iso) -> str:
    """PURE. 'Aug 28 · 23:14' in LOCAL time, '' when the timestamp is unreadable.

    ⚠️ LOCAL, and that is a correctness point rather than a nicety: goose stores UTC and
    `session list`'s own text output prints UTC, so a strip showing 23:14 for something
    the user did at 02:14 their time reads as somebody else's history."""
    e = _iso_to_epoch(iso)
    if e <= 0:
        return ""
    return time.strftime("%b %-d · %H:%M", time.localtime(e))


def chip_line(text, words=CHIP_WORDS) -> str:
    """PURE. At most `words` words, no trailing punctuation, never a sentence — the
    chip grammar. An over-long chip is ELIDED with '…' so the truncation is visible
    rather than being read as the whole thing."""
    s = " ".join((text or "").split())
    if not s:
        return ""
    parts = s.split(" ")
    if len(parts) > words:
        s = " ".join(parts[:words]) + "…"
    return s.rstrip(" .,:;!")


def parse_sessions(text) -> list:
    """PURE. F1's JSON → the rows the strip renders. Total: any non-array, any row that
    is not an object, any missing field costs THAT VALUE and never the list.

    ⚠️ `name` is NOT trusted as a title. With GOOSE_DISABLE_SESSION_NAMING on (which
    this lane sets, for the reason in the header) every session goose names itself is
    called "CLI Session" — a strip of five identical chips is a list that cannot be
    chosen from. `user_set_name` is the field that says whether the name means
    anything, and the router prefers a real first-message preview over a generic one.
    """
    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for row in data:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("id") or "").strip()
        if not sid:
            continue
        mc = row.get("model_config")
        model = str((mc or {}).get("model_name") or "") if isinstance(mc, dict) else ""
        try:
            msgs = int(row.get("message_count") or 0)
        except (TypeError, ValueError):
            msgs = 0
        upd = str(row.get("updated_at") or row.get("created_at") or "")
        out.append({
            "id": sid,
            "name": str(row.get("name") or ""),
            "named": bool(row.get("user_set_name")),
            "workdir": str(row.get("working_dir") or ""),
            "created": str(row.get("created_at") or ""),
            "updated": upd,
            "when": when_label(upd),
            "messages": msgs,
            "model": model,
        })
    out.sort(key=lambda r: _iso_to_epoch(r["updated"]), reverse=True)
    return out


def scan_session_id(data, seen: int = 0) -> str:
    """PURE. F3 — the session id out of the startup banner, '' when the text does not
    carry one or when we are already past the banner's byte budget.

    ⚠️ `data` IS THE ACCUMULATED BUFFER, NOT ONE CHUNK, AND THAT IS THE FIX. The first
    version scanned each pty read in isolation and found nothing on the live walk: goose
    writes its banner in several writes, and `20260829_33` straddled two of them. A
    token-shaped fact must be looked for in the whole text it lives in, never in an
    arbitrary slice of it — the general form of a bug class that would have come back
    as "sometimes the strip marks the live row and sometimes it doesn't".

    ANSI is stripped first: goose colours the banner, and an SGR sequence can sit
    between the id and the ` · ` that follows it.
    """
    if seen >= SNIFF_BUDGET:
        return ""
    try:
        s = _strip_ansi(bytes(data)[:SNIFF_BUDGET].decode("utf-8", "replace"))
    except (TypeError, ValueError):
        return ""
    m = SESSION_ID_RE.search(s)
    return m.group(1) if m else ""


# ── the store, on disk ───────────────────────────────────────────────────────
def store_size(root) -> tuple:
    """(bytes, ok). F5 — the sqlite file plus its -wal/-shm siblings, which are part of
    the database and not scratch. ok=False means we could not measure, which the footer
    renders as no number rather than as zero (absence of information is not
    information — the v1.5.51 lesson)."""
    total, seen = 0, False
    d = sessions_dir(root)
    try:
        for name in os.listdir(d):
            if not name.startswith(SESSIONS_DB):
                continue
            try:
                total += os.path.getsize(os.path.join(d, name))
                seen = True
            except OSError:
                pass
    except OSError:
        return 0, False
    return total, seen


def human_mb(n) -> str:
    """PURE. '0.7 MB'. Total; '' for anything unmeasurable."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    if v < 0:
        return ""
    if v < 1024 * 1024:
        return f"{v / 1024:.0f} KB"
    return f"{v / (1024 * 1024):.1f} MB"


def _run_fenced(root, argv, timeout, base_env=None):
    """Run the pinned binary under the fence, capturing text. (out, err)."""
    try:
        r = subprocess.run(argv, cwd=str(root),
                           env=fence_env(base_env if base_env is not None
                                         else os.environ, root),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", f"goose did not answer within {int(timeout)}s"
    except OSError as e:
        return "", f"could not run goose: {e}"
    if r.returncode != 0:
        return r.stdout or "", (r.stderr or r.stdout or "").strip()[-400:]
    return r.stdout or "", ""


def list_sessions(root, base_env=None) -> tuple:
    """(rows, error). F1 through goose's own CLI — the AUTHORITY on what exists.

    ⚠️ NOT read out of the sqlite. The schema is upstream's private business and it has
    a migration table in it; the CLI is the contract we can pin and the one that will be
    kept working. (The one-line PREVIEW below is the deliberate exception, and it is a
    nice-to-have that degrades to nothing.)"""
    ok, _p, reason = is_installed(root)
    if not ok:
        return [], reason
    out, err = _run_fenced(root, list_argv(root), LIST_TIMEOUT_S, base_env)
    if err and not out.strip().startswith("["):
        return [], err
    return parse_sessions(out), ""


def previews(root, ids) -> dict:
    """{id: first-user-line}. BEST-EFFORT, READ-ONLY, AND ALLOWED TO RETURN NOTHING.

    ⚠️ THIS IS THE ONE PLACE THAT TOUCHES THE SQLITE, AND IT IS A SOFT COUPLING ON
    PURPOSE — stated out loud rather than discovered later (ledger U18). The CLI has no
    preview to offer (`last_message_snippet` is null on every row we measured) and a
    strip whose chips all read "CLI Session" is a list nobody can choose from, so the
    first user message is what makes the feature usable. Every failure mode — no
    sqlite3, a moved file, a renamed table, a changed content shape — returns {} and the
    strip falls back to the session name. It opens `mode=ro` and never writes.

    goose prepends a `<turn-context>` block to the user's text as its own message; those
    are skipped, because showing the harness's scaffolding as 'what you asked' is a lie
    about the user's own history.
    """
    want = {str(i) for i in (ids or []) if str(i)}
    if not want:
        return {}
    try:
        import sqlite3
    except Exception:                                            # noqa: BLE001
        return {}
    p = sessions_db_path(root)
    if not os.path.isfile(p):
        return {}
    out: dict = {}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = con.execute(
                "SELECT session_id, content_json FROM messages "
                "WHERE role='user' ORDER BY created_timestamp ASC").fetchall()
        finally:
            con.close()
    except Exception:                                            # noqa: BLE001
        return {}
    for sid, cj in rows:
        sid = str(sid)
        if sid not in want or sid in out:
            continue
        try:
            blocks = json.loads(cj or "")
        except (ValueError, TypeError):
            continue
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict) or b.get("type") != "text":
                continue
            txt = str(b.get("text") or "").strip()
            if not txt or txt.startswith("<turn-context>"):
                continue
            out[sid] = chip_line(txt)
            break
    return out


# ── the prune: goose's OWN deletion mechanism, driven honestly ───────────────
def remove_session(root, session_id: str, base_env=None) -> tuple:
    """(ok, message). Delete ONE session through `goose session remove`.

    ⚠️ WHY THIS IS A PTY AND NOT A `subprocess.run`. MEASURED (F4): the subcommand takes
    an explicit `--session-id` and STILL raises its own confirmation, defaulting to No;
    with no tty it dies "Error: not connected" and deletes nothing. Upstream offers no
    --yes. So the choice was: delete rows out of the sqlite ourselves (refused — see the
    block header), or answer goose's own prompt on a real terminal.

    ⚠️ AND ANSWERING A PROMPT IS ONLY SAFE IF YOU READ IT FIRST. The protocol is:
      1. goose prints "The following sessions will be removed:" and one `- <id> …` line
         per session. We require EXACTLY ONE such line and that its id is the one the
         user pointed at. Anything else — two lines, a different id, no header — and we
         close our own child and delete nothing.
      2. Only then, after goose's own confirm sentence has appeared verbatim, do we
         send `y`.
      3. We report success only on goose's own receipt line. "The process exited 0" is
         not evidence that anything was deleted; the receipt is.
    Every deviation is a refusal with a sentence, never a retry with a different key.

    ⚠️ THE GUARD IS PER-SESSION, NOT PER-LANE (v1.5.64, correcting v1.5.61). The first
    version refused while ANY session ran, on the theory that a live goose holds the
    sqlite open. Measured (F6): it holds it open in WAL mode and a delete of a DIFFERENT
    session is completely uneventful — receipt, integrity ok, live session unharmed and
    still persisting its later turns. The refusal that IS earned is the LIVE ID: goose
    will cheerfully delete the session it is running and the window then dies mid-answer
    (F6b). So the rule is: everything else deletes; the live one says one sentence and
    names the one action that unblocks it.
    """
    sid = (session_id or "").strip()
    if not sid:
        return False, "no session was named"
    if not SESSION_ID_RE.fullmatch(sid):
        # The id goes on a command line. Nothing but goose's own id shape may.
        return False, f"{sid!r} is not a goose session id"
    ok, _p, reason = is_installed(root)
    if not ok:
        return False, reason
    if busy():
        live = live_id()
        if not live:
            # A session IS running but has not printed its id yet (the banner arrives a
            # second or two after the spawn — see routers/goose.py::_sniff_id). We
            # cannot tell whether the user just pointed at THAT session, and deleting
            # blind is exactly the F6b accident. Refuse for a moment, and say why.
            return False, ("a session just started and has not said which one it is "
                           "yet — try again in a moment, or End it first")
        if live == sid:
            return False, ("that session is live — End it first, then delete it "
                           "(goose would delete it out from under the running window "
                           "and the answer in progress would be lost)")
    import pty as _pty
    import select as _select
    master, slave = _pty.openpty()
    try:
        set_winsize(master, 100, 30)
        proc = subprocess.Popen(
            remove_argv(root, sid), cwd=str(root),
            env=fence_env(base_env if base_env is not None else os.environ, root),
            stdin=slave, stdout=slave, stderr=slave,
            close_fds=True, start_new_session=True)
    except OSError as e:
        os.close(master)
        os.close(slave)
        return False, f"could not run goose: {e}"
    finally:
        try:
            os.close(slave)
        except OSError:
            pass
    buf, sent, deadline = "", False, time.time() + REMOVE_TIMEOUT_S
    try:
        while time.time() < deadline:
            r, _w, _x = _select.select([master], [], [], 0.25)
            if r:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
            if not sent and REMOVE_CONFIRM in buf:
                listed = _removal_targets(buf)
                if listed != [sid]:
                    return False, ("goose offered to delete "
                                   f"{listed or 'nothing we could read'} — not the one "
                                   "session you picked. Nothing was deleted.")
                os.write(master, b"y")
                sent = True
            if f"`{sid}` {REMOVE_RECEIPT}" in buf:
                return True, f"session {sid} deleted"
            if proc.poll() is not None and not r:
                break
        if not sent:
            return False, ("goose did not ask its own confirmation, so nothing was "
                           "answered and nothing was deleted"
                           + (f" — it said: {buf.strip()[-200:]}" if buf.strip() else ""))
        return False, ("goose did not confirm the deletion; nothing is assumed. "
                       f"It said: {buf.strip()[-200:]}")
    finally:
        # PROCESS-KILL RULE: our OWN child handle, spawned three lines up, never a
        # pattern and never a port.
        kill_process_group(proc)
        try:
            os.close(master)
        except OSError:
            pass


def _removal_targets(text) -> list:
    """PURE. The ids on goose's own "will be removed" list, in order. '' input → []."""
    out, seen_header = [], False
    for raw in (text or "").splitlines():
        line = _strip_ansi(raw).strip()
        if REMOVE_HEADER in line:
            seen_header = True
            continue
        if not seen_header:
            continue
        if not line.startswith("- "):
            break
        m = SESSION_ID_RE.match(line[2:].strip())
        if not m:
            break
        out.append(m.group(1))
    return out


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")


def _strip_ansi(s) -> str:
    """PURE. goose colours its own output; the words are what we match on."""
    return _ANSI_RE.sub("", s or "")


# ── the pidfile (the memory ledger's handle) ─────────────────────────────────
def write_pidfile(root, pid: int) -> tuple[int, str]:
    """Record the exact child handle; failure is fatal to the new session."""
    return _ownership.record_child(Path(root), "goose", int(pid))


def clear_pidfile(root, pid: int, birth: str) -> bool:
    """Retire only this session generation, including after the child has exited."""
    return _ownership.retire_owned(Path(root), "goose", int(pid), str(birth or ""))


def reap_orphan(root, base_env=None) -> str:
    """Called once when the bridge comes up. Returns 'none' | 'stale' | 'reaped' | the
    kill verdict.

    ⚠️ WHY THIS EXISTS, AND IT IS A CONSEQUENCE OF THIS SLICE. Before the detach fix a
    goose session lived exactly as long as a websocket, so a bridge restart could not
    leave one behind for long. Now a session deliberately OUTLIVES its socket — and it
    is spawned with start_new_session=True, so it also outlives the bridge. A restart
    would leave an orphan holding the workspace with no handle on it, while a new tab
    happily claimed the (now empty) slot and started a SECOND goose on the same
    directory. That is the exact shape the one-at-a-time claim exists to prevent, so
    the fix belongs here and not in a ledger row.

    ⛔ PROCESS-KILL RULE, IN FULL. The ONLY pid considered is the one in OUR reporting
    file, and it is signalled only while the exact PID+kernel-birth record written from
    the original Popen child still matches under the shared lock. A recycled pid,
    Debi's standalone goose, a matching command/path/CWD, and a legacy bare pidfile
    authorize nothing. Never a pattern, never a port.
    """
    claim = _ownership.read_claim(Path(root), "goose")
    pid = _ownership.read_pid_report(Path(root), "goose")
    if not claim:
        if pid is None and not os.path.lexists(pidfile_path(root)):
            return "none"
        # An empty expected birth can clean legacy bookkeeping but can never match a
        # complete claim, so a concurrent launch is neither signalled nor erased.
        _ownership.signal_owned(
            Path(root), "goose", expected_pid=pid or 0, expected_birth="", force=True)
        return "stale"
    pid = claim[0]
    birth = claim[1]
    sent, _detail = _ownership.signal_owned(
        Path(root), "goose", expected_pid=pid, expected_birth=birth,
        retire=False, group=True)
    if not sent:
        return "unverified"
    for _ in range(50):
        if _ownership.process_birth(pid) != birth:
            _ownership.retire_owned(Path(root), "goose", pid, birth)
            return "reaped:term"
        time.sleep(0.1)
    sent, _detail = _ownership.signal_owned(
        Path(root), "goose", expected_pid=pid, expected_birth=birth,
        force=True, group=True)
    return "reaped:kill" if sent else "unverified"


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


def live_id() -> str:
    """The RUNNING session's own goose id, '' when nothing runs — and ALSO '' when
    something runs whose banner we have not read yet. The two are told apart by
    busy(), deliberately: a caller that needs to discriminate (remove_session) must
    handle the don't-know state explicitly rather than reading '' as 'nothing runs'."""
    s = current()
    if s is None or not s.alive():
        return ""
    return (getattr(s, "session_id", "") or "").strip()


def kill_current() -> str:
    """Used by the status/teardown paths; harmless when nothing runs."""
    s = current()
    if s is None:
        return "gone"
    how = s.close()
    release(s)
    return how
