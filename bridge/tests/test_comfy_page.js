/* THE GENERATE PAGE (bridge/panel/comfy.html) — v3, the Patchbay surface.
 *
 * Run: node bridge/tests/test_comfy_page.js
 * Measure another copy:  COMFY_HTML=/path/to/comfy.html node bridge/tests/test_comfy_page.js
 *
 * v3 re-skinned and re-structured the page onto docs/mockups/2026-08-29/generate-j.html
 * (spec v3): settings rail | media stage | results rail, the stage RESIZABLE and
 * SPLITTABLE into 1/2/4 panes, and the REAL-DATA RULE — every chip, number, thumbnail
 * and label comes from the endpoints or is absent. Groups 1–5 below are v2's and are
 * unchanged in intent (the mechanics survived the re-skin item by item); groups 6–8 are
 * the new layout, Debi's stage, and the real-data rule.
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
/* COMFY_HTML lets the same harness measure a DIFFERENT copy of the page, which is how
   the at-rest count below is compared old-vs-new across a redesign rather than quoted
   from a previous report. The gate itself always runs against the shipped file. */
const PAGE = process.env.COMFY_HTML || path.join(ROOT, 'bridge', 'panel', 'comfy.html');
const html = fs.readFileSync(PAGE, 'utf8');
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
      dataset: {}, style: { setProperty() {}, removeProperty() {} },
      childNodes: [], value: '',
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
/* A recording localStorage, so "the view state is persisted" is EXECUTED rather than
   grepped — and so the test can prove the page writes its own key and nothing else. */
function makeStore(seed) {
  const m = Object.assign({}, seed || {});
  return { _m: m, getItem(k) { return k in m ? m[k] : null; },
           setItem(k, v) { m[k] = String(v); }, removeItem(k) { delete m[k]; } };
}
function runPage(state, gallery, mutate, store) {
  const env = makeEnv();
  const fn = new Function(
    'document', 'window', 'localStorage', 'fetch', 'EventSource', 'setTimeout',
    'clearTimeout', 'addEventListener', 'location',
    bodyScript + '\n;return { S, render, gb, secs, cardAction, stateVerdict, ' +
    'licenseVerdict, healthVerdict, measuredVerdict, diskVerdict, engineVerdict, ' +
    'modelVerdict, itemVerdict, tipHtml, tipPlain, refusalHtml, ' +
    /* v3 — Debi's stage + the hue type system, all pure and all executed below */
    'SPLITS, setSplit, clampFrac, paneItem, stageItem, assign, hueFor, aspectOf, ' +
    'pinCurrent, resetUntouched, ' +
    'advDirty, loadView, saveView, AT_REST_BUDGET };');
  const M = fn(
    env.document, env.window, store || makeStore(),
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
/* THE MEASUREMENT ITSELF, PRINTED. v1 stood 106 text elements / 27 sentences; v2's
   chip-first surface cut that; v3 re-structures onto the Patchbay layout, which adds
   the rail's field labels (one or two words each) and removes the composer's. The
   number is printed rather than asserted at a magic value — the ASSERTION that matters
   is the sentence rule above; this line is how a redesign reports what it did to the
   standing text. Compare with:  COMFY_HTML=<other copy> node bridge/tests/test_comfy_page.js */
console.log('  ——   at rest (daily use): ' + dailyNodes.length + ' standing text elements, '
  + dailyNodes.filter(n => words(n.text) >= 8).length + ' sentences  [' + PAGE + ']');

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
// ⚠️ AND THE ASSERTION ITSELF MUST NOT GO VACUOUS: it used to look for a base rule
// spelled `button { height:var(--ctl-h)`, which v3's Patchbay control block renamed —
// indexOf returned -1 and "later than -1" passed while proving nothing. Both indexes
// are now required to exist, and the chrome block is checked against the LATEST of the
// base rules it has to beat (`.fbox textarea` and `button.primary` are 0,1,1 — a tie
// with a `:where()` rule, decided by order).
const iChrome = cssNC.indexOf(':where(html[data-chrome="studio"]) button');
const iBase = Math.max(cssNC.indexOf('button {'), cssNC.indexOf('.fbox textarea {'),
                       cssNC.indexOf('button.primary {'));
ok(iChrome > 0 && iBase > 0 && iChrome > iBase,
   'the studio-chrome control font rules sit AFTER every base control rule they must '
   + 'beat (both anchors found: ' + (iChrome > 0) + '/' + (iBase > 0) + ')');

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

// ADVERSARIAL FINDING (2026-08-29), now a gate: a run that DIED must not vanish. The
// progress chips come off the LIVE job, so an errored job simply stopped being drawn —
// the bar emptied, the button said Generate again, and the previous picture stayed on
// the stage as if nothing had been asked for.
const failed = runPage(STATE({ jobs: [{ id: 'j7', state: 'error', pick_title: 'SDXL base 1.0',
  shape: '1024×1024', error: 'ComfyUI: OutOfMemoryError on node 3', submitted: 1 }] }), GAL);
ok(/last run failed/.test(failed.markup), 'a failed run says so, until the next one');
proseAudit('a failed run', failed, 0);
const stopped = runPage(STATE({ jobs: [{ id: 'j8', state: 'cancelled',
  pick_title: 'SDXL base 1.0', submitted: 1 }] }), GAL);
ok(/last run stopped/.test(stopped.markup), 'a stopped run says so too, and stays quiet about why');
const deadAndFailed = runPage(STATE({ comfy: { up: false, port: 8188, error: 'refused' },
  jobs: [{ id: 'j7', state: 'error', error: 'x', submitted: 1 }] }), GAL);
ok(/Engine is off/.test(deadAndFailed.markup) && !/last run failed/.test(deadAndFailed.markup),
   '…and when the engine is DOWN the actionable line wins over the post-mortem');

// ── 6. THE PATCHBAY LAYOUT (spec v3) ────────────────────────────────────────
// docs/mockups/2026-08-29/generate-j.html is the binding design source. What is
// pinned here is the STRUCTURE and the DENSITY UNIT — the two things the "defaults
// look so wide" verdict was about — not the prettiness, which no test can hold.
console.log('\n6. the Patchbay layout: three columns, 208/184 rails, 18px rows');
const staticHtml = html.split('</style>')[1].split('<script>')[0];
for (const id of ['id="rail"', 'id="centre"', 'id="results"', 'id="stage"',
                  'id="grip"', 'id="thumbs"', 'id="railbody"', 'id="keyrow"',
                  'id="splitseg"', 'id="verb"']) {
  ok(staticHtml.includes(id), `the frame carries ${id}`);
}
ok(/#frame \{[^}]*grid-template-columns:var\(--railw\) minmax\(0,1fr\) var\(--resw\)/
     .test(css.replace(/\s+/g, ' ')),
   'the frame is settings rail | centre | results rail, by token');
const rootBlk = css.split(':root {')[1].split('}')[0];
ok(/--railw:208px/.test(rootBlk) && /--resw:184px/.test(rootBlk),
   'the rails are 208 / 184 px (generate-j’s measured density, not a round guess)');
ok(/--row:18px/.test(rootBlk) && /--ink:10\.5px/.test(rootBlk),
   '…on an 18px row unit at 10.5px ink');
ok(/--gut:8px/.test(rootBlk), '…with 8px gutters');
ok(/\.srow \{[^}]*grid-template-columns:\.4fr \.6fr/.test(css.replace(/\s+/g, ' ')),
   'every settings row is split at Blender’s UI_ITEM_PROP_SEP_DIVIDE 0.4 — one constant');
ok(/#rail\.basic \.adv \{ display:none/.test(css.replace(/\s+/g, ' ')),
   'the Basic/Advanced gate is a CSS gate over the same rows, not a second markup path');
ok(/border-bottom:1px solid var\(--fam/.test(css),
   'a panel’s label bar is UNDERLINED in its family hue (not the banned side stripe)');
ok(/max-height:calc\(2 \* var\(--thumb/.test(css.replace(/\s+/g, ' ')),
   'the results rail shows two rows plus a measured peek of the third');
ok(/aspect-ratio:3\/2/.test(css),
   'thumbnails are 3:2 — a square in a wide column is the round-1 defect');
// Emil Kowalski's motion rules, taken exactly rather than approximated.
ok(/--eo:cubic-bezier\(0\.23, 1, 0\.32, 1\)/.test(css),
   'the ease-out token is Emil’s exact curve, not the familiar 0.4,0,0.2,1');
ok(/transform:scale\(\.97\)/.test(css.replace(/\s+/g, '')) ||
   /scale\(\.97\)/.test(css), 'press feedback is scale(.97)…');
ok(/button:active/.test(css), '…on :active (pointer-down), not on release');
ok(/S\.full \? 300 : 240/.test(html),
   'the fullscreen FLIP is 300ms in / 240ms out — a collapse is shorter than its expansion');
ok(/transition:opacity 620ms/.test(css),
   'the fullscreen ground is on Carbon slow-02 (620ms), so it recedes rather than competes');
ok(/prefers-reduced-motion/.test(css) && /prefers-reduced-motion/.test(html.split('<script>').pop()),
   'the vestibular path exists in BOTH the stylesheet and the FLIP itself');
ok(/max-width:900px/.test(css), 'the rails stack on a narrow window');
// ALL DESIGNS, v3 tokens: the Patchbay chrome and the hue wheel are token families, so
// a light look gets black hairlines and a low-lightness wheel instead of invisible ones.
for (const sel of [':root', 'html[data-theme="light"]', 'html[data-theme="gold"]',
                   'html[data-theme="cyber"]', 'html[data-design="studio"]',
                   'html[data-design="studio"][data-dvariant="light"]']) {
  // comments first: the studio block explains a specificity tie with a `{ … }` inside
  // a comment, and splitting on raw text would end the block at that brace.
  const blk = css.replace(/\/\*[\s\S]*?\*\//g, '').split(sel + ' {')[1].split('}')[0];
  ok(/--zborder:/.test(blk) && /--img-edge:/.test(blk) && /--stage-bg:/.test(blk),
     `${sel} defines the Patchbay chrome (hairline, image edge, stage ground)`);
  const hs = ['--h1', '--h2', '--h3', '--h4', '--h5', '--h6', '--h7']
    .filter(h => new RegExp(h + ':').test(blk));
  ok(hs.length === 7, `${sel} defines the whole seven-hue wheel (${hs.length}/7)`);
}

// ── 7. DEBI'S STAGE — resizable and splittable, and both are real ───────────
console.log('\n7. the media stage: 1/2/4 panes, resizable, persisted');
const G4 = { ok: true, total_h: '5 MB', output_dir: '/x/output', items: [
  Object.assign({}, GAL.items[0], { filename: 'a.png' }),
  Object.assign({}, GAL.items[0], { filename: 'b.png', seed: 2, pick: 'wan',
                                    pick_title: 'Wan 2.1 T2V 1.3B' }),
  Object.assign({}, GAL.items[0], { filename: 'c.png', seed: 3 }),
  Object.assign({}, GAL.items[0], { filename: 'd.png', seed: 4 }),
] };
const one = runPage(STATE(), G4);
ok((one.markup.match(/class="pane"/g) || []).length === 1,
   'the default stage is ONE pane');
ok(/id="panes" class="s1"/.test(one.markup), '…and says so in the layout class');
const two = runPage(STATE(), G4, (S) => { S.split = 2; });
ok((two.markup.match(/class="pane"/g) || []).length === 2, 'split 2 draws two panes');
const four = runPage(STATE(), G4, (S) => {
  S.split = 4; S.panes = ['a.png', 'b.png', 'c.png', 'd.png']; });
ok((four.markup.match(/class="pane"/g) || []).length === 4, 'split 4 draws four panes');
for (const fn of ['a.png', 'b.png', 'c.png', 'd.png']) {
  ok(new RegExp('data-fn="' + fn + '"').test(four.markup),
     `…each holding its OWN result (${fn}) — side-by-side comparison, not four copies`);
}
ok((four.markup.match(/aria-current="true"/g) || []).length >= 1 &&
   /data-i="0" aria-current="true"/.test(four.markup),
   'exactly one pane is current, and the current one is marked for the keyboard too');
ok(four.M.SPLITS.join(',') === '1,2,4', 'the only legal splits are 1, 2 and 4');
// splitting fills the new panes from the gallery: four empty boxes would make the
// user click four times to find out what the feature is for.
const grown = runPage(STATE(), G4);
grown.M.setSplit(4);
const grownFns = grown.M.S.panes.slice(0, 4);
ok(new Set(grownFns).size === 4 && grownFns.every(Boolean),
   'splitting fills every new pane with a DIFFERENT real result from the gallery');
const thin = runPage(STATE(), { ok: true, total_h: '2 MB', output_dir: '/x',
  items: [G4.items[0]] });
thin.M.setSplit(4);
ok(thin.M.S.panes[1] === null && thin.M.S.panes[2] === null,
   '…and leaves panes empty when the gallery genuinely has nothing more to show');
// collapsing keeps the picture you were actually looking at
const collapse = runPage(STATE(), G4, (S) => {
  S.split = 4; S.panes = ['a.png', 'b.png', 'c.png', 'd.png']; S.pane = 2; S.sel = 'c.png'; });
collapse.M.setSplit(1);
ok(collapse.M.S.pane === 0 && collapse.M.S.panes[0] === 'c.png',
   'collapsing to one pane keeps the result that WAS current, not whatever pane 0 held');
ok(collapse.M.S.panes[2] === 'a.png',
   '…and the displaced one is swapped rather than dropped, so re-splitting restores it');
const badSplit = runPage(STATE(), G4);
badSplit.M.setSplit(3);
ok(badSplit.M.S.split === 1, 'an illegal split is refused rather than half-applied');
// A pane holding a file that has since left the gallery must go EMPTY, not keep a
// picture of a file that is no longer on disk (the LIES class, at pane rank).
const stale = runPage(STATE(), G4, (S) => {
  S.split = 2; S.panes = ['a.png', 'deleted-outside.png']; });
ok(stale.M.paneItem(1) === null,
   'a pane pointing at a file that is gone from the gallery resolves to nothing…');
ok(/empty pane/.test(stale.markup), '…and paints as an empty pane');
ok(!/deleted-outside\.png/.test(stale.markup), '…with no trace of the vanished file');
// promote: clicking a pane that is not current makes it the subject of every fact
const promoted = runPage(STATE(), G4, (S) => {
  S.split = 4; S.panes = ['a.png', 'b.png', 'c.png', 'd.png']; S.pane = 1;
  S.sel = 'b.png'; });
ok(/data-i="1" aria-current="true"/.test(promoted.markup),
   'promoting a pane moves the current mark to it');
ok(promoted.M.stageItem().filename === 'b.png',
   '…and the caption chips and the result facts follow the promoted pane');
ok(/Wan 2\.1 T2V 1\.3B/.test(promoted.markup),
   '…so the rail’s facts describe THAT result, not the first one');
// resize
const rz = runPage(STATE(), GAL);
ok(rz.M.clampFrac(0.5) === 0.5, 'the stage fraction passes a legal value through');
ok(rz.M.clampFrac(9) === 0.82 && rz.M.clampFrac(-4) === 0.22,
   '…clamps to 22–82% so neither region can be dragged out of existence');
ok(rz.M.clampFrac('nonsense') === 0.58,
   '…and a corrupt persisted value falls back to the default rather than to NaN');
ok(/height:calc\(var\(--stagef/.test(css),
   'the stage height IS that fraction — the layout genuinely reflows, nothing overlays');
ok(/cursor:row-resize/.test(css) && /aria-orientation="horizontal"/.test(html),
   'the handle is a real separator control (mouse and keyboard)');
ok(/ArrowUp/.test(html) && /ArrowDown/.test(html),
   '…and ↑↓ nudge it, so the feature is not mouse-only');
// persistence, executed
const store = makeStore();
const persisted = runPage(STATE(), G4, (S) => { S.split = 4; S.stagef = 0.34; }, store);
persisted.M.saveView();
ok(!!store._m['harness-comfy-view'], 'the view state persists under its OWN key');
ok(JSON.parse(store._m['harness-comfy-view']).split === 4 &&
   JSON.parse(store._m['harness-comfy-view']).stagef === 0.34,
   '…carrying the split and the stage fraction');
ok(!('harness-theme' in store._m) && !('harness-chrome' in store._m) &&
   !('harness-design' in store._m),
   '…and the page still writes NONE of the panel’s three appearance keys');
const restored = runPage(STATE(), G4, null,
  makeStore({ 'harness-comfy-view': '{"split":2,"stagef":0.7,"panes":["c.png"]}' }));
ok(restored.M.S.split === 2 && restored.M.S.stagef === 0.7,
   'a reload restores the stage you left');
const junk = runPage(STATE(), G4, null,
  makeStore({ 'harness-comfy-view': 'not json at all' }));
ok(junk.M.S.split === 1 && junk.M.S.stagef === 0.58,
   '…and a corrupt stored value is ignored silently rather than throwing on boot');
ok(rz.M.aspectOf({ shape: '832×480' }).toFixed(3) === (832 / 480).toFixed(3),
   'fullscreen fits the result’s REAL aspect ratio, read off the run record');
ok(rz.M.aspectOf({}) === 1.5,
   '…and falls back to 3:2 only when the record does not say');
/* WALKED PAIR (2026-08-29), and the two halves pull against each other, so both are
   pinned: an UNASSIGNED pane must follow the newest result (otherwise a finished run
   leaves the old picture on the stage while the counts move — a lie at stage rank),
   and a pane you LEAVE must keep what it was showing (otherwise promoting a neighbour
   blanks the picture you were looking at). */
const fresh = runPage(STATE(), G4);
ok(fresh.M.S.panes[0] === null,
   'a pane nobody has assigned stays unassigned — it is a follower, not a pin');
ok(fresh.M.stageItem().filename === 'a.png',
   '…and it shows the newest result in the gallery, so a finished run lands on it');
fresh.M.pinCurrent();
ok(fresh.M.S.panes[0] === 'a.png',
   'leaving a pane (promote, or a split) pins what it was showing…');
fresh.M.S.gallery = { ok: true, total_h: '6 MB', output_dir: '/x',
  items: [Object.assign({}, GAL.items[0], { filename: 'newer.png' })].concat(G4.items) };
ok(fresh.M.stageItem().filename === 'a.png',
   '…and a pinned pane then holds its own result while newer ones arrive');
ok(/S\.panes\[S\.pane\] = null;/.test(html),
   'submitting a run RELEASES the current pane, so the result lands where you are looking');

// ── 8. THE REAL-DATA RULE (Debi, at GO) ─────────────────────────────────────
// The mockup carried invented depiction data. Nothing here may. Every chip, number,
// thumbnail and label is read from the payload, or it is ABSENT — never a zero, a
// placeholder or a plausible default.
console.log('\n8. the real-data rule: live values or nothing');
// checked against what the page PAINTS (every scenario's markup plus the static body),
// not against the source, where the mockup's values legitimately appear in the comment
// that bans them.
const painted = allMarkup + '\n' + staticHtml;
ok(!/2\.1 s|Flux Schnell|SDXL Turbo|418223|18\.4 MB/.test(painted),
   'not one of the mockup’s invented values survives anywhere the user can read');
ok(!/Concurrency/.test(painted),
   'the mockup’s "Concurrency: 1 at a time" is gone — no endpoint reports it');
// the hue legend is COUNTED off the gallery
ok(/>2</.test(runPage(STATE(), { ok: true, total_h: '4 MB', output_dir: '/x',
     items: [Object.assign({}, GAL.items[0], { filename: 'p.png' }),
             Object.assign({}, GAL.items[0], { filename: 'q.png' })] }).markup),
   'the "models here" legend counts the REAL gallery, so it can never over-report');
// a record missing a field renders NO row rather than a dash
const sparse = runPage(STATE(), { ok: true, total_h: '2 MB', output_dir: '/x/output',
  items: [{ filename: 'z.png', subfolder: 'harness', kind: 'image', state: 'ok',
            pick: 'sdxl', pick_title: 'SDXL base 1.0', mode: 'image',
            prompt: 'x', shape: '1024×1024' }] });
// the FACT rows (the results rail's key/value list), not the settings rail's fields:
// a seed you can type is a control, a seed you are told is a claim.
ok(!/<span>Seed<\/span>/.test(sparse.markup) && !/<span>Time<\/span>/.test(sparse.markup) &&
   !/<span>Peak<\/span>/.test(sparse.markup),
   'a result with no seed / time / peak shows no seed, time or peak FACT row');
ok(/<span>Size<\/span>/.test(sparse.markup),
   '…and the rows it can fill are still there (nothing collapses to an empty rail)');
ok(!/—/.test(sparse.markup.replace(/<option[^>]*>[^<]*<\/option>/g, '')),
   '…and invents no em-dash placeholder to fill the shape');
ok(!/data-act="reuse-seed"/.test(sparse.markup),
   '…and offers no "reuse this seed" for a seed we do not have');
ok(/1024×1024/.test(sparse.markup),
   '…while the fields it DOES have are surfaced verbatim');
// A MODE OR MODEL SWITCH RE-READS THAT TEMPLATE'S OWN DEFAULTS — unless you typed.
// Walked 2026-08-29: after an SDXL run wrote 1024×1024 back, switching to Clip kept
// 1024×1024 on a model whose stock video shape is 832×480 — the page was offering a
// far heavier job than the template it claims to run.
const sw = runPage(STATE(), GAL);
sw.M.S.form = { mode:'image', width:1024, height:1024, steps:25, frames:33, fps:16 };
sw.M.S.typed = { width:true };
sw.M.resetUntouched();
ok(sw.M.S.form.width === 1024, 'a number the USER typed survives a mode switch…');
ok(sw.M.S.form.height === null && sw.M.S.form.steps === null &&
   sw.M.S.form.frames === null && sw.M.S.form.fps === null,
   '…and every number the PAGE wrote goes back to the new template’s own default');
const vid = runPage(STATE(), GAL, (S) => { S.form = { mode:'video', pick:'wan' }; });
ok(/id="f-frames"/.test(vid.markup) && /id="f-fps"/.test(vid.markup),
   'clip mode shows the frame and fps controls the video template actually takes');
ok(/value="832"/.test(vid.markup) && /value="480"/.test(vid.markup) &&
   /value="33"/.test(vid.markup),
   '…prefilled from THAT template’s defaults, read off the payload');
ok(!/last /.test(runPage(STATE({ curation: Object.assign({}, BASE.curation,
     { picks: [Object.assign({}, SDXL, { measured: {} })] }) }), GAL).markup),
   'a model that has never run here quotes no "last …" time in the rail');

console.log(`\n${checks - fails}/${checks} checks passed`);
process.exit(fails ? 1 : 0);
