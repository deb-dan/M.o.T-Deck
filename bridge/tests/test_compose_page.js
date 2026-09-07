/* COMPOSE (bridge/panel/compose.html) — the alternative music surface.
 *
 * Run: node bridge/tests/test_compose_page.js
 *
 * WHAT THIS GUARDS, group by group:
 *
 *  1. NOTHING EXTERNAL. The office.html lesson as a gate: a render-blocking <link> or a
 *     <script src> that never resolves paints a blank rectangle and no further script in
 *     the document runs. This page must be self-contained.
 *
 *  2. THE PURE FUNCTIONS AND THE VERDICT OBJECTS, EXECUTED — extracted from the SHIPPED
 *     source, not retyped. Every verdict object must feed its chip AND its tooltip off
 *     ONE object (the v1.5.34 ruling: a chip that can disagree with its own hover is the
 *     lie this structure prevents by construction).
 *
 *  3. THE AT-REST BUDGET AND THE SENTENCE RULE — the reason this surface exists. The
 *     whole page script is executed against a stub DOM, every state is rendered, and the
 *     emitted markup is parsed into (text node → nearest enclosing class) pairs. A
 *     sentence (≥8 words) may appear ONLY inside `.say` (our prose) or `.utext` (the
 *     USER's own words, echoed back in the track sheet), `.say` may appear only as often
 *     as the rule allows, and chips must stay chip-length. Element-class-based: it does
 *     not care what a sentence says, only where sentences are allowed to live.
 *     The audit measured the CURRENT Music view at ~55 standing elements / ~14 standing
 *     sentences (docs/research/2026-08-29-surface-audit.md §3.1).
 *
 *  4. ALL DESIGNS (Debi's standing rule). Editorial + the three packs + studio
 *     light/dark + studio chrome, verified structurally: every pack is a token-only
 *     block, and no layout rule hard-codes a colour.
 *
 *  5. THE CONSERVATION LAW. Every honest mechanic the Music view carries must still be
 *     REACHABLE here — demoted to a chip, a hover, a sheet row or the track sheet, never
 *     deleted. Each row of the conservation table is one assertion.
 *
 *  6. THE LIES THIS PAGE COULD TELL, pinned shut: a stage that names one file and plays
 *     another, a rename that makes the list and the disk disagree, a chip that
 *     contradicts its hover, an invented ETA, a player restarted by the poll.
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'compose.html'), 'utf8');
const py = fs.readFileSync(path.join(ROOT, 'bridge', 'routers', 'music.py'), 'utf8');
const musicPy = fs.readFileSync(path.join(ROOT, 'bridge', 'music.py'), 'utf8');
const indexHtml = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok   ' : '  FAIL ') + msg); if (!cond) fails++; }

// ── 1. nothing external ──────────────────────────────────────────────────────
console.log('\n1. the document is self-contained');
ok(!/<link\b/i.test(html), 'no <link> at all (no stylesheet can hang the parse)');
ok(!/<script[^>]+\bsrc=/i.test(html), 'no <script src=> — every script is inline');
ok(!/https?:\/\/(?!127\.0\.0\.1)/.test(css), 'the CSS fetches nothing');
ok(!/@import/.test(css), 'no @import in the stylesheet');
ok(!/<img[^>]+src=["']http/i.test(html), 'no remote images');

// ── the backend contract this page rests on ──────────────────────────────────
console.log('\n1b. it is served by the EXISTING music router, and the Music view is untouched');
ok(/@app\.get\("\/compose"\)/.test(py) && /compose\.html/.test(py),
   '/compose is served from bridge/routers/music.py — no new router file');
ok(/@app\.post\("\/api\/music\/title"\)/.test(py),
   'the ONE route this slice added is the title write-back');
ok(/def set_track_title/.test(musicPy) && /library_target\(root, name\)/.test(
     musicPy.split('def set_track_title')[1].split('def library_entries')[0]),
   '…and it goes through library_target — the same containment /file and /delete use');
ok(!/os\.rename|shutil\.move/.test(musicPy.split('def set_track_title')[1].split('def library_entries')[0]),
   'LIE GUARD: naming a track NEVER renames the file, so the list and the folder cannot '
   + 'disagree');
for (const route of ['/api/music/status', '/api/music/library', '/api/music/generate',
                     '/api/music/cancel', '/api/music/install', '/api/music/convert',
                     '/api/music/delete', '/api/music/templates', '/api/music/settings',
                     '/api/music/file/']) {
  ok(html.includes(route), 'the page drives the EXISTING route ' + route);
}
// THE SECOND ROUTE, added by the v2 visual rebuild because the gap is real: nothing in
// this lane knows a song's structure, so the waveform's colour had to be MEASURED.
ok(/@app\.get\("\/api\/music\/analysis\/\{name\}"\)/.test(py),
   'the analysis route exists in the SAME router (no second music backend)');
ok(/library_target/.test(musicPy.split('def track_analysis')[1].split('\n\n\n')[0]),
   '…and it is contained by library_target, exactly like /file and /delete');
{
  const fn = musicPy.split('def track_analysis')[1].split('\n\n\n')[0];
  ok(/"sections" if secs else "ramp"/.test(fn),
     'LIE GUARD: the mode is a FUNCTION of whether the audio segmented — there is no '
     + 'branch in which sections are invented');
  ok(/"derived": True/.test(fn) && /ANALYSIS_METHOD/.test(fn),
     '…and every payload carries its own provenance (derived + the method)');
  const seg = musicPy.split('def segment(')[1].split('\ndef ')[0];
  ok(/return \[\]/.test(seg) && /len\(set\(lv\)\) < 2/.test(seg),
     '…and the segmenter RETURNS NOTHING rather than splitting audio that has no runs');
  ok(!/verse|chorus|bridge|intro|outro/i.test(seg + fn),
     'NO MUSICAL ROLE IS EVER NAMED: the labels are the measured ones (quiet/steady/loud), '
     + 'because a verse is a claim we cannot make');
  ok(/ANALYSIS_LEVEL_NAMES = \("quiet", "steady", "loud"\)/.test(musicPy),
     '…and those are the only three labels the lane can produce');
  ok(/fingerprint/.test(fn) && /st\.st_size/.test(musicPy.split('def analysis_fingerprint')[1]),
     'a cached analysis is keyed on the FILE\u2019s own size+mtime, so a replaced file is '
     + 're-measured instead of drawn from a picture of a different song');
}
ok(html.includes('/api/music/analysis/'), 'the page drives that route');
// ⚠️ REWRITTEN AT THE CONSOLIDATION SLICE (Debi 2026-08-29). The Compose slice's rule
// was "two rows, both stay until Debi picks". She picked: ONE door, both looks. So the
// assertion inverts on the ROW count and HOLDS on what it was really protecting — that
// neither SURFACE is deleted, and the Classic view is still in the panel, untouched.
ok(/id:'compose', label:'Music'/.test(indexHtml)
   && /id:'music',\s+label:'Music Classic'/.test(indexHtml),
   'ONE Music row (the Studio) and Classic named as the second look');
ok(/const NAV_OFFBAR = \['music'\];/.test(indexHtml),
   '…and Classic owns no row on either bar — that is the consolidation');
ok(/#view-music/.test(indexHtml), '…while the Music view itself is still in the panel');
// THE SWITCHER, both directions — the thing that makes one door legal.
ok(/<select id="look"/.test(html) && /value="classic"/.test(html)
   && /<option value="studio" selected>Music Studio<\/option>/.test(html),
   'the Studio page carries the header switcher, defaulting to Studio');
ok(/function musicClassic\(\)/.test(html) && !/cmd:'switchTab'/.test(html)
   && /location\.href = '\/\?solo=music'/.test(html),
   '…which navigates IN PLACE in app and browser alike — the switchTab path is BANNED '
   + '(Debi live feedback 2026-08-29: it parked a second Music tab in a strip window '
   + 'slot; both looks live inside the ONE Music tab)');
ok(/sel\.value = 'studio';/.test(html),
   '…and re-asserts its own value afterwards: in the app this document stays loaded in '
   + 'its tab, so a select left reading "Music Classic" would be a standing lie');
ok(/openMusicStudio\(\)/.test(indexHtml),
   'and the Classic view carries the way back');

// ══ THE HARNESS ══════════════════════════════════════════════════════════════
// The page's whole body script is executed in a stub DOM. Everything it writes with
// innerHTML is recorded, so the at-rest audit below is a MEASUREMENT of what the page
// would paint — not a grep over its source.
function makeEnv() {
  const written = [], created = [];
  const esc = (s) => String(s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function node(id) {
    const n = {
      id, _html: '', _text: '', className: '', hidden: false, title: '',
      dataset: {}, style: {}, childNodes: [], value: '', attrs: {},
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
      setAttribute(k, v) { this.attrs[k] = String(v); },
      hasAttribute(k) { return k in this.attrs; },
      removeAttribute(k) { delete this.attrs[k]; },
      getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
      addEventListener() {}, appendChild(c) { this.childNodes.push(c); }, remove() {},
      querySelectorAll() { return { forEach() {} }; },
      querySelector() { return null; },
      closest() { return null; },
      focus() {},
      getBoundingClientRect() { return { left: 0, top: 0, bottom: 0, right: 0 }; },
    };
    return n;
  }
  const nodes = {};
  const document = {
    getElementById(id) { return (nodes[id] = nodes[id] || node(id)); },
    createElement(t) { const n = node('new:' + t); created.push(n); return n; },
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
  return { written, created, nodes, document, window: win };
}

const bodyScript = html.split('<script>').pop().split('</script>')[0];
function runPage(st, lib, mutate) {
  const env = makeEnv();
  const fn = new Function(
    'document', 'window', 'localStorage', 'fetch', 'setTimeout', 'clearTimeout',
    'addEventListener', 'location',
    bodyScript + '\n;return { S, render, bytes, clock, mmss, ago, titleOf, enginesVerdict, ' +
    'engineStateVerdict, licenseVerdict, ramVerdict, speedVerdict, measuredVerdict, ' +
    'engineChipVerdict, lengthVerdict, seedVerdict, totalVerdict, jobVerdict, ' +
    'trackChips, tipHtml, tipPlain, advisoryHtml, heroTrack, fileSrc, writeBack, ' +
    'waveVerdict, promptHead, LEVEL_TOKEN, LAYOUT_KEY, CONTAINERS, readLayout, ' +
    'saveLayout, applyLayout, heroDuration };');
  const M = fn(
    env.document, env.window, { getItem() { return null; }, setItem() {} },
    () => new Promise(() => {}),                       // load() never resolves: inert
    () => 0, () => {}, () => {}, env.window.location);
  M.S.st = st;
  M.S.lib = lib;
  if (mutate) mutate(M.S);
  env.written.length = 0;
  M.render();
  return { M, env, markup: env.written.map(w => w.html).join('\n') };
}

/* A tiny text extractor: walk the emitted markup, track the class of the innermost open
   element, and emit {cls, text} for every non-empty text node. Attribute values (where
   the tooltip payloads and titles live) are skipped by construction — a tooltip is not
   standing prose. */
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

// ── the fixtures (shaped exactly like /api/music/status + /api/music/library) ──
const MINIMAX = {
  engine: 'minimax', label: 'MiniMax-Music3 · MLX',
  note: '~2 min per minute of song · highest quality', installed: true, reason: '',
  size_gb: 11.1, size_estimated: false, ram_gb: 14, default_steps: 30, max_steps: 30,
  installing: false, install_error: '',
  license: { license: 'minimax-community (weights)', badge: 'unknown',
             reason: 'weights under the MiniMax-Music3 Community License',
             source_url: 'https://huggingface.co/x/LICENSE' },
};
const ACESTEP = {
  engine: 'acestep', label: 'acestep.cpp · GGUF', note: '~25s per song · fast',
  installed: true, reason: '', size_gb: 7.6, size_estimated: false, ram_gb: 9,
  default_steps: 8, max_steps: 20, installing: false, install_error: '',
  license: { license: 'MIT', badge: 'ok', reason: '',
             source_url: 'https://github.com/x/acestep.cpp' },
};
const absent = (e, over) => Object.assign({}, e, { installed: false,
  reason: 'not on disk' }, over || {});
const ST = (over) => Object.assign({
  ok: true, engines: [MINIMAX, ACESTEP], busy: false, job: null,
  dir: '/Users/x/Library/Application Support/MOT Deck/data/music',
  default_dir: '/Users/x/Library/Application Support/MOT Deck/data/music',
  seconds_min: 10, seconds_max: 300, seconds_default: 60, prompt_max: 8000,
  seed_max: 2147483647,
  seed_help: 'Any whole number from 0 to 2147483647. The same seed + the same settings '
           + '+ the same engine = the same song again.',
  formats: { minimax: ['wav'], acestep: ['wav24', 'wav32', 'wav16', 'mp3'] },
  format_default: { minimax: 'wav', acestep: 'wav24' },
  format_label: { wav: 'WAV', wav24: 'WAV 24-bit', mp3: 'MP3' },
  convert_formats: ['mp3', 'm4a'],
  templates: [{ id: 'neo-soul', name: 'Neo-soul / R&B ballad', tag: 'vocal · 72 BPM',
                seconds: 90, prompt: 'Warm modern neo-soul R&B ballad at 72 BPM in D minor, '
                  + 'swung sixteenths, intimate and unhurried and long enough to be prose.',
                lyrics: '', builtin: true }],
}, over || {});
const TRACK = {
  name: 'minimax-20260820-235921.wav', title: '', ext: 'wav', size_bytes: 43216940,
  created: (Date.now() / 1000) - 700000, engine: 'minimax',
  prompt: 'Dark psychedelic trap with a detuned warbling melody, 130 BPM, E minor, '
        + 'heavy 808s and an autotuned top line that carries the hook.',
  lyrics: '[Verse]\nthe city hums', seconds: 243, steps: 30, seed: 1728872057,
  wall: 1591.7, path: '/Users/x/music/minimax-20260820-235921.wav',
};
const TRACK2 = Object.assign({}, TRACK, {
  name: 'acestep-20260829-101500.wav', title: 'Night Bus', engine: 'acestep',
  seconds: 60, steps: 8, seed: 12, wall: 24.5, size_bytes: 10600000,
  created: (Date.now() / 1000) - 300,
  path: '/Users/x/music/acestep-20260829-101500.wav',
});
const LIB = [TRACK2, TRACK];

// ── 2. the pure functions and the verdict objects ────────────────────────────
console.log('\n2. the pure functions and the verdict objects, taken from the shipped source');
const daily = runPage(ST(), LIB);
const M = daily.M;
ok(M.bytes(0) === 'nothing' && M.bytes(null) === '?', 'bytes(0/null) never reads as "0 kB"');
ok(M.bytes(43216940) === '43 MB' && M.bytes(9828025775) === '9.83 GB',
   'bytes() is DECIMAL, the same spelling the bridge uses');
ok(M.clock(45) === '45s' && M.clock(1591.7) === '26m 32s' && M.clock(null) === '—',
   'clock() reads as a human would say it, and null is a dash rather than "0s"');
ok(/days ago/.test(M.ago(TRACK.created)) && M.ago(Date.now() / 1000) === 'just now',
   'ago() is relative and total');

// THE NAME. The audit's central charge against the Music view: a raw filename was the
// row's identity. Here the fallback ladder is title → prompt head → filename.
ok(M.titleOf(TRACK2) === 'Night Bus', 'a titled track is called what the user called it');
ok(M.titleOf(TRACK) === 'Dark psychedelic trap with a detuned…',
   'an untitled track is named by the head of its prompt, not by its timestamp');
ok(M.titleOf({ name: 'x.wav' }) === 'x.wav',
   '…and a track with NO sidecar at all still gets a name it can be found by');
ok(words(M.titleOf(TRACK)) <= 7, 'a derived name stays label-length, never a paragraph');

const ev = M.enginesVerdict();
ok(ev.chip === '2 of 2 engines ready' && ev.up === true, 'the header states what can render');
ok(/one-shot process/.test(M.tipPlain(ev)),
   'the "one-shot subprocess" architecture sentence: demoted from the page SUBTITLE to '
   + 'this chip’s hover');
ok(!/subprocess|port|server/.test(
     textNodes(daily.markup).map(n => n.text).join(' ')),
   '…and the words subprocess/port/server appear nowhere the user can READ them at rest '
   + '(measured over text nodes: the CSS class `transport` is not a word on the page)');

ok(M.engineStateVerdict(MINIMAX).chip === 'On disk ✓',
   'an installed engine says so, in a chip');
ok(M.engineStateVerdict(absent(MINIMAX)).chip === 'Get 11.1 GB',
   'an absent engine offers its SIZE on the action chip');
ok(M.engineStateVerdict(Object.assign({}, absent(MINIMAX), { installing: true })).busy === true,
   'an install in flight is its own state, not a Get that would start a second one');
const failed = M.engineStateVerdict(Object.assign({}, absent(MINIMAX),
  { install_error: 'cmake: command not found' }));
ok(failed.chip === 'Retry install' && /cmake/.test(M.tipPlain(failed)),
   'a failed install offers Retry and carries the bridge’s OWN words in the hover '
   + '(the Music view’s "View log" button, demoted)');
ok(/read from disk/i.test(M.tipPlain(M.engineStateVerdict(MINIMAX))),
   'installed-is-read-from-disk-every-time honesty: kept, on the hover');

ok(/14 GB/.test(M.ramVerdict(MINIMAX).chip) && /planning figure/.test(M.tipPlain(M.ramVerdict(MINIMAX))),
   'the RAM figure is provenance-worded as a PLANNING number, not a measured peak');
ok(/never block|render anyway/i.test(M.tipPlain(M.ramVerdict(MINIMAX))),
   '…and its hover says it is advisory (Debi’s advisory-gates ruling)');
ok(M.licenseVerdict(ACESTEP).cls === 'c-ok' && M.licenseVerdict(MINIMAX).cls === 'c-warn',
   'the licence chip’s colour comes from the badge the bridge computed');
ok(M.licenseVerdict(MINIMAX).link === MINIMAX.license.source_url,
   '…and the licence TEXT link lives in that chip’s hover, nowhere else');
ok(M.speedVerdict(MINIMAX).chip === '~2 min per minute of song' &&
   /highest quality/.test(M.tipPlain(M.speedVerdict(MINIMAX))),
   'the engine trade-off is a chip, with the whole note in the hover — never truncated '
   + 'into a different meaning');

const meas = M.measuredVerdict('minimax', LIB);
ok(/last 26m 32s for 243s/.test(meas.chip) && /Measured on this Mac/i.test(M.tipPlain(meas)),
   'render cost is MEASURED from this machine’s own tracks, provenance-worded');
const unmeas = M.measuredVerdict('acestep', []);
ok(unmeas.unmeasured && /made-up number would be worse/i.test(M.tipPlain(unmeas)),
   '"first run is the measurement" honesty: kept, as a chip + hover');

console.log('\n2b. one verdict object drives the chip AND the hover');
const objs = [M.enginesVerdict(), M.engineStateVerdict(MINIMAX), M.licenseVerdict(MINIMAX),
              M.ramVerdict(MINIMAX), M.speedVerdict(ACESTEP), M.measuredVerdict('minimax', LIB),
              M.engineChipVerdict(MINIMAX), M.lengthVerdict(60), M.seedVerdict(42),
              M.totalVerdict(LIB)].concat(M.trackChips(TRACK));
for (const v of objs) {
  ok(typeof v.chip === 'string' && v.chip.length > 0, 'verdict "' + v.chip + '" has a chip label');
  ok(words(v.chip) <= 6, '…and it is chip-length (' + words(v.chip) + ' words)');
  ok(M.tipHtml(v) === '' || /t-line|t-math|t-hedge/.test(M.tipHtml(v)),
     '…and its tooltip is rendered from the SAME object');
}
ok(M.tipPlain(M.seedVerdict(42)).indexOf('same seed') > -1,
   'the seed-determinism essay (a per-field paragraph in the Music view) is now the '
   + 'seed chip’s hover');

// ── 3. THE AT-REST BUDGET AND THE SENTENCE RULE ──────────────────────────────
console.log('\n3. the at-rest budget and the sentence rule '
            + '(the current Music view: ~55 standing elements, ~14 standing sentences)');
function proseAudit(label, res, budget) {
  const nodes = audit(res.env);
  const prose = nodes.filter(n => words(n.text) >= 8);
  const outside = prose.filter(n => !/\bsay\b/.test(n.cls) && !/\butext\b/.test(n.cls));
  const says = nodes.filter(n => /\bsay\b/.test(n.cls));
  ok(outside.length === 0,
     `${label}: every sentence lives in .say or .utext (${outside.length} stray${outside.length
       ? ': ' + outside.map(n => `[${n.cls}] ${n.text.slice(0, 52)}`).join(' | ') : ''})`);
  ok(says.length <= budget,
     `${label}: at most ${budget} .say element(s) standing (found ${says.length}${
       says.length ? ': ' + says.map(n => n.text.slice(0, 44)).join(' | ') : ''})`);
  const chips = nodes.filter(n => /\bchip\b/.test(n.cls));
  const longChips = chips.filter(n => words(n.text) > 6);
  ok(longChips.length === 0,
     `${label}: every chip is ≤6 words (${longChips.map(n => n.text).join(' | ') || 'all short'})`);
  return nodes;
}

// (a) THE NORMAL DAY: two engines on disk, tracks in the library, nothing running.
//     This is the screen Debi looks at, and it carries ZERO sentences.
const dailyNodes = proseAudit('daily use', daily, 0);
ok(dailyNodes.filter(n => words(n.text) >= 8).length === 0,
   'daily use: the page stands NO prose at all — chips, names and labels only');
ok(!/Application Support|data\/music/.test(daily.markup),
   'daily use: NO absolute output path is standing (the Music view prints it in mono at rest)');
// Attribute VALUES carry the filename (it is the id every action addresses a track by),
// so they are stripped before the test — this asks what the user can READ.
const dailyText = daily.markup.replace(/<[^>]*>/g, ' ');
ok(!/\.wav|\.mp3/.test(dailyText),
   'daily use: no raw filename is standing either — a filename is not an identity');
// The at-rest element count, MEASURED the same way the audit counted the Music view.
const standing = dailyNodes.length;
// THE BUDGET MOVED, DELIBERATELY AND WITH A REASON. v1 was a single column and stood 30
// text elements. Spec v2 is a WORKBENCH — Debi's own structure: a settings pane plus a
// 3-per-row block grid whose whole point is that everything is visible at a glance. So
// the ELEMENT budget is set by measurement of that structure, while the rule that
// actually protects the reader — no sentence outside .say / .utext, and none at all on
// a normal day — is unchanged and asserted above.
ok(standing <= 95, 'daily use: ' + standing + ' standing text elements across the whole '
   + 'workbench (settings pane + 8 blocks + the ledger), and ZERO of them prose');

// (b) FIRST RUN: no engine on disk. Exactly one sentence — the invitation.
const first = runPage(ST({ engines: [absent(MINIMAX), absent(ACESTEP)] }), []);
proseAudit('first run', first, 2);   /* the invitation heading + its one line */
ok(/Get MiniMax-Music3 · MLX · 11\.1 GB/.test(first.markup) &&
   /Get acestep\.cpp · GGUF · 7\.6 GB/.test(first.markup),
   'first run: both Get buttons are IN THE STAGE with their sizes on them');
ok(/Describe a song and hear it here/.test(first.markup),
   '…under one invitation heading, and nothing else');
ok(!/licence|license/i.test(first.markup),
   '…with no licence link standing beside them (it rides on the buttons’ hover)');
ok(first.env.nodes.go && first.env.nodes.go.disabled === true,
   '…and Compose is disabled rather than failing on click');

// (c) INSTALLING, nothing else on disk: the stage says so instead of reading empty.
const inst = runPage(ST({ engines: [Object.assign({}, absent(MINIMAX), { installing: true }),
                                    absent(ACESTEP)] }), []);
proseAudit('installing', inst, 1);
ok(/Installing minimax/.test(inst.markup), 'installing: the stage names what is landing');

// (d) EMPTY LIBRARY, engines ready: one quiet line, not a paragraph.
const empty = runPage(ST(), []);
proseAudit('empty library', empty, 1);
ok(/lands here, and stays/.test(empty.markup), 'empty library: one line in the stage');
ok(!/All tracks/.test(empty.markup), '…and no strip controls for tracks that do not exist');

// (e) RENDERING: the stage is the progress surface, Generate is disabled and Stop appears.
const running = runPage(ST({ busy: true, job: { id: 'j1', engine: 'minimax', state: 'running',
  started: (Date.now() / 1000) - 65, seconds: 60, steps: 30, seed: 7, format: 'wav',
  progress_view: { progress: 0.42, phase: 'rendering', phase_kind: 'render',
                   elapsed_s: 65, remaining_s: 200 } } }), LIB);
proseAudit('rendering', running, 0);
ok(/data-act="stop"/.test(running.markup), 'rendering: Stop is offered');
ok(/Rendering…/.test(running.markup), '…and Generate says what it is doing, disabled');
ok(/left/.test(running.markup), '…and the remaining time is shown when the bridge gives one');
// THE HONEST-ETA RULE: no remaining_s → no invented number.
const noeta = runPage(ST({ busy: true, job: { id: 'j2', engine: 'minimax', state: 'running',
  started: (Date.now() / 1000) - 900, seconds: 300, steps: 30, seed: 7,
  progress_view: { progress: 0.9, phase: '', phase_kind: 'render', remaining_s: null } } }), LIB);
ok(/longer than estimated/.test(noeta.markup) && !/left/.test(noeta.markup),
   'LIE GUARD: with no honest estimate the page says so instead of inventing one');
ok(!/\bETA\b/.test(html.split('</style>').slice(1).join('</style>')),
   'the word ETA appears nowhere the user can read it');

// (f) THE FAILURE / CANCEL / BRIDGE-DOWN states still speak — as sentences that demand
//     a decision, which is exactly what the rule allows.
const failedJob = runPage(ST({ job: { id: 'j3', engine: 'minimax', state: 'failed',
  wall: 12.3, error: 'the engine exited with status 1' } }), LIB);
proseAudit('failed render', failedJob, 1);
ok(/The last render failed/.test(failedJob.markup) && /status 1/.test(failedJob.markup),
   'a failed render says so, in the bridge’s own words');
const cancelled = runPage(ST({ job: { id: 'j4', engine: 'minimax', state: 'cancelled', wall: 9 } }), LIB);
proseAudit('cancelled render', cancelled, 1);
ok(/nothing was saved/.test(cancelled.markup),
   'a cancelled render still says nothing was saved (the Music view’s wording, kept)');
const warned = runPage(ST(), LIB, (S) => {
  S.warn = 'a minimax render wants about 14 GB and 6.0 GB of models are already loaded — '
         + 'that is over the 20 GB model-RAM budget and may push the machine into swap.'; });
proseAudit('RAM advisory', warned, 1);
ok(/Compose anyway/.test(warned.markup) && /data-act="dismiss-warn"/.test(warned.markup),
   'ADVISORY, NOT A WALL: the numbers, a way through, and a way out — never a refusal');

// (g) THE ENGINES SHEET, one tap. Rows, not the essay cards the Music view opens with.
const sheet = runPage(ST(), LIB, (S) => { S.sheet = 'engines'; });
proseAudit('engines sheet', sheet, 0);
ok(/class="erow"/.test(sheet.markup), 'the sheet is ROWS (the Studio Models-page grammar)');
ok((sheet.markup.match(/class="erow"/g) || []).length === 2, 'one row per engine');
ok(/tracks folder/.test(sheet.markup) && /data-act="edit-dir"/.test(sheet.markup),
   'the output folder lives here — Reveal + Change, with the path on a hover');
ok(!/Application Support/.test(sheet.markup.replace(/data-tip="[^"]*"/g, '')),
   '…and the absolute path is in the hover payload, not printed as standing copy');

// (h) THE TRACK SHEET, one tap: real name editing + the run’s own numbers.
const track = runPage(ST(), LIB, (S) => { S.sheet = 'track'; S.detail = TRACK.name; });
proseAudit('track sheet', track, 0);
ok(/id="t-title"/.test(track.markup) && /data-act="save-title"/.test(track.markup),
   'a track can be NAMED (the audit’s charge: a filename is not an identity)');
ok(track.markup.indexOf(TRACK.name) > -1,
   '…while the real filename is shown as provenance, so the disk is never contradicted');
ok(/data-act="convert"/.test(track.markup) && /data-act="reveal"/.test(track.markup) &&
   /data-act="delete"/.test(track.markup) && /data-act="reuse"/.test(track.markup),
   'convert / reveal / delete / re-use all survive, one tap down instead of five co-equal '
   + 'chips per row');
ok(/class="utext"/.test(track.markup),
   'the prompt and the lyric sheet are shown back — the user’s own words, not our copy');
const converted = runPage(ST(), [Object.assign({}, TRACK2, { ext: 'mp3',
  name: 'acestep-20260829-101500.mp3' }), TRACK2, TRACK],
  (S) => { S.sheet = 'track'; S.detail = TRACK2.name; });
ok(!/data-act="convert" data-name="[^"]*" data-fmt="mp3"/.test(converted.markup),
   'a format that already exists beside the track is NOT offered again (a control that '
   + 'cannot work is absent, never greyed out)');

// (h2) A POLL MAY NOT WIPE WHAT SOMEBODY IS TYPING — walked live on the tracks-folder
//      path, and the track-name field is the same shape. The sheet is left alone while
//      the focus is in one of its fields.
{
  const res = runPage(ST(), LIB, (S) => { S.sheet = 'track'; S.detail = TRACK.name; });
  res.env.document.activeElement = { id: 't-title', tagName: 'INPUT', value: 'half typed' };
  res.env.written.length = 0;
  res.M.render();
  const sheetWrites = res.env.written.filter(w => w.id === 'sheet');
  ok(sheetWrites.length === 0,
     'a re-render while a sheet field has focus does NOT redraw the sheet (the half-typed '
     + 'name survives the poll)');
  res.env.document.activeElement = null;
  res.env.written.length = 0;
  res.M.render();
  ok(res.env.written.filter(w => w.id === 'sheet').length > 0,
     '…and the very next poll after the field is left redraws it normally');
}
// …AND A POLL MAY NOT DISARM A TWO-STEP CONFIRMATION. Walked live on the delete path:
// the 20s poll redrew the sheet inside the 3-second "sure?" window and put the plain
// label back under the pointer.
{
  const res = runPage(ST(), LIB, (S) => { S.sheet = 'track'; S.detail = TRACK.name; });
  const armed = { querySelector: (sel) => (sel === '.arm' ? {} : null) };
  res.env.nodes.sheet.querySelector = armed.querySelector;
  res.env.written.length = 0;
  res.M.render();
  ok(res.env.written.filter(w => w.id === 'sheet').length === 0,
     'a re-render while a confirmation is armed does NOT redraw the sheet (the "sure?" '
     + 'state survives the poll)');
}
// The tracks-folder editor is STATE, so a redraw cannot close it under the user.
{
  const res = runPage(ST(), LIB, (S) => { S.sheet = 'engines'; S.dirEdit = true;
                                          S.dirValue = '/Users/x/Music/MOT Deck'; });
  ok(/id="dir-inp"/.test(res.markup) && /\/Users\/x\/Music\/MOT Deck/.test(res.markup),
     'the folder editor and what is typed in it live in state, not in the DOM alone');
  ok(/data-act="cancel-dir"/.test(res.markup), '…and it has a way out as well as a Set');
  ok(/function blurCommitted\(/.test(html) &&
     /blurCommitted\(\);[\s\S]{0,80}S\.dirEdit = false/.test(html),
     '…and committing a field releases the caret, so the guard cannot leave a stale sheet');
}

// (i) PRESETS (the Music view’s templates), one tap.
const presets = runPage(ST(), LIB, (S) => { S.sheet = 'presets'; });
proseAudit('presets sheet', presets, 0);
ok(/Neo-soul/.test(presets.markup) && /data-act="use-preset"/.test(presets.markup),
   'the six starter captions survive, as presets');
ok(/data-act="save-preset"/.test(presets.markup), '…and so does Save as template');
ok(!/Neo-soul/.test(daily.markup), '…and none of them is standing on the composer');

// (j) THE STRIP and the in-place expansion.
const many = runPage(ST(), Array.from({ length: 9 }, (_, i) =>
  Object.assign({}, TRACK2, { name: 'acestep-' + i + '.wav', title: 'Song ' + i })));
ok(/data-act="all"/.test(html), 'the run ledger carries the All-tracks control');
const expanded = runPage(ST(), Array.from({ length: 9 }, (_, i) =>
  Object.assign({}, TRACK2, { name: 'acestep-' + i + '.wav', title: 'Song ' + i })),
  (S) => { S.all = true; });
ok((expanded.env.written.find(w => w.id === 'alltracks') || {}).html.indexOf('Song 8') > -1,
   '…and it expands IN PLACE (Debi’s Generate fork answer, mirrored)');

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
for (const sel of ['html[data-theme="light"]', 'html[data-theme="gold"]',
                   'html[data-theme="cyber"]', 'html[data-design="studio"]',
                   'html[data-design="studio"][data-dvariant="light"]']) {
  const blk = css.split(sel + ' {')[1].split('}')[0];
  ok(/--float-bg:/.test(blk) && /--scrim:/.test(blk),
     `${sel} defines --float-bg and --scrim (the sheet + tooltip ground)`);
}
// THE WHEEL IS A TOKEN SET, AND THE LIGHT LOOKS RE-BAND IT. The research finding is
// that loud is a LIGHTNESS problem: seven hues stay calm inside one band on a ground
// that stays the darkest thing on screen. Two of the six looks are LIGHT, where the
// same band would be invisible rather than calm — so they declare their own.
const WHEEL = ['--h1', '--h2', '--h3', '--h4', '--h5', '--h6', '--h7'];
{
  const rootBlk = css.split(':root {')[1].split('}')[0];
  for (const t of WHEEL) ok(rootBlk.includes(t + ':'), 'Editorial declares ' + t);
  const band = WHEEL.map(t => Number(/hsl\([\d.]+ [\d.]+% ([\d.]+)%/.exec(
    rootBlk.split(t + ':')[1])[1]));
  ok(Math.min(...band) >= 60 && Math.max(...band) <= 82,
     'and every one of them sits in ONE lightness band on dark (' +
     Math.min(...band) + '–' + Math.max(...band) + '%)');
  for (const sel of ['html[data-theme="light"]', 'html[data-design="studio"][data-dvariant="light"]']) {
    const blk = css.split(sel + ' {')[1].split('}')[0];
    const lb = WHEEL.map(t => Number(/hsl\([\d.]+ [\d.]+% ([\d.]+)%/.exec(
      blk.split(t + ':')[1])[1]));
    ok(Math.max(...lb) <= 52,
       sel + ' re-bands the wheel DOWN for a light ground (max ' + Math.max(...lb) + '%)');
    ok(/--ring:/.test(blk) && /--zborder:/.test(blk),
       sel + ' also restates the ring/hairline tokens (a white ring is nothing on paper)');
  }
}
const cssBody = css.split('* { box-sizing')[1] || '';
const hexes = (cssBody.match(/#[0-9a-fA-F]{3,8}\b/g) || []);
ok(hexes.length === 0, `no hard-coded colour in any layout rule (found ${hexes.join(', ') || 'none'})`);
ok((cssBody.match(/rgba?\(/g) || []).length === 0, 'no hard-coded rgba() either');
ok(!/localStorage\.setItem\(\s*['"]motdeck-(theme|chrome|design)/.test(html),
   'the page NEVER writes the panel’s three appearance keys');
ok(/getItem\('motdeck-theme'\)/.test(html) && /getItem\('motdeck-chrome'\)/.test(html)
   && /getItem\('motdeck-design'\)/.test(html), '…it only reads all three');
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

// ── 5. THE CONSERVATION LAW ──────────────────────────────────────────────────
// Every honest mechanic of the CURRENT Music view (index.html #view-music), and where
// it lives here. Nothing is deleted; everything is demoted.
console.log('\n5. conservation — every honest mechanic of the Music view, and its new home');
const all = [daily, first, inst, empty, running, failedJob, cancelled, warned, sheet,
             track, presets, many].map(r => r.markup).join('\n');
const halfSheet = runPage(ST({ engines: [MINIMAX, absent(ACESTEP)] }), LIB,
                          (S) => { S.sheet = 'engines'; });
ok(/data-act="install"/.test(first.markup) && /data-act="install"/.test(halfSheet.markup),
   '1. engine install: the stage’s Get buttons + the sheet’s action chip');
ok(/On disk ✓/.test(halfSheet.markup) && /Get 7\.6 GB/.test(halfSheet.markup),
   '…and a half-installed pair states each engine’s own truth on its own row');
ok(/Retry install/.test(M.engineStateVerdict(Object.assign({}, absent(MINIMAX),
   { install_error: 'x' })).chip), '2. install failure: a Retry chip carrying the error');
ok(/data-act="pick-engine"/.test(sheet.markup) && /data-act="engines"/.test(daily.markup),
   '3. engine choice as a real named trade-off: a chip at rest, the comparison one tap down');
ok(/minimax-community/.test(sheet.markup), '4. per-engine licence: a chip in the sheet');
ok(/GB while rendering/.test(sheet.markup), '5. the RAM figure: a chip with a provenance hover');
ok(/data-act="presets"/.test(daily.markup) && /Neo-soul/.test(presets.markup),
   '6. templates: the presets sheet, one tap, with the built-ins intact');
ok(/data-act="save-preset"/.test(presets.markup) && /data-act="forget-preset"/.test(
     runPage(ST({ templates: [{ id: 'mine', name: 'Mine', tag: 'x', prompt: 'y' }] }), LIB,
             (S) => { S.sheet = 'presets'; }).markup),
   '7. save-as-template and forget-template: both in that sheet');
ok(/id="f-prompt"/.test(html) && /id="f-lyrics"/.test(html.replace(/\n/g, '')),
   '8. prompt + lyrics: at rest, lyrics as the ONE promoted field');
ok(/id="f-lyrics"/.test(html) && /id="lyrlabel"/.test(html),
   '…and in v2 lyrics STANDS on the line beside the prompt (a stronger promotion than '
   + 'v1\u2019s collapsed chip), with the [Verse]/[Chorus] teaching still on its label\u2019s hover');
ok(/\[Verse\] \/ \[Chorus\]/.test(html), '…which still carries the tag grammar');
ok(/id="f-secs"/.test(daily.markup), '9. length: a control at rest, with its range on the hover');
ok(/id="f-steps"/.test(runPage(ST(), LIB, (S) => { S.more = true; }).markup),
   '10. steps: More ▸, with the engine’s default as the placeholder');
// THE DOT IS MEASURED AGAINST THE ENGINE'S DEFAULTS, not against emptiness. Walked
// live: the write-back put the steps a run actually used (which WERE the default) into
// the field, and the dot claimed a hidden edit that did not exist.
const atDefault = runPage(ST(), LIB, (S) => { S.form.engine = 'minimax'; S.form.steps = '30'; });
ok(!/class="btn dotted"/.test(atDefault.markup),
   '10b. a written-back value that EQUALS the engine default does not dot More ▸');
const edited = runPage(ST(), LIB, (S) => { S.form.engine = 'minimax'; S.form.steps = '12'; });
ok(/class="btn dotted"/.test(edited.markup),
   '10c. …and a real difference still does (a hidden edit is never silent)');
ok(!/class="btn dotted"/.test(runPage(ST({ engines: [absent(MINIMAX), absent(ACESTEP)] }),
     [], (S) => { S.form.steps = '8'; }).markup),
   '10d. …and with NO engine on disk there is no default to differ from, so it says '
   + 'nothing rather than guessing');
ok(/id="f-seed"/.test(runPage(ST(), LIB, (S) => { S.more = true; }).markup),
   '11. seed: More ▸, with the determinism essay on its hover');
ok(/id="f-fmt"/.test(runPage(ST(), LIB, (S) => { S.more = true; S.form.engine = 'acestep'; }).markup),
   '12. format: More ▸, and only when the engine can write more than one');
ok(/id="go" class="press" data-act="go"/.test(html) && /data-act="go-anyway"/.test(warned.markup),
   '13. compose + the RAM override: kept exactly, as an advisory (Compose now rides the '
   + 'prompt/lyrics line, so it is static markup whose disabled state is a property)');
ok(/class="bar"/.test(running.markup), '14. phase-aware progress bar: the stage, while it runs');
ok(/elapsed|·/.test(running.markup), '15. the elapsed clock: on the running chip');
ok(/data-act="stop"/.test(running.markup) && /armed\(b, 'Stop'\)/.test(html),
   '16. cancel, two-step armed: kept');
ok(/data-act="select"/.test(daily.markup), '17. the library: the strip, newest first');
ok(/<audio/.test(html) || /createElement\('audio'\)/.test(html),
   '18. playback: promoted from a per-row button to the hero stage');
ok(/data-act="reuse"/.test(daily.markup),
   '19. re-use these settings: on the stage and in the track sheet');
ok(/data-act="reuse-seed"/.test(daily.markup),
   '20. the drawn seed: a click-to-reuse caption chip (it used to be a blank field asking '
   + 'a question up front)');
ok(/took 26m 32s|took /.test(daily.markup), '21. the measured "rendered in Ns": a caption chip');
ok(/data-act="convert"/.test(track.markup), '22. convert to mp3/m4a: the track sheet');
ok(/data-act="reveal"/.test(track.markup) && /data-act="reveal-dir"/.test(sheet.markup),
   '23. Reveal (file and folder): kept, and it SHOWS the place instead of printing it');
ok(/data-act="delete"/.test(track.markup) && /armed\(b, 'Delete'\)/.test(html),
   '24. delete, two-step armed: kept');
ok(/data-act="edit-dir"/.test(sheet.markup) && /data-act="set-dir"/.test(html),
   '25. change the output folder (a typed path — WKWebView has no folder picker): the sheet');
ok(/no sidecar|titleOf/.test(html) && M.titleOf({ name: 'x.wav' }) === 'x.wav',
   '26. a track with no sidecar is still listed and still named');
ok(/function section\(/.test(html) && /failed to draw/.test(html),
   '27. per-section render isolation (a walked /comfy defect): carried over');
ok(/arm\(running\(\) \|\| installing\(\) \? 1000 : 20000\)/.test(html),
   '28. the poll costs nothing when nothing is happening (1s live, 20s idle)');
// …AND IT KEEPS POLLING. Walked live: the page polled exactly once and then went
// quietly stale, because a FIRED setTimeout leaves its handle truthy and the
// "already armed" guard skipped the re-arm. Same defect and fix as comfy.html's arm()
// (v1.5.41) — the class, pinned here so neither page can regrow it.
ok(/timer = setTimeout\(\(\) => \{ timer = null; load\(\); \}, ms\)/.test(html),
   '28b. the timer clears its own handle when it fires, so the next render re-arms it '
   + '(a page that polls once and then lies about "now" is the worst version of this)');
ok(/new EventSource\('\/api\/events'\)/.test(html)
   && /msg\.type !== 'music'/.test(html)
   && /musicEventRefresh = setTimeout\(load, 120\)/.test(html),
   '28c. Music events nudge the SAME load() path; no second state/render path was invented');
ok(/arm\(running\(\) \|\| installing\(\) \? 1000 : 20000\)/.test(html),
   '28d. push did not delete active progress or dead-stream backstop polling');
// Comments may NAME alert(); routine feedback remains non-modal even though S12 now
// gives embedded pages a working native-dialog fallback.
const codeOnly = html.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/<!--[\s\S]*?-->/g, ' ')
                     .replace(/^\s*\/\/.*$/gm, ' ');
ok(/function toast\(/.test(html) && !/(^|[^.\w])alert\s*\(/.test(codeOnly),
   '29. routine feedback stays in the non-modal toast rather than a blocking alert');
ok(/S\.form\.steps = String\(j\.steps\)/.test(html) && /S\.form\.seed = '';/.test(html),
   '30. write-back: a finished run’s values land in the ordinary controls, and the seed '
   + 'still resets to random');

// ── 6. the lies this page could tell ─────────────────────────────────────────
console.log('\n6. the lies this page could tell, pinned shut');
const hero = daily.M.heroTrack();
ok(hero.name === LIB[0].name, 'the hero is the NEWEST track unless one is selected');
const heroHtml = (daily.env.written.find(w => w.id === 'stage-body') || {}).html || '';
ok(heroHtml.indexOf(daily.M.titleOf(hero)) > -1,
   'the stage names the track it is about…');
const audio = daily.env.created.find(n => n.id === 'new:audio');
ok(audio && audio.getAttribute('src') === daily.M.fileSrc(hero),
   '…and PLAYS THAT SAME FILE — one track object feeds the title and the src, so the '
   + 'stage cannot name one song and play another');
const picked = runPage(ST(), LIB, (S) => { S.sel = TRACK.name; });
const pickedAudio = picked.env.created.find(n => n.id === 'new:audio');
ok(pickedAudio.getAttribute('src') === picked.M.fileSrc(TRACK),
   'selecting a track from the strip moves BOTH the name and the audio');
// The player must survive the poll: a re-render may not reset playback.
const before = audio.getAttribute('src');
daily.M.render();
const audios = daily.env.created.filter(n => n.id === 'new:audio');
ok(audios.length === 1 && audios[0].getAttribute('src') === before,
   'a re-render does NOT rebuild the player or re-set its src (a poll that restarted the '
   + 'song every 20 seconds would be this page’s worst bug)');
ok(/getAttribute\('src'\) !== src/.test(html),
   '…and that is enforced in the source, not by luck of ordering');
// WALKED DEFECT, PINNED: the player measured 0px wide in the live page because <audio>
// is inline and its host was a shrink-to-fit grid item — the width has to sit on the
// HOST, with the element filling it. Present-correct-and-invisible is still broken.
ok(/#player-host audio \{ display:block; width:100%/.test(css) &&
   /<div id="player-host"><\/div>/.test(html),
   'the player lives in its OWN host outside every innerHTML\u2019d region, and the element '
   + 'fills that host (v1 measured 0px wide when the percentage sat on the inline <audio>)');
ok(html.indexOf('<div id="player-host">') < html.indexOf('<div id="hints">'),
   '\u2026and that host is static markup, so no renderer can take the player with it');
ok(/canvas\.wf \{ display:block; width:100%/.test(css),
   'the waveform canvas has the same discipline: the box sizes it, the canvas fills the box');

// Write-back, executed.
const done = runPage(ST({ job: { id: 'j9', state: 'done', engine: 'acestep', seconds: 90,
  steps: 12, seed: 5, format: 'mp3', wall: 30, out: 'acestep-x.wav' } }), LIB);
ok(done.M.S.form.seconds === 90 && done.M.S.form.steps === '12' && done.M.S.form.engine === 'acestep',
   'the finished run’s ACTUAL values land in the ordinary controls (the Pixelmator mechanic)');
ok(done.M.S.form.seed === '',
   '…and the seed field resets to random, with the drawn seed on the track’s own chip');
ok(done.M.S.sel === null, '…and the stage moves to the song that was just made');

// A track that vanished under an open sheet must say so rather than draw a ghost.
const ghost = runPage(ST(), LIB, (S) => { S.sheet = 'track'; S.detail = 'gone.wav'; });
ok(/no longer in the library/.test(ghost.markup),
   'a track deleted under an open sheet says so instead of drawing a ghost');


// ── 7. THE WAVEFORM: the identity, and the one place this page could lie ─────
// Debi's constraint at GO: never paint fake sections. The waveform is the only
// saturated object on the page, so if its colour claimed a structure the audio does
// not have, the page's most attractive element would be its biggest lie.
console.log('\n7. the waveform — colour that is measured, or no colour at all');
const AN_SECTIONS = { v: 2, duration: 60, mode: 'sections', derived: true,
  method: 'energy envelope (RMS over 0.25 s frames), derived from the audio',
  peaks: Array.from({ length: 240 }, (_, i) => (i % 7) / 7 + 0.2),
  sections: [{ start: 0, end: 13.25, level: 1, label: 'steady', energy: 0.53 },
             { start: 13.25, end: 60, level: 2, label: 'loud', energy: 0.49 }] };
const AN_RAMP = Object.assign({}, AN_SECTIONS, { mode: 'ramp', sections: [] });
const withWave = (an, err) => (S) => {
  S.wave[TRACK2.name] = err ? { error: err } : { analysis: an };
};
{
  const M2 = daily.M;
  const pend = M2.waveVerdict({ pending: true });
  ok(pend.state === 'pending' && /Measuring/i.test(M2.tipPlain(pend)),
     'while the analysis is being computed the chip says so — it never shows a shape early');
  const none = M2.waveVerdict({ error: 'this track could not be decoded for analysis' });
  ok(none.state === 'none' && none.chip === 'no waveform',
     'a track that cannot be decoded gets NO waveform, and the chip says exactly that');
  ok(/still plays/.test(M2.tipPlain(none)),
     '…while the song itself still plays (graceful absence, not a dead block)');
  const sec = M2.waveVerdict({ analysis: AN_SECTIONS });
  ok(sec.state === 'sections' && /2 sections · derived/.test(sec.chip),
     'a measured segmentation is labelled DERIVED on the chip itself');
  ok(/not verses and choruses/.test(M2.tipPlain(sec)) &&
     /Neither engine reports musical structure/.test(M2.tipPlain(sec)),
     'LIE GUARD: the hover states what the colour is and what it is NOT');
  ok(/energy envelope/.test(M2.tipPlain(sec)),
     '…and carries the method that produced it (provenance, off the same object)');
  const ramp = M2.waveVerdict({ analysis: AN_RAMP });
  ok(ramp.state === 'ramp' && /one hue/.test(ramp.chip),
     'audio that did not segment falls back to ONE hue, and says so');
  ok(/inventing them/.test(M2.tipPlain(ramp)),
     '…with the reason in the hover rather than a drawn boundary');
  for (const v of [pend, none, sec, ramp]) {
    ok(words(v.chip) <= 6, 'the waveform chip stays chip-length ("' + v.chip + '")');
    ok(/t-line/.test(M2.tipHtml(v)), '…and its hover comes off the same object');
  }
}
{
  // THE LEGEND AND THE STRUCTURE BLOCK ARE THE SAME NUMBERS AS THE COLOUR.
  const res = runPage(ST(), LIB, withWave(AN_SECTIONS));
  const struct = (res.env.written.filter(w => w.id === 'secbody').pop() || {}).html || '';
  ok(/steady/.test(struct) && /loud/.test(struct),
     'the STRUCTURE block prints the measured runs, so the hue is never mere decoration');
  ok(/0:00 – 0:13/.test(struct) && /53%/.test(struct),
     '…with each run\u2019s own times and measured energy');
  ok(!/verse|chorus/i.test(struct), '…and never a musical role');
  const rampRes = runPage(ST(), LIB, withWave(AN_RAMP));
  const rampBody = (rampRes.env.written.filter(w => w.id === 'secbody').pop() || {}).html || '';
  ok(!/class="erow"/.test(rampBody) && /one hue/.test(rampBody),
     'in ramp mode the STRUCTURE block lists NOTHING and says why — no invented rows');
  const errRes = runPage(ST(), LIB, withWave(null, 'this track could not be decoded'));
  const errBody = (errRes.env.written.filter(w => w.id === 'secbody').pop() || {}).html || '';
  ok(/no waveform/.test(errBody), 'a failed analysis is stated, in a chip, where it happened');
  ok(res.M.LEVEL_TOKEN.length === 3 && res.M.LEVEL_TOKEN.every(t => /^--h\d$/.test(t)),
     'the three level hues are TOKENS (so every one of the six looks re-bands them)');
}
ok(/const secs = \(an\.mode === 'sections' && an\.sections\) \? an\.sections : null;/.test(html),
   'the painter reads sections ONLY in sections mode — the fallback is structural, not a '
   + 'convention someone has to remember');
ok(/S\.wave\[t\.name\] = \{ pending:true \}/.test(html) && /if \(S\.wave\[t\.name\]\) return;/.test(html),
   'the analysis is fetched ONCE per track, and a failure is remembered rather than '
   + 'respawning a decode on every 20-second poll');

// ── 8. THE WORKBENCH: the grid, the drag, and the arrangement that must survive ─
// The adversarial worst case here is not a crash: it is a layout the user arranged by
// hand that silently resets, which is the same class as a lost edit.
console.log('\n8. the block grid, the docks, and the arrangement that is remembered');
const BLOCKS = ['wave', 'engines', 'ledger', 'queue', 'structure', 'reuse', 'library', 'disk'];
for (const b of BLOCKS) ok(html.includes('data-block="' + b + '"'),
  'the ' + b + ' block is a real, draggable block');
ok((html.match(/class="panel block/g) || []).length === BLOCKS.length,
   'every block carries the one block chrome (' + BLOCKS.length + ' of them)');
ok(/#blocks \{ display:grid; grid-template-columns:repeat\(3, minmax\(0,1fr\)\)/.test(css),
   'the grid is three per row (Debi\u2019s spec), two per row under 1180px');
ok(/e\.target\.closest\('\.block > \.pbar\.grab'\)/.test(html),
   'the LABEL BAR is the drag handle, and only the label bar');
ok(/closest\('button,input,textarea,select,a'\)/.test(html),
   '…so a control inside a block is never stolen by a drag');
ok(/const LAYOUT_KEY = 'compose-layout-v1'/.test(html),
   'the arrangement is persisted (localStorage, a per-machine VIEW preference — the same '
   + 'grammar as the panel\u2019s appearance keys, and it cannot fail a render)');
ok(/const CONTAINERS = \['blocks', 'spill'\]/.test(html) && /the dock strip is reserved/.test(html),
   'the reserved tool dock is NOT a drop target — a block cannot be lost into P6 space');
ok(/document\.body\.classList\.toggle\('shrunk', !!L\.shrunk \|\| parked > 0\)/.test(html),
   'RESTORE GUARD: a block parked in the spill slot forces the pane back into its shrunk '
   + 'state, or restoring it into a hidden container would make the block vanish');
ok(/Moved that block back to the grid/.test(html),
   'COLLAPSE GUARD: un-shrinking with blocks parked moves them back to the grid, with a '
   + 'toast — a control may never hide the user\u2019s own content');
ok(/saveLayout\(\);/.test(html.split('pointerup')[2] || ''),
   'a drop writes the arrangement immediately (no save-on-unload to lose)');
{
  // The reader is TOTAL about surprises: junk, unknown ids and a missing key all land
  // on a working page rather than an exception.
  const cases = [null, 'not json', '{"v":1}', '{"v":1,"blocks":["nope","wave"],"side":"right"}',
                 '[]', '{"v":1,"spill":["ledger"],"shrunk":false}'];
  for (const raw of cases) {
    let threw = false;
    try {
      const env = makeEnv();
      const fn = new Function('document', 'window', 'localStorage', 'fetch', 'setTimeout',
        'clearTimeout', 'addEventListener', 'location',
        bodyScript + '\n;return { readLayout, applyLayout };');
      const m = fn(env.document, env.window,
        { getItem() { return raw; }, setItem() {} },
        () => new Promise(() => {}), () => 0, () => {}, () => {}, env.window.location);
      m.applyLayout();
    } catch (e) { threw = true; }
    ok(!threw, 'a saved layout of ' + JSON.stringify(raw).slice(0, 34) +
       ' loads without throwing');
  }
}

// ── 9. the settings pane, the one line, and the dock strip ───────────────────
console.log('\n9. the pane, the line and the reserved dock');
ok(/body\.dock-right #bench \{ grid-template-columns:minmax\(0,1fr\) var\(--sw\)/.test(css),
   'docking is a grid-template swap (Blender\u2019s 140ms class of move), not a re-layout');
ok(/body\.shrunk #scol \{ grid-template-rows:minmax\(0,1fr\) minmax\(0,1fr\)/.test(css) &&
   /body\.shrunk #spill \{ display:grid/.test(css),
   'shrinking the pane to half height is what REVEALS the spill slot');
ok(/#line \{ display:grid; grid-template-columns:minmax\(0,1\.15fr\) minmax\(0,1fr\) auto/.test(css),
   'prompt | lyrics | Compose share ONE line');
ok(/\.fbox textarea \{[^}]*resize:none/.test(css) &&
   /t\.style\.height = Math\.min\(t\.scrollHeight \|\| 34, 168\) \+ 'px'/.test(html),
   '…and both fields grow DOWNWARD only, never wider');
ok(/id="dockslots"/.test(html) && (html.match(/class="ghost/g) || []).length === 3,
   'the dock strip stands one live ghost slot and two reserved ones');
ok(/stem separation \(demucs \/ UVR class\)/.test(html) && !/data-act="stem/.test(html),
   'P6 is NAMED as the first future occupant and NOTHING is built for it — no fake tool');

console.log(`\n${checks - fails}/${checks} checks passed`);
process.exit(fails ? 1 : 0);
