"""OFFICE AGENT LANE — the SERVER-SIDE half of the six LOffice tools (slice S1).

Built to docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md §2/§3. bridge/office_mcp.py is the
MCP wire; THIS module is every decision, so every decision is table-testable without a
server (bridge/tests/test_office_mcp.py).

WHAT THIS IS FOR. The LOffice AI panel's taught action block ("Quick" lane) gives
propose → preview → apply → undo on ANY local model, but it lives in the PAGE: it can
only touch the workbook that is open in front of Debi, one turn at a time. A real tool
loop — read, compute, write, verify, across files — is Hermes's job, and Hermes already
owns the tool registry, the approval cards and the path-guard discipline. So this module
exposes the SAME six gestures the page has, server-side, name-addressed.

═══ THE THREE RULINGS THIS FILE IS BUILT ON ═══

1. IT OPERATES ON office.py's SNAPSHOT, NOT ON openpyxl DIRECTLY.
   `office.snapshot_from_path` → mutate → `office.save_doc` (which takes the daily
   `.bak` and writes through the temp-file + os.replace discipline). openpyxl is still
   what reads and writes the file; it is simply reached through the ONE round-trip this
   codebase already has.

   WHY, and it is the whole reason the semantics table below can be honest: the page
   mutates exactly this shape (`IWorkbookData`), and the spec's bar is that the two
   sides be EQUAL. Re-deriving "sort a sheet" against openpyxl worksheets would be a
   SECOND idea of what a sort means, in a second data model, with its own off-by-one in
   the merge arithmetic — and the test would be comparing two guesses. Mirroring the
   page's algorithms over the page's own data structure means the only thing that can
   drift is a constant, and the constants are pinned byte-for-byte in the test.

   THE PRICE, said out loud because a tool RESULT says it too: an agent write goes
   through the same save the page's ⌘S goes through, so it carries the same fidelity
   contract (office.FIDELITY_NOTE) — charts, images, pivot tables, conditional
   formatting, borders and comments do not survive a save of a file that came from
   Excel. That is why the pre-write copy in rule 3 exists.

2. openpyxl COMPUTES NOTHING, and every read says so. A formula comes back as TEXT plus
   the CACHED result the last real engine wrote, LABELLED as cached. Never as "the
   value". A number in a tool result that the model believes is live, and is not, is the
   worst thing this file could produce.

3. THE PRE-WRITE SIBLING COPY IS THE AGENT LANE'S UNDO. `<stem>.pre-agent.xlsx`, taken
   before every write tool, one level, overwritten per agent write. The page's in-memory
   undo stack CANNOT cover a write that happened while the page was not looking and must
   not pretend to; a sibling file is the only undo that survives the process.

═══ NAME-ADDRESSED, NEVER PATH-ADDRESSED ═══

Every entry point takes a workbook NAME and resolves it through office.doc_target /
office.valid_name — basename only, realpath containment strictly under data/office,
traversal and symlink escape refused, `.xlsx` forced. A tool that takes no path cannot
escape one; that is containment by construction rather than by review.

═══ TOTALITY ═══

Every value here arrives from a LANGUAGE MODEL over MCP. A surprise type, a NaN, an
absurd range, half a nested array: each must cost that ONE operation with a sentence a
person can read, never the workbook and never a traceback.
"""
from __future__ import annotations

import copy
import functools
import json
import math
import os
import re
import secrets
import shutil
import time

try:                                                             # pragma: no cover
    from . import office
except ImportError:                                              # pragma: no cover
    import office                                                # type: ignore


# ═══ 1. THE MIRRORED CONSTANTS ══════════════════════════════════════════════
# ⚠️ EVERY NAME IN THIS BLOCK IS A MIRROR OF ONE IN bridge/panel/office.html, AND
# bridge/tests/test_office_mcp.py READS THE PAGE AND ASSERTS THEM EQUAL. That test is
# the only thing standing between "the two lanes have the same caps" and "the two lanes
# had the same caps when this was written". Do not change one side alone.
#
# Sharing the literals across the two languages is not available: the page is a served
# HTML document with no build step and this is a python module the bridge imports. So
# the contract is pinned by TEST rather than by import — the spec's own instruction
# ("shared constants where practical; where not, contract tests pin both sides").
ACT_V = 1                       # office.html:4417
ACT_MAX_OPS = 60                # office.html:4418 — ops in one change
ACT_MAX_CELLS = 2000            # office.html:4419 — over ALL ops in one change
ACT_MAX_ROW = 4999              # office.html:4420 — 0-based; row 5000
ACT_MAX_COL = 199               # office.html:4421 — column GR
ACT_STR_MAX = 2000              # office.html:4422 — one cell's text
ACT_SHEET_MAX = 31              # office.html:4424 — Excel's own limit
ACT_NAME_MAX = 80               # office.html:4425 — office.NAME_MAX
RC_MAX = 200                    # office.html:2435 — rows/cols in one gesture
TIER1_MAX_COLS = 200            # office.html:2925
SORT_BLANK = 3                  # office.html:2335 — blanks sort last, either direction
ACT_HT = {"left": 1, "center": 2, "centre": 2, "right": 3}        # office.html:4432
ACT_VT = {"top": 1, "middle": 2, "center": 2, "centre": 2, "bottom": 3}   # :4433

CV_STRING, CV_NUMBER, CV_BOOLEAN = office.CV_STRING, office.CV_NUMBER, office.CV_BOOLEAN

# office.html:2313. The ⌘Z at the end is the PAGE's undo; the agent lane's is the
# pre-agent copy, so the tool results append AGENT_UNDO_NOTE rather than editing this
# sentence — one constant, mirrored exactly, plus one sentence that is ours.
RC_FORMULA_NOTE = ("this sheet holds formulas and their references were NOT "
                   "rewritten — LOffice stores a formula as TEXT and has no parser, so "
                   "a relative reference may now point at the wrong cell. Check them, "
                   "or ⌘Z.")

# ── THE HONESTY LINES, WHICH ARE PART OF THE PRODUCT ────────────────────────
# The spec's §2 ruling: "the model must see the honesty, not just the user". Every one
# of these travels in a tool RESULT, not in a log line and not only in the panel.
CACHED_NOTE = ("formula cells are returned as TEXT plus the value CACHED in the file by "
               "whichever real engine last saved it. Nothing here recomputes anything — "
               "openpyxl has no formula engine — so a cached value may be stale if the "
               "inputs changed since that save, and a formula this workbook has never "
               "been opened in has no cached value at all.")
AGENT_UNDO_NOTE = ("the workbook as it was BEFORE this write is kept beside it as "
                   "{backup} — that is the only undo for an agent write, because "
                   "LOffice's in-page undo stack cannot see a write it did not make.")
FIDELITY_WRITE_NOTE = ("this write re-saved the whole workbook from LOffice's snapshot, "
                       "which is what the LOffice page's own ⌘S does: " +
                       office.FIDELITY_NOTE)

# ── THE OPEN-DIRTY REFUSAL (spec §3 rule 2) ────────────────────────────────
# ADVISORY, NEVER A LOCK FILE. The page beacons {name, dirty} while a workbook is open;
# an entry older than HEARTBEAT_TTL is ignored, and NO entry means allowed. A crashed
# page, a closed tab or a bridge restart must never leave a workbook the agent can no
# longer write — that failure mode is worse than the race it would prevent.
HEARTBEAT_TTL = 15.0
DIRTY_REFUSAL = ("Debi has unsaved edits in that workbook — ask her to save or close "
                 "first.")
# ⚠️ THE SAME RULE, WORDED FOR THE PERSON PRESSING THE BUTTON. In v2 nothing an agent
# does can write, so the only caller left is Debi's own Apply — and she is looking at
# the workbook. Applying over her unsaved edits would destroy them silently, so the
# refusal STAYS and tells her the one thing that clears it.
APPLY_DIRTY_REFUSAL = ("you have unsaved edits in that workbook — save it (⌘S) or close "
                       "it, then press Apply again. Applying now would overwrite what "
                       "you have not saved.")

PRE_AGENT_SUFFIX = ".pre-agent" + office.DOC_EXT

# ═══ THE CHANGESET LANE (docs/FABLE-AGENT-CHANGESET-SPEC.md) ═════════════════
# ⚠️ THE MCP WRITE TOOLS STOPPED WRITING. Everything below this line is v2's answer to
# the 2026-08-27 consent incident: one intention → one staged changeset → ONE card in
# LOffice → a human's Apply. Nothing in this module writes a workbook except
# apply_changeset (which no MCP tool can reach) and restore_checkpoint.
CHANGESET_TTL = 600.0            # spec §1: "TTL ~10 min"
CHANGESET_MAX = 24               # a cheap bound on the bridge-held store
PREVIEW_MAX_CELLS = 400          # the card lists this many before→after rows, then says
                                 # how many more there are — never a silent truncation
CHECKPOINT_DIR = ".checkpoints"  # under data/office/, one folder per workbook stem
CHECKPOINT_KEEP = 10             # spec §3: "keep last 10 per workbook, prune oldest"

# THE SENTENCE THAT TRAVELS IN EVERY STAGING RESULT, so the MODEL reads it and not only
# the user. Spec §1 quotes it; the test pins it character for character.
NOT_APPLIED_SENTENCE = ("NOT applied — Debi reviews and applies this in LOffice.")
STAGED_NOTE = ("You cannot apply this yourself: there is no apply tool, and Apply is a "
               "button in LOffice that only Debi can press. Say in one short sentence "
               "what you staged and STOP. Do not claim anything was changed unless a "
               "system line tells you the changeset was applied.")

# The two outcome lines (spec §2). One of these reaches the session after every human
# decision, so the next turn cannot hallucinate the state of the workbook.
APPLIED_LINE = ("[LOffice] changeset {cid} was APPLIED by the user at {when} — receipt "
                "{receipt}: {cells} cell(s) written to \"{name}\". The workbook on disk "
                "now holds that change.")
DISMISSED_LINE = ("[LOffice] changeset {cid} was DISMISSED by the user at {when} — it "
                  "was NEVER applied and \"{name}\" is unchanged. Do not claim "
                  "otherwise.")
UNDONE_LINE = ("[LOffice] changeset {cid} was UNDONE by the user at {when} — \"{name}\" "
               "was restored to the checkpoint taken before that apply.")

# The undo's mtime fence (spec §3). An honest refusal, never a silent clobber.
# ⚠️ THE SLACK IS 2ms, NOT THE HALF-SECOND THE PAGE'S POLLING USES, AND THE DIFFERENCE
# MATTERS. The page compares an mtime it read minutes ago against one it reads now, over
# a filesystem, so it needs slack. This compares an mtime the bridge recorded off the
# file IT JUST WROTE against the same file now: any real difference is somebody else's
# save, including one that landed in the same second. A half-second window here would
# let the undo throw away work Debi did immediately after pressing Apply — which is
# exactly when she is most likely to do some.
FENCE_EPS = 0.002
UNDO_FENCE_REFUSAL = ("that workbook changed on disk after the change was applied, so "
                      "restoring the checkpoint would throw away whatever happened "
                      "since. Nothing was restored — the checkpoint is still there as "
                      "{checkpoint} if you want it.")

# Read caps. The 2000 is the write cap reused deliberately: one number for "how much of
# a spreadsheet fits in one exchange", so a model that can write a block can read it back.
READ_MAX_CELLS = ACT_MAX_CELLS
STATS_MAX_COLS = 64             # column stats past this is a wall of text, not an answer


# ═══ 2. SMALL TOTAL HELPERS ═════════════════════════════════════════════════
def _fin(v):
    """A finite float, or None. NaN/inf are not values — JS `isFinite`'s twin."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _numeric(f):
    """A finite float → int when it is integral, matching office.cell_snapshot's own
    rule, so a snapshot this module writes is byte-comparable with one it read."""
    return int(f) if float(f).is_integer() and abs(f) < 2 ** 53 else f


def col_name(c) -> str:
    """0 → 'A', 25 → 'Z', 26 → 'AA'. office.html's colName(), for the messages."""
    try:
        i = int(c)
    except (TypeError, ValueError):
        return "?"
    if i < 0:
        return "?"
    out = ""
    i += 1
    while i > 0:
        i, rem = divmod(i - 1, 26)
        out = chr(65 + rem) + out
    return out


def a1(r, c) -> str:
    return f"{col_name(c)}{int(r) + 1}"


# ═══ 3. THE PURE PARSERS (office.html:4437-4585, mirrored) ══════════════════
def act_scalar(v) -> bool:
    """A value simple enough to be a cell. `None` is allowed and MEANS "empty it"."""
    if v is None:
        return True
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return _fin(v) is not None
    if isinstance(v, str):
        return len(v) <= ACT_STR_MAX
    return False


_REF_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]{1,7})$")
_COL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?[0-9]{0,7}$")


def _letters_to_col(letters: str) -> int:
    c = 0
    for ch in letters.upper():
        c = c * 26 + (ord(ch) - 64)
    return c


def act_ref(s):
    """'B12' / '$b$12' → (r, c) 0-based, or None. Lower case and the $ are accepted
    because a model that has ever seen a spreadsheet writes both."""
    m = _REF_RE.match("" if s is None else str(s).strip())
    if not m:
        return None
    c = _letters_to_col(m.group(1))
    r = int(m.group(2)) - 1
    if r < 0 or c < 1:
        return None
    return (r, c - 1)


def act_range(s):
    """'A1' → a 1x1 rectangle, 'A1:C10' → itself, 'C10:A1' → the SAME rectangle."""
    t = ("" if s is None else str(s)).strip()
    if not t:
        return None
    bits = t.split(":")
    if len(bits) == 1:
        a = act_ref(bits[0])
        return None if a is None else (a[0], a[1], a[0], a[1])
    if len(bits) != 2:
        return None
    a, b = act_ref(bits[0]), act_ref(bits[1])
    if a is None or b is None:
        return None
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def act_col(v) -> int:
    """'B' / '$b$12' / 'AA' → a 0-based column, or -1.

    LETTERS ONLY, and that is a decision: a bare `2` is ambiguous between "column 2"
    and "column B" the moment anybody 0-indexes it, and a sort aimed one column over is
    a silently wrong document."""
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return -1
    m = _COL_RE.match("" if v is None else str(v).strip())
    if not m:
        return -1
    return _letters_to_col(m.group(1)) - 1


def act_rc_target(axis, v) -> int:
    """Where an insert or a delete lands. A ROW is a 1-based number (or a cell
    reference, because a model that has seen a spreadsheet writes 'A3'); a COLUMN is a
    letter."""
    if axis == "col":
        return act_col(v)
    t = ("" if v is None else str(v)).strip()
    ref = act_ref(t)
    if ref is not None:
        return ref[0]
    if re.match(r"^[0-9]{1,7}$", t):
        n = int(t)
        return n - 1 if n >= 1 else -1
    return -1


def act_grid(v):
    """Anything a model called "values" → a row-major grid, or None.

    FORGIVING ON READ, deliberately: a scalar is a 1x1 grid and a FLAT list is ONE ROW,
    because those are the two shapes a model reaches for when it means "one cell" and
    "one row". A HALF-nested list is REFUSED rather than repaired — that one is
    genuinely ambiguous, and guessing could put a value in the wrong cell.
    """
    if v is None:
        return None
    if not isinstance(v, list):
        return [[v]] if act_scalar(v) else None
    if not v:
        return None
    nested = sum(1 for x in v if isinstance(x, list))
    if nested and nested != len(v):
        return None
    rows = v if nested else [v]
    out = []
    for row in rows:
        if not isinstance(row, list) or not row:
            return None
        for x in row:
            if not act_scalar(x):
                return None
        out.append(list(row))                    # a COPY, never the caller's list
    return out or None


def act_color(v):
    """'#abc' / '#AABBCC' / {rgb:'#..'} → {'rgb': '#aabbcc'}. A colour NAME is refused:
    the file stores hex and inventing one for "reddish" would be a lie in a document."""
    raw = v.get("rgb") if isinstance(v, dict) else v
    t = ("" if raw is None else str(raw)).strip().lower()
    if re.match(r"^#[0-9a-f]{6}$", t):
        return {"rgb": t}
    if re.match(r"^#[0-9a-f]{3}$", t):
        return {"rgb": "#" + t[1] * 2 + t[2] * 2 + t[3] * 2}
    return None


def act_style_set(v):
    """A style dict → only the keys office.apply_style actually writes into the .xlsx.

    ⚠️ THE LIST IS NOT A STYLE CHOICE. A key accepted here and dropped by the bridge
    would be a formatting change that looks right, vanishes on save, and comes back
    missing on the next open — the worst kind of silent loss. Unknown keys are dropped;
    an op left with nothing is refused, and the reason says so.
    """
    if not isinstance(v, dict):
        return None
    out = {}
    if v.get("bl"):
        out["bl"] = 1
    if v.get("it"):
        out["it"] = 1
    if v.get("ul"):
        out["ul"] = {"s": 1}
    if v.get("st"):
        out["st"] = {"s": 1}
    ff = v.get("ff")
    if isinstance(ff, str) and ff.strip() and len(ff) <= 64:
        out["ff"] = ff.strip()
    fs = _fin(v.get("fs"))
    if fs is not None and 1 <= fs <= 409:
        out["fs"] = _numeric(fs)
    cl = act_color(v.get("cl"))
    if cl:
        out["cl"] = cl
    bg = act_color(v.get("bg"))
    if bg:
        out["bg"] = bg
    raw_ht = v.get("ht")
    ht = ACT_HT.get(raw_ht.strip().lower()) if isinstance(raw_ht, str) else raw_ht
    if ht in (1, 2, 3) and not isinstance(ht, bool):
        out["ht"] = ht
    raw_vt = v.get("vt")
    vt = ACT_VT.get(raw_vt.strip().lower()) if isinstance(raw_vt, str) else raw_vt
    if vt in (1, 2, 3) and not isinstance(vt, bool):
        out["vt"] = vt
    if v.get("tb") == 3 or v.get("tb") is True or v.get("tb") == "wrap":
        out["tb"] = 3
    n = v.get("n")
    pat = n.get("pattern") if isinstance(n, dict) else n
    if isinstance(pat, str) and pat.strip() and len(pat) <= 64:
        out["n"] = {"pattern": pat.strip()}
    return out or None


def act_doc_name(v) -> str:
    """A workbook name a model suggested → something office.valid_name can be asked
    for. This only removes what could not possibly be a file name; the BRIDGE owns the
    rest of the rules and its own ' (n)' never-clobber walk, in its own words."""
    s = "" if v is None else str(v)
    s = s.replace('"', " ")
    s = re.sub(r"[\\/:*?<>|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\.xlsx$", "", s, flags=re.IGNORECASE).strip()
    return s[:ACT_NAME_MAX]


# ═══ 4. THE VALIDATOR (office.html:4588-4740, mirrored) ═════════════════════
class Refused(Exception):
    """A refusal carrying a sentence a person — and a model — can act on."""


def validate_ops(raw):
    """(ops, count, '') or (None, None, reason). The page's `actValidate`, minus the
    envelope: the MCP tool takes the ops list directly (there is no fenced block to
    find), so `v` and the fence grammar have no job here. EVERY refusal string below is
    the page's, character for character, and the test asserts that.

    ⚠️ THE CAP ASYMMETRY IS THE POINT, and it is not set-vs-style — both of those
    REFUSE. It is REFUSE vs CLAMP:
      · REFUSE, because a clamp would drop data: `set` over the cell budget, `set` past
        the grid, `style` over the budget, `delete_rc` over RC_MAX.
      · CLAMP, because a clamp loses nothing: `resize` (a row count is a view) and
        `insert` (it adds empty space). A model asking for 100 000 rows means "a lot".
    """
    if not isinstance(raw, list) or not raw:
        return None, None, 'the block carried no "ops" list'
    if len(raw) > ACT_MAX_OPS:
        return None, None, (f"that is {len(raw)} operations and the cap is "
                            f"{ACT_MAX_OPS}")
    ops = []
    count = {"cells": 0, "cleared": 0, "formulas": 0, "styled": 0, "sheets": 0,
             "renames": 0, "resizes": 0, "lines": 0, "sorts": 0, "inserts": 0,
             "deletes": 0, "creates": 0}
    budget = 0
    for i, o in enumerate(raw):
        at = f"operation {i + 1}: "
        if not isinstance(o, dict):
            return None, None, at + "not an object"
        kind = ("" if o.get("op") is None else str(o["op"])).strip().lower()
        if kind == "set":
            rg = act_range(o.get("at"))
            if rg is None:
                return None, None, (at + '"at" is not a cell or a range ('
                                    + json.dumps(o.get("at")) + ")")
            grid = act_grid(o["values"] if "values" in o else o.get("value"))
            if grid is None:
                return None, None, (at + '"values" is not a row-major grid of simple '
                                         "values")
            w = max(len(r) for r in grid)
            # ⚠️ THE RANGE IS AN ANCHOR, NOT A CLIP. at:'A1:C3' with five rows of values
            # writes five rows: clipping would silently drop what the model meant to
            # write, and a spreadsheet that quietly loses half a table is worse than one
            # that wrote further than you expected — which you can SEE, and take back.
            if (rg[0] + len(grid) - 1 > ACT_MAX_ROW
                    or rg[1] + w - 1 > ACT_MAX_COL):
                return None, None, (at + "that would write past "
                                    + col_name(ACT_MAX_COL) + str(ACT_MAX_ROW + 1))
            n = 0
            for row in grid:
                for x in row:
                    n += 1
                    if x is None or x == "":
                        count["cleared"] += 1
                    else:
                        count["cells"] += 1
                        if isinstance(x, str) and x[:1] == "=":
                            count["formulas"] += 1
            budget += n
            count["lines"] += n
            if budget > ACT_MAX_CELLS:
                return None, None, (f"that is more than {ACT_MAX_CELLS} cells in one "
                                    "change — ask for it in a few smaller pieces")
            ops.append({"op": "set", "r": rg[0], "c": rg[1], "values": grid})
        elif kind == "style":
            rg = act_range(o.get("at"))
            if rg is None:
                return None, None, (at + '"at" is not a cell or a range ('
                                    + json.dumps(o.get("at")) + ")")
            if rg[2] > ACT_MAX_ROW or rg[3] > ACT_MAX_COL:
                return None, None, (at + "that range reaches past "
                                    + col_name(ACT_MAX_COL) + str(ACT_MAX_ROW + 1))
            st = act_style_set(o["set"] if "set" in o else o.get("style"))
            if not st:
                return None, None, (at + "none of those formatting keys are carried by "
                                         "the .xlsx round-trip, so applying them would "
                                         "only look right until you saved")
            budget += (rg[2] - rg[0] + 1) * (rg[3] - rg[1] + 1)
            if budget > ACT_MAX_CELLS:
                return None, None, (f"that formats more than {ACT_MAX_CELLS} cells in "
                                    "one change — ask for it in a few smaller pieces")
            count["styled"] += 1
            count["lines"] += 1
            ops.append({"op": "style", "r0": rg[0], "c0": rg[1], "r1": rg[2],
                        "c1": rg[3], "set": st})
        elif kind == "create_workbook":
            # ⚠️ ABSORBED FROM THE RETIRED office_create (spec §1). It takes NO name: the
            # workbook a changeset is about is the changeset's own `name`, so a create
            # cannot address a second file and there is nothing here to escape with.
            count["creates"] += 1
            count["lines"] += 1
            ops.append({"op": "create_workbook"})
        elif kind in ("sheet", "add_sheet"):
            if kind == "add_sheet" and isinstance(o.get("name"), str):
                o = dict(o, add=o["name"])       # `add_sheet` is `sheet`+`add`, spelled
            add = o["add"].strip() if isinstance(o.get("add"), str) else ""
            ren = o["rename"].strip() if isinstance(o.get("rename"), str) else ""
            if add:
                if len(add) > ACT_SHEET_MAX:
                    return None, None, (at + "a sheet name is at most "
                                        f"{ACT_SHEET_MAX} characters")
                count["sheets"] += 1
                count["lines"] += 1
                ops.append({"op": "sheet", "add": add})
            elif ren:
                if len(ren) > ACT_SHEET_MAX:
                    return None, None, (at + "a sheet name is at most "
                                        f"{ACT_SHEET_MAX} characters")
                count["renames"] += 1
                count["lines"] += 1
                ops.append({"op": "sheet", "rename": ren,
                            "at": o["at"].strip() if isinstance(o.get("at"), str) else ""})
            else:
                return None, None, at + 'a "sheet" operation needs "add" or "rename"'
        elif kind == "resize":
            fr, fc = _fin(o.get("rows")), _fin(o.get("cols"))
            rows = math.floor(fr) if fr is not None else 0
            cols = math.floor(fc) if fc is not None else 0
            R = min(rows, ACT_MAX_ROW + 1) if rows > 0 else 0
            C = min(cols, ACT_MAX_COL + 1) if cols > 0 else 0
            if not R and not C:
                return None, None, at + 'a "resize" needs "rows" or "cols"'
            count["resizes"] += 1
            count["lines"] += 1
            ops.append({"op": "resize", "rows": R, "cols": C})
        elif kind == "sort":
            given = o["col"] if "col" in o else o.get("at")
            col = act_col(given)
            if col < 0:
                return None, None, (at + '"col" is not a column letter ('
                                    + json.dumps(given) + ")")
            if col > ACT_MAX_COL:
                return None, None, (at + "column " + col_name(col) + " is past "
                                    + col_name(ACT_MAX_COL))
            raw_word = o.get("dir") if "order" not in o else o.get("order")
            word = ("" if raw_word is None else str(raw_word)).strip().lower()
            desc = (o.get("desc") is True or o.get("desc") == "true"
                    or word in ("desc", "descending", "za", "z-a"))
            count["sorts"] += 1
            count["lines"] += 1
            ops.append({"op": "sort", "col": col, "desc": bool(desc)})
        elif kind in ("insert", "delete_rc"):
            given = o["what"] if "what" in o else o.get("axis")
            what = ("" if given is None else str(given)).strip().lower()
            axis = ("row" if what in ("row", "rows")
                    else ("col" if what in ("col", "cols", "column", "columns") else ""))
            if not axis:
                return None, None, (at + 'an "insert" or a "delete_rc" needs "what": '
                                         "row or col")
            idx = act_rc_target(axis, o.get("at"))
            if idx < 0:
                return None, None, (at + '"at" is not a '
                                    + ("row number" if axis == "row"
                                       else "column letter")
                                    + " (" + json.dumps(o.get("at")) + ")")
            lim = ACT_MAX_ROW if axis == "row" else ACT_MAX_COL
            if idx > lim:
                return None, None, (at + "that is past "
                                    + (str(ACT_MAX_ROW + 1) if axis == "row"
                                       else col_name(ACT_MAX_COL)))
            fa = _fin(1 if o.get("n") is None else o.get("n"))
            asked = math.floor(fa) if fa is not None else 0
            want = asked if asked >= 1 else 1
            # ⚠️ THE ASYMMETRY, for the third time and the same reason: an INSERT adds
            # empty space and is CLAMPED, a DELETE destroys data and is REFUSED over the
            # cap rather than quietly doing 200 of it.
            if kind == "delete_rc" and want > RC_MAX:
                return None, None, (at + f"deleting {want} {axis}s at once is past the "
                                    f"cap of {RC_MAX} — ask for it in smaller pieces")
            n = min(want, RC_MAX)
            if kind == "insert":
                count["inserts"] += n
            else:
                count["deletes"] += n
            count["lines"] += 1
            ops.append({"op": kind, "axis": axis, "at": idx, "n": n})
        else:
            return None, None, at + "unknown operation " + json.dumps(kind)
    if not ops:
        return None, None, "the block asked for nothing"
    return ops, count, ""


# ═══ 5. THE SNAPSHOT PRIMITIVES (office.html:2274-3067, mirrored) ═══════════
def cell_at(sh, r, c):
    row = (sh or {}).get("cellData", {})
    row = row.get(str(r)) if isinstance(row, dict) else None
    cell = row.get(str(c)) if isinstance(row, dict) else None
    return cell if isinstance(cell, dict) else None


def put_cell(sh, r, c, cell) -> None:
    """THE ONE DOOR every write in this module goes through, `putCell`'s twin —
    including the empty-row pruning, which matters because a test compares snapshots."""
    cd = sh.get("cellData")
    if not isinstance(cd, dict):
        cd = sh["cellData"] = {}
    rk, ck = str(r), str(c)
    if cell is None:
        if isinstance(cd.get(rk), dict):
            cd[rk].pop(ck, None)
            if not cd[rk]:
                cd.pop(rk, None)
        return
    if not isinstance(cd.get(rk), dict):
        cd[rk] = {}
    cd[rk][ck] = cell


def display_text(cell) -> str:
    """What the cell SHOWS. A formula shows its own TEXT — this tier has no formula
    engine and inventing one would be worse than being honest about it."""
    if not cell:
        return ""
    f = cell.get("f")
    if isinstance(f, str) and f:
        return f
    return value_text(cell.get("v"), cell.get("t"))


def value_text(v, t=None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool) or t == CV_BOOLEAN:
        return "TRUE" if v else "FALSE"
    if isinstance(v, dict):                      # rich text: {body:{dataStream}}
        ds = (v.get("body") or {}).get("dataStream") if isinstance(v.get("body"), dict) else None
        return re.sub(r"[\r\n]+$", "", ds) if isinstance(ds, str) else ""
    if isinstance(v, float) and float(v).is_integer() and abs(v) < 2 ** 53:
        return str(int(v))                       # JS prints 900.0 as 900
    return str(v)


def used_extent(sh):
    """(rows, cols) of the used range, merges included — so a small sheet is not padded
    to 5000 rows and a big one is not truncated below its own data."""
    max_r = max_c = -1
    cd = (sh or {}).get("cellData")
    if isinstance(cd, dict):
        for rk, row in cd.items():
            try:
                r = int(rk)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            any_cell = False
            for ck in row:
                try:
                    c = int(ck)
                except (TypeError, ValueError):
                    continue
                any_cell = True
                if c > max_c:
                    max_c = c
            if any_cell and r > max_r:
                max_r = r
    for m in (sh or {}).get("mergeData") or []:
        if not isinstance(m, dict):
            continue
        er, ec = _fin(m.get("endRow")), _fin(m.get("endColumn"))
        if er is not None and er > max_r:
            max_r = int(er)
        if ec is not None and ec > max_c:
            max_c = int(ec)
    return max_r + 1, max_c + 1


def sheet_formulas(sh) -> int:
    n = 0
    for row in ((sh or {}).get("cellData") or {}).values():
        if not isinstance(row, dict):
            continue
        for cell in row.values():
            if isinstance(cell, dict) and isinstance(cell.get("f"), str) and cell["f"]:
                n += 1
    return n


def sheet_merges(sh) -> int:
    md = (sh or {}).get("mergeData")
    return len([m for m in md if m]) if isinstance(md, list) else 0


def grid_remap(sh, rows, cols, src) -> int:
    """THE ONE CELL-MOVER: sort, insert row/col and delete row/col are all one remap
    over a source function.

    ⚠️ IT CAPTURES BEFORE IT WRITES, and that is the whole correctness argument: source
    and destination are the SAME rectangle, so writing as it goes would read cells it
    had already overwritten. (That is the bug every hand-rolled "insert a row" has, and
    it shows up as a DUPLICATED ROW rather than as an error.)
    """
    if not sh or rows <= 0 or cols <= 0 or not callable(src):
        return 0
    held = []
    for r in range(rows):
        row = []
        for c in range(cols):
            s = src(r, c)
            row.append(cell_at(sh, s[0], s[1]) if s else None)
        held.append(row)
    n = 0
    for r in range(rows):
        for c in range(cols):
            put_cell(sh, r, c, held[r][c])
            if held[r][c]:
                n += 1
    return n


def sort_key(cell):
    """(k, n, s). k: 0 numbers · 1 text · 2 booleans · SORT_BLANK blanks. A FORMULA
    sorts as its own text (class 1), never as its cached value — the cached number is
    not something this lane may pretend to know the sort order of."""
    if not cell:
        return (SORT_BLANK, 0.0, "")
    f = cell.get("f")
    if isinstance(f, str) and f:
        return (1, 0.0, f.lower())
    v = cell.get("v")
    if v is None or v == "":
        return (SORT_BLANK, 0.0, "")
    if isinstance(v, bool) or cell.get("t") == CV_BOOLEAN:
        return (2, 0.0, "true" if v else "false")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and _fin(v) is not None:
        return (0, float(v), "")
    s = display_text(cell)
    return (SORT_BLANK, 0.0, "") if s == "" else (1, 0.0, s.lower())


def sort_order(sh, col, desc, rows):
    """Which SOURCE row each destination row takes. Numbers before text before
    booleans, BLANKS ALWAYS LAST IN BOTH DIRECTIONS (a sheet whose empty rows climb to
    the top on Z→A is not a sort anybody wanted), and STABLE.

    ⚠️ WRITTEN AS AN EXPLICIT COMPARATOR ON PURPOSE. `sorted(key=…, reverse=True)`
    gets BOTH special cases wrong: it would reverse the blanks-last rule and it would
    reverse the tie order. In the page's comparator the blank branch and the
    `d == 0` tiebreak both return BEFORE the `desc` negation, so they are not affected
    by direction — that is what cmp_to_key reproduces and a key function cannot.
    """
    idx = list(range(rows))
    keys = [sort_key(cell_at(sh, r, col)) for r in idx]

    def cmp(a, b):
        ka, kb = keys[a], keys[b]
        if ka[0] == SORT_BLANK or kb[0] == SORT_BLANK:
            if ka[0] == kb[0]:
                return a - b
            return 1 if ka[0] == SORT_BLANK else -1
        if ka[0] != kb[0]:
            d = ka[0] - kb[0]
        elif ka[0] == 0:
            d = -1 if ka[1] < kb[1] else (1 if ka[1] > kb[1] else 0)
        else:
            d = -1 if ka[2] < kb[2] else (1 if ka[2] > kb[2] else 0)
        if d == 0:
            return a - b                          # stable
        return -d if desc else d

    idx.sort(key=functools.cmp_to_key(cmp))
    return idx


def rc_merges(lst, axis, at, n, delete):
    """The merge list, renumbered. Returns a NEW list, so the caller decides whether to
    install it. INSERT: a merge wholly at/after the line shifts by n; one that
    STRADDLES it GROWS by n, which is what Excel does and the only answer that leaves
    the same cells joined. DELETE: a straddler shrinks and one wholly inside the band is
    dropped — there is nothing left of it to merge."""
    out = []
    S = "startColumn" if axis == "col" else "startRow"
    E = "endColumn" if axis == "col" else "endRow"
    for m in (lst if isinstance(lst, list) else []):
        if not m or not isinstance(m, dict):
            continue
        s, e = _fin(m.get(S)), _fin(m.get(E))
        if s is None or e is None:
            continue                              # unreadable: dropped, not guessed
        s, e = int(s), int(e)
        copy = dict(m)
        if not delete:
            if s >= at:
                copy[S], copy[E] = s + n, e + n
            elif e >= at:
                copy[E] = e + n
        else:
            last_gone = at + n - 1
            if s > last_gone:
                copy[S], copy[E] = s - n, e - n
            elif e >= at:
                cut = min(e, last_gone) - max(s, at) + 1
                copy[S] = min(s, at)
                copy[E] = e - cut
                if int(copy[E]) <= int(copy[S]):
                    continue                      # nothing left to merge
        out.append(copy)
    return out


def rc_apply(sh, kind, axis, at, n):
    """The whole insert/delete gesture, without a DOM. `kind` is 'insert' or 'delete'.

    ⚠️ THE CLAMP LIVES HERE AND THE DELETE REFUSAL LIVES IN validate_ops, exactly as on
    the page: two layers, two behaviours, and a delete over RC_MAX never reaches this
    function through a tool call."""
    fn = _fin(n)
    count = max(1, min(int(math.floor(fn)) if fn else 1, RC_MAX))
    delete = kind == "delete"
    urows, ucols = used_extent(sh)
    rows = (urows if delete else urows + count) if axis == "row" else urows
    cols = (ucols if delete else ucols + count) if axis == "col" else ucols
    cap_cols = min(cols, TIER1_MAX_COLS)

    def shift(i):
        if i < at:
            return i
        if delete:
            return i + count
        return -1 if i < at + count else i - count   # -1 = the new empty band

    if axis == "row":
        def src(r, c):
            s = shift(r)
            return None if s < 0 else (s, c)
    else:
        def src(r, c):
            s = shift(c)
            return None if s < 0 else (r, s)

    wrote = grid_remap(sh, max(rows, 1), max(cap_cols, 1), src)
    sh["mergeData"] = rc_merges(sh.get("mergeData"), axis, at, count, delete)
    if axis == "row":
        rc = int(_fin(sh.get("rowCount")) or 0)
        sh["rowCount"] = max(1, max(rc - count, urows - count) if delete else rc + count)
    else:
        cc = int(_fin(sh.get("columnCount")) or 0)
        sh["columnCount"] = min(
            TIER1_MAX_COLS,
            max(1, max(cc - count, ucols - count) if delete else cc + count))
    return {"kind": kind, "axis": axis, "at": at, "n": count, "cells": wrote,
            "clipped": cap_cols < cols, "merges": sheet_merges(sh),
            "formulas": sheet_formulas(sh)}


# ═══ 6. VALUE COERCION (office.html:2992-3010, 4851-4867, mirrored) ═════════
def parse_input(text, prev=None):
    """The SAME converter a typed cell goes through, so a value the agent wrote and one
    Debi typed become the same cell. A leading '=' is a formula; 'true'/'false' is a
    boolean; a PLAIN number is a number — and '1e5', '0x10' and '007' deliberately stay
    TEXT, because those are things a person typed as text far more often than as a
    number, and a silently renumbered part code is a corrupted document."""
    s = ("" if text is None else str(text)).replace("\r", "")
    style = prev.get("s") if isinstance(prev, dict) and "s" in prev else None
    has_style = isinstance(prev, dict) and "s" in prev
    if s == "":
        return {"s": style} if has_style else None
    out = {}
    if has_style:
        out["s"] = style
    if s[:1] == "=":
        out["f"] = s
        return out
    low = s.lower()
    if low in ("true", "false"):
        out["v"], out["t"] = (low == "true"), CV_BOOLEAN
        return out
    if re.match(r"^-?(\d+\.?\d*|\.\d+)$", s) and not re.match(r"^-?0\d", s):
        f = _fin(s)
        if f is not None:
            out["v"], out["t"] = _numeric(f), CV_NUMBER
            return out
    out["v"], out["t"] = s, CV_STRING
    return out


def act_cell(v, prev=None):
    """A value the MODEL wrote → a cell, keeping the previous cell's STYLE. Writing a
    number into a bold red cell must not strip the bold red."""
    has_style = isinstance(prev, dict) and "s" in prev
    style = prev.get("s") if has_style else None
    if v is None or v == "":
        return {"s": style} if has_style else None
    if isinstance(v, bool):
        out = {"v": v, "t": CV_BOOLEAN}
        if has_style:
            out["s"] = style
        return out
    if isinstance(v, (int, float)):
        f = _fin(v)
        if f is None:
            return {"s": style} if has_style else None
        out = {"v": _numeric(f), "t": CV_NUMBER}
        if has_style:
            out["s"] = style
        return out
    return parse_input(str(v), prev)


def resolve_style(snapshot, cell):
    """⚠️ THE SHARED-STYLE-ID TRAP. A cell's `s` may be a STRING ID into
    snapshot['styles'], SHARED with other cells. It is resolved here, and the caller
    COPIES it and writes the copy back inline on that ONE cell — mutating the shared
    entry would bold half the workbook, silently, and the save would make it permanent.
    """
    s = cell.get("s") if isinstance(cell, dict) else None
    if isinstance(s, str):
        styles = (snapshot or {}).get("styles")
        s = styles.get(s) if isinstance(styles, dict) else None
    return s if isinstance(s, dict) else None


# ═══ 7. SHEETS ══════════════════════════════════════════════════════════════
def sheet_ids(snapshot) -> list:
    """sheetOrder first, then anything in `sheets` it forgot — a workbook must never be
    seen with zero sheets because sheetOrder was junk (office._sheet_names's rule)."""
    sheets = (snapshot or {}).get("sheets")
    if not isinstance(sheets, dict):
        return []
    order = snapshot.get("sheetOrder")
    ids = [i for i in order if isinstance(i, str) and i in sheets] \
        if isinstance(order, list) else []
    for k in sheets:
        if k not in ids:
            ids.append(k)
    return ids


def target_sid(snapshot, name):
    """A sheet NAME (the only handle a model has) → the id we hold, or '' when there are
    no sheets. An unknown name falls back to the FIRST sheet rather than inventing one —
    and every tool result says which of the two happened, because a write that landed on
    a different sheet than the model believed is exactly the failure this lane must be
    loud about."""
    ids = sheet_ids(snapshot)
    if not ids:
        return ""
    want = ("" if name is None else str(name)).strip().lower()
    if not want:
        return ids[0]
    for sid in ids:
        sh = snapshot["sheets"].get(sid)
        if isinstance(sh, dict) and str(sh.get("name") or "").strip().lower() == want:
            return sid
    return ids[0]


def sheet_exists(snapshot, name) -> bool:
    want = ("" if name is None else str(name)).strip().lower()
    if not want:
        return False
    for sid in sheet_ids(snapshot):
        sh = snapshot["sheets"].get(sid)
        if isinstance(sh, dict) and str(sh.get("name") or "").strip().lower() == want:
            return True
    return False


def add_sheet(snapshot, name, seq=0):
    """`actAddSheet`'s twin: a name already taken steps to 'Name 2' rather than
    colliding, because Excel refuses duplicate sheet names and dropping the second
    sheet would lose whatever the model meant to put in it."""
    ids = sheet_ids(snapshot)
    taken = [str((snapshot["sheets"].get(i) or {}).get("name") or "").lower()
             for i in ids]
    base = (("" if name is None else str(name)).strip() or "Sheet")[:ACT_SHEET_MAX]
    nm, n = base, 2
    while nm.lower() in taken:
        nm = f"{base} {n}"[:ACT_SHEET_MAX]
        n += 1
    sid = f"sheet-{int(time.time() * 1000):x}-{seq}"
    while sid in snapshot["sheets"]:
        seq += 1
        sid = f"sheet-{int(time.time() * 1000):x}-{seq}"
    snapshot["sheets"][sid] = {"id": sid, "name": nm, "cellData": {},
                              "rowCount": 200, "columnCount": 26}
    if not isinstance(snapshot.get("sheetOrder"), list):
        snapshot["sheetOrder"] = list(ids)
    snapshot["sheetOrder"].append(sid)
    return nm


# ═══ 8. RUN THE OPS (office.html:4938-5046, mirrored) ═══════════════════════
def run_ops(snapshot, sid, ops):
    """Apply a VALIDATED ops list to one sheet of a snapshot. Returns the report the
    tool result is built from, or None when the sheet id is not there.

    ⚠️ AN OP THAT CANNOT BE DONE IS SKIPPED AND SAID — the whole change is not refused.
    That is the page's ruling and it carries over: the rest of the plan is still what
    was approved, and one honest note beats losing all of it. `skipped` and `notes` are
    what carry it, and the MCP layer puts both in the tool RESULT so the MODEL sees them.
    """
    done = {"cells": 0, "cleared": 0, "styled_cells": 0, "sheets": [], "renamed": "",
            "skipped": 0, "sorted": 0, "inserted": 0, "deleted": 0, "created": False,
            "notes": []}
    sheets = (snapshot or {}).get("sheets")
    sh = sheets.get(sid) if isinstance(sheets, dict) else None
    if not isinstance(sh, dict) or not isinstance(ops, list):
        return None
    seq = 0
    for o in ops:
        kind = o.get("op")
        if kind == "set":
            for r, row in enumerate(o["values"]):
                for c, val in enumerate(row):
                    rr, cc = o["r"] + r, o["c"] + c
                    cell = act_cell(val, cell_at(sh, rr, cc))
                    put_cell(sh, rr, cc, cell)
                    if cell and ("v" in cell or "f" in cell):
                        done["cells"] += 1
                    else:
                        done["cleared"] += 1
                    if int(_fin(sh.get("rowCount")) or 0) <= rr:
                        sh["rowCount"] = rr + 1
                    if int(_fin(sh.get("columnCount")) or 0) <= cc:
                        sh["columnCount"] = cc + 1
        elif kind == "style":
            for r in range(o["r0"], o["r1"] + 1):
                for c in range(o["c0"], o["c1"] + 1):
                    prev = cell_at(sh, r, c)
                    base = resolve_style(snapshot, prev)
                    nxt = dict(base) if base else {}
                    nxt.update(o["set"])
                    cell = {k: v for k, v in (prev or {}).items() if k != "s"}
                    if nxt:
                        cell["s"] = nxt
                    put_cell(sh, r, c, cell if cell else None)
                    done["styled_cells"] += 1
        elif kind == "sheet":
            if o.get("add"):
                seq += 1
                done["sheets"].append(add_sheet(snapshot, o["add"], seq))
            elif o.get("rename"):
                tid = target_sid(snapshot, o.get("at")) if o.get("at") else sid
                t = sheets.get(tid)
                if isinstance(t, dict):
                    t["name"] = str(o["rename"])[:ACT_SHEET_MAX]
                    done["renamed"] = t["name"]
                else:
                    done["skipped"] += 1
        elif kind == "resize":
            if o.get("rows") and int(_fin(sh.get("rowCount")) or 0) < o["rows"]:
                sh["rowCount"] = o["rows"]
            if o.get("cols") and int(_fin(sh.get("columnCount")) or 0) < o["cols"]:
                sh["columnCount"] = o["cols"]
        elif kind == "sort":
            merged = sheet_merges(sh)
            if merged:
                done["skipped"] += 1
                done["notes"].append(
                    "the sort was refused: this sheet has "
                    + str(merged)
                    + (" merged range" if merged == 1 else " merged ranges")
                    + ", and a sort moves whole rows while a merge does not move with "
                      "them, so it would end up spanning cells that never belonged "
                      "together.")
            else:
                urows, ucols = used_extent(sh)
                if urows > 1:
                    order = sort_order(sh, o["col"], o["desc"], urows)
                    grid_remap(sh, urows, ucols, lambda r, c: (order[r], c))
                    done["sorted"] += 1
                else:
                    done["skipped"] += 1
                    done["notes"].append("there was nothing to sort — fewer than two "
                                         "rows of data.")
        elif kind in ("insert", "delete_rc"):
            info = rc_apply(sh, "insert" if kind == "insert" else "delete",
                            o["axis"], o["at"], o["n"])
            if kind == "insert":
                done["inserted"] += info["n"]
            else:
                done["deleted"] += info["n"]
            if info["clipped"]:
                done["notes"].append(
                    "the insert reached the right-hand edge of this grid (column "
                    + col_name(TIER1_MAX_COLS - 1) + "), so the last column fell off "
                    "it.")
        elif kind == "create_workbook":
            # ⚠️ NOTHING TO DO HERE, DELIBERATELY. A create is not a mutation of a
            # snapshot — apply_changeset makes the empty workbook BEFORE loading one,
            # and staging shows the same empty snapshot the create would produce. The
            # branch exists so a reader sees the op is handled rather than ignored.
            done["created"] = True
    # THE SORT'S OWN SENTENCE, moved here from the retired op_sort so that one place
    # says it whichever way a sort arrives.
    if done["sorted"]:
        done["notes"].insert(0, "this sorted the whole sheet, ROW 1 INCLUDED: LOffice "
                                "does not guess at a header row. Blank cells went to "
                                "the bottom in both directions.")
    # ⚠️ THE FORMULA NOTE, ONCE PER CHANGE AND NOT ONCE PER OPERATION, and only when the
    # sheet STILL holds a formula. Same sentence as the page, from the same constant.
    if (done["sorted"] or done["inserted"] or done["deleted"]) and sheet_formulas(sh):
        done["notes"].append(RC_FORMULA_NOTE)
    return done


# ═══ 9. THE OPEN-DIRTY HEARTBEAT REGISTRY (spec §3 rule 2) ══════════════════
# PROCESS-LOCAL, ADVISORY, TTL'd. Deliberately not a file and deliberately not durable:
# a heartbeat that survives a bridge restart would be a workbook nobody can write until
# somebody deletes a lock, which is a strictly worse failure than the race it prevents.
#
# S2 (the panel lane) is what will POST to it. Until then nothing registers, every
# workbook reads as "not open", and every write is allowed — which is the correct
# behaviour for a closed page and is asserted as such in the tests.
_HEARTBEATS: dict = {}


def heartbeat(name, dirty, now=None) -> dict:
    """Record that the page has `name` open, dirty or not. Returns what was stored."""
    safe, reason = office.valid_name(name)
    if not safe:
        return {"ok": False, "error": reason}
    ts = now if isinstance(now, (int, float)) else time.time()
    _HEARTBEATS[safe] = {"dirty": bool(dirty), "at": float(ts)}
    return {"ok": True, "name": safe, "dirty": bool(dirty), "ttl": HEARTBEAT_TTL}


def heartbeat_clear(name=None) -> None:
    """Forget one workbook (the page closed it) or all of them (tests)."""
    if name is None:
        _HEARTBEATS.clear()
        return
    safe, _ = office.valid_name(name)
    if safe:
        _HEARTBEATS.pop(safe, None)


def open_state(name, now=None) -> dict:
    """{open, dirty} for a workbook, with a stale heartbeat read as CLOSED."""
    safe, _ = office.valid_name(name)
    ent = _HEARTBEATS.get(safe) if safe else None
    if not isinstance(ent, dict):
        return {"open": False, "dirty": False}
    ts = now if isinstance(now, (int, float)) else time.time()
    if ts - ent["at"] > HEARTBEAT_TTL:
        return {"open": False, "dirty": False}
    return {"open": True, "dirty": bool(ent["dirty"])}


# ═══ 10. THE PRE-WRITE SIBLING COPY (spec §3 rule 1) ════════════════════════
def pre_agent_for(path) -> str:
    """`<stem>.pre-agent.xlsx` beside the file. ONE level, overwritten per agent write:
    it answers "put it back the way it was before the agent touched it", which is the
    only question the page's undo stack cannot answer at all. Distinct from the daily
    `.bak` (office.backup_for), which answers "put it back the way it was this morning"
    — the two are not substitutes and a write takes both."""
    stem = os.path.splitext(str(path))[0]
    if stem.endswith(".pre-agent"):              # never .pre-agent.pre-agent.xlsx
        stem = stem[: -len(".pre-agent")]
    return stem + PRE_AGENT_SUFFIX


def take_pre_agent(path):
    """(basename, None) or (None, reason). A copy we cannot write is a reason to STOP,
    never to write anyway — the same ruling office.save_doc makes about the daily
    `.bak`, for the same reason: this file is the only undo the agent lane has."""
    dst = pre_agent_for(path)
    try:
        shutil.copy2(str(path), dst)
    except OSError as e:
        return None, f"could not write the pre-agent copy beside that workbook: {e}"
    return os.path.basename(dst), None


# ═══ 11. THE SIX TOOLS ══════════════════════════════════════════════════════
# Each returns (result_dict, None) or (None, reason). `root` is the harness root, so
# every path decision goes through office.office_dir / office.doc_target and NOTHING
# here ever sees a caller-supplied path.

def _load(root, name):
    target, reason = office.doc_target(root, name)
    if not target:
        return None, None, reason
    try:
        snap = office.snapshot_from_path(target)
    except office.OfficeError as e:
        return None, None, str(e)
    return target, snap, ""


def _sheet_note(snap, asked, sid) -> str:
    """The sentence a tool result carries when the model named a sheet that is not
    there. Silence here would be a write on the wrong sheet that read as a success."""
    if not asked or sheet_exists(snap, asked):
        return ""
    got = (snap["sheets"].get(sid) or {}).get("name") or "?"
    return (f"there is no sheet called {asked!r} in this workbook, so this acted on "
            f"{got!r} — the first sheet. Ask for office_sheet_stats to see the real "
            f"sheet names.")


def op_list(root) -> dict:
    """Every workbook, newest first, with the open/dirty hint the heartbeat carries."""
    files = []
    for e in office.list_docs(root):
        st = open_state(e["name"])
        files.append({"name": e["name"], "size_bytes": e["size_bytes"],
                      "modified_epoch": round(e["modified"], 3),
                      "modified": time.strftime("%Y-%m-%d %H:%M:%S",
                                                time.localtime(e["modified"])),
                      "has_daily_backup": bool(e["has_backup"]),
                      "open_in_loffice": st["open"],
                      "unsaved_edits": st["dirty"]})
    return {"ok": True, "folder": "data/office", "count": len(files), "files": files,
            "notes": ["a workbook is addressed by NAME — these tools cannot read or "
                      "write anything outside data/office.",
                      "'unsaved_edits' true means a write tool will refuse until Debi "
                      "saves or closes it.",
                      "a *.pre-agent.xlsx is the copy an earlier agent write kept of "
                      "the workbook it was about to change."]}


def op_read(root, name, sheet=None, cell_range=None):
    """values + formulas-as-text + cached values + merges, for a range.

    THE HONEST BOUND, and it is in the RESULT so the model reads it: openpyxl computes
    NOTHING. A formula cell comes back as {formula, cached_value, cached: true} — never
    as a value. See CACHED_NOTE.
    """
    target, snap, reason = _load(root, name)
    if snap is None:
        return None, reason
    sid = target_sid(snap, sheet)
    if not sid:
        return None, "that workbook has no readable sheets"
    sh = snap["sheets"][sid]
    urows, ucols = used_extent(sh)
    if cell_range:
        rg = act_range(cell_range)
        if rg is None:
            return None, (f"{cell_range!r} is not a cell or a range — write it like "
                          "A1:D20")
    else:
        rg = (0, 0, max(urows - 1, 0), max(ucols - 1, 0))
    r0, c0, r1, c1 = rg
    r1, c1 = min(r1, ACT_MAX_ROW), min(c1, ACT_MAX_COL)
    area = max(r1 - r0 + 1, 0) * max(c1 - c0 + 1, 0)
    if area > READ_MAX_CELLS:
        return None, (f"that range is {area} cells and the read cap is "
                      f"{READ_MAX_CELLS} — ask for it in a few smaller pieces")
    cells, formulas = [], 0
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cell = cell_at(sh, r, c)
            if not cell:
                continue
            ref = a1(r, c)
            f = cell.get("f")
            if isinstance(f, str) and f:
                formulas += 1
                out = {"ref": ref, "formula": f, "cached": True}
                if "v" in cell:
                    out["cached_value"] = cell["v"]
                cells.append(out)
            elif "v" in cell:
                cells.append({"ref": ref, "value": cell["v"],
                              "text": display_text(cell)})
    merges = []
    for m in sh.get("mergeData") or []:
        if not isinstance(m, dict):
            continue
        sr, sc = _fin(m.get("startRow")), _fin(m.get("startColumn"))
        er, ec = _fin(m.get("endRow")), _fin(m.get("endColumn"))
        if None in (sr, sc, er, ec):
            continue
        if int(er) < r0 or int(sr) > r1 or int(ec) < c0 or int(sc) > c1:
            continue
        merges.append(f"{a1(int(sr), int(sc))}:{a1(int(er), int(ec))}")
    notes = []
    if formulas:
        notes.append(CACHED_NOTE)
    if merges:
        notes.append(f"this range holds {len(merges)} merged "
                     f"{'range' if len(merges) == 1 else 'ranges'} — office_sort "
                     "REFUSES a sheet with any merge on it.")
    sn = _sheet_note(snap, sheet, sid)
    if sn:
        notes.append(sn)
    if sh.get("truncated"):
        notes.append(f"this sheet is larger than the {office.MAX_CELLS}-cell reader "
                     "and was truncated — the tail is not in this result.")
    return {"ok": True, "name": os.path.basename(target), "sheet": sh.get("name"),
            "range": f"{a1(r0, c0)}:{a1(r1, c1)}",
            "used_range": (f"A1:{a1(max(urows - 1, 0), max(ucols - 1, 0))}"
                           if urows and ucols else "(empty sheet)"),
            "cells": cells, "cell_count": len(cells), "formula_count": formulas,
            "merges": merges, "notes": notes}, None


def op_sheet_stats(root, name, sheet=None):
    """Dimensions, every sheet's name, and per-column stats for the named one."""
    target, snap, reason = _load(root, name)
    if snap is None:
        return None, reason
    sid = target_sid(snap, sheet)
    if not sid:
        return None, "that workbook has no readable sheets"
    sheets = []
    for i in sheet_ids(snap):
        s = snap["sheets"][i]
        rr, cc = used_extent(s)
        sheets.append({"name": s.get("name"), "used_rows": rr, "used_columns": cc,
                       "merges": sheet_merges(s), "formulas": sheet_formulas(s)})
    sh = snap["sheets"][sid]
    urows, ucols = used_extent(sh)
    cols, clipped = [], ucols > STATS_MAX_COLS
    for c in range(min(ucols, STATS_MAX_COLS)):
        nums, texts, bools, blanks, fx = [], 0, 0, 0, 0
        for r in range(urows):
            cell = cell_at(sh, r, c)
            k = sort_key(cell)
            if isinstance(cell, dict) and isinstance(cell.get("f"), str) and cell["f"]:
                fx += 1
            if k[0] == SORT_BLANK:
                blanks += 1
            elif k[0] == 0:
                nums.append(k[1])
            elif k[0] == 2:
                bools += 1
            else:
                texts += 1
        ent = {"column": col_name(c), "numbers": len(nums), "text": texts,
               "booleans": bools, "blanks": blanks, "formulas": fx,
               "first_row_value": display_text(cell_at(sh, 0, c))}
        if nums:
            total = math.fsum(nums)
            ent["min"] = _numeric(min(nums))
            ent["max"] = _numeric(max(nums))
            ent["sum"] = _numeric(total)
            ent["mean"] = _numeric(round(total / len(nums), 10))
        cols.append(ent)
    notes = ["'first_row_value' is row 1 as it is — these tools never guess at a "
             "header row, and neither does office_sort (it sorts row 1 with the rest).",
             "every number here is computed from the values in the file: a formula "
             "cell counts as a FORMULA, not as its cached number. " + CACHED_NOTE]
    if clipped:
        notes.append(f"column stats stop at {col_name(STATS_MAX_COLS - 1)} "
                     f"({STATS_MAX_COLS} columns); this sheet is wider.")
    sn = _sheet_note(snap, sheet, sid)
    if sn:
        notes.append(sn)
    return {"ok": True, "name": os.path.basename(target),
            "sheet_count": len(sheets), "sheets": sheets,
            "sheet": sh.get("name"), "used_rows": urows, "used_columns": ucols,
            "columns": cols, "notes": notes}, None


# ═══ 12. THE APPLY ENGINE — the ONE place a workbook is written ══════════════
# ⚠️ NO MCP TOOL REACHES ANY OF THIS. `_apply` is called by apply_changeset, which is
# called by POST /api/office/changeset/{id}/apply, which is called by a BUTTON. That is
# the whole of v2's consent story: the model can propose, and only a person can write.

def _apply(root, name, sheet, ops, count, label):
    """dirty-refusal → checkpoint + pre-agent copy → run ALL ops → ONE save.

    ATOMIC, ALL-OR-NOTHING (spec §2): every op runs against an in-memory snapshot and
    the file is written ONCE at the end, so a changeset either lands whole or the file
    is untouched. There is no half-applied state to explain to anybody.
    """
    target, reason = office.doc_target(root, name)
    if not target:
        return None, reason
    st = open_state(name)
    if st["dirty"]:
        return None, APPLY_DIRTY_REFUSAL
    try:
        snap = office.snapshot_from_path(target)
    except office.OfficeError as e:
        return None, str(e)
    sid = target_sid(snap, sheet)
    if not sid:
        return None, "that workbook has no readable sheets"
    backup, reason = take_pre_agent(target)
    if backup is None:
        return None, reason
    done = run_ops(snap, sid, ops)
    if done is None:
        return None, "refused: those operations could not be applied to that sheet"
    report, reason = office.save_doc(root, os.path.basename(target), snap)
    if report is None:
        return None, reason
    notes = list(done["notes"])
    notes.append(AGENT_UNDO_NOTE.format(backup=backup))
    notes.append(FIDELITY_WRITE_NOTE)
    sn = _sheet_note(snap, sheet, sid)
    if sn:
        notes.insert(0, sn)
    if st["open"]:
        notes.append("that workbook is OPEN in LOffice with no unsaved edits — the page "
                     "will notice the change and reload.")
    out = {"ok": True, "action": label, "name": report["name"],
           "sheet": (snap["sheets"][sid] or {}).get("name"),
           "cells_written": done["cells"], "cells_emptied": done["cleared"],
           "cells_formatted": done["styled_cells"],
           "sorted": done["sorted"], "rows_or_columns_inserted": done["inserted"],
           "rows_or_columns_deleted": done["deleted"],
           "sheets_added": done["sheets"], "sheet_renamed": done["renamed"],
           "operations_skipped": done["skipped"],
           "pre_agent_copy": backup, "daily_backup": report["backup"],
           "notes": notes}
    if isinstance(count, dict):
        out["planned"] = {k: v for k, v in count.items() if v}
    return out, None


# ═══ 13. THE STAGING DRY RUN — before → after, computed, never guessed ══════
# ⚠️ THE PREVIEW IS A REAL EXECUTION ON A COPY. The alternative was to describe each op
# in words ("a sort would reorder rows"), which is a SECOND idea of what an op does and
# would drift from the one that applies. So staging deep-copies the snapshot it read off
# disk, runs the SAME run_ops the apply runs, and DIFFS the two. Every before→after row
# on Debi's card is therefore what will actually happen, including the rows a sort or an
# insert moved that nobody named — which is exactly the class of change the incident's
# per-call approval cards could never show.

def cell_face(cell) -> str:
    """What a cell SAYS, as one string: its formula if it has one, else its text.

    Formula-first because a formula is the thing that changed when a formula changed,
    and comparing cached values would call `=SUM(B1:B7)` unchanged after the row it
    sums moved."""
    if not isinstance(cell, dict):
        return ""
    f = cell.get("f")
    if isinstance(f, str) and f:
        return f
    return display_text(cell)


def snapshot_diff(before, after, limit=PREVIEW_MAX_CELLS):
    """[{sheet, ref, before, after}, …], total. EVERY cell whose face changed, in
    reading order, across every sheet — a sheet the ops ADDED included."""
    rows, total = [], 0
    seen_sheets = []
    for sid in sheet_ids(after):
        seen_sheets.append(sid)
        a = (after.get("sheets") or {}).get(sid) or {}
        b = ((before or {}).get("sheets") or {}).get(sid) or {}
        nm = a.get("name") or "?"
        coords = set()
        for src in (a, b):
            cd = src.get("cellData")
            if not isinstance(cd, dict):
                continue
            for r, row in cd.items():
                if not isinstance(row, dict):
                    continue
                for c in row:
                    try:
                        coords.add((int(r), int(c)))
                    except (TypeError, ValueError):
                        continue
        for r, c in sorted(coords):
            fb, fa = cell_face(cell_at(b, r, c)), cell_face(cell_at(a, r, c))
            if fb == fa:
                continue
            total += 1
            if len(rows) < max(int(limit or 0), 0):
                rows.append({"sheet": nm, "ref": a1(r, c), "before": fb, "after": fa})
    return rows, total


def op_summary(op) -> str:
    """One human line per operation, for the card's op list. PURE."""
    k = op.get("op")
    if k == "set":
        grid = op.get("values") or []
        h, w = len(grid), max((len(r) for r in grid), default=0)
        span = a1(op["r"], op["c"]) if h * w == 1 else (
            a1(op["r"], op["c"]) + ":" + a1(op["r"] + h - 1, op["c"] + w - 1))
        return f"set {span}"
    if k == "style":
        keys = ", ".join(sorted((op.get("set") or {}).keys()))
        return (f"format {a1(op['r0'], op['c0'])}:{a1(op['r1'], op['c1'])}"
                + (f" ({keys})" if keys else ""))
    if k == "sheet":
        if op.get("add"):
            return f"add a sheet called {op['add']!r}"
        return f"rename a sheet to {op.get('rename')!r}"
    if k == "resize":
        return (f"grow the sheet to {op.get('rows') or '—'} rows × "
                f"{op.get('cols') or '—'} columns")
    if k == "sort":
        return (f"sort the whole sheet by column {col_name(op['col'])}"
                + (" (Z→A)" if op.get("desc") else " (A→Z)"))
    if k == "insert":
        return (f"insert {op['n']} blank "
                + (f"row(s) above row {op['at'] + 1}" if op["axis"] == "row"
                   else f"column(s) left of column {col_name(op['at'])}"))
    if k == "delete_rc":
        return (f"DELETE {op['n']} "
                + (f"row(s) from row {op['at'] + 1}" if op["axis"] == "row"
                   else f"column(s) from column {col_name(op['at'])}"))
    if k == "create_workbook":
        return "create the workbook (it does not exist yet)"
    return str(k)


# ═══ 14. THE CHANGESET STORE — bridge-held, one pending per workbook ════════
# Keyed by (hermes session, workbook name) exactly as spec §1 rules. PROCESS-LOCAL and
# deliberately not durable, for the heartbeat's reason: a proposal that survived a
# bridge restart would be a card offering to write a file from a conversation nobody
# remembers. A restart loses pending proposals, which costs one re-ask.
_CHANGESETS: dict = {}           # changeset_id → the changeset dict
_PENDING: dict = {}              # (session, name) → changeset_id
_SESSION_LINES: dict = {}        # session → [outcome line, …] not yet shown to a model
_ACTIVE_SESSION: dict = {}       # session → last-seen-alive timestamp
ACTIVE_SESSION_TTL = 900.0


def _now(now=None) -> float:
    return float(now) if isinstance(now, (int, float)) else time.time()


def _sesskey(session) -> str:
    """A session id we can key on. '-' is the honest name for "we do not know which
    Hermes session this came from", NOT a wildcard: it is one bucket like any other."""
    s = str(session or "").strip()
    return s if s else "-"


def mark_session(session, now=None) -> str:
    """A Hermes turn is starting (or running) on this session. bridge/app.py's
    /api/hermes/chat relay calls this, which is the ONLY correlation available: an MCP
    tools/call carries the MCP TRANSPORT's session, never the Hermes one (Hermes keeps a
    single MCP client for the whole process). See active_session()."""
    key = _sesskey(session)
    if key == "-":
        return key
    _ACTIVE_SESSION[key] = _now(now)
    if len(_ACTIVE_SESSION) > 64:
        for k in sorted(_ACTIVE_SESSION, key=lambda k: _ACTIVE_SESSION[k])[:32]:
            _ACTIVE_SESSION.pop(k, None)
    return key


def active_session(now=None) -> str:
    """The Hermes session a staging call most likely belongs to: the most recently
    marked one, inside a generous TTL, else ''.

    ⚠️ AN HONEST APPROXIMATION, STATED AS ONE. Two Hermes turns running at the same
    moment would both look like "the newest", and the newer would win. That is survivable
    here and nowhere near the worst option: the changeset key is (session, NAME), the
    panel asks for a pending changeset BY NAME and prefers its own session, and a
    mismatch shows Debi a card for a workbook she can read on it — never a write.
    """
    t = _now(now)
    live = [(v, k) for k, v in _ACTIVE_SESSION.items() if t - v <= ACTIVE_SESSION_TTL]
    return max(live)[1] if live else ""


def clear_sessions() -> None:
    _ACTIVE_SESSION.clear()


def expire_changesets(now=None) -> int:
    """Drop every changeset past CHANGESET_TTL. Returns how many went."""
    t = _now(now)
    gone = [cid for cid, cs in _CHANGESETS.items() if t - cs["staged_at"] > CHANGESET_TTL]
    for cid in gone:
        _drop(cid)
    return len(gone)


def _drop(cid) -> None:
    cs = _CHANGESETS.pop(cid, None)
    if cs is not None and _PENDING.get(cs["key"]) == cid:
        _PENDING.pop(cs["key"], None)


def changeset_clear() -> None:
    _CHANGESETS.clear()
    _PENDING.clear()
    _SESSION_LINES.clear()


def get_changeset(cid, now=None):
    """The live changeset, or None. Expiry is checked on every read, so a card that sat
    on screen for twenty minutes cannot apply."""
    expire_changesets(now)
    cs = _CHANGESETS.get(str(cid or ""))
    return cs if isinstance(cs, dict) and cs.get("status") == "pending" else None


def pending_changeset(session=None, name=None, now=None):
    """The ONE pending changeset for (session, workbook), with two fallbacks that are
    about the honest limits of session correlation and nothing else:
      · asked for a session and a name and there is none → the pending changeset for
        that NAME under any session (there is one loffice session; a bridge restart or a
        re-minted sid must not orphan a proposal Debi can see the workbook of);
      · asked for no name → the newest pending changeset for that session.
    """
    expire_changesets(now)
    key = (_sesskey(session), str(name or ""))
    if name:
        cid = _PENDING.get(key)
        if cid and cid in _CHANGESETS:
            return _CHANGESETS[cid]
        for (sk, nm), cid in _PENDING.items():
            if nm == str(name) and cid in _CHANGESETS:
                return _CHANGESETS[cid]
        return None
    rows = [cs for cs in _CHANGESETS.values()
            if cs["status"] == "pending"
            and (not session or cs["key"][0] == _sesskey(session))]
    return max(rows, key=lambda cs: cs["staged_at"]) if rows else None


def public_changeset(cs) -> dict:
    """The changeset as the PANEL and the MODEL see it. The validated ops list stays
    private: it is the bridge's business how it will be carried out, and shipping it to
    the page would invite a page-side writer to grow around it."""
    if not isinstance(cs, dict):
        return {}
    return {"changeset_id": cs["id"], "name": cs["name"], "sheet": cs["sheet"],
            "session": cs["key"][0], "staged_at": cs["staged_at"],
            "staged_at_text": time.strftime("%H:%M:%S",
                                            time.localtime(cs["staged_at"])),
            "expires_at": cs["staged_at"] + CHANGESET_TTL,
            "op_count": len(cs["ops"]), "op_list": list(cs["op_list"]),
            "summary": cs["summary"], "preview": list(cs["preview"]),
            "preview_total": cs["preview_total"],
            "cells_changed": cs["preview_total"],
            "planned": dict(cs["planned"]), "notes": list(cs["notes"]),
            "creates_workbook": cs["creates_workbook"],
            "applied": False, "staged": True}


def stage_changes(root, session, name, sheet=None, ops=None, now=None):
    """(result, None) or (None, reason). THE ONLY WRITE-SHAPED TOOL, AND IT WRITES
    NOTHING (spec §1).

    It validates the ops, reads the workbook, runs them on a COPY, diffs, and records
    the proposal in the bridge's store. A new request REPLACES the pending changeset for
    that (session, workbook) — never accumulates, because "one intention, one card" is
    the whole ruling and a second card is the incident.
    """
    parsed, count, reason = validate_ops(ops)
    if parsed is None:
        return None, reason
    target, reason = office.doc_target(root, name, must_exist=False)
    if not target:
        return None, reason
    base = os.path.basename(target)
    creating = any(o.get("op") == "create_workbook" for o in parsed)
    exists = os.path.isfile(target)
    if not exists and not creating:
        return None, (f"there is no workbook called {base!r}. Call office_list to see "
                      "the real names, or stage a {\"op\":\"create_workbook\"} "
                      "operation first if you mean to make it.")
    if exists and creating:
        parsed = [o for o in parsed if o.get("op") != "create_workbook"]
        count = dict(count, creates=0)
        if not parsed:
            return None, (f"{base!r} already exists, so there is nothing to create and "
                          "the change asked for nothing else.")
    try:
        snap = (office.snapshot_from_path(target) if exists
                else office.empty_snapshot(os.path.splitext(base)[0]))
    except office.OfficeError as e:
        return None, str(e)
    sid = target_sid(snap, sheet)
    if not sid:
        return None, "that workbook has no readable sheets"
    after = copy.deepcopy(snap)
    done = run_ops(after, sid, parsed)
    if done is None:
        return None, "refused: those operations could not be applied to that sheet"
    preview, total = snapshot_diff(snap, after)
    op_list = [op_summary(o) for o in parsed]
    if not exists:
        op_list.insert(0, op_summary({"op": "create_workbook"}))
    notes = list(done["notes"])
    if not exists:
        notes.insert(0, f"{base!r} does not exist yet — applying this creates it.")
    st = open_state(base)
    if st["dirty"]:
        notes.append("Debi has UNSAVED edits in that workbook right now. Apply will "
                     "refuse until she saves or closes it — say so if she asks why.")
    summary = _summary_line(base, done, total, exists)
    t = _now(now)
    key = (_sesskey(session), base)
    cid = secrets.token_hex(8)
    old = _PENDING.get(key)
    if old:
        _drop(old)                       # REPLACED, never accumulated (spec §1)
    if len(_CHANGESETS) >= CHANGESET_MAX:
        for dead in sorted(_CHANGESETS, key=lambda c: _CHANGESETS[c]["staged_at"])[:4]:
            _drop(dead)
    _CHANGESETS[cid] = {
        "id": cid, "key": key, "name": base, "sheet": sheet or "",
        "ops": parsed, "op_list": op_list, "planned": {k: v for k, v in count.items()
                                                       if v},
        "preview": preview, "preview_total": total, "summary": summary,
        "notes": notes, "staged_at": t, "status": "pending",
        "creates_workbook": not exists,
        "file_mtime": (os.path.getmtime(target) if exists else 0.0),
    }
    _PENDING[key] = cid
    out = public_changeset(_CHANGESETS[cid])
    out["replaced"] = bool(old)
    out["message"] = NOT_APPLIED_SENTENCE
    out["notes"] = list(notes) + [NOT_APPLIED_SENTENCE, STAGED_NOTE]
    return out, None


def _summary_line(name, done, cells, exists) -> str:
    """The card's first line, and the model's own summary. PURE-ish."""
    bits = []
    if not exists:
        bits.append("create the workbook")
    if done["cells"]:
        bits.append(f"{done['cells']} cell{'' if done['cells'] == 1 else 's'} written")
    if done["cleared"]:
        bits.append(f"{done['cleared']} emptied")
    if done["styled_cells"]:
        bits.append(f"{done['styled_cells']} formatted")
    if done["sorted"]:
        bits.append("the sheet sorted")
    if done["inserted"]:
        bits.append(f"{done['inserted']} row/column(s) inserted")
    if done["deleted"]:
        bits.append(f"{done['deleted']} row/column(s) DELETED")
    if done["sheets"]:
        bits.append("sheet " + ", ".join(repr(s) for s in done["sheets"]) + " added")
    if done["renamed"]:
        bits.append(f"a sheet renamed to {done['renamed']!r}")
    what = ", ".join(bits) if bits else "no visible change"
    return (f"{name}: {what} — {cells} cell{'' if cells == 1 else 's'} would change.")


# ═══ 15. CHECKPOINTS (spec §3) ══════════════════════════════════════════════
# data/office/.checkpoints/<stem>/<changeset_id>.xlsx, last 10 per workbook. The
# `<stem>.pre-agent.xlsx` sibling STAYS (existing name, existing visibility ruling) as
# the most-recent-apply convenience copy; the stack is what makes "Undo this change" an
# answer about a SPECIFIC apply rather than about the last one.

def checkpoint_dir(root, name) -> str:
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    return os.path.join(office.office_dir(root), CHECKPOINT_DIR, stem)


def checkpoint_path(root, name, cid) -> str:
    return os.path.join(checkpoint_dir(root, name),
                        str(cid) + office.DOC_EXT)


def list_checkpoints(root, name) -> list:
    """Newest first: [{changeset_id, path, at, size_bytes}, …]."""
    d = checkpoint_dir(root, name)
    out = []
    try:
        entries = os.listdir(d)
    except OSError:
        return out
    for f in entries:
        if not f.endswith(office.DOC_EXT):
            continue
        p = os.path.join(d, f)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"changeset_id": f[: -len(office.DOC_EXT)], "path": p,
                    "at": st.st_mtime, "size_bytes": st.st_size})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


def push_checkpoint(root, name, cid):
    """(entry, None) or (None, reason). Copies the workbook AS IT IS NOW into the stack
    and prunes to CHECKPOINT_KEEP. Taken BEFORE the apply, like every other copy in this
    module — a checkpoint of the post-write file would be a checkpoint of nothing."""
    target, reason = office.doc_target(root, name)
    if not target:
        return None, reason
    d = checkpoint_dir(root, name)
    dst = checkpoint_path(root, name, cid)
    try:
        os.makedirs(d, exist_ok=True)
        shutil.copy2(target, dst)
    except OSError as e:
        return None, f"could not write the checkpoint for that workbook: {e}"
    pruned = prune_checkpoints(root, name)
    return {"changeset_id": str(cid), "file": os.path.basename(dst),
            "rel": os.path.join("data", "office", CHECKPOINT_DIR,
                                os.path.basename(d), os.path.basename(dst)),
            "pruned": pruned, "kept": len(list_checkpoints(root, name))}, None


def prune_checkpoints(root, name) -> list:
    """Delete everything past the newest CHECKPOINT_KEEP. Returns what went."""
    gone = []
    for e in list_checkpoints(root, name)[CHECKPOINT_KEEP:]:
        try:
            os.remove(e["path"])
            gone.append(e["changeset_id"])
        except OSError:
            pass
    return gone


def restore_checkpoint(root, name, cid, applied_mtime=None, now=None):
    """(report, None) or (None, reason) — "Undo this change".

    ⚠️ THE MTIME FENCE IS THE WHOLE POINT (spec §3). If the workbook moved since the
    apply — Debi saved over it, another apply landed, the editor wrote back — restoring
    would throw that away silently. So it REFUSES, in words, and says where the
    checkpoint still is. `applied_mtime=None` means "no fence recorded", which only
    happens for a checkpoint restored out of band; that path is allowed and SAYS so.
    """
    target, reason = office.doc_target(root, name)
    if not target:
        return None, reason
    src = checkpoint_path(root, name, cid)
    if not os.path.isfile(src):
        return None, ("there is no checkpoint for that change any more — the stack keeps "
                      f"the last {CHECKPOINT_KEEP} per workbook.")
    st = open_state(name)
    if st["dirty"]:
        return None, APPLY_DIRTY_REFUSAL
    fenced = isinstance(applied_mtime, (int, float)) and applied_mtime > 0
    try:
        live = os.path.getmtime(target)
    except OSError as e:
        return None, f"could not read that workbook: {e}"
    if fenced and abs(live - float(applied_mtime)) > FENCE_EPS:
        return None, UNDO_FENCE_REFUSAL.format(checkpoint=os.path.basename(src))
    # The file about to be replaced is itself worth keeping: an undo is a change too,
    # and "undo the undo" must not be a question with no answer.
    pre = pre_agent_for(target)
    try:
        shutil.copy2(target, pre)
        shutil.copy2(src, target)
        # ⚠️ AND THE CLOCK IS PUSHED FORWARD, WHICH IS NOT COSMETIC. copy2 preserves the
        # checkpoint's OWN mtime, which is older than the file it just replaced — and
        # every "did this file change under me?" check on this bridge (the page's
        # extPlan, the editor's writeback fence) reads a strictly NEWER mtime as the
        # change. Restoring an old copy with an old timestamp is a change nobody can
        # see. So the restored file is stamped NOW.
        os.utime(target, None)
    except OSError as e:
        return None, f"could not restore that checkpoint: {e}"
    return {"ok": True, "name": os.path.basename(target),
            "restored_from": os.path.basename(src),
            "changeset_id": str(cid), "fenced": fenced,
            "pre_agent_copy": os.path.basename(pre),
            "at": _now(now),
            "notes": ([] if fenced else
                      ["no post-apply mtime was recorded for this change, so the fence "
                       "could not be checked — the file as it was a moment ago is in "
                       + os.path.basename(pre) + "."])}, None


# ═══ 16. APPLY / DISMISS / UNDO, AND THE SESSION LINE ═══════════════════════
def push_session_line(session, line) -> None:
    """Queue one system line for the next turn of that Hermes session.

    ⚠️ WHY A QUEUE AND NOT AN INJECTION, MEASURED RATHER THAN ASSUMED. The vendored
    gateway (v2026.8.13) has no "append a message to an idle session" method at all. The
    nearest thing is `session.steer`, and reading AIAgent.steer / _drain_pending_steer
    (vendor/hermes/run_agent.py:3294, :3442, :3753) settles it: a steer is stashed and
    drained onto the LAST TOOL RESULT of the next tool batch. On an IDLE session that
    means the line would arrive AFTER the next turn's first model response — too late to
    condition the turn it is about — and `session.steer` also records a fake user bubble
    in the live transcript on the way (methods_session.py:3248). Both are worse than
    honest. So the outcome line is queued here and the panel PREPENDS it to Debi's next
    agent message, which puts it in the model's context BEFORE it thinks. Stated in the
    ship report; the panel's own test pins the prepend.
    """
    key = _sesskey(session)
    if not str(line or "").strip():
        return
    _SESSION_LINES.setdefault(key, []).append(str(line))
    if len(_SESSION_LINES[key]) > 8:
        del _SESSION_LINES[key][:-8]


def peek_session_lines(session) -> list:
    return list(_SESSION_LINES.get(_sesskey(session)) or [])


def drain_session_lines(session) -> list:
    """Take the queued lines and forget them. The panel calls this once, as it sends."""
    return _SESSION_LINES.pop(_sesskey(session), [])


def apply_changeset(root, cid, now=None):
    """(receipt, None) or (None, reason). The HUMAN gesture, and the only write path a
    changeset has.

    The receipt is spec §2's: {changeset_id, applied_at, cells_written, verify}. `verify`
    is a RE-READ OF THE TOUCHED CELLS FROM DISK after the save — not a restatement of
    what we meant to do, which is exactly the difference between a receipt and a claim.
    """
    cs = get_changeset(cid, now)
    if cs is None:
        return None, ("that change is no longer pending — it was already applied, "
                      "dismissed, or it expired (proposals last "
                      f"{int(CHANGESET_TTL // 60)} minutes).")
    name = cs["name"]
    t = _now(now)
    created = False
    if cs["creates_workbook"]:
        target, reason = office.doc_target(root, name, must_exist=False)
        if not target:
            return None, reason
        if not os.path.isfile(target):
            try:
                office.write_snapshot(
                    office.empty_snapshot(os.path.splitext(name)[0]), target)
            except office.OfficeError as e:
                return None, str(e)
            created = True
    checkpoint, reason = push_checkpoint(root, name, cs["id"])
    if checkpoint is None and not created:
        return None, reason
    ops = [o for o in cs["ops"] if o.get("op") != "create_workbook"]
    if ops:
        out, reason = _apply(root, name, cs["sheet"] or None, ops, cs["planned"],
                            "changeset")
        if out is None:
            return None, reason
    else:
        out = {"ok": True, "action": "changeset", "name": name, "sheet": "",
               "cells_written": 0, "cells_emptied": 0, "cells_formatted": 0,
               "sorted": 0, "rows_or_columns_inserted": 0,
               "rows_or_columns_deleted": 0, "sheets_added": [], "sheet_renamed": "",
               "operations_skipped": 0, "pre_agent_copy": "", "daily_backup": "",
               "notes": ["this changeset only created the workbook."]}
    verify, verify_note = _verify(root, name, cs)
    receipt_hash = secrets.token_hex(4)
    applied_mtime = 0.0
    try:
        tgt, _r = office.doc_target(root, name)
        applied_mtime = os.path.getmtime(tgt) if tgt else 0.0
    except OSError:
        pass
    cs["status"] = "applied"
    cs["applied_at"] = t
    cs["applied_mtime"] = applied_mtime
    cs["receipt"] = receipt_hash
    _PENDING.pop(cs["key"], None)
    line = APPLIED_LINE.format(cid=cs["id"], when=time.strftime(
        "%H:%M:%S", time.localtime(t)), receipt=receipt_hash,
        cells=out["cells_written"], name=name)
    push_session_line(cs["key"][0], line)
    return {"ok": True, "changeset_id": cs["id"], "receipt": receipt_hash,
            "applied_at": t,
            "applied_at_text": time.strftime("%H:%M:%S", time.localtime(t)),
            "name": name, "created_workbook": created,
            "cells_written": out["cells_written"],
            "cells_emptied": out["cells_emptied"],
            "cells_formatted": out["cells_formatted"],
            "sorted": out["sorted"],
            "rows_or_columns_inserted": out["rows_or_columns_inserted"],
            "rows_or_columns_deleted": out["rows_or_columns_deleted"],
            "sheets_added": out["sheets_added"],
            "operations_skipped": out["operations_skipped"],
            "verify": verify, "verify_note": verify_note,
            "checkpoint": checkpoint, "pre_agent_copy": out["pre_agent_copy"],
            "daily_backup": out["daily_backup"],
            "can_undo": bool(checkpoint), "applied_mtime": applied_mtime,
            "session_line": line, "notes": out["notes"]}, None


def _verify(root, name, cs):
    """Re-read the touched cells FROM DISK and report what they say now. This is what
    makes a receipt a receipt: the panel's success badge renders from these numbers, so
    a save that silently did nothing cannot look like a success."""
    target, reason = office.doc_target(root, name)
    if not target:
        return [], reason
    try:
        snap = office.snapshot_from_path(target)
    except office.OfficeError as e:
        return [], str(e)
    by_sheet = {}
    for i in sheet_ids(snap):
        by_sheet[(snap["sheets"][i] or {}).get("name")] = snap["sheets"][i]
    rows, matched = [], 0
    for p in cs["preview"]:
        sh = by_sheet.get(p["sheet"])
        rg = act_range(p["ref"])
        got = cell_face(cell_at(sh, rg[0], rg[1])) if (sh and rg) else ""
        ok = got == p["after"]
        matched += 1 if ok else 0
        rows.append({"sheet": p["sheet"], "ref": p["ref"], "expected": p["after"],
                     "found": got, "match": ok})
    note = (f"{matched} of {len(rows)} re-read cell(s) hold what the change said they "
            "would" + ("." if matched == len(rows) else
                       " — the ones that do not are listed above."))
    if cs["preview_total"] > len(cs["preview"]):
        note += (f" (the change touched {cs['preview_total']} cells; the first "
                 f"{len(cs['preview'])} were verified.)")
    return rows, note


def dismiss_changeset(root, cid, now=None):
    """(report, None) or (None, reason). NOTHING is written, and the session is TOLD."""
    cs = get_changeset(cid, now)
    if cs is None:
        return None, "that change is no longer pending — nothing to dismiss."
    t = _now(now)
    cs["status"] = "dismissed"
    cs["dismissed_at"] = t
    _PENDING.pop(cs["key"], None)
    line = DISMISSED_LINE.format(cid=cs["id"], when=time.strftime(
        "%H:%M:%S", time.localtime(t)), name=cs["name"])
    push_session_line(cs["key"][0], line)
    return {"ok": True, "changeset_id": cs["id"], "name": cs["name"],
            "dismissed_at": t, "session_line": line,
            "notes": ["nothing was written — this proposal never touched the "
                      "workbook."]}, None


def undo_changeset(root, cid, now=None):
    """(report, None) or (None, reason). Restores the checkpoint that apply pushed."""
    cs = _CHANGESETS.get(str(cid or ""))
    if not isinstance(cs, dict) or cs.get("status") != "applied":
        # A checkpoint outlives the changeset that made it (the store is process-local,
        # the files are not), so an undo with no record is still ANSWERED — just without
        # the mtime fence, and the report says the fence was not checked.
        cs = None
    name = ""
    fence = None
    if cs is not None:
        name, fence = cs["name"], cs.get("applied_mtime")
    else:
        for entry in _checkpoint_owner(root, cid):
            name = entry
            break
        if not name:
            return None, ("that change is not one this bridge remembers applying, and "
                          "no checkpoint for it is on disk.")
    out, reason = restore_checkpoint(root, name, cid, fence, now)
    if out is None:
        return None, reason
    if cs is not None:
        cs["status"] = "undone"
        line = UNDONE_LINE.format(cid=cs["id"], when=time.strftime(
            "%H:%M:%S", time.localtime(out["at"])), name=name)
        push_session_line(cs["key"][0], line)
        out["session_line"] = line
    return out, None


def _checkpoint_owner(root, cid):
    """Which workbook stems hold a checkpoint with this id. Used only by the
    no-record undo path above."""
    base = os.path.join(office.office_dir(root), CHECKPOINT_DIR)
    try:
        stems = os.listdir(base)
    except OSError:
        return []
    out = []
    for stem in stems:
        if os.path.isfile(os.path.join(base, stem, str(cid) + office.DOC_EXT)):
            out.append(stem + office.DOC_EXT)
    return out
