# Adversarial QA — LOffice server lane, 2026-08-28

**Scope.** `bridge/office.py` (snapshot ↔ openpyxl round-trip) and `bridge/office_ops.py`
(op grammar, staging, apply, checkpoints), read-side included. Hunted for ONE class of
defect: **behaviour that is silently wrong from Debi's point of view** — a card, a tool
result, a receipt or a file that says one thing and means another. The 2026-08-27 incident
(`"$2,500"` written as text, `=SUM` returning 0, nothing warning) is the template.

**Method.** Real workbooks built by openpyxl (i.e. by something that is *not* this lane),
real `stage_changes` → `apply_changeset` cycles against a scratch motdeck root, real
re-reads off disk. Nothing here is inferred from reading the source; every finding was
executed. Every one has a repro in `bridge/tests/test_office_adversarial.py`, same id.

    data/bridge-venv/bin/python bridge/tests/test_office_adversarial.py

**Counts.** 34 findings reproduce: **18 LIES-TO-USER · 6 REFUSES-WRONGLY · 10 COSMETIC**,
plus 4 CONTROL checks pinning behaviour that is already correct.

**Nothing here was fixed.** No existing file was edited. The two new files are this
document and the repro script.

---

## Known-in-flight — checked, confirmed landed, skipped

Another builder is in `office_ops.py` / `office_mcp.py` / `office/panel/office.html`. I
read their work as it stood at the time of writing and confirmed the following are DONE,
so they are not findings:

| in-flight item | state at 2026-08-28 |
| --- | --- |
| currency-string coercion (`"$2,500"` → 2500 + `$#,##0`) | landed — `coerce_numeric`, and it also covers `15%`, `1,200`, `-$500`, `$ 2,500`, and whitespace-padded numbers (`"  42  "` → 42) |
| aggregate-over-text warning | landed — `text_numeric` / the trap detector |
| type-honest grounding | in progress — `before_display` / `after_display` / `coerced` are on every preview row |
| computed receipt check | in progress — `_verify` re-reads from disk |

Their documented **deliberate** exclusions (other currencies and locales, accounting
negatives `(2,500)`, `1e5` / `0x10` / `007`, malformed grouping `1,23`) I verified behave
as documented and did **not** file. F-09, F-10, F-11, F-13 and F-28 touch the same
neighbourhood but are separate mechanisms, and each says so in its own entry.

---

## LIES-TO-USER (18)

### F-01 — the apply has no mtime fence, and one is *recorded* for it
`stage_changes` writes `cs["file_mtime"] = os.path.getmtime(target)`. **Nothing in the
codebase ever reads that key** (`grep -rn file_mtime bridge/` → one hit, the write). So:
stage a sort → the ONLYOFFICE editor writes back, or Debi saves, or another changeset
lands → press Apply → it applies, against a preview that is now fiction. The card promised
`A1: 10 → 50`; the receipt afterwards says *"0 of 4 re-read cell(s) hold what the change
said they would."* The dirty-heartbeat refusal does not cover this: a *saved* writeback
clears dirty. The undo path has exactly this fence already (`FENCE_EPS`,
`UNDO_FENCE_REFUSAL`) — the apply path does not.
**Correct:** `apply_changeset` must refuse when the workbook's current mtime differs from
`cs["file_mtime"]` by more than `FENCE_EPS`, in a sentence that says the workbook changed
since the preview and the change must be re-staged.

### F-02 — the card names the sheet the model asked for, not the one that gets written
`public_changeset` returns `"sheet": cs["sheet"]`, which is the *requested* name.
`target_sid` falls back to the first sheet for an unknown name, and `_sheet_note` — the
honest sentence, which exists — is wired into `_apply` and `op_read` only, **never into
`stage_changes`**. Staging against `"Q3 Data"` on a workbook of Alpha/Beta/Gamma produces
a card headed `sheet: "Q3 Data"` whose preview rows all say `Alpha`, with no note. The
warning arrives in the apply result, after the write.
**Correct:** `stage_changes` must resolve the sheet, put the RESOLVED name in
`public_changeset["sheet"]`, and prepend `_sheet_note` to the changeset's notes.

### F-03 — insert/delete silently mis-shifts every column past GR on a wide sheet
`rc_apply` computes `cap_cols = min(cols, TIER1_MAX_COLS)` (200) and hands that to
`grid_remap`. On a sheet 250 columns wide:
* **row insert** — columns A…GR shift down one, columns GS…IP do not. The header row is
  now split across two different rows, permanently, in the saved file.
* **column insert** — the value in column 200 is destroyed and columns 201…250 stay put.

The only note that fires is *"the insert reached the right-hand edge of this grid (column
GR), so the last column fell off it"* — false on three counts (nothing fell off; it fires
for row inserts where no column moved; 50 columns silently stopped moving). `sort` uses
the full `ucols` and is correct, which makes the asymmetry invisible from the outside.
**Correct:** remap the full used width, or refuse insert/delete on a sheet whose used
width exceeds `TIER1_MAX_COLS` with a sentence naming the limit.

### F-04 — the formula honesty note is scoped to one sheet
`run_ops` gates `RC_FORMULA_NOTE` on `sheet_formulas(sh)` — the *target* sheet. Insert a
row in `Data` while `Summary!A1` holds `=SUM(Data!A1:A5)` and `Summary!A2` holds
`=Data!A3`: both now read the wrong cells, and **no note reaches the card, the receipt or
the tool result.** This is exactly the "does the honesty note reach every path" question,
and the answer is no.
**Correct:** fire the note when ANY sheet in the workbook holds a formula, and name the
other sheets whose formulas reference the one being changed.

### F-05 — merged ranges are invisible in the preview
`snapshot_diff` walks `cellData` only. Deleting two rows inside `A1:A4` reshapes the merge
to `A1:A2`; the card reads *"2 row/column(s) DELETED — 0 cells would change"* with an
empty before→after table. Inserting a row above a merge shifts `A1:C1` → `A2:C2` with no
mention either.
**Correct:** `snapshot_diff` must emit merge before→after rows, and the card must list
them alongside the cell rows.

### F-06 — a formatting-only changeset previews as nothing and gets a green receipt
`cell_face` ignores `s` entirely, so a `style` op produces `preview == []` and
`cells_changed == 0`. The card says *"5 formatted — 0 cells would change"*; the receipt
says *"0 of 0 re-read cell(s) hold what the change said they would."* The write did happen
(A1 is bold on red). The panel's success badge renders from those numbers.
**Correct:** the diff must include style and number-format changes as preview rows, and
`_verify` must re-read at least the styled cells.

### F-07 — the pre-agent copy destroys a real workbook of that name
`pre_agent_for` returns `<stem>.pre-agent.xlsx` and `take_pre_agent` does an unconditional
`shutil.copy2` onto it. A workbook Debi actually has called `report.pre-agent.xlsx` — and
`op_list` lists such files as ordinary workbooks, so she can make one from the panel — is
silently overwritten by the first apply on `report.xlsx`. Nothing on the card, in the
receipt or in the notes names the file it is about to overwrite.
**Correct:** refuse (or step to a free name) when the destination exists and is not a copy
this lane made, and name the pre-agent file on the card before Apply, not after.

### F-08 — a trailing space on a formula makes the receipt report a failed write
`parse_input` stores `out["f"] = s` unstripped; `office._write_cell` writes
`f.strip()`. So the snapshot, the preview and `_verify`'s `expected` carry
`"=SUM(B1:B2) "` while the disk correctly holds `"=SUM(B1:B2)"` — and the receipt says
*"0 of 1 re-read cell(s) hold what the change said they would."* A perfect write reports
as a failure, on the surface whose whole job is to be trustworthy.
**Correct:** `parse_input` must store the stripped formula, so snapshot, preview and disk
agree.

### F-09 — coercion overrides an explicit text (`@`) or custom number format
A column Debi formatted `@` ("this is text") takes `"1,200"` and stores the **number**
1200 with format `#,##0`. A cell formatted `0.00" kg"` loses her unit pattern the same way.
`_merge_format` always writes the generated pattern over whatever was there. The card's
coercion note says the value is stored "as a real NUMBER with a matching format" and never
mentions the format it replaced.
**Correct:** suppress coercion when the target cell's existing number format is a text
format (`@`), and when the cell already carries a number format, say on the card which
pattern is being replaced.

### F-10 — a text date in a date-formatted cell is completely invisible
Writing `"2026-01-15"` into a cell formatted `yyyy-mm-dd` keeps the format, so the cell
**renders identically to the real dates above it** while being a string that breaks
`=A3-A1` and every date sort. The card's `before_display` prints `46034 (yyyy-mm-dd)` — the
raw serial, not the date — so the before→after row reads "46034 → 2026-01-15", which looks
like a *fix*. `coerced: false`, no note, and the receipt says `match: true`. This is the
`$2,500` incident with the visual tell removed.
**Correct:** flag a value that stays TEXT in a cell whose number format is a date/time
pattern the same way currency coercion is flagged, and render `before_display` for a
date-formatted numeric cell as the actual date.

### F-11 — `op_read` hands the model bare date serials
A date cell comes back as `{"value": 46037.0, "text": "46037"}`; a time cell as
`0.3958333333333333`. No number format, no note anywhere in the result. An agent asked
"what is the invoice date in A1?" answers 46037.
**Correct:** carry the cell's number format in the read result and, when it is a date/time
pattern, render `text` as the date and say so in a note.

### F-12 — integers past 2^53 lose precision, and the card prints a third value
`_fin` floats everything, so `12345678901234567` lands on disk as
`1.234567890123457e+16` (…570). The preview shows `1.2345678901234568e+16` — a value that
matches neither the request nor the file. No note. An order number or an ID silently
changes digits.
**Correct:** refuse an integer whose magnitude exceeds 2^53 (or keep it as text) with a
sentence saying it cannot be stored exactly.

### F-13 — `sheet_stats` counts a formula cell twice and aggregates none of them
`sort_key` classes a formula as text, so a column of five `=A1*2` cells reports
`{"numbers": 0, "text": 5, "formulas": 5}` — ten things in a five-cell column — with no
`sum`/`min`/`max` at all, under a note claiming *"every number here is computed from the
values in the file."* A model reading `numbers: 0, text: 5` concludes the column is text.
**Correct:** a formula cell must count only in `formulas`; report the cached-value
aggregate separately and labelled, or say in words that this column's values are formulas
and cannot be aggregated from the file.

### F-14 — `"cached": true` on a formula cell that has no cached value
`op_read` sets `"cached": True` unconditionally for a formula and adds `cached_value` only
when one exists. After any apply — see F-33 — none does, so every formula in the workbook
reads back as `{"formula": …, "cached": true}`: a flag asserting a value that is not there.
**Correct:** emit `"cached": false` with an explicit reason when the file holds no cached
result for that formula.

### F-15 — a rename with an unknown `at` renames the *first* sheet
`{"op":"sheet","rename":"Renamed","at":"Nonexistent"}` renames Alpha, because
`target_sid` falls back. `op_summary` returns `"rename a sheet to 'Renamed'"` — it never
names *which* sheet — the preview is empty, and there is no note.
**Correct:** `op_summary` must name the resolved sheet, and a rename whose `at` matches no
existing sheet must be skipped with a note.

### F-16 — renaming onto an existing sheet name renames the *other* sheet
Renaming Alpha to `"Beta"` on a workbook that already has a Beta yields `["Beta",
"Beta(2)"]`: `office._sheet_names`' dedup step renamed **Debi's** Beta. The card only
offered to rename one sheet, and said nothing about the second.
**Correct:** refuse a rename onto a name another sheet already holds — the same ruling
`office.rename_doc` already makes for files.

### F-17 — the changeset store cap evicts pending proposals silently
`stage_changes` drops the four oldest changesets whenever the store reaches
`CHANGESET_MAX`. Staging 30 proposals across 30 workbooks leaves **one** pending; the
other 29 models were told *"NOT applied — Debi reviews and applies this in LOffice"* and
their cards simply do not exist. No session line, no note, nothing in the panel.
**Correct:** push an eviction session line to the affected session (the mechanism already
exists — `push_session_line`), or refuse a new staging once the cap is reached.

### F-27 — four things the fidelity contract does not name are lost, and the snapshot fakes three of them
Verified survivors of stage → apply → re-read: bold, italic, underline, strike, font name,
font size, font colour, fill colour, h/v alignment, wrap, number formats, merges, column
widths, row heights, multiple sheets. All good. **Also lost, and named nowhere:** freeze
panes, gridline visibility, hidden rows, hidden columns, autofilter. A hidden column
becoming visible is data Debi deliberately hid coming back on screen after an agent write.
Worse: `sheet_snapshot` emits hard-coded `freeze: {xSplit:0,…}`, `showGridlines: 1` and
`hd: 0` on every row/column entry — values read from nothing and written to nothing, so
they *assert* "not frozen, gridlines on, nothing hidden" about a sheet where all three are
false. A present-but-fake field is worse than an absent one.
**Correct:** carry freeze / hidden / gridlines / autofilter through the round-trip (the
snapshot fields already exist), or stop emitting the fake values and name the losses in
`office.FIDELITY_NOTE`.

---

## REFUSES-WRONGLY (6)

### F-18 — `add_sheet` loops forever on a 31-character name collision
```python
base = name[:ACT_SHEET_MAX]          # 31 chars
nm, n = base, 2
while nm.lower() in taken:
    nm = f"{base} {n}"[:ACT_SHEET_MAX]   # ← re-truncated to the SAME 31 chars
    n += 1
```
Adding a sheet whose name is already taken and already 31 characters long spins forever.
Reached from **both** `stage_changes` and `apply_changeset`, so the request never returns
and a bridge worker thread is burnt at 100% CPU permanently. Confirmed with a SIGALRM
guard in the repro.
**Correct:** build the suffix inside the budget — truncate `base` to
`ACT_SHEET_MAX - len(suffix)` before appending — and bail out after a bounded number of
attempts.

### F-19 — an Excel-invalid sheet name stages fine and 500s on Apply
`validate_ops` checks only length. `office.write_snapshot` calls
`wb.create_sheet(title=name)` outside any `try`, and openpyxl raises `ValueError: Invalid
character : found in sheet title` for any of `: [ ] * ? / \`. `save_doc` catches only
`OfficeError`, so the ValueError escapes `apply_changeset` and the route answers **HTTP
500 with a traceback**. By then the checkpoint, the daily `.bak` and the pre-agent copy
have all been taken, the whole changeset (including any `set` ops in it) is lost, and every
retry crashes the same way.
**Correct:** refuse an `add`/`rename` sheet name containing Excel's invalid title
characters in `validate_ops`, with a sentence; and wrap `create_sheet` so an unwritable
title becomes an `OfficeError`, not a 500.

### F-20 — a refused Apply still pushes a checkpoint, pruning away every real undo point
`apply_changeset` calls `push_checkpoint` **before** `_apply` runs the dirty check. Each
refused press ("you have unsaved edits…") therefore adds a checkpoint of an unchanged
file, and `CHECKPOINT_KEEP` is 10 — so ten refused presses while the editor is dirty prune
out every checkpoint from a real apply. Verified: 3 real applies then 10 refused presses
leaves 10 checkpoints, **none** of them from a real apply.
**Correct:** run every refusal (`open_state` dirty, sheet resolution, file existence)
before taking the checkpoint, or delete the checkpoint when the apply fails.

### F-21 — renaming a workbook kills undo for good
`checkpoint_dir` is keyed by the file stem, and `office.rename_doc` moves neither
`.checkpoints/<stem>/` nor `<stem>.pre-agent.xlsx`. After a rename, `undo_changeset`
answers `"no such workbook"` — blaming a missing file for what is really an orphaned
stack — while the checkpoint sits on disk under the old stem, unreachable.
**Correct:** move the checkpoint directory and the pre-agent sibling in `rename_doc`, or
say in the refusal that the workbook was renamed and where the checkpoint still is.

### F-22 — a workbook named `*.pre-agent.xlsx` can never be written
`pre_agent_for("report.pre-agent.xlsx")` returns itself (the `.pre-agent` strip is there to
avoid `.pre-agent.pre-agent`), so `take_pre_agent` does `copy2(x, x)` and the refusal that
reaches Debi is a raw `shutil.SameFileError` string with two absolute temp paths in it.
**Correct:** detect the self-copy and refuse with a sentence — or better, refuse to open a
`*.pre-agent.xlsx` for writing at all and say why.

### F-23 — a sheet-add or sheet-rename changeset verifies nothing, in a sentence that reads as a failure
`_verify` iterates `cs["preview"]`, which is empty for a structural change, and reports
*"0 of 0 re-read cell(s) hold what the change said they would."* The sheet was in fact
added (correctly stepped to `Data 2` on collision) and nothing re-read the workbook to
confirm it.
**Correct:** verify sheet-level outcomes too (the sheet exists, under the name that was
actually written) and give a receipt sentence that is about sheets rather than cells.

---

## COSMETIC (10)

* **F-03b** — the clipped-grid note says *"the insert reached…"* on a `delete_rc`.
* **F-24** — a destructive `n` is silently defaulted to 1: `n: 0`, `n: -5`, `n: "all"` and
  `n: 1.9` all delete exactly one row. Only the card's own op line contradicts a model
  that reported deleting everything. *Correct:* refuse a non-numeric or `< 1` count on a
  destructive op.
* **F-25** — `RC_FORMULA_NOTE` fires for an insert at row 900 on a sheet whose only
  formula is `B1=A1*2`. Nothing could have moved; she is told to check her formulas anyway.
  *Correct:* fire only when a reference could plausibly have been affected (or say "no
  reference in this sheet could have moved" when none could).
* **F-26** — `op_read`'s merge note tells the model *"office_sort REFUSES a sheet with any
  merge on it."* There is no `office_sort` tool any more; a `sort` op inside a changeset is
  skipped with a different sentence on a different surface.
* **F-28** — `FORCE_STRING` (`t: 4`) intent does not survive the round-trip: `{v:7,t:4}`
  writes as the string `"7"` (right) and re-reads as `{v:"7",t:1}`, so the new
  text-that-looks-numeric detector will nag about a cell the page made text on purpose.
  *Correct:* re-derive FORCE_STRING on read from an `@` number format, or persist the
  intent.
* **F-29** — syntactically invalid formula text (`==`, `=A1+`) is written verbatim as a
  formula with no note; Excel may report the workbook as needing repair.
* **F-30** — a self-referencing formula (`=A3+1` in A3) is accepted with no note.
* **F-31** — `office._sheet_names`' dedup step produces 32-character titles from the tenth
  duplicate on (`base[:28] + "(10)"`), past Excel's limit; openpyxl warns and writes it.
* **F-32** — apply after a rename or a delete answers a bare `"no such workbook"`, never
  that the workbook moved or that the proposal is still pending and re-stageable.
* **F-33** — every apply wipes every cached formula result in the workbook (openpyxl writes
  formulas without cached values), and nothing says so. Excel and ONLYOFFICE recalculate on
  open, so the visible damage is nil — but the *model* can no longer read any computed
  number out of the file it just changed, which is a grounding cliff nothing warns about.

---

## CONTROL — verified correct, pinned against regression

* **CTRL-CAPS** — exactly at and one over: 60/61 ops, 2000/2001 cells, row 5000/5001,
  column GR/GS, `style` GR5000/GS5000, `delete_rc` 200/201 rows. All twelve behave, with
  the right refusal sentence. The REFUSE-vs-CLAMP asymmetry (`insert`/`resize` clamp,
  `set`/`style`/`delete_rc` refuse) holds.
* **CTRL-REFS** — `A0`, `1A`, `A1:`, `:B2`, `A`, `A1:B2:C3`, `AAAA1`, `A99999999` all
  refused; `D5:A1` normalises to the same rectangle as `A1:D5`; `$A$1` accepted;
  `ZZZ99999` parses and is refused by the grid bound with a useful sentence.
* **CTRL-AON** — one invalid op refuses the whole changeset and writes nothing. All-or-
  nothing holds, at staging (so it never reaches the file).
* **CTRL-SHEET** — read-side sheet targeting across three sheets: exact name, case- and
  whitespace-insensitive match, `None` → first sheet, and an unknown name → first sheet
  **with** the `_sheet_note` warning. (Contrast F-02: staging does not do this.)

Also verified and *not* findings: reversed ranges are documented as normalising; the
heartbeat TTL correctly reads a 16-second-old beacon as closed; `op_read`'s 2000-cell cap
is exact and its refusal names the size; checkpoint pruning keeps the newest 10 and the
refusal for a pruned checkpoint is honest; `create_workbook` name edges (`.hidden`, `..`,
`a/b.xlsx`, 81 characters) are all refused by `office.valid_name`; unicode and emoji sheet
and workbook names work; a real date cell round-trips intact; `sort` correctly remaps the
full used width (unlike insert/delete — F-03); staging never touches the file's mtime.

---

## Suggested fix order

1. **F-18** (hangs the bridge), **F-19** (500s on Apply) — availability, and both are
   small.
2. **F-01** (apply with no mtime fence), **F-03** (silent wide-sheet corruption),
   **F-07** (destroys a real file) — irreversible damage.
3. **F-02**, **F-05**, **F-06**, **F-08**, **F-15**, **F-16**, **F-23** — the card and the
   receipt are the consent surface; each of these makes them say something untrue.
4. **F-09**, **F-10**, **F-11**, **F-12**, **F-13**, **F-14** — the typing and grounding
   family, adjacent to the in-flight coercion work and best done in the same pass.
5. **F-20**, **F-21**, **F-22**, **F-17**, **F-27** — recovery and fidelity.
6. The COSMETIC ten, as a single sentence-and-wording sweep.
