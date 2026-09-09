#!/usr/bin/env python3
"""Point OpenCode at OUR runner: the provider catalog + the seeded default model.

⚠️ THIS WAS A HEREDOC INSIDE scripts/start_component.sh, AND THAT WAS THE BUG.
The audit (docs/research/2026-08-29-post-switch-audit.md §1) measured OpenCode's
provider catalog holding SIXTEEN models — including `Muse-Glimmer-30B-Heretic-Q4_K_S`,
`dflash-Muse-Glimmer-30B-Abliterated-Q4_K_M` and the gemma-4 DECKARD — whose weights
sample had deleted days earlier, because the only thing that ever rewrote that block was
OpenCode's own Start, and it had not been started since. Picking one of those does not
fail: llama.cpp ignores the request's `model` field, so the turn works and answers
under the dead model's name. Lie class.

Being a script instead of a heredoc is what lets the bridge call it — from the model
switch fan-out (routers/models._rebind_dependents) and from RESCAN — so the catalog
tracks the registry without a component restart. The shell arm still calls it, with the
same environment, so there is exactly ONE implementation.

ENV (all read here, nothing implicit):
  OC_CFG    the global config path (<XDG_CONFIG_HOME>/opencode/opencode.json)
  OC_PCFG   the project copy (<workspace>/opencode.json) — provider ONLY, no `model`
  OC_BASE   the runner's base url            OC_KEY  its api key
  OC_MODEL  the model to seed a default from (a CANDIDATE, never an answer — see below)
  MOT_DECK_ROOT  where data/models.json lives (default: cwd)

stdlib only.
"""
import json
import os
import sys
import base64
import stat
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
try:
    from bridge.core import modelreg as MR                     # type: ignore
except Exception:                                              # noqa: BLE001
    MR = None

PID = "llama.cpp"          # our provider id, everywhere — never spelled twice


def _key(model_id):
    """The shared U94 grammar, with a stdlib-only recovery fallback."""
    if MR is not None:
        return MR.opencode_model_key(model_id)
    model_id = str(model_id or "")
    plain = (model_id and all(c.isascii() and (c.isalnum() or c in "._-")
                              for c in model_id)
             and not model_id.startswith("mot1_"))
    if plain:
        return model_id
    return "mot1_" + base64.urlsafe_b64encode(
        model_id.encode("utf-8")).decode("ascii").rstrip("=")


def _legacy_key(model_id):
    if MR is not None:
        return MR.opencode_legacy_model_key(model_id)
    return str(model_id or "").replace("/", "_")


# ── the catalog ──────────────────────────────────────────────────────────────
# TWO SEPARATE IDENTIFIERS, and conflating them was a real defect:
#   * the KEY of the models map is how OpenCode addresses the model everywhere —
#     `provider/model` strings, the picker, `cfg.model`. It must be slash-free, because
#     the desktop splits those strings with a bare `.split("/")` destructure
#     (app/src/hooks/provider-catalog.ts:31-36) and an absolute path would leave the
#     model id EMPTY.
#   * `id` inside the entry becomes `api.id` (provider.ts:1465), which is what is
#     literally sent as the model name on the wire (provider.ts:1886
#     `sdk.languageModel(model.api.id)`).
# llama.cpp is launched with `--alias <registry id>` so its wire name IS the id; the MLX
# servers treat the request's `model` field as a model to LOAD and need the registry
# PATH — the rule modelreg.wire_id() owns for all five enumerators.
def catalog(registry):
    """PURE. (models map, {registry id: opencode key}) from a registry list.

    WHICH ROWS: modelreg.offerable() — chat, not hidden, not flagged absent, file not
    provably gone. That last clause is S29 and it is the whole point of this file."""
    models, key_of = {}, {}
    rows = MR.offerable(registry) if MR is not None else [
        m for m in (registry or [])
        if isinstance(m, dict) and m.get("kind") != "audio" and not m.get("hidden")
        and not m.get("absent") and str(m.get("id") or "").strip()]
    for m in rows:
        mid = m.get("id")
        wire = (MR.wire_id(m) if MR is not None else
                (((m.get("path") or "").strip() or mid)
                 if str(m.get("format") or "gguf").strip().lower() == "mlx" else mid))
        key = _key(mid)
        key_of[mid] = key
        entry = {"name": mid, "id": wire}
        # tool_call is declared only when we actually know (bridge/modeltools.py is
        # three-valued); unknown stays absent so upstream's own default (true,
        # provider.ts:1490) applies rather than us asserting something unmeasured.
        t = m.get("tools")
        if isinstance(t, bool):
            entry["tool_call"] = t
        try:
            ctx = int(m.get("ctx") or 0)
        except (TypeError, ValueError):
            ctx = 0
        if ctx > 0:
            # ⚠️ builder numbers: context is the registry's, output mirrors the
            # MOT Deck's own 4096 max_tokens default. Omitted entirely when ctx is
            # unknown, because a limit of 0 is worse than no limit.
            entry["limit"] = {"context": ctx, "output": min(4096, ctx)}
        models[key] = entry
    return models, key_of


def provider_block(models, base, key):
    # ⚠️ `models` MUST NOT be empty, and that is measured, not stylistic: a provider
    # whose models map is empty is DELETED outright (provider/provider.ts:1686 at the
    # pin — `if (Object.keys(provider.models).length === 0) { delete providers[id] }`),
    # so an empty registry would make the whole lane vanish from Settings AND the
    # picker. This fallback is what keeps the provider visible enough to explain itself.
    return {
        "npm": "@ai-sdk/openai-compatible",
        "name": "MOT Deck (local)",
        "options": {"baseURL": base, "apiKey": key},
        "models": models or {"motdeck-runner": {"name": "MOT Deck runner",
                                                "id": "motdeck-runner"}},
    }


def load(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return {}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("OpenCode configuration must be a regular file")
        with os.fdopen(fd, encoding="utf-8") as fh:
            fd = -1
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("OpenCode configuration must contain an object")
        return data
    finally:
        if fd >= 0:
            os.close(fd)


def save(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    if os.path.lexists(path) and load(path) == data:
        os.chmod(path, 0o600)
        return
    fd, tmp = tempfile.mkstemp(prefix=".opencode-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


KEEP = "…keep the user's own choice…"   # sentinel: plan_default's third outcome


def plan_default(cur, want, key_of, model_keys):
    """PURE: (new value | None to unset | KEEP, repair note or ''). The three-state rule.

    SEED when unset · REPLACE when the configured choice DANGLES against our provider ·
    HONOUR otherwise. Same sentence as modelreg/gooseprov.dangles, applied to OpenCode's
    `provider/model` string shape.

    ⚠️ THE ONE RULE THAT MATTERS HERE: a default we write must NAME A MODEL THAT EXISTS.
    `defaultModel()` returns `parseModel(cfg.model)` UNVALIDATED when the key is set
    (provider/provider.ts:1980-1981), so a dangling id is handed onward as if it were
    real; and with no valid selection the desktop falls back to its own ordering, whose
    priority list is ["gpt-5", "claude-sonnet-4", "big-pickle", ...] (provider.ts:2017)
    — that is where "Big Pickle" comes from. Leaving `model` UNSET is safe by contrast:
    with no key, upstream falls through to the providers named in cfg.provider — i.e.
    ours — and takes its first model (:2002-2007).
    """
    fallback_key = _key(want)
    want_key = key_of.get(want, fallback_key)
    if want_key not in model_keys:
        # not in the registry -> deterministic first model of ours, or nothing at all
        want_key = sorted(model_keys)[0] if model_keys else ""
    stale = (isinstance(cur, str) and cur.startswith(PID + "/")
             and cur.split("/", 1)[1] not in model_keys)
    if want_key and (not isinstance(cur, str) or not cur or stale):
        return PID + "/" + want_key, ("replaced a default model that named no existing "
                                      "model" if stale else "")
    if stale:
        # ours, dangling, and we have nothing valid to offer: unset beats dangling.
        return None, "cleared a default model that named no existing model"
    return KEEP, ""


def migrate_saved_default(cur, key_of, model_keys):
    """PURE. Migrate one pre-U94 selection without guessing through a collision."""
    if not isinstance(cur, str) or not cur.startswith(PID + "/"):
        return KEEP, ""
    old = cur.split("/", 1)[1]
    matches = [mid for mid in key_of if _legacy_key(mid) == old]
    if old in model_keys and len(matches) <= 1:
        return KEEP, ""
    if len(matches) == 1:
        return PID + "/" + key_of[matches[0]], "migrated legacy OpenCode model key"
    if len(matches) > 1:
        return None, ("discarded an ambiguous legacy OpenCode preference; the current "
                      "valid fallback is not presented as the prior choice")
    return KEEP, ""


def main() -> int:
    root = os.environ.get("MOT_DECK_ROOT") or os.getcwd()
    base = os.environ.get("OC_BASE") or ""
    key = os.environ.get("OC_KEY") or ""
    cfg_path = os.environ.get("OC_CFG") or ""
    pcfg_path = os.environ.get("OC_PCFG") or ""
    if not cfg_path:
        print("[motdeck] opencode config: OC_CFG not set — nothing written")
        return 1
    registry = (MR.load_registry(root) if MR is not None
                else (load(os.path.join(root, "data", "models.json")).get("models") or []))
    models, key_of = catalog(registry)
    PROVIDER = provider_block(models, base, key)
    MODEL_KEYS = set(PROVIDER["models"])

    # ── the GLOBAL config: provider + default model + the pin rule ────────────
    # MERGE, never overwrite: only the keys we own are replaced, so anything the user
    # adds in that file (permissions, themes, other providers) survives a restart.
    # Validate both destinations before modifying either configuration.
    try:
        cfg = load(cfg_path)
        pcfg = load(pcfg_path) if pcfg_path else None
        for document in (cfg, pcfg):
            if document is not None and document.get("provider") is not None \
                    and not isinstance(document["provider"], dict):
                raise ValueError("provider must contain an object")
    except (OSError, ValueError):
        print("[motdeck] opencode config: unreadable or invalid configuration — left untouched")
        return 1
    before = len(((cfg.get("provider") or {}).get(PID) or {}).get("models") or {})
    provider = cfg.get("provider")
    if not isinstance(provider, dict):
        provider = {}
    provider[PID] = PROVIDER
    cfg["provider"] = provider
    cfg["$schema"] = "https://opencode.ai/config.json"
    # THE PIN RULE, in the file as well as in the env: upstream's auto-update is ON by
    # default and would move the binary out from under motdeck.yaml.
    cfg["autoupdate"] = False

    # ── UN-DISABLE OURSELVES. Measured against the real server at the pin: with
    # `disabled_providers: ["llama.cpp"]` present, our provider is deleted BEFORE the
    # models loop (provider/provider.ts:1644) and disappears from BOTH `all` and
    # `connected` — Settings → Providers reads "No connected providers" and the picker
    # offers no local model, no matter how correct the provider block beside it is.
    # ONE click on "Disconnect" in OpenCode's own Settings writes that entry, and
    # because our merge only ever replaces the keys we own, it would otherwise survive
    # every restart forever — an unrecoverable dead lane with no visible cause.
    # ⚠️ this DOES overrule a disable the user may have made deliberately. The trade is
    # deliberate: pointing this lane at MOT Deck runner is the entire job, a
    # stuck-disabled provider has no other cure, and the line below says out loud that
    # we did it (so a user who really wants it off can disable it and not Start).
    repairs = []
    dis = cfg.get("disabled_providers")
    if isinstance(dis, list) and any(str(x) == PID for x in dis):
        kept = [x for x in dis if str(x) != PID]
        if kept:
            cfg["disabled_providers"] = kept
        else:
            cfg.pop("disabled_providers", None)
        repairs.append("removed %s from disabled_providers" % PID)
    # The mirror-image key: a non-empty allowlist that omits us filters us out just the
    # same (`if (enabled && !enabled.has(id)) return false`, provider.ts:1415-1422).
    # Nothing in OpenCode's UI writes this one, so it can only be hand-written — we add
    # ourselves rather than empty it, leaving every other choice in it intact.
    # ⚠️ an EMPTY list is deliberately NOT touched: `cfg.enabled_providers ? new Set()`
    # reads an empty array as truthy in JS, which would mean "allow nothing", but that
    # reading is inferred and was never measured — and if it is wrong, writing one entry
    # would turn "no allowlist" into "only MOT Deck", disabling everything else.
    en = cfg.get("enabled_providers")
    if isinstance(en, list) and en and not any(str(x) == PID for x in en):
        cfg["enabled_providers"] = list(en) + [PID]
        repairs.append("added %s to enabled_providers" % PID)

    # motdeck.yaml's runner.model is an INTENT and can easily name something the
    # registry does not carry (the runner is stopped, the model was deleted, the id
    # differs), so it is a candidate, never an answer. When the bridge calls this from
    # the switch/rescan fan-out it passes the LIVE wire id instead (U18's rule).
    want = os.environ.get("OC_MODEL") or ""
    migrated, migration_note = migrate_saved_default(
        cfg.get("model"), key_of, MODEL_KEYS)
    if migration_note:
        repairs.append(migration_note)
    if migrated is None:
        cfg.pop("model", None)
    elif migrated is not KEEP:
        cfg["model"] = migrated
    new, note = plan_default(cfg.get("model"), want, key_of, MODEL_KEYS)
    if note:
        repairs.append(note)
    if new is None:
        cfg.pop("model", None)
    elif new is not KEEP:
        cfg["model"] = new
    save(cfg_path, cfg)
    for r in repairs:
        print("[motdeck]   REPAIRED: %s" % r)

    # ── the PROJECT config: the provider only ────────────────────────────────
    # config.ts:406-409 loads `opencode.json` walking up from the instance directory and
    # merges it AFTER the global one, so the workspace we always start in carries its
    # own copy — two independent paths to the same fact.
    # ⚠️ it deliberately carries NO `model` key: the desktop writes a model choice back
    # to the GLOBAL config (PATCH /global/config), and a project key merges last, so
    # seeding one here would stomp the user's own pick on every load.
    if pcfg_path:
        pprovider = pcfg.get("provider")
        if not isinstance(pprovider, dict):
            pprovider = {}
        pprovider[PID] = PROVIDER
        pcfg["provider"] = pprovider
        pcfg["$schema"] = "https://opencode.ai/config.json"
        # We never seed a project model, but an older OpenCode/user may have stored
        # one. Project config merges last, so leaving a legacy value here would undo
        # the global migration. Ambiguity is cleared visibly, never assigned by order.
        pnew, pnote = migrate_saved_default(pcfg.get("model"), key_of, MODEL_KEYS)
        if pnote:
            print("[motdeck]   REPAIRED: project %s" % pnote)
        if pnew is None:
            pcfg.pop("model", None)
        elif pnew is not KEEP:
            pcfg["model"] = pnew
        save(pcfg_path, pcfg)
        print("[motdeck] opencode config -> %s (project copy, provider only)" % pcfg_path)
    print("[motdeck] opencode config -> %s" % cfg_path)
    dropped = before - len(models)
    print("[motdeck]   provider llama.cpp -> %s · %d model(s)%s · default %s"
          % (base, len(models),
             (" (%d dropped — gone from the registry or from disk)" % dropped)
             if dropped > 0 else "",
             cfg.get("model") or "unset"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
