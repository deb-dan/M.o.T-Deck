'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
function page() {
  const nodes={}, timers=[];
  const node=id=>nodes[id]??=( {innerHTML:'',textContent:'',children:[],
    insertAdjacentHTML(_where,html){this.innerHTML+=html;}} );
  const context=vm.createContext({console,AbortController,setTimeout(fn,ms){timers.push([fn,ms]);return timers.length;},
    clearTimeout(){},Date,document:{getElementById:node,createElement(){return {
      textContent:'',get innerHTML(){return String(this.textContent).replace(/&/g,'&amp;')
        .replace(/</g,'&lt;').replace(/>/g,'&gt;');}};}},
    lastStatus:null,lastProv:{},lastHealth:{},statusFails:0,pollTimer:null,
    sseStep(){},stampFor(){},renderSidebar(){},renderSetup(){},maybeAutoSetup(){},
    showOutputLog(){},armPoll(){timers.push(['poll']);},
    healthOf:c=>c?.health||'ok',cardHTML:()=>'<card>',
    fetch:async url=>({ok:true,json:async()=>url==='/api/status'?{components:{},disk:{free_gb:0}}:{}})});
  if(source.includes('let statusRefreshPending'))vm.runInContext(
    'let statusRefreshPending=null,statusRefreshAgain=false,statusRefreshManual=false;',context);
  for(const name of ['esc','escAttr','metric','feed','refresh','refreshStatusOnce','panelReadJSON']) {
    if(new RegExp('^(?:async )?function '+name+'\\(', 'm').test(source))
      vm.runInContext(extractFunction(source,name),context);
  }
  return {context,nodes,timers,run:code=>vm.runInContext(code,context)};
}
const checks=[];function check(name,fn){checks.push([name,fn]);}
async function tick(){for(let i=0;i<20;i++)await Promise.resolve();}
check('HTTP failures retain the last complete status and schedule another poll',async()=>{
  const p=page(),previous={components:{runner:{running:true}}};p.context.lastStatus=previous;
  p.context.fetch=async()=>({ok:false,status:503,json:async()=>({error:'busy'})});
  await p.run('refresh()');assert.equal(p.context.lastStatus,previous);
  assert.equal(p.context.statusFails,1);assert(p.timers.length);
});
check('overlapping status refreshes coalesce without publishing an older snapshot last',async()=>{
  const p=page();let release,calls=0;
  p.context.fetch=async url=>{
    if(url==='/api/status'&&++calls===1)return new Promise(r=>{release=r;});
    return {ok:true,json:async()=>url==='/api/status'?{components:{},disk:{free_gb:2}}:{}};
  };
  const first=p.run('refresh()');await tick();const second=p.run('refresh(true)');await tick();
  assert.equal(calls,1);assert.equal(first,second);
  release({ok:true,json:async()=>({components:{},disk:{free_gb:1}})});
  await second;assert.equal(calls,2);assert.equal(p.context.lastStatus.disk.free_gb,2);
});
check('activity messages render model names and API errors as text',()=>{
  const p=page();p.run("feed('api', '<img src=x onerror=alert(1)>')");
  assert.doesNotMatch(p.nodes.feed.innerHTML,/<img/);assert.match(p.nodes.feed.innerHTML,/&lt;img/);
});
check('IME confirmation does not send a partially composed chat message',()=>{
  const input=source.match(/<textarea id="chat-input"[\s\S]*?<\/textarea>/)[0];
  const handler=input.match(/onkeydown="([^"]+)"/)[1];let sends=0;
  const run=new Function('event','sendChat',handler);
  run({key:'Enter',isComposing:true,preventDefault(){}},()=>sends++);
  assert.equal(sends,0);run({key:'Enter',isComposing:false,preventDefault(){}},()=>sends++);
  assert.equal(sends,1);
});
(async()=>{let failed=0;for(const [name,fn]of checks){try{await fn();console.log('OK '+name);}
catch(e){failed++;console.error('FAIL '+name+'\n'+e.stack);}}if(failed)process.exit(1);})();
