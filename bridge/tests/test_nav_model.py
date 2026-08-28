"""NAV MODEL — sidebar/tab-strip customization (FABLE-STUDIO-PHASE2-SPEC §A, 2026-08-21).

What each group guards:

1. THE REGISTRY. Three parties read this layout — the panel, the shell and this module —
   and the ID SET is the only thing they share. A test that the panel's mirror agrees is
   the whole reason a customisation cannot point at an entry one of them cannot render.
2. NORMALIZE. This arrives as JSON from a web page and from a file a human may have
   edited. Every surprise shape must cost that ROW, never the layout: the rule is that
   `normalize` is TOTAL and always returns something renderable.
3. VALIDATE. Two rules, and both exist so a customisation cannot LOSE something —
   nothing hidden on every bar it is allowed on, and at most 12 pinned tabs (Debi's
   ruling). Strict on the wire.
4. REPAIR. The same two problems, fixed silently, when the input is a FILE — a bad
   nav.json must never be able to stop the panel or the shell from starting.
5. PERSISTENCE. Atomic, round-trips, and an absent/corrupt file is the default layout.
6. WIRING. The routes, the generation counter on the carrier the shell already polls,
   and the defaults agreeing with app/main.swift's own default strip.

Run: python3 bridge/tests/test_nav_model.py
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import nav                                          # noqa: E402

FAILS = []
CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("FAIL " + label)


def ids(model, bar):
    return [r["id"] for r in model[bar]]


# ── 1. the registry ──────────────────────────────────────────────────────────
def test_registry():
    ok(len(nav.NAV_IDS) == len(set(nav.NAV_IDS)), "no duplicate ids in the registry")
    for e in nav.NAV_ENTRIES:
        ok(isinstance(e["id"], str) and e["id"], f"{e} has an id")
        ok(e["bars"] and all(b in nav.BARS for b in e["bars"]), f"{e['id']} names real bars")
        ok(e["kind"] in ("view", "lane", "component"), f"{e['id']} has a known kind")
    # Debi's amendment: the two newest lanes ARE in the registry — that is how they
    # become reachable from the sidebar at all (they are lanes, not services, so they
    # never appear on Mission Control).
    for lane in ("aider", "loffice"):
        e = nav.entry(lane)
        ok(e is not None and e["kind"] == "lane", f"{lane} is a registry lane")
        ok(e and set(e["bars"]) == {"sidebar", "topbar"}, f"{lane} may live on either bar")
    # Logs is the ONE sidebar-only entry, and the one that may be hidden everywhere
    # (⌘K reaches it) — both facts are load-bearing for `validate`.
    ok(nav.entry("logs")["bars"] == ("sidebar",), "logs is sidebar-only (it has no view)")
    ok(nav.entry("logs").get("always") is True, "logs is the declared always-reachable one")
    ok(not any(e.get("always") for e in nav.NAV_ENTRIES if e["id"] != "logs"),
       "…and it is the ONLY one (an exemption must be deliberate)")
    ok(nav.can_show("logs", "sidebar") and not nav.can_show("logs", "topbar"),
       "can_show answers the capability question")
    ok(not nav.can_show("nope", "sidebar"), "an unknown id can show nowhere")
    # the defaults mention every id exactly once, per bar
    for bar in nav.BARS:
        got = [i for i, _p in nav.DEFAULTS[bar]]
        ok(len(got) == len(set(got)), f"{bar} defaults have no duplicate")
        for i in got:
            ok(nav.can_show(i, bar), f"{bar} default {i} is allowed on that bar")
        allowed = [e["id"] for e in nav.NAV_ENTRIES if bar in e["bars"]]
        ok(sorted(got) == sorted(allowed), f"{bar} defaults cover every allowed entry")


# ── 2. normalize (TOTALITY) ──────────────────────────────────────────────────
def test_normalize():
    d = nav.default_model()
    ok(nav.validate(d) == "", "the DEFAULT layout is itself valid")
    ok(ids(d, "sidebar")[0] == "mc", "the sidebar default opens on Mission Control")
    ok(ids(d, "topbar")[0] == "mc", "…and so does the strip")
    # The pinned prefix of DEFAULT_TOPBAR, in order — eleven since OpenCode landed
    # (2026-08-21). Derived from the table rather than a literal count so adding a tab
    # is a one-line change here, but the ORDER is still asserted.
    ok(nav.visible(d, "topbar") == [i for i, p in nav.DEFAULT_TOPBAR if p],
       "the default strip is exactly the pinned defaults, in order")
    ok(len(nav.visible(d, "topbar")) == 11,
       "eleven default tabs (ten shipped + OpenCode) — a change here must be deliberate")
    ok(nav.hidden(d, "topbar") == ["chat", "models", "caps"],
       "the three pinnable views start hidden (one sidebar click away)")

    # junk totality: none of these may raise, and each must return a full model
    for junk in [None, 0, "x", [], {"sidebar": "x"}, {"topbar": 7},
                 {"sidebar": [None, 3, [], {}, {"id": 5}]},
                 {"sidebar": [{"id": "mc", "pinned": "yes"}]},
                 {"topbar": ["mc", "mc", "mc"]},
                 {"sidebar": [{"id": "nope"}], "topbar": [{"id": "logs"}]}]:
        m = nav.normalize(junk)
        ok(sorted(ids(m, "sidebar")) == sorted(i for i, _ in nav.DEFAULT_SIDEBAR),
           f"normalize({junk!r}) still yields every sidebar entry")
        ok(sorted(ids(m, "topbar")) == sorted(i for i, _ in nav.DEFAULT_TOPBAR),
           f"normalize({junk!r}) still yields every strip entry")

    # unknown ids are DROPPED (a file from a newer build cannot resurrect an entry)
    m = nav.normalize({"sidebar": [{"id": "ghost"}, {"id": "chat"}]})
    ok("ghost" not in ids(m, "sidebar"), "an unknown id is dropped, not rendered")
    ok(ids(m, "sidebar")[0] == "chat", "…and the known ones keep the order given")
    # an id on a bar it cannot live on is dropped too
    m = nav.normalize({"topbar": [{"id": "logs"}, {"id": "mc"}]})
    ok("logs" not in ids(m, "topbar"), "logs cannot be put on the strip")
    # ORDER IS RENDER ORDER, and a hidden row keeps its place
    m = nav.normalize({"sidebar": [{"id": "caps"}, {"id": "chat", "pinned": False},
                                   {"id": "models"}]})
    ok(ids(m, "sidebar")[:3] == ["caps", "chat", "models"],
       "the given order is preserved exactly (order IS render order)")
    ok(len(ids(m, "sidebar")) == len(nav.DEFAULT_SIDEBAR),
       "…and every omitted entry is appended, so nothing silently disappears")
    # a bare string row means pinned
    m = nav.normalize({"topbar": ["odysseus", "mc"]})
    ok(m["topbar"][0]["id"] == "mc" and m["topbar"][0]["pinned"],
       "Mission Control is forced FIRST and PINNED on the strip")
    ok(ids(m, "topbar")[1] == "odysseus", "…and the rest keep their given order")
    # chat can never be un-pinned from the sidebar
    m = nav.normalize({"sidebar": [{"id": "chat", "pinned": False}]})
    ok(m["sidebar"][0]["id"] == "chat" and m["sidebar"][0]["pinned"],
       "Chat cannot be hidden from the sidebar")
    # appending must never invalidate: at the cap, an appended default lands unpinned
    full = [{"id": i, "pinned": True} for i in
            ["mc", "odysseus", "hermes", "voicestudio", "voicebox", "comfyui",
             "unsloth", "music", "aider", "loffice", "chat", "models"]]
    m = nav.normalize({"topbar": full})
    ok(sum(1 for r in m["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_MAX,
       "an appended entry is never pinned onto a full strip")
    ok(nav.validate(m) == "", "…so normalize can never hand back an over-full strip")
    # IDEMPOTENT
    a = nav.normalize({"sidebar": [{"id": "caps"}], "topbar": [{"id": "music"}]})
    ok(nav.normalize(a) == a, "normalize is a fixed point")


# ── 3. validate (STRICT — the wire) ──────────────────────────────────────────
def test_validate():
    m = nav.default_model()
    ok(nav.validate(m) == "", "the default model validates")

    # hidden on BOTH bars → refused, and the message names the entry
    m = nav.normalize({})
    for r in m["sidebar"]:
        if r["id"] == "models":
            r["pinned"] = False
    for r in m["topbar"]:
        if r["id"] == "models":
            r["pinned"] = False
    err = nav.validate(m)
    ok(err and "models" in err, "an entry hidden on BOTH bars is refused, by name")
    # …but hidden on ONE bar is fine
    m = nav.normalize({})
    for r in m["sidebar"]:
        if r["id"] == "models":
            r["pinned"] = False
    for r in m["topbar"]:
        if r["id"] == "models":
            r["pinned"] = True
    ok(nav.validate(m) == "", "hidden on one bar and shown on the other is legal")
    # logs is the declared exception
    m = nav.normalize({})
    for r in m["sidebar"]:
        if r["id"] == "logs":
            r["pinned"] = False
    ok(nav.validate(m) == "", "logs may be hidden everywhere (⌘K reaches it)")

    # the 13th pin — Debi's ruling — refused with the limit named
    m = nav.normalize({})
    for r in m["topbar"]:
        r["pinned"] = True
    n = sum(1 for r in m["topbar"] if r["pinned"])
    err = nav.validate(m)
    ok(n > nav.NAV_TOPBAR_MAX,
       f"the registry offers {n} strip-able entries, so the cap is reachable at all")
    ok(err and str(nav.NAV_TOPBAR_MAX) in err,
       "pinning every entry is refused, naming the limit")
    ok(nav.NAV_TOPBAR_MAX == 12, "the limit is Debi's 12")
    # exactly 12 is allowed — boundary inclusive. Unpin from the END so the leading
    # choices survive, the same rule `repair` follows.
    over = n - nav.NAV_TOPBAR_MAX
    for r in reversed(m["topbar"]):
        if over and r["pinned"]:
            r["pinned"] = False
            over -= 1
    ok(sum(1 for r in m["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_MAX,
       "unpinning from the end lands exactly on the cap")
    ok(nav.validate(m) == "", "exactly 12 pinned tabs is allowed (boundary inclusive)")


# ── 4. repair (FORGIVING — the file) ─────────────────────────────────────────
def test_repair():
    m = nav.normalize({})
    for bar in nav.BARS:
        for r in m[bar]:
            if r["id"] == "hermes":
                r["pinned"] = False
    fixed = nav.repair({k: [dict(r) for r in v] for k, v in m.items()})
    ok(nav.validate(fixed) == "", "repair fixes a would-be-unreachable entry")
    ok(any(r["id"] == "hermes" and r["pinned"] for r in fixed["sidebar"]),
       "…by putting it back on the SIDEBAR (the home that always exists)")
    m = nav.normalize({})
    for r in m["topbar"]:
        r["pinned"] = True
    fixed = nav.repair(m)
    ok(nav.validate(fixed) == "", "repair drops pins past the cap")
    ok(sum(1 for r in fixed["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_MAX,
       "…down to exactly the cap")
    ok(fixed["topbar"][0]["pinned"] and fixed["topbar"][0]["id"] == "mc",
       "…from the END, so the leading choices survive")


# ── 5. persistence ───────────────────────────────────────────────────────────
def test_persistence():
    with tempfile.TemporaryDirectory() as td:
        ok(nav.read(td) == nav.default_model(), "no file at all = the default layout")
        m = nav.normalize({"sidebar": [{"id": "caps"}, {"id": "chat"}],
                           "topbar": [{"id": "music"}]})
        nav.write(td, m)
        p = nav.nav_path(td)
        ok(os.path.exists(p), "write creates data/nav.json")
        ok(not os.path.exists(p + ".tmp"), "…atomically (no temp file left behind)")
        raw = json.load(open(p))
        ok(raw.get("v") == 1, "the file is versioned")
        back = nav.read(td)
        ok(ids(back, "sidebar") == ids(m, "sidebar"), "the sidebar order round-trips")
        ok(ids(back, "topbar") == ids(m, "topbar"), "the strip order round-trips")
        # a corrupt file is the default, not a crash
        open(p, "w").write("{not json")
        ok(nav.read(td) == nav.default_model(), "a corrupt file degrades to the default")
        open(p, "w").write('["a list, not an object"]')
        ok(nav.read(td) == nav.default_model(), "…so does a file of the wrong shape")
        # a file that would be REFUSED on the wire is REPAIRED on disk
        bad = nav.normalize({})
        for bar in nav.BARS:
            for r in bad[bar]:
                if r["id"] == "music":
                    r["pinned"] = False
        json.dump({"v": 1, **bad}, open(p, "w"))
        ok(nav.validate(nav.read(td)) == "", "a bad file is repaired on read, never fatal")


# ── 6. wiring ────────────────────────────────────────────────────────────────
APP = _APP_SOURCE
SWIFT = (ROOT / "app" / "main.swift").read_text()
PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()


def test_wiring():
    # `..`, not `.`: the defensive pair moved to bridge/core/appctx.py in the router/core
    # split, one directory deeper, so the package-relative branch that means bridge.nav
    # is now `from .. import`. What this pins is the PAIR — a relative try AND an
    # absolute fallback, so a snapshot without nav.py still boots — not the dot count.
    ok("from .. import nav as _nav" in APP and "from bridge import nav as _nav" in APP,
       "the bridge imports nav defensively (a missing module = the default layout, "
       "not a 500)")
    ok('@app.get("/api/nav")' in APP and '@app.post("/api/nav")' in APP,
       "both routes exist")
    ok('"nav_gen": nav_gen()' in APP,
       "the generation rides the EXISTING /api/status carrier — no new poll route")
    ok(APP.count("_nav_bump()") == 2, "the generation is bumped in exactly one place")
    ok("_nav.normalize(raw)" in APP and "_nav.validate(model)" in APP,
       "the POST normalizes THEN validates")
    ok(re.search(r"err = _nav\.validate\(model\)\s*\n\s*if err:\s*\n\s*return JSONResponse\("
                 r"\{\"ok\": False, \"error\": err\}, status_code=400\)", APP),
       "…and REFUSES with the reason rather than quietly repairing")
    ok(APP.index("err = _nav.validate(model)") < APP.index("_nav.write(ROOT, model)"),
       "nothing is written until it validates")

    # the shell's default strip and nav.py's must agree, or the strip and the editor
    # would be describing different windows.
    m = re.search(r'let navDefaultTopbar = \[([^\]]+)\]', SWIFT)
    ok(m is not None, "the shell declares its default strip as one list")
    shell = re.findall(r'"([^"]+)"', m.group(1)) if m else []
    ok(shell == [i for i, p in nav.DEFAULT_TOPBAR if p],
       f"the shell's default strip == nav.py's pinned defaults ({shell})")
    # every registry id the shell can draw is one this module knows
    swift_ids = re.findall(r'HarnessTab\(id: "([^"]+)"', SWIFT)
    ok(sorted(swift_ids) == sorted(e["id"] for e in nav.NAV_ENTRIES if "topbar" in e["bars"]),
       f"the shell's tab registry == the topbar-able ids ({swift_ids})")
    ok(len(swift_ids) == len(set(swift_ids)), "no duplicate tab id in the shell")

    # the PANEL's mirror of the id set + the cap
    pids = re.findall(r"\{ id:'([a-z]+)',", PANEL)
    ok(sorted(set(pids)) == sorted(nav.NAV_IDS),
       f"the panel's NAV_ENTRIES ids == bridge/nav.py's NAV_IDS ({sorted(set(pids))})")
    ok(f"const NAV_TOPBAR_MAX = {nav.NAV_TOPBAR_MAX};" in PANEL,
       "the panel mirrors the same pin cap")
    ok("const NAV_SIDEBAR_ONLY = ['logs'];" in PANEL,
       "…and the same sidebar-only set")
    for bar, const in (("sidebar", "NAV_DEFAULT_SIDEBAR"), ("topbar", "NAV_DEFAULT_TOPBAR")):
        mm = re.search(const + r" = \[([^\]]+)\]", PANEL)
        got = re.findall(r"'([^']+)'", mm.group(1)) if mm else []
        want = [i for i, p in nav.DEFAULTS[bar] if p]
        ok(got == want, f"the panel's {const} == nav.py's pinned {bar} defaults")


def test_routes_live():
    """Drive the REAL app. The POST is pointed at a temp ROOT so the repo's own
    data/nav.json is never touched by a test run."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live route tests — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A

    ok(A._nav is not None, f"the app imported the nav module ({A._NAV_ERR})")
    client = TestClient(A.app)
    with tempfile.TemporaryDirectory() as td:
        old = A.ROOT
        A.ROOT = Path(td)
        try:
            r = client.get("/api/nav")
            ok(r.status_code == 200, "GET /api/nav is 200")
            body = r.json()
            ok(body["ok"] and body["nav"]["topbar"], "…and carries a layout")
            ok(body["max_topbar"] == nav.NAV_TOPBAR_MAX, "…and the cap the panel enforces")
            gen0 = body["gen"]

            good = nav.normalize({"topbar": [{"id": "hermes"}, {"id": "mc"}]})
            r = client.post("/api/nav", json={"nav": good})
            ok(r.status_code == 200 and r.json()["ok"], "POST /api/nav saves a valid layout")
            ok(r.json()["gen"] == gen0 + 1, "…and moves the generation exactly once")
            ok(os.path.exists(nav.nav_path(td)), "…writing data/nav.json under ROOT")
            ok([x["id"] for x in r.json()["nav"]["topbar"]][:2] == ["mc", "hermes"],
               "…with Mission Control forced first")

            # ── THE REORDER ROUND TRIP (Debi: "reorder not working", 2026-08-21) ──
            # Driven in EXACTLY the panel's payload shape — {"nav": {sidebar:[{id,pinned}],
            # topbar:[...]}} — so a mismatch between what the panel sends and what nav.py
            # accepts would fail here. It does not: the order comes back verbatim, the
            # generation moves, and the file agrees. The bug Debi saw was PANEL-side (the
            # sidebar is drawn as two groups out of one flat list, so moving a component
            # above a view saved perfectly and moved nothing on screen — see the v2 note in
            # bridge/panel/index.html).
            base = client.get("/api/nav").json()["nav"]
            g1 = client.get("/api/nav").json()["gen"]
            moved = {b: [dict(r) for r in base[b]] for b in nav.BARS}
            row = [r for r in moved["topbar"] if r["id"] == "unsloth"][0]
            moved["topbar"].remove(row)
            moved["topbar"].insert(1, row)          # straight after the pinned mc
            srow = [r for r in moved["sidebar"] if r["id"] == "music"][0]
            moved["sidebar"].remove(srow)
            moved["sidebar"].insert(0, srow)
            want_top = [r["id"] for r in moved["topbar"]]
            want_side = [r["id"] for r in moved["sidebar"]]
            r = client.post("/api/nav", json={"nav": moved})
            ok(r.status_code == 200 and r.json()["ok"],
               f"a REORDER in the panel's own payload shape is accepted ({r.json().get('error')})")
            ok([x["id"] for x in r.json()["nav"]["topbar"]] == want_top,
               "…the strip order comes back exactly as sent")
            ok([x["id"] for x in r.json()["nav"]["sidebar"]] == want_side,
               "…and so does the sidebar order")
            ok(r.json()["gen"] == g1 + 1, "…and the generation the SHELL polls moves")
            back = client.get("/api/nav").json()["nav"]
            ok([x["id"] for x in back["topbar"]] == want_top,
               "…and a fresh read of data/nav.json agrees (it really persisted)")
            ok([x["id"] for x in json.loads(open(nav.nav_path(td)).read())["topbar"]] == want_top,
               "…as does the file itself")
            ok(all(r0["pinned"] == r1["pinned"]
                   for r0, r1 in zip(sorted(base["topbar"], key=lambda x: x["id"]),
                                     sorted(back["topbar"], key=lambda x: x["id"]))),
               "…and a reorder changed nothing about what is SHOWN")

            gen_pre_bad = client.get("/api/nav").json()["gen"]
            bad = nav.normalize({})
            for bar in nav.BARS:
                for row in bad[bar]:
                    if row["id"] == "comfyui":
                        row["pinned"] = False
            r = client.post("/api/nav", json={"nav": bad})
            ok(r.status_code == 400 and "comfyui" in r.json()["error"],
               "an entry that would vanish is refused 400, by name")
            gen_after = client.get("/api/nav").json()["gen"]
            ok(gen_after == gen_pre_bad, "a REFUSED save does not move the generation")

            r = client.post("/api/nav", data="not json")
            ok(r.status_code == 400, "a body that is not json is 400, not a 500")

        finally:
            A.ROOT = old
    # /api/status reads harness.yaml, so it runs against the REAL root (read-only).
    st = client.get("/api/status")
    ok(st.status_code == 200 and "nav_gen" in st.json(),
       "/api/status carries nav_gen for the shell to poll")


for fn in (test_registry, test_normalize, test_validate, test_repair,
           test_persistence, test_wiring, test_routes_live):
    fn()

if FAILS:
    print(f"\nFAILED {len(FAILS)} of {CHECKS[0]}:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"\nnav model: {CHECKS[0]} checks passed")
