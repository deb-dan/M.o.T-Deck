// PHASE 3 unit test — pure fence→kind→worthy classification used by renderChatBody().
// Mirrors the panel's LANG_EXT map + artifactKind() sniff + the "artifact-worthy" rule.
// Run: node bridge/tests/test_fence_classify.js  (offline, no deps)

function artifactKind(filename, content){
  const fn=(filename||'').toLowerCase().trim();
  const ext=(fn.match(/\.([a-z0-9]+)$/)||[])[1]||'';
  const c=content||'';
  const EXT={html:'html',htm:'html',svg:'svg',jsx:'react',tsx:'react',js:'js',mjs:'js',cjs:'js',
    md:'markdown',markdown:'markdown',pdf:'pdf',py:'code',ts:'code',go:'code',rs:'code',sh:'code',
    json:'code',yaml:'code',yml:'code',css:'code',sql:'code'};
  let kind=EXT[ext]||'';
  const importsReact=/import\s+[\s\S]*?from\s*['"]react(?:-dom)?(?:\/[\w-]+)?['"]/.test(c)||/\bReactDOM\b|\bReact\.(?:createElement|Component|useState|Fragment)\b/.test(c);
  const hasJsxTag=/<[A-Z][A-Za-z0-9]*[\s/>]/.test(c);
  if(!kind){const t=c.replace(/^\s+/,'');
    if(/^<svg[\s>]/i.test(t))kind='svg';
    else if(/^<!doctype html/i.test(t)||/^<html[\s>]/i.test(t)||/<\/(?:div|body|head|p|span|section|main|h[1-6])>/i.test(t))kind='html';
    else if(importsReact||hasJsxTag)kind='react';
    else if(/^#{1,6}\s|\n#{1,6}\s|```|^\s*[-*]\s+\S/m.test(t))kind='markdown';
    else kind='code';}
  if((kind==='js'||kind==='html')&&(importsReact||hasJsxTag))kind='react';
  return kind;
}
const LANG_EXT={html:'html',htm:'html',svg:'svg',jsx:'jsx',tsx:'tsx',react:'jsx',javascript:'js',js:'js',
  typescript:'ts',ts:'ts',python:'py',py:'py',bash:'sh',sh:'sh',json:'json',css:'css',go:'go',rust:'rs',md:'md'};
function classify(lang,code){
  const ext=LANG_EXT[lang]||'';
  const synth='artifact.'+(ext||'txt');
  const kind=artifactKind(ext?synth:'',code);
  const lines=code.split('\n').length;
  const big=lines>=8||code.length>=300;
  const worthy=kind==='html'||kind==='svg'||kind==='react'||(kind==='js'&&big)||(kind==='code'&&big);
  return {kind,worthy};
}

const big='x\n'.repeat(10);
const cases=[
  ['html','<!doctype html><html><body>hi</body></html>','html',true],
  ['svg','<svg viewBox="0 0 10 10"></svg>','svg',true],
  ['jsx','function App(){return <div/>}','react',true],
  ['tsx','const A=()=><div/>','react',true],
  ['python','print(1)','code',false],
  ['python','print(1)\n'+big,'code',true],
  ['js','console.log(1)','js',false],
  ['js','console.log(1)\n'+big,'js',true],
  ['','<svg></svg>','svg',true],
  ['','# Heading\n- a\n- b','markdown',false],
  ['','plain text','code',false],
  ['','import React from "react"\nconst A=()=><div/>','react',true],
];
let ok=0,fail=0;
for(const [lang,code,ek,ew] of cases){
  const r=classify(lang,code);
  const pass=r.kind===ek&&r.worthy===ew;
  if(pass)ok++;else{fail++;console.log('FAIL',JSON.stringify(lang),'got',r,'want',{kind:ek,worthy:ew});}
}
console.log(`fence-classify: ${ok}/${ok+fail} passed`);
process.exit(fail?1:0);
