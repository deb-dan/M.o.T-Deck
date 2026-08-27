"""OFFICE AGENT LANE (slice S1) — the tables that make the two lanes ONE lane.

Built to docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md §6. What each group guards:

1. THE MIRRORED CONSTANTS. bridge/office_ops.py restates every cap that lives in
   bridge/panel/office.html, because the two are a served HTML document and a python
   module with no build step between them and cannot share a literal. So this group
   READS THE PAGE and asserts each one equal. Without it, "the agent lane and the Quick
   lane have the same caps" is a claim about the day the code was written.

2. THE SEMANTICS TABLE, EXECUTED AGAINST REAL .xlsx FILES. Not "the function returns
   what the function returns" — a workbook is written with openpyxl, put through the
   tool, and read back with openpyxl. The four that matter most, all named in the spec:
   the SORT MERGE-REFUSAL, an INSERT that shifts merges while leaving formula text
   alone, the CAP ASYMMETRY (refuse vs clamp), and the SHARED-STYLE-ID TRAP.
   The expected values are the ones bridge/tests/test_office_ai.js pins on the page
   side, restated here — two tables, one answer, and a drift breaks one of them.

3. THE MCP SURFACE, through the MOUNTED app. Tool list, schemas, the approval split
   (which is `annotations.readOnlyHint`, the thing that actually arms Hermes's card),
   containment refusals, and the transport rules a real MCP client depends on — a
   notification answered 202-with-no-body, a request answered application/json, GET
   answered 405.

4. THE THREE WRITE-SAFETY RULES S1 OWNS. The `.pre-agent.xlsx` copy exists AND holds
   the PRE-write content; the open-dirty refusal fires through the real heartbeat
   endpoint; no heartbeat and a stale heartbeat both mean ALLOWED, because a page that
   crashed must never leave a workbook nobody can write.

5. CONFIG-GEN. The `mcp_servers.loffice` entry lands, is byte-identical on a second run
   (idempotent), and survives a config that already holds other servers and other keys
   — the pin-bump reconciliation the a2a mirror's tests are shaped like. Tested against
   the REAL heredoc lifted out of scripts/start_component.sh, so a change to the
   script's copy of the entry cannot pass while the test's copy stays green.

Run: python3 bridge/tests/test_office_mcp.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# Sandbox hygiene, and it is load-bearing here: importing bridge.app builds an httpx
# client at import time, and one of the groups below writes a Hermes config — so HERMES
# HOME is pointed at a temp dir BEFORE the import, exactly as test_voice_mcp.py does.
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)
_HHOME = tempfile.mkdtemp(prefix="harness-office-mcp-hermes-")
os.environ["HERMES_HOME"] = _HHOME

from bridge import office, office_mcp, office_ops              # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


def eq(name, got, want):
    ok = got == want
    print(("PASS" if ok else "FAIL"), name)
    if not ok:
        print(f"     got  {got!r}\n     want {want!r}")
        FAILS.append(name)


try:
    import openpyxl
    from openpyxl.styles import Font
    HAVE_XL = True
except Exception as _e:                                          # noqa: BLE001
    HAVE_XL = False
    print("!! openpyxl is NOT importable here — every executed-workbook table below is "
          f"SKIPPED and only the pure/wiring groups run ({_e})")

PAGE = (ROOT / "bridge" / "panel" / "office.html").read_text(encoding="utf-8")
AIJS = (ROOT / "bridge" / "tests" / "test_office_ai.js").read_text(encoding="utf-8")


# ══ 1. THE MIRRORED CONSTANTS ════════════════════════════════════════════════
def page_const(name):
    """The literal on the page, as text. Multi-line values included (RC_FORMULA_NOTE is
    a concatenation across three lines), which is why this is not a `.*?` match."""
    m = re.search(r"^const " + name + r" = ([\s\S]*?);\s*(?://.*)?$", PAGE, re.M)
    assert m, f"const {name} not found in office.html"
    return m.group(1).strip()


def page_number(name):
    raw = page_const(name)
    raw = re.sub(r"//.*", "", raw).strip()
    return eval(raw, {"__builtins__": {}}, {})       # noqa: S307 — a numeric literal


print("\n── 1. the constants the two lanes must agree on ──")
for name, mine in [("ACT_V", office_ops.ACT_V),
                   ("ACT_MAX_OPS", office_ops.ACT_MAX_OPS),
                   ("ACT_MAX_CELLS", office_ops.ACT_MAX_CELLS),
                   ("ACT_MAX_ROW", office_ops.ACT_MAX_ROW),
                   ("ACT_MAX_COL", office_ops.ACT_MAX_COL),
                   ("ACT_STR_MAX", office_ops.ACT_STR_MAX),
                   ("ACT_SHEET_MAX", office_ops.ACT_SHEET_MAX),
                   ("ACT_NAME_MAX", office_ops.ACT_NAME_MAX),
                   ("RC_MAX", office_ops.RC_MAX),
                   ("TIER1_MAX_COLS", office_ops.TIER1_MAX_COLS),
                   ("SORT_BLANK", office_ops.SORT_BLANK)]:
    eq(f"office_ops.{name} == the page's {name}", mine, page_number(name))

# RC_FORMULA_NOTE is the sentence the model reads in a tool result and the sentence
# Debi reads in the panel. Two different wordings of the same limit would be two
# different limits as far as anyone reading them is concerned.
_note_js = page_const("RC_FORMULA_NOTE")
_note = "".join(re.findall(r"'([^']*)'", _note_js))
eq("RC_FORMULA_NOTE is the page's sentence, character for character",
   office_ops.RC_FORMULA_NOTE, _note)

eq("ACT_HT mirrors the page's alignment words", office_ops.ACT_HT,
   {"left": 1, "center": 2, "centre": 2, "right": 3})
eq("ACT_VT likewise", office_ops.ACT_VT,
   {"top": 1, "middle": 2, "center": 2, "centre": 2, "bottom": 3})
check("the style keys office_ops accepts are exactly the keys office.py writes",
      sorted(office_ops.act_style_set(
          {"bl": 1, "it": 1, "ul": 1, "st": 1, "ff": "Arial", "fs": 12,
           "cl": "#112233", "bg": "#445566", "ht": "center", "vt": "top",
           "tb": "wrap", "n": "0.00"}).keys())
      == sorted(["bl", "it", "ul", "st", "ff", "fs", "cl", "bg", "ht", "vt", "tb", "n"]))
check("…and an unknown key is dropped rather than promised",
      office_ops.act_style_set({"border": "thin"}) is None
      and office_ops.act_style_set({"bl": 1, "border": "thin"}) == {"bl": 1})


# ══ 2. THE PURE TABLES, mirrored from bridge/tests/test_office_ai.js ═════════
print("\n── 2a. references, ranges, grids, columns ──")
for s, want in [("A1", (0, 0)), ("B3", (2, 1)), ("AA1", (0, 26)), ("AB10", (9, 27)),
                ("GR5000", (4999, 199)), ("a1", (0, 0)), ("$B$2", (1, 1)),
                ("  C7  ", (6, 2)), ("ZZ1", (0, 701))]:
    eq(f"act_ref({s!r})", office_ops.act_ref(s), want)
eq("act_ref refuses everything that is not a cell rather than inventing one",
   [office_ops.act_ref(x) for x in ["A0", "0A", "1A", "A", "1", "", "   ", "A1:B2",
                                    "AAAA1", "the total row", None, 42, {}, []]],
   [None] * 14)
eq("act_range takes a single cell as a 1x1 rectangle", office_ops.act_range("B3"),
   (2, 1, 2, 1))
eq("…a range as itself", office_ops.act_range("A1:C3"), (0, 0, 2, 2))
eq("…and a BACKWARDS range as the same rectangle, because it is the same rectangle",
   office_ops.act_range("C3:A1"), office_ops.act_range("A1:C3"))
eq("act_range refuses junk",
   [office_ops.act_range(x) for x in ["", "A1:B2:C3", "A1:", ":B2", "nope", None]],
   [None] * 6)
eq("col_name is act_col's inverse across the whole tier-1 width",
   [office_ops.act_col(office_ops.col_name(c)) for c in
    [0, 1, 25, 26, 27, 51, 52, 199, 701]],
   [0, 1, 25, 26, 27, 51, 52, 199, 701])
eq("a FLAT list is one row — the shape a model reaches for when it means 'a row'",
   office_ops.act_grid(["a", "b"]), [["a", "b"]])
eq("a bare scalar is one cell", office_ops.act_grid(42), [[42]])
eq("a HALF-nested list is REFUSED, not repaired: guessing could put a value in the "
   "wrong cell, which is worse than saying no", office_ops.act_grid([["a"], "b"]), None)
eq("…as are empty lists, empty rows, and a cell holding an object",
   [office_ops.act_grid([]), office_ops.act_grid([[]]),
    office_ops.act_grid([[{"a": 1}]])], [None, None, None])
check("a cell longer than the text cap is refused rather than truncated into the file",
      office_ops.act_grid([["x" * office_ops.ACT_STR_MAX]]) is not None
      and office_ops.act_grid([["x" * (office_ops.ACT_STR_MAX + 1)]]) is None)
eq("act_col takes a LETTER with or without a row and with or without the $",
   [office_ops.act_col(x) for x in ["B", "b", "$B$4", "AA", "GR"]],
   [1, 1, 1, 26, 199])
eq("…and a bare NUMBER is refused: it is ambiguous between 'column 2' and 'column B' "
   "the moment anybody 0-indexes it, and a sort aimed one column over is a silently "
   "wrong document",
   [office_ops.act_col(x) for x in ["2", 2, "", None, "the sales column"]],
   [-1, -1, -1, -1, -1])
eq("an insert row target is a 1-based row NUMBER or a cell reference; a column is a "
   "letter",
   [office_ops.act_rc_target("row", 3), office_ops.act_rc_target("row", "3"),
    office_ops.act_rc_target("row", "A3"), office_ops.act_rc_target("row", 0),
    office_ops.act_rc_target("row", "x"), office_ops.act_rc_target("col", "D"),
    office_ops.act_rc_target("col", 4)],
   [2, 2, 2, -1, -1, 3, -1])

print("\n── 2b. value coercion: the SAME converter typing uses ──")
eq("a JSON number is a number cell", office_ops.act_cell(900, None),
   {"v": 900, "t": office_ops.CV_NUMBER})
eq("a formula string is a formula", office_ops.act_cell("=SUM(B2:B3)", None),
   {"f": "=SUM(B2:B3)"})
eq("a numeric STRING is a number, exactly as if it had been typed",
   office_ops.act_cell("120", None), {"v": 120, "t": office_ops.CV_NUMBER})
eq("…and a leading-zero string stays text, because it is almost always an id",
   office_ops.act_cell("007", None), {"v": "007", "t": office_ops.CV_STRING})
eq("…as do 1e5 and 0x10, which Number() would have swallowed",
   [office_ops.act_cell("1e5", None), office_ops.act_cell("0x10", None)],
   [{"v": "1e5", "t": office_ops.CV_STRING},
    {"v": "0x10", "t": office_ops.CV_STRING}])
eq("a boolean is a boolean cell", office_ops.act_cell(True, None),
   {"v": True, "t": office_ops.CV_BOOLEAN})
eq("null and '' empty the cell",
   [office_ops.act_cell(None, None), office_ops.act_cell("", None)], [None, None])
eq("the cell's STYLE survives a value the model wrote — writing a number into a bold "
   "red cell must not strip the bold red",
   [office_ops.act_cell(5, {"v": 1, "s": {"bl": 1}}),
    office_ops.act_cell("x", {"v": 1, "s": {"bl": 1}}),
    office_ops.act_cell(None, {"v": 1, "s": {"bl": 1}})],
   [{"v": 5, "t": office_ops.CV_NUMBER, "s": {"bl": 1}},
    {"s": {"bl": 1}, "v": "x", "t": office_ops.CV_STRING},
    {"s": {"bl": 1}}])
eq("a non-finite number cannot reach a cell",
   office_ops.act_cell(float("inf"), None), None)

print("\n── 2c. the caps, and THE ASYMMETRY the spec asked to be pinned ──")
OKOP = {"op": "set", "at": "A1", "values": [["Month", "Planned"]]}
check("a well-formed change validates", office_ops.validate_ops([OKOP])[0] is not None)
check(f"more than {office_ops.ACT_MAX_OPS} operations is refused before anything is "
      "read",
      office_ops.validate_ops([OKOP] * (office_ops.ACT_MAX_OPS + 1))[0] is None
      and office_ops.validate_ops([OKOP] * office_ops.ACT_MAX_OPS)[0] is not None)
check(f"a change over the {office_ops.ACT_MAX_CELLS}-cell budget is refused WHOLE, not "
      "truncated — half a table written is worse than none",
      office_ops.validate_ops(
          [{"op": "set", "at": "A1", "values": [["x"] * 40 for _ in range(60)]}])[0]
      is None)
check("…and the budget is shared across ALL the ops in one change, not per op",
      office_ops.validate_ops([
          {"op": "set", "at": "A1", "values": [["x"] * 30]},
          {"op": "style", "at": "A1:AZ100", "set": {"bl": 1}}])[0] is None)
eq("…the refusal names which KIND of op crossed the line, because the fix differs",
   [office_ops.validate_ops(
       [{"op": "set", "at": "A1", "values": [["x"] * 40 for _ in range(60)]}])[2][:12],
    office_ops.validate_ops(
        [{"op": "style", "at": "A1:BZ100", "set": {"bl": 1}}])[2][:16]],
   ["that is more", "that formats mor"])
check("exactly the cap is allowed — the check is on EXCEEDING it",
      office_ops.validate_ops(
          [{"op": "style", "at": "A1:T100", "set": {"bl": 1}}])[0] is not None)
check("a set that would land outside the grid this tier draws is refused",
      office_ops.validate_ops([{"op": "set", "at": "GR5000", "values": [["x"]]}])[0]
      is not None
      and office_ops.validate_ops([{"op": "set", "at": "GS1", "values": [["x"]]}])[0]
      is None
      and office_ops.validate_ops(
          [{"op": "set", "at": "A5000", "values": [["a"], ["b"]]}])[0] is None)
# ⚠️ THE DELIBERATE ASYMMETRY, pinned so it reads as a decision rather than as a bug
check("RESIZE clamps where SET refuses: a clamped resize loses nothing, a clamped set "
      "would drop data",
      office_ops.validate_ops([{"op": "resize", "rows": 999999,
                                "cols": 999999}])[0][0]
      == {"op": "resize", "rows": office_ops.ACT_MAX_ROW + 1,
          "cols": office_ops.ACT_MAX_COL + 1})
check("an INSERT over the cap is CLAMPED and a DELETE over it is REFUSED: a clamped "
      "insert loses nothing (it is empty space), a clamped delete would destroy "
      "exactly as much data as it felt like",
      office_ops.validate_ops(
          [{"op": "insert", "what": "row", "at": 1, "n": 99999}])[0][0]["n"]
      == office_ops.RC_MAX
      and office_ops.validate_ops(
          [{"op": "delete_rc", "what": "row", "at": 1, "n": 99999}])[0] is None)
check("a missing or junk 'n' is one, which is what a model means when it omits it",
      office_ops.validate_ops([{"op": "insert", "what": "row", "at": 1}])[0][0]["n"] == 1
      and office_ops.validate_ops(
          [{"op": "insert", "what": "row", "at": 1, "n": "a few"}])[0][0]["n"] == 1)
eq("a range is an ANCHOR, not a clip: five rows offered at A1:B2 write five rows",
   office_ops.validate_ops([{"op": "set", "at": "A1:B2",
                             "values": [["a"], ["b"], ["c"], ["d"], ["e"]]}])[1]["cells"],
   5)
for label, ops in [
        ("ops that is not a list", "set A1"),
        ("an empty ops list", []),
        ("an op that is not an object", ["set A1 to x"]),
        ("an unknown op", [{"op": "delete_file", "at": "A1"}]),
        ("an op with no op name", [{"at": "A1", "values": [["x"]]}]),
        ("a set with no values", [{"op": "set", "at": "A1"}]),
        ("a set whose 'at' is prose",
         [{"op": "set", "at": "the total row", "values": [["x"]]}]),
        ("a style with no readable key",
         [{"op": "style", "at": "A1", "set": {"border": 1}}]),
        ("a sheet op with neither add nor rename", [{"op": "sheet"}]),
        ("a resize with neither rows nor cols", [{"op": "resize"}]),
        ("a sheet name past Excel's limit", [{"op": "sheet", "add": "x" * 40}]),
        ("a sort with no column", [{"op": "sort"}]),
        ("a sort whose column is prose", [{"op": "sort", "col": "the totals"}]),
        ("a sort past the last column this grid draws", [{"op": "sort", "col": "GS"}]),
        ("an insert with no axis", [{"op": "insert", "at": 1}]),
        ("an insert with a junk axis", [{"op": "insert", "what": "diagonal", "at": 1}]),
        ("an insert with no target", [{"op": "insert", "what": "row"}]),
        ("an insert past the row ceiling",
         [{"op": "insert", "what": "row", "at": 99999}])]:
    ops_out, _c, why = office_ops.validate_ops(ops)
    check("REFUSED, with a reason a person can read — " + label,
          ops_out is None and isinstance(why, str) and len(why) > 8)
check("every refusal that is about one operation NAMES which one",
      office_ops.validate_ops([OKOP, {"op": "nope"}])[2].startswith("operation 2: "))
eq("'rows'/'columns'/'column' are all understood, and 'axis' as well as 'what'",
   [office_ops.validate_ops([{"op": "insert", "what": "rows", "at": 1}])[0][0]["axis"],
    office_ops.validate_ops([{"op": "insert", "what": "columns", "at": "A"}])[0][0]["axis"],
    office_ops.validate_ops([{"op": "insert", "axis": "column", "at": "A"}])[0][0]["axis"]],
   ["row", "col", "col"])
check("the sort direction is accepted the several ways a model writes it",
      office_ops.validate_ops([{"op": "sort", "col": "A", "order": "desc"}])[0][0]["desc"]
      and office_ops.validate_ops(
          [{"op": "sort", "col": "A", "dir": "descending"}])[0][0]["desc"]
      and not office_ops.validate_ops([{"op": "sort", "col": "A"}])[0][0]["desc"])
check("…and 'at' is taken as the column too, because half the models will write that",
      office_ops.validate_ops([{"op": "sort", "at": "C1"}])[0][0]["col"] == 2)

print("\n── 2d. the sort order, blanks-last IN BOTH DIRECTIONS, and stability ──")


def _sheet(rows):
    cd = {}
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell is not None:
                cd.setdefault(str(r), {})[str(c)] = cell
    return {"id": "s1", "name": "Sheet1", "cellData": cd, "rowCount": 200,
            "columnCount": 26}


N = office_ops.CV_NUMBER
S = office_ops.CV_STRING
B = office_ops.CV_BOOLEAN
_mixed = _sheet([[{"v": 30, "t": N}], [None], [{"v": "apple", "t": S}],
                 [{"v": True, "t": B}], [{"v": 10, "t": N}], [{"v": "", "t": S}],
                 [{"v": "Banana", "t": S}], [{"v": False, "t": B}]])
eq("ascending: numbers, then text (case-insensitively), then booleans, then blanks",
   office_ops.sort_order(_mixed, 0, False, 8), [4, 0, 2, 6, 7, 3, 1, 5])
eq("descending reverses the ORDER but NOT the blanks rule — a sheet whose empty rows "
   "climb to the top on Z→A is not a sort anybody wanted",
   office_ops.sort_order(_mixed, 0, True, 8), [3, 7, 6, 2, 0, 4, 1, 5])
_ties = _sheet([[{"v": 5, "t": N}], [{"v": 5, "t": N}], [{"v": 1, "t": N}],
                [{"v": 5, "t": N}]])
eq("STABLE ascending: equal keys keep the order they were already in",
   office_ops.sort_order(_ties, 0, False, 4), [2, 0, 1, 3])
eq("…and stable DESCENDING too, because the tiebreak sits before the negation — "
   "sorting by one column twice must not shuffle ties",
   office_ops.sort_order(_ties, 0, True, 4), [0, 1, 3, 2])
_fx = _sheet([[{"f": "=B1", "v": 999, "t": N}], [{"v": 5, "t": N}]])
eq("a FORMULA sorts as its own text (class 'text'), never as its cached number — this "
   "lane may not pretend to know the sort order of a value it did not compute",
   office_ops.sort_order(_fx, 0, False, 2), [1, 0])

print("\n── 2e. rc_merges: shift, GROW on a straddling insert, shrink, drop ──")
M = [{"startRow": 5, "endRow": 6, "startColumn": 0, "endColumn": 1}]
eq("a merge wholly after the line shifts by n",
   office_ops.rc_merges(M, "row", 2, 2, False),
   [{"startRow": 7, "endRow": 8, "startColumn": 0, "endColumn": 1}])
eq("a merge that STRADDLES an insert GROWS by n, which is what Excel does and the only "
   "answer that leaves the same cells joined together",
   office_ops.rc_merges(M, "row", 6, 1, False),
   [{"startRow": 5, "endRow": 7, "startColumn": 0, "endColumn": 1}])
eq("a merge wholly BEFORE the line is untouched",
   office_ops.rc_merges(M, "row", 9, 3, False), M)
eq("on a delete, a straddling merge SHRINKS",
   office_ops.rc_merges([{"startRow": 5, "endRow": 7, "startColumn": 0,
                          "endColumn": 1}], "row", 7, 1, True),
   [{"startRow": 5, "endRow": 6, "startColumn": 0, "endColumn": 1}])
eq("…one wholly inside the deleted band is DROPPED — there is nothing left of it",
   office_ops.rc_merges(M, "row", 5, 2, True), [])
eq("…and so is one that would collapse to a SINGLE cell: a two-row merge losing one "
   "row is not a merge any more (the page's test is `end <= start`, not `<`)",
   office_ops.rc_merges(M, "row", 6, 1, True), [])
eq("the CROSS-axis bounds and every other key survive verbatim",
   office_ops.rc_merges([{"startRow": 3, "endRow": 3, "startColumn": 7,
                          "endColumn": 9, "note": "keep me"}], "row", 0, 1, False),
   [{"startRow": 4, "endRow": 4, "startColumn": 7, "endColumn": 9, "note": "keep me"}])
eq("an unreadable merge entry is DROPPED, not guessed at",
   office_ops.rc_merges([None, {"startRow": "x", "endRow": 2}, "nope"],
                        "row", 0, 1, False), [])


# ══ 3. THE SEMANTICS TABLE, EXECUTED AGAINST REAL WORKBOOKS ═════════════════
TMP = tempfile.mkdtemp(prefix="harness-office-mcp-")
D = office.office_dir(TMP)


def make(name, rows, merges=(), styles=None):
    """A real .xlsx on disk, written by openpyxl — not a snapshot dict."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            if v is not None:
                ws.cell(row=r, column=c).value = v
    for m in merges:
        ws.merge_cells(m)
    for ref, font in (styles or {}).items():
        ws[ref].font = font
    p = os.path.join(D, name)
    wb.save(p)
    return p


def read(name, sheet=0):
    wb = openpyxl.load_workbook(os.path.join(D, name), data_only=False)
    ws = wb.worksheets[sheet] if isinstance(sheet, int) else wb[sheet]
    grid = [[ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
            for r in range(1, ws.max_row + 1)]
    merges = sorted(str(m) for m in ws.merged_cells.ranges)
    return grid, merges, ws


if HAVE_XL:
    print("\n── 3a. THE SORT MERGE-REFUSAL, on a real workbook ──")
    # ⚠️ THE MERGE IS AT D1:E1, AWAY FROM THE SORTED DATA, AND THAT IS THE POINT:
    # `sortGo` refuses on ANY merge anywhere on the sheet, not only one intersecting
    # the sorted range. (It is also the only way to write this fixture — openpyxl's
    # merge_cells BLANKS every cell but the top-left, so merging over the data would
    # have destroyed the values the assertion reads.)
    make("merged.xlsx", [["b", 30, None, "x", None], ["a", 10], ["c", 20]],
         merges=["D1:E1"])
    out, reason = office_ops.op_sort(TMP, "merged.xlsx", None, "B")
    grid, merges, _ = read("merged.xlsx")
    eq("A SORT ON A MERGED SHEET IS REFUSED, and no cell moved",
       [row[1] for row in grid[:3]], [30, 10, 20])
    eq("…the merge itself is untouched", merges, ["D1:E1"])
    check("…it is REPORTED as skipped rather than swallowed — the tool result says so, "
          "so the MODEL learns it and not only the user",
          out is not None and out["operations_skipped"] == 1 and out["sorted"] == 0)
    check("…in words that name what would have gone wrong",
          any("merged range" in n and "never belonged together" in n
              for n in out["notes"]))
    check("…and the pre-agent copy was still taken, because a refused OP is not a "
          "refused CALL", out["pre_agent_copy"] == "merged.pre-agent.xlsx")

    print("\n── 3b. A SORT THAT RUNS, on a real workbook ──")
    make("plain.xlsx", [["b", 30], ["a", 10], ["c", 20]])
    out, reason = office_ops.op_sort(TMP, "plain.xlsx", None, "B")
    grid, _m, _ws = read("plain.xlsx")
    eq("the rows really sorted, and column A came with them",
       [(row[0], row[1]) for row in grid[:3]], [("a", 10), ("c", 20), ("b", 30)])
    check("…reported as one sort, and it SAYS row 1 went with the rest",
          out["sorted"] == 1
          and any("ROW 1 INCLUDED" in n for n in out["notes"]))
    make("plainz.xlsx", [["b", 30], ["a", 10], ["c", 20]])
    office_ops.op_sort(TMP, "plainz.xlsx", None, "B", True)
    grid, _m, _ws = read("plainz.xlsx")
    eq("Z→A is the same sort the other way up",
       [row[1] for row in grid[:3]], [30, 20, 10])

    print("\n── 3c. A SORT MOVES A FORMULA AS TEXT AND SAYS SO ──")
    make("fx.xlsx", [["b", 30], ["a", 10], ["c", 20, "=B3*2"]])
    out, reason = office_ops.op_sort(TMP, "fx.xlsx", None, "B")
    grid, _m, _ws = read("fx.xlsx")
    eq("the formula moved with its row and STILL SAYS WHAT IT SAID — no reference was "
       "rewritten, which is the honest half of the bound",
       grid[1][2], "=B3*2")
    check("…and the tool RESULT carries the page's own sentence about it, so the model "
          "is told rather than only the user",
          office_ops.RC_FORMULA_NOTE in out["notes"])

    print("\n── 3d. AN INSERT SHIFTS MERGES AND LEAVES FORMULA TEXT ──")
    # Again the merge sits away from the data (openpyxl blanks the non-anchor cells of
    # a merge), so the formula assertion below reads a real formula and not a hole.
    make("ins.xlsx", [["top", None, None, None], [None, None, None, None],
                      ["below", "=A1", "m", None]], merges=["C3:D3"])
    out, reason = office_ops.op_insert_delete(TMP, "ins.xlsx", None, "insert", "row", 3)
    grid, merges, _ws = read("ins.xlsx")
    eq("the rows below the line moved down, once", grid[3][0], "below")
    eq("…the inserted row is blank", grid[2][:2], [None, None])
    eq("THE MERGE WAS RENUMBERED", merges, ["C4:D4"])
    eq("THE FORMULA WAS NOT: it still says =A1", grid[3][1], "=A1")
    check("…and the result says both halves out loud",
          out["rows_or_columns_inserted"] == 1
          and office_ops.RC_FORMULA_NOTE in out["notes"])

    print("\n── 3e. A DELETE PULLS THE REST UP ──")
    make("del.xlsx", [["b", 30], ["a", 10], ["c", 20]])
    out, reason = office_ops.op_insert_delete(TMP, "del.xlsx", None, "delete", "row", 1)
    grid, _m, _ws = read("del.xlsx")
    eq("'at': 1 is ROW 1, the way a person says it, so the first row is the one that "
       "goes — and the tail is cleared rather than left duplicated",
       [row[0] for row in grid], ["a", "c"])
    eq("…counted as a delete", out["rows_or_columns_deleted"], 1)
    out, reason = office_ops.op_insert_delete(TMP, "del.xlsx", None, "delete", "row",
                                             1, 9999)
    check("…and a delete past the cap is REFUSED with the cap in the sentence, not "
          "quietly clamped", out is None and str(office_ops.RC_MAX) in reason)

    print("\n── 3f. THE SHARED-STYLE-ID TRAP, through a real write ──")
    make("style.xlsx", [["a", "b"]],
         styles={"A1": Font(italic=True), "B1": Font(italic=True)})
    out, reason = office_ops.op_write_cells(
        TMP, "style.xlsx", None, [{"op": "style", "at": "A1", "set": {"bl": 1}}])
    _g, _m, ws = read("style.xlsx")
    check("the style write bolded A1 and KEPT its italic — the base was resolved and "
          "COPIED, not replaced", ws["A1"].font.bold and ws["A1"].font.italic)
    check("…and the cell that shared the style is UNTOUCHED. openpyxl hands out a "
          "SHARED style record for cells with the same format; writing through it "
          "would have bolded B1 too, silently, and the save would make it permanent.",
          ws["B1"].font.italic and not ws["B1"].font.bold)
    # …and the snapshot-level trap the page records, which is the one a page-authored
    # workbook can actually carry (a string `s` id into snapshot.styles).
    snap = {"styles": {"S1": {"it": 1}},
            "sheetOrder": ["s1"],
            "sheets": {"s1": _sheet([[{"v": "a", "t": S, "s": "S1"},
                                      {"v": "b", "t": S, "s": "S1"}]])}}
    office_ops.run_ops(snap, "s1",
                       office_ops.validate_ops(
                           [{"op": "style", "at": "A1", "set": {"bl": 1}}])[0])
    eq("a style write RESOLVES a shared style ID, copies it and writes the copy back "
       "INLINE on that one cell", snap["sheets"]["s1"]["cellData"]["0"]["0"],
       {"v": "a", "t": S, "s": {"it": 1, "bl": 1}})
    eq("…the cell that shared the id keeps the id",
       snap["sheets"]["s1"]["cellData"]["0"]["1"], {"v": "b", "t": S, "s": "S1"})
    eq("…and the shared entry itself is unchanged — mutating it would bold half the "
       "workbook", snap["styles"]["S1"], {"it": 1})

    print("\n── 3g. WRITE VALUES, and the cells nobody mentioned ──")
    make("w.xlsx", [["keep", None], [None, None]])
    out, reason = office_ops.op_write_cells(TMP, "w.xlsx", None, [
        {"op": "set", "at": "B1", "values": [["Month", "Planned"], ["January", 900]]},
        {"op": "set", "at": "B4", "values": [["=SUM(C1:C3)"]]},
        {"op": "set", "at": "D1", "values": [[None]]}])
    grid, _m, _ws = read("w.xlsx")
    eq("the values landed where the change said, with the number as a NUMBER and the "
       "formula as a FORMULA",
       [grid[0][1], grid[0][2], grid[1][1], grid[1][2], grid[3][1]],
       ["Month", "Planned", "January", 900, "=SUM(C1:C3)"])
    eq("THE CELL NOBODY MENTIONED IS UNTOUCHED", grid[0][0], "keep")
    eq("…and the report counts written and emptied apart",
       (out["cells_written"], out["cells_emptied"]), (5, 1))

    print("\n── 3h. READ: formulas as TEXT plus a value LABELLED cached ──")
    make("read.xlsx", [["Month", "Planned"], ["Jan", 900], [None, "=SUM(B2:B2)"]])
    out, reason = office_ops.op_read(TMP, "read.xlsx", None, "A1:B3")
    byref = {c["ref"]: c for c in out["cells"]}
    eq("a value cell comes back as a value", byref["B2"]["value"], 900)
    check("a formula cell comes back as TEXT, flagged cached, and NEVER as 'value'",
          byref["B3"]["formula"] == "=SUM(B2:B2)"
          and byref["B3"]["cached"] is True
          and "value" not in byref["B3"])
    check("…and the result carries the whole honesty paragraph, so the model cannot "
          "mistake a cached number for a computed one",
          office_ops.CACHED_NOTE in out["notes"])
    out, reason = office_ops.op_read(TMP, "read.xlsx", None, "A1:BZ200")
    check("a read over the cell cap is refused with the number in the sentence",
          out is None and str(office_ops.READ_MAX_CELLS) in reason)
    out, reason = office_ops.op_read(TMP, "read.xlsx", None, "not a range")
    check("…and a junk range is refused rather than read as something else",
          out is None and "not a cell or a range" in reason)

    print("\n── 3i. STATS ──")
    out, reason = office_ops.op_sheet_stats(TMP, "read.xlsx")
    colb = [c for c in out["columns"] if c["column"] == "B"][0]
    check("a column's numbers are counted and summarised, and a formula counts as a "
          "FORMULA rather than as its cached number",
          colb["numbers"] == 1 and colb["sum"] == 900 and colb["formulas"] == 1)
    eq("row 1 is reported as it IS — no header guessing anywhere in this lane",
       colb["first_row_value"], "Planned")

    print("\n── 3j. CREATE never clobbers ──")
    out, reason = office_ops.op_create(TMP, "brand new")
    eq("a create returns the name it actually got", out["name"], "brand new.xlsx")
    out2, reason = office_ops.op_create(TMP, "brand new")
    eq("…and a second create of the same name STEPS rather than overwriting",
       out2["name"], "brand new (2).xlsx")
    check("…and says so, so the model uses the right name next turn",
          any("already existed" in n for n in out2["notes"]))
    out3, reason = office_ops.op_create(TMP, "../escape")
    check("a create cannot escape the folder either",
          out3 is None or out3["name"] == "escape.xlsx")

    print("\n── 3k. SHEETS ──")
    make("sheets.xlsx", [["x"]])
    out, reason = office_ops.op_write_cells(TMP, "sheets.xlsx", None, [
        {"op": "sheet", "add": "Notes"}, {"op": "sheet", "add": "Notes"}])
    wb = openpyxl.load_workbook(os.path.join(D, "sheets.xlsx"))
    eq("two sheets asked for by the same name do not collide — the second is renamed, "
       "never dropped and never a duplicate",
       wb.sheetnames, ["Sheet1", "Notes", "Notes 2"])
    out, reason = office_ops.op_write_cells(TMP, "sheets.xlsx", "Nope", [
        {"op": "set", "at": "A1", "values": [["landed"]]}])
    check("a sheet the model named that does not exist falls back to the first one AND "
          "THE RESULT SAYS SO — a write on a different sheet than the model believed "
          "must never read as a plain success",
          out is not None and any("there is no sheet called" in n for n in out["notes"]))


# ══ 4. THE WRITE-SAFETY RULES S1 OWNS ═══════════════════════════════════════
print("\n── 4a. the pre-agent copy: it exists, and it holds the PRE-write content ──")
eq("the name is <stem>.pre-agent.xlsx, beside the file and distinct from the daily .bak",
   os.path.basename(office_ops.pre_agent_for("/x/Sales.xlsx")), "Sales.pre-agent.xlsx")
check("…and it can never become .pre-agent.pre-agent.xlsx",
      office_ops.pre_agent_for("/x/Sales.pre-agent.xlsx")
      == "/x/Sales.pre-agent.xlsx")
if HAVE_XL:
    make("undo.xlsx", [["before"]])
    out, reason = office_ops.op_write_cells(TMP, "undo.xlsx", None, [
        {"op": "set", "at": "A1", "values": [["after"]]}])
    eq("the write reports the copy it took", out["pre_agent_copy"],
       "undo.pre-agent.xlsx")
    check("the daily .bak is taken as well — the two are not substitutes: the .bak "
          "answers 'the way it was this morning', the pre-agent copy answers 'the way "
          "it was before the agent touched it'",
          bool(out["daily_backup"]))
    check("the copy EXISTS on disk",
          os.path.isfile(os.path.join(D, "undo.pre-agent.xlsx")))
    eq("…and it holds what the cell said BEFORE the write — this is the agent lane's "
       "whole undo, so its CONTENT is the assertion, not its existence",
       read("undo.pre-agent.xlsx")[0][0][0], "before")
    eq("…while the workbook itself holds the write", read("undo.xlsx")[0][0][0], "after")
    out, reason = office_ops.op_write_cells(TMP, "undo.xlsx", None, [
        {"op": "set", "at": "A1", "values": [["again"]]}])
    eq("a SECOND agent write overwrites the copy — it is one level, and it answers "
       "'put it back the way it was before the agent touched it'",
       read("undo.pre-agent.xlsx")[0][0][0], "after")
    check("…and the note in the result NAMES the file, because a model that reports a "
          "write must be able to say how to undo it",
          any("undo.pre-agent.xlsx" in n for n in out["notes"]))
    check("every write result also carries the fidelity contract, because an agent "
          "write re-saves the whole workbook the way ⌘S does",
          any(office.FIDELITY_NOTE in n for n in out["notes"]))

print("\n── 4b. the open-dirty refusal, and why NO heartbeat means ALLOWED ──")
office_ops.heartbeat_clear()
eq("with no heartbeat a workbook reads as closed — a page that crashed must never "
   "leave a file nobody can write",
   office_ops.open_state("x.xlsx"), {"open": False, "dirty": False})
office_ops.heartbeat("x.xlsx", True)
eq("a heartbeat with dirty=true reads as open AND dirty",
   office_ops.open_state("x.xlsx"), {"open": True, "dirty": True})
office_ops.heartbeat("x.xlsx", True, now=time.time() - (office_ops.HEARTBEAT_TTL + 1))
eq("…and a STALE one reads as closed: the heartbeat is advisory with a TTL, never a "
   "lock file", office_ops.open_state("x.xlsx"), {"open": False, "dirty": False})
office_ops.heartbeat("x.xlsx", False)
eq("open-and-CLEAN is open but not dirty, which rule 2 allows",
   office_ops.open_state("x.xlsx"), {"open": True, "dirty": False})
check("a junk name cannot register a heartbeat",
      office_ops.heartbeat("../etc/passwd", True)["ok"] is False)
office_ops.heartbeat_clear()

if HAVE_XL:
    make("busy.xlsx", [["mine"]])
    office_ops.heartbeat("busy.xlsx", True)
    out, reason = office_ops.op_write_cells(TMP, "busy.xlsx", None, [
        {"op": "set", "at": "A1", "values": [["agent"]]}])
    eq("a write to a workbook with UNSAVED EDITS is refused, in the spec's own words",
       (out, reason), (None, office_ops.DIRTY_REFUSAL))
    eq("…and nothing was written", read("busy.xlsx")[0][0][0], "mine")
    check("…and no pre-agent copy was made either — the refusal is BEFORE the copy",
          not os.path.exists(os.path.join(D, "busy.pre-agent.xlsx")))
    office_ops.heartbeat("busy.xlsx", False)
    out, reason = office_ops.op_write_cells(TMP, "busy.xlsx", None, [
        {"op": "set", "at": "A1", "values": [["agent"]]}])
    eq("open-and-CLEAN is allowed", read("busy.xlsx")[0][0][0], "agent")
    check("…and the result warns that the page will reload under her",
          any("OPEN in LOffice" in n for n in out["notes"]))
    office_ops.heartbeat_clear()


# ══ 5. THE MCP SURFACE, through the MOUNTED app ═════════════════════════════
print("\n── 5. the MCP surface ──")
SPECS = office_mcp.tool_specs()
eq("the six spec rows are these seven tool names — office_sort and "
   "office_insert_delete share a row in the spec table but are separate tools",
   [t["name"] for t in SPECS],
   ["office_list", "office_read", "office_sheet_stats", "office_write_cells",
    "office_sort", "office_insert_delete", "office_create"])
# ⚠️ THE APPROVAL FENCE. `readOnlyHint: true` is what DISARMS Hermes's approval card
# (vendor/hermes/tools/mcp_tool.py:3999 — `hint is True`). A write tool that gained it
# would lose its card silently, which is why this is asserted as a SET on both sides
# rather than spot-checked.
eq("exactly the three read tools are declared read-only", office_mcp.read_tool_names(),
   ["office_list", "office_read", "office_sheet_stats"])
eq("exactly the four write tools are NOT — these are the ones Hermes puts behind an "
   "approval card", office_mcp.write_tool_names(),
   ["office_write_cells", "office_sort", "office_insert_delete", "office_create"])
PAYLOAD = office_mcp.tool_list_payload()
check("every read tool carries annotations.readOnlyHint TRUE (not 'truthy' — Hermes "
      "tests `hint is True`)",
      all(t["annotations"].get("readOnlyHint") is True for t in PAYLOAD
          if t["name"] in office_mcp.read_tool_names()))
check("…and NO write tool carries readOnlyHint at all, so a client that ignores "
      "annotations still sees no claim of read-onlyness",
      all("readOnlyHint" not in t["annotations"] for t in PAYLOAD
          if t["name"] in office_mcp.write_tool_names()))
check("every tool has a description that teaches the name-addressing rule",
      all("addressed by NAME" in t["description"] for t in PAYLOAD))
check("no tool takes a path-shaped argument — containment is BY CONSTRUCTION, so "
      "there must be no argument called path/file/dir/folder anywhere",
      all(not {"path", "filepath", "file", "dir", "directory", "folder"}
          & set((t["inputSchema"].get("properties") or {}).keys()) for t in PAYLOAD))
check("every schema is a closed object — an argument we do not read must not be "
      "silently accepted",
      all(t["inputSchema"].get("additionalProperties") is False for t in PAYLOAD))
eq("the write tools' descriptions say the pre-agent copy is the undo",
   sorted(t["name"] for t in PAYLOAD
          if "pre-agent" in t["description"] or "pre-agent" in
          json.dumps(t["inputSchema"])),
   ["office_write_cells"])
eq("negotiate() echoes a protocol it knows and names its own for one it does not",
   [office_mcp.negotiate("2025-06-18"), office_mcp.negotiate("1999-01-01"),
    office_mcp.negotiate(None)],
   ["2025-06-18", office_mcp.DEFAULT_PROTOCOL, office_mcp.DEFAULT_PROTOCOL])

# ── the Hermes config entry ──
ENTRY = office_mcp.hermes_entry(8700)
eq("the entry is Hermes's url-only (= Streamable HTTP) shape, on LOOPBACK, with the "
   "trust key that arms the approval gate",
   ENTRY, {"url": "http://127.0.0.1:8700/mcp/office", "trust": "untrusted",
           "timeout": 120})
check("it can never bind a non-loopback host",
      office_mcp.hermes_entry(9999)["url"].startswith("http://127.0.0.1:"))
eq("a junk port produces no entry rather than a wrong one",
   [office_mcp.hermes_entry(0), office_mcp.hermes_entry("x"),
    office_mcp.hermes_entry(70000)], [{}, {}, {}])
check("`trust: untrusted` is the whole approval story on the config side, and Hermes "
      "really is the code that reads it",
      "trust" in ENTRY and ENTRY["trust"] == "untrusted")

# ── the transport, live, against the mounted app ──
try:
    from fastapi.testclient import TestClient                    # noqa: E402
    from bridge.app import app as _app                           # noqa: E402
    cl = TestClient(_app)

    def rpc(method, params=None, rid=1):
        body = {"jsonrpc": "2.0", "method": method}
        if rid is not None:
            body["id"] = rid
        if params is not None:
            body["params"] = params
        return cl.post(office_mcp.MOUNT_PATH, json=body)

    r = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "1"}})
    j = r.json()
    check("initialize answers 200 with a single application/json body — the branch a "
          "real MCP client takes at streamable_http.py:365",
          r.status_code == 200
          and r.headers["content-type"].startswith("application/json"))
    check("…naming the protocol, the tools capability and the server",
          j["result"]["protocolVersion"] == "2025-06-18"
          and "tools" in j["result"]["capabilities"]
          and j["result"]["serverInfo"]["name"] == "loffice")
    check("…and handing back an Mcp-Session-Id for a client that wants to echo one",
          bool(r.headers.get("mcp-session-id")))
    check("the instructions tell the model the three things it cannot discover by "
          "trying: name-addressing, no formula engine, and the pre-agent copy",
          all(s in j["result"]["instructions"]
              for s in ("office_list", "pre-agent", "computes a formula")))

    r = cl.post(office_mcp.MOUNT_PATH,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    check("A NOTIFICATION IS ANSWERED 202 WITH AN EMPTY BODY. Answering it with a "
          "JSON-RPC response is the single most common way a hand-written MCP server "
          "breaks: the client reads it as a reply to a request it never sent.",
          r.status_code == 202 and not r.content)
    r = cl.post(office_mcp.MOUNT_PATH,
                json={"jsonrpc": "2.0", "method": "notifications/cancelled",
                      "params": {"requestId": 1}})
    check("…and so is any other notification, known or not", r.status_code == 202)

    r = cl.get(office_mcp.MOUNT_PATH)
    check("GET is 405 with an Allow header: this server never initiates anything, so "
          "there is no stream to open, and the client stops asking "
          "(streamable_http.py:588)",
          r.status_code == 405 and "POST" in r.headers.get("allow", ""))
    check("DELETE is honoured, because a client that cleans up should not be told off "
          "for it", cl.delete(office_mcp.MOUNT_PATH).status_code == 204)

    tools = rpc("tools/list").json()["result"]["tools"]
    eq("tools/list over the wire is the same catalog", [t["name"] for t in tools],
       [t["name"] for t in SPECS])
    check("ping answers", rpc("ping").json()["result"] == {})
    check("an unknown METHOD is a JSON-RPC error, because that is a protocol fault",
          rpc("nope/nope").json()["error"]["code"] == -32601)
    check("an unknown TOOL likewise", "error" in rpc(
        "tools/call", {"name": "office_delete_everything", "arguments": {}}).json())
    r = cl.post(office_mcp.MOUNT_PATH, content=b"{not json")
    check("a body that is not JSON is a parse error, not a traceback",
          r.status_code == 400 and r.json()["error"]["code"] == -32700)

    # ⚠️ CONTAINMENT, OVER THE WIRE. Every one of these is a TOOL error with a
    # SENTENCE, never a transport error: a model that gets "refused: a workbook is
    # addressed by name, not by path" learns the rule; one that gets a 500 learns
    # nothing and retries.
    for arg, why in [("../../etc/passwd", "traversal"),
                     ("/etc/passwd", "an absolute path"),
                     ("a/b.xlsx", "a separator"),
                     (".hidden.xlsx", "a dotfile"),
                     ("notes.docx", "a non-xlsx extension"),
                     ("", "an empty name"),
                     (None, "no name at all"),
                     ("x" * 200, "an absurd name")]:
        res = rpc("tools/call", {"name": "office_read",
                                 "arguments": {"name": arg}}).json()["result"]
        body = json.loads(res["content"][0]["text"])
        check(f"REFUSED over MCP, with a sentence and isError — {why}",
              res["isError"] is True and body["ok"] is False
              and isinstance(body.get("error"), str) and len(body["error"]) > 8)
    res = rpc("tools/call", {"name": "office_list",
                             "arguments": {}}).json()["result"]
    check("office_list works over the wire and is not an error",
          res["isError"] is False and json.loads(res["content"][0]["text"])["ok"])
    check("…and it teaches the containment rule in its own notes, so a model that "
          "never read a tool description still learns it",
          any("outside data/office" in n
              for n in json.loads(res["content"][0]["text"])["notes"]))
    for tool in office_mcp.write_tool_names():
        res = rpc("tools/call", {"name": tool,
                                 "arguments": {"name": "../x.xlsx"}}).json()["result"]
        check(f"…and {tool} refuses a path just as hard", res["isError"] is True)

    # ── the heartbeat endpoint, which is the seam S2 plugs into ──
    r = cl.post("/api/office/heartbeat", json={"name": "hb.xlsx", "dirty": True})
    check("POST /api/office/heartbeat registers {name, dirty}",
          r.status_code == 200 and r.json()["ok"] is True
          and office_ops.open_state("hb.xlsx") == {"open": True, "dirty": True})
    r = cl.post("/api/office/heartbeat", json={"name": "hb.xlsx", "close": True})
    check("…and {close:true} forgets it",
          r.json()["closed"] is True
          and office_ops.open_state("hb.xlsx")["open"] is False)
    check("a junk name is a 400 with a reason, not a 500",
          cl.post("/api/office/heartbeat",
                  json={"name": "../x"}).status_code == 400)
    check("a junk BODY is answered rather than raising",
          cl.post("/api/office/heartbeat", content=b"nonsense").status_code in (200, 400))

    st = cl.get("/api/office/mcp").json()
    check("GET /api/office/mcp reports what the entry SHOULD be and whether Hermes has "
          "it — the out-of-sync/Adopt reconciliation reads exactly this",
          st["expected"] == ENTRY and "in_sync" in st and "registered" in st)
    eq("…and names the approval split honestly, including the mechanism",
       (st["approval"]["gated"], st["approval"]["ungated"]),
       (office_mcp.write_tool_names(), office_mcp.read_tool_names()))
    check("…and says which mechanism it is, because Hermes has no per-tool approval "
          "field and a reader must not be left to assume it does",
          "trust=untrusted" in st["approval"]["mechanism"]
          and "readOnlyHint" in st["approval"]["mechanism"])
except Exception as _e:                                          # noqa: BLE001
    check(f"the mounted MCP surface could be exercised (got {_e!r})", False)


# ══ 6. CONFIG-GEN: idempotent, and it never disturbs a neighbour ════════════
print("\n── 6. config-gen ──")
SCRIPT = (ROOT / "scripts" / "start_component.sh").read_text(encoding="utf-8")
m = re.search(r"<<'PYLOFFICE'\n([\s\S]*?)\nPYLOFFICE\n", SCRIPT)
check("the config-gen step really is in scripts/start_component.sh's hermes branch — "
      "a test against its own copy of the entry would pass while the script drifted",
      bool(m))
check("…in the hermes branch specifically, so it runs on every Hermes start and "
      "therefore survives a pin bump",
      bool(m) and SCRIPT.index("PYLOFFICE") > SCRIPT.index("harness-path-guard"))
if m:
    GEN = m.group(1)
    check("…and it reads the bridge port out of harness.yaml rather than hardcoding it",
          "BR_PORT=$(awk '/^bridge:/" in SCRIPT)
    check("…with the trust key, without which the write tools would have NO approval "
          "card", '"trust": "untrusted"' in GEN)
    genpy = Path(tempfile.mkdtemp(prefix="harness-loffice-gen-")) / "gen.py"
    genpy.write_text(GEN, encoding="utf-8")

    def run_gen(cfg_path, port="8700"):
        env = dict(os.environ, HCFG=str(cfg_path), BR_PORT=port)
        return subprocess.run([sys.executable, str(genpy)], capture_output=True,
                              text=True, env=env, timeout=60)

    import yaml                                                  # noqa: E402
    cdir = Path(tempfile.mkdtemp(prefix="harness-loffice-cfg-"))
    cfg = cdir / "config.yaml"

    out = run_gen(cfg)
    data = yaml.safe_load(cfg.read_text())
    eq("the entry lands, exactly as bridge/office_mcp.hermes_entry() would write it — "
       "one shape, two writers, and this is what keeps them the same",
       data["mcp_servers"]["loffice"], ENTRY)
    check("…and it says so on stdout, because a silent config write is a config write "
          "nobody can debug", "LOffice MCP server registered" in out.stdout)

    before = cfg.read_bytes()
    out = run_gen(cfg)
    check("A SECOND RUN DOES NOT TOUCH THE FILE AT ALL — idempotent by BYTES, not "
          "merely by result, so the yaml round-trip's one cost (comments, key order) "
          "is paid once and never again",
          cfg.read_bytes() == before and "already registered" in out.stdout)

    # THE PIN-BUMP / NEIGHBOUR CASE, in the shape the a2a mirror's tests take: a real
    # config with other servers, other keys, and a stale url.
    cfg.write_text(yaml.safe_dump({
        "model": {"default": "local"},
        "approvals": {"mode": "manual"},
        "plugins": {"enabled": ["harness-path-guard"]},
        "mcp_servers": {
            "browsermcp": {"command": "npx", "args": ["@browsermcp/mcp"]},
            "voicestudio": {"url": "http://127.0.0.1:3900/mcp"},
            "loffice": {"url": "http://127.0.0.1:9999/mcp/office"},
        }}, sort_keys=False), encoding="utf-8")
    run_gen(cfg)
    data = yaml.safe_load(cfg.read_text())
    eq("a STALE loffice entry is corrected", data["mcp_servers"]["loffice"], ENTRY)
    eq("…every other MCP server is preserved byte for byte",
       (data["mcp_servers"]["browsermcp"], data["mcp_servers"]["voicestudio"]),
       ({"command": "npx", "args": ["@browsermcp/mcp"]},
        {"url": "http://127.0.0.1:3900/mcp"}))
    eq("…and so is every other top-level key: the config-gen writes ONE key and reads "
       "the rest through unchanged",
       (data["model"], data["approvals"], data["plugins"]),
       ({"default": "local"}, {"mode": "manual"},
        {"enabled": ["harness-path-guard"]}))

    cfg.write_text("mcp_servers: not-a-mapping\n", encoding="utf-8")
    run_gen(cfg)
    eq("a junk mcp_servers block is REPLACED rather than crashing the Hermes start",
       yaml.safe_load(cfg.read_text())["mcp_servers"]["loffice"], ENTRY)
    cfg.write_text("{{{ not yaml at all\n", encoding="utf-8")
    out = run_gen(cfg)
    check("an unparseable config is left ALONE with a warning — a start script that "
          "clobbers a config it could not read is worse than one that does nothing",
          out.returncode == 0 and "WARNING" in out.stdout
          and cfg.read_text().startswith("{{{"))
    gone = cdir / "nested" / "config.yaml"
    run_gen(gone)
    check("a config that does not exist yet is created",
          yaml.safe_load(gone.read_text())["mcp_servers"]["loffice"] == ENTRY)
    shutil.rmtree(cdir, ignore_errors=True)

# The bridge-side writer, over the same temp HERMES_HOME test_voice_mcp.py uses.
try:
    from bridge.app import (_hermes_get_mcp, _hermes_write_mcp,  # noqa: E402
                            hermes_cfg_gen)
    _hermes_write_mcp("browsermcp", {"command": "npx", "args": ["@browsermcp/mcp"]})
    g0 = hermes_cfg_gen()
    check("the bridge-side writer lands the same entry",
          _hermes_write_mcp("loffice", ENTRY) and _hermes_get_mcp("loffice") == ENTRY)
    g1 = hermes_cfg_gen()
    check("…re-writing the identical entry is a no-op that does not even move the "
          "config generation, so it cannot cause a spurious Hermes reload",
          _hermes_write_mcp("loffice", ENTRY) and hermes_cfg_gen() == g1 and g1 > g0)
    check("…and removing it leaves the neighbour alone",
          _hermes_write_mcp("loffice", None) is False
          and _hermes_get_mcp("loffice") is None
          and _hermes_get_mcp("browsermcp") == {"command": "npx",
                                                "args": ["@browsermcp/mcp"]})
except Exception as _e:                                          # noqa: BLE001
    check(f"the bridge-side registration helpers could be exercised (got {_e!r})", False)


# ══ housekeeping ════════════════════════════════════════════════════════════
shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(_HHOME, ignore_errors=True)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print(f"office agent lane OK — all checks passed"
      f"{'' if HAVE_XL else ' (executed-workbook tables SKIPPED: no openpyxl)'}")
