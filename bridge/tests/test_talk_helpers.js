/* Panel-side unit test for the PHASE D dictation helpers (● talk).
 *
 * Same extraction pattern as test_speak_text.js: the functions are pulled OUT of
 * bridge/panel/index.html by name, so a rename or an edit trips this test instead of
 * letting the test drift from the shipped code.
 *
 *   talkTime(sec)        the recording button's mono timer
 *   talkMime(supported)  which container MediaRecorder should produce, and the fmt
 *                        string the bridge is told about
 *
 * Run: node bridge/tests/test_talk_helpers.js   (from repo root)
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

eval(grab('talkTime'));
eval(grab('talkMime'));

/* ---- talkTime -------------------------------------------------------------- */
check('0 seconds → 0:00', talkTime(0) === '0:00');
check('5 seconds pads to 0:05', talkTime(5) === '0:05');
check('9.9 seconds floors to 0:09 (never rounds a second up early)', talkTime(9.9) === '0:09');
check('59 → 0:59', talkTime(59) === '0:59');
check('60 rolls to 1:00', talkTime(60) === '1:00');
check('61 → 1:01', talkTime(61) === '1:01');
check('125 → 2:05', talkTime(125) === '2:05');
check('600 → 10:00', talkTime(600) === '10:00');
check('negative clamps to 0:00 (a clock skew must not print -1:-5)', talkTime(-3) === '0:00');
check('NaN clamps to 0:00', talkTime(NaN) === '0:00');
check('undefined clamps to 0:00', talkTime(undefined) === '0:00');
check('a numeric string is accepted', talkTime('7') === '0:07');
check('the seconds field is ALWAYS two digits',
  [0, 1, 9, 10, 59, 61, 119].every(s => /^\d+:\d\d$/.test(talkTime(s))));

/* ---- talkMime -------------------------------------------------------------- */
const only = list => (t => list.indexOf(t) >= 0);

let r = talkMime(only(['audio/mp4', 'audio/webm']));
check('mp4 is preferred when both are supported (WKWebView records AAC-in-mp4)',
  r.mime === 'audio/mp4' && r.fmt === 'mp4');

r = talkMime(only(['audio/webm']));
check('webm is used when mp4 is unsupported', r.mime === 'audio/webm' && r.fmt === 'webm');

r = talkMime(only(['audio/mp4']));
check('mp4 is used when webm is unsupported', r.mime === 'audio/mp4' && r.fmt === 'mp4');

r = talkMime(only([]));
check('nothing supported → empty mime (let the browser choose)', r.mime === '');
check('nothing supported → a fmt is STILL named (the bridge must be told something)',
  r.fmt === 'webm');

check('every returned fmt is one the bridge accepts',
  [only(['audio/mp4', 'audio/webm']), only(['audio/webm']), only([])]
    .every(s => ['mp4', 'webm', 'wav'].indexOf(talkMime(s).fmt) >= 0));
check('the mime always matches the fmt when a mime is chosen',
  [only(['audio/mp4']), only(['audio/webm'])]
    .every(s => { const x = talkMime(s); return x.mime === 'audio/' + x.fmt; }));

/* ---- wiring facts read straight out of the panel source -------------------- */
check('the ● talk button exists in the composer', html.indexOf('id="chat-talk"') >= 0);
// Debi 2026-08-13: talk sat AFTER Send and read ~40% smaller than it.
// ⚠️ FENCE MOVED, v1.5.26 — reviewed, not quietly adjusted. Debi's composer redesign
// puts every control INSIDE one bounded field, in the grammar Claude / LM Studio /
// Unsloth share: the mic sits beside Send with Send LAST before the audio switch. So
// the ORDER pinned here inverts. What the 2026-08-13 ruling was protecting — talk is
// visibly subordinate to Send — is unchanged and is pinned on the next check instead:
// Send is the one filled accent control, ● talk is the quiet ghost beside it.
check('● talk sits INSIDE the field, immediately before Send (textarea → talk → Send)',
  html.indexOf('id="chat-talk"') > html.indexOf('id="chat-input"')
  && html.indexOf('id="chat-send"') > html.indexOf('id="chat-talk"'));
check('…and the field is the composer row itself, not the textarea',
  /#chat-inputrow \{[^}]*background:var\(--card\)[^}]*border-radius:16px/.test(html)
  && /#chat-inputrow:focus-within \{ border-color:var\(--gold\); \}/.test(html)
  && /#chat-input \{[^}]*background:transparent[^}]*border:0/.test(html));
check('● talk ships hidden (shown only when an STT default exists)',
  /id="chat-talk"[\s\S]{0,400}?hidden>/.test(html));
// AUTO-DICTATION v1 widened the smaller override to `#chat-talk, #chat-auto`, and
// CONVERSATION MODE widened it again to include `#chat-conv` — each is the same
// class of control at the same size, so they share the rule rather than adding one.
// ⚠️ FENCE MOVED 2026-08-28 (v1.5.24, the impeccable-debt slice), spelled out because a
// moved fence should be reviewed, not quietly adjusted. THREE suites (this one,
// test_conv_mode and test_vad_segmenter) pinned the literal `font-size:7px`. What each of
// them is actually about is that the three chips SHARE ONE size rule; the number was
// incidental to that claim and load-bearing for nothing else. 7px was the smallest ink in
// the panel and its only declaration under 9px, so it is now 9.5px — with the argument
// (including which standing Debi ruling that overrode) in the rule's own comment in
// index.html. The claim these checks make is unchanged; only the literal moved. The floor
// itself is now fenced properly in bridge/tests/test_editorial_debt.js, which asserts the
// whole sheet has no font under 10px APART FROM this one named exception — the number is
// pinned in ONE place with its reason instead of three places without one.
// v1.5.26: `auto` and `conv` are no longer chips — they are the two ends of the
// audio-mode switch, and its zones carry the same 9.5px. The claim is unchanged (ONE
// small size, shared, never invented per control); the selector that carries it moved.
check('Send keeps the shared size rule; talk carries its own smaller override',
  html.indexOf('#chat-send, #chat-talk {') >= 0
  && /#chat-talk \{[^}]*font-size:9\.5px/.test(html));
check('…and the audio switch\'s zones reuse that same 9.5px rather than inventing one',
  /#chat-audiosw \.asw-zone \{[^}]*font:9\.5px var\(--mono\)/.test(html));
check('Send is the one FILLED accent control and talk is the ghost beside it (what the '
    + '2026-08-13 subordination ruling was actually about)',
  /#chat-talk \{[^}]*background:transparent/.test(html)
  && !/#chat-send \{[^}]*background:transparent/.test(html));
check('the size rule does NOT touch button.primary globally',
  !/button\.primary\s*\{[^}]*font-size:/.test(html));
check('the button rides loadVoiceCfg (same read as the AUDIO chip)',
  html.indexOf('renderTalkBtn();     // PHASE D') >= 0);
check('the transcript is APPENDED to the composer, never auto-sent',
  html.indexOf('async function finishTalk') >= 0
  && !/function finishTalk[\s\S]*?\n}/.exec(html)[0].includes('sendChat('));
check('recording auto-stops at a hard cap', html.indexOf('TALK_MAX_S = 60') >= 0);
check('the mic tracks are stopped on every exit path (the mic light must go out)',
  (html.match(/getTracks\(\)\.forEach\(t => t\.stop\(\)\)/g) || []).length >= 2);
check('a permission failure points at Logs/README',
  html.indexOf("'microphone permission — see Logs/README'") >= 0);
check('errors reuse the ▶ speak flash idiom', html.indexOf('speakFlash(btn,') >= 0);
check('the POST names the container in the query string',
  html.indexOf("'/api/voice/stt?fmt=' + encodeURIComponent(fmt)") >= 0);

console.log('');
console.log((fails.length ? 'FAIL' : 'OK') + ' — ' + fails.length + ' failure(s)');
fails.forEach(f => console.log('  - ' + f));
process.exit(fails.length ? 1 : 0);
