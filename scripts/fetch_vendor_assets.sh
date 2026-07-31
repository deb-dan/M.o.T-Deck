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
)

fetch() {
  local name="$1" url="$2" out="$DEST/$1"
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
