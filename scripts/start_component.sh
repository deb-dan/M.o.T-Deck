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
    # M0: point Hermes's model at the harness endpoint (Jan). Patches ONLY the three
    # model.* keys, preserving the rest of an existing config; creates a minimal file if absent.
    HCFG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
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
    HCFG="$HCFG" BASE_URL="$BASE_URL" MODEL="$MODEL" python3 - <<'PYPATCH'
import os, re
path, base, model = os.environ["HCFG"], os.environ["BASE_URL"], os.environ["MODEL"]
if not os.path.exists(path):
    open(path, "w").write(f'model:\n  default: {model}\n  provider: custom\n  base_url: {base}\n')
else:
    lines = open(path).read().split("\n")
    out, in_model, seen = [], False, set()
    for ln in lines:
        if re.match(r'^model:\s*$', ln):
            in_model = True; out.append(ln); continue
        if in_model and re.match(r'^\S', ln):  # left the model block
            for k, v in (("default", model), ("provider", "custom"), ("base_url", base)):
                if k not in seen: out.append(f'  {k}: {v}')
            in_model = False
        if in_model:
            m = re.match(r'^  (default|provider|base_url):', ln)
            if m:
                k = m.group(1); seen.add(k)
                out.append({"default": f'  default: {model}', "provider": '  provider: custom',
                            "base_url": f'  base_url: {base}'}[k]); continue
        out.append(ln)
    open(path, "w").write("\n".join(out))
print(f"[harness] Hermes model -> {model} @ {base}")
PYPATCH
    PORT=9119
    pkill -f "hermes serve" 2>/dev/null || true   # clear any stale server
    sleep 1
    : > data/logs/hermes.log
    nohup hermes serve --host 127.0.0.1 --port "$PORT" >>data/logs/hermes.log 2>&1 &
    echo $! > data/hermes.pid
    up=0
    for _ in $(seq 1 25); do
      if curl -sf -m 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 \
         || nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat data/hermes.pid)" 2>/dev/null || { echo "ERROR: hermes serve exited on launch. Last log lines:"; tail -15 data/logs/hermes.log; exit 1; }
      sleep 1
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] hermes serve up on :${PORT} (model=$MODEL @ $BASE_URL)"
      echo "[harness] tool-calling proof: run scripts/test_hermes.sh"
    else
      echo "ERROR: hermes serve did not open :${PORT} within 25s. Last log lines:"
      tail -15 data/logs/hermes.log
      exit 1
    fi
    ;;
  *) echo "usage: $0 hermes|odysseus"; exit 1 ;;
esac
