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
