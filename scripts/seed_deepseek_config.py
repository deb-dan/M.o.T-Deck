#!/usr/bin/env python3
"""Point the DeepSeek Harness lane at OUR runner: one named provider + the default.

WRITES exactly two sections of $DSH_HOME/settings.yaml and nothing else:

  llm-pi-ai.providers["mot-deck"]   the OpenAI-compatible route -> MOT Deck runner,
                                    with the registry's models enumerated as facts.
  agent-default-model              {provider, model} — SEEDED when unset, REPLACED
                                    when it dangles against OUR route, HONOURED
                                    otherwise (the three-state rule every seeder in
                                    this repo implements).

Being a script instead of a heredoc is what lets the bridge call it — from the model
switch fan-out (routers/models._rebind_dependents) and from RESCAN — so the catalog
tracks the registry without a component restart. The shell arm calls the same file with
the same environment, so there is exactly ONE implementation. (That rule exists because
OpenCode's catalog was a heredoc and spent days advertising models Debi had deleted:
docs/research/2026-08-29-post-switch-audit.md §1.)

ENV (all read here, nothing implicit):
  DS_SETTINGS    the settings document ($DSH_HOME/settings.yaml)
  DS_BASE        the runner's base url (e.g. http://127.0.0.1:6767/v1)
  DS_KEY_ENV     the NAME of the env var dsh should read the key from (not the key)
  DS_MODEL       the model to seed a default from (a CANDIDATE, never an answer)
  MOT_DECK_ROOT   where data/models.json lives (default: cwd)

⚠️ `DS_`, NOT `DSH_`, AND THAT IS DELIBERATE RATHER THAN TERSE. `DSH_*` is UPSTREAM'S
OWN environment namespace — DSH_HOME, DSH_TELEMETRY_DISABLED, DSH_TELEMETRY_MODE,
DSH_ENV_PREFIX, DSH_BOOT__*, and eighteen more at this pin — and the child process
inherits our environment. A variable of ours called DSH_SETTINGS would sit in the same
namespace dsh reads from and would collide the day upstream adds a settings-path
override by that name, which is a plausible name for them to pick. (The first draft of
this file used DSH_* and the shell arm used DS_*; the mismatch meant the seeder saw
nothing and refused with "DS_SETTINGS not set" on the first real walk of the lane —
caught there, which is exactly what the walk is for.)

stdlib + PyYAML only.


═══ THE FIVE FACTS THIS FILE IS BUILT ON, ALL MEASURED AT PIN 0.1.1-rc.2 ═══════════

F1  `providers` IS A DICT KEYED BY ROUTE ID, and the pre-release ARRAY shape "fails
    load with migration directions" (dsh-llm-pi-ai README). Our route id is `mot-deck`
    and it is the STABLE KEY across every seed — never a display name, which the user
    may rename. `mot-deck` is also inside dsh's credential-record grammar (lowercase,
    hyphen), so it is a route the user could additionally sign into by hand if they
    ever wanted to; `apiKeyEnv` outranks that anyway ("the request's `apiKey` option,
    which pi-ai treats as the highest-priority auth override").

F2  A HAND-DECLARED ROUTE NEEDS `api`, `baseURL`, AND A NON-EMPTY `models` LIST, or
    resolution "fails loud, naming the offending route and model". ⚠️ AND THE FAILURE
    IS NOT SCOPED TO US: "the settings seam keeps a namespace's last good value for an
    already-stored section that fails" — i.e. an unserviceable block we wrote would
    take out the WHOLE `llm-pi-ai` namespace, every other route the user configured
    included. That is why an empty enumeration REFUSES TO WRITE rather than writing a
    placeholder the way seed_opencode_config.py can afford to (OpenCode merely deletes
    a models-less provider; dsh rejects the section).

F3  THE KEY IS NAMED, NOT INLINE. `apiKeyEnv` holds an ENV VAR NAME, resolved per
    request; "a configured reference that resolves to nothing fails the request with
    MISSING_CREDENTIAL instead" of falling through to some unrelated ambient key. So
    the secret NEVER enters this file, exactly like the goose lanes — and
    start_component.sh is what puts the value in the child's environment under that
    name. The name itself is DERIVED, not chosen twice: see key_env_name().
    ⚠️ dsh has no `${env:VAR}` value indirection ("a deferred seam-level feature"), so
    apiKeyEnv is the only way to keep the key out of the document.

F4  THE WIRE-COMPAT MEASUREMENT, run against a request-capturing server so the answers
    are the bytes on the wire and not a reading of the docs. For a hand-declared model:

      route config                             system role   output cap
      ---------------------------------------  ------------  -------------------------
      (bare)                                   system        max_completion_tokens
      + compat.maxTokensField: max_tokens      system        max_tokens
      + reasoningEfforts on the model          DEVELOPER     max_completion_tokens
      + …and compat.supportsDeveloperRole:false  system      max_completion_tokens

    And on OUR side of the wire:
      · llama.cpp b10662 ACCEPTS all of it — `developer` role, `max_completion_tokens`,
        `max_tokens`, `reasoning_effort` (four curls, all 200).
      · mlx_lm.server 0.31.3 reads `max_completion_tokens` first and falls back to
        `max_tokens` (server.py:1169-1172), so the cap spelling is a no-op there too —
        but ROLES go straight into the tokenizer's chat template, where an unknown
        `developer` role is a template error, not a shrug.

    THEREFORE:
      · `maxTokensField` IS NOT SET. Both of our engines read both spellings; setting
        it would be a knob with no measured effect, and the brief's guess that it was
        needed is simply wrong for this runner. Ledger U68 carries the recipe for
        re-deciding this if a third engine ever lands.
      · `supportsDeveloperRole: false` IS SET, at ROUTE level. It is moot TODAY (we
        declare no `reasoningEfforts`, so the role is already `system`) and it is the
        one line standing between an MLX-served model and a hard chat-template failure
        the moment anything flips that — a future pin's default, or a user adding
        efforts to a model on our own route. A defensive knob whose exact trigger has
        been measured is not cargo cult; an unmeasured one would be.

F5  A MALFORMED BLOCK IS SILENT. Measured: booted `dsh web` against a deliberately
    broken route (hand-declared, no baseURL) — the server started, `GET /` returned
    200, and NOTHING was printed to stdout or stderr. The provider simply is not
    there. So upstream gives us no post-hoc signal to grep for, and OUR OWN
    validation (validate_route, below) is the only gate between a bad write and a lane
    that looks fine and has no models. That is why it runs before every write.


⚠️ YAML ROUND-TRIP COST, stated because the user will see it. dsh's own writer does
leaf-level diffs and preserves comments; yaml.safe_dump does not. A settings.yaml the
user has commented by hand keeps its VALUES through our seed but loses its COMMENTS
(and its key order). Same trade seed_hermes_provider.py records for ~/.hermes/config.yaml.
Everything the user configured is preserved as data — only the prose is lost.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile

try:
    import yaml
except Exception:                                                   # noqa: BLE001
    # The house rule (seed_hermes_provider.py): a missing PyYAML must NEVER fail a
    # Start. Say it and leave the file untouched — a lane with no provider is
    # recoverable; a lane whose Start refuses is not.
    print("[motdeck] WARNING: PyYAML unavailable — DeepSeek provider NOT seeded")
    raise SystemExit(0)

PID = "mot-deck"                    # our route id, everywhere — never spelled twice
PRODUCT_NAME = "MOT Deck (local)"   # the DISPLAY name, and the same string the goose
                                    # and OpenCode providers carry
NS = "llm-pi-ai"                    # the settings namespace the adapter registers
DEFAULT_NS = "agent-default-model"  # the deployment default an entry point resolves
API = "openai-completions"          # the protocol; ours is an OpenAI-compatible gateway
MARKER = "motdeck_seed_state.json"  # written beside settings.yaml


# ── S29: the ONE definition of an offerable model (bridge/core/modelreg.py) ──
# Loaded BY PATH, resolved from THIS FILE (never the cwd), so it works from the repo
# and from the provisioned snapshot alike — the same loader seed_hermes_provider.py
# uses, for the same reason: this script is spawned as a subprocess and cannot rely on
# `bridge` being importable.
def _load_modelreg():
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         os.pardir, "bridge", "core", "modelreg.py")
        spec = importlib.util.spec_from_file_location("motdeck_modelreg", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                               # noqa: BLE001
        return None


MR = _load_modelreg()


def key_env_name(name: str = PRODUCT_NAME) -> str:
    """PURE. The env var name dsh reads the key from, DERIVED from the product name.

    Deliberately the same shape gooseprov.api_key_env() derives ("the provider name
    upper-cased + _API_KEY") rather than a second hand-picked constant, because two
    hand-picked names is how the goose lane ended up with a `MOT_DECK_RUNNER_API_KEY`
    that nothing read. "MOT Deck (local)" -> MOT_DECK_LOCAL_API_KEY.

    ⚠️ NOT byte-identical to gooseprov's answer for the same product name
    (CUSTOM_MOT_DECK__LOCAL_API_KEY) and it must not be: goose derives its name from
    goose's OWN provider slug, which carries a `custom_` prefix and keeps the
    empty-segment double underscore that goose's slugify produces. dsh has no such
    slug — the name is ours to choose, and it only has to be stable and legal. What is
    shared is the RULE (derive it, never hand-pick it twice), not the string.

    ⚠️ It must be a legal POSIX env var name (start_component.sh exports it with
    `env NAME=value`), so every run of non-alphanumerics collapses to one underscore
    and a leading digit is impossible from this input.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or PRODUCT_NAME)).strip("_").upper()
    return (slug or "MOT_DECK") + "_API_KEY"


# ── the catalog ──────────────────────────────────────────────────────────────
def catalog(registry) -> list:
    """PURE. The `models` list for our route, from a registry list.

    WHICH ROWS: modelreg.offerable() — chat, not hidden, not flagged absent, file not
    provably gone. That last clause is S29 and it is the whole point of this file.

    TWO IDENTIFIERS, and conflating them is a real defect (the same one
    seed_opencode_config.py documents):
      * `id` is what pi-ai literally SENDS as the model name on the wire, and it is
        also how dsh addresses the model in `agent-default-model`. It must therefore
        be modelreg.wire_id(): llama.cpp is launched with `--alias <registry id>` so
        its wire name IS the id, while the MLX servers treat the request's `model`
        field as a model to LOAD and need the registry PATH.
      * `name` is the human label the picker shows — the registry id, always, because
        an MLX path is not something to read in a menu.

    ⚠️ `input`/modalities are DELIBERATELY NOT DECLARED. The adapter's configurable
    entry fields are id, name, contextWindow, maxTokens, reasoningEfforts and compat;
    the route's `defaultInput` (default `[text]`) is what answers for modalities, and
    the docs are explicit that under-claiming costs a refusal naming the model while
    over-claiming "admits an image the provider then rejects mid-turn — after the
    message is durable". We have no per-model VLM fact we trust here, so we claim
    nothing and let the conservative default stand. (The brief's sketch put
    `input: [text]` on each entry; that field is not in the entry schema at this pin.)

    ⚠️ `reasoningEfforts` is DELIBERATELY NOT DECLARED either — see F4. The registry
    carries no thinking-level facts, and declaring the field is precisely what flips
    the system prompt to the `developer` role.
    """
    rows = MR.offerable(registry) if MR is not None else [
        m for m in (registry or [])
        if isinstance(m, dict) and m.get("kind") != "audio" and not m.get("hidden")
        and not m.get("absent") and str(m.get("id") or "").strip()]
    out, seen = [], set()
    for m in rows:
        mid = str(m.get("id") or "").strip()
        wire = (MR.wire_id(m) if MR is not None else
                (((m.get("path") or "").strip() or mid)
                 if str(m.get("format") or "gguf").strip().lower() == "mlx" else mid))
        wire = str(wire or "").strip()
        if not wire or wire in seen:
            # F2: "a non-empty models list of UNIQUELY-IDENTIFIED models". Two registry
            # rows can share a wire id (the same MLX directory registered twice), and a
            # duplicate would fail the whole section, not just the row.
            continue
        seen.add(wire)
        entry = {"id": wire, "name": mid or wire}
        try:
            ctx = int((m.get("load") or {}).get("ctx") or m.get("ctx") or 0)
        except (TypeError, ValueError):
            ctx = 0
        if ctx > 0:
            # ⚠️ builder numbers, and they mean different things: contextWindow is the
            # registry's own fact; maxTokens mirrors MOT Deck's 4096 max_tokens
            # default and BECOMES the request default ("a model's CONFIGURED maxTokens
            # becomes the seam's defaultMaxTokens"), so it must be a cap we actually
            # want sent. Both omitted when ctx is unknown — the route then falls back
            # to the adapter's own 262144/32768, which are honest guesses, whereas a
            # contextWindow of 0 would be a lie.
            entry["contextWindow"] = ctx
            entry["maxTokens"] = min(4096, ctx)
        out.append(entry)
    return out


def provider_block(models, base, key_env) -> dict:
    """PURE. Our route, exactly as it must appear under llm-pi-ai.providers."""
    return {
        "displayName": PRODUCT_NAME,
        "api": API,
        "baseURL": base,
        "apiKeyEnv": key_env,
        # F4 — the one measured-defensive knob. Route level, so it is the default for
        # every model on the route.
        "compat": {"supportsDeveloperRole": False},
        "models": models,
    }


def validate_route(block) -> str:
    """PURE. '' when this block is serviceable, else the ONE sentence to print.

    F5: upstream accepts a broken block in silence and simply serves no provider, and
    F2: a broken block takes the whole namespace's next load with it. So this is not
    belt-and-braces — it is the only gate there is.
    """
    if not isinstance(block, dict):
        return "the provider block is not a mapping"
    if not str(block.get("api") or "").strip():
        return "no `api` protocol"
    if not str(block.get("baseURL") or "").strip():
        return "no `baseURL` (the runner endpoint is empty in motdeck.yaml)"
    ms = block.get("models")
    if not isinstance(ms, list) or not ms:
        return ("no models — a hand-declared route with an empty `models` list is "
                "REFUSED by the adapter, and a refused section would disable every "
                "other provider in the namespace too")
    ids = [str((m or {}).get("id") or "").strip() for m in ms]
    if not all(ids):
        return "a model entry with no `id`"
    if len(set(ids)) != len(ids):
        return "two model entries share an `id`"
    return ""


# ── the document ─────────────────────────────────────────────────────────────
def load_doc(path):
    """The existing settings document, or {}. A document we cannot PARSE is a refusal,
    not an empty dict: overwriting a user's hand-edited YAML because we could not read
    it is the clobber this whole file exists to avoid. Returns (doc, error)."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return {}, ""
    except Exception as e:                                          # noqa: BLE001
        return None, f"could not read {path}: {str(e)[:100]}"
    if not raw.strip():
        return {}, ""
    try:
        data = yaml.safe_load(raw)
    except Exception as e:                                          # noqa: BLE001
        return None, f"{path} is not valid YAML (values redacted) — left untouched"
    if data is None:
        return {}, ""
    if not isinstance(data, dict):
        return None, f"{path} does not hold a mapping at the top level — left untouched"
    return data, ""


def save_doc(path, data) -> None:
    """Atomic, owner-only, same-directory temp-and-rename.

    ⚠️ 0600 is not decoration: dsh's own writer exclusive-creates its temp with mode
    0600 and this document sits next to .credentials.yaml. A world-readable
    settings.yaml would be a downgrade we introduced.
    ⚠️ Same directory, deliberately: os.replace across filesystems is not atomic, and
    $DSH_HOME can be on a different volume from /tmp.
    """
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings.", suffix=".yaml")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False,
                           allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


KEEP = "…keep the user's own choice…"   # sentinel: plan_default's third outcome


def plan_default(cur, want, model_ids):
    """PURE: (new selection | None to leave absent | KEEP, repair note or '').

    SEED when unset · REPLACE when the configured choice DANGLES against OUR route ·
    HONOUR otherwise. The same sentence as modelreg/gooseprov.dangles and
    seed_opencode_config.plan_default, applied to dsh's {provider, model} shape.

    ⚠️ THE ONE RULE THAT MATTERS: a default we write must NAME A MODEL THAT EXISTS.
    The service "does not validate catalog membership" (dsh-agent-default-model
    README) — it hands the selection straight to the entry point, and a model our
    route does not configure then fails with LlmError('UNKNOWN_MODEL') before any
    request. So a dangling default is not a wrong answer, it is a dead lane.

    ⚠️ AND A SELECTION ON SOMEBODY ELSE'S PROVIDER IS NOT OURS TO TOUCH. `cur` naming
    provider `deepseek-official` (upstream's own default) is a statement about a route
    we do not own; we only ever repair a selection that names OUR route and dangles.
    The one exception is the empty case, which is nobody's choice yet.
    """
    if not isinstance(cur, dict):
        cur = {}
    cur_prov = str(cur.get("provider") or "").strip()
    cur_model = str(cur.get("model") or "").strip()

    pick = str(want or "").strip()
    if pick not in model_ids:
        # not in the registry -> deterministic first model of ours, or nothing at all
        pick = sorted(model_ids)[0] if model_ids else ""

    ours = cur_prov == PID
    stale = ours and cur_model not in model_ids

    if not cur_prov and not cur_model:
        if not pick:
            return None, ""
        return {"provider": PID, "model": pick}, ""
    if stale:
        if pick:
            return ({"provider": PID, "model": pick},
                    "replaced a default model that named no existing model")
        # ours, dangling, and we have nothing valid to offer. Leaving it is the least
        # bad option: removing the section entirely would silently hand the lane back
        # to upstream's `deepseek-official` route, which needs a DeepSeek cloud key —
        # i.e. we would turn "one dead model" into "asks you for a cloud account".
        return KEEP, ("left a default model that names no existing model — the "
                      "registry has nothing to offer this route right now")
    return KEEP, ""


def main() -> int:
    root = os.environ.get("MOT_DECK_ROOT") or os.getcwd()
    path = os.environ.get("DS_SETTINGS") or ""
    base = (os.environ.get("DS_BASE") or "").strip()
    key_env = (os.environ.get("DS_KEY_ENV") or "").strip() or key_env_name()
    want = (os.environ.get("DS_MODEL") or "").strip()

    if not path:
        print("[motdeck] deepseek config: DS_SETTINGS not set — nothing written")
        return 1

    registry = (MR.load_registry(root) if MR is not None
                else ((json.load(open(os.path.join(root, "data", "models.json"),
                                      encoding="utf-8")) or {}).get("models") or []))
    models = catalog(registry)
    block = provider_block(models, base, key_env)

    bad = validate_route(block)
    if bad:
        # THE REFUSAL, and it is loud. ⚠️ It is also the empty-registry case, and
        # modelreg's standing rule is that "[] IS NOT A DECISION": the runner may be
        # stopped, the disk unplugged, the rescan not yet run. Leaving the previous
        # good block in place is strictly better than replacing it with something the
        # adapter will reject.
        print("[motdeck] deepseek config: NOT WRITTEN — %s" % bad)
        print("[motdeck]   the existing settings.yaml is left exactly as it was; run "
              "Rescan in Models (or start the runner) and Start again.")
        return 0

    doc, err = load_doc(path)
    if err:
        print("[motdeck] deepseek config: %s" % err)
        return 0

    # ── MERGE, NEVER OVERWRITE. Only the keys we own are replaced, so every other
    # namespace (theme, permission presets, other providers, the user's own routes)
    # survives a Start. This is the same discipline the OpenCode/Hermes/goose seeders
    # implement, and it is what makes a config-resident provider safe to re-write on
    # every single start.
    ns = doc.get(NS)
    if not isinstance(ns, dict):
        if ns is not None:
            print("[motdeck] deepseek config: llm-pi-ai is not a mapping — left untouched")
            return 0
        ns = {}
    provs = ns.get("providers")
    if not isinstance(provs, dict):
        if provs is not None:
            print("[motdeck] deepseek config: providers must be a mapping; "
                  "existing routes were preserved for repair in DeepSeek settings")
            return 0
        provs = {}
    before = len(((provs.get(PID) or {}) if isinstance(provs.get(PID), dict) else {})
                 .get("models") or [])
    provs[PID] = block
    ns["providers"] = provs
    doc[NS] = ns

    repairs = []
    cur_default = doc.get(DEFAULT_NS)
    new, note = plan_default(cur_default, want, {m["id"] for m in models})
    if note:
        repairs.append(note)
    if new is None:
        pass                            # nothing valid to say; leave the section absent
    elif new is not KEEP:
        # Only provider+model are ours. `reasoningEffort` belongs to the user's saved
        # selection ("a complete saved selection can clear an effort when the next
        # selected model has none"), so a value they chose is carried, not stomped —
        # except when we are re-pointing at a different model, where their old effort
        # would describe a model that is no longer selected.
        keep_effort = (isinstance(cur_default, dict)
                       and str(cur_default.get("provider") or "") == PID
                       and str(cur_default.get("model") or "") == new["model"]
                       and cur_default.get("reasoningEffort") is not None)
        if keep_effort:
            new = dict(new, reasoningEffort=cur_default["reasoningEffort"])
        doc[DEFAULT_NS] = new

    try:
        save_doc(path, doc)
    except Exception as e:                                          # noqa: BLE001
        print("[motdeck] deepseek config: could not write %s (%s) — left untouched"
              % (path, str(e)[:100]))
        return 1

    # ── THE MARKER: only the values we actually wrote. Same purpose as
    # hermes_seed_state.json — it is what lets a later audit tell "the user set this"
    # from "we set this", without which a rename or a hand-edit is indistinguishable
    # from our own last write. Never carries the key (there is no key here to carry).
    try:
        sel = doc.get(DEFAULT_NS) if isinstance(doc.get(DEFAULT_NS), dict) else {}
        with open(os.path.join(os.path.dirname(os.path.abspath(path)), MARKER),
                  "w", encoding="utf-8") as fh:
            json.dump({"provider_id": PID, "display_name": PRODUCT_NAME,
                       "base_url": base, "api_key_env": key_env, "api": API,
                       "compat": block["compat"],
                       "model_ids": [m["id"] for m in models],
                       "default": {"provider": sel.get("provider"),
                                   "model": sel.get("model")}
                       if str(sel.get("provider") or "") == PID else None},
                      fh, indent=2)
    except Exception:                                               # noqa: BLE001
        pass                            # the marker is diagnostics, never the gate

    for r in repairs:
        print("[motdeck]   REPAIRED: %s" % r)
    dropped = before - len(models)
    sel = doc.get(DEFAULT_NS) if isinstance(doc.get(DEFAULT_NS), dict) else {}
    print("[motdeck] deepseek config -> %s" % path)
    print("[motdeck]   provider %s (%s) -> %s · %d model(s)%s · default %s"
          % (PID, PRODUCT_NAME, base or "(no endpoint!)", len(models),
             (" (%d dropped — gone from the registry or from disk)" % dropped)
             if dropped > 0 else "",
             ("%s/%s" % (sel.get("provider"), sel.get("model")))
             if sel.get("model") else "unset"))
    print("[motdeck]   key: read by dsh from $%s at request time — the secret is NOT "
          "in this file" % key_env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
