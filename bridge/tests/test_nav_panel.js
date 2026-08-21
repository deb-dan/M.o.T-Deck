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
  NAV_DEFAULT_SIDEBAR, NAV_DEFAULT_TOPBAR, NAV_TOPBAR_UNPINNED,
  navEntry, navCanShow, navDefaultModel, navNormalize, navValidate };`)();
const ids = (m, bar) => m[bar].map(r => r.id);

// ── 1. the registry ─────────────────────────────────────────────────────────
console.log('registry');
{
  const seen = {};
  M.NAV_ENTRIES.forEach(e => { ok(!seen[e.id], 'no duplicate id: ' + e.id); seen[e.id] = 1; });
  // Debi's amendment: the two newest LANES are registry entries — that is precisely how
  // they become reachable from the sidebar (they are lanes, not services, so they have
  // no Mission Control card and were previously reachable only from the tab strip).
  for (const id of ['aider', 'loffice']) {
    const e = M.navEntry(id);
    ok(e && e.kind === 'lane', id + ' is a registry LANE');
    ok(e && e.prefersTab === true, '...and a click on it asks the shell for its tab');
    ok(e && typeof e.url === 'string' && e.url.startsWith('/'),
       '...with a page URL, so a plain browser is not left with a dead row');
    ok(e && !e.view, '...and no in-panel view (it does not have one)');
  }
  ok(M.navEntry('loffice').tab === 'LOffice' && M.navEntry('aider').tab === 'Aider',
     'the lane tab titles are the shell\'s, spelled exactly');
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
  ok(M.NAV_SIDEBAR_ONLY.join() === 'logs', '…and it is the one sidebar-only entry');
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
  ok(ws.join(',') === 'mc,chat,models,music,aider,loffice,caps,logs',
     'the workspace rail is today\'s order + the two lanes: ' + ws.join(','));
  const comps = ids(d, 'sidebar').filter(i => M.navEntry(i).kind === 'component');
  ok(comps.join(',') === 'odysseus,hermes,voicestudio,voicebox,comfyui,unsloth',
     'the components group lists every component that has a tab');
  ok(d.sidebar.every(r => r.pinned), 'nothing starts hidden on the sidebar');
  const top = d.topbar.filter(r => r.pinned).map(r => r.id);
  ok(top.join(',') === 'mc,odysseus,hermes,voicestudio,voicebox,comfyui,unsloth,music,aider,loffice',
     'the default strip is exactly the ten tabs that shipped, in order');
  ok(d.topbar.filter(r => !r.pinned).map(r => r.id).join(',') === 'chat,models,caps',
     'the three pinnable VIEWS start hidden (they are one sidebar click away)');
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
  ok(m.topbar.length === 13, 'the registry offers 13 strip-able entries');
  const e13 = M.navValidate(m);
  ok(e13 && e13.indexOf(String(M.NAV_TOPBAR_MAX)) >= 0,
     'the 13th pin is refused and the message NAMES the limit: ' + e13);
  m.topbar.forEach(r => { if (r.id === 'caps') r.pinned = false; });
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
  const run = new Function(...Object.keys(env),
    srcFull + html.slice(sideStart, sideEnd) + `
    NAV_ENTRIES.forEach(e => { if (e.kind === 'component' && e.tab) TAB_FOR_COMPONENT[e.id] = e.tab; });
    renderSidebar();
    return { ws: document.getElementById('sideworkspace').innerHTML,
             comp: document.getElementById('sidecomponents').innerHTML };`);
  const out = run(...Object.values(env));
  const rows = [...out.ws.matchAll(/id="nav-([a-z]+)"/g)].map(m => m[1]);
  ok(rows.join(',') === 'mc,chat,models,music,aider,loffice,caps,logs',
     'with NO saved layout the workspace rail renders today\'s rows + the two lanes');
  ok(/id="nav-chat" class="on"/.test(out.ws),
     'the current view is highlighted after a render (curView, not a lost class)');
  ok((out.ws.match(/onclick="navOpen\(/g) || []).length === rows.length,
     'every workspace row is clickable through navOpen');
  ok(/<span class="ico">♫<\/span> Music/.test(out.ws), 'the icons and labels come from the registry');
  const comps = [...out.comp.matchAll(/openComponent\('([a-z]+)'\)/g)].map(m => m[1]);
  ok(comps.join(',') === 'odysseus,hermes,searxng,runner',
     'the components group lists the registry ones in nav order, then the rest: ' + comps.join(','));
  ok(/title="open the Hermes tab"/.test(out.comp),
     'a RUNNING component with a tab says so');
  ok(/title="show odysseus on Mission Control — not running"/.test(out.comp),
     '…and a stopped one points at its card, where Start lives');
  ok(/class="dot ok"/.test(out.comp) && /class="dot warn"/.test(out.comp),
     'the live status dots survive the move into the renderer');
  // a hidden entry really disappears, and only that one
  const env2 = Object.assign({}, env, { localStorage: {
    getItem: () => JSON.stringify({ v: 1, sidebar: [{ id: 'models', pinned: false }],
                                    topbar: [{ id: 'models', pinned: true }] }),
    setItem: () => {} } });
  const run2 = new Function(...Object.keys(env2),
    srcFull + html.slice(sideStart, sideEnd) + `
    renderSidebar();
    return document.getElementById('sideworkspace').innerHTML;`);
  const ws2 = run2(...Object.values(env2));
  ok(!/id="nav-models"/.test(ws2), 'an entry hidden on the sidebar is not rendered');
  ok(/id="nav-chat"/.test(ws2) && /id="nav-mc"/.test(ws2),
     '…and hiding one takes nothing else with it');
}

// ── 6. persistence + the two-tier sync ─────────────────────────────────────
console.log('persistence');
{
  ok(/const NAV_KEY = 'harness-nav';/.test(html), 'the localStorage key is v1-named');
  ok(/JSON\.stringify\(\{ v:1, sidebar:navModel\.sidebar, topbar:navModel\.topbar \}\)/.test(html),
     'the instant copy is versioned');
  ok(/raw && raw\.v === 1 \? raw : null/.test(html),
     'a copy from another version is ignored, not half-read');
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

// ── 7. the Appearance editor ───────────────────────────────────────────────
console.log('appearance');
{
  ok(/function renderAppearance\(\)/.test(html), 'renderAppearance exists');
  ok(/setSec\('caps-sec-general', generalHtml \+ renderAppearance\(\)\)/.test(html),
     'it lives in Capabilities → General (no new top-level view)');
  ok(/if \(g\) g\.innerHTML = renderAppearance\(\);/.test(html),
     '…and renders on the Odysseus-unreachable path too (it writes OUR file, not theirs)');
  const bar = html.slice(html.indexOf('function navBarHtml(bar)'),
                         html.indexOf('function renderAppearance()'));
  ok(/navMove\('\$\{bar\}','\$\{escAttr\(r\.id\)\}',-1\)/.test(bar)
     && /navMove\('\$\{bar\}','\$\{escAttr\(r\.id\)\}',1\)/.test(bar),
     'each row has ↑ and ↓ (buttons, not drag — testable and needs no new CSS)');
  ok(/navPin\('\$\{bar\}','\$\{escAttr\(r\.id\)\}'\)/.test(bar), '…and one pin/hide chip');
  ok(/\$\{\(i === 0 \|\| first\) \? 'disabled' : ''\}/.test(bar),
     'the first row cannot move up');
  ok(/navRowFixed\(bar, r\.id\)/.test(bar) && /\$\{fixed \? 'disabled' : ''\}/.test(bar),
     'a fixed entry\'s pin chip is disabled, not silently ignored');
  ok(/class="cap-pill off">hidden/.test(bar), 'a hidden row says so');
  // ZERO new CSS: every class used here already exists in the stylesheet
  const css = html.split('<style>')[1].split('</style>')[0];
  ['cap-row', 'cap-txt', 'cap-name', 'cap-ctl', 'cap-btn', 'cap-pill', 'cap-count',
   'caps-group', 'cap-card', 'cap-desc'].forEach(c => {
    ok(css.indexOf('.' + c) >= 0, 'Appearance reuses the existing .' + c);
  });
  ok(!/#caps-appearance\s*\{/.test(css) && !/\.nav-row\s*\{/.test(css),
     'the editor invents NO new css rule of its own');
  const apply = html.slice(html.indexOf('function navApply(next)'),
                           html.indexOf('function navClone()'));
  ok(apply.indexOf('navValidate(next)') < apply.indexOf('navModel = next'),
     'a change is VALIDATED before it is adopted (a refused edit leaves the model alone)');
  ok(/if \(err\) \{ navRedraw\(err\); return; \}/.test(apply),
     '…and the reason is shown instead of being applied');
  const mv = html.slice(html.indexOf('function navMove(bar, id, dir)'),
                        html.indexOf('function navPin(bar, id)'));
  ok(/if \(bar === 'topbar' && \(i === 0 \|\| j === 0\)\) return;/.test(mv),
     'nothing can be moved above Mission Control on the strip');
  ok(/const next = navClone\(\)/.test(mv), 'edits are made on a COPY');
  const pin = html.slice(html.indexOf('function navPin(bar, id)'),
                         html.indexOf('function navPin(bar, id)') + 500);
  ok(/if \(navRowFixed\(bar, id\)\) return;/.test(pin),
     'the fixed entries cannot be un-pinned even by calling the handler directly');
  ok(/id="nav-err"/.test(html), 'there is somewhere for the refusal to appear');
  ok(/⋯/.test(html), 'the copy tells the user where a hidden tab goes');
  // Debi's amendment: the sidebar is UNCAPPED and must scroll when it grows. It already
  // does — pinned here so a future layout change cannot quietly take it away, and so the
  // "zero new CSS" claim for this slice is checkable.
  ok(/aside \{ position: sticky; top: 0; align-self: flex-start;\s*\n\s*height: 100vh; overflow-y: auto; \}/
       .test(css),
     'the sidebar scrolls when it is longer than the window (no cap on entries)');
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
  ok(/if \(e\.prefersTab && e\.tab && switchTab\(e\.tab, e\.id\)\) return;/.test(open),
     'a lane asks the shell for its tab first');
  ok(/if \(e\.view\) \{ showView\(e\.view\); return; \}/.test(open),
     'a panel view opens IN the panel');
  ok(/window\.open\(e\.url, '_blank'\)/.test(open),
     'a lane in a plain browser opens its page rather than becoming a dead row');
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
