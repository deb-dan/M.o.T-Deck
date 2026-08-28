"""BLANK .docx / .pptx — written here, byte for byte, from the OOXML package rules.

⚠️ WHY THIS FILE EXISTS INSTEAD OF A VENDORED TEMPLATE.
"New document" and "New presentation" need an empty file to hand the editor, and there
were four ways to get one. Three were rejected:

  · A .docx/.pptx downloaded from anywhere — a file of unverifiable origin, which is
    the one thing this project has already ruled it will never ship (the ONLYOFFICE
    probe's Track A ruling, condition #4).
  · python-docx / python-pptx — NOT installed in the bridge venv (checked: both
    ImportError), so this would mean a new dependency and a new install step for two
    files that never change.
  · A template exported from the ONLYOFFICE bundle — it ships none (searched).

So the packages are BUILT HERE, from the OOXML spec, using nothing but `zipfile`. That
makes the provenance the strongest available: every byte is in this file, in plain
XML, readable by whoever comes next, and reproducible — `blank_bytes` is deterministic
(fixed zip timestamps, fixed member order, no compression randomness), so a test can
pin its sha256 and a change cannot slip in unnoticed.

⚠️ AND THEY ARE NOT TAKEN ON TRUST. A minimal package that a parser tolerates and an
EDITOR rejects would be a "New presentation" button that opens a broken document. So
bridge/tests/test_office_lane.py checks the package structure, and the journey test
opens both in the real editor, types into them, saves back and reopens — which is the
only proof that matters.

WHAT "MINIMAL" MEANS HERE. Exactly the parts the format REQUIRES, and no others: no
docProps (optional), no core/app properties (optional), no numbering, styles or
settings for Word (all optional — the editor supplies its own defaults and writes them
on the first save), and for PowerPoint the required chain of
presentation → slideMaster → slideLayout → slide plus ONE complete theme, because
a slide master without a resolvable theme is where minimal PPTX attempts usually break.
"""
from __future__ import annotations

import io
import zipfile

# One fixed timestamp for every member: 1980-01-01 00:00:00, the earliest a zip can
# express. This is what makes the output byte-identical on every call and therefore
# hashable in a test. (A real-time timestamp would also leak when the file was made,
# which is nobody's business.)
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)

_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_XML_HEAD = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n')


def _rels(items) -> str:
    """A .rels part. `items` is a list of (id, type-suffix, target)."""
    body = "".join(
        f'<Relationship Id="{i}" Type="{_NS_OFFICE_REL}/{t}" Target="{tgt}"/>'
        for i, t, tgt in items)
    return f'{_XML_HEAD}<Relationships xmlns="{_NS_PKG_REL}">{body}</Relationships>'


# ── the empty DrawingML shape tree, shared by master, layout and slide ────────
# Every PresentationML part that can hold shapes must hold a <p:spTree> with a group
# shape header, even when it holds nothing. Omitting it is the single most common way a
# hand-built .pptx opens as "repair needed".
_EMPTY_SPTREE = (
    "<p:spTree>"
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
    "</p:spTree>")


def _p_root(tag, extra_attrs="", body="") -> str:
    return (f'{_XML_HEAD}<p:{tag} xmlns:a="{_NS_A}" xmlns:r="{_NS_OFFICE_REL}" '
            f'xmlns:p="{_NS_P}"{extra_attrs}>{body}</p:{tag}>')


# ── the theme, and it is the part that cannot be skimped ─────────────────────
# `fmtScheme` must carry THREE fills, THREE line styles, THREE effect styles and THREE
# background fills; a short list is what makes editors fall back to a repair dialog.
# The palette is Office's own default (Office 2013+ "Office" theme values), so a
# presentation made here looks like one made anywhere else.
def _theme() -> str:
    def dk(tag, val, kind="srgbClr"):
        return f'<a:{tag}><a:{kind} val="{val}"/></a:{tag}>'
    clr = ("<a:clrScheme name=\"Office\">"
           + '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
           + '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
           + dk("dk2", "44546A") + dk("lt2", "E7E6E6")
           + dk("accent1", "4472C4") + dk("accent2", "ED7D31")
           + dk("accent3", "A5A5A5") + dk("accent4", "FFC000")
           + dk("accent5", "5B9BD5") + dk("accent6", "70AD47")
           + dk("hlink", "0563C1") + dk("folHlink", "954F72")
           + "</a:clrScheme>")
    font = ('<a:fontScheme name="Office">'
            '<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/>'
            '<a:cs typeface=""/></a:majorFont>'
            '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/>'
            '<a:cs typeface=""/></a:minorFont></a:fontScheme>')
    solid = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = ('<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr">' + solid
            + '<a:prstDash val="solid"/></a:ln>')
    fmt = ('<a:fmtScheme name="Office">'
           f'<a:fillStyleLst>{solid}{solid}{solid}</a:fillStyleLst>'
           f'<a:lnStyleLst>{line}{line}{line}</a:lnStyleLst>'
           '<a:effectStyleLst>'
           '<a:effectStyle><a:effectLst/></a:effectStyle>'
           '<a:effectStyle><a:effectLst/></a:effectStyle>'
           '<a:effectStyle><a:effectLst/></a:effectStyle>'
           '</a:effectStyleLst>'
           f'<a:bgFillStyleLst>{solid}{solid}{solid}</a:bgFillStyleLst>'
           '</a:fmtScheme>')
    return (f'{_XML_HEAD}<a:theme xmlns:a="{_NS_A}" name="Office Theme">'
            f'<a:themeElements>{clr}{font}{fmt}</a:themeElements>'
            "<a:objectDefaults/><a:extraClrSchemeLst/></a:theme>")


_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_CT_DOCX = ("application/vnd.openxmlformats-officedocument.wordprocessingml"
            ".document.main+xml")
_CT_PPTX = ("application/vnd.openxmlformats-officedocument.presentationml"
            ".presentation.main+xml")


def _docx_parts() -> list:
    """(path, text) members of a minimal, valid, EMPTY .docx, in package order.

    One empty paragraph and a section with A4 page size and 2 cm margins — the same
    defaults ONLYOFFICE and Word start a blank document with, stated explicitly so the
    first page does not depend on whose default wins.
    """
    types = (f'{_XML_HEAD}<Types xmlns="{_CT}">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
             'package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             f'<Override PartName="/word/document.xml" ContentType="{_CT_DOCX}"/>'
             "</Types>")
    root_rels = _rels([("rId1", "officeDocument", "word/document.xml")])
    doc = (f'{_XML_HEAD}<w:document xmlns:w="{_NS_W}"><w:body><w:p/>'
           '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
           '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" '
           'w:header="0" w:footer="0" w:gutter="0"/></w:sectPr>'
           "</w:body></w:document>")
    return [("[Content_Types].xml", types),
            ("_rels/.rels", root_rels),
            ("word/document.xml", doc)]


def _pptx_parts() -> list:
    """(path, text) members of a minimal, valid .pptx with ONE blank 16:9 slide."""
    over = [("/ppt/presentation.xml", _CT_PPTX),
            ("/ppt/slideMasters/slideMaster1.xml",
             "application/vnd.openxmlformats-officedocument.presentationml"
             ".slideMaster+xml"),
            ("/ppt/slideLayouts/slideLayout1.xml",
             "application/vnd.openxmlformats-officedocument.presentationml"
             ".slideLayout+xml"),
            ("/ppt/slides/slide1.xml",
             "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"),
            ("/ppt/theme/theme1.xml",
             "application/vnd.openxmlformats-officedocument.theme+xml")]
    types = (f'{_XML_HEAD}<Types xmlns="{_CT}">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
             'package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             + "".join(f'<Override PartName="{p}" ContentType="{c}"/>'
                       for p, c in over)
             + "</Types>")
    root_rels = _rels([("rId1", "officeDocument", "ppt/presentation.xml")])
    # 12192000 × 6858000 EMU = 13.333in × 7.5in = the 16:9 default every current
    # PowerPoint and ONLYOFFICE uses for a new deck.
    pres = _p_root(
        "presentation",
        body=('<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/>'
              "</p:sldMasterIdLst>"
              '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>'
              '<p:sldSz cx="12192000" cy="6858000"/>'
              '<p:notesSz cx="6858000" cy="9144000"/>'))
    pres_rels = _rels([
        ("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
        ("rId2", "slide", "slides/slide1.xml"),
        ("rId3", "theme", "theme/theme1.xml")])
    clr_map = ('<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" '
               'accent2="accent2" accent3="accent3" accent4="accent4" '
               'accent5="accent5" accent6="accent6" hlink="hlink" '
               'folHlink="folHlink"/>')
    # ⚠️ THE BACKGROUND AND THE TEXT STYLES ARE NOT OPTIONAL POLISH — THEY ARE WHAT STOPS
    # A BLANK DECK DEFAULTING TO INVISIBLE TEXT. `<p:txStyles>` is where a master says
    # what a run with no explicit formatting looks like; a master without it leaves that
    # to whatever the application falls back to, and the fallback resolves through the
    # style matrix, which for an inserted shape is `lt1` — WHITE. Measured on the first
    # cut of this template: a marker added to slide 1 round-tripped perfectly through
    # save and reopen (so the package was fine) and rendered as WHITE ON WHITE in the
    # exported PDF. A document that keeps your words and does not show them is the
    # worst of both. So: an explicit white background from `bg1`, and title/body/other
    # styles that name `tx1` and the theme's minor font.
    def _lvl(sz):
        return ('<a:defRPr sz="%d" kern="1200"><a:solidFill>'
                '<a:schemeClr val="tx1"/></a:solidFill>'
                '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/>'
                '<a:cs typeface="+mn-cs"/></a:defRPr>' % sz)
    lvls = "".join(f'<a:lvl{i}pPr marL="{(i - 1) * 457200}" algn="l">{_lvl(1800)}'
                   f"</a:lvl{i}pPr>" for i in range(1, 10))
    tx_styles = ("<p:txStyles>"
                 f'<p:titleStyle><a:lvl1pPr algn="l">{_lvl(4400)}</a:lvl1pPr>'
                 "</p:titleStyle>"
                 f"<p:bodyStyle>{lvls}</p:bodyStyle>"
                 f"<p:otherStyle>{lvls}</p:otherStyle>"
                 "</p:txStyles>")
    bg = ('<p:bg><p:bgPr><a:solidFill><a:schemeClr val="bg1"/></a:solidFill>'
          "<a:effectLst/></p:bgPr></p:bg>")
    master = _p_root("sldMaster",
                     body=f"<p:cSld>{bg}{_EMPTY_SPTREE}</p:cSld>{clr_map}"
                          '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" '
                          'r:id="rId1"/></p:sldLayoutIdLst>'
                          + tx_styles)
    master_rels = _rels([
        ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
        ("rId2", "theme", "../theme/theme1.xml")])
    layout = _p_root("sldLayout", extra_attrs=' type="blank" preserve="1"',
                     body=f'<p:cSld name="Blank">{_EMPTY_SPTREE}</p:cSld>'
                          "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>")
    layout_rels = _rels([
        ("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")])
    slide = _p_root("sld", body=f"<p:cSld>{_EMPTY_SPTREE}</p:cSld>"
                                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>")
    slide_rels = _rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")])
    return [("[Content_Types].xml", types),
            ("_rels/.rels", root_rels),
            ("ppt/presentation.xml", pres),
            ("ppt/_rels/presentation.xml.rels", pres_rels),
            ("ppt/slideMasters/slideMaster1.xml", master),
            ("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels),
            ("ppt/slideLayouts/slideLayout1.xml", layout),
            ("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels),
            ("ppt/slides/slide1.xml", slide),
            ("ppt/slides/_rels/slide1.xml.rels", slide_rels),
            ("ppt/theme/theme1.xml", _theme())]


PARTS = {".docx": _docx_parts, ".pptx": _pptx_parts}


def blank_bytes(ext: str) -> bytes:
    """A complete, empty OOXML package for `.docx` or `.pptx`. Deterministic.

    Raises KeyError for anything else, deliberately: this is not the place to decide
    which extensions the lane supports (office.valid_name is), and a silent .xlsx
    fallback would put a spreadsheet behind a "New presentation" button.
    """
    parts = PARTS[str(ext).lower()]()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, text in parts:
            info = zipfile.ZipInfo(path, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            z.writestr(info, text.encode("utf-8"))
    return buf.getvalue()
