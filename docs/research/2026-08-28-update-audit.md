# Update audit — 2026-08-28 (READ-ONLY sweep; report only, nothing changed)

Sources of truth read: `harness.yaml` (components + `runner` + `build` pins),
`scripts/install_*.sh`, `scripts/start_component.sh`, venv dist-info listings
(`data/bridge-venv`, `data/mlx-venv`, `data/hermes-venv`, `data/odysseus-venv`),
vendor checkouts (`git describe`/`log`/`status`), `data/onlyoffice` pins in
`scripts/install_onlyoffice.sh`, and the doctrine in
`docs/handoff/UPDATE-RUNBOOK-2026-08-14.md` (one pass per sitting, contract tests
green before shipping, snapshot AND repo both updated, rollback recorded first).

Latest-version data fetched live 2026-08-28 (GitHub releases/commits, PyPI JSON,
registry.npmjs.org, HF API). Verdict legend: **SECURITY** / **BUGFIX-WORTHWHILE** /
**FEATURE-NICE** / **RISKY-BREAKING** / **SKIP**.

---

## 1. Installed components (running lanes)

### Hermes (NousResearch/hermes-agent) — vendored, INSTALLED
> **‼️ SUPERSEDED 2026-08-28 (same day): the bump was ATTEMPTED and ROLLED BACK.**
> The real newest tag is **v2026.8.27** (not a "v0.20.6 line" — that tag *is* v0.20.6),
> and it is **BLOCKED by two upstream bugs**, not by our integration: Hermes v0.20.3+
> forgot to convert two `getattr(obj, "camelCase")` reads for mcp 2.0.0's snake_case
> field rename, which (1) makes every read-only MCP tool on an `untrusted` server raise
> an approval card and (2) writes EMPTY tool schemas into
> `~/.hermes/cache/mcp_schema_cache.json`. Both reproduced live on the real stack.
> **Do not retry above `v2026.8.16` (the last `mcp==1.28.1` tag) without reading
> `docs/handoff/HERMES-v0.20.6-BLOCKED-2026-08-28.md` first** — it carries the root
> cause, the retry plan, and the large amount that DID pass (notably: our hand-written
> MCP server needs no change at all for mcp 2.0.0). Ranked recommendation #4 below is
> stale, and so is this section's "our 102-test contract suite is the gate": the suite
> went GREEN at v0.20.6 (142/142) while the LOffice Agent lane was broken.
- **Our pin:** tag `v2026.8.13` (app version v0.20.1). Verified: `git -C vendor/hermes describe` = v2026.8.13.
- **Latest:** v0.20.6 line, released 2026-08-27 (five releases since ours: 0.20.2–0.20.6, ~1,400 merged PRs total).
- **Delta:** **FEATURE-NICE, leaning RISKY** — big feature waves (MCP 2.x migration in 0.20.3, Bot Mode plugin bundling, desktop registry expansion, OS-keychain encryption in 0.20.6, subprocess Python isolation hardening). No advertised critical security fix. The MCP 2.x migration and the known upstream habit of pruning dashboard flags (`--tui` shim comment; `_add_server_runtime_args()` refactor) mean our 102-test contract suite is the gate — the manifest's own watch-item warns `HERMES_DESKTOP=1` + source-less sessions resolve to "desktop" surfaces.
- **Local modifications a bump would clobber:** `vendor/hermes/package-lock.json` is DIRTY (` M` in git status) — the known dirty file. Stash/discard deliberately before checkout; everything else in vendor/hermes is clean.
- **Update path:** UPDATE-RUNBOOK PASS-2 shape: bump `components.hermes.pin` in BOTH harness.yamls → `git -C vendor/hermes fetch --tags && checkout <tag>` → `python3 -m pytest bridge/contract_tests/ -q` MUST be green → `./scripts/install_component.sh hermes --yes` → rsync to snapshot + pip install -e → `./scripts/ship.sh` → **then `./scripts/start_component.sh hermes` from the snapshot** (ship.sh leaves the old Hermes process serving). Re-check `approvals.mode: manual` after.

### Odysseus (pewdiepie-archdaemon/odysseus) — vendored, INSTALLED
- **Our pin:** dev-branch commit `25c9e735` (2026-07-30). Verified in vendor/odysseus; working tree clean.
- **Latest:** dev @ `c9dd68d` (2026-08-27), ~35+ commits since mid-August alone (a month of drift).
- **Delta:** **BUGFIX-WORTHWHILE** — session-cookie Secure-flag fix, orphaned-temp-file cleanup on atomic writes, vendored KaTeX/Mermaid (perf), VectorRAG shape fixes. Nothing flagged as breaking, but our bridge is rewired to `inject_messages` because upstream removed fork/message routes once already — a bump needs the same contract-check discipline.
- **⚠️ Branch trap (manifest is explicit):** the pin is on **dev**, upstream's default HEAD. `origin/main` is a STALE side branch BEHIND us containing a reverted change. Any bump must be `git -C vendor/odysseus fetch origin dev` + a dev SHA — never "latest main".
- **Update path:** edit `components.odysseus.pin` to the new dev SHA (both yamls) → fetch/checkout in vendor → contract tests → `install_component.sh odysseus` → ship.sh → `start_component.sh odysseus`.

### SearXNG — vendored shallow clone, INSTALLED, pin = `main` (rolling)
- **Our checkout:** `6da6eee2` (2026-07-19) — ~6 weeks behind.
- **Latest:** master @ ~`9fea412` (2026-08-22); very active.
- **Delta:** **SECURITY** — since our checkout upstream fixed a **calculator XSS via innerHTML (#6551, 2026-08-19)**, capped zlib decompression in preferences (DoS hardening, 2026-08-21), and fixed (un)trusted-proxy handling (#6556). Ours is loopback-only which softens the blast radius, but the Odysseus chat pane drives it, so XSS in a results widget is a real lane.
- **Update path:** pin is `main` so no yaml edit — `git -C vendor/searxng pull` (or re-run `install_component.sh searxng`) in repo + snapshot, then `start_component.sh searxng`. Its venv only carries httpx etc.; re-run the installer to catch requirement changes.

### llama.cpp (the model engine) — INSTALLED
- **Our pin:** `runner.llamacpp_pin: b10427` in harness.yaml; verified live: `data/llamacpp/build/bin/llama-server --version` = build 10427. A `data/llamacpp.b10295.bak` rollback copy exists from the last pass (now two generations old).
- **Latest:** `b10662` (2026-08-27) — ~235 builds ahead. Recent range adds Qwen3.8-Flash-Next arch, DFlash2, DeepSeek V4 LIGHTNING_INDEXER (Vulkan), ctx-per-slot unified KV cache.
- **Delta:** **FEATURE-NICE / BUGFIX-WORTHWHILE** — new model-arch support is the usual reason to bump; no advertised breaking changes, but our own pin-notes doctrine requires re-verifying the flag surface at the candidate (`-a/--alias`, `--repeat-penalty`, `--spec-type` + DRAFT_MTP, llama-tts `-m/-mm/-p/-o`, `--tts-lang`, `--tts-speaker-file`, and that `-mv/--vocoder-model` is still absent) plus the config.ini watch-item (#26118). Also verify `llama-<tag>-bin-macos-arm64.tar.gz` actually exists before pinning (CI lags fresh tags — b10297 precedent).
- **Update path:** UPDATE-RUNBOOK PASS-3: `cp -R data/llamacpp data/llamacpp.b10427.bak` FIRST (installer keeps no backup), bump `runner.llamacpp_pin` in both yamls, `./scripts/install_llamacpp.sh` both places, `./scripts/ship.sh`, verify gguf chat + tok/s + gguf TTS.

### mlx-lm / mlx-vlm / mlx-audio / mlx-whisper (data/mlx-venv) — INSTALLED
Venv verified: mlx 0.32.0, mlx-lm 0.31.3, mlx-vlm 0.6.13, mlx-audio 0.4.8, mlx-whisper 0.4.3 — all exactly at the harness.yaml `build.*` pins. ✔ pins == reality.
- **mlx-lm** 0.31.3 → PyPI latest **0.31.3**. **SKIP** — already current.
- **mlx-vlm** 0.6.13 → latest **0.6.17**. **BUGFIX-WORTHWHILE** — patch-line bumps; last bump (0.6.10→0.6.13) was additive-args only, so risk is low, but re-check the `mlx_vlm.server --model/--host/--port` launch line at the candidate.
- **mlx-audio** 0.4.8 → latest **0.5.0** (2026-08-17). **RISKY-BREAKING** — a MINOR-version jump on the exact package where the manifest's standing rule says every bump must re-derive `CLI_PARITY_KWARGS` by measurement (a drift is *silently wrong audio*, not an error). 0.4.7→0.4.8 was only safe because the argparse files were md5-identical; a 0.5.0 will not be. Also remember: RenderCache keys don't include engine version — stale renders survive the bump. Do this one alone, with the pinned-clip A/B verify.
- **mlx-whisper** 0.4.3 → latest **0.4.3**. **SKIP** — current.
- **Update path (all four):** edit `build.mlx_*_pin` in harness.yaml (single source of truth) in BOTH copies → `./scripts/install_mlx.sh` in snapshot then repo → `./scripts/ship.sh` → verify per PASS-1 (MLX chat streams, vision answers, ▶ speak same-voice on FRESH text, both STT models).

### Bridge venv (data/bridge-venv) — our own runtime libs
Verified: fastapi 0.139.2, starlette 1.3.1, uvicorn 0.51.0, websockets 17.0.1, openpyxl 3.1.5, pytest 9.1.1.
- **fastapi** 0.139.2 → latest **0.141.1**: **FEATURE-NICE/SKIP** — no known advisory in range; the mlx-venv already carries 0.141.1 so the ecosystem is compatible. Bump opportunistically at the next bridge-venv rebuild, not as its own pass.
- **openpyxl** 3.1.5 → latest **3.1.5**: **SKIP** — current (and load-bearing for the LOffice round-trip).
- **pytest** 9.1.1 → latest **9.1.1**: **SKIP** — current.
- **Update path:** these aren't pinned in harness.yaml; they ride whatever provisions bridge-venv (bootstrap/requirements). Any bump = reinstall into data/bridge-venv + run the contract suite + ship.sh.

### ONLYOFFICE bundles (LOffice tier 2) — INSTALLED (data/onlyoffice, hash-pinned)
> **‼️ SUPERSEDED 2026-08-28 (same day): the bump was DONE, probed and KEPT.**
> Editor is now **`v9.2.0.119+5`** — sha256 `3f4987af…0715`, sha512 `1f1184fb…04cfa`, and
> that sha512 is **CryptPad's own pinned digest**. x2t stays **`v7.3+1`** (unchanged; its
> sha512 already matched CryptPad's all along). Full WKWebView probe pass, old-vs-new, on
> the real bridge: every journey identical, zero console errors, nothing rolled back —
> **`docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md` → "RESULTS ADDENDUM — 2026-08-28"**.
>
> Two corrections to the bullets below, both from reading CryptPad live rather than from
> search results: **(1) there was never an ambiguity.** CryptPad pins `+5` on every
> RELEASED branch — `main`, `2026.5.1-rc`, `2026.4-rc`, `2026.2.2-rc`, identical hash in
> all four — and the `v9.3.0+0` x2t appears only on their **unreleased** test branches
> (`2026.4-test`: editor `v9.3.0.140+0`; `2026-autumn-test`: editor `v9.3.2+1`). Our "+3"
> was simply two builds behind their tested pair, which is also the whole explanation of
> the runbook's "our sha512 is not in their installer" note. **(2) the bump was far cheaper
> than "deferred" implied:** 31 of 16604 files differ, and `x2t.js`, `x2t.wasm`, `api.js`,
> `api-orig.js` and all three `sdkjs/*/sdk-all-min.js` are byte-identical FILES — so not one
> integration surface moved. The real changes: `presentationeditor/app.js` (+41 bytes, the
> Slide Master fix), the three `index.html`s (a dead `return;` removed from
> `injectSvgIcons`, live only above 2.25 dppx), and 4 new fonts (91 → 95 faces, picked up
> automatically because `/api/oo/fonts` reads the directory).
>
> The **v9.3 editor + x2t pair stays correctly deferred**: a new x2t means re-measuring the
> entire PDF recipe (the `c_oAscFileType` codes and `m_bIsNoBase64`, both of which fail
> SILENTLY when wrong), and CryptPad has not released it. Ranked recommendation #6 below
> is DONE for the +5 half and still open for the v9.3 half.
- **Our pin:** editor `cryptpad/onlyoffice-editor v9.2.0.119+3` (sha256 68ae8f0f…), x2t `cryptpad/onlyoffice-x2t-wasm v7.3+1` (sha256 86b6f1ac…). **The pin is the recorded HASH, not the tag** (2026-08-27 ruling; CryptPad's own installer pinned a neighbouring build).
- **Latest:** editor family — `v9.2.0.119+5` ("Fix Slide Master view"; +4 fixed toolbar at large display zoom), then a newer **v9.3 train** up to `v9.3.2+2`. x2t — `v8.3.0+0` and `v9.3.0+0` (x2t upgraded to v9.3.0.140) exist above our v7.3+1.
- **Delta:** **BUGFIX-WORTHWHILE but deliberately deferred** — the known open question from the probe runbook: CryptPad's install script itself reads two ways (`+5` in one reading, `+3` in another). `+4`/`+5` are small view/toolbar fixes; the v9.3 train + new x2t is a bigger move that would need a fresh WKWebView probe pass (the current bytes are the ones that were *measured*). Nothing security-flagged. If bumping, prefer the whole v9.3 editor+x2t pair as one re-probe, not a mixed set.
- **Update path:** re-run the probe per `docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md`, record new sha256/sha512, edit `EDITOR_TAG/EDITOR_SHA256/X2T_TAG/X2T_SHA256` in `scripts/install_onlyoffice.sh`, run it with `--force`. No restart needed (bridge/oo.py reads the stamp per request). AGPL conditions 1–4 unchanged.

## 2. Optional components (installed: false — no live exposure today)

### VoiceStudio — pin `v0.4.2`, NOT installed
- **Latest:** **v0.5.0** (2026-08-14) — rebrand from OmniVoice-Studio, Model Catalogue, GPU-share join codes, and **server-mode API-key auth for admin actions**.
- **Delta:** **FEATURE-NICE (SECURITY-adjacent if ever exposed)** — the auth hardening matters only in server mode; ours binds 127.0.0.1. ⚠️ The rebrand may move the `omnivoice`-prefixed env vars/ids our manifest comments rely on (OMNIVOICE_BIND_HOST/PORT/DATA_DIR) — verify before pinning. **SKIP until someone actually installs it; bump the pin at that moment.**
- **Update path:** edit `components.voicestudio.pin` → `install_component.sh voicestudio`.

### Voicebox — pin `v0.5.0`, NOT installed
- **Latest:** **v0.5.0** — we are at upstream's newest tag; project bursts (last flurry April 2026) then quiet; manifest already flags it stale with 449 open issues and no auth anywhere.
- **Delta:** **SKIP** — nothing newer exists; the standing risk notes (loopback-only, fragile 5-package dep graph, online-only install) all still apply.

### ComfyUI — pin `v0.33.3`, NOT installed
- **Latest:** **v0.34.0** (2026-08-26) — HDR/AV1/mkv/webm video saving, TRELLIS2/Pixal3d 3D models, MiniMax-H3 support; warns Python 3.10 EOL is coming (we build with 3.12 — fine).
- **Delta:** **FEATURE-NICE** — additive; arm's-length process so blast radius is its own port. Bump whenever it's first installed; nothing urgent while `installed: false`.
- **Update path:** edit `components.comfyui.pin` → `install_component.sh comfyui`. Keep the `--base-directory` rule.

### Unsloth Studio — pin `v0.1.801-beta`, NOT installed
- **Latest:** **v0.1.804-beta** (2026-08-27); 802/803 on 08-25. Fast-moving beta tag family.
- **Delta:** **FEATURE-NICE/SKIP** — three beta tags in a week; pointless to chase while not installed. Re-read the `_terminal_password_gate` loopback behaviour at whatever tag is current when it IS installed.
- **Update path:** edit `components.unsloth.pin` → `install_component.sh unsloth`.
- **CORRECTION (2026-08-28, post-audit):** two facts above went stale the same day: it IS installed (live on :8899, snapshot venv `data/unsloth-venv`, editable at the vendored tree) and the pin WAS bumped to `v0.1.804-beta` (sha `8c43aed`). Then its own UI offered "2026.8.18 → 2026.8.22" anyway. Investigated: **the tag family and PyPI CalVer are the same release train** — `v0.1.804-beta` carries `unsloth/_version.py = "2026.8.22"` and PyPI latest is 2026.8.22 (uploaded 2026-08-27, hours after the tag), so the pin was already feed-current. The banner's "2026.8.18" was the OTHER install's metadata: upstream's CLI re-execs into the managed venv `~/.unsloth/studio/unsloth_studio` (owned by the standalone 8888 app), whose non-editable PyPI `unsloth==2026.8.18` dist is what the version endpoint and the updater report — the executed code is still our vendored tree. Its updater feed is PyPI (`update_status.py` → `pypi.org/pypi/unsloth/json`); its llama.cpp toast tracks GitHub releases of its FORK `unslothai/llama.cpp` (`bNNNNN-mix-<sha>` = fork patches on upstream base build bNNNNN) installed at `~/.unsloth/llama.cpp` — its own binary/process/dirs, updates in place THERE, never our runner on :6767, `data/llamacpp`, or `vendor/`. Fix shipped: `UNSLOTH_DISABLE_UPDATE_CHECK=1` on the launch line (start_component.sh) — upstream's documented opt-out; version banner + startup GitHub probes off. The llama.cpp toast is not covered by that var at this pin (only a Settings custom-path/local-link install suppresses it) — left alone, it manages its own engine. See the standing rule added to UPDATE-RUNBOOK-2026-08-14.md. **UPDATE (2026-08-28, later the same day): the shared-home coupling itself is GONE — the component now runs with UNSLOTH_STUDIO_HOME=data/unsloth-home (own venv at data/unsloth-home/unsloth_studio, in-process serve, own engines), ~/.unsloth is 100% the standalone's again, and start_component.sh fences it. See the isolated-home standing rule in UPDATE-RUNBOOK-2026-08-14.md.**

### OpenCode — pin `1.18.19` (npm version, both `components.opencode.pin` and `build.opencode_pin`), NOT installed
- **Latest:** **1.18.23** on npm.
- **Delta:** **BUGFIX-WORTHWHILE at install time** — patch releases only. A bump must re-verify the three things the manifest names: `serve --port/--hostname`, the `autoupdate` key + `OPENCODE_DISABLE_AUTOUPDATE`, and the four XDG_* variables in packages/core/src/global.ts — plus record the NEW arm64 tarball shasum in `scripts/install_opencode.sh` (it verifies `de148944…` today, which is 1.18.19's). **Two pins + one hardcoded shasum must move together.**
- **Update path:** edit both pins in harness.yaml + the shasum in `install_opencode.sh` → `./scripts/install_opencode.sh`.

### aider — pin commit `5dc9490b` (main), venv/vendor NOT present yet
- **Latest:** main HEAD **is our pin** (2026-05-22 merge; upstream slow-but-alive, exactly as the recon recorded).
- **Delta:** **SKIP** — we are at HEAD; nothing to do. Plan B (cecli fork at a release tag, keeping `--edit-format whole`) only triggers if main goes >6 months quiet — that clock runs out ~2026-11-22; note for the November sweep. (The cecli fork was checked and REJECTED at recon; we installed upstream Aider-AI/aider.)

### Music lane — NOT installed (no data/music-venv on disk)
- **MiniMax-Music3 MLX** (PocketAiHub/MiniMax-Music3-MLX): pin `0505e3f0…` **= current HF revision** (lastModified 2026-08-15). **SKIP** — at head.
- **acestep.cpp** (ServeurpersoCom/acestep.cpp): pin `9761469d` **= current HEAD** ("lm: heterogeneous request batching…"). **SKIP** — at head. Never run its server.sh (binds 0.0.0.0) — rule stands.
- **Update path when it moves:** edit `build.music_minimax_pin` / `build.acestep_pin` → `./scripts/install_music.sh`; the minimax pin doubles as the install-detection cache path, so a pin edit genuinely means "different install".

## 3. Build-time toolchain and static vendored assets

| Thing | Our pin | Latest | Verdict | Path |
|---|---|---|---|---|
| **bun** (build-time only; `data/bun` present) | bun-v1.3.14 | **v1.4.0** (2026-08-20) | FEATURE-NICE — build-time only, nothing at runtime needs it; no advisory surfaced in range. Bump before the next voice-SPA rebuild, verify `bun-darwin-aarch64.zip` exists at the tag. | `build.bun_pin` → `scripts/ensure_bun.sh` re-run |
| **uv** (portable-first-run bootstrap) | 0.12.3 | **0.12.6** (2026-08-25) | SKIP/FEATURE-NICE — no security fixes in range (TLS/riscv64 fixes, bearer-token panic fix); a user's own uv always wins anyway. Bump at next fat-installer build. | `build.uv_pin` → firstrun.sh path |
| **imageio-ffmpeg** | 0.6.0 | **0.6.0** | SKIP — current. ⚠️ still ffmpeg-only, no ffprobe. | `build.imageio_ffmpeg_pin` |
| **Univer UMD bundle** (retired-but-present, `bridge/panel/assets/vendor/univer/`) | 0.25.1 | **0.25.1** (npm latest; the 1.0.0-beta line is deliberately not taken) | SKIP — current AND retired: the LOffice sheets surface moved to ONLYOFFICE; the assets are dead weight served by us. Candidate for removal, not update. | `build.univer_pin` → `scripts/fetch_vendor_assets.sh` |
| **CPython (fat bundle)** | 3.12.11 | (not re-checked — still the pending Fable-QA item in harness.yaml) | SKIP this sweep | `build.python_version` |
| **Node** | not vendored (bun only) | — | n/a | — |
| **whisper.cpp** | not vendored (STT = mlx-whisper; `faster-whisper 1.2.1` in hermes-venv is Hermes's own dep, ours only transitively) | — | n/a — rides the Hermes bump | — |

## 4. Ranked recommendations

1. **SearXNG — SECURITY, do first.** XSS fix (#6551) + zlib DoS cap since our 2026-07-19 checkout; it's a rolling `main` pin so this is a pull + component restart, the cheapest pass in the whole list.
2. **llama.cpp b10427 → b10662 — worthwhile PASS-3-style bump.** New model archs; run the flag-surface verification checklist and take the backup first (`llamacpp.b10427.bak`).
3. **Odysseus dev 25c9e73 → c9dd68d — worthwhile.** A month of fixes incl. cookie Secure flag; MUST be a dev-branch SHA (main is a trap), contract tests gate it.
4. **Hermes v2026.8.13 → v0.20.6-line — feature-rich but the riskiest bump.** MCP 2.x migration + 5 releases of churn; discard the dirty `vendor/hermes/package-lock.json` deliberately; full 102-test suite + the desktop-surface watch-item. Do it on its own sitting.
5. **mlx-vlm 0.6.13 → 0.6.17 — low-risk patch bump** next time install_mlx.sh runs.
6. **ONLYOFFICE editor +3 → +5 (or the v9.3 pair) — deferred by design.** Answers the standing CryptPad "+5 question": +4/+5 are real but minor fixes; a v9.3 editor+x2t move needs a fresh probe pass with newly recorded hashes. No security driver found.
7. **OpenCode 1.18.19 → 1.18.23, ComfyUI → 0.34.0, Unsloth → v0.1.804-beta, VoiceStudio → v0.5.0** — all `installed: false`; bump each at the moment it's first installed, per-component checklists above.

## Explicitly NOT worth touching
- **mlx-lm, mlx-whisper, openpyxl, pytest, imageio-ffmpeg, Univer, aider, MiniMax-Music3, acestep.cpp, Voicebox** — all already at upstream latest (or upstream hasn't moved).
- **mlx-audio 0.4.8 → 0.5.0** — deliberately deferred: minor-version jump on the one package whose bump rule demands re-measuring `CLI_PARITY_KWARGS` (silent audio drift risk) + stale RenderCache. Only as its own pass, with the pinned-clip A/B.
- **Odysseus via `main`** — never; it moves us backward.
- **OpenCode's in-app upgrade** — never; pin discipline.

## Local modifications a bump would clobber
- `vendor/hermes/package-lock.json` — modified (the known dirty file). Everything else in vendor/hermes, vendor/odysseus, vendor/searxng is clean at audit time.
- `data/llamacpp.b10295.bak` still on disk — two generations old once b10662 lands; fine to age out after the next successful bump.
