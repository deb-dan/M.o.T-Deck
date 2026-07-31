// ARTIFACT COVERAGE V2 unit test — artifactKind() additions (mermaid / csv / json) +
// the fenced-block wiring (LANG_EXT + worthy rule) in bridge/panel/index.html.
// Mirrors the panel implementations (established test pattern). Offline, no deps.
// Run: node bridge/tests/test_artifact_kind_v2.js

// --- mirrors of the v2 sniffs ---
const MERMAID_RE = /^(graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|mindmap|journey|timeline|gitGraph|quadrantChart)\b/;
function sniffMermaid(t){ return MERMAID_RE.test(t); }
function sniffJson(t){
  if (!/^[\[{]/.test(t)) return false;
  try { const v = JSON.parse(t); return typeof v === 'object' && v !== null; }
  catch (e) { return false; }
}
function sniffCsv(t){
  const lines = t.split(/\r?\n/).filter(l => l.trim() !== '').slice(0, 10);
  if (lines.length < 2) return false;
  const tabs = (lines[0].match(/\t/g) || []).length;
  const commas = (lines[0].match(/,/g) || []).length;
  const d = (tabs > 0 && tabs >= commas) ? '\t' : ',';
  const n = lines[0].split(d).length - 1;
  if (n < 1) return false;
  return lines.every(l => l.split(d).length - 1 === n);
}
// --- mirror of artifactKind() (v2) ---
function artifactKind(filename, content){
  const fn = (filename || '').toLowerCase().trim();
  const ext = (fn.match(/\.([a-z0-9]+)$/) || [])[1] || '';
  const c = content || '';
  const EXT = {
    html:'html', htm:'html', svg:'svg', jsx:'react', tsx:'react', js:'js', mjs:'js', cjs:'js',
    md:'markdown', markdown:'markdown', mdown:'markdown',
    mmd:'mermaid', mermaid:'mermaid', csv:'csv', tsv:'csv', pdf:'pdf',
    png:'image', jpg:'image',
    py:'code', ts:'code', go:'code', rs:'code', sh:'code',
    json:'json', yaml:'code', yml:'code', css:'code', sql:'code'
  };
  let kind = EXT[ext] || '';
  const importsReact = /import\s+[\s\S]*?from\s*['"]react(?:-dom)?(?:\/[\w-]+)?['"]/.test(c)
                     || /require\(\s*['"]react['"]\s*\)/.test(c)
                     || /\bReactDOM\b|\bReact\.(?:createElement|Component|useState|Fragment)\b/.test(c);
  const hasJsxTag = /<[A-Z][A-Za-z0-9]*[\s/>]/.test(c);
  if (!kind){
    const t = c.replace(/^\s+/, '');
    if (/^<svg[\s>]/i.test(t)) kind = 'svg';
    else if (/^<!doctype html/i.test(t) || /^<html[\s>]/i.test(t) || /<\/(?:div|body|head|p|span|section|main|h[1-6])>/i.test(t)) kind = 'html';
    else if (sniffMermaid(t)) kind = 'mermaid';
    else if (sniffJson(t)) kind = 'json';
    else if (sniffCsv(t)) kind = 'csv';
    else if (importsReact || hasJsxTag) kind = 'react';
    else if (/^#{1,6}\s|\n#{1,6}\s|```|^\s*[-*]\s+\S/m.test(t)) kind = 'markdown';
    else kind = 'code';
  }
  if ((kind === 'js' || kind === 'html') && (importsReact || hasJsxTag)) kind = 'react';
  return kind;
}
// --- mirror of the fenced-block wiring (LANG_EXT subset + worthy rule) ---
const LANG_EXT = { html:'html', svg:'svg', jsx:'jsx', javascript:'js', js:'js', python:'py',
  json:'json', mermaid:'mmd', mmd:'mmd', csv:'csv', tsv:'tsv', md:'md' };
function classify(lang, code){
  const ext = LANG_EXT[lang] || '';
  const synth = 'artifact.' + (ext || 'txt');
  const kind = artifactKind(ext ? synth : '', code);
  const lines = code.split('\n').length;
  const big = lines >= 8 || code.length >= 300;
  const worthy = kind === 'html' || kind === 'svg' || kind === 'react'
              || kind === 'mermaid' || kind === 'csv' || kind === 'json'
              || (kind === 'js' && big) || (kind === 'code' && big);
  return { kind, worthy };
}

let pass = 0, fail = 0;
function eq(name, got, want){
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) pass++;
  else { fail++; console.error('FAIL: ' + name + '\n  got:  ' + g + '\n  want: ' + w); }
}

// ---- extension routes ----
eq('.mmd ext', artifactKind('flow.mmd', ''), 'mermaid');
eq('.mermaid ext', artifactKind('d.mermaid', ''), 'mermaid');
eq('.csv ext', artifactKind('data.csv', ''), 'csv');
eq('.tsv ext', artifactKind('data.tsv', ''), 'csv');
eq('.json ext (code → json change)', artifactKind('cfg.json', ''), 'json');
eq('.yaml stays code', artifactKind('cfg.yaml', ''), 'code');

// ---- mermaid content sniff ----
eq('graph', artifactKind('', 'graph TD\n  A-->B'), 'mermaid');
eq('flowchart', artifactKind('', 'flowchart LR\n  A --> B'), 'mermaid');
eq('sequenceDiagram', artifactKind('', 'sequenceDiagram\n  A->>B: hi'), 'mermaid');
eq('pie', artifactKind('', 'pie title Pets\n  "Dogs": 3'), 'mermaid');
eq('stateDiagram-v2', artifactKind('', 'stateDiagram-v2\n  [*] --> S1'), 'mermaid');
eq('keyword needs boundary (pier ≠ pie)', artifactKind('', 'pier review notes here today'), 'code');
eq('leading whitespace tolerated', artifactKind('', '  \n graph TD\nA-->B'), 'mermaid');

// ---- json content sniff ----
eq('json object', artifactKind('', '{"a": 1, "b": [2, 3]}'), 'json');
eq('json array', artifactKind('', '[1, 2, 3]'), 'json');
eq('invalid json → not json', artifactKind('', '{broken'), 'code');
eq('bare string is NOT json-sniffed', artifactKind('', '"just a string"'), 'code');
eq('json sniff beats csv (multi-line object)', artifactKind('', '{\n "a": 1,\n "b": 2\n}'), 'json');

// ---- csv content sniff ----
eq('csv 3x3', artifactKind('', 'a,b,c\n1,2,3\n4,5,6'), 'csv');
eq('tsv content', artifactKind('', 'a\tb\n1\t2'), 'csv');
eq('inconsistent counts → not csv', artifactKind('', 'a,b\n1,2,3'), 'code');
eq('single line → not csv', artifactKind('', 'a,b,c'), 'code');
eq('js array literal not csv (varying commas)', artifactKind('', 'const a = [1,\n2,\n3];'), 'code');

// ---- regressions: existing kinds unchanged ----
eq('html doc', artifactKind('', '<!doctype html><html></html>'), 'html');
eq('svg', artifactKind('', '<svg viewBox="0 0 1 1"></svg>'), 'svg');
eq('react', artifactKind('', 'import React from "react"\nconst A=()=><div/>'), 'react');
eq('markdown', artifactKind('', '# Heading\n- a\n- b'), 'markdown');
eq('plain text', artifactKind('', 'plain text here'), 'code');

// ---- fenced-block wiring ----
eq('```mermaid worthy', classify('mermaid', 'graph TD\nA-->B'), { kind:'mermaid', worthy:true });
eq('```mmd worthy', classify('mmd', 'graph TD\nA-->B'), { kind:'mermaid', worthy:true });
eq('```csv worthy', classify('csv', 'a,b\n1,2'), { kind:'csv', worthy:true });
eq('```tsv worthy', classify('tsv', 'a\tb\n1\t2'), { kind:'csv', worthy:true });
eq('```json worthy', classify('json', '{"a":1}'), { kind:'json', worthy:true });
eq('unlabeled mermaid fence worthy', classify('', 'sequenceDiagram\nA->>B: hi'), { kind:'mermaid', worthy:true });
eq('small python still not worthy', classify('python', 'print(1)'), { kind:'code', worthy:false });

console.log(`artifact-kind-v2: ${pass}/${pass+fail} passed`);
process.exit(fail ? 1 : 0);
