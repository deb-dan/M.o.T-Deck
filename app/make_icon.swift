// make_icon.swift — THE MOT DECK APP MARK, drawn per pixel size, not downscaled once.
//
// WHY THIS FILE EXISTS AT ALL. The old mark was a single 1024px app/icon.png ("H",
// cream serif on a near-white sheet) that scripts/build_app.sh fed to `sips -z` ten
// times. That works for one glyph and falls apart for a wordmark: "M.O.T" pushed
// through a naive box filter at 16px is five smudges, and the two periods — the part
// Debi actually typed — are the first pixels a downscaler throws away.
//
// So the art is PARAMETRIC and every slot is drawn at its own pixel size, with its own
// decisions:
//
//   * ≥64px   the full "M.O.T" wordmark, cream serif, GOLD periods, gold rule under it.
//             64 is the 32@2x slot — the Finder list row on a Retina Mac — and the
//             wordmark was WALKED there at 6× magnification before this threshold was
//             set: the periods survive as single gold pixels and all three letters read.
//   * ≤32px   just "M", styled identically (same serif, same cream, same ground), and
//             WITHOUT the gold rule, which at one or two pixels high is a brown smudge
//             rather than a rule. Debi's brief authorises exactly this fallback and asks
//             that it be said out loud: at 16 and 32 real pixels there is no honest way
//             to render three glyphs and two periods — the dots land sub-pixel and the
//             M's own inner counters close up. A legible "M" that matches the family is
//             worth more than an illegible wordmark, and a 16px tile is a recognition
//             target, not a reading target.
//
// The ground is the deck's own ground (bridge/panel/index.html :root) so the app tile
// and the app it opens are the same object: --card #14121d over --bg #0b0a10, --cream
// #efe7d7 ink, --gold #d9b36c accent. Workbench, not shrine.
//
// USAGE (regenerating the mark — normally nobody has to):
//   swiftc -O app/make_icon.swift -o /tmp/mot-icon && /tmp/mot-icon app/Harness.icns
// It writes an .iconset next to the target, runs iconutil, and also refreshes
// app/icon.png (the 1024 slot) so scripts/build_app.sh's sips path — used only by a
// FULL fat rebuild — no longer produces the old "H". ship.sh copies the committed
// app/Harness.icns into the bundle on every ship, so the per-size art always wins.

import AppKit
import Foundation

// ── the deck palette, single-sourced from bridge/panel/index.html :root ───────
func hex(_ s: String, _ a: CGFloat = 1) -> NSColor {
    var v: UInt64 = 0
    Scanner(string: s).scanHexInt64(&v)
    return NSColor(srgbRed: CGFloat((v >> 16) & 0xff) / 255.0,
                   green: CGFloat((v >> 8) & 0xff) / 255.0,
                   blue: CGFloat(v & 0xff) / 255.0, alpha: a)
}
let BG = hex("0b0a10")        // --bg
let CARD = hex("14121d")      // --card
let CREAM = hex("efe7d7")     // --cream
let GOLD = hex("d9b36c")      // --gold

// ── the serif, resolved once and reported ────────────────────────────────────
// Iowan Old Style first: it is the deck's own --serif stack's second entry and the one
// with real stroke contrast at small sizes. "New York" is Apple's, ships everywhere on
// macOS 11+, and is the stack's first entry — it is second here only because Iowan's
// heavier weight holds a 32px M better. Georgia/Times are the floors.
func serif(_ size: CGFloat) -> NSFont {
    for name in ["Iowan Old Style", "New York", "Georgia", "Times New Roman"] {
        if let base = NSFont(name: name, size: size) {
            // Bold where the family has it: an app tile is seen at a glance, and the
            // regular weight of a text serif is built for a paragraph, not a 16px tile.
            let bold = NSFontManager.shared.convert(base, toHaveTrait: .boldFontMask)
            return bold
        }
    }
    return NSFont.systemFont(ofSize: size, weight: .bold)
}

let RESOLVED_SERIF = serif(64).familyName ?? "?"

/// Draw the mark at exactly `px` pixels square and return the bitmap.
func render(_ px: Int) -> NSBitmapImageRep {
    let S = CGFloat(px)
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                               isPlanar: false, colorSpaceName: .deviceRGB,
                               bytesPerRow: px * 4, bitsPerPixel: 32)!
    rep.size = NSSize(width: S, height: S)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.setAllowsAntialiasing(true)
    ctx.interpolationQuality = .high

    // ── the tile ─────────────────────────────────────────────────────────────
    // macOS icon geometry: the art is inset in its canvas (Big Sur templates use
    // 824/1024) with a corner radius of ~0.225 of the art square. Below 64px the inset
    // is clamped to 1px a side, because a proportional inset at 16px spends a quarter of
    // the tile on emptiness and leaves nothing for the glyph.
    let inset = max(S * (100.0 / 1024.0), px <= 64 ? 1 : 2)
    let art = NSRect(x: inset, y: inset, width: S - inset * 2, height: S - inset * 2)
    let radius = art.width * 0.225
    let tile = NSBezierPath(roundedRect: art, xRadius: radius, yRadius: radius)

    // Ground: --card at the top falling to --bg. A flat fill reads as a sticker; the
    // one-stop gradient is what makes it read as a surface with a light on it.
    ctx.saveGState()
    tile.addClip()
    let grad = NSGradient(colors: [CARD, BG])!
    grad.draw(in: art, angle: -90)
    ctx.restoreGState()

    // The edge. Cream at 9% — enough to lift the tile off a dark Dock, invisible on a
    // light one. Skipped under 32px, where a hairline stroke is just a grey halo.
    if px >= 32 {
        ctx.saveGState()
        let line = NSBezierPath(roundedRect: art.insetBy(dx: S / 1024 * 3, dy: S / 1024 * 3),
                                xRadius: radius, yRadius: radius)
        line.lineWidth = max(S / 1024 * 4, 1)
        CREAM.withAlphaComponent(0.09).setStroke()
        line.stroke()
        ctx.restoreGState()
    }

    // ── the lettering ────────────────────────────────────────────────────────
    let wordmark = px >= 64
    let text = wordmark ? "M.O.T" : "M"
    // Width budget inside the art box. The wordmark gets more of it than the lone M
    // does: five glyphs need the room, one glyph centred in 62% of the tile is what
    // makes it read as a monogram rather than a letter that outgrew its box.
    let budget = art.width * (wordmark ? 0.78 : 0.62)
    let capBudget = art.height * (wordmark ? 0.42 : 0.62)

    // Solve the point size by measurement, not by a magic ratio: the four candidate
    // serifs have different cap heights and different period advances, and a hardcoded
    // ratio would silently mis-size the mark on a machine where Iowan is absent.
    var pt = capBudget * 2.0
    let tracking = wordmark ? -0.02 : 0.0     // periods sit tight in a wordmark
    func attrs(_ p: CGFloat) -> [NSAttributedString.Key: Any] {
        [.font: serif(p), .foregroundColor: CREAM, .kern: p * tracking]
    }
    for _ in 0..<60 {
        let w = (text as NSString).size(withAttributes: attrs(pt)).width
        let capH = serif(pt).capHeight
        if w <= budget && capH <= capBudget { break }
        pt *= min(budget / max(w, 0.01), capBudget / max(capH, 0.01)) * 0.995
    }
    let font = serif(pt)

    // Baseline placement uses CAP HEIGHT, not the font's line box: a serif's line box
    // carries descender and leading that no glyph in "M.O.T" occupies, so centring the
    // line box leaves the mark visibly high. The optical centre is nudged up by the
    // gold rule's share of the composition.
    let ruleGap = S * (wordmark ? 0.055 : 0.075)
    let ruleH = max(S * (wordmark ? 0.028 : 0.034), 1)
    let ruleW = art.width * (wordmark ? 0.42 : 0.30)
    // The rule is a ≥64px affordance. At 32 real pixels it is one or two rows of gold
    // under a glyph, which does not read as a rule — it reads as dirt on the tile (looked
    // at, magnified 10×, before this line was written). Below 64 the M carries the mark
    // alone and gets the height the rule would have taken.
    let showRule = wordmark
    let blockH = font.capHeight + (showRule ? ruleGap + ruleH : 0)
    let baseline = art.midY - blockH / 2 + (showRule ? ruleGap + ruleH : 0)

    let str = NSMutableAttributedString(string: text, attributes: attrs(pt))
    // GOLD PERIODS. They are the part of "M.O.T" Debi typed and the part a plain
    // one-colour wordmark loses first — in cream they read as dirt at 128px. In gold
    // they read as deliberate punctuation and they tie the mark to the deck's accent.
    if wordmark {
        for (i, ch) in text.enumerated() where ch == "." {
            str.addAttribute(.foregroundColor, value: GOLD, range: NSRange(location: i, length: 1))
        }
    }
    let textW = str.size().width
    // -font.descender puts the DRAW origin where the baseline lands (drawing y is the
    // line box bottom, which sits `descender` below the baseline).
    str.draw(at: NSPoint(x: art.midX - textW / 2, y: baseline + font.descender))

    // The gold rule — inherited from the old "H" mark on purpose. It is the one piece of
    // the previous tile worth keeping: it is what made that icon look like a plate rather
    // than a letter, and keeping it means the change of glyph does not read as a change
    // of product.
    if showRule {
        let r = NSRect(x: art.midX - ruleW / 2, y: baseline - ruleGap - ruleH,
                       width: ruleW, height: ruleH)
        GOLD.setFill()
        NSBezierPath(roundedRect: r, xRadius: ruleH / 2, yRadius: ruleH / 2).fill()
    }

    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func writePNG(_ rep: NSBitmapImageRep, _ path: String) throws {
    guard let data = rep.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "makeicon", code: 1,
                      userInfo: [NSLocalizedDescriptionKey: "PNG encode failed for \(path)"])
    }
    try data.write(to: URL(fileURLWithPath: path))
}

// ── main ─────────────────────────────────────────────────────────────────────
let args = CommandLine.arguments
let target = args.count > 1 ? args[1] : "app/Harness.icns"
let outDir = (target as NSString).deletingLastPathComponent
let iconset = (outDir.isEmpty ? "." : outDir) + "/Harness.iconset"
let fm = FileManager.default
try? fm.removeItem(atPath: iconset)
try fm.createDirectory(atPath: iconset, withIntermediateDirectories: true)

// The ten slots iconutil expects. (name, real pixel size) — note 16@2x and 32 are BOTH
// 32 real pixels and are drawn identically, which is correct: they are the same art at
// the same resolution, requested by two different display paths.
let slots: [(String, Int)] = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]
for (name, px) in slots {
    try writePNG(render(px), iconset + "/" + name)
}
FileHandle.standardError.write(
    "[make_icon] serif: \(RESOLVED_SERIF) · wordmark ≥64px · 'M' at ≤32px\n".data(using: .utf8)!)

let p = Process()
p.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
p.arguments = ["-c", "icns", iconset, "-o", target]
try p.run()
p.waitUntilExit()
guard p.terminationStatus == 0 else {
    FileHandle.standardError.write("[make_icon] iconutil FAILED (\(p.terminationStatus))\n".data(using: .utf8)!)
    exit(2)
}

// app/icon.png stays in sync so a FULL fat rebuild (scripts/build_app.sh, which sips
// this file into an iconset of its own) no longer ships the retired "H". Its 16px slot
// will be a downscale of the wordmark rather than the drawn "M" — that path is for a
// from-scratch bundle build only, and the next ./scripts/ship.sh copies the real
// per-size .icns over it.
try writePNG(render(1024), (outDir.isEmpty ? "." : outDir) + "/icon.png")

// Leave the iconset on disk: it is what a human LOOKS AT to check the 16px slot, which
// is the whole point of drawing per size. It is gitignored by app/.gitignore.
print("[make_icon] wrote \(target) (+ \(iconset), + app/icon.png)")
