# Bug-echo sweep — 2026-08-28

**What this is.** A read-only echo audit per the bug-echo methodology
(github.com/Terryc21/bug-echo, README + TECHNICAL.md read before starting): after a bug
is FIXED and proven real, search the codebase for identical or similar copies of the
same mistake, rate each match, and report — no fixes. Bound by
`docs/DOCTRINE-PROACTIVE-BUILD.md`. The pattern catalogue is this project's own proven,
fixed bugs, mined from the v1.5.9–v1.5.19 commits, both 2026-08-28 adversarial
catalogues, the 2026-08-27 consent incident, and the Hermes v0.20.6 blocked doc.

**Self-validation.** Per the methodology, each pattern was validated against its own
original before sweeping: `bridge/tests/test_office_adversarial.py` was run first and
reads **0 reproduce · 34 fixed · 4 controls hold** — so every F-nn original is
confirmed fixed and its brokenness is articulable (each fix carries a pinned ⚠️ comment
naming the finding). The pages' own suites were then run against CURRENT code so the
findings below describe the tree as it stands: office_grid 625 ✓, office_ai 991 ✓,
nav_panel 223 ✓, theme_packs 146 ✓, office_journey 288 ✓, office_mcp ✓, oo_lane ✓.

**Scope.** First-party only: `bridge/` (core, routers, satellites, panel pages, tests),
`scripts/`, `app/main.swift`. Not `vendor/`, not `data/`.

**Files written by this audit:** this document and
`bridge/tests/test_bug_echo_ledger.py` (executable repros for every BUG rating —
self-running, exits 0 always, NOT in the gate; the campaign-ledger pattern of
`test_office_adversarial.py`). Nothing else was touched.

    data/bridge-venv/bin/python bridge/tests/test_bug_echo_ledger.py

## Counts

| rating | count |
| --- | --- |
| **BUG** (real, executed, repro in the ledger) | **3** |
| **WATCH** (fine today, one step from breaking) | **8** |
| **REVIEW** (judgment call) | **2** |
| classes swept **clean** (echo hunted, none found) | **8 of 14** |

---

## BUG — real echoes, in user-impact order

### BE-01 — ✅ **FIXED 2026-08-28** (the SSE/panel slice) — the false-Done class was fixed in the LOffice panel and NOT in the main chat lane
> **Fix:** `bridge/panel/index.html`'s ONE `tool_output` handler (shared by the Hermes,
> Odysseus-agent and direct lanes) grew the `is_error` branch — a red ✗ chip carrying the
> tool's own sentence, drawn on the message HOLDER so the end-of-turn `renderChatBody()`
> cannot delete it, plus the step marked so `chatSummary` can never stamp ✓ over it.
> Gate: `bridge/tests/test_chat_toolerr.js` (70 checks; the chip functions EXECUTED
> against a DOM shim, the all-designs token proof, and both v1.5.9 controls).
> The paragraph below is the original finding, kept verbatim as the record.
`bridge/panel/index.html:10527` · echoes the **2026-08-27 agent-consent incident**
(model narrated "Done. Added Purchases…" over a failed write; nothing on screen
contradicted it — fixed v1.5.9 with MOT Deck-authored lines + ✗ chips).

The bridge maps `is_error` onto every `tool_output` frame for every lane
(`bridge/routers/hermes.py:218`, including the double-encoding unwrap), and
`office.html:8035` draws the red ✗ chip. index.html's Hermes chat lane consumes the
same frames and renders `tool_output` unconditionally as *"reading results…"* — the
word `is_error` does not occur anywhere in the page. A failed native or MCP tool in the
main chat is exactly as invisible as it was in the incident, and the model's "Done"
stands. **Correct:** the chat renderer draws a failure marker with the tool's own
sentence when `j.is_error`, the same grammar office.html uses.

### BE-02 — the F-01 class at the one writer that never got a fence: `/api/office/save`
`bridge/office.py:1451` (`save_doc(root, name, snapshot)` — no fence parameter),
`bridge/routers/office.py:213` · echoes **F-01** (apply had an mtime recorded and never
checked — fixed v1.5.12 with `FENCE_EPS` + `APPLY_FENCE_REFUSAL`).

Every sibling writer now fences: `oo.writeback` (409 + force), `apply_changeset`,
`undo_changeset`. `save_doc` — behind the tier-1 grid's Save and the Quick lane's sort
route — cannot even express "the file I read at open time": a write that lands between
the page's snapshot read and its save (an agent apply, a second tab, a curl) is
silently reverted, with only the once-per-day `.bak` behind it. Executed in the ledger:
A1=999 written by another writer, stale save lands, A1 reads 10, no refusal. The page's
5s `extCheck` narrows but cannot close the window (and is client-side courtesy, which
F-01's fix ruled insufficient). **Correct:** `save_doc` takes an `expect_mtime` like
`writeback`, the route passes it, the page sends `extSeen`.

### BE-03 — the F-21 fix reintroduced the orphaned-undo through a stem collision
`bridge/office.py:1649-1657` (rename's courtesy move), `office.py:331`
(`checkpoint_dir` keyed by stem), `office_ops.py:2004` (`pre_agent_for` same key) ·
echoes **F-21** (rename orphaned `.checkpoints/<stem>/` — fixed by moving the folder
with the file) and the **F-07 namespace family** (a safety copy living where real
documents can collide with it).

`.checkpoints/<stem>/` is extension-blind while three document types share the folder
(stage 3). Renaming `Budget.docx` → `Notes.docx` moves `.checkpoints/Budget/` — which
holds **Budget.xlsx's** checkpoint stack and pre-agent copy — to `Notes/`. The
spreadsheet's Undo then refuses with *"there is no checkpoint for that change any more —
the stack keeps the last 10 per workbook"*: a false sentence blaming pruning for what is
an orphaned stack, F-21's exact symptom. Executed in the ledger end to end.
**Correct:** key the checkpoint namespace by stem+type (or full name), and move it only
on a rename of the SAME document.

---

## WATCH — fine today, one step from breaking

* **W-01 · writeback's fence is caller-optional** — `oo.writeback(..., expect_mtime=None)`
  silently skips the fence (`bridge/oo.py:350`), and `oo.html:842` sends `?mtime=` only
  when `openedMtime !== null`. Every current caller supplies it; the first future caller
  that forgets gets an unfenced Save with no warning. F-01 class. *Correct:* refuse (or
  loudly log) a writeback with no fence rather than treating None as "don't check".
* **W-02 · ship.sh's per-package glob is one subdirectory from repeating itself** —
  `cp "$ROOT/bridge/$_pkg"/*.py` (`scripts/ship.sh:113`) ships `core/` and `routers/`
  flat. The comment says why, but the day either package grows a subpackage the snapshot
  silently loses it — and a stray `bridge/core/panel/assets/` directory already exists
  (empty, unreferenced) as the first tremor. Flat-glob class (the v1.5.15 near-miss).
* **W-03 · ~/.hermes is a shared home waiting for its Unsloth moment** — config, the
  path-guard plugin, sessions and the MCP schema cache all live in
  `${HERMES_HOME:-$HOME/.hermes}` (`scripts/start_component.sh:1214,1313`,
  `bridge/core/hermescfg.py:55`) and nothing sets `HERMES_HOME` to `data/`. The v0.20.6
  attempt already proved the cache in that home can be poisoned; a standalone Hermes
  install (the exact Unsloth scenario, v1.5.16–17) would share every one of those files.
  The runbook's standing rule — a vendored component never shares a home with a
  standalone install of the same upstream — has not been applied to Hermes.
* **W-04 · the runner will execute a foreign app's llama-server** —
  `bridge/routers/models.py:710-717` falls back to Jan's and LM Studio's home
  directories for the binary. Unsloth class (foreign-app state under our feet) crossed
  with the wrong-oracle class: our probe-auth contract was pinned against OUR b10662,
  and a foreign build of a different vintage re-opens exactly the version-drift the
  b10662 401 regression demonstrated. *Correct:* say on the card which binary is
  serving, or refuse the fallback with the install command.
* **W-05 · motdeck.yaml has two line-level writers and unquoted scalars** —
  `bridge/core/yamlset.py:20,55` writes `model: {value}` unquoted (a value containing
  `: ` or a leading YAML special would change meaning), and `scripts/flip_installed.py`
  edits the same file with no shared lock. Sum-over-text-adjacent (a writer that can
  store a value whose parsed type/meaning differs from what was handed in). Safe for
  every current id shape.
* **W-06 · aider.html hardcodes the ap-cmd bug's exact shape** — `button.primary{…
  color:#171420}` (`bridge/panel/aider.html:39`): near-black ink hardcoded on a
  cream-filled control instead of `var(--bg)`, the very pattern fixed in v1.5.13
  (office.html's equivalent uses the token). Harmless only while aider.html stays
  single-theme and outside the theme-pack axis.
* **W-07 · the new doc/slides badges are outside the token axis** —
  `office.html:419-420` (`.tbadge.doc{color:#7aa2f7}`, `.tbadge.slides{color:#e0af68}`,
  landed v1.5.19). Neither the light theme block nor any theme pack can reach them;
  hardcoded-color class, in the one page that otherwise re-themes.
* **W-08 · extraction-window end anchors in test_audio_drop.js** — windows like
  `swift.slice(swift.indexOf('func maybeReloadStaleHermes'), swift.indexOf('func
  retryIfFailed'))` (lines 351, 408, 453) silently widen to the rest of the file if the
  END anchor function is renamed — the office_grid negative-scope class one notch
  milder (failures would be loud but misattributed, not silent; start anchors are
  guarded by positive presence checks).

## REVIEW — judgment calls

* **R-01 · office.html's resize handles overhang adjacent panes** — `#rail-resize
  {right:-5px}` / `#ai-resize{left:-5px}`, 9px wide, `z-index:6`
  (`office.html:296-299`): the same overlay family that made ＋ New unclickable in the
  panel (fixed v1.5.13 with a measured elementFromPoint pass, whose write-up sits in
  index.html:500-503). Today the overhang only shaves ~4px slivers off the grid edge;
  worth the same elementFromPoint pass at minimum pane widths before it earns a rating.
* **R-02 · the tier-1 grid and menu bar are a hardcoded light surface** —
  `office.html:435-461,606-631` (`#gt`, `#gridbar`, `#menubar`: `#fff`, `#181818`,
  `#dcdcdc`, `#1a73e8`…). Reads as the deliberate white-document ruling (the D3 seam,
  the Google-style bar), matching the editor's own white sheet — but unlike studio's
  no-override exception it was never ratified in writing, so a theme-pack QA pass will
  keep re-finding it.

## Classes swept clean (a clean sweep is information)

1. **camelCase getattr/dict-read (the Hermes class)** — first-party Python has no
   pydantic-object attribute reads of wire-cased names. `office.py`'s
   `getattr(fill,"patternType")` / `showGridLines` are openpyxl's real attribute names;
   the snapshot's camelCase keys are our own schema on both ends; our MCP server is
   hand-written wire-dict JSON-RPC and writes `isError` correctly
   (`office_mcp.py:456`). Hermes wire reads are pinned by the dual-tag contract mirrors.
2. **WKWebView dialog no-ops** — zero live `confirm()`/`prompt()`; the one `alert()`
   (`index.html:5942`) is a browser-only bonus AFTER feed + console fallbacks, with the
   gotcha documented in place. The two-step arm→confirm idiom is used everywhere else.
3. **Unbounded collision loops (F-18 class)** — `add_sheet` is suffix-inside-budget and
   bounded (`office_ops.py:1533-1541`), `_sheet_names` dedup bounded at 200 with a
   positional fallback (`office.py:1026-1031`), the two ` (n)` filename walks cap at
   n<100 (`routers/misc.py:120`, `voice.py:481`).
4. **Text-that-looks-numeric at other writers (sum-over-text class)** — music and
   sampling coerce with explicit `_as_int`/float guards incl. NaN/inf
   (`music.py:442-458`, `routers/sampling.py:219-239`); voice pin counts are `int()`ed
   at the writer (`voice.py:891`). No other writer stores user text where a consumer
   sums it.
5. **Copies taken before refusal gates (F-20 class)** — `apply_changeset` runs every
   gate before the checkpoint (pinned comment at `office_ops.py:3332`), `writeback`
   refuses before its `.bak` (`oo.py:344-370`), `save_doc` runs `require_sheet` before
   its `.bak`.
6. **Version against the wrong oracle** — `routers/version.py` checks OUR VERSION
   against OUR repo's releases/latest; `probe_onlyoffice.sh`'s latest-tag read is
   informational beside a pin; nothing anywhere reads a `package.json` version (the
   v0.20.6 trap).
7. **Vacuously-true negative test assertions (office_grid class)** — the JS suites'
   extractors throw on a missing anchor (`test_office_grid.js:46-79` and kin), and the
   appsrc seam carries the both-ways directory fence from v1.5.15. Only the W-08 end-
   anchor nuance survives.
8. **pyvenv.cfg / symlinked-python (ops class)** — no script symlinks a python; every
   venv use checks `-x` on the real `bin/python` first. The only `ln -sf` is model-file
   aliasing in the music scripts, already pinned by `test_music_lane.py:730`.

## Honest limits

* Page findings (BE-01, W-06, W-07, R-01) are source-verified against the served files
  and the bridge's frame mapper, not driven in a live WKWebView — BE-01's repro is a
  source-level probe by necessity (the defect is a missing renderer branch), with the
  bridge-side mapping and office.html control pinned around it.
* The sweep is text+execution over first-party code; vendor-side echoes of the same
  classes (e.g. other missed `mcp_field` sites) are out of scope by the task's fence.
* `app/main.swift` was swept via the existing suites' pins and greps (dialog delegates,
  timers, tab tables); no swiftc run was performed.
* W-03 assumes no standalone Hermes exists on the machine today; that was not probed.

*Nothing was fixed. Existing files untouched; the two files named above are the only
writes.*
