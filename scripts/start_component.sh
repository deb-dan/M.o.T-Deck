#!/usr/bin/env bash
# Start an installed component in the background (pid tracked in data/).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"
mkdir -p data/logs
ROOT_ABS="$(pwd)"

# ── PORT OWNERSHIP ────────────────────────────────────────────────────────────
# A LISTENER-scoped kill is still a kill of SOMEBODY ELSE'S process when the port
# collides: Debi's STANDALONE Unsloth app listens on :8888 and our own start was
# killing it every time. So establish ownership BEFORE killing.
# Owned iff  (a) the pid is the one in data/<component>.pid, OR
#            (b) the command line names a path inside OUR tree (data/ or vendor/), OR
#            (c) it matches a narrow per-component signature (only where our own
#                launch legitimately runs a binary from outside the tree).
# NOT owned → refuse loudly and exit non-zero rather than kill a stranger.
# ⛔ THERE IS NO KILL BY NAME IN THIS FILE (CLAUDE.md PROCESS-KILL RULE; U19). Stopping
# a previous instance goes through _reap_pidfile (the pid WE wrote, identity re-verified
# before the signal); clearing a port goes through _clear_port (ownership-checked, and a
# port held by a stranger REFUSES the start instead of being cleared). `pkill`/`killall`
# and `hermes dashboard --stop` (which scans for every `hermes dashboard|serve` on the
# machine and kills them) are banned here and fenced by
# bridge/contract_tests/test_no_name_kills_contract.py.
# HARNESS_PORT_TAKEOVER=1 restores the old unconditional behaviour.
_proc_cmd() { ps -o command= -p "$1" 2>/dev/null | tr '\n' ' '; }

# Pure string logic, exposed for tests via `start_component.sh --owner-check <comp> <cmd>`.
_cmd_looks_like_ours() {   # <component> <command line>
  local comp="$1" cmd="$2"
  # A process that vanished between the probe and the check has nothing to protect.
  [[ -z "$cmd" ]] && return 0
  case "$cmd" in
    *"${ROOT_ABS}/data/"*|*"${ROOT_ABS}/vendor/"*) return 0 ;;
  esac
  case "$comp" in
    # runner.binary may legitimately point at a backend OUTSIDE the tree (the
    # LM Studio fallback), so the engine name is the honest signature here. It is
    # narrowed by the port: this only decides who may hold runner.port. Ledger U19c
    # tracks tightening it to "the binary harness.yaml actually configured".
    runner|aux)
      case "$cmd" in *llama-server*|*mlx_lm.server*|*mlx_vlm.server*) return 0 ;; esac ;;
    # hermes may already be running from a DIFFERENT harness root (repo vs snapshot),
    # which ROOT_ABS alone would not match — so widen the evidence, but keep it a
    # PATH: our Hermes is always the one installed into a harness's data/hermes-venv.
    # ⛔ NO NAME SIGNATURE (U19, 2026-08-29). "hermes dashboard" in a command line is
    # exactly the process this guard exists to PROTECT: Debi runs a standalone Hermes
    # out of ~/.hermes/hermes-agent/venv, and matching it by name is how our Start
    # would have closed her work — the Unsloth/goose-Desktop class, third strike.
    hermes)
      case "$cmd" in *"/data/hermes-venv/"*) return 0 ;; esac ;;
    # Deliberately NO name signature for unsloth/comfyui/voicebox/voicestudio: a
    # standalone install of any of them would match its own name, which is the very
    # process this guard exists to protect. Our launches all run
    # "$ROOT/data/<comp>-venv/bin/..." so the path rule above already covers them.
  esac
  return 1
}

if [[ "$NAME" == "--owner-check" ]]; then
  shift
  _cmd_looks_like_ours "${1:-}" "${2:-}"; exit $?
fi

# The ONLY sanctioned way to stop a PREVIOUS instance of one of our components: the
# pid WE recorded, whose identity is re-verified before any signal. Pids are recycled,
# so a stale pidfile must never become a stranger's death warrant — a pid that is not
# provably ours gets NO signal, just a printed line and a discarded pidfile. This is
# what replaced the `pkill -f "<product name>"` lines (U19): a name match is not
# identity, and Debi runs standalone copies of the very apps we embed.
_reap_pidfile() {   # <component> [force]
  # ⚠️ pf is assigned on its OWN line: bash's `local` declares every name in the
  # statement BEFORE assigning, so `local comp="$1" pf="…${comp}…"` reads comp while it
  # is still unset and dies under `set -u` ("comp: unbound variable"). Found by walking
  # the restart, not by reading — it aborted the whole hermes arm. _clear_port below
  # already had it right; this is the same shape, kept the same way.
  local comp="$1" force="${2:-}" pid cmd pf sig="-TERM"
  pf="data/${comp}.pid"
  [[ "$force" == "force" ]] && sig="-KILL"
  [[ -f "$pf" ]] || return 0
  pid="$(tr -cd '0-9' < "$pf" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then rm -f "$pf"; return 0; fi
  cmd="$(_proc_cmd "$pid")"
  if _cmd_looks_like_ours "$comp" "$cmd"; then
    kill "$sig" "$pid" 2>/dev/null || true
  else
    echo "[harness] ${pf} names pid ${pid} (${cmd}) — that is NOT our ${comp} (recycled pid?);"
    echo "[harness]   leaving it alone and discarding the stale pidfile."
  fi
  rm -f "$pf"
}

_clear_port() {   # <port> <component> [force]
  local port="$1" comp="$2" force="${3:-}" pid cmd pf sig="-TERM"
  [[ "$force" == "force" ]] && sig="-KILL"
  pf="data/${comp}.pid"
  for pid in $(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null); do
    if [[ "${HARNESS_PORT_TAKEOVER:-0}" == "1" ]]; then
      kill "$sig" "$pid" 2>/dev/null || true
      continue
    fi
    if [[ -f "$pf" ]] && [[ "$(cat "$pf" 2>/dev/null)" == "$pid" ]]; then
      kill "$sig" "$pid" 2>/dev/null || true
      continue
    fi
    cmd="$(_proc_cmd "$pid")"
    if _cmd_looks_like_ours "$comp" "$cmd"; then
      kill "$sig" "$pid" 2>/dev/null || true
    else
      echo "ERROR: port ${port} is held by pid ${pid} (${cmd}) which does not look like ours — refusing to kill it."
      echo "       Stop that app or set HARNESS_PORT_TAKEOVER=1 to override."
      exit 1
    fi
  done
}

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
        "max_tokens": (1, 262144), "seed": (-1, 2147483647),
        "ctx": (1024, 262144), "gpu_layers": (-1, 999), "threads": (1, 32),
        "batch": (1, 32768), "ubatch": (1, 32768),
        "rope_freq_base": (0.0, 10000000.0), "rope_freq_scale": (0.0, 100.0)}
_ENUM = {"kv_quant": ("off", "q8_0", "q4_0")}
_BOOL = ("flash_attn", "mlock", "mmap")
def _kv(d, keys):
    out = []
    for k in keys:
        if k not in (d or {}):
            continue
        v = (d or {})[k]
        if k in _BOOL:
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
print(_kv(_l, ("ctx", "gpu_layers", "flash_attn", "kv_quant", "threads",
               "batch", "ubatch", "mlock", "mmap",
               "rope_freq_base", "rope_freq_scale")))
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
      BIN=""; BIN_OWNER=""
      [[ -x "data/llamacpp/build/bin/llama-server" ]] && BIN="data/llamacpp/build/bin/llama-server"
      [[ -n "$BIN" ]] || { BIN=$(ls -t "$HOME/Library/Application Support/Jan/data/llamacpp/backends/"*/macos-arm64/build/bin/llama-server 2>/dev/null | head -1); [[ -n "$BIN" ]] && BIN_OWNER="Jan"; }
      # Fallback: LM Studio's backends (often newer llama.cpp — needed for e.g. MTP models).
      [[ -n "$BIN" ]] || { BIN=$(ls -t "$HOME/.lmstudio/extensions/backends/"*/llama-server 2>/dev/null | head -1); [[ -n "$BIN" ]] && BIN_OWNER="LM Studio"; }
      [[ -n "$BIN" ]] || { echo "ERROR: no llama-server binary found — run scripts/install_llamacpp.sh or set runner.binary in harness.yaml"; exit 1; }
    else
      BIN="$R_BIN"; BIN_OWNER=""
      [[ -x "$BIN" ]] || { echo "ERROR: runner.binary is not executable: $BIN"; exit 1; }
    fi
    # ⚠️ A FOREIGN APP'S llama-server IS NOT OUR PINNED CONTRACT (bug-echo W-04, the
    # Unsloth class crossed with the wrong-oracle class). The two fallbacks above run a
    # binary that belongs to Jan or LM Studio: a different app upgrades it whenever it
    # likes, and this harness's probe/auth expectations are pinned against ONE build.
    # That is not hypothetical — llama.cpp b10662's /v1/models started REQUIRING auth
    # where the previous build did not, and the 401 regression that caused took a session
    # to find. Silently starting a stranger's binary of unknown vintage re-opens it.
    # An EXPLICIT runner.binary is exempt: that is a person naming a binary on purpose.
    if [[ -n "${BIN_OWNER:-}" ]]; then
      L_PIN=$(awk '/^runner:/{f=1} f && /^  llamacpp_pin:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*llamacpp_pin:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
      L_BUILD=$("$BIN" --version 2>&1 | sed -n 's/.*build \([0-9][0-9]*\).*/\1/p' | head -1)
      echo "[harness] ⚠️  THE RUNNER BINARY IS NOT OURS. It belongs to ${BIN_OWNER}:"
      echo "[harness]      $BIN"
      echo "[harness]      build ${L_BUILD:-unreadable} · this harness is pinned to ${L_PIN:-(no pin set)}"
      if [[ -n "$L_PIN" && "$L_BUILD" == "${L_PIN#b}" ]]; then
        echo "[harness]      the build MATCHES the pin, so the pinned contracts hold. Using it."
      elif [[ "${HARNESS_ALLOW_FOREIGN_RUNNER:-0}" == "1" ]]; then
        echo "[harness]      HARNESS_ALLOW_FOREIGN_RUNNER=1 — starting it anyway, deliberately."
        echo "[harness]      If the model answers but the panel says the runner is down, or"
        echo "[harness]      /v1/models 401s, THIS is the first thing to suspect."
      else
        echo "ERROR: refusing to start the runner on ${BIN_OWNER}'s llama-server."
        echo "  Its build (${L_BUILD:-unreadable}) is not the one this harness is pinned"
        echo "  against (${L_PIN:-(none)}), and ${BIN_OWNER} can change it at any time"
        echo "  without telling us. Our /v1/models auth probe is pinned per build: b10662"
        echo "  made that endpoint require a key where the build before it did not (a 401"
        echo "  regression that cost a whole session to find), and the same drift in the"
        echo "  other direction reads to the panel as 'the runner is down'."
        echo "  Fix it properly:   ./scripts/install_llamacpp.sh"
        echo "  Name it on purpose: set runner.binary in harness.yaml"
        echo "  Or override, knowing the above: HARNESS_ALLOW_FOREIGN_RUNNER=1 <this command>"
        exit 1
      fi
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
    # ── NAMED API KEYS (ledger S32) ────────────────────────────────────────────
    # The harness-local key above is UNCHANGED and stays the built-in: it is what the
    # readiness poll below sends and what every internal caller uses. This adds the
    # SECOND source — the keys Debi mints in MOT Deck → API and pastes into an app's own
    # Add-Provider form (goose UI, Odysseus, OpenCode all ask for one).
    #
    # MEASURED AT OUR PIN, not assumed (b10662, 2026-08-29, scratch server on :6799):
    # `--api-key-file` takes one key per line, `#` lines are comments, and it COMBINES
    # with `--api-key` — all keys from both flags returned 200, an unknown key 401. So
    # nothing here can cost the built-in key. bridge/routers/apikeys.py carries the full
    # measurement, including the third fact: the file is read ONCE, at launch, with no
    # hot-reload in EITHER direction — which is why the stamp below exists.
    #
    # The file is GENERATED by the bridge on every mint/revoke (data/api_keys.keys), so
    # this arm only has to decide whether there is anything in it. An empty or missing
    # file emits nothing at all: an argv byte-identical to the pre-S32 one.
    # ⚠️ $ROOT_ABS, NOT $ROOT (live finding L2). `ROOT` is set PER-ARM in this script
    # (:579, :606, :630, :734 …) and the runner arm never sets it, so `$ROOT` under
    # `set -u` (:3) aborted the launch with "ROOT: unbound variable" before the model
    # was ever touched — the whole model lane down, reported to the panel as a failed
    # start. `ROOT_ABS` is the file-scope absolute root, set at :7.
    KEYFILE="$ROOT_ABS/data/api_keys.keys"
    KEYFILE_ARMED=0
    if grep -q -- "--api-key-file" data/llama-server.help.txt; then
      KEYFILE_ARMED=1     # the FLAG is supported — an empty key set is still "applied"
      if [[ -s "$KEYFILE" ]] && grep -qv '^[[:space:]]*\(#\|$\)' "$KEYFILE"; then
        ARGS+=(--api-key-file "$KEYFILE")
      fi
    fi
    # …and the PROMETHEUS COUNTERS the API page's totals come from. Disabled by default
    # (GET /metrics returns 501 without it — measured), loopback-only like the rest of
    # this server, and behind the same api-key as every other endpoint on it. Without
    # this flag the API page can show per-request rows for OUR lanes but nothing at all
    # for apps calling :6767 directly, which is the half of the traffic S32 is about.
    if grep -q -- "--metrics" data/llama-server.help.txt; then ARGS+=(--metrics); fi
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
    # v2.1 — the rest of the load surface. Same two rules as everything above:
    # EXPLICIT-ONLY (nothing saved ⇒ nothing emitted ⇒ engine defaults intact) and
    # EVIDENCE-GATED against this binary's own --help. `_floor` is reused verbatim
    # for the value-taking flags; the two boolean flags are their own shape.
    #   -t :7, -b :29, -ub :31, --rope-freq-base :51, --rope-freq-scale :54
    _floor --threads      "$(_lv threads)"
    _floor --batch-size   "$(_lv batch)"
    _floor --ubatch-size  "$(_lv ubatch)"
    _floor --rope-freq-base  "$(_lv rope_freq_base)"
    _floor --rope-freq-scale "$(_lv rope_freq_scale)"
    # --mlock takes no value and has NO --no-mlock counterpart (help :87), so an
    # explicit "off" correctly emits nothing: off IS the engine default.
    if [[ "$(_lv mlock)" == "on" ]] && grep -q -- "--mlock" data/llama-server.help.txt; then
      ARGS+=(--mlock)
    fi
    # --mmap / --no-mmap are BOTH documented (help :89), so both directions are
    # emitted explicitly rather than one being an unspoken default.
    L_MMAP=$(_lv mmap)
    if [[ -n "$L_MMAP" ]] && grep -q -- "--no-mmap" data/llama-server.help.txt; then
      if [[ "$L_MMAP" == "on" ]]; then ARGS+=(--mmap); else ARGS+=(--no-mmap); fi
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
    # Two steps, both identity-bound: OUR last runner by its pidfile (catches one that
    # is hung mid-load and therefore not listening yet), then the port itself, which
    # refuses rather than kills when a stranger holds it. (Was three `pkill -f
    # "<engine>.*--port"` lines: a pattern match, not identity — U19.)
    _reap_pidfile runner force
    _clear_port "$R_PORT" runner force
    sleep 1
    # Launch + wait for readiness. Factored so a bad speculative-decoding guess can
    # be retried WITHOUT those flags instead of leaving the runner dead (spec flags
    # on a model that has no MTP heads fail the load — self-healing beats a hard stop).
    _launch_llama() {   # args: the full argv after $BIN
      nohup "$BIN" "$@" >> data/logs/runner.log 2>&1 &
      echo $! > data/runner.pid
      # THE APPLIED STAMP (S32). b10662 reads --api-key-file exactly ONCE, at this
      # instant — adding a key to the file afterwards does not admit it and removing one
      # does not revoke it (both directions measured). So this records the DIGEST of the
      # key set THIS process was launched with, and the panel compares it against the
      # file on disk to say "active after the runner restarts" as a fact rather than a
      # guess. It is the sorted key set that is hashed, never a key: the stamp is
      # 64 hex characters and reveals nothing.
      #
      # The digest is computed in awk-free plain shell + shasum so this arm keeps
      # working with no python on PATH; the bridge computes the identical value in
      # bridge/routers/apikeys.py:digest() and a test asserts the two agree.
      #
      # ⚠️ ONLY WHEN THE FLAG IS ACTUALLY SUPPORTED. On a binary with no
      # --api-key-file the named keys do NOT work, and stamping them "applied" would
      # make the panel say they are live — the LIE-TO-USER class. No stamp means the
      # panel keeps saying "restart the runner", which is at least not false.
      if [[ "$KEYFILE_ARMED" == "1" ]]; then
        if [[ -s "$KEYFILE" ]]; then
          grep -v '^[[:space:]]*\(#\|$\)' "$KEYFILE" | LC_ALL=C sort \
            | shasum -a 256 | cut -d' ' -f1 > data/api_keys.applied
        else
          : | shasum -a 256 | cut -d' ' -f1 > data/api_keys.applied
        fi
      fi
      local i
      for i in $(seq 1 90); do
        # ⚠️ THE HEADER IS LOAD-BEARING (ledger U21, fixed 2026-08-29). We launch with
        # `--api-key "$R_KEY"` (:292) and llama.cpp b10662 made /v1/models REQUIRE it —
        # the same regression this file already documents at :247/:267. Polling without
        # it 401s forever: a runner that was serving in ~1.3s still burned the whole
        # 90×2s budget and then EXITED NON-ZERO, i.e. "the runner did not come up" about
        # a runner that was up. -f treats 401 as failure, which is what hid it.
        if curl -sf -m 2 -H "Authorization: Bearer ${R_KEY}" \
             "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then return 0; fi
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
      _reap_pidfile runner force
      _clear_port "$R_PORT" runner force
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
    # Cleanup: our own previous runner (whatever engine it was — the format switch
    # case) by pidfile, then the port, ownership-checked. Identity, never a name (U19).
    _reap_pidfile runner force
    _clear_port "$R_PORT" runner force
    sleep 1
    nohup "${CMD[@]}" --model "$MODEL_PATH" --host 127.0.0.1 --port "$R_PORT" \
      ${MLX_FLOOR[@]+"${MLX_FLOOR[@]}"} >> data/logs/runner.log 2>&1 &
    echo $! > data/runner.pid
    up=0
    TRIES=150
    for _ in $(seq 1 "$TRIES"); do
      # The MLX servers take no api-key (loopback only), so this header is inert here —
      # carried anyway so EVERY readiness poll in this file looks the same and the next
      # engine that starts requiring auth cannot re-open U21's 3-minute false "down".
      if curl -sf -m 2 -H "Authorization: Bearer ${R_KEY}" \
           "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then up=1; break; fi
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
    _clear_port 7860 odysseus
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
    _clear_port 8080 searxng
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
    _clear_port "$VS_PORT" voicestudio
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
    _clear_port "$VB_PORT" voicebox
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
  comfyui)
    # OPTIONAL image/video component (GPL-3.0, arm's length: separate process, HTTP only).
    # One aiohttp process serves the SPA and the API on the SAME port; the SPA arrives as a
    # pip package (comfyui-frontend-package), so there is no npm/bun build to go missing.
    [[ -d data/comfyui-venv ]] || { echo "ERROR: comfyui venv missing — click Install first"; exit 1; }
    [[ -f vendor/comfyui/main.py ]] || { echo "ERROR: vendor/comfyui missing — click Install first"; exit 1; }
    ROOT="$(pwd)"
    CUPY="$ROOT/data/comfyui-venv/bin/python"
    [[ -x "$CUPY" ]] || { echo "ERROR: $CUPY not executable — reinstall comfyui"; exit 1; }
    CU_PORT=$(awk '/^  comfyui:/{f=1; next} f && /^  [a-z]/{exit} f && /^    port:/{print $2; exit}' harness.yaml)
    [[ "$CU_PORT" =~ ^[0-9]+$ ]] || CU_PORT=8188
    # Clear the port FIRST — LISTENER-scoped only (standing ops rule: a bare
    # `lsof -ti tcp:PORT` also matches CLIENT sockets and once killed the bridge).
    _clear_port "$CU_PORT" comfyui
    sleep 1
    # --base-directory is MANDATORY: without it ComfyUI creates models/ output/ input/
    # user/ NEXT TO main.py, i.e. inside vendor/. Same trap class as voicebox's --data-dir.
    # --disable-auto-launch stops it opening a browser window behind the native tab.
    # ⚠️ --base-directory does NOT create the tree it points at, and ComfyUI's own
    # startup does not create all of it either — so these MUST exist before launch:
    #   custom_nodes  main.py::execute_prestartup_script() does an UNGUARDED
    #                 os.listdir() on every folder_paths.get_folder_paths("custom_nodes")
    #                 entry (= <base>/custom_nodes at v0.33.3) → FileNotFoundError and an
    #                 instant crash on a fresh base dir. This is the crash Debi hit.
    #   user          holds the sqlite db we point --database-url at (below); sqlalchemy
    #                 will not create a missing parent directory.
    #   models input output
    #                 created lazily by upstream (folder_paths creates input/ inside a
    #                 bare try/except; the rest only on first save) — pre-created so the
    #                 tree Debi is told to drop checkpoints into actually exists.
    for d in custom_nodes user models models/checkpoints input output; do
      mkdir -p "$ROOT/data/comfyui/${d}"
    done
    # ⚠️ --database-url is NOT covered by --base-directory: at v0.33.3 its default is
    # computed from comfy/cli_args.py's OWN __file__ (os.path.join(dirname(__file__),
    # "..", "user", "comfyui.db")), i.e. vendor/comfyui/user/comfyui.db — a write INTO
    # vendor/, the same trap class --base-directory exists to close. Point it at our
    # base dir explicitly. (It also keeps our db lock separate from any other ComfyUI
    # install on the machine — upstream refuses to share one db file between processes.)
    CU_CMD=(main.py --listen 127.0.0.1 --port "$CU_PORT"
            --base-directory "$ROOT/data/comfyui"
            --database-url "sqlite:///$ROOT/data/comfyui/user/comfyui.db"
            --disable-auto-launch)
    # cd applies to the whole subshell (main.py resolves its package imports from the repo
    # root); pid + log use ABSOLUTE paths so they can never land outside the project.
    (
      cd vendor/comfyui
      nohup "$CUPY" "${CU_CMD[@]}" >>"$ROOT/data/logs/comfyui.log" 2>&1 &
      echo $! > "$ROOT/data/comfyui.pid"
    )
    up=0
    # GENEROUS wait: importing torch alone takes tens of seconds on a cold page cache.
    TRIES=150
    for i in $(seq 1 "$TRIES"); do
      # /system_stats is a JSON API route that exists at this pin (server.py) — a cheaper,
      # less ambiguous health signal than the SPA's index page.
      if curl -sf -m 2 "http://127.0.0.1:${CU_PORT}/system_stats" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/comfyui.pid")" 2>/dev/null || {
        echo "ERROR: comfyui exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/comfyui.log"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[harness] comfyui still starting… (~$((i * 2))s; torch import is slow)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] comfyui up on http://127.0.0.1:${CU_PORT} (UI + API, loopback only, NO auth)"
      echo "[harness] base dir: $ROOT/data/comfyui — put checkpoints in models/checkpoints/"
    else
      echo "ERROR: comfyui did not answer /system_stats on :${CU_PORT} in ~5min:"
      tail -20 "$ROOT/data/logs/comfyui.log"
      exit 1
    fi
    ;;
  unsloth)
    # OPTIONAL studio component (Studio is AGPL-3.0-only; arm's length: separate process,
    # HTTP only). One FastAPI process serves the API and the React SPA on the SAME port.
    #
    # ISOLATED HOME (2026-08-28). Upstream's default home is ~/.unsloth, which Debi's
    # STANDALONE Unsloth.app (:8888) owns. Sharing it coupled the two installs: our
    # component reported the standalone's stale version string (/api/health served the
    # ~/.unsloth managed venv's PyPI dist after the CLI re-exec'd into it), and our
    # running process held that install so the standalone's own self-updater greyed out.
    # Ruling: our component gets its OWN home, data/unsloth-home. UNSLOTH_STUDIO_HOME is
    # upstream's documented override (unsloth_cli/commands/studio.py _resolve_studio_home;
    # the STUDIO_HOME alias also exists but UNSLOTH_STUDIO_HOME wins) and the backend
    # honors it everywhere — its llama.cpp/whisper.cpp engines, outputs, logs and auth
    # state all land under the custom home, never in ~/.unsloth.
    #
    # The venv the installer builds now lives AT $UNSLOTH_STUDIO_HOME/unsloth_studio —
    # exactly where the CLI looks for its "managed venv" — so `unsloth studio` serves
    # IN-PROCESS from our editable install (no re-exec into a foreign interpreter), and
    # /api/health reports OUR pinned version. Even if the in-venv detection ever missed
    # (path canonicalization), the fallback re-exec target is this same venv: isolated
    # either way.
    ROOT="$(pwd)"
    US_HOME="$ROOT/data/unsloth-home"
    US_VENV="$US_HOME/unsloth_studio"
    # FENCE: never let our launch resolve into ~/.unsloth — that home belongs 100% to
    # the standalone app. Guards against a mis-set US_HOME and against this script being
    # edited back to the shared default. (We overwrite any inherited UNSLOTH_STUDIO_HOME/
    # STUDIO_HOME below, so an env leak cannot redirect us either.)
    case "$US_HOME" in
      "$HOME/.unsloth"|"$HOME/.unsloth/"*)
        echo "ERROR: unsloth home resolves to $US_HOME — that is the STANDALONE app's home."
        echo "       Our component must use its own home under data/. Refusing to start."
        exit 1 ;;
    esac
    [[ -d "$US_VENV" ]] || {
      if [[ -d "$ROOT/data/unsloth-venv" ]]; then
        echo "ERROR: unsloth is installed in the OLD layout (data/unsloth-venv, shared"
        echo "       ~/.unsloth home). Re-run the install to provision the isolated home:"
        echo "         ./scripts/install_component.sh unsloth --yes"
      else
        echo "ERROR: unsloth venv missing — click Install first"
      fi
      exit 1; }
    [[ -f vendor/unsloth/studio/backend/run.py ]] || { echo "ERROR: vendor/unsloth missing — click Install first"; exit 1; }
    USPY="$US_VENV/bin/python"
    [[ -x "$USPY" ]] || { echo "ERROR: $USPY not executable — reinstall unsloth"; exit 1; }
    US_PORT=$(awk '/^  unsloth:/{f=1; next} f && /^  [a-z]/{exit} f && /^    port:/{print $2; exit}' harness.yaml)
    # Fallback mirrors harness.yaml's 8899 — deliberately NOT upstream's 8888, which is
    # the port Debi's STANDALONE Unsloth app listens on (the port clear below would kill it).
    [[ "$US_PORT" =~ ^[0-9]+$ ]] || US_PORT=8899
    US_DIST="$ROOT/vendor/unsloth/studio/frontend/dist"
    # REFUSE UP FRONT rather than let it die inside uvicorn: at this pin
    # studio/backend/run.py's _missing_frontend_is_fatal() aborts any launch that is not
    # --api-only when it cannot resolve a frontend/dist containing index.html.
    [[ -f "$US_DIST/index.html" ]] || {
      echo "ERROR: the Unsloth Studio SPA is not built ($US_DIST/index.html is missing)."
      echo "       Unsloth REFUSES to start a web-UI launch without it, so there is"
      echo "       nothing to serve in the tab. Rebuild it by re-running the install:"
      echo "         ./scripts/install_component.sh unsloth --yes"
      echo "       (that step needs bun; the reason any previous attempt failed is in"
      echo "        data/logs/unsloth-install.log)"
      exit 1; }
    # Clear the port FIRST — LISTENER-scoped only (standing ops rule).
    _clear_port "$US_PORT" unsloth
    sleep 1
    # `unsloth studio` (the Typer group's invoke_without_command callback) is the PLAIN
    # server launch. Deliberately NOT `unsloth studio run`: at this pin that variant
    # installs a tools-ON process-global policy, and NOT `unsloth start`, which is the
    # agent-wiring path that relocates HERMES_HOME — our Hermes is never touched.
    # Prefer the venv's console script; fall back to the module (a uv-seeded venv can
    # lack bin/ scripts — the same failure mode as bin/pip).
    if [[ -x "$US_VENV/bin/unsloth" ]]; then
      US_BIN=("$US_VENV/bin/unsloth")
    else
      US_BIN=("$USPY" -m unsloth_cli)
    fi
    US_CMD=(studio --host 127.0.0.1 --port "$US_PORT" --frontend "$US_DIST")
    # cd into the repo so run.py's own relative resolution matches an editable install;
    # pid + log use ABSOLUTE paths so they can never land outside the project.
    #
    # UNSLOTH_DISABLE_UPDATE_CHECK=1 — upstream's documented opt-out
    # (studio/backend/utils/update_status.py DISABLE_ENV_VAR). Pins move through OUR
    # installer with recorded hashes, never through in-app self-update, so the
    # "New Unsloth version" banner must not render. With =1 the backend answers
    # /api/studio/update-status with reason "disabled" (no PyPI call), skips the
    # startup llama.cpp GitHub freshness probes (main.py), and skips the release-notes
    # fetch — a fully offline boot. It does NOT gate /api/llama/update-status, so the
    # separate llama.cpp toast for ITS OWN engine (now $US_HOME/llama.cpp — never our
    # runner on 6767, never data/llamacpp, never vendor/) can still appear; suppressing
    # that at this pin would mean taking over its llama.cpp management (Settings custom
    # path), which is its UI's business.
    #
    # UNSLOTH_STUDIO_HOME — the isolation itself (see the block comment above). Set
    # unconditionally (not setdefault) so an inherited value can never point us back at
    # ~/.unsloth; STUDIO_HOME is unset for the same reason (it is upstream's alias, and
    # UNSLOTH_STUDIO_HOME winning over it is upstream behavior we'd rather not lean on).
    mkdir -p "$US_HOME"
    (
      cd vendor/unsloth
      export UNSLOTH_DISABLE_UPDATE_CHECK=1
      export UNSLOTH_STUDIO_HOME="$US_HOME"
      unset STUDIO_HOME
      nohup "${US_BIN[@]}" "${US_CMD[@]}" >>"$ROOT/data/logs/unsloth.log" 2>&1 &
      echo $! > "$ROOT/data/unsloth.pid"
    )
    up=0
    TRIES=150
    for i in $(seq 1 "$TRIES"); do
      # /api/health at this pin answers unauthenticated with a reduced payload — the
      # version/device fields need a bearer, but reachability does not.
      if curl -sf -m 2 "http://127.0.0.1:${US_PORT}/api/health" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/unsloth.pid")" 2>/dev/null || {
        echo "ERROR: unsloth exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/unsloth.log"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[harness] unsloth still starting… (~$((i * 2))s)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[harness] unsloth up on http://127.0.0.1:${US_PORT} (Studio API + SPA, loopback only)"
      echo "[harness] Studio has its OWN login; on a loopback launch its page auto-fills the"
      echo "[harness]   bootstrap credential. Change the password inside its UI."
    else
      echo "ERROR: unsloth did not answer /api/health on :${US_PORT} in ~5min:"
      tail -20 "$ROOT/data/logs/unsloth.log"
      exit 1
    fi
    ;;
  opencode)
    # OPTIONAL second coding lane (MIT). ONE prebuilt native binary; no venv, no repo.
    # It serves its OWN embedded SPA and its JSON API on the same loopback port, which
    # is exactly the tab shape — no PTY, no xterm.js, no websocket of ours.
    ROOT="$(pwd)"
    OC_BIN="$ROOT/data/opencode/bin/opencode"
    [[ -x "$OC_BIN" ]] || { echo "ERROR: opencode is not installed ($OC_BIN missing) — click Install first"; exit 1; }
    OC_PORT=$(awk '/^  opencode:/{f=1; next} f && /^  [a-z]/{exit} f && /^    port:/{print $2; exit}' harness.yaml)
    # ⚠️ upstream's OWN --port default is 0 (an ephemeral port), so this fallback is not
    # cosmetic: without an explicit --port the tab would point at a port nothing holds.
    [[ "$OC_PORT" =~ ^[0-9]+$ ]] || OC_PORT=4096
    OC_HOME="$ROOT/data/opencode/xdg"
    OC_WS="$ROOT/data/opencode-workspace"
    mkdir -p "$OC_HOME/config" "$OC_HOME/cache" "$OC_HOME/data" "$OC_HOME/state" "$OC_WS"

    # ── config fan-out: point OpenCode at OUR runner, the same way Hermes is pointed ──
    # Its global config file is <XDG_CONFIG_HOME>/opencode/opencode.json (Global.Path.config
    # = xdgConfig/opencode at the pin), which is why the XDG_* redirect below is what makes
    # this file the one it reads — we never write to ~/.config.
    # MERGE, never overwrite: only the keys we own are replaced, so anything the user adds
    # in that file (permissions, themes, other providers) survives a restart.
    OC_BASE=$(awk '/^runner:/{f=1} f && /^  endpoint:/{print $2; exit}' harness.yaml)
    OC_KEY=$(awk '/^runner:/{f=1} f && /^  api_key:/{print $2; exit}' harness.yaml)
    OC_MODEL=$(awk '/^runner:/{f=1} f && /^  model:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*model:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
    [[ "$OC_MODEL" == \#* ]] && OC_MODEL=""
    OC_CFG="$OC_HOME/config/opencode/opencode.json"
    # SECOND, REDUNDANT HOME for the same provider block: the PROJECT config.
    # config.ts:406-409 loads `opencode.json` walking up from the instance directory
    # (ConfigPaths.files, paths.ts:10-21) and merges it AFTER the global one, so the
    # workspace we always start in carries its own copy. Two independent paths to the
    # same fact: if the XDG redirect ever fails to land, the provider still exists.
    # ⚠️ the project copy deliberately carries NO `model` key — the desktop writes a
    # model choice back to the GLOBAL config (PATCH /global/config), and a project key
    # merges last, so seeding one here would stomp the user's own pick on every load.
    OC_PCFG="$OC_WS/opencode.json"
    OC_CFG="$OC_CFG" OC_PCFG="$OC_PCFG" OC_BASE="$OC_BASE" OC_KEY="$OC_KEY" OC_MODEL="$OC_MODEL" \
      HARNESS_ROOT="$ROOT" python3 scripts/seed_opencode_config.py

    # Clear the port FIRST — LISTENER-scoped and OWNERSHIP-checked (standing ops rule).
    _clear_port "$OC_PORT" opencode
    sleep 1
    # ── ANNOTATE THE LOG: the scary line that follows is EXPECTED ───────────────
    # `serve` prints "OPENCODE_SERVER_PASSWORD is not set; server is unsecured."
    # unconditionally (cli/cmd/serve.ts:17). We deliberately do NOT set that
    # variable: the server is bound to 127.0.0.1 with no auth BY DESIGN, exactly
    # like Hermes's loopback dashboard, and setting a password would gate the
    # EMBEDDED SPA that our own native tab loads — OpenCode's "Add server" dialog
    # asks for a username/password BY HAND (i18n/en.ts:354-365), so nothing would
    # supply ours and the tab would become unusable. Leaving it unset is the choice;
    # this block is what stops it reading as an alarm.
    # The delimiter matters too: this log is opened with >> below, so it ACCUMULATES
    # one block per Start. Six identical blocks mean six starts, not six servers.
    {
      echo "[harness] ----- start $(date '+%Y-%m-%d %H:%M:%S') -- loopback 127.0.0.1:${OC_PORT}, NO auth BY DESIGN"
      echo "[harness]   the 'OPENCODE_SERVER_PASSWORD is not set; server is unsecured' line below is EXPECTED:"
      echo "[harness]   we never set that variable - it would gate the embedded SPA this app's own tab loads."
      echo "[harness]   this log APPENDS: one block per Start, so N blocks = N starts, not N servers."
    } >>"$ROOT/data/logs/opencode.log"
    # `serve`, deliberately NOT `web`: at the pin both commands call the SAME
    # Server.listen with the SAME network options and the SAME embedded SPA — `web`
    # only differs by calling open() on the URL, which would pop a browser window
    # behind our native tab on every Start.
    (
      cd "$OC_WS"
      # THE CONFINEMENT. packages/core/src/global.ts derives config/cache/data/state
      # from xdg-basedir, so these four variables are the ONLY thing keeping its
      # sessions db and the provider packages it installs at runtime (@npmcli/arborist)
      # inside data/opencode instead of ~/.config and ~/.cache.
      XDG_CONFIG_HOME="$OC_HOME/config" XDG_CACHE_HOME="$OC_HOME/cache" \
      XDG_DATA_HOME="$OC_HOME/data" XDG_STATE_HOME="$OC_HOME/state" \
      OPENCODE_DISABLE_AUTOUPDATE=1 \
      nohup "$OC_BIN" serve --hostname 127.0.0.1 --port "$OC_PORT" \
        >>"$ROOT/data/logs/opencode.log" 2>&1 &
      echo $! > "$ROOT/data/opencode.pid"
    )
    up=0
    TRIES=60
    for i in $(seq 1 "$TRIES"); do
      # /global/health is its own JSON route; `/` (the embedded SPA) is the fallback so
      # a route rename at a future pin degrades to "the tab has something to show".
      if curl -sf -m 2 "http://127.0.0.1:${OC_PORT}/global/health" >/dev/null 2>&1 \
         || curl -sf -m 2 "http://127.0.0.1:${OC_PORT}/" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/opencode.pid")" 2>/dev/null || {
        echo "ERROR: opencode exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/opencode.log"
        exit 1; }
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      # WARM THE PROJECT ROW. OpenCode registers a directory as a project LAZILY, on
      # the first instance-scoped request for it (server cwd is only the default —
      # routes/instance/httpapi/middleware/workspace-routing.ts:87 → instance-store →
      # Project.fromDirectory's insert…onConflictDoUpdate, project.ts:257-289). This one
      # READ does that registration now instead of on the first page load, and writes
      # the id cache at <ws>/.git/opencode. Deliberately a GET, not `POST /session`: a
      # session per Start would leave a growing pile of empty timestamped sessions in
      # the sidebar, which is litter, not a landing.
      curl -sf -m 5 --get --data-urlencode "directory=${OC_WS}" \
        "http://127.0.0.1:${OC_PORT}/project/current" -o /dev/null 2>/dev/null \
        && echo "[harness] project registered for $OC_WS" \
        || echo "[harness] note: could not pre-register the workspace project (harmless)"
      echo "[harness] opencode up on http://127.0.0.1:${OC_PORT} (server + its own SPA, loopback, NO auth)"
      echo "[harness] workspace: $OC_WS — the only directory it is started in"
      # ── PROVIDER SELF-CHECK — the line that makes "no local model" decidable ──
      # `GET /provider` is exactly what the desktop calls on the v1 protocol
      # (app/src/context/global-sync/bootstrap.ts:232-234 -> sdk gen.ts:759) and its
      # `connected` array is computed as `id in provider.list() || credentials[id]`
      # (server/routes/instance/httpapi/handlers/provider.ts:51-60). So if our id is
      # in there, Settings -> Providers WILL list it; if it is not, the config we just
      # wrote is not the config this server read, and that is worth one loud line
      # rather than a silent empty picker.
      # rm FIRST: a leftover from a previous Start must never be read as this one's
      # answer — a stale "CONNECTED" line would be worse than no line at all.
      # ⚠️ 25s, not 8: MEASURED against the real binary, this route answers with the
      # WHOLE catalogue — 193 providers, 5.2 MB — because `all` carries every provider
      # OpenCode knows of, not just ours. It is fast over loopback, but an 8s budget was
      # one slow moment away from printing "could not read /provider" on a healthy lane.
      # `?directory=` asks in the scope the desktop itself asks in (the settings dialog
      # is directory-scoped); measured identical to the unscoped answer, so this can only
      # ever be closer to the truth, never further from it.
      rm -f "$ROOT/data/opencode-provider.json"
      curl -sf -m 25 --get --data-urlencode "directory=${OC_WS}" \
        "http://127.0.0.1:${OC_PORT}/provider" -o "$ROOT/data/opencode-provider.json" \
        2>/dev/null || :
      OC_CFGP="$OC_CFG" python3 - "$ROOT/data/opencode-provider.json" <<'PYOCCHK' || true
import json, os, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = json.load(fh)
except Exception as e:                                            # noqa: BLE001
    print("[harness] opencode provider check: could not read /provider (%s)" % e)
    raise SystemExit(0)
conn = [str(x) for x in (d.get("connected") or [])]
allp = {p.get("id"): p for p in (d.get("all") or []) if isinstance(p, dict)}
n = len((allp.get("llama.cpp") or {}).get("models") or {})
if "llama.cpp" in conn:
    # Settings -> Providers and the composer picker read the SAME payload — the
    # intersection of `all` and `connected` (app/src/hooks/use-providers.ts:52-60,
    # settings-v2/providers.tsx:48-52, context/models.tsx:40-47) — so this one word
    # answers for both surfaces at once.
    print("[harness] opencode provider check: llama.cpp CONNECTED, %d model(s) — it is"
          " in Settings -> Providers and in the model picker" % n)
else:
    # Only two things can delete a provider that is present in the config, and both are
    # now repaired above rather than merely reported; if we still land here, the config
    # we wrote is not the config this server read.
    print("[harness] opencode provider check: llama.cpp NOT CONNECTED — the model")
    print("[harness]   picker will fall back to OpenCode Zen models (e.g. Big Pickle).")
    print("[harness]   the config we wrote: %s" % os.environ.get("OC_CFGP", "?"))
    print("[harness]   what the server reports connected: %s" % (conn or "(nothing)"))
    print("[harness]   in `all` at all: %s" % ("yes" if "llama.cpp" in allp else "no"))
    print("[harness]   NOTE a running OpenCode reads its config at BOOT — if you just")
    print("[harness]   shipped harness code, Stop and Start this component (shipping is")
    print("[harness]   not restarting), then reload the tab with cmd-R.")
PYOCCHK
      rm -f "$ROOT/data/opencode-provider.json"
      # The tab does not open :${OC_PORT}/ — it opens the bridge's /opencode, a 307 into
      # OpenCode's own new-session composer for this directory, so its home screen (the
      # one that says "Nothing here yet" beside an empty Projects rail) never appears.
      # If it ever DOES appear, the manual equivalent is one click: Add project →
      # data/opencode-workspace.
      echo "[harness] the tab lands on a new session for that workspace (via the bridge's"
      echo "[harness]   /opencode redirect). If you ever see OpenCode's own empty home"
      echo "[harness]   screen instead: Add project -> $OC_WS, once."
      echo "[harness] REMINDER: OpenCode requires a TOOL-CALLING model (the green 'tools'"
      echo "[harness]   pill in Models). Without one it looks broken, not merely slower."
    else
      echo "ERROR: opencode did not answer on :${OC_PORT} in ~2min:"
      tail -20 "$ROOT/data/logs/opencode.log"
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
    # ⚠️ THE RUNNER'S ANSWER OUTRANKS harness.yaml (found live: the pin said a 27B whose
    # file Debi had deleted while the runner was serving a 4B). What the runner SERVES is
    # what answers every turn — llama.cpp ignores the request's `model` field entirely
    # (measured, ledger U13/U16) — so seeding the pinned-but-absent id would make both the
    # main slot and our "MOT Deck has X loaded" line say something untrue. The pin is the
    # fallback, for the runner-down Start (config-resident by design).
    MSRC="pinned in harness.yaml (the runner did not answer)"
    LIVE_MODEL=$(curl -sf -m 4 -H "Authorization: Bearer $KEY" "${BASE_URL%/}/models" \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])' 2>/dev/null || true)
    if [[ -n "$LIVE_MODEL" ]]; then
      [[ -n "$MODEL" && "$MODEL" != "$LIVE_MODEL" ]] && \
        echo "[harness] note: harness.yaml pins '$MODEL' but the runner is serving '$LIVE_MODEL' — using what it serves."
      MODEL="$LIVE_MODEL"
      MSRC="live from the runner"
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
    # ── WIRING HERMES TO THE RUNNER (isolation mode S-ISO-3 + ledger U12) ────────
    # ONE writer owns ~/.hermes/config.yaml's two harness surfaces:
    #   * `custom_providers:` — the named "MOT Deck (local)" row that puts our whole
    #     registry in Hermes's OWN model picker (instead of the anonymous `custom` row
    #     whose model list is a live probe — empty whenever the runner is down);
    #   * `model:`            — the main slot, now SEEDED-NOT-ENFORCED. It used to be
    #     re-asserted here on every Start, which silently reset a model the user had
    #     picked inside Hermes (U12). The script updates only what is provably ours
    #     (a marker in data/hermes_seed_state.json records ONLY values we wrote) and
    #     prints a line for every value it honoured instead.
    # Idempotent; refuses (leaving the file untouched) on an unparseable config or a
    # missing PyYAML, and says so.
    # rm FIRST: a verdict left by a PREVIOUS Start must never be read as this one's.
    rm -f data/hermes-provider.json
    HERMES_CFG="$HCFG" BASE_URL="$BASE_URL" KEY="$KEY" MODEL="$MODEL" CTXLEN="$CTXLEN" \
      HARNESS_ROOT="$PWD" python3 scripts/seed_hermes_provider.py || \
      echo "[harness] WARNING: Hermes wiring failed — check ~/.hermes/config.yaml"
    # The provider slug the seed decided ('custom:<normalized name>', or the user's
    # renamed one) — read back for the post-start picker check below.
    # ⚠️ NO FALLBACK, deliberately. Falling back to bare `custom` would make the check
    # look for a slug that ALWAYS exists (Hermes lists every unconfigured canonical
    # provider, `custom` among them, with 0 models) — so a Start where the seed refused
    # would print "IS in its own model picker" about a row that is not ours. An empty
    # slug makes the check say the truth instead: it could not verify anything.
    HPROV=$(python3 - <<'PYSLUG'
import json, os
try:
    with open(os.path.join("data", "hermes-provider.json"), encoding="utf-8") as fh:
        print(str(json.load(fh).get("slug") or "").strip())
except Exception:
    print("")
PYSLUG
)
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
    # ── LOFFICE MCP SERVER (S1): register the bridge-hosted office toolset ────────
    # docs/FABLE-LOFFICE-HERMES-TOOLS-SPEC.md §1. bridge/office_mcp.py mounts the server
    # on the EXISTING bridge port at /mcp/office; this is the config-gen step that tells
    # Hermes it is there. It runs on EVERY Hermes start, which is what makes it survive
    # a pin bump — the same reasoning as the path-guard plugin seed above.
    #
    # IDEMPOTENT: an entry that already matches does not rewrite the file at all, so the
    # yaml round-trip's one cost (comments and key order) is paid once and never again.
    # Only `mcp_servers.loffice` is touched — browsermcp, the voice servers and anything
    # Debi added by hand survive the whole-map load/store.
    #
    # ⚠️ `trust: untrusted` IS THE APPROVAL SWITCH AND IT IS NOT OPTIONAL. Hermes has no
    # per-tool approval field for MCP: write-capable tools are gated only on a server
    # marked untrusted (vendor/hermes/tools/mcp_tool.py:4017, _trust_gate_check), and
    # "write-capable" means "no annotations.readOnlyHint: true", which
    # bridge/office_mcp.py declares per tool. Drop this key and the four write tools run
    # with no approval card at all.
    #
    # ⚠️ NEVER-CLOBBER, AND THE ONE DOCUMENTED EXCEPTION (ledger U12b). Everything else
    # in this entry is seed-if-absent and a user's value is honoured with a printed
    # line — but `trust` is RE-ASSERTED on every Start, deliberately, in the same shape
    # as OpenCode's disabled_providers repair (:1023-1045). The trade is stated out
    # loud: a security fence a user can silently turn off by editing one word is not a
    # fence, this server exposes write tools into their documents, and the line below
    # says we did it (a user who really wants it trusted can say so and not Start).
    # `url` is ours too: it must point at the bridge port this harness is running on,
    # or the toolset simply 404s.
    BR_PORT=$(awk '/^bridge:/{f=1} f && /^  port:/{print $2; exit}' harness.yaml)
    BR_PORT="${BR_PORT:-8700}"
    HCFG="$HCFG" BR_PORT="$BR_PORT" python3 - <<'PYLOFFICE'
import os, tempfile
cfg, port = os.environ["HCFG"], os.environ["BR_PORT"]
try:
    import yaml
except Exception:
    print("[harness] WARNING: PyYAML unavailable — LOffice MCP server NOT registered")
    raise SystemExit(0)
url = "http://127.0.0.1:%s/mcp/office" % port
try:
    data = yaml.safe_load(open(cfg, encoding="utf-8").read()) if os.path.exists(cfg) else {}
except Exception as exc:
    print("[harness] WARNING: could not parse %s (%s) - mcp_servers untouched" % (cfg, exc))
    raise SystemExit(0)
if not isinstance(data, dict):
    data = {}
servers = data.get("mcp_servers")
if not isinstance(servers, dict):
    servers = {}
cur = servers.get("loffice")
cur = dict(cur) if isinstance(cur, dict) else None
notes = []
if cur is None:
    entry = {"url": url, "trust": "untrusted", "timeout": 120}
else:
    # Start from what is THERE — every key we do not manage (headers, env, a
    # description, anything a future Hermes adds) survives untouched.
    entry = dict(cur)
    if str(entry.get("url") or "") != url:
        if entry.get("url"):
            notes.append("url: repointed %s -> %s (it must match this bridge)"
                         % (entry.get("url"), url))
        entry["url"] = url
    if str(entry.get("trust") or "") != "untrusted":
        notes.append("trust: RE-ASSERTED untrusted (was %r) — this server exposes "
                     "write tools into your documents; untrusted is what makes them "
                     "raise an approval card" % entry.get("trust"))
        entry["trust"] = "untrusted"
    if "timeout" not in entry:
        entry["timeout"] = 120
    elif entry.get("timeout") != 120:
        notes.append("timeout: honoured your %s (not reset to 120)" % entry.get("timeout"))
if cur == entry:
    print("[harness] LOffice MCP server: already registered at " + url)
    raise SystemExit(0)
servers["loffice"] = entry
data["mcp_servers"] = servers
d = os.path.dirname(cfg) or "."
os.makedirs(d, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=d)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
os.replace(tmp, cfg)
print("[harness] LOffice MCP server registered at " + entry["url"]
      + " (trust: untrusted - write tools get an approval card)")
for _n in notes:
    print("[harness]   " + _n)
PYLOFFICE
    PORT=9119
    # `hermes dashboard` = same server as `hermes serve` PLUS Hermes's own web UI
    # (embedded chat, live tool feed, approvals, sessions). --no-open: we embed it in
    # the Harness tab, not a browser. --skip-build: serve the prebuilt web_dist from
    # install (no npm at start time). If web_dist is missing it degrades to headless
    # (API only), so a missing build never blocks startup.
    # ⛔ STOPPING THE PREVIOUS DASHBOARD — pidfile-scoped ONLY (U19, closed 2026-08-29).
    # What used to be here killed by NAME, twice over:
    #   · `hermes dashboard --stop` → hermes_cli/dashboard_procs.py::
    #     _kill_stale_dashboard_processes, which scans the WHOLE machine for any
    #     `hermes dashboard|serve` process and SIGTERM/SIGKILLs it;
    #   · `pkill -f "hermes (dashboard|serve)"` → the same blast radius, ours to own.
    # Debi runs a STANDALONE Hermes out of ~/.hermes/hermes-agent/venv. Both lines
    # would have closed it every time she pressed Start — the exact class that already
    # closed her standalone Unsloth (2026-08-28) and goose Desktop (2026-08-29).
    # Now: our own last dashboard, by the pid we wrote, identity re-verified; then the
    # port, which REFUSES the start (with the reason) if a stranger holds :9119 rather
    # than clearing it. A standalone Hermes on 9119 therefore survives — and says so.
    _reap_pidfile hermes force
    _clear_port "$PORT" hermes force
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
      echo "[harness] hermes dashboard up on http://127.0.0.1:${PORT} (UI + API; model=$MODEL [$MSRC] @ $BASE_URL)"
      # ── PROVIDER SELF-CHECK — the line that makes "no local model" decidable ────
      # Same discipline as the opencode lane's `/provider` check: ask the running
      # server for the payload its OWN picker renders (web/src/lib/api.ts:517-536 →
      # web_server.py:6369 → inventory.build_model_options_payload) and say in one
      # line whether our row reached it. A wrong answer here means the config we
      # wrote is not the config this server read — worth a loud line instead of a
      # picker the user finds empty later.
      # rm FIRST: a leftover from a previous Start must never be read as this one's.
      rm -f data/hermes-model-options.json
      curl -sf -m 40 -H "Authorization: Bearer $HTOKEN" \
        "http://127.0.0.1:${PORT}/api/model/options?include_unconfigured=1" \
        -o data/hermes-model-options.json 2>/dev/null || :
      HPROV="$HPROV" HCFG="$HCFG" python3 - data/hermes-model-options.json <<'PYHCHK' || true
import json, os, sys
slug = str(os.environ.get("HPROV") or "").strip().lower()
if not slug:
    print("[harness] hermes provider check: the seed wrote no verdict this Start (see "
          "the warning above) — the picker was NOT verified.")
    raise SystemExit(0)
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        rows = json.load(fh).get("providers") or []
except Exception as e:                                            # noqa: BLE001
    print("[harness] hermes provider check: could not read /api/model/options (%s)" % e)
    raise SystemExit(0)
mine = next((r for r in rows if str(r.get("slug", "")).lower() == slug), None)
if mine and (mine.get("models") or []):
    print('[harness] hermes provider check: "%s" IS in its own model picker — '
          "%d model(s)%s" % (mine.get("name"), len(mine.get("models") or []),
                             ", currently selected" if mine.get("is_current") else ""))
elif mine:
    # The row reached Hermes but carries nothing to pick — a picker the user would
    # find empty. Saying "it IS there" here would be true and useless.
    print('[harness] hermes provider check: "%s" is in the picker but lists NO models'
          " — check data/models.json (the registry the row is seeded from)."
          % mine.get("name"))
else:
    print("[harness] hermes provider check: %s NOT in the picker — its Models page will"
          " show the bare 'Custom endpoint' row instead." % slug)
    print("[harness]   config: %s" % os.environ.get("HCFG", "~/.hermes/config.yaml"))
    print("[harness]   rows it does list: %s"
          % (", ".join(str(r.get("slug")) for r in rows[:8]) or "(none)"))
PYHCHK
      rm -f data/hermes-model-options.json
      echo "[harness] tool-calling proof: run scripts/test_hermes.sh"
    else
      echo "ERROR: hermes dashboard did not open :${PORT} within 25s. Last log lines:"
      tail -15 data/logs/hermes.log
      exit 1
    fi
    ;;
  *) echo "usage: $0 runner|hermes|odysseus|searxng|voicestudio|voicebox|comfyui|unsloth"; exit 1 ;;
esac
