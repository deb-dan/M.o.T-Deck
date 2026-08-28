"""bridge.routers — one module per lane, each declaring its own routes.

Every route is still written `@app.get("/api/…")` against the single FastAPI instance
in bridge.core.appctx — not an APIRouter. That is deliberate: ~78 assertions across the
suite read those decorator lines as TEXT, and an APIRouter would have rewritten all of
them and changed what the gate checks. See bridge/appsrc.py and
docs/handoff/APP-FACADE-MANIFEST.md.

A router may import bridge.core.*, the satellite modules (bridge/voice.py, office.py,
music.py, …) and other routers — the last of those only while the graph stays ACYCLIC,
which bridge/tests/test_app_facade.py checks. Importing bridge.app from here is never
right: app.py is the facade over these modules.
"""
