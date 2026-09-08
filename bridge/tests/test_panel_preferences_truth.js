'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(require('node:path').join(__dirname,'../panel/index.html'),'utf8');
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function page(){
 const ctx=vm.createContext({console,setTimeout,clearTimeout,Date,
  localStorage:{setItem(){},getItem(){return null;}},
  document:{getElementById(){return null;}},
  navModel:{id:'initial'},navNormalize:x=>x,navGet(){return ctx.navModel;},
  navValidate:()=>'',navSaveLocal(){},renderSidebar(){},renderNavDlg(){},nativeShell:()=>null,
  storedDesign:()=>'editorial',designId:x=>x,designApply(x){ctx.applied=x;},DESIGNS:[],feed(){},
  escAttr:s=>String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')});
 vm.runInContext('let navRevision=0,navWrites=0,navSavePending=Promise.resolve(),navConfirmed=null; let _designAsset=null,_designLastStudio="studio",_designRequest=0;',ctx);
 for(const name of ['navSync','navSave','navApply','setDesign','apiArg'])vm.runInContext(extractFunction(source,name),ctx);
 return ctx;
}
const checks=[];const check=(name,fn)=>checks.push([name,fn]);
check('API action arguments survive entity-shaped names',()=>{
 const p=page(),name='&#34;);throw new Error("oops");//';
 const raw=p.apiArg(name).replace(/&(quot|amp|#34|#39);/g,(_m,key)=>({quot:'"',amp:'&','#34':'"','#39':"'"})[key]);
 assert.equal(vm.runInNewContext(raw),name);
});
check('a delayed Studio load cannot override a newer Editorial choice',async()=>{
 const p=page();let release;p.designAsset=()=>new Promise(r=>release=r);
 const old=p.setDesign('studio');await p.setDesign('editorial');release();await old;
 assert.equal(p.applied,'editorial');
});
check('navigation saves serialize while keeping the latest optimistic layout',async()=>{
 const p=page(),pending=[];p.fetch=(_url,options)=>new Promise(resolve=>pending.push({resolve,body:JSON.parse(options.body)}));
 const first=p.navApply({id:'first'});await tick();const second=p.navApply({id:'second'});await tick();
 assert.equal(pending.length,1);
 pending[0].resolve({ok:true,json:async()=>({ok:true,nav:{id:'first'}})});await first;await tick();
 assert.equal(p.navModel.id,'second');assert.equal(pending.length,2);
 assert.equal(pending[1].body.nav.id,'second');
 pending[1].resolve({ok:true,json:async()=>({ok:true,nav:{id:'second'}})});await second;
 assert.equal(p.navModel.id,'second');
});
check('two refused navigation saves restore the last accepted layout',async()=>{
 const p=page(),pending=[];p.fetch=()=>new Promise(resolve=>pending.push(resolve));
 const first=p.navApply({id:'first'});await tick();const second=p.navApply({id:'second'});
 pending[0]({ok:false,status:409,json:async()=>({error:'refused'})});await first;await tick();
 pending[1]({ok:false,status:409,json:async()=>({error:'refused'})});await second;
 assert.equal(p.navModel.id,'initial');
});
check('a navigation read started before an edit cannot erase that edit',async()=>{
 const p=page();let read;p.fetch=(_url,opts)=>opts?Promise.resolve({ok:true,json:async()=>({ok:true,nav:{id:'edit'}})})
 :new Promise(resolve=>read=resolve);
 const sync=p.navSync();await p.navApply({id:'edit'});
 read({ok:true,json:async()=>({ok:true,nav:{id:'old'}})});await sync;
 assert.equal(p.navModel.id,'edit');
});
(async()=>{let fails=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}catch(e){fails++;console.error('FAIL '+name+'\n'+e.stack);}}if(fails)process.exitCode=1;})();
