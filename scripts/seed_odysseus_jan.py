#!/usr/bin/env python3
# seed_odysseus_jan.py — idempotent Odysseus DB seed: wire it to the local Jan endpoint.
#
# Invoked by the harness (install_component.sh / start_component.sh) with the
# odysseus venv active and cwd = vendor/odysseus, after setup.py has created the DB:
#   ( cd vendor/odysseus && python <harness>/scripts/seed_odysseus_jan.py )
#
# This is the "connect" half of one-switch provisioning for Odysseus: it upserts a
# single model endpoint pointing at Jan and makes it the default chat model, so a
# fresh login can chat with zero UI configuration. Safe to run repeatedly.
#
# Endpoint + model schema verified against pinned Odysseus:
#   core/database.py (ModelEndpoint), routes/cookbook_routes.py (local-endpoint mirror),
#   routes/model_routes.py + src/endpoint_resolver.py (default_endpoint_id/default_model),
#   src/settings.py (global settings JSON).

import json
import os
import re
import sys
import urllib.request

BASE_URL = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:6767/v1")
API_KEY = os.environ.get("JAN_API_KEY", "").strip() or None   # headless runner needs a key
NAME = "Local runner"   # display name in Odysseus (Jan is gone; id stays local-jan for fan-out)
ENDPOINT_ID = "local-jan"          # stable caller-supplied String PK (idempotent)
# The harness root — this script is invoked by absolute path with cwd=vendor/odysseus.
HARNESS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _wire_model() -> str:
    """The identifier Odysseus must SEND to the runner for the active model — the
    same rule as bridge/app.py wire_model_id(): the registry id for llama.cpp
    (launched with --alias <id>), the model's local PATH for MLX (mlx_lm/mlx_vlm
    treat the request's `model` field as a model to LOAD and would resolve our id
    on HuggingFace → 404 → runner 400).

    Read straight from harness.yaml + data/models.json (no yaml/pyyaml dependency —
    this runs inside the ODYSSEUS venv), so every call site (start_component.sh,
    install_component.sh, firstrun_fat.sh, diagnose_odysseus.sh) gets it for free.
    Env override: HARNESS_WIRE_MODEL. Empty string ⇒ caller falls back to probing
    the live endpoint."""
    env = os.environ.get("HARNESS_WIRE_MODEL", "").strip()
    if env:
        return env
    try:
        txt = open(os.path.join(HARNESS_ROOT, "harness.yaml")).read()
    except OSError:
        return ""
    m = re.search(r"^runner:\s*$(.*?)(?=^\S|\Z)", txt, re.S | re.M)
    if not m:
        return ""
    mm = re.search(r"^\s+model:\s*(.*)$", m.group(1), re.M)
    mid = re.sub(r"#.*$", "", mm.group(1)).strip().strip("'\"") if mm else ""
    if not mid:
        return ""
    try:
        models = json.load(open(os.path.join(HARNESS_ROOT, "data", "models.json"))).get("models", [])
    except Exception:
        return mid
    entry = next((x for x in models if x.get("id") == mid), None)
    if entry and str(entry.get("format") or "gguf").strip().lower() == "mlx":
        return str(entry.get("path") or "").strip() or mid
    return mid


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

    # Prefer OUR wire identifier for the active model (correct for both engines);
    # only probe the live endpoint when the harness has no active model recorded.
    model = _wire_model() or _discover_model(BASE_URL)
    model_json = json.dumps([model]) if model else None

    with get_db_session() as db:
        # Match by the STABLE id, not base_url: when the runner endpoint changes
        # (e.g. :1337 -> :6767) we must UPDATE the existing row, not insert a
        # duplicate id (that collides on the PK and silently rolls back).
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.id == ENDPOINT_ID).first()
        created = ep is None
        if created:
            ep = ModelEndpoint(id=ENDPOINT_ID, name=NAME, base_url=BASE_URL)
            db.add(ep)
        # Mirror routes/cookbook_routes.py local self-hosted endpoint construction.
        ep.name = NAME
        ep.base_url = BASE_URL
        ep.api_key = API_KEY   # runner key (headless Jan requires it); None if unset
        ep.is_enabled = True
        ep.model_type = "llm"
        ep.endpoint_kind = "local"
        ep.model_refresh_mode = "auto"     # keep model list fresh from /v1/models at runtime
        ep.supports_tools = True
        ep.owner = None                     # NULL = shared/visible to all + admin
        if model_json:                      # pre-seed so the picker needs no live probe
            ep.cached_models = model_json
            ep.pinned_models = model_json
        endpoint_id = ep.id

    settings = load_settings()
    settings["default_endpoint_id"] = endpoint_id
    if model:
        settings["default_model"] = model
    save_settings(settings)

    where = "created" if created else "updated"
    if model:
        print(f"[seed] {where} endpoint {endpoint_id} @ {BASE_URL}; default_model={model}")
    else:
        print(f"[seed] {where} endpoint {endpoint_id} @ {BASE_URL}; model will auto-discover "
              f"when Jan is reachable (endpoint not up at seed time)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
