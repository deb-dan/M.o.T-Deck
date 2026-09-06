#!/usr/bin/env bash
# Install a MUSIC engine into its PERMANENT home (FABLE-MUSIC-LANE-SPEC).
#
#   ./scripts/install_music.sh minimax    MiniMax-Music3 via the pure-MLX port
#   ./scripts/install_music.sh acestep    acestep.cpp (GGML/Metal, GGUF)
#
# Lifted from the measurement prototype (scripts/measure_music.sh) — same verified
# invocations, same HF symlink-farm handling, same direct-cmake build — but writing
# to the homes the bridge reads:
#
#   data/music-venv          python venv for BOTH engines' helper work
#                            (minimax RUNS from here; ⚠️ the port pins mlx==0.30.6,
#                             which is why this is never data/mlx-venv)
#   data/acestep/            acestep.cpp clone + build/ + models/ (gguf symlinks)
#   ~/.cache/huggingface     weights (shared, never re-downloaded)
#
# Idempotent: every step checks first, so a re-run after a failed download resumes.
# Nothing is a component — no port, no manifest entry, no daemon.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

CMD="${1:-}"

VENV="$ROOT/data/music-venv"
ACE="$ROOT/data/acestep"
LOG="$ROOT/data/logs/music-install.log"
NEED_GB=20

mkdir -p "$ROOT/data/logs"
# Everything this script says lands in the panel-viewable install log AS WELL AS on
# stdout (the bridge captures stdout for the endpoint's own reply). The voicebox
# lesson: an install log for a fragile component must be readable without a terminal.
exec > >(tee -a "$LOG") 2>&1
echo "──────── install_music.sh ${CMD:-?} · $(date '+%Y-%m-%d %H:%M:%S') ────────"

say() { echo "[music] $*"; }
die() { echo "[music] ERROR: $*" >&2; exit 1; }

usage() {
  echo "usage: $0 minimax|acestep"
  exit 1
}

# ── pin readers (same awk shape as install_mlx.sh: comments live ABOVE keys) ──
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }

MINIMAX_REPO="PocketAiHub/MiniMax-Music3-MLX"
ACESTEP_REPO="https://github.com/ServeurpersoCom/acestep.cpp.git"
ACESTEP_GGUF_REPO="Serveurperso/ACE-Step-1.5-GGUF"
ACESTEP_GGUFS=(vae-BF16.gguf
               Qwen3-Embedding-0.6B-Q8_0.gguf
               acestep-5Hz-lm-4B-Q8_0.gguf
               acestep-v15-turbo-Q8_0.gguf)

preflight() {
  [[ "$(uname -s)" == "Darwin" ]] || die "the music engines are Apple-Silicon only (Metal/MLX)."
  [[ "$(uname -m)" == "arm64" ]] || die "Apple Silicon only (uname -m says $(uname -m))."
  local free_gb
  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (need ~${NEED_GB}GB)"
  [[ "$free_gb" -ge "$NEED_GB" ]] \
    || die "not enough free disk — need about ${NEED_GB}GB, have ${free_gb}GB."
}

# ── python + venv (the Finder-minimal-PATH rule: resolve by explicit path list) ──
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

resolve_cmake() {
  local c
  for c in "$(command -v cmake || true)" /opt/homebrew/bin/cmake /usr/local/bin/cmake \
           /usr/bin/cmake; do
    [[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 0
}

ensure_venv() {
  local py uv minor
  py="$(resolve_py)" || die "no python3 found — brew install python@3.12"
  uv="$(resolve_uv)"
  minor=$("$py" -c 'import sys; print(sys.version_info[1])')
  say "interpreter: $py (3.${minor})"
  if [[ "$minor" -lt 11 || "$minor" -gt 13 ]]; then
    say "WARN: the MLX port asks for Python 3.11-3.13; mlx may have no wheel here."
  fi
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

vpip() { "$VENV/bin/python" -m pip install --disable-pip-version-check "$@"; }

ensure_hub() {
  "$VENV/bin/python" -c 'import huggingface_hub' >/dev/null 2>&1 && return 0
  say "installing huggingface_hub into data/music-venv…"
  vpip -q -U huggingface_hub || die "could not install huggingface_hub"
}

# ── engine 1: MiniMax-Music3-MLX ─────────────────────────────────────────────
do_minimax() {
  preflight
  local rev
  rev="$(_yb music_minimax_pin)"
  [[ -n "$rev" ]] || die "build.music_minimax_pin missing from harness.yaml"
  say "pin: ${MINIMAX_REPO} @ ${rev:0:12}"

  ensure_venv
  ensure_hub

  say "downloading weights + code (~11.9GB into the HF cache; resumes if interrupted)…"
  local snap
  snap=$("$VENV/bin/python" - "$MINIMAX_REPO" "$rev" <<'PY'
import sys
from huggingface_hub import snapshot_download
print(snapshot_download(sys.argv[1], revision=sys.argv[2]))
PY
  ) || die "snapshot_download failed (network? disk?)"
  say "snapshot: $snap"
  # generate.py imports minimax_mlx_model by BARE NAME, so a partial download leaves
  # the entry point present and the module missing — a confusing runtime failure.
  [[ -f "$snap/generate.py" ]] || die "no generate.py in $snap — the repo layout changed."
  [[ -f "$snap/minimax_mlx_model.py" ]] || die "no minimax_mlx_model.py in $snap — incomplete snapshot."
  [[ -f "$snap/model_manifest.json" ]] || die "no model_manifest.json in $snap — incomplete snapshot."

  say "installing the port's OWN pins (it asks for mlx==0.30.6 — this is why the"
  say "  music venv is separate from data/mlx-venv, which runs mlx 0.32.0)…"
  vpip -q -r "$snap/requirements.txt" || die "requirements install failed — see above"

  say "verifying the port imports…"
  ( cd "$snap" && PYTHONPATH="$snap" "$VENV/bin/python" -c 'import minimax_mlx_model' ) \
    || die "the port does not import — see the traceback above"

  echo ""
  say "minimax installed. Renders run as one-shot subprocesses from the Music panel."
}

# ── engine 2: acestep.cpp ────────────────────────────────────────────────────
do_acestep() {
  preflight
  command -v git >/dev/null 2>&1 || die "git not found — xcode-select --install"
  local cmake_bin
  cmake_bin="$(resolve_cmake)"
  # Fail BEFORE anything is downloaded or cloned: a missing toolchain must cost
  # zero bytes and say exactly what to type.
  [[ -n "$cmake_bin" ]] || die "cmake not found — run: brew install cmake"
  say "cmake: $cmake_bin"

  local sha gguf_pin
  sha="$(_yb acestep_pin)"
  [[ -n "$sha" ]] || die "build.acestep_pin missing from harness.yaml"
  gguf_pin="$(_yb music_acestep_gguf_pin)"
  [[ "$gguf_pin" =~ ^[0-9a-f]{40}$ ]] \
    || die "build.music_acestep_gguf_pin must be an exact 40-character snapshot SHA"
  say "pin: acestep.cpp @ ${sha:0:12}"
  say "weights: ${ACESTEP_GGUF_REPO} @ ${gguf_pin:0:12}"

  local src="$ACE/src"
  mkdir -p "$ACE"
  if [[ ! -d "$src/.git" ]]; then
    say "fetching acestep.cpp at the pinned commit (shallow)…"
    # Fetch the exact SHA rather than a branch head: a branch would silently move
    # the thing we measured. GitHub allows fetching a reachable commit directly;
    # if that is ever refused, fall back to a full clone + checkout.
    mkdir -p "$src"
    git -C "$src" init -q
    git -C "$src" remote add origin "$ACESTEP_REPO" 2>/dev/null || true
    if git -C "$src" fetch --depth 1 origin "$sha" >/dev/null 2>&1; then
      git -C "$src" checkout -q FETCH_HEAD
    else
      say "shallow fetch-by-sha refused — falling back to a full clone…"
      rm -rf "$src"
      git clone -q "$ACESTEP_REPO" "$src" || die "clone failed"
      git -C "$src" checkout -q "$sha" || die "commit $sha not found in the clone"
    fi
    git -C "$src" submodule update --init --recursive --depth 1 \
      || die "submodule init failed"
  else
    local have
    have=$(git -C "$src" rev-parse HEAD)
    if [[ "$have" != "$sha" ]]; then
      say "clone is at ${have:0:12}, pin is ${sha:0:12} — moving it…"
      git -C "$src" fetch --depth 1 origin "$sha" >/dev/null 2>&1 \
        || git -C "$src" fetch origin >/dev/null 2>&1 \
        || die "could not fetch $sha"
      git -C "$src" checkout -q "$sha" || git -C "$src" checkout -q FETCH_HEAD \
        || die "could not check out $sha"
      git -C "$src" submodule update --init --recursive --depth 1 || true
      rm -rf "$src/build"      # a pin move invalidates the build
    else
      say "clone already at the pin."
    fi
  fi

  if [[ ! -x "$src/build/ace-synth" || ! -x "$src/build/ace-lm" ]]; then
    say "building with cmake (Metal + Accelerate auto-enabled on macOS)…"
    # NOT ./buildcpu.sh — it calls `nproc` (Linux-only) and forces -DGGML_BLAS=ON.
    "$cmake_bin" -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release \
      || die "cmake configure failed"
    "$cmake_bin" --build "$src/build" --config Release -j "$(sysctl -n hw.ncpu)" \
      || die "build failed"
  else
    say "reusing the existing build."
  fi
  [[ -x "$src/build/ace-lm" && -x "$src/build/ace-synth" ]] \
    || die "build produced no ace-lm/ace-synth — see the cmake output above"

  ensure_venv
  ensure_hub

  # The four default GGUFs (~7.7GB): downloaded into the HF cache and SYMLINKED into
  # models/, so a reinstall costs nothing and removing data/acestep never deletes the
  # weights.
  local models="$ACE/models"
  mkdir -p "$models"
  local f p
  for f in "${ACESTEP_GGUFS[@]}"; do
    if [[ -L "$models/$f" ]]; then
      p=$("$VENV/bin/python" - "$models/$f" <<'PY'
import os, sys
print(os.path.realpath(sys.argv[1]))
PY
      )
      if [[ "$p" == */snapshots/"$gguf_pin"/"$f" && -e "$models/$f" ]]; then
        say "have ${f} at the pinned snapshot"
        continue
      fi
      say "${f} is stale or broken for snapshot ${gguf_pin:0:12} — replacing the managed link"
    elif [[ -e "$models/$f" ]]; then
      die "refusing to replace non-symlink model file: $models/$f"
    fi
    say "downloading ${f}…"
    p=$("$VENV/bin/python" - "$ACESTEP_GGUF_REPO" "$f" "$gguf_pin" <<'PY'
import sys
from huggingface_hub import hf_hub_download
print(hf_hub_download(sys.argv[1], sys.argv[2], revision=sys.argv[3]))
PY
    ) || die "download of ${f} failed"
    ln -sfn "$p" "$models/$f"
  done
  for f in "${ACESTEP_GGUFS[@]}"; do
    [[ -e "$models/$f" ]] || die "missing model file after install: ${f}"
  done

  echo ""
  say "acestep installed (${sha:0:12}). Renders run as one-shot subprocesses."
}

case "$CMD" in
  minimax) do_minimax ;;
  acestep) do_acestep ;;
  *) usage ;;
esac
