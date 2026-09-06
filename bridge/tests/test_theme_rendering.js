/* S24/S25/A9 — engine-wide live-theme regression fence.
 *
 * These are WebKit failures measured in the installed app, so this suite guards the
 * source shapes that made them possible instead of pretending jsdom can emulate the
 * renderer. Run: node bridge/tests/test_theme_rendering.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const PANEL = path.join(ROOT, 'bridge', 'panel');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

function filesUnder(dir) {
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...filesUnder(p));
    else if (/\.(html|css)$/.test(ent.name)) out.push(p);
  }
  return out;
}

// Flat CSS rules are enough for these predicates: nested @media bodies still expose
// their inner selector blocks to the global matcher. Comments are removed first so a
// documented counterexample cannot be mistaken for shipped CSS.
function rules(src) {
  src = src.replace(/\/\*[\s\S]*?\*\//g, '');
  const out = [];
  for (const m of src.matchAll(/([^{}]+)\{([^{}]*)\}/g))
    out.push({ sel: m[1].trim(), body: m[2] });
  return out;
}

const allFiles = filesUnder(PANEL);
const allRules = [];
for (const file of allFiles) {
  const src = fs.readFileSync(file, 'utf8');
  for (const rule of rules(src)) allRules.push({ file, ...rule });
}

// S24. A pseudo-element that paints background directly from a token can hold the old
// color after a live root-token change in the app's WebKit. The owning real element
// carries the token; the pseudo paints currentColor.
const pseudoTokenPaint = allRules.filter(r =>
  /::(?:before|after)/.test(r.sel)
  && /background(?:-color)?\s*:\s*var\(--/.test(r.body));
ok(pseudoTokenPaint.length === 0,
   'S24: no panel pseudo-element paints its background directly from a token'
   + (pseudoTokenPaint.length ? ' — ' + pseudoTokenPaint.map(r =>
     path.relative(ROOT, r.file) + ' ' + r.sel).join(' | ') : ''));

const namedCurrentColor = [
  ['compose.html', '.btn.dotted::after'],
  ['office.html', '#rail-resize::after,#ai-resize::after'],
  ['index.html', '#chat-audiosw::after'],
  ['index.html', '#cs-resize::after'],
  ['index.html', '#art-divider::after'],
  ['index.html', '#art-canvas-divider::after'],
];
for (const [name, selector] of namedCurrentColor) {
  const found = allRules.find(r => path.basename(r.file) === name
    && r.sel.replace(/\s+/g, '') === selector.replace(/\s+/g, ''));
  ok(found && /background\s*:\s*currentColor/.test(found.body),
     `S24: ${name} ${selector} still draws through currentColor`);
}

// S25. Aggregate repeated rules by file+selector, then forbid a transition on any
// property whose own declaration is calc(var(...)). This catches a split declaration
// as well as the easy same-block form.
const grouped = new Map();
for (const r of allRules) {
  const key = r.file + '\0' + r.sel.replace(/\s+/g, ' ');
  grouped.set(key, (grouped.get(key) || '') + ';' + r.body);
}
const calcTransition = [];
for (const [key, body] of grouped) {
  const calcProps = [...body.matchAll(/(?:^|;)\s*([\w-]+)\s*:\s*[^;]*calc\(\s*var\(--/g)]
    .map(m => m[1]);
  const transitions = [...body.matchAll(/(?:^|;)\s*transition\s*:\s*([^;]+)/g)]
    .map(m => m[1]).join(',');
  for (const prop of calcProps) {
    if (new RegExp(`(?:^|[,\\s])(?:all|${prop})(?:[,\\s]|$)`).test(transitions))
      calcTransition.push(key.replace('\0', ' ') + ' -> ' + prop);
  }
}
ok(calcTransition.length === 0,
   'S25: no calc(var(...)) property is transitioned anywhere in the panel'
   + (calcTransition.length ? ' — ' + calcTransition.join(' | ') : ''));

// A9. Studio owns its palette. The light variant must appear in the external sheet,
// that sheet must be appended after the inline/theme styles, and every Editorial
// palette token must be restated by studio-dark (with studio-light overriding it).
const index = fs.readFileSync(path.join(PANEL, 'index.html'), 'utf8');
const studio = fs.readFileSync(path.join(PANEL, 'assets', 'studio-design.css'), 'utf8');
const inline = index.split('<style>')[1].split('</style>')[0];
function tokens(block) {
  const out = {};
  for (const m of block.matchAll(/(--[\w-]+)\s*:\s*([^;]+)/g)) out[m[1]] = m[2].trim();
  return out;
}
function bodyFor(src, selector) {
  const r = rules(src).find(x => x.sel === selector);
  return r ? r.body : '';
}
const base = tokens(bodyFor(inline, ':root'));
const dark = tokens(bodyFor(studio, 'html[data-design="studio"]'));
const light = tokens(bodyFor(studio,
  'html[data-design="studio"][data-dvariant="light"]'));
const paletteNames = Object.keys(base).filter(n => n !== '--mono' && n !== '--serif');
ok(paletteNames.every(n => Object.prototype.hasOwnProperty.call(dark, n)),
   'A9: Studio restates every base palette token, so retained Gold/Cyber cannot bleed in');
ok(Object.keys(light).length >= 16,
   'A9: Studio-light carries a complete light override rather than a partial tint');
ok(/document\.head\.appendChild\(el\)/.test(index)
   && /el\.href = '\/assets\/studio-design\.css'/.test(index),
   'A9: the Studio asset is appended after inline theme-pack CSS, so equal specificity wins');

console.log(`\ntheme rendering: ${checks - fails}/${checks} checks passed`);
if (fails) process.exit(1);
