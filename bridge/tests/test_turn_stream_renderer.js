/* Executable contract for the complete event grammar M.O.T currently renders. */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const calls = [];
class El {
  constructor(tag){
    this.tagName = tag; this.children = []; this.textContent = ''; this.hidden = false;
    this.open = false; this.className = ''; this.style = {}; this._nodes = {};
    this.classList = {toggle(){}};
  }
  appendChild(node){ this.children.push(node); return node; }
  insertBefore(node){ this.children.push(node); return node; }
  remove(){ this.removed = true; }
  set innerHTML(value){
    this._html = value;
    if (value.includes('class="tbody"')) this._nodes['.tbody'] = new El('div');
    if (value.includes('class="slist"')) this._nodes['.slist'] = new El('div');
    if (value.includes('<summary>')) this._nodes.summary = new El('summary');
  }
  get innerHTML(){ return this._html || ''; }
  querySelector(selector){ return this._nodes[selector] || null; }
  querySelectorAll(selector){ return selector === '.toolerr' ? [] : []; }
}

global.window = {};
global.document = {createElement: tag => new El(tag), getElementById: () => new El('button')};
global.localStorage = {setItem(){}};
global.chatPane = {busy:true, curTurn:null, model:'', hermesSid:'', hermesStoredSid:''};
global.turnStage = value => calls.push(['stage', value]);
global.turnArm = () => calls.push(['arm']);
global.chatInspect = (_holder, value) => calls.push(['inspect', value.type || 'delta']);
global.chatSummary = () => calls.push(['summary']);
global.chatStatus = (_holder, mark, value) => calls.push(['status', mark, value]);
global.chatApproval = (_holder, req, sid) => calls.push(['approval', req.command, sid]);
global.chatAsk = (_holder, req, sid) => calls.push(['ask', req.question, sid]);
global.expireAskCard = (_holder, id) => calls.push(['ask_expire', id]);
global.fileCard = (_holder, value) => calls.push(['file', value.path]);
global.chatToolErr = (_holder, tool, why) => calls.push(['tool_error', tool, why]);
global.chatToolErrsRedraw = () => calls.push(['tool_redraw']);
global.renderChatBody = () => calls.push(['render']);
global.liveModelLabel = value => value;
global.scrollChat = () => {};
global.esc = value => String(value);
global.escAttr = value => String(value);
global.openExt = () => {};
global.sendPaint = () => {};
global.loadSessions = () => {};
global.addMsg = () => { throw new Error('recover DOM setup is not part of this renderer grammar test'); };
global.hermesStop = () => {};
global.forceEndTurn = () => {};
global.TURN_STALL_MS = 75000;

const source = fs.readFileSync(path.join(__dirname, '..', 'panel', 'assets', 'turn-stream.js'), 'utf8');
vm.runInThisContext(source, {filename:'turn-stream.js'});

function response(events, separator='\n\n', chunkSizes=[]){
  const bytes = new TextEncoder().encode(events.map(value =>
    'data: ' + JSON.stringify(value) + separator).join(''));
  let offset = 0, chunk = 0;
  return {ok:true, status:200, body:{getReader(){ return {async read(){
    if (offset >= bytes.length) return {done:true};
    const size = chunkSizes[chunk++] || bytes.length;
    const value = bytes.slice(offset, Math.min(bytes.length, offset + size));
    offset += value.length;
    return {done:false, value};
  }}; }}};
}

function rawResponse(wire, chunkSizes=[]){
  const bytes = new TextEncoder().encode(wire);
  let offset = 0, chunk = 0;
  return {ok:true, status:200, body:{getReader(){ return {async read(){
    if (offset >= bytes.length) return {done:true};
    const size = chunkSizes[chunk++] || bytes.length;
    const value = bytes.slice(offset, Math.min(bytes.length, offset + size));
    offset += value.length;
    return {done:false, value};
  }}; }}};
}

async function main(){
  const holder = new El('article');
  const body = new El('div'), who = new El('span'), think = new El('div');
  holder._nodes['.body'] = body; holder._nodes['.who'] = who;
  const turn = {lane:'agent', hermesSid:'hermes-1', lastSeq:0, timer:null, done:false};
  chatPane.curTurn = turn;
  const grammar = [
    {seq:1, delta:'reason', thinking:true},
    {seq:2, delta:'answer'},
    {seq:3, type:'model_actual', model:'model-1'},
    {seq:4, type:'hermes_session', id:'hermes-2', stored_id:'stored-2'},
    {seq:5, type:'hermes_status', text:'working'},
    {seq:6, type:'approval', request:{command:'pwd'}},
    {seq:7, type:'ask', request:{question:'continue?'}},
    {seq:8, type:'ask_expire', request_id:'ask-1'},
    {seq:9, type:'file_card', path:'/Users/debik/result.txt'},
    {seq:10, type:'guard_flag', path:'/Users/debik/outside.txt'},
    {seq:11, type:'tool_start', tool:'search'},
    {seq:12, type:'tool_output', tool:'search', is_error:true, error:'denied'},
    {seq:13, type:'web_sources', data:[{url:'https://example.com', title:'Example'}]},
    {seq:14, type:'vision', source:'precaption', model:'vision-1'},
    {seq:15, type:'proxy_error', error:'upstream'},
    {seq:16, type:'future_upstream_event', detail:'inspect-only'},
    {seq:17, type:'terminal', state:'completed'},
  ];
  await window.MOTDeckTurnStream.consume(response(grammar), {turn, holder, body, think});

  const has = name => calls.some(call => call[0] === name);
  for (const name of ['approval','ask','ask_expire','file','tool_error','render','tool_redraw'])
    if (!has(name)) throw new Error('renderer dropped the ' + name + ' event');
  if (!holder._guardFlags || !holder._guardFlags.has('/Users/debik/outside.txt'))
    throw new Error('renderer dropped the path-guard provenance event');
  if (!holder._visionLine) throw new Error('renderer dropped the vision provenance event');
  if (!holder.children.some(node => node.className === 'sources'))
    throw new Error('renderer dropped web sources');
  if (!calls.some(call => call[0] === 'inspect' && call[1] === 'future_upstream_event'))
    throw new Error('unknown upstream events stopped being inspect-visible');
  if (body.textContent !== 'answer\n[proxy error: upstream]')
    throw new Error('delta/proxy text changed: ' + JSON.stringify(body.textContent));
  if (!turn.done || turn.lastSeq !== 17) throw new Error('terminal/cursor state was not committed');

  const crlfHolder = new El('article'), crlfBody = new El('div'), crlfThink = new El('div');
  const crlfTurn = {lane:'chat', lastSeq:0, timer:null, done:false};
  chatPane.curTurn = crlfTurn; chatPane.busy = true;
  await window.MOTDeckTurnStream.consume(
    response([{seq:1, delta:'crlf'}, {seq:2, type:'terminal', state:'completed'}],
             '\r\n\r\n', [19, 1, 2, 7]),
    {turn:crlfTurn, holder:crlfHolder, body:crlfBody, think:crlfThink});
  if (crlfBody.textContent !== 'crlf' || !crlfTurn.done || crlfTurn.lastSeq !== 2)
    throw new Error('CRLF/chunk-split SSE framing did not complete');

  const byteHolder = new El('article'), byteBody = new El('div'), byteThink = new El('div');
  const byteTurn = {lane:'chat', lastSeq:0, timer:null, done:false};
  chatPane.curTurn = byteTurn; chatPane.busy = true;
  const byteWire = ': keepalive\rdata:{"seq":1,"delta":"héllo",\r'
    + 'data:"thinking":false}\r\rdata:{"seq":2,"type":"terminal","state":"completed"}';
  await window.MOTDeckTurnStream.consume(
    rawResponse(byteWire, Array(new TextEncoder().encode(byteWire).length).fill(1)),
    {turn:byteTurn, holder:byteHolder, body:byteBody, think:byteThink});
  if (byteBody.textContent !== 'héllo' || !byteTurn.done || byteTurn.lastSeq !== 2)
    throw new Error('bare-CR/data-without-space/multiline/UTF-8 SSE grammar changed');

  const errHolder = new El('article'), errBody = new El('div'), errThink = new El('div');
  const errTurn = {lane:'hermes', lastSeq:0, timer:null, done:false};
  chatPane.curTurn = errTurn; chatPane.busy = true;
  await window.MOTDeckTurnStream.consume(
    rawResponse('event: error\r\ndata:{"error":"upstream won"}\r\n\r\ndata: [DONE]\r\n\r\n'),
    {turn:errTurn, holder:errHolder, body:errBody, think:errThink});
  if (!errTurn.done || !errBody.textContent.includes('upstream won'))
    throw new Error('named upstream error did not win over a later DONE frame');

  const sentinelBody = new El('div'), sentinelTurn = {lane:'hermes', lastSeq:0,
    timer:null, done:false};
  chatPane.curTurn = sentinelTurn; chatPane.busy = true;
  await window.MOTDeckTurnStream.consume(rawResponse('event: error\ndata:[DONE]\n\n'),
    {turn:sentinelTurn, holder:new El('article'), body:sentinelBody, think:new El('div')});
  if (!sentinelTurn.done || !sentinelBody.textContent.includes('error sentinel'))
    throw new Error('named error sentinel was reported as successful completion');

  const badTurn = {lane:'chat', lastSeq:0, timer:null, done:false};
  chatPane.curTurn = badTurn; chatPane.busy = true;
  let malformedFailed = false;
  try {
    await window.MOTDeckTurnStream.consume(rawResponse('data: {"seq":1,"delta":'),
      {turn:badTurn, holder:new El('article'), body:new El('div'), think:new El('div')});
  } catch (error) { malformedFailed = /unreadable event/.test(error.message); }
  if (!malformedFailed) throw new Error('malformed final SSE event was silently accepted');

  const utf8 = new Uint8Array([100,97,116,97,58,32,0xe2,0x82]);
  const utf8Response = {ok:true, status:200, body:{getReader(){ let sent=false; return {
    async read(){ if (sent) return {done:true}; sent=true; return {done:false,value:utf8}; }
  }; }}};
  let utf8Failed = false;
  try {
    await window.MOTDeckTurnStream.consume(utf8Response,
      {turn:{lane:'chat',lastSeq:0,timer:null,done:false}, holder:new El('article'),
       body:new El('div'), think:new El('div')});
  } catch (error) { utf8Failed = /encoding|encoded data|utf-8/i.test(error.message); }
  if (!utf8Failed) throw new Error('incomplete UTF-8 was silently accepted');
  console.log('OK — M.O.T-supported Agent event grammar survives the shared live/replay renderer');
}

main().catch(error => { console.error('FAIL — ' + error.message); process.exit(1); });
