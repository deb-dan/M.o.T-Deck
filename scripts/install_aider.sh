#!/usr/bin/env bash
# Install AIDER — the harness's coding agent, run in a PTY tab.
#
#   ./scripts/install_aider.sh
#
# aider is NOT a component: no port, no manifest card, no daemon. It is a terminal
# program the bridge starts inside a pseudo-terminal while the Aider tab is open.
# So this is a standalone installer in the shape of install_music.sh, not a branch of
# install_component.sh.
#
#   vendor/aider        shallow clone at build.aider_pin (a COMMIT on main — see below)
#   data/aider-venv     its own venv, editable install (~350-450MB, no torch)
#   data/logs/aider-install.log
#
# ONLINE-ONLY (litellm + tree-sitter grammars + scipy resolve from PyPI). Idempotent:
# every step checks first, so a re-run after a failed download resumes.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

VENV="$ROOT/data/aider-venv"
SRC="$ROOT/vendor/aider"
REPO="https://github.com/Aider-AI/aider.git"
LOG="$ROOT/data/logs/aider-install.log"

mkdir -p "$ROOT/data/logs"
# Everything lands in the panel-viewable install log AS WELL AS stdout (the bridge
# captures stdout for the endpoint's reply). The voicebox lesson: a slow, fragile
# install must be readable without a terminal.
exec > >(tee -a "$LOG") 2>&1
echo "──────── install_aider.sh · $(date '+%Y-%m-%d %H:%M:%S') ────────"

say() { echo "[aider] $*"; }
die() { echo "[aider] ERROR: $*" >&2; exit 1; }

# ── pin reader (same awk shape as install_music.sh: comments live ABOVE keys) ──
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }

# ── explicit-path resolution (the Finder-minimal-PATH standing rule) ──────────
resolve_py() {
  local p
  for p in "$ROOT/data/python-standalone/bin/python3" \
           "$(command -v python3.12 || true)" \
           "$(command -v python3.13 || true)" \
           "$(command -v python3.11 || true)" \
           "$(command -v python3 || true)"; do
    [[ -n "$p" && -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

resolve_uv() {
  local u
  for u in "$(command -v uv || true)" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv \
           /usr/local/bin/uv "$HOME/.cargo/bin/uv"; do
    [[ -n "$u" && -x "$u" ]] && { echo "$u"; return 0; }
  done
  return 0   # not an error — every caller has a non-uv fallback
}

ensure_venv() {
  local py uv minor
  py="$(resolve_py)" || die "no python3 found — brew install python@3.12"
  uv="$(resolve_uv)"
  minor=$("$py" -c 'import sys; print(sys.version_info[1])')
  say "interpreter: $py (3.${minor})"
  # upstream pyproject: requires-python = ">=3.10,<3.15"
  if [[ "$minor" -lt 10 || "$minor" -gt 14 ]]; then
    die "aider asks for Python 3.10-3.14; this is 3.${minor}."
  fi
  if [[ ! -x "$VENV/bin/python" ]]; then
    if [[ -n "$uv" ]] && "$uv" venv --python "$py" --seed "$VENV" >/dev/null 2>&1; then
      say "venv created with uv (--seed)."
    elif "$py" -m venv "$VENV" >/dev/null 2>&1; then
      say "venv created with $py -m venv."
    elif "$py" -m venv --without-pip "$VENV" >/dev/null 2>&1; then
      say "venv created without pip (bootstrapping pip)."
    else
      rm -rf "$VENV"
      die "could not create $VENV — install uv, or brew reinstall python@3.12."
    fi
  fi
  # A uv-seeded or --without-pip venv can have the pip MODULE without a bin/pip SCRIPT.
  # Every call below goes through `python -m pip`, never bin/pip (the voicebox lesson).
  if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
      say "pip bootstrapped via ensurepip."
    elif [[ -n "$uv" ]] && "$uv" pip install --python "$VENV/bin/python" pip >/dev/null 2>&1; then
      say "pip bootstrapped via uv."
    else
      die "$VENV has no usable pip. Install uv and re-run."
    fi
  fi
}

# ── the pinned clone ─────────────────────────────────────────────────────────
# The pin is a COMMIT on main, not a tag: the last tag (v0.86.0) predates the Feb-2026
# dependency refresh (openai 2.x / litellm 1.82) that a current OpenAI-compatible
# endpoint wants. A bare-commit pin is native here — odysseus is pinned the same way.
clone_pinned() {
  command -v git >/dev/null 2>&1 || die "git not found — xcode-select --install"
  local sha
  sha="$(_yb aider_pin)"
  [[ -n "$sha" ]] || die "build.aider_pin missing from harness.yaml"
  say "pin: Aider-AI/aider @ ${sha:0:12}"

  if [[ ! -d "$SRC/.git" ]]; then
    say "fetching aider at the pinned commit (shallow)…"
    # Fetch the exact SHA, never a branch head — a branch would silently move the thing
    # we pinned. If GitHub ever refuses a direct sha fetch, fall back to a full clone.
    mkdir -p "$SRC"
    git -C "$SRC" init -q
    git -C "$SRC" remote add origin "$REPO" 2>/dev/null || true
    if git -C "$SRC" fetch --depth 1 origin "$sha" >/dev/null 2>&1; then
      git -C "$SRC" checkout -q FETCH_HEAD
    else
      say "shallow fetch-by-sha refused — falling back to a full clone…"
      rm -rf "$SRC"
      git clone -q "$REPO" "$SRC" || die "clone failed"
      git -C "$SRC" checkout -q "$sha" || die "commit $sha not found in the clone"
    fi
  else
    local have
    have=$(git -C "$SRC" rev-parse HEAD)
    if [[ "$have" != "$sha" ]]; then
      say "clone is at ${have:0:12}, pin is ${sha:0:12} — moving it…"
      git -C "$SRC" fetch --depth 1 origin "$sha" >/dev/null 2>&1 \
        || git -C "$SRC" fetch origin >/dev/null 2>&1 \
        || die "could not fetch $sha"
      git -C "$SRC" checkout -q "$sha" || git -C "$SRC" checkout -q FETCH_HEAD \
        || die "could not check out $sha"
    else
      say "clone already at the pin."
    fi
  fi
  [[ -f "$SRC/pyproject.toml" ]] || die "no pyproject.toml in $SRC — the repo layout changed."
}

main() {
  [[ "$(uname -s)" == "Darwin" ]] || say "WARN: only tested on macOS."
  local free_gb
  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (aider's venv is roughly 0.5GB)"
  [[ "$free_gb" -ge 2 ]] || die "not enough free disk — need about 2GB, have ${free_gb}GB."

  clone_pinned
  ensure_venv

  say "installing aider (editable) — ONLINE; litellm + tree-sitter grammars are big…"
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q -e "$SRC" \
    || die "pip install failed — see the output above"

  [[ -x "$VENV/bin/aider" ]] || die "no $VENV/bin/aider after the install — see above"

  # Prove the entry point actually runs before claiming success: an import error inside
  # litellm here is a tab that opens onto a traceback.
  say "verifying the entry point…"
  "$VENV/bin/aider" --version >/dev/null 2>&1 \
    || die "aider is installed but does not run — see $LOG"

  mkdir -p "$ROOT/data/aider-workspace"
  echo ""
  say "installed: $("$VENV/bin/aider" --version 2>/dev/null | head -1)"
  say "workspace: data/aider-workspace (the ONLY dir aider is started in — it is the"
  say "  security boundary; the Hermes path-guard does not cover aider)."
}

main "$@"
