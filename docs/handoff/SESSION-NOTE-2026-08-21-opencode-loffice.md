# SESSION NOTE 2026-08-21 (Fable 5) — merge into CLAUDE.md next session
(The sandbox VM died of a full disk at session end — this note substitutes for the
usual CLAUDE.md blockquote. Next session: append this to all three CLAUDE.md copies.)

> **🏁 OPENCODE SOLVED BY RUNNING THE REAL BINARY + LOFFICE ERGONOMICS + OFFICE DEEP
> RESEARCH (2026-08-21, Fable QA over 3 Opus agents; ⚠️ opencode fix UNVALIDATED
> in-sandbox — VM died; Debi's step-1 command + the ship gate are the validation):**
> **(1) OPENCODE ROOT CAUSE — observed, not theorized:** npm publishes
> `opencode-linux-arm64` — the agent RAN 1.18.19 in the sandbox with our exact
> seeding. Our seeding is CORRECT (provider connected, models listed, MLX key/wire
> split works, project-config path works, `@ai-sdk/openai-compatible` is BUNDLED so
> no runtime npm install — offline worry closed). **Debi's failure = TWO things:**
> (a) her one early "Disconnect" click wrote `disabled_providers:["llama.cpp"]` via
> their PATCH /global/config, our merge preserved it forever, and upstream DELETES a
> disabled provider before the models loop (provider.ts:1644) → "No connected
> providers" + empty picker; (b) we wrote dangling `model:` defaults when
> runner.model wasn't a registry id — defaultModel() is unvalidated (:1980) and the
> client fallback priority list contains "big-pickle" (:2017) — THAT is where Big
> Pickle came from. **FIX in start_component.sh opencode branch:** strip our id from
> disabled_providers (+ add to non-empty enabled_providers), print `REPAIRED:` lines,
> never write a default that isn't in our own models map (else deterministic first
> model, else unset), self-check timeout 8→25s (measured: /provider = 193 providers,
> 5.2MB). Settings→Providers and the composer picker read the SAME /provider payload
> (all ∩ connected) — a config provider IS expected to appear tagged "config", so her
> screenshot was a real fault. Model picks are client-storage, survive restarts.
> Their pages CAN be iframed (no frame-ancestors/XFO, verified live) — the
> harness-strip fallback is feasible but cross-origin-blind; parked.
> **(2) LOFFICE ERGONOMICS (stamp 21h, browser-verified 27/27):** draggable dividers
> (rail 160-420, AI 260-560, persisted-on-release, dblclick reset, pointer capture,
> mirrored-axis bug pinned), both panes collapse to 34px labelled reopeners
> (railSetOpen single writer), header unified to one 28px control token (the 26/22/16
> mix WAS the "feels off"), ⌘\ toggles rail, Esc clears messages, real hit targets on
> row actions. test_office_grid 205→247; sweep was green when that agent ran.
> **(3) OFFICE DEEP RESEARCH (docs/research/2026-08-21-office-alternatives-deep.md):**
> HEADLINE — the first recon tested the wrong ONLYOFFICE artifact: DocumentServer
> (Linux server) is dead, but **ONLYOFFICE's EDITORS are 100% client-side static
> files** (x2t.wasm + sdkjs/web-apps served over plain HTTP — CryptPad has shipped
> exactly this since 2021; 4 independent backend-free bundles exist). Only option
> with docx+xlsx+pptx+PDF and the real recognizable ribbon, and it REDUCES owned
> surface. Gates: AGPL served from our page (closer coupling than SearXNG — Fable
> preliminary: acceptable for personal use, same conveyance rules) + several hundred
> MB assets. Also: Univer's import/export ceiling is PROPRIETARY (validates our
> tier-1 but caps tier-2 permanently); CryptPad itself = encrypted blobs, files
> invisible to the harness → reject-as-component, harvest its asset pipeline; Grist =
> Airtable not a spreadsheet (xlsx import discards formulas); Document Builder
> WATERMARKS without license; Collabora structurally mac-impossible; EtherCalc now
> Bun/CF-workers (worse); Quadratic went closed 2026-03. **FABLE RULING: the
> 30-minute measurement decides (music pattern)** — unzip the prebuilt bundle, serve
> statically, open in a REAL WKWebView, round-trip a real .xlsx; pass → adopt as
> LOffice tier-2 REPLACING the Univer lazy-loader (tier-1 grid stays as instant boot;
> x2t.wasm becomes the converter for both); fail → x2t.wasm converter-only. Either
> way ship "Open in ONLYOFFICE" (brew cask, detect-never-install) as the fidelity
> escape hatch. Queue the probe as the next office slice.
> **(4) OPS:** the sandbox VM wedged on a full disk mid-wave (opencode binary runs +
> a blobless clone) — the ship gate (verify.sh) did its job as the safety net: Debi
> validates on-Mac before shipping. LOffice "are we writing an app from scratch?"
> answered honestly: partially yes (SDK-embed vs complete-app was the recon's
> tradeoff under no-Docker/macOS constraints — now re-examined by the deep research).
