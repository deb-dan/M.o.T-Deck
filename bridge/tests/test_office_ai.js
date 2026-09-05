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

// A contiguous RUN of const declarations, first..last inclusive, taken verbatim out of
// the page. Added at loffice-2026-08-28d: the coercion rule and the contextual-inference
// weights are constants (regexes, word lists, weights) that several eval'd functions
// close over, and restating them here would be a second copy of the exact thing this
// test exists to pin.
// ⚠️ `const` → `var` IS LOAD-BEARING: a `const` declared inside eval() is block-scoped to
// that eval and does NOT leak into this module, so every function eval'd afterwards would
// throw ReferenceError on those names. `var` in a direct sloppy-mode eval does leak,
// which is the same mechanism the function declarations already rely on. The VALUES stay
// the page's, verbatim.
function grabConsts(first, last) {
  const a = html.indexOf('const ' + first);
  const c = html.indexOf('const ' + last);
  if (a < 0 || c < 0) throw new Error('const run ' + first + '..' + last + ' not found');
  const b = html.indexOf('\n', c);
  if (b < a) throw new Error('const run ' + first + '..' + last + ' is out of order');
  return html.slice(a, b).replace(/(^|\n)(\s*)const /g, '$1$2var ');
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
      /el\('ai-send'\)\.disabled = aiBusy \|\| agentHistoryLoading \|\| !aiModel/
        .test(grab('aiPaint')));
check('a status fetch that throws leaves the model UNKNOWN rather than claiming one',
      /catch[\s\S]{0,200}aiModel = ''/.test(grab('aiRefreshModel')));

// ── the context builder ──────────────────────────────────────────────────────
const AI_CTX_ROWS = num('AI_CTX_ROWS'), AI_CTX_COLS = num('AI_CTX_COLS'),
      AI_CTX_CHARS = num('AI_CTX_CHARS');
check('the caps are the ones the brief asked for (≤200 rows × 30 cols, ≤20k chars)',
      AI_CTX_ROWS === 200 && AI_CTX_COLS === 30 && AI_CTX_CHARS === 20000);
const CV_STRING = num('CV_STRING'), CV_NUMBER = num('CV_NUMBER'), CV_BOOLEAN = num('CV_BOOLEAN');
eval(grab('colName')); eval(grab('a1')); eval(grab('cellAt')); eval(grab('valueText'));
eval(grab('displayText')); eval(grab('usedExtent'));
// The coercion rule, because ctxCellText now asks it whether a cell is text-that-looks-
// numeric (the type-honest grounding, loffice-2026-08-28d).
eval(grabConsts('CO_MAX_LEN', 'CO_LEADING_ZERO'));
eval(grab('stripTextMark')); eval(grab('coDp')); eval(grab('coPattern'));
eval(grab('coNum')); eval(grab('coerceNumeric')); eval(grab('textNumeric'));
eval(grab('ctxCellText'));
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
// ⚠️ upgrade() dropped out of this list at loffice-2026-08-27c and that is correct,
// not a regression: tier 2 is now a NAVIGATION to /oo-edit, so there is no panel left
// on this page to recount. It is asserted the other way round instead.
check('…as does opening another workbook',
      /aiPaint\(true\)/.test(grab('openDoc'))
      && !/aiPaint/.test(grab('upgrade')));

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
/* ⚠️⚠️ TWO CHAT URLS AS OF loffice-2026-08-27e, AND THE SECOND ONE IS THE POINT OF THE
   SLICE. The Agent lane speaks the harness's EXISTING Hermes lane — the same endpoint,
   body and SSE frames the main panel's Hermes mode uses — so it is a SHARED lane, not
   an office-specific one. The negative that actually matters is unchanged and is
   asserted above: there is no /api/office/chat and no /api/office/ask. */
eq('…and the only chat URLs anywhere in the page are the two SHARED lanes — the direct '
   + 'one for Quick and the Hermes one for Agent',
   urls.filter(u => /chat|ask|complet/.test(u)).sort(),
   ["'/api/chat/direct'", "'/api/hermes/chat'"]);
check('every URL the page calls is one of the endpoints that already existed',
      urls.every(u => ["'/api/chat/direct'", "'/api/status'", "'/api/office/files'",
                       "'/api/office/new'", "'/api/office/save'", "'/api/office/delete'",
                       "'/api/office/rename'",
                       "'/api/office/upload?name='", "'/api/office/open/'",
                       "'/api/office/download/'", "'/api/office/diag'",
                       // TIER 2 (loffice-2026-08-27c): the ONLY new endpoint the page
                       // calls. It asks whether the ONLYOFFICE bundle is installed
                       // before navigating, so the button is never a dead click. The
                       // editor page itself is /oo-edit, not an /api/ URL — this page
                       // does not talk to the editor, it hands the file over to it.
                       "'/api/oo/status'",
                       // SLICE S2 (loffice-2026-08-27e) — the Agent lane. FIVE URLs,
                       // and not one of them is new to the harness: three are the
                       // Hermes lane the main panel already drives, and two are the
                       // office surfaces slice S1 shipped for exactly this page.
                       "'/api/hermes/chat'", "'/api/hermes/approve'",
                       "'/api/hermes/session/'", "'/api/office/mcp'",
                       "'/api/office/heartbeat'", "'/api/models'",
                       /* THE CHANGESET LANE (loffice-2026-08-28b). ONE read and three
                          POSTs, and the POSTs are the whole reason this slice exists:
                          consent for a spreadsheet change is now a button on this page,
                          and the WRITE happens bridge-side behind it. The page still
                          adds no writer of its own — see the writer fence in PART 5. */
                       "'/api/office/changeset?file='",
                       "'/api/office/changeset/'",
                       /* THE IN-RIBBON AI TAB (loffice-2026-08-29a). ONE read, and it
                          is READ-ONLY: Help → About asks whether ONLYOFFICE's own AI
                          plugin is vendored and whether it is currently usable, so the
                          AGPL attribution AND the honest "why the tab is missing"
                          sentence both come from the bridge instead of being retyped
                          here. This page does not configure the plugin and never talks
                          to it — bridge/panel/oo.html does that, inside the editor
                          frame, because the plugin lives inside the editor. */
                       "'/api/oo/ai/status'"].indexOf(u) >= 0), urls);
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
/* ⚠️⚠️ REWRITTEN AT loffice-2026-08-27e, AND THE REWRITE IS THE ARGUMENT. The interval
   used to belong to the AI PANEL: aiSetOpen armed it and clearInterval'd it, and its one
   job was the model pill. Slice S2 gave the page two duties that CANNOT be switched off
   by collapsing a panel — the open-file heartbeat (which decides whether an agent write
   is refused on a workbook with unsaved edits in it) and the mtime watch. So the timer
   is now the PAGE's, armed once at boot, and the model pill is what is gated on the
   panel being open — inside the tick. Still exactly ONE interval on this page. */
check('the page has exactly ONE recurring interval, and it is the page tick',
      (code.match(/setInterval\(/g) || []).length === 1
      && /setInterval\(pageTick, HB_TICK_MS\)/.test(grab('pageTickStart')));
check('…armed once at boot, not by the AI panel', /pageTickStart\(\)/.test(grab('boot'))
      && !/setInterval/.test(grab('aiSetOpen')));
check('the model pill still re-checks itself only while the panel is open',
      /if \(aiPaneOpen\(\)\) aiRefreshModel\(\);/.test(grab('pageTick')));
check('…and the tick does nothing at all on a hidden page, as the old one did',
      /if \(document\.hidden\) return;/.test(grab('pageTick')));

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
      /const message = aiPreamble\(current, aiSheetName\(\), stale\)/.test(send3));
/* ⚠️ AND THE THIRD ARGUMENT IS THE STALENESS SENTENCE (live finding L6). The prompt is
   `aiPreamble()` + the sheet dump, and the dump is `snap` — read from DISK and refreshed at
   exactly two moments (an open and a save). With unsaved edits in the editor the model was
   therefore shown the PRE-EDIT file under the sentence "The user is editing the workbook
   X", and nothing in the prompt said otherwise. On screen the entire warning was
   `aiPaint()` appending "· as last saved" to the context chip: eight characters of 10.5px
   dim text in an overflow:hidden span, which the transcript's own "context sent"
   disclosure never recorded either — so a saved log kept answers about data that was
   already stale when they were given, unmarked. */
check('…and it is TOLD when the sheet is behind what the user is looking at',
      /IMPORTANT: the sheet below is the file AS LAST SAVED/.test(
        aiPreamble('Sales.xlsx', 'Sheet1', true))
      && !/AS LAST SAVED/.test(aiPreamble('Sales.xlsx', 'Sheet1', false)));
check('…only when a workbook is actually open — there is nothing to be behind otherwise',
      !/AS LAST SAVED/.test(aiPreamble('', '', true)));
check('…and the staleness is exactly editorActive() && dirty: the snapshot IS the '
      + 'document in tier 1, so tier 1 can never be behind',
      /editorActive\(\) && dirty/.test(grab('aiStale')));
check('…and the LOG records it too, so a saved transcript says what the answer was based '
      + 'on', /asked against the LAST-SAVED sheet/.test(send3));
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
check('⌂ MOT Deck asks the SHELL to switch tabs, through the same postMessage contract '
      + 'the panel sidebar already uses',
      /messageHandlers[\s\S]{0,80}harness/.test(home) && /cmd: 'switchTab'/.test(home));
check('…sending the stable id AS WELL AS the title, so a renamed tab still resolves',
      /id: 'mc'/.test(home) && /title: 'MOT Deck'/.test(home));
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
check('say() renders an inline action as a real button…', /b\.textContent = a\.label/.test(sayFn));
/* ⚠️ ONE ACTION OR AN ARRAY OF THEM, as of loffice-2026-08-27e. The external-change
   banner (spec §3.3) states a dilemma with TWO answers, and the whole reason this
   argument exists is that a message stating a dilemma should be able to resolve it. The
   single-object form is unchanged — PART 6 EXECUTES both shapes against a stub DOM. */
check('…and several of them, in order, for the two-button banner',
      /Array\.isArray\(action\) \? action : \[action\]/.test(sayFn));
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
check('the build stamp was bumped for this change', stamp === 'loffice-2026-08-29b');
// ⚠️ THE TWO PLACES THAT MATTER, NAMED. This used to count occurrences and require
// exactly two, which only held while no comment in the page mentioned the build it was
// written for — and the one-editor slice writes its own stamp into the comments that
// explain it (that is a feature: a reader of the CSS can date the fork). What the check
// is FOR is that the no-script fallback banner cannot claim to be a build the meta tag
// does not, so it asserts those two by shape instead of by census.
check('…and the static fallback banner carries the SAME one, so "is the bridge serving '
      + 'what I shipped?" is answerable by eye with no console',
      html.includes('<meta name="harness-build" content="' + stamp + '">')
      && html.includes('Build <code>' + stamp + '</code>'));

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

// THE COERCION RULE AND THE CONTEXTUAL INFERENCE (loffice-2026-08-28d). parseInput
// delegates to coerceNumeric/stripTextMark, and actRunOps asks setContext whether a
// numeric-shaped string in that column is meant as a number.
eval(grabConsts('CO_MAX_LEN', 'CO_LEADING_ZERO'));
eval(grabConsts('NUM_HEADER_WORDS', 'INFER_W_OP_COL'));
eval(grab('stripTextMark')); eval(grab('coDp')); eval(grab('coPattern'));
eval(grab('coNum')); eval(grab('coerceNumeric')); eval(grab('textNumeric'));
eval(grab('cellFormat')); eval(grab('mergeFormat'));
eval(grab('headerLean')); eval(grab('shapeLean')); eval(grab('sheetColLean'));
eval(grab('setContext'));
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
// ⚠️ THE TIMER CHECK LOOKS INSIDE setTimeout'S ARGUMENTS AS OF loffice-2026-08-28d, not
// at the 80 characters after the word. The loose version began matching the moment
// `ooWaitReady` (whose whole body is a poll, and which is L2's fix) was defined just above
// `async function actApply` — a false positive on a DEFINITION, which is not a call site
// and cannot auto-apply anything. What must never exist is a TIMER THAT CALLS IT.
check('nothing on a timer, and no auto-apply anywhere near the reply path',
      !/setTimeout\(\s*[^)]*actApply\s*\(/.test(code)
      && !/actApply/.test(stripComments(send))
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
/* ⚠️⚠️ THESE TWO CHECKS PINNED A PROMISE THAT WAS FALSE IN THE LANE IT DESCRIBED (live
   finding L5), so what they pin changed with it. The intro said "You get a preview of every
   cell it would touch and it changes nothing until you press Apply — with an Undo after,
   and the file only written when you press ⌘S." MEASURED:
     · once a workbook is open the EDITOR owns the document, `ooActApply` sets
       card._undo = false and actLast = null, and there is NO Undo button on the card. The
       undo is the editor's own ⌘Z — which the card says and the intro did not.
     · a plan containing a `sort` takes the BRIDGE route, which SAVES THE FILE IMMEDIATELY
       (/api/office/save plus a daily .bak), so "only written when you press ⌘S" was exactly
       wrong for it.
   Worse, the promise was SOMETIMES kept — the create-from-nothing path does render an Undo
   chip — so the rule could not be learnt. One sentence per lane, matching what the card
   will actually offer. */
check('…and names the guarantees it can keep: a preview, an Apply, and the EDITOR\'s ⌘Z '
      + 'as the undo — not a card button that is not there',
      /preview of every cell/.test(html) && /<b>Apply<\/b>/.test(html)
      && /<b>⌘Z<\/b> inside the sheet takes it/.test(html)
      && !/with an <b>Undo<\/b> after/.test(html));
check('…and that ⌘S writes the file, WITH the one route that does not wait for it',
      /<b>⌘S<\/b> writes it to the file/.test(html)
      && /<b>sort<\/b>, which has to go through the file and is saved straight away/
         .test(html)
      && !/file only written when you press ⌘S/.test(html));
check('the block header no longer claims the panel is advisory only, because it is not',
      html.indexOf('AND IT IS ADVISORY ONLY') < 0
      && /NO LONGER ADVISORY ONLY/.test(html));

/* ══════════════════════════════════════════════════════════════════════════════
   PART 6 — SLICE S2: THE AGENT LANE, THE HEARTBEAT AND THE EXTERNAL-CHANGE BANNER
   (docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md §3.2–§4, build loffice-2026-08-27e)

   S1 shipped the other half and is not re-tested here: the bridge hosts an MCP server
   at /mcp/office, Hermes consumes it with `trust: untrusted`, the three read tools
   carry readOnlyHint so only the four write tools get a card, every agent write leaves
   a `<stem>.pre-agent.xlsx`, and a workbook registered OPEN-AND-DIRTY is refused.
   bridge/tests/test_office_mcp.py and test_office_lane.py own all of that.

   WHAT THIS PART PINS is the PAGE side, and it is four claims:
     1. the lane toggle greys with the REASON in its title, one reason per cause;
     2. the Agent lane reuses the harness's existing Hermes lane and its cards, and
        leaves the Quick lane byte-for-byte alone;
     3. the heartbeat is accurate the INSTANT the dirty flag flips, and rides no timer
        of its own;
     4. the banner's two sentences, exactly as the spec words them.
   And one negative, which is the one that matters most: THE AGENT LANE ADDS NO
   PAGE-SIDE WRITER.
   ═════════════════════════════════════════════════════════════════════════════ */

// The python half, read for the cross-language pins below. A page-side constant that
// drifted from office_ops.py would break the lane in the one way nobody would look at
// the page for.
const opsPy = fs.readFileSync(path.join(ROOT, 'bridge', 'office_ops.py'), 'utf8');
function pyNum(name) {
  const m = opsPy.match(new RegExp('^' + name + '\\s*=\\s*(\\d+(?:\\.\\d+)?)', 'm'));
  if (!m) throw new Error('constant ' + name + ' not found in office_ops.py');
  return parseFloat(m[1]);
}
// Constants the extracted functions close over are READ OUT OF THE PAGE, never written
// down here — and the one that crosses the language boundary is pinned against
// office_ops.py in §4 below, which is the pin that actually matters.
const PRE_AGENT_SUFFIX = (code.match(/PRE_AGENT_SUFFIX = '([^']+)'/) || [])[1];

// ── 1. THE LANE TOGGLE ──────────────────────────────────────────────────────
// GREY-NOT-HIDE. The chip is always on screen; when it cannot be used it is disabled
// with the reason in its own title. There is deliberately no third state.
check('the AI panel has both lane chips, as REAL MARKUP',
      /id="lane-quick"/.test(html) && /id="lane-agent"/.test(html)
      && />Quick</.test(html) && />Agent</.test(html));
check('…Quick is the default and is marked `on` in the MARKUP, not by JS — a page whose '
      + 'boot failed must not look like it is in the Agent lane',
      /id="lane-quick" class="chip on"/.test(html));
check('…and the Agent chip ships DISABLED with a reason already in its title, so the '
      + 'pre-probe state is honest too',
      /id="lane-agent"[\s\S]{0,120}disabled/.test(html)
      && /id="lane-agent"[\s\S]{0,300}title="[^"]+"/.test(html));
check('the chips reuse the existing .chip grammar (the `sheet` chip\'s), so there is no '
      + 'new control vocabulary on this page',
      /id="lane-quick" class="chip/.test(html) && /id="lane-agent" class="chip/.test(html));
check('…and a disabled chip is greyed by the stylesheet rule that already covers every '
      + 'button in this pane, which is why this slice added no CSS for it',
      /button:disabled\{opacity:\.45;cursor:default\}/.test(css));
eq('the ONLY CSS this slice added is the header wrap the two extra chips need',
   (css.match(/#ai-hd\{[^}]*\}/) || [''])[0].indexOf('flex-wrap:wrap') >= 0, true);

// THE GATE, EXECUTED — one case per grey reason, in the order a person would fix them.
eval(grab('agentGate'));
{
  const shut = [
    ['hermes is down', {}, /Hermes is not running/],
    ['the MCP server is not registered', { hermes: true }, /not registered with Hermes/],
    ['…or is registered but out of sync',
     { hermes: true, mcpRegistered: true }, /out of sync/],
    ['…or the model explicitly cannot tool-call',
     { hermes: true, mcpRegistered: true, mcpInSync: true, tools: false, model: 'M-4B' },
     /NO tool-calling support/],
  ];
  shut.forEach(([label, env, re]) => {
    const st = agentGate(env);
    check('the Agent lane is refused when ' + label, st.ok === false);
    check('…with that reason in the title: ' + label, re.test(st.why), st.why);
    check('…and no warning, because a refusal is not a warning: ' + label, st.warn === '');
  });
  eq('every refusal reason is a whole sentence, not a word',
     shut.every(([, env]) => agentGate(env).why.length > 40), true);
  check('the refusal for a tool-less model NAMES the model, so "which one?" is not the '
        + 'next question',
        /M-4B/.test(agentGate({ hermes: true, mcpRegistered: true, mcpInSync: true,
                                tools: false, model: 'M-4B' }).why));
  check('…and every refusal names WHERE to fix it',
        shut.every(([, env]) => /MOT Deck|Models/.test(agentGate(env).why)));

  const open = { hermes: true, mcpRegistered: true, mcpInSync: true, tools: true,
                 model: 'M-4B' };
  const st = agentGate(open);
  check('all three gates open on a tool-calling model', st.ok === true && st.warn === '');
  check('…and the title then says what the lane IS for', /real Office tools/.test(st.why));

  /* ⚠️⚠️ THE THIRD VALUE IS THE WHOLE JUDGEMENT CALL OF THIS FUNCTION, AND IT IS PINNED
     HERE RATHER THAN ARGUED IN A COMMENT ALONE. The bridge reports tool-calling as
     true / false / NULL, where null means "this model's chat template could not be
     read" (bridge/modeltools.py; surfaced as installed[].tools on GET /api/models, the
     same field the green `tools` pill and the panel's own modelHasSTools read). An
     explicit FALSE is a hard gate. A NULL is NOT one: the absent-not-greyed rule says
     an unknown must never be drawn as a "no", and — measured on this machine, sixteen
     installed models, `tools` null on all sixteen — gating on null would refuse the
     lane on EVERY model Debi owns. So null opens the lane with the requirement stated
     as a warning, which the spec's "the reason in its title" still satisfies. */
  const unk = agentGate(Object.assign({}, open, { tools: null }));
  check('an UNKNOWN tool-calling verdict opens the lane rather than refusing it',
        unk.ok === true);
  check('…but says so, by name, as a warning', unk.warn.length > 40 && /M-4B/.test(unk.warn));
  check('…and the warning is carried in the TITLE too, because the title is the only '
        + 'place a person reads before clicking', unk.why.indexOf(unk.warn) > 0);
  check('…and it points at the same green pill the Models page uses',
        /`tools` pill/.test(unk.warn));
  [undefined, null, {}, 0, 'x'].forEach((v, i) => {
    let threw = null, r = null;
    try { r = agentGate(v); } catch (e) { threw = e; }
    check('agentGate survives junk input and fails CLOSED (case ' + i + ')',
          !threw && r && r.ok === false);
  });
}

// The paint side: the gate's verdict is what disables the chip and writes the title,
// and a lane that stopped being available does not sit there pretending.
{
  const lp = grab('lanePaint');
  check('lanePaint disables the Agent chip from the gate and puts the gate\'s reason in '
        + 'its title', /a\.disabled = !st\.ok/.test(lp) && /a\.title = st\.why/.test(lp));
  check('…and falls back to Quick if the gate shuts while you are in the Agent lane, '
        + 'because a dead composer is worse than a lane change',
        /aiLane === LANE_AGENT && !st\.ok/.test(lp) && /laneApply\(LANE_QUICK/.test(lp));
  /* ⚠️⚠️ AND THE FALLBACK DOES NOT FORGET WHAT WAS ASKED FOR — A BUG FOUND ON THE REAL
     PAGE, NOT IN A TEST. The gate is probed asynchronously, so for the first few hundred
     ms of EVERY page load Hermes has not been checked yet and the gate reads shut. When
     the fallback also PERSISTED itself, a remembered Agent lane was destroyed on every
     single reload. `laneWant` is the choice (persisted, only ever set by laneSet);
     `aiLane` is what is in effect (never persisted, set by laneApply). */
  check('…and the fallback writes NOTHING to localStorage, which is what makes a '
        + 'remembered Agent lane survive a reload past the async probe',
        !/localStorage/.test(grab('laneApply')) && /localStorage\.setItem\(LS_LANE/.test(grab('laneSet')));
  check('…and the wanted lane is re-adopted the moment the gate opens',
        /laneWant === LANE_AGENT && st\.ok/.test(lp) && /laneApply\(LANE_AGENT/.test(lp));
  check('…and the boot restores the WANT, not the effect — the gate still has the last '
        + 'word', /getItem\(LS_LANE\) === LANE_AGENT\) laneWant = LANE_AGENT/.test(grab('boot')));
  check('laneSet refuses the Agent lane on a shut gate itself — the disabled attribute '
        + 'is belt, this is braces',
        /want === LANE_AGENT && !agentGate\(agentEnv\)\.ok/.test(grab('laneSet')));
  check('…and remembers the choice, so the lane survives a reload',
        /localStorage\.setItem\(LS_LANE/.test(grab('laneSet'))
        && /getItem\(LS_LANE\) === LANE_AGENT/.test(grab('boot')));
  check('…and a REFUSED click is not remembered either — laneWant is only written after '
        + 'the gate has said yes',
        /if \(want === LANE_AGENT && !agentGate\(agentEnv\)\.ok\) return false;[\s\S]{0,40}laneWant = want;/
          .test(grab('laneSet')));
  check('…which the boot only ADOPTS, never trusts: the gate still has the last word',
        /lanePaint\(\)/.test(grab('aiPaint')));
  check('the chips are repainted from aiPaint, the same funnel the model pill and the '
        + 'context note use', /lanePaint\(\);/.test(grab('aiPaint')));
  check('clicking the greyed chip says why, rather than doing nothing',
        /aiStatus\(agentGate\(agentEnv\)\.why, true\)/.test(code));
}

// The probe: three gates, and only one of them costs a request of its own.
{
  const pr = grab('agentProbe');
  check('the Hermes gate is read off the /api/status response aiRefreshModel ALREADY '
        + 'fetches, so it costs nothing',
        /components\.hermes/.test(grab('aiRefreshModel'))
        && /agentEnv\.hermes = !!\(h && h\.running\)/.test(grab('aiRefreshModel')));
  check('…and a bridge that did not answer closes the gate rather than leaving it open',
        /agentEnv\.hermes = false/.test(grab('aiRefreshModel')));
  check('the MCP gate reads GET /api/office/mcp — the S1 surface, not a new one',
        /fetch\('\/api\/office\/mcp'/.test(pr));
  check('…and reads BOTH registered and in_sync, because an out-of-sync entry points at '
        + 'a server this bridge does not serve',
        /j\.registered/.test(pr) && /j\.in_sync/.test(pr));
  check('the tools verdict is CACHED BY MODEL, because /api/models is 75 KB and can '
        + 're-seed the registry — it must never ride a fast poll',
        /model !== agentToolsPin/.test(pr) && /agentToolsPin = model/.test(pr));
  check('…and it is the panel\'s own predicate: true ONLY on an explicit yes',
        /live\.tools === true/.test(pr) && /indexOf\('tools'\) >= 0/.test(pr)
        && /live\.tools === false \? false : null/.test(pr));
  check('…and the panel it mirrors still derives it the same way, so the two agree '
        + 'about what a green pill means',
        /if \(m\.tools === true\) return true;/.test(panel)
        && /\(m\.capabilities \|\| \[\]\)\.indexOf\('tools'\) >= 0/.test(panel));
}

// ── 2. THE AGENT LANE ON THE WIRE ───────────────────────────────────────────
// It invents nothing: the harness's existing Hermes lane, the same frames, the same
// approve call. The negative that no /api/office/chat exists is asserted in PART 2 and
// covers this lane too.
const asend = grab('agentSend');
check('the fork between the lanes is ONE line, and it is the FIRST line of aiSend — so '
      + 'the Quick lane below it is the lane that shipped',
      /^\s*if \(aiLane === LANE_AGENT\) return agentSend\(\);$/m
        .test(stripComments(send).split('\n').slice(0, 6).join('\n')));
check('the Quick lane still posts to /api/chat/direct with an EMPTY session',
      /fetch\('\/api\/chat\/direct'/.test(send) && /session: ''/.test(send));
check('…and the Quick lane never touches the Hermes lane',
      !/api\/hermes/.test(stripComments(send)));
check('the Agent lane posts to the harness\'s EXISTING Hermes lane',
      /fetch\('\/api\/hermes\/chat'/.test(asend));
check('…with the SAME body the main panel sends, session_id / message / stored_sid',
      /session_id: agentSid \|\| ''/.test(asend) && /message: message/.test(asend)
      && /stored_sid: agentStored \|\| ''/.test(asend));
check('…and the main panel really does send that body, so this is a REUSE and not a '
      + 'second protocol', /session_id: chatPane\.hermesSid \|\| ''/.test(panel)
      && /stored_sid: chatPane\.hermesStoredSid \|\| ''/.test(panel));
check('…reading the same `data: ` frames and the same [DONE]',
      /startsWith\('data: '\)/.test(asend) && /\[DONE\]/.test(asend));
check('the session is created LAZILY — no session id on the first message, and the '
      + 'bridge mints one; the page never calls session/new',
      /agentSid \|\| ''/.test(asend) && code.indexOf("'/api/hermes/session/new'") < 0);
// ⚠️ rewritten 2026-08-27 (was "preamble rides EVERY agent message"): Debi's live
// transcript showed the model re-reading the full grammar N times by turn N — the
// Hermes session keeps its history, so the full grounding now rides the FIRST message
// only, and later turns send agentBrief (the one thing that can change between turns:
// which workbook is open).
check('full grounding (preamble + tool note WITH the open file named) rides the FIRST '
      + 'message of a session',
      /aiPreamble\(current, aiSheetName\(\), agStale\) \+ agentToolNote\(current\)/
        .test(asend));
// ⚠️ AND THE STALENESS SENTENCE RIDES BOTH LANES (live finding L6). The Agent lane's tools
// read the FILE, so a dirty editor means every read they do is behind what she is looking
// at — which is also exactly why office_ops refuses to write it. Told on the first turn
// through aiPreamble, and on later turns beside agentBrief.
check('…and a dirty editor is stated to the agent on EVERY turn, not only the first',
      /UNSAVED edits in the editor, so the file the tools/.test(asend)
      && /a write will be refused/.test(asend));
check('…and later turns send agentBrief instead, gated on agentSid',
      /agentSid\s*[\s\S]{0,20}\?\s*agentBrief\(current, aiSheetName\(\)\)/.test(asend));
check('…and the sheet chip still governs the sheet exactly as it does in Quick',
      /aiCtxOn \? aiContext\(\) : null/.test(asend));
check('the reply is rendered by the Quick lane\'s OWN renderer, so a formula is still a '
      + 'copy card and an action block is still a preview-and-Apply card — one grammar, '
      + 'two engines', /aiRenderBody\(turn\.body\.parentNode, out\)/.test(asend));
check('a write tool that ran means the FILE moved, so the turn ends by asking',
      /extCheck\(\);/.test(asend));

// The session is the ONE dedicated `loffice` session the spec asks for.
eq('the dedicated session is named exactly `loffice`',
   (code.match(/AGENT_SESSION_NAME = '([^']+)'/) || [])[1], 'loffice');
check('…renamed through the EXISTING rename route, on the DURABLE id (the gateway has '
      + 'no rename for a live session it does not own)',
      /'\/api\/hermes\/session\/' \+ encodeURIComponent\(agentStored\)/.test(grab('agentName')));
check('…once, and never load-bearing: a rename that fails costs a beacon and remains '
      + 'retryable rather than being logged as success',
      /if \(agentNamed \|\| agentNaming \|\| !agentStored\) return;/.test(grab('agentName'))
      && /if \(!r\.ok \|\| j\.ok !== true\)/.test(grab('agentName'))
      && /agentNamed = false/.test(grab('agentName'))
      && /agent-name-fail/.test(code));
check('a real Hermes title conflict preserves the older session and retries with this '
      + 'exact durable id rather than guessing, deleting, or overwriting',
      /result\.r\.status === 409/.test(grab('agentName'))
      && /AGENT_SESSION_NAME \+ ' · ' \+ agentStored/.test(grab('agentName'))
      && /result = await requestName\(chosen\)/.test(grab('agentName')));
check('…only after the durable turn work completes, so first-turn auto-title cannot '
      + 'win behind it',
      asend.indexOf('await csAfterTurn(turn);') < asend.indexOf('await agentName();'));
check('the session id is persisted, so the next question — and the next page load — '
      + 'continue the same conversation',
      /localStorage\.setItem\(LS_AGENT_SID/.test(code)
      && /getItem\(LS_AGENT_SID\)/.test(grab('boot')));
const restore = grab('agentRestoreHistory');
check('U30: boot restores the durable Agent transcript through the read-only history '
      + 'route before landing',
      /agentRestoreHistory\(\)/.test(grab('boot'))
      && /\/api\/hermes\/session\//.test(restore) && /\/history\?view=loffice/.test(restore));
check('U30: new stored turns carry an explicit projection marker rather than making '
      + 'reload guess where internal spreadsheet grounding ends',
      /AGENT_USER_MARKER = '\\n\\n--- M\.O\.T LOffice user question ---\\n\\n'/.test(code)
      && /\+ AGENT_USER_MARKER \+ q/.test(asend));
check('U30: repaint never resumes or creates a live Hermes gateway session',
      !/session\/resume|session\/new/.test(restore));
check('U30: restored user and assistant rows use the existing transcript renderer',
      /aiAdd\(row\.role/.test(restore) && /aiRenderBody\(/.test(restore));
check('U30: the 500-row boundary is visible and explicitly uncertain',
      /limit_reached/.test(restore) && /older messages may exist/.test(restore));
check('U30: sends are blocked while history is loading, preventing reordered rows',
      /agentHistoryLoading/.test(grab('aiBusyBlock'))
      && /agentHistoryLoading/.test(grab('aiPaint')));
check('…and `clear` forgets it, because on this lane the history is not only on screen '
      + '— Hermes is holding it',
      /agentSid = ''; agentStored = ''; agentNamed = false;/.test(code)
      && /removeItem\(LS_AGENT_SID\)/.test(code));
check('a restored durable id never masquerades as evidence that its title is right',
      /agentStored = localStorage\.getItem\(LS_AGENT_STORED\) \|\| '';[\s\S]*agentNamed = false;/.test(grab('boot')));

// THE FRAME VOCABULARY, EXECUTED against the exact frames bridge/app.py's
// hermes_event_to_frames emits. A frame this page silently dropped would be a turn that
// looked dead.
{
  let named = 0, cards = [], status = '', beacons = [];
  let agentSid = '', agentStored = '', agentNamed = false; // the fn assigns to these
  const store = {};
  const localStorage = { setItem: (k, v) => { store[k] = v; }, getItem: k => store[k] };
  const bx = (s, d) => beacons.push(s + ':' + d);
  const aiStatus = t => { status = t; };
  const agentName = () => { named++; };
  const agentCard = (host, req, s) => { cards.push({ req: req, sid: s }); };
  const LS_AGENT_SID = 'k1', LS_AGENT_STORED = 'k2';
  const document = { createElement: () => ({ style: {}, appendChild() {} }) };
  eval(grab('agentFrame'));
  const turn = { wrap: { appendChild() {} } };
  const held = { sid: 'S0' };
  const steps = [];
  eq('a prose delta is prose', agentFrame({ delta: 'hi' }, turn, held, steps), { delta: 'hi' });
  eq('a thinking delta is kept apart from the answer',
     agentFrame({ delta: 'mm', thinking: true }, turn, held, steps), { thinking: 'mm' });
  eq('an empty delta is nothing at all', agentFrame({ delta: '' }, turn, held, steps), {});
  agentFrame({ type: 'hermes_session', id: 'S9', stored_id: 'D9' }, turn, held, steps);
  eq('the hermes_session frame is where the sid comes from — announced BEFORE any token',
     [held.sid, store.k1, store.k2], ['S9', 'S9', 'D9']);
  eq('…and it does NOT rename before the first turn is durable', named, 0);
  agentNamed = true;
  agentFrame({ type: 'hermes_session', id: 'S10', stored_id: 'D10' }, turn, held, steps);
  eq('a replacement durable id invalidates naming success from the previous row',
     [agentStored, agentNamed], ['D10', false]);
  agentFrame({ type: 'approval', request: { command: 'c', choices: ['once', 'deny'] } },
             turn, held, steps);
  eq('an approval frame draws a card, in the session THAT TURN owns',
     [cards.length, cards[0].sid], [1, 'S10']);
  agentFrame({ type: 'tool_start', tool: 'office_read' }, turn, held, steps);
  eq('a tool_start is recorded as a step and said on the status line',
     [steps.slice(), /office_read/.test(status)], [['office_read'], true]);
  agentFrame({ type: 'tool_output', tool: 'office_read', summary: '12 cells' },
             turn, held, steps);
  eq('…and its summary joins the step it belongs to', steps, ['office_read — 12 cells']);
  eq('a proxy_error ends the turn with its reason, rather than hanging on it',
     agentFrame({ type: 'proxy_error', error: 'boom' }, turn, held, steps),
     { error: 'boom' });
  ['hermes_ping', 'file_card', 'guard_flag', 'ask_expire', 'session.info', ''].forEach(t => {
    eq('the ' + (t || 'typeless') + ' frame is inspect-only noise and is dropped',
       agentFrame({ type: t }, turn, held, steps), {});
  });
  eq('a hermes_status is shown as status, not as an answer',
     agentFrame({ type: 'hermes_status', text: 'working' }, turn, held, steps), {});
  eq('…on the status line', status, 'working');
  [null, undefined, {}, 'x', 0].forEach((v, i) => {
    let threw = null;
    try { agentFrame(v, turn, held, steps); } catch (e) { threw = e; }
    check('agentFrame survives junk input (case ' + i + ')', !threw);
  });
  // The ONE frame this lane deliberately does not render as a control, said out loud.
  const askOut = [];
  const turn2 = { wrap: { appendChild: n => askOut.push(n) } };
  agentFrame({ type: 'ask', request: { question: 'which sheet?' } }, turn2, held, steps);
  eq('a clarify/ask card is NOT faked: the question is printed and the user is told '
     + 'where it can actually be answered', askOut.length, 1);
  check('…and the page never posts an answer it has no picker for',
        code.indexOf("'/api/hermes/answer'") < 0);
}

// The frames the page handles are the frames the BRIDGE emits — pinned across the file
// boundary so a mapper change cannot silently strip this lane.
{
  const app = require('./_appsrc.js').appSource();
  const mapper = app.slice(app.indexOf('def hermes_event_to_frames'),
                           app.indexOf('class _HermesWS'));
  check('the bridge mapper really emits every type this lane branches on',
        ['tool_start', 'tool_output', 'approval', 'ask', 'ask_expire', 'proxy_error',
         'hermes_session', 'status'].every(t => mapper.indexOf('"' + t + '"') > 0
                                              || app.indexOf('"type": "' + t + '"') > 0
                                              || app.indexOf('"type":"' + t + '"') > 0));
  check('…and the approval frame really carries {command, description, choices}',
        /"command": p\.get\("command"\)/.test(mapper)
        && /"choices": \[str\(c\) for c in ch\]/.test(mapper));
}

// ── THE TOOL NOTE — THE GROUNDING v2 REWROTE ────────────────────────────────
/* ⚠️ THIS BLOCK IS THE ONE THAT CHANGED MOST AT loffice-2026-08-28b, AND WHAT IT PINS IS
   THE INCIDENT'S ROOT CAUSE ON THE MODEL'S SIDE. Debi's 2026-08-27 transcript shows the
   model turning ONE instruction ("add a purchases row of 200 and update the total") into
   office_write_cells → office_insert_delete → office_write_cells: three writes, three
   approval cards, one of them never answered, one tool error, and "Done. … new planned
   total 1,635" over a sheet that still said 1,435. The tools no longer WRITE, so the
   grain is enforced rather than requested — but the note still has to teach the shape,
   and it has to say the two sentences that make a false "Done" a contradiction of its
   own instructions: you cannot apply, and you do not claim unless a system line says so.
   docs/FABLE-AGENT-CHANGESET-SPEC.md §4. */
eval(grab('agentToolNote'));
eval(grab('agentBrief'));
{
  const note = agentToolNote('Untitled (4).xlsx');
  check('with a workbook open, the note names it EXACTLY as the name argument',
        note.indexOf('THE OPEN WORKBOOK IS NAMED EXACTLY "Untitled (4).xlsx"') >= 0);
  check('with NO workbook open, the note points at office_list and the create op',
        /No workbook is open right now/.test(agentToolNote(''))
        && /create_workbook/.test(agentToolNote('')));
  check('agentBrief names the open workbook exactly, and covers the no-file case',
        agentBrief('B.xlsx', 'S1').indexOf('Open workbook: "B.xlsx", sheet "S1"') === 0
        && /tools take this exact name/.test(agentBrief('B.xlsx', 'S1'))
        && /No workbook is open/.test(agentBrief('', '')));
  ['office_list', 'office_read', 'office_sheet_stats', 'office_stage_changes']
    .forEach(t => check('the agent is told it has ' + t, note.indexOf(t) >= 0));
  check('…and that the tools are the PREFERRED route over the taught block, because '
        + 'aiPreamble teaches that block on this lane too',
        /PREFER THE TOOLS/.test(note) && /instead of emitting a loffice block/.test(note));
  check('…that a tool takes a NAME and never a path, which is the containment rule the '
        + 'MCP server enforces by construction', /NAME, never a path/.test(note));

  // THE FOUR SENTENCES THE SPEC'S §4 ASKS FOR, each pinned on its own so a rewrite
  // cannot quietly drop one.
  check('1. READ FIRST, then compute — the multi-step shape this lane exists for',
        /READ the workbook first/.test(note) && /work out every cell/.test(note));
  check('2. STAGE ONCE, with the COMPLETE op list for the whole request — the direct '
        + 'answer to three write calls for one intention',
        /ONCE with the COMPLETE list of operations/.test(note)
        && /for the whole request/.test(note));
  check('…and that a second staging call REPLACES the first, so "send it in pieces" is '
        + 'named as the loss it is',
        /REPLACES the first proposal/.test(note) && /LOSES the earlier pieces/.test(note));
  check('3. …then STOP, and do not ask for permission in prose',
        /and STOP\./.test(note) && /do not ask "OK\?"/.test(note));
  /* ⚠️⚠️ THE TWO SENTENCES THAT ANSWER THE FALSE "DONE" DIRECTLY. Everything else in
     this slice makes a lie visible; these make it a violation of the model's own
     instructions, which is the cheapest place to stop it. */
  check('4. …and it says PLAINLY that the model cannot apply anything',
        /YOU CANNOT APPLY CHANGES/.test(note) && /There is no apply tool/.test(note)
        && /Only Debi can press Apply/.test(note));
  check('…AND THAT IT MUST NEVER CLAIM A CHANGE WAS MADE WITHOUT A SYSTEM LINE — named '
        + 'in the model\'s own vocabulary (a row added, a total updated), because that '
        + 'is the exact sentence the incident produced',
        /NEVER claim a change was made/.test(note)
        && /a row\s+was added or a total was updated/.test(note.replace(/\n/g, ' '))
        && /unless a system line in this conversation\s+confirms/.test(note));
  check('…and that a refusal is to be repeated, not smoothed over',
        /says it was refused, say that plainly/.test(note));
  check('staging is described as writing NOTHING, on the model\'s side of the wire too',
        /Staging writes NOTHING/.test(note));
  check('the tool names are EXACTLY the four the MCP server serves — the retired write '
        + 'tools are not taught, and a fifth tool could not be taught unnoticed',
        (() => {
          const mcp = fs.readFileSync(path.join(ROOT, 'bridge', 'office_mcp.py'), 'utf8');
          const served = Array.from(new Set(mcp.match(/"name": "(office_[a-z_]+)"/g) || [])
            .values()).map(s => s.split('"')[3]).sort();
          const told = Array.from(new Set(note.match(/office_[a-z_]+/g) || [])).sort();
          return served.length === 4 && JSON.stringify(served) === JSON.stringify(told);
        })());
  check('…and the retired write tools are named NOWHERE in the page: a grounding that '
        + 'still offered office_write_cells would teach a tool that does not exist',
        !/office_write_cells|office_insert_delete|office_create\b/.test(code)
        && !/office_sort/.test(code));
}

// ── THE APPROVAL CARD ───────────────────────────────────────────────────────
// ONE VISUAL GRAMMAR, TWO ENGINES (spec §4).
eval(grab('agentToolOf'));
{
  /* ⚠️ THE SENTENCE PARSED HERE IS HERMES'S OWN, COPIED FROM THE PIN — the trust gate
     builds it at vendor/hermes/tools/mcp_tool.py:4035-4046 and the bridge forwards it
     verbatim as the card's `command`. Pinning the real string is what makes the parse
     a contract rather than a hope. */
  const real = "MCP tool 'office_write_cells' on UNTRUSTED server 'loffice' wants to "
             + "run. This tool is write-capable (no readOnlyHint=true annotation) and "
             + "may modify external state.";
  eq('the tool name is read out of Hermes\'s own approval sentence',
     agentToolOf(real), 'office_write_cells');
  const hermesSrc = fs.readFileSync(
    path.join(ROOT, 'vendor', 'hermes', 'tools', 'mcp_tool.py'), 'utf8');
  check('…and that sentence is still the one the pin builds — if upstream rewords it, '
        + 'this test fails instead of the card going vague in silence',
        /f"MCP tool '\{tool_name\}' on UNTRUSTED server "/.test(hermesSrc));
  eq('an unparseable command yields no tool name rather than a guess',
     [agentToolOf(''), agentToolOf('something else'), agentToolOf(null)], ['', '', '']);
}
{
  // agentCardText reads `current`; the wording is what is under test.
  let current = 'Budget.xlsx';
  eval(grab('preAgentName')); eval(grab('agentToolOf'));
  const AGENT_TOOLS = eval('(' + (code.match(/const AGENT_TOOLS = (\{[\s\S]*?\});/) || [])[1] + ')');
  eval(grab('agentCardText'));
  const t = agentCardText({ command: "MCP tool 'shell' on UNTRUSTED server 'x' wants to run." });
  check('the card names the tool it was told about', /shell/.test(t));
  check('…and that nothing happens until it is answered',
        /Nothing happens until you answer this/.test(t));
  /* ⚠️⚠️ THE CARD'S JOB CHANGED COMPLETELY AT loffice-2026-08-28b AND SO DID THESE
     ASSERTIONS. Every tool on the loffice server is read-only now, so Hermes has nothing
     here to gate: an Office tool CANNOT produce this card any more. The old checks
     (which tool it is, the pre-agent copy, the dirty refusal) described a surface that
     no longer exists, and the honest replacement is the NEGATIVE — the card says out
     loud that it is not a spreadsheet change, because a card that let Debi think she was
     approving a cell write would be worse than the two cards the incident produced. */
  check('…and SAYS PLAINLY that this is not a spreadsheet change, because no Office '
        + 'tool can ask here any more',
        /This is NOT a spreadsheet change/.test(t) && /no Office tool can write/.test(t));
  check('…and points at where a spreadsheet change DOES ask — a card with every cell '
        + 'listed and an Apply button',
        /every cell listed and an Apply button/.test(t));
  check('…and states the limit that has not moved: this panel cannot show the tool\'s '
        + 'arguments, because Hermes\'s gate does not put them on the wire',
        /cannot\s+show its arguments/.test(t.replace(/\n/g, ' '))
        && /approve\s+it only if you know what asked/.test(t.replace(/\n/g, ' ')));
  eq('AGENT_TOOLS IS EMPTY, and the emptiness is the assertion: a line for '
     + 'office_write_cells would be describing a card that never appears',
     Object.keys(AGENT_TOOLS), []);
  check('…and the bridge agrees that NOTHING on the loffice server is gated any more, '
        + 'because nothing on it can write',
        (() => {
          const mcp = fs.readFileSync(path.join(ROOT, 'bridge', 'office_mcp.py'), 'utf8');
          return /def write_tool_names/.test(mcp)
                 && mcp.indexOf('"office_write_cells"') < 0
                 // Every row in the catalog is read-only, so write_tool_names() is []
                 && (mcp.match(/"read_only": False/g) || []).length === 0
                 && (mcp.match(/"read_only": True/g) || []).length === 4;
        })());
  const t2 = agentCardText({});
  check('an approval whose command could not be parsed still says what class of thing '
        + 'is about to happen', /write-capable tool/.test(t2));
}
{
  /* ZERO NEW CSS, computed the same way PART 5 computes it for the Quick lane's card:
     every class the agent card uses must already have a rule. A class the card invented
     would have to be styled to be worth having, and there is no rule for one. */
  const cardSrc = ['agentCard', 'agentStamp', 'agentExpire'].map(grab).join('\n');
  const cls = Array.from(new Set((cardSrc.match(/className = '([\w-]+)'/g) || [])
    .map(s => s.split("'")[1])));
  check('the agent card is built from several existing classes', cls.length >= 3);
  check('…and EVERY one of them is already in the stylesheet',
        cls.every(c => rules.some(r => new RegExp('\\.' + c + '(?![\\w-])').test(r.sel))), cls);
  check('…and they are the SAME pieces the Quick lane\'s preview card is built from, '
        + 'which is what "one visual grammar" means',
        ['aicode', 'bar', 'lang'].every(c => cls.indexOf(c) >= 0));
  check('…and the shared card helpers are REUSED, not copied',
        /actDet\(/.test(grab('agentCard')) && /actChip\(/.test(grab('agentCard'))
        && /actNote\(/.test(grab('agentApprove')));
}
{
  const ap = grab('agentApprove');
  check('approving posts the EXISTING route with {session_id, choice}',
        /fetch\('\/api\/hermes\/approve'/.test(ap)
        && /session_id: card\._sid, choice: choice/.test(ap));
  check('…addressed to the session THE CARD was born in, captured at render time — '
        + 'approvals carry no request id on the wire, so the sid is the whole address',
        /card\._sid = String\(sid \|\| ''\)/.test(grab('agentCard'))
        && /const held = \{ sid: agentSid \}/.test(asend));
  check('…and the main panel captures it the same way, for the same reason',
        /card\._sid = String\(sid \|\| ''\)/.test(panel));
  check('no double-fire: every button dies the instant one is clicked',
        /btns\.forEach\(b => \{ b\.disabled = true; \}\)/.test(ap));
  check('a card that resolved NOTHING gateway-side is stamped honestly, never as '
        + '"approved"', /if \(!j\.resolved\)/.test(ap) && /already expired/.test(ap));
  check('…and a failed approve re-arms the buttons, because the approval is still '
        + 'pending upstream', /btns\.forEach\(b => \{ b\.disabled = false; \}\)/.test(ap));
  check('the choices come from the frame, defaulting to once/deny — never OFFERING a '
        + 'persistence scope upstream did not declare',
        /\['once', 'deny'\]/.test(grab('agentCard')));
  check('a card still open when the turn ends stops pretending it is answerable',
        /agentExpire\(turn\.wrap\)/.test(asend)
        && /no longer answerable/.test(grab('agentExpire')));
}

// ── 3. THE HEARTBEAT ────────────────────────────────────────────────────────
eval(grab('hbPlan'));
{
  eq('nothing open, nothing sent', hbPlan('', false, null, false), []);
  eq('nothing open on the keepalive beat either', hbPlan('', false, null, true), []);
  eq('opening a workbook registers it', hbPlan('A.xlsx', false, null, false),
     [{ name: 'A.xlsx', dirty: false }]);
  eq('…and nothing changing sends nothing at all — this is what makes it safe to hang '
     + 'the beat off paint(), which fires on every keystroke',
     hbPlan('A.xlsx', false, { name: 'A.xlsx', dirty: false }, false), []);
  eq('THE DIRTY FLIP IS IMMEDIATE, which is the whole point: the S1 refusal is only '
     + 'accurate if the bridge knows about the unsaved edit now, not in five seconds',
     hbPlan('A.xlsx', true, { name: 'A.xlsx', dirty: false }, false),
     [{ name: 'A.xlsx', dirty: true }]);
  eq('…and so is a SAVE, in the other direction — a stale dirty flag would refuse a '
     + 'write the user is perfectly happy with',
     hbPlan('A.xlsx', false, { name: 'A.xlsx', dirty: true }, false),
     [{ name: 'A.xlsx', dirty: false }]);
  eq('switching workbooks CLOSES the old one explicitly, so the bridge forgets it now '
     + 'rather than in fifteen seconds — and registers the new one in the same beat',
     hbPlan('B.xlsx', false, { name: 'A.xlsx', dirty: true }, false),
     [{ name: 'A.xlsx', close: true }, { name: 'B.xlsx', dirty: false }]);
  eq('closing the last workbook closes the registration and registers nothing',
     hbPlan('', false, { name: 'A.xlsx', dirty: true }, false),
     [{ name: 'A.xlsx', close: true }]);
  eq('the keepalive beat re-sends the SAME state, so the TTL never expires under a page '
     + 'that is still sitting there',
     hbPlan('A.xlsx', true, { name: 'A.xlsx', dirty: true }, true),
     [{ name: 'A.xlsx', dirty: true }]);
  eq('the dirty flag is always a real boolean on the wire',
     hbPlan('A.xlsx', 'yes', null, false), [{ name: 'A.xlsx', dirty: true }]);
  [null, undefined, 0].forEach((v, i) => {
    let threw = null;
    try { hbPlan(v, v, v, v); } catch (e) { threw = e; }
    check('hbPlan survives junk input (case ' + i + ')', !threw);
  });
}
check('the beat posts the S1 route, and only that route',
      /fetch\('\/api\/office\/heartbeat'/.test(grab('hbPost')));
check('…with the {name, dirty} the bridge documents, and {name, close} to forget one',
      /close: true/.test(grab('hbPlan')));
check('…and a heartbeat that fails costs a beacon, never the page: it is ADVISORY',
      /bx\('hb-fail'/.test(grab('hbPost')));
check('THE DIRTY FLIP RIDES paint(), the one funnel every change of `dirty` already '
      + 'goes through — so there is no new hook to forget at a twelfth call site',
      /hbSync\(\);/.test(grab('paint')));
/* ⚠️ AND THIS IS THE ASSERTION THAT MAKES "paint() IS THE FUNNEL" A FACT RATHER THAN AN
   INTENTION: every single place that assigns `dirty` either paints within a few lines,
   or lives in one of THREE functions whose callers paint in their own `finally`. The
   three are named here, not hand-waved, so a fourth appearing fails this test. */
{
  const lines = code.split('\n');
  const at = [];
  lines.forEach((l, i) => { if (/\bdirty = (true|false)\b/.test(l)) at.push(i); });
  const viaCaller = ['showWorkbook', 'save', 'clearWorkbook'].map(grab);
  const orphans = at.filter(i => {
    const l = lines[i];
    if (/^let files = /.test(l.trim())) return false;              // the declaration
    if (/paint\(\)/.test(lines.slice(i, i + 6).join('\n'))) return false;
    return !viaCaller.some(b => b.indexOf(l.trim()) >= 0);
  });
  check('the page really has a dozen places that set `dirty` — a vacuous scan is no '
        + 'scan', at.length >= 12);
  eq('…and every one of them paints, so the heartbeat rides a funnel nothing can slip '
     + 'past', orphans.map(i => lines[i].trim()), []);
  check('…and the three that paint through their CALLER really are painted for, in that '
        + 'caller\'s own finally',
        // `busy = false` became `busyOff()` at the stuck-latch fix (2026-08-29): the
        // reset also disarms the operation's watchdog, so a raw assignment here would
        // leave a timer live to fire in the middle of the NEXT operation.
        /finally \{ busyOff\(\); renderFiles\(\); paint\(\); extCheck\(\); \}/.test(grab('openDoc'))
        && /finally \{ busyOff\(\); paint\(\); \}/.test(grab('save'))
        && /paint\(\); aiPaint\(true\)/.test(grab('mi_close')));
}
check('the keepalive rides the page tick, not a timer of its own',
      /hbRun\(true\)/.test(grab('pageTick')) && /hbSync\(\)/.test(grab('paint'))
      && /hbRun\(false\)/.test(grab('hbSync')));
eq('the beat is comfortably inside the bridge\'s own TTL — a beat AT the TTL would go '
   + 'stale on the boundary and refuse nothing',
   num('HB_TICK_MS') / 1000 <= pyNum('HEARTBEAT_TTL') / 2, true);
eq('…and the slow work still lands on the AI_POLL_MS this page has always used for the '
   + 'model pill', num('AI_POLL_MS') / num('HB_TICK_MS'), 3);
check('a closed workbook stops the registration — mi_close goes through the same paint',
      /paint\(\); aiPaint\(true\)/.test(grab('mi_close')));

// ── 4. THE EXTERNAL-CHANGE BANNER ───────────────────────────────────────────
// THE TWO SENTENCES ARE THE CONTRACT (spec §3 rule 3), and they are pinned literally.
/* ⚠️⚠️ REWRITTEN AT loffice-2026-08-28d FOR TWO FINDINGS ON THE SAME FILE.

   SERVER F-07 / F-22 + LIVE C4 — THE COPY MOVED. It was the sibling
   `<stem>.pre-agent.xlsx`, i.e. a safety copy living in the namespace of real documents:
   a workbook Debi genuinely had by that name was silently OVERWRITTEN by the first apply
   on its neighbour (F-07), such a workbook could never be written at all because the copy
   resolved to ITSELF (F-22), and the copies sat in the file rail with a download/delete
   pair, indistinguishable from documents (C4). It is now
   `.checkpoints/<stem>/pre-agent.xlsx`, which is none of those things.

   LIVE L4 — AND THE BANNER STOPPED COMPUTING THE NAME AT ALL. `extPlan` fires on nothing
   but a newer mtime, and both its sentences asserted an AGENT and that copy. Only a
   changeset apply ever writes one; Excel, a script, `curl` on /api/office/save, a second
   LOffice tab and a `git checkout` all move the mtime and got the same sentence, naming a
   file that does not exist — the DIRTY fork offering "Keep mine" on the strength of a
   backup that was not there. So the decision now takes `agentCopy`, the path the BRIDGE
   says EXISTS (office.list_docs stats it per path), and `preAgentName` is only for the
   follow-up sentence, where existence has already been established. */
// The two constants preAgentName reads, brought in from the page the same way the
// function is, so nothing here restates a literal the page owns.
const PRE_AGENT_DIR = (code.match(/PRE_AGENT_DIR = '([^']+)'/) || [])[1];
const PRE_AGENT_FILE = (code.match(/PRE_AGENT_FILE = '([^']+)'/) || [])[1];
eval(grab('preAgentName'));
{
  const DIR_JS = (code.match(/PRE_AGENT_DIR = '([^']+)'/) || [])[1];
  const FILE_JS = (code.match(/PRE_AGENT_FILE = '([^']+)'/) || [])[1];
  eq('the checkpoint folder is the one office.py actually writes into — pinned ACROSS the '
     + 'two languages, because a page naming a file that does not exist is worse than a '
     + 'page saying nothing', DIR_JS,
     (officePy.match(/CHECKPOINT_DIR = "([^"]+)"/) || [])[1]);
  eq('…and so is the copy\'s own file name', FILE_JS,
     (officePy.match(/PRE_AGENT_NAME = "([^"]+)" \+ DOC_EXT/) || [])[1] + '.xlsx');
  eq('preAgentName mirrors office_ops.pre_agent_label', preAgentName('Budget.xlsx'),
     '.checkpoints/Budget/pre-agent.xlsx');
  eq('…on a name given without its extension too', preAgentName('Budget'),
     '.checkpoints/Budget/pre-agent.xlsx');
  eq('…and a workbook actually NAMED *.pre-agent.xlsx gets its OWN folder rather than '
     + 'resolving to itself, which is the whole of F-07 and F-22',
     preAgentName('Budget.pre-agent.xlsx'),
     '.checkpoints/Budget.pre-agent/pre-agent.xlsx');
  check('…which is the rule the python states in its own words',
        /neither itself nor a document/.test(opsPy));
  eq('a nameless workbook yields nothing rather than a bare folder path',
     [preAgentName(''), preAgentName(null)], ['', '']);
}
const EXT_EPS = num('EXT_EPS');
eval(grab('extPlan'));
{
  eq('no workbook, no banner', extPlan({}).act, 'none');
  eq('a workbook with no mtime is not an accusation',
     extPlan({ name: 'A.xlsx', seen: 5, mtime: 0 }).act, 'none');
  eq('THE FIRST SIGHT IS A BASELINE, NEVER A BANNER — a page that has not yet learned '
     + 'the mtime must not report the file as changed',
     extPlan({ name: 'A.xlsx', seen: 0, mtime: 100 }).act, 'baseline');
  eq('an unchanged file says nothing',
     extPlan({ name: 'A.xlsx', seen: 100, mtime: 100 }).act, 'none');
  eq('…and neither does a filesystem\'s own jitter under the slack',
     extPlan({ name: 'A.xlsx', seen: 100, mtime: 100 + EXT_EPS / 2 }).act, 'none');
  eq('an OLDER mtime is not a change either', 
     extPlan({ name: 'A.xlsx', seen: 200, mtime: 100 }).act, 'none');

  /* ══ CLEAN PAGE → AUTO-RELOAD. TWO SENTENCES NOW, ONE PER TRUTH (live finding L4).
     The `agentCopy` field is the path the bridge says EXISTS for this workbook. With one,
     the change is attributed to the agent and the copy is NAMED — that copy is the only
     thing that HAS an agent as its author. Without one, nothing is promised. */
  const COPY = '.checkpoints/Budget/pre-agent.xlsx';
  const clean = extPlan({ name: 'Budget.xlsx', dirty: false, seen: 100, mtime: 200,
                          agentCopy: COPY });
  eq('a clean page reloads itself', clean.act, 'reload');
  eq('…and when a safety copy really is there, the sentence names it and says the agent '
     + 'did it', clean.text,
     'the agent edited this file — reloaded (the copy from before that change is kept as '
     + COPY + ')');
  const cleanNo = extPlan({ name: 'Budget.xlsx', dirty: false, seen: 100, mtime: 200 });
  eq('…and it still reloads when nothing here wrote the file', cleanNo.act, 'reload');
  check('…BUT IT PROMISES NO COPY AND BLAMES NO AGENT — this is the fork Excel, a script, '
        + 'a second tab and a git checkout all take, and it used to get the agent sentence',
        !/pre-agent/.test(cleanNo.text) && !/the agent edited/.test(cleanNo.text)
        && /outside LOffice/.test(cleanNo.text), cleanNo.text);

  // DIRTY PAGE → TWO BUTTONS, and the sentence that says which version survives where.
  const dirtyP = extPlan({ name: 'Budget.xlsx', dirty: true, seen: 100, mtime: 200,
                           agentCopy: COPY });
  eq('a dirty page asks instead of discarding your work', dirtyP.act, 'ask');
  check('…the banner names the file', dirtyP.text.indexOf('Budget.xlsx') > 0);
  check('…says what Reload does', /Reload discards your unsaved edits/.test(dirtyP.text));
  check('…says what Keep mine does', /Keep mine keeps yours/.test(dirtyP.text));
  /* ⚠️ AND THE DANGEROUS FORK: dirty, changed on disk, and NO safety copy. This offered
     "Keep mine" on the strength of a backup that did not exist (live finding L4). It must
     name no copy and must SAY there is none, because the whole point of the sentence is
     what the user can fall back on. */
  const dirtyNo = extPlan({ name: 'Budget.xlsx', dirty: true, seen: 100, mtime: 200 });
  eq('a dirty page with no safety copy still asks', dirtyNo.act, 'ask');
  check('…and says PLAINLY that there is no safety copy, rather than naming one',
        !/pre-agent/.test(dirtyNo.text) && /NO safety copy/.test(dirtyNo.text)
        && /Download it first/.test(dirtyNo.text), dirtyNo.text);
  eq('…and it carries the copy path (or the empty string) so the follow-up sentence '
     + 'cannot invent one either', [dirtyP.copy, dirtyNo.copy], [COPY, '']);
  /* ⚠️⚠️ THE ONE SENTENCE THE SPEC WRITES OUT IN FULL, and it is pinned as a literal
     substring rather than paraphrased: "the banner must say that plainly". Keeping your
     version means your next ⌘S overwrites the agent's write, and the agent's write
     survives in NOTHING — the .pre-agent copy holds the PRE-write state, not the
     write. A banner that only implied that would be the failure this rule exists for. */
  check('…AND SAYS PLAINLY THAT SAVING WILL OVERWRITE WHAT IS ON DISK',
        /saving will overwrite what is on disk/.test(dirtyP.text), dirtyP.text);
  check('…and names where the PRE-write state is kept, which is the only version the '
        + 'agent lane can restore', dirtyP.text.indexOf(COPY) > 0);
  check('…and says BEFORE, so the copy is never read as "the agent\'s write is safe"',
        /before that change is kept/.test(dirtyP.text));
  [null, undefined, 0, 'x', { name: 1 }].forEach((v, i) => {
    let threw = null, r = null;
    try { r = extPlan(v); } catch (e) { threw = e; }
    check('extPlan survives junk input and does nothing (case ' + i + ')',
          !threw && r && r.act === 'none');
  });
}
{
  const ea = grab('extAct');
  /* ⚠️ REWRITTEN AT loffice-2026-08-28a, AND THE DECISION IT GUARDS DID NOT CHANGE. The
     two sentences above (extPlan) are byte-identical and still pinned. What changed is
     what "reload" MEANS: in one-editor world the document lives in the embedded
     ONLYOFFICE editor, so calling openDoc() alone would re-read the file into a snapshot
     nobody is looking at while the editor went on showing the stale document. So extAct
     goes through ooExtReload, which is a ONE-LINE fork: the editor re-reads the same
     workbook in place (keeping the warm frame, the rail, the AI conversation and the
     pane widths), and when the editor is NOT the editor it is still literally
     openDoc(name). There is still exactly one loader per surface. */
  const er = grab('ooExtReload');
  check('the reload path goes through ooExtReload, the ONE fork between "reload the '
        + 'document in the editor" and "reload it into the grid"',
        /ooExtReload\(name\)\.then/.test(ea)
        && (code.match(/function ooExtReload\(/g) || []).length === 1);
  check('…and its grid half really is the page\'s EXISTING load path, unchanged',
        /if \(!editorActive\(\)\) return openDoc\(name\);/.test(er)
        && (code.match(/async function openDoc\(/g) || []).length === 1);
  check('…and its editor half reloads the DOCUMENT, not the page — and refreshes the '
        + 'snapshot the AI panel sends, so the model sees the agent\'s version',
        /ooReload\('ext-change'\)/.test(er) && /ooRefreshSnapshot\(\)/.test(er)
        && !/location\.(href|reload)/.test(er));
  /* ⚠️ AND IT SAYS THE SENTENCE **AFTER** THE OPEN. openDoc's first act is say(''), so a
     message set beforehand flashes and vanishes — i.e. the spec's one required sentence
     would never be read. Found by reading the code, and pinned here so it cannot come
     back the obvious way round. */
  check('…and says the sentence AFTER it, because openDoc clears the message line first',
        /ooExtReload\(name\)\.then\(\(\) => \{ if \(!el\('msg'\)\.textContent\) say\(plan\.text, 'dim'\); \}\)/
          .test(ea)
        && /busyOn\('opening [^)]*\); say\(''\); paint\(\);/.test(grab('openDoc')));
  check('…and never over the top of something openDoc had to say — a read failure or a '
        + 'truncation warning is the bigger sentence', /!el\('msg'\)\.textContent/.test(ea));
  check('the dirty path is a TWO-BUTTON banner, in the message box that already exists',
        /label: 'Reload'/.test(ea) && /label: 'Keep mine'/.test(ea)
        && /say\(plan\.text, null, \[/.test(ea));
  check('…Reload discards the in-memory edits explicitly, rather than tripping over the '
        + 'discard guard that would ask the same question twice',
        /dirty = false; paint\(\);/.test(ea) && /ooExtReload\(name\)/.test(ea));
  // The apostrophe is BACKSLASH-ESCAPED in the page's single-quoted string, so the
  // source form is matched with a tolerant class; the sentence itself is pinned as a
  // literal against extPlan's real output above, which is the pin that counts.
  /* ⚠️ REWORDED FOR live finding L4: the sentence promised the agent's `.pre-agent.xlsx`
     copy on a path that had never made one, and "the agent's changes" named an author this
     banner cannot know. It repeats the overwrite warning — that half was right and the
     reason for it has not changed — and it names the safety copy ONLY when the bridge said
     one exists. */
  check('…and Keep mine repeats the overwrite warning, because the banner it replaces '
        + 'is gone the moment it is clicked',
        /will overwrite what is on disk/.test(ea));
  check('…and it names a safety copy only when there IS one, and otherwise says there is '
        + 'not — the dangerous half of L4 was offering Keep mine on a backup that did not '
        + 'exist',
        /extCopy\s*\n?\s*\?/.test(ea) && /nothing here has a copy of what is on disk/
          .test(ea));
  check('both answers beacon, so "it reloaded my file" is answerable from the boot log',
        /bx\('ext-reload'/.test(ea) && /bx\('ext-keep-mine'/.test(ea));
  const ec = grab('extCheck');
  check('the mtime comes off the EXISTING file list, which already carries `modified` — '
        + 'no new route', /fetch\('\/api\/office\/files'/.test(ec) && /row\.modified/.test(ec));
  check('…and office.py really does put it there',
        /"modified": st\.st_mtime/.test(
          fs.readFileSync(path.join(ROOT, 'bridge', 'office.py'), 'utf8')));
  check('the check rides the page tick, not a timer of its own',
        /extCheck\(\);/.test(grab('pageTick')) && !/setInterval/.test(ec));
  check('the baseline moves BEFORE the banner is drawn, which is what makes it fire '
        + 'once per change instead of every beat for ever',
        /extSeen = Number\(row\.modified\)[\s\S]{0,200}extAct\(plan, name\)/.test(ec));
  check('a workbook that was opened, saved or closed gets a FRESH baseline rather than '
        + 'a stale one — a stale-old mtime would accuse the agent of the user\'s own save',
        /extSeen = 0;/.test(grab('showWorkbook')) && /extSeen = 0;/.test(grab('save'))
        && /extSeen = 0/.test(grab('clearWorkbook')));
  check('…and an open establishes it at once rather than a beat later',
        /renderFiles\(\); paint\(\); extCheck\(\)/.test(grab('openDoc')));
  /* ⚠️ STRENGTHENED 2026-08-29 (adversarial pass on the stuck-latch fix). The old check
     was `!el('msg').textContent` — recovery only when the strip was left BLANK. Any
     say() that REPLACED the banner with a different sentence stranded the latch true for
     the session, silently retiring the agent-write watch; busyBlock() puts up exactly
     such a sentence. Identity (msgGen), not emptiness. */
  check('a banner REPLACED by some other say() — not merely cleared — does not leave the '
        + 'latch stuck ON, silently retiring the whole mechanism',
        /if \(extAsking && msgGen !== extMsgGen\) \{ extAsking = false;/.test(ec)
        && /extMsgGen = msgGen;/.test(grab('extAct')));
  check('one banner at a time, and it does not race the load it asked for',
        /if \(!current \|\| busy \|\| extAsking\) return/.test(ec)
        && /if \(name !== current\) return null/.test(ec));
  check('a workbook that vanished is not this banner\'s business',
        /if \(!row\) return null/.test(ec));
}
// say() with one action and with two, EXECUTED against a stub DOM — the two-button
// banner is load-bearing and a regex would not notice a second button being dropped.
{
  const made = [];
  const mk = tag => { const n = { tag: tag, kids: [], style: {},
                                  set textContent(v) { this._t = v; },
                                  get textContent() { return this._t; },
                                  appendChild(c) { this.kids.push(c); } };
                      made.push(n); return n; };
  const msg = mk('div');
  msg.classList = { toggle() {} };
  const document = { createElement: mk };
  const el = () => msg;
  // say() stamps the strip's identity (msgGen) so a banner's owner can tell "still
  // mine" from "replaced" — see extCheck's stranded-latch fix, 2026-08-29.
  var msgGen = 0;
  eval(grab('say'));
  msg.kids = [];
  say('one', null, { label: 'A', run() {} });
  eq('say() with a single action draws the text and one button',
     msg.kids.map(k => k.textContent), ['one', 'A']);
  msg.kids = [];
  say('two', null, [{ label: 'Reload', run() {} }, { label: 'Keep mine', run() {} }]);
  eq('…and an ARRAY draws them in order — the banner\'s two answers',
     msg.kids.map(k => k.textContent), ['two', 'Reload', 'Keep mine']);
  msg.kids = [];
  say('none', null, null);
  eq('…and no action is still just the sentence', msg.kids.length, 1);
  msg.kids = [];
  say('bad', null, [{ label: 'x' }, null, { run() {} }]);
  eq('a malformed action is skipped rather than drawn as a dead button',
     msg.kids.length, 1);
}

/* ══ 4b. THE CHANGESET CARD — ONE INTENTION, ONE CARD ═══════════════════════════
   (loffice-2026-08-28b, docs/FABLE-AGENT-CHANGESET-SPEC.md §2)

   THE INCIDENT THIS BLOCK EXISTS FOR, from docs/research/2026-08-27-agent-consent-
   incident.md, in its own words: "add a new row called purchases and the amount for it
   is 200" produced TWO approval cards, one was never answered, a write failed, and the
   model said "Done. Added Purchases = 200 on row 7 … new planned total 1,635" while the
   sheet still showed 6 rows and 1,435 — with NOTHING in the panel contradicting it.

   So the assertions below are not "does the card render". They are the four rules that
   make that transcript impossible:
     1. ONE card per staged changeset, listing every op and every cell's before → after.
     2. A harness-authored status line under EVERY staging turn — narration never stands
        alone.
     3. A success badge that can ONLY come from a receipt (cells_written + a re-read
        verify + a receipt hash), never from model text and never from an HTTP 200.
     4. Whether something was staged is read from the BRIDGE, not from the reply.
   Plus the outcome line that reaches the model's next turn, and the ✗ chips. */
{
  eval(grab('csRow')); eval(grab('csRows')); eval(grab('csCardText'));
  eval(grab('csReceiptText')); eval(grab('csPrefix'));
  eval(grab('csTypeLines')); eval(grab('csWarnLines')); eval(grab('csComputedText'));
  const CS_LIST_MAX = num('CS_LIST_MAX');

  // ── the before→after list, which is the review surface (spec §5: no editor-side
  //    highlight in v2 — this list IS the diff Debi reads) ──
  const cs = {
    changeset_id: 'abc123', name: 'ZZ final A.xlsx', op_count: 3,
    summary: 'ZZ final A.xlsx: 3 cells written, 1 row/column(s) inserted — 4 cells '
           + 'would change.',
    op_list: ['insert 1 blank row(s) above row 7', 'set A7:B7', 'set B8'],
    preview: [{ sheet: 'Sheet1', ref: 'A7', before: 'Total', after: 'purchases' },
              { sheet: 'Sheet1', ref: 'B7', before: '=SUM(B2:B6)', after: '200' },
              { sheet: 'Sheet1', ref: 'A8', before: '', after: 'Total' },
              { sheet: 'Sheet1', ref: 'B8', before: '', after: '=SUM(B2:B7)' }],
    preview_total: 4, notes: ['formula references were NOT rewritten'],
  };
  const rows = csRows(cs);
  eq('every touched cell is listed as ref, before → after — including the cells the '
     + 'INSERT moved that nobody named, which is exactly what a per-call approval card '
     + 'could never show', rows.lines,
     ['A7  Total  →  purchases',
      'B7  =SUM(B2:B6)  →  200',
      'A8  (empty)  →  Total',
      'B8  (empty)  →  =SUM(B2:B7)']);
  eq('…and nothing is hidden: a change over the list cap SAYS how many more there are',
     csRows({ preview: [{ ref: 'A1', before: '', after: 'x' }], preview_total: 900 }).more,
     899);
  eq('an empty cell reads as "(empty)" on both sides rather than as a blank gap',
     csRows({ preview: [{ ref: 'A1', before: 'x', after: '' }] }).lines,
     ['A1  x  →  (empty)']);
  check('the list cap is a real number and is not one row',
        CS_LIST_MAX >= 20 && rows.more === 0);
  [null, undefined, {}, 0, 'x', { preview: 'no' }].forEach((v, i) => {
    let threw = null, r = null;
    try { r = csRows(v); } catch (e) { threw = e; }
    check('csRows survives junk input (case ' + i + ')', !threw && r && !r.lines.length);
  });

  // ── the card's words: a PROPOSAL, and the two guarantees behind Apply ──
  const t = csCardText(cs);
  check('the card says how many operations, and names the workbook',
        /3 operations/.test(t) && t.indexOf('ZZ final A.xlsx') > 0);
  check('…carries the bridge\'s own summary line rather than re-deriving one',
        t.indexOf(cs.summary) > 0);
  check('…SAYS NOTHING HAS BEEN WRITTEN, which is the sentence the whole lane rests on',
        /Nothing has been written/.test(t) && /this is a proposal/.test(t));
  check('…that Apply is the only thing that touches the file',
        /Apply is the only thing\s+that touches the file/.test(t.replace(/\n/g, ' ')));
  check('…and that Apply checkpoints first, so the click is responsible rather than '
        + 'merely quick (spec §3)',
        /keeps a checkpoint first/.test(t) && /can be undone/.test(t));
  eq('one operation is not "1 operations"', /1 operation\b/.test(
     csCardText({ op_count: 1, name: 'a.xlsx', summary: '' })), true);
  check('csCardText survives junk', (() => {
    try { return typeof csCardText(null) === 'string'; } catch (e) { return false; } })());

  /* ⚠️⚠️ 3. THE BADGE COMES FROM THE RECEIPT AND FROM NOTHING ELSE. This is the
     assertion that answers "the model claimed Done": the only text that can ever say
     "applied" is built from numbers the bridge measured AFTER saving the file. */
  const r = { changeset_id: 'abc123', receipt: 'fe2e56d8', cells_written: 3,
              rows_or_columns_inserted: 1, verify_note: '4 of 4 …' };
  const badge = csReceiptText(r);
  eq('the badge states what actually landed and the receipt that proves it', badge,
     '✓ applied · 3 cells written, 1 inserted · receipt fe2e56d8');
  check('a receipt with no cell change still says so rather than claiming a write',
        /no cell changed/.test(csReceiptText({ receipt: 'x' })));
  check('…and a receipt with no hash does not invent one',
        /receipt \?$/.test(csReceiptText({ cells_written: 1 })));
  check('a DELETE is shouted in the badge, because it is the one outcome that cannot be '
        + 'read off the sheet by eye',
        /DELETED/.test(csReceiptText({ rows_or_columns_deleted: 2, receipt: 'x' })));
  const src = grab('csApply');
  /* ⚠️ TWO CALL SITES AS OF loffice-2026-08-28d, NOT ONE, AND BOTH TAKE `j`. The second
     is the post-apply COMPUTED CHECK: after the editor has reloaded and been asked what
     the new formulas evaluate to, the badge is RE-LABELLED with that answer appended. The
     fence is unchanged in substance — every csReceiptText argument is still the parsed
     body of the apply POST, and every call site is still inside csApply — so it is
     asserted that way rather than by a bare count of one. */
  check('THE BADGE IS ONLY REACHED FROM AN APPLY RESPONSE — every csReceiptText call '
        + 'takes the parsed body of the apply POST, and every call site in the page is '
        + 'inside csApply',
        /csStamp\(card, csReceiptText\(j\)\)/.test(src)
        && /csRelabel\(card, csReceiptText\(j\) \+ ' · ' \+ comp\.line\)/.test(src)
        && (code.match(/csReceiptText\(/g) || []).length === 3
        && (stripComments(src).match(/csReceiptText\(/g) || []).length === 2);
  check('…and the relabel does not empty the bar, so the receipt can grow a computed '
        + 'line without losing the "Undo this change" chip that was added before it',
        /const lang = card\._bar\.querySelector\('\.lang'\)/.test(grab('csRelabel'))
        && !/innerHTML/.test(grab('csRelabel')));
  check('…and a non-ok apply NEVER reaches it: the throw is before the stamp',
        src.indexOf('throw new Error') < src.indexOf('csReceiptText'));
  check('…a failed apply says "NOT applied" and leaves the card answerable, rather than '
        + 'stamping something',
        /That was NOT applied: /.test(src) && /csBusy\(card, false\)/.test(src));
  check('…and the receipt\'s RE-READ is shown, so "it says it wrote it" and "the file '
        + 'says so" are two visible facts',
        /re-read from the file after saving/.test(src) && /j\.verify/.test(src));

  // ── 2. THE STATUS LINE: harness-authored, on every staging turn ──
  eq('the status line is the spec\'s sentence, character for character',
     (code.match(/CS_STAGED_LINE = '([^']+)'/) || [])[1],
     '⏳ staged — nothing is written until you press Apply');
  const after = grab('csAfterTurn');
  check('…and it is drawn for EVERY turn that staged something, before the card and '
        + 'unconditionally — narration never stands alone',
        /csStatusLine\(turn\.wrap\);\s*\n\s*csShown = cs\.changeset_id;\s*\n\s*csCard\(/
          .test(after));
  check('…and there is exactly one way to draw it',
        (code.match(/function csStatusLine\(/g) || []).length === 1);

  /* 4. WHETHER SOMETHING WAS STAGED IS A FACT ABOUT THE BRIDGE. A model that says it
     staged nothing still gets the card; one that claims it staged something when it did
     not gets neither card nor status line. */
  check('the panel ASKS THE BRIDGE for the pending changeset instead of parsing the '
        + 'reply for a claim',
        /fetch\('\/api\/office\/changeset\?file='/.test(grab('csRead'))
        && !/out\b|reply|text/.test(grab('csAfterTurn')));
  check('…keyed by the open workbook AND the session the turn belongs to',
        /file=' \+ encodeURIComponent\(current \|\| ''\)/.test(grab('csRead'))
        && /session=' \+ encodeURIComponent\(agentSid \|\| ''\)/.test(grab('csRead')));
  check('…and it runs after EVERY agent turn, error or not — a model that staged and '
        + 'then crashed mid-sentence still staged it',
        /await csAfterTurn\(turn\);/.test(asend)
        && stripComments(asend).indexOf('await csAfterTurn') >
           stripComments(asend).lastIndexOf('turn.wrap.appendChild(d)'));
  check('a proposal outlives the page: the tick re-draws a pending card after a reload, '
        + 'so a changeset can never be left unapplyable and forgotten',
        /csTick\(\);/.test(grab('pageTick'))
        && /cs\.changeset_id === csShown/.test(grab('csTick'))
        && /aiLane !== LANE_AGENT \|\| aiBusy/.test(grab('csTick')));

  // ── APPLY / DISMISS / UNDO, on the wire ──
  check('Apply POSTs to the bridge\'s apply route — the write happens THERE, not here',
        /\/apply'/.test(src)
        && /'\/api\/office\/changeset\/'\s*\n?\s*\+ encodeURIComponent\(cs\.changeset_id\)/
             .test(src)
        && /method: 'POST'/.test(src));
  check('…and the document is reloaded through the page\'s EXISTING path afterwards, '
        + 'never re-rendered from what we think we wrote',
        /ooExtReload\(j\.name\)/.test(src) && /extSeen = 0/.test(src));
  const dis = grab('csDismiss');
  check('Dismiss POSTs to the dismiss route and stamps the honest sentence',
        /\/dismiss'/.test(dis)
        && /✗ dismissed — nothing was written/.test(dis));
  check('…and a dismiss that FAILED does not stamp it as dismissed',
        dis.indexOf('throw new Error') < dis.indexOf('csStamp')
        && /dismiss failed: /.test(dis));
  const un = grab('csUndo');
  check('"Undo this change" is offered ONLY when the apply receipt carried a checkpoint '
        + '— an undo button with nothing behind it is a lie',
        /if \(j\.checkpoint\) \{/.test(src) && /'Undo this change'/.test(src));
  check('…and it POSTs the undo route, then reloads the document',
        /\/undo'/.test(un) && /ooExtReload\(j\.name\)/.test(un));
  check('…and a REFUSED undo (the mtime fence) reads as a refusal carrying the bridge\'s '
        + 'own sentence, never as an undo that quietly did nothing',
        /Not undone: /.test(un) && /e\.message/.test(un)
        && un.indexOf('throw new Error') < un.indexOf('Not undone'));
  check('every one of the three answers beacons, so "I pressed Apply and nothing '
        + 'happened" is answerable from the boot log alone',
        ['cs-card', 'cs-applied', 'cs-dismissed', 'cs-undone', 'cs-recovered']
          .every(b => code.indexOf("bx('" + b + "'") > 0)
        && ['cs-apply-fail', 'cs-dismiss-fail', 'cs-undo-fail', 'cs-fetch-fail']
          .every(b => code.indexOf("bx('" + b + "'") > 0));

  /* ⚠️⚠️ THE SESSION LINE — spec §2's "the bridge injects one system line into the
     Hermes session", shipped as the spec's own named fallback. The vendored gateway has
     no way to append a message to an IDLE session (session.steer lands on the next TOOL
     RESULT, i.e. after the next turn has already begun answering, and records a fake
     user bubble on the way — see bridge/office_ops.push_session_line). So the bridge
     queues the line and this page prepends it to the next agent message, which puts it
     in the model's context BEFORE it thinks. What is pinned here is that it cannot be
     lost and cannot be silently dropped. */
  const pre = csPrefix(['[LOffice] changeset abc was APPLIED …',
                        '[LOffice] changeset def was DISMISSED …']);
  check('the outcome lines ride in front of the next message, labelled as the RECORD '
        + 'and not as the user speaking',
        pre.indexOf('SYSTEM — what happened in LOffice since your last turn') === 0
        && /not the user speaking/.test(pre)
        && pre.indexOf('APPLIED') > 0 && pre.indexOf('DISMISSED') > 0);
  eq('…and no lines means no prefix at all — an empty preamble is noise',
     [csPrefix([]), csPrefix(null), csPrefix(['', '  '])], ['', '', '']);
  check('the message really carries it, in front of the grounding',
        /csPrefix\(carried\) \+ grounding/.test(asend));
  check('…and the queue is drained AS IT IS SENT, so a line that never reached a message '
        + 'is a line still owed',
        /const carried = csLines\.slice\(\);\s*\n\s*csLines = \[\];/.test(asend));
  check('…both outcomes queue one: the bridge hands back session_line on apply AND on '
        + 'dismiss, and the page records both',
        /csNote\(j\.session_line\)/.test(src) && /csNote\(j\.session_line\)/.test(dis)
        && /csNote\(j\.session_line\)/.test(un));
  check('…and lines the page missed (it was reloaded) are recovered from the bridge',
        /session_lines \|\| \[\]\)\.forEach\(csNote\)/.test(grab('csRead')));
  check('a line is never queued twice', /csLines\.indexOf\(s\) < 0/.test(grab('csNote')));

  // ── ✗ CHIPS: the silent-failure gap, closed ──
  const chip = grab('csErrChip');
  check('a failed tool result renders as a red chip carrying the TOOL\'S OWN sentence — '
        + '"a tool failed" is not an answer to "what went wrong"',
        /className = 'err'/.test(chip) && /'✗ '/.test(chip)
        && /String\(why \|\| /.test(chip));
  const fr = grab('agentFrame');
  check('…driven off the frame the BRIDGE sets when a tool result carries an error, so '
        + 'it fires for native tools and for every MCP server alike',
        /if \(j && j\.is_error\)/.test(fr) && /csErrChip\(turn\.wrap/.test(fr));
  check('…and the bridge really sets it',
        /fr\["is_error"\] = True/.test(require('./_appsrc.js').appSource()));
  check('…and the chip survives the end-of-turn re-render, which would otherwise delete '
        + 'it the moment the model\'s prose arrived',
        /held\.errors = \(held\.errors \|\| \[\]\)\.concat/.test(fr)
        && /\(held\.errors \|\| \[\]\)\.forEach\(e => csErrChip\(turn\.wrap, e\.tool, e\.why\)\)/
             .test(asend));
  check('…and the step list says it failed too, so the "tools used" disclosure cannot '
        + 'read as a clean run', /' — ✗ '/.test(fr));

  // ── ZERO NEW CSS, computed the way PART 5 computes it for the other cards ──
  const csSrc = ['csCard', 'csStamp', 'csStatusLine', 'csErrChip'].map(grab).join('\n');
  const csCls = Array.from(new Set((csSrc.match(/className = '([\w-]+)'/g) || [])
    .map(x => x.split("'")[1])));
  check('the changeset card is built from several existing classes', csCls.length >= 4);
  check('…and EVERY one of them is already in the stylesheet — the Quick lane\'s exact '
        + 'visual grammar, which is what the spec asked for by name',
        csCls.every(c => rules.some(rr => new RegExp('\\.' + c + '(?![\\w-])').test(rr.sel))),
        csCls);
  check('…and it reuses the Quick lane\'s own card helpers rather than a second set',
        /actChip\(bar, 'Apply'\)/.test(grab('csCard'))
        && /actChip\(bar, 'Dismiss', 'lnk'\)/.test(grab('csCard'))
        && /actDet\(/.test(grab('csCard')) && /actNote\(card/.test(src));
}

// ── 5. THE WRITER FENCE — THE NEGATIVE THAT MATTERS MOST ────────────────────
/* ⚠️⚠️ THE AGENT LANE ADDS ZERO PAGE-SIDE WRITERS, AND THAT IS THE WHOLE SAFETY STORY
   OF THIS SLICE. Hermes's writes land on DISK — through office_ops.py, behind Hermes's
   own approval card, with a .pre-agent copy taken first. This page finds out the way it
   would find out about any other program editing the file (the mtime moved) and reloads
   through its EXISTING load path. The writer-set fence in PART 4 is unchanged and still
   lists exactly seven functions; what is added here is the per-function assertion that
   nothing in the new lane writes anything at all. */
{
  const S2 = ['agentGate', 'agentToolNote', 'preAgentName', 'lanePaint', 'laneSet',
              'laneApply', 'agentProbe', 'agentSend', 'agentFrame', 'agentName',
              'agentToolOf',
              'agentCardText', 'agentCard', 'agentApprove', 'agentStamp', 'agentExpire',
              'hbPlan', 'hbPost', 'hbRun', 'hbSync', 'extPlan', 'extCheck', 'extAct',
              'pageTick', 'pageTickStart',
              /* ⚠️ AND THE CHANGESET LANE (loffice-2026-08-28b), WHICH IS WHERE THE
                 FENCE EARNS ITS KEEP. This lane's Apply WRITES A WORKBOOK — so the one
                 thing that must be provable is that the write does not happen HERE. It
                 happens bridge-side, in office_ops.apply_changeset, behind a checkpoint;
                 the page POSTs an id and reloads the document. Every function of it is
                 listed, and not one of them may touch a cell or the dirty flag. */
              'csNote', 'csPrefix', 'csRow', 'csRows', 'csCardText', 'csReceiptText',
              'csCard', 'csBusy', 'csApply', 'csDismiss', 'csUndo', 'csStamp',
              'csRelabel', 'csStatusLine', 'csErrChip', 'csRead', 'csAfterTurn', 'csTick',
              /* AND THE TYPE-HONESTY SLICE (loffice-2026-08-28d): the coercion outcomes
                 on the card, the aggregate-over-text info line, and the post-apply
                 computed check. The computed check READS the editor (that is its whole
                 job) but must not WRITE anything — readCells is a getter and this fence
                 is what says so. */
              'csTypeLines', 'csWarnLines', 'csComputedText', 'csComputed'];
  check('every function this slice added is actually IN the page — a vacuous fence is '
        + 'no fence', S2.every(n => fnNames.indexOf(n) >= 0), S2.filter(n => fnNames.indexOf(n) < 0));
  check('and NOT ONE of them writes a cell, moves one, or sets the dirty flag',
        S2.every(n => !writers.test(stripComments(grab(n)))),
        S2.filter(n => writers.test(stripComments(grab(n)))));
  /* ⚠️ THE ONE DELIBERATE EXCEPTION, NAMED RATHER THAN HIDDEN: extAct's Reload button
     sets `dirty = false`. That is not a write — it is the ANSWER to the question the
     button asked ("discard my in-memory edits"), and clearing it is what stops
     confirmDiscard asking the same question a second time. It can only ever LOSE
     in-memory edits the user just chose to lose, and it never touches a cell. */
  eq('…with exactly one flag touched anywhere in the new lane, in the one place the '
     + 'user asked for it',
     S2.filter(n => /\bdirty = (true|false)\b/.test(stripComments(grab(n)))), ['extAct']);
  check('…and it is `false`, never `true`: nothing in this lane can make the page dirty',
        !/\bdirty = true\b/.test(stripComments(grab('extAct'))));
  check('nothing in the new lane can apply a Quick-lane action plan either',
        S2.every(n => !/actApply|actRunOps|replaceWrite|gridRemap/
          .test(stripComments(grab(n)))));
  check('…and the reload still resolves to the page\'s existing load path — one openDoc '
        + 'in the whole page, reached through the one fork',
        /ooExtReload\(name\)/.test(grab('extAct'))
        && /openDoc\(name\)/.test(grab('ooExtReload'))
        && (code.match(/async function openDoc\(/g) || []).length === 1);
}

// BEACONS — the diagnostic contract, extended to the new capability.
['lane', 'agent-send', 'agent-session', 'agent-approval', 'agent-approved', 'heartbeat',
 'ext-base', 'ext-change', 'ext-reload', 'ext-keep-mine']
  .forEach(st => check('the page beacons ' + st, code.indexOf("bx('" + st + "'") > 0));
check('…and every failure of the new lane beacons its reason, so "it did nothing" is '
      + 'answerable from the boot log alone',
      ['agent-mcp-fail', 'agent-tools-fail', 'agent-fail', 'agent-approve-fail',
       'hb-fail', 'ext-check-fail'].every(st => code.indexOf("bx('" + st + "'") > 0));
check('the landing beacon says which lane the page came up in',
      /lane=' \+ aiLane/.test(grab('boot')));

/* ══ 6. THE ONE-EDITOR APPLY — WHERE A QUICK-LANE PLAN ACTUALLY GOES ═══════════
   (loffice-2026-08-28a, Debi's one-editor ruling, roadmap §8)

   The parse, the caps, the preview and every refusal in PART 4 above did not move a
   line and are still the tests that guard them. What changed is the BACKEND of one
   click: when the embedded ONLYOFFICE editor owns the document, Apply runs the SAME
   validated ops through the editor's own builder API instead of through our tier-1
   model — which is what makes the EDITOR'S ⌘Z undo an AI apply, and what let this
   page's own undo stack retire with the grid.

   Two PURE functions carry that whole decision, which is why it is testable at all:
     · ooOpPlan(ops)     — how each op will be carried out, and the route for the plan.
     · ooEditorOps(ops)  — the 'api' ops translated into the A1-addressed verbs the
                           editor speaks.
   They are executed here against real op lists, because the alternative — grepping the
   page for the word "sort" — would pass against a function that routed it wrongly. */
eval(grab('ooOpPlan'));
eval(grab('ooRects'));            // the format-op grouper ooEditorOps calls (28c)
eval(grab('ooTextForce'));        // …and the editor's-parser guard (28c)
eval(grab('ooEditorOps'));

/* ══ ooEditorOps: THE RANGE MUST BE THE WHOLE RECTANGLE ════════════════════════
   A LIE-TO-USER found in the loffice-2026-08-28d adversarial self-pass, live, in a real
   editor — not in either hunt's catalogue, and live since the one-editor ruling.

   MEASURED in the vendored bundle (v9.2.0.119+3 — and still true at +5: sdkjs/cell/sdk-all-min.js is a BYTE-IDENTICAL file between the two tags, verified 2026-08-28), the two forms side by side in one call:
       SetValue over 'D1'    with [[a,b],[c,d],[e,f]]  →  D1=a and NOTHING ELSE
       SetValue over 'G1:H3' with the same array        →  all six cells
   ApiRange.SetValue writes an array ACROSS ITS OWN RANGE. The parent used to emit the
   ANCHOR only (`colName(o.c) + (o.r + 1)`), so every multi-cell Quick-lane apply through
   the editor stored exactly ONE cell — while `done.cells` counted every value and the card
   stamped "6 written", and the ⌘S it then asked for made that permanent. The incident's
   exact shape: a true-looking number over a write that did not happen. */
{
  const rows = ooEditorOps([{ op: 'set', r: 0, c: 0,
                              values: [['Month', 'Planned'], ['January', 900]] }], null);
  const set = rows.filter(r => r.k === 'set')[0];
  eq('a multi-cell `set` addresses the WHOLE rectangle, so SetValue writes all of it',
     set.at, 'A1:B2');
  eq('…and the values it is handed are exactly that rectangle', set.values,
     [['Month', 'Planned'], ['January', 900]]);
  /* ⚠️ `null` MEANS "EMPTY THIS CELL", AND THE EDITOR'S WAY OF SAYING THAT IS ''.
     MEASURED live in the same run: SetValue over 'F1:H1' with [[null,'','keep']] wrote
     F1 = "#N/A" — the ERROR VALUE, which looks like a broken formula and is worse than
     the silence it replaced. Unreachable before the rectangle fix (only the anchor was
     ever written), so it is the same defect surfacing rather than a new one. */
  const nulls = ooEditorOps([{ op: 'set', r: 0, c: 0,
                               values: [['keep', null], [undefined, 2]] }], null)
    .filter(r => r.k === 'set')[0];
  eq('a null or an undefined becomes the empty string, never the #N/A the editor writes '
     + 'for null', nulls.values, [['keep', ''], ['', 2]]);
  /* ⚠️⚠️ AND A PLAIN NUMERIC STRING GOES AS A NUMBER. This is the 2026-08-28 incident
     living on in the editor route, found in the loffice-2026-08-28d self-pass and MEASURED
     LIVE: LOffice's own starter template came up with `=SUM(B2:B5)` reading 0 over the four
     amounts directly above it, every amount left-aligned. The test was
     `!co || !co.n || …`, and `coerceNumeric('900')` returns {v:900, n:NULL} — the pattern
     is deliberately null because General is already right for a bare number — so `!co.n`
     read that as "keep it as text", sent the STRING, and `ooTextForce` then stamped the
     cell `@` to protect it. An ordinary integer pinned as text on purpose. `=SUM` ignores
     text (0) while `=C2-B2` still worked (operators DO coerce), which is why it looked
     half-working. The question is "does our rule say this is a NUMBER", never "does it
     also have a pattern to write". */
  // A local fixture: an 'Amount' header in B1 so the inference reads column B as numeric.
  const numCol = { name: 'S', cellData: { '0': { '1': { v: 'Amount', t: 1 } } } };
  const plain = ooEditorOps([{ op: 'set', r: 1, c: 1,
                               values: [['900'], ['320'], ['75']] }], numCol);
  eq('a PLAIN numeric string is sent as a NUMBER, so =SUM over it is not 0',
     plain.filter(r => r.k === 'set')[0].values, [[900], [320], [75]]);
  eq('…with NO number-format op, because General is already right for a bare number and '
     + 'writing one would flatten a format Debi had set herself',
     plain.filter(r => r.k === 'style').length, 0);
  check('…and NO `@` text-protection op either — that guard is for the values our rule '
        + 'refused to coerce, which is not this one',
        !plain.some(r => r.k === 'style' && r.set && r.set.n
                    && r.set.n.pattern === '@'), plain);
  check('…and this now AGREES with office_ops.parse_input, which has always stored the '
        + 'plain shape as a number with no format merge — the two lanes were disagreeing '
        + 'about every plain numeric string',
        /out\["v"\], out\["t"\] = co\["v"\], CV_NUMBER/.test(opsPy));
  const one = ooEditorOps([{ op: 'set', r: 2, c: 3, values: [['x']] }], null)
    .filter(r => r.k === 'set')[0];
  eq('…while a single cell is still a single cell, not a degenerate range', one.at, 'D3');
  /* THE OP GRAMMAR ALLOWS RAGGED ROWS (a short row means "nothing further along this
     one"), and handing a ragged array to a rectangular range is a second thing to get
     wrong — so the grid is PADDED with null, which is what the tier-1 writer already
     means by "leave that cell". */
  const rag = ooEditorOps([{ op: 'set', r: 0, c: 0,
                             values: [['a', 'b', 'c'], ['d']] }], null)
    .filter(r => r.k === 'set')[0];
  eq('a ragged grid is padded to the rectangle it claims', rag.at, 'A1:C2');
  eq('…with the EMPTY STRING in the cells the model did not name — not null, which the '
     + 'editor turns into #N/A', rag.values, [['a', 'b', 'c'], ['d', '', '']]);
  check('and the child counts what it was SENT, which is only honest because the range '
        + 'now matches the array',
        /done\.cells \+= \(row \|\| \[\]\)\.length/.test(
          fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'oo.html'), 'utf8')));
}

const OO_STYLE_KEYS = JSON.parse('[' + (code.match(/const OO_STYLE_KEYS = \[([\s\S]*?)\];/)[1]
  .replace(/'/g, '"').replace(/\s+/g, ' ')) + ']');

// ── the routing decision ──
{
  const P = ooOpPlan([{ op: 'set', r: 0, c: 0, values: [['a']] }]);
  eq('a `set` runs in the editor', [P.route, P.api, P.rows[0].how], ['api', 1, 'api']);
}
{
  const P = ooOpPlan([{ op: 'style', r0: 0, c0: 0, r1: 0, c1: 0,
                        set: { bl: 1, bg: { rgb: '#ffffff' }, n: { pattern: '0.00' } } }]);
  eq('a `style` whose every key has an ApiRange setter runs in the editor too',
     [P.route, P.rows[0].how], ['api', 'api']);
}
{
  // ⚠️ THE FENCE THAT MATTERS: a style key the editor cannot set must not be silently
  // DROPPED (a formatting change that looks applied and is not), so the whole plan
  // takes the file route instead.
  const P = ooOpPlan([{ op: 'style', r0: 0, c0: 0, r1: 0, c1: 0,
                        set: { bl: 1, zz: 9 } }]);
  eq('a `style` carrying a key with NO editor setter sends the plan through the file',
     [P.route, P.rows[0].how], ['bridge', 'bridge']);
  check('…and says which key it was, so the card can print a reason rather than a shrug',
        /zz/.test(P.rows[0].why));
}
{
  // Checked against the vendored bundle, not assumed: sdkjs/cell has no ApiRange.Sort
  // and no ApiWorksheet.Sort. So `sort` is the one op with no honest API equivalent.
  const P = ooOpPlan([{ op: 'sort', col: 0, desc: false }]);
  eq('a `sort` has no builder-API equivalent, so it goes through the file',
     [P.route, P.bridge, P.rows[0].how], ['bridge', 1, 'bridge']);
  check('…and the reason names the editor rather than blaming the user',
        /no sort in its API/.test(P.rows[0].why));
}
{
  // A resize sizes TIER 1's render window. The real editor already has every row and
  // column, so there is nothing to do — and "nothing to do" is reported as a SKIP with
  // its reason, not counted as a change that happened.
  const P = ooOpPlan([{ op: 'resize', rows: 500, cols: 40 }]);
  eq('a `resize` is a SKIP, and it does NOT drag the plan onto the file route',
     [P.route, P.skip, P.bridge, P.rows[0].how], ['api', 1, 0, 'skip']);
  check('…with the honest reason', /every row and column/.test(P.rows[0].why));
}
{
  const P = ooOpPlan([{ op: 'sheet', add: 'Q1' },
                      { op: 'insert', axis: 'row', at: 2, n: 3 },
                      { op: 'delete_rc', axis: 'col', at: 1, n: 2 }]);
  eq('sheet / insert / delete_rc all run in the editor',
     [P.route, P.api, P.rows.map(r => r.how)],
     ['api', 3, ['api', 'api', 'api']]);
}
{
  // ⚠️ ALL-OR-NOTHING. A plan half-applied through the API and half through a file
  // round-trip is exactly the silent partial apply this block exists to prevent, so
  // ONE bridge op takes the WHOLE plan with it.
  const P = ooOpPlan([{ op: 'set', r: 0, c: 0, values: [['a']] },
                      { op: 'sort', col: 0, desc: true },
                      { op: 'set', r: 1, c: 0, values: [['b']] }]);
  eq('one op the editor cannot do sends the WHOLE plan through the file',
     [P.route, P.api, P.bridge], ['bridge', 2, 1]);
}
eq('an unknown op is routed to the file rather than assumed harmless',
   ooOpPlan([{ op: 'nonsense' }]).route, 'bridge');
[undefined, null, 0, '', 'x', {}, [[]], [null], [undefined], [{ op: null }]].forEach((v, i) => {
  let threw = null, r = null;
  try { r = ooOpPlan(v); } catch (e) { threw = e; }
  check('ooOpPlan is TOTAL over junk (case ' + i + ')',
        !threw && r && (r.route === 'api' || r.route === 'bridge'), threw);
});
check('…and it is PURE: no DOM, no page state, nothing but its argument',
      !/document\.|\bel\(|\bsnap\b|dirty|\bbx\(/.test(grab('ooOpPlan')));

// ── the translation to the editor's own addresses ──
/* ⚠️ THIS CHECK PINNED THE ANCHOR, AND THE ANCHOR WAS THE BUG (loffice-2026-08-28d
   adversarial self-pass, measured live in a real editor). ApiRange.SetValue writes an
   array ACROSS ITS OWN RANGE, so `at: 'F1'` handed a 2×2 grid stored ONE cell and dropped
   the rest in silence — while the child counted every value and the card stamped "4
   written". See the ooEditorOps rectangle block above for the side-by-side measurement.
   The three eq()s further down had the same anchor baked in for the same reason. */
eq('a `set` becomes the A1 RECTANGLE its values fill, and the same grid of values',
   ooEditorOps([{ op: 'set', r: 0, c: 5, values: [['x', 1], [null, true]] }]),
   [{ k: 'set', at: 'F1:G2', values: [['x', 1], ['', true]] }]);
eq('a `style` becomes an A1 RANGE and the style dict untouched',
   ooEditorOps([{ op: 'style', r0: 1, c0: 1, r1: 3, c1: 2, set: { bl: 1 } }]),
   [{ k: 'style', at: 'B2:C4', set: { bl: 1 } }]);
eq('a one-cell style range is still a range, so the editor gets one shape not two',
   ooEditorOps([{ op: 'style', r0: 0, c0: 0, r1: 0, c1: 0, set: { it: 1 } }])[0].at,
   'A1:A1');
eq('adding a sheet', ooEditorOps([{ op: 'sheet', add: 'Q1' }]),
   [{ k: 'addSheet', name: 'Q1' }]);
eq('renaming one carries the target NAME, which is the only handle a model has',
   ooEditorOps([{ op: 'sheet', rename: 'New', at: 'Old' }]),
   [{ k: 'renameSheet', name: 'New', at: 'Old' }]);
eq('…and an unnamed rename means "this sheet"',
   ooEditorOps([{ op: 'sheet', rename: 'New' }])[0].at, '');
// Rows are 1-based ranges and columns are letter ranges, because that is what
// ApiWorksheet.GetRows()/GetCols() take. An off-by-one here inserts in the wrong place
// and is invisible until somebody's data has moved, so the arithmetic is executed.
eq('inserting 3 rows at row index 2 is the 1-based range 3:5',
   ooEditorOps([{ op: 'insert', axis: 'row', at: 2, n: 3 }]),
   [{ k: 'insertRows', n: 3, at: '3:5' }]);
eq('inserting 1 row at row index 0 is 1:1',
   ooEditorOps([{ op: 'insert', axis: 'row', at: 0, n: 1 }])[0].at, '1:1');
eq('deleting 2 columns at column index 1 is B:C',
   ooEditorOps([{ op: 'delete_rc', axis: 'col', at: 1, n: 2 }]),
   [{ k: 'deleteCols', n: 2, at: 'B:C' }]);
eq('…and the 26 boundary is the same colName the grid draws with',
   ooEditorOps([{ op: 'insert', axis: 'col', at: 26, n: 1 }])[0].at, 'AA:AA');
eq('a `resize` produces NOTHING — it was already reported as a skip',
   ooEditorOps([{ op: 'resize', rows: 9, cols: 9 }]), []);
check('ooEditorOps is PURE too',
      !/document\.|\bel\(|\bsnap\b|dirty|\bbx\(/.test(grab('ooEditorOps')));
// The two must agree about which ops the editor path runs: an op ooOpPlan calls 'api'
// and ooEditorOps drops would be a change the card promised and nobody made.
{
  const ops = [{ op: 'set', r: 0, c: 0, values: [['a']] },
               { op: 'style', r0: 0, c0: 0, r1: 0, c1: 0, set: { bl: 1 } },
               { op: 'sheet', add: 'S' },
               { op: 'insert', axis: 'row', at: 0, n: 1 },
               { op: 'delete_rc', axis: 'row', at: 5, n: 1 }];
  eq('every op ooOpPlan routes to the editor is one ooEditorOps can express — the card '
     + 'must not promise a change nobody makes',
     ooEditorOps(ops).length, ooOpPlan(ops).api);
}

// ── the style keys, against the page's own mapper ──
// ⚠️ THIS IS THE ONE THAT WOULD CATCH A REAL SILENT BUG: actStyleSet decides which keys
// a plan may carry, ooOpPlan decides which keys the editor can set. If actStyleSet ever
// grows a key that OO_STYLE_KEYS does not have, every style op quietly starts taking the
// heavier file route — and if OO_STYLE_KEYS has one the editor cannot set, formatting
// silently does not happen. So the two lists are compared.
{
  const emitted = Object.keys(actStyleSet({
    bl: 1, it: 1, ul: 1, st: 1, ff: 'Arial', fs: 12, cl: '#112233', bg: '#445566',
    ht: 'center', vt: 'middle', tb: 3, n: { pattern: '0.00' },
  }) || {}).sort();
  eq('actStyleSet emits exactly the keys the editor path knows how to set',
     emitted, OO_STYLE_KEYS.slice().sort());
}
const OOH = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'oo.html'), 'utf8');
const OOSTYLE = grabFrom(OOH, 'ooStyle', 'oo.html');
OO_STYLE_KEYS.forEach(k => {
  check("the editor page really handles the style key '" + k + "'",
        new RegExp('set\\.' + k + '\\b').test(OOSTYLE));
});

// ── and the apply itself: no page-side undo, and it says so ──
{
  const oa = stripComments(grab('ooActApply'));
  check('the editor apply takes NO page-side undo entry — histPush clones the tier-1 '
        + 'snapshot, which is not the document you are looking at, so an Undo built on '
        + 'it would restore a workbook the editor never had',
        !/histPush/.test(oa) && /card\._undo = false;/.test(oa)
        && /actLast = null;/.test(oa));
  check('…and the card is told WHICH route ran, because the two have different truths '
        + 'about whether the file is already saved',
        /card\._viaEditor/.test(oa) && /card\._viaBridge/.test(oa));
  check('…and a failure names the op and points at the editor\'s own ⌘Z rather than '
        + 'claiming a rollback this page cannot perform',
        /r\.error/.test(oa) && /steps back through them/.test(grab('ooActApply')));
  check('…and it writes no cell of its own: the two routes are the editor\'s API and '
        + 'the page\'s ONE existing writer',
        !/\bputCell\s*\(/.test(oa));
  const ap = stripComments(grab('actApply'));
  check('actApply hands over to it on the FIRST decision, before it takes an undo '
        + 'clone or touches the snapshot',
        ap.indexOf('ooActApply') > 0
        && ap.indexOf('ooActApply') < ap.indexOf('histPush'));
  check('…and the interstitial is refused rather than raced: an Apply landing while the '
        + 'editor is still opening would write into a snapshot it is about to replace',
        /ooInstalled && ooBooting/.test(ap));
}
{
  // The file route is the one that must not lie: it saves immediately, the editor's ⌘Z
  // does not cover it, and it round-trips through our own .xlsx mapper.
  const ob = grab('ooApplyBridge');
  check('the file route saves the EDITOR first — the file is about to be rewritten '
        + 'underneath it, and unsaved editor edits would simply vanish',
        ob.indexOf('ooSave(false)') < ob.indexOf('/api/office/open/'));
  check('…refuses the whole thing if that save failed, changing nothing',
        /nothing was changed/.test(ob));
  check('…runs the ops through actRunOps, the SAME writer the menu gestures use, so '
        + 'there is no second idea of what a sort means',
        /actRunOps\(sid, plan\.ops\)/.test(ob));
  check('…and reloads the DOCUMENT afterwards, not the page',
        /ooReload\('ai-apply'\)/.test(ob) && !/location\.(href|reload)/.test(ob));
  check('…and the note it adds names all three ways this route differs: it saves '
        + 'straight away, the editor\'s ⌘Z does not undo it, and the round-trip drops '
        + 'charts and images',
        /saved straight away/.test(ob) && /⌘Z does not/.test(ob)
        && /charts or images/.test(ob));
}

// ── the writer fence, extended to the one-editor functions ──
/* ⚠️ THE FENCE DID NOT GROW, AND THAT IS THE CLAIM. The restructure added a dozen
   functions and NOT ONE of them writes a cell: the editor path writes through the
   editor's own API (inside the iframe, in the editor's undo stack), and the file path
   goes through actRunOps — which was already in the list of seven. So the complete
   writer set asserted in PART 4 is unchanged, and these are the per-function
   assertions that make that a fact rather than a hope. */
{
  const S3 = ['editorActive', 'ooPaintClass', 'ooEvent', 'ooProbe', 'ooStart', 'ooSave',
              'ooReload', 'ooRefreshSnapshot', 'ooOpPlan', 'ooEditorOps', 'ooApplyApi',
              'ooApplyBridge', 'ooActApply', 'ooExtReload', 'upgrade'];
  check('every function the one-editor slice added is actually IN the page — a vacuous '
        + 'fence is no fence', S3.every(n => fnNames.indexOf(n) >= 0),
        S3.filter(n => fnNames.indexOf(n) < 0));
  check('and NOT ONE of them writes a cell', S3.every(n => !/\bputCell\s*\(/.test(grab(n))),
        S3.filter(n => /\bputCell\s*\(/.test(grab(n))));
  eq('…and the ONLY ones that touch the dirty flag are the three that carry the '
     + 'editor\'s own answer about it',
     S3.filter(n => /\bdirty = (true|false)\b/.test(stripComments(grab(n)))).sort(),
     ['ooActApply', 'ooEvent']);
  check('the two PURE routing functions touch no page state at all, which is why the '
        + 'route can be printed on the card before anything is applied',
        ['ooOpPlan', 'ooEditorOps'].every(n => {
          const b = stripComments(grab(n));
          return !/document\.|\bel\(|\bsnap\b|dirty|\bbx\(|ooChild/.test(b);
        }));
  check('and the predicate is the only thing the hide/show fork reads — no second '
        + 'version of "is the editor up" anywhere in the page',
        (code.match(/classList\.toggle\('ooedit'/g) || []).length === 1
        && (code.match(/function editorActive\(\)/g) || []).length === 1);
}

/* ══ 7. TYPE HONESTY — THE 2026-08-28 INCIDENT, PINNED ON THE PAGE SIDE ════════
   (loffice-2026-08-28d)

   WHAT HAPPENED, in one sentence: Debi's budget was staged as the strings "$2,500",
   "$400", …; our writers stored them verbatim as TEXT; her "sum it up" produced a
   perfectly correct =SUM(B2:B12) over twelve text cells, which every spreadsheet engine
   computes as 0; and nothing anywhere said a word. Four layers were silent, and this
   block is the page's half of all four:

     1. THE WRITERS COERCE. A numeric-shaped string becomes the NUMBER plus a number
        format — the same thing typing it into Excel does — unless intent says otherwise.
     2. INTENT ALWAYS WINS. A leading apostrophe, or "as_text": true on the op.
     3. CONTEXT DECIDES THE REST, AUTOMATICALLY. No question is ever put to Debi.
     4. IT IS ALL VISIBLE. The card shows every coercion and every kept-as-text value; the
        sheet the model is sent QUOTES text that looks numeric; and after an apply that
        wrote formulas the receipt says what the editor actually computed.

   ⚠️ THE COERCION TABLE BELOW IS THE SAME TABLE bridge/tests/test_office_journey.py
   walks in PYTHON, value for value. That is the pin that keeps the two implementations
   from drifting — which matters because a drifting rule means the same budget is numbers
   on one lane and text on the other. If you change one, the other fails. */
{
  // ── 7a. the accepted shapes, and the refused ones ──
  // [input, value, pattern-or-null] — coerced; or [input, null] — stays TEXT.
  const CO = [
    ['$2,500', 2500, '$#,##0'], ['$400', 400, '$#,##0'],
    ['$400.50', 400.5, '$#,##0.00'], ['$0.99', 0.99, '$#,##0.00'],
    ['-$5', -5, '$#,##0'], ['$-5', -5, '$#,##0'], ['$ 2,500', 2500, '$#,##0'],
    ['2,500', 2500, '#,##0'], ['1,234,567.89', 1234567.89, '#,##0.00'],
    ['50%', 0.5, '0%'], ['12.5%', 0.125, '0.0%'], ['-3%', -0.03, '0%'],
    ['1,000%', 10, '0%'], ['0%', 0, '0%'],
    ['1234', 1234, null], ['-12.5', -12.5, null], ['.5', 0.5, null], ['0.5', 0.5, null],
    // AND THE REFUSALS, which are the half that protects a document:
    ['007', null], ['-007', null], ['$007', null], ['1e5', null], ['0x10', null],
    ['1,23', null], ['12,3456', null], ['(2,500)', null], ['(555) 010-1234', null],
    ['$2,500-B', null], ['2500 kr', null], ['2500 USD', null],
    ['€1.234,56', null], ['£5', null], ['¥500', null], ['1 234,56', null],
    ['', null], ['   ', null], ['hello', null],
    ['$1234567890123456789012345678901234', null],   // past CO_MAX_LEN
  ];
  CO.forEach(row => {
    const got = coerceNumeric(row[0]);
    if (row[1] === null) {
      eq('coerceNumeric leaves ' + JSON.stringify(row[0]) + ' as TEXT', got, null);
    } else {
      eq('coerceNumeric ' + JSON.stringify(row[0]), got && [got.v, got.n],
         [row[1], row[2]]);
    }
  });
  check('coerceNumeric is TOTAL — junk costs the coercion, never a throw',
        [null, undefined, {}, [], 0, NaN, true].every(v => {
          try { coerceNumeric(v); return true; } catch (e) { return false; }
        }));
  check('EVERY non-$ currency and every non-US locale is refused, and that is a scope '
        + 'decision written down rather than an oversight: "€1.234,56" is 1234.56 in '
        + 'Germany and nonsense elsewhere, and guessing turns a thousands separator into '
        + 'a decimal point — a budget wrong by a factor of a thousand, silently',
        ['€1.234,56', '£5', '¥500', 'CHF 5', 'R$ 5', '5 kr', '1 234,56', '2 500']
          .every(s => coerceNumeric(s) === null));

  // ── 7b. intent overrides everything ──
  // ⚠️ NO LOCAL `snap` HERE. actRunOps and mergeFormat were eval'd at MODULE scope and
  // close over the module-level `snap`; a block-scoped one would shadow it for this test
  // only and the writers would keep reading the old one — a test that measures nothing.
  snap = null;
  eq('a leading apostrophe stores the text verbatim, apostrophe stripped — the convention '
     + 'every spreadsheet user already knows',
     parseInput("'$2,500", null), { v: '$2,500', t: CV_STRING });
  eq('…it beats the formula rule too', parseInput("'=SUM(A1)", null),
     { v: '=SUM(A1)', t: CV_STRING });
  eq('…and the boolean rule', parseInput("'true", null), { v: 'true', t: CV_STRING });
  eq('TWO apostrophes are a value that starts with ONE', parseInput("''x", null),
     { v: "'x", t: CV_STRING });
  eq('a BARE apostrophe is an EMPTY TEXT cell, not an emptied one — Excel\'s own '
     + 'behaviour, and the distinction matters because \' must not clear a cell',
     parseInput("'", null), { v: '', t: CV_STRING });
  eq('asText stores the string verbatim without coercing',
     parseInput('$2,500', null, true), { v: '$2,500', t: CV_STRING });
  eq('…and a coerced value carries the number format on its own style',
     parseInput('$2,500', null), { v: 2500, t: CV_NUMBER, n: undefined }.v === 2500
       ? parseInput('$2,500', null) : null,
     { v: 2500, t: CV_NUMBER, s: { n: { pattern: '$#,##0' } } });
  eq('…MERGED with the style that was already there, never replacing it — writing a '
     + 'number into a bold red cell must not strip the bold red',
     parseInput('$2,500', { s: { bl: 1, cl: { rgb: '#ff0000' } } }).s,
     { bl: 1, cl: { rgb: '#ff0000' }, n: { pattern: '$#,##0' } });
  eq('a PLAIN number gets no pattern: General is already right, and writing one over it '
     + 'would flatten a cell Debi had formatted herself',
     parseInput('1234', null), { v: 1234, t: CV_NUMBER });

  // ── 7c. the contextual inference — automatic, and never a question ──
  function sheetWith(cells, header) {
    const cd = {};
    if (header) cd['0'] = { '1': { v: header, t: CV_STRING } };
    (cells || []).forEach((v, i) => {
      cd[String(i + 1)] = { '1': typeof v === 'number' ? { v: v, t: CV_NUMBER }
                                                       : { v: v, t: CV_STRING } };
    });
    return { name: 'S', cellData: cd };
  }
  const money = setContext(sheetWith([]), { r: 0, c: 0,
    values: [['Item', 'Planned'], ['Rent', '$2,500'], ['Groceries', '$400']] });
  check('a "Planned" column of money strings resolves to NUMBERS — the incident\'s own '
        + 'column, decided correctly and silently', money[1].numeric === true);
  const band = setContext(sheetWith([]), { r: 0, c: 0,
    values: [['Product', 'Price band code'], ['X', '$2,500']] });
  check('a "Price band code" column resolves to TEXT: two text words outvote one numeric '
        + 'one, and the header is a hint that is COMBINED rather than obeyed',
        band[1].numeric === false);
  check('a "SKU" column resolves to TEXT', setContext(sheetWith([]),
    { r: 0, c: 0, values: [['SKU'], ['$2,500']] })[0].numeric === false);
  check('an "Amount" column resolves to NUMBERS', setContext(sheetWith([]),
    { r: 0, c: 0, values: [['Amount'], ['$2,500']] })[0].numeric === true);
  check('NO header and nothing else to go on resolves to NUMBERS — the default lean, '
        + 'because typing $2,500 into any spreadsheet gives you a number',
        setContext(sheetWith([]), { r: 0, c: 0, values: [['$2,500'], ['$400']] })[0]
          .numeric === true);
  check('a column that ALREADY holds text outvotes the default lean',
        setContext(sheetWith(['AB-1', 'AB-2', 'AB-3'], 'Ref'),
                   { r: 4, c: 1, values: [['$2,500']] })[1].numeric === false);
  check('…and a column that already holds NUMBERS keeps them, even under a vague header',
        setContext(sheetWith([100, 200, 300], 'Ref'),
                   { r: 4, c: 1, values: [['$2,500']] })[1].numeric === true);
  /* ⚠️⚠️ THE CIRCULARITY GUARD, AND IT IS THE ONE ASSERTION IN THIS BLOCK MOST WORTH
     READING. Signal A asks "do this column's other values read as numbers?" — and if a
     COERCIBLE STRING counted as a yes, then a column of nothing but "$2,500"-shaped
     strings would always vote to coerce itself, signal A would be a rubber stamp, and
     the header and sheet signals could never outvote it. So a coercible string is worth
     ZERO there; only a JSON number (+1) or unambiguous prose (-1) speaks. */
  eq('a coercible STRING is worth zero as evidence about its own column (the '
     + 'circularity guard)', shapeLean('$2,500'), 0);
  eq('…a JSON NUMBER is +1: the model was explicit and that is real evidence',
     shapeLean(2500), 1);
  eq('…prose is -1', shapeLean('Rent'), -1);
  eq('…an apostrophe-marked value is -1: it SAYS text', shapeLean("'$2,500"), -1);
  eq('…a formula types itself and votes on nothing', shapeLean('=SUM(A1:A2)'), 0);
  eq('a header with one word each way nets out to NO signal rather than to a coin toss',
     headerLean('Invoice amount'), 0);
  check('header matching is on WHOLE WORDS, so "Bandwidth" is not "band" and '
        + '"Identifier" is not "id"',
        headerLean('Bandwidth') === 0 && headerLean('Identifier') === 0);
  check('setContext is TOTAL over junk', [null, undefined, {}, { values: [] }]
    .every(o => { try { setContext(null, o); return true; } catch (e) { return false; } }));

  // ── 7d. the writers agree with the decision, and RECORD it ──
  {
    snap = { styles: {}, sheetOrder: ['s1'],
             sheets: { s1: { id: 's1', name: 'S', cellData: {}, rowCount: 20,
                             columnCount: 8 } } };
    let activeSid = 's1';
    const done = actRunOps('s1', [
      { op: 'set', r: 0, c: 0,
        values: [['Item', 'Planned'], ['Rent', '$2,500'], ['Groceries', '$400']] },
      { op: 'set', r: 0, c: 3, values: [['Phone'], ['(555) 010-1234']] },
      { op: 'set', r: 0, c: 4, as_text: true, values: [['Band'], ['$2,500']] }]);
    eq('the money column was stored as NUMBERS with the currency format',
       [snap.sheets.s1.cellData['1']['1'], snap.sheets.s1.cellData['2']['1']],
       [{ v: 2500, t: CV_NUMBER, s: { n: { pattern: '$#,##0' } } },
        { v: 400, t: CV_NUMBER, s: { n: { pattern: '$#,##0' } } }]);
    eq('the phone number was never a candidate — a shape with residue cannot coerce at '
       + 'all, with or without a flag',
       snap.sheets.s1.cellData['1']['3'], { v: '(555) 010-1234', t: CV_STRING });
    eq('as_text kept the money-shaped string verbatim',
       snap.sheets.s1.cellData['1']['4'], { v: '$2,500', t: CV_STRING });
    eq('…and every coercion was RECORDED where it happened, so the card can say it',
       done.coerced.map(c => [c.ref, c.raw, c.v, c.n]),
       [['B2', '$2,500', 2500, '$#,##0'], ['B3', '$400', 400, '$#,##0']]);
    check('…and it is SAID in the notes, not left for someone to notice',
          done.notes.some(n => /stored as real NUMBERS/.test(n)
                            && /B2 "\$2,500" → 2500 \(\$#,##0\)/.test(n)));
  }
  {
    snap = { styles: {}, sheetOrder: ['s1'],
             sheets: { s1: { id: 's1', name: 'S', cellData: {}, rowCount: 20,
                             columnCount: 8 } } };
    const done = actRunOps('s1', [{ op: 'set', r: 0, c: 0,
      values: [['SKU'], ['$2,500']] }]);
    eq('a numeric-shaped string in a column the context reads as TEXT stays text',
       snap.sheets.s1.cellData['1']['0'], { v: '$2,500', t: CV_STRING });
    eq('…and the reason is recorded rather than turned into a question for Debi',
       done.keptText.length === 1 && /reads as an identifier/.test(done.keptText[0].why),
       true);
    check('…and said in the notes', done.notes.some(n => /kept as TEXT/.test(n)));
  }

  // ── 7e. the editor route stores numbers too, with the format grouped ──
  eq('ooEditorOps sends the NUMBER to SetValue, not the string — so the cell holds 2500 '
     + 'with $#,##0 whatever the editor\'s own SetValue does with "$2,500"',
     ooEditorOps([{ op: 'set', r: 1, c: 1,
                    values: [['$2,500'], ['$400'], ['$200']] }], sheetWith([], 'Planned')),
     [{ k: 'set', at: 'B2:B4', values: [[2500], [400], [200]] },
      { k: 'style', at: 'B2:B4', set: { n: { pattern: '$#,##0' } } }]);
  eq('…the format ops are GROUPED into rectangles, so a column of twelve amounts is one '
     + 'SetNumberFormat call and not twelve',
     ooEditorOps([{ op: 'set', r: 0, c: 0,
                    values: [['$1', '$2'], ['$3', '$4']] }], null)
       .filter(o => o.k === 'style').length, 1);
  eq('…two different formats are two ops, never one wrong one',
     ooEditorOps([{ op: 'set', r: 0, c: 0, values: [['$1'], ['50%']] }], null)
       .filter(o => o.k === 'style').map(o => o.set.n.pattern).sort(),
     ['$#,##0', '0%']);
  /* ⚠️⚠️ THE EDITOR HAS ITS OWN PARSER, AND IT IS NOT OURS. MEASURED IN THE REAL
     VENDORED EDITOR (ONLYOFFICE v9.2.0.119+3 — and still true at +5: sdkjs/cell/sdk-all-min.js is a BYTE-IDENTICAL file between the two tags, verified 2026-08-28) on 2026-08-28, not assumed:
         SetValue("$2,500") → 2500 shown "$2,500"   · agrees with us
         SetValue("50%")    → 0.5  shown "50%"      · agrees with us
         SetValue("2,500")  → 2500 shown "2,500"    · agrees with us
         SetValue("007")    → 7                     · ⚠️ DESTROYS THE LEADING ZERO
     The last one is silent data loss on a column of ids — the exact thing our own rule
     refuses to do — so a value we are storing AS TEXT cannot simply be handed over. The
     fix, also measured in the real editor: set the Text format ("@") on the cell FIRST
     and SetValue stores the string verbatim. These are the assertions that keep it. */
  eq('…as_text emits the Text format BEFORE the write, so the editor\'s own parser cannot '
     + 'renumber a value the op said was verbatim text',
     ooEditorOps([{ op: 'set', r: 0, c: 0, as_text: true, values: [['$2,500']] }], null),
     [{ k: 'style', at: 'A1', set: { n: { pattern: '@' } } },
      { k: 'set', at: 'A1', values: [['$2,500']] }]);
  eq('…an apostrophe-marked value is sent as the STRIPPED text, protected the same way',
     ooEditorOps([{ op: 'set', r: 0, c: 0, values: [["'$2,500"]] }], null),
     [{ k: 'style', at: 'A1', set: { n: { pattern: '@' } } },
      { k: 'set', at: 'A1', values: [['$2,500']] }]);
  eq('…and a LEADING-ZERO ID is protected even though our rule never coerced it — this '
     + 'is the case the editor gets wrong on its own',
     ooEditorOps([{ op: 'set', r: 0, c: 0, values: [['Employee ID'], ['007']] }], null),
     [{ k: 'style', at: 'A2', set: { n: { pattern: '@' } } },
      { k: 'set', at: 'A1:A2', values: [['Employee ID'], ['007']] }]);
  eq('a value the inference kept as text is protected too',
     ooEditorOps([{ op: 'set', r: 0, c: 0, values: [['SKU'], ['$2,500']] }],
                 { name: 'S', cellData: {} }),
     [{ k: 'style', at: 'A2', set: { n: { pattern: '@' } } },
      { k: 'set', at: 'A1:A2', values: [['SKU'], ['$2,500']] }]);
  check('ooTextForce is NARROW: a label is in no danger from the editor\'s parser and '
        + 'must not have its number format rewritten',
        ['Rent', 'AB-100', 'Q1 2026', 'Groceries', ''].every(s => !ooTextForce(s)));
  check('…and it catches every shape the editor would swallow: leading zeros, phone '
        + 'numbers, accounting parens, bad grouping, exponent and hex',
        ['007', '0042', '(555) 010-1234', '(2,500)', '1,23', '1e5', '0x10', '$2,500']
          .every(s => ooTextForce(s)));
  eq('ooRects covers a single cell as a single ref', ooRects([{ r: 0, c: 0 }]), ['A1']);
  eq('…a row as a row, a column as a column',
     [ooRects([{ r: 0, c: 0 }, { r: 0, c: 1 }]),
      ooRects([{ r: 0, c: 0 }, { r: 1, c: 0 }])], [['A1:B1'], ['A1:A2']]);
  eq('…a block as ONE rectangle', ooRects([{ r: 0, c: 0 }, { r: 0, c: 1 },
     { r: 1, c: 0 }, { r: 1, c: 1 }]), ['A1:B2']);
  eq('…and an L shape as the fewest rectangles that cover it, never as one that covers '
     + 'a cell it was not given',
     ooRects([{ r: 0, c: 0 }, { r: 1, c: 0 }, { r: 1, c: 1 }]), ['A1:A2', 'B2']);

  // ── 7f. the grounding is TYPE-HONEST ──
  {
    const wb2 = { sheets: { s1: { name: 'S', cellData: {
      '0': { '0': { v: 'Item', t: CV_STRING }, '1': { v: 'Planned', t: CV_STRING } },
      '1': { '0': { v: 'Rent', t: CV_STRING }, '1': { v: '$2,500', t: CV_STRING } },
      '2': { '0': { v: 'Food', t: CV_STRING },
             '1': { v: 400, t: CV_NUMBER, s: { n: { pattern: '$#,##0' } } } },
      '3': { '1': { f: '=SUM(B2:B3)', v: 400, t: CV_NUMBER } },
    } } } };
    const c2 = buildContext(wb2, 's1', '', 'B.xlsx');
    /* ⚠️ THE THIRD SILENT LAYER. displayText renders the TEXT "$2,500" and the NUMBER
       400-formatted-as-$400 identically, so the model reading this grounding could not
       see the difference either. Quoting the text-typed one is the whole fix, and it is
       four characters of output. */
    check('a text cell that LOOKS numeric is QUOTED in the sheet the model is sent',
          /\t"\$2,500"/.test(c2.text));
    check('…a real number is BARE, so the two can be told apart at a glance',
          /\t400\b/.test(c2.text) && !/"400"/.test(c2.text));
    check('…a formula still shows its formula text', /=SUM\(B2:B3\)/.test(c2.text));
    check('…and ONE line of the legend explains the convention, because a quote nobody '
          + 'was told about is just a quote',
          /in "double quotes" is stored as TEXT/.test(c2.text)
          && /computes 0/.test(c2.text));
    check('prose is not quoted just because it is text', !/"Rent"/.test(c2.text));
  }

  // ── 7g. the card SHOWS the coercion, and never asks about it ──
  eq('a coerced row prints the STAGED STRING on the left and the stored number with its '
     + 'format on the right — "never a coercion the card didn\'t show"',
     csRow({ ref: 'B2', before: '', after: '2500', before_display: '',
             after_display: '2500 ($#,##0)', coerced: true, coerced_from: '$2,500' }),
     'B2  "$2,500"  →  2500 ($#,##0)');
  eq('a kept-as-text value prints QUOTED, which is how you tell the two apart',
     csRow({ ref: 'B2', before: '', after: '$2,500', before_display: '',
             after_display: '"$2,500"' }),
     'B2  (empty)  →  "$2,500"');
  eq('an older bridge with no *_display fields falls back to the raw faces rather than '
     + 'rendering blank', csRow({ ref: 'B2', before: 'x', after: 'y' }), 'B2  x  →  y');
  eq('the retyped values are their own short list, so a reader does not have to spot '
     + 'them among sixty diff rows',
     csTypeLines({ coerced: [{ ref: 'B2', raw: '$2,500', v: 2500, n: '$#,##0' }],
                   kept_text: [{ ref: 'D2', raw: '007', why: 'the header reads as an '
                                                          + 'identifier' }] }),
     ['B2  "$2,500"  →  2500 ($#,##0)  · stored as a number',
      'D2  "007"  · kept as text — the header reads as an identifier']);
  eq('nothing retyped draws nothing — a "0 values converted" line is noise',
     csTypeLines({}), []);
  /* ⚠️ NO QUESTION AND NO SECOND BUTTON (Debi's ruling). The aggregate-over-text
     condition is the MODEL's to fix, inside its own turn, from the instruction in its
     tool result. If a stale changeset still carries it, Debi is INFORMED. Apply stays
     one click, and the wording is the BRIDGE'S OWN sentence — two wordings of one fact
     is how one of them goes stale. */
  eq('the aggregate-over-text line is carried through from the bridge verbatim',
     csWarnLines({ warnings: [{ sentence: '⚠ B2:B12 hold text that looks numeric, so '
                                        + 'this SUM will compute 0 as written.' }] }),
     ['⚠ B2:B12 hold text that looks numeric, so this SUM will compute 0 as written.']);
  eq('no warnings, no line', csWarnLines({}), []);
  check('the card renders it ABOVE the collapsed detail blocks — the one thing here that '
        + 'changes what the change MEANS must not be behind a disclosure',
        (() => { const b = grab('csCard');
                 return b.indexOf('csWarnLines') < b.indexOf('what it will change'); })());
  check('…and it adds NO button and asks NO question: the card\'s only controls are '
        + 'still Apply and Dismiss',
        (grab('csCard').match(/actChip\(/g) || []).length === 2);
  check('the card does not put a type decision to the user anywhere',
        !/your call|which is it|is this a number|Convert\?/i
          .test(stripComments(grab('csCard')) + stripComments(grab('csWarnLines'))
                + stripComments(grab('csTypeLines'))));

  // ── 7h. the post-apply COMPUTED check — the only formula engine we have ──
  /* ⚠️ NOTHING BRIDGE-SIDE HAS ONE. "=SUM(B2:B12)" goes into the .xlsx as text and comes
     back as text, so the receipt's re-read can only ever say "the formula is in the
     cell" — which is exactly what it said on 2026-08-28 while the cell displayed 0. The
     EDITOR has just recalculated the document it reloaded, so it is asked. */
  eq('a computed total reads as a tick', csComputedText(
     [{ ref: 'B13', value: 4735, text: '$4,735', formula: '=SUM(B2:B12)' }], false).line,
     'computed: B13=$4,735 ✓');
  eq('a ZERO is flagged — a total that came out 0 is the incident\'s own signature, and '
     + 'this receipt never lets one past unmarked', csComputedText(
     [{ ref: 'B13', value: 0, text: '0' }], false).bad, 1);
  check('…and when the dry-run had WARNED about that range, the line says that is what '
        + 'the 0 means rather than leaving Debi to connect it',
        /warned that this range holds text/.test(
          csComputedText([{ ref: 'B13', value: 0, text: '0' }], true).line));
  check('a #VALUE!/#DIV/0! result is flagged too',
        csComputedText([{ ref: 'B13', text: '#DIV/0!' }], false).bad === 1);
  check('an unreadable cell costs that ROW and not the receipt',
        csComputedText([{ ref: 'B13', error: 'nope' },
                        { ref: 'C13', value: 5, text: '5' }], false).bad === 1);
  check('csComputedText is TOTAL', [null, undefined, {}, 'x', [null]].every(v => {
    try { csComputedText(v, false); return true; } catch (e) { return false; } }));
  {
    const cc = stripComments(grab('csComputed'));
    check('it only asks about cells whose staged value was a FORMULA — there is nothing '
          + 'to compute for a plain number',
          /expected\) \|\| ''\)\.charAt\(0\) === '='/.test(cc));
    check('⚠️ IT RUNS AFTER THE RELOAD, which is the whole correctness argument: reading '
          + 'before onDocumentReady would report the OLD document\'s values as the new '
          + 'ones — a confident wrong number, which is worse than no number',
          /await ooExtReload\(j\.name\);[\s\S]{0,400}await csComputed\(/
            .test(stripComments(grab('csApply'))));
    check('…and it is HONEST when there is no engine to ask (tier 1, or an older embed '
          + 'frame) rather than reporting nothing at all',
          /editorActive\(\)/.test(cc) && /typeof ooChild\.readCells !== 'function'/.test(cc)
          && /CS_NO_ENGINE/.test(cc));
    check('…it never writes: the editor call is a GETTER',
          /ooChild\.readCells\(/.test(cc) && !/applyOps|SetValue/.test(cc));
  }
  // The embed contract's own half: readCells exists, is a getter, and the version moved.
  {
    const oo = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'oo.html'), 'utf8');
    check('bridge/panel/oo.html exposes readCells on the parent contract',
          /readCells: readCells/.test(oo) && /function readCells\(refs, sheetName\)/.test(oo));
    // ⚠️ 2 → 3 AT loffice-2026-08-28d (`renameTo`, live finding B1); 3 → 4 AT
    // loffice-2026-08-29a (`downloadPdf`, the PDF export that replaces Print).
    check('…the contract version moved with it, so an older frame is detectable',
          /contract: 4/.test(oo));
    check('…and the new member is the PDF export, published as a FUNCTION so an older '
          + 'frame degrades to a sentence instead of a silent nothing',
          /downloadPdf: downloadPdf/.test(oo)
          && /typeof ooChild\.downloadPdf !== 'function'/.test(html));
    /* ⚠️⚠️ THE TWO HALVES OF live finding L1, PINNED IN THE EMBED WHERE THEY LIVE. The
       vendored header's own floppy-disk Save ran sdkjs's DocumentServer save, which arrives
       at the mock server as `saveChanges`; we ACKed it and did nothing else, so sdkjs
       considered the document saved and fired onDocumentStateChange(false) → the parent
       cleared THE dirty flag that guards every discard path → the strip said "all changes
       saved" with the FILE UNTOUCHED (mtime identical before and after) → the next rail
       click found dirty === false and swapped with no warning at all. The work was gone,
       two clicks apart. */
    check('L1a: the editor\'s OWN save gesture is routed into the write-back, so the only '
          + 'Save control in the window that looks like it writes the file actually does',
          /t === 'saveChanges'/.test(oo) && /extSaves\+\+/.test(oo)
          && /save\(false\)/.test(oo));
    check('…and it cannot re-enter our own save, which does not come through there',
          /if \(!saving && ready\)/.test(oo));
    check('L1b: a dirty:false that NO write-back produced is refused rather than '
          + 'forwarded — the floor under L1a, and the half that keeps us honest if that '
          + 'route is ever unreachable',
          /if \(!d && dirtyNow && !saving\)/.test(oo)
          && /heldClears\+\+/.test(oo)
          && /tell\('state', \{dirty: true\}\)/.test(oo));
    check('…and BOTH are countable off probe(), so the fix is measurable rather than '
          + 'inferred', /extSaves: extSaves/.test(oo) && /heldClears: heldClears/.test(oo));
    /* live finding B1: rename a workbook while the editor holds it and the next save
       posted to the OLD name, got a 404, and the unsaved work could never be written by
       any route at all. */
    check('B1: the embed can be re-pointed at a new name WITHOUT re-opening the file, so a '
          + 'rename cannot cost the unsaved edits it deliberately keeps',
          /renameTo: renameTo/.test(oo) && /function renameTo\(to\)/.test(oo)
          && !/function renameTo\(to\)[\s\S]{0,400}openDoc\(/.test(oo));
    check('…and the parent calls it on a successful rename, probing for the FUNCTION',
          /typeof ooChild\.renameTo === 'function'/.test(code)
          && /ooChild\.renameTo\(j\.name\)/.test(code));
    check('…and an embed too old to be told says so instead of leaving a Save that will '
          + '404 looking like a Save that will work',
          /too old to be told/.test(code));
    check('…and the parent probes for the FUNCTION, not the number — a version check that '
          + 'gates a capability the object plainly has is a way to break a working page',
          /typeof ooChild\.readCells !== 'function'/.test(code));
    check('…readCells only READS: GetValue/GetText/GetFormula and no setter',
          /GetValue\(\)/.test(oo) && /GetText\(\)/.test(oo)
          && !/readCells[\s\S]{0,1200}SetValue/.test(oo));
    /* ⚠️ THE BUNDLE ITSELF IS CHECKED WHEN IT IS ON THIS MACHINE, and skipped honestly
       when it is not — the ONLYOFFICE install is a 3 GB optional component, so a test
       that REQUIRED it would fail on every clean checkout and get disabled, which is
       worse than a check that says what it did. `readCells` names these four getters as
       "grepped, not assumed"; this is the grep. */
    const bundle = path.join(process.env.HOME || '', 'Library', 'Application Support',
                             'Harness', 'data', 'onlyoffice', 'dist', 'v9', 'sdkjs',
                             'cell', 'sdk-all.js');
    if (fs.existsSync(bundle)) {
      const sdk = fs.readFileSync(bundle, 'utf8');
      check('…and every getter readCells uses IS present in the vendored sdkjs/cell '
            + 'bundle on this machine — grepped, not assumed',
            ['GetValue', 'GetText', 'GetFormula']
              .every(g => sdk.indexOf('ApiRange.prototype.' + g) > 0));
    } else {
      check('…(the sdkjs bundle is not installed here, so its getters were not grepped '
            + '— said rather than silently passed)', true);
    }
  }
}

/* ══ THE RENDER-TRUTH PAIR — THE PANEL'S HALF (roadmap §9.3, v1.5.25) ═══════════
   The repaint itself lives in the editor frame (bridge/panel/oo.html::ooPaintPair,
   pinned in test_oo_lane.py). What is this suite's business is the PANEL'S half: that
   Apply still goes through the one seam, that the editor's answer is not flattened on
   the way to the card, and that a build which CANNOT repaint tells the user instead of
   quietly showing them a stale sheet.

   THE FINDING, measured live in a real WKWebView before the fix: ooApplyApi wrote
   B7='PAINTPROOF' and D3=1234, GetValue() read both back, and the grid on screen still
   drew the OLD -300 with every dependent formula unchanged. After the fix, the same
   call through the same seam painted B7, D3 AND the recalculated C7/B13/C13 — and one
   asc_Undo took the whole apply back, on screen, in one step. */
{
  check('Apply still routes through ONE seam into the editor frame',
        /return ooChild\.applyOps\(list, \(plan && plan\.sheet\) \|\| ''\);/.test(html));
  check('…and the editor\'s NOTES survive the normalisation onto the card — the "the '
        + 'cells went in but this build could not be asked to redraw them" sentence '
        + 'reaches the user through this line or it reaches nobody',
        /notes: Array\.isArray\(d\.notes\) \? d\.notes\.slice\(\) : \[\],/.test(html));
  check('…and the card renders them (a note nobody paints is a note nobody reads)',
        /done\.notes/.test(html));
  check('…and a partial apply still names the editor\'s own ⌘Z as the way back, which '
        + 'is now ONE undo for the whole plan rather than one per op',
        /⌘Z inside the editor/.test(html));
}

// ── report ──
console.log('');
if (fails.length) {
  console.log(`${fails.length} FAILED (of ${pass + fails.length}):`);
  fails.forEach(f => console.log('  -', f));
  process.exit(1);
}
console.log(`loffice chrome scope + AI panel OK — ${pass} checks passed`);
