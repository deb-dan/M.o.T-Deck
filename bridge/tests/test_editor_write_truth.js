'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../panel/oo.html'), 'utf8');
const script = html.split('<script>').pop().split('</script>')[0];
function page() {
  const nodes = new Map(), events = [], frames = [];
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {style: {}, classList: {add(){},remove(){},toggle(){}},
      firstElementChild: {style:{}}, addEventListener(){}, appendChild(){}, innerHTML:'', textContent:''});
    return nodes.get(id);
  }
  const storage = new Map();
  const context = vm.createContext({console, URLSearchParams, URL, Blob, Uint8Array, Date,
    location: {search:'?embed=1', origin:'http://localhost'},
    document: {body:node('body'), getElementById:node, createElement:node},
    setInterval(){return 1;}, clearInterval(){}, setTimeout, clearTimeout,
    localStorage: {getItem:k=>storage.get(k)??null, setItem:(k,v)=>storage.set(k,v), removeItem:k=>storage.delete(k)},
    addEventListener(){}, frames,
    parent: {LOfficeHost: {event:e=>events.push(e), register(){}}},
    fetch: async()=>({ok:true,status:200,json:async()=>({ok:true,mtime:2,bytes:1024,name:'A.xlsx'})})});
  context.window = context;
  vm.runInContext(script, context);
  const run = code=>vm.runInContext(code, context);
  run("DOC='A.xlsx'; ready=true; dirtyNow=true; openedMtime=1; x2tConvert=()=>new Uint8Array([1]);");
  let content = 'original';
  const api = {asc_nativeGetFile:()=>content};
  frames.push({editor:api});
  return {context,run,api,events,nodes, setContent:v=>{content=v;}};
}
const checks=[];
function check(name,fn){checks.push([name,fn]);}
check('typing during a save remains unsaved in the child and its receipt',async()=>{
  const p=page();let release;
  p.context.fetch=()=>new Promise(r=>{release=r;});
  const pending=p.run('save(false)');p.setContent('new typing');
  release({ok:true,status:200,json:async()=>({ok:true,mtime:2,bytes:1024})});
  const result=await pending;
  assert.equal(result.ok,true);assert.equal(result.dirty,true);
  assert.equal(p.run('dirtyNow'),true);
  assert.equal(p.events.find(e=>e.kind==='saved').dirty,true);
  assert.equal(p.events.at(-1).dirty,true);
});
check('an unchanged successful save clears dirty state',async()=>{
  const p=page(), result=await p.run('save(false)');
  assert.equal(result.ok,true);assert.equal(p.run('dirtyNow'),false);
});
check('an unreadable post-save editor stays conservatively dirty',async()=>{
  const p=page();let calls=0;
  p.api.asc_nativeGetFile=()=>{if(++calls>1)throw Error('editor unavailable');return 'original';};
  const result=await p.run('save(false)');
  assert.equal(result.ok,true);assert.equal(p.run('dirtyNow'),true);
});
check('a lost write response does not claim that no bytes reached disk',async()=>{
  const p=page();p.context.fetch=async()=>{throw Error('connection reset');};
  const result=await p.run('save(false)');assert.equal(result.ok,false);
  assert.equal(result.uncertain,true);
  assert.doesNotMatch(p.nodes.get('note-text').textContent,/was not changed/);
});
check('a partial builder apply is dirty even when the editor emits no event',()=>{
  const p=page();p.run('dirtyNow=false');let writes=0;
  const sheet={GetRange(){return {SetValue(){if(++writes===2)throw Error('refused');}};}};
  Object.assign(p.api,{GetActiveSheet:()=>sheet,canRunBuilderScript:()=>true,asc_Recalculate(){}});
  const result=p.run("applyOps([{k:'set',at:'A1',values:[[1]]},{k:'set',at:'A2',values:[[2]]}], '')");
  assert.equal(result.ok,false);assert.equal(result.done.cells,1);
  assert.equal(p.run('dirtyNow'),true);assert.equal(p.events.at(-1).dirty,true);
});
check('a missing named sheet never redirects writes to the active sheet',()=>{
  const p=page();let writes=0;
  Object.assign(p.api,{GetSheet:()=>null,GetActiveSheet:()=>({GetRange:()=>({SetValue(){writes++;}})})});
  const result=p.run("applyOps([{k:'set',at:'A1',values:[[1]]}], 'Deleted sheet')");
  assert.equal(result.ok,false);assert.equal(writes,0);
});
check('false style values clear existing emphasis',()=>{
  const p=page(), got={};p.context.range=Object.fromEntries(['Bold','Italic','Strikeout','Underline']
    .map(key=>['Set'+key,value=>{got[key]=value;}]));
  p.run('ooStyle({}, range, {bl:0,it:false,st:0,ul:false})');
  assert.deepEqual(got,{Bold:false,Italic:false,Strikeout:false,Underline:'none'});
});
function openingPage() {
  const p=page();p.run('once=async()=>true; dirtyNow=false;');
  const configs=[];
  p.context.DocsAPI={DocEditor:function(_id,config){configs.push(config);
    this.connectMockServer=()=>{};this.destroyEditor=()=>{};}};
  p.context.fetch=async url=>({ok:true,status:200,json:async()=>({files:[{name:'A.xlsx',modified:1},
    {name:'B.xlsx',modified:2}]}),arrayBuffer:async()=>new Uint8Array([1]).buffer});
  return {...p,configs};
}
async function tick(){for(let i=0;i<20;i++)await Promise.resolve();}
check('old editor callbacks cannot mark a newer document dirty or failed',async()=>{
  const p=openingPage();const first=p.run("openDoc('A.xlsx')");await tick();
  p.configs[0].events.onDocumentReady();await first;
  const second=p.run("openDoc('B.xlsx')");await tick();
  p.configs[1].events.onDocumentReady();await second;p.events.length=0;
  p.configs[0].events.onDocumentStateChange({data:true});
  p.configs[0].events.onError({data:'late failure'});
  assert.equal(p.run('dirtyNow'),false);assert.equal(p.run('ready'),true);
  assert.equal(p.events.length,0);
});
check('an editor acknowledgement during a pending save cannot clear dirty',async()=>{
  const p=openingPage();const opened=p.run("openDoc('A.xlsx')");await tick();
  p.configs[0].events.onDocumentReady();await opened;
  p.run('dirtyNow=true;saving=true;');
  p.configs[0].events.onDocumentStateChange({data:false});
  assert.equal(p.run('dirtyNow'),true);
});
check('a superseded open settles promptly instead of hanging on a destroyed frame',async()=>{
  const p=openingPage();let result;
  p.run("openDoc('A.xlsx')").then(r=>{result=r;});await tick();
  const second=p.run("openDoc('B.xlsx')");await tick();
  p.configs.at(-1).events.onDocumentReady();await second;await tick();
  assert.equal(result?.error,'superseded');
});
check('a superseded chat flush cannot destroy the replacement editor',async()=>{
  const p=openingPage();const opened=p.run("openDoc('A.xlsx')");await tick();
  p.configs[0].events.onDocumentReady();await opened;
  let release;p.context.pause=()=>new Promise(r=>{release=r;});
  p.run('aiChatHandover=pause;');
  const old=p.run("openDoc('Old.xlsx')");await tick();
  p.run('aiChatHandover=async()=>{};');
  const newer=p.run("openDoc('B.xlsx')");await tick();
  p.configs.at(-1).events.onDocumentReady();await newer;
  release();await tick();
  assert.equal(p.run('DOC'),'B.xlsx');assert.equal(p.configs.length,2);
  assert.equal((await old).error,'superseded');
});
const parentHTML=fs.readFileSync(path.join(__dirname,'../panel/office.html'),'utf8');
function hostPage(receipt) {
  const messages=[];
  const context=vm.createContext({documentGen:0,dirty:true,extSeen:0,ooDoc:'A.xlsx',current:'A.xlsx',
    ooChild:{save:async()=>receipt},ooCall:async(_name,fn)=>fn(),
    busyOn(){},busyOff(){},paint(){},bx(){},loadFiles(){},ooRefreshSnapshot(){},
    say:text=>messages.push(text),bakNote:()=>'',BUSY_MAX_EDITOR_MS:1000});
  for(const [start,end] of [['function ooEvent(ev)', '\n// ── is it installed?'],
    ['async function ooSave(force)', '\n// ══ DOWNLOAD AS PDF']]) {
    vm.runInContext(parentHTML.slice(parentHTML.indexOf(start),parentHTML.indexOf(end,parentHTML.indexOf(start))),context);
  }
  return {context,messages,run:code=>vm.runInContext(code,context)};
}
check('the host keeps newer edits dirty and Save & open refuses to discard them',async()=>{
  const p=hostPage({ok:true,dirty:true});
  p.run("ooEvent({kind:'saved',mtime:2,dirty:true,bytes:1024})");
  assert.equal(p.context.dirty,true);assert.equal(p.context.extSeen,2);
  assert.equal(await p.run('ooSave(false)'),false);
  assert.match(p.messages[0],/newer edits/);
});
check('the host preserves uncertain save wording',async()=>{
  const p=hostPage({ok:false,uncertain:true,error:'connection reset'});
  assert.equal(await p.run('ooSave(false)'),false);
  assert.match(p.messages[0],/outcome is unknown/);
  assert.doesNotMatch(p.messages[0],/was not changed/);
});
check('a document swap during font loading cancels PDF export before serialization',async()=>{
  const p=page();let release,printed=0;
  p.api.asc_nativePrint=()=>{};p.api.asc_nativeGetPDF=()=>{printed++;return [];};
  p.context.waitForFonts=()=>new Promise(r=>{release=r;});
  p.run('mountFonts=waitForFonts;');
  const exportTask=p.run('exportPdf()');p.run("openSeq++;DOC='B.xlsx';");
  release(10);const result=await exportTask;
  assert.equal(result.ok,false);assert.equal(printed,0);
  assert.match(result.error,/document changed/);
});
check('a failed conversion cleans up both temporary document buffers',()=>{
  const p=page(), files=new Map();
  p.context.moduleStub={FS:{writeFile:(name,data)=>files.set(name,data),unlink:name=>files.delete(name)},
    ccall:()=>7};
  p.run('x2t=moduleStub;');
  // Restore the real converter instead of page()'s writeback-only stub.
  vm.runInContext(script.slice(script.indexOf('function x2tConvert('),
    script.indexOf('\n// ══ DOWNLOAD AS PDF')),p.context);
  assert.throws(()=>p.run("x2tConvert('contents','source.xlsx','bin')"),/x2t returned 7/);
  assert.equal(files.has('/working/source.xlsx'),false);
  assert.equal(files.has('/working/source.xlsx.bin'),false);
});
check('the child reports the selected sheet and cell through the public builder API',()=>{
  const p=page();
  Object.assign(p.api,{GetActiveSheet:()=>({GetName:()=> 'Second sheet',
    GetSelection:()=>({GetAddress:()=> 'B2:C4'})})});
  const selected=p.run('selection()');
  assert.equal(selected.doc,'A.xlsx');assert.equal(selected.sheet,'Second sheet');assert.equal(selected.at,'B2:C4');
});
check('host ignores dirty and ready events naming a different document',()=>{
  const p=hostPage({ok:true});p.context.dirty=false;
  p.run("ooEvent({kind:'state',doc:'B.xlsx',dirty:true})");assert.equal(p.context.dirty,false);
  p.run("ooEvent({kind:'ready',doc:'B.xlsx',mtime:8})");assert.equal(p.context.ooDoc,'A.xlsx');
});
(async()=>{let failed=0;for(const [name,fn] of checks){try{await fn();console.log('OK '+name);}
  catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}
  if(failed)process.exit(1);
})();
