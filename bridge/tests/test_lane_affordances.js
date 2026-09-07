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
 *   lane status     one capability summary or one transient notice, never both
 *
 * Run: node bridge/tests/test_lane_affordances.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const turnStream = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'turn-stream.js'), 'utf8');
const sd = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8');

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

const src = grab('attachVerdict');
// eslint-disable-next-line no-new-func
const mod = new Function(src + '; return {attachVerdict};')();
const { attachVerdict } = mod;

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
// ⚠️ v1.5.32 REWROTE THIS BLOCK ON PURPOSE. v1.5.28 could only WARN about the
// unset `vision_model`; the bridge now FIXES it (pre-caption + evidence-gated
// auto-wire — bridge/routers/ody.py ody_vision_prepare), so warning about it
// would be crying wolf over a problem we just solved. What must survive is the
// HONESTY: the agent answers from a DESCRIPTION, and that is a NOTE, not a
// warning — `why` greys the ⊕ and means "act on this", `note` never does.
check('agent + a vision-capable model + Odysseus with NO vision model set: NO warning '
      + 'any more — the bridge wires this itself (v1.5.32, the cry-wolf fix)',
      attachVerdict('agent', true, BLIND).on === true
      && !attachVerdict('agent', true, BLIND).why);
check('…but the honest note stands: the loaded vision model reads it FOR the agent',
      /reads this image/.test(attachVerdict('agent', true, BLIND).note || ''));
check('WARN-ONCE: a verdict is never BOTH a warning and a note (one line, or none)',
      [['chat', true, BLIND], ['agent', true, BLIND], ['agent', true, OFF],
       ['agent', false, BLIND], ['agent', null, OK], ['hermes', false, OK]]
        .every(a => { const v = attachVerdict(a[0], a[1], a[2]);
                      return !(v.why && v.note); }));
check('agent + Odysseus vision switched OFF still WARNS — nothing on our side can '
      + 'fix a disabled attachment path (upstream skips it entirely)',
      /turned OFF/.test(attachVerdict('agent', true, OFF).why));
check('agent + a configured vision model: a clean yes, still with the note',
      attachVerdict('agent', true, OK).on === true
      && !attachVerdict('agent', true, OK).why
      && !!attachVerdict('agent', true, OK).note);
check('NO caps snapshot yet is UNKNOWN, not "misconfigured" — an unread config must '
      + 'never print a warning we cannot support',
      !attachVerdict('agent', true, null).why
      && !attachVerdict('agent', true, undefined).why);
check('the note is AGENT-only — chat sends the pixels itself, Hermes has its own path',
      !attachVerdict('hermes', true, BLIND).note
      && !attachVerdict('chat', true, BLIND).note
      && !attachVerdict('hermes', true, BLIND).why
      && !attachVerdict('chat', true, BLIND).why);
check('a text-only model on the agent lane with nothing configured anywhere still '
      + 'says the truth: the agent will tell you it cannot see this',
      /can't see this image/.test(attachVerdict('agent', false, BLIND).why)
      && /describe/.test(attachVerdict('agent', false, OK).why));
// The chip renders exactly one of the two lines, and a NOTE must not grey the ⊕.
const staged = grab('showAttachedImage');
check('the chip renders the warning OR the note, in their own classes',
      /v\.why \|\| v\.note/.test(staged) && /'anote' : 'ainfo'/.test(staged));
check('…and a document-capable lane stays usable when only its image path is refused',
      /const filesWork = chatPane\.mode !== 'chat'/.test(grab('applyVisionUi'))
      && /const usable = v\.on \|\| filesWork/.test(grab('applyVisionUi')));
check('…and .ainfo is a real, themed class rather than an inline colour (ALL-DESIGNS)',
      /#chat-attachstrip \.ainfo \{ color:var\(--faint\); \}/.test(html));

// THE ANTI-LIE LINE: the turn itself says how the model got at the picture.
const visLine = turnStream.slice(turnStream.indexOf("j.type === 'vision'"),
                                 turnStream.indexOf("j.type === 'vision'") + 1400);
check('a `vision` stream event renders a statusline (the turn states its provenance)',
      /className = 'statusline'/.test(visLine));
check('…a PRE-CAPTIONED image is never presented as directly seen',
      /not from the picture/.test(visLine));
check('…a NATIVE read says so instead of borrowing the description wording',
      /reads this image\s*'\s*\n?\s*\+ 'directly|reads this image[\s\S]{0,40}directly/.test(visLine));
check('…a failed/absent vision pass warns rather than going quiet',
      /was not described here/.test(visLine));
check('…and it is drawn ONCE per turn, not per stream frame',
      /holder\._visionLine/.test(visLine));

check('odyVisionCfg never invents a config (null when no snapshot)',
      /capsSnap && capsSnap\.vision/.test(grab('odyVisionCfg')));
check('…and the caps fetch repaints the ⊕ once the config is known',
      /renderCapsStrip\(\);[\s\S]{0,300}?applyVisionUi\(\)/.test(grab('ensureCapsStrip')));

console.log('\n-- the ⊕ is grey-not-hide, and never a silent no-op --');
const vis = grab('applyVisionUi');
check('applyVisionUi never hides the ⊕ on a lane or a model (btn.hidden = false)',
      /btn\.hidden\s*=\s*false/.test(vis) && !/btn\.hidden\s*=\s*!/.test(vis));
check('…it greys only when neither images nor documents can work, and states why',
      /classList\.toggle\('off', !usable\)/.test(vis)
      && /Supported text, code and PDF files still work/.test(vis));
check('…and marks it aria-disabled rather than `disabled` (still focusable, '
      + 'still able to explain itself)',
      /aria-disabled/.test(vis) && /usable \? 'false' : 'true'/.test(vis)
      && !/btn\.disabled\s*=/.test(vis));
check('a STAGED image gets its caveat repainted on a lane switch (stage on Hermes '
      + 'with no caveat, switch to Agent, and the Odysseus warning must appear)',
      /else if \(chatPane\.attachedImage\)[\s\S]{0,260}?showAttachedImage/.test(vis));
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
// motdeckNativeDrop is an assignment onto `window`, not a declaration — the Swift
// shell calls it directly for Finder drags WKWebView never forwards to the DOM.
const nativeDrop = html.slice(html.indexOf('window.motdeckNativeDrop'),
                              html.indexOf('window.motdeckNativeAudioDrop'));
check('the NATIVE Finder-drop path gates on attachVerdict too (it is the path a '
      + 'Mac user actually uses, and it had its own copy of the lane check)',
      /attachVerdict\(chatPane\.mode, liveVision, odyVisionCfg\(\)\)/.test(nativeDrop));
check('the drag-drop and ⌘V paste handlers use the shared file/image classifier',
      (html.match(/acceptImageFile\(file\)/g) || []).length >= 2
      && /if \(f\) acceptImageFile\(f\)/.test(html));
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
check('the shared payload still carries image + image_name for picture attachments',
      /img\.kind === 'file'[\s\S]{0,180}?image:img\.data, image_name:img\.name/.test(send));
check('…and BOTH Hermes and Odysseus\/direct bodies receive that same payload',
      (send.match(/\.\.\.attachPayload/g) || []).length === 2);
check('the live ✕ only claims a delete on the lane that owns the bytes',
      /_lane === 'chat'[\s\S]{0,200}?liveAttachDrop/.test(send)
      && /Remove from this view/.test(send));
check('a reopened AGENT turn rehydrates from Odysseus (ody_id → the proxy route)',
      /att\.ody_id/.test(grab('addRestoredAttachment'))
      && /\/api\/ody\/attachment\//.test(grab('addRestoredAttachment')));

check('an attachment with NO message says why nothing was sent (all three backends '
      + 'refuse an empty message — the silent-no-op class, found by the adversarial pass)',
      /if \(!text\)\{[\s\S]{0,700}?attachNote\('add a message to send with this attachment'\)/
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

console.log('\n-- affordances that are composer-level, and must stay that way --');
for (const fn of ['toggleTalk', 'toggleAuto', 'toggleConv']) {
  check(fn + ' has no lane branch — audio in is one control for all three lanes',
        grab(fn).indexOf('chatPane.mode') < 0);
}
check('the mic, the audio switch and the ⊕ all live in the ONE composer row, so no '
      + 'lane can lose them by construction',
      /id="chat-inputrow"[\s\S]{0,4000}id="chat-attach"/.test(html)
      && /id="chat-inputrow"[\s\S]{0,6000}id="chat-audiosw"/.test(html));

console.log('\n-- lane-truthfulness fences --');
check('web search is still a hardcoded allow_web_search:true on the agent lane — '
      + 'there is no per-turn toggle in the composer yet (queued finding)',
      /allow_web_search:true/.test(send));
eval(grab('capsStripText'));
const capFixture = {features:{web_search:true, deep_research:false, memory:true},
                    builtin_tools:[{enabled:true},{enabled:false}]};
check('only Agent reports Odysseus capabilities',
      /web ✓/.test(capsStripText('agent', capFixture))
      && !/web|research|memory/.test(capsStripText('chat', capFixture))
      && !/web|research|memory/.test(capsStripText('hermes', capFixture)));
check('Chat names its real direct-runner boundary',
      capsStripText('chat', capFixture) === 'direct chat · runner only');
check('Hermes names its own tool/skill surface',
      capsStripText('hermes', capFixture) === 'Hermes · tools + skills');
check('Browse state is added only to the lanes that can use it',
      /browser on/.test(capsStripText('agent', capFixture, true))
      && /browser on/.test(capsStripText('hermes', capFixture, true))
      && !/browser/.test(capsStripText('chat', capFixture, true)));
check('an unavailable Odysseus snapshot is stated only on Agent',
      /unavailable/.test(capsStripText('agent', null)));
check('a lane switch repaints the capability strip', /renderCapsStrip\(\)/.test(grab('setMode')));
check('a lane switch clears stale progress/error notices before repainting',
      /chatNotice\(''\)/.test(grab('setMode')));

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


console.log('\n-- THE COMPOSER IS ONE CONTROL ROW, NOT FOUR OBJECTS IN A BOX (Debi, 2026-08-29) --');
/* Her words on the non-Studio looks: "the plus button and the others though, they feel
   like they're outside the box… like in lm studio which doesn't demarcate it". v1.5.26
   put the controls INSIDE the field but left each one wearing its own outline, so the
   row read as four bordered objects inside a fifth. These pins hold the answer: the
   quiet controls are ink, Send is the single filled anchor, and the audio switch keeps
   its GEOMETRY while losing its edge. */
function rule(sel){
  const css = html.split('<style>')[1].split('</style>')[0];
  const at = css.indexOf('\n  ' + sel + ' {');
  if (at < 0) return '';
  return css.slice(at, css.indexOf('}', at));
}
check('⊕ is ink inside the field: no ground and no outline of its own',
      /border-color:transparent/.test(rule('#chat-attach.chip'))
      && /background:transparent/.test(rule('#chat-attach.chip')));
check('● talk likewise — it was the second outline in the row',
      /border-color:transparent/.test(rule('#chat-talk')));
check('…and both still get an affordance ON HOVER, so quiet is not invisible',
      /#chat-attach\.chip:hover \{[^}]*border-color:var\(--gold\)/.test(html)
      && /#chat-send:hover, #chat-talk:hover \{ border-color:var\(--gold\)/.test(html));
check('Send stays the ONE filled accent control (a control row with no anchor is the '
      + 'opposite failure)', /button\.primary \{ background:var\(--cream\)/.test(html));
check('the audio switch loses its ground and its edge…',
      /background:transparent/.test(rule('#chat-audiosw'))
      && /border:1px solid transparent/.test(rule('#chat-audiosw')));
check('…but its border is made TRANSPARENT, not deleted, so the 66px track and the '
      + '18px zones test_audio_switch.js pins do not move',
      /width:66px/.test(rule('#chat-audiosw'))
      && !/border:0/.test(rule('#chat-audiosw')));
check('…and the knob still paints in every position, so the state signal survives the '
      + 'un-drawing', /#chat-audiosw::after \{ content:''/.test(html));
/* "both sides space needs to shrink by a 3rd" — the row's flex gap and its right
   padding are 8px each, and a flex gap cannot be set per item, so the pill takes 3px
   off each side. Measured live afterwards: 5px to Send, 6px to the field's edge. */
check('the pill gives back ~a third of the space on each side, and the text box takes it',
      /margin-left:-3px; margin-right:-3px/.test(rule('#chat-audiosw'))
      && /#chat-input \{ flex:1/.test(html));
check('studio restates the pair for its OWN 5/7 numbers rather than inheriting -3',
      /margin-left:-2px; margin-right:-2px/.test(sd));


console.log();
if (fails.length) {
  console.log(fails.length + ' FAILED:');
  for (const f of fails) console.log('  - ' + f);
  process.exit(1);
}
console.log('all lane-affordance checks passed');
