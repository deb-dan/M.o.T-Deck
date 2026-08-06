#!/usr/bin/env bash
# Harness OFFLINE first-run provisioner (§G-phase3, fat installer).
# Invoked by main.swift on a fresh Mac from inside the app bundle:
#     bash firstrun_fat.sh <RESOURCES_DIR> <DEST_ROOT>
# where RESOURCES_DIR = Harness.app/Contents/Resources (holds the bundled payloads) and
# DEST_ROOT = ~/Library/Application Support/Harness (the runtime root).
#
# Unlike scripts/firstrun.sh (portable, needs internet + brew + npm), this variant provisions
# EVERYTHING OFFLINE from bundled payloads:
#   • standalone CPython (relocatable)     → data/python-standalone/
#   • an arm64 wheelhouse                   → pip install --no-index --find-links (all 5 venvs)
#   • pinned vendor SOURCE + web_dist       → extracted from the seed
#   • pinned llama-server                   → data/llamacpp/build/bin/
# Creating the venvs ON the target machine (from the bundled python) sidesteps venv
# relocatability entirely. No PyPI, no npm, no brew, no git needed. Fails loudly naming the
# exact component + its log. Leaves components INSTALLED-BUT-STOPPED; the panel's §E setup
# checklist starts them (fat first-run installs; §E starts — no duplication).
set -euo pipefail

RES="${1:-}"; DEST="${2:-}"
[[ -n "$RES"  && -d "$RES"  ]] || { echo "[firstrun-fat] ERROR: resources dir missing: '$RES'"  >&2; exit 1; }
[[ -n "$DEST" ]]               || { echo "[firstrun-fat] ERROR: destination root not given"       >&2; exit 1; }

say()  { printf "\033[1;36m[firstrun-fat]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[firstrun-fat]\033[0m %s\n" "$*" >&2; exit 1; }

SEED="$RES/harness-seed-fat.tar.gz"
PYTAR="$RES/python-standalone.tar.gz"
WHEELS="$RES/wheelhouse"
[[ -f "$SEED"  ]] || fail "bundled seed missing: $SEED (not a fat build?)"
[[ -f "$PYTAR" ]] || fail "bundled standalone python missing: $PYTAR"
[[ -d "$WHEELS" ]] || fail "bundled wheelhouse missing: $WHEELS"

# ---------- 1. extract the seed → runtime root ----------
say "Provisioning Harness into: $DEST"
mkdir -p "$DEST"
tar xzf "$SEED" -C "$DEST" || fail "could not extract the seed into $DEST"
cd "$DEST"

LOGDIR="$DEST/data/logs"; mkdir -p "$LOGDIR"

# ---------- 2. relocatable standalone python ----------
PYDIR="$DEST/data/python-standalone"
if [[ ! -x "$PYDIR/bin/python3" ]]; then
  say "Unpacking bundled standalone CPython…"
  rm -rf "$PYDIR"; mkdir -p "$PYDIR"
  tar xzf "$PYTAR" -C "$PYDIR" || fail "could not extract standalone python"
fi
PYBIN="$(find "$PYDIR" -type f -name python3 -path '*/bin/*' 2>/dev/null | head -1)"
[[ -x "$PYBIN" ]] || PYBIN="$PYDIR/bin/python3"
[[ -x "$PYBIN" ]] || fail "standalone python not found under $PYDIR"
say "Using python: $("$PYBIN" --version 2>&1)"

# Offline pip everywhere: never reach the network, always resolve from the wheelhouse
# (this also feeds pip's PEP517 build-isolation env, so editable installs of the vendored
# projects pick up their build backends from the wheelhouse too).
export PIP_NO_INDEX=1
export PIP_FIND_LINKS="$WHEELS"
export PIP_DISABLE_PIP_VERSION_CHECK=1

mkvenv() { # mkvenv <path> <component> <logfile>
  local vpath="$1" comp="$2" log="$3"
  say "Creating venv for ${comp}…"
  "$PYBIN" -m venv "$vpath" >>"$log" 2>&1 || fail "$comp: venv creation failed — see $log"
  # ensure pip exists (standalone builds ship it, but be defensive) + upgrade from wheelhouse
  "$vpath/bin/python" -m ensurepip --upgrade >>"$log" 2>&1 || true
  "$vpath/bin/python" -m pip install --no-index --find-links "$WHEELS" -U pip setuptools wheel >>"$log" 2>&1 \
    || fail "$comp: could not seed pip/setuptools/wheel from the wheelhouse — see $log"
}
pipi() { # pipi <venv> <component> <logfile> <pip args…>  — fatal on failure
  local vpath="$1" comp="$2" log="$3"; shift 3
  "$vpath/bin/python" -m pip install --no-index --find-links "$WHEELS" "$@" >>"$log" 2>&1 \
    || fail "$comp: offline install failed — see $log (look for the first 'ERROR:' / missing wheel)"
}
pipi_try() { # pipi_try <venv> <logfile> <pip args…>  — NON-fatal; returns pip's exit code
  local vpath="$1" log="$2"; shift 2
  "$vpath/bin/python" -m pip install --no-index --find-links "$WHEELS" "$@" >>"$log" 2>&1
}

# ---------- 3. bridge venv ----------
BLOG="$LOGDIR/firstrun_bridge.log"; : >"$BLOG"
mkvenv data/bridge-venv bridge "$BLOG"
pipi data/bridge-venv bridge "$BLOG" -r bridge/requirements.txt

# ---------- 4. hermes venv (editable install of the vendored source; web_dist prebuilt) ----------
HLOG="$LOGDIR/firstrun_hermes.log"; : >"$HLOG"
mkvenv data/hermes-venv hermes "$HLOG"
# try the [all] extra first; fall back to the base package (fatal only if BOTH fail).
if ! pipi_try data/hermes-venv "$HLOG" -e "vendor/hermes[all]"; then
  say "hermes: [all] extra failed offline — retrying base package…"
  pipi data/hermes-venv hermes "$HLOG" -e "vendor/hermes"
fi
[[ -f vendor/hermes/hermes_cli/web_dist/index.html ]] \
  || say "WARN: hermes web_dist not found in the seed — dashboard will run headless (API only)."

# ---------- 5. odysseus venv + admin seed ----------
OLOG="$LOGDIR/firstrun_odysseus.log"; : >"$OLOG"
mkvenv data/odysseus-venv odysseus "$OLOG"
pipi data/odysseus-venv odysseus "$OLOG" -r vendor/odysseus/requirements.txt
pipi_try data/odysseus-venv "$OLOG" ddgs || say "note: ddgs not in wheelhouse — DDG web-search fallback unavailable until installed."
# setup.py seeds the admin account + DB (fully local, no network).
( cd vendor/odysseus && ODYSSEUS_ADMIN_USER=admin ODYSSEUS_ADMIN_PASSWORD=admin123 \
    "$DEST/data/odysseus-venv/bin/python" setup.py ) >>"$OLOG" 2>&1 \
  || fail "odysseus: setup.py failed — see $OLOG"
# connect step: seed the runner endpoint (runner isn't up yet — endpoint is seeded, model
# auto-discovers on Start; the || true mirrors install_component.sh).
( cd vendor/odysseus && "$DEST/data/odysseus-venv/bin/python" "$DEST/scripts/seed_odysseus_jan.py" ) >>"$OLOG" 2>&1 || true

# ---------- 6. searxng venv + settings ----------
SLOG="$LOGDIR/firstrun_searxng.log"; : >"$SLOG"
mkvenv data/searxng-venv searxng "$SLOG"
pipi data/searxng-venv searxng "$SLOG" -U pyyaml msgspec typing-extensions pybind11
# editable, no build isolation (backends already seeded in the venv); offline via env vars.
pipi data/searxng-venv searxng "$SLOG" --no-build-isolation -e vendor/searxng
mkdir -p data/searxng
if [[ ! -f data/searxng/settings.yml ]]; then
  SECRET="$("$PYBIN" -c 'import secrets; print(secrets.token_hex(32))')"
  cat > data/searxng/settings.yml <<EOF
use_default_settings: true
server:
  secret_key: "$SECRET"
  bind_address: "127.0.0.1"
  port: 8080
  limiter: false
search:
  formats:
    - html
    - json
EOF
fi

# ---------- 7. mlx runtime venv ----------
# PINNED from harness.yaml build.mlx_*_pin — the same values build_app.sh bundled into
# the wheelhouse. Asking for anything else here fails OFFLINE ("no matching distribution").
# Empty pin ⇒ fall back to unpinned so a hand-edited yaml can't hard-block provisioning.
_yb_mlx() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' "$DEST/harness.yaml" 2>/dev/null; }
MLX_LM_PIN="$(_yb_mlx mlx_lm_pin)"; MLX_VLM_PIN="$(_yb_mlx mlx_vlm_pin)"
if [[ -n "$MLX_LM_PIN" && -n "$MLX_VLM_PIN" ]]; then
  MLX_PKGS=("mlx-lm==$MLX_LM_PIN" "mlx-vlm==$MLX_VLM_PIN")
else
  echo "[firstrun] WARN: build.mlx_*_pin missing from harness.yaml — installing mlx unpinned"
  MLX_PKGS=(mlx-lm mlx-vlm)
fi
MLOG="$LOGDIR/firstrun_mlx.log"; : >"$MLOG"
mkvenv data/mlx-venv mlx "$MLOG"
pipi data/mlx-venv mlx "$MLOG" "${MLX_PKGS[@]}"

# ---------- 8. llama-server (already bundled in the seed) ----------
LS="$DEST/data/llamacpp/build/bin/llama-server"
[[ -x "$LS" ]] || chmod +x "$LS" 2>/dev/null || true
[[ -f "$LS" ]] || say "WARN: bundled llama-server missing at $LS — the GGUF runner won't start until scripts/install_llamacpp.sh is run (needs internet)."

# ---------- 9. seed the model registry (empty on a fresh Mac — models download later) ----------
( "$DEST/data/bridge-venv/bin/python" scripts/seed_registry.py ) >>"$LOGDIR/firstrun_registry.log" 2>&1 || \
  say "note: registry seed produced no models yet (expected on a fresh Mac — download models from the Models pane)."

# ---------- 10. done. Bridge is started by main.swift (ensureBridgeThenLoad); §E starts components. ----------
touch "$DEST/.provisioned"
say "Offline provision complete. Components installed (stopped). Mission Control will open; the setup checklist starts them."
