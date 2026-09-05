"""Transactional explicit registry Rescan and legacy-missing confirmation."""
from __future__ import annotations

import json
import os
import subprocess
import asyncio

from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, app
from ..core.health import file_state_forget
from ..core.modelid import _live_model_id
from ..core.procs import cfg
from .models import _rescan_fanout


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
    env = dict(os.environ, HARNESS_PROTECT_MODELS="\n".join(_protect_ids()))
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
            result["apps"] = await asyncio.to_thread(_rescan_fanout)
        except Exception as exc:
            result["apps"] = f"catalog refresh failed: {str(exc)[:120]}"
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)[:300]}, status_code=500)
