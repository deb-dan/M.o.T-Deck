/* Stop receipts and delayed fallbacks must belong to the turn that requested them. */
'use strict';
const assert = require('assert');
const fs = require('fs'), path = require('path'), vm = require('vm');
const panel = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const stream = fs.readFileSync(path.join(__dirname, '../panel/assets/turn-stream.js'), 'utf8');
const timers = [], ended = [];
const context = {
  window:{}, chatPane:{}, console, Date, Math, JSON, AbortController,
  setTimeout(fn){ timers.push(fn); return timers.length; }, clearTimeout(){},
  forceEndTurn(reason){ ended.push([context.chatPane.curTurn, reason]); },
  chatStatus(){}, TURN_FORCE_MS:3000,
};
vm.createContext(context);
vm.runInContext(stream, context);
context.MOTDeckTurnStream = context.window.MOTDeckTurnStream;
const start = panel.indexOf('async function hermesStop(');
const end = panel.indexOf('\nasync function sendChat()', start);
vm.runInContext(panel.slice(start, end), context);

async function main(){
  const old = {id:'old', lane:'chat'}, replacement = {id:'new', lane:'chat'};
  context.chatPane.curTurn = old; context.chatPane.busy = true;
  let settle;
  context.fetch = () => new Promise(resolve => { settle = resolve; });
  const pending = context.stopTurnNow('panel stop');
  context.chatPane.curTurn = replacement;
  settle({ok:true, json:async () => ({state:'stopped'})});
  // Drain only the old implementation's trailing UI-delay timer.
  for (let i=0; i<8; i++) await Promise.resolve();
  timers.splice(0).forEach(fn => fn());
  await pending;
  assert(!ended.some(([turn]) => turn === replacement), 'late Stop receipt ended the replacement turn');

  ended.length = 0;
  context.chatPane = {curTurn:{id:'h-old',lane:'hermes'}, busy:true, hermesSid:'old-session'};
  context.fetch = async () => ({ok:true});
  await context.hermesStop('panel stop');
  context.chatPane.curTurn = replacement;
  timers.splice(0).forEach(fn => fn());
  assert(!ended.length, 'old Hermes fallback ended the replacement turn');

  const retry = {id:'retry', lane:'chat'};
  let calls = 0;
  context.fetch = async () => { calls++; if (calls === 1) throw new Error('offline');
    return {ok:true,json:async () => ({state:'stopped'})}; };
  await assert.rejects(context.MOTDeckTurnStream.stop(retry), /offline/);
  await context.MOTDeckTurnStream.stop(retry);
  assert.strictEqual(calls, 2, 'failed Stop permanently disabled retries');
  console.log('OK — delayed Stop work cannot affect a newer turn, and failed requests can retry');
}
main().catch(error => { console.error(error); process.exit(1); });
