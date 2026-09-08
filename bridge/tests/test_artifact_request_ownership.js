'use strict';
const assert = require('node:assert/strict'), vm = require('node:vm'), fs = require('node:fs');
const {extractFunction} = require('./_panel_source');
const source = fs.readFileSync(require('node:path').join(__dirname,'../panel/index.html'),'utf8');
function page() {
 const p=vm.createContext({console,Symbol,document:{createElement(){throw new Error('stale renderer touched DOM');}, getElementById(){return null;}}, window:{},
 _canvas:{on:true,generation:1,savedPath:''}, _artFilename:'one.js',_artKind:'js',
 canvasBuffer:()=> 'original',canvasSaveName:x=>x, canvasNote:note=>{p.note=note;}});
 for(const n of ['renderArtMarkdown','renderArtCode','canvasSave'])vm.runInContext(extractFunction(source,n),p);
 return p;
}
(async()=>{
 for(const n of ['renderArtMarkdown','renderArtCode']){
  const p=page();let release;p.ensureHostVendor=()=>new Promise(r=>release=r);
  const container={_renderToken:Symbol()},task=p[n](container,'old','old.js');
  container._renderToken=Symbol();release();await task;
  console.log('OK '+n+' abandons a replaced artifact');
 }
 {
  const p=page();let release,calls=0;p.fetch=()=>{calls++;return new Promise(r=>release=r);};
  const task=p.canvasSave();await p.canvasSave();assert.equal(calls,1);
  p._canvas.generation++;p._canvas.savedPath='new';p.note='new canvas';
  release({ok:true,json:async()=>({path:'/artifacts/old.js'})});await task;
  assert.equal(p._canvas.savedPath,'new');assert.equal(p.note,'new canvas');
  console.log('OK old save cannot change a newer canvas; duplicate saves coalesce');
 }
 {
  const p=page();p.fetch=async()=>({ok:true,json:async()=>({path:'/artifacts/one.js'})});
  const task=p.canvasSave();p.canvasBuffer=()=> 'newer';await task;
  assert.match(p.note,/newer edits unsaved/);console.log('OK save receipt distinguishes newer unsaved edits');
 }
})().catch(e=>{console.error(e);process.exitCode=1;});
