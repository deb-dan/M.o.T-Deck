'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../panel/compose.html'),'utf8');
const source=html.split('<script>').pop().split('</script>')[0];
const testSource=fs.readFileSync(path.join(__dirname,'test_compose_page.js'),'utf8');
const makeEnv=new Function(testSource.slice(testSource.indexOf('function makeEnv()'),testSource.indexOf('\nconst bodyScript'))+';return makeEnv;')();
function page(layout){
 const env=makeEnv(), handlers={};let request=async()=>({ok:true,json:async()=>({ok:true,engines:[],tracks:[]})});
 env.document.addEventListener=(name,fn)=>{(handlers[name]??=[]).push(fn);};
 const api=new Function('document','window','localStorage','fetch','setTimeout','clearTimeout','addEventListener','location',
  source.slice(0,source.lastIndexOf('\napplyLayout();'))+';return {S,load,render,renderStage,renderLibraryBlock,renderComposer,renderQueueBlock,applyLayout,wantWave,titleOf,tipBind};')(
  env.document,env.window,{getItem(){return layout||null;},setItem(){}},(...a)=>request(...a),()=>0,()=>{},()=>{},env.window.location);
 env.document.querySelector=selector=>{assert(!selector.includes('"bad'),'unknown saved id reached a selector');return null;};
 return{env,api,handlers,setFetch(fn){request=fn;},async click(act){const b={dataset:{act},disabled:false};
   for(const fn of handlers.click||[])await fn({target:{closest(s){return s==='[data-act]'?b:null;}}});return b;}};
}
const track={name:'song.wav',title:'My song',engine:'one',path:'/music/song.wav',size_bytes:100,seconds:30};
const state={ok:true,engines:[{engine:'one',installed:true,label:'One',default_steps:8}],formats:{one:['wav']},format_default:{one:'wav'}};
const checks=[];const check=(name,fn)=>checks.push([name,fn]);
check('existing songs remain playable without installed engines',()=>{
 const p=page();p.api.S.st={ok:true,engines:[]};p.api.S.lib=[track];p.api.S.wave[track.name]={error:'not decoded'};
 p.api.renderStage();assert.match(p.env.nodes['stage-body'].innerHTML,/id="play"/);
 assert(p.env.created.some(n=>n.id==='new:audio'));
});
check('polling does not replace a focused advanced setting',()=>{
 const p=page();p.api.S.st=state;p.api.S.more=true;p.api.renderComposer();
 p.env.document.activeElement={id:'f-steps',tagName:'INPUT',value:'12'};
 p.env.nodes.sbody.contains=el=>el===p.env.document.activeElement;p.env.written.length=0;
 p.api.S.form.steps='12';p.api.renderComposer();
 assert.equal(p.env.written.filter(x=>x.id==='sbody').length,0);
});
check('polling preserves the armed Stop confirmation',()=>{
 const p=page();p.api.S.st={...state,job:{id:'j',state:'running',started:1}};
 p.api.renderQueueBlock();p.env.nodes.queuebody.querySelector=()=>({});p.env.written.length=0;
 p.api.renderQueueBlock();assert.equal(p.env.written.filter(x=>x.id==='queuebody').length,0);
});
check('median averages both middle render times',()=>{
 const p=page();p.api.S.lib=[{...track,wall:10},{...track,wall:30}];p.api.renderLibraryBlock();
 assert.match(p.env.nodes.libbody.innerHTML,/Median render<\/span><b class="num">20s/);
});
check('Unicode prompts supply track names',()=>{
 const p=page();assert.equal(p.api.titleOf({name:'timestamp.wav',prompt:'🎵 夜晚的钢琴旋律'}),'夜晚的钢琴旋律');
 assert.equal(p.api.titleOf({name:'timestamp.wav',prompt:'Тихая музыка для вечера'}),'Тихая музыка для вечера');
});
check('malformed saved layout lists cannot prevent startup',()=>{
 for(const layout of [{blocks:'wave'},{spill:{}},{blocks:[null,{},'"bad','wave']}]){
  const p=page(JSON.stringify(layout));assert.doesNotThrow(()=>p.api.applyLayout());
 }
});
check('changing engines clears an unsupported previous output format',()=>{
 const p=page();p.api.S.st=state;p.api.S.form={engine:'one',format:'mp3'};p.api.renderComposer();
 assert.equal(p.api.S.form.format,'');
});
check('library failures are visible while the last successful library remains',async()=>{
 const p=page();p.api.S.st=state;p.api.S.lib=[track];p.api.S.wave[track.name]={error:'not decoded'};
 p.setFetch(async url=>({ok:!url.endsWith('library'),status:503,json:async()=>url.endsWith('library')?{ok:false,error:'library unavailable'}:state}));
 await p.api.load();assert.equal(p.api.S.lib[0],track);assert.match(p.api.S.err,/library unavailable/);
});
check('failed conversions re-enable the control and show the failure',async()=>{
 const p=page();p.setFetch(async()=>{throw Error('offline');});
 const b=await p.click('convert');assert.equal(b.disabled,false);assert.match(p.env.nodes.toast.textContent,/offline/);
});
(async()=>{let failed=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}
 catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}if(failed)process.exit(1);})();
