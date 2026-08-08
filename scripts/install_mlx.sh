#!/usr/bin/env bash
# Create/refresh the MLX runtime venv (mlx-lm text + mlx-vlm vision servers).
# Idempotent: re-run to upgrade-safe no-op when already satisfied.
set -euo pipefail
cd "$(dirname "$0")/.."

MLXV="data/mlx-venv"

if [[ ! -x "$MLXV/bin/python" ]]; then
  uv venv "$MLXV" --python "$(command -v python3.12 || command -v python3.11 || command -v python3)"
fi

# shellcheck disable=SC1091
source "$MLXV/bin/activate"
# PINNED (project doctrine: pin everything, bump deliberately). These were the
# latest on PyPI at 2026-08-06 and are exactly what was verified working — leaving
# them unpinned meant any re-install could silently change runtime behaviour.
# Bump = edit here, reinstall, re-verify a chat turn + the MLX wire-id path
# (a future mlx-lm that adds a served-model-name flag would let bridge/app.py's
# wire_model_id() switch from path-based to alias-based identification).
# Pins come from harness.yaml build.mlx_lm_pin / build.mlx_vlm_pin (single source of
# truth shared with build_app.sh's wheelhouse + firstrun_fat.sh's offline install).
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }
MLX_LM_PIN="${MLX_LM_PIN:-$(_yb mlx_lm_pin)}"
MLX_VLM_PIN="${MLX_VLM_PIN:-$(_yb mlx_vlm_pin)}"
# mlx-audio: the MLX half of the harness-native voice capability. It already arrives
# transitively as an mlx-vlm dep, so this pin exists to make the version DELIBERATE —
# the provisioned venv carried 0.4.4 while the recon that fixed our argv surface
# (--join_audio / --output_path / --file_prefix) read 0.4.7. Naming it here upgrades
# the venv on the next install so installed reality matches the code.
MLX_AUDIO_PIN="${MLX_AUDIO_PIN:-$(_yb mlx_audio_pin)}"
# mlx-whisper: the STT half of the voice capability (Phase D dictation). Same venv on
# purpose — it shares mlx/numpy with mlx-lm and pulls no torch, so a second venv would
# only duplicate ~200MB of wheels. bridge/voice.py spawns its `mlx_whisper` console
# script from data/mlx-venv/bin by EXPLICIT path.
MLX_WHISPER_PIN="${MLX_WHISPER_PIN:-$(_yb mlx_whisper_pin)}"
[[ -n "$MLX_LM_PIN" && -n "$MLX_VLM_PIN" ]] || { echo "ERROR: build.mlx_lm_pin / build.mlx_vlm_pin missing from harness.yaml"; exit 1; }
[[ -n "$MLX_AUDIO_PIN" ]] || { echo "ERROR: build.mlx_audio_pin missing from harness.yaml"; exit 1; }
[[ -n "$MLX_WHISPER_PIN" ]] || { echo "ERROR: build.mlx_whisper_pin missing from harness.yaml"; exit 1; }
uv pip install "mlx-lm==${MLX_LM_PIN}" "mlx-vlm==${MLX_VLM_PIN}" \
               "mlx-audio==${MLX_AUDIO_PIN}" "mlx-whisper==${MLX_WHISPER_PIN}"
deactivate

echo "[harness] mlx runtime installed:"
"$MLXV/bin/python" -c "import importlib.metadata as m; print(' mlx-lm', m.version('mlx-lm')); print(' mlx-vlm', m.version('mlx-vlm')); print(' mlx-audio', m.version('mlx-audio')); print(' mlx-whisper', m.version('mlx-whisper'))"
# The console script is what bridge/voice.py spawns; say so loudly if it is missing
# (the library-import fallback exists, but a silent absence would hide a bad install).
[[ -x "$MLXV/bin/mlx_whisper" ]] \
  && echo " mlx_whisper CLI $MLXV/bin/mlx_whisper" \
  || echo " WARN: $MLXV/bin/mlx_whisper missing — dictation falls back to the library form"
