# The office menu bar — what Google actually ships, and what LOffice can honestly do

Date: 2026-08-21 · Source: Debi's own screenshots of **Google Sheets**, **Google Docs**, **Google Slides**
and the Sheets home screen, transcribed here item-by-item because the screenshots live in a chat
transcript and this file is how the next builder sees them. Cross-checked against `bridge/office.py`
(the round-trip we own), `bridge/panel/office.html` (tier 1) and the vendored Univer 0.25.1 preset
bundle (tier 2).

**Read `2026-08-21-office-alternatives-deep.md` first.** Its verdict stands and bounds this document:
Univer's own import/export is `Proprietary` + Docker-only, so **every fidelity claim below is about
OUR openpyxl mapper**, and Docs/Slides do not arrive until the ONLYOFFICE-static-bundle measurement
is taken. **This document is about the SHEETS menu bar only.** Nothing in it was executed.

---

## 0. The complaint, stated exactly

> "The design of the new/file etc is so bad. It's not even on the main strip as all office/sheet docs
> have it. Did you even care to do research as per google sheets/doc/presentation? See how extensive
> it is, how everything is in the white strip and uniform."

Three separate claims, all correct:

1. **Location.** Every office app puts its commands in a **menu strip under the document title**.
   LOffice had a single `File ⌄` popup button floating in dark app chrome, with four more actions
   (`Rich editor`, `Import`, `New`, `Save`) scattered beside it and two more (`download`, `delete`)
   hidden on file-row hover. Six places, no strip.
2. **Colour.** The strip is **white** — visually continuous with the sheet, not with the app frame.
   Ours was `--bg2` #0e0c15.
3. **Uniformity.** One label height, one dropdown rhythm, one shortcut column, thin group separators.
   Ours mixed a 16px serif wordmark, 10px mono pills and 12px sans buttons.

The word "extensive" is the one that matters most: Google Sheets' bar carries **ten menus and roughly
120 items**. The credibility of a menu bar is breadth. An item that cannot work is *greyed*, never
*absent* — which is how Google keeps breadth without lying.

---

## 1. Google Sheets — the full bar, transcribed

Bar: **File · Edit · View · Insert · Format · Data · Tools · Gemini · Extensions · Help**

| Menu | Items (⌘ shortcuts as shown, `▸` = submenu) |
|---|---|
| **File** | New ▸ / Open ⌘O / Import / Make a copy · Share ▸ / Email ▸ / Download ▸ · Rename / Move to trash · Version history ▸ / Make available offline · Details / Security limitations / Settings · Print ⌘P |
| **Edit** | Undo ⌘Z / Redo ⌘Y · Cut ⌘X / Copy ⌘C / Paste ⌘V / Paste special ▸ · Move ▸ / Delete ▸ · Find and replace ⌘⇧H |
| **View** | Show ▸ / Freeze ▸ / Group ▸ / Comments ▸ · Hidden sheets ▸ · Zoom ▸ / Full screen |
| **Insert** | Cells ▸ / Rows ▸ / Columns ▸ / Sheet ⇧F11 · Generate a table / Pre-built tables · Create a canvas / Chart / Pivot table / Image ▸ / Drawing · Function ▸ / Link ⌘K · Checkbox / Dropdown / Emoji / Smart chips ▸ · Comment / Note |
| **Format** | Theme · Number ▸ / Text ▸ / Alignment ▸ / Wrapping ▸ / Rotation ▸ / Smart chips ▸ · Font size ▸ / Merge cells ▸ · Convert to table / Conditional formatting / Alternating colors · Clear formatting ⌘\ |
| **Data** | Analyze data / Solve an optimization problem · Sort sheet ▸ / Sort range ▸ · Create a filter / Create group by view ▸ / Create filter view / Add a slicer · Protect sheets and ranges / Named ranges / Named functions / Randomize range · Column stats / Data validation / Data cleanup ▸ / Split text to columns / Data extraction · Data connectors ▸ |
| **Tools, Gemini, Extensions, Help** | not transcribed in detail; **Gemini is a first-class MENU**, which is the precedent for our AI menu |

### The visual grammar (this is the part to copy, not the item list)

- **Two rows.** Row 1 = logo (left, spanning both rows) + document title + status; row 2 = the menu
  labels. The save state ("All changes saved in Drive") sits **to the right of the menu bar, on the
  menu row** — not next to the title. Our `#p-file`/`#p-state` go exactly there.
- **White, flush with the sheet.** No card, no shadow, no border on the strip itself.
- **Text labels, mixed case, sans, ~13-14px**, generous horizontal padding, no borders until hover.
- **Click to open, then HOVER to switch** between menus. Escape closes. Arrow keys walk.
- **Dropdown**: white card, soft shadow, ~1px hairline, rows ~30px, label left, **shortcut
  right-aligned in a dimmer colour**, `▸` for submenus, thin separators between GROUPS (Google groups
  3-5 items and separates; it never lists 14 items flat).
- **Greyed, not hidden**, when inapplicable. Docs/Slides additionally show a small leading icon per
  row; Sheets mostly does not. A "New" badge marks new features.
- **No native `<select>` and no OS menu** — it is all in-page DOM, which is what makes it copyable.

## 2. Google Docs — the deltas worth knowing

Bar: **File · Edit · View · Insert · Format · Tools · Gemini · Extensions · Help**

- **Insert**: Image / Table / Building blocks / Smart chips / Audio buttons / Link ⌘K / Drawing /
  Chart / Symbols · Tab ⇧F11 / Horizontal line / Break / Bookmark / Page elements · Comment
- **Format**: Text ▸ / Paragraph styles ▸ / Align & indent ▸ / Line & paragraph spacing ▸ /
  Columns ▸ / Bullets & numbering ▸ · Headers & footers / Page numbers / Page orientation / Switch
  to Pageless · Table ▸ / Image ▸ / Borders & lines ▸ · Clear formatting ⌘\
- **Tools**: Proofread ▸ / Word count ⌘⇧C / Review suggested edits / Compare documents / Citations /
  Line numbers / Linked objects / Dictionary ⌘⇧Y · Translate document / Voice typing ⌘⇧S / Audio ▸ /
  Gemini · Notification settings / Preferences / Accessibility
- **Gemini menu**: Create a new doc / Add new text / Refine selected text / Listen to this tab /
  Listen to document summary / Show Gemini bottom bar / Ask something else
- Chrome around it: a left **document-tabs / outline** pane and a ruler.

**The transferable lesson:** the AI surface is a MENU, and its items are *verbs on the document*
("refine selected text"), not "open a chat". Our AI menu follows that shape as far as an
advisory-only panel honestly can.

## 3. Google Slides — the deltas

Bar: **File · Edit · View · Insert · Format · Slide · Arrange · Tools · Extensions · Help** —
i.e. **the bar grows a menu per document TYPE** (`Slide`, `Arrange`). Chrome: a toolbar with
Background / Layout / Theme / Transition, a left filmstrip, a right rail (Slide / Image / Templates /
Blocks / Media / Uploads / Record), speaker notes along the bottom.

**Lesson for us:** when LOffice grows documents or slides, the strip gains a menu — the eight we ship
now are not a fixed set.

## 4. The Sheets HOME screen (`docs.google.com/spreadsheets`)

- A **"Start a new spreadsheet"** band: a **Blank** card first, then template cards (thumbnail +
  name), with a "Template gallery" affordance.
- Then a **file list** with columns (name, owner, last opened) and grid/list, sort and folder-picker
  controls.
- **It does not auto-create a document.** The Blank card is one click away, and that is the whole
  answer to "don't land on a dead end" — a start screen is not an empty state.

This is what LOffice's `#empty` becomes.

---

## 5. Menu item → implementation, item by item

Legend for the **How** column:
`T1` = our own tier-1 JavaScript · `BR` = an existing `bridge/office.py` route ·
`UV` = would need a Univer Facade command · `—` = **shipped DISABLED**, with the reason in its
`title` (the reason column IS the tooltip text, near-verbatim).

### File

| Item | How | Note |
|---|---|---|
| New spreadsheet | BR `POST /api/office/new` | opens the rail's name row; a blank name = the bridge's `Untitled` |
| Open… ⌘O | T1 | shows the file rail (the rail *is* the open dialog) |
| Import… | BR `POST /api/office/upload` | needs the shell's `runOpenPanelWith` |
| **Make a copy** | — | *"there is no copy route on the bridge yet — Download gives you a byte-exact copy of the saved file"*. ⚠️ deliberately NOT composed from `new`+`save`: that would round-trip through our mapper and silently drop what §6 lists |
| Rename… | BR `POST /api/office/rename` | inline row, never `window.prompt` |
| Save ⌘S | BR `POST /api/office/save` | |
| Download | BR `GET /api/office/download/{name}` | byte-exact, the saved file |
| Delete… | BR `POST /api/office/delete` | two-step through `say()`'s inline action |
| Close file | T1 | |
| ⌂ LOffice home | T1 | closes the document → the start screen. **This is the bug fix**: the item called "home" used to leave LOffice entirely |
| Back to MOT Main ↗ | T1 | `postMessage {cmd:'switchTab', id:'mc'}`; unchanged, just labelled honestly and moved to the bottom |

### Edit

| Item | How | Note |
|---|---|---|
| Undo / Redo | — | *"⌘Z works inside the cell you are editing — the browser's own undo. A whole-sheet history needs the rich editor."* ⚠️ Univer has undo commands; the Facade command id was **not verified by reading the bundle**, so it is not invented here |
| Cut / Copy | — | *"use ⌘X / ⌘C in the cell — opening this menu moves the focus out of it"*. True and structural: tier-1 selection **is** DOM focus, and clicking a menu button blurs the cell (which also commits it) |
| Paste | — | *"a page cannot paste for you — press ⌘V in the cell"* (no programmatic clipboard read) |
| **Find… ⌘F** | T1 | built in this slice: a real find bar, scans the active sheet's `cellData`, walks matches, grows the render window to reach one |
| Find and replace | — | *"replace is not built yet — Find takes you to each match and you can type over it"* |
| Clear this cell | T1 | acts on the last cell that had focus |

### View

| Item | How | Note |
|---|---|---|
| Show file list / Show AI panel | T1 | the two existing panes; the AI call is made defensively (another builder owns that panel) |
| Full width | T1 | collapses both panes — the honest local meaning of "Full screen" |
| Gridlines | T1 | a class on `#gt` |
| Zoom 50 / 75 / 100 / 125 / 150 % | T1 | CSS `zoom` on `#gt`. ⚠️ **unverified in WKWebView** |
| Freeze rows / columns | — | *"freezing needs a second sticky axis the plain grid does not have — the rich editor freezes"* |
| Rich editor | T1 | the existing tier-2 upgrade, now reachable from a menu as well as a button |

### Insert

| Item | How | Note |
|---|---|---|
| Sheet ⇧F11 | T1 | appends to `sheets` + `sheetOrder`; `office.py::_sheet_names` de-duplicates the name on write |
| 50 more rows / 10 more columns (at the end) | T1 | the two `#gridbar` grow actions, also in the menu |
| Row above / Column left | — | *"inserting inside the sheet would have to renumber every merged range and every formula — the rich editor does that"* |
| Function ▸ | — | *"type it into the cell, starting with `=` — LOffice stores formulas as text and Excel recalculates them"* |
| Chart / Image / Pivot table / Link / Checkbox | — | *"LOffice's .xlsx round-trip does not model this yet (see Help → What round-trips)"* |

### Format — **all of these round-trip; verified against `office.py::apply_style`**

| Item | How | Style key written |
|---|---|---|
| Bold ⌘B | T1 | `bl` |
| Italic ⌘I | T1 | `it` |
| Underline ⌘U | T1 | `ul:{s:1}` |
| Strikethrough | T1 | `st:{s:1}` |
| Align left / center / right | T1 | `ht` = 1 / 2 / 3 |
| Wrap text | T1 | `tb:3` |
| Clear formatting | T1 | removes `s` |
| Number format | — | *"the plain grid shows raw values, so a format you could not see would be worse than none — the rich editor renders them"*. ⚠️ `n:{pattern}` **is** carried by `office.py` both ways; the gap is tier-1 rendering only |
| Merge cells | — | *"merging needs a selected range, and this grid selects one cell at a time"* |
| Text colour / Fill colour | — | *"a colour picker is a control this page does not have yet"*. `cl` / `bg` are carried both ways |

The mechanism is worth writing down because it is the one thing a naive implementation gets wrong:
a cell's `s` may be **an inline dict OR a string id into `workbook.styles`**
(`office.py::_resolve_style`, verified). A style id is **shared between cells**, so a toggle must
resolve → *copy* → write back as an **inline dict on that one cell**. Mutating the shared entry would
bold half the workbook.

### Data

| Item | How | Note |
|---|---|---|
| **Column statistics** | T1 | count / numbers / sum / min / max / mean of the focused column, into the message box. Read-only: zero corruption risk, which is why it is the one Data item that ships enabled |
| Sort sheet / Sort range | — | *"sorting moves cells, and this grid will not risk a merged range or a formula reference yet"* |
| Create a filter / Data validation / Split text to columns | — | *"not built yet"* |
| Rename this sheet | — | *"the rail's name box is doing two jobs already; the rich editor renames a sheet from its tab"* ⚠️ this one is a **test fence, not a judgement**: `nameMode` is pinned to exactly two verbs by `test_office_ai.js`, so a third mode is not this slice's to add |

### AI (our Gemini-menu equivalent) and Help

| Item | How |
|---|---|
| Ask about this sheet | T1 — opens the panel and focuses its box |
| Show the AI panel / Clear the conversation | T1, defensively (`typeof` guarded; the item disables itself if that panel's ids move) |
| Keyboard shortcuts | T1 — a real cheat sheet of what *we* implement, in the message box |
| What round-trips | T1 — the bridge's own `fidelity` sentence |
| About this build | T1 — build stamp, tier, documents folder, boot-log path |

---

## 6. What our `.xlsx` round-trip carries — the honest ceiling

**Carried both ways** (`office.py`): cell values typed as string / number / boolean, **formulas as
text plus the cached result**, dates as Excel serials, number formats, bold, italic, underline,
strikethrough, font name, font size, font colour, solid fill, horizontal and vertical alignment,
wrap, merged ranges, column widths, row heights, sheet names and order.

**NOT carried — a save drops it**: charts, images, pivot tables, conditional formatting, data
validation, comments, cell borders, freeze panes, filters, named ranges, macros.

That is why the fidelity sentence and the daily `.bak` exist, and it is why **Make a copy is not
faked** out of `new` + `save`.

## 7. What we did not do, and would do next

1. **Verify Univer's Facade command ids** (undo/redo/merge/number-format) by reading the vendored
   bundle. Every `UV` row above is a one-line wiring job *after* that read — and not before.
2. **Submenus.** Google nests with `▸`; we ship one flat level with separators. Zoom is five sibling
   rows rather than a `Zoom ▸`. Worth revisiting when a menu passes ~14 rows.
3. **A real toolbar** (the icon row under the menu bar: bold/italic/fill/align/number). The Format
   menu is the same commands; the toolbar is the fast path.
4. **Find and replace**, **sort**, **insert row/column** — all three want an undo stack first, which
   wants either a tier-1 history or Univer's.
5. Docs and Slides. Gated on the §9 measurement in the alternatives sweep, not on this file.
</content>
</invoke>

---

## ⟳ UPDATE 2026-08-27 (v1.5.2) — the undo stack arrived; §5 and §7 are partially stale

§7.4's "want an undo stack first" gate is CLEARED: LOffice now has a page-wide undo/redo
stack (50 entries, ⌘Z/⇧⌘Z/⌘Y, Edit-menu rows live). Rows listed `—` disabled in §5 that are
now WIRED: Edit → Undo/Redo, Find **and replace** (replace + replace-all in the find strip);
Data → Sort sheet A→Z / Z→A (merges refuse, formulas warn, row 1 sorts with the sheet — no
header guessing); Insert → Row above / Column to the left / Delete this row / Delete this
column (merges renumbered, formula references deliberately NOT rewritten — stated per gesture).
The AI action block gained `sort` / `insert` / `delete_rc` riding the same stack. Still
disabled as listed: cut/copy/paste, freeze, number-format rendering, merge UI, colour pickers,
filters, data validation. §7.3's toolbar row = the next slice. Details: test suites 491+491
and the 2026-08-27 session notes.

## ⟳ UPDATE 2026-08-27b — §7.2 and §7.3 are DONE; §7.1, §7.5 are what remain

**§7.3 the toolbar row** shipped: a third white row flush with the sheet (`#toolbar`),
twelve icon buttons — undo · redo │ **B** *I* U S │ align left/centre/right · wrap │ clear
formatting · find. It adds NO command: each button carries `data-row` (the id of the menu
row it mirrors) and its click is `el(data-row).click()`, so the handler, the enable rule,
the disabled REASON and the pressed state are all read off the menu after `menuPaint` has
decided them. The writer-set fence in `test_office_ai.js` still names exactly seven
writers — the toolbar added none. `View → Show toolbar` toggles it
(`motdeck-office-toolbar`, default ON).

**§7.2 submenus** shipped, one nesting level with Google's `▸`: `View → Zoom ▸` (the five
sibling rows moved in, ids unchanged) and `Format → Text ▸` (bold/italic/underline/
strikethrough, shortcut column intact). Opens on click and on hover after 220 ms, `→`
enters, `←` closes, Esc/outside-click closes all, and the flyout flips to the left of its
parent row — but **only when flipping helps**: driving the real page at 362 px showed a
one-sided rule putting the card at x = -87, off the screen entirely. The `overflow` ban
now covers the whole ancestor chain (`#menubar`, `#menus`, `.mwrap`, `.mpop`, `.msubwrap`)
and a test walks it.

Suites: 577 (grid) + 496 (AI) green, plus the Python lane. Still open from §7: (1) Univer
Facade command ids — moot, the tier-2 loader is being replaced by ONLYOFFICE; (5) Docs and
Slides. Still shipped disabled, unchanged: cut/copy/paste, freeze, number-format
rendering, merge UI, colour pickers, filters, data validation.
