"""CORE — the office lane's logger and its module-absent reply.

_office_log is called from three places that cannot share a router: the /assets
StaticFiles subclass in app.py (the LOffice asset trace), the office router and the oo
router. _office_unavailable travels with it.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse
from .appctx import _OFFICE_ERR


# ⚠️ MOVED HERE from app.py:9460-9467 by the router/core split (2026-08-28).
#    _office_log is used by the /assets StaticFiles subclass in app.py, by the
#    office router and by the oo router; _office_unavailable travels with it.
#    Leaving them in the office router made office and oo mutually dependent.

def _office_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": f"the office module failed to load: {_OFFICE_ERR}"},
        status_code=503)


def _office_log(msg: str) -> None:
    print(f"[office] {msg}", flush=True)
