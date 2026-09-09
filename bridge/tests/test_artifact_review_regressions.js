'use strict';
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const path = require('node:path');
const {extractFunction} = require('./_panel_source');
const source = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const context = vm.createContext({});
vm.runInContext(extractFunction(source, 'injectIntoDoc'), context);
const extra = '<meta name="protected" content="yes">';
for (const input of [
  '<!doctype html><!-- example <head> --><html><head><title>T</title></head><body>B</body></html>',
  '<html data-tip="<head>"><head data-tip=">">x</head><body>B</body></html>',
  '<html><script>const sample="<head>";</script><body>B</body></html>',
  '<!doctype html><!-- unclosed <head>',
  '<header>Not a head</header>',
]) {
  const output = context.injectIntoDoc(input, extra);
  assert(output.includes(extra));
  const uncommented = output.replace(/<!--[\s\S]*?-->/g, '');
  assert(uncommented.includes(extra), 'protection was swallowed by a comment');
  assert(output.indexOf(extra) < output.indexOf('<script>') || !output.includes('<script>'));
}
assert.match(context.injectIntoDoc('<html lang="et"><head><title>T</title></head></html>',extra), /<html lang="et"><head><meta name="protected"/);

function element(tag) {
  return {tag, kids:[], listeners:{}, open:false, textContent:'',
    appendChild(child){this.kids.push(child);return child;},
    addEventListener(event, fn){this.listeners[event]=fn;},
    querySelectorAll(){return [];},
    set innerHTML(value){this.kids=[];}};
}
context.document={createElement:element};context.JSON_OPEN_DEPTH=2;context.CSV_ROW_CAP=2000;
for (const name of ['parseCsv','csvDelim','csvColNumeric','csvSortRows','renderArtCsv','jsonCount','buildJsonTree'])
  vm.runInContext(extractFunction(source,name),context);
const host=element('div'); context.renderArtCsv(host,'name\nA,hidden,also visible');
const table=host.kids[0].kids[0];
assert.equal(table.kids[0].kids[0].kids.length,3);
assert.deepEqual(table.kids[1].kids[0].kids.map(n=>n.textContent),['A','hidden','also visible']);
// Depth must be bounded by expanded nodes, including a deeply nested input.
let data={leaf:'kept'};for(let i=0;i<10000;i++) data={next:data};
const tree=context.buildJsonTree(null,data,0);
const second=tree.kids[1].kids[0], third=second.kids[1].kids[0];
assert.equal(third.open,false);assert.equal(third.kids[1].kids.length,0);
third.open=true;third.listeners.toggle();assert.equal(third.kids[1].kids.length,1);
third.listeners.toggle();assert.equal(third.kids[1].kids.length,1);
console.log('artifact document prologue, complete CSV rows and lazy JSON expansion passed');
