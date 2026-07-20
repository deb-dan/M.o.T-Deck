#!/usr/bin/env bash
# Start an installed component in the background (pid tracked in data/).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"
mkdir -p data/logs

case "$NAME" in
  odysseus)
    [[ -d data/odysseus-venv ]] || { echo "ERROR: odysseus venv missing — click Install first"; exit 1; }
    ROOT="$(pwd)"
    # shellcheck disable=SC1091
    source data/odysseus-venv/bin/activate
    # Clear any stale server on the port so a restart can bind cleanly.
    lsof -ti tcp:7860 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    # Connect (idempotent): (re)wire Odysseus to the local Jan endpoint as default model,
    # picking up whatever model Jan is currently serving. Runs before the server boots.
    ( cd vendor/odysseus && python "$ROOT/scripts/seed_odysseus_jan.py" ) || true
    # Start server. cd applies to the whole subshell (Odysseus expects cwd=vendor/odysseus);
    # pid + log use ABSOLUTE paths so the earlier '../../ from wrong cwd' bug can't recur.
    (
      cd vendor/odysseus
      nohup python -m uvicorn app:app --host 127.0.0.1 --port 7860 >>"$ROOT/data/logs/odysseus.log" 2>&1 &
      echo $! > "$ROOT/data/odysseus.pid"
    )
    sleep 2
    if kill -0 "$(cat data/odysseus.pid)" 2>/dev/null; then
      echo "[harness] odysseus starting → http://127.0.0.1:7860 (login: admin / admin123 — change it)"
    else
      echo "ERROR: odysseus exited immediately. Last log lines:"; tail -15 data/logs/odysseus.log; exit 1
    fi
    ;;
  hermes)
    [[ -d data/hermes-venv ]] || { echo "ERROR: hermes venv missing — click Reinstall first"; exit 1; }
    # shellcheck disable=SC1091
    source data/hermes-venv/bin/activate
    # M0: point Hermes's model at the harness endpoint (Jan). Patches ONLY the three
    # model.* keys, preserving the rest of an existing config; creates a minimal file if absent.
    HCFG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
    BASE_URL=$(awk '/^  hermes_llm:/{f=1; next} f && /^    base_url:[[:space:]]*/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*base_url:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    MODEL=$(awk '/^  hermes_llm:/{f=1; next} f && /^    model:[[:space:]]*/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*model:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ "$MODEL" == \#* ]] && MODEL=""   # guard: never treat a stray comment as a model name
    CTXLEN=$(awk '/^  hermes_llm:/{f=1; next} f && /^    context_length:[[:space:]]*/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*context_length:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ "$CTXLEN" =~ ^[0-9]+$ ]] || CTXLEN=65536
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
    HCFG="$HCFG" BASE_URL="$BASE_URL" MODEL="$MODEL" CTXLEN="$CTXLEN" python3 - <<'PYPATCH'
import os, re
path = os.environ["HCFG"]
managed = {"default": os.environ["MODEL"], "provider": "custom",
           "base_url": os.environ["BASE_URL"], "context_length": os.environ["CTXLEN"]}
order = ["default", "provider", "base_url", "context_length"]
def block():
    return "model:\n" + "".join(f"  {k}: {managed[k]}\n" for k in order)
if not os.path.exists(path):
    open(path, "w").write(block())
else:
    lines = open(path).read().split("\n")
    out, in_model, seen = [], False, set()
    for ln in lines:
        if re.match(r'^model:\s*$', ln):
            in_model = True; out.append(ln); continue
        if in_model and re.match(r'^\S', ln):  # left the model block
            for k in order:
                if k not in seen: out.append(f'  {k}: {managed[k]}')
            in_model = False
        if in_model:
            m = re.match(r'^  (default|provider|base_url|context_length):', ln)
            if m:
                k = m.group(1); seen.add(k); out.append(f'  {k}: {managed[k]}'); continue
        out.append(ln)
    if in_model:  # model block ran to EOF
        for k in order:
            if k not in seen: out.append(f'  {k}: {managed[k]}')
    open(path, "w").write("\n".join(out))
print(f"[harness] Hermes model -> {managed['default']} @ {managed['base_url']} (ctx {managed['context_length']})")
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
