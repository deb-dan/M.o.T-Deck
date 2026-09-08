/* v1.5.90 uninstall/reset surface: source-level safety and UI preservation fences. */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge/panel/index.html'), 'utf8');
const js = fs.readFileSync(path.join(ROOT, 'bridge/panel/assets/storage-controls.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'bridge/panel/assets/storage-controls.css'), 'utf8');
let checks = 0, failures = 0;
function ok(value, message) { checks++; if (!value) { failures++; console.error('FAIL ' + message); } }

ok(html.includes('/assets/storage-controls.css') && html.includes('/assets/storage-controls.js'),
   'the external storage assets are loaded (the monolithic panel does not absorb the feature)');
ok(/onclick="openStorageManager\(\)"[^>]*>⌫</.test(html),
   'Mission Control has one discoverable installations/storage entry');
ok(/Choose optional tools…<\/button>/.test(html) && /function setupOptionalTools\(\)/.test(html),
   'first-launch core setup links directly to the optional-tool selector');
ok(/if \(c\.installed && !isRunner\)[\s\S]{0,220}openStorageManager/.test(html),
   'installed component cards offer a scoped Uninstall preview');
ok(html.includes('id="cs-more"') && html.includes('Delete all chats in this lane'),
   'the sessions header offers a clear-all action without replacing Refresh or New');
ok(js.includes('/api/storage/runtime/plan') && js.includes('/api/storage/runtime/apply'),
   'runtime removal is a preview/apply protocol');
ok(js.includes('/api/storage/chats/plan') && js.includes('/api/storage/chats/apply'),
   'chat clearing is a preview/apply protocol');
ok(js.includes('/api/storage/optional') && js.includes('/api/storage/optional/install'),
   'optional tools use one allowlisted install queue rather than ad-hoc shell text');
ok(js.includes('/api/storage/reset/plan') && js.includes('/api/storage/reset/apply'),
   'factory reset and full uninstall use identity-bound preview/apply routes');
ok(js.includes("? 'RESET' : 'UNINSTALL'") && js.includes("confirm.value !== phrase"),
   'the broad reset tiers require an exact typed confirmation after preview');
ok(js.includes('External/shared stores remain') && js.includes('Repositories and external/shared stores remain'),
   'the reset surface names its preservation boundary instead of implying total erasure');
ok(js.includes('Reset unavailable') && js.includes('capability.factory_reset'),
   'factory reset is visibly disabled when the installed FAT seed cannot reproduce the live release');
ok(js.includes('textContent') && !js.includes('innerHTML'),
   'dynamic paths and upstream titles are rendered as text, never HTML');
ok(js.includes('space returns only after Trash is emptied'),
   'the UI does not claim that a recoverable Trash move immediately frees disk');
ok(js.includes("plan.bytes === null") && js.includes('Size is not scanned'),
   'broad reset preview omits an expensive whole-root size scan instead of freezing the bridge');
ok(js.includes("chatPane.mode === 'hermes'") && js.includes("'odysseus'"),
   'clear-all targets Hermes only in Hermes lane and Odysseus for Chat/Agent');
ok(css.includes('#storage-dlg') && !/(^|\n)\s*(button|\.card|#chat-inputrow|#cs-resize)\s*\{/.test(css),
   'new CSS is scoped away from existing cards, composer and resize handles');

// Preserve the exact composer DOM order and its single-shell contract while adding the menu.
const inputRow = html.slice(html.indexOf('<div id="chat-inputrow">'), html.indexOf('<!-- ══ THE AUDIO-MODE SWITCH'));
ok(inputRow.indexOf('id="chat-attach"') < inputRow.indexOf('id="chat-input"')
   && inputRow.indexOf('id="chat-input"') < inputRow.indexOf('id="chat-talk"')
   && inputRow.indexOf('id="chat-talk"') < inputRow.indexOf('id="chat-send"'),
   'attachment, textarea, mic and send retain their established DOM order');
ok(/html\[data-chrome="studio"\] #chat-input \{[\s\S]{0,120}background:transparent; border:0; border-radius:0/.test(html),
   'late Studio chrome cannot repaint the textarea as a nested field');

if (failures) { console.error(`${failures} failure(s) of ${checks}`); process.exit(1); }
console.log(`storage controls: ${checks} checks passed`);
