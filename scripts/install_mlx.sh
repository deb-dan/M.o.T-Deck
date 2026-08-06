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
MLX_LM_PIN="${MLX_LM_PIN:-0.31.3}"
MLX_VLM_PIN="${MLX_VLM_PIN:-0.6.10}"
uv pip install "mlx-lm==${MLX_LM_PIN}" "mlx-vlm==${MLX_VLM_PIN}"
deactivate

echo "[harness] mlx runtime installed:"
"$MLXV/bin/python" -c "import importlib.metadata as m; print(' mlx-lm', m.version('mlx-lm')); print(' mlx-vlm', m.version('mlx-vlm'))"
