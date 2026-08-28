# New Harness — working memory (canonical project home)

> **🗄️ ARCHIVE:** session notes older than the current wave live in `docs/handoff/archive/CLAUDE-ARCHIVE-2026-07--08.md` (full, verbatim). This file carries only standing doctrine + the current wave — keep it that way: when a wave closes, move its notes to the archive.

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
> Queued: ONLYOFFICE AI plugin -> our runner, Download-as-PDF (x2t has PdfWriter), Docs/Slides,
> app.py modularization (10,072 lines — router/facade split ratified), tier-1
> deletion after soak. Debi's clicks: PAT revoke; probe dir (3.2GB) + update .baks deletable.

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
