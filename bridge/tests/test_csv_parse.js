// ARTIFACT COVERAGE V2 unit test — pure CSV machinery used by renderArtCsv()
// (bridge/panel/index.html): parseCsv / csvDelim / csvColNumeric / csvSortRows.
// Mirrors the panel implementations (established test pattern). Offline, no deps.
// Run: node bridge/tests/test_csv_parse.js

// --- mirror of parseCsv() ---
function parseCsv(text, delim){
  delim = delim || ',';
  const s = String(text == null ? '' : text);
  const rows = []; let row = [], field = '', inQ = false;
  for (let i = 0; i < s.length; i++){
    const ch = s[i];
    if (inQ){
      if (ch === '"'){ if (s[i+1] === '"'){ field += '"'; i++; } else inQ = false; }
      else field += ch;
    } else if (ch === '"' && field === ''){ inQ = true; }
    else if (ch === delim){ row.push(field); field = ''; }
    else if (ch === '\n'){ row.push(field); rows.push(row); row = []; field = ''; }
    else if (ch === '\r'){ if (s[i+1] !== '\n'){ row.push(field); rows.push(row); row = []; field = ''; } }
    else field += ch;
  }
  if (field !== '' || row.length){ row.push(field); rows.push(row); }
  return rows;
}
// --- mirror of csvDelim() ---
function csvDelim(text){
  const first = String(text == null ? '' : text).split(/\r?\n/, 1)[0] || '';
  const tabs = (first.match(/\t/g) || []).length, commas = (first.match(/,/g) || []).length;
  return (tabs > 0 && tabs >= commas) ? '\t' : ',';
}
// --- mirror of csvColNumeric() ---
function csvColNumeric(rows, ci){
  let any = false;
  for (const r of rows){
    const v = (r[ci] == null ? '' : String(r[ci])).trim();
    if (v === '') continue;
    if (!isFinite(Number(v))) return false;
    any = true;
  }
  return any;
}
// --- mirror of csvSortRows() ---
function csvSortRows(rows, ci, dir, numeric){
  const s = rows.slice();
  s.sort(function(a, b){
    const av = (a[ci] == null ? '' : String(a[ci])), bv = (b[ci] == null ? '' : String(b[ci]));
    let c;
    if (numeric){
      const an = av.trim() === '' ? -Infinity : Number(av);
      const bn = bv.trim() === '' ? -Infinity : Number(bv);
      c = an < bn ? -1 : an > bn ? 1 : 0;
    } else c = av.localeCompare(bv);
    return dir === 'desc' ? -c : c;
  });
  return s;
}

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
