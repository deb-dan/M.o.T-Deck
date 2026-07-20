#!/usr/bin/env bash
# Install a component natively: ./scripts/install_component.sh hermes|odysseus [--yes]
# Shows the plan first; --yes skips the prompt (used by the panel after UI approval).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="${1:-}"; YES="${2:-}"
[[ "$NAME" == "hermes" || "$NAME" == "odysseus" ]] || { echo "usage: $0 hermes|odysseus [--yes]"; exit 1; }
[[ -e "vendor/$NAME/.git" ]] || { echo "vendor/$NAME missing — run bootstrap.sh first"; exit 1; }

plan_hermes="PLAN (hermes):
  - create venv data/hermes-venv (isolated; vendor/ stays pristine)
  - pip install -e vendor/hermes[all]  (~ a few hundred MB of deps)
  - write hermes config pointing its provider at the gearbox endpoint
  - expose MCP server on port 8721 when started"

plan_odysseus="PLAN (odysseus):
  - create venv data/odysseus-venv
  - pip install -r vendor/odysseus/requirements.txt (+ optional ddgs for web search)
  - run its setup.py (creates admin account, prints temp password)
  - serve natively on port 7860 when started (Metal-accelerated Cookbook)"

var="plan_$NAME"; echo "${!var}"
if [[ "$YES" != "--yes" ]]; then
  read -r -p "Proceed? [y/N] " reply
  [[ "$reply" =~ ^[Yy] ]] || { echo "Aborted — nothing was changed."; exit 1; }
fi

PY=$(command -v python3.12 || command -v python3.11 || command -v python3)

if [[ "$NAME" == "hermes" ]]; then
  uv venv "data/hermes-venv" --python "$PY" 2>/dev/null || true
  # shellcheck disable=SC1091
  source data/hermes-venv/bin/activate
  uv pip install -e "vendor/hermes[all]" || uv pip install -e "vendor/hermes"
  deactivate
else
  uv venv "data/odysseus-venv" --python "$PY" 2>/dev/null || true
  # shellcheck disable=SC1091
  source data/odysseus-venv/bin/activate
  uv pip install -r vendor/odysseus/requirements.txt
  uv pip install ddgs || true          # Docker-free web search provider
  ( cd vendor/odysseus && python setup.py )
  deactivate
fi

# flip installed: true in harness.yaml
python3 - "$NAME" <<'EOF'
import re, sys
name = sys.argv[1]
p = "harness.yaml"; s = open(p).read()
block = re.compile(rf"(  {name}:\n(?:    .*\n)*?    installed: )false")
open(p, "w").write(block.sub(r"\1true", s))
EOF

echo "[harness] $NAME installed. Start it from the panel or scripts/start_component.sh $NAME"
