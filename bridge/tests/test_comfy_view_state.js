'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const root=path.join(__dirname,'..');
const html=fs.readFileSync(path.join(root,'panel/comfy.html'),'utf8');
const testSource=fs.readFileSync(path.join(__dirname,'test_comfy_page.js'),'utf8');
const makeEnv=new Function(testSource.slice(testSource.indexOf('function makeEnv()'),testSource.indexOf('\nconst bodyScript'))+';return makeEnv;')();
const script=html.split('<script>').pop().split('</script>')[0];
function page(){
  const env=makeEnv(), handlers={}, calls=[];
  env.document.addEventListener=(name,fn)=>{(handlers[name]??=[]).push(fn);};
  env.document.body.contains=()=>true;
  let fetcher=async url=>{calls.push(url);return {ok:true,json:async()=>url.includes('/gallery')?{ok:true,items:[]}:
    url.includes('/catalog')?{ok:true,catalog:{models:[]}}:{ok:true,downloads:[],jobs:[],curation:{picks:[]}}};};
  const fn=new Function('document','window','localStorage','fetch','EventSource','setTimeout','clearTimeout',
    script.slice(0,script.lastIndexOf('\nloadView();'))+';return {S,load,dlSig,renderStage,paint,flushPending,renderPicker,currentPick,curWorkflow,tipBind,render};');
  const api=fn(env.document,env.window,{getItem(){return null;},setItem(){}},
    (...args)=>fetcher(...args),function(){},()=>0,()=>{});
  return {env,api,calls,handlers,setFetch(fn){fetcher=fn;},
    async click(act,data={}){const button={dataset:{act,...data},disabled:false};
      const event={target:{closest(sel){return sel==='[data-act]'?button:null;}}};
      for(const handler of handlers.click||[])await handler(event);
      return button;
    }};
}
const checks=[];
function check(name,fn){checks.push([name,fn]);}
check('download percentage does not invalidate the full catalogue',()=>{
  const p=page();p.api.S.state={downloads:[{id:'d',state:'downloading',pct:1}]};
  const first=p.api.dlSig();p.api.S.state.downloads[0].pct=2;
  assert.equal(p.api.dlSig(),first);p.api.S.state.downloads[0].state='done';
  assert.notEqual(p.api.dlSig(),first);
});
check('existing results remain visible after starter weights are removed',()=>{
  const p=page();p.api.S.state={curation:{picks:[]}};
  p.api.S.gallery={items:[{filename:'keep.png',kind:'image',state:'ok'}]};
  p.api.renderStage();assert.match(p.env.nodes['stage-body'].innerHTML,/keep\.png/);
  assert.doesNotMatch(p.env.nodes['stage-body'].innerHTML,/stage-invite/);
});
check('Refresh asks for a current catalogue even when no download changes',async()=>{
  const p=page();await p.api.load();p.calls.length=0;await p.click('refresh');
  assert(p.calls.includes('/api/comfy/catalog?refresh=1'));
});
check('failed state read retains the last good results and reports failure',async()=>{
  const p=page(), old={ok:true,curation:{picks:[]},downloads:[]}, gallery={ok:true,items:[]};
  p.api.S.state=old;p.api.S.gallery=gallery;
  p.setFetch(async()=>({ok:false,status:503,json:async()=>({error:'temporarily unavailable'})}));
  await p.api.load();assert.equal(p.api.S.state,old);assert.equal(p.api.S.gallery,gallery);
  assert.match(p.api.S.err,/temporarily unavailable/);
});
check('an obsolete deferred repaint cannot replace a newer rendered value',()=>{
  const p=page();p.api.paint('railbody','current');const el=p.env.nodes.railbody;
  el._pending='obsolete';p.api.paint('railbody','current');
  assert.equal(el._pending,null);
});
check('the source selection uses origin, subfolder and filename together',()=>{
  const p=page();p.api.S.catalog={models:[{id:'m',workflows:[{id:'w',needs:['image'],complete:true,runnable:true}]}]};
  p.api.S.sources=[{origin:'input',subfolder:'one',filename:'same.png',kind:'image',label:'one'},
    {origin:'gallery',subfolder:'two|nested',filename:'same.png',kind:'image',label:'two'}];
  p.api.S.form.source={...p.api.S.sources[1]};p.api.renderPicker();
  const markup=p.env.nodes.picker.innerHTML;
  assert.equal((markup.match(/ selected/g)||[]).length,3); // model + workflow + one source
  const select={id:'p-src',value:JSON.stringify(['gallery','two|nested','same.png'])};
  for(const handler of p.handlers.change||[])handler({target:select});
  assert.equal(p.api.S.form.source.subfolder,'two|nested');
});
check('choosing a curated model in the sheet updates the active catalogue workflow',async()=>{
  const p=page();p.api.S.state={curation:{picks:[{id:'a',modes:['image'],downloaded:true},
    {id:'b',modes:['image'],downloaded:true}]}};
  p.api.S.catalog={models:[{id:'ma',workflows:[{id:'wa',curated_pick:'a',runnable:true}]},
    {id:'mb',workflows:[{id:'wb',curated_pick:'b',runnable:true}]}]};
  p.api.S.form={model:'ma',workflow:'wa',pick:'a',mode:'image'};
  await p.click('use',{pick:'b'});assert.equal(p.api.currentPick().id,'b');
  assert.equal(p.api.curWorkflow().id,'wb');
});
check('overlapping refreshes share a reader and retain an explicit catalogue refresh',async()=>{
  const p=page();let release;let stateCalls=0;const urls=[];
  p.setFetch(async url=>{urls.push(url);if(url==='/api/comfy/state'&&++stateCalls===1)
    return new Promise(resolve=>{release=resolve;});
    return {ok:true,json:async()=>url.includes('/gallery')?{ok:true,items:[]}:
      url.includes('/catalog')?{ok:true,catalog:{models:[]}}:{ok:true,downloads:[],curation:{picks:[]}}};});
  const first=p.api.load(), second=p.api.load(true);
  assert.equal(stateCalls,1);assert.equal(first,second);
  release({ok:true,json:async()=>({ok:true,downloads:[],curation:{picks:[]}})});
  await second;assert.equal(stateCalls,2);assert(urls.includes('/api/comfy/catalog?refresh=1'));
});
check('actionable tooltip chips remain operable with Enter',()=>{
  const p=page();const events={};let clicks=0;
  const chip={dataset:{act:'reuse-seed'},classList:{add(){}},hasAttribute(){return true;},
    addEventListener(name,fn){events[name]=fn;},click(){clicks++;},
    getBoundingClientRect(){return {left:0,top:0,bottom:20};}};
  p.api.tipBind(chip,'seed information','seed');
  events.keydown({key:'Enter',preventDefault(){},stopPropagation(){}});
  assert.equal(clicks,1);
});
(async()=>{let failed=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}
 catch(error){failed++;console.error('FAIL '+name+'\n'+error.stack);}}
 if(failed)process.exit(1);
})();
