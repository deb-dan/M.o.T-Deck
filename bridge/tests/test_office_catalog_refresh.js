const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'panel', 'office.html'), 'utf8');
let pass = 0, fails = [];
function check(name, ok) { if (ok) pass++; else fails.push(name); }
function eq(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) pass++;
  else fails.push(`${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}
function grab(name) {
  const at = src.indexOf('function ' + name + '(');
  if (at < 0) throw new Error(name + ' not found');
  let depth = 0, quote = '', escaped = false;
  for (let i = src.indexOf('{', at); i < src.length; i++) {
    const c = src[i];
    if (quote) {
      if (!escaped && c === quote) quote = '';
      escaped = !escaped && c === '\\';
      if (c !== '\\') escaped = false;
      continue;
    }
    if (c === "'" || c === '"' || c === '`') { quote = c; continue; }
    if (c === '{') depth++;
    if (c === '}' && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error(name + ' unbalanced');
}

eval(grab('agentCatalogPlan'));
eq('no server fingerprint does nothing', agentCatalogPlan('old', '', true, false), 'none');
eq('same fingerprint preserves session', agentCatalogPlan('same', 'same', true, false), 'none');
eq('session-free first observation is adopted', agentCatalogPlan('', 'new', false, false), 'adopt');
eq('session-free changed observation is adopted', agentCatalogPlan('old', 'new', false, false), 'adopt');
eq('legacy session adopts its first fingerprint instead of guessing it is stale',
   agentCatalogPlan('', 'new', true, false), 'adopt');
eq('changed idle session rolls over', agentCatalogPlan('old', 'new', true, false), 'rollover');
eq('changed busy session defers', agentCatalogPlan('old', 'new', true, true), 'defer');

const boot = grab('boot');
check('boot reads the stored catalog fingerprint', /LS_AGENT_CATALOG/.test(boot));
check('boot awaits model/catalog probe before history restore',
      /await aiRefreshModel\(\); await agentRestoreHistory\(\)/.test(boot));
const refresh = grab('aiRefreshModel');
check('model refresh awaits catalog reconciliation', /await agentProbe\(aiModel\)/.test(refresh));
const reconcile = grab('agentCatalogReconcile');
check('transient registration state is not a rollover input',
      !/mcpRegistered|mcpInSync/.test(reconcile));
const rollover = grab('agentCatalogRollover');
check('rollover forgets only local live/stored binding',
      /removeItem\(LS_AGENT_SID\)/.test(rollover)
      && /removeItem\(LS_AGENT_STORED\)/.test(rollover));
check('rollover never deletes Hermes history', !/fetch\(|delete/.test(rollover));
check('rollover tells the user previous history remains', /remains in Hermes history/.test(rollover));

console.log(`office catalog refresh: ${pass} passed, ${fails.length} failed`);
fails.forEach(x => console.log('FAIL', x));
process.exit(fails.length ? 1 : 0);
