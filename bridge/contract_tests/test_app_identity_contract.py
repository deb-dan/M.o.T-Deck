"""THE APP'S NAME IS "M.O.T", AND THE BUNDLE IS STILL Harness.app — 2026-09-02.

Debi: *"the dock hover shows Harness — i think it should show M.O.T"*.

THE MECHANISM (researched, not assumed). The Dock's hover label is Launch Services'
display name for the bundle — `lsappinfo info -only name <asn>` prints exactly the
string the Dock shows. LS resolves it in this order:

    localized name (Contents/Resources/<lang>.lproj/InfoPlist.strings)
      → CFBundleDisplayName
        → the .app FILENAME

The installed bundle had neither key (its CFBundleName still said "Harness", predating
build_app.sh's "MOT Deck"), so the filename won and hover read "Harness". CFBundleName
is a different question: it is what the MENU BAR reads.

⛔ THE BUNDLE PATH IS NOT RENAMED, AND THAT IS THE CONTRACT. ship.sh, stop.sh, the
pidfiles, `osascript -e 'quit app "Harness"'` in CLAUDE.md's restart recipes and Debi's
muscle memory all point at /Applications/Harness.app. A display name changes what is
SHOWN without moving anything; renaming the bundle is a different slice with a much
larger blast radius. This file exists to keep those two apart.

WHAT IS PINNED:
  1. ship.sh sets the display name AND the menu-bar name AND the localized name, and
     re-signs + refreshes Launch Services when it does (an ad-hoc signature covers
     Contents/, so editing Info.plist invalidates it exactly as replacing the icon does).
  2. build_app.sh writes the same names, so a FRESH fat install matches a shipped one.
  3. The app menu's Quit item names the SAME string, because "M.O.T" in the Dock over
     "Quit MOT Deck" in the menu is the incoherence this slice removed.
  4. Nothing renamed the bundle: ship.sh still targets /Applications/Harness.app and
     still asks the app to quit by that name.

⚠️ NO ASSERTION HERE READS THE INSTALLED BUNDLE. ship.sh runs this gate BEFORE its
bundle step, so a test that required the live plist to already say M.O.T would refuse
the very ship that sets it. The live check belongs in the walk, and it is:
    lsappinfo info -only name "$(lsappinfo find bundleid=local.harness.app)"

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_app_identity_contract.py -q
"""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHIP = os.path.join(ROOT, "scripts", "ship.sh")
BUILD = os.path.join(ROOT, "scripts", "build_app.sh")
SWIFT = os.path.join(ROOT, "app", "main.swift")

NAME = "M.O.T"


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(p):
    return "\n".join(ln for ln in _read(p).splitlines()
                     if not ln.lstrip().startswith(("#", "//")))


def test_ship_sets_the_display_name_the_menu_name_and_the_localized_name():
    code = _code(SHIP)
    assert f'_APP_NAME="{NAME}"' in code, "ship.sh no longer names the app"
    for key in ("CFBundleDisplayName", "CFBundleName"):
        assert f"_plist_put {key}" in code, f"ship.sh stopped setting {key}"
    assert "en.lproj/InfoPlist.strings" in code, (
        "the LOCALIZED name is gone. CFBundleDisplayName alone may be IGNORED when it "
        "differs from the .app filename (Apple's anti-spoofing rule); the localized "
        "name always wins, and the filename stays Harness.app on purpose.")
    assert "PlistBuddy" in code and "Add :" in code, \
        "the Set-then-Add fallback is gone: a bundle without the key gets nothing"


def test_a_name_change_resigns_and_refreshes_launch_services():
    code = _code(SHIP)
    # The name branch must set BOTH flags: the ad-hoc signature covers Contents/, and a
    # cached display name is exactly as invisible as a cached icon.
    tail = code.split('_APP_NAME="', 1)[1]
    branch = tail.split("if [[ \"$_RESIGN\"", 1)[0]
    assert "_RESIGN=1" in branch, "an Info.plist edit that is not re-signed breaks the app"
    assert "_MARK_CHANGED=1" in branch, \
        "without the cache refresh the Dock keeps showing the old name indefinitely"
    assert "lsregister -f" in code or '"$_LSREG" -f' in code
    assert "launchctl kickstart -k" in code, \
        "the Dock refresh must stay launchd's own restart, never a kill by name"


def test_fresh_fat_installs_get_the_same_name():
    code = _code(BUILD)
    assert f"<key>CFBundleDisplayName</key><string>{NAME}</string>" in code
    assert f"<key>CFBundleName</key><string>{NAME}</string>" in code
    assert "en.lproj/InfoPlist.strings" in code, \
        "the fat build must write the localized name too, or a fresh install disagrees"
    assert f"{NAME} uses the microphone" in code, \
        "the mic prompt names the app to the user in a system dialog — keep it in step"


def test_the_menu_bar_quit_item_agrees_with_the_display_name():
    code = _read(SWIFT)
    m = re.search(r'appMenu\.addItem\(withTitle:\s*"Quit ([^"]+)"', code)
    assert m, "the app menu's Quit item moved — re-read this fence"
    assert m.group(1) == NAME, (
        f"the Quit item says “Quit {m.group(1)}” while the Dock says “{NAME}”. macOS "
        f"names the Quit item after the app; a disagreement here IS the bug this slice "
        f"fixed (the menu said MOT Deck while hover said Harness).")


def test_nothing_renamed_the_bundle():
    code = _code(SHIP)
    assert 'APP="/Applications/Harness.app"' in code, \
        "the bundle PATH moved — that is a different slice (pidfiles, quit recipes, docs)"
    assert "osascript -e 'quit app \"Harness\"'" in code, \
        "the Apple Event quit must keep naming the bundle, not the display name"
