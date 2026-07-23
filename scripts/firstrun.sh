#!/usr/bin/env bash
# Harness portable first-run. Run from the extracted ~/Harness (main.swift does this
# on a fresh Mac). Checks prerequisites with actionable messages, installs uv if needed,
# then hands off to bootstrap.sh (which git-inits, adds the pinned public submodules, and
# builds the bridge venv). The §E setup checklist in the panel guides per-component installs.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

say()  { printf "\033[1;36m[firstrun]\033[0m %s\n" "$*"; }
fail() { printf "\033[1;31m[firstrun]\033[0m %s\n" "$*" >&2; exit 1; }

say "Harness first-run in: $ROOT"

# ---------- prerequisites (actionable failures) ----------
command -v git  >/dev/null || fail "git not found — install Xcode Command Line Tools:  xcode-select --install"
command -v brew >/dev/null || fail "Homebrew not found — install it from https://brew.sh then reopen Harness. (bootstrap uses brew to add any missing tools.)"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null; then
    "$c" -c 'import sys; exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null && { PY="$c"; break; }
  fi
done
[[ -z "$PY" ]] && say "Python 3.11+ not found — bootstrap will offer 'brew install python@3.12'."
command -v node >/dev/null || say "Node.js not found — Hermes's dashboard build needs it later ('brew install node')."

# ---------- uv (bootstrap uses it for venvs) ----------
if ! command -v uv >/dev/null; then
  say "Installing uv (astral.sh)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh || fail "uv install failed — see https://astral.sh/uv"
  export PATH="$HOME/.local/bin:$PATH"
fi

# ---------- git identity fallback (fresh Macs often have none; bootstrap commits) ----------
if ! git config --get user.email >/dev/null 2>&1; then
  say "No git identity configured — using a local fallback for the initial commit."
  export GIT_AUTHOR_NAME="Harness" GIT_AUTHOR_EMAIL="harness@localhost"
  export GIT_COMMITTER_NAME="Harness" GIT_COMMITTER_EMAIL="harness@localhost"
fi

say "Handing off to bootstrap…"
exec bash ./scripts/bootstrap.sh --yes
