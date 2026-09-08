/* Real storage controller, disposable DOM and manually delivered HTTP responses. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../panel/assets/storage-controls.js'), 'utf8');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.listeners = {}; this.open = false; this.hidden = true; this.text = ''; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map(c => c.textContent).join(' '); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.text = ''; this.children = nodes; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  showModal() { this.open = true; }
  close() { this.open = false; for (const fn of this.listeners.close || []) fn(); }
  setAttribute() {}
  querySelectorAll() { return []; }
  focus() {}
  scrollIntoView() {}
}
function setup() {
  const ids = Object.fromEntries(['storage-dlg', 'storage-body', 'storage-note', 'chat-menu', 'cs-more'].map(id => [id, new Element('div')]));
  const pending = [], timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    document: {getElementById: id => ids[id], createElement: tag => new Element(tag),
      createTextNode: text => { const e = new Element('text'); e.textContent = text; return e; },
      addEventListener() {}},
    fetch: (url, options) => new Promise(resolve => pending.push({url, options, resolve})),
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id), chatPane: {mode: 'hermes'},
  });
  context.window = context;
  vm.runInContext(source, context);
  function reply(url, data, status = 200) {
    const at = pending.findIndex(p => p.url === url);
    assert(at >= 0, 'expected request ' + url);
    pending.splice(at, 1)[0].resolve({ok: status < 400, status, json: async () => data});
  }
  function button(text) {
    function find(e) { if (e.tag === 'button' && e.textContent === text) return e; for (const c of e.children) { const hit = find(c); if (hit) return hit; } }
    const found = find(ids['storage-body']); assert(found, 'button ' + text); return found;
  }
  return {context, ids, pending, timers, reply, button};
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const inventory = {ok: true, runtimes: [{id: 'opencode', label: 'OpenCode', installed: true}], reset: {factory_reset: false}};
const optional = {ok: true, options: [], job: {running: true, current: 'aider'}};

(async () => {
  // A timer or in-flight inventory must not replace a deliberate removal preview.
  const a = setup();
  const opened = a.context.openStorageManager();
  a.reply('/api/storage/runtimes', inventory); a.reply('/api/storage/optional', optional);
  await opened;
  const preview = a.button('Uninstall…').onclick();
  assert.equal(a.timers.size, 0, 'entering a preview cancels inventory polling');
  a.reply('/api/storage/runtime/plan', {ok: true, label: 'OpenCode', bytes: 7, paths: [], preserve: [], token: 'fixture'});
  await preview;
  assert(a.ids['storage-body'].textContent.includes('Uninstall OpenCode'));

  // Close while a read is pending: no hidden repaint and no future reopen timer.
  const b = setup();
  const reading = b.context.openStorageManager();
  b.context.closeStorageManager();
  const closedText = b.ids['storage-body'].textContent;
  b.reply('/api/storage/runtimes', inventory); b.reply('/api/storage/optional', optional);
  await reading;
  assert.equal(b.ids['storage-body'].textContent, closedText);
  assert.equal(b.timers.size, 0);
  assert.equal(b.ids['storage-dlg'].open, false);

  // Escape/native dialog close uses the same cleanup as the explicit close control.
  const c = setup();
  const opening = c.context.openStorageManager();
  c.reply('/api/storage/runtimes', inventory); c.reply('/api/storage/optional', optional);
  await opening;
  c.ids['storage-dlg'].close();
  assert.equal(c.timers.size, 0);

  // A 409 with receipts is a partial result, and each failed session remains visible.
  const d = setup();
  d.context.planClearLaneChats();
  d.reply('/api/storage/chats/plan', {ok: true, count: 2, token: 'fixture', note: 'Per-session results'});
  await settle();
  const applying = d.button('Delete 2 chats').onclick();
  d.reply('/api/storage/chats/apply', {ok: false, deleted: 1, count: 2, receipts: [
    {id: 'one', ok: true, detail: 'deleted'}, {id: 'two', ok: false, detail: 'upstream unavailable'},
  ]}, 409);
  await applying;
  assert(d.ids['storage-body'].textContent.includes('1 of 2 chats deleted'));
  assert(d.ids['storage-body'].textContent.includes('two: upstream unavailable'));
  console.log('storage dialog: preview, delayed read, Escape and partial-result journeys passed');
})().catch(error => { console.error(error); process.exit(1); });
