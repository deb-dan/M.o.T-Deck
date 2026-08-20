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
      // 2026-08-20: tabTitles is now DERIVED from the single `tabs` table (title + url
      // per row) rather than being a literal array — the fact this pinned genuinely
      // changed. Still exactly one strip, still fed from one source.
      /let tabTitles: \[String\] = tabs\.map \{ \$0\.title \}/.test(swift) &&
      (swift.match(/labels: tabTitles/g) || []).length === 1);

// ── tab-count generalization (standing rule, Debi 2026-08-20) ──
// Every tab must inherit every tab behaviour BY CONSTRUCTION. These pin the absence of
// hardcoded counts, not the presence of any particular tab.
check('one table declares every tab (title + url together)',
      /struct HarnessTab \{[\s\S]{0,120}let title: String[\s\S]{0,120}let url: URL/.test(swift) &&
      /let tabs: \[HarnessTab\] = \[/.test(swift));
check('the two optional component tabs are rows in that table',
      /HarnessTab\(title: "ComfyUI", url: URL\(string: "http:\/\/127\.0\.0\.1:8188"\)!\)/.test(swift) &&
      // 8899, NOT upstream's 8888: that port belongs to Debi's standalone Unsloth app and
      // the start script's listener-scoped port clear would kill it. Same number as
      // harness.yaml (contract test pins that side).
      /HarnessTab\(title: "Unsloth", url: URL\(string: "http:\/\/127\.0\.0\.1:8899"\)!\)/.test(swift));
check('...and the shell never points a tab at :8888 again',
      !/127\.0\.0\.1:8888/.test(swift));
check('Music is a tab row loading OUR OWN panel chromeless (?solo=music)',
      /HarnessTab\(title: "Music", url: URL\(string: "http:\/\/127\.0\.0\.1:8700\/\?solo=music"\)!\)/.test(swift));
check('special tabs are looked up BY TITLE, never written as a literal index',
      /let odysseusTab = tabTitles\.firstIndex\(of: "Odysseus"\) \?\? -1/.test(swift) &&
      /let hermesTab = tabTitles\.firstIndex\(of: "Hermes"\) \?\? -1/.test(swift));
check('...and an absent named tab degrades to -1 (never matches) rather than to tab 0',
      !/firstIndex\(of: "(Odysseus|Hermes)"\) \?\? 0/.test(swift));
check('the primaries are built FROM the table, so a new row needs no code here',
      /primaries = tabs\.indices\.map \{ i -> WKWebView in/.test(swift) &&
      /return WKWebView\(frame: \.zero, configuration: WKWebViewConfiguration\(\)\)/.test(swift));
check('webViewFor / allWebViews / urlForTab are table lookups, not switch tables',
      /func webViewFor\(_ idx: Int\) -> WKWebView \{[\s\S]{0,300}return primaries\[idx\]/.test(swift) &&
      /func allWebViews\(\) -> \[WKWebView\] \{ return primaries \}/.test(swift) &&
      /func urlForTab\(_ idx: Int\) -> URL \{[\s\S]{0,200}return tabs\[idx\]\.url/.test(swift));
check('lazy load is ONE generic path keyed by a Set, not a flag per tab',
      /var loadedTabs = Set<Int>\(\)/.test(swift) &&
      /guard !loadedTabs\.contains\(idx\) else \{ return \}/.test(swift) &&
      !/var (odyLoaded|vsLoaded|vbLoaded) /.test(swift));
check('no per-tab webview properties survive for the optional SPAs',
      !/\bvsWV\b/.test(swift) && !/\bvbWV\b/.test(swift));
check('urlFor resolves a primary by INDEX, so a new tab needs no identity branch',
      /if let i = primaries\.firstIndex\(where: \{ \$0 === wv \}\) \{ return urlForTab\(i\) \}/.test(swift));
check('Mission Control stays tab 0 by construction and keeps the sole drop overlay',
      /let panelTab = 0/.test(swift) &&
      /\(leftWV === panelWV\) \? leftHost/.test(swift));
check('no hardcoded tab count anywhere (the old `% 5` class of bug)',
      !/% 5\b/.test(swift) && !/< 5\b/.test(swift));
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
// UPDATED HONESTLY for the drag-a-tab slice: the swap moved OUT of tabChanged into
// routeTab(_:toPane:) so the click path and the drop path share one body. The two facts
// are now pinned separately, which is strictly stronger than the old single grep — it
// also forbids the strip quietly stopping to route to the focused pane.
check('the routing rule takes the destination pane as a parameter and swaps on collision',
      /func routeTab\(_ idx: Int, toPane p: Int\)[\s\S]{0,700}if splitOn && p == 1 \{[\s\S]{0,120}if idx == currentTab \{ currentTab = rightTab \}/.test(swift) &&
      /if splitOn && idx == rightTab \{ rightTab = currentTab \}/.test(swift));
check('the strip routes to the FOCUSED pane through that one rule',
      /func tabChanged[\s\S]{0,240}routeTab\(idx, toPane: \(splitOn && focusedPane == 1\) \? 1 : 0\)/.test(swift));
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
// UPDATED HONESTLY for the second-instance slice: the overlay used to be located by TAB
// INDEX, which cannot distinguish Mission Control's primary from a second instance of it.
// It now follows the primary webview by IDENTITY — strictly stronger, and it is what keeps
// file drops attached to the one webview that handles them.
check('the DropOverlay follows Mission Control\'s PRIMARY webview, by identity',
      /let target: NSView\? = \(leftWV === panelWV\) \? leftHost/.test(swift) &&
      /\(rightWV === panelWV\) \? rightHost : nil/.test(swift));
check('⌘R targets the focused pane',
      /func visibleWebView\(\)[\s\S]{0,300}focusedPane == 1/.test(swift));
check('the split diagnostics name focus and both tabs',
      /slog\("applyPanes left=[\s\S]{0,80}focus=/.test(swift));

// ── drag a tab onto a pane (v2 enhancement) ──
// NSSegmentedControl handles a click in a cell tracking loop that pulls events straight
// off the queue, so a monitor watching for .leftMouseDragged after the fact would never
// fire. The shell therefore claims the mouseDown itself and runs the whole gesture —
// which makes "a plain click is completely unaffected" a thing that must be PINNED.
check('a second monitor claims only a mouseDown that lands on a segment',
      /tabDragMonitor = NSEvent\.addLocalMonitorForEvents\(matching: \[\.leftMouseDown\]\)/.test(swift) &&
      /guard let idx = s\.segmentAt\(ev\.locationInWindow\) else \{ return ev \}/.test(swift) &&
      /s\.runTabGesture\(startingAt: ev\.locationInWindow, tab: idx\)/.test(swift));
check('the focus monitor is still its own, untouched monitor',
      /clickMonitor = NSEvent\.addLocalMonitorForEvents/.test(swift) &&
      /var tabDragMonitor: Any\?/.test(swift));
check('segment geometry is knowable: widths are set explicitly at construction',
      /func setSegmentWidths\(\)[\s\S]{0,300}seg\.setWidth\(/.test(swift) &&
      /setSegmentWidths\(\)\n\s*tabBar\.addSubview\(seg\)/.test(swift));
check('segmentAt returns nil off the strip so the event is left alone',
      /func segmentAt\(_ windowPoint: NSPoint\) -> Int\?/.test(swift) &&
      /guard seg\.bounds\.contains\(p\) else \{ return nil \}/.test(swift));
check('below the 10pt threshold the gesture is the ordinary click, performed verbatim',
      /hypot\(last\.x - start\.x, last\.y - start\.y\) >= 10/.test(swift) &&
      /if !dragging \{[\s\S]{0,200}seg\.selectedSegment = tab\n\s*tabChanged\(seg\)/.test(swift));
check('the drag runs its own tracking loop (the control never gets the events)',
      /NSApp\.nextEvent\(matching: \[\.leftMouseDragged, \.leftMouseUp, \.keyDown\]/.test(swift) &&
      /inMode: \.eventTracking, dequeue: true/.test(swift));
check('a lost mouseUp cannot wedge the strip',
      /until: Date\(timeIntervalSinceNow: 60\)/.test(swift) &&
      /drag -> cancelled \(no event for 60s\)/.test(swift));
check('Esc and a release outside the content area both cancel',
      /ev\.keyCode == 53 \{ cancelled = true/.test(swift) &&
      /guard let p = paneTarget\(for: last\) else \{[\s\S]{0,140}return\n\s*\}/.test(swift) &&
      /drag -> cancelled \(released outside the content area\)/.test(swift));
check('the drop target is the real pane when split is on, the half when it is off',
      /func paneTarget\(for wp: NSPoint\) -> Int\?[\s\S]{0,600}rightPane\.bounds\.contains[\s\S]{0,120}return 1/.test(swift) &&
      /return wp\.x < c\.midX \? 0 : 1/.test(swift));
// Distance widened 600→900: the collision branch now precedes this one inside dropTab.
check('a drop on the right half with the split OFF opens the split',
      /func dropTab\(_ tab: Int, onPane p: Int\)[\s\S]{0,900}if p == 1 && !splitOn \{[\s\S]{0,700}setSplit\(true, persist: true\)/.test(swift));
// The two distances below were widened (1300→1600, 800→1000) because dropTab's body grew
// by the collision branch. The facts pinned are unchanged.
check('a non-colliding drop with the split ON reuses the shared routing rule + swap',
      /func dropTab\([\s\S]{0,1600}routeTab\(tab, toPane: p\)[\s\S]{0,120}setFocus\(p\)/.test(swift));
check('the drop persists through the existing keys, no new ones',
      /func dropTab\([\s\S]{0,1000}persistTabs\(\)/.test(swift) &&
      !/harness\.split\.drag/.test(swift));
check('the ghost + hint are mouse-transparent child windows, cleaned up on every exit',
      /func makeFloater\([\s\S]{0,400}ignoresMouseEvents = true/.test(swift) &&
      /defer \{ tabDragActive = false; endDragVisuals\(\) \}/.test(swift) &&
      /func endDragVisuals\(\)[\s\S]{0,300}window\.removeChildWindow\(w\)/.test(swift));
check('the drag has its own [split] diagnostics',
      /slog\("drag -> begin /.test(swift) &&
      /slog\("drag -> tab /.test(swift) &&
      /slog\("drag -> opened split: /.test(swift));

// ── same tab in BOTH panes: on-demand second instances ("ghosts") ──
// Debi's ask: dragging a tab the OTHER pane already shows opens a SECOND copy here
// instead of always swapping. The STRIP keeps the swap — that separation is the design,
// so both halves of it are pinned.
check('the ghost state is two booleans plus one lazily-keyed dictionary',
      /var leftIsGhost = false/.test(swift) && /var rightIsGhost = false/.test(swift) &&
      /var secondInstances: \[Int: WKWebView\] = \[:\]/.test(swift));
check('a COLLIDING drop opens a second instance instead of swapping',
      /func dropTab\([\s\S]{0,900}let other = splitOn \? \(p == 1 \? currentTab : rightTab\) : currentTab[\s\S]{0,200}if tab == other && \(splitOn \|\| p == 1\) \{[\s\S]{0,120}openSecondInstance\(tab, onPane: p\)/
        .test(swift));
check('the STRIP still swaps: openSecondInstance is reachable ONLY from the drop path',
      (swift.match(/openSecondInstance\(/g) || []).length === 2 &&        // decl + the one call
      !/func routeTab\([\s\S]{0,900}openSecondInstance/.test(swift) &&
      !/func tabChanged[\s\S]{0,300}openSecondInstance/.test(swift));
check('the split-OFF right-half drop of the CURRENT tab no longer steps the left tab',
      !/currentTab = \(tab \+ 1\) % tabTitles\.count/.test(swift));
check('a second instance copies the primary\'s configuration (skin + shared cookies)',
      /func ghostFor\(_ idx: Int\) -> WKWebView[\s\S]{0,600}WKWebView\(frame: \.zero, configuration: webViewFor\(idx\)\.configuration\)/
        .test(swift));
check('a second instance is a PLAIN WKWebView, not a DropWebView',
      !/func ghostFor\([\s\S]{0,600}DropWebView/.test(swift));
check('a second instance loads its own tab URL through the shared tab→URL table',
      /func urlForTab\(_ idx: Int\) -> URL/.test(swift) &&
      /func ghostFor\([\s\S]{0,700}wv\.load\(URLRequest\(url: urlForTab\(idx\)\)\)/.test(swift));
check('urlFor asks the ghost table FIRST (else a ⌘R on a copy would go to the bridge)',
      /func urlFor\(_ wv: WKWebView\) -> URL[\s\S]{0,400}secondInstances\.first\(where: \{ \$0\.value === wv \}\)[\s\S]{0,60}urlForTab\(hit\.key\)/
        .test(swift));
check('⌘R reloads the COPY when the focused pane is showing one',
      /func visibleWebView\(\)[\s\S]{0,400}rightIsGhost \? secondInstances\[rightTab\] : webViewFor\(rightTab\)/.test(swift) &&
      /if leftIsGhost \{ return secondInstances\[currentTab\] \}/.test(swift));
// Memory discipline — the primary is never destroyed, the copy always is.
check('destroyGhost stops loading, unparents, and drops the only strong reference',
      /func destroyGhost\(_ idx: Int\)[\s\S]{0,500}secondInstances\.removeValue\(forKey: idx\)[\s\S]{0,400}g\.stopLoading\(\)[\s\S]{0,300}g\.removeFromSuperview\(\)/
        .test(swift));
check('destroyGhost forgets a failed load so the set cannot leak identifiers',
      /func destroyGhost\([\s\S]{0,500}failedLoads\.remove\(ObjectIdentifier\(g\)\)/.test(swift));
check('releaseUnusedGhosts iterates a COPY of the keys (the dict is mutated inside)',
      /func releaseUnusedGhosts\(\)[\s\S]{0,200}for idx in Array\(secondInstances\.keys\)/.test(swift));
check('a copy is kept only while a pane\'s ghost flag claims it',
      /func releaseUnusedGhosts\([\s\S]{0,500}let keptLeft = leftIsGhost && idx == currentTab[\s\S]{0,200}let keptRight = splitOn && rightIsGhost && idx == rightTab[\s\S]{0,160}destroyGhost\(idx\)/
        .test(swift));
check('closing the split / a pane destroys the copy: applyPanes clears the flags first',
      /func applyPanes\(\)[\s\S]{0,900}if !splitOn \|\| rightTab != leftIdx \{ leftIsGhost = false; rightIsGhost = false \}[\s\S]{0,200}releaseUnusedGhosts\(\)/
        .test(swift));
check('both panes can never be the copy (the primary lives in exactly one pane)',
      /if leftIsGhost && rightIsGhost \{ rightIsGhost = false \}/.test(swift));
check('a pane holds either the primary or the copy, and the placeholder still backs it up',
      /let leftWV: WKWebView = leftIsGhost \? ghostFor\(leftIdx\) : webViewFor\(leftIdx\)/.test(swift) &&
      /if rightIsGhost \{ rightWV = ghostFor\(rightTab\) \}/.test(swift) &&
      /else if rightBorrows \|\| leftIsGhost \{ rightWV = webViewFor\(rightTab\) \}/.test(swift) &&
      /\} else if splitOn \{\n\s*attach\(rightPlaceholder, to: rightHost\)/.test(swift));
check('only primaries are parked; copies are destroyed, never parked',
      /for wv in allWebViews\(\) where wv !== leftWV && wv !== rightWV \{[\s\S]{0,120}attach\(wv, to: park\)/.test(swift));
// NEGATIVE: ghosts are deliberately NOT persisted — a relaunch restores the swap-based
// arrangement, so no new defaults key may appear for them.
check('no ghost state is persisted (no new UserDefaults key)',
      !/harness\.split\.ghost/.test(swift) &&
      (swift.match(/"harness\.split\.[a-z]+"/g) || [])
        .every(k => ['"harness.split.on"', '"harness.split.left"',
                     '"harness.split.right"', '"harness.split.focus"'].includes(k)));
check('the second-instance path has its own [split] diagnostics',
      /slog\("ghost -> created /.test(swift) &&
      /slog\("ghost -> destroyed /.test(swift) &&
      /slog\("ghost -> tab /.test(swift) &&
      /slog\("applyPanes left=[\s\S]{0,140}ghosts=/.test(swift));

// ── composer auto-grow ──
// The cap is now a PARAMETER (the Music page shares this one implementation with its
// own multiplier), so the invariant is: the composer still defaults to GROW_MAX = 3,
// and the cap is still applied — one growInput, not two.
check('growInput caps the box at its caller\'s multiple of the measured base height',
      /const GROW_MAX = 3;/.test(html) &&
      /function growInput\(el, maxMul\)\{/.test(html) &&
      /\(typeof maxMul === 'number' && maxMul > 1\) \? maxMul : GROW_MAX/.test(html) &&
      /Math\.max\(base, Math\.min\(need, base \* mul\)\)/.test(html));
check('there is exactly ONE growInput implementation in the panel',
      (html.match(/function growInput\(/g) || []).length === 1);
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

// ── Hermes config-generation reload ──
// Hermes's own Skills page fetches its lists ONCE on mount (SkillsPage.tsx:155-174)
// and never refreshes, so a toolset/skill switched from OUR Capabilities page left it
// showing the pre-change state until the 600s staleness rule happened to fire. The
// shell now reloads that webview when the bridge's `hermes_config_gen` has increased
// since the page loaded. What is pinned here is the wiring and, above all, the
// FAIL-SAFE and NO-LOOP properties — neither can be exercised without swiftc.
const gen = swift.slice(swift.indexOf('func maybeReloadStaleHermes'),
                        swift.indexOf('func retryIfFailed'));
check('there is still exactly ONE Hermes reload entry point',
      (swift.match(/func maybeReloadStaleHermes/g) || []).length === 1 &&
      (swift.match(/func syncHermesGen/g) || []).length === 1);
check('the 600s staleness rule is intact and INDEPENDENT of the new one',
      /Date\(\)\.timeIntervalSince\(since\) > staleAfter/.test(gen) &&
      /hermesLastActive = nil/.test(gen) &&
      /hermesWV\.reload\(\)/.test(gen));
check('a staleness reload re-records the generation instead of comparing',
      /hermesWV\.reload\(\)[\s\S]{0,240}syncHermesGen\(reloadIfNewer: false\)[\s\S]{0,40}return/
        .test(gen));
check('the config-generation check runs only when staleness did NOT fire',
      gen.indexOf('syncHermesGen(reloadIfNewer: false)') <
      gen.indexOf('syncHermesGen(reloadIfNewer: true)'));
check('it reads the field off the EXISTING /api/status (no new bridge route)',
      /appendingPathComponent\("api\/status"\)/.test(swift) &&
      /obj\["hermes_config_gen"\] as\? Int/.test(swift) &&
      !/api\/hermes\/gen/.test(swift));
check('the fetch is asynchronous and short — never blocks the UI thread',
      /URLSession\.shared\.dataTask[\s\S]{0,900}\}\.resume\(\)/.test(swift) &&
      /req\.timeoutInterval = 2\.0/.test(swift) &&
      /DispatchQueue\.main\.async \{[\s\S]{0,600}hermesCfgGen = gen/.test(swift));
check('FAIL SAFE: an error, a non-200, an unparseable body or a missing field all ' +
      'return without touching anything',
      /guard err == nil,[\s\S]{0,320}statusCode == 200,[\s\S]{0,320}as\? Int else \{ return \}/
        .test(swift));
check('NO LOOP: the generation is recorded BEFORE the reload decision',
      swift.indexOf('self.hermesCfgGen = gen') <
      swift.indexOf('guard reloadIfNewer, let p = prev, gen > p'));
check('a bridge restart (gen back to 0) is recorded, never reloaded for — the ' +
      'compare is a STRICT increase against a KNOWN previous value',
      /let p = prev, gen > p else \{ return \}/.test(swift) &&
      /var hermesCfgGen: Int\?/.test(swift));
// The single-webview guard became a per-surface one when ghosts were covered (below),
// but it asks exactly the same two questions: is it visible, is it healthy.
check('visibility and health are re-checked on the main thread after the fetch',
      /let targets = self\.visibleHermesWebViews\(\)\.filter \{[\s\S]{0,220}failedLoads\.contains\(ObjectIdentifier\(\$0\)\)[\s\S]{0,120}scheme == "http"[\s\S]{0,80}\}\s*\n\s*guard !targets\.isEmpty else \{ return \}/
        .test(swift));
check('every OTHER Hermes load path records the generation too (first load, ⌘R, retry)',
      // the first-load site moved into the ONE generic ensureLoaded when the per-tab
      // `hermesLoaded = true` flag became a Set — same fact, pinned at the new site
      /loadedTabs\.insert\(idx\)[\s\S]{0,300}if idx == hermesTab \{ syncHermesGen\(reloadIfNewer: false\) \}/.test(swift) &&
      /func retryIfFailed[\s\S]{0,240}wv === hermesWV \{ syncHermesGen\(reloadIfNewer: false\) \}/
        .test(swift) &&
      /func reloadTab[\s\S]{0,700}wv === hermesWV \{ syncHermesGen\(reloadIfNewer: false\) \}/
        .test(swift));
check('the reload announces itself in the house log idiom, saying what triggered it',
      /\[hermes\] reload -> config generation \\\(gen\) \(\\\(why\)\)/.test(swift));
check('no new UserDefaults key was invented for any of this',
      !/harness\.hermes\.gen/.test(swift) && !/harness\.hermes\.config/.test(swift));

// ── the SPLIT-VIEW gap: a poll, gated on Hermes actually being on screen ──
// maybeReloadStaleHermes only runs when a tab BECOMES visible, so a Hermes pane sitting
// beside Mission Control was never checked (Debi's own layout: toggle a toolset, wait
// five minutes, Hermes's Skills page still says `inactive`). A repeating timer now asks
// the SAME question while a Hermes surface is visible — and must not exist otherwise.
const tim = swift.slice(swift.indexOf('func updateHermesGenTimer'),
                        swift.indexOf('func syncStrip'));
check('there is exactly ONE poll and ONE place that arms it',
      (swift.match(/func updateHermesGenTimer/g) || []).length === 1
      && (swift.match(/updateHermesGenTimer\(\)/g) || []).length === 3   // decl + 2 calls
      && (swift.match(/Timer\.scheduledTimer/g) || []).length === 1);
check('the poll calls the EXISTING sync, not a second copy of the logic',
      /syncHermesGen\(reloadIfNewer: true, why: "poll"\)/.test(tim)
      && !/hermes_config_gen/.test(tim) && !/URLSession/.test(tim));
check('the interval is a named constant, not a magic number at the call site',
      /let hermesGenPoll: TimeInterval = \d/.test(swift)
      && /withTimeInterval: hermesGenPoll/.test(tim));
check('the timer only exists while a Hermes surface is ON SCREEN',
      /if !visibleHermesWebViews\(\)\.isEmpty \{/.test(tim));
check('...and is INVALIDATED and dropped the moment it is not',
      /else if let t = hermesGenTimer \{[\s\S]{0,160}t\.invalidate\(\)[\s\S]{0,80}hermesGenTimer = nil/
        .test(tim));
check('...and is never restacked by a repeat arm',
      /if hermesGenTimer != nil \{ return \}/.test(tim));
check('the tick re-checks visibility and retires itself rather than polling forever',
      /if s\.visibleHermesWebViews\(\)\.isEmpty \{ s\.updateHermesGenTimer\(\); return \}/.test(tim));
// v2: the queued refinement — an inactive app has nothing to learn from the poll.
check('the tick early-returns while the app is not frontmost',
      /if !NSApp\.isActive \{ return \}/.test(tim));
check('...by early-return only — the timer is NOT torn down and re-armed by observers',
      !/NSApplication\.didBecomeActiveNotification/.test(swift)
      && !/NSApplication\.didResignActiveNotification/.test(swift));
check('...and the visibility gate still runs BEFORE the activity gate',
      tim.indexOf('visibleHermesWebViews().isEmpty') < tim.indexOf('!NSApp.isActive'));
check('the closure does not retain the delegate strongly',
      /\{ \[weak self\] _ in/.test(tim));
check('arming happens from applyPanes — the one place that settles what is visible',
      /applyPanes[\s\S]{0,3200}updateHermesGenTimer\(\)\s*\n\s*\}/.test(swift));
check('the tab-select entry point is KEPT, so a switch checks immediately',
      /maybeReloadStaleHermes\(idx\)/.test(swift)
      && /syncHermesGen\(reloadIfNewer: true\)/.test(swift));
check('the 600s staleness rule stayed independent of all of this',
      !/staleAfter/.test(tim) && /let staleAfter: TimeInterval = 600/.test(swift));

// Ghosts: with a SECOND INSTANCE of the Hermes tab both panes show Hermes, and both are
// equally stale after a config change — so both are reloaded, not just the primary.
const vis = swift.slice(swift.indexOf('func visibleHermesWebViews'),
                        swift.indexOf('func updateHermesGenTimer'));
check('the visible set covers a Hermes ghost as well as the primary',
      // the literal index became the named constant when the tab list grew — same fact
      /secondInstances\[hermesTab\]/.test(vis) && /out\.append\(hermesWV\)/.test(vis));
check('...the primary is still gated on hermesLoaded',
      /if hermesLoaded,/.test(vis));
check('...both panes are asked, so split view is genuinely covered',
      /let leftShowsHermes = currentTab == hermesTab/.test(vis)
      && /let rightShowsHermes = splitOn && rightTab == hermesTab/.test(vis));
check('...and every visible Hermes surface is reloaded, not only the first',
      /for wv in targets \{ wv\.reload\(\) \}/.test(swift));

// ── panel → shell tab switching (2026-08-21) ──
// A sidebar row must be able to OPEN a component's tab, not merely highlight its card.
// The whole bridge is one script message, and the security property is that it is
// registered on the PANEL webview only — a component page must never drive our strip.
const handler = swift.slice(swift.indexOf('func userContentController(_ ucc:'));
const handlerBody = handler.slice(0, handler.indexOf('\n    }\n', handler.indexOf('default:')) + 6);
check('the shell conforms to WKScriptMessageHandler',
      /NSSplitViewDelegate, WKScriptMessageHandler \{/.test(swift));
check('the handler is registered exactly ONCE, on the panel configuration',
      (swift.match(/userContentController\.add\(self, name: "harness"\)/g) || []).length === 1
      && /let panelCfg = WKWebViewConfiguration\(\)[\s\S]{0,400}panelCfg\.userContentController\.add\(self, name: "harness"\)[\s\S]{0,200}panelWV = DropWebView\(frame: \.zero, configuration: panelCfg\)/.test(swift));
check('...so no other webview\'s configuration carries it',
      !/odyCfg\.userContentController\.add\(self/.test(swift));
check('it accepts only the "harness" message name',
      /message\.name == "harness"/.test(handlerBody));
check('switchTab resolves a TITLE against the tabs table (no index on the wire)',
      /body\["title"\] as\? String/.test(handlerBody)
      && /tabTitles\.firstIndex\(of: title\)/.test(handlerBody));
check('an unknown title is ignored, never coerced to a tab',
      /else \{[\s\S]{0,160}unknown title[\s\S]{0,60}return/.test(handlerBody)
      && !/firstIndex\(of: title\) \?\? 0/.test(handlerBody));
check('an unknown cmd is ignored too',
      /default:[\s\S]{0,120}unknown cmd/.test(handlerBody));
check('it takes the SAME path a strip click takes (routeTab, focused pane)',
      /routeTab\(idx, toPane: \(splitOn && focusedPane == 1\) \? 1 : 0\)/.test(handlerBody));
check('...and syncs the strip, which a real click gets from the control itself',
      /syncStrip\(\)/.test(handlerBody));
check('the switch is logged like every other tab event',
      /slog\("panel -> switchTab/.test(handlerBody));

// ── the panel half of the same bridge ──
check('the panel maps components to tab titles with a TABLE, not a name guess',
      /const TAB_FOR_COMPONENT = \{/.test(html)
      && /odysseus: 'Odysseus'/.test(html) && /comfyui: 'ComfyUI'/.test(html)
      && /unsloth: 'Unsloth'/.test(html));
check('...and searxng, which has no tab, is absent from it',
      !/searxng: '/.test(html));
const oc = html.slice(html.indexOf('function openComponent('),
                      html.indexOf('function openMusic('));
check('openComponent reads running state at CLICK time, not from the rendered row',
      /lastStatus && lastStatus\.components/.test(oc));
check('...a RUNNING component opens its tab',
      /c\.running && title && switchTab\(title\)/.test(oc));
check('...and everything else falls back to jumpToCard (browser, stopped, no tab)',
      /jumpToCard\(name\)/.test(oc));
check('switchTab returns false when the native bridge is absent',
      /function switchTab\(title\)[\s\S]{0,240}if \(!h\) return false/.test(html));
check('the sidebar rows call openComponent, not jumpToCard directly',
      /onclick="openComponent\('\$\{name\}'\)"/.test(html));
check('the Music nav entry routes to the native tab with an in-panel fallback',
      /id="nav-music" onclick="openMusic\(\)"/.test(html)
      && /function openMusic\(\)[\s\S]{0,240}if \(switchTab\('Music'\)\) return;[\s\S]{0,60}showView\('music'\)/.test(html));

// ── solo mode ──
check('soloView is pure and only knows the views solo mode declares',
      /const SOLO_VIEWS = \['music'\]/.test(html)
      && /function soloView\(search\)/.test(html));
check('applySolo adds body.solo and pins the view, and is armed at boot',
      /document\.body\.classList\.add\('solo'\)/.test(html)
      && /applySolo\(\);/.test(html));
check('solo mode hides chrome in exactly three CSS rules and restyles nothing else',
      (html.match(/body\.solo /g) || []).length === 3
      && /body\.solo aside \{ display:none; \}/.test(html)
      && /body\.solo \.topbar \{ display:none; \}/.test(html));

// soloView EXECUTED on the shipped source — the decision table, incl. totality.
{
  const src = html.slice(html.indexOf("const SOLO_VIEWS = ['music']"),
                         html.indexOf('function applySolo('));
  const soloView = new Function(src + '; return soloView;')();
  const cases = [
    ['?solo=music', 'music'], ['?solo=MUSIC', 'music'], ['?a=1&solo=music', 'music'],
    ['?solo=music&b=2', 'music'], ['', null], ['?', null], ['?solo=', null],
    ['?solo=chat', null], ['?solo=musicx', null], ['?notsolo=music', null],
    [null, null], [undefined, null], ['?xsolo=music', null],
  ];
  let ok = true;
  for (const [inp, want] of cases) {
    const got = soloView(inp);
    if (got !== want) { ok = false; console.log('   soloView(' + JSON.stringify(inp) + ') = ' + got + ', want ' + want); }
  }
  check('soloView decision table (13 cases incl. junk/null totality)', ok);
}

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
