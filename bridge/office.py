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
import os
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
# The one sentence the panel prints under the file list. Single-sourced here so the
# page and any future surface cannot promise two different things.
FIDELITY_NOTE = ("Values, formulas and basic formatting round-trip. Complex styling "
                 "may be simplified — keep your original file; Office saves copies.")
NAME_MAX = 80
SHEET_NAME_MAX = 31            # Excel's own limit; openpyxl truncates past it
# A snapshot travels as JSON through a WKWebView. 200k cells is far past any workbook
# a person edits by hand and still well inside what JSON.stringify survives; past it
# we stop reading and SAY the sheet was truncated rather than hanging the tab.
MAX_CELLS = 200_000
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

PX_PER_CHAR = 7.0
PT_PER_PX = 0.75               # row height: openpyxl points ↔ Univer pixels

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
    """Every workbook, newest first. Backups are on disk but not in this list."""
    d = office_dir(root)
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        if not n.lower().endswith(DOC_EXT) or is_backup_name(n) or n.startswith("~$"):
            continue
        p = os.path.join(d, n)
        if not os.path.isfile(p):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"name": n, "size_bytes": st.st_size, "modified": st.st_mtime,
                    "has_backup": bool(_any_backup(p))})
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

    row_data, column_data = {}, {}
    try:
        for idx, dim in (ws.row_dimensions or {}).items():
            i = _idx(idx)
            h = _num(getattr(dim, "height", None))
            if i is not None and i >= 1 and h:
                row_data[str(i - 1)] = {"h": round(h / PT_PER_PX, 2), "hd": 0}
    except Exception:                                            # noqa: BLE001
        pass
    try:
        for letter, dim in (ws.column_dimensions or {}).items():
            w = _num(getattr(dim, "width", None))
            col = getattr(dim, "min", None)
            i = _idx(col)
            if i is not None and i >= 1 and w:
                column_data[str(i - 1)] = {"w": round(w * PX_PER_CHAR, 2), "hd": 0}
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
        "id": sheet_id, "name": name, "tabColor": "", "hidden": 0,
        "rowCount": min(rows, 5000), "columnCount": min(cols, 500),
        "zoomRatio": 1, "freeze": {"xSplit": 0, "ySplit": 0,
                                   "startRow": -1, "startColumn": -1},
        "scrollTop": 0, "scrollLeft": 0,
        "defaultColumnWidth": DEFAULT_COL_PX, "defaultRowHeight": DEFAULT_ROW_PX,
        "mergeData": merges, "cellData": cell_data,
        "rowData": row_data, "columnData": column_data,
        "showGridlines": 1, "rowHeader": {"width": 46}, "columnHeader": {"height": 20},
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
        base, n = name, 2
        while name.lower() in seen:            # Excel refuses duplicate sheet names
            name = f"{base[:SHEET_NAME_MAX - 3]}({n})"
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
        ws = wb.create_sheet(title=name)
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
    return wrote


def _write_dimensions(ws, data: dict) -> None:
    try:
        rd = data.get("rowData")
        if isinstance(rd, dict):
            for key, val in rd.items():
                i = _idx(key)
                h = _num((val or {}).get("h")) if isinstance(val, dict) else None
                if i is not None and h and h > 0:
                    ws.row_dimensions[i + 1].height = round(h * PT_PER_PX, 2)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        cd = data.get("columnData")
        if isinstance(cd, dict):
            for key, val in cd.items():
                i = _idx(key)
                w = _num((val or {}).get("w")) if isinstance(val, dict) else None
                if i is not None and w and w > 0:
                    ws.column_dimensions[get_column_letter(i + 1)].width = \
                        round(w / PX_PER_CHAR, 2)
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
    """(name, None) or (None, reason). Never clobbers an existing workbook."""
    safe, reason = valid_name(name)
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


def delete_doc(root, name):
    """(True, None) or (False, reason). Deletes the workbook only — a .bak beside
    it is the thing that exists to survive mistakes, so it stays."""
    target, reason = doc_target(root, name)
    if not target:
        return False, reason
    try:
        os.remove(target)
    except OSError as e:
        return False, f"could not delete: {e}"
    return True, None
