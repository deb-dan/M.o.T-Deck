#!/usr/bin/env bash
# install_goose_ui.sh — self-provision the GOOSE UI surface: goose Desktop's own
# renderer bundle, extracted from a SHA-PINNED UPSTREAM RELEASE ARTIFACT.
#
#   ./scripts/install_goose_ui.sh              install (idempotent)
#   ./scripts/install_goose_ui.sh --check      say what is installed, change nothing
#   ./scripts/install_goose_ui.sh --force      re-download + re-extract even at the pin
#
# ⚠️ WHY THIS DOWNLOADS 209MB TO KEEP 6.6MB, AND WHY THAT IS STILL THE RIGHT SHAPE.
# Upstream publishes ONE macOS desktop artifact per release — `Goose.zip`, the whole
# signed .app (Electron framework + the 268MB goose Mach-O + the renderer). There is no
# separate renderer artifact and no `latest-mac.yml` at this tag (checked: 404). The only
# alternative is building `ui/desktop` from the pinned source tree, which needs node +
# pnpm + a lockfile install on the user's machine — a much larger, much less
# reproducible dependency than one digest-verified download we throw away. So: fetch the
# pinned zip, extract ONE MEMBER (`Goose.app/Contents/Resources/app.asar`), verify a
# SECOND digest over that member, unpack the renderer from it, delete the zip.
#
# ⚠️ AND IT NEVER READS THE USER'S OWN INSTALLED Goose.app. The spike did, to prove the
# serve-and-shim quickly; that path is DELETED (doctrine 2b — sourcing an artifact from a
# local copy silently exempts the install journey from ever being tested). If Goose.app
# happens to be installed on this Mac, this script does not look at it.
#
# ⚠️ THE PIN IS THREE DIGESTS OVER THREE DIFFERENT SETS OF BYTES, and each one makes the
# next claim honest rather than assumed:
#   1. the ZIP's sha256          → "we downloaded the artifact upstream published"
#   2. the app.asar's sha256     → "the zip contained the container we measured"
#   3. the BUNDLE sha256         → "unpacking it produced exactly these 89 files"
# install_onlyoffice.sh and install_goose.sh use the same two-digest discipline; the
# third exists here because unpacking is OUR code, not tar's.
#
# ⚠️ NOTHING IS SWAPPED IN UNTIL EVERY CHECK HAS PASSED. All work happens in a
# per-invocation staging directory, and a failure at ANY point leaves the previously
# installed bundle exactly as it was — never a half-install. The staging directory is
# also the LOCK: two installers cannot share a partial download (the comfy A-10
# two-writer `.part` lesson), because the second one refuses on a held lock rather than
# writing into the first one's file.
#
# ⚖️ LICENSE: Apache-2.0. goose ships one LICENSE at its repo root and
# ui/desktop/package.json declares "license": "Apache-2.0"; there is no NOTICE file
# upstream. §4b (state your changes) is answered by data/goose/UI-SOURCES.txt: we change
# nothing — the bundle is served byte-for-byte and every shim lives in our own generated
# page + preload script. TRADEMARK: goose is a Series of LF Projects, LLC; the UI keeps
# its own name, wordmark and Block lockup assets exactly as shipped.
#
# What lands:
#   data/goose/ui/                  the renderer bundle, UNMODIFIED (89 files, 6.6MB)
#   data/goose/ui.sha256            per-file sha manifest + the one BUNDLE line
#   data/goose/UI-SOURCES.txt       provenance stamp
#   data/goose/UI-INSTALLED         machine-readable stamp (the panel reads this)
#   data/logs/goose-ui-install.log  panel-viewable install log
#
# The goose BINARY is a separate, already-pinned install: ./scripts/install_goose.sh.
# ONLINE-ONLY. Idempotent: a bundle already at the pin is left alone.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── THE PIN ──────────────────────────────────────────────────────────────────
# Measured 2026-08-29 against the real release. Bumping goose means editing ALL of these
# together and re-running with --force; there is deliberately no env override.
GOOSE_REPO="aaif-goose/goose"
GOOSE_TAG="v1.48.0"
UI_ASSET="Goose.zip"                       # the ONLY macOS desktop artifact at this tag
UI_ASSET_SIZE="219010697"
UI_ASSET_SHA256="98d7b09c9e57949e0dc2c8889fc05934bffb3159ae1a0c26ae0d78f397db5041"
ASAR_MEMBER="Goose.app/Contents/Resources/app.asar"
ASAR_SHA256="9f9f9db4a0d47a1774c86a109f19a2fd0257401726eabc0237dcb0e9b2ad9903"
RENDERER_PREFIX="/.vite/renderer/main_window"
BUNDLE_SHA256="342d291ddc8c41d923e15760e56164ef8e331a2dcde0769b0c476e6907d8acd0"
APP_VERSION="1.48.0"

DEST="${GOOSE_UI_DEST:-$ROOT/data/goose}"
UI="$DEST/ui"
MAN="$DEST/ui.sha256"
SOURCES="$DEST/UI-SOURCES.txt"
STAMP="$DEST/UI-INSTALLED"
LOG="$ROOT/data/logs/goose-ui-install.log"
URL="https://github.com/${GOOSE_REPO}/releases/download/${GOOSE_TAG}/${UI_ASSET}"

FORCE=0; CHECK=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    --yes|-y) ;;                                  # accepted, nothing here prompts
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

mkdir -p "$ROOT/data/logs"
if [[ "$CHECK" -eq 0 ]]; then
  exec > >(tee -a "$LOG") 2>&1
  echo "──────── install_goose_ui.sh · $(date '+%Y-%m-%d %H:%M:%S') ────────"
fi

say()  { echo "[goose-ui] $*"; }
die()  { echo "[goose-ui] ERROR: $*" >&2; exit 1; }
sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
bundle_sha_of() {   # bundle_sha_of <dir> — the sha over the sorted per-file sha list
  ( cd "$1" && find . -type f | LC_ALL=C sort | xargs shasum -a 256 ) | shasum -a 256 \
    | awk '{print $1}'
}

# ── --check ──────────────────────────────────────────────────────────────────
if [[ "$CHECK" -eq 1 ]]; then
  if [[ -f "$UI/index.html" ]]; then
    echo "[goose-ui] bundle  ${UI#"$ROOT"/}  ($(find "$UI" -type f | wc -l | tr -d ' ') files)"
    echo "[goose-ui] on disk $(bundle_sha_of "$UI")"
    echo "[goose-ui] pin     ${BUNDLE_SHA256}"
    [[ "$(bundle_sha_of "$UI")" == "$BUNDLE_SHA256" ]] \
      && echo "[goose-ui] VERIFIED — the bundle is at the pin, unmodified." \
      || echo "[goose-ui] MISMATCH — re-run without --check (or with --force)."
  else
    echo "[goose-ui] not installed (no $UI/index.html)"
    echo "[goose-ui] would download ${UI_ASSET} (${UI_ASSET_SIZE} bytes) from ${URL}"
  fi
  exit 0
fi

# ── preconditions ────────────────────────────────────────────────────────────
command -v curl   >/dev/null 2>&1 || die "curl not found."
command -v shasum >/dev/null 2>&1 || die "shasum not found (it ships with macOS)."
command -v unzip  >/dev/null 2>&1 || die "unzip not found (it ships with macOS)."
command -v python3 >/dev/null 2>&1 || die "python3 not found — the asar reader needs it."

FREE_GB=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
say "free disk on this volume: ${FREE_GB}GB (the download is 0.21GB, kept 0.007GB)"
[[ "$FREE_GB" -ge 2 ]] || die "not enough free disk — need about 2GB, have ${FREE_GB}GB."

# ── already at the pin? ──────────────────────────────────────────────────────
if [[ "$FORCE" -eq 0 && -f "$UI/index.html" ]]; then
  got="$(bundle_sha_of "$UI")"
  if [[ "$got" == "$BUNDLE_SHA256" ]]; then
    say "already installed at the pin (bundle ${got}) — nothing to download."
    exit 0
  fi
  say "the installed bundle's sha does not match the pin — replacing it."
  say "  on disk: ${got}"
  say "  pin:     ${BUNDLE_SHA256}"
fi

# ── THE LOCK / STAGING DIRECTORY ─────────────────────────────────────────────
# `mkdir` is atomic on every filesystem we care about, so the directory IS the lock: a
# second installer fails to create it and refuses, instead of appending into the first
# one's half-written download. That is the comfy A-10 lesson stated as a mechanism —
# two writers on one `.part` file produce a corrupt artifact whose digest failure looks
# like an upstream problem.
STAGE="$DEST/.ui-install"
if ! mkdir "$STAGE" 2>/dev/null; then
  die "another install is already running (staging dir ${STAGE#"$ROOT"/} exists).
     If you are sure nothing is running, remove it and try again:
       rm -rf '${STAGE}'"
fi
# EVERY exit path cleans the staging dir — including a Ctrl-C mid-download. An
# interrupted transfer therefore leaves NOTHING behind: the next run starts clean, and
# the previously installed bundle (if any) was never touched.
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT INT TERM

ZIP="$STAGE/${UI_ASSET}"
say "downloading ${UI_ASSET} (${UI_ASSET_SIZE} bytes ≈ 209MB) from ${GOOSE_REPO} ${GOOSE_TAG}…"
say "  only ${ASAR_MEMBER} is kept; the rest of the .app is discarded."
# --fail so an HTML 404 page is an error rather than a 9-byte "artifact"; --retry for a
# flaky line; -# would be a progress bar on a tty, but this is tee'd into a log the panel
# renders, so plain output it is.
curl -fL --retry 3 -sS -o "$ZIP" "$URL" || die \
  "download FAILED: ${URL}
     Nothing was installed and the previous bundle (if any) is untouched.
     If this is a 404, the release asset for the pin has moved or been withdrawn:
     the pin is ${GOOSE_TAG} / ${UI_ASSET} / sha256 ${UI_ASSET_SHA256}."

# SIZE first — free, and it names the problem better than a digest does ("you got a
# 9-byte error page" vs "the hashes differ").
gotsize="$(wc -c <"$ZIP" | tr -d ' ')"
[[ "$gotsize" == "$UI_ASSET_SIZE" ]] || die \
  "size MISMATCH for ${UI_ASSET}: got ${gotsize} bytes, the pin says ${UI_ASSET_SIZE}.
     Refusing to extract. Nothing was installed."

gotsha="$(sha256_of "$ZIP")"
[[ "$gotsha" == "$UI_ASSET_SHA256" ]] || die \
  "sha256 MISMATCH for ${UI_ASSET} — refusing to extract. Nothing was installed.
       got: ${gotsha}
       pin: ${UI_ASSET_SHA256}
     Either the download is corrupt or the release asset was replaced. Neither is
     something to shrug at: re-run, and if it happens twice, re-verify the pin."
say "sha256 verified for ${UI_ASSET} (${gotsha})"

# ── extract ONE member, then digest #2 ───────────────────────────────────────
unzip -q -o "$ZIP" "$ASAR_MEMBER" -d "$STAGE" || die \
  "the archive does not contain ${ASAR_MEMBER} — upstream changed the .app layout.
     Nothing was installed."
ASAR="$STAGE/$ASAR_MEMBER"
[[ -f "$ASAR" ]] || die "no app.asar after extraction. Nothing was installed."
rm -f "$ZIP"                       # 209MB we can always re-fetch against the digest

asarsha="$(sha256_of "$ASAR")"
[[ "$asarsha" == "$ASAR_SHA256" ]] || die \
  "app.asar sha256 is ${asarsha}, the pin says ${ASAR_SHA256}. Nothing was installed."
say "sha256 verified for app.asar (${asarsha})"

# ── unpack the renderer, then digest #3 ──────────────────────────────────────
# asar is a trivial container: a 16-byte pickle header, a JSON directory, then the
# concatenated file bodies. Reading it in Python costs nothing and adds no node/npm
# dependency to a bridge that has neither.
NEW="$STAGE/ui"
mkdir -p "$NEW"
python3 - "$ASAR" "$NEW" "$RENDERER_PREFIX" <<'PY'
import json, os, struct, sys
asar, outdir, prefix = sys.argv[1], sys.argv[2], sys.argv[3]
with open(asar, "rb") as fh:
    _a, hdr_size, _c, json_len = struct.unpack("<IIII", fh.read(16))
    hdr = json.loads(fh.read(json_len).decode("utf-8"))
    base = 8 + hdr_size

def walk(node, path=""):
    for name, meta in (node.get("files") or {}).items():
        p = path + "/" + name
        if "files" in meta:
            yield from walk(meta, p)
        else:
            yield p, meta

n = 0
with open(asar, "rb") as fh:
    for p, meta in walk(hdr):
        if not p.startswith(prefix + "/") or "offset" not in meta:
            continue
        rel = p[len(prefix) + 1:]
        dest = os.path.join(outdir, rel)
        # Containment: a crafted asar directory entry must not write outside outdir.
        if not os.path.realpath(dest).startswith(os.path.realpath(outdir) + os.sep):
            raise SystemExit(f"refused: asar entry escapes the output dir: {p}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        fh.seek(base + int(meta["offset"]))
        open(dest, "wb").write(fh.read(int(meta["size"])))
        n += 1
if n == 0:
    raise SystemExit(f"no files under {prefix} — upstream changed the bundle layout")
print(f"[goose-ui] unpacked {n} renderer files")
PY
[[ -f "$NEW/index.html" ]] || die "no index.html in the unpacked renderer. Nothing was installed."

newsha="$(bundle_sha_of "$NEW")"
[[ "$newsha" == "$BUNDLE_SHA256" ]] || die \
  "the unpacked bundle's sha is ${newsha}, the pin says ${BUNDLE_SHA256}.
     Nothing was installed."
say "sha verified for the unpacked bundle (${newsha})"

# ── the manifest, then the ATOMIC swap ───────────────────────────────────────
( cd "$NEW" && find . -type f | LC_ALL=C sort | xargs shasum -a 256 ) > "$STAGE/man"
{ echo "# goose Desktop renderer bundle — installed by scripts/install_goose_ui.sh"
  echo "# app ${APP_VERSION} · ${UI_ASSET} ${UI_ASSET_SHA256} · app.asar ${ASAR_SHA256}"
  echo "BUNDLE ${BUNDLE_SHA256}"
  cat "$STAGE/man"; } > "$STAGE/ui.sha256"

# Swap LAST, and move the old one aside first so an interrupted swap can be seen rather
# than leaving an empty ui/ that looks installed.
rm -rf "$DEST/.ui-old"
[[ -d "$UI" ]] && mv "$UI" "$DEST/.ui-old"
mv "$NEW" "$UI"
mv "$STAGE/ui.sha256" "$MAN"
rm -rf "$DEST/.ui-old"

cat > "$SOURCES" <<EOF
goose Desktop RENDERER BUNDLE — installed by scripts/install_goose_ui.sh, UNMODIFIED.

  repo          https://github.com/${GOOSE_REPO}
  tag           ${GOOSE_TAG}
  app version   ${APP_VERSION}
  asset         ${UI_ASSET}
  asset url     ${URL}
  asset size    ${UI_ASSET_SIZE}
  asset sha256  ${UI_ASSET_SHA256}
  asar member   ${ASAR_MEMBER}
  asar sha256   ${ASAR_SHA256}
  asar path     ${RENDERER_PREFIX}
  bundle sha    ${BUNDLE_SHA256}   (sha256 of the sorted per-file sha manifest)
  manifest      data/goose/ui.sha256
  license       Apache-2.0 (goose ships one LICENSE at repo root; ui/desktop/package.json
                declares "license": "Apache-2.0"; no NOTICE file exists upstream)

CHANGES STATED (Apache-2.0 §4b): none to these files. The bundle is served byte-for-byte.
The Electron window.electron / window.appConfig preload seam is supplied by OUR OWN
generated script (bridge/gooseui.py, served at /gooseui/harness-preload.js) and OUR OWN
copy of the entry document (served at /gooseui/, generated from the vendored index.html
with one extra <script> tag and our own surface title). Nothing under data/goose/ui/ is
edited — bridge/contract_tests/test_gooseui_contract.py recomputes every digest.

TRADEMARK: goose is a Series of LF Projects, LLC. The UI keeps its own name, wordmark and
Block lockup assets exactly as shipped — nominative use of an unmodified UI, not a rebrand.

NOTE: this installer NEVER reads a Goose.app installed on this Mac. Sourcing the artifact
from a local copy would exempt the install path from ever being tested (doctrine 2b).

Reproduce:
  curl -sLO ${URL}
  shasum -a 256 ${UI_ASSET}
EOF

cat > "$STAMP" <<EOF
tag ${GOOSE_TAG}
app_version ${APP_VERSION}
asset ${UI_ASSET}
asset_size ${UI_ASSET_SIZE}
asset_sha256 ${UI_ASSET_SHA256}
asar_sha256 ${ASAR_SHA256}
bundle_sha256 ${BUNDLE_SHA256}
files $(find "$UI" -type f | wc -l | tr -d ' ')
installed_at $(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

echo ""
say "bundle:   ${UI#"$ROOT"/}  ($(find "$UI" -type f | wc -l | tr -d ' ') files, $(du -sh "$UI" | awk '{print $1}'))"
say "manifest: ${MAN#"$ROOT"/}  (BUNDLE ${BUNDLE_SHA256})"
say "served:   http://127.0.0.1:8700/gooseui/  — the Goose UI tab"
say "backend:  a supervised 'goose serve --platform desktop' from the SAME pinned binary"
say "  the terminal lane uses, fenced with GOOSE_PATH_ROOT=data/goose/ui-home/goose so"
say "  its sessions can never mix with the terminal lane's."
say "NOTE: the goose BINARY is a separate pinned install — ./scripts/install_goose.sh"
