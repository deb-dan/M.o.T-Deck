/* THE HELP SURFACE (roadmap §2.4, v1.5.27).
 *
 * WHAT THIS FILE GUARDS, and why each group is the shape it is:
 *
 *  1. THE SUBSET IS REAL. The panel ships a ~90-line markdown renderer instead of the
 *     vendored markdown-it, and the whole safety of that choice rests on one claim:
 *     the source document uses only the syntax the renderer handles. So this asserts
 *     it against docs/USER-EXPLAINERS.md ITSELF — no links, no images, no fenced code,
 *     no raw HTML. The day somebody pastes a link into the help text, this fails here
 *     rather than silently rendering `[text](url)` as literal characters to a user.
 *
 *  2. THE RENDERER, EXECUTED. The pure half is extracted from the shipped page and run
 *     over the real document and over hostile input. The bar is the doctrine's: a
 *     LIE-TO-USER outranks a crash, and for a renderer the lie is a SILENT DROP —
 *     words that were written and are not on screen. Group 2 counts words.
 *
 *  3. THE ADVERSARIAL LEDGER, pinned. Every finding from the build's own adversarial
 *     pass is a test here, named, so the fix cannot be undone by a tidy-up:
 *       A-1 (LIE) the first draft scanned forward to `# ` and DISCARDED everything it
 *                 walked over — a document opening with prose lost its lead-in silently
 *       A-2 (LIE) html in the source must be escaped, not injected
 *       A-3       an odd number of backticks must not swallow the rest of the line
 *       A-4       a `## ` with no title gave the contents rail an invisible row
 *       A-5       duplicate section titles must not collide into one anchor
 *       A-6       helpJump must not re-render the document it is scrolling to
 *
 *  4. THE WIRING. The view, the route, the ⌘K entry, the first-run hand-off, and the
 *     nav registry seam (the id table half lives in test_nav_model.py /
 *     test_nav_panel.js; this owns the VIEW half — showView, the peek, the solo
 *     exclusion).
 *
 *  5. ALL DESIGNS (Debi's standing rule). Editorial, the three packs and studio
 *     light/dark. The mechanism, asserted structurally: Help's prose is `.art-md`, a
 *     class studio already owns, and no rule in Help's own block hardcodes a colour.
 *
 * Run: node bridge/tests/test_help_view.js
 */
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'index.html'), 'utf8');
const sd = fs.readFileSync(path.join(ROOT, 'bridge', 'panel', 'assets', 'studio-design.css'), 'utf8');
const md = fs.readFileSync(path.join(ROOT, 'docs', 'USER-EXPLAINERS.md'), 'utf8');
const routerSrc = fs.readFileSync(path.join(ROOT, 'bridge', 'routers', 'help.py'), 'utf8');
const shipSrc = fs.readFileSync(path.join(ROOT, 'scripts', 'ship.sh'), 'utf8');
const css = html.split('<style>')[1].split('</style>')[0];
const script = html.split('</style>').slice(1).join('</style>');

let fails = 0, checks = 0;
function ok(cond, msg) { checks++; console.log((cond ? '  ok  ' : '  FAIL ') + msg); if (!cond) fails++; }

// ── extract + execute the PURE renderer, from the shipped source ─────────────
const start = html.indexOf('const HELP_URL =');
const end = html.indexOf('async function initHelp()');
ok(start > 0 && end > start, 'the help renderer block is where the test expects it');
const shim = `
  function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;'); }
  function escAttr(s){ return esc(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }`;
const M = new Function(shim + html.slice(start, end) + `
  ; return { HELP_URL, HELP_SRC, helpInline, helpSlug, helpBlocks, helpParse, helpMatches };`)();
const DOC = M.helpParse(md);
const strip = s => String(s).replace(/<[^>]*>/g, ' ').replace(/&amp;/g, '&')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'");

// ═════════════════════════════════════════════════════════════════════════════
console.log('1. the subset the renderer claims, checked against the real document');
// ═════════════════════════════════════════════════════════════════════════════
{
  const body = md.replace(/`[^`]*`/g, '');       // code spans may contain anything
  ok(!/\[[^\]]*\]\([^)]*\)/.test(body), 'no markdown LINKS in the source (unsupported)');
  ok(body.indexOf('![') < 0, 'no images');
  ok(md.indexOf('```') < 0, 'no fenced code blocks');
  ok(!/<[a-zA-Z][a-zA-Z0-9]*[\s>/]/.test(body), 'no raw HTML tags');
  // …and the constructs it DOES use are all present, so the renderer is exercised by
  // the real file rather than only by the fixtures below.
  for (const [what, re] of [['h1', /^#\s/m], ['h2', /^##\s/m], ['h3', /^###\s/m],
                            ['blockquote', /^>\s/m], ['hr', /^---$/m],
                            ['pipe table', /^\|/m], ['bullets', /^-\s/m],
                            ['numbers', /^\d+\.\s/m], ['bold', /\*\*/],
                            ['italic', /(?<!\*)\*(?!\*)/], ['code span', /`/]]) {
    ok(re.test(md), 'the source really uses ' + what + ' (so the renderer is exercised by it)');
  }
  // the renderer's own manifest of the subset is written down where it is implemented
  ok(/THE SUBSET, stated exactly/.test(html),
     'the handled subset is enumerated AT the renderer, not only in this test');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n2. the renderer, executed over the real document');
// ═════════════════════════════════════════════════════════════════════════════
{
  ok(DOC.sections.length >= 5, DOC.sections.length + ' sections parsed out of the document');
  const wanted = ['Voice', 'Models', 'Window and layout'];
  for (const w of wanted) ok(DOC.sections.some(s => s.title === w), 'section present: ' + w);
  ok(DOC.title === 'MOT Deck explainers', 'the `# ` line is lifted out as the doc title');
  ok(DOC.lead.length > 0, '…and the lead-in before the first `## ` is KEPT, not skipped');

  // NO SILENT DROP — the load-bearing property, measured rather than eyeballed. Every
  // non-trivial word of the source has to appear in the rendered text.
  // DOC.title is included because it IS shown — as the view's own <h1>, not inside the
  // document body, which is the one deliberate relocation this renderer makes.
  const rendered = strip(DOC.title + ' ' + DOC.lead
    + DOC.sections.map(s => s.title + ' ' + s.html).join(' '));
  const srcWords = md.replace(/[#>|*`_-]/g, ' ').split(/\s+/)
    .filter(w => w.length > 3 && /^[A-Za-z][A-Za-z']*$/.test(w));
  const missing = [...new Set(srcWords)].filter(w => rendered.indexOf(w) < 0);
  ok(missing.length === 0,
     'every word of the source reaches the rendered output — 0 dropped'
     + (missing.length ? ' (missing: ' + missing.slice(0, 12).join(', ') + ')' : ''));

  // structure
  const voice = DOC.sections.find(s => s.title === 'Voice');
  ok(/<table>/.test(voice.html), 'the Voice table renders as a real table');
  ok(!/\|---\|/.test(strip(voice.html)),
     '…and the |---| delimiter row is STRUCTURE, never a visible data row');
  ok(/<div class="hlp-tw">/.test(voice.html),
     '…inside a scroll wrapper, so a wide table cannot push the page sideways');
  ok((voice.html.match(/<tr>/g) || []).length >= 6, '…with every row of it (header + 5)');
  ok(/<ul><li>/.test(voice.html), 'bullets render as a list');
  const wrong = DOC.sections.find(s => s.title === 'When something looks wrong');
  ok(/<ol><li>/.test(wrong.html), 'a numbered list renders as <ol>, not as four paragraphs');
  ok(/<code>hermes\.max_turn_s<\/code>/.test(wrong.html), 'inline `code` renders as <code>');
  // ⚠️ THE COUNT IS DERIVED, NOT WRITTEN DOWN (widened by the S22 slice, which added a
  // fifth entry to this list and turned a real property into a stale magic number). The
  // property being guarded was never "there are four items" — it is "a wrapped
  // continuation line does not become its own item", i.e. the rendered count equals the
  // number of `N. ` starts in the SOURCE, whatever that number is. Derived, the fence
  // now catches the wrapping bug on every future edit instead of only failing on them.
  const wrongMd = md.split('## When something looks wrong')[1] || '';
  const wrongStarts = (wrongMd.split('\n## ')[0].match(/^\d+\. /gm) || []).length;
  ok(wrongStarts >= 4, 'the numbered list is still a numbered list in the source');
  ok((wrong.html.match(/<li>/g) || []).length === wrongStarts,
     `…and a bullet that wraps onto an indented line stays ONE item (${wrongStarts} items,`
     + ' not one per line)');
  const hermes = DOC.sections.find(s => /^Hermes tools/.test(s.title));
  const hermesMd = md.split(/^## Hermes tools.*$/m)[1] || '';
  const hermesSubStarts = (hermesMd.split(/^## /m)[0].match(/^###\s+\S.*$/gm) || []).length;
  ok(hermesSubStarts > 0 && hermes.subs.length === hermesSubStarts,
     `all ${hermesSubStarts} source \`### \` subsections are collected for the contents rail`);
  for (const u of hermes.subs) {
    ok(hermes.html.indexOf('id="' + u.id + '"') >= 0,
       'the rail id "' + u.id + '" is an id that really exists in the rendered body '
       + '(minted once and read back, so the uniquifier cannot drift them apart)');
  }
  ok(!/<hr/.test(DOC.sections.map(s => s.html).join('')),
     'the `---` rules are dropped: the layout rules its own sections, and two rules read '
     + 'as a mistake');
  // Find the semantic section. A new Help section must not
  // turn an inline-format test into an accidental assertion about section order.
  const chatLanes = DOC.sections.find(s => /^Chat lanes/.test(s.title));
  ok(/<strong>Agent<\/strong>/.test(chatLanes.html), '**bold** inside a table cell works');
  ok(/<em>/.test(chatLanes.html), '…and *italic*');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n2b. the API page is EXPLAINED, not merely mentioned (Debi, 2026-09-02)');
// ═════════════════════════════════════════════════════════════════════════════
/* "api page looks good… let's ensure it's well explained in help too." The four things
   a person actually has to understand before another app talks to this runner, each
   asserted on the RENDERED text rather than on the markdown — so a topic that gets
   reworded survives, and a topic that gets deleted does not. Every claim here is a
   claim the API page itself makes on screen (bridge/panel/index.html apiEndpointHtml /
   apiKeysHtml / apiLogHtml and bridge/routers/apikeys.py::ENDPOINTS); the pairing is
   the point — Help must not drift into describing a page that no longer exists.

   ⚠️ COUNTED, NOT LISTED. The check is "every topic below is covered", derived from the
   TOPICS table, so adding a fifth topic here is the only edit a fifth topic needs. */
{
  const api = DOC.sections.find(s => s.title.indexOf('API') === 0);
  ok(!!api, 'the document has an API section');
  const t = strip(api.html).toLowerCase();
  const TOPICS = [
    ['what the page IS — a local address other apps point at',
     /openai-compatible/.test(t) && /own machine/.test(t) && /127\.0\.0\.1:6767/.test(t)],
    ['the three fields another app asks for, INCLUDING the model name',
     /model name/.test(t) && /serving/.test(t) && /copy button/.test(t)],
    ['keys are shown once and pasted into the other app',
     /create key/.test(t) && /once/.test(t) && /never shown again/.test(t)],
    ['revoke exists and takes two clicks',
     /revoke/.test(t) && /two clicks/.test(t)],
    ['restart-to-apply, and WHY — the engine reads the key file once, at startup',
     /restart to apply/.test(t) && /llama\.cpp/.test(t) && /once/.test(t)
       && /(read the file again|re-read)/.test(t)],
    ['…in BOTH directions: a revoked key keeps working until the restart',
     /revoked/.test(t) && /still works/.test(t)],
    ['the route catalogue, and the "need a launch flag" chips',
     /routes served/.test(t) && /launch flag/.test(t)
       && /--embeddings/.test(t) && /v1\/chat\/completions/.test(t)],
    ['…and WHY the dead routes are listed rather than hidden',
     /deliberate/.test(t) && /embeddings/.test(t)],
    ['the request log is honestly split: rows are our lanes, totals are everything',
     /totals/.test(t) && /one row per\s*turn/.test(t.replace(/\s+/g, ' '))],
    ['…and WHY direct callers appear only in the totals',
     /(goose and opencode|goose)/.test(t) && /directly/.test(t)
       && /no line of its own|no row of its own/.test(t)],
    ['keys never leave the machine',
     /data\/api_keys\.json/.test(t) && /leaves the machine/.test(t)],
  ];
  const uncovered = TOPICS.filter(([, hit]) => !hit).map(([name]) => name);
  for (const [name, hit] of TOPICS) ok(hit, 'Help covers: ' + name);
  ok(uncovered.length === 0,
     TOPICS.length + ' of ' + TOPICS.length + ' API topics covered'
     + (uncovered.length ? ' (missing: ' + uncovered.join('; ') + ')' : ''));
  // …and it is PROSE, not a spec dump: the section stays inside the document's own
  // voice, which here means it is written as bullets with bold lead-ins like every
  // other section, and carries no fenced code or table.
  ok(/<ul><li>/.test(api.html), 'the API section is written as bullets, like its neighbours');
  ok(!/<table>/.test(api.html) && !/<pre/.test(api.html),
     '…with no table and no code block — the renderer subset and the house voice agree');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n3. the adversarial ledger — every finding, pinned');
// ═════════════════════════════════════════════════════════════════════════════
{
  // A-1 (LIE-TO-USER): content before the title was silently discarded.
  const noTitle = M.helpParse('> a standing note\n\nand a paragraph\n\n## S\n\nbody\n');
  ok(strip(noTitle.lead).indexOf('standing note') >= 0
     && strip(noTitle.lead).indexOf('and a paragraph') >= 0,
     'A-1 a document with NO `# ` title keeps its whole lead-in (the first draft threw '
     + 'away everything it scanned past, silently — the worst failure a help renderer has)');
  ok(M.helpParse('lead first\n\n# Title\n\n## S\n\nx').title === 'Title',
     '…and the title is still found when prose precedes it');

  // A-2 (LIE-TO-USER): injection.
  const eq = M.helpParse('## X\n\n<script>alert(1)</script>\n\n| a | <img src=x onerror=y> |\n|---|---|\n| <b>z</b> | w |\n');
  const h = eq.sections[0].html;
  ok(h.indexOf('<script') < 0 && h.indexOf('&lt;script&gt;') >= 0,
     'A-2 html in the source is ESCAPED, never injected (paragraph)');
  ok(h.indexOf('onerror=') < 0 || h.indexOf('&lt;img') >= 0,
     '…and inside a table cell too');
  ok(M.helpInline('<b>x</b> **y**').indexOf('<b>') < 0,
     '…because the inline pass escapes BEFORE it decorates');

  // A-3: an odd number of backticks.
  const odd = M.helpParse('## X\n\nsome `unclosed and **bold**\n');
  ok(strip(odd.sections[0].html).indexOf('unclosed and **bold**') >= 0,
     'A-3 an odd backtick count leaves the tail as text — the words stay on screen');

  // A-4: the invisible rail row.
  ok(M.helpParse('## \n\nbody\n').sections[0].title === 'Untitled section',
     'A-4 a `## ` with no title gets a name, so the contents rail cannot grow an '
     + 'invisible, unclickable row');

  // A-5: colliding anchors.
  const dup = M.helpParse('## Same\n\na\n\n## Same\n\nb\n');
  ok(dup.sections[0].id !== dup.sections[1].id,
     'A-5 two sections with the same title get different anchors (a rail link that '
     + 'scrolls to the wrong section is a lie about where you are)');

  // A-6: the jump must not rebuild what it is scrolling to.
  const jump = /function helpJump\(id, el\)[\s\S]*?\n}/.exec(script);
  ok(!!jump && jump[0].indexOf('renderHelp(') < 0,
     'A-6 helpJump does NOT call renderHelp — re-rendering replaces the nodes the '
     + 'smooth scroll is travelling to, and the jump lands nowhere');
  ok(!!jump && /classList\.remove\('on'\)/.test(jump[0]) && /classList\.add\('on'\)/.test(jump[0]),
     '…it moves the highlight on the links directly instead');
  // A-7 (LIE-TO-USER, found by DRIVING the live panel): the rail did not scroll at all.
  // `scrollIntoView({behavior:'smooth'})` is a silent no-op in this WKWebView —
  // measured: the plain call moved the page to 1869px, the smooth call left scrollY at
  // 0 and threw nothing. Every link in the contents rail was dead and said so nowhere.
  // comments stripped: the function's own comment NAMES both of the things the code
  // must not do, which is exactly what a comment recording a fix looks like.
  const jumpCode = jump ? jump[0].replace(/\/\*[\s\S]*?\*\//g, '') : '';
  ok(jumpCode.indexOf("behavior:'smooth'") < 0 && /scrollIntoView\(true\)/.test(jumpCode),
     'A-7 helpJump uses the plain scrollIntoView — the smooth form silently does not '
     + 'scroll in this WKWebView, which made every contents-rail link a dead click');
  ok(jumpCode.indexOf('window.scrollTo') < 0,
     '…and still scrollIntoView rather than window.scrollTo, because in a ⧉ peek the '
     + 'scroller is the overlay body and not the window');

  // and the totality guarantees: no shape may throw, and none may hang.
  for (const [name, src] of [['empty', ''], ['whitespace', '  \n\n '],
                             ['one pipe', '## T\n\n|\n'], ['bare rule', '---\n'],
                             ['a table with no delimiter', '## T\n\n| a | b |\n| 1 | 2 |\n'],
                             ['deep heading', '## T\n\n###### deep\n'],
                             ['huge indent run', '## T\n\n- a\n      b\n      c\n'],
                             ['crlf', '## T\r\n\r\nbody\r\n']]) {
    let threw = false;
    try { M.helpParse(src); } catch (e) { threw = true; }
    ok(!threw, 'helpParse is TOTAL: ' + name + ' does not throw');
  }
  ok(M.helpParse('').sections.length === 0 && M.helpParse('').lead === '',
     '…and an empty document parses to an empty document, not to junk');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n4. the filter, executed');
// ═════════════════════════════════════════════════════════════════════════════
{
  const q = s => DOC.sections.filter(x => M.helpMatches(x, s));
  ok(q('').length === DOC.sections.length, 'an empty filter shows everything');
  ok(q('voice').length >= 1 && q('voice').some(s => s.title === 'Voice'),
     'a filter on a TITLE word finds that section');
  const kokoro = q('kokoro');
  ok(kokoro.length === 1 && kokoro[0].title === 'Voice',
     'a filter on a word that appears only in the BODY finds it (full-text, not titles)');
  ok(q('agent').some(s => /^Chat lanes/.test(s.title)),
     '…including a word that is only inside markdown emphasis (**Agent**) — the filter '
     + 'searches the raw source, so the markup never hides a word from it');
  ok(q('zzzznotathing').length === 0, 'a filter that matches nothing matches nothing');
  ok(q('VOICE'.toLowerCase()).length === q('voice').length, 'matching is case-insensitive');
  // the empty state — the standing rule: every reachable state lands on something usable
  ok(/Nothing in Help matches/.test(script),
     'a filter with no matches lands on a sentence, not on a blank column');
  ok(/Try a shorter word/.test(script), '…that says what to do next');
  ok(/helpState\.q = String\(v == null \? '' : v\)\.trim\(\)\.toLowerCase\(\)/.test(script),
     'the filter trims and lower-cases, so a stray space cannot empty the page');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n5. the wiring — view, route, ⌘K, first-run hand-off');
// ═════════════════════════════════════════════════════════════════════════════
{
  ok(/<div id="view-help" hidden>/.test(html), 'the Help view exists in the page');
  ok(/document\.getElementById\('view-help'\)\.hidden = \(v !== 'help'\);/.test(script),
     'showView hides/shows it like every other view');
  ok(/if \(v === 'help'\) initHelp\(\);/.test(script), '…and arms it on entry');
  ok(/PEEK_VIEWS = \['models', 'music', 'caps', 'help', 'api'\]/.test(script),
     'Help is peekable (⧉) — the question you ask WHILE doing the thing');
  ok(/else if \(view === 'help'\) initHelp\(\);/.test(script),
     '…and a peek arms it the same way a navigation does');
  // the SOLO exclusion. Before Help, "sidebar-only" and "has no view" were the same
  // set, so the exclusion happened by accident; it now has to be explicit.
  ok(/NAV_SIDEBAR_ONLY\.indexOf\(e\.id\) < 0/.test(script),
     'SOLO_VIEWS excludes sidebar-only entries EXPLICITLY — `?solo=help` would be a URL '
     + 'nothing in the product can produce');
  const solo = new Function(`const NAV_ENTRIES = ${JSON.stringify(
      [{ id:'mc', view:'mc' }, { id:'chat', view:'chat' }, { id:'help', view:'help' },
       { id:'logs', view:null }])};
    const NAV_SIDEBAR_ONLY = ['logs','help','api'];
    ${/const SOLO_VIEWS[\s\S]*?\.map\(e => e\.view\);/.exec(script)[0]}
    ${/function soloView\(search\)[\s\S]*?\n}/.exec(script)[0]}
    return { SOLO_VIEWS, soloView };`)();
  ok(solo.SOLO_VIEWS.indexOf('help') < 0, '…executed: help is not a solo view');
  ok(solo.soloView('?solo=help') === null, '…and ?solo=help resolves to nothing');
  ok(solo.soloView('?solo=chat') === 'chat', '…while a real solo view still resolves');

  // ⌘K
  ok(/\{t:'Help', k:'\?', f:\(\)=>showView\('help'\)\}/.test(script),
     'the command palette has a Help entry');
  ok(/`always` in the nav model lets a user hide the Help row/.test(script),
     '…and it says WHY it is load-bearing (it is what makes hiding the row safe)');
  // FOUND BY DRIVING: the Appearance editor's own prose said "Logs stays reachable
  // from ⌘K", which stopped being the whole truth the moment Help joined `always`.
  // Shipped copy that is quietly incomplete is the same defect class as stale help.
  // …and WIDENED again at S32, when `api` became the third `always` entry. The defect
  // class is the point: shipped copy that is quietly incomplete rots the same way
  // whether it names one row too few or two.
  ok(/except Logs, Help and API, which stay reachable from ⌘K/.test(script),
     'the Customize dialog names ALL the always-reachable rows, not just Logs');

  // FIRST-RUN (roadmap §2.4): one line on the existing tour, not a rebuilt tour.
  const tour = /const TOUR = \[[\s\S]*?\n\];/.exec(script)[0];
  ok((tour.match(/\{ sel:/g) || []).length === 4,
     'the tour is still FOUR steps — the brief said one line, not a fifth step');
  ok(/tourToHelp\(\)/.test(tour), '…and the last step links to Help');
  ok(/open Help/.test(tour) && /⌘K → Help/.test(tour),
     '…naming both routes to it (the sidebar row and the palette)');
  ok(/function tourToHelp\(\) \{ endTour\(\); showView\('help'\); \}/.test(script),
     'the hand-off ENDS THE TOUR FIRST — otherwise the scrim is left over the view it '
     + 'just opened');
  ok(/\.coach \.coach-help \{/.test(css), '…and the link is styled as a link');

  // THE ROUTE CONTRACT
  ok(M.HELP_URL === '/api/help/explainers', 'the panel calls /api/help/explainers');
  ok(routerSrc.indexOf('@app.get("/api/help/explainers")') >= 0,
     '…and the bridge declares exactly that route, with GET only');
  ok(routerSrc.indexOf('@app.post') < 0, '…and no POST: this surface is read-only');
  ok(/ROOT \/ "docs" \/ HELP_DOC/.test(routerSrc),
     '…serving docs/USER-EXPLAINERS.md off ROOT (repo in a checkout, snapshot in the app)');
  ok(/media_type="text\/markdown/.test(routerSrc), '…as text/markdown, RAW');
  ok(/no-store/.test(routerSrc),
     '…no-store, or a WKWebView would keep serving yesterday\'s help after a ship');
  ok(/except FileNotFoundError/.test(routerSrc) && /run \.\/scripts\/ship\.sh/.test(routerSrc),
     'a missing file is a 404 whose message NAMES THE FIX, not a blank page');
  ok(/Help could not be loaded/.test(script),
     '…and the panel renders that message rather than an empty column');
  ok(/the bridge did not answer/.test(script),
     '…and a dead bridge gets its own sentence too');
  // ZERO-CODE CONTENT UPDATES — the brief's actual requirement, asserted structurally.
  ok(html.indexOf('Every entry here answers a question') < 0,
     'THE HELP TEXT IS NOT BAKED INTO THE PAGE — updating help is a documentation edit, '
     + 'never a code edit, and the page never grows by the size of the prose');
  ok(/for _d in "\$ROOT"\/docs\/\*\.md/.test(shipSrc),
     'ship.sh copies the top-level docs/*.md into the snapshot — without this Help is '
     + 'permanently empty in the only place it matters');
  ok(shipSrc.indexOf('cp -R "$ROOT/docs') < 0,
     '…and does NOT recursively copy docs/handoff + docs/research (1.5MB of internal '
     + 'archaeology that is not shipped product)');
}

// ═════════════════════════════════════════════════════════════════════════════
console.log('\n6. ALL DESIGNS (Debi\'s standing rule) — the mechanism, structurally');
// ═════════════════════════════════════════════════════════════════════════════
{
  // (a) the prose reuses .art-md, which studio ALREADY owns — that is the whole reason
  //     six looks come out right without six hand-tunings.
  ok(/<div class="art-md">/.test(script),
     'Help renders its prose into `.art-md`, the artifact viewer\'s existing markdown style');
  for (const sel of ['.art-md h1,.art-md h2,.art-md h3', '.art-md code', '.art-md th,.art-md td']) {
    ok(css.indexOf(sel) >= 0, 'Editorial already styles ' + sel);
  }
  for (const sel of ['html[data-design="studio"] .art-md h2',
                     'html[data-design="studio"] .art-md p',
                     'html[data-design="studio"] .art-md code']) {
    ok(sd.indexOf(sel) >= 0, 'studio already overrides ' + sel);
  }
  // (b) NOTHING in Help's own block hardcodes a colour — every one is a token, so the
  //     four Editorial palettes and both studio variants reach it. This is the
  //     --on-wash lesson as a mechanical check.
  const helpBlock = css.slice(css.indexOf('/* ---------- HELP view'), css.indexOf('.art-code {'));
  ok(helpBlock.length > 400, 'the Help CSS block was found (' + helpBlock.length + ' chars)');
  const lits = helpBlock.replace(/\/\*[\s\S]*?\*\//g, '').match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g);
  ok(!lits, 'not one hardcoded colour in Help\'s CSS — every colour is a var(--token), '
     + 'so every palette and both studio variants reach it'
     + (lits ? ' (found: ' + lits.join(', ') + ')' : ''));
  ok(!/box-shadow/.test(helpBlock),
     '…and no box-shadow, so Editorial\'s one-glow fence and studio\'s dark-glow ban are '
     + 'both untouched');
  // (c) the type floor and the measure cap, the two Editorial-debt rules this view has
  //     to obey (test_editorial_debt.js owns them globally; these are Help\'s sites).
  const sizes = (helpBlock.match(/font(?:-size)?:\s*([\d.]+)px/g) || [])
    .map(s => parseFloat(s.replace(/[^\d.]/g, '')));
  ok(sizes.length > 0 && Math.min(...sizes) >= 10,
     'nothing in Help is under the 10px floor (smallest: ' + Math.min(...sizes) + 'px)');
  ok(/#help-doc \.art-md p, #help-doc \.art-md li, #help-doc \.art-md blockquote \{ max-width:66ch/.test(helpBlock),
     'the 66ch measure is on the PROSE — a cap on the container would have squeezed the '
     + 'three-column tables to fix a line length they do not have');
  ok(/#help-doc \.hlp-tw \{ overflow-x:auto/.test(helpBlock),
     '…and the tables get the other half of that deal: they scroll inside their column');
  // (d) studio's own delta is one rule, and it is scoped like every other rule in that file
  const sdHelp = (sd.match(/^html\[data-design="studio"\] #help[^{]*\{/gm) || []);
  ok(sdHelp.length >= 1, 'studio restates the contents rail in its own voice ('
     + sdHelp.length + ' rules)');
  ok(sdHelp.every(s => s.indexOf('html[data-design="studio"]') === 0),
     '…and every one of them is scoped, so with the attribute absent they cannot match');
}

console.log('');
console.log(fails ? fails + ' failure(s) of ' + checks : 'help view: ' + checks + ' checks passed');
process.exit(fails ? 1 : 0);
