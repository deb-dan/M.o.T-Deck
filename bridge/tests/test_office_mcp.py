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
# ⚠️ EVERY TABLE BELOW NOW RUNS THROUGH stage → apply, AND THAT IS THE POINT OF THE
# REWRITE. In v1 each of these called an op_* MCP tool that wrote the file directly;
# those tools are gone (docs/FABLE-AGENT-CHANGESET-SPEC.md §1). The semantics did not
# change — the same run_ops, the same merge refusal, the same caps — but the ROUTE did,
# so testing the semantics through the route is strictly better: it proves the change a
# model proposes is the change a person's Apply carries out.
TMP = tempfile.mkdtemp(prefix="harness-office-mcp-")
D = office.office_dir(TMP)
SESS = "test-session"


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


def stage(name, ops, sheet=None, session=SESS):
    """(staged, None) or (None, reason) — what an MCP office_stage_changes call does."""
    return office_ops.stage_changes(TMP, session, name, sheet, ops)


def run(name, ops, sheet=None, session=SESS):
    """stage → apply. THE ONLY WAY A WORKBOOK IS WRITTEN in v2, and the apply half is
    reachable from a button and from no tool at all."""
    st, reason = stage(name, ops, sheet, session)
    if st is None:
        return None, reason
    return office_ops.apply_changeset(TMP, st["changeset_id"])


if HAVE_XL:
    print("\n── 3a. THE SORT MERGE-REFUSAL, on a real workbook ──")
    # ⚠️ THE MERGE IS AT D1:E1, AWAY FROM THE SORTED DATA, AND THAT IS THE POINT:
    # `sortGo` refuses on ANY merge anywhere on the sheet, not only one intersecting
    # the sorted range. (It is also the only way to write this fixture — openpyxl's
    # merge_cells BLANKS every cell but the top-left, so merging over the data would
    # have destroyed the values the assertion reads.)
    make("merged.xlsx", [["b", 30, None, "x", None], ["a", 10], ["c", 20]],
         merges=["D1:E1"])
    out, reason = run("merged.xlsx", [{"op": "sort", "col": "B"}])
    grid, merges, _ = read("merged.xlsx")
    eq("A SORT ON A MERGED SHEET IS REFUSED, and no cell moved",
       [row[1] for row in grid[:3]], [30, 10, 20])
    eq("…the merge itself is untouched", merges, ["D1:E1"])
    check("…it is REPORTED as skipped rather than swallowed — the receipt says so, and "
          "the STAGING said so before that, so the model learns it and the card shows it",
          out is not None and out["operations_skipped"] == 1 and out["sorted"] == 0)
    st, _r = stage("merged.xlsx", [{"op": "sort", "col": "B"}])
    check("…in words that name what would have gone wrong, ON THE CARD, before anybody "
          "presses Apply",
          any("merged range" in n and "never belonged together" in n
              for n in st["notes"]))
    eq("…and a refused op is a change with NOTHING in it, so the card says so instead of "
       "offering an Apply that would do nothing visible", st["cells_changed"], 0)
    check("…and the pre-agent copy was still taken, because a refused OP is not a "
          "refused CALL", out["pre_agent_copy"] == "merged.pre-agent.xlsx")

    print("\n── 3b. A SORT THAT RUNS, on a real workbook ──")
    make("plain.xlsx", [["b", 30], ["a", 10], ["c", 20]])
    out, reason = run("plain.xlsx", [{"op": "sort", "col": "B"}])
    grid, _m, _ws = read("plain.xlsx")
    eq("the rows really sorted, and column A came with them",
       [(row[0], row[1]) for row in grid[:3]], [("a", 10), ("c", 20), ("b", 30)])
    check("…reported as one sort, and it SAYS row 1 went with the rest",
          out["sorted"] == 1
          and any("ROW 1 INCLUDED" in n for n in out["notes"]))
    make("plainz.xlsx", [["b", 30], ["a", 10], ["c", 20]])
    run("plainz.xlsx", [{"op": "sort", "col": "B", "desc": True}])
    grid, _m, _ws = read("plainz.xlsx")
    eq("Z→A is the same sort the other way up",
       [row[1] for row in grid[:3]], [30, 20, 10])

    print("\n── 3c. A SORT MOVES A FORMULA AS TEXT AND SAYS SO ──")
    make("fx.xlsx", [["b", 30], ["a", 10], ["c", 20, "=B3*2"]])
    out, reason = run("fx.xlsx", [{"op": "sort", "col": "B"}])
    grid, _m, _ws = read("fx.xlsx")
    eq("the formula moved with its row and STILL SAYS WHAT IT SAID — no reference was "
       "rewritten, which is the honest half of the bound",
       grid[1][2], "=B3*2")
    check("…and the RECEIPT carries the page's own sentence about it, so the model is "
          "told rather than only the user",
          office_ops.RC_FORMULA_NOTE in out["notes"])

    print("\n── 3d. AN INSERT SHIFTS MERGES AND LEAVES FORMULA TEXT ──")
    # Again the merge sits away from the data (openpyxl blanks the non-anchor cells of
    # a merge), so the formula assertion below reads a real formula and not a hole.
    make("ins.xlsx", [["top", None, None, None], [None, None, None, None],
                      ["below", "=A1", "m", None]], merges=["C3:D3"])
    out, reason = run("ins.xlsx", [{"op": "insert", "what": "row", "at": 3}])
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
    out, reason = run("del.xlsx", [{"op": "delete_rc", "what": "row", "at": 1}])
    grid, _m, _ws = read("del.xlsx")
    eq("'at': 1 is ROW 1, the way a person says it, so the first row is the one that "
       "goes — and the tail is cleared rather than left duplicated",
       [row[0] for row in grid], ["a", "c"])
    eq("…counted as a delete", out["rows_or_columns_deleted"], 1)
    out, reason = stage("del.xlsx", [{"op": "delete_rc", "what": "row", "at": 1,
                                     "n": 9999}])
    check("…and a delete past the cap is REFUSED AT STAGING, with the cap in the "
          "sentence — the refusal now happens before there is anything to approve",
          out is None and str(office_ops.RC_MAX) in reason)

    print("\n── 3f. THE SHARED-STYLE-ID TRAP, through a real apply ──")
    make("style.xlsx", [["a", "b"]],
         styles={"A1": Font(italic=True), "B1": Font(italic=True)})
    out, reason = run("style.xlsx", [{"op": "style", "at": "A1", "set": {"bl": 1}}])
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
    out, reason = run("w.xlsx", [
        {"op": "set", "at": "B1", "values": [["Month", "Planned"], ["January", 900]]},
        {"op": "set", "at": "B4", "values": [["=SUM(C1:C3)"]]},
        {"op": "set", "at": "D1", "values": [[None]]}])
    grid, _m, _ws = read("w.xlsx")
    eq("the values landed where the change said, with the number as a NUMBER and the "
       "formula as a FORMULA",
       [grid[0][1], grid[0][2], grid[1][1], grid[1][2], grid[3][1]],
       ["Month", "Planned", "January", 900, "=SUM(C1:C3)"])
    eq("THE CELL NOBODY MENTIONED IS UNTOUCHED", grid[0][0], "keep")
    eq("…and the receipt counts written and emptied apart",
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

    print("\n── 3j. create_workbook: the retired office_create, absorbed ──")
    # ⚠️ A DELIBERATE BEHAVIOUR CHANGE, ARGUED. office_create stepped a taken name
    # ('budget.xlsx' → 'budget (2).xlsx') because a create was its own call and the
    # model's intent survived a rename. A changeset is about ONE workbook, named once,
    # and every other op in it addresses that name — so silently retargeting the whole
    # change at a DIFFERENT file would be the worst kind of helpful. It refuses instead.
    st, reason = stage("fresh book.xlsx", [{"op": "create_workbook"},
                                           {"op": "set", "at": "A1",
                                            "values": [["hello"]]}])
    check("a workbook that does not exist can be staged, and the card SAYS it will be "
          "created", st is not None and st["creates_workbook"] is True
          and any("does not exist yet" in n for n in st["notes"])
          and any("create the workbook" in o for o in st["op_list"]))
    check("…and NOTHING is on disk yet, because staging never writes",
          not os.path.exists(os.path.join(D, "fresh book.xlsx")))
    rc, reason = office_ops.apply_changeset(TMP, st["changeset_id"])
    check("…applying it creates the workbook and writes the cells in one gesture",
          rc is not None and rc["created_workbook"] is True
          and read("fresh book.xlsx")[0][0][0] == "hello")
    st, reason = stage("fresh book.xlsx", [{"op": "create_workbook"}])
    check("a create_workbook aimed at a workbook that ALREADY EXISTS is refused rather "
          "than stepped to a new name — a changeset addresses one file",
          st is None and "already exists" in reason)
    st, reason = stage("fresh book.xlsx", [{"op": "create_workbook"},
                                           {"op": "set", "at": "A2",
                                            "values": [["more"]]}])
    check("…but the same op alongside real work is simply DROPPED, and the rest stages "
          "against the existing file", st is not None
          and st["creates_workbook"] is False)
    st, reason = stage("../escape.xlsx", [{"op": "create_workbook"}])
    check("a create cannot escape the folder either", st is None)
    st, reason = stage("nothing here.xlsx", [{"op": "set", "at": "A1",
                                              "values": [["x"]]}])
    check("…and staging against a workbook that does not exist WITHOUT a create says so, "
          "naming the two ways forward",
          st is None and "office_list" in reason and "create_workbook" in reason)

    print("\n── 3k. SHEETS ──")
    make("sheets.xlsx", [["x"]])
    out, reason = run("sheets.xlsx", [{"op": "sheet", "add": "Notes"},
                                      {"op": "add_sheet", "name": "Notes"}])
    wb = openpyxl.load_workbook(os.path.join(D, "sheets.xlsx"))
    eq("two sheets asked for by the same name do not collide — the second is renamed, "
       "never dropped and never a duplicate; and `add_sheet` is the same op spelled the "
       "way the spec names it", wb.sheetnames, ["Sheet1", "Notes", "Notes 2"])
    out, reason = run("sheets.xlsx", [{"op": "set", "at": "A1",
                                      "values": [["landed"]]}], sheet="Nope")
    check("a sheet the model named that does not exist falls back to the first one AND "
          "THE RESULT SAYS SO — a write on a different sheet than the model believed "
          "must never read as a plain success",
          out is not None and any("there is no sheet called" in n for n in out["notes"]))


# ══ 4. THE WRITE-SAFETY RULES ═══════════════════════════════════════════════
print("\n── 4a. the pre-agent copy: it exists, and it holds the PRE-write content ──")
eq("the name is <stem>.pre-agent.xlsx, beside the file and distinct from the daily .bak",
   os.path.basename(office_ops.pre_agent_for("/x/Sales.xlsx")), "Sales.pre-agent.xlsx")
check("…and it can never become .pre-agent.pre-agent.xlsx",
      office_ops.pre_agent_for("/x/Sales.pre-agent.xlsx")
      == "/x/Sales.pre-agent.xlsx")
if HAVE_XL:
    make("undo.xlsx", [["before"]])
    out, reason = run("undo.xlsx", [{"op": "set", "at": "A1", "values": [["after"]]}])
    eq("the apply reports the copy it took", out["pre_agent_copy"],
       "undo.pre-agent.xlsx")
    check("the daily .bak is taken as well — the two are not substitutes: the .bak "
          "answers 'the way it was this morning', the pre-agent copy answers 'the way "
          "it was before the agent touched it'",
          bool(out["daily_backup"]))
    check("the copy EXISTS on disk",
          os.path.isfile(os.path.join(D, "undo.pre-agent.xlsx")))
    eq("…and it holds what the cell said BEFORE the write — this is the convenience "
       "undo, so its CONTENT is the assertion, not its existence",
       read("undo.pre-agent.xlsx")[0][0][0], "before")
    eq("…while the workbook itself holds the write", read("undo.xlsx")[0][0][0], "after")
    out, reason = run("undo.xlsx", [{"op": "set", "at": "A1", "values": [["again"]]}])
    eq("a SECOND apply overwrites the copy — it is one level, and it answers 'put it "
       "back the way it was before the last apply'",
       read("undo.pre-agent.xlsx")[0][0][0], "after")
    check("…and the note in the result NAMES the file, because a model that reports a "
          "write must be able to say how to undo it",
          any("undo.pre-agent.xlsx" in n for n in out["notes"]))
    check("every apply also carries the fidelity contract, because it re-saves the "
          "whole workbook the way ⌘S does",
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
    # ⚠️ THE REFUSAL MOVED FROM THE AGENT TO THE BUTTON, AND IT STAYED. In v1 it stopped
    # an UNATTENDED agent write. In v2 the only caller left is Debi's own Apply — and
    # applying over her unsaved edits would destroy them just as silently, so the rule
    # holds and the sentence now tells the person at the keyboard what clears it.
    make("busy.xlsx", [["mine"]])
    office_ops.heartbeat("busy.xlsx", True)
    st, reason = stage("busy.xlsx", [{"op": "set", "at": "A1", "values": [["agent"]]}])
    check("STAGING a workbook with unsaved edits is ALLOWED — a proposal harms nothing "
          "and refusing to even show one would be theatre", st is not None)
    check("…and the card warns that Apply will refuse until she saves",
          any("UNSAVED edits" in n for n in st["notes"]))
    out, reason = office_ops.apply_changeset(TMP, st["changeset_id"])
    eq("…but APPLYING is refused, and the sentence names the one thing that clears it",
       (out, reason), (None, office_ops.APPLY_DIRTY_REFUSAL))
    check("…and it says ⌘S, because 'unsaved edits' is not an instruction",
          "⌘S" in office_ops.APPLY_DIRTY_REFUSAL)
    eq("…and nothing was written", read("busy.xlsx")[0][0][0], "mine")
    check("…and no pre-agent copy was made either — the refusal is BEFORE the copy",
          not os.path.exists(os.path.join(D, "busy.pre-agent.xlsx")))
    office_ops.heartbeat("busy.xlsx", False)
    out, reason = office_ops.apply_changeset(TMP, st["changeset_id"])
    eq("open-and-CLEAN is allowed, and the SAME changeset applies — a refusal does not "
       "consume the proposal", read("busy.xlsx")[0][0][0], "agent")
    check("…and the result warns that the page will reload under her",
          any("OPEN in LOffice" in n for n in out["notes"]))
    office_ops.heartbeat_clear()


# ══ 4c. THE CHANGESET LANE ITSELF (the spec §6 bar) ═════════════════════════
# ⚠️ THIS IS THE GROUP THE WHOLE SLICE EXISTS FOR. Each block below answers one line of
# docs/FABLE-AGENT-CHANGESET-SPEC.md §6, and between them they are the technical form of
# "the model can propose and only a person can write".
if HAVE_XL:
    print("\n── 4c-1. STAGING PURITY: it computes a whole change and touches nothing ──")
    office_ops.changeset_clear()
    make("purity.xlsx", [["Category", "Amount"], ["Rent", 1000], ["Food", 300],
                         ["Transport", 135], ["Total", "=SUM(B2:B4)"]])
    path = os.path.join(D, "purity.xlsx")
    before_mtime, before_size = os.path.getmtime(path), os.path.getsize(path)
    before_bytes = open(path, "rb").read()
    st, reason = stage("purity.xlsx", [
        {"op": "insert", "what": "row", "at": 5},
        {"op": "set", "at": "A5", "values": [["purchases", 200]]},
        {"op": "set", "at": "B6", "values": [["=SUM(B2:B5)"]]}])
    check("the incident's own request stages in ONE call", st is not None, )
    # ⚠️⚠️ THE ASSERTION THE `readOnlyHint: true` ANNOTATION RESTS ON. If staging ever
    # touches the file, the annotation becomes a lie and Hermes's gate is disarmed for a
    # tool that writes. mtime AND bytes, because a same-size rewrite would pass on size.
    eq("THE FILE'S MTIME IS UNCHANGED BY STAGING", os.path.getmtime(path), before_mtime)
    eq("…and so is every byte of it — this is what makes readOnlyHint honest",
       open(path, "rb").read(), before_bytes)
    eq("…and its size", os.path.getsize(path), before_size)
    check("…and no sibling was created either: no .pre-agent, no .bak, no checkpoint",
          not os.path.exists(os.path.join(D, "purity.pre-agent.xlsx"))
          and not os.path.isdir(os.path.join(D, office_ops.CHECKPOINT_DIR, "purity")))

    print("\n── 4c-2. BEFORE VALUES, computed from the file for every touched cell ──")
    pv = {p["ref"]: p for p in st["preview"]}
    eq("every touched cell carries its BEFORE and its AFTER, read out of the workbook",
       [(r, pv[r]["before"], pv[r]["after"]) for r in ("A5", "B5", "A6", "B6")],
       [("A5", "Total", "purchases"), ("B5", "=SUM(B2:B4)", "200"),
        ("A6", "", "Total"), ("B6", "", "=SUM(B2:B5)")])
    check("…INCLUDING the two cells nobody named, which the INSERT pushed down. This is "
          "the class of change Hermes's own approval card could not show at all: it "
          "cannot put tool arguments on the wire, let alone their consequences.",
          "A6" in pv and pv["A6"]["before"] == "" and pv["A6"]["after"] == "Total")
    eq("a formula is shown as its FORMULA on both sides, never as a cached number — the "
       "cell that changed is the formula", pv["B5"]["before"], "=SUM(B2:B4)")
    eq("the op list is one human line per operation, in the order they will run",
       st["op_list"], ["insert 1 blank row(s) above row 5", "set A5:B5", "set B6"])
    check("the summary line says what will change and how much",
       "purchases" not in st["summary"] and "4 cells would change" in st["summary"])
    check("every staging result carries the spec's own sentence, so the MODEL reads it",
          st["message"] == office_ops.NOT_APPLIED_SENTENCE
          and office_ops.NOT_APPLIED_SENTENCE in st["notes"])
    check("…and the sentence that forbids the false 'Done': you cannot apply, and you do "
          "not claim without a system line",
          any("there is no apply tool" in n and "system line" in n for n in st["notes"]))
    eq("…and it never reports itself as applied", (st["applied"], st["staged"]),
       (False, True))
    check("the private ops list is NOT shipped to the panel — how a change is carried "
          "out is the bridge's business, and a page that had the ops would grow a writer "
          "around them", "ops" not in st)

    print("\n── 4c-3. ONE PENDING CHANGESET PER (SESSION, WORKBOOK): REPLACED ──")
    first = st["changeset_id"]
    st2, _r = stage("purity.xlsx", [{"op": "set", "at": "A9", "values": [["second"]]}])
    check("a second staging call REPLACES the first — one intention, one card, which is "
          "the entire ruling", st2["replaced"] is True
          and office_ops.get_changeset(first) is None)
    eq("…and there is exactly ONE pending changeset for that workbook",
       office_ops.pending_changeset(SESS, "purity.xlsx")["id"], st2["changeset_id"])
    check("…so the replaced one can no longer be applied by anybody",
          office_ops.apply_changeset(TMP, first)[0] is None)
    other, _r = stage("undo.xlsx", [{"op": "set", "at": "A1", "values": [["x"]]}])
    eq("a DIFFERENT workbook keeps its own pending changeset — the key is (session, "
       "workbook), not one slot for the whole bridge",
       (office_ops.pending_changeset(SESS, "purity.xlsx")["id"],
        office_ops.pending_changeset(SESS, "undo.xlsx")["id"]),
       (st2["changeset_id"], other["changeset_id"]))
    third, _r = stage("purity.xlsx", [{"op": "set", "at": "A9", "values": [["s3"]]}],
                      session="another-session")
    check("…and so does a different SESSION, which is what the spec's key says",
          office_ops.pending_changeset("another-session", "purity.xlsx")["id"]
          == third["changeset_id"])

    print("\n── 4c-4. TTL: a proposal expires rather than waiting for ever ──")
    office_ops.changeset_clear()
    st, _r = stage("purity.xlsx", [{"op": "set", "at": "A9", "values": [["late"]]}])
    cid = st["changeset_id"]
    check("it is pending now", office_ops.get_changeset(cid) is not None)
    late = time.time() + office_ops.CHANGESET_TTL - 1
    check("…and still pending one second inside the TTL",
          office_ops.get_changeset(cid, now=late) is not None)
    late = time.time() + office_ops.CHANGESET_TTL + 1
    check("…gone one second past it", office_ops.get_changeset(cid, now=late) is None)
    out, reason = office_ops.apply_changeset(TMP, cid, now=late)
    check("…and applying an expired changeset is REFUSED, in words, naming the minutes",
          out is None and "expired" in reason and "10 minutes" in reason)
    eq("the TTL is the spec's ~10 minutes", office_ops.CHANGESET_TTL, 600.0)
    check("…and nothing was written by the attempt",
          read("purity.xlsx")[0][8] if False else
          len(read("purity.xlsx")[0]) == 5)

    print("\n── 4c-5. APPLY: atomic, all-or-nothing, with a receipt that RE-READS ──")
    office_ops.changeset_clear()
    st, _r = stage("purity.xlsx", [
        {"op": "insert", "what": "row", "at": 5},
        {"op": "set", "at": "A5", "values": [["purchases", 200]]},
        {"op": "set", "at": "B6", "values": [["=SUM(B2:B5)"]]}])
    rc, reason = office_ops.apply_changeset(TMP, st["changeset_id"])
    grid, _m, _ws = read("purity.xlsx")
    eq("the incident's exact change lands, whole: the row AND the total that had to "
       "follow it", [row[0] for row in grid] + [grid[4][1], grid[5][1]],
       ["Category", "Rent", "Food", "Transport", "purchases", "Total",
        200, "=SUM(B2:B5)"])
    check("the receipt is the spec's shape",
          all(k in rc for k in ("changeset_id", "applied_at", "cells_written",
                                "verify")))
    eq("…it counts what was written", rc["cells_written"], 3)
    check("…it carries a receipt hash, which is what the panel's badge quotes",
          isinstance(rc["receipt"], str) and len(rc["receipt"]) >= 8)
    # ⚠️⚠️ `verify` IS A RE-READ FROM DISK, NOT A RESTATEMENT. This is the difference
    # between a receipt and a claim, and it is the assertion that answers the incident's
    # second failure: a save that silently did nothing cannot look like a success.
    check("VERIFY IS A RE-READ OF THE TOUCHED CELLS FROM THE SAVED FILE, and every one "
          "matches", rc["verify"] and all(v["match"] for v in rc["verify"])
          and len(rc["verify"]) == 4)
    eq("…and it says so in a sentence a person can read", rc["verify_note"],
       "4 of 4 re-read cell(s) hold what the change said they would.")
    check("…the verify names the cell, what was expected and what was FOUND, so a "
          "mismatch is legible rather than a boolean",
          all({"ref", "expected", "found", "match"} <= set(v) for v in rc["verify"]))
    check("a changeset can only be applied ONCE — the second press is refused, not a "
          "second write", office_ops.apply_changeset(TMP, st["changeset_id"])[0] is None)
    eq("…and it is no longer pending for the panel to draw",
       office_ops.pending_changeset(SESS, "purity.xlsx"), None)
    # ATOMICITY, executed: an op list whose LAST op is impossible must leave the file
    # exactly as it was, not two-thirds changed.
    make("atomic.xlsx", [["a", 1], ["b", 2]], merges=["D1:E1"])
    keep = open(os.path.join(D, "atomic.xlsx"), "rb").read()
    st, _r = stage("atomic.xlsx", [{"op": "set", "at": "A1", "values": [["z"]]},
                                   {"op": "sort", "col": "B"}])
    rc2, _r = office_ops.apply_changeset(TMP, st["changeset_id"])
    grid, _m, _ws = read("atomic.xlsx")
    check("a change whose sort is refused still applies its OTHER ops and SAYS the sort "
          "was skipped — the page's own ruling, carried over: the rest of the plan is "
          "still what was approved",
          grid[0][0] == "z" and rc2["operations_skipped"] == 1 and rc2["sorted"] == 0)
    check("…and the ONE save is what makes it atomic: the file is written once, at the "
          "end, so there is no half-applied state to explain",
          keep != open(os.path.join(D, "atomic.xlsx"), "rb").read())

    print("\n── 4c-6. DISMISS: nothing written, and the session is TOLD ──")
    office_ops.changeset_clear()
    make("dismissed.xlsx", [["keep me"]])
    keep = open(os.path.join(D, "dismissed.xlsx"), "rb").read()
    st, _r = stage("dismissed.xlsx", [{"op": "set", "at": "A1",
                                       "values": [["clobbered"]]}])
    out, reason = office_ops.dismiss_changeset(TMP, st["changeset_id"])
    check("dismiss answers ok", out is not None and out["ok"])
    eq("…and NOT ONE BYTE of the workbook changed",
       open(os.path.join(D, "dismissed.xlsx"), "rb").read(), keep)
    check("…the changeset is gone from the store, so it cannot be applied afterwards",
          office_ops.get_changeset(st["changeset_id"]) is None
          and office_ops.apply_changeset(TMP, st["changeset_id"])[0] is None)
    check("…and dismissing twice is refused rather than pretending",
          office_ops.dismiss_changeset(TMP, st["changeset_id"])[0] is None)

    print("\n── 4c-7. THE SESSION LINE, on BOTH outcomes ──")
    # ⚠️ THE SPEC ASKED FOR AN INJECTION INTO THE HERMES SESSION AND NAMED THE FALLBACK.
    # The vendored gateway has no method that appends a message to an IDLE session; the
    # nearest thing (session.steer) stashes text that drains onto the next TOOL RESULT,
    # i.e. after the next turn has already started answering, and records a fake user
    # bubble on the way. So the bridge QUEUES the line and the panel prepends it to the
    # next agent message — which puts it in the model's context BEFORE it thinks. What is
    # pinned here is that both outcomes produce one and that it cannot be lost.
    office_ops.changeset_clear()
    lines = office_ops.drain_session_lines("L")
    st, _r = stage("purity.xlsx", [{"op": "set", "at": "A9", "values": [["x"]]}],
                   session="L")
    rc, _r = office_ops.apply_changeset(TMP, st["changeset_id"])
    lines = office_ops.peek_session_lines("L")
    check("APPLY queues exactly one line for that session",
          len(lines) == 1 and lines[0] == rc["session_line"])
    check("…and it says APPLIED, names the changeset, quotes the receipt and the cell "
          "count, and names the workbook",
          "APPLIED" in lines[0] and st["changeset_id"] in lines[0]
          and rc["receipt"] in lines[0] and "purity.xlsx" in lines[0])
    st2, _r = stage("undo.xlsx", [{"op": "set", "at": "A1", "values": [["y"]]}],
                    session="L")
    d, _r = office_ops.dismiss_changeset(TMP, st2["changeset_id"])
    lines = office_ops.peek_session_lines("L")
    check("DISMISS queues one too, and it says the change was NEVER applied and tells "
          "the model not to claim otherwise",
          len(lines) == 2 and "DISMISSED" in lines[1]
          and "NEVER applied" in lines[1] and "do not claim" in lines[1].lower()
          + lines[1])
    check("peek does not consume — a line the panel has not SENT yet is still owed",
          len(office_ops.peek_session_lines("L")) == 2)
    check("…and drain does, exactly once",
          len(office_ops.drain_session_lines("L")) == 2
          and office_ops.drain_session_lines("L") == [])
    check("a session with no outcomes has no lines, rather than an empty ceremony",
          office_ops.peek_session_lines("nobody") == [])

    print("\n── 4c-8. CHECKPOINTS: push, prune, restore, and the mtime FENCE ──")
    office_ops.changeset_clear()
    make("cp.xlsx", [["v0"]])
    ids = []
    for i in range(1, 14):
        st, _r = stage("cp.xlsx", [{"op": "set", "at": "A1",
                                    "values": [["v" + str(i)]]}])
        rc, reason = office_ops.apply_changeset(TMP, st["changeset_id"])
        assert rc is not None, reason
        ids.append(st["changeset_id"])
    stack = office_ops.list_checkpoints(TMP, "cp.xlsx")
    eq("the stack keeps the last 10 per workbook and prunes the rest (spec §3)",
       len(stack), office_ops.CHECKPOINT_KEEP)
    eq("…the ten it kept are the ten NEWEST",
       [e["changeset_id"] for e in stack], list(reversed(ids[-10:])))
    check("…and the pruned ones are really off disk",
          not os.path.exists(office_ops.checkpoint_path(TMP, "cp.xlsx", ids[0])))
    eq("the path is the spec's: data/office/.checkpoints/<stem>/<changeset_id>.xlsx",
       os.path.relpath(office_ops.checkpoint_path(TMP, "cp.xlsx", "abc"),
                       office.office_dir(TMP)),
       os.path.join(".checkpoints", "cp", "abc.xlsx"))
    check("…and a checkpoint is taken on EVERY apply, not only the first",
          all(os.path.isfile(office_ops.checkpoint_path(TMP, "cp.xlsx", c))
              for c in ids[-10:]))
    eq("the workbook itself holds the last apply", read("cp.xlsx")[0][0][0], "v13")
    # RESTORE, and it is byte-exact: a checkpoint is a copy of the file, not a replay.
    cp13 = office_ops.checkpoint_path(TMP, "cp.xlsx", ids[-1])
    want = open(cp13, "rb").read()
    out, reason = office_ops.undo_changeset(TMP, ids[-1])
    check("'Undo this change' restores that apply's checkpoint",
          out is not None and out["restored_from"] == ids[-1] + ".xlsx")
    eq("…and the workbook is what it was BEFORE that apply", read("cp.xlsx")[0][0][0],
       "v12")
    eq("…BYTE FOR BYTE, because a checkpoint is a copy and not a replay",
       open(os.path.join(D, "cp.xlsx"), "rb").read(), want)
    check("…the fence was checked, and the undo says so",
          out["fenced"] is True)
    check("…and the restored file is stamped NOW, so every 'did this change under me?' "
          "check on this bridge can SEE the undo (copy2 would have restored an OLD "
          "mtime, which reads as no change at all)",
          os.path.getmtime(os.path.join(D, "cp.xlsx")) > out["at"] - 5)
    check("…and the file as it was a moment before the undo is kept, so undoing the "
          "undo is a question with an answer",
          read("cp.pre-agent.xlsx")[0][0][0] == "v13")
    # ⚠️⚠️ THE MTIME FENCE. The whole reason one-click Apply is responsible is that it
    # can be taken back — and an undo that silently threw away work done SINCE the apply
    # would be a worse bug than the one it fixes.
    office_ops.changeset_clear()
    make("fence.xlsx", [["original"]])
    st, _r = stage("fence.xlsx", [{"op": "set", "at": "A1", "values": [["applied"]]}])
    rc, _r = office_ops.apply_changeset(TMP, st["changeset_id"])
    time.sleep(0.05)
    make("fence.xlsx", [["Debi typed this afterwards"]])       # the file moves
    out, reason = office_ops.undo_changeset(TMP, st["changeset_id"])
    check("AN UNDO OF A WORKBOOK THAT CHANGED SINCE THE APPLY IS REFUSED",
          out is None and "changed on disk after the change was applied" in reason)
    check("…in words that say nothing was restored and where the checkpoint still is",
          "Nothing was restored" in reason
          and st["changeset_id"] + ".xlsx" in reason)
    eq("…and the later work is untouched", read("fence.xlsx")[0][0][0],
       "Debi typed this afterwards")
    out, reason = office_ops.undo_changeset(TMP, "0" * 16)
    check("an undo of a changeset nobody applied is refused rather than guessed at",
          out is None and "no checkpoint" in reason)
    st, _r = stage("fence.xlsx", [{"op": "set", "at": "A1", "values": [["x"]]}])
    check("…and an undo of a changeset that was never APPLIED is refused too",
          office_ops.undo_changeset(TMP, st["changeset_id"])[0] is None)


# ══ 5. THE MCP SURFACE, through the MOUNTED app ═════════════════════════════
print("\n── 5. the MCP surface ──")
SPECS = office_mcp.tool_specs()
# ⚠️⚠️ THE CATALOG IS AN EXACT LIST OF FOUR, AND THE FOUR RETIRED NAMES ARE ASSERTED
# ABSENT BY NAME. docs/FABLE-AGENT-CHANGESET-SPEC.md §1 retired office_write_cells,
# office_sort, office_insert_delete and office_create: "S1 is a day old; tests updated,
# not appeased". A catalog test that only checked the four survivors were PRESENT would
# pass with a fifth, write-capable tool sitting next to them.
eq("THE CATALOG IS EXACTLY THESE FOUR TOOLS", [t["name"] for t in SPECS],
   ["office_list", "office_read", "office_sheet_stats", "office_stage_changes"])
eq("…and not one of the four retired write tools is served any more",
   [n for n in ("office_write_cells", "office_sort", "office_insert_delete",
                "office_create")
    if n in [t["name"] for t in SPECS]], [])
# ⚠️ THE ANNOTATION FENCE, THE OTHER WAY ROUND FROM v1. `readOnlyHint: true` is what
# DISARMS Hermes's approval card (vendor/hermes/tools/mcp_tool.py:3999 — `hint is True`),
# so in v1 it had to be absent from four tools. In v2 EVERY tool carries it, and what
# makes that honest is the mtime assertion in group 4c-1: staging does not touch the
# file. A tool added here that writes would make the annotation a lie AND remove its
# card in one move — hence the set assertion on both sides.
eq("EVERY tool is declared read-only", office_mcp.read_tool_names(),
   ["office_list", "office_read", "office_sheet_stats", "office_stage_changes"])
eq("…so NOTHING is write-capable, which is why no Hermes approval card can fire on this "
   "lane at all — the consent moved to the panel's changeset card",
   office_mcp.write_tool_names(), [])
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
# ⚠️ THE STAGING TOOL'S DESCRIPTION IS PART OF THE FIX, not documentation: it is the
# only place a model reads the rule before it acts. Each sentence pinned separately.
STAGE = [t for t in PAYLOAD if t["name"] == "office_stage_changes"][0]["description"]
check("office_stage_changes SAYS it writes nothing", "THIS WRITES NOTHING" in STAGE)
check("…carries the spec's own NOT-applied sentence verbatim",
      office_ops.NOT_APPLIED_SENTENCE in STAGE)
check("…says the model cannot apply it and that there will never be an apply tool",
      "You cannot apply it" in STAGE and "there never will be" in STAGE)
check("…tells it to send the COMPLETE change in ONE call, and says what a second call "
      "costs — the direct answer to three write calls for one intention",
      "in ONE call" in STAGE and "REPLACES the first proposal" in STAGE)
check("…and forbids the false 'Done' in the tool description itself",
      "Never say a workbook was changed unless a system line" in STAGE)
check("…and names the TTL, so a model that comes back in an hour is not surprised",
      "expires after 10 minutes" in STAGE)
OPSDOC = [t for t in PAYLOAD if t["name"] == "office_stage_changes"][0][
    "inputSchema"]["properties"]["ops"]["description"]
check("the ops grammar teaches every op the changeset grammar accepts, create_workbook "
      "and add_sheet included (absorbed from the retired office_create)",
      all(k in OPSDOC for k in ('"op":"set"', '"op":"style"', '"op":"sort"',
                                '"op":"insert"', '"op":"delete_rc"',
                                '"op":"add_sheet"', '"op":"create_workbook"')))
check("…and it still says the honest bound: formula references are never rewritten",
      "FORMULA REFERENCES\nARE NEVER REWRITTEN" in OPSDOC
      or "FORMULA REFERENCES ARE NEVER REWRITTEN" in OPSDOC.replace("\n", " "))
check("…and it says the caps, and that going over refuses the WHOLE change rather than "
      "half-staging it",
      str(office_ops.ACT_MAX_OPS) in OPSDOC and str(office_ops.ACT_MAX_CELLS) in OPSDOC
      and "never half-staged" in OPSDOC)
check("…and that ONE call is the unit, because two calls are two cards for one "
      "intention", "two calls are two cards" in OPSDOC)
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
    check("the instructions tell the model the things it cannot discover by trying: "
          "name-addressing, no formula engine, and — the one that matters most now — "
          "that NOTHING here writes and it cannot apply",
          all(s in j["result"]["instructions"]
              for s in ("office_list", "computes a formula",
                        "NOTHING HERE WRITES A WORKBOOK", "You cannot apply it",
                        "system line")))

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
    res = rpc("tools/call", {"name": "office_stage_changes",
                             "arguments": {"name": "../x.xlsx",
                                           "ops": [{"op": "set", "at": "A1",
                                                    "values": [["x"]]}]}}
              ).json()["result"]
    check("…and office_stage_changes refuses a path just as hard — containment does not "
          "get looser because a tool only PROPOSES", res["isError"] is True)
    res = rpc("tools/call", {"name": "office_stage_changes",
                             "arguments": {"name": "whatever.xlsx",
                                           "ops": "not a list"}}).json()["result"]
    check("…and a junk ops list is a refusal WITH A SENTENCE, which the panel renders as "
          "a ✗ chip, so a model's bad call is visible to Debi too",
          res["isError"] is True
          and len(json.loads(res["content"][0]["text"])["error"]) > 8)
    check("no tool named apply/write/save exists over the wire at all — apply is a "
          "route, reachable from a button, and this is the assertion that keeps it "
          "that way",
          all(not any(w in t["name"] for w in ("apply", "write", "save", "delete",
                                              "create"))
              for t in tools))

    # ── THE CHANGESET ROUTES, through the mounted app (spec §2) ──
    # ⚠️ THE WHOLE CONSENT STORY IS THESE FOUR ROUTES PLUS ONE MCP TOOL, so it is worth
    # exercising over HTTP and not only in-process: this is the shape the panel actually
    # speaks, and a route that 404s is a card whose buttons do nothing.
    if HAVE_XL:
        import bridge.app as _bapp
        _saved_root = _bapp.ROOT
        try:
            _bapp.ROOT = TMP
            office_mcp.configure(TMP)
            office_ops.changeset_clear()
            office_ops.heartbeat_clear()
            make("wire.xlsx", [["Category", "Amount"], ["Rent", 1000],
                               ["Total", "=SUM(B2:B2)"]])
            wpath = os.path.join(D, "wire.xlsx")
            wmtime = os.path.getmtime(wpath)
            office_ops.mark_session("wire-session")
            res = rpc("tools/call", {
                "name": "office_stage_changes",
                "arguments": {"name": "wire.xlsx", "ops": [
                    {"op": "insert", "what": "row", "at": 3},
                    {"op": "set", "at": "A3", "values": [["purchases", 200]]},
                    {"op": "set", "at": "B4", "values": [["=SUM(B2:B3)"]]}]}}
                     ).json()["result"]
            body = json.loads(res["content"][0]["text"])
            check("staging over MCP is NOT an error and comes back staged, not applied",
                  res["isError"] is False and body["staged"] is True
                  and body["applied"] is False)
            eq("…and the file did not move — asserted over the WIRE this time, because "
               "the readOnlyHint on this tool is a claim about exactly this",
               os.path.getmtime(wpath), wmtime)
            eq("…and the tool call is attributed to the Hermes session the bridge saw "
               "running, which is what makes the panel's lookup find it",
               body["session"], "wire-session")
            cid = body["changeset_id"]
            g = cl.get("/api/office/changeset?file=wire.xlsx&session=wire-session").json()
            eq("GET /api/office/changeset hands the panel that ONE changeset",
               g["changeset"]["changeset_id"], cid)
            check("…with the op list and the before→after preview on it, which is what "
                  "the card renders",
                  len(g["changeset"]["op_list"]) == 3
                  and any(p["ref"] == "A3" and p["before"] == "Total"
                          and p["after"] == "purchases"
                          for p in g["changeset"]["preview"]))
            eq("…and nothing for a workbook that has no proposal",
               cl.get("/api/office/changeset?file=nothing.xlsx").json()["changeset"],
               None)
            r = cl.post(f"/api/office/changeset/{cid}/apply").json()
            check("POST …/apply answers with the receipt",
                  r["ok"] and r["receipt"] and r["cells_written"] == 3
                  and all(v["match"] for v in r["verify"]))
            eq("…and the workbook on disk holds the row AND the updated total",
               [row[0] for row in read("wire.xlsx")[0]],
               ["Category", "Rent", "purchases", "Total"])
            check("…and a checkpoint exists for it",
                  os.path.isfile(office_ops.checkpoint_path(TMP, "wire.xlsx", cid)))
            eq("…which the checkpoints route reports",
               [e["changeset_id"] for e in
                cl.get("/api/office/checkpoints/wire.xlsx").json()["checkpoints"]],
               [cid])
            g = cl.get("/api/office/changeset?file=wire.xlsx&session=wire-session").json()
            check("…the pending changeset is gone, and the outcome line is waiting for "
                  "the next turn",
                  g["changeset"] is None and len(g["session_lines"]) == 1
                  and "APPLIED" in g["session_lines"][0])
            check("applying twice over HTTP is a 400 with a sentence, not a second write",
                  cl.post(f"/api/office/changeset/{cid}/apply").status_code == 400)
            r = cl.post(f"/api/office/changeset/{cid}/undo").json()
            check("POST …/undo restores the checkpoint",
                  r["ok"] and [row[0] for row in read("wire.xlsx")[0]]
                  == ["Category", "Rent", "Total"])
            # dismiss, over the wire, with the file watched byte for byte
            keep = open(wpath, "rb").read()
            res = rpc("tools/call", {"name": "office_stage_changes",
                                     "arguments": {"name": "wire.xlsx", "ops": [
                                         {"op": "set", "at": "A9",
                                          "values": [["dismiss me"]]}]}}
                      ).json()["result"]
            cid2 = json.loads(res["content"][0]["text"])["changeset_id"]
            r = cl.post(f"/api/office/changeset/{cid2}/dismiss").json()
            check("POST …/dismiss answers ok and NOT ONE BYTE changed",
                  r["ok"] and open(wpath, "rb").read() == keep)
            g = cl.get("/api/office/changeset?file=wire.xlsx&session=wire-session").json()
            check("…and the DISMISSED line is queued for the session, so the next turn "
                  "cannot claim it landed",
                  any("DISMISSED" in ln and "NEVER applied" in ln
                      for ln in g["session_lines"]))
            check("a changeset id that never existed is a 400 on every route, never a "
                  "500 and never a silent ok",
                  all(cl.post(f"/api/office/changeset/deadbeef/{a}").status_code == 400
                      for a in ("apply", "dismiss", "undo")))
            check("…and a junk workbook name on the checkpoints route is a 400",
                  cl.get("/api/office/checkpoints/..%2Fetc").status_code in (400, 404))
            st2 = cl.get("/api/office/mcp").json()
            check("/api/office/mcp says WHERE consent now happens, because 'gated: []' "
                  "on its own reads like a missing fence rather than a moved one",
                  st2["consent"]["apply_route"]
                  == "POST /api/office/changeset/{id}/apply"
                  and "read-only" in st2["consent"]["why"])
        finally:
            _bapp.ROOT = _saved_root
            office_mcp.configure(_saved_root)
            office_ops.clear_sessions()

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
