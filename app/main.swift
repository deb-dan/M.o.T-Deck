// Harness.app — native macOS shell. One window, tabbed (see `tabs` below for the list).
// Each tab is its own top-level WKWebView load — sidesteps Odysseus's X-Frame-Options/
// frame-ancestors (which block iframing) entirely. Auto-starts the bridge on launch.
// Built by scripts/build_app.sh (which generates Config.swift with harnessRoot).
//
// ⚠️ STANDING RULE (Debi, 2026-08-20): every tab inherits EVERY tab behaviour by
// construction — split view, tab-drag, ghosts, ⌘R reload, lazy load and the
// "Not reachable yet" placeholder. NOTHING in this file may hardcode a tab COUNT, and
// the only tab INDICES that may be written down are the named constants derived from
// `tabs` immediately below. Adding a tab is adding one row to `tabs`.

import Cocoa
import WebKit

let bridgeURL = URL(string: "http://127.0.0.1:8700")!

// ONE table: the tab strip's labels AND the URL each tab loads. It feeds the single
// NSSegmentedControl (v2 deleted the right pane's mini strip), `urlForTab`, the
// id-keyed webview table and the ghost table — so none of them can drift from each
// other. STUDIO PHASE 2 split it in two: the REGISTRY (everything that can be a tab)
// and `tabs` (what is on the strip now), which the nav model chooses.
struct HarnessTab {
    let id: String
    let title: String
    let url: URL
}
// STUDIO PHASE 2: `tabRegistry` is every entry that CAN be a tab; `tabs` (below) is
// which of them are ON the strip right now, in the user's order, rebuilt from
// data/nav.json. The ID is the stable key — webviews are keyed by it, so reordering or
// hiding a tab never reloads a page — while the TITLE is only ever a label.
let tabRegistry: [HarnessTab] = [
    // Mission Control — the Bridge control panel. Index 0 BY CONSTRUCTION: it is the
    // app's home, the page the bridge-wait screen writes into, and the only file-drop
    // target (DropOverlay). Keep it first.
    HarnessTab(id: "mc", title: "Mission Control", url: bridgeURL),
    HarnessTab(id: "odysseus", title: "Odysseus", url: URL(string: "http://127.0.0.1:7860")!),
    HarnessTab(id: "hermes", title: "Hermes", url: URL(string: "http://127.0.0.1:9119")!),
    // Optional components — usually NOT running, so their first load normally fails into
    // the shared "Not reachable yet" placeholder and retries on re-select / ⌘R.
    HarnessTab(id: "voicestudio", title: "VoiceStudio", url: URL(string: "http://127.0.0.1:3900")!),
    HarnessTab(id: "voicebox", title: "Voicebox", url: URL(string: "http://127.0.0.1:17493")!),
    HarnessTab(id: "comfyui", title: "ComfyUI", url: URL(string: "http://127.0.0.1:8188")!),
    // :8899, NOT upstream's default :8888 — that port belongs to Debi's standalone
    // Unsloth app (harness.yaml carries the same number and the reason).
    HarnessTab(id: "unsloth", title: "Unsloth", url: URL(string: "http://127.0.0.1:8899")!),
    // OpenCode — the second coding lane. Its own server serves its own embedded SPA on
    // one loopback port (:4096; upstream's own --port DEFAULT is 0/ephemeral, so
    // start_component.sh always passes it explicitly and harness.yaml carries the same).
    //
    // ⚠️ THE URL IS THE BRIDGE, NOT :4096, AND THAT IS THE FIX for "the tab opens on
    // Nothing here yet". GET /opencode is a 307 to OpenCode's own new-session composer
    // for data/opencode-workspace — a route only the bridge can build, because only it
    // knows ROOT (repo vs snapshot) and the configured port. See opencode_landing_url
    // in bridge/app.py for why there is nothing to seed instead.
    HarnessTab(id: "opencode", title: "OpenCode",
               url: URL(string: "http://127.0.0.1:8700/opencode")!),
    // Music is OUR OWN panel page, opened chromeless: same bridge origin, ?solo=music
    // hides the sidebar + topbar and pins the panel to the Music view. It is therefore
    // a second load of the panel document, deliberately — a native tab that is always
    // reachable, while the in-panel Music view keeps working exactly as before.
    HarnessTab(id: "music", title: "Music", url: URL(string: "http://127.0.0.1:8700/?solo=music")!),
    // Aider — the coding agent, running in a pseudo-terminal. Also ours, also the
    // bridge origin, but its OWN document (/aider): it loads xterm.js and talks to
    // ws://…/api/pty/aider, so it must not carry the panel's poll loops.
    HarnessTab(id: "aider", title: "Aider", url: URL(string: "http://127.0.0.1:8700/aider")!),
    // LOffice — spreadsheets over vendored Univer, served from OUR bridge (/office).
    // Ours, bridge origin, its own document for the same reason Aider is: it loads
    // ~10MB of Univer UMD and must not carry the panel's poll loops. Debi suggested
    // "Office Lane"; the tab-strip width budget below rules a two-word title out, so
    // the name is LOffice (2026-08-21). The ROUTE stays /office: internal names do
    // not churn with a wordmark.
    HarnessTab(id: "loffice", title: "LOffice", url: URL(string: "http://127.0.0.1:8700/office")!),
    // PHASE 2: the three panel VIEWS that can be pinned to the strip. They are the same
    // chromeless `?solo=` load Music already used, generalised — the panel hides its own
    // sidebar/topbar and pins itself to that view. None of them is on the strip by
    // default (they are one sidebar click away), so this changes nothing until asked.
    HarnessTab(id: "chat", title: "Chat", url: URL(string: "http://127.0.0.1:8700/?solo=chat")!),
    HarnessTab(id: "models", title: "Models", url: URL(string: "http://127.0.0.1:8700/?solo=models")!),
    HarnessTab(id: "caps", title: "Capabilities", url: URL(string: "http://127.0.0.1:8700/?solo=caps")!),
]

// The DEFAULT strip, in order (eleven tabs since OpenCode landed, 2026-08-21). It is
// also bridge/nav.py's DEFAULT_TOPBAR pinned prefix; the two are asserted to agree by
// test, because a disagreement would mean the strip and the panel's Appearance editor
// describe different windows.
let navDefaultTopbar = ["mc", "odysseus", "hermes", "voicestudio", "voicebox",
                        "comfyui", "unsloth", "music", "aider", "loffice", "opencode"]
func tabsFor(_ ids: [String]) -> [HarnessTab] {
    return ids.compactMap { i in tabRegistry.first(where: { $0.id == i }) }
}
// THE STRIP. A `var` now: applyNav rebuilds it from data/nav.json (order + hidden), and
// every use site below reads it live rather than caching an index.
var tabs: [HarnessTab] = tabsFor(navDefaultTopbar)
var tabTitles: [String] { tabs.map { $0.title } }

// Named indices, looked up BY ID (stable across a rename and across a reorder) so
// rebuilding `tabs` can never silently repoint a behaviour at the wrong tab. `-1` when
// the tab is not on the strip, which every use site reads as "never matches" rather
// than accidentally matching tab 0 — and which is now a REAL state: a user may hide
// Hermes from the strip, in which case there is no Hermes tab to reload.
let panelId = "mc"
let odysseusId = "odysseus"
let hermesId = "hermes"
let panelTab = 0                                              // MC is pinned first (applyNav)
var odysseusTab: Int { tabs.firstIndex(where: { $0.id == odysseusId }) ?? -1 }   // the only skinned webview
var hermesTab: Int { tabs.firstIndex(where: { $0.id == hermesId }) ?? -1 }       // the only staleness-reloaded one

// The panel's gold, as the focused-pane indicator. The unfocused pane gets a strip of
// the SAME height in clear, so switching focus never moves a single pixel of content.
let paneGold = NSColor(red: 0.788, green: 0.643, blue: 0.302, alpha: 1)
let paneInk = NSColor(red: 0.043, green: 0.039, blue: 0.063, alpha: 1)
let paneFaint = NSColor(red: 0.435, green: 0.416, blue: 0.502, alpha: 1)
let paneCream = NSColor(red: 0.937, green: 0.906, blue: 0.843, alpha: 1)

// The per-pane ✕. A plain NSButton has no hover state, and this control floats over
// page content, so it must be quiet at rest and legible under the pointer.
final class PaneCloseButton: NSButton {
    private var ta: NSTrackingArea?
    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let t = ta { removeTrackingArea(t) }
        let t = NSTrackingArea(rect: bounds,
                               options: [.mouseEnteredAndExited, .activeInKeyWindow],
                               owner: self, userInfo: nil)
        addTrackingArea(t)
        ta = t
    }
    func tint(_ c: NSColor) {
        attributedTitle = NSAttributedString(string: "✕", attributes: [
            .foregroundColor: c,
            .font: NSFont.systemFont(ofSize: 11),
        ])
    }
    override func mouseEntered(with event: NSEvent) { tint(paneCream) }
    override func mouseExited(with event: NSEvent) { tint(paneFaint) }
}

// PROVEN by /tmp/harness-drag.log: macOS never delivers drag events to the WKWebView
// at all (registrations correct, draggingEntered never called). So a transparent
// sibling ABOVE the panel is the drag destination: invisible to clicks (hitTest nil),
// registered only for file drags, forwarding every phase to DropWebView's logic.
final class DropOverlay: NSView {
    weak var webView: DropWebView?
    init(webView: DropWebView) {
        self.webView = webView
        super.init(frame: .zero)
        registerForDraggedTypes([.fileURL])
    }
    required init?(coder: NSCoder) { return nil }
    override func hitTest(_ point: NSPoint) -> NSView? { return nil }   // clicks fall through
    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        return webView?.draggingEntered(sender) ?? []
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        return webView?.draggingUpdated(sender) ?? []
    }
    override func draggingExited(_ sender: NSDraggingInfo?) {
        webView?.draggingExited(sender)
    }
    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        return webView?.prepareForDragOperation(sender) ?? false
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        return webView?.performDragOperation(sender) ?? false
    }
}

// Mission Control's webview: WKWebView does not forward Finder file-drags to the DOM
// (page handlers never fire — verified: same page accepts drops in a real browser).
// So the SHELL is the drop target: catch the drag natively, read the image, and hand
// it to the page's `harnessNativeDrop(name, dataURL)` hook. The page does the real
// gating (vision model, Chat mode, size) and shows its own notes.
final class DropWebView: WKWebView {
    // diagnostic trail for the drag chain → /tmp/harness-drag.log
    private func dragLog(_ s: String) {
        let line = "\(Date()) \(s)\n"
        guard let d = line.data(using: .utf8) else { return }
        if let h = FileHandle(forWritingAtPath: "/tmp/harness-drag.log") {
            h.seekToEndOfFile(); h.write(d); h.closeFile()
        } else {
            try? line.write(toFile: "/tmp/harness-drag.log", atomically: true, encoding: .utf8)
        }
    }

    override init(frame: CGRect, configuration: WKWebViewConfiguration) {
        super.init(frame: frame, configuration: configuration)
        registerForDraggedTypes([.fileURL])
        dragLog("init: registered=\(registeredDraggedTypes.map { $0.rawValue })")
    }
    required init?(coder: NSCoder) { return nil }

    // WKWebView re-registers its OWN drag types on page load, which REPLACES any
    // registration done at init — silently dropping .fileURL and starving our
    // overrides. Guarantee .fileURL survives every re-registration.
    override func registerForDraggedTypes(_ newTypes: [NSPasteboard.PasteboardType]) {
        var types = newTypes
        if !types.contains(.fileURL) { types.append(.fileURL) }
        super.registerForDraggedTypes(types)
        dragLog("register: \(types.map { $0.rawValue })")
    }
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        registerForDraggedTypes(Array(registeredDraggedTypes))
    }

    // hover: cheap type check (file contents may not be readable mid-drag);
    // drop: actually resolve the URL.
    private func hasFile(_ sender: NSDraggingInfo) -> Bool {
        return sender.draggingPasteboard.availableType(from: [.fileURL]) != nil
    }
    private func draggedFile(_ sender: NSDraggingInfo) -> URL? {
        let opts: [NSPasteboard.ReadingOptionKey: Any] = [.urlReadingFileURLsOnly: true]
        let urls = sender.draggingPasteboard.readObjects(forClasses: [NSURL.self], options: opts) as? [URL]
        return urls?.first
    }
    private func cue(_ on: Bool) {
        let js = "var b=document.getElementById('chat-bar'); if(b) b.classList." + (on ? "add" : "remove") + "('dropping');"
        evaluateJavaScript(js, completionHandler: nil)
    }

    override func draggingEntered(_ sender: NSDraggingInfo) -> NSDragOperation {
        let types = (sender.draggingPasteboard.types ?? []).map { $0.rawValue }
        dragLog("entered: hasFile=\(hasFile(sender)) pbTypes=\(types)")
        guard hasFile(sender) else { return super.draggingEntered(sender) }
        cue(true)
        return .copy
    }
    override func draggingUpdated(_ sender: NSDraggingInfo) -> NSDragOperation {
        return hasFile(sender) ? .copy : super.draggingUpdated(sender)
    }
    // the final gate before the drop is delivered — WebKit's default says NO for
    // drags it didn't accept itself, which silently refuses our file drop.
    override func prepareForDragOperation(_ sender: NSDraggingInfo) -> Bool {
        dragLog("prepare: hasFile=\(hasFile(sender))")
        return hasFile(sender) ? true : super.prepareForDragOperation(sender)
    }
    override func draggingExited(_ sender: NSDraggingInfo?) {
        cue(false)
        super.draggingExited(sender)
    }
    override func performDragOperation(_ sender: NSDraggingInfo) -> Bool {
        cue(false)
        let url = draggedFile(sender)
        dragLog("perform: url=\(url?.path ?? "nil")")
        guard let url = url else { return super.performDragOperation(sender) }
        let mimes = ["png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"]
        // PHASE 2 — a dropped audio file is a VOICE CLIP, not an attachment. Same
        // suffix set as the bridge's REF_AUDIO_SUFFIXES and the same 15 MB cap, so a
        // file the shell accepts is a file /api/voice/library/save will accept.
        let audioMimes = ["wav": "audio/wav", "mp3": "audio/mpeg",
                          "flac": "audio/flac", "m4a": "audio/mp4"]
        let note = { (msg: String) in
            self.evaluateJavaScript("typeof attachNote==='function'&&attachNote('\(msg)');", completionHandler: nil)
        }
        let ext = url.pathExtension.lowercased()
        let isAudio = audioMimes[ext] != nil
        guard let mime = mimes[ext] ?? audioMimes[ext] else {
            dragLog("perform: rejected ext=\(url.pathExtension)")
            note("only png / jpeg / webp images or wav / mp3 / flac / m4a audio"); return true
        }
        guard let data = try? Data(contentsOf: url) else {
            dragLog("perform: unreadable file")
            note(isAudio ? "could not read that audio file" : "could not read that image"); return true
        }
        let cap = isAudio ? 15 * 1024 * 1024 : 8 * 1024 * 1024
        guard data.count <= cap else {
            dragLog("perform: too large (\(data.count) bytes)")
            note(isAudio ? "audio too large (max 15 MB)" : "image too large (max 8 MB)"); return true
        }
        let name = url.lastPathComponent
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let hook = isAudio ? "harnessNativeAudioDrop" : "harnessNativeDrop"
        let js = "window.\(hook) && \(hook)(\"\(name)\", \"data:\(mime);base64,\(data.base64EncodedString())\");"
        dragLog("perform: injecting \(data.count) bytes as \(mime) via \(hook)")
        evaluateJavaScript(js) { _, err in
            self.dragLog(err == nil ? "perform: js ok" : "perform: js ERROR \(err!)")
        }
        return true
    }
}

// ── downloads ──
// A WKWebView SAVES NOTHING by itself: a response it cannot display (an audio export
// from VoiceStudio, a log file, anything sent as Content-Disposition: attachment) and
// every `<a download>` click are simply DROPPED unless the host app answers the
// download delegate. That is exactly the silent-no-op class that broke ⊕ attach
// (runOpenPanelWith) and ● talk (requestMediaCapturePermissionFor) — Debi hit it as
// "the download button in the VoiceStudio tab does nothing".
//
// One handler instance is shared by all five tabs. It must be RETAINED by the app:
// WKDownload.delegate is weak, so a handler created per download would deallocate
// before decideDestination is ever called.
@available(macOS 11.3, *)
final class DownloadHandler: NSObject, WKDownloadDelegate {
    // download → where we told WebKit to put it (downloadDidFinish carries no URL).
    private var dests: [ObjectIdentifier: URL] = [:]

    // Never-clobber " (n)" suffixing, matching the artifact-save discipline: a
    // generated clip or export cannot be re-made if we silently overwrite it.
    static func destination(for suggested: String) -> URL {
        let fm = FileManager.default
        let dir = fm.urls(for: .downloadsDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory() + "/Downloads")
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        // BASENAME ONLY — suggestedFilename is page-controlled data and must never be
        // able to climb out of ~/Downloads.
        var base = (suggested as NSString).lastPathComponent
        if base.isEmpty || base == "." || base == ".." { base = "download" }
        let ext = (base as NSString).pathExtension
        let stem = (base as NSString).deletingPathExtension
        var candidate = dir.appendingPathComponent(base)
        var n = 2
        while fm.fileExists(atPath: candidate.path) && n < 1000 {
            let name = ext.isEmpty ? "\(stem) (\(n))" : "\(stem) (\(n)).\(ext)"
            candidate = dir.appendingPathComponent(name)
            n += 1
        }
        return candidate
    }

    func download(_ download: WKDownload,
                  decideDestinationUsing response: URLResponse,
                  suggestedFilename: String,
                  completionHandler: @escaping (URL?) -> Void) {
        let url = DownloadHandler.destination(for: suggestedFilename)
        dests[ObjectIdentifier(download)] = url
        completionHandler(url)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let url = dests.removeValue(forKey: ObjectIdentifier(download)) else { return }
        // The ONLY completion signal: reveal the file in Finder once. Deliberately not a
        // notification (needs a bundle-level surface + a thing to dismiss) and not a
        // page-side toast (the SPA is a third party we do not script).
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        dests.removeValue(forKey: ObjectIdentifier(download))
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate,
                         NSSplitViewDelegate, WKScriptMessageHandler {
    // retained handler for every tab's downloads (see DownloadHandler); AnyObject so the
    // stored property itself carries no availability requirement.
    var downloadHandler: AnyObject?
    var window: NSWindow!
    var dropOverlay: NSView?
    // THE primaries. One webview per REGISTRY entry, exactly once —
    // a pane BORROWS one by reparenting; a ghost is a second instance (secondInstances).
    // Three of them are also held by name because they have behaviour of their own
    // (the panel is the drop target + the bridge-wait surface; Odysseus is the only
    // skinned one; Hermes is the only staleness/config-generation reloaded one). Every
    // other tab is a plain webview created generically from the table.
    // PHASE 2: keyed BY ENTRY ID, not by index. That is the whole reason reordering or
    // hiding a tab never reloads a page — the strip is a view of this dictionary, and
    // rebuilding the view touches no webview at all. One webview per REGISTRY entry
    // (they cost nothing until something loads a URL into them, and lazy-load means an
    // entry that is never selected never loads).
    var wvById: [String: WKWebView] = [:]
    var primaries: [WKWebView] { return tabs.map { wvById[$0.id] ?? panelWV } }
    var panelWV: WKWebView!      // == wvById[panelId]
    var odyWV: WKWebView!        // == wvById[odysseusId]
    var hermesWV: WKWebView!     // == wvById[hermesId]
    // Lazy-load bookkeeping, one Set instead of a flag per tab (a flag per tab is
    // exactly the hardcoded-count shape the standing rule forbids). By ID, so a rebuilt
    // strip cannot make the shell think a loaded page is unloaded (or the reverse).
    var loadedTabs = Set<String>()
    var hermesLoaded: Bool { return loadedTabs.contains(hermesId) }
    var failedLoads = Set<ObjectIdentifier>()   // webviews whose last load failed → retry on select/⌘R
    var crashedOnce = Set<ObjectIdentifier>()   // webviews whose content process died since their last good load
    // Staleness auto-reload (Hermes tab only): WebKit tears down a BACKGROUNDED
    // webview's sockets, and Hermes's dashboard misclassifies the resulting
    // close-without-status (WS 1005) as a terminal "session ended" and refuses to
    // auto-reconnect (upstream client bug — see CLAUDE.md, WS-1005 entry). The
    // remedy is a plain reload, so do it for the user when the tab has been
    // backgrounded long enough for the teardown to have happened. Odysseus is
    // deliberately NOT reloaded (it can hold unsent in-page draft state).
    var currentTab = 0
    // ── split view (v2) ──
    // Mental model: ONE tab strip, one or two PANES, and exactly one FOCUSED pane.
    // Every webview still exists exactly once (the properties above are unchanged) —
    // a pane BORROWS one by reparenting it, and a webview nobody borrows is parked in
    // a hidden holder view (the old `isHidden = true` state with a different owner).
    //
    // v1's control model was "the right pane has its own mini strip and the LEFT ALWAYS
    // WINS a collision". Debi's verdict after Mac-testing: the mini strip felt
    // unresponsive, the right pane felt stuck, and "left wins" was invisible logic that
    // produced a placeholder out of nowhere. v2 replaces it wholesale:
    //   • the mini strip is DELETED — one strip, which routes to the FOCUSED pane;
    //   • clicking in a pane focuses it (2px gold top border says which);
    //   • asking the focused pane for the tab the OTHER pane holds SWAPS them, so the
    //     collision has a predictable, visible outcome instead of a placeholder;
    //   • each pane has its own ✕ (close THIS pane; the survivor becomes the one tab).
    // The placeholder survives only as a safety net for a state applyPanes should
    // never be asked for.
    var splitView: NSSplitView!
    var seg: NSSegmentedControl!     // THE tab strip — mirrors the focused pane's tab
    var leftPane: NSView!            // focus strip + leftHost + ✕
    var leftHost: NSView!            // the left pane's content area
    var rightPane: NSView!           // focus strip + rightHost + ✕
    var rightHost: NSView!           // the right pane's content area
    var focusStripL: NSView!         // 2px: gold when focused, clear when not
    var focusStripR: NSView!
    var closeL: PaneCloseButton!
    var closeR: PaneCloseButton!
    var rightPlaceholder: NSView!    // safety net only (see applyPanes)
    var park: NSView!                // hidden holder for un-borrowed webviews
    var splitButton: NSButton!
    var overflowButton: NSButton!
    // ── nav (STUDIO PHASE 2) ──
    // Which entries are on the strip, in order, as data/nav.json last said. The shell
    // cannot read the panel's localStorage, which is exactly why that file exists.
    var navPinned: [String] = navDefaultTopbar
    // Session-only: entries the user picked out of the ⋯ menu (and any entry that was
    // hidden while it was ON SCREEN — taking the page out from under the pointer would
    // be worse than leaving it until they navigate away). ⚠️ never persisted.
    var tempShown: [String] = []
    var navGen: Int?
    var navLoaded = false
    var navTimer: Timer?
    // ⚠️ BUILDER NUMBER. One loopback GET of a route the shell already polls, and only
    // while the app is frontmost — the layout can only change because of something the
    // user did in THIS app, and the panel also pushes `navChanged` the moment it saves,
    // so this poll is the backstop (a change made in a solo tab, which has no
    // script-message handler) rather than the mechanism.
    let navPoll: TimeInterval = 5
    var splitOn = false
    var rightTab = 1
    var focusedPane = 0              // 0 = left, 1 = right — the tab strip's + ⌘R's target
    // ── second instances ("ghosts") ──
    // Debi's ask: dragging a tab the OTHER pane already shows should be able to open a
    // SECOND copy of that app here instead of always swapping. The strip KEEPS the swap
    // (clicking it stays predictable); the DRAG gained this power.
    //
    // The whole state addition is two booleans. A ghost can only exist while both panes
    // hold the SAME tab, and the PRIMARY webview always lives in exactly one pane — so
    // "which pane holds the copy" is the only fact to remember. At most one is true;
    // both false is the ordinary two-different-tabs state.
    var leftIsGhost = false
    var rightIsGhost = false
    // Lazily created, keyed by ENTRY ID (an index would repoint under a rebuilt strip).
    // Destroyed the moment no pane shows them (see releaseUnusedGhosts) — the primaries
    // are never destroyed.
    var secondInstances: [String: WKWebView] = [:]
    var clickMonitor: Any?
    // ── drag a tab onto a pane ──
    // Second monitor, deliberately separate from clickMonitor (which only ever cares
    // about clicks INSIDE a pane; a strip click is in neither, so the two can never
    // fight over the same event). See runTabGesture for why this owns the whole
    // gesture — click included — rather than watching for drags after the fact.
    var tabDragMonitor: Any?
    var tabDragActive = false
    var dragGhostWin: NSWindow?      // the translucent label following the cursor
    var dragHintWin: NSWindow?       // the gold rect over the pane that would receive it
    var hermesLastActive: Date?
    let staleAfter: TimeInterval = 600   // 10 minutes backgrounded → reload on re-select
    // ── Hermes config generation ──
    // The bridge's `hermes_config_gen` (see the _HERMES_CFG_GEN block in bridge/app.py)
    // as it stood when the Hermes webview last loaded. nil = we have never successfully
    // read it, which is treated as "no change" — the whole mechanism fails toward
    // today's behaviour. Hermes's own Skills page fetches its lists once on mount and
    // never refreshes, so without this a toolset/skill switched from OUR Capabilities
    // page leaves that page showing the pre-change state for up to `staleAfter`.
    var hermesCfgGen: Int?
    // ── config-generation POLL ──
    // The reload used to be triggered only from maybeReloadStaleHermes, which runs when a
    // tab BECOMES visible. A Hermes pane sitting beside Mission Control in split view
    // never "becomes" visible, so it never got the reload — toggle a toolset here and
    // Hermes's Skills page kept saying `inactive` until ⌘R. This timer asks the SAME
    // question (syncHermesGen — not a second copy of the logic) on a slow tick, and only
    // exists while a Hermes surface is actually on screen.
    var hermesGenTimer: Timer?
    // ⚠️ BUILDER NUMBER. The generation only moves when the user acts in this panel, so a
    // few seconds of latency is invisible; 4s reads as immediate while costing one
    // loopback GET of an endpoint the shell already polls. Not gated on window occlusion:
    // a reload behind a minimised window is harmless and the alternative (observing
    // occlusion changes to re-arm) is more machinery than one cheap request is worth.
    let hermesGenPoll: TimeInterval = 4
    var bridgeProcess: Process?
    var spawnedBridge = false
    // Working harness root: the baked dev path if present, else ~/Harness (portable builds).
    var resolvedRoot = harnessRoot

    func applicationDidFinishLaunching(_ notification: Notification) {
        if #available(macOS 11.3, *) { downloadHandler = DownloadHandler() }
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Harness"
        // 1160, raised from 900 when the 9th tab (Aider) landed: the tab strip is
        // centred and the ⫽ button is pinned trailing, so at 900pt the nine titles
        // could touch it (see the WIDTH BUDGET note on setSegmentWidths). Two panes at
        // the 420pt minimum plus the divider still fit comfortably inside 1160.
        window.minSize = NSSize(width: 1160, height: 620)
        // Dark editorial chrome: makes the titlebar + segmented control render dark,
        // matching the near-black panel instead of the default white strip.
        window.appearance = NSAppearance(named: .darkAqua)

        let container = NSView()
        window.contentView = container

        // ── tab strip ──
        let tabBar = NSView()
        tabBar.translatesAutoresizingMaskIntoConstraints = false
        tabBar.wantsLayer = true
        tabBar.layer?.backgroundColor = paneInk.cgColor
        container.addSubview(tabBar)

        // PHASE 2: the saved arrangement is remembered by ID (see persistTabs). nav.json
        // arrives asynchronously, so the strip starts on the DEFAULT order — seed it
        // with any saved id that is not in that order, or a customised layout would
        // restore its panes onto whatever happens to sit at those indices instead.
        for key in ["harness.split.leftId", "harness.split.rightId"] {
            guard let id = UserDefaults.standard.string(forKey: key), !id.isEmpty,
                  tabRegistry.contains(where: { $0.id == id }),
                  !tabs.contains(where: { $0.id == id }),
                  !tempShown.contains(id) else { continue }
            tempShown.append(id)
        }
        if !tempShown.isEmpty { tabs = tabsFor(navDefaultTopbar + tempShown) }

        seg = NSSegmentedControl(
            labels: tabTitles,
            trackingMode: .selectOne,
            target: self, action: #selector(tabChanged(_:)))
        seg.selectedSegment = 0
        seg.translatesAutoresizingMaskIntoConstraints = false
        // Segment widths are now EXPLICIT. NSSegmentedControl exposes no per-segment
        // hit test, and `width(forSegment:)` returns 0 for an auto-sized segment — i.e.
        // with autosizing the geometry is unreadable, and this slice has to know which
        // LABEL the pointer is on (for the drag AND, because it now owns the gesture,
        // for the ordinary click too). Setting the widths ourselves makes the rendered
        // layout and our model the same numbers. ⚠️ this is a small rendered change:
        // the strip's width becomes measured-text + 26pt per segment rather than
        // AppKit's own autosize. At the 900pt minimum window width the five titles come
        // to roughly 450pt, so it cannot collide with the ⫽ button.
        setSegmentWidths()
        tabBar.addSubview(seg)

        // ⫽ — the split toggle, at the right end of the strip.
        splitButton = NSButton(title: "⫽", target: self, action: #selector(toggleSplit(_:)))
        splitButton.setButtonType(.pushOnPushOff)
        splitButton.bezelStyle = .texturedRounded
        splitButton.toolTip = "Split view"
        splitButton.translatesAutoresizingMaskIntoConstraints = false
        tabBar.addSubview(splitButton)

        // ⋯ — the overflow menu, immediately left of ⫽. It is the strip's RELIEF VALVE:
        // a tab the user un-pinned is not gone, it is in here, and picking one shows it
        // for this session only (nothing is written back — a temporary look is not a
        // change of layout). Hidden entirely while nothing is hidden.
        overflowButton = NSButton(title: "⋯", target: self, action: #selector(showOverflow(_:)))
        overflowButton.bezelStyle = .texturedRounded
        overflowButton.toolTip = "Hidden tabs"
        overflowButton.translatesAutoresizingMaskIntoConstraints = false
        overflowButton.isHidden = true
        tabBar.addSubview(overflowButton)

        // ── web views ──
        // DropWebView: native drag-destination so Finder image drops reach the chat.
        // The panel — and ONLY the panel — also gets the "harness" script-message
        // handler, so its sidebar can ask the shell to switch tabs. Registering it on
        // any other webview would let a third-party component page drive our tab strip,
        // so this configuration is deliberately not shared (see userContentController).
        let panelCfg = WKWebViewConfiguration()
        panelCfg.userContentController.add(self, name: "harness")
        panelWV = DropWebView(frame: .zero, configuration: panelCfg)

        // "Harness skin" for Odysseus: override its base --font-family (unset → falls back to
        // Fira Code monospace everywhere) with a refined sans for prose/UI. Code blocks use an
        // explicit 'Fira Code' rule, so they stay mono. Colors are left to Odysseus's Theme editor.
        let odyCfg = WKWebViewConfiguration()
        let skin = ":root{--font-family:-apple-system,'SF Pro Text','Segoe UI',system-ui,sans-serif;} body{line-height:1.5;} .msg,.message,p{letter-spacing:0.1px;}"
        let inject = "(function(){var s=document.getElementById('harness-skin')||document.createElement('style');s.id='harness-skin';s.textContent=`\(skin)`;document.documentElement.appendChild(s);})();"
        let userScript = WKUserScript(source: inject, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
        odyCfg.userContentController.addUserScript(userScript)
        odyWV = WKWebView(frame: .zero, configuration: odyCfg)

        // Hermes runs its own polished dark UI — no skin injection (unlike Odysseus).
        hermesWV = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())

        // Build the id-keyed primaries FROM THE REGISTRY (not from `tabs`: an entry the
        // user has hidden still needs its webview, so that un-hiding it — or the ⋯ menu
        // — shows the page it already had). Every entry that is not one of the three
        // named above is a plain webview: no skin, no drag handling. Adding a row to
        // `tabRegistry` therefore adds a fully-working tab with no edit here.
        wvById = [:]
        for t in tabRegistry {
            // explicit `!` on the three named ones: they are stored as implicitly
            // unwrapped optionals, and being explicit here keeps the type unambiguous.
            if t.id == panelId { wvById[t.id] = panelWV! }
            else if t.id == odysseusId { wvById[t.id] = odyWV! }
            else if t.id == hermesId { wvById[t.id] = hermesWV! }
            else { wvById[t.id] = WKWebView(frame: .zero, configuration: WKWebViewConfiguration()) }
        }

        for wv in wvById.values {
            wv.translatesAutoresizingMaskIntoConstraints = false
            wv.uiDelegate = self          // route target=_blank links to the default browser
            wv.navigationDelegate = self  // detect failed loads → placeholder + retry
            if #available(macOS 12.0, *) {
                wv.underPageBackgroundColor = NSColor(red: 0.043, green: 0.039, blue: 0.063, alpha: 1)
            }
            // NOT added to the container here any more: applyPanes() owns every
            // webview's parent from now on (a pane, or the hidden park view).
        }

        // drop-catcher above the panel's webview; applyPanes() moves it to whichever
        // pane Mission Control currently lives in (it is the only drop target).
        let ov = DropOverlay(webView: panelWV as! DropWebView)
        ov.translatesAutoresizingMaskIntoConstraints = false
        dropOverlay = ov

        // ── panes ──
        splitView = NSSplitView()
        splitView.isVertical = true
        splitView.dividerStyle = .thin
        splitView.autosaveName = "harness-split"
        splitView.delegate = self
        splitView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(splitView)

        // ⚠️ TAMIC stays FALSE on the panes. NSSplitView's autolayout mode (the one
        // NSSplitViewController itself uses) expects constraint-based arranged subviews;
        // flipping these to true would give the pane its autoresizing mask derived from
        // its CURRENT frame — which for a runtime-inserted `NSView()` is .zero, i.e.
        // strictly worse than the bug we are fixing. The children inside each pane keep
        // their own TAMIC=false constraints either way.
        // Both panes are built by the same function, so the two can only differ where
        // they are DELIBERATELY made to differ (which pane a ✕ closes).
        leftPane = NSView()
        leftPane.translatesAutoresizingMaskIntoConstraints = false
        focusStripL = NSView()
        leftHost = NSView()
        closeL = PaneCloseButton(title: "✕", target: self, action: #selector(closeLeft(_:)))
        buildPane(leftPane, strip: focusStripL, host: leftHost, close: closeL,
                  tip: "Close this pane")
        splitView.addArrangedSubview(leftPane)   // the right pane is added only when split is ON
        // Holding priority: the subview with the LOWER value is the first to absorb a
        // change, so a WINDOW resize moves the left pane's edge and leaves the pane you
        // just opened alone. ⚠️ 250/251 are arbitrary-but-adjacent: any pair with
        // left < right gives the same deterministic behaviour.
        splitView.setHoldingPriority(NSLayoutConstraint.Priority(250), forSubviewAt: 0)

        rightPane = NSView()
        rightPane.translatesAutoresizingMaskIntoConstraints = false
        focusStripR = NSView()
        rightHost = NSView()
        closeR = PaneCloseButton(title: "✕", target: self, action: #selector(closeRight(_:)))
        buildPane(rightPane, strip: focusStripR, host: rightHost, close: closeR,
                  tip: "Close this pane")

        rightPlaceholder = makeRightPlaceholder()

        // parked webviews stay full-size (so a re-borrow needs no relayout) but never draw.
        park = NSView()
        park.translatesAutoresizingMaskIntoConstraints = false
        park.isHidden = true
        container.addSubview(park)

        // Min pane width, the LAYOUT half of the rule the divider-drag delegate enforces.
        // ⚠️ DELIBERATELY NOT REQUIRED. As `required` these fought the split view's own
        // frame engine the moment rightPane joined the hierarchy (a split view positions
        // its arranged subviews itself; a required width minimum it does not know about
        // has to be resolved by BREAKING a constraint — possibly ours — which is silent
        // to the user and was one half of the "⫽ does nothing" bug). At 750 the engine
        // satisfies them when it can and quietly relaxes them when it cannot, and the
        // hard 420 floor still holds where it actually matters: constrainMin/MaxCoordinate
        // on the drag, and positionDivider() on insertion.
        let leftMin = leftPane.widthAnchor.constraint(greaterThanOrEqualToConstant: 420)
        let rightMin = rightPane.widthAnchor.constraint(greaterThanOrEqualToConstant: 420)
        leftMin.priority = NSLayoutConstraint.Priority(750)
        rightMin.priority = NSLayoutConstraint.Priority(750)

        NSLayoutConstraint.activate([
            leftMin, rightMin,
            tabBar.topAnchor.constraint(equalTo: container.topAnchor),
            tabBar.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            tabBar.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            tabBar.heightAnchor.constraint(equalToConstant: 44),
            seg.centerXAnchor.constraint(equalTo: tabBar.centerXAnchor),
            seg.centerYAnchor.constraint(equalTo: tabBar.centerYAnchor),
            splitButton.trailingAnchor.constraint(equalTo: tabBar.trailingAnchor, constant: -12),
            splitButton.centerYAnchor.constraint(equalTo: tabBar.centerYAnchor),
            overflowButton.trailingAnchor.constraint(equalTo: splitButton.leadingAnchor, constant: -8),
            overflowButton.centerYAnchor.constraint(equalTo: tabBar.centerYAnchor),
            splitView.topAnchor.constraint(equalTo: tabBar.bottomAnchor),
            splitView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            splitView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            splitView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            park.topAnchor.constraint(equalTo: tabBar.bottomAnchor),
            park.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            park.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            park.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])

        // Restore the persisted arrangement. ⚠️ The LEFT tab is restored only when the
        // split was on: reopening the whole arrangement is what the user asked for, but
        // a single-pane launch landing on a stopped Voicebox would be a worse first
        // impression than today's Mission Control.
        let ud = UserDefaults.standard
        let wasSplit = ud.bool(forKey: "harness.split.on")
        // ID first (PHASE 2), the old integer key second so an upgrade from the previous
        // build still restores its arrangement rather than silently resetting it.
        let savedRightId = ud.string(forKey: "harness.split.rightId") ?? ""
        let savedLeftId = ud.string(forKey: "harness.split.leftId") ?? ""
        rightTab = tabs.firstIndex(where: { $0.id == savedRightId })
                   ?? (ud.object(forKey: "harness.split.right") as? Int ?? 1)
        if rightTab < 0 || rightTab >= tabTitles.count { rightTab = 1 }
        if wasSplit {
            currentTab = tabs.firstIndex(where: { $0.id == savedLeftId })
                         ?? (ud.object(forKey: "harness.split.left") as? Int ?? 0)
            if currentTab < 0 || currentTab >= tabTitles.count { currentTab = 0 }
            // The two panes can never hold the same tab (that is what the swap rule
            // guarantees); repair a defaults file that somehow says otherwise.
            if rightTab == currentTab { rightTab = (currentTab + 1) % tabTitles.count }
            ensureLoaded(currentTab)
        }
        seg.selectedSegment = currentTab
        setSplit(wasSplit, persist: false)
        if wasSplit {
            let f = ud.object(forKey: "harness.split.focus") as? Int ?? 0
            setFocus(f == 1 ? 1 : 0)
        }

        // "focused pane" = the pane you last clicked in. It drives BOTH the tab strip
        // and ⌘R. Deliberately a coarse hit-test over each pane's frame rather than
        // chasing first responder through WKWebView's internals — a click anywhere in
        // a pane, including inside the page, focuses that pane.
        clickMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] ev in
            guard let s = self, s.splitOn, s.rightPane.superview != nil else { return ev }
            guard ev.window === s.window else { return ev }
            if s.rightPane.bounds.contains(s.rightPane.convert(ev.locationInWindow, from: nil)) {
                s.setFocus(1)
            } else if s.leftPane.bounds.contains(s.leftPane.convert(ev.locationInWindow, from: nil)) {
                s.setFocus(0)
            }
            // A click on the tab strip or the ⫽ button is in NEITHER pane → focus is
            // left exactly where it was, which is what makes the strip route correctly.
            return ev
        }

        // Drag a TAB LABEL onto a pane. This monitor claims a mouseDown that lands on a
        // segment and runs the ENTIRE gesture itself (see runTabGesture) — that is not
        // gold-plating, it is the only shape that works: NSSegmentedControl handles a
        // click in a cell tracking loop that pulls events straight off the queue, so a
        // monitor watching for .leftMouseDragged afterwards would never be called. Any
        // mouseDown we cannot resolve to a segment (the ⫽ button, the bare strip) is
        // returned untouched and behaves exactly as it does today.
        tabDragMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown]) { [weak self] ev in
            guard let s = self, !s.tabDragActive else { return ev }
            guard ev.window === s.window else { return ev }
            guard let idx = s.segmentAt(ev.locationInWindow) else { return ev }
            s.runTabGesture(startingAt: ev.locationInWindow, tab: idx)
            return nil   // consumed: we performed either the click or the drag ourselves
        }

        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        beginLaunch()
        // NAV: the strip above was built from the DEFAULT order (the bridge may not even
        // be up yet). This asks for the saved one and rebuilds if it differs — and keeps
        // asking, cheaply, so a layout saved in the panel reaches the strip on its own.
        updateOverflowButton()
        startNavPoll()
    }

    // ── §G-phase2 portable first-run ──
    // Dev builds bake a valid harnessRoot → this whole path is dormant. Portable builds
    // have no valid baked root → resolve to ~/Harness, self-installing on first launch.
    func homeHarness() -> String { NSHomeDirectory() + "/Harness" }
    // §G-phase3 fat build: the runtime root lives in Application Support (the app installs
    // there on first run rather than into a repo checkout).
    func appSupportHarness() -> String {
        NSHomeDirectory() + "/Library/Application Support/Harness"
    }
    func rootIsProvisioned(_ root: String) -> Bool {
        FileManager.default.fileExists(atPath: root + "/bridge/app.py")
    }
    // Fat first-run writes .provisioned only after all venvs build, so a half-extracted
    // seed (bridge/app.py present but venvs missing) still re-provisions.
    func fatProvisioned(_ root: String) -> Bool {
        FileManager.default.fileExists(atPath: root + "/.provisioned")
    }

    func beginLaunch() {
        // Fat/offline build: dedicated Application Support root + offline provisioner.
        // Dev/thin/portable builds (fatBuild == false) fall through unchanged.
        if fatBuild {
            let dest = appSupportHarness()
            if fatProvisioned(dest) { resolvedRoot = dest; ensureBridgeThenLoad(attempt: 0) }
            else { runFirstRunFat() }
            return
        }
        if rootIsProvisioned(harnessRoot) { resolvedRoot = harnessRoot; ensureBridgeThenLoad(attempt: 0); return }
        let dest = homeHarness()
        if rootIsProvisioned(dest) { resolvedRoot = dest; ensureBridgeThenLoad(attempt: 0); return }
        runFirstRun()   // nothing provisioned anywhere → portable first-run
    }

    func setupHTML(_ title: String, _ body: String) -> String {
        "<body style='background:#0b0a10;color:#c9c4d4;font-family:-apple-system;display:flex;" +
        "align-items:center;justify-content:center;height:100vh;margin:0'>" +
        "<div style='max-width:560px;padding:24px;line-height:1.65'>" +
        "<h2 style='color:#efe7d7;font-weight:500'>\(title)</h2><p>\(body)</p></div></body>"
    }
    func esc(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
    }
    func tail(_ path: String, _ n: Int) -> String {
        guard let s = try? String(contentsOfFile: path, encoding: .utf8) else { return "" }
        return s.split(separator: "\n", omittingEmptySubsequences: false).suffix(n).joined(separator: "\n")
    }
    func setupFailed(_ msg: String) {
        DispatchQueue.main.async { self.panelWV.loadHTMLString(self.setupHTML("Setup problem", self.esc(msg)), baseURL: nil) }
    }

    func runFirstRun() {
        let seed = (Bundle.main.resourcePath ?? "") + "/harness-seed.tar.gz"
        if !FileManager.default.fileExists(atPath: seed) {
            panelWV.loadHTMLString(setupHTML("Harness folder not found",
                "This build expects the harness at<br><code>\(esc(harnessRoot))</code><br>which isn’t present, and it carries no portable seed.<br><br>Rebuild from the repo with <code>./scripts/build_app.sh</code>, or make a portable build with <code>--portable</code>."), baseURL: nil)
            return
        }
        let a = NSAlert()
        a.messageText = "Set up Harness"
        a.informativeText = "Harness will install its local stack into:\n\(homeHarness())\n\nRequirements: Xcode Command Line Tools, Homebrew, and an internet connection. This can take several minutes."
        a.addButton(withTitle: "Continue")
        a.addButton(withTitle: "Quit")
        if a.runModal() != .alertFirstButtonReturn { NSApp.terminate(nil); return }
        panelWV.loadHTMLString(setupHTML("Setting things up…",
            "Installing the local stack into <code>~/Harness</code>.<br>This can take several minutes — progress is logged to<br><code>~/Harness/data/logs/firstrun.log</code>.<br><br>This screen continues automatically when the harness is ready."), baseURL: nil)
        DispatchQueue.global().async { self.doFirstRun() }
    }

    func doFirstRun() {
        let fm = FileManager.default
        let dest = homeHarness()
        let seed = (Bundle.main.resourcePath ?? "") + "/harness-seed.tar.gz"
        try? fm.createDirectory(atPath: dest, withIntermediateDirectories: true)

        let untar = Process()
        untar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
        untar.arguments = ["-xzf", seed, "-C", dest]
        do { try untar.run() } catch { setupFailed("Could not extract the setup seed: \(error)"); return }
        untar.waitUntilExit()
        if untar.terminationStatus != 0 { setupFailed("Extracting the setup seed failed."); return }

        let logDir = dest + "/data/logs"
        try? fm.createDirectory(atPath: logDir, withIntermediateDirectories: true)
        let logFile = logDir + "/firstrun.log"
        fm.createFile(atPath: logFile, contents: nil)
        let fh = FileHandle(forWritingAtPath: logFile)

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        // login shell so brew (/opt/homebrew/bin) and ~/.local/bin are on PATH for a GUI launch
        p.arguments = ["-lc", "bash '\(dest)/scripts/firstrun.sh' --yes 2>&1"]
        p.currentDirectoryURL = URL(fileURLWithPath: dest)
        if let fh = fh { p.standardOutput = fh; p.standardError = fh }
        do { try p.run() } catch { setupFailed("Could not start setup: \(error)"); return }
        p.waitUntilExit()

        let ok = p.terminationStatus == 0
        DispatchQueue.main.async {
            if ok { self.resolvedRoot = dest; self.ensureBridgeThenLoad(attempt: 0) }
            else {
                self.panelWV.loadHTMLString(self.setupHTML("Setup didn’t finish",
                    "See <code>~/Harness/data/logs/firstrun.log</code>. Common causes: Homebrew or Xcode Command Line Tools missing, or no internet. Fix, then reopen Harness.<br><br><pre style='white-space:pre-wrap;color:#6f6a80;font:11px ui-monospace,Menlo,monospace'>\(self.esc(self.tail(logFile, 30)))</pre>"), baseURL: nil)
            }
        }
    }

    // ── §G-phase3 fat/offline first-run ──
    // Consent → run the bundled offline provisioner (no network/npm/brew needed) → on success
    // load the panel where §E starts each component. Dormant unless fatBuild (dev unchanged).
    func runFirstRunFat() {
        let res = Bundle.main.resourcePath ?? ""
        let seed = res + "/harness-seed-fat.tar.gz"
        let script = res + "/firstrun_fat.sh"
        if !FileManager.default.fileExists(atPath: seed) || !FileManager.default.fileExists(atPath: script) {
            panelWV.loadHTMLString(setupHTML("Installer payload missing",
                "This is a fat build but the bundled setup payload isn’t present.<br>Rebuild with <code>./scripts/build_app.sh --fat</code>."), baseURL: nil)
            return
        }
        let a = NSAlert()
        a.messageText = "Set up Harness"
        a.informativeText = "Harness will install its local AI stack into:\n\(appSupportHarness())\n\nNo internet is needed for setup — everything is bundled. This can take a few minutes."
        a.addButton(withTitle: "Continue")
        a.addButton(withTitle: "Quit")
        if a.runModal() != .alertFirstButtonReturn { NSApp.terminate(nil); return }
        panelWV.loadHTMLString(setupHTML("Setting things up…",
            "Installing the local stack (offline) into<br><code>~/Library/Application Support/Harness</code>.<br>This can take a few minutes — progress is logged to<br><code>…/data/logs/firstrun.log</code>.<br><br>This screen continues automatically when the harness is ready."), baseURL: nil)
        DispatchQueue.global().async { self.doFirstRunFat() }
    }

    func doFirstRunFat() {
        let fm = FileManager.default
        let dest = appSupportHarness()
        let res = Bundle.main.resourcePath ?? ""
        let script = res + "/firstrun_fat.sh"
        try? fm.createDirectory(atPath: dest, withIntermediateDirectories: true)

        let logDir = dest + "/data/logs"
        try? fm.createDirectory(atPath: logDir, withIntermediateDirectories: true)
        let logFile = logDir + "/firstrun.log"
        fm.createFile(atPath: logFile, contents: nil)
        let fh = FileHandle(forWritingAtPath: logFile)

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/bash")
        // login shell so any user PATH is present; pass RESOURCES + DEST to the provisioner.
        p.arguments = ["-lc", "bash '\(script)' '\(res)' '\(dest)' 2>&1"]
        p.currentDirectoryURL = URL(fileURLWithPath: dest)
        if let fh = fh { p.standardOutput = fh; p.standardError = fh }
        do { try p.run() } catch { setupFailed("Could not start setup: \(error)"); return }
        p.waitUntilExit()

        let ok = p.terminationStatus == 0 && fm.fileExists(atPath: dest + "/.provisioned")
        DispatchQueue.main.async {
            if ok { self.resolvedRoot = dest; self.ensureBridgeThenLoad(attempt: 0) }
            else {
                self.panelWV.loadHTMLString(self.setupHTML("Setup didn’t finish",
                    "See <code>~/Library/Application Support/Harness/data/logs/firstrun.log</code> (and the per-component <code>firstrun_*.log</code> beside it). Fix the reported component, then reopen Harness.<br><br><pre style='white-space:pre-wrap;color:#6f6a80;font:11px ui-monospace,Menlo,monospace'>\(self.esc(self.tail(logFile, 30)))</pre>"), baseURL: nil)
            }
        }
    }

    // ── v2 pane plumbing ──

    // One builder for both panes: focus strip on top, content host below it, ✕ floating
    // over the host's top-right. Z-ORDER MATTERS — the host is added before the ✕, so a
    // webview reparented INTO the host can never cover the button.
    func buildPane(_ pane: NSView, strip: NSView, host: NSView, close: PaneCloseButton, tip: String) {
        strip.translatesAutoresizingMaskIntoConstraints = false
        strip.wantsLayer = true
        strip.layer?.backgroundColor = NSColor.clear.cgColor
        pane.addSubview(strip)

        host.translatesAutoresizingMaskIntoConstraints = false
        pane.addSubview(host)

        // No bezelStyle: the NSBezelStyle case names were renamed in the macOS 14 SDK,
        // and a borderless button does not use one anyway.
        close.isBordered = false
        close.toolTip = tip
        close.translatesAutoresizingMaskIntoConstraints = false
        close.tint(paneFaint)
        pane.addSubview(close)

        NSLayoutConstraint.activate([
            strip.topAnchor.constraint(equalTo: pane.topAnchor),
            strip.leadingAnchor.constraint(equalTo: pane.leadingAnchor),
            strip.trailingAnchor.constraint(equalTo: pane.trailingAnchor),
            strip.heightAnchor.constraint(equalToConstant: 2),
            host.topAnchor.constraint(equalTo: strip.bottomAnchor),
            host.leadingAnchor.constraint(equalTo: pane.leadingAnchor),
            host.trailingAnchor.constraint(equalTo: pane.trailingAnchor),
            host.bottomAnchor.constraint(equalTo: pane.bottomAnchor),
            close.trailingAnchor.constraint(equalTo: host.trailingAnchor, constant: -8),
            close.topAnchor.constraint(equalTo: host.topAnchor, constant: 8),
            close.widthAnchor.constraint(equalToConstant: 16),
            close.heightAnchor.constraint(equalToConstant: 16),
        ])
    }

    // The tab the strip is currently speaking for.
    func focusedTab() -> Int {
        return (splitOn && focusedPane == 1) ? rightTab : currentTab
    }
    // Hermes is visible if EITHER pane holds it — v1's staleness stamp was keyed on the
    // left strip alone and could therefore be pessimistic. With one strip that mistake
    // is avoidable, so this asks the real question.
    func hermesVisible() -> Bool { return currentTab == hermesTab || (splitOn && rightTab == hermesTab) }

    // Every Hermes surface currently ON SCREEN — the question the config-generation
    // reload actually needs answered. Usually just the primary; when a pane holds a
    // SECOND INSTANCE ("ghost") of the Hermes tab, BOTH panes show Hermes (one primary,
    // one copy) and both are equally stale after a config change, so both are returned
    // and both get reloaded. Reloading only the primary would leave the copy in the other
    // half of the window still lying about Hermes's state.
    //
    // The ghost flags are only ever set while the split is on and both panes hold the
    // same tab (applyPanes normalises them first), so the two tests below cannot both
    // claim the same pane. The primary is gated on `hermesLoaded` — a page that has never
    // loaded has nothing to reload; a ghost loads itself on creation, so it needs no flag.
    func visibleHermesWebViews() -> [WKWebView] {
        var out: [WKWebView] = []
        let leftShowsHermes = currentTab == hermesTab
        let rightShowsHermes = splitOn && rightTab == hermesTab
        if hermesLoaded,
           (leftShowsHermes && !leftIsGhost) || (rightShowsHermes && !rightIsGhost) {
            out.append(hermesWV)
        }
        if (leftShowsHermes && leftIsGhost) || (rightShowsHermes && rightIsGhost),
           let g = secondInstances[hermesId] {
            out.append(g)
        }
        return out
    }

    // Start/stop the poll from the ONE place that knows what is on screen: applyPanes is
    // called by every path that changes it (tab route, split on/off, pane close, second
    // instance), so there is no second rule to keep in step. No Hermes on screen — or no
    // Hermes page loaded yet — means NO timer at all, rather than a timer that returns
    // early. Idempotent: an applyPanes pass that changed nothing does not restack it.
    func updateHermesGenTimer() {
        if !visibleHermesWebViews().isEmpty {
            if hermesGenTimer != nil { return }
            hermesGenTimer = Timer.scheduledTimer(withTimeInterval: hermesGenPoll,
                                                  repeats: true) { [weak self] _ in
                guard let s = self else { return }
                // Belt and braces: if the layout ever changed without applyPanes running,
                // the timer retires itself instead of polling forever.
                if s.visibleHermesWebViews().isEmpty { s.updateHermesGenTimer(); return }
                // Pause while the app is not frontmost (queued Fable refinement): the
                // generation only ever moves because of something the user did HERE, so
                // a background app has nothing to learn. The timer stays armed — the
                // next tick after the user comes back does the check — rather than
                // adding resign/become observers for a saving of one loopback GET.
                if !NSApp.isActive { return }
                s.syncHermesGen(reloadIfNewer: true, why: "poll")
            }
            NSLog("%@", "[hermes] gen poll -> on (every \(Int(hermesGenPoll))s)" as NSString)
        } else if let t = hermesGenTimer {
            t.invalidate()
            hermesGenTimer = nil
            NSLog("%@", "[hermes] gen poll -> off (no Hermes on screen)" as NSString)
        }
    }

    // The strip always MIRRORS the focused pane. Setting selectedSegment
    // programmatically does not fire the control's action, so this cannot recurse.
    func syncStrip() {
        let t = focusedTab()
        if seg.selectedSegment != t { seg.selectedSegment = t }
    }

    func updateFocusStrips() {
        // Single-pane mode gets no gold line: with nothing to distinguish, a permanent
        // accent bar would be noise. ⚠️ deliberate (the spec only defines the two-pane
        // case); the strip stays in the hierarchy either way so nothing shifts.
        let l = (splitOn && focusedPane == 0) ? paneGold : NSColor.clear
        let r = (splitOn && focusedPane == 1) ? paneGold : NSColor.clear
        focusStripL.layer?.backgroundColor = l.cgColor
        focusStripR.layer?.backgroundColor = r.cgColor
        closeL.isHidden = !splitOn
        closeR.isHidden = !splitOn
    }

    func setFocus(_ p: Int) {
        let np = (splitOn && rightPane.superview === splitView) ? p : 0
        if np != focusedPane { slog("focus -> \(np)") }
        focusedPane = np
        UserDefaults.standard.set(np, forKey: "harness.split.focus")
        updateFocusStrips()
        syncStrip()
    }

    func persistTabs() {
        let ud = UserDefaults.standard
        ud.set(currentTab, forKey: "harness.split.left")
        ud.set(rightTab, forKey: "harness.split.right")
        // PHASE 2: the indices only mean anything against the strip that was on screen
        // when they were written, and the strip is the user's now — so the ID is the
        // real record and the ints are kept only as the upgrade path.
        ud.set(tabId(currentTab), forKey: "harness.split.leftId")
        ud.set(tabId(rightTab), forKey: "harness.split.rightId")
    }

    // THE v2 routing rule. If the OTHER pane already holds the requested tab, the two
    // panes SWAP — one webview, two panes, and a predictable visible outcome instead of
    // v1's out-of-nowhere placeholder.
    //
    // The destination pane is a PARAMETER. The strip passes
    // the focused pane; a tab dropped on a pane passes that pane. One body, so the click
    // path and the drag path cannot drift apart — including the swap.
    func routeTab(_ idx: Int, toPane p: Int) {
        guard idx >= 0 && idx < tabTitles.count else { return }
        let wasHermes = hermesVisible()
        if splitOn && p == 1 {
            if idx == currentTab { currentTab = rightTab }   // swap
            rightTab = idx
        } else {
            if splitOn && idx == rightTab { rightTab = currentTab }   // swap
            currentTab = idx
        }
        if wasHermes && !hermesVisible() { hermesLastActive = Date() }
        persistTabs()
        ensureLoaded(currentTab)
        if splitOn { ensureLoaded(rightTab) }
        maybeReloadStaleHermes(idx)
        applyPanes()
        updateFocusStrips()
        // A previously failed tab retries automatically on re-select (component may be up now).
        retryIfFailed(webViewFor(idx))
    }

    // ── the tab strip is a VIEW of the nav model (STUDIO PHASE 2 §B) ──
    //
    // `tabs` is rebuilt from `navPinned` + `tempShown`; every webview is keyed by ID, so
    // a rebuild reparents nothing and reloads nothing. The panes are remembered by ID
    // across the rebuild too, so reordering the strip does not move what you are
    // looking at.
    func tabId(_ idx: Int) -> String {
        return (idx >= 0 && idx < tabs.count) ? tabs[idx].id : panelId
    }
    func urlForId(_ id: String) -> URL {
        return tabRegistry.first(where: { $0.id == id })?.url ?? bridgeURL
    }
    func rebuildTabs() {
        let keepLeft = tabId(currentTab)
        let keepRight = tabId(rightTab)
        var ids = navPinned.filter { i in tabRegistry.contains(where: { $0.id == i }) }
        // Mission Control is FIRST and always present: it is the bridge-wait surface,
        // the file-drop target and `panelTab = 0`. The nav model already guarantees it;
        // this is the shell refusing to be broken by a file that does not.
        ids.removeAll { $0 == panelId }
        ids.insert(panelId, at: 0)
        // Anything on screen, or picked from ⋯, stays on the strip for this session.
        // ⚠️ deliberate: un-pinning the tab you are LOOKING AT does not yank the page out
        // from under you — it stays until you navigate away, and lives in ⋯ after that.
        // Only the panes that are actually on screen count (rightTab means nothing while
        // the split is off), so hiding a tab the closed right pane once held is instant.
        for id in tempShown where !ids.contains(id) { ids.append(id) }
        for id in (splitOn ? [keepLeft, keepRight] : [keepLeft]) where !ids.contains(id) {
            if tabRegistry.contains(where: { $0.id == id }) {
                if !tempShown.contains(id) { tempShown.append(id) }
                ids.append(id)
            }
        }
        tabs = tabsFor(ids)
        seg.segmentCount = tabs.count
        for (i, t) in tabs.enumerated() { seg.setLabel(t.title, forSegment: i) }
        setSegmentWidths()
        currentTab = tabs.firstIndex(where: { $0.id == keepLeft }) ?? 0
        rightTab = tabs.firstIndex(where: { $0.id == keepRight }) ?? ((currentTab + 1) % max(1, tabs.count))
        if rightTab == currentTab && tabs.count > 1 { rightTab = (currentTab + 1) % tabs.count }
        persistTabs()
        updateOverflowButton()
        applyPanes()
        updateFocusStrips()
        syncStrip()
        let names = tabs.map { $0.id }.joined(separator: ",")
        slog("nav -> strip \(names) left=\(currentTab) right=\(rightTab)")
    }

    func hiddenTabs() -> [HarnessTab] {
        return tabRegistry.filter { r in !tabs.contains(where: { $0.id == r.id }) }
    }
    func updateOverflowButton() {
        overflowButton.isHidden = hiddenTabs().isEmpty
    }
    @objc func showOverflow(_ sender: Any?) {
        let menu = NSMenu()
        for t in hiddenTabs() {
            let it = NSMenuItem(title: t.title, action: #selector(overflowPick(_:)), keyEquivalent: "")
            it.target = self
            it.representedObject = t.id
            menu.addItem(it)
        }
        if menu.items.isEmpty { menu.addItem(NSMenuItem(title: "No hidden tabs", action: nil, keyEquivalent: "")) }
        _ = menu.popUp(positioning: nil,
                       at: NSPoint(x: 0, y: overflowButton.bounds.height + 4),
                       in: overflowButton)
    }
    @objc func overflowPick(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        if !tempShown.contains(id) { tempShown.append(id) }
        rebuildTabs()          // session only — nothing is written back to nav.json
        guard let idx = tabs.firstIndex(where: { $0.id == id }) else { return }
        routeTab(idx, toPane: (splitOn && focusedPane == 1) ? 1 : 0)
        syncStrip()
        slog("overflow -> \(id)")
    }

    // Adopt a pinned list. No-ops when nothing changed, so the poll can run forever
    // without ever touching the layout.
    func applyNav(_ ids: [String]) {
        let clean = ids.filter { i in tabRegistry.contains(where: { $0.id == i }) }
        guard !clean.isEmpty, clean != navPinned else { return }
        navPinned = clean
        // An entry that is pinned again no longer needs its session-only pass.
        tempShown.removeAll { clean.contains($0) }
        rebuildTabs()
    }

    // Start the nav poll. `force` on the first pass because there is no generation to
    // compare against yet; after that only a MOVED generation costs a second request.
    func startNavPoll() {
        guard navTimer == nil else { return }
        syncNav(force: true)
        navTimer = Timer.scheduledTimer(withTimeInterval: navPoll, repeats: true) { [weak self] _ in
            guard let s = self else { return }
            if !NSApp.isActive { return }
            s.syncNav(force: !s.navLoaded)
        }
    }
    // FAIL SAFE, exactly like syncHermesGen: any transport error, non-200, unparseable
    // body or missing field leaves the strip exactly as it is. A DECREASE means the
    // bridge restarted (the counter is process-lifetime) — recorded, never acted on,
    // because nav.json on disk did not move while the bridge was down.
    func syncNav(force: Bool) {
        if force { fetchNav(); return }
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/status"))
        req.timeoutInterval = 2.0
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, resp, err in
            guard err == nil,
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let d = data,
                  let raw = try? JSONSerialization.jsonObject(with: d),
                  let obj = raw as? [String: Any],
                  let gen = obj["nav_gen"] as? Int else { return }
            DispatchQueue.main.async {
                let prev = self.navGen
                self.navGen = gen                      // record FIRST → cannot loop
                guard let p = prev, gen > p else { return }
                self.fetchNav()
            }
        }.resume()
    }
    func fetchNav() {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/nav"))
        req.timeoutInterval = 2.0
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, resp, err in
            guard err == nil,
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let d = data,
                  let raw = try? JSONSerialization.jsonObject(with: d),
                  let obj = raw as? [String: Any],
                  let nav = obj["nav"] as? [String: Any],
                  let top = nav["topbar"] as? [[String: Any]] else { return }
            let ids = top.compactMap { r -> String? in
                guard let id = r["id"] as? String, (r["pinned"] as? Bool) == true else { return nil }
                return id
            }
            DispatchQueue.main.async {
                self.navLoaded = true
                if let g = obj["gen"] as? Int { self.navGen = g }
                self.applyNav(ids)
            }
        }.resume()
    }

    @objc func tabChanged(_ sender: NSSegmentedControl) {
        let idx = sender.selectedSegment
        routeTab(idx, toPane: (splitOn && focusedPane == 1) ? 1 : 0)
        slog("tab -> \(idx) focus=\(focusedPane) left=\(currentTab) right=\(rightTab)")
    }

    // ── panel → shell: switch to a tab by TITLE ──
    //
    // The panel's COMPONENTS sidebar is the natural place to say "take me to Odysseus",
    // but the panel is a web page and the tabs are AppKit. This is the whole bridge for
    // that, and it is deliberately tiny: one message name, one command, a title looked up
    // in `tabs`, and then the EXACT path a strip click takes (routeTab + the strip sync
    // a click gets for free from the control itself). Split view, focus, lazy load and
    // the failed-load retry therefore behave identically whichever way the tab is chosen.
    //
    // An unknown title is ignored — the panel may be newer than the shell (it is served
    // from disk and reloads on its own), so a title we do not have is a normal, benign
    // state, not an error to surface.
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "harness",
              let body = message.body as? [String: Any],
              let cmd = body["cmd"] as? String else { return }
        switch cmd {
        case "switchTab":
            // PHASE 2: resolve the stable ID first, the title second (an older panel
            // sends only a title). Resolution is against the REGISTRY, not the strip:
            // a tab the user hid is still reachable from its sidebar row — it is shown
            // for this session, exactly as the ⋯ menu does it, rather than ignored.
            let title = body["title"] as? String
            let wantId = body["id"] as? String
            var id: String? = nil
            if let w = wantId, !w.isEmpty, tabRegistry.contains(where: { $0.id == w }) { id = w }
            if id == nil, let t = title { id = tabRegistry.first(where: { $0.title == t })?.id }
            guard let hit = id else {
                slog("panel -> switchTab (unknown tab) ignored")
                return
            }
            if !tabs.contains(where: { $0.id == hit }) {
                if !tempShown.contains(hit) { tempShown.append(hit) }
                rebuildTabs()
            }
            guard let idx = tabs.firstIndex(where: { $0.id == hit }) else { return }
            routeTab(idx, toPane: (splitOn && focusedPane == 1) ? 1 : 0)
            syncStrip()   // a strip CLICK selects the segment itself; this path must not skip it
            slog("panel -> switchTab \(hit) (tab \(idx))")
        case "navChanged":
            // The panel just saved a layout. Fetch it NOW rather than waiting for the
            // poll — the poll exists for the cases this message cannot cover.
            slog("panel -> navChanged")
            syncNav(force: true)
        default:
            slog("panel -> unknown cmd ignored")
        }
    }

    // ── drag a tab onto a pane ──

    // Explicit per-segment widths — the whole reason the geometry below is knowable.
    //
    // WIDTH BUDGET (re-checked when the 9th tab, Aider, was added, 2026-08-21). The strip
    // is centred in `tabBar` and the ⫽ button is pinned trailing at -12, so the strip may
    // occupy roughly minSize.width - 70 before the two could touch. The eight-tab estimate
    // (~733-808pt) had already used up the old 900pt window's ~830pt budget, so THIS tab
    // raised minSize.width to 1160 — budget ~1090pt — rather than shrinking a label.
    // The ELEVEN current titles (OpenCode landed 2026-08-21, +8 characters and +1
    // segment, on top of the ten that totalled 79) total 87 characters; at 13pt SF that
    // is ~7.0-8.0pt per character plus the fixed
    // 26pt padding per segment, i.e. ~895pt to ~982pt: inside
    // 1090 with room for one more tab. If a future tab pushes the estimate past
    // the budget, shorten the LONGEST titles (e.g. "Mission Control" → "Control") rather
    // than removing the padding: `segmentAt` reads exactly these numbers back to hit-test
    // a drag.
    // PHASE 2: this runs again on every strip REBUILD, so the numbers `segmentAt` reads
    // back are always the ones on screen. Debi's cap of 12 pinned tabs is the budget's
    // upper bound — twelve of today's titles is ~950-1050pt, still inside ~1090.
    func setSegmentWidths() {
        let f = seg.font ?? NSFont.systemFont(ofSize: NSFont.systemFontSize)
        for (i, t) in tabTitles.enumerated() {
            guard i < seg.segmentCount else { break }
            let w = (t as NSString).size(withAttributes: [.font: f]).width
            seg.setWidth((w + 26).rounded(), forSegment: i)
        }
        seg.invalidateIntrinsicContentSize()   // the strip is centred by autolayout
    }

    // Which segment is under a WINDOW-coordinate point, or nil if the point is not on the
    // strip at all (⫽ button, tab-bar background, anywhere else) — in which case the
    // caller must leave the event completely alone.
    func segmentAt(_ windowPoint: NSPoint) -> Int? {
        guard seg != nil else { return nil }
        let p = seg.convert(windowPoint, from: nil)
        guard seg.bounds.contains(p) else { return nil }
        var widths: [CGFloat] = []
        var total: CGFloat = 0
        let n = seg.segmentCount
        guard n > 0 else { return nil }
        for i in 0..<n {
            let w = seg.width(forSegment: i)
            // 0 = autosized: cannot happen while setSegmentWidths() runs at construction,
            // but degrade to an equal share rather than to a divide-by-zero.
            let ww = w > 0 ? w : seg.bounds.width / CGFloat(n)
            widths.append(ww)
            total += ww
        }
        guard total > 0 else { return nil }
        // The control's bounds are a little wider than the sum of the segment widths
        // (bezel inset + separators). A SMALL slack is inset at the two ends; a large one
        // means AppKit spread the extra space into the segments, so scale instead. Either
        // way the boundary error is a couple of points on ~80pt segments.
        let slack = seg.bounds.width - total
        var scale: CGFloat = 1
        var x = seg.bounds.minX
        if slack > 8 { scale = seg.bounds.width / total } else { x += max(0, slack / 2) }
        for (i, w) in widths.enumerated() {
            if i == widths.count - 1 { return i }   // last segment is the catch-all
            x += w * scale
            if p.x < x { return i }
        }
        return nil
    }

    // The content area, in window coordinates. A release ABOVE this (the strip, the
    // titlebar) cancels the drag — dropping a tab back on the strip means "never mind".
    func contentRectInWindow() -> NSRect { return splitView.convert(splitView.bounds, to: nil) }

    // Which pane would receive a drop at this point. With the split ON the real pane
    // frames decide (so a dragged divider is honoured); with it OFF there is only one
    // pane, so the geometric halves of the content area are what "left" and "right" mean.
    func paneTarget(for wp: NSPoint) -> Int? {
        let c = contentRectInWindow()
        guard c.contains(wp) else { return nil }
        if splitOn, rightPane.superview === splitView {
            if rightPane.bounds.contains(rightPane.convert(wp, from: nil)) { return 1 }
            if leftPane.bounds.contains(leftPane.convert(wp, from: nil)) { return 0 }
            // on the divider itself → fall through to the halves
        }
        return wp.x < c.midX ? 0 : 1
    }

    // The rect the gold hint covers: the target PANE when split is on, the target HALF
    // when it is off (which is exactly what the drop will then create).
    func dropHintRect(for wp: NSPoint) -> NSRect? {
        guard let p = paneTarget(for: wp) else { return nil }
        if splitOn, rightPane.superview === splitView {
            let pane: NSView = (p == 1) ? rightPane! : leftPane!
            return pane.convert(pane.bounds, to: nil)
        }
        let c = contentRectInWindow()
        return NSRect(x: (p == 0) ? c.minX : c.midX, y: c.minY, width: c.width / 2, height: c.height)
    }

    // A borderless, mouse-transparent child window. ⚠️ deliberately a WINDOW rather than
    // an overlay NSView: the container is an autolayout hierarchy, so a frame-positioned
    // subview would be re-laid-out from under us mid-drag, and an extra subview of a pane
    // host would also have to be reasoned about in applyPanes (which asserts what the
    // last subview of a host is, for the DropOverlay). A child window touches neither.
    func makeFloater(_ size: NSSize) -> NSWindow {
        let w = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                         styleMask: [.borderless], backing: .buffered, defer: false)
        w.isOpaque = false
        w.backgroundColor = .clear
        w.hasShadow = false
        w.ignoresMouseEvents = true   // must never interfere with the tracking loop
        w.level = .floating
        let v = NSView(frame: NSRect(origin: .zero, size: size))
        v.wantsLayer = true
        w.contentView = v
        return w
    }

    func beginDragVisuals(_ tab: Int, at wp: NSPoint) {
        let title = tabTitles[tab]
        let font = NSFont.systemFont(ofSize: 12)
        let tw = (title as NSString).size(withAttributes: [.font: font]).width
        let size = NSSize(width: (tw + 22).rounded(), height: 22)

        // hint first, ghost second → the ghost is the higher child window. Both are
        // FRAMED BEFORE being added as children, so neither can flash at screen origin.
        let hint = makeFloater(NSSize(width: 10, height: 10))
        hint.contentView?.layer?.backgroundColor = paneGold.withAlphaComponent(0.10).cgColor
        hint.contentView?.layer?.borderColor = paneGold.cgColor
        hint.contentView?.layer?.borderWidth = 2
        if let r = dropHintRect(for: wp) { hint.setFrame(window.convertToScreen(r), display: false) }
        else { hint.alphaValue = 0 }
        window.addChildWindow(hint, ordered: .above)
        dragHintWin = hint

        let ghost = makeFloater(size)
        ghost.setFrameOrigin(window.convertPoint(toScreen: NSPoint(x: wp.x + 12, y: wp.y - 26)))
        ghost.contentView?.layer?.backgroundColor = paneInk.withAlphaComponent(0.92).cgColor
        ghost.contentView?.layer?.borderColor = paneGold.cgColor
        ghost.contentView?.layer?.borderWidth = 1
        ghost.contentView?.layer?.cornerRadius = 4
        let l = NSTextField(labelWithString: title)
        l.font = font
        l.textColor = paneCream
        l.alignment = .center
        l.isBordered = false
        l.drawsBackground = false
        l.frame = NSRect(x: 0, y: 3, width: size.width, height: 16)
        ghost.contentView?.addSubview(l)
        ghost.alphaValue = 0.92
        window.addChildWindow(ghost, ordered: .above)
        dragGhostWin = ghost
    }

    func moveDragVisuals(to wp: NSPoint) {
        if let g = dragGhostWin {
            // just below/right of the pointer, so the label never sits under it
            let origin = window.convertPoint(toScreen: NSPoint(x: wp.x + 12, y: wp.y - 26))
            g.setFrameOrigin(origin)
        }
        guard let h = dragHintWin else { return }
        if let r = dropHintRect(for: wp) {
            // addChildWindow already showed it; only the frame + alpha move from here.
            h.setFrame(window.convertToScreen(r), display: true)
            h.alphaValue = 1
        } else {
            h.alphaValue = 0   // released here = cancel, so show no target
        }
    }

    func endDragVisuals() {
        for w in [dragHintWin, dragGhostWin] {
            guard let w = w else { continue }
            window.removeChildWindow(w)
            w.orderOut(nil)
        }
        dragHintWin = nil
        dragGhostWin = nil
    }

    // The whole gesture, from the mouseDown we swallowed to the mouseUp. Below the
    // movement threshold it is a CLICK and is performed exactly as the control's own
    // target/action would have performed it; above it, it is a drag.
    //
    // ⚠️ because the mouseDown is consumed, the segment does not draw its pressed
    // highlight during a click. The selection and the action are identical.
    func runTabGesture(startingAt start: NSPoint, tab: Int) {
        tabDragActive = true
        defer { tabDragActive = false; endDragVisuals() }
        var dragging = false
        var last = start
        var cancelled = false
        loop: while true {
            // A per-event 60s ceiling so a lost mouseUp can never wedge the strip.
            guard let ev = NSApp.nextEvent(matching: [.leftMouseDragged, .leftMouseUp, .keyDown],
                                          until: Date(timeIntervalSinceNow: 60),
                                          inMode: .eventTracking, dequeue: true) else {
                cancelled = true
                slog("drag -> cancelled (no event for 60s)")
                break loop
            }
            switch ev.type {
            case .keyDown:
                // ⚠️ a keyDown may not be delivered at all while a mouse button is held;
                // releasing over the strip is the cancel that always works.
                if ev.keyCode == 53 { cancelled = true; slog("drag -> cancelled (esc)"); break loop }
            case .leftMouseDragged:
                last = ev.locationInWindow
                if !dragging, hypot(last.x - start.x, last.y - start.y) >= 10 {
                    dragging = true
                    beginDragVisuals(tab, at: last)
                    slog("drag -> begin \(tabTitles[tab])")
                }
                if dragging { moveDragVisuals(to: last) }
            case .leftMouseUp:
                last = ev.locationInWindow
                break loop
            default: break
            }
        }
        if cancelled { return }
        if !dragging {
            // Plain click: the strip's normal behaviour, unchanged.
            seg.selectedSegment = tab
            tabChanged(seg)
            return
        }
        guard let p = paneTarget(for: last) else {
            slog("drag -> cancelled (released outside the content area)")
            return
        }
        dropTab(tab, onPane: p)
    }

    // Assign a dragged tab to a pane. Split ON → the ordinary routing rule (including the
    // swap) against that pane. Split OFF → a drop on the LEFT half is just a tab switch,
    // and a drop on the RIGHT half OPENS the split with the dragged tab on the right.
    func dropTab(_ tab: Int, onPane p: Int) {
        // Would this drop collide with what the OTHER pane already shows? Then it is a
        // request for a SECOND INSTANCE, not a swap — that is the point of this slice.
        // With the split OFF the "other pane" is the single pane itself, so dropping its
        // own tab on the right half is the same request and opens the split with BOTH
        // panes on that app. (A drop of the current tab on the LEFT half still falls
        // through to routeTab, where it is the no-op it always was.)
        let other = splitOn ? (p == 1 ? currentTab : rightTab) : currentTab
        if tab == other && (splitOn || p == 1) {
            openSecondInstance(tab, onPane: p)
            return
        }
        if p == 1 && !splitOn {
            rightTab = tab
            persistTabs()
            ensureLoaded(currentTab)
            ensureLoaded(rightTab)
            // Same rule as a tab switch: a Hermes dashboard that has been backgrounded
            // long enough for WebKit to drop its sockets gets its reload as it reappears.
            maybeReloadStaleHermes(tab)
            setSplit(true, persist: true)
            setFocus(1)
            retryIfFailed(webViewFor(tab))
            slog("drag -> opened split: left=\(currentTab) right=\(rightTab)")
            return
        }
        routeTab(tab, toPane: p)
        setFocus(p)      // the pane you dropped onto becomes the focused one (syncs the strip)
        syncStrip()
        slog("drag -> tab \(tab) to pane \(p) (left=\(currentTab) right=\(rightTab))")
    }

    // ── second instances ("ghosts") ──

    // Tab → URL, independent of any webview identity. urlFor(_:) resolves by IDENTITY and
    // therefore cannot answer for a ghost, so both now go through this one table.
    func urlForTab(_ idx: Int) -> URL {
        guard idx >= 0 && idx < tabs.count else { return bridgeURL }
        return tabs[idx].url
    }

    // Create-on-first-need. The configuration is COPIED FROM THE PRIMARY (WKWebView's
    // `configuration` getter returns a copy), which is what carries the Odysseus skin
    // user script and the default website data store — so the second instance is styled
    // like the first and shares its cookies/login rather than asking to log in again.
    //
    // ⚠️ a plain WKWebView, deliberately NOT a DropWebView: file-drop handling belongs to
    // Mission Control's PRIMARY, and applyPanes keeps the DropOverlay with that one. A
    // ghost of the panel tab (idx 0) is allowed, but you cannot drop files onto it.
    func ghostFor(_ idx: Int) -> WKWebView {
        let id = tabId(idx)
        if let g = secondInstances[id] { return g }
        let wv = WKWebView(frame: .zero, configuration: webViewFor(idx).configuration)
        wv.translatesAutoresizingMaskIntoConstraints = false
        wv.uiDelegate = self
        wv.navigationDelegate = self
        if #available(macOS 12.0, *) { wv.underPageBackgroundColor = paneInk }
        secondInstances[id] = wv
        wv.load(URLRequest(url: urlForTab(idx)))
        slog("ghost -> created \(id)")
        return wv
    }

    // Memory discipline: a ghost lives only as long as a pane is showing it. The PRIMARY
    // is never destroyed, so closing the pane that holds the primary keeps the primary and
    // discards the copy — ⚠️ which means that copy's own navigation state is lost, by
    // design (there is nowhere honest to put it once there is one pane again).
    func destroyGhost(_ id: String) {
        guard let g = secondInstances.removeValue(forKey: id) else { return }
        g.stopLoading()
        g.navigationDelegate = nil
        g.uiDelegate = nil
        failedLoads.remove(ObjectIdentifier(g))
        g.removeFromSuperview()   // last strong reference goes with the dictionary entry
        slog("ghost -> destroyed \(id)")
    }

    // Called from applyPanes AFTER the ghost flags are normalised: anything the flags no
    // longer claim is gone. That single rule covers closing the split, closing either
    // pane, and moving a pane to a different tab.
    func releaseUnusedGhosts() {
        for id in Array(secondInstances.keys) {   // Array(): the dict is mutated in here
            let keptLeft = leftIsGhost && id == tabId(currentTab)
            let keptRight = splitOn && rightIsGhost && id == tabId(rightTab)
            if !keptLeft && !keptRight { destroyGhost(id) }
        }
    }

    // Show `tab` in pane `p` as a SECOND instance, the other pane keeping the primary.
    // Only reachable from a drag (dropTab); the strip still swaps.
    func openSecondInstance(_ tab: Int, onPane p: Int) {
        if p == 1 {
            rightTab = tab
            rightIsGhost = true
            leftIsGhost = false      // the left pane keeps/takes the primary
            currentTab = tab
        } else {
            currentTab = tab
            leftIsGhost = true
            rightIsGhost = false     // the right pane keeps the primary
            rightTab = tab
        }
        persistTabs()                // ⚠️ writes left == right; a relaunch repairs that to
                                     // the swap-based arrangement (ghosts are NOT persisted)
        ensureLoaded(tab)            // the primary loads on first borrow, exactly as before
        _ = ghostFor(tab)            // the copy loads itself on creation
        if !splitOn { setSplit(true, persist: true) }   // setSplit calls applyPanes
        else { applyPanes() }
        setFocus(p)
        syncStrip()
        slog("ghost -> tab \(tab) as a second instance in pane \(p) (left=\(currentTab) right=\(rightTab) leftGhost=\(leftIsGhost) rightGhost=\(rightIsGhost))")
    }

    // ✕ closes THAT pane: split turns off, the SURVIVOR's tab becomes the one tab, and
    // focus lands on the survivor (setSplit(false) forces focus 0, which is the only
    // pane left).
    @objc func closeLeft(_ sender: Any?) { closePane(0) }
    @objc func closeRight(_ sender: Any?) { closePane(1) }
    func closePane(_ p: Int) {
        guard splitOn else { return }
        slog("close pane \(p) (left=\(currentTab) right=\(rightTab))")
        let wasHermes = hermesVisible()
        if p == 0 { currentTab = rightTab }   // the right pane survives → it becomes THE tab
        setSplit(false, persist: true)
        // Closing a pane can be the moment Hermes stops being visible — same staleness
        // rule as a tab switch, so a backgrounded dashboard still gets its reload.
        if wasHermes && !hermesVisible() { hermesLastActive = Date() }
        seg.selectedSegment = currentTab
    }

    // Permanent split diagnostics. Visible with
    //   log stream --predicate 'process == "Harness"'
    // or by running /Applications/Harness.app/Contents/MacOS/Harness from a terminal.
    // NSString cast, not a bare String, so the %@ CVarArg is unambiguous.
    func slog(_ s: String) { NSLog("%@", ("[split] " + s) as NSString) }

    // ⫽ ON opens the right pane on the NEXT tab and leaves focus on the left; ⫽ OFF is
    // literally "close the right pane" (one code path, so the two gestures cannot drift).
    // Always stepping to (currentTab + 1) is deliberate: v1 reopened onto the remembered
    // right tab, which is what made the right pane feel stuck on Odysseus.
    @objc func toggleSplit(_ sender: Any?) {
        if splitOn { closePane(1); return }
        rightTab = (currentTab + 1) % tabTitles.count
        slog("toggle -> on (left=\(currentTab) right=\(rightTab))")
        persistTabs()
        ensureLoaded(rightTab)
        setSplit(true, persist: true)
        setFocus(0)
    }

    // THE FIX for "clicking ⫽ does nothing visible". `addArrangedSubview` alone never
    // POSITIONS the divider: a split view derives pane frames in adjustSubviews/resize,
    // so a pane inserted at runtime arrives at the frame it already had — for a freshly
    // built `NSView()` that is .zero, i.e. a right pane 0pt wide with the divider flush
    // against the window's right edge. No crash, button state flips, nothing visible.
    // So: force a layout pass, then set the divider explicitly.
    //
    // Only intervenes when a pane is DEGENERATE (< the 420 floor). A divider restored
    // from the autosave, or one the user dragged, is left exactly where it was.
    func positionDivider() {
        guard splitOn, rightPane.superview === splitView else { return }
        splitView.layoutSubtreeIfNeeded()
        let total = splitView.bounds.width
        guard total > 0 else { return }   // pre-window-display; the async pass retries
        if leftPane.frame.width < 420 || rightPane.frame.width < 420 {
            let pos = max(420, min(total - 420, (total / 2).rounded()))
            splitView.setPosition(pos, ofDividerAt: 0)
            splitView.layoutSubtreeIfNeeded()
        }
        slog("panes \(Int(leftPane.frame.width))/\(Int(rightPane.frame.width)) of \(Int(total))")
    }

    func setSplit(_ on: Bool, persist: Bool) {
        splitOn = on
        if on {
            if rightPane.superview !== splitView {
                splitView.addArrangedSubview(rightPane)
                // Only settable once the subview exists. Higher than the left pane's
                // 250 → the left edge is the one a window resize moves. ⚠️ see the
                // comment where the left value is set.
                splitView.setHoldingPriority(NSLayoutConstraint.Priority(251), forSubviewAt: 1)
            }
        } else {
            if rightPane.superview === splitView {
                splitView.removeArrangedSubview(rightPane)
                rightPane.removeFromSuperview()   // removeArrangedSubview alone keeps it a subview
            }
            focusedPane = 0
            UserDefaults.standard.set(0, forKey: "harness.split.focus")
        }
        splitButton.state = on ? .on : .off
        if persist { UserDefaults.standard.set(on, forKey: "harness.split.on") }
        persistTabs()
        if on && rightTab != currentTab { ensureLoaded(rightTab) }
        applyPanes()
        updateFocusStrips()
        syncStrip()
        let attached = (rightPane.superview === splitView)
        slog("setSplit(\(on)) rightAttached=\(attached) arranged=\(splitView.arrangedSubviews.count)")
        if on {
            positionDivider()
            // At LAUNCH restore, setSplit runs before the window is on screen, so
            // splitView.bounds is still zero and the sync pass above no-ops. One
            // runloop later the frame is real — this is that second chance.
            DispatchQueue.main.async { [weak self] in self?.positionDivider() }
        }
    }

    // Index → primary. Out-of-range degrades to the panel rather than trapping: an
    // index can only come from the strip, a drag or a restored default, and a crash on a
    // corrupt UserDefaults value would be a far worse failure than showing the panel.
    func webViewFor(_ idx: Int) -> WKWebView {
        guard idx >= 0 && idx < tabs.count else { return panelWV }
        return wvById[tabs[idx].id] ?? panelWV
    }
    // EVERY primary, not only the ones on the strip: applyPanes parks whatever neither
    // pane is showing, and a webview for a hidden entry must be parked too (it may
    // still hold a loaded page from before it was hidden).
    func allWebViews() -> [WKWebView] { return Array(wvById.values) }

    // Lazy-load rule unchanged: a webview loads on FIRST borrow, by either pane, and
    // exactly once. Mission Control (panelTab) is loaded by ensureBridgeThenLoad, never
    // here. Every OTHER tab is handled identically — an optional component that is not
    // running simply fails into the shared "Not reachable yet" placeholder and retries
    // on re-select / ⌘R via failedLoads. No per-tab special cases except Hermes's
    // config-generation bookkeeping.
    func ensureLoaded(_ idx: Int) {
        guard idx >= 0, idx < tabs.count else { return }
        let id = tabs[idx].id
        guard id != panelId else { return }
        guard !loadedTabs.contains(id) else { return }
        loadedTabs.insert(id)
        (wvById[id] ?? panelWV).load(URLRequest(url: urlForTab(idx)))
        // The first Hermes load records the generation it is loading against, so the
        // first tab switch back compares like with like instead of making no claim.
        if id == hermesId { syncHermesGen(reloadIfNewer: false) }
    }

    // Called from every path that makes the Hermes tab visible (routeTab + the
    // drag-opens-the-split branch). TWO independent reload rules live here — one
    // entry point, so they cannot drift:
    //
    //   1. STALENESS (unchanged): backgrounded longer than `staleAfter`, so WebKit
    //      will have dropped the dashboard's sockets.
    //   2. CONFIG GENERATION (new): we changed Hermes's configuration since this
    //      page loaded, and that page never refreshes itself.
    //
    // Rule 1 still fires exactly when it always did. Rule 2 is only reached when
    // rule 1 did not fire (one reload is enough) and is entirely asynchronous.
    //
    // Rule 2 is ALSO driven by updateHermesGenTimer's poll, which is what covers a Hermes
    // pane that was already on screen (split view — it never "becomes" visible). This
    // call site stays so that a tab switch checks IMMEDIATELY instead of waiting a tick.
    func maybeReloadStaleHermes(_ idx: Int) {
        guard idx == hermesTab, hermesLoaded,
              !failedLoads.contains(ObjectIdentifier(hermesWV)),
              hermesWV.url?.scheme == "http" else { return }
        if let since = hermesLastActive, Date().timeIntervalSince(since) > staleAfter {
            // Backgrounded long enough that WebKit will have dropped its sockets →
            // reload so the dashboard reconnects instead of showing "session ended".
            hermesLastActive = nil
            hermesWV.reload()
            // A reload for ANY reason re-reads the generation, so a later compare
            // cannot fire against a value from before this page.
            syncHermesGen(reloadIfNewer: false)
            return
        }
        syncHermesGen(reloadIfNewer: true)
    }

    // Read `hermes_config_gen` off the bridge's EXISTING /api/status and record it
    // against the currently loaded Hermes page. With `reloadIfNewer` the webview is
    // reloaded first when the bridge has moved on since that page loaded.
    //
    // FAIL SAFE BY CONSTRUCTION: any transport error, non-200, unparseable body or
    // missing/wrong-typed field returns without touching anything — an older bridge,
    // a bridge that is down, or a slow one all degrade to exactly today's behaviour.
    // Never blocks the UI thread (URLSession callback + a short timeout); the recorded
    // value is written BEFORE the reload decision, so a reload can never loop.
    //
    // `why` only labels the log line, so a poll-driven reload is distinguishable from a
    // tab-select one in `log stream` without reading the code.
    func syncHermesGen(reloadIfNewer: Bool, why: String = "tab") {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/status"))
        req.timeoutInterval = 2.0
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, resp, err in
            guard err == nil,
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let d = data,
                  let raw = try? JSONSerialization.jsonObject(with: d),
                  let obj = raw as? [String: Any],
                  let gen = obj["hermes_config_gen"] as? Int else { return }
            DispatchQueue.main.async {
                let prev = self.hermesCfgGen
                self.hermesCfgGen = gen          // record FIRST → cannot loop
                // prev == nil  → never read it before: no claim, no reload.
                // gen < prev   → the bridge restarted (the counter is process-lifetime).
                //                Recorded silently above; a restart is not a change.
                guard reloadIfNewer, let p = prev, gen > p else { return }
                // Re-check visibility/health on the main thread: the fetch is async, so
                // the user may have switched away or the page may have failed since it
                // was issued. visibleHermesWebViews() answers the visibility half (and
                // the hermesLoaded half for the primary); the filter answers the health
                // half, per surface, exactly as the single-webview version did.
                let targets = self.visibleHermesWebViews().filter {
                    !self.failedLoads.contains(ObjectIdentifier($0))
                        && $0.url?.scheme == "http"
                }
                guard !targets.isEmpty else { return }
                NSLog("%@", "[hermes] reload -> config generation \(gen) (\(why))" as NSString)
                for wv in targets { wv.reload() }
            }
        }.resume()
    }

    func retryIfFailed(_ wv: WKWebView) {
        guard failedLoads.contains(ObjectIdentifier(wv)) else { return }
        failedLoads.remove(ObjectIdentifier(wv))
        wv.load(URLRequest(url: urlFor(wv)))
        if wv === hermesWV { syncHermesGen(reloadIfNewer: false) }
    }

    // Reparent a view into a pane. Constraints against the OLD superview die with the
    // removal, so this is the only place pane membership is expressed.
    func attach(_ v: NSView, to host: NSView) {
        if v.superview === host { return }
        v.removeFromSuperview()
        v.translatesAutoresizingMaskIntoConstraints = false
        host.addSubview(v)
        NSLayoutConstraint.activate([
            v.topAnchor.constraint(equalTo: host.topAnchor),
            v.leadingAnchor.constraint(equalTo: host.leadingAnchor),
            v.trailingAnchor.constraint(equalTo: host.trailingAnchor),
            v.bottomAnchor.constraint(equalTo: host.bottomAnchor),
        ])
    }

    // Place every webview. `rightBorrows` (two DIFFERENT tabs) is the ordinary state; the
    // other legitimate one is "same tab, one pane holding a second instance". The
    // placeholder branch remains a SAFETY NET for a state we should never be asked for.
    //
    // attach() early-returns when a view is already in the right host, so calling this
    // when nothing changed reparents nothing — no relayout, no page reload, no thrash.
    func applyPanes() {
        let leftIdx = currentTab
        let rightBorrows = splitOn && rightTab != leftIdx

        // Normalise the ghost flags before anything reads them: a copy only makes sense
        // while both panes hold the same tab, and only one pane can hold the copy.
        if !splitOn || rightTab != leftIdx { leftIsGhost = false; rightIsGhost = false }
        if leftIsGhost && rightIsGhost { rightIsGhost = false }
        releaseUnusedGhosts()

        // Which VIEW each pane holds. `rightWV == nil` while the split is ON is the OLD
        // safety-net state (both panes asking for the same tab with no copy anywhere) and
        // still renders the placeholder — it should be unreachable, not silently blank.
        let leftWV: WKWebView = leftIsGhost ? ghostFor(leftIdx) : webViewFor(leftIdx)
        var rightWV: WKWebView? = nil
        if splitOn {
            if rightIsGhost { rightWV = ghostFor(rightTab) }
            else if rightBorrows || leftIsGhost { rightWV = webViewFor(rightTab) }
        }

        // Park every primary neither pane is showing (ghosts are never parked — they are
        // destroyed instead, above).
        for wv in allWebViews() where wv !== leftWV && wv !== rightWV {
            attach(wv, to: park)     // park is hidden → same effect as the old isHidden
        }
        attach(leftWV, to: leftHost)
        if let r = rightWV {
            if rightPlaceholder.superview != nil { rightPlaceholder.removeFromSuperview() }
            attach(r, to: rightHost)
        } else if splitOn {
            attach(rightPlaceholder, to: rightHost)
        }

        // The DropOverlay follows Mission Control's PRIMARY webview — file drops belong to
        // it only, so a panel ghost gets no overlay. It must stay ABOVE the webview it
        // guards, so it is re-added when (and only when) its host changed or a webview
        // landed on top of it.
        if let ov = dropOverlay {
            let target: NSView? = (leftWV === panelWV) ? leftHost
                                : ((rightWV === panelWV) ? rightHost : nil)
            if let t = target {
                if ov.superview !== t { attach(ov, to: t) }
                else if t.subviews.last !== ov { ov.removeFromSuperview(); attach(ov, to: t) }
            } else if ov.superview != nil {
                ov.removeFromSuperview()
            }
        }

        // Permanent diagnostics: `log stream --predicate 'process == "Harness"'`, or just
        // run the binary from a terminal, and one click tells you exactly what fired and
        // what widths came out of it. Cheap; keeps this class of bug one paste away.
        slog("applyPanes left=\(leftIdx) right=\(rightTab) focus=\(focusedPane) borrows=\(rightBorrows) ghosts=\(leftIsGhost ? "L" : "-")\(rightIsGhost ? "R" : "-")(\(secondInstances.count)) parkHidden=\(park.isHidden) panes \(Int(leftPane.frame.width))/\(Int(rightPane.frame.width))")

        // Last, because it reads the state this function just settled: arm the
        // config-generation poll iff a Hermes surface ended up on screen, tear it down
        // otherwise. Every path that changes what is visible funnels through here (and
        // ensureLoaded — which sets hermesLoaded — always runs BEFORE it), so this one
        // call site covers tab routing, ⫽, a pane ✕, a drag-drop and a second instance.
        updateHermesGenTimer()
    }

    func makeRightPlaceholder() -> NSView {
        // v2 SAFETY NET only. The two panes CAN now hold the same tab — but when they do,
        // one of them holds a second instance of it, so this is still unreachable: it
        // exists so that a state with neither a distinct tab nor a copy renders something
        // honest instead of an empty pane. It cannot BE
        // showUnreachable: that mechanism loads HTML into a webview, and the premise
        // here is that the webview is busy in the other pane.
        let v = NSView()
        v.wantsLayer = true
        v.layer?.backgroundColor = paneInk.cgColor
        let l = NSTextField(labelWithString: "Already open in the left pane.")
        l.font = NSFont.systemFont(ofSize: 13)
        l.textColor = paneFaint
        l.translatesAutoresizingMaskIntoConstraints = false
        v.addSubview(l)
        NSLayoutConstraint.activate([
            l.centerXAnchor.constraint(equalTo: v.centerXAnchor),
            l.centerYAnchor.constraint(equalTo: v.centerYAnchor),
        ])
        return v
    }

    // Min pane width 420, enforced on the divider drag.
    func splitView(_ sv: NSSplitView, constrainMinCoordinate proposedMin: CGFloat,
                   ofSubviewAt dividerIndex: Int) -> CGFloat {
        return max(proposedMin, 420)
    }
    func splitView(_ sv: NSSplitView, constrainMaxCoordinate proposedMax: CGFloat,
                   ofSubviewAt dividerIndex: Int) -> CGFloat {
        return min(proposedMax, sv.bounds.width - 420)
    }

    // The pane ⌘R acts on: the last one clicked (left when split is off). A pane showing a
    // SECOND INSTANCE reloads that copy, not the primary in the other pane.
    func visibleWebView() -> WKWebView? {
        if focusedPane == 1 && splitOn && (rightTab != currentTab || rightIsGhost) {
            return rightIsGhost ? secondInstances[tabId(rightTab)] : webViewFor(rightTab)
        }
        if leftIsGhost { return secondInstances[tabId(currentTab)] }
        return webViewFor(currentTab)
    }

    func urlFor(_ wv: WKWebView) -> URL {
        // A second instance is not one of the primaries, so ask the ghost table FIRST —
        // otherwise a ⌘R / retry on a ghost would send it to the bridge's URL. Both
        // tables are keyed by ID, so this answers for a HIDDEN entry too (a ⌘R on a
        // pane still showing a tab the user just un-pinned must not go to the bridge).
        if let hit = secondInstances.first(where: { $0.value === wv }) { return urlForId(hit.key) }
        if let hit = wvById.first(where: { $0.value === wv }) { return urlForId(hit.key) }
        return bridgeURL
    }

    @objc func reloadTab(_ sender: Any?) {
        guard let wv = visibleWebView() else { return }
        failedLoads.remove(ObjectIdentifier(wv))
        // If the last load failed (or we're on the placeholder), go back to the real URL.
        if let u = wv.url, u.scheme == "http" { wv.reload() }
        else { wv.load(URLRequest(url: urlFor(wv))) }
        // A manual reload is still a reload: re-record so the automatic rule does not
        // fire a second time for a change this ⌘R already picked up.
        if wv === hermesWV { syncHermesGen(reloadIfNewer: false) }
    }

    // Failed navigation → dark editorial placeholder (never a white void) + retry paths.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showUnreachable(webView)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showUnreachable(webView)
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let u = webView.url, u.scheme == "http" { failedLoads.remove(ObjectIdentifier(webView)) }
        // A load that actually landed clears the crash memory: the next termination on
        // this tab is a NEW incident and gets its own automatic retry.
        crashedOnce.remove(ObjectIdentifier(webView))
    }

    // ── the web content process died ────────────────────────────────────────
    // ⚠️ THE MISSING DELEGATE, same class as runOpenPanelWith (⊕ attach), the media
    // capture grant (● talk) and WKDownloadDelegate (downloads): when WebKit kills a
    // tab's web content process — jetsam under memory pressure is the usual reason, and
    // LOffice is by far the heaviest page we serve at ~10.5 MB of script plus a canvas
    // engine — the view is left showing NOTHING. No error, no navigation callback, no
    // console, and no amount of looking at the page can tell you it happened. That is
    // an exact description of the symptom this delegate was written for.
    //
    // Policy: reload ONCE, silently (a jetsam under transient pressure is recoverable
    // and a reload is what recovers it). A SECOND death without an intervening
    // successful load is not transient, so say so rather than loop.
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        let key = ObjectIdentifier(webView)
        let title = tabRegistry.first { wvById[$0.id] === webView }?.title ?? "a tab"
        if crashedOnce.contains(key) {
            NSLog("%@", "[tab] \(title): web content process died again — showing the notice" as NSString)
            failedLoads.insert(key)
            webView.loadHTMLString(
                "<body style='background:#0b0a10;color:#6f6a80;font-family:-apple-system;" +
                "display:flex;align-items:center;justify-content:center;height:100vh'>" +
                "<div style='text-align:center;max-width:460px'>" +
                "<h2 style='color:#efe7d7;font-weight:500'>This tab ran out of memory</h2>" +
                "<p>macOS stopped its web process twice in a row. Close a pane or eject a " +
                "model to free memory, then press &#8984;R to load it again.</p></div></body>",
                baseURL: nil)
            return
        }
        crashedOnce.insert(key)
        NSLog("%@", "[tab] \(title): web content process died — reloading once" as NSString)
        if let u = webView.url, u.scheme == "http" {
            webView.load(URLRequest(url: u))
        } else {
            webView.reload()
        }
    }

    // ── download routing (all five tabs share this delegate) ──
    // A response the webview cannot render (attachment disposition, unknown MIME) is
    // turned into a download instead of being silently discarded. Everything WebKit CAN
    // show is still shown — byte-compatible with the previous no-delegate default.
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if #available(macOS 11.3, *), !navigationResponse.canShowMIMEType {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    // `<a download>` clicks — including the blob: URLs a SPA builds client-side.
    // WebKit sets shouldPerformDownload for them; every other navigation is allowed
    // exactly as before (no delegate = .allow).
    func webView(_ webView: WKWebView,
                 decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if #available(macOS 11.3, *), navigationAction.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        decisionHandler(.allow)
    }

    @available(macOS 11.3, *)
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse,
                 didBecome download: WKDownload) {
        download.delegate = downloadHandler as? WKDownloadDelegate
    }

    @available(macOS 11.3, *)
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction,
                 didBecome download: WKDownload) {
        download.delegate = downloadHandler as? WKDownloadDelegate
    }

    func showUnreachable(_ wv: WKWebView) {
        failedLoads.insert(ObjectIdentifier(wv))
        wv.loadHTMLString(
            "<body style='background:#0b0a10;color:#6f6a80;font-family:-apple-system;" +
            "display:flex;align-items:center;justify-content:center;height:100vh'>" +
            "<div style='text-align:center'><h2 style='color:#efe7d7;font-weight:500'>Not reachable yet</h2>" +
            "<p>Start the component in Mission Control,<br>then re-select this tab &mdash; or press &#8984;R.</p></div></body>",
            baseURL: nil)
    }

    func ensureBridgeThenLoad(attempt: Int) {
        portOpen { open in
            if open {
                DispatchQueue.main.async { self.panelWV.load(URLRequest(url: bridgeURL)) }
            } else if attempt == 0 {
                self.startBridge()
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                    self.ensureBridgeThenLoad(attempt: 1)
                }
            } else if attempt < 20 {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) {
                    self.ensureBridgeThenLoad(attempt: attempt + 1)
                }
            } else {
                DispatchQueue.main.async {
                    self.panelWV.loadHTMLString(
                        "<body style='background:#0b0a10;color:#c9c4d4;font-family:-apple-system;" +
                        "display:flex;align-items:center;justify-content:center;height:100vh'>" +
                        "<div><h2 style='color:#efe7d7'>Bridge failed to start</h2>" +
                        "<p>Check data/logs/bridge.log in the harness folder.</p></div></body>",
                        baseURL: nil)
                }
            }
        }
    }

    func portOpen(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/status"))
        req.timeoutInterval = 0.6
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            done((resp as? HTTPURLResponse)?.statusCode == 200)
        }.resume()
    }

    func startBridge() {
        let py = "\(resolvedRoot)/data/bridge-venv/bin/python"
        guard FileManager.default.isExecutableFile(atPath: py) else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "uvicorn", "bridge.app:app",
                       "--host", "127.0.0.1", "--port", "8700"]
        p.currentDirectoryURL = URL(fileURLWithPath: resolvedRoot)
        let log = FileHandle(forWritingAtPath: logPath()) ?? FileHandle.nullDevice
        log.seekToEndOfFile()
        p.standardOutput = log
        p.standardError = log
        do { try p.run(); bridgeProcess = p; spawnedBridge = true } catch {}
    }

    func logPath() -> String {
        let dir = "\(resolvedRoot)/data/logs"
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let path = "\(dir)/bridge.log"
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        return path
    }

    // target=_blank / new-window requests → open in the user's default browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        // blob:/data:/javascript: are in-page constructs — handing one to NSWorkspace
        // does nothing useful (a `<a download target=_blank>` on a client-built blob
        // lands here). Everything else keeps the previous behaviour exactly.
        if let url = navigationAction.request.url {
            let s = (url.scheme ?? "").lowercased()
            if s != "blob" && s != "data" && s != "javascript" { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    // <input type="file"> — WKWebView shows NO file dialog unless the app provides one.
    // Without this, the panel's ⊕ image-attach button silently does nothing.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.begin { resp in
            completionHandler(resp == .OK ? panel.urls : nil)
        }
    }

    // PHASE D (dictation): getUserMedia inside a WKWebView is DENIED by default —
    // WebKit asks the host app, and with no delegate method the promise rejects and
    // the panel's ● talk button just says "microphone permission". Same class of
    // silent no-op as runOpenPanelWith above (that one broke ⊕ attach).
    //
    // .grant is safe here because the only page allowed to ask is our own panel on
    // 127.0.0.1:8700, and macOS still shows its own TCC prompt the first time (which
    // needs NSMicrophoneUsageDescription in Info.plist — added in build_app.sh).
    // Camera is refused: nothing in the harness uses it, so a request would only ever
    // be something we did not ship.
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView,
                 requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo,
                 type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(type == .camera ? .deny : .grant)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if spawnedBridge { bridgeProcess?.terminate() }   // only stop what we started
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

// minimal menu so ⌘Q / ⌘W / copy-paste work
let mainMenu = NSMenu()
let appItem = NSMenuItem()
mainMenu.addItem(appItem)
let appMenu = NSMenu()
let reloadItem = NSMenuItem(title: "Reload Tab", action: #selector(AppDelegate.reloadTab(_:)), keyEquivalent: "r")
reloadItem.target = delegate
appMenu.addItem(reloadItem)
appMenu.addItem(withTitle: "Quit Harness", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appItem.submenu = appMenu
let editItem = NSMenuItem()
mainMenu.addItem(editItem)
let editMenu = NSMenu(title: "Edit")
editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editItem.submenu = editMenu
app.mainMenu = mainMenu

app.run()
