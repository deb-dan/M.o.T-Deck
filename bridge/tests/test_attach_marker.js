/* Panel-side unit test for the image-attachment marker helpers.
 *
 * Both functions are EXTRACTED from bridge/panel/index.html by name (the pattern
 * test_msg_actions.py established for statsLine, reused by test_audio_rows.js and
 * test_speak_text.js) rather than copied, so a rename or an edit in the panel trips
 * this test instead of silently drifting from it.
 *
 *   stripAttachMarker(s)          what the user bubble DISPLAYS when a thumbnail renders
 *   lastAttachmentId(hist, text)  which sidecar row a live ✕ deletes
 *
 * The marker itself is single-sourced in bridge/app.py (ATTACH_MARKER) and duplicated
 * in the panel by necessity — the string literal is asserted here so a bridge-side
 * change that isn't mirrored fails loudly.
 *
 * Run: node bridge/tests/test_attach_marker.js   (from repo root)
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

// Brace-matched extraction of `function <name>(...) { ... }` from the panel source.
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

const NAMES = ['stripAttachMarker', 'lastAttachmentId'];
const P = new Function(NAMES.map(grab).join('\n') + '\nreturn {' + NAMES.join(',') + '};')();

// ── stripAttachMarker: the trailing marker only ────────────────────────────────
check('the persisted "\\n[image attached]" form is stripped',
      P.stripAttachMarker('look at this\n[image attached]') === 'look at this');
check('a space-separated marker is stripped too',
      P.stripAttachMarker('look at this [image attached]') === 'look at this');
check('a CRLF-separated marker is stripped',
      P.stripAttachMarker('look at this\r\n[image attached]') === 'look at this');
check('a tab-separated marker is stripped',
      P.stripAttachMarker('look at this\t[image attached]') === 'look at this');
check('a bare marker leaves an empty bubble',
      P.stripAttachMarker('[image attached]') === '');
check('the marker is NOT stripped mid-sentence (only a trailing one is ours)',
      P.stripAttachMarker('the [image attached] note explains it')
        === 'the [image attached] note explains it');
check('a marker followed by more text is left alone',
      P.stripAttachMarker('a\n[image attached]\nb') === 'a\n[image attached]\nb');
check('only ONE marker is removed (a doubled one keeps the first)',
      P.stripAttachMarker('x\n[image attached]\n[image attached]')
        === 'x\n[image attached]');
check('text with no marker is untouched',
      P.stripAttachMarker('what is in this picture?') === 'what is in this picture?');
check('a similar-but-different marker is not matched',
      P.stripAttachMarker('done [image attached!]') === 'done [image attached!]');
check('interior whitespace/newlines are preserved (not a trim)',
      P.stripAttachMarker('line one\nline two\n[image attached]') === 'line one\nline two');
check('trailing whitespace after the marker means it is not trailing',
      P.stripAttachMarker('x\n[image attached] ') === 'x\n[image attached] ');

// defensive: this runs on every reopened transcript row
check('null → empty string', P.stripAttachMarker(null) === '');
check('undefined → empty string', P.stripAttachMarker(undefined) === '');
check('a non-string is coerced', P.stripAttachMarker(42) === '42');
check('empty stays empty', P.stripAttachMarker('') === '');

// the panel's copy of the marker must still match the bridge's ATTACH_MARKER
// ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28):
// bridge/app.py is a facade over bridge/core/*.py + bridge/routers/*.py, so the
// cross-file pins below read _appsrc.js's assembled view of the whole app layer.
const appPy = require('./_appsrc.js').appSource();
check('bridge ATTACH_MARKER is still "\\n[image attached]"',
      /ATTACH_MARKER\s*=\s*"\\n\[image attached\]"/.test(appPy));
check('the bridge still appends that exact marker when persisting an image turn',
      appPy.indexOf('"\\n[image attached]" if image') >= 0);

// ── lastAttachmentId: which sidecar row the live ✕ removes ─────────────────────
const HIST = [
  { role: 'user',      content: 'first question\n[image attached]', attachment: {id: 11, name: 'a.png'} },
  { role: 'assistant', content: 'first answer' },
  { role: 'user',      content: 'second question\n[image attached]', attachment: {id: 22, name: 'b.png'} },
  { role: 'assistant', content: 'second answer' },
];
check('the matching user turn wins, not merely the newest',
      P.lastAttachmentId(HIST, 'first question') === 11);
check('the newest matching turn is found',
      P.lastAttachmentId(HIST, 'second question') === 22);
check('the sent text (marker-free) matches the stored text (marker present)',
      P.lastAttachmentId(HIST, '  second question  ') === 22);
check('an unmatched question never authorizes deleting another attachment',
      P.lastAttachmentId(HIST, 'text the server rewrote') === null);
check('duplicate texts resolve to the newest of the duplicates',
      P.lastAttachmentId([
        { role: 'user', content: 'same\n[image attached]', attachment: {id: 1} },
        { role: 'user', content: 'same\n[image attached]', attachment: {id: 2} },
      ], 'same') === 2);
check('user rows WITHOUT an attachment are ignored',
      P.lastAttachmentId([
        { role: 'user', content: 'second question' },
        { role: 'user', content: 'first question\n[image attached]', attachment: {id: 11} },
      ], 'second question') === null);
check('assistant rows are never considered',
      P.lastAttachmentId([
        { role: 'assistant', content: 'hi', attachment: {id: 99} },
      ], 'hi') === null);
check('no attachments anywhere → null (caller retries)',
      P.lastAttachmentId([{ role: 'user', content: 'hi' }], 'hi') === null);
check('an empty history → null', P.lastAttachmentId([], 'hi') === null);
check('a missing history is not an error', P.lastAttachmentId(undefined, 'hi') === null);
check('null rows are skipped', P.lastAttachmentId([null, undefined], 'hi') === null);
check('an attachment with a null id is not usable',
      P.lastAttachmentId([{ role: 'user', content: 'hi', attachment: {id: null} }], 'hi') === null);
check('id 0 is a legitimate id (never treated as missing)',
      P.lastAttachmentId([{ role: 'user', content: 'hi', attachment: {id: 0} }], 'hi') === 0);
check('a missing question does not borrow a different image',
      P.lastAttachmentId(HIST, null) === null);
check('the history array is not mutated',
      HIST.length === 4 && HIST[0].attachment.id === 11);

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
