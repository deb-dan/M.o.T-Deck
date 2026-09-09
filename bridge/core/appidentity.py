"""Python caller for MOT Deck's canonical installed-bundle resolver.

Discovery policy belongs to ``scripts/app_bundle_identity.sh``.  The bridge calls that
same resolver instead of maintaining a second Finder-name/identity implementation.
The detached reset helper still revalidates the one returned bundle immediately before
moving it; that is a final-target safety check, not another discovery policy.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tarfile


class AppIdentityError(RuntimeError):
    pass


_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def embedded_seed_version(app_path: Path) -> str:
    """Return the exact FAT seed version that a factory reset would provision.

    Ordinary shipping updates the live snapshot and native shell, while the offline
    seed belongs to a full FAT build. Treating those as interchangeable can roll a
    freshly reset installation backwards, so factory reset is unavailable unless the
    installed bundle carries a readable matching seed.
    """
    resources = Path(app_path) / "Contents/Resources"
    seed = resources / "motdeck-seed-fat.tar.gz"
    provisioner = resources / "firstrun_fat.sh"
    if seed.is_symlink() or not seed.is_file() or provisioner.is_symlink() \
            or not provisioner.is_file():
        raise AppIdentityError("the installed app has no complete offline factory-reset seed")
    try:
        with tarfile.open(seed, "r:gz") as archive:
            member = next((archive.getmember(name) for name in ("./VERSION", "VERSION")
                           if name in archive.getnames()), None)
            if member is None or not member.isfile() or member.size > 64:
                raise AppIdentityError("the installed factory-reset seed has no valid VERSION")
            handle = archive.extractfile(member)
            raw = handle.read(65) if handle is not None else b""
    except (OSError, tarfile.TarError) as exc:
        raise AppIdentityError("the installed factory-reset seed is unreadable") from exc
    try:
        version = raw.decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise AppIdentityError("the installed factory-reset seed has an invalid VERSION") from exc
    if not _VERSION_RE.fullmatch(version):
        raise AppIdentityError("the installed factory-reset seed has an invalid VERSION")
    return version


def require_current_factory_seed(app_path: Path, expected_version: str) -> str:
    version = embedded_seed_version(app_path)
    if version != str(expected_version or "").strip():
        raise AppIdentityError(
            f"the installed factory-reset seed is v{version}, but the live app is "
            f"v{expected_version}; install the current FAT DMG before resetting")
    return version


def resolve_installed_bundle(*, roots: tuple[Path, ...] | None = None,
                             explicit: str | None = None) -> Path:
    script = Path(__file__).resolve().parents[2] / "scripts/app_bundle_identity.sh"
    if not script.is_file():
        raise AppIdentityError("the canonical installed-app identity resolver is missing")
    selected_roots = roots or (Path("/Applications"), Path.home() / "Applications")
    command = (
        'source "$1"; shift; '
        'MOT_DECK_APP_RESOLVE_QUIET=1 motdeck_resolve_installed_app --roots "$@" '
        '|| exit $?; printf "%s" "$MOT_DECK_RESOLVED_APP"'
    )
    env = dict(os.environ)
    if explicit is not None:
        if explicit:
            env["MOT_DECK_APP_PATH"] = explicit
        else:
            env.pop("MOT_DECK_APP_PATH", None)
    result = subprocess.run(
        ["/bin/bash", "-c", command, "motdeck-app-resolver", str(script),
         *(str(root) for root in selected_roots)],
        text=True, capture_output=True, env=env, timeout=30, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        reasons = {
            2: "MOT_DECK_APP_PATH is not a valid local.motdeck.app bundle",
            3: "no installed local.motdeck.app bundle was found",
            4: "more than one installed local.motdeck.app bundle was found",
        }
        raise AppIdentityError(reasons.get(result.returncode,
                               "installed MOT Deck bundle discovery failed closed"))
    return Path(result.stdout)
