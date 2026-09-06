// CANVAS unit test — pure editor logic used by the editable-artifact mode
// (bridge/panel/index.html): split clamp, kind→CodeMirror-mode map, default
// save filename. Mirror copies (house pattern, like test_rewrite_cdns.js).
// Run: node bridge/tests/test_canvas_logic.js

// --- mirror of clampCanvasSplit() ---
function clampCanvasSplit(f){ f = parseFloat(f); if (!isFinite(f)) return 0.5; return Math.max(0.2, Math.min(0.8, f)); }
// --- mirror of cmModeFor() ---
function cmModeFor(kind, filename){
  if (kind === 'html') return 'htmlmixed';
  if (kind === 'svg') return 'xml';
  if (kind === 'react') return 'jsx';
  if (kind === 'js') return 'javascript';
  if (kind === 'json') return 'application/json';
  if (kind === 'markdown') return 'markdown';
  if (kind === 'code'){
    const ext = ((filename || '').toLowerCase().match(/\.([a-z0-9]+)$/) || [])[1] || '';
    const M = { py:'python', ts:'javascript', js:'javascript', css:'css', scss:'css',
                yaml:'yaml', yml:'yaml', xml:'xml', json:'application/json', md:'markdown' };
    return (ext in M) ? M[ext] : null;
  }
  return null;
}
// --- mirror of canvasSaveName() ---
function canvasSaveName(filename, kind){
  if (filename && /\.[a-z0-9]+$/i.test(filename)) return filename;
  const E = { html:'html', svg:'svg', react:'jsx', js:'js', markdown:'md',
              mermaid:'mmd', csv:'csv', json:'json' };
  return 'artifact.' + (E[kind] || 'txt');
}

let pass = 0, fail = 0;
function eq(name, got, want){
  if (got === want) { pass++; }
  else { fail++; console.error('FAIL: ' + name + '\n  got:  ' + got + '\n  want: ' + want); }
}

// ---- clampCanvasSplit ----
eq('mid passes', clampCanvasSplit(0.5), 0.5);
eq('low clamps to 0.2', clampCanvasSplit(0.05), 0.2);
eq('high clamps to 0.8', clampCanvasSplit(0.95), 0.8);
eq('string parses', clampCanvasSplit('0.33'), 0.33);
eq('NaN → default 0.5', clampCanvasSplit('nope'), 0.5);
eq('undefined → default 0.5', clampCanvasSplit(undefined), 0.5);
eq('Infinity → default 0.5', clampCanvasSplit(Infinity), 0.5);
eq('negative clamps to 0.2', clampCanvasSplit(-1), 0.2);

// ---- cmModeFor ----
eq('html → htmlmixed', cmModeFor('html', 'page.html'), 'htmlmixed');
eq('svg → xml', cmModeFor('svg', 'a.svg'), 'xml');
eq('react → jsx', cmModeFor('react', 'App.jsx'), 'jsx');
eq('js → javascript', cmModeFor('js', 'x.js'), 'javascript');
eq('json → application/json', cmModeFor('json', 'x.json'), 'application/json');
eq('markdown → markdown', cmModeFor('markdown', 'n.md'), 'markdown');
eq('mermaid → plain (null)', cmModeFor('mermaid', 'f.mmd'), null);
eq('csv → plain (null)', cmModeFor('csv', 'd.csv'), null);
eq('code .py → python', cmModeFor('code', 'run.py'), 'python');
eq('code .yaml → yaml', cmModeFor('code', 'motdeck.yaml'), 'yaml');
eq('code .css → css', cmModeFor('code', 'a.css'), 'css');
eq('code unknown ext → plain', cmModeFor('code', 'Makefile'), null);
eq('code no filename → plain', cmModeFor('code', ''), null);
eq('unknown kind → plain', cmModeFor('image', 'p.png'), null);

// ---- canvasSaveName ----
eq('existing filename kept', canvasSaveName('page.html', 'html'), 'page.html');
eq('uppercase ext kept', canvasSaveName('App.JSX', 'react'), 'App.JSX');
eq('no filename html → artifact.html', canvasSaveName('', 'html'), 'artifact.html');
eq('no filename react → artifact.jsx', canvasSaveName(null, 'react'), 'artifact.jsx');
eq('no filename markdown → artifact.md', canvasSaveName('', 'markdown'), 'artifact.md');
eq('no filename mermaid → artifact.mmd', canvasSaveName('', 'mermaid'), 'artifact.mmd');
eq('no filename code → artifact.txt', canvasSaveName('', 'code'), 'artifact.txt');
eq('extensionless filename → synthesized', canvasSaveName('Makefile', 'code'), 'artifact.txt');

console.log(pass + ' passed, ' + fail + ' failed');
process.exit(fail ? 1 : 0);
