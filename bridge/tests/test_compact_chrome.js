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

ok(sels.length === 18, 'the compact block declares exactly 18 rules (got ' + sels.length + ')');

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
// It must not restyle content typography (headers/body/messages).
for (const s of ['h1', '.brand', '.cmsg', '.body', 'body {']) {
  ok(!sels.some(x => x.includes(' ' + s)),
     'the block does not restyle content element: ' + s);
}

// ---------- the controls Fable named are actually covered ----------
for (const target of ['.chip', '.chip.chip-icon', '.caps-tab.on', '.mp-act',
                      '.mode-chip', '#chat-model-btn', '#chat-audio-btn',
                      'button.primary']) {
  ok(sels.some(x => x.includes(target)), 'compact chrome covers ' + target);
}
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

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
