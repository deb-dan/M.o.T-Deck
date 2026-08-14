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

// ── split-view shell (v2) ──
// v1 had TWO strips and a "left always wins" collision rule. v2 deletes the right
// pane's mini strip and routes the ONE strip to the focused pane, swapping on collision.
// These greps were updated with that redesign — the facts they pinned genuinely changed.
check('exactly ONE tab strip is built from the titles array',
      /let tabTitles = \[/.test(swift) &&
      (swift.match(/labels: tabTitles/g) || []).length === 1);
check('the right pane\'s mini strip is gone',
      !/rightSeg/.test(swift) && !/rightTabChanged/.test(swift));
check('the split state is persisted under all four v2 keys',
      /"harness\.split\.on"/.test(swift) && /"harness\.split\.right"/.test(swift) &&
      /"harness\.split\.left"/.test(swift) && /"harness\.split\.focus"/.test(swift));
check('the split view autosaves its divider',
      /autosaveName = "harness-split"/.test(swift));
check('min pane width 420 is enforced on the divider drag',
      /constrainMinCoordinate[\s\S]{0,200}420/.test(swift) &&
      /constrainMaxCoordinate[\s\S]{0,200}420/.test(swift));
check('the strip routes to the FOCUSED pane and swaps on collision',
      /func tabChanged[\s\S]{0,700}if splitOn && focusedPane == 1 \{[\s\S]{0,120}if idx == currentTab \{ currentTab = rightTab \}/.test(swift) &&
      /if splitOn && idx == rightTab \{ rightTab = currentTab \}/.test(swift));
check('the strip mirrors the focused pane\'s tab',
      /func focusedTab\(\)[\s\S]{0,160}focusedPane == 1\) \? rightTab : currentTab/.test(swift) &&
      /func syncStrip\(\)[\s\S]{0,200}seg\.selectedSegment = t/.test(swift));
check('a click in either pane sets focus by hit-test',
      /rightPane\.bounds\.contains[\s\S]{0,80}setFocus\(1\)/.test(swift) &&
      /leftPane\.bounds\.contains[\s\S]{0,80}setFocus\(0\)/.test(swift));
check('the focused pane is marked with a 2px gold top strip',
      /let paneGold = NSColor\(red: 0\.788, green: 0\.643, blue: 0\.302/.test(swift) &&
      /focusedPane == 0\) \? paneGold : NSColor\.clear/.test(swift) &&
      /strip\.heightAnchor\.constraint\(equalToConstant: 2\)/.test(swift));
check('each pane has its own ✕ that closes THAT pane',
      /func closeLeft\(/.test(swift) && /func closeRight\(/.test(swift) &&
      /func closePane\(_ p: Int\)[\s\S]{0,300}if p == 0 \{ currentTab = rightTab \}[\s\S]{0,120}setSplit\(false, persist: true\)/.test(swift));
check('⫽ OFF goes through the same close path as the right pane\'s ✕',
      /func toggleSplit[\s\S]{0,200}if splitOn \{ closePane\(1\); return \}/.test(swift));
check('⫽ ON opens the right pane on the NEXT tab',
      /func toggleSplit[\s\S]{0,300}rightTab = \(currentTab \+ 1\) % tabTitles\.count/.test(swift));
check('holding priorities are set on BOTH panes, left lower',
      /setHoldingPriority\(NSLayoutConstraint\.Priority\(250\), forSubviewAt: 0\)/.test(swift) &&
      /setHoldingPriority\(NSLayoutConstraint\.Priority\(251\), forSubviewAt: 1\)/.test(swift));
check('the placeholder survives as a safety net',
      /Already open in the left pane\./.test(swift) &&
      /let rightBorrows = splitOn && rightTab != leftIdx/.test(swift));
check('applyPanes does not thrash reparents when nothing changed',
      /func attach\([\s\S]{0,120}if v\.superview === host \{ return \}/.test(swift) &&
      /if ov\.superview !== t \{ attach\(ov, to: t\) \}/.test(swift));
check('the DropOverlay follows Mission Control\'s pane host',
      /let target: NSView\? = \(leftIdx == 0\) \? leftHost/.test(swift) &&
      /rightBorrows && rightTab == 0\) \? rightHost : nil/.test(swift));
check('⌘R targets the focused pane',
      /func visibleWebView\(\)[\s\S]{0,300}focusedPane == 1/.test(swift));
check('the split diagnostics name focus and both tabs',
      /slog\("applyPanes left=[\s\S]{0,80}focus=/.test(swift));

// ── composer auto-grow ──
check('growInput caps the box at 3x its measured base height',
      /const GROW_MAX = 3;/.test(html) &&
      /function growInput\(el\)\{/.test(html) &&
      /Math\.max\(base, Math\.min\(need, base \* GROW_MAX\)\)/.test(html));
check('growInput measures the base height lazily (hidden view = no cache)',
      /if \(!bh\) return;/.test(html) && /box\._growBase = bh;/.test(html));
check('the textarea grows on typing and pasting (oninput covers both)',
      /oninput="growInput\(this\)"/.test(html));
check('a programmatic transcript write grows the box too',
      /function appendTranscript\([\s\S]{0,400}growInput\(box\);/.test(html) &&
      /function convSend\([\s\S]{0,700}growInput\(box\);/.test(html));
check('sending shrinks the box back to its base',
      /inp\.value = '';\s*\n\s*growInput\(inp\);/.test(html));
check('the box scrolls internally past the cap', /overflow-y:auto; \}/.test(html));

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
