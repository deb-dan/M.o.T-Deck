> **DONE — implemented and shipped (marked 2026-08-20).**

# FABLE SPEC — MUSIC LANE v1 (dual-engine)
2026-08-20 · Fable 5 · decision-free build spec. Debi's ruling: BOTH engines pass the
ear test — keep both, selectable when both are installed, auto-selected when only one
is. Build for speed where free, but 2min/song is acceptable.
Ground truth for every engine invocation: `scripts/measure_music.sh` (the working
prototype — lift its logic, incl. the HF symlink-farm fix and the cmake line) +
`docs/handoff/MUSIC-MEASUREMENT-RUNBOOK.md` (measured numbers) +
`docs/research/(done) 2026-08-20-music-video-gen.md` (licenses).

## Shape
Music is a NATIVE bridge lane like voice — no new component daemon, no new port, no
Swift change. Renders are one-shot subprocesses run as background JOBS. A new panel
view **Music** (sidebar entry `♫ Music`, between Models and Capabilities).

## Engines (both first-class)
- **minimax** — MiniMax-Music3-MLX int8, pin `PocketAiHub/MiniMax-Music3-MLX @
  0505e3f04ddfb883e0a2fbd8ad1a34c2f313e514` (build key `build.music_minimax_pin`),
  own venv `data/music-venv` (the port pins mlx==0.30.6 — NEVER touch data/mlx-venv),
  weights via snapshot_download into the HF cache. Invocation = the measure script's
  fixed form: cd snapshot + PYTHONPATH + explicit --model-dir. Default steps 30.
  License line on its card: `minimax-community (weights)` amber (the LICENSE_OVERRIDES
  row already exists — reuse its reason/source_url).
- **acestep** — acestep.cpp at pin `9761469d95fc204b5468623c68a1a2203e50b1f9`
  (build key `build.acestep_pin`), clone+cmake into `data/acestep/` (direct cmake,
  NOT upstream's Linux-only buildcpu.sh; -j hw.ncpu), the four default GGUFs
  (vae-BF16, Qwen3-Embedding-0.6B-Q8_0, acestep-5Hz-lm-4B-Q8_0, acestep-v15-turbo-Q8_0)
  hf-downloaded into the HF cache and symlinked into `data/acestep/models/`. Two-stage
  render: ace-lm → ace-synth exactly as the measure script does (AceRequest JSON;
  duration float seconds; output_format has no CLI flag). Default steps 8 (turbo's
  design point). MIT. NEVER launch upstream's server.sh (binds 0.0.0.0).

## Install path
`scripts/install_music.sh <minimax|acestep>` — idempotent, lifted from
measure_music.sh but writing to the PERMANENT homes above; reads pins from
motdeck.yaml (awk pattern like install_mlx.sh); logs to `data/logs/music-install.log`
(add to `_LOG_NAMES` + panel LOG_SOURCES — the voicebox-install lesson: install logs
must be viewable in-panel). Bridge: `POST /api/music/install {engine}` runs it in a
background thread with the component-install timeout pattern; `GET /api/music/status`
reports per-engine `{installed, installing, size_gb, license?}` — installed = detected
FROM DISK (minimax: venv python + snapshot dir with model_manifest.json; acestep: both
binaries + all four ggufs resolve), never a stored flag. cmake missing → the install
endpoint fails EARLY with "brew install cmake" in the message, before any download.
STANDING RULES: zsh-paste-safe, `${var}` braced against glued multibyte
(test_script_hygiene.py now enforces this), listener-scoped kills n/a (no ports).

## Render jobs
`POST /api/music/generate {engine, prompt, lyrics?, seconds, steps?, seed?}` →
validates (engine installed; prompt non-empty ≤2000; seconds 10..300 int; steps
1..30 minimax / 1..20 acestep, defaults 30/8; seed optional int ≥0) → **RAM ledger
gate**: `MUSIC_RAM_GB = {"minimax": 32, "acestep": 9}` (minimax's measured 2.2GB RSS
is known-understated — the planning number stands); refuse 409 with "eject the chat
model first" when loaded-model bytes + need exceed `memory.budget_gb`. ONE render at a
time (global lock → 409 busy, never a queue). Job = `{id, engine, state:
queued|running|done|failed, started, wall?, error?, out?}` in a process-lifetime dict;
thread runs the subprocess with a 30-minute timeout; output lands in `data/music/`
(gitignored) as `<engine>-<yyyymmdd-hhmmss>.wav` + a `.json` sidecar {engine, prompt,
lyrics, seconds, steps, seed, wall}. `GET /api/music/jobs` returns the active job (the
panel polls only while one runs). Engine stderr tail carried into `error` on failure —
the bridge log gets one `[music] render …` line per job (the voice-lane logging rule:
diagnosable from the log alone).

## Library
`GET /api/music/library` lists data/music/ wavs + sidecar meta, newest first.
`POST /api/music/delete {name}` — basename-only, realpath containment on data/music
(the `_deletable_target` discipline), deletes wav + sidecar. Playback is client-side.

## Panel (Music view)
Existing grammar only (.card/.mrow/.mpill/.cap-*/chips); the ONE sanctioned new
element type is the native `<audio controls>` player (style: width 100%, no new CSS
rules beyond at most one layout rule if unavoidable — tag it). Layout top-to-bottom:
1. **Engines** — one row per engine: name + pills (`installed`/`not installed`,
   size, `MIT` / amber `minimax-community (weights)`), a Get/Install button (arms the
   install, shows `installing…` with a View-log link into the existing log dialog),
   and one faint line each: minimax "~2 min per minute of song · highest quality";
   acestep "~25s per song · fast".
2. **Create** — engine picker (chips; auto-picks the only installed engine, hidden
   when neither installed with a note pointing at Get), prompt textarea, lyrics
   textarea (placeholder says instrumental if empty), seconds slider+box (10–300,
   default 60, reuse .cap-range), steps + seed number boxes with per-engine defaults
   shown, **Generate** (primary). While a job runs: button disabled, elapsed ticker
   + state line, and a Cancel is deliberately NOT offered in v1 (killing a Metal
   render mid-flight is untested — note in UI copy that a render cannot be stopped).
   Ledger refusals surface inline with the bridge's own message.
3. **Library** — rows: name, engine pill, seconds, date, wall time; `<audio>` player
   (lazy: only the selected/most-recent row renders a player, src via a new
   `GET /api/music/file/{name}` with the same containment as delete + correct MIME);
   Reveal-in-Finder via the existing /api/open allowlist; two-step ✕ delete.
Sidebar: `♫ Music` nav entry + ⌘K entries ("Music", "Generate music").

## Tests (mandatory, all green + full sweep + contract 105 intact)
Pure decision tables: both engines' argv/request builders (lift expectations from the
measure script; minimax MUST carry cd/PYTHONPATH/--model-dir semantics — pin by
structure), the RAM-gate table (both engines × loaded-bytes cases, boundary
inclusive), validation totality (junk engine/seconds/steps/seed), install detection
from fake disk trees (present/partial/absent per engine), library listing +
containment refusals + sidecar pairing, job state machine (busy-409, done, failed
carries stderr tail, timeout), and wiring greps (endpoints exist, log names added,
panel view + nav + poll-only-while-running). bash -n both scripts; script-hygiene
suite must stay green.

## Out of scope v1 (recorded)
Engine auto-download of alternate quants; streaming progress %; render cancel;
Hermes/agent tool exposure of music generation (a later, deliberate decision — NOT a
default); the ComfyUI Video/Audio tab (separate milestone — this lane may later be
linked from it).
