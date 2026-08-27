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

import functools
import json
import math
import os
import re
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

PRE_AGENT_SUFFIX = ".pre-agent" + office.DOC_EXT

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
             "deletes": 0}
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
        elif kind == "sheet":
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
            "skipped": 0, "sorted": 0, "inserted": 0, "deleted": 0, "notes": []}
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


def _write(root, name, sheet, ops, count, label):
    """The ONE write path every write tool goes through: dirty-refusal, pre-agent copy,
    run, save. Nothing else in this module writes a workbook."""
    target, reason = office.doc_target(root, name)
    if not target:
        return None, reason
    st = open_state(name)
    if st["dirty"]:
        return None, DIRTY_REFUSAL
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


def op_write_cells(root, name, sheet=None, ops=None):
    """The `set`/`style`/`sheet`/`resize` grammar, same caps, refuse-over-cap."""
    parsed, count, reason = validate_ops(ops)
    if parsed is None:
        return None, reason
    return _write(root, name, sheet, parsed, count, "write_cells")


def op_sort(root, name, sheet=None, col=None, desc=False):
    """Sort the WHOLE sheet by one column, row 1 included. Refuses on merges."""
    parsed, count, reason = validate_ops([{"op": "sort", "col": col, "desc": desc}])
    if parsed is None:
        return None, reason
    out, reason = _write(root, name, sheet, parsed, count, "sort")
    if out is not None and not out["sorted"] and not out["operations_skipped"]:
        out["notes"].insert(0, "the rows were already in that order — nothing moved.")
    if out is not None:
        out["notes"].insert(0, "this sorted the whole sheet, ROW 1 INCLUDED: LOffice "
                               "does not guess at a header row. Blank cells went to "
                               "the bottom in both directions.")
    return out, reason


def op_insert_delete(root, name, sheet=None, action=None, what=None, at=None, n=1):
    """Insert blank rows/columns, or delete them. Merges shift/grow/shrink; formula
    references are NOT rewritten and the result says so."""
    kind = ("" if action is None else str(action)).strip().lower()
    if kind in ("insert", "add"):
        op = "insert"
    elif kind in ("delete", "delete_rc", "remove"):
        op = "delete_rc"
    else:
        return None, ('"action" must be "insert" or "delete"'
                      f" (got {json.dumps(action)})")
    parsed, count, reason = validate_ops([{"op": op, "what": what, "at": at, "n": n}])
    if parsed is None:
        return None, reason
    return _write(root, name, sheet, parsed, count, op)


def op_create(root, name):
    """A new, empty workbook. NEVER clobbers: office.free_name's ' (n)' walk, so a name
    already taken comes back stepped rather than refused — a create is the one gesture
    where the model's intent ("give me a workbook") survives a renamed result."""
    stem = act_doc_name(name)
    final, reason = office.free_name(root, stem or office.DEFAULT_DOC_STEM)
    if not final:
        return None, reason
    target, reason = office.doc_target(root, final, must_exist=False)
    if not target:
        return None, reason
    try:
        office.write_snapshot(office.empty_snapshot(final), target)
    except office.OfficeError as e:
        return None, str(e)
    notes = ["it holds one empty sheet called Sheet1 — use office_write_cells to put "
             "something in it."]
    if stem and final != (stem + office.DOC_EXT):
        notes.insert(0, f"a workbook called {stem + office.DOC_EXT!r} already existed, "
                        f"so this one is {final!r} — nothing was overwritten.")
    return {"ok": True, "action": "create", "name": final, "notes": notes}, None
