# ONLYOFFICE AI plugin — recon for the LOffice one-editor world (2026-08-27, Fable)

**Question:** Debi saw the AI tab on ONLYOFFICE's site; our CryptPad bundle strips plugins
(verified — no plugins dir under dist/v9). Can we vendor their AI plugin and point it at
OUR runner, the Hermes/OpenCode provider pattern?

**Answer: yes, shape confirmed.**
- The plugin is ONLYOFFICE's own, distributed via their plugin marketplace repos
  (ONLYOFFICE/sdkjs-plugins ecosystem / onlyoffice.github.io). AGPL family — same
  conveyance posture as the editor bundle; vendor unmodified, pin + hash.
- **Custom providers are a tiny JS file**: `class Provider extends AI.Provider {
  constructor(){ super("MOT Deck (local)", "http://127.0.0.1:6767", KEY_OR_EMPTY, "v1"); } }`
  — name, base URL, key, and the "v1" addon (the OpenAI wire suffix). Their own examples
  (Tongyi, Kimi) are OpenAI-compatible chat-completions endpoints, i.e. exactly what
  llama.cpp serves on :6767/v1. We would REGISTER the provider programmatically/at
  config-gen rather than asking Debi to upload a file through their Settings UI.
- **Loading into the static editors**: DocsAPI `editorConfig.plugins.pluginsData`
  (list of plugin config.json URLs) + autostart — must be verified against OUR vendored
  api.js (CryptPad build) before the slice is scoped; if the static build strips plugin
  loading too, the honest fallback is our own AI panel only (which already exists and
  is deeper — approval-carded agent tools).
- **COEP constraint carries over**: the plugin's assets must be served same-origin with
  CORP, under /oo/ or a sibling route with the same three headers.

**Slice shape (v1.5.9-ish, after the consolidation lands):** vendor plugin (pin+hash,
installer extends install_onlyoffice.sh or sibling), serve same-origin, pluginsData in
the DocEditor config, provider JS pointing at :6767/v1 with the model name the runner
reports, verify in WKWebView, honest gating when the runner is down. Our AI panel stays —
the plugin covers in-ribbon rewrite/summarize; the panel owns agent tools + approvals.

Sources: onlyoffice.com blog "How to add a custom provider to the ONLYOFFICE AI plugin"
(2025-03), api.onlyoffice.com AI plugin docs, ONLYOFFICE/sdkjs-plugins.

---

## ✅ ANSWERED AND SHIPPED — 2026-08-28 (Opus 5, loffice-2026-08-29a)

**The blocking question ("does our vendored CryptPad build support plugin loading at all?")
is YES, and the AI tab is live in a real WKWebView, answering from our own runner.**

### The evidence for the gate
- `web-apps/apps/*/main/app.js` carries `pluginsData`, `getPlugins`, `asc_pluginsRegister`,
  `onPluginToolbarMenu` and `Common.UI.LayoutManager.addCustomControls` (the code that draws
  a plugin's own ribbon tab). `sdkjs/*/sdk-all-min.js` carries
  `pluginMethod_AddToolbarMenuItem` plus the three events this plugin declares
  (`onAIPluginSettings`, `onContextMenuShow`, `onToolbarMenuClick`).
- CryptPad's `api.js` is a WRAPPER: it deep-merges our config and hands it to the real
  `api-orig.js`, whose `_init` posts the WHOLE `editorConfig` into the editor iframe. So
  `editorConfig.plugins.pluginsData` is a live surface in our build. Nothing was patched.
- **`customization.plugins` was `false` in bridge/panel/oo.html for the entire life of the
  embed**, and the plugins controller reads it FIRST and skips loading entirely — so the
  recon's question would have looked like "not supported" from the outside.

### What was vendored, and what it cost
`scripts/install_oo_ai_plugin.sh` — ONLYOFFICE's own `ai.plugin` deploy archive
(`ONLYOFFICE/onlyoffice.github.io @ 799b287`, sha256 `5e98cc51…`, plugin 3.2.2, guid
`asc.{9DC93CDB-…}`) plus the three shared SDK files, UNMODIFIED, into
`data/onlyoffice-plugins/` and served at `/ooplug/*` with the same three isolation headers.
8.7 MB, 666 files.

**The deploy archive is what makes UNMODIFIED possible.** The repository's working copy of
`content/ai/index.html` loads the SDK from `https://onlyoffice.github.io/…` — absolute,
which a COEP page cannot load and an offline Mac cannot reach. The deploy archive uses
`./../v1/plugins.js`. The installer now FAILS LOUDLY if a future pin regresses that.

### Four upstream traps, all of which fail SILENTLY (each is now a pinned test)
1. **The layout.** `./../v1/` resolves ONE level above the plugin folder, so it must be
   unzipped to `<dest>/ai/` NEXT TO `<dest>/v1/` — not `content/ai/` mirroring the repo.
   Wrong layout ⇒ `window.Asc.plugin` undefined inside the plugin frame, no AI tab, and no
   error anywhere the host can see.
2. **A merge race.** `mergePlugins` no-ops while either list is `undefined`, and the
   `plugins.json` error branch never calls it again — so `editorConfig.plugins` ALONE loses
   a coin flip. Fixed by ANSWERING the bundle's own `plugins.json` request from the route
   (generated, nothing written into the vendored tree).
3. **An upstream crash.** `onResetPlugins` creates the ribbon's "Background plugins" button
   only while walking a NON-background plugin, then calls `.show()` on it whenever any
   background plugin exists — and the AI plugin IS one. A list holding only it throws
   mid-registration, and the throw is swallowed by upstream's own `.catch`. Fixed by adding
   ONE generated, invisible companion entry (`EditorsSupport: []`).
4. **`Asc.plugin.info.aiPluginSettings` is a dead end**: sdkjs only fills it from a
   DocumentServer licence message and then forces `data.proxy = …/ai-proxy`. Registration
   goes through the plugin's OWN localStorage keys instead (same origin, same keys its
   Settings dialog writes), seeded by the glue page before the editor starts.

### Live proof
AI tab in the ribbon (Settings · Chatbot · Summarization · Translation) on a spreadsheet, a
document and a presentation; a Chatbot prompt round-tripped through `127.0.0.1:6767` — the
runner log shows an 11,268-token prompt eval and 52 generated tokens — and the answer
("LOCAL RUNNER OK") rendered in the chat window. Plugin removed ⇒ the editor opens exactly
as before, no Plugins tab, no AI tab, `probe().ai.gate` says why. Nothing leaves the Mac.

⚠️ **Honest limit:** the plugin's own capability list is bound to Chat, Summarization,
Translation and Text analysis only. Image generation, OCR and vision are deliberately left
UNBOUND — a local text model cannot do them, and a bound-but-broken action would be worse
than a visibly empty one.

---

## ✅ ROUND TWO — 2026-08-28 (Opus 5, v1.5.28): latency, chat persistence, the modal

Three things Debi observed while USING the AI tab, all three root-caused by measurement.

### A. Prompt caching — there was nothing to fix, and that is the finding
`cache_prompt` is **on by default** in llama.cpp b10662. Measured against the live
runner, 29,624-token sheet prefix, three consecutive asks, oracle = the runner's own
`prompt eval time = X ms / N tokens` line:

| body | ask 1 | ask 2 | ask 3 |
|---|---|---|---|
| `cache_prompt` **omitted** (what the plugin sends) | 116.1s / 29,624 tok | 3.71s / **516** | 3.80s / **517** |
| `cache_prompt: true` | 3.68s / 515 | 3.71s / 515 | 3.69s / 516 |
| `cache_prompt: false` (control) | 115.0s / 29,624 | 116.6s / 29,624 | 122.7s / 29,625 |

OMITTED ≡ TRUE. So the bridge proxy that would have injected the flag into the plugin's
body was **not built** — it would have been a no-op wearing a proxy, plus a second place
for the runner URL and key to drift. (There is no data-only hook: the plugin's base
`Provider.getChatCompletions` returns `{model, messages}` and `getRequestBodyOptions()`
returns `{}`; `AI.createProviderInstance` drops to the BASE class for a custom provider,
so a seeded provider cannot override a method.) The Quick lane keeps sending it
explicitly — `false` is a real setting and a default flip must not cost it two minutes.

**Cross-lane eviction does not happen either.** `--cache-ram -1` (llama.cpp PR 16391,
host-memory prompt cache, unbounded) keeps several conversations' KV state resident:
A(cached 505 tok) → B(full 22,950 tok prefill, 84.8s) → A again = **506 tok / 18.4s**,
then 3.8s. Another lane's turn costs the sheet a KV restore, not a re-read. **The runner
argv was not changed.**

Real in-ribbon ask, measured end to end: 11,270-token prompt eval in 35.7s → the first
ask on a sheet IS the physics, and the repeat is seconds.

### C. The modal is the EDITOR's block, and its length is the first-token wait
It is not a plugin loader and there is no settings knob. The plugin calls
`Asc.Editor.callMethod("StartAction", ["Block", "AI (model)"])`:
- **Chatbot panel** (`register.js:186`) — `chatRequestAgent(data, /*block*/ false, streamFunc)`
  and `checkEndAction()` fires on the FIRST streamed chunk. The modal lasts **TTFT**,
  then the answer streams into the docked panel.
- **Ribbon actions** (Summarization, Translation, …, `register.js:455-635`) —
  `chatRequest(prompt)` with block defaulting true and NO streamFunc, so the modal holds
  for the **whole generation**.

Shipped: the honest lines in LOffice Help → About (numbers, and "for anything long, ask
in the Chatbot"). Nothing vendored was patched.

### B. The chat vanished on a file switch — FIFTH upstream trap, and it is deliberate
```
ai/scripts/code.js
    function clearChatState() { localStorage.removeItem('onlyoffice_ai_chat_state'); }
    window.Asc.plugin.init = async function() { … clearChatState(); … }
```
The plugin **deletes its own conversation on every start**. It also only ever SAVES from
`onUpdateState`, which only `onDockedChanged` commands (`register.js:395`) — so nothing
is written unless the user happens to dock/undock. In our one-editor world every swap
re-inits the plugin, so both halves fire on every file switch.

Fixed in `bridge/panel/oo.html` with the plugin's OWN published surfaces, no vendored
byte touched: command `onUpdateState` before `destroyEditor()`, move the blob to a
per-file key of ours (`mot.ooai.chat.<file>`, LRU 12, 512 KB cap, quota-safe), plant the
incoming file's blob before construction and **HOLD** it there (the plugin's init wipes
it) until the Chatbot opens. Version-fenced on plugin 3.2.2 in `test_oo_ai_lane.py`.

Two defects of our own, both found by walking the journey live and both pinned:
1. **A null flush deleted a saved conversation.** "I could not read the chat" was being
   treated as "there is no chat". LIE-TO-USER class. Nothing is deleted on an empty read.
2. **A tick-count timeout is not a timeout.** The flush polled "14 × 50ms = 700ms";
   WebKit clamps timers in an off-screen window and those ticks took **over 30 seconds**,
   hanging the whole document swap at "converted to the editor format". Bounded by the
   CLOCK now. General lesson: timers promise ORDER, not DURATION.

Live proof (WKWebView, real editor swaps): type in the Chatbot on A → swap to B →
**B's panel is clean** (no bleed) → swap back → **the conversation is back**; a rename
carries it; `drops: 0`.
