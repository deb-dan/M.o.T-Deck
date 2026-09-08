'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');

function page(lane) {
  const html = fs.readFileSync(path.join(__dirname, '../panel/' + lane + '.html'), 'utf8');
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  const source = scripts.at(-1)[1].split('(async function boot()')[0];
  const nodes = new Map(), sockets = [];
  const element = id => {
    if (!nodes.has(id)) nodes.set(id, {textContent:'', innerHTML:'', style:{},
      classList:{add(){}, remove(){}}, remove(){}, removeAttribute(){}});
    return nodes.get(id);
  };
  class Socket {
    constructor(){ this.readyState=0; this.closed=false; sockets.push(this); }
    send(){} close(){ this.closed=true; this.readyState=2; }
  }
  class Terminal {
    constructor(){ this.cols=80; this.rows=24; this.output=[]; }
    open(){} onData(){} reset(){ this.output=[]; } focus(){}
    write(data){ this.output.push(data); }
  }
  const ctx = {console, TextEncoder, Uint8Array, WebSocket:Socket,
    window:{Terminal, addEventListener(){}},
    document:{getElementById:element, addEventListener(){}, querySelectorAll(){return [];}},
    location:{host:'127.0.0.1:8700'}, requestAnimationFrame(){return 1;},
    cancelAnimationFrame(){}, setInterval(){return 1;}, clearInterval(){},
    fetch:async () => ({ok:true, json:async () => ({ok:true, sessions:[], store:{count:0}})}),
  };
  vm.createContext(ctx);
  vm.runInContext(source + '\nthis.api={start,loadSessions:typeof loadSessions===\'function\'?loadSessions:null, getSocket:()=>sock, getTerm:()=>term, arm:()=>{armed="chosen";}};',ctx);
  return {ctx, element, sockets, api:ctx.api};
}

(async () => {
  for (const lane of ['aider','goose']) {
    {
      const p=page(lane); p.api.start(); const first=p.api.getSocket(); first.readyState=1;
      p.ctx.fetch=async url => url.endsWith('/end')
        ? {ok:false,status:503,json:async()=>({error:'stop refused'})}
        : {ok:true,json:async()=>({ok:true,sessions:[],store:{count:0}})};
      await p.element('btn-stop').onclick();
      assert.equal(first.closed,false,lane+': failed End detached the running session');
      assert.equal(p.element('btn-stop').disabled,false,lane+': End cannot be retried');
    }
    {
      const p=page(lane); p.api.start(); const old=p.api.getSocket(); old.readyState=2;
      p.api.start(); const next=p.api.getSocket(); next.readyState=1;
      old.onmessage({data:'stale bytes'}); old.onerror(); old.onclose({code:1006,reason:''});
      assert.equal(p.api.getSocket(),next,lane+': old close discarded the new socket');
      assert.deepEqual(Array.from(p.api.getTerm().output),[],lane+': old output corrupted the new terminal');
      assert.equal(p.element('msg').textContent,'',lane+': old failure overwrote current status');
    }
    {
      const p=page(lane); p.api.start(); const old=p.api.getSocket(); old.readyState=1;
      let resolveEnd;
      p.ctx.fetch=url => url.endsWith('/end')
        ? new Promise(resolve=>{resolveEnd=resolve;})
        : Promise.resolve({ok:true,json:async()=>({ok:true,sessions:[],store:{count:0}})});
      const pending=p.element('btn-stop').onclick(); old.readyState=2;
      p.api.start(); const next=p.api.getSocket(); next.readyState=1;
      resolveEnd({ok:true,json:async()=>({ok:true})}); await pending;
      assert.equal(next.closed,false,lane+': old End receipt detached a new connection');
    }
  }
  const p=page('goose'); let complete;
  p.ctx.fetch=()=>new Promise(resolve=>{complete=resolve;});
  const pending=p.api.loadSessions(); p.api.arm();
  p.element('s-row').innerHTML='armed session controls';
  complete({ok:true,json:async()=>({sessions:[],store:{count:0}})}); await pending;
  assert.equal(p.element('s-row').innerHTML,'armed session controls','late history refresh moved armed delete controls');
  console.log('OK — terminal connection ownership, failed End retry and armed history preservation');
})().catch(error=>{console.error(error);process.exit(1);});
