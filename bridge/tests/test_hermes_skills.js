/* Panel-side unit test for the PER-SKILL trimming sub-list.
 *
 * The functions are EXTRACTED from bridge/panel/index.html by name (never
 * copied), so a rename or an edit in the panel trips this test rather than
 * drifting from it.
 *
 * The properties worth pinning are honesty + non-destructiveness, not cosmetics:
 *   · a blank filter can never HIDE a row (a filter that hides rows and a bulk
 *     action that writes "the shown" are a dangerous pair if the filter lies);
 *   · the group SAYS the writes are global — upstream's own toggle route has no
 *     platform, so a skill switched off here is off on every Hermes surface;
 *   · with the skills TOOLSET off the list is moot and says so, rather than
 *     presenting switches as if they changed the current prompt;
 *   · Hermes stopped ⇒ every switch is disabled, never a live-looking control
 *     with nothing to write to.
 *
 * Run: node bridge/tests/test_hermes_skills.js   (from repo root)
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

/* Extract a function body by brace matching. NESTED TEMPLATE LITERALS are the
   reason this is not the three-line version: these renderers interpolate
   `${cond ? `<div>` : ''}`, and a naive scanner that treats the inner backtick
   as closing the outer string then counts the interpolation's `}` as a real
   brace and truncates the function halfway. A small mode stack handles it. */
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
    } else {                                  // code, or inside a ${ … }
      // COMMENTS FIRST. An apostrophe in an ordinary prose comment
      // (“Hermes's page says…”) would otherwise open a string that swallows the
      // rest of the file — which is exactly how this scanner first over-ran.
      if (c === '/' && html[j + 1] === '/') { j = html.indexOf('\n', j); if (j < 0) break; prev = '\n'; continue; }
      if (c === '/' && html[j + 1] === '*') { j = html.indexOf('*/', j) + 1; if (j < 1) break; prev = '/'; continue; }
      if (c === "'") stack.push({t: 'sq'});
      else if (c === '"') stack.push({t: 'dq'});
      else if (c === '`') stack.push({t: 'tpl'});
      else if (c === '{') depth++;
      else if (c === '}') {
        if (t === 'itp' && depth === top.d) stack.pop();   // end of ${ … }
        else if (--depth === 0) return html.slice(at, j + 1);
      }
    }
    prev = bs ? '' : c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
const escAttr = s => esc(s).replace(/"/g, '&quot;');
var hermesToolsSnap = null;
var hermesSkillsSnap = null;
var hermesSkillsOpen = false;
var hermesSkillsFilter = '';
eval(grab('hermesSkillMatch'));
eval(grab('hermesSkillArg'));
eval(grab('hermesSkillsShown'));
eval(grab('hermesSkillCountNote'));
eval(grab('hermesSkillsLocked'));
eval(grab('hermesSkillsMootNote'));
eval(grab('hermesSkillsExpander'));
eval(grab('hermesSkillRows'));
eval(grab('renderHermesSkills'));

const S = (name, enabled, category, description, extra) =>
  Object.assign({name, enabled, category, description, provenance: 'bundled',
                 lane_off: false}, extra || {});
const SNAP = {
  running: true, scope: 'global', total: 4, enabled_count: 3, in_prompt: 3,
  lane_off: [], categories: ['documents', 'design'],
  skills: [
    S('pdf', true, 'documents', 'Work with PDF files'),
    S('xlsx', true, 'documents', 'Spreadsheets'),
    S('canvas-design', true, 'design', 'Posters and art'),
    S('veriff-knowledge', false, 'company', 'Internal context'),
  ],
};
const TOOLS_ON = {running: true, skills: {count: 78},
                  toolsets: [{name: 'skills', enabled: true}]};

// ── hermesSkillMatch: the filter must never hide something it should not ─────
check('a blank filter matches everything',
      SNAP.skills.every(s => hermesSkillMatch(s, '')));
check('whitespace-only is still blank',
      hermesSkillMatch(SNAP.skills[0], '   ') === true);
check('null/undefined query matches everything',
      hermesSkillMatch(SNAP.skills[0], null) && hermesSkillMatch(SNAP.skills[0], undefined));
check('matches on name', hermesSkillMatch(SNAP.skills[0], 'pdf') === true);
check('matches on name case-insensitively', hermesSkillMatch(SNAP.skills[0], 'PDF') === true);
check('matches on a substring, not just a prefix',
      hermesSkillMatch(SNAP.skills[2], 'design') === true);
check('matches on category',
      hermesSkillMatch(SNAP.skills[1], 'documents') === true);
check('matches on description',
      hermesSkillMatch(SNAP.skills[1], 'spreadsheet') === true);
check('a non-match is a non-match', hermesSkillMatch(SNAP.skills[0], 'zzz') === false);
check('the query is trimmed before matching',
      hermesSkillMatch(SNAP.skills[0], '  pdf  ') === true);
// Totality: a junk row must be a non-match, never an exception that would blank
// the whole list mid-keystroke.
[null, undefined, 0, '', 7, [], {}, {name: 1}, {description: null}].forEach(j => {
  let ok = true;
  try { hermesSkillMatch(j, 'pdf'); } catch (e) { ok = false; }
  check('hermesSkillMatch total on ' + JSON.stringify(j), ok);
});
check('a junk row never falsely MATCHES a real query',
      hermesSkillMatch(null, 'pdf') === false && hermesSkillMatch(7, 'pdf') === false);

// ── hermesSkillArg: a quote in a skill name must not kill its switch ────────
check('an ordinary name is untouched', hermesSkillArg('pdf') === 'pdf');
check("an apostrophe is escaped for the JS string, not stripped",
      hermesSkillArg("don't") === "don\\'t");
check('a backslash is escaped FIRST (order matters)',
      hermesSkillArg('a\\b') === 'a\\\\b' && hermesSkillArg("a\\'b") === "a\\\\\\'b");
check('hermesSkillArg is total', hermesSkillArg(null) === '' && hermesSkillArg(undefined) === ''
      && hermesSkillArg(7) === '7');
(function () {
  const row = hermesSkillRows([S("don't-do-this", true, 'x', '')], '');
  const m = /onchange="toggleHermesSkill\('([^']*(?:\\'[^']*)*)'/.exec(row);
  check('a quoted name still produces a syntactically valid onchange', !!m);
  // The real proof: the emitted handler must PARSE. A raw apostrophe would end
  // the string early and leave a switch that silently does nothing on click.
  let ok = true;
  try {
    const attr = /onchange="([^"]*)"/.exec(row)[1]
      .replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<');
    new Function('toggleHermesSkill', 'this_', attr.replace(/this/g, 'this_'));
  } catch (e) { ok = false; }
  check('…and the handler body actually parses as JS', ok);
})();

// ── hermesSkillsShown ───────────────────────────────────────────────────────
check('shown with no filter is the whole list',
      hermesSkillsShown(SNAP, '').length === 4);
check('shown filters', hermesSkillsShown(SNAP, 'documents').map(s => s.name)
      .join(',') === 'pdf,xlsx');
check('shown keeps payload order',
      hermesSkillsShown(SNAP, '').map(s => s.name).join(',')
      === SNAP.skills.map(s => s.name).join(','));
check('shown on a missing snapshot is empty, not an error',
      hermesSkillsShown(null, '').length === 0 && hermesSkillsShown({}, '').length === 0);
check('shown on a junk snapshot is empty',
      hermesSkillsShown({skills: 'nope'}, '').length === 0);

// ── the count line ──────────────────────────────────────────────────────────
check('the count reads the LANE number (in_prompt), not the enabled count',
      hermesSkillCountNote(SNAP, TOOLS_ON) === '3 of 4 skills in the prompt');
check('a lane-hidden skill makes the two numbers differ, and the smaller wins',
      hermesSkillCountNote({skills: SNAP.skills, total: 4, enabled_count: 3,
                            in_prompt: 2}, TOOLS_ON) === '2 of 4 skills in the prompt');
check('before the list is fetched the count falls back to the toolset snapshot',
      hermesSkillCountNote(null, TOOLS_ON) === '78 installed');
check('with neither, the count says nothing rather than lying',
      hermesSkillCountNote(null, null) === '');

// ── locks + the moot note ───────────────────────────────────────────────────
check('Hermes stopped is a lock',
      hermesSkillsLocked({running: false}) === 'start Hermes to change its skills');
check('no snapshot at all is a lock', !!hermesSkillsLocked(null));
check('Hermes running is not a lock', hermesSkillsLocked(TOOLS_ON) === '');
// Deliberately NOT a lock: the skills toolset being off makes the list moot for
// the CURRENT prompt, but the write still lands and shapes the next one.
check('the skills toolset being off is NOT reported as a lock',
      hermesSkillsLocked({running: true, toolsets: [{name: 'skills', enabled: false}]}) === '');
check('…it produces the moot NOTE instead',
      hermesSkillsMootNote({name: 'skills', enabled: false})
        .indexOf('none of these are in the model’s prompt right now') > 0);
check('the moot note is silent when the toolset is on',
      hermesSkillsMootNote({name: 'skills', enabled: true}) === '');
check('the moot note is silent on a missing row', hermesSkillsMootNote(null) === '');

// ── the expander ────────────────────────────────────────────────────────────
hermesSkillsOpen = false;
let exp = hermesSkillsExpander(TOOLS_ON);
check('the expander uses the existing .cap-exp grammar (zero new CSS)',
      exp.indexOf('class="cap-exp"') > 0);
check('collapsed shows a right-pointing marker', exp.indexOf('▸ per-skill') > 0);
check('the expander carries the count before anything is fetched',
      exp.indexOf('78 installed') > 0);
hermesSkillsOpen = true;
check('open shows a down marker',
      hermesSkillsExpander(TOOLS_ON).indexOf('▾ per-skill') > 0);

// ── the sub-list ────────────────────────────────────────────────────────────
hermesSkillsOpen = false;
check('a CLOSED list renders nothing at all (no 78-row string per refresh)',
      renderHermesSkills({name: 'skills', enabled: true}) === '');
hermesSkillsOpen = true;
hermesSkillsSnap = null;
hermesToolsSnap = TOOLS_ON;
check('open-but-unfetched says it is loading rather than "no skills"',
      renderHermesSkills({name: 'skills', enabled: true}).indexOf('loading skills…') > 0);
hermesSkillsSnap = SNAP;
let out = renderHermesSkills({name: 'skills', enabled: true});
check('the sub-list uses the existing .cap-sub grammar',
      out.indexOf('class="cap-sub" id="hsk-list"') > 0);
check('every skill gets a row', SNAP.skills.every(s => out.indexOf('>' + s.name + '<') > 0));
check('one switch per skill, and exactly the enabled ones are checked',
      out.split('type="checkbox"').length - 1 === 4
      && out.split('checkbox" checked').length - 1 === 3);
check('the switch reuses the existing .cap-sw grammar (zero new CSS)',
      out.split('class="cap-sw"').length - 1 === 4);
check('the group NAMES the global write scope in the description',
      out.indexOf('off on <b>every</b> Hermes surface') > 0);
check('the group carries the Hermes-page staleness warning',
      out.indexOf('loads its list once when it opens and never refreshes') > 0);
// Same promise as the toolset group: the shell reloads the Hermes webview whenever our
// config generation has moved and a Hermes surface is on screen — including split view,
// where a poll (updateHermesGenTimer) does the work no tab switch could. The one case it
// cannot reach is a Hermes dashboard open outside this app, and the copy names it.
check('...and now promises the automatic reload, split view included',
      /MOT Deck reloads that tab for you/i.test(out) && /split view/i.test(out));
check('...and still names the one case ⌘R is on the user',
      /outside<\/i> this app/i.test(out) && out.indexOf('⌘R') > 0);
check('the shown count is rendered', out.indexOf('4 shown') > 0);
check('the defaults chip is present and named after HERMES, not "everything"',
      out.indexOf(">Hermes's defaults<") > 0);
check('the bulk chip says it only touches the shown rows',
      out.indexOf('>Turn off the shown<') > 0
      && out.indexOf('never the ones the filter is hiding') > 0);
check('the filter box exists and reuses .cap-inp',
      out.indexOf('class="cap-inp" id="hsk-q"') > 0);
check('the filter box is pre-filled from the persisted filter state',
      out.indexOf('value=""') > 0);
check('the toolset-on case shows NO moot note',
      out.indexOf('none of these are in the model’s prompt right now') < 0);
out = renderHermesSkills({name: 'skills', enabled: false});
check('the toolset-off case DOES show the moot note',
      out.indexOf('none of these are in the model’s prompt right now') > 0);

// filter state survives a re-render (renderHermesTools replaces the whole group
// on every write, so an in-flight filter must not be lost)
hermesSkillsFilter = 'documents';
out = renderHermesSkills({name: 'skills', enabled: true});
check('a persisted filter narrows the re-rendered list',
      out.indexOf('>pdf<') > 0 && out.indexOf('>canvas-design<') < 0);
check('a persisted filter is echoed back into the input',
      out.indexOf('value="documents"') > 0);
check('the shown count follows the filter', out.indexOf('2 shown') > 0);
hermesSkillsFilter = 'zzzz';
check('a filter matching nothing says so rather than rendering an empty box',
      renderHermesSkills({name: 'skills', enabled: true})
        .indexOf('no skill matches that filter') > 0);
hermesSkillsFilter = '';

// lane-hidden pill
hermesSkillsSnap = {...SNAP, in_prompt: 2, lane_off: ['xlsx'],
                    skills: SNAP.skills.map(s => s.name === 'xlsx'
                                            ? {...s, lane_off: true} : s)};
out = renderHermesSkills({name: 'skills', enabled: true});
check('a lane-hidden skill carries a pill naming the config key',
      out.indexOf('skills.platform_disabled.cli') > 0);
check('the pill uses the existing faint grammar (zero new CSS)',
      out.indexOf('class="cap-pill off">not in this lane') > 0);
check('only the hidden row gets the pill',
      out.split('not in this lane').length === 2);
hermesSkillsSnap = SNAP;

// Hermes stopped ⇒ every switch disabled, and the chips too
hermesToolsSnap = {running: false, skills: {count: 78}};
out = renderHermesSkills({name: 'skills', enabled: true});
check('with Hermes stopped every skill switch is disabled',
      out.split('type="checkbox"').length - 1 === 4
      && out.split('disabled').length - 1 >= 4 + 2);
check('with Hermes stopped both action chips are disabled too',
      /Hermes's defaults/.test(out) && out.indexOf('cap-btn" style="margin-left:8px" disabled') > 0);
hermesToolsSnap = TOOLS_ON;

// a probe error is shown, and never mistaken for "this library is empty"
hermesSkillsSnap = {skills: [], total: 0, enabled_count: 0, in_prompt: 0,
                    error: 'connection refused'};
out = renderHermesSkills({name: 'skills', enabled: true});
check('a failed load shows the error, not an empty list',
      out.indexOf('connection refused') > 0 && out.indexOf('no skill matches') < 0);
hermesSkillsSnap = SNAP;

// ── wiring / negatives read out of the panel source ─────────────────────────
check('the list is fetched LAZILY (only inside the expand handler)',
      /toggleHermesSkillsList[\s\S]{0,400}loadHermesSkills\(\)/.test(html));
check('the normal Capabilities render does NOT probe skills',
      html.indexOf('await loadHermesSkills()') > 0
      && !/function renderHermesTools\(\)[\s\S]{0,3000}loadHermesSkills/.test(html));
check('the filter re-renders ONLY the rows (so the input keeps focus)',
      /function hermesSkillsSetFilter[\s\S]{0,400}getElementById\('hsk-rows'\)/.test(html)
      && !/function hermesSkillsSetFilter[\s\S]{0,400}refreshHermesToolsRender/.test(html));
check('a write is serialised (no interleaved half-applied bulk)',
      html.indexOf('if (hermesSkillsBusy) return false;') > 0);
check('a failed toggle puts the switch back',
      html.indexOf('if (!ok && el) el.checked = !on;') > 0);
check('nothing in the skills path touches the toolset intent map',
      !/function hermesSkillsWrite[\s\S]{0,1200}hermesToolsIntent/.test(html));
check('the bulk-off refuses cleanly when nothing shown is on',
      html.indexOf("'nothing shown is on'") > 0);

console.log('');
console.log(fails.length ? ('FAILED: ' + fails.join('; ')) : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
