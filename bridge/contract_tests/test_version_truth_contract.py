"""ONE VERSION NUMBER CONTRACT — U56, 2026-09-02.

THE INCIDENT. The deck's Version tile showed **0.1.0 at release 1.5.72**. There were two
version numbers in the tree and the app displayed the dead one:

  · `harness.yaml` had `version: "0.1.0"  # bump on release`. Nothing bumped it in 72
    releases, and `routers/version.py` read it and NOTHING ELSE.
  · the top-level `VERSION` file held `1.5.72` — QA bumps it in the same commit as every
    slice, ship.sh and every commit message name it — and NO RUNTIME CODE READ IT.

It also poisoned the update check: `_assemble_update` compared a GitHub release tag
against 0.1.0, so any tag on the repo would have read as "newer" for ever.

THE FIX IS SINGLE-SOURCING, NOT SYNCING: `VERSION` is the release truth, the runtime
reads it (`core/procs.harness_version`), the update check compares against it, and
`harness.yaml version:` is gone. What this file pins:

  1. `VERSION` exists, is readable, and parses as a release number.
  2. `harness_version()` returns exactly its contents.
  3. NO runtime module reads a version out of harness.yaml, and the repo manifest has no
     top-level `version:` key to read (the shape of the whole bug: a second copy of a
     fact is a second answer).
  4. ship.sh copies VERSION into the snapshot — without that line the app's number
     freezes at whatever release last rebuilt the fat DMG, which is the same lie with a
     different number.
  5. The endpoint answers with the file's value, and an ABSENT VERSION file degrades to
     "unknown" + a sentence rather than a guess.
  6. The update comparison never reports an update it cannot prove: unknown local
     version → no; unparseable tag → no; older/equal tag → no.

Run: data/bridge-venv/bin/python -m pytest \
       bridge/contract_tests/test_version_truth_contract.py -q
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _code(path):
    return "\n".join(ln for ln in _read(path).splitlines()
                     if not ln.lstrip().startswith("#"))


# ── 1-2. the file is the truth, and the reader returns it ────────────────────
def test_version_file_exists_and_is_a_release_number():
    raw = _read(os.path.join(ROOT, "VERSION")).strip()
    assert raw, "the VERSION file is empty — it is the one release marker"
    assert re.fullmatch(r"\d+\.\d+\.\d+", raw), \
        f"VERSION should be a dotted release number, got {raw!r}"


def test_harness_version_returns_the_version_file_verbatim():
    from bridge.core.procs import harness_version
    assert harness_version() == _read(os.path.join(ROOT, "VERSION")).strip()


# ── 3. no second copy of the fact ────────────────────────────────────────────
def test_harness_yaml_has_no_version_key():
    import yaml
    cfg = yaml.safe_load(_read(os.path.join(ROOT, "harness.yaml"))) or {}
    assert "version" not in cfg, (
        "harness.yaml grew a `version:` key again. That key IS U56: it was frozen at "
        "0.1.0 for 72 releases while the app displayed it. The release number lives in "
        "the top-level VERSION file, and bridge/core/procs.py::harness_version is its "
        "one reader.")


def test_no_runtime_module_reads_a_version_out_of_the_manifest():
    """The reader is what made the dead key dangerous — so the reader is what is fenced.
    Scans every module the bridge runs (tests name things on purpose)."""
    bridge = os.path.join(ROOT, "bridge")
    skip = (os.path.join(bridge, "tests"), os.path.join(bridge, "contract_tests"))
    bad = []
    pat = re.compile(r"""(?:cfg\(\)|\bc\b|\bconf\b)\s*\.\s*get\(\s*["']version["']""")
    for base, _dirs, files in os.walk(bridge):
        if "__pycache__" in base or base.startswith(skip):
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(base, f)
            for m in pat.finditer(_code(p)):
                bad.append(f"{os.path.relpath(p, ROOT)}: {m.group(0)!r}")
    assert not bad, ("a runtime module is reading a version out of harness.yaml again "
                     "(U56): " + "; ".join(bad))


# ── 4. the number ships with the code it names ───────────────────────────────
def test_ship_copies_the_version_file_into_the_snapshot():
    code = _code(os.path.join(ROOT, "scripts", "ship.sh"))
    assert re.search(r'cp\s+"\$ROOT/VERSION"\s+"\$DST/VERSION"', code), (
        "ship.sh no longer copies VERSION into the snapshot. ROOT for the app IS the "
        "snapshot, so without this the tile freezes at the release that last rebuilt "
        "the fat seed — U56 again, wearing a newer number.")


def test_the_fat_seed_still_carries_version():
    code = _code(os.path.join(ROOT, "scripts", "build_app.sh"))
    assert "VERSION" in code, "the fat seed stopped shipping VERSION (v1.5.70 fix)"


# ── 5. the endpoint, and graceful absence ────────────────────────────────────
def test_api_version_serves_the_version_file_and_degrades_honestly(tmp_path, monkeypatch):
    from bridge.core import procs
    from bridge.routers import version as vmod

    monkeypatch.setattr(procs, "ROOT", tmp_path)
    (tmp_path / "harness.yaml").write_text("components: {}\n")

    (tmp_path / "VERSION").write_text("9.9.9\n")
    assert procs.harness_version() == "9.9.9"

    (tmp_path / "VERSION").unlink()
    assert procs.harness_version() == "", "an absent VERSION must read as unknown"
    # The route is async and hits the network; the two pure halves it is made of are
    # what carry the contract, so they are what is asserted (the live endpoint is
    # walked in the report, not here).
    assert vmod.VERSION_UNKNOWN_NOTE and "ship.sh" in vmod.VERSION_UNKNOWN_NOTE, \
        "the unknown-version case must tell the user how to fix it"


# ── 6. the update check may never claim an update it cannot prove ────────────
def test_update_comparison_is_conservative():
    from bridge.routers.version import _assemble_update as u

    tag = {"tag_name": "v1.5.73", "html_url": "http://x"}
    assert u("1.5.72", tag)["available"] is True, "a genuinely newer tag must show"
    assert u("1.5.73", tag)["available"] is False, "the same version is not an update"
    assert u("1.5.74", tag)["available"] is False, "an OLDER tag is not an update"
    assert u("1.5", {"tag_name": "1.5.0", "html_url": ""})["available"] is False, \
        "1.5 and 1.5.0 are the same release — zero-pad, do not compare tuple lengths"

    # THE ORIGINAL BUG: 0.1.0 (harness.yaml's frozen key) vs any tag → "newer for ever".
    # It cannot recur through the caller, but the helper must also refuse to guess when
    # the local version is genuinely UNKNOWN (a pre-v1.5.70 install with no VERSION).
    for unknown in (None, "", "   "):
        out = u(unknown, tag)
        assert out["available"] is False, f"guessed an update against {unknown!r}"
        assert "no local version" in out.get("note", "")

    # An unparseable tag used to fall through to `latest != local`, i.e. ANY weird tag
    # became an update available. Unparseable now means uncomparable, and says so.
    weird = u("1.5.72", {"tag_name": "nightly", "html_url": ""})
    assert weird["available"] is False and "cannot compare" in weird.get("note", "")

    # A suffixed tag still compares on its numeric head rather than being discarded.
    assert u("1.5.72", {"tag_name": "v1.5.80-beta1", "html_url": ""})["available"] is True
    assert u("1.5.72", {"tag_name": "v1.5.70-beta1", "html_url": ""})["available"] is False

    # No release at all → "unavailable", never an update.
    assert u("1.5.72", None) == {"available": False, "latest": None, "note": "unavailable"}
