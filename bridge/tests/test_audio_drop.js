/* Wiring test for the cross-app voice drop (Fable split-screen spec, Phase 2) and
 * the split-view shell (Phase 1).
 *
 * There is no swiftc in the sandbox and the drop path cannot be exercised headlessly
 * (it starts in AppKit and ends at a fetch), so what IS pinned here is the wiring:
 * the handler exists under the name the Swift shell calls, it posts to the EXISTING
 * library/save endpoint, and it does NOT auto-pin — a drop is an import, not a choice
 * about which voice a model speaks in. Those three facts are the whole contract.
 *
 * Run: node bridge/tests/test_audio_drop.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const swift = fs.readFileSync(path.join(ROOT, 'app', 'main.swift'), 'utf8');

let fails = [];
function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + name);
  if (!cond) fails.push(name);
}

// ── the panel handler ──
const at = html.indexOf('window.harnessNativeAudioDrop');
check('the panel defines window.harnessNativeAudioDrop', at > 0);
// body = from the assignment to the closing "};" of the function expression
const body = at > 0 ? html.slice(at, html.indexOf('\n};', at) + 3) : '';

check('it posts to the EXISTING /api/voice/library/save (no new endpoint)',
      /\/api\/voice\/library\/save\?name=/.test(body));
check('it sends the stem as ?name= and the suffix as ?fmt=',
      /name=' \+ encodeURIComponent\(stem\)/.test(body) &&
      /fmt=' \+ encodeURIComponent\(ext\)/.test(body));
check('it POSTs RAW bytes, not a data URL string',
      /method: 'POST'/.test(body) && /new Uint8Array\(/.test(body) && /atob\(/.test(body));
check('it accepts exactly the bridge\'s four reference suffixes',
      /\['wav','mp3','flac','m4a'\]/.test(body));
check('the suffix set matches bridge/voice.py REF_AUDIO_SUFFIXES',
      /REF_AUDIO_SUFFIXES = \("wav", "mp3", "flac", "m4a"\)/
        .test(fs.readFileSync(path.join(ROOT, 'bridge', 'voice.py'), 'utf8')));
check('a successful drop writes one activity-feed line',
      /feed\('voice', 'clip ' \+ esc\(/.test(body));
check('the clip name is escaped before it reaches the feed (feed interpolates HTML)',
      /esc\(j\.name \|\| stem\)/.test(body));
check('it refreshes the voice library so an open clip picker shows the new chip',
      /loadVoiceLib\(true\)/.test(body));

// THE load-bearing negative: no pin is written on drop.
check('NO auto-pin: the handler never calls setEntryRef',
      body.indexOf('setEntryRef') < 0);
check('NO auto-pin: the handler never posts to /api/voice/entry-ref',
      body.indexOf('entry-ref') < 0);

check('the image drop path is untouched (still its own hook)',
      /window\.harnessNativeDrop = function\(name, dataUrl\)/.test(html));

// ── the Swift half ──
check('the shell routes audio drops to harnessNativeAudioDrop',
      /harnessNativeAudioDrop/.test(swift));
check('the shell accepts the same four suffixes',
      /audioMimes = \["wav": "audio\/wav", "mp3": "audio\/mpeg",[\s\S]{0,80}"flac": "audio\/flac", "m4a": "audio\/mp4"\]/
        .test(swift));
check('the shell caps audio at 15 MB (the bridge\'s REF_AUDIO_MAX_BYTES)',
      /isAudio \? 15 \* 1024 \* 1024 : 8 \* 1024 \* 1024/.test(swift));
check('the bridge cap really is 15 MB',
      /REF_AUDIO_MAX_BYTES = 15 \* 1024 \* 1024/
        .test(fs.readFileSync(path.join(ROOT, 'bridge', 'voice.py'), 'utf8')));

// ── Phase 1 shell wiring ──
check('one titles array feeds both tab strips',
      /let tabTitles = \[/.test(swift) &&
      (swift.match(/labels: tabTitles/g) || []).length === 2);
check('the split state is persisted under the spec\'s keys',
      /"harness\.split\.on"/.test(swift) && /"harness\.split\.right"/.test(swift));
check('the split view autosaves its divider',
      /autosaveName = "harness-split"/.test(swift));
check('min pane width 420 is enforced on the divider drag',
      /constrainMinCoordinate[\s\S]{0,200}420/.test(swift) &&
      /constrainMaxCoordinate[\s\S]{0,200}420/.test(swift));
check('left wins: the right pane borrows only a DIFFERENT tab',
      /let rightBorrows = splitOn && rightTab != leftIdx/.test(swift));
check('the collision case shows the placeholder text the spec names',
      /Already open in the left pane\./.test(swift));
check('the DropOverlay follows Mission Control\'s pane',
      /if leftIdx == 0 \{ attach\(ov, to: leftPane\) \}/.test(swift) &&
      /rightBorrows && rightTab == 0 \{ attach\(ov, to: rightHost\) \}/.test(swift));
check('⌘R targets the focused pane',
      /func visibleWebView\(\)[\s\S]{0,300}focusedPane == 1/.test(swift));

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
