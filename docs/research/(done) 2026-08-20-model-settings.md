# Model settings — what's tunable, what LM Studio exposes, and what we should surface

**Research report, 2026-08-20. Opus 5 research agent to a Fable brief. NO code was changed.**
Debi's ask (paramount): *"re-work models — research what's tunable for models, what settings models can
have, what settings LM Studio has. Surface those settings for our models. Tighten them."*

Everything about our own stack below is read out of the tree at today's pins and cited `file:line`.
The llama-server request surface is **verified empirically against our own pinned binary** (symbol
extraction from `data/llamacpp/build/bin/libllama-server-impl.dylib`, b10427) rather than from docs.
LM Studio claims carry URLs. Uncertainty is flagged inline with ⚠️.

---

# PART 0 — RECOMMENDED SPEC (read this first)

## 0.1 The three headline findings that shape everything

**(1) We currently send ZERO sampling parameters, anywhere.** The direct lane's request body is
exactly `{model, messages, stream, cache_prompt, stream_options}` — `bridge/app.py:3574-3576`. No
temperature, no top_p, no max_tokens. Every generation in the harness therefore runs on
*whatever the engine's own defaults are*, and those defaults differ wildly per engine (§1.4).

**(2) There IS one sampling decision already made — and it is a buried constant.** `scripts/start_component.sh:225-227`
appends `--repeat-penalty 1.1 --repeat-last-n 256` to every llama-server launch, added 2026-08-06 to
stop gemma-31B IQ4 degenerating into `C-C-C-…` loops. It is invisible, global, un-overridable, and
**not applied to the aux runner** (`bridge/app.py:2425-2429` builds its own argv without it). Making
this a visible, per-model, editable default *is* the concrete meaning of "tighten them".

**(3) There is a live truncation bug on the MLX path.** `mlx_lm.server`'s `--max-tokens` default is
**512** (`data/mlx-venv/…/mlx_lm/server.py:1838-1843`) and it is used as the request default when the
body omits `max_tokens` (`server.py:1169-1173`). Our direct lane omits it. So **every reply from an
MLX text model is silently cut at 512 tokens.** (`mlx_vlm.server`'s default is 2048 —
`mlx_vlm/generate/dispatch.py:50` — so vision MLX is cut at 2048.) llama.cpp is unaffected: its
`-n/--predict` default is `-1` = infinity. Whatever else this slice does, **the direct lane must
always send an explicit `max_tokens`.**

## 0.2 Storage shape

Add ONE optional key per registry entry in `data/models.json`:

```json
{
  "id": "gemma-4-31B-…-q4_k_m",
  "format": "gguf", "path": "…", "ctx": 95536,
  "settings": {
    "launch":   { "ctx": 65536, "cache_type_k": "q8_0", "cache_type_v": "q8_0",
                  "flash_attn": "auto", "mlock": false, "batch": 2048, "ubatch": 512 },
    "sampling": { "temperature": 0.7, "top_p": 0.95, "top_k": 40, "min_p": 0.05,
                  "repeat_penalty": 1.1, "repeat_last_n": 256, "max_tokens": 4096 }
  }
}
```

Why the registry and not `harness.yaml`:
- it is already the per-model home for user decisions (`voice`, `ref_audio`, `ref_text`, `hidden` —
  `scripts/seed_registry.py:515`), and `_registry_update()` (`bridge/app.py:3011-3042`) is an
  existing atomic writer with the right semantics (a `None` patch value **removes** the key, so
  "reset to default" = absence, not a stored null — exactly the grammar the voice picker already uses).
- `harness.yaml` is written by a **line-scan scalar** writer (`_set_yaml_scalar`, `bridge/app.py:1792-1798`)
  that deliberately cannot express nested maps, and `ship.sh`'s manifest merge is additive at the top
  level only. A per-model settings tree does not belong there. (Same reasoning that put the voice
  folder list in `data/voice_folders.json`.)

⚠️ **THE RESCAN TRAP — this must be in the spec or the feature silently deletes itself.**
`merge()` replaces every entry whose source is in `RESCANNED_SOURCES` (`local`, `jan-import`,
`lmstudio-import`, `audio-hf-cache` — `seed_registry.py:507`) with a fresh disk scan; only
`USER_KEYS` survive (`:515`, carried by `_keep_user` `:532-541`). **`settings` must be added to
`USER_KEYS`**, or one Rescan click wipes every tuned model. Two sharp edges in `_keep_user`:
- it carries the value **wholesale** (`dict(entry, **add)`), so a nested `settings` dict is
  preserved atomically — acceptable, but it means there is no per-key merge if a future scan ever
  learns a settings key.
- its guard is `v not in (None, "", False)`, so an **empty `settings: {}` is dropped**. Harmless
  (empty = no overrides = the intended state), worth knowing.

⚠️ **`ctx` is a pre-existing special case.** It already lives at the top level of the entry
(`seed_registry.py:551-586` carries it forward for `local` entries *only*, and only when the fresh
scan's value is null). If `ctx` becomes user-editable it now has two homes. **Recommendation:
keep `ctx` where it is** (top-level `entry["ctx"]`, which `start_component.sh:89-91` and
`aux_start` already read) and do NOT duplicate it into `settings.launch`; instead add `ctx` to
`USER_KEYS` so a rescan of a `download`-sourced model can't lose a hand-set value either.

## 0.3 The class split — LAUNCH vs REQUEST

The split is real but **engine-dependent**, and this is the single most important thing for the UI
to get right, because getting it wrong means a slider that silently does nothing.

| Class | Meaning | Applied by | Takes effect |
|---|---|---|---|
| **LAUNCH** | argv of the server process | `start_component.sh` (runner) / `aux_start` (aux) | on the next model load — **UI must say "needs reload"** |
| **REQUEST** | fields in the chat-completions body | `bridge/app.py` direct lane | immediately, next turn |

LAUNCH class (both engines): `ctx-size`, KV cache quant (`-ctk/-ctv`), `flash-attn`, `mlock/mmap`,
`batch/ubatch`, RoPE scaling, `parallel`, draft/spec model, chat template, `mmproj`.

REQUEST class: the whole sampling suite + `max_tokens` + `seed` + `stop` + grammar/json_schema.

⚠️ **The trap: in llama.cpp every sampler is BOTH.** The CLI `--temp/--top-k/--repeat-penalty/…`
set the *server-wide default* that a request inherits when it omits the field. So our
`--repeat-penalty 1.1` is a launch-time **default**, not a lock — a request body carrying
`repeat_penalty` overrides it. **Recommendation: put samplers in the REQUEST class only** and stop
passing them on argv (or keep argv as a belt-and-braces floor for surfaces we don't own — Hermes and
Odysseus, §0.4 — and document it as exactly that). Doing both without saying which wins is how this
gets confusing.

⚠️ MLX asymmetry: `mlx_lm.server` also takes `--temp/--top-p/--top-k/--min-p/--max-tokens` as
request defaults (`server.py:1174-1179` read `cli_args.*`), but has **no `--ctx-size` at all** —
context comes from the model config. So "context length" is a LAUNCH control for gguf and simply
**does not exist** for mlx-lm. The UI must hide it, not grey it out with a lie.

## 0.4 Lane mapping — and the honesty problem

This is the part Fable must decide, because two of our three lanes structurally cannot honour
per-model sampling.

| Setting | DIRECT lane | AGENT lane (Odysseus) | HERMES lane |
|---|---|---|---|
| `temperature` | ✅ full control (we own the body) | ⚠️ only via the **global, admin-only** `custom` preset (`vendor/odysseus/src/preset_manager.py:56-59`, route `routes/preset_routes.py:33-50`) | ❌ **impossible** — no `model.temperature` key exists and the main-agent path never passes one (`vendor/hermes/agent/transports/chat_completions.py:632-635` reads `params["temperature"]`; no call site supplies it) |
| `max_tokens` | ✅ | ⚠️ same global preset (`max_tokens`, auto-swapped to `max_completion_tokens` for reasoning models, `src/llm_core.py:2225-2227`) | ✅ `model.max_tokens` in `~/.hermes/config.yaml` (`agent/agent_init.py:2209-2231`) |
| `top_p / top_k / min_p / penalties / stop / seed` | ✅ | ❌ never sent (`src/llm_core.py:2215-2245` sends only model/messages/temperature/stream[+max_tokens/tools]) | ❌ only via the `custom_providers[].extra_body` escape hatch |
| `ctx / context_length` | LAUNCH (ours) | ❌ runtime-probed from `/v1/models` (`src/model_context.py:264-331`) | ✅ `model.context_length` |
| reasoning effort | request field (`reasoning_effort` exists in b10427, §1.2) | Mistral-only, env-gated (`src/llm_core.py:2236-2237`) | ✅ `agent.reasoning_effort` + per-model `agent.reasoning_overrides` |

**Consequences, stated plainly:**

- **Per-model sampling is a DIRECT-LANE feature.** Anything else is a partial fan-out. The UI must
  say so — the precedent is the toolset lever's "controls the harness chat lane" honesty.
- **Because LAUNCH-class settings live in argv, they apply to ALL THREE lanes** (every lane hits the
  same `:6767` process). So context/KV-quant/flash-attn genuinely are universal; only *sampling* is
  lane-scoped. That asymmetry is a gift: the two groups the UI wants to draw anyway ("Load" and
  "Sampling") happen to also be the "universal" and "direct-lane-only" groups.
- **Writing `model.temperature` into `~/.hermes/config.yaml` would be a SILENT NO-OP.** Nothing reads
  it; `hermes config set` even accepts it without complaint (`hermes_cli/config.py:5084-5089`, because
  `DEFAULT_CONFIG["model"]` is the bare string `""`). Do not build that. ⚠️ Also: Hermes's config
  cache is keyed on `(mtime_ns, size)` (`config.py:3436-3449`), so a same-length overwrite is
  invisible to a long-running gateway; and `model.max_tokens` is snapshotted at **agent init**
  (`agent_init.py:2209`), so an edit only reaches a NEW session.
- **Fanning out to Odysseus's `custom` preset is destructive-by-nature**: it is one global row, it is
  admin-only, and it is what the user's own preset dropdown points at. Writing our per-model
  temperature there would silently retune every Odysseus chat, including ones using a different
  model. ⚠️ **Recommendation: do NOT fan out to Odysseus in v1.** State on the row that the Agent
  lane uses Odysseus's own preset.

**The alternative worth naming (and rejecting for v1):** route the Agent and Hermes lanes through a
bridge-owned OpenAI-compatible proxy that injects our per-model sampling on the way past — this is
literally the shelved "gearbox" (`bridge/gearbox.py`). It would make settings universal in one
stroke. It is also a new hop on the hot path for every turn in the product, and it re-opens a design
Debi shelved. Flag for Fable; do not build unopposed.

## 0.5 Proposed defaults ("tighten them", concretely)

Today's *effective* values, and what to ship as our visible defaults:

**GGUF / llama-server** — engine defaults today (from `data/llama-server.help.txt`): `temp 0.80`,
`top_k 40`, `top_p 0.95`, `min_p 0.05`, `typical_p 1.0` (off), plus **our** `repeat_penalty 1.1`,
`repeat_last_n 256`, and `n_predict -1` (unbounded).

| Field | Proposed default | Why |
|---|---|---|
| `temperature` | **0.7** | llama.cpp's 0.8 is tuned for creative completion; 0.7 is the conventional assistant setting and reduces loop risk on heavy quants |
| `top_p` | 0.95 | = engine default, keep |
| `top_k` | 40 | = engine default, keep |
| `min_p` | 0.05 | = engine default, keep. This is the modern quality lever; leaving it visible is the point |
| `repeat_penalty` | **1.1** | promote today's hidden constant, unchanged, now visible + editable |
| `repeat_last_n` | **256** | same |
| `max_tokens` | **4096** (or `-1`/unbounded, deliberate) | see the MLX bug in §0.1 — the direct lane must send *something* |

**MLX** — engine defaults today: `temp 0.0` (greedy!), `top_p 1.0`, `top_k 0` (off), `min_p 0.0`
(off), `repetition_penalty 0.0` (off — note MLX uses **0.0** as "disabled", not 1.0),
`max_tokens 512` (mlx-lm) / `2048` (mlx-vlm).

| Field | Proposed default | Why |
|---|---|---|
| `temperature` | **0.7** | 0.0 greedy is a surprising default for chat and is a *different* product behaviour from the gguf lane |
| `top_p` | 0.95 | match the gguf lane so switching engines doesn't change the model's personality |
| `top_k` | 40 | ditto |
| `min_p` | 0.05 | ditto |
| `repetition_penalty` | **1.1** | ⚠️ **different scale semantics from llama.cpp's `repeat_penalty`** — same number, different disabled-value. The UI must not present one slider that writes both without translating |
| `repetition_context_size` | 256 | mirrors `repeat_last_n`; MLX's own default is 20 |
| `max_tokens` | **4096** | fixes the 512 truncation |

⚠️ **These are researcher-proposed numbers, not measured.** Only `1.1/256` has evidence behind it
(the 2026-08-06 loop incident). Everything else is convention. A "Sampling" group whose defaults
were never A/B'd should say *"harness defaults"*, not *"recommended"*.

## 0.6 Presets

Three layers, in precedence order — this is LM Studio's shape too (§2.3) and it is the right one:

1. **Engine default** — what the binary does with no flags. Never stored; shown as the greyed
   placeholder in each field.
2. **Harness default per engine** — the §0.5 table. A module-level constant in `bridge/app.py`
   (contract-testable), NOT a file the user edits in v1.
3. **Per-model override** — `entry["settings"]`, written by the Models detail pane. Absence = fall
   through. Per-field **reset** = `_registry_update(mid, {"settings": …})` with that key removed.

A future 4th layer (per-chat override, LM-Studio-preset-style named bundles) is deliberately out of
scope: it needs a session-scoped store the direct lane doesn't have, and Odysseus already proves
that a global preset colliding with per-model defaults needs a conflict resolver (LM Studio ships
one; ours would too). **Recommendation: ship layers 1-3, name layer 4 as the follow-on.**

## 0.7 UI sketch — Models detail pane

Extend `renderDetail()`'s installed branch (`bridge/panel/index.html:7204-7270`) with two collapsed
`▸` groups below the existing `.md-actions` row and above `.md-div`/`.md-path`. Both use the existing
`.cap-row` / `.cap-pill` / `.cap-btn` grammar from the Capabilities page — **zero new CSS** should be
achievable, matching the toolset lever's record.

```
gemma-4-31B-it-uncensored-biproj-q4_k_m
llamacpp · 18.7 GB · 95,536 ctx · local
[ Eject ] [ Set aux ] [ Delete ]

▸ Sampling  ·  3 changed  ·  affects the CHAT lane only
    temperature      [ 0.7  ]  default 0.7          ↺
    top_p            [ 0.95 ]  default 0.95
    top_k            [ 40   ]  default 40
    min_p            [ 0.05 ]  default 0.05
    repeat_penalty   [ 1.15 ]  default 1.1          ↺   ← was a hidden constant until now
    repeat_last_n    [ 256  ]  default 256
    max_tokens       [ 4096 ]  default 4096
    ⓘ Agent and Hermes lanes build their own requests — see the note.
    [ Reset all to harness defaults ]

▸ Load  ·  needs a model reload to take effect
    context           [ 95536 ]  model max 262144
    KV cache K/V      [ q8_0 ▾ ] [ q8_0 ▾ ]   ⚠ V-quant wants flash-attn on
    flash attention   [ auto ▾ ]
    keep in RAM       [ off ]
    batch / ubatch    [ 2048 ] [ 512 ]
    ⚠ 3 changes pending — [ Reload model ]
```

Design notes:
- **Group headers carry the truth**, following the toolset lever precedent: Sampling says *"affects
  the CHAT lane only"*; Load says *"needs a model reload"* and shows a pending-changes count with an
  explicit Reload button (never a silent auto-restart — an unprompted 60-90s model reload is worse
  than a button).
- **Per-field default shown inline + a `↺` reset that only appears when overridden.** A field with no
  override renders its default as placeholder text, so "what is this actually running at" is
  answerable without opening anything.
- **Engine-conditional rendering, not greying.** MLX rows: no `context`, no `flash_attn`, no
  `batch/ubatch`; label the penalty `repetition_penalty` with its own scale. GGUF rows: the full set.
  A control that cannot work must be *absent*.
- **Both groups collapsed by default.** Debi's Models pane works today; this must not become the
  first thing she sees.
- Write path: one new `POST /api/models/settings {id, group, key, value}` → `_registry_update`.
  A `null` value removes the key. Validation bridge-side against a per-engine range table (the
  `min/max` values are known: `mlx_lm/server.py:1229-1251` publishes MLX's, and llama.cpp's are in
  the help dump) — a slider that lets you post `top_p: 5` gets a 400, not a broken turn.

## 0.8 Sequencing recommendation

1. **Fix the MLX `max_tokens` truncation + wire the direct lane to send sampling at all.** This is a
   bug fix and is worth shipping alone.
2. **Promote `repeat_penalty/repeat_last_n` out of `start_component.sh` into the visible default
   table** (and give the aux runner the same treatment — it lacks them today).
3. **Sampling group in the Models pane** (request-class, direct lane, per-model, `USER_KEYS`-protected).
4. **Load group** with the explicit Reload affordance.
5. Named presets / per-chat overrides / any Odysseus-or-Hermes fan-out: separate slices, separate
   decisions.

---

# PART 1 — Our engines: the full tunable surface

## 1.1 llama-server b10427 — LAUNCH flags that matter

Source: `data/llama-server.help.txt`, regenerated on every runner start by
`scripts/start_component.sh:212`. Line refs are into that file.

**Context / memory**
| Flag | Default | Line | Note |
|---|---|---|---|
| `-c, --ctx-size N` | 0 = from model | :25 | we pass registry `ctx` → `harness.yaml ctx_size` → 65536 (`start_component.sh:89-91`) |
| `-n, --predict N` | **-1 = infinity** | :27 | never set by us; contrast MLX's 512 |
| `-b, --batch-size` / `-ub, --ubatch-size` | 2048 / 512 | :29,:31 | |
| `-ctk/-ctv, --cache-type-k/v` | f16 | :75,:79 | `f32 f16 bf16 q8_0 q4_0 q4_1 iq4_nl q5_0 q5_1`. The big VRAM lever |
| `-fa, --flash-attn [on\|off\|auto]` | auto | :39 | |
| `--mlock` / `--mmap,--no-mmap` / `-dio,--direct-io` | off / on / off | :87,:89,:92 | |
| `--swa-full`, `--keep N` | false, 0 | :35,:33 | |
| `-kvu/--kv-unified`, `-np/--parallel` | auto, -1 auto | :415,:433 | **we pin `--parallel 1`** (`start_component.sh:216`) |
| `-cram, --cache-ram N` | 8192 MiB | :411 | **we pass `-1` (no limit)** |
| `--context-shift` | disabled | :423 | **we pass `--no-context-shift`** (redundant at this pin — the default flipped) |
| `-ctxcp, --ctx-checkpoints` | 32 | :404 | |
| `--cache-prompt` / `--cache-reuse N` | enabled / 0 | :541,:543 | prompt-cache reuse via KV shifting |
| `-sps, --slot-prompt-similarity` | 0.10 | :640 | the KV-affinity knob from the old backlog item |
| `-fit, --fit [on\|off]`, `-fitt`, `-fitc` | on / 1024 / 4096 | :134-142 | auto-shrink-to-fit; **we pass `--fit off`** |
| `--sleep-idle-seconds` | -1 disabled | :645 | ⚠️ this is llama.cpp's answer to LM Studio's TTL — unused by us |

**RoPE / long context**: `--rope-scaling {none,linear,yarn}`, `--rope-scale`, `--rope-freq-base`,
`--rope-freq-scale`, `--yarn-*` (:46-67).

**Device**: `-ngl/--gpu-layers` (default **auto**, :117), `-dev/--device`, `-sm/--split-mode`,
`-ts/--tensor-split`, `-mg/--main-gpu`, `-cmoe/--cpu-moe`, `-ncmoe/--n-cpu-moe` (:104-133).
On a unified-memory Mac `-ngl auto` is already right; `-ncmoe` is the interesting one for MoE models
that don't fit.

**Speculative decoding**: `--spec-type` accepts
`none,draft-simple,draft-eagle3,draft-mtp,draft-dflash,ngram-simple,ngram-map-k,ngram-map-k4v,ngram-mod,ngram-cache`
(:359) plus `-md/--model-draft`, `--spec-draft-n-max/-n-min/-p-min/-p-split`, draft KV types
(:216-225), draft `-ngld` (:352). **We use exactly one of ten modes**
(`--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-n-min 0 --spec-draft-p-min 0.75`,
`start_component.sh:245`). ⚠️ The `ngram-*` family needs **no draft model at all** and is a plausible
free speedup on any model — completely unexplored by us.

**Chat / reasoning**: `--jinja` (default **enabled** at this pin, :568), `--chat-template` (with a
50-name builtin list, :595-610), `--chat-template-file`, `--chat-template-kwargs` (:532),
`--reasoning-format {none,deepseek,deepseek-legacy}` (:570), `-rea/--reasoning [on|off|auto]` (:578),
`--reasoning-budget N` (:581), `--reasoning-budget-message` (:584), `--reasoning-preserve` (:587),
`--skip-chat-parsing` (:628), `--prefill-assistant` (:633).
⚠️ `--reasoning-format` is directly relevant to us: our direct lane hand-parses both
`reasoning_content` **and** inline `<think>` tags (`bridge/app.py:3604-3636`) precisely because we
never pin this flag.

**Other**: `-a/--alias` (:460 — we use it, and it is why gguf models accept our registry id as
`model`), `--api-key` (:522), `--metrics` (:547), `--props` (:549), `--slots` (:551),
`--lora`/`--lora-scaled` (:149), `--control-vector` (:154), `--override-kv` (:144).

**What we pass today** (`start_component.sh:214-227`):
`--no-context-shift --host --port --alias --ctx-size --no-cont-batching --cache-ram -1 --fit off
--model --parallel 1 [--mmproj] [--api-key] [--repeat-penalty 1.1 --repeat-last-n 256]`.
So of the launch surface above we exercise ~10 flags of ~80. Notably absent and worth surfacing:
**KV cache quantization** (the single biggest memory-vs-quality lever on a 64 GB box),
**flash-attn** (currently `auto`), **`--reasoning-format`**, and **`-n/--predict`**.

## 1.2 llama-server b10427 — REQUEST-time fields

⚠️ Method note, and this is stronger evidence than a doc citation: the b10427 **source is not in the
tree** (`data/llamacpp` ships binaries only). The list below was obtained by extracting exact-match
JSON key symbols from **our own pinned** `data/llamacpp/build/bin/libllama-server-impl.dylib`. Every
name below is present in that binary; names marked ✗ were tested and are **absent**.

**Sampling** — `temperature`, `top_k`, `top_p`, `min_p`, `typical_p`, `top_n_sigma`,
`xtc_probability`, `xtc_threshold`, `dynatemp_range`, `dynatemp_exponent`, `mirostat`,
`mirostat_tau`, `mirostat_eta`, `adaptive_target`, `adaptive_decay`, `min_keep`, `samplers`
(sampler-chain *ordering*), `seed`.
✗ absent as body keys: `temp` (the CLI's short form), `typ_p`, `dynatemp_exp`.

**Penalties** — `repeat_penalty`, `repeat_last_n`, `presence_penalty`, `frequency_penalty`,
`dry_multiplier`, `dry_base`, `dry_allowed_length`, `dry_penalty_last_n`, `dry_sequence_breakers`.

**Length / stopping** — `n_predict`, `max_tokens`, `max_completion_tokens`, `stop`, `ignore_eos`,
`n_keep`, `t_max_predict_ms`, `n_indent`.

**Constrained output** — `grammar`, `json_schema`, `response_format`, `logit_bias`.

**Introspection** — `logprobs`, `top_logprobs`, `n_probs`, `post_sampling_probs`, `return_tokens`,
`timings_per_token`.

**Plumbing** — `stream`, `stream_options` (+`include_usage`), `cache_prompt`, `tools`, `tool_choice`,
`parallel_tool_calls`, `chat_template`, `chat_template_kwargs`, `add_generation_prompt`,
`reasoning_format`, `reasoning_effort`, `lora`.
✗ `prompt_cache_key` is **absent** at this pin (Odysseus sends a `session_id`/`cache_prompt` pair
instead — `vendor/odysseus/src/llm_core.py:908`).

**We currently send 5 of these** (`bridge/app.py:3574-3576`): `model`, `messages`, `stream`,
`cache_prompt`, `stream_options`.

## 1.3 mlx-lm 0.31.3 (`mlx_lm.server`)

Installed at `data/mlx-venv/lib/python3.12/site-packages/mlx_lm/` (`_version.py:3` → 0.31.3).

**Launch flags** (`server.py:1751-1880`) — `--model`, `--adapter-path`, `--host`, `--port`,
`--allowed-origins`, `--draft-model`, `--num-draft-tokens` (3), `--trust-remote-code`, `--log-level`,
`--chat-template`, `--use-default-chat-template`, `--temp` (**0.0**), `--top-p` (1.0), `--top-k`
(0), `--min-p` (0.0), `--max-tokens` (**512**), `--chat-template-args` (JSON, e.g.
`{"enable_thinking":false}`), `--decode-concurrency` (32), `--prompt-concurrency` (8),
`--prefill-step-size` (2048), `--prompt-cache-size` (10), `--prompt-cache-bytes`, `--pipeline`.

**Confirmed absent: `--api-key` and any `--ctx-size`/context flag.** This is why
`start_component.sh:194` launches it with only `--model --host --port` and the log line says
"loopback only, no auth".

**Request-body fields** (`server.py:1160-1198`) — `stream`, `stream_options`, `model`, `draft_model`,
`num_draft_tokens`, `adapters`, `max_completion_tokens`/`max_tokens`, `temperature`, `top_p`,
`top_k`, `min_p`, `repetition_penalty` (**0.0** = off), `repetition_context_size` (20),
`presence_penalty` (0.0) + `presence_context_size` (20), `frequency_penalty` (0.0) +
`frequency_context_size` (20), `xtc_probability`, `xtc_threshold`, `logit_bias`, `logprobs`,
`top_logprobs`, `seed`, `chat_template_kwargs`, `stop`.

**Validation ranges** are published in code (`server.py:1229-1251`) — use these verbatim for the
bridge-side validator: `temperature ≥0`; `top_p ∈[0,1]`; `top_k ≥0`; `min_p ∈[0,1]`;
`repetition_penalty ≥0`; `max_tokens ≥0`; `xtc_* ∈[0,1]`; `top_logprobs ∈[0,11]` or -1.

## 1.4 mlx-vlm 0.6.13 (`mlx_vlm.server`) — much richer than mlx-lm, and it breaks two of our rules

Installed at `…/site-packages/mlx_vlm/` (`version.py` → 0.6.13). The server is a **package**
(`mlx_vlm/server/`), not a single file.

**Launch flags** (`mlx_vlm/server/cli.py:31-267`) — `--host`, `--port`, `--trust-remote-code`,
`--model`, `--image-model`, `--tts-model`, `--stt-model`, `--embedding-model`, `--adapter-path`,
`--vision-cache-size`, `--prefill-step-size`, `--log-progress-interval`, `--max-tokens`
(**default 2048** via `MLX_VLM_MAX_TOKENS`, `mlx_vlm/generate/dispatch.py:50`),
`--enable-thinking`, `--thinking-budget`, `--thinking-start-token`, `--thinking-end-token`,
`--kv-bits`, `--kv-key-bits`, `--kv-value-bits`, `--kv-key-scheme`, `--kv-value-scheme`,
`--kv-quant-scheme {uniform,turboquant}`, `--kv-group-size` (64), `--max-kv-size`,
`--quantized-kv-start` (5000), `--draft-model`, `--draft-kind {dflash,eagle3,mtp}`,
`--draft-block-size`, `--max-num-seqs`, `--top-logprobs-k`, **`--api-key`**, `--reload`,
`--log-level`.

⚠️ **Two recorded facts in CLAUDE.md are wrong for the VLM path:** (a) "MLX server has no
`--api-key`" — mlx-vlm **does** (`cli.py:248`); (b) "MLX has no KV-cache control" — mlx-vlm has a
full KV-quantization suite including TurboQuant. Both are true only of `mlx_lm.server`.

**Request-body fields** (`mlx_vlm/server/schemas.py:664-790`, OpenAI shape at `:921+`, Anthropic
shape at `:918+`) — the sampling suite is the widest of the three engines:
`temperature` (default 0.0), `top_p` (1.0), `top_k` (0), `min_p` (0.0), **`top_n_sigma`**,
**`typical_p`**, **`p_less`** (hyperparameter-free sampling), `seed` (0), `repetition_penalty` +
`repetition_context_size`, `presence_penalty` + `presence_context_size`, `frequency_penalty` +
`frequency_context_size`, `logit_bias`, `max_tokens`, `enable_thinking`, `reasoning`,
`reasoning_effort`, `thinking_budget`, `thinking_start_token`, `thinking_end_token`, `logprobs`,
`top_logprobs`, plus a large masked-diffusion block (`max_denoising_steps`, `block_length`,
`num_to_transfer`, `diffusion_sampler`, `threshold`, …) that applies only to diffusion checkpoints.
It also serves an **Anthropic-compatible** `/v1/messages` (`schemas.py:918-955`) and its request
model is `extra="allow"` (`schemas.py:28-31`) — unknown fields are ignored, never 400'd.

## 1.5 Cross-engine asymmetry table (the UI must be honest about these)

| Capability | llama.cpp b10427 | mlx-lm 0.31.3 | mlx-vlm 0.6.13 |
|---|---|---|---|
| context length flag | ✅ `--ctx-size` | ❌ none (model config) | ⚠️ `--max-kv-size` only |
| KV cache quantization | ✅ `-ctk/-ctv` (9 types) | ❌ | ✅ bits/scheme/group/turboquant |
| flash attention | ✅ `-fa` | ❌ (always on internally) | ❌ |
| mlock / mmap | ✅ | ❌ | ❌ |
| batch / ubatch | ✅ | ⚠️ `--prefill-step-size` | ⚠️ `--prefill-step-size` |
| api key | ✅ | ❌ | ✅ |
| penalty scale | `repeat_penalty`, 1.0 = off | `repetition_penalty`, **0.0 = off** | same as mlx-lm |
| `typical_p` | ✅ | ❌ | ✅ |
| `top_n_sigma` | ✅ | ❌ | ✅ |
| DRY sampler | ✅ | ❌ | ❌ |
| mirostat | ✅ | ❌ | ❌ |
| dynatemp | ✅ | ❌ | ❌ |
| XTC | ✅ | ✅ | ❌ (not in the schema) |
| sampler chain ORDER (`samplers`) | ✅ | ❌ | ❌ |
| grammar / json_schema | ✅ both | ❌ | ⚠️ `response_format` + `structured.py` |
| default `max_tokens` | **-1 unbounded** | **512** | **2048** |
| default temperature | **0.80** | **0.0** | **0.0** |
| reasoning control | `-rea`, `--reasoning-budget`, `--reasoning-format` | `chat_template_kwargs` only | `enable_thinking`, `thinking_budget`, start/end tokens, `reasoning_effort` |
| idle unload / TTL | ✅ `--sleep-idle-seconds` | ❌ | ❌ |

**Design implication:** the honest common denominator across all three is
`temperature / top_p / top_k / min_p / repetition penalty (+window) / max_tokens / seed / stop`.
That is exactly the §0.5 default table. Everything beyond it belongs behind an engine-conditional
"advanced" disclosure, or nowhere.

---

# PART 2 — LM Studio's settings inventory (the reference UX)

⚠️ Sourcing note: LM Studio's app docs are screenshot-driven and name only a subset of fields. The
authoritative enumeration is its SDK type definitions, which are the same config objects the GUI
writes: [`LLMLoadModelConfig.ts`](https://github.com/lmstudio-ai/lmstudio-js/blob/main/packages/lms-shared-types/src/llm/LLMLoadModelConfig.ts)
and [`LLMPredictionConfig.ts`](https://raw.githubusercontent.com/lmstudio-ai/lmstudio-js/main/packages/lms-shared-types/src/llm/LLMPredictionConfig.ts).
Where a GUI **label** is not published I mark it unverified.

## 2.1 Load / "Model Load Parameters"

| SDK field | UI label | llama.cpp equivalent |
|---|---|---|
| `contextLength` | Context Length ([REST load](https://lmstudio.ai/docs/developer/rest/load)) | `-c` |
| `gpu.ratio` | GPU Offload, a **0-1 ratio** or `off`/`max` ([lms load](https://lmstudio.ai/docs/cli/local-models/load)) | `-ngl` (a layer *count*) |
| `gpu.numCpuExpertLayersRatio` | CPU MoE slider ([0.4.0](https://lmstudio.ai/changelog/lmstudio-v0.4.0)) | `-ncmoe` |
| `gpu.mainGpu` / `gpu.splitStrategy` / `gpu.disabledGpus` | GPU Controls (⌘⇧H panel, [0.3.14](https://lmstudio.ai/blog/lmstudio-v0.3.14)) | `-mg` / `-sm`,`-ts` / no equivalent |
| `gpuStrictVramCap` | "Limit Model Offload to Dedicated GPU Memory" ([0.3.14](https://lmstudio.ai/blog/lmstudio-v0.3.14)) | **none** |
| `offloadKVCacheToGpu` | "Offload KV Cache to GPU Memory" | `-nkvo` (inverse) |
| `evalBatchSize` / `physicalBatchSize` | unverified labels | `-b` / `-ub` |
| `flashAttention` | Flash Attention | `-fa` |
| `llamaKCacheQuantizationType` / `llamaVCacheQuantizationType` | K/V Cache Quantization Type (unverified labels) | `-ctk`/`-ctv`. ⚠️ LM Studio omits `bf16`; V-quant "requires Flash Attention" |
| `useFp16ForKVCache` | unverified | coarse legacy switch |
| `mlxKvCacheQuantization` | KV Cache Quantization for MLX ([0.3.9](https://lmstudio.ai/blog/lmstudio-v0.3.9)) | n/a — `{enabled, bits, groupSize, quantizedStart}` |
| `keepModelInMemory` / `tryMmap` / `tryDirectIO` | unverified | `--mlock` / `--mmap` / `-dio` — ⚠️ all three now **deprecated upstream in favour of `--load-mode`**, and LM Studio 0.4.21 build 2 explicitly reworked them |
| `seed` | Seed | `-s`. ⚠️ **load-side** in LM Studio, request-side in llama.cpp |
| `numExperts` | ([REST load](https://lmstudio.ai/docs/developer/rest/load)) | no server flag |
| `ropeFrequencyBase` / `ropeFrequencyScale` | RoPE Frequency Base/Scale | `--rope-freq-base/-scale` |
| `maxParallelPredictions` | "Max Concurrent Predictions" (default 4, [docs](https://lmstudio.ai/docs/app/advanced/parallel-requests)) | `-np` |
| `useUnifiedKvCache` | "Unified KV Cache" (default on, [0.4.0](https://lmstudio.ai/blog/0.4.0)) | `-kvu` |
| `contextCheckpoints` | unverified | `-ctxcp` |
| `promptTemplate` | **"Chat Template"**, moved into Load>Advanced in [0.4.17](https://lmstudio.ai/changelog/lmstudio-v0.4.17); source says it "require[s] a reload to change" | `--chat-template`/`--jinja` |
| `reasoningBudgetMessage` | unverified; "requires reloading the model" | `--reasoning-budget-message` |
| `speculativeDraft{Mtp,Simple,Model,MaxTokens,MinTokens,MinContinueProbability}` | Load>Advanced>Speculative Decoding ([0.4.17](https://lmstudio.ai/changelog/lmstudio-v0.4.17)) | `--spec-type`, `-md`, `--spec-draft-n-max/-n-min/-p-min` |
| (GUI-only) CPU Thread Pool Size | moved from Prediction to Load>Advanced in 0.4.17 | `-t` |

**Reload semantics — LM Studio is categorical, and this validates §0.3:** *"Inference parameters can
be set on a per-request basis, while load parameters are set when loading the model"*, and for
`.model()`: *"if the model is already loaded, the configuration will be ignored"*
([docs](https://lmstudio.ai/docs/typescript/llm-prediction/parameters)). The GUI ships a gear button
to change load params on a loaded model, which triggers a reload
([0.4.0 build 12](https://lmstudio.ai/changelog/lmstudio-v0.4.0)).

## 2.2 Inference / "Prediction" parameters

Sampling: `temperature`, `topKSampling`, `topPSampling`, `minPSampling`, `repeatPenalty`,
`presencePenalty`, `xtcProbability`, `xtcThreshold`.
Length/stopping: `maxTokens` (`number|false`), `stopStrings`, `toolCallStopStrings`,
`contextOverflowPolicy` (`stopAtLimit|truncateMiddle|rollingWindow`).
Reasoning: `reasoningParsing {enabled, startString, endString}` — a **user-editable** think-tag pair;
`reasoningBudget`; `enableThinking`.
Structured: `structured` (Zod schema or GBNF; GGUF→llama.cpp grammar, MLX→Outlines,
[docs](https://lmstudio.ai/docs/developer/openai-compat/structured-output)).
Tools: `toolChoice`, `toolNaming`, `rawTools`(deprecated). Other: `cpuThreads`,
`userMaxImageDimensionPixels`, `draftModel`, `raw` (an explicit "do not use" escape hatch).

**Notably ABSENT from LM Studio** but present in llama.cpp: `frequency_penalty` (though the
OpenAI-compat endpoint accepts it), `repeat_last_n` (**no penalty-window control at all**),
typical-p/TFS, DRY, dynatemp, top_n_sigma, mirostat (a type exists but is not in the prediction
schema), `samplers` ordering, raw grammar, `bf16` KV type.

## 2.3 Presets and per-model defaults — TWO systems

**Config Presets** ([docs](https://lmstudio.ai/docs/app/presets)) — named JSON files in
`~/.lmstudio/config-presets`, containing *"every parameter under the Advanced Configuration
sidebar"* plus a system prompt. **Global/named, not per-model**, selected per chat, shareable via
`lms get {author}/{preset}` and publishable to the Hub. ⚠️ **Explicitly excludes load params**:
*"Notable difference: Load parameters are not included in the new preset format. Favor editing the
model's default config in My Models."* — a sentence that appears only in a migration footnote.
⚠️ The current preset JSON schema is **not published**.

**Per-model Defaults** ([docs](https://lmstudio.ai/docs/app/advanced/per-model)) — *"You can set
default **load** settings for each model… When the model is loaded anywhere in the app (including
through `lms load`) these settings will be used."* Set via My Models → ⚙. You can also tune in the
loader and then save as the model's defaults. ⚠️ **On-disk location/format undocumented**; a
community claim of `~/.cache/lm-studio/model-presets.json` conflicts with the official `~/.lmstudio/`
root — treat as unverified.

A **preset conflict resolver dialog** exists in the app (referenced in 0.4.0 bugfixes) — i.e. the two
systems *can* disagree and the user is asked to arbitrate. Worth knowing before we add a 4th layer.

## 2.4 API surface

`POST /v1/chat/completions` accepts, verbatim from
[docs](https://lmstudio.ai/docs/developer/openai-compat/chat-completions):
`model, messages, temperature, top_p, top_k, max_tokens, stream, stop, presence_penalty,
frequency_penalty, logit_bias, repeat_penalty, seed` (+`response_format` for structured output).
Note `min_p` is **absent** here but present on `/api/v1/chat`; `seed` is accepted here despite being
a *load* param in the SDK; `frequency_penalty`/`logit_bias` are accepted despite having no SDK field.

`POST /api/v1/models/load` ([docs](https://lmstudio.ai/docs/developer/rest/load)) accepts only
`model, context_length, eval_batch_size, flash_attention, num_experts, offload_kv_cache_to_gpu,
echo_load_config` — **~6 of ~30 load params.** `echo_load_config:true` returns the *effective*
config, which is a nice pattern for "what is it actually running at".

`POST /api/v1/chat` (stateful, 0.4.0) adds `min_p`, `max_output_tokens`, per-request
**`context_length`**, `system_prompt`, `integrations`, and a coarse
**`reasoning: off|low|medium|high|on`** dial.

`ttl` is a per-request top-level field in seconds; JIT-loaded models default to 60 min; **models
loaded via `lms load` have no TTL**; Auto-Evict keeps at most 1 JIT model resident
([docs](https://lmstudio.ai/docs/developer/core/ttl-and-auto-evict)).

`lms load` exposes only `--ttl --gpu --context-length --identifier --estimate-only --host`
([docs](https://lmstudio.ai/docs/cli/local-models/load)) — everything else comes from per-model
defaults. `--estimate-only` prints a memory estimate accounting for context length, flash attention
and vision-enabled-ness: **a direct analogue of our RAM ledger, and a better one** (ours approximates
by weight-file size only — `bridge/app.py` `_loaded_models_bytes`).

## 2.5 Progressive disclosure (the pattern worth copying)

LM Studio gates settings behind **eight** nested layers:
1. App mode: **User** ("auto-configure everything") vs **Developer**
   ([docs](https://lmstudio.ai/docs/app/user-interface/modes)) — collapsed from three modes in 0.4.0.
2. Loader toggle "**Manually choose model load parameters**", then a second toggle "**Show advanced
   settings**" ([docs](https://lmstudio.ai/docs/app/advanced/parallel-requests)).
3. A "🧪 Advanced Configuration" sidebar for inference.
4. **Conditional reveal**: the Prompt Template box appears *only when the model lacks template
   metadata*, otherwise it is pinned via right-click → "Always Show Prompt Template".
5. Separate hotkey surfaces (GPU Controls ⌘⇧H, with a pop-out so you can change them *while a model
   loads*).
6. Sub-grouping: Load>Advanced>Speculative Decoding.
7. App-settings experimental flags (`reasoning_content` was behind one).
8. Source-level `@experimental`/`@deprecated` with no UI at all.

**What to take from this:** (a) two visible groups, everything else behind one "advanced"
disclosure; (b) hide a control that cannot apply rather than disabling it (their conditional
Prompt Template); (c) resource-safety settings are deliberately **not** hidden behind Developer mode
(a 0.4.0 bugfix explicitly restored guardrail settings in User mode).

**What NOT to take:** their three surfaces disagree about which params are load vs prediction
(`seed`, `cpuThreads`, `context_length` all land differently in SDK vs GUI vs REST). Pick one
taxonomy — §0.3 — and hold it.

---

# PART 3 — Lane-by-lane detail

## 3.1 DIRECT lane (panel → bridge → runner)

We own the body 100%. Built at `bridge/app.py:3574-3576`; history assembled from Odysseus at
`:3535-3543` (last 30 messages), vision gate at `:3549-3558`. Response parsing already handles
`reasoning_content` and inline `<think>` (`:3604-3636`) and consumes the
`stream_options.include_usage` frame for analytics (`:3594-3596`).
**Nothing else needs to change to support sampling — it is a dict merge.**

## 3.2 AGENT lane (panel → Odysseus → runner) @ 25c9e73

Payload built three times in `vendor/odysseus/src/llm_core.py`: streaming at `:2215-2245` (the one
the chat UI uses), async non-stream `:2060-2076`, sync `:1852-1866`. Base body is
`{model, messages, temperature, stream}` plus conditionally `stream_options`, `max_tokens` **or**
`max_completion_tokens` (key chosen by `_uses_max_completion_tokens`, `:1184`, and only when
`max_tokens > 0`), `tools`/`tool_choice`, and llama.cpp slot-affinity hints (`session_id` +
`cache_prompt`, `_apply_local_cache_affinity` `:908`).

**NOT sent on the normal path: `top_p, top_k, min_p, presence_penalty, frequency_penalty, stop,
seed, repetition_penalty, logit_bias`.**

Where temperature/max_tokens come from: **presets**, not settings.
`src/preset_manager.py:9-65` (`code_analyze` 0.2/8000, `brainstorm` 0.9/4096, `reason` 0.3/6000,
`custom` 1.0/0), persisted to `data/presets.json` (`:68`), only `custom` writable, via **admin-only**
`POST /api/presets/custom` (`routes/preset_routes.py:33-50`; temperature 0-2, max_tokens 0-65536).
Defaults `DEFAULT_TEMPERATURE=1.0`, `DEFAULT_MAX_TOKENS=0` (`src/llm_core.py:96-97`).

Negative findings that matter:
- **`model_endpoints` has NO sampling columns** (`core/database.py:433-466`; full migration history
  checked — nothing was added and dropped). Context length is runtime-probed
  (`src/model_context.py:264-331`), never stored.
- **`DEFAULT_SETTINGS` has no sampling keys** (`src/settings.py:31-199`); `POST /api/auth/settings`
  silently drops unknown keys (`routes/auth_routes.py:658-660`), so posting `temperature` there is a
  no-op.
- **No per-session sampling** — `class Session` (`core/database.py:175-252`) has `model`,
  `endpoint_url`, `headers`, but no temperature/max_tokens/preset_id.
- ⚠️ There IS one hardcoded sampling block: `_apply_local_generation_stability()`
  (`src/llm_core.py:951-975`), gated to local MiniMax-MLX endpoints only, which pins temp ≤0.2,
  top_p 0.9, top_k 20, repetition_penalty 1.12/256, and a stop list — with no config surface. A
  precedent for exactly the buried-constant problem we are fixing.
- ⚠️ Temperature is **dropped entirely** for o1/o3/o4/gpt-5/Moonshot (`_omit_temperature` `:1222`)
  and Opus 4.7+ (`:1234`) — irrelevant locally, but it means a temperature slider is not universally
  honoured even within this lane.

## 3.3 HERMES lane @ v2026.8.13

**The headline is a negative: `model.temperature` does not exist and cannot be made to work by
writing config.** `DEFAULT_CONFIG["model"]` is the bare string `""`
(`hermes_cli/config_defaults.py:8`); the `model:` section is documented only in
`cli-config.yaml.example:34-137`. Keys actually read:

| Key | Reader |
|---|---|
| `model.default` | `agent/agent_init.py:2275` |
| `model.provider` | `agent/agent_init.py:2290` |
| `model.base_url` | `agent/agent_init.py:2292` |
| `model.api_key` | `cli-config.yaml.example:72` |
| `model.context_length` | `agent/agent_init.py:2235` (total window; int only) |
| `model.max_tokens` | `agent/agent_init.py:2209-2231` (output cap) |
| `model.ollama_num_ctx` | `agent/agent_init.py:2786-2791` |
| `model.default_headers` / `extra_headers` | `agent/auxiliary_client.py:1047,1052` |

**No `top_p`, `top_k`, `min_p`, penalties, `seed`, `stop`, or `reasoning_effort` under `model:`.**
Reasoning depth lives under `agent.reasoning_effort` (`cli-config.yaml.example:944`) and per-model
`agent.reasoning_overrides` (`config_defaults.py:285-290`).

Payload construction: `agent/transports/chat_completions.py:599` (`_build_kwargs_from_profile`),
base dict `:622-625`, temperature block `:627-635`, max_tokens `:649-668`, `extra_body` `:686-737`.
The temperature block reads `params.get("temperature")` — **and no call site ever supplies it**
(`agent/chat_completion_helpers.py:1546-1558`, `:1572-1607` pass only `fixed_temperature`/
`omit_temperature`). Upstream says it outright at `agent/moa_loop.py:1185-1187`: *"a single-model
Hermes agent … never sends temperature unless explicitly configured."* The only user-configurable
temperature in the product is MoA presets (`hermes_cli/moa_config.py:300-303`).

Config caching: `_load_config_impl` (`hermes_cli/config.py:3409`), cache keyed on the 4-tuple
`(user mtime_ns, user size, managed mtime_ns, managed size)` (`:3415-3449`). ⚠️ A same-length
in-place overwrite does NOT invalidate it. And `model.max_tokens`/`context_length` are snapshotted at
agent init, so an edit only affects a **new** session.

⚠️ Additional conflict risks if we write this file: `_normalize_root_model_keys` rewrites the
`model:` block on **every load** (`config.py:2813-2873`), moving root-level keys in and renaming
aliases, and the normalized form is what `save_config` persists; writes go through
`atomic_yaml_write` (`:3211-3214`) which destroys comments; a managed `/etc/hermes/config.yaml`
deep-merges **after** the user file and wins (`:3517-3525`); unknown `providers.<name>` keys are
logged and dropped (`:1320-1346`); and malformed YAML falls back to last-known-good silently
(`:3474-3513`) so a bad write looks like a success.

## 3.4 The aux runner

`bridge/app.py:2362-2432`. Same engine dispatch, but its argv (`:2425-2429`) is
`--no-context-shift --host --port --alias --ctx-size --no-cont-batching --cache-ram -1 --fit off
--model --parallel 1 [--mmproj] [--api-key]` with `ctx = m.get("ctx") or 8192`.
⚠️ **It does NOT get `--repeat-penalty/--repeat-last-n` and does NOT get the MTP spec flags** — an
undocumented divergence from the main runner. If sampling defaults become a table, both launchers
must read the same table (or, better, samplers move to request-class and the divergence dissolves).

---

# PART 4 — Gotchas to carry into the spec

1. **`USER_KEYS` or it silently dies.** `settings` (and arguably `ctx`) must join
   `scripts/seed_registry.py:515` or one Rescan wipes every tuned model. `_keep_user` drops
   falsy values, so an empty dict won't persist (fine) — and it carries nested dicts wholesale.
2. **`_registry_update`'s None-removes-key grammar** (`bridge/app.py:3030-3031`) is exactly right for
   "reset to default" — absence, never a stored null. Reuse it; don't invent a second convention.
3. **MLX takes the model PATH, not our id** (`wire_model_id`, `bridge/app.py:3531`). Any new
   settings endpoint keys off the registry **id**; only the wire field translates.
4. **mlx-lm has no `--api-key` and no ctx flag; mlx-vlm HAS `--api-key` and a KV-quant suite.**
   The recorded blanket rule "MLX has no api-key / no ctx" is only true of mlx-lm.
5. **`ctx` has a migration history**: registry `ctx` → `harness.yaml ctx_size` → 65536
   (`start_component.sh:89-91`), and the 95536 on the 35B came from Jan's `router.preset.ini`,
   carried forward for `local` entries only (`seed_registry.py:551-586`). Hermes also enforces a
   64 K floor. A ctx editor must respect that floor or the Hermes lane breaks.
6. **Hermes reads config at use-time but snapshots `model.*` at agent init**, and its cache is
   `(mtime, size)`-keyed. Odysseus's endpoint/preset changes need no re-seed (they are DB/JSON reads
   per request), but its **endpoint row** is re-seeded on every Odysseus start
   (`start_component.sh:221-224` → `seed_odysseus_jan.py`), so anything we write into that row is
   fair game to be overwritten.
7. **A load-param change costs a 60-90 s model reload** on the 35B, and during it the runner card
   shows amber "Loading…". Never trigger that implicitly from a settings edit.
8. **KV-cache quantization interacts with the RAM ledger.** `memory.budget_gb: 48` is approximated by
   weight-file size and ignores KV entirely; turning on `-ctk q8_0` genuinely changes the footprint
   in a direction the ledger cannot see. If we surface KV quant we should say the ledger doesn't
   model it (LM Studio's `--estimate-only` is the mature version of this).
9. **Contract tests**: `--repeat-penalty`, `--spec-type`, `-a/--alias` are already pin-asserted in
   `harness.yaml`'s runner comments. Any newly-depended-on flag (`-ctk`, `-fa`, `--reasoning-format`)
   should join that list, and the MLX validation ranges are worth pinning against
   `mlx_lm/server.py:1229-1251` so a pin bump that tightens them trips loudly.
10. ⚠️ **New watch-item already recorded and now relevant**: b10427 reads
    `/etc/llama.cpp/config.ini` and `~/.config/llama.cpp/config.ini` **if they exist**, applied
    before env and CLI (`harness.yaml` runner comment). Neither exists on Debi's Mac, but
    llama-server's effective settings are no longer determined by our argv alone — so an
    "effective config" readout (LM Studio's `echo_load_config`) is more valuable than it looks.

---

# Appendix — verification method

- llama-server launch flags: `data/llama-server.help.txt` (669 lines), regenerated by
  `scripts/start_component.sh:212` on every runner start; this copy is from the b10427 binary.
- llama-server **request** fields: exact-match symbol extraction from
  `data/llamacpp/build/bin/libllama-server-impl.dylib` (our pinned binary). Absences were tested,
  not assumed (`temp`, `typ_p`, `dynatemp_exp`, `prompt_cache_key` are all absent as body keys).
- MLX: read from the installed venv at `data/mlx-venv/lib/python3.12/site-packages/`
  (mlx-lm 0.31.3, mlx-vlm 0.6.13) — i.e. the code that actually runs here, not PyPI docs.
- Odysseus/Hermes: read from `vendor/` at the current pins (25c9e73 / v2026.8.13), verified via
  `git log -1` and `git tag --points-at HEAD`.
- LM Studio: web only, URLs inline. **Not verified against a running LM Studio install.**

**Not verified / open:**
- Whether llama-server b10427 applies each CLI sampler value as the *request default* (strongly
  implied by the help text's per-flag "default:" and by long-standing behaviour, but not confirmed
  against source or a live probe). If it does not, our `--repeat-penalty 1.1` may be doing nothing
  today, which changes the framing of §0.1(2).
- LM Studio's per-model-defaults on-disk format, its current preset JSON schema, and the
  SDK/REST parameter name for selecting a preset.
- Every number in §0.5 except `1.1/256` is convention, not measurement.
