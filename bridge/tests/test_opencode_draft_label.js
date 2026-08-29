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
 * This file EXTRACTS the script from app/main.swift — the shipped text, not a copy —
 * and RUNS it against a DOM fixture built from their real template, because the whole
 * safety argument is "any fence failing means it does nothing at all", and a source
 * assertion cannot prove that.
 *
 *   1. the happy path: a draft the STORE agrees is a draft gets the new label;
 *   2. the four fences, each proven to produce NO change: wrong version, missing store,
 *      an id the store does not call a draft, and a label that is not upstream's;
 *   3. it never writes: the store is byte-identical afterwards;
 *   4. the wiring: the script reaches ONLY the opencode webview, and that webview gets
 *      neither the "harness" message handler nor the shell self-description.
 *
 * LIVE PROOF (2026-08-29, not repeatable in CI so recorded here): the same extracted
 * text was injected with CDP into a SCRATCH headless-Chrome profile against the running
 * OpenCode 1.18.23 at 127.0.0.1:4096. Two boots of the real landing URL rendered
 * `draft:4180d2ef…` and `draft:67cdee65…` as "runner auto session"; the same walk with
 * the pin forced to 9.9.9 rendered "New session" both times, and the persisted store was
 * identical in both runs.
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
const A = swift.indexOf('let src = """');
ok(A > 0, 'main.swift carries the user script');
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

// ── a DOM fixture built from OpenCode's own template ────────────────────────
// Structure verified against the served bundle at the pin (index-DonkoK44.js, `R6e`):
//   div[data-tab-key="draft:<id>"] > div[data-titlebar-tab] > a > span[data-titlebar-tab-title]
function fixture({ store, version, tabs }) {
  const nodes = tabs.map(t => {
    const title = { textContent: t.text };
    return {
      key: t.key,
      getAttribute: n => (n === 'data-tab-key' ? t.key : null),
      querySelector: sel => (sel === '[data-titlebar-tab-title]' ? title : null),
      _title: title,
    };
  });
  const raw = store === null ? null : JSON.stringify(store);
  const ls = {
    _k: store === null ? [] : ['opencode.window.browser.dat:tabs'],
    get length() { return this._k.length; },
    key(i) { return this._k[i]; },
    getItem(k) { return k === 'opencode.window.browser.dat:tabs' ? raw : null; },
    setItem() { throw new Error('the relabel must never write to their store'); },
    removeItem() { throw new Error('the relabel must never write to their store'); },
  };
  const doc = {
    body: {},
    addEventListener() {},
    querySelectorAll(sel) {
      return sel === '[data-tab-key^="draft:"]'
        ? nodes.filter(n => n.key.indexOf('draft:') === 0) : [];
    },
  };
  return {
    nodes, raw,
    sandbox: {
      localStorage: ls,
      document: doc,
      JSON,
      MutationObserver: function () { this.observe = () => {}; },
      fetch: () => Promise.resolve({ json: () => Promise.resolve({ healthy: true, version }) }),
    },
  };
}

function run(fx) {
  const fn = new Function('localStorage', 'document', 'MutationObserver', 'fetch', SRC);
  fn(fx.sandbox.localStorage, fx.sandbox.document, fx.sandbox.MutationObserver,
     fx.sandbox.fetch);
  // the script arms itself behind one resolved promise
  return new Promise(r => setTimeout(r, 0));
}

const DRAFT = 'aaaaaaaa-1111-2222-3333-444444444444';
const OTHER = 'bbbbbbbb-1111-2222-3333-444444444444';
const draftStore = [{ type: 'draft', server: 'http://127.0.0.1:4096',
                      draftID: DRAFT, directory: '/w' }];

(async () => {
  // ── 1. the happy path ─────────────────────────────────────────────────────
  let fx = fixture({ store: draftStore, version: PIN,
                     tabs: [{ key: 'draft:' + DRAFT, text: 'New session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'runner auto session',
     'a draft the STORE calls a draft is relabelled');

  // A real session tab in the same strip is left completely alone — the id shape is
  // `<server>\n<href>`, never `draft:…`, so it is not even looked at.
  fx = fixture({ store: draftStore, version: PIN, tabs: [
    { key: 'draft:' + DRAFT, text: 'New session' },
    { key: 'http://127.0.0.1:4096\n/x/y', text: 'Refactor the parser' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'runner auto session'
     && fx.nodes[1]._title.textContent === 'Refactor the parser',
     '…and a real session tab beside it is untouched');

  // ── 2. the four fences: each one means NOTHING happens ────────────────────
  fx = fixture({ store: draftStore, version: '9.9.9',
                 tabs: [{ key: 'draft:' + DRAFT, text: 'New session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'New session',
     'FENCE version: a different OpenCode build is left exactly as upstream drew it');

  fx = fixture({ store: null, version: PIN,
                 tabs: [{ key: 'draft:' + DRAFT, text: 'New session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'New session',
     'FENCE store: no persisted tabs key → no relabel');

  fx = fixture({ store: draftStore, version: PIN,
                 tabs: [{ key: 'draft:' + OTHER, text: 'New session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'New session',
     'FENCE entry: an id the store does not list as a draft is not relabelled');

  fx = fixture({ store: draftStore, version: PIN,
                 tabs: [{ key: 'draft:' + DRAFT, text: 'Nouvelle session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'Nouvelle session',
     'FENCE text: only the exact upstream string is replaced (a localised build is safe)');

  // A store that is not an array at all (a future schema change) must be inert.
  fx = fixture({ store: { tabs: [] }, version: PIN,
                 tabs: [{ key: 'draft:' + DRAFT, text: 'New session' }] });
  await run(fx);
  ok(fx.nodes[0]._title.textContent === 'New session',
     'a store shape we do not recognise is inert, not a crash');

  // ── 3. it never writes ────────────────────────────────────────────────────
  // setItem/removeItem THROW in the fixture, so reaching either would have failed
  // every case above. State it as its own check so the intent survives a refactor.
  ok(SRC.indexOf('setItem') < 0 && SRC.indexOf('removeItem') < 0,
     'the script contains no write to their store at all (zero vendored bytes, zero state)');

  // ── 4. the wiring ─────────────────────────────────────────────────────────
  const oc = swift.slice(swift.indexOf('else if t.id == "opencode"'), swift.indexOf('else if t.id == "loffice"'));
  ok(oc.indexOf('openCodeDraftScript()') > 0, 'the opencode webview gets the script');
  ok(oc.indexOf('userContentController.add(self') < 0,
     '…and NOT the "harness" message handler (it is a third-party page)');
  ok(oc.indexOf('shellScript') < 0, '…and not the shell self-description either');
  ok(swift.indexOf('forMainFrameOnly: true') > 0, '…injected into the main frame only');
  ok(/injectionTime: \.atDocumentEnd[\s\S]{0,80}forMainFrameOnly/.test(
       swift.slice(swift.indexOf('func openCodeDraftScript'))),
     '…at documentEnd, so their own bundle has already defined the strip');
  ok(swift.indexOf('opencodePin()') > 0 && /guard let pin = opencodePin\(\) else \{/.test(swift),
     'no readable pin → the script is not injected AT ALL (degrade to nothing)');

  console.log(fails ? `\nFAILED ${fails} of ${checks}` : `\nopencode draft label: ${checks} checks passed`);
  process.exit(fails ? 1 : 0);
})();
