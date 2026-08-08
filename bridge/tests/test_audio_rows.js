/* Panel-side unit test for the AUDIO tab's pure row/label helpers (Phase A).
 *
 * The functions are EXTRACTED from bridge/panel/index.html by name (the pattern
 * test_msg_actions.py established for statsLine) rather than copied, so a rename or
 * an edit in the panel trips this test instead of silently drifting from it.
 *
 * Run: node bridge/tests/test_audio_rows.js   (from repo root)
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

// Brace-matched extraction of `function <name>(...) { ... }` from the panel source.
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

const NAMES = ['esc', 'fmtGB', 'isAppOwned', 'srcLabel', 'srcBadge',
               'audioEngineLabel', 'audioDefaultId', 'audioRowHtml'];
const src = NAMES.map(grab).join('\n');
// The panel's esc() escapes via a detached element's textContent→innerHTML; node has
// no DOM, so stub exactly that one behaviour (& < > escaped, quotes are NOT — which
// is why the panel has a separate escAttr for attribute contexts).
const fn = new Function('document', src + '\nreturn {' + NAMES.join(',') + '};');
const P = fn({
  createElement: () => ({
    set textContent(v) {
      this._h = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
    get innerHTML() { return this._h; },
  }),
});

// ── engine label: the row must say llama.cpp / mlx, not the raw registry format ──
check('mlx entry → engine label "mlx"', P.audioEngineLabel({ engine: 'mlx' }) === 'mlx');
check('llamacpp entry → engine label "llama.cpp"',
      P.audioEngineLabel({ engine: 'llamacpp' }) === 'llama.cpp');
check('an unknown engine falls back to llama.cpp (the default engine)',
      P.audioEngineLabel({}) === 'llama.cpp');

// ── which default applies is ROLE-scoped: a TTS row must never read the STT default ──
const R = { voice: { tts_model: 'kokoro', stt_model: 'whisper-base-mlx' } };
check('tts role reads voice.tts_model', P.audioDefaultId(R, 'tts') === 'kokoro');
check('stt role reads voice.stt_model', P.audioDefaultId(R, 'stt') === 'whisper-base-mlx');
check('a missing voice block is not an error', P.audioDefaultId({}, 'tts') === '');
check('an unset default reads as empty (= capability off)',
      P.audioDefaultId({ voice: { tts_model: '' } }, 'tts') === '');

// ── row markup ──
const row = P.audioRowHtml({ id: 'Kokoro-82M-bf16', role: 'tts', engine: 'mlx',
                             source: 'download', size_bytes: 408_000_000 }, true);
check('row shows the FULL model id (never truncated)', row.includes('Kokoro-82M-bf16'));
check('row carries the role pill', row.includes('>tts<'));
check('the default row gets the gold pill', row.includes('mpill live">default<'));
check('row carries the engine pill', row.includes('>mlx<'));
check('row carries the size', row.includes('0.4 GB'));
check('row carries the provenance badge', row.includes('downloaded'));

const row2 = P.audioRowHtml({ id: 'whisper-base-mlx', role: 'stt', engine: 'mlx',
                              source: 'audio-hf-cache' }, false);
check('a non-default row has NO default pill', !row2.includes('>default<'));
check('stt rows say stt', row2.includes('>stt<'));
check('an HF-cache model is badged as a read-only import',
      row2.includes('mpill imported') && row2.includes('HF cache'));
check('a size-less entry simply omits the size', !row2.includes('GB'));

// The id is user-visible text that came off the network (an HF repo leaf) — escaped.
const row3 = P.audioRowHtml({ id: '<img src=x onerror=1>', role: 'tts', engine: 'mlx' }, false);
check('the model id is HTML-escaped in the row',
      !row3.includes('<img') && row3.includes('&lt;img'));

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
