#!/usr/bin/env bash
# Start the bridge (control panel + API). Components are started from the panel.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -d data/bridge-venv ]] || { echo "Run ./scripts/bootstrap.sh first."; exit 1; }
mkdir -p data/logs

# shellcheck disable=SC1091
source data/bridge-venv/bin/activate
PORT=$(awk '/^bridge:/{f=1} f && /port:/{print $2; exit}' harness.yaml)
echo "[harness] Bridge starting on http://127.0.0.1:${PORT}"
exec python -m uvicorn bridge.app:app --host 127.0.0.1 --port "${PORT}" \
  --log-config /dev/null 2>>data/logs/bridge.log
