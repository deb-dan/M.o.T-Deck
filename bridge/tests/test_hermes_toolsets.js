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

/* Extract a function body by brace matching.
 *
 * HONEST UPGRADE (2026-08-15): the previous three-line version treated every
 * quote as a string delimiter with no comment or nested-template handling, and
 * only worked here by luck — an apostrophe in an ordinary prose comment
 * ("Hermes's page says…") opened a string that swallowed the rest of the file,
 * and `${cond ? `<div>` : ''}` made it count an interpolation's `}` as a real
 * brace. It silently returned a TRUNCATED function rather than failing, which
 * is the worst possible failure for a test that evals what it extracts. No
 * assertion changed; the extractor just stopped being able to lie. */
function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  const stack = [];        // {t:'sq'|'dq'|'tpl'} or {t:'itp', d:<depth at ${>}
  let depth = 0, prev = '';
  for (let j = html.indexOf('{', at); j < html.length; j++) {
    const c = html[j], top = stack[stack.length - 1], bs = prev === '\\';
    const t = top && top.t;
    if (t === 'sq' || t === 'dq') {
      if (!bs && c === (t === 'sq' ? "'" : '"')) stack.pop();
    } else if (t === 'tpl') {
      if (!bs && c === '`') stack.pop();
      else if (!bs && c === '$' && html[j + 1] === '{') { stack.push({t: 'itp', d: depth}); j++; }
    } else {
      if (c === '/' && html[j + 1] === '/') { j = html.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && html[j + 1] === '*') { j = html.indexOf('*/', j) + 1; if (j < 1) break; prev = '/'; continue; }
      if (c === "'") stack.push({t: 'sq'});
      else if (c === '"') stack.push({t: 'dq'});
      else if (c === '`') stack.push({t: 'tpl'});
      else if (c === '{') depth++;
      else if (c === '}') {
        if (t === 'itp' && depth === top.d) stack.pop();
        else if (--depth === 0) return html.slice(at, j + 1);
      }
    }
    prev = bs ? '' : c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const escAttr = s => esc(s).replace(/"/g, '&quot;');
var hermesToolsSnap = null;   // the panel's module-level snapshot, under our control here
var hermesToolsIntent = {};   // our own in-session asks (see hermesToolsetSync)
var hermesToolsSummary = null;// the `check` card, null = closed
// The per-skill sub-list hangs off the `skills` row, so renderHermesTools now
// calls into it. Evaluated for REAL (never stubbed) so a break in that coupling
// shows up here instead of only at runtime. Its own behaviour is covered by
// bridge/tests/test_hermes_skills.js.
var hermesSkillsSnap = null;
var hermesSkillsOpen = false;
var hermesSkillsFilter = '';
eval(grab('hermesSkillMatch'));
eval(grab('hermesSkillsShown'));
eval(grab('hermesSkillCountNote'));
eval(grab('hermesSkillsLocked'));
eval(grab('hermesSkillsMootNote'));
eval(grab('hermesSkillsExpander'));
eval(grab('hermesSkillRows'));
eval(grab('renderHermesSkills'));
eval(grab('hermesToolsetNote'));
eval(grab('hermesToolsetExtra'));
eval(grab('hermesToolsetScopeNote'));
eval(grab('hermesToolsetScopePill'));
eval(grab('hermesToolsetSync'));
eval(grab('hermesToolsetLocked'));
eval(grab('renderHermesToolsCheck'));
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
  enabled_count: 2, total: 3, other_count: 0, platform: 'cli',
  tool_count_enabled: 6, tool_count_total: 10,
  skills: {count: 78, disabled_count: 0},
  config: {platform_toolsets_cli: ['file', 'skills'], disabled_toolsets: [], coding_context: 'auto'},
  toolsets: [
    {name: 'file', label: 'File Operations', description: 'read, write', enabled: true, tools: ['a','b','c'], tool_count: 3, platform: 'cli', platform_label: 'CLI', lever: true, config_only: false, default_off: false},
    {name: 'skills', label: 'Skills', description: 'list, view', enabled: true, tools: ['x','y','z'], tool_count: 3, platform: 'cli', platform_label: 'CLI', lever: true, config_only: false, default_off: false},
    {name: 'web', label: 'Web Search', description: 'web_search', enabled: false, tools: ['w'], tool_count: 1, platform: 'cli', platform_label: 'CLI', lever: true, config_only: false, default_off: false},
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
/* The shape moved when the intent map arrived (a failed write must also stop being
   an "ask", or the row would show a permanent out-of-sync pill for something Hermes
   was never told). The INVARIANT is unchanged and both halves are pinned. */
check('a failed toggle re-arms the switch instead of lying',
  /el\.checked = !on;/.test(html));
check('a failed toggle also drops the recorded intent (a write that never landed is not an ask)',
  /delete hermesToolsIntent\[name\];/.test(html));
check('stuck names are surfaced, not swallowed',
  html.indexOf('agent.disabled_toolsets in ~/.hermes/config.yaml') >= 0);
// feed(tag, msg) takes TWO arguments; the one-argument calls here rendered the whole
// sentence as the TAG column and a literal "undefined" as the message (2026-08-20).
check('a successful write logs to the activity feed, with a real tag AND a message',
  /feed\('hermes', 'toolsets: /.test(html));
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

// ── hermesToolsetSync: does the row disagree with what we asked for? ─────────
const T = (o) => Object.assign({name: 'web', enabled: true, drift: ''}, o);
check('agreement is silence', hermesToolsetSync(T({enabled: true}), {web: true}) === ''
  && hermesToolsetSync(T({enabled: false}), {web: false}) === '');
check('no intent and no drift ⇒ no claim (a fresh panel never accuses Hermes)',
  hermesToolsetSync(T({enabled: true}), {}) === ''
  && hermesToolsetSync(T({enabled: false}), {}) === '');
check('we asked OFF, Hermes says on', hermesToolsetSync(T({enabled: true}), {web: false}) === 'on');
check('we asked ON, Hermes says off', hermesToolsetSync(T({enabled: false}), {web: true}) === 'off');
check('the PERSISTED drift from the bridge is honoured with no client intent at all',
  hermesToolsetSync(T({enabled: false, drift: 'off'}), {}) === 'off');
check('a stale drift flag cannot fire against a row Hermes now reports ON',
  hermesToolsetSync(T({enabled: true, drift: 'off'}), {}) === '');
check('the word printed is always HERMES’s side, never ours',
  hermesToolsetSync(T({enabled: true}), {web: false}) === 'on');
check('sync is total against junk', hermesToolsetSync(null, {}) === ''
  && hermesToolsetSync({}, {}) === '' && hermesToolsetSync(T({}), null) === '');

// ── the two layers, said on the skills row ───────────────────────────────────
check('the skills row explains that the LIBRARY stays enabled — the exact confusion '
  + 'that made two apps have to be cross-read',
  /library/i.test(hermesToolsetExtra({name: 'skills'}))
  && /prompt/i.test(hermesToolsetExtra({name: 'skills'})));
check('no other row gets the sentence', hermesToolsetExtra({name: 'web'}) === ''
  && hermesToolsetExtra(null) === '');

// ── the verify card ──────────────────────────────────────────────────────────
hermesToolsSummary = null;
check('no card until Check is pressed', renderHermesToolsCheck() === '');
hermesToolsSummary = {ok: true, tools: ['read_file', 'terminal'], tool_count: 5,
  always: {toolset: 'project', tools: ['project_list', 'project_create', 'project_switch']},
  skill_index: false, skill_count: 78, excludes_mcp: true};
let card = renderHermesToolsCheck();
check('the card leads with the number Debi wants to compare against the banner',
  card.indexOf('hand the model 5 tools') >= 0);
check('the card NAMES the tools', card.indexOf('read_file') >= 0 && card.indexOf('terminal') >= 0);
check('the always-added project tools are shown too, so the list adds up to the number',
  card.indexOf('project_switch') >= 0);
check('an absent skill index says the library is untouched (both layers, again)',
  /skill index: ABSENT/.test(card) && card.indexOf('78 skills stay installed') >= 0);
hermesToolsSummary.skill_index = true;
check('a present skill index says all N skills are in the prompt',
  /skill index: PRESENT/.test(renderHermesToolsCheck()));
hermesToolsSummary.focus_override = true;
check('focus mode makes the card SAY the figures do not apply, rather than print a '
  + 'confident number Hermes will ignore',
  /coding_context is “focus”/.test(renderHermesToolsCheck())
  && renderHermesToolsCheck().indexOf('NOT what it will hand the model') >= 0);
delete hermesToolsSummary.focus_override;
check('the default posture prints no such warning',
  renderHermesToolsCheck().indexOf('NOT what it will hand') < 0);
check('the card admits it cannot see MCP tools',
  renderHermesToolsCheck().indexOf('MCP servers are not counted') >= 0);
hermesToolsSummary = {error: 'Hermes is not reachable — start it first'};
check('a failed check shows the reason instead of a made-up number',
  renderHermesToolsCheck().indexOf('not reachable') >= 0
  && renderHermesToolsCheck().indexOf('hand the model') < 0);
hermesToolsSummary = null;

// ── render wiring: pill, adopt chip, check chip ──────────────────────────────
hermesToolsSnap = {running: true, enabled_count: 1, total: 2, tool_count_enabled: 1,
  tool_count_total: 3, config: {}, skills: {count: 78},
  toolsets: [{name: 'file', label: 'File', enabled: true, tool_count: 1, drift: ''},
             {name: 'clarify', label: 'Clarify', enabled: false, tool_count: 1, drift: 'off'}]};
hermesToolsIntent = {};
let out2 = renderHermesTools();
check('a drifting row renders the pill in the existing grammar (zero new CSS)',
  out2.indexOf('cap-pill off">out of sync — Hermes says off') >= 0);
check('the group heads with the count of rows out of sync',
  out2.indexOf('1 out of sync') >= 0);
check('exactly ONE adopt chip for the whole group',
  (out2.match(/hermesToolsAdopt/g) || []).length === 1);
check('the Check chip is always offered', out2.indexOf('hermesToolsCheck(this)') >= 0);
// HONEST MOVE: this sentence used to sit on the preset row and said only "what
// HERMES reports". It now sits in the group header and is strictly stronger — it
// also NAMES the platform these switches govern, which is the fact whose absence
// sent Debi to cross-check a second app.
check('the group says out loud that the switches show HERMES’s answer',
  /Every switch shows what HERMES reports/.test(out2));
check('...and NAMES the platform it controls',
  out2.indexOf('<b>cli</b> platform') >= 0
  && /the one this chat runs on/.test(out2));
check('...and still NAMES the trap (Hermes’s own page fetches once on open, '
    + 'SkillsPage.tsx:155-174, and never live-refreshes)',
  /Skills → TOOLSETS/.test(out2) && /never refreshes itself/.test(out2));
// The shell reloads that webview whenever our config generation has moved and a Hermes
// surface is on screen — on a tab switch (maybeReloadStaleHermes) AND on a poll while it
// is already visible (updateHermesGenTimer), which is what covers split view. The copy
// may therefore promise the automatic reload for BOTH, and the only case left uncovered
// is a Hermes dashboard open outside this app, which it must still name.
check('...and now promises the automatic reload, not a tab switch you have to make',
  /MOT Deck reloads that tab for you/i.test(out2));
check('...covering split view explicitly, and still naming the one case it cannot reach',
  /split view/i.test(out2) && /outside<\/i> this app/i.test(out2) && /⌘R/.test(out2));
check('the defaults preset chip no longer promises "everything"',
  out2.indexOf('Everything back on') < 0
  && out2.indexOf(">Hermes's defaults<") >= 0);
check('...and says which toolsets it deliberately leaves off',
  /video analysis/i.test(out2) && /one row at a time/.test(out2));
hermesToolsSnap.toolsets[1].drift = '';
out2 = renderHermesTools();
check('no drift ⇒ no pill and no adopt chip',
  out2.indexOf('out of sync') < 0 && out2.indexOf('hermesToolsAdopt') < 0);
check('Check stays available even when everything agrees',
  out2.indexOf('hermesToolsCheck(this)') >= 0);
hermesToolsIntent = {clarify: true};
check('our own in-session ask is enough to surface a disagreement, with no bridge '
  + 'drift flag at all', renderHermesTools().indexOf('Hermes says off') >= 0);
hermesToolsIntent = {};

check('adopt RE-READS and never writes (the switches are already Hermes’s answer)',
  grab('hermesToolsAdopt').indexOf('refreshHermesTools') >= 0
  && grab('hermesToolsAdopt').indexOf("method:'POST'") < 0
  && grab('hermesToolsAdopt').indexOf('/api/hermes/toolsets\'') < 0);
check('adopt clears our claim rather than suppressing the bridge’s persisted one',
  /hermesToolsIntent = \{\};/.test(grab('hermesToolsAdopt')));
check('Check reads the dedicated summary endpoint, live',
  grab('hermesToolsCheck').indexOf("fetch('/api/hermes/toolsets/summary')") >= 0);
check('Check re-reads the rows too, so the card and the switches are never one '
  + 'refresh apart', grab('hermesToolsCheck').indexOf('refreshHermesTools') >= 0);
check('a write drops a stale verify card instead of leaving a confident wrong number',
  grab('hermesToolsWrite').indexOf('hermesToolsSummary = null') >= 0);
check('the preset path deliberately records NO client intent (the preset membership '
  + 'lives once, in the bridge)',
  grab('hermesToolsPreset').indexOf('hermesToolsIntent') < 0);

// ═══════════════════════════════════════════════════════════════════════════
// NON-LEVER ROWS SAY WHAT THEY ARE. One list from Hermes carries three kinds of
// row and only the cli ones reach the model in this lane; a row that does not
// must not sit in the grid looking identical to the ones that do.
// ═══════════════════════════════════════════════════════════════════════════
check('a cli row gets no scope pill and no scope note',
  hermesToolsetScopePill({name: 'file', lever: true}) === ''
  && hermesToolsetScopeNote({name: 'file', lever: true}) === '');
check('the config-only stt row is named for what it is — Hermes’s speech-to-text '
  + 'switch, not a prompt toolset',
  hermesToolsetScopePill({name: 'stt', lever: false, config_only: true})
    === 'not a prompt toolset'
  && /speech-to-text/.test(hermesToolsetScopeNote({name: 'stt', lever: false, config_only: true}))
  && /saves nothing here/.test(hermesToolsetScopeNote({name: 'stt', lever: false, config_only: true})));
check('an other-platform row NAMES the platform it controls and says the model '
  + 'here never gets its tools',
  hermesToolsetScopePill({name: 'discord', lever: false, platform: 'discord', platform_label: 'Discord'})
    === 'Discord only'
  && /Discord platform, not this chat lane/.test(
       hermesToolsetScopeNote({name: 'discord', lever: false, platform: 'discord', platform_label: 'Discord'}))
  && /never gets these tools/.test(
       hermesToolsetScopeNote({name: 'discord', lever: false, platform: 'discord', platform_label: 'Discord'})));
check('a missing platform_label degrades to the raw platform, never to blank',
  hermesToolsetScopePill({name: 'd', lever: false, platform: 'discord'}) === 'discord only');
check('scope helpers are total against junk',
  hermesToolsetScopePill(null) === '' && hermesToolsetScopeNote(null) === ''
  && hermesToolsetScopePill({lever: false}) === 'other platform only');

// the row renders both, and the skills two-layer sentence still wins on its own row
hermesToolsSnap = JSON.parse(JSON.stringify(SNAP));
hermesToolsSnap.other_count = 2;
hermesToolsSnap.toolsets.push(
  {name: 'stt', label: 'Speech-to-Text', description: 'voice', enabled: true,
   tools: [], tool_count: 0, platform: 'cli', platform_label: 'CLI',
   lever: false, config_only: true, default_off: false},
  {name: 'discord', label: 'Discord', description: 'fetch messages', enabled: true,
   tools: ['discord_send'], tool_count: 1, platform: 'discord',
   platform_label: 'Discord', lever: false, config_only: false, default_off: true});
const hs = renderHermesTools();
check('both non-lever rows STILL RENDER (hiding a switch Hermes shows would be its '
  + 'own lie)', hs.indexOf('Speech-to-Text') >= 0 && hs.indexOf('>Discord<') >= 0);
check('each non-lever row carries its pill in the existing faint grammar',
  hs.indexOf('not a prompt toolset</span>') >= 0
  && hs.indexOf('Discord only</span>') >= 0);
check('the header says how many rows were left out of the counts',
  /2 more rows below belong to other Hermes surfaces/.test(hs));
check('the skills row still gets its two-layer sentence, not a scope note',
  /skill library in/.test(hs));
check('a lever row carries NO scope pill', (hs.match(/only<\/span>/g) || []).length === 1);
hermesToolsSnap.other_count = 0;
check('no non-lever rows ⇒ no "left out" sentence',
  renderHermesTools().indexOf('belong to other Hermes surfaces') < 0);

// the Check card names the lane it counted
hermesToolsSnap = JSON.parse(JSON.stringify(SNAP));
hermesToolsSummary = {ok: true, platform: 'cli', tool_count: 12,
  tools: ['read_file', 'terminal'], always: {toolset: 'project', tools: ['project_list']},
  skill_index: false, skill_count: 78, excludes_mcp: true};
const hc = renderHermesTools();
check('the Check card names the lane it counted',
  /cli lane/.test(hc) && /Counted for the cli lane only/.test(hc));
check('...and still says MCP tools are not in the number',
  /MCP servers are not counted/.test(hc));
hermesToolsSummary = null;

console.log();
console.log(fails.length ? ('FAILED: ' + fails.join(', ')) : 'all checks passed');
process.exit(fails.length ? 1 : 0);
