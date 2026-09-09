'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(path.join(__dirname,'../panel/index.html'),'utf8');
function page(names,extra={}) {
  const nodes={},created=[];
  function element(tag='DIV') {
    const e={tagName:tag.toUpperCase(),style:{},dataset:{},children:[],fields:{},value:'',paused:true,
      classList:{add(){},remove(){}},appendChild(c){this.children.push(c);},contains:()=>false,
      play(){this.plays=(this.plays||0)+1;return Promise.resolve();},
      querySelector(sel){if(sel.startsWith('#'))return this.fields[sel.slice(1)]||null;
        for(const c of this.children){if(c.tagName===sel.toUpperCase())return c;const found=c.querySelector(sel);if(found)return found;}return null;},
      set innerHTML(value){this.html=value;this.children=[];this.fields={};
        for(const m of value.matchAll(/<(input|textarea|select)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
          const f=element(m[1]);f.id=m[3];f.value=(/\bvalue="([^"]*)"/.exec(m[2])||[])[1]||'';
          if(f.tagName==='SELECT'){f.options=[{value:'wav'},{value:'mp3'}];f.value='wav';}
          this.fields[f.id]=f;nodes[f.id]=f;
        }
      },get innerHTML(){return this.html||'';}};
    return e;
  }
  for(const id of ['music-create-wrap','music-create','music-outdir','music-library','music-libcount'])nodes[id]=element();
  const document={activeElement:null,getElementById:id=>nodes[id]||null,createElement:tag=>{const e=element(tag);created.push(e);return e;}};
  const c=vm.createContext({document,musicSnap:{dir:'/songs',engines:[{engine:'one',installed:true},{engine:'two',installed:true}],formats:{one:['wav','mp3'],two:['wav']}},
    musicEngine:'one',musicView:'classic',musicSaveTpl:false,MUSIC_TA_BASE:62,musicErr:'',musicWarn:'',musicLib:[],musicPlay:'',musicPromptOpen:new Set(),
    esc:String,escAttr:String,apiArg:JSON.stringify,growMusicInput(){},musicPaintState(){},musicTrackMeta:()=>'',...extra});
  for(const name of names)vm.runInContext(extractFunction(source,name),c);
  return {c,nodes,created,run:code=>vm.runInContext(code,c)};
}
const form=page(['musicEngines','musicInstalled','musicJob','musicRunning','musicStudio','musicSecs','musicSyncSecs','musicRememberDraft','renderMusicCreate','musicPick']);
form.run('renderMusicCreate()');
for(const [id,value] of Object.entries({'mus-prompt':'my draft','mus-lyrics':'verse','mus-secs':'45','mus-steps':'8','mus-seed':'0','mus-fmt':'mp3'}))form.nodes[id].value=value;
form.c.musicSaveTpl=true;form.run('renderMusicCreate()');
assert.equal(form.nodes['mus-prompt'].value,'my draft');assert.equal(form.nodes['mus-lyrics'].value,'verse');assert.equal(form.nodes['mus-seed'].value,'0');
form.nodes['mus-tplname'].value='template draft';form.c.musicView='studio';form.run('renderMusicCreate()');
assert.equal(form.nodes['mus-tplname'].value,'template draft');assert.equal(form.nodes['mus-fmt'].value,'mp3');
form.run("musicPick('two')");assert.equal(form.nodes['mus-prompt'].value,'my draft');assert.equal(form.nodes['mus-secs'].value,'45');
const dir=page(['renderMusicOutDir']);dir.nodes['mus-dir']={value:'/half typed'};
dir.nodes['music-outdir'].html='editing';dir.run('renderMusicOutDir()');assert.equal(dir.nodes['music-outdir'].innerHTML,'editing');
dir.run('renderMusicOutDir(true)');assert.match(dir.nodes['music-outdir'].innerHTML,/saving to/);
const lib=page(['renderMusicLibrary'],{musicLib:[{name:'song.wav',ext:'wav',prompt:'a song'}]});
lib.run('renderMusicLibrary()');const player=lib.nodes['music-library'].querySelector('audio');player.currentTime=42;player.paused=false;
lib.c.musicPromptOpen.add('song.wav');lib.run('renderMusicLibrary()');
assert.equal(lib.nodes['music-library'].querySelector('audio'),player);assert.equal(player.currentTime,42);assert.equal(lib.created.filter(e=>e.tagName==='AUDIO').length,1);
(async()=>{
  let release;const p=page(['loadMusicLibrary'],{musicLibraryRequest:0,renderMusicLibrary(){},renderMusicHero(){},renderMusicTemplates(){},
    fetch:()=>new Promise(r=>{release=r;})});
  const pending=p.run('loadMusicLibrary()');p.c.musicSnap.dir='/other';release({ok:true,json:async()=>({ok:true,tracks:[{name:'wrong folder'}]})});await pending;
  assert.equal(p.c.musicLib.length,0);
  console.log('PASS Music Classic retains form drafts, folder editing, audio playback and library request identity');
})().catch(e=>{console.error(e);process.exitCode=1;});
