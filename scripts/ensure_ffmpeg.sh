#!/usr/bin/env bash
# Make a usable `ffmpeg` available WITHOUT Homebrew, WITHOUT sudo and WITHOUT writing
# anything outside the project tree. Used by the two optional voice components
# (transcription / audio conversion shell out to ffmpeg).
#
# CONTRACT — identical shape to scripts/ensure_bun.sh:
#   • the resolved ffmpeg path is the ONLY thing printed on STDOUT
#   • every human-readable line goes to STDERR
#   • failure is NON-FATAL by design; the caller swallows it:
#         FF="$(bash scripts/ensure_ffmpeg.sh "$VENV" || true)"
#     (the `|| true` matters: without it `set -e` would abort the whole install)
#
# Resolution order — the user's own tools always win:
#   (a) an `ffmpeg` already on PATH        → use it, never shadow it
#   (b) data/ffmpeg/bin/ffmpeg we provisioned earlier
#   (c) the `imageio-ffmpeg` wheel, installed into the CALLING COMPONENT'S venv
#
# WHY (c) AND NOT A PINNED STATIC-BUILD DOWNLOAD:
#   imageio-ffmpeg publishes per-platform wheels that CONTAIN a self-contained static
#   ffmpeg (macosx_11_0_arm64 wheel = 21.1 MB, BSD-2-Clause, verified on PyPI
#   2026-08-07) and exposes `imageio_ffmpeg.get_ffmpeg_exe()` to locate it. It is also
#   already a VoiceStudio dependency. That means: no new download infrastructure, no
#   URL to pin+bump, no unofficial "static builds" host to trust, and it rides the
#   same pip/uv path every other component dependency already uses. The binary is then
#   COPIED to data/ffmpeg/bin/ffmpeg so that (1) a rebuilt venv can never leave a
#   dangling reference and (2) start_component.sh has ONE canonical dir to prepend to
#   PATH at runtime.
#   ⚠️ HONEST LIMIT: imageio-ffmpeg bundles ffmpeg ONLY — there is no `ffprobe`. Any
#   upstream code path that shells out to ffprobe specifically will still fail unless
#   the user has a full ffmpeg install on PATH.
#
# usage: ensure_ffmpeg.sh [<venv-dir>]      (venv only needed to reach branch (c))
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
say() { echo "[motdeck] $*" >&2; }

VENV="${1:-}"
DEST="$ROOT/data/ffmpeg"
BINPATH="$DEST/bin/ffmpeg"

# ── (a) the user's own ffmpeg ─────────────────────────────────────────────────
# Checked BEFORE the pin is read: branches (a)/(b) need no pin at all, so a missing
# build.imageio_ffmpeg_pin must not turn an already-satisfied system into an error.
if command -v ffmpeg >/dev/null 2>&1; then
  say "ffmpeg found on PATH: $(command -v ffmpeg) — using it, not shadowing it"
  command -v ffmpeg
  exit 0
fi

# ── (b) one we provisioned earlier ────────────────────────────────────────────
if [[ -x "$BINPATH" ]] && "$BINPATH" -version >/dev/null 2>&1; then
  say "ffmpeg already provisioned: $BINPATH"
  echo "$BINPATH"
  exit 0
fi

# ── (c) provision from the imageio-ffmpeg wheel, into the caller's venv ───────
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' motdeck.yaml; }
PIN="${IMAGEIO_FFMPEG_PIN:-$(_yb imageio_ffmpeg_pin)}"
[[ -n "$PIN" ]] || {
  say "ERROR: build.imageio_ffmpeg_pin missing from $(pwd)/motdeck.yaml"
  say "  (if this is the FAT app's snapshot: ship.sh deliberately never overwrites"
  say "   motdeck.yaml, so a newly added build.* key only arrives with a --fat rebuild."
  say "   Add 'imageio_ffmpeg_pin: \"0.6.0\"' under build:, or export"
  say "   IMAGEIO_FFMPEG_PIN=0.6.0 and re-run.)"
  exit 1; }

if [[ -z "$VENV" ]]; then
  say "ERROR: no ffmpeg on PATH and no venv given — cannot provision."
  say "  usage: scripts/ensure_ffmpeg.sh <venv-dir>"
  exit 1
fi
VPY="$VENV/bin/python"
if [[ ! -x "$VPY" ]]; then
  say "ERROR: $VPY not executable — cannot provision ffmpeg into that venv."
  exit 1
fi

# Only install if the package is genuinely absent. VoiceStudio's venv is built from a
# uv LOCKFILE and already declares imageio-ffmpeg; installing on top of a --frozen env
# for no reason is exactly the kind of drift we avoid.
if ! "$VPY" -c 'import imageio_ffmpeg' >/dev/null 2>&1; then
  say "installing imageio-ffmpeg==${PIN} into $(basename "$VENV") (bundles a static ffmpeg, ~21MB)…"
  if ! "$VPY" -m pip install "imageio-ffmpeg==${PIN}" >&2; then
    say "ERROR: could not install imageio-ffmpeg==${PIN} (network? incompatible platform?)."
    say "  This is NOT fatal — the component installs anyway; audio conversion /"
    say "  transcription paths that shell out to ffmpeg will fail until one exists."
    exit 1
  fi
fi

SRC="$("$VPY" - <<'PY' 2>/dev/null || true
import sys
try:
    import imageio_ffmpeg
    sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    pass
PY
)"
if [[ -z "$SRC" || ! -f "$SRC" ]]; then
  say "ERROR: imageio_ffmpeg.get_ffmpeg_exe() did not resolve to a real file."
  say "  got: '${SRC:-<empty>}'"
  say "  (this wheel may be the source distribution, which bundles no binary)"
  exit 1
fi

mkdir -p "$DEST/bin"
# COPY (not symlink): rebuilding/deleting the venv must never leave a dangling ffmpeg.
cp -f "$SRC" "$BINPATH"
chmod +x "$BINPATH"
if ! "$BINPATH" -version >/dev/null 2>&1; then
  say "ERROR: $BINPATH was installed but does not run (quarantine? wrong arch?)."
  say "  copied from: $SRC"
  exit 1
fi
say "ffmpeg provisioned → $BINPATH   (from imageio-ffmpeg==${PIN}, BSD-2-Clause)"
say "  NOTE: this bundle has no 'ffprobe' — code paths needing ffprobe still want a full install."
echo "$BINPATH"
