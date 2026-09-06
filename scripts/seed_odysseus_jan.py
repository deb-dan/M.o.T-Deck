#!/usr/bin/env python3
# seed_odysseus_jan.py — Odysseus DB seed: wire it to the local runner endpoint,
# ONCE, and then NEVER CLOBBER THE HUMAN AGAIN.
#
# Invoked by MOT Deck (install_component.sh / start_component.sh) with the
# odysseus venv active and cwd = vendor/odysseus, after setup.py has created the DB:
#   ( cd vendor/odysseus && python <motdeck>/scripts/seed_odysseus_jan.py )
#
# This is the "connect" half of one-switch provisioning for Odysseus: it creates a
# single model endpoint pointing at our runner, pins EVERY chat model in our registry
# onto it so Odysseus's OWN picker is populated in isolation, and seeds (never
# enforces) the default chat model — so a fresh login can chat with zero UI
# configuration, and a user who then makes the row their own keeps it.
#
# ── WHY THIS FILE IS SHAPED THE WAY IT IS (U11, ledger row, isolation research) ──
# Until v1.5.48 this script re-asserted `name`, `api_key` and `is_enabled=True` on
# EVERY Start. A user who renamed the row in Odysseus's own Settings, or pasted their
# own key, or DELIBERATELY DISABLED the endpoint, had that undone the next time the
# component was started — silently, with no line saying so. That is the never-clobber
# violation the isolation research found (docs/research/2026-08-29-isolation-mode.md
# §3(3), §7), and the house standard it fails is v1.5.33's odyvision registration
# (bridge/routers/odyvision.py): match on stable identity, migrate only rows still
# wearing a DEFAULT name, delete/rewrite only what is provably OURS.
#
# The three rules every write below obeys:
#   1. CREATE-IF-ABSENT. A row we did not create is never invented twice; a row that
#      exists is UPDATED in place, field by field, under rule 2.
#   2. UPDATE ONLY WHAT IS PROVABLY OURS AND STALE. "Provably ours" = the value equals
#      what WE last wrote (recorded in data/ody_seed_state.json, the marker), or it is
#      still a shipped default (a name in NAMES_ALL; a loopback runner-shaped URL; an
#      empty field). Anything else is the human's and is left alone WITH A PRINTED LINE
#      saying we honoured it — a silent no-op is its own kind of lie.
#   3. NEVER RE-ENABLE. `is_enabled` is written exactly once, at creation. A human who
#      switches this endpoint off stays switched off, for ever, no matter how many
#      times the component is restarted.
#
# ── WHAT ODYSSEUS'S SCHEMA ACTUALLY SUPPORTS (read at the pin, contract-pinned) ──
# ModelEndpoint carries BOTH a probe cache and an admin list (core/database.py:530-531):
#   cached_models — "last-known model IDs", overwritten by Odysseus's own discovery;
#   pinned_models — "admin-pinned model IDs (manual, MAY NOT APPEAR IN /v1/models)".
# For a LOCAL endpoint the picker shows `_visible_models(cached, hidden, pinned)` =
# cached ∪ pinned − hidden (routes/model_routes.py:1300-1322, :1350-1367). So the
# OpenCode property — models are CONFIG-RESIDENT FACTS, not the result of a live probe —
# is reachable here without inventing anything: we write the registry into
# `pinned_models`, and the picker holds them with the runner down.
# `hidden_models` is never touched: it is how the human hides what they don't want, and
# hidden wins over pinned in that same merge.
# Pinned by bridge/contract_tests/test_odysseus_seed_contract.py; the never-clobber
# matrix is pinned by bridge/tests/test_odysseus_seed.py.
#
# Endpoint + model schema verified against pinned Odysseus:
#   core/database.py (ModelEndpoint), routes/cookbook_routes.py (local-endpoint mirror),
#   routes/model_routes.py + src/endpoint_resolver.py (default_endpoint_id/default_model),
#   src/settings.py (global settings JSON).

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:6767/v1")
API_KEY = os.environ.get("JAN_API_KEY", "").strip() or None   # headless runner needs a key
NAME = "Local runner"   # display name in Odysseus (Jan is gone; id stays local-jan for fan-out)
# Every default name this row has EVER shipped under — the odyvision precedent
# (ODY_VLSHIM_EP_NAMES_ALL). Used for exactly one thing: recognising a row that still
# wears a name WE chose, so a future rename of the default can migrate forward without
# ever touching a name a human typed.
NAMES_ALL = (NAME, "Jan (local)")
ENDPOINT_ID = "local-jan"          # stable caller-supplied String PK (idempotent)
# ⚠️ THE PK IS THE PROOF OF OWNERSHIP. Odysseus's own "add endpoint" form gives new rows
# a RANDOM 8-char uuid (routes/model_routes.py:2146), so a row whose id is exactly
# `local-jan` can only have been created by this script. That is what lets us update it
# at all; everything inside it still follows the marker rules above.
# MOT Deck root — this script is invoked by absolute path with cwd=vendor/odysseus.
MOT_DECK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# What WE last wrote. Not a cache and not state Odysseus reads — purely our evidence for
# "this value is still ours", so a human's edit is distinguishable from our own leftover.
STATE_PATH = os.environ.get("MOT_DECK_ODY_SEED_STATE") or os.path.join(
    MOT_DECK_ROOT, "data", "ody_seed_state.json")
# Our own URL shape: how a row we wrote LOOKS even when the marker file is gone
# (fresh clone, user tidy-up). Loopback + the /v1 root the runner serves.
_OUR_URL_RE = re.compile(r"^https?://(?:127\.0\.0\.1|localhost|\[::1\]):\d+/v1/?$", re.I)


# ── S29: the ONE definition of an offerable model (bridge/core/modelreg.py) ──
# Loaded BY PATH, resolved from THIS FILE, because this script runs under Odysseus's
# own venv with cwd=vendor/odysseus — neither the bridge package nor the repo root is
# importable from there. None ⇒ registry_wire_models falls back to its own inline rule
# (which now also honours the `absent` flag), because a helper that failed to import
# must never empty a working picker.
def _load_modelreg():
    try:
        import importlib.util
        p = os.path.join(MOT_DECK_ROOT, "bridge", "core", "modelreg.py")
        spec = importlib.util.spec_from_file_location("motdeck_modelreg", p)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:                                          # noqa: BLE001
        return None


_MODELREG = _load_modelreg()


# ── PURE HELPERS (no DB, no network — executed directly by the tests) ────────────

def looks_like_our_runner_url(url) -> bool:
    """PURE: whether `url` has the shape THIS SCRIPT writes — a loopback OpenAI root.

    Used only as the marker-less fallback for "is this base_url still ours?". A user
    who repoints the row at their own box (another host, another path) fails this and
    is honoured; a port change between Starts (:1337 → :6767) passes and is refreshed.
    """
    return bool(_OUR_URL_RE.match(str(url or "").strip()))


def runner_key_accepted(base_url, api_key):
    """Return True/False for an authoritative auth result, else None.

    A custom key that still works is user intent and survives every seed. A 401/403
    from the exact loopback runner is authoritative evidence that the stored key can
    no longer serve this M.O.T-owned endpoint; only then may the stable ``local-jan``
    row be repaired. Network failures grant no write authority.
    """
    try:
        req = urllib.request.Request(str(base_url or "").rstrip("/") + "/models")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=3) as response:  # noqa: S310
            return True if response.status == 200 else None
    except urllib.error.HTTPError as exc:
        return False if exc.code in (401, 403) else None
    except Exception:  # noqa: BLE001 -- absence of evidence authorizes no write
        return None


def registry_wire_models(models, active: str = "") -> list:
    """PURE: every CHAT model in our registry, as the identifier Odysseus must SEND.

    The two-identifier rule, same as bridge/core/modelid.py::wire_model_id and the
    OpenCode provider block (start_component.sh:938-971): llama.cpp is launched with
    `--alias <registry id>` so its wire name IS the id; the MLX servers treat the
    request's `model` field as a model to LOAD and need the registry PATH (an id would
    be resolved on HuggingFace → 404 → runner 400).

    Audio models are dropped (they are not chat models and Odysseus would offer them in
    the chat picker), so are registry rows marked hidden. The ACTIVE model is ordered
    first so a fresh default lands on the one the runner has actually loaded.

    ⚠️ S29 — WHICH ROWS QUALIFY IS NOT DECIDED HERE ANY MORE. bridge/core/modelreg.py
    owns the one definition (chat · not hidden · not flagged `absent` · file not
    provably gone) and all four seeders import it. The clause this function was missing
    is the FILE one: Odysseus went on pinning models whose weights had been deleted in
    LM Studio, and llama.cpp answers those requests with whatever it has loaded, so the
    picker offered a choice that silently became a different model.

    A failure to load the helper falls back to the old inline rule rather than
    enumerating nothing — an empty list here would empty a working picker.
    """
    if _MODELREG is not None:
        return _MODELREG.offerable_wire_ids(models, active)
    out = []
    for m in models or []:
        if not isinstance(m, dict) or m.get("kind") == "audio" or m.get("hidden"):
            continue
        if m.get("absent") is True:
            continue
        mid = str(m.get("id") or "").strip()
        if not mid:
            continue
        if str(m.get("format") or "gguf").strip().lower() == "mlx":
            wire = str(m.get("path") or "").strip() or mid
        else:
            wire = mid
        if wire not in out:
            out.append(wire)
    a = str(active or "").strip()
    if a:
        if a in out:
            out.remove(a)
        out.insert(0, a)
    return out


def endpoint_plan(row, marker, want) -> tuple:
    """PURE: (changes, notes) for ONE endpoint row — the whole never-clobber matrix.

    `row`    — the existing DB row as a plain dict, or None to create it.
    `marker` — what we last wrote for this row ({} when we have no record).
    `want`   — {"name","base_url","api_key","models"} from motdeck.yaml + the registry.

    `changes` is only the fields that must actually be written; `notes` is the honest
    log of every field we deliberately did NOT touch and why.
    """
    notes = []
    w_models = list(want.get("models") or [])
    if row is None:
        first = {
            "id": ENDPOINT_ID,
            "name": want["name"],
            "base_url": want["base_url"],
            "api_key": want.get("api_key"),
            # The ONLY place is_enabled is ever written. See rule 3.
            "is_enabled": True,
            "model_type": "llm",
            "endpoint_kind": "local",
            "model_refresh_mode": "auto",
            "supports_tools": True,
            "owner": None,                 # NULL = shared/visible to all + admin
        }
        if w_models:      # an empty registry writes NOTHING, not an empty list
            first["cached_models"] = list(w_models)
            first["pinned_models"] = list(w_models)
        return first, []

    ch = {}
    # No record of our own writes AND the row carries OUR primary key (which only this
    # script can have created): infer ownership from the shipped shapes below. A row we
    # merely ADOPTED (the user made it, random uuid id) never gets that benefit — every
    # value in it is theirs until we write one ourselves.
    bootstrap = (not marker) and str(row.get("id") or "") == ENDPOINT_ID

    # ── name: migrate only a row still wearing one of OUR default names ──────────
    cur_name = str(row.get("name") or "").strip()
    if cur_name != want["name"]:
        if cur_name in NAMES_ALL or (marker.get("name") and cur_name == marker["name"]):
            ch["name"] = want["name"]
        else:
            notes.append(f"name: honoured your rename ({cur_name!r}) — not renamed")

    # ── base_url: refresh only OUR stale address ─────────────────────────────────
    cur_url = str(row.get("base_url") or "").strip()
    if cur_url.rstrip("/") != str(want["base_url"]).rstrip("/"):
        ours = (cur_url == marker.get("base_url")) or (bootstrap and looks_like_our_runner_url(cur_url))
        if ours:
            ch["base_url"] = want["base_url"]
        else:
            notes.append(f"base_url: honoured your address ({cur_url}) — not repointed")

    # ── api_key: fill empty, rotate ours, repair only a PROVEN-REJECTED local key ─
    cur_key = row.get("api_key") or ""
    if cur_key != (want.get("api_key") or ""):
        rejected_local = (want.get("current_key_accepted") is False
                          and str(row.get("id") or "") == ENDPOINT_ID
                          and looks_like_our_runner_url(row.get("base_url")))
        if not cur_key or cur_key == (marker.get("api_key") or "\0") or rejected_local:
            ch["api_key"] = want.get("api_key")
            if rejected_local and cur_key != (marker.get("api_key") or "\0"):
                notes.append("api_key: replaced only after the M.O.T runner rejected it")
        else:
            verdict = want.get("current_key_accepted")
            reason = "accepted by the runner" if verdict is True else "not proven invalid"
            notes.append(f"api_key: honoured your key ({reason}) — not replaced")

    # ── is_enabled: NEVER. Not once, not on a restart, not on a reinstall. ───────
    if not row.get("is_enabled"):
        notes.append("is_enabled: left DISABLED — you disabled this endpoint; "
                     "re-enable it in Odysseus → Settings → Model endpoints")

    # ── the mechanical fields: fill only when Odysseus has nothing there ─────────
    # Each of these is togglable in Odysseus's own endpoint form, so an existing value
    # is a decision — ours or theirs, and we cannot tell them apart. Fill-if-empty only.
    for field, value in (("model_type", "llm"), ("endpoint_kind", "local"),
                         ("model_refresh_mode", "auto"), ("supports_tools", True)):
        if row.get(field) in (None, ""):
            ch[field] = value

    # ── the model lists: the picker's contents ───────────────────────────────────
    # pinned_models is the admin allow-list that survives the runner being down. We own
    # it while it still holds what we wrote — or, with no marker, while it holds at most
    # the ONE model the pre-U11 seed used to write (its exact shape). A longer list we
    # cannot account for is a human's curation and is left alone.
    # ⚠️ `w_models` EMPTY IS NEVER A DECISION. data/models.json unreadable for one Start
    # (mid-write, a bad mount) must not empty a picker that was full a minute ago — the
    # absence of information is not information.
    cur_pinned = _as_list(row.get("pinned_models"))
    if w_models and cur_pinned != w_models:
        ours = (cur_pinned == _as_list(marker.get("pinned_models"))
                or not cur_pinned
                or (bootstrap and len(cur_pinned) <= 1))
        if ours:
            ch["pinned_models"] = list(w_models)
        else:
            notes.append(f"pinned_models: honoured your {len(cur_pinned)}-model "
                         f"selection — not re-seeded")
    # cached_models is Odysseus's OWN probe cache (it rewrites it on every refresh); we
    # only prime it so the picker is populated before the first probe ever runs.
    cur_cached = _as_list(row.get("cached_models"))
    if w_models and (not cur_cached or cur_cached == _as_list(marker.get("cached_models"))
                     or (bootstrap and len(cur_cached) <= 1)):
        if cur_cached != w_models:
            ch["cached_models"] = list(w_models)
    # hidden_models is NEVER touched: it is how a human hides a model, and hidden beats
    # pinned in Odysseus's own merge (_visible_models), so their choice keeps winning.
    return ch, notes


def settings_plan(settings, ep_id: str, ep_enabled: bool, visible, wire: str,
                  known_ep_ids=None, marker=None) -> tuple:
    """PURE: (changes, notes) for the GLOBAL default chat model — seeded, never enforced.

    Same rule as OpenCode's default-model block (start_component.sh:1059-1086): set it
    when nothing is configured, or when the configured choice DANGLES (names an endpoint
    that no longer exists, or a model this endpoint no longer offers). A working choice
    a human made inside Odysseus is never overwritten.

    ⚠️ THE FOURTH STATE, ADDED BY S28: *our own previous write*. Rule 2 at the top of
    this file already says "provably ours = the value equals what WE last wrote", and
    every endpoint field obeys it — but `default_model` had no marker, so a value THIS
    SCRIPT seeded two switches ago was honoured as if a human had chosen it. The
    post-switch audit is what that costs: switch the runner twice and Odysseus's chip
    keeps naming the model from the switch before, valid and stale, for ever. With the
    marker, our own leftover is refreshed and a human's pick is still untouchable — the
    distinction the honour rule was always trying to make.
    """
    ch, notes = {}, []
    marker = marker or {}
    cur_ep = str(settings.get("default_endpoint_id") or "").strip()
    ids = set(known_ep_ids or ()) | {ep_id}
    if not cur_ep or cur_ep not in ids:
        if ep_enabled:
            ch["default_endpoint_id"] = ep_id
        else:
            notes.append("default_endpoint_id: not set to a DISABLED endpoint")
    elif cur_ep != ep_id:
        notes.append(f"default_endpoint_id: honoured your choice ({cur_ep})")

    on_ours = ch.get("default_endpoint_id", cur_ep) == ep_id
    cur_model = str(settings.get("default_model") or "").strip()
    ours = bool(cur_model) and cur_model == str(marker.get("default_model") or "\0")
    dangling = bool(on_ours and visible and cur_model and cur_model not in visible)
    if wire and cur_model != wire and (not cur_model or dangling or (on_ours and ours)):
        if dangling:
            notes.append(f"default_model: {cur_model!r} is no longer offered by this "
                         f"endpoint — reset to the loaded model")
        elif ours:
            notes.append(f"default_model: {cur_model!r} was OUR OWN last seed, not your "
                         f"choice — refreshed to the model the runner is serving")
        ch["default_model"] = wire
    elif cur_model and cur_model != wire and on_ours:
        notes.append(f"default_model: honoured your choice ({cur_model})")
    return ch, notes


def next_marker(marker, changes) -> dict:
    """PURE: the marker to persist — ONLY the values we actually wrote this run.

    Critical, and the one thing an obvious implementation gets wrong: recording a value
    we HONOURED (the user's rename) would make it "ours" next run and clobber it one
    Start later. Fields we did not write keep whatever we last wrote for them.
    """
    out = dict(marker or {})
    for k in ("name", "base_url", "api_key", "pinned_models", "cached_models",
              "default_model"):
        if k in changes:
            v = changes[k]
            out[k] = list(v) if isinstance(v, list) else v
    return out


def _as_list(raw) -> list:
    """PURE: Odysseus stores these columns as a JSON string (or NULL)."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        v = json.loads(raw)
    except Exception:
        return []
    return [str(x) for x in v] if isinstance(v, list) else []


def live_wire(probed, registry) -> str:
    """PURE: a /v1/models probe answer → the wire id we are willing to BELIEVE, or ''.

    ⚠️ THE RULE THE HERMES ARM ESTABLISHED (v1.5.56) AND THIS SCRIPT DID NOT HAVE:
    *the runner's own answer outranks motdeck.yaml*. The post-switch coherence audit
    (docs/research/2026-08-29-post-switch-audit.md §1, root-cause class 4) measured what
    pin-first seeding costs: motdeck.yaml's pin had drifted onto a 27B whose file was
    deleted, so every Odysseus Start re-seeded that ghost as the default AND force-
    inserted it into `pinned_models` — the stale pin did not merely persist, it
    PROPAGATED into a third-party picker, where llama.cpp's silent substitution made
    every turn work under the wrong name.

    But a probe is only trusted when it MAPS TO SOMETHING WE SHIP: an MLX server's
    /v1/models enumerates the whole HuggingFace cache, so `data[0]` is routinely an
    unrelated repo id (the same trap bridge/core/modelid.py::_reconcile_live guards).
    Anything we cannot find in the registry's own wire set is discarded and the caller
    falls back to the pin — never trust an unmappable probe.
    """
    p = str(probed or "").strip()
    if not p:
        return ""
    return p if p in set(registry_wire_models(registry)) else ""


def pin_wire() -> str:
    """The wire identifier for motdeck.yaml's PINNED model — INTENT, not reality.

    The registry id for llama.cpp (launched with --alias <id>), the model's local PATH
    for MLX (mlx_lm/mlx_vlm treat the request's `model` field as a model to LOAD and
    would resolve our id on HuggingFace → 404 → runner 400).

    Read straight from motdeck.yaml + data/models.json (no yaml/pyyaml dependency —
    this runs inside the ODYSSEUS venv), so every call site (start_component.sh,
    install_component.sh, firstrun_fat.sh, diagnose_odysseus.sh) gets it for free."""
    mid = _active_model_id()
    if not mid:
        return ""
    entry = next((x for x in _registry() if x.get("id") == mid), None)
    if entry and str(entry.get("format") or "gguf").strip().lower() == "mlx":
        return str(entry.get("path") or "").strip() or mid
    return mid


def resolve_wire() -> tuple:
    """(wire, source) — LIVE-FIRST, pin last. source ∈ {env, live, pin, none}.

      1. MOT_DECK_WIRE_MODEL — the explicit caller's answer (the auto-rebind trigger in
         bridge/routers/models.py::_do_switch passes the model it just loaded). This
         seam existed from the start and had ZERO CALLERS until S28.
      2. the runner's own authenticated /v1/models, reconciled against our registry.
      3. motdeck.yaml's pin — intent, correct whenever it has not drifted.
    """
    env = os.environ.get("MOT_DECK_WIRE_MODEL", "").strip()
    if env:
        return env, "env"
    lw = live_wire(_discover_model(BASE_URL), _registry())
    if lw:
        return lw, "live"
    pin = pin_wire()
    return (pin, "pin") if pin else ("", "none")


def _wire_model() -> str:
    """Back-compat alias: just the identifier from resolve_wire(). Empty string ⇒ the
    caller falls back to probing the live endpoint."""
    return resolve_wire()[0]


def offerable(wire: str, source: str, registry) -> bool:
    """PURE: may this identifier go into Odysseus's picker (and be the default)?

    THE DANGLES RULE, applied to the SEED rather than to the honour-check. A wire that
    is in our registry is always offerable; one that is not is offerable only when we
    have OBSERVED it (env override / a live probe). A PIN that names neither a
    registered nor a served model is a GHOST — the audit's word — and force-inserting it
    is how a deleted model kept appearing in a third-party picker for a week.
    """
    if not wire:
        return False
    return source in ("env", "live") or wire in set(registry_wire_models(registry))


def _active_model_id() -> str:
    """The registry id named by motdeck.yaml `runner: model:` (no yaml dependency)."""
    try:
        txt = open(os.path.join(MOT_DECK_ROOT, "motdeck.yaml")).read()
    except OSError:
        return ""
    m = re.search(r"^runner:\s*$(.*?)(?=^\S|\Z)", txt, re.S | re.M)
    if not m:
        return ""
    mm = re.search(r"^\s+model:\s*(.*)$", m.group(1), re.M)
    return re.sub(r"#.*$", "", mm.group(1)).strip().strip("'\"") if mm else ""


def _registry() -> list:
    try:
        return json.load(open(os.path.join(MOT_DECK_ROOT, "data", "models.json"))).get("models", [])
    except Exception:
        return []


def _discover_model(base_url: str) -> str:
    """Ask the live endpoint for its first model id. Empty string if unreachable —
    Odysseus then auto-discovers at runtime (model_refresh_mode='auto').
    ⚠️ LAST RESORT ONLY: an MLX runner's /v1/models enumerates the whole HuggingFace
    CACHE (unrelated repos), so data[0] can be junk — prefer _wire_model()."""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/models")
        if API_KEY:
            req.add_header("Authorization", f"Bearer {API_KEY}")
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.load(r).get("data") or []
            return data[0]["id"] if data else ""
    except Exception:
        return ""


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
        os.replace(tmp, STATE_PATH)
    except OSError as e:      # a marker we cannot write only costs us caution, never data
        print(f"[seed] WARN: could not record the seed marker at {STATE_PATH}: {e}")


_JSON_COLS = ("cached_models", "pinned_models")


def main() -> int:
    # Invoked by absolute path, so the script's dir (not cwd) is on sys.path by default.
    # Odysseus modules (core.*, src.*) live in cwd (= vendor/odysseus) — put it first.
    sys.path.insert(0, os.getcwd())
    try:
        from core.database import get_db_session, ModelEndpoint
        from src.settings import load_settings, save_settings
    except Exception as e:
        print(f"[seed] ERROR: cannot import Odysseus modules (run with venv active, cwd=vendor/odysseus): {e}")
        return 1

    # LIVE FIRST, PIN LAST (S28) — see resolve_wire(). The old line here read the pin
    # and only fell back to a probe, which is exactly backwards and is the bug the
    # post-switch audit traced.
    reg = _registry()
    wire, source = resolve_wire()
    ghost = bool(wire) and not offerable(wire, source, reg)
    if ghost:
        # A pin that names neither a registered nor a served model. It is NOT written
        # into the picker and NOT proposed as the default; motdeck.yaml is left exactly
        # as it is (the pin is a legitimate intent record — v1.5.57's ruling), and the
        # honest line below is the only thing this script does about it.
        wire = ""
    # …and the WHOLE registry behind it, so Odysseus's own picker is populated in
    # isolation — with the runner down, with a fresh DB, with no probe.
    models = registry_wire_models(reg, wire)
    if wire and wire not in models:            # probed-not-registered: still offer it
        models.insert(0, wire)

    state = _load_state()
    marker = state.get(ENDPOINT_ID) or {}
    want = {"name": NAME, "base_url": BASE_URL, "api_key": API_KEY, "models": models}

    with get_db_session() as db:
        # Match by the STABLE id, not base_url: when the runner endpoint changes
        # (e.g. :1337 -> :6767) we must UPDATE the existing row, not insert a
        # duplicate id (that collides on the PK and silently rolls back).
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ENDPOINT_ID).first()
        adopted = ""
        if ep is None:
            # …but a row the USER added for the same URL through Odysseus's own form
            # (random uuid id) must be ADOPTED, not duplicated. Odysseus dedupes by
            # base_url on create (model_routes.py:2036-2110); a second row for the same
            # address is exactly the mess that dedupe exists to prevent, and only we
            # can avoid making it here.
            want_url = BASE_URL.rstrip("/")
            ep = next((r for r in db.query(ModelEndpoint).all()
                       if str(r.base_url or "").rstrip("/") == want_url), None)
            if ep is not None:
                adopted = str(ep.id)
        row = None if ep is None else {
            "id": ep.id, "name": ep.name, "base_url": ep.base_url, "api_key": ep.api_key,
            "is_enabled": bool(ep.is_enabled), "model_type": ep.model_type,
            "endpoint_kind": ep.endpoint_kind, "model_refresh_mode": ep.model_refresh_mode,
            "supports_tools": ep.supports_tools, "owner": ep.owner,
            "cached_models": _as_list(ep.cached_models),
            "pinned_models": _as_list(ep.pinned_models),
            "hidden_models": _as_list(ep.hidden_models),
        }
        if row is not None:
            want["current_key_accepted"] = runner_key_accepted(
                row.get("base_url"), row.get("api_key"))
        changes, notes = endpoint_plan(row, marker, want)
        created = row is None
        if created:
            ep = ModelEndpoint(id=ENDPOINT_ID, name=want["name"], base_url=want["base_url"])
            db.add(ep)
        for field, value in changes.items():
            if field == "id":
                continue
            if field in _JSON_COLS:
                # NULL, never "[]" — an empty JSON list is a DELIBERATE "show nothing"
                # to Odysseus's own allow-list logic (_has_explicit_pinned_models), and
                # an empty registry must not read as a decision we never made.
                setattr(ep, field, json.dumps(value) if value else None)
            else:
                setattr(ep, field, value)
        endpoint_id = ep.id
        enabled = bool(ep.is_enabled)
        # What the picker will actually show: Odysseus's own merge, cached ∪ pinned −
        # hidden (routes/model_routes.py:_visible_models) — computed here for the
        # dangling-default check below, so we never "fix" a default that is fine.
        hidden = set(_as_list(ep.hidden_models))
        visible = [m for m in _merge(_as_list(ep.cached_models), _as_list(ep.pinned_models))
                   if m not in hidden]
        known_ids = [str(r.id) for r in db.query(ModelEndpoint).all()]

    settings = load_settings()
    s_changes, s_notes = settings_plan(settings, endpoint_id, enabled, visible, wire,
                                       known_ids, marker)
    if s_changes:
        settings.update(s_changes)
        save_settings(settings)

    # The marker records BOTH plans' writes: the endpoint fields and (S28) the global
    # default_model, so our own leftover is distinguishable from the human's pick on
    # the next run. Values we HONOURED are never recorded — that is what would make
    # them 'ours' and clobber them one Start later (see next_marker).
    state[ENDPOINT_ID] = next_marker(next_marker(marker, changes), s_changes)
    # ⚠️ AND THE OTHER HALF, WHICH THE SIGNAL NEEDS (S28, found in the live walk).
    # When we HONOUR a default we have decided, deliberately and for ever, not to
    # change it. /api/deps was then deriving "Odysseus is still wired to X — restart it
    # to rebind" for exactly that value: a sentence whose action CANNOT work, because
    # the restart re-runs this script, which honours it again. A banner offering a
    # button that provably does nothing is the S20 dead-button defect.
    # So the honoured value is recorded too, under its own key, and the deps reader
    # makes NO CLAIM about a binding equal to it. Nothing lies either way: Odysseus's
    # own requested→actual label still names the model that answered.
    _cur_default = str(settings.get("default_model") or "").strip()
    if _cur_default and "default_model" not in s_changes:
        state[ENDPOINT_ID]["default_model_honoured"] = _cur_default
    else:
        state[ENDPOINT_ID].pop("default_model_honoured", None)
    _save_state(state)

    where = "created" if created else ("adopted YOUR" if adopted else "updated")
    fields = ", ".join(sorted(k for k in changes if k != "id")) or "nothing (already current)"
    print(f"[seed] {where} endpoint {endpoint_id} @ {BASE_URL}; wrote: {fields}")
    print(f"[seed] picker: {len(visible)} model(s) offered by this endpoint "
          f"({'pinned from our registry — visible with the runner down' if models else 'none pinned'})")
    print(f"[seed] wire model: {wire or '(none)'} (source: {source})")
    if ghost:
        print(f"[seed] motdeck.yaml pins “{pin_wire()}”, which is neither in the model "
              f"registry nor served by the runner — NOT offered in Odysseus's picker "
              f"and not proposed as its default (the pin itself is left alone)")
    if not wire:
        print("[seed] no usable active model (pin dangling or absent, runner not "
              "reachable) — Odysseus will auto-discover when it comes up")
    for n in notes + s_notes:
        print(f"[seed] {n}")
    return 0


def _merge(*lists) -> list:
    out = []
    for lst in lists:
        for x in lst:
            if x not in out:
                out.append(x)
    return out


if __name__ == "__main__":
    sys.exit(main())
