/* Execute the shipped handlers with delayed responses and a changing selection. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');

function handler(name) {
  const start = html.indexOf('async function ' + name + '(');
  const end = html.indexOf('\n}', start) + 2;
  assert(start > 0 && end > start);
  return html.slice(start, end);
}

function loadHandlers(context) {
  const start = html.indexOf('const modelSettingsWrites =');
  if (start >= 0) vm.runInContext(html.slice(start, html.indexOf('async function samplingPost(', start)), context);
  for (const name of ['samplingPost', 'loadPost']) vm.runInContext(handler(name), context);
}

async function exercise(name, failed, typing = false) {
  let resolve;
  const hosts = Object.fromEntries(['md-sampling', 'md-load', 'md-launch'].map(
    id => [id, {innerHTML: 'B controls'}]));
  const errors = [];
  const context = vm.createContext({
    mSel: {kind: 'installed', id: 'A'},
    lastModels: {installed: [{id: 'A'}, {id: 'B'}]},
    fetch: () => new Promise(r => { resolve = r; }),
    document: {getElementById: id => hosts[id]},
    samplingErr: value => errors.push(value), loadErr: value => errors.push(value),
    renderSampling: m => m.id + ' controls', renderLoad: m => m.id + ' controls',
    renderLaunch: m => m.id + ' launch', samplingTyping: () => typing,
    feed: () => {}, esc: x => x,
  });
  loadHandlers(context);
  const input = {disabled: false};
  const pending = context[name]({}, input);
  await Promise.resolve(); await Promise.resolve();
  if (!typing) context.mSel = {kind: 'installed', id: 'B'};
  resolve({ok:true,json: async () => failed ? {ok: false, error: 'A was refused'} : {
    ok: true, id: 'A', settings: {temperature: 0.3}, sampling: {changed: 1},
    load: {ctx: 2048}, loadview: {changed: 1}, launch: {changed: 1},
  }});
  await pending;
  for (const host of Object.values(hosts)) assert.equal(host.innerHTML, 'B controls');
  assert.equal(errors.filter(Boolean).length, 0, 'a stale failure must not blame model B');
  assert.equal(input.disabled, false, 'the originating control is always released');
  if (!failed) {
    const a = context.lastModels.installed[0];
    assert(a[name === 'samplingPost' ? 'sampling' : 'loadview']);
    assert.equal(context.lastModels.installed[1].settings, undefined);
  }
}

async function orderedEdits(firstFails, name = 'samplingPost') {
  const requests = [];
  const context = vm.createContext({
    mSel: {kind: 'installed', id: 'A'}, lastModels: {installed: [{id:'A'}]},
    fetch: (url, init) => new Promise((resolve, reject) => requests.push({
      body: JSON.parse(init.body), resolve, reject,
    })),
    document: {getElementById: () => null}, samplingErr: () => {}, loadErr: () => {},
    samplingTyping: () => false, feed: () => {}, esc: x => x,
  });
  loadHandlers(context);
  const edit = context[name]({settings:{temperature:0.2},load:{ctx:2048}}, {});
  const reset = context[name]({reset:true}, {});
  await Promise.resolve(); await Promise.resolve();
  assert.equal(requests.length, 1, 'Reset must not overtake the earlier save at the server');
  if (firstFails) requests[0].reject(new Error('connection lost'));
  else requests[0].resolve({ok:true,json:async () => ({ok:true,id:'A',settings:{temperature:0.2},sampling:{changed:1},load:{ctx:2048},loadview:{changed:1}})});
  await edit;
  await Promise.resolve(); await Promise.resolve();
  assert.equal(requests.length, 2, 'the queue must progress even after a failed save');
  assert.equal(requests[1].body.reset, true);
  requests[1].resolve({ok:true,json:async () => ({ok:true,id:'A',settings:{},sampling:{changed:0},load:{},loadview:{changed:0}})});
  await reset;
  assert.equal(context.lastModels.installed[0][name === 'samplingPost' ? 'settings' : 'load'], null, 'the final reset remains authoritative');
}

(async () => {
  for (const name of ['samplingPost', 'loadPost']) {
    await exercise(name, false);
    await exercise(name, true);
    await exercise(name, false, true);
    await orderedEdits(false, name);
    await orderedEdits(true, name);
  }
  console.log('settings races: selection, typing, save/reset ordering and failed-save recovery passed');
})().catch(error => { console.error(error); process.exit(1); });
