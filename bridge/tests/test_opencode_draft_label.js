/* OPENCODE DRAFT RELABEL (ledger S21) — the shell's user script, EXECUTED.
 *
 * THE FACT THIS SLICE EXISTS FOR. docs/research/2026-08-29-opencode-phantom-sessions.md
 * root-caused Debi's growing pile of OpenCode "New session" tabs: they are not sessions
 * (sqlite 0 rows, GET /session []). Our /opencode landing deep-links `/:dir/session`
 * with no draftId, and OpenCode 1.18.23's SPA mints and PERSISTS one draft TAB per boot.
 * Debi's ruling: leave the landing alone, and stop the drafts calling themselves work
 * she started — label them "runner auto session".
 *
 * WHY A DOM RELABEL IS NOT A PREFERENCE. A draft entry in their persisted store is
 * exactly {type,server,draftID,directory,worktree} and the strip renders it with a
 * HARDCODED i18n lookup (`title = t("command.session.new")`, bundle component `U6e`).
 * There is no store field that could carry a label — so the rendered text is the only
 * mechanism that exists, and it leaves their store byte-untouched (which is what keeps
 * their own ✕ cleanup working).
 *
 * THE DISCRIMINATOR (Debi's live bug, 2026-08-29). The first cut relabelled EVERY
 * draft, so clicking + — a deliberate new session — was branded "runner auto session"
 * too: the same lie the slice removes, pointed at the user's own work. Auto and user
 * drafts are byte-identical in the store and land on the same `/new-session?draftId=…`
 * url (their `newDraft` does both), so only the GESTURE separates them. AUTO = the one
 * draft whose id was NOT in the documentStart snapshot, becomes THIS document's own
 * `draftId`, and does so before any pointerdown/mousedown/keydown. The answer is
 * persisted under OUR key `harness.opencode.autoDrafts` so labels survive reloads and a
 * + draft is never marked later; the set is pruned to what their store still calls a
 * draft, so promotion and closing drop out on their own.
 *
 * This file EXTRACTS the script from app/main.swift — the shipped text, not a copy —
 * and RUNS it against a DOM fixture built from their real template, because the whole
 * safety argument is "any fence failing means it does nothing at all", and a source
 * assertion cannot prove that.
 *
 *   1. the happy path: the boot mint gets the new label;
 *   2. THE DISCRIMINATOR: a + draft (gesture first) keeps "New session", forever —
 *      including across a reload, and including while an auto draft sits beside it;
 *   3. the four fences, each proven to produce NO change: wrong version, missing store,
 *      an id the store does not call a draft, and a label that is not upstream's;
 *   4. it never writes to THEIRS: any opencode.* write throws in the fixture; only our
 *      own key may be written, and the tabs blob is byte-identical afterwards;
 *   5. promotion + pruning: a draft that becomes a session leaves our persisted set;
 *   6. the wiring: the script reaches ONLY the opencode webview, at documentStart, and
 *      that webview gets neither the "harness" message handler nor the shell self-desc.
 *
 * LIVE PROOF (2026-08-29, not repeatable in CI so recorded here): the same extracted
 * text was injected with CDP into a SCRATCH headless-Chrome profile against the running
 * OpenCode 1.18.23 at 127.0.0.1:4096. See docs/research/… and the builder report: boot
 * mint relabelled, + draft kept "New session", both survived a reload, promotion cleaned
 * the id out of our set, and the pin forced to 9.9.9 relabelled nothing.
 *
 * Run: node bridge/tests/test_opencode_draft_label.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const swift = fs.readFileSync(path.join(ROOT, 'app', 'main.swift'), 'utf8');
const yaml = fs.readFileSync(path.join(ROOT, 'harness.yaml'), 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

// ── extract the SHIPPED script ──────────────────────────────────────────────
// Both anchors are asserted before the slice is taken: an indexOf that returned -1
// would hand the runner the wrong text and every assertion below would be vacuous.
// The slice is anchored to the FUNCTION, not the first `let src = """` in the file —
// v1.5.66's gooseSidebarDeleteScript added an earlier one and this suite silently
// tested the wrong script for two versions. Never anchor to a literal that another
// WKUserScript can also use.
const FN = swift.indexOf('func openCodeDraftScript');
ok(FN > 0, 'main.swift carries openCodeDraftScript');
const A = swift.indexOf('let src = """', FN);
ok(A > FN, 'main.swift carries the user script');
const B = swift.indexOf('"""', A + 13);
ok(B > A, '…and it is a closed multiline literal');
let RAW = swift.slice(A + 13, B).replace(/\\\\/g, '\\');
ok(RAW.indexOf('runner auto session') > 0, "…and the label is Debi's words");

const PIN = (yaml.match(/opencode_pin:\s*"([^"]+)"/) || [])[1];
ok(!!PIN, 'harness.yaml declares build.opencode_pin');
// The Swift interpolation `\(pin)` IS the version fence, so it must be resolved to a
// real value here — leaving it literal would make every fence pass for the wrong
// reason (nothing would ever match, so nothing would ever be relabelled).
ok(RAW.indexOf('\\(pin)') > 0, 'the pin is interpolated into the script by the shell');
const SRC = RAW.split('\\(pin)').join(PIN);

const MINE = 'harness.opencode.autoDrafts';
ok(SRC.indexOf(MINE) > 0 && !/setItem\(\s*k[^A-Za-z]/.test(SRC),
   'the persisted set lives under OUR OWN key, never an opencode.* one');

// ── a DOM fixture built from OpenCode's own template ────────────────────────
// Structure verified against the served bundle at the pin (index-DonkoK44.js, `R6e`):
//   div[data-tab-key="draft:<id>"] > div[data-titlebar-tab] > a > span[data-titlebar-tab-title]
//
// The fixture is now a small WORLD rather than a snapshot: the store is mutable (the
// SPA mints into it), the url is mutable (their newDraft navigates), and gestures are
// injectable — because the thing under test is a decision made over TIME.
function world({ store, version, ours }) {
  const bag = {};
  bag['opencode.window.browser.dat:tabs'] = store === null ? undefined : JSON.stringify(store);
  if (ours !== undefined) bag[MINE] = JSON.stringify(ours);
  const ls = {
    get length() { return Object.keys(bag).length; },
    key(i) { return Object.keys(bag)[i]; },
    getItem(k) { return bag[k] === undefined ? null : bag[k]; },
    setItem(k, v) {
      if (k.indexOf('opencode.') === 0) throw new Error('wrote to THEIR store: ' + k);
      if (k !== MINE) throw new Error('wrote an unexpected key: ' + k);
      bag[k] = String(v);
    },
    removeItem(k) { throw new Error('the relabel must never remove a key: ' + k); },
  };
  const listeners = {};
  const nodes = [];
  const doc = {
    body: {},
    addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
    querySelectorAll(sel) {
      return sel === '[data-tab-key^="draft:"]'
        ? nodes.filter(n => n.key.indexOf('draft:') === 0) : [];
    },
  };
  const timers = [];
  const w = {
    bag, nodes, listeners,
    loc: { search: '' },
    tabs() { return JSON.parse(bag['opencode.window.browser.dat:tabs']); },
    mine() { return bag[MINE] === undefined ? null : JSON.parse(bag[MINE]); },
    // a rendered tab strip entry
    tab(key, text) {
      const title = { textContent: text };
      nodes.push({
        key,
        getAttribute: n => (n === 'data-tab-key' ? key : null),
        querySelector: s => (s === '[data-titlebar-tab-title]' ? title : null),
        _title: title,
      });
      return nodes[nodes.length - 1];
    },
    text(i) { return nodes[i]._title.textContent; },
    // their newDraft: push the entry, then client-navigate to /new-session?draftId=…
    mint(id) {
      const v = JSON.parse(bag['opencode.window.browser.dat:tabs']);
      v.push({ type: 'draft', server: 'http://127.0.0.1:4096', draftID: id, directory: '/w' });
      bag['opencode.window.browser.dat:tabs'] = JSON.stringify(v);
      w.loc.search = '?draftId=' + id;
      return w.tab('draft:' + id, 'New session');
    },
    // their promoteDraft: the entry is REPLACED IN PLACE by a session entry
    promote(id, title) {
      const v = JSON.parse(bag['opencode.window.browser.dat:tabs']);
      const n = v.findIndex(e => e.type === 'draft' && e.draftID === id);
      if (n !== -1) v[n] = { type: 'session', server: 'http://127.0.0.1:4096', sessionId: 'ses_x' };
      bag['opencode.window.browser.dat:tabs'] = JSON.stringify(v);
      const node = nodes.find(x => x.key === 'draft:' + id);
      if (node) { node.key = 'http://127.0.0.1:4096\n/x/y'; node._title.textContent = title; }
    },
    gesture() { (listeners['pointerdown'] || []).forEach(f => f()); },
    // run every armed timer callback n times (the script's own bounded poll)
    pump(n) { for (let i = 0; i < (n || 1); i++) timers.forEach(t => t()); },
    sandbox: {
      localStorage: ls,
      document: doc,
      location: w0 => w0,
      JSON,
      MutationObserver: function () { this.observe = () => {}; },
      fetch: () => Promise.resolve({ json: () => Promise.resolve({ healthy: true, version }) }),
      setInterval: fn => { timers.push(fn); return timers.length; },
      clearInterval: h => { timers[h - 1] = () => {}; },
    },
  };
  w.sandbox.location = w.loc;
  return w;
}

// The script is a documentStart script: it must be STARTED before the SPA mints, and
// only then does the world move. `start` returns once the version fence has resolved.
function start(w) {
  const fn = new Function('localStorage', 'document', 'location', 'MutationObserver',
                          'fetch', 'setInterval', 'clearInterval', SRC);
  const s = w.sandbox;
  fn(s.localStorage, s.document, s.location, s.MutationObserver, s.fetch,
     s.setInterval, s.clearInterval);
  return new Promise(r => setTimeout(r, 0));   // one resolved promise, then armed
}

const AUTO = 'aaaaaaaa-1111-2222-3333-444444444444';
const USER = 'bbbbbbbb-1111-2222-3333-444444444444';
const OLD  = 'cccccccc-1111-2222-3333-444444444444';
const oldDraft = { type: 'draft', server: 'http://127.0.0.1:4096',
                   draftID: OLD, directory: '/w' };

(async () => {
  // ── 1. the happy path: OUR boot mint ──────────────────────────────────────
  let w = world({ store: [], version: PIN });
  await start(w);            // documentStart: snapshot taken, no gesture yet
  w.mint(AUTO);              // their landing mint, on SPA boot
  w.pump();
  ok(w.text(0) === 'runner auto session', 'the boot mint is relabelled');
  ok(JSON.stringify(w.mine()) === JSON.stringify([AUTO]),
     '…and its id is persisted in OUR set, so the label survives a reload');

  // A real session tab in the same strip is left completely alone — the id shape is
  // `<server>\n<href>`, never `draft:…`, so it is not even looked at.
  w = world({ store: [], version: PIN });
  await start(w);
  w.mint(AUTO);
  w.tab('http://127.0.0.1:4096\n/x/y', 'Refactor the parser');
  w.pump();
  ok(w.text(0) === 'runner auto session' && w.text(1) === 'Refactor the parser',
     '…and a real session tab beside it is untouched');

  // ── 2. THE DISCRIMINATOR — Debi's bug ─────────────────────────────────────
  w = world({ store: [], version: PIN });
  await start(w);
  w.mint(AUTO);              // boot mint
  w.pump();
  w.gesture();               // she clicks…
  w.mint(USER);              // …+, which mints exactly the same shape
  w.pump(3);
  ok(w.text(1) === 'New session',
     'DISCRIMINATOR: a draft created by clicking + KEEPS upstream\'s "New session"');
  ok(w.text(0) === 'runner auto session',
     '…while the auto draft beside it stays labelled');
  ok(JSON.stringify(w.mine()) === JSON.stringify([AUTO]),
     '…and the + draft is never written into our set');

  // …and it is still immune after a restart: a NEW document, our set restored from
  // disk, both drafts already in the store (so both are in the documentStart snapshot).
  const persisted = w.mine();
  const restored = w.tabs();
  let w2 = world({ store: restored, version: PIN, ours: persisted });
  await start(w2);
  w2.tab('draft:' + AUTO, 'New session');
  w2.tab('draft:' + USER, 'New session');
  w2.pump();
  ok(w2.text(0) === 'runner auto session' && w2.text(1) === 'New session',
     'RELOAD: both verdicts survive a restart — ours relabelled, hers not');

  // The + draft is not marked even if it is the one in the url on that later boot
  // (she left the app sitting on her own composer): the snapshot already knows it.
  w2 = world({ store: restored, version: PIN, ours: persisted });
  w2.loc.search = '?draftId=' + USER;
  await start(w2);
  w2.tab('draft:' + USER, 'New session');
  w2.pump();
  ok(w2.text(0) === 'New session',
     '…and a pre-existing draft in the url is never newly marked');

  // A draft minted in the SPLIT GHOST (the other webview) changes the shared store but
  // never THIS document's url — so this document does not claim it.
  w = world({ store: [], version: PIN });
  await start(w);
  const other = w.tabs();
  other.push({ type: 'draft', server: 'http://127.0.0.1:4096', draftID: USER, directory: '/w' });
  w.bag['opencode.window.browser.dat:tabs'] = JSON.stringify(other);
  w.tab('draft:' + USER, 'New session');
  w.pump(2);
  ok(w.text(0) === 'New session' && w.mine() === null,
     'a draft that never became THIS document\'s url is not claimed as ours');

  // Drafts that predate the fix are left exactly as upstream draws them.
  w = world({ store: [oldDraft], version: PIN });
  await start(w);
  w.tab('draft:' + OLD, 'New session');
  w.pump();
  ok(w.text(0) === 'New session' && w.mine() === null,
     'a draft from before this fix is never newly marked (conservative by design)');

  // ── 3. the four fences: each one means NOTHING happens ────────────────────
  w = world({ store: [], version: '9.9.9' });
  await start(w);
  w.mint(AUTO); w.pump();
  ok(w.text(0) === 'New session' && w.mine() === null,
     'FENCE version: a different OpenCode build is left exactly as upstream drew it');

  w = world({ store: null, version: PIN });
  await start(w);
  w.loc.search = '?draftId=' + AUTO;
  w.tab('draft:' + AUTO, 'New session');
  w.pump();
  ok(w.text(0) === 'New session' && w.mine() === null,
     'FENCE store: no persisted tabs key → no relabel');

  w = world({ store: [], version: PIN });
  await start(w);
  w.loc.search = '?draftId=' + AUTO;          // url says draft, store never listed it
  w.tab('draft:' + AUTO, 'New session');
  w.pump();
  ok(w.text(0) === 'New session' && w.mine() === null,
     'FENCE entry: an id the store does not list as a draft is not relabelled');

  w = world({ store: [], version: PIN });
  await start(w);
  const n = w.mint(AUTO); n._title.textContent = 'Nouvelle session';
  w.pump();
  ok(w.text(0) === 'Nouvelle session',
     'FENCE text: only the exact upstream string is replaced (a localised build is safe)');

  // A store that is not an array at all (a future schema change) must be inert.
  w = world({ store: { tabs: [] }, version: PIN });
  await start(w);
  w.loc.search = '?draftId=' + AUTO;
  w.tab('draft:' + AUTO, 'New session');
  w.pump();
  ok(w.text(0) === 'New session' && w.mine() === null,
     'a store shape we do not recognise is inert, not a crash');

  // ── 4. it never writes to THEIRS ──────────────────────────────────────────
  // Any setItem on an `opencode.*` key THROWS in the fixture, so reaching one would
  // have failed every case above. State the byte-identity as its own check too.
  w = world({ store: [], version: PIN });
  const beforeBytes = w.bag['opencode.window.browser.dat:tabs'];
  await start(w);
  w.mint(AUTO); w.pump(2);
  const afterBytes = JSON.stringify(w.tabs().filter(e => e.draftID !== AUTO));
  ok(afterBytes === beforeBytes,
     'their tabs blob is byte-identical apart from their OWN mint (we never write it)');
  ok(SRC.indexOf('removeItem') < 0,
     'the script never removes a key from that origin at all');

  // ── 5. promotion + pruning ────────────────────────────────────────────────
  w = world({ store: [], version: PIN });
  await start(w);
  w.mint(AUTO); w.pump();
  ok(JSON.stringify(w.mine()) === JSON.stringify([AUTO]), 'the auto id is in our set');
  w.gesture();
  w.promote(AUTO, 'Fix the parser');     // she types and sends: draft → session
  w.pump(2);
  ok(w.mine() !== null && w.mine().length === 0,
     'PROMOTION: a draft that became a session drops out of our persisted set');
  ok(w.text(0) === 'Fix the parser',
     '…and its real session title is never touched');

  // closing a draft with their ✕ prunes it the same way
  w = world({ store: [], version: PIN });
  await start(w);
  w.mint(AUTO); w.pump();
  w.bag['opencode.window.browser.dat:tabs'] = '[]';
  w.nodes.length = 0;
  w.pump(2);
  ok(w.mine().length === 0, 'a draft closed with their ✕ drops out of our set too');

  // ── 6. the wiring ─────────────────────────────────────────────────────────
  const oc = swift.slice(swift.indexOf('else if t.id == "opencode"'), swift.indexOf('else if t.id == "loffice"'));
  ok(oc.indexOf('openCodeDraftScript()') > 0, 'the opencode webview gets the script');
  ok(oc.indexOf('userContentController.add(self') < 0,
     '…and NOT the "harness" message handler (it is a third-party page)');
  ok(oc.indexOf('shellScript') < 0, '…and not the shell self-description either');
  ok(swift.indexOf('forMainFrameOnly: true') > 0, '…injected into the main frame only');
  ok(/injectionTime: \.atDocumentStart[\s\S]{0,80}forMainFrameOnly/.test(
       swift.slice(swift.indexOf('func openCodeDraftScript'))),
     '…at documentStart — the snapshot must precede their SPA, or it would contain the '
     + 'very draft it exists to identify');
  ok(swift.indexOf('opencodePin()') > 0 && /guard let pin = opencodePin\(\) else \{/.test(swift),
     'no readable pin → the script is not injected AT ALL (degrade to nothing)');
  // ship.sh's additive pyyaml merge writes the snapshot's copy UNQUOTED
  // (`opencode_pin: 1.18.23`). A quote-only pin regex reads the repo on a dev Mac and
  // finds NOTHING on a fat/portable install, where the snapshot is the only
  // harness.yaml — the feature would silently not exist there.
  ok(/opencode_pin:\\s\*"\?\[0-9\]/.test(swift),
     'the pin regex accepts the SNAPSHOT\'s unquoted form as well as the repo\'s quoted one');

  console.log(fails ? `\nFAILED ${fails} of ${checks}` : `\nopencode draft label: ${checks} checks passed`);
  process.exit(fails ? 1 : 0);
})();
