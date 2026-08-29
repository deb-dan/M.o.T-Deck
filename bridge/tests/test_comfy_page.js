/* THE GENERATE PAGE (bridge/panel/comfy.html) — its pure half, and the ALL-DESIGNS rule.
 *
 * Run: node bridge/tests/test_comfy_page.js
 *
 * WHAT THIS GUARDS, group by group:
 *
 *  1. NOTHING EXTERNAL. The office.html lesson, as a gate: a render-blocking <link> or a
 *     <script src> that never resolves produces a blank rectangle and no further script
 *     in the document runs. This page must be self-contained, so the failure mode is
 *     unrepresentable rather than merely unlikely.
 *
 *  2. THE PURE FUNCTIONS, EXECUTED — extracted from the SHIPPED source, not retyped.
 *     `gb()` must agree with the bridge's own decimal-GB spelling (a number that changes
 *     unit as it crosses the wire is a small lie that costs a lot of trust), and
 *     `cardAction()` is the single source of the word "downloaded" on this page.
 *
 *  3. ALL DESIGNS (Debi's standing rule). Editorial + the three packs + studio
 *     light/dark, verified structurally: every pack is a token-only block, every colour
 *     in the page's own rules resolves through var(--…), and no rule hard-codes a hex.
 *     A page verified in one look only is NOT verified — and the --on-wash / --on-accent
 *     incidents are exactly what an unreachable literal costs.
 *
 *  4. THE HONESTY STRINGS. The claims this surface makes about itself have to be IN the
 *     page: the stock-node fence, the keep-everything gallery, the "not measured yet"
 *     wording, and the missing-model refusal that carries its own Download button.
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'comfy.html'), 'utf8');
const py = fs.readFileSync(path.join(ROOT, 'bridge', 'routers', 'comfy.py'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok   ' : '  FAIL ') + msg); if (!cond) fails++; }

// ── 1. nothing external ──────────────────────────────────────────────────────
console.log('\n1. the document is self-contained');
ok(!/<link\b/i.test(html), 'no <link> at all (no stylesheet can hang the parse)');
ok(!/<script[^>]+\bsrc=/i.test(html), 'no <script src=> — every script is inline');
ok(!/https?:\/\/(?!huggingface|127\.0\.0\.1)/.test(css), 'the CSS fetches nothing');
ok(!/@import/.test(css), 'no @import in the stylesheet');
ok(!/<img[^>]+src=["']http/i.test(html), 'no remote images');

// ── 2. the pure functions, executed ──────────────────────────────────────────
console.log('\n2. the pure functions, taken from the shipped source');
const start = html.indexOf('function gb(n)');
const end = html.indexOf('async function api(');
ok(start > 0 && end > start, 'the pure block is where the test expects it');
const M = new Function(html.slice(start, end) + '\nreturn { gb, secs, cardAction };')();

ok(M.gb(0) === 'nothing', 'gb(0) says "nothing", not "0 kB"');
ok(M.gb(9828025775) === '9.83 GB', 'gb() is DECIMAL GB — 9,828,025,775 B → 9.83 GB');
ok(M.gb(253815318) === '254 MB', 'gb() steps down to MB');
ok(M.gb(null) === '?', 'gb(null) is "?", never "0"');
// The same numbers the bridge prints, so a size never changes unit mid-page.
ok(/def gb\(/.test(py) && /1e9/.test(py.replace(/1_000_000_000/g, '1e9')),
   'the bridge uses the same decimal-GB rule (its gb() is the mirror of this one)');
ok(M.secs(45) === '45s' && M.secs(600) === '10.0 min' && M.secs(null) === '—',
   'secs() reads as a human would say it, and null is a dash rather than "0s"');

const base = { need_h: '9.83 GB', downloaded: false, corrupt: [], partial_bytes: 0 };
ok(M.cardAction(base, null).label === 'Download 9.83 GB', 'a fresh card offers the size');
ok(M.cardAction({ ...base, downloaded: true }, null).done === true,
   'a complete card says "On disk" and has no action');
ok(M.cardAction({ ...base, downloaded: true, corrupt: ['x'] }, null).act === 'download',
   'LIE GUARD: a card with a wrong-size file offers RE-download even if every other '
   + 'file is present — it must never present as finished');
ok(/already down/.test(M.cardAction({ ...base, partial_bytes: 2.4e9 }, null).label),
   'a .part on disk offers RESUME and states how much is already down '
   + '(the bridge-restarted-mid-download case, walked live)');
ok(M.cardAction(base, { state: 'downloading' }).busy === true,
   'a running download shows as busy…');
ok(M.cardAction(base, { state: 'verifying' }).busy === true,
   '…and so does the sha-verification pass (it is not "done" until the hash matches)');
ok(M.cardAction(base, { state: 'error' }).label === 'Retry download',
   'a failed download offers a retry rather than going dead');

// ── 3. all designs ───────────────────────────────────────────────────────────
console.log('\n3. every design this page can render in');
for (const sel of ['html[data-theme="light"]', 'html[data-theme="gold"]',
                   'html[data-theme="cyber"]', 'html[data-design="studio"]',
                   'html[data-design="studio"][data-dvariant="light"]',
                   'html[data-chrome="studio"]']) {
  ok(css.includes(sel), `${sel} has a block`);
}
// A pack is a TOKEN SWAP and nothing else — the panel's own guardrail, restated here.
for (const pack of ['gold', 'cyber']) {
  const blk = css.split(`html[data-theme="${pack}"] {`)[1].split('}')[0];
  const decls = blk.split(';').map(s => s.trim()).filter(Boolean);
  ok(decls.every(d => d.startsWith('--')),
     `the ${pack} pack declares ONLY custom properties (${decls.length} of them)`);
}
// No literal colours in the page's own rules: an unreachable hex is how --on-wash and
// --on-accent were each discovered, twice, in a shipped look nobody had opened.
const body = css.split('* { box-sizing')[1] || '';
const hexes = (body.match(/#[0-9a-fA-F]{3,8}\b/g) || []);
ok(hexes.length === 0, `no hard-coded colour in any layout rule (found ${hexes.join(', ') || 'none'})`);
const rgba = (body.match(/rgba?\(/g) || []);
ok(rgba.length === 0, 'no hard-coded rgba() either');
// The three axes are read, never written — a tab that could disagree with the app it
// lives in is the original complaint.
ok(!/localStorage\.setItem\(\s*['"]harness-(theme|chrome|design)/.test(html),
   'the page NEVER writes the panel\'s three appearance keys');
ok(/getItem\('harness-theme'\)/.test(html) && /getItem\('harness-chrome'\)/.test(html)
   && /getItem\('harness-design'\)/.test(html), '…it only reads all three');
ok(html.indexOf('function skin()') < html.indexOf('<style>'),
   'the skin is applied in the HEAD, before the stylesheet — no dark-then-flip flash');
ok(/addEventListener\('storage', skin\)/.test(html),
   'a flip in the panel reaches this tab live (storage event)');
ok(/:focus-visible/.test(css), 'keyboard focus is visible in every design');
// ⚠️ THE STUDIO DESIGN'S TYPOGRAPHY IS A TOKEN SWAP, and this pins WHY. The first
// draft used `:where(html[data-design="studio"]) h1 { font-family: … }`, which is
// specificity (0,0,1) — exactly what the base `h1` rule is — so the later base rule
// won and studio silently kept the serif. Caught by reading computed styles in the
// live page, not by reading the CSS. Restating --serif cannot lose that race.
const cssNC = css.replace(/\/\*[\s\S]*?\*\//g, '');
const studioBlk = cssNC.split('html[data-design="studio"] {')[1].split('}')[0];
ok(/--serif:\s*var\(--sans\)/.test(studioBlk),
   'studio goes sans by restating --serif, not by a selector that ties on specificity');
ok(!/data-design="studio"[^{]*\bh1\b/.test(cssNC),
   '…and there is no equal-specificity h1 override left to lose that race');

// ── 4. the honesty strings ───────────────────────────────────────────────────
console.log('\n4. what the page claims about itself');
ok(/Stock nodes only/.test(html), 'the stock-node fence is stated on the page');
ok(/custom_nodes/.test(html), '…naming the directory that stays empty');
ok(/reported as downloaded/.test(html) && /pinned sha256/.test(html),
   'the sha/size pledge is on the page, next to the buttons it constrains');
ok(/Nothing here is ever deleted automatically/.test(html),
   'the keep-everything gallery says so');
ok(/the next one is the measurement/.test(html),
   'an unmeasured model says "never run here" instead of inventing an ETA');
ok(/Cannot run — model file missing/.test(html),
   'the missing-model refusal is named…');
ok(/validationBox/.test(html) && /Download ' \+\s*\n?\s*esc\(m\.pick_title\)|Download ' \+ esc\(m\.pick_title\)/.test(html.replace(/\s+/g, ' ')),
   '…and carries the Download button that fixes it');
ok(/free space on the volume they land on/.test(html),
   'the empty state explains where the disk number comes from');
ok(/shared with the ComfyUI tab/.test(html),
   'the page says a model downloaded here also serves the ComfyUI tab');
// The page's VISIBLE text must never promise a time it has not measured. (The word
// appears once in the head comment, explaining exactly that — hence body-only.)
const visible = html.split('</style>').slice(1).join('</style>');
ok(!/\bETA\b/.test(visible),
   'the word ETA appears nowhere the user can read it — we never invent one');
ok(/data-act="reveal"/.test(html) && /data-act="graph"/.test(html),
   'every gallery item can be revealed in Finder and can show its exact graph');

console.log(`\n${checks - fails}/${checks} checks passed`);
process.exit(fails ? 1 : 0);
