/* NAV — the PANEL half (FABLE-STUDIO-PHASE2-SPEC §A, 2026-08-21).
 *
 * bridge/tests/test_nav_model.py owns the authority (bridge/nav.py) and the fact that
 * the two id sets agree. This file owns the panel: the pure model functions are
 * EXTRACTED FROM THE SHIPPED SOURCE and executed, so the panel's mirror of the rules is
 * proved to behave the same way rather than merely to exist; the rest is wiring.
 *
 * The load-bearing questions:
 *   • does a machine with NO saved layout render exactly today's sidebar? (Debi's rule:
 *     nothing moves until somebody customises it — plus the two lanes that had no row.)
 *   • can a customisation make something unreachable? (it must not)
 *   • is the 13th pin refused with the limit named? (Debi's ruling)
 *
 * Run: node bridge/tests/test_nav_panel.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const swift = fs.readFileSync(path.join(ROOT, 'app', 'main.swift'), 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

// ── extract + execute the pure half ─────────────────────────────────────────
const start = html.indexOf('const NAV_ENTRIES = [');
const end = html.indexOf('let navModel = null;');
ok(start > 0 && end > start, 'the nav model block is where the test expects it');
const src = html.slice(start, end);
const M = new Function(src + `; return { NAV_ENTRIES, NAV_TOPBAR_MAX, NAV_SIDEBAR_ONLY,
  NAV_DEFAULT_SIDEBAR, NAV_DEFAULT_TOPBAR, NAV_TOPBAR_UNPINNED, NAV_ALWAYS,
  NAV_MODEL_V, NAV_DEFAULT_TOPBAR_V1,
  navEntry, navCanShow, navDefaultModel, navNormalize, navValidate, navMigrate };`)();
const ids = (m, bar) => m[bar].map(r => r.id);

// ── 1. the registry ─────────────────────────────────────────────────────────
console.log('registry');
{
  const seen = {};
  M.NAV_ENTRIES.forEach(e => { ok(!seen[e.id], 'no duplicate id: ' + e.id); seen[e.id] = 1; });
  // Debi's amendment: the two newest LANES are registry entries — that is precisely how
  // they become reachable from the sidebar (they are lanes, not services, so they have
  // no Mission Control card and were previously reachable only from the tab strip).
  for (const id of ['aider', 'loffice', 'goose', 'comfy']) {
    const e = M.navEntry(id);
    ok(e && e.kind === 'lane', id + ' is a registry LANE');
    ok(e && e.prefersTab === true, '...and a click on it asks the shell for its tab');
    ok(e && typeof e.url === 'string' && e.url.startsWith('/'),
       '...with a page URL, so a plain browser is not left with a dead row');
    ok(e && !e.view, '...and no in-panel view (it does not have one)');
  }
  ok(M.navEntry('loffice').tab === 'LOffice' && M.navEntry('aider').tab === 'Aider',
     'the lane tab titles are the shell\'s, spelled exactly');
  // THE COMFY PAIR (comfy-nav slice). Two entries, two real surfaces — `comfy` is OUR
  // /comfy generate page and `comfyui` is upstream's stock UI on :8188. This is written
  // down because the obvious "cleanup" is to collapse them, and either collapse silently
  // removes a surface the user has: no stock UI, or no navigation to Generate at all.
  {
    const g = M.navEntry('comfy'), c = M.navEntry('comfyui');
    ok(g && c, 'both comfy entries exist');
    ok(g.kind === 'lane' && c.kind === 'component', 'comfy is our LANE, comfyui THE component');
    ok(g.label === 'Generate' && g.tab === 'Generate' && g.url === '/comfy',
       'the Generate row is labelled for what it does and points at our own page');
    ok(c.label === 'Comfyui' && c.tab === 'ComfyUI',
       '…and the stock ComfyUI entry keeps its own name and its own tab, untouched');
    ok(g.tab !== c.tab, 'they are two different native tabs');
    // The ICON may not be a chrome control's glyph: ✦ is the design-axis toggle in the
    // topbar, and a sidebar row wearing it reads as that control. Caught live.
    ok(g.ico !== '✦', 'the Generate icon is not the design-toggle glyph');
    ok(M.NAV_ENTRIES.filter(e => e.ico && e.ico === g.ico).length === 1,
       '…and no other nav row wears it either');
  }
  // every `tab` the panel names must be a title the shell actually has, or the
  // switchTab bridge silently does nothing.
  const swiftTitles = (swift.match(/HarnessTab\(id: "[^"]+", title: "([^"]+)"/g) || [])
    .map(s => s.replace(/.*title: "/, '').replace('"', ''));
  M.NAV_ENTRIES.filter(e => e.tab).forEach(e => {
    ok(swiftTitles.indexOf(e.tab) >= 0, 'the shell has a tab titled "' + e.tab + '"');
  });
  // …and every id the panel names must be an id the shell has, since the id is what the
  // switchTab bridge now resolves first.
  const swiftIds = (swift.match(/HarnessTab\(id: "([^"]+)"/g) || [])
    .map(s => s.replace('HarnessTab(id: "', '').replace('"', ''));
  M.NAV_ENTRIES.filter(e => e.tab).forEach(e => {
    ok(swiftIds.indexOf(e.id) >= 0, 'the shell knows the id "' + e.id + '"');
  });
  ok(M.navEntry('logs') && !M.navEntry('logs').view && !M.navEntry('logs').tab,
     'Logs is a dialog: no view, no tab');
  ok(M.NAV_SIDEBAR_ONLY.join() === 'logs,help',
     '…and the sidebar-only set is Logs + Help (v1.5.27)');
  // HELP (roadmap §2.4). The entry that broke the old shape of these assertions: it is
  // the first registry entry that is a REAL VIEW and still sidebar-only, so "no tab"
  // can no longer be inferred from "no view".
  {
    const h = M.navEntry('help');
    ok(!!h && h.view === 'help', 'Help is a real panel VIEW (unlike Logs, which is a dialog)');
    ok(!!h && !h.tab, '…with no native tab');
    ok(!!h && !h.prefersTab, '…so a click can never be handed to the shell');
    ok(M.navCanShow('help', 'sidebar') && !M.navCanShow('help', 'topbar'),
       '…and the model refuses to put it on the strip');
    ok(M.NAV_ALWAYS.join() === 'logs,help',
       'the `always` set is a NAMED list, mirroring nav.py (it was an inline id test)');
  }
  ok(!M.navCanShow('logs', 'topbar') && M.navCanShow('logs', 'sidebar'),
     'navCanShow answers the capability question');
  ok(!M.navCanShow('nope', 'sidebar') && !M.navCanShow('nope', 'topbar'),
     'an unknown id can show nowhere');
  ok(M.NAV_ENTRIES.filter(e => e.kind === 'view' && e.view).every(e => e.ico),
     'every workspace row has an icon (the rail renders one per row)');
}

// ── 2. THE FALLBACK: no saved layout looks exactly like today ───────────────
console.log('defaults');
{
  const d = M.navDefaultModel();
  ok(M.navValidate(d) === '', 'the default layout is itself valid');
  // today's hardcoded sidebar was: Mission Control, Chat, Models, Music, Capabilities,
  // Logs — plus the components group. PHASE 2 adds exactly the two lanes Debi asked
  // for, in the workspace group, and moves nothing else.
  const ws = ids(d, 'sidebar').filter(i => M.navEntry(i).kind !== 'component');
  // …and the goose slice adds a THIRD lane, next to aider (its sibling: both are pty
  // lanes in their own tab). Everything else still moves nothing.
  // …and the comfy-nav slice adds a FOURTH, `comfy` (Generate), placed next to MUSIC
  // rather than next to the agent lanes — Music and Generate are MOT Deck's own two
  // generate surfaces (sound, then image/video), so they read as a pair. Still an
  // ADDITION only: no existing row changed position relative to its neighbours.
  ok(ws.join(',') === 'mc,chat,models,music,comfy,aider,goose,loffice,caps,logs,help',
     'the workspace rail is today\'s order + the four lanes + Help under Logs: ' + ws.join(','));
  const comps = ids(d, 'sidebar').filter(i => M.navEntry(i).kind === 'component');
  ok(comps.join(',') === 'odysseus,hermes,voicestudio,voicebox,comfyui,unsloth,opencode',
     'the components group lists every component that has a tab');
  ok(d.sidebar.every(r => r.pinned), 'nothing starts hidden on the sidebar');
  const top = d.topbar.filter(r => r.pinned).map(r => r.id);
  // v1.5.26 — DEBI'S ORDER. Same eleven ids, new reading order (the deck · the three
  // agent/model lanes · everything else). Pinned as a literal on purpose: here the
  // ORDER itself is the requirement, so it may not drift silently.
  ok(top.join(',') === 'mc,hermes,unsloth,opencode,odysseus,voicestudio,comfyui,aider,loffice,music,voicebox',
     'the default strip is exactly the eleven default tabs, in Debi\'s order');
  // ⚠️ WIDENED, NOT WEAKENED, at the goose slice: still a closed literal list, and
  // goose is on it because the strip is at 11 of 12 pins and a new lane must not spend
  // the last one silently. It is one sidebar click (or one ⋯) away.
  // ⚠️ WIDENED AGAIN, STILL NOT WEAKENED, at the comfy-nav slice: `comfy` (Generate)
  // joins for goose's identical argument — the pinned prefix above is STILL eleven, so
  // the last free pin is still free. Closed literal list; order mirrors nav.py's tail.
  ok(d.topbar.filter(r => !r.pinned).map(r => r.id).join(',') === 'chat,models,caps,goose,comfy',
     'the three pinnable VIEWS + goose + comfy start hidden (one sidebar click away)');
  ok(top.length <= M.NAV_TOPBAR_MAX, 'the default strip is inside the pin cap');
}

// ── 3. normalize — TOTALITY, order, and the two fixed rules ─────────────────
console.log('normalize');
{
  const full = M.navDefaultModel();
  for (const junk of [null, undefined, 0, 'x', [], {sidebar: 'x'}, {topbar: 7},
                      {sidebar: [null, 3, [], {}, {id: 5}]},
                      {topbar: ['mc', 'mc', 'mc']},
                      {sidebar: [{id: 'ghost'}], topbar: [{id: 'logs'}]}]) {
    const m = M.navNormalize(junk);
    ok(ids(m, 'sidebar').slice().sort().join() === ids(full, 'sidebar').slice().sort().join(),
       'normalize(' + JSON.stringify(junk) + ') still yields every sidebar entry');
    ok(ids(m, 'topbar').slice().sort().join() === ids(full, 'topbar').slice().sort().join(),
       'normalize(' + JSON.stringify(junk) + ') still yields every strip entry');
  }
  let m = M.navNormalize({ sidebar: [{ id: 'ghost' }, { id: 'chat' }] });
  ok(ids(m, 'sidebar').indexOf('ghost') < 0, 'an unknown id is dropped, never rendered');
  ok(ids(m, 'sidebar')[0] === 'chat', '…and the known ones keep the order given');
  m = M.navNormalize({ topbar: [{ id: 'logs' }, { id: 'odysseus' }] });
  ok(ids(m, 'topbar').indexOf('logs') < 0, 'logs cannot be put on the strip');
  ok(ids(m, 'topbar')[0] === 'mc' && m.topbar[0].pinned,
     'Mission Control is forced FIRST and PINNED on the strip');
  ok(ids(m, 'topbar')[1] === 'odysseus', '…and the rest keep the order given');
  m = M.navNormalize({ sidebar: [{ id: 'chat', pinned: false }] });
  ok(m.sidebar[0].id === 'chat' && m.sidebar[0].pinned,
     'Chat can never be un-pinned from the sidebar');
  m = M.navNormalize({ sidebar: [{ id: 'caps' }, { id: 'models', pinned: false }] });
  ok(ids(m, 'sidebar').slice(0, 2).join() === 'caps,models',
     'a HIDDEN row keeps its place in the order (un-hiding puts it back where it was)');
  ok(m.sidebar[1].pinned === false, '…and stays hidden');
  ok(ids(m, 'sidebar').length === M.NAV_DEFAULT_SIDEBAR.length,
     'every omitted entry is appended, so a new registry row appears for everyone');
  // appending must never invalidate a model that was valid
  const twelve = ['mc','odysseus','hermes','voicestudio','voicebox','comfyui','unsloth',
                  'music','aider','loffice','chat','models'].map(id => ({id, pinned:true}));
  m = M.navNormalize({ topbar: twelve });
  ok(m.topbar.filter(r => r.pinned).length === M.NAV_TOPBAR_MAX,
     'an appended entry is never pinned onto a full strip');
  ok(M.navValidate(m) === '', '…so normalize can never hand back an over-full strip');
  const a = M.navNormalize({ sidebar: [{ id: 'caps' }], topbar: [{ id: 'music' }] });
  ok(JSON.stringify(M.navNormalize(a)) === JSON.stringify(a), 'normalize is a fixed point');
}

// ── 4. validate — the two rules that stop a customisation LOSING something ──
console.log('validate');
{
  let m = M.navNormalize({});
  ok(M.navValidate(m) === '', 'the default model validates');
  ['sidebar', 'topbar'].forEach(b => m[b].forEach(r => { if (r.id === 'models') r.pinned = false; }));
  const err = M.navValidate(m);
  ok(err && /Models/.test(err), 'an entry hidden on BOTH bars is refused, by LABEL: ' + err);
  m = M.navNormalize({});
  m.sidebar.forEach(r => { if (r.id === 'models') r.pinned = false; });
  m.topbar.forEach(r => { if (r.id === 'models') r.pinned = true; });
  ok(M.navValidate(m) === '', 'hidden on one bar and shown on the other is legal');
  m = M.navNormalize({});
  m.sidebar.forEach(r => { if (r.id === 'logs') r.pinned = false; });
  ok(M.navValidate(m) === '', 'logs may be hidden everywhere (⌘K reaches it)');
  // Debi's ruling, both sides of the boundary
  m = M.navNormalize({});
  m.topbar.forEach(r => { r.pinned = true; });
  ok(m.topbar.length > M.NAV_TOPBAR_MAX,
     'the registry offers ' + m.topbar.length + ' strip-able entries, so the cap is reachable');
  const e13 = M.navValidate(m);
  ok(e13 && e13.indexOf(String(M.NAV_TOPBAR_MAX)) >= 0,
     'pinning them all is refused and the message NAMES the limit: ' + e13);
  // Unpin from the END, the same rule navRepair follows, until exactly the cap remains.
  let over = m.topbar.length - M.NAV_TOPBAR_MAX;
  for (let i = m.topbar.length - 1; i >= 0 && over > 0; i--) {
    if (m.topbar[i].pinned) { m.topbar[i].pinned = false; over--; }
  }
  ok(m.topbar.filter(r => r.pinned).length === M.NAV_TOPBAR_MAX, 'exactly the cap is pinned');
  ok(M.navValidate(m) === '', 'exactly 12 is allowed (the boundary is inclusive)');
  ok(M.NAV_TOPBAR_MAX === 12, 'the cap is Debi\'s 12');
}

// ── 5. the sidebar is RENDERED from the model ──────────────────────────────
console.log('sidebar');
{
  ok(/<nav id="sideworkspace"><\/nav>/.test(html) && /<nav id="sidecomponents"><\/nav>/.test(html),
     'both rails are empty containers in the markup — nothing is hardcoded');
  ok(!/id="nav-mc" class="on" onclick/.test(html),
     'the old hardcoded workspace rows are gone');
  const rs = html.slice(html.indexOf('function renderSidebar()'),
                        html.indexOf('function renderSidebar()') + 2600);
  ok(/const ids = navSideIds\(\)/.test(rs), 'it renders the model\'s pinned sidebar ids…');
  ok(/navOpen\('\$\{escAttr\(e\.id\)\}'\)/.test(rs), '…each row going through navOpen');
  ok(/id="nav-\$\{escAttr\(e\.id\)\}"/.test(rs),
     '…keeping the nav-<id> element ids showView and the tour depend on');
  ok(/e\.view === curView/.test(rs), 'the highlighted row survives a re-render');
  ok(/openComponent\('\$\{escAttr\(name\)\}'\)/.test(rs),
     'component rows still go through openComponent (running → its tab)');
  ok(/Object\.keys\(comps\)\.filter\(n => !known\[n\]\)/.test(rs),
     'a component the registry does not know (searxng, runner) is still listed');
  ok(/const cls = \(st === 'starting'/.test(rs), '…with its live status dot, as before');
  // refresh() must not keep a second copy of the component-row renderer
  const refresh = html.slice(html.indexOf('async function refresh(manual)'),
                             html.indexOf('function showProvLog('));
  ok(/renderSidebar\(\);/.test(refresh), 'refresh() redraws the rails through that one renderer');
  ok(!/side\.insertAdjacentHTML/.test(refresh), '…and holds no second copy of the markup');
  ok(/renderSidebar\(\);\s*\/\/ NAV/.test(html) && /navSync\(\);/.test(html),
     'boot draws from the instant copy, then adopts the shared one');
  // showView must tolerate a row the user hid
  const sv = html.slice(html.indexOf('function showView(v)'),
                        html.indexOf('function showView(v)') + 1400);
  ok(/const a = document\.getElementById\('nav-' \+ e\.id\);\s*\n\s*if \(a\)/.test(sv),
     'showView tolerates a MISSING row (hiding one must not throw)');
  ok(/curView = v;/.test(sv), '…and records the current view for the next render');
}

// ── 5b. renderSidebar EXECUTED on the shipped source ───────────────────────
// Greps prove the renderer exists; this proves it RUNS and produces the fallback
// layout — the one thing Debi's rule is actually about ("a fresh install looks like
// the build before this slice"). The DOM is two innerHTML sinks, which is all this
// function touches.
console.log('render (executed)');
{
  // wider than `src`: the render path needs navGet/navModel/navSaveLocal too.
  const srcFull = html.slice(start, html.indexOf('// Kept as its own name'));
  const sideStart = html.indexOf('function navSideIds()');
  const sideEnd = html.indexOf('\n}\n', html.indexOf("const lbl = document.getElementById('sidecomponents-lbl')")) + 3;
  const els = {};
  const doc = { getElementById: (id) => els[id] || (els[id] = { id, innerHTML: '', hidden: false }) };
  const env = {
    document: doc,
    localStorage: { getItem: () => null, setItem: () => {} },
    esc: (s) => String(s), escAttr: (s) => String(s),
    curView: 'chat',
    lastStatus: { components: {
      hermes: { running: true, installed: true },
      odysseus: { running: false, installed: false },
      searxng: { running: false, installed: true },
      runner: { running: true, installed: true } }, prov: {} },
    TAB_FOR_COMPONENT: {},
  };
  // renderSidebar now asks peekEligible() which rows get the ⧉ overlay trigger. The
  // REAL predicate is pulled in (not stubbed) so the render is proved against the same
  // rule the click path uses.
  const peekStart = html.indexOf('const PEEK_VIEWS = [');
  const peekEnd = html.indexOf('function pkFlash(');
  ok(peekStart > 0 && peekEnd > peekStart, 'the peek predicate block is where the test expects it');
  const peekSrc = html.slice(peekStart, peekEnd);
  // renderSidebar's status dot now goes through healthOf(), the ONE health derivation
  // (defined later in the page — hoisting covers the live page, but not this slice).
  // The REAL function is pulled in, not stubbed, for the same reason as the peek block.
  const healthStart = html.indexOf('function healthOf(c)');
  const healthEnd = html.indexOf('\n}\n', healthStart) + 3;
  ok(healthStart > 0 && healthEnd > healthStart, 'the healthOf derivation is where the test expects it');
  const healthSrc = html.slice(healthStart, healthEnd);
  const run = new Function(...Object.keys(env),
    srcFull + peekSrc + healthSrc + html.slice(sideStart, sideEnd) + `
    NAV_ENTRIES.forEach(e => { if (e.kind === 'component' && e.tab) TAB_FOR_COMPONENT[e.id] = e.tab; });
    renderSidebar();
    return { ws: document.getElementById('sideworkspace').innerHTML,
             comp: document.getElementById('sidecomponents').innerHTML };`);
  const out = run(...Object.values(env));
  const rows = [...out.ws.matchAll(/id="nav-([a-z]+)"/g)].map(m => m[1]);
  // ⚠️ WIDENED (not weakened) at the comfy-nav slice, in step with the defaults fence
  // above: this one proves the rail actually RENDERS what the model declares, so the
  // two literals must move together or the Generate row is declared but never drawn.
  ok(rows.join(',') === 'mc,chat,models,music,comfy,aider,goose,loffice,caps,logs,help',
     'with NO saved layout the workspace rail renders today\'s rows + the four lanes + Help');
  ok(rows.indexOf('help') === rows.indexOf('logs') + 1,
     '…and Help is DIRECTLY under Logs, which is where the roadmap put it');
  ok(/id="nav-chat" class="on"/.test(out.ws),
     'the current view is highlighted after a render (curView, not a lost class)');
  ok((out.ws.match(/onclick="navOpen\(/g) || []).length === rows.length,
     'every workspace row is clickable through navOpen');
  ok(/<span class="ico">♫<\/span> Music/.test(out.ws), 'the icons and labels come from the registry');
  // ⧉ = open as an overlay (2026-08-21). It rides the eligible workspace rows only.
  const peeks = [...out.ws.matchAll(/peekOpen\('([a-z]+)'/g)].map(m => m[1]).sort();
  ok(peeks.join(',') === 'caps,help,models,music',
     'the ⧉ overlay trigger is on Models / Music / Capabilities / Help: ' + peeks.join(',')
     + ' — Help is in because "how does conv mode work" is a question you ask WHILE '
     + 'doing the thing, and it is read-only prose with no live state to borrow');
  for (const no of ['chat', 'mc', 'logs', 'aider', 'loffice']) {
    ok(peeks.indexOf(no) < 0, no + ' has NO ⧉ trigger (it is not a peekable view)');
  }
  ok(/onclick="peekOpen\('models', event, this\)"/.test(out.ws),
     'the trigger passes the event (so it can stop the row navigating) and its own element');
  const comps = [...out.comp.matchAll(/openComponent\('([a-z]+)'\)/g)].map(m => m[1]);
  ok(comps.join(',') === 'odysseus,hermes,searxng,runner',
     'the components group lists the registry ones in nav order, then the rest: ' + comps.join(','));
  ok(/title="open the Hermes tab"/.test(out.comp),
     'a RUNNING component with a tab says so');
  ok(/title="show odysseus on MOT Deck — not running"/.test(out.comp),
     '…and a stopped one points at its card, where Start lives');
  ok(/class="dot ok"/.test(out.comp) && /class="dot warn"/.test(out.comp),
     'the live status dots survive the move into the renderer');
  // a hidden entry really disappears, and only that one
  const env2 = Object.assign({}, env, { localStorage: {
    getItem: () => JSON.stringify({ v: 1, sidebar: [{ id: 'models', pinned: false }],
                                    topbar: [{ id: 'models', pinned: true }] }),
    setItem: () => {} } });
  const run2 = new Function(...Object.keys(env2),
    srcFull + peekSrc + healthSrc + html.slice(sideStart, sideEnd) + `
    renderSidebar();
    return document.getElementById('sideworkspace').innerHTML;`);
  const ws2 = run2(...Object.values(env2));
  ok(!/id="nav-models"/.test(ws2), 'an entry hidden on the sidebar is not rendered');
  ok(/id="nav-chat"/.test(ws2) && /id="nav-mc"/.test(ws2),
     '…and hiding one takes nothing else with it');
}

// ── 5b. THE ONE-TIME REORDER MIGRATION (v1.5.26) ────────────────────────────
// THE TRAP THIS TESTS: changing NAV_DEFAULT_TOPBAR changes only a FRESH machine. Every
// machine that has ever opened the panel has a saved layout, and the saved layout wins
// — so without a migration Debi's reorder is invisible on Debi's own Mac. The rule is
// "untouched gets the new default, customised is left alone", and it must run ONCE.
console.log('the reorder migration');
{
  const V1 = () => ({ v:1,
    sidebar: M.NAV_DEFAULT_SIDEBAR.map(id => ({ id, pinned:true })),
    topbar: M.NAV_DEFAULT_TOPBAR_V1.map(id => ({ id, pinned:true }))
      .concat(M.NAV_TOPBAR_UNPINNED.map(id => ({ id, pinned:false })))
  });
  const topIds = m => m.topbar.filter(r => r.pinned).map(r => r.id).join(',');
  const NEW = M.NAV_DEFAULT_TOPBAR.join(',');
  const OLD = M.NAV_DEFAULT_TOPBAR_V1.join(',');
  ok(NEW !== OLD, 'the reorder actually reorders something (a no-op migration is a lie)');
  ok(M.NAV_DEFAULT_TOPBAR.slice().sort().join(',') === M.NAV_DEFAULT_TOPBAR_V1.slice().sort().join(','),
     '…and it moves the SAME eleven ids — nothing gained a tab, nothing lost one, so '
     + 'validate has nothing new to say and no entry can become unreachable');

  // (a) UNTOUCHED — the case that must move
  ok(topIds(M.navMigrate(V1())) === NEW,
     'an UNTOUCHED v1 layout (byte-for-byte the old default) is replaced with Debi\'s order');
  ok(M.navMigrate(V1()).sidebar.map(r => r.id).join(',') === M.NAV_DEFAULT_SIDEBAR.join(','),
     '…and the SIDEBAR is not touched: this ruling was about the tab strip only');

  // (b) CUSTOMISED — the cases that must NOT move
  const reordered = V1(); reordered.topbar = reordered.topbar.slice().reverse();
  ok(topIds(M.navMigrate(reordered)) === topIds(reordered),
     'a REORDERED layout is left exactly alone (a user\'s arrangement is theirs)');
  const unpinned = V1();
  unpinned.topbar = unpinned.topbar.map(r => r.id === 'comfyui' ? { id:r.id, pinned:false } : r);
  ok(topIds(M.navMigrate(unpinned)) === topIds(unpinned),
     '…and so is one that only differs by a PIN — the comparison is over ids AND pins, '
     + 'because unpinning a tab is customising just as much as dragging one');
  const extra = V1();
  extra.topbar = extra.topbar.concat([{ id:'nope', pinned:true }]);
  ok(topIds(M.navMigrate(extra)) === topIds(extra),
     '…and one carrying an id we do not know (a layout from a newer build)');

  // (c) ONCE — the stamp
  ok(topIds(M.navMigrate({ ...V1(), v:M.NAV_MODEL_V })) === OLD,
     'a layout ALREADY stamped v' + M.NAV_MODEL_V + ' is never migrated again — so a user '
     + 'who later arranges their tabs back into the old order keeps that arrangement');
  ok(M.navMigrate(null) === null && M.navMigrate(undefined) === undefined,
     '…and the function is TOTAL: junk in, junk back, never a throw on boot');
  ok(M.navMigrate({ v:1, topbar:'not a list' }).topbar === 'not a list',
     '…including a topbar that is not a list at all — it comes back untouched for '
     + 'navNormalize to repair, rather than being treated as an untouched default');
}

// ── 6. persistence + the two-tier sync ─────────────────────────────────────
console.log('persistence');
{
  ok(/const NAV_KEY = 'harness-nav';/.test(html), 'the localStorage key is v1-named');
  ok(/JSON\.stringify\(\{ v:NAV_MODEL_V, sidebar:navModel\.sidebar, topbar:navModel\.topbar \}\)/.test(html),
     'the instant copy is versioned');
  // v1.5.26 — THE GATE CHANGED SHAPE, and the reason is the whole migration. It used to
  // be `raw.v === 1`, i.e. "the current version"; bumping MODEL_V to 2 under that test
  // would have thrown EVERY saved layout on every machine away on upgrade — a silent
  // reset dressed as a reorder. It is now "a version we know how to read", because v1
  // and v2 have identical SHAPES (only the default order moved).
  ok(/\+raw\.v === 1 \|\| \+raw\.v === NAV_MODEL_V/.test(html),
     'both known versions are readable — the bump does not discard a saved layout');
  ok(/const NAV_MODEL_V = 2;/.test(html), 'and the panel mirrors nav.py MODEL_V');
  const sync = html.slice(html.indexOf('async function navSync()'),
                          html.indexOf('async function navSave()'));
  ok(/fetch\('\/api\/nav'\)/.test(sync) && /navModel = navNormalize\(r\.nav\)/.test(sync),
     'navSync adopts the SHARED copy (the one the shell reads)');
  ok(/renderSidebar\(\)/.test(sync), '…and redraws');
  ok(/catch \(e\) \{\}/.test(sync), '…and a bridge that is down changes nothing');
  const save = html.slice(html.indexOf('async function navSave()'),
                          html.indexOf('const TAB_FOR_COMPONENT'));
  ok(/method:'POST'/.test(save) && /'\/api\/nav'/.test(save), 'navSave POSTs the model');
  ok(/if \(!r\.ok \|\| !j\.ok\) return \(j && j\.error\)/.test(save),
     '…and returns the bridge\'s own reason when it is refused');
  ok(/postMessage\(\{ cmd:'navChanged' \}\)/.test(save),
     '…then pushes the shell so the strip does not wait for its poll');
  ok(/const h = nativeShell\(\);\s*\n\s*if \(h\)/.test(save),
     '…which is a no-op in a plain browser');
}

// ── 7. the CUSTOMIZE overlay (v2 — Debi rejected v1's static ↑ ↓ section) ──
//
// The reference is Unsloth's "Customize sidebar", and the standing doctrine is that a
// design reference is LITERAL. So the questions here are about the INTERACTION: is it a
// floating translucent panel over the page, are rows DRAGGED, is there a switch per row,
// does every change apply immediately, and does a refusal roll back rather than leaving
// the user looking at a layout the bridge did not accept.
console.log('customize overlay');
const css = html.split('<style>')[1].split('</style>')[0];
{
  // -- the surface itself
  ok(/<dialog id="navdlg" class="float-surface">/.test(html),
     'the overlay is a <dialog> (Esc and a backdrop for free) wearing the shared '
     + 'floating-surface grammar (2026-08-21: it no longer owns its own ground)');
  ok(/<div class="nv-body" id="nv-body">/.test(html), '…with a body the renderer fills');
  const b0 = css.indexOf('APPEARANCE OVERLAY — #navdlg');
  const b1 = css.indexOf('end appearance overlay');
  ok(b0 > 0 && b1 > b0, 'the sanctioned overlay CSS block is present exactly once');
  ok(html.indexOf('APPEARANCE OVERLAY — #navdlg', html.indexOf('APPEARANCE OVERLAY — #navdlg') + 1) === -1,
     '…and only once in the document');
  ok(css.indexOf('OPTIONAL "STUDIO" CHROME') > b1,
     '…and it sits BEFORE the studio block, which must stay last in the sheet');
  const blk = css.slice(b0, b1).replace(/\/\*[\s\S]*?\*\//g, '');
  const sels = [...blk.matchAll(/(?:^|\})\s*([^{}]+?)\s*\{/g)].map(m => m[1].trim());
  // 15 → 14: the light-theme ground moved out to the shared --float-* tokens.
  ok(sels.length === 14, 'the overlay block declares exactly 14 rules (got ' + sels.length + ')');
  ok(sels.every(s => s.indexOf('#navdlg') >= 0),
     'every one of them names #navdlg — nothing leaks onto the page underneath');
  // The blur + translucency ARE still there, they are just no longer this block's to
  // declare: bridge/tests/test_float_surface.js owns the shared grammar and asserts that
  // #navdlg wears it. What must be true HERE is the negative — this block must not have
  // kept a second, drifting copy of the ground.
  // (::backdrop is the page DIMMER, not the surface — it legitimately keeps its own.)
  const noBackdropRule = blk.replace(/#navdlg::backdrop\s*\{[^}]*\}/g, '');
  ok(!/backdrop-filter/.test(noBackdropRule) && !/background:rgba\(/.test(noBackdropRule),
     'the overlay block declares NO ground of its own — it comes from .float-surface, so '
     + 'the floating surfaces cannot drift apart again');
  ok(/#navdlg::backdrop/.test(blk) && /rgba\(5,4,10,\.3\)/.test(blk),
     'the backdrop is faint — the point is that the page stays visible');
  ok(/#navdlg \.nv-h \{[^}]*cursor:grab/.test(blk), 'the handle looks draggable');
  ok(/#navdlg \.nv-row\.nv-dragging/.test(blk), 'the dragged row has a state of its own');

  // -- three ways in, one overlay
  ok(/<nav id="sidemore"><a onclick="openNavDlg\(\)"/.test(html),
     'the sidebar carries the ⋯ Customize row (Unsloth\'s own path)');
  ok(html.indexOf('<nav id="sidemore">') > html.indexOf('<nav id="sideworkspace">'),
     '…under the Workspace list');
  ok(!/renderSidebar[\s\S]{0,4000}sidemore/.test(html.slice(html.indexOf('function renderSidebar'))),
     '…and it is STATIC markup, so no edit made in the overlay can hide the way back in');
  ok(/<button class="cap-btn" onclick="openNavDlg\(\)">Customize…<\/button>/.test(html),
     'Capabilities → General keeps a one-line link to the same overlay');
  ok(/\{t:'Customize navigation', k:'⠿', f:openNavDlg\}/.test(html), '…and ⌘K reaches it');

  // -- the old v1 editor is GONE, not merely unused
  ok(!/function navMove\(/.test(html), 'the v1 ↑ ↓ handler is gone');
  ok(!/function navPin\(/.test(html), 'the v1 Hide chip handler is gone');
  ok(!/function navRedraw\(/.test(html), '…and its redraw with it');
  const app = html.slice(html.indexOf('function renderAppearance()'),
                         html.indexOf('function renderAppearance()') + 900);
  ok(!/navBarHtml/.test(app), 'the Capabilities section no longer renders the list itself');

  // -- open / close
  const open = html.slice(html.indexOf('function openNavDlg()'),
                          html.indexOf('/* ---------- live drag reorder'));
  ok(/renderNavDlg\(''\)/.test(open) && /navdlg\.showModal\(\)/.test(open),
     'opening renders fresh and shows the dialog modally');
  ok(/if \(!navdlg\.open\) navdlg\.showModal\(\)/.test(open),
     '…and opening it twice cannot throw');
  ok(/function closeNavDlg\(\) \{ if \(navdlg && navdlg\.open\) navdlg\.close\(\); \}/.test(open),
     'closing is idempotent');
  ok(/addEventListener\('mousedown', e => \{ if \(e\.target === navdlg\) closeNavDlg\(\); \}\)/.test(open),
     'a click OUTSIDE closes it — on mousedown-on-the-dialog-itself, which is the backdrop');
  ok(/nv-x" onclick="closeNavDlg\(\)"/.test(html), '…and there is a ✕');

  // -- drag, live
  const drag = html.slice(html.indexOf('/* ---------- live drag reorder'),
                          html.indexOf('function navToggle('));
  ok(/draggable="true"/.test(html) && /ondragstart="navDragStart\(/.test(html),
     'rows are DRAGGED (not moved by buttons)');
  ok(/ondragover="navDragOver\(/.test(html) && /ondrop="navDrop\(/.test(html)
     && /ondragend="navDragEnd\(/.test(html), '…with the full HTML5 drag wiring');
  ok(/box\.insertBefore\(navDrag\.el, before\)/.test(drag)
     && /box\.appendChild\(navDrag\.el\)/.test(drag),
     'the list RE-FLOWS LIVE — the node itself is moved while you drag');
  ok(/ev\.clientY < b\.top \+ b\.height \/ 2/.test(drag),
     '…deciding by the midpoint of the row under the cursor');
  ok(/if \(!navDrag \|\| navDrag\.bar !== bar \|\| navDrag\.grp !== grp\) return;/.test(drag),
     'a row can only be dropped in its OWN group — which is what keeps the saved order '
     + 'and the rendered sidebar in step (v1\'s real reorder bug)');
  ok(/function navDragEnd\(\)[\s\S]*navCommitOrder\(d\.bar\)/.test(drag),
     'the commit hangs off dragend, which fires on every ending incl. a cancelled drag');
  ok(/classList\.remove\('nv-dragging'\)/.test(drag), '…and the drag state is always cleared');
  ok(/function navDrop\(ev\) \{ ev\.preventDefault\(\); \}/.test(drag),
     'drop itself does nothing but allow the drop (no double commit)');
  ok(/ev\.target\.closest\('\.cap-sw'\)\) \{ ev\.preventDefault\(\); return; \}/.test(drag),
     'a drag that starts ON the switch is refused — it toggles, it does not move the row');
  ok(/max-width:none/.test(blk),
     'the overlay restates max-width (the base `dialog` rule caps every dialog at 520px)');

  // -- every change is its own POST, and a refusal rolls back
  const apply = html.slice(html.indexOf('function navApply(next)'),
                           html.indexOf('function navClone()'));
  ok(apply.indexOf('navValidate(next)') < apply.indexOf('navModel = next'),
     'a change is VALIDATED before it is adopted');
  ok(/if \(err\) \{ renderNavDlg\(err\); return Promise\.resolve\(err\); \}/.test(apply),
     '…and a client-side refusal adopts nothing at all, it just says why');
  ok(/const prev = navGet\(\);/.test(apply) && /navModel = prev; navSaveLocal\(\); renderSidebar\(\); renderNavDlg\(e2\);/.test(apply),
     'a BRIDGE refusal rolls the whole model back (optimistic UI, honest rollback)');
  ok(/return navSave\(\)/.test(apply), 'every accepted change is saved immediately (no Save button)');
  const rend = html.slice(html.indexOf('function renderNavDlg(err)'),
                          html.indexOf('const navdlg = document.getElementById'));
  ok(!/Save|Apply/.test(rend), '…and the overlay renders no Save/Apply button at all');
  ok(/function navToggle\(bar, id, el\)[\s\S]{0,260}navApply\(next\)/.test(html),
     'a switch writes through the same path');
  ok(/if \(navRowFixed\(bar, id\)\) \{ if \(el\) el\.checked = true; return; \}/.test(html),
     '…and a fixed entry cannot be switched off even by calling the handler directly');
  ok(/id="nav-err"/.test(html), 'there is somewhere for a refusal to appear, inside the overlay');
  ok(/⋯/.test(html), 'the copy tells the user where a hidden tab goes');
  ok(/aside \{ position: sticky; top: 0; align-self: flex-start;\s*\n\s*height: 100vh; overflow-y: auto; \}/
       .test(css),
     'the sidebar still scrolls when it is longer than the window (no cap on entries)');
}

// ── 7b. EXECUTE the overlay's renderer + its commit ────────────────────────
// The renderer and navCommitOrder are the two places a bug would be invisible to a grep:
// one decides what you can touch, the other turns what you SEE back into the model.
console.log('overlay behaviour');
{
  const s0 = html.indexOf('const NAV_BAR_LABEL =');
  const s1 = html.indexOf('function renderNavDlg(err)');
  const c0 = html.indexOf('function navCommitOrder(bar)');
  const c1 = html.indexOf('function navToggle(bar, id, el)');
  ok(s0 > 0 && s1 > s0 && c0 > s1 && c1 > c0, 'the overlay helpers are where the test expects');
  const model = { sidebar: M.navDefaultModel().sidebar, topbar: M.navDefaultModel().topbar };
  const posted = [];
  const env = {
    esc: x => String(x), escAttr: x => String(x),
    navGet: () => model,
    navClone: () => ({ sidebar: model.sidebar.map(r => ({ ...r })),
                       topbar: model.topbar.map(r => ({ ...r })) }),
    navApply: next => { posted.push(next); return Promise.resolve(''); },
    document: null,
  };
  // the pure model half, again (section 5's copy is block-scoped)
  const pure = html.slice(html.indexOf('const NAV_ENTRIES = ['), html.indexOf('let navModel = null;'));
  const body = pure + html.slice(s0, s1) + html.slice(c0, c1);
  const mk = extra => new Function(...Object.keys(env), body + extra);

  // (1) the sidebar is edited in the TWO GROUPS the sidebar is DRAWN in
  const groups = mk('return { g: navGroups("sidebar").map(x => x.key), t: navGroups("topbar").map(x => x.key) };')
    (...Object.values(env));
  ok(groups.g.join(',') === 'ws,comp', 'the sidebar has a Workspace group and a Components group');
  ok(groups.t.join(',') === 'all', '…and the strip is one list');
  const barHtml = mk('return navBarHtml("sidebar");')(...Object.values(env));
  const grpIds = [...barHtml.matchAll(/data-grp="(\w+)"/g)].map(m => m[1]);
  ok(grpIds.join(',') === 'ws,comp', 'both groups are rendered as their own drop zones');
  const wsPart = barHtml.slice(barHtml.indexOf('data-grp="ws"'), barHtml.indexOf('data-grp="comp"'));
  ok(/data-id="hermes"/.test(barHtml) && !/data-id="hermes"/.test(wsPart),
     'a component is in the Components group, never the Workspace one');
  // (2) fixed rows show no controls rather than controls that refuse
  const rowOf = (h, id) => ('<div class="nv-row' + h.split('<div class="nv-row')
    .find(p => p.indexOf('data-id="' + id + '"') >= 0));
  const chatRow = rowOf(barHtml, 'chat');
  ok(/nv-fixed/.test(chatRow) && !/type="checkbox"/.test(chatRow) && !/draggable="true"/.test(chatRow),
     'Chat (fixed on the sidebar) has no switch and cannot be dragged');
  ok(/class="cap-pill">always/.test(chatRow), '…and says so');
  const topHtml = mk('return navBarHtml("topbar");')(...Object.values(env));
  const mcRow = rowOf(topHtml, 'mc');
  ok(/nv-fixed/.test(mcRow) && !/draggable="true"/.test(mcRow),
     'Mission Control is fixed on the strip, so nothing can be dropped above it');
  ok((topHtml.match(/type="checkbox"/g) || []).length === model.topbar.length - 1,
     'every other strip row gets exactly one switch');
  ok(/max 12/.test(topHtml), 'the strip names its cap');
  // a HIDDEN row is still listed (hiding keeps its place — nav.py\'s design) and unchecked
  const m2 = { sidebar: model.sidebar.map(r => r.id === 'models' ? { ...r, pinned: false } : r),
               topbar: model.topbar };
  const env2 = Object.assign({}, env, { navGet: () => m2 });
  const h2 = mk('return navBarHtml("sidebar");')(...Object.values(env2));
  ok(/data-id="models"/.test(h2), 'a hidden entry keeps its place in the editor…');
  const mrow = h2.slice(h2.indexOf('data-id="models"'), h2.indexOf('data-id="models"') + 400);
  ok(/type="checkbox" \n?\s*onchange/.test(mrow) || !/checked/.test(mrow.split('onchange')[0]),
     '…with its switch OFF');

  // (3) navCommitOrder: read the DOM back → model. Stubbed document, real logic.
  const fakeDom = ids => ({
    querySelectorAll: () => ids.map(id => ({ getAttribute: () => id })),
  });
  const order = model.topbar.map(r => r.id);
  const moved = [order[0]].concat([order[2]], order.slice(1, 2), order.slice(3));
  const env3 = Object.assign({}, env, { document: fakeDom(moved) });
  posted.length = 0;
  mk('navCommitOrder("topbar");')(...Object.values(env3));
  ok(posted.length === 1, 'a real move posts exactly once');
  ok(posted[0].topbar.map(r => r.id).join(',') === moved.join(','),
     '…carrying the order the user is looking at');
  ok(posted[0].topbar.every(r => r.pinned === model.topbar.find(x => x.id === r.id).pinned),
     '…and a REORDER never changes what is shown (pins are carried by id)');
  posted.length = 0;
  const env4 = Object.assign({}, env, { document: fakeDom(order) });
  mk('navCommitOrder("topbar");')(...Object.values(env4));
  ok(posted.length === 0, 'a drag that ends where it started posts NOTHING');
  posted.length = 0;
  const env5 = Object.assign({}, env, { document: fakeDom(['nope', order[1]]) });
  mk('navCommitOrder("topbar");')(...Object.values(env5));
  ok(posted.length === 1 && posted[0].topbar.length === model.topbar.length,
     'an id the model does not know is ignored, and no row is lost');
  ok(posted[0].topbar.map(r => r.id).indexOf('nope') < 0, '…rather than being adopted');
}


// ── 8. click routing ───────────────────────────────────────────────────────
console.log('routing');
{
  const open = html.slice(html.indexOf('function navOpen(id)'),
                          html.indexOf('/* ---------- the sidebar, rendered'));
  ok(/if \(e\.id === 'logs'\) \{ showLogs\(\); return; \}/.test(open),
     'Logs opens the dialog');
  ok(/if \(e\.kind === 'component'\) \{ openComponent\(id\); return; \}/.test(open),
     'a component keeps its own rule (running → its tab, stopped → its card)');
  ok(/if \(e\.prefersTab && e\.tab\) \{/.test(open)
     && /if \(shellKnowsTab\(e\.id\) !== false && switchTab\(e\.tab, e\.id\)\) return;/.test(open),
     'a lane asks the shell for its tab first — and never with an id the shell says it lacks');
  ok(/if \(e\.view\) \{ showView\(e\.view\); return; \}/.test(open),
     'a panel view opens IN the panel');
  ok(/window\.open\(e\.url, '_blank'\)/.test(open),
     'a lane in a plain browser opens its page rather than becoming a dead row');
  // THE 2026-08-21 REGRESSION, pinned: clicking Aider/LOffice inside the app opened the
  // page in CHROME, because a stale shell made switchTab return false and the very next
  // line was window.open(). The in-app guard must exist AND must precede that line.
  const guard = open.indexOf('if (inNativeApp() && !e.view) { navShellNote(e.id, SHELL_STALE_NOTE); return; }');
  const wopen = open.indexOf("window.open(e.url, '_blank')");
  ok(guard >= 0, 'inside the app a lane with no view says so instead of falling through');
  ok(guard >= 0 && wopen >= 0 && guard < wopen,
     '…and that guard sits BEFORE the window.open fallback (this is the whole bug)');
  // Pinned as its WHOLE body: it must ask only whether we are in a WKWebView, never
  // whether the "harness" handler is there. A shell built before that handler existed is
  // exactly the case this has to be true for.
  ok(/function inNativeApp\(\) \{\s*\n\s*return !!\(window\.webkit && window\.webkit\.messageHandlers\);\s*\n\}/.test(html),
     'inNativeApp is deliberately weaker than nativeShell — true even with no harness handler');
  ok(/function shellKnowsTab\(id\)[\s\S]{0,200}return t \? t\.indexOf\(id\) >= 0 : null;/.test(html),
     'an unknowable shell answers null, never false (a missing global is not "no tabs")');
  // the deliberate asymmetry, recorded: mc/chat/models/caps are views and do NOT jump
  // out of the panel even when the user has pinned them as tabs.
  ok(!M.navEntry('chat').prefersTab && !M.navEntry('models').prefersTab
     && !M.navEntry('caps').prefersTab && !M.navEntry('mc').prefersTab,
     'pinning a VIEW as a tab does not make its sidebar row leave the panel');
  ok(M.navEntry('music').prefersTab === true,
     'Music keeps its established behaviour (its tab wins, with the view as fallback)');
}

console.log('');
console.log(fails ? fails + ' failure(s) of ' + checks : 'nav panel: ' + checks + ' checks passed');
process.exit(fails ? 1 : 0);
