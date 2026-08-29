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
        ok(all(b in nav.BARS for b in e["bars"]), f"{e['id']} names real bars")
        ok(e["kind"] in ("view", "lane", "component"), f"{e['id']} has a known kind")
    # Debi's amendment: the two newest lanes ARE in the registry — that is how they
    # become reachable from the sidebar at all (they are lanes, not services, so they
    # never appear on Mission Control).
    for lane in ("aider", "loffice", "goose", "comfy", "compose", "gooseui"):
        e = nav.entry(lane)
        ok(e is not None and e["kind"] == "lane", f"{lane} is a registry lane")
        ok(e and set(e["bars"]) == {"sidebar", "topbar"}, f"{lane} may live on either bar")
    # ⚠️ THE COMFY PAIR. `comfy` (our /comfy Generate surface) and `comfyui` (upstream's
    # stock UI on :8188) are TWO entries for TWO real surfaces, and the comfy-nav slice
    # must never be "simplified" into one: dropping `comfyui` takes the stock UI away,
    # dropping `comfy` takes our generate page back off the navigation entirely.
    ok(nav.entry("comfy")["kind"] == "lane" and nav.entry("comfyui")["kind"] == "component",
       "comfy is OUR lane and comfyui is THE component — both present, and distinct")
    # ⚠️ THE MUSIC PAIR, REWRITTEN AT THE CONSOLIDATION SLICE (Debi 2026-08-29) AND NOT
    # WEAKENED. The Compose slice's rule was "both stay until Debi chooses"; she chose:
    # ONE door, both looks. So BOTH SURFACES STILL EXIST — collapsing either into the
    # other still removes something the user has — but only ONE of them may be a row.
    ok(nav.entry("music")["kind"] == "view" and nav.entry("compose")["kind"] == "lane",
       "music is the panel VIEW and compose is OUR lane — both present, and distinct")
    ids = list(nav.NAV_IDS)
    ok(ids.index("compose") == ids.index("music") + 1,
       "compose is registered DIRECTLY after music (the spec's placement, not a tail append)")
    ok("music" not in [i for i, _p in nav.DEFAULT_SIDEBAR]
       and "music" not in [i for i, _p in nav.DEFAULT_TOPBAR],
       "ONE Music row and ONE Music tab: `music` is on neither default bar")
    ok(nav.SUPERSEDED == {"music": "compose"},
       "…and a saved layout naming `music` is rewritten into `compose`, not dropped")
    # ⚠️ THE GOOSE PAIR, for the comfy pair's and the music pair's exact reason (Goose UI
    # slice, ledger S14). `goose` is the PTY terminal lane at /goose and `gooseui` is the
    # embedded surface at /gooseui/ driving a goosed we supervise. Debi's ruling is that
    # BOTH lanes coexist — they hold separate homes and separate session stores — so
    # collapsing either into the other silently removes a surface the user has.
    ok(nav.entry("goose")["kind"] == "lane" and nav.entry("gooseui")["kind"] == "lane",
       "goose (terminal) and gooseui (embedded) are BOTH registry lanes, and distinct")
    ok(ids.index("gooseui") == ids.index("goose") + 1,
       "gooseui is registered DIRECTLY after goose (one product, two surfaces — not a "
       "tail append)")
    # Logs and Help are the sidebar-only entries, and the ones that may be hidden
    # everywhere (⌘K reaches both) — all of it is load-bearing for `validate`.
    #
    # ⚠️ THIS ASSERTION WAS `logs` ALONE UNTIL v1.5.27, AND IT IS WIDENED, NOT WEAKENED.
    # The point of it is that an exemption must be DELIBERATE, so the check is still a
    # closed list — it just names two entries now, and each one's argument is written
    # at its registry line. A third `always` still fails here until somebody comes and
    # makes the case for it in this comment.
    for eid in ("logs", "help"):
        ok(nav.entry(eid)["bars"] == ("sidebar",), f"{eid} is sidebar-only")
        ok(nav.entry(eid).get("always") is True, f"{eid} is declared always-reachable")
    ok({e["id"] for e in nav.NAV_ENTRIES if e.get("always")} == {"logs", "help"},
       "…and those two are the ONLY ones (an exemption must be deliberate)")
    # ⚠️ WIDENED AT THE MUSIC-CONSOLIDATION SLICE, NOT WEAKENED: `bars` may now be
    # EMPTY, which says "this build knows the entry and NO bar may hold a row for it".
    # It is still a CLOSED list of one, with its argument at its registry line, and the
    # pair of questions is now explicit — `can_show` (may it be a ROW?) vs `can_tab`
    # (may the STRIP draw it at all?). An entry with no bars and no tab would be
    # unreachable, which is the thing this asserts cannot happen by accident.
    offbar = [e["id"] for e in nav.NAV_ENTRIES if not e["bars"]]
    ok(offbar == ["music"],
       "exactly one entry is allowed on no bar — Music Classic, reached from the "
       f"Studio's header switcher (got {offbar})")
    ok(nav.entry("music").get("tab_only") is True and nav.can_tab("music"),
       "…and it earns that by having a TAB: the strip can still draw it, through the "
       "last-three window")
    ok(not nav.can_show("music", "sidebar") and not nav.can_show("music", "topbar"),
       "…while no bar may hold a row for it")
    ok({e["id"] for e in nav.NAV_ENTRIES if e.get("tab_only")} == {"music"},
       "…and `tab_only` is that same closed list (an exemption must be deliberate)")
    ok(nav.can_tab("comfy") and not nav.can_tab("logs") and not nav.can_tab("nope"),
       "can_tab is a SUPERSET of can_show(topbar): a lane yes, a dialog no, junk no")
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
    # ⚠️ WAS 11 PINS UNTIL THE 9+3 RULING (Debi 2026-08-29), AND THE STRIP STILL DRAWS
    # ELEVEN TABS — that is the whole point of the seed, and it is asserted below rather
    # than left to inspection. Nine pins + the two-entry default window.
    ok(len(nav.visible(d, "topbar")) == 9,
       "nine default PINS (a change here must be deliberate)")
    ok(nav.strip(d) == [i for i, p in nav.DEFAULT_TOPBAR if p] + list(nav.DEFAULT_MRU),
       "…and the default STRIP is those pins followed by the window's seed")
    ok(len(nav.strip(d)) == 11,
       "…which is the SAME ELEVEN TABS the strip drew before the ruling: nothing left "
       "the strip, two of them merely became swappable")
    ok(nav.strip(d)[9] == "compose",
       "…with the Music surface where Music was — slot ten (the consolidation slice)")
    ok(nav.NAV_TOPBAR_PINS == 9 and nav.NAV_TOPBAR_MRU == 3
       and nav.NAV_TOPBAR_MAX == 12,
       "9 stable pins + a 3-slot window = Debi's 12, unchanged")
    ok(len(nav.strip(d)) <= nav.NAV_TOPBAR_MAX, "the default strip is inside the cap")
    # ⚠️ WIDENED AT THE GOOSE SLICE, NOT WEAKENED. It is still a CLOSED list and the
    # point is unchanged: an entry declared on the strip but not pinned must be a
    # deliberate choice with its argument written at its registry line. Goose joins the
    # three views because the strip is at 11 of NAV_TOPBAR_MAX=12 pins and a new lane
    # must not silently spend the last one — see nav.py's DEFAULT_TOPBAR tail.
    #
    # ⚠️ WIDENED AGAIN AT THE COMFY-NAV SLICE, AND AGAIN NOT WEAKENED: `comfy`
    # (Generate) is on the list for goose's identical argument — the pinned prefix is
    # STILL 11 of 12, so the one free pin stays free rather than being spent by whichever
    # lane happens to land next. The list remains closed and ordered; a fifth entry
    # requires its own argument at its own registry line.
    #
    # ⚠️ WIDENED A THIRD TIME AT THE COMPOSE SLICE, AND AGAIN NOT WEAKENED: `compose`
    # joins for goose's and comfy's identical argument (the pinned prefix is STILL 11 of
    # 12) plus one of its own — it is an ALTERNATIVE to `music`, which IS pinned, and
    # pinning both by default would put two surfaces for one job on the strip without
    # anyone choosing that. The list remains closed and ordered.
    #
    # ⚠️ WIDENED A FOURTH TIME AT THE GOOSE UI SLICE, AND AGAIN NOT WEAKENED: `gooseui`
    # joins with the strongest version of the argument yet — the pinned prefix is STILL
    # 11 of 12, AND this lane is an alternative SURFACE onto the same product as `goose`,
    # which is itself still waiting behind ⋯ for that one free pin. Pinning the embedded
    # lane by default would silently declare a winner between two lanes Debi's ruling
    # says coexist. The list remains closed and ordered.
    # ⚠️ WIDENED A FIFTH TIME AT THE 9+3 SLICE, AND STILL NOT WEAKENED. It is the same
    # closed, ordered list; `compose` and `voicebox` join it for a DIFFERENT reason,
    # which is why they LEAD it: they are not waiting behind ⋯ for a pin, they are the
    # SEED OF THE WINDOW and are ON the default strip. The four lanes after them are
    # unpinned for their original argument, which the window now also answers — a lane
    # behind ⋯ is one click from a strip slot instead of one click from a pin nobody
    # has spare.
    ok(nav.hidden(d, "topbar") == ["compose", "voicebox", "chat", "models", "caps",
                                   "goose", "comfy", "gooseui"],
       "the window's seed + the three pinnable views + goose + comfy + gooseui are the "
       "unpinned rows, in order")
    ok(set(nav.hidden(d, "topbar")) - set(nav.strip(d))
       == {"chat", "models", "caps", "goose", "comfy", "gooseui"},
       "…and the ⋯ menu is the unpinned rows MINUS the window: exactly the six that are "
       "not on the strip at all")
    ok("goose" not in [i for i, p in nav.DEFAULT_TOPBAR if p]
       and "gooseui" not in [i for i, p in nav.DEFAULT_TOPBAR if p],
       "…and NEITHER goose lane is pinned: the strip does not pick one of the two")

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
    # ⚠️ NOT `[0] == "chat"` ANY MORE, AND THE CHANGE IS THE NEIGHBOUR-APPEND FIX (A8/
    # S19) DOING ITS JOB: `mc` is the first entry in the default order, so a layout that
    # does not carry it gets it in FRONT rather than at the tail. What is asserted is
    # the invariant that matters — the given rows are all there, in the order given.
    g = ids(m, "sidebar")
    ok("chat" in g and g.index("mc") < g.index("chat"),
       "…the known ones are kept, and an omitted first-in-default-order entry lands "
       "in front rather than at the bottom")
    # an id on a bar it cannot live on is dropped too
    m = nav.normalize({"topbar": [{"id": "logs"}, {"id": "mc"}]})
    ok("logs" not in ids(m, "topbar"), "logs cannot be put on the strip")
    # ORDER IS RENDER ORDER, and a hidden row keeps its place
    m = nav.normalize({"sidebar": [{"id": "caps"}, {"id": "chat", "pinned": False},
                                   {"id": "models"}]})
    # ⚠️ WIDENED AT THE NEIGHBOUR-APPEND FIX (ledger A8/S19), AND IT IS A STRONGER
    # CHECK, NOT A LOOSER ONE. Before it, an omitted entry went to the TAIL and the
    # given rows were therefore always the first N; now an omitted entry lands at its
    # DEFAULT-ORDER NEIGHBOUR, so it may sit BETWEEN two given rows. What must hold —
    # and what "order IS render order" actually means — is that the rows the caller
    # gave keep their RELATIVE order and none of them moves past another.
    got = ids(m, "sidebar")
    ok([i for i in got if i in ("caps", "chat", "models")] == ["caps", "chat", "models"],
       "the given rows keep their relative order exactly (order IS render order)")
    ok(len(got) == len(nav.DEFAULT_SIDEBAR),
       "…and every omitted entry is added, so nothing silently disappears")
    # …and the ADDED ones land at their designed neighbour rather than at the tail.
    ok(got.index("logs") + 1 == got.index("help"),
       "an omitted entry lands after its default-order neighbour (Help under Logs) — "
       "ledger A8/S19, three sightings, closed here")
    ok(got.index("compose") + 1 == got.index("comfy"),
       "…and Generate beside the Music surface, not at the bottom of the group")
    ok(got.index("goose") + 1 == got.index("gooseui"),
       "…and Goose UI directly after Goose CLI (the third sighting's own case)")
    # a bare string row means pinned
    m = nav.normalize({"topbar": ["odysseus", "mc"]})
    ok(m["topbar"][0]["id"] == "mc" and m["topbar"][0]["pinned"],
       "Mission Control is forced FIRST and PINNED on the strip")
    ok(ids(m, "topbar")[1] == "odysseus", "…and the rest keep their given order")
    # chat can never be un-pinned from the sidebar
    m = nav.normalize({"sidebar": [{"id": "chat", "pinned": False}]})
    ok(any(r["id"] == "chat" and r["pinned"] for r in m["sidebar"]),
       "Chat cannot be hidden from the sidebar")
    # appending must never invalidate: at the cap, an appended default lands unpinned
    # ⚠️ THE CAP THE APPEND RESPECTS IS NOW THE PIN CAP (9), NOT THE STRIP SIZE (12).
    # The rule is unchanged in substance and this is still the boundary case: a caller
    # who arrives already AT the cap must not have a new registry entry pinned on top of
    # their layout, because growing the registry may never invalidate a model that was
    # valid a moment ago.
    full = [{"id": i, "pinned": True} for i in
            ["mc", "odysseus", "hermes", "voicestudio", "voicebox", "comfyui",
             "unsloth", "compose", "aider"]]
    m = nav.normalize({"topbar": full})
    ok(sum(1 for r in m["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_PINS,
       "an appended entry is never pinned onto a full strip")
    ok(nav.validate(m) == "", "…so normalize can never hand back an over-pinned strip")
    ok(len(nav.strip(m)) <= nav.NAV_TOPBAR_MAX,
       "…and the strip it derives is never longer than Debi's twelve")
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
        # …and one pin has to come off to make room, because the default layout already
        # spends all nine. That is the 9+3 cap being real, not a wrinkle in this test.
        if r["id"] == "loffice":
            r["pinned"] = False
    ok(nav.validate(m) == "", "hidden on one bar and shown on the other is legal")
    # logs is the declared exception
    m = nav.normalize({})
    for r in m["sidebar"]:
        if r["id"] == "logs":
            r["pinned"] = False
    ok(nav.validate(m) == "", "logs may be hidden everywhere (⌘K reaches it)")

    # THE 10th PIN — refused with BOTH numbers named. ⚠️ THE CAP MOVED FROM 12 TO 9 AT
    # THE 9+3 RULING AND DEBI'S 12 DID NOT MOVE: the strip still holds twelve, three of
    # which are the most-recently-opened window rather than pins. That is why the
    # message must carry the window as well as the number — "at most 9" alone reads as
    # a cap that was cut, which is a lie about what the user lost.
    m = nav.normalize({})
    for r in m["topbar"]:
        r["pinned"] = True
    n = sum(1 for r in m["topbar"] if r["pinned"])
    err = nav.validate(m)
    ok(n > nav.NAV_TOPBAR_PINS,
       f"the registry offers {n} strip-able entries, so the cap is reachable at all")
    ok(err and str(nav.NAV_TOPBAR_PINS) in err,
       "pinning every entry is refused, naming the limit")
    ok(err and str(nav.NAV_TOPBAR_MRU) in err and str(nav.NAV_TOPBAR_MAX) in err,
       "…and naming where the other three slots went, so the cap does not read as loss")
    ok(nav.NAV_TOPBAR_MAX == 12, "the STRIP is still Debi's 12")
    ok(nav.NAV_TOPBAR_PINS + nav.NAV_TOPBAR_MRU == nav.NAV_TOPBAR_MAX,
       "…and it is exactly the pins plus the window — no slot is unaccounted for")
    # exactly 9 pins is allowed — boundary inclusive. Unpin from the END so the leading
    # choices survive, the same rule `repair` follows.
    over = n - nav.NAV_TOPBAR_PINS
    for r in reversed(m["topbar"]):
        if over and r["pinned"]:
            r["pinned"] = False
            over -= 1
    ok(sum(1 for r in m["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_PINS,
       "unpinning from the end lands exactly on the cap")
    ok(nav.validate(m) == "", "exactly 9 pinned tabs is allowed (boundary inclusive)")
    ok(len(nav.strip(m)) <= nav.NAV_TOPBAR_MAX,
       "…and the strip it derives still fits in twelve")


# ── 4. repair (FORGIVING — the file) ─────────────────────────────────────────
def test_repair():
    m = nav.normalize({})
    for bar in nav.BARS:
        for r in m[bar]:
            if r["id"] == "hermes":
                r["pinned"] = False
    fixed = nav.repair({**m, **{b: [dict(r) for r in m[b]] for b in nav.BARS}})
    ok(nav.validate(fixed) == "", "repair fixes a would-be-unreachable entry")
    ok(any(r["id"] == "hermes" and r["pinned"] for r in fixed["sidebar"]),
       "…by putting it back on the SIDEBAR (the home that always exists)")
    m = nav.normalize({})
    for r in m["topbar"]:
        r["pinned"] = True
    fixed = nav.repair(m)
    ok(nav.validate(fixed) == "", "repair drops pins past the cap")
    ok(sum(1 for r in fixed["topbar"] if r["pinned"]) == nav.NAV_TOPBAR_PINS,
       "…down to exactly the cap")
    ok(fixed["topbar"][0]["pinned"] and fixed["topbar"][0]["id"] == "mc",
       "…from the END, so the leading choices survive")

    # ── THE 9+3 UPGRADE PATH, EXECUTED. Every nav.json in existence carries ELEVEN
    # pinned tabs. Trimming to nine and stopping would take two tabs off the strip on
    # the next boot with nothing said, so the trimmed ones are pushed to the FRONT of
    # the window instead: the strip still draws what it drew.
    eleven = ["mc", "hermes", "unsloth", "opencode", "odysseus", "voicestudio",
              "comfyui", "aider", "loffice", "music", "voicebox"]
    old = {"v": nav.MODEL_V,
           "sidebar": [{"id": i, "pinned": p} for i, p in nav.DEFAULT_SIDEBAR],
           "topbar": [{"id": i, "pinned": True} for i in eleven]}
    up = nav.repair(nav.normalize(old))
    ok(nav.validate(up) == "", "an eleven-pin layout from before the ruling still saves")
    ok(nav.visible(up, "topbar") == eleven[:9], "…its first nine pins are untouched")
    ok(up["mru"][:2] == ["compose", "voicebox"],
       "…and the tenth and eleventh went into the window, in their strip order "
       "(`music` superseded to `compose` on the way)")
    ok(nav.strip(up) == eleven[:9] + ["compose", "voicebox"],
       "…so the STRIP IS UNCHANGED: eleven tabs, same order, Music where Music was")
    ok(nav.repair(nav.normalize(up)) == up, "…and the trim is idempotent (it settles)")


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
        ok(raw.get("v") == nav.MODEL_V, "the file is versioned (v%d)" % nav.MODEL_V)
        # ADDITIVE, no `v` bump: an older build ignores the key, this one seeds the
        # default window when it is absent, and neither can clobber the other's layout.
        ok(isinstance(raw.get("mru"), list), "…and carries the last-three window")
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


# ── 5b. THE ONE-TIME DEFAULT-TOPBAR REORDER MIGRATION (v1.5.26) ──────────────
# ⚠️ THE TRAP. Changing DEFAULT_TOPBAR changes what a FRESH machine gets and nothing
# else: every machine that has opened the panel has a data/nav.json, and applyNav puts
# the SAVED order back. Without the migration Debi's reorder is invisible on Debi's own
# Mac — a shipped change that does nothing where it matters. The rule: untouched gets
# the new default, customised is left alone, and it happens ONCE per machine.
def test_reorder_migration():
    new = [i for i, p in nav.DEFAULT_TOPBAR]
    old = [i for i, p in nav.DEFAULT_TOPBAR_V1]
    ok(new != old, "the reorder actually reorders something")
    ok(sorted(new) == sorted(old),
       "…and it moves the SAME ids — no entry gained or lost a home, so `validate` has "
       "nothing new to say and nothing can become unreachable")
    ok([i for i, p in nav.DEFAULT_TOPBAR if p][:5]
       == ["mc", "hermes", "unsloth", "opencode", "odysseus"],
       "Debi's order leads with the deck and the three agent/model lanes")

    def v1_file():
        return {"v": 1,
                "sidebar": [{"id": i, "pinned": p} for i, p in nav.DEFAULT_SIDEBAR],
                "topbar": [{"id": i, "pinned": p} for i, p in nav.DEFAULT_TOPBAR_V1]}

    # (a) UNTOUCHED — the case that must move
    got, moved = nav.migrate(v1_file())
    ok(moved and [r["id"] for r in got["topbar"]] == new,
       "an UNTOUCHED v1 layout is replaced with Debi's order")
    ok([r["id"] for r in got["sidebar"]] == [i for i, _p in nav.DEFAULT_SIDEBAR],
       "…and the sidebar is untouched: this ruling was about the tab strip only")

    # (b) CUSTOMISED — every case that must NOT move
    f = v1_file(); f["topbar"] = list(reversed(f["topbar"]))
    ok(nav.migrate(f)[1] is False, "a REORDERED layout is left exactly alone")
    f = v1_file()
    f["topbar"] = [dict(r, pinned=False) if r["id"] == "comfyui" else r for r in f["topbar"]]
    ok(nav.migrate(f)[1] is False,
       "…and so is one that differs only by a PIN (unpinning is customising too)")
    f = v1_file(); f["topbar"] = f["topbar"] + [{"id": "nope", "pinned": True}]
    ok(nav.migrate(f)[1] is False, "…and one from a newer build carrying an unknown id")
    f = v1_file(); f["topbar"] = f["topbar"][:-1]
    ok(nav.migrate(f)[1] is False, "…and one that is merely SHORT of the old default")

    # (c) TOTALITY + the stamp
    ok(nav.migrate(None) == (None, False) and nav.migrate("junk") == ("junk", False),
       "migrate is TOTAL — junk in, junk back, never a throw on boot")
    ok(nav.migrate({"v": "banana", **v1_file()})[1] is True,
       "…and an unparseable version reads as OLD, so the migration still runs")
    ok(nav.migrate({**v1_file(), "v": nav.MODEL_V})[1] is False,
       "a layout already stamped v%d is never migrated again" % nav.MODEL_V)


def test_reorder_migration_on_disk_runs_exactly_once():
    """The end-to-end shape: an old file on disk migrates on the first read, is STAMPED,
    and a layout the user then arranges into the old order is never taken away again."""
    with tempfile.TemporaryDirectory() as td:
        p = nav.nav_path(td)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump({"v": 1,
                   "sidebar": [{"id": i, "pinned": q} for i, q in nav.DEFAULT_SIDEBAR],
                   "topbar": [{"id": i, "pinned": q} for i, q in nav.DEFAULT_TOPBAR_V1]},
                  open(p, "w"))
        m = nav.read(td)
        ok(nav.visible(m, "topbar") == [i for i, q in nav.DEFAULT_TOPBAR if q],
           "an untouched v1 file on disk reads back as Debi's order")
        ok(json.load(open(p)).get("v") == nav.MODEL_V,
           "…and the file is STAMPED on that read, so this is a one-time event")

        # now the user arranges their strip back into the old order. It must survive.
        m2 = nav.normalize({"sidebar": [{"id": i, "pinned": q} for i, q in nav.DEFAULT_SIDEBAR],
                            "topbar": [{"id": i, "pinned": q} for i, q in nav.DEFAULT_TOPBAR_V1]})
        nav.write(td, m2)
        ok(nav.visible(nav.read(td), "topbar") == [i for i, q in nav.DEFAULT_TOPBAR_V1 if q],
           "a user who LATER chooses the old order keeps it — the stamp, not the shape, "
           "is what says 'already considered'")

    # …and a machine with no file at all simply gets the new default, no write needed.
    with tempfile.TemporaryDirectory() as td:
        ok(nav.visible(nav.read(td), "topbar") == [i for i, q in nav.DEFAULT_TOPBAR if q],
           "a fresh machine gets Debi's order with no migration involved")
        ok(not os.path.exists(nav.nav_path(td)),
           "…and reading a machine with no nav.json still writes nothing")


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
    # ⚠️ WIDENED FROM 2 TO 3 AT THE 9+3 SLICE, NOT WEAKENED. The point of this fence is
    # that a bump is DELIBERATE and lives beside the write it accounts for — `POST
    # /api/nav` (the save) and now `POST /api/nav/mru` (the swap), which writes
    # nav.json too and must therefore move the generation the shell polls. Three
    # occurrences = the definition + one call per writer; a fourth needs its argument.
    ok(APP.count("_nav_bump()") == 3,
       "the generation is bumped once per WRITER (the save and the window swap)")
    ok('@app.post("/api/nav/mru")' in APP,
       "the last-three window has its own route — a USE, not a SAVE: it can never "
       "refuse, reorder or drop a row")
    ok("_nav.mru_touch(model, eid)" in APP,
       "…and it delegates the rule to nav.py rather than reimplementing it")
    ok('"strip": _nav.strip(model)' in APP,
       "…while GET /api/nav derives the strip ONCE, for the shell to draw")
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
    # ⚠️ THE COMPARISON IS `can_tab`, NOT `"topbar" in bars`, SINCE THE CONSOLIDATION
    # SLICE — and that is a WIDENING with a named reason, not a loosening. Music Classic
    # is a real tab that no bar may hold a row for (`tab_only`), so the question the
    # shell's registry answers is "does this build know that tab at all", which is
    # exactly `can_tab`. Under the old spelling this fence would have demanded the shell
    # DELETE the Classic tab — taking the surface away to satisfy a test.
    swift_ids = re.findall(r'HarnessTab\(id: "([^"]+)"', SWIFT)
    ok(sorted(swift_ids) == sorted(e["id"] for e in nav.NAV_ENTRIES if nav.can_tab(e["id"])),
       f"the shell's tab registry == the tab-able ids ({swift_ids})")
    ok("music" in swift_ids and "compose" in swift_ids,
       "…and BOTH music surfaces still have a tab — one door, both looks")
    ok('HarnessTab(id: "music", title: "Music Classic"' in SWIFT
       and 'HarnessTab(id: "compose", title: "Music"' in SWIFT,
       "…titled as Debi named them, with neither id moved")
    mm = re.search(r'let navDefaultMru = \[([^\]]+)\]', SWIFT)
    shell_mru = re.findall(r'"([^"]+)"', mm.group(1)) if mm else []
    ok(shell_mru == list(nav.DEFAULT_MRU),
       f"the shell's default window == nav.py's DEFAULT_MRU ({shell_mru})")
    ok(shell + shell_mru == nav.strip(nav.default_model()),
       "…so the strip the shell draws before the bridge answers IS nav.strip(default)")
    ok("let navWindowMax = 3" in SWIFT and "func touchWindow(" in SWIFT
       and "api/nav/mru" in SWIFT,
       "…and the window is bounded, swapped through one function, and PERSISTED "
       "(the unbounded `tempShown` that let a 12-tab strip draw fourteen is gone)")
    ok("tempShown" not in SWIFT.replace("// `tempShown`", ""),
       "…with no tempShown left anywhere but the note recording what it was")
    ok(len(swift_ids) == len(set(swift_ids)), "no duplicate tab id in the shell")

    # the PANEL's mirror of the id set + the cap
    pids = re.findall(r"\{ id:'([a-z]+)',", PANEL)
    ok(sorted(set(pids)) == sorted(nav.NAV_IDS),
       f"the panel's NAV_ENTRIES ids == bridge/nav.py's NAV_IDS ({sorted(set(pids))})")
    ok(f"const NAV_TOPBAR_MAX = {nav.NAV_TOPBAR_MAX};" in PANEL,
       "the panel mirrors the same pin cap")
    ok("const NAV_SIDEBAR_ONLY = ['logs','help'];" in PANEL,
       "…and the same sidebar-only set (logs + help)")
    # THE `always` SET, mirrored. Until Help arrived the panel's validate carried a
    # hardcoded `e.id === 'logs'`, which is precisely how a second exception gets added
    # on one side only — so both sides now NAME the list and this compares them.
    ok("const NAV_ALWAYS = ['logs','help'];" in PANEL,
       "…and the same `always` set, as a NAMED list rather than an inline id test")
    ok(sorted(e["id"] for e in nav.NAV_ENTRIES if e.get("always")) == ["help", "logs"],
       "nav.py's `always` entries are exactly logs + help")
    ok("if (NAV_ALWAYS.indexOf(e.id) >= 0) continue;" in PANEL,
       "…and the panel's validate reads that list instead of naming one id")
    for bar, const in (("sidebar", "NAV_DEFAULT_SIDEBAR"), ("topbar", "NAV_DEFAULT_TOPBAR")):
        mm = re.search(const + r" = \[([^\]]+)\]", PANEL)
        got = re.findall(r"'([^']+)'", mm.group(1)) if mm else []
        want = [i for i, p in nav.DEFAULTS[bar] if p]
        ok(got == want, f"the panel's {const} == nav.py's pinned {bar} defaults")


def test_help_entry():
    """HELP (roadmap §2.4) — the registry entry, and the upgrade path EXECUTED.

    The interesting half is not that the entry exists; it is that adding it moved
    nothing. A machine with a saved nav.json must gain the row without its tab strip
    or its arranged sidebar changing, and hiding Help must stay a legal choice."""
    h = nav.entry("help")
    ok(h is not None, "the registry knows Help")
    ok(h and h["bars"] == ("sidebar",),
       "Help is SIDEBAR-ONLY — a reference surface, and the strip is at 11 of 12 pins")
    ok(h and h.get("always") is True,
       "…and hideable, because ⌘K reaches it (the argument Logs already carried)")
    ok("help" not in [i for i, _p in nav.DEFAULT_TOPBAR],
       "Help is not on the default strip at all, so no saved topbar layout can move")
    side = [i for i, _p in nav.DEFAULT_SIDEBAR]
    ok(dict(nav.DEFAULT_SIDEBAR).get("help") is True, "…and it IS pinned on the sidebar")
    ok(side.index("help") == side.index("logs") + 1,
       "…directly under Logs, which is where the roadmap put it")
    ok(not nav.can_show("help", "topbar"), "the model refuses to put Help on the strip")

    # THE UPGRADE PATH, executed rather than asserted about.
    old = {"v": nav.MODEL_V,
           "sidebar": [{"id": i, "pinned": p} for i, p in nav.DEFAULT_SIDEBAR if i != "help"],
           "topbar": [{"id": i, "pinned": p} for i, p in nav.DEFAULT_TOPBAR]}
    got = nav.normalize(old)
    ok("help" in [r["id"] for r in got["sidebar"]],
       "a pre-Help nav.json gains the Help row on read (normalize appends known ids)")
    ok([r["id"] for r in got["topbar"]] == [i for i, _p in nav.DEFAULT_TOPBAR],
       "…and the TAB STRIP is byte-identical — Help is not topbar-able, so nothing moved")
    ok(nav.validate(got) == "", "…and the upgraded model still saves")

    # hiding Help everywhere is ALLOWED — the whole point of `always`.
    hidden = {b: [dict(r, pinned=(False if r["id"] == "help" else r["pinned"]))
                  for r in got[b]] for b in nav.BARS}
    ok(nav.validate(hidden) == "",
       "hiding Help is a legal customisation (⌘K is the reachability that pays for it)")
    ok(any(r["id"] == "help" and not r["pinned"] for r in nav.repair(hidden)["sidebar"]),
       "…and `repair` does not silently pin it back on the next read")
    # a POST that tries to smuggle Help onto the strip loses the ROW, not the layout
    smuggled = nav.normalize({"topbar": [{"id": "mc"}, {"id": "help"}, {"id": "hermes"}],
                              "sidebar": [{"id": "chat"}]})
    ok("help" not in [r["id"] for r in smuggled["topbar"]][:3],
       "a hand-written nav.json that pins Help to the strip has that row dropped")
    ok(nav.validate(smuggled) == "", "…and the rest of that layout still saves")


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
            srow = [r for r in moved["sidebar"] if r["id"] == "compose"][0]
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


# ── 7. THE LAST-THREE WINDOW, as journeys (Debi's ruling 2026-08-29) ─────────
def test_the_window_swaps():
    """The user story, executed: the strip is full at twelve, you open something from ⋯,
    it takes a slot and the oldest of the three goes back to ⋯ — and the nine pins never
    move, whatever you open."""
    m = nav.default_model()
    pins = nav.visible(m, "topbar")
    ok(len(nav.strip(m)) == 11, "the strip starts at eleven (nine pins + the seed)")

    ok(nav.mru_touch(m, "goose") is True, "opening Goose CLI from ⋯ moves the window")
    ok(nav.strip(m) == pins + ["goose", "compose", "voicebox"],
       "…it takes the FIRST swappable slot, straight after the pins")
    ok(len(nav.strip(m)) == nav.NAV_TOPBAR_MAX, "…and the strip is now exactly twelve")

    ok(nav.mru_touch(m, "comfy") is True, "open Generate too")
    ok(nav.strip(m) == pins + ["comfy", "goose", "compose"],
       "…and the LEAST RECENT of the three (Voicebox) fell off the end")
    ok("voicebox" not in nav.strip(m), "…it is off the strip, so it is back in ⋯")
    ok(nav.visible(m, "topbar") == pins,
       "…while not one pin moved — that is the half the ruling protects")

    ok(nav.mru_touch(m, "goose") is False,
       "opening a tab that is ALREADY in the window moves nothing (a strip that "
       "re-sorts under the pointer is the bug, not the feature)")
    ok(nav.strip(m) == pins + ["comfy", "goose", "compose"], "…so the strip is unchanged")
    ok(nav.mru_touch(m, "mc") is False, "…and neither does opening a PIN")

    # the strip can never exceed twelve, whatever you open, however often
    for eid in ["gooseui", "chat", "models", "caps", "voicebox", "compose", "music",
                "aider", "nope", "", None, 7]:
        nav.mru_touch(m, eid)
        ok(len(nav.strip(m)) <= nav.NAV_TOPBAR_MAX,
           f"the strip stays inside twelve after opening {eid!r}")
        ok(nav.visible(m, "topbar") == pins, f"…and the pins are untouched after {eid!r}")
    ok(nav.validate(m) == "", "…and the model is still saveable throughout")
    # MUSIC CLASSIC is the tab no bar may hold — it still reaches the strip.
    m2 = nav.default_model()
    ok(nav.mru_touch(m2, "music") is True and "music" in nav.strip(m2),
       "Music Classic has no row anywhere and STILL reaches the strip, through the "
       "window — which is the whole reason `can_tab` is not `can_show`")
    ok(not any(r["id"] == "music" for r in m2["topbar"] + m2["sidebar"]),
       "…without ever becoming a row")
    # a hand-written window full of junk cannot break the strip
    for junk in [None, "x", 7, ["nope", "logs", "help", "mc", "mc", 3, {"id": "goose"}],
                 [], {"a": 1}]:
        got = nav.normalize({"topbar": [{"id": "mc"}], "mru": junk})
        ok(len(nav.strip(got)) <= nav.NAV_TOPBAR_MAX,
           f"normalize({junk!r}) still yields a strip inside the cap")
        ok(all(nav.can_tab(i) for i in got["mru"]),
           f"…and a window of only real tabs ({got['mru']})")


def test_music_is_one_door():
    """Debi's consolidation ruling, executed on a saved layout: ONE Music row and ONE
    Music tab, the row lands where Music was rather than at the bottom, and the Classic
    surface is still reachable."""
    saved = {"v": nav.MODEL_V,
             "sidebar": [{"id": i, "pinned": True} for i in
                         ["mc", "chat", "models", "music", "aider", "loffice", "caps",
                          "logs", "odysseus", "hermes", "voicestudio", "voicebox",
                          "comfyui", "unsloth", "opencode"]],
             "topbar": [{"id": i, "pinned": True} for i in
                        ["mc", "hermes", "unsloth", "opencode", "odysseus",
                         "voicestudio", "comfyui", "aider", "loffice", "music",
                         "voicebox"]]}
    m = nav.repair(nav.normalize(saved))
    side = [r["id"] for r in m["sidebar"]]
    ok(side.count("compose") == 1 and "music" not in side,
       "the saved `music` row IS the Music row — one row, not two")
    ok(side.index("compose") == 3,
       "…and it is IN PLACE, at the position Music held (not appended under Components)")
    ok(nav.strip(m)[9] == "compose",
       "…and on the strip it holds Music's slot, tenth, exactly as before")
    ok("music" not in nav.strip(m), "…with no second Music tab drawn")
    ok(nav.validate(m) == "", "…and the migrated layout saves")
    # a layout that already carries BOTH must not end up with two rows for one job
    both = {"v": nav.MODEL_V,
            "sidebar": [{"id": "chat"}, {"id": "music"}, {"id": "compose"}],
            "topbar": [{"id": "mc"}, {"id": "music"}, {"id": "compose"}]}
    m2 = nav.normalize(both)
    for bar in nav.BARS:
        ok([r["id"] for r in m2[bar]].count("compose") == 1,
           f"a layout naming BOTH ids yields exactly one row on the {bar}")
    sb = [r["id"] for r in m2["sidebar"]]
    ok(sb.index("chat") < sb.index("compose") < sb.index("comfy"),
       "…keeping the EARLIER of the two positions (where they had put `music`) rather "
       "than the later one, with only default-order neighbours filled in around it")


def test_window_route_live():
    """POST /api/nav/mru against the real app, on a temp ROOT."""
    try:
        from fastapi.testclient import TestClient
    except Exception as e:                                       # noqa: BLE001
        print(f"  (skipped live window route — no TestClient: {e})")
        return
    import warnings
    warnings.filterwarnings("ignore")
    from bridge import app as A
    client = TestClient(A.app)
    with tempfile.TemporaryDirectory() as td:
        old = A.ROOT
        A.ROOT = Path(td)
        try:
            body = client.get("/api/nav").json()
            ok(body["strip"] == nav.strip(body["nav"]),
               "GET /api/nav carries the STRIP the shell draws, derived once")
            ok(body["max_pins"] == nav.NAV_TOPBAR_PINS
               and body["max_mru"] == nav.NAV_TOPBAR_MRU,
               "…and both halves of the 9+3 rule, for the panel to word its editor with")
            gen0 = body["gen"]
            r = client.post("/api/nav/mru", json={"id": "goose"})
            ok(r.status_code == 200 and r.json()["moved"] is True,
               "opening a tab that is not on the strip moves the window")
            ok(r.json()["strip"][9] == "goose", "…into the first swappable slot")
            ok(r.json()["gen"] == gen0 + 1, "…and moves the generation the shell polls")
            ok(json.load(open(nav.nav_path(td)))["mru"][0] == "goose",
               "…and it PERSISTED (this survives a relaunch — the old tempShown did not)")
            r = client.post("/api/nav/mru", json={"id": "goose"})
            ok(r.json()["moved"] is False and r.json()["gen"] == gen0 + 1,
               "…and opening it again writes nothing and does not move the generation")
            r = client.post("/api/nav/mru", json={"id": "hermes"})
            ok(r.json()["moved"] is False, "opening a PIN is not window business either")
            for bad in [{"id": "nope"}, {"id": ""}, {}, {"id": 7}]:
                r = client.post("/api/nav/mru", json=bad)
                ok(r.status_code in (200, 400) and not r.json().get("moved"),
                   f"a junk swap ({bad}) is refused or ignored, never a 500")
            r = client.post("/api/nav/mru", data="not json")
            ok(r.status_code == 400, "…and a body that is not json is 400, not a 500")
            ok(nav.validate(nav.read(td)) == "",
               "…and after all of it the saved layout is still valid")
        finally:
            A.ROOT = old


for fn in (test_registry, test_normalize, test_validate, test_repair,
           test_persistence, test_wiring, test_help_entry,
           test_the_window_swaps, test_music_is_one_door, test_window_route_live,
           test_routes_live):
    fn()

if FAILS:
    print(f"\nFAILED {len(FAILS)} of {CHECKS[0]}:")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print(f"\nnav model: {CHECKS[0]} checks passed")
