/* Recovered-turn AbortController semantics.
 *
 * A user Stop intentionally aborts the recovery fetch after forceEndTurn has
 * stamped the turn interrupted.  That abort must not be rendered as a bridge
 * recovery failure.  A real reader failure still must be visible.  Exercise both
 * the Chat/Agent and Hermes recovery entry points so their predicates cannot drift.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const statuses = [];
const observedStages = [];
class El {
  constructor(tag='div') {
    this.tagName = tag; this.children = []; this.textContent = ''; this.hidden = false;
    this.className = ''; this.style = {}; this._nodes = {};
  }
  appendChild(node){ this.children.push(node); return node; }
  insertBefore(node){ this.children.push(node); return node; }
  remove(){ this.removed = true; }
  setAttribute(name, value){ this[name] = String(value); }
  querySelector(selector){
    if (!this._nodes[selector]) this._nodes[selector] = new El(selector);
    return this._nodes[selector];
  }
  querySelectorAll(){ return []; }
}

const button = new El('button');
global.window = {};
global.document = {
  createElement: tag => new El(tag),
  getElementById: id => id === 'chat-send' ? button : new El(id),
};
global.localStorage = {getItem(){ return null; }, setItem(){}, removeItem(){}};
global.chatPane = {mode:'chat', sid:'direct-session', busy:false, curTurn:null,
  hermesSid:'', hermesStoredSid:''};
global.addMsg = () => {
  const holder = new El('article');
  holder._nodes['.body'] = new El('div');
  holder._nodes['.who'] = new El('span');
  return holder;
};
global.chatStatus = (_holder, mark, value) => statuses.push([mark, value]);
global.sendPaint = global.scrollChat = global.loadSessions = global.chatSummary =
  global.chatToolErrsRedraw = global.renderChatBody = global.chatInspect =
  global.chatApproval = global.chatAsk = global.expireAskCard = global.fileCard =
  global.chatToolErr = global.turnStage = global.turnArm = () => {};
global.liveModelLabel = value => value;
global.esc = global.escAttr = value => String(value);
global.openExt = () => {};
global.TURN_STALL_MS = 75000;

const source = fs.readFileSync(
  path.join(__dirname, '..', 'panel', 'assets', 'turn-stream.js'), 'utf8');
vm.runInThisContext(source, {filename:'turn-stream.js'});
const H = window.HarnessTurnStream;

function brokenResponse(intentional) {
  return {ok:true, status:200, body:{getReader(){ return {async read(){
    observedStages.push(chatPane.curTurn && chatPane.curTurn.stage);
    if (intentional && chatPane.curTurn) chatPane.curTurn.ended = true;
    throw new Error(intentional ? 'AbortError' : 'socket broke');
  }}; }}};
}

async function direct(intentional) {
  statuses.length = 0;
  chatPane.mode = 'chat'; chatPane.sid = 'direct-session';
  chatPane.busy = false; chatPane.curTurn = null;
  global.fetch = async () => brokenResponse(intentional);
  await H.recover({id:'direct-turn', instance:'bridge'}, 'chat', 'direct-session');
  return statuses.some(([, value]) => value.includes('could not recover this turn'));
}

async function hermes(intentional) {
  statuses.length = 0;
  chatPane.mode = 'hermes'; chatPane.hermesStoredSid = 'stored-session';
  chatPane.busy = false; chatPane.curTurn = null;
  global.fetch = async () => brokenResponse(intentional);
  await H.recoverHermes({id:'hermes-turn', session_id:'live-session',
    stored_id:'stored-session', user:'hello'}, []);
  return statuses.some(([, value]) => value.includes('could not recover this Hermes turn'));
}

async function main(){
  observedStages.length = 0;
  if (await direct(true)) throw new Error('intentional Direct abort was mislabeled');
  if (!(await direct(false))) throw new Error('real Direct recovery failure was hidden');
  if (await hermes(true)) throw new Error('intentional Hermes abort was mislabeled');
  if (!(await hermes(false))) throw new Error('real Hermes recovery failure was hidden');
  if (observedStages.length !== 4 || observedStages.some(value => value !== 'reconnecting'))
    throw new Error('a recovered turn lost its reconnecting diagnostic stage');
  console.log('OK — recovered-turn Stop aborts stay interrupted; real failures stay visible');
}

main().catch(error => { console.error('FAIL — ' + error.message); process.exit(1); });
