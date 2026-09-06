"""ROUTER — the Help surface's content: docs/USER-EXPLAINERS.md, served as text.

WHY A ROUTE AND NOT A BAKED PAGE. The brief's requirement was that updating the help
text costs ZERO code. Baking the markdown into index.html at ship time would have
meant a build step, a generated blob inside a hand-edited file, and a second copy of
the prose that can disagree with the first. Serving the file the writers already edit
means the whole content pipeline is: edit docs/USER-EXPLAINERS.md, ./scripts/ship.sh,
⌘R. Nothing is generated and there is exactly one copy.

WHAT IS SERVED. The RAW markdown, not HTML. The rendering lives in the panel (a ~90
line renderer for the subset this file actually uses — h1/h2/h3, blockquote, hr, GFM
pipe tables, `-` and `1.` lists with two-space continuations, and the three inline
forms **bold** / *italic* / `code`). That split is deliberate: the panel needs the
document's SECTION STRUCTURE for its table of contents and its filter, which a slab
of pre-rendered HTML would have made it re-parse anyway.

⚠️ THE FILE HAS TO REACH THE SNAPSHOT. The fat app runs from ~/Library/Application
Support/MOT Deck, and until this slice ship.sh copied bridge/, scripts/, guards/ and
policies/ — not docs/. It now copies the top-level docs/*.md, and this route's 404
branch names that as the fix rather than leaving the view blank, because "help is
empty" with no explanation is precisely the class of dead end the Help surface exists
to stop.
"""
from __future__ import annotations

from fastapi.responses import JSONResponse, PlainTextResponse
from ..core.appctx import ROOT, app

# The one place the path is written down. `docs/` is repo-relative in a checkout and
# snapshot-relative in the app — ROOT means the same thing to both.
HELP_DOC = "USER-EXPLAINERS.md"


@app.get("/api/help/explainers")
def api_help_explainers():
    """The help text, verbatim, as text/markdown.

    no-store for the same reason the panel itself is no-store: a WKWebView that
    heuristically cached this would keep serving yesterday's help after a ship, and
    the user's only symptom would be a document that quietly does not match the app.
    """
    p = ROOT / "docs" / HELP_DOC
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JSONResponse(
            {"ok": False,
             "error": f"docs/{HELP_DOC} is not in this install — run ./scripts/ship.sh "
                      f"to copy it into the snapshot."},
            status_code=404)
    except OSError as e:                                     # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"could not read docs/{HELP_DOC}: {e}"},
                            status_code=500)
    return PlainTextResponse(
        text, media_type="text/markdown; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})
