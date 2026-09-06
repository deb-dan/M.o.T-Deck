# Update sweep — every pin we own, checked against upstream (2026-08-14)

**Research only. NOTHING was bumped in this session.** No file outside this report was written.
Method: `git ls-remote` / shallow blob-less clones of each upstream at the candidate ref, PyPI
JSON + sdist diffs for the Python pins, and — where a candidate exists — **our own
`bridge/contract_tests/` were RUN against the candidate checkout** (symlinked into a fake repo
root), so the risk column is measured, not guessed.

Network note: `api.github.com` and `raw.githubusercontent.com` are **blocked** from this sandbox
(curl 56 / HTTP 000 via the proxy), and release-asset bodies on `objects.githubusercontent.com`
are blocked too. `github.com` itself works, so `git ls-remote`, blob-less clones, and asset
**existence** checks (302 = present, 404 = absent — discriminated against a bogus tag) all work.
Release *notes* were therefore read from in-repo `CHANGELOG.md` and commit titles rather than the
Releases API.

---

## The table

| Component | Pinned now | Latest available | Contract risk | Recommendation |
|---|---|---|---|---|
| **Hermes** | `v2026.7.30` | **`v2026.8.13`** (also `v2026.8.3`) | **LOW** — 13/14 contract asserts pass at the candidate; the 1 failure is a **cosmetic import reformat**, not a seam loss | **BUMP WITH CARE** (this week's green-light candidate) |
| **Odysseus** | `25c9e73` (motdeck.yaml says "main" — **it is not on main**) | `dev` HEAD `c436930` (+44 commits) | **MEDIUM** — every *runtime* seam intact, but **2 contract tests break on file paths** (mcp routes moved; the unpaged history handler was consolidated) | **DEFER 1–2 weeks**; fix the two contract tests first, then bump |
| **VoiceStudio** | `v0.4.2` | **`v0.5.0`** (2026-08-13) | **LOW on contracts** (11/11 pass) / **MEDIUM on install** — huge release, new engines, new deps, uv.lock churn | **DEFER** — not blocking anything; bump when someone will actually sit through a reinstall |
| **Voicebox** | `v0.5.0` | `v0.5.0` — **already current** | none | **NO ACTION** (repo still stale: tag dated 2026-04-25) |
| **llama.cpp** | `b10295` | **`b10427`** (macos-arm64 asset **confirmed present**) | **LOW** — every flag we depend on verified present at b10427 | **BUMP WITH CARE** (second green-light candidate) |
| **mlx-lm** | `0.31.3` | `0.31.3` — current | none | **NO ACTION** |
| **mlx-vlm** | `0.6.10` | **`0.6.13`** | **LOW** — server arg surface changed **additively only** | **BUMP** (lowest-risk item in the sweep) |
| **mlx-audio** | `0.4.7` | **`0.4.8`** | **LOW — and I can prove it**: `tts/generate.py` and `stt/generate.py` are **byte-identical** between the two, so `CLI_PARITY_KWARGS` is unchanged | **BUMP WITH CARE** — see the loud note below |
| **mlx-whisper** | `0.4.3` | `0.4.3` — current | none | **NO ACTION** |
| **bun** | `bun-v1.3.14` | `bun-v1.3.14` — current | none | **NO ACTION** |
| **uv** | `0.12.3` | `0.12.4` | trivial (installer-script pin only) | **DEFER** — zero value, costs a verification cycle |
| **imageio-ffmpeg** | `0.6.0` | `0.6.0` — current | none | **NO ACTION** |
| **SearXNG** | `main` (a **branch**, not a commit) | `master` HEAD `094c33d` | **doctrine gap, not a bump** | **NO BUMP — fix the pin instead** (see note) |

---

## Per-component notes

### 1. Hermes — `v2026.7.30` → `v2026.8.13` — **BUMP WITH CARE**

**Available:** `v2026.8.3` and `v2026.8.13`. **2565 commits** in the range (a fortnight of very
heavy upstream activity — this is the fastest-moving thing we vendor).

**What I actually verified (ran `test_hermes_ws_contract.py` + `test_seam.py` against a real
`v2026.8.13` checkout):** **13 passed, 1 failed.**

The single failure is **cosmetic and I confirmed the seam is intact**:

```
assert "from tools.approval import request_tool_approval" in plugins
```

At `v2026.8.13` `hermes_cli/plugins.py:5884` reformats that to a parenthesised multi-line import:

```python
from tools.approval import (
    request_tool_approval,
    ...
)
```

`resolve_pre_tool_block` still exists (L5851) and still **calls** `request_tool_approval` (L5900).
The path-guard escalation path is unbroken. **The fix is to the TEST, not the code** — widen it to
assert `"request_tool_approval" in plugins` plus `"def resolve_pre_tool_block"` (both already
asserted separately), or match `from tools.approval import\s*\(?` with a regex. This is a good
outcome for the pin-bump gate: it fired exactly where it was supposed to and cost one read.

Everything else we depend on is present and unchanged at the candidate:

- **Launch line** `hermes dashboard --no-open --skip-build --host 127.0.0.1 --port 9119` — all four
  flags present. `--port`/`--host`/`--insecure`/`--skip-build` moved into a shared
  `_add_server_runtime_args()` used by both `dashboard` and `serve`; `--no-open` is still a real
  flag on `dashboard` (only the `serve` copy is `argparse.SUPPRESS`). ⚠️ **Watch-item:** a
  now-hidden `--tui` compat shim exists with a comment saying it is "safe to delete once the floor
  app version is well past 0.16.0" — evidence that upstream *does* prune dashboard flags. Our
  contract test already pins `--no-open`/`--skip-build`, which is the right guard.
- **`/api/ws` gateway** — all 8 JSON-RPC methods (`session.create/list/history/resume/delete/close`,
  `prompt.submit`, `approval.respond`) and all 9 events (`message.delta`, `reasoning.delta`,
  `thinking.delta`, `tool.start`, `tool.complete`, `approval.request`, `message.complete`,
  `status.update`, `gateway.ready`) still registered/emitted. `HERMES_DASHBOARD_SESSION_TOKEN`,
  `ws.query_params.get("token"`, `X-Hermes-Session-Token` all present.
- **Approval protocol** — `_emit_approval_request`, `payload["choices"]`,
  `_redact_approval_command`, `params.get("choice"/"all")`, `resolve_gateway_approval`,
  `is_interrupted()` all present. **`approvals.mode` default is still `"smart"`** — the fact Debi
  set it to `manual` in Hermes Config is user state and survives (it is in `~/.hermes/config.yaml`).
- **`pre_tool_call` hook** — still in `VALID_HOOKS`; directive vocabulary `block`/`approve` +
  `message` + `rule_key` unchanged.
- **`mcp_servers` config shape** — `server_config["url"] = url`, `config.setdefault("mcp_servers", …)`
  unchanged, so the Browse/voice toggle's yaml round-trip is safe.
- **Loopback ⇒ no auth** — `should_require_auth()` unchanged (loopback → False).
- **`HERMES_DESKTOP=1` desktop cron ticker** — `_start_desktop_cron_ticker` still gated on the env
  var at `web_server.py:243`. Our cron keeps working.
- **`web_dist`** mount unchanged (`HERMES_WEB_DIST` override or `hermes_cli/web_dist`).

**Relevant changes in the range (from commit titles):** a lot of plugin-system work
(`plugin packs`, `classify_api_error` hook, entry-point provider classification fixes), gateway
robustness (drain markers, wake routing, compression exhaustion), several `desktop`-only MCP-consent
features (`setup_mcp` card — desktop surface, not ours), and `image.generate` / `profiles.list` /
`profiles.create` new WS RPCs (additive). Nothing named a removal on our seams.

**Bump sequence (isolated ship — do nothing else in the same pass):**

```bash
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck"
git -C vendor/hermes reset --hard                 # upstream files only; mode-flip/dirty guard
git -C vendor/hermes fetch --tags origin
git -C vendor/hermes checkout v2026.8.13
#  edit motdeck.yaml: components.hermes.pin: v2026.8.13
#  edit bridge/contract_tests/test_hermes_ws_contract.py L220 → widen the import assertion
python3 -m pytest bridge/contract_tests/ -q       # MUST be green before anything else
./scripts/install_component.sh hermes --yes       # rebuilds venv deps + web_dist (npm)
./scripts/ship.sh
```

**Verify:** dashboard loads on :9119 · a Hermes-lane chat streams in the panel (proves `/api/ws`) ·
a dangerous command shows the **approval card** and `Once` works (proves `approval.request` +
`approval.respond`) · a `write_file` outside the workspace shows the **path-guard card** (proves
`pre_tool_call` → `request_tool_approval`) · `./scripts/test_hermes.sh` = PASS · cron still fires.

**Rollback:** `git -C vendor/hermes checkout v2026.7.30` + revert motdeck.yaml pin +
`./scripts/install_component.sh hermes --yes`. (Reverting the contract-test widening is optional —
the widened assertion passes at both tags.)

---

### 2. Odysseus — `25c9e73` → `dev@c436930` — **DEFER** (and fix a factual error in motdeck.yaml)

**🔴 FINDING, independent of any bump: our pin is NOT on `main`.**
`motdeck.yaml`'s comment and CLAUDE.md both describe the pin as `main@25c9e73`. Measured:

```
origin/main  cf4e240  2026-07-23  "Merge verified Odysseus fixes"     ← STALE, 3 weeks old
origin/dev   c436930  2026-08-14  (repo default branch / HEAD)        ← the live branch
our pin      25c9e73  2026-07-30  fix(email): open settings after OAuth callback (#5803)

merge-base --is-ancestor 25c9e73 origin/main  → NO
merge-base --is-ancestor 25c9e73 origin/dev   → YES
```

So we are pinned to a **`dev` commit**, `main` is a stale side branch that is *behind* us, and the
repo's default HEAD is `dev`. This is fine operationally (the pin is a commit SHA, which is what
matters) but the **comment is wrong and would mislead the next bump**. Upstream itself confirms
`main` is the odd one out: `f06a0a3 fix(session): restore session URL hash writes (removed in
cf4e240a)` — i.e. a fix *undoing* something main introduced. **Correct the comment to
`dev@<sha>` whether or not we bump.**

**Candidate is only 44 commits ahead** — modest, mostly `fix(...)`. But two of them touch us:

**(a) `c00ef8f refactor(routes): move mcp domain into routes/mcp/ subpackage (#5899)`**
`routes/mcp_routes.py` is now a **17-line `sys.modules` shim** (identical idiom to the earlier
search-routes refactor); the real code is `routes/mcp/mcp_routes.py`.
→ **Runtime is FINE** (we talk HTTP; `POST/DELETE /api/mcp/servers` verified present at
`routes/mcp/mcp_routes.py:158/356`, `APIRouter(prefix="/api/mcp"` L21, `transport == "http"` L181,
`"url": srv.url,` L143).
→ **`test_seam.py::test_odysseus_mcp_register_form_contract` WILL FAIL** — it greps the shim.
Fix: point it at `routes/mcp/mcp_routes.py`, or better, at *whichever of the two paths exists*.
Same class of change likely coming for `document`/`webhook`/`vault` (already moved) — worth making
the test resolve the module rather than a literal path.

**(b) `d449a9d fix(history): defer full transcript hydration to model sends (#5929)`**
The duplicate unpaged `GET /history/{sid}` in `session_routes.py` is **gone**; the canonical handler
is now `@router.get("/api/history/{session_id}")` in `routes/history/history_routes.py:140`, and it
gained optional `limit`/`offset`.
→ **Our seam survives — but only because we never pass `limit`.** With `limit=None` the handler
takes the in-memory branch, which emits full `metadata` (incl. `_db_id`), and its DB fallback uses
`_db_history_entry()` which parses `m.meta_data` JSON (also carrying `_db_id`, stamped by
`core/session_manager.py:150/165/285/381`). **If anything ever passes `limit`, the paged branch is
capped at 100 rows** — CLAUDE.md's standing "never pass limit/offset" rule is now load-bearing in a
second way.
→ **`test_odysseus_msg_contract.py::test_unpaged_history_returns_metadata` WILL FAIL** — it asserts
the old literal `@router.get("/history/{sid}")` and
`{"history": [msg.to_dict() for msg in session.history]}` in `session_routes.py`. Both need
rewriting against the new file, and the new test should additionally pin that **`limit is None`
takes the metadata-preserving branch** — that is the actual invariant.

**Everything else verified present on `dev`:** `/api/chat_stream` + `_explicit_web_intent` (assigned,
`chat_routes.py:928`) · `/api/chat/stop` · `POST /session/{sid}/inject_messages` (L539) ·
`delete-messages` (L279) · `edit-message` (L342) · `truncate` (L247) · `fork` (L592) ·
`GET /sessions` (L221) · `POST /session` (L330) · `PATCH /session/{sid}` (L461) ·
`POST /session/{sid}/delete` (L571) · `POST /api/auth/login` (L138) ·
`GET/POST /api/auth/features` (L667/672) + `/settings` (L688/699) · `GET /api/tools` +
`POST /api/tools` (`model_routes.py:2696/2710`) · `GET /api/search/providers` ·
`X-Frame-Options` (`core/middleware.py:102/108`) · seed deps `core.database.ModelEndpoint` (L520),
`get_db_session` (L2583), `src.settings.load_settings/save_settings` (L232/250).
**5 of 7 `test_odysseus_msg_contract` tests pass unchanged.**

**Why defer:** the value in those 44 commits is almost entirely upstream-internal (email/calendar
serialisation, Windows shell, frontend perf, gallery/MPS). Nothing in it fixes a problem we have.
Against that, it costs two contract-test rewrites and a reinstall. **Do it as its own slice when
someone is going to sit and verify chat + sessions properly — not bundled with anything.**

**Bump sequence (when the time comes):**

```bash
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck"
git -C vendor/odysseus reset --hard                # upstream rewrites scripts/odysseus-* at runtime
git -C vendor/odysseus fetch origin dev
git -C vendor/odysseus checkout c4369305f01417b2b02cb06dfa1d8ba8c963762f
#  motdeck.yaml: components.odysseus.pin: c436930…  + FIX THE COMMENT to say dev@, not main@
#  bridge/contract_tests/test_seam.py           → routes/mcp/mcp_routes.py (or resolve either path)
#  bridge/contract_tests/test_odysseus_msg_contract.py → history_routes.py:140 + pin "limit is None"
python3 -m pytest bridge/contract_tests/ -q
./scripts/install_component.sh odysseus --yes
./scripts/ship.sh
```

**Verify:** Agent-mode chat replies **with web sources** (chat_stream + search) · session
create/rename/delete/duplicate from the rail (inject_messages + fork) · per-message
copy/edit/delete/fork (`_db_id` present ⇒ the actions are not greyed out) · Capabilities panel
loads (features+settings) · Browse toggle on/off (MCP add/remove) · Hermes tab still frames.

**Rollback:** `git -C vendor/odysseus checkout 25c9e735ef5ce605f47f8f666ac6689056d2c10c` + revert
the pin + reinstall. ⚠️ The contract-test edits must be reverted too if you roll back — the new
assertions do **not** pass at `25c9e73` (the mcp file moved *into* the subpackage in the range).

---

### 3. VoiceStudio — `v0.4.2` → `v0.5.0` — **DEFER**

**All 11 of `test_voicestudio_contract.py` PASS against a real `v0.5.0` checkout.** Every seam we
recorded holds: port 3900 default (`main.py:1540`), `OMNIVOICE_BIND_HOST` defaulting to `127.0.0.1`
(L1549), `OMNIVOICE_PORT`, `_EXIT_PORT_IN_USE = 78` (L1538, `EX_CONFIG`), `/health`, the
`app.mount("/mcp")` + `streamable_http_path` root trick, the MCP tool names, `OMNIVOICE_API_URL`
callback base, the `X-OmniVoice-Client-Id` header, and the `TRANSLATE_BASE_URL/MODEL/API_KEY`
triplet with `resolve_base_url`/`resolve_model`/`stored_active_provider_id`.

**Why defer anyway — this is a big, wide release, not a patch.** From its own `CHANGELOG.md`:

- **Renamed** OmniVoice-Studio → VoiceStudio; **the GitHub repo moved to `debpalash/VoiceStudio`**
  (our clone URL is already the new one, so no action). Data dir, bundle id and env prefix all
  deliberately unchanged — which is why our contract tests still pass.
- New **Model Catalogue** workspace, **remote GPU workers** (a whole control-plane feature with
  certificate-pinned TLS and a new port 7443), **IndexTTS 2.5 sidecar**, **PocketTTS (Kyutai)**,
  crash-isolated TTS sidecar, invisible watermark toggle (**on by default**), Wayland dictation fixes.
- ⚠️ **"Server mode is locked down: admin actions require an API key (#1525)."** I checked: the gate
  is `OMNIVOICE_API_KEY` and it applies to **non-loopback clients only** (`backend/main.py:1195`,
  `backend/core/auth.py:71`). **Our loopback tab is unaffected.** Good, but it is the kind of change
  that goes the other way next release.
- `requires-python >= 3.11` and the `setuptools>=75,<80` cap (for whisperx's `pkg_resources`) are
  **both unchanged** — so the fat-wheelhouse constraint story does not move.

**The real cost is the reinstall**: `uv sync --frozen` against a substantially rewritten `uv.lock`
plus a `bun` SPA rebuild, on a component that already costs ~5–8 GB of venv. That is a
"sit-and-watch-it" operation, and the new capabilities (remote GPU, dubbing UX) are not things we
consume — we point a webview at it. **Bump when Debi wants the new engines, not on a schedule.**

**Bump sequence:**

```bash
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck"
git -C vendor/voicestudio fetch --tags origin
git -C vendor/voicestudio checkout v0.5.0
#  motdeck.yaml: components.voicestudio.pin: v0.5.0
python3 -m pytest bridge/contract_tests/test_voicestudio_contract.py -q
./scripts/install_component.sh voicestudio --yes     # uv sync --frozen + bun build; SLOW
./scripts/ship.sh
```

**Verify:** the VoiceStudio tab loads the SPA · `/health` green from the card · a TTS render works ·
the voice MCP toggle still registers into Odysseus + Hermes · the runner wiring (`TRANSLATE_*`)
still points at :6767.
**Rollback:** `git -C vendor/voicestudio checkout v0.4.2` + revert pin + reinstall (the venv is
rebuilt from the old lock, so this is clean).

---

### 4. Voicebox — `v0.5.0` — **NO ACTION, already current**

Newest tag is `v0.5.0` (annotated tag `db56013` → commit `2bcb98d`, **2026-04-25**). Our pin is that
tag. The default branch has moved on (`HEAD 51f49de`) but **no newer tag exists**, and our doctrine
is tags-only for this component. The repo remains as stale as recorded in July. Nothing to do; the
five `--no-deps`/git-URL pip hacks stay exactly as fragile as they were.

---

### 5. llama.cpp — `b10295` → `b10427` — **BUMP WITH CARE**

**132 commits** in the range. **`b10427` has the `llama-b10427-bin-macos-arm64.tar.gz` asset**
(HTTP 302 to the CDN; a bogus tag and a bogus filename both return 404, so the check discriminates).
The CI-lag trap that forced `b10094`/`b10295` did **not** bite here — the newest four tags
(`b10424`–`b10427`) all have the asset.

**Every flag we depend on, verified in the `b10427` source (blob-less sparse clone of
`common/` + `tools/tts`):**

| Flag | Where | Status |
|---|---|---|
| `-a, --alias` | `common/arg.cpp:2966` | present (this is what makes the runner's registry id work) |
| `--repeat-penalty` | `common/arg.cpp:2080` | present (repetition guard) |
| `--spec-type` | `common/arg.cpp:4139`, values from `common_speculative_all_types_str()` | present; `COMMON_SPECULATIVE_TYPE_DRAFT_MTP` still an enum member |
| `llama-tts -m / -mm / -p / -o` | `tools/tts/tts.cpp:37` usage line | present, unchanged shape |
| `--tts-lang` | `common/arg.cpp:4317` | present |
| `--tts-speaker-file` | `common/arg.cpp:4325` | present |
| `-mv` / `--vocoder-model` | — | **still ABSENT** (our contract test asserts absence — still correct) |

**Three changes worth knowing about:**

1. **`f65e568f common : auto-detect spec type from draft GGUF metadata (#26814)`** — llama.cpp can
   now infer the spec type from the draft model's metadata. Our explicit `--spec-type draft-mtp`
   still wins (`spec_types_is_default()` only auto-picks when the user set nothing), so this is
   **compatible and possibly a net win**: it may fix MTP for repos our id-or-repo substring
   heuristic misses. The self-healing "strip SPEC_ARGS and relaunch" retry in
   `start_component.sh` is unchanged insurance either way.
2. **`217df17a mtmd: stop feeding the text stream again during Qwen3-TTS generation (#26706)`** —
   a real fix in the exact `llama-tts` path we use for `tts-gguf`. Argues *for* the bump.
3. ⚠️ **`8e7f22b6 common: add system-level config file (#26118)`** — **new implicit config surface.**
   `common_params_apply_system_config()` (`common/arg.cpp:717`) now reads
   `/etc/llama.cpp/config.ini` then `${XDG_CONFIG_HOME:-~/.config}/llama.cpp/config.ini` **if they
   exist**, applying them *before* env and CLI (so our argv still overrides). On Debi's Mac neither
   file exists → **no-op today**. But it means llama-server's behaviour is no longer determined by
   our argv alone. Recording it as a watch-item; not a blocker.

**Bump sequence:**

```bash
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck"
cp -R data/llamacpp data/llamacpp.b10295.bak     # install_llamacpp.sh OVERWRITES — no auto-backup
#  motdeck.yaml: runner.llamacpp_pin: b10427   (+ update the CI-lag comment: b10427 asset verified)
./scripts/install_llamacpp.sh                     # downloads + relocates + prints --version
python3 -m pytest bridge/contract_tests/test_llama_tts_contract.py -q   # runs --help on the Mac
./scripts/ship.sh
```

**Verify:** Runner starts and a gguf chat streams (proves `--alias`, since the direct lane sends the
registry id) · no `C-C-C` repetition loop (proves `--repeat-penalty` still applied) · an MTP gguf
still loads, and if the spec flags fail the log shows the strip-and-retry warning rather than a dead
runner · Models → Audio → a `tts-gguf` model → **▶ speak produces a non-empty wav** (proves
`llama-tts -m/-mm/-p/-o`).
**Rollback:** re-pin `b10295` and re-run `./scripts/install_llamacpp.sh`, or
`rm -rf data/llamacpp && mv data/llamacpp.b10295.bak data/llamacpp`.
⚠️ **`install_llamacpp.sh` keeps no backup of its own** — the `data/llamacpp.b10094.bak` from the
July bump was made by hand. Take the copy first; that is the whole rollback.

---

### 6. MLX Python pins

All four are read from `motdeck.yaml` `build.*` by `scripts/install_mlx.sh` (single source of truth —
it hard-errors if any is missing), and installed as one `uv pip install` line, so they bump together.

#### mlx-audio `0.4.7` → `0.4.8` — **BUMP WITH CARE, but the parity fear is measured and clear**

**🔊 THE LOUD PART, resolved rather than assumed:** the doctrine says `CLI_PARITY_KWARGS` in
`bridge/voice_worker.py` **must be re-derived on any mlx-audio bump**, because `generate_audio()`'s
Python defaults differ from the CLI's argparse defaults (`max_tokens` `1200` vs `None`, `voice`
`"af_heart"` vs `None`) and a drift there means **silently wrong audio**, not an error. I did the
re-derivation the cheapest sound way — sdist-to-sdist:

```
md5  mlx_audio/tts/generate.py   0.4.7 == 0.4.8   (3c06956e96925b41f90dcd50692896f3)
md5  mlx_audio/stt/generate.py   0.4.7 == 0.4.8   (8e931fee7b127a4a7e4fff0d711366f5)
diff -rq mlx_audio/tts/models/omnivoice   0.4.7 vs 0.4.8   →  IDENTICAL
```

**Both CLI entry points are byte-identical**, so the argparse default dict — which is what
`CLI_PARITY_KWARGS` mirrors — **cannot have changed**, and `generate_audio`'s signature lives in the
same unchanged file. The Parakeet STT argv (`--model/--audio/--output-path/--format json`) and the
whole `omnivoice` family are untouched. **This bump does not require re-deriving the parity dict** —
but the *rule* stands for every future bump, and the check above is the two-minute way to discharge it.

**What did change (0.4.8 is a resampling-quality release):** a new `mlx_audio/resample.py` replaces
the scipy-based `resample_poly` path in `utils.py`; `audio_io.py` gains a streaming
`_decode_miniaudio_downsampled()` that pushes native-rate PCM through the new FIR in 1-second chunks;
`dsp.py`, `convert.py`, `kokoro/istftnet.py`, `kitten_tts/istftnet.py`, `qwen3_tts/qwen3_tts.py` and
`whisper.py` all changed, plus a new `test_istftnet_fidelity.py`. New `nemotron_voicechat` codec.
**Declared dependencies are unchanged** (diffed `pyproject.toml`).

⚠️ **The honest risk is audio, not API**: istftnet is the Kokoro/kitten vocoder and the resample path
feeds every reference clip. Output *should* improve (that is the stated intent), but **our OmniVoice
cloning path and the reference-clip pipeline are exactly what the changed code touches**. The
`RenderCache` key does **not** include the engine version, so **cached renders from 0.4.7 will keep
being served after the bump** — which is arguably fine (the bytes are still valid audio) but means
an A/B needs a fresh text or a bridge restart. Worth one line in the bump note.

#### mlx-vlm `0.6.10` → `0.6.13` — **BUMP** (lowest risk in the sweep)

Server package arg surface changed **additively only**: `+--kv-key-bits`, `+--kv-value-bits`,
`+--kv-key-scheme`, `+--kv-value-scheme`, `+--max-num-seqs`. **No removals.** `requirements.txt`
identical. New models (`cohere_compass`, `minimax_h3`, `muse_glimmer`), new `kv_quant.py`, new
`generate/video_generation.py`. Our launch (`mlx_vlm.server --model … --host … --port …`) is unaffected.

#### mlx-lm `0.31.3` and mlx-whisper `0.4.3` — **NO ACTION, both are PyPI latest.**

Note `mlx` itself is at `0.32.0`, which is what the venv already has. Also worth recording:
**mlx-whisper declares `torch` as a hard dependency** (the resolved "torch mystery" from the July
QA) — that has not changed and remains an accepted ~2 GB cost isolated to `data/mlx-venv`.

**Bump sequence (all MLX pins move together):**

```bash
#  motdeck.yaml build.*:  mlx_vlm_pin: "0.6.13"   mlx_audio_pin: "0.4.8"
#                         (mlx_lm_pin / mlx_whisper_pin unchanged)

# ⚠️ RUN FROM THE SNAPSHOT, NOT THE REPO — the fat app uses the snapshot's venv.
# This is the exact 2026-08-08 ops gap that cost a debugging session.
cd ~/Library/Application\ Support/MOT Deck && ./scripts/install_mlx.sh
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck" && ./scripts/install_mlx.sh   # keep the repo venv in step
python3 -m pytest bridge/contract_tests/test_mlx_audio_stt_contract.py \
                  bridge/contract_tests/test_mlx_whisper_contract.py -q
./scripts/ship.sh
```

**Verify:** an MLX chat model loads and streams (mlx-lm, untouched — regression check only) · a
vision MLX model answers about an image (mlx-vlm) · **▶ speak on an OmniVoice model with a pinned
clip renders in the same voice** and the bridge log shows a `[voice] render …s` line (mlx-audio +
the resident worker + `CLI_PARITY_KWARGS`) · the `auto` chip transcribes with Parakeet **and** with
whisper-base (both STT engines still selectable).
**Rollback:** revert the two `build.*` values and re-run `install_mlx.sh` in **both** locations — the
pins are exact `==`, so the downgrade is deterministic.

---

### 7. bun / uv / imageio-ffmpeg

- **bun `bun-v1.3.14`** — latest tag. **No action.**
- **uv `0.12.3` → `0.12.4`** — a patch. `build.uv_pin` only feeds the
  `https://astral.sh/uv/<ver>/install.sh` URL in `firstrun.sh` for the fresh-Mac path we have not
  exercised in months. Bumping buys nothing and costs a verification cycle. **Defer** — fold it into
  the next fat-installer rebuild, which is when it actually matters.
- **imageio-ffmpeg `0.6.0`** — latest. **No action.** (Still ships `ffmpeg` only, **no `ffprobe`** —
  the recorded limit is unchanged, and it is why the starter-voice degrade and the clip-trim guard
  are written the way they are.)

### 8. SearXNG — **not a bump; a pin-doctrine gap**

`components.searxng.pin: main` is a **branch name**, not a commit. `test_seam.py` only asserts the
pin is truthy, so `"main"` passes the gate while giving us none of what the gate exists for: a fresh
`install_searxng.sh` on a new machine gets whatever `master` is that day (currently `094c33d`), and
there is **no recorded commit to roll back to**. Upstream's default branch is `master`, so the
`main` value is additionally likely resolving only by GitHub's symref courtesy.

**Recommendation (a 5-minute fix, not a bump):** on the Mac, read the commit the working clone is
actually on and write *that* into `motdeck.yaml`:

```bash
git -C vendor/searxng rev-parse HEAD     # → pin this exact sha
```

and tighten `test_seam.py` to reject `main`/`master`/`HEAD` as a pin value the way
`test_voicebox_contract.py` already does (`comp["pin"] not in ("main", "master")`). That test exists
for voicebox and voicestudio and simply was never extended to searxng. No reinstall needed — this
records reality rather than changing it.

---

## What I would green-light this week

**Two, and I would ship them as two separate passes, not one:**

1. **mlx-vlm `0.6.10` → `0.6.13` + mlx-audio `0.4.7` → `0.4.8`** — one `install_mlx.sh` run. The
   parity risk that makes mlx-audio scary is **measured away** (both CLI entry points byte-identical,
   `omnivoice/` identical), and mlx-vlm is purely additive. Smallest blast radius, fully reversible
   by exact-version downgrade, and it clears the "are we behind on MLX?" question for a month.
2. **Hermes `v2026.7.30` → `v2026.8.13`** — 13/14 contract asserts already pass at the candidate and
   the one failure is a reformatted import that I have already read the fix for. Do it **alone**,
   because it is the component whose failure mode is a silent lane outage, and because the reinstall
   rebuilds `web_dist`.

**Everything else: hold.** llama.cpp `b10427` is *safe* (I verified every flag) but it buys us one
TTS fix and an MTP auto-detect we already work around — I would queue it right behind Hermes rather
than in the same week, so a `[voice] render` regression has only one candidate cause. Odysseus and
VoiceStudio both want a contract-test edit or a long reinstall respectively, for value we are not
currently asking for.

## Biggest caution

**The Odysseus pin is not where our own manifest says it is.** `motdeck.yaml` and CLAUDE.md both
describe `25c9e73` as `main`; it is on `dev`, and `main` is a stale branch that sits *behind* us and
contains at least one change upstream later reverted (`cf4e240a`). The next person to bump
"Odysseus to latest main" would **silently move us backwards by three weeks** and re-introduce
whatever `f06a0a3` fixed — and every contract test would pass while they did it, because the
seams they grep for exist on both branches. Fix the comment before anyone touches that pin.

The runner-up caution is narrower but sharper: on the Odysseus `dev` branch, **`GET /api/history/{sid}`
now caps at 100 rows the moment a `limit` parameter appears**. Our bridge's long-standing "never
pass limit/offset" rule was previously about getting `metadata._db_id` from the unpaged handler;
after `#5929` it is *also* the only thing standing between us and silently truncated transcripts.
That deserves an explicit assertion in the contract test rather than a comment in a memory file.
