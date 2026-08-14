// Harness.app — native macOS shell. One window, tabbed:
//   • Mission Control (the Bridge control panel, :8700)
//   • Odysseus (the workspace UI, :7860)
//   • Hermes (the agent dashboard, :9119)
//   • VoiceStudio (voice component SPA, :3900)   — optional, often not running
//   • Voicebox (voice component SPA, :17493)     — optional, often not running
// Each tab is its own top-level WKWebView load — sidesteps Odysseus's X-Frame-Options/
// frame-ancestors (which block iframing) entirely. Auto-starts the bridge on launch.
// Built by scripts/build_app.sh (which generates Config.swift with harnessRoot).

import Cocoa
import WebKit

let bridgeURL = URL(string: "http://127.0.0.1:8700")!
let odysseusURL = URL(string: "http://127.0.0.1:7860")!
let hermesURL = URL(string: "http://127.0.0.1:9119")!
let voiceStudioURL = URL(string: "http://127.0.0.1:3900")!
let voiceboxURL = URL(string: "http://127.0.0.1:17493")!

// ONE source for the tab strings. v2 has exactly ONE tab strip (the right pane's mini
// strip is gone — see the split-view v2 note on AppDelegate), so this array feeds the
// single NSSegmentedControl and nothing else can drift from it.
let tabTitles = ["Mission Control", "Odysseus", "Hermes", "VoiceStudio", "Voicebox"]

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
                         NSSplitViewDelegate {
    // retained handler for every tab's downloads (see DownloadHandler); AnyObject so the
    // stored property itself carries no availability requirement.
    var downloadHandler: AnyObject?
    var window: NSWindow!
    var dropOverlay: NSView?
    var panelWV: WKWebView!      // Mission Control (:8700)
    var odyWV: WKWebView!        // Odysseus (:7860), lazy-loaded on first select
    var odyLoaded = false
    var hermesWV: WKWebView!     // Hermes dashboard (:9119), lazy-loaded on first select
    var hermesLoaded = false
    var vsWV: WKWebView!         // VoiceStudio (:3900), lazy-loaded on first select
    var vsLoaded = false
    var vbWV: WKWebView!         // Voicebox (:17493), lazy-loaded on first select
    var vbLoaded = false
    var failedLoads = Set<ObjectIdentifier>()   // webviews whose last load failed → retry on select/⌘R
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
    var splitOn = false
    var rightTab = 1
    var focusedPane = 0              // 0 = left, 1 = right — the tab strip's + ⌘R's target
    var clickMonitor: Any?
    var hermesLastActive: Date?
    let staleAfter: TimeInterval = 600   // 10 minutes backgrounded → reload on re-select
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
        window.minSize = NSSize(width: 900, height: 620)
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

        seg = NSSegmentedControl(
            labels: tabTitles,
            trackingMode: .selectOne,
            target: self, action: #selector(tabChanged(_:)))
        seg.selectedSegment = 0
        seg.translatesAutoresizingMaskIntoConstraints = false
        tabBar.addSubview(seg)

        // ⫽ — the split toggle, at the right end of the strip.
        splitButton = NSButton(title: "⫽", target: self, action: #selector(toggleSplit(_:)))
        splitButton.setButtonType(.pushOnPushOff)
        splitButton.bezelStyle = .texturedRounded
        splitButton.toolTip = "Split view"
        splitButton.translatesAutoresizingMaskIntoConstraints = false
        tabBar.addSubview(splitButton)

        // ── web views ──
        // DropWebView: native drag-destination so Finder image drops reach the chat.
        panelWV = DropWebView(frame: .zero, configuration: WKWebViewConfiguration())

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

        // Voice components ship their own SPAs — plain webviews, no skin, no drag handling.
        vsWV = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        vbWV = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())

        for wv in [panelWV!, odyWV!, hermesWV!, vsWV!, vbWV!] {
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
        rightTab = ud.object(forKey: "harness.split.right") as? Int ?? 1
        if rightTab < 0 || rightTab >= tabTitles.count { rightTab = 1 }
        if wasSplit {
            currentTab = ud.object(forKey: "harness.split.left") as? Int ?? 0
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

        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        beginLaunch()
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
    func hermesVisible() -> Bool { return currentTab == 2 || (splitOn && rightTab == 2) }

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
    }

    // THE v2 routing rule. The strip drives the FOCUSED pane. If the OTHER pane already
    // holds the requested tab, the two panes SWAP — one webview, two panes, and a
    // predictable visible outcome instead of v1's out-of-nowhere placeholder.
    @objc func tabChanged(_ sender: NSSegmentedControl) {
        let idx = sender.selectedSegment
        guard idx >= 0 && idx < tabTitles.count else { return }
        let wasHermes = hermesVisible()
        if splitOn && focusedPane == 1 {
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
        slog("tab -> \(idx) focus=\(focusedPane) left=\(currentTab) right=\(rightTab)")
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

    func webViewFor(_ idx: Int) -> WKWebView {
        switch idx {
        case 1: return odyWV
        case 2: return hermesWV
        case 3: return vsWV
        case 4: return vbWV
        default: return panelWV
        }
    }
    func allWebViews() -> [WKWebView] { return [panelWV, odyWV, hermesWV, vsWV, vbWV] }

    // Lazy-load rule unchanged: a webview loads on FIRST borrow, by either pane.
    // Mission Control (0) is loaded by ensureBridgeThenLoad, never here.
    func ensureLoaded(_ idx: Int) {
        switch idx {
        case 1: if !odyLoaded { odyLoaded = true; odyWV.load(URLRequest(url: odysseusURL)) }
        case 2: if !hermesLoaded { hermesLoaded = true; hermesWV.load(URLRequest(url: hermesURL)) }
        // Voice tabs: components are OPTIONAL and usually stopped → the first load
        // normally fails into the "Not reachable yet" placeholder, and re-select /
        // ⌘R retries via the shared failedLoads path. No staleness reload (that
        // exists for Hermes's WS dashboard only).
        case 3: if !vsLoaded { vsLoaded = true; vsWV.load(URLRequest(url: voiceStudioURL)) }
        case 4: if !vbLoaded { vbLoaded = true; vbWV.load(URLRequest(url: voiceboxURL)) }
        default: break
        }
    }

    func maybeReloadStaleHermes(_ idx: Int) {
        guard idx == 2, hermesLoaded, let since = hermesLastActive,
              Date().timeIntervalSince(since) > staleAfter,
              !failedLoads.contains(ObjectIdentifier(hermesWV)),
              hermesWV.url?.scheme == "http" else { return }
        // Backgrounded long enough that WebKit will have dropped its sockets →
        // reload so the dashboard reconnects instead of showing "session ended".
        hermesLastActive = nil
        hermesWV.reload()
    }

    func retryIfFailed(_ wv: WKWebView) {
        guard failedLoads.contains(ObjectIdentifier(wv)) else { return }
        failedLoads.remove(ObjectIdentifier(wv))
        wv.load(URLRequest(url: urlFor(wv)))
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

    // Place every webview. The swap rule keeps currentTab != rightTab whenever split is
    // on, so `rightBorrows` is true in every normal state; the placeholder branch is a
    // SAFETY NET for a state we should never be asked for, not a routine outcome.
    //
    // attach() early-returns when a view is already in the right host, so calling this
    // when nothing changed reparents nothing — no relayout, no page reload, no thrash.
    func applyPanes() {
        let leftIdx = currentTab
        let rightBorrows = splitOn && rightTab != leftIdx

        for (i, wv) in allWebViews().enumerated() {
            if i == leftIdx { continue }
            if rightBorrows && i == rightTab { continue }
            attach(wv, to: park)     // park is hidden → same effect as the old isHidden
        }
        attach(webViewFor(leftIdx), to: leftHost)
        if rightBorrows {
            if rightPlaceholder.superview != nil { rightPlaceholder.removeFromSuperview() }
            attach(webViewFor(rightTab), to: rightHost)
        } else if splitOn {
            attach(rightPlaceholder, to: rightHost)
        }

        // The DropOverlay follows Mission Control's pane — file drops belong to it only.
        // It must stay ABOVE the webview it guards, so it is re-added when (and only
        // when) its host changed or a webview landed on top of it.
        if let ov = dropOverlay {
            let target: NSView? = (leftIdx == 0) ? leftHost
                                : ((rightBorrows && rightTab == 0) ? rightHost : nil)
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
        slog("applyPanes left=\(leftIdx) right=\(rightTab) focus=\(focusedPane) borrows=\(rightBorrows) parkHidden=\(park.isHidden) panes \(Int(leftPane.frame.width))/\(Int(rightPane.frame.width))")
    }

    func makeRightPlaceholder() -> NSView {
        // v2 SAFETY NET only. The swap rule means the two panes can never ask for the
        // same tab, so this should be unreachable — it exists so that an impossible
        // state renders something honest instead of an empty pane. It cannot BE
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

    // The pane ⌘R acts on: the last one clicked (left when split is off).
    func visibleWebView() -> WKWebView? {
        if focusedPane == 1 && splitOn && rightTab != currentTab { return webViewFor(rightTab) }
        return webViewFor(currentTab)
    }

    func urlFor(_ wv: WKWebView) -> URL {
        if wv === odyWV { return odysseusURL }
        if wv === hermesWV { return hermesURL }
        if wv === vsWV { return voiceStudioURL }
        if wv === vbWV { return voiceboxURL }
        return bridgeURL
    }

    @objc func reloadTab(_ sender: Any?) {
        guard let wv = visibleWebView() else { return }
        failedLoads.remove(ObjectIdentifier(wv))
        // If the last load failed (or we're on the placeholder), go back to the real URL.
        if let u = wv.url, u.scheme == "http" { wv.reload() }
        else { wv.load(URLRequest(url: urlFor(wv))) }
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
