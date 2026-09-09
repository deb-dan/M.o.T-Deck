#!/usr/bin/env bash
# Install MOT Deck's OWN pinned llama-server (llama.cpp) binary into data/llamacpp/.
# Replaces borrowing Jan's / LM Studio's backends — determinism + pin+bump control.
#
# Reads runner.llamacpp_pin + runner.llamacpp_sha256 from motdeck.yaml, downloads the
# macOS arm64 release archive from ggml-org/llama.cpp, and lands llama-server at
#   data/llamacpp/build/bin/llama-server
# (the canonical path the shared binary-discovery order looks for).
#
# VERIFIED 2026-07-23 from the release page HTML (sandbox): the macOS arm64 asset is
#   llama-<TAG>-bin-macos-arm64.tar.gz   (a .tar.gz — NOT the .zip the first spec drafted)
# and assets can lag a freshly-cut tag by a few hours (b10103 had none yet; b10094 did),
# so the default pin is the newest tag CONFIRMED to carry the macos-arm64 asset.
# ⚠️ The archive's INTERNAL layout could not be verified from the sandbox (the release
# CDN, objects.githubusercontent.com, is network-blocked here). This script therefore
# does not assume the layout: it extracts to a staging dir, FINDS llama-server anywhere
# inside, and relocates that whole dir (binary + its .dylibs) to build/bin/. If nothing
# is found it fails loudly, printing the exact URL it fetched and the staging contents.
set -euo pipefail
cd "$(dirname "$0")/.."

PIN=$(awk '/^runner:/{f=1} f && /^  llamacpp_pin:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*llamacpp_pin:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' motdeck.yaml)
[[ -n "$PIN" ]] || { echo "ERROR: runner.llamacpp_pin not set in motdeck.yaml"; exit 1; }
SHA256=$(awk '/^runner:/{f=1} f && /^  llamacpp_sha256:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*llamacpp_sha256:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' motdeck.yaml)
[[ "$SHA256" =~ ^[0-9a-f]{64}$ ]] || {
  echo "ERROR: runner.llamacpp_sha256 must be a recorded 64-character digest"; exit 1; }

DEST="${LLAMACPP_DEST:-data/llamacpp}"
BINPATH="$DEST/build/bin/llama-server"
ASSET="llama-${PIN}-bin-macos-arm64.tar.gz"
URL="https://github.com/ggml-org/llama.cpp/releases/download/${PIN}/${ASSET}"

echo "[motdeck] installing llama.cpp pin ${PIN}"
echo "[motdeck]   asset : ${ASSET}"
echo "[motdeck]   url   : ${URL}"

mkdir -p "$DEST"
STAGE="$DEST/.staging"
rm -rf "$STAGE"; mkdir -p "$STAGE"
TARBALL="$DEST/.download.tar.gz"
rm -f "$TARBALL"

if ! curl -fL --retry 3 -m 600 -o "$TARBALL" "$URL"; then
  echo "ERROR: download failed."
  echo "  tried: $URL"
  echo "  Check the tag exists AND has macOS binaries uploaded (CI can lag a few hours):"
  echo "    https://github.com/ggml-org/llama.cpp/releases/tag/${PIN}"
  rm -f "$TARBALL"; exit 1
fi

GOT_SHA256=$(shasum -a 256 "$TARBALL" | awk '{print $1}')
if [[ "$GOT_SHA256" != "$SHA256" ]]; then
  echo "ERROR: llama.cpp sha256 MISMATCH for ${ASSET}"
  echo "  expected: $SHA256"
  echo "  got     : $GOT_SHA256"
  rm -rf "$STAGE" "$TARBALL"
  exit 1
fi
echo "[motdeck] sha256 verified: ${SHA256}"

echo "[motdeck] extracting…"
if ! tar xzf "$TARBALL" -C "$STAGE"; then
  echo "ERROR: extraction failed — archive may not be a gzip tar. Downloaded from:"
  echo "  $URL"
  # 2026-08-29 install-path audit: clean up the corrupt tarball + staging debris, so a
  # re-run starts from a fresh download instead of re-failing on the same bad bytes.
  rm -rf "$STAGE" "$TARBALL"
  exit 1
fi

SRV=$(find "$STAGE" -type f -name llama-server 2>/dev/null | head -1)
if [[ -z "$SRV" ]]; then
  echo "ERROR: no 'llama-server' binary found inside the archive from:"
  echo "  $URL"
  echo "  Extracted contents:"
  find "$STAGE" -maxdepth 3 -print | sed 's/^/    /' | head -40
  echo "  (If the asset name/layout changed upstream, update this script or set runner.binary.)"
  exit 1
fi

SRVDIR=$(dirname "$SRV")
# Relocate the binary + its colocated .dylibs to the canonical build/bin/ path,
# regardless of the archive's internal prefix (build/bin, bin, flat, …).
rm -rf "$DEST/build"
mkdir -p "$DEST/build/bin"
# Move every sibling of llama-server (shared libs live next to it).
( shopt -s dotglob; mv "$SRVDIR"/* "$DEST/build/bin/" )
rm -rf "$STAGE" "$TARBALL"

[[ -f "$BINPATH" ]] || { echo "ERROR: relocation failed — $BINPATH missing after install"; exit 1; }
chmod +x "$BINPATH"

echo "[motdeck] installed: $BINPATH"
# Print the version if the binary supports it (loads no model; cheap). Fall back to pin.
if "$BINPATH" --version >/tmp/llama-ver.txt 2>&1; then
  sed 's/^/[motdeck]   /' /tmp/llama-ver.txt | head -4
else
  echo "[motdeck]   version flag unsupported by this build — pinned tag: ${PIN}"
fi
rm -f /tmp/llama-ver.txt
echo "[motdeck] done — runner will auto-discover this binary (pin has priority over Jan/LM Studio)."
