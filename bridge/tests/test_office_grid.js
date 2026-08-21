/* LOFFICE TIER 1 — the plain-DOM grid (2026-08-21)
 *
 * WHY THIS FILE EXISTS. LOffice failed three times on a Mac none of us can reach, and
 * every suspect was inside ~11 MB of third-party UMD the page could not open without.
 * The answer was to stop betting the tab on it: TIER 1 is a grid built from plain DOM
 * that needs nothing but the served document, and TIER 2 (Univer) is an opt-in upgrade
 * that is allowed to fail.
 *
 * This file guards the half that must never break:
 *
 *   1. THE CELL MODEL. Tier 1 edits the bridge's own IWorkbookData snapshot in place,
 *      so what it writes goes straight through bridge/office.py's reverse mapper into
 *      a real .xlsx. A wrong `t`, a lost `s`, or a stringly-typed number here is a
 *      silently wrong workbook, not an error — so the decision table is executed.
 *   2. THE RENDER PLAN. A workbook may declare 5000x500. Laying 2.5 M table cells out
 *      hangs the tab, which is a worse failure than the one being fixed.
 *   3. THE TIER WIRING. That there is no external script tag in the document at all;
 *      that the Univer bundles load on demand IN ORDER; that a failed upgrade puts the
 *      working grid back; and that saving routes by the tier that owns the document.
 *
 * Run: node bridge/tests/test_office_grid.js
 */
// ⚠️ deliberately NOT 'use strict': a direct eval() in strict mode gets its own scope,
// so `eval(grab('colName'))` would define the function and immediately throw it away.
// Sloppy mode is what makes the extract-and-execute pattern work at all.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'office.html'), 'utf8');

let pass = 0;
const fails = [];
function check(name, cond) {
  if (cond) { pass++; } else { fails.push(name); }
}
function eq(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) { pass++; } else { fails.push(`${name}  (got ${a}, want ${b})`); }
}

// ── the extractor ────────────────────────────────────────────────────────────
// String/comment/template aware, so an apostrophe in a comment cannot truncate a
// function body and leave a test that passes by measuring nothing. (That exact defect
// was found in this repo's own harness once; it does not get to happen twice.)
function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in office.html');
  const stack = [];
  let depth = 0, prev = '';
  for (let j = html.indexOf('{', at); j < html.length; j++) {
    const c = html[j], top = stack[stack.length - 1], bs = prev === '\\';
    const t = top && top.t;
    if (t === 'sq' || t === 'dq') {
      if (!bs && c === (t === 'sq' ? "'" : '"')) stack.pop();
    } else if (t === 'tpl') {
      if (!bs && c === '`') stack.pop();
      else if (!bs && c === '$' && html[j + 1] === '{') { stack.push({ t: 'itp', d: depth }); j++; }
    } else {
      if (c === '/' && html[j + 1] === '/') { j = html.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && html[j + 1] === '*') { j = html.indexOf('*/', j) + 1; if (j < 1) break; prev = '/'; continue; }
      if (c === "'") stack.push({ t: 'sq' });
      else if (c === '"') stack.push({ t: 'dq' });
      else if (c === '`') stack.push({ t: 'tpl' });
      else if (c === '{') depth++;
      else if (c === '}') {
        if (t === 'itp' && depth === top.d) stack.pop();
        else if (--depth === 0) return html.slice(at, j + 1);
      }
    }
    prev = bs ? '' : c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

// Constants are READ OUT OF THE PAGE, never restated here: a value changed in the page
// must not keep passing against a stale copy in the test.
function num(name) {
  const m = html.match(new RegExp('\\b' + name + '\\s*=\\s*(\\d+)'));
  if (!m) throw new Error('constant ' + name + ' not found in office.html');
  return parseInt(m[1], 10);
}
const CV_STRING = num('CV_STRING'), CV_NUMBER = num('CV_NUMBER'), CV_BOOLEAN = num('CV_BOOLEAN');
const TIER1_MAX_CELLS = num('TIER1_MAX_CELLS');
const TIER1_MIN_ROWS = num('TIER1_MIN_ROWS'), TIER1_MIN_COLS = num('TIER1_MIN_COLS');
const TIER1_MAX_COLS = num('TIER1_MAX_COLS');

eq('the CellValueType enums match bridge/office.py (1/2/3)',
   [CV_STRING, CV_NUMBER, CV_BOOLEAN], [1, 2, 3]);

let snap = null;                       // the page's module-level document
eval(grab('colName'));
eval(grab('sheetIds'));
eval(grab('cellAt'));
eval(grab('putCell'));
eval(grab('valueText'));
eval(grab('displayText'));
eval(grab('editText'));
eval(grab('parseInput'));
eval(grab('usedExtent'));
eval(grab('planView'));

// ══ 1. column names ══════════════════════════════════════════════════════════
// A1 notation is the one thing every spreadsheet user can check by eye, so an
// off-by-one at the 26 boundary would be visible and wrong on every workbook.
[[0, 'A'], [1, 'B'], [25, 'Z'], [26, 'AA'], [27, 'AB'], [51, 'AZ'], [52, 'BA'],
 [701, 'ZZ'], [702, 'AAA']].forEach(([i, want]) => {
  eq(`colName(${i}) === ${want}`, colName(i), want);
});

// ══ 2. the cell model ════════════════════════════════════════════════════════
// Typed text → a Univer cell. This table IS the contract with bridge/office.py's
// `_write_cell`: `f` becomes a formula, `v`+`t` become a typed value, and a cell that
// comes back null is DELETED from cellData.
const P = [
  ['hello',      null, { v: 'hello', t: CV_STRING }, 'plain text'],
  ['12.5',       null, { v: 12.5, t: CV_NUMBER },    'a decimal is a NUMBER, not text'],
  ['7',          null, { v: 7, t: CV_NUMBER },       'an integer'],
  ['-3',         null, { v: -3, t: CV_NUMBER },      'a negative'],
  ['.5',         null, { v: 0.5, t: CV_NUMBER },     'a leading-dot decimal'],
  ['-0.25',      null, { v: -0.25, t: CV_NUMBER },   'a negative decimal'],
  ['=B2+B3',     null, { f: '=B2+B3' },              'a formula is carried as `f`'],
  ['=SUM(A1:A9)', null, { f: '=SUM(A1:A9)' },        'a function call is still a formula'],
  ['true',       null, { v: true, t: CV_BOOLEAN },   'a boolean, case-insensitively'],
  ['FALSE',      null, { v: false, t: CV_BOOLEAN },  '…either case'],
  ['007',        null, { v: '007', t: CV_STRING },   'a leading zero stays TEXT — it is an id far more often than a number'],
  ['-007',       null, { v: '-007', t: CV_STRING },  '…negative too'],
  ['1e5',        null, { v: '1e5', t: CV_STRING },   'exponent notation stays text: Number() would swallow a typo silently'],
  ['0x10',       null, { v: '0x10', t: CV_STRING },  'hex stays text for the same reason'],
  ['1 2',        null, { v: '1 2', t: CV_STRING },   'a number with a space is text'],
  ['',           null, null,                          'an empty cell with no style is REMOVED'],
  [null,         null, null,                          'a null input is an empty cell'],
  [undefined,    null, null,                          'an undefined input is an empty cell'],
  ['0',          null, { v: 0, t: CV_NUMBER },        'zero is a number, not an empty cell'],
];
P.forEach(([text, prev, want, why]) => {
  eq('parseInput: ' + why, parseInput(text, prev), want);
});

// STYLE SURVIVAL is the half a naive implementation loses: typing a new number into a
// bold red cell must not strip the bold red, because the style is the only thing in
// the cell that the user cannot retype.
eq('parseInput keeps the previous style on a new value',
   parseInput('9', { v: 1, t: CV_NUMBER, s: { bl: 1 } }), { s: { bl: 1 }, v: 9, t: CV_NUMBER });
eq('…on a formula too',
   parseInput('=A1', { v: 1, s: 'style-id-7' }), { s: 'style-id-7', f: '=A1' });
eq('…and CLEARING a styled cell keeps the style but drops the value',
   parseInput('', { v: 'x', t: CV_STRING, s: { bg: { rgb: '#ff0' } } }), { s: { bg: { rgb: '#ff0' } } });
eq('…while clearing an unstyled cell removes it entirely',
   parseInput('', { v: 'x', t: CV_STRING }), null);
check('a style id of the empty string still counts as a style (falsy but present)',
      JSON.stringify(parseInput('', { s: '' })) === JSON.stringify({ s: '' }));

// ── what a cell SHOWS ──
eq('displayText of a string', displayText({ v: 'hi', t: CV_STRING }), 'hi');
eq('displayText of a number', displayText({ v: 12.5, t: CV_NUMBER }), '12.5');
eq('displayText of a boolean is TRUE/FALSE, the spreadsheet convention',
   displayText({ v: true, t: CV_BOOLEAN }), 'TRUE');
eq('…and false', displayText({ v: false, t: CV_BOOLEAN }), 'FALSE');
eq('displayText of a FORMULA is its own text — tier 1 has no formula engine and '
   + 'inventing one would be worse than saying so',
   displayText({ f: '=B2+B3', v: 19.5, t: CV_NUMBER }), '=B2+B3');
eq('displayText of an empty cell', displayText(null), '');
eq('displayText of {} is empty, not "undefined"', displayText({}), '');
eq('valueText of Univer rich text reads the dataStream',
   valueText({ body: { dataStream: 'rich\r\n' } }, CV_STRING), 'rich');
eq('valueText of an unknown object is empty rather than [object Object]',
   valueText({ nope: 1 }, CV_STRING), '');
eq('editText is the display text — the display IS the source in this tier',
   editText({ f: '=A1' }), displayText({ f: '=A1' }));

// ── the round trip a user actually performs: type it, read it back ──
[['hello', CV_STRING], ['12.5', CV_NUMBER], ['=A1+A2', undefined],
 ['TRUE', CV_BOOLEAN]].forEach(([typed]) => {
  eq(`typing ${typed} and reading it back gives the same text`,
     displayText(parseInput(typed, null)), typed === 'TRUE' ? 'TRUE' : typed);
});

// ══ 3. cellData bookkeeping ══════════════════════════════════════════════════
// The nested {row: {col: cell}} shape is the bridge's, and an empty row left behind
// after a delete would ship a `{"3":{}}` into every save.
const sh = { cellData: {} };
putCell(sh, 0, 0, { v: 'a', t: CV_STRING });
putCell(sh, 0, 1, { v: 2, t: CV_NUMBER });
eq('putCell writes {row:{col:cell}} with STRING keys',
   sh.cellData, { '0': { '0': { v: 'a', t: 1 }, '1': { v: 2, t: 2 } } });
eq('cellAt reads it back', cellAt(sh, 0, 1), { v: 2, t: CV_NUMBER });
eq('cellAt of an empty cell is null', cellAt(sh, 9, 9), null);
eq('cellAt of a missing sheet is null', cellAt(null, 0, 0), null);
putCell(sh, 0, 0, null);
eq('putCell(null) deletes the cell', sh.cellData, { '0': { '1': { v: 2, t: 2 } } });
putCell(sh, 0, 1, null);
eq('…and removes the row once it is empty, so no {"0":{}} ships in a save',
   sh.cellData, {});
const sh2 = {};
putCell(sh2, 1, 1, { v: 'x', t: CV_STRING });
check('putCell creates cellData when a sheet has none',
      sh2.cellData && sh2.cellData['1'] && sh2.cellData['1']['1'].v === 'x');
const sh3 = { cellData: 'not an object' };
putCell(sh3, 0, 0, { v: 1, t: CV_NUMBER });
check('putCell repairs a junk cellData rather than throwing',
      sh3.cellData && sh3.cellData['0'] && sh3.cellData['0']['0'].v === 1);
check('cellAt refuses a non-object cell (a workbook is third-party JSON)',
      cellAt({ cellData: { '0': { '0': 'nope' } } }, 0, 0) === null);

// ══ 4. sheet order ═══════════════════════════════════════════════════════════
eq('sheetIds follows sheetOrder',
   sheetIds({ sheetOrder: ['b', 'a'], sheets: { a: {}, b: {} } }), ['b', 'a']);
eq('…and appends a sheet the order forgot, so a workbook can never open with a '
   + 'sheet that is unreachable',
   sheetIds({ sheetOrder: ['a'], sheets: { a: {}, z: {} } }), ['a', 'z']);
eq('…and drops an order entry with no sheet behind it',
   sheetIds({ sheetOrder: ['a', 'ghost'], sheets: { a: {} } }), ['a']);
eq('…and tolerates a junk sheetOrder',
   sheetIds({ sheetOrder: 'nope', sheets: { a: {} } }), ['a']);
eq('…and an absent workbook', sheetIds(null), []);

// ══ 5. the render plan ═══════════════════════════════════════════════════════
// A workbook may declare 5000x500. The cap is what stops the tab hanging, which would
// be a worse failure than the blank grid this whole rebuild exists to abolish.
let p = planView({ cellData: {} });
check('an empty sheet still gets a usable canvas of cells',
      p.rows >= TIER1_MIN_ROWS && p.cols >= TIER1_MIN_COLS);
eq('…and reports an empty used range', p.used, { rows: 0, cols: 0 });

p = planView({ cellData: { '2': { '3': { v: 1 } } } });
eq('usedExtent counts the last row and column that hold data', p.used, { rows: 3, cols: 4 });
check('a small sheet is padded out, not truncated', p.rows >= TIER1_MIN_ROWS);

const wide = { cellData: {}, columnCount: 500, rowCount: 5000 };
wide.cellData['4999'] = { '499': { v: 1 } };
p = planView(wide);
check('a 5000x500 declaration is CAPPED — the tab must not be asked to lay out 2.5M cells',
      p.rows * p.cols <= TIER1_MAX_CELLS);
check('…and the column cap is honoured too', p.cols <= TIER1_MAX_COLS);
check('…while the plan still reports the TRUE used extent, so the note can say what '
      + 'is being hidden', p.used.rows === 5000 && p.used.cols === 500);

eq('usedExtent tolerates junk row/column keys',
   usedExtent({ cellData: { 'x': { '0': { v: 1 } }, '1': { 'y': { v: 1 } } } }),
   { rows: 0, cols: 0 });
eq('usedExtent tolerates a non-object row', usedExtent({ cellData: { '0': 5 } }),
   { rows: 0, cols: 0 });
eq('usedExtent has no sheet to measure', usedExtent(null), { rows: 0, cols: 0 });
eq('usedExtent extends to cover a MERGE that reaches past the data',
   usedExtent({ cellData: { '0': { '0': { v: 1 } } },
                mergeData: [{ startRow: 0, startColumn: 0, endRow: 5, endColumn: 7 }] }),
   { rows: 6, cols: 8 });
eq('…and ignores a junk merge entry',
   usedExtent({ cellData: { '0': { '0': { v: 1 } } }, mergeData: [null, 'x'] }),
   { rows: 1, cols: 1 });

// ══ 6. TIER WIRING — the structural promises ═════════════════════════════════
// ⚠️ THE ONE THAT MATTERS MOST. The previous build put 10.5 MB of classic script and a
// render-blocking <link> in the document, and a stylesheet that never resolves blocks
// every script AFTER it — which is exactly "the head beacon fired and nothing else ever
// did". Neither is representable now: the served document has no external subresource
// at all, so it cannot be blocked by one.
const HEAD = html.split('</head>')[0];
// comments necessarily TALK about link and script tags to explain why there are none
const strip = s => s.replace(/<!--[\s\S]*?-->/g, '');
check('the document contains NO external script tag — tier 1 is the served document',
      !/<script[^>]*\bsrc=/.test(strip(html)));
check('…and NO external stylesheet in <head>: a pending render-blocking <link> blocks '
      + 'every script that follows it, which IS the reported symptom',
      !/<link\b/.test(strip(HEAD)));
check('…and nothing in <head> but the beacon and our own inline CSS',
      strip(HEAD).indexOf('<script>') > 0 && strip(HEAD).indexOf('<style>') > 0
      && !/<img|<iframe|@import/.test(strip(HEAD)));

// The bundles now load on demand, and their ORDER is the thing a reader could get
// wrong and only discover in a browser. It is data now, so it can be read.
const VLIST = html.match(/const VENDOR = \[([\s\S]*?)\];/);
check('the vendor bundles are declared as a list, not scattered through the code', !!VLIST);
const VORDER = VLIST ? [...VLIST[1].matchAll(/'([^']*\.js)'\]/g)].map(m => m[1]) : [];
eq('…and there are six of them', VORDER.length, 6);
check('react and react-dom load before Univer (they are peer globals)',
      VORDER.findIndex(u => u.endsWith('/react.production.min.js'))
        < VORDER.findIndex(u => u.endsWith('presets.umd.js'))
      && VORDER.findIndex(u => u.endsWith('/react-dom.production.min.js'))
        < VORDER.findIndex(u => u.endsWith('presets.umd.js')));
check('rxjs loads before Univer (peer dep)',
      VORDER.findIndex(u => u.endsWith('rxjs.umd.min.js'))
        < VORDER.findIndex(u => u.endsWith('presets.umd.js')));
check('the sheets preset loads after the presets runtime',
      VORDER.findIndex(u => u.endsWith('presets.umd.js'))
        < VORDER.findIndex(u => u.endsWith('preset-sheets-core.umd.js')));
check('the locale loads last', VORDER[VORDER.length - 1].endsWith('en-US.js'));
check('every bundle is served from our own /assets mount — no runtime CDN',
      VORDER.every(u => u.startsWith('/assets/vendor/')));
check('they load SEQUENTIALLY, so the order is a fact rather than a hope and the '
      + 'progress line can name the file that is arriving',
      /for \(let i = 0; i < VENDOR\.length; i\+\+\) \{\s*await loadScript/.test(html));
check('…and each load reports BOTH outcomes plus a timeout, so a stall is not '
      + 'indistinguishable from a hang', /s\.onload =/.test(html) && /s\.onerror =/.test(html)
      && /ASSET_TIMEOUT_MS/.test(html) && /'asset-timeout'/.test(html));
// ⚠️ The stylesheet is the ONE asset that is fetched and not waited for. A page stuck
// behind a stylesheet is the exact failure this rebuild exists to make impossible, and
// the css only styles tier-2 chrome — a grid with plain chrome beats no grid.
const LV = grab('loadVendor');
check('the tier-2 stylesheet is injected…',
      /rel = 'stylesheet'/.test(LV) && /VENDOR_CSS/.test(LV));
check('…but deliberately NOT awaited', !/await[\s\S]{0,120}stylesheet/.test(LV));
check('…and reports itself either way',
      /l\.onload = \(\) => bx\('asset-ok'/.test(LV)
      && /l\.onerror = \(\) => bx\('asset-error'/.test(LV));
check('…exactly once per page (a second upgrade attempt must not stack <link> tags)',
      /cssAsked/.test(LV) && /cssAsked = true/.test(LV));

// The upgrade is reversible. This is the whole promise of the two-tier design: a
// failure of the optional half may not cost the working half.
const UP = grab('upgrade');
check('upgrade() un-hides the tier-2 container BEFORE mounting into it (Univer measures '
      + 'its container at mount; a 0x0 box is a permanently blank grid)',
      UP.indexOf("el('sheet').classList.add('on')") < UP.indexOf('mount(snap)')
      && UP.indexOf('requestAnimationFrame') < UP.indexOf('mount(snap)'));
check('…and a failed load leaves the page on tier 1 with the grid still shown',
      /catch \(e\) \{[\s\S]*?richLoading = false;[\s\S]*?rich-fail/.test(UP));
check('…and a failed MOUNT puts the grid straight back',
      UP.indexOf("el('gridwrap').classList.remove('off')") > UP.indexOf('const ok ='));
check('…and only a success flips the mode',
      UP.lastIndexOf("mode = 'univer'") > UP.indexOf('const ok ='));
check('the failure message says the grid still works rather than only naming the error',
      /plain grid is still working/.test(UP));

// Saving must ask the tier that owns the document. Tier 1 IS the snapshot; Univer owns
// it once mounted, and reading the stale `snap` after an upgrade would silently save
// the pre-upgrade workbook over the user's edits.
const SS = grab('snapshotToSave');
check('saving reads the facade in univer mode and the snapshot in grid mode',
      /mode === 'univer'/.test(SS) && /return snap;/.test(SS));
check('…using save() with the deprecated getSnapshot() alias as fallback',
      /wb\.save \? wb\.save\(\) : wb\.getSnapshot\(\)/.test(SS));
check('…and commits a half-typed cell first, so ⌘S while editing saves what is on '
      + 'screen rather than the value before the keystroke',
      /activeElement/.test(SS) && /commit\(act\)/.test(SS));

// One place decides which tier draws a workbook, so the two can never both think they
// own the document.
const SW = grab('showWorkbook');
check('showWorkbook is the only tier decision point, and it falls back to the grid '
      + 'when the rich editor is wanted but cannot mount',
      /richWanted && richLoaded && mount\(snap\)/.test(SW) && /mode = 'grid'/.test(SW));

// Editing is delegated, not per-cell: 20 000 cells x 3 closures is 60 000 closures that
// a re-render would leak.
check('the grid uses delegated listeners on the table, not per-cell handlers',
      (html.match(/el\('gt'\)\.addEventListener/g) || []).length >= 3
      && !/td\.onclick\s*=/.test(html));
check('Enter/Tab/Escape are handled; the ARROW keys are deliberately left to the caret '
      + '(there is no way to tell "next cell" from "editing text" inside a '
      + 'contenteditable, and hijacking them would make cells uneditable)',
      /k === 'Enter'/.test(html) && /k === 'Tab'/.test(html) && /k === 'Escape'/.test(html)
      && !/ArrowDown|ArrowRight/.test(html));
// ⚠️ REGRESSION FENCE FOR A DATA-CORRUPTING DEFECT. A contenteditable puts the caret
// where you clicked, so clicking a cell holding `10` and typing `99` produced `9910` —
// the typed value INSERTED into the old one, silently, and then saved into the .xlsx.
// Found by driving the real page; no unit test can see a caret.
check('focusing a cell SELECTS its contents, so typing replaces the value the way '
      + 'every spreadsheet does instead of splicing into it',
      /function selectCell\(/.test(html) && /selectNodeContents\(td\)/.test(html)
      && /removeAllRanges\(\)/.test(html)
      && grab('selectCell').includes('addRange'));
check('…and it is called from the focus handler, not from a click handler (a second '
      + 'click inside an already-focused cell must still position the caret)',
      /td\.textContent = editText\(cell\);\s*\/\/[^\n]*\n\s*selectCell\(td\);/.test(html)
      || /td\.textContent = editText\(cell\);[\s\S]{0,80}selectCell\(td\);/.test(html));
check('a commit compares against the PREVIOUS text, so merely focusing a cell can '
      + 'never mark the workbook dirty',
      /const was = editText\(prev\);/.test(html) && /if \(now === was\)/.test(html));
check('…and normalises the non-breaking spaces contenteditable inserts, so a save '
      + 'cannot put an invisible character into somebody data',
      /\\u00a0| /.test(html.split('const now = td.textContent')[1].slice(0, 60)));

// ══ 7. the boot trace ════════════════════════════════════════════════════════
// Every stage the page can be in has a beacon, because the entire evidence available
// from the real Mac is what reaches the bridge log.
['script-start', 'boot-inline', 'dom-ready', 'tier1-ready', 'grid-render', 'files-ok',
 'files-fail', 'open-start', 'open-ok', 'open-fail', 'save-ok', 'save-fail',
 'create-fail', 'import-fail', 'auto-open', 'landed',
 'rich-start', 'rich-loaded', 'rich-ready', 'rich-fail',
 'pane-resize', 'pane-reset', 'rail-open', 'rail-collapse',
 'asset-ok', 'asset-error', 'asset-timeout', 'selfcheck-pass', 'selfcheck-fail',
 'mount-start', 'mount-fail', 'mount-raf', 'mount-settled', 'page-error', 'rejection',
 'watchdog',
 // the menu bar and the start screen, added at 2026-08-21j
 'menu-open', 'menu-row', 'home-start', 'home-render', 'find-open', 'find-close',
 'zoom', 'add-sheet', 'template'].forEach(stage => {
  check(`the page beacons '${stage}'`, html.includes("'" + stage + "'"));
});
check('the boot runs immediately when the document is already parsed — this script is '
      + 'at the END of the body, and waiting for a DOMContentLoaded that has already '
      + 'FIRED would hang the boot forever',
      /document\.readyState === 'loading'/.test(html)
      && /\} else \{\s*boot\(\);/.test(html));
check('the tier-1 watchdog is SHORT — there is no 11 MB download to be patient about '
      + 'any more, so a slow boot is a fault rather than a slow network',
      num('WATCHDOG_MS') <= 15000);
check('the per-asset timeout is generous — the biggest bundle is ~7 MB on a cold start',
      num('ASSET_TIMEOUT_MS') >= 30000);

// ══ 8. PANE GEOMETRY — resize, collapse, persistence ═════════════════════════
// THE REPORT THIS GUARDS: "the borders are not dragable for screensize, still feels
// unintuitive… feels off." Both side panes were fixed pixel widths and the file rail
// collapsed to display:none — no handle, and nothing left on screen to bring it back.
//
// The arithmetic is EXECUTED rather than grepped, because every branch of it is a way
// the page can end up with a pane you cannot see or cannot use: a junk stored value,
// a drag past either end, a persisted width that survives a reload as something else.
const CSS = html.match(/<style>([\s\S]*?)<\/style>/)[1];

const RAIL_W_DEF = num('RAIL_W_DEF'), RAIL_W_MIN = num('RAIL_W_MIN'), RAIL_W_MAX = num('RAIL_W_MAX');
const AI_W_DEF = num('AI_W_DEF'), AI_W_MIN = num('AI_W_MIN'), AI_W_MAX = num('AI_W_MAX');
eq('the clamps are the ones the brief asked for — rail 160-420, AI 260-560',
   [RAIL_W_MIN, RAIL_W_MAX, AI_W_MIN, AI_W_MAX], [160, 420, 260, 560]);
check('…and both defaults sit inside their own range',
      RAIL_W_DEF >= RAIL_W_MIN && RAIL_W_DEF <= RAIL_W_MAX
      && AI_W_DEF >= AI_W_MIN && AI_W_DEF <= AI_W_MAX);

// The CSS default and the JS default are two copies of one number. If they drift, a
// first-ever load paints one width and the first drag jumps to another.
const cssRailDef = (CSS.match(/--rail-w:\s*(\d+)px/) || [])[1];
const cssAiDef = (CSS.match(/--ai-w:\s*(\d+)px/) || [])[1];
eq('the CSS pane defaults agree with the JS ones — a mismatch would make the very '
   + 'first drag jump', [Number(cssRailDef), Number(cssAiDef)], [RAIL_W_DEF, AI_W_DEF]);

// ── the pure clamp, over everything a stored value can actually be ──
eval(grab('clampW'));
[
  ['a sane width is kept', [300, 160, 420, 236], 300],
  ['…and rounded, because a fractional CSS pixel is a blurry 1px seam', [300.6, 160, 420, 236], 301],
  ['below the minimum clamps UP rather than being refused', [20, 160, 420, 236], 160],
  ['above the maximum clamps DOWN', [9999, 160, 420, 236], 420],
  ['the boundaries themselves are allowed', [160, 160, 420, 236], 160],
  ['…both of them', [420, 160, 420, 236], 420],
  ['a stored string is a number, because localStorage only ever returns strings',
   ['312', 160, 420, 236], 312],
  ['junk falls back to the DEFAULT — never to 0, which is the bug being fixed',
   ['nonsense', 160, 420, 236], 236],
  ['…so does NaN', [NaN, 160, 420, 236], 236],
  ['…so does null', [null, 160, 420, 236], 236],
  ['…so does undefined', [undefined, 160, 420, 236], 236],
  ['…so does an empty string, which Number() would otherwise call 0', ['', 160, 420, 236], 236],
  ['…so does a negative', [-40, 160, 420, 236], 236],
  ['…so does zero', [0, 160, 420, 236], 236],
  ['…so does Infinity', [Infinity, 160, 420, 236], 236],
].forEach(([label, args, want]) => eq('clampW: ' + label, clampW.apply(null, args), want));

// ── the setters + the drag, executed against a stub DOM ──
(function () {
  const props = {}, store = {}, beacons = [];
  const doc = { documentElement: { style: { setProperty: (k, v) => { props[k] = v; } } },
                body: { classList: { _s: new Set(),
                                     add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
                                     toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); },
                                     contains(c) { return this._s.has(c); } } } };
  const localStorage = { getItem: k => (k in store ? store[k] : null),
                         setItem: (k, v) => { store[k] = String(v); } };
  const nodes = {
    'files': { getBoundingClientRect: () => ({ left: 0, right: 236 }) },
    'ai': { getBoundingClientRect: () => ({ left: 900, right: 1234 }) },
    'rail-resize': mkHandle(), 'ai-resize': mkHandle(),
  };
  function mkHandle() {
    return { on: [], off: [], cap: 0, rel: 0,
             setPointerCapture() { this.cap++; }, releasePointerCapture() { this.rel++; },
             addEventListener(t) { this.on.push(t); }, removeEventListener(t) { this.off.push(t); } };
  }
  const document = doc;                                   // shadows the real global name
  const el = id => nodes[id];
  const bx = (s, d) => beacons.push(s + ':' + d);
  let railW, aiW, paneDrag;
  // the constants the setters close over
  const LS_RAIL = "harness-office-rail", LS_RAIL_W = "harness-office-rail-w",
        LS_AI_W = "harness-office-ai-w";
  eval(grab('setRailW')); eval(grab('setAiW')); eval(grab('loadPaneWidths'));
  eval(grab('paneHandle')); eval(grab('paneDown')); eval(grab('paneMove')); eval(grab('paneUp'));
  eval(grab('paneReset')); eval(grab('railSetOpen')); eval(grab('railIsOpen'));

  // the storage KEYS, asserted as literals: a renamed key silently forgets every
  // width the user ever set, and looks exactly like "it did not persist".
  eq('the persistence keys are the four harness-office-* ones',
     [LS_RAIL, LS_RAIL_W, LS_AI_W], ['harness-office-rail', 'harness-office-rail-w',
                                     'harness-office-ai-w']);
  check('…and the AI panel keeps the key it already shipped with, so an existing '
        + 'collapse preference is not thrown away by this change',
        html.includes("'harness-office-ai'"));

  // setters write the variable the stylesheet reads
  setRailW(300, false);
  eq('setRailW writes --rail-w', props['--rail-w'], '300px');
  check('…and does NOT persist when told not to — a pointermove fires per frame and '
        + 'must not write localStorage 60 times a second',
        store[LS_RAIL_W] === undefined);
  setRailW(300, true);
  eq('…and persists the CLAMPED value when it is asked to', store[LS_RAIL_W], '300');
  setAiW(5000, true);
  eq('setAiW clamps to its own maximum, not the rail\'s', props['--ai-w'], AI_W_MAX + 'px');
  eq('…and stores what it actually applied, never what it was handed',
     store[LS_AI_W], String(AI_W_MAX));

  // load: a stored width comes back; a missing one is the default; junk is the default
  delete store[LS_RAIL_W]; delete store[LS_AI_W];
  loadPaneWidths();
  eq('a first-ever load lands on the defaults',
     [props['--rail-w'], props['--ai-w']], [RAIL_W_DEF + 'px', AI_W_DEF + 'px']);
  store[LS_RAIL_W] = '390'; store[LS_AI_W] = '270';
  loadPaneWidths();
  eq('…and a later load restores exactly what was stored',
     [props['--rail-w'], props['--ai-w']], ['390px', '270px']);
  store[LS_RAIL_W] = 'boom';
  loadPaneWidths();
  eq('…while a corrupt key gives the default rather than a 0-wide pane',
     props['--rail-w'], RAIL_W_DEF + 'px');

  // ── a real drag, event by event ──
  store[LS_RAIL_W] = String(RAIL_W_DEF);
  const h = nodes['rail-resize'];
  h.on.length = 0; h.off.length = 0;
  paneDown('rail', { preventDefault() {}, pointerId: 1 });
  check('pointerdown takes pointer capture, so the drag survives the cursor leaving '
        + 'the 9px strip', h.cap === 1);
  eq('…and subscribes to move/up/cancel — cancel included, or a system gesture '
     + 'strands the page mid-drag', h.on.sort(), ['pointercancel', 'pointermove', 'pointerup']);
  check('…and marks the body, which is what turns off text selection and stops the '
        + 'grid swallowing the pointer stream', doc.body.classList.contains('office-dragging'));
  paneMove({ clientX: 340 });
  eq('dragging right widens the rail to the cursor', props['--rail-w'], '340px');
  paneMove({ clientX: 10 });
  eq('…dragging past the left end stops at the minimum instead of collapsing',
     props['--rail-w'], RAIL_W_MIN + 'px');
  paneMove({ clientX: 5000 });
  eq('…and past the right end stops at the maximum', props['--rail-w'], RAIL_W_MAX + 'px');
  eq('nothing was written to storage during the drag itself',
     store[LS_RAIL_W], String(RAIL_W_DEF));
  paneUp({ pointerId: 1 });
  eq('pointerup persists the width that is actually on screen',
     store[LS_RAIL_W], String(RAIL_W_MAX));
  eq('…and unsubscribes all three, so a second drag cannot double-handle',
     h.off.sort(), ['pointercancel', 'pointermove', 'pointerup']);
  check('…releases the capture', h.rel === 1);
  check('…and clears the body flag', !doc.body.classList.contains('office-dragging'));
  paneMove({ clientX: 200 });
  eq('a stray pointermove after the drag ended changes nothing',
     props['--rail-w'], RAIL_W_MAX + 'px');

  // the AI side grows the other way: its right edge is fixed, so a LOWER clientX is
  // a WIDER panel. Getting this backwards is the classic mirrored-divider bug.
  const ah = nodes['ai-resize'];
  paneDown('ai', { preventDefault() {}, pointerId: 2 });
  paneMove({ clientX: 900 });
  eq('the AI panel measures from its RIGHT edge — 1234-900 = 334', props['--ai-w'], '334px');
  paneMove({ clientX: 800 });
  check('…so dragging LEFT makes it wider, not narrower', Number(props['--ai-w'].replace('px','')) > 334);
  paneUp({ pointerId: 2 });
  check('…and its release persists to the AI key, never the rail one',
        store[LS_AI_W] === String(clampW(1234 - 800, AI_W_MIN, AI_W_MAX, AI_W_DEF)));

  // double-click reset
  paneReset('rail'); paneReset('ai');
  eq('double-click resets a divider to the shipped width — a pane dragged somewhere '
     + 'silly should not need a pixel-perfect drag to undo',
     [props['--rail-w'], props['--ai-w']], [RAIL_W_DEF + 'px', AI_W_DEF + 'px']);
  eq('…and the reset is persisted, not just applied',
     [store[LS_RAIL_W], store[LS_AI_W]], [String(RAIL_W_DEF), String(AI_W_DEF)]);

  // collapse, both directions, and the beacon pair
  beacons.length = 0;
  railSetOpen(false, 'button');
  check('collapsing the rail sets the class', doc.body.classList.contains('railoff'));
  eq('…persists it', store[LS_RAIL], '0');
  check('…and says so', beacons.indexOf('rail-collapse:button') >= 0);
  check('railIsOpen agrees with the class', railIsOpen() === false);
  railSetOpen(true, 'tab');
  check('…and reopening puts everything back',
        !doc.body.classList.contains('railoff') && store[LS_RAIL] === '1'
        && railIsOpen() === true && beacons.indexOf('rail-open:tab') >= 0);
})();

// ── the markup and the stylesheet ──
check('both panes carry a drag handle',
      /id="rail-resize"/.test(html) && /id="ai-resize"/.test(html));
check('…each inside its own pane, so it can be absolutely positioned against it '
      + 'without adding a flex child to #body',
      html.indexOf('id="rail-resize"') > html.indexOf('<aside id="files">')
      && html.indexOf('id="rail-resize"') < html.indexOf('<main id="mid">')
      && html.indexOf('id="ai-resize"') > html.indexOf('<aside id="ai">'));
check('…and both say what they do on hover, including the double-click',
      (html.match(/title="Drag to resize · double-click to reset"/g) || []).length === 2);
check('the handles are wired to pointerdown and dblclick, not to mousedown — pointer '
      + 'events are what make setPointerCapture available at all',
      /rail-resize'\)\.onpointerdown/.test(html) && /ai-resize'\)\.onpointerdown/.test(html)
      && /rail-resize'\)\.ondblclick/.test(html) && /ai-resize'\)\.ondblclick/.test(html));
check('the panes take their width from the CSS variables',
      /#files\{[^}]*width:var\(--rail-w/.test(CSS) && /#ai\{[^}]*width:var\(--ai-w/.test(CSS));
check('…and neither is a fixed pixel width any more — that was the literal report',
      !/#files\{[^}]*width:236px/.test(CSS) && !/#ai\{[^}]*width:334px/.test(CSS));
check('a handle needs touch-action:none or a trackpad drag is stolen by scrolling',
      /#rail-resize,#ai-resize\{[^}]*touch-action:none/.test(CSS));
check('while dragging, the grid stops taking pointer events — otherwise a drag that '
      + 'crosses a contenteditable cell puts the caret in it',
      /body\.office-dragging #gridwrap[^}]*pointer-events:none/.test(CSS));

// COLLAPSE, and the bug in the shipped build: the rail vanished to display:none.
check('a collapsed rail is a 34px reopener, NOT display:none — a pane that leaves '
      + 'nothing behind can only be brought back by remembering a button',
      /body\.railoff #files\{width:34px\}/.test(CSS)
      && !/body\.railoff #files\{display:none\}/.test(CSS));
check('…and the AI panel collapses to the same 34px, so the page has one collapse '
      + 'grammar rather than two', /body\.aioff #ai\{width:34px\}/.test(CSS));
check('both reopeners are REAL MARKUP hidden by a class, like everything else here',
      /<button id="rail-tab"/.test(html) && /<button id="ai-tab"/.test(html)
      && /#rail-tab\{display:none\}/.test(CSS) && /#ai-tab\{display:none\}/.test(CSS));
check('both panes carry a matching chevron collapse in their own header',
      /id="rail-hide"[^>]*>‹</.test(html) && /id="ai-hide"[^>]*>›</.test(html));
check('a collapsed pane hides its own divider — there is nothing left to resize',
      /body\.railoff #rail-resize\{display:none\}/.test(CSS)
      && /body\.aioff #ai-resize\{display:none\}/.test(CSS));
check('the boot restores the rail state alongside the AI one',
      /localStorage\.getItem\(LS_RAIL\) !== '0'/.test(grab('boot'))
      && /railSetOpen\(railWant, 'boot'\)/.test(grab('boot')));
check('…and the widths are applied BEFORE anything is drawn into the panes',
      /loadPaneWidths\(\);[\s\S]{0,600}railSetOpen\(railWant/.test(grab('boot')));
check('the rail toggle goes through railSetOpen — a raw classList.toggle would flip '
      + 'the pane without remembering it, which is how a preference gets lost',
      /btn-rail'\)\.onclick = \(\) => railSetOpen\(!railIsOpen\(\)/.test(html)
      && !/classList\.toggle\('railoff'\)/.test(html));
// ⚠️ THIS ONE WAS ALREADY RED BEFORE 2026-08-21j AND IS REPAIRED HERE, NOT WEAKENED.
// It pinned `const toggleNew = () => { … railSetOpen(true, 'new') … }`, a shape the
// page has not had since the name row learned its second verb: `toggleNew` is a
// one-liner into nameRow(), and nameRow() is what opens the rail (with its own mode as
// the reason string). The invariant is unchanged — New must open the rail, because the
// name box lives in it — so it is pinned where it now lives.
check('…and so does New, which needs the rail open because the name box lives in it',
      /const toggleNew = \(\) => nameRow\('create'\)/.test(html)
      && /railSetOpen\(true, mode\);/.test(grab('nameRow')));
check('the landing beacon reports the geometry it landed on, so "it opened tiny" is '
      + 'answerable from the log', /rail=' \+ \(railIsOpen\(\)/.test(html));

// ── keyboard + affordances ──
check('⌘S still saves', /toLowerCase\(\) === 's'[\s\S]{0,80}save\(\)/.test(html));
check('⌘\\ toggles the rail — the shortcut every editor with a sidebar uses',
      /ev\.key === '\\\\'[\s\S]{0,160}railSetOpen\(!railIsOpen\(\), 'key'\)/.test(html));
check('Esc dismisses the message box, which otherwise can only be replaced by the '
      + 'next message', /ev\.key === 'Escape' && el\('msg'\)\.classList\.contains\('on'\)/.test(html));
check('…and Esc does NOT preventDefault, so the name box and the grid keep their own '
      + 'Escape meanings', !/ev\.key === 'Escape'[^\n]*preventDefault/.test(html));
// ⚠️ ALSO ALREADY RED BEFORE 2026-08-21j: it pinned `'Enter') create()`, and that box
// stopped being create-only when it learned Rename. `nameRowGo()` is the verb it is
// currently showing, which is the behaviour that actually matters.
check('Enter in the name box does whichever verb the box is showing',
      /new-name'\)\.onkeydown[\s\S]{0,120}'Enter'\) nameRowGo\(\)/.test(html));
check('the row actions are a real click target rather than two bare words — a ~9px '
      + 'hit box next to a DELETE was the affordance bug',
      /\.lnk\{[^}]*padding:4px 7px/.test(CSS));
check('…and they have their own hover ground, not just a colour change',
      /\.lnk:hover\{[^}]*background:var\(--card2\)/.test(CSS));
check('…while the armed delete stays red on hover instead of turning gold like an '
      + 'ordinary link', /\.lnk\.arm:hover\{color:var\(--bad\)/.test(CSS));
check('the active file row is unmistakable — ground AND a gold border',
      /\.frow\.on\{background:var\(--card\);border-color:var\(--gold\)\}/.test(CSS));
check('…and every row answers the pointer', /\.frow:hover\{background:var\(--card\)\}/.test(CSS));

// ── the header ──
check('every header control is one height from ONE token, so they cannot drift apart '
      + 'again', /--ctl-h:\s*\d+px/.test(CSS)
      && /:where\(#hdr\) button\{height:var\(--ctl-h\)/.test(CSS)
      && /\.pill\{[^}]*height:var\(--ctl-h\)/.test(CSS));
// ⚠️ THIS ASSERTION CHANGED SHAPE AT 2026-08-21j, HONESTLY, BECAUSE THE LAYOUT DID.
// It used to pin `p-state` ABOVE the hairline, in the header's status group. The save
// state and the tier are no longer in the header at all: they sit to the RIGHT OF THE
// MENU ROW, which is where every office application puts them ("All changes saved in
// Drive"). What the old check was really about — that the row reads as groups rather
// than a line of unrelated controls — is pinned below instead, as the hairline sitting
// between the title group and the actions.
check('the header still separates the title group from the things that change the '
      + 'document, with the hairline between them',
      /<span class="hsep"><\/span>/.test(html)
      && html.indexOf('id="doctitle"') < html.indexOf('class="hsep"')
      && html.indexOf('class="hsep"') < html.indexOf('id="btn-rich"'));
check('the action group is ordered Rich · Import · New · Save, with Save the only '
      + 'filled button',
      html.indexOf('id="btn-rich"') < html.indexOf('id="btn-import"')
      && html.indexOf('id="btn-import"') < html.indexOf('id="btn-new2"')
      && html.indexOf('id="btn-new2"') < html.indexOf('id="btn-save"')
      && /id="btn-save" class="primary"/.test(html));
check('row 1 carries the DOCUMENT TITLE, and it is a control — clicking a title '
      + 'renames the document in every office app there is',
      /<button id="doctitle"/.test(html)
      && /doctitle'\)\.onclick = \(\) => \{ if \(current && !busy\) nameRow\('rename'\)/.test(html));
check('…and paint() keeps it truthful rather than leaving the placeholder up',
      /t\.textContent = current \|\| 'no workbook open'/.test(grab('paint')));

// ══ THE LANDING ══════════════════════════════════════════════════════════════
// THE BUG THIS GUARDS. LOffice booted perfectly — tier-1 ready in 4-7 ms, bridge fine,
// zero errors — and then sat on 'No spreadsheets yet.' with 'Pick a spreadsheet on the
// left, or make a new one.' in the main pane. A spreadsheet app that opens on no
// spreadsheet reads as broken however healthy its boot log is. autoOpen is the answer,
// and it is executed here rather than grepped, because every branch of it is a way the
// landing can go wrong: opening nothing, opening the wrong file, or creating a second
// workbook on every single page load.
(function () {
  const calls = [];
  let current = null, filesOk = true, roundtripOk = true, files = [];
  function bx(stage, detail) { calls.push(['bx', stage, String(detail === undefined ? '' : detail)]); }
  async function openDoc(name) { calls.push(['open', name]); current = name; }
  async function create() { calls.push(['create']); current = 'Untitled.xlsx'; return current; }
  function renderHome() { calls.push(['home']); }
  // grab() anchors on `function <name>(`, which inside `async function autoOpen(`
  // yields a body WITHOUT its async keyword — so it is put back here rather than
  // silently defining a sync function whose awaits are a syntax error.
  eval('async ' + grab('autoOpen'));

  function run(state) {
    calls.length = 0;
    current = state.current || null;
    filesOk = state.filesOk !== false;
    roundtripOk = state.roundtripOk !== false;
    files = state.files || [];
    let done = false;
    autoOpen().then(() => { done = true; });
    // autoOpen only ever awaits our own already-resolved stubs, so one microtask drain
    // settles it; the flag proves that rather than assuming it.
    return new Promise(r => setImmediate(() => r({ done, calls: calls.slice() })));
  }

  const cases = [
    // ⚠️ THIS CASE CHANGED AT 2026-08-21j AND IT IS A DELIBERATE BEHAVIOUR CHANGE, not
    // a relaxation. An empty library used to auto-create `Untitled.xlsx`, because the
    // alternative at the time was landing on one centred sentence. The alternative now
    // is the START SCREEN, whose first element is a Blank card — so the reason for the
    // auto-create ("never a dead end") is served without putting a file in somebody's
    // documents folder that they never asked for. Google's own home does exactly this.
    ['an EMPTY library lands on the START SCREEN and creates nothing — a start screen '
     + 'with a Blank card in it is not a dead end',
     { files: [] }, ['bx:auto-open:start screen', 'home']],
    ['a NON-empty library opens the newest instead of making another one',
     { files: [{ name: 'newest.xlsx' }, { name: 'older.xlsx' }] },
     ['bx:auto-open:newest.xlsx', 'open:newest.xlsx']],
    ['a workbook already open is left exactly as it is',
     { current: 'mine.xlsx', files: [{ name: 'other.xlsx' }] },
     ['bx:auto-open:skipped: already open']],
    ['a file list that never arrived is NOT answered by creating a workbook — the '
     + 'listing failure is already on screen and a second failure would bury it',
     { filesOk: false, files: [] }, ['bx:auto-open:skipped: the file list did not load']],
    ['a bridge with no openpyxl creates nothing — the install banner is the message '
     + 'that matters, and a doomed create would push it off screen',
     { roundtripOk: false, files: [] },
     ['bx:auto-open:skipped: no .xlsx round-trip on this bridge']],
    ['…and it still creates nothing when there ARE files but no round-trip',
     { roundtripOk: false, files: [{ name: 'a.xlsx' }] },
     ['bx:auto-open:skipped: no .xlsx round-trip on this bridge']],
  ];

  (async () => {
    for (const [label, state, want] of cases) {
      const { done, calls: got } = await run(state);
      const flat = got.map(c => c[0] === 'bx' ? 'bx:' + c[1] + ':' + c[2] : c.join(':'));
      eq(label, flat, want);
      check(label + ' — and it settles', done);
    }
    // The one ordering fact the whole thing rests on: files[0] is the NEWEST, because
    // office.list_docs sorts by mtime descending. If that ever flips, the landing would
    // silently open the oldest workbook and nothing else would notice.
    check('autoOpen takes files[0] — pinned to list_docs sorting newest-first',
          /files\[0\]\.name/.test(grab('autoOpen')));
    check('autoOpen creates NOTHING at all any more — a workbook appears because '
          + 'somebody clicked Blank, never because a page loaded',
          !/create\(/.test(grab('autoOpen')));
    check('…and the Blank card is the thing that does create one, with no name of its '
          + 'own, so the bridge still owns the default',
          /el\('h-blank'\)\.onclick = newBlank/.test(html)
          && /await create\(\)/.test(grab('newBlank'))
          && !/create\(['"]/.test(grab('newBlank')));
    check('boot() runs the landing, and only AFTER the file list is in',
          /await loadFiles\(\);[\s\S]{0,200}await autoOpen\(\);/.test(grab('boot')));

    // ── create(): the empty name used to be a silent no-op ──
    const src = grab('create');
    check('create() no longer bails on an empty name — that early return WAS the dead '
          + 'end: no request, no message, no beacon, nothing at all',
          !/if\s*\(\s*!name/.test(src));
    check('…while the busy guard, which is a real one, stays', /if\s*\(busy\)\s*return/.test(src));
    check('create() sends whatever is in the box, empty included, and lets the bridge '
          + 'choose the default name', /JSON\.stringify\(\{ name: name \}\)/.test(src));
    check('a create that throws on the wire beacons create-fail too — the message box '
          + 'was the very thing that was broken the first time round',
          /catch[\s\S]{0,400}bx\('create-fail', 'threw/.test(src));
    check('a non-2xx with an unparseable body still reports a reason rather than '
          + 'throwing past the handler', /the bridge answered/.test(src));
    check('loadFiles reports whether it worked, so the landing can refuse to act on a '
          + 'listing it never got', /filesOk = true/.test(grab('loadFiles'))
          && /return true;/.test(grab('loadFiles')));
    check('…and records the round-trip verdict from the bridge, not from a guess',
          /roundtripOk = j\.roundtrip !== false/.test(grab('loadFiles')));

    /* ══ 9. THE MENU BAR ═══════════════════════════════════════════════════════
       THE REPORT THIS GUARDS, verbatim: "The design of the new/file etc is so bad.
       It's not even on the main strip as all office/sheet docs have it… See how
       extensive it is, how everything is in the white strip and uniform."

       So the three things asserted here are location, breadth and honesty — and the
       last one is the one that keeps the other two from becoming a lie: a menu bar is
       only worth having if every row in it either works or says why not. */
    const STAMP = (html.match(/<meta name="harness-build" content="([^"]+)">/) || [])[1] || '';
    // ⚠️ A LITERAL, AND IT HAS TO BE BUMPED BY HAND EVERY SLICE — which is exactly what
    // it is for (it fails loudly when someone changes the page and forgets the stamp).
    // Bumped to k by the AI-actions slice, which owns the AI panel and the stamp with
    // it; nothing else in this file changed.
    eq('the build stamp is this slice\'s', STAMP, 'loffice-2026-08-21k');
    check('…and the static fallback banner carries the SAME one, so "is the bridge '
          + 'serving what I shipped?" is answerable by eye, with no console',
          html.indexOf('<code>' + STAMP + '</code>') > 0);

    // ── the strip exists, is light, and is a strip ──
    check('there IS a menu bar, and it is its own row under the title — not a button '
          + 'floating in the app chrome', /<nav id="menubar">/.test(html)
          && html.indexOf('<nav id="menubar">') > html.indexOf('</header>'));
    check('it is a LIGHT surface, flush with the sheet — "everything in the white strip"',
          /#menubar\{[^}]*background:#fff/.test(CSS));
    // ⚠️ THE DELIBERATE DECISION, PINNED SO IT CANNOT BE UNDONE BY ACCIDENT: neither
    // theme axis repaints the strip or the dropdowns. A desktop office app in dark mode
    // still frames a white page, and this bar belongs to the DOCUMENT. Overruling it is
    // a one-line addition here plus one in the sheet — which is the point of pinning it.
    check('…in BOTH themes: neither the light palette nor the studio axis repaints the '
          + 'strip or the dropdowns',
          !/data-theme="light"\]\)\s*#menubar/.test(CSS)
          && !/data-chrome="studio"\]\)\s*#menubar/.test(CSS)
          && !/data-theme="light"\]\)\s*\.mpop/.test(CSS)
          && !/data-chrome="studio"\]\)\s*\.mpop/.test(CSS)
          && !/data-theme="light"\]\)\s*\.mtop/.test(CSS));
    check('…and the dropdowns are the same light surface',
          /\.mpop\{[^}]*background:#fff/.test(CSS));
    check('the dropdowns are NOT clipped: an ancestor with overflow:hidden would hide '
          + 'every absolutely-positioned menu, which is a whole-feature failure',
          /#menus\{[^}]*\}/.test(CSS) && !/#menus\{[^}]*overflow/.test(CSS));
    check('a menu label is text, not a chip — mixed case, sans, no border until hover',
          /\.mtop\{[^}]*font:13px/.test(CSS) && /\.mtop:hover\{/.test(CSS)
          && !/\.mtop\{[^}]*text-transform/.test(CSS));

    // ── eight menus, in Google's order ──
    const BAR = ['File', 'Edit', 'View', 'Insert', 'Format', 'Data', 'AI', 'Help'];
    const TOPS = ['btn-file', 'btn-edit', 'btn-view', 'btn-insert', 'btn-format',
                  'btn-data', 'btn-ai', 'btn-help'];
    const POPS = ['filemenu', 'm-edit', 'm-view', 'm-insert', 'm-format', 'm-data',
                  'm-ai', 'm-help'];
    TOPS.forEach((id, i) => {
      check('the bar carries ' + BAR[i],
            new RegExp('<button class="mtop" id="' + id + '">' + BAR[i] + '<').test(html));
    });
    POPS.forEach(id => check('…and ' + id + ' is a real dropdown in the markup',
                             new RegExp('id="' + id + '" class="mpop"').test(html)
                             || new RegExp('<div id="' + id + '" class="mpop">').test(html)));
    check('the labels appear in that order in the document, so the strip reads the way '
          + 'the transcription does', TOPS.every((id, i) =>
            i === 0 || html.indexOf('id="' + id + '"') > html.indexOf('id="' + TOPS[i - 1] + '"')));
    check('the engine is DATA, not eight copies of one function — adding a menu is '
          + 'adding a pair to two arrays',
          /const MENUS = \[/.test(html) && /const MTOPS = \[/.test(html));
    // the JS arrays and the markup are two lists of the same eight things
    const jsPops = (html.match(/const MENUS = \[([\s\S]*?)\];/) || [, ''])[1]
      .match(/'([^']+)'/g).map(s => s.replace(/'/g, ''));
    const jsTops = (html.match(/const MTOPS = \[([\s\S]*?)\];/) || [, ''])[1]
      .match(/'([^']+)'/g).map(s => s.replace(/'/g, ''));
    eq('…and the engine\'s dropdown list is exactly the markup\'s', jsPops, POPS);
    eq('…and its label list is exactly the markup\'s', jsTops, TOPS);

    // ── THE HONESTY RULE, and it is the important one ──
    const ROWS = [...html.matchAll(/<button class="mi" id="(mi-[\w-]+)"([^>]*)>/g)]
      .map(m => ({ id: m[1], attrs: m[2] }));
    check('the bar is EXTENSIVE — Google Sheets carries ~120 items across ten menus, '
          + 'and a menu bar\'s credibility is breadth', ROWS.length >= 55);
    const ZLIST = ((html.match(/const ZOOMS = \[([^\]]*)\]/) || [, ''])[1])
      .split(',').map(s => s.trim()).filter(Boolean);
    check('the zoom steps are declared as data', ZLIST.length >= 3);
    function wired(id) {
      if (new RegExp("mi\\('" + id + "'").test(html)) return true;
      // the zoom rows are wired by a loop over ZOOMS rather than one call each
      return /^mi-z\d+$/.test(id) && ZLIST.indexOf(id.slice(4)) >= 0
             && /ZOOMS\.forEach\(z => mi\('mi-z' \+ z/.test(html);
    }
    const dead = ROWS.filter(r => /^\s+disabled\b/.test(r.attrs));
    const live = ROWS.filter(r => !/^\s+disabled\b/.test(r.attrs));
    check('most of the bar is LIVE, not a wall of grey', live.length >= 35);
    eq('EVERY live row is wired to something. A row that looks live and does nothing '
       + 'is the whole complaint, so this is the assertion that matters most',
       live.filter(r => !wired(r.id)).map(r => r.id), []);
    eq('…and EVERY disabled row carries a REAL reason in its own title, so a greyed '
       + 'row explains itself instead of merely refusing',
       dead.filter(r => !/title="[^"]{25,}"/.test(r.attrs)).map(r => r.id), []);
    eq('…and no row is both wired and disabled — there is no third state',
       dead.filter(r => wired(r.id)).map(r => r.id), []);
    check('the shortcut column is right-aligned and dimmer, the way every menu on the '
          + 'reference screenshots draws it',
          /\.mpop \.mk\{[^}]*margin-left:auto/.test(CSS) && /\.mpop \.mk\{[^}]*color:#/.test(CSS));
    check('groups are separated by a hairline rather than listed flat',
          /\.mpop \.msep\{/.test(CSS) && (html.match(/<div class="msep">/g) || []).length >= 8);
    check('a toggle row states what it IS, with a tick, rather than what clicking would do',
          /\.mpop \.mtick\{/.test(CSS) && /<span class="mtick">/.test(html)
          && /function tick\(id, on\)/.test(html));
    check('a DISABLED row\'s tick greys with it, so a ticked-but-dead row cannot read '
          + 'as active', /\.mpop \.mi:disabled \.mtick\{/.test(CSS));

    // ── the pinned contract with the other suite ──
    check('btn-rail → btn-file → p-file order is preserved (test_office_ai.js pins it, '
          + 'and it is why the two status readouts moved to the menu row rather than '
          + 'staying in the header)',
          html.indexOf('id="btn-rail"') < html.indexOf('id="btn-file"')
          && html.indexOf('id="btn-file"') < html.indexOf('id="p-file"'));
    check('…and both readouts really are on the menu row, after the menus',
          html.indexOf('id="p-file"') > html.indexOf('<nav id="menubar">')
          && html.indexOf('id="p-file"') > html.indexOf('id="btn-help"')
          && /<span class="mstat" id="p-file">/.test(html)
          && /<span class="mstat" id="p-state">/.test(html));
    check('the File dropdown keeps its exact two pinned visibility rules',
          /#filemenu\{display:none\}/.test(CSS) && /#filemenu\.on\{display:flex\}/.test(CSS));
    check('…and no id-scoped rule styles its ROWS any more, which is what made it the '
          + 'one menu of eight that looked different',
          !/#filemenu \.mi\{/.test(CSS) && !/#filemenu \.mk\{/.test(CSS));

    // ── keyboard + hover, the behaviour that makes it a BAR ──
    check('click to open, then HOVER to switch — without the second half it is eight '
          + 'unrelated popovers', /onmouseenter = \(\) => \{ if \(openMenu >= 0/.test(html));
    check('← → walk the bar and ↑ ↓ walk the open menu',
          /ArrowRight'\) \{ ev\.preventDefault\(\); menuStep\(1\)/.test(html)
          && /ArrowLeft'\) \{ ev\.preventDefault\(\); menuStep\(-1\)/.test(html)
          && /ArrowDown'\) \{ ev\.preventDefault\(\); menuMove\(1\)/.test(html)
          && /ArrowUp'\) \{ ev\.preventDefault\(\); menuMove\(-1\)/.test(html));
    check('…and the walk SKIPS disabled rows rather than focusing one that will refuse',
          /=> !n\.disabled/.test(grab('menuRows')));
    check('Escape closes an open menu — the File one where it already was, the other '
          + 'seven in the new listener, so there is exactly one owner per case',
          /Escape' && el\('filemenu'\)\.classList\.contains\('on'\)/.test(html)
          && /k === 'Escape' && openMenu > 0/.test(html));
    check('an outside mousedown closes the whole BAR, not just the File wrapper — a '
          + 'click on another label must switch menus, not read as "outside"',
          /const w = el\('menubar'\) \|\| el\('filewrap'\)/.test(html));
    check('⌘B / ⌘I / ⌘U preventDefault, because inside a contenteditable the browser '
          + 'would otherwise insert RICH TEXT bold that textContent throws away and '
          + 'that could never reach the .xlsx',
          /k === 'b'\) \{ ev\.preventDefault\(\); fmtToggle\('bl'\)/.test(html)
          && /k === 'i'\) \{ ev\.preventDefault\(\); fmtToggle\('it'\)/.test(html)
          && /k === 'u'\) \{ ev\.preventDefault\(\); fmtToggle\('ul', \{ s: 1 \}\)/.test(html));
    check('…and they are refused outright in the rich editor rather than writing into a '
          + 'snapshot Univer is no longer reading', /if \(!t1ok\(\)\) return;/.test(html)
          && /mode === 'grid'/.test(grab('t1ok')));
    check('the beacon budget is respected: the bar reports its FIRST open, not one per '
          + 'label the cursor crosses (hover-switching would have spent all 80)',
          /if \(!menuTraced\) \{/.test(html) && /menuTraced = true;/.test(html));
    check('…and every deliberate row click IS reported, which is the line that answers '
          + '"I clicked Format → Bold and nothing happened"',
          /bx\('menu-row', id\)/.test(grab('mi')));

    // ── ⌂ HOME: the bug fix ──
    const START = grab('goStart'), HOME = grab('goHome');
    check('⌂ LOffice home stays INSIDE LOffice — it closes the document and shows the '
          + 'start screen, and it can no longer switch the whole app to another tab',
          !/switchTab/.test(START) && !/messageHandlers/.test(START)
          && /mi_close\(\)/.test(START));
    check('…while the way OUT is its own row at the bottom, still using the shell\'s '
          + 'postMessage contract', /switchTab/.test(HOME) && /id: 'mc'/.test(HOME)
          && /mi\('mi-home', goHome\)/.test(html) && /mi\('mi-start', goStart\)/.test(html));
    check('…and the two rows are labelled so nobody has to guess which is which',
          /id="mi-start">⌂ LOffice home</.test(html)
          && /id="mi-home">Back to MOT Main</.test(html));
    check('home is the LAST thing before the exit row, and the exit row is last of all',
          html.indexOf('id="mi-start"') < html.indexOf('id="mi-home"'));
    check('going home with unsaved work offers to save rather than discarding it, and '
          + 'does not go if the save failed',
          /Save & go home/.test(START) && /if \(dirty\) return;/.test(START));

    /* ══ 10. THE START SCREEN ═══════════════════════════════════════════════════
       #empty stopped being one centred sentence and became LOffice's own home, on the
       Sheets-home model: a Blank card first, then templates, then the recent list.
       It is the SAME element and the SAME `.off` class, because "no document is open"
       and "the start screen" are one state, and rendering it is EXECUTED here because
       an empty library is the case it exists for and the case that used to look broken. */
    check('the start screen is the empty state, not a second surface — same element, '
          + 'same overlay, same class', /<div id="empty">/.test(html)
          && /#empty\{[^}]*position:absolute/.test(CSS) && /#empty\.off\{display:none\}/.test(CSS));
    check('…and it can SCROLL, which a centred flex box cannot — a start screen taller '
          + 'than the pane has to be reachable',
          /#empty\{[^}]*overflow:auto/.test(CSS)
          && !/#empty\{[^}]*align-items:center/.test(CSS));
    check('it opens with "Start a new spreadsheet" and a Blank card FIRST, exactly like '
          + 'the reference home screen',
          /Start a new spreadsheet/.test(html)
          && html.indexOf('id="h-blank"') < html.indexOf('id="h-budget"')
          && /<div class="hcards">/.test(html));
    check('…and the template cards are generated from the routes we already have, so '
          + 'there is no template file to ship and nothing new on the bridge',
          /const TPL = \{/.test(html) && /await create\(\)/.test(grab('newFromTemplate'))
          && /await save\(\)/.test(grab('newFromTemplate'))
          && !/fetch\(/.test(grab('newFromTemplate')));
    check('…with a bolded header row, which also makes a template a live demonstration '
          + 'that styles round-trip', /cell\.s = \{ bl: 1 \}/.test(grab('newFromTemplate')));
    check('the recent list and the file rail are drawn from ONE array by ONE call, so '
          + 'they cannot disagree about what exists',
          (grab('renderFiles').match(/renderHome\(\)/g) || []).length >= 2);
    check('…including the EMPTY branch, which is the one the start screen is for',
          /renderHome\(\);\s*\/\/[^\n]*empty/.test(html));

    // renderHome, executed against a stub DOM
    (function () {
      function mkNode(tag) {
        const n = { tag: tag || 'div', children: [], attrs: {}, className: '',
                    textContent: '', title: '', tabIndex: -1,
                    appendChild(c) { this.children.push(c); return c; },
                    setAttribute(k, v) { this.attrs[k] = v; },
                    focus() { n.focused = true; },
                    querySelectorAll(sel) {
                      const want = String(sel).replace(/^\./, ''), out = [];
                      (function walk(x) {
                        x.children.forEach(c => {
                          if (String(c.className || '').split(' ').indexOf(want) >= 0) out.push(c);
                          walk(c);
                        });
                      })(this);
                      return out;
                    } };
        Object.defineProperty(n, 'innerHTML',
          { get() { return ''; }, set(v) { if (v === '') n.children.length = 0; } });
        return n;
      }
      const nodes = { hlist: mkNode(), hnote: mkNode(), fidelity: mkNode() };
      nodes.fidelity.textContent = 'the fidelity sentence';
      const el = id => nodes[id];
      const document = { createElement: mkNode };
      const bx = () => {};
      let files = [], filesOk = true, armed = null;
      function fmtSize(n) { return n + 'B'; }
      function fmtWhen(t) { return 'when' + t; }
      async function openDoc() {}
      function renderFiles() {}
      function remove() {}
      const HOME_MAX = num('HOME_MAX');
      eval(grab('renderHome'));
      eval(grab('homeDel'));

      const rowsOf = () => nodes.hlist.children.filter(
        c => String(c.className).split(' ').indexOf('hrow') >= 0);

      files = []; renderHome();
      eq('an empty library draws exactly one line, and it points at the Blank card '
         + 'rather than at a control somewhere else',
         nodes.hlist.children.map(c => c.className), ['hempty']);
      check('…and that line names Blank',
            /Blank/.test(nodes.hlist.children[0].textContent));
      filesOk = false; renderHome();
      check('…while a bridge that never answered says THAT instead of pretending the '
            + 'library is empty', /bridge did not answer/.test(nodes.hlist.children[0].textContent));
      filesOk = true;

      files = [{ name: 'newest.xlsx', size_bytes: 10, modified: 2 },
               { name: 'older.xlsx', size_bytes: 20, modified: 1 }];
      renderHome();
      eq('two files give two rows, newest first (list_docs sorts them, the page does not '
         + 're-sort and cannot disagree)',
         rowsOf().map(r => r.children[0].textContent), ['newest.xlsx', 'older.xlsx']);
      eq('…each row carrying its name, its meta, and the two actions',
         rowsOf()[0].children.map(c => c.className), ['hn', 'hm', 'lnk', 'lnk']);
      eq('…and the actions are download and delete, in that order — never delete first',
         rowsOf()[0].children.slice(2).map(c => c.textContent), ['download', 'delete']);
      check('a row is keyboard-reachable, so Enter opens the selected file',
            rowsOf()[0].tabIndex === 0 && rowsOf()[0].attrs.role === 'button'
            && typeof rowsOf()[0].onkeydown === 'function');
      check('…and it says what it does on hover', /^Open /.test(rowsOf()[0].title));

      armed = 'older.xlsx'; renderHome();
      eq('a delete armed anywhere shows as armed HERE too, because both lists read the '
         + 'same variable', rowsOf()[1].children[3].textContent, 'sure?');
      check('…and only that one row is armed',
            rowsOf()[0].children[3].textContent === 'delete');
      armed = null;

      files = [];
      for (let i = 0; i < HOME_MAX + 6; i++) files.push({ name: 'f' + i + '.xlsx', size_bytes: 1, modified: i });
      renderHome();
      eq('a big library is capped rather than drawing hundreds of rows', rowsOf().length, HOME_MAX);
      check('…and the note SAYS it is capped, and where the rest are',
            /most recent/.test(nodes.hnote.textContent)
            && /file list on the left/.test(nodes.hnote.textContent));
      check('…while a small one just carries the fidelity sentence',
            (function () { files = [{ name: 'a.xlsx', size_bytes: 1, modified: 1 }];
                           renderHome();
                           return nodes.hnote.textContent === 'the fidelity sentence'; })());
    })();

    // ── FIND, the one new capability ──
    check('Find scans the SHEET, not the DOM, so it can match a row that is not drawn '
          + 'yet', /cellAt\(sh, r, c\)/.test(grab('findRun'))
          && /usedExtent\(sh\)/.test(grab('findRun')));
    check('…and then GROWS the render window to reach the match, terminating even when '
          + 'the column cap is hit',
          /while \(h\.r >= viewRows\)/.test(grab('findGo'))
          && /viewCols < TIER1_MAX_COLS/.test(grab('findGo')));
    check('…is capped, so a one-letter query on a huge sheet cannot hang the tab',
          num('FIND_MAX') > 0 && /findHits\.length < FIND_MAX/.test(grab('findRun')));
    check('…says how many and where you are, and admits when a match sits under a merge',
          /' of ' \+ findHits\.length/.test(grab('findGo'))
          && /merged cell/.test(grab('findGo')));
    check('…and Enter / ⇧Enter walk the matches',
          /findGo\(ev\.shiftKey \? -1 : 1\)/.test(html));

    // ── Format: the write path, and the trap in it ──
    const SWR = grab('styleWrite');
    check('a style toggle RESOLVES the base style and writes a COPY back inline — a '
          + 'style id is shared between cells, and mutating it would bold half the '
          + 'workbook silently',
          /cellStyle\(rc\)/.test(SWR) && /for \(const k in base\) next\[k\] = base\[k\]/.test(SWR)
          && /cell\.s = next/.test(SWR));
    check('…and it banks the cell being typed into first, then RE-ARMS the edit, '
          + 'because commit() clears the flag and focusin will never fire again for a '
          + 'cell that never lost focus',
          /commitFocused\(\)/.test(SWR)
          && /act\.dataset\.editing = '1'/.test(grab('commitFocused')));
    check('…keeping the value while replacing only the style',
          /if \(prev\) for \(const k in prev\) if \(k !== 's'\)/.test(SWR));
    check('the style keys are the ones bridge/office.py::apply_style actually reads, so '
          + 'a format applied here survives a save',
          /fmtToggle\('bl'\)/.test(html) && /fmtToggle\('it'\)/.test(html)
          && /fmtToggle\('ul', \{ s: 1 \}\)/.test(html)
          && /fmtToggle\('st', \{ s: 1 \}\)/.test(html)
          && /fmtToggle\('tb', 3\)/.test(html)
          && /fmtAlign\(1\)/.test(html) && /fmtAlign\(2\)/.test(html) && /fmtAlign\(3\)/.test(html));
    check('the cell a menu acts on is the LAST FOCUSED one, never activeElement — '
          + 'clicking a menu label has already blurred the cell',
          /let lastRC = null/.test(html) && /function lastCellNow\(\)/.test(html)
          && !/document\.activeElement/.test(grab('menuPaint')));

    // ── every tier-1 write is refused in the rich editor, and SAYS so ──
    check('a tier-1 write cannot run while Univer owns the document — it would edit a '
          + 'snapshot nobody is reading and be lost at the next save',
          [grab('styleWrite'), grab('clearCell'), grab('addSheet'), grab('growRows'),
           grab('growCols')].every(f => /t1ok\(\)/.test(f)));
    check('…and the row says which of the three reasons applies rather than going grey '
          + 'in silence', /const T1_ONLY = /.test(html) && /const NO_DOC = /.test(html)
          && /const NO_CELL = /.test(html)
          && /n\.title = \(!ok && why\) \? why : ''/.test(grab('setRow')));
    check('the AI rows are guarded, because that panel belongs to another surface: they '
          + 'disable themselves instead of throwing into a page that must keep working',
          /typeof aiSetOpen === 'function'/.test(grab('aiAvail'))
          && /setRow\(id, aiAvail\(\), NO_AI\)/.test(html));

    // ── report ──
    console.log('');
    if (fails.length) {
      console.log(`${fails.length} FAILED (of ${pass + fails.length}):`);
      fails.forEach(f => console.log('  -', f));
      process.exit(1);
    }
    console.log(`loffice tier-1 grid OK — ${pass} checks passed`);
  })();
})();

