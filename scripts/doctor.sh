#!/usr/bin/env bash
# Diagnose MOT Deck: prereqs, pins, ports, component health.
set -uo pipefail
cd "$(dirname "$0")/.."

ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$*"; }

echo "== prerequisites =="
for c in git tmux uv; do command -v $c >/dev/null && ok "$c" || bad "$c missing"; done
python3 -c 'import sys; exit(0 if sys.version_info>=(3,11) else 1)' \
  && ok "python $(python3 -V 2>&1)" || bad "python 3.11+ required"

echo "== pins =="
for name in hermes odysseus; do
  if [[ -e "vendor/$name/.git" ]]; then
    ok "$name @ $(git -C vendor/$name rev-parse --short HEAD) ($(git -C vendor/$name describe --tags --always 2>/dev/null))"
  else
    bad "$name not installed (vendor/$name empty)"
  fi
done

echo "== ports =="
for p in 8700 8710 7860 8721 11434 1234; do
  if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then ok "port $p in use"; else echo "  - port $p free"; fi
done

echo "== bridge =="
curl -sf "http://127.0.0.1:8700/api/status" >/dev/null && ok "bridge responding" || bad "bridge not running (./scripts/start.sh)"
