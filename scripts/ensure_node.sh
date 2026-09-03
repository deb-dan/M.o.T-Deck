#!/usr/bin/env bash
# Make a usable `node` (>= 22.19, or >= 24) available WITHOUT Homebrew, WITHOUT sudo
# and WITHOUT writing anything outside the project tree.
#
# WHY THIS EXISTS AND WHY IT LOOKS LIKE ensure_bun.sh. The DeepSeek Harness lane
# (components.deepseek) is a TypeScript app: node is its RUN-time, not just its
# build-time. Before this file the repo had exactly one line about node anywhere —
# scripts/firstrun.sh's advisory "Node.js not found … ('brew install node')" — so a
# machine without node would have installed the component and then failed to start it
# with an error nobody could act on. ensure_bun.sh is the repo's established answer to
# "an external runtime we need but must not assume": three-step resolution, the user's
# own tool always wins, the pin lives in harness.yaml, the download lands in data/.
# This is that pattern applied to node. It does not exist for any other component.
#
# CONTRACT (identical to ensure_bun.sh, deliberately — one idiom, one set of surprises):
#   • the resolved node path is the ONLY thing printed on STDOUT
#   • every human-readable line goes to STDERR
#   • exit 0 = a usable node was found or provisioned; non-zero = none, and the
#     stderr lines say exactly what was tried
#
#   ⚠️ UNLIKE bun, A FAILURE HERE IS FATAL TO ITS CALLER. bun builds an optional web
#   UI, so ensure_bun.sh's callers swallow the failure (`|| true`) and ship a component
#   with no SPA. node RUNS the DeepSeek lane; without it there is nothing to install
#   and nothing to start, so install_deepseek.sh and start_component.sh both
#   treat an empty result as a hard, well-explained refusal. That difference is the
#   whole reason this comment exists.
#
# Resolution order — the user's own tools always win:
#   (a) a `node` already on PATH that satisfies the floor  → use it, never shadow it
#   (b) data/node/bin/node we provisioned                  → reuse it (refetched if
#                                                             the pin moved)
#   (c) download the PINNED release                        → data/node/bin/node
#
# ⚠️ (a) IS DELIBERATELY VERSION-CHECKED AND (b)/(c) ARE THE FALLBACK, NOT THE REVERSE.
# Debi's own node is v22.23.1 in ~/.local/bin. Shadowing it with a second 100MB copy of
# a runtime she already has would be rude and would double every future upgrade; but
# accepting a node BELOW the floor would hand the user a component that installs and
# then dies on `dsh --version`. So: her node if it is new enough, ours if it is not.
#
# The pin lives in harness.yaml under build.node_pin (single source of truth, same
# idiom as build.bun_pin / build.opencode_pin / runner.llamacpp_pin).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
say() { echo "[harness] $*" >&2; }

DEST="$ROOT/data/node"
BINPATH="$DEST/bin/node"

# THE FLOOR, and where it comes from. @deepseek-ai/dsh's monorepo root package.json
# declares `engines.node: "^22.19.0 || >=24.0.0"`. ⚠️ MEASURED 2026-09-03: the
# PUBLISHED npm package carries NO `engines` field at all, so npm will not enforce
# this and nothing but this script will. Encoded as two integers so the comparison is
# arithmetic rather than a string sort (v22.9.0 > v22.19.0 as strings).
FLOOR_MAJOR=22
FLOOR_MINOR=19        # only applies when major == 22
FLOOR_NEXT_MAJOR=24   # 23 is an odd/unsupported line; the range skips it on purpose

# Pin from harness.yaml build.node_pin (e.g. "v24.20.0"). Same awk reader as
# ensure_bun.sh / install_mlx.sh so there is exactly one way to read a build.* key.
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }

# "v24.20.0" → 24 20 0, on stdout, space separated. Empty on anything unparsable.
_semver() {   # <version string, with or without a leading v>
  local v="${1#v}"
  [[ "$v" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+) ]] || return 1
  echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}"
}

# 0 = satisfies the floor. Pure arithmetic; exposed for tests via --floor-check.
_meets_floor() {   # <version string>
  local parts maj min
  parts="$(_semver "$1")" || return 1
  maj="${parts%% *}"; min="$(echo "$parts" | cut -d' ' -f2)"
  (( maj >= FLOOR_NEXT_MAJOR )) && return 0
  (( maj == FLOOR_MAJOR && min >= FLOOR_MINOR )) && return 0
  return 1
}

if [[ "${1:-}" == "--floor-check" ]]; then
  _meets_floor "${2:-}"; exit $?
fi

# ── (a) the user's own node ───────────────────────────────────────────────────
# Checked BEFORE the pin is read: if the user already has a good node, a missing pin
# is irrelevant and must not turn into an error.
if command -v node >/dev/null 2>&1; then
  _have="$(node --version 2>/dev/null || true)"
  if _meets_floor "${_have:-}"; then
    say "node found on PATH: $(command -v node) (${_have}) — using it, not shadowing it"
    command -v node
    exit 0
  fi
  say "node on PATH is ${_have:-unreadable}, below the floor (>= v${FLOOR_MAJOR}.${FLOOR_MINOR}, or >= v${FLOOR_NEXT_MAJOR})."
  say "  Leaving it alone and provisioning our own pinned copy under data/node instead."
fi

PIN="${NODE_PIN:-$(_yb node_pin)}"
[[ -n "$PIN" ]] || {
  say "ERROR: build.node_pin missing from $(pwd)/harness.yaml"
  say "  (if this is the FAT app's snapshot: ship.sh's manifest merge is ADDITIVE, so a"
  say "   newly added build.* key does arrive — but only on the next ship. Add"
  say "   'node_pin: \"vNN.NN.N\"' under build:, or export NODE_PIN=vNN.NN.N and re-run.)"
  exit 1; }
PIN_VER="${PIN#v}"

# ── (b) a node we provisioned earlier ─────────────────────────────────────────
if [[ -x "$BINPATH" ]]; then
  HAVE="$("$BINPATH" --version 2>/dev/null || true)"
  if [[ -n "$HAVE" ]]; then
    if [[ "${HAVE#v}" == "$PIN_VER" ]]; then
      say "node already provisioned: $BINPATH (${HAVE})"
      echo "$BINPATH"
      exit 0
    fi
    say "provisioned node is ${HAVE} but the pin is ${PIN} — refetching"
  else
    say "provisioned node at $BINPATH does not run — refetching"
  fi
fi

# ── (c) download the pinned release ───────────────────────────────────────────
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Darwin/arm64)  ASSET="node-${PIN}-darwin-arm64.tar.xz" ;;
  Darwin/x86_64) ASSET="node-${PIN}-darwin-x64.tar.xz" ;;
  Linux/aarch64|Linux/arm64) ASSET="node-${PIN}-linux-arm64.tar.xz" ;;
  Linux/x86_64)  ASSET="node-${PIN}-linux-x64.tar.xz" ;;
  *)
    say "ERROR: no pinned node asset for $OS/$ARCH."
    say "  Install node >= v${FLOOR_MAJOR}.${FLOOR_MINOR} yourself: https://nodejs.org"
    exit 1 ;;
esac
BASE="https://nodejs.org/dist/${PIN}"
URL="${BASE}/${ASSET}"

command -v curl >/dev/null 2>&1 || { say "ERROR: 'curl' not found."; exit 1; }
command -v tar  >/dev/null 2>&1 || { say "ERROR: 'tar' not found."; exit 1; }

# MEASURED on the from-scratch walk (2026-09-03, v24.20.0 darwin-arm64): the tarball
# is 26MB on the wire and 199MB unpacked in data/node. Both numbers are said out loud
# because "about 50MB" was the guess and the guess was wrong in the direction that
# matters — a disk preflight sized against the download would have been too small.
say "provisioning node ${PIN} (${ASSET}) — about 26MB to download, ~200MB unpacked,"
say "  and it stays inside data/node (no sudo, no ~/.local, no shell-profile edits)"
say "  url : $URL"
mkdir -p "$DEST"
STAGE="$DEST/.staging"
rm -rf "$STAGE"; mkdir -p "$STAGE"
TARF="$DEST/.download.tar.xz"
SUMS="$DEST/.SHASUMS256.txt"
rm -f "$TARF" "$SUMS"

# ⚠️ THE CHECKSUM IS FETCHED FROM UPSTREAM, NOT HARDCODED HERE, AND THAT IS A
# DELIBERATE TRADE. A digest in this file would pin the BYTES (strictly stronger), but
# it would also mean every routine `node_pin` bump needs a hand-copied hash or the
# install refuses — the failure mode install_goose.sh accepts because its asset never
# moves. nodejs.org publishes SHASUMS256.txt per release over the same TLS origin as
# the tarball, so this catches a corrupt or truncated download and a mismatched asset;
# it does NOT defend against a compromised nodejs.org. Said out loud rather than
# implied, per the "verify BEFORE extract" rule the installer contract fences.
if ! curl -fsSL --retry 3 -m 120 -o "$SUMS" "${BASE}/SHASUMS256.txt"; then
  say "ERROR: could not fetch ${BASE}/SHASUMS256.txt (no network? bad pin?)"
  say "  Check the release exists: ${BASE}/"
  rm -rf "$STAGE"; rm -f "$SUMS"; exit 1
fi
WANT="$(awk -v a="$ASSET" '$2==a {print $1; exit}' "$SUMS")"
[[ -n "$WANT" ]] || {
  say "ERROR: ${ASSET} is not listed in that release's SHASUMS256.txt —"
  say "  upstream renamed the asset, or build.node_pin names a release that has none."
  rm -rf "$STAGE"; rm -f "$SUMS"; exit 1; }

if ! curl -fL --retry 3 -m 900 -o "$TARF" "$URL"; then
  say "ERROR: node download failed."
  say "  tried: $URL"
  rm -rf "$STAGE"; rm -f "$TARF" "$SUMS"; exit 1
fi

# VERIFY BEFORE EXTRACT — a mismatch is a corrupt download or a substituted artifact,
# and either way we stop with nothing unpacked and nothing left behind.
GOTSUM="$(shasum -a 256 "$TARF" 2>/dev/null | awk '{print $1}')"
if [[ "$GOTSUM" != "$WANT" ]]; then
  say "ERROR: sha256 MISMATCH for ${ASSET}"
  say "  got      : ${GOTSUM:-<could not hash>}"
  say "  nodejs.org says: ${WANT}"
  rm -rf "$STAGE"; rm -f "$TARF" "$SUMS"; exit 1
fi
say "sha256 verified (${WANT})"
rm -f "$SUMS"

if ! tar xJf "$TARF" -C "$STAGE"; then
  say "ERROR: could not unpack the node archive downloaded from:"
  say "  $URL"
  rm -rf "$STAGE"; rm -f "$TARF"; exit 1
fi

# Layout-agnostic (upstream ships node-<ver>-<plat>/bin/node today, but never assume it).
SRC="$(find "$STAGE" -type d -name bin -maxdepth 2 2>/dev/null | head -1)"
SRCROOT="${SRC%/bin}"
if [[ -z "$SRC" || ! -x "$SRCROOT/bin/node" ]]; then
  say "ERROR: no bin/node found inside the archive from:"
  say "  $URL"
  find "$STAGE" -maxdepth 3 -print | sed 's/^/    /' | head -30 >&2
  rm -rf "$STAGE"; rm -f "$TARF"; exit 1
fi

# The WHOLE distribution moves, not just the binary: `npm` is a node script that lives
# in lib/node_modules and resolves relative to its own prefix, and the installer needs
# npm as much as it needs node. Extracting one file (the install_opencode.sh shape)
# would give us a node with no npm.
rm -rf "$DEST/dist"
mkdir -p "$DEST"
mv "$SRCROOT" "$DEST/dist"
rm -rf "$DEST/bin"; mkdir -p "$DEST/bin"
ln -sf "../dist/bin/node" "$BINPATH"
ln -sf "../dist/bin/npm"  "$DEST/bin/npm"
rm -rf "$STAGE"; rm -f "$TARF"

GOT="$("$BINPATH" --version 2>/dev/null || true)"
if [[ -z "$GOT" ]]; then
  say "ERROR: $BINPATH was installed but does not run (quarantine? wrong arch?)."
  say "  Downloaded from: $URL"
  exit 1
fi
_meets_floor "$GOT" || {
  say "ERROR: provisioned node reports ${GOT}, which does not meet the floor."
  say "  build.node_pin is ${PIN} — that pin is wrong for this component."
  exit 1; }
say "node ${GOT} installed → $BINPATH (npm beside it)"
echo "$BINPATH"
