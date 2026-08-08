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
# Resolution order — the user's own uv always wins, and nothing is downloaded until
# every known location has been checked. The explicit path list is the same one
# install_component.sh uses for VB_UV: a Finder-launched app gets a MINIMAL PATH, so
# `command -v uv` alone misses a perfectly good uv in ~/.local/bin (its own default
# install location). That single miss already cost us one failed voicebox install.
UV_DIR="$ROOT/data/uv/bin"
UV_BIN=""
for _u in "$(command -v uv || true)" "$UV_DIR/uv" "$HOME/.local/bin/uv" \
          /opt/homebrew/bin/uv /usr/local/bin/uv "$HOME/.cargo/bin/uv"; do
  [[ -n "$_u" && -x "$_u" ]] && { UV_BIN="$_u"; break; }
done

if [[ -n "$UV_BIN" ]]; then
  say "uv: $UV_BIN ($("$UV_BIN" --version 2>/dev/null || echo 'version?'))"
else
  # PINNED install. The version-in-the-URL form is documented by upstream
  # (docs.astral.sh/uv/getting-started/installation → "Request a specific version"),
  # and UV_UNMANAGED_INSTALL=<dir> is the documented way to (a) choose the install
  # directory, (b) stop the installer editing shell profiles and (c) disable
  # self-update — exactly the no-writes-outside-our-tree rule ensure_bun.sh follows.
  # Pin lives in harness.yaml build.uv_pin; same awk reader as ensure_bun.sh.
  _yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }
  UV_PIN="${UV_PIN:-$(_yb uv_pin)}"
  if [[ -n "$UV_PIN" ]]; then
    UV_URL="https://astral.sh/uv/${UV_PIN}/install.sh"
    say "Installing uv ${UV_PIN} → ${UV_DIR} (nothing is written outside this folder)…"
  else
    # A missing pin must not brick a fresh Mac: warn loudly, install latest.
    UV_URL="https://astral.sh/uv/install.sh"
    say "WARN: build.uv_pin missing from harness.yaml — installing the LATEST uv (unpinned)."
  fi
  mkdir -p "$UV_DIR"
  curl -LsSf "$UV_URL" | env UV_UNMANAGED_INSTALL="$UV_DIR" sh \
    || fail "uv install failed — tried: $UV_URL  (see https://astral.sh/uv)"
  UV_BIN="$UV_DIR/uv"
  [[ -x "$UV_BIN" ]] || fail "uv installed but $UV_BIN is not executable — tried: $UV_URL"
  say "$("$UV_BIN" --version 2>/dev/null || echo 'uv ?') installed → $UV_BIN"
fi
# bootstrap.sh calls `uv` by name.
export PATH="$(dirname "$UV_BIN"):$PATH"

# ---------- git identity fallback (fresh Macs often have none; bootstrap commits) ----------
if ! git config --get user.email >/dev/null 2>&1; then
  say "No git identity configured — using a local fallback for the initial commit."
  export GIT_AUTHOR_NAME="Harness" GIT_AUTHOR_EMAIL="harness@localhost"
  export GIT_COMMITTER_NAME="Harness" GIT_COMMITTER_EMAIL="harness@localhost"
fi

say "Handing off to bootstrap…"
exec bash ./scripts/bootstrap.sh --yes
