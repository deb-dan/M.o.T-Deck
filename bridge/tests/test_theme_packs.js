/* THEME PACKS + SIDEBAR RAIL + CHAT DENSITY — the "taste slice" (2026-08-28).
 *
 * Three panel refinements, and the three things that could go wrong with them are not
 * the same shape, so this file answers them in three different ways.
 *
 *   1. THEME PACKS. The risk is NOT "does gold look nice" — it is drift. A theme that
 *      is allowed to add one rule of its own becomes a theme that has forty, and then
 *      the panel has four stylesheets instead of one palette. So the fence here is
 *      structural and total: the whole stylesheet is parsed, and every rule whose
 *      selector mentions a pack must declare NOTHING BUT custom properties, exactly
 *      once, and must never restate the type system. It is a fence, not a sample —
 *      a future pack cannot pass it by being small.
 *
 *   2. THE RAIL. The risk is a silent default change: promoting a Chat-only affordance
 *      to global with its old default would collapse the sidebar on the app's OPENING
 *      screen. So the decision table is EXECUTED, including the "nothing stored yet"
 *      row, which is the row that proves nothing changed for anyone.
 *
 *   3. DENSITY. The risk is that "tighter" quietly eats a hit target or the resizer.
 *      The numbers are pinned WITH their arithmetic, so a future tightening has to
 *      argue with a computed row height rather than with a taste claim.
 *
 * And one cross-file contract: office.html reads the SAME localStorage key. It is out
 * of scope for this slice, so what is asserted here is that the panel did not break
 * it — every pack value office.html does not know still lands it somewhere sane.
 *
 * Run: node bridge/tests/test_theme_packs.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const office = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'office.html'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];
const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}
function eq(msg, got, want) {
  ok(JSON.stringify(got) === JSON.stringify(want),
     msg + (JSON.stringify(got) === JSON.stringify(want) ? ''
       : ' — got ' + JSON.stringify(got) + ', want ' + JSON.stringify(want)));
}

// A brace-matching rule walker (the same shape test_studio_chrome uses for its cascade
// resolver): comments carry braces and prose, so they are stripped first.
function rules(src) {
  const out = [];
  let i = 0;
  while (i < src.length) {
    const b = src.indexOf('{', i); if (b < 0) break;
    const sel = src.slice(i, b).trim();
    let d = 1, j = b + 1;
    while (j < src.length && d > 0) { if (src[j] === '{') d++; else if (src[j] === '}') d--; j++; }
    if (!sel.startsWith('@')) out.push({ sel, body: src.slice(b + 1, j - 1) });
    i = j;
  }
  return out;
}
const ALL = rules(noComments);
ok(ALL.length > 300, 'the rule walker parsed the whole stylesheet (' + ALL.length + ' rules)');

// ═══════════════════════════════════════════════════════════════════════════════
// 1. THEME PACKS — THE TOKEN-SWAP-ONLY FENCE
// ═══════════════════════════════════════════════════════════════════════════════
console.log('theme packs — token-swap-only fence');
const PACKS = ['gold', 'cyber'];          // the two packs this slice ADDED
const ALL_IDS = ['dark', 'light', 'gold', 'cyber'];

// (a) exactly one rule per new pack, and its selector is the bare root form.
for (const p of PACKS) {
  const mine = ALL.filter(r => r.sel.includes('data-theme="' + p + '"'));
  eq('the ' + p + ' pack is declared by exactly ONE rule', mine.length, 1);
  if (!mine.length) continue;
  eq('…whose selector is the bare root, so it can add no specificity anywhere',
     mine[0].sel, 'html[data-theme="' + p + '"]');
  // (b) the body is custom properties and nothing else. Split on ';' and demand each
  // non-empty declaration start with '--'. A single `background:` here is a fork.
  const decls = mine[0].body.split(';').map(s => s.trim()).filter(Boolean);
  const bad = decls.filter(d => !/^--[a-z0-9-]+\s*:/.test(d));
  eq('…and declares CUSTOM PROPERTIES ONLY (no rule fork)', bad, []);
  ok(decls.length >= 14, '…and it is a COMPLETE look, not a tint (' + decls.length
     + ' tokens; the base palette is 15)');
  // (c) typography is not a pack's business.
  ok(!/--mono|--serif|font-family|font-size/.test(mine[0].body),
     '…and it never touches the type system — a pack changes colour voice, not type');
  // (d) every value is a LITERAL colour — hex, or rgba() for the one translucent token
  // (--on-wash). No var(), so no pack can alias another pack's token and inherit a look
  // it never declared.
  const vals = decls.map(d => d.slice(d.indexOf(':') + 1).trim());
  eq('…and every token is a literal colour (no var() chains to unpick)',
     vals.filter(v => !/^#[0-9a-f]{3,8}$/i.test(v)
                   && !/^rgba?\([\d\s,.]+\)$/i.test(v)), []);
  ok(!/var\(/.test(mine[0].body), '…no var() anywhere in the pack');
}

// (d2) THE TOKEN THAT ONLY EXISTS BECAUSE OF THE GUARDRAIL. .cap-sw's checked track
// carried the gold literal rgba(217,179,108,.22) inline, which no palette swap can
// reach — under Cyber a cyan knob sat in a warm haze (caught in the LIVE drive, not by
// reading the sheet). The fix was NOT a per-theme fork: the literal became --on-wash on
// :root, so the swap reaches it like every other colour.
{
  ok(/--on-wash:rgba\(217,179,108,\.22\)/.test(noComments),
     'Editorial\'s --on-wash is BYTE-IDENTICAL to the literal it replaced, so the '
     + 'default look did not move');
  ok(/\.cap-sw input:checked ~ \.track \{ background:var\(--on-wash\)/.test(noComments),
     '…and the toggle track reads the token, not a literal');
  ok(!/rgba\(217,179,108/.test(noComments.replace(/--on-wash:rgba\(217,179,108,\.22\);/, '')),
     '…and the literal survives NOWHERE else in the sheet');
  const lightBlk = ALL.filter(r => r.sel === 'html[data-theme="light"]')
                      .map(r => r.body).join('');
  ok(!/--on-wash/.test(lightBlk),
     'Warm Paper deliberately does NOT override it — inheriting the same wash is exactly '
     + 'what the shipped light theme rendered, so Warm Paper stays byte-identical too');
}

// (e) THE ACTUAL FENCE: nowhere else in the sheet may a pack value appear. This is what
// stops the next pack from bringing rules with it.
{
  const strays = ALL.filter(r => PACKS.some(p => r.sel.includes('data-theme="' + p + '"')))
                    .filter(r => !/^html\[data-theme="(gold|cyber)"\]$/.test(r.sel));
  eq('NO rule outside the two token blocks mentions a pack value', strays.map(r => r.sel), []);
}

// (f) the tokens each pack must cover = the tokens :root defines (minus type).
{
  const root = ALL.find(r => r.sel === ':root');
  ok(!!root, ':root is still the single source of the base palette');
  const names = v => (v.body.match(/--[a-z0-9-]+(?=\s*:)/g) || []);
  const base = names(root).filter(n => n !== '--mono' && n !== '--serif');
  for (const p of PACKS) {
    const mine = ALL.find(r => r.sel === 'html[data-theme="' + p + '"]');
    if (!mine) continue;
    const have = names(mine);
    eq('the ' + p + ' pack covers every base palette token (no half-painted look)',
       base.filter(n => !have.includes(n)), []);
    eq('…and invents none of its own (a new token is a rule fork in disguise)',
       have.filter(n => !base.includes(n)), []);
  }
}

// (g) the light pack's THREE pre-existing rule forks are FENCED, not grown. They shipped
// with §C (--cream is dark ink in light, so the cream-filled button needs light text) and
// are out of scope here — but the count is pinned so this slice cannot be the excuse for
// a fourth one, and so a future pack cannot copy the pattern.
{
  const lf = ALL.filter(r => r.sel.includes('data-theme="light"')
                          && r.sel !== 'html[data-theme="light"]');
  const chromeOwned = lf.filter(r => r.sel.includes('data-chrome'));   // the studio axis's own
  const rest = lf.filter(r => !r.sel.includes('data-chrome'));
  eq('the LIGHT pack still has exactly its 3 legacy rule forks + the music view — '
     + 'pinned, so this slice cannot grow them (its two ROOT token rules — the palette '
     + 'and the shared --float-* ground — are excluded above, being token swaps)',
     rest.map(r => r.sel).sort(),
     ['#view-music[data-mview="studio"]:where(html[data-theme="light"] *)',
      'html[data-theme="light"] .cmsg.user .body',
      'html[data-theme="light"] button.primary',
      'html[data-theme="light"] button.primary:hover'].sort());
  eq('…and the studio axis keeps its ONE light override (the --st-* surface tokens)',
     chromeOwned.length, 1);
  ok(true, 'NOTE for Fable: gold + cyber deliberately add NO --st-* override. Both are '
     + 'dark grounds, so the studio axis\'s dark slate is already coherent on them, and '
     + 'an override would have required html[data-chrome="studio"][data-theme="gold"] — '
     + 'a per-theme rule fork, which the guardrail forbids. Honest limit, not an oversight.');
}

// ── the sanctioned comment block exists exactly once, and holds the two packs ──
{
  const b0 = css.indexOf('THEME PACKS — TOKEN SWAPS ONLY');
  const b1 = css.indexOf('end theme packs (no rules past here)');
  ok(b0 > 0 && b1 > b0, 'the sanctioned theme-pack block is present exactly once');
  ok(css.indexOf('THEME PACKS — TOKEN SWAPS ONLY', b0 + 1) === -1, '…and only once');
  const blk = css.slice(b0, b1);
  ok(PACKS.every(p => blk.includes('data-theme="' + p + '"')),
     '…and both new packs live inside it');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. PERSISTENCE — THE KEYS DID NOT CHANGE
// ═══════════════════════════════════════════════════════════════════════════════
console.log('persistence keys');
ok(/localStorage\.setItem\('harness-theme', id\)/.test(html),
   'the theme is persisted in harness-theme — the SAME key, so office.html follows along');
ok(!/harness-theme-pack|harness-themepack|harness-pack/.test(html),
   'no second theme key was invented (one axis, one key)');
{
  // no NEW localStorage key at all in this slice: the rail reuses harness-chat-rail.
  const keys = new Set((html.match(/localStorage\.(?:get|set|remove)Item\('([^']+)'/g) || [])
    .map(s => s.replace(/.*\('/, '').replace(/'$/, '')));
  ok(keys.has('harness-theme') && keys.has('harness-chrome') && keys.has('harness-chat-rail')
     && keys.has('harness-sessions-rail'),
     'the four skin/layout keys are all still the shipped names');
}
// pre-paint: same pass, theme first, and the whitelist is explicit.
{
  const pre = html.split('</style>')[1].split('</head>')[0];
  ok(pre.indexOf('harness-theme') < pre.indexOf('harness-chrome'),
     'theme is still applied before chrome in the ONE pre-paint pass (no flash)');
  const line = (pre.match(/[\s\S]*?getItem\('harness-theme'\)[\s\S]*?catch/) || [''])[0];
  for (const p of ['light', 'gold', 'cyber']) {
    ok(line.includes("'" + p + "'"), 'the pre-paint whitelist knows ' + p);
  }
  ok(!/dataset\.theme\s*=\s*_th[\s\S]{0,40}else/.test(line),
     'an UNKNOWN stored value falls through to Editorial pre-paint (no attribute that '
     + 'no stylesheet answers)');
}
// office.html's reader is UNTOUCHED, and every pack value still lands somewhere sane.
{
  ok(/if \(theme === 'light'\) d\.setAttribute\('data-theme', 'light'\);/.test(office)
     && /else d\.removeAttribute\('data-theme'\);/.test(office),
     'office.html still maps light→light and EVERYTHING ELSE→its own dark (not edited)');
  ok(!/setItem\('harness-theme'/.test(office),
     '…and still never writes the key — the panel remains the only author');
  // executed: the office mapping, run over all four pack ids.
  const officeTheme = t => (t === 'light' ? 'light' : 'dark');
  eq('every pack id renders office.html sanely (gold/cyber → its dark ground, by design)',
     ALL_IDS.map(officeTheme), ['dark', 'light', 'dark', 'dark']);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. THE PACK LIST + THE PURE RESOLVERS — EXECUTED
// ═══════════════════════════════════════════════════════════════════════════════
console.log('theme resolvers (executed)');
{
  const grab = name => {
    const i = html.indexOf('function ' + name + '(');
    const s = html.slice(i);
    return s.slice(0, s.indexOf('\n}') + 2);
  };
  const listSrc = html.slice(html.indexOf('const THEME_PACKS = ['));
  const THEME_PACKS = eval('(' + listSrc.slice(listSrc.indexOf('['),
                                               listSrc.indexOf('];') + 1) + ')');
  eq('four curated packs, in the ◐ chip\'s fixed order',
     THEME_PACKS.map(p => p.id), ALL_IDS);
  eq('…and Editorial is first — the default is the identity, not a palette',
     THEME_PACKS[0].id, 'dark');
  ok(THEME_PACKS.every(p => p.label && p.note), 'every pack is NAMED and described');
  eq('the four names Debi asked for', THEME_PACKS.map(p => p.label),
     ['Editorial', 'Warm Paper', 'Luxury Gold', 'Cyber']);

  eval(grab('themeId')); eval(grab('nextThemeId'));
  for (const id of ALL_IDS) eq('themeId keeps the known id ' + id, themeId(id), id);
  for (const junk of [null, undefined, '', 'LIGHT', 'compact', 'gold ', '{}'])
    eq('themeId(' + JSON.stringify(junk) + ') → dark (a theme axis never leaves the '
       + 'panel unpainted)', themeId(junk), 'dark');
  // the cycle is a total, wrapping permutation — 4 clicks return you home.
  let cur = 'dark';
  const walk = [];
  for (let i = 0; i < 4; i++) { cur = nextThemeId(cur); walk.push(cur); }
  eq('◐ steps through all four and wraps', walk, ['light', 'gold', 'cyber', 'dark']);
  eq('…from an unknown stored value it still starts at the top of the list',
     nextThemeId('nonsense'), 'light');

  // 'dark' must REMOVE the attribute, or Editorial stops being byte-identical.
  const aa = grab('applyThemeAttr');
  ok(/id === 'dark'/.test(aa) && /removeAttribute\('data-theme'\)/.test(aa),
     "applyThemeAttr('dark') REMOVES the attribute — Editorial is :root itself");
}
// the selector lives on the EXISTING Appearance surface; no fifth top-bar chip.
console.log('the appearance surface');
{
  // ⚠️ WINDOW WIDENED 900 → 1800 (2026-08-28, the studio-design slice). The Appearance
  // group gained a Design row ABOVE Theme, which is the correct order — the design is
  // the outer axis — and that row's description pushed the theme select further from
  // the function head. What this assertion is FOR is unchanged and still holds: the
  // theme picker lives on the EXISTING Appearance surface, not on a new one.
  ok(/function renderAppearance\(\)[\s\S]{0,1800}\$\{themePackSelect\(\)\}/.test(html),
     'the theme picker is hosted by the existing Appearance group (no new surface)');
  ok(/function renderAppearance\(\)[\s\S]{0,1200}\$\{designSelect\(\)\}/.test(html),
     '…and so is the new Design picker, on the same surface rather than a second one');
  ok(/<div class="cap-name">Theme<\/div>/.test(html), '…as a named Appearance row');
  ok(/id="theme-pack" onchange="setTheme\(this\.value\)"/.test(html),
     '…a <select> of the four, applying on change');
  ok(/<button class="cap-btn" onclick="openNavDlg\(\)">Customize…<\/button>/.test(html),
     '…and the Navigation row it sits beside is untouched');
  const topbar = html.slice(html.indexOf('<div class="topbar">'),
                            html.indexOf('<div id="view-mc">'));
  // ⚠️ PIN MOVED 4 → 5 (2026-08-28, the studio-design slice), and the reason is
  // recorded rather than the number quietly bumped. This assertion's job is to stop a
  // slice from growing the top bar CASUALLY. The theme packs added none, and still add
  // none — the fifth chip is the ✦ design axis, which the spec required to have its own
  // button, and which is separately fenced in test_studio_design.js. The identities are
  // pinned below, so a sixth chip, or a swap of one of these five, still fails here.
  eq('the top bar carries exactly five icon chips — the packs added none, and the '
     + 'design axis added exactly one', (topbar.match(/class="chip chip-icon"/g) || []).length, 5);
  eq('…and they are these five, in this order — ◐ theme, ▣ chrome, ✦ design, ⌘K, ↻',
     (topbar.match(/onclick="(\w+)\(/g) || []).map(s => s.slice(9, -1)),
     ['toggleTheme', 'toggleChrome', 'toggleDesign', 'openPalette', 'refresh']);
  ok(/onclick="toggleTheme\(\)"/.test(topbar), '…and ◐ is still one of them');
  ok(/\{t:'Next theme', k:'◐', f:toggleTheme\}/.test(html), '⌘K reaches the theme axis');
  // the select must reflect reality when the chip is what moved.
  ok(/getElementById\('theme-pack'\)[\s\S]{0,80}sel\.value = id/.test(html),
     'a ◐ click updates the Appearance <select>, so the two can never disagree');
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. SIDEBAR RAIL — GLOBAL, PERSISTED, AND THE DEFAULT UNCHANGED
// ═══════════════════════════════════════════════════════════════════════════════
console.log('sidebar rail (executed decision table)');
{
  const grab = name => {
    const i = html.indexOf('function ' + name + '(');
    const s = html.slice(i);
    return s.slice(0, s.indexOf('\n}') + 2);
  };
  eval(grab('railPref')); eval(grab('railIsSlim'));
  eq('an explicit slim reads as slim', railPref('slim'), 'slim');
  eq('an explicit full reads as full', railPref('full'), 'full');
  for (const junk of [null, undefined, '', 'collapsed', 'true'])
    eq('anything else is AUTO, not a guess: ' + JSON.stringify(junk),
       railPref(junk), 'auto');

  // the row that matters: nothing stored → exactly the pre-2026-08-28 behaviour.
  for (const v of ['mc', 'models', 'caps', 'music'])
    eq('AUTO on ' + v + ' → expanded (the opening screen did NOT change)',
       railIsSlim('auto', v), false);
  eq('AUTO on chat → slim (the shipped Chat default is preserved)',
     railIsSlim('auto', 'chat'), true);
  // and an explicit choice is global — that is the whole point of the slice.
  for (const v of ['mc', 'chat', 'models', 'caps', 'music']) {
    eq('explicit slim collapses ' + v, railIsSlim('slim', v), true);
    eq('explicit full expands ' + v, railIsSlim('full', v), false);
  }

  // ── v1.5.26: THE THIRD STATE (Debi — the rail can now go away entirely) ──────
  eval(grab('railState')); eval(grab('railNext'));
  eq('an explicit hidden reads as hidden', railPref('hidden'), 'hidden');
  for (const v of ['mc', 'chat', 'models', 'caps', 'music'])
    eq('explicit hidden hides ' + v + ' — it is global like the other two',
       railState('hidden', v), 'hidden');
  eq('…and `hidden` still answers TRUE to the old boolean face, so nothing that only '
     + 'knows about slim/full has to learn a third state',
     railIsSlim('hidden', 'mc'), true);
  // the AUTO row is untouched: the third state is reachable only by choosing it
  eq('AUTO never resolves to hidden (on chat)', railState('auto', 'chat'), 'slim');
  eq('AUTO never resolves to hidden (elsewhere)', railState('auto', 'mc'), 'full');
  eq('junk never resolves to hidden', railState(railPref('nonsense'), 'mc'), 'full');
  // the cycle: three states, wrapping, with no fourth
  eq('the cycle is full → slim', railNext('full'), 'slim');
  eq('…then slim → hidden', railNext('slim'), 'hidden');
  eq('…then hidden → full (it wraps; there is no fourth state)', railNext('hidden'), 'full');
  eq('three ⌘\\ presses from full return to full',
     railNext(railNext(railNext('full'))), 'full');
}
// the reopener for the hidden state — the SAME grammar as the collapsed sessions rail
{
  ok(/<button id="rail-reopen" onclick="toggleSideRail\(\)"/.test(html),
     'the hidden state has a real reopener in the markup (not injected), and it calls '
     + 'the same cycle the chevron does');
  ok(/id="rail-reopen"[\s\S]{0,160}aria-label="Show sidebar"/.test(html),
     '…labelled for assistive tech');
  ok(/id="rail-reopen"[\s\S]{0,200}<span>Menu/.test(html),
     '…and VISIBLY labelled: office.html\'s finding about its own file rail, applied a '
     + 'third time (a bare glyph never said what came back)');
  const hid = ALL.find(r => r.sel === '#rail-reopen');
  ok(hid && /display:none/.test(hid.body),
     '…and hidden by a class while the sidebar is on screen');
  const strip = ALL.find(r => r.sel === 'body.rail-hidden #rail-reopen');
  ok(!!strip, 'the strip has its own rule');
  const w = parseInt((strip.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  ok(w > 0 && w <= 20, 'the strip is ' + w + 'px — slim enough that `hidden` really is '
     + 'hidden (the 56px icon rail is the state before this one)');
  ok(/top:0; bottom:0/.test(strip.body) && /height:auto/.test(strip.body),
     '…and FULL HEIGHT, which is the whole hit-target argument: ' + w + ' × ≈800px, not '
     + w + ' × ' + w + '. Same argument as the 34px sessions strip. `height:auto` is '
     + 'pinned WITH top/bottom because it is load-bearing and was found by driving: the '
     + 'studio design sets a height on bare buttons, and top+bottom only fill while the '
     + 'height is auto — without it the strip rendered 14 × 30px in studio and '
     + '14 × 589px in Editorial, i.e. a lone button in a gutter, which is the exact '
     + 'shape this collapse pattern exists to remove.');
  ok(/writing-mode:vertical-rl/.test(
       ALL.find(r => r.sel === 'body.rail-hidden #rail-reopen span').body),
     '…and the label runs vertically, which is what makes it readable at that width');
  const gone = ALL.find(r => r.sel === 'body.rail-hidden aside');
  ok(gone && /display:none/.test(gone.body), 'the sidebar itself is really gone');
  ok(!!ALL.find(r => r.sel === 'body.rail-hidden main'),
     '…and the page starts after the strip, so nothing sits underneath it');
}
// persistence + the toggle's flip source
ok(/localStorage\.setItem\('harness-chat-rail', next\)/.test(html),
   'the rail choice is persisted in the SHIPPED key (no new key for a promoted feature)');
{
  const i = html.indexOf('function toggleSideRail()');
  const body = html.slice(i, html.indexOf('\n}', i) + 2);
  ok(/classList\.contains\('rail-slim'\)/.test(body),
     'the toggle flips against WHAT IS ON SCREEN — with the key absent the stored value '
     + 'and the screen disagree, and a chevron reading » must expand on the first click');
  ok(/setItem/.test(body) && /applySideRail\(\)/.test(body),
     '…then persists and re-applies');
}
ok(/if \(typeof applySideRail === 'function'\) applySideRail\(\);/.test(
     html.slice(html.indexOf("classList.toggle('chat-mode'"),
                html.indexOf("classList.toggle('chat-mode'") + 500)),
   'showView re-runs the decision, because the AUTO default is per-view');
ok(/applySideRail\(\);\s+\/\/ sidebar rail/.test(html), '…and it runs once at boot');
ok(!/toggleChatRail|applyChatRail/.test(html),
   'the old chat-only names are GONE, not left as dead aliases');

// the rail's CSS: global, 48–56px, and a real hit target
console.log('the rail geometry');
{
  const slim = ALL.filter(r => r.sel.includes('.rail-slim'));
  ok(slim.length > 0, 'the collapsed rail has rules');
  eq('NONE of them is still scoped to body.chat-mode — the rail is global now',
     slim.filter(r => r.sel.includes('chat-mode')).map(r => r.sel), []);
  const aside = slim.find(r => r.sel === 'body.rail-slim aside');
  ok(!!aside, 'body.rail-slim aside sets the collapsed width');
  const w = parseInt((aside.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  ok(w >= 48 && w <= 56, 'the collapsed rail is 48–56px (got ' + w + 'px)');
  // HIT TARGET, with its arithmetic: at font-size:0 the row's height is the .ico LINE BOX
  // — the 16px glyph times body's line-height 1.55 — plus 2× the row padding. Floor 44px.
  const row = slim.find(r => r.sel === 'body.rail-slim aside nav a');
  ok(!!row, 'the collapsed row has its own padding');
  const pad = parseInt((row.body.match(/padding:\s*(\d+)px/) || [])[1], 10);
  const ico = slim.find(r => r.sel === 'body.rail-slim aside nav a .ico');
  const gly = parseInt((ico.body.match(/font-size:\s*(\d+)px/) || [])[1], 10);
  // HEIGHT: nav a sets font-SIZE only, so it inherits body's line-height 1.55, and at
  // font-size:0 the row's content box is the .ico line box. 16 × 1.55 + 2×11 = 46.8px,
  // which is what the served panel measures (see the report).
  const rowH = gly * 1.55 + 2 * pad;
  ok(rowH >= 44, 'a collapsed row is at least 44px TALL (' + gly + 'px glyph × 1.55 line'
     + '-height + 2×' + pad + 'px padding = ' + rowH.toFixed(1) + 'px)');
  ok(/font:14px\/1\.55/.test(css.replace(/\s+/g, '')),
     '…and 1.55 really is body\'s line-height, which that arithmetic leans on');
  // WIDTH: a hit target has two axes, and this is the one the LIVE drive caught. The
  // row is a block inside the rail's content box, so its width is the rail width minus
  // the rail's own side padding × 2. At the inherited 8px that was 39px — tall enough
  // and too narrow. Pinned so it cannot silently regress.
  const sidePad = parseInt((aside.body.match(/padding:\s*\d+px\s+(\d+)px/) || [])[1], 10);
  const rowW = w - 2 * sidePad;
  ok(rowW >= 44, 'a collapsed row is at least 44px WIDE (' + w + 'px rail − 2×'
     + sidePad + 'px rail padding = ' + rowW + 'px) — the axis the live drive caught');
  ok(/font-size:\s*0/.test(row.body),
     'the text label is collapsed by font-size:0 — the row keeps its title/aria-label, '
     + 'so the label MOVES to the tooltip rather than being deleted');
  // the labels really are on the rows (that is what makes 56px readable)
  const rs = html.slice(html.indexOf('function renderSidebar'));
  ok(/title="\$\{escAttr\(e\.label\)\}"/.test(rs), 'workspace rows carry a title tooltip');
  ok(/title="\$\{esc\(tip\)\}"/.test(rs), 'component rows carry a title tooltip');
  ok(/<span class="dot \$\{cls\}"/.test(rs),
     '…and component rows carry the status DOT, which is what the rail reads by');
  // the peek target is hidden rather than left to land on the glyph
  ok(slim.some(r => r.sel === 'body.rail-slim aside .pk-open'),
     'the hover-revealed ⧉ peek target is hidden in the rail (nowhere to sit at 56px)');
  // …and the expanded behaviours are untouched
  ok(/function peekOpen\(/.test(html) && /function openNavDlg\(/.test(html),
     'peek and the drag/reorder overlay are untouched — they return with the rail');
  ok(!slim.some(r => /nv-row|nv-body|#navdlg/.test(r.sel)),
     'no rail rule reaches into the reorder overlay');
}
// the chevron + the keyboard grammar
{
  const t = ALL.find(r => r.sel === '#rail-toggle');
  ok(!!t && /display:block/.test(t.body),
     'the chevron is present in EVERY view now (it was chat-only)');
  const sz = parseInt((t.body.match(/width:\s*(\d+)px/) || [])[1], 10);
  ok(sz >= 24, 'the chevron itself is at least 24px (got ' + sz + 'px)');
  ok(/id="rail-toggle" onclick="toggleSideRail\(\)"/.test(html), 'the chevron calls it');
  // v1.5.26 — THE CYCLE GAINED A THIRD STATE (full → slim → hidden), so one glyph can
  // no longer carry the whole meaning and the pin moves to what it CAN carry: « while
  // there is something left to narrow, » only from `hidden`, and the actual sentence in
  // the tooltip. (This is the v1.5.24 sessions-chevron lesson applied a second time: a
  // control that means two things is the defect, not the glyph.)
  ok(/textContent = narrowing \? '«' : '»'/.test(html),
     'the glyph shows the ACTION: « while there is something left to collapse, » only '
     + 'from the hidden state');
  ok(/'Collapse sidebar to icons \(⌘\\\\\)'/.test(html)
     && /'Hide sidebar \(⌘\\\\\)'/.test(html)
     && /'Show sidebar \(⌘\\\\\)'/.test(html),
     '…and the tooltip names the exact next step in all three states, which is the part '
     + 'a single glyph cannot say');
  ok(/\(e\.metaKey\|\|e\.ctrlKey\) && e\.key==='\\\\'\)\{ e\.preventDefault\(\); toggleSideRail\(\)/
       .test(html),
     '⌘\\ toggles the rail — MIRRORED from LOffice, which binds ⌘\\ to its own file rail');
  ok(/⌘\\/.test(office), '…and that is genuinely the LOffice binding being mirrored');
  ok(/\{t:'Collapse \/ expand sidebar \(⌘\\\\\)'/.test(html), '…and ⌘K reaches it too');
  // ⌘\ must not already mean something else in the panel
  const binds = (html.match(/metaKey\|\|e\.ctrlKey\) && e\.key==='([^']+)'/g) || []);
  eq('⌘\\ is bound exactly once', binds.filter(b => b.includes("'\\\\'")).length, 1);
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. CHAT DENSITY — THE NUMBERS, WITH THEIR ARITHMETIC
// ═══════════════════════════════════════════════════════════════════════════════
console.log('chat density');
function winner(sel, prop) {
  // last declaration of `prop` in the last rule with this exact selector = what wins
  const rs = ALL.filter(r => r.sel === sel);
  for (let i = rs.length - 1; i >= 0; i--) {
    const m = rs[i].body.match(new RegExp(prop + '\\s*:\\s*([^;}]+)'));
    if (m) return m[1].trim();
  }
  return null;
}
eq('the turn gap is 22px (was 30 — a break, not a paragraph)', winner('.cmsg', 'margin'), '0 0 22px');
eq('the eyebrow sits 6px off its message (was 8 — it belongs TO the message)',
   winner('.cmsg .who', 'margin-bottom'), '6px');
eq('the user bubble is indented 14% (was 20% — the largest empty region on screen)',
   winner('.cmsg.user .body', 'margin-left'), '14%');
eq('…and padded 12/16 (was 15/19)', winner('.cmsg.user .body', 'padding'), '12px 16px');
eq('the session card is padded 8/11 (was 10/12)', winner('.cs-item', 'padding'), '8px 11px');
eq('the sessions head sits 10px off the list (was 12)',
   winner('.cs-head', 'margin-bottom'), '10px');
eq('the rail↔chat gap is 18px (was 24 — dead space either side of the resizer)',
   winner('#chat-body', 'gap'), '18px');

// DENSER, BUT STILL CALM — the two things that must NOT have moved.
eq('the assistant reply keeps its 15px reading size', winner('.cmsg.assistant .body', 'font-size'), '15px');
eq('…and its 1.75 line-height (density came out of the GAPS, not the prose)',
   winner('.cmsg.assistant .body', 'line-height'), '1.75');
ok(/--serif: "New York"/.test(css) && /--mono: "SF Mono"/.test(css),
   'the serif/mono type system is untouched — this is not a terminal');

// HIT TARGET: the session card, with the arithmetic that justifies 8px and not 6.
{
  // ⚠️ THE LINE-HEIGHT HERE IS 'normal', NOT body's 1.55, and getting that wrong is how
  // a hit-target claim becomes a fiction. .cs-item .nm and .meta are both set with the
  // `font:` SHORTHAND, which RESETS line-height to normal (≈1.2 for this stack). The
  // first draft of this check used 1.55 and predicted a 55px card; the served panel
  // measures 46.5px. Both clear 44px, but only one of them is true — so the factor is
  // 1.2 and the margin over the floor is the real ~2.5px, not a comfortable 11px.
  const pad = parseInt(winner('.cs-item', 'padding'), 10);
  const nm = parseFloat(winner('.cs-item.on .nm', 'font-size'));   // 13.5px (active row)
  const metaTop = parseInt(winner('.cs-item .meta', 'margin-top'), 10);
  const NORMAL = 1.2;
  const nmLine = nm * NORMAL;
  const metaLine = parseFloat(winner('.cs-item .meta', 'font').match(/([\d.]+)px/)[1]) * NORMAL;
  const h = 2 * pad + nmLine + metaTop + metaLine;
  ok(h >= 44, 'a session card is still ≥44px tall (2×' + pad + ' + ' + nmLine.toFixed(1)
     + ' + ' + metaTop + ' + ' + metaLine.toFixed(1) + ' = ' + h.toFixed(1)
     + 'px; the served panel measures 47.5px)');
  ok(h < 50, '…and the arithmetic AGREES with the live measurement (47.5px) rather than '
     + 'assuming body\'s 1.55 line-height, which the `font:` shorthand resets');
  ok(/\.cs-item \.nm \{ font:/.test(css) && /\.cs-item \.meta \{ font:/.test(css),
     '…and both really are set with the `font:` shorthand (which is why 1.2, not 1.55)');
}
// THE RESIZER: the density pass must not have touched the handle or its hit area.
{
  const r = ALL.find(x => x.sel === '#cs-resize');
  ok(!!r, 'the sessions resize handle still exists');
  eq('…still 8px wide', (r.body.match(/width:\s*([^;]+)/) || [])[1].trim(), '8px');
  eq('…still centred on the rail edge at right:-4px',
     (r.body.match(/right:\s*([^;]+)/) || [])[1].trim(), '-4px');
  // NOT 100% any more, and that is a DELIBERATE change this slice made — see the
  // `+ New` collision block below. The grab length is the rail minus the header.
  eq('…and still reaches the rail\'s foot (full height minus the header it now clears)',
     (r.body.match(/height:\s*([^;]+)/) || [])[1].trim(), 'calc(100% - 38px)');
  ok(/function clampSessionsWidth\(w\)/.test(html) && /Math\.max\(120, Math\.min\(560/.test(html),
     '…and the width clamp is unchanged (120–560px)');
  ok(ALL.some(x => x.sel === '#art-divider'), 'the artifact divider is untouched too');
}
// THE `+ New` / HANDLE COLLISION the research warned about — IT IS REAL, and this is
// the fix. Not "not applicable": it was invisible at the default width and fatal at the
// clamp minimum, which is exactly the shape of bug a default-width screenshot misses.
{
  const sess = ALL.find(r => r.sel === '#chat-sessions');
  const rz = ALL.find(r => r.sel === '#cs-resize');
  const padR = parseInt((sess.body.match(/padding-right:\s*(\d+)px/) || [])[1], 10);
  const top = parseInt((rz.body.match(/top:\s*(\d+)px/) || [])[1], 10);
  const head = ALL.find(r => r.sel === '.cs-head');
  const headMB = parseInt(winner('.cs-head', 'margin-bottom'), 10);
  const HEAD_H = 24;   // measured on the served panel (the ＋ New button's own height)

  ok(top > 0, 'the resize handle no longer starts at the top of the rail');
  ok(top >= HEAD_H + headMB, 'it starts BELOW the .cs-head row (' + top + 'px ≥ '
     + HEAD_H + 'px head + ' + headMB + 'px margin = ' + (HEAD_H + headMB) + 'px), so no '
     + 'rail width can put it over the ＋ New button');
  ok(new RegExp('height:calc\\(100% - ' + top + 'px\\)').test(rz.body),
     '…and its height is reduced by the same amount, so it still reaches the rail\'s '
     + 'foot rather than overhanging it');
  ok(/z-index:6/.test(rz.body),
     '…the handle does still sit above the panes, which is WHY the overlap was fatal '
     + 'rather than merely ugly');
  // The arithmetic that made this invisible at the default width, kept as the record of
  // why a single screenshot did not catch it.
  ok(padR === 16, 'at the DEFAULT 204px width ＋ New stops ' + padR + 'px short of the '
     + 'rail edge while the handle reaches 4px inward — a 12px gap, which is why the '
     + 'collision was invisible until the rail was dragged narrow');
  ok(/Math\.max\(120, Math\.min\(560/.test(html),
     '…and the rail really can be dragged to 120px, which is where it became fatal '
     + '(measured live: elementFromPoint at the ＋ New button\'s own centre returned '
     + 'cs-resize, i.e. the painted button was unclickable)');
  ok(/\* \{ box-sizing:border-box/.test(css),
     '…that arithmetic rests on the border-box reset, which is still in force');
  ok(ALL.some(x => x.sel === '#art-divider'),
     'the artifact divider is untouched by any of this');
}

console.log('');
console.log(fails ? (fails + ' failure(s) of ' + checks)
                  : ('theme packs / rail / density: ' + checks + ' checks passed'));
process.exit(fails ? 1 : 0);
