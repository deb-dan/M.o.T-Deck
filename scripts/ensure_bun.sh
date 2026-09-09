#!/usr/bin/env bash
# Make a usable `bun` available WITHOUT Homebrew, WITHOUT sudo and WITHOUT writing
# anything outside the project tree. Bun is a BUILD-TIME-ONLY tool: the two optional
# voice components (voicestudio, voicebox) ship Vite SPAs that must be compiled once.
#
# CONTRACT (this is why the script is so quiet):
#   • the resolved bun path is the ONLY thing printed on STDOUT
#   • every human-readable line goes to STDERR
#   • a failure is NON-FATAL by design — it exits non-zero after printing the exact
#     URL it tried, and the caller is expected to swallow that:
#         BUN="$(bash scripts/ensure_bun.sh || true)"
#         [[ -n "$BUN" ]] && … build the SPA … || echo "WARN: no UI built"
#     (the `|| true` matters: without it, `set -e` in the caller would abort the
#      whole component install just because an optional web UI could not be built)
#
# Resolution order — the user's own tools always win:
#   (a) a `bun` already on PATH            → use it, never shadow it
#   (b) data/bun/bin/bun we provisioned    → reuse it (re-provisioned if the pin moved)
#   (c) download the PINNED release        → data/bun/bin/bun
#
# The pin lives in motdeck.yaml under build.bun_pin (single source of truth, same
# idiom as build.mlx_lm_pin / runner.llamacpp_pin). Bump = edit motdeck.yaml, re-run
# an install of the component; this script notices the version drift and refetches.
#
# Mirrors scripts/install_llamacpp.sh: staging dir → find the binary anywhere inside
# the archive → relocate → chmod → verify → loud failure printing the exact URL.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
say() { echo "[motdeck] $*" >&2; }

DEST="${BUN_DEST:-$ROOT/data/bun}"
BINPATH="$DEST/bin/bun"

# ── (a) the user's own bun ────────────────────────────────────────────────────
# Checked BEFORE the pin is read: if the user already has bun, a missing pin is
# irrelevant and must not turn into an error.
if [[ "${BUN_IGNORE_PATH:-0}" != "1" ]] && command -v bun >/dev/null 2>&1; then
  say "bun found on PATH: $(command -v bun) ($(bun --version 2>/dev/null || echo 'version?')) — using it, not shadowing it"
  command -v bun
  exit 0
fi

# Pin from motdeck.yaml build.bun_pin (e.g. "bun-v1.3.14"). Same awk reader as
# install_mlx.sh so there is exactly one way to read a build.* key.
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' motdeck.yaml; }
PIN="${BUN_PIN:-$(_yb bun_pin)}"
[[ -n "$PIN" ]] || {
  say "ERROR: build.bun_pin missing from $(pwd)/motdeck.yaml"
  say "  (if this is the FAT app's snapshot: ship.sh deliberately never overwrites"
  say "   motdeck.yaml, so a newly added build.* key only arrives with a --fat rebuild."
  say "   Add 'bun_pin: \"bun-v…\"' under build:, or export BUN_PIN=bun-v… and re-run.)"
  exit 1; }
# "bun-v1.3.14" → "1.3.14" (what `bun --version` prints)
PIN_VER="${PIN#bun-v}"

# ── (b) a bun we provisioned earlier ──────────────────────────────────────────
if [[ -x "$BINPATH" ]]; then
  HAVE="$("$BINPATH" --version 2>/dev/null || true)"
  if [[ -n "$HAVE" ]]; then
    if [[ "$HAVE" == "$PIN_VER" ]]; then
      say "bun already provisioned: $BINPATH ($HAVE)"
      echo "$BINPATH"
      exit 0
    fi
    say "provisioned bun is $HAVE but the pin is $PIN_VER — refetching"
  else
    say "provisioned bun at $BINPATH does not run — refetching"
  fi
fi

# ── (c) download the pinned release ───────────────────────────────────────────
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Darwin/arm64)          ASSET="bun-darwin-aarch64.zip"; SHA256="$(_yb bun_darwin_arm64_sha256)" ;;
  Darwin/x86_64)         ASSET="bun-darwin-x64.zip"; SHA256="$(_yb bun_darwin_x64_sha256)" ;;
  Linux/aarch64|Linux/arm64) ASSET="bun-linux-aarch64.zip"; SHA256="$(_yb bun_linux_arm64_sha256)" ;;
  Linux/x86_64)          ASSET="bun-linux-x64.zip"; SHA256="$(_yb bun_linux_x64_sha256)" ;;
  *)
    say "ERROR: no pinned bun asset for $OS/$ARCH."
    say "  The component still installs; its web UI just won't be built."
    say "  Install bun yourself if you want the UI: https://bun.sh"
    exit 1 ;;
esac
[[ "$SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  say "ERROR: no recorded SHA-256 for ${PIN}/${ASSET}."
  say "  A pin bump must record every supported platform asset before use."
  exit 1; }
URL="https://github.com/oven-sh/bun/releases/download/${PIN}/${ASSET}"

command -v unzip >/dev/null 2>&1 || {
  say "ERROR: 'unzip' not found — cannot unpack the bun release."
  say "  (unzip ships with macOS; on Linux: apt-get install unzip)"
  exit 1; }

say "provisioning bun ${PIN} (${ASSET}) — build-time only, stays inside data/"
say "  url : $URL"
mkdir -p "$DEST"
STAGE="$DEST/.staging"
rm -rf "$STAGE"; mkdir -p "$STAGE"
ZIPF="$DEST/.download.zip"
rm -f "$ZIPF"

if ! curl -fL --retry 3 -m 600 -o "$ZIPF" "$URL"; then
  say "ERROR: bun download failed."
  say "  tried: $URL"
  say "  Check the tag exists AND carries that asset (CI can lag a fresh tag):"
  say "    https://github.com/oven-sh/bun/releases/tag/${PIN}"
  say "  This is NOT fatal — the component installs anyway, only its web UI is skipped."
  rm -rf "$STAGE"; rm -f "$ZIPF"; exit 1
fi

GOT_SHA256=$(shasum -a 256 "$ZIPF" | awk '{print $1}')
if [[ "$GOT_SHA256" != "$SHA256" ]]; then
  say "ERROR: bun sha256 MISMATCH for ${PIN}/${ASSET}."
  say "  expected: $SHA256"
  say "  got     : $GOT_SHA256"
  rm -rf "$STAGE" "$ZIPF"
  exit 1
fi
say "sha256 verified: ${SHA256}"

if ! unzip -q -o "$ZIPF" -d "$STAGE"; then
  say "ERROR: could not unzip the bun archive downloaded from:"
  say "  $URL"
  rm -rf "$STAGE" "$ZIPF"; exit 1
fi

# Layout-agnostic (upstream ships bun-<platform>/bun today, but never assume it).
SRC="$(find "$STAGE" -type f -name bun 2>/dev/null | head -1)"
if [[ -z "$SRC" ]]; then
  say "ERROR: no 'bun' binary found inside the archive from:"
  say "  $URL"
  say "  Extracted contents:"
  find "$STAGE" -maxdepth 3 -print | sed 's/^/    /' | head -30 >&2
  rm -rf "$STAGE" "$ZIPF"; exit 1
fi

mkdir -p "$DEST/bin"
rm -f "$BINPATH"
mv "$SRC" "$BINPATH"
chmod +x "$BINPATH"
rm -rf "$STAGE" "$ZIPF"

GOT="$("$BINPATH" --version 2>/dev/null || true)"
if [[ -z "$GOT" ]]; then
  say "ERROR: $BINPATH was installed but does not run (quarantine? wrong arch?)."
  say "  Downloaded from: $URL"
  exit 1
fi
say "bun ${GOT} installed → $BINPATH"
echo "$BINPATH"
