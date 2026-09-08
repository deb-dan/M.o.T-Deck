'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
const readers=[],notices=[];
const c=vm.createContext({chatPane:{mode:'chat',sid:'old',openRequest:1,attachedImage:null},document:{getElementById:()=>null},
  liveVision:true,odyVisionCfg:()=>({}),attachVerdict:()=>({on:true}),attachNote:msg=>notices.push(msg),
  showAttachedImage:(data,name)=>{c.chatPane.attachedImage={data,name};},showAttachedFile:(data,name)=>{c.chatPane.attachedImage={data,name};},
  FileReader:class{constructor(){readers.push(this);}readAsDataURL(){}},setTimeout:fn=>fn()});
for(const name of ['clearImage','acceptImageFile','stripAttachMarker','lastAttachmentId','dropSidecarAttachment'])vm.runInContext(extractFunction(source,name),c);
function pick(name){c.acceptImageFile({type:'image/png',size:20,name});return readers.at(-1);}
const old=pick('old.png'),current=pick('current.png');current.result='current';current.onload();
old.result='late old';old.onload();old.onerror();assert.equal(c.chatPane.attachedImage.name,'current.png');assert.deepEqual(notices,[]);
const cleared=pick('cleared.png');c.clearImage();cleared.result='late';cleared.onload();assert.equal(c.chatPane.attachedImage,null);
const moved=pick('old conversation.png');c.chatPane.openRequest++;moved.result='late';moved.onload();assert.equal(c.chatPane.attachedImage,null);
(async()=>{
  let release;const urls=[];
  c.fetch=(url)=>{urls.push(url);if(url.includes('/history/'))return new Promise(r=>{release=r;});return Promise.resolve({ok:true});};
  const pending=c.dropSidecarAttachment('question','original/session');c.chatPane.sid='replacement';
  release({ok:true,json:async()=>({history:[{role:'user',content:'question',attachment:{id:4}}]})});await pending;
  assert.deepEqual(urls,['/api/ody/history/original%2Fsession','/api/attachment/4/delete']);
  urls.length=0;
  c.fetch=async url=>{urls.push(url);return {ok:true,json:async()=>({history:[{role:'user',content:'unrelated',attachment:{id:99}}]})};};
  await c.dropSidecarAttachment('not persisted yet','original');assert.equal(urls.length,2);assert.ok(urls.every(url=>url.includes('/history/')));
  console.log('PASS attachment reads and removals retain their selection and conversation');
})().catch(e=>{console.error(e);process.exitCode=1;});
