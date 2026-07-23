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
uv pip install mlx-lm mlx-vlm
deactivate

echo "[harness] mlx runtime installed:"
"$MLXV/bin/python" -c "import importlib.metadata as m; print(' mlx-lm', m.version('mlx-lm')); print(' mlx-vlm', m.version('mlx-vlm'))"
