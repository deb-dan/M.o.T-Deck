/* FLOATING-SURFACE GRAMMAR + VIEW PEEK (2026-08-21).
 *
 * Two things sample asked for after the Customize overlay landed:
 *   1. ONE look for everything that floats above the page — the panel had seven.
 *   2. Models / Music / Capabilities openable ON TOP of the page you are on, so a
 *      quick change does not cost you your place.
 *
 * The load-bearing questions this file answers:
 *   • does every floating surface actually wear the grammar, and does none of them
 *     keep a private copy of the ground that could drift again?
 *   • is the translucency the MEASURED value (readability over arbitrary content is
 *     the whole risk of a see-through surface) — and is the alpha pinned so a future
 *     "let's make it prettier" has to argue with a number?
 *   • can scrolling inside a floating surface ever scroll — or close — the page
 *     behind it? (both halves: overscroll containment AND the popovers' own
 *     inside-origin check)
 *   • does peekView really hand the borrowed node BACK, to the same place?
 *
 * The peek half is EXECUTED against a stub DOM rather than grepped: "the node returns
 * to its original position" is a claim about behaviour, and a regex cannot see it.
 *
 * Run: node bridge/tests/test_float_surface.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

// ── 1. the sanctioned block ─────────────────────────────────────────────────
console.log('the block');
const B0 = css.indexOf('FLOATING-SURFACE GRAMMAR + VIEW PEEK');
const B1 = css.indexOf('end floating-surface grammar');
ok(B0 > 0 && B1 > B0, 'the sanctioned block is present exactly once');
ok(css.indexOf('FLOATING-SURFACE GRAMMAR + VIEW PEEK', B0 + 1) === -1, '…and only once');
ok(css.indexOf('OPTIONAL "STUDIO" CHROME') > B1,
   'it sits BEFORE the studio block, which must stay last in the sheet');
ok(css.indexOf('end appearance overlay') < B0,
   '…and AFTER the appearance overlay, whose ground it now owns');
const blk = css.slice(B0, B1);
const noC = blk.replace(/\/\*[\s\S]*?\*\//g, '');
const sels = [...noC.matchAll(/(?:^|\})\s*([^{}]+?)\s*\{/g)].map(m => m[1].trim());
ok(sels.length === 16, 'the block declares exactly 16 rules (got ' + sels.length + ')');

// ── 2. the grammar itself ───────────────────────────────────────────────────
console.log('the grammar');
{
  // The tokens, not literals scattered per surface — that is what makes it ONE answer.
  ok(/:root \{ --float-bg:rgba\(20,18,29,\.72\)/.test(noC),
     'dark ground = --card at alpha .72 (MEASURED, see below — not the .70 first drafted)');
  ok(/html\[data-theme="light"\] \{ --float-bg:rgba\(250,246,236,\.72\)/.test(noC),
     'light gets the warm-paper equivalent at the SAME alpha');
  ok(/--float-blur:blur\(20px\) saturate\(140%\)/.test(noC), 'blur 20px / saturate 140%');
  ok(/--float-edge:var\(--line2\)/.test(noC) && /--float-shadow:/.test(noC),
     'the edge and the shadow are tokens too, so a surface cannot half-adopt the grammar');

  const surf = (noC.match(/\.float-surface \{[^}]*\}/) || [''])[0];
  ok(/background:var\(--float-bg\)/.test(surf), '.float-surface takes its ground from the token');
  ok(/border:1px solid var\(--float-edge\)/.test(surf), '…its edge');
  ok(/border-radius:14px/.test(surf), '…radius 14, the one corner for all of them');
  ok(/box-shadow:var\(--float-shadow\)/.test(surf), '…its shadow');
  ok(/-webkit-backdrop-filter:var\(--float-blur\)/.test(surf) &&
     /[^-]backdrop-filter:var\(--float-blur\)/.test(surf),
     '…and the blur WITH the WebKit prefix (this has to render in WKWebView)');
}

// ── 3. the alpha is defensible, not decorative ──────────────────────────────
// A see-through surface has to stay readable over ARBITRARY page content, so the worst
// case is the ground composited over the LIGHTEST thing the panel can put behind it.
// This recomputes it rather than trusting the comment.
console.log('readability (computed, not asserted)');
{
  const lin = c => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
  const L = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const ratio = (a, b) => { const l1 = Math.max(L(a), L(b)), l2 = Math.min(L(a), L(b)); return (l1 + 0.05) / (l2 + 0.05); };
  const over = (fg, alpha, bg) => fg.map((c, i) => alpha * c + (1 - alpha) * bg[i]);
  const m = noC.match(/--float-bg:rgba\((\d+),(\d+),(\d+),(\.\d+)\)/);
  ok(!!m, 'the dark ground parses');
  const card = [+m[1], +m[2], +m[3]], alpha = +m[4];
  ok(card.join(',') === '20,18,29', '…and it really is --card (#14121d)');

  const CREAM = [0xef, 0xe7, 0xd7], FG = [0xc9, 0xc4, 0xd4], WORST = CREAM;  // a solid field of --cream
  const ground = over(card, alpha, WORST);
  const rCream = ratio(CREAM, ground), rFg = ratio(FG, ground);
  console.log('       worst-case ground rgb(' + ground.map(Math.round).join(',') + ')'
    + ' — cream ' + rCream.toFixed(2) + ':1, fg ' + rFg.toFixed(2) + ':1');
  ok(rCream >= 4.5, 'primary text (--cream) clears 4.5:1 even in the impossible worst case');
  ok(rFg >= 4.5, 'body text (--fg) clears 4.5:1 there too — the tier that actually binds');
  // The number is not taste: it is where the margin is. .70 (the first draft) passes by
  // 0.02, and a little more transparency than that fails outright — so the pin exists to
  // make "let's make it prettier" argue with an arithmetic floor.
  ok(ratio(FG, over(card, 0.70, WORST)) < rFg,
     '…with MORE margin than .70 would have had (' + ratio(FG, over(card, 0.70, WORST)).toFixed(2) + ':1)');
  ok(ratio(FG, over(card, 0.66, WORST)) < 4.5,
     'and materially more transparency than the pin DOES fail the bar — the floor is real');
  // over the grounds that actually occur, it is nowhere near the edge
  const real = ratio(FG, over(card, alpha, [0x18, 0x15, 0x27]));   // --card2, the brightest panel ground
  ok(real >= 7, 'over a real page ground the same text reads at ' + real.toFixed(1) + ':1');
}

// ── 4. every floating surface wears it ──────────────────────────────────────
console.log('applied everywhere');
{
  const worn = [
    ['<dialog id="dlg" class="float-surface">',    'the install/plan dialog'],
    ['<dialog id="logdlg" class="float-surface">', 'the logs dialog'],
    ['<dialog id="palette" class="float-surface">', 'the command palette'],
    ['<dialog id="navdlg" class="float-surface">', 'the Customize overlay'],
    ['<div id="model-pop" class="float-surface"',  'the model popover'],
    ['<div id="audio-pop" class="float-surface"',  'the voice popover'],
    ['<div id="setup-card" class="float-surface">', 'the first-run setup card'],
    ['<div id="peek-card" class="float-surface">', 'the peek overlay'],
  ];
  for (const [needle, what] of worn) {
    ok(html.indexOf(needle) > 0, what + ' wears .float-surface');
    ok(html.indexOf(needle, html.indexOf(needle) + 1) === -1, '…exactly once');
  }
  // NEGATIVE: none of them may keep a private ground that could drift away again.
  const bodies = {
    '#model-pop, #audio-pop': (css.match(/#model-pop, #audio-pop \{[^}]*\}/) || [''])[0],
    '#setup-card':            (css.match(/#setup-card \{[^}]*\}/) || [''])[0],
    '#navdlg':                (css.match(/\n  #navdlg \{[^}]*\}/) || [''])[0],
  };
  for (const [name, body] of Object.entries(bodies)) {
    ok(body.length > 0, name + ' still has a rule of its own (for its SIZE)');
    ok(!/background:/.test(body) && !/box-shadow:/.test(body) && !/border:/.test(body)
       && !/border-radius:/.test(body),
       '…but declares no ground/edge/radius/shadow — those come from the grammar');
  }
}

// ── 5. scrolling (the two bugs) ─────────────────────────────────────────────
console.log('scroll behaviour');
{
  ok(/\.float-surface, \.float-surface \* \{ overscroll-behavior:contain; \}/.test(noC),
     'overscroll containment is applied to the surface AND every descendant — inert on '
     + 'anything that does not scroll, which is what makes it TOTAL (a scroll region '
     + 'added later cannot be missed)');
  // it must not be scoped to one surface's body, which is how this gets missed
  ok(!/#navdlg \.nv-body \{[^}]*overscroll/.test(css),
     '…and it is NOT hand-applied per region (that is the version that goes stale)');

  // the other half: an inside-origin scroll must not close a popover. Combined with
  // containment above, a list that hits its end can no longer raise an OUTSIDE scroll.
  for (const which of ['model', 'audio']) {
    const fn = (html.match(new RegExp('function ' + which + 'PopScroll\\(e\\)\\{[\\s\\S]*?\\n\\}')) || [''])[0];
    ok(fn.length > 0, which + 'PopScroll exists');
    ok(/pop\.contains\(e\.target\)/.test(fn) && /return;/.test(fn),
       '…and RETURNS for a scroll raised inside the popover (containment check)');
    ok(new RegExp("addEventListener\\('scroll', " + which + 'PopScroll').test(html),
       '…and it is what the scroll listener actually calls (not a bare close)');
    ok(!new RegExp("addEventListener\\('scroll', close" + which[0].toUpperCase() + which.slice(1) + 'Pop').test(html),
       '…the listener is NOT wired straight to the close (that was the original bug)');
  }
}

// ── 6. the peek — EXECUTED ──────────────────────────────────────────────────
// Grep can prove a reparent exists; only running it can prove the node comes BACK.
console.log('peek (executed)');
{
  const pStart = html.indexOf('const PEEK_VIEWS = [');
  const pEnd = html.indexOf('function peekKey(e)');
  ok(pStart > 0 && pEnd > pStart, 'the peek block is where the test expects it');
  const src = html.slice(pStart, html.indexOf('\n', pEnd + 40));

  // -- a stub DOM with real parent/child semantics (that is the thing under test)
  function El(id, tag) {
    return {
      id, tag: tag || 'div', hidden: false, children: [], parentNode: null,
      classList: { _s: {}, add(c) { this._s[c] = 1; }, remove(c) { delete this._s[c]; },
                   has(c) { return !!this._s[c]; } },
      textContent: '', set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html || ''; },
      appendChild(n) { if (n.parentNode) n.parentNode.remove(n); n.parentNode = this; this.children.push(n); return n; },
      insertBefore(n, ref) {
        if (n.parentNode) n.parentNode.remove(n);
        const i = this.children.indexOf(ref);
        this.children.splice(i < 0 ? this.children.length : i, 0, n);
        n.parentNode = this; return n;
      },
      removeChild(n) { this.remove(n); },
      remove(n) { const i = this.children.indexOf(n); if (i >= 0) this.children.splice(i, 1); n.parentNode = null; },
      addEventListener() {},
    };
  }
  function mkEnv(curView) {
    const main = El('main');
    const els = { main };
    for (const v of ['mc', 'chat', 'models', 'music', 'caps']) {
      const n = El('view-' + v); n.hidden = (v !== curView); main.appendChild(n); els[n.id] = n;
    }
    const body = El('body');
    const doc = {
      getElementById: id => els[id] || null,
      createElement: t => { const e = El('', t); return e; },
      createComment: t => { const c = El('#c'); c.comment = t; return c; },
      body, addEventListener() {}, removeEventListener() {},
    };
    // the overlay is built lazily by peekEnsure(); the stub cannot parse innerHTML, so
    // its two children are pre-registered exactly as that markup names them.
    const scrim = El('peek-scrim'); scrim.hidden = true;
    els['peek-scrim'] = scrim;
    els['peek-body'] = El('peek-body');
    els['peek-title'] = El('peek-title');
    const calls = [];
    return {
      env: {
        document: doc, curView,
        navEntry: id => ({ models: { id, view: 'models', label: 'Models' },
                           music: { id, view: 'music', label: 'Music' },
                           caps: { id, view: 'caps', label: 'Capabilities' },
                           chat: { id, view: 'chat', label: 'Chat' },
                           mc: { id, view: 'mc', label: 'MOT Main' },
                           logs: { id, view: null, label: 'Logs' },
                           aider: { id, view: null, label: 'Aider' } })[id] || null,
        setTimeout: () => {}, initModels: () => calls.push('models'),
        initCaps: () => calls.push('caps'), initMusic: () => calls.push('music'),
        stopMusicPoll: () => calls.push('stopMusicPoll'),
        closeModelPop: () => calls.push('closeModelPop'),
        closeAudioPop: () => calls.push('closeAudioPop'),
      },
      main, els, calls,
    };
  }
  const build = (curView, tail) => {
    const { env, main, els, calls } = mkEnv(curView);
    const fn = new Function(...Object.keys(env), src + '\n' + tail);
    return { out: fn(...Object.values(env)), main, els, calls };
  };

  // -- the eligibility rule
  {
    const r = build('mc', `return { models: peekEligible('models'), music: peekEligible('music'),
      caps: peekEligible('caps'), chat: peekEligible('chat'), mc: peekEligible('mc'),
      logs: peekEligible('logs'), aider: peekEligible('aider'), junk: peekEligible('nope') };`);
    ok(r.out.models && r.out.music && r.out.caps, 'Models / Music / Capabilities are peekable');
    ok(!r.out.chat, 'CHAT is NOT peekable (streaming composer, live mic, artifact pane)');
    ok(!r.out.mc, 'MISSION CONTROL is NOT peekable (it is the page you stand on)');
    ok(!r.out.logs, 'LOGS is not peekable (it is already a dialog)');
    ok(!r.out.aider, 'a LANE has no in-panel view, so it cannot be peeked');
    ok(!r.out.junk, 'an unknown id is refused rather than throwing');
  }

  // -- the reparent AND the restore
  {
    const r = build('mc', `
      const before = document.getElementById('main').children.map(n => n.id).join(',');
      const opened = peekOpen('models', null, null);
      const during = document.getElementById('main').children.map(n => n.id).join(',');
      const inBody = document.getElementById('peek-body').children.map(n => n.id).join(',');
      const vis = !document.getElementById('view-models').hidden;
      const scrimShown = !document.getElementById('peek-scrim').hidden;
      closePeek();
      const after = document.getElementById('main').children.map(n => n.id).join(',');
      return { before, during, after, inBody, opened, vis, scrimShown,
               hiddenAgain: document.getElementById('view-models').hidden,
               bodyEmpty: document.getElementById('peek-body').children.length,
               scrimHidden: document.getElementById('peek-scrim').hidden,
               stillPeeking: !!peekState };`);
    ok(r.out.opened === true, 'peekOpen reports that it opened');
    ok(r.out.inBody === 'view-models', 'the REAL view node is moved into the overlay body');
    ok(r.out.during.indexOf('view-models') < 0, '…and is genuinely out of <main> while borrowed');
    ok(r.out.vis === true, '…and visible there, whatever showView had left the hidden flag at');
    ok(r.out.scrimShown === true, 'the overlay is shown');
    ok(r.out.after === r.out.before,
       'on close the node is back in <main> IN ITS ORIGINAL POSITION (' + r.out.after + ')');
    ok(r.out.hiddenAgain === true, '…hidden again, because it is not the active view');
    ok(r.out.bodyEmpty === 0 && r.out.scrimHidden === true, '…and the overlay is emptied and hidden');
    ok(r.out.stillPeeking === false, '…and no peek is recorded any more');
  }

  // -- position is preserved even when the node is NOT last
  {
    const r = build('mc', `
      const before = document.getElementById('main').children.map(n => n.id).join(',');
      peekOpen('caps', null, null); closePeek();
      peekOpen('models', null, null); closePeek();
      return { before, after: document.getElementById('main').children.map(n => n.id).join(',') };`);
    ok(r.out.after === r.out.before,
       'two peeks in a row leave the view order untouched: ' + r.out.after);
  }

  // -- one at a time
  {
    const r = build('mc', `
      peekOpen('models', null, null);
      peekOpen('caps', null, null);
      return { body: document.getElementById('peek-body').children.map(n => n.id).join(','),
               view: peekState && peekState.view,
               main: document.getElementById('main').children.map(n => n.id).join(',') };`);
    ok(r.out.body === 'view-caps', 'opening a second peek returns the first and shows only the new one');
    ok(r.out.view === 'caps', '…and the recorded state is the new one');
    ok(r.out.main.indexOf('view-models') >= 0, '…with the first view handed back to <main>');
  }

  // -- the active view is a no-op WITH a flash, not an empty overlay onto its own hole
  {
    const r = build('models', `
      const el = { classList: { _s:{}, add(c){this._s[c]=1;}, remove(c){delete this._s[c];} } };
      const opened = peekOpen('models', null, el);
      return { opened, flashed: !!el.classList._s['pk-flash'],
               peeking: !!peekState,
               scrimBuilt: document.getElementById('peek-scrim').hidden };`);
    ok(r.out.opened === false, 'peeking the view you are ALREADY on does nothing');
    ok(r.out.peeking === false, '…no peek is opened');
    ok(r.out.flashed === true, '…the glyph flashes instead, so the click is not silent');
  }

  // -- entry work runs, exactly as showView would have run it
  {
    const r = build('mc', `peekOpen('music', null, null); return 0;`);
    ok(r.calls.indexOf('music') >= 0, 'a music peek runs initMusic (its poll is armed)');
    ok(r.calls.indexOf('closeModelPop') >= 0 && r.calls.indexOf('closeAudioPop') >= 0,
       '…and the position:fixed popovers are closed, never stranded under the overlay');
  }
  {
    const r = build('mc', `peekOpen('music', null, null); closePeek(); return 0;`);
    ok(r.calls.indexOf('stopMusicPoll') >= 0,
       'closing a music peek RETIRES its poll — it must not keep ticking invisibly');
  }
  {
    const r = build('music', `peekOpen('caps', null, null); closePeek(); return 0;`);
    ok(r.calls.indexOf('stopMusicPoll') < 0,
       '…but closing a DIFFERENT peek while Music is the live view leaves its poll alone');
  }

  // -- closePeek is idempotent (a second Esc, a close during teardown)
  {
    const r = build('mc', `
      peekOpen('caps', null, null); closePeek(); closePeek(); closePeek();
      return document.getElementById('main').children.map(n => n.id).join(',');`);
    ok(r.out === 'view-mc,view-chat,view-models,view-music,view-caps',
       'closePeek twice over is inert (state is cleared BEFORE the node is handed back)');
  }
}

// ── 7. the wiring around it ─────────────────────────────────────────────────
console.log('wiring');
{
  const sv = html.slice(html.indexOf('function showView(v) {'),
                        html.indexOf('/* ---------- VIEW PEEK'));
  ok(/if \(peekState && peekState\.view === v\) closePeek\(\);/.test(sv),
     'navigating TO the peeked view hands the node back FIRST');
  ok(sv.indexOf('closePeek();') < sv.indexOf("document.getElementById('view-mc').hidden"),
     '…before the hidden flags are written, or the view you asked for would stay in the overlay');
  ok(/if \(peekState\) peekState\.node\.hidden = false;/.test(sv),
     'a still-borrowed view stays visible when you navigate underneath it');
  ok(/else if \(!\(peekState && peekState\.view === 'music'\)\) stopMusicPoll\(\)/.test(sv),
     '…and a music PEEK survives that navigation with its poll intact');

  ok(/scrim\.addEventListener\('mousedown', e => \{ if \(e\.target === scrim\) closePeek\(\); \}\)/.test(html),
     'an outside mousedown closes — on the scrim itself, so a click inside cannot');
  ok(/function peekKey\(e\) \{ if \(e\.key === 'Escape'\)/.test(html), 'Esc closes');
  ok(/document\.addEventListener\('keydown', peekKey, true\)/.test(html) &&
     /document\.removeEventListener\('keydown', peekKey, true\)/.test(html),
     '…and the key listener is REMOVED on close (no listener left behind per peek)');
  ok(/onclick="closePeek\(\)"/.test(html), 'the ✕ closes');
  // it must not invent a second copy of a view
  ok(!/id="peek-view-/.test(html) && !/cloneNode/.test(html.slice(html.indexOf('const PEEK_VIEWS'),
     html.indexOf('function peekKey'))),
     'the peek never CLONES a view — a second Models pane could disagree with the first');
}

console.log('');
console.log(fails ? (fails + ' failure(s) of ' + checks) : ('float surface: ' + checks + ' checks passed'));
process.exit(fails ? 1 : 0);
