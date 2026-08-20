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
print(m.get("repo") or "")   # source HF repo (download entries) — MTP marker often lives here
# v2 (2026-08-20): the model's SAVED sampling + load overrides, as `key=value` tokens.
# Only EXPLICIT user values travel — an unset field keeps the engine's own default on
# the Agent/Hermes lanes, exactly as before. Junk is dropped here (values are numbers
# or one-word tokens, so a token can never contain a space and split the shell loop).
# The bridge owns the meaning of these keys: bridge/app.py SAMPLING_* / LOAD_*.
# Ranges mirror bridge/app.py SAMPLING_RANGES / LOAD_RANGES; a hand-edited registry
# carrying nonsense must never reach the launch line and fail the load.
_NUM = {"temperature": (0.0, 2.0), "top_p": (0.0, 1.0), "top_k": (0, 500),
        "min_p": (0.0, 1.0), "repeat_penalty": (1.0, 2.0), "repeat_last_n": (-1, 8192),
        "max_tokens": (1, 1048576), "seed": (-1, 2147483647),
        "ctx": (1024, 262144), "gpu_layers": (-1, 999)}
_ENUM = {"kv_quant": ("off", "q8_0", "q4_0")}
def _kv(d, keys):
    out = []
    for k in keys:
        if k not in (d or {}):
            continue
        v = (d or {})[k]
        if k == "flash_attn":
            if isinstance(v, bool):
                out.append(f"{k}={'on' if v else 'off'}")
            elif isinstance(v, str) and v.strip().lower() in ("on", "off"):
                out.append(f"{k}={v.strip().lower()}")
        elif k in _ENUM:
            if isinstance(v, str) and v.strip().lower() in _ENUM[k]:
                out.append(f"{k}={v.strip().lower()}")
        elif k in _NUM and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = _NUM[k]
            if v == v and lo <= v <= hi:
                out.append(f"{k}={v}")
    return " ".join(out)
_s = (m or {}).get("settings"); _s = _s if isinstance(_s, dict) else {}
_l = (m or {}).get("load");     _l = _l if isinstance(_l, dict) else {}
print(_kv(_s, ("temperature", "top_p", "top_k", "min_p",
               "repeat_penalty", "repeat_last_n", "max_tokens", "seed")))
print(_kv(_l, ("ctx", "gpu_layers", "flash_attn", "kv_quant")))
PYRESOLVE
) || { echo "ERROR: $(R_MODEL="$R_MODEL" python3 -c 'import os,json,sys;print("model \x27%s\x27 not in registry — run scripts/seed_registry.py or pick another model"%os.environ["R_MODEL"])')"; exit 1; }
    MODEL_PATH=$(sed -n '1p' <<<"$RESOLVED")
    MMPROJ_PATH=$(sed -n '2p' <<<"$RESOLVED")
    REG_CTX=$(sed -n '3p' <<<"$RESOLVED")
    MODEL_FORMAT=$(sed -n '4p' <<<"$RESOLVED")
    MODEL_VISION=$(sed -n '5p' <<<"$RESOLVED")
    MODEL_REPO=$(sed -n '6p' <<<"$RESOLVED")
    SAMP_KV=$(sed -n '7p' <<<"$RESOLVED")
    LOAD_KV=$(sed -n '8p' <<<"$RESOLVED")
    # Read one saved value, or empty. Deliberately EMPTY-means-unset: a caller that
    # gets nothing back emits nothing, which is what keeps engine defaults intact.
    _sv() { local k="$1" tok; for tok in $SAMP_KV; do
              [[ "${tok%%=*}" == "$k" ]] && { printf '%s' "${tok#*=}"; return 0; }
            done; return 0; }
    _lv() { local k="$1" tok; for tok in $LOAD_KV; do
              [[ "${tok%%=*}" == "$k" ]] && { printf '%s' "${tok#*=}"; return 0; }
            done; return 0; }
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
    # CTX preference: the model's SAVED load.ctx (Models → Load, v2) wins, then the
    # registry ctx, then harness.yaml ctx_size, then 65536.
    L_CTX=$(_lv ctx)
    if [[ "$L_CTX" =~ ^[0-9]+$ ]]; then CTX="$L_CTX"
    elif [[ "$REG_CTX" =~ ^[0-9]+$ ]]; then CTX="$REG_CTX"
    else CTX="$R_CTX"; fi
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
    # Repetition guard (Fable, 2026-08-06): heavily-quantized local models (gemma-31B
    # IQ4/Q4) degenerate into token loops ("C-C-C-…"). A mild repeat penalty is the
    # standard mitigation; gated on binary support like --api-key above.
    #
    # NO LONGER A MYSTERY CONSTANT (2026-08-20): these two numbers are the visible
    # `repeat_penalty` / `repeat_last_n` defaults in Models → detail → Sampling
    # (SAMPLING_DEFAULTS, bridge/app.py). llama.cpp treats a CLI sampler as the
    # server-wide DEFAULT a request inherits when it omits the field, so this stays
    # here as the engine-default FLOOR for the surfaces we do not own — the Agent
    # (Odysseus) and Hermes lanes build their own request bodies and never send a
    # penalty. The direct lane always sends one, and a request body WINS over argv.
    # Rationale + full engine surface: docs/research/2026-08-20-model-settings.md.
    #
    # v2 (2026-08-20, Debi ruling): the two numbers below are now the FALLBACK — a
    # value saved in Models → Sampling wins, and is emitted ONCE here (never twice).
    S_RP=$(_sv repeat_penalty); S_RL=$(_sv repeat_last_n)
    if grep -q -- "--repeat-penalty" data/llama-server.help.txt; then
      ARGS+=(--repeat-penalty "${S_RP:-1.1}" --repeat-last-n "${S_RL:-256}")
    fi
    # SAMPLING FLOORS (v2). Every OTHER saved sampling value also becomes a launch
    # default, so the Agent (Odysseus) and Hermes lanes — which build their own
    # request bodies and send no sampling at all — inherit the user's choice. Only
    # EXPLICIT values travel: nothing saved ⇒ nothing emitted ⇒ engine defaults,
    # byte-identical to the pre-v2 launch line. The direct lane is unaffected: a
    # request body still WINS over argv (Fable D2). Flag names + support are gated
    # against this binary's own --help, exactly like --api-key above.
    #   help refs: --temp :240, --top-p :243, --top-k :241, --min-p :244, --seed :234
    _floor() {  # $1 = flag, $2 = saved value (empty ⇒ emit nothing)
      [[ -n "$2" ]] || return 0
      grep -q -- "$1" data/llama-server.help.txt || return 0
      ARGS+=("$1" "$2")
    }
    _floor --temp  "$(_sv temperature)"
    _floor --top-p "$(_sv top_p)"
    _floor --top-k "$(_sv top_k)"
    _floor --min-p "$(_sv min_p)"
    # seed: -1 means "random" and is already the engine default — never pin it.
    S_SEED=$(_sv seed)
    if [[ "$S_SEED" =~ ^[0-9]+$ ]]; then _floor --seed "$S_SEED"; fi
    # LOAD settings (v2) — llama.cpp only; the MLX servers have no equivalent flags.
    #   -ngl :117 (number | 'auto' | 'all'), -fa :39 (on|off|auto), -ctk/-ctv :75-82
    L_NGL=$(_lv gpu_layers)
    if [[ -n "$L_NGL" ]] && grep -q -- "--n-gpu-layers" data/llama-server.help.txt; then
      # -1 is the conventional "all layers" value; translate to the engine's own token.
      [[ "$L_NGL" == "-1" ]] && L_NGL=all
      ARGS+=(--n-gpu-layers "$L_NGL")
    fi
    L_FA=$(_lv flash_attn)
    if [[ "$L_FA" == "on" || "$L_FA" == "off" ]] \
       && grep -q -- "--flash-attn" data/llama-server.help.txt; then
      ARGS+=(--flash-attn "$L_FA")
    fi
    L_KV=$(_lv kv_quant)
    if [[ -n "$L_KV" && "$L_KV" != "off" ]] \
       && grep -q -- "--cache-type-k" data/llama-server.help.txt; then
      ARGS+=(--cache-type-k "$L_KV" --cache-type-v "$L_KV")
    fi
    # MTP-variant GGUFs need speculative-decoding flags to actually GET the MTP
    # speedup (values mirror LM Studio's proven invocation on this machine).
    # Detection matches the registry id OR the source repo — an MTP model is
    # commonly published as "<org>/…-MTP-GGUF" while the per-file id carries no
    # marker (e.g. Qwen3.5-9B-Q4_0), which is why id-only detection silently gave
    # us MTP-without-acceleration. `runner.spec_mtp` (auto|on|off) overrides.
    # Kept in a SEPARATE array so a misdetection can be retried without them.
    SPEC_ARGS=()
    R_SPEC=$(awk '/^runner:/{f=1} f && /^  spec_mtp:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*spec_mtp:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ -n "$R_SPEC" ]] || R_SPEC=auto
    MTP_HIT=0
    case "$R_SPEC" in
      on|true|yes|1) MTP_HIT=1; MTP_WHY="runner.spec_mtp=$R_SPEC" ;;
      off|false|no|0) MTP_HIT=0 ;;
      *) if [[ "$R_MODEL" =~ [Mm][Tt][Pp] ]]; then MTP_HIT=1; MTP_WHY="model id"
         elif [[ -n "$MODEL_REPO" && "$MODEL_REPO" =~ [Mm][Tt][Pp] ]]; then MTP_HIT=1; MTP_WHY="source repo $MODEL_REPO"
         fi ;;
    esac
    if [[ "$MTP_HIT" == "1" ]]; then
      if grep -q -- "--spec-type" data/llama-server.help.txt; then
        SPEC_ARGS=(--jinja --spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-n-min 0 --spec-draft-p-min 0.75)
        echo "[harness] MTP detected ($MTP_WHY) — speculative decoding enabled (--spec-type draft-mtp)"
      else
        echo "[harness] WARN: MTP model but this llama-server lacks --spec-type — running WITHOUT acceleration."
        echo "[harness]   Fix: set runner.binary to a newer backend, e.g.:"
        ls -t "$HOME/.lmstudio/extensions/backends/"*/llama-server 2>/dev/null | head -1 | sed 's/^/[harness]   /'
      fi
    fi
    # Cleanup any stale server on the port — including MLX servers (format switch).
    pkill -f "llama-server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_lm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_vlm.server.*--port ${R_PORT}" 2>/dev/null || true
    lsof -ti tcp:"$R_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    # Launch + wait for readiness. Factored so a bad speculative-decoding guess can
    # be retried WITHOUT those flags instead of leaving the runner dead (spec flags
    # on a model that has no MTP heads fail the load — self-healing beats a hard stop).
    _launch_llama() {   # args: the full argv after $BIN
      nohup "$BIN" "$@" >> data/logs/runner.log 2>&1 &
      echo $! > data/runner.pid
      local i
      for i in $(seq 1 90); do
        if curl -sf -m 2 "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then return 0; fi
        sleep 2
      done
      return 1
    }
    up=0
    if _launch_llama "${ARGS[@]}" ${SPEC_ARGS[@]+"${SPEC_ARGS[@]}"}; then
      up=1
    elif [[ ${#SPEC_ARGS[@]} -gt 0 ]]; then
      echo "[harness] WARN: runner did not start WITH speculative-decoding flags —"
      echo "[harness]   this model likely has no usable MTP heads. Retrying without them."
      echo "--- runner.log tail (failed spec attempt) ---"; tail -12 data/logs/runner.log 2>/dev/null
      pkill -f "llama-server.*--port ${R_PORT}" 2>/dev/null || true
      lsof -ti tcp:"$R_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
      sleep 1
      SPEC_ARGS=()
      if _launch_llama "${ARGS[@]}"; then up=1; fi
    fi
    if [[ "$up" == "1" ]]; then
      SPEC_NOTE=""; [[ ${#SPEC_ARGS[@]} -gt 0 ]] && SPEC_NOTE=" spec=draft-mtp"
      echo "[harness] runner (llama-server) up on :$R_PORT — model=$R_MODEL ctx=$CTX${SPEC_NOTE} pid=$(cat data/runner.pid)"
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
      MLX_ARGSRC=$(ls "$MLXV"/lib/python*/site-packages/mlx_lm/server.py 2>/dev/null | head -1)
    else
      SRV="$MLXV/bin/mlx_vlm.server"
      if [[ -x "$SRV" ]]; then CMD=("$SRV"); else CMD=("$MLXV/bin/python" "-m" "mlx_vlm.server"); fi
      MLX_ARGSRC=$(ls "$MLXV"/lib/python*/site-packages/mlx_vlm/server/cli.py 2>/dev/null | head -1)
    fi
    # SAMPLING FLOORS (v2) — the MLX servers accept a SUBSET of the sampling fields on
    # their launch line and use them as the request default, which is how the Agent
    # and Hermes lanes (which send none) inherit the user's saved values. Only
    # EXPLICIT values travel. There is no --help capture here (importing mlx to print
    # it costs seconds), so each flag is gated against the installed server SOURCE —
    # the same evidence discipline, one grep of one file.
    #   mlx_lm/server.py:1818-1848 = --temp/--top-p/--top-k/--min-p/--max-tokens
    #   mlx_vlm/server/cli.py:105  = --max-tokens ONLY (no sampler flags at all)
    #   NEITHER takes a seed or a repetition flag on the launch line.
    MLX_FLOOR=()
    _mfloor() {   # $1 = flag, $2 = saved value
      [[ -n "$2" ]] || return 0
      [[ -n "$MLX_ARGSRC" ]] && grep -q -- "\"$1\"" "$MLX_ARGSRC" || return 0
      MLX_FLOOR+=("$1" "$2")
    }
    if [[ "$ENGINE" == "mlxlm" ]]; then
      _mfloor --temp  "$(_sv temperature)"
      _mfloor --top-p "$(_sv top_p)"
      _mfloor --top-k "$(_sv top_k)"
      _mfloor --min-p "$(_sv min_p)"
    fi
    # ⚠️ max_tokens is the one field where an OMITTED value genuinely hurts on these
    # servers (mlx-lm defaults to 512, mlx-vlm to 2048 — the v1 truncation bug), and
    # the Agent/Hermes lanes cannot send it. A saved value therefore rides the launch
    # line for BOTH MLX engines. Still explicit-only: nothing saved ⇒ nothing emitted.
    _mfloor --max-tokens "$(_sv max_tokens)"
    # Cleanup: kill both MLX servers AND any llama-server on this port (format switch).
    pkill -f "mlx_lm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "mlx_vlm.server.*--port ${R_PORT}" 2>/dev/null || true
    pkill -f "llama-server.*--port ${R_PORT}" 2>/dev/null || true
    lsof -ti tcp:"$R_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    nohup "${CMD[@]}" --model "$MODEL_PATH" --host 127.0.0.1 --port "$R_PORT" \
      ${MLX_FLOOR[@]+"${MLX_FLOOR[@]}"} >> data/logs/runner.log 2>&1 &
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
    lsof -ti tcp:7860 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
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
    lsof -ti tcp:8080 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
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
  voicestudio)
    # OPTIONAL voice component (AGPL-3.0-only). One FastAPI process serves the API and
    # the built SPA on the SAME port; it binds 127.0.0.1 by default and ships NO auth.
    [[ -d data/voicestudio-venv ]] || { echo "ERROR: voicestudio venv missing — click Install first"; exit 1; }
    [[ -f vendor/voicestudio/backend/main.py ]] || { echo "ERROR: vendor/voicestudio missing — click Install first"; exit 1; }
    ROOT="$(pwd)"
    VSPY="$ROOT/data/voicestudio-venv/bin/python"
    [[ -x "$VSPY" ]] || { echo "ERROR: $VSPY not executable — reinstall voicestudio"; exit 1; }
    VS_PORT=$(awk '/^  voicestudio:/{f=1; next} f && /^  [a-z]/{exit} f && /^    port:/{print $2; exit}' harness.yaml)
    [[ "$VS_PORT" =~ ^[0-9]+$ ]] || VS_PORT=3900
    # Clear the port FIRST — LISTENER-scoped only (standing ops rule: a bare
    # `lsof -ti tcp:PORT` also matches CLIENT sockets and once killed the bridge).
    lsof -ti tcp:"$VS_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    # uvicorn is the documented entrypoint; fall back to the module's own __main__
    # if this build's deps somehow lack the uvicorn CLI module.
    if "$VSPY" -c 'import uvicorn' >/dev/null 2>&1; then
      VS_CMD=(-m uvicorn backend.main:app --host 127.0.0.1 --port "$VS_PORT")
    else
      VS_CMD=(backend/main.py)
    fi
    # ── environment ─────────────────────────────────────────────────────────
    # OMNIVOICE_API_URL: the in-process MCP tools call BACK into this same backend
    # over HTTP and default to http://localhost:3900 — pin it to the port we actually
    # bound, or a non-default port silently breaks every MCP tool call.
    VS_ENV=(OMNIVOICE_BIND_HOST=127.0.0.1 OMNIVOICE_PORT="$VS_PORT"
            OMNIVOICE_API_URL="http://127.0.0.1:${VS_PORT}")
    # ffmpeg: whisperx/demucs shell out to it by NAME. If the install provisioned one
    # into our own tree (scripts/ensure_ffmpeg.sh — no Homebrew), put that dir on the
    # child's PATH. Only when the system has none, so a user's own ffmpeg still wins.
    if [[ -x "$ROOT/data/ffmpeg/bin/ffmpeg" ]] && ! command -v ffmpeg >/dev/null 2>&1; then
      VS_ENV+=(PATH="$ROOT/data/ffmpeg/bin:$PATH")
      echo "[harness] voicestudio ffmpeg → $ROOT/data/ffmpeg/bin/ffmpeg (harness-provisioned)"
    fi
    # Optional LLM (Cinematic translate / glossary extraction / dictation refinement)
    # is OpenAI-compatible. Point it at OUR runner, the same way seed_odysseus_jan.py
    # seeds Odysseus. VoiceStudio's provider registry resolves env FIRST, and the
    # TRANSLATE_* trio is the "custom (OpenAI-compatible)" provider's env triplet
    # (services/llm_providers.py @v0.4.2). We deliberately do NOT set
    # LLM_DEFAULT_PROVIDER: a lone TRANSLATE_BASE_URL only makes our runner the
    # DEFAULT, while an explicit provider chosen in VoiceStudio's own Settings still
    # wins.  ⚠️ PENDING FABLE QA.
    VS_BASE_URL=$(awk '/^runner:/{f=1} f && /^  endpoint:/{print $2; exit}' harness.yaml)
    VS_KEY=$(awk '/^runner:/{f=1} f && /^  api_key:/{print $2; exit}' harness.yaml)
    VS_MODEL=$(awk '/^runner:/{f=1} f && /^  model:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*model:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ "$VS_MODEL" == \#* ]] && VS_MODEL=""
    # Same WIRE identifier rule as the hermes branch (MLX servers need the PATH).
    if [[ -n "$VS_MODEL" ]]; then
      VS_MODEL=$(MODEL="$VS_MODEL" python3 - <<'PYWIRE'
import json, os
mid = os.environ["MODEL"]
try:
    models = json.load(open("data/models.json")).get("models", [])
except Exception:
    models = []
m = next((x for x in models if x.get("id") == mid), None)
if m and str(m.get("format") or "gguf").strip().lower() == "mlx":
    print((m.get("path") or "").strip() or mid)
else:
    print(mid)
PYWIRE
)
    fi
    # Best-effort ONLY — an unresolvable model must never block the voice component
    # (core TTS/ASR needs no LLM at all, and voicestudio has no depends_on).
    if [[ -n "$VS_BASE_URL" && -n "$VS_MODEL" ]]; then
      VS_ENV+=(TRANSLATE_BASE_URL="$VS_BASE_URL" TRANSLATE_MODEL="$VS_MODEL")
      [[ -n "$VS_KEY" ]] && VS_ENV+=(TRANSLATE_API_KEY="$VS_KEY")
      echo "[harness] voicestudio LLM → ${VS_BASE_URL} (${VS_MODEL})"
    else
      echo "[harness] voicestudio: no runner model in harness.yaml — leaving its LLM"
      echo "[harness]  unset (TTS/ASR are unaffected; set a provider in its Settings"
      echo "[harness]  or start the Runner and restart voicestudio)"
    fi
    # cd applies to the whole subshell (backend.main:app resolves from the repo root);
    # pid + log use ABSOLUTE paths so they can never land outside the project.
    (
      cd vendor/voicestudio
      nohup env "${VS_ENV[@]}" \
        "$VSPY" "${VS_CMD[@]}" >>"$ROOT/data/logs/voicestudio.log" 2>&1 &
      echo $! > "$ROOT/data/voicestudio.pid"
    )
    up=0
    # GENEROUS wait: the first boot can pull/load speech models before /health answers.
    TRIES=150
    for i in $(seq 1 "$TRIES"); do
      if curl -sf -m 2 "http://127.0.0.1:${VS_PORT}/health" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/voicestudio.pid")" 2>/dev/null || {
        echo "ERROR: voicestudio exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/voicestudio.log"
        echo "[harness] (this backend exits with code 78 when :$VS_PORT is already in use)"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[harness] voicestudio still starting… (~$((i * 2))s; first boot loads models)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] voicestudio up on http://127.0.0.1:${VS_PORT} (API + UI, loopback only, NO auth)"
    else
      echo "ERROR: voicestudio did not answer /health on :${VS_PORT} in ~5min:"
      tail -20 "$ROOT/data/logs/voicestudio.log"
      exit 1
    fi
    ;;
  voicebox)
    # OPTIONAL voice component #2 (MIT). One FastAPI process serves the JSON API, the
    # in-process MCP server at /mcp and (when built) the SPA — all on the SAME port.
    # It ships NO AUTHENTICATION, so the bind host is pinned to 127.0.0.1.
    [[ -d data/voicebox-venv ]] || { echo "ERROR: voicebox venv missing — click Install first"; exit 1; }
    [[ -f vendor/voicebox/backend/main.py ]] || { echo "ERROR: vendor/voicebox missing — click Install first"; exit 1; }
    ROOT="$(pwd)"
    VBPY="$ROOT/data/voicebox-venv/bin/python"
    [[ -x "$VBPY" ]] || { echo "ERROR: $VBPY not executable — reinstall voicebox"; exit 1; }
    VB_PORT=$(awk '/^  voicebox:/{f=1; next} f && /^  [a-z]/{exit} f && /^    port:/{print $2; exit}' harness.yaml)
    [[ "$VB_PORT" =~ ^[0-9]+$ ]] || VB_PORT=17493
    # Clear the port FIRST — LISTENER-scoped only (standing ops rule: a bare
    # `lsof -ti tcp:PORT` also matches CLIENT sockets and once killed the bridge).
    lsof -ti tcp:"$VB_PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    sleep 1
    # `python -m backend.main` (NOT plain uvicorn): that entry point calls
    # config.set_data_dir() + database.init_db() before serving.
    # ⚠️ ITS ARGPARSE DEFAULTS TO PORT 8000 — --port must ALWAYS be passed explicitly.
    # --data-dir is likewise mandatory for us: the default is Path("data") resolved
    # against the CWD, which would write the DB + generated audio INTO vendor/voicebox.
    # (There is no VOICEBOX_DATA_DIR env var at this pin; the flag is the only lever.)
    # The HuggingFace cache is left at its default so voice models are shared with the
    # rest of the machine (VOICEBOX_MODELS_DIR would fork it into a second copy).
    mkdir -p "$ROOT/data/voicebox"
    # ffmpeg: the backend shells out to it by NAME (transcription / conversion). If the
    # install provisioned one into our own tree (scripts/ensure_ffmpeg.sh — no Homebrew,
    # a static binary out of the imageio-ffmpeg wheel), put that dir on the child's
    # PATH. Only when the system has none, so a user's own ffmpeg still wins.
    # (There is no ffmpeg-path env var in voicebox at this pin — PATH is the only lever.)
    if [[ -x "$ROOT/data/ffmpeg/bin/ffmpeg" ]] && ! command -v ffmpeg >/dev/null 2>&1; then
      export PATH="$ROOT/data/ffmpeg/bin:$PATH"
      echo "[harness] voicebox ffmpeg → $ROOT/data/ffmpeg/bin/ffmpeg (harness-provisioned)"
    fi
    VB_CMD=(-m backend.main --host 127.0.0.1 --port "$VB_PORT" --data-dir "$ROOT/data/voicebox")
    # cd applies to the whole subshell (the backend package resolves from the repo
    # root); pid + log use ABSOLUTE paths so they can never land outside the project.
    (
      cd vendor/voicebox
      nohup "$VBPY" "${VB_CMD[@]}" >>"$ROOT/data/logs/voicebox.log" 2>&1 &
      echo $! > "$ROOT/data/voicebox.pid"
    )
    up=0
    # GENEROUS wait: importing torch/transformers alone takes tens of seconds, and the
    # first boot may pull speech models before /health answers.
    TRIES=150
    for i in $(seq 1 "$TRIES"); do
      if curl -sf -m 2 "http://127.0.0.1:${VB_PORT}/health" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/voicebox.pid")" 2>/dev/null || {
        echo "ERROR: voicebox exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/voicebox.log"
        echo "[harness] (a missing/broken ML dependency shows up here — voicebox's"
        echo "[harness]  dependency graph is known-fragile; reinstall is online-only)"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[harness] voicebox still starting… (~$((i * 2))s; first boot loads models)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] voicebox up on http://127.0.0.1:${VB_PORT} (API + /mcp, loopback only, NO auth)"
    else
      echo "ERROR: voicebox did not answer /health on :${VB_PORT} in ~5min:"
      tail -20 "$ROOT/data/logs/voicebox.log"
      exit 1
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
    # WIRE identifier (mirrors bridge/app.py wire_model_id + seed_odysseus_jan._wire_model):
    # llama.cpp is launched with `--alias <registry id>` so the id is the served name;
    # the MLX servers treat the request's `model` field as a model to LOAD and would
    # resolve our id on HuggingFace (404 → runner 400), so they need the model PATH,
    # byte-identical to the --model argument used at launch.
    MODEL=$(MODEL="$MODEL" python3 - <<'PYWIRE'
import json, os
mid = os.environ["MODEL"]
try:
    models = json.load(open("data/models.json")).get("models", [])
except Exception:
    models = []
m = next((x for x in models if x.get("id") == mid), None)
if m and str(m.get("format") or "gguf").strip().lower() == "mlx":
    print((m.get("path") or "").strip() or mid)
else:
    print(mid)
PYWIRE
)
    mkdir -p "$(dirname "$HCFG")"
    HCFG="$HCFG" BASE_URL="$BASE_URL" MODEL="$MODEL" CTXLEN="$CTXLEN" KEY="$KEY" python3 - <<'PYPATCH'
import os, re
path = os.environ["HCFG"]
def y(v):
    """Minimal YAML-scalar safety for the model default ONLY — it can now be a
    filesystem PATH (the MLX wire identifier), which may contain a space or '#';
    unquoted, YAML would keep the space but treat ' #' as a comment. Plain ids are
    emitted unchanged, so an existing config's formatting is untouched."""
    s = str(v)
    if s and (s != s.strip() or "#" in s or ": " in s or s[0] in "-?:,[]{}&*!|>'\"%@`"):
        return "'" + s.replace("'", "''") + "'"
    return s
managed = {"default": y(os.environ["MODEL"]), "provider": "custom",
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
    # Safety floor: warn loudly if approvals are globally disabled (warn-only —
    # 'smart' is a legitimate user choice; we never overwrite the user's mode).
    python3 - "$HCFG" <<'PYAPPR'
import sys, re
try: txt = open(sys.argv[1]).read()
except FileNotFoundError: sys.exit(0)
m = re.search(r'^approvals:\s*$(.*?)(?=^\S|\Z)', txt, re.S | re.M)
mode = None
if m:
    mm = re.search(r'^\s+mode:\s*(\S+)', m.group(1), re.M)
    if mm: mode = mm.group(1).strip('\'"')
if mode == 'off':
    print("[harness] WARNING: approvals.mode is 'off' in ~/.hermes/config.yaml — "
          "dangerous shell commands will run with NO approval card. Set 'manual' or 'smart'.")
PYAPPR
    # ── PATH-GUARD FENCE (B1): seed our pre_tool_call plugin + enable it ──────────
    # guards/harness-path-guard/ is the source of truth; it is copied (if changed)
    # into ~/.hermes/plugins/harness-path-guard/ and added to plugins.enabled, which
    # Hermes requires for user plugins (opt-in allow-list, hermes_cli/plugins.py
    # _get_enabled_plugins). policy.yaml gets {HARNESS_ROOT} substituted with this
    # repo root; {HERMES_CWD}/{TMPDIR} stay placeholders (resolved at call time).
    HGUARD_SRC="$PWD/guards/harness-path-guard"
    HGUARD_DST="${HERMES_HOME:-$HOME/.hermes}/plugins/harness-path-guard"
    if [[ -d "$HGUARD_SRC" ]]; then
      HGUARD_SRC="$HGUARD_SRC" HGUARD_DST="$HGUARD_DST" HARNESS_ROOT="$PWD" \
        HCFG="$HCFG" python3 - <<'PYGUARD'
import os, re, shutil, tempfile
src, dst = os.environ["HGUARD_SRC"], os.environ["HGUARD_DST"]
root, cfg = os.environ["HARNESS_ROOT"], os.environ["HCFG"]
os.makedirs(dst, exist_ok=True)
changed = []

def write_if_changed(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except Exception:
        pass
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True

for name in ("plugin.yaml", "__init__.py", "README.md"):
    s = os.path.join(src, name)
    if os.path.exists(s):
        if write_if_changed(os.path.join(dst, name),
                            open(s, encoding="utf-8").read()):
            changed.append(name)
pol = os.path.join(src, "policy.yaml")
if os.path.exists(pol):
    text = open(pol, encoding="utf-8").read().replace("{HARNESS_ROOT}", root)
    if write_if_changed(os.path.join(dst, "policy.yaml"), text):
        changed.append("policy.yaml")
# Drop stale bytecode so a refreshed __init__.py is definitely the code that runs.
shutil.rmtree(os.path.join(dst, "__pycache__"), ignore_errors=True)

# plugins.enabled must list the plugin (user plugins are opt-in). yaml round-trip,
# atomic write, other keys preserved — same discipline as the mcp_servers write.
def enable_in_config(path):
    try:
        import yaml
    except Exception:
        print("[harness] WARNING: PyYAML unavailable — cannot verify plugins.enabled")
        return None
    try:
        data = yaml.safe_load(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}
    except Exception as exc:
        print("[harness] WARNING: could not parse %s (%s) — plugins.enabled untouched" % (path, exc))
        return None
    if not isinstance(data, dict):
        data = {}
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
        data["plugins"] = plugins
    enabled = plugins.get("enabled")
    if not isinstance(enabled, list):
        enabled = []
    if "harness-path-guard" in [str(x) for x in enabled]:
        return False
    enabled.append("harness-path-guard")
    plugins["enabled"] = enabled
    disabled = plugins.get("disabled")
    if isinstance(disabled, list) and "harness-path-guard" in [str(x) for x in disabled]:
        plugins["disabled"] = [x for x in disabled if str(x) != "harness-path-guard"]
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
    os.replace(tmp, path)
    return True

added = enable_in_config(cfg)
bits = []
if changed: bits.append("seeded " + ", ".join(changed))
if added: bits.append("enabled in plugins.enabled")
print("[harness] path-guard plugin: " + ("; ".join(bits) if bits else "up to date"))
PYGUARD
    else
      echo "[harness] WARNING: guards/harness-path-guard missing — file writes are UNFENCED"
    fi
    PORT=9119
    # `hermes dashboard` = same server as `hermes serve` PLUS Hermes's own web UI
    # (embedded chat, live tool feed, approvals, sessions). --no-open: we embed it in
    # the Harness tab, not a browser. --skip-build: serve the prebuilt web_dist from
    # install (no npm at start time). If web_dist is missing it degrades to headless
    # (API only), so a missing build never blocks startup.
    hermes dashboard --stop >/dev/null 2>&1 || true      # clean stop of any web server
    pkill -f "hermes (dashboard|serve)" 2>/dev/null || true
    lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
    sleep 1
    : > data/logs/hermes.log
    # Deterministic dashboard session token (Hermes chat lane): the dashboard seeds
    # its _SESSION_TOKEN from HERMES_DASHBOARD_SESSION_TOKEN (the same trick Hermes's
    # own desktop shell uses), so the Bridge can auth the /api/ws?token=<...> gateway.
    # Precedence: harness.yaml components.hermes.dashboard_token override → else
    # generate ONCE into data/hermes.token (chmod 600) and reuse on every start.
    HTOKEN=$(awk '/^  hermes:/{f=1; next} f && /^  [a-z]/{exit} f && /^    dashboard_token:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*dashboard_token:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    if [[ -z "$HTOKEN" ]]; then
      if [[ ! -s data/hermes.token ]]; then
        python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > data/hermes.token
        chmod 600 data/hermes.token
      fi
      HTOKEN=$(cat data/hermes.token)
    fi
    # HERMES_DESKTOP=1: make the dashboard run its OWN cron ticker so scheduled jobs
    # fire without a running messaging gateway (Hermes has no standalone cron daemon —
    # normally the gateway fires cron). Side effects of this flag: it also exposes two
    # desktop-only tools (read_terminal/close_terminal) that are inert outside the
    # Electron app, and adds minor desktop framing to the system prompt. NOTE: if the
    # gateway is later run as a component, BOTH would fire cron (no cross-process lock)
    # → dedupe then (single ticker). See CLAUDE.md.
    nohup env HERMES_DESKTOP=1 HERMES_DASHBOARD_SESSION_TOKEN="$HTOKEN" hermes dashboard --no-open --skip-build --host 127.0.0.1 --port "$PORT" >>data/logs/hermes.log 2>&1 &
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
  *) echo "usage: $0 runner|hermes|odysseus|searxng|voicestudio|voicebox"; exit 1 ;;
esac
