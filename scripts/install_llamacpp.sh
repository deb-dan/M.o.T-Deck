#!/usr/bin/env bash
# Install the harness's OWN pinned llama-server (llama.cpp) binary into data/llamacpp/.
# Replaces borrowing Jan's / LM Studio's backends — determinism + pin+bump control.
#
# Reads runner.llamacpp_pin (a bNNNN release tag) from harness.yaml, downloads the
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

PIN=$(awk '/^runner:/{f=1} f && /^  llamacpp_pin:/{line=$0; sub(/#.*/,"",line); sub(/^[[:space:]]*llamacpp_pin:[[:space:]]*/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit}' harness.yaml)
[[ -n "$PIN" ]] || { echo "ERROR: runner.llamacpp_pin not set in harness.yaml"; exit 1; }

DEST="data/llamacpp"
BINPATH="$DEST/build/bin/llama-server"
ASSET="llama-${PIN}-bin-macos-arm64.tar.gz"
URL="https://github.com/ggml-org/llama.cpp/releases/download/${PIN}/${ASSET}"

echo "[harness] installing llama.cpp pin ${PIN}"
echo "[harness]   asset : ${ASSET}"
echo "[harness]   url   : ${URL}"

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

echo "[harness] extracting…"
if ! tar xzf "$TARBALL" -C "$STAGE"; then
  echo "ERROR: extraction failed — archive may not be a gzip tar. Downloaded from:"
  echo "  $URL"
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

echo "[harness] installed: $BINPATH"
# Print the version if the binary supports it (loads no model; cheap). Fall back to pin.
if "$BINPATH" --version >/tmp/llama-ver.txt 2>&1; then
  sed 's/^/[harness]   /' /tmp/llama-ver.txt | head -4
else
  echo "[harness]   version flag unsupported by this build — pinned tag: ${PIN}"
fi
rm -f /tmp/llama-ver.txt
echo "[harness] done — runner will auto-discover this binary (pin has priority over Jan/LM Studio)."
