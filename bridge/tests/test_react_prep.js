// Execute the shipped helpers; the expectations below are independent fixtures.
const fs = require('node:fs'), path = require('node:path');
const {extractFunction} = require('./_panel_source');
const source = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const names = ['prepReact', 'clampArtSplit', 'clampSessionsWidth'];
const {prepReact,clampArtSplit,clampSessionsWidth} = new Function(names.map(n => extractFunction(source, n)).join('\n')
  + '; return {' + names.join(',') + '};')();

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

// Existing single-file expressions must remain executable after export normalization.
for (const input of ['export default props => props.value;', 'export default React.memo(() => 7);']) {
  const result = prepReact(input);
  eq('expression default gets a synthetic root', result.root, '__ArtifactRoot__');
  const component = new Function('React', result.code + '; return ' + result.root)({memo: fn => fn});
  eq('expression default remains executable', component({value:7}), 7);
}

// ---- clamp math ----
eq('artsplit default (junk)', clampArtSplit('abc'), 0.42);
eq('artsplit clamp low', clampArtSplit(0.1), 0.25);
eq('artsplit clamp high', clampArtSplit(0.9), 0.75);
eq('artsplit passthrough', clampArtSplit(0.5), 0.5);
eq('artsplit string parse', clampArtSplit('0.6'), 0.6);
eq('sessions default (junk)', clampSessionsWidth('x'), 204);
eq('sessions clamp low', clampSessionsWidth(50), 120);
eq('sessions clamp high', clampSessionsWidth(900), 560);
eq('sessions passthrough', clampSessionsWidth(300), 300);
eq('sessions string parse', clampSessionsWidth('250px'), 250);

console.log((fail ? 'FAILED ' : 'OK ') + pass + '/' + (pass + fail) + ' assertions passed');
process.exit(fail ? 1 : 0);
