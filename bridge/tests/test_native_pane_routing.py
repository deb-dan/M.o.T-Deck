"""Execute the shell's actual Swift pane functions, with lightweight view doubles."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def swift_cache(tmp_path_factory):
    return tmp_path_factory.mktemp("native-swift-cache")


def _method(name):
    source = (ROOT / 'app/main.swift').read_text()
    start = source.index('    func ' + name + '(')
    end = source.index('\n    }', start) + len('\n    }')
    return source[start:end]


def test_duplicate_pane_survives_nav_and_reload_targets_focused_view(tmp_path, swift_cache):
    source = '''
import Foundation
final class WKWebView {}
struct Tab { let id: String; let title: String }
final class Strip {
    var segmentCount = 0
    func setLabel(_ label: String, forSegment: Int) {}
}
var tabs = [Tab(id: "mc", title: "MOT Deck"), Tab(id: "hermes", title: "Hermes")]
func tabsFor(_ ids: [String]) -> [Tab] { ids.map { Tab(id: $0, title: $0) } }
final class Shell {
    var currentTab = 1, rightTab = 1, focusedPane = 1
    var splitOn = true, leftIsGhost = true, rightIsGhost = false
    let primary = WKWebView(), duplicate = WKWebView()
    var secondInstances: [String: WKWebView] = [:]
    let seg = Strip()
    func webViewFor(_ idx: Int) -> WKWebView { primary }
    func tabId(_ idx: Int) -> String { tabs[idx].id }
    func touchWindow(_ id: String) {}
    func stripIds() -> [String] { ["mc", "hermes"] }
    func setSegmentWidths() {}
    func persistTabs() {}
    func updateOverflowButton() {}
    func updateFocusStrips() {}
    func syncStrip() {}
    func slog(_ message: String) {}
    func applyPanes() {
        if !splitOn || currentTab != rightTab {
            leftIsGhost = false; rightIsGhost = false; secondInstances.removeAll()
        }
    }
''' + _method('visibleWebView') + '\n' + _method('rebuildTabs') + '''
}
let shell = Shell()
shell.secondInstances["hermes"] = shell.duplicate
var failed: [String] = []
if shell.visibleWebView() !== shell.primary { failed.append("right focus reloaded left duplicate") }
shell.focusedPane = 0
if shell.visibleWebView() !== shell.duplicate { failed.append("left focus missed duplicate") }
shell.rebuildTabs()
if shell.secondInstances["hermes"] !== shell.duplicate || shell.rightTab != shell.currentTab {
    failed.append("nav refresh discarded duplicate pane")
}
shell.leftIsGhost = false; shell.rightIsGhost = true; shell.focusedPane = 1
if shell.visibleWebView() !== shell.duplicate { failed.append("right focus missed duplicate") }
shell.focusedPane = 0
if shell.visibleWebView() !== shell.primary { failed.append("left focus missed primary") }
if !failed.isEmpty { print(failed.joined(separator: "\n")); exit(1) }
'''
    # Keep compiler caches inside the test's scratch directory.
    path = tmp_path / 'main.swift'
    path.write_text(source.replace('separator: "\n"', 'separator: "\\n"'))
    result = subprocess.run(['swift', '-module-cache-path', str(swift_cache), str(path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_drop_reader_bounds_large_files_and_refuses_special_files(tmp_path, swift_cache):
    source = (ROOT / 'app/main.swift').read_text()
    helper = source[source.index('enum NativeDropReadError:'):source.index('// ONE table:')]
    test = r'''
import Foundation
import Darwin
''' + helper + r'''
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let small = root.appendingPathComponent("small.txt")
let text = Data("Résumé 😀".utf8)
try text.write(to: small)
let read = try readNativeDrop(small, limit: text.count)
assert(read == text)
let link = root.appendingPathComponent("chosen-link.txt")
try FileManager.default.createSymbolicLink(at: link, withDestinationURL: small)
assert(try readNativeDrop(link, limit: 100) == text)
let large = root.appendingPathComponent("large.txt")
FileManager.default.createFile(atPath: large.path, contents: nil)
let writer = try FileHandle(forWritingTo: large)
try writer.truncate(atOffset: 5 * 1024 * 1024 * 1024)
try writer.close()
do { _ = try readNativeDrop(large, limit: 10 * 1024 * 1024); fatalError("large drop was accepted") }
catch NativeDropReadError.tooLarge {}
let fifo = root.appendingPathComponent("pipe.txt")
assert(mkfifo(fifo.path, 0o600) == 0)
do { _ = try readNativeDrop(fifo, limit: 100); fatalError("FIFO was accepted") }
catch NativeDropReadError.unreadable {}
do { _ = try readNativeDrop(root, limit: 100); fatalError("directory was accepted") }
catch NativeDropReadError.unreadable {}
'''
    path = tmp_path / 'main.swift'
    # Throwing reads are evaluated before assert's non-throwing autoclosure.
    test = test.replace('assert(try readNativeDrop(link, limit: 100) == text)',
                        'let linked = try readNativeDrop(link, limit: 100); assert(linked == text)')
    path.write_text(test)
    result = subprocess.run(['swift', '-module-cache-path', str(swift_cache), str(path), str(tmp_path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_cancelled_navigation_preserves_page_and_placeholder_keeps_crash_memory(tmp_path, swift_cache):
    source = (ROOT / 'app/main.swift').read_text()
    start = source.index('    func webView(_ webView: WKWebView, didFailProvisionalNavigation')
    end = source.index('\n    // ── the web content process died', start)
    methods = source[start:end]
    code = r'''
import Foundation
class WKNavigation {}
class WKWebView { var url: URL? = URL(string: "http://127.0.0.1:8700") }
class Shell {
    var notices = 0
    var failedLoads = Set<ObjectIdentifier>(), crashedOnce = Set<ObjectIdentifier>()
    func showUnreachable(_ webView: WKWebView) { notices += 1 }
''' + methods + r'''
}
let shell = Shell(), view = WKWebView()
let cancellation = NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled)
shell.webView(view, didFailProvisionalNavigation: nil, withError: cancellation)
shell.webView(view, didFail: nil, withError: cancellation)
var failures: [String] = []
if shell.notices != 0 { failures.append("cancelled prior load replaced the current page") }
shell.webView(view, didFailProvisionalNavigation: nil,
              withError: NSError(domain: NSURLErrorDomain, code: NSURLErrorCannotConnectToHost))
if shell.notices != 1 { failures.append("real connection failure did not show one notice") }
shell.crashedOnce.insert(ObjectIdentifier(view))
view.url = URL(string: "about:blank")
shell.webView(view, didFinish: nil)
if !shell.crashedOnce.contains(ObjectIdentifier(view)) { failures.append("placeholder cleared crash-loop memory") }
view.url = URL(string: "http://127.0.0.1:8700")
shell.webView(view, didFinish: nil)
if shell.crashedOnce.contains(ObjectIdentifier(view)) { failures.append("successful recovery did not reset crash memory") }
if !failures.isEmpty { print(failures.joined(separator: "\n")); exit(1) }
'''
    path = tmp_path / 'main.swift'
    path.write_text(code)
    result = subprocess.run(['swift', '-module-cache-path', str(swift_cache), str(path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
