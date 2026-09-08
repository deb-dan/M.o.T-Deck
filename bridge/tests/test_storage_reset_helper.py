from pathlib import Path
import io
import os
import plistlib
import tarfile
from types import SimpleNamespace

import pytest

from scripts import storage_reset_helper as H
from bridge.routers import storage as STORAGE


def _fixture(tmp_path: Path):
    home = tmp_path / "home"
    root = home / "Library/Application Support/MOT Deck"
    app = tmp_path / "Applications/MOT Deck.app"
    binary = app / "Contents/MacOS/MOTDeck"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    with (app / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": "local.motdeck.app",
                       "CFBundleExecutable": "MOTDeck"}, handle)
    root.mkdir(parents=True)
    (root / "data.txt").write_text("owned")
    (home / ".Trash").mkdir()
    return home, root, app


def _args(home: Path, root: Path, app: Path, *, dry_run=False):
    rst, ast = os.lstat(root), os.lstat(app)
    return SimpleNamespace(mode="full-uninstall", root=str(root), app=str(app),
        root_dev=rst.st_dev, root_ino=rst.st_ino, app_dev=ast.st_dev,
        app_ino=ast.st_ino, bridge_pid=999_999_999, home=str(home), dry_run=dry_run,
        expected_version="")


def _factory_seed(app: Path, version: str) -> None:
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "firstrun_fat.sh").write_text("#!/bin/sh\n")
    payload = (version + "\n").encode()
    info = tarfile.TarInfo("VERSION")
    info.size = len(payload)
    with tarfile.open(resources / "motdeck-seed-fat.tar.gz", "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))


def test_dry_run_validates_but_changes_nothing(tmp_path):
    home, root, app = _fixture(tmp_path)
    result = H.execute(_args(home, root, app, dry_run=True))
    assert result["dry_run"] is True
    assert root.is_dir() and app.is_dir()
    assert not list((home / ".Trash").iterdir())


def test_full_uninstall_moves_only_exact_fixture_targets(tmp_path, monkeypatch):
    home, root, app = _fixture(tmp_path)
    monkeypatch.setattr(H.subprocess, "run", lambda *a, **k: None)
    result = H.execute(_args(home, root, app))
    assert not root.exists() and not app.exists()
    batch = Path(result["trash"])
    assert (batch / "MOT Deck Application Support/data.txt").read_text() == "owned"
    assert (batch / "MOT Deck.app/Contents/MacOS/MOTDeck").is_file()


def test_helper_refuses_noncanonical_and_wrong_bundle(tmp_path):
    home, root, app = _fixture(tmp_path)
    with pytest.raises(H.ResetRefusal, match="canonical"):
        H.validate_support_root(home, home=home)
    with (app / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": "some.other.app",
                       "CFBundleExecutable": "MOTDeck"}, handle)
    with pytest.raises(H.ResetRefusal, match="does not match"):
        H.validate_bundle(app)


def test_helper_refuses_a_canonical_support_root_symlink(tmp_path):
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    outside.mkdir()
    root = home / "Library/Application Support/MOT Deck"
    root.parent.mkdir(parents=True)
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(H.ResetRefusal, match="not a real directory"):
        H.validate_support_root(root, home=home)


def test_identity_change_is_refused(tmp_path):
    home, root, app = _fixture(tmp_path)
    args = _args(home, root, app)
    old = root.with_name("old")
    root.rename(old)
    root.mkdir()
    with pytest.raises(H.ResetRefusal, match="identity changed"):
        H.execute(args)


def test_router_helper_evidence_binds_content_not_only_file_metadata(tmp_path):
    helper = tmp_path / "storage_reset_helper.py"
    helper.write_bytes(b"first-payload")
    st = os.lstat(helper)
    import hashlib
    evidence = {"path": str(helper), "dev": st.st_dev, "ino": st.st_ino,
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}
    assert STORAGE._same_helper(evidence) is True

    # Replacing bytes while restoring size and mtime defeats metadata-only evidence;
    # the content digest must still reject the helper before detached execution.
    helper.write_bytes(b"other-payload")
    os.utime(helper, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert STORAGE._same_helper(evidence) is False


def test_factory_helper_refuses_absent_or_stale_reprovision_seed(tmp_path):
    home, root, app = _fixture(tmp_path)
    args = _args(home, root, app, dry_run=True)
    args.mode = "factory-reset"
    args.expected_version = "1.5.90"
    with pytest.raises(H.ResetRefusal, match="no complete offline"):
        H.execute(args)
    _factory_seed(app, "1.5.89")
    with pytest.raises(H.ResetRefusal, match="does not match"):
        H.execute(args)
    _factory_seed(app, "1.5.90")
    assert H.execute(args)["dry_run"] is True
