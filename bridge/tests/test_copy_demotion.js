/* S15/S16 — information may move out of the standing layout, but it may not vanish. */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..', '..');
const panel = fs.readFileSync(path.join(root, 'bridge/panel/index.html'), 'utf8');
const office = fs.readFileSync(path.join(root, 'bridge/panel/office.html'), 'utf8');
const aider = fs.readFileSync(path.join(root, 'bridge/panel/aider.html'), 'utf8');
const goose = fs.readFileSync(path.join(root, 'bridge/panel/goose.html'), 'utf8');
const help = fs.readFileSync(path.join(root, 'docs/USER-EXPLAINERS.md'), 'utf8');

const failures = [];
let passes = 0;
function check(name, condition) {
  if (condition) { passes++; console.log('PASS ' + name); }
  else failures.push(name);
}

check('Aider keeps workspace, reattach and grace facts on titled chips',
  /title="Aider edits only inside this workspace/.test(aider)
  && /title="Reload reattaches/.test(aider)
  && /title="With no tab attached/.test(aider));
check('Aider full behavior has a Help destination',
  /Full behavior: MOT Deck → Help → Aider/.test(aider) && /^## Aider$/m.test(help));
check('Goose keeps workspace, runner, reattach and grace facts on titled chips',
  /title="Goose edits only inside this workspace/.test(goose)
  && /title="This lane uses MOT Deck's local runner/.test(goose)
  && /title="Reload reattaches/.test(goose)
  && /title="With no tab attached/.test(goose));
check('Goose full behavior has a Help destination',
  /Full behavior: MOT Deck → Help → Goose CLI/.test(goose)
  && /Goose CLI/.test(help));
check('Changeset cards keep no-write and undo guarantees on status chips',
  /Nothing is written until you choose Apply/.test(office)
  && /Apply saves a checkpoint first/.test(office)
  && /undoable ✓/.test(office));
check('Model paths move to Finder actions with the exact path in the title',
  (panel.match(/reveal\.textContent = 'Show in Folder'/g) || []).length === 2
  && /reveal\.title = m\.path/.test(panel)
  && /reveal\.title = a\.path/.test(panel));
check('Apply/reload preserves its full consequence in the hover disclosure',
  /av\.note \? av\.note \+ ' ' : ''/.test(panel)
  && /Restart the runner on this model/.test(panel));
check('Metal overcommit override remains documented after leaving the dialog',
  /MOT_DECK_ALLOW_METAL_OVERCOMMIT=1/.test(help)
  && !/Set \$\{esc\(a\.refuse\.override_env\)\}=1/.test(panel));
check('Long navigation/design explanations have a dedicated Help section',
  /^## Navigation and appearance$/m.test(help));
check('Capabilities tool taxonomy remains in Help',
  /^### Capabilities → Tools: three different kinds of tool$/m.test(help));
check('Commit pins are demoted to a checkmark but retain the exact pin as title',
  /isCommitPin \? '✓'/.test(panel)
  && /title="\$\{escAttr\(pinLabel \+ ' ' \+ pinFull\)\}"/.test(panel));
check('Chat has one normal status readout and transient notices replace it',
  /id="chat-note" hidden/.test(panel)
  && /note\.hidden = !text/.test(panel)
  && /caps\.hidden = !!text/.test(panel));
check('Every transient chat status uses the shared replacement boundary',
  (panel.match(/getElementById\('chat-note'\)/g) || []).length === 1
  && /chatNotice\(phase\)/.test(panel)
  && /chatNotice\('model ejected/.test(panel));

if (failures.length) {
  failures.forEach(x => console.error('FAIL ' + x));
  console.error(`${failures.length} failure(s), ${passes} passed`);
  process.exit(1);
}
console.log(`copy-demotion contracts passed (${passes})`);
