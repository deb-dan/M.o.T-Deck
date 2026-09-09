from pathlib import Path
import io
import os
import plistlib
import tarfile

import pytest

from bridge.core.appidentity import (AppIdentityError, embedded_seed_version,
                                     require_current_factory_seed,
                                     resolve_installed_bundle)


def _bundle(root: Path, name: str, *, bundle_id: str = "local.motdeck.app") -> Path:
    app = root / name
    binary = app / "Contents/MacOS/MOTDeck"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    with (app / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": bundle_id,
                       "CFBundleExecutable": "MOTDeck"}, handle)
    return app


def test_python_reset_caller_uses_the_canonical_shell_identity_resolver(tmp_path):
    app = _bundle(tmp_path, "A Finder Rename.app")
    assert resolve_installed_bundle(roots=(tmp_path,), explicit="") == app.resolve()


def test_identity_discovery_fails_closed_on_ambiguity_and_bad_explicit_path(tmp_path):
    _bundle(tmp_path, "One.app")
    _bundle(tmp_path, "Two.app")
    with pytest.raises(AppIdentityError, match="more than one"):
        resolve_installed_bundle(roots=(tmp_path,), explicit="")
    with pytest.raises(AppIdentityError, match="MOT_DECK_APP_PATH"):
        resolve_installed_bundle(roots=(tmp_path,), explicit=str(tmp_path / "missing.app"))


def test_symlink_aliases_deduplicate_to_one_real_bundle(tmp_path):
    app = _bundle(tmp_path, "Real.app")
    os.symlink(app, tmp_path / "Alias.app")
    assert resolve_installed_bundle(roots=(tmp_path,), explicit="") == app.resolve()


def _factory_seed(app: Path, version: str) -> None:
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    (resources / "firstrun_fat.sh").write_text("#!/bin/sh\n")
    payload = (version + "\n").encode()
    info = tarfile.TarInfo("./VERSION")
    info.size = len(payload)
    with tarfile.open(resources / "motdeck-seed-fat.tar.gz", "w:gz") as archive:
        archive.addfile(info, io.BytesIO(payload))


def test_factory_reset_requires_a_current_embedded_fat_seed(tmp_path):
    app = _bundle(tmp_path, "MOT Deck.app")
    with pytest.raises(AppIdentityError, match="no complete offline"):
        embedded_seed_version(app)
    _factory_seed(app, "1.5.89")
    assert embedded_seed_version(app) == "1.5.89"
    with pytest.raises(AppIdentityError, match="live app is v1.5.90"):
        require_current_factory_seed(app, "1.5.90")
    assert require_current_factory_seed(app, "1.5.89") == "1.5.89"
