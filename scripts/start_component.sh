#!/usr/bin/env bash
# Start an installed component in the background (pid tracked in data/).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"
mkdir -p data/logs

case "$NAME" in
  runner)
    R_ADAPTER=$(awk '/^runner:/{f=1} f && /^  adapter:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*adapter:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ -n "$R_ADAPTER" ]] || R_ADAPTER=auto
    # jan retired 2026-07-23 (cleanup 3.1d) — the harness owns its own llama-server
    # binary + model files now. Only llamacpp | mlx | auto are valid; anything else
    # errors loudly rather than silently falling through.
    case "$R_ADAPTER" in
      llamacpp|mlx|auto) ;;
      *) echo "ERROR: unknown adapter '$R_ADAPTER' — llamacpp|mlx|auto"; exit 1 ;;
    esac
    # adapter is llamacpp | mlx | auto — all consult OUR registry. Resolve the active
    # model's path / mmproj / ctx / format / vision FIRST, then pick the engine.
    R_PORT=$(awk '/^runner:/{f=1} f && /^  port:/{print $2; exit}' harness.yaml)
    R_KEY=$(awk '/^runner:/{f=1} f && /^  api_key:/{print $2; exit}' harness.yaml)
    R_CTX=$(awk '/^runner:/{f=1} f && /^  ctx_size:/{print $2; exit}' harness.yaml)
    R_MODEL=$(awk '/^runner:/{f=1} f && /^  model:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*model:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    R_BIN=$(awk '/^runner:/{f=1} f && /^  binary:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*binary:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ "$R_CTX" =~ ^[0-9]+$ ]] || R_CTX=65536
    [[ -n "$R_MODEL" ]] || { echo "ERROR: runner.model not set in harness.yaml"; exit 1; }
    # Ensure the registry exists.
    [[ -f data/models.json ]] || python3 scripts/seed_registry.py
    # Resolve the model from the registry (path / mmproj / ctx / format / vision).
    # MLX models are DIRECTORIES (safetensors); GGUF models are files — validate
    # accordingly so the auto/mlx path resolves an mlx model dir.
    RESOLVED=$(R_MODEL="$R_MODEL" python3 - <<'PYRESOLVE'
import os, json, sys
mid = os.environ["R_MODEL"]
try:
    models = json.load(open("data/models.json")).get("models", [])
except Exception:
    models = []
m = next((x for x in models if x.get("id") == mid), None)
fmt = (m or {}).get("format", "gguf")
path = (m or {}).get("path")
ok = bool(m and path) and (os.path.isdir(path) if fmt == "mlx" else os.path.isfile(path))
if not ok:
    sys.stderr.write(f"model '{mid}' not in registry — run scripts/seed_registry.py or pick another model\n")
    sys.exit(1)
print(m["path"])
print(m.get("mmproj") or "")
print(m.get("ctx") if m.get("ctx") not in (None, "") else "")
print(fmt)
print("true" if m.get("vision") else "false")
PYRESOLVE
) || { echo "ERROR: $(R_MODEL="$R_MODEL" python3 -c 'import os,json,sys;print("model \x27%s\x27 not in registry — run scripts/seed_registry.py or pick another model"%os.environ["R_MODEL"])')"; exit 1; }
    MODEL_PATH=$(sed -n '1p' <<<"$RESOLVED")
    MMPROJ_PATH=$(sed -n '2p' <<<"$RESOLVED")
    REG_CTX=$(sed -n '3p' <<<"$RESOLVED")
    MODEL_FORMAT=$(sed -n '4p' <<<"$RESOLVED")
    MODEL_VISION=$(sed -n '5p' <<<"$RESOLVED")
    # Pick the effective engine.
    case "$R_ADAPTER" in
      auto)
        if [[ "$MODEL_FORMAT" == "mlx" && "$MODEL_VISION" == "true" ]]; then ENGINE=mlxvlm
        elif [[ "$MODEL_FORMAT" == "mlx" ]]; then ENGINE=mlxlm
        else ENGINE=llamacpp; fi ;;
      llamacpp) ENGINE=llamacpp ;;
      mlx)
        if [[ "$MODEL_VISION" == "true" ]]; then ENGINE=mlxvlm; else ENGINE=mlxlm; fi ;;
      *) ENGINE=llamacpp ;;
    esac
    case "$ENGINE" in
      llamacpp)
    # llama-server (llama.cpp) direct — deterministic, visible process, our registry.
    # Resolve the llama-server binary.
    if [[ -z "$R_BIN" ]]; then
      # SHARED binary-discovery order (keep identical in bridge/app.py aux_start):
      #   explicit runner.binary → OUR pin (data/llamacpp) → Jan backends → LM Studio.
      BIN=""
      [[ -x "data/llamacpp/build/bin/llama-server" ]] && BIN="data/llamacpp/build/bin/llama-server"
      [[ -n "$BIN" ]] || BIN=$(ls -t "$HOME/Library/Application Support/Jan/data/llamacpp/backends/"*/macos-arm64/build/bin/llama-server 2>/dev/null | head -1)
      # Fallback: LM Studio's backends (often newer llama.cpp — needed for e.g. MTP models).
      [[ -n "$BIN" ]] || BIN=$(ls -t "$HOME/.lmstudio/extensions/backends/"*/llama-server 2>/dev/null | head -1)
      [[ -n "$BIN" ]] || { echo "ERROR: no llama-server binary found — run scripts/install_llamacpp.sh or set runner.binary in harness.yaml"; exit 1; }
    else
      BIN="$R_BIN"
      [[ -x "$BIN" ]] || { echo "ERROR: runner.binary is not executable: $BIN"; exit 1; }
    fi
    # CTX preference: registry ctx, else harness.yaml ctx_size, else 65536.
    if [[ "$REG_CTX" =~ ^[0-9]+$ ]]; then CTX="$REG_CTX"; else CTX="$R_CTX"; fi
    [[ "$CTX" =~ ^[0-9]+$ ]] || CTX=65536
    # Capture the binary's flags to decide whether --api-key is supported (cheap; every start ok).
    "$BIN" --help > data/llama-server.help.txt 2>&1 || true
    # Build argv as an ARRAY — paths contain spaces ("Application Support"); unquoted
    # expansion would split them. (Fable QA fix on the builder's draft.)
    ARGS=(--no-context-shift --host 127.0.0.1 --port "$R_PORT" --alias "$R_MODEL"
          --ctx-size "$CTX" --no-cont-batching --cache-ram -1 --fit off
          --model "$MODEL_PATH" --parallel 1)
    if [[ -n "$MMPROJ_PATH" ]]; then ARGS+=(--mmproj "$MMPROJ_PATH"); fi
    if grep -q -- "--api-key" data/llama-server.help.txt; then ARGS+=(--api-key "$R_KEY"); fi
    # MTP-variant GGUFs need speculative-decoding flags (values mirror LM Studio's
    # proven invocation on this machine). Only added when the binary supports them —
    # Jan's older backend may not; the LM Studio backend fallback above does.
    if [[ "$R_MODEL" =~ [Mm][Tt][Pp] ]]; then
      if grep -q -- "--spec-type" data/llama-server.help.txt; then
        ARGS+=(--jinja --spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-n-min 0 --spec-draft-p-min 0.75)
        echo "[harness] MTP model detected — speculative-decoding flags enabled"
      else
        echo "[harness] WARN: MTP model but this llama-server lacks --spec-type — it may fail to load."
        echo "[harness]   Fix: set runner.binary to LM Studio's newer backend, e.g.:"
        ls -t "$HOME/.lmstudio/extensions/backends/"*/llama-server 2>/dev/null | head -1 | sed 's/^/[harness]   /'
      fi
    fi
    # Cleanup any stale server on the port — including MLX servers (format switch).
    pkill -f "llama-server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_lm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_vlm.server.*--port ${R_PORT}" 2>/dev/null || true
    lsof -ti tcp:"$R_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    # Launch (argv replicates Jan's proven-working invocation on this machine).
    nohup "$BIN" "${ARGS[@]}" >> data/logs/runner.log 2>&1 &
    echo $! > data/runner.pid
    up=0
    TRIES=90
    for _ in $(seq 1 "$TRIES"); do
      if curl -sf -m 2 "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then up=1; break; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] runner (llama-server) up on :$R_PORT — model=$R_MODEL ctx=$CTX pid=$(cat data/runner.pid)"
    else
      echo "ERROR: runner (llama-server) did not become ready on :${R_PORT} in ~3min."
      echo "--- runner.log tail ---"; tail -20 data/logs/runner.log 2>/dev/null
      exit 1
    fi
    ;;
      mlxlm|mlxvlm)
    # Apple MLX servers (mlx-lm text / mlx-vlm vision) — loopback only, no api-key,
    # context comes from the model config (no --ctx flag).
    MLXV="data/mlx-venv"
    if [[ ! -x "$MLXV/bin/python" ]]; then bash scripts/install_mlx.sh; fi
    if [[ "$ENGINE" == "mlxlm" ]]; then
      SRV="$MLXV/bin/mlx_lm.server"
      if [[ -x "$SRV" ]]; then CMD=("$SRV"); else CMD=("$MLXV/bin/python" "-m" "mlx_lm.server"); fi
    else
      SRV="$MLXV/bin/mlx_vlm.server"
      if [[ -x "$SRV" ]]; then CMD=("$SRV"); else CMD=("$MLXV/bin/python" "-m" "mlx_vlm.server"); fi
    fi
    # Cleanup: kill both MLX servers AND any llama-server on this port (format switch).
    pkill -f "mlx_lm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_vlm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "llama-server.*--port ${R_PORT}" 2>/dev/null || true
    lsof -ti tcp:"$R_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    nohup "${CMD[@]}" --model "$MODEL_PATH" --host 127.0.0.1 --port "$R_PORT" >> data/logs/runner.log 2>&1 &
    echo $! > data/runner.pid
    up=0
    TRIES=150
    for _ in $(seq 1 "$TRIES"); do
      if curl -sf -m 2 "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then up=1; break; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] runner ($ENGINE) up on :$R_PORT — model=$R_MODEL pid=$(cat data/runner.pid) (loopback only, no auth)"
    else
      echo "ERROR: runner ($ENGINE) did not become ready on :${R_PORT} in ~5min."
      echo "--- runner.log tail ---"; tail -20 data/logs/runner.log 2>/dev/null
      exit 1
    fi
    ;;
    esac
    ;;
  odysseus)
    [[ -d data/odysseus-venv ]] || { echo "ERROR: odysseus venv missing — click Install first"; exit 1; }
    ROOT="$(pwd)"
    # shellcheck disable=SC1091
    source data/odysseus-venv/bin/activate
    # Clear any stale server on the port so a restart can bind cleanly.
    lsof -ti tcp:7860 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    # Connect (idempotent): (re)wire Odysseus to the harness RUNNER endpoint (:6767 + key)
    # as default model. Runs before the server boots.
    R_ENDPOINT=$(awk '/^runner:/{f=1} f && /^  endpoint:/{print $2; exit}' harness.yaml)
    R_KEY=$(awk '/^runner:/{f=1} f && /^  api_key:/{print $2; exit}' harness.yaml)
    ( cd vendor/odysseus && JAN_BASE_URL="$R_ENDPOINT" JAN_API_KEY="$R_KEY" python "$ROOT/scripts/seed_odysseus_jan.py" ) || true
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
  searxng)
    [[ -d data/searxng-venv ]] || { echo "ERROR: searxng venv missing — run scripts/install_searxng.sh"; exit 1; }
    ROOT="$(pwd)"
    lsof -ti tcp:8080 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    nohup env SEARXNG_SETTINGS_PATH="$ROOT/data/searxng/settings.yml" \
      "$ROOT/data/searxng-venv/bin/python" -m searx.webapp \
      >>"$ROOT/data/logs/searxng.log" 2>&1 &
    echo $! > "$ROOT/data/searxng.pid"
    up=0
    for _ in $(seq 1 15); do
      if curl -sf -m 2 "http://127.0.0.1:8080/" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/searxng.pid")" 2>/dev/null || { echo "ERROR: searxng exited on launch:"; tail -10 "$ROOT/data/logs/searxng.log"; exit 1; }
      sleep 1
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] searxng up on :8080 (private search; Odysseus uses it automatically)"
    else
      echo "ERROR: searxng did not answer on :8080 in ~15s:"; tail -10 "$ROOT/data/logs/searxng.log"; exit 1
    fi
    ;;
  hermes)
    [[ -d data/hermes-venv ]] || { echo "ERROR: hermes venv missing — click Reinstall first"; exit 1; }
    # shellcheck disable=SC1091
    source data/hermes-venv/bin/activate
    # M1: point Hermes at the harness RUNNER endpoint (:6767 + key). Patches ONLY the
    # managed model.* keys, preserving the rest of an existing config; creates minimal if absent.
    HCFG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
    BASE_URL=$(awk '/^runner:/{f=1} f && /^  endpoint:/{print $2; exit}' harness.yaml)
    KEY=$(awk '/^runner:/{f=1} f && /^  api_key:/{print $2; exit}' harness.yaml)
    MODEL=$(awk '/^runner:/{f=1} f && /^  model:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*model:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    CTXLEN=$(awk '/^runner:/{f=1} f && /^  ctx_size:/{print $2; exit}' harness.yaml)
    [[ "$MODEL" == \#* ]] && MODEL=""   # guard: never treat a stray comment as a model name
    [[ "$CTXLEN" =~ ^[0-9]+$ ]] || CTXLEN=65536
    if [[ -z "$MODEL" ]]; then
      MODEL=$(curl -sf -m 4 -H "Authorization: Bearer $KEY" "${BASE_URL%/}/models" \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || true)
    fi
    if [[ -z "$MODEL" ]]; then
      echo "ERROR: could not reach the runner at ${BASE_URL} or no model available."
      echo "Start the Runner first (panel → Runner → Start)."
      exit 1
    fi
    mkdir -p "$(dirname "$HCFG")"
    HCFG="$HCFG" BASE_URL="$BASE_URL" MODEL="$MODEL" CTXLEN="$CTXLEN" KEY="$KEY" python3 - <<'PYPATCH'
import os, re
path = os.environ["HCFG"]
managed = {"default": os.environ["MODEL"], "provider": "custom",
           "base_url": os.environ["BASE_URL"], "api_key": os.environ["KEY"],
           "context_length": os.environ["CTXLEN"]}
order = ["default", "provider", "base_url", "api_key", "context_length"]
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
            m = re.match(r'^  (default|provider|base_url|api_key|context_length):', ln)
            if m:
                k = m.group(1); seen.add(k); out.append(f'  {k}: {managed[k]}'); continue
        out.append(ln)
    if in_model:  # model block ran to EOF
        for k in order:
            if k not in seen: out.append(f'  {k}: {managed[k]}')
    open(path, "w").write("\n".join(out))
print(f"[harness] Hermes -> {managed['default']} @ {managed['base_url']} (key set, ctx {managed['context_length']})")
PYPATCH
    PORT=9119
    # `hermes dashboard` = same server as `hermes serve` PLUS Hermes's own web UI
    # (embedded chat, live tool feed, approvals, sessions). --no-open: we embed it in
    # the Harness tab, not a browser. --skip-build: serve the prebuilt web_dist from
    # install (no npm at start time). If web_dist is missing it degrades to headless
    # (API only), so a missing build never blocks startup.
    hermes dashboard --stop >/dev/null 2>&1 || true      # clean stop of any web server
    pkill -f "hermes (dashboard|serve)" 2>/dev/null || true
    lsof -ti tcp:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    : > data/logs/hermes.log
    # HERMES_DESKTOP=1: make the dashboard run its OWN cron ticker so scheduled jobs
    # fire without a running messaging gateway (Hermes has no standalone cron daemon —
    # normally the gateway fires cron). Side effects of this flag: it also exposes two
    # desktop-only tools (read_terminal/close_terminal) that are inert outside the
    # Electron app, and adds minor desktop framing to the system prompt. NOTE: if the
    # gateway is later run as a component, BOTH would fire cron (no cross-process lock)
    # → dedupe then (single ticker). See CLAUDE.md.
    nohup env HERMES_DESKTOP=1 hermes dashboard --no-open --skip-build --host 127.0.0.1 --port "$PORT" >>data/logs/hermes.log 2>&1 &
    echo $! > data/hermes.pid
    up=0
    for _ in $(seq 1 25); do
      if curl -sf -m 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 \
         || nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat data/hermes.pid)" 2>/dev/null || { echo "ERROR: hermes dashboard exited on launch. Last log lines:"; tail -15 data/logs/hermes.log; exit 1; }
      sleep 1
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] hermes dashboard up on http://127.0.0.1:${PORT} (UI + API; model=$MODEL @ $BASE_URL)"
      echo "[harness] tool-calling proof: run scripts/test_hermes.sh"
    else
      echo "ERROR: hermes dashboard did not open :${PORT} within 25s. Last log lines:"
      tail -15 data/logs/hermes.log
      exit 1
    fi
    ;;
  *) echo "usage: $0 hermes|odysseus"; exit 1 ;;
esac
