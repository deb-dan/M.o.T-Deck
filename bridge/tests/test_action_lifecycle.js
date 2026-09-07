/* U42: the Compose/Generate submission lifecycle, executed rather than grepped. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const ROOT = path.resolve(__dirname, '..', '..');
const compose = fs.readFileSync(path.join(ROOT, 'bridge/panel/compose.html'), 'utf8');
const comfy = fs.readFileSync(path.join(ROOT, 'bridge/panel/comfy.html'), 'utf8');
let checks = 0;
function ok(v, msg) { checks++; if (!v) throw new Error('FAIL: ' + msg); }
function block(s) {
  const a = s.indexOf('/* MOT_ACTION_LIFECYCLE_V1_START');
  const b = s.indexOf('/* MOT_ACTION_LIFECYCLE_V1_END */', a);
  ok(a >= 0 && b > a, 'the shared lifecycle block exists');
  return s.slice(a, b + '/* MOT_ACTION_LIFECYCLE_V1_END */'.length);
}

const c1 = block(compose), c2 = block(comfy);
ok(c1 === c2, 'Compose and Generate carry a byte-identical lifecycle implementation');
ok(!/<script[^>]+\bsrc=/i.test(compose) && !/<script[^>]+\bsrc=/i.test(comfy),
  'the shared contract does not weaken either page’s single-file boot guarantee');
ok(/25000/.test(compose) && /90000/.test(comfy),
  'deadlines are named at each backend boundary rather than pretending their costs match');
ok(/submitUnknown/.test(compose) && /submitUnknown/.test(comfy),
  'an unknown outcome blocks a duplicate submission until status reconciles');
ok(/may have [^\n]+\n\s*\+ 'reached Music/.test(compose)
  && /may have reached '\s*\n\s*\+ 'ComfyUI/.test(comfy),
  'timeout copy never claims the upstream job failed or was cancelled');

const context = { AbortController, Promise, setTimeout, clearTimeout };
vm.createContext(context);
vm.runInContext(c1.replace('const MOTActionLifecycle', 'this.MOTActionLifecycle'), context);
(async () => {
  let out = await context.MOTActionLifecycle.run(async () => 42, 50);
  ok(out.kind === 'settled' && out.value === 42, 'a settled request passes through');
  out = await context.MOTActionLifecycle.run(async () => { throw new Error('wire broke'); }, 50);
  ok(out.kind === 'failed' && out.error === 'wire broke', 'a real rejection remains a failure');
  let aborted = false;
  out = await context.MOTActionLifecycle.run((signal) => {
    signal.addEventListener('abort', () => { aborted = true; });
    return new Promise(() => {});
  }, 5);
  await new Promise(resolve => setTimeout(resolve, 0));
  ok(out.kind === 'unknown' && aborted, 'a stalled request releases the UI and aborts only its browser wait');
  console.log(`action lifecycle: ${checks} checks passed`);
})().catch(e => { console.error(e.stack || e); process.exitCode = 1; });
