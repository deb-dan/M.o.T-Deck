"""Harness-native OFFICE lane — slice 1, SHEETS ONLY (.xlsx).

Built to docs/research/2026-08-20-office-lane-recon.md §5/§7 and the Fable rulings
of 2026-08-21. Same shape as the voice and music lanes and deliberately NOT a
component: no port, no manifest entry, no daemon, no second process. Univer
(Apache-2.0) is vendored as UMD assets our own bridge serves from /assets/vendor/
univer; THIS module is the half Univer does not give away — the .xlsx round-trip.

WHY WE OWN THE ROUND-TRIP: Univer's own import/export is `@univerjs-pro/
exchange-client`, which needs Univer Server (Docker-shaped, commercially licensed).
Univer's docs name the escape hatch outright — parse the file with an open-source
library into the `IWorkbookData` shape and hand it to the facade. openpyxl (MIT,
pure python, already wheelhouse-friendly) is that library.

THE FIDELITY CONTRACT, said in the UI in these words and honoured here:

    "Values, formulas and basic formatting round-trip. Complex styling may be
     simplified — keep your original file; Office saves copies."

Concretely: cell values, cell types, formulas, number formats, bold/italic/
underline, font name+size, font colour, fill colour, horizontal+vertical
alignment, merged ranges, column widths and row heights survive. Charts, images,
pivot tables, conditional formatting, data validation, comments, defined names,
borders and print settings DO NOT — a save writes a NEW workbook from the
snapshot, so anything not in the snapshot is not in the output. That is why a
save of a pre-existing file takes a `.bak` first (see `backup_for`).

TOTALITY IS THE RULE, both directions. Every value here comes off a wire or out
of a third-party file: a surprise type, a NaN, a junk row key or a cell dict that
is a string must cost that one cell, never the workbook and never a 500.

Everything decision-shaped is a PURE function so it can be table-tested:
name validation, containment, the cell/style mappers both ways, the backup name.
See bridge/tests/test_office_lane.py.
"""
from __future__ import annotations

import datetime as _dt
import math
import io as _io
import os
import re
import shutil
import tempfile
import time

# openpyxl is declared in bridge/requirements.txt, but a snapshot that has not been
# re-provisioned since this lane landed will not have it. Import defensively for the
# same reason app.py imports THIS module defensively: the bridge must still boot, and
# the Office page must say what is missing instead of 500-ing.
try:                                                             # pragma: no cover
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    _OPENPYXL_ERR = ""
except Exception as _e:                                          # noqa: BLE001
    openpyxl = None                                              # type: ignore
    Alignment = Font = PatternFill = None                        # type: ignore
    get_column_letter = None                                     # type: ignore
    _OPENPYXL_ERR = str(_e)[:200]


# ── constants ────────────────────────────────────────────────────────────────
DOC_EXT = ".xlsx"
# ⚠️ THE FIDELITY SENTENCE IS PER SAVE PATH AS OF loffice-2026-08-28d, AND THE SPLIT IS
# THE WHOLE FIX (live finding L3, server finding F-27). It was ONE sentence describing
# the openpyxl mapper, printed globally — while the surface a user actually saves
# through is the embedded ONLYOFFICE editor, whose x2t round-trip MEASURABLY keeps
# charts, images, autofilters, data validation, hyperlinks and freeze panes (measured
# on QA-rich.xlsx: chart1.xml 1159 B → 3020 B, every feature still present). Telling
# her the app drops all of that was a lie in our own disfavour, and it drove her away
# from the app.
#
# TWO PATHS, TWO SENTENCES, and every surface now names WHICH one it is about:
#   · FIDELITY_EDITOR_NOTE — the editor's ⌘S (asc_nativeGetFile → x2t → writeback).
#     This is the normal save and it is high fidelity.
#   · FIDELITY_NOTE — the FILE path: office.write_snapshot through openpyxl. Reached by
#     a `sort` op, an agent changeset apply, and LOffice's own tier-1 grid. This one
#     really does lose the things named in it, and now it names them ALL rather than
#     three of them (F-27 added freeze panes, hidden rows/columns, gridline visibility
#     and autofilter to the round-trip, so those four came OFF this list).
FIDELITY_NOTE = ("this save rewrote the whole workbook through LOffice's own .xlsx "
                 "mapper, which carries values, formulas, dates, number formats, "
                 "fonts, fills, alignment, merges, widths, heights, freeze panes, "
                 "hidden rows and columns, gridline visibility and autofilter — but "
                 "NOT charts, images, pivot tables, conditional formatting, cell "
                 "borders, comments, named ranges or macros. Saving from the full "
                 "editor (⌘S) keeps all of those.")
FIDELITY_EDITOR_NOTE = ("a save from the full editor round-trips the workbook through "
                        "the editor's own converter and keeps charts, images, "
                        "autofilters, data validation, hyperlinks, freeze panes and "
                        "conditional formatting. Measured, not assumed.")
NAME_MAX = 80
# Where the checkpoint stack and the pre-agent copies live. ⚠️ MIRRORED IN
# bridge/office_ops.py (which reads it from here) and in bridge/panel/office.html.
CHECKPOINT_DIR = ".checkpoints"
# ⚠️ THE PRE-AGENT COPY MOVED INSIDE .checkpoints/<stem>/ AT loffice-2026-08-28d, and it
# is a deliberate deviation from the old sibling-file ruling — see office_ops.pre_agent_for
# for the argument (server findings F-07, F-22, live finding C4).
PRE_AGENT_NAME = "pre-agent" + DOC_EXT
# Excel refuses these in a sheet title, and openpyxl raises ValueError rather than
# repairing — which used to escape apply_changeset as an HTTP 500 (F-19).
SHEET_TITLE_BAD = ":\\/?*[]"
SHEET_NAME_MAX = 31            # Excel's own limit; openpyxl truncates past it
# A snapshot travels as JSON through a WKWebView. 200k cells is far past any workbook
# a person edits by hand and still well inside what JSON.stringify survives; past it
# we stop reading and SAY the sheet was truncated rather than hanging the tab.
MAX_CELLS = 200_000
# Import cap. A spreadsheet that big is past what the 200k-cell reader will show
# anyway; the point of the cap is that a webview cannot hand the bridge an arbitrary
# amount of memory in one body.
UPLOAD_MAX_BYTES = 30 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
DEFAULT_ROWS, DEFAULT_COLS = 100, 26
DEFAULT_ROW_PX, DEFAULT_COL_PX = 24, 88

# Univer enums, read out of the pinned UMD bundle (@univerjs/presets 0.25.1) rather
# than from memory — a wrong number here is a silently wrong cell.
#   CellValueType   STRING=1 NUMBER=2 BOOLEAN=3 FORCE_STRING=4
#   HorizontalAlign UNSPECIFIED=0 LEFT=1 CENTER=2 RIGHT=3
#   VerticalAlign   UNSPECIFIED=0 TOP=1 MIDDLE=2 BOTTOM=3
CV_STRING, CV_NUMBER, CV_BOOLEAN, CV_FORCE_STRING = 1, 2, 3, 4
H_ALIGN = {"left": 1, "center": 2, "centerContinuous": 2, "right": 3}
H_ALIGN_BACK = {1: "left", 2: "center", 3: "right"}
V_ALIGN = {"top": 1, "center": 2, "bottom": 3}
V_ALIGN_BACK = {1: "top", 2: "center", 3: "bottom"}

# openpyxl column width is in "characters"; Univer's is pixels. 7px per character is
# the conventional approximation for the default 11pt Calibri grid — exact fidelity
# would need font metrics we do not have, and the contract says basic formatting.
DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE = "Calibri", 11.0

# The name a workbook gets when nobody typed one — see create_doc's empty-name case.
# The ' (n)' step is free_name's, so this is `Untitled.xlsx`, `Untitled (2).xlsx`, …
# rather than `Untitled 2.xlsx`: one never-clobber convention in this codebase, shared
# with artifact-save, the voice clips and the .xlsx import.
DEFAULT_DOC_STEM = "Untitled"

PX_PER_CHAR = 7.0
PT_PER_PX = 0.75               # row height: openpyxl points ↔ Univer pixels

# ── the boot beacon ──────────────────────────────────────────────────────────
# THE PROBLEM THIS EXISTS FOR: this page failed twice on a Mac nobody here can reach,
# and every hypothesis about WHY was unfalsifiable from a screenshot of a blank
# rectangle. So the page now phones home at every step of its own boot and the
# bridge writes it down. The next report is one command, not a theory:
#
#     grep loffice ~/Library/Application\ Support/Harness/data/logs/bridge.log
#
# The trace also lands in its own file (data/logs/loffice-boot.log, viewable in the
# panel's log picker) so it survives a bridge log that has rolled past it.
DIAG_LOG_NAME = "loffice-boot"
DIAG_MAX_LINES = 400
DIAG_STAGE_MAX = 40
DIAG_DETAIL_MAX = 400

# Excel's day-zero. 1899-12-30, not 12-31: the 1900 leap-year bug means serial 60 is
# a date that never existed, and every spreadsheet since has compensated the same way.
_EPOCH = _dt.datetime(1899, 12, 30)


def openpyxl_error() -> str:
    """'' when the round-trip is available, else why it is not."""
    return _OPENPYXL_ERR


# ── paths, names, containment ────────────────────────────────────────────────
def office_dir(root) -> str:
    """Where workbooks live. Fixed in slice 1 (the music lane's configurable-dir
    machinery is a later slice); created on demand so a fresh install has one."""
    d = os.path.join(str(root), "data", "office")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def is_backup_name(name) -> bool:
    """`sheet.20260821.bak.xlsx` — our own safety copies, hidden from the list so
    the file column does not double in length after a week of editing."""
    return isinstance(name, str) and name.lower().endswith(".bak" + DOC_EXT)


def is_agent_copy_name(name) -> bool:
    """`sheet.pre-agent.xlsx` — the LEGACY sibling copies an agent write used to leave
    in data/office (live finding C4, server finding F-07).

    ⚠️ THESE ARE NO LONGER CREATED. The copy now lives at
    `.checkpoints/<stem>/pre-agent.xlsx`, so this predicate exists to stop the ones
    already on disk from being listed as ordinary workbooks — indistinguishable from
    real documents, with a download/delete pair, and the sentence that created them
    long gone. Filtered exactly the way `.bak` copies are, and for exactly the reason:
    a safety copy is not a document.

    ⚠️ DEVIATION FOR FABLE, STATED OUT LOUD: this CHANGES VISIBILITY. A workbook Debi
    deliberately named `something.pre-agent.xlsx` herself would disappear from the rail.
    That is judged the lesser harm — the old behaviour let the first agent apply on
    `report.xlsx` silently OVERWRITE such a file (F-07) — and `checkpoint_pre_agent`'s
    namespacing means nothing writes to that name any more, so nothing can be lost by
    it. The files stay on disk and File → Download of the real workbook is unaffected.
    """
    return isinstance(name, str) and name.lower().endswith(".pre-agent" + DOC_EXT)


def checkpoint_root(root) -> str:
    return os.path.join(office_dir(root), CHECKPOINT_DIR)


def agent_copy_path(root, name) -> str:
    """`data/office/.checkpoints/<stem>/pre-agent.xlsx` — the pre-write copy of ONE
    workbook, namespaced so it can never collide with a document."""
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    return os.path.join(checkpoint_root(root), stem, PRE_AGENT_NAME)


def agent_copy_rel(name) -> str:
    """The same path as the panel and the tool results say it: a relative path, so
    nobody reads it as a sibling workbook they could open."""
    stem = os.path.splitext(os.path.basename(str(name)))[0]
    return CHECKPOINT_DIR + "/" + stem + "/" + PRE_AGENT_NAME


def valid_name(name):
    """(safe_basename, None) or (None, reason).

    The name comes off the wire in every route here, so this is the ONE place that
    decides what a workbook may be called: a basename, no traversal, no dotfile, no
    separators, `.xlsx` FORCED (a caller may omit it; a caller may not pick another).
    """
    if not isinstance(name, str) or not name.strip():
        return None, "no file name given"
    name = name.strip()
    if name in (".", "..") or name != os.path.basename(name):
        return None, "refused: a workbook is addressed by name, not by path"
    if "/" in name or "\\" in name or os.sep in name or name.startswith("."):
        return None, "refused: a workbook is addressed by name, not by path"
    if "\x00" in name:
        return None, "refused: that name is not a file name"
    stem, ext = os.path.splitext(name)
    if ext and ext.lower() != DOC_EXT:
        return None, f"refused: slice 1 is spreadsheets only ({DOC_EXT})"
    if not stem.strip():
        return None, "no file name given"
    safe = stem.strip() + DOC_EXT
    if len(safe) > NAME_MAX:
        return None, f"refused: that name is longer than {NAME_MAX} characters"
    return safe, None


def doc_target(root, name, must_exist: bool = True):
    """(path, None) or (None, reason) — the boundary for open/save/delete/download.

    Basename + realpath containment strictly under data/office: the `library_target`
    / `_deletable_target` discipline, so no traversal and no symlink escape.
    """
    safe, reason = valid_name(name)
    if not safe:
        return None, reason
    base = os.path.realpath(office_dir(root))
    target = os.path.realpath(os.path.join(base, safe))
    if not target.startswith(base + os.sep):
        return None, "refused: that path is outside the Office folder"
    if must_exist and not os.path.isfile(target):
        return None, "no such workbook"
    return target, None


def backup_for(path, today=None) -> str:
    """`<stem>.<YYYYMMDD>.bak.xlsx` beside the file.

    ONE backup per file per DAY (Fable-tagged judgment call): a save writes a NEW
    workbook from the snapshot, so a file that arrived from Excel can lose things
    the snapshot never carried — the pre-edit copy of the day it was first touched
    must survive. Per-save copies would fill the folder during normal editing;
    per-day keeps exactly the version that existed before today's session.
    """
    stem = os.path.splitext(str(path))[0]
    day = today or time.strftime("%Y%m%d")
    return f"{stem}.{day}.bak{DOC_EXT}"


def list_docs(root) -> list:
    """Every workbook, newest first. Backups are on disk but not in this list.

    ⚠️ `agent_copy` IS NOT DECORATION (live finding L4). The page's external-change
    banner used to promise `<name>.pre-agent.xlsx` on ANY mtime change — Excel, a
    script, a second tab, a `git checkout` — while only a changeset apply ever writes
    one. The dirty variant offered "Keep mine" on the strength of a backup that was not
    there. So the row now carries whether that copy ACTUALLY exists, per path, and the
    banner says only what is true.
    """
    d = office_dir(root)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if (not n.lower().endswith(DOC_EXT) or is_backup_name(n)
                or is_agent_copy_name(n) or n.startswith("~$")):
            continue
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        agent = agent_copy_path(root, n)
        out.append({"name": n, "size_bytes": st.st_size, "modified": st.st_mtime,
                    "has_backup": bool(_any_backup(p)),
                    "agent_copy": (agent_copy_rel(n) if os.path.isfile(agent) else "")})
    out.sort(key=lambda e: e["modified"], reverse=True)
    return out


def _any_backup(path) -> str:
    """The newest .bak beside a workbook, or ''. Cheap: one listdir of our own dir."""
    d, base = os.path.split(str(path))
    stem = os.path.splitext(base)[0]
    best = ""
    try:
        for n in os.listdir(d):
            if n.startswith(stem + ".") and is_backup_name(n):
                if n > best:
                    best = n
    except OSError:
        return ""
    return best


# ── small total helpers ──────────────────────────────────────────────────────
def _num(v, default=None):
    """A finite number, or the default. NaN/inf are neither JSON nor a cell value."""
    if isinstance(v, bool) or v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _idx(key):
    """A non-negative integer row/column key, or None. Snapshot keys arrive as JSON
    object keys, i.e. STRINGS — '3' and 3 must mean the same row."""
    if isinstance(key, bool):
        return None
    try:
        i = int(key)
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < 1_048_576 else None


def _rgb(color) -> str:
    """openpyxl Color → '#rrggbb', or '' when it is a theme/indexed colour we cannot
    resolve without the workbook's theme (we do not guess a colour)."""
    try:
        if color is None or getattr(color, "type", "") != "rgb":
            return ""
        v = getattr(color, "rgb", None)
        if not isinstance(v, str) or len(v) not in (6, 8):
            return ""
        return "#" + (v[-6:]).lower()
    except Exception:                                            # noqa: BLE001
        return ""


def _hex_to_argb(v) -> str:
    """'#rrggbb' / 'rrggbb' → 'FFRRGGBB' for openpyxl, or '' if it is not a colour."""
    if not isinstance(v, str):
        return ""
    s = v.strip().lstrip("#")
    if len(s) == 8:
        s = s[2:]
    if len(s) != 6 or any(c not in "0123456789abcdefABCDEF" for c in s):
        return ""
    return "FF" + s.upper()


def valid_sheet_title(name):
    """('', ) → (safe, None) or (None, reason). THE ONE PLACE that decides whether a
    sheet title can be written at all.

    ⚠️ IT EXISTS BECAUSE openpyxl RAISES, NOT BECAUSE EXCEL IS FUSSY (F-19). A title
    holding `:` made `wb.create_sheet` throw a bare ValueError out through
    `apply_changeset` and out through the route as an HTTP 500 with a traceback — after
    the checkpoint, the daily `.bak` and the pre-agent copy had all been taken, and with
    the whole changeset lost. A refusal with a sentence, at validation time, costs one
    operation instead.
    """
    s = "" if name is None else str(name).strip()
    if not s:
        return None, "a sheet needs a name"
    bad = sorted({c for c in s if c in SHEET_TITLE_BAD})
    if bad:
        return None, ("a sheet name cannot contain " + " ".join(bad)
                      + " — Excel refuses those characters in a sheet title")
    if s.startswith("'") or s.endswith("'"):
        return None, "a sheet name cannot start or end with an apostrophe"
    if len(s) > SHEET_NAME_MAX:
        return None, f"a sheet name is at most {SHEET_NAME_MAX} characters"
    if s.lower() == "history":
        return None, "'History' is reserved by Excel and cannot be a sheet name"
    return s, None


# ── dates, both directions ───────────────────────────────────────────────────
# ⚠️ THE INVERSE OF excel_serial, AND IT IS A HONESTY FIX RATHER THAN A FEATURE
# (findings F-10, F-11). A date cell is a NUMBER with a date number-format on it; the
# tool result used to hand the model `{"value": 46037.0, "text": "46037"}` and the
# card's before→after column printed `46034 (yyyy-mm-dd)`. An agent asked "what is the
# invoice date in A1" answered 46037, and a text date written into a date-formatted cell
# read as a FIX on the card ("46034 → 2026-01-15") when it was in fact the $2,500
# incident with the visual tell removed.
_DATE_TOKENS = re.compile(r"[ymdhs]", re.IGNORECASE)


def is_date_format(pattern) -> bool:
    """Does this number-format pattern render its cell as a DATE or a TIME? PURE.

    Quoted literals and [bracketed] sections are stripped first, so `0.00" kg"` and
    `[$-409]#,##0` are not mistaken for dates by the letters inside them. A pattern
    holding `@` is a TEXT format and is never a date.
    """
    p = str(pattern or "")
    if not p or p.strip().lower() == "general":
        return False
    p = re.sub(r'"[^"]*"', "", p)
    p = re.sub(r"\[[^\]]*\]", "", p)
    p = re.sub(r"\\.", "", p)
    if "@" in p:
        return False
    return bool(_DATE_TOKENS.search(p))


def is_text_format(pattern) -> bool:
    """`@` — the pattern that MEANS "this cell is text on purpose" (F-09, F-28)."""
    p = str(pattern or "").strip().strip('"')
    return p == "@"


def serial_text(serial, pattern="") -> str:
    """A date serial → 'YYYY-MM-DD' (or with a time when the value has a fraction, or
    a bare 'HH:MM:SS' when it is under a day). '' when it is not a usable serial.

    Deliberately ISO rather than a re-implementation of Excel's pattern language: the
    goal is that a human and a model can both read the cell, and inventing a second
    number-format renderer would be a second thing to get wrong. The PATTERN travels
    alongside so the reader can see how the sheet shows it.
    """
    n = _num(serial)
    if n is None or n < 0 or n > 2_958_465:            # 0 … 9999-12-31
        return ""
    try:
        days = int(n)
        frac = float(n) - days
        secs = int(round(frac * 86400.0))
        if secs >= 86400:
            days, secs = days + 1, 0
        if days == 0:
            return "%02d:%02d:%02d" % (secs // 3600, (secs // 60) % 60, secs % 60)
        d = _EPOCH + _dt.timedelta(days=days, seconds=secs)
    except (OverflowError, ValueError):
        return ""
    if secs:
        return d.strftime("%Y-%m-%d %H:%M:%S")
    return d.strftime("%Y-%m-%d")


def excel_serial(value) -> float:
    """datetime/date/time → the spreadsheet serial number Univer stores dates as."""
    if isinstance(value, _dt.datetime):
        delta = value - _EPOCH
        return delta.days + delta.seconds / 86400.0
    if isinstance(value, _dt.date):
        return float((_dt.datetime(value.year, value.month, value.day) - _EPOCH).days)
    if isinstance(value, _dt.time):
        return (value.hour * 3600 + value.minute * 60 + value.second) / 86400.0
    return 0.0


# ── style mapping ────────────────────────────────────────────────────────────
def style_from_cell(cell) -> dict:
    """openpyxl cell → a Univer inline style dict (only keys we actually carry).

    Emitting NOTHING for an unstyled cell matters: an empty dict per cell would
    triple the snapshot for a plain workbook.
    """
    s = {}
    # openpyxl hands back a fully-populated Font/Fill/Alignment for EVERY cell in the
    # used range, styled or not — so without this gate a plain 20x10 sheet ships 200
    # style dicts saying "Calibri 11" and every blank cell inside a used range becomes
    # a snapshot entry. `has_style` is openpyxl's own "this cell has a style id".
    if not getattr(cell, "has_style", True):
        return s
    try:
        f = cell.font
        if f is not None:
            if f.bold:
                s["bl"] = 1
            if f.italic:
                s["it"] = 1
            if f.underline:
                s["ul"] = {"s": 1}
            if f.strike:
                s["st"] = {"s": 1}
            # The workbook default (Calibri 11) is a no-op worth omitting: carrying
            # it would put a font key on every styled cell for no visible effect.
            if f.name and str(f.name) != DEFAULT_FONT_NAME:
                s["ff"] = str(f.name)
            size = _num(f.size)
            if size and size > 0 and size != DEFAULT_FONT_SIZE:
                s["fs"] = size
            rgb = _rgb(f.color)
            if rgb:
                s["cl"] = {"rgb": rgb}
    except Exception:                                            # noqa: BLE001
        pass
    try:
        fill = cell.fill
        if fill is not None and getattr(fill, "patternType", None) == "solid":
            rgb = _rgb(getattr(fill, "fgColor", None))
            # White-on-white is openpyxl's default for a themed sheet; carrying it
            # would repaint every cell of an unstyled workbook.
            if rgb and rgb != "#ffffff":
                s["bg"] = {"rgb": rgb}
    except Exception:                                            # noqa: BLE001
        pass
    try:
        al = cell.alignment
        if al is not None:
            h = H_ALIGN.get(al.horizontal or "")
            if h:
                s["ht"] = h
            v = V_ALIGN.get(al.vertical or "")
            if v:
                s["vt"] = v
            if al.wrapText:
                s["tb"] = 3                    # WrapStrategy.WRAP
    except Exception:                                            # noqa: BLE001
        pass
    try:
        nf = cell.number_format
        if isinstance(nf, str) and nf and nf != "General":
            s["n"] = {"pattern": nf}
    except Exception:                                            # noqa: BLE001
        pass
    return s


def apply_style(cell, style) -> None:
    """A Univer style dict → openpyxl, ignoring anything we do not understand."""
    if not isinstance(style, dict):
        return
    try:
        kw = {}
        if style.get("bl"):
            kw["bold"] = True
        if style.get("it"):
            kw["italic"] = True
        ul = style.get("ul")
        if ul and (ul is True or (isinstance(ul, dict) and ul.get("s"))):
            kw["underline"] = "single"
        stk = style.get("st")
        if stk and (stk is True or (isinstance(stk, dict) and stk.get("s"))):
            kw["strike"] = True
        if isinstance(style.get("ff"), str) and style["ff"].strip():
            kw["name"] = style["ff"].strip()
        fs = _num(style.get("fs"))
        if fs and 1 <= fs <= 409:
            kw["size"] = fs
        cl = style.get("cl")
        argb = _hex_to_argb(cl.get("rgb") if isinstance(cl, dict) else cl)
        if argb:
            kw["color"] = argb
        if kw:
            cell.font = Font(**kw)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        bg = style.get("bg")
        argb = _hex_to_argb(bg.get("rgb") if isinstance(bg, dict) else bg)
        if argb:
            cell.fill = PatternFill(fill_type="solid", start_color=argb, end_color=argb)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        h = H_ALIGN_BACK.get(style.get("ht"))
        v = V_ALIGN_BACK.get(style.get("vt"))
        wrap = True if style.get("tb") == 3 else None
        if h or v or wrap:
            cell.alignment = Alignment(horizontal=h, vertical=v, wrapText=wrap)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        n = style.get("n")
        pattern = n.get("pattern") if isinstance(n, dict) else n
        if isinstance(pattern, str) and pattern.strip():
            cell.number_format = pattern
    except Exception:                                            # noqa: BLE001
        pass


# ── xlsx → IWorkbookData ─────────────────────────────────────────────────────
def cell_snapshot(cell, cached=None) -> dict:
    """One openpyxl cell → a Univer cell dict, or {} when there is nothing to say.

    A formula is carried as `f` (Univer recomputes it); when the file also holds a
    CACHED result — which it does whenever Excel/LibreOffice last wrote it — that
    value rides along as `v`, so a formula Univer's engine does not implement still
    shows the number the user saw in Excel.
    """
    out = {}
    v = cell.value
    if isinstance(v, str) and v.startswith("="):
        out["f"] = v
        cv = cached
        if isinstance(cv, (int, float)) and not isinstance(cv, bool):
            n = _num(cv)
            if n is not None:
                out["v"], out["t"] = n, CV_NUMBER
        elif isinstance(cv, str) and cv:
            out["v"], out["t"] = cv, CV_STRING
    elif isinstance(v, bool):
        out["v"], out["t"] = v, CV_BOOLEAN
    elif isinstance(v, (int, float)):
        n = _num(v)
        if n is not None:
            out["v"] = int(n) if float(n).is_integer() and abs(n) < 2 ** 53 else n
            out["t"] = CV_NUMBER
    elif isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        out["v"], out["t"] = excel_serial(v), CV_NUMBER
    elif isinstance(v, str):
        if v:
            out["v"], out["t"] = v, CV_STRING
    elif v is not None:
        out["v"], out["t"] = str(v), CV_STRING
    style = style_from_cell(cell)
    if style:
        out["s"] = style
    # ⚠️ FORCE_STRING IS RE-DERIVED FROM THE `@` NUMBER FORMAT (finding F-28), because
    # the .xlsx has nowhere else to keep it. Univer's t:4 means "this cell is text ON
    # PURPOSE" — a part code, a leading-zero id — and it was written out as a plain
    # string and read back as t:1, at which point the text-that-looks-numeric detector
    # nagged about a cell the page had deliberately made text. The `@` pattern IS the
    # persisted intent, in the format Excel itself uses for it.
    if out.get("t") == CV_STRING and isinstance(style, dict):
        n = style.get("n")
        pat = n.get("pattern") if isinstance(n, dict) else n
        if is_text_format(pat):
            out["t"] = CV_FORCE_STRING
    return out


def sheet_snapshot(ws, sheet_id: str, cached_ws=None) -> dict:
    """One worksheet → an IWorksheetData dict."""
    cell_data, used = {}, 0
    truncated = False
    for row in ws.iter_rows():
        if truncated:
            break
        for cell in row:
            if used >= MAX_CELLS:
                truncated = True
                break
            cached = None
            if cached_ws is not None:
                try:
                    cached = cached_ws.cell(row=cell.row, column=cell.column).value
                except Exception:                                # noqa: BLE001
                    cached = None
            try:
                c = cell_snapshot(cell, cached)
            except Exception:                                    # noqa: BLE001
                c = {}
            if not c:
                continue
            cell_data.setdefault(str(cell.row - 1), {})[str(cell.column - 1)] = c
            used += 1

    # ⚠️ hd (HIDDEN) IS READ FROM THE FILE NOW, NOT HARD-CODED TO 0 (finding F-27).
    # This block used to emit `hd: 0` on every entry — a value read from nothing and
    # written to nothing, so the snapshot ASSERTED "nothing is hidden" about a sheet
    # where rows and columns were hidden. A present-but-fake field is worse than an
    # absent one, and the consequence was real: a hidden column came BACK ON SCREEN
    # after an agent write, which is data Debi deliberately hid reappearing.
    row_data, column_data = {}, {}
    try:
        for idx, dim in (ws.row_dimensions or {}).items():
            i = _idx(idx)
            h = _num(getattr(dim, "height", None))
            hd = 1 if getattr(dim, "hidden", False) else 0
            if i is not None and i >= 1 and (h or hd):
                ent = {"hd": hd}
                if h:
                    ent["h"] = round(h / PT_PER_PX, 2)
                row_data[str(i - 1)] = ent
    except Exception:                                            # noqa: BLE001
        pass
    try:
        for letter, dim in (ws.column_dimensions or {}).items():
            w = _num(getattr(dim, "width", None))
            hd = 1 if getattr(dim, "hidden", False) else 0
            lo, hi = _idx(getattr(dim, "min", None)), _idx(getattr(dim, "max", None))
            if lo is None or lo < 1 or not (w or hd):
                continue
            # A column_dimensions entry can span a RANGE (min..max); hidden columns very
            # often arrive that way, and reading only `min` lost every other column in
            # the band. Bounded so a "hide A:XFD" cannot build a 16k-entry dict.
            hi = lo if hi is None or hi < lo else min(hi, lo + 512)
            for i in range(lo, hi + 1):
                ent = {"hd": hd}
                if w:
                    ent["w"] = round(w * PX_PER_CHAR, 2)
                column_data[str(i - 1)] = ent
    except Exception:                                            # noqa: BLE001
        pass

    # ⚠️ FREEZE PANES, GRIDLINES AND AUTOFILTER, ALSO READ RATHER THAN INVENTED (F-27).
    # The three hard-coded literals below the return used to say "not frozen, gridlines
    # on, no filter" about every sheet ever read.
    freeze = {"xSplit": 0, "ySplit": 0, "startRow": -1, "startColumn": -1}
    try:
        fp = getattr(ws, "freeze_panes", None)
        if isinstance(fp, str) and fp:
            m = re.match(r"^\$?([A-Za-z]{1,3})\$?([0-9]{1,7})$", fp.strip())
            if m:
                c = 0
                for ch in m.group(1).upper():
                    c = c * 26 + (ord(ch) - 64)
                xs, ys = max(c - 1, 0), max(int(m.group(2)) - 1, 0)
                freeze = {"xSplit": xs, "ySplit": ys,
                          "startRow": ys if ys else -1,
                          "startColumn": xs if xs else -1}
    except Exception:                                            # noqa: BLE001
        pass
    gridlines = 1
    try:
        sv = getattr(ws, "sheet_view", None)
        if sv is not None and getattr(sv, "showGridLines", True) is False:
            gridlines = 0
    except Exception:                                            # noqa: BLE001
        pass
    autofilter = ""
    try:
        af = getattr(ws, "auto_filter", None)
        ref = getattr(af, "ref", None) if af is not None else None
        if isinstance(ref, str) and ref:
            autofilter = ref
    except Exception:                                            # noqa: BLE001
        pass

    merges = []
    try:
        for m in (ws.merged_cells.ranges if ws.merged_cells else []):
            merges.append({"startRow": m.min_row - 1, "startColumn": m.min_col - 1,
                           "endRow": m.max_row - 1, "endColumn": m.max_col - 1})
    except Exception:                                            # noqa: BLE001
        merges = []

    rows = max(int(getattr(ws, "max_row", 0) or 0) + 20, DEFAULT_ROWS)
    cols = max(int(getattr(ws, "max_column", 0) or 0) + 5, DEFAULT_COLS)
    name = str(getattr(ws, "title", "") or "Sheet")[:SHEET_NAME_MAX]
    return {
        "id": sheet_id, "name": name, "tabColor": "",
        "hidden": 1 if str(getattr(ws, "sheet_state", "visible")) != "visible" else 0,
        "rowCount": min(rows, 5000), "columnCount": min(cols, 500),
        "zoomRatio": 1, "freeze": freeze,
        "scrollTop": 0, "scrollLeft": 0,
        "defaultColumnWidth": DEFAULT_COL_PX, "defaultRowHeight": DEFAULT_ROW_PX,
        "mergeData": merges, "cellData": cell_data,
        "rowData": row_data, "columnData": column_data,
        "showGridlines": gridlines, "autoFilter": autofilter,
        "rowHeader": {"width": 46}, "columnHeader": {"height": 20},
        "rightToLeft": 0, "truncated": bool(truncated),
    }


def empty_snapshot(name: str) -> dict:
    """A new, empty workbook in Univer's shape — no file is touched to build one."""
    sid = "sheet-01"
    sheet = {
        "id": sid, "name": "Sheet1", "tabColor": "", "hidden": 0,
        "rowCount": DEFAULT_ROWS, "columnCount": DEFAULT_COLS, "zoomRatio": 1,
        "freeze": {"xSplit": 0, "ySplit": 0, "startRow": -1, "startColumn": -1},
        "scrollTop": 0, "scrollLeft": 0,
        "defaultColumnWidth": DEFAULT_COL_PX, "defaultRowHeight": DEFAULT_ROW_PX,
        "mergeData": [], "cellData": {}, "rowData": {}, "columnData": {},
        "showGridlines": 1, "rowHeader": {"width": 46}, "columnHeader": {"height": 20},
        "rightToLeft": 0,
    }
    return {"id": "workbook-" + str(int(time.time() * 1000)),
            "name": os.path.splitext(str(name or "Untitled"))[0],
            "appVersion": "", "locale": "enUS", "styles": {},
            "sheetOrder": [sid], "sheets": {sid: sheet}, "resources": []}


def snapshot_from_path(path) -> dict:
    """Read an .xlsx into IWorkbookData. Raises OfficeError with a sentence in it."""
    if openpyxl is None:
        raise OfficeError("openpyxl is not installed in the bridge venv — "
                          f"the .xlsx round-trip is unavailable ({_OPENPYXL_ERR})")
    try:
        wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as e:                                       # noqa: BLE001
        raise OfficeError(f"could not read that workbook: {e}") from None
    # Second, best-effort pass for CACHED formula results. A file we wrote ourselves
    # has none (openpyxl does not calculate), which is fine — Univer recomputes.
    cached_wb = None
    try:
        cached_wb = openpyxl.load_workbook(path, data_only=True)
    except Exception:                                            # noqa: BLE001
        cached_wb = None

    sheets, order = {}, []
    for i, ws in enumerate(wb.worksheets):
        sid = f"sheet-{i + 1:02d}"
        cached_ws = None
        if cached_wb is not None:
            try:
                cached_ws = cached_wb[ws.title]
            except Exception:                                    # noqa: BLE001
                cached_ws = None
        try:
            sheets[sid] = sheet_snapshot(ws, sid, cached_ws)
        except Exception as e:                                   # noqa: BLE001
            # One unreadable sheet must not lose the other four.
            sheets[sid] = dict(empty_snapshot("x")["sheets"]["sheet-01"], id=sid,
                               name=str(getattr(ws, "title", "Sheet"))[:SHEET_NAME_MAX],
                               unreadable=str(e)[:200])
        order.append(sid)
    if not order:
        return empty_snapshot(os.path.basename(str(path)))
    return {"id": "workbook-" + str(int(time.time() * 1000)),
            "name": os.path.splitext(os.path.basename(str(path)))[0],
            "appVersion": "", "locale": "enUS", "styles": {},
            "sheetOrder": order, "sheets": sheets, "resources": []}


# ── IWorkbookData → xlsx ─────────────────────────────────────────────────────
class OfficeError(Exception):
    """A refusal with a sentence a person can act on."""


def _resolve_style(cell, styles):
    """A cell's `s` is either an inline style dict or an id into workbook.styles."""
    s = cell.get("s")
    if isinstance(s, dict):
        return s
    if isinstance(s, str) and isinstance(styles, dict):
        got = styles.get(s)
        return got if isinstance(got, dict) else None
    return None


def _sheet_names(snapshot) -> list:
    """(sheet_id, name) in sheetOrder order, falling back to the sheets dict's own
    order when sheetOrder is junk — a workbook must never open with zero sheets."""
    sheets = snapshot.get("sheets")
    if not isinstance(sheets, dict) or not sheets:
        return []
    order = snapshot.get("sheetOrder")
    ids = [i for i in order if isinstance(i, str) and i in sheets] if isinstance(order, list) else []
    for k in sheets:
        if k not in ids:
            ids.append(k)
    out = []
    seen = set()
    for i, sid in enumerate(ids):
        data = sheets.get(sid)
        name = ""
        if isinstance(data, dict):
            name = str(data.get("name") or "").strip()[:SHEET_NAME_MAX]
        if not name:
            name = f"Sheet{i + 1}"
        # ⚠️ THE SUFFIX IS BUILT INSIDE THE 31-CHARACTER BUDGET (finding F-31). The old
        # `base[:SHEET_NAME_MAX - 3] + "(n)"` produced a 32-character title from the
        # tenth duplicate on, past Excel's own limit — openpyxl warned and wrote it, and
        # some applications refuse the file. And it is BOUNDED: a name that cannot be
        # made free in 200 tries falls back to a positional one rather than spinning.
        base, n = name, 2
        while name.lower() in seen:            # Excel refuses duplicate sheet names
            if n > 200:
                name = f"Sheet{i + 1}-{len(seen)}"[:SHEET_NAME_MAX]
                break
            sfx = f"({n})"
            name = base[:max(1, SHEET_NAME_MAX - len(sfx))] + sfx
            n += 1
        seen.add(name.lower())
        out.append((sid, name))
    return out


def write_snapshot(snapshot, path) -> dict:
    """Write an IWorkbookData snapshot out as .xlsx, atomically.

    Returns a small report ({sheets, cells}) so the panel can say what it saved.
    Junk in any cell costs that cell; junk in the whole snapshot is a refusal.
    """
    if openpyxl is None:
        raise OfficeError("openpyxl is not installed in the bridge venv — "
                          f"the .xlsx round-trip is unavailable ({_OPENPYXL_ERR})")
    if not isinstance(snapshot, dict):
        raise OfficeError("refused: that is not a workbook snapshot")
    pairs = _sheet_names(snapshot)
    if not pairs:
        raise OfficeError("refused: that snapshot has no sheets")
    styles = snapshot.get("styles")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    written = 0
    for sid, name in pairs:
        data = snapshot["sheets"].get(sid)
        # ⚠️ THE ONE LINE THAT USED TO 500 (finding F-19). openpyxl raises a bare
        # ValueError for a title holding `: [ ] * ? / \`, save_doc catches only
        # OfficeError, so the ValueError escaped apply_changeset and the route answered
        # HTTP 500 with a traceback — the whole changeset lost and every retry crashing
        # the same way. validate_ops refuses such a name now; this is the FLOOR under
        # that, for a snapshot that arrived from anywhere else.
        try:
            ws = wb.create_sheet(title=name)
        except Exception as e:                                   # noqa: BLE001
            raise OfficeError(
                f"refused: {name!r} cannot be a sheet name — {e}") from None
        if not isinstance(data, dict):
            continue
        cell_data = data.get("cellData")
        if isinstance(cell_data, dict):
            for rkey, rowv in cell_data.items():
                r = _idx(rkey)
                if r is None or not isinstance(rowv, dict):
                    continue
                for ckey, cval in rowv.items():
                    c = _idx(ckey)
                    if c is None or not isinstance(cval, dict):
                        continue
                    try:
                        if _write_cell(ws, r + 1, c + 1, cval, styles):
                            written += 1
                    except Exception:                            # noqa: BLE001
                        continue
        _write_dimensions(ws, data)
        _write_merges(ws, data)
        _write_view(ws, data)
    _atomic_save(wb, path)
    return {"sheets": len(pairs), "cells": written}


def _write_cell(ws, row: int, col: int, cval: dict, styles) -> bool:
    cell = ws.cell(row=row, column=col)
    f = cval.get("f")
    wrote = False
    if isinstance(f, str) and f.strip().startswith("="):
        cell.value = f.strip()
        wrote = True
    else:
        v, t = cval.get("v"), cval.get("t")
        if isinstance(v, bool):
            cell.value = v
            wrote = True
        elif isinstance(v, (int, float)):
            n = _num(v)
            if n is not None:
                # FORCE_STRING is Univer's "this number is text" — honour it, else a
                # leading-zero part number silently becomes an integer.
                cell.value = str(v) if t == CV_FORCE_STRING else (
                    int(n) if float(n).is_integer() and abs(n) < 2 ** 53 else n)
                wrote = True
        elif isinstance(v, str):
            if v != "":
                cell.value = v
                wrote = True
        elif v is not None:
            cell.value = str(v)
            wrote = True
    style = _resolve_style(cval, styles)
    if style:
        apply_style(cell, style)
        wrote = True
    # ⚠️ FORCE_STRING'S INTENT IS PERSISTED AS THE `@` FORMAT (finding F-28). Writing the
    # string alone lost the "this is text on purpose" flag, and the round-trip then read
    # it back as an ordinary string — so the text-that-looks-numeric detector nagged
    # about a cell the page had deliberately made text. `@` is what Excel itself uses to
    # say this, and cell_snapshot re-derives t:4 from it.
    if cval.get("t") == CV_FORCE_STRING and isinstance(cell.value, str):
        try:
            if not is_text_format(cell.number_format):
                cell.number_format = "@"
                wrote = True
        except Exception:                                        # noqa: BLE001
            pass
    return wrote


def _write_dimensions(ws, data: dict) -> None:
    """Row heights, column widths — and, as of loffice-2026-08-28d, HIDDEN (F-27)."""
    try:
        rd = data.get("rowData")
        if isinstance(rd, dict):
            for key, val in rd.items():
                i = _idx(key)
                if i is None or not isinstance(val, dict):
                    continue
                h = _num(val.get("h"))
                if h and h > 0:
                    ws.row_dimensions[i + 1].height = round(h * PT_PER_PX, 2)
                if _num(val.get("hd")):
                    ws.row_dimensions[i + 1].hidden = True
    except Exception:                                            # noqa: BLE001
        pass
    try:
        cd = data.get("columnData")
        if isinstance(cd, dict):
            for key, val in cd.items():
                i = _idx(key)
                if i is None or not isinstance(val, dict):
                    continue
                w = _num(val.get("w"))
                letter = get_column_letter(i + 1)
                if w and w > 0:
                    ws.column_dimensions[letter].width = round(w / PX_PER_CHAR, 2)
                if _num(val.get("hd")):
                    ws.column_dimensions[letter].hidden = True
    except Exception:                                            # noqa: BLE001
        pass


def _write_view(ws, data: dict) -> None:
    """Freeze panes, gridline visibility, autofilter and sheet-hidden — the four things
    finding F-27 proved were LOST by every save while the snapshot claimed otherwise.

    Each one is independently guarded: an unwritable view setting must cost that setting
    and never the workbook.
    """
    try:
        fz = data.get("freeze")
        if isinstance(fz, dict):
            xs = int(_num(fz.get("xSplit")) or 0)
            ys = int(_num(fz.get("ySplit")) or 0)
            if xs > 0 or ys > 0:
                ws.freeze_panes = get_column_letter(max(xs, 0) + 1) + str(max(ys, 0) + 1)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        g = data.get("showGridlines")
        if g is not None and not _num(g):
            ws.sheet_view.showGridLines = False
    except Exception:                                            # noqa: BLE001
        pass
    try:
        af = data.get("autoFilter")
        if isinstance(af, str) and af.strip():
            ws.auto_filter.ref = af.strip()
    except Exception:                                            # noqa: BLE001
        pass
    try:
        if _num(data.get("hidden")):
            ws.sheet_state = "hidden"
    except Exception:                                            # noqa: BLE001
        pass


def _write_merges(ws, data: dict) -> None:
    merges = data.get("mergeData")
    if not isinstance(merges, list):
        return
    for m in merges:
        if not isinstance(m, dict):
            continue
        r1, c1 = _idx(m.get("startRow")), _idx(m.get("startColumn"))
        r2, c2 = _idx(m.get("endRow")), _idx(m.get("endColumn"))
        if None in (r1, c1, r2, c2) or r2 < r1 or c2 < c1:
            continue
        try:
            ws.merge_cells(start_row=r1 + 1, start_column=c1 + 1,
                           end_row=r2 + 1, end_column=c2 + 1)
        except Exception:                                        # noqa: BLE001
            continue


def _atomic_save(wb, path) -> None:
    """Save through a temp file in the SAME directory + os.replace, so a crash
    mid-write can never leave a half-written workbook where the original was."""
    d = os.path.dirname(os.path.realpath(str(path))) or "."
    fd, tmp = tempfile.mkstemp(prefix=".office-", suffix=DOC_EXT, dir=d)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, str(path))
    except Exception as e:                                       # noqa: BLE001
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise OfficeError(f"could not write that workbook: {e}") from None


# ── the operations the routes call ───────────────────────────────────────────
def create_doc(root, name):
    """(name, None) or (None, reason). Never clobbers an existing workbook.

    TWO CALLERS, TWO MEANINGS, and the difference is the whole point of the empty case:

      * a NAME the user typed is honoured literally — if a workbook is already called
        that, this refuses and says so, because silently making `budget (2).xlsx` when
        somebody asked for `budget.xlsx` hides the thing they need to know.
      * an EMPTY name means "just give me a sheet". That is what the landing does on a
        fresh install (and what the New box does when you press Enter without typing),
        so it must never fail for a reason the user did not choose — it takes
        DEFAULT_DOC_STEM through `free_name`, the same ' (n)' never-clobber discipline
        import uses. Before this, an empty name returned "no file name given" and the
        panel simply swallowed it: the button did nothing, three sessions running.
    """
    blank = name is None or (isinstance(name, str) and not name.strip())
    if blank:
        safe, reason = free_name(root, DEFAULT_DOC_STEM)
    else:
        safe, reason = valid_name(name)          # junk types still land here, and refuse
    if not safe:
        return None, reason
    target, reason = doc_target(root, safe, must_exist=False)
    if not target:
        return None, reason
    if os.path.exists(target):
        return None, "a workbook with that name already exists"
    try:
        write_snapshot(empty_snapshot(safe), target)
    except OfficeError as e:
        return None, str(e)
    return safe, None


def free_name(root, name):
    """A name nothing is stored under yet: `book.xlsx` → `book (2).xlsx` → …

    Import NEVER clobbers. A workbook that arrives from outside is somebody's real
    file and the one already here is somebody's real file too — the artifact-save and
    voice-clip discipline (' (n)') is the only safe policy, and it is why upload does
    not simply reuse create_doc's refusal.
    """
    safe, reason = valid_name(name)
    if not safe:
        return None, reason
    stem = os.path.splitext(safe)[0]
    for n in range(1, 1000):
        cand = safe if n == 1 else f"{stem} ({n}){DOC_EXT}"
        if len(cand) > NAME_MAX:
            return None, f"refused: that name is longer than {NAME_MAX} characters"
        target, reason = doc_target(root, cand, must_exist=False)
        if not target:
            return None, reason
        if not os.path.exists(target):
            return cand, None
    return None, "refused: too many workbooks with that name already"


def import_doc(root, name, data):
    """(report, None) or (None, reason) — an .xlsx from outside, into data/office.

    The bytes are VERIFIED as a workbook before they are kept: a renamed .txt would
    otherwise land in the list and only fail later, when the user clicks it. Written
    through the same temp-file + os.replace path as every other write here.
    """
    if openpyxl is None:
        return None, ("openpyxl is not installed in the bridge venv — "
                      f"the .xlsx round-trip is unavailable ({_OPENPYXL_ERR})")
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None, "no file received"
    if len(data) > UPLOAD_MAX_BYTES:
        return None, (f"that file is {len(data) // (1024 * 1024)} MB — the import cap "
                      f"is {UPLOAD_MAX_BYTES // (1024 * 1024)} MB")
    safe, reason = valid_name(name)
    if not safe:
        return None, reason
    try:
        openpyxl.load_workbook(_io.BytesIO(bytes(data)), data_only=False).close()
    except Exception as e:                                       # noqa: BLE001
        return None, f"that file is not a readable .xlsx workbook: {e}"
    final, reason = free_name(root, safe)
    if not final:
        return None, reason
    target, reason = doc_target(root, final, must_exist=False)
    if not target:
        return None, reason
    d = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(prefix=".office-", suffix=DOC_EXT, dir=d)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(bytes(data))
        os.replace(tmp, target)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None, f"could not write that workbook: {e}"
    return {"name": final, "renamed": final != safe, "bytes": len(data)}, None


def save_doc(root, name, snapshot):
    """(report, None) or (None, reason). Takes a .bak first when the workbook
    already exists and today's backup has not been made yet."""
    target, reason = doc_target(root, name, must_exist=False)
    if not target:
        return None, reason
    backup = ""
    if os.path.isfile(target):
        bak = backup_for(target)
        if not os.path.exists(bak):
            try:
                shutil.copy2(target, bak)
                backup = os.path.basename(bak)
            except OSError as e:
                # A backup we cannot write is a reason to STOP, not to overwrite
                # the only copy of the user's file.
                return None, f"could not write a backup beside that file: {e}"
    try:
        report = write_snapshot(snapshot, target)
    except OfficeError as e:
        return None, str(e)
    report["name"] = os.path.basename(target)
    report["backup"] = backup
    return report, None


def open_doc(root, name):
    """(snapshot, None) or (None, reason)."""
    target, reason = doc_target(root, name)
    if not target:
        return None, reason
    try:
        snap = snapshot_from_path(target)
    except OfficeError as e:
        return None, str(e)
    snap["name"] = os.path.splitext(os.path.basename(target))[0]
    return snap, None


def diag_line(stage, detail="", boot="", ms=None, now=None) -> str:
    """PURE. One line of the boot trace, in the shape a person greps.

        2026-08-21 05:31:44 boot=7f3a1c +1240ms stage=mount-ok detail=canvases=3 …

    Everything here arrives from a webview that is, by hypothesis, MALFUNCTIONING —
    so every field is coerced and clamped. A diagnostic that can itself raise is
    worse than no diagnostic: it would take the bridge down while reporting that
    the page is down. Newlines are flattened because one beacon is one line, and a
    beacon that could inject a newline could forge a second entry.
    """
    def clean(v, cap):
        s = "" if v is None else str(v)
        s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
        return s[:cap] or ""
    st = clean(stage, DIAG_STAGE_MAX) or "?"
    dt = clean(detail, DIAG_DETAIL_MAX)
    bt = clean(boot, 16) or "?"
    try:
        n = float(ms)
        if n != n or n in (float("inf"), float("-inf")):         # NaN / inf
            raise ValueError
        el = f"+{int(n)}ms"
    except (TypeError, ValueError):
        el = "+?ms"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S",
                          time.localtime(now if isinstance(now, (int, float)) else time.time()))
    return f"{stamp} boot={bt} {el} stage={st}" + (f" detail={dt}" if dt else "")


def write_diag(root, stage, detail="", boot="", ms=None) -> str:
    """Append one `diag_line` to data/logs/loffice-boot.log and return it.

    Bounded on purpose: the loudest signal this file can carry is a CRASH LOOP (the
    same `script-start` stage arriving again and again under different boot ids, which
    is what a jetsammed web content process being reloaded looks like from outside),
    and a crash loop writing an unbounded file is a disk problem on top of a tab
    problem. Trim to the last DIAG_MAX_LINES.

    Never raises: the caller is an error path.
    """
    line = diag_line(stage, detail, boot, ms)
    try:
        d = os.path.join(str(root), "data", "logs")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, DIAG_LOG_NAME + ".log")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        # cheap trim: only when the file has grown past the cap, and only by rewriting
        # the tail — an append-mostly file that is read in full once in a while.
        if os.path.getsize(p) > DIAG_MAX_LINES * 200:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                keep = fh.read().splitlines()[-DIAG_MAX_LINES:]
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write("\n".join(keep) + "\n")
            os.replace(tmp, p)
    except Exception:                                            # noqa: BLE001
        pass
    return line


def delete_doc(root, name, backups: bool = False):
    """(True, None) or (False, reason).

    THE WORKBOOK ONLY, BY DEFAULT — a `.bak` beside it is the thing that exists to survive
    mistakes, so it stays.

    ⚠️ `backups=True` IS THE OTHER HALF OF AN HONESTY FIX (live finding B5). "This cannot be
    undone" was false in BOTH directions: a delete left the daily `<stem>.YYYYMMDD.bak.xlsx`
    on disk, and `is_backup_name()` filters those out of `list_docs`, so the copy was
    neither listed nor deletable from the UI. The delete COULD be undone from a file the
    user was never told about — and somebody deleting a workbook for privacy kept its
    contents. The panel now says which of the two she is getting and offers both.

    The pre-agent copy and the checkpoint stack go with the workbook whenever the backups
    do: they are copies of the same content, under the same argument.
    """
    target, reason = doc_target(root, name)
    if not target:
        return False, reason
    try:
        os.remove(target)
    except OSError as e:
        return False, f"could not delete: {e}"
    if not backups:
        return True, None
    d, base = os.path.split(target)
    stem = os.path.splitext(base)[0]
    try:
        for n in os.listdir(d):
            if n.startswith(stem + ".") and is_backup_name(n):
                try:
                    os.remove(os.path.join(d, n))
                except OSError:
                    pass
    except OSError:
        pass
    try:
        shutil.rmtree(os.path.join(checkpoint_root(root), stem), ignore_errors=True)
    except OSError:
        pass
    return True, None


def rename_doc(root, name, to):
    """(new_name, None) or (None, reason).

    BOTH names go through `doc_target`, so the same basename + realpath containment
    that guards open/save/delete guards this: a rename can no more reach outside
    data/office than a delete can. It NEVER clobbers — renaming onto an existing
    workbook is refused rather than resolved to ' (n)', because a rename names a file
    the user typed and quietly picking a different one hides the collision.

    ⚠️ The `.bak` copies keep their OLD stem. They are dated safety copies of the file
    as it was, and moving them would make the date the only thing tying them to
    anything; `_any_backup` already looks them up per path, so the old ones simply
    belong to the old name.
    """
    src, reason = doc_target(root, name)
    if not src:
        return None, reason
    safe, reason = valid_name(to)
    if not safe:
        return None, reason
    dst, reason = doc_target(root, safe, must_exist=False)
    if not dst:
        return None, reason
    if os.path.realpath(dst) == os.path.realpath(src):
        return safe, None                       # renaming a file to its own name: a no-op
    if os.path.exists(dst):
        return None, "a workbook with that name already exists"
    try:
        os.rename(src, dst)
    except OSError as e:
        return None, f"could not rename: {e}"
    # ⚠️ THE UNDO STACK FOLLOWS THE FILE (finding F-21). `.checkpoints/<stem>/` is keyed
    # by the file stem, and a rename used to orphan it: `undo_changeset` then answered
    # "no such workbook" — blaming a missing file for what was really an unreachable
    # stack — while the checkpoints, and the pre-agent copy that now lives beside them,
    # sat on disk under the old stem for ever. A rename is not a reason to lose an undo.
    try:
        old_dir = os.path.join(checkpoint_root(root),
                               os.path.splitext(os.path.basename(src))[0])
        new_dir = os.path.join(checkpoint_root(root), os.path.splitext(safe)[0])
        if os.path.isdir(old_dir) and not os.path.exists(new_dir):
            os.makedirs(os.path.dirname(new_dir), exist_ok=True)
            os.rename(old_dir, new_dir)
    except OSError:
        pass                                 # the rename SUCCEEDED; this is a courtesy
    return safe, None
