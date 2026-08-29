"""NAV — which entries appear on the sidebar and on the native tab strip, in what
order (FABLE-STUDIO-PHASE2-SPEC §A, 2026-08-21).

The shape is Unsloth's, because it is the right one: ONE list per bar of
`{id, pinned}` where **array order IS render order** (plus, since Debi's 2026-08-29
9+3 ruling, one flat `mru` list of ids — the tab strip's swappable last three; see
DEFAULT_MRU and `strip`). There is no separate
"position" field to fall out of step with the list, and hiding an entry keeps its
place in the order, so un-hiding it puts it back where it was rather than at the end.

Three parties read this file and they must agree:

  • the PANEL renders the sidebar from it (and owns the Appearance editor),
  • the SHELL (app/main.swift) rebuilds the native tab strip from the `topbar` list —
    which is the whole reason this lives on DISK and not only in localStorage, since
    an AppKit shell cannot read a web page's localStorage,
  • this module is the AUTHORITY: the panel's copy of the id table is a mirror and a
    test asserts the two agree.

`nav.json` carries PREFERENCES ONLY — ids and booleans. Every fact about an entry
(its label, its icon, its URL, its port) stays where it belongs: the panel owns the
labels, the shell owns the URLs. So a pin file can never carry a stale port.

STRICT ON THE WIRE, FORGIVING ON DISK. `normalize` + `validate` refuse a bad POST
with a reason the user can act on; `read` repairs the same problems silently, because
a hand-edited (or older, or newer) nav.json must never be able to stop the panel
booting.
"""
import json
import os

# ── the registry ─────────────────────────────────────────────────────────────
# `bars` is where an entry is ALLOWED to appear, which is a capability, not a
# preference:
#   • a VIEW can be a native tab only because of the `?solo=<view>` pattern, so a
#     view with no solo surface (Logs is a DIALOG, not a view) is sidebar-only;
#   • every component/lane tab can also be a sidebar row, because clicking one asks
#     the shell to switch tabs (the switchTab bridge) — and in a plain browser it
#     degrades to Mission Control / the page's own URL.
# `kind` only groups the sidebar ("Workspace" vs "Components"); it carries no rules.
NAV_ENTRIES = (
    {"id": "mc",          "kind": "view",      "bars": ("sidebar", "topbar")},
    {"id": "chat",        "kind": "view",      "bars": ("sidebar", "topbar")},
    {"id": "models",      "kind": "view",      "bars": ("sidebar", "topbar")},
    # MUSIC CLASSIC — the ORIGINAL Music view, `?solo=music`. Its code is untouched and
    # its surface is untouched; what changed at the music-consolidation slice (Debi's
    # ruling 2026-08-29, "ONE door, both looks") is only how you REACH it.
    #
    # ⚠️ `bars: ()` — DECLARED, ALLOWED ON NEITHER BAR, AND THAT IS THE WHOLE RULING.
    # Debi asked for ONE Music row and ONE Music tab: two rows for one job is the thing
    # being removed. This entry stays in the registry because it is still a REAL surface
    # with a real tab (`Music Classic` in app/main.swift, loading `?solo=music`) — reached
    # from the switcher in the header of the Studio page, and from the Classic page's own
    # switcher back. An empty `bars` is a positive statement, not an omission: "this build
    # knows the tab, and the navigation model may never place it on a bar."
    # `validate` skips an entry with no bars (there is no bar it could be hidden from),
    # `can_show` refuses it everywhere, so a saved layout naming it loses that ROW — which
    # is why SUPERSEDED below rewrites the row instead of dropping it.
    #
    # ⚠️ NO `tab_only` ANY MORE (v1.5.60, Debi's live follow-up): tab_only let Classic
    # into the last-three window and the ⋯ menu, where one click re-created the second
    # Music tab the ruling removed — she saw "Music Classic" standing on the strip
    # again within the hour. Classic is now IN-PLACE ONLY, everywhere: the Studio
    # header's dropdown navigates this same tab to `?solo=music`, the Classic page's
    # own chip navigates back, and ⌘K's row opens the in-panel view. can_tab() is
    # False, so mru_touch refuses it, the ⋯ menu never lists it, and the strip can
    # never draw it — there is exactly ONE Music tab in every state the model allows.
    {"id": "music",       "kind": "view",      "bars": ()},
    # MUSIC — the Studio (docs/FABLE-MUSIC-COMPOSE-SPEC.md): bridge/routers/music.py
    # serves bridge/panel/compose.html at /compose and drives the SAME /api/music/*
    # routes the Classic view drives. A LANE for `comfy`'s reason: it is our own page,
    # not a service with a port and a lifecycle, so it has no Mission Control card.
    #
    # ⚠️ THE ID IS STILL `compose` AND IT DOES NOT CHURN — the Goose CLI rule verbatim:
    # internal names do not churn with a display name. `compose` is the ROUTE (/compose),
    # the tab id and the row in every saved nav.json; the LABEL the panel shows became
    # "Music" at the consolidation slice because this is now the one Music door, opening
    # on the Studio look by default with Classic one header-dropdown away.
    {"id": "compose",     "kind": "lane",      "bars": ("sidebar", "topbar")},
    # GENERATE (v1.5.36's first-party ComfyUI surface — bridge/routers/comfy.py serves
    # bridge/panel/comfy.html at /comfy). A LANE for aider's and loffice's reason: it is
    # OUR page, not a service with its own port and lifecycle, so it has no Mission
    # Control card of its own and had NO navigation entry at all until this slice —
    # reachable only by typing the URL. It sits beside Music on purpose: those two are
    # MOT Deck's own generate surfaces (sound, then image/video) and read as a pair.
    #
    # ⚠️ THIS IS NOT THE `comfyui` ENTRY BELOW, AND IT DOES NOT REPLACE IT. `comfyui` is
    # the COMPONENT: upstream's own stock web UI on :8188, with a Mission Control card
    # and a start/stop lifecycle. `comfy` is our surface, which drives that same engine
    # through /api/comfy/*. Two entries because there are two real surfaces; the id is
    # the ROUTE (/comfy) while the label the panel shows is "Generate", which is what
    # the page does for the user.
    {"id": "comfy",       "kind": "lane",      "bars": ("sidebar", "topbar")},
    {"id": "aider",       "kind": "lane",      "bars": ("sidebar", "topbar")},
    # GOOSE CLI (docs/research/2026-08-28-goose-source-verify.md) — a LANE, not a
    # component, for aider's exact reason: it has no port, no daemon and no browser UI of
    # its own, so it never appears on Mission Control. It runs in a pty inside its own
    # tab.
    #
    # ⚠️ THE ID IS `goose` AND IT DOES NOT CHURN. The DISPLAY name became "Goose CLI" at
    # the Goose UI slice (Debi's naming ruling 2026-08-29) because there are now two
    # goose surfaces and "Goose" alone stopped saying which one is meant. Renaming the id
    # would invalidate every saved nav.json, the pty route /api/pty/goose, data/goose.pid
    # and the memory ledger's handle on it — all for a wordmark. LOffice's rule verbatim:
    # internal names do not churn with a display name.
    {"id": "goose",       "kind": "lane",      "bars": ("sidebar", "topbar")},
    # GOOSE UI (v1.5.40's embed — bridge/routers/gooseui.py serves goose Desktop's own
    # renderer at /gooseui/ against a goosed WE supervise). A LANE for `goose`'s reason
    # AND one of its own: the goosed it drives is started by the page itself and lives
    # only while the tab does, so there is nothing for a Mission Control card to start.
    #
    # ⚠️ IT DOES NOT REPLACE `goose`, AND BOTH ARE REQUIRED — the comfy/comfyui and
    # music/compose pairs' argument a third time, and here it is Debi's explicit ruling
    # (ledger S14): the terminal lane STAYS. They are two surfaces onto one product with
    # SEPARATE homes and SEPARATE sessions (data/goose/home vs data/goose/ui-home),
    # proven in v1.5.40 to run simultaneously. Dropping `goose` takes the terminal away;
    # dropping `gooseui` leaves the embedded surface reachable only by typing a URL. It
    # sits DIRECTLY AFTER Goose CLI because they are one product done two ways.
    {"id": "gooseui",     "kind": "lane",      "bars": ("sidebar", "topbar")},
    {"id": "loffice",     "kind": "lane",      "bars": ("sidebar", "topbar")},
    {"id": "caps",        "kind": "view",      "bars": ("sidebar", "topbar")},
    # Logs is a DIALOG. It has no view id, so it can never be a solo tab — and it is
    # the one entry that may be hidden everywhere, because ⌘K ("Show bridge logs")
    # reaches it regardless. Every other entry is protected by `validate`.
    {"id": "logs",        "kind": "view",      "bars": ("sidebar",), "always": True},
    # HELP (roadmap §2.4) — the in-app explainers, rendered from docs/USER-EXPLAINERS.md
    # by the panel's own tiny markdown renderer. It sits directly under Logs.
    #
    # SIDEBAR-ONLY, like Logs, but NOT for Logs' reason. Logs is sidebar-only because it
    # is a dialog with no view at all; Help IS a real panel view. It is sidebar-only
    # because it is a reference surface you consult and leave rather than a workspace
    # you keep a tab on — and because the strip is at 11 of Debi's 12 pins already, so
    # the honest default is "not a tab". The panel's SOLO_VIEWS derivation therefore
    # excludes it EXPLICITLY (a view with no tab home has no ?solo= surface either),
    # rather than the exclusion happening by accident of `view: null`.
    #
    # `always` for exactly Logs' reason: ⌘K ("Help") reaches it whatever the sidebar
    # says, so hiding the row has to be allowed to be a real choice.
    {"id": "help",        "kind": "view",      "bars": ("sidebar",), "always": True},
    # API (ledger S32) — the local API ACCESS surface: the base URL an app's own
    # Add-Provider form wants, the named keys it consumes, and the request log.
    #
    # ⚠️ SIDEBAR-ONLY, AND NOT `tab_only` EITHER — v1.5.60's Music lesson, applied
    # BEFORE the mistake rather than after it. `tab_only` let Music Classic into the
    # last-three window and the ⋯ menu, where one click re-created the tab the ruling
    # had just removed; Debi saw it standing on her strip within the hour. This entry
    # is therefore declared with `bars: ("sidebar",)` and NOTHING else: `can_tab` is
    # False, `mru_touch` refuses it, the ⋯ menu never lists it and the strip can never
    # draw it. Debi asked for "an Unsloth-style API page, like Capabilities, only on
    # the side panel" — the shape she named is Help's, not Capabilities' (`caps` is
    # tab-eligible), so the fence is written against the shape and not the example
    # (doctrine 8b: an example is the floor, not the boundary).
    #
    # It is a REFERENCE surface for the same reason Help is: you come here to copy a
    # base URL or mint a key, paste it into another app, and leave. It is not a
    # workspace you keep a tab on, and the strip is at 11 of 12 pins besides.
    #
    # `always` for exactly Logs' and Help's reason, and it is load-bearing here too:
    # ⌘K ("API keys") reaches it whatever the sidebar says, which is what makes hiding
    # the row a safe choice rather than a way to lose the only revoke button.
    {"id": "api",         "kind": "view",      "bars": ("sidebar",), "always": True},
    {"id": "odysseus",    "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "hermes",      "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "voicestudio", "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "voicebox",    "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "comfyui",     "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "unsloth",     "kind": "component", "bars": ("sidebar", "topbar")},
    {"id": "opencode",    "kind": "component", "bars": ("sidebar", "topbar")},
)
NAV_IDS = tuple(e["id"] for e in NAV_ENTRIES)

# THE DEFAULTS ARE TODAY'S LAYOUT, deliberately: a machine with no nav.json must look
# exactly like the build before this slice, so nothing moves until somebody customises
# it. The only additions are the two lanes Debi asked for (aider, loffice), which had
# no sidebar row at all and were therefore reachable only from the tab strip.
#
# ⚠️ `help` is APPENDED TO THE SIDEBAR IN PLACE (directly after `logs`) and not to the
# topbar at all, so the strip's saved layouts are untouched and no migration is needed:
# `normalize` appends a known id the caller omitted, so an EXISTING nav.json gains
# `help` at the tail of its sidebar list. That still renders directly under Logs, and
# not by luck: everything between `logs` and the tail of a saved layout is a COMPONENT,
# and renderSidebar draws components into their own group. The one visible consequence
# is that the Appearance editor lists Help last rather than ninth — which is the honest
# truth about where it sits in that user's saved order, so it is left alone rather than
# "fixed" by a migration that would move rows somebody may have arranged.
# That is the whole upgrade path: no `v` bump, no one-time migration.
DEFAULT_SIDEBAR = (
    ("mc", True), ("chat", True), ("models", True), ("compose", True),
    ("comfy", True),
    ("aider", True), ("goose", True), ("gooseui", True),
    ("loffice", True), ("caps", True), ("logs", True),
    ("help", True),
    # API (S32) — appended directly after Help by Help's OWN upgrade rule, and for the
    # same reason it worked there: `normalize` appends a known id the caller omitted, so
    # an EXISTING nav.json gains this row at the tail of its sidebar list, which renders
    # in the Workspace group directly under Help (everything between `logs` and the tail
    # of a saved layout is a COMPONENT, and renderSidebar draws components into their
    # own group). No `v` bump, no migration, nothing anybody arranged moves.
    ("api", True),
    ("odysseus", True), ("hermes", True), ("voicestudio", True),
    ("voicebox", True), ("comfyui", True), ("unsloth", True), ("opencode", True),
)
# …and this is the shell's `tabs` table, in order, followed by the three views that CAN
# be pinned as solo tabs but are not by default.
#
# ⚠️ v1.5.26 — DEBI'S ORDER. The strip is now read left-to-right as "the deck, then the
# three agent/model lanes you actually work in, then everything else":
#   MOT Deck · Hermes · Unsloth · OpenCode · Odysseus · VoiceStudio · ComfyUI · Aider ·
#   LOffice · Music · Voicebox
# The SET is unchanged (the same eleven ids) — only the order moved, so no entry gained
# or lost a home and `validate` has nothing new to say. The same list appears in
# app/main.swift (`navDefaultTopbar`) and in the panel (`NAV_DEFAULT_TOPBAR`); all three
# are asserted to agree by test_nav_model.py, because a disagreement means the strip and
# the panel's Appearance editor describe different windows.
#
# ⚠️ v1.5.49 — THE 9 + 3 STRIP (Debi's ruling 2026-08-29). The strip is still at most
# NAV_TOPBAR_MAX = 12 tabs, but they are no longer 12 pins: the FIRST NINE are the
# user's own pinned order and never move, and the LAST THREE are a most-recently-opened
# WINDOW over everything else (DEFAULT_MRU below is its seed). So the pinned prefix here
# is NINE, and the two entries that used to be pinned tenth and eleventh — the Music
# surface and Voicebox — are declared unpinned and seeded into the window instead. The
# strip a fresh machine draws is therefore the SAME ELEVEN TABS, in the same order; what
# changed is that the last two of them can now be swapped out by opening something else
# rather than being fixed forever.
DEFAULT_TOPBAR = (
    ("mc", True), ("hermes", True), ("unsloth", True), ("opencode", True),
    ("odysseus", True), ("voicestudio", True), ("comfyui", True), ("aider", True),
    ("loffice", True),
    ("compose", False), ("voicebox", False),
    ("chat", False), ("models", False), ("caps", False),
    # ⚠️ GOOSE IS DECLARED HERE BUT NOT PINNED, AND THAT IS THE DELIBERATE CHOICE.
    # The strip is at 11 of NAV_TOPBAR_MAX=12 pins in Debi's arranged order; a twelfth
    # would fill the last slot on a FRESH machine while doing nothing at all on Debi's
    # (her nav.json is already stamped v2, so `migrate` returns early and `normalize`
    # appends a new id UNPINNED regardless). Declaring it unpinned means both machines
    # agree: Goose is one sidebar click or one ⋯ away, and pinning it is a choice the
    # Appearance editor can make — rather than a default that quietly spends the last pin.
    ("goose", False),
    # ⚠️ AND `comfy` (Generate) IS DECLARED-BUT-NOT-PINNED FOR EXACTLY GOOSE'S REASON.
    # The pinned prefix is still 11 of NAV_TOPBAR_MAX=12; there is ONE free pin, and it
    # is not this slice's to spend — goose is already waiting behind ⋯ for it, and a
    # default that quietly fills the last slot on a fresh machine while doing nothing on
    # Debi's (her nav.json is stamped v2, so `migrate` returns early and `normalize`
    # appends a new id UNPINNED regardless) makes the two machines disagree. Generate is
    # one sidebar click or one ⋯ away, and the Appearance editor can pin it by choice.
    ("comfy", False),
    # ⚠️ AND `gooseui` (Goose UI) IS DECLARED-BUT-NOT-PINNED, A FOURTH TIME, AND THE
    # ARGUMENT HAS ONLY GOT STRONGER. The pinned prefix is STILL 11 of NAV_TOPBAR_MAX=12
    # — the one free pin stays free — and this lane is an ALTERNATIVE SURFACE onto the
    # same product as `goose`, which is itself already waiting behind ⋯ for that pin.
    # Pinning the embedded surface while the terminal one is unpinned would silently
    # declare a winner between two lanes Debi's ruling says coexist. One sidebar click
    # or one ⋯ away, and the Appearance editor can pin it by choice.
    ("gooseui", False),
)
# THE ORDER AS IT SHIPPED BEFORE v1.5.26, frozen. This is not history for its own sake:
# it is the ONLY way to tell "this user never customised their strip" from "this user
# chose an order that happens to be short one tab" — see `migrate` below. Never edit it;
# if the default moves again, add the next frozen tuple beside it.
DEFAULT_TOPBAR_V1 = (
    ("mc", True), ("odysseus", True), ("hermes", True), ("voicestudio", True),
    ("voicebox", True), ("comfyui", True), ("unsloth", True), ("music", True),
    ("aider", True), ("loffice", True), ("opencode", True),
    ("chat", False), ("models", False), ("caps", False),
)
DEFAULTS = {"sidebar": DEFAULT_SIDEBAR, "topbar": DEFAULT_TOPBAR}
BARS = ("sidebar", "topbar")

# ── THE LAST-THREE WINDOW (Debi's ruling 2026-08-29) ─────────────────────────
# "Keep the strip at twelve, but the last three are replaceable/swappable."
#
# `mru` is the window's contents, MOST-RECENTLY-OPENED FIRST, and it is the third list
# in nav.json. It is a PREFERENCE like the other two (ids only, no facts about an
# entry), it is written by the same atomic writer, and an older build that has never
# heard of it simply ignores the key — which is why this is an ADDITIVE change with no
# `v` bump and no migration: MODEL_V stays 2.
#
# THE RULE, stated the way a user would: opening a tab that is not on the strip puts it
# straight after your pins and pushes the others right; the third one falls off the end
# into ⋯. Opening a tab that is ALREADY in the window moves NOTHING — it is already in
# front of you, and a strip that re-sorts itself under the pointer is the bug this rule
# is supposed to prevent, not a feature. So "least recent" means least recently OPENED
# FROM ELSEWHERE, which is exactly what the eviction is for.
#
# THE SEED is the two entries that were pinned tenth and eleventh before this slice, in
# their old order, so a fresh machine's strip is unchanged and Debi's own (whose saved
# layout `repair` trims from eleven pins to nine) keeps showing exactly what it showed.
DEFAULT_MRU = ("compose", "voicebox")

# ── SUPERSEDED IDS ───────────────────────────────────────────────────────────
# An id whose ROW is now another entry's row. The saved layout is rewritten IN PLACE —
# same position, same pinned flag — rather than having the old row dropped (which
# `can_show` would do, silently, because the superseded entry is allowed on no bar) and
# the new one appended somewhere else.
#
# `music` → `compose` is the music-consolidation slice (Debi 2026-08-29): ONE Music door,
# opening on the Studio look, with Classic one header-dropdown away. Every saved nav.json
# in existence names `music` — pinned on the strip and on the sidebar — so a drop would
# have taken the Music tab off Debi's strip and put a row labelled Music at the BOTTOM of
# her Workspace group (the A8/S19 tail-append, third instance). In place is the only
# honest answer.
SUPERSEDED = {"music": "compose"}

# Mission Control is FIRST and PINNED on the tab strip by construction, not by taste:
# `panelTab = 0` in the shell is the bridge-wait surface, the file-drop target and the
# page the launch screen writes into.
FIXED_TOP = "mc"
# Chat is PINNED on the sidebar (it cannot be hidden). ⚠️ deliberately NOT forced to
# index 0: the spec says "fixed first on the sidebar", but Mission Control is first
# there today and Debi's rule for this slice is that a fresh install must look
# identical until customised. Pinning it is the half that matters — the chat can never
# become unreachable — and the position stays the user's.
FIXED_SIDE = "chat"

# ⚠️ DEBI'S 12 IS UNCHANGED; WHAT THE 12 ARE MADE OF IS NOT (ruling 2026-08-29). The
# strip shows at most twelve tabs — 9 STABLE PINS in the user's own order, then a
# 3-SLOT most-recently-opened WINDOW. Before this slice all twelve were pins and the
# shell then appended every tab you opened from ⋯ or from a sidebar row on top of them
# for the session, which is how a "12 max" strip crept to fourteen and fifteen.
NAV_TOPBAR_PINS = 9        # the stable prefix: the user's pinned order, never moved
NAV_TOPBAR_MRU = 3         # the swappable window at the end
NAV_TOPBAR_MAX = NAV_TOPBAR_PINS + NAV_TOPBAR_MRU   # 12 — Debi's ruling, unchanged
NAV_FILE = "nav.json"      # data/nav.json
# The MODEL version written into nav.json (and mirrored into the panel's localStorage
# copy). 1 = every build up to v1.5.24. 2 = the default-topbar reorder, which needs a
# stamp so the one-time migration below runs exactly once per machine.
MODEL_V = 2


def entry(eid) -> "dict | None":
    for e in NAV_ENTRIES:
        if e["id"] == eid:
            return e
    return None


def can_show(eid, bar) -> bool:
    """May this entry be a ROW on this bar? The customisation question."""
    e = entry(eid)
    return bool(e and bar in e["bars"])


def can_tab(eid) -> bool:
    """May the tab strip draw this entry AT ALL? A superset of `can_show(id, "topbar")`:
    an entry may have a native tab without ever being allowed a row (`tab_only`, today
    Music Classic). This is the question the last-three window asks, because that window
    is over TABS, not over rows."""
    e = entry(eid)
    return bool(e and ("topbar" in e["bars"] or e.get("tab_only")))


def default_model() -> dict:
    m = {b: [{"id": i, "pinned": p} for i, p in DEFAULTS[b]] for b in BARS}
    m["mru"] = list(DEFAULT_MRU)
    return m


def _rows(raw, bar) -> list:
    """The rows a caller supplied for one bar, cleaned of everything that cannot be
    a row. TOTAL: any shape that is not a list of {id,pinned} (or bare id strings)
    contributes nothing rather than raising — this arrives as JSON from a web page."""
    src = raw.get(bar) if isinstance(raw, dict) else None
    out, seen = [], set()
    if not isinstance(src, list):
        return out
    for r in src:
        if isinstance(r, str):
            rid, pin = r, True
        elif isinstance(r, dict):
            rid, pin = r.get("id"), r.get("pinned", True)
        else:
            continue
        if not isinstance(rid, str):
            continue
        # A superseded id IS its successor's row, in place, with its pin. If the layout
        # already carries the successor too (a machine that saw both rows), the earlier
        # of the two wins the POSITION and the pins are OR-ed by `seen` skipping the
        # second — never two rows for one entry.
        rid = SUPERSEDED.get(rid, rid)
        if rid in seen:
            continue
        if not can_show(rid, bar):          # unknown id, or not allowed on this bar
            continue
        seen.add(rid)
        out.append({"id": rid, "pinned": bool(pin)})
    return out


def _default_pos(bar, rid, rows) -> int:
    """Where a known id the caller OMITTED belongs in their saved layout: directly after
    the nearest entry that precedes it in the DEFAULT order and is actually present.

    ⚠️ THIS IS LEDGER A8 / S19 (three sightings: Generate landing under Help, Compose
    under Help, Goose UI under Generate). Appending at the TAIL was chosen deliberately
    for Help — which wants the tail, because it renders directly under Logs — and then
    applied to every entry after it, so every new row landed at the BOTTOM of a
    customised sidebar while sitting where it was designed to sit on a fresh one. The
    fix reorders NOTHING the user placed: it only chooses an insertion point, and it
    falls back to the tail when no default-order predecessor survives in their layout.
    """
    have = {r["id"]: i for i, r in enumerate(rows)}
    order = [i for i, _p in DEFAULTS[bar]]
    if rid not in order:
        return len(rows)
    at = order.index(rid)
    for prev in reversed(order[:at]):
        if prev in have:
            return have[prev] + 1
    # No predecessor of theirs survives — so look FORWARD and land BEFORE the nearest
    # successor instead. Without this the FIRST entry in the default order (`mc`) would
    # tail-append onto a layout that had lost it: the row designed to be first arriving
    # last is the same bug this function exists to fix, just at the other end.
    for nxt in order[at + 1:]:
        if nxt in have:
            return have[nxt]
    return len(rows)


def normalize(raw) -> dict:
    """A well-formed model from anything. Unknown ids are DROPPED (a nav.json written
    by a newer build must not resurrect an entry this build cannot render), and known
    ids the caller omitted are APPENDED in their default order — so adding an entry to
    the registry shows it to everyone without anybody re-doing their layout.

    An appended entry is never pinned onto a full strip: growing the registry must not
    be able to invalidate a model that was valid a moment ago.
    """
    out = {}
    for bar in BARS:
        rows = _rows(raw, bar)
        have = {r["id"] for r in rows}
        pinned = sum(1 for r in rows if r["pinned"])
        for rid, pin in DEFAULTS[bar]:
            if rid in have:
                continue
            if bar == "topbar" and pin and pinned >= NAV_TOPBAR_PINS:
                pin = False
            rows.insert(_default_pos(bar, rid, rows), {"id": rid, "pinned": bool(pin)})
            have.add(rid)
            if pin:
                pinned += 1
        out[bar] = rows
    # Mission Control first + pinned on the strip.
    top = out["topbar"]
    mc = [r for r in top if r["id"] == FIXED_TOP]
    if mc:
        mc[0]["pinned"] = True
        out["topbar"] = mc + [r for r in top if r["id"] != FIXED_TOP]
    for r in out["sidebar"]:
        if r["id"] == FIXED_SIDE:
            r["pinned"] = True
    out["mru"] = _mru(raw, out["topbar"])
    return out


def _mru(raw, topbar) -> list:
    """The last-three window, cleaned. TOTAL, like `_rows`: anything that is not an id
    this build can put on the strip contributes nothing.

    An id that is already in the PINNED PREFIX is dropped from the window rather than
    shown twice — the window is "everything else", by definition. An ABSENT `mru` key
    (every nav.json written before this slice) seeds the default window, which is what
    makes the upgrade invisible: the two entries that used to be pinned tenth and
    eleventh stay on the strip.
    """
    src = raw.get("mru") if isinstance(raw, dict) else None
    if not isinstance(src, list):
        src = list(DEFAULT_MRU)
    pins = set(_pins(topbar))
    out, seen = [], set()
    for rid in src:
        if isinstance(rid, dict):                       # tolerate a {id: …} row shape
            rid = rid.get("id")
        if not isinstance(rid, str):
            continue
        # ⚠️ NO SUPERSEDE HERE, DELIBERATELY. SUPERSEDED is about ROWS — "this saved row
        # is now that entry's row". The window is about TABS, and `music` in it means
        # the Music Classic TAB, which still exists and is exactly what an off-bar
        # entry uses this list for. Rewriting it would silently swap the look the user
        # last opened for the other one.
        if rid in seen or rid in pins or not can_tab(rid):
            continue
        seen.add(rid)
        out.append(rid)
        if len(out) >= NAV_TOPBAR_MRU:
            break
    return out


def _pins(topbar) -> list:
    """The STABLE prefix: the first NAV_TOPBAR_PINS pinned ids, in order. `validate`
    refuses more than that on the wire and `repair` trims a file down to it, so this
    slice is normally the whole pinned list — the slice is the belt to that braces."""
    return [r["id"] for r in (topbar or []) if r.get("pinned")][:NAV_TOPBAR_PINS]


def strip(model) -> list:
    """THE TAB STRIP, in order: the stable pins, then the last-three window. This is the
    ONE derivation the shell draws from — never `visible(model, "topbar")` alone, which
    is only the pinned half."""
    pins = _pins(model.get("topbar"))
    win = [i for i in (model.get("mru") or []) if i not in pins][:NAV_TOPBAR_MRU]
    return pins + win


def mru_touch(model, eid) -> bool:
    """Open `eid` from somewhere that is not the strip (the ⋯ menu, a sidebar row).
    True when the window MOVED — the caller then persists and bumps the generation.

    Nothing moves when the entry is already on the strip: a pinned tab is not window
    business, and an entry already IN the window is already in front of you (re-sorting
    the strip under the pointer is the bug, not the feature)."""
    if not isinstance(eid, str) or not can_tab(eid):
        return False
    if eid in strip(model):
        return False
    win = [i for i in (model.get("mru") or []) if isinstance(i, str) and i != eid]
    model["mru"] = ([eid] + win)[:NAV_TOPBAR_MRU]
    return True


def validate(model) -> str:
    """'' when the model may be SAVED, else the reason, phrased for the user.

    Two rules, and both exist to stop a customisation from removing something:
      1. nothing may be hidden on every bar it is allowed on (the exception is
         declared per entry — `always` — and today only Logs carries it, because ⌘K
         reaches it);
      2. at most NAV_TOPBAR_PINS pinned tabs — the strip is a fixed-width centred
         control and past NAV_TOPBAR_MAX = 12 it collides with the ⫽ button, and since
         Debi's 2026-08-29 ruling the last three of those twelve are not pins at all but
         the most-recently-opened window. So the number a user may PIN is nine; the
         message says so and says where the other three went, because "at most 9" with
         no explanation reads as the cap having been cut.
    """
    pins = {b: {r["id"]: bool(r["pinned"]) for r in model.get(b) or []} for b in BARS}
    for e in NAV_ENTRIES:
        if e.get("always"):
            continue
        bars = [b for b in BARS if b in e["bars"]]
        if bars and not any(pins.get(b, {}).get(e["id"]) for b in bars):
            return ("%s would be hidden everywhere — keep it on the sidebar or on the "
                    "tabs." % e["id"])
    n = sum(1 for v in pins.get("topbar", {}).values() if v)
    if n > NAV_TOPBAR_PINS:
        return ("at most %d tabs can be pinned to the top strip (you asked for %d) — "
                "the last %d of its %d slots follow what you open. Unpin one first."
                % (NAV_TOPBAR_PINS, n, NAV_TOPBAR_MRU, NAV_TOPBAR_MAX))
    return ""


def repair(model) -> dict:
    """The forgiving half, used when READING a file (never on the wire): fix exactly
    what `validate` would refuse, quietly, so a bad file cannot stop the panel or the
    shell from starting. Re-pin an entry that would be unreachable; drop pins off the
    END of the strip past the cap (the end, so the user's leading choices survive).

    ⚠️ AND THAT LAST RULE IS THE 9+3 UPGRADE PATH, WHICH IS WHY IT DOES NOT JUST UNPIN.
    Every nav.json in existence carries ELEVEN pinned tabs; trimming to nine and stopping
    would take two tabs off the user's strip on the next boot with nothing said. The ones
    trimmed are pushed to the FRONT of the last-three window instead, in their strip
    order, so the strip still draws exactly what it drew — the two tabs are simply
    swappable now instead of fixed. No `v` bump, no one-time migration: the trim is
    idempotent (a second read has nine pins and nothing to trim)."""
    pins = {b: {r["id"]: bool(r["pinned"]) for r in model.get(b) or []} for b in BARS}
    for e in NAV_ENTRIES:
        if e.get("always"):
            continue
        bars = [b for b in BARS if b in e["bars"]]
        if bars and not any(pins.get(b, {}).get(e["id"]) for b in bars):
            home = "sidebar" if "sidebar" in bars else bars[0]
            for r in model.get(home) or []:
                if r["id"] == e["id"]:
                    r["pinned"] = True
    n, demoted = 0, []
    for r in model.get("topbar") or []:
        if not r["pinned"]:
            continue
        n += 1
        if n > NAV_TOPBAR_PINS:
            r["pinned"] = False
            demoted.append(r["id"])
    if demoted:
        win = [i for i in (model.get("mru") or []) if i not in demoted]
        model["mru"] = (demoted + win)[:NAV_TOPBAR_MRU]
    return model


# ── migration ────────────────────────────────────────────────────────────────
# ⚠️ THE TRAP THIS EXISTS TO ANSWER (v1.5.26). Changing DEFAULT_TOPBAR changes what a
# FRESH machine gets — and nothing else. Every machine that has ever opened the panel
# has a data/nav.json (the panel writes one the first time it syncs), so on those
# machines the SAVED order silently wins and the reorder would appear to have done
# nothing at all. That is the failure mode: a shipped change that is invisible on the
# only machine that matters.
#
# The rule is the one a user would state themselves: if you never touched your strip,
# you get the new default; if you arranged it, your arrangement is yours and we do not
# touch it. "Never touched" is decidable EXACTLY — the saved topbar is byte-for-byte
# the old default, ids and pins, in order.
#
# It runs ONCE per machine: `read` stamps MODEL_V into the file afterwards whether or
# not the layout moved, so a user who LATER arranges their tabs into the old order is
# not migrated a second time.
def _topbar_rows(raw) -> list:
    """(id, pinned) pairs exactly as the file states them — no normalisation, because
    the comparison below has to be against what was WRITTEN, not against what we would
    repair it into."""
    src = raw.get("topbar") if isinstance(raw, dict) else None
    if not isinstance(src, list):
        return []
    out = []
    for r in src:
        if isinstance(r, str):
            out.append((r, True))
        elif isinstance(r, dict) and isinstance(r.get("id"), str):
            out.append((r["id"], bool(r.get("pinned", True))))
        else:
            return []                       # a shape we did not write → not our default
    return out


def migrate(raw) -> tuple:
    """(model_dict, moved). Total: anything unrecognisable comes back untouched."""
    if not isinstance(raw, dict):
        return raw, False
    try:
        ver = int(raw.get("v") or 1)
    except Exception:                                   # noqa: BLE001
        ver = 1
    if ver >= MODEL_V:
        return raw, False
    if _topbar_rows(raw) != [(i, bool(p)) for i, p in DEFAULT_TOPBAR_V1]:
        return raw, False                   # customised — leave it exactly alone
    out = dict(raw)
    out["topbar"] = [{"id": i, "pinned": bool(p)} for i, p in DEFAULT_TOPBAR]
    return out, True


# ── persistence ──────────────────────────────────────────────────────────────
def nav_path(root) -> str:
    return os.path.join(str(root), "data", NAV_FILE)


def read(root) -> dict:
    """Always a usable model. An absent, unreadable or junk file is the DEFAULT
    layout — the same thing a fresh machine gets."""
    try:
        with open(nav_path(root), encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:                                   # noqa: BLE001
        return default_model()
    if not isinstance(raw, dict):
        return default_model()
    raw, moved = migrate(raw)
    clean = normalize(raw)
    before = json.dumps(clean, sort_keys=True)
    model = repair(clean)
    # A file `repair` had to change is a file that should be written back — otherwise the
    # 11-pins→9+window trim (and every other repair) would be re-derived on every boot
    # and the file on disk would keep describing a layout this build does not draw. The
    # repair is idempotent, so this settles after exactly one write.
    repaired = json.dumps(model, sort_keys=True) != before
    # STAMP THE VERSION, migrated or not. Writing here is the one deliberate side effect
    # in a reader, and it is what makes the migration ONE-TIME rather than a rule that
    # re-fires forever: after this, `v` is MODEL_V and `migrate` returns early. A failure
    # to write is not a failure to read — the model is already correct in memory, and the
    # worst case is that the (idempotent) migration is attempted again next boot.
    try:
        stale = int(raw.get("v") or 1) < MODEL_V
    except Exception:                                   # noqa: BLE001
        stale = True
    if moved or stale or repaired:
        try:
            write(root, model)
        except Exception:                               # noqa: BLE001
            pass
    return model


def write(root, model) -> None:
    """Atomic (tmp + os.replace): the shell reads this file on its own schedule, and a
    half-written one would rebuild the tab strip from nothing."""
    p = nav_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"v": MODEL_V, "sidebar": model["sidebar"], "topbar": model["topbar"],
                   # ADDITIVE (no `v` bump): a build that predates the last-three window
                   # ignores this key, and this build seeds the default window when it is
                   # absent. Neither can clobber the other's saved layout.
                   "mru": model.get("mru") or []},
                  fh, indent=2)
    os.replace(tmp, p)


def visible(model, bar) -> list:
    """The ids to RENDER on one bar, in order. The shell's tab strip and the panel's
    sidebar are both exactly this call."""
    return [r["id"] for r in (model.get(bar) or []) if r.get("pinned")]


def hidden(model, bar) -> list:
    """The rest, in order — the UNPINNED rows.

    ⚠️ ON THE TOPBAR THIS IS NO LONGER THE ⋯ MENU. Since the 9+3 ruling the strip is
    `strip(model)`, so the overflow is "everything the registry knows that `strip` did
    not draw" — this list MINUS the last-three window. The shell derives it that way
    (registry − strip) and so must anything else that says "hidden tabs"."""
    return [r["id"] for r in (model.get(bar) or []) if not r.get("pinned")]
