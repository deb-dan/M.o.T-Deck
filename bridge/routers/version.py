"""ROUTER — /api/version and the update check."""
from __future__ import annotations

import asyncio
from fastapi.responses import JSONResponse
from ..core.appctx import app
from ..core.procs import cfg


# --- Version / update notice (PART 4) -------------------------------------------
# NOTICE ONLY: shows the local harness version + component pins, and best-effort
# checks GitHub for a newer new-harness release. NO auto-download / auto-apply /
# git ops — updates happen via the CLAUDE.md pin+bump discipline only.
#
# HONESTY NOTE: github.com/Debkbas/new-harness is a PRIVATE repo, so the
# unauthenticated GitHub API call below will almost always 404. We deliberately do
# NOT bundle or require any token. In practice `update.available` will be false /
# "unavailable" — that's expected. The tile's real job is to SHOW the version.
# It only surfaces an "Update available" line if the repo is ever made public and
# a release tag newer than the local version exists.

def _assemble_update(local_version, gh_result):
    """Pure helper (unit-testable, no network): build the `update` dict.

    gh_result is either a dict parsed from the GitHub releases/latest response,
    or None (404 / timeout / error / no network)."""
    if not gh_result or not gh_result.get("tag_name"):
        return {"available": False, "latest": None, "note": "unavailable"}
    latest = str(gh_result.get("tag_name") or "")
    url = gh_result.get("html_url") or ""
    local_norm = str(local_version or "").lstrip("vV")
    latest_norm = latest.lstrip("vV")
    # Simple, conservative comparison: "available" only when the tags differ AND
    # the latest sorts after the local one (tuple-compare numeric dotted parts;
    # fall back to a plain string inequality if either isn't cleanly numeric).
    def _parts(s):
        try:
            return tuple(int(x) for x in s.split(".") if x != "")
        except Exception:
            return None
    lp, rp = _parts(local_norm), _parts(latest_norm)
    if lp is not None and rp is not None:
        available = rp > lp
    else:
        available = latest_norm != local_norm
    return {"available": available, "latest": latest, "url": url}


def _fetch_latest_release():
    """Best-effort, blocking (run via asyncio.to_thread). Returns the parsed JSON
    dict on success, or None on any 404 / timeout / error / no network."""
    try:
        from urllib.request import Request, urlopen
        import json as _json
        req = Request(
            "https://api.github.com/repos/Debkbas/new-harness/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "harness-bridge"},
        )
        with urlopen(req, timeout=3) as resp:   # NO auth by design (private repo → 404)
            return _json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None


@app.get("/api/version")
async def api_version() -> JSONResponse:
    """Local versions instantly + a best-effort update check. Never raises."""
    out = {"harness": None, "hermes": None, "odysseus": None,
           "searxng": None, "update": {"available": False, "latest": None, "note": "unavailable"}}
    local_version = None
    try:
        c = cfg()
        local_version = c.get("version")
        comps = c.get("components", {}) or {}
        out["harness"] = local_version
        out["hermes"] = (comps.get("hermes") or {}).get("pin")
        out["odysseus"] = (comps.get("odysseus") or {}).get("pin")
        out["searxng"] = (comps.get("searxng") or {}).get("pin")
    except Exception:
        pass  # still return whatever we have; the version check must never crash
    try:
        gh = await asyncio.to_thread(_fetch_latest_release)   # off the event loop, 3s cap
        out["update"] = _assemble_update(local_version, gh)
    except Exception:
        pass  # keep the default "unavailable" update dict
    return JSONResponse(out)
