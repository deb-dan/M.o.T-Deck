#!/usr/bin/env python3
"""LOFFICE — DOCS + SLIDES, and DOWNLOAD AS PDF (2026-08-28, loffice-2026-08-29a).

Stage 3 put two more file types in data/office and stage 2 replaced Print. Both are
built on an asymmetry that is easy to erode by accident, so it is pinned here:

  THE STORE handles three types. Naming, listing, containment, backups, upload,
  download, rename, create and the editor's write-back all work on .xlsx, .docx and
  .pptx, because every one of those needs only a name and some bytes.

  THE CONTENT is .xlsx ONLY, and REFUSES the other two BY NAME. There is no document
  mapper and there is deliberately never going to be one; `office.require_sheet()` is
  the single refusal, and it returns a SENTENCE that says what the user can do instead.

What each group guards, and why a test rather than a comment:

1. THE THREE EXTENSIONS AND THE ONE DEFAULT. `valid_name` accepts the three and
   defaults a bare stem to .xlsx (which is what New has always meant); anything else is
   refused. A rename may change the STEM and never the TYPE — with three extensions in
   one folder that stopped being a naming rule and became a truthfulness one.

2. THE BLANK PACKAGES. bridge/officeblank.py builds them from the OOXML rules rather
   than vendoring a file of unverifiable origin. They are DETERMINISTIC, so their
   sha256 is pinned: a change to either package is a change somebody has to mean.
   Structure is checked part by part, including the two parts that were added after a
   live finding — the master's `<p:bg>` and `<p:txStyles>`, without which a blank deck
   defaults to WHITE text on a white slide.

3. THE CONTENT REFUSAL, at every door: snapshot_from_path, write_snapshot, open_doc,
   save_doc, and the agent's office_read / office_sheet_stats / office_stage_changes.

4. THE PACKAGE VERIFIER. A .docx renamed .pptx is refused on IMPORT and on WRITE-BACK,
   because a file that lands in the list and only fails when clicked is a folder the
   user stops trusting.

5. PER-TYPE FACTS ON THE WIRE — `kind`, `ext`, the media type, the daily backup's
   extension, and the fidelity sentence for a file the bridge never rewrites.

6. THE PANEL. Three start-screen cards, a type badge on every row, tier-1 verbs OFF for
   a blob, no /api/office/open for a blob, and an AI panel that says it cannot see the
   file instead of offering to.

7. DOWNLOAD AS PDF. The whole recipe is measured and each part of it fails SILENTLY if
   it is wrong, so each part is pinned: the CANVAS format codes, `m_bIsNoBase64` true,
   the font mount as a precondition, the page-count re-read that refuses an empty PDF,
   and the `<a download>` blob mechanism (the one the shell's delegate turns into a
   real download — a navigation would not, because WebKit CAN show application/pdf).

Run: python3 bridge/tests/test_office_types.py
"""
import hashlib
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bridge import office                                        # noqa: E402
from bridge import officeblank                                   # noqa: E402
from bridge import oo as oomod                                   # noqa: E402
from bridge import office_ops                                    # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name + ((" | " + str(extra)[:300]) if extra else ""))


def eq(name, got, want):
    check(name, got == want, f"got {got!r} want {want!r}")


# ══ 1. THE THREE EXTENSIONS ═══════════════════════════════════════════════════
eq("the store knows exactly three extensions",
   list(office.DOC_EXTS), [".xlsx", ".docx", ".pptx"])
eq("…and .xlsx is still the DEFAULT for a bare stem", office.DOC_EXT, ".xlsx")
eq("every extension maps to a kind",
   office.KINDS, {".xlsx": "sheet", ".docx": "doc", ".pptx": "slides"})
eq("every kind has a noun for a sentence", sorted(office.KIND_NOUNS),
   ["doc", "sheet", "slides"])
eq("…and a media type, because a hardcoded spreadsheet MIME opens a .docx in the "
   "wrong application", sorted(office.MEDIA_TYPES), [".docx", ".pptx", ".xlsx"])
for ext, frag in ((".xlsx", "spreadsheetml"), (".docx", "wordprocessingml"),
                  (".pptx", "presentationml")):
    check(f"…and {ext}'s media type is the right one",
          frag in office.MEDIA_TYPES[ext], office.MEDIA_TYPES[ext])

NAMES = [("a", "a.xlsx"), ("a.xlsx", "a.xlsx"), ("a.docx", "a.docx"),
         ("a.pptx", "a.pptx"), ("A.DOCX", "A.docx"), ("  b.pptx  ", "b.pptx"),
         ("a.csv", None), ("a.doc", None), ("a.ppt", None), ("a.txt", None),
         ("a.docx.exe", None), ("../a.docx", None), ("a/b.pptx", None),
         (".docx", None), ("x\x00.docx", None)]
for raw, want in NAMES:
    got, reason = office.valid_name(raw)
    check(f"valid_name({raw!r}) → {want!r}", got == want and (want or bool(reason)))
check("a caller can still NARROW the set (the rename path does)",
      office.valid_name("a.docx", allowed=(".xlsx",))[0] is None)
eq("kind_of reads the extension", office.kind_of("x.PPTX"), "slides")
eq("noun_of names the thing in a sentence", office.noun_of("x.docx"), "document")
eq("…and an unknown extension gets a neutral noun", office.noun_of("x.zzz"), "file")

# The daily backup keeps the SOURCE extension — a .docx backed up as .xlsx is a file
# macOS, Word and our own list all mis-identify.
for ext in office.DOC_EXTS:
    eq(f"backup_for keeps {ext}",
       os.path.basename(office.backup_for(f"/d/report{ext}", today="20260101")),
       f"report.20260101.bak{ext}")
    check(f"…and is_backup_name recognises the {ext} one",
          office.is_backup_name(f"report.20260101.bak{ext}"))
check("a real file is NOT mistaken for a backup",
      not any(office.is_backup_name(f"report{e}") for e in office.DOC_EXTS))


# ══ 2. THE BLANK PACKAGES ═════════════════════════════════════════════════════
# ⚠️ THE HASHES ARE THE POINT. blank_bytes is deterministic (fixed zip timestamps,
# fixed member order), so these two lines turn "somebody edited the template" into a
# failing test rather than a surprise in a document six months from now. Update them
# ONLY together with a deliberate change, and re-walk the editor journey when you do.
BLANK_SHA = {
    ".docx": "b82ef4bf15cdc671e8db690321045a5fb77f7550949142e36c4da9ceff547488",
    ".pptx": "35579e2363386fb32302783d6c06df655850bf741e96f9d6d74a2f5b7a265ff5",
}
for ext in (".docx", ".pptx"):
    b1 = officeblank.blank_bytes(ext)
    b2 = officeblank.blank_bytes(ext)
    check(f"blank {ext} is DETERMINISTIC — same bytes every call", b1 == b2)
    check(f"…and it is a valid zip", zipfile.ZipFile(io.BytesIO(b1)).testzip() is None)
    got = hashlib.sha256(b1).hexdigest()
    eq(f"…and its sha256 is the pinned one ({len(b1)} bytes)", got, BLANK_SHA[ext])

z = zipfile.ZipFile(io.BytesIO(officeblank.blank_bytes(".docx")))
names = set(z.namelist())
for want in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
    check(f"the blank .docx carries {want}", want in names)
ct = z.read("[Content_Types].xml").decode()
check("…and declares its main part", "/word/document.xml" in ct
      and "wordprocessingml.document.main+xml" in ct)
doc = z.read("word/document.xml").decode()
check("…and has a body with one paragraph and a section", "<w:body>" in doc
      and "<w:p/>" in doc and "<w:sectPr>" in doc)
check("…on A4 with real margins, stated rather than left to whoever wins",
      'w:w="11906"' in doc and 'w:h="16838"' in doc and "w:pgMar" in doc)
eq("…and nothing else — 'minimal' is checked, not claimed", len(names), 3)

z = zipfile.ZipFile(io.BytesIO(officeblank.blank_bytes(".pptx")))
names = set(z.namelist())
for want in ("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml",
             "ppt/_rels/presentation.xml.rels",
             "ppt/slideMasters/slideMaster1.xml",
             "ppt/slideMasters/_rels/slideMaster1.xml.rels",
             "ppt/slideLayouts/slideLayout1.xml",
             "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
             "ppt/slides/slide1.xml", "ppt/slides/_rels/slide1.xml.rels",
             "ppt/theme/theme1.xml"):
    check(f"the blank .pptx carries {want}", want in names)
pres = z.read("ppt/presentation.xml").decode()
check("the presentation references its master AND its one slide",
      "sldMasterId" in pres and "sldIdLst" in pres and 'r:id="rId2"' in pres)
check("…and is 16:9, the default every current PowerPoint uses",
      'cx="12192000"' in pres and 'cy="6858000"' in pres)
master = z.read("ppt/slideMasters/slideMaster1.xml").decode()
check("the master carries a clrMap (a slide cannot resolve a colour without one)",
      "<p:clrMap " in master and 'tx1="dk1"' in master)
# ⚠️ THESE TWO ARE A LIVE FINDING, NOT TIDINESS. Without txStyles the default run
# colour resolves through the style matrix to lt1 — WHITE — and text typed on a blank
# slide is invisible while round-tripping perfectly through save and reopen.
check("…and <p:txStyles>, WITHOUT WHICH DEFAULT TEXT COMES OUT WHITE ON WHITE",
      "<p:txStyles>" in master and "titleStyle" in master
      and "bodyStyle" in master and "otherStyle" in master)
check("…whose default run colour is the theme's TEXT colour, named explicitly",
      'val="tx1"' in master)
check("…and an explicit background from bg1, so the slide is definitively white",
      "<p:bg>" in master and 'val="bg1"' in master)
theme = z.read("ppt/theme/theme1.xml").decode()
check("the theme has all twelve scheme colours",
      theme.count("<a:accent") == 6 and "<a:dk1>" in theme and "<a:lt1>" in theme
      and "<a:dk2>" in theme and "<a:lt2>" in theme and "<a:hlink>" in theme
      and "<a:folHlink>" in theme)
check("…a font scheme", "majorFont" in theme and "minorFont" in theme)
# A short fmtScheme list is what sends a real editor to a repair dialog.
check("…and a fmtScheme with THREE of each style list",
      theme.count("<a:fillStyleLst>") == 1 and theme.count("<a:ln ") == 3
      and theme.count("<a:effectStyle>") == 3)
for part in ("slideMaster1.xml", "slideLayout1.xml", "slide1.xml"):
    p = [n for n in names if n.endswith("/" + part)][0]
    check(f"{part} has the required <p:spTree> group header",
          "<p:spTree>" in z.read(p).decode())
# blank_bytes must REFUSE a type it has no package for, rather than quietly handing back
# a spreadsheet behind a "New presentation" button.
try:
    officeblank.blank_bytes(".xlsx")
    check("blank_bytes refuses .xlsx (the spreadsheet path is the mapper's)", False)
except KeyError:
    check("blank_bytes refuses .xlsx (the spreadsheet path is the mapper's)", True)


# ══ 3–5. THE STORE, EXECUTED ══════════════════════════════════════════════════
work = tempfile.mkdtemp(prefix="office-types-")
try:
    os.makedirs(os.path.join(work, "data", "office"))
    D = os.path.join(work, "data", "office")

    eq("create a spreadsheet (the historic New)", office.create_doc(work, "s")[0],
       "s.xlsx")
    eq("create a document", office.create_doc(work, "n", ".docx")[0], "n.docx")
    eq("create a presentation", office.create_doc(work, "d", ".pptx")[0], "d.pptx")
    eq("…and an EMPTY name plus a type still gets the never-clobber walk",
       office.create_doc(work, "", ".pptx")[0], "Untitled.pptx")
    check("a bogus type is refused rather than silently made a spreadsheet",
          office.create_doc(work, "x", ".txt")[0] is None)
    check("…and the refusal names what IS stored",
          ".pptx" in (office.create_doc(work, "x", ".txt")[1] or ""))
    check("a second create with the same name is refused, in the right NOUN",
          "presentation" in (office.create_doc(work, "d", ".pptx")[1] or ""))

    rows = {r["name"]: r for r in office.list_docs(work)}
    eq("all three land in the list", sorted(rows),
       ["Untitled.pptx", "d.pptx", "n.docx", "s.xlsx"])
    eq("…each row carrying its kind", rows["n.docx"]["kind"], "doc")
    eq("…and its extension", rows["d.pptx"]["ext"], ".pptx")
    check("…and the blank packages are real files with real sizes",
          rows["n.docx"]["size_bytes"] > 400 and rows["d.pptx"]["size_bytes"] > 2000)

    # ── the content path refuses, everywhere, with a sentence ────────────────
    for name in ("n.docx", "d.pptx"):
        noun = office.noun_of(name)
        r = office.require_sheet(name)
        check(f"require_sheet refuses {name}", bool(r))
        check(f"…naming what it IS ({noun})", noun in r, r)
        check("…and saying who CAN edit it", "full editor" in r, r)
        check("…and that nothing here rewrites it, so nothing can be lost",
              "never rewrite" in r or "can be lost" in r, r)
        check(f"open_doc refuses {name}", office.open_doc(work, name)[0] is None)
        check(f"save_doc refuses {name}", office.save_doc(work, name, {})[0] is None)
        try:
            office.snapshot_from_path(os.path.join(D, name))
            check(f"snapshot_from_path refuses {name}", False)
        except office.OfficeError as e:
            check(f"snapshot_from_path refuses {name}", noun in str(e))
        try:
            office.write_snapshot(office.empty_snapshot(name), os.path.join(D, name))
            check(f"write_snapshot refuses {name}", False)
        except office.OfficeError as e:
            check(f"write_snapshot refuses {name}", noun in str(e))
        # and the AGENT tools
        check(f"office_read refuses {name}",
              office_ops.op_read(work, name)[0] is None)
        check(f"office_sheet_stats refuses {name}",
              office_ops.op_sheet_stats(work, name)[0] is None)
        rr = office_ops.stage_changes(work, "sess", name, None,
                                      [{"op": "set", "at": "A1", "values": [["x"]]}])
        check(f"office_stage_changes refuses {name}", rr[0] is None)
        check("…with the same sentence, not a type error", noun in (rr[1] or ""), rr[1])
    check("…and the .xlsx still works, which is the whole point of the split",
          office.open_doc(work, "s.xlsx")[0] is not None)

    # the tool LIST tells the model the fact instead of only refusing later
    lst = office_ops.op_list(work)
    check("office_list carries `kind` per row so the model never has to guess",
          all("kind" in f for f in lst["files"]))
    check("…and a note saying which kind these tools can change",
          any("kind 'sheet'" in n for n in lst["notes"]), lst["notes"])

    # ── the package verifier ────────────────────────────────────────────────
    check("a .docx that is really a .pptx is refused on import",
          office.import_doc(work, "z.docx", officeblank.blank_bytes(".pptx"))[0] is None)
    check("…and the refusal explains the rename, because that is what happened",
          "renamed" in (office.import_doc(
              work, "z.docx", officeblank.blank_bytes(".pptx"))[1] or ""))
    check("a zip that is no Office package at all is refused",
          office.verify_package(b"PK\x03\x04nonsense", ".docx") is not None)
    check("…and so are bytes that are not a zip",
          office.verify_package(b"hello", ".pptx") is not None)
    check("a real package passes",
          office.verify_package(officeblank.blank_bytes(".docx"), ".docx") is None)
    check("import of a real .pptx works and keeps the name",
          office.import_doc(work, "ok.pptx",
                            officeblank.blank_bytes(".pptx"))[0]["name"] == "ok.pptx")

    # ── the write-back: the editor's own bytes, type-checked ────────────────
    rep, err = oomod.writeback(office, work, "n.docx",
                               officeblank.blank_bytes(".pptx"))
    check("the write-back REFUSES a package that is not what the name claims",
          rep is None and err[0] == 400, err)
    # `unfenced=True` because this call is not testing the fence and has no mtime to
    # fence with — and since bug-echo W-01 that has to be SAID rather than defaulted.
    rep, err = oomod.writeback(office, work, "n.docx",
                               officeblank.blank_bytes(".docx"), unfenced=True)
    check("…and accepts the right one", rep is not None, err)
    check("…taking the daily safety copy WITH THE RIGHT EXTENSION",
          rep and rep["backup"].endswith(".bak.docx"), rep)
    rep, err = oomod.writeback(office, work, "n.docx", b"not a zip at all")
    check("junk bytes are refused, in the right noun",
          rep is None and "document" in err[1], err)

    # ── rename may change the stem, never the type ──────────────────────────
    eq("rename keeps the extension when none is given",
       office.rename_doc(work, "n.docx", "notes")[0], "notes.docx")
    check("a rename that would change the TYPE is refused",
          office.rename_doc(work, "notes.docx", "notes.xlsx")[0] is None)
    check("…and says which extension it will accept",
          ".docx" in (office.rename_doc(work, "notes.docx", "notes.xlsx")[1] or ""))
    check("free_name's ' (n)' walk keeps the extension too",
          office.free_name(work, "d.pptx")[0] == "d (2).pptx")
finally:
    import shutil
    shutil.rmtree(work, ignore_errors=True)


# ══ 6. THE PANEL ══════════════════════════════════════════════════════════════
PAGE = (ROOT / "bridge" / "panel" / "office.html").read_text()
OO = (ROOT / "bridge" / "panel" / "oo.html").read_text()
ROUTES = (ROOT / "bridge" / "routers" / "office.py").read_text()

check("/api/office/files reports all three extensions and the kind map",
      '"exts": list(_office.DOC_EXTS)' in ROUTES and '"kinds": _office.KINDS' in ROUTES)
check("…and the per-type fidelity sentence for the two it never rewrites",
      "FIDELITY_BLOB_NOTE" in ROUTES and "FIDELITY_BLOB_NOTE" in
      (ROOT / "bridge" / "office.py").read_text())
check("POST /api/office/new takes a KIND (what the card says) as well as an ext",
      '(body or {}).get("kind")' in ROUTES and "_office.create_doc, ROOT, want, ext"
      in ROUTES)
check("…and refuses a kind it does not know rather than defaulting to a spreadsheet",
      "there is no “" in ROUTES)
check("download's media type follows the FILE, not a hardcoded spreadsheet",
      "_office.MEDIA_TYPES.get(" in ROUTES
      and "spreadsheetml.sheet\"," not in ROUTES.split("def office_download")[1])

check("the start screen offers all three, as CARDS",
      'id="h-blank"' in PAGE and 'id="h-doc"' in PAGE and 'id="h-deck"' in PAGE)
check("…labelled for what they make",
      "Blank document" in PAGE and "Blank presentation" in PAGE)
check("…and the File menu has the same two, so there is one place to look either way",
      'id="mi-newdoc"' in PAGE and 'id="mi-newdeck"' in PAGE)
check("both new-blob cards check for the EDITOR first — a .docx on a Mac with no "
      "editor would be a dead row made by a working button",
      "async function newBlob" in PAGE and "ooInstalled === false" in
      PAGE.split("async function newBlob")[1].split("\n}")[0])
check("every rail and start-screen row carries a TYPE BADGE",
      # THREE mentions: the builder's own signature plus the two lists that call it.
      "function typeBadge" in PAGE and "KIND_BADGE" in PAGE
      and PAGE.count("n.appendChild(typeBadge(f))") == 2)
check("…and the rail is no longer called Spreadsheets",
      ">Files</span>" in PAGE and ">Spreadsheets</span>" not in PAGE)

check("a .docx never goes through /api/office/open — that route returns a SPREADSHEET "
      "snapshot and now refuses it by name",
      "if (kindOf(name) !== 'sheet') { openBlob(name); return; }" in PAGE)
check("…and openBlob does not mount the tier-1 grid at all",
      "function openBlob" in PAGE and "renderGrid" not in
      PAGE.split("function openBlob")[1].split("\nfunction ")[0])
check("…and puts a SENTENCE in the centre while the editor comes up, not an empty grid",
      'id="blobwait"' in PAGE and "body.blobdoc #gridwrap{display:none}" in PAGE)
check("the tier-1 verbs are off for a blob, from the same one gate",
      "!editorActive() && !blobDoc" in PAGE)
check("…and Save is greyed rather than routed into a mapper that would refuse",
      "(blobDoc && !editorActive())" in PAGE)
check("…and save() refuses BEFORE the request rather than after it",
      "if (blobDoc) {" in PAGE.split("async function save()")[1][:1200])
check("the status line never calls itself a grid editor for a blob",
      "editor only" in PAGE)
check("the AI panel says it cannot see the file, and swaps its whole placeholder",
      'id="ai-empty-blob"' in PAGE and "cannot" in PAGE.split('id="ai-empty-blob"')[1][:400])
check("…and its sheet toggle is disabled with the reason on it",
      "cx.disabled = true" in PAGE)
check("…and the context note says which kind of file it is",
      "no sheet — this is a" in PAGE)
check("the fidelity sentence is PER TYPE, and the blob one comes first",
      "blobDoc || (current && kindOf(current) !== 'sheet')" in PAGE)
check("…and it makes the STRONGER promise, because it is true",
      "so nothing in it can be" in PAGE and "dropped" in PAGE)
check("the blob state is cleared wherever a document closes",
      "blobDoc = false" in PAGE and PAGE.count("blobDoc = false") >= 3)
check("the editor's document-type map already covers all three",
      "docx: 'word', pptx: 'slide'" in OO)


# ══ 7. DOWNLOAD AS PDF ════════════════════════════════════════════════════════
check("the canvas format codes are the editor's own c_oAscFileType values, per type",
      "PDF_CANVAS_FORMAT = {cell: 8194, word: 8193, slide: 8195}" in OO)
eq("…and the PDF target is 513", "const PDF_FORMAT = 513;" in OO, True)
check("⚠️ m_bIsNoBase64 is TRUE for this conversion — with false x2t decodes the raw "
      "print buffer as base64, finds no pages, and STILL returns rc 0",
      "<m_bIsNoBase64>true</m_bIsNoBase64>" in OO)
check("…and the reason is written down where the next person will read it",
      "FINDING 3" in OO and "/Count 0" in OO)
check("the fonts are a PRECONDITION, not an optimisation — an empty /working/fonts "
      "aborts the wasm module and takes SAVE with it",
      "function mountFonts" in OO and "Out of\n//       bounds memory access" in OO
      or "Out of" in OO)
check("…the font list comes from the bridge, so a bundle bump cannot leave it short",
      "/api/oo/fonts" in OO and "def font_files" in (ROOT / "bridge" / "oo.py").read_text())
check("…and a PARTIAL font set is refused rather than rendered with wrong glyphs",
      "not converting with an incomplete font set" in OO)
check("the produced PDF is RE-READ and a zero-page one is refused",
      "function pdfPageCount" in OO and "no pages — nothing was downloaded" in OO)
check("…scanning the WHOLE file, because the page tree is not near the trailer in "
      "x2t's real output (it is in its EMPTY one, which is how this got shipped wrong)",
      "SCANNED OVER THE WHOLE FILE" in OO)
check("the download is an <a download> blob click, which is what the shell's delegate "
      "turns into a real download",
      "function saveBlob" in OO and "a.download = filename" in OO)
check("…and the note says WHY a navigation would not do (WebKit CAN show a PDF)",
      "WebKit CAN show" in OO and "REPLACE the editor with a PDF viewer" in OO)
check("the export is the LIVE document, and the menu row says so",
      "asc_nativeGetPDF" in OO and "live · as it prints" in PAGE)
check("…which is stated as a consequence, not hidden: the PDF can be NEWER than the "
      "saved file", "newer than the saved" in PAGE)
check("asc_nativeGetPDF is used for ALL THREE, because asc_nativePrint's no-argument "
      "form is only implemented in the spreadsheet api",
      "FINDING 4" in OO and "frame.native.Save_End" in OO)
check("…and the length comes from that host hook, not from the buffer's size",
      "printedLen" in OO)
check("an x2t abort marks the converter dead and SAVE then refuses with the reason",
      "x2tDead = true" in OO and "x2tDead" in OO.split("async function save(")[1][:900])
check("the PDF row needs the editor and says which reason applies when it is off",
      "setRow('mm-pdf', editorActive()" in PAGE and "not installed on this Mac" in PAGE)
check("…in BOTH menus", "mm('mm-pdf', ooDownloadPdf)" in PAGE
      and "mi('mi-pdf', ooDownloadPdf)" in PAGE)
check("the editor page has its own PDF button, so the standalone surface is not a dead "
      "end for the feature that replaces Print",
      'id="btn-pdf"' in OO)
check("Print stays OFF, and About now points at Download as PDF instead of at a "
      "printer we do not have",
      "print: false" in OO and "DOWNLOAD AS PDF REPLACES IT" in PAGE)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("office types + PDF OK — all checks passed")
