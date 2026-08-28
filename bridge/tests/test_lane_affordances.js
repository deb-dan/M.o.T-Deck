/* THE CAPABILITY-AFFORDANCE AUDIT, AS A FENCE (2026-08-28, Debi's ruling).
 *
 * "We should ensure all paths have what they can handle depending on the model."
 * The first instance she found: the ⊕ attach button existed on the Chat lane only,
 * for no reason except that it was built there first. This file is the audit table
 * turned into assertions, so the next affordance that quietly grows a lane gate
 * trips a test instead of shipping.
 *
 * THE TABLE (lane × affordance → what the UI must do). Backend evidence for the
 * attach row lives in bridge/tests/test_lane_attach.py; this file is the PANEL half.
 *
 *   affordance      chat            agent           hermes
 *   image attach    ⊕, vision-gated ⊕, no gate      ⊕, no gate
 *   audio in        composer-level — one control, no lane branch
 *   TTS speak-back  composer-level — one control, no lane branch
 *   stop/interrupt  Send→Stop       Send→Stop       Send→Stop (+ session.interrupt)
 *   sessions/new    Odysseus rail   Odysseus rail   Hermes rail
 *   lane note       one source (laneNote), three sentences
 *
 * Run: node bridge/tests/test_lane_affordances.js   (from repo root)
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

/* Brace-matched extraction of `function <name>(...) { ... }` (the established
   pattern — see test_attach_marker.js), made COMMENT-AWARE. This panel documents
   its bugs in prose, and prose contains apostrophes: a `//` line explaining what
   "Odysseus's setting" does used to put the scanner into string mode and swallow
   the rest of the file. A test that breaks when a comment is written is a test
   that discourages comments. */
function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  let i = html.indexOf('{', at), depth = 0, inStr = null, prev = '', mode = '';
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (mode === 'line') {
      if (c === '\n') mode = '';
    } else if (mode === 'block') {
      if (prev === '*' && c === '/') mode = '';
    } else if (inStr) {
      if (c === inStr && prev !== '\\') inStr = null;
    } else if (c === '/' && html[j + 1] === '/') {
      mode = 'line';
    } else if (c === '/' && html[j + 1] === '*') {
      mode = 'block';
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

const src = grab('attachVerdict') + '\n' + grab('laneNote');
// eslint-disable-next-line no-new-func
const mod = new Function(src + '; return {attachVerdict, laneNote};')();
const { attachVerdict, laneNote } = mod;

const LANES = ['chat', 'agent', 'hermes'];

console.log('\n-- the attach row of the table --');
for (const lane of LANES) {
  const v = attachVerdict(lane, true);
  check(lane + ': a VISION model carries an image with no caveat', v.on && !v.why);
}
check('chat + a model that CANNOT see: blocked, and the reason names the way out',
      attachVerdict('chat', false).on === false
      && /Agent|Hermes/.test(attachVerdict('chat', false).why));
for (const lane of ['agent', 'hermes']) {
  const v = attachVerdict(lane, false);
  check(lane + ': a text-only model is WARN-NOT-BLOCK — the backend describes it',
        v.on === true && /describe/.test(v.why));
}
// The three-valued rule, mirrored from the `tools` pill: null is NOT false.
for (const lane of LANES) {
  const v = attachVerdict(lane, null);
  check(lane + ': an UNKNOWN model (null) warns and lets the attempt through — '
        + 'absent-not-greyed, the tools-pill rule',
        v.on === true && !!v.why);
  check(lane + ': …and undefined is treated as null, never as "no"',
        attachVerdict(lane, undefined).on === true);
}
check('every verdict that is not a clean yes carries a SENTENCE (no bare grey)',
      LANES.every(l => [true, false, null].every(v => {
        const r = attachVerdict(l, v);
        return (r.on && !r.why) || (typeof r.why === 'string' && r.why.length > 20);
      })));

console.log('\n-- the Odysseus vision-config caveat (a DRIVEN finding) --');
// Odysseus decides main-model vision by NAME KEYWORDS and falls back to its own
// `vision_model`; unset, the picture becomes the literal text "[No vision model
// configured…]". Driven 2026-08-28 on a genuinely vision-capable local model.
const BLIND = {enabled: true, model: ''};
const OFF = {enabled: false, model: 'x'};
const OK = {enabled: true, model: 'some-vl-model'};
check('agent + vision model + Odysseus has NO vision model: the ⊕ still works but '
      + 'SAYS SO before the send (the dead end we drove into)',
      attachVerdict('agent', true, BLIND).on === true
      && /Settings → Vision/.test(attachVerdict('agent', true, BLIND).why));
check('…and it names BY NAME as the condition, because that is literally Odysseus\'s '
      + 'rule (is_vision_model keyword match)',
      /BY NAME/.test(attachVerdict('agent', true, BLIND).why));
check('agent + Odysseus vision switched OFF gets its own sentence',
      /turned OFF/.test(attachVerdict('agent', true, OFF).why));
check('agent + a configured vision model: back to a clean yes, no noise',
      attachVerdict('agent', true, OK).on === true && !attachVerdict('agent', true, OK).why);
check('NO caps snapshot yet is UNKNOWN, not "misconfigured" — an unread config must '
      + 'never print a warning we cannot support',
      !attachVerdict('agent', true, null).why
      && !attachVerdict('agent', true, undefined).why);
check('the caveat is AGENT-only — it is Odysseus\'s setting, and Hermes/chat do not '
      + 'read it',
      !attachVerdict('hermes', true, BLIND).why && !attachVerdict('chat', true, BLIND).why);
check('a text-only model on the agent lane stops promising a description it cannot '
      + 'produce when no vision model is configured',
      /Settings → Vision/.test(attachVerdict('agent', false, BLIND).why)
      && /describe/.test(attachVerdict('agent', false, OK).why));
check('odyVisionCfg never invents a config (null when no snapshot)',
      /capsSnap && capsSnap\.vision/.test(grab('odyVisionCfg')));
check('…and the caps fetch repaints the ⊕ once the config is known',
      /renderCapsStrip\(\);[\s\S]{0,300}?applyVisionUi\(\)/.test(grab('ensureCapsStrip')));

console.log('\n-- the ⊕ is grey-not-hide, and never a silent no-op --');
const vis = grab('applyVisionUi');
check('applyVisionUi never hides the ⊕ on a lane or a model (btn.hidden = false)',
      /btn\.hidden\s*=\s*false/.test(vis) && !/btn\.hidden\s*=\s*!/.test(vis));
check('…it greys it with a class and states the reason as the title',
      /classList\.toggle\('off'/.test(vis) && /btn\.title\s*=\s*v\.why/.test(vis));
check('…and marks it aria-disabled rather than `disabled` (still focusable, '
      + 'still able to explain itself)',
      /aria-disabled/.test(vis) && !/btn\.disabled\s*=/.test(vis));
check('a STAGED image gets its caveat repainted on a lane switch (stage on Hermes '
      + 'with no caveat, switch to Agent, and the Odysseus warning must appear)',
      /else if \(chatPane\.attachedImage\)[\s\S]{0,120}?showAttachedImage/.test(vis));
check('a blocked ⊕ still SPEAKS when clicked (the silent-no-op class)',
      /attachNote\(v\.why\)/.test(grab('pickImage')));
check('#chat-attach.off is styled by opacity only — no colour token, so all six '
      + 'looks keep their own ink (ALL-DESIGNS)',
      /#chat-attach\.off\s*\{\s*opacity:/.test(html));
check('the ⊕ still carries BOTH design children (studio icon + editorial glyph)',
      /id="chat-attach"[\s\S]{0,400}?st-only[\s\S]{0,200}?ed-only/.test(html));

console.log('\n-- every entry point uses the same verdict --');
check('pickImage gates on attachVerdict, not on a hardcoded lane name',
      /attachVerdict\(chatPane\.mode, liveVision, odyVisionCfg\(\)\)/.test(grab('pickImage')));
// harnessNativeDrop is an assignment onto `window`, not a declaration — the Swift
// shell calls it directly for Finder drags WKWebView never forwards to the DOM.
const nativeDrop = html.slice(html.indexOf('window.harnessNativeDrop'),
                              html.indexOf('window.harnessNativeAudioDrop'));
check('the NATIVE Finder-drop path gates on attachVerdict too (it is the path a '
      + 'Mac user actually uses, and it had its own copy of the lane check)',
      /attachVerdict\(chatPane\.mode, liveVision, odyVisionCfg\(\)\)/.test(nativeDrop));
check('the drag-drop and ⌘V paste handlers gate on attachVerdict too',
      (html.match(/const v = attachVerdict\(chatPane\.mode, liveVision, odyVisionCfg\(\)\)/g) || []).length >= 4);
check('NO handler still says "images attach in Chat mode"',
      html.indexOf('attach in Chat mode') < 0);
check('the vision pill no longer claims chat-mode-only either',
      html.indexOf('vision · chat mode') < 0);
check('liveVision is initialised to null (unknown), not false',
      /let liveVision = null;/.test(html));
check('…and an absent live entry stays null rather than collapsing to false',
      /liveEntry \? \(liveEntry\.capabilities \|\| \[\]\)\.includes\('vision'\) : null/
        .test(html));

console.log('\n-- one attachment shape, three lanes --');
/* sendChat is 350 lines with comments that quote unbalanced JSON, so the brace
   matcher cannot walk it — slice it from its own header to the next declaration. */
const _sendAt = html.indexOf('async function sendChat()');
const send = html.slice(_sendAt, html.indexOf('\nfunction ', _sendAt));
check('sendChat was located for these assertions (a rename must fail loudly, not '
      + 'silently make every `not in` check below vacuous)',
      _sendAt > 0 && send.length > 2000);
check('sendChat takes the staged image on ANY lane (no mode === chat guard)',
      /const img = chatPane\.attachedImage \|\| null;/.test(send));
check('…and the Hermes body carries image + image_name like the others',
      /session_id: chatPane\.hermesSid[\s\S]{0,300}?image: img\.data, image_name: img\.name/
        .test(send));
check('…as does the Odysseus/direct body',
      /mode:chatPane\.mode[\s\S]{0,300}?image: img\.data, image_name: img\.name/.test(send));
check('the live ✕ only claims a delete on the lane that owns the bytes',
      /_lane === 'chat'[\s\S]{0,200}?liveAttachDrop/.test(send)
      && /Remove from this view/.test(send));
check('a reopened AGENT turn rehydrates from Odysseus (ody_id → the proxy route)',
      /att\.ody_id/.test(grab('addRestoredAttachment'))
      && /\/api\/ody\/attachment\//.test(grab('addRestoredAttachment')));

check('an image with NO message says why nothing was sent (all three backends '
      + 'refuse an empty message — the silent-no-op class, found by the adversarial pass)',
      /if \(!text\)\{[\s\S]{0,700}?attachNote\('add a message to send with this image'\)/
        .test(send));

console.log('\n-- stop / interrupt: every lane --');
check('Send becomes Stop on EVERY lane, not just Hermes',
      /sendPaint\('Stop'\);/.test(send) && !/sendBtn\.disabled = true;/.test(send));
check('…and a click while busy really stops the direct/agent turn',
      /else stopTurnNow\('panel stop'\)/.test(send));
check('…while the Hermes branch still additionally interrupts upstream',
      /hermesStop\('panel stop'\)/.test(send));
check('the composer is released for every lane when the turn ends',
      /sb\.disabled = false; sendPaint\('Send'\);/.test(html));

console.log('\n-- the lane note has ONE source --');
check('laneNote gives each lane its own sentence',
      laneNote('agent') !== laneNote('chat')
      && laneNote('hermes') !== laneNote('chat')
      && /Hermes/.test(laneNote('hermes')));
check('…and Hermes is never described as "plain model — no tools" (it is the lane '
      + 'with the MOST tools) — the browse-toggle used to print exactly that',
      laneNote('hermes').indexOf('no tools') < 0
      && html.indexOf("'plain model — no tools'") < 0);
check('both painters call laneNote rather than repeating the strings',
      (html.match(/laneNote\(/g) || []).length >= 3);

console.log('\n-- affordances that are composer-level, and must stay that way --');
for (const fn of ['toggleTalk', 'toggleAuto', 'toggleConv']) {
  check(fn + ' has no lane branch — audio in is one control for all three lanes',
        grab(fn).indexOf('chatPane.mode') < 0);
}
check('the mic, the audio switch and the ⊕ all live in the ONE composer row, so no '
      + 'lane can lose them by construction',
      /id="chat-inputrow"[\s\S]{0,4000}id="chat-attach"/.test(html)
      && /id="chat-inputrow"[\s\S]{0,6000}id="chat-audiosw"/.test(html));

console.log('\n-- KNOWN GAPS the audit recorded (change these WITH the table) --');
check('web search is still a hardcoded allow_web_search:true on the agent lane — '
      + 'there is no per-turn toggle in the composer yet (queued finding)',
      /allow_web_search:true/.test(send));
check('the caps strip still reads Odysseus features on every lane (queued finding: '
      + 'it is meaningless on the Hermes lane)',
      /renderCapsStrip/.test(html) && /api\/ody\/caps/.test(html));

console.log('\n-- the smooth-scroll no-op, swept --');
/* The fixed sites DOCUMENT the bug in a block comment, and that comment naturally
   contains the very string we are forbidding — so the check runs on the code with
   block comments removed. (A test that could be satisfied by deleting the
   explanation would be the wrong incentive.) */
function decomment(s){ return s.replace(/\/\*[\s\S]*?\*\//g, ''); }
check('jumpToCard no longer asks for behavior:smooth (a silent no-op in WKWebView)',
      !/behavior:\s*'smooth'/.test(decomment(grab('jumpToCard'))));
check('…and it still scrolls, with a fallback for an engine that rejects the options',
      /scrollIntoView\(\{ block: 'center' \}\)/.test(grab('jumpToCard'))
      && /scrollIntoView\(true\)/.test(grab('jumpToCard')));
check('musicScrollToCreate — the SECOND copy found by the sweep — is fixed too',
      !/behavior:\s*'smooth'/.test(decomment(grab('musicScrollToCreate')))
      && /scrollIntoView\(\{block: 'start'\}\)/.test(grab('musicScrollToCreate')));
check('NO executable behavior:smooth survives anywhere in the panel (the sweep, '
      + 'pinned: this is a proven bug class, not a one-off)',
      !/behavior:\s*['"]smooth/.test(decomment(html)));

console.log();
if (fails.length) {
  console.log(fails.length + ' FAILED:');
  for (const f of fails) console.log('  - ' + f);
  process.exit(1);
}
console.log('all lane-affordance checks passed');
