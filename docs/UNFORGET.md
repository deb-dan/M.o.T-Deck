<!-- unforget-format: v2 · preset: standard-10col · created 2026-08-29 by /unforget init -->

# UNFORGET — MOT Deck deferred-work ledger

One source of truth for deferred work. Format: unforget v2, Standard preset.
Sections: 1 Paused plans (P) · 2 Session spillover (S) · 3 Audit findings (A) · 4 User-reported/observed (U).
Targets: 🔴 THIS (blocks current cycle) · 🔵 NEXT · 🟡 LATER · ⚪ SOMEDAY.

## 1. Paused plans

| # | Target | Finding | Urgency | Risk: Fix | Risk: No Fix | ROI | Blast Radius | Fix Effort | Status |
|---|---|---|---|---|---|---|---|---|---|
| P1 | 🟡 LATER | Hermes v0.20.x update retry — blocked on two upstream camelCase bugs; venv parked, ceiling v2026.8.16 | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | 🟢 2-5 files | Small | `@status:blocked` waiting on upstream fix of 2 lines |
| P2 | ⚪ SOMEDAY | Euro-Office editor bump (next CryptPad released pair = upstream switch; full re-verification slice) | ⚪ LOW | 🟡 High | ⚪ Low | 🟢 Good | 🟡 6-15 files | Large | `@status:blocked` waiting on CryptPad release to move past v9.2.0.119+5 |
| P3 | 🔵 NEXT | Voice Chat M3 — push-to-talk/turn-based lane, VoiceChat-11B (measured 17.45GB peak), additive per ruling | 🟡 HIGH | 🟢 Medium | ⚪ Low | 🟠 Excellent | 🟡 6-15 files | Large | `@status:open` Fable spec next, then build |
| P4 | 🔵 NEXT | goose lane build — BUILD-READY (pins + kill switches verified); waiting on index.html owner to land | 🟡 HIGH | 🟢 Medium | ⚪ Low | 🟢 Good | 🟢 2-5 files | Medium | `@status:blocked` on UI-polish builder freeing index.html |
| P5 | 🔵 NEXT | ComfyUI Video/Audio first-party surface — research in flight; then Fable spec, then S1 build | 🟡 HIGH | 🟢 Medium | ⚪ Low | 🟠 Excellent | 🟡 6-15 files | Large | `@status:open` research DONE (docs/research/2026-08-29-comfyui-tab.md); Fable spec next, gated on Debi's 6 answers |

### Detail - Paused plans

- **P1** - llama.cpp-side mcp 2.0 renamed camelCase→snake_case; Hermes upstream missed `mcp_field` at mcp_tool.py:4643 (readOnlyHint→None→everything write-capable) and :7374 (inputSchema cache poison). Clean rollback done; retry venv parked. Research doc: docs/research (Hermes bump attempt notes, 2026-08-28 wave). **Verify-still-open:** `grep -rn "0.20" vendor/hermes/pyproject.toml 2>/dev/null || echo "check installed hermes version"` — expect: version still < 0.20.x.
- **P2** - CryptPad's 9.3.x tags are built from Euro-Office (Nextcloud/IONOS fork; does NOT ship the AI plugin). Bump = upstream switch: x2t/PDF re-measurement + AI-plugin-loads re-verification. See docs/research/2026-08-28-onlyoffice-forks-loader.md §1a and ROADMAP addendum. **Verify-still-open:** `grep -n "9.2.0.119" scripts/install_onlyoffice.sh` — expect: pin unchanged.
- **P3** - Measurement done (docs/research/2026-08-28-s2s-m2-voicechat.md): RTF 0.95 turn / 1.29 duplex, sha dffd203f, mlx-vlm 0.6.17 ships nemotron_voicechat runtime + /v1/realtime WS. Shape: push-to-talk first. 17.45GB figure surfaces ADVISORILY via the fit engine (advisory-gates ruling).
- **P4** - docs/research/2026-08-28-goose-source-verify.md: v1.48.0 sha 25021517…, asset sha256 d502945f…, GOOSE_TELEMETRY kill switches, GOOSE_DISABLE_KEYRING, seed real API key. Needs nav.py + index.html + main.swift.
- **P5** - Debi facts for the spec: NO ComfyUI models downloaded yet; models determine nodes — acquisition surface is first-class in S1. Research lands as docs/research/2026-08-29-comfyui-tab.md.

## 2. Session spillover

| # | Target | Finding | Urgency | Risk: Fix | Risk: No Fix | ROI | Blast Radius | Fix Effort | Status |
|---|---|---|---|---|---|---|---|---|---|
| S1 | 🔵 NEXT | LOffice Agent lane: auto-refresh model session when the tool catalog changes (stale sessions call retired tools) | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` |
| S2 | ⚪ SOMEDAY | Session-creation unification across lanes (offered to Debi, no word yet) | ⚪ LOW | 🟢 Medium | ⚪ Low | 🟡 Marginal | 🟢 2-5 files | Medium | `@status:open` awaiting Debi's word |
| S3 | 🟡 LATER | Tier-1 grid code deletion after soak + Univer rollback-asset removal decision | ⚪ LOW | 🟢 Medium | ⚪ Low | 🟡 Marginal | 🟡 6-15 files | Medium | `@status:open` soak ongoing since v1.5.x one-editor cutover |
| S4 | 🔵 NEXT | Voice/music spawn gates still use old budget_gb predicate — retrofit onto the fit engine (core/fit.py) | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | 🟢 2-5 files | Small | `@status:open` queued in v1.5.30 report |
| S5 | 🟡 LATER | Post-load truth: parse runner's own buffer-size log lines, store measured-vs-predicted per model | 🟢 MEDIUM | ⚪ Low | ⚪ Low | 🟢 Good | 🟢 2-5 files | Medium | `@status:open` designed in v1.5.30, not built |
| S6 | 🟡 LATER | Guardrail spectrum as a setting (Quiet / Advise / Advise-early / Custom headroom) per UX research §9.6 | ⚪ LOW | ⚪ Low | ⚪ Low | 🟡 Marginal | 🟢 2-5 files | Small | `@status:open` |
| S7 | 🔵 NEXT | Wan 2.1 colour defect on MPS: A/B the bf16 variant (2.84GB, same repo) against the recorded fp16 numbers | 🟡 HIGH | ⚪ Low | 🟢 Medium | 🟠 Excellent | ⚪ 1 file | Small | `@status:open` verdict printed on the /comfy card meanwhile |
| S8 | 🔵 NEXT | bridge/routers/comfy.py sits at exactly 1500 lines (facade ceiling) — extract curation+graph builders to core/comfycur.py BEFORE comfy S2 | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | 🟢 2-5 files | Medium | `@status:open` |
| S9 | 🟡 LATER | Goose slice 2: --resume/--name/--fork surface (history persisted+reachable, tab offers no way in); session-store size readout + prune for data/goose | 🟢 MEDIUM | ⚪ Low | ⚪ Low | 🟢 Good | 🟢 2-5 files | Medium | `@status:open` contract test already pins the flags |
| S10 | 🟡 LATER | aider.html predates theme packs (dark-only); goose.html's syncSkin is the backport pattern; studio-goose/aider.css if the design axis should reach terminal lanes | ⚪ LOW | ⚪ Low | ⚪ Low | 🟡 Marginal | 🟢 2-5 files | Small | `@status:open` |
| S11 | ⚪ SOMEDAY | opencode_tools_warning should take a lane label so goose+OpenCode share one decision table | ⚪ LOW | ⚪ Low | ⚪ Low | 🟡 Marginal | ⚪ 1 file | Trivial | `@status:open` |

### Detail - Session spillover

- **S1** - Incident: model called retired office_write_cells from stale session history; Debi cleared the session by hand. The fix: catalog-change hash → panel auto-starts a fresh Agent session with a notice line.
- **S4** - v1.5.30 shipped the engine + ledger; spawn_guard on music/voice lanes still uses the pre-advisor file-size predicate. Retrofit = same advisory + confirm shape as /api/models/switch. **Verify-still-open:** `grep -rn "budget_gb" bridge/ | head -3` — expect: hits in the spawn-gate path.
- **S5** - Ollama-pattern (fit-math research §3): the engine's own log lines are ground truth; storing measured-vs-predicted per model closes the loop and tightens future verdicts.

## 3. Audit findings

| # | Target | Finding | Urgency | Risk: Fix | Risk: No Fix | ROI | Blast Radius | Fix Effort | Status |
|---|---|---|---|---|---|---|---|---|---|
| A1 | 🔵 NEXT | USER-EXPLAINERS content gaps: LOffice section, new shortcuts (⌘⇧T etc.), memory strip/verdicts | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` Help serves the md raw — edit + ship only |
| A2 | 🔵 NEXT | Non-image file attach on Agent + Hermes lanes (backends accept; no UI) — second ⊕ type + @file: chip | 🟢 MEDIUM | 🟢 Medium | ⚪ Low | 🟢 Good | 🟢 2-5 files | Medium | `@status:open` from v1.5.28 audit table |
| A3 | 🟡 LATER | Hermes attach rehydration: reopened Hermes turn shows @image:<path> as text, not a thumbnail | ⚪ LOW | ⚪ Low | ⚪ Low | 🟡 Marginal | ⚪ 1 file | Small | `@status:open` |
| A4 | 🔵 NEXT | Caps strip shows Odysseus features on Chat + Hermes lanes where they mean nothing (misleading) | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` from v1.5.28 audit table |
| A5 | 🟡 LATER | Per-turn web-search toggle on Agent lane (allow_web_search hardcoded true) | ⚪ LOW | ⚪ Low | ⚪ Low | 🟡 Marginal | ⚪ 1 file | Small | `@status:open` |
| A6 | 🟡 LATER | Fit paths unvalidated on this machine: MLA + non-Gemma SWA (synthetic-header tested only); MLX vs real load; mmproj vision cost term | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` validate when such a model is installed/loaded |
| A7 | 🔵 NEXT | STALE GATE (fails at HEAD, pre-dates the comfy-nav slice): `test_opencode_lane.py::test_status_publishes_the_verdict_and_keeps_degraded_byte_identical` counts `"health": ` in the appsrc view and demands exactly 2; v1.5.36's `bridge/routers/comfy.py:134` made it 3 | 🟡 HIGH | ⚪ Low | 🟡 High | 🟠 Excellent | ⚪ 1 file | Trivial | `@status:open` a red test nobody is reading is a gate that has stopped gating |
| A8 | 🟡 LATER | `nav.normalize` appends an id a saved layout never heard of at the TAIL of the bar, not at its DEFAULT-order neighbour — so every new nav row lands at the bottom of the Workspace group on a customised machine while sitting where it was designed to sit on a fresh one | 🟢 MEDIUM | 🟡 High | 🟢 Medium | 🟢 Good | 🟢 2-5 files | Medium | `@status:open` observed live at the comfy-nav slice |
| A9 | 🟡 LATER | Panel-wide (NOT slice-specific): the `studio-light` design under a DARK theme pack (cyber/gold/Editorial) drops sidebar text to ~2.3-2.5:1 contrast — every row equally, measured by computed values across 24 look-combos | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` the two axes are independent, so the combo is user-reachable |

### Detail - Audit findings

- **A2** - Backends verified in v1.5.28: Odysseus uploads inline text/PDF/audio via POST /api/upload; Hermes has file.attach + pdf.attach RPCs. **Verify-still-open:** `grep -c "file.attach" bridge/routers/hermes.py` — expect: 0 (no UI wiring yet).
- **A7** - Found by the comfy-nav slice's sweep and confirmed PRE-EXISTING by stashing that slice's diff and re-running at HEAD. The fence's *point* is right ("both the components loop and the runner publish `health`, and nothing else does") but its *instrument* is a substring count over the whole appsrc view, so an unrelated dict key in an unrelated router trips it. Fix = count within the two publishers, or name them. **Verify-still-open:** `data/bridge-venv/bin/python -m pytest -q bridge/tests/test_opencode_lane.py` — expect: 1 failed, 70 passed.
- **A8** - The Help precedent (bridge/nav.py's DEFAULT_SIDEBAR comment) chose tail-append deliberately, and rightly: a migration that repositions rows would move rows a user arranged by hand. But Help *wanted* the tail (it renders directly under Logs there); Generate does not — on Debi's Mac it renders below Help instead of beside Music, where a fresh install puts it. The general shape: appending by DEFAULT-ORDER NEIGHBOUR rather than at the tail would give both machines the designed layout without ever reordering a row the user actually placed. Not attempted in a nav-entry slice because it changes placement for every future entry. **Verify-still-open:** `curl -s http://127.0.0.1:8700/api/nav | grep -o '"comfy"'` then read the position — expect: last in the sidebar list.
- **A9** - Measured at the comfy-nav slice's ALL-DESIGNS pass, on the *sibling* row as well as the new one (identical computed color and background), which is what makes it panel-wide and pre-existing rather than a slice regression. `data-theme` (Editorial/light/gold/cyber) and `data-design` (editorial/studio/studio-light) are independent axes and the panel's own toggles can reach every pairing, so a user in cyber who flips to Studio light gets 2.31:1 body text. The dark-theme × studio-dark and light-theme × studio-light pairings are all ≥6.4:1. **Verify-still-open:** in the panel, set `data-theme="cyber"` + `data-design="studio"` + `data-dvariant="light"` on `<html>` and read the computed color of any sidebar row against its ground.
- **A6** - v1.5.30 honest-limits: no DeepSeek/GLM/Kimi (MLA) model installed; MLX estimate is formula+10% labeled; vision = file size + 0.4× encoder (Unsloth's constant), unvalidated. When one of these is installed, run predicted-vs-measured and extend the gate table in test_fit_advisor.py.

## 4. User-reported / observed

| # | Target | Finding | Urgency | Risk: Fix | Risk: No Fix | ROI | Blast Radius | Fix Effort | Status |
|---|---|---|---|---|---|---|---|---|---|
| U1 | 🟡 LATER | Odysseus vision ROOT CAUSE upstream (Debi ruling 2026-08-29): name-keyword detection + hard-coded 120s VL timeout; our pre-caption is a bridge, retire it when upstream fixes | 🟡 HIGH | 🟢 Medium | 🟢 Medium | 🟠 Excellent | 🟢 2-5 files | Medium | `@status:blocked` upstream issue/PR needs Debi's word (publishes under her account) |
| U2 | 🟡 LATER | ~/.hermes shared-home ruling pending (component isolation vs standalone app, same class as the Unsloth ~/.unsloth fence) | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | 🟢 2-5 files | Small | `@status:open` awaiting Debi's ruling |
| U3 | 🔵 NEXT | Debi's clicks: revoke the GitHub PAT that appeared in a session transcript; give the word on deleting the 3.4GB probe dir + update .baks | 🟡 HIGH | ⚪ Low | 🟡 High | 🟠 Excellent | ⚪ 1 file | Trivial | `@status:blocked` user actions, not code |
| U4 | ⚪ SOMEDAY | Agent-lane bubble shows Odysseus's own "[Image: name]" line beside the thumbnail (cosmetic; stripAttachMarker kept for bridge parity) | ⚪ LOW | 🟢 Medium | ⚪ Low | 🟡 Marginal | ⚪ 1 file | Small | `@status:open` |
| U5 | ⚪ SOMEDAY | ONLYOFFICE AI plugin chat-wipe still unfixed upstream (our oo.html fix is the only one); re-check on any plugin bump | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:blocked` version fence flags the moment automatically |
| U6 | ⚪ SOMEDAY | Two LOffice surfaces open at once (embed + standalone /oo-edit) contend over one localStorage plugin key — not walked | ⚪ LOW | 🟢 Medium | ⚪ Low | 🟡 Marginal | ⚪ 1 file | Small | `@status:open` |
| U7 | 🟡 LATER | Ribbon AI Text-analysis actions in the WORD editor take the same shim seam but were never clicked in a .docx (inference, not measurement) | 🟢 MEDIUM | ⚪ Low | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:open` walk once in a real .docx |
| U8 | ⚪ SOMEDAY | MiniMax H3 video+audio (open weights 2026-08-03, day-0 ComfyUI) — REFUSED FOR NOW by Debi: smallest set ~39.6GB vs ~48GB free disk | ⚪ LOW | 🟢 Medium | ⚪ Low | 🟢 Good | 🟢 2-5 files | Large | `@status:blocked` on disk space; revisit when freed |
| U9 | 🟡 LATER | ComfyUI's ASSET SYSTEM is off at our pin, so the newest workflow templates carry no `properties.models` registry — the Generate lane's curation can only be generated from the 78 of 517 templates that still do. Bridge: curate registry-bearing templates only; drift is named on the card | 🟢 MEDIUM | 🟢 Medium | 🟢 Medium | 🟢 Good | ⚪ 1 file | Small | `@status:blocked` on an upstream/config change that enables `/api/assets` |

### Detail - User-reported / observed

- **U1** - Full context: ROADMAP-2026-08-14.md addendum (2026-08-29) + v1.5.31 commit. Bridge = pre-caption via loaded vision model (enable_thinking:false, ~6s) into Odysseus's own .vision cache + evidence-gated vision_model auto-wire. Retirement: delete pre-caption path + data/ody_vision_autowire.json when upstream update lands; test_attach_lanes_contract.py pin-bump gates name exactly what to re-check. Upstream asks: capability-based detection + configurable timeout. **Verify-still-open:** `grep -n "timeout=120" vendor/odysseus/src/*.py | head -2` — expect: the hard-coded cap still present.
- **U3** - The PAT (ghp_…) appeared in a session transcript; treat as exposed. Revoke at github.com/settings/tokens and mint a fresh one if pushes should continue. The 3.4GB: ONLYOFFICE probe dir + component-update .bak files — deletion needs Debi's explicit word (destructive).
- **U9** - `GET /features` → `"assets": false` at ComfyUI v0.34.1 as we launch it, and `/api/assets` answers 503; the `app/assets/` tree exists in the vendored source but is not enabled. Upstream is migrating template model references OUT of `properties.models[]` and INTO that system, so the share of templates our curation can read will SHRINK with every pin bump. Our bridge (bridge/routers/comfy.py `template_models` + `registry_drift`) is honest about it — a pick whose template stops naming its files says so on the card instead of downloading the wrong thing — but the answer is either enabling the asset system or vendoring the model manifests ourselves. Re-check at every ComfyUI pin bump. **Verify-still-open:** `curl -s http://127.0.0.1:8188/features` — expect: `"assets": false`.
- **U8** - Sizes HEAD-verified 2026-08-29: pruned-int8 diffusion 19.5GB + nvfp4 encoder 14.6GB + VAEs 5.5GB = 39.6GB minimum; standard 62.5GB. MiniMax H3 Community License (verify terms before curating). Native stereo audio could partially cover the S3 audio goal. Curate via the vendored template registry when disk allows.
- **U5** - Fifth upstream trap (v1.5.29): plugin's init clearChatState() wipes its own saved state; setState only reachable via onDockedChanged. Our fix is version-fenced on plugin 3.2.2 — a plugin bump deactivates it safely and the fence test says so. **Verify-still-open:** `grep -rn "clearChatState" data/oo/dist/v9/ai/scripts/code.js 2>/dev/null | head -1` — expect: still present in vendored bytes.
