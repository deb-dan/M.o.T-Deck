'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function page(){
 const btn={disabled:false,textContent:'',classList:{remove(){},add(){},contains(){return true;}}};
 const audios=[];let url=0;
 const p=vm.createContext({console,setTimeout,clearTimeout,setInterval,clearInterval,Blob,
  Date,Uint8Array,Float32Array,ArrayBuffer,DataView,
  document:{getElementById:()=>btn,body:{contains:()=>true}},
  navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[]})}},
  URL:{createObjectURL:()=>String(++url),revokeObjectURL(){}},
  Audio:class{constructor(){audios.push(this);}play(){return Promise.resolve();}pause(){this.paused=true;}},
  SPEAK_LABEL:'speak',SPEAK_TITLE:'Speak',TALK_MAX_S:60,
  currentAudio:null,talkRec:null,autoVad:null,chatPane:{mode:'chat',sid:'one'},curView:'chat',
  talkMime:()=>({mime:'audio/mp4',fmt:'mp4'}),renderTalkBtn(){},renderAutoBtn(){},renderConvBtn(){},
  talkPaint(){},speakFlash(){},autoFlash(){},convOn:()=>false,stopConv(){},
  sttOn:()=>true,convEvent(){},msgRaw:()=> 'hello',speakText:x=>x,
  wavFromPcm:()=>new Blob(['audio']),resampleLinear:x=>x,
  appendTranscript(t){p.appended=t;},VAD_MAX_ERRORS:3});
 vm.runInContext('let speakRequest=0,speakPending=null,talkRequest=0,talkStarting=false,autoRequest=0,autoStarting=null;',p);
 for(const name of ['stopSpeaking','msgSpeak','startTalk','stopTalk','finishTalk','stopAuto','autoDrain'])
  vm.runInContext(extractFunction(source,name),p);
 return {p,btn,audios};
}
const checks=[];const check=(n,f)=>checks.push([n,f]);
check('stopped auto dictation drops a late transcript',async()=>{
 const {p}=page();let release;p.autoVad={queue:[new Float32Array([1])],rate:16000,mode:'auto'};
 p.fetch=()=>new Promise(r=>release=r);const task=p.autoDrain();p.stopAuto('leave');
 release({ok:true,json:async()=>({ok:true,text:'old words'})});await task;
 assert.equal(p.appended,undefined);
});
check('stopping playback also cancels a render that has not answered yet',async()=>{
 const {p,btn,audios}=page();let release;p.fetch=()=>new Promise(r=>release=r);
 const task=p.msgSpeak({},btn);p.stopSpeaking();
 release({ok:true,blob:async()=>new Blob(['clip'])});assert.equal(await task,false);assert.equal(audios.length,0);
});
check('an old audio error cannot stop the newer clip',async()=>{
 const {p,audios}=page();p.fetch=async()=>({ok:true,blob:async()=>new Blob(['clip'])});
 await p.msgSpeak({},{});const old=audios[0];await p.msgSpeak({},{});
 old.onerror();assert.equal(p.currentAudio.audio,audios[1]);assert.notEqual(audios[1].paused,true);
});
check('a cancelled recorder callback cannot steal a newer recording',async()=>{
 const {p}=page();const old={cancelled:true},current={cancelled:false};p.talkRec=current;
 p.fetch=async()=>({ok:true,json:async()=>({ok:true,text:'wrong'})});
 await p.finishTalk([new Blob(['old'])],'mp4',old);
 assert.equal(p.talkRec,current);assert.equal(p.appended,undefined);
});
check('permission arriving after Stop releases the microphone without recording',async()=>{
 const {p}=page();let release,stops=0,constructed=0;
 p.navigator.mediaDevices.getUserMedia=()=>new Promise(r=>release=r);
 p.MediaRecorder=class{constructor(){constructed++;}start(){}stop(){}};
 const task=p.startTalk();await tick();p.stopTalk(true);
 release({getTracks:()=>[{stop(){stops++;}}]});await task;
 if(p.talkRec)p.stopTalk(true);
 assert.equal(constructed,0);assert.equal(stops,1);
});
(async()=>{let failed=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}if(failed)process.exitCode=1;})();
