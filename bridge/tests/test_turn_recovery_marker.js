/* Executable contract for U31's metadata-only bridge-restart marker. */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const memory = new Map();
global.window = {};
global.localStorage = {
  getItem:key => memory.has(key) ? memory.get(key) : null,
  setItem:(key, value) => memory.set(key, String(value)),
  removeItem:key => memory.delete(key)
};
global.document = {createElement(){ return {}; }, getElementById(){ return null; }};
global.chatPane = {busy:false, curTurn:null};
global.turnStage = global.chatSummary = global.chatToolErrsRedraw = global.renderChatBody = () => {};

const source = fs.readFileSync(path.join(__dirname, '..', 'panel', 'assets', 'turn-stream.js'), 'utf8');
vm.runInThisContext(source, {filename:'turn-stream.js'});
const H = window.MOTDeckTurnStream;

let failures = 0;
function check(label, value){
  console.log((value ? 'PASS ' : 'FAIL ') + label);
  if (!value) failures += 1;
}
function reply(status, value){
  return {ok:status >= 200 && status < 300, status,
    async json(){ return value; }};
}

async function journey(){
  const turn = {id:'turn-1', lane:'chat', session:'session-1', instance:'old-bridge'};
  H.remember(turn);
  check('the marker contains metadata but no prompt or events', (() => {
    const raw = [...memory.values()].join(' ');
    return raw.includes('turn-1') && raw.includes('session-1')
      && !raw.includes('message') && !raw.includes('event');
  })());

  global.fetch = async url => url.includes('/active')
    ? reply(200, {turn:null, instance:'new-bridge'})
    : reply(404, {detail:'turn not found'});
  const restarted = await H.reconcile('chat', 'session-1');
  check('a missing turn from a different bridge instance is an honest interruption',
    restarted.interrupted === true);
  check('an acknowledged interruption clears its marker', memory.size === 0);

  H.remember({id:'turn-2', lane:'agent', session:'session-2', instance:'same'});
  global.fetch = async url => url.includes('/active')
    ? reply(200, {turn:null, instance:'same'})
    : reply(404, {detail:'turn pruned'});
  const pruned = await H.reconcile('agent', 'session-2');
  check('same-process pruning is not mislabeled as a bridge restart', pruned.interrupted === false);
  check('a pruned same-process marker is cleared', memory.size === 0);

  H.remember({id:'turn-3', lane:'chat', session:'session-3', instance:'old'});
  global.fetch = async () => { throw new Error('offline'); };
  let threw = false;
  try { await H.reconcile('chat', 'session-3'); } catch (_) { threw = true; }
  check('transport failure remains retryable and is not converted to a restart', threw);
  check('transport failure retains the marker', memory.size === 1);
}

journey().then(() => process.exit(failures ? 1 : 0)).catch(error => {
  console.error(error); process.exit(1);
});
