# New Harness — working memory (canonical project home)

> **🗄️ ARCHIVE:** session notes older than the current wave live in `docs/handoff/archive/CLAUDE-ARCHIVE-2026-07--08.md` (full, verbatim). This file carries only standing doctrine + the current wave — keep it that way: when a wave closes, move its notes to the archive.

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

> **🔁 DOCTRINE (Debi, 2026-08-27): every report to Debi that touches shipped behavior MUST
> end with the exact commands to see it — restart/refresh/kill MOT Deck. The canonical set:
> full ship `./scripts/ship.sh` (gate → snapshot → restarts app+bridge; components stay up);
> component restart `./scripts/ship.sh --restart <name>`; app only: quit with
> `osascript -e 'quit app "Harness"'` then `open -a Harness`; stale tab = ⌘R in the tab.**


> **🔢 VERSIONING (Debi's ruling, 2026-08-27):** the project is at **v1.5.0** (see `VERSION`).
> Every shipped work slice bumps the patch: 1.5.1, 1.5.2, … up to 1.5.100, then 1.6.0.
> Bump `VERSION` in the same commit as the slice it names and lead the commit message with
> the version (`v1.5.1: …`). "Shipped" = passed the gate + ship.sh, not merely edited.
> Sidebar → LOffice/Aider native-tab routing CONFIRMED by Debi on the Mac 2026-08-27.
