#!/usr/bin/env bash
# Stop bridge and any component processes the harness started.
set -euo pipefail
cd "$(dirname "$0")/.."

for pidfile in data/*.pid; do
  [[ -e "$pidfile" ]] || continue
  pid=$(cat "$pidfile")
  if kill -0 "$pid" 2>/dev/null; then
    echo "[harness] stopping $(basename "$pidfile" .pid) (pid $pid)"
    kill "$pid" || true
  fi
  rm -f "$pidfile"
done
pkill -f "uvicorn bridge.app:app" 2>/dev/null || true
echo "[harness] stopped."
