/* Panel-side wiring test for TURN LIFECYCLE OWNERSHIP (2026-08-14).
 *
 * WHY this exists: the wedge Debi hit was not a rendering bug, it was an
 * OWNERSHIP bug. `chatBusy` was cleared in exactly one place — sendChat's
 * finally — which only runs when the SSE reader returns or throws. A Hermes turn
 * that never produced a terminal frame therefore pinned chatBusy TRUE forever,
 * and every escape hatch (+NEW, a rail click, a lane switch) was written as
 * `if (chatBusy) return;` — a SILENT no-op. Stop was unreachable after a lane
 * switch because the busy branch keyed off the CURRENT chip, not the turn's lane.
 *
 * So the invariants asserted here are all of the form "there is no path that
 * leaves the composer held hostage by a stream":
 *   • a force-end exists, aborts the fetch, and hard-releases the UI if that
 *     somehow is not enough;
 *   • Stop arms the force-end even with NO session id yet (pre-first-event);
 *   • +NEW / lane switch / session click reach the stop path instead of returning;
 *   • the send path's cleanup is in a finally that also clears the turn;
 *   • the bridge relay emits the heartbeat the panel's watchdog depends on.
 *
 * Run: node bridge/tests/test_turn_lifecycle.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const appy = fs.readFileSync(path.join(ROOT, 'bridge', 'app.py'), 'utf8');

let fails = [];
function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + name);
  if (!cond) fails.push(name);
}

function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  let i = html.indexOf('{', at), depth = 0, inStr = null, prev = '';
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (inStr) { if (c === inStr && prev !== '\\') inStr = null; }
    else if (c === '"' || c === "'" || c === '`') inStr = c;
    else if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return html.slice(at, j + 1); }
    prev = c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

/* Constants read OUT of the panel — a value changed there must change the
 * expectation here rather than silently passing against a stale copy. */
function constant(name) {
  const m = new RegExp('const\\s+' + name + '\\s*=\\s*([0-9]+)\\s*;').exec(html);
  if (!m) throw new Error('constant ' + name + ' not found in the panel');
  return Number(m[1]);
}

/* ── 1. the force-end itself ─────────────────────────────────────────────── */
const force = grab('forceEndTurn');
check('forceEndTurn exists and is idempotent (a second call is a no-op)',
  /if \(!t \|\| t\.ended \|\| t\.done\) return false;/.test(force) && /t\.ended = true;/.test(force));
check('a COMPLETED turn can never be force-ended — a +NEW clicked in the sliver '
    + 'between [DONE] and the socket closing must not stamp a finished reply',
  /t\.done/.test(force) && /turn\.done = true; turnStage\('done'\)/.test(html));
check('forceEndTurn ABORTS the fetch — that is what unblocks reader.read() and '
    + 'lets sendChat\'s finally do the real cleanup',
  /t\.ctl\.abort\(\)/.test(force));
check('forceEndTurn disarms its own watchdog', /clearTimeout\(t\.timer\)/.test(force));
check('forceEndTurn schedules the HARD release, so even a reader that ignores the '
    + 'abort cannot hold the composer', /setTimeout\(\(\) => turnHardRelease\(t\), \d+\)/.test(force));
check('forceEndTurn stamps the turn "interrupted (forced)" with the stage',
  /interrupted \(forced\)/.test(force));

const hard = grab('turnHardRelease');
check('turnHardRelease clears chatBusy and restores the Send button',
  /chatBusy = false;/.test(hard) && /sb\.textContent = 'Send'/.test(hard));
check('turnHardRelease only ever releases the turn it was armed for (a late timer '
    + 'must not kill the NEXT turn)', /if \(curTurn !== t\) return;/.test(hard));

/* ── 2. the diagnostic (which stage did it die in?) ──────────────────────── */
check('the force-end names the stage on the console AND in the activity feed',
  /console\.warn\('\[turn\] force-end/.test(force) && /feed\('chat', 'turn force-ended at/.test(force));
check('stages are recorded through ONE setter, so a stage cannot be written to a '
    + 'turn that already ended',
  /function turnStage\(s\)\{ if \(curTurn && !curTurn\.ended\) curTurn\.stage = s; \}/.test(html));
check('every phase of a turn labels itself',
  ['connecting', 'waiting for the first frame', 'thinking', 'answering',
   'running a tool', 'awaiting approval', 'prefill (bridge says hermes is working)']
    .every(s => html.indexOf(s) > 0));

/* ── 3. Stop always wins ─────────────────────────────────────────────────── */
const stop = grab('hermesStop');
check('Stop arms a client-side force-end BEFORE it touches the network',
  /t\.stopArmed = true;[\s\S]{0,200}setTimeout\(\(\) => forceEndTurn\([\s\S]{0,120}TURN_FORCE_MS\)/.test(stop));
check('the force-end is armed even with NO session id yet — the pre-first-event '
    + 'phase used to make Stop a silent no-op',
  stop.indexOf('t.stopArmed = true;') < stop.indexOf('if (!hermesSid || hermesStopping) return;'));
check('Stop still issues the gateway interrupt when there IS a sid',
  /fetch\('\/api\/hermes\/stop'/.test(stop));
check('the busy branch routes on the TURN\'s lane, not the current chip — so a '
    + 'lane switch can never make Stop unreachable',
  /if \(chatMode === 'hermes' \|\| \(curTurn && curTurn\.lane === 'hermes'\)\) hermesStop\('panel stop'\)/.test(html));

const stopNow = grab('stopTurnNow');
check('stopTurnNow does NOT await the gateway interrupt (session.interrupt can '
    + 'itself stall for its own 10s RPC timeout)',
  /[^t]\s+hermesStop\(reason\);/.test(stopNow) && !/await hermesStop/.test(stopNow));
check('stopTurnNow force-ends locally regardless of the interrupt',
  /forceEndTurn\(reason\);/.test(stopNow));

/* ── 4. no escape hatch may be a silent no-op ────────────────────────────── */
for (const [fn, label] of [['newSession', '+NEW'], ['selectSession', 'a rail row'],
                           ['selectHermesSession', 'a Hermes rail row'],
                           ['duplicateSession', 'duplicate']]) {
  const src = grab(fn);
  check(label + ' STOPS a running turn instead of returning silently',
    /if \(chatBusy\) await stopTurnNow\(/.test(src) && !/if \(chatBusy\) return;/.test(src));
}
const mode = grab('setMode');
check('a lane switch stops the running turn FIRST, before chatMode flips',
  /if \(chatBusy && m !== prev\) await stopTurnNow\('lane switch'\)/.test(mode)
  && mode.indexOf("await stopTurnNow('lane switch')") < mode.indexOf('chatMode = m;'));
check('setMode is async so the stop can be awaited', /async function setMode\(m\)/.test(html));

/* ── 5. the send path owns + releases the turn ───────────────────────────── */
/* sendChat is sliced by markers rather than brace-matched: its comments contain
 * apostrophes, which the (deliberately simple) extractor above reads as string
 * delimiters. The slice runs from the function header to the next top-level
 * block comment, i.e. exactly the function body. */
const sendAt = html.indexOf('async function sendChat()');
if (sendAt < 0) throw new Error('sendChat not found in the panel');
const sendEnd = html.indexOf('/* ====', sendAt);
const send = html.slice(sendAt, sendEnd > 0 ? sendEnd : sendAt + 20000);
check('sendChat creates the turn (lane + AbortController + stage) before fetching',
  /const turn = \{lane: chatMode, stage: 'connecting', ctl: new AbortController\(\)/.test(send));
check('the fetch carries the abort signal — without it nothing can cancel a read',
  /signal: turn\.ctl\.signal/.test(send));
check('the finally clears the timer AND the turn handle (a stale curTurn would '
    + 'let the next Stop abort nothing)',
  /finally \{\s*clearTimeout\(turn\.timer\);\s*if \(curTurn === turn\) curTurn = null;/.test(send));
check('the finally still clears chatBusy and restores the button (unchanged)',
  /chatBusy = false;[\s\S]{0,400}sb\.textContent = 'Send'/.test(send));
check('a deliberate abort is not reported as a stream error',
  /if \(turn\.ended\) body\.textContent \+= '\\n· interrupted';/.test(send));
check('conv-mode turn hooks are still inside the send path\'s try/finally, so a '
    + 'force-ended turn still resumes the conversation',
  /convEvent\('turn_start'\)/.test(send) && /convTurnEnd\(holder\)/.test(send));

/* ── 6. the panel watchdog + the heartbeat it depends on ─────────────────── */
const arm = grab('turnArm');
check('the watchdog is re-armed on EVERY received chunk',
  /if \(turn\.lane === 'hermes'\) turnArm\(TURN_STALL_MS\);/.test(send));
check('the first-byte watchdog is armed at send time',
  /if \(turn\.lane === 'hermes'\) turnArm\(TURN_FIRSTBYTE_MS\);/.test(send));
check('the watchdog is HERMES-lane only (the other lanes have no heartbeat and a '
    + 'long local prefill emits nothing — arming there would kill healthy turns)',
  /HERMES lane only/.test(arm) || /hermes/i.test(arm));
check('a watchdog armed on an already-ended (or completed) turn is a no-op',
  /if \(!curTurn \|\| curTurn\.ended \|\| curTurn\.done\) return;/.test(arm));

const FIRST = constant('TURN_FIRSTBYTE_MS'), STALL = constant('TURN_STALL_MS'),
      FORCE = constant('TURN_FORCE_MS');
check('the first-byte watchdog is LATER than the bridge\'s own 60s first-event '
    + 'error, so the bridge\'s clearer message wins when the relay is alive',
  FIRST > 60000);
check('the stall watchdog is longer than 3 bridge heartbeats (~20s each), so a '
    + 'single slow tick can never fire it', STALL > 60000);
check('the Stop force-end grace matches the relay\'s own 3s fallback', FORCE === 3000);

check('the bridge relay emits a heartbeat on every waiting tick',
  /yield 'data: \{"type":"hermes_ping"\}/.test(appy));
check('…emitted BEFORE the branch that suppresses everything while an approval '
    + 'card is pending (a card can legitimately wait minutes)',
  appy.indexOf('"type":"hermes_ping"') < appy.indexOf('if approval_pending:'));
check('the panel consumes the heartbeat silently — it must not flood the inspect '
    + 'log', /if \(j\.type === 'hermes_ping'\) continue;/.test(html));

/* ── 7. things this slice must NOT have changed ──────────────────────────── */
check('the bridge still keeps its 600s hard guard', /silent >= 600\.0/.test(appy));
check('the bridge still keeps its 60s first-event guard',
  /not got_any and silent >= 60\.0/.test(appy));
check('the active_list probe still fails SAFE (a probe failure never kills a live '
    + 'stream)', /except Exception:\s*\n\s*return True/.test(appy));
check('no new CSS rule was needed for the forced-interrupt stamp (it reuses the '
    + 'statusline)', /chatStatus\(t\.holder, '✓', 'interrupted \(forced\)/.test(force));

console.log('');
console.log((fails.length ? 'FAIL' : 'OK') + ' — ' + fails.length + ' failure(s)');
fails.forEach(f => console.log('  - ' + f));
process.exit(fails.length ? 1 : 0);
