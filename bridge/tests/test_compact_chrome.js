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

ok(sels.length === 27, 'the compact block declares exactly 27 rules (got ' + sels.length + ')');

// ---------------------------------------------------------------------------
// STRUCTURAL GROUND TRUTH (added 2026-08-14h, third Mac failure). Two sessions
// diagnosed "the toggle does nothing" from the stylesheet and both were wrong; the
// missing step was proving the block is actually SERVED and actually PARSED. These
// four assertions are what "the CSS is fine" is allowed to mean from now on.
// ---------------------------------------------------------------------------
{
  const s0 = html.indexOf('<style>'), e0 = html.indexOf('</style>');
  const abs = html.indexOf(START);
  ok(html.indexOf(START, abs + 1) === -1,
     'the compact block appears exactly ONCE in the file (not duplicated into an '
     + 'artifact-iframe srcdoc template string)');
  ok(s0 >= 0 && e0 > s0 && abs > s0 && abs < e0,
     'the compact block lies inside the FIRST <style> element (byte range '
     + s0 + '..' + e0 + ', block at ' + abs + ')');
  // brace depth at the block's start must be 0, or an earlier unclosed rule /
  // @media / @supports would swallow the whole axis silently.
  const upto = css.slice(0, bi).replace(/\/\*[\s\S]*?\*\//g, '')
                              .replace(/"[^"]*"|'[^']*'/g, '""');
  let d = 0;
  for (const ch of upto) { if (ch === '{') d++; else if (ch === '}') d--; }
  ok(d === 0, 'CSS brace depth is 0 where the compact block starts (got ' + d + ')');
  ok(!/@(media|supports|container)[^{}]*\{[^{}]*$/.test(upto),
     'no at-rule wrapper is left open before the compact block');
}

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
ok(decls.length > 0 && decls.every(d => d.startsWith('--chrome-')),
   'every custom property the block defines is namespaced --chrome-* (redefines no '
   + 'palette token): ' + decls.join(' '));
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
     'button.primary keeps its cream fill under compact chrome (source-order tie won)');
  ok(w['border-color'] && w['border-color'].v === 'var(--cream)',
     'button.primary keeps its cream border under compact chrome');
  // 2026-08-14h: the bare-button rule is (0,1,2) and OUTRANKS base button.primary
  // (0,1,1) — a `color` on it would have made the one filled button light-on-light.
  ok(w.color && w.color.v === '#171420',
     'button.primary keeps its DARK ink under compact chrome (the bare-button rule '
     + 'must not claim color)'); }
// STATE NEGATIVES: compact `.cap-btn` is (0,2,1) and outranks `.cap-btn.arm` (0,2,0),
// so the two-step-delete states are restated inside the block or they go flat.
for (const [st, want] of [['arm', 'var(--bad)'], ['go', 'var(--gold)']]) {
  const w = winners({ tag: 'button', id: null, cls: ['cap-btn', st] }, ON);
  ok(w.color && w.color.v === want,
     '.cap-btn.' + st + ' keeps ' + want + ' under compact chrome');
  ok(w['border-color'] && w['border-color'].v === want,
     '.cap-btn.' + st + ' keeps its ' + want + ' border under compact chrome');
}
for (const id of ['chat-model-btn', 'chat-audio-btn']) {
  const w = winners({ tag: 'button', id: id, cls: ['mode-chip', 'empty'] }, ON);
  ok(w.color && w.color.v === 'var(--faint)',
     '#' + id + '.empty stays faint under compact chrome (the compact id rule is '
     + '(1,1,1) and outranks the base (1,1,0) state rule)');
}
// lane chip + row-action active states must still be the gold fill with theme ink
for (const cls of [['mode-chip', 'on'], ['mp-act', 'on']]) {
  const w = winners({ tag: 'span', id: null, cls }, ON);
  ok(w.background && w.background.v === 'var(--gold)',
     '.' + cls[0] + '.on stays gold-filled under compact chrome');
  ok(w.color && w.color.v === 'var(--bg)',
     '.' + cls[0] + '.on uses theme-aware ink under compact chrome');
}
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

// ---------------------------------------------------------------------------
// THE 2026-08-14h GUARD: a rule that WINS can still be a NO-OP, and that is what
// three Mac reports actually were. `border-color:var(--line2)` on the bare button was
// byte-identical to the base rule's own border-color; the "solid ground" was --card2
// (#181527) on a --card (#14121d) parent, a lift of 4/3/10 — invisible. So resolve the
// tokens for real and demand a PERCEPTUAL delta, plus the right hover direction.
// ---------------------------------------------------------------------------
{
  const tok = {};
  for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*[;}]/g)) {
    if (!(m[1] in tok)) tok[m[1]] = m[2];       // FIRST wins = the dark :root default
  }
  for (const t of ['--chrome-btn', '--chrome-btn-hi', '--chrome-edge',
                   '--card', '--card2', '--line2', '--bg2']) {
    ok(typeof tok[t] === 'string', 'token ' + t + ' resolves to a hex literal');
  }
  const lum = (h) => {
    h = h.replace('#', '');
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
      .map(x => x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const ratio = (a, b) => {
    const x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  };
  // (1) the axis ground must not BE the base ground under another name
  ok(tok['--chrome-btn'] !== tok['--card2'] && tok['--chrome-btn'] !== tok['--card'],
     'the compact ground is its own value, not an alias of --card/--card2');
  ok(tok['--chrome-edge'] !== tok['--line2'],
     'the compact border colour differs from --line2 (the base border-color — '
     + 'setting it again is a literal no-op)');
  // (2) it must be VISIBLE against every surface a control sits on
  for (const bg of ['--card', '--bg2']) {
    ok(ratio(tok['--chrome-btn'], tok[bg]) >= 1.3,
       'the compact ground is perceptible against ' + bg + ' (ratio '
       + ratio(tok['--chrome-btn'], tok[bg]).toFixed(2) + ' >= 1.3)');
  }
  // (3) hover must go LIGHTER than rest — the shipped build went darker
  ok(lum(tok['--chrome-btn-hi']) > lum(tok['--chrome-btn']),
     'compact hover is LIGHTER than the resting ground (the shipped build inverted it)');
  // (4) NO compact declaration may restate a value the base sheet already computes.
  //     Resolved per element via the cascade resolver: if it is in the compact rule it
  //     must actually differ with the attribute on.
  for (const el of [{ tag: 'button', id: null, cls: [] },
                    { tag: 'button', id: null, cls: ['cap-btn'] },
                    { tag: 'span', id: 'mode-agent', cls: ['mode-chip'] },
                    { tag: 'span', id: null, cls: ['chip'] }]) {
    const a = winners(el, OFF), b = winners(el, ON);
    for (const p of ['background', 'border-color']) {
      if (!(b[p] && /--chrome-/.test(b[p].v))) continue;
      ok((a[p] && a[p].v) !== b[p].v,
         'compact ' + p + ' on ' + (el.id || el.cls[0] || el.tag)
         + ' is a real change, not a restatement of the base value');
    }
  }
  // (5) the light axis gets its own three tokens, or dark slate lands on warm paper
  ok(/html\[data-chrome="compact"\]\[data-theme="light"\]/.test(noComments),
     'the compact axis carries a light-theme override for its own surface tokens');
  {
    const lr = (noComments.match(
      /html\[data-chrome="compact"\]\[data-theme="light"\]\s*\{([^}]*)\}/) || [null, ''])[1];
    const lt = {};
    for (const m of lr.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})/g)) lt[m[1]] = m[2];
    for (const t of ['--chrome-btn', '--chrome-btn-hi', '--chrome-edge']) {
      ok(typeof lt[t] === 'string', 'the light override defines ' + t);
      ok(lt[t] !== tok[t], 'the light ' + t + ' is not the dark value');
    }
    // light surfaces are --card #ffffff and --bg2 #f2eee3
    ok(ratio(lt['--chrome-btn'], '#ffffff') >= 1.3,
       'the light compact ground is perceptible on a white card (ratio '
       + ratio(lt['--chrome-btn'], '#ffffff').toFixed(2) + ')');
    // direction INVERTS on paper: hover darkens. Asserted so a future "make them
    // consistent" edit has to be deliberate.
    ok(lum(lt['--chrome-btn-hi']) < lum(lt['--chrome-btn']),
       'light-theme hover DARKENS (the inverse of dark theme, and correct on paper)');
  }
}

// ---------------------------------------------------------------------------
// RUNTIME SELF-CHECK. The next report must be ground truth, not a description:
// toggleChrome reads the attribute BACK and asks getComputedStyle what a real
// control resolved to, then feeds it. Cheap, permanent, and cannot throw.
// ---------------------------------------------------------------------------
ok(/function chromeProbe\(\)/.test(html), 'chromeProbe() exists');
{
  const pf = html.slice(html.indexOf('function chromeProbe()'));
  const pb = pf.slice(0, pf.indexOf('\n}') + 2);
  ok(/getAttribute\('data-chrome'\)/.test(pb),
     'the probe reads the attribute BACK off <html> (not the variable it just set)');
  ok(/getComputedStyle\(/.test(pb),
     'the probe asks the BROWSER what it computed, not the stylesheet');
  for (const p of ['borderRadius', 'backgroundColor', 'fontSize', 'textTransform']) {
    ok(pb.includes(p), 'the probe reports ' + p);
  }
  ok(/try\s*\{/.test(pb) && /catch/.test(pb),
     'the probe never throws (a self-check must not break what it watches)');
  ok(!/setAttribute|removeAttribute|\.style\./.test(pb),
     'the probe writes nothing — it only observes');
  // ordering: the probe must run AFTER the attribute write inside toggleChrome
  const t = html.slice(html.indexOf('function toggleChrome()'));
  const tb = t.slice(0, t.indexOf('\n}') + 2);
  ok(tb.indexOf("dataset.chrome = 'compact'") < tb.indexOf('chromeProbe()'),
     'toggleChrome() probes AFTER setting the attribute');
  ok(/feed\('chrome',\s*p\)/.test(tb),
     'the probe result reaches the activity feed (visible without a console)');
  ok(/console\.log/.test(tb), 'the probe result is also logged to the console');
}

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
