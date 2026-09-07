"""Opaque, allowlisted read surface for Hermes history image thumbnails (A3)."""
from __future__ import annotations

from fastapi.responses import Response

from ..core.appctx import app
from ..core.hermesattachments import open_image


@app.get("/api/hermes/history-image/{token}")
def hermes_history_image(token: str) -> Response:
    got = open_image(token)
    if got is None:
        return Response("image unavailable", status_code=404, media_type="text/plain")
    raw, media, _name = got
    return Response(raw, media_type=media, headers={"Cache-Control": "no-store"})
