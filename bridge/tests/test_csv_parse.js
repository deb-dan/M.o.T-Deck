// Execute the shipped helpers; the expectations below are independent fixtures.
const fs = require('node:fs'), path = require('node:path');
const {extractFunction} = require('./_panel_source');
const source = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const names = ['parseCsv', 'csvDelim', 'csvColNumeric', 'csvSortRows'];
const {parseCsv,csvDelim,csvColNumeric,csvSortRows} = new Function(names.map(n => extractFunction(source, n)).join('\n')
  + '; return {' + names.join(',') + '};')();

let pass = 0, fail = 0;
function eq(name, got, want){
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) pass++;
  else { fail++; console.error('FAIL: ' + name + '\n  got:  ' + g + '\n  want: ' + w); }
}

// ---- parse ----
eq('simple', parseCsv('a,b\n1,2'), [['a','b'],['1','2']]);
eq('trailing newline adds no row', parseCsv('a,b\n1,2\n'), [['a','b'],['1','2']]);
eq('quoted embedded comma', parseCsv('"a,x",b\n1,2'), [['a,x','b'],['1','2']]);
eq('escaped quotes ""', parseCsv('"Quote ""Q"" Co",1'), [['Quote "Q" Co','1']]);
eq('embedded newline in quotes', parseCsv('"line1\nline2",b\n1,2'), [['line1\nline2','b'],['1','2']]);
eq('CRLF endings', parseCsv('a,b\r\n1,2\r\n'), [['a','b'],['1','2']]);
eq('lone CR endings', parseCsv('a,b\r1,2'), [['a','b'],['1','2']]);
eq('embedded CRLF in quotes', parseCsv('"x\r\ny",b'), [['x\r\ny','b']]);
eq('empty fields', parseCsv('a,,c\n,,'), [['a','','c'],['','','']]);
eq('quote mid-field is literal', parseCsv('a"b,c'), [['a"b','c']]);
eq('tab delim explicit', parseCsv('a\tb\n1\t2', '\t'), [['a','b'],['1','2']]);

// ---- delimiter detect ----
eq('delim comma', csvDelim('a,b\n1,2'), ',');
eq('delim tab', csvDelim('a\tb\n1\t2'), '\t');
eq('delim tab-dominated', csvDelim('a\tb,c\td\n'), '\t');
eq('delim comma-dominated over tab', csvDelim('a,b,c\td\n'), ',');

eq('UTF-8 BOM before quoted field is not cell data', parseCsv('\uFEFF"name, label",amount\nX,1'), [['name, label','amount'],['X','1']]);
eq('tabs inside a quoted CSV field are not separators', csvDelim('"a\tb\tc",d\n1,2'), ',');
eq('commas inside a quoted TSV field are not separators', csvDelim('"a,b,c"\td\n1\t2'), '\t');
eq('quoted multiline first record uses its actual separators', csvDelim('"a\nb,c"\td\n1\t2'), '\t');

// ---- numeric detection ----
const data = [['Bolt','340'],['Acme','1200'],['Quote','905'],['Delta','77'],['Empty','']];
eq('col 1 numeric', csvColNumeric(data, 1), true);
eq('col 0 not numeric', csvColNumeric(data, 0), false);
eq('all-empty col not numeric', csvColNumeric([['x',''],['y','']], 1), false);

// ---- sort ordering ----
eq('numeric asc (77 < 340 < 905 < 1200, empty first)',
   csvSortRows(data, 1, 'asc', true).map(r => r[0]),
   ['Empty','Delta','Bolt','Quote','Acme']);
eq('numeric desc',
   csvSortRows(data, 1, 'desc', true).map(r => r[0]),
   ['Acme','Quote','Bolt','Delta','Empty']);
eq('string sort would misorder numbers (sanity: numeric-aware matters)',
   csvSortRows([['a','2'],['b','10']], 1, 'asc', false).map(r => r[0]),
   ['b','a']);   // localeCompare: "10" < "2"
eq('string asc', csvSortRows(data, 0, 'asc', false).map(r => r[0]),
   ['Acme','Bolt','Delta','Empty','Quote']);
eq('sort returns a copy (input untouched)', (function(){
  const rows = [['b','2'],['a','1']];
  csvSortRows(rows, 0, 'asc', false);
  return rows[0][0];
})(), 'b');

console.log(`csv-parse: ${pass}/${pass+fail} passed`);
process.exit(fail ? 1 : 0);
