"""NAV — which entries appear on the sidebar and on the native tab strip, in what
order (FABLE-STUDIO-PHASE2-SPEC §A, 2026-08-21).

The shape is Unsloth's, because it is the right one: ONE list per bar of
`{id, pinned}` where **array order IS render order**. There is no separate
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
    {"id": "music",       "kind": "view",      "bars": ("sidebar", "topbar")},
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
    # GOOSE (docs/research/2026-08-28-goose-source-verify.md) — a LANE, not a component,
    # for aider's exact reason: it has no port, no daemon and no browser UI of its own,
    # so it never appears on Mission Control. It runs in a pty inside its own tab.
    {"id": "goose",       "kind": "lane",      "bars": ("sidebar", "topbar")},
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
    ("mc", True), ("chat", True), ("models", True), ("music", True), ("comfy", True),
    ("aider", True), ("goose", True), ("loffice", True), ("caps", True), ("logs", True),
    ("help", True),
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
DEFAULT_TOPBAR = (
    ("mc", True), ("hermes", True), ("unsloth", True), ("opencode", True),
    ("odysseus", True), ("voicestudio", True), ("comfyui", True), ("aider", True),
    ("loffice", True), ("music", True), ("voicebox", True),
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

NAV_TOPBAR_MAX = 12        # Debi's ruling: at most 12 pinned tabs on the strip.
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
    e = entry(eid)
    return bool(e and bar in e["bars"])


def default_model() -> dict:
    return {b: [{"id": i, "pinned": p} for i, p in DEFAULTS[b]] for b in BARS}


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
        if not isinstance(rid, str) or rid in seen:
            continue
        if not can_show(rid, bar):          # unknown id, or not allowed on this bar
            continue
        seen.add(rid)
        out.append({"id": rid, "pinned": bool(pin)})
    return out


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
            if bar == "topbar" and pin and pinned >= NAV_TOPBAR_MAX:
                pin = False
            rows.append({"id": rid, "pinned": bool(pin)})
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
    return out


def validate(model) -> str:
    """'' when the model may be SAVED, else the reason, phrased for the user.

    Two rules, and both exist to stop a customisation from removing something:
      1. nothing may be hidden on every bar it is allowed on (the exception is
         declared per entry — `always` — and today only Logs carries it, because ⌘K
         reaches it);
      2. at most NAV_TOPBAR_MAX pinned tabs (Debi's ruling) — the strip is a fixed-width
         centred control and past that it collides with the ⫽ button.
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
    if n > NAV_TOPBAR_MAX:
        return ("at most %d tabs can be pinned to the top strip (you asked for %d) — "
                "unpin one first." % (NAV_TOPBAR_MAX, n))
    return ""


def repair(model) -> dict:
    """The forgiving half, used when READING a file (never on the wire): fix exactly
    what `validate` would refuse, quietly, so a bad file cannot stop the panel or the
    shell from starting. Re-pin an entry that would be unreachable; drop pins off the
    END of the strip past the cap (the end, so the user's leading choices survive)."""
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
    n = 0
    for r in model.get("topbar") or []:
        if not r["pinned"]:
            continue
        n += 1
        if n > NAV_TOPBAR_MAX:
            r["pinned"] = False
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
    model = repair(normalize(raw))
    # STAMP THE VERSION, migrated or not. Writing here is the one deliberate side effect
    # in a reader, and it is what makes the migration ONE-TIME rather than a rule that
    # re-fires forever: after this, `v` is MODEL_V and `migrate` returns early. A failure
    # to write is not a failure to read — the model is already correct in memory, and the
    # worst case is that the (idempotent) migration is attempted again next boot.
    try:
        stale = int(raw.get("v") or 1) < MODEL_V
    except Exception:                                   # noqa: BLE001
        stale = True
    if moved or stale:
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
        json.dump({"v": MODEL_V, "sidebar": model["sidebar"], "topbar": model["topbar"]},
                  fh, indent=2)
    os.replace(tmp, p)


def visible(model, bar) -> list:
    """The ids to RENDER on one bar, in order. The shell's tab strip and the panel's
    sidebar are both exactly this call."""
    return [r["id"] for r in (model.get(bar) or []) if r.get("pinned")]


def hidden(model, bar) -> list:
    """The rest, in order — the strip's ⋯ overflow menu."""
    return [r["id"] for r in (model.get(bar) or []) if not r.get("pinned")]
