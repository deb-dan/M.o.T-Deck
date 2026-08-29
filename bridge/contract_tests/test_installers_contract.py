"""INSTALLER CONTRACT — doctrine 2b ("the install path is a journey too") pinned.

Born from the 2026-08-29 install-path audit (Debi's ONLYOFFICE local-copy suspicion).
What that audit PROVED live, and this file keeps true:

  · every fresh path was walked on the real network against the pinned upstream:
    goose (full 90MB, both digests), the OO AI plugin (full, 4 files), the OO x2t.zip
    (full 12MB, sha256+sha512), the OO editor zip (HEAD content-length == pin size +
    first-1MiB byte-compare — a full 583MB re-pull was deliberately skipped as waste);
  · tamper → refusal with NO half-install, on all three digest installers;
  · truncated / corrupt / 404 downloads → refusal naming the pin, debris cleaned.

The EXECUTED tests below re-fire the refusal paths on every gate run using tiny
fixtures and a curl shim — no network, no real bundles, temp dests only (the
OO_DEST/OOP_DEST/GOOSE_DEST seams exist exactly for this; the live installs are never
touched). The source-order tests pin the discipline that cannot cheaply be executed.

Sibling coverage, referenced rather than duplicated:
  · bridge/tests/test_oo_lane.py       — editor fixture-zip mismatch walk, stamp schema
  · bridge/tests/test_oo_ai_lane.py    — plugin pins + install_state ladder
  · bridge/tests/test_goose_lane.py    — goose installer pins, 409 concurrency
  · test_gooseui_contract.py           — the Goose UI installer (v1.5.40 slice owns it,
                                          incl. the ~/Downloads local-copy ban)
  · bridge/tests/test_comfy_lane.py    — the ComfyUI model downloads (size+sha gate,
                                          .part states, two-writer fence)

Run: data/bridge-venv/bin/python -m pytest bridge/contract_tests/test_installers_contract.py -q
"""
import os
import platform
import re
import stat
import subprocess
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")

OO = os.path.join(SCRIPTS, "install_onlyoffice.sh")
PLUG = os.path.join(SCRIPTS, "install_oo_ai_plugin.sh")
GOOSE = os.path.join(SCRIPTS, "install_goose.sh")

_SRC = {}


def src(path: str) -> str:
    if path not in _SRC:
        with open(path, encoding="utf-8") as fh:
            _SRC[path] = fh.read()
    return _SRC[path]


# ── existence + the 2026-08-21 executability regression class ────────────────
def test_installers_exist_and_can_be_spawned():
    """The 2026-08-21 aider regression, pinned at ITS settled contract: the bridge
    spawns installers directly, and since the fix in bridge/core/procs.py::_script a
    script that lost its +x bit is run via bash instead of hard-crashing. So the
    invariant is: executable, OR the bash fallback still exists. (The strict repo-side
    +x fence — disk AND git index — is bridge/tests/test_script_hygiene.py; this suite
    also runs against SNAPSHOTS, where a copy may legitimately arrive bit-less and the
    fallback is exactly what keeps its Install button alive.)"""
    import glob
    paths = sorted(glob.glob(os.path.join(SCRIPTS, "install_*.sh")))
    assert paths, "no install_*.sh scripts found at all"
    bitless = [os.path.basename(p) for p in paths
               if not os.stat(p).st_mode & stat.S_IXUSR]
    if bitless:
        procs = src(os.path.join(ROOT, "bridge", "core", "procs.py"))
        assert '["/bin/bash", str(p), *args]' in procs, (
            f"{bitless} lost the +x bit AND _script's bash fallback is gone — "
            f"these Install buttons cannot start")


# ── digest constants present and well-formed ──────────────────────────────────
def test_onlyoffice_pins_are_two_digests_each():
    """AGPL condition #1 rests on TWO independent digests per zip: our measured sha256
    AND the sha512 CryptPad's own installer verifies. Both, well-formed, or the claim
    'unmodified upstream' degrades to an assertion."""
    s = src(OO)
    assert len(re.findall(r'^EDITOR_SHA256="[0-9a-f]{64}"$', s, re.M)) == 1
    assert len(re.findall(r'^EDITOR_SHA512="[0-9a-f]{128}"$', s, re.M)) == 1
    assert len(re.findall(r'^X2T_SHA256="[0-9a-f]{64}"$', s, re.M)) == 1
    assert len(re.findall(r'^X2T_SHA512="[0-9a-f]{128}"$', s, re.M)) == 1
    # No tag-only override: the pin is the hash, not the tag (header rule). The header
    # COMMENT names OO_EDITOR_TAG to explain its deliberate absence; what must never
    # appear is an actual expansion of it.
    assert "${OO_EDITOR_TAG" not in s


def test_plugin_pins_every_fetched_file():
    """Four files are fetched; four sha256 pins must exist (plugin + 3 SDK files),
    plus the commit pin (upstream publishes from a branch — a tag cannot pin it)."""
    s = src(PLUG)
    assert re.search(r'^COMMIT="[0-9a-f]{40}"', s, re.M)
    assert re.search(r'^PLUGIN_SHA256="[0-9a-f]{64}"$', s, re.M)
    for var in ("SDK_SHA_plugins_js", "SDK_SHA_plugins_ui_js", "SDK_SHA_plugins_css"):
        assert re.search(rf'^{var}="[0-9a-f]{{64}}"$', s, re.M), f"{var} missing/malformed"


def test_goose_pins_size_and_both_digests():
    """Size (names truncation better than a digest does), the archive digest, and the
    extracted binary's digest — two digests over DIFFERENT bytes."""
    s = src(GOOSE)
    assert re.search(r'^GOOSE_ASSET_SHA256="[0-9a-f]{64}"$', s, re.M)
    assert re.search(r'^GOOSE_BIN_SHA256="[0-9a-f]{64}"$', s, re.M)
    assert re.search(r'^GOOSE_ASSET_SIZE="\d+"$', s, re.M)


# ── verify BEFORE extract, stamp invalidated BEFORE the destructive rm ───────
def test_verify_precedes_extract_in_all_three():
    s = src(OO)
    assert s.index("sha256 MISMATCH") < s.index("unzip -q -o")
    assert s.index("sha512 MISMATCH") < s.index("unzip -q -o")
    s = src(PLUG)
    assert s.index("sha256 MISMATCH") < s.index("unzip -q -o")
    s = src(GOOSE)
    assert s.index("size MISMATCH") < s.index("tar xzf")
    assert s.index("sha256 MISMATCH") < s.index("tar xzf")


def test_stamp_dies_before_the_bundle_does():
    """2026-08-29 audit fix: an unzip that dies midway must not leave a stamp claiming
    the pinned hashes over a half-populated dist/. The stamp is removed before the
    first `rm -rf` and only rewritten after the landing checks pass."""
    s = src(OO)
    assert s.index('rm -f "$STAMP"') < s.index('rm -rf "$DV"'), \
        "install_onlyoffice.sh: stamp must be invalidated before dist/v9 is removed"
    s = src(PLUG)
    assert s.index('rm -f "$STAMP"') < s.index('rm -rf "$AIDIR"'), \
        "install_oo_ai_plugin.sh: stamp must be invalidated before ai/ is removed"


def test_llamacpp_cleans_debris_on_extract_failure():
    """2026-08-29 audit fix: a corrupt tarball (this script has no digest pin) must not
    survive to re-fail the next run."""
    s = src(os.path.join(SCRIPTS, "install_llamacpp.sh"))
    fail_branch = s.split("extraction failed")[1].split("fi")[0]
    assert '"$STAGE" "$TARBALL"' in fail_branch


# ── EXECUTED: tamper → refusal, no half-install (tiny fixtures, temp dests) ──
def _run(script, env_extra, cwd=ROOT, timeout=60):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run([script], env=env, cwd=cwd, timeout=timeout,
                          capture_output=True, text=True)


def test_editor_tamper_refusal_executed():
    with tempfile.TemporaryDirectory(prefix="inst-oo-") as td:
        zips = os.path.join(td, "zips")
        dest = os.path.join(td, "dest")
        os.makedirs(zips)
        # Wrong bytes under the right names. OO_OFFLINE turns the mismatch into a
        # refusal instead of a 583MB download inside a gate test.
        open(os.path.join(zips, "onlyoffice-editor.zip"), "wb").write(b"tampered")
        open(os.path.join(zips, "x2t.zip"), "wb").write(b"tampered")
        r = _run(OO, {"OO_DEST": dest, "OO_ZIP_DIR": zips, "OO_OFFLINE": "1"})
        assert r.returncode != 0
        assert "MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "INSTALLED"))
        assert not os.path.exists(os.path.join(dest, "dist"))


def test_plugin_tamper_refusal_executed():
    with tempfile.TemporaryDirectory(prefix="inst-plug-") as td:
        cache = os.path.join(td, "zips")
        dest = os.path.join(td, "dest")
        os.makedirs(cache)
        open(os.path.join(cache, "ai.plugin"), "wb").write(b"tampered")
        r = _run(PLUG, {"OOP_DEST": dest, "OOP_ZIP_DIR": cache, "OOP_OFFLINE": "1"})
        assert r.returncode != 0
        assert "MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "INSTALLED"))
        assert not os.path.exists(os.path.join(dest, "ai"))


@pytest.mark.skipif(platform.system() != "Darwin" or platform.machine() != "arm64",
                    reason="install_goose.sh refuses non-arm64-macOS by design")
def test_goose_truncated_download_refusal_executed():
    """The nasty case walked live in the audit: curl exits 0 having written a partial
    file (CDN truncation). The size gate must refuse, delete the debris, and leave no
    binary. A curl SHIM stands in for the network — the pinned URL is never touched."""
    with tempfile.TemporaryDirectory(prefix="inst-goose-") as td:
        shim = os.path.join(td, "shim")
        dest = os.path.join(td, "dest")
        ws = os.path.join(td, "ws")
        os.makedirs(shim)
        curl = os.path.join(shim, "curl")
        with open(curl, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/bash\nout=""; prev=""\n'
                     'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
                     '[ -n "$out" ] && head -c 4096 /dev/zero > "$out"\nexit 0\n')
        os.chmod(curl, 0o755)
        r = _run(GOOSE, {"GOOSE_DEST": dest, "GOOSE_WS": ws,
                         "PATH": f"{shim}:/usr/bin:/bin:/usr/sbin:/sbin"}, timeout=120)
        assert r.returncode != 0
        assert "size MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "bin", "goose"))
        assert not os.path.exists(os.path.join(dest, "goose-aarch64-apple-darwin.tar.gz"))


# ── local-copy sourcing stays an explicit, digest-checked OVERRIDE ────────────
def test_cached_zip_reuse_is_never_a_trust_boundary():
    """OO_ZIP_DIR / OOP_ZIP_DIR / a cached goose archive may skip the DOWNLOAD, never
    the DIGEST: every reuse path re-hashes before use (the audit's core question —
    local sourcing is a bandwidth convenience, not an install-path exemption)."""
    s = src(OO)
    assert 'ZIPS="${OO_ZIP_DIR:-$DEST/zips}"' in s
    reuse = s.split('if [[ -s "$dest" ]]', 1)[1]
    assert 'sha256_of "$dest"' in reuse.split("fi", 1)[0] or "sha256_of" in reuse[:400]
    # the sha512 pass runs OUTSIDE fetch_verified so the cached path gets it too
    assert "Outside fetch_verified deliberately" in s
    s = src(GOOSE)
    assert 'sha256_of "$TGZ"' in s.split("reusing", 1)[0].split("A cached archive", 1)[-1] \
        or '"$(sha256_of "$TGZ")" == "$GOOSE_ASSET_SHA256"' in s
