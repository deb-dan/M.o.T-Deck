"""ROUTER — /api/version and the update check."""
from __future__ import annotations

import asyncio
from fastapi.responses import JSONResponse
from ..core.appctx import app
from ..core.procs import VERSION_UNKNOWN_NOTE, cfg, motdeck_version


# --- Version / update notice (PART 4) -------------------------------------------
# NOTICE ONLY: shows the local motdeck version + component pins, and best-effort
# checks GitHub for a newer mot-deck release. NO auto-download / auto-apply /
# git ops — updates happen via the CLAUDE.md pin+bump discipline only.
#
# HONESTY NOTE: github.com/Debkbas/mot-deck is a PRIVATE repo, so the
# unauthenticated GitHub API call below will almost always 404. We deliberately do
# NOT bundle or require any token. In practice `update.available` will be false /
# "unavailable" — that's expected. The tile's real job is to SHOW the version.
# It only surfaces an "Update available" line if the repo is ever made public and
# a release tag newer than the local version exists.

def _assemble_update(local_version, gh_result):
    """Pure helper (unit-testable, no network): build the `update` dict.

    gh_result is either a dict parsed from the GitHub releases/latest response,
    or None (404 / timeout / error / no network).

    ⚠️ U56 REWROTE THE COMPARISON, AND THE OLD ONE HAD TWO WAYS TO LIE.
      1. It was fed `motdeck.yaml version:` = 0.1.0, frozen for 72 releases, so ANY
         tag on the repo compared as newer FOR EVER. That half is fixed at the source
         (the caller now passes the VERSION file), but the local version can still be
         genuinely UNKNOWN on a pre-v1.5.70 install — and comparing against an unknown
         is guessing. An unknown local version now yields "no local version to compare
         against", never an update banner.
      2. `_parts` returned None for anything not cleanly numeric ("v1.5.72-beta",
         "2026.09.01-rc1") and the fallback was `latest != local`, i.e. ANY unparseable
         tag became "update available" — a false positive by construction. Unparseable
         now means UNCOMPARABLE and says so."""
    if not gh_result or not gh_result.get("tag_name"):
        return {"available": False, "latest": None, "note": "unavailable"}
    latest = str(gh_result.get("tag_name") or "")
    url = gh_result.get("html_url") or ""
    local_norm = str(local_version or "").strip().lstrip("vV")
    latest_norm = latest.strip().lstrip("vV")
    if not local_norm:
        return {"available": False, "latest": latest, "url": url,
                "note": "no local version to compare against"}

    def _parts(s):
        """Leading dotted-numeric parts, or None when there is nothing comparable."""
        out = []
        for chunk in s.split("."):
            digits = ""
            for ch in chunk:
                if not ch.isdigit():
                    break
                digits += ch
            if digits == "":
                break
            out.append(int(digits))
            if digits != chunk:      # "72-beta" → take 72, then stop
                break
        return tuple(out) or None

    lp, rp = _parts(local_norm), _parts(latest_norm)
    if lp is None or rp is None:
        return {"available": False, "latest": latest, "url": url,
                "note": f"cannot compare “{latest}” with “{local_norm}”"}
    # Zero-pad so 1.5 vs 1.5.72 compares on equal footing rather than by tuple length.
    n = max(len(lp), len(rp))
    lp = lp + (0,) * (n - len(lp))
    rp = rp + (0,) * (n - len(rp))
    return {"available": rp > lp, "latest": latest, "url": url}


def _fetch_latest_release():
    """Best-effort, blocking (run via asyncio.to_thread). Returns the parsed JSON
    dict on success, or None on any 404 / timeout / error / no network."""
    try:
        from urllib.request import Request, urlopen
        import json as _json
        req = Request(
            "https://api.github.com/repos/Debkbas/mot-deck/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "motdeck-bridge"},
        )
        with urlopen(req, timeout=3) as resp:   # NO auth by design (private repo → 404)
            return _json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None


@app.get("/api/version")
async def api_version() -> JSONResponse:
    """Local versions instantly + a best-effort update check. Never raises."""
    out = {"motdeck": None, "hermes": None, "odysseus": None,
           "searxng": None, "update": {"available": False, "latest": None, "note": "unavailable"}}
    # ⛔ THE VERSION COMES FROM ROOT/VERSION AND FROM NOWHERE ELSE (U56). It used to be
    # `cfg().get("version")` — motdeck.yaml's dead 0.1.0 — which is why the tile read
    # 0.1.0 at release 1.5.72. See core/procs.motdeck_version for the whole story.
    local_version = motdeck_version()
    out["motdeck"] = local_version or "unknown"
    if not local_version:
        out["motdeck_note"] = VERSION_UNKNOWN_NOTE
    try:
        c = cfg()
        comps = c.get("components", {}) or {}
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
