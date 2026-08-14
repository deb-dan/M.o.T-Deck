/* Panel-side unit test for the Hermes toolset-trimming group's pure helpers.
 *
 * The functions are EXTRACTED from bridge/panel/index.html by name (never copied),
 * so a rename or an edit in the panel trips this test instead of drifting from it.
 *
 * The two things worth pinning here are honesty properties, not cosmetics:
 *   hermesToolsetLocked — a switch that cannot possibly work must be reported as
 *     locked (Hermes stopped, or agent.coding_context=focus, where upstream returns
 *     its own toolset list BEFORE the config list is read).
 *   hermesToolsetNote  — the `skills` row must say it also carries the whole skill
 *     index, because that is the single biggest prefill lever and a bare "3 tools"
 *     would badly understate it.
 *
 * Run: node bridge/tests/test_hermes_toolsets.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');

let fails = [];
function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + name);
  if (!cond) fails.push(name);
}

function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  let i = html.indexOf('{', at), depth = 0, inStr = null, prev = '';
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (inStr) { if (c === inStr && prev !== '\\') inStr = null; }
    else if (c === '"' || c === "'" || c === '`') inStr = c;
    else if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return html.slice(at, j + 1); }
    prev = c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const escAttr = s => esc(s).replace(/"/g, '&quot;');
var hermesToolsSnap = null;   // the panel's module-level snapshot, under our control here
eval(grab('hermesToolsetNote'));
eval(grab('hermesToolsetLocked'));
eval(grab('renderHermesTools'));

// ── hermesToolsetNote ────────────────────────────────────────────────────────
check('plural tool count', hermesToolsetNote({name: 'web', tool_count: 2}, {}) === '2 tools');
check('singular is not "1 tools"', hermesToolsetNote({name: 'clarify', tool_count: 1}, {}) === '1 tool');
check('zero tools reads as 0 tools', hermesToolsetNote({name: 'x', tool_count: 0}, {}) === '0 tools');
check('missing count degrades to 0', hermesToolsetNote({name: 'x'}, {}) === '0 tools');
check('junk entry does not throw', hermesToolsetNote(null, null) === '0 tools');
check('the skills row names the skill index — the biggest lever',
  hermesToolsetNote({name: 'skills', tool_count: 3}, {skills: {count: 78}})
    === '3 tools + the whole skill index (78 skills)');
check('skills row without a count still names the index',
  hermesToolsetNote({name: 'skills', tool_count: 3}, {}) === '3 tools + the skill index');
check('skills row with a zero count does not print "(0 skills)"',
  hermesToolsetNote({name: 'skills', tool_count: 3}, {skills: {count: 0}})
    === '3 tools + the skill index');
check('a non-skills row never mentions skills',
  hermesToolsetNote({name: 'memory', tool_count: 1}, {skills: {count: 78}}).indexOf('skill') < 0);

// ── hermesToolsetLocked (fail-CLOSED: no snapshot ⇒ locked) ──────────────────
check('no snapshot ⇒ locked', hermesToolsetLocked(null) !== '');
check('Hermes stopped ⇒ locked, and says to start it',
  hermesToolsetLocked({running: false}).indexOf('start Hermes') >= 0);
check('focus mode ⇒ locked, and names the config key',
  hermesToolsetLocked({running: true, focus_override: true}).indexOf('coding_context') >= 0);
check('running + auto ⇒ NOT locked',
  hermesToolsetLocked({running: true, focus_override: false}) === '');
check('stopped beats focus in the message (start it first)',
  hermesToolsetLocked({running: false, focus_override: true}).indexOf('start Hermes') >= 0);

// ── renderHermesTools ────────────────────────────────────────────────────────
const SNAP = {
  running: true, source: 'probe', focus_override: false, restart_required: false,
  enabled_count: 2, total: 3, tool_count_enabled: 6, tool_count_total: 10,
  skills: {count: 78, disabled_count: 0},
  config: {platform_toolsets_cli: ['file', 'skills'], disabled_toolsets: [], coding_context: 'auto'},
  toolsets: [
    {name: 'file', label: 'File Operations', description: 'read, write', enabled: true, tools: ['a','b','c'], tool_count: 3},
    {name: 'skills', label: 'Skills', description: 'list, view', enabled: true, tools: ['x','y','z'], tool_count: 3},
    {name: 'web', label: 'Web Search', description: 'web_search', enabled: false, tools: ['w'], tool_count: 1},
  ],
};
const out = renderHermesTools();   // reads the module-level snapshot
check('no snapshot ⇒ renders nothing at all (the group is absent, not empty)',
  out === '');

hermesToolsSnap = SNAP;
const h = renderHermesTools();
check('group carries the stable id the refresh swaps on', h.indexOf('id="caps-hermes-tools"') >= 0);
check('one switch per toolset', (h.match(/type="checkbox"/g) || []).length === 3);
// `\schecked\s` matches only the ATTRIBUTE — the onchange's `this.checked,` has no
// leading whitespace and no trailing space, so it cannot inflate the count.
check('enabled rows are checked, disabled are not',
  (h.match(/\schecked\s/g) || []).length === 2);
check('both preset chips rendered', h.indexOf("hermesToolsPreset('minimal'") >= 0
  && h.indexOf("hermesToolsPreset('all'") >= 0);
check('aggregate counts shown', h.indexOf('2/3 toolsets on') >= 0
  && h.indexOf('6 of 10 tools in the prompt') >= 0);
check('the skills row is flagged as the biggest lever', h.indexOf('biggest lever') >= 0);
check('skill count reaches the row', h.indexOf('78 skills') >= 0);
check('the "applies to the next chat" promise is on screen',
  h.indexOf('next chat') >= 0);
check('nothing is disabled when unlocked', h.indexOf('disabled') < 0);
check('per-row error slots exist for the inline failure path',
  h.indexOf('id="hts-file-err"') >= 0 && h.indexOf('id="hts-preset-err"') >= 0);

hermesToolsSnap = Object.assign({}, SNAP, {running: false});
const hoff = renderHermesTools();
check('stopped: the group still renders (so the section is not a hole)', hoff !== '');
check('stopped: NO switches are offered', hoff.indexOf('type="checkbox"') < 0);
check('stopped: the configured list is still reported from disk',
  hoff.indexOf('configured: file, skills') >= 0);
hermesToolsSnap = Object.assign({}, SNAP, {running: false, config: {platform_toolsets_cli: null, disabled_toolsets: [], coding_context: 'auto'}});
check('stopped + never configured says so rather than showing an empty list',
  renderHermesTools().indexOf('not configured yet') >= 0);

hermesToolsSnap = Object.assign({}, SNAP, {focus_override: true});
const hfoc = renderHermesTools();
check('focus mode: switches are rendered but DISABLED', (hfoc.match(/disabled/g) || []).length >= 3);
check('focus mode: the reason is on screen', hfoc.indexOf('coding_context') >= 0);

hermesToolsSnap = Object.assign({}, SNAP, {
  config: {platform_toolsets_cli: ['file'], disabled_toolsets: ['web'], coding_context: 'auto'}});
check('a toolset forced off by agent.disabled_toolsets is MARKED (it can never be '
  + 'enabled from here, so the switch must not look effective)',
  renderHermesTools().indexOf('forced off in config') >= 0);

// ── `needs setup in Hermes` pill (2026-08-14h) ────────────────────────────────
// Mirrors UPSTREAM's own signal: the row's `configured:false`, which is what Hermes's
// Skills→TOOLSETS page prints "Setup needed" from (web/src/pages/SkillsPage.tsx:606).
// The bridge fails OPEN, so a row without the flag can never grow a scary pill.
hermesToolsSnap = Object.assign({}, SNAP, {toolsets: [
  {name: 'browser', label: 'Browser', description: 'automation', enabled: false,
   tools: ['b'], tool_count: 1, needs_setup: true},
  {name: 'file', label: 'File Operations', description: 'read, write', enabled: true,
   tools: ['a'], tool_count: 1, needs_setup: false},
]});
const hsetup = renderHermesTools();
check('a toolset upstream reports unconfigured gets a faint "needs setup in Hermes" pill',
  hsetup.indexOf('needs setup in Hermes') >= 0);
check('the pill uses the existing quiet .cap-pill off grammar (zero new CSS)',
  /<span class="cap-pill off">needs setup in Hermes<\/span>/.test(hsetup));
check('exactly ONE row carries it (a configured toolset does not)',
  (hsetup.match(/needs setup in Hermes/g) || []).length === 1);
check('the pill is shown even though the switch is OFF — knowing before you enable '
  + 'it is the whole point (upstream gates its own caption on enabled &&)',
  hsetup.indexOf('needs setup in Hermes') >= 0);
check('the pill does not disable the switch (Hermes accepts the write either way)',
  hsetup.indexOf('id="hts-browser"') >= 0
  && !/id="hts-browser"[^>]*disabled/.test(hsetup));
// NEGATIVE: a row with no needs_setup key renders no pill at all
hermesToolsSnap = Object.assign({}, SNAP, {toolsets: [
  {name: 'file', label: 'File', description: '', enabled: true, tools: ['a'], tool_count: 1},
]});
check('a row with no needs_setup field grows no pill (fail open, end to end)',
  renderHermesTools().indexOf('needs setup') < 0);

hermesToolsSnap = Object.assign({}, SNAP, {toolsets: []});
check('an empty catalog renders the group without throwing',
  typeof renderHermesTools() === 'string');

// ── wiring / negatives ───────────────────────────────────────────────────────
check('the write path is the bridge endpoint, not Hermes directly',
  html.indexOf("fetch('/api/hermes/toolsets'") >= 0);
check('a failed toggle re-arms the switch instead of lying',
  /if \(!ok && el\) el\.checked = !on;/.test(html));
check('stuck names are surfaced, not swallowed',
  html.indexOf('agent.disabled_toolsets in ~/.hermes/config.yaml') >= 0);
check('a successful write logs to the activity feed', /feed\('hermes toolsets: /.test(html));
const writeFn = grab('hermesToolsWrite');
check('the panel NEVER sends a bare empty list (the preset/name forms are the only '
  + 'two callers, and both are non-empty by construction)',
  writeFn.indexOf('enabled: []') < 0);
check('a transient refresh failure keeps the group in the DOM instead of deleting '
  + 'it (an empty render would leave nothing for the next refresh to swap)',
  /if \(!hermesToolsSnap\) \{ hermesToolsSnap = prev; return false; \}/.test(html));
check('the render function touches no chat state (it is a caps-only surface)',
  grab('renderHermesTools').indexOf('sendChat') < 0
  && grab('renderHermesTools').indexOf('hermesSid') < 0);

console.log();
console.log(fails.length ? ('FAILED: ' + fails.join(', ')) : 'all checks passed');
process.exit(fails.length ? 1 : 0);
