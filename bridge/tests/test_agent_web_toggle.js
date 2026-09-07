/* A5 — Agent web-search permission is a real per-request choice, not hardcoded. */
'use strict';
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync('bridge/panel/index.html', 'utf8');
let failures = 0;
function check(name, ok){ if (!ok){ failures++; console.error('FAIL', name); }
  else console.log('PASS', name); }
function fn(name){
  const at = src.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('missing ' + name);
  const open = src.indexOf('{', at); let depth = 0, quote = '', escape = false;
  for (let i = open; i < src.length; i++){
    const c = src[i];
    if (quote){ if (escape) escape = false; else if (c === '\\') escape = true;
      else if (c === quote) quote = ''; continue; }
    if (c === "'" || c === '"' || c === '`'){ quote = c; continue; }
    if (c === '{') depth++; else if (c === '}' && --depth === 0) return src.slice(at, i + 1);
  }
  throw new Error('unterminated ' + name);
}
const box = {}; vm.createContext(box);
vm.runInContext(fn('agentWebForTurn'), box);
check('Agent defaults to web when the global capability is available',
  box.agentWebForTurn('agent', true, {features:{web_search:true}}) === true);
check('the per-turn off choice wins',
  box.agentWebForTurn('agent', false, {features:{web_search:true}}) === false);
check('a globally disabled capability cannot be re-enabled by the local chip',
  box.agentWebForTurn('agent', true, {features:{web_search:false}}) === false);
check('unknown capability state preserves the historical on default',
  box.agentWebForTurn('agent', true, null) === true);
check('Direct Chat and Hermes can never receive Agent search permission',
  box.agentWebForTurn('chat', true, null) === false
  && box.agentWebForTurn('hermes', true, null) === false);
check('the request sends the computed choice rather than hardcoded true',
  src.includes('allow_web_search:agentWebForTurn(chatPane.mode, chatPane.agentWeb, capsSnap)')
  && !src.includes('allow_web_search:true'));
check('Web and Browse remain visibly separate controls',
  src.includes('id="mode-agent-web"') && src.includes('id="mode-browse"'));
check('the user choice survives panel reloads',
  src.includes("localStorage.setItem('motdeck-agent-web'")
  && src.includes("localStorage.getItem('motdeck-agent-web')"));
process.exitCode = failures ? 1 : 0;
