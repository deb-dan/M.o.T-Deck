'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(require('node:path').join(__dirname,'../panel/index.html'),'utf8');
function setup(fetch){
  const switched=[],errors=[];
  const c=vm.createContext({fetch,modelSettingsWrites:new Map(),loadApplying:false,modelsBusy:false,
    mSel:{kind:'installed',id:'A'},lastModels:{installed:[{id:'A'}]},
    switchModel:async id=>switched.push(id),feed(){},loadErr:e=>errors.push(e)});
  for(const name of ['modelSettingsRequest','loadApply'])vm.runInContext(extractFunction(source,name),c);
  return {c,switched,errors};
}
(async()=>{
  for(const failure of [false,true]){
    let release;
    const p=setup(()=>new Promise(r=>{release=r;}));
    const write=p.c.modelSettingsRequest('A','/settings',{});write.catch(()=>{});
    await Promise.resolve();await Promise.resolve();
    const btn={disabled:false};const reload=p.c.loadApply(btn);await p.c.loadApply(btn);
    assert.deepEqual(p.switched,[]);assert.equal(btn.disabled,true);
    release({ok:!failure,json:async()=>({ok:true,id:'A'})});
    await Promise.allSettled([write,reload]);
    assert.deepEqual(p.switched,failure?[]:['A']);assert.equal(btn.disabled,false);
    if(failure)assert.match(p.errors[0],/Not reloaded/);
  }
  const p=setup(async()=>({ok:true,json:async()=>({ok:true,id:'B'})}));
  await assert.rejects(p.c.modelSettingsRequest('A','/settings',{}),/did not confirm/);
  assert.equal(p.c.modelSettingsWrites.size,0);
  console.log('model reload waits for saved settings, rejects bad receipts and deduplicates clicks');
})().catch(e=>{console.error(e);process.exit(1);});
