/* LOFFICE — the chrome-scope fix and the AI side panel (2026-08-21)
 *
 * TWO GAPS, ONE FILE, because they share a page.
 *
 * GAP 1 — "some things are barely visible … looks weird, still seems barebones."
 *   ROOT CAUSE, measured in a real engine (headless Chromium, getComputedStyle) and
 *   not guessed at: THIS PAGE'S OWN STYLESHEET was reaching into Univer's DOM.
 *     · `header{background:var(--bg2)}` — a BARE TYPE SELECTOR — painted Univer's own
 *       <header> (its ribbon bar) with our #0e0c15, and Univer's black <input> text
 *       ("Arial", "11") then sat on it at 1.08:1.
 *     · `body{color:var(--fg)}` inherited our cream #efe9dc into Univer's menu items,
 *       which set no colour of their own, over their white menu ground: 1.21:1.
 *       Ten menu rows measured at 1.21.
 *   Univer's menus are portalled into an ANONYMOUS `body > div` with no id and no
 *   class, so nothing could be scoped there after the fact — the ink and the chrome
 *   had to stop belonging to the document and start belonging to our own regions.
 *   AFTER: 'Arial' 1.08 → 21:1, the menus 1.21 → 21:1, worst Univer node 5.34:1.
 *
 *   The fence in this file is the part that matters: a test that a bare type selector
 *   CANNOT come back. Greps prove a rule exists; this proves a whole CLASS of rule
 *   does not.
 *
 * GAP 2 — "no way to load model or use model there, which defeats the purpose."
 *   The slice-2 stub is a working chat over the harness's EXISTING direct lane. The
 *   load-bearing invariants: it invents no endpoint, it sends no session (so it can
 *   never pollute or retitle a chat in Mission Control), the sheet it sends is capped
 *   and shown to the user verbatim, and NOTHING it does writes into the spreadsheet.
 *
 * Run: node bridge/tests/test_office_ai.js
 */
// ⚠️ deliberately NOT 'use strict' — a direct eval() in strict mode gets its own
// scope, so the extract-and-execute pattern would define each function and instantly
// throw it away. Same reason as test_office_grid.js.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'office.html'), 'utf8');
const panel = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');

let pass = 0;
const fails = [];
function check(name, cond) { if (cond) { pass++; } else { fails.push(name); } }
function eq(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) { pass++; } else { fails.push(`${name}  (got ${a}, want ${b})`); }
}
function near(name, got, want, tol) {
  if (Math.abs(got - want) <= tol) { pass++; } else { fails.push(`${name}  (got ${got}, want ~${want})`); }
}

// ── the extractor (string/comment/template aware) ────────────────────────────
function grabFrom(src, name, label) {
  const at = src.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in ' + label);
  const stack = [];
  let depth = 0, prev = '';
  for (let j = src.indexOf('{', at); j < src.length; j++) {
    const c = src[j], top = stack[stack.length - 1], bs = prev === '\\';
    const t = top && top.t;
    if (t === 'sq' || t === 'dq') {
      if (!bs && c === (t === 'sq' ? "'" : '"')) stack.pop();
    } else if (t === 'tpl') {
      if (!bs && c === '`') stack.pop();
      else if (!bs && c === '$' && src[j + 1] === '{') { stack.push({ t: 'itp', d: depth }); j++; }
    } else {
      if (c === '/' && src[j + 1] === '/') { j = src.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && src[j + 1] === '*') { j = src.indexOf('*/', j) + 1; if (j < 1) break; prev = '/'; continue; }
      if (c === "'") stack.push({ t: 'sq' });
      else if (c === '"') stack.push({ t: 'dq' });
      else if (c === '`') stack.push({ t: 'tpl' });
      else if (c === '{') depth++;
      else if (c === '}') {
        if (t === 'itp' && depth === top.d) stack.pop();
        else if (--depth === 0) return src.slice(at, j + 1);
      }
    }
    prev = bs ? '' : c;
  }
  throw new Error('unbalanced braces extracting ' + name + ' from ' + label);
}
const grab = n => grabFrom(html, n, 'office.html');

// Constants are READ OUT OF THE PAGE. A value changed there must not keep passing
// against a stale copy written down here.
function num(name) {
  const m = html.match(new RegExp('\\b' + name + '\\s*=\\s*(\\d+(?:\\.\\d+)?)'));
  if (!m) throw new Error('constant ' + name + ' not found in office.html');
  return parseFloat(m[1]);
}

// ⚠️ A COMMENT IS NOT CODE, and half the assertions below are negatives ("this page
// contains no such call"). Without this, a comment SAYING "there must never be an
// /api/office/chat" would fail the test asserting there isn't one — a negative that
// can be defeated by explaining it is worse than no negative at all.
function stripComments(src) {
  let out = '', st = null, prev = '';
  for (let i = 0; i < src.length; i++) {
    const c = src[i], bs = prev === '\\';
    if (st === 'sq' || st === 'dq' || st === 'tpl') {
      out += c;
      if (!bs && c === (st === 'sq' ? "'" : st === 'dq' ? '"' : '`')) st = null;
    } else if (st === 'line') {
      if (c === '\n') { st = null; out += c; }
    } else if (st === 'blk') {
      if (c === '*' && src[i + 1] === '/') { st = null; i++; }
    } else if (c === '/' && src[i + 1] === '/') { st = 'line'; i++; }
    else if (c === '/' && src[i + 1] === '*') { st = 'blk'; i++; }
    else {
      out += c;
      if (c === "'") st = 'sq'; else if (c === '"') st = 'dq'; else if (c === '`') st = 'tpl';
    }
    prev = bs ? '' : c;
  }
  return out;
}
const code = stripComments(html);
eq('the comment stripper removes both comment forms',
   stripComments('a // b\nc /* d */ e'), 'a \nc  e');
eq('…and leaves a // inside a string alone',
   stripComments("var u = 'http://x'; // gone"), "var u = 'http://x'; ");

/* ══════════════════════════════════════════════════════════════════════════════
   PART 1 — THE SCOPE FENCE
   ═════════════════════════════════════════════════════════════════════════════ */

const styleAt = html.indexOf('<style>');
const styleEnd = html.indexOf('</style>', styleAt);
check('office.html has exactly one stylesheet', styleAt > 0 && styleEnd > styleAt
      && html.indexOf('<style>', styleEnd) < 0);
// comment-stripped, because comment prose otherwise glues onto the next selector and
// every selector test silently measures nothing (a defect this repo has had before).
const css = html.slice(styleAt + 7, styleEnd).replace(/\/\*[\s\S]*?\*\//g, '');

// top-level comma split — `:where(a,b,c)` is ONE part, not three
function splitTop(sel) {
  const out = [];
  let depth = 0, cur = '';
  for (const c of sel) {
    if (c === '(') depth++;
    else if (c === ')') depth--;
    if (c === ',' && depth === 0) { out.push(cur); cur = ''; continue; }
    cur += c;
  }
  if (cur.trim()) out.push(cur);
  return out.map(s => s.trim()).filter(Boolean);
}
const rules = [];
{
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) rules.push({ sel: m[1].trim(), body: m[2].trim() });
}
check('the stylesheet parsed into rules', rules.length > 40);

// THE FENCE. A selector part is "anchored" if it names one of our ids or classes, or
// is rooted at the document (html / body / a direct child of body). Anything else is a
// bare type selector, and a bare type selector in this page reaches into Univer.
const ROOTED = /^(html|body|:root)\b/;
function anchored(part) {
  if (part.indexOf('#') >= 0 || part.indexOf('.') >= 0) return true;
  return ROOTED.test(part);
}
const bare = [];
rules.forEach(r => splitTop(r.sel).forEach(p => { if (!anchored(p)) bare.push(p); }));
eq('NO bare type selector survives in office.html — the exact class of rule that '
   + 'painted Univer\'s ribbon with our background', bare, []);
// …and prove the fence can actually fire, so it is not passing vacuously.
check('the fence would catch a re-introduced bare selector',
      !anchored('header') && !anchored('button:hover') && !anchored('input')
      && anchored('body>header') && anchored('#files button') && anchored('.lnk')
      && anchored(':where(#boot,body>header) button'));

check('`body` no longer declares a colour — that inheritance was reaching a third '
      + 'party we do not control',
      rules.filter(r => splitTop(r.sel).indexOf('body') >= 0)
           .every(r => !/(^|;)\s*color\s*:/.test(r.body)));
check('…and our cream is re-declared on our own regions instead',
      rules.some(r => /^:where\(#boot,body>header/.test(r.sel) && /color:var\(--fg\)/.test(r.body)));
check('the button rules are scoped to our regions',
      rules.filter(r => /(^|\s)button(\s|$|[:.])/.test(r.sel))
           .every(r => /:where\(/.test(r.sel) || /#/.test(r.sel)));

// SPECIFICITY IS UNCHANGED, and that is why `:where()` and not a plain ancestor list:
// `#files button` would be (1,0,1) and would beat `.lnk` (0,1,0), turning the file
// row's download/delete links into boxes. Computed here rather than asserted.
function spec(sel) {
  const s = sel.replace(/:where\([^)]*\)/g, ' ');       // :where() contributes nothing
  const ids = (s.match(/#[\w-]+/g) || []).length;
  const cls = (s.match(/(?:\.[\w-]+|\[[^\]]*\]|:(?!:)(?!where)[\w-]+(?:\([^)]*\))?)/g) || []).length;
  const typ = (s.match(/(?:^|[\s>+~])[a-zA-Z][\w-]*/g) || []).length;
  return [ids, cls, typ];
}
const cmp = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]);
// A missing rule must FAIL, not throw: a crashed test is a test nobody reads.
const btnRule = rules.find(r => /\)\s*button$/.test(r.sel)) || { sel: '#none button' };
check('the base button rule is scoped with :where()', /:where\(/.test(btnRule.sel));
eq('…and carries the specificity of a bare `button` — (0,0,1) — because of :where()',
   spec(btnRule.sel), [0, 0, 1]);
check('…so `.lnk` (0,1,0) still beats it, and the file rows stay text links',
      cmp(spec('.lnk'), spec(btnRule.sel)) > 0);
const prim = rules.find(r => /button\.primary$/.test(r.sel));
check('…and `button.primary` still wins its cream fill',
      prim && cmp(spec(prim.sel), spec(btnRule.sel)) > 0);
const gb = rules.find(r => /^#gridbar button$/.test(r.sel));
check('…and `#gridbar button` still wins its own light chrome',
      gb && cmp(spec(gb.sel), spec(btnRule.sel)) > 0);
check('our header rule is a DIRECT child of body, which Univer\'s nested <header> '
      + 'can never be', rules.some(r => /^body>header$/.test(r.sel)));

// The theme decision, recorded as a test so the next reader knows it was a decision.
check('Univer stays on its LIGHT theme — a spreadsheet is a white page, and every '
      + 'fill and font colour inside a .xlsx was chosen against one',
      /darkMode:\s*false/.test(html) && !/darkMode:\s*true/.test(html));
check('…and BOTH tiers render that same white surface, so pressing "Rich editor" '
      + 'does not change what the document looks like',
      rules.some(r => r.sel === '#gridwrap' && /background:#fff/.test(r.body))
      && rules.some(r => r.sel === '#sheet' && /background:#fff/.test(r.body)));
check('…with a deliberate 1px seam where our dark chrome meets it',
      rules.filter(r => r.sel === '#gridwrap' || r.sel === '#sheet')
           .every(r => /box-shadow:inset[^;]*var\(--line2\)/.test(r.body)));

// ── the runtime chrome probe ────────────────────────────────────────────────
eval(grab('cssRgb')); eval(grab('relLum')); eval(grab('contrast')); eval(grab('overBg'));
eq('cssRgb parses rgb()', cssRgb('rgb(255, 255, 255)'), { r: 255, g: 255, b: 255, a: 1 });
eq('cssRgb parses rgba() with its alpha', cssRgb('rgba(16, 16, 16, 0.3)'),
   { r: 16, g: 16, b: 16, a: 0.3 });
eq('cssRgb refuses junk rather than inventing a colour',
   [cssRgb(''), cssRgb(null), cssRgb('transparent'), cssRgb('rgb(a,b,c)')],
   [null, null, null, null]);
near('contrast(black, white) is the 21:1 maximum', contrast({ r: 0, g: 0, b: 0 }, { r: 255, g: 255, b: 255 }), 21, 0.01);
near('contrast is symmetric', contrast({ r: 255, g: 255, b: 255 }, { r: 0, g: 0, b: 0 }), 21, 0.01);
near('a colour against itself is 1:1', contrast({ r: 90, g: 90, b: 90 }, { r: 90, g: 90, b: 90 }), 1, 0.001);
// THE MEASURED BUG, reproduced from the numbers the browser actually reported.
near('the reported symptom, in numbers: our cream ink on Univer\'s white menu',
     contrast(cssRgb('rgb(239, 233, 220)'), cssRgb('rgb(255, 255, 255)')), 1.21, 0.02);
near('…and Univer\'s black input text on the background our `header` rule painted',
     contrast(cssRgb('rgb(0, 0, 0)'), cssRgb('rgb(14, 12, 21)')), 1.08, 0.02);
check('…both of which are far below the AA floor this page now measures against',
      contrast(cssRgb('rgb(239, 233, 220)'), cssRgb('rgb(255, 255, 255)')) < 4.5
      && contrast(cssRgb('rgb(0, 0, 0)'), cssRgb('rgb(14, 12, 21)')) < 4.5);
near('AFTER the fix the same ink is black on white: 21:1',
     contrast(cssRgb('rgb(0, 0, 0)'), cssRgb('rgb(255, 255, 255)')), 21, 0.01);
// alpha compositing: without it a 30%-alpha grey reads as 19:1, i.e. the probe lies
const white = { r: 255, g: 255, b: 255, a: 1 };
check('translucent ink is composited before measuring, or the probe flatters it',
      contrast(overBg(cssRgb('rgba(16, 16, 16, 0.3)'), white), white) < 2.5
      && contrast(cssRgb('rgba(16, 16, 16, 0.3)'), white) > 15);
eq('opaque ink is returned unchanged by the compositor',
   overBg({ r: 10, g: 20, b: 30, a: 1 }, white), { r: 10, g: 20, b: 30, a: 1 });

const cp = grab('chromeProbe');
eq('the probe measures against the WCAG AA floor', num('CHROME_MIN_RATIO'), 4.5);
check('chromeProbe reads <input> and <button>, not just text nodes — the ribbon\'s '
      + 'font name and size ARE inputs, which is exactly what the first probe missed',
      /querySelectorAll\('input,textarea,button,label,span,a'\)/.test(cp));
check('…skips disabled controls, which are supposed to be grey (WCAG 1.4.3 exempts '
      + 'them; Univer greys undo/redo at 2.19:1 on a fresh sheet)',
      /n\.disabled === true/.test(cp) && /aria-disabled/.test(cp));
check('…composites alpha', /overBg\(fg, bg\)/.test(cp));
check('…and says BELOW-AA in the beacon when it is', /BELOW-AA/.test(cp));
check('chromeProbe is a pure observer: it writes nothing to the page',
      !/\.textContent\s*=/.test(cp) && !/classList/.test(cp) && !/innerHTML/.test(cp)
      && !/fetch\(/.test(cp));
check('it runs on the settled mount, beside the canvas probe, so one log line answers '
      + '"is the ribbon legible"', /canvasProbe\('mount-settled'\);\s*\n\s*chromeProbe\('chrome-contrast'\)/.test(html));

/* ══════════════════════════════════════════════════════════════════════════════
   PART 2 — THE AI SIDE PANEL
   ═════════════════════════════════════════════════════════════════════════════ */

check('the "coming in slice 2" placeholder is gone from the served document',
      html.indexOf('coming in slice 2') < 0);
check('the rail has a real composer, a send button and a model readout',
      /id="ai-in"/.test(html) && /id="ai-send"/.test(html) && /id="ai-model"/.test(html));
check('…a collapse control and a re-open strip', /id="ai-hide"/.test(html) && /id="ai-tab"/.test(html));

// ── the model readout ────────────────────────────────────────────────────────
eval(grab('officeModelLabel'));
const lane = grabFrom(panel, 'laneModelLabel', 'index.html');
eval(lane.replace('function laneModelLabel', 'function laneModelLabelRef'));
const MODEL_TABLE = [
  ['fake-coder-7b', true, '', 'fake-coder-7b'],
  ['fake-coder-7b', false, '', ''],
  [null, true, '', ''],
  ['', true, 'org/model-name', 'model-name'],
  ['', false, 'org/model-name', 'model-name'],
  ['  spaced  ', true, '', 'spaced'],
  [undefined, false, 'plain', 'plain'],
  ['', false, 'org/sub/leaf/', 'leaf'],
  ['', false, '', ''],
];
MODEL_TABLE.forEach(([live, running, echo, want]) => {
  eq(`officeModelLabel(${JSON.stringify(live)}, ${running}, ${JSON.stringify(echo)})`,
     officeModelLabel(live, running, echo), want);
});
check('officeModelLabel answers IDENTICALLY to the panel\'s own laneModelLabel — one '
      + 'rule for "what model is live", not two that can drift',
      MODEL_TABLE.every(([l, r, e]) => officeModelLabel(l, r, e) === laneModelLabelRef(l, r, e)));
check('it reads the runner off the status the panel already polls',
      /components\.runner/.test(grab('aiRefreshModel'))
      && /fetch\('\/api\/status'/.test(grab('aiRefreshModel')));
check('with no model loaded it SAYS so and names where to fix it',
      /No model is loaded/.test(grab('aiRefreshModel'))
      && /Models/.test(grab('aiRefreshModel')));
check('…and Ask is disabled rather than failing on click',
      /el\('ai-send'\)\.disabled = aiBusy \|\| !aiModel/.test(grab('aiPaint')));
check('a status fetch that throws leaves the model UNKNOWN rather than claiming one',
      /catch[\s\S]{0,200}aiModel = ''/.test(grab('aiRefreshModel')));

// ── the context builder ──────────────────────────────────────────────────────
const AI_CTX_ROWS = num('AI_CTX_ROWS'), AI_CTX_COLS = num('AI_CTX_COLS'),
      AI_CTX_CHARS = num('AI_CTX_CHARS');
check('the caps are the ones the brief asked for (≤200 rows × 30 cols, ≤20k chars)',
      AI_CTX_ROWS === 200 && AI_CTX_COLS === 30 && AI_CTX_CHARS === 20000);
const CV_STRING = num('CV_STRING'), CV_NUMBER = num('CV_NUMBER'), CV_BOOLEAN = num('CV_BOOLEAN');
eval(grab('colName')); eval(grab('a1')); eval(grab('cellAt')); eval(grab('valueText'));
eval(grab('displayText')); eval(grab('usedExtent')); eval(grab('ctxCellText'));
eval(grab('buildContext'));
let snap = null;                     // displayText/styleCss read this global; unused here

eq('a1 is A1 notation', [a1(0, 0), a1(2, 1), a1(0, 26), a1(9, 27)], ['A1', 'B3', 'AA1', 'AB10']);
eq('a1 refuses a negative or non-finite coordinate rather than inventing a cell',
   [a1(-1, 0), a1(0, -1), a1(NaN, 0), a1(0, undefined)], ['', '', '', '']);

function sheetOf(cells, name) {
  const cd = {};
  cells.forEach(([r, c, cell]) => { (cd[String(r)] = cd[String(r)] || {})[String(c)] = cell; });
  return { sheets: { s1: { name: name || 'Sheet1', cellData: cd } } };
}
const wb = sheetOf([
  [0, 0, { v: 'Region', t: CV_STRING }], [0, 1, { v: 'Sales', t: CV_STRING }],
  [1, 0, { v: 'North', t: CV_STRING }], [1, 1, { v: 120, t: CV_NUMBER }],
  [2, 0, { v: 'South', t: CV_STRING }], [2, 1, { v: 90, t: CV_NUMBER }],
  [3, 1, { f: '=SUM(B2:B3)', v: 210, t: CV_NUMBER }],
]);
const ctx = buildContext(wb, 's1', 'B4', 'Sales.xlsx');
eq('the context reports the used extent', [ctx.rows, ctx.cols], [4, 2]);
check('…names the file and the sheet', /File: Sales\.xlsx/.test(ctx.text)
      && /Sheet: Sheet1/.test(ctx.text));
check('…states the used range in A1 terms', /used range A1:B4/.test(ctx.text));
check('…tells the model which cell the user is on', /cell B4 selected/.test(ctx.text));
check('…lays the grid out with column letters and row numbers',
      /\n\tA\tB\n1\tRegion\tSales\n2\tNorth\t120\n3\tSouth\t90\n4\t\t=SUM\(B2:B3\)/.test(ctx.text));
check('a formula travels as its FORMULA, not as its cached number — that is what a '
      + 'question about a spreadsheet is usually about',
      ctx.text.indexOf('=SUM(B2:B3)') > 0 && ctx.text.indexOf('\t210') < 0);
check('nothing is truncated for a four-row sheet', ctx.truncated === false);

// tabs and newlines inside a value would break the row shape the model is told about
const messy = sheetOf([[0, 0, { v: 'a\tb\nc\r\nd', t: CV_STRING }], [0, 1, { v: 'ok', t: CV_STRING }]]);
check('a tab or newline inside a cell is flattened to a space, so the row shape holds',
      /\n1\ta b c d\tok/.test(buildContext(messy, 's1', '', 'x').text));
eq('booleans read as a spreadsheet writes them',
   ctxCellText({ cellData: { '0': { '0': { v: true, t: CV_BOOLEAN } } } }, 0, 0), 'TRUE');
eq('an empty cell is an empty field, not the word undefined',
   ctxCellText({ cellData: {} }, 5, 5), '');

// ── truncation, all three ways ───────────────────────────────────────────────
function bigSheet(rows, cols, cellText) {
  const cd = {};
  for (let r = 0; r < rows; r++) {
    const row = {};
    for (let c = 0; c < cols; c++) row[String(c)] = { v: (cellText || ('r' + r + 'c' + c)), t: CV_STRING };
    cd[String(r)] = row;
  }
  return { sheets: { s1: { name: 'Big', cellData: cd } } };
}
const tallCtx = buildContext(bigSheet(AI_CTX_ROWS + 40, 3), 's1', '', 'big.xlsx');
eq('a sheet taller than the row cap is cut to the cap', tallCtx.rows, AI_CTX_ROWS);
check('…and says so, in the prompt, where the model can see it',
      tallCtx.truncated === true && /Only the first 200 rows/.test(tallCtx.text));
check('…and the last row shown is the capped one, not the last one in the file',
      tallCtx.text.indexOf('\n' + AI_CTX_ROWS + '\t') > 0
      && tallCtx.text.indexOf('\n' + (AI_CTX_ROWS + 1) + '\t') < 0);
const wideCtx = buildContext(bigSheet(3, AI_CTX_COLS + 15), 's1', '', 'wide.xlsx');
eq('a sheet wider than the column cap is cut to the cap', wideCtx.cols, AI_CTX_COLS);
check('…and the header row stops at the capped column',
      wideCtx.text.indexOf('\t' + colName(AI_CTX_COLS - 1) + '\n') > 0
      && wideCtx.text.indexOf('\t' + colName(AI_CTX_COLS) + '\n') < 0);
check('…and the used range still reports the REAL size, so the model knows it is '
      + 'seeing a corner of something bigger', /used range A1:AS3/.test(wideCtx.text));
// the character ceiling bites even when rows and columns are within their caps
const fatCtx = buildContext(bigSheet(150, 25, 'x'.repeat(40)), 's1', '', 'fat.xlsx');
check('the character ceiling is enforced on top of the row and column caps',
      fatCtx.text.length <= AI_CTX_CHARS + 120 && fatCtx.truncated === true);
check('…and it cuts on a LINE boundary, so half a row of data never reaches the model',
      /\n… \(cut here/.test(fatCtx.text)
      && fatCtx.text.split('\n… (cut here')[0].split('\n').pop().split('\t').length === 26);

// totality: every one of these is a third-party file or a wire value
[[null, 's1'], [{}, 's1'], [{ sheets: null }, 's1'], [{ sheets: {} }, 'nope'],
 [{ sheets: { s1: 'a string' } }, 's1'], [{ sheets: { s1: null } }, 's1'],
 [undefined, undefined], [{ sheets: { s1: { cellData: 'junk' } } }, 's1'],
 [{ sheets: { s1: { cellData: { x: 1, '0': 'nope' } } } }, 's1']
].forEach(([s, sid], i) => {
  let out = null, threw = null;
  try { out = buildContext(s, sid, '', 'x'); } catch (e) { threw = e; }
  check('a surprise snapshot shape costs the context, never the page (case ' + i + ')',
        !threw && out && typeof out.text === 'string');
});
eq('an unusable snapshot yields NO context rather than a made-up one',
   buildContext(null, 's1', '', 'x').text, '');
const emptyCtx = buildContext(sheetOf([]), 's1', '', 'blank.xlsx');
eq('an empty sheet reports 0×0', [emptyCtx.rows, emptyCtx.cols], [0, 0]);
check('…and says the used range is empty rather than printing A1:A0',
      /used range empty/.test(emptyCtx.text));
check('with no selection the "selected cell" line is simply absent',
      buildContext(wb, 's1', '', 'x').text.indexOf('selected') < 0);

// the cheap extent used by the note under the composer — the panel repaints on every
// model poll, and building the whole prompt to print "5×2" would be work nobody asked
// for. It must AGREE with buildContext, or the note lies about what will be sent.
eval(grab('sheetIds'));
var AI_SNAP = null;                              // the snapshot the stub hands back
let activeSid = 's1', current = 'x', mode = 'grid', api = null;
function aiSnapshot() { return AI_SNAP; }        // the tier switch is tested in the browser
eval(grab('aiSheetId')); eval(grab('aiExtent'));
[[wb, 4, 2, false],
 [bigSheet(AI_CTX_ROWS + 40, 3), AI_CTX_ROWS, 3, true],
 [bigSheet(3, AI_CTX_COLS + 15), 3, AI_CTX_COLS, true],
 [sheetOf([]), 0, 0, false]].forEach(([s, r, c, tr], i) => {
  AI_SNAP = s;
  const e = aiExtent(), b = buildContext(s, 's1', '', 'x');
  eq('aiExtent agrees with buildContext on rows×cols (case ' + i + ')',
     [e.rows, e.cols], [b.rows, b.cols]);
  eq('…and on the size it reports (case ' + i + ')', [e.rows, e.cols, e.truncated], [r, c, tr]);
});
AI_SNAP = null;
eq('with nothing open the note has nothing to report', aiExtent(), null);

// …and the note is CACHED, because reading the extent back in the rich editor means
// asking Univer to serialise the whole workbook — pointless on a 15-second poll.
const pt = grab('aiPaint');
check('the note reads the cached extent, never rebuilds the prompt to print a size',
      /aiCtxOn \? aiNote : null/.test(pt) && !/aiContext\(\)/.test(stripComments(pt)));
check('a recount happens for free in the plain grid and only on demand in Univer',
      /recount === true \|\| \(recount !== false && mode !== 'univer'\)/.test(pt));
check('the 15-second model poll does NOT force one', /aiPaint\(\);\s*\n\}/.test(grab('aiRefreshModel')));
['aiSetOpen', 'aiSend'].forEach(fn =>
  check(fn + ' forces a recount, because the user just did something',
        /aiPaint\(true\)/.test(grab(fn))));
check('…as does opening another workbook, and switching to the rich editor',
      /aiPaint\(true\)/.test(grab('openDoc')) && /aiPaint\(true\)/.test(grab('upgrade')));

// the placeholder must step aside AFTER the turn is in the log, not before — it counts
check('aiAdd appends the turn and only THEN re-evaluates the placeholder',
      /appendChild\(wrap\);\s*\n\s*aiEmpty\(\)/.test(grab('aiAdd')));
check('the placeholder is hidden by a CLASS, never by an inline display — the rule '
      + 'this page states on #msg and then had to learn twice',
      /classList\.toggle\('off'/.test(grab('aiEmpty'))
      && !/style\.display/.test(grab('aiEmpty')));
check('clear removes the TURNS and leaves the placeholder markup alone',
      /querySelectorAll\('\.aim'\), n => n\.remove\(\)/.test(code)
      && !/ai-log'\)\.innerHTML = ''/.test(code));

// ── the reply renderer ───────────────────────────────────────────────────────
eval(grab('aiFences'));
eq('prose with no fence is one text part',
   aiFences('just words').map(p => p.kind), ['text']);
eq('a fenced block is split out of the prose around it',
   aiFences('before\n```excel\n=SUM(A1:A2)\n```\nafter').map(p => [p.kind, p.lang, p.body.trim()]),
   [['text', '', 'before'], ['code', 'excel', '=SUM(A1:A2)'], ['text', '', 'after']]);
eq('two fences both survive',
   aiFences('```a\n1\n```\nmid\n```b\n2\n```').map(p => p.lang || p.body.trim()),
   ['a', 'mid', 'b']);
eq('an UNTERMINATED fence still yields its code — a stream cut short must not swallow '
   + 'the answer', aiFences('here:\n```python\nprint(1)').map(p => [p.kind, p.body.trim()]),
   [['text', 'here:'], ['code', 'print(1)']]);
eq('a fence with no language is still a code part',
   aiFences('```\nx\n```').map(p => [p.kind, p.lang]), [['code', '']]);
eq('blank prose between fences is dropped rather than rendered as an empty paragraph',
   aiFences('```a\n1\n```\n\n\n```b\n2\n```').length, 2);
eq('an empty fence is dropped too', aiFences('```js\n\n```').length, 0);
[null, undefined, '', 0, {}].forEach((v, i) => {
  let threw = null;
  try { aiFences(v); } catch (e) { threw = e; }
  check('aiFences survives junk input (case ' + i + ')', !threw);
});

// ── the wire, and the two rules that matter most ─────────────────────────────
const send = grab('aiSend');
check('the panel posts to the harness\'s EXISTING direct chat lane',
      /fetch\('\/api\/chat\/direct'/.test(send));
check('…with the same {session, message} body the main panel sends',
      /JSON\.stringify\(\{ session: '', message: message \}\)/.test(send));
check('…and reads the same `data: ` SSE frames, [DONE] included',
      /startsWith\('data: '\)/.test(send) && /\[DONE\]/.test(send));
check('…handling the lane\'s proxy_error frame rather than hanging on it',
      /proxy_error/.test(send));
// THE NEGATIVE THAT MATTERS: no second chat endpoint may ever exist for this page.
// Asserted over the CODE, comments stripped — see stripComments above.
check('the page defines and calls NO office-specific chat endpoint',
      code.indexOf('/api/office/chat') < 0 && code.indexOf('/api/office/ask') < 0);
const urls = Array.from(new Set(code.match(/'\/api\/[^']*'/g) || []));
check('…and the only chat URL anywhere in the page is the shared lane',
      urls.filter(u => /chat|ask|complet/.test(u)).join() === "'/api/chat/direct'", urls);
check('every URL the page calls is one of the endpoints that already existed',
      urls.every(u => ["'/api/chat/direct'", "'/api/status'", "'/api/office/files'",
                       "'/api/office/new'", "'/api/office/save'", "'/api/office/delete'",
                       "'/api/office/upload?name='", "'/api/office/open/'",
                       "'/api/office/download/'", "'/api/office/diag'"].indexOf(u) >= 0), urls);
check('the session is deliberately EMPTY, so a spreadsheet question can never appear '
      + 'in — or retitle — a chat in Mission Control',
      /session: ''/.test(send));

// READ-ONLY ADVISORY, enforced by construction.
const writers = /\bputCell\(|\bcommit\(|\brenderGrid\(|\bparseInput\(|dirty = true/;
check('aiSend writes NOTHING into the spreadsheet', !writers.test(send));
check('…nor does the reply renderer', !writers.test(grab('aiRenderBody')));
check('…nor the context builder (it only reads)', !writers.test(grab('buildContext')));
check('…nor the snapshot reader — and it is deliberately NOT snapshotToSave(), which '
      + 'COMMITS the focused cell', !writers.test(grab('aiSnapshot'))
      && !/snapshotToSave/.test(grab('aiSnapshot')) && !/snapshotToSave/.test(send));
check('a suggested formula is COPIED, never applied to a cell',
      /aiCopy\(cp, pre\.textContent\)/.test(grab('aiRenderBody'))
      && !/apply/i.test(stripComments(grab('aiRenderBody'))));
check('the copy button falls back to execCommand where the async clipboard is absent '
      + '(a WKWebView is not a browser)', /execCommand\('copy'\)/.test(grab('aiCopy')));

// what the user is shown about what was sent
check('the user turn carries the context VERBATIM in a disclosure — a model answering '
      + 'about data you cannot see is a guess you cannot check',
      /context sent · /.test(grab('aiAdd')) && /pre\.textContent = ctx\.text/.test(grab('aiAdd')));
check('the context can be switched off, and the panel says when it is',
      /sheet not sent/.test(grab('aiPaint')));
// ⚠️ SAID OUT LOUD, because it is a real limit: with session:'' the bridge loads no
// history, so every question is single-shot. A user who asks a follow-up and gets a
// puzzled answer must not have to discover why.
check('the panel says plainly that each question is asked on its own',
      /Each question is asked on its own/.test(html));
// the selected cell: tier 1 records it on focus, the rich editor is asked for it
check('tier 1 records the selected cell on focus', /aiSel = a1\(/.test(code));
const sn = grab('aiSelNow');
check('…and the rich editor is asked for its own, through the facade',
      /getActiveRange/.test(sn) && /getA1Notation/.test(sn));
check('…with a facade name that moves costing the LINE, not the question',
      /try \{/.test(sn) && /catch/.test(sn) && /return '';/.test(sn));
check('thinking is kept, collapsed, rather than filling the rail or being thrown away',
      /thinking · /.test(send) && /details/.test(send));
check('an empty answer is reported rather than shown as a blank bubble',
      /returned an empty answer|said nothing/.test(send));

// beacons — this page's whole diagnostic contract
['ai-send', 'ai-reply-ok', 'ai-reply-fail', 'ai-model', 'ai-snapshot-fail']
  .forEach(st => check('the panel beacons ' + st, code.indexOf("bx('" + st + "'") > 0));
check('…and beacons the open/collapse transition through one call site',
      /bx\(open \? 'ai-open' : 'ai-collapse', why/.test(grab('aiSetOpen')));
check('the landing beacon now says whether the panel is open and what model it found',
      /bx\('landed'[\s\S]{0,220}ai=/.test(html) && /bx\('landed'[\s\S]{0,240}model=/.test(html));

// state
check('the open/closed choice is persisted', /localStorage\.setItem\('harness-office-ai'/.test(html));
check('…and the sheet-context choice separately',
      /localStorage\.setItem\('harness-office-ai-ctx'/.test(html));
check('the panel is OPEN by default — a capability nobody can see is the bug being '
      + 'fixed here', /localStorage\.getItem\('harness-office-ai'\) !== '0'/.test(grab('boot')));
check('a localStorage that throws (private mode) does not stop the boot',
      /catch \(e\) \{ \/\* private mode/.test(grab('boot')));
check('Enter asks and Shift+Enter is a newline, as everywhere else in the harness',
      /ev\.key === 'Enter' && !ev\.shiftKey/.test(html));
check('the model pill re-checks itself while the panel is open',
      /setInterval\(\(\) => \{ if \(!document\.hidden\) aiRefreshModel\(\); \}, AI_POLL_MS\)/.test(grab('aiSetOpen')));
check('…and stops when it is collapsed', /clearInterval\(aiTimer\)/.test(grab('aiSetOpen')));

// the build stamp moved, so a stale document is still decidable by eye
const stamp = (html.match(/name="harness-build" content="([^"]+)"/) || [])[1];
check('the build stamp was bumped for this change', stamp === 'loffice-2026-08-21g');
check('…and the static fallback banner carries the SAME one',
      (html.match(/loffice-2026-08-21g/g) || []).length === 2);

// ── report ──
console.log('');
if (fails.length) {
  console.log(`${fails.length} FAILED (of ${pass + fails.length}):`);
  fails.forEach(f => console.log('  -', f));
  process.exit(1);
}
console.log(`loffice chrome scope + AI panel OK — ${pass} checks passed`);
