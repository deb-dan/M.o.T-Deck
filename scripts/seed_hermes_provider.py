#!/usr/bin/env python3
"""Wire Hermes to the MOT Deck runner — ONCE — and then never clobber the human.

Two surfaces in ~/.hermes/config.yaml, one writer:
  * `custom_providers:` — the NAMED provider row "MOT Deck (local)" that puts our
    whole registry in Hermes's OWN model picker (isolation mode, S-ISO-3);
  * `model:`            — the main slot (default / provider / base_url / api_key /
    context_length), which used to be re-asserted on EVERY Start (ledger U12): a
    model the user picked inside Hermes was silently reset by the next restart.

Both now obey the three never-clobber rules of the house pattern
(scripts/seed_odysseus_jan.py, v1.5.51, itself the odyvision precedent generalised):
  1. CREATE-IF-ABSENT — a row/key we did not create is never invented twice; what
     exists is updated field by field under rule 2.
  2. UPDATE ONLY WHAT IS PROVABLY OURS AND STALE — "provably ours" = the value equals
     what WE last wrote (recorded in data/hermes_seed_state.json, the marker), or it
     is still a shipped-default shape. Anything else is the human's and is left alone
     WITH A PRINTED LINE saying we honoured it — a silent no-op is its own lie.
  3. THE MARKER RECORDS ONLY VALUES WE WROTE — recording one we HONOURED would make
     it "ours" next run and clobber it one Start later (the subtle half).



WHY THIS EXISTS (isolation mode, S-ISO-3). Until this script, Start pointed Hermes
at our runner with the ANONYMOUS shape — `model.provider: custom` + `model.base_url`.
That works for a turn, but Hermes's OWN "Set main model" picker then shows a bare
"Custom endpoint" row whose model list is a LIVE PROBE of the current endpoint
(hermes_cli/model_switch.py:2903-2952, section 3b) — runner down ⇒ the one row that
is ours is empty too, and nothing on the page says "MOT Deck". Every other row is an
unauthenticated cloud provider with 0 models.

Hermes already has the mechanism: a NAMED entry in the legacy `custom_providers:`
list. It renders as its own picker row under the slug `custom:<normalized-name>`
(hermes_cli/providers.py:748-758 `custom_provider_slug`), its models come from the
entry itself (model_switch.py:3081-3090 `_declared_model_ids`), and with
`discover_models: false` (model_switch.py:3190-3196 `_discovery_allowed`) that list
is CONFIG-RESIDENT: the picker stays populated with the runner stopped, exactly like
OpenCode's provider block (scripts/start_component.sh:920-1106, the house pattern).

THE FIVE RULES THIS FILE IMPLEMENTS (the OpenCode pattern, verbatim):
  1. write our provider into the app's OWN config surface, under the product name;
  2. enumerate the registry, don't rely on live discovery;
  3. merge only the keys we own — never clobber a user edit;
  4. seed defaults, never enforce them;
  5. print a one-line verdict a human can act on.

WHAT IS OURS AND WHAT IS THE USER'S (rule 3, the odyvision precedent):
  * identity is the base_url, NEVER the name. A rename inside Hermes's own Config
    page is honoured: the entry keeps the user's name, and the main slot follows it
    to the new slug (that is what makes the rename survive a restart).
  * MANAGED keys on our entry: `models` (union-merged), `discover_models`,
    `context_length`, and `api_key` — but api_key ONLY when the entry does not
    declare `key_env`, because a key_env is a deliberate user choice about where the
    secret lives and an inline key would silently outrank it
    (hermes_cli/runtime_provider.py:1141-1152, the api_key candidate order).
  * `name` is written only when the entry is NEW or still wears a DEFAULT name (ours,
    or the one Hermes's own writer would generate — `_auto_provider_name`,
    hermes_cli/main.py:4083-4101).
  * every other key (api_mode, extra_headers, extra_body, model, ssl_*, …) is left
    exactly as found, and models the user added by hand are preserved.

YAML ROUND-TRIP: this writes with yaml.safe_dump, which costs comments and key order
ONCE — the same accepted property as bridge/core/hermescfg.py:70-72 and the LOffice
MCP seed. It is paid at most once because this script is STRICTLY IDEMPOTENT: when
the config it would write equals the config on disk, it does not open the file for
writing at all.

THE MAIN SLOT (`model:`), key by key — what "provably ours" means for each:
  * `provider`       — ours while it is a shipped default (`custom` / `local` / empty,
                       the pre-S-ISO-3 anonymous shape) or a `custom:` slug that
                       resolves to OUR entry (so a rename repoints it, which is what
                       makes the rename survive). A real other provider is the user's.
  * `default`        — the model. Ours while it equals what we last wrote. A model the
                       user picked inside Hermes STAYS — with a printed line naming the
                       model MOT Deck actually has loaded, because llama.cpp answers
                       every request from the resident model whatever the request asks
                       for (MEASURED — ledger U13/U14).
  * `base_url`       — ours while it equals the marker or still has our loopback shape.
  * `api_key`        — filled when empty, rotated while it is ours, never overwritten.
  * `context_length` — ours while it equals the marker; Hermes's own picker DELETES
                       this key on every model switch (web_server.py:1616), so an
                       absent value is simply re-seeded.
BOOTSTRAP (no marker yet — every config written before this slice): the main slot was
re-asserted on every Start by construction, so its values ARE ours and are refreshed
once, which records the marker. From that Start on, the user's edits stick.
BOUNDED, though — by the config's OWN evidence (`seeded_before`): a config carrying our
row (`discover_models: false`, a key none of Hermes's writers emit) or a main slot
already on our slug has demonstrably been seeded by this script, so a MISSING marker
there means the marker was deleted, not that this is a pre-slice config. Without that
bound, `rm data/hermes_seed_state.json` would hand the user's picked model straight back
to us on the next Start — U12, one directory tidy-up away.

Env in:  HERMES_CFG, BASE_URL, KEY, MODEL (wire id), CTXLEN, MOT_DECK_ROOT (registry).
Files out (both under <MOT_DECK_ROOT>/data/, both OURS — never read by Hermes):
  hermes-provider.json  — the verdict the Start script prints/verifies against;
  hermes_seed_state.json — the marker: ONLY the values we actually wrote.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

try:
    import yaml
except Exception:                                                   # noqa: BLE001
    print("[motdeck] WARNING: PyYAML unavailable — Hermes provider NOT seeded")
    raise SystemExit(0)

PRODUCT_NAME = "MOT Deck (local)"


# ── S29: the ONE definition of an offerable model (bridge/core/modelreg.py) ──
# Loaded BY PATH, resolved from THIS FILE (never the cwd), so it works from the repo and
# from the provisioned snapshot alike. None ⇒ registry_models falls back to its own
# inline rule, because a helper that failed to import must not empty Hermes's picker.
def _load_modelreg():
    try:
        import importlib.util
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


_MODELREG = _load_modelreg()


# ── identity helpers — mirrors of upstream, cited so a pin bump can be diffed ──

def norm_url(value: str) -> str:
    """base_url identity. Mirrors upstream's own comparisons (rstrip('/')+lower):
    model_switch.py:151-158, config.py:1554-1558, main.py:4147-4149."""
    return str(value or "").strip().rstrip("/").lower()


def custom_provider_slug(display_name: str) -> str:
    """hermes_cli/providers.py:748-758, for a legacy custom_providers entry (which
    carries no provider_key, so the normalized DISPLAY NAME is the identity)."""
    normalized = str(display_name or "").strip().lower().replace(" ", "-")
    return normalized if normalized.startswith("custom:") else "custom:" + normalized


def custom_provider_aliases(display_name: str) -> set:
    """hermes_cli/providers.py:761-777 — every identity that resolves to the entry."""
    raw = str(display_name or "").strip().lower()
    if not raw:
        return set()
    normalized = raw.replace(" ", "-")
    out = {raw, normalized, custom_provider_slug(normalized)}
    if normalized.startswith("custom:"):
        suffix = normalized.split(":", 1)[1]
        if suffix:
            out.update({suffix, "custom:" + normalized})
    return out


def auto_provider_name(base_url: str) -> str:
    """hermes_cli/main.py:4083-4101 — the name Hermes's OWN writer generates when it
    registers a bare custom endpoint (POST /api/model/set does this for
    `provider: custom`, web_server.py:6757-6773). Recognising it is what lets us
    ADOPT Hermes's auto-registered row instead of adding a second one beside it."""
    clean = str(base_url or "").replace("https://", "").replace("http://", "").rstrip("/")
    clean = re.sub(r"/v1/?$", "", clean)
    name = clean.split("/")[0]
    if "localhost" in name or "127.0.0.1" in name:
        return "Local (%s)" % name
    if "runpod" in name.lower():
        return "RunPod (%s)" % name
    return name.capitalize()


def entry_url(entry: dict) -> str:
    """The three spellings upstream accepts, in its own precedence order
    (config.py:1352-1368; model_switch.py:2986-2991)."""
    for key in ("base_url", "url", "api"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# ── the catalog ───────────────────────────────────────────────────────────────

def registry_models(root: str, current_wire: str, ctxlen: int) -> "dict[str, dict]":
    """Every chat model in OUR registry, keyed by its WIRE id.

    ⚠️ ONE identifier, not two (this is where Hermes differs from OpenCode): the key
    of `models` IS what Hermes sends as the model name, so it must be the wire id —
    llama.cpp is launched with `--alias <registry id>` so the id is the served name;
    the MLX servers treat the request's `model` as a model to LOAD and need the
    registry PATH. Same rule as bridge/app.py::wire_model_id, the OpenCode block and
    seed_odysseus_jan._wire_model. An MLX row therefore shows as a path in Hermes's
    picker — ugly, and deliberate: a prettier label would be a name Hermes cannot
    send.

    The value is per-model metadata, NOT an allowlist — upstream reads a dict shape
    as `_save_custom_provider`-style metadata (model_switch.py:104-127
    `_models_config_is_allowlist`), and config.py:1723-1740 reads
    `models.<id>.context_length` as the per-model context override.
    """
    models: "dict[str, dict]" = {}
    try:
        with open(os.path.join(root, "data", "models.json"), encoding="utf-8") as fh:
            reg = json.load(fh).get("models", []) or []
    except Exception:                                               # noqa: BLE001
        reg = []
    # S29 — one definition of which rows may be offered (bridge/core/modelreg.py):
    # chat · not hidden · not flagged `absent` · file not provably gone. This seeder
    # was already the most careful of the four (it checked BOTH audio spellings) and it
    # was still missing the file clause, which is the one that matters after a deletion
    # in LM Studio. The inline fallback keeps this script standalone-correct.
    if _MODELREG is not None:
        rows = _MODELREG.offerable(reg)
    else:
        rows = [m for m in reg
                if isinstance(m, dict) and m.get("kind") != "audio"
                and not m.get("hidden") and m.get("absent") is not True
                and str(m.get("id") or "").strip()
                and not str(m.get("format") or "").lower().startswith(("tts-", "stt-"))]
    for m in rows:
        mid = str(m.get("id") or "").strip()
        fmt = str(m.get("format") or "gguf").strip().lower()
        wire = ((m.get("path") or "").strip() or mid) if fmt == "mlx" else mid
        try:
            ctx = int(m.get("ctx") or 0)
        except (TypeError, ValueError):
            ctx = 0
        meta = {}
        if ctx > 0:
            meta["context_length"] = ctx
        models[wire] = meta
    # The model the runner is actually serving is ALWAYS offered, even if the
    # registry file is stale or unreadable — the row must never be empty, for the
    # same measured reason OpenCode's block carries a fallback: an empty list is a
    # row that cannot explain itself.
    if current_wire and current_wire not in models:
        models[current_wire] = {"context_length": ctxlen} if ctxlen > 0 else {}
    return models


# ── the main slot: the never-clobber planner (PURE — the tests call it directly) ──

# How a `model.base_url` WE wrote looks even with no marker file (fresh clone, a user
# tidy-up): loopback + the /v1 root the runner serves. Same shape rule as
# seed_odysseus_jan.looks_like_our_runner_url.
_OUR_URL_RE = re.compile(r"^https?://(?:127\.0\.0\.1|localhost|\[::1\]):\d+/v1/?$", re.I)

MODEL_KEYS = ("default", "provider", "base_url", "api_key", "context_length")


def looks_like_our_runner_url(url) -> bool:
    """PURE: whether `url` has the shape THIS SCRIPT writes."""
    return bool(_OUR_URL_RE.match(str(url or "").strip()))


def model_block_plan(model_cfg, marker, want, our_aliases, seeded_before=False) -> tuple:
    """PURE: (changes, notes) for `model:` — the whole never-clobber matrix (U12).

    `model_cfg`     — the existing block (dict; a bare string = a very old config).
    `marker`        — what we last wrote ({} = no evidence; see `seeded_before`).
    `want`          — the values this Start would like to see.
    `our_aliases`   — every identity that resolves to OUR provider entry.
    `seeded_before` — TRUE when the CONFIG ITSELF proves this script has run against
                      it (our named row was already there, or the main slot already
                      pointed at our slug). It is what BOUNDS bootstrap.

    BOOTSTRAP is the benefit of the doubt owed to a config written before this slice:
    Start re-asserted `model:` on every run back then, so those values ARE ours and are
    refreshed once. Given without bound it becomes a clobber: delete data/ (a tidy-up, a
    fresh snapshot) and the next Start would hand the user's picked model back to us —
    the very defect U12 is about, one directory removal away. So the file's own evidence
    outranks the missing marker: a config we have demonstrably seeded is NEVER in
    bootstrap, and every value we cannot prove is ours is honoured out loud.
    """
    notes: "list[str]" = []
    if not isinstance(model_cfg, dict):
        # A bare `model: <name>` string is upstream's oldest shape; there is nothing to
        # honour inside it, so the block is (re)built.
        return dict(want), (["model: replaced the legacy bare-string form"]
                            if model_cfg else [])
    bootstrap = not marker and not seeded_before
    ch = {}
    for key in MODEL_KEYS:
        target = want.get(key)
        if target in (None, ""):
            continue
        cur = model_cfg.get(key)
        cur_s = "" if cur is None else str(cur).strip()
        if cur_s == str(target):
            continue
        if not cur_s:
            ch[key] = target                       # rule 1: create-if-absent
            continue
        ours = bool(marker.get(key)) and cur_s == str(marker.get(key))
        if not ours and key == "provider":
            # The anonymous shapes we used to write, plus any slug that still points at
            # our own entry (that is how a RENAME repoints rather than duplicating).
            ours = cur_s.lower() in ({"custom", "local"} | set(our_aliases))
            if not ours and cur_s.lower().startswith("custom:"):
                # A `custom:` slug that resolves to nothing can only be OUR pointer,
                # left dangling by a rename — repairing it steals from no one.
                ours = True
                notes.append("model.provider: repaired a dangling %r" % cur_s)
        if not ours and key == "base_url":
            ours = looks_like_our_runner_url(cur_s)
        if not ours and key == "api_key" and bootstrap:
            ours = True            # the key was ours on every Start before the marker
        if not ours and bootstrap and key in ("default", "context_length"):
            ours = True            # ditto — see BOOTSTRAP in the header
        if ours:
            ch[key] = target
        else:
            notes.append("model.%s: honoured your %s (%s) — not overwritten"
                         % (key, "choice" if key != "default" else "model",
                            "redacted" if key == "api_key" else cur_s))
    return ch, notes


def next_marker(marker, model_cfg, want) -> dict:
    """PURE: the marker to persist — every managed value that is OURS afterwards.

    "Ours" = the value now on disk equals the value we wanted to write: either we just
    wrote it, or it was already exactly that. A value we HONOURED differs from `want`
    by definition, so it is never recorded — recording it would make it ours next run
    and clobber it one Start later (the subtle half of the house rule).

    ⚠️ WALKED BUG, and the reason this takes `model_cfg` rather than just the changes:
    recording only the keys CHANGED this run left the marker EMPTY after a no-op Start
    (nothing changes when everything already matches), so the script stayed in
    bootstrap for ever — and bootstrap treats the block as ours. Measured live: a model
    picked in Hermes's own picker was reset by the very next restart, the exact defect
    U12 is about. The marker must record what is ours, not merely what moved.
    """
    out = dict(marker or {})
    cur = model_cfg if isinstance(model_cfg, dict) else {}
    for k in MODEL_KEYS:
        target = want.get(k)
        if target in (None, ""):
            continue
        have = cur.get(k)
        if have is not None and str(have).strip() == str(target):
            out[k] = target
    return out


# ── the write ─────────────────────────────────────────────────────────────────

def main() -> int:
    cfg_path = os.environ.get("HERMES_CFG") or os.path.expanduser("~/.hermes/config.yaml")
    base_url = (os.environ.get("BASE_URL") or "").strip()
    api_key = (os.environ.get("KEY") or "").strip()
    wire = (os.environ.get("MODEL") or "").strip()
    root = os.environ.get("MOT_DECK_ROOT") or os.getcwd()
    try:
        ctxlen = int(os.environ.get("CTXLEN") or 0)
    except ValueError:
        ctxlen = 0
    if not base_url:
        print("[motdeck] WARNING: no runner endpoint — Hermes provider NOT seeded")
        return 0

    try:
        raw = open(cfg_path, encoding="utf-8").read() if os.path.exists(cfg_path) else ""
        data = yaml.safe_load(raw) if raw.strip() else {}
    except Exception as exc:                                        # noqa: BLE001
        # A config we cannot parse is a config we must not rewrite (it may be the
        # user's half-finished edit). Say so and leave the file alone; the anonymous
        # model.* wiring the Start script writes still routes every turn.
        print("[motdeck] WARNING: could not parse or read %s — provider NOT seeded (values redacted)"
              % cfg_path)
        return 0
    if not isinstance(data, dict):
        print("[motdeck] WARNING: Hermes config is not a mapping — left untouched")
        return 0
    before = json.dumps(data, sort_keys=True, default=str)

    providers = data.get("custom_providers")
    if not isinstance(providers, list):
        # A dict here is the documented user mistake (missing '-' on each entry;
        # model_switch/runtime_provider both warn and bail). Never overwrite it —
        # that would delete configuration the user is one dash away from fixing.
        if providers is not None:
            print("[motdeck] WARNING: custom_providers in %s is not a list — provider "
                  "NOT seeded (each entry needs a leading '-'; run `hermes doctor`)"
                  % cfg_path)
            return 0
        providers = []

    ours = None
    for entry in providers:
        if isinstance(entry, dict) and norm_url(entry_url(entry)) == norm_url(base_url):
            ours = entry
            break

    # ⚠️ READ BEFORE WE TOUCH ANYTHING: does the config itself prove we have seeded it
    # before? `discover_models: false` on the row at our endpoint is OUR fingerprint —
    # Hermes's own writers never emit it (main.py::_save_custom_provider writes name/
    # base_url/api_key/models only). This is what bounds bootstrap in model_block_plan:
    # a marker that was deleted must not hand the user's edits back to us.
    seeded_before = isinstance(ours, dict) and ours.get("discover_models") is False

    # The marker, read here because the catalog merge below needs its `models` list.
    marker_path = os.path.join(root, "data", "hermes_seed_state.json")
    try:
        with open(marker_path, encoding="utf-8") as fh:
            marker = json.load(fh)
        marker = marker if isinstance(marker, dict) else {}
    except Exception:                                               # noqa: BLE001
        marker = {}

    notes = []
    if ours is None:
        ours = {"name": PRODUCT_NAME, "base_url": base_url}
        providers.append(ours)
        notes.append("created")

    # ── name: seeded, then the user's (rule 4). Default names we may replace are
    # OUR product name and the one Hermes's own auto-registration writes.
    cur_name = str(ours.get("name") or "").strip()
    default_names = {PRODUCT_NAME.lower(), auto_provider_name(base_url).lower(), ""}
    if cur_name.lower() in default_names:
        if cur_name != PRODUCT_NAME:
            notes.append("named %r (was %r)" % (PRODUCT_NAME, cur_name or "unnamed"))
        ours["name"] = PRODUCT_NAME
    else:
        notes.append("kept your name %r" % cur_name)
    final_name = str(ours.get("name") or PRODUCT_NAME).strip()

    # ── base_url: normalise the spelling only if the entry used an alias key, so the
    # entry we own always carries the canonical field the resolver reads first.
    if "base_url" not in ours:
        ours["base_url"] = base_url

    # ── credential: ours UNLESS the user pointed the entry at an env var.
    if str(ours.get("key_env") or "").strip():
        notes.append("key_env kept (api_key not written)")
    elif api_key and ours.get("api_key") != api_key:
        ours["api_key"] = api_key

    # ── the catalog: union-merge. Registry rows are refreshed; anything the user (or
    # an older Hermes probe) put there that we do not know is KEPT.
    wanted = registry_models(root, wire, ctxlen)
    existing = ours.get("models")
    merged: "dict[str, dict]" = {}
    if isinstance(existing, dict):
        for mid, meta in existing.items():
            merged[str(mid)] = meta if isinstance(meta, dict) else {}
    elif isinstance(existing, list):
        # A plain list is upstream's own discovery cache
        # (model_switch.py:_save_discovered_models_to_config) — not a user edit, and
        # it is ALSO the shape upstream reads back as an allowlist. Replacing it with
        # the dict shape is what stops the row from self-pinning to a stale probe.
        for item in existing:
            if isinstance(item, str) and item.strip():
                merged.setdefault(item.strip(), {})
    for mid, meta in wanted.items():
        cur = merged.get(mid)
        merged[mid] = {**(cur if isinstance(cur, dict) else {}), **meta}
    # ── and the other half of union-merge: PRUNE OUR OWN DEAD IDS. Found live — the
    # row still offered a 27B Debi had deleted from the registry (its file was gone,
    # ledger U15) plus six other ids from older registries, because a union never
    # shrinks. A picker row promising models MOT Deck does not have is the lie this
    # slice exists to remove, so ids WE wrote and the registry no longer lists are
    # dropped. Only ids the marker proves are ours: anything the user (or an older
    # Hermes probe) added is not in that list and is kept, which is the odyvision
    # "delete only our own stale rows" rule. First run after this change the marker
    # carries no list yet, so nothing is pruned until it does — a Start late, never
    # a user's model early.
    prev_ids = [str(x) for x in (marker.get("models") or [])]
    if marker and "models" not in marker and seeded_before:
        # ONE-SHOT MIGRATION, and the only place ownership is inferred rather than
        # proven: a marker written before the catalog was tracked, on a row that
        # carries our own fingerprint. Every id in it was put there by an earlier run
        # of THIS script (that is what the fingerprint means), so the dead ids it
        # accumulated are ours to drop — measured on Debi's live config, which had 21
        # models for a 14-model registry. After this run the marker carries the list
        # and ownership is proven again, never inferred.
        prev_ids = list(merged)
    # …and two ids are never dropped whatever the registry says: the model the runner
    # is serving, and the one the main slot points at. WALKED: the first prune removed
    # the very model picked inside Hermes (its id had left the registry), leaving the
    # slot pointing at a model its own row no longer listed — Hermes then showed it
    # anyway, so the count on screen disagreed with the config. Honouring a pick means
    # keeping it visible.
    _cur = data.get("model") if isinstance(data.get("model"), dict) else {}
    _picked = str(_cur.get("default") or "").strip()
    _picked_is_ours = _picked and str(_cur.get("provider") or "").strip().lower() \
        in custom_provider_aliases(final_name)
    injected = set()
    if _picked_is_ours and _picked not in merged:
        # It was picked THROUGH our row, so our row must offer it — a main slot whose
        # own provider does not list its model is a picker that argues with itself.
        # It goes in the marker too (below): WE wrote it, so once the pick moves on and
        # the registry still does not know it, it is ours to drop. Without that it would
        # be permanent junk — the exact accumulation this prune exists to end.
        merged[_picked] = {}
        injected.add(_picked)
    keep = {wire, _picked}
    pruned = [mid for mid in prev_ids
              if mid in merged and mid not in wanted and mid not in keep]
    for mid in pruned:
        merged.pop(mid, None)
    if pruned:
        notes.append("dropped %d model(s) we seeded that the registry no longer has "
                     "(%s%s)" % (len(pruned), ", ".join(pruned[:3]),
                                 ", …" if len(pruned) > 3 else ""))
    ours["models"] = merged

    # ── pin the catalog. Without this the row is live-probed and collapses to the ONE
    # model llama-server is currently serving; with it the picker holds the registry
    # whether the runner is up or down (the OpenCode property).
    ours["discover_models"] = False
    if ctxlen > 0:
        ours["context_length"] = ctxlen

    data["custom_providers"] = providers

    # ── THE MAIN SLOT (ledger U12). One writer for the whole file: this used to be a
    # separate text patch in start_component.sh that re-asserted every managed key on
    # every Start. The migration from the anonymous shape happens here too — writing
    # the named slug in the SAME pass that creates the row is what stops Hermes from
    # rendering the bare "custom" row beside ours (model_switch.py section 3b
    # suppresses itself once a custom_providers entry carries this base_url).
    slug = custom_provider_slug(final_name)
    aliases = custom_provider_aliases(final_name)
    want = {"default": wire, "provider": slug, "base_url": base_url,
            "api_key": api_key, "context_length": ctxlen if ctxlen > 0 else None}
    model_cfg = data.get("model")
    if isinstance(model_cfg, dict) and str(model_cfg.get("provider") or "").strip() \
            .lower() in aliases:
        seeded_before = True   # the main slot already points at our named row
    changes, model_notes = model_block_plan(model_cfg, marker, want, aliases,
                                            seeded_before)
    if changes:
        if not isinstance(model_cfg, dict):
            model_cfg = {}
        model_cfg.update(changes)
        data["model"] = model_cfg
    notes.extend(model_notes)
    # THE HONEST LINE the deck owes the user when their pick and the loaded model
    # differ: llama.cpp ignores the request's `model` field and answers from whatever
    # is resident, so a mismatch is silent everywhere else (ledger U13/U14).
    kept_model = str((data.get("model") or {}).get("default") or "") \
        if isinstance(data.get("model"), dict) else ""
    if wire and kept_model and kept_model != wire:
        notes.append("MOT Deck has %r loaded — this turn is answered by THAT model, "
                     "whatever the picker says" % wire)

    after = json.dumps(data, sort_keys=True, default=str)
    changed = after != before
    if changed:
        d = os.path.dirname(cfg_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False,
                               allow_unicode=True)
            os.replace(tmp, cfg_path)
        except Exception:                                           # noqa: BLE001
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ⚠️ THE MARKER IS WRITTEN ONLY AFTER THE CONFIG WRITE SUCCEEDED. Recording a value
    # we did not manage to write would make a value we never wrote "ours" next Start —
    # the marker's whole job is to be evidence, so it must never run ahead of the file.
    try:
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        mk = next_marker(marker, data.get("model"), want)
        # The catalog half of the same rule: the ids we wrote THIS run — never the
        # merged list, which also holds ids the user added and we must never prune.
        # Ours = what we wrote this run, what we put back for the pick, and what was
        # ours already and only survived because `keep` shielded it (dropping it from
        # the marker would launder a stale id of ours into "the user's" for ever).
        mk["models"] = sorted((set(wanted) | injected | (set(prev_ids) & keep))
                              & set(merged))
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(mk, fh, indent=2)
    except Exception:                                               # noqa: BLE001
        pass

    # The Start script prints/verifies against this one.
    try:
        with open(os.path.join(root, "data", "hermes-provider.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"slug": slug, "name": final_name, "base_url": base_url,
                       "models": len(merged), "changed": changed,
                       "model": kept_model,
                       "wrote": sorted(changes), "honoured": model_notes}, fh, indent=2)
    except Exception:                                               # noqa: BLE001
        pass

    print('[motdeck] Hermes provider "%s" -> %s · %d model(s) · slug %s%s'
          % (final_name, base_url, len(merged), slug,
             "" if changed else " (already current)"))
    print("[motdeck]   main model: %s @ %s (key %s, ctx %s)"
          % (kept_model or "unset", base_url, "set" if api_key else "none",
             (data.get("model") or {}).get("context_length", "auto")))
    for n in notes:
        print("[motdeck]   %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
