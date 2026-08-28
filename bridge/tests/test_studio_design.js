/* THE STUDIO DESIGN — the design fence (FABLE-STUDIO-DESIGN-SPEC §4, 2026-08-28).
 *
 * A second COMPLETE DESIGN is a different risk shape from a theme pack, so this file
 * is a different fence from test_theme_packs.js. A pack could only ever get colour
 * wrong, and the answer was "token swaps only". A design owns layout, type, spacing
 * and component shape — it can get anything wrong — so what is fenced here is not the
 * design's taste but the four properties that make it SAFE to have two designs at all:
 *
 *   1. EDITORIAL CANNOT BE REACHED. Every selector in studio-design.css carries
 *      html[data-design="studio"]. Not "most" — the file is parsed and every rule is
 *      checked, so a future edit cannot add an unscoped rule and repaint the default.
 *      Editorial's own stylesheet grows by exactly TWO rules (the ✦ chip's loading
 *      state, and one inline-style literal LIFTED into the sheet unchanged so that any
 *      axis can reach it at all) — both pinned by name below.
 *
 *   2. EDITORIAL DOES NOT PAY FOR IT. The studio CSS is a separate asset. With the
 *      key absent the boot path is one localStorage read and zero requests. index.html
 *      is held to a byte budget, because "Editorial is untouched" has to include its
 *      weight or the sentence is decoration.
 *
 *   3. NOTHING IS HALF-PAINTED, AND NOTHING OF THE USER'S IS LOST. The attribute is
 *      stamped only after the sheet loads; the axis never writes harness-theme or
 *      harness-chrome; ◐ maps to studio's variants instead of going dead; the packs
 *      are greyed rather than silently ignored; the one seam is total and idempotent.
 *
 *   4. THE DESIGN IS MEASURED, NOT ASSERTED. Contrast is computed from the hex for
 *      every ink on every ground in BOTH variants (the arithmetic pattern
 *      test_theme_packs.js established), and the deterministic subset of
 *      pbakaus/impeccable's 59 detector rules is executed against the stylesheet.
 *
 * ── WHY THE IMPECCABLE SECTION IS HERE AND NOT IN A REPORT ────────────────────────
 * The spec made impeccable's anti-pattern set BINDING on this design. A rule that was
 * checked once by hand at build time is a claim; a rule that runs in the gate is a
 * constraint. The 24 rules below are the ones decidable from a static stylesheet.
 * Their thresholds are quoted from the project's own source
 * (cli/engine/registry/antipatterns.mjs + cli/engine/rules/checks.mjs), not from its
 * prose, because the prose and the code disagree in two places that matter:
 * nested-cards fires at depth TWO (not three), and there is NO touch-target rule in
 * the set at all. Rules needing a rendered DOM or a screenshot (line-length,
 * text-occlusion, heading-rhythm, nested-cards' DOM half, …) are named in the report
 * as walked-live-not-fenced, which is the honest split.
 *
 * Run: node bridge/tests/test_studio_design.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const CSSPATH = path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css');
const sd = fs.readFileSync(CSSPATH, 'utf8');
const inlineCss = html.split('<style>')[1].split('</style>')[0];

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}
function eq(msg, got, want) {
  const same = JSON.stringify(got) === JSON.stringify(want);
  ok(same, msg + (same ? '' : ' — got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)));
}

// ── a brace-matching rule walker (the shape test_theme_packs / test_studio_chrome
// use). Comments carry braces and prose, so they go first. @-blocks are recorded
// rather than skipped: an @media that escapes the scope is exactly the leak this
// fence exists to catch.
function rules(src) {
  const out = [];
  let i = 0;
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
const noC = sd.replace(/\/\*[\s\S]*?\*\//g, '');
const ALL = rules(noC);
const RULES = ALL.filter(r => !r.at);

// ═══════════════════════════════════════════════════════════════════════════════
// 1. THE SCOPE FENCE — the whole file, every rule
// ═══════════════════════════════════════════════════════════════════════════════
console.log('1. the scope fence (studio cannot reach Editorial)');
const SCOPE = 'html[data-design="studio"]';
ok(RULES.length > 180, 'the walker parsed the whole stylesheet (' + RULES.length + ' rules)');
{
  // EVERY comma-separated selector in EVERY rule must carry the scope. A rule with
  // five scoped selectors and one bare one is the exact accident this catches.
  const bad = [];
  for (const r of RULES) {
    for (const one of r.sel.split(',')) {
      const s = one.trim();
      if (!s) continue;
      if (!s.includes(SCOPE)) bad.push(s.slice(0, 90));
    }
  }
  eq('every selector carries html[data-design="studio"]', bad, []);
  eq('…and there is no bare :root / html / * rule', RULES.filter(r =>
     /^(:root|html|\*)\s*$/.test(r.sel)).map(r => r.sel), []);
  eq('…and no @-block at all (an @media/@supports wrapper is how a scope leaks)',
     ALL.filter(r => r.at).map(r => r.sel.slice(0, 60)), []);
  ok(!/@import/.test(noC), '…and no @import (one asset, one request)');
  ok(!/!important/.test(noC), '…and not one !important — the axis wins on source order alone');
  ok(!/url\(/.test(noC), '…and no url() — nothing in this file can reach the network');
}
// the mirror image: Editorial's own sheet gained exactly two rules, both pinned.
{
  const inlineRules = rules(inlineCss.replace(/\/\*[\s\S]*?\*\//g, '')).filter(r => !r.at);
  const mine = inlineRules.filter(r => /design-chip|data-design|#models-aux/.test(r.sel));
  // EXACTLY TWO, and they are these two. The first is the ✦ chip's loading state. The
  // second is the --on-wash pattern applied again: the AUX RUNNER label carried
  // `style="letter-spacing:.16em"` INLINE from its renderer, and an inline style beats
  // every stylesheet, so it was the one piece of typography a second design could not
  // reach without !important. The literal moved into the sheet UNCHANGED — .16em at the
  // same font-size is the same used value — which is why the before/after computed-style
  // comparison over 61 elements shows zero diffs.
  eq('Editorial\'s inline sheet gained exactly TWO rules, and these are they',
     mine.map(r => r.sel).sort(), ['#design-chip.loading', '#models-aux .name']);
  ok(!/letter-spacing/.test(html.slice(html.indexOf('AUX RUNNER') - 200,
                                       html.indexOf('AUX RUNNER') + 40)),
     '…and the renderer no longer carries that inline style (a presentational inline '
     + 'style is unreachable by ANY axis, which is the defect class, not the instance)');
  ok(/#models-aux \.name \{ letter-spacing:\.16em; \}/.test(inlineCss),
     '…and the value it replaced is byte-identical, so Editorial did not move');
  ok(/html\[data-design="studio"\] #models-aux \.name[\s\S]{0,60}letter-spacing:normal/.test(noC),
     '…and studio can now actually reach it');
  ok(/opacity:\.55;\s*pointer-events:none/.test(mine[0].body.replace(/\s+/g, ' ').trim()
     .replace(/ ;/g, ';')) || /opacity/.test(mine[0].body),
     '…and it does nothing but dim the chip while the asset is in flight');
  ok(!/data-design/.test(inlineCss.replace(/#design-chip\.loading[^}]*}/, '')),
     '…and no inline rule mentions the design ATTRIBUTE at all — Editorial\'s sheet '
     + 'has no knowledge of the second design');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. EDITORIAL DOES NOT PAY — the boot path and the byte budget
// ═══════════════════════════════════════════════════════════════════════════════
console.log('2. Editorial does not pay for the second design');
{
  const pre = html.split('</style>')[1].split('</head>')[0];
  ok(pre.includes("localStorage.getItem('harness-design')"),
     'the pre-paint pass reads the new key');
  // the ORDER matters: theme, chrome, then design — design is last because it is the
  // only one that can be async.
  ok(pre.indexOf('harness-theme') < pre.indexOf('harness-chrome')
     && pre.indexOf('harness-chrome') < pre.indexOf('harness-design'),
     '…after theme and chrome, in the same single pass');
  // THE PROPERTY THAT MATTERS: the link is created INSIDE the key test, so an
  // Editorial boot issues no request at all.
  const blk = pre.slice(pre.indexOf("localStorage.getItem('harness-design')"));
  const guard = blk.slice(0, blk.indexOf('createElement'));
  ok(/_dg === 'studio'/.test(guard) && /_dg === 'studio-light'/.test(guard),
     '…and the <link> is created ONLY inside the key test (Editorial issues 0 requests)');
  ok(blk.indexOf('_dl.onload') < blk.indexOf("dataset.design = 'studio'"),
     '…and the attribute is stamped INSIDE onload — never before the sheet exists');
  ok(!/document\.documentElement\.dataset\.design/.test(guard),
     '…so no code path can stamp the attribute ahead of the stylesheet');
  // an unknown / corrupt stored value must fall through to Editorial pre-paint, the
  // same rule the theme axis learned.
  ok(!/_dg\s*\)/.test(guard.replace(/_dg === '[a-z-]+'/g, '')),
     '…and an unknown stored value stamps nothing (no attribute without a stylesheet)');
}
{
  /* THE BYTE BUDGET. Editorial's page weight is the thing "untouched" has to include,
     and the point that has always mattered is that the 59KB design is NOT inlined.

     ⚠️ RE-EXPRESSED 2026-08-28 (SSE-hybrid slice) — and this is a fence being MOVED,
     so it is spelled out for review rather than quietly adjusted. The check was
     `size - 675454 <= 12000`, where 675454 is index.html at c0eaf03, the commit BEFORE
     the studio slice. That measured "all growth of index.html since that commit" while
     claiming to measure studio's footprint, so it charged every LATER, unrelated slice
     against studio's budget — the first one to touch the page (BE-01's ✗ chip + the SSE
     hybrid, +13.7KB of new behaviour) failed a studio fence it has nothing to do with.
     A fence that fails for reasons outside its own subject teaches people to raise the
     number, which is how a fence dies.

     So it is now two separate facts, each checkable on its own terms:
       (a) STRUCTURAL — the design asset is not inlined. That is the real invariant and
           it cannot rot: it is asserted against the sheet's own content, not a number.
       (b) A CEILING on the page, deliberately tight enough that moving prose into a
           test file (never served) stays the cheaper option — which is exactly what
           the SSE slice did before raising it. A slice that needs more must say what
           it bought, here, in this comment.

     Ceiling history (each line = a slice that consciously raised it):
       690000  studio design slice (2026-08-28) — the chip, the axis, designBoot
       706000  BE-01 ✗ chip + the SSE hybrid (2026-08-28) — +13.7KB: the events
               subscription, the cadence state machine, the chip renderer and its CSS
       720000  the impeccable-debt slice (v1.5.24, 2026-08-28) — +14KB, and it is almost
               entirely PROSE, which the ceiling's own note says should have gone to a
               test file instead. It did not, deliberately, and here is the trade: what
               this slice bought is a set of ARGUED EXCEPTIONS living at the rules they
               excuse — the one kept glow, the kept 10/10.5px micro-caps voice, the 9.5px
               chip size that overrode a standing Debi ruling, the full-width transcript,
               the measure caps and the four re-measured palettes. An exception whose
               argument is in a test file is an exception the next person editing the rule
               will not read. The MEASURED numbers are in the fence
               (bridge/tests/test_editorial_debt.js, 96 checks) so nothing here is load-
               bearing for correctness; only the reasoning is in the page. The structural
               half of this budget — the design asset is not inlined — is unaffected and
               is asserted below on its own terms.
       745000  v1.5.26, Debi's composer + navigation wave — +23.7KB, and here is what it
               bought, per the ceiling's own protocol. NEW BEHAVIOUR (not prose): the
               audio-mode switch's markup, its state-derivation renderer, its keyboard
               radio-group handler and its CSS in three looks; the composer's rewrite
               into one bounded field; the sidebar's third (fully hidden) state with its
               pure decision + cycle functions and its edge reopener; and the nav
               reorder's one-time localStorage migration, which has to live in the page
               because the page paints the sidebar before /api/nav answers. Measured:
               ~14KB of that is code and markup, ~10KB is the argued exceptions the
               v1.5.24 line already justifies keeping AT the rule (the 34px strip's
               hit-floor argument, the switch's 60px width and why it is 60 and not 34,
               the four specificity restatements, and the two moved Debi rulings — talk
               before Send, and auto/conv becoming one control). The MEASURED numbers all
               live in fences (test_editorial_debt.js, test_theme_packs.js,
               test_audio_switch.js, test_audio_drop.js); only the reasoning is here.
       775000  the HELP surface (roadmap §2.4, v1.5.27) — +21KB, and per the protocol,
               what it bought. NEW BEHAVIOUR, essentially all of it: the markdown
               renderer for the subset docs/USER-EXPLAINERS.md uses (inline, blocks,
               GFM tables, lists with continuation lines, the section splitter), the
               view's fetch → parse → render → filter path, the contents-rail jump, the
               empty and error states, the view's markup, and ~40 lines of layout CSS.
               The PROSE half is small and is where this ceiling's own note wants it:
               the handled subset is enumerated AT the renderer (a renderer that
               silently drops syntax is the whole defect class, so what it handles has
               to be readable by whoever edits it), and the one adversarial finding — a
               scan-forward that discarded the document's lead-in — is recorded at the
               loop it fixed rather than in a report nobody will open again.
               ⚠️ AND THE PAGE DID NOT GROW BY THE SIZE OF THE HELP TEXT. The content
               is served from docs/USER-EXPLAINERS.md by /api/help/explainers and is
               never inlined — structurally the same argument as the design asset
               asserted below. Editing the help costs zero page bytes, for ever. */
  const CEILING = 775000;
  const size = Buffer.byteLength(html, 'utf8');
  ok(size <= CEILING, 'index.html is ' + size + ' bytes (ceiling ' + CEILING + ')');
  // (a) the structural half: the design's own rules are NOT in the page.
  const inline = html.split('<style>')[1].split('</style>')[0];
  const sdRules = (sd.match(/html\[data-design="studio"\][^{]*\{/g) || [])
    .map(s => s.trim()).slice(0, 40);
  ok(sdRules.length >= 20, 'the design sheet has rules to check against ('
     + sdRules.length + ' sampled)');
  ok(!sdRules.some(r => inline.includes(r)),
     'NOT ONE of the design\'s own rules appears in index.html\'s inline sheet — the '
     + Buffer.byteLength(sd, 'utf8') + '-byte design is still a lazy-loaded asset');
  // and the growth is confined to the named seams
  for (const seam of ['harness-design', 'id="design-chip"', 'function designApply(',
                      'function setDesign(', 'function designSelect(',
                      'function designBoot(', 'toggleDesign']) {
    ok(html.includes(seam), 'seam present: ' + seam);
  }
  ok(!fs.existsSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.js'))
     && !/<script[^>]*studio-design/.test(html) && !/studio-design\.js'/.test(html),
     'no studio-design.js exists and nothing loads one — the design needed no additive '
     + 'classes, so none were invented (the amendment allowed one ONLY if genuinely '
     + 'needed, and designApply() applies no classes at all)');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. THE AXIS — keys, wiring, and the pure resolvers, EXECUTED
// ═══════════════════════════════════════════════════════════════════════════════
console.log('3. the axis (executed)');
const grab = name => {
  const i = html.indexOf('function ' + name + '(');
  if (i < 0) return '';
  const s = html.slice(i);
  return s.slice(0, s.indexOf('\n}') + 2);
};
{
  const listSrc = html.slice(html.indexOf('const DESIGNS = ['));
  const DESIGNS = eval('(' + listSrc.slice(listSrc.indexOf('['), listSrc.indexOf('];') + 1) + ')');
  eq('three stops: Editorial (the identity) and studio\'s two variants',
     DESIGNS.map(d => d.id), ['editorial', 'studio', 'studio-light']);
  eq('…and Editorial is first', DESIGNS[0].id, 'editorial');
  ok(DESIGNS.every(d => d.label && d.note), '…and every stop is NAMED and described');

  eval(grab('designId')); eval(grab('nextDesignId')); eval(grab('flipDesignVariant'));
  for (const id of ['editorial', 'studio', 'studio-light'])
    eq('designId keeps the known id ' + id, designId(id), id);
  for (const junk of [null, undefined, '', 'STUDIO', 'studio ', 'dark', '{}', 0, [], {}])
    eq('designId(' + JSON.stringify(junk) + ') → editorial (a design axis never leaves '
       + 'the panel unpainted)', designId(junk), 'editorial');

  // ✦ is a TWO-state toggle on the axis, and it remembers which variant you left.
  eq('✦ from Editorial with no memory → studio dark', nextDesignId('editorial', undefined), 'studio');
  eq('✦ from Editorial remembering light → studio light',
     nextDesignId('editorial', 'studio-light'), 'studio-light');
  eq('✦ from studio dark → Editorial', nextDesignId('studio', 'studio'), 'editorial');
  eq('✦ from studio light → Editorial', nextDesignId('studio-light', 'studio-light'), 'editorial');
  eq('✦ from a corrupt value behaves as Editorial did', nextDesignId('junk', 'studio'), 'studio');
  // …and it is an INVOLUTION on the axis: two clicks are always where you started.
  for (const start of ['editorial', 'studio', 'studio-light']) {
    const once = nextDesignId(start, start === 'editorial' ? 'studio' : start);
    const twice = nextDesignId(once, start === 'editorial' ? 'studio' : start);
    eq('two ✦ clicks return to ' + start + ' exactly', twice, designId(start));
  }

  // ◐ under studio: total, and the identity on Editorial (where ◐ keeps its packs).
  eq('◐ under studio dark → studio light', flipDesignVariant('studio'), 'studio-light');
  eq('◐ under studio light → studio dark', flipDesignVariant('studio-light'), 'studio');
  eq('◐ on Editorial is the identity (the four-pack cycle still owns it)',
     flipDesignVariant('editorial'), 'editorial');
  for (const junk of [null, 'junk', ''])
    eq('◐ on a corrupt value → editorial, never a stamp', flipDesignVariant(junk), 'editorial');
}
{
  // ONE new key, and the two existing keys are never written by this axis.
  const keys = new Set((html.match(/localStorage\.setItem\('([^']+)'/g) || [])
    .map(s => s.replace(/.*\('/, '').replace(/'$/, '')));
  ok(keys.has('harness-design'), 'the design is persisted in harness-design');
  ok(!/harness-design-variant|harness-dvariant|harness-studio/.test(html),
     '…and no SECOND key was invented for the variant (it rides the same value)');
  // the crucial one: setDesign / toggleTheme-under-studio must not write the theme key
  const sdSrc = html.slice(html.indexOf('async function setDesign('));
  const setDesignBody = sdSrc.slice(0, sdSrc.indexOf('\nfunction toggleDesign'));
  ok(!/harness-theme|harness-chrome/.test(setDesignBody),
     'setDesign() never writes harness-theme or harness-chrome — leaving studio '
     + 'restores the user\'s theme and chrome because they were never touched');
  const tt = grab('toggleTheme');
  ok(/storedDesign\(\)/.test(tt) && /flipDesignVariant/.test(tt),
     '◐ maps to studio\'s variants while studio is active (it is never dead)');
  ok(tt.indexOf('flipDesignVariant') < tt.indexOf('nextThemeId'),
     '…and it does so BEFORE reaching the pack cycle, so ◐ cannot write harness-theme '
     + 'from inside studio');
}
{
  // designApply: the one seam. Total, idempotent, and the only writer.
  const da = grab('designApply');
  ok(/const id = designId\(/.test(da),
     'designApply() runs its argument through designId — the seam is total on its own '
     + '(the adversarial pass reached it directly with junk and got a studio paint)');
  ok(/removeAttribute\('data-design'\)/.test(da) && /removeAttribute\('data-dvariant'\)/.test(da),
     '…Editorial REMOVES both attributes (Editorial is the stylesheet itself, not a value)');
  ok(!/toggle|!\s*d\.dataset/.test(da),
     '…and it sets absolute state rather than toggling, which is what makes it idempotent');
  const writers = (html.match(/dataset\.design\s*=[^=]|removeAttribute\('data-design'\)/g) || []).length;
  const preWriters = (html.split('</head>')[0].match(/dataset\.design\s*=[^=]/g) || []).length;
  ok(writers - preWriters <= 2,
     'only designApply() writes data-design in page script (' + (writers - preWriters)
     + ' writes: the stamp and the removal)');
  // grey-not-hide
  ok(/o\.disabled = \(id !== 'editorial'\) && PACK_GATED/.test(da),
     'the two dark packs are GREYED (not hidden, not silently ignored) while studio owns '
     + 'the palette');
  ok(/ts\.title = \(id === 'editorial'\) \? 'Theme pack' : PACKS_GATED_NOTE/.test(da),
     '…and the select\'s own title says why');
  ok(/Studio provides its own light and dark/.test(html)
     && /returns when/.test(html),
     '…and the note promises the theme comes back, which the round-trip journey proves');
  // BOTH render paths gate: designApply (live flip) and themePackSelect (fresh render)
  const tps = grab('themePackSelect');
  ok(/storedDesign\(\) !== 'editorial'/.test(tps) && /PACK_GATED\.includes/.test(tps),
     'themePackSelect() gates on FIRST render too, so the two paths cannot disagree');
}
{
  // the button, the Appearance row, the ⌘K entry
  const topbar = html.slice(html.indexOf('<div class="topbar">'), html.indexOf('<div id="view-mc">'));
  eq('the top bar now carries FIVE icon chips — the design axis added exactly one',
     (topbar.match(/class="chip chip-icon"/g) || []).length, 5);
  ok(/id="design-chip" onclick="toggleDesign\(\)" title="Studio design"/.test(topbar),
     '…the ✦ chip, wired to toggleDesign, tooltip "Studio design"');
  ok(/>✦<\/span>/.test(topbar), '…with its own glyph, distinct from ◐ and ▣');
  ok(/onclick="toggleTheme\(\)"/.test(topbar) && /onclick="toggleChrome\(\)"/.test(topbar),
     '…and ◐ and ▣ are still there, still wired to their own functions (untouched)');
  ok(/\{t:'Studio design[^}]*f:toggleDesign\}/.test(html), '⌘K reaches the design axis');
  ok(/<div class="cap-name">Design<\/div>/.test(html), 'Appearance gained a named Design row');
  ok(/id="design-pick" onchange="setDesign\(this\.value\)"/.test(html),
     '…with a <select> of the three, applying on change');
  ok(html.indexOf('<div class="cap-name">Design</div>')
     < html.indexOf('<div class="cap-name">Theme</div>'),
     '…placed ABOVE Theme, because the design is the outer axis');
  // the loading state, and that it is honest
  const sdb = html.slice(html.indexOf('async function setDesign('));
  ok(/classList\.add\('loading'\)/.test(sdb) && /textContent = '◌'/.test(sdb),
     'the first click SHOWS the load (dim + a distinct glyph) rather than swallowing it');
  ok((sdb.match(/classList\.remove\('loading'\)/g) || []).length >= 2,
     '…and the loading state is cleared on BOTH the success and the failure path');
  ok(/feed\('design', 'studio design stylesheet failed to load/.test(sdb)
     && /return 'editorial'/.test(sdb),
     '…and a failed asset TELLS the user and stays on Editorial (no attribute without '
     + 'a stylesheet)');
  ok(/function designBoot\(\)/.test(html) && /designBoot\(\);/.test(html),
     'the recovery path runs at boot (a key that says Studio over an Editorial page is '
     + 'reconciled, not left lying)');
  // one promise, so a double click cannot double-fetch
  const da2 = grab('designAsset');
  ok(/if \(_designAsset\) return _designAsset;/.test(da2),
     'designAsset() memoises ONE promise — a double click cannot start two fetches');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. THE PALETTE — token completeness, then contrast MEASURED
// ═══════════════════════════════════════════════════════════════════════════════
console.log('4. the palette (measured, not eyeballed)');
const DARKSEL = 'html[data-design="studio"]';
const LIGHTSEL = 'html[data-design="studio"][data-dvariant="light"]';
function tokensOf(sel) {
  const r = RULES.find(x => x.sel === sel);
  const t = {};
  if (!r) return t;
  for (const m of r.body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+)/g)) t[m[1]] = m[2].trim();
  return t;
}
const DK = tokensOf(DARKSEL), LT = tokensOf(LIGHTSEL);
ok(Object.keys(DK).length > 20, 'the studio-dark token block parsed (' + Object.keys(DK).length + ' tokens)');
ok(Object.keys(LT).length > 10, 'the studio-light token block parsed (' + Object.keys(LT).length + ' tokens)');
{
  // COMPLETENESS is what makes the packs inert: studio must redefine every token
  // :root declares, or a pack's leftover value bleeds through.
  const inl = rules(inlineCss.replace(/\/\*[\s\S]*?\*\//g, '')).filter(r => !r.at);
  const root = inl.find(r => r.sel === ':root');
  const baseNames = (root.body.match(/--[a-z0-9-]+(?=\s*:)/g) || [])
    .filter(n => n !== '--mono' && n !== '--serif');
  eq('studio-dark redefines EVERY base palette token — this is why the theme packs '
     + 'cannot bleed through', baseNames.filter(n => !(n in DK)), []);
  ok(!('--serif' in DK) && !('--mono' in DK),
     '…and it never redefines --serif or --mono: the serif is killed per-SITE, so the '
     + 'token keeps its meaning for Editorial');
  // the serif genuinely appears nowhere
  ok(!/var\(--serif\)/.test(noC), 'var(--serif) appears nowhere in the studio design');
  const serifKill = RULES.find(r => r.sel.includes('.brand') && r.body.includes('--sd-sans'));
  ok(!!serifKill, '…and every serif-bearing site is re-set to the studio sans');
  for (const site of ['h1', '.brand', '.card .state', '.metric .v', 'dialog h3',
                      '.md-title', '.mrow .mname', '.glog-base', '#thinking', '.msg-edit']) {
    ok(serifKill.sel.includes(site), '…including ' + site);
  }
  ok(/font-style:normal/.test(serifKill.body),
     '…and the italic goes with it (the italic serif wordmark is Editorial\'s signature)');
}
// ── the arithmetic (WCAG relative luminance, the theme-pack fence's pattern) ──
function lum(h) {
  h = h.replace('#', '').trim();
  if (h.length === 3) h = h.split('').map(c => c + c).join('');
  const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(x => x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
const ratio = (a, b) => {
  const x = lum(a), y = lum(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};
// an opacity:.4 disabled control over a ground — the composite, not the raw ink
function over(fg, bg, a) {
  const p = h => { h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
                   return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); };
  const f = p(fg), b = p(bg);
  return '#' + f.map((v, i) => Math.round(v * a + b[i] * (1 - a))
    .toString(16).padStart(2, '0')).join('');
}
const spread = h => { h = h.replace('#', ''); if (h.length === 3) h = h.split('').map(c => c + c).join('');
  const c = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
  return Math.max(...c) - Math.min(...c); };

for (const [name, T] of [['studio-dark', DK], ['studio-light', { ...DK, ...LT }]]) {
  console.log('  — ' + name + ' —');
  const GROUNDS = ['--bg', '--bg2', '--card', '--card2', '--st-btn', '--st-hi', '--st-inp'];
  // (a) REAL TEXT clears AA on every ground it can land on.
  for (const ink of ['--cream', '--fg', '--dim']) {
    for (const g of GROUNDS) {
      const r = ratio(T[ink], T[g]);
      ok(r >= 4.5, name + ': ' + ink + ' on ' + g + ' = ' + r.toFixed(2) + ' (AA 4.5)');
    }
  }
  // (b) --faint IS HELD TO THE FULL 4.5, AND THAT IS A CORRECTION MADE BY DRIVING.
  // This fence originally tiered --faint at 3.0 on the theory that it is smallprint
  // and disabled ink, which WCAG 1.4.3 would exempt. A live getComputedStyle sweep of
  // all eight surfaces said otherwise: --faint is what actually paints
  //   .card .meta      "pin local · port 8700"   4.32
  //   .cs-item .meta   "23 Aug · 2 msg"          4.01 dark / 3.52 light
  //   .mpill / .msize  "gguf" / "15.9 GB"        4.01
  //   .navlbl / .cs-title / .build / .kicker .lbl  3.41–3.60 light
  // Every one of those is information a user reads, at 11px, on an enabled surface.
  // The tier was wrong, not the measurement — so the tier moved. Studio's four ink
  // levels ALL clear AA at 11px, which is the actual reason the ramp below is
  // compressed relative to Editorial's.
  for (const g of GROUNDS) {
    const r = ratio(T['--faint'], T[g]);
    ok(r >= 4.5, name + ': --faint on ' + g + ' = ' + r.toFixed(2) + ' — it carries real '
       + '11px metadata, so it gets the full AA 4.5 (Editorial\'s own --faint is 2.17)');
  }
  // …and the four tiers must stay PERCEPTIBLY apart, or "all of them clear AA" would
  // have been bought by collapsing the hierarchy into one grey.
  {
    const ramp = ['--cream', '--fg', '--dim', '--faint'];
    for (let i = 0; i < ramp.length - 1; i++) {
      const r = ratio(T[ramp[i]], T[ramp[i + 1]]);
      ok(r >= 1.2, name + ': the ink ramp step ' + ramp[i] + ' → ' + ramp[i + 1] + ' = '
         + r.toFixed(2) + ' — four distinguishable levels, not one grey');
    }
    // and monotonic: each tier is quieter than the one above it, on both grounds
    const dir = lum(T['--bg']) < 0.5 ? -1 : 1;   // dark ground → ink descends
    for (let i = 0; i < ramp.length - 1; i++) {
      ok(Math.sign(lum(T[ramp[i + 1]]) - lum(T[ramp[i]])) === dir,
         name + ': ' + ramp[i + 1] + ' is quieter than ' + ramp[i] + ' (ramp is monotonic)');
    }
  }
  // (c) the accent carries 11px labels (.who, .activity .tag, .cap-exp, #cs-new), which
  // is SMALL text, so it needs the full 4.5 — not the 3.0 a large accent would get.
  for (const g of ['--bg', '--bg2', '--card', '--card2', '--st-btn']) {
    const r = ratio(T['--gold'], T[g]);
    ok(r >= 4.5, name + ': the accent as 11px label text on ' + g + ' = ' + r.toFixed(2));
  }
  // (d) the ink ON the accent (button.primary, #chat-send, .mpill.live, .ap-btn.on)
  {
    const r = ratio(T['--sd-on-accent'], T['--gold']);
    ok(r >= 4.5, name + ': --sd-on-accent on the accent fill = ' + r.toFixed(2));
    // impeccable gray-on-color: gray ink (chroma <20) on a chromatic bg (chroma >=40)
    ok(!(spread(T['--sd-on-accent']) < 20 && spread(T['--gold']) >= 40),
       name + ': the ink on the accent has CHROMA (' + spread(T['--sd-on-accent'])
       + ') — impeccable gray-on-color forbids grey ink on a chromatic ground');
  }
  // (e) status inks are small glyphs and pills: 3.0, measured.
  for (const ink of ['--ok', '--warn', '--bad']) {
    for (const g of ['--bg', '--card']) {
      const r = ratio(T[ink], T[g]);
      ok(r >= 3.0, name + ': ' + ink + ' on ' + g + ' = ' + r.toFixed(2));
    }
  }
  // (f) hairlines must actually be visible against what they sit on.
  for (const g of ['--bg', '--bg2', '--card', '--card2', '--st-btn', '--st-inp']) {
    const r = ratio(T['--line2'], T[g]);
    ok(r >= 1.12, name + ': --line2 hairline on ' + g + ' = ' + r.toFixed(2) + ' (visible)');
  }
  ok(ratio(T['--line'], T['--card']) >= 1.08,
     name + ': --line separator on --card = ' + ratio(T['--line'], T['--card']).toFixed(2));
  // (g) disabled buttons are opacity:.4 over the control ground — measure the composite
  {
    const comp = over(T['--fg'], T['--st-btn'], 0.4);
    const r = ratio(comp, T['--st-btn']);
    ok(r >= 1.6, name + ': a DISABLED button label (opacity .4 composite ' + comp
       + ') still reads at ' + r.toFixed(2) + ' against its ground — greyed, not gone');
  }
  // (h) the DIRECTIONS. Hover and the field-well invert between the two variants, and
  // getting the sign wrong is the exact defect the chrome axis shipped once.
  const dark = name === 'studio-dark';
  ok(dark ? lum(T['--st-hi']) > lum(T['--st-btn']) : lum(T['--st-hi']) < lum(T['--st-btn']),
     name + ': hover ' + (dark ? 'LIGHTENS' : 'DARKENS') + ' — correct for this ground');
  ok(dark ? lum(T['--st-inp']) < lum(T['--st-btn']) : lum(T['--st-inp']) > lum(T['--st-btn']),
     name + ': a field ' + (dark ? 'RECEDES below' : 'RISES above') + ' the button ground '
     + '(the well rule, signed for the ground)');
  ok(dark ? lum(T['--card']) > lum(T['--bg']) : lum(T['--card']) > lum(T['--bg']),
     name + ': a card is lighter than the page on both grounds (cards lift)');
  // (i) the neutrals are TINTED, not grey (impeccable: never pure black/gray)
  for (const t of ['--bg', '--bg2', '--card', '--card2', '--cream', '--fg']) {
    ok(spread(T[t]) >= 1, name + ': ' + t + ' is TINTED, not a pure grey (spread '
       + spread(T[t]) + ')');
    ok(!/^#(000|000000|fff|ffffff)$/i.test(T[t]) || t === '--card',
       name + ': ' + t + ' is not pure black or pure white');
  }
  // (j) the accent is ONE accent
  eq(name + ': --accent and --gold are the SAME value — one accent, used sparingly',
     T['--accent'], T['--gold']);
  // (k) impeccable ai-color-palette: no purple/violet accent (hue 260-310, chroma >=50)
  {
    const h = T['--gold'].replace('#', '');
    const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    let hue = 0;
    if (mx !== mn) {
      const d = mx - mn;
      hue = mx === r ? ((g - b) / d + (g < b ? 6 : 0)) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      hue *= 60;
    }
    ok(!(hue >= 260 && hue <= 310 && spread(T['--gold']) >= 50),
       name + ': the accent is not the purple/violet AI tell (hue ' + Math.round(hue) + ')');
    ok(hue > 120 && hue < 220, name + ': …it is the cool teal the design is built around '
       + '(hue ' + Math.round(hue) + '), and the neutrals are tinted to match');
  }
  // (l) impeccable cream-palette on the LIGHT variant: min>=209 AND r>=g>=b AND r-b in 6..48
  if (!dark) {
    const h = T['--bg'].replace('#', '');
    const [r, g, b] = [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
    ok(!(Math.min(r, g, b) >= 209 && r >= g && g >= b && (r - b) >= 6 && (r - b) <= 48),
       'studio-light is a COOL near-white, not the warm-cream AI default (r' + r + ' g' + g
       + ' b' + b + ')');
  }
}
// the two variants must be genuinely different looks, not a nudge
{
  const moved = ['--bg', '--card', '--cream', '--fg', '--gold', '--line2']
    .filter(t => LT[t] && LT[t] !== DK[t]);
  eq('studio-light moves every structural token (it is a variant, not a tint)',
     moved.length, 6);
  ok(lum(LT['--bg']) > 0.7 && lum(DK['--bg']) < 0.05,
     'the two grounds are a real light/dark pair (lum ' + lum(LT['--bg']).toFixed(2)
     + ' vs ' + lum(DK['--bg']).toFixed(3) + ')');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. IMPECCABLE — the deterministic subset, EXECUTED against the stylesheet
//    Thresholds quoted from pbakaus/impeccable's own source, not its prose.
// ═══════════════════════════════════════════════════════════════════════════════
console.log('5. impeccable (deterministic rules, run against the sheet)');
const decls = [];
for (const r of RULES) {
  for (const d of r.body.split(';')) {
    const t = d.trim(); if (!t) continue;
    const c = t.indexOf(':'); if (c < 0) continue;
    decls.push({ sel: r.sel, prop: t.slice(0, c).trim(), val: t.slice(c + 1).trim(), body: r.body });
  }
}
const valuesOf = p => decls.filter(d => d.prop === p);

// overused-font: the 21-name list. Inter / Helvetica / Arial / Space Grotesk are on it.
{
  const BANNED = ['inter', 'roboto', 'open sans', 'lato', 'montserrat', 'arial', 'helvetica',
    'fraunces', 'instrument sans', 'instrument serif', 'geist', 'mona sans',
    'plus jakarta sans', 'space grotesk', 'recoleta'];
  const fams = valuesOf('font-family').map(d => d.val.toLowerCase())
    .concat(Object.entries(DK).filter(([k]) => k === '--sd-sans').map(([, v]) => v.toLowerCase()));
  const hits = [];
  for (const f of fams) for (const b of BANNED) if (f.includes(b)) hits.push(b);
  eq('overused-font: no monoculture typeface anywhere', [...new Set(hits)], []);
  ok(/Avenir Next/.test(DK['--sd-sans']),
     '…the UI sans is "Avenir Next" — on none of the lists, ships with macOS, zero bytes '
     + 'to download, and gives studio a voice that is not Editorial\'s and not the default');
  ok(/sans-serif\s*$/.test(DK['--sd-sans'].trim()),
     '…and the stack ends in a real generic fallback');
}
// flat-type-hierarchy: >=3 distinct sizes AND max/min < 2.0 is a finding.
{
  const sizes = [...new Set(decls.filter(d => d.prop === 'font-size')
    .map(d => parseFloat(d.val)).filter(v => v >= 8 && v <= 200)
    .concat(valuesOf('font').map(d => parseFloat(d.val)).filter(v => v >= 8 && v <= 200)))]
    .sort((a, b) => a - b);
  const r = sizes[sizes.length - 1] / sizes[0];
  ok(sizes.length >= 3 && r >= 2.0,
     'flat-type-hierarchy: the ramp spans ' + sizes[0] + '-' + sizes[sizes.length - 1]
     + 'px = ' + r.toFixed(2) + 'x (needs >= 2.0)');
  // undersized-ui-text: 11px is the floor for interactive / furniture / <=20-char runs.
  eq('undersized-ui-text: nothing in the design is under 11px (Editorial\'s 7-10px '
     + 'micro-caps are all raised — studio buys density from the GAPS)',
     sizes.filter(s => s < 11), []);
  // tiny-text: body copy must clear 12px. The prose sites, named.
  const prose = decls.filter(d => d.prop === 'font-size'
    && /\.cmsg\.assistant \.body|\.cap-desc|\.art-md p|dialog li|\.coach p/.test(d.sel))
    .map(d => parseFloat(d.val));
  eq('tiny-text: every body-copy site is >= 12px', prose.filter(s => s < 12), []);
}
// wide-tracking (>0.05em) / extreme-negative-tracking (<=-0.05em) / all-caps-body
{
  const ls = decls.filter(d => d.prop === 'letter-spacing');
  const wide = ls.filter(d => /em$/.test(d.val) && Math.abs(parseFloat(d.val)) > 0.05);
  eq('wide-tracking / extreme-negative-tracking: every tracking value is inside '
     + '+/-0.05em', wide.map(d => d.sel.slice(0, 40) + ':' + d.val), []);
  ok(ls.filter(d => d.val === 'normal').length > 20,
     '…and tracking is reset to normal in ' + ls.filter(d => d.val === 'normal').length
     + ' places — the tracked mono small-caps voice is Editorial\'s and is not borrowed');
  const caps = decls.filter(d => d.prop === 'text-transform' && d.val === 'uppercase');
  eq('all-caps-body: the design introduces no uppercase transform at all',
     caps.map(d => d.sel.slice(0, 40)), []);
  ok(decls.filter(d => d.prop === 'text-transform' && d.val === 'none').length > 25,
     '…and it REMOVES uppercase in ' + decls.filter(d => d.prop === 'text-transform'
     && d.val === 'none').length + ' places');
}
// tight-leading: line-height/font-size >= 1.3 on prose
{
  const bad = [];
  for (const r of RULES) {
    const fs = /font-size:\s*([\d.]+)px/.exec(r.body);
    const lh = /line-height:\s*([\d.]+)(?!px)/.exec(r.body);
    if (fs && lh && parseFloat(lh[1]) < 1.3 && !/\.st-word|pre|code|\.chip|button|mode-chip|talk/.test(r.sel))
      bad.push(r.sel.slice(0, 40) + ' ' + lh[1]);
  }
  eq('tight-leading: no prose leading under 1.3 (control line-height:1 is exempt — a '
     + 'button is not a paragraph)', bad, []);
}
// bounce-easing: cubic-bezier y outside [-0.1, 1.1], or a bounce/elastic name
{
  const bez = [...noC.matchAll(/cubic-bezier\(([^)]+)\)/g)].map(m =>
    m[1].split(',').map(v => parseFloat(v)));
  ok(bez.length > 0, 'bounce-easing: the design declares an easing (' + bez.length + ' uses)');
  const bad = bez.filter(([, y1, , y2]) => y1 < -0.1 || y1 > 1.1 || y2 < -0.1 || y2 > 1.1);
  eq('…and every control point is inside [-0.1, 1.1] — fast ease-out only', bad, []);
  ok(!/bounce|elastic|wobble|jiggle|spring/i.test(noC), '…and no bounce/elastic keyword');
  eq('…and the design adds ZERO keyframes (the panel still has exactly its one)',
     (noC.match(/@keyframes/g) || []).length, 0);
  // one easing, not a zoo
  const uniq = [...new Set([...noC.matchAll(/cubic-bezier\([^)]+\)/g)].map(m => m[0]))];
  eq('…and it is ONE easing everywhere, not a zoo', uniq.length, 1);
}
// layout-transition: never animate width/height/padding/margin
{
  const bad = valuesOf('transition').filter(d =>
    /\b(width|height|max-width|min-width|max-height|min-height|padding|margin)\b/.test(d.val));
  eq('layout-transition: nothing animates a layout property', bad.map(d => d.sel.slice(0, 40)), []);
}
// dark-glow + gpt-thin-border-wide-shadow
{
  const shadows = valuesOf('box-shadow').map(d => d.val)
    .concat(Object.entries(DK).concat(Object.entries(LT))
      .filter(([k]) => /shadow|elev/.test(k)).map(([, v]) => v));
  const chromatic = [];
  const wide = [];
  for (const s of shadows) {
    if (s === 'none') continue;
    for (const layer of s.split(/,(?![^(]*\))/)) {
      const blur = (layer.match(/(-?[\d.]+)px/g) || [])[2];
      const b = blur ? Math.abs(parseFloat(blur)) : 0;
      if (b >= 16) wide.push(layer.trim());
      const rgb = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(layer);
      if (rgb) {
        const c = [+rgb[1], +rgb[2], +rgb[3]];
        if (Math.max(...c) - Math.min(...c) >= 30 && b > 4) chromatic.push(layer.trim());
      } else if (/#[0-9a-f]{3,6}/i.test(layer)) {
        const hx = /#[0-9a-f]{3,6}/i.exec(layer)[0];
        if (spread(hx) >= 30 && b > 4) chromatic.push(layer.trim());
      }
    }
  }
  eq('dark-glow: no chromatic blurred shadow anywhere — studio\'s elevation is neutral',
     chromatic, []);
  eq('gpt-thin-border-wide-shadow: with hairlines everywhere, no shadow blurs >=16px',
     wide, []);
  ok(/\.dot\b/.test(sd) && /box-shadow:none/.test(sd),
     '…and Editorial\'s green halo on the status dot is explicitly removed');
}
// side-tab / border-accent-on-rounded: no >=2px single-edge accent on a rounded box
{
  const bad = [];
  for (const r of RULES) {
    for (const m of r.body.matchAll(/border-(left|right|top|bottom):\s*([\d.]+)px[^;]*/g)) {
      const w = parseFloat(m[2]);
      const chromatic = /--gold|--accent|--ok|--bad|--warn/.test(m[0]);
      if (w >= 2 && chromatic) bad.push(r.sel.slice(0, 46) + ' → ' + m[0].trim().slice(0, 40));
    }
  }
  eq('side-tab / border-accent-on-rounded: no accent edge >=2px anywhere. Editorial\'s '
     + 'selected-row idiom IS that shape, so studio states are ground + ink instead',
     bad, []);
  // and the ones Editorial owns are explicitly neutralised
  ok(/\.cs-item[^{]*\{[^}]*border-left:0/.test(noC.replace(/\n/g, ' ')),
     '…and .cs-item\'s 2px accent edge is explicitly zeroed');
  ok(/\.mrow[^{]*\{[^}]*border-left:0/.test(noC.replace(/\n/g, ' ')),
     '…and .mrow.sel\'s is too');
  ok(/border-left:1px solid var\(--gold\)/.test(noC),
     '…while the approval card keeps a 1px accent rule, which is under BOTH thresholds');
}
// nested-cards (the CSS half): a card is (shadow OR border) AND (radius OR bg). Every
// surface that can sit INSIDE another surface must therefore carry a ground with NO
// border and NO shadow.
{
  const inner = ['.chatcode', '.filecard', '.cmsg .approval', '.ap-cmd'];
  for (const s of inner) {
    const r = RULES.find(x => x.sel.endsWith(s) && /background/.test(x.body));
    ok(!!r, 'nested-cards: ' + s + ' is styled here');
    if (!r) continue;
    ok(/border:0/.test(r.body) || /border:\s*0/.test(r.body),
       '…and ' + s + ' carries a GROUND WITH NO BORDER, so a code block inside a user '
       + 'bubble is not a card inside a card (the rule fires at depth TWO)');
    ok(!/box-shadow:\s*(?!none)/.test(r.body), '…and no shadow on ' + s);
  }
  const pre = RULES.find(r => r.sel.split(',').some(s => s.trim().endsWith('pre')));
  ok(pre && /border:0/.test(pre.body),
     '…and <pre> loses its border too (a bordered pre inside a dialog is the same defect)');
}
// gradient-text / radial-halo / repeating-stripes / marquee / codex-grid / image-hover
{
  ok(!/background-clip:\s*text|-webkit-background-clip:\s*text/.test(noC),
     'gradient-text: absent');
  ok(!/radial-gradient/.test(noC), 'radial-halo / radial-spotlight-glow: no radial gradient');
  ok(!/repeating-(linear|radial|conic)-gradient/.test(noC), 'repeating-stripes-gradient: absent');
  ok(!/linear-gradient|conic-gradient/.test(noC),
     '…and no gradient of any kind: studio is flat grounds and hairlines');
  ok(!/marquee/.test(noC), 'marquee: absent');
  ok(!/transparent\s+\d+px/.test(noC), 'codex-grid-background: no hairline-grid background');
  ok(!/img[^{]*:hover[^}]*transform/.test(noC), 'image-hover-transform: absent');
  ok(!/text-align:\s*justify/.test(noC), 'justified-text: absent');
  ok(!/animation:/.test(noC), 'pulsing-dot / blinking-cursor: the design declares no animation');
}
// monotonous-spacing: >=10 spacing values, dominant >60% AND <=3 unique = finding
{
  const sp = decls.filter(d => /^(padding|margin|gap|row-gap|column-gap)/.test(d.prop))
    .flatMap(d => (d.val.match(/-?[\d.]+px/g) || []).map(v => Math.round(parseFloat(v) / 4) * 4));
  const uniq = [...new Set(sp)];
  const counts = {};
  for (const v of sp) counts[v] = (counts[v] || 0) + 1;
  const dom = Math.max(...Object.values(counts)) / sp.length;
  ok(sp.length >= 10, 'monotonous-spacing: ' + sp.length + ' spacing values to judge');
  ok(!(dom > 0.6 && uniq.length <= 3),
     '…and the spacing is a real scale, not one value everywhere (' + uniq.length
     + ' unique on the 4px grid, most common used ' + Math.round(dom * 100) + '% of the time)');
}
// the hardcoded-literal defect class (--on-wash's lesson, generalised): a colour a
// palette swap cannot reach is a bug waiting for the other variant.
{
  const lits = decls.filter(d => /color|background|border|shadow|fill/.test(d.prop))
    .filter(d => /#[0-9a-fA-F]{3,8}\b/.test(d.val))
    .filter(d => !d.sel.includes('[data-dvariant'))
    .filter(d => !RULES.find(r => r.sel === DARKSEL && r.body === d.body));
  eq('no hardcoded colour literal outside the two token blocks — every colour is a '
     + 'token, so the light variant reaches all of them (this is the #0a0910 / --on-wash '
     + 'defect class, and Editorial hardcodes that near-black in TWO pre rules which '
     + 'studio overrides with tokens)',
     lits.map(d => d.sel.slice(0, 40) + ' ' + d.prop + ':' + d.val), []);
  ok(/html\[data-design="studio"\] pre[\s\S]{0,200}background:var\(--st-inp\)/.test(noC),
     '…and <pre>\'s Editorial near-black IS overridden with a token');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. THE SPECIFICITY RESTATEMENTS — found by driving, pinned so they cannot be lost
// ═══════════════════════════════════════════════════════════════════════════════
console.log('6. the states another rule owns (the collision trap)');
{
  // `html[data-design="studio"] aside` is (0,1,2) — EXACTLY `body.rail-slim aside`.
  // Being the later sheet, studio silently won and ⌘\ produced a 228px column of
  // centred glyphs. Every such state has to be restated. These are pinned WITH the
  // reason, so a future tidy-up cannot delete them as redundant.
  for (const [sel, prop] of [
    ['html[data-design="studio"] body.rail-slim aside', 'width'],
    ['html[data-design="studio"] body.sessions-collapsed #chat-sessions', 'width'],
    // v1.5.24 — THE THIRD INSTANCE, and the sharpest: the collapsed sessions rail became a
    // labelled reopen strip, and `html[data-design="studio"] button` is (0,1,1) while
    // Editorial's `body.sessions-collapsed #cs-reopen` is (1,1,1). The generic studio
    // button rule LOSES, so without this restatement the one control that gets your
    // sessions back would have kept Editorial's tracked mono caps while every other
    // studio control changed. Found by reading the trap this list already records —
    // which is what a pinned trap is for.
    ['html[data-design="studio"] body.sessions-collapsed #cs-reopen', 'font-size'],
    // v1.5.26 — THE FIFTH INSTANCE. The sidebar gained a third (fully hidden) state with
    // its own edge reopener, and `body.rail-hidden #rail-reopen` is (1,1,1) against this
    // sheet's generic `button` at (0,1,1): without the restatement the one control that
    // gets the sidebar back would keep Editorial's tracked mono caps while every other
    // studio control changed. ⚠️ The SIXTH instance of the same trap in this wave was a
    // property the base rule OMITTED rather than one it stated — this sheet's
    // `button { height }` collapsed that strip to 30px — which is why the base rule now
    // states `height:auto` (fenced in test_theme_packs.js).
    ['html[data-design="studio"] body.rail-hidden #rail-reopen', 'font-size'],
    // v1.5.26 — the audio-mode switch. Typography and ground only; the geometry is
    // deliberately NOT restated (one object in every design, the sessions-rail lesson).
    ['html[data-design="studio"] #chat-audiosw .asw-zone', 'font-family'],
  ]) {
    const r = RULES.find(x => x.sel === sel);
    ok(!!r, 'restated: ' + sel);
    if (r) ok(r.body.includes(prop + ':'),
      '…and it restates ' + prop + ', the property the collision broke');
  }
  const slim = RULES.find(x => x.sel === 'html[data-design="studio"] body.rail-slim aside');
  ok(slim && /width:56px/.test(slim.body),
     'the collapsed rail is still 56px in studio (it was 228px of empty column)');
  const col = RULES.find(x => x.sel === 'html[data-design="studio"] body.sessions-collapsed #chat-sessions');
  // v1.5.24: 24px → 44px. v1.5.26: 44px → 34px (Debi — office.html's house strip width).
  // The number is not duplicated as a literal on both sides — it is read from EDITORIAL's
  // rule and required to match, because a collapse geometry that differs per design is
  // exactly how studio ended up with a 22×14px reopen target.
  const edCol = /body\.sessions-collapsed #chat-sessions \{[^}]*width:(\d+)px/.exec(inlineCss);
  ok(!!edCol, 'Editorial states the collapsed strip width');
  ok(col && new RegExp('width:' + edCol[1] + 'px').test(col.body) && /padding-right:0/.test(col.body),
     'the collapsed sessions rail is the SAME ' + edCol[1] + 'px in studio as in Editorial, '
     + 'with no padding (24px pre-v1.5.24, 44px in v1.5.24, 34px since Debi ruled for '
     + 'office.html\'s own reopener width)');
  ok(+edCol[1] === 34, '…and that width is office.html\'s house 34px in this design too. '
     + 'The hit floor is met by the FULL-HEIGHT reopener, not by the strip\'s narrow axis '
     + '— the rule that carries the argument is the `flex:1 1 auto` + `min-height:44px` '
     + 'pair fenced in test_editorial_debt.js §6, so shrinking the width without keeping '
     + 'the full-height click area fails there.');
  const sro34 = RULES.find(x => x.sel === 'html[data-design="studio"] body.sessions-collapsed #cs-reopen');
  ok(sro34 && !/width:\s*\d/.test(sro34.body),
     '…and studio\'s reopener restatement is TYPOGRAPHY ONLY: it must not re-declare a '
     + 'width, or the two designs would drift apart again at the new narrower number');
  // and the states studio deliberately does NOT restate, because Editorial's rule is
  // MORE specific and correctly wins — recorded so the next reader does not "fix" it.
  ok(/body\.chat-mode main \{/.test(inlineCss),
     'body.chat-mode main is (0,1,2) vs studio\'s (0,1,1) — Editorial wins, and that is '
     + 'correct: the chat lane\'s full-bleed padding is layout, not design');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 7. THE PER-SURFACE BAR (spec §2) — every named surface is actually addressed
// ═══════════════════════════════════════════════════════════════════════════════
console.log('7. every surface the spec names is addressed');
{
  const sels = RULES.map(r => r.sel).join(' | ');
  const SURFACES = {
    'sidebar':      ['aside', '.brand', '.navlbl', 'nav a', 'nav a.on'],
    'MOT Deck':     ['.card', '.card .state', '.card .meta', '.card .actions', '.metric',
                     '.activity', '.grid', 'h1', '.kicker .lbl'],
    'chat lane':    ['#chat-inputrow', '#chat-input', '#chat-send', '.cmsg.user .body',
                     '.cmsg.assistant .body', '.cmsg .who', '.chatcode', '.cs-item',
                     '#chat-msgs', '.mode-chip'],
    'models':       ['.mrow', '.mrow .mname', '.mrow .mbadges', '#models-detail',
                     '.md-title', '#mb-q', '.dlrow .dlbar', '#models-toggle'],
    'capabilities': ['.cap-card', '.cap-row', '.cap-name', '.cap-desc', '.cap-sw .knob',
                     '.cap-btn', '.cap-h'],
    'logs':         ['.glog-row', '.glog-base', 'dialog', '#log-note'],
  };
  for (const [surface, needed] of Object.entries(SURFACES)) {
    const missing = needed.filter(n => !sels.includes(n));
    eq(surface + ': every component the spec names is restyled', missing, []);
  }
  // the flagship's specific asks
  ok(/#chat-inputrow[\s\S]{0,300}border-radius:var\(--sd-r-xl\)/.test(noC),
     'the composer is ONE rounded field (the shell owns the ground and the radius)');
  ok(/#chat-inputrow:focus-within/.test(noC),
     '…and the focus state lives on the SHELL, so the whole composer lights up as one object');
  ok(/#chat-input[\s\S]{0,200}background:transparent[\s\S]{0,120}border:0/.test(noC),
     '…and the textarea inside it is transparent and borderless');
  ok(/#chat-send[\s\S]{0,240}border-radius:999px/.test(noC),
     '…and send is a round accent icon button');
  ok(/\.cmsg\.user \.body[\s\S]{0,120}margin-left:auto/.test(noC),
     'the 14% editorial indent is gone: the user turn right-aligns instead');
  ok(/\.cmsg\.assistant \.body[\s\S]{0,120}border-left:0/.test(noC),
     '…and the assistant\'s gold rail is gone: plain prose, as a modern chat reads');
  ok(/#chat-msgs[\s\S]{0,120}margin:0 auto/.test(noC)
     && /#chat-bar[\s\S]{0,140}margin:4px auto 0/.test(noC),
     '…and the transcript and the composer share ONE centred lane, so they cannot drift');
  ok(/\.mrow \{[\s\S]{0,200}display:grid/.test(noC),
     'models rows are a two-column grid (name left, badges aligned right) — the '
     + 'LM-Studio table read, not a stack of tiles');
  ok(/\.mrow \+ \.mrow[\s\S]{0,80}border-top:1px solid/.test(noC),
     '…separated by hairlines rather than gaps');
  ok(/\.caps-tabs \{[\s\S]{0,200}background:var\(--st-btn\)/.test(noC),
     'the sub-tab strip is a segmented control');
  // the icon set is reused, not reinvented
  ok(/\.st-only \{[\s\S]{0,120}display:inline-flex/.test(noC)
     && /\.ed-only \{ display:none/.test(noC),
     'studio reuses the EXISTING dual-child icon contract — zero DOM change, zero '
     + 'renderer branch');
  // a real focus ring, which Editorial does not have everywhere
  ok(/:focus-visible[\s\S]{0,120}outline:2px solid var\(--gold\)/.test(noC),
     'and studio adds a visible focus ring: keyboard reach is not weaker than the mouse\'s');
}

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
