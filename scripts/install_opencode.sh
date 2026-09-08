#!/usr/bin/env bash
# Install OPENCODE — MOT Deck's second coding lane, run as a TAB.
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

# Version probes use the same private XDG directories as the runtime.
opencode_run() {
  local executable="$1"
  shift
  mkdir -p "$DEST/xdg/"{config,cache,data,state}
  env XDG_CONFIG_HOME="$DEST/xdg/config" XDG_CACHE_HOME="$DEST/xdg/cache" \
      XDG_DATA_HOME="$DEST/xdg/data" XDG_STATE_HOME="$DEST/xdg/state" \
      OPENCODE_DISABLE_AUTOUPDATE=1 "$executable" "$@"
}

# ── pin reader (identical awk shape to install_aider.sh / install_music.sh) ───
_yb() { awk -v k="  $1:" '/^build:/{f=1} f && index($0,k)==1 {line=$0; sub(/#.*/,"",line); sub(/^[^:]*:[[:space:]]*/,"",line); gsub(/[",]/,"",line); gsub(/[[:space:]]+$/,"",line); print line; exit} f && /^[a-z]/ && !/^build:/{exit}' motdeck.yaml; }

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
# Only the two macOS builds are supported here — MOT Deck is a Mac product and a
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
  local pin pkg py free_gb tgz sha_recorded integrity_expect url want digest_key
  pin="$(_yb opencode_pin)"
  [[ -n "$pin" ]] || die "build.opencode_pin missing from motdeck.yaml"
  pkg="$(plat_pkg)"
  case "$pkg" in
    opencode-darwin-arm64) digest_key="opencode_darwin_arm64_sha256" ;;
    opencode-darwin-x64) digest_key="opencode_darwin_x64_sha256" ;;
    *) die "no recorded digest key for ${pkg}" ;;
  esac
  sha_recorded="$(_yb "$digest_key")"
  [[ "$sha_recorded" =~ ^[0-9a-f]{64}$ ]] \
    || die "build.${digest_key} must be a recorded 64-character SHA-256"
  py="$(resolve_py)" || die "no python3 found — it is only used to read npm's JSON."
  say "pin: opencode-ai@${pin} (prebuilt: ${pkg})"

  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (the binary is about 0.15GB)"
  [[ "$free_gb" -ge 2 ]] || die "not enough free disk — need about 2GB, have ${free_gb}GB."

  # Already at the pin? `--version` is the only honest check (the file name carries
  # no version) and it is also the proof the binary RUNS on this machine.
  if [[ -x "$BIN" ]]; then
    local have
    have="$(opencode_run "$BIN" --version 2>/dev/null | tr -d '[:space:]' || true)"
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

  # 2. The prebuilt's tarball URL + npm's published SHA-512 integrity. The latter is
  #    checked in addition to our manifest's independently recorded SHA-256; live
  #    registry metadata is never allowed to authorize changed bytes by itself.
  curl -fsSL "$REGISTRY/$pkg/$pin" -o "$ROOT/data/opencode-plat.json" \
    || die "could not read $REGISTRY/$pkg/$pin"
  url="$("$py" -c 'import json,sys;print(json.load(open(sys.argv[1]))["dist"]["tarball"])' "$ROOT/data/opencode-plat.json")"
  integrity_expect="$("$py" -c 'import json,sys;print(json.load(open(sys.argv[1]))["dist"].get("integrity",""))' "$ROOT/data/opencode-plat.json")"
  rm -f "$ROOT/data/opencode-plat.json"
  [[ -n "$url" ]] || die "no tarball url for ${pkg}@${pin}"
  [[ "$integrity_expect" == sha512-* ]] \
    || die "npm published no SHA-512 integrity for ${pkg}@${pin}"
  say "downloading ${pkg}@${pin} (about 46MB)…"
  tgz="$ROOT/data/opencode-${pin}.tgz"
  curl -fL --retry 3 -o "$tgz" "$url" || { rm -f "$tgz"; die "download failed: $url"; }

  # 3. Verify BOTH authorities BEFORE extracting.
  local got_sha256 got_integrity
  got_sha256="$(shasum -a 256 "$tgz" | awk '{print $1}')"
  [[ "$got_sha256" == "$sha_recorded" ]] \
    || { rm -f "$tgz"; die "sha256 mismatch: got ${got_sha256}, recorded ${sha_recorded}"; }
  got_integrity="$("$py" - "$tgz" <<'PY'
import base64, hashlib, sys
h = hashlib.sha512()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
print("sha512-" + base64.b64encode(h.digest()).decode("ascii"))
PY
)"
  [[ "$got_integrity" == "$integrity_expect" ]] \
    || { rm -f "$tgz"; die "SHA-512 integrity mismatch: downloaded bytes disagree with npm metadata"; }
  say "recorded SHA-256 and npm SHA-512 verified."

  # 4. Extract exactly ONE file. --strip-components drops npm's `package/` wrapper.
  mkdir -p "$DEST/bin"
  OPENCODE_STAGE="$(mktemp -d "$DEST/.opencode-install.XXXXXX")"
  trap 'rm -rf "${OPENCODE_STAGE:-}"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  local candidate="$OPENCODE_STAGE/opencode"
  tar xzf "$tgz" -C "$OPENCODE_STAGE" --strip-components 2 package/bin/opencode \
    || { rm -f "$tgz"; die "the tarball does not contain package/bin/opencode — upstream changed its layout."; }
  rm -f "$tgz"
  [[ -f "$candidate" && ! -L "$candidate" ]] || die "no regular executable after extraction."
  chmod +x "$candidate"

  # 5. Prove it RUNS before claiming success — a tab that opens onto a dyld error is
  #    worse than an install that refused.
  local ver
  ver="$(opencode_run "$candidate" --version 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "$ver" ]] || die "the candidate binary does not run; the existing install was kept (see $LOG)."
  [[ "$ver" == "$pin" ]] || say "WARN: the binary reports ${ver}, the pin says ${pin}."
  mv -f "$candidate" "$BIN"
  rm -rf "$OPENCODE_STAGE"
  OPENCODE_STAGE=""
  say "installed: opencode ${ver}"
  post_install "$pin"
}

# ── THE WORKSPACE MUST BE A PROJECT, OR THE TAB LANDS ON "Add project" ────────
# OpenCode does not have a projects file we could write. A directory IS a project
# only if it is a git repo AND that repo yields an id — the hash of a remote URL, a
# cached id in <git-common-dir>/opencode, or THE ROOT COMMIT SHA
# (packages/core/src/project.ts:110-122 at pin 1.18.19). `git init` alone is NOT
# enough: with no commits `git rev-list --max-parents=0 HEAD` fails, the id falls back
# to the shared pseudo-project "global", and upstream asserts exactly that in its own
# test (test/project/migrate-global.test.ts:64-72). One EMPTY commit is what turns the
# directory into a project with an identity of its own.
#
# This is the honest mechanism, not a fake: it is the same thing the app's own
# "Add project" button does for an empty directory (it calls POST /project/git/init),
# plus the commit that button leaves you to make.
#
# Repo-LOCAL identity via `-c`: this must never touch the user's global git config,
# and a machine with no user.email set would otherwise fail the commit outright.
# Best-effort throughout — a workspace without git still works, it just shares the
# "global" project, so this may warn but must never fail the install.
seed_workspace_project() {
  local ws="$ROOT/data/opencode-workspace"
  [[ -d "$ws/.git" ]] && { say "workspace: already a git project"; return 0; }
  command -v git >/dev/null 2>&1 || {
    say "WARN: no git on PATH — data/opencode-workspace cannot become a distinct"
    say "  OpenCode project; it will share the shared 'global' one."
    return 0; }
  if [[ ! -f "$ws/README.md" ]]; then
    printf '%s\n' "# MOT Deck workspace" "" \
      "This is the working directory the OpenCode lane is started in — and, because" \
      "OpenCode is started nowhere else, the only boundary on what it edits." \
      "(The Hermes path-guard is a Hermes plugin hook and does NOT cover this lane.)" \
      > "$ws/README.md" || true
  fi
  ( cd "$ws" \
    && git init --quiet \
    && git -c user.name="MOT Deck" -c user.email="motdeck@localhost" \
           -c commit.gpgsign=false commit --allow-empty --quiet -m "opencode workspace" \
  ) && say "workspace: git-initialised — one empty commit is what makes it a real" \
    && say "  OpenCode project rather than the shared 'global' one" \
    || say "WARN: could not git-init data/opencode-workspace — OpenCode will treat it"
  [[ -d "$ws/.git" ]] || say "  as the shared 'global' project. Harmless; the lane still works."
  return 0
}

post_install() {
  # Its private home + the workspace it will be started in. Created here so the first
  # Start has somewhere to write; the four XDG_* vars in start_component.sh are what
  # actually point OpenCode at them.
  mkdir -p "$DEST/xdg/config" "$DEST/xdg/cache" "$DEST/xdg/data" "$DEST/xdg/state" \
           "$ROOT/data/opencode-workspace"
  seed_workspace_project

  # ── THE MANIFEST FLAG. Mission Control's card reads components.opencode.installed
  # from motdeck.yaml (bridge/app.py::status), NOT the disk — so without this the
  # binary lands, the script says "installed", and the card still offers Install.
  # That was the 2026-08-21 bug: install_component.sh has flipped the flag in its tail
  # since M0, and this standalone installer never learned to. It runs on the
  # "already installed at the pin" path too, so a plain re-run repairs a stale flag.
  # $ROOT is this script's OWN root, which is what makes it edit the SNAPSHOT's
  # manifest when the bridge spawns it from ~/Library/Application Support/MOT Deck
  # (ship.sh's merge is additive-only and will never set it later).
  local py_flip
  py_flip="$(resolve_py)" || py_flip="python3"
  "$py_flip" "$ROOT/scripts/flip_installed.py" opencode || {
    say "ERROR: the binary is installed but components.opencode.installed could not be"
    say "  set in motdeck.yaml, so the card will still say 'Not installed'. Fix with:"
    say "  python3 scripts/flip_installed.py opencode"
    exit 1; }
  echo ""
  say "home:      data/opencode/xdg (config, cache, sessions — never ~/.config)"
  say "workspace: data/opencode-workspace — the ONLY directory it is started in, and"
  say "  therefore the only boundary on what it edits (the Hermes path-guard is a"
  say "  Hermes plugin hook and does NOT cover this lane)."
  say "provider: Start writes an OpenAI-compatible provider named 'llama.cpp' pointing"
  say "  at MOT Deck runner, into BOTH data/opencode/xdg/config/opencode/opencode.json"
  say "  and data/opencode-workspace/opencode.json. In OpenCode it shows as CONNECTED in"
  say "  Settings -> Providers and its models are yours. If the picker offers OpenCode's"
  say "  own Zen models (Big Pickle, gpt-5...) instead, the config did not reach it — the"
  say "  Start log prints one 'opencode provider check:' line that says which it was."
  say "NOTE: OpenCode REQUIRES tool-calling and has no text-edit fallback. Load a model"
  say "  with the green 'tools' pill in Models, or it will look broken rather than slow."
  say "NOTE: auto-update is disabled two ways (config + env). Never use its in-app"
  say "  upgrade — this install is pinned at build.opencode_pin in motdeck.yaml."
}

main "$@"
