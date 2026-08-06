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
[[ -n "$MLX_LM_PIN" && -n "$MLX_VLM_PIN" ]] || { echo "ERROR: build.mlx_lm_pin / build.mlx_vlm_pin missing from harness.yaml"; exit 1; }
uv pip install "mlx-lm==${MLX_LM_PIN}" "mlx-vlm==${MLX_VLM_PIN}"
deactivate

echo "[harness] mlx runtime installed:"
"$MLXV/bin/python" -c "import importlib.metadata as m; print(' mlx-lm', m.version('mlx-lm')); print(' mlx-vlm', m.version('mlx-vlm'))"
