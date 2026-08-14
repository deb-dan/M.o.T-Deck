/* Panel-side unit test for the PHASE C voice helpers (composer AUDIO control).
 *
 * Both functions are EXTRACTED from bridge/panel/index.html by name (the pattern
 * test_msg_actions.py established for statsLine, reused by test_audio_rows.js) rather
 * than copied, so a rename or an edit in the panel trips this test instead of silently
 * drifting from it.
 *
 *   speakText(raw)         what actually reaches the TTS engine
 *   voiceTtsRows(entries)  the popover's row list: TTS only, llama.cpp first
 *
 * Run: node bridge/tests/test_speak_text.js   (from repo root)
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

const NAMES = ['speakText', 'voiceTtsRows'];
const P = new Function(NAMES.map(grab).join('\n') + '\nreturn {' + NAMES.join(',') + '};')();

// ── speakText: fenced code is dropped WHOLE (content included) ──────────────────
check('a complete fence is removed with its content',
      P.speakText('Here you go:\n```js\nconst x = 1;\n```\nThat is it.')
        === 'Here you go: That is it.');
check('two fences are both removed',
      P.speakText('one ```a\nX\n``` two ```b\nY\n``` three') === 'one two three');
check('a code-ONLY message speaks nothing',
      P.speakText('```py\nprint("hi")\n```') === '');
check('an unterminated fence (truncated/live turn) drops the rest',
      P.speakText('intro text\n```sh\nrm -rf /') === 'intro text');
check('a fence with no language is still removed',
      P.speakText('a\n```\nraw\n```\nb') === 'a b');

// ── inline code keeps its words, loses the backticks (they would be read aloud) ──
check('inline code delimiters are stripped, the word survives',
      P.speakText('run the `install` script') === 'run the install script');

// ── markdown emphasis: the engine read "asterisk asterisk Temperature…" aloud ────
check('**bold** loses its markers, keeps the word',
      P.speakText('the **Temperature** is high') === 'the Temperature is high');
check('*emphasis* and ***both*** are stripped too',
      P.speakText('*one* and ***two***') === 'one and two');
check('__bold__ and _em_ are stripped',
      P.speakText('__a__ then _b_') === 'a then b');
check('a heading loses its hashes',
      P.speakText('## Current conditions:\nsunny') === 'Current conditions: sunny');
check('list bullets are not read',
      P.speakText('- **Wind**: 11 mph\n- **Rain**: none') === 'Wind: 11 mph Rain: none');
check('a lone asterisk in prose survives',
      P.speakText('5 * 3 equals 15') === '5 * 3 equals 15');

// ── emoji: the engine tries to pronounce pictographs (Debi 2026-08-14) ──────────
check('emoji are stripped, words survive',
      P.speakText('Sure thing! \u{1F60A} Let me know.') === 'Sure thing! Let me know.');
check('multiple emoji + variation selectors are stripped',
      P.speakText('ok \u2705\uFE0F done \u{1F389}') === 'ok done');
check('accented letters are NOT stripped',
      P.speakText('caf\u00e9 na\u00efve') === 'caf\u00e9 na\u00efve');

// ── whitespace / trimming ───────────────────────────────────────────────────────
check('newlines and runs of spaces collapse to one space',
      P.speakText('a\n\n\nb    c\td') === 'a b c d');
check('leading/trailing whitespace is trimmed', P.speakText('   hello   ') === 'hello');
check('whitespace-only input speaks nothing', P.speakText('   \n\t  ') === '');

// ── defensive input (never throws — a stuck "…" chip is the failure we avoid) ────
check('null → empty', P.speakText(null) === '');
check('undefined → empty', P.speakText(undefined) === '');
check('a non-string is coerced', P.speakText(42) === '42');
check('plain prose passes through unchanged',
      P.speakText('The capital of France is Paris.') === 'The capital of France is Paris.');

// ── voiceTtsRows: llama.cpp (tts-gguf) FIRST, then MLX; STT never appears ───────
const AVAIL = [
  { id: 'whisper-base-mlx',   format: 'stt-mlx',  engine: 'mlx' },
  { id: 'Kokoro-82M-bf16',    format: 'tts-mlx',  engine: 'mlx' },
  { id: 'Qwen3-TTS-Q4_K_M',   format: 'tts-gguf', engine: 'llamacpp' },
  { id: 'whisper-large-v3',   format: 'stt-mlx',  engine: 'mlx' },
  { id: 'Another-TTS-Q8',     format: 'tts-gguf', engine: 'llamacpp' },
  { id: 'Qwen3-TTS-8bit',     format: 'tts-mlx',  engine: 'mlx' },
];
const ids = P.voiceTtsRows(AVAIL).map(a => a.id);
check('every gguf row comes before every mlx row (Debi: llama.cpp on top)',
      JSON.stringify(ids) === JSON.stringify(
        ['Another-TTS-Q8', 'Qwen3-TTS-Q4_K_M', 'Kokoro-82M-bf16', 'Qwen3-TTS-8bit']));
check('STT models never leak into the voice popover',
      !ids.includes('whisper-base-mlx') && !ids.includes('whisper-large-v3'));
check('ordering is deterministic (same input → same order)',
      JSON.stringify(P.voiceTtsRows(AVAIL).map(a => a.id)) === JSON.stringify(ids));
check('the input array is not mutated',
      AVAIL[0].id === 'whisper-base-mlx' && AVAIL.length === 6);
check('an empty registry yields no rows', P.voiceTtsRows([]).length === 0);
check('a missing registry is not an error', P.voiceTtsRows(undefined).length === 0);
check('null entries are skipped', P.voiceTtsRows([null, undefined]).length === 0);
check('an unknown format is not treated as TTS',
      P.voiceTtsRows([{ id: 'chat-model', format: 'gguf' }]).length === 0);
check('a chat entry with no format at all is excluded',
      P.voiceTtsRows([{ id: 'Qwen3.5-9B-Q4_0' }]).length === 0);
check('a lone mlx tts model still renders',
      P.voiceTtsRows([{ id: 'k', format: 'tts-mlx' }]).length === 1);

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
