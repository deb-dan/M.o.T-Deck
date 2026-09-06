"""LOffice TIER 2 — the vendored ONLYOFFICE static editors, served by our bridge.

WHAT THIS IS. `scripts/install_onlyoffice.sh` unzips two CryptPad release zips into
`data/onlyoffice/` (`dist/v9` = sdkjs + web-apps, `dist/x2t` = the wasm converter).
This module is the ONLY thing that reads that directory: it decides whether the
bundle is installed, resolves a request path inside it with the same containment
discipline as `office.py`, and stamps every response with the headers the editors
need. Our own first-party glue page (`bridge/panel/oo.html`) drives it.

NOT A COMPONENT. No port, no process, no manifest entry, no venv. Static files and
one write-back route.

⚠️ THE THREE HEADERS ARE LOAD-BEARING, MEASURED, AND NOT NEGOTIABLE.
The 2026-08-27 WKWebView probe found that WITHOUT cross-origin isolation the
spreadsheet editor renders its whole frame and then hangs at "Loading spreadsheet"
forever — SharedArrayBuffer never appears and there are ZERO console errors. It
fails silently. So every response under /oo/* AND the glue page itself carries:

    Cross-Origin-Opener-Policy:   same-origin
    Cross-Origin-Embedder-Policy: require-corp
    Cross-Origin-Resource-Policy: same-origin

The consequence runs the other way too: a COEP page refuses cross-origin
subresources, so EVERYTHING the editor touches must be same-origin. That is why the
glue page points `document.url` at a `blob:` of our own bytes and fetches the
workbook from our own `/api/office/download/{name}` — never at a third-party URL.

⚠️ .wasm MUST be `application/wasm` or `WebAssembly.instantiateStreaming` refuses
it. The stdlib's mimetypes module knows this only on some builds, so it is forced.

CACHING. The bundle is IMMUTABLE once vendored (the installer verifies a sha256 pin
before unzipping and re-unzips from scratch on a bump), so bundle files get a
one-year immutable cache — the probe's 40–75s cold load was measured with no HTTP
cache at all. The stamp, the sources file and the glue page are never cached.

BROTLI. The zips ship a pre-compressed `.br` sibling for most text assets. When the
client says it accepts `br` we serve the sibling with `Content-Encoding: br`, which
is what CryptPad does and is worth a lot over 16600 files. Guarded on the request
header; a client that does not ask gets the plain file.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

# ── the headers ──────────────────────────────────────────────────────────────
# One dict, one source of truth, asserted directly in bridge/tests/test_oo_lane.py.
ISOLATION_HEADERS = {
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}

IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
NO_CACHE = "no-store, no-cache, must-revalidate"

# Forced MIME types. `.wasm` is the one that turns a working bundle into a silent
# failure; the rest are here so a Python build without /etc/apache2/mime.types
# cannot serve a stylesheet as text/plain and break the ribbon's layout.
FORCE_TYPES = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".bin": "application/octet-stream",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "text/xml",
    ".aff": "text/plain",
    ".dic": "text/plain",
    ".map": "application/json",
}

STAMP_NAME = "INSTALLED"
SOURCES_NAME = "SOURCES.txt"
INSTALLER = "scripts/install_onlyoffice.sh"

# The four files the glue page cannot work without. `install_state` checks them on
# disk rather than trusting the stamp: a stamp with no api.js beside it is a half
# install, and "installed" must mean "the button will work".
REQUIRED = (
    "dist/v9/web-apps/apps/api/documents/api.js",
    "dist/v9/web-apps/apps/spreadsheeteditor/main/index.html",
    "dist/x2t/x2t.js",
    "dist/x2t/x2t.wasm",
)

# ⚖️ AGPL-3.0 attribution, single-sourced. The glue page footer and the LOffice
# About sheet both render THIS, so condition #3 of the 2026-08-27 ruling cannot be
# satisfied in one place and forgotten in the other.
ATTRIBUTION = {
    "name": "ONLYOFFICE Docs (sdkjs + web-apps) and x2t",
    "licence": "AGPL-3.0",
    "licence_url": "https://www.gnu.org/licenses/agpl-3.0.html",
    "note": ("The rich editor is unmodified upstream ONLYOFFICE, vendored as its own "
             "static bundle and served read-only. MOT Deck does not modify it."),
    "sources": [
        {"what": "editor bundle (the vendored build)",
         "url": "https://github.com/cryptpad/onlyoffice-editor"},
        {"what": "x2t wasm converter (the vendored build)",
         "url": "https://github.com/cryptpad/onlyoffice-x2t-wasm"},
        {"what": "ONLYOFFICE web-apps (upstream source)",
         "url": "https://github.com/ONLYOFFICE/web-apps"},
        {"what": "ONLYOFFICE sdkjs (upstream source)",
         "url": "https://github.com/ONLYOFFICE/sdkjs"},
        {"what": "ONLYOFFICE core / x2t (upstream source)",
         "url": "https://github.com/ONLYOFFICE/core"},
    ],
}

# Write-back cap. A workbook that ONLYOFFICE serialised is the same order of size as
# one openpyxl wrote, so the import cap is the right number to reuse — but this is
# its own constant because the two paths could diverge and a silent shared limit is
# how a 30MB rule becomes a mystery.
WRITEBACK_MAX_BYTES = 60 * 1024 * 1024


# ── paths + containment ──────────────────────────────────────────────────────
def oo_dir(root) -> str:
    """Where the bundle lives. NOT created on demand — its absence is the signal
    that the installer has not run, and a helpfully-made empty directory would turn
    "not installed" into "installed but broken"."""
    return os.path.join(str(root), "data", "onlyoffice")


def stamp_path(root) -> str:
    return os.path.join(oo_dir(root), STAMP_NAME)


def read_stamp(root) -> dict:
    """The installer's `key value` lines as a dict. Total: an unreadable, truncated
    or garbage stamp is an empty dict, never an exception."""
    out = {}
    try:
        with open(stamp_path(root), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or " " not in line:
                    continue
                key, _, value = line.partition(" ")
                if key and key.isascii() and len(out) < 64:
                    out[key] = value.strip()[:400]
    except OSError:
        return {}
    return out


def install_state(root) -> dict:
    """The single answer to "is the rich editor available?".

    Shape is the /api/oo/status body and the thing bridge/panel/office.html branches
    on, so the button is NEVER a dead click: `installed` false always comes with a
    `reason` a human can act on and the command that fixes it.
    """
    base = oo_dir(root)
    stamp = read_stamp(root)
    missing = [rel for rel in REQUIRED if not os.path.isfile(os.path.join(base, rel))]
    if not os.path.isdir(base):
        reason = "the ONLYOFFICE editor bundle has not been installed yet"
    elif not stamp:
        reason = ("the bundle directory exists but there is no INSTALLED stamp — "
                  "the install did not finish")
    elif missing:
        reason = (f"the stamp is there but {len(missing)} required file(s) are not, "
                  f"starting with {missing[0]}")
    else:
        reason = ""
    return {
        "installed": not reason,
        "reason": reason,
        "installer": INSTALLER,
        "dir": base,
        "editor_tag": stamp.get("editor_tag", ""),
        "x2t_tag": stamp.get("x2t_tag", ""),
        "editor_sha256": stamp.get("editor_sha256", ""),
        "x2t_sha256": stamp.get("x2t_sha256", ""),
        "installed_at": stamp.get("date", ""),
        "files": stamp.get("files", ""),
        "attribution": ATTRIBUTION,
    }


# ── the bundle's fonts, listed (PDF export needs them IN the wasm filesystem) ──
# ⚠️ WHY THE BRIDGE HAS TO LIST THESE. x2t renders a PDF with real, subsetted, EMBEDDED
# TrueType faces, so it needs the font FILES — and its wasm filesystem starts empty. The
# glue page therefore copies the bundle's own font directory into x2t's FS before the
# first export. MEASURED 2026-08-28: with an empty /working/fonts the conversion does not
# fail politely — it takes the whole wasm module out ("Out of bounds memory access") and
# every later conversion in that page, INCLUDING SAVE, dies with it. So the list is a
# precondition, not an optimisation.
#
# Read from disk rather than hardcoded, for a reason that has already bitten this lane:
# a vendored bump that adds or renames a face would leave a hardcoded list quietly
# short, and "quietly short" here means a PDF with the wrong glyphs.
FONTS_REL = "dist/v9/fonts/fonts"
FONT_EXTS = (".ttf", ".otf", ".ttc")


def font_files(root) -> list:
    """The bundle's font file NAMES, sorted. Empty list when the bundle is absent.

    Names only — the page fetches each one through /oo/* like any other asset, so
    containment, forced MIME and the immutable cache all still apply, and this route
    cannot become a second way to read the disk.
    """
    base = os.path.join(oo_dir(root), FONTS_REL)
    try:
        return sorted(n for n in os.listdir(base)
                      if n.lower().endswith(FONT_EXTS)
                      and os.path.isfile(os.path.join(base, n)))
    except OSError:
        return []


def bundle_target(root, rel):
    """(abs_path, None) or (None, reason) for a /oo/* request.

    The SAME rule as office.doc_target, for the same reason: the path comes off the
    wire. realpath containment strictly under data/onlyoffice, so neither `..` nor a
    symlink planted in the bundle can address a byte outside it. Directories are
    refused outright — there is no index and no listing.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None, "no file requested"
    if "\x00" in rel:
        return None, "refused: that is not a file name"
    rel = rel.lstrip("/")
    base = os.path.realpath(oo_dir(root))
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None, "refused: that path is outside the editor bundle"
    if not os.path.isfile(target):
        return None, "no such file in the editor bundle"
    return target, None


def media_type_for(path) -> str:
    ext = os.path.splitext(str(path))[1].lower()
    return FORCE_TYPES.get(ext, "application/octet-stream")


def cache_control_for(rel) -> str:
    """Immutable for the bundle, never for the two files the installer rewrites."""
    base = os.path.basename(str(rel))
    if base in (STAMP_NAME, SOURCES_NAME):
        return NO_CACHE
    return IMMUTABLE_CACHE


def brotli_sibling(path, accept_encoding) -> str:
    """The pre-compressed `.br` beside `path` when the client accepts brotli, else ''.

    The zips ship `.br` for most text assets. Serving them is a large win over 16600
    files — and it is safe only when the client asked, which is why the header is a
    required argument rather than an assumption.
    """
    if not isinstance(accept_encoding, str) or "br" not in accept_encoding.lower():
        return ""
    if str(path).endswith(".br"):
        return ""
    cand = str(path) + ".br"
    try:
        if os.path.isfile(cand) and os.path.getsize(cand) > 0:
            return cand
    except OSError:
        return ""
    return cand if os.path.isfile(cand) else ""


# ── write-back: THE SAVE ─────────────────────────────────────────────────────
# This is Save, not import: it OVERWRITES the workbook the editor opened. Three
# guards, in this order, because each one is a way real work gets lost:
#
#   1. CONTAINMENT — the name goes through office.doc_target, exactly like every
#      other route in the lane. No traversal, no symlink escape, no new extension.
#   2. THE DAILY .bak — office.backup_for, the same once-per-file-per-day copy
#      tier 1 takes. ONLYOFFICE has far better fidelity than our snapshot
#      round-trip, but "better" is not "identical", and the pre-edit file of the day
#      must survive.
#   3. THE MTIME FENCE — if the file on disk changed since the editor opened it,
#      the save is REFUSED rather than silently winning. That is a real case here:
#      tier 1 and tier 2 can both be looking at the same workbook, and the tier-2
#      page is a full-page navigation that can sit open for an hour. `force` exists
#      because a refusal the user cannot override is its own kind of data loss.
#
# The write itself is temp-file + os.replace in the SAME directory, so a crash
# mid-write leaves the old workbook intact rather than a truncated one.
#
# ⚠️ AND THE FENCE IS NO LONGER CALLER-OPTIONAL BY ACCIDENT (bug-echo W-01). `expect_mtime
# =None` used to mean "do not check", silently: every caller happened to supply one, so
# the first future caller that forgot would have got an unfenced Save with nothing said
# anywhere — the F-01 class arriving through a default argument. None now means REFUSE TO
# GUESS. A caller that genuinely does not know the version it started from says
# `unfenced=True` and gets a write plus a line in the log; a caller that forgets gets a
# sentence. The same three states, in the same words, as office.save_doc's fence.
UNFENCED_REFUSAL = ("refused: this save carries no record of the version it started from, "
                    "so it cannot promise not to overwrite somebody else's write. Reopen "
                    "the document and save again.")

def _zip_looking(data) -> bool:
    """OOXML is a zip. Two signatures are legal: a normal local file header and an
    empty archive. Anything else is not an Office file and must not land on disk.

    This is the sniff for ALL THREE types (stage 3): .xlsx, .docx and .pptx are the same
    container. The TYPE is then checked properly by `writeback` below, which asks
    office.verify_package whether the package really is what its name claims.
    """
    return isinstance(data, (bytes, bytearray)) and len(data) > 4 and (
        bytes(data[:4]) in (b"PK\x03\x04", b"PK\x05\x06"))


def writeback(office, root, name, data, expect_mtime=None, force=False, today=None,
              unfenced=False):
    """(report, None) or (None, (status, reason)).

    `office` is the office module, injected rather than imported so this stays
    testable and so oo.py cannot resurrect a lane whose own import failed.

    `expect_mtime` is the mtime the editor saw when it opened the file. None is a
    REFUSAL, not a skip — see UNFENCED_REFUSAL above; `unfenced=True` is how a caller
    that truly cannot know says so out loud.
    """
    if office is None:
        return None, (503, "the office module failed to load")
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None, (400, "no file received")
    if len(data) > WRITEBACK_MAX_BYTES:
        return None, (413, f"that save is {len(data) // (1024 * 1024)} MB — the cap "
                           f"is {WRITEBACK_MAX_BYTES // (1024 * 1024)} MB")
    if not _zip_looking(data):
        return None, (400, f"refused: those bytes are not a {office.noun_of(name)}")

    target, reason = office.doc_target(root, name)
    if not target:
        return None, (404 if reason == "no such workbook" else 400, reason)
    # ⚠️ THE PACKAGE MUST BE WHAT THE NAME CLAIMS. The editor serialises whatever it is
    # holding, and a document-type mix-up upstream (a word editor asked to write over a
    # .pptx, say) would otherwise land a valid-but-wrong package on top of the user's
    # file — a zip signature alone cannot tell those apart.
    if hasattr(office, "verify_package") and office.kind_of(target) != "sheet":
        bad = office.verify_package(data, office.ext_of(target))
        if bad:
            return None, (400, "refused: " + bad)

    try:
        st = os.stat(target)
    except OSError as e:
        return None, (404, f"cannot read that workbook: {e.strerror or e}")
    disk_mtime = st.st_mtime

    want = None
    if expect_mtime is not None:
        try:
            want = float(expect_mtime)
        except (TypeError, ValueError):
            want = None
        if want is not None and (want != want or want in (float("inf"),
                                                          float("-inf"))):
            want = None                                  # NaN / inf compare with nothing
        # ⚠️ A FENCE VALUE WE CANNOT READ IS NOT "NO FENCE". This used to fall through to
        # an unfenced write: `?mtime=lunchtime` (or a JSON null-as-string, or a truncated
        # float) skipped the check as thoroughly as sending nothing, and the caller had
        # every reason to believe it was fenced because it sent one.
        if want is None:
            return None, (400, UNFENCED_REFUSAL)
    elif not unfenced:
        return None, (400, UNFENCED_REFUSAL)

    if want is not None and not force:
        # One second of slack: the wire carries a float that has been through JSON
        # and a filesystem whose timestamp resolution is not ours to assume.
        if abs(want - disk_mtime) > 1.0:
            return None, (409, "that workbook changed on disk since the editor opened "
                               "it — saving now would overwrite the newer version. "
                               "Reopen it, or save again with force to overwrite.")

    # The daily .bak, before a byte is written.
    backup = ""
    try:
        bak = office.backup_for(target, today=today)
        if not os.path.exists(bak):
            shutil.copy2(target, bak)
            backup = os.path.basename(bak)
    except OSError as e:                                          # noqa: BLE001
        return None, (500, f"could not take a safety copy first: {e.strerror or e}")

    d = os.path.dirname(target)
    tmp = ""
    try:
        # ⚠️ THE TARGET'S OWN EXTENSION, NOT A HARDCODED .xlsx (stage 3). The temp file is
        # renamed over the real one, and a .docx that spent a moment named .xlsx is a
        # .docx that Spotlight, Quick Look and a crash-recovery listing all misread.
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".oo-save-",
                                   suffix=(office.ext_of(target) or ".xlsx"))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        tmp = ""
    except OSError as e:                                          # noqa: BLE001
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return None, (500, f"could not write that workbook: {e.strerror or e}")

    try:
        new_mtime = os.stat(target).st_mtime
    except OSError:
        new_mtime = time.time()
    return {"name": os.path.basename(target), "bytes": len(data),
            "backup": backup, "mtime": new_mtime,
            # `fenced` says which of the three states this save took, so a log line (and
            # a reader of one) never has to infer it from the absence of a 409.
            "fenced": want is not None,
            "forced": bool(force and want is not None)}, None
