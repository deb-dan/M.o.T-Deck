"""goose DECLARATIVE CUSTOM PROVIDER — "MOT Deck (local)", in goose's own file format.

v1.5.49 slice (S-ISO-4). This closes the honest limit v1.5.40 recorded verbatim:
*"custom openai_compatible provider unbuilt (stock openai seeding proven; three on-disk
custom layouts all 'Unknown provider')"*.

⚠️ NOTHING IN THIS FILE IS GUESSED. THE SCHEMA WAS READ OFF A FILE GOOSE ITSELF WROTE.
The method (2026-08-29, goose v1.48.0, our fenced ui-home, driven through the REAL
renderer at http://127.0.0.1:8700/gooseui/):

  1. Settings → Models → Configure providers → "+" → **Configure manually**.
  2. Provider Type = OpenAI Compatible · Display Name = "MOT Deck (local)" ·
     API URL = http://127.0.0.1:6767 · requires-API-key ON, key = the runner's ·
     Available Models = two real registry ids · streaming ON.
  3. Create Provider. The renderer sent, over its ACP websocket:
        {"jsonrpc":"2.0","id":35,
         "method":"_goose/unstable/providers/custom/create",
         "params":{"engine":"openai_compatible","displayName":"MOT Deck (local)",
                   "apiUrl":"http://127.0.0.1:6767","apiKey":"…",
                   "models":[…],"supportsStreaming":true,"headers":{},
                   "requiresAuth":true,"catalogProviderId":null,"basePath":null,
                   "preservesThinking":null}}
  4. goose then wrote, ITSELF:
        <config dir>/custom_providers/custom_mot_deck__local.json   (the schema below)
        <config dir>/secrets.yaml   →  CUSTOM_MOT_DECK__LOCAL_API_KEY: <key>

THE FOUR FACTS THAT KILLED THE THREE EARLIER GUESSES, in the order they matter:

  F1  THE DIRECTORY IS `<config dir>/custom_providers/`, ONE JSON FILE PER PROVIDER —
      never a `custom_providers:` key inside config.yaml. And "config dir" differs
      per lane: the EMBED lane is GOOSE_PATH_ROOT-fenced (`…/ui-home/goose/config/`)
      while the CLI lane is XDG-fenced (`…/home/.config/goose/`). Both were walked
      live; see goose_config_dir() callers.
  F2  THE FILE'S `engine` IS `"openai"`, NOT the form's `"openai_compatible"`. The
      form's value is a UI-level enum that goose maps down on the way to disk.
      (Measured: `"openai_compatible"` in the FILE also loads at this pin, so the
      engine was not the whole blocker — but `"openai"` is what goose writes, and
      writing what goose writes is the only shape a future version is obliged to
      keep reading.)
  F3  THE KEY IS NAMED, NOT INLINE. `api_key_env` holds an ENV VAR NAME
      (`CUSTOM_MOT_DECK__LOCAL_API_KEY` = the provider name upper-cased + `_API_KEY`).
      ⚠️ MEASURED PRECEDENCE: the PROCESS ENVIRONMENT WINS over `secrets.yaml` — a
      correct key in secrets.yaml with a wrong one in the env produced
      `401 Invalid API Key`. So we hand the key to the child in its env and NEVER
      write the user's secret store. `HARNESS_RUNNER_API_KEY` (gooseui.py's older
      guess at this name) is kept in the env as well, but it is NOT what goose reads.
  F4  `base_url` IS THE ORIGIN AND `base_path` STAYS NULL. goose composes
      `http://127.0.0.1:6767` + its openai default path; the request that actually
      reached llama-server was `http://127.0.0.1:6767/v1/chat/completions` (read off
      the 401 in the precedence probe). Handing it the `…/v1` base would produce
      `/v1/v1/…` — the same trap pty_goose.openai_host exists for.

TWO MORE MEASURED FACTS THAT SHAPE THE WRITER:

  F5  THE CREATE CALL IS NOT IDEMPOTENT. Submitting the same display name twice gave
      `custom_mot_deck__local` AND `custom_mot_deck__local_1` — two identical rows in
      the picker. So the seed writes THE FILE, by its stable name, and never drives
      the create API. Our name is goose's OWN slug for our display name, which is what
      makes a provider the user later edits in goose's form still be ours.
  F6  ENV `GOOSE_PROVIDER` OVERRIDES CONFIG `active_provider` — measured both ways on
      the pinned binary. That is a pre-existing never-clobber violation in both lanes:
      a user who switched provider inside goose got the switch silently undone at the
      next spawn. provider_choice() below is the fix.

Everything here is PURE and table-tested in bridge/tests/test_goose_lane.py and
bridge/tests/test_gooseui_lane.py; the file SHAPE is contract-pinned in
bridge/contract_tests/test_goose_contract.py. A goose bump re-runs the census (house
rule for every vendored component).
"""
from __future__ import annotations

import json
import os
import re

# ── identity ─────────────────────────────────────────────────────────────────
# The product name, spelled once. Same string OpenCode's provider carries
# (scripts/start_component.sh) — one product, one name in every vendor picker.
DISPLAY_NAME = "MOT Deck (local)"

# ⚠️ NOT INVENTED: this is the slug GOOSE ITSELF derived from DISPLAY_NAME when its own
# form created the provider. slugify() reproduces the rule so the two can never drift,
# and PROVIDER_NAME is asserted equal to slugify(DISPLAY_NAME) in the contract test.
PROVIDER_NAME = "custom_mot_deck__local"

ENGINE = "openai"                      # F2 — the FILE's value, not the form's
DIR_NAME = "custom_providers"          # F1
DESCRIPTION = f"Custom {DISPLAY_NAME} provider"

# The provider we used to ride anonymously, and the ONLY value of `active_provider` we
# are allowed to migrate away from: it is OUR OWN previous seeding, not a user's pick.
LEGACY_PROVIDER = "openai"

# goose's own form writes a number here for every model; the registry does not carry one
# for any resident model today (`ctx` is unset on all 20 rows), so this is the value the
# form itself defaulted to. It is a LIMIT, not a claim about the weights.
DEFAULT_CONTEXT = 128000

# The keys of the provider file WE own and refresh on every seed, because each of them is
# a fact about our runner that must stay true or the provider lies about where it points.
# EVERYTHING ELSE IN THE FILE IS THE USER'S and is preserved byte-for-byte — display_name
# above all (the walked never-clobber journey), plus headers, base_path, requires_auth,
# supports_streaming and any key a future goose adds that we have never heard of.
OWNED_KEYS = ("engine", "base_url", "api_key_env", "models")


def slugify(display: str) -> str:
    """PURE. goose's own display-name → provider-name rule, reproduced from its output.

    Observed: "MOT Deck (local)" → "custom_mot_deck__local". Lower-cased, every run of
    non-alphanumeric characters that is a SINGLE character becomes `_` (so the space and
    the `(` each contribute one, which is where the DOUBLE underscore comes from — a
    collapsing slugifier would have produced `mot_deck_local` and we would be writing a
    file goose's form could never match), trailing separators trimmed, `custom_` prefix.
    """
    s = (display or "").strip().lower()
    s = "".join(ch if ch.isalnum() else "_" for ch in s)
    s = s.strip("_")
    return f"custom_{s}" if s else "custom_provider"


def api_key_env(name: str = PROVIDER_NAME) -> str:
    """PURE. The env var goose reads the key from: NAME.upper() + '_API_KEY' (F3)."""
    return f"{(name or PROVIDER_NAME).upper()}_API_KEY"


# ── pure: paths ──────────────────────────────────────────────────────────────
def providers_dir(config_dir) -> str:
    """`<config dir>/custom_providers` — F1. The caller supplies the config dir because
    THE TWO LANES FENCE DIFFERENTLY and pretending otherwise is how one lane silently
    gets no provider at all: the embed's is GOOSE_PATH_ROOT/config, the CLI's is
    XDG_CONFIG_HOME/goose."""
    return os.path.join(str(config_dir), DIR_NAME)


def provider_path(config_dir, name: str = PROVIDER_NAME) -> str:
    return os.path.join(providers_dir(config_dir), f"{name}.json")


# ── pure: the runner → the provider's base_url ───────────────────────────────
def base_url(endpoint, port=6767) -> str:
    """PURE. F4: the ORIGIN, with a trailing `/v1` stripped.

    Deliberately the same rule (and the same trap) as pty_goose.openai_host — goose
    appends its own path, so handing it `…:6767/v1` yields `/v1/v1/chat/completions`,
    a 404 that reads to a user as "the model is broken"."""
    s = (endpoint if isinstance(endpoint, str) else "").strip().rstrip("/")
    if s.endswith("/v1"):
        s = s[: -len("/v1")]
    if not s.startswith("http://") and not s.startswith("https://"):
        try:
            return f"http://127.0.0.1:{int(port)}"
        except (TypeError, ValueError):
            return "http://127.0.0.1:6767"
    return s


# ── pure: the model list ─────────────────────────────────────────────────────
def model_entries(registry, wire_of=None) -> list:
    """PURE. Every CHAT model in our registry, as goose's model objects.

    ⚠️ THE NAME IS THE WIRE IDENTIFIER, AND FOR MLX THAT IS A FILESYSTEM PATH. goose's
    declarative model object has exactly ONE identifier slot (`name`) — it is both the
    picker label and what goes on the wire. OpenCode's provider has two and we use both
    (key vs `id`); here there is no second slot, so correctness wins: an MLX row reads as
    its path in goose's picker, because a pretty label that 400s is a lie and a path that
    works is merely ugly. Named as an honest limit in the report.

    ⚠️ AND THE LIST IS WRITTEN, NOT PROBED — OpenCode's property, for its reason: goose's
    picker renders what the provider file says, so the models stay listed with the runner
    down instead of the tab going empty at the worst possible moment.

    Audio models are excluded (`kind == "audio"`), hidden ones too, and duplicate ids are
    collapsed keeping first-seen order.
    """
    # S29 — WHICH ROWS is not this function's decision any more. core/modelreg.offerable
    # is the one definition (chat · not hidden · not flagged absent · file not provably
    # gone), shared with the Odysseus, Hermes and OpenCode seeders. The file clause is
    # what stops goose's picker offering weights the user deleted in LM Studio.
    from .core.modelreg import offerable, wire_id
    out, seen = [], set()
    for m in offerable(registry):
        mid = str(m.get("id") or "").strip()
        wire = str(wire_of(mid) or mid) if callable(wire_of) else wire_id(m)
        if wire in seen:
            continue
        seen.add(wire)
        try:
            ctx = int(m.get("ctx") or 0)
        except (TypeError, ValueError):
            ctx = 0
        out.append({
            "name": wire,
            "context_limit": ctx if ctx > 0 else DEFAULT_CONTEXT,
            "input_token_cost": None,
            "output_token_cost": None,
            "currency": None,
            "supports_cache_control": None,
            # Three-valued in our registry; goose's field is a bool. Only a MEASURED
            # true is asserted — unknown reads as false, which is upstream's own default.
            "reasoning": bool(m.get("reasoning") is True),
        })
    return out


def provider_doc(url: str, models: list, display: str = DISPLAY_NAME,
                 name: str = PROVIDER_NAME) -> dict:
    """PURE. The whole file, in the shape and key order goose's own form produced.

    Writing the FULL shape (rather than the minimal one that also loads — measured) is
    deliberate: it is the document goose's own editor round-trips, so a user who opens
    our provider in that form and presses Update does not silently lose fields.
    """
    return {
        "name": name,
        "engine": ENGINE,
        "display_name": display,
        "description": DESCRIPTION,
        "api_key_env": api_key_env(name),
        "base_url": url,
        "models": list(models or []),
        "headers": None,
        "timeout_seconds": None,
        "supports_streaming": True,
        "requires_auth": True,
        "catalog_provider_id": None,
        "base_path": None,
        "env_vars": None,
        "dynamic_models": None,
        "skip_canonical_filtering": False,
        "model_doc_link": None,
        "setup_steps": [],
        "fast_model": None,
        "preserves_thinking": True,
        "emit_clear_thinking": False,
        "setup": None,
    }


def merge_provider(existing, ours: dict) -> dict:
    """PURE. MERGE, NEVER OVERWRITE — the never-clobber rule, as a table.

    Start from what is on disk (so a key a future goose adds, or a header the user typed,
    survives untouched) and replace ONLY OWNED_KEYS. `display_name` is emphatically not
    ours: the walked journey is "rename it by hand, re-seed, the rename is still there".

    A file that is not a JSON object (corrupt, or a directory the user put there) is
    treated as absent rather than as a reason to refuse — we write our own document and
    the user's unreadable one is what was lost, which the caller reports.
    """
    if not isinstance(existing, dict):
        return dict(ours)
    out = dict(existing)
    for k in OWNED_KEYS:
        # ⚠️ AN EMPTY MODEL LIST IS NEVER A DECISION (S29, found in this slice's own
        # adversarial pass). Until now the only way `models` came back empty was an
        # unreadable data/models.json for one Start; the shared enumeration rule adds a
        # second way — every artifact answering "gone" at once, which is exactly what an
        # UNPLUGGED EXTERNAL DISK looks like for one poll. Writing that through would
        # empty goose's picker over a cable, and the next seed with the disk back would
        # not undo the confusion. The rule the other three seeders already hold, spelled
        # here: when we learned nothing, we change nothing — the previous list stands.
        if k == "models" and not ours.get(k) and existing.get(k):
            continue
        out[k] = ours[k]
    # `name` is the file's own identity and must match the filename or goose indexes it
    # under a name nothing references. It is repaired, not preserved.
    out["name"] = ours["name"]
    return out


# ── the writer ───────────────────────────────────────────────────────────────
def read_provider(config_dir, name: str = PROVIDER_NAME):
    try:
        with open(provider_path(config_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def seed_provider(config_dir, endpoint, registry, port=6767,
                  name: str = PROVIDER_NAME) -> tuple:
    """(path, changed, error). Write/refresh OUR provider file only.

    ⚠️ ONE FILE, BY NAME, NEVER THE DIRECTORY. `custom_providers/` is also where the
    USER's own creations live (goose's form writes them there), so a seeder that
    rewrote the directory would delete work goose told them was saved.

    Best-effort like every other seed in these lanes: a read-only config dir costs the
    provider, never the launch — the caller falls back to the stock openai wiring, which
    is still in the env.
    """
    p = provider_path(config_dir, name)
    ours = provider_doc(base_url(endpoint, port), model_entries(registry), name=name)
    try:
        merged = merge_provider(read_provider(config_dir, name), ours)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        new = json.dumps(merged, indent=2) + "\n"
        try:
            with open(p, encoding="utf-8") as fh:
                cur = fh.read()
        except OSError:
            cur = ""
        if new == cur:
            return p, False, ""
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(tmp, p)
        return p, True, ""
    except OSError as e:                                              # noqa: BLE001
        return p, False, str(e)


# ── pure: the main-model setting, and how NOT to silently change it ──────────
_ACTIVE_RE = re.compile(r"^active_provider:\s*(.*?)\s*$", re.M)


def active_provider(config_text: str) -> str:
    """PURE. The `active_provider:` value in a goose config.yaml, '' when absent.

    A TEXT READ, never a YAML parse — the same rule the two upsert_config writers follow,
    and here it also means a config we cannot parse degrades to "no opinion" (which
    leaves the user's setting alone) instead of to an exception."""
    ms = _ACTIVE_RE.findall(config_text or "")
    if not ms:
        return ""
    # ⚠️ THE LAST ONE, not the first. A duplicated top-level key is legal text and
    # PyYAML — which is what goose's own loader behaves like — keeps the LAST. Reading
    # the first would let a line WE appended earlier mask a choice the user made after
    # it, i.e. it would read our own writing as their consent. When in doubt about whose
    # setting this is, the newer line is the answer.
    return ms[-1].strip().strip("'\"")


def provider_choice(config_text: str, name: str = PROVIDER_NAME) -> tuple:
    """PURE. (env_provider, migrate) — the whole main-model migration policy.

    THE POLICY, AND WHY (F6: env GOOSE_PROVIDER beats config active_provider, measured):

      * no `active_provider` yet, or it is `openai` (OUR OWN previous anonymous seeding),
        or it is already ours  →  ("<ours>", True). This is the deliberate migration: the
        provider LABEL changes from goose's stock OpenAI to "MOT Deck (local)" while the
        endpoint, the key and the wire model are the same three values as before, so no
        session and no turn changes behaviour. Stated in the report, not smuggled.
      * ANY other value — a second custom provider, an Anthropic key the user added,
        anything at all  →  ("", False): we set NEITHER GOOSE_PROVIDER nor GOOSE_MODEL
        in the env and we do not touch the config. Their choice wins. Before this
        function existed, every spawn silently overrode it.

    Note the model travels WITH the provider: forcing GOOSE_MODEL onto somebody else's
    provider is the same class of override as forcing the provider.
    """
    cur = active_provider(config_text)
    if cur in ("", LEGACY_PROVIDER, name):
        return name, True
    return "", False


# ── THE SHARED "DANGLES" RULE (S28, the post-switch coherence audit §5.2) ────
# The three-state rule — SEED when unset, REPLACE when the configured choice DANGLES,
# HONOUR otherwise — existed in exactly two places (OpenCode's default-model block and
# seed_odysseus_jan.settings_plan) and nowhere else. goose's `providers.<slug>.model`
# honoured unconditionally, which is how a model deleted a week earlier stayed on the
# Goose UI chip while llama.cpp quietly answered every turn with the model it actually
# had loaded. This is the definition, spelled ONCE, so the next seeder can import it
# instead of re-deriving it slightly differently.
def dangles(name, offered, served: str = "") -> bool:
    """PURE. Does `name` point at nothing real?

    DANGLING = neither offered by us (not in the registry-derived list this provider
    advertises) NOR actually served by the runner right now. The `served` half matters:
    a user running a model we do not index is making a legitimate choice, and an
    aggressive "not in our list ⇒ replace it" would clobber it. An EMPTY `offered` is
    not information (an unreadable registry for one Start) and never makes anything
    dangle — the same absence-is-not-information rule the seed's model lists obey.
    """
    n = str(name or "").strip()
    if not n:
        return False                      # unset is "seed me", not "repair me"
    off = [str(x) for x in (offered or [])]
    if not off:
        return False
    if served and n == str(served).strip():
        return False
    return n not in set(off)


# ── pure: goose's OWN nested `providers.<slug>.model` key ────────────────────
# ⚠️ A TEXT EDIT, NEVER A YAML ROUND-TRIP — same rule and same reason as
# upsert_config: this config carries 20 extensions goose wrote itself plus whatever the
# user added, and a dumper round-trip would silently reshape all of it. These two are
# nested (upsert_config only reaches top-level keys), so they walk the block by indent.
def _providers_walk(config_text: str, name: str):
    """Yield (index, line, in_our_block) over the lines of the `providers:` mapping.
    Also reports the sub-indent goose used, so we never hard-code two spaces."""
    lines = (config_text or "").splitlines()
    in_p = False
    sub = None
    in_ours = False
    for i, ln in enumerate(lines):
        if ln and not ln[0].isspace():
            in_p = ln.rstrip() == "providers:"
            in_ours = False
            continue
        if not in_p or not ln.strip():
            continue
        ind = len(ln) - len(ln.lstrip())
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+):\s*$", ln)
        if m and (sub is None or ind == sub):
            sub = ind
            in_ours = m.group(1) == name
            continue
        yield i, ln, in_ours
    return


def provider_model(config_text: str, name: str = PROVIDER_NAME) -> str:
    """PURE. `providers.<name>.model` as goose wrote it, '' when absent/unreadable."""
    for _i, ln, ours in _providers_walk(config_text, name):
        if not ours:
            continue
        m = re.match(r"^\s*model:\s*(.*?)\s*$", ln)
        if m:
            return m.group(1).strip().strip("'\"")
    return ""


def set_provider_model(config_text: str, value: str,
                       name: str = PROVIDER_NAME) -> str:
    """PURE. Rewrite `providers.<name>.model` IN PLACE, byte-preserving everything else.

    ⚠️ IT NEVER CREATES THE BLOCK. If goose has no `providers:` mapping, or no entry for
    our slug, the text comes back unchanged: this key is GOOSE'S (it writes it when the
    user picks a model), and our licence extends to repairing a value that points at
    nothing — not to inventing a choice the user never made.
    """
    lines = (config_text or "").splitlines()
    for i, ln, ours in _providers_walk(config_text, name):
        if ours and re.match(r"^\s*model:\s*", ln):
            ind = ln[: len(ln) - len(ln.lstrip())]
            lines[i] = f"{ind}model: {value}"
            return "\n".join(lines).strip("\n") + "\n"
    return config_text or ""


def repair_config_model(config_path: str, offered, served: str = "",
                        name: str = PROVIDER_NAME) -> tuple:
    """(old, new, changed, error) — repair a DANGLING `providers.<slug>.model` on disk.

    The one case "seeded, never enforced" (F6's never-clobber fix) must treat as
    repairable, per the audit. A working choice is honoured for ever; a choice that
    names a model neither offered nor served is not a choice any more, it is a ghost.
    Best-effort like every other writer in this lane: an unreadable config costs the
    repair, never the launch.
    """
    try:
        with open(config_path, encoding="utf-8") as fh:
            cur = fh.read()
    except OSError as e:
        return "", "", False, str(e)
    old = provider_model(cur, name)
    if not old or not dangles(old, offered, served) or not served:
        return old, old, False, ""
    new_text = set_provider_model(cur, served, name)
    if new_text == cur:
        return old, old, False, ""
    try:
        tmp = config_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        os.replace(tmp, config_path)
    except OSError as e:
        return old, old, False, str(e)
    return old, served, True, ""


# The config.yaml keys OUR seeding used to own and now must REMOVE when it migrates: goose
# itself deletes them the moment the user switches provider through its UI (measured — it
# rewrites the file as `providers:` + `active_provider:`), so leaving them behind would
# leave two sources of truth for one setting, one of them ours and stale.
LEGACY_CONFIG_KEYS = ("GOOSE_PROVIDER", "GOOSE_MODEL")
