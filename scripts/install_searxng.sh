#!/usr/bin/env bash
# Native SearXNG install (no Docker) for macOS/arm64. Source-only (not on PyPI).
# Serves a private meta-search on 127.0.0.1:8080 with the JSON API enabled so
# Odysseus DeepResearch + the agent web_search tool can consume it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

command -v uv >/dev/null || { echo "uv not found — run scripts/bootstrap.sh first"; exit 1; }
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)

# 1. Source clone (SearXNG is not on PyPI).
if [[ ! -d vendor/searxng/.git ]]; then
  echo "[harness] cloning searxng (shallow)..."
  git clone --depth 1 https://github.com/searxng/searxng vendor/searxng
else
  echo "[harness] vendor/searxng already present."
fi

# 2. venv + build deps + editable install (this compiles some C deps — can take a few minutes).
echo "[harness] creating venv + installing searxng (compiles deps; be patient)..."
uv venv data/searxng-venv --python "$PY" 2>/dev/null || true
# shellcheck disable=SC1091
source data/searxng-venv/bin/activate
uv pip install -U pip setuptools wheel
uv pip install -U pyyaml msgspec typing-extensions pybind11   # build prereqs first
uv pip install --use-pep517 --no-build-isolation -e vendor/searxng
deactivate

# 3. settings.yml — merge over SearXNG defaults; localhost-only, no Redis (limiter off),
#    JSON format enabled for API consumers.
mkdir -p data/searxng
SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
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

echo "[harness] searxng installed."
echo "[harness] settings: $ROOT/data/searxng/settings.yml"
echo "[harness] test-run it with:"
echo "  SEARXNG_SETTINGS_PATH=$ROOT/data/searxng/settings.yml $ROOT/data/searxng-venv/bin/python -m searx.webapp"
