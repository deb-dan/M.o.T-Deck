// Execute production detection and the production fenced-block classifier.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
const context=vm.createContext({});
vm.runInContext(source.match(/^const MERMAID_RE = .*;$/m)[0],context);
vm.runInContext(source.match(/const LANG_EXT = \{[\s\S]*?\n\};/)[0],context);
for(const name of ['sniffMermaid','sniffJson','sniffCsv','artifactKind'])
  vm.runInContext(extractFunction(source,name),context);
const block=extractFunction(source,'_appendCodeBlock');
// The prefix calculates kind/worthy; only the subsequent DOM construction is omitted.
vm.runInContext(block.slice(0,block.indexOf('  const box ='))+'return {kind,worthy};}',context);
const artifactKind=context.artifactKind;
const classify=(lang,code)=>context._appendCodeBlock(null,lang,code);

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
