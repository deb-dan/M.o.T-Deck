/* Panel-side unit test for AUTO-DICTATION v1 — the VAD segmenter and its helpers.
 *
 * The segmenter is the crown jewel of this slice: it is the only thing standing
 * between a live microphone and a stream of junk POSTs, and it is impossible to
 * eyeball. It is therefore written PURE (a new state object per block, no DOM, no
 * audio) and table-tested here off synthetic RMS sequences.
 *
 * Functions are pulled OUT of bridge/panel/index.html by name (same extraction
 * pattern as test_speak_text.js / test_talk_helpers.js), so a rename or an edit trips
 * this test instead of letting the test drift from the shipped code:
 *
 *   vadNoiseFloor(list)        median of a rolling non-speech RMS window
 *   vadInit(frameMs, opts)     initial state, ms constants → block counts
 *   vadRearm(st)               the next listening window: reset, but KEEP the floor
 *   hangoverFor(fmt)           engine-aware close time (whisper 800 / parakeet 575)
 *   vadStep(st, rms)           the state machine, one block at a time
 *   vadSplice(frames, base, from, to)   ring-buffer cut
 *   resampleLinear(in, a, b)   48k → 16k
 *
 * Run: node bridge/tests/test_vad_segmenter.js   (from repo root)
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

/* The constants are read out of the panel too — a value changed there must change
 * the expectations here, not silently pass against a stale copy. */
function constant(name) {
  const m = new RegExp('const\\s+' + name + '\\s*=\\s*([0-9.]+)\\s*;').exec(html);
  if (!m) throw new Error('constant ' + name + ' not found in the panel');
  return Number(m[1]);
}

const VAD_BLOCK      = constant('VAD_BLOCK');
const VAD_OPEN_FRAMES= constant('VAD_OPEN_FRAMES');
const VAD_HANGOVER_MS= constant('VAD_HANGOVER_MS');
const VAD_PREROLL_MS = constant('VAD_PREROLL_MS');
const VAD_TAIL_MS    = constant('VAD_TAIL_MS');
const VAD_MIN_MS     = constant('VAD_MIN_MS');
const VAD_MAX_MS     = constant('VAD_MAX_MS');
const VAD_NOISE_MS   = constant('VAD_NOISE_MS');
const VAD_WARMUP_MS  = constant('VAD_WARMUP_MS');
const VAD_MULT       = constant('VAD_MULT');
const VAD_FLOOR      = constant('VAD_FLOOR');
const VAD_THR_MAX    = constant('VAD_THR_MAX');

const VAD_HANGOVER_FAST_MS = constant('VAD_HANGOVER_FAST_MS');

eval(grab('vadNoiseFloor'));
eval(grab('hangoverFor'));
eval(grab('vadInit'));
eval(grab('vadRearm'));
eval(grab('vadStep'));
eval(grab('vadSplice'));
eval(grab('resampleLinear'));

/* 10ms blocks keep the arithmetic legible: hangover 80 blocks, pre-roll 30,
 * min 40, max 3000, noise window 200. */
const MS = 10;
const fr = (ms) => Math.round(ms / MS);

/* Drive a whole sequence, collecting every emit with the block index it fired at. */
function run(seq, st0) {
  let st = st0 || vadInit(MS);
  const emits = [];
  for (let i = 0; i < seq.length; i++) {
    const r = vadStep(st, seq[i]);
    st = r.st;
    if (r.emit) emits.push(Object.assign({ at: i }, r.emit));
  }
  return { st: st, emits: emits };
}
const rep = (v, n) => new Array(n).fill(v);

/* ---- vadNoiseFloor --------------------------------------------------------- */
check('empty window → 0', vadNoiseFloor([]) === 0);
check('single value is its own median', vadNoiseFloor([0.4]) === 0.4);
check('odd count takes the middle', vadNoiseFloor([9, 1, 5]) === 5);
check('even count averages the two middles', vadNoiseFloor([1, 2, 3, 4]) === 2.5);
check('a single loud outlier does NOT move the floor (why median, not mean)',
  vadNoiseFloor([0.01, 0.01, 0.01, 0.01, 9]) === 0.01);
check('NaN / negative / junk entries are ignored, not counted',
  vadNoiseFloor([0.02, NaN, -1, 'x', 0.02]) === 0.02);
check('an all-junk window degrades to 0 rather than NaN',
  vadNoiseFloor([NaN, undefined, 'x']) === 0);
check('undefined input is total', vadNoiseFloor(undefined) === 0);

/* ---- vadInit --------------------------------------------------------------- */
let st = vadInit(MS);
check('init starts idle', st.speaking === false && st.n === -1);
check('the opening threshold starts at the absolute floor (a silent room must not '
    + 'have a threshold of zero)', st.thr === VAD_FLOOR);
check('hangover ms → block count', st.hangover === fr(VAD_HANGOVER_MS));
check('pre-roll ms → block count', st.preroll === fr(VAD_PREROLL_MS));
check('tail ms → block count', st.tail === fr(VAD_TAIL_MS));
check('min ms → block count', st.minFrames === fr(VAD_MIN_MS));
check('max ms → block count', st.maxFrames === fr(VAD_MAX_MS));
check('noise window ms → block count', st.noiseCap === fr(VAD_NOISE_MS));
check('open frames is a COUNT and is not scaled by frameMs',
  st.open === VAD_OPEN_FRAMES && vadInit(3).open === VAD_OPEN_FRAMES);
check('a 2.67ms block (128 samples @48k) still yields sane counts',
  vadInit(2.67).hangover === Math.round(VAD_HANGOVER_MS / 2.67));
check('a zero/garbage frameMs cannot produce Infinity block counts',
  isFinite(vadInit(0).hangover) && vadInit(0).hangover >= 1);
check('every derived count is at least 1 block', (() => {
  const s = vadInit(1000);
  return [s.hangover, s.preroll, s.tail, s.minFrames, s.maxFrames, s.noiseCap]
    .every(v => v >= 1);
})());

/* ---- hangoverFor: the engine-aware close time ------------------------------- */
check('the whisper engine keeps the long, hallucination-tuned hangover',
  hangoverFor('stt-mlx') === VAD_HANGOVER_MS);
check('the mlx-audio/Parakeet engine closes sooner',
  hangoverFor('stt-mlx-audio') === VAD_HANGOVER_FAST_MS);
check('the fast hangover really is FASTER (this is the whole point)',
  VAD_HANGOVER_FAST_MS < VAD_HANGOVER_MS);
check('the fast hangover is not so short that it splits utterances at a natural '
    + 'pause — in conv mode a split SENDS TWO MESSAGES', VAD_HANGOVER_FAST_MS >= 500);
check('an unknown / empty / junk format degrades to the SAFE long hangover',
  ['', 'stt-mlx-whatever', 'tts-mlx', undefined, null, 0, {}]
    .every(v => hangoverFor(v) === VAD_HANGOVER_MS));

/* ---- vadInit: the opts channel ---------------------------------------------- */
check('vadInit with no opts is byte-for-byte the old behaviour',
  vadInit(MS).hangover === fr(VAD_HANGOVER_MS) && vadInit(MS).noise.length === 0
  && vadInit(MS).thr === VAD_FLOOR);
check('an explicit hangoverMs is converted to blocks like every other constant',
  vadInit(MS, { hangoverMs: VAD_HANGOVER_FAST_MS }).hangover
    === fr(VAD_HANGOVER_FAST_MS));
check('a zero/garbage hangoverMs falls back to the default, never to 0 blocks',
  [0, -5, NaN, 'x', undefined].every(v =>
    vadInit(MS, { hangoverMs: v }).hangover === fr(VAD_HANGOVER_MS)));
check('a carried noise window is COPIED, not aliased (a later push must not reach '
    + 'back into the old state)', (() => {
  const src = [0.01, 0.02];
  const s = vadInit(MS, { noise: src });
  s.noise.push(0.9);
  return src.length === 2;
})());
check('a carried threshold is used as the opening threshold',
  vadInit(MS, { thr: 0.05 }).thr === 0.05);
check('a junk carried threshold degrades to the floor',
  [0, -1, NaN, 'x', null].every(v => vadInit(MS, { thr: v }).thr === VAD_FLOOR));

/* ---- vadStep: purity -------------------------------------------------------- */
const before = vadInit(MS);
const snapshot = JSON.stringify(before);
vadStep(before, 0.9);
check('vadStep does NOT mutate the state it is given', JSON.stringify(before) === snapshot);
check('vadStep returns a NEW state object', vadStep(before, 0.9).st !== before);

/* Every scenario below opens with a LEAD of quiet blocks: the segmenter cannot open
 * the gate until it has heard a warm-up window, so a sequence that starts talking on
 * block 0 is not testing what it looks like it is testing. */
const WARM = fr(VAD_WARMUP_MS);
const LEAD = WARM + 10;
const HANG = fr(VAD_HANGOVER_MS);
const QUIET = 0.001, LOUD = 0.5;

/* ---- vadStep: warm-up ------------------------------------------------------- */
check('the gate cannot open during the warm-up window, however loud it gets',
  run(rep(LOUD, WARM - 1)).st.speaking === false);
check('speech DOES open once the warm-up window has passed',
  run(rep(QUIET, LEAD).concat(rep(LOUD, 10))).st.speaking === true);
check('warm-up is what guarantees the pre-roll has history to roll back into',
  VAD_PREROLL_MS <= VAD_WARMUP_MS);

/* ---- vadRearm: THE floor-carry behaviour change -----------------------------
 * BEHAVIOUR CHANGE, recorded honestly: conversation mode used to re-arm with a bare
 * vadInit(frameMs), which threw the learned noise floor away and made every single
 * turn pay a fresh ~600ms deaf warm-up. Only the machine RESET was ever load-bearing
 * (it is what makes resuming mid-utterance from before the feedback gate impossible);
 * the floor is a property of the ROOM, and the room does not change between turns. */
{
  const learned = run(rep(0.02, WARM + 40)).st;
  check('a warmed-up window has a full noise history and a raised threshold',
    learned.noise.length >= learned.warm && learned.thr > VAD_FLOOR);
  const re = vadRearm(learned);
  check('re-arm CARRIES the learned noise floor forward (this is the ~600ms saving)',
    re.noise.length === learned.noise.length && re.thr === learned.thr);
  check('and therefore the next window is NOT warming up — it can open immediately',
    re.noise.length >= re.warm);
  check('speech opens on the very next blocks after a re-arm, with no warm-up wait',
    run(rep(LOUD, VAD_OPEN_FRAMES + 1), re).st.speaking === true);
  check('re-arm still RESETS the machine — that half was always the load-bearing one',
    re.speaking === false && re.run === 0 && re.silence === 0
    && re.start === 0 && re.vstart === 0 && re.n === -1);
  check('re-arm keeps the session\'s engine-tuned hangover exactly (no ms round-trip)',
    vadRearm(vadInit(MS, { hangoverMs: VAD_HANGOVER_FAST_MS })).hangover
      === fr(VAD_HANGOVER_FAST_MS));
  check('re-arm does not mutate the state it is given',
    (() => { const snap = JSON.stringify(learned); vadRearm(learned);
             return JSON.stringify(learned) === snap; })());
  check('re-arm returns a NEW object', vadRearm(learned) !== learned);
  check('re-arming a window that never finished warming up simply CONTINUES warming',
    (() => { const r2 = vadRearm(run(rep(0.02, 5)).st);
             return r2.noise.length === 5 && r2.noise.length < r2.warm; })());
  check('a FIRST window (nothing carried) still pays the full warm-up',
    run(rep(LOUD, WARM - 1)).st.speaking === false);
}

/* ---- vadStep: a clean utterance --------------------------------------------- */
let r = run(rep(QUIET, LEAD).concat(rep(LOUD, 100), rep(QUIET, HANG + 5)));
check('a clean utterance emits exactly once', r.emits.length === 1);
check('it closes on the hangover, not the max cut', r.emits[0].reason === 'hangover');
check('it is long enough to transcribe', r.emits[0].ok === true);
check('it ends idle, ready for the next one', r.st.speaking === false);
check('the reported speech length is the speech, not the padding',
  Math.round(r.emits[0].speechMs) === 100 * MS);

/* ---- vadStep: pre-roll ------------------------------------------------------ */
check('the cut starts a full pre-roll BEFORE the first speech block (a quiet word '
    + 'onset must not be clipped)', r.emits[0].from === LEAD - fr(VAD_PREROLL_MS));
check('the pre-roll is really ~300ms of audio',
  (LEAD - r.emits[0].from) * MS === VAD_PREROLL_MS);
check('the cut start is never negative, whatever the timing',
  [LEAD, LEAD + 1, LEAD + 40].every(lead =>
    run(rep(QUIET, lead).concat(rep(LOUD, 100), rep(QUIET, HANG + 5)))
      .emits[0].from >= 0));

/* ---- vadStep: the tail ------------------------------------------------------ */
check('the cut ends a tail after the last speech block, NOT after the whole hangover '
    + '(800ms of trailing silence is what makes whisper hallucinate)',
  r.emits[0].to === LEAD + 100 + fr(VAD_TAIL_MS));
check('the emitted ms matches the block span',
  Math.round(r.emits[0].ms) === Math.round((r.emits[0].to - r.emits[0].from) * MS));

/* ---- vadStep: hangover does not split a natural pause ----------------------- */
const shortPause = HANG - 10;
r = run(rep(QUIET, LEAD)
  .concat(rep(LOUD, 60), rep(QUIET, shortPause), rep(LOUD, 60), rep(QUIET, HANG + 5)));
check('a pause SHORTER than the hangover does not split the utterance',
  r.emits.length === 1);
check('the single emit spans both halves',
  r.emits[0].to - r.emits[0].from > (60 + shortPause + 60));

const longPause = HANG + 5;
r = run(rep(QUIET, LEAD)
  .concat(rep(LOUD, 60), rep(QUIET, longPause), rep(LOUD, 60), rep(QUIET, longPause)));
check('a pause LONGER than the hangover DOES split it into two utterances',
  r.emits.length === 2);
check('the two utterances do not overlap', r.emits[0].to <= r.emits[1].from);
check('both halves are transcribed (neither is swallowed)',
  r.emits.every(e => e.ok));

/* ---- vadStep: minimum length ------------------------------------------------ */
const tiny = fr(VAD_MIN_MS) - 2;
r = run(rep(QUIET, LEAD).concat(rep(LOUD, tiny), rep(QUIET, HANG + 5)));
check('a cough emits with ok:false (the caller drops it, nothing is POSTed)',
  r.emits.length === 1 && r.emits[0].ok === false);
check('the length gate measures SPEECH, not the padded cut — pre-roll + tail add '
    + '500ms and would otherwise float every cough past a 400ms floor',
  r.emits[0].ms > VAD_MIN_MS && r.emits[0].speechMs < VAD_MIN_MS);
check('one block more than the minimum IS accepted (the boundary is not off by a lot)',
  run(rep(QUIET, LEAD).concat(rep(LOUD, fr(VAD_MIN_MS) + 1), rep(QUIET, HANG + 5)))
    .emits[0].ok === true);
check('a rejected utterance still leaves the segmenter idle and usable',
  r.st.speaking === false);
r = run(rep(QUIET, LEAD).concat(rep(LOUD, 100), rep(QUIET, HANG + 5),
        rep(LOUD, 100), rep(QUIET, HANG + 5)));
check('two well-separated utterances both emit ok',
  r.emits.length === 2 && r.emits.every(e => e.ok));

/* ---- vadStep: max length ---------------------------------------------------- */
r = run(rep(QUIET, LEAD).concat(rep(LOUD, fr(VAD_MAX_MS) + 200)));
check('a monologue is hard-cut at the max length', r.emits.length >= 1);
check('the hard cut is labelled as such', r.emits[0].reason === 'max');
check('the hard cut is long enough to transcribe', r.emits[0].ok === true);
check('the hard cut is no longer than the max',
  (r.emits[0].to - r.emits[0].from) <= fr(VAD_MAX_MS) + fr(VAD_PREROLL_MS));
check('a hard cut carries NO tail (there is no trailing silence to keep)',
  r.emits[0].to === r.emits[0].from + Math.min(fr(VAD_MAX_MS),
    r.emits[0].to - r.emits[0].from));
check('speech CONTINUES after a hard cut (the mic is not left closed mid-sentence)',
  r.st.speaking === true || r.emits.length === 2);

/* ---- vadStep: noise-floor adaptation ---------------------------------------- */
check('a silent room keeps the threshold at the clamp, never at ~0',
  run(rep(0.0005, 300)).st.thr === VAD_FLOOR);
check('a moderately noisy room raises the threshold to the multiplier × the floor',
  Math.abs(run(rep(0.02, 400)).st.thr - VAD_MULT * 0.02) < 1e-9);
check('the moderate noise itself NEVER opens an utterance',
  run(rep(0.02, 400)).emits.length === 0);
const fan = run(rep(0.05, 600));
check('a LOUD room (ambient above the clamp) still learns — this is the whole reason '
    + 'the warm-up exists; without it the gate opens on block 3 and never learns',
  fan.st.thr > VAD_FLOOR && fan.emits.length === 0);
check('the threshold is capped so a loud room cannot make the VAD deaf to speech',
  fan.st.thr === VAD_THR_MAX);
check('a voice above the raised threshold still opens in that loud room',
  run(rep(0.05, 600).concat(rep(0.4, 100), rep(0.05, HANG + 5))).emits.length === 1);
check('the noise window is bounded to its cap (memory cannot grow unbounded)',
  run(rep(0.02, fr(VAD_NOISE_MS) * 5)).st.noise.length === fr(VAD_NOISE_MS));
check('speech is NOT fed into the noise window (a talker must not deafen the VAD)',
  (() => {
    const q = run(rep(QUIET, 300));
    const s = run(rep(QUIET, 300).concat(rep(LOUD, 200)));
    return s.st.thr === q.st.thr;
  })());

/* ---- vadStep: totality ------------------------------------------------------ */
check('a NaN rms is treated as silence, never as speech',
  run(rep(NaN, 400)).emits.length === 0 && run(rep(NaN, 400)).st.speaking === false);
check('a negative rms is treated as silence', run(rep(-1, 400)).emits.length === 0);
check('undefined blocks cannot crash the machine',
  run(rep(undefined, 200)).st.speaking === false);
check('the block counter advances exactly once per call',
  run(rep(QUIET, 25)).st.n === 24);

/* ---- vadSplice -------------------------------------------------------------- */
const frames = [0, 1, 2, 3, 4].map(v => Float32Array.from([v, v]));
let cut = vadSplice(frames, 0, 1, 3);
check('a splice concatenates the requested blocks in order',
  cut.length === 4 && cut[0] === 1 && cut[2] === 2);
cut = vadSplice(frames, 10, 11, 13);
check('an absolute range is offset by the ring-buffer base',
  cut.length === 4 && cut[0] === 1 && cut[2] === 2);
check('a range starting before the base is clamped, not read out of bounds',
  vadSplice(frames, 10, 5, 12).length === 4);
check('a range ending past the end is clamped',
  vadSplice(frames, 0, 3, 99).length === 4);
check('an empty range yields an empty buffer', vadSplice(frames, 0, 2, 2).length === 0);
check('an inverted range yields an empty buffer', vadSplice(frames, 0, 4, 1).length === 0);

/* ---- resampleLinear --------------------------------------------------------- */
const ramp = Float32Array.from({ length: 48 }, (_, i) => i / 47);
let out = resampleLinear(ramp, 48000, 16000);
check('48k → 16k divides the length by three', out.length === 16);
check('the first sample is preserved exactly (endpoint)', out[0] === ramp[0]);
check('the output stays inside the input range',
  Array.from(out).every(v => v >= ramp[0] - 1e-6 && v <= ramp[ramp.length - 1] + 1e-6));
check('a monotonic ramp resamples monotonically (no interpolation sign errors)',
  Array.from(out).every((v, i) => i === 0 || v >= out[i - 1]));
check('an equal rate returns the same samples', (() => {
  const same = resampleLinear(ramp, 16000, 16000);
  return same.length === ramp.length && same[5] === ramp[5];
})());
check('an equal rate returns a COPY, not the caller\'s buffer',
  resampleLinear(ramp, 16000, 16000) !== ramp);
check('44.1k → 16k lands on the expected length',
  resampleLinear(new Float32Array(441), 44100, 16000).length
    === Math.floor(441 / (44100 / 16000)));
check('upsampling works too (16k → 48k triples)',
  resampleLinear(new Float32Array(16), 16000, 48000).length === 48);
check('interpolation actually interpolates (a midpoint is between its neighbours)',
  (() => {
    const two = Float32Array.from([0, 1]);
    const up = resampleLinear(two, 1, 2);      // → [0, 0.5]
    return up.length === 4 || (up[1] > 0 && up[1] < 1);
  })());
check('an empty input yields an empty output', resampleLinear(new Float32Array(0), 48000, 16000).length === 0);
check('a zero/absurd rate yields empty rather than Infinity',
  resampleLinear(ramp, 0, 16000).length === 0
  && resampleLinear(ramp, 48000, 0).length === 0);
check('undefined input is total', resampleLinear(undefined, 48000, 16000).length === 0);
check('the output is always a Float32Array',
  resampleLinear(ramp, 48000, 16000) instanceof Float32Array);

/* ---- wiring facts read straight out of the panel source --------------------- */
check('the auto chip exists in the composer', html.indexOf('id="chat-auto"') >= 0);
check('the auto chip sits AFTER ● talk (Send → talk → auto)',
  html.indexOf('id="chat-auto"') > html.indexOf('id="chat-talk"'));
check('the auto chip ships hidden (shown only when an STT default exists)',
  /id="chat-auto"[\s\S]{0,400}?hidden>/.test(html));
// (CONVERSATION MODE later joined both selectors — same class of control, same
//  size, same meaning of "live" — so these pin the widened form.)
check('the auto chip shares ● talk\'s size rule instead of inventing one',
  /#chat-talk,\s*#chat-auto,\s*#chat-conv\s*\{[^}]*font-size:9\.5px/.test(html));
check('the listening state reuses the glyph-carries-the-colour idiom',
  /#chat-auto\.on \.talk-dot,\s*#chat-conv\.on \.talk-dot\s*\{\s*color:var\(--gold\)/.test(html));
check('the auto chip rides the SAME config read as ● talk',
  /renderTalkBtn[\s\S]{0,900}?renderAutoBtn\(\);/.test(html));
check('capture goes through an AudioWorklet (GATE 1\'s proven path), not MediaRecorder',
  html.indexOf('registerProcessor("harness-vad"') >= 0);
check('the worklet module is loaded from a Blob URL exactly as the spike proved',
  /addModule\(url\)[\s\S]{0,200}?harness-vad/.test(html)
  || html.indexOf("new AudioWorkletNode(ctx, 'harness-vad'") >= 0);
check('utterances are POSTed to the EXISTING stt endpoint as wav',
  html.indexOf("'/api/voice/stt?fmt=wav'") >= 0);
check('a 16 kHz mono wav is encoded client-side (no ffmpeg on the bridge side)',
  /wavFromPcm\(resampleLinear\(pcm, a\.rate, 16000\), 16000\)/.test(html));
check('wavFromBuffer still exists and now delegates to wavFromPcm (the clip recorder '
    + 'path is unchanged)',
  html.indexOf('function wavFromBuffer(') >= 0
  && /function wavFromBuffer\(buf\)\{[\s\S]{0,160}?wavFromPcm\(buf\.getChannelData\(0\)/.test(html));
check('the transcript is APPENDED, never auto-sent',
  html.indexOf('function appendTranscript(') >= 0
  && !/function autoDrain\([\s\S]*?\n}/.exec(html)[0].includes('sendChat('));
check('an empty transcript is silently skipped (whisper hallucinates on silence)',
  /if \(text\) appendTranscript\(text, false\)/.test(html));
check('utterances are transcribed one at a time (the endpoint holds a global lock)',
  /if \(!a \|\| a\.busy \|\| !a\.queue\.length\) return;/.test(html));
check('auto mode gives up after repeated failures rather than looping forever',
  html.indexOf('VAD_MAX_ERRORS') >= 0 && /a\.errors >= VAD_MAX_ERRORS/.test(html));
check('there is exactly ONE teardown path', (html.match(/function stopAuto\(/g) || []).length === 1);
check('the mic tracks are stopped in it (the mic light must go out)',
  /function stopAuto\([\s\S]{0,900}?getTracks\(\)\.forEach\(t => t\.stop\(\)\)/.test(html));
check('the AudioContext is closed in it too', /function stopAuto\([\s\S]{0,900}?ctx\.close\(\)/.test(html));
check('leaving the Chat view stops it', html.indexOf("stopAuto('left the Chat view')") >= 0);
check('a lane switch stops it', html.indexOf("stopAuto('lane switch')") >= 0);
check('clearing the STT default stops it',
  html.indexOf("stopAuto('the speech-to-text default was cleared')") >= 0);
check('starting manual dictation stops it (the two are exclusive)',
  html.indexOf("stopAuto('manual dictation started')") >= 0);
check('starting auto stops manual dictation (exclusive both ways)',
  /async function startAuto\([\s\S]{0,400}?if \(talkRec\) stopTalk\(true\)/.test(html));
check('the transcribing state is surfaced in the title attribute (non-intrusive)',
  /busy \? 'transcribing…'/.test(html));
check('errors on this chip use a flash that restores the AUTO label, not speakFlash '
    + '(which restores "▶ speak" after 2s and would mislabel the composer)',
  html.indexOf('function autoFlash(') >= 0
  && !/function startAuto\([\s\S]*?\n}\n\n\/\* One block/.exec(html)[0].includes('speakFlash('));
check('a flash is not immediately overwritten by a re-render',
  !/autoFlash\([^)]*\);\s*renderAutoBtn\(\);/.test(html));
check('a suspended AudioContext is resumed (a suspended ctx pumps no frames at all)',
  /ctx\.state === 'suspended'/.test(html));
check('the warm-up window exists and is read from a named constant',
  html.indexOf('VAD_WARMUP_MS') >= 0 && /s\.noise\.length < s\.warm/.test(html));
check('every VAD tunable is a named module-level constant, not a literal in the logic',
  ['VAD_BLOCK', 'VAD_OPEN_FRAMES', 'VAD_HANGOVER_MS', 'VAD_HANGOVER_FAST_MS',
   'VAD_PREROLL_MS', 'VAD_TAIL_MS',
   'VAD_MIN_MS', 'VAD_MAX_MS', 'VAD_NOISE_MS', 'VAD_WARMUP_MS', 'VAD_MULT', 'VAD_FLOOR',
   'VAD_THR_MAX', 'VAD_MAX_ERRORS']
    .every(n => new RegExp('const ' + n + ' =').test(html)));
check('the worklet is never connected to the output (no feedback howl)',
  /createMediaStreamSource\(stream\)\.connect\(node\)/.test(html)
  && !/node\.connect\(ctx\.destination\)/.test(html));
check('the segmenter is tuned to the STT engine at CAPTURE time (switching the '
    + 'default mid-session must not retune a live listener)',
  /st: vadInit\(frameMs, \{ hangoverMs: hangoverFor\(sttFormat\(\)\) \}\)/.test(html));
check('sttFormat reads the format off the SAME /api/voice/config payload the chips '
    + 'already use — no second endpoint',
  /function sttFormat\(\)\{[\s\S]{0,400}?voiceCfg\.stt_model[\s\S]{0,200}?voiceCfg\.available/
    .test(html));
check('the conv re-arm goes through vadRearm, never a bare vadInit',
  /convSt\.phase === 'listening'\)\{\s*autoVad\.st = vadRearm\(autoVad\.st\)/.test(html)
  && (html.match(/vadInit\(autoVad\.frameMs\)/g) || []).length === 0);

console.log('');
console.log((fails.length ? 'FAIL' : 'OK') + ' — ' + fails.length + ' failure(s)');
fails.forEach(f => console.log('  - ' + f));
process.exit(fails.length ? 1 : 0);
