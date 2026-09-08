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
  vm.runInContext(handler(name), context);
  const input = {disabled: false};
  const pending = context[name]({}, input);
  if (!typing) context.mSel = {kind: 'installed', id: 'B'};
  resolve({json: async () => failed ? {ok: false, error: 'A was refused'} : {
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

(async () => {
  for (const name of ['samplingPost', 'loadPost']) {
    await exercise(name, false);
    await exercise(name, true);
    await exercise(name, false, true);
  }
  console.log('settings races: stale success, stale failure and typed input preserved in both groups');
})().catch(error => { console.error(error); process.exit(1); });
