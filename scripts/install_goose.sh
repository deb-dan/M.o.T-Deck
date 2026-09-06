#!/usr/bin/env bash
# install_goose.sh — vendor the pinned `goose` CLI as MOT Deck's THIRD agent lane.
#
#   ./scripts/install_goose.sh              install (idempotent)
#   ./scripts/install_goose.sh --check      say what is installed, change nothing
#   ./scripts/install_goose.sh --force      re-download + re-extract even at the pin
#
# NOT A COMPONENT. No port, no manifest `components:` entry, no daemon, no venv, no
# registry row — exactly like install_onlyoffice.sh says of itself, and for the same
# reason: nothing here runs on its own. goose is a TERMINAL PROGRAM the bridge spawns
# in a pseudo-terminal for exactly as long as the Goose tab holds a websocket open
# (bridge/pty_goose.py + bridge/routers/goose.py), which is the aider lane's shape.
#
# ⚠️ THEREFORE THERE IS NO `scripts/flip_installed.py goose` CALL, and the absence is
# deliberate. That script flips `components.<name>.installed` so a MISSION CONTROL CARD
# stops saying "Not installed". goose has no card (it has no port and nothing to Start),
# so there is no flag to flip — flip_installed.py would exit 1 with "components.goose is
# not in motdeck.yaml", which would be correct. The lane reads INSTALLED FROM DISK on
# every status call (pty_goose.is_installed), which is strictly better than a flag: a
# deleted binary reads as not-installed immediately. docs/research/2026-08-28-goose-
# source-verify.md's install recipe named flip_installed.py because it assumed a
# manifest entry; the entry is what changed, not the discipline.
#
# ⚖️ LICENSE: Apache-2.0, verified at source at this exact sha (research doc §2). There
# is NO NOTICE file in the upstream tree, so there is nothing extra to carry. goose is
# part of the Agentic AI Foundation at the Linux Foundation; github.com/block/goose is a
# 301 to github.com/aaif-goose/goose, a redirect and not a fork.
#
# ⚠️ THE PIN IS THE SHA256 OF THE RELEASE ASSET, NOT THE TAG. A tag can be moved; a
# digest cannot. There is deliberately no GOOSE_TAG environment override: the documented
# way to bump is to edit the constants below (all six of them, together) and re-run with
# --force. v2.0 release CANDIDATES exist upstream; this is a 1.48.0 pin and evaluating v2
# is its own sitting.
#
# What lands:
#   data/goose/bin/goose            the pinned Mach-O arm64 binary (~270MB extracted)
#   data/goose/home/                its ENTIRE HOME — $HOME and all four XDG_* dirs are
#                                   pointed here by bridge/pty_goose.py, so its config,
#                                   its session history and its logs can never touch
#                                   ~/.config/goose or ~/.local/state/goose.
#   data/goose-workspace/           the directory it is STARTED in = the only boundary
#                                   on what it edits (the aider/opencode rule).
#   data/logs/goose-install.log     panel-viewable install log.
#
# ONLINE-ONLY (one 90MB download). Idempotent: a binary already at the pin is left alone.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── THE PIN (docs/research/2026-08-28-goose-source-verify.md, "BUILD-READY pin sheet") ─
GOOSE_REPO="aaif-goose/goose"
GOOSE_TAG="v1.48.0"
GOOSE_SRC_SHA="25021517f12cab87c94bed0874fe7d28168dc264"   # the tag's commit, recorded
GOOSE_ASSET="goose-aarch64-apple-darwin.tar.gz"
GOOSE_ASSET_SHA256="d502945fca78d8e58c8f56932973f454ad57d0754b272f5d44f696a4722da49a"
GOOSE_ASSET_SIZE="90382385"
# The extracted binary's own digest. A SECOND digest over DIFFERENT bytes (the archive
# vs the file inside it) is what makes "the archive contained exactly the binary we
# measured" a claim rather than an assertion — the same two-digest discipline
# install_onlyoffice.sh applies to the CryptPad zips.
GOOSE_BIN_SHA256="e900f1b96662818791ee599c58ea0e44204ca29579dd182ecc238b732ef5d768"

DEST="${GOOSE_DEST:-$ROOT/data/goose}"
BIN="$DEST/bin/goose"
HOMEDIR="$DEST/home"
STAMP="$DEST/INSTALLED"
SOURCES="$DEST/SOURCES.txt"
WS="${GOOSE_WS:-$ROOT/data/goose-workspace}"
LOG="$ROOT/data/logs/goose-install.log"
URL="https://github.com/${GOOSE_REPO}/releases/download/${GOOSE_TAG}/${GOOSE_ASSET}"

FORCE=0
CHECK=0
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
    --check) CHECK=1 ;;
    --yes|-y) ;;                                  # accepted, nothing here prompts
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

mkdir -p "$ROOT/data/logs"
# Panel-viewable install log AS WELL AS stdout — the voicebox lesson: a slow install
# must be readable with no terminal (the tab renders GET /api/logs/goose-install).
if [[ "$CHECK" -eq 0 ]]; then
  exec > >(tee -a "$LOG") 2>&1
  echo "──────── install_goose.sh · $(date '+%Y-%m-%d %H:%M:%S') ────────"
fi

say()  { echo "[goose] $*"; }
warn() { echo "[goose] WARN: $*" >&2; }
die()  { echo "[goose] ERROR: $*" >&2; exit 1; }

sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
stamp_says() { [[ -f "$STAMP" ]] && awk -v k="$1" '$1==k {print $2; exit}' "$STAMP" || true; }

# ⚠️ EVERY INVOCATION OF THE BINARY GOES THROUGH HERE, INCLUDING `--version`, AND THAT
# IS A MEASURED BUG FIX, NOT TIDINESS. goose opens a per-invocation CLI log at
# $XDG_STATE_HOME/goose/logs/cli/<date>/<stamp>.log BEFORE it parses argv — so a bare
# `goose --version` run by THIS SCRIPT created ~/.local/state/goose/logs on Debi's Mac
# (observed 2026-08-29, three empty files), while the very next line of our own output
# promised nothing would ever land there. That is the ~/.unsloth defect class and it is
# also the LIE-TO-USER class: the installer contradicting itself in the same paragraph.
#
# The general rule this records: A CONFINEMENT FENCE THAT ONLY THE RUNTIME APPLIES IS
# NOT A FENCE. Any code path that executes a vendored binary — installer probes, doctor
# checks, version checks, --check modes — must carry the same env the runtime carries.
# `env -i` (not just HOME=…) because inherited XDG_* from the operator's shell would
# otherwise win over HOME; PATH is kept because the binary may exec helpers.
goose_run() {   # goose_run <args…>   — the pinned binary, inside its own home
  env -i PATH="/usr/bin:/bin:/usr/sbin:/sbin" HOME="$HOMEDIR" \
      XDG_CONFIG_HOME="$HOMEDIR/.config" XDG_DATA_HOME="$HOMEDIR/.local/share" \
      XDG_STATE_HOME="$HOMEDIR/.local/state" XDG_CACHE_HOME="$HOMEDIR/.cache" \
      GOOSE_TELEMETRY_OFF=1 GOOSE_DISABLE_KEYRING=true \
      "$BIN" "$@"
}
goose_version() { mkdir -p "$HOMEDIR" 2>/dev/null || true
                  goose_run --version 2>/dev/null | tr -d '[:space:]'; }

# ── --check ──────────────────────────────────────────────────────────────────
if [[ "$CHECK" -eq 1 ]]; then
  if [[ -x "$BIN" ]]; then
    echo "[goose] binary  $BIN"
    echo "[goose] version $(goose_version || echo '(does not run)')"
    echo "[goose] stamp   tag $(stamp_says tag) asset_sha256 $(stamp_says asset_sha256)"
  else
    echo "[goose] not installed (no $BIN)"
  fi
  echo "[goose] home    $HOMEDIR"
  echo "[goose] work    $WS"
  exit 0
fi

# ── platform + preconditions ─────────────────────────────────────────────────
[[ "$(uname -s)" == "Darwin" ]] || die "goose is wired for macOS here (uname says $(uname -s))."
[[ "$(uname -m)" == "arm64" ]] || die "the pinned asset is aarch64-apple-darwin; this machine reports $(uname -m). Bumping to an x86_64 asset means new digests — edit the pin block."
command -v curl   >/dev/null 2>&1 || die "curl not found."
command -v shasum >/dev/null 2>&1 || die "shasum not found (it ships with macOS; check your PATH)."
command -v tar    >/dev/null 2>&1 || die "tar not found."

FREE_GB=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
say "free disk on this volume: ${FREE_GB}GB (the download is 0.09GB, extracted 0.27GB)"
[[ "$FREE_GB" -ge 2 ]] || die "not enough free disk — need about 2GB, have ${FREE_GB}GB."

# ── already at the pin? ──────────────────────────────────────────────────────
# The stamp is the cheap answer; the DIGEST is the honest one, so both are checked and
# the digest wins. `--version` is checked last because it is also the proof it RUNS on
# this machine — a tab that opens onto a dyld error is worse than an install that refused.
if [[ "$FORCE" -eq 0 && -x "$BIN" ]]; then
  got="$(sha256_of "$BIN")"
  if [[ "$got" == "$GOOSE_BIN_SHA256" ]]; then
    ver="$(goose_version || true)"
    [[ -n "$ver" ]] || die "the binary at the pin is on disk but does not run (see $LOG)."
    say "already installed at the pin (goose ${ver}) — nothing to download."
    post_install_done=1
  else
    say "the installed binary's sha256 does not match the pin — replacing it."
    say "  on disk: ${got}"
    say "  pin:     ${GOOSE_BIN_SHA256}"
  fi
fi

# ── fetch + VERIFY BEFORE EXTRACT ────────────────────────────────────────────
if [[ "${post_install_done:-0}" -ne 1 ]]; then
  TGZ="$DEST/${GOOSE_ASSET}"
  mkdir -p "$DEST/bin"

  # A cached archive whose digest already matches is reused rather than re-fetched;
  # anything else on that path is deleted, because a partial download that merely LOOKS
  # like the asset is the failure this whole block exists to make impossible.
  if [[ -f "$TGZ" ]] && [[ "$(sha256_of "$TGZ")" == "$GOOSE_ASSET_SHA256" ]]; then
    say "reusing ${TGZ#"$ROOT"/} (sha256 matches the pin)"
  else
    rm -f "$TGZ"
    say "downloading ${GOOSE_ASSET} (${GOOSE_ASSET_SIZE} bytes) from ${GOOSE_REPO} ${GOOSE_TAG}…"
    curl -fL --retry 3 -sS -o "$TGZ" "$URL" || { rm -f "$TGZ"; die "download failed: $URL"; }
  fi

  # SIZE first — it is free, and a size mismatch names the problem ("you got a 9-byte
  # error page") far better than a digest mismatch does.
  gotsize="$(wc -c <"$TGZ" | tr -d ' ')"
  [[ "$gotsize" == "$GOOSE_ASSET_SIZE" ]] || {
    rm -f "$TGZ"
    die "size MISMATCH for ${GOOSE_ASSET}: got ${gotsize} bytes, the pin says ${GOOSE_ASSET_SIZE}. Refusing to extract."; }

  gotsha="$(sha256_of "$TGZ")"
  [[ "$gotsha" == "$GOOSE_ASSET_SHA256" ]] || {
    rm -f "$TGZ"
    die "sha256 MISMATCH for ${GOOSE_ASSET} — refusing to extract.
       got: ${gotsha}
       pin: ${GOOSE_ASSET_SHA256}
     Either the download is corrupt or the release asset was replaced. Neither is
     something to shrug at: re-run, and if it happens twice, re-verify the pin
     (docs/research/2026-08-28-goose-source-verify.md 'Reproduce this recon')."; }
  say "sha256 verified for ${GOOSE_ASSET} (${gotsha})"

  # The archive contains exactly `./` and `./goose` (verified at recon). Extract only
  # that one member by name, so a re-packaged archive cannot scatter files: --strip
  # nothing, just the one path.
  rm -f "$BIN"
  tar xzf "$TGZ" -C "$DEST/bin" ./goose \
    || { die "the archive does not contain ./goose — upstream changed its layout. Nothing was installed."; }
  [[ -f "$BIN" ]] || die "no file at $BIN after extraction."
  chmod +x "$BIN"

  # THE SECOND DIGEST, over the extracted bytes.
  binsha="$(sha256_of "$BIN")"
  [[ "$binsha" == "$GOOSE_BIN_SHA256" ]] || {
    rm -f "$BIN"
    die "the extracted binary's sha256 is ${binsha}, the pin says ${GOOSE_BIN_SHA256}. Removed it."; }
  say "sha256 verified for the extracted binary (${binsha})"

  # Prove it RUNS before claiming success.
  ver="$(goose_version || true)"
  [[ -n "$ver" ]] || die "the binary is installed but does not run (see $LOG)."
  [[ "$ver" == "${GOOSE_TAG#v}" ]] || warn "the binary reports '${ver}', the pin says ${GOOSE_TAG#v} — the digests matched, so this is an upstream labelling change, not a substituted artifact."
  say "installed: goose ${ver}"
  rm -f "$TGZ"                       # 90MB we can always re-fetch against the digest
fi

# ── the confined home + the workspace ────────────────────────────────────────
# ⚠️ THE ~/.unsloth LESSON, applied before the first run rather than after it. goose
# writes its config to $HOME/.config/goose/config.yaml and its logs to
# $HOME/.local/state/goose/logs (both proven empirically at the recon, item 6). A shared
# dotfolder home is how a lane leaks state out of data/ and becomes un-uninstallable.
# These directories exist so the FIRST spawn has somewhere to write; the env in
# bridge/pty_goose.py is what actually points goose at them.
mkdir -p "$HOMEDIR/.config/goose" "$HOMEDIR/.local/state/goose" \
         "$HOMEDIR/.local/share" "$HOMEDIR/.cache" "$WS"

if [[ ! -f "$WS/README.md" ]]; then
  {
    echo "# MOT Deck goose workspace"
    echo
    echo "This is the working directory the Goose lane is started in — and, because"
    echo "goose is started nowhere else, the only boundary on what it edits."
    echo "(The Hermes path-guard is a Hermes plugin hook and does NOT cover this lane.)"
  } > "$WS/README.md" || true
fi

# ── provenance stamp (install_onlyoffice.sh's shape) ─────────────────────────
cat > "$SOURCES" <<EOF
goose — vendored by scripts/install_goose.sh, unmodified.

  repo         https://github.com/${GOOSE_REPO}
               (github.com/block/goose is an HTTP 301 to this, not a fork)
  tag          ${GOOSE_TAG}
  source sha   ${GOOSE_SRC_SHA}
  asset        ${GOOSE_ASSET}
  asset url    ${URL}
  asset size   ${GOOSE_ASSET_SIZE}
  asset sha256 ${GOOSE_ASSET_SHA256}
  binary sha256 ${GOOSE_BIN_SHA256}
  license      Apache-2.0 (no NOTICE file exists upstream at this sha)

Verified at docs/research/2026-08-28-goose-source-verify.md. Reproduce:
  curl -sLO ${URL}
  shasum -a 256 ${GOOSE_ASSET}
EOF

cat > "$STAMP" <<EOF
tag ${GOOSE_TAG}
src_sha ${GOOSE_SRC_SHA}
asset ${GOOSE_ASSET}
asset_size ${GOOSE_ASSET_SIZE}
asset_sha256 ${GOOSE_ASSET_SHA256}
bin_sha256 ${GOOSE_BIN_SHA256}
installed_at $(date -u '+%Y-%m-%dT%H:%M:%SZ')
EOF

echo ""
say "binary:    ${BIN#"$ROOT"/}"
say "home:      ${HOMEDIR#"$ROOT"/} — \$HOME and every XDG_* dir for this lane point"
say "  here, so nothing lands in ~/.config/goose or ~/.local/state/goose. Ever."
say "workspace: ${WS#"$ROOT"/} — the ONLY directory goose is started in, and therefore"
say "  the only boundary on what it edits (the Hermes path-guard is a Hermes plugin"
say "  hook and does NOT cover this lane)."
say "telemetry: OFF two ways at spawn — GOOSE_TELEMETRY_OFF=1 in the env AND"
say "  GOOSE_TELEMETRY_ENABLED: false in the seeded config. Upstream's PostHog client"
say "  is opt-IN already; we nail it shut anyway (the opencode auto-update discipline)."
say "keychain:  GOOSE_DISABLE_KEYRING keeps the macOS Keychain out of a lane that runs"
say "  in a tab — a modal prompt behind a webview is a hang, not a question."
say "NOTE: goose REQUIRES tool-calling and has no text-edit fallback. Load a model with"
say "  the green 'tools' pill in Models, or it will look broken rather than slow."
say "NOTE: auto-update is a manual goose-update SUBCOMMAND upstream and is never run"
say "  by us — this install is pinned by digest. Never use it: that is the pin rule."
