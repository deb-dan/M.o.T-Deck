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
// A contiguous RUN of const declarations, first..last inclusive, taken verbatim out of
// the page. Added at loffice-2026-08-28d for the coercion rule, whose constants are
// regexes built over several lines — restating them here would be a second copy of the
// exact thing this test exists to pin.
function grabConsts(first, last) {
  const a = html.indexOf('const ' + first);
  const c = html.indexOf('const ' + last);
  if (a < 0 || c < 0) throw new Error('const run ' + first + '..' + last + ' not found');
  const b = html.indexOf('\n', c);
  if (b < a) throw new Error('const run ' + first + '..' + last + ' is out of order');
  // ⚠️ `const` → `var`, AND IT IS NOT COSMETIC: a `const` declared inside eval() is
  // block-scoped to the eval and does NOT leak into this module, so the functions
  // eval'd next would throw ReferenceError on every one of these names. `var` in a
  // direct sloppy-mode eval does leak, which is the same mechanism `grab`'s function
  // declarations already rely on. The VALUES are still the page's, verbatim.
  return html.slice(a, b).replace(/(^|\n)(\s*)const /g, '$1$2var ');
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
// ⚠️ THE COERCION RULE'S OWN FUNCTIONS, added at loffice-2026-08-28d. parseInput is no
// longer self-contained: it delegates "is this string a number, and in what format" to
// coerceNumeric, and the apostrophe convention to stripTextMark.
eval(grabConsts('CO_MAX_LEN', 'CO_LEADING_ZERO'));
eval(grab('stripTextMark'));
eval(grab('coDp'));
eval(grab('coPattern'));
eval(grab('coNum'));
eval(grab('coerceNumeric'));
eval(grab('textNumeric'));
eval(grab('cellFormat'));
eval(grab('mergeFormat'));
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
// ⚠️ AND SO DOES SCRIPT BODY PROSE, SINCE v1.5.25: the harness-design axis appends a
// stylesheet AT RUNTIME (bridge/panel/assets/studio-office.css, only when the key says
// so), and the block that does it has to be able to say the word "<link>" in its own
// comment. So the MARKUP check strips script bodies as well as HTML comments — what it
// is about is what the SERVED DOCUMENT contains, which for Editorial is still zero
// external subresources. bridge/tests/test_studio_office.js is what proves the runtime
// link is absent unless the design is on.
const stripJs = s => s.replace(/<script>[\s\S]*?<\/script>/g, '<script></script>');
const strip = s => stripJs(s.replace(/<!--[\s\S]*?-->/g, ''));
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

// ONE EDITOR NOW (loffice-2026-08-28a). The five checks this block replaced pinned the
// NAVIGATION to /oo-edit that 2026-08-27c introduced, and Debi's one-editor ruling
// deleted it: the editor is EMBEDDED in this page's centre column. The promises are
// unchanged in shape — a failure of the editor may not cost the working grid, and
// nothing may be a dead click — so every one of them has a successor here.
// ⚠️ The Univer bundle machinery above (VENDOR / loadVendor / mount) is RETIRED but
// still present and still pinned, because the vendored assets are still on disk and it
// is the rollback. What is asserted below is that nothing live USES it.
const UP = grab('upgrade');
check('upgrade() no longer navigates ANYWHERE — the editor is in this page',
      !/location\.href/.test(UP) && !/oo-edit/.test(UP));
check('…and no longer touches the retired Univer loader',
      !/loadVendor|mount\(snap\)|selfCheck\(\)/.test(UP));
check('…it asks the bridge whether the editor is installed FIRST, so a missing bundle '
      + 'is a sentence rather than a dead click',
      /await ooProbe\(\)/.test(UP) && /st\.installer/.test(UP) && /st\.reason/.test(UP));
check('…and refuses with a reason when there is no workbook to open',
      UP.indexOf('if (!current)') > 0
      && UP.indexOf('if (!current)') < UP.indexOf('ooProbe()'));
check('the not-installed message says the plain grid is still the editor rather than '
      + 'only naming the error', /own grid is the editor/.test(UP));
check('…and an explicit press is treated as a request to TRY AGAIN after a failure, '
      + 'not as a second dead click', /ooFailed = ''/.test(UP));

// ── THE ONE PREDICATE. This is the fork the whole restructure rests on. ──
const EA = grab('editorActive');
check('there is ONE predicate for "is the editor the editor right now", and it is a '
      + 'pure read of three flags',
      /return !!\(ooInstalled && ooReady && !!current\);/.test(EA)
      && !/document\.|\bel\(/.test(EA));
eq('…defined exactly once',
   (html.match(/function editorActive\(\)/g) || []).length, 1);
const OPC = grab('ooPaintClass');
eq('…and it reaches the DOM in exactly one place',
   (html.match(/classList\.toggle\('ooedit'/g) || []).length, 1);
check('…which is a body class, so the hide/show fork is a stylesheet rather than '
      + 'eleven paint functions each with its own if',
      /ooedit/.test(OPC) && /oowait/.test(OPC));
check('paint() calls it, so the class cannot lag the state — paint is the funnel every '
      + 'change of `current` and `dirty` already goes through',
      /ooPaintClass\(\);/.test(grab('paint')));
// The four surfaces that must get out of the editor's way, in the stylesheet, by name.
['#menubar', '#toolbar', '#findrow', '#gridwrap'].forEach(sel => {
  check('body.ooedit hides ' + sel + ' — no duplicate ribbons',
        html.includes('body.ooedit ' + sel + '{display:none}'));
});
// ⚠️ AND THE SPECIFICITY IS ASSERTED, NOT ASSUMED. `#menubar{display:flex}` and
// `#findrow.on{display:flex}` live FURTHER DOWN the same stylesheet, so a hide rule of
// equal-or-lower weight would lose and the menu bar would sit on top of the ribbon. Each
// hide rule adds a TYPE selector (`body`) on top of the id, which outranks both without
// depending on source order — and this check is what would notice if somebody
// "simplified" `body.ooedit #menubar` down to `.ooedit #menubar`.
check('…each hide rule carries the `body` type selector that makes it outrank the '
      + 'display:flex rules further down the stylesheet',
      ['#menubar', '#toolbar', '#findrow', '#gridwrap'].every(sel => {
        const rule = 'body.ooedit ' + sel + '{display:none}';
        return html.includes(rule) && !html.includes('\n  .ooedit ' + sel);
      }));
check('the interstitial grid is READ-ONLY: an edit into a snapshot the editor is about '
      + 'to replace is not offered at all',
      html.includes('body.oowait #gridwrap{pointer-events:none'));
// ⚠️ AND THE KEYBOARD, WHICH IS THE HALF A HIDDEN MENU DOES NOT COVER. ⌘B, ⌘Z and
// ⇧F11 are page-level shortcuts; hiding the menu bar does not disarm one of them.
const T1 = grab('t1ok');
check('t1ok — the gate every tier-1 verb goes through — also refuses while the editor '
      + 'owns the document, and while it is coming up',
      /!editorActive\(\)/.test(T1) && /!\(ooInstalled && ooBooting\)/.test(T1));

// ── ONE INSTANCE, KEPT ALIVE. This is the "why is it not instant like Music?" half. ──
const ST = grab('ooStart');
check('the iframe src is set at most once per page and every later file switch is a '
      + 'document SWAP through the living child',
      /ooSrcSet/.test(ST) && /ooChild\.open\(name\)/.test(ST));
check('…and the swap path is preferred, so the compiled wasm and the loaded api.js are '
      + 'not thrown away on every click in the file list',
      ST.indexOf('if (!ooSrcSet)') < ST.indexOf('ooChild.open(name)'));
check('…and it reports WHICH path ran and how long it took, so the claim is checkable '
      + 'from the boot log rather than only from a stopwatch',
      /bx\('oo-start', name \+ ' via=' \+ \(ooSrcSet \? 'swap' : 'src'\)/.test(ST));
check('closing a workbook stands the editor DOWN without tearing it down',
      /ooReady = false; ooBooting = false; ooDoc = '';/.test(grab('clearWorkbook'))
      && !/destroy\(\)/.test(grab('clearWorkbook')));

// Saving must ask whoever owns the document. The EDITOR owns it when it is up; tier 1
// IS the snapshot otherwise; and reading the stale `snap` while the editor holds the
// document would write the file as it was when the editor opened it over the user's
// edits — the single worst thing this page could do.
const SV = grab('save');
check('save() branches to the editor FIRST when the editor owns the document',
      /if \(editorActive\(\)\) \{ await ooSave\(false\); return; \}/.test(SV));
const SVC = SV.split('\n').filter(l => !l.trim().startsWith('//')).join('\n');
check('…before it reads the snapshot at all', SVC.indexOf('editorActive()') < SVC.indexOf('snapshotToSave'));
const SS = grab('snapshotToSave');
check('the tier-1/Univer read-back is unchanged for the case it still serves',
      /mode === 'univer'/.test(SS) && /return snap;/.test(SS));
check('…using save() with the deprecated getSnapshot() alias as fallback',
      /wb\.save \? wb\.save\(\) : wb\.getSnapshot\(\)/.test(SS));
check('…and commits a half-typed cell first, so ⌘S while editing saves what is on '
      + 'screen rather than the value before the keystroke',
      /activeElement/.test(SS) && /commit\(act\)/.test(SS));

// One place decides which surface draws a workbook, so two of them can never both
// think they own the document. It draws the GRID first — instant, and the honest
// interstitial — and then hands the centre over.
const SW = grab('showWorkbook');
check('showWorkbook is still the one decision point, it still falls back to the grid, '
      + 'and it is what starts (or swaps) the editor',
      /richWanted && richLoaded && mount\(snap\)/.test(SW) && /mode = 'grid'/.test(SW)
      && /ooStart\(name, 'open'\)/.test(SW));
check('…and the grid is rendered BEFORE the editor is asked for, which is what makes '
      + 'the interstitial real rather than a spinner',
      SW.indexOf('renderGrid();') < SW.indexOf('ooStart('));

// ── THE PARENT↔CHILD CONTRACT. One object each way, same-origin, no postMessage. ──
check('the host half of the contract is published BEFORE the iframe can exist, so the '
      + 'child never has to poll or retry to find it',
      /window\.LOfficeHost = \{/.test(html)
      && html.indexOf('window.LOfficeHost = {') < html.indexOf("el('ooframe').src"));
check('…it carries a contract VERSION, so a signature change is a visible one',
      /contract: 1,/.test(html.split('window.LOfficeHost = {')[1].slice(0, 200)));
check('…and it is exactly two entry points: register (the child hands its API up) and '
      + 'event (everything else)',
      /register: \(embed\) =>/.test(html) && /event: \(ev\) => ooEvent/.test(html));
check('every report to the child is guarded, so a child that throws cannot take the '
      + 'page down with it', /try \{ HOST\.event\(ev\); \}/.test(
        fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'oo.html'), 'utf8')));
const EV = grab('ooEvent');
['boot', 'ready', 'state', 'saved', 'error'].forEach(k => {
  check("ooEvent handles the '" + k + "' event", EV.includes("kind === '" + k + "'"));
});
check('the editor\'s own state event IS the page\'s dirty flag — one flag, not two',
      /if \(d !== dirty\) \{ dirty = d; paint\(\); \}/.test(EV));
check('…and a FATAL editor failure puts the working grid back and says why, rather '
      + 'than leaving a dead frame in the middle of the layout',
      /ev\.fatal/.test(EV) && /ooReady = false; ooBooting = false;/.test(EV)
      && /using its own grid/.test(EV));

// Editing is delegated, not per-cell: 20 000 cells x 3 closures is 60 000 closures that
// a re-render would leak.
check('the grid uses delegated listeners on the table, not per-cell handlers',
      (html.match(/el\('gt'\)\.addEventListener/g) || []).length >= 3
      && !/td\.onclick\s*=/.test(html));
// ⚠️ SCOPED AT 2026-08-21: this used to assert no ArrowDown/ArrowRight anywhere in the
// page, which was only true while the grid was the sole keyboard consumer. The menubar
// now navigates with arrows — wanted, and gated behind `openMenu >= 0` so it can never
// reach an editing cell — and the start screen's file rows arrow within themselves. The
// invariant that matters is pinned where it lives: the GRID's own keydown handler.
const GT_KD = (html.split("el('gt').addEventListener('keydown'")[1] || '').split('});')[0];
check('Enter/Tab/Escape are handled; the ARROW keys are deliberately left to the caret '
      + '(there is no way to tell "next cell" from "editing text" inside a '
      + 'contenteditable, and hijacking them would make cells uneditable)',
      /k === 'Enter'/.test(GT_KD) && /k === 'Tab'/.test(GT_KD) && /k === 'Escape'/.test(GT_KD)
      && !/Arrow(Down|Up|Left|Right)/.test(GT_KD)
      // …and the menubar's arrow handling exists only inside the open-menu guard
      // (the window widened at 2026-08-27b: the submenu ruling is written between the
      // guard and the ArrowRight branch it explains)
      && /if \(openMenu >= 0\) \{[\s\S]{0,900}'ArrowRight'/.test(html));
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
 // ⚠️ THE RETIRED UNIVER LOADER'S BEACONS, KEPT because loadVendor is still the
 // rollback path and still emits them. `rich-ready` / `rich-fail` went with the
 // navigation that Debi's one-editor ruling deleted; the EDITOR's own beacons are
 // asserted as their own group below, and they are what a boot log is read for now.
 'rich-start', 'rich-loaded',
 // the embedded editor (loffice-2026-08-28a)
 'oo-status', 'oo-start', 'oo-boot', 'oo-swap', 'oo-register', 'oo-saved', 'oo-error',
 'oo-reload', 'oo-snap', 'oo-not-installed', 'action-route',
 'pane-resize', 'pane-reset', 'rail-open', 'rail-collapse',
 'asset-ok', 'asset-error', 'asset-timeout', 'selfcheck-pass', 'selfcheck-fail',
 'mount-start', 'mount-fail', 'mount-raf', 'mount-settled', 'page-error', 'rejection',
 'watchdog',
 // the menu bar and the start screen, added at 2026-08-21j
 'menu-open', 'menu-row', 'home-start', 'home-render', 'find-open', 'find-close',
 'zoom', 'add-sheet', 'template',
 // the toolbar row and the submenus, added at 2026-08-27b
 'toolbar', 'toolbar-show', 'toolbar-hide', 'submenu'].forEach(stage => {
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
      /loadPaneWidths\(\);[\s\S]{0,1400}railSetOpen\(railWant/.test(grab('boot')));
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
// ⚠️ SCOPED AT 2026-08-21: the page-wide "no Escape+preventDefault on one line" sweep
// broke when the find bar arrived — ITS input legitimately preventDefaults Escape in
// its OWN keydown handler, which can only fire with focus in the find box and so steals
// nothing from the grid or the name box. What must stay true is that the WINDOW-level
// Escape branches (dismiss message, close menubar menu) never preventDefault.
check('…and Esc does NOT preventDefault, so the name box and the grid keep their own '
      + 'Escape meanings',
      /=== 'Escape' && el\('msg'\)\.classList\.contains\('on'\)\) say\(''\);/.test(html)
      && /nk === 'Escape' && openMenu > 0\) \{ menuClose\('esc'\); return; \}/.test(html));
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
      // The guard grew a VOICE at the stuck-latch fix (2026-08-29): the row IS disabled
      // in both blocked states, but a handler that can be reached at all must answer.
      /<button id="doctitle"/.test(html)
      && /doctitle'\)\.onclick = \(\) => \{[\s\S]{0,400}?busyBlock\('renaming'\)[\s\S]{0,120}?nameRow\('rename'\)/.test(html));
check('…and paint() keeps it truthful rather than leaving the placeholder up',
      // 'no workbook open' → 'no file open' at loffice-2026-08-29a: three types live
      // here now, and two of them are not workbooks.
      /t\.textContent = current \|\| 'no file open'/.test(grab('paint')));

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
    // ⚠️ WIDENED AT loffice-2026-08-28a, AND THE REASON IS THE POINT OF THE WIDENING:
    // the file list, the "is the editor installed?" probe, and the read-only stored
    // Agent-history repaint are now asked TOGETHER (one Promise.all — three small GETs
    // on the same loopback bridge, none needing another's answer), and ALL are awaited
    // before the landing. The second half is
    // not a nicety: autoOpen → showWorkbook decides whether the grid is an interactive
    // editor or a read-only interstitial, and a page that did not yet know would offer
    // an edit it was about to discard.
    check('boot() runs the landing, and only AFTER the file list, editor probe, and '
          + 'stored Agent-history repaint are all in',
          /await Promise\.all\(\[loadFiles\(\), ooProbe\(\), agentRestoreHistory\(\)\]\);[\s\S]{0,400}await autoOpen\(\);/
            .test(grab('boot')));

    // ── create(): the empty name used to be a silent no-op ──
    const src = grab('create');
    check('create() no longer bails on an empty name — that early return WAS the dead '
          + 'end: no request, no message, no beacon, nothing at all',
          !/if\s*\(\s*!name/.test(src));
    // …and at the stuck-latch fix (2026-08-29) it stopped being SILENT: a real guard
    // still refuses, but "nothing happened" is not an answer a button may give.
    check('…while the busy guard, which is a real one, stays — and now SPEAKS',
          /if \(busyBlock\('creating that file'\)\) return null;/.test(src));
    check('create() sends whatever is in the box, empty included, and lets the bridge '
          + 'choose the default name',
          // `kind` joined the body at loffice-2026-08-29a (stage 3): '' is a
          // spreadsheet, 'doc' and 'slides' are the two new start-screen cards. The
          // NAME half of this assertion is the one that matters and is unchanged.
          /JSON\.stringify\(\{ name: name, step: !!step, kind: kind \|\| '' \}\)/.test(src));
    // ⚠️ `step` ARRIVED AT loffice-2026-08-28d (live finding B2), AND IT DOES NOT WEAKEN
    // THE NEVER-CLOBBER RULING — it is how the caller SAYS which of the two meanings it
    // has. A name the USER TYPED still collides and is still refused; a TEMPLATE CARD
    // takes the ' (n)' walk, because refusing it left the card permanently dead after one
    // use with an error that offered no way forward.
    check('…and a TEMPLATE says so, so the bridge can step its name instead of refusing',
          /await create\(true\)/.test(grab('newFromTemplate')));
    check('…while newBlank still passes no flag: an empty name already takes the walk',
          !/create\(true\)/.test(grab('newBlank')));
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
    eq('the build stamp is this slice\'s', STAMP, 'loffice-2026-08-29b');
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
    // the submenu PARENT rows are the one live row shape that is deliberately not wired
    // through mi() — mi() closes the whole bar after running a row, which is right for a
    // leaf and wrong for a row whose whole job is to open something inside the menu
    const SUBROWS = [...html.matchAll(/\{ row: '(mi-[\w-]+)', pop: '(m-[\w-]+)' \}/g)]
      .map(m => ({ row: m[1], pop: m[2] }));
    function wired(id) {
      if (new RegExp("mi\\('" + id + "'").test(html)) return true;
      // the zoom rows are wired by a loop over ZOOMS rather than one call each
      if (/^mi-z\d+$/.test(id) && ZLIST.indexOf(id.slice(4)) >= 0
          && /ZOOMS\.forEach\(z => mi\('mi-z' \+ z/.test(html)) return true;
      return SUBROWS.some(s => s.row === id)
             && /row\.onclick = ev => \{ ev\.stopPropagation\(\); subGo\('open', s\.pop/.test(html);
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
    // ⚠️ RESHAPED AT 2026-08-27b, and only in the ← → half: → now ENTERS a submenu when
    // the focused row has one, and falls through to walking the bar when it does not, so
    // the old behaviour is what happens whenever submenus are not involved.
    check('← → walk the bar and ↑ ↓ walk the open menu',
          /ArrowRight'\) \{ ev\.preventDefault\(\); if \(!subEnter\(\)\) menuStep\(1\)/.test(html)
          && /ArrowLeft'\) \{ ev\.preventDefault\(\); if \(!subLeave\(\)\) menuStep\(-1\)/.test(html)
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
          && /id="mi-home">Back to MOT Deck</.test(html));
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
          /const TPL = \{/.test(html) && /await create\(true\)/.test(grab('newFromTemplate'))
          && /await save\(\)/.test(grab('newFromTemplate'))
          && !/fetch\(/.test(grab('newFromTemplate')));
    /* ⚠️ AND THE ROWS GO THROUGH THE EDITOR WHEN THE EDITOR HOLDS THE FILE (live finding
       L2, the template half of it). The tail of newFromTemplate was tier-1 — putCell into
       `snap`, then save() — and with the editor installed save() routes to ooSave(), which
       writes THE EDITOR'S document: the empty file the create route had just made. So the
       template rows went into a hidden snapshot, the file on disk stayed empty, and the
       strip reported a save. Same defect as the AI lane's create-with-data, same fix. */
    check('…and with the editor installed the rows go through ooApplyApi, after WAITING '
          + 'for the editor to hold the new file — not into a snapshot nobody is looking '
          + 'at',
          /ooWaitReady\(/.test(grab('newFromTemplate'))
          && /ooApplyApi\(/.test(grab('newFromTemplate')));
    check('…and if the editor never takes it, the template REFUSES and says the file is '
          + 'empty, rather than reporting rows it did not write',
          /were not written/.test(grab('newFromTemplate')));
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
      // ⚠️ THE START-SCREEN NOTE IS `fnoteText()` AS OF loffice-2026-08-28d, NOT THE
      // MAPPER'S SENTENCE (live finding L3). It used to greet a first-time user with
      // "Complex styling may be simplified — keep your original file", which is the limit
      // of the NARROW save path and not the one their ⌘S will take: the embedded editor's
      // x2t save measurably keeps charts, images, filters and validation. The stub returns
      // the same literal the old span did, so the two checks below still pin the SHAPE of
      // the note (capped / not capped) rather than being rewritten around the wording.
      const fnoteText = () => 'the fidelity sentence';
      const deleteAsk = () => {};
      // STAGE 3 (loffice-2026-08-29a): the row carries a TYPE BADGE, and the badge is
      // the REAL function — the tables it reads are declared here because the page
      // declares them as consts, and `grab` extracts functions. `kindOf` is the real
      // one, so a badge that stopped matching the extension would fail here.
      const KIND_NOUN = { sheet: 'spreadsheet', doc: 'document', slides: 'presentation' };
      const KIND_BADGE = { sheet: 'XLSX', doc: 'DOCX', slides: 'PPTX' };
      const EXT_KIND = { '.xlsx': 'sheet', '.docx': 'doc', '.pptx': 'slides' };
      eval(grab('kindOf'));
      eval(grab('typeBadge'));
      eval(grab('renderHome'));
      eval(grab('homeDel'));

      const rowsOf = () => nodes.hlist.children.filter(
        c => String(c.className).split(' ').indexOf('hrow') >= 0);

      files = []; renderHome();
      eq('an empty library draws exactly one line, and it points at the Blank card '
         + 'rather than at a control somewhere else',
         nodes.hlist.children.map(c => c.className), ['hempty']);
      check('…and that line names what the three cards make, not just a spreadsheet',
            /spreadsheet/.test(nodes.hlist.children[0].textContent)
            && /document/.test(nodes.hlist.children[0].textContent)
            && /presentation/.test(nodes.hlist.children[0].textContent));
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

      // ⚠️ THE BADGE IS ON EVERY ROW, NOT JUST THE NEW TWO. A badge that appears for
      // some rows and not others reads as a warning about those rows; a badge on all
      // three reads as a fact about the file. And the badge must never displace the
      // NAME from the row's text, which is what the previous assertion covers.
      files = [{ name: 'a.xlsx', size_bytes: 1, modified: 3 },
               { name: 'b.docx', size_bytes: 1, modified: 2 },
               { name: 'c.pptx', size_bytes: 1, modified: 1 }];
      renderHome();
      eq('every row carries a type badge, one per file type',
         rowsOf().map(r => r.children[0].children.map(c => c.textContent).join('')),
         ['XLSX', 'DOCX', 'PPTX']);
      eq('…and the badge is classed by kind so the rail can colour it',
         rowsOf().map(r => r.children[0].children[0].className),
         ['tbadge sheet', 'tbadge doc', 'tbadge slides']);
      eq('…and the NAME is still the row\u2019s text, unmoved by the badge',
         rowsOf().map(r => r.children[0].textContent),
         ['a.xlsx', 'b.docx', 'c.pptx']);
      check('…and the badge says what it means on hover',
            rowsOf()[1].children[0].children[0].title === 'document');

      files = [{ name: 'newest.xlsx', size_bytes: 10, modified: 2 },
               { name: 'older.xlsx', size_bytes: 20, modified: 1 }];
      renderHome();
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

    // ── FIND ──
    // ⚠️ TWO OF THESE MOVED AT 2026-08-27a: the scan came OUT of findRun into
    // `findScan`, so that Replace scans through the same function Find does. Two
    // scanners could disagree about how many matches there are, and "Replace all
    // replaced 7 when the bar said 6" is the kind of report that costs a day.
    check('Find scans the SHEET, not the DOM, so it can match a row that is not drawn '
          + 'yet', /cellAt\(sh, r, c\)/.test(grab('findScan'))
          && /usedExtent\(sh\)/.test(grab('findScan')));
    check('…through ONE scanner, which Replace uses too, so the count in the bar and the '
          + 'count Replace all reports cannot disagree',
          /findHits = findScan\(sh, q\)/.test(grab('findRun'))
          && /findScan\(sh, q\)/.test(grab('findReplaceAll'))
          && /findScan\(sh, q\)/.test(grab('findReplaceOne')));
    check('…and then GROWS the render window to reach the match, terminating even when '
          + 'the column cap is hit',
          /while \(h\.r >= viewRows\)/.test(grab('findGo'))
          && /viewCols < TIER1_MAX_COLS/.test(grab('findGo')));
    check('…is capped, so a one-letter query on a huge sheet cannot hang the tab',
          num('FIND_MAX') > 0 && /hits\.length < FIND_MAX/.test(grab('findScan')));
    check('…says how many and where you are, and admits when a match sits under a merge',
          /' of ' \+ findHits\.length/.test(grab('findGo'))
          && /merged cell/.test(grab('findGo')));
    check('…and Enter / ⇧Enter walk the matches',
          /findGo\(ev\.shiftKey \? -1 : 1\)/.test(html));

    /* ══ 11. THE UNDO STACK, AND THE THREE GESTURES THAT WERE BLOCKED ON IT ═════
       (2026-08-27a) Everything in this section is EXECUTED against bare snapshots,
       because every one of these operations MOVES OR DESTROYS cells and a regex over
       the source cannot tell a correct row insert from one that duplicates a row.

       The reference doc listed exactly these four as "want an undo stack first"
       (docs/research/2026-08-21-office-ui-reference.md §7.4), so the stack is tested
       first and the gestures are tested through it. */
    (function () {
      // A const whose value is an expression (4 * 1024 * 1024) rather than a literal,
      // read out of the page like every other constant in this file: a ceiling changed
      // there must not keep passing against a copy written down here.
      function constOf(name) {
        const m = html.match(new RegExp('^const ' + name + ' = ([^;]+);', 'm'));
        if (!m) throw new Error('const ' + name + ' not found in office.html');
        return eval(m[1]);                                    // eslint-disable-line
      }
      const HIST_MAX = num('HIST_MAX');
      const HIST_MAX_BYTES = constOf('HIST_MAX_BYTES');
      const FIND_MAX = num('FIND_MAX');
      const FIND_CELL_MAX = num('FIND_CELL_MAX');
      const RC_MAX = num('RC_MAX');
      const SORT_BLANK = num('SORT_BLANK');
      const RC_FORMULA_NOTE = constOf('RC_FORMULA_NOTE');
      check('the stack is bounded by COUNT and each entry by BYTES — a long session and '
            + 'one enormous workbook are two different ways to leak a tab',
            HIST_MAX === 50 && HIST_MAX_BYTES === 4 * 1024 * 1024);

      // ── the page's module state, and the stubs the gestures reach for ──
      let snap = null, activeSid = 's1', dirty = false, current = 'Book.xlsx',
          busy = false, mode = 'grid', viewRows = 0, viewCols = 0, openMenu = -1;
      const beacons = [], said = [];
      let rendered = 0, painted = 0;
      function bx(stage, detail) { beacons.push(stage + ':' + (detail === undefined ? '' : detail)); }
      function say(text, kind) { said.push(String(text)); }
      function renderGrid() { rendered++; }
      function paint() { painted++; }
      function findClear() { findHits = []; findAt = -1; }
      function findPaint() {}
      function aiPaint() {}
      function menuPaint() {}
      // the toolbar is a SECOND surface over this same state (section 13 executes its
      // derivation properly); here it only has to exist, because histPaint repaints it
      function toolbarPaint() {}
      function t1ok() { return !!current && !busy && mode === 'grid'; }
      function activeSheet() { return (snap && snap.sheets) ? (snap.sheets[activeSid] || null) : null; }
      function commitFocused() {}
      let lastRC = null;
      function lastCellNow() { return (lastRC && activeSheet()) ? lastRC : null; }
      let findHits = [], findAt = -1;
      const NO_CELL = 'Click a cell first';
      const el = () => ({ value: '', textContent: '', disabled: false, focus() {} });
      const lastSaid = () => said.length ? said[said.length - 1] : '';

      eval(grab('colName')); eval(grab('sheetIds')); eval(grab('cellAt'));
      eval(grab('putCell')); eval(grab('valueText')); eval(grab('displayText'));
      eval(grab('parseInput')); eval(grab('usedExtent'));
      eval(grab('histEntry')); eval(grab('histPush')); eval(grab('histClear'));
      eval(grab('histCan')); eval(grab('histTop')); eval(grab('histRestore'));
      eval(grab('histGo')); eval(grab('histPaint'));
      eval(grab('findScan')); eval(grab('findReplaceText')); eval(grab('replaceWrite'));
      eval(grab('gridRemap')); eval(grab('sheetFormulas')); eval(grab('sheetMerges'));
      eval(grab('sortKey')); eval(grab('sortOrder')); eval(grab('sortGo'));
      eval(grab('rcMerges')); eval(grab('rcApply')); eval(grab('rcGo'));
      let histBack = [], histFwd = [];

      // A sheet with one of everything the honest limits are about: a formula, a merge,
      // a number, blanks, and a cell nobody in these tests ever mentions (D9 = the
      // sentinel, exactly as in test_office_ai.js).
      function book(opts) {
        const o = opts || {};
        const cd = { '0': { '0': { v: 'Region', t: 1 }, '1': { v: 'Sales', t: 1 } },
                     '1': { '0': { v: 'north', t: 1 }, '1': { v: 120, t: 2 } },
                     '2': { '0': { v: 'Alps', t: 1 }, '1': { v: 90, t: 2 } },
                     '3': { '0': { v: 'zulu', t: 1 }, '1': { v: 300, t: 2 } },
                     '8': { '3': { v: 'keep', t: 1 } } };
        if (o.formula) cd['4'] = { '1': { f: '=SUM(B2:B4)', v: 510, t: 2 } };
        const sh = { id: 's1', name: 'Sheet1', cellData: cd, rowCount: 200, columnCount: 26 };
        if (o.merge) sh.mergeData = o.merge;
        return { sheets: { s1: sh }, sheetOrder: ['s1'] };
      }
      function reset(opts) {
        snap = book(opts); activeSid = 's1'; dirty = false; busy = false;
        mode = 'grid'; current = 'Book.xlsx'; lastRC = { r: 1, c: 1 };
        histBack = []; histFwd = [];
        said.length = 0; beacons.length = 0;
      }

      /* ── THE STACK ITSELF: byte-for-byte, both ways ─────────────────────────── */
      reset();
      const original = JSON.stringify(snap);
      check('with nothing pushed there is nothing to undo, and nothing to redo',
            !histCan('undo') && !histCan('redo'));
      const e1 = histPush('typing in B2');
      check('a push returns the entry it pushed, so a caller that needs to recognise it '
            + 'later (the AI card) can hold on to it', !!e1 && e1.label === 'typing in B2');
      check('…and the stack now offers an undo but still no redo',
            histCan('undo') && !histCan('redo'));
      eq('…and names the gesture, which is what the menu row\'s title says',
         histTop('undo').label, 'typing in B2');
      putCell(snap.sheets.s1, 1, 1, { v: 999, t: 2 });
      dirty = true;
      const after = JSON.stringify(snap);
      check('the write really changed the document', after !== original);
      check('UNDO', histGo('undo') === true);
      eq('UNDO RESTORES THE WORKBOOK BYTE FOR BYTE — a clone put back, not a list of '
         + 'operations reversed, because reversing has to GUESS what a cell held',
         JSON.stringify(snap), original);
      eq('…including the dirty flag, so a clean document goes back to CLEAN and stops '
         + 'asking to be saved for a change that no longer exists', dirty, false);
      check('…and the redo is now available, because the present became its top',
            histCan('redo') && !histCan('undo'));
      check('REDO', histGo('redo') === true);
      eq('REDO PUTS IT BACK BYTE FOR BYTE TOO', JSON.stringify(snap), after);
      eq('…dirty flag included', dirty, true);
      check('…and undo is available again: the two stacks are symmetric',
            histCan('undo') && !histCan('redo'));
      check('every transition is beaconed, so "⌘Z did nothing" is answerable from the '
            + 'boot log alone',
            beacons.some(b => /^hist-push:/.test(b)) && beacons.some(b => /^hist-undo:/.test(b))
            && beacons.some(b => /^hist-redo:/.test(b)));
      check('…and each restore redraws the grid and repaints the chrome',
            rendered > 0 && painted > 0);

      // a NEW gesture ends the redo branch
      reset();
      histPush('one');
      putCell(snap.sheets.s1, 0, 5, { v: 'x', t: 1 });
      histGo('undo');
      check('after an undo there is a redo waiting', histCan('redo'));
      histPush('something else');
      eq('…and a NEW gesture THROWS IT AWAY. Anything else would let ⇧⌘Z jump to a '
         + 'future that no longer follows from the present, which is not a redo',
         histFwd.length, 0);

      // the cap
      reset();
      for (let i = 0; i < HIST_MAX + 12; i++) {
        putCell(snap.sheets.s1, 20 + i, 0, { v: i, t: 2 });
        histPush('change ' + i);
      }
      eq('the stack is capped at HIST_MAX entries', histBack.length, HIST_MAX);
      eq('…and it is the OLDEST that is dropped, never the newest',
         histTop('undo').label, 'change ' + (HIST_MAX + 11));

      // an entry that will not fit
      reset();
      snap.sheets.s1.cellData['99'] = { '0': { v: 'y'.repeat(HIST_MAX_BYTES), t: 1 } };
      histPush('a change to a huge workbook');
      check('a workbook too large to clone CLEARS the stack rather than leaving entries '
            + 'that no longer describe it — an Undo that restores the wrong thing is '
            + 'worse than no Undo at all',
            histBack.length === 0 && histFwd.length === 0
            && beacons.some(b => /^hist-too-large:/.test(b)));
      check('…and histPush says so by returning null, so the caller knows this gesture '
            + 'cannot be taken back', histPush('again') === null);

      // the tier and the busy guard
      reset();
      histPush('x');
      mode = 'univer';
      check('the stack refuses to act while Univer owns the document — restoring a '
            + 'tier-1 clone under it would edit a snapshot nobody is reading',
            !histCan('undo') && histGo('undo') === false);
      mode = 'grid'; busy = true;
      check('…and not while the page is busy either', !histCan('undo'));
      busy = false; current = null;
      check('…and not with no workbook open', !histCan('undo'));
      current = 'Book.xlsx';

      // ⌘Z inside a cell stays the BROWSER'S undo — the distinction the old disabled
      // reason drew, kept honest. Asserted over the handler, because the caret only
      // exists in a browser.
      const kd = html.slice(html.indexOf('if (k === \'z\' || k === \'y\')'));
      check('⌘Z / ⌘Y check histEditing() FIRST and return WITHOUT preventDefault, so '
            + 'while you are typing in a cell the browser\'s own text undo is untouched',
            kd.indexOf('if (histEditing()) return;') >= 0
            && kd.indexOf('if (histEditing()) return;') < kd.indexOf('ev.preventDefault();'));
      check('…and histEditing covers the cell being edited, the find boxes and the AI '
            + 'composer — all text, all the browser\'s',
            /dataset\.editing === '1'/.test(grab('histEditing'))
            && /INPUT/.test(grab('histEditing')) && /TEXTAREA/.test(grab('histEditing')));
      check('⇧⌘Z and ⌘Y both redo, which is the pair every editor answers to',
            /\(k === 'y' \|\| ev\.shiftKey\) \? 'redo' : 'undo'/.test(html));
      check('the history is CLEARED when a workbook is opened or closed — restoring a '
            + 'clone of another workbook into this one is the corruption this page '
            + 'refuses to make possible',
            /histClear\('open ' \+ name\)/.test(grab('showWorkbook'))
            && /histClear\('close'\)/.test(grab('clearWorkbook')));
      check('every mutating gesture pushes an entry BEFORE it writes',
            ['styleWrite', 'clearCell', 'addSheet', 'growRows', 'growCols', 'commit',
             'sortGo', 'rcGo', 'findReplaceOne', 'findReplaceAll'].every(fn => {
               const src = grab(fn);
               const p = src.indexOf('histPush(');
               return p > 0;
             }));
      check('…and `commit` pushes only AFTER the "nothing actually changed" test, or '
            + 'clicking through fifty cells would fill the whole stack with identical '
            + 'clones and ⌘Z would appear to do nothing fifty times',
            grab('commit').indexOf('if (now === was)') < grab('commit').indexOf('histPush('));
      check('…while growing the render WINDOW is view state and is not undoable — only '
            + 'the sheet\'s own rowCount/columnCount change is',
            /if \(\(Number\(sh\.rowCount\) \|\| 0\) < viewRows\) \{\s*\n\s*histPush\(/.test(grab('growRows')));
      // ⚠️ AND IT DOES NOT MARK THE DOCUMENT DIRTY, which is a separate fact and a
      // measured one: bridge/office.py reads rowCount and columnCount into the snapshot
      // and never writes them back, so the saved .xlsx is byte-identical either way.
      // Asking somebody to save a change the file cannot carry is a lie on screen.
      check('growing the sheet does NOT claim the file changed, because office.py does '
            + 'not carry rowCount or columnCount back into the .xlsx',
            !/dirty = true/.test(grab('growRows')) && !/dirty = true/.test(grab('growCols'))
            && (fs.readFileSync(path.join(ROOT, 'bridge', 'office.py'), 'utf8')
                  .match(/rowCount/g) || []).length === 2);

      /* ── FIND AND REPLACE ────────────────────────────────────────────────────── */
      eq('replace is case-INSENSITIVE, like the find that feeds it, and replaces every '
         + 'occurrence inside the one cell',
         findReplaceText('North by north', 'north', 'south'),
         { text: 'south by south', n: 2 });
      eq('…and it is not a regex: a user\'s query is text, so a dot matches a dot',
         findReplaceText('a.b axb', '.', '-'), { text: 'a-b axb', n: 1 });
      eq('…a query that is not there changes nothing',
         findReplaceText('abc', 'zz', 'q'), { text: 'abc', n: 0 });
      eq('…an EMPTY query is refused rather than inserting the replacement between '
         + 'every character', findReplaceText('abc', '', 'q'), { text: 'abc', n: 0 });
      eq('…and an empty REPLACEMENT is a deletion, which is a legitimate thing to want',
         findReplaceText('a-b-c', '-', ''), { text: 'abc', n: 2 });
      eq('replace terminates when the replacement CONTAINS the query — the one input '
         + 'that turns a naive loop into a hung tab',
         findReplaceText('aaa', 'a', 'aa'), { text: 'aaaaaa', n: 3 });
      [[null, 'a', 'b'], ['x', null, 'b'], ['x', 'a', null], [undefined, undefined, undefined],
       [42, 4, 5], [{}, 'o', 'x']].forEach((args, i) => {
        let threw = null, out = null;
        try { out = findReplaceText(args[0], args[1], args[2]); } catch (e) { threw = e; }
        check('findReplaceText is total (case ' + i + ')',
              !threw && out && typeof out.text === 'string' && typeof out.n === 'number');
      });

      reset();
      eq('the scan finds every match, case-insensitively, in reading order — "n" is in '
         + 'both "Region" and "north", and the capital does not hide it',
         findScan(snap.sheets.s1, 'n').map(h => colName(h.c) + (h.r + 1)),
         ['A1', 'A2']);
      eq('…and an empty query matches nothing rather than everything',
         findScan(snap.sheets.s1, '  ').length, 0);
      eq('…and a junk sheet costs the scan, never the page',
         [findScan(null, 'x').length, findScan({}, 'x').length], [0, 0]);

      // REPLACE ALL, executed, then UNDONE
      reset();
      const beforeAll = JSON.stringify(snap);
      const hits = findScan(snap.sheets.s1, 'n');
      histPush('replacing n throughout Sheet1');
      const rep = replaceWrite(snap.sheets.s1, hits, 'n', 'N');
      eq('replace all reports the cells it touched and the occurrences inside them',
         [rep.cells, rep.occurrences], [2, 2]);
      eq('…and the cells really say the new thing', [snap.sheets.s1.cellData['1']['0'].v,
         snap.sheets.s1.cellData['3']['0'].v], ['North', 'zulu']);
      eq('THE SENTINEL IS UNTOUCHED — replace writes what it matched and nothing else',
         snap.sheets.s1.cellData['8']['3'], { v: 'keep', t: 1 });
      check('UNDO after a replace-all', histGo('undo') === true);
      eq('…and ONE undo entry puts the WHOLE replace-all back, byte for byte',
         JSON.stringify(snap), beforeAll);

      // the replaced value goes back through parseInput, so it is TYPED
      reset();
      putCell(snap.sheets.s1, 6, 0, { v: 'x12', t: 1 });
      replaceWrite(snap.sheets.s1, [{ r: 6, c: 0 }], 'x', '');
      eq('a replaced cell is re-TYPED through parseInput, the same converter a person '
         + 'typing gets — so "x12" → "12" becomes a NUMBER, not the string 12',
         snap.sheets.s1.cellData['6']['0'], { v: 12, t: 2 });
      reset();
      putCell(snap.sheets.s1, 6, 0, { v: 'keepme', t: 1, s: { bl: 1 } });
      replaceWrite(snap.sheets.s1, [{ r: 6, c: 0 }], 'keep', 'hold');
      eq('…and the cell\'s STYLE survives the replacement, exactly as it does when the '
         + 'value is typed over', snap.sheets.s1.cellData['6']['0'].s, { bl: 1 });

      // a match inside a FORMULA is a match in its TEXT, and that is reported
      reset({ formula: true });
      const fx = replaceWrite(snap.sheets.s1, findScan(snap.sheets.s1, 'B2'), 'B2', 'B3');
      eq('a match inside a FORMULA is a match in the formula TEXT, because that is what '
         + 'this tier shows and stores — and it is counted separately so the message can '
         + 'warn about it', [fx.cells, fx.formulas], [1, 1]);
      eq('…and the formula really was rewritten, as text',
         snap.sheets.s1.cellData['4']['1'].f, '=SUM(B3:B4)');
      check('…which the page says out loud, in the message and on the row',
            /holds a FORMULA and its text was rewritten/.test(grab('findReplaceOne'))
            && /the formula TEXT was rewritten/.test(grab('findReplaceAll')));

      reset();
      putCell(snap.sheets.s1, 7, 0, { v: 'q'.repeat(FIND_CELL_MAX - 1), t: 1 });
      const big = replaceWrite(snap.sheets.s1, [{ r: 7, c: 0 }], 'q', 'qqq');
      eq('a replacement that would make the cell longer than a cell may be is REFUSED '
         + 'for that cell rather than truncated — half a value written silently into a '
         + 'document is the outcome this page will not have',
         [big.cells, big.skipped], [0, 1]);
      eq('…and the cell is exactly as it was', snap.sheets.s1.cellData['7']['0'].v.length,
         FIND_CELL_MAX - 1);
      check('replaceWrite touches no view state and no dirty flag, which is why it can '
            + 'be run against a bare snapshot here',
            !/dirty|renderGrid|viewRows|viewCols|document\.|\bel\(/.test(grab('replaceWrite')));
      check('Replace all says when Find\'s own cap means there may be more',
            /Replace all again/.test(grab('findReplaceAll')) && FIND_MAX === 500);
      // A GESTURE THAT CHANGED NOTHING IS NOT A GESTURE, and all three places that can
      // no-op say so the same way. A ⌘Z that appears to do nothing is the defect class
      // this page keeps removing, and it is easiest to reintroduce by accident here.
      check('a replace, a replace-all and a sort that change nothing all decline to '
            + 'leave a ⌘Z that would appear to do nothing',
            /histBack\.pop\(\)/.test(grab('findReplaceAll'))
            && /histBack\.pop\(\)/.test(grab('findReplaceOne'))
            && grab('sortGo').indexOf('if (!moved) {')
                 < grab('sortGo').indexOf('histPush('));
      {
        // …executed, for the sort, because it is the one that has to compute it
        snap = { sheets: { s1: { id: 's1', name: 'Sheet1', rowCount: 200, columnCount: 26,
          cellData: { '0': { '0': { v: 'a', t: 1 } }, '1': { '0': { v: 'b', t: 1 } },
                      '2': { '0': { v: 'c', t: 1 } } } } }, sheetOrder: ['s1'] };
        activeSid = 's1'; lastRC = { r: 0, c: 0 };
        histBack = []; histFwd = []; said.length = 0;
        const untouched = JSON.stringify(snap);
        sortGo(false);
        eq('an already-sorted sheet is left alone, with no history entry and a message '
           + 'that says nothing moved',
           [histBack.length, JSON.stringify(snap) === untouched,
            /already in that order/.test(lastSaid())], [0, true, true]);
      }

      /* ── SORT ────────────────────────────────────────────────────────────────── */
      eq('sortKey puts numbers before text before booleans, and BLANKS LAST',
         [sortKey({ v: 5, t: 2 }).k, sortKey({ v: 'a', t: 1 }).k,
          sortKey({ v: true, t: 3 }).k, sortKey(null).k, sortKey({ v: '', t: 1 }).k],
         [0, 1, 2, 3, 3]);
      eq('…and a FORMULA sorts as its own TEXT, because this tier has no formula engine '
         + 'and inventing one would be worse than being honest about it',
         sortKey({ f: '=SUM(A1:A2)', v: 9, t: 2 }).s, '=sum(a1:a2)');
      reset();
      eq('A→Z by a NUMERIC column orders by value, not by the text of the number — and '
         + 'the header row, being TEXT, sorts after them, because sort SHEET sorts row 1 '
         + 'with the rest and this page does not guess at a header',
         sortOrder(snap.sheets.s1, 1, false, 4), [2, 1, 3, 0]);
      eq('…and Z→A is its exact reverse', sortOrder(snap.sheets.s1, 1, true, 4), [0, 3, 1, 2]);
      eq('A→Z by a TEXT column is case-INSENSITIVE, so "Alps" does not sort above '
         + '"north" merely for being capitalised (row 1 is the header "Region", and '
         + 'sort SHEET sorts it with the rest)',
         sortOrder(snap.sheets.s1, 0, false, 4).map(r => r), [2, 1, 0, 3]);
      {
        // blanks last in BOTH directions, and stability
        const s = { cellData: { '0': { '0': { v: 'b', t: 1 } }, '1': {},
                                '2': { '0': { v: 'a', t: 1 } }, '3': {} } };
        eq('blank rows go to the bottom on A→Z…', sortOrder(s, 0, false, 4), [2, 0, 1, 3]);
        eq('…AND on Z→A: a sheet whose empty rows climb to the top is not a sort '
           + 'anybody wanted', sortOrder(s, 0, true, 4), [0, 2, 1, 3]);
        const t = { cellData: { '0': { '0': { v: 'x', t: 1 } }, '1': { '0': { v: 'x', t: 1 } },
                                '2': { '0': { v: 'x', t: 1 } } } };
        eq('equal keys keep the order they were already in — the sort is STABLE, so '
           + 'sorting twice does not shuffle ties', sortOrder(t, 0, false, 3), [0, 1, 2]);
      }

      // THE GESTURE, executed: values move WITH their rows.
      // ⚠️ a sheet of its own, four rows of it, because "sort SHEET" really does sort the
      // WHOLE used extent — including the D9 sentinel row `book()` carries — and a test
      // that expected otherwise would be testing a sort this page does not perform.
      function sortBook(withFormula) {
        const cd = { '0': { '0': { v: 'Region', t: 1 }, '1': { v: 'Sales', t: 1 } },
                     '1': { '0': { v: 'north', t: 1 }, '1': { v: 120, t: 2 } },
                     '2': { '0': { v: 'Alps', t: 1 }, '1': { v: 90, t: 2 } },
                     '3': { '0': { v: 'zulu', t: 1 }, '1': { v: 300, t: 2 } } };
        if (withFormula) cd['3']['2'] = { f: '=B4*2', v: 600, t: 2 };
        return { sheets: { s1: { id: 's1', name: 'Sheet1', cellData: cd,
                                 rowCount: 200, columnCount: 26 } },
                 sheetOrder: ['s1'] };
      }
      snap = sortBook(true); activeSid = 's1'; dirty = false; histBack = []; histFwd = [];
      said.length = 0; beacons.length = 0;
      lastRC = { r: 0, c: 1 };                       // the focused column is B
      const beforeSort = JSON.stringify(snap);
      sortGo(false);
      eq('the sort moved whole ROWS: the sales column is now ascending, with the text '
         + 'header after the numbers',
         [0, 1, 2, 3].map(r => snap.sheets.s1.cellData[String(r)]['1'].v),
         [90, 120, 300, 'Sales']);
      eq('…and column A came WITH it, row by row, which is the whole of "values with '
         + 'their rows"',
         [0, 1, 2, 3].map(r => snap.sheets.s1.cellData[String(r)]['0'].v),
         ['Alps', 'north', 'zulu', 'Region']);
      check('the message says which column it sorted by, how many rows moved, that row 1 '
            + 'went with them, and where the blanks went',
            /by column B/.test(lastSaid()) && /moved/.test(lastSaid())
            && /Row 1 was sorted with the rest/.test(lastSaid())
            && /Blank cells went to the bottom/.test(lastSaid()));
      check('…and, because this sheet holds a formula, it says the references were NOT '
            + 'rewritten — the honest half of the old disabled reason',
            lastSaid().indexOf(RC_FORMULA_NOTE) > 0);
      eq('the formula moved with its row, as TEXT, and still says exactly what it said: '
         + 'it was in C4 and is now in C3, and it STILL reads =B4*2',
         snap.sheets.s1.cellData['2']['2'].f, '=B4*2');
      check('one gesture, one undo entry', histBack.length === 1);
      check('UNDO after a sort', histGo('undo') === true);
      eq('…and the whole sort comes back byte for byte', JSON.stringify(snap), beforeSort);

      // THE MERGE REFUSAL — the honest limit, stated
      reset({ merge: [{ startRow: 0, endRow: 0, startColumn: 0, endColumn: 1 }] });
      lastRC = { r: 0, c: 1 };
      const beforeRefuse = JSON.stringify(snap);
      sortGo(false);
      eq('A SHEET WITH A MERGED RANGE IS NOT SORTED AT ALL, and nothing was touched',
         JSON.stringify(snap), beforeRefuse);
      eq('…and no history entry was pushed for a gesture that did not happen',
         histBack.length, 0);
      check('…and the refusal SAYS WHY, in terms of what would go wrong: a sort moves '
            + 'whole rows and a merge does not move with them',
            /merged range/.test(lastSaid()) && /will not sort/.test(lastSaid())
            && /never belonged together/.test(lastSaid()));
      check('…and it names the way to do it anyway rather than being a dead end',
            /rich editor/.test(lastSaid()));
      check('…and it is beaconed with the count', beacons.some(b => /^sort-refused:merges=1/.test(b)));
      check('the ROW ITSELF greys on a merged sheet, so the refusal arrives BEFORE the '
            + 'click as well as after it',
            /sheetMerges\(activeSheet\(\)\)/.test(grab('menuPaint'))
            && /mi-sortaz/.test(grab('menuPaint')));
      reset();
      lastRC = null;
      sortGo(false);
      eq('with no cell selected the sort asks for one instead of guessing a column',
         [lastSaid(), histBack.length], [NO_CELL, 0]);

      /* ── INSERT AND DELETE ───────────────────────────────────────────────────── */
      // the merge renumbering, on its own, because it is the half that WAS the reason
      eq('a merge entirely AFTER the insertion line shifts by n',
         rcMerges([{ startRow: 4, endRow: 5, startColumn: 0, endColumn: 1 }], 'row', 2, 1, false),
         [{ startRow: 5, endRow: 6, startColumn: 0, endColumn: 1 }]);
      eq('a merge entirely BEFORE it does not move',
         rcMerges([{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }], 'row', 4, 1, false),
         [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }]);
      eq('a merge that STRADDLES the line GROWS, which is what Excel does and the only '
         + 'answer that leaves the same cells joined together',
         rcMerges([{ startRow: 1, endRow: 4, startColumn: 0, endColumn: 1 }], 'row', 3, 1, false),
         [{ startRow: 1, endRow: 5, startColumn: 0, endColumn: 1 }]);
      eq('COLUMNS are renumbered on their own axis, and rows are left alone',
         rcMerges([{ startRow: 0, endRow: 2, startColumn: 3, endColumn: 4 }], 'col', 1, 2, false),
         [{ startRow: 0, endRow: 2, startColumn: 5, endColumn: 6 }]);
      eq('on a DELETE a merge after the line shifts BACK',
         rcMerges([{ startRow: 6, endRow: 7, startColumn: 0, endColumn: 0 }], 'row', 2, 1, true),
         [{ startRow: 5, endRow: 6, startColumn: 0, endColumn: 0 }]);
      eq('…one that straddles it SHRINKS',
         rcMerges([{ startRow: 1, endRow: 5, startColumn: 0, endColumn: 0 }], 'row', 3, 2, true),
         [{ startRow: 1, endRow: 3, startColumn: 0, endColumn: 0 }]);
      eq('…and one with nothing left of it is DROPPED, not kept as a merge of one cell',
         rcMerges([{ startRow: 2, endRow: 3, startColumn: 0, endColumn: 0 }], 'row', 2, 2, true),
         []);
      eq('an unreadable merge is dropped rather than guessed at',
         rcMerges([null, { startRow: 'x', endRow: 2 }, 7], 'row', 0, 1, false), []);
      eq('rcMerges returns a NEW list and leaves the one it was given alone — the caller '
         + 'decides whether to install it, which is what makes it testable',
         (() => { const src = [{ startRow: 4, endRow: 5, startColumn: 0, endColumn: 0 }];
                  rcMerges(src, 'row', 0, 1, false); return src[0].startRow; })(), 4);

      // INSERT A ROW, executed: a merge shifts, a formula does NOT
      reset({ formula: true, merge: [{ startRow: 3, endRow: 3, startColumn: 0, endColumn: 1 }] });
      lastRC = { r: 1, c: 0 };                     // insert above row 2
      const beforeIns = JSON.stringify(snap);
      rcGo('insert', 'row');
      eq('the row above the cursor is now BLANK', snap.sheets.s1.cellData['1'], undefined);
      eq('…and everything from there down moved one row, ONCE (a remap that wrote as it '
         + 'read would have duplicated it)',
         [2, 3, 4].map(r => snap.sheets.s1.cellData[String(r)]['0'].v),
         ['north', 'Alps', 'zulu']);
      eq('THE MERGE WAS RENUMBERED — the half of the old disabled reason that is now '
         + 'simply done', snap.sheets.s1.mergeData,
         [{ startRow: 4, endRow: 4, startColumn: 0, endColumn: 1 }]);
      eq('THE FORMULA WAS NOT REWRITTEN: it moved as text and still says B2:B4, because '
         + 'this tier stores a formula as text and has no parser',
         snap.sheets.s1.cellData['5']['1'].f, '=SUM(B2:B4)');
      check('…and the page SAYS that, in the message box, on this gesture',
            lastSaid().indexOf(RC_FORMULA_NOTE) > 0);
      check('…as well as saying the merged range was renumbered',
            /merged range was renumbered/.test(lastSaid()));
      eq('the sentinel nobody mentioned moved with its own row and is otherwise intact',
         snap.sheets.s1.cellData['9']['3'], { v: 'keep', t: 1 });
      check('one gesture, one undo entry', histBack.length === 1);
      check('UNDO after an insert', histGo('undo') === true);
      eq('…and the sheet, its merges and its formula all come back byte for byte',
         JSON.stringify(snap), beforeIns);

      // DELETE A ROW
      reset();
      lastRC = { r: 1, c: 0 };
      const beforeDel = JSON.stringify(snap);
      rcGo('delete', 'row');
      eq('the row is gone and the rows below it moved up',
         [1, 2].map(r => snap.sheets.s1.cellData[String(r)]['0'].v), ['Alps', 'zulu']);
      eq('…and the tail really was cleared rather than left as a duplicate of the last '
         + 'row', snap.sheets.s1.cellData['4'], undefined);
      check('the message COUNTS what went with it, before ⌘Z is even pressed — "I '
            + 'deleted a row and lost data" has to be answerable',
            /2 cells of data went with it/.test(lastSaid()));
      check('UNDO after a delete', histGo('undo') === true);
      eq('…and the deleted row comes back byte for byte', JSON.stringify(snap), beforeDel);

      // COLUMNS, both ways
      reset();
      lastRC = { r: 0, c: 0 };
      rcGo('insert', 'col');
      eq('inserting a column to the left moves the data right, once',
         [snap.sheets.s1.cellData['0']['0'], snap.sheets.s1.cellData['0']['1'].v], [undefined, 'Region']);
      reset();
      lastRC = { r: 0, c: 0 };
      rcGo('delete', 'col');
      eq('deleting a column moves the data left, and clears the last one',
         [snap.sheets.s1.cellData['0']['0'].v, snap.sheets.s1.cellData['0']['1']],
         ['Sales', undefined]);

      // rcApply's own bounds
      reset();
      eq('rcApply clamps the number of rows or columns in one call to RC_MAX',
         rcApply(snap.sheets.s1, 'insert', 'row', 0, 99999).n, RC_MAX);
      reset();
      eq('…and treats a missing or junk count as one',
         [rcApply(snap.sheets.s1, 'insert', 'row', 0, undefined).n,
          rcApply(snap.sheets.s1, 'insert', 'row', 0, 'lots').n], [1, 1]);
      check('rcApply reports the merge and formula state it left behind, so the caller '
            + 'does not have to re-derive it', (() => {
              reset({ formula: true, merge: [{ startRow: 0, endRow: 1, startColumn: 0, endColumn: 1 }] });
              const info = rcApply(snap.sheets.s1, 'insert', 'row', 5, 1);
              return info.merges === 1 && info.formulas === 1 && info.clipped === false;
            })());
      check('a column insert that would reach past the grid\'s own width refuses rather '
            + 'than pushing the last column off the edge',
            /already reaches column/.test(grab('rcGo'))
            && /used\.cols >= TIER1_MAX_COLS/.test(grab('rcGo')));
      check('gridRemap CAPTURES BEFORE IT WRITES — the source and destination are the '
            + 'same rectangle, so writing as it went would read cells it had already '
            + 'overwritten (which shows up as a duplicated row, not as an error)',
            grab('gridRemap').indexOf('held.push(row)')
              < grab('gridRemap').indexOf('putCell(sh, r, c, held'));
      eq('gridRemap refuses a junk rectangle rather than throwing',
         [gridRemap(null, 1, 1, () => null), gridRemap({}, 0, 5, () => null),
          gridRemap({}, 5, 5, 'nope')], [0, 0, 0]);
      check('sortGo, rcGo and the two replace gestures are all refused in the rich '
            + 'editor, exactly as every other tier-1 write is',
            [grab('sortGo'), grab('rcGo')].every(f => /t1ok\(\)/.test(f))
            && /findCanWrite\(\)/.test(grab('findReplaceOne'))
            && /findCanWrite\(\)/.test(grab('findReplaceAll'))
            && /t1ok\(\)/.test(grab('findCanWrite')));
    })();

    // ⚠️ THE NUL-BYTE REPAIR, PINNED SO IT CANNOT COME BACK. This file carried NUL
    // bytes (U+0000) inside three string literals for two slices; the visible symptom
    // was that ripgrep refused to search it ("binary file matches"), so every builder
    // after that had to work on this page without Grep. It is clean now, and one
    // assertion is cheaper than rediscovering that.
    eq('office.html contains ZERO NUL bytes, so ripgrep — and therefore the Grep tool — '
       + 'searches it like any other file',
       fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'office.html'))
         .filter(b => b === 0).length, 0);

    /* ── EVERY id THIS PAGE REACHES FOR EXISTS IN THE MARKUP ─────────────────────
       The page states this rule in a comment ("a rule the test harness enforces, and
       the reason it can catch a renamed element") and it was NOT actually enforced
       anywhere. It is now, because this slice added six new ids and the failure mode of
       getting one wrong is silent: `el('find-repall')` returning null makes the whole
       script throw at LOAD, before anything is drawn — the blank-rectangle symptom this
       page has already been debugged for three times. */
    {
      const declared = new Set([...html.matchAll(/id="([\w-]+)"/g)].map(m => m[1]));
      const reached = [...new Set([...html.matchAll(/\bel\('([\w-]+)'\)/g)].map(m => m[1]))];
      check('the id scan found the page\'s elements — a vacuous fence is no fence',
            declared.size > 50 && reached.length > 50);
      eq('EVERY id el() reaches for is declared in the markup. A typo here throws at '
         + 'LOAD and paints nothing, which is the exact symptom this page has been '
         + 'debugged for three times', reached.filter(id => !declared.has(id)), []);
      ['find-r', 'find-rep', 'find-repall', 'mi-undo', 'mi-redo', 'mi-rowdel', 'mi-coldel']
        .forEach(id => check('…including the new ' + id, declared.has(id)));
    }

    /* ── the rows that stopped being grey, and the two that arrived ───────────── */
    ['mi-undo', 'mi-redo', 'mi-replace', 'mi-rowabove', 'mi-colleft', 'mi-sortaz',
     'mi-sortza'].forEach(id => {
      check(id + ' is no longer shipped disabled — it does the thing now',
            new RegExp('id="' + id + '"(?![^>]*disabled)').test(html));
    });
    ['mi-rowdel', 'mi-coldel'].forEach(id =>
      check('the Insert menu grew a ' + id + ' row, because an insert with no delete is '
            + 'half a capability', html.indexOf('id="' + id + '"') > 0));
    check('the find bar grew a replace box and its two verbs, in the SAME strip',
          /id="find-r"/.test(html) && /id="find-rep"/.test(html)
          && /id="find-repall"/.test(html)
          && html.indexOf('id="find-r"') > html.indexOf('<div id="findrow">')
          && html.indexOf('id="find-r"') < html.indexOf('id="find-x"'));
    check('…and a replace button with nothing to replace GREYS rather than vanishing — '
          + 'the same grey-not-hide grammar the menu rows follow',
          /\.fbtn:disabled\{/.test(CSS) && /function findPaint\(\)/.test(html));
    check('the keyboard cheat sheet lists the new shortcuts, including the one honest '
          + 'caveat about ⌘Z inside a cell',
          /⇧⌘H/.test(html) && /undo the last change to the sheet/.test(html)
          && /browser’s own/.test(html));

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

    /* ══ 12. THE TOOLBAR ROW (2026-08-27b) ══════════════════════════════════════
       §7.3 of docs/research/2026-08-21-office-ui-reference.md: "A real toolbar (the icon
       row under the menu bar). The Format menu is the same commands; the toolbar is the
       fast path."

       THE PROPERTY THIS SECTION EXISTS TO PIN, and it is the whole reason a toolbar was
       cheap enough to add at all: THE ROW ADDS NO COMMAND. Every button mirrors a menu
       row by id, its click is that row's own click, and its disabled state, its reason
       and its pressed state are READ OFF the row after menuPaint has decided them. So
       the assertion that matters is not "the button works" — it is "there is only one of
       everything", and it is asserted by construction. */
    {
      const TBAR = [...html.matchAll(/<button class="tb" id="(tb-[\w-]+)"([^>]*)>/g)]
        .map(m => {
          const a = m[2];
          const at = k => (a.match(new RegExp(k + '="([^"]*)"')) || [])[1];
          return { id: m[1], row: at('data-row'), tip: at('data-tip'),
                   on: at('data-on'), title: at('title'), aria: at('aria-label') };
        });
      check('there IS a third row, white and flush with the sheet like the menu bar, and '
            + 'it is its own row UNDER the menus',
            /<div id="toolbar">/.test(html)
            && html.indexOf('<div id="toolbar">') > html.indexOf('</nav>')
            && html.indexOf('<div id="toolbar">') < html.indexOf('<div id="findrow">')
            && /#toolbar\{[^}]*background:#fff/.test(CSS));
      check('…in BOTH themes, like the strip above it: neither theme axis repaints it',
            !/data-theme="light"\]\)\s*#toolbar/.test(CSS)
            && !/data-chrome="studio"\]\)\s*#toolbar/.test(CSS));
      check('…and it is HIDDEN BY A CLASS, never by an inline display — the recorded #msg '
            + 'trap, and the rule the whole page follows',
            /body\.tbaroff #toolbar\{display:none\}/.test(CSS)
            && /classList\.toggle\('tbaroff'/.test(html));
      eq('the row carries the commands the brief named — undo, redo, the four text '
         + 'styles, three alignments, wrap, clear formatting, and a Find toggle',
         TBAR.map(t => t.id),
         ['tb-undo', 'tb-redo', 'tb-bold', 'tb-italic', 'tb-underline', 'tb-strike',
          'tb-alignl', 'tb-alignc', 'tb-alignr', 'tb-wrap', 'tb-clearfmt', 'tb-find']);
      eq('EVERY button names the menu row it mirrors, and every one of those rows exists '
         + 'in the markup', TBAR.filter(t => !t.row
           || !new RegExp('id="' + t.row + '"').test(html)).map(t => t.id), []);
      eq('…and every one of those rows is itself WIRED — so a toolbar button can only '
         + 'ever resolve to a handler that already existed. This is the "zero new '
         + 'writers" claim, made by construction rather than by grep',
         TBAR.filter(t => !wired(t.row)).map(t => t.id), []);
      check('…and the click really is the row\'s own click, not a copy of its body',
            /const row = el\(b\.dataset\.row\);/.test(html)
            && /if \(row\) row\.click\(\);/.test(html));
      eq('exactly ONE button has a handler of its own, and it is the Find TOGGLE — a row '
         + 'that is a verb ("Find…") against a button that is a state',
         Object.keys(JSON.parse(JSON.stringify({}))).concat(
           (html.match(/const TB_TOGGLE = \{([^}]*)\}/) || [, ''])[1]
             .match(/'([\w-]+)'/g) || []).map(s => s.replace(/'/g, '')),
         ['tb-find']);
      check('…and that handler is findOpen — the SAME function the menu row calls, in its '
            + 'own toggle form', /'tb-find': \(\) => findOpen\(\)/.test(html));
      check('the icons are inline SVG and letterforms IN THE MARKUP — no font, no sprite, '
            + 'no external asset, and the row is complete in the served document',
            (html.match(/<svg viewBox="0 0 16 16" aria-hidden="true">/g) || []).length >= 8
            && /<span class="g gb">B<\/span>/.test(html)
            && /<span class="g gi">I<\/span>/.test(html)
            && /<span class="g gu">U<\/span>/.test(html)
            && /<span class="g gs">S<\/span>/.test(html));
      eq('…and every button says what it is, before any script runs and to a screen '
         + 'reader', TBAR.filter(t => !t.title || !t.aria || t.title !== t.tip).map(t => t.id),
         []);
      check('the groups are separated by the same hairline the dropdowns use, not by gaps',
            /#toolbar \.tbsep\{/.test(CSS)
            && (html.match(/<span class="tbsep"><\/span>/g) || []).length >= 3);
      check('a pressed button has its own ground, and a disabled one greys rather than '
            + 'vanishing — the grey-not-hide grammar, one row down',
            /#toolbar \.tb\.on\{/.test(CSS) && /#toolbar \.tb:disabled\{/.test(CSS));
      check('the row does not scroll or clip: an overflow here would be the same defect '
            + 'as one on #menubar', !/#toolbar\{[^}]*overflow/.test(CSS));
      check('View → Show toolbar is a real menu row with a tick, and it is wired',
            /id="mi-toolbar"><span class="mtick"><\/span>Show toolbar/.test(html)
            && /mi\('mi-toolbar', \(\) => toolbarSetOpen\(!toolbarOn\(\), 'menu'\)\)/.test(html)
            && /tick\('mi-toolbar', toolbarOn\(\)\)/.test(html));

      /* ── THE DERIVATION, EXECUTED. The pressed state of B / I / U / S has to come from
         the SAME place the Format menu's ticks come from — the focused cell's RESOLVED
         style, which may be an inline dict or a shared style id — or the two surfaces
         will disagree about a bold cell, which is exactly the report this row could
         produce. So the real menuPaint and the real toolbarPaint are run together, over
         a real snapshot, with a stub DOM underneath. */
      (function () {
        function mkNode(id, isRow) {
          const cls = {};
          const n = { id: id, disabled: false, title: '', dataset: {},
                      _tick: isRow ? { textContent: '' } : null,
                      classList: {
                        toggle(c, on) { cls[c] = on === undefined ? !cls[c] : !!on; return !!cls[c]; },
                        contains(c) { return !!cls[c]; },
                        add(c) { cls[c] = true; },
                        remove(c) { cls[c] = false; } },
                      querySelector(sel) { return sel === '.mtick' ? n._tick : null; },
                      click() { n._clicks = (n._clicks || 0) + 1; } };
          return n;
        }
        const nodes = {};
        const el = id => nodes[id] || null;
        // the rows the toolbar mirrors, plus the find bar it reads its own state from
        TBAR.forEach(t => { nodes[t.row] = mkNode(t.row, true); });
        ['mi-replace', 'mi-clearcell'].forEach(id => { nodes[id] = mkNode(id, true); });
        nodes.findrow = mkNode('findrow', false);
        const buttons = TBAR.map(t => {
          const b = mkNode(t.id, false);
          b.dataset.row = t.row;
          b.dataset.tip = t.tip;
          if (t.on) b.dataset.on = t.on;
          nodes[t.id] = b;
          return b;
        });
        const bodyCls = {};
        const document = {
          body: { classList: { toggle(c, on) { bodyCls[c] = on === undefined ? !bodyCls[c] : !!on; },
                               contains: c => !!bodyCls[c] } },
          querySelectorAll: sel => (sel === '#toolbar .tb' ? buttons : []),
          activeElement: null
        };
        const store = {};
        const localStorage = { getItem: k => (k in store ? store[k] : null),
                               setItem: (k, v) => { store[k] = String(v); } };
        const beacons = [];
        function bx(stage, detail) { beacons.push(stage + ':' + (detail || '')); }
        // the page's own module state, and the two constants menuPaint reads
        let snap = null, activeSid = 's1', current = 'Book.xlsx', busy = false,
            mode = 'grid', dirty = false, openMenu = -1, lastRC = null,
            histBack = [], histFwd = [];
        // ⚠️ ADDED AT loffice-2026-08-28a. t1ok() now also reads the editor's state,
        // because a HIDDEN menu bar does not disarm ⌘B / ⌘Z / ⇧F11 — so the stub has
        // to carry the same three flags the page does, and the default here is the
        // NOT-INSTALLED case, which is exactly the tier-1 world every assertion below
        // was written for.
        let ooInstalled = false, ooReady = false, ooBooting = false;
        const T1_ONLY = 'rich editor', NO_DOC = 'no workbook', NO_CELL = 'click a cell';
        const LS_TOOLBAR = (html.match(/const LS_TOOLBAR = '([^']+)'/) || [])[1];
        function activeSheet() { return (snap && snap.sheets) ? (snap.sheets[activeSid] || null) : null; }
        function lastCellNow() { return (lastRC && activeSheet()) ? lastRC : null; }
        function railIsOpen() { return true; }
        function aiAvail() { return false; }
        function aiPaneOpen() { return false; }
        function sheetMerges() { return 0; }
        eval(grab('cellAt'));
        eval(grab('cellStyle'));
        eval(grab('setRow'));
        eval(grab('tick'));
        eval(grab('editorActive'));
        eval(grab('t1ok'));
        eval(grab('histCan'));
        eval(grab('histTop'));
        eval(grab('menuPaint'));
        eval(grab('toolbarButtons'));
        eval(grab('toolbarOn'));
        eval(grab('toolbarSetOpen'));
        eval(grab('toolbarPaint'));

        eq('the localStorage key is this page\'s own namespace, like every other pref',
           LS_TOOLBAR, 'harness-office-toolbar');
        // ── the View toggle and its persistence ──
        check('the toolbar is on by default — a fast path nobody can see is not one',
              toolbarOn());
        toolbarSetOpen(false, 'test');
        check('hiding it puts the class on the body…', !toolbarOn());
        eq('…and persists the choice under that key', store[LS_TOOLBAR], '0');
        toolbarSetOpen(true, 'test');
        eq('…and showing it again persists that', store[LS_TOOLBAR], '1');
        check('both transitions are beaconed, so "my toolbar vanished" is answerable from '
              + 'the boot log', beacons.some(b => /^toolbar-hide:/.test(b))
              && beacons.some(b => /^toolbar-show:/.test(b)));

        // ── the state the buttons show, derived from the sheet ──
        const styled = { sheets: { s1: { id: 's1', name: 'Sheet1', rowCount: 20,
          columnCount: 8, cellData: {
            '0': { '0': { v: 'plain', t: 1 },
                   '1': { v: 'bold', t: 1, s: { bl: 1 } },
                   '2': { v: 'shared', t: 1, s: 'S1' },
                   '3': { v: 'right', t: 1, s: { ht: 3, tb: 3 } } } } } },
          sheetOrder: ['s1'], styles: { S1: { it: 1 } } };
        const lit = () => buttons.filter(b => b.classList.contains('on')).map(b => b.id);
        const off = () => buttons.filter(b => b.disabled).map(b => b.id);

        snap = null; current = null; lastRC = null;
        toolbarPaint();
        eq('with NO WORKBOOK OPEN every button greys — and none of them lights',
           [off().length, lit()], [buttons.length, []]);
        eq('…and each one carries the menu row\'s own REASON rather than its cheerful '
           + 'tooltip', nodes['tb-bold'].title, NO_DOC);

        snap = styled; current = 'Book.xlsx';
        lastRC = { r: 0, c: 0 };
        toolbarPaint();
        eq('a plain cell lights nothing', lit(), []);
        check('…and the style buttons are live again, with their own sentences back',
              !nodes['tb-bold'].disabled
              && /Bold/.test(nodes['tb-bold'].title));
        check('…while UNDO and REDO stay grey, because the stack is empty — the toolbar '
              + 'greys live with the stack because it is READ OFF the Edit rows',
              nodes['tb-undo'].disabled && nodes['tb-redo'].disabled);
        eq('…and they carry the Edit rows\' own reasons, word for word',
           [nodes['tb-undo'].title, nodes['tb-redo'].title],
           [nodes['mi-undo'].title, nodes['mi-redo'].title]);

        histBack.push({ label: 'typing in B2' });
        toolbarPaint();
        check('one entry on the stack and UNDO comes alive on both surfaces at once',
              !nodes['tb-undo'].disabled && !nodes['mi-undo'].disabled
              && nodes['tb-redo'].disabled);
        eq('…and the live title NAMES the gesture, exactly as the Edit row does',
           nodes['tb-undo'].title, 'Undo typing in B2');

        lastRC = { r: 0, c: 1 };
        toolbarPaint();
        eq('a BOLD cell lights B and nothing else', lit(), ['tb-bold']);
        lastRC = { r: 0, c: 2 };
        toolbarPaint();
        eq('A CELL WHOSE STYLE IS A SHARED ID LIGHTS TOO — the toolbar resolves the style '
           + 'the same way the Format ticks do, because it reads the tick they set',
           lit(), ['tb-italic']);
        lastRC = { r: 0, c: 3 };
        toolbarPaint();
        eq('align-right + wrap light together, and left/centre stay dark',
           lit().sort(), ['tb-alignr', 'tb-wrap']);
        eq('…and the menu ticks say the same thing, because they ARE the same decision',
           ['mi-alignr', 'mi-wrap', 'mi-alignl'].map(id => nodes[id]._tick.textContent),
           ['✓', '✓', '']);

        nodes.findrow.classList.add('on');
        toolbarPaint();
        check('the Find button lights while the find bar is open — the one button whose '
              + 'state is not a menu tick, and it names the element that holds it',
              nodes['tb-find'].classList.contains('on'));
        nodes.findrow.classList.remove('on');
        toolbarPaint();
        check('…and goes dark when it closes', !nodes['tb-find'].classList.contains('on'));

        mode = 'univer';
        toolbarPaint();
        eq('once the RICH EDITOR owns the document every button greys with the tier-1 '
           + 'reason — a toolbar write into a snapshot Univer is not reading would be '
           + 'lost at the next save', [off().length, nodes['tb-bold'].title],
           [buttons.length, T1_ONLY]);
        mode = 'grid';

        // A hidden row does not paint, and showing it repaints — the pair matters,
        // because the first half is only safe if the second half holds.
        current = null;                               // → every row greys at the next paint
        nodes['tb-bold'].disabled = false;
        toolbarSetOpen(false, 'test');
        toolbarPaint();
        check('a HIDDEN toolbar paints nothing at all — there is nothing on screen to be '
              + 'wrong, and painting it would be work per keystroke for no one',
              nodes['tb-bold'].disabled === false);
        toolbarSetOpen(true, 'test');
        check('…and showing it repaints in the same breath, so it can never come back '
              + 'stale — which is what makes the line above safe',
              nodes['tb-bold'].disabled === true);
        current = 'Book.xlsx';
      })();
    }

    /* ══ 13. SUBMENUS — ONE NESTING LEVEL (2026-08-27b) ══════════════════════════
       §7.2: "Google nests with ▸; we ship one flat level with separators. Zoom is five
       sibling rows rather than a Zoom ▸. Worth revisiting when a menu passes ~14 rows."
       The View menu was at fourteen. This is that revisit, and the state machine is
       EXECUTED — every report this page has had about menus was about a menu that stayed
       open or one that closed under the cursor, which is a state machine, and a state
       machine buried in DOM handlers can only be tested by driving a browser. */
    {
      const PAIRS = [...html.matchAll(/\{ row: '(mi-[\w-]+)', pop: '(m-[\w-]+)' \}/g)]
        .map(m => ({ row: m[1], pop: m[2] }));
      eq('the two submenus the slice asked for, declared as DATA like the bar itself',
         PAIRS, [{ row: 'mi-zoom', pop: 'm-zoom' }, { row: 'mi-text', pop: 'm-text' }]);
      PAIRS.forEach(p => {
        check(p.pop + ' is a real flyout in the markup, nested inside a .msubwrap next to '
              + 'its own parent row',
              new RegExp('<div class="msubwrap">\\s*<button class="mi" id="' + p.row
                         + '" aria-haspopup="true">[^<]*<span class="marrow">▸</span>'
                         + '</button>\\s*<div id="' + p.pop + '" class="mpop mfly">')
                .test(html));
      });
      check('the flyout IS a .mpop — same white card, same hairline, same 30px rows, same '
            + 'reserved tick gutter, same shortcut column — moved to the right of its row',
            /\.mpop\.mfly\{[^}]*left:100%/.test(CSS)
            && /\.mpop\.mfly\.flip\{[^}]*right:100%/.test(CSS));
      check('the ▸ marker rides the shortcut column, so a submenu row and a shortcut row '
            + 'have the same silhouette', /\.mpop \.marrow\{[^}]*margin-left:auto/.test(CSS)
            && /\.mpop \.mi:disabled \.marrow\{/.test(CSS));
      check('the parent row stays lit while its child is open', /\.mpop \.mi\.on\{/.test(CSS));
      // ⚠️ THE RULE THE WHOLE FEATURE STANDS ON, and it is why it is asserted over the
      // WHOLE ancestor chain rather than #menus alone: a flyout is absolutely positioned
      // five levels deep, and any ONE of those ancestors with an overflow clips it into
      // nothing — a whole-feature failure with no error message.
      ['#menubar', '#menus', '.mwrap', '.mpop', '.msubwrap']
        .forEach(sel => check('no `overflow` on ' + sel + ' — it would clip the flyouts',
          !new RegExp(sel.replace('.', '\\.') + '\\{[^}]*overflow').test(CSS)));
      check('the five zoom rows MOVED, they were not rewritten: the ids are the ones the '
            + 'wiring loop and the tick loop already used',
            /<div id="m-zoom" class="mpop mfly">[\s\S]{0,700}id="mi-z150"/.test(html)
            && /ZOOMS\.forEach\(z => mi\('mi-z' \+ z/.test(html)
            && /tick\('mi-z' \+ z, zoomNow === z\)/.test(html));
      check('…and so did the four text rows, shortcut column intact',
            /<div id="m-text" class="mpop mfly">[\s\S]{0,900}id="mi-strike"/.test(html)
            && /id="mi-bold"><span class="mtick"><\/span>Bold<span class="mk">⌘B<\/span>/
                 .test(html));
      check('opening on HOVER waits a short delay AND a click opens immediately, which is '
            + 'Google\'s pair', /const SUB_DELAY_MS = \d+/.test(html)
            && /setTimeout\(\(\) => \{ subTimer = null; subGo\('open', s\.pop, 'hover'\)/.test(html)
            && /row\.onclick = ev => \{ ev\.stopPropagation\(\); subGo\('open', s\.pop/.test(html));
      check('…and the delay is short enough not to feel stuck and long enough that '
            + 'sweeping past a row does not fling a card out', num('SUB_DELAY_MS') >= 120
            && num('SUB_DELAY_MS') <= 400);
      check('switching or closing a top-level menu takes the flyout with it, and the '
            + 'flyout closes FIRST — ahead of menuClose\'s early return, or a card could '
            + 'be left floating over the sheet',
            /subApply\(null, 'menu-switch'\)/.test(grab('menuOpen'))
            && grab('menuClose').indexOf("subApply(null, why || 'menu')")
               < grab('menuClose').indexOf('if (openMenu < 0) return;'));
      check('Esc closes ALL of it, through the one close path',
            /k === 'Escape' && openMenu > 0/.test(html));
      check('an outside mousedown still closes the whole bar, and the flyouts live INSIDE '
            + '#menubar so a click in one is not "outside"',
            /const w = el\('menubar'\) \|\| el\('filewrap'\)/.test(html)
            && html.indexOf('<div id="m-zoom"') > html.indexOf('<nav id="menubar">')
            && html.indexOf('<div id="m-zoom"') < html.indexOf('</nav>'));

      // ── the transition function, executed event by event ──
      (function () {
        eval(grab('subNext'));
        eq('a click or a survived hover on a row OPENS its flyout',
           subNext(null, 'open', 'm-zoom'), 'm-zoom');
        eq('…and opening the one that is already open is idempotent, not a toggle: '
           + 'Google\'s submenu parent has no "close" gesture of its own',
           subNext('m-zoom', 'open', 'm-zoom'), 'm-zoom');
        eq('opening the OTHER one closes the first, because only one is ever open',
           subNext('m-zoom', 'open', 'm-text'), 'm-text');
        eq('an `open` with no id leaves what is open alone (a stale timer must not close '
           + 'a card the user has just entered)', subNext('m-text', 'open', null), 'm-text');
        eq('hovering a PEER row of the same dropdown takes the flyout away — without this '
           + 'half a nested menu reads as two unrelated cards',
           subNext('m-zoom', 'peer', null), null);
        eq('…but the parent row is not its own peer', subNext('m-zoom', 'peer', 'm-zoom'),
           'm-zoom');
        ['left', 'esc', 'outside', 'menu'].forEach(ev =>
          eq('`' + ev + '` closes', subNext('m-zoom', ev, null), null));
        eq('AND SO DOES ANYTHING UNRECOGNISED — an event this function has never heard of '
           + 'must not be able to leave a card open over the sheet',
           subNext('m-zoom', 'something-new', 'm-text'), null);
      })();

      // ── the flip, which is arithmetic and therefore testable ──
      (function () {
        eval(grab('subFlip'));
        check('a flyout with room opens to the RIGHT of its row',
              subFlip(200, 400, 176, 1200, 8) === false);
        check('…and flips LEFT when opening right would leave the window',
              subFlip(900, 1100, 176, 1200, 8) === true);
        check('…counting the padding, so it flips just BEFORE it would touch the edge',
              subFlip(900, 1017, 176, 1200, 8) === true
              && subFlip(900, 1016, 176, 1200, 8) === false);
        /* ⚠️ THE CASE FOUND BY DRIVING THE REAL PAGE AT 362px, which is a width this tab
           really gets: the right side overflows AND the left side has no room either. A
           rule that asked only the first question flipped the card to x = -87 — entirely
           off the screen, strictly worse than a clipped right edge. */
        check('…but it does NOT flip when flipping would not help — a card off the left '
              + 'edge is worse than one clipped on the right',
              subFlip(91, 335, 176, 362, 8) === false);
        check('…and it does flip the moment the left side can actually hold it',
              subFlip(184, 335, 176, 362, 8) === true);
        check('an unmeasurable layout does not flip — the default side is the right one',
              subFlip(200, 400, 0, 0, 8) === false
              && subFlip(200, 400, 176, 0, 8) === false);
      })();

      // ── what the ↑ ↓ walk may land on, once there are two cards ──
      (function () {
        let openSub = null;
        const MENUS = ['m-view'];
        function mkRow(id, fly, disabled) {
          return { id: id, disabled: !!disabled,
                   closest: sel => (sel === '.mfly' ? (fly || null) : null),
                   focus() { this.focused = true; } };
        }
        const flyOn = {};
        const fly = { classList: { contains: c => !!flyOn[c] },
                      querySelectorAll: () => flyRows };
        const flyRows = [mkRow('mi-z50', fly), mkRow('mi-z75', fly),
                         mkRow('mi-z100', fly)];
        const topRows = [mkRow('mi-lines', null), mkRow('mi-zoom', null),
                         mkRow('mi-freeze', null, true)];
        const pop = { contains: n => n === fly,
                      querySelectorAll: () => topRows.concat(flyRows) };
        const el = id => (id === 'm-view' ? pop : (id === 'm-zoom' ? fly : null));
        eval(grab('subHidden'));
        eval(grab('menuRows'));

        eq('with the flyout CLOSED the walk sees the parent menu only — a row inside a '
           + 'closed flyout is in the document but not on screen, and a walk that stopped '
           + 'on one would focus something invisible',
           menuRows(0).map(r => r.id), ['mi-lines', 'mi-zoom']);
        openSub = 'm-zoom'; flyOn.on = true;
        eq('with it OPEN the walk belongs to the FLYOUT, not to both cards at once — '
           + 'Google\'s arrows always walk the innermost open menu',
           menuRows(0).map(r => r.id), ['mi-z50', 'mi-z75', 'mi-z100']);
        openSub = null; flyOn.on = false;
        eq('and a disabled row is still skipped either way, as it always was',
           menuRows(0).filter(r => r.id === 'mi-freeze').length, 0);
      })();

      // ── the apply half: one open at a time, the parent lit, one beacon per change ──
      (function () {
        const SUBS = PAIRS;
        const beacons = [];
        function bx(stage, detail) { beacons.push(stage + ':' + (detail || '')); }
        function mkNode() {
          const cls = {};
          return { classList: {
            toggle(c, on) { cls[c] = on === undefined ? !cls[c] : !!on; return !!cls[c]; },
            contains: c => !!cls[c], add(c) { cls[c] = true; }, remove(c) { cls[c] = false; } } };
        }
        const nodes = {};
        SUBS.forEach(s => { nodes[s.row] = mkNode(); nodes[s.pop] = mkNode(); });
        const el = id => nodes[id] || null;
        let openSub = null, subTimer = null;
        const clearTimeout = () => {};
        eval(grab('subNext'));
        eval(grab('subApply'));
        eval(grab('subGo'));
        // ⚠️ the placement half is measured against a real window, so it is stubbed here
        // and its arithmetic is tested above, on its own, where it can be.
        function subPlace() { nodes._placed = (nodes._placed || 0) + 1; }

        subGo('open', 'm-zoom', 'click');
        check('opening puts the card on screen and LIGHTS its parent row',
              nodes['m-zoom'].classList.contains('on')
              && nodes['mi-zoom'].classList.contains('on'));
        check('…and positions it, once', nodes._placed === 1);
        subGo('open', 'm-text', 'hover');
        check('opening the other one closes the first and moves the light with it',
              nodes['m-text'].classList.contains('on')
              && !nodes['m-zoom'].classList.contains('on')
              && !nodes['mi-zoom'].classList.contains('on'));
        subGo('peer', null, 'peer');
        check('a peer hover closes everything', !nodes['m-text'].classList.contains('on')
              && !nodes['mi-text'].classList.contains('on') && openSub === null);
        beacons.length = 0;
        subGo('peer', null, 'peer');
        eq('…and a close that changes nothing is NOT beaconed: hover fires this dozens of '
           + 'times a sweep, and the boot beacon\'s 80-send budget is the reason the bar '
           + 'reports its first open only', beacons.length, 0);
        subGo('open', 'm-zoom', 'click');
        eq('…while a real change is', beacons.filter(b => /^submenu:m-zoom/.test(b)).length, 1);
      })();
    }

    /* ══ THE BUSY LATCH, AND THE SILENT-GUARD CLASS ════════════════════════════
       THE JOURNEY THIS PINS (Debi, 2026-08-29, five failed clicks): the LOffice file
       list's Delete did nothing at all, five times running. The bridge was fine and the
       confirm banner rendered — what swallowed it was `remove()`'s first line,
       `if (busy) return;`, reading a latch that had stuck true earlier in the session.
       No message, no beacon, no spinner. A click that does NOTHING is the dead-end
       class, and this section is the gate that keeps it dead:

         · the latch cannot stick (busyOn arms a watchdog; every reset goes through
           busyOff, and a cross-frame call that never settles loses a race),
         · and no user action reads it silently ever again (busyBlock speaks).

       The functions are EXECUTED here, not grepped, because "the guard says something"
       is a behaviour and a regex would pass against a sentence that never renders. */
    await (async () => {
      var busy = false, busyWhat = '', busyAt = 0, busyTimer = 0, busyGen = 0;
      var said = [], beacons = [], painted = 0, rendered = 0;
      // The page's collaborators, reduced to what these five functions actually touch.
      function say(text, kind) { said.push([String(text || ''), kind || null]); }
      function bx(stage, detail) { beacons.push(stage + ':' + (detail === undefined ? '' : detail)); }
      function paint() { painted++; }
      function renderFiles() { rendered++; }
      const nap = (ms) => new Promise(r => setTimeout(r, ms));

      eval(grabConsts('BUSY_MAX_MS', 'OO_RPC_MS'));
      eval(grab('busyOn'));
      eval(grab('busyOff'));
      eval(grab('busyWatchdog'));
      eval(grab('busyBlock'));
      eval(grab('ooCall'));

      // ── the budgets are ordered, and the order is the design ──
      // The RPC race must expire INSIDE the editor watchdog's budget, so the normal
      // stuck-editor case gets ooCall's honest "the editor did not answer" sentence and
      // the watchdog stays what it is: the last resort that should never be reached.
      check('the editor budget is longer than a bridge call\'s', BUSY_MAX_EDITOR_MS > BUSY_MAX_MS);
      check('and the cross-frame RPC gives up INSIDE it, so the honest sentence wins the '
            + 'race against the watchdog', OO_RPC_MS < BUSY_MAX_EDITOR_MS);

      // ── 1. the ordinary round trip ──
      busyOn('deleting “a.xlsx”');
      check('busyOn sets the latch', busy === true);
      eq('…and names the operation in the user\'s words, for busyBlock to quote back',
         busyWhat, 'deleting “a.xlsx”');
      check('…and beacons it', beacons.some(b => b === 'busy-on:deleting “a.xlsx”'));
      busyOff();
      check('busyOff clears it', busy === false);
      check('…and disarms the watchdog with it', busyTimer === 0);

      // ── 2. THE FIX FOR THE STUCK LATCH: the watchdog ──
      said.length = 0; beacons.length = 0;
      // ⚠️ 1ms is not a legal budget: busyOn floors it at 1000ms on purpose, so a caller
      // that passes nonsense cannot turn the safety net into a self-tripping wire. The
      // test therefore waits out the real floor rather than pretending it isn't there.
      busyOn('saving “a.xlsx”', 1);
      await nap(1200);
      check('a latch nothing ever resets is cleared by the watchdog', busy === false);
      check('…and the page is repainted so the buttons come back', painted > 0 && rendered > 0);
      check('…and it SAYS so, naming the operation and the wait',
            said.length === 1 && /gave up waiting on saving “a\.xlsx”/.test(said[0][0]));
      check('…and it refuses to claim the operation failed — it says what is NOT known',
            /NOT known/.test(said[0][0]));
      check('…and it beacons the defect it just papered over',
            beacons.some(b => /^busy-watchdog:saving/.test(b)));

      // ── 3. …and it NEVER fires on a healthy page ──
      // The subtle way a watchdog becomes a bug of its own: firing on generation N while
      // generation N+1 is legitimately running, and unlocking a page mid-write.
      said.length = 0; beacons.length = 0;
      busyOn('opening “a.xlsx”', 1);      // floored to 1000ms — see above
      busyOff();
      busyOn('saving “a.xlsx”', 30000);
      await nap(1200);
      check('an operation that finished cannot have its watchdog fire on the NEXT one',
            busy === true && !beacons.some(b => /^busy-watchdog/.test(b)) && said.length === 0);
      busyOff();

      // ── 4. THE SILENT GUARD IS GONE ──
      said.length = 0; beacons.length = 0;
      check('busyBlock lets an action through when the page is idle',
            busyBlock('deleting “a.xlsx”') === false);
      eq('…saying nothing at all while it does', said.length, 0);
      busyOn('saving “a.xlsx”', 30000);
      check('…and stops it when the page is busy', busyBlock('deleting “a.xlsx”') === true);
      check('…having first told the user BOTH halves: what is running, and what was asked',
            said.length === 1 && /saving “a\.xlsx”/.test(said[0][0])
            && /deleting “a\.xlsx”/.test(said[0][0]));
      check('…and promised it will work — a guard is a WAIT, not a refusal',
            /in a moment/.test(said[0][0]));
      check('…and beaconed the block, so a stuck latch is visible in the beacon trail '
            + 'instead of being reconstructed from a user saying "nothing happened"',
            beacons.some(b => /^busy-block:deleting/.test(b)));
      busyOff();

      // ── 5. ooCall: the cross-frame promise that never settles ──
      // THE ACTUAL UNRESETTABLE PATH. `ooChild.save()` is a promise from the iframe's
      // realm; re-point or reload that frame and it neither resolves nor rejects, for
      // ever. `finally` never runs on a promise that never settles, which is why this
      // race exists and why the watchdog above is a SECOND net rather than the only one.
      eq('ooCall passes the child\'s answer straight through',
         await ooCall('save', () => Promise.resolve({ ok: true, bytes: 42 }), 500),
         { ok: true, bytes: 42 });
      const rej = await ooCall('save', () => Promise.reject(new Error('x2t died')), 500);
      check('a rejecting child becomes a result, never an unhandled rejection',
            rej.ok === false && /x2t died/.test(rej.error));
      const thr = await ooCall('save', () => { throw new Error('the frame is gone'); }, 500);
      check('…and so does a SYNCHRONOUS throw across the frame boundary',
            thr.ok === false && /the frame is gone/.test(thr.error));
      const never = await ooCall('save', () => new Promise(() => {}), 1);   // floored to 1000ms
      check('AND A PROMISE THAT NEVER SETTLES RESOLVES ANYWAY — the whole point',
            never.ok === false && /did not answer in/.test(never.error));
      check('…in the editor\'s own terms, not a stack trace', /reloading/.test(never.error));
      /* ⚠️ AND THE TIMEOUT IS MARKED AS A TIMEOUT (adversarial finding, 2026-08-29).
         "We stopped waiting" and "it failed" are DIFFERENT FACTS, and ooSave's failure
         sentence ends "the workbook on disk was not changed" — which after a timeout is
         a claim nobody can make: the editor's save may land a second later. Reporting it
         as a failure is the LIE-TO-USER class, and it is the sentence a user acts on
         when deciding whether to retype. So the flag exists and the sentences branch. */
      check('a timeout is FLAGGED as one, distinct from a real failure',
            never.timedOut === true && rej.timedOut !== true && thr.timedOut !== true);

      // ── 6. the walked journey, in one line of state ──
      // A stuck latch, then a Delete click. Before the fix this was `return;`.
      said.length = 0;
      busyOn('making the PDF of “a.xlsx”', 30000);     // the shape of Debi's stuck page
      const blocked = busyBlock('deleting “a.xlsx”');
      check('THE LIVE BUG: Delete on a stuck page is answered, not swallowed',
            blocked === true && said.length === 1);
      busyOff();
      said.length = 0;
      check('…and once the latch clears, the very next Delete click goes through',
            busyBlock('deleting “a.xlsx”') === false && said.length === 0);
    })();

    /* ── the class, pinned in the SOURCE ──────────────────────────────────────
       Behaviour tests above prove the helpers work. This proves nobody quietly adds a
       sixteenth silent guard next month: there is exactly ONE `busy` early-return left
       in office.html that says nothing, it is the heartbeat, and it is commented as
       such. Every other one is a busyBlock() or an actNote(). */
    {
      const office = html;
      /* ⚠️ COMMENTS OUT FIRST, AND IT IS NOT FUSSiness: this file DOCUMENTS the old
         `if (busy) return;` in three separate comment blocks, quoting the exact line
         this test exists to ban. A scan over raw source finds those quotations and
         "fails" against prose — which is how a gate teaches people to delete the
         comments instead of keeping the fix. Blank-fill rather than delete, so the
         surviving lines keep their real shape. */
      const code = office.replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
                         .replace(/^([ \t]*)\/\/.*$/gm, '$1');
      const silent = [];
      const re = /^.*\bbusy\b.*\breturn\b.*$/gm;
      let m;
      while ((m = re.exec(code))) {
        const line = m[0];
        if (!/if\s*\(/.test(line)) continue;
        // Answers the user in some voice → not silent.
        if (/busyBlock|aiBusyBlock|actNote|say\(/.test(line)) continue;
        // A PREDICATE, not a guard: these compute an enabled/disabled state for paint().
        if (/return (false|true)\b/.test(line)) continue;
        // busyWatchdog's own re-entrancy check, and the changeset CARD's own state
        // machine (`card._state === 'busy'` is the card's latch, not the page's, and its
        // buttons are `disabled` in exactly that state).
        if (/busyGen|card\._state/.test(line)) continue;
        silent.push(line.trim());
      }
      eq('exactly ONE silent busy guard survives in office.html — the extCheck '
         + 'heartbeat, which nobody clicked (every other one now speaks)',
         silent, ['if (!current || busy || extAsking) return null;']);
      check('…and it carries the comment saying WHY silence is right there',
            /THE ONE SILENT `busy` GUARD LEFT IN THIS FILE, AND IT IS DELIBERATE/.test(office));

      // The five-failed-clicks line itself, by name.
      // ⚠️ read off the COMMENT-STRIPPED source: remove()'s own header quotes the banned
      // line verbatim, which is the point of the header.
      const removeSrc = code.slice(code.indexOf('async function remove(name, backups)'),
                                   code.indexOf('const madeThisSession'));
      check('remove() — THE five-failed-clicks function — opens with busyBlock, and the '
            + 'bare silent guard is gone from its code',
            /if \(busyBlock\('deleting/.test(removeSrc)
            && !/if \(busy\) return;/.test(removeSrc));
      check('…and every busy mutation in the page goes through busyOn/busyOff/'
            + 'busyWatchdog, so the watchdog can never be bypassed by a stray assignment',
            (code.match(/(?<!ai)\bbusy = (true|false)/g) || []).length === 4);   // 1 decl + 3 in the manager
      check('remove() reports its own success — a row vanishing from a list is not a '
            + 'sentence, and "did it even do anything?" was a fair question',
            /say\('Deleted /.test(grab('remove')));
      check('…and beacons both outcomes', /bx\('delete-ok'/.test(grab('remove'))
            && /bx\('delete-fail'/.test(grab('remove')));
      check('the editor RPCs are RACED, never bare-awaited: save, downloadPdf, open, reload',
            /ooCall\('save'/.test(office) && /ooCall\('downloadPdf'/.test(office)
            && /ooCall\('open'/.test(office) && /ooCall\('reload'/.test(office));
      check('ooSave resets the latch in a `finally`, so a throw cannot strand it',
            /finally \{ busyOff\(\); paint\(\); \}/.test(grab('ooSave')));
      check('…and so does ooDownloadPdf',
            /finally \{ busyOff\(\); paint\(\); \}/.test(grab('ooDownloadPdf')));
      // The download-first path is EXISTING behaviour and stays: downloading is not
      // answering the question, so the question comes back.
      check('“Download it first” still re-arms the delete question rather than answering it',
            /setTimeout\(\(\) => deleteAsk\(n, opts\), 400\)/.test(grab('deleteAsk')));
      check('the AI panel\'s latch echoes the same fix (doctrine 6b)',
            /if \(aiBusyBlock\(\)\) return;/.test(grab('aiSend'))
            && /if \(aiBusyBlock\(\)\) return;/.test(grab('agentSend')));

      // ── the two adversarial findings the busy fix itself produced ──
      {
        const ooS = grab('ooSave'), ooP = grab('ooDownloadPdf');
        check('a TIMED-OUT save does not tell the user their work was not written — '
              + '"we stopped waiting" is not "it failed", and this is the sentence they '
              + 'act on when deciding whether to retype',
              /if \(r && r\.timedOut\)/.test(ooS)
              && /does NOT mean it failed/.test(ooS)
              && ooS.indexOf('r.timedOut') < ooS.indexOf('the workbook on disk was not changed'));
        check('…and a timed-out PDF does not claim nothing was downloaded, when it may '
              + 'land in Downloads a moment later',
              /if \(r && r\.timedOut\)/.test(ooP)
              && ooP.indexOf('r.timedOut') < ooP.indexOf('Nothing was downloaded'));
        check('…and a 409 is still answered inside the editor frame, not twice',
              /r\.status !== 409/.test(ooS));
      }
      {
        /* THE STRANDED BANNER. extAsking used to be un-stuck only by a BLANK message
           line, so any say() that replaced the external-change banner with a different
           sentence retired the agent-write watch for the rest of the session — and
           busyBlock() puts up exactly such a sentence. Identity, not emptiness. */
        const ec = grab('extCheck'), ea = grab('extAct'), sy = grab('say');
        check('every say() bumps msgGen, blank ones included — a cleared strip is a '
              + 'different message, not the absence of one', /^\s*msgGen\+\+;/m.test(sy));
        check('…the external-change banner records WHICH message it is',
              /extMsgGen = msgGen;/.test(ea));
        check('…and extCheck un-sticks its latch when something REPLACED the banner, not '
              + 'only when the strip was left blank',
              /extAsking && msgGen !== extMsgGen/.test(ec)
              && !/extAsking && !el\('msg'\)\.textContent/.test(ec));
      }
    }

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
