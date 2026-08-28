"""ROUTER — the panel itself at /."""
from __future__ import annotations

from fastapi.responses import FileResponse
from ..core.appctx import PANEL, app


@app.get("/")
def panel() -> FileResponse:
    # no-store: the panel HTML must never be cached by the WKWebView, else code
    # edits silently don't appear after a relaunch (heuristic caching served a
    # stale index.html — the cause of "changes didn't show" during iteration).
    return FileResponse(
        PANEL / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )
