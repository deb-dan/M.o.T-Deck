/* THE GENERATE PAGE (bridge/panel/comfy.html) — v2, the chip-first surface.
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
 *  2. THE PURE FUNCTIONS AND THE VERDICT OBJECTS, EXECUTED — extracted from the SHIPPED
 *     source, not retyped. `gb()` must agree with the bridge's own decimal-GB spelling,
 *     `cardAction()` is the single source of the word "downloaded", and every verdict
 *     object must feed its chip AND its tooltip off ONE object (the v1.5.34 ruling:
 *     a chip that can disagree with its own hover is the lie this structure prevents).
 *
 *  3. THE AT-REST BUDGET AND THE SENTENCE RULE — the reason v2 exists. The whole page
 *     script is executed against a stub DOM, every state is rendered, and the emitted
 *     markup is parsed into (text node → nearest enclosing class) pairs. A sentence
 *     (≥8 words) may appear ONLY inside `.say`, `.say` may appear only as often as the
 *     rule allows, and chips must stay chip-length. This is element-class-based: it
 *     does not care what any sentence says, only where sentences are allowed to live.
 *     v1 measured 106 standing text elements / 27 standing sentences on a live render.
 *
 *  4. ALL DESIGNS (Debi's standing rule). Editorial + the three packs + studio
 *     light/dark, verified structurally: every pack is a token-only block, every colour
 *     in the page's own rules resolves through var(--…), and no rule hard-codes a hex.
 *
 *  5. THE HONESTY LEDGER (§5 of docs/research/2026-08-29-generate-page-redesign.md).
 *     Every mechanic the v1 page carried must still be REACHABLE in v2 — demoted to a
 *     chip, a hover, a sheet row or an overflow item, never deleted. Each row of that
 *     table is one assertion here.
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

// ══ THE HARNESS ══════════════════════════════════════════════════════════════
// The page's whole body script is executed in a stub DOM. Everything it writes with
// innerHTML is recorded, so the at-rest audit below is a MEASUREMENT of what the page
// would paint — not a grep over its source.
function makeEnv() {
  const written = [];
  const esc = (s) => String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function node(id) {
    return {
      id, _html: '', _text: '', className: '', hidden: false, title: '',
      dataset: {}, style: {}, childNodes: [], value: '',
      offsetWidth: 100, offsetHeight: 40,
      get innerHTML() { return this._html; },
      set innerHTML(v) { this._html = String(v); written.push({ id, html: String(v) }); },
      get textContent() { return this._text; },
      set textContent(v) { this._text = String(v); written.push({ id, html: esc(String(v)) }); },
      classList: {
        _s: new Set(),
        add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
        toggle(c, on) { if (on) this._s.add(c); else this._s.delete(c); },
        contains(c) { return this._s.has(c); },
      },
      setAttribute() {}, hasAttribute() { return false; }, removeAttribute() {},
      getAttribute() { return null; },
      addEventListener() {}, appendChild() {}, remove() {},
      querySelectorAll() { return { forEach() {} }; },
      querySelector() { return null; },
      closest() { return null; },
      getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, right: 0 }; },
    };
  }
  const nodes = {};
  const document = {
    getElementById(id) { return (nodes[id] = nodes[id] || node(id)); },
    createElement(t) { return node('new:' + t); },
    addEventListener() {},
    body: node('body'),
    documentElement: node('html'),
    activeElement: null,
    querySelectorAll() { return { forEach() {} }; },
  };
  const win = {
    innerWidth: 1200, innerHeight: 900, addEventListener() {},
    location: { origin: 'http://127.0.0.1:8700' }, open() { return null; },
  };
  return { written, nodes, document, window: win };
}

const bodyScript = html.split('<script>').pop().split('</script>')[0];
function runPage(state, gallery, mutate) {
  const env = makeEnv();
  const fn = new Function(
    'document', 'window', 'localStorage', 'fetch', 'EventSource', 'setTimeout',
    'clearTimeout', 'addEventListener', 'location',
    bodyScript + '\n;return { S, render, gb, secs, cardAction, stateVerdict, ' +
    'licenseVerdict, healthVerdict, measuredVerdict, diskVerdict, engineVerdict, ' +
    'modelVerdict, itemVerdict, tipHtml, tipPlain, refusalHtml };');
  const M = fn(
    env.document, env.window, { getItem() { return null; }, setItem() {} },
    () => new Promise(() => {}),                       // load() never resolves: inert
    function () { return { onmessage: null }; },
    () => 0, () => {}, () => {}, env.window.location);
  M.S.state = state;
  M.S.gallery = gallery;
  if (mutate) mutate(M.S);
  env.written.length = 0;
  M.render();
  return { M, env, markup: env.written.map(w => w.html).join('\n') };
}

/* A tiny text extractor: walk the emitted markup, track the class of the innermost open
   element, and emit {cls, text} for every non-empty text node. Attribute values (where
   the tooltip payloads and titles live) are skipped by construction, which is exactly
   the point — a tooltip is not standing prose. */
function textNodes(markup) {
  const out = [];
  const stack = [{ cls: '' }];
  const re = /<\/?([a-zA-Z0-9]+)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
  let last = 0, m;
  const push = (t) => {
    const s = t.replace(/&[a-z]+;|&#\d+;/g, 'x').replace(/\s+/g, ' ').trim();
    if (s) out.push({ cls: stack[stack.length - 1].cls, text: s });
  };
  const VOID = ['br', 'img', 'input', 'i', 'hr', 'meta'];
  while ((m = re.exec(markup))) {
    push(markup.slice(last, m.index));
    last = re.lastIndex;
    if (m[0][1] === '/') { if (stack.length > 1) stack.pop(); }
    else if (!/\/\s*$/.test(m[2]) && !VOID.includes(m[1].toLowerCase())) {
      const c = /class\s*=\s*"([^"]*)"/.exec(m[2]);
      stack.push({ cls: c ? c[1] : '' });
    }
  }
  push(markup.slice(last));
  return out;
}
const words = (s) => s.split(/\s+/).filter(Boolean).length;
function audit(env) {
  const all = [];
  for (const w of env.written) all.push(...textNodes(w.html));
  return all;
}

// ── the fixtures ─────────────────────────────────────────────────────────────
const FILE = (n, st) => ({ directory: 'diffusion_models', name: n, bytes: 2838303560,
                           state: st || 'present', present: st ? false : true,
                           on_disk_bytes: 2838303560, shared: null });
const WAN = {
  id: 'wan', title: 'Wan 2.1 T2V 1.3B', vendor: 'Alibaba', template: 'text_to_video_wan',
  modes: ['image', 'video'], starter: true, role: 'video', note: 'the video half',
  license: 'Apache-2.0', license_badge: 'green', license_note: 'Apache-2.0, read from the repo.',
  license_url: 'https://huggingface.co/x/LICENSE.txt',
  files: [FILE('wan.safetensors')], total_bytes: 9828025775, need_bytes: 0,
  partial_bytes: 0, total_h: '9.83 GB', need_h: 'nothing', downloaded: true, corrupt: [],
  registry_drift: null, disk: { level: 'done', text: '9.83 GB already on disk' },
  defaults: { image: { width: 832, height: 480, steps: 25 },
              video: { width: 832, height: 480, steps: 25, frames: 33, fps: 16 } },
  negative_default: 'blurry', health: { video: 'the COLOURS are wrong, measured 2026-08-29' },
  measured: { video: { wall_s: 176, peak_bytes: 31057765016, label: '832×480 · 17f' } },
};
const SDXL = {
  id: 'sdxl', title: 'SDXL base 1.0', vendor: 'Stability AI', template: 'image_sdxl_simple',
  modes: ['image'], starter: true, role: 'image', note: 'the image half',
  license: 'CreativeML Open RAIL++-M', license_badge: 'amber',
  license_note: 'Open RAIL++-M with use restrictions.',
  license_url: 'https://huggingface.co/y/LICENSE.md',
  files: [FILE('sdxl.safetensors')], total_bytes: 6938040714, need_bytes: 0,
  partial_bytes: 0, total_h: '6.94 GB', need_h: 'nothing', downloaded: true, corrupt: [],
  registry_drift: null, disk: { level: 'done', text: '6.94 GB already on disk' },
  defaults: { image: { width: 1024, height: 1024, steps: 25 } },
  negative_default: '', health: {},
  measured: { image: { wall_s: 38.3, peak_bytes: 13265768096, label: '1024×1024' } },
};
const notOnDisk = (c) => Object.assign({}, c, {
  downloaded: false, need_bytes: c.total_bytes, need_h: c.total_h, measured: {},
  files: c.files.map(f => Object.assign({}, f, { state: 'absent', present: false })),
  disk: { level: 'ok', text: 'needs ' + c.total_h + ' · 47.80 GB free · leaves ~38 GB' } });

const BASE = {
  ok: true,
  comfy: { up: true, port: 8188, url: 'http://127.0.0.1:8188', version: '0.34.1',
           torch: '2.15.0', templates_version: '0.11.48', custom_nodes: [], error: null },
  curation: {
    picks: [WAN, SDXL],
    cap: { over: true, text: 'The starter set is 16.77 GB — 2.77 GB OVER the 14.00 GB budget.' },
    disk: { ok: true, free_bytes: 59119734784, total_bytes: 994610155520,
            measured_at: '/x/models' },
    models_dir: '/x/models',
  },
  downloads: [], jobs: [], gallery_total_h: '2 MB', gallery_count: 1,
  output_dir: '/x/output', fence: { custom_nodes: [] },
};
const STATE = (over) => Object.assign({}, BASE, over || {});
const GAL = {
  ok: true, total_h: '2 MB', output_dir: '/x/output',
  items: [{ filename: 'image_00002_.png', subfolder: 'harness', job: 'j1', pick: 'sdxl',
            pick_title: 'SDXL base 1.0', mode: 'image', prompt: 'a red fox in the snow',
            seed: 128339186323896, steps: 25, shape: '1024×1024', wall_s: 38.3,
            peak_bytes: 13265768096, bytes: 1578515, size_h: '2 MB', state: 'ok',
            kind: 'image' }],
};

// ── 2. the pure functions + the verdict objects ──────────────────────────────
console.log('\n2. the pure functions and the verdict objects, taken from the shipped source');
const daily = runPage(STATE(), GAL);
const M = daily.M;
ok(M.gb(0) === 'nothing', 'gb(0) says "nothing", not "0 kB"');
ok(M.gb(9828025775) === '9.83 GB', 'gb() is DECIMAL GB — 9,828,025,775 B → 9.83 GB');
ok(M.gb(253815318) === '254 MB', 'gb() steps down to MB');
ok(M.gb(null) === '?', 'gb(null) is "?", never "0"');
ok(/def gb\(/.test(py) && /1e9/.test(py.replace(/1_000_000_000/g, '1e9')),
   'the bridge uses the same decimal-GB rule (its gb() is the mirror of this one)');
ok(M.secs(45) === '45s' && M.secs(600) === '10.0 min' && M.secs(null) === '—',
   'secs() reads as a human would say it, and null is a dash rather than "0s"');

const base = { id: 'x', need_h: '9.83 GB', total_bytes: 9828025775, downloaded: false,
               corrupt: [], partial_bytes: 0, files: [{}], disk: { text: 'needs …' } };
ok(M.cardAction(base, null).label === 'Get 9.83 GB', 'a fresh row offers the size as a chip');
ok(M.cardAction({ ...base, downloaded: true }, null).done === true,
   'a complete row says "On disk ✓" and has no action');
ok(M.cardAction({ ...base, downloaded: true, corrupt: ['x'] }, null).act === 'download',
   'LIE GUARD: a row with a wrong-size file offers RE-download even if every other '
   + 'file is present — it must never present as finished');
ok(/^Resume · 2\.40 GB of 9\.83 GB$/.test(
     M.cardAction({ ...base, partial_bytes: 2.4e9, need_bytes: 7428025775 }, null).label),
   'a .part on disk offers RESUME and states how much is already down '
   + '(the bridge-restarted-mid-download case, walked live)');
// WALKED DEFECT (2026-08-29): the denominator is the OUTSTANDING work, not the model.
// One 254 MB file cancelled inside an otherwise complete 9.83 GB pick must not read
// "Resume · 212 MB of 9.83 GB" — that says 2% when the truth is 98%.
ok(M.cardAction({ ...base, partial_bytes: 212e6, need_bytes: 42e6 }, null).label
     === 'Resume · 212 MB of 254 MB',
   '…against what is left to fetch, not against the whole model');
ok(M.cardAction(base, { state: 'downloading', pct: 42 }).label === 'Downloading 42%',
   'a running download shows its percentage as the chip label…');
ok(M.cardAction(base, { state: 'verifying' }).busy === true,
   '…and the sha-verification pass is still busy (not "done" until the hash matches)');
ok(M.cardAction(base, { state: 'error' }).label === 'Retry',
   'a failed download offers a retry rather than going dead');

console.log('\n2b. one verdict object drives the chip AND the hover');
for (const [name, v] of [
  ['state (on disk)', M.stateVerdict(WAN, null)],
  ['state (get)', M.stateVerdict(notOnDisk(SDXL), null)],
  ['licence', M.licenseVerdict(SDXL)],
  ['health', M.healthVerdict(WAN, 'video')],
  ['measured', M.measuredVerdict(SDXL, 'image')],
  ['unmeasured', M.measuredVerdict(SDXL, 'video')],
  ['disk', M.diskVerdict(STATE())],
  ['engine up', M.engineVerdict(STATE())],
  ['engine off', M.engineVerdict(STATE({ comfy: { up: false, port: 8188, error: 'refused' } }))],
  ['model', M.modelVerdict(WAN, 'video', null)],
  ['no model', M.modelVerdict(null, 'image', null)],
]) {
  ok(!!v && typeof v.chip === 'string' && v.chip.length > 0, `${name}: has a chip label`);
  // ≤7 words is the chip line and ≥8 is the prose line, so the two budgets cannot
  // overlap: nothing can be both "a legal chip" and "an illegal sentence".
  ok(!!v && words(v.chip) <= 7, `${name}: the chip is chip-length ("${v && v.chip}")`);
  ok(!!(v && (v.line || v.math || v.hedge)), `${name}: carries its sentence in the hover`);
  ok(M.tipHtml(v).length > 0 && M.tipPlain(v).length > 0, `${name}: the hover renders`);
}
ok(M.healthVerdict(SDXL, 'image') === null,
   'a model with NO measured defect gets no health chip — a warning that fires on '
   + 'everything says nothing');
ok(/colour shift/.test(M.modelVerdict(WAN, 'video', null).chip),
   'THE WAN DEFECT IS ECHOED ON THE COMPOSER MODEL CHIP when that model+mode is selected');
ok(M.modelVerdict(WAN, 'video', null).line === M.healthVerdict(WAN, 'video').line,
   '…off the SAME verdict text as the sheet row’s own chip (they cannot contradict)');
ok(!/colour shift/.test(M.modelVerdict(SDXL, 'image', null).chip),
   '…and a healthy model’s chip says "ready", not a warning');
ok(M.licenseVerdict(SDXL).link === SDXL.license_url,
   'the licence chip carries the licence-text LINK in its hover, and nowhere else');
ok(/t-link/.test(M.tipHtml(M.licenseVerdict(SDXL))) &&
   /<a /.test(M.tipHtml(M.licenseVerdict(SDXL))),
   '…as a real anchor inside the tooltip');
ok(!/pointer-events:\s*none/.test(css.split('#tip {')[1].split('}')[0]),
   'the tooltip is NOT unconditionally click-through — a licence link that cannot be '
   + 'clicked would be "demoted into invisibility"');
ok(/#tip\.inert \{ pointer-events:none/.test(css.replace(/\s+/g, ' ')),
   '…it only goes click-through when it carries no link');
ok(/first run = measurement/.test(M.measuredVerdict(SDXL, 'video').chip),
   'a never-measured model+mode says so instead of inventing a time');
ok(/last 38s · peak 13\.27 GB/.test(M.measuredVerdict(SDXL, 'image').chip),
   'a measured one states the measured numbers');
ok(/Free now: /.test(M.diskVerdict(STATE()).line),
   'the disk hover uses Debi’s STATUS+DELTA grammar');
ok(/−9\.83 GB on this download/.test(M.diskVerdict(STATE({
     downloads: [{ id: 'c1', pick: 'wan', state: 'downloading', pct: 12 }],
     curation: Object.assign({}, BASE.curation, { picks: [notOnDisk(WAN), SDXL] }) })).line),
   '…including the DELTA half while a download is spending the space');

// ── 3. THE AT-REST BUDGET AND THE SENTENCE RULE ──────────────────────────────
console.log('\n3. the at-rest budget and the sentence rule (v1: 106 text elements, 27 sentences)');
function proseAudit(label, res, budget) {
  const nodes = audit(res.env);
  const prose = nodes.filter(n => words(n.text) >= 8);
  const outside = prose.filter(n => !/\bsay\b/.test(n.cls));
  const says = nodes.filter(n => /\bsay\b/.test(n.cls));
  ok(outside.length === 0,
     `${label}: every sentence lives in .say (${outside.length} stray${outside.length
       ? ': ' + outside.map(n => `[${n.cls}] ${n.text.slice(0, 52)}`).join(' | ') : ''})`);
  ok(says.length <= budget,
     `${label}: at most ${budget} .say element(s) standing (found ${says.length}${
       says.length ? ': ' + says.map(n => n.text.slice(0, 44)).join(' | ') : ''})`);
  const chips = nodes.filter(n => /\bchip\b/.test(n.cls));
  const longChips = chips.filter(n => words(n.text) > 7);
  ok(longChips.length === 0,
     `${label}: every chip is ≤7 words (${longChips.map(n => n.text).join(' | ') || 'all short'})`);
  return nodes;
}

// (a) THE NORMAL DAY: models on disk, engine up, a result in the gallery, nothing
//     running. This is the screen Debi looks at, and it must carry ZERO sentences.
const dailyNodes = proseAudit('daily use', daily, 0);
ok(dailyNodes.filter(n => words(n.text) >= 8).length === 0,
   'daily use: the page stands NO prose at all — chips and labels only');

// (b) FIRST RUN: nothing on disk. Exactly one sentence — the invitation.
const first = runPage(
  STATE({ curation: Object.assign({}, BASE.curation,
          { picks: [notOnDisk(WAN), notOnDisk(SDXL)] }) }),
  { ok: true, items: [], total_h: '0', output_dir: '/x/output' });
// two sanctioned lines, and they are the invitation: its heading and its one sentence.
proseAudit('first run', first, 2);
ok(/Get the image model · 6\.94 GB/.test(first.markup) &&
   /Get the video model · 9\.83 GB/.test(first.markup),
   'first run: the two curated Get buttons are IN THE STAGE with their sizes on them');
ok(/Turn a sentence into a picture or a clip/.test(first.markup),
   '…under one invitation heading, and nothing else');
ok(!/licence text/i.test(first.markup) && !/sha256/.test(first.markup),
   '…with no licence link and no verification mechanics standing beside them');

// (c) ENGINE DOWN: one short line WITH an action, never a warnbox essay.
const dead = runPage(STATE({ comfy: { up: false, port: 8188, error: 'connection refused' } }), GAL);
proseAudit('engine down', dead, 1);
ok(/Engine is off/.test(dead.markup) && /Components/.test(dead.markup),
   'engine down: the line names the fix (MOT Deck → Components)');
ok(/disabled/.test(dead.markup.split('data-act="go"')[1] || ''),
   '…and Generate is disabled rather than failing on click');

// (d) A JOB RUNNING: the stage is the progress surface, Generate becomes Stop.
const running = runPage(STATE({ jobs: [{ id: 'j9', state: 'running', step: 14, step_max: 30,
  pick_title: 'SDXL base 1.0', mode: 'image', shape: '1024×1024', submitted: 1, ws: false,
  peak_bytes: 12e9 }] }), GAL);
proseAudit('generating', running, 0);
ok(/step 14 of 30/.test(running.markup), 'generating: step progress is a chip');
ok(/\(polling\)/.test(running.markup), '…a dropped websocket says "(polling)" as a chip suffix');
ok(/>Stop</.test(running.markup), '…and Generate becomes Stop');
ok(!/\bETA\b/.test(running.markup), '…and no ETA is invented');

// (e) THE UNHAPPY DISK/FILE STATES still speak, and still only in chips.
const broken = runPage(STATE({
  curation: Object.assign({}, BASE.curation, { picks: [
    Object.assign({}, WAN, { downloaded: false, corrupt: ['wan.safetensors'],
                             need_h: '9.83 GB',
                             registry_drift: 'the template no longer matches our curation' }),
    SDXL] }),
  fence: { custom_nodes: ['LLMVISION', 'ultralytics'] },
}), { ok: true, total_h: '2 MB', output_dir: '/x/output', items: [
  Object.assign({}, GAL.items[0], { state: 'missing' }) ] }, (S) => { S.sheet = true; });
// the missing-output line + the sheet's cap line; every OTHER unhappy state is a chip
proseAudit('corrupt file + fence violation + missing output', broken, 2);

// (f) THE MODELS SHEET, OPEN. One tap; rows, not cards; the cap line is its ONE
//     sanctioned sentence (Debi's ruling).
const sheet = runPage(STATE(), GAL, (S) => { S.sheet = true; });
const sheetNodes = proseAudit('models sheet open', sheet, 1);
ok(/OVER the 14\.00 GB budget/.test(sheet.markup),
   'the cap-overshoot statement survives, as ONE line in the sheet footer');
ok(/class="mrow"/.test(sheet.markup), 'the sheet is ROWS (Studio Models-page grammar), not cards');
ok(!/class="mcard"/.test(sheet.markup), '…and there is no card left to nest anything inside');
ok((sheet.markup.match(/data-act="row-menu"/g) || []).length === 2,
   'every row carries a ⋯ overflow');
ok(!/Open template in ComfyUI/.test(sheet.markup),
   '…and "Open template in ComfyUI" is INSIDE that overflow — invisible at rest');
ok(/Open template in ComfyUI/.test(html),
   '…but it still exists (kept, demoted — Debi’s fork answer 4)');
ok(sheetNodes.filter(n => /\bfn\b/.test(n.cls)).length === 0,
   'no file-path manifest is standing on the sheet — it is behind "Show the file list"');

// (g) THE MANIFEST, ON INTENT.
const manifest = runPage(STATE(), GAL, (S) => { S.sheet = true; S.manifest = 'wan'; });
ok(/diffusion_models\/wan\.safetensors/.test(manifest.markup),
   'the file manifest (directory/filename/size/state) is reachable on intent');
proseAudit('models sheet + manifest', manifest, 1);

// ── 4. all designs ───────────────────────────────────────────────────────────
console.log('\n4. every design this page can render in');
for (const sel of ['html[data-theme="light"]', 'html[data-theme="gold"]',
                   'html[data-theme="cyber"]', 'html[data-design="studio"]',
                   'html[data-design="studio"][data-dvariant="light"]',
                   'html[data-chrome="studio"]']) {
  ok(css.includes(sel), `${sel} has a block`);
}
for (const pack of ['gold', 'cyber']) {
  const blk = css.split(`html[data-theme="${pack}"] {`)[1].split('}')[0];
  const decls = blk.split(';').map(s => s.trim()).filter(Boolean);
  ok(decls.every(d => d.startsWith('--')),
     `the ${pack} pack declares ONLY custom properties (${decls.length} of them)`);
}
// Every look must define the floating grammar's ground, or the sheet/tooltip borrows a
// dark rgba into a light theme — the --on-wash lesson, sixth sighting.
for (const sel of ['html[data-theme="light"]', 'html[data-theme="gold"]',
                   'html[data-theme="cyber"]', 'html[data-design="studio"]',
                   'html[data-design="studio"][data-dvariant="light"]']) {
  const blk = css.split(sel + ' {')[1].split('}')[0];
  ok(/--float-bg:/.test(blk) && /--scrim:/.test(blk),
     `${sel} defines --float-bg and --scrim (the sheet + tooltip ground)`);
}
const cssBody = css.split('* { box-sizing')[1] || '';
const hexes = (cssBody.match(/#[0-9a-fA-F]{3,8}\b/g) || []);
ok(hexes.length === 0, `no hard-coded colour in any layout rule (found ${hexes.join(', ') || 'none'})`);
const rgba = (cssBody.match(/rgba?\(/g) || []);
ok(rgba.length === 0, 'no hard-coded rgba() either');
ok(!/localStorage\.setItem\(\s*['"]harness-(theme|chrome|design)/.test(html),
   'the page NEVER writes the panel\'s three appearance keys');
ok(/getItem\('harness-theme'\)/.test(html) && /getItem\('harness-chrome'\)/.test(html)
   && /getItem\('harness-design'\)/.test(html), '…it only reads all three');
ok(html.indexOf('function skin()') < html.indexOf('<style>'),
   'the skin is applied in the HEAD, before the stylesheet — no dark-then-flip flash');
ok(/addEventListener\('storage', skin\)/.test(html),
   'a flip in the panel reaches this tab live (storage event)');
ok(/:focus-visible/.test(css), 'keyboard focus is visible in every design');
const cssNC = css.replace(/\/\*[\s\S]*?\*\//g, '');
const studioBlk = cssNC.split('html[data-design="studio"] {')[1].split('}')[0];
ok(/--serif:\s*var\(--sans\)/.test(studioBlk),
   'studio goes sans by restating --serif, not by a selector that ties on specificity');
ok(!/data-design="studio"[^{]*\bh1\b/.test(cssNC),
   '…and there is no equal-specificity h1 override left to lose that race');
// THE SAME TIE, ONE AXIS OVER (measured live 2026-08-29, inherited from v1): the studio
// CHROME control font is a real declaration at specificity (0,0,1) and the base
// `button { font: … }` shorthand is too, so the chrome rule only wins if it comes LATER
// in the file. It used to come first, and studio chrome silently rendered 12px type.
ok(cssNC.indexOf('html[data-chrome="studio"]) button') >
   cssNC.indexOf('button {\n    height:var(--ctl-h)'),
   'the studio-chrome control font rule sits AFTER the base button rule it must beat');

// ── 5. the honesty ledger (§5) — every mechanic, its new home ────────────────
console.log('\n5. the honesty ledger — nothing deleted, everything demoted');
const allMarkup = [daily, first, dead, running, broken, sheet, manifest]
  .map(r => r.markup).join('\n');
ok(/sha256/.test(M.tipPlain(M.stateVerdict(notOnDisk(WAN), null))),
   'sha/size verification: on the state chip’s hover');
ok(/never block a download/.test(M.tipPlain(M.diskVerdict(STATE()))),
   'disk verdicts advisory-never-blocking: on the disk chip’s hover');
ok(/measured phys_footprint/i.test(M.tipPlain(M.measuredVerdict(SDXL, 'image'))),
   'measured wall time + peak: provenance-worded on the measured chip’s hover');
ok(/we never guess/i.test(M.tipPlain(M.measuredVerdict(SDXL, 'video'))),
   '"first run is the measurement" honesty: kept, as a chip + hover');
ok(/colour shift/.test(sheet.markup), 'the Wan defect: one amber chip on its row…');
ok(!/colour shift/.test(daily.markup),
   '…and NOT standing on the composer when the healthy image model is selected');
ok(/Missing:/.test(html) && /data-act="download"/.test(html),
   'the missing-model refusal names the file and carries its own Get button');
ok(/Everything is kept/.test(allMarkup) || /Everything is kept/.test(html),
   'keep-everything gallery policy: on the total chip’s hover');
ok(/file is gone|size changed|no record/.test(allMarkup),
   'missing / size-changed / orphan gallery states: chips on the item');
ok(/node packs — not ours/.test(allMarkup),
   'stock-node fence: a header chip ONLY when violated…');
ok(!/node packs — not ours/.test(daily.markup),
   '…and completely silent when it is intact (the normal case)');
ok(/credential stealers/.test(html),
   '…with the supply-chain sentence kept, in that chip’s hover');
ok(/registry drift/.test(broken.markup),
   'registry drift: an amber chip on the affected row');
ok(/Engine is off/.test(dead.markup), 'engine-down graceful absence: a line with an action');
ok(/f\.shared \|\|/.test(html),
   'shared-file dedup awareness: carried into the manifest row’s hover');
ok(/function section\(/.test(html) && /failed to draw/.test(html),
   'per-section render isolation: kept, message shrunk to one line');
ok(/new EventSource\('\/api\/events'\)/.test(html) &&
   /arm\(live \|\| dlLive \? 1000 : 15000\)/.test(html),
   'SSE + the adaptive 1s/15s cadence: unchanged');
// WALKED DEFECT (2026-08-29, inherited from v1): a fired setTimeout leaves a truthy id
// behind, so `if (cadence === ms && timer) return;` short-circuited every re-arm after
// the first tick and the page silently stopped polling — the engine could die under it
// and the header would go on saying "running". The id MUST be nulled when it fires.
ok(/timer = setTimeout\(\(\) => \{ timer = null; load\(\); \}, ms\);/.test(html),
   'the poll timer nulls its own id when it fires, so arm() can re-arm it');
ok(/act:'graph'/.test(html) && /The exact graph that made this/.test(html),
   'the Graph power exit: kept, in the item’s ⋯ overflow (fork answer 3)');
ok(!/>Graph</.test(daily.markup) && !/exact graph/.test(daily.markup),
   '…and invisible at rest');
ok(/ComfyUI tab ↗/.test(sheet.markup),
   'the ComfyUI deep link: one pill, in the sheet, not on the resting page');
const scriptNoComments = bodyScript.replace(/\/\*[\s\S]*?\*\//g, '')
                                   .replace(/^\s*\/\/.*$/gm, '');
ok(/function toast\(/.test(html) && !/[^\w.]alert\s*\(/.test(scriptNoComments),
   'the v1.5.39 toast pattern stays and alert() is still banned (silent no-op in the shell)');
ok(/S\.form\.width = Number\(m\[1\]\)/.test(html) && /S\.form\.seed = null;/.test(html),
   'Pixelmator write-back: a finished run’s values land in the ordinary controls, and '
   + 'the seed still resets to random');
ok(/data-act="reuse-seed"/.test(daily.markup),
   '…with the drawn seed on a click-to-reuse caption chip');
ok(/4n\+1/.test(html), 'the 4n+1 frames rule: a hover on the frames field');
// The word must not reach the user — checked against what the page actually PAINTS
// (every scenario's markup, every tooltip payload, and the static body) rather than
// against the source, where it legitimately appears in comments explaining the ban.
const staticBody = html.split('</style>')[1].split('<script>')[0];
const readable = allMarkup + '\n' + staticBody + '\n' +
  [M.diskVerdict(STATE()), M.engineVerdict(STATE()), M.measuredVerdict(SDXL, 'video'),
   M.measuredVerdict(SDXL, 'image'), M.modelVerdict(WAN, 'video', null)]
    .map(v => M.tipPlain(v)).join('\n');
ok(!/\bETA\b/.test(readable),
   'the word ETA appears nowhere the user can read it — we never invent one');

// The write-back mechanic, executed rather than grepped.
console.log('\n5b. write-back, executed');
const done = runPage(STATE({ jobs: [{ id: 'j9', state: 'done', shape: '832×480 · 17f',
  steps: 20, seed: 42, pick_title: 'Wan 2.1 T2V 1.3B', mode: 'video' }] }), GAL);
ok(done.M.S.form.width === 832 && done.M.S.form.height === 480,
   'the resolved size of the finished run lands in the ordinary More ▸ fields');
ok(done.M.S.form.frames === 17,
   'the SNAPPED frame count (4n+1) lands there too — what you see is what you re-run');
ok(done.M.S.form.steps === 20, 'so do the steps actually used');
ok(done.M.S.form.seed === null,
   'the seed field still resets to random after a run (the deliberate v1 behaviour, kept)');

console.log(`\n${checks - fails}/${checks} checks passed`);
process.exit(fails ? 1 : 0);
