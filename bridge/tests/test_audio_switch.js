#!/usr/bin/env node
/* THE AUDIO-MODE SWITCH + THE BOUNDED COMPOSER — the fence (v1.5.26, sample's design).
 *
 * WHY THIS FILE EXISTS. Two of sample's rulings landed on the same twelve lines of the
 * composer, and both are the kind that a later "tidy-up" undoes by accident:
 *   (1) the controls live INSIDE one bounded field, in the grammar Claude / LM Studio /
 *       Unsloth share — not in a row of chips underneath it;
 *   (2) the separate `auto` and `conv` chips became ONE three-position switch, and it is
 *       a SURFACE over the existing state, not a second state machine. The moment
 *       somebody gives it its own `mode` variable, the mic light and the switch can
 *       disagree — which is the worst bug this area can have.
 *
 * WHAT IS FENCED, and the shape of each fact:
 *   1. THE STATE MACHINE, EXECUTED. renderAudioSwitch / audioModeOff / audioSwKey are
 *      lifted out of the panel and RUN against a DOM shim, over the whole nine-cell grid
 *      (three positions × the three gates). Not "the source mentions autoOn()" — "given
 *      autoOn() is true, the knob attribute says auto, aria-checked moves, and the mic
 *      button is disabled WITH A REASON".
 *   2. ZERO LOGIC FORKS. The two ends are still #chat-auto / #chat-conv with their
 *      original onclick handlers; the switch owns no persistence and no new state.
 *   3. GEOMETRY, PER DESIGN. The composer is one field and the switch is one object, in
 *      Editorial, under the icon-chrome axis, and in the studio design — with the
 *      specificity trap (which bit this slice twice) asserted from the rules themselves.
 *   4. THE HIT-TARGET ARITHMETIC, re-derived from the CSS rather than pinned as a claim.
 *
 * Run: node bridge/tests/test_audio_switch.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const sd = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];
const noC = css.replace(/\/\*[\s\S]*?\*\//g, '');
const sdNoC = sd.replace(/\/\*[\s\S]*?\*\//g, '');

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok  ' : '  FAIL ') + msg); if (!cond) fails++; }
function eq(msg, got, want) {
  const same = JSON.stringify(got) === JSON.stringify(want);
  ok(same, msg + (same ? '' : ' — got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)));
}
function rules(src) {
  const out = []; let i = 0;
  while (i < src.length) {
    const b = src.indexOf('{', i); if (b < 0) break;
    const sel = src.slice(i, b).trim();
    let d = 1, j = b + 1;
    while (j < src.length && d > 0) { if (src[j] === '{') d++; else if (src[j] === '}') d--; j++; }
    out.push({ sel, body: src.slice(b + 1, j - 1) });
    i = j;
  }
  return out;
}
const ALL = rules(noC);
const SDALL = rules(sdNoC);
const rule = sel => ALL.find(r => r.sel === sel);

// ═══════════════════════════════════════════════════════════════════════════════
// 1. THE STATE MACHINE — LIFTED OUT AND EXECUTED
// ═══════════════════════════════════════════════════════════════════════════════
console.log('1. the switch\'s state machine (extracted and executed against a DOM shim)');

// A DOM shim with exactly the surface these three functions touch. Deliberately tiny:
// a fuller fake would start hiding bugs behind its own behaviour.
function makeEl(id) {
  return {
    id, hidden: false, disabled: false, title: '', _focused: false, _clicks: 0,
    dataset: {}, attrs: {}, classes: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return this.attrs[k]; },
    classList: {
      _o: null,
      toggle(c, on) { this._o.classes[c] = !!on; },
      contains(c) { return !!this._o.classes[c]; },
    },
    focus() { this._focused = true; },
    click() { this._clicks++; },
  };
}
function makeDom() {
  const ids = ['chat-audiosw', 'chat-auto', 'chat-conv', 'chat-audio-off', 'chat-talk'];
  const els = {};
  for (const i of ids) { els[i] = makeEl(i); els[i].classList._o = els[i]; }
  return { els, getElementById: id => els[id] || null };
}

// Lift the three functions verbatim out of the panel. The slice runs from the first to
// the closing brace of the last — if that block is ever split up, this test stops
// finding it, which is the intended failure.
const A = html.indexOf('function renderAudioSwitch(){');
const B = html.indexOf('\n}', html.indexOf('function audioSwKey(e){')) + 2;
ok(A > 0 && B > A, 'the three switch functions are one contiguous block in the panel');
const SRC = html.slice(A, B);

function run(state) {
  const dom = makeDom();
  const log = [];
  const env = {
    document: dom,
    autoOn: () => state.pos === 'auto',
    convOn: () => state.pos === 'conv',
    talkRec: state.talkRec || null,
    voiceCfg: { stt_model: 'whisper-x' },
    TALK_TITLE: 'Dictate — record and transcribe into the message box',
    stopAuto: r => log.push('stopAuto:' + r),
    stopConv: r => log.push('stopConv:' + r),
  };
  dom.els['chat-auto'].hidden = !state.sttOn;
  dom.els['chat-conv'].hidden = !(state.sttOn && state.ttsOn);
  const fns = new Function('document', 'autoOn', 'convOn', 'talkRec', 'voiceCfg',
    'TALK_TITLE', 'stopAuto', 'stopConv', 'autoStarting',
    SRC + '; return { renderAudioSwitch, audioModeOff, audioSwKey };')(
      env.document, env.autoOn, env.convOn, env.talkRec, env.voiceCfg, env.TALK_TITLE,
      env.stopAuto, env.stopConv, state.pending || null);
  fns.renderAudioSwitch();     // every case below starts from a painted switch
  return { dom, log, fns, els: dom.els };
}

// (a) THE THREE POSITIONS × THE GATES — the whole grid, executed
for (const pos of ['off', 'auto', 'conv']) {
  const r = run({ pos, sttOn: true, ttsOn: true });
  eq('position ' + pos + ': the knob attribute is the position',
     r.els['chat-audiosw'].dataset.pos, pos);
  eq('…and aria-checked is true on exactly that zone', [
    r.els['chat-auto'].getAttribute('aria-checked'),
    r.els['chat-audio-off'].getAttribute('aria-checked'),
    r.els['chat-conv'].getAttribute('aria-checked'),
  ], [String(pos === 'auto'), String(pos === 'off'), String(pos === 'conv')]);
  ok(r.els['chat-audiosw'].hidden === false,
     '…and the switch is on screen while at least one end is available');
}
// (b) THE GATES ARE THE ENDS' OWN — the switch derives, it never decides
{
  const none = run({ pos: 'off', sttOn: false, ttsOn: false });
  ok(none.els['chat-audiosw'].hidden === true,
     'no speech-to-text default → NO SWITCH AT ALL, exactly as there were no chips '
     + 'before: the visibility is derived from the two ends\' own `hidden` gates, not '
     + 'decided a second time here');
  const sttOnly = run({ pos: 'off', sttOn: true, ttsOn: false });
  ok(sttOnly.els['chat-audiosw'].hidden === false && sttOnly.els['chat-conv'].hidden === true,
     '…and STT without TTS shows the switch with only the conversation end missing '
     + '(hands-free dictation needs no voice to speak back)');
}
// (c) GREY, NOT HIDE, WITH THE REASON — both directions of the exclusion
{
  const off = run({ pos: 'off', sttOn: true, ttsOn: true });
  ok(off.els['chat-talk'].disabled === false,
     'with the switch OFF the mic button is live');
  ok(/whisper-x/.test(off.els['chat-talk'].title),
     '…and its title is the resting one the renderer owns (the model + what it does)');
  for (const pos of ['auto', 'conv']) {
    const r = run({ pos, sttOn: true, ttsOn: true });
    ok(r.els['chat-talk'].disabled === true,
       'with the switch on ' + pos + ' the mic button is DISABLED, not hidden');
    ok(/set the audio switch to off first/.test(r.els['chat-talk'].title),
       '…and its title says WHY and what to do about it (grey-not-hide is only honest '
       + 'if the reason travels with the grey)');
  }
  const rec = run({ pos: 'off', sttOn: true, ttsOn: true, talkRec: { live: true } });
  ok(rec.els['chat-auto'].disabled && rec.els['chat-conv'].disabled,
     'and SYMMETRICALLY: while a push-to-talk recording is live, both ends grey out — '
     + 'starting a hands-free mode would silently discard that recording');
  ok(/discard it/.test(rec.els['chat-auto'].title), '…with that reason in the title');
  ok(rec.els['chat-audio-off'].disabled === false,
     '…and the MIDDLE stays live: "off" is never a destructive answer');
  ok(rec.els['chat-talk'].disabled === false,
     '…and a live recorder\'s own stop button is never disabled — that would trap the '
     + 'microphone open, which is the worst bug this area can have');
}
// (d) THE MIDDLE — it turns things off, and it is never a silent no-op
{
  const a = run({ pos: 'auto', sttOn: true, ttsOn: true });
  a.fns.audioModeOff();
  eq('the middle stops hands-free dictation through the EXISTING teardown', a.log,
     ['stopAuto:the audio switch was set to off']);
  const c = run({ pos: 'conv', sttOn: true, ttsOn: true });
  c.fns.audioModeOff();
  eq('…and conversation mode through ITS existing teardown', c.log,
     ['stopConv:the audio switch was set to off']);
  const o = run({ pos: 'off', sttOn: true, ttsOn: true });
  o.fns.audioModeOff();
  eq('…and from off it tears nothing down', o.log, []);
  ok(o.els['chat-audiosw'].dataset.pos === 'off',
     '…but still REPAINTS rather than doing nothing at all');
}
for (const pending of ['auto', 'conv']) {
  const r = run({pos:'off', sttOn:true, ttsOn:true, pending});
  r.fns.audioModeOff();
  eq('Off cancels pending ' + pending + ' microphone permission', r.log,
     [(pending === 'conv' ? 'stopConv:' : 'stopAuto:') + 'the audio switch was set to off']);
}
// (e) THE KEYBOARD — a radio group moves and selects in one action, and skips dead zones
{
  const mk = (pos, from, key, gates) => {
    const r = run(Object.assign({ pos, sttOn: true, ttsOn: true }, gates || {}));
    r.fns.renderAudioSwitch();
    r.fns.audioSwKey({ key, currentTarget: r.els[from], preventDefault() {} });
    return r;
  };
  const down = mk('off', 'chat-audio-off', 'ArrowDown');
  ok(down.els['chat-conv']._focused && down.els['chat-conv']._clicks === 1,
     '↓ from the middle focuses AND engages the conversation end (one action, as a '
     + 'radio group behaves — not focus-then-space)');
  const up = mk('off', 'chat-audio-off', 'ArrowUp');
  ok(up.els['chat-auto']._focused && up.els['chat-auto']._clicks === 1,
     '↑ from the middle engages hands-free');
  const home = mk('conv', 'chat-conv', 'Home');
  ok(home.els['chat-auto']._clicks === 1, 'Home jumps to the first live zone');
  const end = mk('auto', 'chat-auto', 'End');
  ok(end.els['chat-conv']._clicks === 1, 'End jumps to the last live zone');
  const noTts = mk('off', 'chat-audio-off', 'ArrowDown', { ttsOn: false });
  ok(noTts.els['chat-conv']._clicks === 0 && noTts.els['chat-auto']._clicks === 1,
     'a zone its own gate has hidden is SKIPPED, not focused — you cannot arrow into a '
     + 'conversation position that does not exist on this machine');
  const other = mk('off', 'chat-audio-off', 'a');
  ok(other.els['chat-auto']._clicks === 0 && other.els['chat-conv']._clicks === 0,
     'and every other key is left entirely alone (typing is not navigation)');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. ZERO LOGIC FORKS — the switch is a SURFACE over the state that already existed
// ═══════════════════════════════════════════════════════════════════════════════
console.log('2. the switch owns no state of its own');
{
  ok(/id="chat-auto"[^>]*onclick="toggleAuto\(\)"/.test(html)
     && /id="chat-conv"[^>]*onclick="toggleConv\(\)"/.test(html),
     'the two ends still call the ORIGINAL togglers — the pill is a control surface, '
     + 'not a second state machine (and that is why clicking an engaged end turns it '
     + 'off: toggleAuto/toggleConv always did)');
  ok(/id="chat-audio-off"[^>]*onclick="audioModeOff\(\)"/.test(html),
     '…and the only genuinely new affordance is the middle');
  ok(!/audioSwitchState|swMode|audioMode\s*=/.test(SRC),
     'renderAudioSwitch declares NO mode variable of its own — autoOn() / convOn() stay '
     + 'the single source of truth');
  ok(!/localStorage/.test(SRC),
     '…and persists NOTHING NEW: the old chips persisted nothing, so neither does this '
     + '(sample\'s instruction, and the safe default — a hands-free mic that survives a '
     + 'reload would start listening before anybody asked)');
  ok(/renderAudioSwitch\(\);   \/\/ v1\.5\.26/.test(html),
     'it is painted from the EXISTING renderers rather than from new call sites');
  const n = (html.match(/renderAudioSwitch\(\)/g) || []).length;
  ok(n >= 4 && n <= 8, 'and from a small, countable number of places (' + n + ')');
  // the mic keeps push-to-talk, per sample's split
  ok(/id="chat-talk"[^>]*onclick="toggleTalk\(\)"/.test(html),
     '`talk` (push-to-talk) stays on the mic button and did not move onto the switch — '
     + 'sample\'s split: the switch is for the two HANDS-FREE modes');
  ok(/renderAutoBtn\(\); renderConvBtn\(\);/.test(
       html.slice(html.indexOf('async function startTalk()'),
                  html.indexOf('function stopTalk(cancel)'))),
     '…and starting a recording repaints the ends THROUGH their renderers, from inside '
     + 'the async function — a repaint at the call site would run before talkRec exists '
     + 'and grey nothing');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. THE COMPOSER IS ONE BOUNDED FIELD — in Editorial, and still in studio
// ═══════════════════════════════════════════════════════════════════════════════
console.log('3. the bounded composer, per design');
{
  const row = rule('#chat-inputrow');
  ok(!!row, 'Editorial\'s composer row has its own rule');
  ok(/background:var\(--card\)/.test(row.body) && /border:1px solid var\(--line2\)/.test(row.body)
     && /border-radius:16px/.test(row.body),
     '…and it is THE FIELD: it carries the ground, the border and the radius');
  ok(!!rule('#chat-inputrow:focus-within'),
     '…with focus on the SHELL, so the whole composer lights up as one object');
  const inp = rule('#chat-input');
  ok(/background:transparent/.test(inp.body) && /border:0/.test(inp.body),
     '…and the textarea inside it is transparent and borderless');
  const foc = rule('#chat-input:focus');
  ok(foc && /border:0/.test(foc.body),
     '…and does NOT draw a second ring on focus (a box inside the box is the exact look '
     + 'this change removes)');
  // the order sample asked for: textarea → mic → SEND → switch, all inside the field
  const ix = s => html.indexOf(s);
  ok(ix('id="chat-input"') < ix('id="chat-talk"')
     && ix('id="chat-talk"') < ix('id="chat-send"')
     && ix('id="chat-send"') < ix('id="chat-audiosw"'),
     'the order INSIDE the field is textarea → dictate → SEND → the switch far right');
  ok(ix('id="chat-audiosw"') < ix('</div>\n          </div>'),
     '…and every one of them is inside #chat-inputrow, not in a row beneath it');
  // studio already had this structure; adopting it must not have regressed it
  ok(/#chat-inputrow \{[\s\S]{0,300}border-radius:var\(--sd-r-xl\)/.test(sdNoC)
     && /#chat-inputrow:focus-within/.test(sdNoC),
     'the studio design\'s own bounded composer is untouched — Editorial adopted ITS '
     + 'structure, the borrowing did not run the other way');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. THE SWITCH'S GEOMETRY — one object, and the hit-target arithmetic re-derived
// ═══════════════════════════════════════════════════════════════════════════════
console.log('4. the switch\'s geometry');
const HIT = 44;
{
  const box = rule('#chat-audiosw');
  ok(!!box, 'the switch has its own rule');
  const w = parseInt((box.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  const zone = rule('#chat-audiosw .asw-zone');
  const h = parseInt((zone.body.match(/height:\s*(\d+)px/) || [])[1], 10);
  ok(/flex-direction:column/.test(box.body), 'it is VERTICAL, as sample drew it');
  // 66, not 60 — and the 6px is a LIVE FINDING, not a preference. At 60 the track left a
  // 56px content box and `listening` measures 56.6px, so conversation mode's live phase
  // was clipped by 3px (scrollWidth 59 vs clientWidth 56). A state word that is silently
  // cut off is precisely the failure "a state that becomes invisible is worse than no
  // icon at all" is about, so the number is pinned exactly rather than left as a range.
  ok(w === 66, 'the track is ' + w + 'px wide — set by the widest thing a zone must ever '
     + 'SAY (`listening`, measured at 56.6px live), not by taste');
  // the arithmetic, derived rather than claimed
  const area = w * h;
  ok(area === 1188, 'each zone is therefore ' + w + ' × ' + h + ' = ' + area + 'px²');
  ok(area < HIT * HIT,
     '…which is UNDER the ' + HIT + '×' + HIT + ' = ' + (HIT * HIT) + 'px² floor, and is '
     + 'stated here rather than buried: this is a flagged tradeoff, not an oversight');
  ok(area > 600,
     '…but it is an IMPROVEMENT on what it replaced: the `auto` and `conv` chips were '
     + '9.5px labels at 3px/6px padding, ~34 × 18 ≈ 612px² each. The control got bigger '
     + 'and there are now TWO ways out of an engaged mode (the engaged zone, or the '
     + 'middle), so the smallest zone is never the only way back.');
  // the knob is CSS, driven by the attribute the renderer sets — no JS geometry
  const knob = rule('#chat-audiosw::after');
  ok(!!knob && /position:absolute/.test(knob.body),
     'the knob is ONE pseudo-element, not an extra node the renderer has to keep in sync');
  const kh = parseInt((knob.body.match(/height:\s*(\d+)px/) || [])[1], 10);
  ok(kh === h, '…exactly one zone tall (' + kh + 'px), so it can never sit between two '
     + 'positions');
  const moves = ALL.filter(r => /^#chat-audiosw\[data-pos=/.test(r.sel) && /::after/.test(r.sel));
  const ty = moves.map(r => (r.body.match(/translateY\((\d+)px\)/) || [])[1])
                  .filter(Boolean).map(Number).sort((a, b) => a - b);
  eq('…and its three positions are 0 / one zone / two zones, derived from the same ' + h
     + 'px', ty, [h, 2 * h]);
  ok(!/style\.(top|transform)/.test(SRC),
     '…and NO JavaScript writes the knob\'s position: the renderer sets one attribute '
     + 'and CSS does the rest, so the knob cannot desynchronise from the state');
  ok(/transition:transform/.test(knob.body), '…and it slides, so the position reads as '
     + 'a movement rather than a repaint');
}
// the labels, and why they are labels
{
  ok(/#chat-audiosw \.st-only \{ display:none; \}/.test(noC)
     && /#chat-audiosw \.ed-only \{ display:inline; \}/.test(noC),
     'the switch\'s positions are LABELLED in every design — the dual-child contract is '
     + 'untouched (both spans are still in the markup, every renderer stays mode-blind), '
     + 'but inside the switch the CSS always picks the WORD: three abstract glyphs would '
     + 'be a puzzle, and no icon can carry conversation mode\'s live phase');
  ok(/#chat-audiosw \.talk-dot \{ display:none; \}/.test(noC),
     '…and the ●/▸ dot is hidden inside the switch: `● listening` does not fit a zone, '
     + 'and a gold dot ON the gold knob would be invisible anyway');
  ok(!/#chat-auto\.on \.talk-dot/.test(noC),
     '…and the rule that used to colour that dot is DELETED, not left pointing at a '
     + 'display:none element (dead CSS is the anti-pattern these fences exist to catch)');
  ok(/#chat-audiosw\[data-pos="auto"\] \.asw-top/.test(noC)
     && /color:var\(--on-accent\)/.test(rule('#chat-audiosw[data-pos="auto"] .asw-top,\n  #chat-audiosw[data-pos="conv"] .asw-bot').body),
     'the engaged label takes --on-accent, the SAME token every other gold fill in '
     + 'Editorial uses (v1.5.24\'s fourth sighting of a hardcoded near-black was exactly '
     + 'this class of site)');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. THE SPECIFICITY TRAP — both icon axes had to be told about the switch
// ═══════════════════════════════════════════════════════════════════════════════
console.log('5. the specificity restatements (the trap that bit this slice twice)');
{
  // The base switch rule is (1,1,0). A rule of the form `html[data-*] #chat-auto` is
  // (1,1,1) and WINS. So the two ends had to LEAVE both icon-axis lists, or they would
  // have been round 30px buttons stacked inside the track with the middle zone — which
  // neither axis had ever heard of — keeping Editorial's look between them.
  for (const [name, src] of [['the icon-chrome axis', noC], ['the studio design', sdNoC]]) {
    const composer = src.split('\n').filter(l => /#chat-(auto|conv)\b/.test(l));
    eq(name + ' no longer addresses #chat-auto / #chat-conv by id at all', composer, []);
  }
  ok(/html\[data-chrome="studio"\] #chat-audiosw \.asw-zone/.test(noC),
     'the icon-chrome axis restates the SWITCH instead (its zone typography)');
  ok(/html\[data-design="studio"\] #chat-audiosw \.asw-zone/.test(sdNoC),
     '…and so does the studio design');
  const sz = SDALL.find(r => r.sel === 'html[data-design="studio"] #chat-audiosw .asw-zone');
  ok(sz && /letter-spacing:normal/.test(sz.body) && /text-transform:none/.test(sz.body),
     '…in studio\'s own voice: sentence case at normal tracking (Editorial\'s tracked '
     + 'mono caps are its signature, and are what impeccable\'s wide-tracking rules '
     + 'are about)');
  const fs2 = parseFloat((sz.body.match(/font-size:\s*([\d.]+)px/) || [])[1]);
  ok(fs2 >= 11, '…and at ' + fs2 + 'px, studio\'s own 11px floor (Editorial\'s zones are '
     + '9.5px, the one argued exception fenced in test_editorial_debt.js §2)');
  // GEOMETRY IS NOT RESTATED — one object in both designs, the sessions-rail lesson
  const sbox = SDALL.find(r => r.sel === 'html[data-design="studio"] #chat-audiosw');
  ok(sbox && !/width:/.test(sbox.body) && !/flex-direction/.test(sbox.body),
     'and neither axis restates the switch\'s GEOMETRY — it is the same object in every '
     + 'design, exactly as the collapsed sessions rail is. A per-design geometry is how '
     + 'the studio slice once shipped a 22×14px reopen target.');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. ACCESSIBILITY — it is a radio group, and it says so
// ═══════════════════════════════════════════════════════════════════════════════
console.log('6. it is a radio group, semantically');
{
  ok(/<div id="chat-audiosw" role="radiogroup" aria-label="Audio mode"/.test(html),
     'the container is a radiogroup with a name');
  for (const id of ['chat-auto', 'chat-audio-off', 'chat-conv']) {
    ok(new RegExp('id="' + id + '" role="radio" aria-checked=').test(html),
       '#' + id + ' is a radio with an initial aria-checked');
    ok(new RegExp('id="' + id + '"[\\s\\S]{0,400}?aria-label="').test(html),
       '…and carries its own accessible name');
    ok(new RegExp('id="' + id + '"[\\s\\S]{0,300}?title="').test(html),
       '…and a hover title, so the read survives for the pointer too (sample\'s ask)');
  }
  ok((html.match(/class="[^"]*asw-zone[^"]*" id="chat-(auto|conv)"/g) || []).length === 2
     && /class="asw-zone asw-mid" id="chat-audio-off"/.test(html),
     'every zone is a real <button>, so it is tab-reachable with no tabindex bookkeeping');
  ok((html.match(/onkeydown="audioSwKey\(event\)"/g) || []).length === 3,
     '…and all three carry the arrow-key handler');
}

console.log('');
console.log(fails ? (fails + ' failure(s) of ' + checks)
                  : ('audio switch + composer: ' + checks + ' checks passed'));
process.exit(fails ? 1 : 0);
