#!/usr/bin/env node
// OPTIONAL "STUDIO" CHROME (2026-08-20, Fable design — FABLE-STUDIO-CHROME-SPEC.md)
// — invariants. PORTED FROM test_compact_chrome.js, which this file replaces along
// with the axis it guarded.
//
// The two mechanisms below are the reason compact's THIRD attempt finally landed on
// Debi's Mac, and they are carried over verbatim in intent:
//   (A) a real CASCADE RESOLVER — a grep proves a rule EXISTS, not that it WINS or
//       that it REACHES the screen. Two sessions diagnosed "the toggle does nothing"
//       from the stylesheet and both were wrong.
//   (B) a VALUE-LEVEL NO-OP DETECTOR — a rule that wins can still be a no-op. The
//       shipped compact build restated `border-color:var(--line2)` (byte-identical to
//       the base) on a ground 1.04:1 against its own parent. Tokens are resolved to
//       hex here and contrast is computed, so "solid ground" has to be measurable.
// The rule COUNT is read out of the panel, so a rule added without updating this file
// trips rather than passing silently.

const fs = require('fs');
const path = require('path');
const P = path.join(__dirname, '..', 'panel', 'index.html');
const html = fs.readFileSync(P, 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  if (!cond) { fails++; console.error('FAIL: ' + msg); }
}

// ---------- locate the stylesheet + the studio block ----------
const css = html.split('<style>')[1].split('</style>')[0];
const START = '/* ============ OPTIONAL "STUDIO" CHROME';
const END = 'end studio chrome';
ok(css.includes(START), 'the studio-chrome block exists in the stylesheet');
ok(css.includes(END), 'the studio-chrome block is closed by its end marker');

const bi = css.indexOf(START);
const ei = css.indexOf(END);
const block = css.slice(bi, ei);

// The block must be the LAST thing in the stylesheet — it wins on equal specificity
// only if nothing follows it.
const after = css.slice(ei).replace(/[=\s*/-]/g, '');
ok(after.replace('endstudiochrome', '') === '',
   'the studio block is the last content in the stylesheet (nothing after it)');

// ---------- the retired axis is GONE, not parked beside this one ----------
ok(!html.includes('data-chrome="compact"'),
   'the compact axis is deleted wholesale — no data-chrome="compact" anywhere in the '
   + 'panel (two half-themes on one button was the thing Fable refused)');

// ---------- every rule is prefixed; nothing leaks ----------
const noComments = block.replace(/\/\*[\s\S]*?\*\//g, '');
const sels = (noComments.match(/([^{}]+)\{/g) || [])
  .map(s => s.slice(0, -1).trim()).filter(Boolean);

// 40 → 47: STUDIO PHASE 2 §C added the FORM-FIELD rules (7). Nothing else grew.
ok(sels.length === 47, 'the studio block declares exactly 47 rules (got ' + sels.length + ')');

// ---------------------------------------------------------------------------
// STRUCTURAL GROUND TRUTH (inherited from 2026-08-14h, the third Mac failure).
// Proving the block is SERVED and PARSED is what "the CSS is fine" is allowed to mean.
// ---------------------------------------------------------------------------
{
  const s0 = html.indexOf('<style>'), e0 = html.indexOf('</style>');
  const abs = html.indexOf(START);
  ok(html.indexOf(START, abs + 1) === -1,
     'the studio block appears exactly ONCE in the file (not duplicated into an '
     + 'artifact-iframe srcdoc template string)');
  ok(s0 >= 0 && e0 > s0 && abs > s0 && abs < e0,
     'the studio block lies inside the FIRST <style> element (byte range '
     + s0 + '..' + e0 + ', block at ' + abs + ')');
  const upto = css.slice(0, bi).replace(/\/\*[\s\S]*?\*\//g, '')
                              .replace(/"[^"]*"|'[^']*'/g, '""');
  let d = 0;
  for (const ch of upto) { if (ch === '{') d++; else if (ch === '}') d--; }
  ok(d === 0, 'CSS brace depth is 0 where the studio block starts (got ' + d + ')');
  ok(!/@(media|supports|container)[^{}]*\{[^{}]*$/.test(upto),
     'no at-rule wrapper is left open before the studio block');
}

// Split on a separator only at paren depth 0 — a selector list may now contain
// `:not(:where(.a, .b))`, whose comma is NOT a list separator.
function splitTop(str, sep) {
  const out = []; let d = 0, cur = '';
  for (const ch of str) {
    if (ch === '(') d++;
    else if (ch === ')') d--;
    if (ch === sep && d === 0) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur);
  return out;
}

const PREFIX = 'html[data-chrome="studio"]';
for (const sel of sels) {
  const parts = splitTop(sel, ',').map(s => s.trim());
  ok(parts.every(p => p.startsWith(PREFIX)),
     'every selector part is prefixed with the chrome attribute: ' + sel.slice(0, 60));
}

// NEGATIVE: the attribute appears in the stylesheet ONLY inside this block, so with
// data-chrome absent the panel is byte-for-byte the editorial chrome.
const outside = css.slice(0, bi) + css.slice(ei);
ok(!outside.includes('data-chrome'),
   'no data-chrome selector exists outside the studio block');

// The ONE sanctioned base rule the slice adds: editorial is the DEFAULT, so the icon
// spans must be hidden with the attribute ABSENT — that cannot live inside the block.
ok(/\n\s*\.st-only \{ display:none; \}/.test(outside),
   'the base sheet hides .st-only (icons are invisible in editorial chrome)');

// NEGATIVE: this axis must not touch the palette or content typography. The block
// may READ tokens (var(--…)) but must never REDEFINE one, except its own namespace.
const decls = noComments.match(/--[a-z0-9-]+\s*:/g) || [];
ok(decls.length > 0 && decls.every(d => d.startsWith('--st-')),
   'every custom property the block defines is namespaced --st-* (redefines no '
   + 'palette token): ' + decls.join(' '));
for (const t of ['--bg:', '--gold:', '--cream:', '--serif:', '--mono:']) {
  ok(!noComments.includes(t), 'the block never redefines ' + t);
}
// It must not restyle content typography. Tests the LAST compound (what a rule
// TARGETS), not ancestors — a rule may legitimately carry `.cmsg` as an ancestor path
// to reach the exemptions.
const lastOf = (sel) => sel.trim().split(/\s+/).filter(p => p !== '>').pop();
for (const s of ['h1', '.brand', '.cmsg', '.body', 'body']) {
  ok(!sels.some(x => x.split(',').some(p => lastOf(p) === s)),
     'the block does not restyle content element: ' + s);
}

// ---------- the surfaces Fable named (D3) are actually covered ----------
for (const target of ['.chip', '.chip.chip-icon', '.caps-tab.on', '.mp-act',
                      '.mode-chip', '#chat-model-btn', '#chat-audio-btn',
                      'button.primary', '.cap-btn', '.cap-sw', '#cs-new',
                      '.cs-act button', '.hfget', '.art-btn', '.dlacts button',
                      '#chat-send', '#chat-talk', '#chat-auto', '#chat-conv',
                      '#chat-attach', '.st-only', '.ed-only', '.st-ico', '.st-word',
                      // PHASE 2 §C — the form fields, the half of the Music page the
                      // axis used to miss entirely.
                      '.cap-inp', '.cap-num', '.cap-sel', 'textarea.cap-inp',
                      '#chat-input', '.cap-range::-webkit-slider-thumb']) {
  ok(sels.some(x => x.includes(target)), 'studio chrome covers ' + target);
}
// The axis must reach the BARE element or it is a no-op on Mission Control, the
// screen the app OPENS on (every control there is an unclassed <button>).
ok(sels.some(x => x.split(',').some(p => /^html\[data-chrome="studio"\] button(:|$)/.test(p.trim()))),
   'studio chrome reaches the BARE <button> element (Mission Control card actions)');

// ---------- pre-paint + toggle + persistence + legacy migration ----------
const pre = html.split('</style>')[1].split('</head>')[0];
ok(/localStorage\.getItem\('harness-chrome'\)\s*===\s*'studio'/.test(pre),
   'the saved chrome is applied PRE-PAINT, in the same head script as the theme');
ok(pre.indexOf('harness-theme') < pre.indexOf('harness-chrome'),
   'theme and chrome are applied in one pre-paint pass (theme first, then chrome)');
ok(/dataset\.chrome\s*=\s*'studio'/.test(pre), 'pre-paint sets dataset.chrome');
// LEGACY MIGRATION (D1): a stored 'compact' must resolve to EDITORIAL, silently.
{
  const line = (pre.match(/^.*getItem\('harness-chrome'\).*$/m) || [''])[0];
  ok(line.includes("'studio'") && !line.includes("'compact'"),
     'the pre-paint script never matches the legacy value, so a stored \'compact\' '
     + 'falls through to editorial with no modal and no data loss');
}

ok(/function toggleChrome\(\)/.test(html), 'toggleChrome() exists');
const fn = html.slice(html.indexOf('function toggleChrome()'));
const body = fn.slice(0, fn.indexOf('\n}') + 2);
ok(/removeAttribute\('data-chrome'\)/.test(body),
   'turning it OFF removes the attribute entirely (editorial = no attribute)');
ok(/localStorage\.setItem\('harness-chrome'/.test(body), 'the choice is persisted');
ok(/'studio' : 'editorial'/.test(body),
   'the persisted values are studio | editorial (the legacy name is never rewritten)');
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
ok(/title="Toggle Studio chrome \(uniform buttons \+ icons\)"/.test(html),
   'the ▣ chip carries the spec\'s title');
ok(/\{t:'Toggle Studio chrome',[^}]*f:toggleChrome\}/.test(html),
   'the command palette offers "Toggle Studio chrome"');
ok(sels.some(x => x.includes('#chrome-chip')),
   'the chip\'s active look lives inside the studio block (no rule outside it)');

// ---------------------------------------------------------------------------
// D4 — THE ICON SET. Six symbols, once each, built from primitives only.
// ---------------------------------------------------------------------------
{
  const ids = ['i-send', 'i-mic', 'i-auto', 'i-conv', 'i-attach', 'i-theme'];
  const defs = (html.match(/<defs>[\s\S]*?<\/defs>/) || [''])[0];
  ok(defs.length > 0, 'the panel carries an inline <defs> sprite');
  ok(html.indexOf('<defs>') === html.lastIndexOf('<defs>'),
     'there is exactly ONE sprite block (a second copy would duplicate every id)');
  ok(html.indexOf('<defs>') > html.indexOf('<body>')
     && html.indexOf('<defs>') < html.indexOf('<aside>'),
     'the sprite sits immediately after <body> opens, before any consumer');
  for (const id of ids) {
    const n = (html.match(new RegExp('id="' + id + '"', 'g')) || []).length;
    ok(n === 1, 'symbol #' + id + ' is declared exactly once (got ' + n + ')');
    ok(defs.includes('id="' + id + '"'), 'symbol #' + id + ' lives in the sprite');
    ok(html.includes('href="#' + id + '"'), 'symbol #' + id + ' is actually referenced');
  }
  const syms = defs.match(/<symbol[\s\S]*?<\/symbol>/g) || [];
  ok(syms.length === 6, 'the sprite declares exactly 6 symbols (got ' + syms.length + ')');
  for (const sy of syms) {
    const id = (sy.match(/id="([\w-]+)"/) || [])[1];
    ok(/viewBox="0 0 16 16"/.test(sy), id + ' uses the 16x16 viewBox');
    ok(/stroke="currentColor"/.test(sy),
       id + ' strokes with currentColor (so a state colour is one declaration)');
    ok(/stroke-width="1\.5"/.test(sy), id + ' uses stroke-width 1.5');
    // primitives only — no freehand path data beyond arcs (A) and the moveto/closepath
    // that carry them. A cubic/quadratic curve would be a hand-drawn shape.
    ok(!/[CcSsQqTt]\s*[\d.-]/.test(sy.replace(/[\w-]+="/g, '"')),
       id + ' is built from primitives only (no bezier path data)');
    const prim = (sy.match(/<(line|rect|circle|path)\b/g) || []).length;
    ok(prim >= 2, id + ' is drawn from at least two primitives');
  }
  // the sprite must not be display:none — a <use> into a display:none sprite is the
  // one WebKit corner that has historically failed; off-layout is the safe idiom.
  const spriteTag = (html.match(/<svg[^>]*>\s*<defs>/) || [''])[0];
  ok(/position:absolute/.test(spriteTag) && !/display:none/.test(spriteTag),
     'the sprite is positioned off-layout, not display:none');
}

// ---------------------------------------------------------------------------
// D4 — BOTH CHILDREN. Every icon-bearing control carries the icon span AND the text
// span in the markup, and CSS alone picks one, so no renderer branches on the theme.
// ---------------------------------------------------------------------------
{
  const btns = ['chat-send', 'chat-talk', 'chat-auto', 'chat-conv', 'chat-attach'];
  for (const id of btns) {
    const i = html.indexOf('id="' + id + '"');
    ok(i > 0, id + ' exists in the markup');
    const tag = html.slice(i, html.indexOf('</button>', i));
    ok(/class="st-only"/.test(tag), id + ' carries the .st-only icon span');
    ok(/class="ed-only"/.test(tag), id + ' carries the .ed-only text span');
    ok(/<use href="#i-/.test(tag), id + ' references a sprite symbol');
  }
  // the topbar ◐ becomes an icon too (D4 mapping); ▣ / ⌘K / ↻ keep their glyphs
  const th = html.indexOf('onclick="toggleTheme()"');
  const thTag = html.slice(th, html.indexOf('</span>', html.indexOf('ed-only', th)));
  ok(/#i-theme/.test(thTag), 'the ◐ theme chip carries the #i-theme icon');
  const chip = html.slice(html.indexOf('id="chrome-chip"'));
  ok(!/st-only/.test(chip.slice(0, chip.indexOf('</span>'))),
     'the ▣ chip keeps its glyph (only ◐ was mapped to an icon)');
  // NEGATIVE: not one renderer may branch on the chrome attribute.
  ok(!/dataset\.chrome[^!=]*===\s*'studio'\s*\)\s*\{[\s\S]{0,200}(innerHTML|textContent)/
       .test(html),
     'no renderer branches on the theme to choose an icon (CSS alone decides)');
}

// ---------------------------------------------------------------------------
// STATE MUST NEVER BECOME INVISIBLE. Every render site that used to write the button
// label wholesale now goes through ctlPaint(), which writes BOTH children — and the
// live states (recording clock, conversation phase, Stop) are mirrored as .st-word.
// ---------------------------------------------------------------------------
{
  ok(/function ctlPaint\(btn, icon, dot, text, word\)/.test(html), 'ctlPaint() exists');
  ok(/function ctlIcon\(id\)/.test(html), 'ctlIcon() exists');
  ok(/function sendPaint\(label\)/.test(html), 'sendPaint() exists');
  const cp = html.slice(html.indexOf('function ctlPaint('));
  const cb = cp.slice(0, cp.indexOf('\n}') + 2);
  ok(/className = 'st-only'/.test(cb) && /className = 'ed-only'/.test(cb),
     'ctlPaint writes BOTH children on every paint');
  ok(/className = 'talk-dot'/.test(cb) && /className = 'talk-t'/.test(cb),
     'the editorial half reproduces today\'s .talk-dot / .talk-t markup exactly');
  ok(/createTextNode\(text\)/.test(cb),
     'a dot-less label stays a bare text node (today\'s idle labels were plain '
     + 'textContent writes — wrapping them in .talk-t would change editorial\'s font)');
  ok(/w\.textContent = word/.test(cb),
     'the status word is written with textContent, never as markup');

  // the four dynamic render sites no longer wipe the icon
  for (const f of ['renderTalkBtn', 'talkPaint', 'renderAutoBtn', 'renderConvBtn',
                   'autoFlash']) {
    const s = html.slice(html.indexOf('function ' + f + '('));
    const b = s.slice(0, s.indexOf('\n}') + 2);
    ok(/ctlPaint\(/.test(b), f + '() paints through ctlPaint (the icon survives)');
    ok(!/\.textContent = (TALK_LABEL|AUTO_LABEL|CONV_LABEL|text)\b/.test(b),
       f + '() no longer writes the label wholesale over the icon');
  }
  // the two live states are mirrored beside the icon
  const tp = html.slice(html.indexOf('function talkPaint('));
  ok(/ctlPaint\(btn, 'i-mic', '■ ', talkTime\(sec\), talkTime\(sec\)\)/
       .test(tp.slice(0, tp.indexOf('\n}') + 2)),
     'the recording CLOCK is mirrored as the status word beside the mic');
  const rc = html.slice(html.indexOf('function renderConvBtn('));
  ok(/convLabel\(convSt\), convLabel\(convSt\)\)/.test(rc.slice(0, rc.indexOf('\n}') + 2)),
     'the conversation PHASE word (listening / … / speaking) is mirrored beside the '
     + 'headset icon — the state must never become invisible in studio chrome');
  // Send / Stop
  const sp = html.slice(html.indexOf('function sendPaint('));
  const sb = sp.slice(0, sp.indexOf('\n}') + 2);
  ok(/'i-send'/.test(sb), 'sendPaint uses the send arrow');
  ok(/label === 'Send' \? '' : label/.test(sb),
     'a non-resting label (Stop) is shown as the status word, so the Hermes stop '
     + 'affordance is readable without a seventh symbol');
  ok(!/\bsb\.textContent = 'Send'\b/.test(html) && !/sendBtn\.textContent = 'Stop'/.test(html),
     'every Send/Stop label site funnels through sendPaint()');
  ok((html.match(/sendPaint\('Send'\)/g) || []).length === 2
     && (html.match(/sendPaint\('Stop'\)/g) || []).length === 1,
     'all three former label sites are converted (2x Send release, 1x Stop)');
}

// ---------------------------------------------------------------------------
// (A) THE CASCADE RESOLVER — attribute off vs on. Greps prove a rule EXISTS; this
// proves it WINS and REACHES the screen. Extended from the compact version with
// :where() support (zero specificity), which is what makes the bare-<button> rule
// able to exempt .msg-act / .ap-btn without out-specifying the smaller tiers.
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
// CSS specificity: :where() contributes ZERO; :not() contributes its argument's.
function specOf(s) {
  const t = s.replace(/:where\([^)]*\)/g, '')      // zero-specificity
             .replace(/:not\(/g, '').replace(/\)/g, ' ');  // :not() counts its arg
  const a = (t.match(/#[\w-]+/g) || []).length;
  const b = (t.match(/\.[\w-]+/g) || []).length + (t.match(/\[[^\]]+\]/g) || []).length
          + (t.match(/:(?!:)[\w-]+/g) || []).length;
  const c = (t.replace(/\[[^\]]+\]/g, '').match(/(^|[\s>+~])([a-z][\w-]*)/g) || []).length;
  return [a, b, c];
}
function hits(cmpd, el) {
  // functional pseudos first: :where(a, b) matches if ANY matches; :not(x) inverts.
  let rest = '', fns = [];
  for (let i = 0; i < cmpd.length; ) {
    const m = /^:(not|where)\(/.exec(cmpd.slice(i));
    if (!m) { rest += cmpd[i]; i++; continue; }
    let d = 1, j = i + m[0].length, arg = '';
    while (j < cmpd.length && d > 0) {
      if (cmpd[j] === '(') d++;
      else if (cmpd[j] === ')') { d--; if (!d) break; }
      arg += cmpd[j]; j++;
    }
    fns.push([m[1], arg]); i = j + 1;
  }
  for (const [name, arg] of fns) {
    const any = splitTop(arg, ',').map(x => x.trim()).filter(Boolean)
                   .some(x => hits(x, el));
    if (name === 'not' && any) return false;
    if (name === 'where' && !any) return false;
  }
  const id = (rest.match(/#([\w-]+)/g) || []).map(x => x.slice(1));
  const cl = (rest.match(/\.([\w-]+)/g) || []).map(x => x.slice(1));
  const tag = rest.match(/^([a-z][\w-]*)/);
  if (tag && tag[1] !== el.tag) return false;
  if (id.some(x => x !== el.id)) return false;
  if (cl.some(x => !(el.cls || []).includes(x))) return false;
  for (const a of (rest.match(/\[[^\]]+\]/g) || [])) {
    const m = a.match(/\[([\w-]+)="?([^"\]]*)"?\]/);
    if (!m || (el.attrs || {})[m[1]] !== m[2]) return false;
  }
  for (const p of (rest.match(/:(?!:)[\w-]+/g) || [])) {
    if (!(el.pseudo || []).includes(p.slice(1))) return false;
  }
  return true;
}
function matchSel(sel, el, ancestors) {
  const parts = splitTop(sel.trim().replace(/\s+/g, ' '), ' ')
                  .filter(p => p && p !== '>');
  if (!hits(parts[parts.length - 1], el)) return false;
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
// Ancestors are PER ELEMENT (el.anc), not one global chain: a shared chain would let
// `.dlrow .dlacts button` match a Mission Control button and silently answer every
// question with the wrong rule — which is exactly the class of mistake this resolver
// exists to catch, so it must not make it itself.
function winners(el, root) {
  const anc = [root, { tag: 'body', id: null, cls: [] }].concat(el.anc || []);
  const w = {};
  for (const r of allRules) for (const raw of splitTop(r.sel, ',')) {
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
// two SEPARATE ancestors: `.cmsg .approval .ap-btn` is a descendant chain, and a
// single element carrying both classes would silently fail to match it.
const CMSG = [{ tag: 'div', id: null, cls: ['cmsg'] },
              { tag: 'div', id: null, cls: ['approval'] }];
const DLROW = [{ tag: 'div', id: null, cls: ['dlrow'] },
               { tag: 'span', id: null, cls: ['dlacts'] }];
const CSACT = [{ tag: 'div', id: null, cls: ['cs-act'] }];
const OFF = { tag: 'html', id: null, cls: [], attrs: {} };
const ON = { tag: 'html', id: null, cls: [], attrs: { 'data-chrome': 'studio' } };
function delta(el, props) {
  const a = winners(el, OFF), b = winners(el, ON);
  return props.filter(p => (a[p] && a[p].v) !== (b[p] && b[p].v));
}
// sanity: the resolver understands the two functional pseudos it just learned
ok(specOf('html[data-chrome="studio"] button:not(:where(.msg-act, .ap-btn))')
     .join() === '0,1,2', ':where() inside :not() contributes ZERO specificity');
ok(specOf('html[data-chrome="studio"] button:hover:not(.primary)').join() === '0,3,2',
   ':not(.primary) contributes its argument\'s specificity (attr + :hover + .primary)');
ok(hits('button:not(:where(.msg-act, .ap-btn))', { tag: 'button', id: null, cls: [] })
   && !hits('button:not(:where(.msg-act, .ap-btn))',
            { tag: 'button', id: null, cls: ['msg-act'], anc: CMSG }),
   'the resolver excludes an exempt class and keeps a plain button');

// (a) a Mission Control component card action — `<button>Start</button>`, no class.
ok(delta({ tag: 'button', id: null, cls: [] },
         ['background', 'border-radius', 'padding', 'font-size', 'border-color', 'height']).length >= 4,
   'a bare Mission Control <button> visibly changes when studio is on');
// (b) Capabilities, (c) session rail, (d) HF get, (e) artifact, (f) download row
ok(delta({ tag: 'button', id: null, cls: ['cap-btn'] },
         ['background', 'border-radius', 'padding', 'font-size', 'text-transform', 'height']).length >= 4,
   'a .cap-btn visibly changes when studio is on');
ok(delta({ tag: 'button', id: 'cs-new', cls: [] },
         ['background', 'font-size', 'text-transform', 'height']).length >= 3,
   '#cs-new visibly changes when studio is on');
ok(delta({ tag: 'button', id: null, cls: ['hfget'] },
         ['background', 'font-size', 'text-transform', 'height']).length >= 3,
   'a .hfget visibly changes when studio is on');
ok(delta({ tag: 'button', id: null, cls: ['art-btn'] },
         ['background', 'font-size', 'height', 'padding']).length >= 3,
   'an .art-btn visibly changes when studio is on');
ok(delta({ tag: 'button', id: null, cls: [], anc: DLROW },
         ['background', 'height', 'text-transform']).length >= 3,
   'a download-row action visibly changes when studio is on');
ok(delta({ tag: 'button', id: null, cls: ['cs-del'], anc: CSACT },
         ['background', 'height', 'font-size', 'font-family', 'border-radius']).length >= 3,
   'a session-rail row action visibly changes when studio is on');
// (g') THE MUSIC PAGE (deck spec C7). Debi reported ▣ "not restyling the music page";
// the audit says the BUTTONS there always did and the FORM FIELDS never did, because
// this axis covers controls-that-are-buttons and the Music page is form-dominated.
// These pin the half that is genuinely ours, so a regression there trips here.
const MCARD = [{ tag: 'div', id: 'view-music', cls: [] },
               { tag: 'div', id: null, cls: ['cap-card'] },
               { tag: 'div', id: null, cls: ['cap-row'] }];
ok(delta({ tag: 'button', id: null, cls: ['cap-btn', 'go'], anc: MCARD },
         ['background', 'border-radius', 'font-size', 'height', 'text-transform']).length >= 4,
   'the Music page Get / Reveal / convert buttons restyle under studio chrome');
ok(delta({ tag: 'button', id: 'mus-go', cls: ['primary'], anc: MCARD },
         ['border-radius', 'font-family', 'text-transform', 'height']).length >= 3,
   'the Music Generate button restyles under studio chrome');
ok(delta({ tag: 'button', id: 'mus-cancel', cls: ['cap-btn'], anc: MCARD },
         ['background', 'height', 'font-size']).length >= 3,
   'the Music Cancel chip restyles under studio chrome');
ok(delta({ tag: 'button', id: null, cls: ['chip'], anc: MCARD },
         ['background', 'height', 'font-size', 'text-transform']).length >= 3,
   'the Music engine chips restyle under studio chrome');
// PHASE 2 §C — THE RULING THAT CLOSED THAT GAP. The negative above used to record it
// honestly ("the axis does not reach form fields"); the Music page is two textareas,
// three number boxes, a slider and a select, i.e. most of its visual mass, which is why
// ▣ READ as a no-op there. These are the same elements, now asserted the other way.
ok(delta({ tag: 'textarea', id: 'mus-prompt', cls: ['cap-inp'], anc: MCARD },
         ['background', 'font-size', 'border-color', 'font-family']).length >= 3,
   'the Music page textareas restyle under studio chrome (§C)');
ok(delta({ tag: 'textarea', id: 'mus-prompt', cls: ['cap-inp'], anc: MCARD },
         ['height']).length === 0,
   '...but a textarea gets NO height rule (growInput owns that at runtime)');
ok(delta({ tag: 'input', id: 'mus-secs', cls: ['cap-inp'], anc: MCARD },
         ['background', 'height', 'border-color', 'font-size']).length >= 3,
   'the Music page number boxes restyle, height included (a single-line row allows it)');
ok(delta({ tag: 'select', id: 'mus-fmt', cls: ['cap-inp'], anc: MCARD },
         ['background', 'height', 'border-radius']).length >= 3,
   'the Music page format select restyles under studio chrome');
ok(delta({ tag: 'select', id: 'cap-setting-search_provider', cls: ['cap-sel'] },
         ['background', 'height', 'border-radius', 'font-family']).length >= 3,
   'a Capabilities .cap-sel restyles too (the ruling is global, not music-only)');
ok(delta({ tag: 'input', id: 'cap-setting-agent_max_rounds', cls: ['cap-num'] },
         ['background', 'height', 'border-radius']).length >= 3,
   'a Capabilities .cap-num restyles too');
{ // the FIELD ground is its own token and reads as a WELL, not a button
  const w = winners({ tag: 'input', id: null, cls: ['cap-inp'] }, ON);
  ok(w.background && w.background.v === 'var(--st-inp)',
     'a field sits on --st-inp, deliberately NOT the button ground --st-btn');
  ok(w['border-color'] === undefined && w.border && /--st-edge/.test(w.border.v),
     '...with the same edge as the buttons, so it is the same family');
}
// LANDMINE L4 (this slice's own): base #chat-input:focus is (1,1,0) and the studio block
// is LAST in the sheet, so a studio #chat-input rule at the same specificity would win
// the tie on source order and take the gold focus border with it.
{ const w = winners({ tag: 'textarea', id: 'chat-input', cls: [], pseudo: ['focus'] }, ON);
  ok(w['border-color'] && w['border-color'].v === 'var(--gold)',
     '#chat-input keeps its GOLD focus border under studio chrome (L4)'); }
{ const w = winners({ tag: 'input', id: null, cls: ['cap-inp'], pseudo: ['focus'] }, ON);
  ok(w['border-color'] && w['border-color'].v === 'var(--gold)',
     'a focused field takes the gold edge, like every other focused control'); }
// the slider joins by FAMILY only — asserted by grep, because a ::pseudo-element rule is
// not a rule about the element and the resolver deliberately does not model one.
ok(/html\[data-chrome="studio"\] \.cap-range::-webkit-slider-thumb \{ border-radius:6px; \}/
     .test(noComments),
   'the slider thumb is squared to the button corner; the track is untouched');
ok(!/html\[data-chrome="studio"\] \.cap-range \{/.test(noComments),
   '...and the track itself gets no studio rule at all');

// (g) the composer chips + the icon buttons
ok(delta({ tag: 'span', id: 'mode-agent', cls: ['mode-chip', 'on'] },
         ['font-size', 'padding', 'text-transform', 'letter-spacing', 'height']).length >= 4,
   'a composer lane chip visibly changes when studio is on');
for (const id of ['chat-send', 'chat-talk', 'chat-auto', 'chat-conv']) {
  ok(delta({ tag: 'button', id: id, cls: ['primary'] },
           ['height', 'border-radius', 'font-size', 'background']).length >= 3,
     '#' + id + ' becomes an icon button when studio is on');
}
ok(delta({ tag: 'button', id: 'chat-attach', cls: ['chip', 'chip-icon'] },
         ['height', 'border-radius', 'background']).length >= 2,
   '#chat-attach becomes an icon button when studio is on');

// D5 LANDMINES — asserted by RESOLUTION, not by grep: the state must WIN.
// L1: html[…] button (0,1,2) outranks base button.primary (0,1,1).
{ const w = winners({ tag: 'button', id: null, cls: ['primary'] }, ON);
  ok(w.background && w.background.v === 'var(--cream)',
     'button.primary keeps its cream fill under studio chrome');
  ok(w['border-color'] && w['border-color'].v === 'var(--cream)',
     'button.primary keeps its cream border under studio chrome');
  // ⚠️ FENCE MOVED 2026-08-28 (v1.5.24): this pinned the LITERAL `#171420`, and the
  // literal was the bug. Measured, a near-black label on a --cream fill is ~14:1 in every
  // dark palette and 1.08:1 in Warm Paper, where --cream is DARK ink — and the ▣ chrome
  // axis's own restatement of button.primary out-ordered the light pack's fork of it, so
  // this landmine check was pinning black-on-black into place. The ink is now var(--bg),
  // which is by construction the ground the cream fill is drawn against, so it is correct
  // in every palette (Warm Paper: 15.65). The CLAIM is unchanged and now stronger: the
  // state still WINS the cascade; it just wins with a colour a palette can reach.
  ok(w.color && w.color.v === 'var(--bg)',
     'button.primary keeps its readable dark-on-cream ink under studio chrome (L1)');
  ok(w['font-weight'] && w['font-weight'].v === '600',
     'button.primary keeps weight 600 under studio chrome'); }
  // the block writes font size/family as LONGHANDS: a `font:` shorthand is parsed only
  // after var() substitution (one bad token kills the whole declaration) AND it resets
  // font-weight, which is the property the line above depends on.
  ok(!/(^|[\s;{])font\s*:/.test(noComments),
     'the studio block never uses the font shorthand (longhands only)');
// #chat-send is the ONE filled control on the composer surface
{ const w = winners({ tag: 'button', id: 'chat-send', cls: ['primary'] }, ON);
  ok(w.background && w.background.v === 'var(--gold)',
     '#chat-send is the one FILLED composer control (gold) under studio chrome');
  // same fence move: the on-the-accent ink is a token now (--on-accent), which is what
  // lets Warm Paper give the darker gold a LIGHT ink (4.99) instead of a near-black
  // one (3.40) while every dark palette keeps the near-black it always had.
  ok(w.color && w.color.v === 'var(--on-accent)',
     '#chat-send keeps the gold-fill ink so the arrow reads in every theme'); }
// L2: studio .cap-btn (0,2,1) outranks .cap-btn.arm/.go (0,2,0).
for (const [st, want] of [['arm', 'var(--bad)'], ['go', 'var(--gold)']]) {
  const w = winners({ tag: 'button', id: null, cls: ['cap-btn', st] }, ON);
  ok(w.color && w.color.v === want,
     '.cap-btn.' + st + ' keeps ' + want + ' under studio chrome (L2)');
  ok(w['border-color'] && w['border-color'].v === want,
     '.cap-btn.' + st + ' keeps its ' + want + ' border under studio chrome');
}
// L2 class, the !important pair: the two-step deletes stay red.
for (const cls of [['cs-del', 'armed'], ['md-del', 'armed']]) {
  const w = winners({ tag: 'button', id: null, cls, anc: cls[0] === 'cs-del' ? CSACT : [] }, ON);
  ok(w.color && w.color.v.indexOf('var(--bad)') === 0,
     '.' + cls[0] + '.armed still turns red under studio chrome');
}
// L3: studio #chat-model-btn (1,2,1) outranks base .empty (1,1,0).
for (const id of ['chat-model-btn', 'chat-audio-btn']) {
  const w = winners({ tag: 'button', id: id, cls: ['mode-chip', 'empty'] }, ON);
  ok(w.color && w.color.v === 'var(--faint)',
     '#' + id + '.empty stays faint under studio chrome (L3)');
}
// active states stay gold-filled with theme-aware ink
for (const cls of [['mode-chip', 'on'], ['mp-act', 'on'], ['chip', 'caps-tab', 'on']]) {
  const w = winners({ tag: 'span', id: null, cls }, ON);
  ok(w.background && w.background.v === 'var(--gold)',
     '.' + cls[cls.length - 2] + '.on stays gold-filled under studio chrome');
  ok(w.color && w.color.v === 'var(--bg)',
     '.' + cls[cls.length - 2] + '.on uses theme-aware ink under studio chrome');
}
// Browse stays the quieter capability — outline, never filled
{ const w = winners({ tag: 'span', id: 'mode-browse', cls: ['mode-chip', 'on'] }, ON);
  ok(w.background && w.background.v === 'var(--st-btn)',
     '#mode-browse.on stays OUTLINED (never gold-filled) under studio chrome'); }
// .art-btn.on keeps its gold outline
{ const w = winners({ tag: 'button', id: null, cls: ['art-btn', 'on'] }, ON);
  ok(w.color && w.color.v === 'var(--gold)', '.art-btn.on keeps gold under studio'); }

// D3 EXEMPTIONS — asserted as NEGATIVES.
{ const w = winners({ tag: 'button', id: null, cls: ['msg-act'], anc: CMSG }, ON);
  ok(w.background && /none/.test(w.background.v) && w.border && /\b0\b/.test(w.border.v),
     'message actions (Copy/Edit/Fork/Delete) stay borderless TEXT under studio');
  ok(w.height && w.height.v === 'auto',
     'the uniform control height does not leak onto the message action row');
  ok(w.font && /var\(--mono\)/.test(w.font.v),
     'message actions keep their editorial mono small-caps'); }
{ const w = winners({ tag: 'button', id: null, cls: ['ap-btn'], anc: CMSG }, ON);
  ok(w['border-radius'] && w['border-radius'].v === '999px',
     'approval chips keep their pill radius (their identity) under studio');
  ok(w.height && w.height.v === 'auto',
     'the uniform control height does not leak onto the approval chips');
  ok(w.background && /none/.test(w.background.v),
     'approval chips keep their unfilled ground, so a gold .on pick still reads'); }
for (const el of [{ tag: 'span', id: null, cls: ['mpill'] },
                  { tag: 'span', id: null, cls: ['cap-pill'] },
                  { tag: 'summary', id: null, cls: [] }]) {
  ok(delta(el, ['background', 'border-radius', 'padding', 'font', 'font-size',
                'font-family', 'height', 'text-transform', 'color',
                'border-color']).length === 0,
     'studio chrome leaves ' + (el.id || el.cls[0] || el.tag) + ' untouched (exempt)');
}
// #chat-input is the PARTIAL exemption §C names: the ground, the edge and the corner
// join the family; the 14px prose sizing and the height do not.
ok(delta({ tag: 'textarea', id: 'chat-input', cls: [] },
         ['background', 'border-color', 'border-radius']).length === 3,
   'the chat composer joins the family on ground / edge / corner only');
ok(delta({ tag: 'textarea', id: 'chat-input', cls: [] },
         ['font', 'font-size', 'font-family', 'height', 'padding']).length === 0,
   '...and keeps its own 14px prose sizing, padding and height (§C exemption)');
// NEGATIVE: with the attribute ABSENT no studio selector can match anything.
ok(!sels.some(s => matchSel(splitTop(s, ',')[0].trim(),
                            { tag: 'button', id: null, cls: ['chip'] },
                            [OFF, { tag: 'body', id: null, cls: [] }])),
   'no studio rule matches anything while the attribute is absent');

// ---------------------------------------------------------------------------
// (B) THE VALUE-LEVEL NO-OP DETECTOR (2026-08-14h). A rule that WINS can still be a
// no-op, and that is what three Mac reports actually were. Resolve the tokens for
// real and demand a PERCEPTUAL delta, plus the right hover direction, per theme.
// ---------------------------------------------------------------------------
{
  const tok = {};
  for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\s*[;}]/g)) {
    if (!(m[1] in tok)) tok[m[1]] = m[2];       // FIRST wins = the dark :root default
  }
  for (const t of ['--st-btn', '--st-hi', '--st-edge', '--st-inp',
                   '--card', '--card2', '--line2', '--bg2', '--fg', '--cream']) {
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
  ok(tok['--st-btn'] !== tok['--card2'] && tok['--st-btn'] !== tok['--card'],
     'the studio ground is its own value, not an alias of --card/--card2');
  ok(tok['--st-edge'] !== tok['--line2'],
     'the studio border colour differs from --line2 (the base border-color — setting '
     + 'it again is a literal no-op)');
  ok(tok['--st-hi'] !== tok['--st-btn'], 'hover is not the resting ground restated');
  // PHASE 2 §C — the FIELD ground. ⚠️ HONEST NOTE, and it is a builder call recorded
  // rather than hidden: §C asks for ≥1.3 against the card surface, but the same
  // sentence asks for a value DARKER than --st-btn (so a field reads as a well, not a
  // button). On this palette no colour satisfies both — --st-btn itself is only 1.41
  // off --card — so what is asserted here is the INTENT, which is falsifiable in every
  // direction that matters: it is nobody else's colour, it is on the right side of the
  // button ground, its label is readable on it, and it is not a no-op (a value equal to
  // --card2, the base field ground, would be exactly the no-op this detector exists for).
  ok(tok['--st-inp'] !== tok['--card'] && tok['--st-inp'] !== tok['--card2']
     && tok['--st-inp'] !== tok['--st-btn'] && tok['--st-inp'] !== tok['--bg2'],
     'the field ground is its own value, not an alias of --card/--card2/--st-btn/--bg2');
  ok(lum(tok['--st-inp']) < lum(tok['--st-btn']),
     'on the dark palette a field RECEDES below the button ground (it is a well)');
  ok(ratio(tok['--cream'], tok['--st-inp']) >= 4.5,
     'the text you type clears AA on the field ground (ratio '
     + ratio(tok['--cream'], tok['--st-inp']).toFixed(2) + ')');
  ok(ratio(tok['--st-edge'], tok['--st-inp']) >= 1.15,
     'the field border is visible against the field ground (ratio '
     + ratio(tok['--st-edge'], tok['--st-inp']).toFixed(2) + ')');
  // (2) it must be VISIBLE against every surface a control sits on
  for (const bg of ['--card', '--bg2', '--bg']) {
    if (!tok[bg]) continue;
    ok(ratio(tok['--st-btn'], tok[bg]) >= 1.3,
       'the studio ground is perceptible against ' + bg + ' (ratio '
       + ratio(tok['--st-btn'], tok[bg]).toFixed(2) + ' >= 1.3)');
  }
  // (2b) …and the label on it must be readable (the reason --fg replaced --dim)
  ok(ratio(tok['--fg'], tok['--st-btn']) >= 4.5,
     'the control label (--fg) clears AA on the studio ground (ratio '
     + ratio(tok['--fg'], tok['--st-btn']).toFixed(2) + ')');
  ok(ratio(tok['--st-edge'], tok['--st-btn']) >= 1.15,
     'the border is visible against its own ground (ratio '
     + ratio(tok['--st-edge'], tok['--st-btn']).toFixed(2) + ')');
  // (3) hover must go LIGHTER than rest on dark — the shipped compact build inverted it
  ok(lum(tok['--st-hi']) > lum(tok['--st-btn']),
     'studio hover is LIGHTER than the resting ground on the dark palette');
  // (4) NO studio declaration may restate a value the base sheet already computes.
  for (const el of [{ tag: 'button', id: null, cls: [] },
                    { tag: 'button', id: null, cls: ['cap-btn'] },
                    { tag: 'span', id: 'mode-agent', cls: ['mode-chip'] },
                    { tag: 'span', id: null, cls: ['chip'] },
                    { tag: 'button', id: 'cs-new', cls: [] },
                    { tag: 'button', id: null, cls: ['hfget'] },
                    { tag: 'button', id: null, cls: ['art-btn'] },
                    { tag: 'span', id: null, cls: ['mp-act'] }]) {
    const a = winners(el, OFF), b = winners(el, ON);
    for (const p of ['background', 'border-color']) {
      if (!(b[p] && /--st-/.test(b[p].v))) continue;
      ok((a[p] && a[p].v) !== b[p].v,
         'studio ' + p + ' on ' + (el.id || el.cls[0] || el.tag)
         + ' is a real change, not a restatement of the base value');
    }
  }
  // (5) the light axis gets its own three tokens, or dark slate lands on warm paper
  ok(/html\[data-chrome="studio"\]\[data-theme="light"\]/.test(noComments),
     'the studio axis carries a light-theme override for its own surface tokens');
  {
    const lr = (noComments.match(
      /html\[data-chrome="studio"\]\[data-theme="light"\]\s*\{([^}]*)\}/) || [null, ''])[1];
    const lt = {};
    for (const m of lr.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,6})/g)) lt[m[1]] = m[2];
    for (const t of ['--st-btn', '--st-hi', '--st-edge', '--st-inp']) {
      ok(typeof lt[t] === 'string', 'the light override defines ' + t);
      ok(lt[t] !== tok[t], 'the light ' + t + ' is not the dark value');
    }
    // light surfaces: --card #ffffff (cards, dialogs, the model popover) and the
    // page paper --bg2 #f2eee3 / --bg #faf7f0. ⚠️ The paper pair is the FLOOR of
    // Fable's final palette (1.21), not the 1.3 the dark axis clears — asserted at
    // 1.15 so an ALIAS or a no-op (ratio 1.0) still trips, which is what this
    // detector exists for, while a deliberate palette value is not overruled here.
    ok(ratio(lt['--st-btn'], '#ffffff') >= 1.3,
       'the light studio ground is perceptible on a white card (ratio '
       + ratio(lt['--st-btn'], '#ffffff').toFixed(2) + ')');
    for (const bg of ['#f2eee3', '#faf7f0']) {
      ok(ratio(lt['--st-btn'], bg) >= 1.15,
         'the light studio ground is distinguishable from the paper ' + bg + ' (ratio '
         + ratio(lt['--st-btn'], bg).toFixed(2) + ')');
    }
    ok(ratio(lt['--st-edge'], lt['--st-btn']) >= 1.15,
       'the light border is visible against the light ground');
    // direction INVERTS on paper: hover darkens.
    ok(lum(lt['--st-hi']) < lum(lt['--st-btn']),
       'light-theme hover DARKENS (the inverse of dark theme, and correct on paper)');
    // …and the well INVERTS with it: on paper a field is lighter than the button, which
    // is the same design rule (a field recedes toward the page) with the sign flipped.
    ok(lum(lt['--st-inp']) > lum(lt['--st-btn']),
       'on paper a field RISES above the button ground — the well rule, inverted');
    ok(ratio('#171420', lt['--st-inp']) >= 4.5,
       'dark ink clears AA on the light field ground');
  }
}

// ---------------------------------------------------------------------------
// RUNTIME SELF-CHECK, retargeted. The next report must be ground truth, not a
// description: toggleChrome reads the attribute BACK and asks getComputedStyle what
// real controls resolved to — now including #chat-send, the one control that becomes
// an ICON button, so the composer half of the axis is provable from the feed alone.
// ---------------------------------------------------------------------------
ok(/function chromeProbe\(\)/.test(html), 'chromeProbe() exists');
{
  const pf = html.slice(html.indexOf('function chromeProbe()'));
  const pb = pf.slice(0, pf.indexOf('\n}') + 2);
  ok(/getAttribute\('data-chrome'\)/.test(pb),
     'the probe reads the attribute BACK off <html> (not the variable it just set)');
  ok(/getComputedStyle\(/.test(pb),
     'the probe asks the BROWSER what it computed, not the stylesheet');
  for (const p of ['borderRadius', 'backgroundColor', 'fontSize', 'textTransform',
                   'height']) {
    ok(pb.includes(p), 'the probe reports ' + p);
  }
  ok(/getElementById\('chat-send'\)/.test(pb),
     'the probe also reads #chat-send (the icon button)');
  ok(/'studio=' \+ attr/.test(pb), 'the probe names the axis it is reporting on');
  ok(/try\s*\{/.test(pb) && /catch/.test(pb),
     'the probe never throws (a self-check must not break what it watches)');
  ok(!/setAttribute|removeAttribute|\.style\./.test(pb),
     'the probe writes nothing — it only observes');
  const t = html.slice(html.indexOf('function toggleChrome()'));
  const tb = t.slice(0, t.indexOf('\n}') + 2);
  ok(tb.indexOf("dataset.chrome = 'studio'") < tb.indexOf('chromeProbe()'),
     'toggleChrome() probes AFTER setting the attribute');
  ok(/feed\('chrome',\s*p\)/.test(tb),
     'the probe result reaches the activity feed (visible without a console)');
  ok(/console\.log/.test(tb), 'the probe result is also logged to the console');
}

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
