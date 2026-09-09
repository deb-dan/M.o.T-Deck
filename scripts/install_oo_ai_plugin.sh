#!/usr/bin/env bash
# install_oo_ai_plugin.sh — vendor ONLYOFFICE's OWN AI plugin for the LOffice ribbon.
#
#   ./scripts/install_oo_ai_plugin.sh              install (idempotent)
#   ./scripts/install_oo_ai_plugin.sh --check      say what is installed, change nothing
#   ./scripts/install_oo_ai_plugin.sh --force      re-unzip even if the stamp matches
#
# NOT A COMPONENT, and deliberately NOT part of install_onlyoffice.sh: the plugin has
# its own upstream, its own licence line and its own pins, and an editor-bundle bump
# must not silently re-cut the plugin (or the reverse). Its own directory, its own
# stamp, its own route (/ooplug/*).
#
# ⚖️ AGPL-3.0 — the same four standing conditions as the editor bundle
# (docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md "THE AGPL RULING"), and the reason this
# script downloads a RELEASE-SHAPED ARTEFACT rather than assembling one:
#   1. UNMODIFIED. `ai.plugin` is upstream's own deploy zip and it is unzipped as-is.
#      NOT ONE BYTE IS PATCHED — which is possible only because that zip's index.html
#      references the shared SDK RELATIVELY (`./../v1/plugins.js`). The repository's
#      working copy of the same file uses ABSOLUTE https://onlyoffice.github.io URLs,
#      which a cross-origin-isolated (COEP) page cannot load and an offline machine
#      cannot reach at all. Vendoring the deploy zip is therefore not a convenience:
#      it is the ONLY way to serve this plugin same-origin without editing it.
#      ⚠️ If a future pin's index.html reverts to absolute URLs, this script FAILS
#      LOUDLY (the guard is below) instead of shipping a plugin that needs the net.
#   2. Arm's length: data/onlyoffice-plugins/, served read-only, no intermixing.
#   3. If MOT Deck is ever distributed, About must name ONLYOFFICE + AGPL-3.0 and
#      link these exact pins. SOURCES.txt is written beside the bundle for that.
#   4. Nothing of unverified provenance: every byte is sha256-pinned below.
#
# ⚠️ THE PIN IS THE COMMIT + THE HASH. Upstream publishes the plugin from a branch,
# not a tagged release, so a tag cannot be the pin. The pin is the repository COMMIT
# the bytes were taken from plus the sha256 of each file. A mismatch is a hard
# failure — never a warning.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── the pin ──────────────────────────────────────────────────────────────────
REPO="ONLYOFFICE/onlyoffice.github.io"
COMMIT="799b28724a69d29bcb0a31bffc00c9b173867b54"      # 2026-08-28, recorded by this slice
RAW="https://raw.githubusercontent.com/${REPO}/${COMMIT}/sdkjs-plugins"

PLUGIN_REL="content/ai/deploy/ai.plugin"
PLUGIN_SHA256="5e98cc51659cdf3fd0edcdf076137893575f4840a5fa6dcb2f460f93c8669c43"
PLUGIN_VERSION="3.2.2"                                  # config.json INSIDE THE DEPLOY ZIP.
#                                                       ⚠️ Not the same as the repo's
#                                                       working-copy config.json (3.2.3 at
#                                                       this commit) — the deploy archive is
#                                                       cut on its own cadence. The vendored
#                                                       BYTES are the truth; the mismatch
#                                                       warning below caught this.
PLUGIN_GUID="asc.{9DC93CDB-B576-4F0C-B55E-FCC9C48DD007}"

# The shared plugin SDK the plugin's index.html loads as `./../v1/*`. Three files,
# each self-contained (verified: no external refs, every image a data: URI).
SDK_FILES=(plugins.js plugins-ui.js plugins.css)
SDK_SHA_plugins_js="f859cfeb337e82afd97391dde1e413d41a31a45e2f986238e1796ebe324a2d43"
SDK_SHA_plugins_ui_js="4896dd856c75b7efb764447295582a3c0c93769c1f3b3574ac256f6bf33f6f5a"
SDK_SHA_plugins_css="d0fabc8d79c8c4fa677f399df7e433dea1c7f77bf33e0653c530b55367e08abd"

sdk_sha_for() {   # sdk_sha_for <filename>
  case "$1" in
    plugins.js)     echo "$SDK_SHA_plugins_js" ;;
    plugins-ui.js)  echo "$SDK_SHA_plugins_ui_js" ;;
    plugins.css)    echo "$SDK_SHA_plugins_css" ;;
    *)              echo "" ;;
  esac
}

# OOP_DEST exists for the same two honest reasons OO_DEST does: an ops move, and the
# test suite, which must never go near the real install.
DEST="${OOP_DEST:-$ROOT/data/onlyoffice-plugins}"
STAMP="$DEST/INSTALLED"
SOURCES="$DEST/SOURCES.txt"
CACHE="${OOP_ZIP_DIR:-$DEST/zips}"

say()  { echo "[oo-ai-plugin] $*"; }
warn() { echo "[oo-ai-plugin] WARN: $*" >&2; }
die()  { echo "[oo-ai-plugin] ERROR: $*" >&2; exit 1; }

MODE="install"
case "${1:-}" in
  ""|--force) [[ "${1:-}" == "--force" ]] && MODE="force" ;;
  --check)    MODE="check" ;;
  -h|--help)
    echo "usage: ./scripts/install_oo_ai_plugin.sh [--check|--force]"
    echo "env: OOP_ZIP_DIR  reuse an ai.plugin already on disk"
    echo "     OOP_DEST     install somewhere other than data/onlyoffice-plugins"
    echo "     OOP_OFFLINE  never download: a missing or mismatching file is an error"
    exit 0 ;;
  *) die "unknown argument ${1} — try --help" ;;
esac

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
  say "  plugin      ai ${PLUGIN_VERSION} sha256 $(stamp_says plugin_sha256)"
  say "  guid        $(stamp_says plugin_guid)"
  say "  commit      $(stamp_says commit)"
  say "  sdk         $(stamp_says sdk_files)"
  say "  installed   $(stamp_says date)"
  return 0
}

if [[ "$MODE" == "check" ]]; then
  report_state || exit 1
  exit 0
fi

need() { command -v "$1" >/dev/null 2>&1 || die "$1 not found — it ships with macOS"; }
need curl; need unzip; need shasum

# Hold one kernel lock across downloads, validation and publication. The helper
# execs this shell with an inherited descriptor, so SIGKILL cannot strand a lock
# directory and a surviving installer child still excludes a replacement.
PUBLISHER="$ROOT/scripts/oo_plugin_install.py"
if [[ -z "${OOP_INSTALL_LOCK_FD:-}" ]]; then
  exec python3 "$PUBLISHER" run "$DEST" "$ROOT/scripts/install_oo_ai_plugin.sh" "$@"
fi
python3 "$PUBLISHER" recover "$DEST"

mkdir -p "$DEST" "$CACHE"

PLUGIN_INDEX_REL="ai/index.html"
PLUGIN_CONFIG_REL="ai/config.json"

if [[ "$MODE" != "force" && -f "$STAMP" ]] \
   && [[ "$(stamp_says plugin_sha256)" == "$PLUGIN_SHA256" ]] \
   && [[ -f "$DEST/$PLUGIN_INDEX_REL" && -f "$DEST/v1/plugins.js" ]]; then
  say "already installed at the pinned hashes — nothing to do."
  report_state
  exit 0
fi

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
    [[ -n "${OOP_OFFLINE:-}" ]] && die "sha256 MISMATCH for ${label} and OOP_OFFLINE
       is set — refusing to unzip and refusing to download."
    mv -f "$dest" "${dest}.mismatch.$(date -u '+%Y%m%d%H%M%S')" || true
  fi
  [[ -n "${OOP_OFFLINE:-}" ]] && die "${label} is not on disk and OOP_OFFLINE is set."
  say "downloading ${label}"
  curl -fsSL --retry 3 --retry-delay 2 -o "${dest}.part" "$url" \
    || { rm -f "${dest}.part"; die "could not download ${label} from ${url}"; }
  mv -f "${dest}.part" "$dest"
  got="$(sha256_of "$dest")"
  [[ "$got" == "$want" ]] || die "sha256 MISMATCH for ${label} — refusing to install.
       want ${want}
       got  ${got}
       The pin is the commit AND the hash. If upstream force-pushed that branch, that
       is a decision for a human, not for this script."
  say "sha256 verified for ${label}"
}

# ── the plugin ───────────────────────────────────────────────────────────────
PZ="$CACHE/ai.plugin"
fetch_verified "${RAW}/${PLUGIN_REL}" "$PZ" "$PLUGIN_SHA256" "${REPO}@${COMMIT:0:7} ${PLUGIN_REL}"

# Prepare the entire plugin and SDK before touching the served installation.
# The durable publication journal also restores interrupted installs next time.
STAGE=""
cleanup_install() {
  local result=$?
  trap - EXIT
  [[ -z "$STAGE" ]] || python3 "$PUBLISHER" cleanup "$DEST" "$STAGE" || exit 1
  exit "$result"
}
trap cleanup_install EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
STAGE="$(python3 "$PUBLISHER" stage "$DEST")"
CANDIDATE="$STAGE/new"
AIDIR="$CANDIDATE/ai"
mkdir -p "$AIDIR" "$STAGE/old"
say "unzipping the plugin into a private candidate"
unzip -q -o "$PZ" -d "$AIDIR" || die "unzip of ai.plugin failed"

# Some deploy zips wrap everything in one folder; flatten so config.json is at the
# top of ai/ (the URL the editor is given ends in `ai/config.json`).
if [[ ! -f "$AIDIR/config.json" ]]; then
  inner="$(find "$AIDIR" -mindepth 1 -maxdepth 1 -type d | head -1)"
  if [[ -n "$inner" && -f "$inner/config.json" ]]; then
    say "  (flattening single top-level dir $(basename "$inner"))"
    ( shopt -s dotglob nullglob; mv "$inner"/* "$AIDIR"/ ) && rmdir "$inner" || true
  fi
fi

# ── the shared SDK ───────────────────────────────────────────────────────────
mkdir -p "$CANDIDATE/v1"
for f in "${SDK_FILES[@]}"; do
  want="$(sdk_sha_for "$f")"
  [[ -n "$want" ]] || die "no pinned hash for SDK file ${f} — refusing to fetch it"
  # Reuse installed SDK bytes offline, but verify them against the requested pin.
  [[ ! -f "$DEST/v1/$f" ]] || cp "$DEST/v1/$f" "$CANDIDATE/v1/$f"
  fetch_verified "${RAW}/v1/${f}" "$CANDIDATE/v1/$f" "$want" "${REPO}@${COMMIT:0:7} v1/${f}"
done

# ── verify the landing ───────────────────────────────────────────────────────
for rel in "$PLUGIN_CONFIG_REL" "$PLUGIN_INDEX_REL" \
           "ai/scripts/engine/providers/provider.js" \
           "ai/scripts/engine/local_storage.js" \
           "v1/plugins.js" "v1/plugins-ui.js" "v1/plugins.css"; do
  [[ -f "$CANDIDATE/$rel" ]] || die "the unzip landed but ${rel} is missing — the deploy
       layout changed. Look at ${DEST} and do not ship this."
done

# ⚠️ THE GUARD THAT KEEPS CONDITION #1 TRUE. If index.html ever points at
# onlyoffice.github.io again, the plugin would need the network AND would be blocked
# by COEP — and the only fixes are editing it (breaks "unmodified") or shipping a
# dead ribbon tab. Fail here instead, loudly, while a human is watching.
if grep -q "onlyoffice\.github\.io" "$CANDIDATE/$PLUGIN_INDEX_REL"; then
  die "this pin's index.html loads the plugin SDK from onlyoffice.github.io (absolute).
       A cross-origin-isolated page cannot load that, and an offline machine cannot
       reach it. The vendored deploy zip is supposed to use ./../v1/ RELATIVE paths.
       Do not ship this pin — record the finding and pick a pin that deploys relatively."
fi
grep -q "\./\.\./v1/plugins\.js" "$CANDIDATE/$PLUGIN_INDEX_REL" \
  || die "index.html does not reference ./../v1/plugins.js — the layout this
       installer serves no longer matches the plugin.

⚠️ THE LAYOUT IS <dest>/ai/ NEXT TO <dest>/v1/, AND THAT IS FORCED, NOT CHOSEN.
   index.html loads the SDK as ./../v1/plugins.js, which resolves ONE level above the
   plugin folder. Unzipping into <dest>/content/ai/ (mirroring the repository path)
   therefore made the editor ask for /ooplug/content/v1/plugins.js, which 404s — and
   the only symptom was window.Asc.plugin undefined inside the plugin frame and no AI
   tab. Measured live, 2026-08-28. So the plugin folder must sit DIRECTLY under the
   served root, exactly as ONLYOFFICE installs a .plugin into sdkjs-plugins/<name>/.
"

got_guid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("guid",""))' \
            "$CANDIDATE/$PLUGIN_CONFIG_REL" 2>/dev/null || echo "")"
[[ "$got_guid" == "$PLUGIN_GUID" ]] \
  || die "config.json guid is ${got_guid:-<unreadable>}, expected ${PLUGIN_GUID}.
       The autostart list in bridge/panel/oo.html is keyed on that guid."
got_ver="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' \
           "$CANDIDATE/$PLUGIN_CONFIG_REL" 2>/dev/null || echo "")"
[[ "$got_ver" == "$PLUGIN_VERSION" ]] \
  || warn "config.json version is ${got_ver}, the pin recorded ${PLUGIN_VERSION}"

files=$(find "$CANDIDATE/ai" "$CANDIDATE/v1" -type f | wc -l | tr -d ' ')
size=$(du -sh "$CANDIDATE" 2>/dev/null | awk '{print $1}')
say "landed: ${files} files, ${size}"

cat > "$CANDIDATE/SOURCES.txt" <<SRC
ONLYOFFICE AI plugin — vendored for the LOffice ribbon.

LICENCE: AGPL-3.0 (GUI elements and documentation: CC-BY-SA-4.0), (c) Ascensio
System SIA. This plugin is UNMODIFIED upstream: \`ai.plugin\` is upstream's own
deploy archive, unzipped byte-for-byte, and the three shared SDK files are fetched
verbatim. MOT Deck patches nothing. It is served read-only at /ooplug/* and
driven only through published surfaces: the editor's own
\`editorConfig.plugins.pluginsData\` loader, and the plugin's own localStorage
settings keys (which is how its Settings UI stores providers too).

plugin  ${REPO} @ ${COMMIT}
  file    sdkjs-plugins/${PLUGIN_REL}
  version ${PLUGIN_VERSION}   guid ${PLUGIN_GUID}
  source  https://github.com/${REPO}/blob/${COMMIT}/sdkjs-plugins/${PLUGIN_REL}
  code    https://github.com/${REPO}/tree/${COMMIT}/sdkjs-plugins/content/ai
  sha256  ${PLUGIN_SHA256}

sdk     ${REPO} @ ${COMMIT}  (sdkjs-plugins/v1)
  plugins.js     ${SDK_SHA_plugins_js}
  plugins-ui.js  ${SDK_SHA_plugins_ui_js}
  plugins.css    ${SDK_SHA_plugins_css}
  code    https://github.com/${REPO}/tree/${COMMIT}/sdkjs-plugins/v1

upstream (the plugin marketplace repository)
  https://github.com/${REPO}

If this MOT Deck build is ever distributed to anyone else, the About surface must name
ONLYOFFICE + AGPL-3.0 and link these exact pins, and any modification made to the
plugin must be published. See docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md, AGPL ruling.
SRC


cat > "$CANDIDATE/INSTALLED" <<EOF
schema 1
date $(date -u '+%Y-%m-%dT%H:%M:%SZ')
repo ${REPO}
commit ${COMMIT}
plugin_rel ${PLUGIN_REL}
plugin_version ${PLUGIN_VERSION}
plugin_guid ${PLUGIN_GUID}
plugin_sha256 ${PLUGIN_SHA256}
sdk_files ${SDK_FILES[*]}
files ${files}
licence AGPL-3.0
EOF
# Invalidate the served receipt before replacing any files; publish its successor last.
python3 "$PUBLISHER" publish "$DEST" "$STAGE"

say "done. The bridge picks this up with no restart (bridge/ooai.py reads the stamp"
say "per request); ship.sh is still the way to push code changes."
report_state
