'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
function page(){
 const p=vm.createContext({console,voiceErr:'',pendingClip:null,lastModels:{audio:[]},
  loadVoiceLib:async()=>{},renderAudioDetail(){},initModels:async()=>{},stopSpeaking(){},feed(){}});
 for(const name of ['saveClip','setEntryRef'])vm.runInContext(extractFunction(source,name),p);
 return p;
}
const checks=[];const check=(n,f)=>checks.push([n,f]);
check('a failed library save retains the recording for retry',async()=>{
 const p=page(),clip={blob:'bytes',fmt:'wav',id:'voice'};p.pendingClip=clip;
 p.fetch=async()=>({ok:false,status:503,json:async()=>({error:'busy'})});
 await p.saveClip('voice','sample');assert.equal(p.pendingClip,clip);
});
check('repeated Save while a recording is being saved sends only one copy',async()=>{
 const p=page();p.pendingClip={blob:'bytes',fmt:'wav',id:'voice'};let release,calls=0;
 p.fetch=()=>{calls++;return new Promise(r=>release=r);};p.setEntryRef=async()=>{};
 const first=p.saveClip('voice','sample');const second=p.saveClip('voice','sample');
 assert.equal(calls,1);release({ok:true,json:async()=>({ok:true,name:'sample.wav'})});await Promise.all([first,second]);
 assert.equal(p.pendingClip,null);
});
check('changing the reference clip does not reuse the old transcript',async()=>{
 const p=page();p.lastModels.audio=[{id:'voice',ref_audio:'first.wav',ref_text:'first words'}];let body;
 p.fetch=async(_url,opts)=>{body=JSON.parse(opts.body);return {ok:true,json:async()=>({ok:true})};};
 await p.setEntryRef('voice','second.wav');assert.equal(body.ref_text,undefined);
 await p.setEntryRef('voice','first.wav');assert.equal(body.ref_text,'first words');
});
(async()=>{let failed=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}if(failed)process.exitCode=1;})();
