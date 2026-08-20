/* Panel-side unit test for the Model-settings v2.1 pure helpers.
 *
 * All three are EXTRACTED from bridge/panel/index.html by name (the established
 * pattern) rather than copied, so an edit in the panel trips this test instead of
 * silently drifting from it.
 *
 *   laneModelLabel(live, running, echo)  THE BUG FIX — which model a reply is
 *       attributed to. Debi switched MLX → gguf and the Hermes/Agent bylines kept
 *       naming the old model as a raw absolute path. The live runner is the truth;
 *       the lane's own echo is a fallback only, and is basename-shortened so a wire
 *       path can never be printed in full again.
 *   fieldTip(f, defaultWord)             the per-row tooltip (help + range + reset)
 *   sliderPos(raw, min, max)             slider ⇄ box sync arithmetic
 *
 * Run: node bridge/tests/test_model_settings_ui.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');

let fails = [];
function check(name, cond) {
  console.log((cond ? 'PASS' : 'FAIL') + ' ' + name);
  if (!cond) fails.push(name);
}

function grab(name) {
  const at = html.indexOf('function ' + name + '(');
  if (at < 0) throw new Error('function ' + name + ' not found in the panel');
  let i = html.indexOf('{', at), depth = 0, inStr = null, prev = '';
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (inStr) {
      if (c === inStr && prev !== '\\') inStr = null;
    } else if (c === '"' || c === "'" || c === '`') {
      inStr = c;
    } else if (c === '{') {
      depth++;
    } else if (c === '}') {
      depth--;
      if (depth === 0) return html.slice(at, j + 1);
    }
    prev = c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

const NAMES = ['laneModelLabel', 'fieldTip', 'sliderPos'];
const P = new Function(NAMES.map(grab).join('\n') + '\nreturn {' + NAMES.join(',') + '};')();
const L = P.laneModelLabel;

// ── 1. laneModelLabel — the reported bug, in both lanes ─────────────────────────
const MLXPATH = '/Users/debik/.lmstudio/models/radixark/Muse-Glimmer-q4km-gs128-MLX';

check('the LIVE model wins over a stale lane echo (THE BUG)',
      L('Qwen3.8-27B-Heretic-Q4_K_M', true, MLXPATH) === 'Qwen3.8-27B-Heretic-Q4_K_M');
check('a stale echo cannot survive a switch in the Hermes lane either (same fn)',
      L('Qwen3.8-27B-Heretic-Q4_K_M', true, 'Muse-Glimmer') === 'Qwen3.8-27B-Heretic-Q4_K_M');
check('with nothing loaded the echo is used, but SHORTENED to a basename',
      L('', false, MLXPATH) === 'Muse-Glimmer-q4km-gs128-MLX');
check('a trailing slash on a wire path does not yield an empty label',
      L(null, false, MLXPATH + '/') === 'Muse-Glimmer-q4km-gs128-MLX');
check('a plain registry id is passed through untouched as the fallback',
      L('', false, 'Qwen3.8-27B-Heretic-Q4_K_M') === 'Qwen3.8-27B-Heretic-Q4_K_M');
check('a live pin is NOT trusted while the runner is stopped (it falls back to intent)',
      L('Qwen3.8-27B-Heretic-Q4_K_M', false, 'Muse-Glimmer') === 'Muse-Glimmer');
check('nothing live and nothing echoed = empty (caller supplies "Assistant")',
      L('', false, '') === '');
check('running with an empty pin still falls back rather than showing blank',
      L('', true, 'Muse-Glimmer') === 'Muse-Glimmer');

// totality: junk of every shape is safe, never throws, never prints "null"
check('null/undefined everywhere', L(null, true, undefined) === '');
check('undefined running is falsy, not a crash', L('X', undefined, 'Y') === 'Y');
check('a numeric echo is stringified', L('', false, 4096) === '4096');
check('whitespace-only live is not a label', L('   ', true, 'Y') === 'Y');
check('whitespace-only echo is not a label', L('', false, '   ') === '');
check('an object echo cannot become "[object Object]/x"',
      typeof L('', false, {}) === 'string');
check('a bare "/" echo yields no label at all rather than a lone slash',
      L('', false, '/') === '');

// ── 2. fieldTip — every row explains itself, from the BRIDGE's string ───────────
const F = { key: 'ctx', help: 'How much conversation the model can see at once.',
            min: 1024, max: 262144, default: 'registry / 65536' };
const t = P.fieldTip(F, 'engine');
check('the tooltip leads with the bridge help', t.indexOf(F.help) === 0);
check('...then states the range', t.indexOf('Range 1024 to 262144.') > 0);
check('...then the reset convention with the right default word',
      t.indexOf('Leave empty for the engine default (registry / 65536).') > 0);
check('the sampling side says "harness default" instead',
      P.fieldTip({ help: 'h', min: 0, max: 2, default: 0.7 }, 'harness')
        .indexOf('harness default (0.7)') > 0);
check('a field with no range still gets help + reset',
      P.fieldTip({ help: 'h', default: 'auto' }, 'engine') === 'h Leave empty for the engine default (auto).');
check('a field with no default at all does not print "(undefined)"',
      P.fieldTip({ help: 'h' }, 'engine').indexOf('undefined') < 0);
check('a missing help never yields "undefined" text',
      P.fieldTip({ min: 1, max: 2, default: 3 }, 'engine').indexOf('undefined') < 0);
check('junk input is total', typeof P.fieldTip(null, 'engine') === 'string');
check('a missing defaultWord falls back to "engine"',
      P.fieldTip({ help: 'h' }).indexOf('engine default') > 0);
check('a zero minimum is not treated as absent (0 is a real bound)',
      P.fieldTip({ help: 'h', min: 0, max: 500 }, 'engine').indexOf('Range 0 to 500.') > 0);

// ── 3. sliderPos — the knob can never go NaN while the box is being typed in ───
check('an in-range value is itself', P.sliderPos(32768, 1024, 262144) === 32768);
check('a typed string coerces', P.sliderPos('32768', 1024, 262144) === 32768);
check('an empty box parks the knob at the minimum, not at NaN',
      P.sliderPos('', 1024, 262144) === 1024);
check('a half-typed value ("3") is still a number and is clamped up',
      P.sliderPos('3', 1024, 262144) === 1024);
check('junk parks at the minimum', P.sliderPos('abc', 1024, 262144) === 1024);
check('above the ceiling clamps down', P.sliderPos(999999999, 1024, 262144) === 262144);
check('below the floor clamps up', P.sliderPos(-5, 1024, 262144) === 1024);
check('gpu_layers -1 is a legal position, not clamped away',
      P.sliderPos(-1, -1, 999) === -1);
check('null is empty, not 0', P.sliderPos(null, 1, 32) === 1);
check('undefined is empty too', P.sliderPos(undefined, 1, 32) === 1);
check('a junk range never returns NaN', P.sliderPos(5, 'a', 'b') === 0);
check('NaN input parks at the minimum', P.sliderPos(NaN, 1, 32) === 1);

// ── 4. wiring: the label helper is what the byline actually uses ────────────────
check('addMsg attributes replies through the live-model helper',
      /const who = role === 'user' \? 'You' : \(liveModelLabel\(chatModel\)/.test(html));
check('the model_info/model_actual frame no longer writes the echo straight in',
      html.indexOf("holder.querySelector('.who').textContent = chatModel;") < 0);
check('...and routes through the same helper instead',
      html.indexOf("liveModelLabel(chatModel) || 'Assistant'") > 0);
check('liveModelLabel reads the live runner off the status poll',
      /function liveModelLabel[\s\S]{0,240}components\.runner/.test(html));
check('...and passes BOTH the pin and its running gate (a stopped pin lies)',
      /laneModelLabel\(r && r\.pin, !!\(r && r\.running\), echo\)/.test(html));
check('the session-model fallback is no longer mangled by a dash split',
      html.indexOf(".split('-').slice(0,2).join('-') || 'model'") < 0);

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
