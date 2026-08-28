"""THE HELP CONTENT ROUTE — /api/help/explainers (roadmap §2.4, v1.5.27).

The panel half (renderer, filter, wiring, all-designs) is bridge/tests/test_help_view.js.
This owns the WIRE: what the bridge actually answers, driven against the real app.

The three facts that matter, and why each is here rather than assumed:

  * IT SERVES THE FILE THE WRITERS EDIT. The whole content pipeline is "edit
    docs/USER-EXPLAINERS.md, ship, ⌘R"; if this route ever served a copy, a cache or a
    baked blob, that claim would quietly stop being true and nobody would notice until
    a help edit failed to appear.
  * IT IS READ-ONLY AND IT IS SCOPED. GET only, one hardcoded filename. A help route
    that took a path parameter would be a file-read primitive on the bridge.
  * A MISSING FILE IS A SENTENCE, NOT A BLANK PAGE. The fat app runs from a snapshot,
    and a snapshot provisioned before ship.sh learned to copy docs/ has no explainers
    at all. The 404 has to NAME the fix — this is the standing empty-state rule applied
    to the surface people reach precisely when they are already lost.

Run: python3 bridge/tests/test_help_route.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.appsrc import APP_SOURCE as APP                      # noqa: E402

FAILS = []
CHECKS = [0]


def ok(cond, msg):
    CHECKS[0] += 1
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def test_source():
    """The route's shape, read off the app layer's own source view."""
    ok('@app.get("/api/help/explainers")' in APP,
       "the route is declared, on the one FastAPI instance like every other lane")
    # the whole surface is ONE route and it is a GET.
    ok(APP.count("/api/help/explainers") == 1,
       "…exactly once — there is no second declaration to disagree with it")
    ok('@app.post("/api/help' not in APP and '@app.put("/api/help' not in APP
       and '@app.delete("/api/help' not in APP,
       "…and there is no POST/PUT/DELETE under /api/help: the surface is read-only")
    ok('HELP_DOC = "USER-EXPLAINERS.md"' in APP,
       "the filename is a constant in the module, not a request parameter — this route "
       "is not a file-read primitive on the bridge")
    ok("{path" not in APP.split("/api/help/explainers")[1].split("def ")[0],
       "…and the path carries no parameter at all")
    ok("no-store" in APP.split("/api/help/explainers")[1][:1600],
       "no-store, or a WKWebView keeps serving yesterday's help after a ship")


def test_live():
    """Drive the REAL app."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live route tests — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A
    from bridge.routers import help as H

    client = TestClient(A.app)

    r = client.get("/api/help/explainers")
    ok(r.status_code == 200, "GET /api/help/explainers is 200 in the repo")
    disk = (ROOT / "docs" / "USER-EXPLAINERS.md").read_text(encoding="utf-8")
    ok(r.text == disk,
       "…and the body is docs/USER-EXPLAINERS.md BYTE FOR BYTE — the route serves the "
       "file the writers edit, which is the whole zero-code-content-update claim")
    ok(r.headers.get("content-type", "").startswith("text/markdown"),
       "…as text/markdown (RAW — the panel owns the rendering, because it needs the "
       "section structure for its contents rail and its filter)")
    ok("no-store" in r.headers.get("cache-control", ""), "…and it is not cacheable")

    head = client.request("POST", "/api/help/explainers")
    ok(head.status_code in (404, 405),
       "a POST to it is refused (405/404), never accepted")

    # THE SNAPSHOT-WITHOUT-DOCS CASE, driven rather than reasoned about. `ROOT` is
    # imported by name into the router, so it is repointed there — the same way the
    # facade propagates A.ROOT into the modules that read it.
    old = H.ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            H.ROOT = Path(td)                     # a root with no docs/ at all
            r2 = client.get("/api/help/explainers")
            ok(r2.status_code == 404, "a missing explainers file is a 404, not a 500")
            body = r2.json()
            ok(body.get("ok") is False, "…with ok:false, so the panel can branch on it")
            ok("USER-EXPLAINERS.md" in body.get("error", ""),
               "…naming the file that is missing")
            ok("ship.sh" in body.get("error", ""),
               "…AND the command that fixes it — the standing empty-state rule, on the "
               "one surface people reach when they are already lost")
    finally:
        H.ROOT = old

    ok(client.get("/api/help/explainers").status_code == 200,
       "…and the route is fine again afterwards (the test repointed nothing permanently)")


for fn in (test_source, test_live):
    fn()

if FAILS:
    print(f"\nFAILED {len(FAILS)} of {CHECKS[0]}:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"\nhelp route: {CHECKS[0]} checks passed")
