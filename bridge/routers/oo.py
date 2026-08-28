"""ROUTER — LOffice's vendored ONLYOFFICE editors and the COOP/COEP asset serving."""
from __future__ import annotations

import asyncio
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from ..core.appctx import PANEL, ROOT, _OO_ERR, _office, _oo, app
from ..core.officelog import _office_log, _office_unavailable


# ══ LOFFICE TIER 2 — the vendored ONLYOFFICE editors ════════════════════════════
#
# Still not a component: `scripts/install_onlyoffice.sh` unzips two sha256-pinned
# CryptPad release zips into data/onlyoffice/ and this serves them read-only. No
# port, no daemon, no manifest key. bridge/oo.py owns every decision; these four
# routes are wiring.
#
# ⚠️ EVERY response below carries oo.ISOLATION_HEADERS. Without cross-origin
# isolation the spreadsheet editor hangs at "Loading spreadsheet" forever with zero
# console errors — measured in a real WKWebView on 2026-08-27. That includes the
# GLUE PAGE itself: a COEP document is the only kind that may embed the COEP editor
# frame, and `crossOriginIsolated` is a property of the whole page tree.

def _oo_unavailable() -> JSONResponse:
    return JSONResponse(
        {"ok": False, "installed": False,
         "reason": f"the rich-editor module failed to load: {_OO_ERR}",
         "installer": "scripts/install_onlyoffice.sh"},
        status_code=503, headers=dict(_OO_FALLBACK_HEADERS))


# Used only when oo.py itself did not import; the literal is duplicated ONCE, here,
# so a broken oo.py cannot serve a page without the headers that make it work.
_OO_FALLBACK_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _oo_headers(extra: dict | None = None) -> dict:
    h = dict(_oo.ISOLATION_HEADERS if _oo is not None else _OO_FALLBACK_HEADERS)
    if extra:
        h.update(extra)
    return h


@app.get("/api/oo/status")
def oo_status() -> JSONResponse:
    """Is the rich editor installed, at which pins, and how do I install it?

    The page and the LOffice button BOTH branch on this, which is why "not
    installed" always carries a reason and the installer path: the button must never
    be a dead click.
    """
    if _oo is None:
        return _oo_unavailable()
    body = _oo.install_state(ROOT)
    return JSONResponse({"ok": True, **body},
                        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE}))


@app.get("/oo-edit")
def oo_edit_page() -> Response:
    """The glue page — OUR integration, at /oo-edit?doc=<name>[&embed=1].

    ⚠️ THE OLD DOCSTRING HERE ARGUED FOR A NAVIGATION AND AGAINST AN IFRAME, AND
    DEBI'S 2026-08-27 ONE-EDITOR RULING REVERSED IT. Its second (deciding) reason was
    that embedding "would force the LOffice page ITSELF to carry COEP, and that page
    loads /assets/*". That premise was already stale when it was written: the Univer
    tier had been retired in the same wave, so office.html loads no subresource at
    all. See the audit in office_page() above — COEP on /office costs nothing.

    So this page is now BOTH:
      · `?embed=1` — the editing surface inside LOffice's centre column. Its own
        header/footer are hidden and the LOffice chrome around it does that job.
      · no `embed` — the standalone page, unchanged, kept as the rollback and as the
        way to open the editor on its own when something about the embed goes wrong.
    Parent and child are same-origin, so the contract between them is direct property
    access (window.LOfficeHost / window.LOfficeEmbed) rather than postMessage — the
    whole of it is documented at the top of bridge/panel/oo.html.
    """
    if _oo is None:
        return _oo_unavailable()
    return FileResponse(
        PANEL / "oo.html",
        headers=_oo_headers({"Cache-Control": _oo.NO_CACHE, "Pragma": "no-cache"}))


@app.get("/oo/{rel:path}")
def oo_asset(rel: str, request: Request) -> Response:
    """The bundle, read-only. Containment + forced MIME + immutable cache + brotli.

    Deliberately NOT a StaticFiles mount: a mount cannot add per-response headers
    without a middleware wrapper (the /assets precedent), and three of the four
    things this route does are per-response.
    """
    if _oo is None:
        return _oo_unavailable()
    target, reason = _oo.bundle_target(ROOT, rel)
    if not target:
        # 404 for everything, including a refused traversal. Telling a caller which
        # of its guesses was "outside the bundle" is free reconnaissance.
        return JSONResponse({"ok": False, "error": reason}, status_code=404,
                            headers=_oo_headers())
    headers = _oo_headers({"Cache-Control": _oo.cache_control_for(rel)})
    media = _oo.media_type_for(target)
    # A Range request must never be answered with the .br sibling: FileResponse would
    # slice the COMPRESSED bytes and still claim Content-Encoding: br, which is a
    # corrupt response rather than a slow one. Ranges get the plain file.
    br = ("" if request.headers.get("range")
          else _oo.brotli_sibling(target, request.headers.get("accept-encoding", "")))
    if br:
        # The `.br` sibling shipped inside the zip. Content-Type stays that of the
        # UNCOMPRESSED file — brotli is a transfer encoding, not a format.
        headers["Content-Encoding"] = "br"
        headers["Vary"] = "Accept-Encoding"
        return FileResponse(br, media_type=media, headers=headers)
    return FileResponse(target, media_type=media, headers=headers)


@app.post("/api/office/writeback/{name}")
async def office_writeback(name: str, req: Request) -> JSONResponse:
    """RAW .xlsx body → OVERWRITE that workbook. This is Save, not import.

    `?mtime=<float>` is the fence: the mtime the editor saw when it opened. A
    workbook that changed underneath gets a 409 and no write, unless `?force=1`.
    A daily .bak is taken first and the write is temp-file + os.replace — see
    oo.writeback, which owns all of that.
    """
    if _oo is None:
        return _oo_unavailable()
    if _office is None:
        return _office_unavailable()
    raw = await req.body()
    q = req.query_params
    mtime = q.get("mtime")
    force = q.get("force") in ("1", "true", "yes")
    report, err = await asyncio.to_thread(
        _oo.writeback, _office, ROOT, name, raw,
        mtime if mtime not in (None, "") else None, force)
    if report is None:
        status, reason = err
        _office_log(f"oo-writeback reject {name!r}: {status} {reason}")
        return JSONResponse({"ok": False, "error": reason}, status_code=status,
                            headers=_oo_headers())
    _office_log(f"oo-writeback saved {report['name']} ({report['bytes']} bytes"
                + (f", .bak {report['backup']}" if report["backup"] else "")
                + (", FORCED" if report["forced"] else "") + ")")
    return JSONResponse({"ok": True, **report}, headers=_oo_headers())
