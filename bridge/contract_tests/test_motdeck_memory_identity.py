import plistlib

from bridge.core.memory import _is_motdeck_shell


def _bundle(tmp_path, name, bundle_id="local.motdeck.app", executable="MOTDeck"):
    bundle = tmp_path / name
    macos = bundle / "Contents/MacOS"
    macos.mkdir(parents=True)
    binary = macos / executable
    binary.write_text("binary")
    with (bundle / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id,
                       "CFBundleExecutable": executable}, handle)
    return bundle, binary


def test_memory_ledger_recognizes_renamed_bundle_by_metadata(tmp_path):
    _bundle_dir, binary = _bundle(tmp_path, "Anything the user called it.app")
    assert _is_motdeck_shell(str(binary))


def test_memory_ledger_rejects_old_or_foreign_identity_and_lookalike_path(tmp_path):
    _old, old_binary = _bundle(tmp_path, "old.app", bundle_id="local.harness.app")
    _foreign, foreign_binary = _bundle(tmp_path, "foreign.app", bundle_id="org.other")
    assert not _is_motdeck_shell(str(old_binary))
    assert not _is_motdeck_shell(str(foreign_binary))
    assert not _is_motdeck_shell(str(tmp_path / "not-an-app/Contents/MacOS/MOTDeck"))
