#!/usr/bin/env node
// OPTIONAL "COMPACT" CHROME (2026-08-14, Fable design) — invariants.
//
// The whole point of this slice is that it can be OFF and then nothing changed.
// So the load-bearing assertions here are NEGATIVES: every new rule must be
// prefixed html[data-chrome="compact"], no such selector may live outside the one
// sanctioned block, and the default (attribute absent) must be the editorial chrome.
// The rule COUNT is read out of the panel, so a rule added without updating this
// file trips rather than passing silently.

const fs = require('fs');
const path = require('path');
const P = path.join(__dirname, '..', 'panel', 'index.html');
const html = fs.readFileSync(P, 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  if (!cond) { fails++; console.error('FAIL: ' + msg); }
}

// ---------- locate the stylesheet + the compact block ----------
const css = html.split('<style>')[1].split('</style>')[0];
const START = '/* ============ OPTIONAL "COMPACT" CHROME';
const END = 'end compact chrome';
ok(css.includes(START), 'the compact-chrome block exists in the stylesheet');
ok(css.includes(END), 'the compact-chrome block is closed by its end marker');

const bi = css.indexOf(START);
const ei = css.indexOf(END);
const block = css.slice(bi, ei);

// The block must be the LAST thing in the stylesheet — it wins on equal specificity
// only if nothing follows it.
const after = css.slice(ei).replace(/[=\s*/-]/g, '');
ok(after.replace('endcompactchrome', '') === '',
   'the compact block is the last content in the stylesheet (nothing after it)');

// ---------- every rule is prefixed; nothing leaks ----------
const noComments = block.replace(/\/\*[\s\S]*?\*\//g, '');
const sels = (noComments.match(/([^{}]+)\{/g) || [])
  .map(s => s.slice(0, -1).trim()).filter(Boolean);

ok(sels.length === 23, 'the compact block declares exactly 23 rules (got ' + sels.length + ')');

const PREFIX = 'html[data-chrome="compact"]';
for (const sel of sels) {
  const parts = sel.split(',').map(s => s.trim());
  ok(parts.every(p => p.startsWith(PREFIX)),
     'every selector part is prefixed with the chrome attribute: ' + sel.slice(0, 60));
}

// NEGATIVE: the attribute appears in the stylesheet ONLY inside this block, so with
// data-chrome absent the panel is byte-for-byte the editorial chrome.
const outside = css.slice(0, bi) + css.slice(ei);
ok(!outside.includes('data-chrome'),
   'no data-chrome selector exists outside the compact block');

// NEGATIVE: this axis must not touch the palette or content typography. The block
// may READ tokens (var(--…)) but must never REDEFINE one, except its own font var.
const decls = noComments.match(/--[a-z0-9-]+\s*:/g) || [];
ok(decls.length === 1 && decls[0].startsWith('--chrome-font'),
   'the block defines exactly one custom property (--chrome-font), redefining no palette token');
for (const t of ['--bg:', '--gold:', '--cream:', '--serif:', '--mono:']) {
  ok(!noComments.includes(t), 'the block never redefines ' + t);
}
// It must not restyle content typography (headers/body/messages). NOTE (2026-08-14):
// this used to test `sel.includes(' ' + s)`, which broke honestly when the ap-btn rule
// gained the `.cmsg .approval` ANCESTOR path it needs for specificity. The invariant
// was never about ancestors — it is about what a rule TARGETS — so it now tests the
// last compound, which is strictly the right question and still forbids `.cmsg { }`.
const lastOf = (sel) => sel.trim().split(/\s+/).filter(p => p !== '>').pop();
for (const s of ['h1', '.brand', '.cmsg', '.body', 'body']) {
  ok(!sels.some(x => x.split(',').some(p => lastOf(p) === s)),
     'the block does not restyle content element: ' + s);
}

// ---------- the controls Fable named are actually covered ----------
for (const target of ['.chip', '.chip.chip-icon', '.caps-tab.on', '.mp-act',
                      '.mode-chip', '#chat-model-btn', '#chat-audio-btn',
                      'button.primary']) {
  ok(sels.some(x => x.includes(target)), 'compact chrome covers ' + target);
}
// REGRESSION (Debi Mac-verify 2026-08-14, "the ▣ toggles but nothing changes"): the
// first cut styled ONLY chip classes, and Mission Control — the screen the app opens
// on — has no chips beyond the four topbar icons. Every control on it is an UNCLASSED
// <button>. The axis must therefore reach the bare element, the Capabilities buttons
// and the approval/ask chips, or the toggle is a no-op wherever the user actually is.
ok(sels.some(x => x.split(',').some(p => lastOf(p) === 'button')),
   'compact chrome reaches the BARE <button> element (Mission Control card actions)');
for (const target of ['.cap-btn', '.ap-btn']) {
  ok(sels.some(x => x.includes(target)), 'compact chrome covers ' + target);
}
// The ap-btn rule must carry the base rule's own three-class ancestor path, otherwise
// `html[data-chrome="compact"] .ap-btn` (0-2-1) loses to `.cmsg .approval .ap-btn`
// (0-3-0) and that one row silently keeps its editorial look.
ok(sels.some(x => /\.cmsg\s+\.approval\s+\.ap-btn/.test(x)),
   'the ap-btn rule matches the base selector depth (.cmsg .approval .ap-btn)');
// A multi-select pick's gold `.on` state lives in the BASE sheet, so the compact
// ap-btn rule must not claim color/border-color or it would erase the selection.
const apRule = (noComments.match(/[^{}]*\.ap-btn\s*\{([^}]*)\}/) || [null, ''])[1];
ok(!/(^|;)\s*color\s*:/.test(apRule) && !/border-color\s*:/.test(apRule),
   'the compact ap-btn rule sets neither color nor border-color (the .on pick wins)');
// active state = filled gold with theme-aware ink (var(--bg)), not the hardcoded
// #171420 the editorial chips use — otherwise light theme would go dark-on-dark.
const onRules = sels.filter(x => /\.(on)\b/.test(x));
ok(onRules.length >= 3, 'at least three active-state rules (tab / row action / lane chip)');
ok(!noComments.includes('#171420'),
   'the block uses var(--bg) as gold-fill ink, never the hardcoded #171420');

// ---------- pre-paint + toggle + persistence ----------
const pre = html.split('</style>')[1].split('</head>')[0];
ok(/localStorage\.getItem\('harness-chrome'\)\s*===\s*'compact'/.test(pre),
   'the saved chrome is applied PRE-PAINT, in the same head script as the theme');
ok(pre.indexOf("harness-theme") < pre.indexOf("harness-chrome"),
   'theme and chrome are applied in one pre-paint pass (theme first, then chrome)');
ok(/dataset\.chrome\s*=\s*'compact'/.test(pre), 'pre-paint sets dataset.chrome');

ok(/function toggleChrome\(\)/.test(html), 'toggleChrome() exists');
const fn = html.slice(html.indexOf('function toggleChrome()'));
const body = fn.slice(0, fn.indexOf('\n}') + 2);
ok(/removeAttribute\('data-chrome'\)/.test(body),
   'turning it OFF removes the attribute entirely (editorial = no attribute)');
ok(/localStorage\.setItem\('harness-chrome'/.test(body), 'the choice is persisted');
ok(/feed\(/.test(body), 'the flip is logged to the activity feed');

// NEGATIVE: the chrome axis must be INDEPENDENT — toggleTheme must not touch it and
// toggleChrome must not touch the theme (no 4-state cycle).
const tfn = html.slice(html.indexOf('function toggleTheme()'));
const tbody = tfn.slice(0, tfn.indexOf('\n}') + 2);
ok(!/chrome/i.test(tbody), 'toggleTheme() does not touch the chrome axis');
ok(!/harness-theme|data-theme/.test(body), 'toggleChrome() does not touch the theme axis');

// ---------- both entry points ----------
ok(/id="chrome-chip"[^>]*onclick="toggleChrome\(\)"/.test(html)
   || /onclick="toggleChrome\(\)"[^>]*id="chrome-chip"/.test(html),
   'a topbar chip (#chrome-chip) calls toggleChrome()');
ok(html.indexOf('onclick="toggleTheme()"') < html.indexOf('id="chrome-chip"'),
   'the chrome chip sits beside (after) the ◐ theme chip');
ok(/\{t:'Toggle compact chrome',[^}]*f:toggleChrome\}/.test(html),
   'the command palette offers "Toggle compact chrome"');
// the chip only reads "on" from inside the block, so no off-state rule was added
ok(sels.some(x => x.includes('#chrome-chip')),
   'the chip\'s active look lives inside the compact block (no rule outside it)');

// ---------------------------------------------------------------------------
// THE REAL REGRESSION GUARD: resolve the actual cascade, attribute off vs on.
//
// Every assertion above passed on the build Debi reported as broken — greps prove a
// rule EXISTS, not that it WINS or that it reaches the screen. So this section walks
// the whole stylesheet, computes the winning declaration per property for a handful
// of real elements (tag + id + classes taken from the panel's own markup), and demands
// that turning the attribute on actually CHANGES them. A future rule that is out-
// specified by an id/multi-class base rule fails here instead of on Debi's Mac.
// ---------------------------------------------------------------------------
const allRules = [];
{ const src = css.replace(/\/\*[\s\S]*?\*\//g, '');   // comments carry braces + prose
  let i = 0;
  while (i < src.length) {
    const b = src.indexOf('{', i); if (b < 0) break;
    const sel = src.slice(i, b).trim();
    let d = 1, j = b + 1;
    while (j < src.length && d > 0) { if (src[j] === '{') d++; else if (src[j] === '}') d--; j++; }
    if (!sel.startsWith('@')) allRules.push({ sel, body: src.slice(b + 1, j - 1), order: allRules.length });
    i = j;
  }
  ok(allRules.length > 300, 'the cascade resolver parsed the whole stylesheet (got '
     + allRules.length + ' rules)'); }
function specOf(s) {
  const a = (s.match(/#[\w-]+/g) || []).length;
  const b = (s.match(/\.[\w-]+/g) || []).length + (s.match(/\[[^\]]+\]/g) || []).length
          + (s.match(/:(?!:)[\w-]+/g) || []).length;
  const c = (s.replace(/\[[^\]]+\]/g, '').match(/(^|[\s>+~])([a-z][\w-]*)/g) || []).length;
  return [a, b, c];
}
function hits(cmpd, el) {
  const id = (cmpd.match(/#([\w-]+)/g) || []).map(x => x.slice(1));
  const cl = (cmpd.match(/\.([\w-]+)/g) || []).map(x => x.slice(1));
  const tag = cmpd.match(/^([a-z][\w-]*)/);
  if (tag && tag[1] !== el.tag) return false;
  if (id.some(x => x !== el.id)) return false;
  if (cl.some(x => !(el.cls || []).includes(x))) return false;
  for (const a of (cmpd.match(/\[[^\]]+\]/g) || [])) {
    const m = a.match(/\[([\w-]+)="?([^"\]]*)"?\]/);
    if (!m || (el.attrs || {})[m[1]] !== m[2]) return false;
  }
  for (const p of (cmpd.match(/:(?!:)[\w-]+/g) || [])) {
    const n = p.slice(1);
    if (n === 'not') continue;                       // handled below
    if (!(el.pseudo || []).includes(n)) return false;
  }
  const not = cmpd.match(/:not\(([^)]*)\)/);
  if (not && hits(not[1], el)) return false;
  return true;
}
function matchSel(sel, el, ancestors) {
  const parts = sel.trim().split(/\s+/).filter(p => p !== '>');
  if (!hits(parts[parts.length - 1].replace(/:not\([^)]*\)/g, m => m), el)) return false;
  let pool = ancestors.slice();
  for (let k = 0; k < parts.length - 1; k++) {
    const idx = pool.findIndex(a => hits(parts[k], a));
    if (idx < 0) return false;
    pool = pool.slice(idx + 1);
  }
  return true;
}
// [important, id, class, type, source-order] — later source order wins a full tie.
function beats(x, y) {
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return true;
}
function winners(el, root) {
  const anc = [root, { tag: 'body', id: null, cls: [] },
               { tag: 'div', id: null, cls: ['cmsg', 'approval'] }];
  const w = {};
  for (const r of allRules) for (const raw of r.sel.split(',')) {
    const s = raw.trim(); if (!s) continue;
    if (!matchSel(s, el, anc)) continue;
    const key = [0, ...specOf(s), r.order];
    for (const d of r.body.split(';')) {
      const ci = d.indexOf(':'); if (ci < 0) continue;
      const p = d.slice(0, ci).trim(), v = d.slice(ci + 1).trim();
      if (!/^[a-z-]+$/.test(p)) continue;
      const k = /!important/.test(v) ? [1, ...key.slice(1)] : key;
      if (!w[p] || beats(k, w[p].key)) w[p] = { v, key: k, sel: s };
    }
  }
  return w;
}
const OFF = { tag: 'html', id: null, cls: [], attrs: {} };
const ON = { tag: 'html', id: null, cls: [], attrs: { 'data-chrome': 'compact' } };
function delta(el, props) {
  const a = winners(el, OFF), b = winners(el, ON);
  return props.filter(p => (a[p] && a[p].v) !== (b[p] && b[p].v));
}
// (a) a Mission Control component card action — `<button>Start</button>`, no class.
//     THIS is the check that fails on the reported build.
ok(delta({ tag: 'button', id: null, cls: [] },
         ['background', 'border-radius', 'padding', 'font-size', 'border-color']).length >= 3,
   'a bare Mission Control <button> visibly changes when compact is on');
// (b) a Capabilities action button, (c) an ask/approval choice chip.
ok(delta({ tag: 'button', id: null, cls: ['cap-btn'] },
         ['background', 'border-radius', 'padding', 'font', 'text-transform']).length >= 3,
   'a .cap-btn visibly changes when compact is on');
ok(delta({ tag: 'button', id: null, cls: ['ap-btn'] },
         ['background', 'border-radius', 'padding', 'font']).length >= 3,
   'an .ap-btn choice chip visibly changes when compact is on');
// (d) the chip family Fable's first cut covered — still must change.
ok(delta({ tag: 'span', id: 'mode-agent', cls: ['mode-chip', 'on'] },
         ['font', 'padding', 'text-transform', 'letter-spacing']).length >= 3,
   'a composer lane chip visibly changes when compact is on');
// TIE-BREAK NEGATIVE: the generic button rule must not flatten the cream primary —
// same specificity as the base button.primary rule and later in source order.
{ const w = winners({ tag: 'button', id: null, cls: ['primary'] }, ON);
  ok(w.background && w.background.v === 'var(--cream)',
     'button.primary keeps its cream fill under compact chrome (source-order tie won)'); }
// NEGATIVE: the per-message action row must NOT become boxes (.cmsg .msg-act, 0-2-0,
// still outranks the bare-button rule).
{ const w = winners({ tag: 'button', id: null, cls: ['msg-act'] }, ON);
  ok(w.background && /none/.test(w.background.v) && w.border && /\b0\b/.test(w.border.v),
     'message actions (Copy/Edit/Fork/Delete) stay borderless text under compact'); }
// NEGATIVE: with the attribute ABSENT nothing may differ from today — the same
// resolver, run twice against OFF, is a tautology, so instead assert that no compact
// selector can match an element whose root lacks the attribute.
ok(!sels.some(s => matchSel(s.split(',')[0].trim(),
                            { tag: 'button', id: null, cls: ['chip'] },
                            [OFF, { tag: 'body', id: null, cls: [] }])),
   'no compact rule matches anything while the attribute is absent');

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
