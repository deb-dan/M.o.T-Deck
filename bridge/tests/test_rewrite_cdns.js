// Exercise both the real rewrite and the actual injected navigation handler.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const {extractFunction} = require('./_panel_source');
const source = fs.readFileSync(path.join(__dirname, '../panel/index.html'), 'utf8');
const rewriteVendorCdns = new Function(extractFunction(source, 'rewriteVendorCdns') + ';return rewriteVendorCdns;')();
const start = source.indexOf('const ART_NAV_GUARD ='), end = source.indexOf("+ '})();</scr' + 'ipt>';", start);
const guard = new Function(source.slice(start, end + "+ '})();</scr' + 'ipt>';".length) + ';return ART_NAV_GUARD;')();
let click;
vm.runInNewContext(guard.slice(8, -9), {document:{addEventListener:(_event, fn)=>{click=fn;}}});
function navBlocked(href){
  let blocked=false;
  click({target:{closest:()=>({getAttribute:()=>href})},preventDefault(){blocked=true;},stopPropagation(){}});
  return blocked;
}

const A = 'http://127.0.0.1:8700/assets/vendor';
const LOCAL = A + '/tailwind.play.js';
let pass = 0, fail = 0;
function eq(name, got, want){
  if (got === want) { pass++; }
  else { fail++; console.error('FAIL: ' + name + '\n  got:  ' + got + '\n  want: ' + want); }
}

// ---- rewrite: Tailwind Play tag variants ----
eq('bare cdn.tailwindcss.com dq',
   rewriteVendorCdns('<script src="https://cdn.tailwindcss.com"></script>', A),
   '<script src="' + LOCAL + '"></script>');
eq('bare cdn.tailwindcss.com sq',
   rewriteVendorCdns("<script src='https://cdn.tailwindcss.com'></script>", A),
   "<script src='" + LOCAL + "'></script>");
eq('versioned play url',
   rewriteVendorCdns('<script src="https://cdn.tailwindcss.com/3.4.16"></script>', A),
   '<script src="' + LOCAL + '"></script>');
eq('with query plugins',
   rewriteVendorCdns('<script src="https://cdn.tailwindcss.com?plugins=forms,typography"></script>', A),
   '<script src="' + LOCAL + '"></script>');
eq('other attrs preserved',
   rewriteVendorCdns('<script defer src="https://cdn.tailwindcss.com" data-x="1"></script>', A),
   '<script defer src="' + LOCAL + '" data-x="1"></script>');
eq('www.tailwindcss.com variant',
   rewriteVendorCdns('<script src="https://www.tailwindcss.com/x.js"></script>', A),
   '<script src="' + LOCAL + '"></script>');
eq('case-insensitive match, original case preserved',
   rewriteVendorCdns('<SCRIPT SRC="https://cdn.tailwindcss.com"></SCRIPT>', A),
   '<SCRIPT SRC="' + LOCAL + '"></SCRIPT>');
eq('two tailwind tags both rewritten',
   rewriteVendorCdns('<script src="https://cdn.tailwindcss.com"></script>\n<script src="https://cdn.tailwindcss.com/3.4.16"></script>', A),
   '<script src="' + LOCAL + '"></script>\n<script src="' + LOCAL + '"></script>');

// ---- rewrite: must NOT touch other CDNs / content ----
eq('unrelated cdn untouched',
   rewriteVendorCdns('<script src="https://cdn.jsdelivr.net/npm/foo.js"></script>', A),
   '<script src="https://cdn.jsdelivr.net/npm/foo.js"></script>');
eq('no script tag → unchanged',
   rewriteVendorCdns('<h1 class="text-xl">hi</h1>', A),
   '<h1 class="text-xl">hi</h1>');
eq('empty → empty', rewriteVendorCdns('', A), '');
eq('null → empty', rewriteVendorCdns(null, A), '');
eq('rewrite marks change (used by usesTailwind)',
   String(rewriteVendorCdns('<script src="https://cdn.tailwindcss.com"></script>', A)
          !== '<script src="https://cdn.tailwindcss.com"></script>'),
   'true');

// ---- nav guard: href resolution intent ----
eq('href="#" is in-page (not blocked)', String(navBlocked('#')), 'false');
eq('href="#section" in-page (not blocked)', String(navBlocked('#section')), 'false');
eq('href="/" blocked', String(navBlocked('/')), 'true');
eq('href="http://127.0.0.1:8700/" blocked', String(navBlocked('http://127.0.0.1:8700/')), 'true');
eq('relative path blocked', String(navBlocked('page.html')), 'true');
eq('empty href blocked (href="" would reload)', String(navBlocked('')), 'true');

console.log((fail ? ('FAILED ' + fail + ' / ') : 'OK ') + (pass + fail) + ' assertions (' + pass + ' passed)');
process.exit(fail ? 1 : 0);
