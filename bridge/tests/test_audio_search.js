/* Panel-side unit test for the Audio tab's HF SEARCH helpers (T2).
 *
 * The functions are EXTRACTED from bridge/panel/index.html by name (the pattern
 * test_audio_rows.js established) rather than copied, so an edit in the panel trips
 * this test instead of silently drifting from it.
 *
 * Run: node bridge/tests/test_audio_search.js   (from repo root)
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
    if (inStr) { if (c === inStr && prev !== '\\') inStr = null; }
    else if (c === '"' || c === "'" || c === '`') inStr = c;
    else if (c === '{') depth++;
    else if (c === '}') { depth--; if (depth === 0) return html.slice(at, j + 1); }
    prev = c;
  }
  throw new Error('unbalanced braces extracting ' + name);
}

// fmtGB is a dependency of audioProbeSummary — take the panel's own copy.
eval(grab('fmtGB'));
eval(grab('audioLicPill'));
eval(grab('audioLicText'));
eval(grab('audioProbeSummary'));
eval(grab('audioGetState'));

// ── licence pills (reuse the existing fit-pill palette; no new CSS) ───────────
check('an ok licence is the green pill', audioLicPill('ok') === 'fit-ok');
check('an unknown licence is the AMBER pill', audioLicPill('unknown') === 'fit-slow');
check('a non-commercial licence is the RED pill', audioLicPill('nc') === 'fit-no');
check('an unrecognised badge degrades to green rather than blank',
      audioLicPill('') === 'fit-ok' && audioLicPill(undefined) === 'fit-ok');
check('the three classes are ones the stylesheet already defines',
      ['fit-ok', 'fit-slow', 'fit-no'].every(c => html.includes('.' + c + ' {')));

check('the licence id is shown verbatim when known',
      audioLicText({ license: 'cc-by-nc-sa-4.0' }) === 'cc-by-nc-sa-4.0');
check('a missing licence says so instead of showing nothing',
      audioLicText({ license: '' }) === 'licence unknown'
      && audioLicText(null) === 'licence unknown');

// ── the probe summary line ───────────────────────────────────────────────────
check('a tts-mlx probe reads engine · size · voices',
      audioProbeSummary({ format: 'tts-mlx', size_bytes: 1932735283, voice_count: 9 })
      === 'TTS · MLX · 1.8 GB · 9 named voices');
check('one voice is singular',
      audioProbeSummary({ format: 'tts-mlx', size_bytes: 0, voice_count: 1 })
      === 'TTS · MLX · 1 named voice');
check('no voices ⇒ no voice clause (never claim 0 voices as a feature)',
      audioProbeSummary({ format: 'stt-mlx', size_bytes: 1073741824, voice_count: 0 })
      === 'Speech-to-text · MLX · 1.0 GB');
check('an unmeasured size is omitted, not printed as 0 GB',
      audioProbeSummary({ format: 'unknown', size_bytes: 0 }) === 'unrecognised');
check('a transformers verdict is labelled in plain words',
      audioProbeSummary({ format: 'transformers' }) === 'transformers checkpoint');
check('the gguf lane is labelled by its engine',
      audioProbeSummary({ format: 'tts-gguf', size_bytes: 1481763717 })
      === 'TTS · llama.cpp · 1.4 GB');
check('an unknown format falls through to its own name (no crash)',
      audioProbeSummary({ format: 'weird-new-lane' }) === 'weird-new-lane');
check('audioProbeSummary survives a missing probe', audioProbeSummary(null) === '');

// ── the Get button: it must never lie ────────────────────────────────────────
check('a downloadable probe gives an enabled Get',
      JSON.stringify(audioGetState({ can_get: true, format: 'tts-mlx' }))
      === JSON.stringify({ disabled: false, label: 'Get', reason: '' }));
const nc = audioGetState({ can_get: false, block_reason: 'non-commercial licence' });
check('a blocked probe disables the button', nc.disabled === true);
check('…and carries the bridge’s OWN reason, not a panel guess',
      nc.reason === 'non-commercial licence');
check('…and stops calling itself Get', nc.label === 'Unavailable');
check('a blocked probe with no reason still says something',
      audioGetState({ can_get: false }).reason.length > 0);
check('a failed probe is disabled, not silently enabled',
      audioGetState(null).disabled === true && audioGetState(undefined).disabled === true);

// ── wiring facts (read from the panel source) ────────────────────────────────
for (const frag of ['/api/models/hf/audio?kind=', '/api/models/hf/audio/probe?repo=',
                    'id="as-results"', 'id="as-kind"', 'function toggleAudioSearch',
                    'function audioSearch', 'function audioProbe']) {
  check('the panel wires ' + frag, html.includes(frag));
}
check('the three search lanes are the bridge’s three kinds',
      ['value="tts"', 'value="tts-gguf"', 'value="stt"'].every(v => html.includes(v)));
check('Get routes through the EXISTING download manager with the probed hint',
      html.includes("dlStart(p.repo, p.file || '',") &&
      html.includes('voice_format: p.format, mmproj: p.mmproj'));
check('a refused download puts its reason ON the card (truthful-Get rule)',
      /audioProbe[\s\S]*?mp-err[\s\S]*?download failed/.test(html));
check('the search section is collapsed by default (the starters stay first)',
      html.includes('<div id="as-body" hidden>'));

console.log(fails.length ? '\nFAILED: ' + fails.join(', ')
                         : '\nall audio-search panel checks passed');
process.exit(fails.length ? 1 : 0);
