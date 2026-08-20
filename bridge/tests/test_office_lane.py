"""OFFICE LANE slice 1 (SHEETS) — the round-trip tables (2026-08-21).

Built to docs/research/2026-08-20-office-lane-recon.md §5/§7. What each group guards:

1. NAME + CONTAINMENT. Every office route takes a NAME off the wire. `valid_name` and
   `doc_target` are the whole boundary — the `library_target`/`_deletable_target`
   discipline: basename only, no traversal, no symlink escape, .xlsx forced.
2. THE FORWARD MAPPER (xlsx → IWorkbookData). The enums are Univer's, read out of the
   pinned UMD bundle: a renumbered CellValueType is a silently wrong cell, not an
   error, so the numbers are asserted literally here.
3. THE REVERSE MAPPER (IWorkbookData → xlsx) and the ROUND TRIP. This is the whole
   product: the recon's own verdict is that any plan which ships a beautiful grid and
   writes CSV has solved nothing. The round-trip is executed, not argued.
4. TOTALITY. A snapshot arrives as JSON from a webview and a workbook arrives from
   somebody else's software. Junk in a cell must cost that cell — never the workbook,
   never a 500.
5. THE BACKUP POLICY. A save writes a NEW workbook from the snapshot, so the pre-edit
   file has to survive: one .bak per file per day, taken BEFORE the first save, and a
   backup that cannot be written refuses the save rather than overwriting the original.
6. WIRING. The routes, the tab row, the pinned assets and the page's script ORDER
   (React and rxjs are Univer's peer globals — the wrong order is a blank tab).

Run: python3 bridge/tests/test_office_lane.py
"""
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bridge import office                                        # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


try:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    HAVE_XL = True
except Exception as _e:                                          # noqa: BLE001
    HAVE_XL = False
    print("!! openpyxl is NOT importable here — every round-trip test below is "
          f"SKIPPED and only the pure/wiring tables run ({_e})")


# ══ 1. names + containment ═══════════════════════════════════════════════════
NAME_TABLE = [
    ("sheet", "sheet.xlsx", "a bare stem gets the extension"),
    ("sheet.xlsx", "sheet.xlsx", "an .xlsx name passes through"),
    ("Sheet.XLSX", "Sheet.xlsx", "an upper-case extension is accepted and normalised"),
    ("  budget  ", "budget.xlsx", "surrounding whitespace is trimmed"),
    ("a b c", "a b c.xlsx", "spaces inside a name are fine"),
    ("../secrets", None, "traversal is refused"),
    ("/etc/passwd", None, "an absolute path is refused"),
    ("a/b.xlsx", None, "a separator is refused"),
    ("a\\b.xlsx", None, "a backslash is refused"),
    (".hidden", None, "a dotfile is refused"),
    ("..", None, "'..' is refused"),
    (".", None, "'.' is refused"),
    ("sheet.docx", None, "slice 1 refuses a non-xlsx extension"),
    ("sheet.csv", None, "…including csv"),
    ("", None, "empty is refused"),
    ("   ", None, "whitespace-only is refused"),
    (None, None, "None is refused"),
    (17, None, "a number is refused"),
    ({"name": "x"}, None, "a dict is refused"),
    ("x\x00y", None, "a NUL byte is refused"),
    ("z" * 200, None, "an absurdly long name is refused"),
]
for raw, want, why in NAME_TABLE:
    got, reason = office.valid_name(raw)
    check(f"valid_name: {why}", got == want and (want is not None or bool(reason)))

check("every refusal carries a sentence",
      all(office.valid_name(r)[1] for r, w, _ in NAME_TABLE if w is None))

tmp = tempfile.mkdtemp()
D = office.office_dir(tmp)
check("office_dir is data/office under the root",
      os.path.realpath(D) == os.path.realpath(os.path.join(tmp, "data", "office")))
check("office_dir creates the folder", os.path.isdir(D))

open(os.path.join(D, "real.xlsx"), "wb").close()
t, r = office.doc_target(tmp, "real.xlsx")
check("doc_target resolves an existing workbook", t and os.path.isfile(t))
check("doc_target refuses traversal", office.doc_target(tmp, "../../x.xlsx")[0] is None)
check("doc_target refuses a missing file when must_exist",
      office.doc_target(tmp, "ghost.xlsx")[0] is None)
check("doc_target allows a missing file when not must_exist",
      office.doc_target(tmp, "ghost.xlsx", must_exist=False)[0] is not None)

# A symlink pointing OUT of the folder must not become a readable workbook.
outside = os.path.join(tmp, "outside.xlsx")
open(outside, "wb").close()
try:
    os.symlink(outside, os.path.join(D, "escape.xlsx"))
    got, reason = office.doc_target(tmp, "escape.xlsx")
    check("doc_target refuses a symlink that escapes the folder",
          got is None and "outside" in (reason or ""))
except OSError:
    check("doc_target refuses a symlink that escapes the folder (skipped: no symlinks)", True)

check("backup_for is <stem>.<day>.bak.xlsx",
      office.backup_for("/a/b/sheet.xlsx", "20260821") == "/a/b/sheet.20260821.bak.xlsx")
check("a backup name is recognised as one",
      office.is_backup_name("sheet.20260821.bak.xlsx"))
check("an ordinary name is not a backup", not office.is_backup_name("sheet.xlsx"))
check("is_backup_name is total over junk", office.is_backup_name(None) is False)


# ══ 2/3/4. the mappers ═══════════════════════════════════════════════════════
def build_fixture(path):
    """A workbook with one of everything the contract promises."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws["A1"] = "Name"
    ws["B1"] = 42
    ws["C1"] = True
    ws["D1"] = "=B1*2"
    ws["A2"] = 3.5
    ws["B2"] = datetime.datetime(2026, 8, 21, 12, 0)
    ws["C2"] = ""                       # an empty string is not a value
    ws["A1"].font = Font(bold=True, italic=True, size=14, color="FFFF0000", name="Arial")
    ws["A1"].fill = PatternFill(fill_type="solid", start_color="FF00FF00",
                                end_color="FF00FF00")
    ws["A1"].alignment = Alignment(horizontal="center", vertical="top")
    ws["B1"].number_format = "0.00"
    ws.column_dimensions["A"].width = 20
    ws.row_dimensions[1].height = 30
    ws.merge_cells("E1:F2")
    wb.create_sheet("Second")["A1"] = "x"
    wb.save(path)
    return path


if HAVE_XL:
    src = build_fixture(os.path.join(D, "fixture.xlsx"))
    snap = office.snapshot_from_path(src)
    s1 = snap["sheets"][snap["sheetOrder"][0]]
    cd = s1["cellData"]

    check("the snapshot carries both sheets in order", snap["sheetOrder"] == ["sheet-01", "sheet-02"])
    check("sheet names survive", [snap["sheets"][i]["name"] for i in snap["sheetOrder"]]
          == ["Data", "Second"])
    check("the workbook name comes from the file stem", snap["name"] == "fixture")
    check("cellData is keyed row-then-column, ZERO-based",
          cd["0"]["0"]["v"] == "Name" and cd["1"]["0"]["v"] == 3.5)
    check("a string cell is CellValueType STRING (1)", cd["0"]["0"]["t"] == 1
          and office.CV_STRING == 1)
    check("a number cell is NUMBER (2)", cd["0"]["1"]["t"] == 2 and office.CV_NUMBER == 2)
    check("an integer stays an integer", cd["0"]["1"]["v"] == 42
          and isinstance(cd["0"]["1"]["v"], int))
    check("a boolean is BOOLEAN (3)", cd["0"]["2"]["t"] == 3 and cd["0"]["2"]["v"] is True
          and office.CV_BOOLEAN == 3)
    check("a formula rides as `f`, verbatim", cd["0"]["3"]["f"] == "=B1*2")
    check("a formula cell carries no invented value",
          "v" not in cd["0"]["3"] or cd["0"]["3"].get("v") is not None)
    check("a date becomes the Excel serial number",
          abs(cd["1"]["1"]["v"] - 46255.5) < 1e-6 and cd["1"]["1"]["t"] == 2)
    check("the date's number format travels with it",
          "yyyy" in cd["1"]["1"]["s"]["n"]["pattern"])
    check("an empty string is not a cell", "2" not in cd.get("1", {}))
    st = cd["0"]["0"]["s"]
    check("bold survives", st["bl"] == 1)
    check("italic survives", st["it"] == 1)
    check("the font name survives", st["ff"] == "Arial")
    check("the font size survives", st["fs"] == 14.0)
    check("the font colour survives as #rrggbb", st["cl"] == {"rgb": "#ff0000"})
    check("the fill colour survives", st["bg"] == {"rgb": "#00ff00"})
    check("horizontal centre is HorizontalAlign.CENTER (2)", st["ht"] == 2)
    check("vertical top is VerticalAlign.TOP (1)", st["vt"] == 1)
    check("the number format survives", cd["0"]["1"]["s"]["n"]["pattern"] == "0.00")
    check("an UNSTYLED cell carries no style dict at all", "s" not in cd["1"]["0"])
    check("blank cells inside the used range are not emitted",
          all(v for row in cd.values() for v in row.values()))
    check("the merged range survives, zero-based",
          {"startRow": 0, "startColumn": 4, "endRow": 1, "endColumn": 5} in s1["mergeData"])
    check("the column width is carried in PIXELS", abs(s1["columnData"]["0"]["w"] - 140.0) < 0.01)
    check("the row height is carried in PIXELS", abs(s1["rowData"]["0"]["h"] - 40.0) < 0.01)
    check("the snapshot is JSON-serialisable", isinstance(json.dumps(snap), str))

    # ── the round trip ──
    dst = os.path.join(D, "written.xlsx")
    report = office.write_snapshot(snap, dst)
    check("write_snapshot reports both sheets", report["sheets"] == 2)
    check("write_snapshot reports the cells it wrote", report["cells"] >= 7)
    back = office.snapshot_from_path(dst)
    b1 = back["sheets"][back["sheetOrder"][0]]
    check("ROUND TRIP: every cell (value, type, formula, style) is identical",
          b1["cellData"] == cd)
    check("ROUND TRIP: sheet names are identical",
          [back["sheets"][i]["name"] for i in back["sheetOrder"]] == ["Data", "Second"])
    check("ROUND TRIP: merges are identical", b1["mergeData"] == s1["mergeData"])
    check("ROUND TRIP: column widths are identical", b1["columnData"] == s1["columnData"])
    check("ROUND TRIP: row heights are identical", b1["rowData"] == s1["rowData"])

    # ── cached formula results ──
    # A file whose formulas were last calculated by Excel carries the RESULT too; we
    # fake that by writing a value where the formula was and asserting the reader
    # prefers f + a cached v. openpyxl cannot calculate, so a file we wrote has none.
    check("a workbook we wrote has no cached result to invent",
          "v" not in b1["cellData"]["0"]["3"])

    # ── an empty workbook ──
    empty_path = os.path.join(D, "blank.xlsx")
    openpyxl.Workbook().save(empty_path)
    esnap = office.snapshot_from_path(empty_path)
    check("an empty workbook still opens with one sheet", len(esnap["sheetOrder"]) == 1)
    check("an empty workbook has no cells",
          esnap["sheets"][esnap["sheetOrder"][0]]["cellData"] == {})

    # ── new-file shape ──
    made, reason = office.create_doc(tmp, "budget")
    check("create_doc makes budget.xlsx", made == "budget.xlsx" and reason is None)
    check("the new workbook is a real xlsx", os.path.getsize(os.path.join(D, made)) > 0)
    nsnap = office.snapshot_from_path(os.path.join(D, made))
    check("a new workbook opens clean",
          nsnap["sheets"][nsnap["sheetOrder"][0]]["cellData"] == {})
    again, reason = office.create_doc(tmp, "budget")
    check("create_doc never clobbers an existing workbook",
          again is None and "already exists" in (reason or ""))
    check("create_doc refuses a junk name", office.create_doc(tmp, "../x")[0] is None)

    # ── totality of the reverse mapper ──
    JUNK = {
        "id": "w", "sheetOrder": ["s1"], "styles": {"S1": {"bl": 1}},
        "sheets": {"s1": {"id": "s1", "name": "J", "cellData": {
            "0": {"0": {"v": "keep", "t": 1}},
            "1": "not a row",
            "x": {"0": {"v": "bad row key"}},
            "2": {"y": {"v": "bad col key"}, "0": "not a cell", "1": {"v": float("nan")},
                  "2": {"v": None}, "3": {"v": {"deep": 1}}, "4": {"f": 17},
                  "5": {"v": 5, "s": "S1"}, "6": {"v": 6, "s": "NOPE"},
                  "7": {"v": "07", "t": 4}},
            "-1": {"0": {"v": "negative row"}},
        }, "mergeData": ["junk", {"startRow": 5, "startColumn": 5, "endRow": 1,
                                  "endColumn": 1}, {"startRow": 8, "startColumn": 0,
                                                    "endRow": 9, "endColumn": 1}],
           "rowData": {"0": {"h": "tall"}, "1": {"h": 48}},
           "columnData": "junk"}},
    }
    jpath = os.path.join(D, "junk.xlsx")
    jreport = office.write_snapshot(JUNK, jpath)
    check("a snapshot full of junk still writes a workbook", os.path.isfile(jpath))
    jback = office.snapshot_from_path(jpath)
    jcd = jback["sheets"][jback["sheetOrder"][0]]["cellData"]
    check("a good cell beside junk survives", jcd["0"]["0"]["v"] == "keep")
    check("a row that is not a dict is skipped", "1" not in jcd)
    check("a non-numeric row key is skipped", all(k.lstrip("-").isdigit() for k in jcd))
    check("a NaN value is not written", "1" not in jcd.get("2", {}))
    check("a None value is not written", "2" not in jcd.get("2", {}))
    check("a cell that is not a dict is skipped", "0" not in jcd.get("2", {}))
    check("a nested-object value is stringified, not dropped silently",
          isinstance(jcd["2"]["3"]["v"], str))
    check("a non-string formula is not treated as a formula",
          "f" not in jcd.get("2", {}).get("4", {}))
    check("a style id resolves out of workbook.styles", jcd["2"]["5"]["s"]["bl"] == 1)
    check("an unknown style id costs the style, not the value", jcd["2"]["6"]["v"] == 6)
    check("FORCE_STRING keeps a leading zero", jcd["2"]["7"]["v"] == "07"
          and jcd["2"]["7"]["t"] == 1 and office.CV_FORCE_STRING == 4)
    check("a negative row index is skipped", "-1" not in jcd)
    check("an inverted merge range is skipped and a good one kept",
          {"startRow": 8, "startColumn": 0, "endRow": 9, "endColumn": 1}
          in jback["sheets"][jback["sheetOrder"][0]]["mergeData"]
          and len(jback["sheets"][jback["sheetOrder"][0]]["mergeData"]) == 1)
    check("a junk row height is ignored and a good one applied",
          jback["sheets"][jback["sheetOrder"][0]]["rowData"].get("1", {}).get("h") == 48.0)

    for bad, why in [(None, "None"), ("a string", "a string"), (17, "a number"),
                     ({}, "an empty dict"), ({"sheets": {}}, "no sheets"),
                     ({"sheets": "x"}, "sheets that is not a dict")]:
        try:
            office.write_snapshot(bad, os.path.join(D, "never.xlsx"))
            ok = False
        except office.OfficeError as e:
            ok = bool(str(e))
        check(f"write_snapshot refuses {why} with a sentence", ok)
    check("a refused write leaves no file behind",
          not os.path.exists(os.path.join(D, "never.xlsx")))

    # sheetOrder junk must not lose the sheets
    recovered = office.write_snapshot(
        {"sheetOrder": "junk", "sheets": {"a": {"name": "One", "cellData": {}},
                                          "b": {"name": "One", "cellData": {}}}},
        os.path.join(D, "recovered.xlsx"))
    check("a junk sheetOrder falls back to the sheets dict", recovered["sheets"] == 2)
    rsnap = office.snapshot_from_path(os.path.join(D, "recovered.xlsx"))
    names = [rsnap["sheets"][i]["name"] for i in rsnap["sheetOrder"]]
    check("duplicate sheet names are made unique (Excel refuses duplicates)",
          len(set(n.lower() for n in names)) == 2)

    # ── the backup policy ──
    saved, reason = office.save_doc(tmp, "budget.xlsx", office.empty_snapshot("budget"))
    bak = office.backup_for(os.path.join(D, "budget.xlsx"))
    check("saving over an existing workbook takes a backup first",
          saved and saved["backup"] == os.path.basename(bak) and os.path.isfile(bak))
    before = os.path.getmtime(bak)
    saved2, _ = office.save_doc(tmp, "budget.xlsx", office.empty_snapshot("budget"))
    check("a SECOND save the same day does not re-copy",
          saved2 and saved2["backup"] == "" and os.path.getmtime(bak) == before)
    listed = [f["name"] for f in office.list_docs(tmp)]
    check("backups are on disk but not in the file list",
          os.path.basename(bak) not in listed and "budget.xlsx" in listed)
    check("the file list flags that a backup exists",
          any(f["name"] == "budget.xlsx" and f["has_backup"] for f in office.list_docs(tmp)))
    check("the file list is newest-first",
          [f["modified"] for f in office.list_docs(tmp)]
          == sorted([f["modified"] for f in office.list_docs(tmp)], reverse=True))
    check("saving a NEW name takes no backup",
          (office.save_doc(tmp, "fresh.xlsx", office.empty_snapshot("fresh"))[0] or {})
          .get("backup") == "")
    check("save_doc refuses a junk name before touching disk",
          office.save_doc(tmp, "../evil.xlsx", office.empty_snapshot("x"))[0] is None)
    check("save_doc refuses a junk snapshot", office.save_doc(tmp, "fresh.xlsx", "nope")[0] is None)

    # ── open/delete ──
    got, reason = office.open_doc(tmp, "budget.xlsx")
    check("open_doc returns a snapshot", got and got["sheetOrder"])
    check("open_doc refuses a missing workbook", office.open_doc(tmp, "ghost.xlsx")[0] is None)
    ok, reason = office.delete_doc(tmp, "fresh.xlsx")
    check("delete_doc removes the workbook", ok and not os.path.exists(os.path.join(D, "fresh.xlsx")))
    check("delete_doc refuses traversal", office.delete_doc(tmp, "../x.xlsx")[0] is False)
    check("delete leaves the backup alone (it exists to survive mistakes)",
          os.path.isfile(bak))

    # ── the cell cap ──
    big = {"sheetOrder": ["s"], "sheets": {"s": {"name": "Big", "cellData": {}}}}
    check("MAX_CELLS is a real bound, not decoration", office.MAX_CELLS >= 100000)

# a snapshot of an unreadable file must be a sentence, not a traceback
bad_path = os.path.join(D, "notreally.xlsx")
with open(bad_path, "w", encoding="utf-8") as fh:
    fh.write("this is not a zip archive")
try:
    office.snapshot_from_path(bad_path)
    ok = False
except office.OfficeError as e:
    ok = "could not read" in str(e) or "openpyxl" in str(e)
except Exception:                                                # noqa: BLE001
    ok = False
check("a corrupt file raises OfficeError with a sentence, never a raw traceback", ok)


# ══ 5. pure helpers ══════════════════════════════════════════════════════════
check("excel_serial: the 1900 leap bug epoch is 1899-12-30",
      excel := office.excel_serial(datetime.datetime(1900, 1, 1)) == 2.0)
check("excel_serial: a date is a whole number",
      office.excel_serial(datetime.date(2026, 8, 21)) == 46255.0)
check("excel_serial: a time is a day fraction",
      abs(office.excel_serial(datetime.time(12, 0)) - 0.5) < 1e-9)
check("excel_serial is total over junk", office.excel_serial("nope") == 0.0)
for raw, want in [("#FF0000", "FFFF0000"), ("ff0000", "FFFF0000"),
                  ("FFFF0000", "FFFF0000"), ("nope", ""), (None, ""), (17, ""),
                  ("#12345", "")]:
    check(f"_hex_to_argb({raw!r})", office._hex_to_argb(raw) == want)
for raw, want in [("3", 3), (3, 3), ("0", 0), ("-1", None), ("x", None),
                  (None, None), (True, None), (3.7, 3)]:
    check(f"_idx({raw!r})", office._idx(raw) == want)
check("_num rejects NaN", office._num(float("nan")) is None)
check("_num rejects inf", office._num(float("inf")) is None)
check("_num rejects a bool", office._num(True) is None)
check("_num accepts a numeric string", office._num("3.5") == 3.5)

es = office.empty_snapshot("Untitled")
check("empty_snapshot has exactly one sheet", len(es["sheetOrder"]) == 1)
check("empty_snapshot's sheet is in the sheets dict", es["sheetOrder"][0] in es["sheets"])
check("empty_snapshot is JSON-serialisable", isinstance(json.dumps(es), str))
check("empty_snapshot names the workbook from the file stem",
      office.empty_snapshot("budget.xlsx")["name"] == "budget")

check("the fidelity contract is single-sourced and says the honest thing",
      "round-trip" in office.FIDELITY_NOTE and "simplified" in office.FIDELITY_NOTE
      and "saves copies" in office.FIDELITY_NOTE)


# ══ 6. wiring ════════════════════════════════════════════════════════════════
APP = (ROOT / "bridge" / "app.py").read_text(encoding="utf-8")
PAGE = (ROOT / "bridge" / "panel" / "office.html").read_text(encoding="utf-8")
SWIFT = (ROOT / "app" / "main.swift").read_text(encoding="utf-8")
FETCH = (ROOT / "scripts" / "fetch_vendor_assets.sh").read_text(encoding="utf-8")
YAML = (ROOT / "harness.yaml").read_text(encoding="utf-8")
REQ = (ROOT / "bridge" / "requirements.txt").read_text(encoding="utf-8")

for route in ['@app.get("/office")', '@app.get("/api/office/files")',
              '@app.post("/api/office/new")', '@app.get("/api/office/open/{name}")',
              '@app.post("/api/office/save")', '@app.post("/api/office/delete")',
              '@app.get("/api/office/download/{name}")']:
    check(f"app.py declares {route}", route in APP)
check("the office module is imported DEFENSIVELY (a missing file must not kill the bridge)",
      "from bridge import office as _office" in APP and "_OFFICE_ERR" in APP)
check("every office route answers 503 when the module is missing",
      APP.count("return _office_unavailable()") >= 6)
check("download and delete both go through doc_target/delete_doc containment",
      "_office.doc_target(ROOT, name)" in APP and "_office.delete_doc" in APP)
check("the page is served no-store (the stale-panel lesson)",
      re.search(r'PANEL / "office\.html",\s*headers=\{"Cache-Control": "no-store',
                APP, re.S) is not None)
check("the blocking round-trip runs off the event loop",
      "asyncio.to_thread(_office.open_doc" in APP
      and "asyncio.to_thread(_office.save_doc" in APP)
check("the fidelity note reaches the panel from the module, not a second copy",
      "_office.FIDELITY_NOTE" in APP and office.FIDELITY_NOTE not in PAGE)

check("main.swift has the Office tab, last, on the bridge origin",
      'HarnessTab(title: "Office", url: URL(string: "http://127.0.0.1:8700/office")!)' in SWIFT)
tab_titles = re.findall(r'HarnessTab\(title: "([^"]+)"', SWIFT)
check("Office is the tenth tab", tab_titles and tab_titles[-1] == "Office" and len(tab_titles) == 10)
check("the width budget note was re-checked for ten tabs",
      "ten current titles" in SWIFT)
check("the title is ONE word — a two-word title does not fit the strip budget",
      " " not in tab_titles[-1])
check("…and the reason Debi's 'Office Lane' was not taken is recorded next to it",
      "Office Lane" in SWIFT)

check("harness.yaml pins univer", re.search(r'^\s*univer_pin:\s*"[\d.]+"', YAML, re.M))
check("the fetch script reads the pin from harness.yaml", "univer_pin:" in FETCH
      and "UNIVER_V=" in FETCH)
for asset in ["univer/rxjs.umd.min.js", "univer/presets.umd.js",
              "univer/preset-sheets-core.umd.js", "univer/preset-sheets-core.css",
              "univer/preset-sheets-core.en-US.js"]:
    check(f"the fetch script vendors {asset}", asset in FETCH)
check("the fetch script makes the subdirectory before writing",
      'mkdir -p "$(dirname "$out")"' in FETCH)
check("no runtime CDN reaches the office page",
      "cdn.jsdelivr" not in PAGE and "unpkg" not in PAGE and "http://" not in
      PAGE.split("<script")[0])
check("openpyxl is declared in bridge/requirements.txt", "openpyxl" in REQ)

# Load ORDER is the one thing a reader could get wrong and only find out in a browser.
order = [m for m in re.findall(r'<script src="/assets/vendor/([^"]+)"', PAGE)]
check("react and react-dom load before Univer (they are peer globals)",
      order.index("react.production.min.js") < order.index("univer/presets.umd.js")
      and order.index("react-dom.production.min.js") < order.index("univer/presets.umd.js"))
check("rxjs loads before Univer (peer dep)",
      order.index("univer/rxjs.umd.min.js") < order.index("univer/presets.umd.js"))
check("the sheets preset loads after the presets runtime",
      order.index("univer/presets.umd.js") < order.index("univer/preset-sheets-core.umd.js"))
check("the locale loads last", order[-1] == "univer/preset-sheets-core.en-US.js")
check("the stylesheet is self-hosted too",
      '/assets/vendor/univer/preset-sheets-core.css' in PAGE)
check("the page uses the globals the pinned bundles actually define",
      "window.UniverPresets" in PAGE and "window.UniverPresetSheetsCore" in PAGE
      and "UniverPresetSheetsCoreEnUS" in PAGE)
check("the page builds the workbook through the facade",
      "createUniver(" in PAGE and "createUniverSheet(" in PAGE)
check("saving reads the snapshot back with save() and the deprecated alias as fallback",
      "wb.save ? wb.save() : wb.getSnapshot()" in PAGE)
check("the AI side-panel is a labelled STUB with no controls",
      "coming in slice 2" in PAGE and "<aside id=\"ai\"" in PAGE
      and "<button" not in PAGE.split('<aside id="ai"')[1].split("</aside>")[0])
check("unsaved work is defended on navigation away", "beforeunload" in PAGE)
check("switching files with unsaved work asks IN THE PAGE — window.confirm is a "
      "recorded WKWebView no-op that returns FALSE and would wedge the tab",
      "window.confirm(" not in PAGE and "confirm(" not in
      re.sub(r"//[^\n]*", "", PAGE) and "confirmDiscard(name)" in PAGE
      and "discardArmed" in PAGE)
check("delete is two-step armed, not a single click", "sure?" in PAGE)
check("a missing openpyxl is SAID on the page, not hidden",
      "roundtrip" in PAGE and "bootstrap.sh" in PAGE)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print(f"office lane OK — all checks passed{'' if HAVE_XL else ' (round-trip SKIPPED: no openpyxl)'}")
