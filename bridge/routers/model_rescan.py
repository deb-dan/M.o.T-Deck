"""Transactional explicit registry Rescan and legacy-missing confirmation."""
from __future__ import annotations

import json
import os
import subprocess
import asyncio
import importlib.util

from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, app
from ..core.health import file_state_forget
from ..core.modelid import _live_model_id, wire_model_id
from ..core.modelreg import offerable_wire_ids
from ..core.procs import _port_alive_sync, _registry_models, cfg
from .models import _rebind_odysseus_offline, _rescan_fanout


_ODY_SEED = None


def _ody_seed_module():
    """Load the offline seeder's exact never-clobber planner, not a second copy."""
    global _ODY_SEED
    if _ODY_SEED is not None:
        return _ODY_SEED
    path = ROOT / "scripts" / "seed_odysseus_jan.py"
    spec = importlib.util.spec_from_file_location("motdeck_ody_seed_plan", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError("Odysseus seed planner could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _ODY_SEED = module
    return module


def _rescan_wire_inventory() -> tuple[list[str], str]:
    """One registry snapshot: (picker wires, actually-served-or-pinned wire)."""
    registry = _registry_models()
    rc = cfg().get("runner", {}) or {}
    live = None
    try:
        if rc.get("port"):
            live = _live_model_id(int(rc["port"]))
    except Exception:
        live = None
    model = live or str(rc.get("model") or "")
    wire = wire_model_id(model, registry) or model
    return offerable_wire_ids(registry, wire), wire


def _ody_live_catalog_plan(rows, wanted, marker, runner_base) -> dict:
    """Plan only the managed row's picker update through the seeder's exact rules.

    The stable primary key proves ownership. A matching runner URL proves the row still
    serves this app. The seeder's marker then distinguishes our prior list from a list
    curated by the user. No one of those facts alone grants write authority.
    """
    if not wanted:
        return {"action": "refuse", "reason": "the registry offered no models"}
    rows = rows if isinstance(rows, list) else []
    row = next((r for r in rows if isinstance(r, dict)
                and str(r.get("id") or "") == "local-jan"), None)
    if row is None:
        return {"action": "refuse", "reason": "the managed local endpoint is absent"}
    have_base = str(row.get("base_url") or "").strip().rstrip("/")
    want_base = str(runner_base or "").strip().rstrip("/")
    if not want_base or have_base != want_base:
        return {"action": "honour", "reason": "the managed row was repointed by the user"}
    if row.get("is_enabled") is False:
        return {"action": "honour", "reason": "the managed endpoint is disabled"}
    seed = _ody_seed_module()
    want = {
        "name": str(row.get("name") or seed.NAME),
        "base_url": have_base,
        "api_key": row.get("api_key"),
        "models": list(wanted),
    }
    changes, notes = seed.endpoint_plan(row, marker or {}, want)
    if "pinned_models" in changes:
        return {"action": "patch", "id": "local-jan",
                "pinned_models": list(changes["pinned_models"])}
    current = seed._as_list(row.get("pinned_models"))
    if current == list(wanted):
        return {"action": "current", "reason": "picker already current"}
    reason = next((n for n in notes if n.startswith("pinned_models:")), "")
    return {"action": "honour",
            "reason": reason or "the current picker list is not proven app-owned"}


async def _rebind_odysseus_after_rescan() -> str:
    """Refresh the live picker via Odysseus, or use the existing offline seeder.

    This updates no model file and creates no second registry. A user-curated list, a
    disabled endpoint, a repointed endpoint, an empty inventory, or an unverified write
    is preserved and named.
    """
    if not (ROOT / "vendor" / "odysseus").is_dir():
        return ""
    wanted, wire = _rescan_wire_inventory()
    if not wanted:
        return "Odysseus: registry offered no models — picker left unchanged"
    try:
        port = int(((cfg().get("components") or {}).get("odysseus") or {}).get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not port or not await asyncio.to_thread(_port_alive_sync, port):
        note = await asyncio.to_thread(_rebind_odysseus_offline, wire)
        return f"Odysseus: {note}" if note else \
            f"Odysseus: picker rebuilt offline ({len(wanted)} models)"

    from .ody import _ody_req
    seed = _ody_seed_module()
    state = seed._load_state()
    marker = state.get(seed.ENDPOINT_ID) or {}
    rc = cfg().get("runner", {}) or {}
    runner_base = str(rc.get("endpoint") or "http://127.0.0.1:6767/v1")
    try:
        listing = await _ody_req("GET", "/api/model-endpoints")
        rows = listing.json() if listing.status_code == 200 else []
    except Exception as exc:
        return f"Odysseus: live picker refresh unavailable ({str(exc)[:100]})"
    plan = _ody_live_catalog_plan(rows, wanted, marker, runner_base)
    if plan["action"] == "current":
        return f"Odysseus: picker already current ({len(wanted)} models)"
    if plan["action"] != "patch":
        return f"Odysseus: {plan['reason']} — picker left unchanged"
    try:
        result = await _ody_req(
            "PATCH", f"/api/model-endpoints/{plan['id']}/models",
            json={"pinned_models": plan["pinned_models"]})
        body = result.json() if result.status_code == 200 else {}
        if (result.status_code != 200 or not isinstance(body, dict)
                or body.get("id") != plan["id"]
                or body.get("pinned_count") != len(plan["pinned_models"])):
            return ("Odysseus: the live picker update was not acknowledged exactly "
                    "— marker left unchanged")
        verify = await _ody_req("GET", "/api/model-endpoints")
        verify_rows = verify.json() if verify.status_code == 200 else []
        exact = next((r for r in verify_rows if isinstance(r, dict)
                      and str(r.get("id") or "") == plan["id"]), None)
        if exact is None or seed._as_list(exact.get("pinned_models")) != plan["pinned_models"]:
            return ("Odysseus: the live picker read-back did not match — marker left "
                    "unchanged")
        state[seed.ENDPOINT_ID] = seed.next_marker(
            marker, {"pinned_models": plan["pinned_models"]})
        seed._save_state(state)
        recorded = seed._load_state().get(seed.ENDPOINT_ID) or {}
        if seed._as_list(recorded.get("pinned_models")) != plan["pinned_models"]:
            return ("Odysseus: picker updated, but ownership evidence could not be "
                    "recorded; future rescans will fail closed")
        return f"Odysseus: live picker refreshed ({len(plan['pinned_models'])} models)"
    except Exception as exc:
        return f"Odysseus: live picker refresh failed ({str(exc)[:100]})"


def _protect_ids():
    runner = cfg().get("runner", {}) or {}
    ids = [str(runner.get("model") or "")]
    try:
        port = runner.get("port")
        ids.append(str(_live_model_id(int(port)) or "") if port else "")
    except Exception:
        pass
    return [x for x in ids if x]


async def _rescan_body(request):
    try:
        raw = await request.body()
    except Exception:
        return "", JSONResponse({"ok": False, "error": "invalid rescan confirmation"}, status_code=400)
    if not raw:
        return "", None
    try:
        body = json.loads(raw)
    except (TypeError, ValueError):
        body = None
    if (not isinstance(body, dict) or set(body) != {"confirm_missing", "token"}
            or body.get("confirm_missing") is not True):
        return "", JSONResponse({"ok": False, "error": "invalid rescan confirmation"}, status_code=400)
    token = body.get("token")
    if (not isinstance(token, str) or len(token) != 64
            or any(ch not in "0123456789abcdef" for ch in token.lower())):
        return "", JSONResponse({"ok": False, "error": "invalid rescan confirmation"}, status_code=400)
    return token.lower(), None


def _success_result(result):
    """The script protocol is a transaction boundary, not a best-effort hint."""
    return (isinstance(result, dict) and result.get("ok") is True
            and isinstance(result.get("count"), int) and not isinstance(result["count"], bool)
            and isinstance(result.get("pruned"), list) and all(isinstance(x, str) for x in result["pruned"])
            and isinstance(result.get("flagged"), list) and all(isinstance(x, str) for x in result["flagged"])
            and isinstance(result.get("manager_removed", []), list)
            and all(isinstance(x, str) for x in result.get("manager_removed", []))
            and isinstance(result.get("unlisted", []), list)
            and all(isinstance(x, str) for x in result.get("unlisted", []))
            and isinstance(result.get("source_warnings", []), list)
            and all(isinstance(x, str) for x in result.get("source_warnings", []))
            and isinstance(result.get("partial", False), bool)
            and result.get("requires_confirmation") is False
            and result.get("ambiguous_missing") == [])


def _run_seed(token):
    """Blocking protection lookup + subprocess protocol, isolated from the ASGI loop."""
    cmd = ["python3", "scripts/seed_registry.py", "--json"]
    if token:
        cmd.extend(["--confirm-missing-token", token])
    env = dict(os.environ, MOT_DECK_PROTECT_MODELS="\n".join(_protect_ids()))
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120,
                          check=False, env=env)


@app.post("/api/models/rescan")
async def api_models_rescan(request: Request):
    """Run the only evidence-writing registry transaction; preview never fans out."""
    token, refusal = await _rescan_body(request)
    if refusal:
        return refusal
    try:
        run = await asyncio.to_thread(_run_seed, token)
        try:
            result = json.loads(run.stdout or "{}")
        except (TypeError, ValueError):
            result = {}
        if run.returncode == 3:
            preview = (result.get("ok") is False and result.get("requires_confirmation") is True
                       and isinstance(result.get("ambiguous_missing"), list)
                       and result["ambiguous_missing"] == sorted(set(result["ambiguous_missing"]))
                       and all(isinstance(x, str) and x for x in result["ambiguous_missing"])
                       and isinstance(result.get("confirmation_token"), str)
                       and len(result["confirmation_token"]) == 64)
            if preview:
                return JSONResponse(result, status_code=409)
            return JSONResponse({"ok": False, "error": "invalid rescan preview"}, status_code=500)
        if run.returncode != 0 or not _success_result(result):
            error = result.get("error") or (run.stderr or run.stdout or "seed failed")[:300]
            return JSONResponse({"ok": False, "error": error},
                                status_code=409 if error == "missing-entry confirmation changed" else 500)
        file_state_forget()
        try:
            app_notes = await asyncio.to_thread(_rescan_fanout)
            ody_note = await _rebind_odysseus_after_rescan()
            result["apps"] = "; ".join(
                note for note in (app_notes, ody_note) if note)[:900]
        except Exception as exc:
            result["apps"] = f"catalog refresh failed: {str(exc)[:120]}"
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:300]}, status_code=500)
