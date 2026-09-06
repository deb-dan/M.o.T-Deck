#!/usr/bin/env bash
# ONLYOFFICE static-editors PROBE — throwaway, adopts nothing.
#
#   ./scripts/probe_onlyoffice.sh personal    fernfei/OnlyofficePersonal (a finished static site)
#   ./scripts/probe_onlyoffice.sh cryptpad    CryptPad's prebuilt onlyoffice-editor.zip + x2t.zip
#   ./scripts/probe_onlyoffice.sh both        run both, then serve
#   ./scripts/probe_onlyoffice.sh serve       just start the local server again
#   ./scripts/probe_onlyoffice.sh clean       delete every byte this made
#
# It answers ONE question, the one docs/research/2026-08-21-office-alternatives-deep.md
# §9 says decides the whole office lane: do ONLYOFFICE's client-side editors (sdkjs +
# web-apps) and x2t.wasm actually WORK in WebKit on this Mac, and do they round-trip a
# real .xlsx? Every fidelity claim in that report is read from source; nothing has been
# run on macOS and no document has been round-tripped through anything.
#
# Nothing here is a component: no port is registered, no manifest key is touched, no
# venv is created, vendor/ is never written to, bridge/panel/assets is never written to.
# Everything lands in data/office-probe/ (gitignored) and one rm -rf removes it.
#
# Fill the numbers into docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

CMD="${1:-}"

PROBE="$ROOT/data/office-probe"
OO_ROOT="$PROBE/onlyoffice"          # cryptpad track  -> dist/v9/... + dist/x2t/...
PERSONAL="$PROBE/personal"           # fernfei track   -> office.html
ZIPS="$PROBE/zips"
PORT="${PORT:-8787}"
NEED_GB=5

# ── pins ─────────────────────────────────────────────────────────────────────
# The DEFAULT pair is the one CryptPad's own install-onlyoffice.sh ships and tests
# TOGETHER (editor v9 + x2t v7.3+1). Newer tags exist on both repos; a probe is not the
# place to go off-piste, and the whole value of this pair is that a large deployed
# project runs it every day. Override deliberately:
#     OO_EDITOR_TAG=v9.3.0+0 ./scripts/probe_onlyoffice.sh cryptpad
#
# ⚠️ UNRESOLVED FROM THE SANDBOX: the deep-alternatives report read the editor pin as
# `v9.2.0.119+5` and said the newest x2t is `v9.3.0+0` (2026-04-24, x2t 9.3.0.140);
# search results for the SAME file read `v9.2.0.119+3` / `v7.3+1`. api.github.com and
# raw.githubusercontent were both unreachable here, so neither could be settled. The
# script therefore (a) defaults to the +3 / v7.3+1 pair, (b) ASKS GitHub at run time
# what the latest tag is and prints it without switching, and (c) records the tag and
# the sha256/sha512 it actually downloaded. Those recorded values are the pin if this
# passes — exactly how measure_music.sh handled the unresolvable acestep sha.
EDITOR_REPO="cryptpad/onlyoffice-editor"
EDITOR_TAG="${OO_EDITOR_TAG:-v9.2.0.119+3}"
EDITOR_ASSET="onlyoffice-editor.zip"
X2T_REPO="cryptpad/onlyoffice-x2t-wasm"
X2T_TAG="${OO_X2T_TAG:-v7.3+1}"
X2T_ASSET="x2t.zip"
# CryptPad's installer carries the authoritative sha512 for each asset. We do not
# hardcode a hash we could not read; we fetch that script at run time and check whether
# OUR computed hash appears in it. Format-agnostic, and it cannot false-positive.
INSTALLER_URL="https://raw.githubusercontent.com/cryptpad/cryptpad/main/install-onlyoffice.sh"

# fernfei/OnlyofficePersonal — a static site that already wires the ONLYOFFICE editors
# to x2t.wasm with no server (office.html: new / open local file / edit / save back).
# ⚠️ AGPL-3.0, and the provenance of its bundled vendor/{web-apps,sdkjs,fonts} is
# UNVERIFIED — the report flags exactly this class (Developer-Edition assets exported
# from a Docker image) as a licensing hazard. It is used HERE as a measurement vehicle
# only. Adoption would vendor CryptPad's release zips, whose lineage is clean.
PERSONAL_REPO="https://github.com/fernfei/OnlyofficePersonal.git"
PERSONAL_BRANCH="${OO_PERSONAL_BRANCH:-main}"

say()  { echo "[oo-probe] $*"; }
warn() { echo "[oo-probe] WARN: $*" >&2; }
die()  { echo "[oo-probe] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
usage: ./scripts/probe_onlyoffice.sh personal|cryptpad|both|serve|clean

  personal   clone fernfei/OnlyofficePersonal — a FINISHED static ONLYOFFICE site
             (office.html). This is the fastest honest answer to "does the real
             ribbon work in WebKit on this Mac, and can it round-trip my .xlsx?"
  cryptpad   download CryptPad's prebuilt onlyoffice-editor.zip + x2t.zip — the
             artifacts we would actually VENDOR. Records tag + sha256/sha512, checks
             them against CryptPad's own installer, unzips into CryptPad's documented
             layout, and reports what really landed (the layout is unknowable offline).
  both       personal, then cryptpad, then serve.
  serve      start the local static server on 127.0.0.1:PORT (default 8787).
  clean      rm -rf data/office-probe

env: PORT, OO_EDITOR_TAG, OO_X2T_TAG, OO_PERSONAL_BRANCH
USAGE
  exit 1
}

# ── preflight ────────────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || die "$1 not found — $2"; }

resolve_py() {
  local p
  for p in "$ROOT/data/python-standalone/bin/python3" \
           "$(command -v python3 || true)" \
           "$(command -v python3.12 || true)" \
           "$(command -v python3.11 || true)"; do
    [[ -n "$p" && -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}
PY=""

preflight() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "not macOS. The download/layout half still works, but the MEASUREMENT is"
    warn "about WebKit specifically — every one of the office lane's bugs has lived"
    warn "there. A pass on another engine decides nothing."
  fi
  need curl "it ships with macOS; check your PATH"
  need unzip "it ships with macOS; check your PATH"
  need shasum "it ships with macOS; check your PATH"
  PY="$(resolve_py)" || die "no python3 found — xcode-select --install"

  local free_gb
  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (need about ${NEED_GB}GB)"
  if [[ "$free_gb" -lt "$NEED_GB" ]]; then
    die "not enough free disk — the editor bundle alone is several hundred MB unzipped."
  fi
  mkdir -p "$PROBE" "$ZIPS"
}

# ── download helper ──────────────────────────────────────────────────────────
# GitHub release tags here contain a '+'. It is legal in a URL path segment and
# CryptPad's own installer sends it literally, so we do too — with a percent-encoded
# retry, because a 404 from an encoding difference would look identical to a wrong pin.
dl() {
  local url="$1" dest="$2" alt="${3:-}"
  say "downloading ${url}"
  if curl -fL -# --retry 3 --retry-delay 2 -o "${dest}.part" "$url"; then
    mv "${dest}.part" "$dest"; return 0
  fi
  rm -f "${dest}.part"
  if [[ -n "$alt" ]]; then
    warn "that URL failed; retrying percent-encoded"
    say "downloading ${alt}"
    if curl -fL -# --retry 3 --retry-delay 2 -o "${dest}.part" "$alt"; then
      mv "${dest}.part" "$dest"; return 0
    fi
    rm -f "${dest}.part"
  fi
  return 1
}

latest_tag() {
  curl -fsSL --max-time 20 "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
    | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1
}

INSTALLER_SRC=""
CHECKS="$PROBE/CHECKSUMS.txt"

record_hashes() {
  local file="$1" label="$2"
  local s256 s512
  s256=$(shasum -a 256 "$file" | awk '{print $1}')
  s512=$(shasum -a 512 "$file" | awk '{print $1}')
  {
    echo "$label"
    echo "  file    $(basename "$file")  ($(wc -c <"$file" | tr -d ' ') bytes)"
    echo "  sha256  $s256"
    echo "  sha512  $s512"
  } >> "$CHECKS"
  if [[ -n "$INSTALLER_SRC" ]] && printf '%s' "$INSTALLER_SRC" | grep -qi -- "$s512"; then
    say "  sha512 VERIFIED — this exact byte string appears in CryptPad's own installer"
    echo "  verify  MATCHES cryptpad/install-onlyoffice.sh" >> "$CHECKS"
  else
    warn "  sha512 NOT confirmed against CryptPad's installer."
    warn "  That is expected if you overrode the tag (upstream pins a different one),"
    warn "  and is otherwise worth a look before anything is vendored:"
    warn "    ${INSTALLER_URL}"
    echo "  verify  NOT FOUND in cryptpad/install-onlyoffice.sh (see the warning above)" >> "$CHECKS"
  fi
  echo "" >> "$CHECKS"
}

# ── track 1: fernfei/OnlyofficePersonal ──────────────────────────────────────
do_personal() {
  preflight
  need git "xcode-select --install"

  echo ""
  say "⚠️  LICENCE, said before anything is downloaded:"
  say "    fernfei/OnlyofficePersonal is AGPL-3.0, and the ONLYOFFICE editors it"
  say "    bundles are AGPL-3.0 too. The provenance of ITS copies is unverified."
  say "    This is a MEASUREMENT vehicle. Adoption vendors CryptPad's zips instead,"
  say "    and the AGPL question is a Fable ruling that has not been made yet."
  echo ""

  if [[ ! -d "$PERSONAL/.git" ]]; then
    say "cloning OnlyofficePersonal (${PERSONAL_BRANCH}, shallow)..."
    git clone --depth 1 --branch "$PERSONAL_BRANCH" "$PERSONAL_REPO" "$PERSONAL" \
      || die "clone failed (branch ${PERSONAL_BRANCH} wrong? try OO_PERSONAL_BRANCH=master)"
  else
    say "reusing existing clone at data/office-probe/personal"
  fi

  local sha
  sha=$(git -C "$PERSONAL" rev-parse HEAD)
  echo "$sha" > "$PROBE/personal.sha"
  say "OnlyofficePersonal commit: ${sha}"
  say "  (recorded in data/office-probe/personal.sha — quote it in the runbook)"

  [[ -f "$PERSONAL/office.html" ]] \
    || die "no office.html in the clone — the repo layout changed. Look at $PERSONAL"

  # git-lfs pointer trap: a plain clone of an LFS repo yields ~130-byte text stubs and
  # the editor then fails with a WASM error that looks like a WebKit problem.
  local stub
  stub=$(find "$PERSONAL" -name '*.wasm' -size -2k 2>/dev/null | head -1 || true)
  if [[ -n "$stub" ]] && head -c 40 "$stub" | grep -q 'git-lfs'; then
    die "this repo uses git-lfs and the .wasm files are pointer stubs.
       Fix: brew install git-lfs && git lfs install && git -C \"$PERSONAL\" lfs pull"
  fi

  say "size on disk: $(du -sh "$PERSONAL" 2>/dev/null | awk '{print $1}')"
  write_support_files
  say "track ready:  http://127.0.0.1:${PORT}/personal/office.html"
}

# ── track 2: CryptPad's prebuilt zips ────────────────────────────────────────
do_cryptpad() {
  preflight

  echo ""
  say "⚠️  LICENCE: the ONLYOFFICE editors and x2t are AGPL-3.0. Serving AGPL JS/WASM"
  say "    from our own bridge inside our own page is a CLOSER coupling than SearXNG"
  say "    over HTTP. Fable rules on that before any of this is vendored; this probe"
  say "    only measures whether it works at all."
  echo ""

  say "fetching CryptPad's installer for its authoritative checksums..."
  INSTALLER_SRC="$(curl -fsSL --max-time 20 "$INSTALLER_URL" || true)"
  if [[ -z "$INSTALLER_SRC" ]]; then
    warn "could not fetch ${INSTALLER_URL} — hashes will be RECORDED but not verified."
  fi

  local lt
  lt="$(latest_tag "$EDITOR_REPO" || true)"
  if [[ -n "$lt" && "$lt" != "$EDITOR_TAG" ]]; then
    say "note: ${EDITOR_REPO} latest release is ${lt}; this probe pins ${EDITOR_TAG} (CryptPad's tested pair)"
  fi
  lt="$(latest_tag "$X2T_REPO" || true)"
  if [[ -n "$lt" && "$lt" != "$X2T_TAG" ]]; then
    say "note: ${X2T_REPO} latest release is ${lt}; this probe pins ${X2T_TAG} (CryptPad's tested pair)"
  fi

  : > "$CHECKS"
  {
    echo "ONLYOFFICE probe — what was actually downloaded"
    echo "date    $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""
  } >> "$CHECKS"

  local ez xz eurl xurl
  ez="$ZIPS/${EDITOR_ASSET}"
  xz="$ZIPS/${X2T_ASSET}"
  eurl="https://github.com/${EDITOR_REPO}/releases/download/${EDITOR_TAG}/${EDITOR_ASSET}"
  xurl="https://github.com/${X2T_REPO}/releases/download/${X2T_TAG}/${X2T_ASSET}"

  if [[ ! -s "$ez" ]]; then
    dl "$eurl" "$ez" "${eurl//+/%2B}" \
      || die "could not download the editor zip.
       Check the tag exists: https://github.com/${EDITOR_REPO}/releases
       Then re-run with OO_EDITOR_TAG=<tag>"
  else
    say "reusing ${EDITOR_ASSET} already in data/office-probe/zips"
  fi
  record_hashes "$ez" "editor  ${EDITOR_REPO} @ ${EDITOR_TAG}"

  if [[ ! -s "$xz" ]]; then
    dl "$xurl" "$xz" "${xurl//+/%2B}" \
      || die "could not download x2t.zip.
       Check the tag exists: https://github.com/${X2T_REPO}/releases
       Then re-run with OO_X2T_TAG=<tag>"
  else
    say "reusing ${X2T_ASSET} already in data/office-probe/zips"
  fi
  record_hashes "$xz" "x2t     ${X2T_REPO} @ ${X2T_TAG}"

  # CryptPad's documented layout: the editor into www/common/onlyoffice/dist/v9/ and
  # x2t into .../dist/x2t/ (the x2t path is version-independent — one converter serves
  # every editor version). We mirror it exactly so anything learned here transfers.
  local dv="$OO_ROOT/dist/v9" dx="$OO_ROOT/dist/x2t"
  rm -rf "$dv" "$dx"
  mkdir -p "$dv" "$dx"
  say "unzipping the editor into onlyoffice/dist/v9/ (this takes a moment)..."
  unzip -q -o "$ez" -d "$dv" || die "unzip of ${EDITOR_ASSET} failed"
  say "unzipping x2t into onlyoffice/dist/x2t/..."
  unzip -q -o "$xz" -d "$dx" || die "unzip of ${X2T_ASSET} failed"

  # Some releases wrap everything in a single top-level folder. Flatten that, otherwise
  # every path below gains a level nobody documented.
  flatten_single_dir "$dv"
  flatten_single_dir "$dx"

  say "unzipped size: $(du -sh "$OO_ROOT" 2>/dev/null | awk '{print $1}')"
  write_support_files
  say "track ready:  http://127.0.0.1:${PORT}/probe-x2t.html"
}

flatten_single_dir() {
  local d="$1" n inner
  n=$(find "$d" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')
  [[ "$n" == "1" ]] || return 0
  inner=$(find "$d" -mindepth 1 -maxdepth 1)
  [[ -d "$inner" ]] || return 0
  say "  (flattening single top-level dir $(basename "$inner"))"
  # shellcheck disable=SC2086
  ( shopt -s dotglob nullglob; mv "$inner"/* "$d"/ ) && rmdir "$inner" || true
}

# ── layout report + probe pages ──────────────────────────────────────────────
# The bundle layout could not be read from the sandbox, so it is DISCOVERED here and
# written to layout.json; both pages render from that file rather than from a guess.
write_layout() {
  "$PY" - "$PROBE" <<'PY'
import json, os, sys

probe = sys.argv[1]
out = {"tracks": {}, "entries": {}, "totals": {}}

def rel(p):
    return os.path.relpath(p, probe).replace(os.sep, "/")

def scan(root):
    files = 0
    size = 0
    hits = {"api_js": [], "editors": [], "x2t_js": [], "x2t_wasm": [],
            "index_html": [], "top": []}
    if not os.path.isdir(root):
        return None
    for name in sorted(os.listdir(root)):
        hits["top"].append(name)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            files += 1
            try:
                size += os.path.getsize(p)
            except OSError:
                pass
            r = rel(p)
            low = r.lower()
            if fn == "api.js" and "/api/documents/" in low:
                hits["api_js"].append(r)
            elif fn == "x2t.js":
                hits["x2t_js"].append(r)
            elif fn == "x2t.wasm":
                hits["x2t_wasm"].append(r)
            elif fn == "index.html":
                hits["index_html"].append(r)
                if "editor/main/" in low or "editor/mobile/" in low:
                    hits["editors"].append(r)
    for k in hits:
        hits[k] = sorted(hits[k])[:40]
    return {"files": files, "bytes": size, "hits": hits}

oo = scan(os.path.join(probe, "onlyoffice"))
if oo:
    out["tracks"]["cryptpad"] = {"root": "onlyoffice", **oo}
pe = scan(os.path.join(probe, "personal"))
if pe:
    entry = "personal/office.html"
    ok = os.path.isfile(os.path.join(probe, "personal", "office.html"))
    out["tracks"]["personal"] = {"root": "personal", "entry": entry if ok else None, **pe}

for name, key in (("personal.sha", "personal_sha"),):
    p = os.path.join(probe, name)
    if os.path.isfile(p):
        out["entries"][key] = open(p).read().strip()

out["totals"]["generated"] = True
with open(os.path.join(probe, "layout.json"), "w") as fh:
    json.dump(out, fh, indent=2)

for tname, t in out["tracks"].items():
    mb = t["bytes"] / 1048576.0
    print(f"[oo-probe] layout: {tname} -> {t['files']} files, {mb:.0f} MB")
    for k in ("api_js", "editors", "x2t_js", "x2t_wasm"):
        v = t["hits"].get(k) or []
        if v:
            print(f"[oo-probe]   {k}: {len(v)} -> {v[0]}")
PY
}

write_support_files() {
  write_serve_py
  write_index_html
  write_x2t_html
  write_layout
}

write_serve_py() {
  cat > "$PROBE/serve.py" <<'PYSERVE'
#!/usr/bin/env python3
"""Static server for the ONLYOFFICE probe. Loopback only. Deliberately NOT the bridge.

Why not `python3 -m http.server`: three things it does not do, each of which would make
a WebKit failure ambiguous.

1. MIME. WebAssembly.instantiateStreaming REFUSES a response that is not
   `application/wasm`, and whether the stdlib's mimetypes knows `.wasm`/`.woff2`
   depends on the Python build and on /etc/apache2/mime.types being present. Forced
   here so a MIME miss can never be mistaken for "WASM does not work in WebKit".
2. Caching. The office lane has already lost hours to a stale cached document
   (loffice-2026-08-21c). Everything is no-store.
3. Threads + keep-alive. The editor bundle is thousands of files; a single-threaded
   HTTP/1.0 server makes that look like a hang.

--isolate adds COOP/COEP (cross-origin isolation). Some ONLYOFFICE builds want
SharedArrayBuffer for threaded WASM; those headers enable it, at the price of blocking
any resource without CORP. Default OFF, because turning it on pre-emptively would trade
one failure mode for another. The runbook says when to reach for it.
"""
import argparse
import http.server
import os
import socketserver
import sys

FORCE_TYPES = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".eot": "application/vnd.ms-fontobject",
    ".bin": "application/octet-stream",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    isolate = False

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        if Handler.isolate:
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        try:
            n = int(code)
        except (TypeError, ValueError):
            n = 0
        mark = "" if 200 <= n < 400 else "  <-- NOT OK"
        sys.stderr.write(f"  {code}  {self.path}{mark}\n")

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")


Handler.extensions_map = dict(http.server.SimpleHTTPRequestHandler.extensions_map)
Handler.extensions_map.update(FORCE_TYPES)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8787")))
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--isolate", action="store_true",
                    help="send COOP/COEP (needed only if the console asks for SharedArrayBuffer)")
    args = ap.parse_args()
    Handler.isolate = args.isolate
    os.chdir(args.root)

    def factory(*a, **kw):
        return Handler(*a, directory=args.root, **kw)

    with Server(("127.0.0.1", args.port), factory) as httpd:
        print(f"serving {args.root}")
        print(f"  http://127.0.0.1:{args.port}/")
        if args.isolate:
            print("  cross-origin isolation: ON")
        print("  Ctrl-C to stop. Requests are logged below; a line marked NOT OK is evidence.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")


if __name__ == "__main__":
    main()
PYSERVE
  chmod +x "$PROBE/serve.py"
}

write_index_html() {
  cat > "$PROBE/index.html" <<'HTML'
<!doctype html>
<meta charset="utf-8">
<title>ONLYOFFICE probe</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: light }
  body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; padding: 28px 32px 60px; max-width: 900px; color: #1b1b1f; background: #fbfaf7 }
  h1 { font-size: 22px; margin: 0 0 4px }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .08em; margin: 30px 0 10px; color: #5a5550 }
  .sub { color: #6b6455; margin: 0 0 22px }
  .card { border: 1px solid #ddd8cd; border-radius: 10px; padding: 16px 18px; margin: 0 0 14px; background: #fff }
  .card h3 { margin: 0 0 6px; font-size: 16px }
  a.go { display: inline-block; margin-top: 10px; padding: 8px 14px; border-radius: 8px;
         background: #1b1b1f; color: #fff; text-decoration: none; font-weight: 600 }
  a.go.sec { background: #fff; color: #1b1b1f; border: 1px solid #bdb7aa }
  .warn { border-left: 3px solid #b8860b; background: #fdf7e6; padding: 10px 14px; margin: 0 0 18px; border-radius: 0 8px 8px 0 }
  code, pre { font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace }
  pre { background: #f2efe8; padding: 10px 12px; border-radius: 8px; overflow: auto }
  ul { padding-left: 20px } li { margin: 3px 0 }
  .miss { opacity: .55 }
  .tag { display: inline-block; font: 11px ui-monospace, Menlo, monospace; padding: 1px 6px;
         border-radius: 5px; background: #eae5da; margin-left: 6px }
  .ok { background: #dff0d8 } .no { background: #f6d9d9 }
</style>
<h1>ONLYOFFICE static-editors probe</h1>
<p class="sub">Throwaway. Nothing here is installed into MOT Deck. One
<code>rm -rf data/office-probe</code> removes all of it.</p>

<div class="warn">
  <b>Licence, up front.</b> The ONLYOFFICE editors and x2t are <b>AGPL-3.0</b>.
  Serving AGPL JS/WASM from our own page is a closer coupling than SearXNG-over-HTTP,
  and that ruling has <b>not</b> been made. This page measures whether it
  <i>works</i>; it does not decide whether we may ship it.
</div>

<h2>Tracks</h2>
<div id="tracks"></div>

<h2>What to look for</h2>
<ul>
  <li>Does the real ONLYOFFICE <b>ribbon</b> render (File / Home / Insert tabs, formula bar)?</li>
  <li>Can you create a sheet, type values and a formula, and <b>save/export .xlsx</b>?</li>
  <li>Does <b>importing one of your own .xlsx files</b> keep formulas, merges, formats?</li>
  <li>How long does it take to load, and what does Activity Monitor say about RAM?</li>
  <li>Open the Web Inspector console. A silent failure is still a failure.</li>
</ul>

<h2>Discovered layout</h2>
<pre id="layout">reading layout.json…</pre>

<script>
const el = (h) => { const d = document.createElement('div'); d.innerHTML = h; return d.firstElementChild; };
const TRACKS = document.getElementById('tracks');

function card(title, desc, href, note, primary) {
  const dead = !href;
  return el(`<div class="card">
    <h3>${title}${dead ? '<span class="tag no">not downloaded</span>' : '<span class="tag ok">ready</span>'}</h3>
    <div>${desc}</div>
    ${note ? `<div style="margin-top:8px;color:#6b6455">${note}</div>` : ''}
    ${dead ? '' : `<a class="go ${primary ? '' : 'sec'}" href="${href}">${primary ? 'Open the editor' : 'Open'}</a>`}
  </div>`);
}

fetch('layout.json', { cache: 'no-store' })
  .then((r) => r.json())
  .then((L) => {
    const p = L.tracks && L.tracks.personal;
    TRACKS.appendChild(card(
      'A · OnlyofficePersonal (the go/no-go)',
      'A finished static ONLYOFFICE site: new document, open a local file, edit, save back. Word / Excel / PPT / PDF.',
      p && p.entry ? p.entry : null,
      p ? `${p.files} files, ${(p.bytes / 1048576).toFixed(0)} MB. Commit <code>${(L.entries && L.entries.personal_sha || '').slice(0, 12)}</code>. ⚠️ AGPL-3.0; provenance of its bundled ONLYOFFICE copies is unverified — measurement vehicle only.`
        : 'Run <code>./scripts/probe_onlyoffice.sh personal</code> to fetch it.',
      true));

    const c = L.tracks && L.tracks.cryptpad;
    const editors = (c && c.hits && c.hits.editors) || [];
    TRACKS.appendChild(card(
      'B · CryptPad prebuilt bundle (the artifacts we would vendor)',
      'x2t.wasm self-test, plus direct links to whatever editor shells the zip actually contains.',
      c ? 'probe-x2t.html' : null,
      c ? `${c.files} files, ${(c.bytes / 1048576).toFixed(0)} MB. sha256/sha512 in CHECKSUMS.txt.`
        : 'Run <code>./scripts/probe_onlyoffice.sh cryptpad</code> to fetch it.',
      false));

    if (editors.length) {
      const list = editors.map((e) => `<li><a href="${e}">${e}</a></li>`).join('');
      TRACKS.appendChild(el(`<div class="card"><h3>B · editor shells found in the zip</h3>
        <div>These are raw ONLYOFFICE entry points. Opening one with no document server
        may well stall at a loading screen — that is <i>information</i>, not a bug in this probe.
        Note how far it gets and what the console says.</div><ul>${list}</ul></div>`));
    }

    document.getElementById('layout').textContent = JSON.stringify(L, null, 2);
  })
  .catch((e) => {
    document.getElementById('layout').textContent = 'layout.json failed to load: ' + e;
    TRACKS.appendChild(el('<div class="card"><h3>No layout.json</h3><div>Re-run the probe script.</div></div>'));
  });
</script>
HTML
}

write_x2t_html() {
  cat > "$PROBE/probe-x2t.html" <<'HTML'
<!doctype html>
<meta charset="utf-8">
<title>x2t.wasm self-test</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root { color-scheme: light }
  body { font: 15px/1.55 -apple-system, BlinkMacSystemFont, sans-serif; margin: 0;
         padding: 26px 30px 60px; max-width: 900px; color: #1b1b1f; background: #fbfaf7 }
  h1 { font-size: 21px; margin: 0 0 4px }
  .sub { color: #6b6455; margin: 0 0 20px }
  pre { background: #14121d; color: #e8e3d6; padding: 14px 16px; border-radius: 10px;
        font: 12.5px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; overflow: auto;
        max-height: 62vh; white-space: pre-wrap; word-break: break-word }
  .l-ok  { color: #9ad39a } .l-bad { color: #f0a0a0 } .l-hi { color: #d8c27a }
  a { color: #1b1b1f }
</style>
<h1>x2t.wasm self-test</h1>
<p class="sub">Does ONLYOFFICE's converter instantiate in <b>this</b> browser engine? This is
the measurement that decides the fallback tier: if the editors are too much for WebKit but
x2t is fine, we keep our own grid and gain ONLYOFFICE-grade .xlsx/.docx conversion anyway.
<br><a href="index.html">back to the probe index</a></p>
<pre id="log">starting…
</pre>
<script>
const LOG = document.getElementById('log');
const t0 = performance.now();
function line(msg, cls) {
  const ms = String(Math.round(performance.now() - t0)).padStart(6, ' ');
  const s = document.createElement('span');
  if (cls) s.className = cls;
  s.textContent = `${ms}ms  ${msg}\n`;
  LOG.appendChild(s);
}
window.onerror = (m, src, ln) => { line(`window.onerror: ${m}  (${src}:${ln})`, 'l-bad'); };
window.addEventListener('unhandledrejection', (e) => line('unhandled rejection: ' + e.reason, 'l-bad'));

line('WebAssembly present: ' + (typeof WebAssembly), typeof WebAssembly === 'object' ? 'l-ok' : 'l-bad');
line('SharedArrayBuffer: ' + (typeof SharedArrayBuffer) + '   crossOriginIsolated: ' + window.crossOriginIsolated);
line('userAgent: ' + navigator.userAgent);

const before = new Set(Object.keys(window));

fetch('layout.json', { cache: 'no-store' }).then((r) => r.json()).then((L) => {
  const c = (L.tracks && L.tracks.cryptpad) || null;
  if (!c) { line('no cryptpad track in layout.json — run: ./scripts/probe_onlyoffice.sh cryptpad', 'l-bad'); return; }
  const js = (c.hits.x2t_js || [])[0];
  const wasm = (c.hits.x2t_wasm || [])[0];
  line('x2t.js:   ' + (js || 'NOT FOUND'), js ? 'l-ok' : 'l-bad');
  line('x2t.wasm: ' + (wasm || 'NOT FOUND'), wasm ? 'l-ok' : 'l-bad');
  if (!js) { line('nothing to load. The zip layout is not what CryptPad documents — see layout.json.', 'l-bad'); return; }

  if (wasm) {
    fetch(wasm, { method: 'HEAD', cache: 'no-store' }).then((r) => {
      const ct = r.headers.get('content-type');
      line(`wasm content-type: ${ct}`, ct === 'application/wasm' ? 'l-ok' : 'l-bad');
      if (ct !== 'application/wasm') line('  instantiateStreaming will refuse this. Serve with serve.py, not python3 -m http.server.', 'l-bad');
    }).catch((e) => line('HEAD on the wasm failed: ' + e, 'l-bad'));
  }

  line('loading ' + js + ' …', 'l-hi');
  const s = document.createElement('script');
  s.src = js;
  s.onerror = () => line('the script element itself failed to load. Check the server log for a NOT OK line.', 'l-bad');
  s.onload = () => {
    line('x2t.js loaded.', 'l-ok');
    const added = Object.keys(window).filter((k) => !before.has(k));
    line('new globals (' + added.length + '): ' + (added.join(', ') || '(none)'), added.length ? 'l-ok' : 'l-bad');
    added.forEach((k) => { try { line('   ' + k + ' : ' + typeof window[k]); } catch (e) { line('   ' + k + ' : <threw>'); } });

    // Deliberately DISCOVERY-shaped. The exported symbol could not be read offline, so
    // we try the plausible names rather than assert one and call a miss a failure.
    //
    // ONLY these names are CALLED. An Emscripten build exports plenty of functions
    // (_free, abort, ...) and invoking one at random would be reckless and would make
    // the log lie about what went wrong. Every OTHER new global is merely inspected.
    const CALLABLE = ['x2t', 'X2T', 'Module', 'createX2T', 'createModule', 'x2tModule',
                      'createX2t', 'X2tModule'];
    const seen = new Set();
    let inspected = 0;
    for (const n of CALLABLE.concat(added)) {
      if (seen.has(n)) continue;
      seen.add(n);
      let v;
      try { v = window[n]; } catch (e) { continue; }
      if (v === undefined || v === null) continue;
      inspected++;
      if (typeof v === 'object') {
        report(n, v);
      } else if (typeof v === 'function' && CALLABLE.indexOf(n) !== -1) {
        line(`${n}() is a known factory name — calling it`, 'l-hi');
        try {
          const r = v({});
          Promise.resolve(r).then((m) => report(n + '()', m)).catch((e) => line(`${n}() rejected: ${e}`, 'l-bad'));
        } catch (e) { line(`${n}() threw: ${e}`, 'l-bad'); }
      } else if (typeof v === 'function') {
        line(`   ${n}: function (not called — not a known factory name)`);
      }
    }
    if (!inspected) line('no candidate module object appeared. Read layout.json and the file itself.', 'l-bad');
  };
  document.head.appendChild(s);
}).catch((e) => line('layout.json failed: ' + e, 'l-bad'));

function report(label, m) {
  if (!m || typeof m !== 'object') { line(`${label}: not an object`, 'l-bad'); return; }
  const keys = Object.keys(m);
  const hasFS = !!m.FS;
  line(`${label}: object with ${keys.length} keys; FS=${hasFS}`, hasFS ? 'l-ok' : '');
  line('   keys: ' + keys.slice(0, 40).join(', '));
  if (!hasFS) return;
  try {
    const listing = m.FS.readdir('/');
    line('   FS./ -> ' + listing.join(' '), 'l-ok');
    try { line('   FS./working -> ' + m.FS.readdir('/working').join(' ')); } catch (e) { line('   /working: ' + e.message); }
    line('VERDICT: x2t instantiated and its in-memory filesystem is reachable in this engine.', 'l-ok');
  } catch (e) {
    line('   FS.readdir threw: ' + e, 'l-bad');
  }
}
</script>
HTML
}

# ── serve ────────────────────────────────────────────────────────────────────
# NOTE: no argument forwarding. Slicing "${@:2}" and empty-array expansion are both
# bash-3.2 + `set -u` traps, and this repo has already paid for that class twice
# (the $APP and $f glued-ellipsis crashes). The one option worth having is an env var.
do_serve() {
  [[ -f "$PROBE/serve.py" ]] || die "nothing to serve yet — run: ./scripts/probe_onlyoffice.sh personal"
  PY="$(resolve_py)" || die "no python3 found — xcode-select --install"
  say "serving data/office-probe on http://127.0.0.1:${PORT}/"
  say "  (Ctrl-C to stop; OO_ISOLATE=1 adds COOP/COEP if the console asks for SharedArrayBuffer)"
  if [[ "${OO_ISOLATE:-0}" == "1" ]]; then
    exec "$PY" "$PROBE/serve.py" --port "$PORT" --isolate
  fi
  exec "$PY" "$PROBE/serve.py" --port "$PORT"
}

checklist() {
  cat <<CHECK

──────────────────────────────────────────────────────────────────────
  READY. Start the server, then open it in SAFARI (WebKit — the engine
  MOT Deck's own tabs use; Chrome would decide nothing):

    cd "$ROOT" && ./scripts/probe_onlyoffice.sh serve

    http://127.0.0.1:${PORT}/

  THE 30-MINUTE MEASUREMENT (docs/handoff/ONLYOFFICE-PROBE-RUNBOOK.md)

    1. Does the real ONLYOFFICE ribbon render?
    2. New sheet: type values + a formula. Does it calculate?
    3. Save/export .xlsx. Does a file come out?
    4. Import one of your OWN .xlsx files from
       ~/Library/Application Support/MOT Deck/data/office/
       Do formulas, merges and number formats survive?
    5. Same for a .docx if the bundle carries the documents editor.
    6. Note the load time and the RAM in Activity Monitor.
    7. Open Web Inspector (Develop menu) and note anything red.

  PASS  -> ONLYOFFICE becomes LOffice tier 2 and replaces the Univer loader.
  FAIL  -> x2t.wasm-as-converter-only behind our own tier-1 grid.

  Write the numbers into the runbook. Then delete everything:

    rm -rf "$PROBE"
──────────────────────────────────────────────────────────────────────

CHECK
}

case "$CMD" in
  personal) do_personal; checklist ;;
  cryptpad) do_cryptpad; checklist ;;
  both)     do_personal; do_cryptpad; checklist; do_serve ;;
  serve)    do_serve ;;
  clean)
    [[ -d "$PROBE" ]] || { say "nothing to clean."; exit 0; }
    say "removing $PROBE"
    rm -rf "$PROBE"
    say "done."
    ;;
  *) usage ;;
esac
