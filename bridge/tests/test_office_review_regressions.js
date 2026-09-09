'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const {extractFunction}=require('./_panel_source');
const source=fs.readFileSync(require('node:path').join(__dirname,'../panel/office.html'),'utf8');
function env(names,values={}) {
  const c=vm.createContext({...values});
  for(const name of names) vm.runInContext(extractFunction(source,name),c);
  return {c,run:code=>vm.runInContext(code,c)};
}
const tests=[];function test(name,fn){tests.push([name,fn]);}
test('editor ownership requires the currently selected document and save returns its outcome',async()=>{
  for(const success of [true,false]){
    let saves=0;
    const p=env(['editorActive','save'],{current:'A.xlsx',ooDoc:'A.xlsx',ooInstalled:true,ooReady:true,
      busyBlock:()=>false,ooSave:async()=>{saves++;return success;},
      snapshotToSave:()=>{throw Error('snapshot must not replace the live editor');}});
    assert.equal(p.run('editorActive()'),true);
    assert.equal(await p.run('save()'),success);assert.equal(saves,1);
    p.c.ooDoc='B.xlsx';assert.equal(p.run('editorActive()'),false);
    p.c.ooDoc='A.xlsx';p.c.ooReady=false;assert.equal(p.run('editorActive()'),false);
  }
});
test('duplicate sheet names retain a suffix within the Excel length limit',()=>{
  const base='x'.repeat(31), second='x'.repeat(29)+' 2';
  const p=env(['actAddSheet'],{ACT_SHEET_MAX:31,actSeq:0,snap:{sheets:{a:{name:base},b:{name:second}},sheetOrder:['a','b']},sheetIds:s=>Object.keys(s.sheets)});
  p.c.base=base; assert.equal(p.run('actAddSheet(base)'), 'x'.repeat(29)+' 3');
  assert.equal(p.c.snap.sheetOrder.length,3);
});
test('deleting one merge dimension preserves the other dimension',()=>{
  const p=env(['rcMerges']);
  p.c.merge=[{startRow:0,endRow:1,startColumn:0,endColumn:2}];
  assert.equal(JSON.stringify(p.run("rcMerges(merge,'row',1,1,true)")),JSON.stringify([{startRow:0,endRow:0,startColumn:0,endColumn:2}]));
  assert.equal(p.run("rcMerges(merge,'row',0,2,true).length"),0);
});
test('ragged editor writes never pad and erase unspecified cells',()=>{
  const p=env(['ooEditorOps','colName','ooTextForce'],{setContext:()=>({}),ooRects:()=>[]});
  const ops=p.run("ooEditorOps([{op:'set',r:0,c:0,values:[[1,2],[3],[null,4],[5,6]]}],null)");
  assert.deepEqual(JSON.parse(JSON.stringify(ops)),[
    {k:'set',at:'A1:B1',values:[[1,2]]},{k:'set',at:'A2',values:[[3]]},
    {k:'set',at:'A3:B4',values:[['',4],[5,6]]}]);
});
test('explicit formula and boolean text is protected from the editor parser',()=>{
  const p=env(['ooTextForce']);
  for(const text of ['=SUM(A1:A2)','=NOW()','TRUE','false']) {p.c.text=text;assert.equal(p.run('ooTextForce(text)'),true);}
  assert.equal(p.run("ooTextForce('Rent')"),false);
});
test('computed receipts cannot read cells from another open workbook',async()=>{
  let reads=0;
  const p=env(['csComputed'],{current:'B.xlsx',ooDoc:'B.xlsx',actNote(){},editorActive:()=>true,ooChild:{readCells(){reads++;}}});
  const result=await p.run("csComputed({}, {name:'A.xlsx',verify:[{expected:'=1+1',ref:'A1'}]})");
  assert.equal(reads,0); assert.match(result.line,/another workbook/);
});
test('a successful HTTP response without a receipt never stamps Applied',async()=>{
  let stamps=0;const notes=[];
  const p=env(['csApply','csBusy'],{fetch:async()=>({ok:true,status:200,json:async()=>({ok:true})}),
    actNote:(_,text)=>notes.push(text),bx(){},csStamp(){stamps++;}});
  p.c.card={_cs:{changeset_id:'test'},_bar:{querySelectorAll:()=>[]}};
  await p.run('csApply(card)');assert.equal(stamps,0);assert.equal(p.c.card._pending,false);
  assert.match(notes[0],/unconfirmed/);
});
test('duplicate approval clicks send one request and expiration stays final',async()=>{
  let release,count=0;const button={disabled:false};
  const p=env(['agentApprove'],{fetch:()=>{count++;return new Promise(r=>{release=r;});},bx(){},actNote(){},agentStamp(){throw Error('expired card re-stamped');}});
  p.c.card={_sid:'s',_bar:{querySelectorAll:()=>[button]}};
  const first=p.run("agentApprove(card,'once')"); await p.run("agentApprove(card,'once')");
  assert.equal(count,1);p.c.card._done=true;
  release({ok:false,status:409,json:async()=>({error:'expired'})}); await first;
  assert.equal(button.disabled,true);assert.equal(p.c.card._pending,false);
});
test('row and column changes preserve offscreen cells and dimension formatting',()=>{
  const p=env(['rcApply','rcMerges','gridRemap','usedExtent','sheetFormulas','sheetMerges','cellAt','putCell'],{RC_MAX:200});
  p.c.sheet={rowCount:1000000,columnCount:250,cellData:{0:{0:{v:'head'}},999999:{249:{v:'tail'}}},rowData:{999999:{h:42}},columnData:{249:{w:160}}};
  p.run("rcApply(sheet,'insert','row',1,1)");
  assert.equal(p.c.sheet.cellData[1000000][249].v,'tail');
  assert.equal(p.c.sheet.rowData[1000000].h,42);
  p.run("rcApply(sheet,'delete','col',1,1)");
  assert.equal(p.c.sheet.cellData[1000000][248].v,'tail');
  assert.equal(p.c.sheet.columnData[248].w,160);
  assert.equal(p.c.sheet.columnCount,249);
});
test('undo after saving restores unsaved content and redo returns to the saved state',()=>{
  const old={sheets:{a:{cellData:{0:{0:{v:'old'}}}}}}, saved={sheets:{a:{cellData:{0:{0:{v:'saved'}}}}}};
  const p=env(['histSignature','histRestore','sheetIds'],{histSaved:JSON.stringify(saved),snap:saved,activeSid:'a',dirty:false,
    lastRC:{r:1,c:1},aiSel:{},findClear(){},renderGrid(){},paint(){},histPaint(){},aiPaint(){}});
  p.c.old=old;p.c.saved=saved;
  p.run("histRestore({snap:old,sid:'a',dirty:false})"); assert.equal(p.c.dirty,true);
  p.run("histRestore({snap:saved,sid:'a',dirty:true})"); assert.equal(p.c.dirty,false);
  assert.equal(p.c.lastRC,null);
});
test('fallback save carries its read-time fence and keeps edits made during the request dirty',async()=>{
  let release,payload;
  const snap={file_mtime:5,sheets:{a:{cellData:{0:{0:{v:'original'}}}}}};
  const p=env(['histSignature','save'],{current:'A.xlsx',snap,dirty:true,mode:'grid',blobDoc:false,ooInstalled:false,ooBooting:false,extSeen:5,histSaved:null,
    busyGen:0,busyBlock:()=>false,editorActive:()=>false,snapshotToSave:()=>snap,
    busyOn(){return ++p.c.busyGen;},busyOff(){},paint(){},say(){},bx(){},bakNote:()=>'',loadFiles:async()=>{},
    fetch:(_url,opt)=>{payload=JSON.parse(opt.body);return new Promise(r=>{release=r;});}});
  const pending=p.run('save()');assert.equal(payload.expect_mtime,5);
  snap.sheets.a.cellData[0][0].v='new typing';
  release({ok:true,status:200,json:async()=>({ok:true,name:'A.xlsx',cells:1,mtime:6})});await pending;
  assert.equal(p.c.dirty,true);assert.equal(JSON.parse(p.c.histSaved).sheets.a.cellData[0][0].v,'original');
  assert.equal(snap.file_mtime,6);assert.equal(p.c.extSeen,6);
});
test('a timed-out save cannot mark the replacement document saved',async()=>{
  let release;const snap={file_mtime:1,sheets:{}};
  const p=env(['histSignature','save'],{current:'A.xlsx',snap,dirty:true,mode:'grid',blobDoc:false,ooInstalled:false,ooBooting:false,extSeen:1,histSaved:null,
    busyGen:0,busyBlock:()=>false,editorActive:()=>false,snapshotToSave:()=>snap,
    busyOn(){return ++p.c.busyGen;},busyOff(){},paint(){},say(){},bx(){},bakNote:()=>'',loadFiles:async()=>{},
    fetch:()=>new Promise(r=>{release=r;})});
  const pending=p.run('save()');p.c.busyGen++;p.c.current='B.xlsx';p.c.snap={sheets:{}};
  release({ok:true,json:async()=>({ok:true,name:'A.xlsx',mtime:2})});await pending;
  assert.equal(p.c.dirty,true);assert.equal(p.c.histSaved,null);assert.equal(p.c.extSeen,1);
});
test('AI context follows the selected editor sheet and never substitutes the first sheet',()=>{
  const p=env(['ooSelection','aiSheetId','aiSheetName','aiSelNow','sheetIds'],{current:'A.xlsx',activeSid:'one',
    editorActive:()=>true,ooChild:{selection:()=>({doc:'A.xlsx',sheet:'Second',at:'B2'})},aiSnapshot:()=>p.c.snapshot});
  p.c.snapshot={sheetOrder:['one','two'],sheets:{one:{name:'First'},two:{name:'Second'}}};
  assert.equal(p.run('aiSheetId(snapshot)'),'two');assert.equal(p.run('aiSheetName()'),'Second');assert.equal(p.run('aiSelNow()'),'B2');
  delete p.c.snapshot.sheets.two;
  assert.equal(p.run('aiSheetId(snapshot)'),null);
});
test('Find scans sparse stored cells in reading order without expanding their rectangle',()=>{
  const p=env(['findScan','cellAt','displayText','valueText'],{FIND_MAX:2,CV_BOOLEAN:3});
  p.c.sheet={cellData:{999999:{249:{v:'target'}},0:{2:{v:'target'},1:{v:'target'}}}};
  assert.equal(JSON.stringify(p.run("findScan(sheet,'target')")),JSON.stringify([{r:0,c:1},{r:0,c:2}]));
});
test('Unicode lowercasing cannot shift replacement into neighboring characters',()=>{
  const p=env(['findReplaceText']);
  const result=p.run("findReplaceText('İstanbul, i', 'i', 'X')");
  assert.equal(result.text,'Xstanbul, X');assert.equal(result.n,2);
});
test('numeric strings beyond Excel precision remain text',()=>{
  const p=env(['coNum']);
  assert.equal(p.run("coNum('9007199254740993')"),null);
  assert.equal(p.run("coNum('12.345678901234567')"),null);
  assert.equal(p.run("coNum('1000000000000000')"),1000000000000000);
});
test('viewport growth and disk timestamps do not turn a clean undo into unsaved work',()=>{
  const p=env(['histSignature']);
  assert.equal(p.run("histSignature({file_mtime:1,sheets:{a:{rowCount:20,columnCount:10,cellData:{}}}})"),
    p.run("histSignature({file_mtime:2,sheets:{a:{rowCount:200,columnCount:30,cellData:{}}}})"));
});
test('sort moves row formatting and distant cells together without a dense rectangle',()=>{
  const p=env(['sortRemap','gridRemap','cellAt','putCell']);
  p.c.sheet={cellData:{0:{0:{v:'b'},16383:{v:'wide'}},1:{0:{v:'a'}}},rowData:{0:{h:40},1:{h:20}}};
  p.run('sortRemap(sheet,[1,0],2,16384)');
  assert.equal(p.c.sheet.cellData[1][16383].v,'wide');
  assert.equal(p.c.sheet.rowData[1].h,40);assert.equal(p.c.sheet.rowData[0].h,20);
});
test('style edits retain explicit false flags instead of silently dropping removal',()=>{
  const p=env(['actStyleSet'],{ACT_HT:{},ACT_VT:{},actColor:()=>null});
  assert.equal(JSON.stringify(p.run("actStyleSet({bl:false,it:0,ul:{s:0},st:false})")),
    JSON.stringify({bl:0,it:0,ul:{s:0},st:{s:0}}));
  assert.equal(p.run("actStyleSet({bl:'false',ul:'true'})"),null);
});
test('Save & go home stays with its original document across an asynchronous save',async()=>{
  let action, release, closes=0;
  const p=env(['goStart'],{current:'A.xlsx',documentGen:1,dirty:true,startArmed:null,DISCARD_MIN_MS:400,
    bx(){},say:(_text,_kind,a)=>{action=a;},setTimeout(){},mi_close(){closes++;},
    save:()=>new Promise(r=>{release=r;})});
  p.run('goStart()');const pending=action.run();
  p.c.current='B.xlsx';p.c.documentGen++;p.c.dirty=false;release(true);await pending;
  assert.equal(closes,0);
});
test('a refused save cannot close a document even if the global dirty flag changed',async()=>{
  let action,closes=0;
  const p=env(['goStart'],{current:'A.xlsx',documentGen:1,dirty:true,startArmed:null,DISCARD_MIN_MS:400,
    bx(){},say:(_text,_kind,a)=>{action=a;},setTimeout(){},mi_close(){closes++;},
    save:async()=>{p.c.dirty=false;return false;}});
  p.run('goStart()');await action.run();assert.equal(closes,0);
});
test('a discard confirmation cannot transfer to another document',()=>{
  const p=env(['confirmDiscard'],{current:'A.xlsx',documentGen:1,dirty:true,discardArmed:'C.xlsx',
    discardGeneration:0,discardToken:0,discardAt:0,DISCARD_MIN_MS:400,say(){},setTimeout(){}});
  assert.equal(p.run("confirmDiscard('C.xlsx')"),false);
  assert.equal(p.c.discardGeneration,1);
});
test('an editor destination mismatch cannot fall through to stale snapshot saving',async()=>{
  const messages=[];
  const p=env(['save'],{current:'B.xlsx',busyBlock:()=>false,editorActive:()=>false,ooInstalled:true,
    ooReady:true,ooDoc:'A.xlsx',say:s=>messages.push(s),fetch(){throw Error('unexpected disk write');}});
  assert.equal(await p.run('save()'),false);assert.match(messages[0],/out of sync/);
});
test('multi-sheet computed receipts read each formula from its own sheet',async()=>{
  const reads=[];
  const p=env(['csComputed','csComputedText'],{current:'A.xlsx',ooDoc:'A.xlsx',editorActive:()=>true,bx(){},actDet:()=>({}),
    ooChild:{readCells:(refs,sheet)=>{reads.push([refs.join(','),sheet]);return {ok:true,cells:refs.map(ref=>({ref,value:7,text:'7'}))};}}});
  p.c.card={_head:{appendChild(){}}};
  const result=await p.run("csComputed(card,{name:'A.xlsx',verify:[{sheet:'One',ref:'A1',expected:'=1+6'},{sheet:'Two',ref:'A1',expected:'=3+4'}]})");
  assert.deepEqual(reads,[['A1','One'],['A1','Two']]);assert.match(result.line,/One!A1=7/);assert.match(result.line,/Two!A1=7/);
  assert.equal(p.run("csComputedText([{ref:'A1',text:'',value:null}],false).bad"),1);
  assert.match(p.run("csComputedText([{ref:'A1',text:'',value:null}],false).line"),/empty/);
});
test('session naming retries the captured durable row and never names a replacement',async()=>{
  let release;const requests=[];
  const p=env(['agentName'],{agentStored:'old',agentNamed:false,agentNaming:false,AGENT_SESSION_NAME:'loffice',bx(){},
    fetch:(url)=>{requests.push(url);if(requests.length===1)return new Promise(r=>{release=r;});return Promise.resolve({ok:true,status:200,json:async()=>({ok:true})});}});
  const pending=p.run('agentName()');p.c.agentStored='new';release({ok:false,status:409,json:async()=>({})});await pending;
  assert.deepEqual(requests,['/api/hermes/session/old/rename','/api/hermes/session/old/rename']);assert.equal(p.c.agentNamed,false);
});
test('a late stored-history response cannot erase the replacement transcript',async()=>{
  let release,removals=0;
  const p=env(['agentRestoreHistory'],{agentStored:'old',agentHistoryRestoredFor:'',agentHistoryLoading:false,agentHistoryRequest:0,
    aiStatus(){},aiPaint(){},bx(){},el:()=>({querySelectorAll:()=>[{remove(){removals++;}}]}),fetch:()=>new Promise(r=>{release=r;})});
  const pending=p.run('agentRestoreHistory()');p.c.agentStored='new';p.c.agentHistoryRequest++;p.c.agentHistoryLoading=true;
  release({ok:true,json:async()=>({history:[]})});await pending;
  assert.equal(removals,0);assert.equal(p.c.agentHistoryLoading,true);assert.equal(p.c.agentHistoryRestoredFor,'');
});
test('stale changeset reads cannot queue outcomes in a replacement conversation',async()=>{
  let release;const notes=[];
  const p=env(['csRead'],{csReadRequest:0,documentGen:1,agentSid:'old',agentStored:'stored',current:'A.xlsx',csPolls:0,bx(){},csNote:line=>notes.push(line),
    fetch:()=>new Promise(r=>{release=r;})});
  const pending=p.run('csRead()');p.c.agentSid='new';
  release({ok:true,json:async()=>({ok:true,session_lines:['old outcome'],changeset:{changeset_id:'old'}})});
  assert.equal(await pending,null);assert.deepEqual(notes,[]);
});
test('an Agent turn stays busy until its changeset and naming work finish',async()=>{
  let release,requests=0,namingBusy;
  const input={value:'hello'}, log={scrollTop:0,scrollHeight:0}, turn={wrap:{appendChild(){}},body:{parentNode:{},textContent:''}};
  const p=env(['agentSend','aiBusyBlock'],{aiBusy:false,aiBusyAt:0,agentHistoryLoading:false,agentEnv:{},agentSid:'s',agentStored:'stored',
    agentCatalogNotice:'',agentCatalogPending:'',aiCtxOn:false,current:'A.xlsx',AI_Q_MAX:100,AGENT_USER_MARKER:'USER:',LANE_AGENT:'agent',csLines:[],
    agentGate:()=>({ok:true}),aiStale:()=>false,agentBrief:()=>'',aiSheetName:()=>'',csPrefix:()=>'',bx(){},aiGrow(){},aiStatus(){},aiPaint(){},
    el:id=>id==='ai-in'?input:log,aiAdd:()=>turn,agentExpire(){},aiRenderBody(){},extCheck(){},AbortController,TextDecoder,
    agentFrame:()=>({delta:'answer'}),csAfterTurn:()=>new Promise(r=>{release=r;}),agentName:async()=>{namingBusy=p.c.aiBusy;},
    fetch:async()=>{requests++;return {ok:true,body:{getReader:()=>({read:async()=>({value:new TextEncoder().encode('data: {}\n\ndata: [DONE]\n\n'),done:false}),cancel:async()=>{}})}};}});
  const pending=p.run('agentSend()');for(let i=0;i<12&&!release;i++)await Promise.resolve();
  assert.ok(release);assert.equal(p.c.aiBusy,true);input.value='second';await p.run('agentSend()');assert.equal(requests,1);
  release(null);await pending;assert.equal(namingBusy,true);assert.equal(p.c.aiBusy,false);assert.equal(input.value,'second');
});
test('failed external reload retains dirty edits and retries the observed change',async()=>{
  let actions;
  const p=env(['extAct'],{documentGen:1,current:'A.xlsx',dirty:true,extSeen:20,extAsking:false,extCopy:'',msgGen:1,
    ooExtReload:async()=>false,say:(_text,_style,buttons)=>{if(buttons)actions=buttons;},paint(){},bx(){}});
  p.run("extAct({act:'ask',text:'changed',previousSeen:10},'A.xlsx')");
  await actions[0].run();assert.equal(p.c.dirty,true);assert.equal(p.c.extSeen,10);
  p.c.extSeen=20;await p.run("extAct({act:'reload',text:'reloaded',previousSeen:10},'A.xlsx')");assert.equal(p.c.extSeen,10);
});
test('an old external-change banner cannot discard a reopened workbook',async()=>{
  let actions,reloads=0;
  const p=env(['extAct'],{documentGen:1,current:'A.xlsx',dirty:true,extSeen:20,extAsking:false,extCopy:'',msgGen:1,
    ooExtReload:async()=>{reloads++;return true;},say:(_text,_style,buttons)=>{if(buttons)actions=buttons;},paint(){},bx(){}});
  p.run("extAct({act:'ask',text:'changed'},'A.xlsx')");p.c.documentGen=3;
  await actions[0].run();actions[1].run();assert.equal(reloads,0);assert.equal(p.c.dirty,true);
});
(async()=>{for(const [name,fn] of tests){await fn();console.log('OK '+name);}})().catch(e=>{console.error(e);process.exit(1);});
