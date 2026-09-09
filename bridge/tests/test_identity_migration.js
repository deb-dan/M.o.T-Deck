'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const source = fs.readFileSync(path.join(ROOT, 'bridge/panel/assets/identity-migration.js'), 'utf8');
let failures = 0;
function ok(condition, message) {
  if (condition) console.log('PASS ' + message);
  else { console.error('FAIL ' + message); failures += 1; }
}

function run(initial, deny = false) {
  const values = new Map(Object.entries(initial));
  const storage = {
    getItem(key) { if (deny) throw new Error('denied'); return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { if (deny) throw new Error('denied'); values.set(key, String(value)); },
    removeItem(key) { if (deny) throw new Error('denied'); values.delete(key); },
  };
  const context = { localStorage: new Proxy(storage, {
    ownKeys() { if (deny) throw new Error('denied'); return Array.from(values.keys()); },
    getOwnPropertyDescriptor() { return { enumerable: true, configurable: true }; },
  }) };
  vm.runInNewContext(source, context);
  return values;
}

let values = run({
  'harness-theme': 'gold',
  'harness.split.on': 'true',
  'motdeck-theme': 'studio',
  'third-party': 'untouched',
});
ok(values.get('motdeck-theme') === 'studio', 'a new value wins over the legacy value');
ok(values.get('motdeck.split.on') === 'true', 'a missing dotted key migrates exactly once');
ok(!values.has('harness-theme') && !values.has('harness.split.on'), 'legacy keys are retired');
ok(values.get('third-party') === 'untouched', 'unowned keys are byte-preserved');
try { run({ 'harness-theme': 'gold' }, true); ok(true, 'storage denial cannot break page boot'); }
catch (error) { ok(false, 'storage denial escaped the fail-safe: ' + error); }

for (const file of ['index.html', 'aider.html', 'goose.html', 'oo.html']) {
  const html = fs.readFileSync(path.join(ROOT, 'bridge/panel', file), 'utf8');
  ok(html.includes('<script src="/assets/identity-migration.js"></script>'),
     file + ' loads the migration before its own boot code');
}

const office = fs.readFileSync(path.join(ROOT, 'bridge/panel/office.html'), 'utf8');
const officeHead = office.split('</head>')[0];
ok(!/<script\s+[^>]*src=/i.test(officeHead),
   'office keeps its deliberate zero-external-script boot contract');
const officeMigration = officeHead.indexOf("oldKey.indexOf('harness.')");
const officeThemeRead = officeHead.indexOf("localStorage.getItem('motdeck-theme')");
ok(officeMigration >= 0 && officeThemeRead >= 0 && officeMigration < officeThemeRead,
   'office migrates owned preferences inline before reading its new theme keys');

const comfy = fs.readFileSync(path.join(ROOT, 'bridge/panel/comfy.html'), 'utf8');
const comfyHead = comfy.split('</head>')[0];
ok(!/<script\s+[^>]*src=/i.test(comfyHead),
   'Generate keeps its deliberate zero-external-script boot contract');
const comfyMigration = comfyHead.indexOf("oldKey.indexOf('harness.')");
const comfyThemeRead = comfyHead.indexOf("localStorage.getItem('motdeck-theme')");
ok(comfyMigration >= 0 && comfyThemeRead >= 0 && comfyMigration < comfyThemeRead,
   'Generate migrates owned preferences inline before reading its new theme keys');

const compose = fs.readFileSync(path.join(ROOT, 'bridge/panel/compose.html'), 'utf8');
const composeHead = compose.split('</head>')[0];
ok(!/<script\s+[^>]*src=/i.test(composeHead),
   'Music keeps its deliberate zero-external-script boot contract');
const composeMigration = composeHead.indexOf("oldKey.indexOf('harness.')");
const composeThemeRead = composeHead.indexOf("localStorage.getItem('motdeck-theme')");
ok(composeMigration >= 0 && composeThemeRead >= 0 && composeMigration < composeThemeRead,
   'Music migrates owned preferences inline before reading its new theme keys');

process.exitCode = failures ? 1 : 0;
