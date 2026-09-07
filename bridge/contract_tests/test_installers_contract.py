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
DSH = os.path.join(SCRIPTS, "install_deepseek.sh")
NODE = os.path.join(SCRIPTS, "ensure_node.sh")
LLAMA = os.path.join(SCRIPTS, "install_llamacpp.sh")
BUN = os.path.join(SCRIPTS, "ensure_bun.sh")
SEARX = os.path.join(SCRIPTS, "install_searxng.sh")
MUSIC = os.path.join(SCRIPTS, "install_music.sh")
OPENCODE = os.path.join(SCRIPTS, "install_opencode.sh")
VENDOR_ASSETS = os.path.join(SCRIPTS, "fetch_vendor_assets.sh")
FIRSTRUN = os.path.join(SCRIPTS, "firstrun.sh")

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


# ── the DeepSeek lane (S34): a THIRD install shape — an npm dependency tree ──
# The three above pin BYTES (a digest per file). This one cannot: npm resolves a
# transitive tree of 455 packages behind one pinned top-level version, and the honest
# contract is therefore different in kind. These rows pin what CAN be pinned, and the
# row that matters most is the last one, which pins the ADMISSION.
def test_deepseek_pins_the_top_level_and_refuses_a_moved_version():
    s = src(DSH)
    assert "dsh_pin" in s, "the pin is single-sourced in motdeck.yaml, not inline"
    assert "--save-exact" in s, "the top-level dependency is written exactly, not as ^"
    # ⚠️ THE PRE-FLIGHT THAT REPLACES A DIGEST. npm verifies dist.integrity itself, but
    # only against what the registry serves NOW; reading the metadata FIRST and
    # refusing on a version mismatch is what turns "upstream unpublished or re-tagged
    # this version" into a stop instead of a silently different install.
    assert 'meta_ver" == "$pin' in s or '"$meta_ver" == "$pin"' in s
    assert s.index("checking npm metadata") < s.index("installing …"), (
        "the metadata check must precede the install, not follow it")
    assert "npm update" not in "\n".join(
        ln for ln in s.splitlines()
        if not ln.strip().startswith(("#", "say ", "echo "))), (
        "a floating update in an install script defeats the pin entirely")


def test_deepseek_uses_the_lockfile_when_it_has_one():
    """`npm ci` is byte-reproducible but only off an existing lock, and the first
    install has none. BOTH halves must be present, or the second install of the same
    pin silently re-resolves the tree."""
    s = src(DSH)
    assert "npm ci" in s and "package-lock.json" in s
    assert "npm install" in s, "…and the first-install path that WRITES the lock"


def test_deepseek_verifies_the_runtime_before_it_spends_seven_minutes():
    """⚠️ THE PUBLISHED PACKAGE DECLARES NO `engines` FIELD, so npm enforces nothing
    and a too-old Node fails at RUN time with an error nobody can place. The preflight
    is the only check there is."""
    s = src(DSH)
    assert "ensure_node.sh" in s
    assert s.index("ensure_node.sh") < s.index("installing …"), (
        "resolve the runtime BEFORE the long download, not after")
    assert "proves it RUNS" in s or "does not run" in s, (
        "and prove the install executes before claiming success")


def test_ensure_node_verifies_before_extract_like_the_other_three():
    """The one place this lane DOES pin bytes, and it obeys the same ordering rule the
    three installers above do."""
    s = src(NODE)
    assert s.index("sha256 MISMATCH") < s.index("tar xJf"), (
        "a mismatched node tarball must stop before anything is unpacked")
    assert s.index("SHASUMS256.txt") < s.index("tar xJf")
    # …and it cleans up after itself, the install_llamacpp.sh rule.
    assert s.count('rm -rf "$STAGE"') >= 3, (
        "every failure path must remove the staging dir, or a corrupt download "
        "survives to re-fail the next run")


def test_the_checksum_source_is_stated_rather_than_implied():
    """⚠️ THE HONEST-LIMIT ROW, and it is the reason this file gained a section rather
    than a line. ensure_node.sh fetches SHASUMS256.txt from nodejs.org instead of
    carrying a hardcoded digest, which is WEAKER than the three installers above: it
    catches a corrupt, truncated or mismatched-asset download but not a compromised
    nodejs.org. That trade may be made; it may not be made SILENTLY. The comment is
    the artefact under test."""
    s = src(NODE)
    assert "does NOT defend against a compromised nodejs.org" in s, (
        "the weaker guarantee must be written down where the guarantee is made")


def test_llamacpp_cleans_debris_on_extract_failure():
    """2026-08-29 audit fix: a corrupt tarball must not survive to re-fail."""
    s = src(LLAMA)
    fail_branch = s.split("extraction failed")[1].split("fi")[0]
    assert '"$STAGE" "$TARBALL"' in fail_branch


# ── A11-A13: every remaining floating/download-only source is immutable ──────
def test_searxng_fetches_and_verifies_the_manifest_commit():
    manifest = src(os.path.join(ROOT, "motdeck.yaml"))
    assert re.search(r"^  searxng:\n(?:^    .*\n)*?^    pin: [0-9a-f]{40}(?:\s|$)",
                     manifest, re.M)
    s = src(SEARX)
    assert 'fetch --depth 1 origin "$PIN"' in s
    assert 'checkout -q --detach FETCH_HEAD' in s
    assert '[[ "$HAVE" == "$PIN" ]]' in s
    assert "git pull" not in s and "--depth 1 https://github.com" not in s
    assert "rm -rf vendor/searxng" not in s
    assert "exists but is not a git checkout; refusing" in s


def test_acestep_weights_use_the_recorded_snapshot_not_huggingface_main():
    manifest = src(os.path.join(ROOT, "motdeck.yaml"))
    assert re.search(r'^  music_acestep_gguf_pin: "[0-9a-f]{40}"$', manifest, re.M)
    s = src(MUSIC)
    assert "music_acestep_gguf_pin" in s
    assert "revision=sys.argv[3]" in s
    assert '*/snapshots/"$gguf_pin"/"$f"' in s, (
        "an old managed symlink must not be mistaken for the newly pinned snapshot")
    assert '&& -e "$models/$f"' in s, (
        "a broken symlink into the right snapshot must be fetched again, not called present")
    assert 'refusing to replace non-symlink model file' in s


def test_acestep_native_build_is_relocatable_across_live_root_and_fat_seed():
    s = open(os.path.join(ROOT, "scripts", "install_music.sh"), encoding="utf-8").read()
    assert "acestep_rpath_ok" in s
    assert '"$cmake_bin" --fresh -S "$src" -B "$build"' in s
    assert "-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON" in s
    assert "-DCMAKE_INSTALL_RPATH=@loader_path" in s
    assert '[[ "$paths" == "@loader_path" ]]' in s
    assert "relocatable ace-lm launch check failed" in s
    assert "relocatable ace-synth launch check failed" in s
    assert "Application Support/MOT Deck/data/acestep/src/build" not in s
    assert 'mv "$build" "$backup"' in s
    assert 'mv "$backup" "$build"' in s
    assert 'prior_sha="$have"' in s
    assert 'git -C "$src" checkout -q "$prior_sha"' in s
    assert 'refusing to move its pin' in s
    assert 'build_failure="relocatable rpath validation"' in s


def test_comfyui_fresh_base_has_every_directory_v0345_reads_at_boot():
    """An existing base already has these paths and masks the first-install failure.
    ComfyUI v0.34.5 enumerates custom_nodes before it creates the directory itself."""
    s = src(os.path.join(SCRIPTS, "install_component.sh"))
    assert 'data/comfyui"/{custom_nodes,models,output,input,user,temp}' in s
    assert s.index('data/comfyui"/{custom_nodes,models,output,input,user,temp}') \
        < s.index('comfyui base directory')


def test_llama_and_bun_verify_recorded_sha256_before_unpacking():
    llama = src(LLAMA)
    assert re.search(r"llamacpp_sha256", llama)
    assert llama.index("sha256 MISMATCH") < llama.index("tar xzf")
    bun = src(BUN)
    for key in ("bun_darwin_arm64_sha256", "bun_darwin_x64_sha256",
                "bun_linux_arm64_sha256", "bun_linux_x64_sha256"):
        assert key in bun
    assert bun.index("sha256 MISMATCH") < bun.index("unzip -q -o")


def test_opencode_requires_recorded_sha256_and_registry_sha512_before_extract():
    s = src(OPENCODE)
    assert "opencode_darwin_arm64_sha256" in s
    assert "opencode_darwin_x64_sha256" in s
    assert 'integrity_expect' in s and 'sha512-' in s
    assert s.index("recorded SHA-256 and npm SHA-512 verified") < s.index("tar xzf")
    assert "extracting unverified" not in s


def test_every_browser_asset_has_a_digest_and_cached_bytes_are_rechecked():
    s = src(VENDOR_ASSETS)
    entries = re.findall(r'^  "([^|]+)\|([0-9a-f]{64})\|', s, re.M)
    assert len(entries) == 20, f"expected all 20 browser assets pinned, got {len(entries)}"
    assert len({name for name, _ in entries}) == len(entries)
    cached = s[s.index('if [[ $FORCE -eq 0 && -s "$out" ]]'):s.index('echo "[vendor] fetching', s.index('if [[ $FORCE -eq 0 && -s "$out" ]]'))]
    assert "shasum -a 256" in cached and '"$got" == "$expected"' in cached
    assert s.index('shasum -a 256 "$out.tmp"') < s.index('mv "$out.tmp" "$out"')


def test_portable_firstrun_verifies_the_installer_script_before_execution():
    manifest = src(os.path.join(ROOT, "motdeck.yaml"))
    assert re.search(r'^  uv_installer_sha256: "[0-9a-f]{64}"$', manifest, re.M)
    s = src(FIRSTRUN)
    assert 'refusing an unpinned installer' in s
    assert 'uv installer sha256 MISMATCH' in s
    assert s.index('shasum -a 256 "$UV_INSTALLER"') < s.index(
        'sh "$UV_INSTALLER"')
    assert 'astral.sh/uv/install.sh' not in s


# ── EXECUTED: tamper → refusal, no half-install (tiny fixtures, temp dests) ──
def _run(script, env_extra, cwd=ROOT, timeout=60):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run([script], env=env, cwd=cwd, timeout=timeout,
                          capture_output=True, text=True)


def _tampering_curl(directory):
    path = os.path.join(directory, "curl")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write('#!/bin/bash\nout=""; prev=""\n'
                 'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done\n'
                 '[ -n "$out" ] && printf tampered > "$out"\nexit 0\n')
    os.chmod(path, 0o755)
    return path


def test_llamacpp_tamper_refusal_executes_before_extract_or_replacement():
    with tempfile.TemporaryDirectory(prefix="inst-llama-") as td:
        shim = os.path.join(td, "shim")
        dest = os.path.join(td, "dest")
        os.makedirs(shim)
        _tampering_curl(shim)
        r = _run(LLAMA, {"LLAMACPP_DEST": dest,
                         "PATH": f"{shim}:/usr/bin:/bin:/usr/sbin:/sbin"})
        assert r.returncode != 0
        assert "sha256 MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "build", "bin", "llama-server"))


def test_bun_tamper_refusal_executes_before_unzip_or_replacement():
    with tempfile.TemporaryDirectory(prefix="inst-bun-") as td:
        shim = os.path.join(td, "shim")
        dest = os.path.join(td, "dest")
        os.makedirs(shim)
        _tampering_curl(shim)
        r = _run(BUN, {"BUN_DEST": dest, "BUN_IGNORE_PATH": "1",
                       "PATH": f"{shim}:/usr/bin:/bin:/usr/sbin:/sbin"})
        assert r.returncode != 0
        assert "sha256 MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "bin", "bun"))


def test_cached_browser_asset_tamper_is_refused_without_network_or_overwrite():
    with tempfile.TemporaryDirectory(prefix="inst-assets-") as td:
        babel = os.path.join(td, "babel.min.js")
        with open(babel, "wb") as fh:
            fh.write(b"user-visible-corruption")
        before = open(babel, "rb").read()
        r = _run(VENDOR_ASSETS, {"VENDOR_ASSET_DEST": td})
        assert r.returncode != 0
        assert "cached babel.min.js" in (r.stdout + r.stderr)
        assert open(babel, "rb").read() == before


def test_portable_firstrun_refuses_a_tampered_installer_before_shell_execution():
    with tempfile.TemporaryDirectory(prefix="inst-uv-") as td:
        shim = os.path.join(td, "shim")
        dest = os.path.join(td, "uv-bin")
        os.makedirs(shim)
        _tampering_curl(shim)
        brew = os.path.join(shim, "brew")
        with open(brew, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/bash\nexit 0\n")
        os.chmod(brew, 0o755)
        r = _run(FIRSTRUN, {"UV_DEST": dest, "UV_IGNORE_PATH": "1",
                            "PATH": f"{shim}:/usr/bin:/bin:/usr/sbin:/sbin"})
        assert r.returncode != 0
        assert "uv installer sha256 MISMATCH" in (r.stdout + r.stderr)
        assert not os.path.exists(os.path.join(dest, "uv"))


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
