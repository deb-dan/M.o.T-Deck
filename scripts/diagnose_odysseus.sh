#!/usr/bin/env bash
# One-shot Odysseus connect diagnostic: runs the seed with FULL output (no swallowing),
# then dumps the model_endpoints table, the default-model settings, and the DB path the
# app actually uses — so we can see exactly why Jan isn't appearing.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[[ -d data/odysseus-venv ]] || { echo "odysseus venv missing"; exit 1; }
# shellcheck disable=SC1091
source data/odysseus-venv/bin/activate

echo "===== 1. run seed (full output / traceback if any) ====="
( cd vendor/odysseus && python "$ROOT/scripts/seed_odysseus_jan.py" ); echo "seed exit=$?"

echo "===== 2. inspect DB + settings (what the app reads) ====="
( cd vendor/odysseus && python - <<'PY'
try:
    import core.database as d
    from core.database import get_db_session, ModelEndpoint
    print("DB URL:", getattr(d, "DATABASE_URL", "?"))
    with get_db_session() as db:
        rows = db.query(ModelEndpoint).all()
        print(f"model_endpoints rows: {len(rows)}")
        for e in rows:
            print(f"  id={e.id} name={e.name!r} url={e.base_url} enabled={e.is_enabled} "
                  f"owner={e.owner} kind={e.endpoint_kind} tools={e.supports_tools} "
                  f"cached={e.cached_models} pinned={e.pinned_models}")
except Exception as ex:
    import traceback; traceback.print_exc()
try:
    from src.settings import load_settings
    s = load_settings()
    print("default_endpoint_id:", s.get("default_endpoint_id"))
    print("default_model:", s.get("default_model"))
    print("share_defaults_with_users:", s.get("share_defaults_with_users"))
except Exception as ex:
    import traceback; traceback.print_exc()
PY
)

echo "===== 3. is Jan reachable right now? ====="
curl -s -m 4 http://127.0.0.1:1337/v1/models | head -c 300; echo
