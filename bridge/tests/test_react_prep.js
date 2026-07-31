// TASK B / TASK A unit test — pure helpers from the sandboxed artifact renderer
// (bridge/panel/index.html): prepReact() (import stripping + root-component detection)
// and the resizable-pane clamp math (clampArtSplit / clampSessionsWidth).
// Mirrors the functions verbatim. Offline, no deps. Run: node bridge/tests/test_react_prep.js

// ---- mirror of prepReact() ----
function prepReact(src){
  let s = String(src || '');
  const named = new Set();
  const grab = (g) => g.split(',').forEach(x => { x = x.trim().replace(/\s+as\s+\w+$/, ''); if (x) named.add(x); });
  s = s.replace(/import\s+React\s*,\s*\{([^}]*)\}\s*from\s*['"]react['"]\s*;?/g, (m, g) => { grab(g); return ''; });
  s = s.replace(/import\s*\{([^}]*)\}\s*from\s*['"]react['"]\s*;?/g, (m, g) => { grab(g); return ''; });
  s = s.replace(/import\s+React\s+from\s*['"]react['"]\s*;?/g, '');
  s = s.replace(/import\s+\*\s+as\s+React\s+from\s*['"]react['"]\s*;?/g, '');
  s = s.replace(/import\s+ReactDOM\s*,?\s*(?:\{[^}]*\})?\s*from\s*['"]react-dom(?:\/client)?['"]\s*;?/g, '');
  s = s.replace(/import\s*\{[^}]*\}\s*from\s*['"]react-dom(?:\/client)?['"]\s*;?/g, '');

  let defaultName = null, m;
  if ((m = s.match(/export\s+default\s+function\s+([A-Za-z_$][\w$]*)/))){
    defaultName = m[1];
    s = s.replace(/export\s+default\s+function\s+([A-Za-z_$][\w$]*)/, 'function $1');
  } else if ((m = s.match(/export\s+default\s+class\s+([A-Za-z_$][\w$]*)/))){
    defaultName = m[1];
    s = s.replace(/export\s+default\s+class\s+([A-Za-z_$][\w$]*)/, 'class $1');
  } else if (/export\s+default\s+function\s*\(/.test(s)){
    defaultName = '__ArtifactRoot__';
    s = s.replace(/export\s+default\s+function\s*\(/, 'function __ArtifactRoot__(');
  } else if (/export\s+default\s+class\b/.test(s)){
    defaultName = '__ArtifactRoot__';
    s = s.replace(/export\s+default\s+class\b/, 'class __ArtifactRoot__');
  } else if ((m = s.match(/export\s+default\s+([A-Za-z_$][\w$]*)\s*;?/))){
    defaultName = m[1];
    s = s.replace(/export\s+default\s+[A-Za-z_$][\w$]*\s*;?/, '');
  } else if (/export\s+default\s+/.test(s)){
    defaultName = '__ArtifactRoot__';
    s = s.replace(/export\s+default\s+/, 'const __ArtifactRoot__ = ');
  }
  s = s.replace(/export\s+default\s+/g, '');
  s = s.replace(/export\s+(?=(?:function|class|const|let|var)\b)/g, '');

  let root = null;
  if (/\b(?:function|class|const|let|var)\s+App\b/.test(s)) root = 'App';
  else if (defaultName) root = defaultName;
  else {
    const comps = [];
    const re = /(?:function|class)\s+([A-Z][\w$]*)|(?:const|let|var)\s+([A-Z][\w$]*)\s*=/g;
    let mm; while ((mm = re.exec(s))) comps.push(mm[1] || mm[2]);
    if (comps.length) root = comps[comps.length - 1];
  }

  const inject = named.size ? ('const { ' + [...named].join(', ') + ' } = React;\n') : '';
  return { code: inject + s, root: root };
}

// ---- mirror of the clamp helpers ----
function clampArtSplit(f){ f = parseFloat(f); if (!isFinite(f)) return 0.5; return Math.max(0.25, Math.min(0.75, f)); }
function clampSessionsWidth(w){ w = parseFloat(w); if (!isFinite(w)) return 204; return Math.max(180, Math.min(420, w)); }

let pass = 0, fail = 0;
function eq(name, got, want){
  if (got === want) { pass++; }
  else { fail++; console.error('FAIL: ' + name + '\n  got:  ' + JSON.stringify(got) + '\n  want: ' + JSON.stringify(want)); }
}
function ok(name, cond){ if (cond) pass++; else { fail++; console.error('FAIL: ' + name); } }

// ---- root detection across the shapes the spec requires ----
eq('function App() → root App', prepReact('function App(){ return null; }').root, 'App');
eq('export default function App', prepReact('export default function App(){ return null; }').root, 'App');
eq('const App = () => root App', prepReact('const App = () => null;').root, 'App');
eq('export default function Widget (no App)', prepReact('export default function Widget(){ return null; }').root, 'Widget');
eq('export default Widget trailing', prepReact('function Widget(){ return null; }\nexport default Widget;').root, 'Widget');
eq('App preferred over default export', prepReact('function App(){return null;}\nexport default function Other(){return null;}').root, 'App');
eq('last top-level component when no App/default',
   prepReact('function Cloud(){return null;}\nfunction Sky(){return null;}').root, 'Sky');
eq('anonymous default function → synthetic root',
   prepReact('export default function(){ return null; }').root, '__ArtifactRoot__');
eq('anonymous default arrow → synthetic root',
   prepReact('export default () => null;').root, '__ArtifactRoot__');
eq('class default export', prepReact('export default class Board extends React.Component{}').root, 'Board');
eq('no component at all → null', prepReact('const x = 1;\nconsole.log(x);').root, null);

// ---- import stripping keeps OTHER component definitions (full-tree mount) ----
const multi = prepReact(
  "import React, { useState } from 'react';\n" +
  "import ReactDOM from 'react-dom/client';\n" +
  "function Cloud(){ return <div className='p-2'>c</div>; }\n" +
  "function App(){ const [n,setN]=useState(0); return <Cloud/>; }\n" +
  "export default App;\n");
ok('react import stripped', !/from ['"]react['"]/.test(multi.code));
ok('react-dom import stripped', !/from ['"]react-dom/.test(multi.code));
ok('helper component Cloud kept', /function Cloud\(/.test(multi.code));
ok('App kept', /function App\(/.test(multi.code));
ok('named hook rebound from React', /const \{ useState \} = React;/.test(multi.code));
ok('no export keyword left', !/\bexport\b/.test(multi.code));
eq('multi-file root = App', multi.root, 'App');

// aliased import is out of scope but must not crash + must strip the line
const aliased = prepReact("import { useState as us } from 'react';\nfunction App(){ return null; }");
ok('aliased react import line removed', !/from ['"]react['"]/.test(aliased.code));
ok('aliased hook rebinds base name (documented limit)', /const \{ useState \} = React;/.test(aliased.code));

// named export declarations kept (export stripped, decl remains)
const namedExp = prepReact('export function Header(){return null;}\nexport const App = () => null;');
ok('named export function kept', /function Header\(/.test(namedExp.code));
ok('named export const kept', /const App = /.test(namedExp.code));
eq('named-export App detected as root', namedExp.root, 'App');

// ---- clamp math ----
eq('artsplit default (junk)', clampArtSplit('abc'), 0.5);
eq('artsplit clamp low', clampArtSplit(0.1), 0.25);
eq('artsplit clamp high', clampArtSplit(0.9), 0.75);
eq('artsplit passthrough', clampArtSplit(0.5), 0.5);
eq('artsplit string parse', clampArtSplit('0.6'), 0.6);
eq('sessions default (junk)', clampSessionsWidth('x'), 204);
eq('sessions clamp low', clampSessionsWidth(50), 180);
eq('sessions clamp high', clampSessionsWidth(900), 420);
eq('sessions passthrough', clampSessionsWidth(300), 300);
eq('sessions string parse', clampSessionsWidth('250px'), 250);

console.log((fail ? 'FAILED ' : 'OK ') + pass + '/' + (pass + fail) + ' assertions passed');
process.exit(fail ? 1 : 0);
