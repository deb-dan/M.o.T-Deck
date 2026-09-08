# MOT Deck — working memory (canonical project home)

> **📍 CURRENT STATE (2026-09-08, v1.5.91 shipped; v1.5.92 prepared) — supersedes the "2026-08-28, v1.5.12" banner
> below for anything about what's shipped.** Full reader-facing status (done / in
> progress / next, by theme) now lives in `docs/ROADMAP.md`; the deferred-work ledger is
> `docs/UNFORGET.md` (unchanged pointer, see below). Since v1.5.12: the component
> isolation ladder landed for Odysseus/Hermes/goose (CLI+UI)/OpenCode; registry truth +
> rescan (S29); the post-switch coherence wave (S28); local API keys + a sidebar API page
> (S32); Generate/Compose rebuilt (Patchbay/Spectrum); goose session continuity + a
> per-chat delete; the process-group detachment fix so components survive an app quit
> (U52); ⌥⌘Q "Quit Everything" alongside plain ⌘Q (U55); the M.O.T app icon; a runner
> pidfile fix (U54) and a stale-Failed-card fix (U60). v1.5.74 closed U56 and U64;
> v1.5.75 added DeepSeek and v1.5.76 recorded the live-state clobber incident. v1.5.77
> closes the recovery wave: U74/U69 recovery hardening, U78 bundle-identity shipping,
> U77 router extraction, U79's truthful Aider parser probe, U80 audio deduplication,
> and U81 canonical-root severance all passed the repository gates and the real-stack
> ship journey. v1.5.78 closes U75: one structured GGUF/MLX artifact probe now governs
> discovery, catalogs, health, launch/switch preflight, and every first-party load
> action, so zero-byte, partial-shard, malformed-manifest, and config-only artifacts
> remain visible with a specific diagnosis but cannot be offered as fresh targets.
> v1.5.79 closes the narrower physical-source-availability part of U76. v1.5.80 is the
> corrective reliability wave: source-specific model membership (without a second
> registry), semantic GGUF/safetensors/MLX structure checks, row-bound Rescan consent,
> crash-recoverable app-owned deletion, launch-provenance process ownership, atomic
> state writes, origin fencing, durable Chat/Agent turns across lane changes and reloads,
> truthful LOffice history, live OpenCode/model binding, conflict-safe LOffice naming,
> and transactional Hermes WhatsApp disable all passed the full gates and real-stack
> journeys. Existing UI intent was explicitly preserved: the sessions divider, pointer
> affordances, controls, labels, navigation and design/theme surfaces were not removed.
> v1.5.81 adds bridge-owned Hermes turns across lane changes/reload/bridge restart;
> protected local secrets; general installed-app discovery; one durable registry writer;
> collision-free OpenCode keys; suite-level pytest collection of legacy standalone tests;
> explicit legacy-process migration; a measured no-change decision for prompt-cache slots;
> and the real Goose minted-key journey. v1.5.82 closes U145: the native Odysseus tab
> enters through a server-side managed-cookie handoff, so the rotated password stays out
> of browser JavaScript/logs while the unmodified upstream workspace opens authenticated.
> v1.5.83 closes the local hardening/honesty wave: dependency actions deep-link to their
> real remedy; remaining installer sources and payloads are revision/digest pinned; the
> repository Python and complete JavaScript fences block shipping; every managed
> single-model consumer reports requested-versus-served drift; and live-theme repairs
> preserve the original hover/drag affordances. v1.5.84 completes the product identity
> migration to MOT Deck, with the exhaustive old→new inventory in
> `docs/U150-IDENTITY-CHANGE-INVENTORY.md`. v1.5.85 closes the local usability and
> seed-ownership wave: LOffice catalogue-bound sessions, native JavaScript dialogs,
> typed Agent/Hermes attachments, lane-specific capabilities, Help/copy cleanup,
> generated Office schemas/pagination, systematic partial-install QA, and manifest-bound,
> test-free FAT runtime seeds. U149, U150 and U152 are the corresponding release closure
> rows in `docs/UNFORGET.md`.
> v1.5.86 closes the local truth/lifecycle/media-compatibility wave plus scoped layout
> reset. v1.5.87 advances OpenCode, Odysseus, SearXNG, VoiceStudio, ComfyUI and llama.cpp
> only after isolated review and real installed journeys; Voicebox's Git and lazy MLX
> runtime graph is exact, while Unsloth and acestep.cpp are evidence-based holds. U157
> and `docs/FABLE-v1.5.87-UPSTREAM-UPDATE-WAVE.md` carry the exact acceptance/rejection
> record. Protected live secrets, model registry and navigation were conserved.
> v1.5.88 closes the media-relocation, selector-truth and real-fit wave: ACE-Step's
> retired-root rpath is repaired transactionally, Generate's Model/Type transaction is
> coherent, model Eject restores exact state, real MLA/SWA/MLX/projector receipts
> calibrate advisory fit truth, and hosted Comfy nodes are refused by authoritative
> engine metadata without adding cloud execution. U165 also makes the native app
> bundle derive its Finder/Get Info version from the same top-level `VERSION` truth.
> U159–U165 and
> `docs/FABLE-v1.5.88-MEDIA-RELOCATION-FIT-WAVE.md` carry the full evidence.
> v1.5.89–v1.5.90 added the existing ownership-safe removal/reset and optional setup
> surfaces. v1.5.91 shipped solo reliability corrections for Direct streams, download
> writer lifetime, storage receipts/recovery and model settings. v1.5.92 prepares two
> session-integrity corrections; see `docs/RELEASE-v1.5.92-RELIABILITY.md`. U170 stays
> open for the requested exhaustive review; no pending feature was implemented.
> Exact-once Direct-history writes remain U139;
> shell execution confinement remains U72; non-LM-Studio source adapters remain conditional
> on an inventory plus launch contract (U91); auxiliary-key rotation remains U142; and
> Goose's upstream provider deletion may leave an inert config stanza (U144). Read
> `docs/ROADMAP.md` for the full picture before treating the older banners below as current.

> **🗄️ ARCHIVE:** session notes older than the current wave live in `docs/handoff/archive/CLAUDE-ARCHIVE-2026-07--08.md` (full, verbatim). This file carries only standing doctrine + the current wave — keep it that way: when a wave closes, move its notes to the archive.

> **⚖️ ADVISORY-GATES RULING (Debi, 2026-08-28): RAM/resource gates WARN AND RECOMMEND,
> never hard-block.** A projected-doesn't-fit launch shows the measured numbers ("needs
> ~XGB peak · you have ~YGB free · expect heavy swapping"), a clear recommendation, and
> an explicit proceed-anyway consent. Applies to the spawn_guard/ledger gates on EVERY
> heavy lane (music, voice workers, the coming Voice Chat) — retrofit queued. Gate
> figures are MEASURED process peaks, surfaced as information, not enforced as walls.
> Voice Chat (M3) is ADDITIVE: no existing sound path (talk/auto/conv/TTS/VoiceStudio/
> Voicebox) is replaced or altered by it.

> **🎨 ALL-DESIGNS RULE (Debi, 2026-08-28): every UI change to a first-party surface must be
> verified under EVERY design/theme it can render in — Editorial, the theme packs, and Studio
> (light + dark) — before it ships. New UI carries tokens reachable by all of them (the
> --on-wash lesson); a change verified in one look only is NOT verified. Builders state
> per-design verification in their reports; the studio/theme fences are the mechanical floor.**

> **📍 CURRENT STATE (2026-08-28, v1.5.12 — read this first):** LOffice is a ONE-EDITOR app:
> ONLYOFFICE (vendored CryptPad static bundle, AGPL ruling GO, COOP/COEP served by bridge/oo.py)
> embedded as the center of /office with our rail/strip/AI panel around it; tier-1 grid =
> interstitial + not-installed fallback only (Univer retired — assets kept as rollback, its old
> known-issues moot). Agent lane = changeset consent (office_stage_changes stages, ONE panel card,
> human-only atomic apply + receipt + .checkpoints undo; zero Hermes approval cards by design —
> see docs/FABLE-AGENT-CHANGESET-SPEC.md). Numeric typing is intent-aware (model-first, contextual
> inference, hard guards; never asks the user). The adversarial campaign fixed 56+3 catalogued
> findings; test_office_journey.py (golden journeys) + test_office_adversarial.py (ledger, not a
> gate) are the standing QA pattern. v1.5.11 updated 8 components/engines (llama.cpp b10662 —
> its /v1/models now needs auth, probe fixed + contract-pinned; Odysseus rsync MUST exclude
> /data/ + /.env or it deletes the live DB). Hermes v0.20.x bump in flight as its own sitting.
> **bridge/app.py IS NO LONGER A MONOLITH (v1.5.15):** its 10,072 lines are now
> bridge/core/*.py + bridge/routers/*.py (29 files, largest 1,206) and app.py is a
> ~280-line FACADE — a module-class proxy so `bridge.app` still answers for every
> symbol the suite imports AND still propagates the monkeypatches (`A.ROOT`,
> `A._script`, …) into the modules that read them. The ~40 test files that assert
> against app.py's SOURCE TEXT read bridge/appsrc.py's ordered view of the whole
> layer instead; adding a lane means adding it to appsrc.FILES (a contract test
> fences that, because a lane missing from the view makes every `not in` assertion
> pass vacuously). ship.sh copies bridge/{core,routers}/ — the flat `bridge/*.py`
> glob would have shipped a facade with nothing behind it. Read
> docs/handoff/APP-FACADE-MANIFEST.md before touching this area.
> **LOFFICE IS THREE FILE TYPES + AN IN-RIBBON AI TAB + PDF EXPORT (loffice-2026-08-29a,
> the three queued items all landed):** (1) ONLYOFFICE's OWN AI plugin is vendored
> UNMODIFIED (`scripts/install_oo_ai_plugin.sh`, pinned by commit+sha256) and pointed at
> our runner through the plugin's own localStorage keys — AI tab live in the ribbon of all
> three editors, round-trip proven against :6767; gated OFF with a sentence when the plugin
> or the runner is absent. FOUR upstream traps, all silent, documented in bridge/ooai.py
> (layout `ai/` next to `v1/`, a mergePlugins race answered by a GENERATED
> `/oo/dist/v9/plugins.json`, an `onResetPlugins` crash worked around with one invisible
> companion entry, and `aiPluginSettings` being a dead end). (2) DOWNLOAD AS PDF replaces
> Print: `asc_nativeGetPDF` → x2t with `m_nFormatFrom` = CANVAS_{SPREADSHEET 8194 | WORD
> 8193 | PRESENTATION 8195}, `m_nFormatTo` 513, the bundle's 91 fonts mounted first, and
> ⚠️ `m_bIsNoBase64` **true** — with false x2t returns rc 0 and a VALID PDF WITH `/Count 0`.
> It is the LIVE editor state (proven with a never-saved marker), downloaded via an
> `<a download>` blob (a navigation would not: WebKit CAN show application/pdf). (3) .docx
> and .pptx are OPAQUE BLOBS to the bridge — the store handles all three, the CONTENT path
> (snapshot, grid, sort, stats, office_read/stage_changes) is .xlsx only and refuses the
> other two by name with `office.require_sheet()`. Blank packages are BUILT in
> bridge/officeblank.py from the OOXML rules (never vendored, deterministic, sha-pinned).
> New suites: test_oo_ai_lane.py (152) + test_office_types.py (168); journeys in
> test_office_journey.py (288).
> Queued: tier-1 deletion after soak. Debi's clicks: PAT revoke; probe dir (3.2GB) + update .baks deletable.

> **📒 DEFERRED WORK LEDGER (unforget) — Ledger home: `docs/UNFORGET.md`.** ALL deferred
> work lives there and ONLY there: paused plans, mid-task spillover, audit findings that
> aren't fixed on the spot, observed quirks, and every WORKAROUND/BRIDGE around an
> upstream defect (Debi's ruling 2026-08-29, after the Odysseus vision bridge). When a
> slice ships a workaround, add a U-row naming the root cause, the retirement plan, and a
> verify-still-open recipe; when closing a row, use the closure pointer + spawn links.
> "What's deferred / what's the backlog?" = read that file. Don't scatter deferral into
> this file's queued lines anymore — new queued shapes from builder reports go into the
> ledger at QA time.


> **🏠 CANONICAL-ROOT RULE (Debi, updated 2026-09-07, U81/U150):** the sole source project is
> `/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck`.
> The older `/Users/debik/Claude Proj Rootz/New Harness/harness` tree is a retained,
> read-only archive: never edit/delete it, copy state or dependencies from it, execute
> against it, or allow a generated link/config/process to depend on it. The installed
> fat app runs from `~/Library/Application Support/MOT Deck`; repository work and release
> inputs come only from the canonical source above. Historical prose may name the archive
> as history. Registered Claude worktrees are preserved until their branches are audited;
> they are never pruned or deleted merely to make a path search look clean. The complete
> old→new identity map, external moves, intentional legacy literals, and exhaustive file
> inventory live in `docs/U150-IDENTITY-CHANGE-INVENTORY.md`; future identity changes must
> update that inventory rather than relying on a global text replacement.


> **⛔ LIVE-STATE FILES RULE (bitten once: motdeck.yaml clobber, 2026-09-03, U74):** the
> snapshot's `motdeck.yaml` and everything under the snapshot's `data/` are LIVE STATE —
> installed flags, pins, registries, sessions. The repo's `motdeck.yaml` is a TEMPLATE.
> Repo↔snapshot byte-parity applies ONLY to code the repo owns (bridge/, scripts/, app/,
> panel, docs); NEVER copy a live-state file from repo to snapshot, at QA or in a builder
> ship. Legitimate live-yaml changes go through targeted key edits (the way seeders and
> installers do it) — never a whole-file copy. ship.sh's `motdeck.yaml.bak-*` rotation is
> the recovery path; a shallow `diff | head` is not an inspection.

> **⛔ PROCESS-KILL RULE (bitten twice: Unsloth 2026-08-28, goose Desktop 2026-08-29):**
> agents/builders may terminate ONLY processes they themselves spawned, tracked by their own
> pidfile/child handle, identity-verified (full command line + env) before the kill. NEVER
> pkill/killall by name or pattern; never kill whatever holds a port (pick another port).
> Debi runs standalone copies of the same apps we embed — a name-match kill closes her work.

> **🧭 THE FULL PROACTIVE BUILD DOCTRINE (Debi standing order, 2026-08-28) — BINDING ON
> EVERY SLICE, EVERY TOPIC: read docs/DOCTRINE-PROACTIVE-BUILD.md and bind it by
> reference into every builder dispatch and every QA pass.** Short form: build the
> destination, not the request; WALK the realistic user journeys end-to-end on the real
> stack before "done"; run an adversarial self-pass (LIES-TO-USER outrank crashes
> outrank refusals); category conventions + graceful absence are requirements the user
> never has to write; prefer contextual inference over rule lists and NEVER dump
> ambiguity on the user as a question (autocorrect standard); every walked journey and
> fixed finding becomes a permanent gate test; reports end with honest limits + the
> try-it commands. Lessons are recorded in their GENERAL form with the incident as the
> example — a narrowly-worded lesson is how "every lane must land on something usable"
> failed to prevent the sum-over-text incident.

> **🧪 PROVE THE PREMISE, NOT THE PATCH (Debi standing order, 2026-09-05) — BINDING
> ANTI-SHORTCUT RULE:** a green suite never validates an unchallenged abstraction or
> source of truth. Before accepting any fix, reproduce the user's exact counterexample,
> identify and compare every plausible authority (filesystem, manager catalog, live
> process, persisted registry, UI), attack the predicate with realistic hostile controls,
> trace adjacent consumers and alternate entry points, and narrow every code/doc/release
> claim to exactly what was proved. Tests that mirror the implementation, one-byte
> "model" fixtures, source-string assertions, ceiling bumps, duplicate caches, and
> symptom-specific deletions cannot close a user-visible bug. Full binding and the
> U75/U76 incident are in docs/DOCTRINE-PROACTIVE-BUILD.md §10.**

> **🛡️ A FIX MAY NOT SPEND EXISTING PRODUCT INTENT (Debi standing order,
> 2026-09-05):** every fix/refactor preserves intentional features, visual and pointer
> affordances, controls, labels, shortcuts, layouts, fallbacks and user state unless
> Debi explicitly authorizes the change. UI QA compares the shipped baseline and the
> feature's introducing commit, accounts for moved code, and walks hover/focus/disabled,
> keyboard/pointer, reload/restart and dependency-failure paths. Any unexplained delta
> is a regression or an explicit UNFORGET row—not an acceptable cost of fixing something
> else. Full binding and incident are in docs/DOCTRINE-PROACTIVE-BUILD.md §11.**

> **🚪 BACKEND TRUTH ≠ HUMAN REACHABILITY (Debi standing order, 2026-09-06):**
> credentials, state, routes and lifecycle changes require two independent proofs: the
> authoritative backend transition and the real installed-shell journey through every
> affected native/sidebar/overlay entry to its first meaningful action. HTTP 200,
> component health, a successful login API, or a mounted DMG is only a smoke check.
> **Affected is the hard boundary:** do not demand a new prompt/render/train/edit inside
> an untouched third-party app, and do not label user-owned login, optional unset state
> (including Aux), or upstream onboarding as an M.O.T defect. Required-but-unwalked
> affected surfaces are explicit UNFORGET/report limits, never inferred green from suite
> volume. Full matrix and the v1.5.81→v1.5.82 Odysseus incident are in
> docs/DOCTRINE-PROACTIVE-BUILD.md §12.**

> **🧾 BASELINE RED/SKIPS ARE EVIDENCE, NOT EXEMPTIONS (Debi standing order,
> 2026-09-06):** “same on clean upstream” proves only that the candidate did not cause
> the result. It never means fixed, harmless or passed. Reports must name every failure
> and skip, reproduce reds at the exact baseline, run the upstream-supported platform and
> feature lane, classify portability/dependency/flakiness versus product behavior, and
> prove the candidate's affected tests were not skipped. Unsupported-command failures and
> transient reds remain recorded even when the supported lane is green. Full binding and
> the U72/U139/U144 incident are in docs/DOCTRINE-PROACTIVE-BUILD.md §13.**

> **🔁 DOCTRINE (Debi, 2026-08-27): every report to Debi that touches shipped behavior MUST
> end with the exact commands to see it — restart/refresh/kill MOT Deck. The canonical set:
> full ship `./scripts/ship.sh` (gate → snapshot → restarts app+bridge; components stay up);
> component restart `./scripts/ship.sh --restart <name>`; app only: quit with
> `osascript -e 'tell application id "local.motdeck.app" to quit'` then
> `open -b local.motdeck.app`; stale tab = ⌘R in the tab. The installed filename may be
> `MOT Deck.app`; lifecycle identity is the bundle id, never the filename.**


> **🔢 VERSIONING (Debi's ruling, 2026-08-27):** the authoritative current version is
> always the tracked `VERSION` file; do not duplicate a stale number in this doctrine.
> Every shipped work slice bumps the patch: 1.5.1, 1.5.2, … up to 1.5.100, then 1.6.0.
> Bump `VERSION` in the same commit as the slice it names and lead the commit message with
> the version (`v1.5.1: …`). "Shipped" = passed the gate + ship.sh, not merely edited.
> Sidebar → LOffice/Aider native-tab routing CONFIRMED by Debi on the Mac 2026-08-27.
