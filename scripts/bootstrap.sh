#!/usr/bin/env bash
# MOT Deck bootstrap — macOS. Idempotent; safe to re-run.
# Sets up: prerequisites (with consent), git repo + pinned submodules, bridge venv.
set -euo pipefail
cd "$(dirname "$0")/.."
MOT_DECK_ROOT="$(pwd)"
YES=0; [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && YES=1

say()  { printf "\033[1;36m[motdeck]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[motdeck]\033[0m %s\n" "$*" >&2; exit 1; }

ask() { # ask "question" -> returns 0 on yes; --yes answers everything
  [[ $YES -eq 1 ]] && { say "$1 -> yes (--yes)"; return 0; }
  # drain any stray buffered input (e.g. multi-line pastes) so it can't answer prompts
  while read -r -t 0.1 -n 1000 _ 2>/dev/null; do :; done
  read -r -p "$1 [y/N] " reply </dev/tty
  [[ "$reply" =~ ^[Yy] ]]
}

# ---------- 0. disk space ----------
avail_gb=$(df -g . | awk 'NR==2 {print $4}')
if [[ "${avail_gb:-0}" -lt 5 ]]; then
  fail "Only ${avail_gb}GB free on this disk — need at least 5GB (repos + Python environments). Free up space and re-run."
fi
say "Disk: ${avail_gb}GB free — ok."

# ---------- 1. prerequisites ----------
say "Checking prerequisites..."
command -v brew >/dev/null || fail "Homebrew is required: https://brew.sh"

need_brew=()
command -v git  >/dev/null || need_brew+=(git)
command -v tmux >/dev/null || need_brew+=(tmux)      # Odysseus Cookbook needs it
command -v uv   >/dev/null || need_brew+=(uv)

# python 3.11+
PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null; then
    v=$("$cand" -c 'import sys; print(sys.version_info >= (3,11))')
    [[ "$v" == "True" ]] && PY="$cand" && break
  fi
done
[[ -z "$PY" ]] && need_brew+=(python@3.12)

if [[ ${#need_brew[@]} -gt 0 ]]; then
  say "Missing: ${need_brew[*]}"
  ask "Install via 'brew install ${need_brew[*]}'?" || fail "Cannot continue without prerequisites."
  brew install "${need_brew[@]}"
  [[ -z "$PY" ]] && PY=python3.12
fi
say "Using Python: $($PY --version)"

# ---------- 2. git repo + pinned submodules ----------
if [[ ! -d .git ]]; then
  say "Initializing git repository..."
  git init -b main
fi

pin_for() { # pin_for <component>  — reads motdeck.yaml (grep-based, no yq dependency)
  awk "/^  $1:/{f=1} f && /pin:/{print \$2; exit}" motdeck.yaml
}
repo_for() {
  awk "/^  $1:/{f=1} f && /repo:/{print \$2; exit}" motdeck.yaml
}

add_submodule() { # add_submodule <name>
  local name="$1" repo pin
  repo="$(repo_for "$name")"; pin="$(pin_for "$name")"
  if [[ ! -d "vendor/$name/.git" && ! -f "vendor/$name/.git" ]]; then
    say "Adding submodule $name @ $pin (shallow download — much smaller than a full clone)..."
    ask "Clone $repo into vendor/$name?" || { say "Skipped $name."; return 0; }
    git submodule add --depth 1 "$repo" "vendor/$name"
  fi
  git -C "vendor/$name" fetch --depth 1 --quiet origin "$pin"
  git -C "vendor/$name" checkout --quiet FETCH_HEAD
  say "vendor/$name pinned to $pin"
}

mkdir -p vendor data
add_submodule hermes
add_submodule odysseus

# ---------- 3. bridge venv ----------
say "Setting up bridge environment..."
if [[ ! -d data/bridge-venv ]]; then
  uv venv data/bridge-venv --python "$PY"
fi
# shellcheck disable=SC1091
source data/bridge-venv/bin/activate
uv pip install -q -r bridge/requirements.txt
deactivate
# Generate launch/admin credentials before any component installer can consume them.
# Values stay in data/.env.local (0600) and are never printed.
data/bridge-venv/bin/python scripts/local_secrets.py ensure "$MOT_DECK_ROOT" --fresh

# ---------- 4. first commit ----------
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git add -A
  git commit -q -m "motdeck: initial scaffold (hermes=$(pin_for hermes), odysseus=$(pin_for odysseus))"
  say "Initial commit created."
fi

say "Bootstrap complete. Next: ./scripts/start.sh then open http://127.0.0.1:8700"
