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

> **🏷️ MOT REBRAND + LOFFICE GROUNDING + ONLYOFFICE PROBE KIT + BUZZ/GOOSE RECON
> (2026-08-21 later, Fable orchestrating 4 Opus agents under a DEAD VM — no bash all
> turn, file-tools-only builders, Debi's ship gate = the validator):** Debi CONFIRMED
> OpenCode working (models in picker — the disabled_providers repair validated live;
> pending-task closed). **(1) MOT REBRAND (visible surfaces only, Fable fence):** app
> = **MOT Deck**, Mission Control → **MOT Main** (sidebar/tab/hero/⌘K/tooltips/error
> strings), wordmark MOT + "mixture of tools / local · control", window title +
> Quit menu + first-run alerts, OpenCode provider name → "MOT Deck (local)",
> office/aider titles, docs H1s + naming notes (HARNESS-INTERNALS/architecture get a
> top note, not a rewrite). INTERNALS UNCHANGED by ruling (harness.yaml, HARNESS_*,
> localStorage keys, paths, bundle id, /Applications/Harness.app) — full internal
> rename = queued ops slice. 2 test pins updated by inspection; "the harness" as a
> common noun deliberately left (~25 sites); app.py:1075 session name "Mission
> Control" KEPT (renaming would orphan the chat session); CFBundleName → MOT Deck
> takes effect only on a full build_app.sh. ✋ GitHub repo rename = Debi's click.
> **(2) LOFFICE ROUND 3 (stamp 21i):** the CLEAN-function bug root-caused — sticky
> global ai-ctx-off + zero grounding → new aiPreamble() ALWAYS prepended (names
> LOffice/.xlsx/open sheet; "function = SPREADSHEET function, Excel semantics");
> SHEET chip on-by-default per file (persisted pref deliberately dropped — it pinned
> the bug; old test assertion was pinning the bug too, rewritten). File ⌄ menu (New/
> Open ⌘O/Import/Rename/Save ⌘S/Download/Close/⌂ MOT Main), POST /api/office/rename
> (containment discipline). Theme coherence: page reads panel's harness-theme +
> harness-chrome from localStorage (same origin), 9 rules, palette rules = the ONE
> deliberate non-:where() exception (a :where() prefix would lose to :root). Fixed a
> LATENT DATA-LOSS bug: double-click on a dirty row armed AND confirmed the discard
> in one gesture (DISCARD_MIN_MS=400). Fable added the Swift branch: loffice+aider
> webviews get the "harness" script-message handler (first-party bridge-served pages
> — third-party components still never). ⚠️ ONE-TIME REPAIR: a NUL byte got into
> office.html (3 string literals, neutralised behind // comments, page syntactically
> valid; Grep refuses the file until stripped):
> `LC_ALL=C tr -d '\000' < bridge/panel/office.html > /tmp/o && mv /tmp/o bridge/panel/office.html`
> **(3) ONLYOFFICE PROBE KIT BUILT** (Debi GO): scripts/probe_onlyoffice.sh (⚠️
> arrives 644 — chmod +x FIRST or the hygiene fence blocks the gate, as designed) +
> docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md. Track A fernfei/OnlyofficePersonal =
> Safari go/no-go (⚠️ unverified provenance, measurement vehicle only); Track B
> CryptPad onlyoffice-editor.zip v9.2.0.119+3 + x2t.zip v7.3+1 (hash-verified at run
> time against CryptPad's own install-onlyoffice.sh; ⚠️ pin unresolved between two
> readings — script records what it downloads, env overrides exist). Ships its own
> serve.py (wasm MIME + no-store + threading — three false-fail sources). Sheets-only
> answer to Debi: v1 was Sheets by design; Docs+Slides ride the probe (the bundle
> carries all three editors + PDF) — pass = full office in one adoption.
> **(4) BUZZ/GOOSE RECON (WebSearch-only, VM dead; docs/research/2026-08-21-buzz-
> goose-recon.md):** block/buzz = REAL but a Nostr hive-mind team workspace needing
> Postgres+Redis+S3 via Docker Compose → REJECT as component, WATCH (hosted Buzz is
> just a URL; Hermes→Buzz wiring exists); chidiwilliams/buzz = native Qt Whisper GUI
> → reject (voice lane covers it). GOOSE UN-REJECTED: moved to the Agentic AI
> Foundation (aaif-goose/goose, Apache-2.0, v1.46.0, prebuilt darwin-arm64 = the
> OpenCode installer shape); tool-calling REQUIRED (no text fallback) = fine now via
> the tools pill + start-plan warning; NO browser UI (goosed = client API; :7681 =
> ttyd red herring) → shape = PTY lane over a generalized pty_aider.py. 9-item
> source-verify checklist queued for when the VM returns. Old "Docker-ish" strike
> was likely an over-read (Docker Model Runner = optional provider).
> Roadmap updated + grep-verified. NOTHING EXECUTED this turn (no bash anywhere) —
> ship gate + Debi's smoke tests are the validation. Restart the session for a
> clean VM before the next heavy round.
