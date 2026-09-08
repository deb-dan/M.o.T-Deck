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
