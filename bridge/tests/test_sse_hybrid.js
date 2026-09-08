/* THE SSE HYBRID, PANEL SIDE (2026-08-28) — the degradation state machine, EXECUTED.
 *
 * The bridge half is bridge/tests/test_events_hub.py. This file owns the half that
 * decides how often the panel asks, because that is where the whole safety argument
 * lives: Fable's design bar for this slice was "a dead push stream must degrade to
 * today's behaviour, not to a frozen UI". A source assertion that the words are
 * present would not prove that. So `pollCadenceMs` and `sseNext` are EXTRACTED FROM
 * THE SHIPPED PAGE and RUN, against the transitions a real session goes through:
 *
 *   1. the cadence table — every branch, in priority order, including the two that
 *      exist to protect a JOURNEY rather than a number (provisioning; a component
 *      that is already unhealthy keeps today's 6s watch);
 *   2. the state machine — connecting → live on a FRAME (never on `open`), live →
 *      down on error AND on staleness (the zombie-socket case), `off` terminal;
 *   3. the round trip: live → dead → recovered, asserting the cadence at each step
 *      is the number the brief specified;
 *   4. the wiring: the poll is DEMOTED, NOT REMOVED, and every event handler is a
 *      handler the page already had (zero new render logic).
 *
 * Run: node bridge/tests/test_sse_hybrid.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const swift = fs.readFileSync(path.join(ROOT, 'app', 'main.swift'), 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

// ── extract + execute the pure half ─────────────────────────────────────────
// Both anchors are asserted to EXIST before the slice is taken: an indexOf that
// returns -1 would silently hand `new Function` the top of the file, and every
// assertion below would then be testing something else entirely (the negative-scope
// class the office_grid suite was hardened against).
const start = html.indexOf("const SSE_URL        = '/api/events';");
const end = html.indexOf('function sseIsLive(st)');
ok(start > 0, 'the SSE constant block is where the test expects it');
ok(end > start, 'the pure block ends at sseIsLive');
const src = html.slice(start, html.indexOf('\n', end)) + '\n';
const M = new Function(src + `; return { POLL_FAST, POLL_WATCH, POLL_BACKSTOP,
  POLL_HEARTBEAT, SSE_STALE_MS, SSE_URL, pollCadenceMs, sseNext, sseIsLive };`)();

// ── 1. the cadence table ────────────────────────────────────────────────────
console.log('\n1. the cadence table');
const C = M.pollCadenceMs;
ok(M.POLL_FAST === 1500, 'provisioning cadence is unchanged from before the hybrid (1500)');
ok(M.POLL_WATCH === 6000, 'the watch cadence IS today\'s number (6000) — the pre-hybrid tail');
ok(M.POLL_BACKSTOP === 4000, 'the backstop is 4000, the cadence Fable specified');
ok(M.POLL_HEARTBEAT === 30000, 'the heartbeat is 30000');
ok(M.POLL_BACKSTOP < M.POLL_WATCH,
   'THE LOAD-BEARING INEQUALITY: degrading must not also mean getting SLOWER — the '
   + 'backstop polls faster than the cadence it replaces');
ok(M.POLL_HEARTBEAT > M.POLL_WATCH,
   '…and the only cadence that relaxes is the all-green idle one');

ok(C({sseLive: true}) === M.POLL_HEARTBEAT,
   'push live, nothing wrong → the 30s heartbeat (the whole point of the slice)');
ok(C({sseLive: false}) === M.POLL_BACKSTOP,
   'push DEAD → 4s backstop. This single line is the "degrades to a working UI" claim');
ok(C({}) === M.POLL_BACKSTOP, 'an empty state is treated as push-dead, not as push-live');
ok(C(null) === M.POLL_BACKSTOP, 'a MISSING state is treated as push-dead too — the '
   + 'fail-safe direction is "keep polling", never "assume the stream is fine"');
ok(C(undefined) === M.POLL_BACKSTOP, '…and so is undefined');
ok(C({sseLive: true, unhealthy: true}) === M.POLL_WATCH,
   'THE JOURNEY GUARD: something is already unhealthy → keep today\'s 6s. A component '
   + 'that dies on its own is not a transition we can push (see core/health.py), so '
   + 'the crash journey must not get 5× worse while the idle one gets better');
ok(C({sseLive: true, provisioning: true}) === M.POLL_FAST
   && C({sseLive: false, provisioning: true}) === M.POLL_FAST
   && C({sseLive: true, provisioning: true, unhealthy: true}) === M.POLL_FAST,
   'provisioning outranks EVERYTHING, push alive or dead');
ok(C({sseOff: true}) === M.POLL_WATCH
   && C({sseOff: true, sseLive: false}) === M.POLL_WATCH,
   'a runtime with NO EventSource falls back to yesterday (6s) — not to the 4s '
   + 'backstop, which would make a browser without push permanently BUSIER than before');
ok(C({sseOff: true, provisioning: true}) === M.POLL_FAST,
   '…and provisioning still wins there');
ok(Object.keys({provisioning:0, sseOff:0, sseLive:0, unhealthy:0}).every(
     k => new Set([C({sseLive:true, [k]:true}), C({sseLive:true, [k]:false})]).size === 2),
   'every documented input key is actually read by the function');

// ── 2. the state machine ────────────────────────────────────────────────────
console.log('\n2. the degradation state machine');
const N = M.sseNext;
const S0 = {phase: 'connecting', lastFrame: 0};
ok(N(S0, 'open', 1000).phase === 'connecting',
   'THE TRAP, PINNED: `open` does NOT mean live. EventSource fires onopen on HEADERS, '
   + 'which a proxy can produce for a stream that then delivers nothing');
ok(N(S0, 'frame', 1000).phase === 'live' && N(S0, 'frame', 1000).lastFrame === 1000,
   'a FRAME is what proves the stream, and it stamps the clock');
ok(M.sseIsLive(N(S0, 'frame', 1)) && !M.sseIsLive(N(S0, 'open', 1))
   && !M.sseIsLive(S0) && !M.sseIsLive(null),
   'sseIsLive agrees, and a null state is not live');
const LIVE = {phase: 'live', lastFrame: 10000};
ok(N(LIVE, 'error', 10001).phase === 'down', 'live → down on error');
ok(N(LIVE, 'open', 99999).phase === 'live',
   'a re-open on an already-live stream does not DEMOTE it (that would flap the cadence)');
ok(N(LIVE, 'tick', 10000 + M.SSE_STALE_MS - 1).phase === 'live',
   'a tick inside the staleness window leaves it live');
ok(N(LIVE, 'tick', 10000 + M.SSE_STALE_MS + 1).phase === 'down',
   'THE ZOMBIE SOCKET: silence past SSE_STALE_MS is death, even with no onerror — a '
   + 'WKWebView can hold a socket open that never errors');
ok(M.SSE_STALE_MS >= 3 * 25000,
   'the staleness window is at least three server pings (events.py PING_S = 25s), so '
   + 'a healthy QUIET stream can never be mistaken for a dead one');
const DOWN = {phase: 'down', lastFrame: 10000};
ok(N(DOWN, 'frame', 20000).phase === 'live',
   'down → live on the first frame after the browser\'s own reconnect');
ok(N(DOWN, 'error', 20000).phase === 'down', 'repeated errors stay down (idempotent)');
ok(N(DOWN, 'tick', 999999).phase === 'down',
   'a tick cannot resurrect a dead stream (only a frame can)');
const OFF = N(S0, 'unsupported', 0);
ok(OFF.phase === 'off', 'unsupported → off');
ok(['open', 'frame', 'error', 'tick', 'unsupported'].every(
     e => N(OFF, e, 12345).phase === 'off'),
   'off is TERMINAL: a runtime with no EventSource never gets one, so nothing may '
   + 'promote it back and start a reconnect loop that cannot succeed');
ok(N(S0, 'nonsense-event', 5).phase === 'connecting'
   && N(LIVE, '', 5).phase === 'live'
   && N(LIVE, null, 5).phase === 'live',
   'an unknown event is inert — it never changes the phase');
ok(N(undefined, 'frame', 7).phase === 'live' && N(null, 'tick', 7).phase === 'connecting',
   'a missing state defaults to connecting rather than throwing');
ok(typeof N(LIVE, 'frame', 1).lastFrame === 'number'
   && N({phase:'live'}, 'tick', 0).lastFrame === 0,
   'lastFrame is always a number (a missing one reads 0, which can only make it look '
   + 'STALE — the safe direction)');

// ── 3. the round trip, cadence at every step ────────────────────────────────
console.log('\n3. the full degradation round trip');
let st = {phase: 'connecting', lastFrame: 0};
const cad = () => C({sseLive: M.sseIsLive(st), sseOff: st.phase === 'off'});
ok(cad() === M.POLL_BACKSTOP,
   'boot, before any frame: 4s — the panel is live from the first tick with or without push');
st = N(st, 'open', 100);
ok(cad() === M.POLL_BACKSTOP, 'headers arrived but no frame yet: still 4s');
st = N(st, 'frame', 200);          // the bridge's `hello`
ok(cad() === M.POLL_HEARTBEAT, 'the hello frame lands → 30s heartbeat');
st = N(st, 'frame', 25200);        // a ping 25s later
ok(cad() === M.POLL_HEARTBEAT, 'a ping keeps it there');
st = N(st, 'error', 26000);        // the stream is killed
ok(cad() === M.POLL_BACKSTOP,
   'THE PROOF: the instant push dies the panel is back to 4s — never frozen');
st = N(st, 'error', 29000);
ok(cad() === M.POLL_BACKSTOP, 'and stays there while it is down');
st = N(st, 'frame', 40000);        // EventSource reconnected by itself
ok(cad() === M.POLL_HEARTBEAT, 'and relaxes again the moment the stream is back');
// the zombie path, end to end
st = N(st, 'tick', 40000 + M.SSE_STALE_MS + 1);
ok(cad() === M.POLL_BACKSTOP,
   'the same recovery works for a zombie stream that never fired onerror');

// ── 4. the wiring: demoted, not removed ─────────────────────────────────────
console.log('\n4. the poll is DEMOTED, not removed');
ok(/pollTimer = setTimeout\(refresh, pollCadenceMs\(pollState\(\)\)\);/.test(html),
   'the poll timer still exists and is armed from the cadence function');
ok(/^\s*refresh\(\);.*$/m.test(html) && /\bsseBoot\(\);/.test(html),
   'boot runs BOTH: one immediate poll and the subscription');
const bootTail = html.slice(html.lastIndexOf('applySolo();'));
ok(bootTail.indexOf('refresh();') < bootTail.indexOf('sseBoot();'),
   '…and the POLL goes first — the panel must be populated even if /api/events 404s '
   + 'on an older bridge');
ok(/function armPoll\(\)\s*\{[\s\S]{0,200}clearTimeout\(pollTimer\)/.test(html),
   'armPoll clears before it sets (no timer leak on an event-driven refresh)');
// THE REGRESSION THIS PINS: someone "finishing the migration" by deleting the poll.
ok(!/clearInterval\(sseStaleTimer\)/.test(html),
   'no extra staleness timer was added — refresh() carries the tick, so the idle path '
   + 'gains ZERO wakeups from this feature');
ok(/async function refreshStatusOnce\(manual\) \{\s*\n\s*sseStep\('tick'\);/.test(html),
   '…and that tick runs before the serialized status read');
// every handler is a handler the page already had
for (const [kind, fn] of [['download', 'refreshDownloads'], ['download', 'ensureDlPoll'],
                          ['nav', 'navSync'], ['model', 'initModels'],
                          ['model', 'loadChatModels'], ['component', 'refresh']]) {
  const disp = html.slice(html.indexOf('function sseDispatch(kind)'),
                          html.indexOf('function sseStep(ev)'));
  ok(disp.includes(fn), `the ${kind} handler reuses the existing ${fn}() — zero new render logic`);
}
const disp = html.slice(html.indexOf('function sseDispatch(kind)'),
                        html.indexOf('function sseStep(ev)'));
ok(!/innerHTML|createElement|insertAdjacentHTML/.test(disp),
   'the dispatcher renders NOTHING itself — it only calls poll handlers');
ok(/kind === 'music'/.test(disp) && /loadMusicStatus\(\)/.test(disp)
   && /loadMusicLibrary\(\)/.test(disp),
   'the music handler reuses existing status/library loaders — event payload is never state');
ok(/sseRun\('status', 120,/.test(disp) && /function sseRun\(key, ms, fn\)/.test(html),
   'bursty emitters are coalesced (starting one component publishes a phase per '
   + 'component in its closure; refresh() is three fetches)');
ok(/if \(j\.missed\)/.test(html),
   'a hub-side drop (`missed`) forces a full refetch — the client is told it is behind '
   + 'rather than left quietly stale');
ok(/sse\.onerror = \(\) => sseStep\('error'\);/.test(html)
   && !/setTimeout\([^)]*new EventSource/.test(html),
   'no hand-rolled reconnect loop: EventSource reconnects itself, honouring the '
   + 'server\'s retry: hint');
// THE STALE-ALARM DEFECT, found by driving (2026-08-28) and pinned so it cannot come
// back: on recovery the panel must take ONE reading before lengthening. It is behind by
// definition (it missed every transition while the stream was down), and after a bridge
// restart the last thing the poll wrote was `BRIDGE UNREACHABLE` — which then sat on
// screen for up to 30s after everything was fine.
{
  const step = html.slice(html.indexOf('function sseStep(ev)'),
                          html.indexOf('function sseBoot()'));
  const liveBranch = step.slice(step.indexOf("sseState.phase === 'live'"),
                                step.indexOf("sseState.phase === 'down'"));
  ok(/clearTimeout\(pollTimer\);\s*\n\s*refresh\(\);/.test(liveBranch),
     'recovering to live takes ONE reading immediately (a stale BRIDGE UNREACHABLE must '
     + 'not survive the recovery it contradicts)');
  ok(!/armPoll\(\);/.test(liveBranch),
     '…and does NOT merely re-arm at 30s, which is what left the stale alarm on screen');
  const downBranch = step.slice(step.indexOf("sseState.phase === 'down'"));
  ok(/clearTimeout\(pollTimer\);\s*\n\s*refresh\(\);/.test(downBranch),
     'and losing the stream also polls IMMEDIATELY — the whole point of the backstop is '
     + 'that the moment push stops, the UI does not');
}

ok(/window\.__sse = /.test(html),
   'a diagnostic handle exists, so "is this panel on push or on the backstop" is '
   + 'answerable without reading the console');

// ── 5. the shell keeps its poll, ON PURPOSE ─────────────────────────────────
console.log('\n5. the native shell');
ok(/let hermesGenPoll: TimeInterval = 4\b/.test(swift)
   && /let navPoll: TimeInterval = 5\b/.test(swift),
   'the shell\'s two polls are UNTOUCHED (4s hermes_config_gen, 5s nav_gen)');
ok(/hermesGenPoll[\s\S]{0,900}SSE HYBRID/.test(swift)
   || /SSE HYBRID[\s\S]{0,900}hermesGenPoll/.test(swift),
   'and the decision NOT to give the shell an SSE client is recorded next to them — '
   + 'that poll is now load-bearing for the panel (it is what calls /api/status often '
   + 'enough for _health_track to push a crash), so a future reader must not "finish '
   + 'the migration" by removing it');
ok(!/EventSource/.test(swift), 'no EventSource in the shell (it has no JS runtime here)');

console.log('');
console.log(fails ? fails + ' failure(s) of ' + checks
                  : 'sse hybrid: ' + checks + ' checks passed');
process.exit(fails ? 1 : 0);
