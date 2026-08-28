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
