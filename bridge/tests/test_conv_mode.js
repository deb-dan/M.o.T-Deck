/* Panel-side unit test for CONVERSATION MODE — the speak ⇄ reply state machine.
 *
 * WHY this is the thing that gets table-tested: conversation mode is a LOOP with a
 * live microphone at one end and a loudspeaker at the other. If the gate that keeps
 * the mic deaf while the assistant talks is wrong in any single phase, MOT Deck
 * hears itself, transcribes itself, answers itself, and does that forever. That is
 * not a bug you can eyeball — so the machine is written PURE (a new state object per
 * event, no DOM, no audio, no fetch) and every transition is asserted here.
 *
 * Functions are pulled OUT of bridge/panel/index.html by name (same extraction
 * pattern as test_vad_segmenter.js / test_speak_text.js), so a rename or an edit
 * trips this test instead of letting the test drift from the shipped code:
 *
 *   convInit()                 the initial state
 *   convStep(st, ev, detail)   the transition table → { st, action }
 *   convGated(st)              the feedback-loop gate: is the VAD suspended?
 *   convLabel(st)              the chip's three visible states
 *
 * Run: node bridge/tests/test_conv_mode.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');

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
    if (inStr) {
      if (c === inStr && prev !== '\\') inStr = null;
    } else if (c === '"' || c === "'" || c === '`') {
      inStr = c;
    } else if (c === '{') {
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0) return html.slice(at, j + 1);
    }
    prev = c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

/* Constants are read OUT of the panel — a value changed there must change the
 * expectations here, not silently pass against a stale copy. */
function constant(name) {
  const m = new RegExp('const\\s+' + name + '\\s*=\\s*([0-9.]+)\\s*;').exec(html);
  if (!m) throw new Error('constant ' + name + ' not found in the panel');
  return Number(m[1]);
}
function strConstant(name) {
  const m = new RegExp("const\\s+" + name + "\\s*=\\s*'([^']*)'").exec(html);
  if (!m) throw new Error('constant ' + name + ' not found in the panel');
  return m[1];
}

const CONV_GRACE_MS   = constant('CONV_GRACE_MS');
const CONV_MAX_ERRORS = constant('CONV_MAX_ERRORS');
const CONV_LABEL      = strConstant('CONV_LABEL');

eval(grab('convInit'));
eval(grab('convStep'));
eval(grab('convGated'));
eval(grab('convLabel'));

/* Tiny driver: replay a list of events from a start state and return the trace. */
function run(st, events) {
  const trace = [];
  for (const e of events) {
    const ev = Array.isArray(e) ? e[0] : e;
    const detail = Array.isArray(e) ? e[1] : undefined;
    const r = convStep(st, ev, detail);
    st = r.st;
    trace.push({ phase: st.phase, action: r.action });
  }
  return { st, trace };
}
const START = () => convStep(convInit(), 'start').st;

/* ─────────────────────────── initial state ─────────────────────────── */

const init = convInit();
check('starts off', init.phase === 'off');
check('starts with no failures counted', init.sttErrors === 0 && init.ttsErrors === 0);
check('the initial state is GATED (nothing is listening before you press the chip)',
  convGated(init) === true);
check('convGated is total — a missing state is gated, not open',
  convGated(null) === true && convGated(undefined) === true);
check('convStep returns a NEW object (purity — never mutates its input)', (() => {
  const a = convInit();
  const b = convStep(a, 'start').st;
  return b !== a && a.phase === 'off';
})());
check('convStep never mutates the state it was given, even on a no-op', (() => {
  const a = START();
  const before = JSON.stringify(a);
  convStep(a, 'turn_end');
  return JSON.stringify(a) === before;
})());

/* ───────────────────────── the happy loop ──────────────────────────── */

check('start → listening', START().phase === 'listening');
check('LISTENING is the only ungated phase', convGated(START()) === false);

const loop = run(START(), [
  'utterance', ['transcript', 'what is the weather'], 'turn_end', 'speak_ok', 'grace_done'
]);
check('an utterance moves to thinking and asks for a transcription',
  loop.trace[0].phase === 'thinking' && loop.trace[0].action === 'transcribe');
check('a non-empty transcript SENDS it (this is what auto mode does not do)',
  loop.trace[1].phase === 'waiting' && loop.trace[1].action === 'send');
check('the turn ending asks for the reply to be spoken',
  loop.trace[2].phase === 'speaking' && loop.trace[2].action === 'speak');
check('playback ending starts the grace window, NOT listening directly',
  loop.trace[3].phase === 'grace' && loop.trace[3].action === 'grace');
check('the grace window expiring is what re-arms the mic',
  loop.trace[4].phase === 'listening' && loop.trace[4].action === null);
check('one full loop leaves both failure counters at zero',
  loop.st.sttErrors === 0 && loop.st.ttsErrors === 0);
check('the loop is repeatable (a second lap behaves identically)', (() => {
  const two = run(loop.st, ['utterance', ['transcript', 'again'], 'turn_end',
                            'speak_ok', 'grace_done']);
  return two.st.phase === 'listening'
    && two.trace.map(t => t.action).join(',') === 'transcribe,send,speak,grace,';
})());

/* ══════════ THE GATE — the invariant the whole feature rests on ══════════ */

check('GATE: thinking (an STT call in flight) is gated',
  convGated(run(START(), ['utterance']).st) === true);
check('GATE: waiting (the reply is streaming) is gated',
  convGated(run(START(), ['utterance', ['transcript', 'x']]).st) === true);
check('GATE: SPEAKING (the reply is playing out loud) is gated — the mic must '
    + 'never hear the assistant',
  convGated(run(START(), ['utterance', ['transcript', 'x'], 'turn_end']).st) === true);
check('GATE: the grace window after playback is STILL gated (a clip tail and the '
    + 'speaker decay would otherwise open an utterance made of our own voice)',
  convGated(run(START(), ['utterance', ['transcript', 'x'], 'turn_end', 'speak_ok']).st) === true);
check('GATE: off is gated', convGated(run(START(), ['stop']).st) === true);
check('GATE: exactly ONE phase in the whole machine is ungated', (() => {
  const phases = ['off', 'listening', 'thinking', 'waiting', 'speaking', 'grace'];
  return phases.filter(p => convGated({ phase: p }) === false).length === 1;
})());
check('GATE: an unknown/future phase is gated by default (fails closed)',
  convGated({ phase: 'some-phase-added-later' }) === true);
check('GATE: the grace window is a real, named, non-zero delay',
  CONV_GRACE_MS > 0 && CONV_GRACE_MS <= 2000);

/* ───────────────── empty and failed transcripts never send ───────────────── */

const empty = run(START(), ['utterance', 'transcript_empty']);
check('an EMPTY transcript never sends — it resumes listening',
  empty.trace[1].phase === 'listening' && empty.trace[1].action === null);
check('an empty transcript is not counted as a failure (the VAD gated in a noise; '
    + 'whisper honestly heard nothing)', empty.st.sttErrors === 0);
check('an empty transcript RESETS a partial failure streak', (() => {
  const s = run(START(), ['utterance', 'stt_fail', 'utterance', 'transcript_empty']);
  return s.st.sttErrors === 0;
})());
check('a failed transcription never sends',
  run(START(), ['utterance', 'stt_fail']).trace[1].action === null);
check('a single failed transcription resumes listening',
  run(START(), ['utterance', 'stt_fail']).st.phase === 'listening');

/* ───────────────────────── failure counters ───────────────────────── */

check('CONV_MAX_ERRORS consecutive STT failures stop the loop', (() => {
  let st = START(), last = null;
  for (let i = 0; i < CONV_MAX_ERRORS; i++) {
    const a = convStep(st, 'utterance'); st = a.st;
    const b = convStep(st, 'stt_fail', 'boom'); st = b.st; last = b;
  }
  return st.phase === 'off' && last.action === 'give_up';
})());
check('one fewer STT failure does NOT stop it', (() => {
  let st = START();
  for (let i = 0; i < CONV_MAX_ERRORS - 1; i++) {
    st = convStep(convStep(st, 'utterance').st, 'stt_fail').st;
  }
  return st.phase === 'listening' && st.sttErrors === CONV_MAX_ERRORS - 1;
})());
check('a SUCCESS between failures resets the STT streak (they must be consecutive)', (() => {
  let st = START();
  for (let i = 0; i < CONV_MAX_ERRORS - 1; i++) {
    st = convStep(convStep(st, 'utterance').st, 'stt_fail').st;
  }
  st = convStep(convStep(st, 'utterance').st, 'transcript', 'hello').st;
  return st.sttErrors === 0 && st.phase === 'waiting';
})());
check('CONV_MAX_ERRORS consecutive TTS failures stop the loop', (() => {
  let st = START(), last = null;
  for (let i = 0; i < CONV_MAX_ERRORS; i++) {
    if (st.phase === 'grace') st = convStep(st, 'grace_done').st;
    st = convStep(st, 'utterance').st;
    st = convStep(st, 'transcript', 'x').st;
    st = convStep(st, 'turn_end').st;
    last = convStep(st, 'speak_fail', 'engine died'); st = last.st;
  }
  return st.phase === 'off' && last.action === 'give_up';
})());
check('a SINGLE failed render skips speaking and resumes listening', (() => {
  const r = run(START(), ['utterance', ['transcript', 'x'], 'turn_end', 'speak_fail',
                          'grace_done']);
  return r.trace[3].action === 'grace' && r.st.phase === 'listening';
})());
check('a successful playback resets the TTS streak', (() => {
  let st = START();
  st = convStep(convStep(convStep(st, 'utterance').st, 'transcript', 'x').st, 'turn_end').st;
  st = convStep(st, 'speak_fail').st;
  st = convStep(st, 'grace_done').st;
  st = convStep(convStep(convStep(st, 'utterance').st, 'transcript', 'x').st, 'turn_end').st;
  st = convStep(st, 'speak_ok').st;
  return st.ttsErrors === 0;
})());
check('a reply with nothing speakable (pure code) is skipped, NOT counted a failure', (() => {
  const st = run(START(), ['utterance', ['transcript', 'x'], 'turn_end', 'speak_skip']).st;
  return st.phase === 'grace' && st.ttsErrors === 0;
})());
check('there is exactly ONE way back to listening — via grace', (() => {
  // every path that resumes the loop passes through the grace phase
  const paths = [['speak_ok'], ['speak_fail'], ['speak_skip']];
  return paths.every(p => {
    let st = START();
    st = convStep(convStep(convStep(st, 'utterance').st, 'transcript', 'x').st, 'turn_end').st;
    st = convStep(st, p[0]).st;
    return st.phase === 'grace';
  });
})());
check('a failed SEND stops the loop rather than listening into a dead turn', (() => {
  const r = run(START(), ['utterance', ['transcript', 'x'], ['send_fail', 'busy']]);
  return r.st.phase === 'off' && r.trace[2].action === 'give_up';
})());
check('a give-up carries the reason so the chip can say what broke',
  run(START(), ['utterance', ['transcript', 'x'], ['send_fail', 'busy']]).st.reason === 'busy');

/* ─────────────── manual typing mid-conversation ─────────────── */

const typed = run(START(), ['turn_start', 'turn_end', 'speak_ok', 'grace_done']);
check('a hand-typed message mid-conversation gates the mic like any turn',
  typed.trace[0].phase === 'waiting' && convGated({ phase: typed.trace[0].phase }));
check('a hand-typed message still gets its reply spoken',
  typed.trace[1].action === 'speak');
check('…and listening resumes after it', typed.st.phase === 'listening');
check('turn_start while already waiting is a no-op (our OWN send fires it too)', (() => {
  const st = run(START(), ['utterance', ['transcript', 'x']]).st;
  const r = convStep(st, 'turn_start');
  return r.st.phase === 'waiting' && r.action === null;
})());

/* ───────────────────── stop / off is absorbing ───────────────────── */

const EVENTS = ['utterance', 'transcript', 'transcript_empty', 'stt_fail', 'turn_start',
                'send_fail', 'turn_end', 'speak_ok', 'speak_skip', 'speak_fail',
                'grace_done'];
check('stop from ANY phase goes off', (() => {
  const seeds = [[], ['utterance'], ['utterance', ['transcript', 'x']],
                 ['utterance', ['transcript', 'x'], 'turn_end'],
                 ['utterance', ['transcript', 'x'], 'turn_end', 'speak_ok']];
  return seeds.every(s => convStep(run(START(), s).st, 'stop').st.phase === 'off');
})());
check('off ABSORBS every event but start — a late callback from a torn-down session '
    + '(a clip finishing after stopConv) can never restart the loop',
  EVENTS.every(ev => {
    const r = convStep(convInit(), ev);
    return r.st.phase === 'off' && r.action === null;
  }));
check('off + start restarts cleanly with the counters cleared', (() => {
  let st = START();
  for (let i = 0; i < CONV_MAX_ERRORS; i++) {
    st = convStep(convStep(st, 'utterance').st, 'stt_fail').st;
  }
  const again = convStep(st, 'start').st;
  return again.phase === 'listening' && again.sttErrors === 0 && again.ttsErrors === 0;
})());

/* ─────────────── totality: no event in any phase can throw ─────────────── */

check('every event in every phase is total (no throw, always a valid phase)', (() => {
  const phases = ['off', 'listening', 'thinking', 'waiting', 'speaking', 'grace'];
  const valid = new Set(phases);
  for (const p of phases) {
    for (const ev of EVENTS.concat(['start', 'stop', 'nonsense', '', null, undefined])) {
      let r;
      try { r = convStep({ phase: p, sttErrors: 0, ttsErrors: 0, reason: '' }, ev); }
      catch (e) { return false; }
      if (!r || !valid.has(r.st.phase)) return false;
    }
  }
  return true;
})());
check('an out-of-order event is ignored rather than skipping a phase', (() => {
  // turn_end while LISTENING must not jump straight to speaking
  const r = convStep(START(), 'turn_end');
  return r.st.phase === 'listening' && r.action === null;
})());
check('a transcript arriving outside thinking never sends',
  convStep(START(), 'transcript', 'x').action !== 'send');
check('speak_ok outside speaking never opens a grace window',
  convStep(START(), 'speak_ok').action !== 'grace');

/* ───────────────────────── the visible label ───────────────────────── */

check('off shows the plain chip label', convLabel(convInit()) === CONV_LABEL);
check('listening reads "listening"', convLabel({ phase: 'listening' }) === 'listening');
check('thinking and waiting both read "…"',
  convLabel({ phase: 'thinking' }) === '…' && convLabel({ phase: 'waiting' }) === '…');
check('speaking and its grace tail both read "speaking"',
  convLabel({ phase: 'speaking' }) === 'speaking' && convLabel({ phase: 'grace' }) === 'speaking');
check('convLabel is total', convLabel(null) === CONV_LABEL && convLabel({}) === CONV_LABEL);

/* ══════════════════════ WIRING (read off the panel) ══════════════════════ */

check('the chip needs BOTH an STT and a TTS default (either alone is useless)',
  /function convAvail\(\)\s*{\s*return sttOn\(\) && voiceOn\(\);\s*}/.test(html));
check('…and the chip is hidden when it is not available',
  /function renderConvBtn\([\s\S]{0,300}?btn\.hidden = !avail/.test(html));
check('the conv chip is rendered AFTER the auto chip in the composer', (() => {
  const a = html.indexOf('id="chat-auto"'), c = html.indexOf('id="chat-conv"');
  return a > 0 && c > a;
})());
// ⚠️ BOTH FENCES MOVED, v1.5.26 — Debi replaced the separate auto / conv chips with ONE
// three-position audio switch inside the composer. The claims survive, on the new object:
check('the conv end shares ONE size grammar with the rest of the switch',
  /#chat-audiosw \.asw-zone \{[^}]*font:9\.5px var\(--mono\)/.test(html));
check('the conv end is the BOTTOM position of the switch, and the switch is a radiogroup',
  /id="chat-audiosw" role="radiogroup"/.test(html)
  && /id="chat-conv" role="radio"[\s\S]{0,40}aria-checked/.test(html)
  && /class="primary asw-zone asw-bot" id="chat-conv"/.test(html));
// The live state used to be a gold ● glyph beside the word. It is now the KNOB — its
// position plus its gold fill — which is a 58px signal instead of a 4px one, and the
// dot is hidden inside the switch because `● listening` does not fit a zone. Still no
// new colour: the real switch owns --gold and the pseudo paints currentColor so a live
// WebKit theme flip cannot strand the old token value (S24).
check('the live state is the knob: gold fill, driven by [data-pos], no new colour token',
  /#chat-audiosw::after \{[^}]*background:currentColor/.test(html)
  && /#chat-audiosw\[data-pos="auto"\],\s*\n?\s*#chat-audiosw\[data-pos="conv"\] \{ color:var\(--gold\); \}/.test(html)
  && /#chat-audiosw \.talk-dot \{ display:none; \}/.test(html));

check('there is exactly ONE conversation teardown path',
  (html.match(/function stopConv\(/g) || []).length === 1);
check('it releases the mic (through the single stopAuto teardown — the mic light '
    + 'must go out)', /function stopConv\([\s\S]{0,600}?stopAuto\(/.test(html));
check('it stops any playback too (the assistant must not keep talking)',
  /function stopConv\([\s\S]{0,600}?stopSpeaking\(\)/.test(html));
check('it clears the grace timer (nothing may re-arm a loop that is over)',
  /function stopConv\([\s\S]{0,300}?clearTimeout\(convGraceTimer\)/.test(html));
check('it moves the machine to off BEFORE tearing anything down, so the teardown\'s '
    + 'own callbacks are absorbed', (() => {
  const m = /function stopConv\(reason\)\{([\s\S]*?)\n}/.exec(html)[1];
  return m.indexOf("convStep(convSt, 'stop'") < m.indexOf('stopSpeaking()');
})());

check('leaving the Chat view stops it', html.indexOf("stopConv('left the Chat view')") >= 0);
check('a lane switch stops it', html.indexOf("stopConv('lane switch')") >= 0);
check('starting manual dictation stops it', html.indexOf("stopConv('manual dictation started')") >= 0);
check('starting auto dictation stops it', html.indexOf("stopConv('auto dictation started')") >= 0);
check('clearing a voice default stops it',
  html.indexOf("stopConv('a voice default was cleared')") >= 0);
check('starting conversation stops auto dictation (exclusive both ways)',
  /function startConv\([\s\S]{0,400}?stopAuto\('conversation mode started'\)/.test(html));
check('starting conversation stops manual dictation too',
  /function startConv\([\s\S]{0,400}?if \(talkRec\) stopTalk\(true\)/.test(html));
check('a capture that never came up leaves the machine OFF, not falsely listening '
    + 'through a microphone that does not exist',
  /await startAuto\('conv'\);[\s\S]{0,400}?if \(!convOn\(\)\) convSt = convStep\(convSt, 'stop'/.test(html));
check('the auto and conv chips can never both read as live (one shared session, '
    + 'so "on" always names WHICH)',
  /function autoOn\(\)\{ return !!autoVad && autoVad\.mode !== 'conv'; \}/.test(html)
  && /function convOn\(\)\{ return !!autoVad && autoVad\.mode === 'conv'; \}/.test(html));

check('the GATE is applied in the worklet frame handler — the block is dropped '
    + 'BEFORE it is buffered or measured',
  /function autoFrame\([\s\S]{0,900}?if \(a\.mode === 'conv' && convGated\(convSt\)\) return;/.test(html));
check('…and it is applied before the frame is pushed or stepped', (() => {
  const m = /function autoFrame\(msg\)\{([\s\S]*?)\n}/.exec(html)[1];
  return m.indexOf('convGated(convSt)') < m.indexOf('a.frames.push')
      && m.indexOf('convGated(convSt)') < m.indexOf('vadStep(');
})());
// UPDATED HONESTLY 2026-08-14: the re-arm still RESETS the segmenter — that half is
// what makes resuming mid-utterance from before the gate impossible, and it is
// unchanged. What it no longer does is throw away the learned NOISE FLOOR, which was
// costing a fresh ~600ms warm-up after every reply. vadRearm() is the reset-and-carry
// split; its own table lives in test_vad_segmenter.js.
check('the segmenter is RESET when the mic re-arms (it can never resume mid-utterance '
    + 'from before the gate) — via vadRearm, which carries the room\'s noise floor',
  /convSt\.phase === 'listening'\)\{\s*autoVad\.st = vadRearm\(autoVad\.st\)/.test(html)
  && /function vadRearm\(st\)\{[\s\S]{0,400}?noise: st\.noise, thr: st\.thr/.test(html));
check('the frame buffer is still cleared with it (a carried FLOOR is fine, carried '
    + 'AUDIO would be the assistant\'s own voice)',
  /autoVad\.st = vadRearm\(autoVad\.st\);\s*autoVad\.frames = \[\]; autoVad\.base = 0;/
    .test(html));
check('the queue is dropped when a turn starts (an utterance captured a moment '
    + 'before the gate closed belongs to the turn in flight)',
  /convSt\.phase === 'waiting' \|\| convSt\.phase === 'speaking'\)\) autoVad\.queue = \[\]/.test(html));

check('a turn STARTING gates the mic (a hand-typed message counts as a turn)',
  /if \(typeof convOn === 'function' && convOn\(\)\) convEvent\('turn_start'\)/.test(html));
check('a turn ENDING is hooked in sendChat\'s finally — so a user-clicked Stop '
    + 'still resumes the conversation',
  /if \(!turn\.detached && typeof convOn === 'function' && convOn\(\)\) convTurnEnd\(holder\)/.test(html));
check('the reply is spoken through the EXISTING ▶ speak path (same endpoint, same '
    + 'replay cache, same speakText stripping)',
  /function convSpeak\([\s\S]{0,700}?msgSpeak\(wrap, btn, \(\) => convEvent\('speak_ok'\)\)/.test(html));
check('playback ending re-arms the mic through ONE funnel (stopSpeaking), so a '
    + 'natural end, an error and a manual ■ stop all resume the same way',
  /if \(c\.onDone\)\{ try \{ c\.onDone\(\); \}/.test(require('./_panel_source').extractFunction(html, 'stopSpeaking')));
check('msgSpeak reports whether playback actually STARTED, so a failed render is '
    + 'counted rather than hanging the loop forever',
  /msgSpeak\(wrap, btn, onDone\)\{/.test(html)
  && /\.then\(ok => \{\s*if \(!ok\) convEvent\('speak_fail'/.test(html));
check('the transcript is SENT, not just appended (that is the whole difference from '
    + 'auto mode)', /function convSend\([\s\S]{0,900}?sendChat\(\)/.test(html));
check('a half-typed message is kept in front of the transcript, never thrown away',
  /function convSend\([\s\S]{0,900}?box\.value = cur \? \(cur \+ ' ' \+ t\) : t/.test(html));
check('conversation never sends an empty transcript',
  /function convSend\([\s\S]{0,400}?if \(!box \|\| !t\)\{ convEvent\('send_fail'/.test(html));
check('every conv tunable is a named module-level constant',
  ['CONV_GRACE_MS', 'CONV_MAX_ERRORS', 'CONV_LABEL', 'CONV_TITLE']
    .every(n => new RegExp('const ' + n + ' =').test(html)));
check('the state lives in ONE named object, not scattered flags',
  /let convSt = convInit\(\);/.test(html));
check('barge-in being out of scope is recorded in the code, not just the handoff',
  /BARGE-IN/.test(html));

/* ── the small in-slice fix: the clip note must not claim wav-only ── */
check('the clip-library note names every supported suffix (REF_AUDIO_SUFFIXES), '
    + 'not just wav',
  /wav \/ mp3 \/ flac \/ m4a/.test(html) && !/add \.wav clips/.test(html));

console.log('');
console.log((fails.length ? 'FAIL' : 'OK') + ' — ' + fails.length + ' failure(s)');
fails.forEach(f => console.log('  - ' + f));
process.exit(fails.length ? 1 : 0);
