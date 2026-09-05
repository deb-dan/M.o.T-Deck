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
 * 2026-08-21 (chat-split PHASE 0): the per-column globals this file pinned by
 * name — chatBusy / chatMode / chatSid / hermesSid / hermesStoredSid / curTurn —
 * now live on the ONE `chatPane` state object. Every assertion below was
 * re-expressed against `chatPane.X`; the FACTS pinned are identical. Three
 * ordering checks were also HARDENED: they compared indexOf() results, so a
 * renamed needle silently became `-1 < positive` = vacuously true. `before()`
 * now demands both needles exist. §8 adds the new invariants: the pane's key set,
 * a negative that none of the old bare globals came back, and I4 — an approval /
 * ask card answers the session it was RENDERED for, never the pane's current one.
 *
 * Run: node bridge/tests/test_turn_lifecycle.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const turnStream = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'turn-stream.js'), 'utf8');
// U31 extracted the durable turn transport/lifecycle helpers to the local asset;
// test the served pair so moving a helper cannot turn its old assertion vacuous.
const panelCode = html + '\n' + turnStream;
// ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28):
// bridge/app.py is a facade over bridge/core/*.py + bridge/routers/*.py, so the
// cross-file pins below read _appsrc.js's assembled view of the whole app layer.
const appy = require('./_appsrc.js').appSource();

let fails = [];
function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + name);
  if (!cond) fails.push(name);
}

/* LATENT DEFECT FIXED 2026-08-21: the old extractor treated an apostrophe in a
 * COMMENT as a string delimiter, so `grab('approveHermes')` — whose comments say
 * "the card raced upstream's own approval timeout" — ran past the closing brace
 * and returned 33 kB of unrelated panel. Every assertion over it was therefore
 * being made against the wrong text (and a NEGATIVE assertion over it would have
 * failed for the wrong reason, which is exactly what surfaced this). Same
 * comment/template-aware walker test_hermes_toolsets.js already carries. */
function grab(name) {
  const at = panelCode.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  const stack = [];        // {t:'sq'|'dq'|'tpl'} or {t:'itp', d:<depth at ${>}
  let depth = 0, prev = '';
  for (let j = panelCode.indexOf('{', at); j < panelCode.length; j++) {
    const c = panelCode[j], top = stack[stack.length - 1], bs = prev === '\\';
    const t = top && top.t;
    if (t === 'sq' || t === 'dq') {
      if (!bs && c === (t === 'sq' ? "'" : '"')) stack.pop();
    } else if (t === 'tpl') {
      if (!bs && c === '`') stack.pop();
      else if (!bs && c === '$' && html[j + 1] === '{') { stack.push({t: 'itp', d: depth}); j++; }
    } else {
      if (c === '/' && panelCode[j + 1] === '/') { j = panelCode.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && panelCode[j + 1] === '*') { j = panelCode.indexOf('*/', j) + 1; if (j < 1) break; prev = '/'; continue; }
      if (c === "'") stack.push({t: 'sq'});
      else if (c === '"') stack.push({t: 'dq'});
      else if (c === '`') stack.push({t: 'tpl'});
      else if (c === '{') depth++;
      else if (c === '}') {
        if (t === 'itp' && depth === top.d) stack.pop();
        else if (--depth === 0) return panelCode.slice(at, j + 1);
      }
    }
    prev = bs ? '' : c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

/* Ordering assertions used to be raw indexOf comparisons, which pass VACUOUSLY
 * when a needle is missing (-1 < anything). Both needles must exist. */
function before(hay, a, b, label){
  const i = hay.indexOf(a), j = hay.indexOf(b);
  check(label, i >= 0 && j >= 0 && i < j);
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
  /t\.done/.test(force) && /turn\.done = true;[\s\S]{0,80}turnStage\(state \|\| 'done'\)/.test(turnStream));
check('forceEndTurn ABORTS the fetch — that is what unblocks reader.read() and '
    + 'lets sendChat\'s finally do the real cleanup',
  /t\.ctl\.abort\(\)/.test(force));
check('forceEndTurn disarms its own watchdog', /clearTimeout\(t\.timer\)/.test(force));
check('forceEndTurn schedules the HARD release, so even a reader that ignores the '
    + 'abort cannot hold the composer', /setTimeout\(\(\) => turnHardRelease\(t\), \d+\)/.test(force));
check('forceEndTurn stamps the turn "interrupted (forced)" with the stage',
  /interrupted \(forced\)/.test(force));

const hard = grab('turnHardRelease');
// UPDATED HONESTLY 2026-08-20 (studio chrome): the Send button now carries BOTH an
// icon and a text child, so every label site funnels through sendPaint() instead of
// writing textContent wholesale (which would have deleted the icon). The invariant is
// unchanged — the composer is released with the resting Send label.
check('turnHardRelease clears the pane\'s busy flag and restores the Send button',
  /chatPane\.busy = false;/.test(hard) && /sendPaint\('Send'\)/.test(hard));
check('turnHardRelease only ever releases the turn it was armed for (a late timer '
    + 'must not kill the NEXT turn)', /if \(chatPane\.curTurn !== turn\) return;/.test(hard));

/* ── 2. the diagnostic (which stage did it die in?) ──────────────────────── */
check('the force-end names the stage on the console AND in the activity feed',
  /console\.warn\('\[turn\] force-end/.test(force) && /feed\('chat', 'turn force-ended at/.test(force));
check('stages are recorded through ONE setter, so a stage cannot be written to a '
    + 'turn that already ended',
  /function turnStage\(s\)\{ if \(chatPane\.curTurn && !chatPane\.curTurn\.ended\) chatPane\.curTurn\.stage = s; \}/.test(html));
check('every phase of a turn labels itself',
  ['connecting', 'waiting for the first frame', 'thinking', 'answering',
   'running a tool', 'awaiting approval', 'prefill (bridge says hermes is working)']
    .every(s => panelCode.indexOf(s) > 0));

/* ── 3. Stop always wins ─────────────────────────────────────────────────── */
const stop = grab('hermesStop');
check('Stop arms a client-side force-end BEFORE it touches the network',
  /t\.stopArmed = true;[\s\S]{0,200}setTimeout\(\(\) => forceEndTurn\([\s\S]{0,120}TURN_FORCE_MS\)/.test(stop));
before(stop, 't.stopArmed = true;',
  'if (!chatPane.hermesSid || chatPane.hermesStopping) return;',
  'the force-end is armed even with NO session id yet — the pre-first-event '
  + 'phase used to make Stop a silent no-op');
check('Stop still issues the gateway interrupt when there IS a sid',
  /fetch\('\/api\/hermes\/stop'/.test(stop));
check('the busy branch routes on the TURN\'s lane, not the current chip — so a '
    + 'lane switch can never make Stop unreachable',
  /if \(chatPane\.mode === 'hermes' \|\| \(chatPane\.curTurn && chatPane\.curTurn\.lane === 'hermes'\)\) hermesStop\('panel stop'\)/.test(html));

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
  check(label + ' DETACHES a durable running turn instead of returning silently',
    /if \(chatPane\.busy\) await (?:stopTurnNow|detachTurnNow)\(/.test(src)
    && !/^\s*if \(chatPane\.busy\) return;/m.test(src));
}

/* ── 4b. …but an INCIDENTAL re-open must never kill a healthy turn ────────
 * REGRESSION (2026-08-14b, Debi: a slow-but-healthy Hermes turn came back as
 * Hermes's own "Operation interrupted."). §4 above turned four no-ops into
 * turn-killers, and three of them are reachable with no intent to stop
 * anything: initChat() re-opens the CURRENT session on every entry to the Chat
 * view (the Hermes lane binds no Odysseus session, so that path runs), the
 * rail's ACTIVE row is the easiest thing to click while waiting, and the lane
 * guards ran AFTER the stop, so a call that was about to return still fired
 * session.interrupt. These four checks are the fence. */
const selH = grab('selectHermesSession'), selO = grab('selectSession');
check('re-opening the Hermes session you are ALREADY in leaves a running turn alone',
  /if \(chatPane\.busy && storedId && storedId === chatPane\.hermesStoredSid\) return;/.test(selH));
check('re-opening the Odysseus session you are ALREADY in leaves a running turn alone',
  /if \(chatPane\.busy && sid && sid === chatPane\.sid\) return;/.test(selO));
before(selH, "if (chatPane.mode !== 'hermes') return;", 'await stopTurnNow(',
  'the Hermes lane guard runs BEFORE the stop — a cross-lane call that does '
  + 'nothing must not interrupt the live turn');
before(selO, "if (chatPane.mode === 'hermes') return;", 'await detachTurnNow(',
  'the Odysseus lane guard runs BEFORE the stop (same rule, other lane)');
const initc = grab('initChat');
check('re-entering the Chat view NEVER touches a live turn (initChat is the path '
    + 'that made simply leaving and coming back interrupt a Hermes turn)',
  /if \(chatPane\.busy\) return;/.test(initc)
  && initc.indexOf('if (chatPane.busy) return;') < initc.indexOf('selectHermesSession('));
before(initc, 'if (chatPane.busy) return;', 'loadSessions(',
  '…and it is the FIRST thing initChat does, before any session load');
const mode = grab('setMode');
check('a lane switch detaches the running durable turn FIRST, before the lane flips',
  /if \(chatPane\.busy && m !== prev\) await detachTurnNow\('lane switch'\)/.test(mode));
before(mode, "await detachTurnNow('lane switch')", 'chatPane.mode = m;',
  '…and detach is ordered before the write');
check('setMode is async so the stop can be awaited', /async function setMode\(m\)/.test(html));
check('every Chat↔Agent lane change re-selects the shared session so returning to '
    + 'the producer lane runs active-turn reconciliation instead of retaining stale DOM',
  /else \{[\s\S]*loadSessions\(\);[\s\S]*if \(chatPane\.sid\) await selectSession\(chatPane\.sid\);/.test(mode));

/* ── 5. the send path owns + releases the turn ───────────────────────────── */
/* sendChat is sliced by markers rather than brace-matched: its comments contain
 * apostrophes, which the (deliberately simple) extractor above reads as string
 * delimiters. The slice runs from the function header to the next top-level
 * block comment, i.e. exactly the function body. */
const sendAt = html.indexOf('async function sendChat()');
if (sendAt < 0) throw new Error('sendChat not found in the panel');
const sendEnd = html.indexOf('/* ====', sendAt);
const send = html.slice(sendAt, sendEnd > 0 ? sendEnd : sendAt + 20000);
check('the extracted stream renderer is a fail-closed dependency for EVERY lane',
  /const streamReady = streamApi && typeof streamApi\.consume === 'function'/.test(send)
  && /chatPane\.mode === 'hermes'[\s\S]{0,180}typeof streamApi\.requestId === 'function'/.test(send)
  && /typeof streamApi\.prepareHermesSession === 'function'/.test(send)
  && /typeof streamApi\.postHermes === 'function'/.test(send)
  && /typeof streamApi\.create === 'function'/.test(send)
  && /typeof streamApi\.remember === 'function'/.test(send));
check('a missing renderer says the prompt was not sent and returns before mutating it',
  /message not sent — the Chat renderer did not load; reload M\.O\.T and try again/.test(send));
before(send, 'if (!streamReady){', "inp.value = '';",
  '…the renderer guard runs before the composer is cleared');
before(send, 'if (!streamReady){', "const url = chatPane.mode === 'hermes'",
  '…and before any producer route is selected or contacted');
check('after that one guard, the send path uses the captured API consistently',
  /streamApi\.create\(turn\.lane, reqBody\)/.test(send)
  && /streamApi\.remember\(turn\)/.test(send)
  && /streamApi\.consume\(resp, \{turn, holder, body, think\}\)/.test(send));
check('sendChat creates the turn (lane + AbortController + stage) before fetching',
  /const turn = \{lane: chatPane\.mode, session: chatPane\.sid, stage: 'connecting', ctl: new AbortController\(\)/.test(send));
check('the fetch carries the abort signal — without it nothing can cancel a read',
  /\{signal:\s*turn\.ctl\.signal\}/.test(send)
  && /postHermes\(reqBody, turn\.ctl\.signal\)/.test(send));
check('the finally clears the timer AND the turn handle (a stale curTurn would '
    + 'let the next Stop abort nothing)',
  /finally \{\s*clearTimeout\(turn\.timer\);\s*const ownsPane = chatPane\.curTurn === turn;\s*if \(ownsPane\) chatPane\.curTurn = null;/.test(send));
check('the finally still clears the busy flag and restores the button (unchanged)',
  /chatPane\.busy = false;[\s\S]{0,400}sendPaint\('Send'\)/.test(send));
check('a deliberate abort is not reported as a stream error',
  /if \(turn\.detached\)[\s\S]{0,160}else if \(turn\.ended\) body\.textContent \+= '\\n· interrupted';/.test(send));
check('conv-mode turn hooks are still inside the send path\'s try/finally, so a '
    + 'force-ended turn still resumes the conversation',
  /convEvent\('turn_start'\)/.test(send) && /convTurnEnd\(holder\)/.test(send));
check('a pre-acceptance Chat/Agent refusal restores the exact prompt instead of '
    + 'clearing it under a safe same-session conflict',
  /turn\.lane !== 'hermes' && !turn\.id/.test(send)
  && /inp\.value = text \+ \(inp\.value \? '\\n' \+ inp\.value : ''\)/.test(send)
  && /\[not sent: /.test(send));
check('a rejected local turn is never stamped as if it reached durable history',
  /!turn\.detached && \(turn\.lane === 'hermes' \|\| turn\.id\)/.test(send));

/* ── 6. the panel watchdog + the heartbeat it depends on ─────────────────── */
const arm = grab('turnArm');
check('the watchdog is re-armed on EVERY received chunk',
  /if \(ctx\.turn\.lane === 'hermes'\) turnArm\(TURN_STALL_MS, 'stall'\);/.test(turnStream));
check('the first-byte watchdog is armed at send time',
  /if \(turn\.lane === 'hermes'\) turnArm\(TURN_FIRSTBYTE_MS, 'first-byte'\);/.test(send));
const rawArmAt = turnStream.indexOf("turnArm(TURN_STALL_MS, 'stall')");
const decodeAt = turnStream.indexOf('buffer += decoder.decode');
const dispatchAt = turnStream.indexOf('if (consumeFrame(frame))');
check('the re-arm happens on the RAW chunk, before decoding or dispatch — a heartbeat '
    + 'that failed to parse must still prove the relay is alive',
  rawArmAt >= 0 && rawArmAt < decodeAt && decodeAt < dispatchAt);
check('every chunk stamps lastByte, so the diagnostic can report real silence',
  /ctx\.turn\.lastByte = Date\.now\(\);/.test(turnStream));
check('a watchdog that fires SAYS which timer it was and how long the relay was '
    + 'actually silent (console + INSPECT), so the next report is self-explanatory',
  /watchdog ' \+ \(t\.timerLabel/.test(arm)
  && /since the last chunk/.test(arm)
  && /chatInspect\(t\.holder, \{type: 'turn_watchdog'/.test(arm));
check('a watchdog belonging to a superseded turn can never fire late',
  /if \(chatPane\.curTurn !== t\) return;/.test(arm));
check('the watchdog is HERMES-lane only (the other lanes have no heartbeat and a '
    + 'long local prefill emits nothing — arming there would kill healthy turns)',
  /HERMES lane only/.test(arm) || /hermes/i.test(arm));
check('a watchdog armed on an already-ended (or completed) turn is a no-op',
  /if \(!chatPane\.curTurn \|\| chatPane\.curTurn\.ended \|\| chatPane\.curTurn\.done\) return;/.test(arm));

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
    + 'log', /if \(j\.type === 'hermes_ping'\) return;/.test(turnStream));

/* ── 7. things this slice must NOT have changed ──────────────────────────── */
check('the bridge still keeps its 600s hard guard', /silent >= 600\.0/.test(appy));
check('the bridge still keeps its 60s first-event guard',
  /not got_any and silent >= 60\.0/.test(appy));
check('the active_list probe still fails SAFE (a probe failure never kills a live '
    + 'stream)', /except Exception:\s*\n\s*return True/.test(appy));
check('no new CSS rule was needed for the forced-interrupt stamp (it reuses the '
    + 'statusline)', /chatStatus\(t\.holder, '✓', 'interrupted \(forced\)/.test(force));

/* ── 8. CHAT-SPLIT PHASE 0 — ONE pane object, and cards that answer THEIR own
 *     session (docs/handoff/DRAFT-CHAT-SPLIT-ISOLATION.md §1.1, §4.3 I4, §6.1).
 *
 * Nothing here makes a second column exist. What it pins is that a second column
 * would be POSSIBLE: every piece of per-column state is on one object, none of it
 * survives as a bare module global, and the one coupling with a security
 * consequence — an approval card posting whatever session the global last pointed
 * at — is fixed for real rather than deferred. */

/* The pane object exists, is a const (a second pane is a second object, never a
 * reassignment of this one), and is declared exactly once. */
check('there is exactly ONE chatPane declaration and it is a const',
  (html.match(/^const chatPane = \{/mg) || []).length === 1
  && !/\blet chatPane\b/.test(html));

/* The key set. A field missing here means a second column would silently share
 * it with the first — which is the entire failure mode this phase exists to make
 * impossible. Read out of the DECLARATION, so adding a field elsewhere at runtime
 * (which would be invisible to a reader of the object) does not satisfy it. */
const paneAt = html.indexOf('const chatPane = {');
const paneDecl = html.slice(paneAt, html.indexOf('\n};', paneAt));
for (const k of ['id', 'sid', 'mode', 'busy', 'model', 'stampModel', 'hermesSid',
                 'hermesStoredSid', 'hermesStopping', 'sessions', 'hermesSessions',
                 'reqSeq', 'curTurn', 'attachedImage', 'pendingAttachDrop',
                 'delArm', 'msgDelArm']) {
  check('chatPane owns per-column state: ' + k,
    new RegExp('^\\s*' + k + ':', 'm').test(paneDecl));
}

/* U31 live journey, 2026-09-05: the producer survived a direct-Chat reload, but
 * the document reset its chip to Agent and therefore never reconciled the active
 * Chat turn until the user changed lanes manually.  Lane state is a whitelisted
 * UI preference (no prompt/event content) and must be painted before first use. */
const storedMode = grab('storedChatMode'), setMode = grab('setMode');
check('reload restores only one of the three real chat lanes',
  /localStorage\.getItem\('harness-chat-mode'\)/.test(storedMode)
  && /\['agent', 'chat', 'hermes'\]\.includes\(value\)/.test(storedMode)
  && /\? value : 'agent'/.test(storedMode));
check('the pane starts from the validated persisted lane',
  /mode: storedChatMode\(\)/.test(paneDecl));
check('every lane switch persists the selected lane without making storage fatal',
  /try \{ localStorage\.setItem\('harness-chat-mode', m\); \} catch \(_\) \{\}/.test(setMode));
check('boot paints the restored lane before the Chat view is first opened',
  /setMode\(chatPane\.mode\);[^\n]*U31/.test(html));

/* NEGATIVE — no orphan remnants. The draft forbids compatibility shims by name:
 * "a shim is exactly how a missed call site stays silently wrong". A surviving
 * `let chatBusy` (aliased or not) would let a rethread miss go unnoticed. */
for (const g of ['chatSid', 'chatMode', 'chatBusy', 'chatModel', 'hermesSid',
                 'hermesStoredSid', 'hermesStopping', 'hermesSessions',
                 'chatSessions', 'sessionsReqSeq', 'curTurn', 'attachedImage',
                 'pendingAttachDrop', '_delArm', '_msgDelArm',
                 '_stampSessionModel']) {
  check('no bare global remnant of ' + g + ' (no shim, no alias)',
    !new RegExp('^\\s*(let|var|const)\\s+' + g + '\\b\\s*=', 'm').test(html));
}

/* Things that must NOT have moved onto the pane: draft §3 singletons. One mic,
 * one clip, one conv machine — enforced by there being one of each in the
 * document, which a per-pane copy would destroy. */
for (const g of ['autoVad', 'currentAudio', 'talkRec', 'convSt', 'liveVision']) {
  check(g + ' stays a document singleton (draft §3), NOT pane state',
    new RegExp('^\\s*let\\s+' + g + '\\b', 'm').test(html)
    && !new RegExp('^\\s*' + g + ':', 'm').test(paneDecl));
}

/* I4 — an approval / ask card answers ITS OWN session.
 * Approvals carry no request id on the wire (the gateway resolves them FIFO per
 * session), so session_id IS the address. Reading the pane's CURRENT hermesSid at
 * CLICK time meant a session switch — or, later, a second column — while a card
 * sat open could send "Always" for a dangerous command to the wrong session, and
 * the panel would stamp `✓ approved`. */
const approval = grab('chatApproval'), ask = grab('chatAsk');
check('the approval card captures its session at RENDER time',
  /function chatApproval\(holder, req, sid\)/.test(approval)
  && /card\._sid = String\(sid \|\| ''\);/.test(approval));
check('the ask card captures its session at RENDER time',
  /function chatAsk\(holder, req, sid\)/.test(ask)
  && /card\._sid = String\(sid \|\| ''\);/.test(ask));

const approve = grab('approveHermes'), answer = grab('answerHermes');
check('approveHermes posts the CARD\'s session id',
  /session_id: card\._sid/.test(approve));
check('answerHermes posts the CARD\'s session id',
  /session_id: card\._sid/.test(answer));
/* The teeth: not "it uses the card" but "it CANNOT reach the pane". A switch
 * between render and click is then structurally unable to retarget the answer. */
check('…and NEITHER handler can read the pane\'s current session (this is the fix)',
  approve.indexOf('chatPane') < 0 && answer.indexOf('chatPane') < 0);

/* Where the captured sid comes from: the TURN, which is the only thing that knows
 * which gateway session this stream is on. Seeded from the pane at turn creation
 * (a continuation turn) and overwritten by the bridge's hermes_session frame (a
 * new or stale-sid-retried one), which the bridge always yields BEFORE
 * prompt.submit — so a card can never be rendered without a session. */
check('the turn record carries the gateway session it is streaming on',
  /holder: holder, hermesSid: chatPane\.hermesSid \|\| '',/.test(send));
check('a hermes_session frame updates the TURN as well as the pane (a stale-sid '
    + 'retry re-mints mid-stream, and the card must follow the new session)',
  /chatPane\.hermesSid = j\.id; turn\.hermesSid = j\.id;/.test(turnStream));
check('both cards are rendered with the TURN\'s session, not the pane\'s',
  /chatApproval\(holder, j\.request \|\| \{\}, turn\.hermesSid\)/.test(turnStream)
  && /chatAsk\(holder, j\.request \|\| \{\}, turn\.hermesSid\)/.test(turnStream));
/* The scenario in one assertion: nothing between render and POST re-reads a
 * session id, so "switch sessions while a card is open, then answer it" lands on
 * the session the card was born in. */
check('SCENARIO — switch sessions with a card open, then answer: the card still '
    + 'addresses its ORIGINAL session (no session id is re-read at click time)',
  !/session_id: chatPane\.hermesSid/.test(approve + answer)
  && !/session_id: chatPane\.hermesSid/.test(approval + ask)
  && (html.match(/card\._sid/g) || []).length >= 4);

/* BE-01 (2026-08-28) — cross-reference pin. bridge/tests/test_chat_toolerr.js owns the
 * chip; this ONE line lives here because this file owns the stream renderer, and the
 * regression to guard against is somebody simplifying the tool_output branch back to a
 * single chatStatus() call while looking at the turn lifecycle rather than at the chip.
 * A failed tool must never be as invisible as it was in the 2026-08-27 incident. */
{
  const tob = turnStream.slice(turnStream.indexOf("j.type === 'tool_output'"),
                               turnStream.indexOf("j.type === 'web_sources'"));
  check('the tool_output branch still renders a failure '
        + '(BE-01 — the chip itself is owned by test_chat_toolerr.js)',
    tob.length > 100 && /if \(j\.is_error\)/.test(tob) && /chatToolErr\(/.test(tob));
}

/* The pane-scoped race token: two independent rail loaders must never invalidate
 * each other (draft §6 "honourable mentions"). */
check('the rail race token is PANE state, not a shared module counter',
  /^\s*reqSeq: 0,/m.test(paneDecl) && /\+\+chatPane\.reqSeq/.test(html));


console.log('');
console.log((fails.length ? 'FAIL' : 'OK') + ' — ' + fails.length + ' failure(s)');
fails.forEach(f => console.log('  - ' + f));
process.exit(fails.length ? 1 : 0);
