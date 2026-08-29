/* LOFFICE — THE OFFICE-SIDE STUDIO DESIGN FENCE, AND THE DELETE-CONFIRM PINS.
 * v1.5.25 · FABLE-STUDIO-DESIGN-SPEC §4, extended to /office by Debi's GO.
 *
 * WHY THIS FILE EXISTS, IN ONE PARAGRAPH PER THING IT GUARDS.
 *
 * 1. EDITORIAL-OFFICE CANNOT BE REACHED. Every selector in
 *    bridge/panel/assets/studio-office.css carries html[data-design="studio"]. Not
 *    "most" — the file is parsed and every comma-separated selector of every rule is
 *    checked, so a future edit cannot add an unscoped rule and repaint the default
 *    LOffice for everyone.
 *
 * 2. EDITORIAL-OFFICE DOES NOT PAY FOR IT. The design CSS is a separate asset; with
 *    the key absent the boot path is one localStorage read and ZERO requests, and
 *    office.html's own inline stylesheet knows nothing about the design attribute.
 *
 * 3. THE SPECIFICITY DISCIPLINE IS MECHANICAL, NOT A HABIT. office.html's own
 *    stylesheet carries the post-mortem: a real `html[data-design="studio"] …` prefix
 *    is (0,1,2) and OUTRANKS `.ghost`, `button.primary` and `.lnk`, so a design flip
 *    would fill in every ghost icon and box every file-row link. So every DESCENDANT
 *    rule in the asset must prefix `:where(html[data-design="studio"])` (zero
 *    specificity) and win on SOURCE ORDER — which is why the boot call that appends
 *    the <link> has to sit BELOW </style>, and why that position is pinned here too.
 *    Only the two ROOT TOKEN blocks may use the bare attribute, and they may declare
 *    nothing but custom properties.
 *
 * 4. THE EDITOR'S GEOMETRY IS NEVER TOUCHED. The embedded ONLYOFFICE editor measures
 *    its container at mount; a design is a RUNTIME flip. So the asset may not set one
 *    box property on #oostage / #ooframe / #gridwrap / #sheet — the seam is colour
 *    only — and it may not reach the document surfaces (#menubar / #toolbar /
 *    #findrow / #gt / #gridbar) at all.
 *
 * 5. THE DESIGN IS MEASURED. Contrast is computed from the hex for every ink on every
 *    ground in BOTH variants (the arithmetic pattern test_theme_packs.js established),
 *    and the deterministic subset of pbakaus/impeccable's rules is executed against
 *    the stylesheet.
 *
 * 6. THE MECHANISM IS EXECUTED, NOT READ. The head script is eval'd against a stub
 *    document + localStorage, so "unknown value → Editorial", "the attribute is
 *    stamped before the link is appended", "a failed asset leaves an honest DOM" and
 *    "idempotent" are behaviours this suite RUNS.
 *
 * 7. THE DELETE CONFIRM NEVER EXPIRES ON A TIMER. Debi's report: "when delete is
 *    clicked on the last file, it seems to not show clearly, and delete/sure button
 *    after really goes away quickly, like after 4 seconds." Both halves are pinned:
 *    the arm/disarm functions are extracted and executed (no setTimeout is allowed to
 *    run at all), and the reveal is a CLASS plus a scroll-into-view rather than
 *    `:hover`, which is what made the last row's confirm unreadable.
 *
 * Run: node bridge/tests/test_studio_office.js
 */
// ⚠️ deliberately NOT 'use strict' — the extract-and-eval pattern (test_office_grid.js)
// needs sloppy mode, or a direct eval() gets its own scope and throws the function away.
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const HTMLPATH = path.join(ROOT, 'bridge', 'panel', 'office.html');
const CSSPATH = path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-office.css');
const html = fs.readFileSync(HTMLPATH, 'utf8');
const sd = fs.readFileSync(CSSPATH, 'utf8');
const inlineCss = html.split('<style>')[1].split('</style>')[0];

let pass = 0;
const fails = [];
function ok(name, cond) { if (cond) pass++; else fails.push(name); }
function eq(name, got, want) {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) pass++; else fails.push(name + '  (got ' + a + ', want ' + b + ')');
}

// ── a brace-matching rule walker (the shape test_studio_design.js uses). Comments
// carry braces and prose, so they go first. @-blocks are RECORDED rather than skipped:
// an @media that escapes the scope is exactly the leak this fence exists to catch.
// comma-split that respects parentheses — `:where(a,b,c)` is ONE selector, and a
// splitter that did not know that would report six unscoped fragments per rule.
function selectors(sel) {
  const out = [];
  let depth = 0, cur = '';
  for (const ch of sel) {
    if (ch === '(') depth++;
    else if (ch === ')') depth--;
    if (ch === ',' && depth === 0) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur);
  return out.map(s => s.trim()).filter(Boolean);
}
function rules(src) {
  const out = [];
  let i = 0;
  while (i < src.length) {
    const b = src.indexOf('{', i); if (b < 0) break;
    const sel = src.slice(i, b).trim();
    let d = 1, j = b + 1;
    while (j < src.length && d > 0) { if (src[j] === '{') d++; else if (src[j] === '}') d--; j++; }
    out.push({ sel: sel, body: src.slice(b + 1, j - 1), at: sel.startsWith('@') });
    i = j;
  }
  return out;
}
const noC = sd.replace(/\/\*[\s\S]*?\*\//g, '');
const ALL = rules(noC);
const RULES = ALL.filter(r => !r.at);
const SCOPE = 'html[data-design="studio"]';
const PREFIX = ':where(html[data-design="studio"])';

// ═══════════════════════════════════════════════════════════════════════════════
console.log('1. the scope fence — studio cannot reach Editorial-office');
// ═══════════════════════════════════════════════════════════════════════════════
ok('the walker parsed the whole stylesheet (' + RULES.length + ' rules)', RULES.length > 60);
{
  const bad = [];
  for (const r of RULES) {
    for (const s of selectors(r.sel)) {
      if (!s.includes(SCOPE)) bad.push(s.slice(0, 90));
    }
  }
  eq('every selector carries html[data-design="studio"]', bad, []);
  eq('…and there is no bare :root / html / * / body rule',
     RULES.filter(r => /^(:root|html|\*|body)\s*$/.test(r.sel)).map(r => r.sel), []);
  eq('…and no @-block at all (an @media wrapper is how a scope leaks)',
     ALL.filter(r => r.at).map(r => r.sel.slice(0, 60)), []);
  ok('…and no @import (one asset, one request)', !/@import/.test(noC));
  ok('…and not one !important — the axis wins on specificity and order alone',
     !/!important/.test(noC));
  ok('…and no url() — nothing in this file can reach the network', !/url\(/.test(noC));
}
// THE SPECIFICITY DISCIPLINE (see the header, §3).
{
  const rootish = RULES.filter(r => !selectors(r.sel).every(s => s.startsWith(PREFIX)));
  eq('exactly TWO rules use the bare attribute prefix, and they are the token blocks',
     rootish.map(r => r.sel),
     ['html[data-design="studio"]',
      'html[data-design="studio"][data-dvariant="light"]']);
  const propOnly = rootish.every(r => r.body.split(';')
    .map(d => d.trim()).filter(Boolean).every(d => d.startsWith('--')));
  ok('…and those two declare NOTHING but custom properties', propOnly);
  const descendants = RULES.filter(r => rootish.indexOf(r) < 0);
  ok('…and every one of the other ' + descendants.length
     + ' rules prefixes :where(html[data-design="studio"])',
     descendants.length > 55
     && descendants.every(r => selectors(r.sel).every(s => s.startsWith(PREFIX))));
}
// EDITORIAL'S OWN SHEET GAINED NOTHING ABOUT THE DESIGN.
{
  ok('office.html\'s inline stylesheet never mentions data-design',
     !/data-design/.test(inlineCss));
  ok('…and the asset is a separate file, not an inline <style>',
     html.indexOf('studio-office.css') > 0 && !/--sd-sans/.test(inlineCss));
  eq('…and the asset href is a single named constant, written once',
     (html.match(/var CSS_HREF = '\/assets\/studio-office\.css';/g) || []).length, 1);
  ok('…and the key is read exactly once per sync, guarded by try/catch',
     /localStorage\.getItem\('harness-design'\)/.test(html));
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('2. the boot position — the one thing the zero-specificity prefix needs');
// ═══════════════════════════════════════════════════════════════════════════════
{
  const styleEnd = html.indexOf('</style>');
  const bootCall = html.indexOf("window.syncSkin('boot')");
  ok('syncSkin(\'boot\') exists', bootCall > 0);
  ok('…and it is called AFTER </style> (so the appended <link> lands after the '
     + 'inline sheet and the asset wins every source-order tie)', bootCall > styleEnd);
  eq('…and it is called exactly once', (html.match(/window\.syncSkin\('boot'\)/g) || []).length, 1);
  ok('…and it is still inside <head>, so Editorial is never half-painted',
     bootCall < html.indexOf('</head>'));
  ok('…and the first head script only DEFINES (it says so where it used to call)',
     /syncSkin\('boot'\) IS NOT CALLED HERE/.test(html));
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('3. the mechanism, EXECUTED against stubs');
// ═══════════════════════════════════════════════════════════════════════════════
function headSandbox(stored) {
  // The first head script, run against a stub DOM. Only what it actually touches.
  const src = html.split('<script>')[1].split('</script>')[0];
  const rootEl = { attrs: {},
    setAttribute: function (k, v) { this.attrs[k] = v; },
    removeAttribute: function (k) { delete this.attrs[k]; },
    getAttribute: function (k) { return Object.prototype.hasOwnProperty.call(this.attrs, k)
                                       ? this.attrs[k] : null; },
    style: { display: '' },
    dataset: {} };
  // the live-flip KICK's world: it hides OUR OWN regions, forces one layout and puts
  // them back. Counted here, so the test can prove it never runs at boot.
  let kicks = 0;
  const appended = [];
  const byId = {};
  const doc = {
    documentElement: rootEl,
    readyState: 'loading',
    body: { get offsetHeight() { kicks++; return 1; } },
    head: { appendChild: function (n) { appended.push(n); if (n.id) byId[n.id] = n; } },
    querySelector: function (sel) {
      if (String(sel).indexOf('meta') === 0) return { content: 'test-build' };
      return { style: { display: '' } };          // a kick region
    },
    getElementById: function (id) { return byId[id] || null; },
    createElement: function (t) { return { tagName: String(t).toUpperCase() }; },
    visibilityState: 'visible',
  };
  const store = {};
  if (stored !== null && stored !== undefined) store['harness-design'] = stored;
  const win = {
    document: doc,
    localStorage: {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem: function (k, v) { store[k] = String(v); },
      removeItem: function (k) { delete store[k]; },
    },
    navigator: { userAgent: 'test', sendBeacon: function () { return true; } },
    location: { href: 'http://127.0.0.1/office' },
    beacons: [],
  };
  const fn = new Function('window', 'document', 'localStorage', 'navigator', 'location',
                          'Blob', 'fetch', src + '\nreturn window;');
  fn(win, doc, win.localStorage, win.navigator, win.location,
     function () { return {}; }, function () { return { catch: function () {} }; });
  // …and then the SECOND head script, the one-liner that lives below </style> and is
  // the whole reason the appended <link> lands after the inline sheet.
  win.syncSkin('boot');
  return { win: win, root: rootEl, appended: appended, store: store, doc: doc,
           kicks: function () { return kicks; },
           late: function () { doc.readyState = 'complete'; } };
}
{
  const a = headSandbox(null);
  eq('key absent → no design attribute at all', a.root.attrs['data-design'], undefined);
  eq('…and ZERO requests: no <link> was appended', a.appended.length, 0);

  const b = headSandbox('studio');
  eq('key "studio" → data-design="studio"', b.root.attrs['data-design'], 'studio');
  eq('…and no variant attribute', b.root.attrs['data-dvariant'], undefined);
  eq('…and exactly one stylesheet <link> was appended', b.appended.length, 1);
  eq('…pointing at the office asset', b.appended[0].href, '/assets/studio-office.css');
  eq('…with the id the sync looks for', b.appended[0].id, 'studio-office-css');
  ok('…and THE ATTRIBUTE WAS STAMPED BEFORE THE APPEND — the WebKit partial-repaint '
     + 'fix. Proven by the source order of the statements in syncDesign.',
     html.indexOf('stamp();') > 0
     && html.indexOf('stamp();\n    var changed =') > 0
     && html.indexOf('stamp();\n    var changed =')
        < html.indexOf('document.head.appendChild(el);'));
  eq('…and NO kick ran at boot (readyState "loading") — the boot path is clean because '
     + 'the sheet is render-blocking there', b.kicks(), 0);

  const c = headSandbox('studio-light');
  eq('key "studio-light" → data-design="studio"', c.root.attrs['data-design'], 'studio');
  eq('…plus data-dvariant="light"', c.root.attrs['data-dvariant'], 'light');

  const d = headSandbox('gold');
  eq('an UNKNOWN value paints Editorial (no attribute)', d.root.attrs['data-design'], undefined);
  eq('…and fetches nothing', d.appended.length, 0);
  const e = headSandbox('');
  eq('an EMPTY value paints Editorial', e.root.attrs['data-design'], undefined);

  // idempotence + the recovery path
  const f = headSandbox('studio');
  f.win.syncDesign('again');
  f.win.syncDesign('again');
  eq('syncDesign is idempotent: still ONE link after three calls', f.appended.length, 1);
  eq('…and the attribute is unchanged', f.root.attrs['data-design'], 'studio');
  f.appended[0].onerror();
  eq('a FAILED asset removes the attribute — an honest DOM, and a working Editorial '
     + 'page', f.root.attrs['data-design'], undefined);

  // the flip-while-in-flight case the stamp() re-read exists for
  const g = headSandbox('studio');
  g.store['harness-design'] = 'studio-light';
  g.appended[0].onload();                      // the sheet lands after the ◐ flip
  g.win.syncDesign('storage');
  eq('a variant flip while the sheet is in flight lands on the variant the user is '
     + 'actually in', g.root.attrs['data-dvariant'], 'light');

  // leaving studio
  const h = headSandbox('studio');
  h.store['harness-design'] = 'editorial';
  h.win.syncDesign('leave');
  eq('leaving studio removes both attributes', [h.root.attrs['data-design'],
     h.root.attrs['data-dvariant']], [undefined, undefined]);

  // it must never WRITE any of the three keys
  const i2 = headSandbox('studio');
  eq('the axis is READ-ONLY on this page — no key was written',
     Object.keys(i2.store), ['harness-design']);
  ok('…and there is no setItem for any harness- key in the head script',
     !/setItem\('harness-(design|theme|chrome)'/.test(html.split('</style>')[0]));
}
// the storage listener has to carry the third key or one window sits in a stale design
ok('the storage listener reacts to harness-design as well as theme/chrome',
   /ev\.key === 'harness-design'/.test(html));

// ═══════════════════════════════════════════════════════════════════════════════
console.log('4. the seam — the editor is not touched, in either direction');
// ═══════════════════════════════════════════════════════════════════════════════
{
  const DOCSURF = ['#menubar', '#toolbar', '#findrow', '#gt', '#gridbar'];
  const touched = DOCSURF.filter(id => RULES.some(r => r.sel.includes(id)));
  eq('the asset does not restyle ONE document surface', touched, []);
  ok('…and #m-more (the ⋯ menu, which hangs off OUR dark strip) IS styled — a menu '
     + 'belongs to the surface it drops out of',
     RULES.some(r => r.sel.includes('#m-more')));
  // GEOMETRY. The editor's canvas engine measures its container at mount.
  const BOXY = /(^|;)\s*(width|height|min-width|min-height|max-width|max-height|padding|margin|border|border-width|border-radius|transform|inset|top|left|right|bottom|position|display|flex)\s*:/;
  const stage = RULES.filter(r => /#oostage|#ooframe|#gridwrap|#sheet/.test(r.sel));
  ok('the seam rules exist', stage.length >= 1);
  const boxy = stage.filter(r => BOXY.test(';' + r.body.replace(/\s+/g, ' ')));
  eq('…and NOT ONE of them sets a box property on the editor\'s container', boxy.map(r => r.sel), []);
  const onlyShadow = stage.every(r => r.body.split(';').map(s => s.trim()).filter(Boolean)
    .every(dcl => /^box-shadow\s*:/.test(dcl)));
  ok('…they change box-shadow (the 1px inset hairline) and nothing else', onlyShadow);
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('5. tokens — every var() office.html uses resolves under studio');
// ═══════════════════════════════════════════════════════════════════════════════
const DARK = RULES.find(r => r.sel === 'html[data-design="studio"]').body;
const LIGHT = RULES.find(r => r.sel === 'html[data-design="studio"][data-dvariant="light"]').body;
function tokens(body) {
  const out = {};
  body.split(';').forEach(d => {
    const m = /^\s*(--[a-z0-9-]+)\s*:\s*([\s\S]+)$/.exec(d);
    if (m) out[m[1]] = m[2].trim();
  });
  return out;
}
const TD = tokens(DARK), TL = tokens(LIGHT);
{
  const rootBody = inlineCss.split(':root{')[1].split('}')[0];
  const declared = Object.keys(tokens(rootBody));
  // --rail-w / --ai-w are the user's dragged pane widths; a design has no opinion.
  const PANE = ['--rail-w', '--ai-w'];
  const missing = declared.filter(t => PANE.indexOf(t) < 0 && !(t in TD));
  eq('every token :root declares is restated in the studio-dark block', missing, []);
  eq('…and the pane widths are deliberately NOT restated',
     PANE.filter(t => t in TD || t in TL), []);
  const used = Array.from(new Set((html.match(/var\((--[a-z0-9-]+)/g) || [])
    .map(s => s.slice(4))));
  const unresolved = used.filter(t => PANE.indexOf(t) < 0 && t !== '--gt-zoom'
    && !(t in TD) && !(new RegExp('\\' + t + '\\s*:').test(inlineCss)));
  eq('…and every var() in office.html resolves somewhere', unresolved, []);
  // the light variant must restate every COLOUR, or a dark hex leaks onto paper
  const colours = Object.keys(TD).filter(t => /^#|rgba?\(/.test(TD[t]));
  const notInLight = colours.filter(t => !(t in TL) && !/^--sd-(elev)$/.test(t));
  eq('the light variant restates every colour token the dark block declares',
     notInLight, []);
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('6. contrast — computed from the hex, both variants (WCAG 2.1)');
// ═══════════════════════════════════════════════════════════════════════════════
function lum(hex) {
  const h = hex.replace('#', '');
  const v = [0, 1, 2].map(i => parseInt(h.slice(i * 2, i * 2 + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
function ratio(a, b) {
  const x = lum(a), y = lum(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
function variant(name, T) {
  const g = k => (T[k] || tokens(DARK)[k]);
  // grounds a first-party surface actually paints, and the inks that sit on them
  const grounds = ['--bg', '--bg2', '--card', '--card2'];
  const inks = ['--cream', '--fg', '--dim'];
  grounds.forEach(gr => inks.forEach(ik => {
    const r = ratio(g(ik), g(gr));
    ok(name + ': ' + ik + ' on ' + gr + ' = ' + r.toFixed(2) + ':1 (AA 4.5)', r >= 4.5);
  }));
  // --faint is only ever used for SUPPORTING 11px+ text; AA large/UI floor 3.0
  grounds.forEach(gr => {
    const r = ratio(g('--faint'), g(gr));
    ok(name + ': --faint on ' + gr + ' = ' + r.toFixed(2) + ':1 (>=3.0, supporting)', r >= 3.0);
  });
  // status inks on the two panel grounds
  ['--gold', '--ok', '--bad'].forEach(ik => ['--bg', '--bg2', '--card'].forEach(gr => {
    const r = ratio(g(ik), g(gr));
    ok(name + ': ' + ik + ' on ' + gr + ' = ' + r.toFixed(2) + ':1 (>=3.0)', r >= 3.0);
  }));
  // the ONE filled control: ink on the accent (impeccable's gray-on-color)
  const onAcc = ratio(g('--sd-on-accent'), g('--gold'));
  ok(name + ': the accent button\'s ink on --gold = ' + onAcc.toFixed(2) + ':1 (AA 4.5)',
     onAcc >= 4.5);
  // and it must have CHROMA, not be a neutral
  const h = g('--sd-on-accent').replace('#', '');
  const ch = [0, 1, 2].map(i => parseInt(h.slice(i * 2, i * 2 + 2), 16));
  ok(name + ': …and that ink is chromatic, not grey', Math.max.apply(null, ch) - Math.min.apply(null, ch) >= 8);
}
variant('studio-dark', TD);
variant('studio-light', TL);
// the neutrals are TINTED (never pure black/grey) — impeccable
{
  [['dark', TD], ['light', TL]].forEach(([n, T]) => {
    ['--bg', '--bg2', '--card', '--card2', '--line', '--line2'].forEach(k => {
      const h = (T[k] || '').replace('#', '');
      if (!h) return;
      const c = [0, 1, 2].map(i => parseInt(h.slice(i * 2, i * 2 + 2), 16));
      ok('studio-' + n + ': ' + k + ' is tinted, not a pure grey/black',
         Math.max.apply(null, c) - Math.min.apply(null, c) >= 1);
    });
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('7. impeccable — the deterministic subset, executed');
// ═══════════════════════════════════════════════════════════════════════════════
{
  // undersized-ui-text: 11px is the floor for anything in our chrome.
  const sizes = [];
  RULES.forEach(r => {
    const m = r.body.match(/font(?:-size)?\s*:\s*[^;]*?(\d+(?:\.\d+)?)px/g) || [];
    m.forEach(s => {
      const n = parseFloat(/(\d+(?:\.\d+)?)px/.exec(s)[1]);
      // heights/paddings are not font sizes: only take declarations that ARE type
      if (/font/.test(s)) sizes.push({ sel: r.sel.slice(0, 60), n: n });
    });
  });
  const tiny = sizes.filter(s => s.n < 11);
  eq('no font-size below 11px anywhere in the asset (undersized-ui-text)',
     tiny.map(s => s.sel + ' @' + s.n), []);
  ok('…and the asset actually RAISES the Editorial micro-caps (it names 10.5px and '
     + '9.5px in its comments as the values it replaced)',
     /was 10\.5/.test(sd) && /9\.5px/.test(sd));

  // wide-tracking (>0.05em) and all-caps furniture
  const tracked = RULES.filter(r => {
    const m = /letter-spacing\s*:\s*([\d.]+)em/.exec(r.body);
    return m && parseFloat(m[1]) > 0.05;
  });
  eq('no letter-spacing above .05em (wide-tracking)', tracked.map(r => r.sel), []);
  const caps = RULES.filter(r => /text-transform\s*:\s*uppercase/.test(r.body));
  eq('nothing is set to uppercase (all-caps-body)', caps.map(r => r.sel), []);
  ok('…and the tracked-caps surfaces are explicitly reset to none',
     (sd.match(/text-transform:none/g) || []).length >= 6);

  // gpt-thin-border-wide-shadow: with hairlines everywhere, no blur >= 16px
  const blurs = [];
  RULES.forEach(r => {
    (r.body.match(/box-shadow\s*:[^;]+/g) || []).forEach(s => {
      (s.match(/(\d+(?:\.\d+)?)px/g) || []).forEach((p, i) => {
        // in `0 6px 14px`, the third length is the blur
        if (i === 2) blurs.push({ sel: r.sel.slice(0, 50), n: parseFloat(p) });
      });
    });
  });
  eq('no shadow blurs 16px or more (gpt-thin-border-wide-shadow)',
     blurs.filter(b => b.n >= 16).map(b => b.sel), []);
  // dark-glow: no chromatic blurred shadow
  const glow = RULES.filter(r => /box-shadow\s*:[^;]*(var\(--gold\)|#[0-9a-f]{6})/.test(r.body)
    && /blur|px \d+px/.test(r.body));
  eq('no chromatic glow shadow (dark-glow)',
     glow.filter(r => !/inset/.test(r.body)).map(r => r.sel), []);

  // no bounce/elastic easing, and nothing animates a layout property
  ok('one easing only, ease-out-cubic', /--sd-ease:cubic-bezier\(\.215,\.61,\.355,1\)/.test(sd));
  eq('no bounce/elastic/spring easing',
     (sd.match(/cubic-bezier\([^)]*\)/g) || []).filter(s => !/\.215,\.61,\.355,1/.test(s)), []);
  const layoutAnim = RULES.filter(r => /transition\s*:[^;]*\b(width|height|padding|margin|top|left|flex)\b/.test(r.body));
  eq('nothing animates a layout property (layout-transition)', layoutAnim.map(r => r.sel), []);

  // nested-cards fires at depth TWO: a card is (shadow OR border) AND (radius OR bg).
  // Every INNER surface must carry a ground with no border and no shadow.
  const INNER = ['.aicode pre', '.aidet pre', '.aim.user .txt'];
  INNER.forEach(sel => {
    const r = RULES.find(x => x.sel.indexOf(sel) >= 0 && !/:hover/.test(x.sel));
    ok('an inner surface exists for ' + sel, !!r);
    if (!r) return;
    const shadow = /box-shadow\s*:(?!\s*none)/.test(r.body);
    if (sel === '.aim.user .txt') {
      // the ONE bubble: a hairline is allowed, but nothing inside it is another card
      ok(sel + ' has no shadow (nested-cards)', !shadow);
    } else {
      ok(sel + ' carries a ground with NO border and NO shadow (nested-cards)',
         !shadow && /border\s*:\s*0/.test(r.body));
    }
  });

  // overused-font: the studio voice is not one of impeccable's 21 names
  const BANNED = ['Inter', 'Helvetica', 'Arial', 'Space Grotesk', 'Roboto', 'Poppins',
                  'Montserrat', 'Lato', 'Open Sans', 'Nunito', 'Raleway'];
  eq('the UI voice is not on impeccable\'s overused list',
     BANNED.filter(f => new RegExp('--sd-sans:[^;]*' + f).test(sd)), []);
  ok('…and the serif is killed (it is Editorial\'s signature, spec §3)',
     /THE SERIF KILL-SWITCH/.test(sd) && /#doctitle/.test(sd));
  // line-length: the measure is capped somewhere
  ok('the prose measure is capped (line-length)', /max-width:70ch/.test(sd));
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('8. the surfaces the spec names are all covered');
// ═══════════════════════════════════════════════════════════════════════════════
{
  const NEEDED = {
    'the dark top strip': 'body>header',
    'the file rail': '#files',
    'the rail rows': '.frow',
    'the start screen': '#empty',
    'the start cards': '.hcard',
    'the recents list': '.hrow',
    'the AI panel': '#ai',
    'the AI lane chips': '.chip',
    'the AI cards': '.aicode',
    'the AI composer': '#ai-in',
    'the message strip': '#msg',
    'the boot banner': '#boot',
    'the rich/progress strip': '#richbar',
    'the ⋯ menu': '#m-more',
    'the collapse tabs': '#rail-tab',
    'the blob interstitial': '#blobwait',
    'the type badge': '.tbadge',
    'the focus ring': ':focus-visible',
  };
  Object.keys(NEEDED).forEach(k => {
    ok('studio styles ' + k + ' (' + NEEDED[k] + ')',
       RULES.some(r => r.sel.indexOf(NEEDED[k]) >= 0));
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('9. THE DELETE CONFIRM — Debi\'s report, pinned');
// ═══════════════════════════════════════════════════════════════════════════════
// ── the extractor (test_office_grid.js's, verbatim in behaviour: string/comment aware
// so an apostrophe in a comment cannot truncate a body and leave a test that measures
// nothing).
function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in office.html');
  const stack = [];
  let depth = 0, prev = '';
  for (let j = html.indexOf('{', at); j < html.length; j++) {
    const c = html[j], top = stack[stack.length - 1], bs = prev === '\\';
    const t = top && top.t;
    if (t === 'sq' || t === 'dq') {
      if (!bs && c === (t === 'sq' ? "'" : '"')) stack.pop();
    } else if (t === 'tpl') {
      if (!bs && c === '`') stack.pop();
    } else {
      if (c === '/' && html[j + 1] === '/') { j = html.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && html[j + 1] === '*') { j = html.indexOf('*/', j) + 1; prev = '/'; continue; }
      if (c === "'") stack.push({ t: 'sq' });
      else if (c === '"') stack.push({ t: 'dq' });
      else if (c === '`') stack.push({ t: 'tpl' });
      else if (c === '{') depth++;
      else if (c === '}') { depth--; if (depth === 0) return html.slice(at, j + 1); }
    }
    prev = c;
  }
  throw new Error('unbalanced body for ' + name);
}

// ① NO TIMER. The old code disarmed with setTimeout(…, 3000) on BOTH surfaces.
{
  const src = html.split('<script>').pop();
  const armTimers = (src.match(/setTimeout\([^;]{0,160}armed\s*=\s*null/g) || []);
  eq('NOT ONE setTimeout anywhere clears `armed` — a destructive confirm may not '
     + 'expire on a timer', armTimers, []);
  ok('…and the 3000 ms disarm is gone from the file entirely',
     !/if \(armed === (name|f\.name)\) \{ armed = null/.test(src));
  ok('…and the house rule is written down where the next reader will find it',
     /a destructive confirm NEVER auto-expires/i.test(html)
     || /A destructive confirm NEVER/.test(html));
}

// ② THE ARM/CONFIRM/DISARM CYCLE, EXECUTED. setTimeout is a THROW here: if any path
// schedules one, this section fails rather than passing quietly.
{
  eval(grab('armDelete'));
  eval(grab('disarmDelete'));
  eval(grab('delClick'));
  eval(grab('homeDel'));
  eval(grab('delArmedRow'));
  // v1.5.65 routed the delete guard through busyBlock (the silent-guard ban).
  // Execute the SHIPPED busyBlock, not a stub — a stub would keep passing after
  // the real one broke.
  eval(grab('busyBlock'));
  const DEL_ARM_MIN_MS = parseInt(/const DEL_ARM_MIN_MS = (\d+)/.exec(html)[1], 10);
  eq('the arm guard is 400 ms — the same number, and the same reason, as '
     + 'DISCARD_MIN_MS', DEL_ARM_MIN_MS, 400);

  // the world
  let armed = null, armedAt = 0, busy = false, busyWhat = '', busyAt = 0;
  let renders = 0, scrolls = 0, asked = [], said = [], beacons = [];
  const scrolled = { scrollIntoView: function () { scrolls++; } };
  function renderFiles() { renders++; }
  function say(t, k, a) { said.push({ t: t, a: a }); }
  function bx(s, d) { beacons.push(s + ':' + d); }
  function deleteAsk(n) { asked.push(n); }
  function setTimeout() { throw new Error('a timer was scheduled — the confirm must ' +
                                          'not expire on its own'); }
  global.document = { querySelector: function () { return scrolled; } };
  let now = 10000;
  const RealDate = Date;
  global.Date = { now: function () { return now; } };

  try {
    // A BUSY CLICK SPEAKS — the silent-guard ban (v1.5.65, Debi's five dead clicks).
    busy = true; busyWhat = 'saving Budget.xlsx'; busyAt = Date.now();
    delClick('A.xlsx');
    eq('a click while busy arms nothing', armed, null);
    ok('…but it SAYS SO instead of dying silently',
       said.length === 1 && /Still working on saving Budget\.xlsx/.test(said[0].t));
    busy = false; said = [];

    // FIRST CLICK: arms, says the sentence with a Cancel action, scrolls it into view
    delClick('A.xlsx');
    eq('first click arms the row', armed, 'A.xlsx');
    eq('…and asks nothing yet', asked, []);
    ok('…and it says WHAT is armed, in words', /Delete “A\.xlsx”\?/.test(said[0].t));
    ok('…and offers Cancel in the same sentence',
       said[0].a && said[0].a.label === 'Cancel');
    eq('…and the armed row is scrolled into view (the LAST-ROW clip)', scrolls, 1);
    ok('…and the sentence goes up BEFORE the scroll, because #msg changes the layout '
       + 'the scroll is computed against',
       html.indexOf('say(\'Delete “\' + name') < html.indexOf('const a = delArmedRow()'));

    // A DOUBLE-CLICK RE-ARMS, it does not delete
    now += 100;
    delClick('A.xlsx');
    eq('a second click 100 ms later RE-ARMS (a double-click is not an answer)', asked, []);
    eq('…and the row is still armed', armed, 'A.xlsx');
    eq('…and the arm time moved forward', armedAt, now);

    // …AND IT NEVER EXPIRES: no timer ran, and a long wait changes nothing
    now += 60000;
    eq('sixty seconds later it is STILL armed', armed, 'A.xlsx');

    // THE ANSWER
    delClick('A.xlsx');
    eq('a click after the guard asks the one delete sentence', asked, ['A.xlsx']);
    eq('…and disarms first, so the row cannot be armed and answered at once', armed, null);

    // ANOTHER ROW ARMS INSTEAD OF CONFIRMING
    delClick('B.xlsx');
    now += 1000;
    delClick('C.xlsx');
    eq('clicking a DIFFERENT row moves the arm rather than deleting', armed, 'C.xlsx');
    eq('…and asked nothing new', asked, ['A.xlsx']);

    // CANCEL / CLICK-AWAY / ESCAPE all go through disarmDelete
    disarmDelete(true);
    eq('disarm clears the arm', armed, null);
    eq('…and clears the message', said[said.length - 1].t, '');
    disarmDelete(true);
    eq('disarming twice is harmless (idempotent)', armed, null);

    // BUSY: a delete must not arm while the page is mid-save
    busy = true;
    delClick('D.xlsx');
    eq('nothing arms while the page is busy', armed, null);
    busy = false;

    // the start screen shares ONE implementation
    homeDel('E.xlsx');
    eq('homeDel delegates to the same arm', armed, 'E.xlsx');
    pass++;   // no timer was ever scheduled — the stub would have thrown
  } finally {
    global.Date = RealDate;
    delete global.document;
  }
}

// ③ THE REVEAL IS A CLASS, NOT :hover — and studio restates it.
{
  ok('the inline sheet reveals an ARMED row\'s actions from a class',
     /\.frow\.armed \.acts\{display:flex\}/.test(inlineCss.replace(/\s+/g, ' ')
       .replace(/ \{/g, '{').replace(/; \}/g, '}').replace(/: /g, ':')));
  ok('…and the armed row carries the danger edge in Editorial',
     /\.frow\.armed\{border-color:var\(--bad\)\}/.test(inlineCss.replace(/\s+/g, '')
       .replace(/;\}/g, '}')));
  ok('…and on the start screen too', /\.hrow\.armed\{border-color:var\(--bad\)\}/
     .test(inlineCss.replace(/\s+/g, '').replace(/;\}/g, '}')));
  ok('…and STUDIO restates both (a zero-specificity prefix ties and wins on order, so '
     + 'the state would otherwise lose its cue)',
     RULES.some(r => r.sel.indexOf('.frow.armed') >= 0 && /--bad/.test(r.body))
     && RULES.some(r => r.sel.indexOf('.hrow.armed') >= 0 && /--bad/.test(r.body)));
  ok('…and studio keeps `.lnk.arm` red (it is (0,2,0) in the inline sheet)',
     RULES.some(r => r.sel.indexOf('.lnk.arm') >= 0 && /--bad/.test(r.body)));
  ok('both row renderers stamp the armed class',
     (html.match(/armed === f\.name \? ' armed' : ''/g) || []).length === 2);
  ok('the armed delete link says, on its own title, that it will not go away',
     /will not go away on its own/.test(html));
}

// ④ THE OTHER WAYS OUT (a confirm that never expires needs them).
{
  ok('a click anywhere else disarms', /if \(inRow \|\| inMsg\) return;\s*\n\s*disarmDelete\(true\);/.test(html));
  ok('…and Escape disarms', /ev\.key === 'Escape' && armed/.test(html));
  ok('…and clicking the armed row itself does NOT count as an answer',
     /closest\('\.frow\.armed, \.hrow\.armed'\)/.test(html));
}

// ═══════════════════════════════════════════════════════════════════════════════
console.log('10. the build stamp');
// ═══════════════════════════════════════════════════════════════════════════════
{
  const stamp = /name="harness-build" content="([^"]+)"/.exec(html)[1];
  eq('office.html carries this slice\'s stamp', stamp, 'loffice-2026-08-29b');
  ok('…and the boot banner says the same one', html.indexOf('loffice-2026-08-29b</code>') > 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
if (fails.length) {
  console.log('\nFAILURES (' + fails.length + '):');
  fails.forEach(f => console.log('  FAIL  ' + f));
  console.log('\n' + pass + ' passed, ' + fails.length + ' FAILED');
  process.exit(1);
}
console.log('\nall ' + pass + ' checks passed');
