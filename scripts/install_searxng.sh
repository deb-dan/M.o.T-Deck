#!/usr/bin/env bash
# Native SearXNG install (no Docker) for macOS/arm64. Source-only (not on PyPI).
# Serves a private meta-search on 127.0.0.1:8080 with the JSON API enabled so
# Odysseus DeepResearch + the agent web_search tool can consume it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

_yc() { awk -v k="    $1:" '/^  searxng:/{f=1;next} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[\",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^  [a-z]/{exit}' motdeck.yaml; }
REPO="$(_yc repo)"
PIN="$(_yc pin)"
[[ "$PIN" =~ ^[0-9a-f]{40}$ ]] || {
  echo "ERROR: components.searxng.pin must be an exact 40-character commit SHA"; exit 1; }
[[ "$REPO" == https://github.com/searxng/searxng.git ]] || {
  echo "ERROR: unexpected components.searxng.repo: ${REPO:-missing}"; exit 1; }

command -v uv >/dev/null || { echo "uv not found — run scripts/bootstrap.sh first"; exit 1; }
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)

# 1. Source checkout (SearXNG is not on PyPI). Fetch the exact object; a shallow
# default-branch clone is not a pin and was the A11 defect.
if [[ -e vendor/searxng && ! -d vendor/searxng/.git ]]; then
  echo "ERROR: vendor/searxng exists but is not a git checkout; refusing to modify it"
  exit 1
elif [[ ! -d vendor/searxng/.git ]]; then
  echo "[motdeck] fetching searxng @ ${PIN:0:12}..."
  mkdir -p vendor/searxng
  git -C vendor/searxng init -q
  git -C vendor/searxng remote add origin "$REPO"
  if git -C vendor/searxng fetch --depth 1 origin "$PIN"; then
    git -C vendor/searxng checkout -q --detach FETCH_HEAD
  else
    echo "[motdeck] exact shallow fetch refused — fetching full history in place..."
    git -C vendor/searxng fetch origin
    git -C vendor/searxng checkout -q --detach "$PIN"
  fi
else
  ORIGIN=$(git -C vendor/searxng remote get-url origin 2>/dev/null || true)
  [[ "$ORIGIN" == "$REPO" || "$ORIGIN" == "${REPO%.git}" ]] || {
    echo "ERROR: vendor/searxng origin is ${ORIGIN:-missing}, expected $REPO"; exit 1; }
  HAVE=$(git -C vendor/searxng rev-parse HEAD)
  if [[ "$HAVE" != "$PIN" ]]; then
    echo "[motdeck] searxng is at ${HAVE:0:12}; moving to ${PIN:0:12}..."
    git -C vendor/searxng fetch --depth 1 origin "$PIN"
    git -C vendor/searxng checkout -q --detach FETCH_HEAD
  else
    echo "[motdeck] vendor/searxng already at the pin."
  fi
fi
HAVE=$(git -C vendor/searxng rev-parse HEAD)
[[ "$HAVE" == "$PIN" ]] || {
  echo "ERROR: searxng checkout is ${HAVE}, expected ${PIN}"; exit 1; }

# 2. venv + build deps + editable install (this compiles some C deps — can take a few minutes).
echo "[motdeck] creating venv + installing searxng (compiles deps; be patient)..."
uv venv data/searxng-venv --python "$PY" 2>/dev/null || true
# shellcheck disable=SC1091
source data/searxng-venv/bin/activate
uv pip install -U pip setuptools wheel
uv pip install -U pyyaml msgspec typing-extensions pybind11   # build prereqs first
# --use-pep517 is a real-pip flag (uv pip doesn't accept it) — use the venv's pip here.
"$ROOT/data/searxng-venv/bin/pip" install --use-pep517 --no-build-isolation -e vendor/searxng
deactivate

# 3. settings.yml — merge over SearXNG defaults; localhost-only, no Redis (limiter off),
#    JSON format enabled for API consumers.
mkdir -p data/searxng
if [[ ! -e data/searxng/settings.yml && ! -L data/searxng/settings.yml ]]; then
SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
# Exclusive creation also preserves settings written by another setup invocation.
( set -o noclobber; cat > data/searxng/settings.yml <<EOF
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
) || { echo "ERROR: could not create SearXNG settings; existing state was preserved"; exit 1; }
fi

# Mission Control reads components.searxng.installed from motdeck.yaml, never the disk
# (bridge/app.py::status). This installer is standalone — it is NOT a branch of
# install_component.sh, whose tail has flipped that flag since M0 — so it has to do it
# itself. Latent until now only because motdeck.yaml already ships searxng as
# installed: true; on a fresh manifest (ship.sh forces a NEW component to false) the
# card would have stayed "Not installed" exactly like OpenCode's did.
"$PY" "$ROOT/scripts/flip_installed.py" searxng || {
  echo "[motdeck] ERROR: searxng installed on disk but motdeck.yaml flag could not"
  echo "[motdeck]   be set — its card will still say 'Not installed'. Fix with:"
  echo "[motdeck]   python3 scripts/flip_installed.py searxng"
  exit 1; }

echo "[motdeck] searxng installed."
echo "[motdeck] settings: $ROOT/data/searxng/settings.yml"
echo "[motdeck] test-run it with:"
echo "  SEARXNG_SETTINGS_PATH=$ROOT/data/searxng/settings.yml $ROOT/data/searxng-venv/bin/python -m searx.webapp"
