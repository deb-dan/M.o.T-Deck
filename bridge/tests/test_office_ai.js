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
                       "'/api/office/rename'",
                       "'/api/office/upload?name='", "'/api/office/open/'",
                       "'/api/office/download/'", "'/api/office/diag'"].indexOf(u) >= 0), urls);
check('the session is deliberately EMPTY, so a spreadsheet question can never appear '
      + 'in — or retitle — a chat in Mission Control',
      /session: ''/.test(send));

/* ⚠️⚠️ THE FOUR ASSERTIONS BELOW WERE REWRITTEN AT 2026-08-21k AND THAT IS A DELIBERATE
   POLICY CHANGE, NOT A WEAKENING. This panel used to be read-only advisory and these
   lines pinned it: "aiSend writes NOTHING", "nor does the reply renderer", "a suggested
   formula is COPIED, never applied". Debi asked for the opposite — "it seems not
   possible to do tool functions, i.e. just ask it to create a document with data on
   that page" — so the panel can now WRITE, and pinning a promise the product no longer
   makes would be worse than pinning nothing.

   WHAT THEY WERE PINNING SURVIVES AS TWO NARROWER, STRONGER FACTS, both below and both
   in PART 4: (1) `aiSend` and the reply renderer STILL write nothing themselves — the
   write lives behind one click, in one function; (2) an ORDINARY fenced block is still
   copy-only, and only an ACTION block earns an Apply.

   ⚠️ AND ONE OF THEM WOULD STILL HAVE PASSED, WHICH IS WHY IT HAD TO GO. `aiRenderBody`
   now renders the Apply card, but it does it by CALLING actCard — so a regex looking for
   `putCell(` in aiRenderBody's own body finds nothing and reports "the reply renderer
   writes nothing into the spreadsheet", which is true of the text and false of the
   product. A negative that keeps passing after the thing it guarded is gone is worse
   than no negative at all. The replacement (PART 4's writer-set fence) is computed over
   EVERY function in the page, so it cannot be defeated by moving the call one level
   down. */
const writers = /\bputCell\(|\bcommit\(|\brenderGrid\(|\bparseInput\(|dirty = true/;
check('aiSend itself writes nothing into the spreadsheet — the reply is text, and the '
      + 'only thing that can act on it is a button the user has to press',
      !writers.test(send) && !/actApply|actRunOps/.test(stripComments(send)));
check('the reply renderer performs no write of its own either: it DELEGATES to actCard, '
      + 'and the writer-set fence in PART 4 is what proves that is the only route',
      !writers.test(grab('aiRenderBody'))
      && /actCard\(host, scan\)/.test(grab('aiRenderBody')));
check('…nor the context builder (it only reads)', !writers.test(grab('buildContext')));
check('…nor the snapshot reader — and it is deliberately NOT snapshotToSave(), which '
      + 'COMMITS the focused cell', !writers.test(grab('aiSnapshot'))
      && !/snapshotToSave/.test(grab('aiSnapshot')) && !/snapshotToSave/.test(send));
check('an ORDINARY fenced block is still copy-only — a suggested formula in a ```excel '
      + 'block is advice, and it grew no Apply button',
      /aiCopy\(cp, pre\.textContent\)/.test(grab('aiRenderBody'))
      && !/actApply/.test(stripComments(grab('aiRenderBody'))));
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
// ⚠️ CHANGED IN ROUND 3, and the old assertion was pinning the bug. The sheet-context
// choice USED to be a persisted global, so one "ask without the sheet" survived every
// later document and every later session — which is half of why a question about CLEAN
// came back about Python. It is now per-document and in memory (see PART 3).
check('…while the sheet-context choice is deliberately NOT persisted any more',
      code.indexOf('harness-office-ai-ctx') < 0);
check('the panel is OPEN by default — a capability nobody can see is the bug being '
      + 'fixed here', /localStorage\.getItem\('harness-office-ai'\) !== '0'/.test(grab('boot')));
check('a localStorage that throws (private mode) does not stop the boot',
      /catch \(e\) \{ \/\* private mode/.test(grab('boot')));
check('Enter asks and Shift+Enter is a newline, as everywhere else in the harness',
      /ev\.key === 'Enter' && !ev\.shiftKey/.test(html));
check('the model pill re-checks itself while the panel is open',
      /setInterval\(\(\) => \{ if \(!document\.hidden\) aiRefreshModel\(\); \}, AI_POLL_MS\)/.test(grab('aiSetOpen')));
check('…and stops when it is collapsed', /clearInterval\(aiTimer\)/.test(grab('aiSetOpen')));

/* ══════════════════════════════════════════════════════════════════════════════
   PART 3 — ROUND 3: the model was not sheet-aware, there was no way out of the page,
   and the page ignored the app's own theme.
   ═════════════════════════════════════════════════════════════════════════════ */

// ── the grounding preamble ───────────────────────────────────────────────────
// THE BUG, from Debi's screenshot: "What does clean function do" → an explanation of
// PYTHON string cleaning. Two things were wrong, and the sheet toggle was only one of
// them: NOTHING in the request said this was a spreadsheet at all.
// ⚠️ actHelp FIRST, and this is not cosmetic: at 2026-08-21k the preamble ENDS by
// calling it (the action format is taught on every request), so evaluating the preamble
// on its own and then calling it would throw ReferenceError — which is a CRASHED test,
// not a failing one, and every assertion after it would never run.
eval(grab('actHelp'));
eval(grab('aiPreamble'));
const PRE = aiPreamble('Sales.xlsx', 'Q3');
check('the preamble says what this app is', /LOffice/.test(PRE) && /spreadsheet/i.test(PRE));
check('…and that it is Excel .xlsx it is talking about', /Excel/.test(PRE) && /xlsx/.test(PRE));
check('…names the workbook and the sheet the question is about',
      /Sales\.xlsx/.test(PRE) && /Q3/.test(PRE));
check('…and settles the exact ambiguity that produced the bug: an unqualified '
      + '"function" is a SPREADSHEET function, not a Python one',
      /function/.test(PRE) && /Excel semantics/.test(PRE) && /Python/.test(PRE));
check('…and asks for formulas in a fenced block, which the reply renderer already '
      + 'turns into a copyable card', /fenced/.test(PRE));
check('with no workbook open it says so rather than naming an empty file',
      /no workbook open/.test(aiPreamble('', '')) && !/“”/.test(aiPreamble('', '')));
check('a missing SHEET name costs a clause, never the preamble',
      /Sales\.xlsx/.test(aiPreamble('Sales.xlsx', '')) && aiPreamble('Sales.xlsx', '').length > 200);
[[null, null], [undefined, undefined], [0, 0], [{}, []], [' ', ' ']].forEach(([f, s], i) => {
  let out = null, threw = null;
  try { out = aiPreamble(f, s); } catch (e) { threw = e; }
  check('aiPreamble is total — it is fed `current`, which can be anything (case '
        + i + ')', !threw && typeof out === 'string' && out.length > 100);
});

const send3 = grab('aiSend');
check('THE FIX: the preamble is prepended UNCONDITIONALLY. The sheet chip governs the '
      + 'DATA, never whether the model is told it is inside a spreadsheet',
      /const message = aiPreamble\(current, aiSheetName\(\)\)/.test(send3));
check('…and the order is preamble → sheet (if sent) → question',
      /aiPreamble[\s\S]{0,200}ctx\.text[\s\S]{0,120}'---/.test(send3));
check('the disclosure now carries the WHOLE message, preamble included — a prompt the '
      + 'user cannot see is a prompt they cannot check', /text: message/.test(send3));
check('…and says out loud when only the grounding went', /grounding only/.test(send3));
check('the preamble travels in the SAME single message on the SAME lane — no second '
      + 'field, no system role, nothing new on the wire',
      /JSON\.stringify\(\{ session: '', message: message \}\)/.test(send3));
// ⚠️ REWORDED AT 2026-08-21k: it used to read "it is READ-ONLY like everything else in
// this panel", and the second half of that is no longer true. The fact it pinned is,
// and it is still worth pinning: the preamble is a string builder, nothing more.
check('the preamble builds a STRING and does nothing else — the model may now propose a '
      + 'change, but the thing that describes the format cannot make one',
      !writers.test(grab('aiPreamble')) && !/actApply|actRunOps/.test(grab('aiPreamble')));

// ── the sheet chip, per document ─────────────────────────────────────────────
check('the chip starts ON in the markup', /id="ai-ctx" class="chip on"/.test(html));
check('…and EVERY workbook opened turns it back on', /aiCtxOn = true/.test(grab('showWorkbook')));
check('…so turning it off is a decision about the question you are asking now, and '
      + 'cannot outlive the document', code.indexOf('harness-office-ai-ctx') < 0);
check('the off state names the workbook it applies to, in the boot trace',
      /bx\('ai-ctx'/.test(code));
check('…and the chip still says plainly when the sheet is not going',
      /sheet not sent/.test(grab('aiPaint')));

// ── the File menu ────────────────────────────────────────────────────────────
const MENU = ['mi-new', 'mi-open', 'mi-import', 'mi-rename', 'mi-save', 'mi-download',
              'mi-close', 'mi-home'];
MENU.forEach(id => check('the File menu carries a ' + id + ' row', html.indexOf('id="' + id + '"') > 0));
check('the File button sits at the left of the header, before the file name',
      html.indexOf('id="btn-file"') > html.indexOf('id="btn-rail"')
      && html.indexOf('id="btn-file"') < html.indexOf('id="p-file"'));
check('every row goes through ONE helper that closes the menu first, so no row can '
      + 'leave it hanging open', MENU.every(id => new RegExp("mi\\('" + id + "'").test(code))
      && /function mi\(id, run\)[\s\S]{0,140}fileMenu\(false\)/.test(code));
check('it closes on an outside mousedown', /filewrap[\s\S]{0,140}contains\(ev\.target\)[\s\S]{0,60}fileMenu\(false\)/.test(code));
check('…and on Escape, before Escape means anything else',
      /Escape' && el\('filemenu'\)\.classList\.contains\('on'\)/.test(code));
check('the rows are disabled from the SAME state the header reads, so a menu left open '
      + 'through a save cannot act on a file that is moving',
      /el\('mi-save'\)\.disabled = el\('btn-save'\)\.disabled/.test(code)
      && /el\('mi-rename'\)\.disabled = !has \|\| busy/.test(code));
check('…and paint() keeps an OPEN menu honest rather than only painting it once',
      /if \(el\('filemenu'\)\.classList\.contains\('on'\)\) fileMenuPaint\(\)/.test(code));
check('the menu is a real dropdown, hidden by a CLASS like everything else on this page',
      rules.some(r => r.sel === '#filemenu' && /display:none/.test(r.body))
      && rules.some(r => r.sel === '#filemenu.on' && /display:flex/.test(r.body)));
check('it invents no dialog primitive — window.prompt and window.confirm are both '
      + 'silent no-ops in a WKWebView, so Rename is an inline row and every '
      + 'are-you-sure is a second click',
      !/window\.(prompt|confirm)\s*\(/.test(code));

// ── the way home ─────────────────────────────────────────────────────────────
const home = grab('goHome');
check('⌂ MOT Main asks the SHELL to switch tabs, through the same postMessage contract '
      + 'the panel sidebar already uses',
      /messageHandlers[\s\S]{0,80}harness/.test(home) && /cmd: 'switchTab'/.test(home));
check('…sending the stable id AS WELL AS the title, so a renamed tab still resolves',
      /id: 'mc'/.test(home) && /title: 'MOT Main'/.test(home));
check('…defensively, because the shell does not register that handler on this webview '
      + 'yet: no handler is a MESSAGE, never a silent nothing',
      /try \{/.test(home) && /say\(/.test(home));
check('…and in a real browser it simply navigates — while inside the shell it does NOT, '
      + 'because that would strand the LOffice tab on Mission Control',
      /inShell/.test(home) && /window\.location\.href = '\/'/.test(home));
check('both the menu and the way home are beaconed',
      code.indexOf("bx('menu-open'") > 0 && code.indexOf("bx('home-click'") > 0);

// ── rename ───────────────────────────────────────────────────────────────────
const ren = grab('renameDoc');
check('rename goes through the bridge, which owns the name rules',
      /fetch\('\/api\/office\/rename'/.test(ren));
check('…carrying both names', /JSON\.stringify\(\{ name: from, to: to \}\)/.test(ren));
check('the open document follows its new name, so the next Save writes the right file',
      /current = j\.name/.test(ren));
check('…and a rename NEVER throws unsaved edits away — it is not a save',
      !/dirty = false/.test(ren));
check('a rename that fails says why, from the bridge, and beacons it',
      /bx\('rename-fail'/.test(ren) && /the bridge answered/.test(ren));
check('the rail\'s one name box does both verbs rather than growing a second one',
      /function nameRow\(want\)/.test(code) && /(nameMode|mode) === 'rename' \? 'Rename' : 'Create'/.test(code)
      && /function nameRowGo\(\)/.test(code));
check('…and Enter in that box follows the verb it is showing',
      /if \(ev\.key === 'Enter'\) nameRowGo\(\)/.test(code));

// ── the third option, and the double-click that used to bin your work ────────
const cd = grab('confirmDiscard');
check('the unsaved-changes message offers the third option outright instead of '
      + 'describing a dilemma and walking away', /Save & open/.test(cd) && /await save\(\)/.test(cd));
check('…and does NOT open when the save failed — its reason is already on screen',
      /if \(dirty\) return;/.test(cd));
check('a DOUBLE-CLICK on a file row can no longer arm and confirm a discard between two '
      + 'halves of one gesture', /DISCARD_MIN_MS/.test(cd) && num('DISCARD_MIN_MS') >= 250);
const sayFn = grab('say');
check('say() renders an inline action as a real button…', /b\.textContent = action\.label/.test(sayFn));
check('…and STILL puts every string in through textContent — innerHTML is only ever '
      + 'used to clear', !/innerHTML = text/.test(sayFn) && /m\.innerHTML = '';/.test(sayFn)
      && /t\.textContent = text/.test(sayFn));
check('closing a file is offered a Save & close in the same shape',
      /Save & close/.test(code) && code.indexOf("bx('close-file'") > 0);
check('the rail says which workbook is OPEN, not merely which row is selected',
      /' · open'/.test(grab('renderFiles')));

// ── theme coherence ──────────────────────────────────────────────────────────
// "non chrome thing again": the tab ignored the ◐ theme and the ▣ chrome the rest of
// the harness obeys, so flipping the app to light left one dark rectangle behind.
check('the page READS the panel\'s own two keys and invents no setting of its own',
      /localStorage\.getItem\('harness-theme'\)/.test(html)
      && /localStorage\.getItem\('harness-chrome'\)/.test(html)
      && !/setItem\('harness-theme'/.test(html) && !/setItem\('harness-chrome'/.test(html));
check('…before first paint, in the head, exactly as the panel does it — applying it '
      + 'later would paint dark and then flip, every load',
      html.indexOf('syncSkin') > 0 && html.indexOf('syncSkin') < html.indexOf('<style>'));
check('…and it stays in step afterwards: a storage event (which is precisely what the '
      + 'panel writing the key looks like from here), focus, and becoming visible',
      /addEventListener\('storage'/.test(code) && /syncSkin\('focus'\)/.test(code)
      && /syncSkin\('visible'\)/.test(code));
check('a localStorage that throws leaves the page on its defaults rather than failing',
      /catch \(e\) \{ return ''; \}/.test(html));
check('the skin is beaconed, and only when it CHANGES', /bx\('skin'/.test(html)
      && /now !== lastSkin/.test(html));

const themeRules = rules.filter(r => /data-theme|data-chrome/.test(r.sel));
check('both axes are implemented in CSS, not by rewriting the page at runtime',
      themeRules.length >= 6);
{
  const root = rules.find(r => r.sel === ':root');
  const lite = rules.find(r => r.sel === 'html[data-theme="light"]');
  check('the light PALETTE rule outranks :root — written with a zero-specificity '
        + ':where() it would have lost, and the theme would have done nothing at all',
        !!root && !!lite && cmp(spec(lite.sel), spec(root.sel)) > 0);
}
{
  // THE LANDMINE THE STUDIO-CHROME POST-MORTEM RECORDS, tested rather than trusted.
  const stBtn = rules.find(r => /^:where\(html\[data-chrome="studio"\]\)[\s\S]*\) button$/.test(r.sel));
  const ghost = rules.find(r => /\) button\.ghost$/.test(r.sel));
  check('the studio chrome restyles our buttons', !!stBtn);
  eq('…with its whole prefix inside :where(), so it carries the specificity of a bare '
     + '`button`', spec(stBtn ? stBtn.sel : 'nope'), [0, 0, 1]);
  check('…and therefore LOSES to .ghost, button.primary and .lnk: a studio flip cannot '
        + 'fill in the icon buttons, flatten the one cream button, or turn the file '
        + 'row\'s download/delete links into boxes',
        !!stBtn && !!ghost && !!prim
        && cmp(spec(ghost.sel), spec(stBtn.sel)) > 0
        && cmp(spec(prim.sel), spec(stBtn.sel)) > 0
        && cmp(spec('.lnk'), spec(stBtn.sel)) > 0);
  check('…and to #gridbar button, so the white sheet\'s own chrome is untouched by '
        + 'either axis', !!gb && !!stBtn && cmp(spec(gb.sel), spec(stBtn.sel)) > 0);
}
check('neither axis themes the SHEET — a .xlsx\'s fills and font colours were all '
      + 'chosen against a white page',
      themeRules.every(r => !/#gt|#gridwrap|#gridbar|#sheet\b/.test(r.sel)));

// the build stamp moved, so a stale document is still decidable by eye
// ⚠️ THIS WAS RED WHEN THIS SLICE STARTED: the menu-bar rebuild bumped the page to
// `j` and left this literal on `i`, so two assertions in this file were already
// failing. Bumped to `k` for the AI-actions slice, and the same one-line literal in
// test_office_grid.js was bumped with it (that file reads the stamp for everything
// EXCEPT this one pin).
const stamp = (html.match(/name="harness-build" content="([^"]+)"/) || [])[1];
check('the build stamp was bumped for this change', stamp === 'loffice-2026-08-27b');
check('…and the static fallback banner carries the SAME one',
      (html.match(/loffice-2026-08-27b/g) || []).length === 2);

/* ══════════════════════════════════════════════════════════════════════════════
   PART 4 — THE ACTION BLOCK: the model can change the sheet, on a click
   ═════════════════════════════════════════════════════════════════════════════
   "The model on LOffice seems to be aware now. However, it seems not possible to do
   tool functions, i.e. just ask it to create a document with data on that page."

   THE MECHANISM IS NOT OPENAI FUNCTION-CALLING, ON PURPOSE: most of the models Debi
   runs locally cannot tool-call at all (that is what the `tools` pill on the Models
   page exists to say) and the direct chat lane sends no tools array — so a
   function-calling path would work on some of her models and silently do nothing on
   the rest. Instead the format is TAUGHT IN THE PROMPT and the reply is parsed.

   WHICH MAKES THE MODEL AN UNTRUSTED INPUT, and that is what most of this part is
   about: the parse is pure, total, capped, and explains every refusal; the preview is
   built from the plan's own literal values; and the write happens in ONE function
   behind ONE click, with a full-workbook clone taken first so Undo is a restore. */

const officePy = fs.readFileSync(path.join(ROOT, 'bridge', 'office.py'), 'utf8');

// The constants come out of the page as `var`, because a `const` inside a sloppy-mode
// direct eval is scoped to the eval and would be lost (function declarations leak,
// lexical declarations do not — the same reason this file is not 'use strict').
// ⚠️ `[\s\S]*?` rather than `.*?`: at 2026-08-27a the constants this file needs include
// one whose value is a multi-line string concatenation (RC_FORMULA_NOTE, the honest note
// the sort and insert gestures share with the AI path), and `.` does not match a newline
// — the old pattern simply did not find it and threw.
function constLine(name) {
  const m = html.match(new RegExp('^const ' + name + ' = [\\s\\S]*?;', 'm'));
  if (!m) throw new Error('const ' + name + ' not found in office.html');
  return m[0].replace(/^const /, 'var ');
}
eval(constLine('ACT_LANGS'));
eval(constLine('ACT_V'));
eval(constLine('ACT_MAX_OPS'));
eval(constLine('ACT_MAX_CELLS'));
eval(constLine('ACT_MAX_ROW'));
eval(constLine('ACT_MAX_COL'));
eval(constLine('ACT_STR_MAX'));
eval(constLine('ACT_LIST_MAX'));
eval(constLine('ACT_SHEET_MAX'));
eval(constLine('ACT_NAME_MAX'));
eval(constLine('ACT_HT'));
eval(constLine('ACT_VT'));
// ⚠️ `ACT_UNDO_MAX_BYTES` IS GONE ON PURPOSE, and so is `actClone`. At 2026-08-27a this
// panel stopped keeping its own private pre-write clone: the page grew ONE undo stack
// and the AI apply became an entry on it. The per-entry byte ceiling moved with it.
eval(constLine('HIST_MAX_BYTES'));
eval(constLine('RC_MAX'));
eval(constLine('SORT_BLANK'));
eval(constLine('RC_FORMULA_NOTE'));
var actSeq = 0;                       // page-side module state, mirrored for actAddSheet
var dirty = false;                    // histEntry records it, so it has to exist here
var TIER1_MAX_COLS = num('TIER1_MAX_COLS');

eval(grab('parseInput')); eval(grab('putCell'));
eval(grab('actHelp'));
eval(grab('actScalar')); eval(grab('actRef')); eval(grab('actRange'));
eval(grab('actGrid')); eval(grab('actColor')); eval(grab('actStyleSet'));
eval(grab('actCol')); eval(grab('actRcTarget'));
eval(grab('actDocName')); eval(grab('actValidate')); eval(grab('actScan'));
eval(grab('parseActions')); eval(grab('actSummary')); eval(grab('actCellList'));
eval(grab('actCell')); eval(grab('actTargetSid'));
eval(grab('actSheetExists')); eval(grab('actAddSheet')); eval(grab('actResolveStyle'));
eval(grab('actRunOps')); eval(grab('actWhere'));
// the shared machinery the two new ops execute through — the SAME functions the menu
// gestures use, which is the whole reason the AI path cannot drift from the manual one
eval(grab('gridRemap')); eval(grab('sheetFormulas')); eval(grab('sheetMerges'));
eval(grab('sortKey')); eval(grab('sortOrder'));
eval(grab('rcMerges')); eval(grab('rcApply'));
eval(grab('histEntry'));

check('the caps mirror the grid they write into: the column ceiling is TIER1_MAX_COLS',
      ACT_MAX_COL === num('TIER1_MAX_COLS') - 1);
check('…the sheet-name cap is Excel\'s own, which bridge/office.py also mirrors',
      ACT_SHEET_MAX === 31 && /SHEET_NAME_MAX = 31/.test(officePy));
check('…and the file-name cap is office.NAME_MAX',
      ACT_NAME_MAX === 80 && /^NAME_MAX = 80/m.test(officePy));

// ── the prompt half: what the model is told, and the cross-file fence on it ──
const HELP = actHelp();
check('the help names the fence tag the parser looks for',
      HELP.indexOf('```loffice') >= 0 && ACT_LANGS.indexOf('loffice') === 0);
check('…shows every operation the parser implements',
      ['"op":"set"', '"op":"style"', '"op":"sheet"', '"op":"resize"']
        .every(s => HELP.indexOf(s) >= 0));
check('…says where the values start, and that = is a formula and null empties a cell',
      /values START/.test(HELP) && /= is a formula/.test(HELP) && /null empties/.test(HELP));
check('…says nothing is written until Apply — the model should not promise otherwise',
      /Nothing is written until the user presses Apply/.test(HELP));
check('…and gives it the way OUT, so a plain question is still answered in prose',
      /answer in prose and emit no loffice block/.test(HELP));
// THE CROSS-FILE FENCE. The style keys the model is told about, the keys the parser
// accepts and the keys bridge/office.py::apply_style actually writes into the .xlsx
// must be ONE list. A key we accepted and the bridge dropped would be a formatting
// change that looks right, vanishes on save and comes back missing — silent loss.
const APPLY_STYLE = officePy.slice(officePy.indexOf('def apply_style'),
                                   officePy.indexOf('def cell_snapshot'));
const STYLE_KEYS = ['bl', 'it', 'ul', 'st', 'ff', 'fs', 'cl', 'bg', 'ht', 'vt', 'tb', 'n'];
STYLE_KEYS.forEach(k => {
  check('office.py::apply_style really writes the "' + k + '" style key',
        APPLY_STYLE.indexOf('style.get("' + k + '")') >= 0
        || APPLY_STYLE.indexOf('style["' + k + '"]') >= 0);
});
check('the help lists exactly those keys, in one place, so the model is told the truth',
      HELP.indexOf(STYLE_KEYS.join(' ')) >= 0);
const styleSrc = grab('actStyleSet');
check('…and actStyleSet emits no key apply_style would not read',
      (styleSrc.match(/out\.([a-z]+) =/g) || [])
        .map(s => s.replace(/out\.| =/g, ''))
        .every(k => STYLE_KEYS.indexOf(k) >= 0));
// the preamble carries it, unconditionally, on the same one message
eval(grab('aiPreamble'));
const PRE4 = aiPreamble('Sales.xlsx', 'Q3');
check('the grounding preamble carries the action format on EVERY request — a heuristic '
      + 'that only taught it when the question "looked like" a write would make the '
      + 'capability vanish for phrasings nobody thought of',
      PRE4.indexOf(HELP) > 0 && /actHelp\(\)/.test(grab('aiPreamble')));
check('…so the "context sent" disclosure shows it too, because that disclosure is the '
      + 'WHOLE message', /text: message/.test(send));
check('…and it still costs one message on one lane: nothing new on the wire',
      /JSON\.stringify\(\{ session: '', message: message \}\)/.test(send));

// ── A1 references ───────────────────────────────────────────────────────────
[['A1', 0, 0], ['B3', 2, 1], ['AA1', 0, 26], ['AB10', 9, 27], ['GR5000', 4999, 199],
 ['a1', 0, 0], ['$B$2', 1, 1], ['  C7  ', 6, 2], ['ZZ1', 0, 701]
].forEach(([s, r, c]) => {
  eq('actRef(' + JSON.stringify(s) + ')', actRef(s), { r: r, c: c });
});
check('actRef is the exact inverse of colName, which is what draws the headers',
      [0, 1, 25, 26, 27, 51, 52, 199, 701].every(c => {
        const ref = actRef(colName(c) + '1');
        return ref && ref.c === c;
      }));
eq('actRef refuses everything that is not a cell rather than inventing one',
   ['A0', '0A', '1A', 'A', '1', '', '   ', 'A1:B2', 'AAAA1', 'the total row',
    null, undefined, 42, {}, []].map(s => actRef(s)),
   [null, null, null, null, null, null, null, null, null, null,
    null, null, null, null, null]);
eq('actRange takes a single cell as a 1x1 rectangle', actRange('B3'),
   { r0: 2, c0: 1, r1: 2, c1: 1 });
eq('…a range as itself', actRange('A1:C3'), { r0: 0, c0: 0, r1: 2, c1: 2 });
eq('…and a BACKWARDS range as the same rectangle, because it is the same rectangle',
   actRange('C3:A1'), actRange('A1:C3'));
eq('actRange refuses junk', [actRange(''), actRange('A1:B2:C3'), actRange('A1:'),
   actRange(':B2'), actRange('nope'), actRange(null)],
   [null, null, null, null, null, null]);

// ── values → a grid ─────────────────────────────────────────────────────────
eq('a 2-D array is a grid', actGrid([['a', 'b'], ['c', 'd']]), [['a', 'b'], ['c', 'd']]);
eq('a FLAT array is one row — the shape a model reaches for when it means "a row"',
   actGrid(['a', 'b']), [['a', 'b']]);
eq('a bare scalar is one cell', actGrid(42), [[42]]);
eq('…including a string, a boolean and null (null means empty this cell)',
   [actGrid('x'), actGrid(true), actGrid(null)], [[['x']], [[true]], null]);
eq('a HALF-nested array is REFUSED, not repaired: guessing could put a value in the '
   + 'wrong cell, which is worse than saying no', actGrid([['a'], 'b']), null);
eq('…as are empty arrays, empty rows, and a cell holding an object',
   [actGrid([]), actGrid([[]]), actGrid([[{ a: 1 }]]), actGrid([[undefined]])],
   [null, null, null, null]);
eq('a non-finite number is not a value', [actGrid(NaN), actGrid([[Infinity]])], [null, null]);
check('a cell longer than the text cap is refused rather than truncated into the file',
      actGrid([['x'.repeat(ACT_STR_MAX)]]) !== null
      && actGrid([['x'.repeat(ACT_STR_MAX + 1)]]) === null);
eq('actGrid copies the rows it was given rather than aliasing the model\'s array',
   (() => { const src = [['a']]; const out = actGrid(src); out[0][0] = 'b'; return src[0][0]; })(),
   'a');

// ── styles ──────────────────────────────────────────────────────────────────
eq('bold, italic, underline and strikethrough take the shapes office.py reads',
   actStyleSet({ bl: true, it: 1, ul: true, st: true }),
   { bl: 1, it: 1, ul: { s: 1 }, st: { s: 1 } });
eq('alignment is accepted as a WORD, because that is what a model writes',
   [actStyleSet({ ht: 'center' }), actStyleSet({ ht: 'Right' }), actStyleSet({ vt: 'top' }),
    actStyleSet({ ht: 2 })],
   [{ ht: 2 }, { ht: 3 }, { vt: 1 }, { ht: 2 }]);
eq('a colour is normalised to 6-digit lower-case hex, and a NAME is refused — the file '
   + 'stores hex and inventing one for "reddish" would be a lie in a document',
   [actStyleSet({ cl: '#ABCDEF' }), actStyleSet({ bg: '#f00' }),
    actStyleSet({ cl: { rgb: '#123456' } }), actStyleSet({ cl: 'red' })],
   [{ cl: { rgb: '#abcdef' } }, { bg: { rgb: '#ff0000' } },
    { cl: { rgb: '#123456' } }, null]);
eq('a font size outside openpyxl\'s own 1..409 is dropped',
   [actStyleSet({ fs: 11 }), actStyleSet({ fs: 0 }), actStyleSet({ fs: 500 }),
    actStyleSet({ fs: 'big' })],
   [{ fs: 11 }, null, null, null]);
eq('wrap is accepted in all three shapes a model writes it',
   [actStyleSet({ tb: 3 }), actStyleSet({ tb: true }), actStyleSet({ tb: 'wrap' })],
   [{ tb: 3 }, { tb: 3 }, { tb: 3 }]);
eq('a number format travels as {pattern}', actStyleSet({ n: '0.00' }), { n: { pattern: '0.00' } });
eq('UNKNOWN keys are dropped, and an op left with nothing is refused outright',
   [actStyleSet({ border: 'thin', shadow: true }), actStyleSet({ bl: 1, border: 'thin' })],
   [null, { bl: 1 }]);
eq('actStyleSet is total over junk',
   [actStyleSet(null), actStyleSet('bold'), actStyleSet([1, 2]), actStyleSet(undefined),
    actStyleSet({})],
   [null, null, null, null, null]);

// ── file names ──────────────────────────────────────────────────────────────
eq('a suggested file name loses only what could not be a file name; the BRIDGE owns '
   + 'the rest of the rules and its own never-clobber walk',
   [actDocName('2026 budget'), actDocName('a/b\\c.xlsx'), actDocName('  x  '),
    actDocName('Sales.XLSX'), actDocName(''), actDocName(null), actDocName(42)],
   ['2026 budget', 'a b c', 'x', 'Sales', '', '', '42']);
check('…and it can never be longer than the bridge accepts',
      actDocName('n'.repeat(400)).length === ACT_NAME_MAX);

/* ── the validator, which is where the model is actually held to account ──── */
function plan(obj) { return actValidate(obj); }
const OK = { v: 1, ops: [{ op: 'set', at: 'A1', values: [['Month', 'Planned']] }] };
check('a well-formed block validates', plan(OK).ok === true);
eq('…and reports what it will do', plan(OK).count.cells, 2);
check('the version is required — a future format must not be read as this one',
      plan({ ops: OK.ops }).ok === false
      && plan({ v: 2, ops: OK.ops }).ok === false
      && plan({ v: '1', ops: OK.ops }).ok === true);
check('…and a version of `true` is not a version', plan({ v: true, ops: OK.ops }).ok === false);
[['not an object at all', 'a string'], ['an array', [1, 2]], ['null', null],
 ['no ops', { v: 1 }], ['ops that is not a list', { v: 1, ops: 'set A1' }],
 ['an empty ops list', { v: 1, ops: [] }],
 ['an op that is not an object', { v: 1, ops: ['set A1 to x'] }],
 ['an unknown op', { v: 1, ops: [{ op: 'delete_file', at: 'A1' }] }],
 ['an op with no op name', { v: 1, ops: [{ at: 'A1', values: [['x']] }] }],
 ['a set with no values', { v: 1, ops: [{ op: 'set', at: 'A1' }] }],
 ['a set whose "at" is prose', { v: 1, ops: [{ op: 'set', at: 'the total row', values: [['x']] }] }],
 ['a style with no readable key', { v: 1, ops: [{ op: 'style', at: 'A1', set: { border: 1 } }] }],
 ['a sheet op with neither add nor rename', { v: 1, ops: [{ op: 'sheet' }] }],
 ['a resize with neither rows nor cols', { v: 1, ops: [{ op: 'resize' }] }],
 ['a sheet name past Excel\'s limit', { v: 1, ops: [{ op: 'sheet', add: 'x'.repeat(40) }] }]
].forEach(([label, obj]) => {
  const p = plan(obj);
  check('REFUSED, with a reason a person can read — ' + label,
        p.ok === false && typeof p.why === 'string' && p.why.length > 8);
});
check('every refusal that is about one operation NAMES which one',
      /operation 2: /.test(plan({ v: 1, ops: [OK.ops[0], { op: 'nope' }] }).why));
// the caps
check('more than ' + ACT_MAX_OPS + ' operations is refused before anything is read',
      plan({ v: 1, ops: new Array(ACT_MAX_OPS + 1).fill(OK.ops[0]) }).ok === false
      && plan({ v: 1, ops: new Array(ACT_MAX_OPS).fill(OK.ops[0]) }).ok === true);
{
  const wide = [];
  for (let i = 0; i < 60; i++) wide.push(new Array(40).fill('x'));    // 2400 cells
  check('a plan over the ' + ACT_MAX_CELLS + '-cell budget is refused WHOLE, not '
        + 'truncated — half a table written is worse than none',
        plan({ v: 1, ops: [{ op: 'set', at: 'A1', values: wide }] }).ok === false);
  check('…and the budget is shared across ALL the ops in one plan, not per op',
        plan({ v: 1, ops: [
          { op: 'set', at: 'A1', values: [new Array(30).fill('x')] },
          { op: 'style', at: 'A1:AZ100', set: { bl: 1 } }]}).ok === false);
}
check('a set that would land outside the grid this tier can draw is refused',
      plan({ v: 1, ops: [{ op: 'set', at: 'GR5000', values: [['x']] }] }).ok === true
      && plan({ v: 1, ops: [{ op: 'set', at: 'GS1', values: [['x']] }] }).ok === false
      && plan({ v: 1, ops: [{ op: 'set', at: 'A5000', values: [['a'], ['b']] }] }).ok === false);
check('…and so is a style range that reaches past it',
      plan({ v: 1, ops: [{ op: 'style', at: 'A1:GS2', set: { bl: 1 } }] }).ok === false);
// ⚠️ THE ONE DELIBERATE ASYMMETRY, pinned so it reads as a decision
check('RESIZE clamps where SET refuses: a clamped resize loses nothing, a clamped set '
      + 'would drop data',
      plan({ v: 1, ops: [{ op: 'resize', rows: 999999, cols: 999999 }] }).ok === true
      && plan({ v: 1, ops: [{ op: 'resize', rows: 999999 }] }).ops[0].rows === ACT_MAX_ROW + 1
      && plan({ v: 1, ops: [{ op: 'resize', cols: 999999 }] }).ops[0].cols === ACT_MAX_COL + 1);
// the range is an ANCHOR
{
  const p = plan({ v: 1, ops: [{ op: 'set', at: 'A1:B2',
                                 values: [['a'], ['b'], ['c'], ['d'], ['e']] }] });
  check('a range is an ANCHOR, not a clip: five rows offered at A1:B2 write five rows, '
        + 'because clipping would silently drop what the model meant to write',
        p.ok === true && p.count.cells === 5 && p.ops[0].r === 0 && p.ops[0].c === 0);
}
// counting, which is what the preview promises
{
  const p = plan({ v: 1, ops: [
    { op: 'set', at: 'A1', values: [['Month', 'Planned'], ['January', 900]] },
    { op: 'set', at: 'B14', values: [['=SUM(B2:B13)']] },
    { op: 'set', at: 'C1', values: [[null]] },
    { op: 'style', at: 'A1:B1', set: { bl: 1 } },
    { op: 'sheet', add: 'Notes' },
    { op: 'sheet', rename: 'Budget' },
    { op: 'resize', rows: 200 }] });
  check('the plan counts what it will do', p.ok === true);
  eq('…cells, emptied cells and formulas',
     [p.count.cells, p.count.cleared, p.count.formulas], [5, 1, 1]);
  eq('…formatted RANGES (not cells), new sheets, renames and resizes',
     [p.count.styled, p.count.sheets, p.count.renames, p.count.resizes], [1, 1, 1, 1]);
  const s = actSummary(p, 'Sheet1');
  check('the summary reads like the brief asked: "N cells in Sheet1 · N formulas · …"',
        /^5 cells in Sheet1 · 1 cell emptied · 1 formula · 1 formatted range · 1 new sheet/.test(s));
  eq('a plan with one cell says "cell", not "cells"',
     actSummary(plan({ v: 1, ops: [{ op: 'set', at: 'A1', values: [['x']] }] }), 'S'),
     '1 cell in S');
  eq('actSummary is total', [actSummary(null, 'x'), actSummary({}, 'x'),
     actSummary(p, null), actSummary(p, undefined)].map(x => typeof x),
     ['string', 'string', 'string', 'string']);
  // the LIST is what the user actually reads before pressing Apply
  const list = actCellList(p);
  check('the preview lists the exact cells, from the plan\'s OWN values — what it '
        + 'promises is what the apply writes',
        list.lines[0] === 'A1 → Month' && list.lines[1] === 'B1 → Planned'
        && list.lines[2] === 'A2 → January' && list.lines[3] === 'B2 → 900'
        && list.lines[4] === 'B14 → =SUM(B2:B13)');
  check('…an emptied cell reads as (empty) rather than as the word null',
        list.lines[5] === 'C1 → (empty)');
  check('…a style op names its range and the keys it sets',
        list.lines[6] === 'A1:B1 → bl');
  check('…and the sheet and resize ops say what they are',
        /a new sheet called Notes/.test(list.lines[7])
        && /rename a sheet to Budget/.test(list.lines[8])
        && /grow to 200 rows/.test(list.lines[9]));
  eq('the plan\'s own line count agrees with the list, so "+N more" can never lie',
     p.count.lines, list.lines.length + list.more);
}
{
  // the cap, and the "+N more" that goes with it
  const many = [];
  for (let i = 0; i < ACT_LIST_MAX + 15; i++) many.push(['row ' + i]);
  const p = plan({ v: 1, ops: [{ op: 'set', at: 'A1', values: many }] });
  const list = actCellList(p);
  eq('the preview list is capped', list.lines.length, ACT_LIST_MAX);
  eq('…and says how many it did not show', list.more, 15);
  eq('…and the two still add up to the plan', p.count.lines, ACT_LIST_MAX + 15);
}
check('a very long value is shortened in the PREVIEW only — the plan still carries it '
      + 'whole, because the preview is a description and the plan is the data',
      (() => {
        const p = plan({ v: 1, ops: [{ op: 'set', at: 'A1', values: [['y'.repeat(400)]] }] });
        return actCellList(p).lines[0].length < 100 && p.ops[0].values[0][0].length === 400;
      })());
eq('actCellList is total over a junk plan',
   [actCellList(null), actCellList({}), actCellList({ ops: 'nope' })].map(x => x.lines.length),
   [0, 0, 0]);

/* ── finding the block in a real reply ─────────────────────────────────────── */
const REPLY_OK = 'Here is the budget.\n\n```loffice\n'
  + '{"v":1,"file":"2026 budget","sheet":"Sheet1","ops":['
  + '{"op":"set","at":"A1","values":[["Month","Planned","Actual"]]},'
  + '{"op":"set","at":"A2","values":[["January",900,null],["February",900,null]]},'
  + '{"op":"set","at":"B4","values":[["=SUM(B2:B3)"]]},'
  + '{"op":"style","at":"A1:C1","set":{"bl":1}}]}\n```\n\nPress Apply.';
{
  const s = parseActions(REPLY_OK);
  check('a tagged block in a real reply is found, parsed and accepted',
        s.found === true && s.ok === true && s.why === '' && s.extra === 0);
  eq('…and the card is told WHICH fenced part it belongs to', s.at, 1);
  eq('…the prose around it survives as its own parts',
     aiFences(REPLY_OK).map(p => p.kind), ['text', 'code', 'text']);
  eq('…and the plan is the one the block described',
     [s.plan.file, s.plan.sheet, s.plan.ops.length, s.plan.count.cells,
      s.plan.count.formulas, s.plan.count.cleared],
     ['2026 budget', 'Sheet1', 4, 8, 1, 2]);
}
check('an UNTAGGED block is still read when it is unmistakably a plan — a model that '
      + 'writes ```json instead of ```loffice has not failed',
      parseActions('```json\n{"v":1,"ops":[{"op":"set","at":"A1","values":[["x"]]}]}\n```').ok === true);
check('…but ordinary JSON in a reply grows NO Apply button',
      parseActions('```json\n{"name":"x","rows":[1,2]}\n```').found === false);
check('…and neither does ordinary prose, or code, or a formula in a fence',
      parseActions('The CLEAN function strips control characters.').found === false
      && parseActions('```excel\n=SUM(A1:A2)\n```').found === false
      && parseActions('```python\nprint(1)\n```').found === false);
check('a TRUNCATED block — the stream cut mid-JSON — is REPORTED, not silently dropped: '
      + 'the model tried, and the user is owed that',
      (() => {
        const s = parseActions('ok\n```loffice\n{"v":1,"ops":[{"op":"set","at":"A1"');
        return s.found === true && s.ok === false && /not valid JSON/.test(s.why);
      })());
check('a tagged block full of nonsense is reported the same way',
      (() => {
        const s = parseActions('```loffice\nplease write the months in column A\n```');
        return s.found === true && s.ok === false && s.why.length > 8;
      })());
check('a tagged block that PARSES but is not a plan says which part it failed on',
      /"v"/.test(parseActions('```loffice\n{"ops":[]}\n```').why));
{
  const two = '```loffice\n{"v":1,"ops":[{"op":"set","at":"A1","values":[["one"]]}]}\n```\n'
            + 'and also\n'
            + '```loffice\n{"v":1,"ops":[{"op":"set","at":"A1","values":[["two"]]}]}\n```';
  const s = parseActions(two);
  check('with TWO blocks only the FIRST is offered, and the rest are COUNTED — two '
        + 'plans applied in sequence is a change nobody previewed',
        s.found === true && s.ok === true && s.extra === 1
        && s.plan.ops[0].values[0][0] === 'one');
  check('…and the card says so out loud rather than quietly dropping one',
        /further block/.test(grab('actPaint')) && /scan\.extra/.test(grab('actPaint')));
}
check('an empty tagged fence produces nothing at all — aiFences already drops it',
      parseActions('```loffice\n\n```').found === false);
// TOTALITY: every one of these is a value that arrives from a language model
[null, undefined, '', 0, 42, {}, [], '```loffice', '```loffice\n```', '`'.repeat(9),
 '```loffice\n{"v":1,"ops":[{"op":"set","at":"A1","values":[[', '```loffice\nnull\n```',
 '```loffice\n[1,2,3]\n```', '```loffice\n"just a string"\n```',
 '```loffice\n{"v":1,"ops":{"op":"set"}}\n```'
].forEach((v, i) => {
  let out = null, threw = null;
  try { out = parseActions(v); } catch (e) { threw = e; }
  check('parseActions survives whatever the model said (case ' + i + ')',
        !threw && out && typeof out.found === 'boolean' && typeof out.why === 'string');
});
eq('actScan is total over a junk parts array',
   [actScan(null), actScan('nope'), actScan([null, 1, { kind: 'code' }])].map(x => x.found),
   [false, false, false]);

/* ── a value the MODEL wrote → a cell, through the SAME converter typing uses ── */
eq('a JSON number is a number cell', actCell(900, null), { v: 900, t: CV_NUMBER });
eq('a formula string is a formula', actCell('=SUM(B2:B3)', null), { f: '=SUM(B2:B3)' });
eq('a numeric STRING is a number, exactly as if it had been typed',
   actCell('120', null), { v: 120, t: CV_NUMBER });
eq('…and a leading-zero string stays text, for the same reason parseInput says so',
   actCell('007', null), { v: '007', t: CV_STRING });
eq('a boolean is a boolean cell', actCell(true, null), { v: true, t: CV_BOOLEAN });
eq('null and "" empty the cell', [actCell(null, null), actCell('', null)], [null, null]);
// ⚠️ the KEY ORDER in the expectations is not cosmetic: eq() compares JSON, and the
// string path goes through parseInput (which writes `s` first) while the number and
// boolean paths are actCell's own (which write it last). Two different orders because
// there are genuinely two writers, and pinning them proves neither drifted.
eq('the cell\'s STYLE survives a value the model wrote — writing a number into a bold '
   + 'red cell must not strip the bold red',
   [actCell(5, { v: 1, s: { bl: 1 } }), actCell('x', { v: 1, s: { bl: 1 } }),
    actCell(null, { v: 1, s: { bl: 1 } })],
   [{ v: 5, t: CV_NUMBER, s: { bl: 1 } }, { s: { bl: 1 }, v: 'x', t: CV_STRING },
    { s: { bl: 1 } }]);
eq('a non-finite number cannot reach a cell', actCell(Infinity, null), null);

/* ── APPLY, EXECUTED, and the undo that makes it safe to try ──────────────── */
// The write half is run for real against a bare snapshot. actRunOps touches no DOM and
// no view state by construction, which is exactly why this is possible.
// D9 is the SENTINEL: the plan below never mentions it, so it is how "the apply wrote
// only what the preview promised" is checked, and how the undo is checked to have put
// back a cell the change had nothing to do with.
function fresh() {
  return { sheets: { s1: { id: 's1', name: 'Sheet1',
                           cellData: { '8': { '3': { v: 'keep', t: CV_STRING } } },
                           rowCount: 200, columnCount: 26 } },
           sheetOrder: ['s1'] };
}
{
  snap = fresh();
  activeSid = 's1';
  const original = JSON.stringify(snap);
  // exactly what actApply pushes onto the page's ONE undo stack, through the SAME
  // function the ⌘Z path uses — the panel no longer has a clone of its own
  const before = histEntry('the model’s change');
  const p = parseActions(REPLY_OK).plan;
  const done = actRunOps('s1', p.ops);
  check('actRunOps reports what it wrote', !!done && done.cells === 8 && done.cleared === 2);
  eq('the header row landed where the plan said',
     [snap.sheets.s1.cellData['0']['0'].v, snap.sheets.s1.cellData['0']['2'].v],
     ['Month', 'Actual']);
  eq('…a number arrived as a number', snap.sheets.s1.cellData['1']['1'],
     { v: 900, t: CV_NUMBER });
  eq('…a formula arrived as a formula', snap.sheets.s1.cellData['3']['1'], { f: '=SUM(B2:B3)' });
  eq('…and the style op bolded the header without touching its value',
     snap.sheets.s1.cellData['0']['0'], { v: 'Month', t: CV_STRING, s: { bl: 1 } });
  check('the sheet grew to hold what was written',
        Number(snap.sheets.s1.rowCount) >= 4 && done.wantRows === 4 && done.wantCols === 3);
  eq('THE CELL THE PLAN DID NOT MENTION IS UNTOUCHED — the apply writes what the '
     + 'preview promised and nothing else',
     snap.sheets.s1.cellData['8']['3'], { v: 'keep', t: CV_STRING });
  // THE UNDO, performed the way histGo performs it: assign the entry's clone back.
  snap = before.snap;
  eq('UNDO RESTORES THE WORKBOOK EXACTLY — a clone put back, not a list of operations '
     + 'reversed, because reversing has to GUESS what a cell held before',
     JSON.stringify(snap), original);
  eq('…and the entry carries the sheet selection and the dirty flag with it, so the '
     + 'restore is of the whole state and not merely of the cells',
     [before.sid, before.dirty, typeof before.label], ['s1', false, 'string']);
}
{
  // a shared style id is the trap styleWrite() records, and actRunOps must not fall in
  snap = { styles: { S1: { it: 1 } },
           sheets: { s1: { id: 's1', name: 'Sheet1', cellData: {
             '0': { '0': { v: 'a', t: CV_STRING, s: 'S1' },
                    '1': { v: 'b', t: CV_STRING, s: 'S1' } } } } },
           sheetOrder: ['s1'] };
  actRunOps('s1', plan({ v: 1, ops: [{ op: 'style', at: 'A1', set: { bl: 1 } }] }).ops);
  eq('a style write RESOLVES a shared style id, copies it and writes the copy back on '
     + 'THAT ONE CELL — mutating the shared entry would bold half the workbook silently',
     snap.sheets.s1.cellData['0']['0'], { v: 'a', t: CV_STRING, s: { it: 1, bl: 1 } });
  eq('…and the cell that shared the id is untouched',
     snap.sheets.s1.cellData['0']['1'], { v: 'b', t: CV_STRING, s: 'S1' });
  eq('…and the shared entry itself is unchanged', snap.styles.S1, { it: 1 });
}
{
  snap = fresh();
  actRunOps('s1', plan({ v: 1, ops: [{ op: 'sheet', add: 'Notes' },
                                     { op: 'sheet', add: 'Notes' }] }).ops);
  const names = Object.keys(snap.sheets).map(k => snap.sheets[k].name);
  check('two sheets asked for by the same name do not collide — the second is renamed, '
        + 'never dropped and never a duplicate',
        names.length === 3 && names.indexOf('Notes') > 0 && names.indexOf('Notes 2') > 0);
  check('…and both are in the sheet ORDER, so the tab strip shows them',
        snap.sheetOrder.length === 3);
}
{
  snap = fresh();
  actRunOps('s1', plan({ v: 1, ops: [{ op: 'sheet', rename: '2026' }] }).ops);
  eq('a rename with no target renames the sheet the change is aimed at',
     snap.sheets.s1.name, '2026');
}
{
  snap = fresh();
  activeSid = 's1';
  eq('a sheet the model named that does not exist falls back to the open one rather '
     + 'than inventing a sheet nobody asked for', actTargetSid('Nope'), 's1');
  eq('…and one that does exist is found by NAME, which is the only handle a model has',
     actTargetSid('sheet1'), 's1');
  check('…and the card SAYS which of the two happened before you press Apply',
        /actSheetExists/.test(grab('actPaint'))
        && /There is no sheet called/.test(grab('actPaint')));
  check('actRunOps refuses a sheet id that is not there rather than throwing',
        actRunOps('nope', []) === null && actRunOps('s1', 'not a list') === null);
}
{
  // what the card TELLS the user about where the change will land
  snap = fresh(); activeSid = 's1';
  const cur = current;
  current = 'Budget.xlsx';
  eq('the card names the sheet the change lands on', actWhere({ sheet: 'Sheet1' }), 'Sheet1');
  eq('…and names the OPEN one when the model asked for a sheet that is not there, '
     + 'which is exactly what it then does', actWhere({ sheet: 'Nope' }), 'Sheet1');
  current = '';
  eq('…and with nothing open it says a new spreadsheet, by the name the model chose',
     actWhere({ file: '2026 budget' }), 'a new spreadsheet called 2026 budget');
  eq('…or just a new spreadsheet when it chose none', actWhere({}), 'a new spreadsheet');
  current = cur;
}
check('a workbook too big to clone still applies, and the card says the change cannot '
      + 'be taken back — an Undo button that would not work is worse than none',
      (() => { snap = { big: 'x'.repeat(HIST_MAX_BYTES) }; return histEntry('x') === null; })()
      && /too large to hold an undo copy/.test(grab('actPaint'))
      && /card\._undo = !!entry/.test(grab('actApply')));
check('the cloner survives a snapshot it cannot serialise at all',
      (() => { const o = {}; o.self = o; snap = o; return histEntry('x') === null; })());
check('…and one that CAN be cloned comes back as a real entry',
      (() => { snap = fresh(); const e = histEntry('a label');
               return !!e && !!e.snap && e.snap !== snap
                      && JSON.stringify(e.snap) === JSON.stringify(snap); })());

/* ══ PART 5 — THE TWO NEW OPS: sort, and insert / delete_rc ════════════════════
   (2026-08-27a) The AI path gets the same two gestures the menu just got, through the
   SAME functions — `sortOrder` + `gridRemap` for a sort, `rcApply` for an insert or a
   delete — so there is no second idea of what either means. What is NEW here is the
   caps discipline and the honest-limits reporting, and both are executed. */

check('the help teaches the two new ops, so a model has a way to ask for them',
      ['"op":"sort"', '"op":"insert"', '"op":"delete_rc"'].every(s => HELP.indexOf(s) >= 0));
check('…and teaches the two honest limits with them: a sort is REFUSED on merged cells, '
      + 'and formula references are NOT rewritten',
      /REFUSED on a sheet that has merged cells/.test(HELP)
      && /FORMULA REFERENCES ARE NOT/.test(HELP));

// ── a column, and where an insert lands ──
eq('a sort column is a LETTER, with or without a row and with or without the $',
   [actCol('B'), actCol('b'), actCol('$B$4'), actCol('AA'), actCol('GR')],
   [1, 1, 1, 26, 199]);
eq('…and a bare NUMBER is refused: it is ambiguous between "column 2" and "column B" '
   + 'the moment anybody 0-indexes it, and a sort aimed one column over is a silently '
   + 'wrong document',
   [actCol('2'), actCol(2), actCol(''), actCol(null), actCol('the sales column')],
   [-1, -1, -1, -1, -1]);
eq('an insert row target is a 1-based row NUMBER, or a cell reference, because a model '
   + 'that has seen a spreadsheet writes both',
   [actRcTarget('row', 3), actRcTarget('row', '3'), actRcTarget('row', 'A3'),
    actRcTarget('row', 0), actRcTarget('row', 'x')], [2, 2, 2, -1, -1]);
eq('…and a column target is a letter', [actRcTarget('col', 'D'), actRcTarget('col', 4)],
   [3, -1]);

// ── the validator on the new ops ──
{
  const p = plan({ v: 1, ops: [{ op: 'sort', col: 'B', desc: true }] });
  check('a sort validates and carries the column and the direction',
        p.ok === true && p.ops[0].col === 1 && p.ops[0].desc === true);
  eq('…and counts as a sort, not as cells', [p.count.sorts, p.count.cells], [1, 0]);
  check('the direction is accepted the several ways a model writes it',
        plan({ v: 1, ops: [{ op: 'sort', col: 'A', order: 'desc' }] }).ops[0].desc === true
        && plan({ v: 1, ops: [{ op: 'sort', col: 'A', dir: 'descending' }] }).ops[0].desc === true
        && plan({ v: 1, ops: [{ op: 'sort', col: 'A' }] }).ops[0].desc === false);
  check('…and "at" is taken as the column too, because half the models will write that',
        plan({ v: 1, ops: [{ op: 'sort', at: 'C1' }] }).ops[0].col === 2);
}
{
  const p = plan({ v: 1, ops: [{ op: 'insert', what: 'row', at: 3, n: 2 },
                               { op: 'delete_rc', what: 'col', at: 'D' }] });
  check('an insert and a delete both validate', p.ok === true);
  eq('…as row/column indexes, 0-based inside the page and 1-based on the wire',
     [p.ops[0].axis, p.ops[0].at, p.ops[0].n, p.ops[1].axis, p.ops[1].at, p.ops[1].n],
     ['row', 2, 2, 'col', 3, 1]);
  eq('…and they are counted apart from each other, because one adds and one destroys',
     [p.count.inserts, p.count.deletes], [2, 1]);
  check('"rows"/"columns"/"column" are all understood, and "axis" as well as "what"',
        plan({ v: 1, ops: [{ op: 'insert', what: 'rows', at: 1 }] }).ops[0].axis === 'row'
        && plan({ v: 1, ops: [{ op: 'insert', what: 'columns', at: 'A' }] }).ops[0].axis === 'col'
        && plan({ v: 1, ops: [{ op: 'insert', axis: 'column', at: 'A' }] }).ops[0].axis === 'col');
}
[['a sort with no column', { v: 1, ops: [{ op: 'sort' }] }],
 ['a sort whose column is prose', { v: 1, ops: [{ op: 'sort', col: 'the totals' }] }],
 ['a sort past the last column this grid draws', { v: 1, ops: [{ op: 'sort', col: 'GS' }] }],
 ['an insert with no axis', { v: 1, ops: [{ op: 'insert', at: 1 }] }],
 ['an insert with a junk axis', { v: 1, ops: [{ op: 'insert', what: 'diagonal', at: 1 }] }],
 ['an insert with no target', { v: 1, ops: [{ op: 'insert', what: 'row' }] }],
 ['an insert past the row ceiling', { v: 1, ops: [{ op: 'insert', what: 'row', at: 99999 }] }],
 ['a delete of more rows than the cap', { v: 1, ops: [{ op: 'delete_rc', what: 'row', at: 1, n: RC_MAX + 1 }] }]
].forEach(([label, obj]) => {
  const p = plan(obj);
  check('REFUSED, with a reason a person can read — ' + label,
        p.ok === false && typeof p.why === 'string' && p.why.length > 8);
});
// ⚠️ THE ASYMMETRY, AGAIN AND ON PURPOSE — the same one `set` and `resize` carry
check('an INSERT over the cap is CLAMPED and a DELETE over it is REFUSED: a clamped '
      + 'insert loses nothing (it is empty space), a clamped delete would destroy '
      + 'exactly as much data as it felt like',
      plan({ v: 1, ops: [{ op: 'insert', what: 'row', at: 1, n: 99999 }] }).ops[0].n === RC_MAX
      && plan({ v: 1, ops: [{ op: 'delete_rc', what: 'row', at: 1, n: 99999 }] }).ok === false);
check('a missing or junk "n" is one, which is what a model means when it omits it',
      plan({ v: 1, ops: [{ op: 'insert', what: 'row', at: 1 }] }).ops[0].n === 1
      && plan({ v: 1, ops: [{ op: 'insert', what: 'row', at: 1, n: 'a few' }] }).ops[0].n === 1);

// ── the preview, which is what the user actually reads before pressing Apply ──
{
  const p = plan({ v: 1, ops: [{ op: 'sort', col: 'B', desc: true },
                               { op: 'insert', what: 'row', at: 3 },
                               { op: 'delete_rc', what: 'col', at: 'D', n: 2 }] });
  const list = actCellList(p);
  check('the preview says the sort covers the WHOLE sheet, row 1 included, and which way',
        /sort the whole sheet by column B \(Z → A\) — row 1 included/.test(list.lines[0]));
  check('…names where an insert lands', /insert 1 blank row above row 3/.test(list.lines[1]));
  check('…and says, in capitals, that a delete LOSES the data in it',
        /DELETE 2 cols from column D — data in them is lost/.test(list.lines[2]));
  const s = actSummary(p, 'Sheet1');
  check('the summary names the structural changes rather than burying them in a cell '
        + 'count, and shouts the destructive one',
        /the sheet sorted/.test(s) && /1 row or column inserted/.test(s)
        && /2 rows or columns DELETED/.test(s));
  eq('the plan\'s line count still agrees with the list, so "+N more" cannot lie',
     p.count.lines, list.lines.length + list.more);
}
check('the card warns about a delete BEFORE the click, by name, because a count does not '
      + 'read as "this loses data"',
      /This DELETES/.test(grab('actPaint')) && /plan\.count\.deletes/.test(grab('actPaint')));
check('…and says, before the click, that a sort on a merged sheet WILL be refused — the '
      + 'refusal is not saved up for afterwards',
      /The sort will be REFUSED/.test(grab('actPaint'))
      && /sheetMerges\(shs\)/.test(grab('actPaint')));
check('…and that merged ranges are renumbered while formula references are NOT',
      /FORMULA REFERENCES ARE NOT/.test(grab('actPaint')));

/* ── EXECUTED: the two ops, against bare snapshots ───────────────────────────── */
function sortable(opts) {
  const o = opts || {};
  const cd = { '0': { '0': { v: 'b', t: CV_STRING }, '1': { v: 30, t: CV_NUMBER } },
               '1': { '0': { v: 'a', t: CV_STRING }, '1': { v: 10, t: CV_NUMBER } },
               '2': { '0': { v: 'c', t: CV_STRING }, '1': { v: 20, t: CV_NUMBER } } };
  if (o.formula) cd['2']['2'] = { f: '=B3*2', v: 40, t: CV_NUMBER };
  const sh = { id: 's1', name: 'Sheet1', cellData: cd, rowCount: 200, columnCount: 26 };
  if (o.merge) sh.mergeData = o.merge;
  return { sheets: { s1: sh }, sheetOrder: ['s1'] };
}
{
  snap = sortable(); activeSid = 's1';
  const done = actRunOps('s1', plan({ v: 1, ops: [{ op: 'sort', col: 'B' }] }).ops);
  eq('an AI sort really sorts, through the same sortOrder + gridRemap the menu uses',
     [0, 1, 2].map(r => snap.sheets.s1.cellData[String(r)]['1'].v), [10, 20, 30]);
  eq('…and column A came with it', [0, 1, 2].map(r => snap.sheets.s1.cellData[String(r)]['0'].v),
     ['a', 'c', 'b']);
  eq('…and it is reported as one sort, not as cells', [done.sorted, done.cells], [1, 0]);
  eq('…with nothing to warn about on a sheet that holds no formula', done.notes, []);
}
{
  snap = sortable({ formula: true }); activeSid = 's1';
  const done = actRunOps('s1', plan({ v: 1, ops: [{ op: 'sort', col: 'B' }] }).ops);
  eq('the formula moved as TEXT and still says what it said',
     snap.sheets.s1.cellData['1']['2'].f, '=B3*2');
  eq('…and the card is handed the SAME honest note the menu prints, from the same '
     + 'constant — one sentence, not two that can drift', done.notes, [RC_FORMULA_NOTE]);
}
{
  // THE MERGE REFUSAL, on the AI path
  snap = sortable({ merge: [{ startRow: 0, endRow: 0, startColumn: 0, endColumn: 1 }] });
  activeSid = 's1';
  const was = JSON.stringify(snap);
  const done = actRunOps('s1', plan({ v: 1, ops: [
    { op: 'sort', col: 'B' },
    { op: 'set', at: 'E1', values: [['still applied']] }] }).ops);
  eq('A SORT ON A MERGED SHEET IS REFUSED HERE TOO, and no cell moved',
     [0, 1, 2].map(r => snap.sheets.s1.cellData[String(r)]['1'].v), [30, 10, 20]);
  eq('…it is counted as skipped and SAID, rather than swallowed', done.skipped, 1);
  check('…in words that name what would have gone wrong',
        done.notes.length === 1 && /merged range/.test(done.notes[0])
        && /never belonged together/.test(done.notes[0]));
  eq('…and the REST of the plan still applied, because that is what the user read and '
     + 'pressed Apply for — one honest note beats losing all of it',
     snap.sheets.s1.cellData['0']['4'], { v: 'still applied', t: CV_STRING });
  check('the merge itself is untouched', JSON.stringify(snap.sheets.s1.mergeData)
        === JSON.stringify(JSON.parse(was).sheets.s1.mergeData));
}
{
  // INSERT, on the AI path: the merge shifts, the formula does not
  snap = { sheets: { s1: { id: 's1', name: 'Sheet1', rowCount: 200, columnCount: 26,
    mergeData: [{ startRow: 2, endRow: 2, startColumn: 0, endColumn: 1 }],
    cellData: { '0': { '0': { v: 'top', t: CV_STRING } },
                '2': { '0': { v: 'below', t: CV_STRING },
                       '1': { f: '=A1', v: 'top', t: CV_STRING } } } } },
    sheetOrder: ['s1'] };
  activeSid = 's1';
  const done = actRunOps('s1', plan({ v: 1,
    ops: [{ op: 'insert', what: 'row', at: 2 }] }).ops);
  eq('an AI insert moves the rows below it down, once',
     snap.sheets.s1.cellData['3']['0'], { v: 'below', t: CV_STRING });
  eq('…leaving the inserted row blank', snap.sheets.s1.cellData['2'], undefined);
  eq('THE MERGE WAS RENUMBERED', snap.sheets.s1.mergeData,
     [{ startRow: 3, endRow: 3, startColumn: 0, endColumn: 1 }]);
  eq('THE FORMULA WAS NOT: it still says =A1, and the card is told to say so',
     [snap.sheets.s1.cellData['3']['1'].f, done.notes], ['=A1', [RC_FORMULA_NOTE]]);
  eq('…and it is counted as an insert', [done.inserted, done.deleted], [1, 0]);
}
{
  snap = sortable(); activeSid = 's1';
  const done = actRunOps('s1', plan({ v: 1,
    ops: [{ op: 'delete_rc', what: 'row', at: 1 }] }).ops);
  eq('an AI delete removes the band and pulls the rest up — "at":1 is ROW 1, the way a '
     + 'person says it, so the first row is the one that goes',
     [0, 1].map(r => snap.sheets.s1.cellData[String(r)]['0'].v), ['a', 'c']);
  eq('…and clears the tail rather than leaving a duplicate',
     snap.sheets.s1.cellData['2'], undefined);
  eq('…counted as a delete', done.deleted, 1);
}
check('the AI ops go through the SAME rcApply and sortOrder the menu rows do, so a model '
      + 'cannot reach a sort or an insert the menu does not perform',
      /sortOrder\(sh, o\.col, o\.desc, u\.rows\)/.test(grab('actRunOps'))
      && /rcApply\(sh, o\.op === 'insert'/.test(grab('actRunOps')));
check('actRunOps STILL touches no view state, no dirty flag and no DOM, even with the '
      + 'two structural ops in it — which is the property that lets everything above '
      + 'run against a bare snapshot',
      (() => {
        const ro = stripComments(grab('actRunOps'));
        return !/dirty/.test(ro) && !/renderGrid/.test(ro) && !/viewRows|viewCols/.test(ro)
               && !/document\./.test(ro) && !/\bel\(/.test(ro);
      })());
check('the formula note is asked ONCE PER APPLY, after the writes, and only when the '
      + 'sheet still holds one — not once per operation',
      /if \(\(done\.sorted \|\| done\.inserted \|\| done\.deleted\) && sheetFormulas\(sh\)\)/
        .test(grab('actRunOps')));
check('and every note actRunOps came back with is PRINTED on the applied card — a '
      + 'refusal the card swallowed would read as a change that happened',
      /\(done\.notes \|\| \[\]\)\.forEach/.test(grab('actPaint')));

/* ── THE STRUCTURAL FENCES ─────────────────────────────────────────────────── */
// THE ONE THAT MATTERS MOST, and it replaces the old "the panel never writes": the
// COMPLETE set of functions in this page that may write a cell. Computed over every
// function in the document, so moving a putCell one level down cannot defeat it.
const fnNames = Array.from(new Set((code.match(/function\s+([A-Za-z_$][\w$]*)\s*\(/g) || [])
  .map(s => s.replace(/^function\s+/, '').replace(/\s*\($/, ''))));
check('the scan really found the page\'s functions — a vacuous fence is no fence',
      fnNames.length > 40 && fnNames.indexOf('commit') >= 0
      && fnNames.indexOf('actRunOps') >= 0);
const writeFns = fnNames.filter(n => {
  let body = '';
  try { body = grabFrom(code, n, 'office.html'); } catch (e) { return false; }
  return /\bputCell\s*\(/.test(body.slice(body.indexOf('{')));
}).sort();
/* ⚠️⚠️ THE FENCE GREW FROM FIVE NAMES TO SEVEN AT 2026-08-27a, AND THAT IS A DELIBERATE,
   ARGUED CHANGE — a writer-set fence is only worth having if widening it is a decision
   somebody had to write down. The slice added Find-and-replace, sort, and insert/delete
   row/column, i.e. three gestures that CHANGE CELLS, and they were given exactly TWO new
   writers rather than five:

     · `replaceWrite`  — the only thing that puts a NEW VALUE in a cell. Both Replace and
                         Replace all go through it (one hit or many), so there is one
                         place where a replaced cell is re-typed through parseInput.
     · `gridRemap`     — the only thing that MOVES cells. Sort, insert row, insert
                         column, delete row and delete column are all one remap over a
                         source function, so the capture-before-write rule that makes an
                         in-place shift correct is written once and tested once.

   Both are shared by the MANUAL gestures and the AI ops, which is the property that
   matters most: the model cannot reach a code path the menu does not, so there is no
   second idea of what a sort or an insert means. Anything beyond these seven appearing
   here is a new writer and needs the same argument made in the same place. */
eq('EXACTLY these functions may write a cell — the grid\'s own three, the template '
   + 'builder, the AI panel\'s ONE writer, and the two this slice added. Nothing else '
   + 'in the page can.',
   writeFns, ['actRunOps', 'clearCell', 'commit', 'gridRemap', 'newFromTemplate',
              'replaceWrite', 'styleWrite']);
check('…and the two new writers are SHARED by the menu gestures and the AI ops, so the '
      + 'model cannot reach a code path the menu does not',
      /gridRemap\(/.test(grab('sortGo')) && /gridRemap\(/.test(grab('rcApply'))
      && /gridRemap\(/.test(grab('actRunOps')) && /rcApply\(/.test(grab('actRunOps'))
      && /rcApply\(/.test(grab('rcGo'))
      && /replaceWrite\(/.test(grab('findReplaceOne'))
      && /replaceWrite\(/.test(grab('findReplaceAll')));
check('…and neither of them touches view state, a dirty flag or the DOM, which is why '
      + 'both are executed against bare snapshots in test_office_grid.js',
      ['gridRemap', 'replaceWrite'].every(fn => {
        const s = stripComments(grab(fn));
        return !/dirty/.test(s) && !/renderGrid/.test(s) && !/viewRows|viewCols/.test(s)
               && !/document\./.test(s) && !/\bel\(/.test(s);
      }));
/* ⚠️⚠️ AND AT 2026-08-27b THE FENCE DID NOT MOVE, WHICH IS THE POINT OF THAT SLICE.
   The toolbar row (§7.3 of the reference) put twelve buttons on screen for commands that
   already existed, and the way it stayed out of the list above IS the design ruling: a
   toolbar button's click is `el(b.dataset.row).click()` — the menu row's own click — so
   the write path is the menu's write path and there is nothing new here to fence. The
   assertions below are what make that a fact rather than a claim. */
check('THE TOOLBAR ADDED NO WRITER, and it could not have: its handler contains no write '
      + 'of any kind, only the row\'s own click',
      (() => {
        // lastIndexOf: the first use of this iterator is inside toolbarPaint (asserted
        // separately below); the WIRING is the last one, at the bottom of the page
        const at = code.lastIndexOf('toolbarButtons().forEach');
        if (at < 0) return false;
        const body = code.slice(at, code.indexOf('\n});', at) + 4);
        return /row\.click\(\)/.test(body) && !writers.test(body)
               && !/styleWrite|fmtToggle|fmtAlign|fmtClear|histGo/.test(body);
      })());
check('…nor does the thing that paints it: toolbarPaint reads `disabled`, `title` and the '
      + 'menu TICK off the rows, and writes nothing anywhere',
      (() => {
        const tp = stripComments(grab('toolbarPaint'));
        return !writers.test(tp) && !/\bsnap\b/.test(tp)
               && /menuPaint\(1\)/.test(tp) && /menuPaint\(4\)/.test(tp)
               && /row\.disabled/.test(tp) && /mtick/.test(tp);
      })());
check('…and the ONE button with a handler of its own calls an EXISTING page function, '
      + 'findOpen, in its own toggle form',
      /'tb-find': \(\) => findOpen\(\)/.test(code) && fnNames.indexOf('findOpen') >= 0);
check('the submenu engine writes nothing either — it moves ONE variable and toggles a '
      + 'class, which is why its transition function can be executed on its own',
      ['subNext', 'subFlip', 'subApply', 'subGo', 'subHidden', 'subEnter', 'subLeave']
        .every(fn => {
          const s = stripComments(grab(fn));
          return !writers.test(s) && !/\bsnap\b/.test(s);
        }));
check('…and its two PURE halves really are pure — no DOM, no page state, nothing but '
      + 'their arguments — which is the property the state-machine tests stand on',
      ['subNext', 'subFlip'].every(fn => {
        const s = stripComments(grab(fn));
        return !/document\.|\bel\(|\bbx\(|openSub/.test(s);
      }));
check('…and the fence would notice a new writer appearing', (() => {
  const faked = code.replace('function aiGrow(', 'function aiGrow(){putCell(1,2,3,4)}\nfunction aiGrowX(');
  let body = '';
  try { body = grabFrom(faked, 'aiGrow', 'faked'); } catch (e) { return false; }
  return /\bputCell\s*\(/.test(body.slice(body.indexOf('{')));
})());

// NOTHING APPLIES WITHOUT A CLICK.
const applySites = (code.match(/\bactApply\s*\(/g) || []).length;
eq('`actApply` appears exactly twice in the page: its definition and ONE call site',
   applySites, 2);
check('…and that call site is a button\'s own onclick handler',
      /yes\.onclick = \(\) => actApply\(card, plan\)/.test(grab('actPaint')));
check('…on a button labelled Apply (or Create & apply when there is no workbook yet)',
      /actChip\(bar, current \? 'Apply' : 'Create & apply'\)/.test(grab('actPaint')));
check('nothing on a timer, and no auto-apply anywhere near the reply path',
      !/setTimeout[\s\S]{0,80}actApply/.test(code) && !/actApply/.test(stripComments(send))
      && !/actApply/.test(stripComments(grab('aiRenderBody')))
      && !/actApply/.test(stripComments(grab('actCard'))));
check('the card renderers write no cell of their own',
      ['actCard', 'actPaint', 'actChip', 'actDet', 'actNote', 'actCellList', 'actSummary']
        .every(fn => !/\bputCell\s*\(/.test(grab(fn))));
check('the parse half touches no global and no DOM at all',
      ['actValidate', 'actScan', 'actGrid', 'actStyleSet', 'actRef', 'actRange', 'actCell']
        .every(fn => !/document\.|\bel\(|\bsnap\b|dirty|renderGrid/.test(grab(fn))));

// THE APPLY ITSELF. ⚠️ the NEGATIVES are asserted over the comment-stripped body: this
// function's comments talk about saving and about the user, and a negative that a
// comment can defeat is worse than none (the rule stripComments exists for).
const ap = grab('actApply');
const apCode = stripComments(ap);
// ⚠️ REWRITTEN AT 2026-08-27a: the clone is still taken before the first write, but it
// is taken onto the PAGE'S ONE UNDO STACK rather than into this panel's own variable.
// That is the point of the slice — the sheet had two histories that could not see each
// other (the AI's single clone, and nothing at all for anything the user typed).
check('the undo entry is pushed BEFORE the first write, or there is nothing to restore',
      apCode.indexOf('histPush(') > 0
      && apCode.indexOf('histPush(') < apCode.indexOf('actRunOps('));
check('…onto the SAME stack ⌘Z walks, so the AI apply is one entry among the user\'s own '
      + 'and neither can strand the other',
      /const entry = histPush\(/.test(apCode)
      && /actLast = entry \? \{ entry: entry, card: card, name: current \} : null/.test(apCode));
check('the document is marked dirty and the grid redrawn, so the change is on screen',
      /dirty = true/.test(apCode) && /renderGrid\(\)/.test(apCode));
// ⚠️ THE RULE THE BRIEF ASKED FOR IN SO MANY WORDS: never auto-save over their file.
check('APPLY NEVER SAVES. The file is written only when the user presses ⌘S — an '
      + 'auto-save would put a model\'s guess into a document with no way back',
      !/\bsave\s*\(/.test(apCode) && apCode.indexOf('/api/office/save') < 0
      && /press ⌘S/.test(grab('actPaint')));
check('and the WRITER touches no view state and no dirty flag of its own, which is why '
      + 'it can be run against a bare snapshot in this file',
      (() => {
        const ro = stripComments(grab('actRunOps'));
        return !/dirty/.test(ro) && !/renderGrid/.test(ro) && !/viewRows|viewCols/.test(ro)
               && !/document\./.test(ro) && !/\bel\(/.test(ro);
      })());
check('parseActions is nothing but actScan over the parts aiFences already made — one '
      + 'fence parser for the whole panel',
      /function parseActions\(text\) \{ return actScan\(aiFences\(text\)\); \}/.test(code));
check('a second click while it is working is ignored, and an applied card cannot be '
      + 'applied twice', /card\._state === 'busy' \|\| card\._state === 'applied'/.test(ap));
check('the rich editor OWNS the document once it has mounted, so Apply refuses there '
      + 'in the same words the Format menu uses, rather than writing a snapshot nobody '
      + 'is looking at', /mode !== 'grid'/.test(ap) && /T1_ONLY/.test(ap));
check('with no workbook open, Apply CREATES one first — which is the whole of "create a '
      + 'document with data on that page"',
      /if \(!current\)/.test(ap) && /await create\(\)/.test(ap)
      && /el\('new-name'\)\.value = plan\.file/.test(ap));
check('…and a create that failed leaves the card re-armed and says so, rather than '
      + 'writing into nothing',
      /create failed/.test(ap) && /card\._state = 'ready'/.test(ap));
check('it goes through the SAME /api/office/new route the New button uses — no new '
      + 'endpoint for this feature either',
      /fetch\('\/api\/office\/new'/.test(grab('create')));

// THE UNDO
const un = grab('actUndo');
check('the card\'s Undo goes through the page\'s undo stack rather than restoring a clone '
      + 'of its own — one history, one restore path',
      /histGo\('undo'\)/.test(un) && !/snap = /.test(un));
check('…which restores the clone whole, dirty flag included, so a clean document goes '
      + 'back to CLEAN and stops asking to be saved for a change that no longer exists',
      /snap = e\.snap/.test(grab('histRestore')) && /dirty = e\.dirty/.test(grab('histRestore')));
check('…and it will not restore over a DIFFERENT workbook',
      /current !== actLast\.name/.test(un));
check('…nor silently do nothing when a later change replaced the copy: a dead button '
      + 'is the defect class this page exists to remove',
      /actLast\.card !== card/.test(un) && /can no longer be undone/.test(un));
// ⚠️ THE STALENESS TEST GOT SHARPER, not looser: it used to mean "a second apply
// replaced my clone", and it now means "my entry is still the TOP of the stack". A cell
// typed after the apply would ALSO have made restoring this entry wrong — it would have
// thrown that typing away — and the old test could not see that at all.
check('the card refuses when ANYTHING has changed the sheet since it applied, not merely '
      + 'when another apply has, and it points at ⌘Z which walks the stack properly',
      /histTop\('undo'\) !== actLast\.entry/.test(un)
      && /Edit → Undo \(⌘Z\)/.test(un));
check('only the LAST apply is undoable, and the card only draws the button when it is '
      + 'the one holding the entry',
      /card\._undo && actLast && actLast\.card === card/.test(grab('actPaint')));

// ZERO NEW CSS — the card is built from the grammar the reply renderer already had
{
  const cardSrc = ['actCard', 'actPaint', 'actChip', 'actDet', 'actNote'].map(grab).join('\n');
  const cls = Array.from(new Set(
    (cardSrc.match(/className = '([\w-]+)'/g) || []).map(s => s.split("'")[1])
      .concat((cardSrc.match(/actChip\(bar, [^,]+, '([\w-]+)'\)/g) || [])
        .map(s => s.split("'").slice(-2)[0]))));
  check('the card uses several of the existing classes', cls.length >= 6);
  check('…and EVERY ONE of them is already in the stylesheet — which is the whole of '
        + 'the zero-new-CSS claim: a class the card invented would have to be styled '
        + 'to be worth having, and there is no rule for one',
        cls.every(c => rules.some(r => new RegExp('\\.' + c + '(?![\\w-])').test(r.sel))), cls);
  // ⚠️ THE ONE HONEST DEVIATION, PINNED RATHER THAN HIDDEN: the card sets four
  // properties inline (the same trick #fnote and say() already use) because .aicode's
  // own <pre> rule would otherwise impose code styling on a block of ordinary prose.
  const inline = Array.from(new Set((cardSrc.match(/\.style\.([A-Za-z]+) =/g) || [])
    .map(s => s.replace(/\.style\.| =/g, '')))).sort();
  eq('…and the only hand-styling on it is four inline properties', inline,
     ['color', 'fontSize', 'marginTop', 'padding']);
}

// BEACONS — this page's whole diagnostic contract, extended to the new capability
['action-parsed', 'action-applied', 'action-undone', 'action-refused', 'action-dismissed']
  .forEach(st => check('the panel beacons ' + st, code.indexOf("bx('" + st + "'") > 0));
check('the parse beacon carries the refusal reason, so "it did nothing" is answerable '
      + 'from the boot log alone', /bx\('action-parsed'[\s\S]{0,320}scan\.why/.test(code));
check('…and the applied beacon says whether an undo copy was kept',
      /bx\('action-applied'[\s\S]{0,400}too-large/.test(code));
check('…and counts the structural ops too, so "it sorted my sheet" is answerable from '
      + 'the boot log', /bx\('action-applied'[\s\S]{0,400}sorted=/.test(code)
      && /bx\('action-applied'[\s\S]{0,400}deleted=/.test(code));
check('the stack beacons its own pushes, clears and the too-large case',
      ['hist-push', 'hist-clear', 'hist-too-large']
        .every(st => code.indexOf("bx('" + st + "'") > 0));
// the undo and the redo share ONE call site, named by the direction — which is why
// test_office_grid.js asserts those two by EXECUTING histGo rather than by grepping
check('…and the undo and the redo through one call site named by direction',
      /bx\('hist-' \+ dir/.test(code));

// WHAT THE PANEL PROMISES THE USER, which must match what it does
check('the placeholder says the model can fill the sheet in',
      /<b>fill the sheet in<\/b>/.test(html));
check('…and names the three guarantees: a preview, an Apply, an Undo',
      /preview of every cell/.test(html) && /<b>Apply<\/b>/.test(html)
      && /<b>Undo<\/b>/.test(html));
check('…and that the FILE is only written on ⌘S',
      /file only written when you press ⌘S/.test(html));
check('the block header no longer claims the panel is advisory only, because it is not',
      html.indexOf('AND IT IS ADVISORY ONLY') < 0
      && /NO LONGER ADVISORY ONLY/.test(html));

// ── report ──
console.log('');
if (fails.length) {
  console.log(`${fails.length} FAILED (of ${pass + fails.length}):`);
  fails.forEach(f => console.log('  -', f));
  process.exit(1);
}
console.log(`loffice chrome scope + AI panel OK — ${pass} checks passed`);
