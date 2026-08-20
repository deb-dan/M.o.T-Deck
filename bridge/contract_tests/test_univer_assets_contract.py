"""Contract: the VENDORED Univer bundles still expose what the Office lane assumes.

Univer is not a submodule, but it IS a pin (`build.univer_pin`) whose surface we
mirror in two places that fail SILENTLY when it moves:

  * bridge/panel/office.html hard-codes the UMD global names and the facade calls.
    A renamed global is a blank tab.
  * bridge/office.py hard-codes Univer's enums (CellValueType, HorizontalAlign,
    VerticalAlign) and IStyleData key names. A RENUMBERED enum is not an error —
    it is a cell that quietly means something else, in a file the user then saves.

So this reads the actual bundles on disk, the same way the other contract tests read
the vendored source. It SKIPS cleanly when the assets have not been fetched yet
(they are gitignored; `./scripts/fetch_vendor_assets.sh` puts them there), because a
checkout without them is a normal state, not a failure.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR = ROOT / "bridge" / "panel" / "assets" / "vendor" / "univer"
PRESETS = VENDOR / "presets.umd.js"
SHEETS = VENDOR / "preset-sheets-core.umd.js"
LOCALE = VENDOR / "preset-sheets-core.en-US.js"

pytestmark = pytest.mark.skipif(
    not (PRESETS.is_file() and SHEETS.is_file() and LOCALE.is_file()),
    reason="Univer assets not fetched — run ./scripts/fetch_vendor_assets.sh")


def _read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def test_umd_globals_are_the_ones_the_page_loads():
    """office.html reaches for exactly these three globals."""
    presets, sheets, locale = _read(PRESETS), _read(SHEETS), _read(LOCALE)
    assert "e.UniverPresets=" in presets or "UniverPresets={}" in presets
    assert "UniverPresetSheetsCore={}" in sheets
    assert "UniverPresetSheetsCoreEnUS=" in locale
    page = _read(ROOT / "bridge" / "panel" / "office.html")
    for g in ("UniverPresets", "UniverPresetSheetsCore", "UniverPresetSheetsCoreEnUS"):
        assert g in page, f"the page no longer references {g}"


def test_facade_entry_points_still_exist():
    """createUniver → {univer, univerAPI}; the preset factory; the two calls the page
    makes on the facade (createUniverSheet to load, save() to read back)."""
    presets, sheets = _read(PRESETS), _read(SHEETS)
    assert "e.createUniver=" in presets, "createUniver is gone from the presets bundle"
    assert "UniverSheetsCorePreset=" in sheets
    assert "createUniverSheet(" in sheets
    assert "getActiveWorkbook()" in sheets
    # `save()` is current; `getSnapshot()` is its deprecated alias. The page tries
    # save() first and falls back — assert at least one of them survives.
    assert "save(){" in sheets or "getSnapshot(){" in sheets


def test_cell_value_type_numbers_have_not_moved():
    """bridge/office.py writes these numbers into every cell it maps."""
    presets = _read(PRESETS)
    assert re.search(r"e\[e\.STRING=1\]=.STRING.,e\[e\.NUMBER=2\]=.NUMBER.,"
                     r"e\[e\.BOOLEAN=3\]=.BOOLEAN.,e\[e\.FORCE_STRING=4\]", presets), \
        "CellValueType was renumbered — bridge/office.py's CV_* constants are now wrong"
    from bridge import office
    assert (office.CV_STRING, office.CV_NUMBER, office.CV_BOOLEAN,
            office.CV_FORCE_STRING) == (1, 2, 3, 4)


def test_alignment_enums_have_not_moved():
    presets = _read(PRESETS)
    assert re.search(r"e\[e\.UNSPECIFIED=0\]=.UNSPECIFIED.,e\[e\.LEFT=1\]=.LEFT.,"
                     r"e\[e\.CENTER=2\]=.CENTER.", presets), "HorizontalAlign moved"
    assert re.search(r"e\[e\.UNSPECIFIED=0\]=.UNSPECIFIED.,e\[e\.TOP=1\]=.TOP.,"
                     r"e\[e\.MIDDLE=2\]=.MIDDLE.", presets), "VerticalAlign moved"
    from bridge import office
    assert office.H_ALIGN["left"] == 1 and office.H_ALIGN["center"] == 2
    assert office.V_ALIGN["top"] == 1 and office.V_ALIGN["center"] == 2


def test_style_key_names_are_still_the_short_ones():
    """IStyleData is a short-key shape (bl/it/ff/fs/cl/bg/ht/n{pattern}); office.py
    emits exactly these, so a rename would silently drop every style."""
    sheets = _read(SHEETS)
    assert "n:{pattern" in sheets, "the number-format style key moved"
    for key in ("bl:", "it:", "ff:", "fs:", "cl:{rgb", "bg:{rgb", "ht:"):
        assert key in sheets, f"style key {key!r} no longer appears in the bundle"


def test_react_and_rxjs_are_still_external_peers():
    """The page loads react/react-dom/rxjs as globals BEFORE Univer. If a future
    bundle inlined them, that ordering would be dead weight; if it changed which
    global it reads, the tab would be blank."""
    sheets = _read(SHEETS)
    assert "e.React" in sheets and "e.ReactDOM" in sheets
    assert "e.rxjs" in sheets
