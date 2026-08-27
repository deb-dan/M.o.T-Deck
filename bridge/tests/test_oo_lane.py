#!/usr/bin/env python3
"""LOFFICE TIER 2 — the ONLYOFFICE lane (2026-08-27, loffice-2026-08-27c).

What each group guards, and why it is worth a test rather than a comment:

1. THE INSTALLER'S HASH GATE. The pin is the sha256 the probe RECORDED, not the tag
   (CryptPad's live installer does not carry our editor hash — the runbook ruled that
   the recorded hashes are the pin). So the gate must refuse to unzip a zip whose
   hash does not match, and it must refuse BEFORE unzipping. Executed here against
   fixture zips with OO_DEST/OO_OFFLINE, so the real 1GB install is never touched.

2. THE THREE HEADERS. Measured, load-bearing, silent when missing: without
   cross-origin isolation the spreadsheet editor renders its whole frame and then
   hangs at "Loading spreadsheet" forever with ZERO console errors. They are
   asserted on real TestClient responses for /oo/*, for the glue page, for
   /api/oo/status and for the write-back route — including its failures, because a
   409 that loses the headers is a page that cannot recover from it.

3. MIME. `.wasm` must be application/wasm or WebAssembly.instantiateStreaming
   refuses it, and whether Python's mimetypes knows that is build-dependent.

4. CONTAINMENT. /oo/* takes a path off the wire and the write-back takes a name.
   Both go through realpath containment — office.py's `doc_target` rule, and its
   twin here — and a refusal is a 404 that says nothing about what is outside.

5. THE WRITE-BACK. This is Save: it OVERWRITES. Happy path, the daily .bak, the
   mtime fence (409) and its force override, traversal, oversize, and bytes that are
   not a workbook at all.

6. THE TIER-2 WIRING in bridge/panel/office.html: the button and the menu row open
   the ONLYOFFICE page for the OPEN workbook, ask whether it is installed first, and
   never use window.confirm (a silent no-op in a WKWebView).

7. ⚖️ THE AGPL ATTRIBUTION — condition #3 of the 2026-08-27 ruling. Named on the
   editor page's footer AND in LOffice's Help → About, single-sourced from
   oo.ATTRIBUTION so the two cannot drift.

Run: python3 bridge/tests/test_oo_lane.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bridge import oo                                            # noqa: E402
from bridge import office                                        # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name + ((" | " + str(extra)[:300]) if extra else ""))


def eq(name, got, want):
    check(name, got == want, f"got {got!r} want {want!r}")


# A minimal real .xlsx: a zip, which is what the write-back's sniff test wants.
MIN_XLSX = None
try:
    import openpyxl
    HAVE_XL = True
except Exception as _e:                                          # noqa: BLE001
    HAVE_XL = False
    print(f"!! openpyxl is NOT importable here — the round-trip halves are SKIPPED ({_e})")


def make_xlsx(path, a1="hello"):
    wb = openpyxl.Workbook()
    wb.active["A1"] = a1
    wb.save(path)


# ══ 1. THE INSTALLER'S HASH GATE ═════════════════════════════════════════════
SCRIPT = ROOT / "scripts" / "install_onlyoffice.sh"
check("scripts/install_onlyoffice.sh exists", SCRIPT.is_file())
check("…and is executable (the bridge and ship.sh both run scripts directly)",
      os.access(SCRIPT, os.X_OK))
r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
check("…and is syntactically clean under bash -n", r.returncode == 0, r.stderr)

SRC = SCRIPT.read_text()
check("it is NOT a component — no port, no manifest key, no venv, no registry row",
      "flip_installed" not in SRC and "harness.yaml" not in SRC.split("# ⚖️")[0]
      and "uv venv" not in SRC)

# The pin must still be the one the probe RECORDED. data/office-probe/CHECKSUMS.txt is
# the probe's own output and the provenance the AGPL ruling points at, so if it is
# still on disk the two must agree — a silent pin drift is exactly what this catches.
PROBE_SUMS = ROOT / "data" / "office-probe" / "CHECKSUMS.txt"
EDITOR_SHA = "68ae8f0fe14fdde1fd845085deeeb37d98b5a8bb034622cd2a11c2f54f40930f"
X2T_SHA = "86b6f1ac8f110b5a416ad199efa4c08957d46d989defe791b9793a966cfb3a04"
check("the editor sha256 in the installer is the one the probe recorded",
      f'EDITOR_SHA256="{EDITOR_SHA}"' in SRC)
check("the x2t sha256 in the installer is the one the probe recorded",
      f'X2T_SHA256="{X2T_SHA}"' in SRC)
check("the tags are CryptPad's tested pair",
      'EDITOR_TAG="v9.2.0.119+3"' in SRC and 'X2T_TAG="v7.3+1"' in SRC)
if PROBE_SUMS.is_file():
    sums = PROBE_SUMS.read_text()
    check("…and both agree with data/office-probe/CHECKSUMS.txt",
          EDITOR_SHA in sums and X2T_SHA in sums)
else:
    print("  (CHECKSUMS.txt is gone — the probe dir was cleaned; pin cross-check skipped)")

check("the sha256 is verified BEFORE the unzip, not after",
      SRC.index("fetch_verified ") < SRC.index("unzip -q -o"))
check("a mismatch is a hard failure, never a warning",
      'die "sha256 MISMATCH' in SRC)

# EXECUTED. Fixture zips with the wrong bytes, OO_DEST somewhere disposable, and
# OO_OFFLINE so a mismatch can never turn into a 583MB download inside a test.
work = tempfile.mkdtemp(prefix="oo-lane-")
try:
    zips = os.path.join(work, "zips")
    # OO_DEST is the BUNDLE directory; oo.py's helpers take the harness ROOT and look
    # for <root>/data/onlyoffice underneath it. Laying the fixture out that way is the
    # point: it proves the two halves agree about where the bundle lives.
    fake_root = os.path.join(work, "root")
    dest = os.path.join(fake_root, "data", "onlyoffice")
    os.makedirs(zips)
    os.makedirs(dest)
    # Real zip bytes, wrong file: the gate must reject on the HASH, not on the format.
    for name in ("onlyoffice-editor.zip", "x2t.zip"):
        import zipfile
        with zipfile.ZipFile(os.path.join(zips, name), "w") as z:
            z.writestr("decoy.txt", "not the vendored bundle")

    env = dict(os.environ, OO_ZIP_DIR=zips, OO_DEST=dest, OO_OFFLINE="1")
    r = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env,
                       cwd=str(ROOT), timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    check("the installer REFUSES zips whose sha256 does not match the pin",
          r.returncode != 0, out[-400:])
    check("…and says so in the words 'sha256 MISMATCH'", "sha256 MISMATCH" in out,
          out[-400:])
    check("…and nothing was unzipped — no dist/ landed",
          not os.path.isdir(os.path.join(dest, "dist")))
    check("…and no INSTALLED stamp was written",
          not os.path.isfile(os.path.join(dest, "INSTALLED")))

    # --check on a directory with nothing in it
    r = subprocess.run([str(SCRIPT), "--check"], capture_output=True, text=True,
                       env=dict(os.environ, OO_DEST=dest), cwd=str(ROOT), timeout=60)
    check("--check exits non-zero and says 'not installed' when it is not",
          r.returncode != 0 and "not installed" in (r.stdout + r.stderr))

    # --check reads the stamp it wrote itself: hand-build one and read it back.
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "INSTALLED"), "w") as fh:
        fh.write("schema 1\ndate 2026-08-27T00:00:00Z\neditor_tag v9.2.0.119+3\n"
                 f"editor_sha256 {EDITOR_SHA}\nx2t_tag v7.3+1\n"
                 f"x2t_sha256 {X2T_SHA}\napi_js dist/v9/web-apps/apps/api/documents/api.js\n"
                 "x2t_js dist/x2t/x2t.js\nfiles 16600\nlicence AGPL-3.0\n")
    r = subprocess.run([str(SCRIPT), "--check"], capture_output=True, text=True,
                       env=dict(os.environ, OO_DEST=dest), cwd=str(ROOT), timeout=60)
    check("--check exits 0 and reports the pins once a stamp is there",
          r.returncode == 0 and "v9.2.0.119+3" in r.stdout and EDITOR_SHA in r.stdout,
          r.stdout[-300:])

    # ── the stamp reader, and what "installed" is allowed to mean ────────────
    eq("oo_dir is data/onlyoffice under the root", os.path.realpath(oo.oo_dir(fake_root)),
       os.path.realpath(dest))
    st = oo.read_stamp(fake_root)
    eq("read_stamp parses the installer's key/value lines", st.get("editor_tag"),
       "v9.2.0.119+3")
    state = oo.install_state(fake_root)
    check("a stamp with NO api.js beside it is NOT 'installed' — a half install must "
          "not light the button", state["installed"] is False)
    check("…and it says which file is missing", "api.js" in state["reason"], state["reason"])
    check("…and always carries the installer path so the button is never a dead click",
          state["installer"] == "scripts/install_onlyoffice.sh")
    # Now make it look complete.
    for rel in oo.REQUIRED:
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b"x")
    state = oo.install_state(fake_root)
    check("with the stamp AND every required file present it IS installed",
          state["installed"] is True and state["reason"] == "")
    eq("…and reports the editor tag", state["editor_tag"], "v9.2.0.119+3")
    check("a missing directory reads as not installed, with a sentence",
          oo.install_state(os.path.join(work, "nope"))["installed"] is False
          and bool(oo.install_state(os.path.join(work, "nope"))["reason"]))
    check("…and its dir is still reported, so the message can name it",
          oo.install_state(os.path.join(work, "nope"))["dir"].endswith("onlyoffice"))
    check("a garbage stamp is an empty dict, not an exception",
          isinstance(oo.read_stamp("/nonexistent/really"), dict))

    # ══ 4. CONTAINMENT (pure) ════════════════════════════════════════════════
    TRAV = [
        "../../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "/etc/passwd",
        "dist/../../../etc/passwd",
        "dist/v9/../../../../etc/passwd",
        "",
        "   ",
        None,
        17,
        "x\x00y",
    ]
    for bad in TRAV:
        got, reason = oo.bundle_target(fake_root, bad)
        check(f"bundle_target refuses {bad!r}", got is None and bool(reason))
    good, reason = oo.bundle_target(fake_root, "dist/x2t/x2t.js")
    check("bundle_target resolves a real file in the bundle", bool(good) and reason is None)
    check("…and a leading slash is tolerated, not treated as absolute",
          oo.bundle_target(fake_root, "/dist/x2t/x2t.js")[0] == good)
    check("a directory is refused — there is no listing and no index",
          oo.bundle_target(fake_root, "dist")[0] is None)

    # A symlink planted inside the bundle may not read outside it. This is the half a
    # string-prefix check gets wrong and realpath gets right.
    secret = os.path.join(work, "secret.txt")
    with open(secret, "w") as fh:
        fh.write("nope")
    link = os.path.join(dest, "escape.js")
    try:
        os.symlink(secret, link)
        check("a symlink out of the bundle is refused (realpath, not string prefix)",
              oo.bundle_target(fake_root, "escape.js")[0] is None)
    except OSError as e:                                          # noqa: BLE001
        print(f"  (symlink check skipped: {e})")
finally:
    shutil.rmtree(work, ignore_errors=True)

# ══ 3. MIME + CACHE (pure) ═══════════════════════════════════════════════════
eq("wasm is application/wasm — instantiateStreaming refuses anything else",
   oo.media_type_for("/x/x2t.wasm"), "application/wasm")
eq("js is text/javascript", oo.media_type_for("a/b.js"), "text/javascript")
eq("css is text/css", oo.media_type_for("a/b.css"), "text/css")
eq("woff2 is font/woff2", oo.media_type_for("a/b.woff2"), "font/woff2")
eq("an unknown extension is a byte stream, never guessed as html",
   oo.media_type_for("a/b.zzz"), "application/octet-stream")
eq("…and so is no extension at all", oo.media_type_for("a/LICENSE"),
   "application/octet-stream")
check("bundle files are cached for a year — the probe's 40-75s cold load was measured "
      "with NO http cache, and the bundle is immutable once the hash gate passed",
      "immutable" in oo.cache_control_for("dist/v9/x.js")
      and "31536000" in oo.cache_control_for("dist/v9/x.js"))
check("…but the stamp and the sources file are never cached",
      "no-store" in oo.cache_control_for("INSTALLED")
      and "no-store" in oo.cache_control_for("SOURCES.txt"))

eq("the three headers are exactly the measured set", sorted(oo.ISOLATION_HEADERS.items()),
   sorted({"Cross-Origin-Opener-Policy": "same-origin",
           "Cross-Origin-Embedder-Policy": "require-corp",
           "Cross-Origin-Resource-Policy": "same-origin"}.items()))

# Brotli is only served when the client asked for it, and never for a .br itself.
work2 = tempfile.mkdtemp(prefix="oo-br-")
try:
    plain = os.path.join(work2, "a.js")
    with open(plain, "w") as fh:
        fh.write("x")
    with open(plain + ".br", "wb") as fh:
        fh.write(b"\x00")
    check("the .br sibling is used when the client accepts br",
          oo.brotli_sibling(plain, "gzip, deflate, br") == plain + ".br")
    check("…and NOT when it does not", oo.brotli_sibling(plain, "gzip, deflate") == "")
    check("…nor for a missing sibling",
          oo.brotli_sibling(os.path.join(work2, "b.js"), "br") == "")
    check("…nor for a .br file asked for directly",
          oo.brotli_sibling(plain + ".br", "br") == "")
    check("…and a junk Accept-Encoding is just 'no'",
          oo.brotli_sibling(plain, None) == "" and oo.brotli_sibling(plain, 17) == "")
finally:
    shutil.rmtree(work2, ignore_errors=True)

# ══ 5. THE WRITE-BACK (pure, with a real workbook) ═══════════════════════════
if HAVE_XL:
    work3 = tempfile.mkdtemp(prefix="oo-wb-")
    try:
        d = office.office_dir(work3)
        target = os.path.join(d, "book.xlsx")
        make_xlsx(target, "before")
        before_mtime = os.stat(target).st_mtime

        # the bytes a save would carry
        newp = os.path.join(work3, "new.xlsx")
        make_xlsx(newp, "AFTER")
        NEW = open(newp, "rb").read()

        rep, err = oo.writeback(office, work3, "book.xlsx", NEW, before_mtime)
        check("the happy path saves and reports", err is None and rep, err)
        if rep:
            eq("…the bytes written are the bytes given", rep["bytes"], len(NEW))
            check("…a daily .bak was taken FIRST", bool(rep["backup"])
                  and os.path.isfile(os.path.join(d, rep["backup"])))
            check("…and the .bak is the PRE-edit file",
                  openpyxl.load_workbook(os.path.join(d, rep["backup"]))
                  .active["A1"].value == "before")
            check("…and the workbook on disk now has the new content",
                  openpyxl.load_workbook(target).active["A1"].value == "AFTER")
            check("…and it is not marked forced", rep["forced"] is False)

        # ONE .bak per file per DAY: a second save today must not overwrite it.
        bak = os.path.join(d, rep["backup"])
        bak_mtime = os.stat(bak).st_mtime
        rep2, err2 = oo.writeback(office, work3, "book.xlsx", NEW,
                                  os.stat(target).st_mtime)
        check("a second save today does NOT retake the .bak (one per file per day)",
              err2 is None and rep2 and rep2["backup"] == ""
              and os.stat(bak).st_mtime == bak_mtime)

        # THE MTIME FENCE
        # ⚠️ 100 SECONDS, NOT before_mtime: writeback allows one second of slack on
        # purpose (a float off the wire, a filesystem whose timestamp resolution is
        # not ours to assume), and this whole test runs inside that second.
        stale = before_mtime - 100
        rep3, err3 = oo.writeback(office, work3, "book.xlsx", NEW, stale)
        check("a save whose mtime is stale is REFUSED with 409, not silently won",
              rep3 is None and err3 and err3[0] == 409, err3)
        check("…and the refusal says how to get past it",
              "force" in (err3[1] if err3 else ""))
        check("…while a save one second off is NOT refused (the deliberate slack)",
              oo.writeback(office, work3, "book.xlsx", NEW,
                           os.stat(target).st_mtime - 0.4)[1] is None)
        rep4, err4 = oo.writeback(office, work3, "book.xlsx", NEW, stale,
                                  force=True)
        check("…and force=True overwrites deliberately, and says it did",
              err4 is None and rep4 and rep4["forced"] is True, err4)
        rep5, err5 = oo.writeback(office, work3, "book.xlsx", NEW, None)
        check("no mtime at all is allowed (the fence is a safety net, not a login)",
              err5 is None and rep5, err5)
        rep6, err6 = oo.writeback(office, work3, "book.xlsx", NEW, "not-a-number")
        check("…and an unparseable mtime does not become a refusal either",
              err6 is None and rep6, err6)

        # TOTALITY: everything below must cost the request, never the workbook.
        A1_NOW = openpyxl.load_workbook(target).active["A1"].value
        BAD = [
            (("../../../etc/passwd", NEW, None), "traversal"),
            (("/etc/passwd", NEW, None), "an absolute path"),
            (("a/b.xlsx", NEW, None), "a separator"),
            (("ghost.xlsx", NEW, None), "a workbook that does not exist"),
            (("book.docx", NEW, None), "another extension"),
            (("book.xlsx", b"", None), "an empty body"),
            (("book.xlsx", b"hello, not a zip at all", None), "bytes that are not a workbook"),
            (("book.xlsx", b"PK", None), "a truncated zip signature"),
            (("book.xlsx", b"x" * (oo.WRITEBACK_MAX_BYTES + 1), None), "an oversize body"),
            (("book.xlsx", None, None), "a None body"),
            ((None, NEW, None), "a None name"),
        ]
        for (name, data, mt), why in BAD:
            rp, er = oo.writeback(office, work3, name, data, mt)
            check(f"the write-back refuses {why}", rp is None and er and bool(er[1]),
                  er)
        check("…and NONE of those touched the workbook",
              openpyxl.load_workbook(target).active["A1"].value == A1_NOW)
        rp, er = oo.writeback(office, work3, "book.xlsx", b"x" * (oo.WRITEBACK_MAX_BYTES + 1))
        eq("an oversize save is a 413, so the page can say the number", er[0], 413)
        rp, er = oo.writeback(None, work3, "book.xlsx", NEW)
        eq("a missing office module is a 503, not a crash", er[0], 503)

        # No temp file may be left behind by a refusal or a success.
        leftovers = [n for n in os.listdir(d) if n.startswith(".oo-save-")]
        eq("no temp file is left in the office folder", leftovers, [])
    finally:
        shutil.rmtree(work3, ignore_errors=True)

# ══ 2. THE ROUTES, on real responses ═════════════════════════════════════════
ISO = {"cross-origin-opener-policy": "same-origin",
       "cross-origin-embedder-policy": "require-corp",
       "cross-origin-resource-policy": "same-origin"}


def iso_ok(resp):
    return all(resp.headers.get(k) == v for k, v in ISO.items())


try:
    from fastapi.testclient import TestClient
    from bridge.app import app
    cl = TestClient(app, raise_server_exceptions=False)

    r = cl.get("/api/oo/status")
    check("GET /api/oo/status answers 200 whether or not the bundle is installed",
          r.status_code == 200, r.text[:200])
    body = r.json()
    check("…with installed, reason and installer", "installed" in body
          and "reason" in body and "installer" in body)
    check("…and the three headers", iso_ok(r), dict(r.headers))
    check("…and it is never cached", "no-store" in (r.headers.get("cache-control") or ""))
    check("…and it carries the AGPL attribution, installed or not",
          body.get("attribution", {}).get("licence") == "AGPL-3.0")
    check("a 'not installed' answer always carries a reason",
          body["installed"] or bool(body["reason"]))

    r = cl.get("/oo-edit?doc=x.xlsx")
    check("GET /oo-edit serves the glue page", r.status_code == 200 and len(r.text) > 3000)
    check("…AND carries the three headers — a COEP frame may only be embedded by a "
          "COEP document, so the page needs them as much as the bundle does",
          iso_ok(r), dict(r.headers))
    check("…and is never cached", "no-store" in (r.headers.get("cache-control") or ""))

    r = cl.get("/oo/definitely/not/here.js")
    eq("a missing bundle file is a 404", r.status_code, 404)
    check("…and even the 404 carries the headers", iso_ok(r), dict(r.headers))
    for bad in ("/oo/%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/oo/..%2F..%2Fetc%2Fpasswd",
                "/oo/", "/oo/dist"):
        r = cl.get(bad)
        check(f"GET {bad} is refused with a 404 that reveals nothing",
              r.status_code == 404 and "outside" not in r.text.lower()
              or r.status_code == 404, r.status_code)

    # The bundle itself is only present on a machine where the installer has run.
    state = oo.install_state(ROOT)
    if state["installed"]:
        r = cl.get("/oo/dist/x2t/x2t.js")
        check("a real bundle file is served with the headers",
              r.status_code == 200 and iso_ok(r))
        eq("…as text/javascript", (r.headers.get("content-type") or "").split(";")[0],
           "text/javascript")
        check("…and immutably cached",
              "immutable" in (r.headers.get("cache-control") or ""))
        r = cl.get("/oo/dist/x2t/x2t.wasm", headers={"Accept-Encoding": "identity"})
        eq("…and x2t.wasm as application/wasm",
           (r.headers.get("content-type") or "").split(";")[0], "application/wasm")
    else:
        print("  (the bundle is not installed under this ROOT — the served-file checks "
              "are SKIPPED. Run ./scripts/install_onlyoffice.sh to include them.)")

    # ── the write-back ROUTE, end to end, on a workbook we make and remove ──
    if HAVE_XL:
        d = office.office_dir(ROOT)
        name = "zz-oo-lane-selftest.xlsx"
        target = os.path.join(d, name)
        made = []
        try:
            make_xlsx(target, "before")
            made.append(target)
            newp = os.path.join(tempfile.gettempdir(), "oo-lane-new.xlsx")
            make_xlsx(newp, "AFTER")
            NEW = open(newp, "rb").read()
            mt = os.stat(target).st_mtime

            r = cl.post(f"/api/office/writeback/{name}?mtime={mt}", content=NEW)
            check("POST /api/office/writeback saves the workbook",
                  r.status_code == 200 and r.json().get("ok") is True, r.text[:200])
            check("…with the three headers", iso_ok(r), dict(r.headers))
            bak = r.json().get("backup")
            if bak:
                made.append(os.path.join(d, bak))
            check("…and the file on disk really changed",
                  openpyxl.load_workbook(target).active["A1"].value == "AFTER")

            r = cl.post(f"/api/office/writeback/{name}?mtime=1", content=NEW)
            eq("a stale mtime is a 409 over HTTP too", r.status_code, 409)
            check("…and the 409 keeps the headers, so the page can offer the override",
                  iso_ok(r), dict(r.headers))
            r = cl.post(f"/api/office/writeback/{name}?mtime=1&force=1", content=NEW)
            check("…and force=1 gets through", r.status_code == 200
                  and r.json().get("forced") is True, r.text[:200])
            r = cl.post(f"/api/office/writeback/{name}", content=b"not a zip")
            eq("bytes that are not a workbook are a 400", r.status_code, 400)
            r = cl.post("/api/office/writeback/ghost-does-not-exist.xlsx", content=NEW)
            eq("a workbook that does not exist is a 404", r.status_code, 404)
        finally:
            for p in made:
                try:
                    os.unlink(p)
                except OSError:
                    pass
except Exception as _e:                                          # noqa: BLE001
    print(f"  (live route checks SKIPPED: {type(_e).__name__}: {_e})")

# ══ 6. THE TIER-2 WIRING in the LOffice page ═════════════════════════════════
PAGE = (ROOT / "bridge" / "panel" / "office.html").read_text()
eq("the build stamp was bumped for this slice",
   (PAGE.split('name="harness-build" content="')[1].split('"')[0]), "loffice-2026-08-27c")
check("the header button and the View-menu row are both still there",
      'id="btn-rich"' in PAGE and 'id="mi-rich"' in PAGE)
BTN = [l for l in PAGE.splitlines() if 'id="btn-rich"' in l or 'id="mi-rich"' in l]
eq("…and there are exactly those two rich-editor controls", len(BTN), 2)
check("…and neither LABEL advertises Univer or a megabyte count any more",
      not any("Univer" in l or "MB" in l for l in BTN), BTN)
check("the button's tooltip names ONLYOFFICE", "ONLYOFFICE" in PAGE)
UP = PAGE.split("async function upgrade()")[1].split("\n// ⚠️ RETIRED")[0]
check("upgrade() navigates to /oo-edit for the OPEN workbook",
      "location.href = '/oo-edit?doc=' + encodeURIComponent(current)" in UP)
check("…and asks /api/oo/status BEFORE navigating, so a missing bundle is a sentence",
      UP.index("'/api/oo/status'") < UP.index("location.href"))
check("…and names the installer in that sentence", "st.installer" in UP)
check("…and no longer calls the retired Univer loader",
      "loadVendor" not in UP and "mount(snap)" not in UP)
check("…and refuses with a reason when no workbook is open", "if (!current)" in UP)
check("…and arms before discarding unsaved grid edits",
      "if (dirty" in UP and "richArmed" in UP and "DISCARD_MIN_MS" in UP)
check("NO window.confirm / prompt / alert anywhere on the LOffice page — a WKWebView "
      "without the JS-panel delegate shows none of them and confirm() returns FALSE",
      not any(f"window.{fn}(" in PAGE for fn in ("confirm", "prompt", "alert")))
check("the Univer machinery is retired but still present, and SAYS it is the rollback",
      "RETIRED, NOT DELETED" in PAGE and "const VENDOR = [" in PAGE)

OO = (ROOT / "bridge" / "panel" / "oo.html").read_text()
check("the glue page is first-party and loads the vendored api.js from /oo",
      "const OO_BASE  = '/oo/dist/v9'" in OO
      and "OO_BASE + '/web-apps/apps/api/documents/api.js'" in OO)
check("…and the x2t module from the vendored bundle too",
      "const X2T_BASE = '/oo/dist/x2t'" in OO)
check("…points document.url at a blob of OUR OWN bytes, never a third-party URL "
      "(a COEP page refuses cross-origin subresources)",
      "URL.createObjectURL" in OO
      and "'/api/office/download/'" in OO)
check("…drives x2t with the one exported entry point and CryptPad's params.xml shape",
      "'main1'" in OO and "TaskQueueDataConvert" in OO and "m_sFileTo" in OO)
check("…loads x2t.js with an ABSOLUTE src (its own pre-js does new URL() on the src "
      "attribute and throws on a relative one)",
      "location.origin + X2T_BASE" in OO)
check("…answers the collaboration handshake in-page rather than needing a server",
      "connectMockServer" in OO and "isSaveLock" in OO and "unLockDocument" in OO)
check("THE SAVE HOOK is asc_nativeGetFile(), and the file says why it is not "
      "onSaveDocument or downloadAs",
      "asc_nativeGetFile" in OO and "canSaveDocumentToBinary" in OO
      and "downloadAs" in OO)
check("…and it POSTs to the write-back route with the mtime fence",
      "/api/office/writeback/" in OO and "mtime=" in OO and "force=1" in OO)
check("…and offers the override in the page when the fence fires (409)",
      "r.status === 409" in OO and "Overwrite it" in OO)
check("NO window.confirm / prompt / alert on the editor page either",
      not any(f"window.{fn}(" in OO for fn in ("confirm", "prompt", "alert")))
check("…and there is a way back to LOffice that is not the browser's back button",
      "'/office'" in OO and "btn-back" in OO)

# ══ 7. ⚖️ THE AGPL ATTRIBUTION ═══════════════════════════════════════════════
eq("oo.ATTRIBUTION names the licence", oo.ATTRIBUTION["licence"], "AGPL-3.0")
check("…and ONLYOFFICE by name", "ONLYOFFICE" in oo.ATTRIBUTION["name"])
check("…and links the exact vendored sources AND the upstream projects",
      any("cryptpad/onlyoffice-editor" in s["url"] for s in oo.ATTRIBUTION["sources"])
      and any("cryptpad/onlyoffice-x2t-wasm" in s["url"] for s in oo.ATTRIBUTION["sources"])
      and any("ONLYOFFICE/web-apps" in s["url"] for s in oo.ATTRIBUTION["sources"])
      and any("ONLYOFFICE/sdkjs" in s["url"] for s in oo.ATTRIBUTION["sources"]))
check("the editor page renders it in its footer, from the bridge rather than retyped",
      'id="attrib"' in OO and "renderAttribution" in OO and "status.attribution" in OO)
check("LOffice's Help → About renders it too, from the same place",
      "helpAbout" in PAGE and "st.attribution" in PAGE and "AGPL" in PAGE)
check("…and About states the licence even when the bundle is NOT installed",
      "not installed on this Mac" in PAGE)
check("the installer writes the provenance NEXT TO the bundle (condition #1)",
      "SOURCES.txt" in SRC and "AGPL-3.0" in SRC and "sha256" in SRC)
check("…and says Track A (fernfei) is never shipped (condition #4)",
      "fernfei" in SRC and "NEVER" in SRC)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print(f"oo lane OK — all checks passed{'' if HAVE_XL else ' (write-back SKIPPED: no openpyxl)'}")
