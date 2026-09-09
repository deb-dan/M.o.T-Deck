#!/usr/bin/env node
// MUSIC "STUDIO DECK" — the per-page view (2026-08-20, FABLE-MUSIC-DECK-SPEC.md).
//
// This file guards the SAME two things test_studio_chrome.js guards, for the same
// reason: three separate sessions once "fixed" a toggle from the stylesheet and were
// wrong every time. So the block is proved to be SERVED and PARSED (byte range, brace
// depth, appears once), every selector is proved to be PREFIXED (with the attribute
// absent the Music page is byte-for-byte the editorial page), and the pure panel
// helpers are EXECUTED rather than grepped.
//
// It also pins the composition rule that makes the deck safe: this block styles no
// button chrome, so the global ▣ axis keeps ownership of every control on the page.

const fs = require('fs');
const path = require('path');
const P = path.join(__dirname, '..', 'panel', 'index.html');
const html = fs.readFileSync(P, 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  if (!cond) { fails++; console.error('FAIL: ' + msg); }
}

// ---------- locate the block ----------
const css = html.split('<style>')[1].split('</style>')[0];
const START = '/* ============ MUSIC STUDIO DECK';
const END = 'end music deck';
ok(css.includes(START), 'the music-deck block exists in the stylesheet');
ok(css.includes(END), 'the music-deck block is closed by its end marker');

const bi = css.indexOf(START);
const ei = css.indexOf(END);
const block = css.slice(bi, ei);

{
  const s0 = html.indexOf('<style>'), e0 = html.indexOf('</style>');
  const abs = html.indexOf(START);
  ok(html.indexOf(START, abs + 1) === -1,
     'the deck block appears exactly ONCE in the file (not duplicated into an '
     + 'artifact-iframe srcdoc template string)');
  ok(s0 >= 0 && e0 > s0 && abs > s0 && abs < e0,
     'the deck block lies inside the FIRST <style> element');
  const upto = css.slice(0, bi).replace(/\/\*[\s\S]*?\*\//g, '')
                              .replace(/"[^"]*"|'[^']*'/g, '""');
  let d = 0;
  for (const ch of upto) { if (ch === '{') d++; else if (ch === '}') d--; }
  ok(d === 0, 'CSS brace depth is 0 where the deck block starts (got ' + d + ')');
  // the GLOBAL studio-chrome block must still be the last thing in the sheet — its own
  // test asserts that, and this block was placed BEFORE it precisely so it stays true.
  ok(css.indexOf('OPTIONAL "STUDIO" CHROME') > ei,
     'the deck block sits BEFORE the global studio-chrome block (which must stay last)');
}

// ---------- every rule prefixed; the count is read out of the panel ----------
const noComments = block.replace(/\/\*[\s\S]*?\*\//g, '');
const sels = (noComments.match(/([^{}]+)\{/g) || [])
  .map(s => s.slice(0, -1).trim()).filter(Boolean);

ok(sels.length === 29, 'the deck block declares exactly 29 rules (got ' + sels.length + ')');

function splitTop(str, sep) {
  const out = []; let d = 0, cur = '';
  for (const ch of str) {
    if (ch === '(') d++;
    else if (ch === ')') d--;
    if (ch === sep && d === 0) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  out.push(cur);
  return out;
}

const PREFIX = '#view-music[data-mview="studio"]';
for (const sel of sels) {
  const parts = splitTop(sel, ',').map(s => s.trim());
  ok(parts.every(p => p.startsWith(PREFIX)),
     'every selector part is prefixed with the view attribute: ' + sel.slice(0, 60));
}

const outside = css.slice(0, bi) + css.slice(ei);
ok(!outside.includes('data-mview'),
   'no data-mview selector exists outside the deck block — with the attribute absent '
   + 'the Music page is byte-for-byte the editorial page');

// tokens are namespaced and no palette token is redefined
const decls = noComments.match(/--[a-z0-9-]+\s*:/g) || [];
ok(decls.length > 0 && decls.every(d => d.startsWith('--mv-')),
   'every custom property the block DEFINES is namespaced --mv-*: ' + decls.join(' '));
for (const t of ['--bg:', '--gold:', '--cream:', '--serif:', '--mono:', '--card:']) {
  ok(!noComments.includes(t), 'the deck block never redefines ' + t);
}

// COMPOSITION WITH ▣ (spec A + C7): the deck owns LAYOUT, the chrome axis owns
// CONTROLS. A background/border on a button here would silently out-specify the global
// axis (id + attr beats its class rules) and re-break exactly what C7 asked us to fix.
for (const sel of sels) {
  if (!/button|\.cap-btn|\.chip\b|#mus-go/.test(sel)) continue;
  const body = noComments.slice(noComments.indexOf(sel) + sel.length);
  const decl = body.slice(body.indexOf('{') + 1, body.indexOf('}'));
  for (const p of ['background', 'border-color', 'font-family', 'text-transform']) {
    ok(!new RegExp('(^|;)\\s*' + p + '\\s*:').test(decl),
       'the deck sets no ' + p + ' on a control (' + sel.trim() + ') — ▣ owns control chrome');
  }
}

// the light axis composes: it overrides only its OWN tokens, with zero specificity
ok(/:where\(html\[data-theme="light"\] \*\)/.test(noComments),
   'the light-theme override uses :where(), so it adds no specificity and the selector '
   + 'still starts with the view prefix');

// the deck's surfaces exist
for (const target of ['#music-hero', '.mv-kick', '.mv-title', '.mv-grad', '.mv-sub',
                      '.mv-pills', '.mv-pill', '.mv-grid', '.mv-card', '.mv-tile',
                      '.mv-name', '.mv-tag', '.mv-gist', '.mv-wave', '.mv-bar',
                      '.mv-acts', '.mv-engs', '.mv-eng', '.mv-3']) {
  ok(sels.some(x => x.includes(target)), 'the deck styles ' + target);
}
ok(sels.some(x => x.includes('.mv-grad'))
   && /linear-gradient\(90deg, var\(--mv-g1\), var\(--mv-g2\)\)/.test(noComments),
   'the hero phrase carries the gradient Fable specified (gold → rose)');

// ---------- markup ----------
ok(/id="music-view-chip"[^>]*onclick="toggleMusicView\(\)"/.test(html),
   'the ✦ Studio view chip calls toggleMusicView()');
ok(/id="music-hero"[^>]*hidden/.test(html),
   'the hero container ships HIDDEN, so classic view shows nothing before any render');
ok(/id="music-tplhead"[^>]*onclick="toggleMusicTpls\(\)"/.test(html),
   'the Templates header is the disclosure control');
ok(!/alert\('Policies UI lands in M2'\)/.test(html),
   'the deliberately removed Policies nav entry is not resurrected by S12 dialogs');

// ---------- EXECUTE the pure helpers ----------
function grab(name) {
  const i = html.indexOf('function ' + name + '(');
  if (i < 0) return null;
  // brace-match the body, ignoring braces inside strings/template literals
  const open = html.indexOf('{', i);
  let d = 0, j = open, q = null;
  for (; j < html.length; j++) {
    const ch = html[j], prev = html[j - 1];
    if (q) { if (ch === q && prev !== '\\') q = null; continue; }
    if (ch === '"' || ch === "'" || ch === '`') { q = ch; continue; }
    if (ch === '{') d++;
    else if (ch === '}') { d--; if (!d) break; }
  }
  return html.slice(i, j + 1);
}
const HELPERS = ['musicHash', 'musicAccent', 'musicGlyph', 'musicTint', 'musicWaveBars'];
for (const h of HELPERS) ok(grab(h), h + '() is extractable from the panel');
const ctx = {};
const src = HELPERS.map(grab).join('\n')
  + '\n' + (html.match(/const MUSIC_ACCENTS = \{[^}]*\};/) || [''])[0]
  + '\n' + (html.match(/const MUSIC_ACCENT_CYCLE = \[[^\]]*\];/) || [''])[0]
  + '\n' + (html.match(/const MUSIC_GLYPHS = \{[^}]*\};/) || [''])[0]
  + '\nmodule.exports = {musicHash, musicAccent, musicGlyph, musicTint, musicWaveBars,'
  + ' MUSIC_ACCENTS, MUSIC_ACCENT_CYCLE};';
const mod = { exports: {} };
new Function('module', src)(mod);
const M = mod.exports;

ok(M.musicAccent({ id: 'neo-soul' }) === '#c96c8e'
   && M.musicAccent({ id: 'rock' }) === '#e06565'
   && M.musicAccent({ id: 'lofi' }) === '#8b93f8'
   && M.musicAccent({ id: 'cinematic' }) === '#46c99a'
   && M.musicAccent({ id: 'edm' }) === '#d9b36c'
   && M.musicAccent({ id: 'folk' }) === '#e0a458',
   'every built-in template keeps the accent Fable assigned it');
ok(M.MUSIC_ACCENT_CYCLE.indexOf(M.musicAccent({ id: 'u18f3' })) >= 0,
   'a user template cycles the same six accents rather than inventing colour');
ok(M.musicAccent({ id: 'u1' }) === M.musicAccent({ id: 'u1' }),
   'a template\'s accent is stable across renders');
ok(M.musicAccent(null) && M.musicAccent(undefined) && M.musicAccent({}),
   'musicAccent is total over a junk template');
ok(M.musicGlyph({ id: 'rock' }) === '⚡' && M.musicGlyph({ id: 'nope' }) === '♫',
   'glyphs are text, with a musical fallback for anything unlisted');
ok(/^rgba\(201,108,142,0?\.18\)$/.test(M.musicTint('#c96c8e', 0.18)),
   'the tile tint is computed here rather than relying on color-mix()');
for (const junk of ['', '#zzz', null, undefined, '#12345']) {
  ok(M.musicTint(junk, 0.18) === 'var(--card2)',
     'musicTint falls back to a real token on junk input: ' + junk);
}
{
  const bars = M.musicWaveBars('rock');
  ok(Array.isArray(bars) && bars.length === 5, 'the waveform motif is exactly five bars');
  ok(bars.every(b => b >= 5 && b <= 16), 'every bar height stays inside the 16px row');
  ok(JSON.stringify(bars) === JSON.stringify(M.musicWaveBars('rock')),
     'a template\'s waveform never changes between renders');
  ok(JSON.stringify(bars) !== JSON.stringify(M.musicWaveBars('folk')),
     'different templates get different waveforms');
}

// ---------- view state ----------
ok(/let musicView = 'classic'/.test(html), 'classic is the default view');
ok(/localStorage\.setItem\('motdeck-music-view'/.test(html), 'the view is persisted');
ok(/localStorage\.getItem\('motdeck-music-view'\)\s*===\s*'studio'/.test(html),
   'only the literal \'studio\' turns the deck on (anything else is classic)');
ok(/loadMusicView\(\);/.test(html), 'the persisted view is restored at boot');
{
  const t = grab('toggleMusicView');
  ok(/renderMusic\(\)/.test(t) && /renderMusicLibrary\(\)/.test(t),
     'flipping the view re-renders BOTH halves of the page');
  ok(/feed\('music',/.test(t), 'the flip is logged to the activity feed with a real tag');
  ok(!/data-theme|motdeck-chrome/.test(t),
     'the deck toggle touches neither the theme nor the global chrome axis');
}
{
  const a = grab('applyMusicView');
  ok(/delete v\.dataset\.mview/.test(a),
     'classic REMOVES the attribute entirely (no data-mview="classic" half-state)');
  ok(/'▤ Classic' : '✦ Studio view'/.test(a), 'the chip names the state it would go to');
}

// ---------- the renderers branch on the view, not on the chrome ----------
{
  const r = grab('renderMusicTemplates');
  ok(/musicStudio\(\) \? musicTplCard\(t\) : musicTplRow\(t\)/.test(r),
     'the gallery draws cards in the deck and rows in classic from ONE renderer');
  ok(/box\.className = musicStudio\(\) \? 'mv-grid' : 'cap-card'/.test(r),
     'the container class follows the view');
  ok(!/dataset\.chrome/.test(r),
     'no music renderer branches on the GLOBAL chrome axis (CSS alone decides that)');
}
ok(!/dataset\.chrome/.test(html.slice(html.indexOf('function renderMusicCreate'))),
   'renderMusicCreate does not branch on the global chrome axis either');

console.log(fails ? `\n${fails} failure(s) of ${checks}` : `OK — 0 failure(s) (${checks} checks)`);
process.exit(fails ? 1 : 0);
