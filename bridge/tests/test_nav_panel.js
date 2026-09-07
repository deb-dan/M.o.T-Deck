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
  NAV_OFFBAR, NAV_SUPERSEDED, NAV_TOPBAR_PINS, NAV_TOPBAR_MRU, NAV_DEFAULT_MRU,
  navEntry, navCanShow, navCanTab, navDefaultModel, navNormalize, navValidate,
  navMigrate, navPins, navStrip, navDefaultPos };`)();
const ids = (m, bar) => m[bar].map(r => r.id);

// ── 1. the registry ─────────────────────────────────────────────────────────
console.log('registry');
{
  const seen = {};
  M.NAV_ENTRIES.forEach(e => { ok(!seen[e.id], 'no duplicate id: ' + e.id); seen[e.id] = 1; });
  // Debi's amendment: the two newest LANES are registry entries — that is precisely how
  // they become reachable from the sidebar (they are lanes, not services, so they have
  // no Mission Control card and were previously reachable only from the tab strip).
  for (const id of ['aider', 'loffice', 'goose', 'comfy', 'compose', 'gooseui']) {
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
  // THE MUSIC PAIR — REWRITTEN AT THE CONSOLIDATION SLICE (Debi 2026-08-29) AND NOT
  // WEAKENED. The Compose slice's rule was "both stay until Debi picks"; she picked:
  // ONE door, both looks. BOTH SURFACES STILL EXIST and neither may be collapsed into
  // the other — what changed is that only ONE of them may be a ROW, and it is the one
  // labelled Music, opening the Studio.
  {
    const m = M.navEntry('music'), c = M.navEntry('compose');
    ok(m && c, 'both music entries exist');
    ok(m.kind === 'view' && c.kind === 'lane', 'music is the VIEW, compose is our LANE');
    ok(c.label === 'Music' && c.tab === 'Music' && c.url === '/compose',
       'the one Music row opens the Studio at our own page');
    ok(c.id === 'compose',
       '…while its ID did not churn with the label (the Goose CLI rule verbatim)');
    ok(m.label === 'Music Classic' && m.tab === undefined && m.id === 'music',
       'the original view is Music Classic, id unmoved — and it owns NO tab '
       + '(v1.5.60: Classic is in-place only)');
    ok(M.NAV_OFFBAR.join(',') === 'music'
       && !M.navCanShow('music', 'sidebar') && !M.navCanShow('music', 'topbar'),
       'ONE Music row: Classic may be a row on NEITHER bar');
    ok(!M.navCanTab('music') && M.navCanTab('compose'),
       '…and the strip can NEVER draw it (v1.5.60: tab_only revoked — one click in ⋯ '
       + 'was re-creating the second Music tab; Classic rides the Music tab in place)');
    ok(M.NAV_SUPERSEDED.music === 'compose',
       'a saved layout naming `music` is rewritten into the Music row, not dropped');
    ok(m.tab !== c.tab, 'they are two different native tabs');
    ok(m.view === 'music' && c.view === null,
       '…and the Music view is untouched: it still renders inside the panel');
    // The GENERAL form of the v1.5.38 lesson: a nav row may never wear another
    // control's OR another row's glyph. A row wearing Music's mark would read as Music.
    // ⚠️ THE GLYPHS SWAPPED AT THE CONSOLIDATION SLICE. ♫ belongs to whichever row
    // says "Music" to a user, and that is the Studio row now; ≋ (a waveform) moves to
    // Classic. The RULE is unchanged and still enforced below: no two entries share a
    // glyph, and no row wears a chrome control's mark.
    ok(c.ico === '♫' && m.ico === '≋',
       'the Music row wears the note; Classic wears the waveform');
    ok(c.ico !== m.ico && c.ico !== '✦' && c.ico !== '▣',
       'the Music icon is not another row\u2019s and not a chrome control\u2019s glyph');
    ok(M.NAV_ENTRIES.filter(e => e.ico && e.ico === c.ico).length === 1,
       '…and no other nav row wears it either');
    const nids = M.NAV_ENTRIES.map(e => e.id);
    ok(nids.indexOf('compose') === nids.indexOf('music') + 1,
       'Compose is registered DIRECTLY after Music (the spec\u2019s placement)');
  }
  // THE GOOSE PAIR (Goose UI slice, ledger S14) \u2014 the same argument a third time, and
  // here it is Debi's explicit ruling that both lanes coexist. `goose` is the PTY
  // terminal at /goose; `gooseui` is goose Desktop's own renderer served by us at
  // /gooseui/. Separate homes, separate sessions, both alive at once.
  {
    const t = M.navEntry('goose'), u = M.navEntry('gooseui');
    ok(t && u, 'both goose entries exist');
    ok(t.kind === 'lane' && u.kind === 'lane', 'both are LANES \u2014 neither has a MC card');
    // THE RENAME. The display name says WHICH goose; the id, the route and the pty path
    // do not churn with a wordmark (LOffice's rule).
    ok(t.label === 'Goose CLI' && t.tab === 'Goose CLI',
       'the terminal lane is named Goose CLI now that there are two goose surfaces');
    ok(t.id === 'goose' && t.url === '/goose',
       '\u2026while its id and its route are UNCHANGED \u2014 only the display name moved');
    ok(u.label === 'Goose UI' && u.tab === 'Goose UI',
       'the embedded lane is named Goose UI');
    // \u26a0\ufe0f THE TRAILING SLASH IS LOAD-BEARING: /gooseui 308s to /gooseui/, and the bundle
    // resolves its assets RELATIVELY \u2014 without the slash they hit the panel's own
    // /assets/ mount and the page paints black with no error (v1.5.40 A1).
    ok(u.url === '/gooseui/', '\u2026and its URL carries the trailing slash the bundle needs');
    ok(t.tab !== u.tab, 'they are two different native tabs');
    // The v1.5.38 lesson in its general form, a third time.
    ok(u.ico !== t.ico && u.ico !== '\u2726' && u.ico !== '\u25a3' && u.ico !== '\u25d0',
       'the Goose UI icon is neither the CLI row\u2019s mark nor a chrome control\u2019s');
    ok(M.NAV_ENTRIES.filter(e => e.ico && e.ico === u.ico).length === 1,
       '\u2026and no other nav row wears it either');
    const gids = M.NAV_ENTRIES.map(e => e.id);
    ok(gids.indexOf('gooseui') === gids.indexOf('goose') + 1,
       'Goose UI is registered DIRECTLY after Goose CLI (one product, two surfaces)');
  }
  // every `tab` the panel names must be a title the shell actually has, or the
  // switchTab bridge silently does nothing.
  const swiftTitles = (swift.match(/MOTDeckTab\(id: "[^"]+", title: "([^"]+)"/g) || [])
    .map(s => s.replace(/.*title: "/, '').replace('"', ''));
  M.NAV_ENTRIES.filter(e => e.tab).forEach(e => {
    ok(swiftTitles.indexOf(e.tab) >= 0, 'the shell has a tab titled "' + e.tab + '"');
  });
  // …and every id the panel names must be an id the shell has, since the id is what the
  // switchTab bridge now resolves first.
  const swiftIds = (swift.match(/MOTDeckTab\(id: "([^"]+)"/g) || [])
    .map(s => s.replace('MOTDeckTab(id: "', '').replace('"', ''));
  M.NAV_ENTRIES.filter(e => e.tab).forEach(e => {
    ok(swiftIds.indexOf(e.id) >= 0, 'the shell knows the id "' + e.id + '"');
  });
  ok(M.navEntry('logs') && !M.navEntry('logs').view && !M.navEntry('logs').tab,
     'Logs is a dialog: no view, no tab');
  ok(M.NAV_SIDEBAR_ONLY.join() === 'logs,help,api',
     '…and the sidebar-only set is Logs + Help + API (S32)');
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
    ok(M.NAV_ALWAYS.join() === 'logs,help,api',
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
  // …and the Compose slice adds a FIFTH, `compose`, DIRECTLY after Music — the two
  // music surfaces read as the pair they are. Still an ADDITION only: no existing row
  // changed position relative to its neighbours.
  // …and the Goose UI slice adds a SIXTH, `gooseui`, DIRECTLY after Goose CLI — the two
  // goose surfaces read as the pair they are. Still an ADDITION only: no existing row
  // changed position relative to its neighbours.
  // …and the CONSOLIDATION slice REMOVES one, which is the only removal in this list's
  // history and is Debi's own ruling: `music` and `compose` were two rows for one job,
  // and the surviving row (id `compose`, labelled Music) sits where Music sat. Classic
  // is not lost — it is behind that page's header switcher.
  // …and the S32 slice adds `api` at the tail, directly after Help, by Help's own
  // upgrade rule. Still an ADDITION only: no existing row changed position.
  ok(ws.join(',') === 'mc,chat,models,compose,comfy,aider,goose,gooseui,loffice,caps,logs,help,api',
     'the workspace rail is today\'s order with ONE Music row: ' + ws.join(','));
  const comps = ids(d, 'sidebar').filter(i => M.navEntry(i).kind === 'component');
  // + deepseek at the tail (S34), by the same additive upgrade rule as `api` above.
  ok(comps.join(',') === 'odysseus,hermes,voicestudio,voicebox,comfyui,unsloth,opencode,deepseek',
     'the components group lists every component that has a tab');
  ok(d.sidebar.every(r => r.pinned), 'nothing starts hidden on the sidebar');
  const top = d.topbar.filter(r => r.pinned).map(r => r.id);
  // v1.5.26 — DEBI'S ORDER. Same eleven ids, new reading order (the deck · the three
  // agent/model lanes · everything else). Pinned as a literal on purpose: here the
  // ORDER itself is the requirement, so it may not drift silently.
  // ⚠️ NINE PINS SINCE THE 9+3 RULING — and eleven TABS still, because the tenth and
  // eleventh became the window's seed. Both halves are literals here: the order is the
  // requirement, and "the strip did not shrink" is the promise.
  ok(top.join(',') === 'mc,hermes,unsloth,opencode,odysseus,voicestudio,comfyui,aider,loffice',
     'the default PINS are the nine, in Debi\'s order: ' + top.join(','));
  ok(M.NAV_DEFAULT_MRU.join(',') === 'compose,voicebox',
     'the window\'s seed is what used to be pinned tenth and eleventh');
  ok(M.navStrip(d).join(',') === 'mc,hermes,unsloth,opencode,odysseus,voicestudio,comfyui,aider,loffice,compose,voicebox',
     'so the default STRIP is the same eleven tabs, Music in Music\'s slot');
  ok(M.NAV_TOPBAR_PINS + M.NAV_TOPBAR_MRU === M.NAV_TOPBAR_MAX && M.NAV_TOPBAR_MAX === 12,
     '9 pins + a 3-slot window = Debi\'s 12, unchanged');
  // ⚠️ WIDENED, NOT WEAKENED, at the goose slice: still a closed literal list, and
  // goose is on it because the strip is at 11 of 12 pins and a new lane must not spend
  // the last one silently. It is one sidebar click (or one ⋯) away.
  // ⚠️ WIDENED AGAIN, STILL NOT WEAKENED, at the comfy-nav slice: `comfy` (Generate)
  // joins for goose's identical argument — the pinned prefix above is STILL eleven, so
  // the last free pin is still free. Closed literal list; order mirrors nav.py's tail.
  // ⚠️ WIDENED A THIRD TIME, STILL NOT WEAKENED, at the Compose slice: `compose` joins
  // for the same reason plus one of its own — it is an alternative to the PINNED
  // `music`, and pinning both by default would choose for the user. Closed literal
  // list; the order mirrors nav.py's tail.
  // ⚠️ WIDENED A FOURTH TIME, STILL NOT WEAKENED, at the Goose UI slice: `gooseui` joins
  // with the strongest form of the argument — it is an alternative SURFACE onto the same
  // product as `goose`, which is itself still behind ⋯ waiting for the one free pin, so
  // pinning the embedded lane would declare a winner between two coexisting lanes.
  // ⚠️ WIDENED A FIFTH TIME AT THE 9+3 SLICE, STILL NOT WEAKENED: `compose` and
  // `voicebox` LEAD the list because they join it for a different reason — they are the
  // window's seed and are ON the strip, not waiting behind ⋯ for a pin.
  // ⚠️ WIDENED A SIXTH TIME AT THE DEEPSEEK SLICE (S34), STILL NOT WEAKENED: one more
  // row at the TAIL, the nine-pin prefix untouched. Pinning it instead would have been
  // the weakening — there is no tenth pin to spend.
  ok(d.topbar.filter(r => !r.pinned).map(r => r.id).join(',') === 'compose,voicebox,chat,models,caps,goose,comfy,gooseui,deepseek',
     'the window seed + the pinnable VIEWS + goose + comfy + gooseui + deepseek are unpinned, in order');
  ok(top.length <= M.NAV_TOPBAR_PINS, 'the default pins are inside the pin cap');
  ok(M.navStrip(d).length <= M.NAV_TOPBAR_MAX, 'and the default strip inside the strip cap');
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
  // ⚠️ NOT `[0] === 'chat'` SINCE THE NEIGHBOUR-APPEND FIX (ledger A8/S19): `mc` leads
  // the default order, so a layout that lost it gets it back in FRONT, not at the tail.
  ok(ids(m, 'sidebar').indexOf('chat') > ids(m, 'sidebar').indexOf('mc'),
     '…the known ones are kept, and a missing first-in-order entry lands in front');
  m = M.navNormalize({ topbar: [{ id: 'logs' }, { id: 'odysseus' }] });
  ok(ids(m, 'topbar').indexOf('logs') < 0, 'logs cannot be put on the strip');
  ok(ids(m, 'topbar')[0] === 'mc' && m.topbar[0].pinned,
     'Mission Control is forced FIRST and PINNED on the strip');
  ok(ids(m, 'topbar').indexOf('odysseus') > 0, '…and the rest keep the order given');
  m = M.navNormalize({ sidebar: [{ id: 'chat', pinned: false }] });
  ok(m.sidebar.some(r => r.id === 'chat' && r.pinned),
     'Chat can never be un-pinned from the sidebar');
  m = M.navNormalize({ sidebar: [{ id: 'caps' }, { id: 'models', pinned: false }] });
  {
    const g = ids(m, 'sidebar');
    ok(g.indexOf('caps') < g.indexOf('models'),
       'a HIDDEN row keeps its place in the order (un-hiding puts it back where it was)');
    ok(m.sidebar.find(r => r.id === 'models').pinned === false, '…and stays hidden');
  }
  ok(ids(m, 'sidebar').length === M.NAV_DEFAULT_SIDEBAR.length,
     'every omitted entry is appended, so a new registry row appears for everyone');
  // appending must never invalidate a model that was valid
  // ⚠️ THE CAP THE APPEND RESPECTS IS THE PIN CAP (9) SINCE THE RULING, NOT THE STRIP
  // SIZE (12). Same rule, same boundary case: growing the registry may never invalidate
  // a model that was valid a moment ago.
  const nine = ['mc','odysseus','hermes','voicestudio','voicebox','comfyui','unsloth',
                'compose','aider'].map(id => ({id, pinned:true}));
  m = M.navNormalize({ topbar: nine });
  ok(m.topbar.filter(r => r.pinned).length === M.NAV_TOPBAR_PINS,
     'an appended entry is never pinned onto a full strip');
  ok(M.navValidate(m) === '', '…so normalize can never hand back an over-pinned strip');
  ok(M.navStrip(m).length <= M.NAV_TOPBAR_MAX, '…and the strip it derives fits in twelve');
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
  // …and one pin comes off to make room: the default layout already spends all nine,
  // which is the 9+3 cap being real rather than a wrinkle in this test.
  m.topbar.forEach(r => { if (r.id === 'models') r.pinned = true;
                          if (r.id === 'loffice') r.pinned = false; });
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
  let over = m.topbar.length - M.NAV_TOPBAR_PINS;
  for (let i = m.topbar.length - 1; i >= 0 && over > 0; i--) {
    if (m.topbar[i].pinned) { m.topbar[i].pinned = false; over--; }
  }
  ok(m.topbar.filter(r => r.pinned).length === M.NAV_TOPBAR_PINS, 'exactly the cap is pinned');
  ok(M.navValidate(m) === '', 'exactly 9 pinned is allowed (the boundary is inclusive)');
  ok(M.NAV_TOPBAR_MAX === 12, 'the STRIP is still Debi\'s 12');
  // …and the message must say where the other three went, or a cap that used to read
  // 12 and now reads 9 is read as loss.
  ok(e13.indexOf(String(M.NAV_TOPBAR_MRU)) >= 0 && e13.indexOf('open') >= 0,
     'the refusal names the window as well as the number: ' + e13);
  // ⚠️ THE WINDOW ITSELF: nine pins, three slots, twelve tabs, whatever you open.
  {
    let w = M.navNormalize({});
    const pins = M.navPins(w);
    ok(M.navStrip(w).length === 11, 'the strip starts at eleven (nine pins + the seed)');
    w.mru = ['goose'].concat(w.mru).slice(0, M.NAV_TOPBAR_MRU);
    w = M.navNormalize(w);
    ok(M.navStrip(w).join(',') === pins.concat(['goose','compose','voicebox']).join(','),
       'opening a tab from ⋯ takes the FIRST swappable slot, straight after the pins');
    ok(M.navStrip(w).length === M.NAV_TOPBAR_MAX, '…and the strip is now exactly twelve');
    w.mru = ['comfy'].concat(w.mru).slice(0, M.NAV_TOPBAR_MRU);
    w = M.navNormalize(w);
    ok(M.navStrip(w).indexOf('voicebox') < 0,
       '…and the least recent of the three fell off the end, back into ⋯');
    ok(M.navPins(w).join(',') === pins.join(','), '…while not one pin moved');
    // v1.5.60: an off-bar view may NEVER reach the strip — even a hand-written window
    // naming it is refused (the vector Debi hit: ⋯ click -> second Music tab).
    w = M.navNormalize({ mru: ['music'] });
    ok(M.navStrip(w).indexOf('music') < 0,
       'Music Classic never reaches the strip — a window naming it is scrubbed');
    ok(w.sidebar.concat(w.topbar).every(r => r.id !== 'music'),
       '…and it is never a row');
    // junk in the window costs the WINDOW, never the strip
    ['x', 7, null, ['logs','nope','mc','mc',{}], []].forEach(j => {
      const g = M.navNormalize({ mru: j });
      ok(M.navStrip(g).length <= M.NAV_TOPBAR_MAX && g.mru.every(i => M.navCanTab(i)),
         'a junk window (' + JSON.stringify(j) + ') still yields a legal strip');
    });
  }
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
  ok(rows.join(',') === 'mc,chat,models,compose,comfy,aider,goose,gooseui,loffice,caps,logs,help,api',
     'with NO saved layout the workspace rail renders ONE Music row: ' + rows.join(','));
  ok(rows.indexOf('api') === rows.indexOf('help') + 1,
     '…and API is DIRECTLY under Help (S32: appended in place, nothing arranged moves)');
  ok(rows.indexOf('help') === rows.indexOf('logs') + 1,
     '…and Help is DIRECTLY under Logs, which is where the roadmap put it');
  ok(/id="nav-chat" class="on"/.test(out.ws),
     'the current view is highlighted after a render (curView, not a lost class)');
  ok((out.ws.match(/onclick="navOpen\(/g) || []).length === rows.length,
     'every workspace row is clickable through navOpen');
  ok(/<span class="ico">♫<\/span> Music/.test(out.ws), 'the icons and labels come from the registry');
  // ══ ALL-DESIGNS, STRUCTURALLY (Goose UI slice) ═══════════════════════════════════
  // The ALL-DESIGNS rule asks whether a new row is correct in Editorial, the three theme
  // packs and Studio, light and dark. The answer for a NAV ROW is settled here rather
  // than by twenty-four screenshots: every design's rules select on `nav a`, `.ico` and
  // the `.on` state, so a row whose markup is IDENTICAL to a shipped row's — same
  // element, same classes, same child shape, differing only in id, glyph and label —
  // cannot render differently in any of them. (This is the v1.5.38 argument, mechanised:
  // that slice compared the new row to Aider's in 24 look-combos and found them byte-
  // identical. A row that ever needs its OWN class fails here, which is the point: it
  // then owes the twenty-four looks a real verification.)
  const shape = (id) => {
    const e = M.navEntry(id);
    const m = out.ws.match(new RegExp('<a[^>]*id="nav-' + id + '"[\\s\\S]*?</a>'));
    return m ? m[0].split(id).join('ID').split(e.label).join('LABEL')
                   .split(e.ico).join('I')
             : null;
  };
  for (const id of ['gooseui', 'goose']) {
    ok(shape(id) && shape(id) === shape('aider'),
       'the ' + id + ' row is structurally identical to the shipped Aider row — same '
       + 'element, classes and children, so every design paints it the same way');
  }
  ok(!/class="[^"]*goose/.test(out.ws),
     '…and neither goose row carries a class of its own (nothing for a design to miss)');
  // ⧉ = open as an overlay (2026-08-21). It rides the eligible workspace rows only.
  const peeks = [...out.ws.matchAll(/peekOpen\('([a-z]+)'/g)].map(m => m[1]).sort();
  // ⚠️ `music` LEAVES THIS LIST AT THE CONSOLIDATION SLICE — not because peeking Music
  // stopped being useful, but because ⧉ rides a sidebar ROW and Classic no longer has
  // one. The Music row is now a LANE (its own page in its own tab), and no lane has ever
  // been peekable: there is no in-panel view to borrow. Stated rather than left to be
  // discovered, because "the overlay lost an entry" looks like a regression otherwise.
  // ⚠️ `api` JOINS AT S32 for Help's exact reason, sharpened: "what is the base URL
  // again" and "I need a key for this app's provider form" are asked WHILE standing in
  // another surface, and the answer is two chips and a copy button.
  ok(peeks.join(',') === 'api,caps,help,models',
     'the ⧉ overlay trigger is on Models / Capabilities / Help / API: ' + peeks.join(',')
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
  // ⚠️ COMPARED THROUGH navStrip SINCE THE 9+3 RULING: the v1 default was ELEVEN PINS,
  // and today's equivalent is nine pins plus the window's two-entry seed — the same
  // eleven TABS. Comparing the pin lists alone would now fail for the right reason and
  // the wrong one at once, so the comparison is made at the level the user sees, with
  // `music` mapped through SUPERSEDED because that row IS the Music row now.
  ok(M.navStrip(M.navDefaultModel()).slice().sort().join(',')
     === M.NAV_DEFAULT_TOPBAR_V1.map(i => M.NAV_SUPERSEDED[i] || i).slice().sort().join(','),
     '…and it moves the SAME ids — nothing gained a tab, nothing lost one, so '
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
  ok(/const NAV_KEY = 'motdeck-nav';/.test(html), 'the localStorage key is v1-named');
  ok(/JSON\.stringify\(\{ v:NAV_MODEL_V, sidebar:navModel\.sidebar, topbar:navModel\.topbar, mru:navModel\.mru \|\| \[\] \}\)/.test(html),
     'the instant copy is versioned AND carries the window (an instant copy without it '
     + 'would redraw the first frame with two tabs missing, then jump)');
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
  // 15 → 14 when the light-theme ground moved out to shared --float-* tokens; the
  // scoped Reset-navigation placement rule brings the block back to 15.
  ok(sels.length === 15, 'the overlay block declares exactly 15 rules (got ' + sels.length + ')');
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
  ok(/class="cap-btn nv-reset" onclick="navReset\(\)"/.test(html)
     && />Reset navigation<\/button>/.test(html),
     'the reorderable navigation surface exposes a separately scoped Reset navigation action');

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
  ok(/function navReset\(\) \{[\s\S]{0,420}return navApply\(navDefaultModel\(\)\);/.test(html),
     'Reset navigation uses the same validate/save/rollback transaction as every row edit');
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
  // ⚠️ THE READOUT CHANGED SHAPE AT THE 9+3 RULING, and the fence with it: "max 12"
  // beside nine switches would be the lie. It names what the switches control AND where
  // the other three slots went.
  ok(/9 pinned of 9/.test(topHtml) && /the last 3 of the strip's 12/.test(topHtml),
     'the strip names its pin cap AND the window: ' + (topHtml.match(/nv-lbl">[^<]*/) || [''])[0]);
  ok(!/max 12/.test(topHtml),
     '…and no longer says "max 12" beside nine switches');
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
     && /if \(shellKnowsTab\(e\.id\) !== false && switchTab\(e\.tab, e\.id\)\) \{ navTouch\(e\.id\); return; \}/.test(open),
     'a lane asks the shell for its tab first — and never with an id the shell says it '
     + 'lacks — and records the open in the last-three window, so a sidebar row and the '
     + '⋯ menu leave the strip in the SAME state');
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
  // whether the "motdeck" handler is there. A shell built before that handler existed is
  // exactly the case this has to be true for.
  ok(/function inNativeApp\(\) \{\s*\n\s*return !!\(window\.webkit && window\.webkit\.messageHandlers\);\s*\n\}/.test(html),
     'inNativeApp is deliberately weaker than nativeShell — true even with no motdeck handler');
  ok(/function shellKnowsTab\(id\)[\s\S]{0,200}return t \? t\.indexOf\(id\) >= 0 : null;/.test(html),
     'an unknowable shell answers null, never false (a missing global is not "no tabs")');
  // the deliberate asymmetry, recorded: mc/chat/models/caps are views and do NOT jump
  // out of the panel even when the user has pinned them as tabs.
  ok(!M.navEntry('chat').prefersTab && !M.navEntry('models').prefersTab
     && !M.navEntry('caps').prefersTab && !M.navEntry('mc').prefersTab,
     'pinning a VIEW as a tab does not make its sidebar row leave the panel');
  ok(!M.navEntry('music').prefersTab,
     'Music Classic prefers NOTHING (v1.5.60): ⌘K opens the in-panel view; the tab is gone');
}

console.log('');
console.log(fails ? fails + ' failure(s) of ' + checks : 'nav panel: ' + checks + ' checks passed');
process.exit(fails ? 1 : 0);
