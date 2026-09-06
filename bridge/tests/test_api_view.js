/* THE API VIEW (bridge/panel/index.html, #view-api) — ledger S32.
 *
 * Run: node bridge/tests/test_api_view.js
 *
 * WHAT THIS FILE GUARDS, group by group:
 *
 *  1. THE NAV SEAM. A sidebar-only entry that is NOT `tab_only` — v1.5.60's Music
 *     lesson applied before the mistake rather than after it, since `tab_only` is
 *     exactly what let a removed tab walk back onto the strip from the ⋯ menu. Plus
 *     the glyph census (no row may wear another row's or a chrome control's mark) and
 *     the solo exclusion, which Help had to write down explicitly and this inherits.
 *
 *  2. THE PURE RENDERERS, EXECUTED, over every state the page can reach: first run,
 *     the ordinary day, restart pending, runner off, runner loading, a key just
 *     minted, an empty log, metrics unavailable in each of its four ways. Extracted
 *     from the SHIPPED source and run — not retyped — so what is measured is what
 *     ships.
 *
 *  3. THE SENTENCE RULE AND THE CHIP GRAMMAR (the v1.5.34 standard the Generate and
 *     Compose pages already carry, and the reason this page is not born texty). A
 *     text node of eight words or more may live only inside `.say`; the number of
 *     `.say` elements standing at once is budgeted per state, and the ORDINARY DAY
 *     gets exactly ONE — the honest split note under the log, which is the one thing
 *     here that must not hide behind a hover. Chips stay at seven words or fewer.
 *
 *  4. THE REAL-DATA RULE. No sample row, no placeholder model name, no invented
 *     number — every state with nothing to show renders an empty line instead. And
 *     the one that matters most: a turn with no measured throughput yields "—" for
 *     its duration rather than 0.0s, which would read as instant.
 *
 *  5. SECRETS. The page must never render a full key except in the one-time reveal,
 *     never persist one, and never show the built-in's value or prefix.
 *
 *  6. ALL DESIGNS (Debi's standing rule), verified structurally: the API block's own
 *     CSS resolves every colour through var(--…) and hard-codes no hex, so Editorial,
 *     the three packs and studio light/dark all reach it through one token swap.
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const py = fs.readFileSync(path.join(ROOT, 'bridge', 'routers', 'apikeys.py'), 'utf8');
const navpy = fs.readFileSync(path.join(ROOT, 'bridge', 'nav.py'), 'utf8');
const swift = fs.readFileSync(path.join(ROOT, 'app', 'main.swift'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];
const script = html.split('</style>').slice(1).join('</style>');

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok  ' : '  FAIL ') + msg); if (!cond) fails++; }

// ── extract + execute the PURE half, from the shipped source ────────────────
const start = script.indexOf('const API_POLL_MS =');
const end = script.indexOf('function renderApi()');
ok(start > 0 && end > start, 'the API renderer block is where the test expects it');
const shim = `
  function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;'); }`;
const M = new Function(shim + script.slice(start, end) + `
  ; return { apiTime, apiDur, apiTok, apiDate, apiEndpointHtml, apiEndpointsHtml,
             apiKeysHtml, apiLogHtml, API_POLL_MS, API_METRIC_CHIPS };`)();

// ── a tiny markup auditor: (text node → nearest enclosing class) ────────────
/* Element-class based, exactly like the Generate page's: it does not care what any
   sentence SAYS, only where sentences are allowed to live.
   ⚠️ A CLOSED <details> DOES NOT STAND (added at S32, when the route catalogue arrived).
   The budget counts prose the reader is MADE to walk past, and six route sentences
   behind a disclosure the user has to open are not that — they are the click-to-expand
   zone the house taste asks for. The rule is deliberately narrow: `<details>` WITHOUT an
   `open` attribute hides its content from the count, and an `open` one does not, so the
   escape hatch cannot be used to smuggle standing prose past the budget. */
function audit(markup) {
  const out = [];
  const stack = [];
  const re = /<(\/?)([a-z][a-z0-9]*)([^>]*)>|([^<]+)/gi;
  let m;
  const hidden = () => stack.some(f => f.collapsed);
  while ((m = re.exec(markup))) {
    if (m[4] !== undefined) {
      const txt = m[4].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/\s+/g, ' ').trim();
      // A <summary> is the ALWAYS-VISIBLE half of a disclosure, so it stands even
      // though its parent <details> is closed — chips there are still chips on screen.
      const inSummary = stack.length && stack[stack.length - 1].tag === 'summary';
      if (txt && (!hidden() || inSummary))
        out.push({ text: txt, cls: stack.length ? stack[stack.length - 1].cls : '',
                   tag: stack.length ? stack[stack.length - 1].tag : '' });
      continue;
    }
    const closing = m[1] === '/', tag = m[2].toLowerCase(), attrs = m[3] || '';
    if (closing) { for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].tag === tag) { stack.length = i; break; } } continue; }
    if (/\/$/.test(attrs) || ['input', 'br', 'hr', 'img'].indexOf(tag) >= 0) continue;
    const c = /class="([^"]*)"/.exec(attrs);
    stack.push({ tag, cls: c ? c[1] : '',
                 collapsed: tag === 'details' && !/\bopen\b/.test(attrs) });
  }
  return out;
}
const words = s => String(s).split(/\s+/).filter(Boolean).length;

/* THE ONE AUDIT EVERY STATE GOES THROUGH. `budget` is the number of `.say` elements
   that state is allowed to stand — and the number is an argument rather than a
   constant because "how much prose is honest here" genuinely differs between the
   ordinary day (one line) and a state the user must act on. */
function prose(label, markup, budget) {
  const nodes = audit(markup);
  const long = nodes.filter(n => words(n.text) >= 8);
  const outside = long.filter(n => !/\bsay\b/.test(n.cls));
  ok(outside.length === 0,
     `${label}: every sentence lives in .say (${outside.length} stray${outside.length
       ? ': ' + outside.map(n => `[${n.cls || n.tag}] ${n.text.slice(0, 60)}`).join(' | ') : ''})`);
  const says = nodes.filter(n => /\bsay\b/.test(n.cls));
  ok(says.length <= budget,
     `${label}: at most ${budget} .say standing (found ${says.length}${
       says.length ? ': ' + says.map(n => n.text.slice(0, 44)).join(' | ') : ''})`);
  const chips = nodes.filter(n => /\b(chip|cap-pill)\b/.test(n.cls));
  const longChips = chips.filter(n => words(n.text) > 7);
  ok(longChips.length === 0,
     `${label}: every chip is ≤7 words (${longChips.map(n => n.text).join(' | ') || 'all short'})`);
  return nodes;
}

// ── the fixtures. REAL SHAPES: these are the objects the routes actually return. ──
const KEY_A = { id:'k_abc123', name:'Goose UI', prefix:'mot-1a2b…', created:'2026-08-29T10:00:00Z' };
const KEYS = (o) => Object.assign({
  ok:true, base_url:'http://127.0.0.1:6767/v1', port:6767,
  keys:[KEY_A], count:1, limit:64, remaining:63,
  pending:false, builtin:true, keyfile:'data/api_keys.keys' }, o || {});
/* THE ROUTE CATALOGUE, in the shape /api/apiendpoints returns — including the two that
   are REAL PATHS answering 501, which are the whole reason the section exists. */
const EPS = (o) => Object.assign({
  ok:true, base_url:'http://127.0.0.1:6767/v1', count:3, served_count:2,
  endpoints:[
    { path:'/v1/chat/completions', method:'POST', served:true,
      means:'Send a conversation, get the next message. This is the one almost every app uses.' },
    { path:'/v1/models', method:'GET', served:true,
      means:'Lists the one model this runner has loaded. Apps call it to fill their model dropdown.' },
    { path:'/v1/embeddings', method:'POST', served:false, enabled_by:'--embeddings',
      means:'Turns text into vectors for search. This model is loaded for chat, so the route answers 501.' },
  ] }, o || {});
const RUNNER = (o) => Object.assign({
  loaded:true, port_up:true, live_id:'Qwen3.6-27B-Fable-Q4_K_S', pin_intent:'Qwen3.6-27B' }, o || {});
/* ⚠️ THE ROW FIELD NAMES ARE THE **SEMANTIC** ONES (`started_at_epoch`,
   `prompt_tokens`, `completion_tokens`, `duration_seconds`) — the AI-friendly API
   checklist's rule, and the shape bridge/routers/apikeys.py::_rows actually publishes.
   They are NOT data/analytics.db's column names, and a test that used those would be
   asserting against a shape no consumer ever sees. */
const LOG = (o) => Object.assign({
  ok:true, metrics_state:'ok', count:1, total_count:1204, limit:40,
  metrics:{ prompt_tokens:14203, tokens_predicted:2211, decodes:2211, processing:0, tps:86.2 },
  rows:[{ started_at_epoch: Date.now()/1000, lane:'direct', lane_label:'Chat',
          model:'Qwen3.6-27B-Fable-Q4_K_S', prompt_tokens:87, completion_tokens:27,
          cached_tokens:0, tokens_per_second:86.2, duration_seconds:0.55 }] }, o || {});
const page = (k, r, l, minted, arm, note, eps) =>
  M.apiEndpointHtml(k, r) + M.apiEndpointsHtml(eps === undefined ? EPS() : eps)
  + M.apiKeysHtml(k, minted, arm, note) + M.apiLogHtml(l);

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n1. the nav seam — sidebar-only, and NOT tab_only');
// ═══════════════════════════════════════════════════════════════════════════
{
  const navStart = script.indexOf('const NAV_ENTRIES = [');
  const navEnd = script.indexOf('let navModel = null;');
  const N = new Function(script.slice(navStart, navEnd) + `; return { NAV_ENTRIES,
    NAV_SIDEBAR_ONLY, NAV_ALWAYS, NAV_OFFBAR, NAV_DEFAULT_SIDEBAR, NAV_TOPBAR_UNPINNED,
    navEntry, navCanShow, navCanTab };`)();
  const e = N.navEntry('api');
  ok(!!e, 'the registry has an `api` entry');
  ok(e.kind === 'view' && e.view === 'api', '…and it is a REAL panel view (not a dialog)');
  ok(!e.tab && !e.prefersTab,
     '…with no native tab, so a click can never be handed to the shell');
  ok(N.navCanShow('api', 'sidebar') && !N.navCanShow('api', 'topbar'),
     '…and the model refuses to put it on the strip');
  /* THE MUSIC LESSON, v1.5.60, applied in advance. `tab_only` let Music Classic reach
     the ⋯ menu and the last-three window, where one click re-created the tab the
     ruling had just removed. An entry that must never be a tab has to be refused by
     navCanTab as well as by navCanShow, or the strip is one overflow click away. */
  ok(!N.navCanTab('api'),
     'THE MUSIC LESSON: the strip can never draw it — no tab_only, so ⋯ cannot either');
  ok(N.NAV_OFFBAR.indexOf('api') < 0,
     '…and it is not off-bar either: it HAS a row, on exactly one bar');
  ok(N.NAV_SIDEBAR_ONLY.indexOf('api') >= 0 && N.NAV_ALWAYS.indexOf('api') >= 0,
     'it is sidebar-only AND `always` — hiding the row stays a legal choice');
  ok(N.NAV_DEFAULT_SIDEBAR.indexOf('api') === N.NAV_DEFAULT_SIDEBAR.indexOf('help') + 1,
     '…and the default sidebar puts it directly after Help');
  ok(N.NAV_TOPBAR_UNPINNED.indexOf('api') < 0,
     '…and the strip does not even DECLARE it (an entry it may never draw)');
  // THE GLYPH CENSUS — the v1.5.38 lesson in its general form.
  ok(!!e.ico, 'the row has an icon (the rail renders one per workspace row)');
  ok(N.NAV_ENTRIES.filter(x => x.ico && x.ico === e.ico).length === 1,
     'no other nav row wears its glyph');
  ok(['✦', '▣', '◐', '«', '⧉'].indexOf(e.ico) < 0,
     '…and it is not a chrome control\u2019s mark either');
  ok(swift.indexOf('MOTDeckTab(id: "api"') < 0,
     'the shell declares NO api tab — a sidebar-only entry must have nothing to pin');
  // nav.py is the AUTHORITY; the panel is the mirror.
  ok(/\{"id": "api",\s+"kind": "view",\s+"bars": \("sidebar",\), "always": True\}/.test(navpy),
     'bridge/nav.py declares the same shape (sidebar only, always, no topbar)');
  ok(navpy.indexOf('("api", True),') > 0, '…and puts it on the default sidebar');
  // the SOLO exclusion, executed — `?solo=api` must be a URL nothing can produce
  const solo = new Function(`const NAV_ENTRIES = ${JSON.stringify(
      [{ id:'mc', view:'mc' }, { id:'chat', view:'chat' }, { id:'api', view:'api' }])};
    const NAV_SIDEBAR_ONLY = ['logs','help','api'];
    ${/const SOLO_VIEWS[\s\S]*?\.map\(e => e\.view\);/.exec(script)[0]}
    ${/function soloView\(search\)[\s\S]*?\n}/.exec(script)[0]}
    return { SOLO_VIEWS, soloView };`)();
  ok(solo.SOLO_VIEWS.indexOf('api') < 0, 'executed: api is not a solo view');
  ok(solo.soloView('?solo=api') === null, '…and ?solo=api resolves to nothing');
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n2. the wiring');
// ═══════════════════════════════════════════════════════════════════════════
{
  ok(/<div id="view-api" hidden>/.test(html), 'the view exists in the document');
  ok(/document\.getElementById\('view-api'\)\.hidden = \(v !== 'api'\);/.test(script),
     'showView hides/shows it like every other view');
  ok(/if \(v === 'api'\) initApi\(\);/.test(script), '…and arms it on entry');
  ok(/else if \(!\(peekState && peekState\.view === 'api'\)\) stopApiPoll\(\);/.test(script),
     '…and RETIRES its poll on exit (Music\u2019s rule: never poll behind another view)');
  ok(/PEEK_VIEWS = \['models', 'music', 'caps', 'help', 'api'\]/.test(script),
     'API is peekable (⧉) — "what is the base URL again" is asked WHILE doing something');
  ok(/else if \(view === 'api'\) initApi\(\);/.test(script),
     '…and a peek arms it the same way a navigation does');
  ok(/st\.view === 'api' && curView !== 'api' && typeof stopApiPoll/.test(script),
     '…and handing a peek back stops the poll too');
  /* L4: the Restart button must recover from the shared route's stop/start race
     (start()'s thread reads `_running_sync` first and can skip the launch, leaving the
     runner DOWN). It retries the AUDITED START route — never a second copy of the kill
     logic, which is what the PROCESS-KILL RULE is protecting. */
  ok(/\/api\/components\/runner\/restart/.test(script)
     && /\/api\/components\/runner\/start/.test(script),
     'L4: Restart calls the audited restart AND retries the audited start');
  ok(!/runner\/stop/.test(script.slice(script.indexOf('async function apiRestartRunner'),
                                       script.indexOf('async function apiRestartRunner') + 1400)),
     '…and never stops anything itself — the kill logic stays in one place');
  ok(/if \(r\.loaded \|\| r\.port_up\) return;/.test(script),
     '…and it stops retrying the moment the runner is actually back');
  ok(/\{t:'API keys', k:'⌗', f:\(\)=>showView\('api'\)\}/.test(script),
     'the command palette has an API keys entry');
  ok(/`always` lets a\s*\n?\s*\/\/ user hide the API row/.test(script)
     || /`always` lets a[\s\S]{0,40}user hide the API row/.test(script),
     '…and it says WHY it is load-bearing (a key you cannot revoke is worse than none)');
  ok(/except Logs, Help and API, which stay reachable from ⌘K/.test(script),
     'the Customize dialog names all THREE always-reachable rows, not just two');
  // the empty-markup rule: nothing in the document may be a fact that can go stale
  const view = /<div id="view-api" hidden>[\s\S]*?\n  <\/div>/.exec(html)[0];
  ok(!/mot-/.test(view), 'the DOCUMENT contains no key-shaped literal');
  ok(!/127\.0\.0\.1:\d/.test(view), '…and no hard-coded endpoint (it comes from motdeck.yaml)');
  ok((view.match(/<table/g) || []).length === 0,
     '…and no table markup: every row is rendered from real data or not at all');
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n3. the pure formatters, executed');
// ═══════════════════════════════════════════════════════════════════════════
{
  ok(M.apiDur(0.55) === '0.6s' && M.apiDur(73.4) === '73s', 'durations read at two scales');
  ok(M.apiDur(null) === '—' && M.apiDur(undefined) === '—' && M.apiDur(NaN) === '—',
     'NO INVENTED DURATION: an unmeasured turn prints an em dash, never 0.0s');
  ok(M.apiTok(87) === '87' && M.apiTok(14203) === '14.2k', 'token counts stay short');
  ok(M.apiTok(null) === '0' && M.apiTok(undefined) === '0', '…and absent counts are 0, not NaN');
  ok(M.apiTime(0) === '—' && M.apiTime(null) === '—', 'a missing timestamp is an em dash');
  ok(/^\d\d:\d\d:\d\d$/.test(M.apiTime(Date.now() / 1000)), 'today shows a clock time');
  ok(/^\d\d-\d\d /.test(M.apiTime(1)), '…and another day carries its date');
  ok(M.apiDate('2026-08-29T10:00:00Z') === '2026-08-29' && M.apiDate('') === '—',
     'created dates are dates, and an absent one is an em dash');
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n4. every state, and the sentence rule');
// ═══════════════════════════════════════════════════════════════════════════

// (a) THE ORDINARY DAY — the screen Debi looks at. ONE sentence: the honest split.
const daily = page(KEYS(), RUNNER(), LOG());
const dailyNodes = prose('daily use', daily, 1);
ok(dailyNodes.filter(n => words(n.text) >= 8).length === 1,
   'daily use: the page stands exactly ONE sentence, and it is the log\u2019s split note');
ok(/Per-request rows cover MOT Deck's own lanes/.test(daily),
   '…which says per-request rows are ours and direct callers show only in the totals');
console.log('  ——   at rest (daily use): ' + dailyNodes.length + ' standing text elements, '
  + dailyNodes.filter(n => words(n.text) >= 8).length + ' sentences');
ok(/http:\/\/127\.0\.0\.1:6767\/v1/.test(daily), 'daily: the base URL is shown…');
ok(/onclick="apiCopy\(/.test(daily), '…with a copy affordance beside it');
ok(/>Serving</.test(daily) && /Qwen3\.6-27B-Fable-Q4_K_S/.test(daily),
   '…and the status + loaded model come from the status the panel already holds');
ok(/mot-1a2b…/.test(daily) && !/mot-1a2b[0-9a-f]/.test(daily),
   'daily: a key row shows its PREFIX and nothing more');
ok(/MOT Deck built-in/.test(daily) && /motdeck\.yaml/.test(daily),
   '…and the built-in is named as a row that cannot be revoked here');
ok(/>prompt 14\.2k</.test(daily) && />generated 2211</.test(daily),
   'daily: the runner totals are chips off /metrics — thousands abbreviated, small '
   + 'counts exact');
ok(/<td class="api-num">0\.6s<\/td>/.test(daily), '…and the row carries its real duration');

// (b) FIRST RUN — no keys yet. One invitation, plus the standing split note.
const first = page(KEYS({ keys: [], builtin: true }), RUNNER(), LOG({ rows: [] }));
prose('first run', first, 2);
ok(/No named keys yet/.test(first),
   'first run: an invitation, naming the apps that ask for a key');
ok(/No turns recorded yet/.test(first),
   '…and an empty log says so rather than showing a sample row');
ok(!/mot-/.test(first), '…with no key-shaped text anywhere on the page');

// (c) A KEY JUST MINTED — the one-time reveal, and it says it is one-time.
const minted = { id:'k_new', name:'Goose UI', key:'mot-' + 'f'.repeat(32), prefix:'mot-ffff…' };
const shown = page(KEYS({ pending: true }), RUNNER(), LOG(), minted, '');
prose('key just minted', shown, 3);
ok(shown.indexOf(minted.key) > 0, 'the full key is shown ONCE, here and nowhere else');
ok(/is not stored in readable form and is never shown again/.test(shown),
   '…and the page says so, so nobody discovers it by coming back');
ok(/Paste this into the app's provider form/.test(shown),
   '…and names what to do with it (Debi\u2019s brief, verbatim)');
ok(/apiCopy\(/.test(shown.split('api-reveal')[1] || ''), '…with a copy button on it');
ok(/apiDismissKey\(\)/.test(shown), '…and a way to put it away');

// (d) RESTART PENDING — the whole honesty of this feature at our pin.
const pend = page(KEYS({ pending: true }), RUNNER(), LOG());
prose('restart pending', pend, 2);
ok(/Restart to apply/.test(pend), 'pending: a chip says the keys are not live yet');
ok(/reads its key file only at startup/.test(pend),
   '…and one sentence says WHY (b10662 has no hot-reload — measured, not assumed)');
ok(/apiRestartRunner\(this\)/.test(pend),
   '…and the fix is offered as a button, not left as homework');

// (e) RUNNER OFF / LOADING — graceful absence, one line with the action in it.
const off = page(KEYS(), RUNNER({ loaded:false, port_up:false, live_id:'' }),
                 LOG({ metrics_state:'down', metrics:{} }));
prose('runner off', off, 2);
ok(/>Runner off</.test(off), 'runner off: a chip states it');
ok(/Start it in Mission Control/.test(off), '…and the sentence names where to fix it');
ok(!/>Serving</.test(off), '…and nothing claims it is serving');
const loading = page(KEYS(), RUNNER({ loaded:false, port_up:true, live_id:'' }),
                     LOG({ metrics_state:'ok' }));
prose('runner loading', loading, 2);
ok(/>Loading</.test(loading),
   'a live port with no model loaded reads as Loading, never as Serving or as off');

// (f) THE METRICS STATES — each absence names its own fix, none is a silent blank.
[['off', /Totals need a runner restart/], ['auth', /Totals refused the built-in key/],
 ['unreadable', /Totals unreadable/], ['down', /Runner off/]].forEach(([st, re]) => {
  const m = M.apiLogHtml(LOG({ metrics_state: st, metrics: {} }));
  prose('metrics ' + st, m, 1);
  ok(re.test(m), `metrics ${st}: the chip names what is missing and why`);
  ok(/Per-request rows cover/.test(m), `…and the split note still stands`);
});

// (g) NO CONFIG AT ALL, and the null shapes — nothing may throw.
ok(/No runner endpoint is configured/.test(M.apiEndpointHtml({ base_url: '' }, null)),
   'no runner in motdeck.yaml lands on an empty line, not a blank');
ok(M.apiEndpointHtml(null, null).indexOf('cs-empty') >= 0, 'a null keys payload renders');
ok(M.apiKeysHtml(null, null, '').indexOf('cs-empty') >= 0, 'a null keys section renders');
ok(M.apiLogHtml(null).indexOf('cs-empty') >= 0, 'a null log renders');
ok(M.apiLogHtml(LOG({ rows: null, metrics_state: 'ok' })).indexOf('No turns') >= 0,
   'a log with a null rows array renders its empty state');

// (h) THE ARMED REVOKE — two steps, and only ever one armed at a time.
const idle = M.apiKeysHtml(KEYS(), null, '');
const armed = M.apiKeysHtml(KEYS({ keys: [KEY_A, { id:'k_two', name:'B', prefix:'mot-2222…',
  created:'2026-08-29' }] }), null, 'k_abc123');
ok(/>Revoke</.test(idle) && !/cap-btn arm/.test(idle), 'a key row offers Revoke, unarmed');
ok(!/apiRevoke\(/.test(idle),
   '…and an UNARMED row cannot call the revoke at all — the first click only arms');
ok((armed.match(/cap-btn arm/g) || []).length === 1,
   'arming marks exactly ONE row, never all of them');
ok(/apiRevoke\(&quot;k_abc123&quot;\)/.test(armed), '…and only the armed row can fire it');
ok(/>Confirm</.test(armed) && (armed.match(/>Revoke</g) || []).length === 1,
   '…while the other row still says Revoke');

// (i2) EVERY onclick ATTRIBUTE IS ACTUALLY PARSEABLE — live finding L3.
/* THE BUG THIS PINS, because it is invisible every other way: the first draft emitted
   `onclick="apiArm("k_abc")"`, where the attribute ENDS at the second double quote. The
   button is silently inert — nothing throws, nothing logs, and a source-text assertion
   spelled /apiArm\("k_abc"\)/ passes on the raw string while the ONLY revoke control in
   the product does nothing. It was caught by clicking it in a live panel, and it can
   never come back: this parses each emitted attribute the way a browser would, and
   then EXECUTES the handler expression to prove it is a complete call. */
{
  const marks = [];
  ['idle', 'armed', 'endpoint', 'reveal'].forEach(() => {});
  const samples = [
    ['keys idle', M.apiKeysHtml(KEYS(), null, '')],
    ['keys armed', M.apiKeysHtml(KEYS(), null, 'k_abc123')],
    ['endpoint', M.apiEndpointHtml(KEYS(), RUNNER())],
    ['reveal', M.apiKeysHtml(KEYS(), { id:'k_n', name:'n', key:'mot-' + 'f'.repeat(32) }, '')],
  ];
  samples.forEach(([label, markup]) => {
    // the browser's own rule: the attribute value runs to the NEXT double quote
    const attrs = [...markup.matchAll(/onclick="([^"]*)"/g)].map(m => m[1]);
    ok(attrs.length > 0, label + ': has onclick handlers to check');
    attrs.forEach(a => {
      let parsed = true;
      try { new Function('apiArm', 'apiRevoke', 'apiCopy', 'apiDismissKey',
                         'apiRestartRunner', 'this_', a.replace(/&quot;/g, '"')); }
      catch (e) { parsed = false; }
      ok(parsed, label + ': onclick is a complete expression — "' + a.slice(0, 46) + '"');
      ok(a.indexOf('"') < 0,
         label + ': …and carries no RAW double quote, which would END the attribute '
         + 'early and leave the control silently inert (L3)');
    });
    marks.push(attrs.length);
  });
  ok(marks.reduce((a, b) => a + b, 0) >= 6, 'every state\u2019s handlers were checked');
}

// (i) HOSTILE DATA. A name is a user string and reaches the DOM through esc().
const nasty = M.apiKeysHtml(KEYS({ keys: [{ id:'k_x', name:'<img src=x onerror=alert(1)>',
  prefix:'mot-0000…', created:'2026-08-29' }] }), null, '');
ok(nasty.indexOf('<img src=x') < 0 && nasty.indexOf('&lt;img') > 0,
   'a hostile key name is ESCAPED, not injected');
const nastyModel = M.apiLogHtml(LOG({ rows: [{ started_at_epoch: 1, lane:'x', lane_label:'x',
  model:'<script>bad()</script>', prompt_tokens:1, completion_tokens:1,
  duration_seconds:1 }] }));
ok(nastyModel.indexOf('<script>bad') < 0, '…and so is a model id from the analytics table');
// …and a hostile ROUTE catalogue, which is ours but arrives over the wire like any other.
const nastyEp = M.apiEndpointsHtml(EPS({ endpoints: [{ path:'<b>/v1/x', method:'POST',
  served:false, enabled_by:'<i>--x', means:'A perfectly ordinary sentence about it.' }] }));
ok(nastyEp.indexOf('<b>/v1/x') < 0 && nastyEp.indexOf('<i>--x') < 0,
   '…and so is every field of a route row, including the flag name');

// (j) THE ROUTE CATALOGUE — the checklist's semantic-documentation clause, as a surface.
{
  const eps = M.apiEndpointsHtml(EPS());
  ok(/<details class="api-routes">/.test(eps) && !/<details class="api-routes" open/.test(eps),
     'routes: the catalogue is a CLOSED disclosure — six sentences may not stand on a '
     + 'page whose ordinary-day budget is one');
  ok(/<summary>[\s\S]*?2 routes served[\s\S]*?1 need a launch flag[\s\S]*?<\/summary>/.test(eps),
     '…with a glanceable summary that counts both halves');
  ok(/\/v1\/chat\/completions/.test(eps) && /\/v1\/models/.test(eps),
     'routes: the two every provider form needs are listed');
  // ⚠️ THE ONE THAT MATTERS. A 501 route is a REAL PATH that refuses, so an app pointed
  // here for embeddings fails in a way its own error blames on the address. Hiding the
  // row would leave that person with no way to find out — the omission class of lie.
  ok(/\/v1\/embeddings/.test(eps) && /needs --embeddings/.test(eps),
     'routes: a route that EXISTS and answers 501 is listed with the flag it needs, '
     + 'not hidden — the difference between a catalogue and a sales sheet');
  ok(/cap-pill on">served</.test(eps), '…while a served route is chipped as served');
  ok(M.apiEndpointsHtml(null) === '' && M.apiEndpointsHtml({ endpoints: [] }) === '',
     'routes: no catalogue renders NOTHING — never an empty box and never a sample row');
  // the budget: closed, it costs the page nothing; opened, its prose is still in .say
  prose('routes (closed)', eps, 0);
  prose('routes (opened)', eps.replace('<details class="api-routes">',
                                       '<details class="api-routes" open>'), 3);
}

// (k) THE COUNTING HINTS, rendered (checklist item 4: LLMs cannot paginate to a count).
{
  const many = M.apiLogHtml(LOG({ count:1, total_count:1204 }));
  ok(/1 of 1204 turns/.test(many),
     'counting: a clamped page says how many of how many, so a short table cannot be '
     + 'mistaken for a quiet afternoon');
  const all = M.apiLogHtml(LOG({ total_count: 1 }));
  ok(/>1 turn</.test(all) && !/ of /.test(all.split('api-tbl')[0]),
     '…and when the page IS everything it just says how many');
  // A COUNT WE COULD NOT TAKE IS NOT A ZERO. The route sends null; the page must not
  // turn that into "1 of 1", which would be a claim we cannot make.
  const unc = M.apiLogHtml(LOG({ total_count: null }));
  ok(/>1 turn</.test(unc) && !/of null/.test(unc) && !/of 0/.test(unc),
     '…and an UNCOUNTABLE table says how many are shown and stops, never "of ?"');
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n5. secrets, and the split the page must not paper over');
// ═══════════════════════════════════════════════════════════════════════════
{
  const block = script.slice(start, end);
  // COMMENTS STRIPPED FIRST: this block EXPLAINS in prose that it stores nothing, and
  // a substring search that the prose satisfies is not a test.
  const blockCode = block.replace(/\/\*[\s\S]*?\*\//g, '')
                         .split('\n').filter(l => !/^\s*\/\//.test(l)).join('\n');
  ok(blockCode.indexOf('localStorage') < 0 && blockCode.indexOf('sessionStorage') < 0,
     'nothing in this block persists anything — a minted key lives in memory only');
  ok(/apiState = \{[^}]*minted:null/.test(script),
     '…and the reveal starts empty on every load');
  ok(/keys\.builtin/.test(block) && block.indexOf('builtin_prefix') < 0,
     'the built-in is rendered from a BOOLEAN — the page never receives its value');
  ok(py.indexOf('"builtin": bool(') > 0,
     '…because the route publishes it as a bool, so there is nothing to leak');
  ok(/llama-server exposes no per-request[\s\S]{0,20}history at our pin/.test(block),
     'the split note carries its reason in the source, so a tidy-up cannot delete it '
     + 'as decoration');
  ok(/log-prompts-dir/.test(py),
     'and the router records the per-request facility we deliberately do NOT ship '
     + '(it writes users\u2019 prompts to disk)');
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n6. all designs — token-only, no hex in the API block');
// ═══════════════════════════════════════════════════════════════════════════
{
  const i = css.indexOf('---------- API (ledger S32) ----------');
  ok(i > 0, 'the API css block is where the test expects it');
  const blk = css.slice(i, css.indexOf('/* ----------', i + 40));
  const hexes = (blk.match(/#[0-9a-fA-F]{3,8}\b/g) || []);
  ok(hexes.length === 0,
     `the API block hard-codes no colour (${hexes.join(', ') || 'none'}) — every one `
     + 'resolves through var(--…), which is what makes the theme packs reach it');
  ok(/var\(--card2\)/.test(blk) && /var\(--line\)/.test(blk) && /var\(--gold\)/.test(blk),
     '…and it uses the palette tokens the packs actually swap');
  ok(/\.say \{/.test(css),
     'the sentence class is declared in the panel stylesheet, so the rule is the '
     + 'product\u2019s and not this page\u2019s');
  ok(!/rgba\(\d/.test(blk),
     '…and no literal rgba() either (the --on-wash lesson: a literal no palette can reach)');
}

console.log(`\n${checks} checks, ${fails} failures`);
process.exit(fails ? 1 : 0);
