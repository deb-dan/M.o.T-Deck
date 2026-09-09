from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SWIFT = (ROOT / "app" / "main.swift").read_text(encoding="utf-8")


def test_all_javascript_panel_delegate_seams_exist():
    for seam in (
        "runJavaScriptAlertPanelWithMessage",
        "runJavaScriptConfirmPanelWithMessage",
        "runJavaScriptTextInputPanelWithPrompt",
    ):
        assert seam in SWIFT


def test_confirm_and_prompt_have_explicit_cancel_paths():
    assert SWIFT.count('alert.addButton(withTitle: "Cancel")') >= 2
    assert "completionHandler($0 == .alertFirstButtonReturn)" in SWIFT
    assert "field.stringValue : nil" in SWIFT


def test_dialogs_use_the_requesting_webview_window():
    assert "webView.window ?? window" in SWIFT
    assert "beginSheetModal(for: host" in SWIFT
