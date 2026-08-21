#!/usr/bin/env bash
# Install OPENCODE — the harness's second coding lane, run as a TAB.
#
#   ./scripts/install_opencode.sh [--yes]
#
# Unlike every other component this is NOT a source checkout and NOT a venv:
# upstream publishes a PREBUILT native binary per platform on npm (built with Bun —
# no Node at run time), so the whole install is "download two npm tarballs, verify,
# extract one Mach-O file". Same shape as install_llamacpp.sh, not install_component.sh.
#
#   data/opencode/bin/opencode      the pinned binary (~144MB)
#   data/opencode/xdg/{config,cache,data,state}
#                                   its ENTIRE home, redirected there by the four XDG_*
#                                   variables start_component.sh exports — so its config,
#                                   its session db and the provider packages it installs
#                                   at runtime never touch ~/.config or ~/.cache.
#   data/opencode-workspace         the directory it is STARTED in = the only place it
#                                   edits by default (the same boundary aider has).
#   data/logs/opencode-install.log
#
# ONLINE-ONLY. Idempotent: an already-correct binary is left alone.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

DEST="$ROOT/data/opencode"
BIN="$DEST/bin/opencode"
LOG="$ROOT/data/logs/opencode-install.log"
REGISTRY="https://registry.npmjs.org"

mkdir -p "$ROOT/data/logs"
# Panel-viewable install log AS WELL AS stdout (the bridge captures stdout for the
# endpoint's reply). The voicebox lesson: a slow install must be readable with no terminal.
exec > >(tee -a "$LOG") 2>&1
echo "──────── install_opencode.sh · $(date '+%Y-%m-%d %H:%M:%S') ────────"

say() { echo "[opencode] $*"; }
die() { echo "[opencode] ERROR: $*" >&2; exit 1; }

# ── pin reader (identical awk shape to install_aider.sh / install_music.sh) ───
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' harness.yaml; }

resolve_py() {
  local p
  for p in "$ROOT/data/python-standalone/bin/python3" \
           "$(command -v python3.12 || true)" \
           "$(command -v python3.13 || true)" \
           "$(command -v python3.11 || true)" \
           "$(command -v python3 || true)"; do
    [[ -n "$p" && -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

# ── which prebuilt package do we need? ───────────────────────────────────────
# Only the two macOS builds are supported here — the harness is a Mac product and a
# wrong guess would download 45MB of the wrong ISA and fail at exec time.
plat_pkg() {
  local os arch
  os="$(uname -s)"; arch="$(uname -m)"
  [[ "$os" == "Darwin" ]] || die "OpenCode is wired for macOS here (uname says ${os})."
  case "$arch" in
    arm64)  echo "opencode-darwin-arm64" ;;
    x86_64) echo "opencode-darwin-x64" ;;
    *) die "no prebuilt OpenCode for ${arch}." ;;
  esac
}

main() {
  local pin pkg py free_gb tgz sha_expect url want
  pin="$(_yb opencode_pin)"
  [[ -n "$pin" ]] || die "build.opencode_pin missing from harness.yaml"
  pkg="$(plat_pkg)"
  py="$(resolve_py)" || die "no python3 found — it is only used to read npm's JSON."
  say "pin: opencode-ai@${pin} (prebuilt: ${pkg})"

  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (the binary is about 0.15GB)"
  [[ "$free_gb" -ge 2 ]] || die "not enough free disk — need about 2GB, have ${free_gb}GB."

  # Already at the pin? `--version` is the only honest check (the file name carries
  # no version) and it is also the proof the binary RUNS on this machine.
  if [[ -x "$BIN" ]]; then
    local have
    have="$("$BIN" --version 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$have" == "$pin" ]]; then
      say "already installed at the pin (${have}) — nothing to do."
      post_install "$pin"
      return 0
    fi
    say "installed binary reports '${have:-unknown}', pin is ${pin} — replacing it."
  fi

  command -v curl >/dev/null 2>&1 || die "curl not found."

  # 1. INTEGRITY, from upstream's own metadata rather than from our guess: the
  #    top-level package must itself declare this platform package AT THIS VERSION.
  #    If upstream ever renames or re-pins the prebuilt, this trips here instead of
  #    silently downloading a mismatched binary.
  say "checking npm metadata for opencode-ai@${pin}…"
  curl -fsSL "$REGISTRY/opencode-ai/$pin" -o "$ROOT/data/opencode-ai.json" \
    || die "could not read $REGISTRY/opencode-ai/$pin (no network?)"
  want="$("$py" - "$ROOT/data/opencode-ai.json" "$pkg" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
print((d.get("optionalDependencies") or {}).get(sys.argv[2], ""))
PY
)"
  rm -f "$ROOT/data/opencode-ai.json"
  [[ "$want" == "$pin" ]] || die "opencode-ai@${pin} declares ${pkg}@'${want}', not ${pin} — upstream changed how the prebuilts are pinned. Re-check build.opencode_pin."

  # 2. The prebuilt's tarball URL + its published sha1.
  curl -fsSL "$REGISTRY/$pkg/$pin" -o "$ROOT/data/opencode-plat.json" \
    || die "could not read $REGISTRY/$pkg/$pin"
  url="$("$py" -c 'import json,sys;print(json.load(open(sys.argv[1]))["dist"]["tarball"])' "$ROOT/data/opencode-plat.json")"
  sha_expect="$("$py" -c 'import json,sys;print(json.load(open(sys.argv[1]))["dist"].get("shasum",""))' "$ROOT/data/opencode-plat.json")"
  rm -f "$ROOT/data/opencode-plat.json"
  [[ -n "$url" ]] || die "no tarball url for ${pkg}@${pin}"
  say "downloading ${pkg}@${pin} (about 46MB)…"
  tgz="$ROOT/data/opencode-${pin}.tgz"
  curl -fL --retry 3 -o "$tgz" "$url" || { rm -f "$tgz"; die "download failed: $url"; }

  # 3. Verify BEFORE extracting. npm publishes sha1 as dist.shasum; a mismatch is a
  #    corrupt download or a substituted artifact, and either way we stop.
  if [[ -n "$sha_expect" ]]; then
    local got
    got="$("$py" - "$tgz" <<'PY'
import hashlib, sys
h = hashlib.sha1()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())
PY
)"
    [[ "$got" == "$sha_expect" ]] || { rm -f "$tgz"; die "sha1 mismatch: got ${got}, npm says ${sha_expect}"; }
    say "sha1 verified (${sha_expect})."
  else
    say "WARN: npm published no shasum for this version — extracting unverified."
  fi

  # 4. Extract exactly ONE file. --strip-components drops npm's `package/` wrapper.
  mkdir -p "$DEST/bin"
  rm -f "$BIN"
  tar xzf "$tgz" -C "$DEST/bin" --strip-components 2 package/bin/opencode \
    || { rm -f "$tgz"; die "the tarball does not contain package/bin/opencode — upstream changed its layout."; }
  rm -f "$tgz"
  chmod +x "$BIN"
  [[ -x "$BIN" ]] || die "no executable at $BIN after extraction."

  # 5. Prove it RUNS before claiming success — a tab that opens onto a dyld error is
  #    worse than an install that refused.
  local ver
  ver="$("$BIN" --version 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "$ver" ]] || die "the binary is installed but does not run (see $LOG)."
  [[ "$ver" == "$pin" ]] || say "WARN: the binary reports ${ver}, the pin says ${pin}."
  say "installed: opencode ${ver}"
  post_install "$pin"
}

post_install() {
  # Its private home + the workspace it will be started in. Created here so the first
  # Start has somewhere to write; the four XDG_* vars in start_component.sh are what
  # actually point OpenCode at them.
  mkdir -p "$DEST/xdg/config" "$DEST/xdg/cache" "$DEST/xdg/data" "$DEST/xdg/state" \
           "$ROOT/data/opencode-workspace"

  # ── THE MANIFEST FLAG. Mission Control's card reads components.opencode.installed
  # from harness.yaml (bridge/app.py::status), NOT the disk — so without this the
  # binary lands, the script says "installed", and the card still offers Install.
  # That was the 2026-08-21 bug: install_component.sh has flipped the flag in its tail
  # since M0, and this standalone installer never learned to. It runs on the
  # "already installed at the pin" path too, so a plain re-run repairs a stale flag.
  # $ROOT is this script's OWN root, which is what makes it edit the SNAPSHOT's
  # manifest when the bridge spawns it from ~/Library/Application Support/Harness
  # (ship.sh's merge is additive-only and will never set it later).
  local py_flip
  py_flip="$(resolve_py)" || py_flip="python3"
  "$py_flip" "$ROOT/scripts/flip_installed.py" opencode || {
    say "ERROR: the binary is installed but components.opencode.installed could not be"
    say "  set in harness.yaml, so the card will still say 'Not installed'. Fix with:"
    say "  python3 scripts/flip_installed.py opencode"
    exit 1; }
  echo ""
  say "home:      data/opencode/xdg (config, cache, sessions — never ~/.config)"
  say "workspace: data/opencode-workspace — the ONLY directory it is started in, and"
  say "  therefore the only boundary on what it edits (the Hermes path-guard is a"
  say "  Hermes plugin hook and does NOT cover this lane)."
  say "NOTE: OpenCode REQUIRES tool-calling and has no text-edit fallback. Load a model"
  say "  with the green 'tools' pill in Models, or it will look broken rather than slow."
  say "NOTE: auto-update is disabled two ways (config + env). Never use its in-app"
  say "  upgrade — this install is pinned at build.opencode_pin in harness.yaml."
}

main "$@"
