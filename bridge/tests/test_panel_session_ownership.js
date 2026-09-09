'use strict';
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(require('node:path').join(__dirname,'../panel/index.html'),'utf8');
const tick=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
function page(mode='hermes'){
 const box={innerHTML:'old history',focus(){}};
 const p=vm.createContext({console,Symbol,chatPane:{mode,busy:false,hermesSid:'live-old',hermesStoredSid:'old',sid:'old',sessions:[]},
 document:{getElementById:()=>box},localStorage:{setItem(){},removeItem(){}},window:{},
 maybeCloseArtifact(){},stopConv(){},stopAuto(){},stopTalk(){},stopSpeaking(){},renderSessions(){},scrollChat(){},stampFor(){},
 chatNotice(note){p.note=note;},addMsg(_role,text){box.innerHTML+=text;return{};},loadSessions:async()=>[],
 renderOdyHistory(h){box.innerHTML=h.history[0].content;},detachTurnNow:async()=>true,stopTurnNow:async()=>true});
 for(const n of ['selectHermesSession','selectSession','newSession','duplicateSession','doDelete','sendChat'])vm.runInContext(extractFunction(source,n),p);
 return {p,box};
}
const cases=[];const check=(n,f)=>cases.push([n,f]);
check('late Hermes resume cannot replace a newer selected chat',async()=>{
 const {p,box}=page(),pending=[];p.fetch=()=>new Promise(r=>pending.push(r));
 const first=p.selectHermesSession('one'),second=p.selectHermesSession('two');
 pending[1]({ok:true,json:async()=>({id:'live-two',stored_id:'two',history:[{role:'user',content:'second'}]})});await second;
 pending[0]({ok:true,json:async()=>({id:'live-one',stored_id:'one',history:[{role:'user',content:'first'}]})});await first;
 assert.equal(p.chatPane.hermesSid,'live-two');assert.equal(box.innerHTML,'second');
});
check('failed Hermes new-chat retains the current live identity and transcript',async()=>{
 const {p,box}=page();p.fetch=async()=>({json:async()=>({error:'offline'})});await p.newSession();
 assert.equal(p.chatPane.hermesSid,'live-old');assert.equal(p.chatPane.hermesStoredSid,'old');assert.equal(box.innerHTML,'old history');assert.match(p.note,/could not/);
});
check('Hermes resume cannot adopt after a lane switch',async()=>{
 const {p,box}=page();let release;p.fetch=()=>new Promise(r=>release=r);
 const task=p.selectHermesSession('one');p.chatPane.mode='chat';
 release({ok:true,json:async()=>({id:'wrong',history:[]})});await task;
 assert.equal(p.chatPane.hermesSid,'live-old');assert.equal(box.innerHTML,'old history');
});
check('A to B to A history requests keep only the latest A snapshot',async()=>{
 const {p,box}=page('chat'),pending=[];p.panelReadJSON=()=>new Promise(r=>pending.push(r));
 const first=p.selectSession('A'),second=p.selectSession('B'),third=p.selectSession('A');
 pending[2]({history:[{content:'current A'}]});await tick();pending[3]({history:[{content:'settled A'}]});await third;
 pending[0]({history:[{content:'stale A'}]});pending[1]({history:[{content:'B'}]});await Promise.all([first,second]);
 assert.equal(box.innerHTML,'settled A');assert.equal(p.chatPane.sid,'A');
});
check('metadata resolving after another selection cannot recover an old turn',async()=>{
 const {p}=page('chat');let metadata,recovered=0;
 p.MOTDeckTurnStream=p.window.MOTDeckTurnStream={reconcile:async()=>({active:{id:'turn'}}),metadata:()=>new Promise(r=>metadata=r),recover:async()=>{recovered++;}};
 p.panelReadJSON=async()=>({history:[{content:'A'}]});const task=p.selectSession('A');await tick();
 p.chatPane.openRequest=Symbol();metadata({id:'turn',state:'running'});await task;assert.equal(recovered,0);
});
check('a refused delete preserves the active identity and history',async()=>{
 const {p,box}=page();p.fetch=async()=>({ok:true,json:async()=>({ok:false})});
 await p.doDelete('old');assert.equal(p.chatPane.hermesSid,'live-old');assert.equal(box.innerHTML,'old history');assert.match(p.note,/delete/);
});
check('a delete completing after another selection cannot clear that chat',async()=>{
 const {p,box}=page();let release;p.fetch=()=>new Promise(r=>release=r);
 const task=p.doDelete('old');p.chatPane.openRequest=Symbol();p.chatPane.hermesSid='new-live';
 release({ok:true,json:async()=>({ok:true})});await task;assert.equal(p.chatPane.hermesSid,'new-live');assert.equal(box.innerHTML,'old history');
});
check('first Hermes send coalesces preparation and preserves edits made during it',async()=>{
 const {p,box}=page();let release,calls=0;p.chatPane.hermesSid=null;box.value='initial';
 p.window.MOTDeckTurnStream={consume(){},requestId(){},postHermes(){throw new Error('must not post');},
 prepareHermesSession(){calls++;return new Promise(r=>release=r);}};
 const task=p.sendChat();await p.sendChat();assert.equal(calls,1);box.value='new draft';release();await task;
 assert.equal(box.value,'new draft');assert.equal(p.chatPane.busy,false);assert.match(p.note,/Message changed/);
});
(async()=>{let failed=0;for(const[n,f]of cases){try{await f();console.log('OK '+n);}catch(e){failed++;console.error('FAIL '+n+'\n'+e.stack);}}if(failed)process.exitCode=1;})();
