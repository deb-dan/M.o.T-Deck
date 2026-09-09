'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
const nodes={'mb-q':{value:'first'},'mb-results':{innerHTML:''},'mb-fmt':{value:'gguf'},'mb-sort':{value:'downloads'},
  'as-q':{value:'first'},'as-kind':{value:'tts'},'as-results':{innerHTML:''}};
const requests=[];
const c=vm.createContext({document:{getElementById:id=>nodes[id],querySelectorAll:()=>[]},
  hfSearchRequest:0,audioSearchRequest:0,audioProbeRequest:0,asSel:'',esc:String,markAudioHfRows(){},
  fetch:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))});
for(const name of ['hfSearch','audioSearch','audioProbe'])vm.runInContext(extractFunction(source,name),c);
const reply=value=>({ok:true,json:async()=>value});
(async()=>{
  const old=c.hfSearch();nodes['mb-q'].value='second';nodes['mb-fmt'].value='mlx';const newer=c.hfSearch();
  requests[1].resolve(reply([]));await newer;const visible=nodes['mb-results'].innerHTML;
  requests[0].reject(Error('old failure'));await old;assert.equal(nodes['mb-results'].innerHTML,visible);assert.match(visible,/MLX/);
  const prior=c.audioSearch();nodes['as-q'].value='second';const recent=c.audioSearch();
  requests[3].resolve(reply({error:'current search error'}));await recent;
  requests[2].resolve(reply([]));await prior;assert.match(nodes['as-results'].innerHTML,/current search error/);
  const card={hidden:true,innerHTML:''};const probe=c.audioProbe({repo:'owner/wanted'}, {},card);
  requests[4].resolve(reply({repo:'owner/different',can_get:true}));await probe;
  assert.match(card.innerHTML,/different model/);assert.doesNotMatch(card.innerHTML,/hfget/);
  console.log('PASS model searches discard stale results and probes refuse mismatched repositories');
})().catch(e=>{console.error(e);process.exitCode=1;});
