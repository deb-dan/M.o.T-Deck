'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {extractFunction} = require('./_panel_source');
const html = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const id = 'a\\b\n\'"&quot;<this>';
const name = 'server\'s "label"\n&copy;';
const document = {createElement: () => ({textContent: '', get innerHTML() { return String(this.textContent).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }})};
const sandbox = {document, capsSnap: {mcp_servers: [{id, name, is_enabled: true}]}, mcpAddForm: () => ''};
vm.createContext(sandbox);
for (const fn of ['esc', 'escAttr', 'apiArg', 'renderMcpServers', 'musicTplRow']) {
  vm.runInContext(extractFunction(html, fn), sandbox);
}
const decode = text => text.replace(/&(?:amp|quot|lt|gt|#39);/g,
  entity => ({'&#39;':"'", '&amp;':'&', '&quot;':'"', '&lt;':'<', '&gt;':'>'})[entity]);
function invoke(markup, method, expected) {
  const raw = [...markup.matchAll(/(?:onclick|onchange)="([^"]*)"/g)]
    .map(m => m[1]).find(body => body.startsWith(method + '('));
  assert.ok(raw, method + ' control exists');
  const control = {checked: true};
  let calls = 0;
  new Function(method, decode(raw)).call(control, (...args) => {
    calls++;
    assert.deepEqual(args, expected.map(arg => arg === 'CONTROL' ? control : arg));
  });
  assert.equal(calls, 1);
}
const mcp = sandbox.renderMcpServers();
invoke(mcp, 'expandMcpTools', [id, 'mcpsub-' + id, 'CONTROL']);
invoke(mcp, 'removeMcpServer', [id, name, 'CONTROL']);
invoke(mcp, 'toggleMcpServer', [id, true, 'CONTROL']);
const template = sandbox.musicTplRow({id, name, prompt: 'test'});
invoke(template, 'musicUseTemplate', [id, false]);
invoke(template, 'musicDelTemplate', [id, 'CONTROL']);
Object.assign(sandbox, {hermesToolsSnap:{running:true,toolsets:[{name:id,enabled:true}]},
  hermesToolsIntent:{},hermesToolsetLocked:()=>'',hermesToolsetSync:()=>'',
  hermesToolsetScopePill:()=>'',hermesToolsetExtra:()=>'',hermesToolsetScopeNote:()=>'',
  hermesToolsetNote:()=>'',renderHermesToolsCheck:()=>''});
vm.runInContext(extractFunction(html,'renderHermesTools'),sandbox);
invoke(sandbox.renderHermesTools(), 'toggleHermesToolset', [id,true,'CONTROL']);
console.log('PASS rendered MCP, music and Hermes controls preserve quoted, multiline and entity-like arguments');
