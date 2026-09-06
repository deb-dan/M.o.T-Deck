#!/usr/bin/env bash
# Start an installed component in the background (pid tracked in data/).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"
mkdir -p data/logs
ROOT_ABS="$(pwd)"

# Compatibility seam retained for old snapshots/tests. Production launch values now
# cross the typed PyYAML boundary below; text normalization cannot implement YAML.
_normalize_yaml_scalar() {   # <already-extracted scalar>
  local value="${1-}"
  if [[ "$value" =~ ^[[:space:]]*$ ]]; then
    printf ''
    return 0
  fi
  case "$value" in
    "~"|"''"|'""'|[Nn][Uu][Ll][Ll]) printf '' ;;
    *) printf '%s' "$value" ;;
  esac
}

# Return the first Python interpreter that can actually parse the YAML the following
# seeders write.  A path is always executed as one argv item, so bridge roots with
# spaces remain valid.  Optional arguments are a fixture-only seam; production callers
# use the fixed compatibility order below.
_yaml_python() {   # [candidate ...] -> interpreter path on stdout, 0; else 1
  local candidate
  if [[ $# -gt 0 ]]; then
    for candidate in "$@"; do
      [[ -n "$candidate" ]] || continue
      if "$candidate" -c 'import yaml' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  else
    for candidate in "${MOT_DECK_MANIFEST_PYTHON:-}" \
                     "$ROOT_ABS/data/bridge-venv/bin/python" \
                     "$HOME/Library/Application Support/MOT Deck/data/bridge-venv/bin/python" \
                     python3 python; do
      if "$candidate" -c 'import yaml' >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  fi
  return 1
}

# Fixture-only seams: run the real pure helpers without entering a component arm.
if [[ "$NAME" == "--normalize-yaml-scalar" ]]; then
  [[ $# -eq 2 ]] || { echo "usage: $0 --normalize-yaml-scalar <scalar>" >&2; exit 2; }
  _normalize_yaml_scalar "$2"
  exit 0
fi
if [[ "$NAME" == "--yaml-python" ]]; then
  shift
  if ! _yaml_python "$@"; then
    echo "ERROR: no Python interpreter able to import PyYAML" >&2
    exit 1
  fi
  exit 0
fi

MANIFEST_PY="$(_yaml_python)" || {
  echo "ERROR: no Python interpreter able to parse motdeck.yaml with PyYAML." >&2
  echo "       Bootstrap the bridge venv, then retry; no component was started." >&2
  exit 1
}
_manifest_value() { # <dotted.path> <str|int|bool>
  "$MANIFEST_PY" "$ROOT_ABS/scripts/read_manifest.py" "$ROOT_ABS" "$1" "$2"
}
_require_secret() { # <value> <dotted.path>
  [[ -n "${1:-}" ]] && return 0
  echo "ERROR: $2 is not provisioned; run scripts/local_secrets.py ensure '$ROOT_ABS'." >&2
  return 1
}

# ── PORT OWNERSHIP ────────────────────────────────────────────────────────────
# A LISTENER-scoped kill is still a kill of SOMEBODY ELSE'S process when the port
# collides: Debi's STANDALONE Unsloth app listens on :8888 and our own start was
# killing it every time. So establish ownership BEFORE killing.
# Owned iff this script recorded the exact child PID and its kernel start stamp and
# both still match. A pidfile, path, CWD, executable name, component name, or port by
# itself is never authority. NOT owned → refuse rather than kill a stranger.
# ⛔ THERE IS NO KILL BY NAME IN THIS FILE (CLAUDE.md PROCESS-KILL RULE; U19). Stopping
# a previous instance goes through _reap_pidfile (the pid WE wrote, identity re-verified
# before the signal); clearing a port goes through _clear_port (ownership-checked, and a
# port held by a stranger REFUSES the start instead of being cleared). `pkill`/`killall`
# and `hermes dashboard --stop` (which scans for every `hermes dashboard|serve` on the
# machine and kills them) are banned here and fenced by
# bridge/contract_tests/test_no_name_kills_contract.py.
_proc_cmd() { ps -o command= -p "$1" 2>/dev/null | tr '\n' ' '; }
_ownership_cli() {
  local py="$ROOT_ABS/data/bridge-venv/bin/python"
  [[ -x "$py" ]] || py="$(command -v python3 || true)"
  [[ -n "$py" && -f "$ROOT_ABS/bridge/core/ownership.py" ]] || {
    echo "ERROR: the shared launch-provenance helper is unavailable; refusing process ownership work." >&2
    return 2
  }
  "$py" "$ROOT_ABS/bridge/core/ownership.py" "$@"
}

# Corroborating path evidence, retained for diagnostics only. It never authorizes a
# signal. Exposed via --owner-check so the compatibility matrix stays observable.
_cmd_looks_like_ours() {   # <component> <command line>
  local comp="$1" cmd="$2"
  [[ -z "$cmd" ]] && return 1
  case "$cmd" in
    *"${ROOT_ABS}/data/"*|*"${ROOT_ABS}/vendor/"*) return 0 ;;
  esac
  case "$comp" in
    hermes)
      case "$cmd" in *"/data/hermes-venv/"*) return 0 ;; esac ;;
  esac
  return 1
}

_record_child() {   # <component> <pid> — call only with the `$!` just spawned here
  local comp="$1" pid="$2" detail
  if ! detail="$(_ownership_cli record "$ROOT_ABS" "$comp" "$pid" 2>&1)"; then
    kill -TERM "$pid" 2>/dev/null || true
    local attempt
    for attempt in {1..30}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
    wait "$pid" 2>/dev/null || true
    echo "ERROR: could not record spawned ${comp} pid ${pid}; stopped only that exact child." >&2
    [[ -n "$detail" ]] && echo "       ${detail}" >&2
    return 1
  fi
}

_ownership_matches() {   # <component> <pid>
  _ownership_cli matches "$ROOT_ABS" "$1" "$2" >/dev/null 2>&1
}

_record_runner_active() {   # <engine> <registry id> <wire id>
  local engine="$1" model="$2" wire="$3"
  ENGINE="$engine" MODEL="$model" WIRE="$wire" ROOT_ABS="$ROOT_ABS" python3 - <<'PYACTIVE'
import importlib.util, json, os, tempfile
root = os.environ["ROOT_ABS"]
helper = os.path.join(root, "bridge", "core", "ownership.py")
spec = importlib.util.spec_from_file_location("mot_ownership", helper)
ownership = importlib.util.module_from_spec(spec); spec.loader.exec_module(ownership)
claim = ownership.read_claim(root, "runner")
if not claim:
    raise SystemExit("runner ownership record is malformed")
raw_pid, birth = claim
record = {"v": 1, "pid": int(raw_pid), "birth": birth,
          "engine": os.environ["ENGINE"], "model": os.environ["MODEL"],
          "wire": os.environ["WIRE"]}
directory = os.path.join(root, "data")
fd, temporary = tempfile.mkstemp(prefix=".runner-active-", suffix=".tmp", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, os.path.join(directory, "runner.active.json"))
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PYACTIVE
}

_runner_active_model() {
  ROOT_ABS="$ROOT_ABS" python3 - <<'PYACTIVE'
import importlib.util, json, os, stat
root = os.environ["ROOT_ABS"]
try:
    active_path = os.path.join(root, "data", "runner.active.json")
    fd = os.open(active_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ValueError("active marker is not regular")
        with os.fdopen(fd, encoding="utf-8") as handle:
            fd = -1; rec = json.load(handle)
    finally:
        if fd >= 0: os.close(fd)
    pid_path = os.path.join(root, "data", "runner.pid")
    pfd = os.open(pid_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(pfd).st_mode): raise ValueError("runner pid report is not regular")
        with os.fdopen(pfd, encoding="ascii") as handle:
            pfd = -1; pidfile = int(handle.read().strip())
    finally:
        if pfd >= 0: os.close(pfd)
    helper = os.path.join(root, "bridge", "core", "ownership.py")
    spec = importlib.util.spec_from_file_location("mot_ownership", helper)
    ownership = importlib.util.module_from_spec(spec); spec.loader.exec_module(ownership)
    claim = ownership.read_claim(root, "runner")
    if not claim: raise ValueError("launch claim is absent")
    pid, birth = claim
    live_birth = ownership.process_birth(pid)
    if (pid != pidfile or rec.get("v") != 1
            or rec.get("pid") != pid or rec.get("birth") != birth
            or birth != live_birth or not isinstance(rec.get("model"), str)):
        raise ValueError("launch provenance does not match the live process")
    print(rec["model"])
except Exception:
    raise SystemExit(1)
PYACTIVE
}

if [[ "$NAME" == "--owner-check" ]]; then
  shift
  _cmd_looks_like_ours "${1:-}" "${2:-}"; exit $?
fi
if [[ "$NAME" == "--ownership-record-check" ]]; then
  shift
  _ownership_matches "${1:-}" "${2:-0}"; exit $?
fi
if [[ "$NAME" == "--record-child" ]]; then
  shift
  [[ $# -eq 2 && "$2" =~ ^[0-9]+$ ]] || {
    echo "usage: $0 --record-child <component> <pid>" >&2; exit 2; }
  _record_child "$1" "$2"
  exit $?
fi

# ── FULL DETACHMENT AT SPAWN (THE 2026-08-30 SILENT-DEATH INCIDENT) ───────────
# Runner + Hermes + Odysseus died together, repeatedly, on an idle machine, while
# Searxng/Voicestudio/Voicebox/ComfyUI/Unsloth/OpenCode survived. Root cause, proven
# on the live process table and then reproduced from scratch:
#
#   `nohup CMD &` BLOCKS SIGHUP AND NOTHING ELSE. It does not change the process
#   group. A component launched through a BRIDGE ROUTE (Restart button, model switch,
#   rebind) therefore runs this script as a child of the bridge and inherits the
#   BRIDGE's process group id. Measured before the fix: llama-server 35558, hermes
#   35657, odysseus 35673 all carried pgid 25183 — which is the bridge's own pid.
#
#   macOS Foundation's `Process.terminate()` — what app/main.swift calls in
#   applicationWillTerminate — does NOT signal only the child. Foundation launches
#   the child as a process-group LEADER and terminate() signals THE GROUP. Verified
#   with a purpose-built Swift test fixture, both directions:
#     · child bash + `nohup sleep 600 &`         → terminate() → the sleep DIED.
#     · child bash + setsid'd `sleep 600`        → terminate() → the sleep SURVIVED.
#   So every quit of MOT Deck was a group kill that reached straight through the
#   bridge into whatever this script had most recently spawned. The long-lived
#   survivors were simply started from shells whose groups were already dead.
#
# THE FIX: give every component its OWN SESSION (setsid), which implies its own
# process group and no controlling terminal. Nothing upstream — an app quit, a bridge
# death, a ship, an agent process-tree reaping — can then address it by group.
#
# macOS ships no /usr/bin/setsid, so the native detour is perl (always present):
# it calls POSIX::setsid() and then EXECs the real command, so the pid that `$!`
# records IS the component. argv is passed through untouched — spaces, arrays and
# `env VAR=val` prefixes all survive, because nothing is ever re-parsed by a shell
# (`exec { $ARGV[0] } @ARGV` is the block form, which never falls back to /bin/sh
# even when the list has a single element).
#
# `exec` inside the function is LOAD-BEARING, not tidiness: every call site is
# `_detached … >>log 2>&1 &` and then `echo $! > data/<comp>.pid`. Without exec,
# bash's background subshell would linger as an extra frame and `$!` could name the
# WRAPPER instead of the component, quietly breaking every pidfile in this file.
# It also means _detached must ONLY ever be called backgrounded — calling it in the
# foreground would replace this script. test_detached_spawn_contract.py fences both.
#
# nohup is kept inside the wrapper: a setsid'd process has no controlling terminal
# and cannot receive a terminal SIGHUP anyway, but the ignore-disposition survives
# exec for free and the redirection semantics at the call sites are unchanged.
#
# Detachment is a safety postcondition, not an optional optimization. Starting in the
# bridge/app process group knowingly recreates the incident this helper exists to
# prevent, so missing Perl or a failed setsid is a loud refusal. The component remains
# stopped and the caller reports the dependency failure; it is never launched in a
# process group an unrelated app quit can address.
_detached() {   # <cmd> [args…]   — ALWAYS call as: _detached … >>log 2>&1 &
  if ! command -v perl >/dev/null 2>&1; then
    echo "ERROR: perl is not on PATH; refusing to launch ${NAME:-component} without its own session." >&2
    return 127
  fi
  exec nohup perl -MPOSIX -e '
    my $s = POSIX::setsid();
    if (!defined($s) || $s < 0) {
      die "[motdeck] detach: setsid failed ($!) - refusing unsafe launch\n";
    }
    exec { $ARGV[0] } @ARGV or die "[motdeck] detach: cannot exec $ARGV[0]: $!\n";
  ' -- "$@"
}

# Self-test hook for the contract suite: spawn a scratch process through the real
# helper and report its pid, so the LIVE test can prove the session/group split and
# then reap ONLY that pid (which it wrote itself). Never used by MOT Deck.
if [[ "$NAME" == "--detach-selftest" ]]; then
  shift
  # stderr is deliberately NOT swallowed: the helper's "setsid failed" sentence is
  # the one thing a failing self-test needs to show, and hiding it once already
  # turned a two-line diagnosis into an hour of guessing.
  _detached "$@" >/dev/null &
  echo "$!"
  exit 0
fi
if [[ "$NAME" == "--ownership-selftest" ]]; then
  shift
  probe_comp="${1:-}"
  shift || true
  [[ -n "$probe_comp" && $# -gt 0 ]] || {
    echo "usage: $0 --ownership-selftest <component> <command> [args...]" >&2; exit 2; }
  _detached "$@" >/dev/null 2>&1 &
  probe_pid="$!"
  _record_child "$probe_comp" "$probe_pid"
  echo "$probe_pid"
  exit 0
fi

# The ONLY sanctioned way to stop a PREVIOUS instance of one of our components: the
# pid WE recorded, whose identity is re-verified before any signal. Pids are recycled,
# so a stale pidfile must never become a stranger's death warrant — a pid that is not
# provably ours gets NO signal. Its unverifiable evidence is retained for the explicit
# migration command; deleting it would make safe recovery harder. This is
# what replaced the `pkill -f "<product name>"` lines (U19): a name match is not
# identity, and Debi runs standalone copies of the very apps we embed.
_reap_pidfile() {   # <component> [force]
  # ⚠️ pf is assigned on its OWN line: bash's `local` declares every name in the
  # statement BEFORE assigning, so `local comp="$1" pf="…${comp}…"` reads comp while it
  # is still unset and dies under `set -u` ("comp: unbound variable"). Found by walking
  # the restart, not by reading — it aborted the whole hermes arm. _clear_port below
  # already had it right; this is the same shape, kept the same way.
  local comp="$1" force="${2:-}" pid birth cmd pf owner detail claim args=()
  pf="data/${comp}.pid"
  owner="data/${comp}.owner"
  [[ "$force" == "force" ]] && args+=(--force)
  claim="$(_ownership_cli claim "$ROOT_ABS" "$comp" 2>/dev/null || true)"
  pid="${claim%%$'\t'*}"
  birth="${claim#*$'\t'}"
  [[ "$claim" == *$'\t'* ]] || { pid=""; birth=""; }
  if [[ -z "$pid" ]]; then
    detail="$(_ownership_cli signal "$ROOT_ABS" "$comp" 0 --birth "" ${args[@]+"${args[@]}"} 2>&1 || true)"
    if [[ -e "$pf" || -L "$pf" || -e "$owner" || -L "$owner" ]]; then
      echo "[motdeck] ${detail:-no complete M.O.T launch record; signalled nothing}"
    fi
    return 0
  fi
  cmd="$(_proc_cmd "$pid")"
  if ! detail="$(_ownership_cli signal "$ROOT_ABS" "$comp" "$pid" --birth "$birth" --keep-claim ${args[@]+"${args[@]}"} 2>&1)"; then
    echo "[motdeck] ${pf} names pid ${pid} (${cmd}) but has no matching M.O.T launch record;"
    echo "[motdeck]   leaving it alone. ${detail}"
    return 1
  fi
  local attempt
  for attempt in {1..40}; do
    _ownership_matches "$comp" "$pid" || break
    sleep 0.1
  done
  if _ownership_matches "$comp" "$pid"; then
    echo "ERROR: recorded ${comp} pid ${pid} is still alive after its stop signal; refusing a replacement." >&2
    return 1
  fi
  _ownership_cli retire "$ROOT_ABS" "$comp" "$pid" --birth "$birth" >/dev/null 2>&1 || true
}

_clear_port() {   # <port> <component> [force]
  local port="$1" comp="$2" force="${3:-}" pid birth cmd detail attempt listeners owner args=()
  owner="data/${comp}.owner"
  [[ "$force" == "force" ]] && args+=(--force)
  for pid in $(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null); do
    birth="$(awk -F '\t' -v p="$pid" '$1 == "v1" && $2 == p {print $3; exit}' "$owner" 2>/dev/null || true)"
    if ! detail="$(_ownership_cli signal "$ROOT_ABS" "$comp" "$pid" --birth "$birth" --keep-claim ${args[@]+"${args[@]}"} 2>&1)"; then
      cmd="$(_proc_cmd "$pid")"
      echo "ERROR: port ${port} is held by pid ${pid} (${cmd}) without a matching M.O.T launch record."
      echo "       Refusing to kill it; stop that application explicitly, then retry. ${detail}"
      exit 1
    fi
    for attempt in {1..40}; do
      listeners="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
      if [[ -z "$listeners" ]] && ! _ownership_matches "$comp" "$pid"; then break; fi
      sleep 0.1
    done
    listeners="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$listeners" ]] || _ownership_matches "$comp" "$pid"; then
      echo "ERROR: recorded ${comp} pid ${pid} or its listener on :${port} survived the stop signal;" >&2
      echo "       retaining its ownership claim and refusing to start a replacement." >&2
      exit 1
    fi
    _ownership_cli retire "$ROOT_ABS" "$comp" "$pid" --birth "$birth" >/dev/null 2>&1 || true
  done
}

# ── U54/U25: THE LISTENER MUST BE THE EXACT CHILD WE RECORDED ────────────────
#
# `echo $! > data/<comp>.pid` records a REPORT: "the pid I just backgrounded". After a
# single launch that report is also the fact (see _detached — the exec chain keeps the
# pid), but the runner arm below is allowed to launch TWICE: a speculative-decoding
# guess that a model cannot honour makes the first llama-server die, and the retry arm
# relaunches. Measured on the live stack twice (2026-08-30): data/runner.pid said 35568
# while llama-server was 35558, and after the detachment fix 44288 while :6767 was held
# by 44276. So the file named a dead pid on every observed restart of that shape.
#
# CONSEQUENCES, all of them quiet: _reap_pidfile could not stop the real runner (it
# fell through to _clear_port, which is why nobody noticed); the "[motdeck] runner … up
# … pid=$(cat data/runner.pid)" line the panel shows was false; and health never
# noticed because health is probe-based.
#
# The old implementation asked the port who held it and then adopted a listener based
# on its path/name. That can turn a manually-started process into ours. The corrected
# rule is opposite: the launch record comes only from `$!`; readiness then proves the
# one listener is that exact recorded child. A mismatch fails and the recorded child is
# the only process this script may clean up.
_stamp_pidfile_from_port() {   # <component> <port>
  local comp="$1" port="$2" recorded listeners pid
  recorded="$(tr -cd '0-9' < "data/${comp}.pid" 2>/dev/null || true)"
  listeners="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  set -- $listeners
  if [[ $# -eq 1 ]] && [[ "$1" == "$recorded" ]] && _ownership_matches "$comp" "$1"; then
    return 0
  fi
  echo "ERROR: :${port} is not held by the exact recorded ${comp} child " \
       "(${recorded:-none}); observed: ${listeners:-none}." >&2
  _reap_pidfile "$comp" force
  return 1
}

# Self-test hook for the contract suite (same shape as --detach-selftest above): run the
# REAL helper against a component name + port and report what it decided, so a live test
# can spawn its OWN listener, prove both the stamp and the stranger-refusal, and reap
# only the pid it wrote itself. Never used by MOT Deck.
#   start_component.sh --pidfile-from-port <component> <port>
if [[ "$NAME" == "--pidfile-from-port" ]]; then
  if _stamp_pidfile_from_port "${2:-}" "${3:-0}"; then echo "STAMPED $(cat "data/${2:-}.pid" 2>/dev/null)"
  else echo "UNCHANGED $(cat "data/${2:-}.pid" 2>/dev/null)"; fi
  exit 0
fi

case "$NAME" in
  runner)
    R_ADAPTER=$(_manifest_value runner.adapter str)
    [[ -n "$R_ADAPTER" ]] || R_ADAPTER=auto
    # jan retired 2026-07-23 (cleanup 3.1d) — MOT Deck owns its own llama-server
    # binary + model files now. Only llamacpp | mlx | auto are valid; anything else
    # errors loudly rather than silently falling through.
    case "$R_ADAPTER" in
      llamacpp|mlx|auto) ;;
      *) echo "ERROR: unknown adapter '$R_ADAPTER' — llamacpp|mlx|auto"; exit 1 ;;
    esac
    # adapter is llamacpp | mlx | auto — all consult OUR registry. Resolve the active
    # model's path / mmproj / ctx / format / vision FIRST, then pick the engine.
    R_PORT=$(_manifest_value runner.port int)
    R_KEY=$(_manifest_value runner.api_key str)
    R_CTX=$(_manifest_value runner.ctx_size int)
    R_MODEL=$(_manifest_value runner.model str)
    R_BIN=$(_manifest_value runner.binary str)
    _require_secret "$R_KEY" runner.api_key || exit 1
    [[ "$R_CTX" =~ ^[0-9]+$ ]] || R_CTX=65536
    [[ -n "$R_MODEL" ]] || { echo "ERROR: runner.model not set in motdeck.yaml"; exit 1; }
    # Ensure the registry exists.
    [[ -f data/models.json ]] || python3 scripts/seed_registry.py
    # Resolve the model from the registry (path / mmproj / ctx / format / vision).
    # MLX models are DIRECTORIES (safetensors); GGUF models are files — validate
    # accordingly so the auto/mlx path resolves an mlx model dir.
    RESOLVED=$(R_MODEL="$R_MODEL" python3 - <<'PYRESOLVE'
import importlib.util, os, json, sys
mid = os.environ["R_MODEL"]
try:
    models = json.load(open("data/models.json")).get("models", [])
except Exception:
    models = []
m = next((x for x in models if x.get("id") == mid), None)
helper = os.path.join(os.getcwd(), "bridge", "core", "modelreg.py")
spec = importlib.util.spec_from_file_location("motdeck_modelreg", helper)
if spec is None or spec.loader is None:
    sys.stderr.write("model integrity helper unavailable (packaging error)\n")
    sys.exit(1)
modelreg = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(modelreg)
except Exception as exc:
    sys.stderr.write(f"model integrity helper unavailable (packaging error): {exc}\n")
    sys.exit(1)
if not m:
    sys.stderr.write(f"model '{mid}' not in registry — Rescan or pick another model\n")
    sys.exit(1)
probe = modelreg.artifact_probe(m)
if probe.get("state") != "ready":
    sys.stderr.write(f"model '{mid}' is {probe.get('state')}: {probe.get('detail')}. Rescan or pick another model\n")
    sys.exit(1)
fmt = m.get("format", "gguf")
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
) || { echo "ERROR: runner model resolution failed — see the diagnostic above."; exit 1; }
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
      [[ -n "$BIN" ]] || { echo "ERROR: no llama-server binary found — run scripts/install_llamacpp.sh or set runner.binary in motdeck.yaml"; exit 1; }
    else
      BIN="$R_BIN"; BIN_OWNER=""
      [[ -x "$BIN" ]] || { echo "ERROR: runner.binary is not executable: $BIN"; exit 1; }
    fi
    # ⚠️ A FOREIGN APP'S llama-server IS NOT OUR PINNED CONTRACT (bug-echo W-04, the
    # Unsloth class crossed with the wrong-oracle class). The two fallbacks above run a
    # binary that belongs to Jan or LM Studio: a different app upgrades it whenever it
    # likes, and this MOT Deck's probe/auth expectations are pinned against ONE build.
    # That is not hypothetical — llama.cpp b10662's /v1/models started REQUIRING auth
    # where the previous build did not, and the 401 regression that caused took a session
    # to find. Silently starting a stranger's binary of unknown vintage re-opens it.
    # An EXPLICIT runner.binary is exempt: that is a person naming a binary on purpose.
    if [[ -n "${BIN_OWNER:-}" ]]; then
      L_PIN=$(_manifest_value runner.llamacpp_pin str)
      L_BUILD=$("$BIN" --version 2>&1 | sed -n 's/.*build \([0-9][0-9]*\).*/\1/p' | head -1)
      echo "[motdeck] ⚠️  THE RUNNER BINARY IS NOT OURS. It belongs to ${BIN_OWNER}:"
      echo "[motdeck]      $BIN"
      echo "[motdeck]      build ${L_BUILD:-unreadable} · MOT Deck is pinned to ${L_PIN:-(no pin set)}"
      if [[ -n "$L_PIN" && "$L_BUILD" == "${L_PIN#b}" ]]; then
        echo "[motdeck]      the build MATCHES the pin, so the pinned contracts hold. Using it."
      elif [[ "${MOT_DECK_ALLOW_FOREIGN_RUNNER:-0}" == "1" ]]; then
        echo "[motdeck]      MOT_DECK_ALLOW_FOREIGN_RUNNER=1 — starting it anyway, deliberately."
        echo "[motdeck]      If the model answers but the panel says the runner is down, or"
        echo "[motdeck]      /v1/models 401s, THIS is the first thing to suspect."
      else
        echo "ERROR: refusing to start the runner on ${BIN_OWNER}'s llama-server."
        echo "  Its build (${L_BUILD:-unreadable}) is not the one MOT Deck is pinned"
        echo "  against (${L_PIN:-(none)}), and ${BIN_OWNER} can change it at any time"
        echo "  without telling us. Our /v1/models auth probe is pinned per build: b10662"
        echo "  made that endpoint require a key where the build before it did not (a 401"
        echo "  regression that cost a whole session to find), and the same drift in the"
        echo "  other direction reads to the panel as 'the runner is down'."
        echo "  Fix it properly:   ./scripts/install_llamacpp.sh"
        echo "  Name it on purpose: set runner.binary in motdeck.yaml"
        echo "  Or override, knowing the above: MOT_DECK_ALLOW_FOREIGN_RUNNER=1 <this command>"
        exit 1
      fi
    fi
    # CTX preference: the model's SAVED load.ctx (Models → Load, v2) wins, then the
    # registry ctx, then motdeck.yaml ctx_size, then 65536.
    L_CTX=$(_lv ctx)
    if [[ "$L_CTX" =~ ^[0-9]+$ ]]; then CTX="$L_CTX"
    elif [[ "$REG_CTX" =~ ^[0-9]+$ ]]; then CTX="$REG_CTX"
    else CTX="$R_CTX"; fi
    [[ "$CTX" =~ ^[0-9]+$ ]] || CTX=65536
    # Capture the binary's flags to decide whether its secret-file interface is
    # supported (cheap; every start ok). The key must never appear in process argv.
    "$BIN" --help > data/llama-server.help.txt 2>&1 || true
    # Build argv as an ARRAY — paths contain spaces ("Application Support"); unquoted
    # expansion would split them. (Fable QA fix on the builder's draft.)
    ARGS=(--no-context-shift --host 127.0.0.1 --port "$R_PORT" --alias "$R_MODEL"
          --ctx-size "$CTX" --no-cont-batching --cache-ram -1 --fit off
          --model "$MODEL_PATH" --parallel 1)
    if [[ -n "$MMPROJ_PATH" ]]; then ARGS+=(--mmproj "$MMPROJ_PATH"); fi
    # ── NAMED API KEYS (ledger S32) ────────────────────────────────────────────
    # The generated built-in key above stays the internal key: it is what the
    # readiness poll below sends and what every internal caller uses. It joins the
    # SECOND source — keys Debi mints in MOT Deck → API — in one ephemeral 0600 launch
    # file. Passing the built-in via --api-key would expose it to every local `ps`.
    #
    # MEASURED AT OUR PIN, not assumed (b10662, 2026-08-29, scratch server on :6799):
    # `--api-key-file` takes one key per line and `#` lines are comments. The file is
    # read ONCE at launch, so it is deleted after readiness; the server retains the
    # accepted set in memory. bridge/routers/apikeys.py carries the full measurement.
    #
    # data/api_keys.keys remains the bridge-generated NAMED-key input and digest source.
    # The launch-only file below prepends the protected built-in key without changing
    # the named-key store or its applied digest semantics.
    # ⚠️ $ROOT_ABS, NOT $ROOT (live finding L2). `ROOT` is set PER-ARM in this script
    # (:579, :606, :630, :734 …) and the runner arm never sets it, so `$ROOT` under
    # `set -u` (:3) aborted the launch with "ROOT: unbound variable" before the model
    # was ever touched — the whole model lane down, reported to the panel as a failed
    # start. `ROOT_ABS` is the file-scope absolute root, set at :7.
    KEYFILE="$ROOT_ABS/data/api_keys.keys"
    LAUNCH_KEYFILE="$ROOT_ABS/data/.runner-api.keys"
    _cleanup_runner_launch_key() {
      [[ -n "${LAUNCH_KEYFILE:-}" ]] && rm -f "$LAUNCH_KEYFILE"
    }
    trap _cleanup_runner_launch_key EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM
    KEYFILE_ARMED=0
    if ! grep -q -- "--api-key-file" data/llama-server.help.txt; then
      echo "ERROR: this llama-server lacks --api-key-file; refusing to expose runner.api_key in process argv."
      echo "  Install the pinned backend: ./scripts/install_llamacpp.sh"
      exit 1
    fi
    KEYFILE_ARMED=1
    if [[ -e "$KEYFILE" || -L "$KEYFILE" ]]; then
      if [[ ! -f "$KEYFILE" || -L "$KEYFILE" ]]; then
        echo "ERROR: data/api_keys.keys is not a regular non-symlink file; refusing the runner launch."
        exit 1
      fi
    fi
    _launch_keys_tmp=$(mktemp "$ROOT_ABS/data/.runner-api.keys.tmp.XXXXXX") || exit 1
    chmod 600 "$_launch_keys_tmp"
    {
      printf '%s\n' "$R_KEY"
      if [[ -s "$KEYFILE" ]]; then
        grep -v '^[[:space:]]*\(#\|$\)' "$KEYFILE" || true
      fi
    } > "$_launch_keys_tmp"
    mv -f "$_launch_keys_tmp" "$LAUNCH_KEYFILE"
    chmod 600 "$LAUNCH_KEYFILE"
    ARGS+=(--api-key-file "$LAUNCH_KEYFILE")
    # …and the PROMETHEUS COUNTERS the API page's totals come from. Disabled by default
    # (GET /metrics returns 501 without it — measured), loopback-only like the rest of
    # this server, and behind the same api-key as every other endpoint on it. Without
    # this flag the API page can show per-request rows for OUR lanes but nothing at all
    # for apps calling :6767 directly, which is the half of the traffic S32 is about.
    if grep -q -- "--metrics" data/llama-server.help.txt; then ARGS+=(--metrics); fi
    # Repetition guard (Fable, 2026-08-06): heavily-quantized local models (gemma-31B
    # IQ4/Q4) degenerate into token loops ("C-C-C-…"). A mild repeat penalty is the
    # standard mitigation; gated on binary support like the auth-file flag above.
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
    # against this binary's own --help, exactly like the auth-file flag above.
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
    R_SPEC=$(_manifest_value runner.spec_mtp str)
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
        echo "[motdeck] MTP detected ($MTP_WHY) — speculative decoding enabled (--spec-type draft-mtp)"
      else
        echo "[motdeck] WARN: MTP model but this llama-server lacks --spec-type — running WITHOUT acceleration."
        echo "[motdeck]   Fix: set runner.binary to a newer backend, e.g.:"
        ls -t "$HOME/.lmstudio/extensions/backends/"*/llama-server 2>/dev/null | head -1 | sed 's/^/[motdeck]   /'
      fi
    fi
    # Cleanup any stale server on the port — including MLX servers (format switch).
    # Two steps, both identity-bound: OUR last runner by its pidfile (catches one that
    # is hung mid-load and therefore not listening yet), then the port itself, which
    # refuses rather than kills when a stranger holds it. (Was three `pkill -f
    # "<engine>.*--port"` lines: a pattern match, not identity — U19.)
    _reap_pidfile runner force
    _clear_port "$R_PORT" runner force
    rm -f data/runner.active.json
    sleep 1
    # Launch + wait for readiness. Factored so a bad speculative-decoding guess can
    # be retried WITHOUT those flags instead of leaving the runner dead (spec flags
    # on a model that has no MTP heads fail the load — self-healing beats a hard stop).
    _launch_llama() {   # args: the full argv after $BIN
      _detached "$BIN" "$@" >> data/logs/runner.log 2>&1 &
      _record_child runner "$!"
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
        # the launch auth file and llama.cpp b10662 made /v1/models REQUIRE a key —
        # the same regression this file already documents at :247/:267. Polling without
        # it 401s forever: a runner that was serving in ~1.3s still burned the whole
        # 90×2s budget and then EXITED NON-ZERO, i.e. "the runner did not come up" about
        # a runner that was up. -f treats 401 as failure, which is what hid it.
        if curl -sf -m 2 -H "Authorization: Bearer ${R_KEY}" \
             "http://127.0.0.1:${R_PORT}/v1/models" >/dev/null 2>&1; then
          # b10662 has already parsed the file; unlink the derived plaintext copy so
          # the protected store is the only persistent home of the built-in key.
          rm -f "$LAUNCH_KEYFILE"
          # U54 — the server is answering, so :$R_PORT can now be ASKED who holds it.
          # This is the one instant where the answer is unambiguous, and it is why the
          # stamp lives inside _launch_llama rather than after the retry ladder: each
          # attempt that reaches readiness corrects the pidfile for itself, so the
          # retry arm below cannot leave a losing $! behind. Never fatal — a failure
          # here only means the pidfile keeps the value it already had.
          _stamp_pidfile_from_port runner "$R_PORT"
          return 0
        fi
        sleep 2
      done
      return 1
    }
    up=0
    if _launch_llama "${ARGS[@]}" ${SPEC_ARGS[@]+"${SPEC_ARGS[@]}"}; then
      up=1
    elif [[ ${#SPEC_ARGS[@]} -gt 0 ]]; then
      echo "[motdeck] WARN: runner did not start WITH speculative-decoding flags —"
      echo "[motdeck]   this model likely has no usable MTP heads. Retrying without them."
      echo "--- runner.log tail (failed spec attempt) ---"; tail -12 data/logs/runner.log 2>/dev/null
      _reap_pidfile runner force
      _clear_port "$R_PORT" runner force
      sleep 1
      SPEC_ARGS=()
      if _launch_llama "${ARGS[@]}"; then up=1; fi
    fi
    if [[ "$up" == "1" ]]; then
      _record_runner_active llamacpp "$R_MODEL" "$R_MODEL" || \
        echo "[motdeck] WARN: runner is live but its launch-provenance marker could not be written"
      SPEC_NOTE=""; [[ ${#SPEC_ARGS[@]} -gt 0 ]] && SPEC_NOTE=" spec=draft-mtp"
      echo "[motdeck] runner (llama-server) up on :$R_PORT — model=$R_MODEL ctx=$CTX${SPEC_NOTE} pid=$(cat data/runner.pid)"
    else
      rm -f "$LAUNCH_KEYFILE"
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
    rm -f data/runner.active.json
    sleep 1
    _detached "${CMD[@]}" --model "$MODEL_PATH" --host 127.0.0.1 --port "$R_PORT" \
      ${MLX_FLOOR[@]+"${MLX_FLOOR[@]}"} >> data/logs/runner.log 2>&1 &
    _record_child runner "$!"
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
      # U54 — same rule for the MLX engines. They launch once, so `$!` is normally
      # already right; the stamp is here so the RULE, not the arm, is what makes the
      # pidfile true, and so a future retry ladder on this arm inherits the fix.
      _stamp_pidfile_from_port runner "$R_PORT"
      _record_runner_active "$ENGINE" "$R_MODEL" "$MODEL_PATH" || \
        echo "[motdeck] WARN: runner is live but its launch-provenance marker could not be written"
      echo "[motdeck] runner ($ENGINE) up on :$R_PORT — model=$R_MODEL pid=$(cat data/runner.pid) (loopback only, no auth)"
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
    # Connect (idempotent): (re)wire Odysseus to MOT Deck RUNNER endpoint (:6767 + key)
    # as default model. Runs before the server boots.
    R_ENDPOINT=$(_manifest_value runner.endpoint str)
    R_KEY=$(_manifest_value runner.api_key str)
    _require_secret "$R_KEY" runner.api_key || exit 1
    [[ -n "$R_ENDPOINT" ]] || R_ENDPOINT="http://127.0.0.1:6767/v1"
    ( cd vendor/odysseus && JAN_BASE_URL="$R_ENDPOINT" JAN_API_KEY="$R_KEY" python "$ROOT/scripts/seed_odysseus_jan.py" ) || true
    # Start server. cd applies to the whole subshell (Odysseus expects cwd=vendor/odysseus);
    # pid + log use ABSOLUTE paths so the earlier '../../ from wrong cwd' bug can't recur.
    (
      cd vendor/odysseus
      _detached python -m uvicorn app:app --host 127.0.0.1 --port 7860 >>"$ROOT/data/logs/odysseus.log" 2>&1 &
      _record_child odysseus "$!"
    )
    sleep 2
    if kill -0 "$(cat data/odysseus.pid)" 2>/dev/null; then
      echo "[motdeck] odysseus starting → http://127.0.0.1:7860 (M.O.T uses the generated local login; values are never logged)"
    else
      echo "ERROR: odysseus exited immediately. Last log lines:"; tail -15 data/logs/odysseus.log; exit 1
    fi
    ;;
  searxng)
    [[ -d data/searxng-venv ]] || { echo "ERROR: searxng venv missing — run scripts/install_searxng.sh"; exit 1; }
    ROOT="$(pwd)"
    _clear_port 8080 searxng
    sleep 1
    _detached env SEARXNG_SETTINGS_PATH="$ROOT/data/searxng/settings.yml" \
      "$ROOT/data/searxng-venv/bin/python" -m searx.webapp \
      >>"$ROOT/data/logs/searxng.log" 2>&1 &
    _record_child searxng "$!"
    up=0
    for _ in $(seq 1 15); do
      if curl -sf -m 2 "http://127.0.0.1:8080/" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/searxng.pid")" 2>/dev/null || { echo "ERROR: searxng exited on launch:"; tail -10 "$ROOT/data/logs/searxng.log"; exit 1; }
      sleep 1
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] searxng up on :8080 (private search; Odysseus uses it automatically)"
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
    VS_PORT=$(_manifest_value components.voicestudio.port int)
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
      echo "[motdeck] voicestudio ffmpeg → $ROOT/data/ffmpeg/bin/ffmpeg (motdeck-provisioned)"
    fi
    # Optional LLM (Cinematic translate / glossary extraction / dictation refinement)
    # is OpenAI-compatible. Point it at OUR runner, the same way seed_odysseus_jan.py
    # seeds Odysseus. VoiceStudio's provider registry resolves env FIRST, and the
    # TRANSLATE_* trio is the "custom (OpenAI-compatible)" provider's env triplet
    # (services/llm_providers.py @v0.4.2). We deliberately do NOT set
    # LLM_DEFAULT_PROVIDER: a lone TRANSLATE_BASE_URL only makes our runner the
    # DEFAULT, while an explicit provider chosen in VoiceStudio's own Settings still
    # wins.  ⚠️ PENDING FABLE QA.
    VS_BASE_URL=$(_manifest_value runner.endpoint str)
    VS_KEY=$(_manifest_value runner.api_key str)
    VS_MODEL=$(_runner_active_model 2>/dev/null || true)
    VS_MODEL_SOURCE="live runner launch provenance"
    if [[ -z "$VS_MODEL" ]]; then
      VS_MODEL=$(_manifest_value runner.model str)
      VS_MODEL_SOURCE="saved runner pin (no live launch provenance)"
    fi
    _require_secret "$VS_KEY" runner.api_key || exit 1
    [[ -n "$VS_BASE_URL" ]] || VS_BASE_URL="http://127.0.0.1:6767/v1"
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
      echo "[motdeck] voicestudio LLM → ${VS_BASE_URL} (${VS_MODEL}; ${VS_MODEL_SOURCE})"
    else
      echo "[motdeck] voicestudio: no runner model in motdeck.yaml — leaving its LLM"
      echo "[motdeck]  unset (TTS/ASR are unaffected; set a provider in its Settings"
      echo "[motdeck]  or start the Runner and restart voicestudio)"
    fi
    # cd applies to the whole subshell (backend.main:app resolves from the repo root);
    # pid + log use ABSOLUTE paths so they can never land outside the project.
    (
      cd vendor/voicestudio
      _detached env "${VS_ENV[@]}" \
        "$VSPY" "${VS_CMD[@]}" >>"$ROOT/data/logs/voicestudio.log" 2>&1 &
      _record_child voicestudio "$!"
    )
    up=0
    # GENEROUS wait: the first boot can pull/load speech models before /health answers.
    TRIES=150
    for i in $(seq 1 "$TRIES"); do
      if curl -sf -m 2 "http://127.0.0.1:${VS_PORT}/health" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/voicestudio.pid")" 2>/dev/null || {
        echo "ERROR: voicestudio exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/voicestudio.log"
        echo "[motdeck] (this backend exits with code 78 when :$VS_PORT is already in use)"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[motdeck] voicestudio still starting… (~$((i * 2))s; first boot loads models)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] voicestudio up on http://127.0.0.1:${VS_PORT} (API + UI, loopback only, NO auth)"
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
    VB_PORT=$(_manifest_value components.voicebox.port int)
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
      echo "[motdeck] voicebox ffmpeg → $ROOT/data/ffmpeg/bin/ffmpeg (motdeck-provisioned)"
    fi
    VB_CMD=(-m backend.main --host 127.0.0.1 --port "$VB_PORT" --data-dir "$ROOT/data/voicebox")
    # cd applies to the whole subshell (the backend package resolves from the repo
    # root); pid + log use ABSOLUTE paths so they can never land outside the project.
    (
      cd vendor/voicebox
      _detached "$VBPY" "${VB_CMD[@]}" >>"$ROOT/data/logs/voicebox.log" 2>&1 &
      _record_child voicebox "$!"
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
        echo "[motdeck] (a missing/broken ML dependency shows up here — voicebox's"
        echo "[motdeck]  dependency graph is known-fragile; reinstall is online-only)"
        exit 1; }
      if (( i % 15 == 0 )); then echo "[motdeck] voicebox still starting… (~$((i * 2))s; first boot loads models)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] voicebox up on http://127.0.0.1:${VB_PORT} (API + /mcp, loopback only, NO auth)"
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
    CU_PORT=$(_manifest_value components.comfyui.port int)
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
      _detached "$CUPY" "${CU_CMD[@]}" >>"$ROOT/data/logs/comfyui.log" 2>&1 &
      _record_child comfyui "$!"
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
      if (( i % 15 == 0 )); then echo "[motdeck] comfyui still starting… (~$((i * 2))s; torch import is slow)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] comfyui up on http://127.0.0.1:${CU_PORT} (UI + API, loopback only, NO auth)"
      echo "[motdeck] base dir: $ROOT/data/comfyui — put checkpoints in models/checkpoints/"
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
    US_PORT=$(_manifest_value components.unsloth.port int)
    # Fallback mirrors motdeck.yaml's 8899 — deliberately NOT upstream's 8888, which is
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
      _detached "${US_BIN[@]}" "${US_CMD[@]}" >>"$ROOT/data/logs/unsloth.log" 2>&1 &
      _record_child unsloth "$!"
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
      if (( i % 15 == 0 )); then echo "[motdeck] unsloth still starting… (~$((i * 2))s)"; fi
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] unsloth up on http://127.0.0.1:${US_PORT} (Studio API + SPA, loopback only)"
      echo "[motdeck] Studio has its OWN login; on a loopback launch its page auto-fills the"
      echo "[motdeck]   bootstrap credential. Change the password inside its UI."
    else
      echo "ERROR: unsloth did not answer /api/health on :${US_PORT} in ~5min:"
      tail -20 "$ROOT/data/logs/unsloth.log"
      exit 1
    fi
    ;;
  deepseek)
    # OPTIONAL THIRD coding lane — DeepSeek Harness `dsh` (MIT, pre-1.0 developer
    # preview). Like OpenCode it serves its OWN SPA and its own JSON/websocket API on
    # one loopback port, which is exactly the tab shape — no PTY, no xterm.js, no
    # websocket of ours. Unlike OpenCode it is a node app, not a Mach-O.
    #
    # ⚠️ PLACED BEFORE THE opencode) ARM ON PURPOSE. bridge/tests/test_opencode_lane.py
    # slices OpenCode's arm as the text between "\n  opencode)" and "\n  hermes)" so
    # that its assertions can never be satisfied by a neighbour's line. Inserting this
    # arm BETWEEN them would have folded every line below into OpenCode's slice and
    # made that suite assert about the wrong component. bridge/tests/test_deepseek_lane.py
    # slices this one the same way, deepseek) -> opencode).
    ROOT="$(pwd)"
    DS_PREFIX="$ROOT/data/deepseek/npm"
    DS_BIN="$DS_PREFIX/node_modules/.bin/dsh"
    [[ -x "$DS_BIN" ]] || { echo "ERROR: deepseek is not installed ($DS_BIN missing) — click Install first"; exit 1; }
    DS_PORT=$(_manifest_value components.deepseek.port int)
    # Upstream's own default IS 3080 (dsh-host-webserver: `port: ctx.webStartup.port ??
    # 3080`), so unlike OpenCode this fallback is belt-and-braces rather than
    # load-bearing — but the port is still passed EXPLICITLY below, because a tab whose
    # URL is a constant must not depend on a default we do not own.
    [[ "$DS_PORT" =~ ^[0-9]+$ ]] || DS_PORT=3080
    DS_HOME="$ROOT/data/deepseek/home"
    DS_WS="$ROOT/data/deepseek-workspace"
    mkdir -p "$DS_HOME" "$DS_WS"

    # ── THE RUNTIME. node is dsh's RUN-time, not just its build-time, and the app
    # spawns this script from a GUI process whose PATH is not the user's shell PATH —
    # so `node` must be RESOLVED here, not assumed. The user's own node always wins;
    # data/node is the pinned fallback (build.node_pin). scripts/ensure_node.sh prints
    # the path on stdout and everything human on stderr.
    # ⚠️ NO `|| true` HERE, unlike every ensure_bun.sh call site: bun builds an
    # optional SPA, node runs the whole lane. An unresolvable node is a refusal with a
    # sentence, not a degraded start.
    DS_NODE="$(bash scripts/ensure_node.sh 2>/dev/null || true)"
    if [[ -z "$DS_NODE" || ! -x "$DS_NODE" ]]; then
      echo "ERROR: deepseek needs node >= 22.19 (or >= 24) and none could be resolved."
      echo "       Run ./scripts/ensure_node.sh to see exactly what was tried. Your own"
      echo "       node is always preferred; data/node is only the pinned fallback."
      exit 1
    fi
    DS_NODE_DIR="$(dirname "$DS_NODE")"

    # ── config fan-out: point dsh at OUR runner, the same way OpenCode is pointed ──
    # Its settings document is $DSH_HOME/settings.yaml (dsh-settings-file: `path`
    # defaults to "settings.yaml under MOT Deck home"; the home resolves as explicit
    # config, then $DSH_HOME, then ~/.dsh) — which is why the DSH_HOME export below is
    # what makes this file the one it reads. We never write ~/.dsh.
    # MERGE, never overwrite: only the two sections we own are replaced, so anything
    # the user adds in that file (theme, permission presets, other providers) survives.
    DS_BASE=$(_manifest_value runner.endpoint str)
    DS_KEY=$(_manifest_value runner.api_key str)
    DS_MODEL=$(_runner_active_model 2>/dev/null || true)
    if [[ -z "$DS_MODEL" ]]; then
      DS_MODEL=$(_manifest_value runner.model str)
    fi
    _require_secret "$DS_KEY" runner.api_key || exit 1
    [[ -n "$DS_BASE" ]] || DS_BASE="http://127.0.0.1:6767/v1"
    [[ "$DS_MODEL" == \#* ]] && DS_MODEL=""
    DS_SETTINGS="$DS_HOME/settings.yaml"
    # THE KEY IS NAMED, NOT INLINE. dsh's `apiKeyEnv` holds an env var NAME resolved
    # per request, so the secret never enters settings.yaml — and the NAME is DERIVED
    # by the seeder (seed_deepseek_config.key_env_name), never hand-picked twice here.
    # Two hand-picked names is how the goose lane ended up exporting a
    # MOT_DECK_RUNNER_API_KEY that nothing read.
    # ⚠️ PICK A PYTHON THAT HAS PyYAML, AND DO NOT ASSUME `python3` IS IT. FOUND ON THE
    # FIRST REAL WALK OF THIS ARM: settings.yaml is YAML, the seeder needs PyYAML, and a
    # bare `python3` (Debi's is /Users/debik/.local/bin/python3) does NOT have it — so
    # the whole point of the lane, the seeded provider, degraded to
    # "WARNING: PyYAML unavailable" on a perfectly healthy machine. The bridge venv
    # always has it (it is in bridge/requirements.txt). This is ship.sh's own idiom,
    # verbatim in spirit — its manifest merge picks an interpreter the same way and for
    # the same stated reason ("a bare system python3 often does NOT — and skipping
    # silently there would hide a missing component card").
    # _yaml_python owns the compatibility order for every YAML-dependent seeder:
    # "$ROOT/data/bridge-venv/bin/python" remains its first candidate, followed by
    # "$HOME/Library/Application Support/MOT Deck/data/bridge-venv/bin/python" for
    # compatibility with a repo checkout whose provisioned bridge venv is the only one.
    DS_PY="$(_yaml_python || true)"
    if [[ -z "$DS_PY" ]]; then
      echo "[motdeck] WARNING: no python with PyYAML found (no Python interpreter can import it), so the 'MOT Deck"
      echo "[motdeck]   (local)' provider will NOT be written. DeepSeek will start, but"
      echo "[motdeck]   its model picker will not list your models. Bootstrap the bridge"
      echo "[motdeck]   venv (PyYAML is in bridge/requirements.txt), then start DeepSeek again."
    fi
    DS_KEY_ENV="MOT_DECK_LOCAL_API_KEY"
    if [[ -n "$DS_PY" ]]; then
      DS_KEY_ENV="$("$DS_PY" -c 'import importlib.util;s=importlib.util.spec_from_file_location("s","scripts/seed_deepseek_config.py");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(m.key_env_name())' 2>/dev/null || true)"
    fi
    if [[ -z "$DS_KEY_ENV" ]]; then
      # The seeder could not even be imported. Fall back to the SAME string its pure
      # function returns for the default product name, so the env we export still
      # matches whatever provider block is already on disk from a previous, working
      # Start — a mismatched name would turn a working lane into MISSING_CREDENTIAL.
      DS_KEY_ENV="MOT_DECK_LOCAL_API_KEY"
      echo "[motdeck] note: could not read the derived key env-var name from the seeder;"
      echo "[motdeck]   using ${DS_KEY_ENV} (its value for the default product name)."
    fi
    if [[ -n "$DS_PY" ]]; then
      DS_SETTINGS="$DS_SETTINGS" DS_BASE="$DS_BASE" DS_KEY_ENV="$DS_KEY_ENV" \
        DS_MODEL="$DS_MODEL" MOT_DECK_ROOT="$ROOT" \
        "$DS_PY" scripts/seed_deepseek_config.py || \
        echo "[motdeck] WARNING: DeepSeek provider seeding failed — its model picker may not list yours"
    fi

    # Clear the port FIRST — LISTENER-scoped and OWNERSHIP-checked (standing ops rule).
    # ⚠️ NO name signature is added to _cmd_looks_like_ours for this component, on
    # purpose: a standalone `dsh` a user installed themselves would match its own name,
    # and that is precisely the process the guard exists to protect (the Unsloth /
    # goose-Desktop class, twice bitten). Ours always runs out of
    # "$ROOT/data/deepseek/npm/...", which the existing PATH rule already covers.
    _clear_port "$DS_PORT" deepseek
    sleep 1
    {
      echo "[motdeck] ----- start $(date '+%Y-%m-%d %H:%M:%S') -- loopback 127.0.0.1:${DS_PORT}, NO auth BY DESIGN"
      echo "[motdeck]   loopback is dsh's POLICY, not just its default: its CLI refuses --host 0.0.0.0."
      echo "[motdeck]   this log APPENDS: one block per Start, so N blocks = N starts, not N servers."
    } >>"$ROOT/data/logs/deepseek.log"

    (
      cd "$DS_WS"
      # THE CONFINEMENT. DSH_HOME is upstream's documented home override and the ONLY
      # thing keeping its settings, profiles, sessions and storages inside
      # data/deepseek/home instead of ~/.dsh. VERIFIED on a from-scratch walk: after
      # an install, a --help, a web boot and eight headless turns, ~/.dsh did not
      # exist.
      # DSH_TELEMETRY_DISABLED=1 is upstream's OWN authoritative pre-load kill switch.
      # At this pin the composed tree already defaults the telemetry mode to DISABLED
      # (verified in `dsh --dump-config`), so this is belt-and-braces — which is the
      # point: a future pin changing that default cannot switch it on under us.
      # ⚠️ `VAR=val _detached …` would NOT be safe: bash's temporary-assignment prefix
      # on a FUNCTION call sets the variables in the shell rather than reliably placing
      # them in the exec'd program's environment, so the confinement could silently
      # evaporate and dsh would write to ~/.dsh after all — a silent-wrong, not a
      # crash. `env` makes it explicit, exactly as the opencode/searxng arms do.
      # PATH carries the resolved node's directory FIRST: the launcher is a node script
      # with a `#!/usr/bin/env node` shebang, so a stale or too-old node earlier on
      # PATH would otherwise be the one that ran it.
      _detached env DSH_HOME="$DS_HOME" \
      DSH_TELEMETRY_DISABLED=1 \
      "$DS_KEY_ENV"="$DS_KEY" \
      PATH="$DS_NODE_DIR:$PATH" \
      "$DS_NODE" "$DS_BIN" web --host 127.0.0.1 --port "$DS_PORT" --no-open \
        >>"$ROOT/data/logs/deepseek.log" 2>&1 &
      _record_child deepseek "$!"
    )
    up=0
    TRIES=60
    for i in $(seq 1 "$TRIES"); do
      # `/` (its embedded SPA) IS the health probe, and that is not laziness: measured
      # against the real server at this pin, /api is a POST/websocket RPC surface and
      # every plausible health path — /healthz, /health, /api/health, /version — is a
      # 404. `/` returning its own document is the only honest HTTP readiness signal
      # upstream offers.
      if curl -sf -m 2 "http://127.0.0.1:${DS_PORT}/" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat "$ROOT/data/deepseek.pid")" 2>/dev/null || {
        echo "ERROR: deepseek exited on launch. Last log lines:"
        tail -20 "$ROOT/data/logs/deepseek.log"
        echo "       (most common cause: node too old — this launch used"
        echo "        ${DS_NODE}, $("$DS_NODE" --version 2>/dev/null || echo 'version unreadable'))"
        exit 1; }
      sleep 2
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] deepseek up on http://127.0.0.1:${DS_PORT} (dsh web — its own SPA + API, loopback, NO auth)"
      echo "[motdeck] workspace: $DS_WS — the only directory it is started in"
      echo "[motdeck] home:      $DS_HOME (settings.yaml, profiles, sessions — never ~/.dsh)"
      # ── PROVIDER SELF-CHECK — and an HONEST one, which here means admitting what
      # cannot be checked. ⚠️ There is NO route to ask this server which providers it
      # resolved: its whole API is a Typert RPC over POST /api plus two websockets, and
      # MEASURED at this pin a deliberately-broken provider block produced a server
      # that started, answered `GET /` with 200, and printed NOTHING to stdout or
      # stderr — the provider was simply absent. So the OpenCode-style "ask the server
      # and print a decidable line" check is not available here, and faking it with a
      # grep that can never match would be worse than saying so.
      # What IS decidable is the file we just wrote, read back independently of the
      # writer: the re-read proves the section survived the YAML round trip, and the
      # two refusal branches below are the exact two ways this lane goes quiet.
      if [[ -n "$DS_PY" ]]; then
        "$DS_PY" - "$DS_SETTINGS" <<'PYDS' || echo "[motdeck] note: could not verify the seeded provider (harmless; the seed line above is the record)"
import sys
try:
    import yaml
except Exception:
    print("[motdeck] provider check: PyYAML unavailable — not verified")
    raise SystemExit(0)
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = yaml.safe_load(fh) or {}
except Exception as e:                                              # noqa: BLE001
    # 200, not 80: the first walk truncated an ENOENT message exactly at the repo path
    # and the line read like a path-splitting bug rather than a missing file.
    print("[motdeck] provider check: could not re-read settings.yaml (%s)" % str(e)[:200])
    raise SystemExit(0)
p = (((d.get("llm-pi-ai") or {}).get("providers") or {}).get("mot-deck")) or {}
ms = p.get("models") or []
if not p:
    print("[motdeck] provider check: NOT PRESENT in settings.yaml — dsh's model picker "
          "will NOT list your models. The seed line above says why.")
elif not ms:
    print("[motdeck] provider check: present but with NO models — dsh REFUSES a "
          "hand-declared route with an empty model list, so it will not load.")
else:
    sel = d.get("agent-default-model") or {}
    print("[motdeck] provider check: 'MOT Deck (local)' -> %s · %d model(s) · default %s"
          % (p.get("baseURL"), len(ms),
             ("%s/%s" % (sel.get("provider"), sel.get("model")))
             if sel.get("model") else "unset"))
    print("[motdeck]   dsh re-reads settings.yaml per request, so a model switch or a "
          "Rescan reaches it with NO restart of this component.")
PYDS
      else
        echo "[motdeck] provider check: NOT VERIFIED — PyYAML is unavailable, so the"
        echo "[motdeck]   provider was not written; bootstrap the bridge venv, then start it again."
      fi
      echo "[motdeck] FIRST RUN: it shows an 'Internal Testing Notice' once, then asks you"
      echo "[motdeck]   to choose a WORKSPACE before it will take a message — click 'Add"
      echo "[motdeck]   workspace' and pick data/deepseek-workspace. That opens macOS's own"
      echo "[motdeck]   folder chooser, launched by dsh itself; if it does not come forward,"
      echo "[motdeck]   click the MOT Deck icon in the Dock. (Ledger U67.)"
    else
      echo "ERROR: deepseek did not answer on :${DS_PORT} in ~2min. Last log lines:"
      tail -20 "$ROOT/data/logs/deepseek.log"
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
    OC_PORT=$(_manifest_value components.opencode.port int)
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
    OC_BASE=$(_manifest_value runner.endpoint str)
    OC_KEY=$(_manifest_value runner.api_key str)
    OC_MODEL=$(_runner_active_model 2>/dev/null || true)
    if [[ -z "$OC_MODEL" ]]; then
      OC_MODEL=$(_manifest_value runner.model str)
    fi
    _require_secret "$OC_KEY" runner.api_key || exit 1
    [[ -n "$OC_BASE" ]] || OC_BASE="http://127.0.0.1:6767/v1"
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
      MOT_DECK_ROOT="$ROOT" python3 scripts/seed_opencode_config.py

    # A catalog file on disk is not evidence of what an already-running OpenCode
    # process loaded. This marker is written only from that process's own /provider
    # response below and is bound to the exact child PID + kernel birth stamp.
    rm -f "$ROOT/data/opencode.runtime-catalog.json"

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
      echo "[motdeck] ----- start $(date '+%Y-%m-%d %H:%M:%S') -- loopback 127.0.0.1:${OC_PORT}, NO auth BY DESIGN"
      echo "[motdeck]   the 'OPENCODE_SERVER_PASSWORD is not set; server is unsecured' line below is EXPECTED:"
      echo "[motdeck]   we never set that variable - it would gate the embedded SPA this app's own tab loads."
      echo "[motdeck]   this log APPENDS: one block per Start, so N blocks = N starts, not N servers."
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
      # ⚠️ `VAR=val _detached …` would NOT be safe: bash's temporary-assignment
      # prefix on a FUNCTION call sets the variables in the shell rather than
      # reliably placing them in the exec'd program's environment, so the
      # confinement above could silently evaporate and OpenCode would write to
      # ~/.config after all — a silent-wrong, not a crash. `env` makes it explicit
      # and matches how the searxng/voicestudio arms already pass their environment.
      _detached env XDG_CONFIG_HOME="$OC_HOME/config" XDG_CACHE_HOME="$OC_HOME/cache" \
      XDG_DATA_HOME="$OC_HOME/data" XDG_STATE_HOME="$OC_HOME/state" \
      OPENCODE_DISABLE_AUTOUPDATE=1 \
      "$OC_BIN" serve --hostname 127.0.0.1 --port "$OC_PORT" \
        >>"$ROOT/data/logs/opencode.log" 2>&1 &
      _record_child opencode "$!"
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
      # Readiness alone does not bind the answer to the child above: a stranger could
      # win the port between our preflight and OpenCode's bind while our child stayed
      # alive for some unrelated reason. Before trusting /provider, prove that the one
      # listener is the exact PID+kernel-birth launch we recorded. A mismatch reaps
      # only that recorded child and fails the Start; it never adopts or signals the
      # listener that happened to answer.
      if ! _stamp_pidfile_from_port opencode "$OC_PORT"; then
        exit 1
      fi
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
        && echo "[motdeck] project registered for $OC_WS" \
        || echo "[motdeck] note: could not pre-register the workspace project (harmless)"
      echo "[motdeck] opencode up on http://127.0.0.1:${OC_PORT} (server + its own SPA, loopback, NO auth)"
      echo "[motdeck] workspace: $OC_WS — the only directory it is started in"
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
      # Re-bind AFTER the response as well. The first check proves who owned the
      # listener before the request; only this second check proves that the bytes we
      # just received still came from that same exact child generation.
      if ! _stamp_pidfile_from_port opencode "$OC_PORT"; then
        rm -f "$ROOT/data/opencode-provider.json"
        exit 1
      fi
      OC_CFGP="$OC_CFG" python3 - "$ROOT/data/opencode-provider.json" "$ROOT" <<'PYOCCHK' || true
import importlib.util, json, os, sys, tempfile
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = json.load(fh)
except Exception as e:                                            # noqa: BLE001
    print("[motdeck] opencode provider check: could not read /provider (%s)" % e)
    raise SystemExit(0)
conn = [str(x) for x in (d.get("connected") or [])]
allp = {p.get("id"): p for p in (d.get("all") or []) if isinstance(p, dict)}
models = (allp.get("llama.cpp") or {}).get("models") or {}
if not isinstance(models, dict) or any(not isinstance(k, str) for k in models):
    print("[motdeck] opencode provider check: llama.cpp returned an unreadable model map")
    raise SystemExit(0)
n = len(models)
# Launch provenance, not a second catalog: this is an observation about the exact
# current child and is discarded on every Start. The registry remains the inventory.
try:
    root = sys.argv[2]
    helper = os.path.join(root, "bridge", "core", "ownership.py")
    spec = importlib.util.spec_from_file_location("mot_ownership", helper)
    ownership = importlib.util.module_from_spec(spec); spec.loader.exec_module(ownership)
    claim = ownership.read_claim(root, "opencode")
    if not claim:
        raise ValueError("ownership record is absent")
    marker = {"v": 1, "pid": claim[0], "birth": claim[1],
              "connected": "llama.cpp" in conn, "models": sorted(models)}
    directory = os.path.join(root, "data")
    fd, tmp = tempfile.mkstemp(prefix=".opencode-catalog-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(marker, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(directory, "opencode.runtime-catalog.json"))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
except Exception as e:
    print("[motdeck] opencode provider check: runtime marker unavailable (%s)" % e)
if "llama.cpp" in conn:
    # Settings -> Providers and the composer picker read the SAME payload — the
    # intersection of `all` and `connected` (app/src/hooks/use-providers.ts:52-60,
    # settings-v2/providers.tsx:48-52, context/models.tsx:40-47) — so this one word
    # answers for both surfaces at once.
    print("[motdeck] opencode provider check: llama.cpp CONNECTED, %d model(s) — it is"
          " in Settings -> Providers and in the model picker" % n)
else:
    # Only two things can delete a provider that is present in the config, and both are
    # now repaired above rather than merely reported; if we still land here, the config
    # we wrote is not the config this server read.
    print("[motdeck] opencode provider check: llama.cpp NOT CONNECTED — the model")
    print("[motdeck]   picker will fall back to OpenCode Zen models (e.g. Big Pickle).")
    print("[motdeck]   the config we wrote: %s" % os.environ.get("OC_CFGP", "?"))
    print("[motdeck]   what the server reports connected: %s" % (conn or "(nothing)"))
    print("[motdeck]   in `all` at all: %s" % ("yes" if "llama.cpp" in allp else "no"))
    print("[motdeck]   NOTE a running OpenCode reads its config at BOOT — if you just")
    print("[motdeck]   shipped motdeck code, Stop and Start this component (shipping is")
    print("[motdeck]   not restarting), then reload the tab with cmd-R.")
PYOCCHK
      rm -f "$ROOT/data/opencode-provider.json"
      # The tab does not open :${OC_PORT}/ — it opens the bridge's /opencode, a 307 into
      # OpenCode's own new-session composer for this directory, so its home screen (the
      # one that says "Nothing here yet" beside an empty Projects rail) never appears.
      # If it ever DOES appear, the manual equivalent is one click: Add project →
      # data/opencode-workspace.
      echo "[motdeck] the tab lands on a new session for that workspace (via the bridge's"
      echo "[motdeck]   /opencode redirect). If you ever see OpenCode's own empty home"
      echo "[motdeck]   screen instead: Add project -> $OC_WS, once."
      echo "[motdeck] REMINDER: OpenCode requires a TOOL-CALLING model (the green 'tools'"
      echo "[motdeck]   pill in Models). Without one it looks broken, not merely slower."
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
    H_PY="$(_yaml_python || true)"
    # M1: point Hermes at MOT Deck RUNNER endpoint (:6767 + key). Patches ONLY the
    # managed model.* keys, preserving the rest of an existing config; creates minimal if absent.
    HCFG="${HERMES_HOME:-$HOME/.hermes}/config.yaml"
    BASE_URL=$(_manifest_value runner.endpoint str)
    KEY=$(_manifest_value runner.api_key str)
    MODEL=$(_runner_active_model 2>/dev/null || true)
    if [[ -n "$MODEL" ]]; then
      MSRC="live runner launch provenance"
    else
      MODEL=$(_manifest_value runner.model str)
      MSRC="saved runner pin (no live launch provenance)"
    fi
    _require_secret "$KEY" runner.api_key || exit 1
    [[ -n "$BASE_URL" ]] || BASE_URL="http://127.0.0.1:6767/v1"
    CTXLEN=$(_manifest_value runner.ctx_size int)
    [[ "$MODEL" == \#* ]] && MODEL=""   # guard: never treat a stray comment as a model name
    [[ "$CTXLEN" =~ ^[0-9]+$ ]] || CTXLEN=65536
    # Launch provenance outranks motdeck.yaml intent. A first-row `/v1/models` probe
    # is NOT used here: llama.cpp reports its alias, but MLX may enumerate cache rows
    # unrelated to the model this child was launched with. `_runner_active_model`
    # accepts only the exact PID + kernel-birth ownership record written after the
    # runner became ready; the pin is used only when that live fact is unavailable.
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
    # ONE writer owns ~/.hermes/config.yaml's two motdeck surfaces:
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
    if [[ -n "$H_PY" ]]; then
      # This intentionally replaces the old bare Python 3 seeder invocation:
      # only the resolver proves the selected interpreter can import the YAML dependency.
      HERMES_CFG="$HCFG" BASE_URL="$BASE_URL" KEY="$KEY" MODEL="$MODEL" CTXLEN="$CTXLEN" \
        MOT_DECK_ROOT="$PWD" "$H_PY" scripts/seed_hermes_provider.py || \
        echo "[motdeck] WARNING: Hermes wiring failed — check ~/.hermes/config.yaml"
    else
      echo "[motdeck] WARNING: no Python interpreter can import PyYAML, so Hermes's"
      echo "[motdeck]   MOT Deck provider and YAML-backed config follow-ups will NOT be"
      echo "[motdeck]   written. Hermes will start without that configuration. Bootstrap"
      echo "[motdeck]   the bridge venv (PyYAML is in bridge/requirements.txt), then restart."
    fi
    # The provider slug the seed decided ('custom:<normalized name>', or the user's
    # renamed one) — read back for the post-start picker check below.
    # ⚠️ NO FALLBACK, deliberately. Falling back to bare `custom` would make the check
    # look for a slug that ALWAYS exists (Hermes lists every unconfigured canonical
    # provider, `custom` among them, with 0 models) — so a Start where the seed refused
    # would print "IS in its own model picker" about a row that is not ours. An empty
    # slug makes the check say the truth instead: it could not verify anything.
    HPROV=""
    if [[ -n "$H_PY" ]]; then
      HPROV=$("$H_PY" - <<'PYSLUG'
import json, os
try:
    with open(os.path.join("data", "hermes-provider.json"), encoding="utf-8") as fh:
        print(str(json.load(fh).get("slug") or "").strip())
except Exception:
    print("")
PYSLUG
      )
    fi
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
    print("[motdeck] WARNING: approvals.mode is 'off' in ~/.hermes/config.yaml — "
          "dangerous shell commands will run with NO approval card. Set 'manual' or 'smart'.")
PYAPPR
    # ── PATH-GUARD FENCE (B1): seed our pre_tool_call plugin + enable it ──────────
    # guards/motdeck-path-guard/ is the source of truth; it is copied (if changed)
    # into ~/.hermes/plugins/motdeck-path-guard/ and added to plugins.enabled, which
    # Hermes requires for user plugins (opt-in allow-list, hermes_cli/plugins.py
    # _get_enabled_plugins). policy.yaml gets {MOT_DECK_ROOT} substituted with this
    # repo root; {HERMES_CWD}/{TMPDIR} stay placeholders (resolved at call time).
    HGUARD_SRC="$PWD/guards/motdeck-path-guard"
    HGUARD_DST="${HERMES_HOME:-$HOME/.hermes}/plugins/motdeck-path-guard"
    if [[ -d "$HGUARD_SRC" && -n "$H_PY" ]]; then
      HGUARD_SRC="$HGUARD_SRC" HGUARD_DST="$HGUARD_DST" MOT_DECK_ROOT="$PWD" \
        HCFG="$HCFG" "$H_PY" - <<'PYGUARD'
import os, re, shutil, tempfile, yaml
src, dst = os.environ["HGUARD_SRC"], os.environ["HGUARD_DST"]
root, cfg = os.environ["MOT_DECK_ROOT"], os.environ["HCFG"]
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
    text = open(pol, encoding="utf-8").read().replace("{MOT_DECK_ROOT}", root)
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
        print("[motdeck] WARNING: PyYAML unavailable — cannot verify plugins.enabled")
        return None
    try:
        data = yaml.safe_load(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}
    except Exception as exc:
        print("[motdeck] WARNING: could not parse %s (%s) — plugins.enabled untouched" % (path, exc))
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
    # U150: the product-identity change also renamed this MOT Deck-owned plugin.
    # Replace the retired id in place, deduplicate both ids, and preserve every
    # user-owned neighbour in its original order. Merely appending the new id leaves
    # both pre_tool_call hooks active and can show two approval cards for one write.
    current, retired = "motdeck-path-guard", "harness-path-guard"
    rewritten, have_current = [], False
    for item in enabled:
        token = str(item)
        if token == retired:
            if not have_current:
                rewritten.append(current)
                have_current = True
            continue
        if token == current:
            if not have_current:
                rewritten.append(item)
                have_current = True
            continue
        rewritten.append(item)
    if not have_current:
        rewritten.append(current)
    plugins["enabled"] = rewritten
    disabled = plugins.get("disabled")
    if isinstance(disabled, list):
        plugins["disabled"] = [x for x in disabled
                               if str(x) not in (current, retired)]
    config_changed = rewritten != enabled or plugins.get("disabled") != disabled
    if not config_changed:
        return False
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
    os.replace(tmp, path)
    return True

added = enable_in_config(cfg)
# The retired directory was a generated copy whose own README says it must never be
# hand-edited. Remove it only after the config transaction succeeded (or proved the
# new id already active), and only when a direct plugin.yaml identifies that exact
# retired plugin. A symlink, special file, unparseable config, or foreign directory is
# left untouched and reported rather than guessed at.
retired_dir = os.path.join(os.path.dirname(dst), "harness-path-guard")
retired_removed = False
if added is not None and os.path.lexists(retired_dir):
    retired_manifest = os.path.join(retired_dir, "plugin.yaml")
    safe = (not os.path.islink(retired_dir) and os.path.isdir(retired_dir)
            and not os.path.islink(retired_manifest)
            and os.path.isfile(retired_manifest))
    try:
        retired_data = yaml.safe_load(open(retired_manifest, encoding="utf-8").read()) if safe else None
        safe = isinstance(retired_data, dict) and retired_data.get("name") == "harness-path-guard"
    except Exception:
        safe = False
    if safe:
        shutil.rmtree(retired_dir)
        retired_removed = True
    else:
        print("[motdeck] WARNING: retired path-guard directory is not a verified "
              "MOT Deck-owned plugin; leaving it untouched: " + retired_dir)
bits = []
if changed: bits.append("seeded " + ", ".join(changed))
if added: bits.append("enabled in plugins.enabled")
if retired_removed: bits.append("retired old plugin id and generated directory")
print("[motdeck] path-guard plugin: " + ("; ".join(bits) if bits else "up to date"))
PYGUARD
    elif [[ ! -d "$HGUARD_SRC" ]]; then
      echo "[motdeck] WARNING: guards/motdeck-path-guard missing — file writes are UNFENCED"
    else
      echo "[motdeck] path-guard config unchanged — PyYAML is unavailable (see warning above)"
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
    # `url` is ours too: it must point at the bridge port MOT Deck is running on,
    # or the toolset simply 404s.
    BR_PORT=$(_manifest_value bridge.port int)
    BR_PORT="${BR_PORT:-8700}"
    if [[ -n "$H_PY" ]]; then
      HCFG="$HCFG" BR_PORT="$BR_PORT" "$H_PY" - <<'PYLOFFICE'
import os, tempfile
cfg, port = os.environ["HCFG"], os.environ["BR_PORT"]
try:
    import yaml
except Exception:
    print("[motdeck] WARNING: PyYAML unavailable — LOffice MCP server NOT registered")
    raise SystemExit(0)
url = "http://127.0.0.1:%s/mcp/office" % port
try:
    data = yaml.safe_load(open(cfg, encoding="utf-8").read()) if os.path.exists(cfg) else {}
except Exception as exc:
    print("[motdeck] WARNING: could not parse %s (%s) - mcp_servers untouched" % (cfg, exc))
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
    print("[motdeck] LOffice MCP server: already registered at " + url)
    raise SystemExit(0)
servers["loffice"] = entry
data["mcp_servers"] = servers
d = os.path.dirname(cfg) or "."
os.makedirs(d, exist_ok=True)
fd, tmp = tempfile.mkstemp(dir=d)
with os.fdopen(fd, "w", encoding="utf-8") as fh:
    yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
os.replace(tmp, cfg)
print("[motdeck] LOffice MCP server registered at " + entry["url"]
      + " (trust: untrusted - write tools get an approval card)")
for _n in notes:
    print("[motdeck]   " + _n)
PYLOFFICE
    else
      echo "[motdeck] LOffice MCP server NOT registered — PyYAML is unavailable (see warning above)"
    fi
    PORT=9119
    # `hermes dashboard` = same server as `hermes serve` PLUS Hermes's own web UI
    # (embedded chat, live tool feed, approvals, sessions). --no-open: we embed it in
    # the MOT Deck tab, not a browser. --skip-build: serve the prebuilt web_dist from
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
    # Hermes's WhatsApp onboarding writes BOTH YAML and WHATSAPP_ENABLED=true, while
    # its dashboard toggle writes only YAML. The env value wins on read. We must not
    # guess which side of an unjournaled mismatch is newer user intent: startup only
    # finishes a M.O.T transaction interrupted between its two atomic replacements.
    # Run after prior owned Hermes quiescence because Hermes does not share our lock.
    # Pairing credentials and session files remain outside this helper.
    if [[ -f scripts/reconcile_hermes_whatsapp.py ]]; then
      [[ -n "$H_PY" ]] || {
        echo "ERROR: no Python with PyYAML can recover an interrupted Hermes WhatsApp transaction."
        exit 1
      }
      "$H_PY" scripts/reconcile_hermes_whatsapp.py \
        --home "$(dirname "$HCFG")" --recover \
        || { echo "ERROR: Hermes WhatsApp transaction recovery failed; credentials were not touched."; exit 1; }
    fi
    : > data/logs/hermes.log
    # Deterministic dashboard session token (Hermes chat lane): the dashboard seeds
    # its _SESSION_TOKEN from HERMES_DASHBOARD_SESSION_TOKEN (the same trick Hermes's
    # own desktop shell uses), so the Bridge can auth the /api/ws?token=<...> gateway.
    # Precedence: motdeck.yaml components.hermes.dashboard_token override → else
    # generate ONCE into data/hermes.token (chmod 600) and reuse on every start.
    HTOKEN=$(_manifest_value components.hermes.dashboard_token str)
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
    _detached env HERMES_DESKTOP=1 HERMES_DASHBOARD_SESSION_TOKEN="$HTOKEN" hermes dashboard --no-open --skip-build --host 127.0.0.1 --port "$PORT" >>data/logs/hermes.log 2>&1 &
    _record_child hermes "$!"
    up=0
    for _ in $(seq 1 25); do
      if curl -sf -m 1 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 \
         || nc -z 127.0.0.1 "$PORT" >/dev/null 2>&1; then up=1; break; fi
      kill -0 "$(cat data/hermes.pid)" 2>/dev/null || { echo "ERROR: hermes dashboard exited on launch. Last log lines:"; tail -15 data/logs/hermes.log; exit 1; }
      sleep 1
    done
    if [[ "$up" == "1" ]]; then
      echo "[motdeck] hermes dashboard up on http://127.0.0.1:${PORT} (UI + API; model=$MODEL [$MSRC] @ $BASE_URL)"
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
    print("[motdeck] hermes provider check: the seed wrote no verdict this Start (see "
          "the warning above) — the picker was NOT verified.")
    raise SystemExit(0)
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        rows = json.load(fh).get("providers") or []
except Exception as e:                                            # noqa: BLE001
    print("[motdeck] hermes provider check: could not read /api/model/options (%s)" % e)
    raise SystemExit(0)
mine = next((r for r in rows if str(r.get("slug", "")).lower() == slug), None)
if mine and (mine.get("models") or []):
    print('[motdeck] hermes provider check: "%s" IS in its own model picker — '
          "%d model(s)%s" % (mine.get("name"), len(mine.get("models") or []),
                             ", currently selected" if mine.get("is_current") else ""))
elif mine:
    # The row reached Hermes but carries nothing to pick — a picker the user would
    # find empty. Saying "it IS there" here would be true and useless.
    print('[motdeck] hermes provider check: "%s" is in the picker but lists NO models'
          " — check data/models.json (the registry the row is seeded from)."
          % mine.get("name"))
else:
    print("[motdeck] hermes provider check: %s NOT in the picker — its Models page will"
          " show the bare 'Custom endpoint' row instead." % slug)
    print("[motdeck]   config: %s" % os.environ.get("HCFG", "~/.hermes/config.yaml"))
    print("[motdeck]   rows it does list: %s"
          % (", ".join(str(r.get("slug")) for r in rows[:8]) or "(none)"))
PYHCHK
      rm -f data/hermes-model-options.json
      echo "[motdeck] tool-calling proof: run scripts/test_hermes.sh"
    else
      echo "ERROR: hermes dashboard did not open :${PORT} within 25s. Last log lines:"
      tail -15 data/logs/hermes.log
      exit 1
    fi
    ;;
  *) echo "usage: $0 runner|hermes|odysseus|searxng|voicestudio|voicebox|comfyui|unsloth|opencode|deepseek"; exit 1 ;;
esac
