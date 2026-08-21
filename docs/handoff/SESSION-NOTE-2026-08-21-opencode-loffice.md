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

> **🧯 REGRESSION REPAIR + LOFFICE BECOMES AN OFFICE APP (2026-08-21 latest, Opus-5
> builder ×4 in parallel, VM STILL DEAD — file-tools only, nothing executed;
> ⚠️ ALL OF THIS IS PENDING FABLE QA. THE GOOGLE REFERENCE SCREENSHOTS DEBI SENT
> (Sheets home + Sheets File/Edit/View/Insert/Format/Data menus, Docs Insert/Format/
> Tools/Gemini menus, Slides Edit/View/Insert) ARE IN THE CHAT TRANSCRIPT AND ARE
> TRANSCRIBED ITEM-BY-ITEM IN `docs/research/2026-08-21-office-ui-reference.md` —
> Fable must read that doc; Debi called seeing them "paramount".**
> **(1) THE REGRESSION WAS MINE (Fable's own Swift edit last turn): two comment lines
> written with a SINGLE `/` instead of `//`** → `swiftc` failed → ship.sh copied panel
> +bridge and moved on → the shell binary stayed OLDER than the panel (topbar still
> read "Mission Control" while the sidebar read "MOT Main"). Every symptom Debi
> reported follows from that skew. **STANDING LESSON, third strike class: Grep's
> `-A/-B` CONTEXT LINES CAN DROP A LEADING CHARACTER** (a healthy `//` renders as `/`)
> — never diagnose or copy comment syntax from context output; Read to confirm. A
> whole-file scan for `^\s*/[^/*]` is now the cheap gate for main.swift.
> **(2) LANE ROW → CHROME, root-caused:** `navOpen` did
> `if (e.prefersTab && e.tab && switchTab(...)) return;` then `window.open(e.url)`;
> `switchTab` returns false when the handler is absent (an old shell), and
> `window.open` in a WKWebView lands in `createWebViewWith` → `NSWorkspace.open` →
> the DEFAULT BROWSER. Aider/LOffice are `view:null` lanes so nothing else caught it.
> FIX: new `inNativeApp()` (webkit present, deliberately weaker than `nativeShell()`)
> + `shellTabs()`/`shellKnowsTab()` reading a NEW shell→page capability record
> `window.harnessShell = {api:2, tabs:[...every registry id...]}` injected at
> documentStart on the panel + loffice + aider only. Inside the app a lane can NEVER
> reach `window.open` — it prints `this build of the app has no such tab — run
> ./scripts/ship.sh`. **A one-way postMessage was previously silent on failure; it
> now has a diagnosable answer.** Also fenced: `ensureLoaded`'s `wvById[id] ?? panelWV`
> could have loaded `/office` INTO THE PANEL'S WEBVIEW (destroying Mission Control and
> showing the panel in the asking tab — exactly Debi's symptom 2); now a `guard` that
> logs `BUG:` and refuses. `/office` + `/aider` routes verified registered OUTSIDE the
> defensive office try/except and unshadowed; office.py audited importable by reading.
> **(3) LOFFICE MENU BAR — the Google-literal rebuild** (Debi: "did you even care to do
> research… everything is in the white strip and uniform"): row 1 = dark app chrome
> (mark · click-to-rename title · dirty dot · Rich/Import/New/Save), **row 2 = a WHITE
> `<nav id="menubar">` flush with the sheet in BOTH themes: File · Edit · View ·
> Insert · Format · Data · AI · Help, 63 rows**, uniform metrics, left tick gutter,
> right-aligned mono shortcut column, hairline groups, click-then-hover switching,
> ←→↑↓/Esc, **41 rows WIRED · 22 DISABLED WITH THE REASON IN THEIR OWN title** (Google's
> grey-not-hide grammar; no dead item may look live). New capability: a real **Find**
> bar (scans cellData, grows the render window, cap 500). Format's bold/italic/
> underline/strike/align/wrap were chosen because `office.py::apply_style` provably
> round-trips exactly `bl it ul st ff fs cl bg ht vt tb n`. **⌂ home NO LONGER LEAVES
> LOFFICE** (Debi's exact complaint): `mi-start` shows LOffice's own **START SCREEN**
> (Sheets-home shaped: "Start a new spreadsheet" Blank + 2 client-generated templates,
> then the recent list with Enter/↑/↓/download/two-step delete), and a separate
> `Back to MOT Main ↗` at the File menu's bottom keeps the switchTab. `autoOpen` no
> longer auto-creates Untitled on an empty library — it lands on the start screen.
> CSS: +47 rules in ONE contiguous block, −6 (`#filemenu` row rules) = net +41.
> **(4) THE AI PANEL CAN NOW WRITE THE SHEET** (Debi: "not possible to do tool
> functions… maybe even Hermes-like abilities"). **Mechanism ruling: NOT
> OpenAI function-calling** — most of her local models can't tool-call and the direct
> lane sends no `tools`, so it would work on some models and silently no-op on the
> rest. Instead a **taught ACTION BLOCK**: ```loffice {v:1, file?, sheet?, ops:[set|
> style|sheet|resize]}``` → pure total `parseActions` (caps 60 ops / 2000 cells /
> GR5000 bounds; `set` REFUSES when over cap, `resize` CLAMPS — asymmetric on purpose)
> → **a PREVIEW card (summary + exact `A1 → value` list, capped) with Apply/Dismiss;
> nothing is written until the click** → Apply writes through the grid's OWN
> putCell/parseInput/renderGrid/dirty path (no second writer) → **Undo restores a
> pre-write full clone** (reversing ops has to guess what a cell held; a shared style
> id or a merge makes that guess wrong invisibly). Never auto-saves — the user saves.
> No-workbook case = `create()` then apply ("Create & apply"). Tier-2 (Univer mounted)
> REFUSES with an honest message. **The old "this panel can never write" assertions
> were deliberately rewritten** and replaced by something stronger: a fence computed
> over every function in the page asserting the complete writer set is exactly
> `[actRunOps, clearCell, commit, newFromTemplate, styleWrite]` (self-tested — an
> injected writer trips it). `actRunOps` is EXECUTED in-test against bare snapshots
> incl. the shared-style-id trap and byte-for-byte undo. Hermes hand-off = a LATER
> slice, deliberately not started (Hermes has the real tools + approval cards +
> path-guard). **Stamp loffice-2026-08-21k** (page ×2 + both test files agree).
> **(5) OPENCODE "degraded while green" — DIAGNOSED, and the expensive-endpoint
> hypothesis is REFUTED.** The card and the feed read the SAME `c.degraded` in the same
> loop iteration — they cannot disagree at an instant; the difference is LIFETIME (the
> card is rebuilt every poll, the feed line is permanent scrollback with no retraction).
> `degraded` was instantaneous: `expected-up AND not running`, and `running` is a 0.5s
> TCP handshake OR pid-alive — it never touches `/provider`. Two healthy windows
> produce it for one poll: **a CLI `--restart` (which Debi ran: `_clear_port` → sleep →
> new pid, while `.expected` is only written by the PANEL's Start)** and event-loop
> congestion. FIXES: per-component probe budget (`{opencode: 2.0}`, default 0.5,
> spent only when expected-up so a stopped component can't slow every poll), a pure
> `health_verdict` → `ok|transient|lost` with **3 consecutive misses** (mirrors the
> panel's own BRIDGE-UNREACHABLE rule), ONE derivation `healthOf(c)` feeding feed+card
> +dot, and the line that makes a stale alarm impossible: **`back online`**. Card reads
> `Reconnecting…` during a restart. **Deliberately NOT switched to `/global/health`:
> a TCP handshake is completed by the KERNEL from the listen backlog, an HTTP GET needs
> the server's event loop — the "cheaper" endpoint would be MORE likely to false-fail.**
> The six log blocks are six STARTS appended to one log (`>>`, never truncated) — no
> leak, ownership-checked port clearing, no `opencode` name signature so a stranger on
> :4096 is never killed; the start log now says so, and annotates the vendored
> `OPENCODE_SERVER_PASSWORD` warning as expected-on-loopback (setting one would gate
> the SPA our own tab loads — Add-server asks for it BY HAND, nothing would supply it).
> ⚠️ QUEUED: probe components concurrently (`asyncio.gather`) — worst-case /api/status
> latency now +1.5s while opencode is expected-up-and-missing.
> **(6) DEBI'S OPEN QUESTION, answered honestly: LOffice is Sheets-only today.**
> Docs + Slides ride the ONLYOFFICE probe (its bundle carries all three editors + PDF);
> the menu bar and start screen were built so a document-type row slots in.
