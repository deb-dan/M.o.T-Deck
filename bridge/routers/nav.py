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
    model = _nav.read(ROOT)
    # `strip` is DERIVED here, not in the shell, and that is the point: the 9+3 rule
    # (nine stable pins, then the three-slot most-recently-opened window) has exactly
    # ONE implementation. An older shell that reads only `nav.topbar` still draws the
    # nine pins — fewer tabs than it should, never wrong ones.
    return JSONResponse({"ok": True, "nav": model, "gen": nav_gen(),
                         "strip": _nav.strip(model),
                         "max_topbar": _nav.NAV_TOPBAR_MAX,
                         "max_pins": _nav.NAV_TOPBAR_PINS,
                         "max_mru": _nav.NAV_TOPBAR_MRU,
                         "ids": list(_nav.NAV_IDS)})


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


@app.post("/api/nav/mru")
async def api_nav_mru(req: Request) -> JSONResponse:
    """Open a tab that is not on the strip: it takes the first of the three swappable
    slots and the oldest of them falls off into ⋯ (Debi's ruling 2026-08-29).

    A SEPARATE ROUTE FROM `POST /api/nav`, deliberately. That one is a SAVE — the user
    arranging their window in the Appearance editor, strict, refused with a reason when
    it would lose something. This is a USE — the shell recording that you just opened
    Goose from the ⋯ menu — and it must never be able to refuse, reorder or drop a row.
    It touches ONE list, and when the window does not move (the tab was already on the
    strip) it writes nothing and does not bump the generation, so a click on a tab that
    is already there costs one request and changes no state anywhere.
    """
    if _nav is None:
        return JSONResponse({"ok": False, "error": "nav module unavailable: " + _NAV_ERR},
                            status_code=503)
    try:
        body = await req.json()
    except Exception:                                    # noqa: BLE001
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    eid = body.get("id") if isinstance(body, dict) else None
    if not isinstance(eid, str) or not eid:
        return JSONResponse({"ok": False, "error": "no id"}, status_code=400)
    model = _nav.read(ROOT)
    if not _nav.mru_touch(model, eid):
        return JSONResponse({"ok": True, "moved": False, "nav": model,
                             "strip": _nav.strip(model), "gen": nav_gen()})
    try:
        _nav.write(ROOT, model)
    except OSError as e:
        return JSONResponse({"ok": False, "error": f"could not save: {e}"}, status_code=500)
    gen = _nav_bump()
    publish("nav", gen=gen)
    return JSONResponse({"ok": True, "moved": True, "nav": model,
                         "strip": _nav.strip(model), "gen": gen})
