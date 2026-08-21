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
 'create-fail', 'import-fail', 'rich-start', 'rich-loaded', 'rich-ready', 'rich-fail',
 'asset-ok', 'asset-error', 'asset-timeout', 'selfcheck-pass', 'selfcheck-fail',
 'mount-start', 'mount-fail', 'mount-raf', 'mount-settled', 'page-error', 'rejection',
 'watchdog'].forEach(stage => {
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

// ── report ──
console.log('');
if (fails.length) {
  console.log(`${fails.length} FAILED (of ${pass + fails.length}):`);
  fails.forEach(f => console.log('  -', f));
  process.exit(1);
}
console.log(`loffice tier-1 grid OK — ${pass} checks passed`);
