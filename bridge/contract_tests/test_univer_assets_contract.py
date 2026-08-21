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


def test_the_modules_the_page_reads_locale_and_theme_from():
    """⚠️ THE TRAP THIS PINS: `UniverPresets` re-exports ONLY the core FACADE plus
    createUniver — it has NO LocaleType and NO defaultTheme. Slice 1 read both off it
    and got `undefined` twice; it survived by luck (LocaleType.EN_US is the string
    'enUS' the fallback already used, and ThemeService seeds itself with defaultTheme),
    which is exactly the kind of luck that stops working at a pin bump.

    So the page now reads UniverCore.LocaleType and UniverThemes.defaultTheme, and
    this asserts BOTH that those globals exist and that UniverPresets still does not
    carry them — if a future bundle re-exports them, this test says so rather than
    leaving two ways to spell it.
    """
    presets = _read(PRESETS)
    assert "e.UniverThemes=" in presets, "the themes global is gone"
    assert "defaultTheme" in presets
    assert "e.UniverCore=" in presets, "the core global is gone"
    assert re.search(r"EN_US=`enUS`|EN_US:`enUS`|EN_US=\"enUS\"", presets) \
        or "`enUS`" in presets, "LocaleType.EN_US no longer spells enUS"
    page = _read(ROOT / "bridge" / "panel" / "office.html")
    assert "window.UniverCore.LocaleType" in page
    assert "window.UniverThemes.defaultTheme" in page


def test_the_bundled_peer_globals_the_self_check_names():
    """The page's self-check lists globals by name. Every one has to be a global the
    pinned bundles genuinely define, or the check invents a failure and hides the tab
    behind a banner that is itself wrong."""
    presets, sheets = _read(PRESETS), _read(SHEETS)
    # redi is bundled INSIDE presets.umd.js under bracket globals — not a separate file.
    assert 'global["@wendellhu/redi"] = {}' in presets
    assert 'global["@wendellhu/redi/react-bindings"] = {}' in presets
    # rxjs is consumed as TWO globals: the root and the operators namespace. The 7.x
    # `rxjs.umd.min.js` bundle carries both; the plain ESM build would not.
    assert "e.rxjs.operators" in presets and "e.rxjs.operators" in sheets
    rxjs = _read(VENDOR / "rxjs.umd.min.js")
    assert "g.operators=" in rxjs, "the vendored rxjs bundle no longer exposes .operators"


def test_the_preset_still_takes_the_full_ui_by_these_option_names():
    """The familiar spreadsheet chrome IS the preset's — the page asks for each part by
    name so a changed plugin default cannot quietly remove the toolbar."""
    sheets = _read(SHEETS)
    m = re.search(r"function p\(F=\{\}\)\{[^}]*const\{([^}]*)\}=F", sheets)
    assert m, "the preset factory's option destructuring moved"
    opts = m.group(1)
    for name in ("container", "header", "footer", "toolbar", "formulaBar", "contextMenu"):
        assert name in opts, f"the preset no longer takes a {name!r} option"


def test_the_stylesheet_is_still_the_one_the_page_asks_for():
    """The css is still a real, non-trivial stylesheet at the path the page injects.

    ⚠️ CHANGED HONESTLY AT 2026-08-21e. This used to pin `.univer-absolute`, which the
    page measured on a probe element to prove the stylesheet had arrived (a 404 leaves
    the <link> tag in place, so presence proved nothing). That probe is GONE, and its
    absence is the point: the stylesheet is no longer in <head> and no longer
    load-bearing. LOffice is two tiers now — a plain-DOM grid that needs no third-party
    asset at all, and Univer as an opt-in upgrade — so this css styles only the
    optional tier-2 chrome. It is fetched on demand, deliberately NOT awaited, and its
    outcome is beaconed either way. A missing stylesheet costs some styling on an
    upgrade nobody has to take; it can no longer cost the spreadsheet.

    What still has to be true is that the file the page names exists and is real.
    """
    css = _read(VENDOR / "preset-sheets-core.css")
    assert len(css) > 10000, "the sheets stylesheet is suspiciously small"
    assert ".univer" in css, "this does not look like the Univer stylesheet"
    page = _read(ROOT / "bridge" / "panel" / "office.html")
    assert "/assets/vendor/univer/preset-sheets-core.css" in page, \
        "the page no longer names the stylesheet this contract pins"
    assert "VENDOR_CSS" in page and "cssAsked" in page, \
        "the on-demand stylesheet injection moved — re-read loadVendor()"


def test_react_and_rxjs_are_still_external_peers():
    """The page loads react/react-dom/rxjs as globals BEFORE Univer. If a future
    bundle inlined them, that ordering would be dead weight; if it changed which
    global it reads, the tab would be blank."""
    sheets = _read(SHEETS)
    assert "e.React" in sheets and "e.ReactDOM" in sheets
    assert "e.rxjs" in sheets
