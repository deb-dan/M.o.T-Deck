/* S23 — execute the Mission Control presentation for every optional component.
   The backend matrix lives in test_partial_install_matrix.py; this is the browser
   half, derived from motdeck.yaml rather than a hand-maintained component list. */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const panel = fs.readFileSync(path.join(ROOT, 'bridge/panel/index.html'), 'utf8');
const swift = fs.readFileSync(path.join(ROOT, 'app/main.swift'), 'utf8');
const manifest = fs.readFileSync(path.join(ROOT, 'motdeck.yaml'), 'utf8');

let fails = 0, checks = 0;
function check(name, ok){ checks++; if (!ok){ fails++; console.log('FAIL ' + name); } }
function through(startText, endText){
  const start = panel.indexOf(startText), end = panel.indexOf(endText, start);
  if (start < 0 || end < start) throw new Error('missing source seam ' + startText);
  return panel.slice(start, end);
}

const componentBlock = (manifest.split(/^components:\s*$/m)[1] || '')
  .split(/^\S/m)[0] || '';
const components = [...componentBlock.matchAll(/^  ([a-z0-9_-]+):\s*$/gm)].map(m => m[1]);
const core = new Set(['hermes', 'odysseus', 'searxng']);
const optional = components.filter(name => !core.has(name));
check('the optional subject set is derived and non-empty', optional.length > 0);

const renderCard = new Function('esc', 'escAttr',
  through('function healthOf(', '\n}\n\n/* ── U15') + '\n}\n'
  + through('function cardHTML(', '\n}\n\n/* The Models pane') + '\n}\n'
  + 'return cardHTML;')(
    s => String(s == null ? '' : s), s => String(s == null ? '' : s));
for (const name of optional){
  const html = renderCard(name, {installed:false, running:false, port_up:false,
    health:'ok', port:null, pin:'', engine:''}, false, {});
  check(name + ': renders its own card', html.includes('id="card-' + name + '"'));
  check(name + ': says Not installed', html.includes('<div class="state">Not installed</div>'));
  check(name + ': offers Install',
    html.includes("planInstall('" + name + "')\">Install</button>"));
  check(name + ': does not borrow a failure/restart state',
    !html.includes('>Failed<') && !html.includes('>Restart<') && !html.includes('>Start<'));
}

const tabs = swift.slice(swift.indexOf('let tabRegistry:'), swift.indexOf('\n]', swift.indexOf('let tabRegistry:')));
for (const name of optional)
  check(name + ': remains a native navigation target while absent', tabs.includes('id: "' + name + '"'));
check('failed optional navigation has the shared visible placeholder',
  swift.includes('Not reachable yet') && swift.includes('re-select this tab') && swift.includes('&#8984;R'));

console.log('partial-install rendering: ' + (checks - fails) + '/' + checks + ' passed');
process.exit(fails ? 1 : 0);
