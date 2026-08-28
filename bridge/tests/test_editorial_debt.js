/* EDITORIAL'S IMPECCABLE DEBT — the fence (v1.5.24).
 *
 * WHY THIS FILE EXISTS. The studio-design slice measured the DEFAULT design live and
 * found it failing the same detector set studio passes at zero: low-contrast ink,
 * line-length overruns, undersized text, one chromatic glow. Those numbers lived in a
 * report, which means they were a claim. This slice repaid the debt; this file turns the
 * repayment into a constraint, so the ramp cannot drift back and the argued exceptions
 * cannot quietly multiply.
 *
 * WHAT IS FENCED, and the shape of each fact:
 *   1. THE QUIET-INK RAMP, ARITHMETICALLY. Every ink token is re-contrasted against
 *      every ground of its OWN palette, in all four Editorial palettes, from the hex in
 *      the file. Not "the hex is #847e98" — "whatever the hex is, it clears 4.5:1 on
 *      --bg, --bg2, --card and --card2, and the ramp faint < dim < fg still separates".
 *      A future palette edit that looks nicer and reads worse fails here.
 *   2. THE TYPE FLOOR. No font declaration under 10px, with ONE pinned exception
 *      (#chat-talk / #chat-auto / #chat-conv at 9.5px, which overrode a standing Debi
 *      ruling and is therefore named in the assertion rather than tolerated by a range).
 *   3. THE MEASURE CAPS, and the ONE ruled overrun. .sub, .cap-desc and .card .meta.wrap
 *      carry a ch cap; `.cmsg.assistant .body` is pinned at max-width:none WITH its
 *      reason, so a future tidy-up cannot "fix" a Debi ruling by accident.
 *   4. THE ONE GLOW. Exactly one chromatic blurred shadow exists in Editorial's sheet and
 *      it is `.dot.ok`. The exception is allowed; a SECOND one fails the build.
 *   5. THE HARDCODED-LITERAL CLASS. The near-black that sat on the accent fill is a token
 *      now; the literal may not come back, at any site.
 *   6. THE COLLAPSED SESSIONS RAIL, per design. Geometry, the 44px hit floor on both
 *      axes, the labelled reopener, and studio's specificity restatement of all of it.
 *
 * Thresholds are the ones the live sweep used, and they are stated where they are used.
 * Run: node bridge/tests/test_editorial_debt.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const sd = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];
const noC = css.replace(/\/\*[\s\S]*?\*\//g, '');
const sdNoC = sd.replace(/\/\*[\s\S]*?\*\//g, '');

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok  ' : '  FAIL ') + msg); if (!cond) fails++; }
function eq(msg, got, want) {
  const same = JSON.stringify(got) === JSON.stringify(want);
  ok(same, msg + (same ? '' : ' — got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)));
}

// the brace-matching walker the other design fences use (comments first: they carry braces)
function rules(src) {
  const out = []; let i = 0;
  while (i < src.length) {
    const b = src.indexOf('{', i); if (b < 0) break;
    const sel = src.slice(i, b).trim();
    let d = 1, j = b + 1;
    while (j < src.length && d > 0) { if (src[j] === '{') d++; else if (src[j] === '}') d--; j++; }
    out.push({ sel, body: src.slice(b + 1, j - 1), at: sel.startsWith('@') });
    i = j;
  }
  return out;
}
const ALL = rules(noC);
const SDALL = rules(sdNoC);

// ── WCAG arithmetic, from the hex in the file (the theme-pack fence's pattern) ──
const hex = h => ({ r: parseInt(h.slice(1, 3), 16), g: parseInt(h.slice(3, 5), 16), b: parseInt(h.slice(5, 7), 16) });
const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
const ratio = (a, b) => { const l1 = lum(hex(a)), l2 = lum(hex(b));
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
const r2 = (a, b) => +ratio(a, b).toFixed(2);

function tokensOf(sel) {
  const rs = ALL.filter(r => r.sel === sel);
  const out = {};
  for (const r of rs) for (const m of r.body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+)/g)) out[m[1]] = m[2].trim();
  return out;
}
const BASE = tokensOf(':root');
const PAL = {
  'Editorial (default dark)': BASE,
  'Warm Paper': { ...BASE, ...tokensOf('html[data-theme="light"]') },
  'Luxury Gold': { ...BASE, ...tokensOf('html[data-theme="gold"]') },
  'Cyber': { ...BASE, ...tokensOf('html[data-theme="cyber"]') },
};
const GROUNDS = ['--bg', '--bg2', '--card', '--card2'];

// ═══════════════════════════════════════════════════════════════════════════════
// 1. THE QUIET-INK RAMP — measured, in every palette, on every ground
// ═══════════════════════════════════════════════════════════════════════════════
console.log('1. the quiet-ink ramp (WCAG AA, computed from the file)');
const AA = 4.5;
{
  ok(Object.keys(BASE).length > 15, ':root still declares the base palette ('
     + Object.keys(BASE).length + ' tokens)');
  for (const [name, p] of Object.entries(PAL)) {
    for (const ink of ['--faint', '--dim', '--fg', '--cream']) {
      const worst = Math.min(...GROUNDS.map(g => ratio(p[ink], p[g])));
      ok(worst >= AA, name + ': ' + ink + ' ' + p[ink] + ' clears AA on its own four '
         + 'grounds (worst ' + worst.toFixed(2) + ' ≥ ' + AA + ')');
    }
    // --gold is INK as often as it is a fill (kickers, links, +New, the accent numeral)
    const goldWorst = Math.min(...GROUNDS.map(g => ratio(p['--gold'], p[g])));
    ok(goldWorst >= AA, name + ': --gold ' + p['--gold'] + ' is used as INK and clears AA '
       + 'too (worst ' + goldWorst.toFixed(2) + ') — Warm Paper is the palette this caught');
    // THE RAMP MUST STILL BE A RAMP. Raising both inks to the floor collapses them into
    // each other (both solve to ~#847e98 in the default palette); the separation has to
    // live ABOVE the floor. 1.25x on the --bg reading is the pinned minimum step.
    const f = ratio(p['--faint'], p['--bg']), d = ratio(p['--dim'], p['--bg']),
          g = ratio(p['--fg'], p['--bg']);
    ok(d / f >= 1.25, name + ': --dim is a real step above --faint (' + d.toFixed(2) + ' / '
       + f.toFixed(2) + ' = ' + (d / f).toFixed(2) + 'x ≥ 1.25) — the ramp did not collapse '
       + 'into one grey when it was raised');
    ok(g / d >= 1.25, name + ': …and --fg is a real step above --dim (' + (g / d).toFixed(2) + 'x)');
    ok(f < d && d < g, name + ': …and the order faint < dim < fg is intact');
  }
}
// the ink that sits ON the accent fill, both grounds it is used on
console.log('   the accent fills');
{
  for (const [name, p] of Object.entries(PAL)) {
    ok(!!p['--on-accent'], name + ' declares --on-accent (the ink on a --gold fill)');
    ok(ratio(p['--on-accent'], p['--gold']) >= AA,
       name + ': --on-accent on --gold = ' + r2(p['--on-accent'], p['--gold']) + ' ≥ ' + AA);
    // the cream-filled primary takes --bg, which is by construction the right ink
    ok(ratio(p['--bg'], p['--cream']) >= AA,
       name + ': --bg on a --cream fill = ' + r2(p['--bg'], p['--cream']) + ' ≥ ' + AA
       + ' (Warm Paper measured 1.08 with the old hardcoded near-black)');
  }
  // the packs must COVER the new token or they are half-painted (the theme-pack rule)
  for (const pack of ['gold', 'cyber']) {
    const t = tokensOf('html[data-theme="' + pack + '"]');
    ok(!!t['--on-accent'], 'the ' + pack + ' pack declares --on-accent itself');
  }
  // …and so must the design axis, whose token block covers every :root token
  ok(/--on-accent\s*:/.test(sdNoC), 'the studio design declares --on-accent too');
  eq('…in BOTH of its variants', (sdNoC.match(/--on-accent\s*:/g) || []).length, 2);
}
// no ink is painted with a BORDER token (the .cch-sep category error)
{
  const inkFromLine = ALL.filter(r => /color:\s*var\(--line2?\)\s*[;}]/.test(r.body)
    && !/border|scrollbar|outline/.test(r.body.match(/[a-z-]*color:\s*var\(--line2?\)/)[0]));
  eq('no rule paints TEXT with a hairline token (--line / --line2 are borders; '
     + '.cch-sep read 1.40:1 that way)', inkFromLine.map(r => r.sel.slice(0, 50)), []);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. THE TYPE FLOOR — 10px, with one named exception
// ═══════════════════════════════════════════════════════════════════════════════
console.log('2. the type floor (Editorial\'s own 10px voice floor)');
{
  const FLOOR = 10;
  const EXEMPT = '#chat-talk, #chat-auto, #chat-conv';
  const under = [];
  for (const r of ALL) {
    for (const m of r.body.matchAll(/font(?:-size)?:\s*([\d.]+)px/g)) {
      const v = parseFloat(m[1]);
      if (v < FLOOR) under.push({ sel: r.sel, size: v });
    }
  }
  eq('every font declaration under ' + FLOOR + 'px belongs to the ONE argued exception '
     + '(the talk / auto / conv chips — see their rule, which says why and says whose '
     + 'ruling it overrode)', under.map(u => u.sel).sort(), [EXEMPT]);
  eq('…and that exception is at 9.5px, a step Editorial\'s ramp already used — not a new size',
     under.map(u => u.size), [9.5]);
  // the 7px original is gone for good
  ok(!/font(?:-size)?:\s*[0-8](\.\d+)?px/.test(noC),
     'nothing in the sheet is 8px or smaller any more (the 7px talk label was the smallest '
     + 'ink in the panel)');
  // and no renderer smuggles one back in through an inline style
  ok(!/font-size:\s*[0-9](\.\d+)?px/.test(html.split('</style>')[1]),
     '…and no INLINE style in the page script sets a sub-10px font either (an inline style '
     + 'is unreachable by every axis — the defect class this slice hit twice)');
  // the identity that is deliberately KEPT is present, so "we kept the voice" is checkable
  const caps = ALL.filter(r => /font:\s*10(\.5)?px var\(--mono\)/.test(r.body)
                            && /text-transform:\s*uppercase/.test(r.body));
  ok(caps.length >= 10, 'Editorial\'s tracked mono micro-caps voice is still there in '
     + caps.length + ' rules at 10/10.5px — this slice repaid debt, it did not redesign '
     + '(impeccable\'s floor is 11px; keeping these is the argued identity exception, and '
     + 'their readability was paid for on the CONTRAST axis in section 1)');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. THE MEASURE CAPS — and the one overrun Debi ruled
// ═══════════════════════════════════════════════════════════════════════════════
console.log('3. reading measure (impeccable line-length: width/(font-size × 0.5), trips > 85)');
{
  // Each capped site, with the live reading that earned the cap.
  const CAPPED = [
    ['.sub', 113.5],
    ['.cap-row .cap-desc', 155.7],
    ['.card .meta.wrap', 169.1],
  ];
  for (const [sel, was] of CAPPED) {
    const r = ALL.find(x => x.sel === sel);
    ok(!!r, sel + ' still exists');
    if (!r) continue;
    const m = /max-width:\s*(\d+)ch/.exec(r.body);
    ok(!!m, sel + ' carries a ch measure cap (it measured ' + was + 'ch live before it)');
    if (m) ok(+m[1] <= 70, '…and the cap is ' + m[1] + 'ch ≤ 70ch, which lands the '
       + 'estimator inside 85');
  }
  // THE RULED EXCEPTION, pinned so it cannot be "fixed"
  const body = ALL.filter(x => x.sel === '.cmsg.assistant .body').map(x => x.body).join(' ');
  ok(/max-width:\s*none/.test(body),
     'the assistant transcript is STILL max-width:none — Editorial runs the transcript '
     + 'full width by Debi\'s ruling (live: 107ch assistant / 99ch user, both over 85). '
     + 'This is the argued exception; studio is the design that caps the lane.');
  ok(!/Reading width is still bounded per-message/.test(css),
     '…and the comment that claimed a 68ch cap which is NOT in the file is gone (the '
     + 'source itself was the thing telling the lie, which is the worst place for one)');
  ok(/CORRECTED v1\.5\.24[\s\S]{0,700}max-width:none/.test(css),
     '…replaced by the correction, which states the real measure and whose ruling it is');
}

// the composer meta row, found by the adversarial pass
{
  const m = ALL.find(r => r.sel === '#chat-modes');
  ok(!!m && /flex-wrap:wrap/.test(m.body),
     'the composer meta row WRAPS. It is over-subscribed by design (live: 1286px of '
     + 'content in a 966px lane at 1280px wide), and with nowrap it pushed its own tail '
     + 'past the right edge of the WINDOW at 820px — #caps-strip, i.e. the tools status, '
     + 'ended at 908px in an 820px window and was unreachable. Raising the sub-10px chip '
     + 'labels made that 23px worse and pushed a third element over, so this slice owns '
     + 'it. The studio design had already answered the same row the same way.');
  ok(/row-gap/.test(m.body), '…with a row-gap, so the second line is not glued to the first');
  ok(/flex-wrap:wrap/.test((SDALL.find(r => r.sel === 'html[data-design="studio"] #chat-modes') || {}).body || ''),
     '…and that really is the answer studio already reached for this row (the two designs '
     + 'now agree instead of one of them being quietly worse)');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. THE ONE GLOW — the exception is allowed; a second one is not
// ═══════════════════════════════════════════════════════════════════════════════
console.log('4. dark-glow (chromatic blurred shadow: blur > 4px, channel spread ≥ 30)');
{
  const glows = [];
  for (const r of ALL) {
    for (const m of r.body.matchAll(/box-shadow:\s*([^;}]+)/g)) {
      for (const layer of m[1].split(/,(?![^(]*\))/)) {
        if (/^\s*none/.test(layer)) continue;
        // lengths in a box-shadow may be UNITLESS zeros in source (`0 0 8px rgba(...)`),
        // which is why this reads the ordered numeric tokens BEFORE the colour rather
        // than only the ones carrying `px` — the first draft of this check found zero
        // glows in a sheet that has one, which is a fence that would never have fired.
        const pre = layer.split(/rgba?\(|#/)[0];
        const nums = (pre.match(/-?[\d.]+/g) || []).map(parseFloat);
        const blur = nums.length >= 3 ? Math.abs(nums[2]) : 0;
        const rgb = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(layer);
        let spread = 0;
        if (rgb) { const c = [+rgb[1], +rgb[2], +rgb[3]]; spread = Math.max(...c) - Math.min(...c); }
        else if (/#[0-9a-f]{6}/i.test(layer)) { const c = hex(/#[0-9a-f]{6}/i.exec(layer)[0]);
          spread = Math.max(c.r, c.g, c.b) - Math.min(c.r, c.g, c.b); }
        if (blur > 4 && spread >= 30) glows.push(r.sel);
      }
    }
  }
  eq('EXACTLY ONE chromatic glow exists in Editorial, and it is the status LED — kept '
     + 'with its argument in the sheet (hue is the only carrier of running/degraded/down '
     + 'on an 8px dot, and the halo triples the lit area in the 56px rail where the dot '
     + 'is the whole row). A SECOND glow is the actual risk and fails here.',
     [...new Set(glows)], ['.dot.ok']);
  // studio's answer to the same dot is the opposite one, on purpose
  ok(/\.dot\b[^{]*\{[^}]*box-shadow:none/.test(sdNoC.replace(/\n/g, ' ')),
     '…and the studio design still removes it, which is the right answer for THAT design '
     + 'and is why the exception is per-design rather than global');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. THE HARDCODED-LITERAL DEFECT CLASS (--on-wash's lesson, fourth sighting)
// ═══════════════════════════════════════════════════════════════════════════════
console.log('5. no colour a palette swap cannot reach');
{
  ok(!/#171420/.test(noC.replace(/--on-accent:\s*#171420/g, '')),
     'the near-black that sat on the accent fill appears nowhere as a literal outside the '
     + 'token blocks — six sites, and Warm Paper measured 4.23 and 1.08 on two of them');
  // a general sweep: any colour literal in a PAINTED declaration outside a token block
  const tokenSels = [':root', 'html[data-theme="light"]', 'html[data-theme="gold"]',
                     'html[data-theme="cyber"]'];
  const strays = [];
  for (const r of ALL) {
    if (tokenSels.includes(r.sel)) continue;
    for (const m of r.body.matchAll(/(^|;)\s*(color|background|background-color|border-color)\s*:\s*([^;}]+)/g)) {
      if (/#[0-9a-fA-F]{3,8}\b/.test(m[3])) strays.push(r.sel.slice(0, 46) + ' → ' + m[2] + ':' + m[3].trim());
    }
  }
  // The two remaining literals are ALLOWLISTED WITH THEIR REASONS, so the list is a
  // ledger rather than a blanket. A NEW literal fails this check, which is the point.
  //   .art-frame #fff       — the sandboxed artifact iframe renders third-party HTML that
  //                           assumes a white page; theming the frame would repaint
  //                           content we do not own. Deliberately not a token.
  //   button.primary:hover  — the hover fill for the cream-filled primary. Reachable:
  //     #fff                  the light pack forks it (that fork is pinned in
  //                           test_theme_packs.js) and both dark packs put near-black ink
  //                           on it, measured ≥16:1. Left as-is rather than tokenised for
  //                           one hover state, and recorded here so it is a choice.
  const ALLOWED = [
    '.art-frame → background:#fff',
    'button.primary:hover → background:#fff',
  ];
  eq('…and the only remaining hex literals are the two allowlisted ones, with reasons',
     strays.filter(s => !ALLOWED.includes(s)), []);
  eq('…and both allowlisted literals are still actually present (an allowlist that has '
     + 'rotted into a fiction is worse than no allowlist)',
     ALLOWED.filter(a => !strays.includes(a)), []);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. THE COLLAPSED SESSIONS RAIL — geometry, per design
// ═══════════════════════════════════════════════════════════════════════════════
console.log('6. the collapsed sessions rail (Debi\'s ratified slim reopen strip)');
const HIT = 44;
{
  // the strip
  const strip = ALL.find(r => r.sel === 'body.sessions-collapsed #chat-sessions');
  ok(!!strip, 'the collapsed state has its own width rule');
  const w = parseInt((strip.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  ok(w >= 34 && w <= 48, 'the strip is ' + w + 'px — inside Debi\'s ratified 34–48px band');
  ok(w >= HIT, '…and ≥ ' + HIT + 'px, so the reopener clears the hit floor on the NARROW '
     + 'axis too (office.html\'s house strip is 34px; this is the house look at the '
     + 'accessibility floor). Before this slice the target was 22×22px in Editorial and '
     + '22×14px in studio.');
  ok(/padding-right:0/.test(strip.body) && /border-right:0/.test(strip.body),
     '…with no padding and no border of its own, so the reclaimed width goes to the '
     + 'transcript rather than to a second rule of dead space');

  // the reopener is REAL MARKUP hidden by a class (office.html's pattern), not injected
  ok(/<button id="cs-reopen"[^>]*onclick="toggleSessionsRail\(\)"/.test(html),
     'the reopener is real markup in the page and calls toggleSessionsRail()');
  ok(/id="cs-reopen"[\s\S]{0,200}aria-label="Show sessions"/.test(html),
     '…and it is LABELLED for assistive tech, not a bare glyph');
  ok(/id="cs-reopen"[\s\S]{0,240}<span>Sessions/.test(html),
     '…and it carries a VISIBLE label: the chevron alone never said what came back, '
     + 'which is office.html\'s own finding about its file rail');
  const hidden = ALL.find(r => r.sel === '#cs-reopen');
  ok(hidden && /display:none/.test(hidden.body),
     '…and it is hidden by a class while the rail is open (one collapse grammar, the '
     + 'shape office.html\'s #rail-tab established)');

  const ro = ALL.find(r => r.sel === 'body.sessions-collapsed #cs-reopen');
  ok(!!ro, 'the collapsed reopener has its own rule');
  ok(/flex:1 1 auto/.test(ro.body),
     '…and it FILLS the strip, so the click axis is the whole rail height (live: '
     + '44 × 718.5px) — there is no lone button floating in an empty column any more');
  const mh = parseInt((ro.body.match(/min-height:\s*(\d+)px/) || [])[1], 10);
  ok(mh >= HIT, '…with a ' + mh + 'px floor for the degenerate case where the rail is '
     + 'shorter than the target');
  ok(/writing-mode:vertical-rl/.test(ALL.find(r => r.sel === 'body.sessions-collapsed #cs-reopen span').body),
     '…and the label runs vertically, which is what makes a 44px strip readable');

  // the chevron and the list are the things that go away
  const gone = ALL.find(r => r.sel.startsWith('body.sessions-collapsed #chat-sessions .cs-head'));
  ok(!!gone && /display:none/.test(gone.body),
     'the .cs-head row (which held the 22px « chevron, the title and ＋ New) is hidden '
     + 'while collapsed — the strip is the ONLY thing in the strip');
  ok(/t\.textContent = '«'/.test(html),
     '…so the chevron has exactly ONE meaning again in applySessionsRail (it used to flip '
     + 'to » for a state it is no longer visible in)');

  // EXPAND RESTORES EXACTLY: the collapse rule must not touch the persisted width
  ok(!/--sessions-width/.test(strip.body),
     'the collapse rule never writes --sessions-width, so a rail dragged to 500px '
     + 'collapses to the strip and reopens at 500px (driven live: 500 → 44 → 500)');
  ok(/function clampSessionsWidth\(w\)/.test(html) && /Math\.max\(120, Math\.min\(560/.test(html),
     '…and the 120–560px clamp is untouched');
  const rz = ALL.find(r => r.sel === 'body.sessions-collapsed #cs-resize');
  ok(!!rz && /display:none/.test(rz.body),
     '…and the drag handle is still hidden while collapsed (there is nothing to resize)');
}
// studio has to RESTATE all of it — the collision trap, third instance
{
  const SC = 'html[data-design="studio"]';
  const col = SDALL.find(r => r.sel === SC + ' body.sessions-collapsed #chat-sessions');
  ok(!!col, 'studio restates the collapsed strip (its own ' + SC + ' #chat-sessions rule '
     + 'would otherwise put 12px of padding back on a 44px strip)');
  const sw = parseInt((col.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  const ew = parseInt((ALL.find(r => r.sel === 'body.sessions-collapsed #chat-sessions')
    .body.match(/width:\s*(\d+)px/) || [])[1], 10);
  ok(sw === ew, 'the two designs agree on the strip width (' + sw + 'px) — a collapse '
     + 'geometry that differs per design is how the studio slice\'s 22×14px target happened');
  const sro = SDALL.find(r => r.sel === SC + ' body.sessions-collapsed #cs-reopen');
  ok(!!sro, 'studio restates the REOPENER too — and this is the sharper half of the trap: '
     + SC + ' button is (0,1,1) and LOSES to Editorial\'s (1,1,1) '
     + 'body.sessions-collapsed #cs-reopen, so without this the one control would have '
     + 'kept Editorial\'s tracked mono caps while every other studio control changed');
  ok(/letter-spacing:normal/.test(sro.body) && /text-transform:none/.test(sro.body),
     '…in studio\'s voice: sentence case at normal tracking (the tracked mono caps are '
     + 'Editorial\'s signature and are also what impeccable\'s wide-tracking and '
     + 'all-caps-body rules are about)');
  const fs2 = parseFloat((sro.body.match(/font-size:\s*([\d.]+)px/) || [])[1]);
  ok(fs2 >= 11, '…and at ' + fs2 + 'px, studio\'s own 11px floor');
}
// THE OTHER COLLAPSIBLE — checked for the same shape, and it does not have it
{
  const aside = ALL.find(r => r.sel === 'body.rail-slim aside');
  const w = parseInt((aside.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  const pad = parseInt((aside.body.match(/padding:\s*\d+px\s+(\d+)px/) || [])[1], 10);
  ok(w - 2 * pad >= HIT, 'the sidebar icon rail was checked for the same dead-space shape: '
     + w + 'px − 2×' + pad + 'px = ' + (w - 2 * pad) + 'px wide rows, ≥ ' + HIT
     + ' (live: 18 rows at 47 × 46.8px, content 870px in an 800px rail — it is FULL, so '
     + 'there is no empty column and no fix was needed)');
  ok(/body\.rail-slim aside nav a/.test(noC),
     '…and every row is still a real target rather than a glyph in a gutter');
}

console.log('');
console.log(fails ? (fails + ' failure(s) of ' + checks)
                  : ('editorial debt: ' + checks + ' checks passed'));
process.exit(fails ? 1 : 0);
