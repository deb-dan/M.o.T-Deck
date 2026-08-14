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

// Constants are read OUT of the panel too, so a value changed there cannot pass
// silently against a stale expectation in here.
function grabConst(name) {
  const m = new RegExp('^const ' + name + ' =[\\s\\S]*?;$', 'm').exec(html);
  if (!m) throw new Error('const ' + name + ' not found in the panel');
  return m[0];
}

const NAMES = ['esc', 'fmtGB', 'isAppOwned', 'srcLabel', 'srcBadge',
               'audioEngineLabel', 'audioDefaultId', 'audioRowHtml',
               'voiceChoiceMode', 'audioVoiceBadge', 'isHideable',
               'omnivoiceBf16Hint'];
const src = [grabConst('OMNIVOICE_FP32_MIN_BYTES'), grabConst('OMNIVOICE_BF16_HINT')]
  .concat(NAMES.map(grab)).join('\n');
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

/* ---- voiceChoiceMode: which voice picker a model gets, if any -------------
   mlx-audio picks a RANDOM named voice per render when --voice is absent, so the
   picker exists to let the user pin one. The refusals are the load-bearing part:
   llama-tts has NO --voice flag, so offering one on a tts-gguf would be a lie. */
const QMLX = { id: 'Qwen3-TTS-8bit', role: 'tts', format: 'tts-mlx',
               engine: 'mlx', voices: ['Chelsie', 'Ethan'] };
check('a known mlx family gets chips', P.voiceChoiceMode(QMLX) === 'chips');
check('an mlx model with no known voices gets free text',
      P.voiceChoiceMode({ ...QMLX, voices: [] }) === 'text');
// The Base-checkpoint case: the model's OWN config says it has no named voices, so
// the pane must state that rather than offering a box whose contents the engine
// silently ignores (Debi's A/B: two "different" voices, one identical render).
check('a model whose config declares NO named voices gets the note, not a box',
      P.voiceChoiceMode({ ...QMLX, voices: [],
                          voice_note: 'this model has no named voices' }) === 'note');
check('declared voices WIN over a stale note (chips beat prose)',
      P.voiceChoiceMode({ ...QMLX, voice_note: 'x' }) === 'chips');
check('a note on a tts-gguf changes nothing — there is no voice flag at all',
      P.voiceChoiceMode({ id: 'g', role: 'tts', format: 'tts-gguf',
                          voices: [], voice_note: 'x' }) === 'none');
check('a missing voices array still gets free text (never a crash)',
      P.voiceChoiceMode({ id: 'x', role: 'tts', format: 'tts-mlx' }) === 'text');
check('a tts-gguf gets NO picker (llama.cpp has no voice parameter)',
      P.voiceChoiceMode({ id: 'q', role: 'tts', format: 'tts-gguf',
                          voices: ['Chelsie'] }) === 'none');
check('an stt model gets no picker',
      P.voiceChoiceMode({ id: 'w', role: 'stt', format: 'stt-mlx' }) === 'none');
check('junk gets no picker',
      P.voiceChoiceMode(null) === 'none' && P.voiceChoiceMode({}) === 'none');
check('an entry with no role defaults to tts (the view always sets one)',
      P.voiceChoiceMode({ id: 'x', format: 'tts-mlx', voices: ['a'] }) === 'chips');

// ── 'clips': a cloning model's picker is the voice LIBRARY, not a name box ──────
check('a cloning model with no names gets the clip picker',
      P.voiceChoiceMode({ id: 'o', role: 'tts', format: 'tts-mlx', voices: [],
                          cloning: true }) === 'clips');
check('declared names BEAT the cloning verdict',
      P.voiceChoiceMode({ id: 'o', role: 'tts', format: 'tts-mlx', voices: ['serena'],
                          cloning: true }) === 'chips');
check('the clip picker replaces the old dead-end note for these models',
      P.voiceChoiceMode({ id: 'o', role: 'tts', format: 'tts-mlx', voices: [],
                          cloning: true, voice_note: 'no named voices' }) === 'clips');
check('a NON-cloning model with no names still gets free text',
      P.voiceChoiceMode({ id: 'u', role: 'tts', format: 'tts-mlx', voices: [] }) === 'text');
check('a gguf model never gets a clip picker (llama-tts has no ref_audio)',
      P.voiceChoiceMode({ id: 'g', role: 'tts', format: 'tts-gguf',
                          cloning: true }) === 'none');

/* Panel wiring facts, asserted against the panel SOURCE — the picker is only
   useful if it actually writes, and only one surface may write. */
check('the detail pane writes through POST /api/voice/entry-voice',
      /fetch\('\/api\/voice\/entry-voice'/.test(html));
check('the detail pane has a voice container',
      html.includes("id=\"ad-voice\"") && html.includes("getElementById('ad-voice')"));
check('a selected voice chip uses the gold .mp-act.on state',
      /\.mp-act\.on\s*\{/.test(html));
check('clearing posts an EMPTY string (the model-default sentinel)',
      html.includes("setEntryVoice(a.id, '')"));
check('the composer popover only DISPLAYS the voice (no picker there)',
      html.includes("'voice: ' + a.voice")
      && !/renderAudioPop[\s\S]{0,4000}entry-voice/.test(html));
check('switching voice stops any clip rendered with the old one',
      /async function setEntryVoice[\s\S]{0,900}stopSpeaking\(\)/.test(html));
// Window widened 2026-08-14: setEntryRef gained the length-guard note/refusal
// surfacing, so stopSpeaking() sits further down the function. The INVARIANT under test
// is unchanged (a re-pin must kill a clip rendered with the old reference) — only the
// distance is, and a proximity window is not the fact being pinned.
check('switching the REFERENCE CLIP also stops a clip rendered with the old voice',
      /async function setEntryRef[\s\S]{0,1600}stopSpeaking\(\)/.test(html));
check('the library delete is a two-step (a recording cannot be re-made)',
      /dataset\.armed[\s\S]{0,200}sure\?/.test(html));
check('a saved recording is auto-pinned onto the model it was recorded for',
      /async function saveClip[\s\S]{0,900}setEntryRef\(id, saved\)/.test(html));

// ── tts sub-badge: HOW this model's voice is chosen, read off the entry ─────────
// Both facts already ride on audio_entry_view (voices / cloning), so the badge is a
// label rather than a probe — and it must stay SILENT when we have no verdict.
check('a model with declared names badges "voices"',
      P.audioVoiceBadge({ role: 'tts', voices: ['serena'] }) === 'voices');
check('a cloning model badges "cloning"',
      P.audioVoiceBadge({ role: 'tts', cloning: true }) === 'cloning');
check('declared names WIN over the cloning verdict (same rule as the picker)',
      P.audioVoiceBadge({ role: 'tts', voices: ['serena'], cloning: true }) === 'voices');
check('no verdict ⇒ no badge (silence is not a verdict)',
      P.audioVoiceBadge({ role: 'tts' }) === ''
      && P.audioVoiceBadge({ role: 'tts', voices: [] }) === '');
check('an STT row never gets a voice badge',
      P.audioVoiceBadge({ role: 'stt', voices: ['x'] }) === '');
check('junk never throws',
      P.audioVoiceBadge(null) === '' && P.audioVoiceBadge({}) === '');
check('the badge reaches the row markup',
      P.audioRowHtml({ id: 'x', role: 'tts', cloning: true }, false).includes('cloning'));

// ── hide: read-only imports ONLY (app-owned rows keep Delete and nothing else) ──
check('an LM Studio import is hideable', P.isHideable('lmstudio-import') === true);
check('a Jan import is hideable', P.isHideable('jan-import') === true);
check('an HF-cache audio entry is hideable', P.isHideable('audio-hf-cache') === true);
check('a downloaded (app-owned) model is NOT hideable — it has a real Delete',
      P.isHideable('download') === false);
check('a local (app-owned) model is NOT hideable', P.isHideable('local') === false);
check('an unknown/absent source is not hideable',
      P.isHideable('') === false && P.isHideable(undefined) === false);
check('the panel hide rule matches the bridge allowlist',
      /HIDEABLE_SOURCES = \("lmstudio-import", "jan-import", "audio-hf-cache"\)/
        .test(fs.readFileSync(path.join(ROOT, 'bridge', 'app.py'), 'utf8')));
check('hiding is a two-step, like Delete',
      /function hideBtn[\s\S]{0,800}dataset\.armed/.test(html));
check('the hidden rows are unhide-able from the list bottom',
      /function renderHiddenRow[\s\S]{0,1600}setModelHidden\(h\.id, false\)/.test(html));

// ── the fp32 → bf16 nudge (nothing automatic; one sentence, or nothing) ────────
const FP32 = { id: 'OmniVoice', role: 'tts', size_bytes: 3.27 * 1024 * 1024 * 1024 };
check('a 3.27 GB OmniVoice entry gets the note',
      P.omnivoiceBf16Hint(FP32).startsWith('a bf16 build (~2 GB, same quality)'));
check('the note names the whole migration, ending in Delete',
      /download it, set it as default, re-pin your clip, then Delete this one\.$/
        .test(P.omnivoiceBf16Hint(FP32)));
check('the id match is case-insensitive',
      P.omnivoiceBf16Hint({ ...FP32, id: 'omnivoice-fp32' }) !== '');
check('the bf16 build itself is never told to download itself',
      P.omnivoiceBf16Hint({ ...FP32, id: 'OmniVoice-bfloat16' }) === ''
      && P.omnivoiceBf16Hint({ ...FP32, id: 'OmniVoice-bf16' }) === '');
check('a SMALL OmniVoice entry gets nothing (the threshold is the whole point)',
      P.omnivoiceBf16Hint({ ...FP32, size_bytes: 2.04 * 1024 * 1024 * 1024 }) === '');
check('exactly 3 GB is not "over 3 GB"',
      P.omnivoiceBf16Hint({ ...FP32, size_bytes: 3 * 1024 * 1024 * 1024 }) === '');
check('another big model is left alone',
      P.omnivoiceBf16Hint({ id: 'whisper-large-v3-turbo', role: 'stt',
                            size_bytes: 9e9 }) === '');
check('an STT entry never gets a TTS suggestion',
      P.omnivoiceBf16Hint({ ...FP32, role: 'stt' }) === '');
check('junk never throws',
      ['', null, undefined, {}, { id: 'x' }, { id: 'omnivoice', size_bytes: 'big' }]
        .every(x => P.omnivoiceBf16Hint(x) === ''));
check('the note is rendered on the audio detail pane',
      /omnivoiceBf16Hint\(a\)[\s\S]{0,200}md-imnote/.test(html));
check('nothing about it is automatic — it never calls a download or a default',
      !/omnivoiceBf16Hint[\s\S]{0,400}(dlStart|setVoiceDefault)/.test(html));

console.log('');
console.log(fails.length ? 'FAILED: ' + fails.join(', ') : 'ALL PASS');
process.exit(fails.length ? 1 : 0);
