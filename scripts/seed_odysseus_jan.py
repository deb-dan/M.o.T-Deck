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
import sys
import urllib.request

BASE_URL = os.environ.get("JAN_BASE_URL", "http://127.0.0.1:1337/v1")
NAME = "Jan (local)"
ENDPOINT_ID = "local-jan"          # stable caller-supplied String PK (idempotent)


def _discover_model(base_url: str) -> str:
    """Ask the live endpoint for its first model id. Empty string if unreachable —
    Odysseus then auto-discovers at runtime (model_refresh_mode='auto')."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=4) as r:
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

    model = _discover_model(BASE_URL)
    model_json = json.dumps([model]) if model else None

    with get_db_session() as db:
        ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url == BASE_URL).first()
        created = ep is None
        if created:
            ep = ModelEndpoint(id=ENDPOINT_ID, name=NAME, base_url=BASE_URL)
            db.add(ep)
        # Mirror routes/cookbook_routes.py local self-hosted endpoint construction.
        ep.name = NAME
        ep.base_url = BASE_URL
        ep.api_key = None
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
