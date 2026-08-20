#!/usr/bin/env bash
# fetch_vendor_assets.sh — download the pinned, self-hosted browser libraries that the
# Mission Control panel's artifact renderer (Phase 2) loads from /assets/vendor/.
#
# WHY: everything in the harness must work FULLY OFFLINE — no runtime CDN. These libs
# are fetched ONCE (here, on a Mac with network) into bridge/panel/assets/vendor/, then
# the bridge serves them same-origin at /assets/vendor/<lib>. The dir is gitignored
# (a runtime/build asset, like the venvs); the FAT build bundles it into the seed.
#
# Idempotent: skips a file that already exists. Pass --force to re-download everything.
# All assets are MIT/Apache/BSD licensed. Pins are exact for reproducibility.
#
# Run:  ./scripts/fetch_vendor_assets.sh          (fetch missing)
#       ./scripts/fetch_vendor_assets.sh --force  (re-fetch all)
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="bridge/panel/assets/vendor"
mkdir -p "$DEST"

FORCE=0
for a in "$@"; do [[ "$a" == "--force" ]] && FORCE=1; done

# Pinned versions (bump deliberately + re-test the renderer).
BABEL_V="7.26.4"       # @babel/standalone — JSX/TSX transform in the sandboxed iframe
REACT_V="18.3.1"       # react + react-dom UMD production
PRISM_V="1.29.0"       # syntax highlighting (code + fenced md blocks)
MDIT_V="14.1.0"        # markdown-it
PURIFY_V="3.2.4"       # DOMPurify — sanitize md/HTML before it touches the host DOM
# Tailwind Play CDN — the standalone in-browser JIT build model HTML pages use via
# <script src="https://cdn.tailwindcss.com">. Self-hosted so those pages render STYLED
# OFFLINE. ⚠️ Play CDN is "not for production" (Tailwind's own note) — fine for local
# artifact PREVIEW only. Served same-origin; the panel rewrites cdn.tailwindcss.com → this.
TAILWIND_V="3.4.16"    # Tailwind Play CDN (versioned build)
MERMAID_V="11.4.1"     # mermaid (MIT) — diagram artifacts; UMD/IIFE dist build for <script src> use
CM_V="5.65.18"         # CodeMirror 5 (MIT) — canvas editor (Fable decision: v5 UMD, not v6 ESM)
# xterm.js (MIT) — the terminal widget the AIDER tab renders into (bridge/panel/aider.html).
# Same versions Hermes itself ships (vendor/hermes/web/package.json), i.e. a pair already
# proven against a raw-bytes PTY websocket. UMD `lib/` builds, loaded with <script src>.
XTERM_V="6.0.0"
XTERM_FIT_V="0.11.0"   # @xterm/addon-fit — cols/rows from the element size

# ── Univer (Apache-2.0) — the OFFICE lane's spreadsheet surface ───────────────
# Univer ships UMD builds explicitly so they can be "downloaded for distribution via
# your own server" (docs.univer.ai → Import Univer via CDN); that is exactly the
# fetch-once-serve-ourselves shape everything above already uses, and is why the
# office lane needs no new process, port or component.
#
# THE PIN LIVES IN harness.yaml (`build.univer_pin`) — read below with the same awk
# one-liner install_llamacpp.sh uses, so a bump is one edit in the manifest. The value
# here is only the fallback when the manifest cannot be read.
# ⚠️ Do NOT move to React 19: the UMD bundle carries a react-polyfill prelude and the
# vendor docs warn React 19 needs shims. react/react-dom 18.3.1 (already fetched above)
# and rxjs are PEER dependencies — Univer's UMD expects the globals React, ReactDOM
# and rxjs to exist before it loads.
UNIVER_V_DEFAULT="0.25.1"
RXJS_V="7.8.2"         # rxjs UMD — Univer peer dep (>=7.0.0)

UNIVER_V="$(awk '/^build:/{b=1;next} b&&/^[a-z]/{b=0} b&&/^[[:space:]]*univer_pin:/{
  gsub(/.*univer_pin:[[:space:]]*"?/,""); gsub(/".*/,""); gsub(/[[:space:]]*#.*/,"");
  gsub(/[[:space:]]+$/,""); print; exit}' harness.yaml 2>/dev/null || true)"
if [[ -z "${UNIVER_V:-}" ]]; then
  echo "[vendor] WARN: build.univer_pin not readable from harness.yaml — using ${UNIVER_V_DEFAULT}"
  UNIVER_V="$UNIVER_V_DEFAULT"
fi
echo "[vendor] univer pin: ${UNIVER_V}"

CDN="https://cdn.jsdelivr.net/npm"

# Prism is fetched as ONE combined file (core + a curated language set, in dependency
# order) via jsDelivr's /combine endpoint — a single offline file, no runtime autoloader.
PRISM_COMBINE="https://cdn.jsdelivr.net/combine/\
npm/prismjs@${PRISM_V}/prism.min.js,\
npm/prismjs@${PRISM_V}/components/prism-markup-templating.min.js,\
npm/prismjs@${PRISM_V}/components/prism-clike.min.js,\
npm/prismjs@${PRISM_V}/components/prism-javascript.min.js,\
npm/prismjs@${PRISM_V}/components/prism-typescript.min.js,\
npm/prismjs@${PRISM_V}/components/prism-jsx.min.js,\
npm/prismjs@${PRISM_V}/components/prism-tsx.min.js,\
npm/prismjs@${PRISM_V}/components/prism-json.min.js,\
npm/prismjs@${PRISM_V}/components/prism-yaml.min.js,\
npm/prismjs@${PRISM_V}/components/prism-python.min.js,\
npm/prismjs@${PRISM_V}/components/prism-bash.min.js,\
npm/prismjs@${PRISM_V}/components/prism-go.min.js,\
npm/prismjs@${PRISM_V}/components/prism-rust.min.js,\
npm/prismjs@${PRISM_V}/components/prism-c.min.js,\
npm/prismjs@${PRISM_V}/components/prism-cpp.min.js,\
npm/prismjs@${PRISM_V}/components/prism-css.min.js,\
npm/prismjs@${PRISM_V}/components/prism-sql.min.js,\
npm/prismjs@${PRISM_V}/components/prism-markup.min.js,\
npm/prismjs@${PRISM_V}/components/prism-ruby.min.js,\
npm/prismjs@${PRISM_V}/components/prism-java.min.js,\
npm/prismjs@${PRISM_V}/components/prism-toml.min.js"

# CodeMirror 5 language modes, combined into ONE offline file in dependency order
# (jsx needs javascript+xml; htmlmixed needs xml+javascript+css). Same /combine
# pattern as Prism above.
CM_MODES_COMBINE="https://cdn.jsdelivr.net/combine/\
npm/codemirror@${CM_V}/mode/xml/xml.min.js,\
npm/codemirror@${CM_V}/mode/css/css.min.js,\
npm/codemirror@${CM_V}/mode/javascript/javascript.min.js,\
npm/codemirror@${CM_V}/mode/jsx/jsx.min.js,\
npm/codemirror@${CM_V}/mode/htmlmixed/htmlmixed.min.js,\
npm/codemirror@${CM_V}/mode/markdown/markdown.min.js,\
npm/codemirror@${CM_V}/mode/python/python.min.js,\
npm/codemirror@${CM_V}/mode/yaml/yaml.min.js"

# name|url   (name = filename written into $DEST)
ASSETS=(
  "babel.min.js|${CDN}/@babel/standalone@${BABEL_V}/babel.min.js"
  "react.production.min.js|${CDN}/react@${REACT_V}/umd/react.production.min.js"
  "react-dom.production.min.js|${CDN}/react-dom@${REACT_V}/umd/react-dom.production.min.js"
  "markdown-it.min.js|${CDN}/markdown-it@${MDIT_V}/dist/markdown-it.min.js"
  "purify.min.js|${CDN}/dompurify@${PURIFY_V}/dist/purify.min.js"
  "prism.css|${CDN}/prismjs@${PRISM_V}/themes/prism-tomorrow.min.css"
  "prism.min.js|${PRISM_COMBINE}"
  "tailwind.play.js|https://cdn.tailwindcss.com/${TAILWIND_V}"
  "mermaid.min.js|${CDN}/mermaid@${MERMAID_V}/dist/mermaid.min.js"
  "codemirror.min.css|${CDN}/codemirror@${CM_V}/lib/codemirror.min.css"
  "codemirror.min.js|${CDN}/codemirror@${CM_V}/lib/codemirror.min.js"
  "codemirror-modes.min.js|${CM_MODES_COMBINE}"
  "xterm.css|${CDN}/@xterm/xterm@${XTERM_V}/css/xterm.css"
  "xterm.js|${CDN}/@xterm/xterm@${XTERM_V}/lib/xterm.js"
  "xterm-addon-fit.js|${CDN}/@xterm/addon-fit@${XTERM_FIT_V}/lib/addon-fit.js"
  # Univer — load order matters and is fixed in bridge/panel/office.html:
  #   react, react-dom (above), rxjs, presets, preset-sheets-core, the locale.
  # Globals, verified by reading the pinned bundles rather than the docs:
  #   presets            → UniverPresets.createUniver / LocaleType / defaultTheme
  #   preset-sheets-core → UniverPresetSheetsCore.UniverSheetsCorePreset
  #   locales/en-US      → UniverPresetSheetsCoreEnUS
  "univer/rxjs.umd.min.js|${CDN}/rxjs@${RXJS_V}/dist/bundles/rxjs.umd.min.js"
  "univer/presets.umd.js|${CDN}/@univerjs/presets@${UNIVER_V}/lib/umd/index.js"
  "univer/preset-sheets-core.umd.js|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/umd/index.js"
  "univer/preset-sheets-core.css|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/index.css"
  "univer/preset-sheets-core.en-US.js|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/umd/locales/en-US.js"
)

fetch() {
  local name="$1" url="$2" out="$DEST/$1"
  # A name may carry one subdirectory (univer/…) — make it before writing.
  mkdir -p "$(dirname "$out")"
  if [[ $FORCE -eq 0 && -s "$out" ]]; then
    echo "[vendor] have $name — skip"
    return 0
  fi
  echo "[vendor] fetching $name"
  # -f fail on HTTP error, -L follow redirects, -S show errors, --retry for flaky CDNs
  curl -fL -S --retry 3 --retry-delay 2 -o "$out.tmp" "$url" \
    || { echo "ERROR: failed to fetch $name from $url"; rm -f "$out.tmp"; exit 1; }
  [[ -s "$out.tmp" ]] || { echo "ERROR: $name downloaded empty from $url"; rm -f "$out.tmp"; exit 1; }
  mv "$out.tmp" "$out"
}

for entry in "${ASSETS[@]}"; do
  fetch "${entry%%|*}" "${entry#*|}"
done

echo "[vendor] done → $DEST"
ls -la "$DEST"
