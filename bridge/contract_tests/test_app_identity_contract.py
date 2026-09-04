"""THE APP'S NAME IS "M.O.T"; ITS INSTALLED FILENAME IS NOT ITS IDENTITY — U78.

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

⛔ THE BUILD OUTPUT IS NOT RENAMED: it remains dist/Harness.app. Finder may install the
same bundle as Harness.app or M.O.T.app, however, and the installed filename is not a
safe lifecycle identity. ship.sh resolves a candidate by its CFBundleIdentifier and its
executable before any gate or copy, then uses the stable bundle id for its quit request.

WHAT IS PINNED:
  1. ship.sh sets the display name AND the menu-bar name AND the localized name, and
     re-signs + refreshes Launch Services when it does (an ad-hoc signature covers
     Contents/, so editing Info.plist invalidates it exactly as replacing the icon does).
  2. build_app.sh writes the same names, so a FRESH fat install matches a shipped one.
  3. The app menu's Quit item names the SAME string, because "M.O.T" in the Dock over
     "Quit MOT Deck" in the menu is the incoherence this slice removed.
  4. Temporary fixture bundles prove zero/ambiguous/invalid resolution fails closed;
     the exact valid override wins and a spaced path remains one argv item.
  5. ship opens that exact resolved path but asks macOS to quit by bundle id, not by a
     filename or display name.

⚠️ NO ASSERTION HERE READS A LIVE INSTALLED BUNDLE. ship.sh runs this gate BEFORE its
bundle step, so a test that required the live plist to already say M.O.T would refuse
the very ship that sets it. Resolver assertions use temporary fixtures; the live check
belongs in the walk, and it is:
    lsappinfo info -only name "$(lsappinfo find bundleid=local.harness.app)"

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_app_identity_contract.py -q
"""
import os
import plistlib
import re
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SHIP = os.path.join(ROOT, "scripts", "ship.sh")
BUILD = os.path.join(ROOT, "scripts", "build_app.sh")
INSTALL_COMPONENT = os.path.join(ROOT, "scripts", "install_component.sh")
SWIFT = os.path.join(ROOT, "app", "main.swift")

NAME = "M.O.T"


def _read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(p):
    return "\n".join(ln for ln in _read(p).splitlines()
                     if not ln.lstrip().startswith(("#", "//")))


def _fixture_app(tmp_path, name, *, bundle_id="local.harness.app",
                 executable="Harness", executable_mode=0o755, create_binary=True):
    """Create the smallest app bundle the real shell resolver accepts or rejects."""
    app = tmp_path / name
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    plist = {"CFBundleIdentifier": bundle_id}
    if executable is not None:
        plist["CFBundleExecutable"] = executable
    with (app / "Contents" / "Info.plist").open("wb") as fh:
        plistlib.dump(plist, fh)
    if executable is not None and create_binary:
        binary = macos / executable
        binary.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        binary.chmod(executable_mode)
    return app


def _resolve_fixture_apps(*apps, override=None):
    """Run only ship.sh's resolver; fixture mode exits before live paths or gates."""
    env = os.environ.copy()
    env.pop("HARNESS_APP_PATH", None)
    if override is not None:
        env["HARNESS_APP_PATH"] = str(override)
    return subprocess.run(["bash", SHIP, "--resolve-app-fixtures", *map(str, apps)],
                          cwd=ROOT, env=env, capture_output=True, text=True)


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
    assert 'APP=dist/Harness.app' in code, "the build artifact filename is contract truth"
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


def test_ship_resolves_installed_bundle_by_identity_and_opens_that_exact_path():
    code = _code(SHIP)
    assert 'CFBundleIdentifier' in code and 'local.harness.app' in code
    assert 'CFBundleExecutable' in code and '"$executable" == "Harness"' in code
    assert 'Contents/MacOS/Harness' in code
    assert 'cd -P "$1"' in code and 'pwd -P' in code
    assert '"/Applications/Harness.app"' in code and '"/Applications/M.O.T.app"' in code
    assert '"$HOME/Applications/Harness.app"' in code
    assert '"$HOME/Applications/M.O.T.app"' in code
    assert 'open "$APP"' in code, "ship must open the precise resolved app, not LS selection"


def test_resolver_accepts_a_valid_spaced_path_without_splitting_it(tmp_path):
    app = _fixture_app(tmp_path, "M.O.T installed copy.app")
    result = _resolve_fixture_apps(app)
    assert result.returncode == 0, result.stderr + result.stdout
    assert f"selected installed app: {app}" in result.stdout


def test_relative_explicit_override_selects_the_canonical_absolute_bundle_path(tmp_path):
    app = _fixture_app(tmp_path, "relative override.app")
    relative = os.path.relpath(app, ROOT)
    result = _resolve_fixture_apps(override=relative)
    assert result.returncode == 0, result.stderr + result.stdout
    assert f"selected installed app: {app.resolve()}" in result.stdout
    assert f"selected installed app: {relative}" not in result.stdout


def test_resolver_rejects_wrong_id_missing_or_nonexecutable_binary(tmp_path):
    wrong_id = _fixture_app(tmp_path, "wrong-id.app", bundle_id="org.example.other")
    missing_declared_executable = _fixture_app(tmp_path, "missing-plist-executable.app",
                                               executable=None)
    missing_binary = _fixture_app(tmp_path, "missing-executable.app", create_binary=False)
    non_executable = _fixture_app(tmp_path, "not-executable.app", executable_mode=0o644)
    alternate_executable = _fixture_app(tmp_path, "alternate-executable.app",
                                        executable="M.O.T")
    slash_executable = _fixture_app(tmp_path, "slash-executable.app",
                                    executable="../Harness", create_binary=False)
    for app in (wrong_id, missing_declared_executable, missing_binary, non_executable,
                alternate_executable, slash_executable):
        result = _resolve_fixture_apps(app)
        assert result.returncode != 0
        assert "no valid installed Harness bundle found" in result.stdout


def test_resolver_zero_and_ambiguous_candidates_fail_closed(tmp_path):
    zero = _resolve_fixture_apps()
    assert zero.returncode != 0
    assert "no valid installed Harness bundle found" in zero.stdout

    first = _fixture_app(tmp_path, "Harness.app")
    second = _fixture_app(tmp_path, "M.O.T.app")
    ambiguous = _resolve_fixture_apps(first, second)
    assert ambiguous.returncode != 0
    assert "refusing to guess" in ambiguous.stdout
    assert str(first) in ambiguous.stdout and str(second) in ambiguous.stdout


def test_explicit_override_selects_only_its_valid_candidate_and_never_falls_back(tmp_path):
    chosen = _fixture_app(tmp_path, "chosen.app")
    other = _fixture_app(tmp_path, "other.app")
    selected = _resolve_fixture_apps(other, override=chosen)
    assert selected.returncode == 0, selected.stderr + selected.stdout
    assert f"selected installed app: {chosen}" in selected.stdout
    assert str(other) not in selected.stdout

    invalid = tmp_path / "invalid.app"
    rejected = _resolve_fixture_apps(other, override=invalid)
    assert rejected.returncode != 0
    assert "HARNESS_APP_PATH" in rejected.stdout
    assert str(invalid) in rejected.stdout
    assert "CFBundleIdentifier local.harness.app" in rejected.stdout
    assert "CFBundleExecutable Harness at Contents/MacOS/Harness" in rejected.stdout
    assert "selected installed app" not in rejected.stdout


def test_ship_quits_by_stable_bundle_id_not_a_filename_or_display_name():
    code = _code(SHIP)
    assert "osascript -e 'tell application id \"local.harness.app\" to quit'" in code
    assert "osascript -e 'quit app \"Harness\"'" not in code
    assert "tell application \"M.O.T\"" not in code


def test_component_wheelhouse_discovery_covers_both_installed_bundle_names():
    code = _code(INSTALL_COMPONENT)
    for path in (
        "/Applications/Harness.app/Contents/Resources/wheelhouse",
        "/Applications/M.O.T.app/Contents/Resources/wheelhouse",
        '"$HOME/Applications/Harness.app/Contents/Resources/wheelhouse"',
        '"$HOME/Applications/M.O.T.app/Contents/Resources/wheelhouse"',
    ):
        assert path in code, f"installed wheelhouse location missing: {path}"


def test_build_quarantine_advice_never_assumes_the_installed_bundle_filename():
    code = _code(BUILD)
    assert "xattr -dr com.apple.quarantine /Applications/Harness.app" not in code
    assert "xattr -dr com.apple.quarantine <installed-app-path>" in code
