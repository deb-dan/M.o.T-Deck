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
import Darwin
import WebKit

let bridgeURL = URL(string: "http://127.0.0.1:8700")!

// Failure after Process.run() must never leave an unrecorded child behind. This helper
// accepts only the Process handle returned by that exact launch, asks it to terminate,
// waits for exit, and escalates only while the same handle still reports running. It
// is intentionally not a general PID/name/port cleanup primitive.
func terminateExactSpawnedChild(_ process: Process) {
    guard process.isRunning else { return }
    process.terminate()
    let deadline = Date().addingTimeInterval(3)
    while process.isRunning && Date() < deadline {
        usleep(50_000)
    }
    if process.isRunning {
        Darwin.kill(process.processIdentifier, SIGKILL)
    }
    process.waitUntilExit()
}

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
    // MOT Deck — the Bridge control panel. Index 0 BY CONSTRUCTION: it is the
    // app's home, the page the bridge-wait screen writes into, and the only file-drop
    // target (DropOverlay). Keep it first. (The id stays "mc": ids are internal keys.)
    HarnessTab(id: "mc", title: "MOT Deck", url: bridgeURL),
    // Enter through the bridge's managed-cookie handoff, then redirect to Odysseus's
    // own unmodified page on :7860. v1.5.81 rotated the old repository password into
    // the protected local store, but a direct URL still showed the ordinary login form
    // with no safe way for the user to know that replacement. The handoff authenticates
    // server-to-server through Odysseus's own API and gives WebKit only its HttpOnly
    // session cookie — never the password, never injected JavaScript. See U145 and
    // bridge/routers/ody.py:ody_managed_workspace.
    HarnessTab(id: "odysseus", title: "Odysseus", url: URL(string: "http://127.0.0.1:8700/odysseus")!),
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
    // DeepSeek Harness — the third coding lane (`dsh web`, MIT, pre-1.0). Its own
    // server serves its own SPA and its own JSON/websocket API on one loopback port.
    //
    // ⚠️ THE URL IS :3080 DIRECTLY, NOT A BRIDGE REDIRECT, AND THE DIFFERENCE FROM THE
    // ROW ABOVE IS THE POINT. OpenCode needs the bridge because its usable landing is a
    // base64url-encoded WORKSPACE PATH inside the URL — a route only the bridge can
    // build, since only it knows ROOT. dsh has no such deep link: its own root document
    // IS the app, and the workspace is chosen inside the page (see U67). Inventing a
    // /deepseek redirect that only ever forwarded to a constant would add a second hop,
    // a second failure mode and a second place the port is written down, for nothing.
    // 3080 is upstream's own default AND harness.yaml's `port` AND what
    // start_component.sh passes explicitly — one number, three agreeing sources.
    //
    // Nothing else in this file needs an edit for this tab: it is a third-party page,
    // so it falls into the final `else` of the wvById loop and gets a bare WKWebView
    // with no `harness` handler and no shellScript. Deliberately NOT added to the
    // loffice/aider/goose/comfy/compose/gooseui branch — that grants window.webkit to a
    // page we did not write. It gets no OpenCode-style user script either: that one
    // exists to relabel OpenCode's auto-minted draft tabs and has no analogue here.
    HarnessTab(id: "deepseek", title: "DeepSeek",
               url: URL(string: "http://127.0.0.1:3080")!),
    // Music is OUR OWN panel page, opened chromeless: same bridge origin, ?solo=music
    // hides the sidebar + topbar and pins the panel to the Music view. It is therefore
    // a second load of the panel document, deliberately — a native tab that is always
    // reachable, while the in-panel Music view keeps working exactly as before.
    // ⚠️ THE TITLE BECAME "Music Classic" AT THE CONSOLIDATION SLICE (Debi's ruling
    // 2026-08-29: ONE Music door, both looks behind it) AND THE ID DID NOT MOVE — the
    // Goose CLI rule verbatim. `music` is still the id, still `?solo=music`, still the
    // same untouched page; what changed is that the tab called "Music" is now the
    // Studio below, and this one is the second look you reach from its header.
    // ⚠️ IT IS ALSO THE ONE TAB THE NAV MODEL MAY NEVER PIN (nav.py gives it `bars: ()`
    // + `tab_only`). It reaches the strip only through the last-three window, which is
    // why `can_tab` exists there and why switchTab below must keep working for it.
    // v1.5.60: the "Music Classic" tab is GONE — Classic is reached in place (the
    // Studio header's dropdown navigates the one Music tab to ?solo=music and back).
    // A shell tab here let the ⋯/window path re-create the second Music tab Debi's
    // one-door ruling removed. Saved layouts naming `music` are SUPERSEDED-mapped.
    // Aider — the coding agent, running in a pseudo-terminal. Also ours, also the
    // bridge origin, but its OWN document (/aider): it loads xterm.js and talks to
    // ws://…/api/pty/aider, so it must not carry the panel's poll loops.
    HarnessTab(id: "aider", title: "Aider", url: URL(string: "http://127.0.0.1:8700/aider")!),
    // Goose CLI — the third agent lane, and a pty for the same verified reason Aider is:
    // goose's own CLI has NO browser UI at all (no `web`, no `ui` subcommand; `goose
    // serve` is an ACP client API that serves no page — docs/research/2026-08-28-goose-
    // source-verify.md item 4). Ours, bridge origin, its own document (/goose): xterm.js
    // plus ws://…/api/pty/goose, so it must not carry the panel's poll loops.
    //
    // ⚠️ THE TITLE GAINED "CLI" AT THE GOOSE UI SLICE (Debi's naming ruling 2026-08-29)
    // AND THE ID DID NOT MOVE. There are two goose tabs now, and "Goose" alone stopped
    // saying which one; `goose` stays the id because it is also the route, the pidfile
    // and the row in every saved nav.json. LOffice's rule: internal names do not churn
    // with a wordmark. The panel's mirror carries the same title, spelled identically —
    // the switchTab bridge resolves by id first, but a drifted title is still a bug.
    //
    // ⚠️ IT IS IN THE REGISTRY BUT NOT IN navDefaultTopbar, AND BOTH ARE REQUIRED. The
    // registry is "does this build know that tab at all" — switchTab shows a hidden tab
    // for the session, which is how the sidebar row opens it. navDefaultTopbar is the
    // PINNED prefix, and test_nav_model.py asserts it equals nav.py's pinned defaults;
    // goose is declared unpinned there (the strip is at 11 of 12), so it must NOT appear
    // in the list below or the three-way agreement breaks.
    HarnessTab(id: "goose", title: "Goose CLI", url: URL(string: "http://127.0.0.1:8700/goose")!),
    // Goose UI — goose Desktop's OWN renderer (vendored, unmodified, v1.5.40), served by
    // the bridge at /gooseui/ and talking WebSocket ACP to a goosed WE supervise. Ours by
    // ORIGIN and by supervision even though the bundle is upstream's: it is served from
    // :8700 with our preload shim injected, which is why it earns the first-party handler
    // below. Its own document for Generate's reason — it is a whole React app.
    //
    // ⚠️ THE TRAILING SLASH IS LOAD-BEARING. /gooseui 308-redirects here; the bundle
    // references its assets RELATIVELY, so without the slash they resolve against
    // /assets/ — a real, occupied mount on this origin — and the tab paints a black
    // rectangle with no error (v1.5.40 A1, measured). Pointing the tab straight at the
    // slash form also spares every launch a redirect.
    //
    // ⚠️ IT IS A SECOND, SEPARATE TAB FROM "Goose CLI" ABOVE, ON PURPOSE, AND NEITHER MAY
    // BE "CLEANED UP" INTO THE OTHER. Debi's ruling (ledger S14) is that both lanes
    // coexist; they hold separate goose homes and separate session stores and were proven
    // alive simultaneously. Removing either takes a real surface away from the user.
    //
    // ⚠️ IN THE REGISTRY BUT NOT IN navDefaultTopbar — goose's, comfy's and compose's
    // note applies verbatim: `gooseui` is declared unpinned in nav.py, so it must NOT
    // appear in that list or the three-way agreement breaks.
    HarnessTab(id: "gooseui", title: "Goose UI",
               url: URL(string: "http://127.0.0.1:8700/gooseui/")!),
    // LOffice — spreadsheets over vendored Univer, served from OUR bridge (/office).
    // Ours, bridge origin, its own document for the same reason Aider is: it loads
    // ~10MB of Univer UMD and must not carry the panel's poll loops. Debi suggested
    // "Office Lane"; the tab-strip width budget below rules a two-word title out, so
    // the name is LOffice (2026-08-21). The ROUTE stays /office: internal names do
    // not churn with a wordmark.
    HarnessTab(id: "loffice", title: "LOffice", url: URL(string: "http://127.0.0.1:8700/office")!),
    // Generate — MOT Deck's OWN image/video surface (v1.5.36), served by the bridge at
    // /comfy and driving the ComfyUI engine through /api/comfy/*. Ours, bridge origin,
    // its own document for LOffice's reason: it renders a gallery and long-lived
    // download/generate progress, so it must not carry the panel's poll loops.
    //
    // ⚠️ IT IS A SECOND, SEPARATE TAB FROM "ComfyUI" ABOVE, ON PURPOSE. That one loads
    // upstream's stock UI straight off :8188; this one is our page. Removing or
    // renaming either would take a real surface away from the user.
    //
    // ⚠️ IN THE REGISTRY BUT NOT IN navDefaultTopbar, AND BOTH ARE REQUIRED — goose's
    // note below-left applies verbatim: the registry is "does this build know that tab
    // at all" (switchTab shows a hidden tab for the session, which is how the sidebar
    // row opens it), while navDefaultTopbar is the PINNED prefix that test_nav_model.py
    // asserts equals nav.py's pinned defaults. `comfy` is declared unpinned there, so it
    // must NOT appear in that list or the three-way agreement breaks.
    HarnessTab(id: "comfy", title: "Generate", url: URL(string: "http://127.0.0.1:8700/comfy")!),
    // Compose — the ALTERNATIVE music surface (docs/FABLE-MUSIC-COMPOSE-SPEC.md), served
    // by the bridge at /compose and driving the SAME /api/music/* routes the panel's
    // Music view drives. Ours, bridge origin, its own document for Generate's reason: it
    // plays audio and watches a render that can run for minutes, so it must not carry
    // the panel's poll loops.
    //
    // ⚠️ IT IS A SECOND, SEPARATE TAB FROM "Music" ABOVE, ON PURPOSE, AND NEITHER MAY BE
    // "CLEANED UP" INTO THE OTHER. Music is the shipped view inside the panel; this is
    // the redesigned surface Debi asked for so the two can be compared live. The ruling
    // is that both stay until they choose.
    //
    // ⚠️ IN THE REGISTRY BUT NOT IN navDefaultTopbar — goose's and comfy's note applies
    // verbatim: the registry is "does this build know that tab at all", navDefaultTopbar
    // is the PINNED prefix that test_nav_model.py asserts equals nav.py's pinned
    // defaults, and `compose` is declared unpinned there.
    // ⚠️ THE TITLE BECAME "Music" AT THE CONSOLIDATION SLICE AND THE ID DID NOT MOVE:
    // `compose` is the route (/compose), the tab id and the row in every saved
    // nav.json. This is THE Music tab now — the Studio look, opening by default, with
    // Classic one header dropdown away.
    HarnessTab(id: "compose", title: "Music", url: URL(string: "http://127.0.0.1:8700/compose")!),
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
//
// ⚠️ v1.5.26 — DEBI'S ORDER: MOT Deck · Hermes · Unsloth · OpenCode · Odysseus ·
// VoiceStudio · ComfyUI · Aider · LOffice · Music · Voicebox. Same eleven ids, new
// reading order. Changing this list alone changes only a FRESH machine: every machine
// that has opened the panel has a data/nav.json whose saved order applyNav puts back.
// bridge/nav.py's `migrate` is the half that makes the reorder visible on Debi's own
// Mac — it rewrites a saved layout that is byte-for-byte the OLD default, and leaves a
// customised one alone.
// ⚠️ NINE SINCE THE 9+3 RULING (Debi 2026-08-29), NOT ELEVEN — and the strip is still
// the same eleven tabs, because the tenth and eleventh are now the SEED of the
// last-three window below rather than pins. test_nav_model.py asserts this list equals
// nav.py's pinned defaults and that the two together equal nav.strip(default_model()).
let navDefaultTopbar = ["mc", "hermes", "unsloth", "opencode", "odysseus",
                        "voicestudio", "comfyui", "aider", "loffice"]
// THE LAST-THREE WINDOW's default contents, mirroring nav.py's DEFAULT_MRU: the two
// entries that used to be pinned tenth and eleventh, in their old order. A fresh
// machine therefore draws exactly what it drew before — Music (the Studio) and
// Voicebox — with those two now swappable instead of fixed.
let navDefaultMru = ["compose", "voicebox"]
let navWindowMax = 3
func tabsFor(_ ids: [String]) -> [HarnessTab] {
    return ids.compactMap { i in tabRegistry.first(where: { $0.id == i }) }
}
// THE STRIP. A `var` now: applyNav rebuilds it from data/nav.json (order + hidden), and
// every use site below reads it live rather than caching an index.
var tabs: [HarnessTab] = tabsFor(navDefaultTopbar + navDefaultMru)
var tabTitles: [String] { tabs.map { $0.title } }

// WHAT THE SHELL TELLS THE PANEL ABOUT ITSELF (2026-08-21, the regression repair).
//
// The panel→shell channel is a ONE-WAY script message, so the panel could not tell
// "the shell switched the tab" from "the shell has never heard of that tab" — and its
// fallback for the second case was window.open(), which in a WKWebView means the
// DEFAULT BROWSER. Clicking Aider in the sidebar opened Chrome. The cause was one
// stage earlier: a malformed comment made `swiftc` fail, so ship.sh never rebuilt this
// binary while the panel (served from disk) moved on. A panel newer than its shell is
// therefore a NORMAL state that must be DETECTABLE rather than a silent no-op.
//
// So the shell injects one global into its own first-party pages:
//     window.harnessShell = { api: <shellAPI>, tabs: [<every tabRegistry id>] }
// `tabs` is the REGISTRY, not the strip: the question is "does this build know that tab
// at all", and a hidden tab is still reachable (switchTab shows it for the session).
// Bump `shellAPI` when the panel needs to detect a NEW shell capability.
let shellAPI = 2

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

// ── THE DEPENDENCY BANNER (S22) ─────────────────────────────────────────────
// docs/research/2026-08-29-isolation-mode.md §6: every Start already re-derives a
// component's wiring to the runner, so "restart rebinds" has always been true. What
// never existed is the SIGNAL — a Hermes dashboard is perfectly healthy on :9119 while
// every chat inside it fails against a runner that is gone or serving a different
// model, and nothing anywhere says so. This strip is that sentence.
//
// ⚠️ IT IS ADVISORY AND IT NEVER BLOCKS THE TAB — Debi's advisory-gates ruling. Three
// properties enforce that, and a future edit must keep all three:
//   1. it SHORTENS the page rather than covering it (attach() pins the webview's top to
//      this view's bottom), so no pixel of the component's own UI is ever hidden;
//   2. it is dismissable, and a dismissal sticks until the SITUATION changes (the
//      dismissal is keyed on the sentence, not on the tab);
//   3. it offers exactly ONE action, and that action is a request the bridge already
//      serves. It is never modal, never a sheet, and never gates a click.
// It also removes itself with no interaction at all the moment the need is met.
let depsBannerHeight: CGFloat = 30

final class DepsBanner: NSView {
    private let label = NSTextField(labelWithString: "")
    private let action = NSButton(title: "", target: nil, action: nil)
    private let dismiss = PaneCloseButton(title: "✕", target: nil, action: nil)
    // What is currently on screen, so applyDepsBanners can skip an identical repaint
    // (this view sits above a live web page — a needless relayout there is visible).
    var shownKey: String = ""
    var onAction: (() -> Void)?
    var onDismiss: (() -> Void)?

    init() {
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        wantsLayer = true
        // Gold-on-ink, the panel's own attention colour, at a strip's weight: this must
        // read as the app talking, not as an OS alert.
        layer?.backgroundColor = NSColor(red: 0.145, green: 0.125, blue: 0.078, alpha: 1).cgColor
        let rule = NSView()
        rule.translatesAutoresizingMaskIntoConstraints = false
        rule.wantsLayer = true
        rule.layer?.backgroundColor = paneGold.withAlphaComponent(0.55).cgColor
        addSubview(rule)

        label.font = NSFont.systemFont(ofSize: 12)
        label.textColor = paneCream
        label.lineBreakMode = .byTruncatingTail
        label.translatesAutoresizingMaskIntoConstraints = false
        label.setContentCompressionResistancePriority(NSLayoutConstraint.Priority(1), for: .horizontal)
        addSubview(label)

        action.font = NSFont.systemFont(ofSize: 11)
        action.bezelStyle = .texturedRounded
        action.target = self
        action.action = #selector(fire(_:))
        action.translatesAutoresizingMaskIntoConstraints = false
        addSubview(action)

        dismiss.isBordered = false
        dismiss.toolTip = "Dismiss until this changes"
        dismiss.tint(paneFaint)
        dismiss.target = self
        dismiss.action = #selector(close(_:))
        dismiss.translatesAutoresizingMaskIntoConstraints = false
        addSubview(dismiss)

        // ⚠️ NO INTRINSIC HEIGHT HERE, DELIBERATELY (adversarial pass, caught before
        // ship). The first draft carried a REQUIRED 30pt height constraint on this view
        // and let the host drive a second one to 0 at priority 999. Autolayout resolves
        // that by satisfying the required one and relaxing ours — i.e. the banner would
        // have been 30pt tall FOREVER, silently eating 30 points off every tab whether
        // it had anything to say or not. The height is owned by exactly one constraint,
        // and it lives in buildPane where the value is driven.
        NSLayoutConstraint.activate([
            rule.leadingAnchor.constraint(equalTo: leadingAnchor),
            rule.trailingAnchor.constraint(equalTo: trailingAnchor),
            rule.bottomAnchor.constraint(equalTo: bottomAnchor),
            rule.heightAnchor.constraint(equalToConstant: 1),
            label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            label.centerYAnchor.constraint(equalTo: centerYAnchor),
            label.trailingAnchor.constraint(lessThanOrEqualTo: action.leadingAnchor, constant: -10),
            action.trailingAnchor.constraint(equalTo: dismiss.leadingAnchor, constant: -8),
            action.centerYAnchor.constraint(equalTo: centerYAnchor),
            dismiss.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -8),
            dismiss.centerYAnchor.constraint(equalTo: centerYAnchor),
            dismiss.widthAnchor.constraint(equalToConstant: 16),
            dismiss.heightAnchor.constraint(equalToConstant: 16),
        ])
        isHidden = true
    }
    required init?(coder: NSCoder) { return nil }

    func show(key: String, text: String, actionLabel: String) {
        if shownKey == key && !isHidden { return }
        shownKey = key
        label.stringValue = "⚠︎  " + text
        label.toolTip = text                       // the full sentence when it truncates
        action.title = actionLabel
        action.isHidden = actionLabel.isEmpty
        isHidden = false
    }
    func hide() {
        if isHidden && shownKey.isEmpty { return }
        shownKey = ""
        isHidden = true
    }
    @objc private func fire(_ s: Any?) { onAction?() }
    @objc private func close(_ s: Any?) { onDismiss?() }
}

// One unmet need, as the shell needs it. Every string in here is written by the bridge
// (bridge/routers/components.py needs_message) — the shell deliberately composes no
// user-facing sentence of its own, so a wording change never needs this binary rebuilt.
struct DepNeed {
    let comp: String        // the component/tab id the banner belongs to
    let text: String
    let actionLabel: String
    let action: String      // "start" | "restart" | "open"
    let target: String      // a component name, or "mc"
    var key: String { return "\(comp)|\(action)|\(target)|\(text)" }
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
    // ── the tab strip's own visibility (v1.5.26) ──
    // The ONE number for the strip's height, so the layout constraint, the peek monitor's
    // "has the pointer left the strip" test and the restore all read the same value.
    let tabBarHeight: CGFloat = 44
    var tabBar: NSView!
    var tabBarH: NSLayoutConstraint!
    var tabBarHidden = false          // the PERSISTED preference
    var tabBarPeeked = false          // transient: the pointer is at the top edge
    var tabPeekMonitor: Any?
    // ── nav (STUDIO PHASE 2) ──
    // Which entries are on the strip, in order, as data/nav.json last said. The shell
    // cannot read the panel's localStorage, which is exactly why that file exists.
    var navPinned: [String] = navDefaultTopbar
    // ══ THE LAST-THREE WINDOW (Debi's ruling 2026-08-29) ═════════════════════════
    // WHAT IT REPLACES, and why the replacement was the ruling: this used to be
    // `tempShown`, an UNBOUNDED session list of everything you had opened from the ⋯
    // menu or from a sidebar row, appended AFTER the (then twelve) pins. So a strip
    // whose rule said "at most 12" routinely drew fourteen — the creep Debi named.
    //
    // Now it is a bounded, PERSISTED window of `navWindowMax` ids, most-recently-opened
    // first, drawn after the nine pins. Opening a tab that is not on the strip puts it
    // in front and pushes the oldest out into ⋯; opening one that is already on the
    // strip moves nothing (a strip that re-sorts under the pointer is the bug, not the
    // feature). The bridge owns the rule (bridge/nav.py `mru_touch`) and this is its
    // client — `POST /api/nav/mru` — so the panel's sidebar and this menu can never
    // disagree about what the strip is.
    var navWindow: [String] = navDefaultMru
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
    // ══ THE SSE HYBRID (2026-08-28) — WHY THE SHELL KEEPS POLLING, DELIBERATELY ══
    // bridge/core/events.py added a push channel (GET /api/events) and the PANEL now
    // rides it: its status poll relaxes from 6s to 30s while push is live and drops to
    // 4s the instant it dies. The shell was checked for the same treatment and
    // deliberately left alone, for three reasons — recorded here because the obvious
    // future edit is to "finish the migration", and it would be a regression:
    //
    //  1. DISPROPORTIONATE. These two timers make one 2s-timeout loopback GET each and
    //     read a single Int out of it (hermes_config_gen, nav_gen). An SSE client in
    //     Swift means a streaming URLSession delegate, frame parsing, a reconnect
    //     policy and a staleness clock — a few hundred lines of new machinery, with its
    //     own failure modes, to save two integers' worth of traffic.
    //  2. THIS POLL IS NOW LOAD-BEARING FOR THE PANEL. A component that dies on its own
    //     is not a transition the harness causes, so the only place that fact exists is
    //     the debounced verdict computed inside GET /api/status (bridge/core/health.py's
    //     _health_track, which now pushes on a CHANGE). Whoever calls /api/status fans
    //     that out to every open panel — and this 4s timer is the most reliable caller
    //     on the machine. Removing or slowing it would make the panel SLOWER to notice a
    //     crash, which is the opposite of what the hybrid is for.
    //  3. THE ACTION IS DIFFERENT. The shell's reaction is "reload a WKWebView", not
    //     "repaint a card". A reload is disruptive, so a slow deliberate tick with an
    //     occlusion guard is the RIGHT cadence for it, not a latency to be minimised.
    //
    // Pinned by bridge/tests/test_sse_hybrid.js §5, which fails if either number moves
    // without this note moving with it.
    // ── OPENCODE: "New session" → "runner auto session" (ledger S21) ────────────
    //
    // WHAT THIS FIXES, AND WHAT IT DELIBERATELY DOES NOT.
    // docs/research/2026-08-29-opencode-phantom-sessions.md root-caused the tabs Debi
    // kept finding in OpenCode: they are not sessions. Our /opencode landing route
    // deep-links `/:dir/session` with no draftId, and OpenCode 1.18.23's SPA mints and
    // PERSISTS one draft TAB per boot of that route. Zero server sessions were ever
    // created (sqlite: 0 rows, GET /session: []). Debi's ruling (S21): LEAVE the landing
    // behaviour alone — the drafts are harmless and prunable with their own ✕ — but stop
    // them calling themselves "New session", because that is what made them look like
    // work she had started and abandoned. They are OURS: one per app launch.
    //
    // WHY A DOM RELABEL AND NOT A STORE EDIT — proven at the pin, not preferred.
    // A draft tab has NO title in the persisted store. Its entry is exactly
    // {type,server,draftID,directory,worktree} (the parser rejects any other shape), and
    // the strip renders it with `title = t("command.session.new")` — a hardcoded i18n
    // lookup at RENDER time (bundle index-DonkoK44.js, component `U6e`). There is no
    // field in their store that could carry a label, so writing to the store could not
    // work even if we were willing to. Renaming the rendered text is therefore not the
    // least invasive mechanism that works — it is the ONLY one, and it leaves the store
    // byte-untouched, which is what keeps their ✕ cleanup working exactly as before.
    //
    // FOUR FENCES. Any one of them failing means the script does NOTHING AT ALL — never
    // a partial effect, never an error in their console, never a changed UI:
    //   1. VERSION. The pin is read from harness.yaml here and compared, inside the
    //      page, against OpenCode's own GET /global/health. A different build → return.
    //      (No pin readable → the script is not injected at all.)
    //   2. THE STORE. A key matching `opencode.window.*.dat:tabs` must exist and parse
    //      as an array — that is the persisted tab strip this whole slice is about.
    //   3. THE ENTRY. A node is relabelled only when the store says its id is a
    //      `type:"draft"` entry. `data-tab-key` is literally `draft:<draftID>` (their
    //      own `Kn`), so this is the store's own answer, not a guess from the DOM.
    //   4. THE TEXT. Only the exact string "New session" is replaced. A renamed tab, a
    //      localised build, or an upstream wording change is left alone.
    // ZERO VENDORED BYTES: this runs in our webview, in our shell, and writes nothing
    // into anything of theirs. Removing it restores upstream's label on the next launch.
    //
    // ── THE DISCRIMINATOR (Debi, live bug 2026-08-29): AUTO vs USER drafts ──────
    // The first cut relabelled EVERY draft, so clicking + — a deliberate new session —
    // was also branded "runner auto session". That is a LIE-TO-USER of the same family
    // the slice was written to remove, pointed the other way: it renames the user's own
    // work. Only the draft OUR landing route mints may carry the label.
    //
    // The two kinds are byte-identical in the store (same shape, same fresh UUID) and
    // land on the SAME url: `newDraft` (bundle, verified at the pin) pushes the entry
    // and then client-navigates to `/new-session?draftId=<uuid>` — for the boot mint and
    // for the + click alike. So the store cannot answer this and neither can the URL.
    // What separates them is the GESTURE, and the honest definition of the boot window:
    //
    //   an AUTO draft is the ONE draft whose id (a) is not in the snapshot of draft ids
    //   taken at documentStart, BEFORE their SPA has run a line, (b) becomes the
    //   `draftId` of THIS document's own url — i.e. it is the navigation the landing
    //   mint performs — and (c) does so before this document has seen a single
    //   pointerdown / mousedown / keydown. At most one per document, because the
    //   landing route mints exactly one per boot.
    //
    // Every other draft — the + click (a pointerdown precedes it), a draft minted in the
    // OTHER webview (the split ghost changes the shared store but never THIS document's
    // url), anything already in the store before this fix existed — renders upstream's
    // own text, untouched. Conservative by construction: the failure mode of every
    // clause is "no label", never "wrong label".
    //
    // ⚠️ THIS IS WHY THE SCRIPT MOVED TO documentStart. At documentEnd their SPA has
    // already booted and minted, so the snapshot would contain the very draft it exists
    // to identify. The snapshot and the gesture listeners are the only things that run
    // before the version fence resolves, and both are PASSIVE (two reads and three
    // listeners; no write, no DOM change) — so a non-matching build still gets nothing.
    //
    // FIFTH FENCE, AND OUR ONE PIECE OF STATE: the answer is remembered under OUR OWN
    // key `harness.opencode.autoDrafts` (a plain array of ids) so a label survives a
    // reload and a relaunch — and so a + draft, once judged the user's, is NEVER marked
    // later even after a restart. We never read or write ANY `opencode.*` entry: theirs
    // stay byte-untouched, which is what keeps their ✕ cleanup working. The set is
    // pruned to what their store still calls a draft, so a promoted draft (type flips to
    // "session" in place — their `promoteDraft`) or a closed one drops out by itself.
    // Drafts that predate this fix are deliberately NOT adopted: they render whatever
    // upstream renders.
    func opencodePin() -> String? {
        // ⚠️ THE WEBVIEWS ARE BUILT BEFORE `resolvedRoot` IS SETTLED (the provisioning
        // resolve runs later in applicationDidFinishLaunching), so this reads the baked
        // root FIRST and the fat snapshot SECOND rather than trusting one of them. Both
        // carry the same harness.yaml; whichever answers first is the pin.
        var yaml: String? = nil
        for r in [resolvedRoot, harnessRoot,
                  NSString(string: "~/Library/Application Support/Harness").expandingTildeInPath] {
            if let s = try? String(contentsOfFile: "\(r)/harness.yaml", encoding: .utf8) {
                yaml = s; break
            }
        }
        guard let y = yaml else { return nil }
        // `opencode_pin: "1.18.23"` in build:. A regex, not a YAML parser: one value,
        // and an unreadable/renamed key must mean "do not inject", not "guess".
        //
        // ⚠️ THE QUOTES ARE OPTIONAL, AND THAT IS NOT COSMETIC. The repo writes the pin
        // quoted; the SNAPSHOT's copy is produced by ship.sh's additive pyyaml merge,
        // which dumps it UNQUOTED (`opencode_pin: 1.18.23` — verified on the live
        // snapshot 2026-08-29). A quote-only regex therefore reads the pin on this dev
        // Mac (where harnessRoot points at the repo) and finds NOTHING on a fat or
        // portable install, where the snapshot is the only harness.yaml there is — the
        // whole feature would silently not exist there. The value class excludes spaces
        // and `#`, so an unquoted match still cannot swallow a trailing comment.
        guard let m = y.range(of: #"opencode_pin:\s*"?[0-9][0-9A-Za-z.\-]*"?"#,
                              options: .regularExpression) else { return nil }
        let seg = String(y[m])   // starts with the key, which carries no digits
        guard let q = seg.range(of: #"[0-9][0-9A-Za-z.\-]*"#,
                                options: .regularExpression) else { return nil }
        return String(seg[q])
    }

    // ── GOOSE UI: a per-chat ✕ IN THE SIDEBAR (Debi, asked twice) ───────────────
    //
    // WHAT SHE HIT. The sidebar's CHATS list — the one thing on screen while you are
    // chatting — has NO per-item delete upstream. Read off the pinned v1.48.0 bundle:
    // the row component renders an inline rename field and three status dots and nothing
    // else, and it merely LISTENS for `session-deleted`. Deletion exists only on the
    // Session History page, on a card, behind icons that are `opacity-0` until hovered.
    // So a user looking at six rows all called "New Chat" has no way to remove one from
    // where they are looking. That is a missing affordance, not a missing capability —
    // and the fix belongs where she is looking.
    //
    // WHY THE DELETE GOES THROUGH THE BRIDGE AND NOT THROUGH THEIR OWN FUNCTION.
    // Measured in the bundle: the trash's delete is `v(id)`, a MODULE-SCOPE binding in
    // their Vite chunk — no global, no window object, no React context reaches it, and
    // their confirm dialog is mounted only on the Sessions page. An injected script
    // therefore CANNOT call their function or raise their dialog. What it can do is ask
    // the bridge to send goose's OWN protocol method (`session/delete`, ACP) to the
    // goosed WE supervise — the same call their trash makes, to the same server, on the
    // same store. See bridge/gooseui.py's ACP section for the measured protocol (A1-A4)
    // and bridge/routers/gooseui.py for the route.
    //
    // ⚠️ NEVER A SILENT DELETE. Since their confirm cannot be raised, the ✕ arms an
    // equivalent TWO-STEP in the row — ✕ → `delete? yes / no`, Esc cancels — which is
    // the same armed grammar the Goose CLI tab's session strip already uses. One click
    // never deletes anything.
    //
    // THREE FENCES. Any one failing ⇒ NOTHING is injected or painted, and the tab is
    // upstream's UI exactly as before:
    //   1. THE PIN. `goose_pin` is read from harness.yaml here (repo or snapshot,
    //      quoted or not — the v1.5.59 lesson) and compared, inside the page, against
    //      the version the bridge reports. No pin readable ⇒ the script is not injected.
    //   2. THE BUNDLE. /api/gooseui/status must report `bundle_sha256` EQUAL to
    //      `pin_bundle_sha256` and non-empty: the DOM shapes below were measured against
    //      exactly that bundle, so a different one gets nothing rather than a guess.
    //   3. THE ROW. A ✕ is added only to a row whose OWN React props carry
    //      `session.id` matching goose's id shape (a bounded 40-hop fiber walk from the
    //      row node). Their DOM carries no session id anywhere — no data attribute, no
    //      href — and matching on the rendered TEXT would be indefensible when every row
    //      says "New Chat". A row that will not answer with an id gets no ✕.
    // ZERO VENDORED BYTES: nothing in data/goose/ui is touched, and removing this
    // function restores upstream's sidebar on the next launch.
    func goosePin() -> String? {
        var yaml: String? = nil
        for r in [resolvedRoot, harnessRoot,
                  NSString(string: "~/Library/Application Support/Harness").expandingTildeInPath] {
            if let s = try? String(contentsOfFile: "\(r)/harness.yaml", encoding: .utf8) {
                yaml = s; break
            }
        }
        guard let y = yaml else { return nil }
        // `goose_pin: "v1.48.0"` in build:. Quotes optional for the same reason as
        // opencodePin's: ship.sh's pyyaml merge writes the snapshot's copy unquoted.
        guard let m = y.range(of: #"goose_pin:\s*"?v?[0-9][0-9A-Za-z.\-]*"?"#,
                              options: .regularExpression) else { return nil }
        let seg = String(y[m])
        guard let q = seg.range(of: #"[0-9][0-9A-Za-z.\-]*"#,
                                options: .regularExpression) else { return nil }
        return String(seg[q])          // "1.48.0" — the leading v never enters the match
    }

    func gooseSidebarDeleteScript() -> WKUserScript? {
        guard let pin = goosePin() else {
            NSLog("%@", "[gooseui] no readable goose_pin — sidebar delete NOT injected" as NSString)
            return nil
        }
        let src = """
        (function () {
          var PIN = "\(pin)", MARK = "data-harness-gdel";
          var ID_RE = /^\\d{8}_\\d+$/, armedRow = null;

          // FENCE 3: the row's OWN props. Bounded walk; no id ⇒ no ✕ on that row.
          function fiberSession(node) {
            var f = null, k;
            for (k in node) { if (k.indexOf("__reactFiber$") === 0) { f = node[k]; break; } }
            for (var i = 0; i < 40 && f; i++) {
              var p = f.memoizedProps;
              if (p && p.session && typeof p.session.id === "string" && ID_RE.test(p.session.id))
                return { id: p.session.id, name: String(p.session.name || "") };
              f = f.return;
            }
            return null;
          }
          // The CHATS section, found by its own heading. Scoping to it is what keeps the
          // ✕ off every other pill-shaped row in their UI.
          function chatsScope() {
            var els = document.querySelectorAll("span,div,h2,h3,p");
            for (var i = 0; i < els.length; i++) {
              var e = els[i];
              if (e.children.length === 0 &&
                  String(e.textContent || "").trim().toLowerCase() === "chats")
                return e.parentElement && e.parentElement.parentElement;
            }
            return null;
          }
          function style() {
            if (document.getElementById("harness-gdel-style")) return;
            var s = document.createElement("style");
            s.id = "harness-gdel-style";
            s.textContent =
              ".hgdel{margin-left:auto;flex:none;display:flex;align-items:center;gap:4px;" +
                "opacity:0;transition:opacity .12s}" +
              "[" + MARK + "]:hover .hgdel,.hgdel:focus-within,.hgdel.armed{opacity:1}" +
              ".hgdel button{background:none;border:0;padding:0 3px;cursor:pointer;" +
                "font:inherit;font-size:11px;line-height:1;color:inherit;opacity:.75}" +
              ".hgdel button:hover{opacity:1}" +
              ".hgdel .x{font-size:13px}" +
              ".hgdel .yes{color:#e5484d}" +
              ".hgdel .ask{display:none;font-size:11px;opacity:.9;white-space:nowrap}" +
              ".hgdel.armed .ask{display:inline}" +
              ".hgdel.armed .x{display:none}" +
              ".hgdel-note{margin:2px 12px 6px;font-size:11px;line-height:1.35;" +
                "color:#e5484d;cursor:help}";
            (document.head || document.documentElement).appendChild(s);
          }
          function disarm() {
            if (!armedRow) return;
            var w = armedRow.querySelector(".hgdel");
            if (w) w.classList.remove("armed");
            armedRow = null;
          }
          // The refusal is a SENTENCE, next to the row it is about. The status code goes
          // on the hover and in the console — never as the message (the log-vomit rule).
          function note(row, sentence, raw) {
            var old = row.parentNode && row.parentNode.querySelector(".hgdel-note");
            if (old) old.remove();
            var d = document.createElement("div");
            d.className = "hgdel-note";
            d.textContent = sentence;
            if (raw) d.title = raw;
            if (row.parentNode) row.parentNode.insertBefore(d, row.nextSibling);
            setTimeout(function () { if (d.parentNode) d.remove(); }, 9000);
          }
          // Is THIS chat the one on screen? Their router puts it in the hash as
          // `#/pair?resumeSessionId=<id>` (measured).
          function showing(id) {
            try { return String(location.hash || "").indexOf("resumeSessionId=" + id) >= 0; }
            catch (e) { return false; }
          }
          // THEIR OWN "New Chat" nav item — the one in the nav panel, not the titlebar
          // chip of the same name (the `w-full` class is what tells them apart).
          function newChat() {
            try {
              var scope = chatsScope();
              var nav = scope && scope.parentElement;
              if (!nav) return;
              var all = nav.querySelectorAll("button");
              for (var i = 0; i < all.length; i++) {
                var b = all[i];
                if (String(b.textContent || "").trim() !== "New Chat") continue;
                if (String(b.className).indexOf("w-full") < 0) continue;
                if (scope.contains(b)) continue;
                b.click();
                return;
              }
            } catch (e) {}
          }
          function remove(row, id) {
            fetch("/api/gooseui/session/delete", {
              method: "POST", cache: "no-store",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: id })
            }).then(function (r) {
              return r.json().catch(function () { return null; })
                .then(function (j) { return { ok: r.ok, status: r.status, j: j }; });
            }).then(function (res) {
              if (res.ok && res.j && res.j.ok) {
                // THEIR OWN refresh path: the sidebar, the Sessions page and the active
                // -session store all listen for this exact event (bundle: `session-deleted`).
                try {
                  window.dispatchEvent(new CustomEvent("session-deleted",
                                                       { detail: { sessionId: id } }));
                } catch (e) {}
                // Belt and braces: if their listener did not take the row away, take
                // ours away — a row for a chat that no longer exists is a lie.
                setTimeout(function () {
                  if (row.parentNode && row.getAttribute(MARK) === id) row.remove();
                }, 1500);
                // ⚠️ DELETING THE CHAT YOU ARE LOOKING AT. Walked live: the row goes and
                // the store agrees, but the MAIN PANE keeps rendering the transcript of
                // a chat that no longer exists — a screen full of something that is
                // gone. Upstream's own Sessions-page handler clears its active-session
                // state alongside the delete; we cannot call that, so we do what a user
                // would do next and press THEIR OWN "New Chat". Not found ⇒ nothing
                // happens, which is exactly today's behaviour.
                if (showing(id)) newChat();
                return;
              }
              var msg = (res.j && res.j.message) || "goose refused that";
              try { console.warn("[harness-gdel] " + id + ": HTTP " + res.status + " — " + msg); }
              catch (e) {}
              note(row, "Nothing was deleted — " + msg,
                   "HTTP " + res.status + " · /api/gooseui/session/delete");
            }).catch(function (e) {
              note(row, "Nothing was deleted — the bridge is not answering.", String(e));
            });
          }
          function decorate(row, sess) {
            if (row.getAttribute(MARK)) return;
            row.setAttribute(MARK, sess.id);
            var wrap = document.createElement("span");
            wrap.className = "hgdel";
            wrap.innerHTML =
              '<button class="x" type="button" title="Delete this chat">✕</button>' +
              '<span class="ask"><b>delete?</b> ' +
                '<button class="yes" type="button">yes</button> ' +
                '<button class="no" type="button">no</button></span>';
            // ⚠️ BUBBLE PHASE, NOT CAPTURE. The first draft stopped propagation in the
            // CAPTURE phase on this wrapper, which stops the event BEFORE it reaches the
            // buttons inside — the ✕ then did nothing at all (caught on the live walk).
            // Bubble is what "do not also open the chat" actually means.
            wrap.addEventListener("click", function (ev) { ev.stopPropagation(); }, false);
            wrap.querySelector(".x").onclick = function (ev) {
              ev.stopPropagation(); ev.preventDefault();
              disarm(); armedRow = row; wrap.classList.add("armed");
            };
            wrap.querySelector(".no").onclick = function (ev) {
              ev.stopPropagation(); ev.preventDefault(); disarm();
            };
            wrap.querySelector(".yes").onclick = function (ev) {
              ev.stopPropagation(); ev.preventDefault();
              disarm(); remove(row, sess.id);
            };
            row.appendChild(wrap);
          }
          function tick() {
            var scope = chatsScope();
            if (!scope) return;
            var rows = scope.querySelectorAll("div.rounded-full.cursor-pointer");
            for (var i = 0; i < rows.length; i++) {
              var r = rows[i];
              if (r.getAttribute(MARK)) continue;
              var s = fiberSession(r);
              if (!s) continue;
              decorate(r, s);
            }
          }
          function arm() {
            style(); tick();
            try {
              new MutationObserver(function () { tick(); })
                .observe(document.body, { childList: true, subtree: true });
            } catch (e) {}
            document.addEventListener("keydown", function (ev) {
              if (ev.key === "Escape") disarm();
            }, true);
          }
          // FENCES 1 + 2, before anything is painted.
          fetch("/api/gooseui/status", { cache: "no-store" })
            .then(function (r) { return r.json(); })
            .then(function (j) {
              if (!j || !j.ok) return;
              if (!j.bundle_sha256 || j.bundle_sha256 !== j.pin_bundle_sha256) return;
              if (String(j.app_version || "") !== PIN) return;
              if (document.body) arm();
              else document.addEventListener("DOMContentLoaded", arm);
            }).catch(function () {});
        })();
        """
        return WKUserScript(source: src, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
    }

    func openCodeDraftScript() -> WKUserScript? {
        guard let pin = opencodePin() else {
            NSLog("%@", "[opencode] no readable pin — draft relabel NOT injected" as NSString)
            return nil
        }
        let src = """
        (function(){
          var PIN = "\(pin)", LABEL = "runner auto session", FROM = "New session";
          // OURS. Never an `opencode.*` key: their entries are read-only to us.
          var MINE = "harness.opencode.autoDrafts", CAP = 64;
          function tabsKey(){
            try {
              for (var i=0;i<localStorage.length;i++){
                var k = localStorage.key(i);
                if (k && /^opencode\\.window\\..*\\.dat:tabs$/.test(k)) return k;
              }
            } catch(e){}
            return null;
          }
          function draftIds(){
            var k = tabsKey(); if (!k) return null;
            try {
              var v = JSON.parse(localStorage.getItem(k));
              if (!Array.isArray(v)) return null;
              var out = {};
              for (var i=0;i<v.length;i++){
                var e = v[i];
                if (e && e.type === "draft" && typeof e.draftID === "string") out[e.draftID] = 1;
              }
              return out;
            } catch(e){ return null; }
          }
          function readMine(){
            var out = {};
            try {
              var v = JSON.parse(localStorage.getItem(MINE));
              if (Array.isArray(v)) for (var i=0;i<v.length;i++)
                if (typeof v[i] === "string") out[v[i]] = 1;
            } catch(e){}
            return out;
          }
          function writeMine(map){
            var a = [], id;
            for (id in map) a.push(id);
            try { localStorage.setItem(MINE, JSON.stringify(a.slice(0, CAP))); } catch(e){}
          }
          function urlDraft(){
            try {
              var m = String(location.search).match(/[?&]draftId=([^&#]+)/);
              return m ? decodeURIComponent(m[1]) : null;
            } catch(e){ return null; }
          }

          // ── documentStart, and PASSIVE: two reads and three listeners. Nothing here
          // writes or paints; the version fence still owns every effect below.
          var before = draftIds() || {};   // drafts that existed before their SPA ran
          var auto = readMine();           // ids WE have already judged auto (persisted)
          var gestured = false, minted = false;
          function gesture(){ gestured = true; }
          try {
            document.addEventListener("pointerdown", gesture, true);
            document.addEventListener("mousedown", gesture, true);
            document.addEventListener("keydown", gesture, true);
          } catch(e){}

          // Merge with what is on disk (the split ghost is a second document writing the
          // same key) and prune to what their store still calls a draft — a promoted or
          // closed draft leaves our set by itself. Writes only when the answer changed.
          function sync(ids){
            var disk = readMine(), merged = {}, id, same = true;
            for (id in disk) if (ids[id]) merged[id] = 1;
            for (id in auto) if (ids[id]) merged[id] = 1;
            for (id in merged) if (!disk[id]) same = false;
            for (id in disk) if (!merged[id]) same = false;
            auto = merged;
            if (!same) writeMine(merged);
          }
          // THE DISCRIMINATOR. See the note above openCodeDraftScript().
          function consider(ids){
            if (minted || gestured) return;
            var id = urlDraft();
            if (!id || before[id] || auto[id] || !ids[id]) return;
            auto[id] = 1; minted = true;
          }
          function tick(){
            var ids = draftIds(); if (!ids) return;
            consider(ids);
            sync(ids);
            var slots = document.querySelectorAll('[data-tab-key^="draft:"]');
            for (var i=0;i<slots.length;i++){
              var id = slots[i].getAttribute("data-tab-key").slice(6);
              if (!auto[id] || !ids[id]) continue;
              var t = slots[i].querySelector("[data-titlebar-tab-title]");
              if (!t) continue;
              if (t.textContent === FROM) t.textContent = LABEL;
            }
          }
          function arm(){
            tick();
            try {
              new MutationObserver(function(){ tick(); })
                .observe(document.body, {childList:true, subtree:true, characterData:true});
            } catch(e){}
            // The mint's navigation is a client-side route change: it need not touch the
            // DOM subtree the observer watches on the tick that matters. A bounded 30s
            // poll covers the boot window; after that the observer alone keeps painting.
            var n = 0, iv = setInterval(function(){
              tick(); if (++n > 60) clearInterval(iv);
            }, 500);
          }
          try {
            fetch("/global/health").then(function(r){ return r.json(); }).then(function(j){
              if (!j || j.version !== PIN) return;
              if (document.body) arm();
              else document.addEventListener("DOMContentLoaded", arm);
            }).catch(function(){});
          } catch(e){}
        })();
        """
        return WKUserScript(source: src, injectionTime: .atDocumentStart, forMainFrameOnly: true)
    }

    // ── the dependency signal (S22) ──
    // The two strips (one per pane) and the height constraint each one is driven by.
    var bannerL: DepsBanner!
    var bannerR: DepsBanner!
    var bannerHeights: [ObjectIdentifier: NSLayoutConstraint] = [:]
    // The latest answer from GET /api/deps, keyed by component/tab id. EMPTY IS THE
    // HEALTHY STATE and also the state we fail into: a bridge that is down, an older
    // bridge with no such route, a timeout or an unparseable body all leave this empty,
    // which draws no banner. The signal can therefore never be the thing that breaks a
    // tab — the same fail-safe shape as syncHermesGen and syncNav.
    var depNeeds: [String: DepNeed] = [:]
    // Sentences the user has waved away. Keyed by the SENTENCE (DepNeed.key), not by the
    // tab: dismissing "Hermes is wired to model A" must not also silence "…model B" or
    // "the runner is down". A dismissal therefore expires by itself the moment the
    // situation actually changes, and nothing has to remember to clear it.
    var depDismissed: Set<String> = []
    var depsTimer: Timer?
    // ⚠️ BUILDER NUMBER, AND IT IS DELIBERATELY SLOWER THAN THE PANEL'S 6s. /api/deps
    // re-runs /api/status's derivation, so this is a SECOND poller of the same loopback
    // probes rather than a free ride on the first — and the facts it watches move on a
    // human timescale (a model swap, a component dying, a restart finishing). 10s reads
    // as immediate for all three while keeping the added probe traffic below the panel's
    // own. The timer only exists while a tab that can carry a banner is on screen, and
    // it asks once IMMEDIATELY on arming so a tab switch never waits out a tick.
    let depsPoll: TimeInterval = 10
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
        window.title = "MOT Deck"
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
        // A property now (v1.5.26): applyTabBar has to reach it to hide and show it.
        tabBar = NSView()
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
                  !navWindow.contains(id) else { continue }
            // Front of the window: it is the most recent thing this user was looking at.
            navWindow.insert(id, at: 0)
            if navWindow.count > navWindowMax { navWindow.removeLast() }
        }
        tabs = tabsFor(stripIds())

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
        //
        // OUR OWN PAGES — and only ours — get the "harness" script-message handler, so
        // that a sidebar row (or LOffice's File menu) can ask the shell to switch tabs.
        // That is the panel here, plus LOffice, Aider, Goose CLI, Goose UI, Generate and
        // Compose in the loop below;
        // registering it on any other webview would let a THIRD-PARTY component page
        // drive our tab strip, so those configurations are deliberately bare.
        //
        // The self-description above, as a user script. Injected at documentStart so it
        // is there before any of the panel's own code runs. Every id is a literal from
        // `tabRegistry`, so there is nothing here to escape.
        let shellIds = tabRegistry.map { "\"\($0.id)\"" }.joined(separator: ",")
        let shellScript = WKUserScript(
            source: "window.harnessShell={api:\(shellAPI),tabs:[\(shellIds)]};",
            injectionTime: .atDocumentStart, forMainFrameOnly: true)

        let panelCfg = WKWebViewConfiguration()
        panelCfg.userContentController.add(self, name: "harness")
        panelCfg.userContentController.addUserScript(shellScript)
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
            // LOffice + Aider + Goose CLI + Generate + Compose + Goose UI are OUR OWN
            // pages served by the bridge (first-party, same origin as the panel) — they
            // get the "harness" handler too, so their own menus can ask the shell to
            // switch tabs. Third-party pages never do. The list is EXPLICIT rather than
            // "anything on :8700": a page earns the handler by being one we wrote, and
            // that has to be stated once per page.
            //
            // ⚠️ `gooseui` EARNS IT ON A NARROWER ARGUMENT THAN THE OTHERS, AND THE
            // ARGUMENT IS THE ORIGIN, NOT THE AUTHORSHIP. The bundle inside that tab is
            // goose Desktop's own renderer, vendored unmodified — we did not write it.
            // What we own is the ORIGIN it is served from (:8700, ours, digest-pinned on
            // disk and re-verified by the contract suite) and the ONE script injected
            // into it (bridge/gooseui.py's preload). A page reaching `window.webkit`
            // here is a page we provisioned byte-for-byte; a third-party page fetched
            // over the network still never gets this handler.
            // OPENCODE gets NO handler and NO shellScript — it is a third-party page.
            // What it gets is ONE cosmetic user script that renames its auto-minted
            // draft tabs, and nothing else. See openCodeDraftScript().
            else if t.id == "opencode" {
                let c = WKWebViewConfiguration()
                if let s = openCodeDraftScript() { c.userContentController.addUserScript(s) }
                wvById[t.id] = WKWebView(frame: .zero, configuration: c)
            }
            else if t.id == "loffice" || t.id == "aider" || t.id == "goose"
                    || t.id == "comfy" || t.id == "compose" || t.id == "gooseui" {
                let c = WKWebViewConfiguration()
                c.userContentController.add(self, name: "harness")
                c.userContentController.addUserScript(shellScript)
                // The sidebar's per-chat ✕ — see gooseSidebarDeleteScript(). Fenced;
                // any fence unreadable ⇒ nothing injected and the tab is upstream's.
                if t.id == "gooseui", let s = gooseSidebarDeleteScript() {
                    c.userContentController.addUserScript(s)
                }
                wvById[t.id] = WKWebView(frame: .zero, configuration: c)
            }
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
        bannerL = DepsBanner()
        buildPane(leftPane, strip: focusStripL, host: leftHost, close: closeL,
                  tip: "Close this pane", banner: bannerL)
        bannerL.onAction = { [weak self] in self?.depAction(pane: 0) }
        bannerL.onDismiss = { [weak self] in self?.depDismiss(pane: 0) }
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
        bannerR = DepsBanner()
        buildPane(rightPane, strip: focusStripR, host: rightHost, close: closeR,
                  tip: "Close this pane", banner: bannerR)
        bannerR.onAction = { [weak self] in self?.depAction(pane: 1) }
        bannerR.onDismiss = { [weak self] in self?.depDismiss(pane: 1) }

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

        // v1.5.26: the height is a held constraint — applyTabBar drives it to 0 and back.
        tabBarH = tabBar.heightAnchor.constraint(equalToConstant: tabBarHeight)
        NSLayoutConstraint.activate([
            leftMin, rightMin,
            tabBar.topAnchor.constraint(equalTo: container.topAnchor),
            tabBar.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            tabBar.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            tabBarH,
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
        // v1.5.26 — restore the strip's own visibility BEFORE the panes are laid out, so
        // a hidden strip never flashes on launch. The monitor is armed from the same
        // fact, so the peek works on the first pointer move after a cold start.
        tabBarHidden = ud.bool(forKey: "harness.tabbar.hidden")
        applyTabBar()
        setTabBarPeekMonitor(tabBarHidden)
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
        a.messageText = "Set up MOT Deck"
        a.informativeText = "MOT Deck will install its local stack into:\n\(homeHarness())\n\nRequirements: Xcode Command Line Tools, Homebrew, and an internet connection. This can take several minutes."
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
        a.messageText = "Set up MOT Deck"
        a.informativeText = "MOT Deck will install its local AI stack into:\n\(appSupportHarness())\n\nNo internet is needed for setup — everything is bundled. This can take a few minutes."
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
    func buildPane(_ pane: NSView, strip: NSView, host: NSView, close: PaneCloseButton, tip: String,
                   banner: DepsBanner) {
        strip.translatesAutoresizingMaskIntoConstraints = false
        strip.wantsLayer = true
        strip.layer?.backgroundColor = NSColor.clear.cgColor
        pane.addSubview(strip)

        host.translatesAutoresizingMaskIntoConstraints = false
        pane.addSubview(host)

        // The dependency strip lives INSIDE the host, at its top, and everything
        // attach() puts in this host starts BELOW it (see attach). A hidden NSView with
        // a height constraint still occupies its space, so the height is driven to 0
        // when there is nothing to say — that is what makes an absent banner cost
        // literally zero pixels rather than a 30pt gap.
        host.addSubview(banner)
        let bh = banner.heightAnchor.constraint(equalToConstant: 0)
        bh.priority = NSLayoutConstraint.Priority(999)   // beats the class's own 30pt
        bannerHeights[ObjectIdentifier(banner)] = bh
        NSLayoutConstraint.activate([
            banner.topAnchor.constraint(equalTo: host.topAnchor),
            banner.leadingAnchor.constraint(equalTo: host.leadingAnchor),
            banner.trailingAnchor.constraint(equalTo: host.trailingAnchor),
            bh,
        ])

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
            // …BELOW the dependency strip, not on top of it: the pane ✕ and the
            // banner's own ✕ must never be able to stack on the same 16 points.
            close.topAnchor.constraint(equalTo: banner.bottomAnchor, constant: 8),
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

    // ── THE DEPENDENCY SIGNAL: poll, paint, act (S22) ───────────────────────────
    //
    // The whole client is these four functions, and every one of them fails toward
    // TODAY'S BEHAVIOUR: no answer, a stale answer, an old bridge or a malformed body
    // all mean "no banner". Nothing here can prevent a tab from loading, reloading or
    // being used, which is the point — the signal is advisory, always.

    // Which tabs can carry one. It is derived, not listed: a banner belongs to a tab
    // whose id is a COMPONENT the bridge answers for, so adding a component to
    // harness.yaml (and NEEDS_SOFT) gives its tab a banner with no edit here — the
    // standing "nothing hardcodes the tab list" rule. `mc` is excluded by construction:
    // it is where the user goes to FIX these, so it must never carry one.
    func bannerCapable(_ idx: Int) -> Bool {
        guard idx >= 0 && idx < tabs.count else { return false }
        return tabs[idx].id != panelId
    }

    // Arm the poll iff a tab that could carry a banner is on screen; retire it otherwise.
    // Called from applyPanes for updateHermesGenTimer's reason: that is the ONE place
    // that knows what is visible, so there is no second rule to keep in step.
    func updateDepsTimer() {
        let live = bannerCapable(currentTab) || (splitOn && bannerCapable(rightTab))
        if live {
            if depsTimer != nil { return }
            fetchDeps()                       // ask NOW, not in six seconds
            depsTimer = Timer.scheduledTimer(withTimeInterval: depsPoll,
                                             repeats: true) { [weak self] _ in
                guard let s = self else { return }
                if !s.bannerCapable(s.currentTab)
                    && !(s.splitOn && s.bannerCapable(s.rightTab)) {
                    s.updateDepsTimer(); return          // belt and braces
                }
                if !NSApp.isActive { return }            // nothing to learn in the background
                s.fetchDeps()
            }
            slog("deps poll -> on (every \(Int(depsPoll))s)")
        } else if let t = depsTimer {
            t.invalidate()
            depsTimer = nil
            slog("deps poll -> off")
        }
    }

    func fetchDeps() {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/deps"))
        req.timeoutInterval = 2.0
        req.cachePolicy = .reloadIgnoringLocalCacheData
        URLSession.shared.dataTask(with: req) { data, resp, err in
            guard err == nil,
                  (resp as? HTTPURLResponse)?.statusCode == 200,
                  let d = data,
                  let raw = try? JSONSerialization.jsonObject(with: d),
                  let obj = raw as? [String: Any],
                  let comps = obj["components"] as? [String: Any] else { return }
            var out: [String: DepNeed] = [:]
            for (name, v) in comps {
                guard let row = v as? [String: Any],
                      let needs = row["needs"] as? [[String: Any]],
                      // ONE banner per tab, and it is the FIRST need the bridge listed:
                      // the bridge orders them by depends_on, so the first is the one
                      // furthest down the chain — fixing it is what unblocks the rest.
                      let n = needs.first,
                      let text = n["text"] as? String, !text.isEmpty else { continue }
                out[name] = DepNeed(comp: name, text: text,
                                    actionLabel: (n["action_label"] as? String) ?? "",
                                    action: (n["action"] as? String) ?? "open",
                                    target: (n["target"] as? String) ?? "mc")
            }
            DispatchQueue.main.async {
                self.depNeeds = out
                self.applyDepsBanners()
            }
        }.resume()
    }

    // The need currently belonging to a pane, or nil. A dismissed sentence is nil too —
    // which is why dismissal is keyed on the sentence: the moment the bridge derives a
    // DIFFERENT one, this returns it again.
    func depNeed(pane: Int) -> DepNeed? {
        let idx = pane == 1 ? rightTab : currentTab
        guard bannerCapable(idx), idx >= 0 && idx < tabs.count else { return nil }
        guard let n = depNeeds[tabs[idx].id], !depDismissed.contains(n.key) else { return nil }
        return n
    }

    // Paint both strips from `depNeeds`. Idempotent — an unchanged sentence repaints
    // nothing at all, because this view sits directly above a live web page.
    func applyDepsBanners() {
        for (pane, banner) in [(0, bannerL), (1, bannerR)] {
            guard let b = banner else { continue }
            // The right strip only exists while the split does.
            let n = (pane == 1 && !splitOn) ? nil : depNeed(pane: pane)
            if let need = n {
                b.show(key: need.key, text: need.text, actionLabel: need.actionLabel)
            } else {
                b.hide()
            }
            if let h = bannerHeights[ObjectIdentifier(b)] {
                let want: CGFloat = (n == nil) ? 0 : depsBannerHeight
                if h.constant != want { h.constant = want }
            }
        }
    }

    // The ONE action. `open` never leaves the app and never asks the bridge for
    // anything; `start` and `restart` are the same POSTs the panel's own component card
    // makes. Either way the banner is left alone: it disappears when the next poll finds
    // the need MET, which is the only honest moment to remove it — a banner that hides
    // itself on click would be claiming a success it cannot know about yet.
    func dependencyPanelView(_ target: String) -> String? {
        // `target` arrives over HTTP. Never interpolate an arbitrary bridge value into
        // JavaScript: this allow-list is the existing panel view vocabulary, not a
        // second navigation model. `mc` means the panel's default view and needs no
        // script at all.
        switch target {
        case "chat", "models", "music", "caps", "help", "api":
            return target
        default:
            return nil
        }
    }

    func depAction(pane: Int) {
        guard let need = depNeed(pane: pane) else { return }
        if need.action == "open" {
            guard let idx = tabs.firstIndex(where: { $0.id == panelId }) else { return }
            // The button belongs to a pane, so that pane is the destination even if a
            // stale focus event says otherwise. routeTab's existing swap rule keeps the
            // one-primary-webview invariant when MOT Deck is open in the other pane.
            let destination = (splitOn && pane == 1) ? 1 : 0
            routeTab(idx, toPane: destination)
            if let view = dependencyPanelView(need.target) {
                // `view` is allow-listed above, so the interpolated script is not
                // attacker-controlled. The panel is loaded before banners can poll.
                webViewFor(idx).evaluateJavaScript(
                    "if (typeof showView === 'function') { showView('\(view)'); }",
                    completionHandler: nil)
            }
            syncStrip()
            slog("deps -> open MOT Deck\(dependencyPanelView(need.target).map { " / \($0)" } ?? "")")
            return
        }
        let verb = need.action == "restart" ? "restart" : "start"
        var req = URLRequest(url: bridgeURL
            .appendingPathComponent("api/components")
            .appendingPathComponent(need.target)
            .appendingPathComponent(verb))
        req.httpMethod = "POST"
        req.timeoutInterval = 10.0
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            NSLog("%@", "[deps] \(verb) \(need.target) -> \(code)" as NSString)
            // Ask again promptly rather than waiting out the tick: a start closure takes
            // a while, but the FIRST thing it does is make the component unhealthy, and
            // the user should see the sentence change rather than sit unchanged.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.fetchDeps() }
        }.resume()
    }

    func depDismiss(pane: Int) {
        guard let need = depNeed(pane: pane) else { return }
        depDismissed.insert(need.key)
        slog("deps dismissed: \(need.comp)")
        applyDepsBanners()
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
    // `tabs` is rebuilt from `navPinned` + `navWindow`; every webview is keyed by ID, so
    // a rebuild reparents nothing and reloads nothing. The panes are remembered by ID
    // across the rebuild too, so reordering the strip does not move what you are
    // looking at.
    func tabId(_ idx: Int) -> String {
        return (idx >= 0 && idx < tabs.count) ? tabs[idx].id : panelId
    }
    func urlForId(_ id: String) -> URL {
        return tabRegistry.first(where: { $0.id == id })?.url ?? bridgeURL
    }
    // THE STRIP, derived: the stable pins, then the last-three window. ONE derivation,
    // mirroring bridge/nav.py's `strip` — and the only thing that may ever build `tabs`.
    func stripIds() -> [String] {
        var pins = navPinned.filter { i in tabRegistry.contains(where: { $0.id == i }) }
        // Mission Control is FIRST and always present: it is the bridge-wait surface,
        // the file-drop target and `panelTab = 0`. The nav model already guarantees it;
        // this is the shell refusing to be broken by a file that does not.
        pins.removeAll { $0 == panelId }
        pins.insert(panelId, at: 0)
        var ids = pins
        for id in navWindow where !ids.contains(id)
            && tabRegistry.contains(where: { $0.id == id }) {
            if ids.count - pins.count >= navWindowMax { break }
            ids.append(id)
        }
        return ids
    }
    // Put `id` in the window's first slot, dropping the oldest, and tell the bridge so
    // it survives a relaunch. Returns false when nothing moved (already on the strip),
    // which is also when NOTHING is written — a click on a tab that is already there
    // must not churn nav.json or move the generation the panel watches.
    @discardableResult
    func touchWindow(_ id: String, persist: Bool = true) -> Bool {
        guard tabRegistry.contains(where: { $0.id == id }) else { return false }
        if stripIds().contains(id) { return false }
        navWindow.removeAll { $0 == id }
        navWindow.insert(id, at: 0)
        if navWindow.count > navWindowMax { navWindow.removeLast(navWindow.count - navWindowMax) }
        if persist { postWindow(id) }
        return true
    }
    // FIRE AND FORGET, exactly like the nav poll's failure rule: a bridge that is down
    // costs the PERSISTENCE of one swap, never the swap itself. The strip has already
    // moved by the time this runs.
    func postWindow(_ id: String) {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/nav/mru"))
        req.httpMethod = "POST"
        req.timeoutInterval = 2.0
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["id": id])
        URLSession.shared.dataTask(with: req) { data, _, _ in
            // Record the generation we just caused so the 5s poll does not read it as
            // somebody else's change and re-fetch a layout we already have.
            guard let d = data,
                  let obj = (try? JSONSerialization.jsonObject(with: d)) as? [String: Any],
                  let gen = obj["gen"] as? Int else { return }
            DispatchQueue.main.async { self.navGen = gen }
        }.resume()
    }
    func rebuildTabs() {
        let keepLeft = tabId(currentTab)
        let keepRight = tabId(rightTab)
        // ⚠️ deliberate: un-pinning the tab you are LOOKING AT does not yank the page out
        // from under you — it takes a window slot, which is where it would have gone if
        // you had opened it from ⋯ anyway. Only the panes that are actually on screen
        // count (rightTab means nothing while the split is off).
        for id in (splitOn ? [keepLeft, keepRight] : [keepLeft]) { touchWindow(id) }
        let ids = stripIds()
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

    // The ⋯ menu is "the registry minus the strip", which since the 9+3 ruling means
    // minus the pins AND minus the window — an entry that fell out of the window comes
    // back here, which is the other half of the swap being honest.
    func hiddenTabs() -> [HarnessTab] {
        return tabRegistry.filter { r in !tabs.contains(where: { $0.id == r.id }) }
    }
    // ⚠️ v1.5.26 — THE ⋯ BUTTON IS NOW ALWAYS PRESENT. It used to vanish whenever no tab
    // was hidden, which was right while it did exactly one thing. It now also carries
    // "Hide tab bar", and a menu that only appears when an unrelated condition holds is
    // not a discoverable home for anything. The menu still says "No hidden tabs" when
    // there are none, so the old meaning is not lost — it is stated instead of implied
    // by absence.
    func updateOverflowButton() {
        overflowButton.isHidden = false
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
        menu.addItem(NSMenuItem.separator())
        // The affordance half of Debi's ask. The KEY EQUIVALENT is shown here but the
        // working binding lives in the View menu (see the menu bar at the bottom of this
        // file): a key equivalent on a menu that only exists while it is popped up would
        // never fire, and ⌘⇧T has to work with a WKWebView holding first responder.
        let hide = NSMenuItem(title: tabBarHidden ? "Show Tab Bar" : "Hide Tab Bar",
                              action: #selector(toggleTabBar(_:)), keyEquivalent: "t")
        hide.keyEquivalentModifierMask = [.command, .shift]
        hide.target = self
        menu.addItem(hide)
        _ = menu.popUp(positioning: nil,
                       at: NSPoint(x: 0, y: overflowButton.bounds.height + 4),
                       in: overflowButton)
    }

    // ══ HIDE / SHOW THE NATIVE TAB STRIP (v1.5.26, Debi) ═════════════════════════════
    //
    // WHAT IT DOES: collapses the 44pt strip to 0 so the page extends to the top of the
    // window. ⌘⇧T (View menu) and "Hide Tab Bar" in the ⋯ menu both toggle it; while it
    // is hidden, putting the pointer in the top 4pt of the window PEEKS it back for as
    // long as the pointer stays on it. Persisted in UserDefaults.
    //
    // ⚠️ WHY THE STRIP IS PUSHED, NOT OVERLAID. The obvious design floats the peeked
    // strip over the page so nothing reflows. It was rejected: `splitView` holds
    // layer-backed WKWebViews, and NSView z-ordering over those is not reliable — the
    // only deterministic way to put the strip in front is to re-add it above the split
    // view, which drops and rebuilds its constraints. A height constraint always works,
    // in every macOS version, with no ordering question at all. The cost is a 44pt
    // reflow of the visible webview on peek, which is the same reflow the window already
    // does on every resize.
    //
    // ⚠️ WHY A MOUSE-MOVED MONITOR AND NOT A TRACKING AREA. A 4pt reveal strip would
    // have to sit ON TOP of a WKWebView to receive mouseEntered — the exact z-ordering
    // problem above, one layer down. A local event monitor sees the event before it is
    // delivered to any view, so it works over the page. `acceptsMouseMovedEvents` is set
    // on the window because a window does not generate them otherwise. The monitor only
    // exists while the strip is hidden, so the ordinary build runs zero extra code.
    func applyTabBar(peeking: Bool = false) {
        let show = !tabBarHidden || peeking
        tabBarH.constant = show ? tabBarHeight : 0
        tabBar.isHidden = !show          // so a 0pt strip cannot still take a click
        tabBarPeeked = peeking
        // The View menu item names the ACTION, not the state — a menu that says
        // "Hide Tab Bar" while the bar is hidden is the same defect as a chevron that
        // means two things. Looked up rather than held: the menu is built at global
        // scope after the delegate, so there is no reference to store at init time.
        if let v = NSApp.mainMenu?.items.first(where: { $0.submenu?.title == "View" }),
           let it = v.submenu?.items.first(where: { $0.action == #selector(toggleTabBar(_:)) }) {
            it.title = tabBarHidden ? "Show Tab Bar" : "Hide Tab Bar"
        }
    }
    @objc func toggleTabBar(_ sender: Any?) {
        tabBarHidden.toggle()
        UserDefaults.standard.set(tabBarHidden, forKey: "harness.tabbar.hidden")
        applyTabBar()
        setTabBarPeekMonitor(tabBarHidden)
        slog("tab bar \(tabBarHidden ? "hidden" : "shown")")
    }
    func setTabBarPeekMonitor(_ on: Bool) {
        if let m = tabPeekMonitor { NSEvent.removeMonitor(m); tabPeekMonitor = nil }
        guard on else { return }
        window.acceptsMouseMovedEvents = true
        tabPeekMonitor = NSEvent.addLocalMonitorForEvents(matching: [.mouseMoved]) { [weak self] ev in
            guard let s = self, s.tabBarHidden, ev.window === s.window,
                  let cv = s.window.contentView else { return ev }
            // AppKit's window coordinates have y=0 at the BOTTOM, so "the top 4pt" is
            // the top of the content view minus four.
            let y = ev.locationInWindow.y
            let top = cv.bounds.height
            if !s.tabBarPeeked && y >= top - 4 {
                s.applyTabBar(peeking: true)
            } else if s.tabBarPeeked && y < top - s.tabBarHeight {
                // Closes only once the pointer has left the STRIP, not the 4pt trigger —
                // otherwise the strip would snap shut the instant it opened under the
                // pointer, which is the classic auto-hide bug.
                s.applyTabBar(peeking: false)
            }
            return ev
        }
    }
    @objc func overflowPick(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        touchWindow(id)        // …the swap Debi asked for: in at the front, oldest out
        rebuildTabs()
        guard let idx = tabs.firstIndex(where: { $0.id == id }) else { return }
        routeTab(idx, toPane: (splitOn && focusedPane == 1) ? 1 : 0)
        syncStrip()
        slog("overflow -> \(id)")
    }

    // Adopt a pinned list. No-ops when nothing changed, so the poll can run forever
    // without ever touching the layout.
    func applyNav(_ ids: [String], _ window: [String]) {
        let clean = ids.filter { i in tabRegistry.contains(where: { $0.id == i }) }
        let win = window.filter { i in tabRegistry.contains(where: { $0.id == i }) }
        guard !clean.isEmpty, clean != navPinned || win != navWindow else { return }
        navPinned = clean
        // The bridge is the authority on the window too — it is persisted there, and a
        // second panel or another window may have moved it. An entry that is PINNED
        // again no longer needs a window slot.
        navWindow = win.filter { !clean.contains($0) }
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
            // The PINS. The bridge caps them at nine (nav.py's NAV_TOPBAR_PINS) and
            // repairs a file that says more, so this is already the stable prefix —
            // the `prefix` here is the shell refusing to be broken by a bridge that
            // is not, exactly as the mc-first rule is.
            let ids = Array(top.compactMap { r -> String? in
                guard let id = r["id"] as? String, (r["pinned"] as? Bool) == true else { return nil }
                return id
            }.prefix(9))
            // THE WINDOW. Read from `nav.mru` — the persisted last-three. A bridge too
            // old to know the key leaves this empty, which draws the nine pins and
            // nothing else: fewer tabs than there should be, never wrong ones.
            let win = Array(((nav["mru"] as? [String]) ?? []).prefix(navWindowMax))
            DispatchQueue.main.async {
                self.navLoaded = true
                if let g = obj["gen"] as? Int { self.navGen = g }
                self.applyNav(ids, win)
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
                // Same swap as the ⋯ menu, deliberately: a sidebar row and a menu item
                // that open the same tab must leave the strip in the same state. The
                // panel ALSO posts this (its own optimistic copy); `mru_touch` is
                // idempotent, so the second one is a no-op that writes nothing.
                touchWindow(hit)
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
    // the budget, shorten the LONGEST titles (e.g. "VoiceStudio" → "Voice") rather
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
        if let wv = wvById[tabs[idx].id] { return wv }
        // UNREACHABLE BY CONSTRUCTION: wvById is built from tabRegistry and `tabs` is
        // always a subset of it. If it ever happens it is a real defect, and its symptom
        // is precisely "this tab shows Mission Control" — so it gets a log line rather
        // than looking like a rendering quirk. Still returns the panel: a nil here would
        // be a crash, and a crash is worse than the wrong page.
        slog("BUG: no webview for tab id \(tabs[idx].id) — showing the panel instead")
        return panelWV
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
        // NO `?? panelWV` HERE, deliberately: loading another tab's URL into the PANEL's
        // webview would replace Mission Control with that page — the bridge-wait surface
        // and the file-drop target — and leave the tab that asked for it showing the
        // panel. Refuse loudly instead, and do not mark it loaded, so a later attempt
        // (⌘R, re-select) can still succeed if whatever went wrong was transient.
        guard let wv = wvById[id] else {
            slog("BUG: no webview for tab id \(id) — refusing to load \(urlForTab(idx)) into the panel")
            return
        }
        loadedTabs.insert(id)
        wv.load(URLRequest(url: urlForTab(idx)))
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
    // The banner a host carries, if any. `park` and any other container has none, so
    // everything parked keeps its full-height geometry and a re-borrow needs no relayout.
    func bannerFor(_ host: NSView) -> DepsBanner? {
        if host === leftHost { return bannerL }
        if host === rightHost { return bannerR }
        return nil
    }

    func attach(_ v: NSView, to host: NSView) {
        if v.superview === host { return }
        v.removeFromSuperview()
        v.translatesAutoresizingMaskIntoConstraints = false
        host.addSubview(v)
        // ⚠️ THE DEPENDENCY STRIP IS ABOVE THE CONTENT, NOT OVER IT. Pinning to the
        // banner's bottom (which sits at the host's top and is 0pt tall when there is
        // nothing to say) is what makes the banner advisory by CONSTRUCTION rather than
        // by good intentions: it cannot cover a control, so it cannot block one.
        let contentTop = bannerFor(host)?.bottomAnchor ?? host.topAnchor
        NSLayoutConstraint.activate([
            v.topAnchor.constraint(equalTo: contentTop),
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
        // …and the dependency signal, for exactly the same reason and from exactly the
        // same call site: this function is the only place that knows what is on screen.
        updateDepsTimer()
        applyDepsBanners()
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
            "<p>Start the component in MOT Deck,<br>then re-select this tab &mdash; or press &#8984;R.</p></div></body>",
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
        // --timeout-graceful-shutdown: THE ZOMBIE-BRIDGE FIX (2026-08-30 incident,
        // second find). On SIGTERM uvicorn closes the LISTENING socket immediately and
        // then waits — with no default deadline — for every in-flight response to
        // finish. /api/events is an infinite text/event-stream, so a single client
        // holding one (measured: the Claude desktop app, across two separate bridges)
        // makes that wait eternal. The result was bridges with no listening socket that
        // never exited: they kept their health poller running and kept appending to
        // data/logs/bridge.log while a NEW bridge owned the port. Three were alive at
        // once. Ten seconds is generous for a real request and finite for a stream.
        p.arguments = ["-m", "uvicorn", "bridge.app:app",
                       "--host", "127.0.0.1", "--port", "8700",
                       "--timeout-graceful-shutdown", "10"]
        p.currentDirectoryURL = URL(fileURLWithPath: resolvedRoot)
        let log = FileHandle(forWritingAtPath: logPath()) ?? FileHandle.nullDevice
        log.seekToEndOfFile()
        p.standardOutput = log
        p.standardError = log
        do {
            try p.run()
            // Launch provenance is written by the process that owns the real child
            // handle. The bridge waits briefly for this exact PID+birth record and
            // refuses to self-adopt from a path, name, CWD, pidfile, or port.
            let recorder = Process()
            recorder.executableURL = URL(fileURLWithPath: "/bin/bash")
            recorder.arguments = ["\(resolvedRoot)/scripts/start_component.sh",
                                  "--record-child", "bridge", "\(p.processIdentifier)"]
            recorder.currentDirectoryURL = URL(fileURLWithPath: resolvedRoot)
            recorder.standardOutput = log
            recorder.standardError = log
            try recorder.run()
            recorder.waitUntilExit()
            if recorder.terminationStatus == 0 {
                bridgeProcess = p
                spawnedBridge = true
            } else {
                terminateExactSpawnedChild(p)
            }
        } catch {
            terminateExactSpawnedChild(p)
        }
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

    // ══ QUIT EVERYTHING (U55 — Debi's ruling, 2026-09-02) ════════════════════
    //
    // BOTH DOORS. ⌘Q ("Quit M.O.T") is UNCHANGED and stays the default: since
    // v1.5.69 the bridge and every component are setsid'd out of the app's process
    // group on purpose, so closing the window leaves the stack serving and reopening
    // the app reuses it. ⌥⌘Q is the second door — the one Debi asked for — and it means
    // exactly what it says: every component down, the bridge down, then the app.
    //
    // THE HONESTY RULES THIS UI OBEYS, all three of which are the same rule:
    //   · the confirmation NAMES what is running, read live from /api/quitall/plan,
    //     because "this will stop everything" is a sentence the user cannot check;
    //   · the app does NOT vanish on a partial stop. If the bridge answers 409 the
    //     failures are shown, the app stays open, and quitting anyway is a second,
    //     explicitly-labelled choice — a quit that leaves orphans behind a closed door
    //     is worse than one that refuses, because nothing is left to see them from;
    //   · losing contact mid-quit is reported as UNKNOWN, not as success.
    //
    // ⚠️ NSAlert, not confirm(). alert()/confirm() are silent no-ops in this WKWebView
    // shell — a panel-side confirm would return instantly and always false.
    var quitAllSheet: NSWindow?
    // ⚠️ ONE AT A TIME (adversarial pass, 2026-09-02). ⌥⌘Q twice in a second — an
    // impatient second press while the first sweep is still working — used to stack a
    // second confirmation ON TOP of the progress sheet and fire a second POST. The
    // bridge now refuses the overlap with a 409, but the app must not put the user in
    // front of that dialog at all: the honest answer to "quit again" while quitting is
    // to do nothing.
    var quitAllInFlight = false

    /// GET /api/quitall/plan → the component names currently running, or nil when the
    /// bridge does not answer (which is itself a valid, and quiet, outcome).
    func quitAllPlan(_ done: @escaping ([String]?) -> Void) {
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/quitall/plan"))
        req.timeoutInterval = 2.5
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            guard (resp as? HTTPURLResponse)?.statusCode == 200, let data = data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let running = obj["running"] as? [String] else { return done(nil) }
            done(running)
        }.resume()
    }

    @objc func quitEverything(_ sender: Any?) {
        if quitAllInFlight { NSSound.beep(); return }
        quitAllInFlight = true
        quitAllPlan { running in
            DispatchQueue.main.async { self.confirmQuitEverything(running) }
        }
    }

    func confirmQuitEverything(_ running: [String]?) {
        let a = NSAlert()
        a.alertStyle = .warning
        guard let running = running else {
            // No bridge to ask. Nothing of ours is being supervised, so this is just a
            // quit — said plainly rather than pretending a stop happened.
            a.messageText = "Quit M.O.T?"
            a.informativeText = "The bridge on 127.0.0.1:8700 is not answering, so there "
                + "is nothing running for M.O.T to stop. The app will just close."
            a.addButton(withTitle: "Quit")
            a.addButton(withTitle: "Cancel")
            if a.runModal() == .alertFirstButtonReturn { NSApp.terminate(nil) }
            quitAllInFlight = false
            return
        }
        a.messageText = "Quit M.O.T and stop everything?"
        if running.isEmpty {
            a.informativeText = "Nothing is running right now. M.O.T will stop the "
                + "bridge and close.\n\nPlain ⌘Q leaves the bridge running instead."
        } else {
            a.informativeText = "This stops \(running.count) running "
                + (running.count == 1 ? "process" : "processes") + ", then the bridge, "
                + "then the app:\n\n    " + running.joined(separator: "\n    ")
                + "\n\nModels are unloaded and anything mid-flight is ended. "
                + "Plain ⌘Q leaves all of it running instead."
        }
        a.addButton(withTitle: "Quit Everything")
        a.addButton(withTitle: "Cancel")
        guard a.runModal() == .alertFirstButtonReturn else {
            quitAllInFlight = false          // Cancel leaves the stack, and the menu, alone
            return
        }
        performQuitEverything(running)
    }

    /// The honest progress surface. Indeterminate on purpose: the bridge stops
    /// components sequentially and a fake percentage would be the only lie here.
    func showQuitAllSheet(_ running: [String]) {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 118),
                         styleMask: [.titled], backing: .buffered, defer: false)
        w.appearance = NSAppearance(named: .darkAqua)
        w.title = "Quitting everything"
        let v = NSView(frame: NSRect(x: 0, y: 0, width: 440, height: 118))
        let label = NSTextField(labelWithString:
            running.isEmpty ? "Stopping the bridge…"
                            : "Stopping \(running.count) "
                              + (running.count == 1 ? "process" : "processes") + "…")
        label.frame = NSRect(x: 24, y: 62, width: 392, height: 20)
        let sub = NSTextField(labelWithString:
            running.isEmpty ? "" : running.joined(separator: ", "))
        sub.frame = NSRect(x: 24, y: 40, width: 392, height: 18)
        sub.textColor = .secondaryLabelColor
        sub.lineBreakMode = .byTruncatingTail
        sub.font = NSFont.systemFont(ofSize: 11)
        let spin = NSProgressIndicator(frame: NSRect(x: 24, y: 14, width: 392, height: 16))
        spin.style = .bar
        spin.isIndeterminate = true
        spin.startAnimation(nil)
        v.addSubview(label); v.addSubview(sub); v.addSubview(spin)
        w.contentView = v
        quitAllSheet = w
        if let host = window, host.isVisible {
            host.beginSheet(w, completionHandler: nil)
        } else {
            w.center(); w.makeKeyAndOrderFront(nil)
        }
    }

    func hideQuitAllSheet() {
        guard let w = quitAllSheet else { return }
        if let host = window, host.isVisible, host.attachedSheet === w {
            host.endSheet(w)
        }
        w.orderOut(nil)
        quitAllSheet = nil
    }

    func performQuitEverything(_ running: [String]) {
        showQuitAllSheet(running)
        var req = URLRequest(url: bridgeURL.appendingPathComponent("api/quitall"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = "{}".data(using: .utf8)
        // Generous: the bridge gives each component up to ~1.5s of settle time and there
        // can be eleven of them, and a wedged model server can take longer still. A
        // timeout shorter than the work is a false "lost contact".
        req.timeoutInterval = 180
        URLSession.shared.dataTask(with: req) { data, resp, err in
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let obj = data.flatMap {
                try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? nil
            DispatchQueue.main.async {
                self.hideQuitAllSheet()
                if code == 200, let obj = obj, (obj["ok"] as? Bool) == true {
                    NSApp.terminate(nil)                      // everything really is down
                    return
                }
                let b = NSAlert()
                b.alertStyle = .critical
                if obj == nil || code == 0 {
                    // ⚠️ NOT reported as success. The bridge exits ~1.2s after answering,
                    // so a dropped connection here is genuinely ambiguous: it may have
                    // stopped everything and gone, or it may have died mid-sweep.
                    b.messageText = "Lost contact with the bridge while quitting"
                    b.informativeText = "MOT Deck did not get an answer"
                        + (err.map { " (\($0.localizedDescription))" } ?? "")
                        + ". Some components may still be running.\n\n"
                        + "Check from Terminal:\n"
                        + "    curl -s 127.0.0.1:8700/api/status\n"
                        + "    lsof -ti tcp:6767 -sTCP:LISTEN"
                } else {
                    let lines = (obj?["sentences"] as? [String]) ?? []
                    let failed = (obj?["failed"] as? [String]) ?? []
                    b.messageText = failed.isEmpty
                        ? "Quit Everything did not finish"
                        : "Still running: " + failed.joined(separator: ", ")
                    b.informativeText = (lines.isEmpty ? "The bridge refused the quit."
                                                       : lines.joined(separator: "\n"))
                        + "\n\nThe bridge was left running on purpose, so you can still "
                        + "see and stop these from Mission Control."
                }
                b.addButton(withTitle: "Stay Open")
                b.addButton(withTitle: "Quit M.O.T Anyway")
                if b.runModal() != .alertFirstButtonReturn { NSApp.terminate(nil) }
                // Staying open must leave ⌥⌘Q usable — the user's next move after
                // reading which component refused is very often to try again.
                self.quitAllInFlight = false
            }
        }.resume()
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
appMenu.addItem(NSMenuItem.separator())
// ⌘Q — UNCHANGED, and deliberately still the plain quit (v1.5.69 behaviour: the bridge
// and every component keep serving; reopening the app reuses them).
appMenu.addItem(withTitle: "Quit M.O.T", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
// ⌥⌘Q — THE SECOND DOOR (U55, Debi 2026-09-02: "i think we should have an option that
// fully quits everything too"). Right next to the plain quit, because that is where a
// user looks for it, and one modifier away, because it is the same intent with a bigger
// blast radius.
//
// ⌥⌘Q WAS CHECKED AGAINST EVERY BINDING THIS APP AND THE PANEL OWN, the same way ⌘⇧T
// was: ⌘R (Reload Tab), ⌘Q (this menu), ⌘C/⌘V/⌘A (Edit), ⌘⇧T (View → tab strip), and
// ⌘K (command palette) + ⌘\ (sidebar) inside the panel. Unclaimed.
// ⚠️ AND ⇧⌘Q WAS REJECTED, not merely not-chosen: ⇧⌘Q is macOS's own LOG OUT shortcut.
// Binding an app action to it means a user reaching for Quit Everything sometimes logs
// out of the Mac instead — the worst kind of near-miss, since it takes everything else
// with it.
let quitAllItem = NSMenuItem(title: "Quit Everything (stop all components)",
                             action: #selector(AppDelegate.quitEverything(_:)),
                             keyEquivalent: "q")
quitAllItem.keyEquivalentModifierMask = [.command, .option]
quitAllItem.target = delegate
appMenu.addItem(quitAllItem)
appItem.submenu = appMenu
let editItem = NSMenuItem()
mainMenu.addItem(editItem)
let editMenu = NSMenu(title: "Edit")
editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editItem.submenu = editMenu
// v1.5.26 — a View menu, for exactly one item: the tab-strip toggle. A MENU item is the
// reliable place for this shortcut, and that is why the menu exists at all — AppKit
// dispatches menu key equivalents before the responder chain, so ⌘⇧T fires while a
// WKWebView holds first responder, which a local key monitor competing with the page
// would not reliably do. The ⋯ menu carries the same action as the discoverable
// affordance; this carries the key.
// ⌘⇧T was checked against every binding this app and the panel already own: ⌘R (Reload
// Tab), ⌘Q, ⌘C/⌘V/⌘A here, and ⌘K (palette) + ⌘\ (sidebar) in the panel. Unclaimed.
let viewItem = NSMenuItem()
mainMenu.addItem(viewItem)
let viewMenu = NSMenu(title: "View")
let tabBarItem = NSMenuItem(title: "Hide Tab Bar",
                            action: #selector(AppDelegate.toggleTabBar(_:)), keyEquivalent: "t")
tabBarItem.keyEquivalentModifierMask = [.command, .shift]
tabBarItem.target = delegate
viewMenu.addItem(tabBarItem)
viewItem.submenu = viewMenu
app.mainMenu = mainMenu

app.run()
