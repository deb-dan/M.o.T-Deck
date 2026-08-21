# Google Sheets / Docs / Slides — menu + chrome inventory (transcribed from Debi's screenshots, 2026-08-21)

> **Why this file exists.** Debi supplied 16 screenshots of Google Sheets (home + every
> menu), Google Docs (Insert/Format/Tools/Gemini) and Google Slides (Edit/View/Insert)
> with the instruction: *"Did you even care to do research as per google
> sheets/doc/presentation etc… See how extensive it is, how everything is in the white
> strip and uniform. Do research, be detailed."* Builders and Fable cannot see the
> images, so this is a **verbatim transcription** — it IS the spec (standing doctrine:
> DESIGN REFERENCES ARE LITERAL; screenshots are spec). Every item below was read off
> the screenshots, including which items are greyed/disabled and which carry shortcuts,
> submenu arrows (▸) or badges.

## 0. The structural lessons (what LOffice got wrong)
1. **One white strip owns everything.** Title row, menu bar, toolbar and formula bar are
   all light chrome, contiguous, no dark band anywhere, no rounded "chips". LOffice's
   dark header + gold-outlined pills + a lone `File ⌄` chip floating above a white
   ribbon is the single biggest departure.
2. **The menu bar is plain text, left-aligned, directly under the document title** —
   ~13px, no borders, no background until hover (light grey pill on hover/open). Ten
   items in Sheets/Docs/Slides. It is NOT a button; it is a menubar.
3. **The title row sits above the menu bar**: app icon (colored), editable document
   title, ☆ star, then right-aligned: comment-history icon, meet icon ▾, 🔒 Share ▾,
   AI sparkle, avatar. Docs/Slides identical, Slides adds a `Slideshow ▾` button.
4. **The toolbar is grouped, not uniform** — icon groups separated by thin vertical
   hairlines, an overflow `⋮` when narrow, and a `⌃` collapse chevron at the far right.
5. **Menus are white cards**: ~1px border + soft shadow, ~220-340px wide, sections
   separated by full-width hairlines, item = optional leading icon + label + right-
   aligned shortcut or ▸. **Disabled items stay visible and greyed** (never hidden) —
   e.g. Sheets ▸ Data ▸ "Analyze data", Docs ▸ Format ▸ Table. Badges (`New`,
   `Updated`) are small blue/green pills after the label.
6. **A bottom bar exists** in Sheets (+ add sheet, sheet-list icon, `Sheet1 ▾` tab) and
   Slides (speaker-notes strip + grid icon + ‹ collapse). Docs uses a left "Document
   tabs" rail instead.
7. **AI is FOUR surfaces at once**: a top-level menu (`Gemini`), a right side panel with
   a rotating hint headline ("Generate a visual dashboard", "Type @ to reference
   sources"), suggestion chips + a prompt box at the bottom of the canvas, and inline
   entry points inside Insert/Tools. Ours is only the right panel.
8. **The home screen is a first-class page, not an empty editor** (see §1) — this is
   what Debi means by "take to main page without anything/doc open".

## 1. Sheets HOME (docs.google.com/spreadsheets/u/0)
- Top bar: ☰ hamburger · Sheets logo+wordmark · big rounded **Search** field · apps-grid
  icon · avatar.
- Band: **"Start a new spreadsheet"** + right-aligned `Template gallery ⌄` and `⋮`.
  Six template cards in a row, each a thumbnail image above a caption: **Blank
  spreadsheet** (grey + glyph), To-do list, Annual budget, Monthly budget, Google
  Finance Invest…, Annual Calendar.
- Below, on white: a section label (**"Earlier"**) and a file LIST with column headers
  `Owned by anyone ▾` · `Last opened by me` and right-aligned view controls
  (grid-view icon, `A↓Z` sort, folder icon). Rows: file-type icon (green Sheets glyph
  or blue `X` for .xlsx/.xls), name, owner ("me" or "--"), date, trailing `⋮`.
- Sharing state shown as a small people glyph after the name.

## 2. Sheets menu bar (10 items)
`File · Edit · View · Insert · Format · Data · Tools · Gemini · Extensions · Help`

Toolbar (one strip, groups hairline-separated):
search · undo · redo · print · paint-format ‖ `100% ▾` ‖ `$` `%` `.0←` `.00→` `123 ▾`
‖ `Default… ▾` (font) ‖ `−` `10` `+` ‖ **B** *I* S̶ `A▾` (text colour) ‖ fill ▾ ·
borders ▾ · merge ▾ ‖ `⋮` overflow … far right `⌃` collapse.
Formula bar row: `A1 ▾` name box · ✕ · ✓ · *fx* · input … right `▾` (expand).
Bottom bar: `+` · sheet-list icon · `Sheet1 ▾`. Bottom-right: grid-view icon,
`− ——●—— +` zoom slider, `74%`/`100%`.

### File
New ▸ · Open ⌘O · Import · Make a copy ─ Share ▸ · Email ▸ *(greyed)* · Download ▸
─ Rename · Move to trash *(greyed)* ─ Version history ▸ *(greyed)* · Make available
offline ─ Details *(greyed)* · Security limitations *(greyed)* · Settings ─ Print ⌘P
### Edit
Undo ⌘Z · Redo ⌘Y ─ Cut ⌘X · Copy ⌘C · Paste ⌘V · Paste special ▸ ─ Move ▸ *(greyed)*
· Delete ▸ ─ Find and replace ⌘+Shift+H
### View
Show ▸ · Freeze ▸ · Group ▸ · Comments ▸ ─ Hidden sheets ▸ *(greyed)* ─ Zoom ▸ ·
Full screen
### Insert
Cells ▸ · Rows ▸ · Columns ▸ · Sheet Shift+F11 ─ Generate a table · Pre-built tables
─ Create a canvas `New` · Chart · Pivot table · Image ▸ · Drawing ─ Function ▸ ·
Link ⌘K ─ Checkbox · Dropdown · Emoji · Smart chips ▸ ─ Comment ⌘+Option+M ·
Note Shift+F2
### Format
Theme ─ Number ▸ · Text ▸ · Alignment ▸ · Wrapping ▸ · Rotation ▸ · Smart chips ▸
─ Font size ▸ · Merge cells ▸ *(greyed)* ─ Convert to table ⌘+Option+T *(greyed)* ·
Conditional formatting · Alternating colors ─ Clear formatting ⌘\
### Data
Analyze data *(greyed)* · Solve an optimization problem `New` *(greyed)* ─ Sort sheet ▸
· Sort range ▸ *(greyed)* ─ Create a filter · Create group by view ▸ · Create filter
view · Add a slicer ─ Protect sheets and ranges · Named ranges · Named functions ·
Randomize range *(greyed)* ─ Column stats · Data validation · Data cleanup ▸ · Split
text to columns · Data extraction ─ Data connectors `New` ▸
### (LOffice's current Univer ribbon for comparison)
Univer gives us tabs `Start | Formulas | Data` with grouped icon rows and cascading
function menus (`Common Functions ⌄ Financial ⌄ Logical ⌄ Text ⌄ Date & Time ⌄
Lookup & Reference ⌄ Math & Trig ⌄ ⋮`) — i.e. Google's *toolbar* exists; the
**menu bar above it is what's missing**, and Univer's own ribbon tabs should sit
UNDER our menu bar, not compete with it.

## 3. Docs menu bar (10 items)
`File · Edit · View · Insert · Format · Tools · Gemini · Extensions · Help`
Toolbar: search · undo · redo · print · paint-format ‖ `100% ▾` ‖ `Normal text ▾` ‖
`Arial ▾` ‖ `− 11 +` ‖ **B** *I* U `A` highlighter ‖ link · comment+ · image ‖
align ▾ · line-spacing ▾ · checklist ▾ · bulleted ▾ · numbered ▾ · outdent · indent ·
clear-formatting ‖ (right) ▶-in-circle (listen) · pencil ▾ (mode) · `⌃`.
A horizontal **ruler** sits under the toolbar; the page is a white sheet on grey.
Left rail: **Document tabs** with `+`, `Tab 1` (selected, blue pill, ⋮), helper text
*"Headings you add to the document will appear here."*, `←` collapse.
Bottom of canvas: chips `Match doc format · Templates · Meeting notes · Email draft ·
More` above a rounded prompt box (`+`, tune icon, "Brainstorm a list of ideas for…",
panel-toggle, ↑).
### Insert
Image ▸ · Table ▸ · Building blocks ▸ · Smart chips ▸ · Audio buttons `New` ▸ ·
Link ⌘K · Drawing ▸ · Chart ▸ · Symbols ▸ ─ Tab Shift+F11 · Horizontal line ·
Break ▸ · Bookmark · Page elements `Updated` ▸ ─ Comment ⌘+Option+M *(greyed)*
### Format
Text ▸ · Paragraph styles ▸ · Align & indent ▸ · Line & paragraph spacing ▸ ·
Columns ▸ · Bullets & numbering ▸ ─ Headers & footers · Page numbers · Page
orientation · Switch to Pageless format ─ Table ▸ *(greyed)* · Image ▸ *(greyed)* ·
Borders & lines ▸ *(greyed)* ─ Clear formatting ⌘\
### Tools
Proofread ▸ · Word count ⌘+Shift+C · Review suggested edits Ctrl+⌘O Ctrl+⌘U ·
Compare documents *(greyed)* · Citations · Line numbers · Linked objects ·
Dictionary ⌘+Shift+Y ─ Translate document · Voice typing ⌘+Shift+S · Audio `New` ▸ ·
Gemini ─ Notification settings · Preferences · Accessibility
### Gemini
Create a new doc · Add new text · Refine selected text *(greyed)* · Listen to this tab
· Listen to document summary ─ ✓ Show Gemini bottom bar ─ ✦ Ask something else

## 4. Slides menu bar (10 items)
`File · Edit · View · Insert · Format · Slide · Arrange · Tools · Extensions · Help`
Toolbar: search · `+` (new slide) · new-slide-with-layout · undo · redo · print ·
paint-format ‖ zoom-glass · `Fit ▾` ‖ select-arrow · `Tt` text box · shape ▾ ·
line ▾ · image ‖ comment+ ‖ **Background** · **Layout** · **Theme** · **Transition**
(text buttons!) … right `⌃`.
Left filmstrip (numbered slide thumbnails). Right icon rail with labels underneath:
`Slide · Image · Templates · Blocks · Media · Uploads · Record · Transform`*(greyed)*.
Canvas: white slide with `Click to add title` / `Click to add subtitle` placeholders,
ruler top+left. Bottom: `Click to add speaker notes` strip, grid icon, `‹` collapse,
and a floating `⊞ Create a slide ✕` AI chip.
### Edit
Undo ⌘Z · Redo ⌘Y ─ Cut ⌘X *(greyed)* · Copy ⌘C *(greyed)* · Paste ⌘V · Paste without
formatting ⌘+Shift+V ─ Select all ⌘A · Delete *(greyed)* · Duplicate ⌘D *(greyed)*
─ Find and replace ⌘+Shift+H
### View
Mode ▸ ─ Slideshow ⌘+Enter · Motion ⌘+Option+Shift+B · Theme builder · Comments ▸
─ Grid view ⌘+Option+1 · ✓ Show ruler ─ Guides ▸ · Snap to ▸ · Live pointers ▸
─ ✓ Show speaker notes · ✓ Show filmstrip ─ Zoom menu ▸ · Full screen
### Insert
Help me visualize 🪄 ▸ ─ Image ▸ · Text box · Shape ▸ · Building blocks · Diagram ▸ ·
Table ▸ · Chart ▸ · Line ▸ · Word art ─ Video · Audio ─ Special characters *(greyed)*
· Animation *(greyed)* ─ Link ⌘K *(greyed)* · Comment ⌘+Option+M ─ New slide Ctrl+M ·
Create a slide ▸ · Templates · Slide numbers · Placeholder ▸ *(greyed)*

## 5. Mapping to LOffice (what we can honestly offer per menu item)
Ours must be **the same shape with our own truthful contents** — never a menu of dead
items. Sheets-first mapping (Docs/Slides when those tiers exist):
- **File** — New · Open ▸ (recent files submenu) · Import… · Make a copy ─ Download ▸
  (.xlsx) ─ Rename… · Move to trash (delete, two-step) ─ Close file (→ LOffice HOME)
  ─ Reveal in Finder · Save ⌘S. (Share/Version history/offline have no meaning here →
  omit rather than grey out: a greyed item that can NEVER work is a lie, whereas
  Google's greys are context-dependent.)
- **Edit** — Undo/Redo (Univer's), Cut/Copy/Paste (native), Find and replace (Univer).
- **View** — Rich editor on/off (our tier toggle!) · Freeze ▸ · Gridlines · Full
  screen · Show AI panel · Show file rail (⌘\) · Zoom ▸.
- **Insert** — Rows/Columns/Sheet · Function ▸ (from Univer's own list) · Chart (tier2)
  · Checkbox/Dropdown where Univer supports it. Absent capabilities are simply absent.
- **Format** — Number ▸ · Text ▸ (B/I/U) · Alignment ▸ · Wrapping ▸ · Merge cells ·
  Conditional formatting (tier2 only) · Clear formatting.
- **Data** — Sort ▸ · Create a filter · Column stats · Data validation (tier2) ·
  Split text to columns.
- **AI** (our `Gemini` equivalent — name it **`Assistant`** or **`MOT`**) — Ask about
  this sheet (focus panel) · **Create a sheet from a description** · **Fill/transform
  the selection** · Explain the selected formula · ✓ Show assistant panel.
- **Help** — Keyboard shortcuts · What round-trips (the fidelity note) · Boot
  diagnostics (the beacon log) · About LOffice + build stamp.

## 6. Non-negotiables extracted for the build
- Menu bar lives in the white strip, under a title row; the dark band goes away.
- Hover opens the next menu once one is open (menubar behaviour), Esc closes, ← →
  move between menus, ↑ ↓ within a menu, Enter activates.
- Every item is either enabled or greyed-with-a-reason-on-hover; nothing silently
  no-ops (the LOffice `if(!name) return;` class of bug).
- Shortcut labels right-aligned in the same row; ▸ for submenus that really cascade.
- The home screen is a real page: template cards + recent-file list, exactly §1's shape.
