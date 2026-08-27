#!/usr/bin/env bash
# install_onlyoffice.sh — vendor the ONLYOFFICE static editors as LOffice tier 2.
#
#   ./scripts/install_onlyoffice.sh              install (idempotent)
#   ./scripts/install_onlyoffice.sh --check      say what is installed, change nothing
#   ./scripts/install_onlyoffice.sh --force      re-unzip even if the stamp matches
#
# NOT A COMPONENT. No port, no manifest entry, no daemon, no venv, no registry row.
# This unzips two verified zips into data/onlyoffice/ and writes a stamp. The bridge
# serves that directory read-only at /oo/* (bridge/oo.py); nothing else runs.
#
# ⚖️ AGPL-3.0 — the four standing conditions of the 2026-08-27 ruling
# (docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md "THE AGPL RULING"):
#   1. VENDOR CRYPTPAD'S RELEASE ZIPS ONLY, UNMODIFIED, with the recorded hashes and
#      the upstream URLs kept beside them. This script never patches a vendored byte;
#      it records SOURCES.txt + INSTALLED inside data/onlyoffice/ so the provenance
#      travels with the bundle.
#   2. Arm's length: its own directory, its own route, no intermixing with our code.
#   3. If the harness is ever distributed, About must name ONLYOFFICE + AGPL-3.0 and
#      link these exact tags (bridge/panel/oo.html footer + the LOffice About sheet).
#   4. fernfei/OnlyofficePersonal (the probe's Track A) is NEVER shipped. Its bundle
#      is a PATCHED web-apps build of unverified provenance; this script cannot even
#      reach it.
#
# ⚠️ THE PIN IS THE RECORDED HASH, NOT THE TAG. CryptPad's live install-onlyoffice.sh
# did not carry the editor sha512 we downloaded on 2026-08-27 (it pins a neighbouring
# build of the same tag family). The runbook already ruled on that: the hashes
# RECORDED BY THE PROBE are the pin. They are hardcoded below, and a mismatch is a
# hard failure — not a warning — because these bytes are the ones that were measured
# in a real WKWebView.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── the pin ──────────────────────────────────────────────────────────────────
EDITOR_REPO="cryptpad/onlyoffice-editor"
EDITOR_TAG="v9.2.0.119+3"
EDITOR_ASSET="onlyoffice-editor.zip"
EDITOR_SHA256="68ae8f0fe14fdde1fd845085deeeb37d98b5a8bb034622cd2a11c2f54f40930f"

X2T_REPO="cryptpad/onlyoffice-x2t-wasm"
X2T_TAG="v7.3+1"
X2T_ASSET="x2t.zip"
X2T_SHA256="86b6f1ac8f110b5a416ad199efa4c08957d46d989defe791b9793a966cfb3a04"

# OO_DEST exists for two honest reasons: an ops move of the 1GB bundle onto another
# volume, and bridge/tests/test_oo_lane.py, which exercises the hash gate against
# fixture zips and must not go anywhere near the real install.
DEST="${OO_DEST:-$ROOT/data/onlyoffice}"
STAMP="$DEST/INSTALLED"
SOURCES="$DEST/SOURCES.txt"
ZIPS="${OO_ZIP_DIR:-$DEST/zips}"
NEED_GB=4

say()  { echo "[onlyoffice] $*"; }
warn() { echo "[onlyoffice] WARN: $*" >&2; }
die()  { echo "[onlyoffice] ERROR: $*" >&2; exit 1; }

MODE="install"
case "${1:-}" in
  ""|--force) [[ "${1:-}" == "--force" ]] && MODE="force" ;;
  --check)    MODE="check" ;;
  -h|--help)
    echo "usage: ./scripts/install_onlyoffice.sh [--check|--force]"
    echo "env: OO_ZIP_DIR  reuse zips already on disk (e.g. data/office-probe/zips)"
    echo "     OO_DEST     install somewhere other than data/onlyoffice"
    echo "     OO_OFFLINE  never download: a missing or mismatching zip is an error"
    exit 0 ;;
  *) die "unknown argument ${1} — try --help" ;;
esac

# ── the stamp is the contract with the bridge ────────────────────────────────
# bridge/oo.py reads exactly this file to decide whether the "Rich editor" button is
# live or points at this installer. Format: `key value` lines, one per line, so a
# grep is a legitimate reader and a partial write cannot look complete (it is written
# to a temp file and renamed).
stamp_says() {   # stamp_says <key> -> value or ''
  [[ -f "$STAMP" ]] || return 0
  awk -v k="$1" '$1 == k { $1 = ""; sub(/^ /, ""); print; exit }' "$STAMP"
}

report_state() {
  if [[ ! -f "$STAMP" ]]; then
    say "not installed (no ${STAMP#"$ROOT"/})"
    return 1
  fi
  say "installed:"
  say "  editor      $(stamp_says editor_tag) sha256 $(stamp_says editor_sha256)"
  say "  x2t         $(stamp_says x2t_tag) sha256 $(stamp_says x2t_sha256)"
  say "  api.js      $(stamp_says api_js)"
  say "  x2t.js      $(stamp_says x2t_js)"
  say "  installed   $(stamp_says date)"
  return 0
}

if [[ "$MODE" == "check" ]]; then
  report_state || exit 1
  exit 0
fi

# ── preflight ────────────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || die "$1 not found — $2"; }
need curl "it ships with macOS; check your PATH"
need unzip "it ships with macOS; check your PATH"
need shasum "it ships with macOS; check your PATH"

mkdir -p "$DEST" "$ZIPS"

free_gb=$(df -k "$DEST" | awk 'NR==2 {print int($4/1048576)}')
if [[ "${free_gb:-0}" -lt "$NEED_GB" ]]; then
  die "only ${free_gb}GB free — the unzipped bundle is about 1.1GB and unzip needs headroom"
fi

# ── already done? ────────────────────────────────────────────────────────────
# Idempotence is checked against the STAMP plus the two files the bridge actually
# needs. A stamp without api.js on disk is a half install, not an install.
API_JS_REL="dist/v9/web-apps/apps/api/documents/api.js"
X2T_JS_REL="dist/x2t/x2t.js"
X2T_WASM_REL="dist/x2t/x2t.wasm"

if [[ "$MODE" != "force" && -f "$STAMP" ]] \
   && [[ "$(stamp_says editor_sha256)" == "$EDITOR_SHA256" ]] \
   && [[ "$(stamp_says x2t_sha256)" == "$X2T_SHA256" ]] \
   && [[ -f "$DEST/$API_JS_REL" && -f "$DEST/$X2T_WASM_REL" ]]; then
  say "already installed at the pinned hashes — nothing to do."
  report_state
  exit 0
fi

# ── fetch + verify ───────────────────────────────────────────────────────────
# sha256 is verified BEFORE anything is unzipped, every time, including for a zip
# that was already on disk. A cached zip is a convenience, never a trust boundary.
sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }

fetch_verified() {   # fetch_verified <url> <path> <expected-sha256> <label>
  local url="$1" dest="$2" want="$3" label="$4" got=""
  if [[ -s "$dest" ]]; then
    got="$(sha256_of "$dest")"
    if [[ "$got" == "$want" ]]; then
      say "reusing ${dest#"$ROOT"/} (sha256 matches the pin)"
      return 0
    fi
    warn "${dest#"$ROOT"/} is on disk but its sha256 does NOT match the pin"
    warn "  want ${want}"
    warn "  got  ${got}"
    if [[ -n "${OO_OFFLINE:-}" ]]; then
      die "sha256 MISMATCH for ${label} and OO_OFFLINE is set — refusing to unzip and
       refusing to download. The pin is the hash, not the tag."
    fi
    warn "  re-downloading (the old file is moved aside, not deleted)"
    mv -f "$dest" "${dest}.mismatch.$(date -u '+%Y%m%d%H%M%S')" || true
  fi
  if [[ -n "${OO_OFFLINE:-}" ]]; then
    die "${label} is not in ${ZIPS} and OO_OFFLINE is set — nothing was downloaded."
  fi
  say "downloading ${label} — this is a large file, be patient"
  # The tag contains a '+'. It is legal in a URL path segment and CryptPad's own
  # installer sends it literally, so we try that first and retry percent-encoded:
  # a 404 caused by encoding looks exactly like a wrong pin otherwise.
  if ! curl -fL -# --retry 3 --retry-delay 2 -o "${dest}.part" "$url"; then
    rm -f "${dest}.part"
    local alt="${url//+/%2B}"
    warn "that URL failed; retrying percent-encoded"
    curl -fL -# --retry 3 --retry-delay 2 -o "${dest}.part" "$alt" \
      || { rm -f "${dest}.part"; die "could not download ${label} from ${url}"; }
  fi
  mv -f "${dest}.part" "$dest"
  got="$(sha256_of "$dest")"
  [[ "$got" == "$want" ]] || die "sha256 MISMATCH for ${label} — refusing to unzip.
       want ${want}
       got  ${got}
       The pin is the hash, not the tag. If upstream re-cut the release, that is a
       decision for a human, not for this script."
  say "sha256 verified for ${label}"
}

EZ="$ZIPS/$EDITOR_ASSET"
XZ="$ZIPS/$X2T_ASSET"
fetch_verified "https://github.com/${EDITOR_REPO}/releases/download/${EDITOR_TAG}/${EDITOR_ASSET}" \
               "$EZ" "$EDITOR_SHA256" "${EDITOR_REPO} ${EDITOR_TAG} ${EDITOR_ASSET}"
fetch_verified "https://github.com/${X2T_REPO}/releases/download/${X2T_TAG}/${X2T_ASSET}" \
               "$XZ" "$X2T_SHA256" "${X2T_REPO} ${X2T_TAG} ${X2T_ASSET}"

# ── unzip into CryptPad's layout, UNMODIFIED ─────────────────────────────────
# dist/v9 = sdkjs + web-apps + fonts + dictionaries; dist/x2t = the converter. The
# x2t path is version-independent upstream (one converter serves every editor
# version) and we keep that, so a later editor bump does not touch it.
DV="$DEST/dist/v9"
DX="$DEST/dist/x2t"
say "unzipping the editor into data/onlyoffice/dist/v9/ (about 1GB, a minute or two)"
rm -rf "$DV"
mkdir -p "$DV"
unzip -q -o "$EZ" -d "$DV" || die "unzip of ${EDITOR_ASSET} failed"
say "unzipping x2t into data/onlyoffice/dist/x2t/"
rm -rf "$DX"
mkdir -p "$DX"
unzip -q -o "$XZ" -d "$DX" || die "unzip of ${X2T_ASSET} failed"

# Some releases wrap everything in one top-level folder; flatten it so the served
# paths match CryptPad's documented layout exactly.
flatten_single_dir() {
  local d="$1" n inner
  n=$(find "$d" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
  [[ "$n" == "1" ]] || return 0
  inner=$(find "$d" -mindepth 1 -maxdepth 1)
  [[ -d "$inner" ]] || return 0
  say "  (flattening single top-level dir $(basename "$inner"))"
  ( shopt -s dotglob nullglob; mv "$inner"/* "$d"/ ) && rmdir "$inner" || true
}
flatten_single_dir "$DV"
flatten_single_dir "$DX"

# ── verify the landing, then stamp ───────────────────────────────────────────
for rel in "$API_JS_REL" "$X2T_JS_REL" "$X2T_WASM_REL" \
           "dist/v9/web-apps/apps/spreadsheeteditor/main/index.html" \
           "dist/v9/web-apps/apps/documenteditor/main/index.html" \
           "dist/v9/web-apps/apps/presentationeditor/main/index.html" \
           "dist/v9/sdkjs/cell/sdk-all-min.js"; do
  [[ -f "$DEST/$rel" ]] || die "the unzip landed but ${rel} is missing — the release
       layout changed. Look at ${DEST}/dist and do not ship this."
done

files=$(find "$DEST/dist" -type f | wc -l | tr -d ' ')
size=$(du -sh "$DEST/dist" 2>/dev/null | awk '{print $1}')
say "landed: ${files} files, ${size}"

cat > "${SOURCES}.tmp" <<SRC
ONLYOFFICE static editors — vendored for LOffice tier 2.

LICENCE: AGPL-3.0. This bundle is UNMODIFIED upstream. Nothing in the harness
patches, minifies, re-bundles or otherwise derives from these files; the bridge
serves them read-only at /oo/* and our own glue page (bridge/panel/oo.html) drives
them through their published DocsAPI/connectMockServer surface.

editor  ${EDITOR_REPO} @ ${EDITOR_TAG}
  asset   ${EDITOR_ASSET}
  source  https://github.com/${EDITOR_REPO}/releases/tag/${EDITOR_TAG}
  code    https://github.com/${EDITOR_REPO}
  sha256  ${EDITOR_SHA256}

x2t     ${X2T_REPO} @ ${X2T_TAG}
  asset   ${X2T_ASSET}
  source  https://github.com/${X2T_REPO}/releases/tag/${X2T_TAG}
  code    https://github.com/${X2T_REPO}
  sha256  ${X2T_SHA256}

upstream (the editors themselves)
  https://github.com/ONLYOFFICE/web-apps
  https://github.com/ONLYOFFICE/sdkjs
  https://github.com/ONLYOFFICE/core           (x2t)

If this harness is ever distributed to anyone else, the About surface must name
ONLYOFFICE + AGPL-3.0 and link these tags, and any modification made to the bundle
must be published. See docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md, AGPL ruling #3.
SRC
mv -f "${SOURCES}.tmp" "$SOURCES"

cat > "${STAMP}.tmp" <<EOF
schema 1
date $(date -u '+%Y-%m-%dT%H:%M:%SZ')
editor_repo ${EDITOR_REPO}
editor_tag ${EDITOR_TAG}
editor_sha256 ${EDITOR_SHA256}
x2t_repo ${X2T_REPO}
x2t_tag ${X2T_TAG}
x2t_sha256 ${X2T_SHA256}
api_js ${API_JS_REL}
x2t_js ${X2T_JS_REL}
x2t_wasm ${X2T_WASM_REL}
files ${files}
licence AGPL-3.0
EOF
mv -f "${STAMP}.tmp" "$STAMP"

say "done. The bridge picks this up with no restart (bridge/oo.py reads the stamp"
say "per request), but ship.sh is still the way to push code changes."
report_state
