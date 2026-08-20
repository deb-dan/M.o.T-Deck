#!/usr/bin/env bash
# Music-engine MEASUREMENT harness — throwaway, adopts nothing.
#
#   ./scripts/measure_music.sh minimax     MiniMax-Music3 via the pure-MLX port
#   ./scripts/measure_music.sh acestep      acestep.cpp (GGML/Metal, GGUF)
#
# It answers ONE question, the one docs/research/2026-08-20-music-video-gen.md
# flagged as unknown: how long does a 60-second song take on THIS Mac, and how
# much RAM does it peak at. Nothing here is a component: no port is registered,
# no manifest is touched, no venv outside data/music-trial-venv is created, and
# vendor/ is never written to. Everything it makes is removable with one rm -rf
# printed at the end.
#
# Fill the numbers into docs/handoff/MUSIC-MEASUREMENT-RUNBOOK.md.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

CMD="${1:-}"

TRIAL="$ROOT/data/music-trial"
VENV="$ROOT/data/music-trial-venv"
OUT="$ROOT/data/tmp/music-trial"
NEED_GB=15

# The SAME prompt, lyrics, duration and seed for both engines — otherwise the two
# numbers are not comparable. The text is the MLX port's own published example, so
# its render can also be A/B'd by ear against the WAV shipped in that repo.
PROMPT="High-energy rock and roll, gritty male vocal, crunchy guitars, boogie piano, live drums, punchy bass, 148 BPM"
SECS=60
SEED=20260815

read -r -d '' LYRICS <<'LYR' || true
[Verse]
Neon on the dashboard, midnight in the street
Engine keeps on rumbling to a backbeat

[Chorus]
Turn it up, let the good times roll
Fire in the speakers, thunder in your soul
LYR

say() { echo "[music-trial] $*"; }

die() { echo "[music-trial] ERROR: $*" >&2; exit 1; }

usage() {
  echo "usage: $0 minimax|acestep"
  echo ""
  echo "  minimax   PocketAiHub/MiniMax-Music3-MLX  (~11.9GB int8 weights, pure MLX)"
  echo "  acestep   ServeurpersoCom/acestep.cpp     (~7.7GB GGUF, GGML + Metal)"
  exit 1
}

# ── preflight ────────────────────────────────────────────────────────────────
preflight() {
  [[ "$(uname -s)" == "Darwin" ]] || die "this measurement only means anything on macOS."
  [[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon only (uname -m says $(uname -m))."

  local free_gb
  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (need ~${NEED_GB}GB)"
  if [[ "$free_gb" -lt "$NEED_GB" ]]; then
    die "not enough free disk — need about ${NEED_GB}GB for weights + build, have ${free_gb}GB."
  fi

  echo ""
  say "⚠️  RAM: a MiniMax-Music3 render wants 32GB minimum, 48GB recommended, and the"
  say "    harness budget is memory.budget_gb: 48. EJECT THE CHAT MODEL FIRST:"
  say "      Harness panel → Models → the row with the gold 'live' pill → Eject"
  say "    (and stop the Aux runner if it is up: Models → Aux runner → Stop)"
  say "    Nothing here talks to the ledger — this script is outside it, so the"
  say "    only thing stopping a swap storm is that click."
  echo ""

  mkdir -p "$TRIAL" "$OUT"
  printf '%s\n' "$LYRICS" > "$OUT/lyrics.txt"
}

# ── python + venv (mirrors install_component.sh's resolution ladder) ──────────
# The app is launched from Finder with a minimal PATH, and a uv installed in
# ~/.local/bin is invisible to `command -v`. Same rule here.
resolve_py() {
  local p
  for p in "$ROOT/data/python-standalone/bin/python3" \
           "$(command -v python3.12 || true)" \
           "$(command -v python3.11 || true)" \
           "$(command -v python3.13 || true)" \
           "$(command -v python3 || true)"; do
    [[ -n "$p" && -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

resolve_uv() {
  local u
  for u in "$(command -v uv || true)" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv \
           /usr/local/bin/uv "$HOME/.cargo/bin/uv"; do
    [[ -n "$u" && -x "$u" ]] && { echo "$u"; return 0; }
  done
  return 0
}

ensure_venv() {
  local py uv minor
  py="$(resolve_py)" || die "no python3 found — brew install python@3.12"
  uv="$(resolve_uv)"
  minor=$("$py" -c 'import sys; print(sys.version_info[1])')
  say "interpreter: $py (3.$minor)"
  if [[ "$minor" -lt 11 || "$minor" -gt 13 ]]; then
    say "WARN: the MLX port asks for Python 3.11-3.13; mlx==0.30.6 may have no wheel here."
  fi
  [[ -n "$uv" ]] && say "uv: $uv" || say "uv: not found (falling back to venv+pip)"

  if [[ ! -x "$VENV/bin/python" ]]; then
    if [[ -n "$uv" ]] && "$uv" venv --python "$py" --seed "$VENV" >/dev/null 2>&1; then
      say "venv created with uv (--seed)."
    elif "$py" -m venv "$VENV" >/dev/null 2>&1; then
      say "venv created with $py -m venv."
    elif "$py" -m venv --without-pip "$VENV" >/dev/null 2>&1; then
      say "venv created without pip (bootstrapping pip)."
    else
      rm -rf "$VENV"
      die "could not create $VENV — install uv, or brew reinstall python@3.12."
    fi
  fi
  if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
      say "pip bootstrapped via ensurepip."
    elif [[ -n "$uv" ]] && "$uv" pip install --python "$VENV/bin/python" pip >/dev/null 2>&1; then
      say "pip bootstrapped via uv."
    else
      die "$VENV has no usable pip. Install uv and re-run."
    fi
  fi
}

vpip() {
  "$VENV/bin/python" -m pip install --disable-pip-version-check "$@"
}

# ── timing ───────────────────────────────────────────────────────────────────
# /usr/bin/time -l writes its stats to stderr, so the command's own stderr lands
# in the same log. That is deliberate: when a render fails, the reason and the
# timing are in one file. WALL_S / RSS_GB are set as globals by run_timed.
WALL_S=""
RSS_GB=""

run_timed() {
  local label="$1"; shift
  local log="$OUT/$label.log"
  local rc=0
  say "running: $label  (log: data/tmp/music-trial/$label.log)"
  set +e
  /usr/bin/time -l "$@" >"$log" 2>&1
  rc=$?
  set -e
  WALL_S=$(awk '/ real +.* user +.* sys/ {r=$1} END {print r+0}' "$log")
  RSS_GB=$(awk '/maximum resident set size/ {m=$1} END {printf "%.1f", m/1073741824}' "$log")
  if [[ "$rc" -ne 0 ]]; then
    echo ""
    tail -30 "$log" >&2
    die "$label exited $rc — the last 30 log lines are above, the whole run is in $log"
  fi
  say "$label: ${WALL_S}s wall, ${RSS_GB}GB max RSS"
}

finish() {
  local engine="$1" audio="$2" wall="$3" rss="$4"
  echo ""
  echo "──────────────────────────────────────────────────────────────────────"
  echo "  RESULT  engine=$engine  song=${SECS}s  wall=${wall}s  maxRSS=${rss}GB"
  echo "  audio:  $audio"
  echo "──────────────────────────────────────────────────────────────────────"
  echo ""
  say "Listen to it (open \"$audio\"), then write the numbers into"
  say "  docs/handoff/MUSIC-MEASUREMENT-RUNBOOK.md"
  echo ""
  say "When you are done with BOTH engines, remove every byte this made:"
  echo "  rm -rf \"$ROOT/data/music-trial\" \"$ROOT/data/music-trial-venv\" \"$ROOT/data/tmp/music-trial\""
  say "(the downloaded weights stay in ~/.cache/huggingface so a later adoption"
  say " does not re-download them; delete that separately if you want the space back)"
}

# ── engine 1: MiniMax-Music3 via the pure-MLX port ───────────────────────────
# The port is an HF REPO, not a GitHub one — code and weights ship together, so
# the "pin" is an HF revision sha. This one was read live from the HF API on
# 2026-08-20 (lastModified 2026-08-15, usedStorage 11,926,051,756 = 11.9GB).
MINIMAX_REPO="PocketAiHub/MiniMax-Music3-MLX"
MINIMAX_REV="0505e3f04ddfb883e0a2fbd8ad1a34c2f313e514"

do_minimax() {
  preflight
  ensure_venv

  say "installing huggingface_hub into the trial venv…"
  vpip -q -U "huggingface_hub" || die "could not install huggingface_hub"

  say "downloading $MINIMAX_REPO @ ${MINIMAX_REV:0:12} (~11.9GB, into the HF cache)…"
  local snap
  snap=$("$VENV/bin/python" - <<PY
from huggingface_hub import snapshot_download
print(snapshot_download("$MINIMAX_REPO", revision="$MINIMAX_REV"))
PY
  ) || die "snapshot_download failed (network? disk?)"
  [[ -f "$snap/generate.py" ]] || die "no generate.py in $snap — the repo layout changed."
  say "snapshot: $snap"

  say "installing the port's own pins (mlx==0.30.6 — this is WHY the venv is separate:"
  say "  data/mlx-venv ships mlx 0.32.0 and must not be downgraded)"
  vpip -q -r "$snap/requirements.txt" || die "requirements install failed — see the error above"

  local wav="$OUT/minimax-${SECS}s.wav"
  rm -f "$wav"
  # 30 flow steps is the port's own acceptance setting and the top of its
  # supported range (1-30); anything lower is a different measurement.
  (
    cd "$snap"
    run_timed "minimax" "$VENV/bin/python" generate.py \
      --prompt "$PROMPT" \
      --lyrics-file "$OUT/lyrics.txt" \
      --seconds "$SECS" \
      --steps 30 \
      --seed "$SEED" \
      --output "$wav"
  ) || exit 1
  # run_timed's globals do not survive the subshell, so re-read them from the log.
  WALL_S=$(awk '/ real +.* user +.* sys/ {r=$1} END {print r+0}' "$OUT/minimax.log")
  RSS_GB=$(awk '/maximum resident set size/ {m=$1} END {printf "%.1f", m/1073741824}' "$OUT/minimax.log")
  [[ -s "$wav" ]] || die "generate.py exited 0 but produced no audio at $wav (check $OUT/minimax.log)"

  finish "MiniMax-Music3-MLX int8 (30 steps)" "$wav" "$WALL_S" "$RSS_GB"
}

# ── engine 2: acestep.cpp ────────────────────────────────────────────────────
# ⚠️ UNVERIFIED PIN: api.github.com and github.com were both unreachable from the
# sandbox that wrote this script (only raw.githubusercontent.com answered), so no
# commit sha could be resolved ahead of time. We clone the BRANCH HEAD and RECORD
# the sha we got into data/music-trial/acestep.cpp.sha — quote that in the runbook,
# it is what makes the number reproducible.
ACESTEP_REPO="https://github.com/ServeurpersoCom/acestep.cpp.git"
ACESTEP_BRANCH="master"
ACESTEP_GGUF_REPO="Serveurperso/ACE-Step-1.5-GGUF"

do_acestep() {
  preflight
  command -v git >/dev/null 2>&1 || die "git not found — xcode-select --install"
  command -v cmake >/dev/null 2>&1 || die "cmake not found — brew install cmake"
  ensure_venv

  local src="$TRIAL/acestep.cpp"
  if [[ ! -d "$src/.git" ]]; then
    say "cloning acestep.cpp ($ACESTEP_BRANCH, shallow, with submodules)…"
    git clone --depth 1 --branch "$ACESTEP_BRANCH" --recurse-submodules \
      --shallow-submodules "$ACESTEP_REPO" "$src" || die "clone failed"
  else
    say "reusing existing clone at data/music-trial/acestep.cpp"
  fi
  local sha
  sha=$(git -C "$src" rev-parse HEAD)
  echo "$sha" > "$TRIAL/acestep.cpp.sha"
  say "acestep.cpp commit: $sha"
  say "  (recorded in data/music-trial/acestep.cpp.sha — put it in the runbook)"

  # NOT ./buildcpu.sh: that script calls `nproc`, which does not exist on macOS,
  # and passes -DGGML_BLAS=ON which the docs only ask for on Linux. The upstream
  # macOS line in docs/ARCHITECTURE.md is a bare `cmake ..` — Metal and Accelerate
  # BLAS are auto-enabled there.
  if [[ ! -x "$src/build/ace-synth" ]]; then
    say "building with cmake (Metal + Accelerate auto-enabled on macOS)…"
    cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release >/dev/null \
      || die "cmake configure failed"
    cmake --build "$src/build" --config Release -j "$(sysctl -n hw.ncpu)" \
      || die "build failed"
  else
    say "reusing existing build at data/music-trial/acestep.cpp/build"
  fi
  [[ -x "$src/build/ace-lm" && -x "$src/build/ace-synth" ]] \
    || die "build produced no ace-lm/ace-synth — see the cmake output above"

  # The four default GGUFs (README's own table): LM-4B Q8_0 4.2GB, text encoder
  # 748MB, DiT turbo Q8_0 2.4GB, VAE BF16 322MB ≈ 7.7GB. Downloaded into the HF
  # cache and SYMLINKED into models/ so a re-run costs nothing and a cleanup does
  # not delete 7.7GB of weights.
  say "installing huggingface_hub into the trial venv…"
  vpip -q -U "huggingface_hub" || die "could not install huggingface_hub"
  local models="$src/models"
  mkdir -p "$models"
  local f
  for f in vae-BF16.gguf \
           Qwen3-Embedding-0.6B-Q8_0.gguf \
           acestep-5Hz-lm-4B-Q8_0.gguf \
           acestep-v15-turbo-Q8_0.gguf; do
    if [[ -e "$models/$f" ]]; then
      say "have $f"
      continue
    fi
    say "downloading $f…"
    local p
    p=$("$VENV/bin/python" - <<PY
from huggingface_hub import hf_hub_download
print(hf_hub_download("$ACESTEP_GGUF_REPO", "$f"))
PY
    ) || die "download of $f failed"
    ln -sf "$p" "$models/$f"
  done

  # AceRequest JSON (docs/ARCHITECTURE.md): `duration` is float SECONDS, `lyrics`
  # is the single source of truth for vocals, `output_format` is a JSON field and
  # has no CLI flag. 8 inference steps is the turbo DiT's design point — this is
  # NOT the same knob as MiniMax's 30 flow steps, and the runbook says so.
  local req="$OUT/acestep-req.json"
  "$VENV/bin/python" - "$req" <<PY
import json, sys
lyrics = open("$OUT/lyrics.txt").read()
req = {
    "caption": """$PROMPT""",
    "lyrics": lyrics,
    "duration": $SECS,
    "seed": $SEED,
    "inference_steps": 8,
    "output_format": "wav24",
}
open(sys.argv[1], "w").write(json.dumps(req, indent=2))
PY
  rm -f "$OUT"/acestep-req0*.json "$OUT"/acestep-req0*.wav "$OUT"/acestep-req0*.mp3

  # Two binaries, two loads: ace-lm writes <stem>0.json next to its input, then
  # ace-synth renders <stem>00.<ext>. They are timed SEPARATELY because their RAM
  # peaks are separate — the ledger claim is the MAX of the two, not the sum,
  # while the wall clock IS the sum.
  ( cd "$src" && run_timed "acestep-lm" ./build/ace-lm --models "$models" --request "$req" ) || exit 1
  local lm_wall lm_rss
  lm_wall=$(awk '/ real +.* user +.* sys/ {r=$1} END {print r+0}' "$OUT/acestep-lm.log")
  lm_rss=$(awk '/maximum resident set size/ {m=$1} END {printf "%.1f", m/1073741824}' "$OUT/acestep-lm.log")
  [[ -f "$OUT/acestep-req0.json" ]] \
    || die "ace-lm produced no acestep-req0.json (see $OUT/acestep-lm.log)"

  ( cd "$src" && run_timed "acestep-synth" ./build/ace-synth --models "$models" \
      --request "$OUT/acestep-req0.json" ) || exit 1
  local sy_wall sy_rss
  sy_wall=$(awk '/ real +.* user +.* sys/ {r=$1} END {print r+0}' "$OUT/acestep-synth.log")
  sy_rss=$(awk '/maximum resident set size/ {m=$1} END {printf "%.1f", m/1073741824}' "$OUT/acestep-synth.log")

  local audio
  audio=$(ls "$OUT"/acestep-req0*.wav "$OUT"/acestep-req0*.mp3 2>/dev/null | head -1 || true)
  [[ -n "$audio" && -s "$audio" ]] \
    || die "ace-synth exited 0 but produced no audio next to $OUT/acestep-req0.json"

  local total peak
  total=$(awk -v a="$lm_wall" -v b="$sy_wall" 'BEGIN {printf "%.2f", a+b}')
  peak=$(awk -v a="$lm_rss" -v b="$sy_rss" 'BEGIN {printf "%.1f", (a>b?a:b)}')
  say "stage split: ace-lm ${lm_wall}s / ${lm_rss}GB · ace-synth ${sy_wall}s / ${sy_rss}GB"
  finish "acestep.cpp GGUF Q8_0 turbo (8 steps, ${sha:0:12})" "$audio" "$total" "$peak"
}

case "$CMD" in
  minimax) do_minimax ;;
  acestep) do_acestep ;;
  *) usage ;;
esac
