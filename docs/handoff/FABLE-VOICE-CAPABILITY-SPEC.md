# FABLE SPEC — Harness-native voice capability (MIT stack: llama.cpp · MLX · Whisper)

Fable 5, 2026-08-07. Successor to the voice-tabs item. Builders: Opus 5 / Opus 4.8,
one phase at a time, identity protocol + ⚠️ PENDING FABLE QA tags apply. Ship rule:
`./scripts/ship.sh` only. Debi's UX direction (verbatim intent): an audio control in
the chat composer that opens an enable/choose popover "just like the dropdown we have
for models"; **llama.cpp on top as the default engine**; the Models page gains an
**Audio tab** with download + "rescan audio models already on computer", mirroring
chat models.

## ⟳ AMENDED 2026-08-07 after Phase 0 recon (recon wins; Fable ratified)

1. **OuteTTS/vocoder is DEAD at our pin** — llama-tts at b10295 is the rewritten
   mtmd tool: `llama-tts -m backbone.gguf -mm mmproj.gguf -p "text" -o out.wav`.
   Registry `tts-gguf` entries carry **`mmproj`** (not `vocoder`). No `--voice` —
   voice selection is an MLX-only affordance; llama.cpp has only `--tts-lang` +
   `--tts-speaker-file` (reference-audio). Upstream calls the tool a playground,
   not production — set expectations accordingly.
2. **Default llama.cpp download offer**: `ggml-org/Qwen3-TTS-12Hz-1.7B-Base-GGUF`
   → `...Q4_K_M.gguf` (0.96 GB) + `mmproj-...-Q8_0.gguf` (0.42 GB). Card license
   note: "Apache-2.0 (upstream Qwen)".
3. **MLX starter model = `mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit`** (named
   voices Chelsie/Ethan, no extra deps). **Kokoro is offered SECOND with its cost
   stated**: it needs `misaki`, whose `en` extra pulls TORCH — the MLX venv must
   stay torch-free, so if Kokoro is installed, misaki goes in WITHOUT the `en`
   extra and Kokoro support is best-effort until verified.
4. **Both engines EXIT 0 ON FAILURE** (mlx-audio swallows exceptions; llama-tts
   quality varies): Phase B defines success as "output wav exists and is
   non-empty", NEVER the return code. This is a unit-tested invariant.
5. **MLX argv must include `--join_audio --output_path <tmpdir> --file_prefix out`**
   (default behaviour writes `audio_000.wav` segments).
6. **mlx-whisper pin = 0.4.3**; STT one-shot = the `mlx_whisper` console script
   with `-f json -o <tmpdir>`, read the json (the CLI writes files, not stdout).
7. Phase C popover shows MODEL rows only (llama.cpp engine rows first, default);
   per-voice picking is deferred (MLX-only, later polish).

## What this is (and is not)

"My agents/chat can SPEAK, and later LISTEN" as a **harness-native capability** built
from MIT/Apache parts we largely already ship. It is NOT the VoiceStudio/Voicebox
route: those remain optional creative apps in tabs, never wired into agents, and this
spec does not touch them. All-MIT posture is the point (Debi's licensing call).

Engine lineup (fixed):
- **TTS `llamacpp`** — the `llama-tts` tool from our OWN pinned llama.cpp build
  (OuteTTS-family GGUF + WavTokenizer vocoder GGUF). DEFAULT per Debi.
- **TTS `mlx`** — `mlx-audio` (already in the fat wheelhouse as an mlx-vlm dep);
  Kokoro (Apache-2.0) is the recommended first model — best quality-per-MB.
- **STT `whisper-mlx`** — `mlx-whisper` into the existing mlx venv, pinned.
- Explicitly EXCLUDED: Coqui/XTTS (non-commercial license, dead org), anything
  needing a cloud key, any new AGPL dependency.

## Architecture decisions (settled — do not relitigate)

1. **One-shot subprocesses, NOT a persistent server.** `llama-tts`,
   `python -m mlx_audio.tts.generate`, and `python -m mlx_whisper` are single-shot
   CLIs: spawn → wav/text → exit. No new port, no lifecycle card, no resident RAM
   claim — which also settles the ledger question for v1: voice models cost DISK
   (shown in the Audio tab) and only transient RAM while a clip renders. A
   runner-adjacent persistent slot is a LATER optimization, only if latency proves
   annoying, and needs a new Fable spec.
2. **Bridge owns the capability**: `POST /api/voice/tts {text, model_id}` → audio
   bytes (wav, correct mime) and later `POST /api/voice/stt` (Phase D). Spawn with
   EXPLICIT paths (standing rule: bridge children get Finder-minimal PATH) from our
   pinned binaries/venvs; temp wavs under `data/tmp/`, cleaned after response.
3. **Registry, not a new store**: audio models are entries in the EXISTING
   `data/models.json` with `kind:"audio"` + `format` ∈ `tts-gguf | tts-mlx | stt-mlx`
   (+ `vocoder` path field for OuteTTS pairs). `api_models` filters them OUT of the
   chat lists (they must never appear in the runner switch/aux flows) and exposes
   them under `audio:[...]`. Download reuses the EXISTING download manager
   (per-file GGUF mode for TTS ggufs; whole-repo mode for mlx/Kokoro repos).
   Rescan extends `seed_registry.py` with an audio scan (HF cache + data/models).
4. **Naming**: this feature's key is `voice` in the bridge, chip label is `AUDIO`.
   Per-session: the CHOSEN tts model id is global (harness.yaml `voice:` block:
   `tts_model`, `stt_model`, empty = off); the per-chat toggle is panel-local state.

## Phase 0 — recon (builder, read-only, evidence-cited; recon wins over this spec)

a. Confirm our pinned llama.cpp release (`runner.llamacpp_pin`, currently b10295)
   ships `llama-tts` in the macos-arm64 asset (list the tarball or the installed
   `data/llamacpp/build/bin/`). Capture its exact CLI (`--help`): model flag,
   vocoder flag, text input, wav output path.
b. Identify ONE known-good OuteTTS GGUF + matching WavTokenizer GGUF on HF (exact
   repos/files/sizes) for the default download offer.
c. `mlx-audio` at our wheelhouse version (0.4.7): exact one-shot TTS invocation,
   Kokoro repo id, output path behaviour, voices arg. Confirm import works in the
   existing mlx venv or needs its own.
d. `mlx-whisper`: PyPI pin, one-shot CLI, model repo ids + sizes (base/small/turbo).
e. WKWebView audio PLAYBACK sanity (should be fine — `new Audio(blobUrl).play()`),
   and note (do NOT build) what mic capture would need for Phase D
   (NSMicrophoneUsageDescription + WKUIDelegate media-capture grant).

## Phase A — Models page: Audio tab

- The Models view gains a two-chip sub-tab in the EXISTING chip grammar
  (`CHAT MODELS | AUDIO`), state persisted like the caps-section chip. Chat tab =
  exactly today's UI, untouched.
- Audio tab: same two-pane grammar. LEFT rows: installed audio models — name +
  pills `tts`/`stt` (gold when it's the active default), engine (`llama.cpp`/`mlx`),
  size GB. RIGHT detail: actions **Set default TTS** / **Set default STT** (writes
  harness.yaml `voice:` block via the bridge), **Delete** (existing guarded delete),
  plus a **Get voice models** section offering the recon-verified starters
  (OuteTTS+vocoder pair, Kokoro, whisper base/turbo) through the EXISTING download
  manager UI (progress/pause/resume come free). **Rescan** button = existing rescan,
  now also picking up audio models.
- No new CSS primitives; reuse .mrow/.mpill/detail grammar.

## Phase B — bridge voice module

- `bridge/voice.py` (new): pure helpers + engine dispatch. `tts(text, entry)` →
  wav bytes: `tts-gguf` → argv `[llama-tts, -m <model>, -mv <vocoder>, ...]` per
  recon; `tts-mlx` → `[<mlx-venv>/bin/python, -m, mlx_audio.tts.generate, ...]`.
  Hard caps: text ≤ 2000 chars per call (413 beyond), one render at a time per
  engine (lock), 120s subprocess timeout, always-cleaned temp files.
- `POST /api/voice/tts {text, model_id?}` (default from harness.yaml) → audio/wav.
  Errors are JSON with the log tail, never a hung request. `GET /api/voice/config`
  → `{tts_model, stt_model, available:[audio entries]}`; `POST /api/voice/config`
  sets defaults. (Note: the existing `/api/voice/status|toggle` from the MCP batch
  keep their names — do not collide; suffix these `/api/voice/tts`, `/config`.)
- Unit tests in the established style: argv builders pure + tested, caps tested,
  registry filtering tested (audio never leaks into chat model lists — this is the
  regression that must be impossible). Contract test: `llama-tts --help` surface
  pinned at pin-bump time (skip when binary absent).

## Phase C — composer AUDIO control (my lane, spec'd here; builder implements)

- A compact `AUDIO` chip in the chat bar next to the model chip, same `.mode-chip`
  grammar, reading `AUDIO off` / `AUDIO on` (mixed-case value like the model chip).
- Click → popover in the EXACT `#model-pop` grammar (reuse the CSS classes): row 0
  = **Off**; then installed TTS models grouped with `llama.cpp` engine rows FIRST
  (Debi: llama on top, default), each row full model id + pills (engine, size,
  `default` gold pill); row click = select + enable (writes config via
  `/api/voice/config`, closes). An **Audio models…** row at the bottom jumps to
  Models → Audio tab. Empty state: "No voice models yet — get one" → same jump.
- When AUDIO is on: every assistant message's existing `.msg-acts` hover row gains
  a **▶ Speak** chip (before Copy). Click → POST `/api/voice/tts` with the message
  `_raw` prose (thinking excluded, fences stripped), chip shows `…` while
  rendering, then plays via `Audio(blobUrl)`; click again while playing = stop.
  Errors surface as the chip flashing `err` with title = message. NO autoplay in
  v1 (an autoplay toggle is a later, deliberate addition).
- Works in ALL lanes (it acts on rendered text, lane-agnostic). Guard: chip
  disabled + tooltip when no TTS model is configured.

## Phase D — STT dictation (GATED: separate go from Debi + Fable review of recon e)

Mic button in the composer → record → `/api/voice/stt` → text into the input.
Needs shell work (Info.plist mic permission + WKUIDelegate grant) and a fat-app
rebuild; do not start until C is verified and Debi green-lights.

## Definition of done (per phase)

Tests green (unit + contract + full sweep), CLAUDE.md updated, ship via
`./scripts/ship.sh`, Mac-verify by Debi: A = Audio tab lists/downloads/rescans and
never pollutes chat lists; B = `curl POST /api/voice/tts` returns a playable wav
for both engines; C = pick llama.cpp default in the popover → ▶ Speak on a reply
plays audio end-to-end. Fat installer must not require any of this (voice models
download on demand; llama-tts already rides the pinned binary; mlx-audio already
in the wheelhouse).
