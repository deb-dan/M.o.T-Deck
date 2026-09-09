#!/usr/bin/env bash
# fetch_vendor_assets.sh — download the pinned, self-hosted browser libraries that the
# Mission Control panel's artifact renderer (Phase 2) loads from /assets/vendor/.
#
# WHY: everything in MOT Deck must work FULLY OFFLINE — no runtime CDN. These libs
# are fetched ONCE (here, on a Mac with network) into bridge/panel/assets/vendor/, then
# the bridge serves them same-origin at /assets/vendor/<lib>. The dir is gitignored
# (a runtime/build asset, like the venvs); the FAT build bundles it into the seed.
#
# Idempotent: re-hashes a file that already exists and reuses it only on an exact match.
# Pass --force to deliberately replace every asset after the new bytes verify.
# All assets are MIT/Apache/BSD licensed. Pins are exact for reproducibility.
#
# Run:  ./scripts/fetch_vendor_assets.sh          (fetch missing)
#       ./scripts/fetch_vendor_assets.sh --force  (re-fetch all)
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${VENDOR_ASSET_DEST:-bridge/panel/assets/vendor}"
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
# THE PIN LIVES IN motdeck.yaml (`build.univer_pin`) — read below with the same awk
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
  gsub(/[[:space:]]+$/,""); print; exit}' motdeck.yaml 2>/dev/null || true)"
if [[ -z "${UNIVER_V:-}" ]]; then
  echo "[vendor] WARN: build.univer_pin not readable from motdeck.yaml — using ${UNIVER_V_DEFAULT}"
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

# name|sha256|url   (name = filename written into $DEST). The version in a URL is
# provenance; the digest is the byte identity. Both move together on a deliberate bump.
ASSETS=(
  "babel.min.js|a12872ea8da3d29b2a296c51bfac7c482e81419c755f2207a49ad9b77200f4ea|${CDN}/@babel/standalone@${BABEL_V}/babel.min.js"
  "react.production.min.js|d949f1c3687aedadcedac85261865f29b17cd273997e7f6b2bfc53b2f9d4c4dd|${CDN}/react@${REACT_V}/umd/react.production.min.js"
  "react-dom.production.min.js|35f4f974f4b2bcd44da73963347f8952e341f83909e4498227d4e26b98f66f0d|${CDN}/react-dom@${REACT_V}/umd/react-dom.production.min.js"
  "markdown-it.min.js|38c70a1e7ca91ab40e2d9e6e60129851a717ed1c7d4acbbdd41bf9503791cf68|${CDN}/markdown-it@${MDIT_V}/dist/markdown-it.min.js"
  "purify.min.js|8eb41b658831fab175fad9bcd00fcb2d84e0ed3a25a55053d4ecd4444b8b43a0|${CDN}/dompurify@${PURIFY_V}/dist/purify.min.js"
  "prism.css|1b15fe2971998a048aebb60f26f6eed76122071db9ef3b995abd003224f52a98|${CDN}/prismjs@${PRISM_V}/themes/prism-tomorrow.min.css"
  "prism.min.js|6d58785540e42887513ea00166cbd7d7d515e8bd40b63b340eecb50e6cfdb990|${PRISM_COMBINE}"
  "tailwind.play.js|3f81aa7f6ecdb1acc14c202e513dfee00b6c7703cd81ce1be25bf5215a92e8cb|https://cdn.tailwindcss.com/${TAILWIND_V}"
  "mermaid.min.js|a43bc1afd446f9c4cc66ac5dd45d02e8d65e26fc5344ec0ef787f88d6ddb6f9e|${CDN}/mermaid@${MERMAID_V}/dist/mermaid.min.js"
  "codemirror.min.css|d8fddcfca0ccaeea67ddd557d22340530a1daae8a09843e8f4c25d7def06efa8|${CDN}/codemirror@${CM_V}/lib/codemirror.min.css"
  "codemirror.min.js|9eb3d93e642327e5f350342a60e6810aa1543644ba003e41bad2f372ead3b372|${CDN}/codemirror@${CM_V}/lib/codemirror.min.js"
  "codemirror-modes.min.js|9da25ebe9ae26276b66716e24923d2ef09d9f1f10d1c46c0e9a082a6b6650557|${CM_MODES_COMBINE}"
  "xterm.css|854a7c0fb70e8b1a083c16797ab827299fb18744f5ad34f227b48337e33293c6|${CDN}/@xterm/xterm@${XTERM_V}/css/xterm.css"
  "xterm.js|14903579ff54664cd72f8e8699e6961a6272c21863ec1c3b118cdc8af5d4a972|${CDN}/@xterm/xterm@${XTERM_V}/lib/xterm.js"
  "xterm-addon-fit.js|ba3ea256ce0620a0992a197d6c9baea64823fc93d8da07a9e366ca9943c18527|${CDN}/@xterm/addon-fit@${XTERM_FIT_V}/lib/addon-fit.js"
  # Univer — load order matters and is fixed in bridge/panel/office.html:
  #   react, react-dom (above), rxjs, presets, preset-sheets-core, the locale.
  # Globals, verified by reading the pinned bundles rather than the docs:
  #   presets            → UniverPresets.createUniver / LocaleType / defaultTheme
  #   preset-sheets-core → UniverPresetSheetsCore.UniverSheetsCorePreset
  #   locales/en-US      → UniverPresetSheetsCoreEnUS
  "univer/rxjs.umd.min.js|2152e8a794982170a4c1dae32a74e31a81218fd74781c27b0d628a02bf532413|${CDN}/rxjs@${RXJS_V}/dist/bundles/rxjs.umd.min.js"
  "univer/presets.umd.js|089c8d7f47f3bc69d47605025ed60900dc25ad5927f9c2a7ba921becb2a05d6c|${CDN}/@univerjs/presets@${UNIVER_V}/lib/umd/index.js"
  "univer/preset-sheets-core.umd.js|71a3007e8796b7073b1f0af3e0a2a23d3282fa74a7493d9b915d7a0c24c57de2|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/umd/index.js"
  "univer/preset-sheets-core.css|608c124418bdca0a976cf152e7c35910556d9de196a0a27d55d9e34f4098e7ba|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/index.css"
  "univer/preset-sheets-core.en-US.js|0a1b2e1e3b3d0e59513c890edb88a1bbc02d76f6905bba2a67255055d4b5f938|${CDN}/@univerjs/preset-sheets-core@${UNIVER_V}/lib/umd/locales/en-US.js"
)

fetch() {
  local name="$1" expected="$2" url="$3" out="$DEST/$1" got
  # A name may carry one subdirectory (univer/…) — make it before writing.
  mkdir -p "$(dirname "$out")"
  if [[ $FORCE -eq 0 && -s "$out" ]]; then
    got=$(shasum -a 256 "$out" | awk '{print $1}')
    if [[ "$got" == "$expected" ]]; then
      echo "[vendor] have $name — sha256 verified"
      return 0
    fi
    echo "ERROR: cached $name has sha256 $got; expected $expected" >&2
    echo "       Refusing to trust or overwrite it. Inspect, then re-run with --force." >&2
    exit 1
  fi
  echo "[vendor] fetching $name"
  # -f fail on HTTP error, -L follow redirects, -S show errors, --retry for flaky CDNs
  curl -fL -S --retry 3 --retry-delay 2 -o "$out.tmp" "$url" \
    || { echo "ERROR: failed to fetch $name from $url"; rm -f "$out.tmp"; exit 1; }
  [[ -s "$out.tmp" ]] || { echo "ERROR: $name downloaded empty from $url"; rm -f "$out.tmp"; exit 1; }
  got=$(shasum -a 256 "$out.tmp" | awk '{print $1}')
  [[ "$got" == "$expected" ]] || {
    echo "ERROR: $name sha256 MISMATCH (expected $expected, got $got)" >&2
    rm -f "$out.tmp"; exit 1; }
  mv "$out.tmp" "$out"
}

for entry in "${ASSETS[@]}"; do
  name="${entry%%|*}"
  rest="${entry#*|}"
  digest="${rest%%|*}"
  url="${rest#*|}"
  fetch "$name" "$digest" "$url"
done

echo "[vendor] done → $DEST"
ls -la "$DEST"
