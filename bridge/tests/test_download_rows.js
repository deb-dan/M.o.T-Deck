/* THE DOWNLOAD ROW, EXECUTED (A14, 2026-08-29).
 *
 * Ledger row A14: `refreshDownloads` rendered EVERY state it did not recognise as
 * the single word "cancelled". v1.5.44 gave the bridge two new facts — a failed
 * verification (`corrupt:true`, `state:"error"`, the per-file `verified` naming
 * WHICH check said no) and a post-download hash phase (`phase:"verifying"` while
 * `state` stays "downloading") — so on the day that shipped, a model whose bytes
 * did not match HuggingFace would have announced itself to the user as A DOWNLOAD
 * THEY CANCELLED. That is the LIE class, and it is the class this file fences.
 *
 * The renderer is EXTRACTED FROM THE SHIPPED PAGE and RUN against a stub DOM +
 * a stub /api/dl, because a source-text assertion that the word "corrupt" appears
 * somewhere would not prove which row the user actually sees. What is pinned:
 *
 *   1. the corrupt row — its own chip, the FILE that failed, WHICH check failed
 *      (read from the bridge's own `verified`, never guessed), the full sentence
 *      on the hover title, and a Retry that is not a dead end;
 *   2. the verifying row — an honest label while a multi-GB digest runs, instead
 *      of a 100% bar at 0.0 MB/s that reads as a finished-or-stalled download;
 *   3. THE RULE: an unknown state renders ITS OWN NAME. Swept over a table of
 *      invented future states — none of them may render as another state's word;
 *   4. the untouched states (downloading / paused / done / cancelled) still say
 *      exactly what they said before;
 *   5. Retry replays the ORIGINAL Get — MLX repo mode's empty filename, a split
 *      GGUF's part 1, an audio pair's voice_format + explicit mmproj — and only
 *      dismisses the failed row once the new download really started;
 *   6. nothing on this path alert()s (the S12 class).
 *
 * Run: node bridge/tests/test_download_rows.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok   ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

/* ── brace-matched, COMMENT-AWARE extraction of a whole function declaration ──
   Same scanner as test_lane_affordances.js / test_attach_marker.js (this panel
   documents its bugs in prose, and prose has apostrophes), widened to return the
   DECLARATION — `async` included — so the extracted text can be re-declared. */
function grabDecl(name) {
  let at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  const pre = html.slice(Math.max(0, at - 6), at);
  if (pre.endsWith('async ')) at -= 6;
  let i = html.indexOf('{', at), depth = 0, inStr = null, prev = '', mode = '';
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (mode === 'line') { if (c === '\n') mode = ''; }
    else if (mode === 'block') { if (prev === '*' && c === '/') mode = ''; }
    else if (inStr) { if (c === inStr && prev !== '\\') inStr = null; }
    else if (c === '/' && html[j + 1] === '/') mode = 'line';
    else if (c === '/' && html[j + 1] === '*') mode = 'block';
    else if (c === '"' || c === "'" || c === '`') inStr = c;
    else if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return html.slice(at, j + 1); }
    prev = c;
  }
  throw new Error('unbalanced braces while extracting ' + name);
}

// The anchors must EXIST before anything is sliced: an indexOf that quietly
// returned -1 would hand MOT Deck the top of the file and every assertion
// below would be testing something else entirely.
const SRC_REFRESH = grabDecl('refreshDownloads');
const SRC_RETRY   = grabDecl('dlRetry');
ok(/^async function refreshDownloads\(/.test(SRC_REFRESH), 'refreshDownloads extracted from the shipped page');
ok(/^async function dlRetry\(/.test(SRC_RETRY), 'dlRetry extracted from the shipped page');

// ── stub DOM ────────────────────────────────────────────────────────────────
function mkEl(tag) {
  const el = { tag, className: '', hidden: false, children: [], _html: '', _text: '',
               parentNode: null, nextSibling: null,
               appendChild(c) { this.children.push(c); return c; },
               insertBefore() { /* placement only — asserted elsewhere */ } };
  Object.defineProperty(el, 'innerHTML', {
    get() { return el._html; },
    set(v) { el._html = String(v); el.children = []; } });
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    set(v) { el._text = String(v);
             el._html = String(v).replace(/&/g, '&amp;')
                                 .replace(/</g, '&lt;').replace(/>/g, '&gt;'); } });
  return el;
}

function makeTestHarness(list, opts) {
  opts = opts || {};
  const els = {};
  for (const id of ['downloads-sec', 'dl-list', 'models-main', 'models-aux', 'models-stamp'])
    els[id] = mkEl('div');
  const holder = mkEl('div');
  els['models-main'].parentNode = holder;
  const calls = { started: [], acted: [], alerts: 0, initModels: 0 };
  const state = { list };
  const document = {
    getElementById: id => els[id] || null,
    createElement: mkEl,
  };
  const fetch = async (url, init) => {
    if (url === '/api/dl') return { ok: true, json: async () => state.list };
    if (url === '/api/dl/start') {
      calls.started.push(JSON.parse(init.body));
      const ok = opts.startOk !== false;
      return { ok, json: async () => (ok ? { ok: true } : { ok: false, log: 'repo required' }) };
    }
    calls.acted.push(url);
    return { ok: true, json: async () => ({}) };
  };
  return { els, calls, document, fetch, setList(next) { state.list = next; } };
}

/* Run the SHIPPED renderer against one /api/dl payload. Everything the two
   functions close over is declared here — the free variables are named, not
   guessed, so a rename in the panel breaks this file loudly. */
async function render(list, opts) {
  const h = makeTestHarness(list, opts);
  const body = `
    "use strict";
    let dlPoll = null;
    const dlDismissed = new Set(${JSON.stringify([...(opts && opts.dismissed || [])])});
    let dlSeenDone = new Set();
    const dlLast = new Map();
    let browseView = false, pendingSelectId = null;
    function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
    function escAttr(s){ return esc(s).replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
    function fmtGB(b){ return (b/1073741824).toFixed(1) + ' GB'; }
    function ensureDlPoll(){ dlPoll = dlPoll || 1; }
    function initModels(){ calls.initModels++; }
    function toggleModelsBrowse(){ browseView = !browseView; }
    function dlDismiss(id){ dlDismissed.add(id); }
    function alert(){ calls.alerts++; }
    async function dlAct(id, act){ await fetch('/api/dl/' + id + '/' + act, {method:'POST'}); }
    async function dlStart(repo, filename, o){
      const b = { repo, filename };
      if (o && o.voice_format) b.voice_format = o.voice_format;
      if (o && o.mmproj) b.mmproj = o.mmproj;
      const r = await fetch('/api/dl/start', {method:'POST', body: JSON.stringify(b)});
      const j = await r.json();
      if (r.ok) return { ok: true };
      return { ok: false, log: j.log };
    }
    ${SRC_REFRESH}
    ${SRC_RETRY}
    return { refreshDownloads, dlRetry, dlDismissed, dlLast };
  `;
  const api = new Function('document', 'fetch', 'calls', body)(h.document, h.fetch, h.calls);
  await api.refreshDownloads();
  const rows = h.els['dl-list'].children.map(c => c._html);
  return { rows, h, api, sec: h.els['downloads-sec'], stamp: h.els['models-stamp'] };
}

const CORRUPT_SHA =
  'CORRUPT — model.gguf: sha256 abc123abc123… does not match the def456def456… ' +
  'HuggingFace publishes for this file. The byte count is right but the bytes are ' +
  'not. The partial file was deleted and nothing was added to your library — press ' +
  'Get again to retry.';

function entry(over) {
  return Object.assign({
    id: '1', repo: 'unsloth/SmolLM2-135M-Instruct-GGUF', model_id: 'SmolLM2-135M',
    kind: 'gguf', state: 'downloading', error: null, rate: 1048576,
    model_dir: null, voice_format: null, corrupt: false, phase: null, verified: null,
    files: [{ name: 'model.gguf', total: 100, done: 50, state: null, verified: null }],
  }, over || {});
}

(async () => {

// ══ 1. THE CORRUPT ROW ══════════════════════════════════════════════════════
{
  const e = entry({ state: 'error', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model.gguf', total: 100, done: 0, state: 'corrupt', verified: 'sha256' }] });
  const { rows } = await render([e]);
  const r = rows[0];
  ok(rows.length === 1, 'corrupt: one row rendered');
  ok(/class="dlstate bad">Corrupt</.test(r), 'corrupt: carries its OWN chip, not a shared error label');
  ok(!/cancelled/i.test(r), 'corrupt: the row NEVER says cancelled (A14, the whole reason this file exists)');
  ok(r.includes('model.gguf'), 'corrupt: names the file that failed');
  ok(r.includes('sha256 mismatch'), 'corrupt: says WHICH check failed, read from the bridge’s own `verified`');
  ok(r.includes('nothing added'), 'corrupt: says the library was left untouched');
  ok(r.includes('title="CORRUPT — model.gguf: sha256'),
     'corrupt: the bridge’s full human sentence rides the hover title (chip-first, v1.5.34)');
  ok(/dlRetry\('1'\)/.test(r) && /Retry/.test(r), 'corrupt: offers Retry');
  ok(/dlDismiss\('1'\)/.test(r), 'corrupt: still offers Dismiss');
  ok(/class="dlfill bad"/.test(r), 'corrupt: the progress bar is marked bad (tokens only)');
  // chip-first: the visible label is SHORT; the paragraph is on the hover only.
  const visible = r.slice(r.indexOf('dlmeta')).replace(/<[^>]*>/g, '').trim();
  ok(visible.length < 90, `corrupt: the visible meta stays chip-short (${visible.length} chars)`);
}

// ══ 1b. the OTHER corrupt verdict — a size mismatch is not a hash mismatch ══
{
  const e = entry({ state: 'error', corrupt: true,
    error: 'CORRUPT — w.gguf: the transfer ended at 90 bytes but HuggingFace says this file is 100 bytes.',
    files: [{ name: 'sub/dir/w.gguf', total: 100, done: 0, state: 'corrupt', verified: 'size' }] });
  const { rows } = await render([e]);
  ok(rows[0].includes('wrong size'), 'corrupt(size): reports the SIZE verdict, not sha256');
  ok(rows[0].includes('w.gguf') && !rows[0].includes('sub/dir'),
     'corrupt: a nested MLX path shows its leaf, not the whole relpath');
}

// ══ 2. THE VERIFYING ROW ════════════════════════════════════════════════════
{
  const e = entry({ state: 'downloading', phase: 'verifying', rate: 0,
    files: [{ name: 'model.gguf', total: 100, done: 100, state: 'verifying', verified: null }] });
  const { rows } = await render([e]);
  const r = rows[0];
  ok(/class="dlstate warn">Verifying</.test(r), 'verifying: has its own honest label');
  ok(r.includes('checking sha256'), 'verifying: says what is actually happening');
  ok(!/MB\/s/.test(r), 'verifying: does NOT render as a 0.0 MB/s download (the stalled-bar lie)');
  ok(!/cancelled/i.test(r), 'verifying: never says cancelled');
  ok(/class="dlfill verifying"/.test(r), 'verifying: the bar is marked, so a full bar is not read as finished');
  ok(/title="[^"]*not stuck/.test(r), 'verifying: the hover explains that a long hash is working, not stuck');
  ok(/Cancel/.test(r), 'verifying: Cancel stays — the bridge honours it the moment the digest ends');
  ok(!/Pause/.test(r), 'verifying: Pause is NOT offered — it is only honoured between chunks');
}

// ══ 2b. ADVERSARIAL: Cancel clicked DURING the hash ════════════════════════
// The bridge only clears `phase` once the digest returns, so for the length of a
// multi-GB hash the entry is state:"cancelled" WITH phase:"verifying". A row that
// keeps saying Verifying (with a Cancel button) after the user cancelled reads as
// a button that did nothing — the user's own action outranks the phase.
{
  const { rows } = await render([entry({ state: 'cancelled', phase: 'verifying', rate: 0,
    files: [{ name: 'model.gguf', total: 100, done: 100, state: 'verifying', verified: null }] })]);
  ok(/cancelled — nothing added/.test(rows[0]), 'cancel during the hash: the row honours the cancel');
  ok(!/Verifying/.test(rows[0]), 'cancel during the hash: it does NOT keep claiming to verify');
  ok(!/Cancel</.test(rows[0]), 'cancel during the hash: no second Cancel button to press');
}
// …and the same for a pause landing mid-hash (the bridge applies it on the next file).
{
  const { rows } = await render([entry({ state: 'paused', phase: 'verifying', rate: 0,
    files: [{ name: 'model.gguf', total: 100, done: 100, state: 'verifying', verified: null }] })]);
  ok(/paused · /.test(rows[0]) && !/Verifying/.test(rows[0]),
     'pause during the hash: the row reads paused, not verifying');
}
// A corrupt verdict is TERMINAL and survives a later cancel: the file really did
// fail verification and really was deleted; "cancelled" would erase that fact.
{
  const { rows } = await render([entry({ state: 'cancelled', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model.gguf', total: 100, done: 0, state: 'corrupt', verified: 'sha256' }] })]);
  ok(/Corrupt/.test(rows[0]), 'a corrupt verdict outranks a later cancel — the failure is the fact');
}

// ══ 2c. Retry's source of truth is pruned with the list ════════════════════
{
  const e = entry({ id: '7', state: 'error', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model.gguf', total: 1, done: 0, state: 'corrupt', verified: 'sha256' }] });
  const { api, h } = await render([e]);
  ok(api.dlLast.has('7'), 'retry map: populated from the rendered list');
  h.setList([]);                       // the bridge restarted / cleaned up
  await api.refreshDownloads();
  ok(!api.dlLast.has('7'),
     'retry map: pruned with the list — an id the bridge has forgotten is not kept forever');
}

// ══ 3. THE RULE — an unknown state renders ITS OWN NAME ═════════════════════
{
  // Every word this renderer knows. An unknown state may render its own name and
  // nothing else: borrowing any of these is the A14 lie, whatever the new state is.
  const OTHERS = ['cancelled', 'paused', 'complete', 'in your library', 'Corrupt', 'Verifying'];
  for (const st of ['quarantined', 'stalled', 'queued', 'expired', 'moved-upstream', '']) {
    const { rows } = await render([entry({ state: st, rate: 0, phase: null,
      files: [{ name: 'model.gguf', total: 100, done: 100, state: null, verified: null }] })]);
    const r = rows[0];
    const shown = st || 'unknown';
    ok(r.includes('>' + shown + '<'), `unknown state "${st}": renders its own name (${shown})`);
    for (const other of OTHERS)
      ok(!r.includes(other), `unknown state "${st}": never borrows the word "${other}"`);
  }
  // …and the fallback assignment that caused this is gone from the source.
  ok(!/meta\s*=\s*'cancelled'\s*;/.test(SRC_REFRESH),
     "the `else meta = 'cancelled'` fallback is gone (ledger A14's verify-still-open recipe)");
}

// ══ 4. THE UNTOUCHED STATES ═════════════════════════════════════════════════
{
  const { rows } = await render([entry({ state: 'downloading', rate: 2097152,
    files: [{ name: 'a.gguf', total: 1073741824, done: 536870912 }] })]);
  ok(/0\.5 GB of 1\.0 GB \(50%\) · 2\.0 MB\/s/.test(rows[0]), 'downloading: unchanged');
  ok(/Pause/.test(rows[0]) && /Cancel/.test(rows[0]), 'downloading: Pause + Cancel unchanged');
}
{
  const { rows } = await render([entry({ state: 'paused' })]);
  ok(/paused · /.test(rows[0]) && /Resume/.test(rows[0]), 'paused: unchanged');
}
{
  const { rows } = await render([entry({ state: 'done',
    verified: 'byte count and sha256 both verified against HuggingFace' })]);
  ok(rows[0].includes('complete — in your library'), 'done: unchanged');
  ok(/title="Verified: byte count and sha256/.test(rows[0]),
     'done: A10’s honest verification summary is reachable on hover instead of being dropped');
}
{
  const { rows } = await render([entry({ state: 'cancelled' })]);
  ok(/cancelled — nothing added/.test(rows[0]), 'cancelled: still says cancelled — for a real cancellation');
  ok(!/Retry/.test(rows[0]), 'cancelled: no Retry (the user meant it)');
}
{
  const { rows } = await render([entry({ state: 'error', corrupt: false,
    error: 'HTTP 404: not found. The repo may have moved.' })]);
  ok(/class="dlstate bad">Failed</.test(rows[0]), 'plain error: labelled Failed, not cancelled');
  ok(/Retry/.test(rows[0]), 'plain error: also retryable — it was a Dismiss-only dead end before');
  ok(/title="HTTP 404: not found\. The repo may have moved\."/.test(rows[0]),
     'plain error: the whole message is on the hover');
  const shown = rows[0].slice(rows[0].indexOf('dlmeta')).replace(/<[^>]*>/g, '');
  ok(shown.includes('HTTP 404: not found.') && !shown.includes('The repo may have moved'),
     'plain error: the row body shows the FIRST SENTENCE only — the paragraph does not spill');
}
{
  const { sec, rows } = await render([]);
  ok(sec.hidden === true && rows.length === 0, 'empty list: the section hides (graceful absence)');
}

// ══ 5. RETRY REPLAYS THE ORIGINAL GET ═══════════════════════════════════════
async function retryOf(e, opts) {
  const { api, h } = await render([e], opts);
  await api.dlRetry(e.id);
  return { started: h.calls.started, dismissed: api.dlDismissed.has(e.id) };
}
{
  const e = entry({ state: 'error', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model-00001-of-00003.gguf', state: 'corrupt', verified: 'sha256', total: 1, done: 0 },
            { name: 'model-00002-of-00003.gguf', total: 1, done: 1 },
            { name: 'model-00003-of-00003.gguf', total: 1, done: 1 }] });
  const { started, dismissed } = await retryOf(e);
  ok(started.length === 1 && started[0].repo === e.repo, 'retry: re-issues the Get to the same repo');
  ok(started[0].filename === 'model-00001-of-00003.gguf',
     'retry(split gguf): replays PART 1 — the bridge expands the set from it, as it did originally');
  ok(dismissed === true, 'retry: the failed row is replaced by the new attempt');
}
{
  const e = entry({ kind: 'mlx', state: 'error', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model.safetensors', state: 'corrupt', verified: 'sha256', total: 1, done: 0 },
            { name: 'config.json', total: 1, done: 1 }] });
  const { started } = await retryOf(e);
  ok(started[0].filename === '',
     'retry(mlx): the EMPTY filename is whole-repo mode — a file name here would be refused');
}
{
  const e = entry({ state: 'error', corrupt: true, error: CORRUPT_SHA, voice_format: 'tts-gguf',
    files: [{ name: 'qwen3-tts.gguf', state: 'corrupt', verified: 'sha256', total: 1, done: 0 },
            { name: 'mmproj-Q8_0.gguf', total: 1, done: 1 }] });
  const { started } = await retryOf(e);
  ok(started[0].voice_format === 'tts-gguf',
     'retry(audio): voice_format rides along, or the retry lands as a chat model');
  ok(started[0].mmproj === 'mmproj-Q8_0.gguf',
     'retry(audio): the EXPLICIT mmproj rides along — the lone-sibling heuristic does not fire on a TTS repo');
}
{
  // The bridge refuses the retry: the row must NOT vanish, or the user loses both
  // the error and the only button that could act on it.
  const e = entry({ state: 'error', corrupt: true, error: CORRUPT_SHA,
    files: [{ name: 'model.gguf', state: 'corrupt', verified: 'sha256', total: 1, done: 0 }] });
  const { dismissed } = await retryOf(e, { startOk: false });
  ok(dismissed === false, 'retry refused: the failed row STAYS, with its Retry still there');
}
{
  // Retry on an id the page has never rendered must be a no-op, not a request
  // with `undefined` in it (a stale click after a bridge restart cleared DOWNLOADS).
  const { api, h } = await render([entry({ state: 'error', corrupt: true, error: 'x' })]);
  await api.dlRetry('does-not-exist');
  ok(h.calls.started.length === 0, 'retry(stale id): a no-op, never a Get for undefined');
}

// ══ 6. the S12 class — nothing here alert()s ════════════════════════════════
// COMMENT-STRIPPED, because this panel's prose talks ABOUT alert() — a fence that
// fires on a comment explaining the rule is a fence that punishes documenting it.
const decomment = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
ok(!/\balert\s*\(/.test(decomment(SRC_REFRESH)) && !/\balert\s*\(/.test(decomment(SRC_RETRY)),
   'neither the row renderer nor Retry uses alert() (the S12 silent-no-op class)');

// ══ 7. ALL-DESIGNS: the new chips are TOKENS ONLY ═══════════════════════════
{
  // The whole download-row style block: from its first rule to the next section
  // marker. Both anchors are asserted, so a moved block fails loudly instead of
  // silently shrinking the text every assertion below is made against.
  const from = html.indexOf('.dlrow {');
  const to = html.indexOf('/* ---------- PHASE 1', from);
  ok(from > 0 && to > from, 'the download-row style block was located between its anchors');
  const block = html.slice(from, to);
  ok(/\.dlrow \.dlstate\b/.test(block), 'the state chip has a style');
  const decls = block.match(/(?:color|background|border-color|border)\s*:\s*[^;]+;/g) || [];
  const literal = decls.filter(d => /#[0-9a-fA-F]{3,8}|\brgba?\(/.test(d));
  ok(literal.length === 0,
     'every colour in the download-row block is a var() token — so all four themes + Studio '
     + 'light/dark inherit their own (ALL-DESIGNS rule)' + (literal.length ? ': ' + literal.join(' ') : ''));
  for (const tok of ['--bad', '--warn', '--line2'])
    ok((html.match(new RegExp('\\' + tok + ':', 'g')) || []).length >= 4
       && new RegExp('\\' + tok + ':').test(
            fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8')),
       `${tok} is defined by every theme in the panel AND by studio-design.css`);
  ok(/prefers-reduced-motion/.test(block), 'the verifying pulse is disabled under prefers-reduced-motion');

  /* THE CLASS, fenced (found live on this slice by the ALL-DESIGNS computed-value
     pass): a state MODIFIER written in index.html must out-specify the design
     pack's own base rule for the same element, or the pack — injected AFTER this
     <style> — silently wins and the corrupt bar draws in the accent colour. The
     obvious `.dlrow .dlfill.bad` (0,3,0) loses to studio-design.css's
     `html[data-design="studio"] .dlrow .dlfill` (0,3,1). This is not a one-off
     about a progress bar: it is true of every modifier this panel adds to an
     element the design pack already styles. */
  const sd = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8');
  const spec = sel => {                        // [id, class-ish, element] — enough for these
    const ids = (sel.match(/#[\w-]+/g) || []).length;
    const cls = (sel.match(/\.[\w-]+/g) || []).length
              + (sel.match(/\[[^\]]+\]/g) || []).length
              + (sel.match(/:(?!:)[\w-]+/g) || []).length;
    const el  = (sel.replace(/\[[^\]]+\]/g, '').match(/(^|[\s>+~])[a-zA-Z][\w-]*/g) || []).length;
    return [ids, cls, el];
  };
  const gt = (a, b) => a[0] !== b[0] ? a[0] > b[0]
                     : a[1] !== b[1] ? a[1] > b[1] : a[2] > b[2];
  const packRule = (sd.match(/^[^\n{]*\.dlrow\s+\.dlfill\s*\{/m) || [''])[0].replace(/\s*\{$/, '').trim();
  ok(packRule.length > 0, 'studio-design.css does style .dlrow .dlfill (the rule these must beat)');
  for (const mod of ['bad', 'verifying']) {
    const ours = (block.match(new RegExp('^[^\\n{]*\\.dlfill\\.' + mod + '\\s*\\{', 'm')) || [''])[0]
                   .replace(/\s*\{$/, '').trim();
    ok(ours.length > 0, `the .dlfill.${mod} modifier exists`);
    ok(gt(spec(ours), spec(packRule)),
       `.dlfill.${mod} [${spec(ours)}] out-specifies the design pack's `
       + `"${packRule}" [${spec(packRule)}] — or Studio repaints it in the accent colour`);
  }
}

console.log('');
console.log(fails ? `test_download_rows.js: ${fails} FAILED of ${checks}`
                  : `test_download_rows.js: all ${checks} checks passed`);
process.exit(fails ? 1 : 0);

})().catch(err => { console.error(err); process.exit(1); });
