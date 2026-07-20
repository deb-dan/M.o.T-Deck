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
    [[ -d data/hermes-venv ]] || { echo "ERROR: hermes venv missing — click Reinstall first"; exit 1; }
    # shellcheck disable=SC1091
    source data/hermes-venv/bin/activate
    # M0: ensure Hermes has a model config (written once; existing config is never touched)
    HCFG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
    if [[ ! -f "$HCFG" ]]; then
      BASE_URL=$(awk '/^  hermes_llm:/{f=1} f && /base_url:/{print $2; exit}' harness.yaml)
      MODEL=$(awk '/^  hermes_llm:/{f=1} f && /model:/{sub(/.*model:[ ]*/,""); print $1; exit}' harness.yaml)
      if [[ -z "$MODEL" ]]; then
        MODEL=$(curl -sf -m 4 "${BASE_URL%/}/models" \
          | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || true)
      fi
      if [[ -z "$MODEL" ]]; then
        echo "ERROR: could not reach ${BASE_URL} or no model available."
        echo "Open Jan, enable Settings -> Local API Server, and make sure a model is downloaded."
        exit 1
      fi
      mkdir -p "$(dirname "$HCFG")"
      printf 'model:\n  default: "%s"\n  provider: "custom"\n  base_url: "%s"\n' "$MODEL" "$BASE_URL" > "$HCFG"
      echo "[harness] wrote $HCFG (model=$MODEL endpoint=$BASE_URL)"
    fi
    ( cd vendor/hermes && \
      nohup python -m gateway.run \
        >>../../data/logs/hermes.log 2>&1 & echo $! > ../../data/hermes.pid )
    sleep 2
    if kill -0 "$(cat data/hermes.pid)" 2>/dev/null; then
      echo "[harness] hermes gateway running (pid $(cat data/hermes.pid))"
    else
      echo "ERROR: hermes gateway exited immediately. Last log lines:"
      tail -8 data/logs/hermes.log
      exit 1
    fi
    ;;
  *) echo "usage: $0 hermes|odysseus"; exit 1 ;;
esac
