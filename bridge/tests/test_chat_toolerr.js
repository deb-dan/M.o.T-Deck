/* BE-01 — THE ✗ CHIP FOR A FAILED TOOL, IN THE MAIN CHAT LANE (fixed 2026-08-28).
 *
 * THE BUG, and it is the worst shape this project recognises — a LIE-TO-USER.
 * On 2026-08-27 a model narrated "Done. Added Purchases…" over a write that had
 * returned an error, and nothing on screen contradicted it. That was fixed in v1.5.9
 * for the LOffice AI panel: bridge/routers/hermes.py maps `is_error` + `error` onto
 * every tool_output frame for EVERY lane, and office.html draws a red ✗ chip carrying
 * the tool's own sentence. The bug-echo sweep (docs/research/2026-08-28-bug-echo-
 * sweep.md, BE-01) found the echo: bridge/panel/index.html's chat lane consumed the
 * same frames and rendered them as "reading results…" whatever they carried — the word
 * `is_error` did not occur anywhere in the page. A failed native or MCP tool in the
 * MAIN chat was exactly as invisible as it had been in the incident.
 *
 * WHAT THIS FILE PINS, and why in this order:
 *   1. the CHIP ITSELF, executed against a DOM shim — it is drawn, it carries the
 *      tool's own sentence, and it is drawn on the HOLDER so the end-of-turn
 *      renderChatBody() (which rebuilds .body from scratch) cannot delete it;
 *   2. the SUMMARY LINE never stamps ✓ over a tool that failed. The summary is the
 *      most-read artifact of a turn; a green tick above a red chip is the same lie in
 *      miniature;
 *   3. the HANDLER: one branch, in the one place every lane's tool_output is rendered;
 *   4. the ALL-DESIGNS RULE: every colour the chip uses is a token that Editorial,
 *      all three theme packs AND both studio variants declare (the --on-wash lesson),
 *      and the chip is shaped so studio's impeccable fence cannot classify it as a
 *      nested card;
 *   5. the CONTROLS: the bridge still maps is_error, and office.html still draws its
 *      chip — if either regresses, this fix is sitting on nothing.
 *
 * Run: node bridge/tests/test_chat_toolerr.js   (from repo root)
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const P = f => path.join(ROOT, 'bridge', f);
const html = fs.readFileSync(P('panel/index.html'), 'utf8');
const office = fs.readFileSync(P('panel/office.html'), 'utf8');
const hermes = fs.readFileSync(P('routers/hermes.py'), 'utf8');
const studio = fs.readFileSync(P('panel/assets/studio-design.css'), 'utf8');

let fails = 0, checks = 0;
function ok(cond, msg) {
  checks++;
  console.log((cond ? '  ok  ' : '  FAIL ') + msg);
  if (!cond) fails++;
}

/* ── a DOM shim just big enough to RUN the chip renderer ─────────────────────
   Deliberately tiny and deliberately NOT jsdom: this suite must run with node and
   nothing else, like every other .js suite here. It implements exactly what the three
   functions touch, and it records order, so "the chip is appended to the holder" is a
   fact the test can read rather than assume. */
function El(tag) {
  return {
    tag, className: '', _text: '', children: [],
    get textContent() {
      return this._text + this.children.map(c => c.textContent).join('');
    },
    set textContent(v) { this._text = String(v); this.children = []; },
    appendChild(c) { this.children.push(c); return c; },
    // the one selector the code uses
    querySelectorAll(sel) {
      const want = String(sel).replace(/^\./, '');
      const out = [];
      const walk = n => { for (const c of n.children) {
        if (String(c.className).split(/\s+/).includes(want)) out.push(c);
        walk(c);
      } };
      walk(this);
      return out;
    },
  };
}
const document = { createElement: El };

// extract + execute. Both anchors asserted before slicing (a -1 would hand the whole
// file to new Function and make every assertion below meaningless).
const a = html.indexOf('function chatToolErrChip(holder, tool, why){');
const b = html.indexOf('async function sendChat(');
ok(a > 0, 'the chip renderer is where this test expects it');
ok(b > a, 'and sendChat follows it (the slice has a real end anchor)');
const src = html.slice(a, b);
ok(/function chatToolErr\(holder, tool, why\)\{/.test(src)
   && /function chatToolErrsRedraw\(holder\)\{/.test(src),
   'all three chip functions are inside the extracted block');
const F = new Function('document', src
  + '; return {chatToolErrChip, chatToolErr, chatToolErrsRedraw};')(document);

// ── 1. the chip ─────────────────────────────────────────────────────────────
console.log('\n1. the chip is drawn, and says what went wrong');
{
  const holder = El('div');
  const body = El('div'); body.className = 'body';
  holder.appendChild(body);
  F.chatToolErr(holder, 'office_write_cells',
                'refused: Budget.xlsx is open in another writer');
  const chips = holder.querySelectorAll('.toolerr');
  ok(chips.length === 1, 'one failed tool → exactly one chip');
  const t = chips[0].textContent;
  ok(t.indexOf('✗') === 0, 'it opens with the ✗ glyph');
  ok(t.includes('office_write_cells'), 'it NAMES the tool');
  ok(t.includes('refused: Budget.xlsx is open in another writer'),
     'and carries the TOOL\'S OWN SENTENCE — "a tool failed" is not an answer to '
     + '"what went wrong" (the whole point of the office.html chip it ports)');
  ok(holder.children.indexOf(chips[0]) > holder.children.indexOf(body),
     'the chip is a child of the HOLDER, after .body — so renderChatBody(), which '
     + 'rebuilds .body from scratch at [DONE], cannot delete it');
  ok(!body.querySelectorAll('.toolerr').length,
     '…and nothing was drawn INSIDE .body (that is the deletable place)');
}
{
  const holder = El('div');
  F.chatToolErr(holder, 'write_file', '');
  ok(holder.querySelectorAll('.toolerr')[0].textContent
       .includes('it failed, and said nothing about why'),
     'a failure with NO message says so, rather than implying we know more than we do');
  const h2 = El('div');
  F.chatToolErr(h2, '', '   ');
  const t2 = h2.querySelectorAll('.toolerr')[0].textContent;
  ok(t2.includes('tool') && t2.includes('said nothing about why'),
     'a nameless tool with a whitespace-only reason still renders a usable chip');
  const h3 = El('div');
  F.chatToolErr(h3, undefined, undefined);
  ok(h3.querySelectorAll('.toolerr').length === 1,
     'undefined/undefined does not throw (a malformed frame must not kill the stream)');
}
{
  const holder = El('div');
  F.chatToolErr(holder, 'a', 'one'); F.chatToolErr(holder, 'b', 'two');
  ok(holder.querySelectorAll('.toolerr').length === 2, 'two failures → two chips');
  ok((holder._toolErrors || []).length === 2,
     'and both are REMEMBERED on the holder, which is what survives a re-render');
  ok(F.chatToolErrsRedraw(holder) === 0,
     'the re-assert after renderChatBody() is a NO-OP when the chips are still there '
     + '(idempotent — it may be called twice)');
  // simulate a future renderer that wipes the holder: the chips must come back
  holder.children = [];
  ok(F.chatToolErrsRedraw(holder) === 2
     && holder.querySelectorAll('.toolerr').length === 2,
     '…and it RESTORES them if some future renderer ever does clear the holder');
  ok(F.chatToolErrsRedraw(El('div')) === 0,
     'a holder that never had an error is left alone (no empty state invented)');
}

// ── 2. the summary line never lies ──────────────────────────────────────────
console.log('\n2. the ✓ summary never stamps a tool that failed');
{
  const s = html.slice(html.indexOf('function chatSummary(holder){'),
                       html.indexOf('function chatToolErrChip('));
  ok(s.length > 50, 'chatSummary is where this test expects it');
  ok(/st\.error/.test(s) && /class="x">✗</.test(s),
     'chatSummary branches on st.error and renders ✗ for a failed step');
  ok(/class="d">✓</.test(s),
     '…while a successful step keeps its ✓ (the change is a branch, not a rewrite)');
  const M = new Function('esc', s.replace('function chatSummary', 'function _cs')
    + '; return function(steps){ return steps.map(st => st.error'
    + ' ? "X " + esc(st.tool) : "V " + esc(st.tool)).join(" . "); };')(x => x);
  ok(M([{tool: 'read_file'}, {tool: 'write_file', error: 'denied'}])
       === 'V read_file . X write_file',
     'executed: the failed step is ✗ and the successful one is ✓, in order');
}

// ── 3. the handler ──────────────────────────────────────────────────────────
console.log('\n3. the frame handler');
{
  ok((html.match(/j\.type === 'tool_output'/g) || []).length === 1,
     'there is exactly ONE tool_output handler in this page — so the fix covers every '
     + 'lane that shares the stream renderer (Hermes, Odysseus-agent, direct), not one');
  const h = html.slice(html.indexOf("j.type === 'tool_output'"),
                       html.indexOf("j.type === 'web_sources'"));
  ok(/if \(j\.is_error\)/.test(h), 'it branches on is_error — BE-01\'s missing branch');
  ok(/chatToolErr\(holder, etool, ewhy\)/.test(h), '…and draws the chip');
  ok(/steps\.push\(\{tool: etool, error:/.test(h) && /last\.error = ewhy/.test(h),
     '…and marks the step, so the summary above can render ✗');
  ok(/if \(last && !last\.error\)/.test(h),
     'a tool_output with no tool_start before it (a frame lost to a reconnect) starts '
     + 'its OWN step rather than writing to index -1 — the same guard office.html has');
  ok(/if \(holder\._summarized\) \{ holder\._summarized = false; chatSummary\(holder\); \}/.test(h),
     'a summary ALREADY on screen is redone — otherwise a late failure leaves a green '
     + 'tick standing over a red chip');
  ok(/\} else if \(!holder\._summarized\) \{[\s\S]{0,300}reading results…/.test(h),
     '"reading results…" no longer clobbers a rendered summary (it would erase the ✗)');
  const done = html.slice(html.indexOf("if (payload === '[DONE]')"),
                          html.indexOf("let j; try { j = JSON.parse(payload)"));
  ok(done.indexOf('renderChatBody(body, body.textContent)')
       < done.indexOf('chatToolErrsRedraw(holder)'),
     'and the re-assert runs AFTER the end-of-turn render, which is the only order '
     + 'that means anything');
}

// ── 4. THE ALL-DESIGNS RULE ─────────────────────────────────────────────────
console.log('\n4. all designs (Editorial · light · gold · cyber · studio ×2)');
{
  const css = html.split('<style>')[1].split('</style>')[0];
  // Collect the chip's rules as WHOLE BLOCKS, not matching lines: a multi-line rule's
  // continuation lines do not mention the selector, and a line filter would silently
  // miss every declaration after the first (which is where the colours live).
  function blocksFor(sheet, re){
    let out = '', i = 0;
    while (true){
      const m = re.exec(sheet);
      if (!m) break;
      const end = sheet.indexOf('}', m.index);
      if (end < 0) break;
      out += sheet.slice(m.index, end + 1) + '\n';
      re.lastIndex = end;
      if (++i > 50) break;
    }
    return out;
  }
  const chipRules = blocksFor(css, /\.cmsg \.toolerr[^{]*\{/g)
                  + blocksFor(css, /\.cmsg \.statusline \.x[^{]*\{/g);
  ok(/\.cmsg \.toolerr \{/.test(css), 'the chip has a rule');
  ok(/\.cmsg \.statusline \.x \{ color:var\(--bad\); \}/.test(css),
     'and so does the ✗ in the summary line');
  // every colour used must be a var() — a literal is unreachable by any palette
  const literals = chipRules.match(/#[0-9a-fA-F]{3,8}|\brgba?\(/g) || [];
  ok(!literals.length,
     'NOT ONE hardcoded colour in the chip\'s CSS — the --on-wash lesson (a literal is '
     + 'a colour no palette swap can reach). found: ' + JSON.stringify(literals));
  const tokens = [...new Set((chipRules.match(/var\((--[a-z0-9-]+)\)/g) || [])
                             .map(s => s.slice(4, -1)))];
  ok(tokens.length >= 3, 'it uses tokens: ' + tokens.join(', '));
  // …and every one of those tokens must be DECLARED by every design
  const blocks = {
    'Editorial (:root)': css.slice(css.indexOf(':root {'), css.indexOf('html[data-theme="light"]')),
    'Warm Paper': css.slice(css.indexOf('html[data-theme="light"] {'), css.indexOf('/* light-only fixes')),
    'Luxury Gold': css.slice(css.indexOf('html[data-theme="gold"] {'), css.indexOf('html[data-theme="cyber"]')),
    'Cyber': css.slice(css.indexOf('html[data-theme="cyber"] {'), css.indexOf('=================== end theme packs')),
    'studio-dark': studio.slice(studio.indexOf('html[data-design="studio"] {'),
                                studio.indexOf('html[data-design="studio"][data-dvariant="light"] {')),
    'studio-light': studio.slice(
      studio.indexOf('html[data-design="studio"][data-dvariant="light"] {'),
      studio.indexOf('html[data-design="studio"][data-dvariant="light"] {') + 3000),
  };
  /* THE RULE, STATED PRECISELY — because "every design declares every token" is the
     WRONG rule and would have been a false failure here. The theme-pack guardrail is
     token swaps of the COLOUR VOICE only: --mono/--serif are declared ONCE on :root and
     a pack deliberately never restates them (a pack that changed typography would be a
     rule fork, which test_theme_packs.js fails). Studio does the same. So:
       · every token must be on :root, or it resolves to nothing in Editorial;
       · every COLOUR token must additionally be declared by EVERY design, or that
         design cannot reach it — which is exactly the --on-wash defect. */
  const root = blocks['Editorial (:root)'];
  const isColour = tk => {
    const m = root.match(new RegExp(tk + ':\\s*([^;]+);'));
    return !!m && /^(#|rgba?\(|hsla?\()/.test(m[1].trim());
  };
  for (const tk of tokens) ok(root.includes(tk + ':'), ':root declares ' + tk);
  const colours = tokens.filter(isColour);
  ok(colours.length >= 3, 'the chip\'s COLOUR tokens are: ' + colours.join(', '));
  ok(tokens.filter(tk => !isColour(tk)).every(tk => /^--(mono|serif)$/.test(tk)),
     'the only non-colour tokens it uses are the typography ones a pack is FORBIDDEN '
     + 'to restate');
  for (const [name, blk] of Object.entries(blocks)) {
    ok(blk.length > 100, name + ': its token block was found');
    for (const tk of colours) {
      ok(blk.includes(tk + ':'), name + ' declares ' + tk);
    }
  }
  // studio's own fence: this chip must not read as a nested CARD
  const rule = css.slice(css.indexOf('.cmsg .toolerr {'),
                         css.indexOf('.cmsg .toolerr .te-x'));
  ok(!/border:/.test(rule) && !/border-left:/.test(rule) && !/box-shadow:/.test(rule),
     'the chip carries NO border and NO shadow, so impeccable\'s card definition '
     + '((shadow OR border) AND (radius OR bg)) cannot classify it — no nested-cards '
     + 'at depth two, and no border-accent-on-rounded from a 2px coloured edge');
  ok(/color:var\(--bad\)/.test(css.slice(css.indexOf('.cmsg .toolerr .te-x'),
                                         css.indexOf('.cmsg .toolerr .te-why'))),
     '…the colour is carried by the GLYPH instead — this page\'s own established idiom '
     + '(#chat-talk.rec .talk-dot)');
  /* ⚠️ CONTRAST, MEASURED LIVE AND THEN PINNED. The chip's REASON is the tool's own
     sentence — the string that contradicts a false "Done" — so it is the last text in
     this page that may be hard to read. Drafted on --dim (the secondary-text token) it
     measured 3.44:1 on Editorial's --card2, under WCAG AA. It is --fg, and these are
     the ratios measured in the running panel with getComputedStyle across all six
     looks (Editorial 8.06 · Warm Paper 8.24 · Gold 7.71 · Cyber 8.03 · studio-dark
     7.63 · studio-light 9.24); the FENCE is the token choice, because a future palette
     edit is exactly what would silently undo it. */
  const whyRule = css.slice(css.indexOf('.cmsg .toolerr .te-why'),
                            css.indexOf('.cmsg .toolerr .te-why') + 200);
  ok(/color:var\(--fg\)/.test(whyRule),
     'the REASON is on --fg, not --dim — the one string the user most needs to read '
     + 'must not be the faintest thing in the chip (measured 3.44:1 on --dim)');
  ok(!/--faint/.test(chipRules), '…and nothing in the chip uses --faint');
  const fs2 = (rule.match(/font:(\d+(?:\.\d+)?)px/) || [])[1];
  ok(Number(fs2) >= 11,
     'and its type is ' + fs2 + 'px, at or above studio\'s 11px undersized-ui-text floor');
}

// ── 5. the controls: this fix is standing on something ──────────────────────
console.log('\n5. controls — the v1.5.9 half of the fix still holds');
ok(/fr\["is_error"\] = True/.test(hermes) && /fr\["error"\] = _err_text/.test(hermes),
   'the bridge still maps is_error + error onto tool_output, for every lane');
ok(/_err_text\.lstrip\(\)\.startswith\("\{"\)/.test(hermes),
   '…including the ONE unwrap, so `error` is the tool\'s sentence and not a wall of '
   + 'braces (measured live 2026-08-28)');
ok(/function csErrChip\(wrap, tool, why\)/.test(office) && /j\.is_error/.test(office),
   'office.html still draws its own ✗ chip (the reference implementation)');
ok(/\(held\.errors \|\| \[\]\)\.forEach\(e => csErrChip/.test(office),
   '…and still re-draws them after its own end-of-turn render');

console.log('');
console.log(fails ? fails + ' failure(s) of ' + checks
                  : 'chat tool-error chips: ' + checks + ' checks passed');
process.exit(fails ? 1 : 0);
