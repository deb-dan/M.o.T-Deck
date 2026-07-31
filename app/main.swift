// Harness.app — native macOS shell. One window, tabbed:
//   • Mission Control (the Bridge control panel, :8700)
//   • Odysseus (the workspace UI, :7860)
// Each tab is its own top-level WKWebView load — sidesteps Odysseus's X-Frame-Options/
// frame-ancestors (which block iframing) entirely. Auto-starts the bridge on launch.
// Built by scripts/build_app.sh (which generates Config.swift with harnessRoot).

import Cocoa
import WebKit

let bridgeURL = URL(string: "http://127.0.0.1:8700")!
let odysseusURL = URL(string: "http://127.0.0.1:7860")!
let hermesURL = URL(string: "http://127.0.0.1:9119")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var panelWV: WKWebView!      // Mission Control (:8700)
    var odyWV: WKWebView!        // Odysseus (:7860), lazy-loaded on first select
    var odyLoaded = false
    var hermesWV: WKWebView!     // Hermes dashboard (:9119), lazy-loaded on first select
    var hermesLoaded = false
    var failedLoads = Set<ObjectIdentifier>()   // webviews whose last load failed → retry on select/⌘R
    var bridgeProcess: Process?
    var spawnedBridge = false
    // Working harness root: the baked dev path if present, else ~/Harness (portable builds).
    var resolvedRoot = harnessRoot

    func applicationDidFinishLaunching(_ notification: Notification) {
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
        tabBar.layer?.backgroundColor = NSColor(red: 0.043, green: 0.039, blue: 0.063, alpha: 1).cgColor
        container.addSubview(tabBar)

        let seg = NSSegmentedControl(
            labels: ["Mission Control", "Odysseus", "Hermes"],
            trackingMode: .selectOne,
            target: self, action: #selector(tabChanged(_:)))
        seg.selectedSegment = 0
        seg.translatesAutoresizingMaskIntoConstraints = false
        tabBar.addSubview(seg)

        // ── web views ──
        panelWV = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())

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

        for wv in [panelWV!, odyWV!, hermesWV!] {
            wv.translatesAutoresizingMaskIntoConstraints = false
            wv.uiDelegate = self          // route target=_blank links to the default browser
            wv.navigationDelegate = self  // detect failed loads → placeholder + retry
            if #available(macOS 12.0, *) {
                wv.underPageBackgroundColor = NSColor(red: 0.043, green: 0.039, blue: 0.063, alpha: 1)
            }
            container.addSubview(wv)
        }
        odyWV.isHidden = true
        hermesWV.isHidden = true

        NSLayoutConstraint.activate([
            tabBar.topAnchor.constraint(equalTo: container.topAnchor),
            tabBar.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            tabBar.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            tabBar.heightAnchor.constraint(equalToConstant: 44),
            seg.centerXAnchor.constraint(equalTo: tabBar.centerXAnchor),
            seg.centerYAnchor.constraint(equalTo: tabBar.centerYAnchor),
            panelWV.topAnchor.constraint(equalTo: tabBar.bottomAnchor),
            panelWV.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            panelWV.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            panelWV.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            odyWV.topAnchor.constraint(equalTo: tabBar.bottomAnchor),
            odyWV.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            odyWV.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            odyWV.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            hermesWV.topAnchor.constraint(equalTo: tabBar.bottomAnchor),
            hermesWV.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            hermesWV.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            hermesWV.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])

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

    @objc func tabChanged(_ sender: NSSegmentedControl) {
        let idx = sender.selectedSegment
        panelWV.isHidden = (idx != 0)
        odyWV.isHidden = (idx != 1)
        hermesWV.isHidden = (idx != 2)
        if idx == 1 && !odyLoaded {
            odyLoaded = true
            odyWV.load(URLRequest(url: odysseusURL))
        }
        if idx == 2 && !hermesLoaded {
            hermesLoaded = true
            hermesWV.load(URLRequest(url: hermesURL))
        }
        // A previously failed tab retries automatically on re-select (component may be up now).
        if let wv = visibleWebView(), failedLoads.contains(ObjectIdentifier(wv)) {
            failedLoads.remove(ObjectIdentifier(wv))
            wv.load(URLRequest(url: urlFor(wv)))
        }
    }

    func visibleWebView() -> WKWebView? {
        if !panelWV.isHidden { return panelWV }
        if !odyWV.isHidden { return odyWV }
        if !hermesWV.isHidden { return hermesWV }
        return nil
    }

    func urlFor(_ wv: WKWebView) -> URL {
        if wv === odyWV { return odysseusURL }
        if wv === hermesWV { return hermesURL }
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
        if let url = navigationAction.request.url { NSWorkspace.shared.open(url) }
        return nil
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
