/* THE APP-LAYER SOURCE VIEW, for the node-side tests — the JS twin of
 * bridge/appsrc.py. Read that file's header for WHY this exists; the short version is
 * that the app layer stopped being one file on 2026-08-28 (app.py became a facade over
 * bridge/core/*.py + bridge/routers/*.py) and `readFileSync('bridge/app.py')` therefore
 * stopped meaning "the bridge's app layer".
 *
 * ⚠️ THE FILE LIST IS NOT DUPLICATED HERE, ON PURPOSE. Two hand-maintained ordered
 * lists of the same modules is one list that silently rots: the day a slab is added to
 * the python side and forgotten here, the four node suites that pin cross-file
 * invariants (panel marker vs bridge ATTACH_MARKER, the frame types this lane branches
 * on, HIDEABLE_SOURCES) would go quietly green against a source that no longer
 * contains the code. So FILES is PARSED out of bridge/appsrc.py, which is the single
 * source of truth, and a parse that finds nothing throws rather than returning "".
 */
const fs = require('fs');
const path = require('path');

const BRIDGE = path.resolve(__dirname, '..');

function files() {
  const src = fs.readFileSync(path.join(BRIDGE, 'appsrc.py'), 'utf8');
  const m = src.match(/^FILES[^=]*=\s*\(([\s\S]*?)\)\s*$/m);
  if (!m) throw new Error('_appsrc.js: could not find FILES in bridge/appsrc.py');
  const out = [];
  const re = /["']([^"']+\.py)["']/g;
  let g;
  while ((g = re.exec(m[1])) !== null) out.push(g[1]);
  if (!out.length) throw new Error('_appsrc.js: FILES in bridge/appsrc.py is empty');
  return out;
}

const FACADE_SENTINEL = '# ══ FACADE RE-EXPORTS';

function appSource() {
  const parts = [];
  files().forEach((rel, i) => {
    let s = fs.readFileSync(path.join(BRIDGE, rel), 'utf8');
    if (rel === 'app.py' && s.indexOf(FACADE_SENTINEL) >= 0) {
      s = s.split(FACADE_SENTINEL)[0];
    }
    if (i > 0) {
      s = s.split('\n').filter(l => l.indexOf('from __future__ import') !== 0).join('\n');
    }
    parts.push('# ══════ appsrc: bridge/' + rel + ' ══════');
    parts.push(s);
  });
  return parts.join('\n') + '\n';
}

module.exports = { appSource, files };
