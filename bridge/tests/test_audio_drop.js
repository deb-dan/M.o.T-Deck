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
const at = html.indexOf('window.motdeckNativeAudioDrop');
check('the panel defines window.motdeckNativeAudioDrop', at > 0);
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
      /feed\('voice', 'clip ' \+ \(j\.name \|\| stem\)/.test(body));
check('feed escapes the clip name at its HTML boundary exactly once',
      require('./_panel_source').extractFunction(html, 'feed').includes('${esc(msg)}')
      && !/esc\(j\.name \|\| stem\)/.test(body));
check('it refreshes the voice library so an open clip picker shows the new chip',
      /loadVoiceLib\(true\)/.test(body));

// THE load-bearing negative: no pin is written on drop.
check('NO auto-pin: the handler never calls setEntryRef',
      body.indexOf('setEntryRef') < 0);
check('NO auto-pin: the handler never posts to /api/voice/entry-ref',
      body.indexOf('entry-ref') < 0);

check('the image drop path is untouched (still its own hook)',
      /window\.motdeckNativeDrop = function\(name, dataUrl\)/.test(html));

// ── the Swift half ──
check('the shell routes audio drops to motdeckNativeAudioDrop',
      /motdeckNativeAudioDrop/.test(swift));
check('the shell accepts the same four suffixes',
      /audioMimes = \["wav": "audio\/wav", "mp3": "audio\/mpeg",[\s\S]{0,80}"flac": "audio\/flac", "m4a": "audio\/mp4"\]/
        .test(swift));
check('the shell caps audio at 15 MB, documents at 10 MB, and images at 8 MB',
      /isAudio \? 15 \* 1024 \* 1024 : \(isFile \? 10 \* 1024 \* 1024 : 8 \* 1024 \* 1024\)/.test(swift));
check('the bridge cap really is 15 MB',
      /REF_AUDIO_MAX_BYTES = 15 \* 1024 \* 1024/
        .test(fs.readFileSync(path.join(ROOT, 'bridge', 'voice.py'), 'utf8')));

// ── split-view shell (v2) ──
// v1 had TWO strips and a "left always wins" collision rule. v2 deletes the right
// pane's mini strip and routes the ONE strip to the focused pane, swapping on collision.
// These greps were updated with that redesign — the facts they pinned genuinely changed.
check('exactly ONE tab strip is built from the titles array',
      // 2026-08-20: tabTitles is DERIVED from the single `tabs` table (title + url per
      // row) rather than being a literal array. 2026-08-21 (STUDIO PHASE 2): `tabs` is a
      // VAR — the strip is rebuilt from the nav model — so tabTitles became a COMPUTED
      // var over it. Both facts genuinely changed; still one strip, still one source.
      /var tabTitles: \[String\] \{ tabs\.map \{ \$0\.title \} \}/.test(swift) &&
      (swift.match(/labels: tabTitles/g) || []).length === 1);

// ── tab-count generalization (standing rule, Debi 2026-08-20) ──
// Every tab must inherit every tab behaviour BY CONSTRUCTION. These pin the absence of
// hardcoded counts, not the presence of any particular tab.
check('one table declares every tab (id + title + url together)',
      /struct MOTDeckTab \{[\s\S]{0,120}let title: String[\s\S]{0,120}let url: URL/.test(swift) &&
      /let id: String/.test(swift) &&
      // PHASE 2: the table split in two — the REGISTRY (everything that CAN be a tab)
      // and the strip, which is a var rebuilt from the nav model.
      /let tabRegistry: \[MOTDeckTab\] = \[/.test(swift) &&
      // …and since the 9+3 ruling the strip's first draw is the PINS PLUS THE WINDOW,
      // because the window's seed is on the default strip.
      /var tabs: \[MOTDeckTab\] = tabsFor\(navDefaultTopbar \+ navDefaultMru\)/.test(swift));
check('the two optional component tabs are rows in that table',
      /MOTDeckTab\(id: "comfyui", title: "ComfyUI", url: URL\(string: "http:\/\/127\.0\.0\.1:8188"\)!\)/.test(swift) &&
      // 8899, NOT upstream's 8888: that port belongs to Debi's standalone Unsloth app and
      // the start script's listener-scoped port clear would kill it. Same number as
      // motdeck.yaml (contract test pins that side).
      /MOTDeckTab\(id: "unsloth", title: "Unsloth", url: URL\(string: "http:\/\/127\.0\.0\.1:8899"\)!\)/.test(swift));
check('...and the shell never points a tab at :8888 again',
      !/127\.0\.0\.1:8888/.test(swift));
// ⚠️ TITLED "Music Classic" SINCE THE CONSOLIDATION SLICE (Debi 2026-08-29: ONE Music
// door, both looks). THE ID AND THE URL DID NOT MOVE — the page is byte-untouched and
// still loads chromeless; what changed is which tab is called "Music" (the Studio, id
// `compose`) and that this one is reached from that page's header switcher.
// v1.5.60: the Classic shell tab is GONE (Debi hit ⋯ -> a second Music tab).
// Classic loads ?solo=music IN the one Music tab via the header dropdown.
check('Music Classic has NO shell tab (v1.5.60) — Classic rides the Music tab in place',
      !/MOTDeckTab\(id: "music"/.test(swift) && /solo=music/.test(swift) === false
      || (!/MOTDeckTab\(id: "music"/.test(swift)));
check('...and the Studio is THE "Music" tab, at our own /compose page',
      /MOTDeckTab\(id: "compose", title: "Music", url: URL\(string: "http:\/\/127\.0\.0\.1:8700\/compose"\)!\)/.test(swift));
check('special tabs are looked up BY ID, never written as a literal index',
      // PHASE 2: by ID rather than by title — the strip can be reordered now, and an id
      // survives a rename as well as a reorder. Strictly stronger than the title lookup.
      /var odysseusTab: Int \{ tabs\.firstIndex\(where: \{ \$0\.id == odysseusId \}\) \?\? -1 \}/.test(swift) &&
      /var hermesTab: Int \{ tabs\.firstIndex\(where: \{ \$0\.id == hermesId \}\) \?\? -1 \}/.test(swift));
check('...and an absent named tab degrades to -1 (never matches) rather than to tab 0',
      !/firstIndex\(where: \{ \$0\.id == (odysseusId|hermesId) \}\) \?\? 0/.test(swift));
check('the primaries are built FROM the registry, so a new row needs no code here',
      /for t in tabRegistry \{/.test(swift) &&
      /wvById\[t\.id\] = WKWebView\(frame: \.zero, configuration: WKWebViewConfiguration\(\)\)/.test(swift));
check('webViewFor / allWebViews / urlForTab are table lookups, not switch tables',
      /func webViewFor\(_ idx: Int\) -> WKWebView \{[\s\S]{0,300}if let wv = wvById\[tabs\[idx\]\.id\] \{ return wv \}/.test(swift) &&
      /func allWebViews\(\) -> \[WKWebView\] \{ return Array\(wvById\.values\) \}/.test(swift) &&
      /func urlForTab\(_ idx: Int\) -> URL \{[\s\S]{0,200}return tabs\[idx\]\.url/.test(swift));
check('lazy load is ONE generic path keyed by a Set of IDS, not a flag per tab',
      // PHASE 2: keyed by id, which is what makes a reorder unable to make the shell
      // think a loaded page is unloaded (or reload one that is already there).
      /var loadedTabs = Set<String>\(\)/.test(swift) &&
      /guard !loadedTabs\.contains\(id\) else \{ return \}/.test(swift) &&
      !/var (odyLoaded|vsLoaded|vbLoaded) /.test(swift));
// REGRESSION FENCE (2026-08-21): the old `(wvById[id] ?? panelWV).load(...)` would, for
// an unmapped id, load that tab's URL INTO MISSION CONTROL — losing the bridge-wait
// surface and the drop target, and leaving the asking tab showing the panel. That is
// exactly the symptom "the LOffice tab shows MOT Main", so it must be unrepresentable.
check('a tab with no webview REFUSES to load, and never loads into the panel',
      /guard let wv = wvById\[id\] else \{[\s\S]{0,240}return\n\s*\}/.test(swift) &&
      /wv\.load\(URLRequest\(url: urlForTab\(idx\)\)\)/.test(swift) &&
      !/\(wvById\[id\] \?\? panelWV\)\.load/.test(swift));
check('...and does not mark itself loaded, so ⌘R or a re-select can still succeed',
      swift.indexOf('guard let wv = wvById[id] else {') <
      swift.indexOf('loadedTabs.insert(id)'));
check('no per-tab webview properties survive for the optional SPAs',
      !/\bvsWV\b/.test(swift) && !/\bvbWV\b/.test(swift));
check('urlFor resolves a primary by ID, so a new tab needs no identity branch',
      /if let hit = wvById\.first\(where: \{ \$0\.value === wv \}\) \{ return urlForId\(hit\.key\) \}/.test(swift));
check('Mission Control stays tab 0 by construction and keeps the sole drop overlay',
      /let panelTab = 0/.test(swift) &&
      /\(leftWV === panelWV\) \? leftHost/.test(swift));
check('no hardcoded tab count anywhere (the old `% 5` class of bug)',
      !/% 5\b/.test(swift) && !/< 5\b/.test(swift));
check('the right pane\'s mini strip is gone',
      !/rightSeg/.test(swift) && !/rightTabChanged/.test(swift));
check('the split state is persisted under all four v2 keys',
      /"motdeck\.split\.on"/.test(swift) && /"motdeck\.split\.right"/.test(swift) &&
      /"motdeck\.split\.left"/.test(swift) && /"motdeck\.split\.focus"/.test(swift));
check('the split view autosaves its divider',
      /autosaveName = "motdeck-split"/.test(swift));
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
      !/motdeck\.split\.drag/.test(swift));
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
      // PHASE 2: keyed by ENTRY ID — an index would repoint under a rebuilt strip.
      /var secondInstances: \[String: WKWebView\] = \[:\]/.test(swift));
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
check('...and is keyed by the tab\'s ID, so a strip rebuild cannot repoint it',
      /func ghostFor\(_ idx: Int\)[\s\S]{0,200}let id = tabId\(idx\)[\s\S]{0,120}secondInstances\[id\]/.test(swift));
check('a second instance is a PLAIN WKWebView, not a DropWebView',
      !/func ghostFor\([\s\S]{0,600}DropWebView/.test(swift));
check('a second instance loads its own tab URL through the shared tab→URL table',
      /func urlForTab\(_ idx: Int\) -> URL/.test(swift) &&
      /func ghostFor\([\s\S]{0,700}wv\.load\(URLRequest\(url: urlForTab\(idx\)\)\)/.test(swift));
check('urlFor asks the ghost table FIRST (else a ⌘R on a copy would go to the bridge)',
      /func urlFor\(_ wv: WKWebView\) -> URL[\s\S]{0,500}secondInstances\.first\(where: \{ \$0\.value === wv \}\)[\s\S]{0,60}urlForId\(hit\.key\)/
        .test(swift));
check('⌘R reloads the COPY when the focused pane is showing one',
      /func visibleWebView\(\)[\s\S]{0,400}rightIsGhost \? secondInstances\[tabId\(rightTab\)\] : webViewFor\(rightTab\)/.test(swift) &&
      /if leftIsGhost \{ return secondInstances\[tabId\(currentTab\)\] \}/.test(swift));
// Memory discipline — the primary is never destroyed, the copy always is.
check('destroyGhost stops loading, unparents, and drops the only strong reference',
      /func destroyGhost\(_ id: String\)[\s\S]{0,500}secondInstances\.removeValue\(forKey: id\)[\s\S]{0,400}g\.stopLoading\(\)[\s\S]{0,300}g\.removeFromSuperview\(\)/
        .test(swift));
check('destroyGhost forgets a failed load so the set cannot leak identifiers',
      /func destroyGhost\([\s\S]{0,500}failedLoads\.remove\(ObjectIdentifier\(g\)\)/.test(swift));
check('releaseUnusedGhosts iterates a COPY of the keys (the dict is mutated inside)',
      /func releaseUnusedGhosts\(\)[\s\S]{0,200}for id in Array\(secondInstances\.keys\)/.test(swift));
check('a copy is kept only while a pane\'s ghost flag claims it',
      /func releaseUnusedGhosts\([\s\S]{0,500}let keptLeft = leftIsGhost && id == tabId\(currentTab\)[\s\S]{0,200}let keptRight = splitOn && rightIsGhost && id == tabId\(rightTab\)[\s\S]{0,160}destroyGhost\(id\)/
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
      !/motdeck\.split\.ghost/.test(swift) &&
      (swift.match(/"motdeck\.split\.[a-z]+"/g) || [])
        .every(k => ['"motdeck.split.on"', '"motdeck.split.left"',
                     '"motdeck.split.right"', '"motdeck.split.focus"'].includes(k)));
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
      /loadedTabs\.insert\(id\)[\s\S]{0,300}if id == hermesId \{ syncHermesGen\(reloadIfNewer: false\) \}/.test(swift) &&
      /func retryIfFailed[\s\S]{0,240}wv === hermesWV \{ syncHermesGen\(reloadIfNewer: false\) \}/
        .test(swift) &&
      /func reloadTab[\s\S]{0,700}wv === hermesWV \{ syncHermesGen\(reloadIfNewer: false\) \}/
        .test(swift));
check('the reload announces itself in the house log idiom, saying what triggered it',
      /\[hermes\] reload -> config generation \\\(gen\) \(\\\(why\)\)/.test(swift));
check('no new UserDefaults key was invented for any of this',
      !/motdeck\.hermes\.gen/.test(swift) && !/motdeck\.hermes\.config/.test(swift));

// ── the SPLIT-VIEW gap: a poll, gated on Hermes actually being on screen ──
// maybeReloadStaleHermes only runs when a tab BECOMES visible, so a Hermes pane sitting
// beside Mission Control was never checked (Debi's own layout: toggle a toolset, wait
// five minutes, Hermes's Skills page still says `inactive`). A repeating timer now asks
// the SAME question while a Hermes surface is visible — and must not exist otherwise.
const tim = swift.slice(swift.indexOf('func updateHermesGenTimer'),
                        swift.indexOf('func syncStrip'));
check('there is exactly ONE Hermes poll and ONE place that arms it',
      (swift.match(/func updateHermesGenTimer/g) || []).length === 1
      && (swift.match(/updateHermesGenTimer\(\)/g) || []).length === 3   // decl + 2 calls
      // PHASE 2 added a SECOND timer — the nav poll — so this is no longer "the only
      // scheduledTimer in the file". It is still the only HERMES one, and the nav one is
      // armed from exactly one place too (see the nav section below).
      // ⚠️ WIDENED 2 → 3 BY THE DEPENDENCY-SIGNAL SLICE (S22), with the argument this
      // fence exists to demand. The third is `depsTimer`, and it earns its place the way
      // the other two did: it is the ONLY deps poll, it is armed from applyPanes and
      // nowhere else, it invalidates itself the moment no tab that could carry a banner
      // is on screen, and every one of those properties is asserted in full by
      // bridge/tests/test_dep_signal.py. This number is a CEILING on new pollers rather
      // than a detail — raising it must always cost a paragraph like this one.
      && (swift.match(/Timer\.scheduledTimer/g) || []).length === 3
      && (swift.match(/depsTimer = Timer\.scheduledTimer/g) || []).length === 1
      && (swift.match(/hermesGenTimer = Timer\.scheduledTimer/g) || []).length === 1);
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
// ⚠️ THE TAIL OF applyPanes IS NOW TWO ARMINGS, NOT ONE (S22): the dependency poll is
// armed from the same place and for the same reason, so the assertion is "the Hermes
// arming is the LAST THING applyPanes does apart from the other armings", not "the very
// last line". Widening it this way keeps what the check is for — no second rule for
// what is on screen — while allowing a sibling that obeys the same rule.
check('arming happens from applyPanes — the one place that settles what is visible',
      /applyPanes[\s\S]{0,3200}updateHermesGenTimer\(\)\s*\n[\s\S]{0,600}\n\s*\}/.test(swift)
      && /updateHermesGenTimer\(\)[\s\S]{0,400}updateDepsTimer\(\)/.test(swift));
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
      /secondInstances\[hermesId\]/.test(vis) && /out\.append\(hermesWV\)/.test(vis));
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
// It is registered on OUR OWN pages only: the panel, plus the first-party documents our
// bridge serves (LOffice, Aider, Goose, Generate — whose own menus ask for a tab the
// same way the sidebar does). That is TWO registration sites — the panel's, and one arm
// of the registry loop gated on an explicit id list. THAT GATE IS THE SECURITY PROPERTY:
// a third-party component page must never be able to drive our tab strip.
check('the handler is registered on the panel configuration',
      /let panelCfg = WKWebViewConfiguration\(\)[\s\S]{0,400}panelCfg\.userContentController\.add\(self, name: "motdeck"\)[\s\S]{0,300}panelWV = DropWebView\(frame: \.zero, configuration: panelCfg\)/.test(swift));
// ⚠️ WIDENED AT THE GOOSE SLICE, and it is still the same closed gate: the arm names
// an EXPLICIT list of our own first-party bridge pages, and every other webview gets a
// bare configuration. Goose is the third (loffice, aider, goose) — a pty terminal in
// our own document, whose page must be able to ask the shell to switch tabs.
// ⚠️ WIDENED AGAIN AT THE COMFY-NAV SLICE, and STILL the same closed gate — the count
// of registration sites is unchanged (two), and the arm still names every id
// explicitly. `comfy` is the fourth (loffice, aider, goose, comfy): our own /comfy
// Generate page, served by the bridge from the panel's origin. A fifth id may only be
// added here by someone who can say, at main.swift's arm, why that page is ours.
// ⚠️ WIDENED AGAIN AT THE COMPOSE SLICE, and STILL the same closed gate — the count of
// registration sites is unchanged (two) and the arm still names every id explicitly.
// `compose` is the fifth (loffice, aider, goose, comfy, compose): our own /compose page,
// served by the bridge from the panel's origin. A sixth id may only be added here by
// someone who can say, at main.swift's arm, why that page is ours.
// ⚠️ WIDENED AGAIN AT THE GOOSE UI SLICE, and STILL the same closed gate — the count of
// registration sites is unchanged (two) and the arm still names every id explicitly.
// `gooseui` is the sixth, and it is the one whose argument is NOT "we wrote it": the
// bundle in that tab is goose Desktop's own renderer, vendored unmodified. What makes it
// ours is the ORIGIN (:8700, digest-pinned on disk, re-verified by the contract suite)
// and the one preload script we inject into it. A seventh id may only be added here by
// someone who can say, at main.swift's arm, why that page is ours.
check('...and on our own LOffice/Aider/Goose CLI/Generate/Compose/Goose UI pages, on nothing else',
      (swift.match(/userContentController\.add\(self, name: "motdeck"\)/g) || []).length === 2
      && /else if t\.id == "loffice" \|\| t\.id == "aider" \|\| t\.id == "goose"\s*\n?\s*\|\| t\.id == "comfy" \|\| t\.id == "compose" \|\| t\.id == "gooseui" \{[\s\S]{0,400}c\.userContentController\.add\(self, name: "motdeck"\)/.test(swift));
check('...so no other webview\'s configuration carries it',
      !/odyCfg\.userContentController\.add\(self/.test(swift)
      // the generic arm — every third-party component page — gets a BARE configuration.
      && /else \{ wvById\[t\.id\] = WKWebView\(frame: \.zero, configuration: WKWebViewConfiguration\(\)\) \}/.test(swift));
// The shell tells the panel what it can do, so a panel NEWER than the shell is
// detectable instead of silently no-op (and never falls through to the default browser).
check('the shell injects its own capability record into its first-party pages',
      /let shellAPI = \d+/.test(swift)
      && /window\.motdeckShell=\{api:\\\(shellAPI\),tabs:\[\\\(shellIds\)\]\};/.test(swift)
      && /let shellIds = tabRegistry\.map \{ "\\"\\\(\$0\.id\)\\"" \}\.joined\(separator: ","\)/.test(swift)
      && /injectionTime: \.atDocumentStart, forMainFrameOnly: true/.test(swift));
check('...the tab list it publishes is the REGISTRY, not the visible strip',
      /shellIds = tabRegistry\.map/.test(swift) && !/shellIds = tabs\.map/.test(swift));
check('...and it is added to the panel and to our own bridge pages, nowhere else',
      (swift.match(/addUserScript\(shellScript\)/g) || []).length === 2);
check('it accepts only the "motdeck" message name',
      /message\.name == "motdeck"/.test(handlerBody));
check('switchTab resolves an ID (title as the fallback) against the REGISTRY',
      // PHASE 2: the id is the stable key and the registry — not the visible strip — is
      // what it resolves against, so a tab the user hid is still reachable from its
      // sidebar row (shown for the session, exactly as the ⋯ menu does it).
      /body\["title"\] as\? String/.test(handlerBody)
      && /body\["id"\] as\? String/.test(handlerBody)
      && /tabRegistry\.contains\(where: \{ \$0\.id == w \}\)/.test(handlerBody)
      && /tabRegistry\.first\(where: \{ \$0\.title == t \}\)\?\.id/.test(handlerBody));
check('...a hidden tab is SHOWN rather than ignored (it takes a window slot, exactly '
    + 'as the \u22ef menu does it — a sidebar row and a menu item must leave the strip '
    + 'in the SAME state)',
      /if !tabs\.contains\(where: \{ \$0\.id == hit \}\) \{[\s\S]{0,400}touchWindow\(hit\)[\s\S]{0,60}rebuildTabs\(\)/.test(handlerBody));
check('an unknown tab is ignored, never coerced to a tab',
      /else \{[\s\S]{0,160}unknown tab[\s\S]{0,60}return/.test(handlerBody)
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
      // PHASE 2: the table is DERIVED from the one nav registry rather than written a
      // second time — a component's tab title now exists in exactly one place.
      /const TAB_FOR_COMPONENT = \{\};/.test(html)
      && /NAV_ENTRIES\.forEach\(e => \{ if \(e\.kind === 'component' && e\.tab\) TAB_FOR_COMPONENT\[e\.id\] = e\.tab; \}\);/.test(html)
      && /id:'odysseus',\s+label:'Odysseus',[\s\S]{0,120}tab:'Odysseus'/.test(html)
      && /tab:'ComfyUI'/.test(html) && /tab:'Unsloth'/.test(html));
check('...and searxng, which has no tab, is absent from it',
      !/id:'searxng'/.test(html) && !/searxng: '/.test(html));
const oc = html.slice(html.indexOf('function openComponent('),
                      html.indexOf('function openMusic('));
check('openComponent reads running state at CLICK time, not from the rendered row',
      /lastStatus && lastStatus\.components/.test(oc));
check('...a RUNNING component opens its tab',
      /c\.running && title\) \{/.test(oc)
      && /shellKnowsTab\(name\) !== false && switchTab\(title, name\)/.test(oc));
check('...and a stale shell SAYS so rather than silently landing on the card',
      /if \(inNativeApp\(\)\) navShellNote\(name, SHELL_STALE_NOTE\);/.test(oc));
check('...and everything else falls back to jumpToCard (browser, stopped, no tab)',
      /jumpToCard\(name\)/.test(oc));
check('switchTab returns false when the native bridge is absent',
      /function switchTab\(title, id\)[\s\S]{0,300}if \(!h\) return false/.test(html));
check('the sidebar rows call openComponent, not jumpToCard directly',
      // PHASE 2: the rows are rendered from the nav model, so the call site moved into
      // renderSidebar — the rule (a component row goes through openComponent) is the same.
      /onclick="openComponent\(\$\{apiArg\(name\)\}\)"/.test(html));
// ⚠️ REWRITTEN AT THE CONSOLIDATION SLICE. The RULE is unchanged and is what this has
// always guarded: the Classic surface routes to its native tab and falls back to the
// in-panel view, so it can never become a dead control. What moved is the ENTRY POINT —
// there is no `music` sidebar row any more (ONE Music door), so the caller is the
// Studio page's header switcher and ⌘K, and the function is named for that.
// REVISED (v1.5.50, Debi's live feedback): the ruling CHANGED — Studio<->Classic swap
// IN PLACE inside the one Music tab; a switchTab here parked a second Music tab in a
// strip window slot (the two-Music-tabs pollution). The fence now pins the revision:
// no switchTab in either direction; the solo document navigates, the panel showViews.
check('the Music Classic route is in-panel only — no switchTab (v1.5.50 revision)',
      /function openMusicClassic\(\)[\s\S]{0,220}showView\('music'\)/.test(html)
      && !/function openMusicClassic\(\)[\s\S]{0,420}switchTab\(/.test(html));
check('...and openMusicStudio navigates IN PLACE from the solo document, navOpen elsewhere',
      /function openMusicStudio\(\) \{[\s\S]{0,260}solo=music[\s\S]{0,120}location\.href = '\/compose'[\s\S]{0,120}navOpen\('compose'\)/.test(html));

// ── STUDIO PHASE 2: the strip is a VIEW of the nav model ──
// The shell cannot read the panel's localStorage, so data/nav.json is the shared copy.
// These pin the properties that make a rebuild safe: it reloads nothing, it cannot lose
// Mission Control, and nothing it hides becomes unreachable.
check('the strip is rebuilt from the pinned list, not from a literal table',
      /func rebuildTabs\(\)/.test(swift)
      // …through ONE derivation since the 9+3 ruling: pins, then the window.
      && /func stripIds\(\) -> \[String\]/.test(swift)
      && /var pins = navPinned\.filter/.test(swift)
      && /let ids = stripIds\(\)/.test(swift)
      && /tabs = tabsFor\(ids\)/.test(swift)
      && /seg\.segmentCount = tabs\.count/.test(swift)
      && /seg\.setLabel\(t\.title, forSegment: i\)/.test(swift));
check('...and the widths are recomputed, so segmentAt still hit-tests the real strip',
      /func rebuildTabs\(\)[\s\S]{0,1600}setSegmentWidths\(\)/.test(swift));
check('a rebuild remembers each pane BY ID, so reordering never moves what you see',
      /func rebuildTabs\(\)[\s\S]{0,300}let keepLeft = tabId\(currentTab\)[\s\S]{0,120}let keepRight = tabId\(rightTab\)/.test(swift)
      && /currentTab = tabs\.firstIndex\(where: \{ \$0\.id == keepLeft \}\) \?\? 0/.test(swift));
check('Mission Control cannot be lost from the strip, whatever the file says',
      /func stripIds\([\s\S]{0,900}pins\.removeAll \{ \$0 == panelId \}[\s\S]{0,60}pins\.insert\(panelId, at: 0\)/.test(swift));
// ⚠️ THE MECHANISM CHANGED AT THE 9+3 RULING, THE PROMISE DID NOT: un-pinning the tab
// you are LOOKING AT does not yank the page out from under you. It used to be appended
// to an unbounded session list; it now takes a WINDOW slot, which is where it would go
// if you had opened it from ⋯ anyway.
check('a tab that is on screen stays on the strip even after it is un-pinned',
      /func rebuildTabs\([\s\S]{0,900}for id in \(splitOn \? \[keepLeft, keepRight\] : \[keepLeft\]\) \{ touchWindow\(id\) \}/.test(swift));
// ══ THE LAST-THREE WINDOW ITSELF (Debi's ruling 2026-08-29) ══════════════════════
// The creep this ends: `tempShown` was UNBOUNDED, so a strip whose rule said "at most
// 12" routinely drew fourteen.
check('the strip is BOUNDED: nine pins + at most three window slots',
      /let navWindowMax = 3/.test(swift)
      && /func stripIds\([\s\S]{0,600}if ids\.count - pins\.count >= navWindowMax \{ break \}/.test(swift)
      && !/var tempShown/.test(swift));
check('...and opening a tab already on the strip moves NOTHING (no re-sort under the pointer)',
      /func touchWindow\([\s\S]{0,300}if stripIds\(\)\.contains\(id\) \{ return false \}/.test(swift));
check('...the newest takes the first slot and the oldest is dropped',
      /func touchWindow\([\s\S]{0,500}navWindow\.insert\(id, at: 0\)[\s\S]{0,200}navWindow\.removeLast/.test(swift));
check('...and it is PERSISTED through the bridge, so a relaunch keeps the swap',
      /func postWindow\(_ id: String\)/.test(swift)
      && /api\/nav\/mru/.test(swift)
      && /req\.httpMethod = "POST"/.test(swift));
check('...fire-and-forget: a bridge that is down costs the persistence, never the swap',
      /func touchWindow\([\s\S]{0,600}if persist \{ postWindow\(id\) \}/.test(swift));
check('...and the shell reads the window back from the bridge, which owns the rule',
      /nav\["mru"\] as\? \[String\]/.test(swift)
      && /func applyNav\(_ ids: \[String\], _ window: \[String\]\)/.test(swift));
// ⚠️ FENCE MOVED, v1.5.26 — the ⋯ button used to hide itself whenever no tab was
// hidden. That was right while it did exactly one thing; it now also carries "Hide Tab
// Bar" (Debi's affordance for the strip toggle), and a menu that only exists when an
// unrelated condition holds is not a discoverable home for anything. The old meaning is
// not lost — the menu STATES "No hidden tabs" instead of implying it by absence, which
// is the assertion below.
check('hidden tabs collect in a ⋯ overflow menu, which is always reachable',
      /overflowButton = NSButton\(title: "⋯"/.test(swift)
      && /func hiddenTabs\(\) -> \[MOTDeckTab\][\s\S]{0,200}tabRegistry\.filter/.test(swift)
      && /overflowButton\.isHidden = false/.test(swift)
      && /NSMenu\(\)/.test(swift));
check('...and it SAYS there are none rather than vanishing',
      /"No hidden tabs"/.test(swift));

// ── v1.5.26: HIDE / SHOW THE NATIVE TAB STRIP (Debi) ────────────────────────────
check('the strip height is ONE constant, held as a constraint so it can be driven to 0',
      /let tabBarHeight: CGFloat = 44/.test(swift)
      && /tabBarH = tabBar\.heightAnchor\.constraint\(equalToConstant: tabBarHeight\)/.test(swift)
      && /tabBarH\.constant = show \? tabBarHeight : 0/.test(swift));
check('...and a 0pt strip is also isHidden, so it cannot still take a click',
      /tabBar\.isHidden = !show/.test(swift));
check('the preference is persisted and restored BEFORE the panes lay out (no flash)',
      /UserDefaults\.standard\.set\(tabBarHidden, forKey: "motdeck\.tabbar\.hidden"\)/.test(swift)
      && /tabBarHidden = ud\.bool\(forKey: "motdeck\.tabbar\.hidden"\)/.test(swift)
      && swift.indexOf('tabBarHidden = ud.bool(forKey: "motdeck.tabbar.hidden")')
         < swift.indexOf('let wasSplit = ud.bool'));
check('BOTH entry points exist: a View-menu item carrying ⌘⇧T, and the ⋯ menu',
      /NSMenuItem\(title: "Hide Tab Bar",\s*\n?\s*action: #selector\(AppDelegate\.toggleTabBar\(_:\)\), keyEquivalent: "t"\)/.test(swift)
      && /tabBarItem\.keyEquivalentModifierMask = \[\.command, \.shift\]/.test(swift)
      && /title: tabBarHidden \? "Show Tab Bar" : "Hide Tab Bar"/.test(swift));
// ⌘⇧T was checked against every binding this app and the panel already own: ⌘R, ⌘Q,
// ⌘C/⌘V/⌘A here and ⌘K / ⌘\ in the panel. The two "t" sites are the SAME action shown
// in two places (the View menu owns the working binding; the ⋯ item shows it).
check('⌘⇧T is unclaimed by every OTHER binding this shell owns',
      (swift.match(/keyEquivalent: "t"/g) || []).length === 2
      && (swift.match(/keyEquivalentModifierMask = \[\.command, \.shift\]/g) || []).length === 2
      && (swift.match(/#selector\((?:AppDelegate\.)?toggleTabBar\(_:\)\), keyEquivalent: "t"/g) || []).length === 2
      && !/keyEquivalent: "([^t])"[^\n]*\n[^\n]*\.shift/.test(swift));
check('the menu item names the ACTION, not the state (the chevron lesson)',
      /it\.title = tabBarHidden \? "Show Tab Bar" : "Hide Tab Bar"/.test(swift));
check('the hover reveal is a mouse-moved MONITOR (a tracking area would have to sit on '
    + 'top of a WKWebView), armed only while the strip is hidden',
      /addLocalMonitorForEvents\(matching: \[\.mouseMoved\]\)/.test(swift)
      && /window\.acceptsMouseMovedEvents = true/.test(swift)
      && /guard on else \{ return \}/.test(swift)
      && /if let m = tabPeekMonitor \{ NSEvent\.removeMonitor\(m\); tabPeekMonitor = nil \}/.test(swift));
check('...and it closes when the pointer leaves the STRIP, not the 4pt trigger — '
    + 'otherwise it would snap shut the instant it opened under the pointer',
      /y >= top - 4/.test(swift) && /y < top - s\.tabBarHeight/.test(swift));
check('a peek is NEVER persisted — only the deliberate toggle writes', (() => {
  const i = swift.indexOf('func applyTabBar(peeking: Bool = false)');
  const j = swift.indexOf('@objc func toggleTabBar(', i);
  return i > 0 && j > i && !swift.slice(i, j).includes('UserDefaults');
})());
// ⚠️ "SESSION ONLY" BECAME "SWAPPED AND PERSISTED" AT THE 9+3 RULING, AND THAT IS THE
// RULING ITSELF: picking from ⋯ swaps the tab into the last-three window, which is
// saved. What this still guards is the half that must never change — picking from ⋯
// does NOT re-pin anything, so the user's nine pins are untouched by using the app.
check('...and picking one SWAPS it into the window without ever touching the pins',
      /func overflowPick\([\s\S]{0,400}touchWindow\(id\)[\s\S]{0,200}rebuildTabs\(\)/.test(swift)
      && !/func overflowPick\([\s\S]{0,400}navPinned =/.test(swift));
check('the overflow menu sits beside ⫽, at the strip\'s right end',
      /overflowButton\.trailingAnchor\.constraint\(equalTo: splitButton\.leadingAnchor/.test(swift));
check('the nav poll rides the EXISTING /api/status carrier (a nav_gen counter)',
      /obj\["nav_gen"\] as\? Int/.test(swift)
      && /func syncNav\(force: Bool\)/.test(swift)
      && /func fetchNav\(\)/.test(swift));
check('...and only a STRICT increase costs the second request',
      /func syncNav\([\s\S]{0,1200}let prev = self\.navGen[\s\S]{0,120}self\.navGen = gen[\s\S]{0,200}guard let p = prev, gen > p else \{ return \}/.test(swift));
check('...FAIL SAFE: an error, a non-200 or a missing field changes nothing',
      /func fetchNav\(\)[\s\S]{0,600}guard err == nil,[\s\S]{0,300}statusCode == 200,[\s\S]{0,300}else \{ return \}/.test(swift));
check('the poll is armed from exactly one place and pauses while the app is not frontmost',
      (swift.match(/startNavPoll\(\)/g) || []).length === 2       // decl + the one call
      && /navTimer = Timer\.scheduledTimer/.test(swift)
      && /guard navTimer == nil else \{ return \}/.test(swift)
      && /func startNavPoll\(\)[\s\S]{0,600}if !NSApp\.isActive \{ return \}/.test(swift));
check('the panel PUSHES a layout change so the strip does not wait for the poll',
      /case "navChanged":/.test(swift) && /syncNav\(force: true\)/.test(swift)
      && /cmd:'navChanged'/.test(html));
check('applyNav no-ops when nothing changed (the poll can run forever safely)',
      /func applyNav\(_ ids: \[String\], _ window: \[String\]\)[\s\S]{0,400}guard !clean\.isEmpty, clean != navPinned \|\| win != navWindow else \{ return \}/.test(swift));
check('the arrangement is persisted by ID as well as by index (an index is strip-relative)',
      /ud\.set\(tabId\(currentTab\), forKey: "motdeck\.split\.leftId"\)/.test(swift)
      && /ud\.set\(tabId\(rightTab\), forKey: "motdeck\.split\.rightId"\)/.test(swift)
      && /tabs\.firstIndex\(where: \{ \$0\.id == savedLeftId \}\)/.test(swift));
// v1.5.26 — DEBI'S ORDER. The same eleven ids in a new reading order; bridge/nav.py's
// DEFAULT_TOPBAR and the panel's NAV_DEFAULT_TOPBAR carry the same list, and
// test_nav_model.py is the fence that compares all three.
// ⚠️ NINE PINS + A TWO-ENTRY WINDOW SEED SINCE THE 9+3 RULING — the same ELEVEN TABS,
// with the Music surface (id `compose`) where Music was.
check('the default strip is still the eleven default tabs, in Debi\'s order',
      /let navDefaultTopbar = \["mc", "hermes", "unsloth", "opencode", "odysseus",\s*\n?\s*"voicestudio", "comfyui", "aider", "loffice"\]/.test(swift)
      && /let navDefaultMru = \["compose", "voicebox"\]/.test(swift));
check('the three pinnable VIEWS load the panel chromeless, one per view',
      /MOTDeckTab\(id: "chat", title: "Chat", url: URL\(string: "http:\/\/127\.0\.0\.1:8700\/\?solo=chat"\)!\)/.test(swift)
      && /MOTDeckTab\(id: "models",[\s\S]{0,80}\?solo=models/.test(swift)
      && /MOTDeckTab\(id: "caps",[\s\S]{0,90}\?solo=caps/.test(swift));

// ── solo mode ──
check('soloView is pure and only knows the views solo mode declares',
      // PHASE 2: the whitelist is DERIVED from the nav registry (any entry that owns a
      // panel view can be pinned as a tab) instead of being the literal ['music'].
      // Mission Control is excluded on purpose: its native tab IS the panel.
      // v1.5.27: …AND an entry that cannot be pinned at all. `?solo=<view>` is how a
      // pinned view becomes a native TAB, so a sidebar-only entry has no solo surface.
      // Before Help, "sidebar-only" and "has no view" were the same set and the
      // exclusion happened by accident; Help is a real view that is sidebar-only, so
      // the filter has to say it.
      /const SOLO_VIEWS = NAV_ENTRIES\s*\n?\s*\.filter\(e => e\.view && e\.id !== 'mc' && NAV_SIDEBAR_ONLY\.indexOf\(e\.id\) < 0\)\s*\n?\s*\.map\(e => e\.view\)/.test(html)
      && /function soloView\(search\)/.test(html));
check('applySolo adds body.solo and pins the view, and is armed at boot',
      /document\.body\.classList\.add\('solo'\)/.test(html)
      && /applySolo\(\);/.test(html));
check('solo mode hides chrome in exactly three CSS rules and restyles nothing else',
      (html.match(/body\.solo /g) || []).length === 3
      && /body\.solo aside \{ display:none; \}/.test(html)
      && /body\.solo \.topbar \{ display:none; \}/.test(html));

// soloView EXECUTED on the shipped source — the decision table, incl. totality.
// PHASE 2: the whitelist is derived from NAV_ENTRIES, so the registry travels with it.
{
  const regStart = html.indexOf('const NAV_ENTRIES = [');
  const reg = html.slice(regStart, html.indexOf('\n];', regStart) + 3);
  // NAV_SIDEBAR_ONLY travels with the registry now: the derivation reads it.
  const sbOnly = /const NAV_SIDEBAR_ONLY = \[[^\]]*\];/.exec(html)[0];
  const src = reg + sbOnly + html.slice(html.indexOf('const SOLO_VIEWS = NAV_ENTRIES'),
                               html.indexOf('function applySolo('));
  const soloView = new Function(src + '; return soloView;')();
  const cases = [
    ['?solo=music', 'music'], ['?solo=MUSIC', 'music'], ['?a=1&solo=music', 'music'],
    ['?solo=music&b=2', 'music'], ['', null], ['?', null], ['?solo=', null],
    // the three views that PHASE 2 made pinnable are now legitimate solo targets…
    ['?solo=chat', 'chat'], ['?solo=models', 'models'], ['?solo=caps', 'caps'],
    // …and Mission Control is deliberately NOT one: its native tab is the panel itself.
    ['?solo=mc', null], ['?solo=logs', null],
    // …and neither is HELP (v1.5.27): a real view, but sidebar-only, so it can never
    // be pinned and `?solo=help` is a URL nothing in the product can produce.
    ['?solo=help', null], ['?solo=HELP', null],
    ['?solo=musicx', null], ['?notsolo=music', null],
    [null, null], [undefined, null], ['?xsolo=music', null],
  ];
  let ok = true;
  for (const [inp, want] of cases) {
    const got = soloView(inp);
    if (got !== want) { ok = false; console.log('   soloView(' + JSON.stringify(inp) + ') = ' + got + ', want ' + want); }
  }
  check('soloView decision table (20 cases incl. junk/null totality)', ok);
}

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
