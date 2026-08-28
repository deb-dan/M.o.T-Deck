"""ROUTER — the sidebar/tab-strip customization model (see bridge/nav.py)."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import ROOT, _NAV_ERR, _nav, app
from ..core.events import publish


# ── NAV generation (FABLE-STUDIO-PHASE2-SPEC §A) ─────────────────────────────
# The SAME carrier and the SAME shape as the Hermes generation below, for the same
# reason and with the same failure mode: the Swift shell cannot read the panel's
# localStorage, so it needs to know when the layout it drew is out of date. It reads
# `nav_gen` off /api/status (a route it already polls) and re-fetches /api/nav only
# when the number moved.
#
# PROCESS-LIFETIME again, and again deliberately: a bridge restart resets it to 0,
# which the shell records silently as a DECREASE rather than treating as a change —
# and it cannot be wrong to skip a refetch there, because nav.json on disk did not
# move while the bridge was down and the shell fetches it once at launch anyway.
_NAV_GEN = 0


def _nav_bump() -> int:
    global _NAV_GEN
    _NAV_GEN += 1
    return _NAV_GEN


def nav_gen() -> int:
    return _NAV_GEN


@app.get("/api/nav")
def api_nav_get() -> JSONResponse:
    """The layout the SHELL draws its tab strip from, and the panel's shared copy."""
    if _nav is None:
        return JSONResponse({"ok": False, "error": "nav module unavailable: " + _NAV_ERR},
                            status_code=503)
    return JSONResponse({"ok": True, "nav": _nav.read(ROOT), "gen": nav_gen(),
                         "max_topbar": _nav.NAV_TOPBAR_MAX, "ids": list(_nav.NAV_IDS)})


@app.post("/api/nav")
async def api_nav_set(req: Request) -> JSONResponse:
    """Save a layout. STRICT: normalize drops what this build cannot render, then
    validate REFUSES (400, with the reason) rather than quietly repairing — a save
    that silently did something else is how a customisation loses an entry."""
    if _nav is None:
        return JSONResponse({"ok": False, "error": "nav module unavailable: " + _NAV_ERR},
                            status_code=503)
    try:
        body = await req.json()
    except Exception:                                    # noqa: BLE001
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    raw = body.get("nav") if isinstance(body, dict) else None
    if raw is None:
        raw = body
    model = _nav.normalize(raw)
    err = _nav.validate(model)
    if err:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    try:
        _nav.write(ROOT, model)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not save: {e}"}, status_code=500)
    gen = _nav_bump()
    # SSE (2026-08-28): the gen bump, pushed. The Swift shell's 5s nav_gen poll stays
    # exactly as it is — it is a different consumer with its own backstop, and a solo
    # tab (no script-message handler) still has nothing but that poll. This event is
    # for the OTHER open panels: a layout saved in one tab now redraws the sidebar in
    # the next without waiting for anybody's tick.
    publish("nav", gen=gen)
    return JSONResponse({"ok": True, "nav": model, "gen": gen})
