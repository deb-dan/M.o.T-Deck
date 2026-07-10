#!/usr/bin/env bash
# Start an installed component in the background (pid tracked in data/).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"
mkdir -p data/logs

case "$NAME" in
  odysseus)
    [[ -d data/odysseus-venv ]] || { echo "not installed"; exit 1; }
    # shellcheck disable=SC1091
    source data/odysseus-venv/bin/activate
    ( cd vendor/odysseus && \
      nohup python -m uvicorn app:app --host 127.0.0.1 --port 7860 \
        >>../../data/logs/odysseus.log 2>&1 & echo $! > ../../data/odysseus.pid )
    echo "[harness] odysseus starting → http://127.0.0.1:7860"
    ;;
  hermes)
    [[ -d data/hermes-venv ]] || { echo "not installed"; exit 1; }
    # shellcheck disable=SC1091
    source data/hermes-venv/bin/activate
    ( cd vendor/hermes && \
      nohup python mcp_serve.py --port 8721 \
        >>../../data/logs/hermes.log 2>&1 & echo $! > ../../data/hermes.pid )
    echo "[harness] hermes MCP server starting on :8721 (TUI: run 'hermes' in its venv)"
    ;;
  *) echo "usage: $0 hermes|odysseus"; exit 1 ;;
esac
