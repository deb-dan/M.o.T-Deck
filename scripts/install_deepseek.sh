#!/usr/bin/env bash
# Install DEEPSEEK HARNESS (`dsh`) — the harness's third coding lane, run as a TAB.
#
#   ./scripts/install_deepseek.sh [--yes]
#
# NOT a source checkout, NOT a venv, and NOT a prebuilt binary. Upstream publishes a
# TypeScript monorepo to npm, so the whole install is "npm install one pinned package
# into a private prefix". Weight class: Hermes/Odysseus (a dependency tree), not
# OpenCode (one Mach-O). MEASURED from scratch 2026-09-03 at pin 0.1.1-rc.2:
# 455 packages, 283MB, ~7 minutes on a warm npm cache.
#
#   data/deepseek/npm/                its private npm prefix — package.json,
#                                     package-lock.json and node_modules/. Nothing is
#                                     installed globally and nothing touches ~/.npm-global.
#   data/deepseek/npm/node_modules/.bin/dsh
#                                     the launcher start_component.sh runs.
#   data/deepseek/home/               its ENTIRE $DSH_HOME — settings.yaml, profiles/,
#                                     sessions/, storages/ — exported at spawn, so its
#                                     config and session logs never touch ~/.dsh.
#   data/deepseek-workspace           the directory it is STARTED in, and the obvious
#                                     answer to its own "choose a workspace" prompt.
#   data/logs/deepseek-install.log
#
# ONLINE-ONLY. Idempotent: an install already at the pin is left alone (and its
# manifest flag is repaired, which is the recorded install_opencode.sh bug).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

DEST="$ROOT/data/deepseek"
PREFIX="$DEST/npm"
DSH="$PREFIX/node_modules/.bin/dsh"
DSH_HOME_DIR="$DEST/home"
WS="$ROOT/data/deepseek-workspace"
LOG="$ROOT/data/logs/deepseek-install.log"
PKG="@deepseek-ai/dsh"
REGISTRY="https://registry.npmjs.org"

mkdir -p "$ROOT/data/logs"
# Panel-viewable install log AS WELL AS stdout (the bridge captures stdout for the
# endpoint's reply). The voicebox lesson: a slow install must be readable with no
# terminal — and at ~7 minutes this one is squarely in that class.
exec > >(tee -a "$LOG") 2>&1
echo "──────── install_deepseek.sh · $(date '+%Y-%m-%d %H:%M:%S') ────────"

say() { echo "[deepseek] $*"; }
die() { echo "[deepseek] ERROR: $*" >&2; exit 1; }

# ── pin reader (identical awk shape to install_opencode.sh / install_aider.sh) ──
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

main() {
  local pin py free_gb node npm_bin have

  pin="$(_yb dsh_pin)"
  [[ -n "$pin" ]] || die "build.dsh_pin missing from harness.yaml"
  py="$(resolve_py)" || die "no python3 found — it is only used to read npm's JSON."
  say "pin: ${PKG}@${pin}"

  # ── PREFLIGHT 1: the platform. macOS only, like install_opencode.sh — the harness
  # is a Mac product, and dsh's own sandbox backend table names macOS (Seatbelt) as a
  # first-class platform, but nothing here has ever been walked anywhere else.
  [[ "$(uname -s)" == "Darwin" ]] || die "the DeepSeek lane is wired for macOS here (uname says $(uname -s))."

  # ── PREFLIGHT 2: the runtime. HARD, not advisory (see the ⚠️ in ensure_node.sh):
  # without node there is nothing to install and nothing to start.
  say "resolving node (>= v22.19, or >= v24) …"
  node="$(bash scripts/ensure_node.sh)" || node=""
  [[ -n "$node" && -x "$node" ]] || {
    say "ERROR: no usable node, and the pinned fallback could not be provisioned."
    say "  The lines above say exactly what was tried. The DeepSeek lane is a"
    say "  TypeScript app: node is its RUN-time, so there is nothing to install"
    say "  without it. Either install node >= 22.19 (https://nodejs.org) — yours"
    say "  will always be preferred over ours — or fix the network and re-run."
    exit 1; }
  npm_bin="$(dirname "$node")/npm"
  # A node from PATH may sit beside no npm at all (a bare-binary install). Say so
  # rather than failing inside npm with a "command not found" nobody can place.
  [[ -x "$npm_bin" ]] || npm_bin="$(command -v npm || true)"
  [[ -n "$npm_bin" && -x "$npm_bin" ]] || die "found node at ${node} but no npm beside it or on PATH — install npm, or delete data/node and re-run to use our pinned copy (which ships npm)."
  say "node: ${node} ($("$node" --version 2>/dev/null || echo '?'))"
  say "npm : ${npm_bin} ($("$npm_bin" --version 2>/dev/null || echo '?'))"

  # ── PREFLIGHT 3: disk. HONEST numbers, MEASURED, not guessed (install_goose.sh's
  # rule): node_modules is 283MB, the npm cache holds roughly as much again during the
  # resolve, and data/node is another 200MB when we had to provision it.
  free_gb=$(df -k "$ROOT" | awk 'NR==2 {print int($4/1048576)}')
  say "free disk on this volume: ${free_gb}GB (node_modules is about 0.3GB; allow ~1GB"
  say "  for the npm cache during the resolve, plus ~0.2GB if node came from us)"
  [[ "$free_gb" -ge 3 ]] || die "not enough free disk — need about 3GB of headroom, have ${free_gb}GB."

  # ── PREFLIGHT 4: the network, and WHAT IT WILL PULL. Said before it happens,
  # because this is the slowest install in the tree after the torch stacks.
  command -v curl >/dev/null 2>&1 || die "curl not found."
  say "this install is ONLINE-ONLY and takes several minutes:"
  say "  MEASURED at this pin — 455 packages, 283MB, about 7 minutes on a warm cache."
  say "  (${PKG}'s own tarball is ~44KB; everything else is its dependency tree.)"

  # ── Already at the pin? `--version` is the only honest check, and it is also the
  # proof the install RUNS on this machine's node.
  if [[ -x "$DSH" ]]; then
    have="$(DSH_HOME="$DSH_HOME_DIR" "$DSH" --version 2>/dev/null | tr -d '[:space:]' || true)"
    if [[ "$have" == "$pin" ]]; then
      say "already installed at the pin (${have}) — nothing to do."
      post_install "$pin" "$node"
      return 0
    fi
    say "installed dsh reports '${have:-unknown}', pin is ${pin} — replacing it."
  fi

  # ── INTEGRITY, from upstream's own metadata rather than from our guess. npm
  # verifies dist.integrity on every fetch by itself, but that only proves "the bytes
  # match what the registry served NOW". Reading the metadata FIRST and refusing on a
  # mismatch is what turns "upstream unpublished/re-tagged this version" from a silent
  # different-install into a stop — the same reason install_opencode.sh reads
  # optionalDependencies before it downloads anything.
  say "checking npm metadata for ${PKG}@${pin} …"
  curl -fsSL "$REGISTRY/${PKG}/${pin}" -o "$DEST.meta.json" \
    || die "could not read $REGISTRY/${PKG}/${pin} (no network? withdrawn version?)"
  local meta_ver meta_int
  meta_ver="$("$py" -c 'import json,sys;print(json.load(open(sys.argv[1])).get("version",""))' "$DEST.meta.json")"
  meta_int="$("$py" -c 'import json,sys;print((json.load(open(sys.argv[1])).get("dist") or {}).get("integrity",""))' "$DEST.meta.json")"
  rm -f "$DEST.meta.json"
  [[ "$meta_ver" == "$pin" ]] || die "${PKG}@${pin} resolves to version '${meta_ver}' — the registry no longer serves this exact version. Re-check build.dsh_pin."
  [[ -n "$meta_int" ]] || say "WARN: npm published no dist.integrity for this version."
  say "registry agrees: ${PKG}@${meta_ver}${meta_int:+ (${meta_int})}"

  # ── THE INSTALL. Private prefix, no global writes, no scripts we did not ask for.
  mkdir -p "$PREFIX"
  # A hand-written package.json rather than `npm init`: one fewer interactive surface,
  # and `private: true` is what stops any accidental publish path dead.
  [[ -f "$PREFIX/package.json" ]] || cat > "$PREFIX/package.json" <<'JSON'
{
  "name": "harness-deepseek-prefix",
  "version": "0.0.0",
  "private": true,
  "description": "Private npm prefix for the harness DeepSeek Harness lane. Managed by scripts/install_deepseek.sh — do not edit by hand.",
  "dependencies": {}
}
JSON

  # ⚠️ LOCKFILE DISCIPLINE, AND ITS HONEST LIMIT. `npm ci` is byte-reproducible but
  # ONLY off an existing lock, and the first install has none — so: `npm ci` when the
  # lock is present AND already describes this pin, else `npm install` at the exact
  # version (which WRITES the lock, 513 entries at this pin) and every later repair is
  # reproducible off it. The transitive tree carries upstream's own `^` ranges, so a
  # first install on a different day can differ; the lock is what freezes it from then
  # on. That is as far as pinning goes in this ecosystem, and the ledger says so.
  local mode="install"
  if [[ -f "$PREFIX/package-lock.json" ]] \
     && "$py" - "$PREFIX/package-lock.json" "$pin" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(1)
pkgs = d.get("packages") or {}
node = pkgs.get("node_modules/@deepseek-ai/dsh") or {}
raise SystemExit(0 if node.get("version") == sys.argv[2] else 1)
PY
  then
    mode="ci"
    say "package-lock.json already describes ${pin} — installing from the lock (npm ci),"
    say "  which is byte-for-byte what the last install resolved."
  else
    say "no lock for ${pin} yet — resolving once (npm install), then the lock freezes it."
  fi

  say "installing … (this is the several-minute part; the log above says why)"
  # --no-audit/--no-fund: two network round trips and a wall of advisory text that
  # would land in a panel log the user cannot act on from here.
  # --ignore-scripts is DELIBERATELY NOT PASSED: pi-ai's provider SDKs and the
  # node-addon helper need their install scripts to produce a working tree, and an
  # install that "succeeds" into a broken tree is the worse failure. Said out loud
  # because it is the one place this install trusts upstream code with our shell.
  if [[ "$mode" == "ci" ]]; then
    ( cd "$PREFIX" && "$npm_bin" ci --no-audit --no-fund ) \
      || die "npm ci failed — see $LOG. Delete data/deepseek/npm/node_modules and re-run to resolve from scratch."
  else
    ( cd "$PREFIX" && "$npm_bin" install --no-audit --no-fund --save-exact "${PKG}@${pin}" ) \
      || die "npm install failed — see $LOG (no network? registry down?)."
  fi

  # ⚠️ NO BACKTICKS IN THESE STRINGS. `die "... its \`bin\` mapping ..."` inside double
  # quotes is COMMAND SUBSTITUTION, not prose — it would try to run `bin`. Caught on
  # the first shellcheck/`bash -n` pass of this file; the fix is to say it in words.
  [[ -x "$DSH" ]] || die "npm reported success but there is no launcher at ${DSH} — upstream changed the bin mapping in its package.json (it was dsh -> lib/bin.js at this pin)."

  # ── Prove it RUNS before claiming success. A tab that opens onto a node stack trace
  # is worse than an install that refused. ⚠️ DSH_HOME is set for this check too: a
  # bare `--version` MATERIALIZES $DSH_HOME/profiles, and without it that would be the
  # one command in the whole lane that wrote to ~/.dsh (MEASURED — the profile tree
  # appears on a plain --help).
  mkdir -p "$DSH_HOME_DIR"
  local ver
  ver="$(DSH_HOME="$DSH_HOME_DIR" DSH_TELEMETRY_DISABLED=1 "$DSH" --version 2>/dev/null | tr -d '[:space:]' || true)"
  [[ -n "$ver" ]] || die "dsh is installed but does not run (see $LOG). Most often: node too old — this machine has $("$node" --version 2>/dev/null || echo '?')."
  [[ "$ver" == "$pin" ]] || say "WARN: dsh reports ${ver}, the pin says ${pin}."
  say "installed: dsh ${ver}"
  post_install "$pin" "$node"
}

# ── THE WORKSPACE MUST EXIST, OR ITS OWN FIRST SCREEN HAS NO ANSWER ───────────
# dsh's composer opens on "Choose a workspace to start" and will not accept a message
# until one is registered (MEASURED in its own UI). Unlike OpenCode there is nothing
# to seed: a workspace record lives in $DSH_HOME/storages/workspace.json, whose entity
# format is package-private and whose own README says an unmarked order/table mismatch
# "remains unexplained corruption and fails loud" — so hand-writing one would be a
# forgery that can brick the lane, not a shortcut. What we CAN honestly do is make
# sure the directory it should point at exists and explains itself. Ledger U67 carries
# the retirement plan.
seed_workspace_dir() {
  mkdir -p "$WS"
  if [[ ! -f "$WS/README.md" ]]; then
    printf '%s\n' \
      "# Harness workspace — DeepSeek Harness lane" \
      "" \
      "This is the working directory the DeepSeek Harness lane is started in, and the" \
      "folder to pick the first time its UI asks you to \"Add workspace\"." \
      "" \
      "Because dsh is only ever started here, this is also the boundary on what it" \
      "edits by default — the same boundary the Aider and OpenCode lanes have. (The" \
      "Hermes path-guard is a Hermes plugin hook and does NOT cover this lane.)" \
      > "$WS/README.md" || true
  fi
  # Deliberately NO `git init` here. That is the OpenCode dance, and it exists because
  # OpenCode derives a project IDENTITY from a root commit. dsh derives nothing from
  # git: it canonicalizes the path with fs.realpath and keys the record on that
  # (dsh-workspace's own documented `create(path, title?)`). A git repo we made for no
  # reason would be litter in the user's tree.
  return 0
}

post_install() {
  local pin="$1" node="$2"
  # Its private home + the workspace it will be started in. Created here so the first
  # Start has somewhere to write; DSH_HOME in start_component.sh is what actually
  # points dsh at this one instead of ~/.dsh.
  mkdir -p "$DSH_HOME_DIR" "$PREFIX"
  seed_workspace_dir

  # ── THE MANIFEST FLAG. Mission Control's card reads components.deepseek.installed
  # from harness.yaml (bridge/routers/components.py::status), NOT the disk — so
  # without this the install lands, the script says "installed", and the card still
  # offers Install. That was the 2026-08-21 install_opencode.sh bug, recorded in that
  # flipper's own header. It runs on the "already installed at the pin" path too, so a
  # plain re-run repairs a stale flag.
  # $ROOT is this script's OWN root, which is what makes it edit the SNAPSHOT's
  # manifest when the bridge spawns it from ~/Library/Application Support/Harness.
  # ⚠️ THE FAILURE BRANCH BELOW IS NOT OPTIONAL, and bridge/tests/test_installed_flip.py
  # fences it by asserting the word ERROR appears within 600 characters of the call:
  # an installer that ignores a failed flip is exactly how a card comes to lie.
  local py_flip
  py_flip="$(resolve_py)" || py_flip="python3"
  "$py_flip" "$ROOT/scripts/flip_installed.py" deepseek || {
    say "ERROR: dsh is installed but components.deepseek.installed could not be set in"
    say "  harness.yaml, so the card will still say 'Not installed'. Fix with:"
    say "  python3 scripts/flip_installed.py deepseek"
    exit 1; }

  echo ""
  say "home:      data/deepseek/home — its ENTIRE \$DSH_HOME (settings.yaml, profiles,"
  say "  sessions, storages). Verified from scratch: ~/.dsh is never created."
  say "workspace: data/deepseek-workspace — the only directory it is started in, and"
  say "  therefore the boundary on what it edits by default."
  say "provider:  Start writes an OpenAI-compatible provider named 'MOT Deck (local)'"
  say "  into data/deepseek/home/settings.yaml under llm-pi-ai.providers, pointing at"
  say "  the harness runner, with your registry's models enumerated. In dsh it shows"
  say "  up in Settings -> Models and in the composer's model picker."
  say "FIRST RUN, two things that surprise people, both upstream's own behaviour:"
  say "  1. an 'Internal Testing Notice' modal — click Continue, it is shown once."
  say "  2. it asks you to choose a WORKSPACE before it will take a message. Click"
  say "     'Add workspace' in its sidebar and pick data/deepseek-workspace. That"
  say "     opens macOS's OWN folder chooser, launched by dsh itself — if it does not"
  say "     come forward, click the Harness icon in the Dock. (Ledger U67.)"
  say "NOTE: pre-1.0 developer preview, pinned at build.dsh_pin (${pin}). It ships no"
  say "  auto-updater (grepped, at this pin), so nothing moves under the pin on its"
  say "  own — but never 'npm update' this prefix by hand for the same reason."
  say "NOTE: telemetry is DISABLED at this pin by default AND we export"
  say "  DSH_TELEMETRY_DISABLED=1 at spawn, so a future default cannot switch it on."
  say "node:      ${node} — your own node is always preferred; data/node is only the"
  say "  pinned fallback (build.node_pin)."
}

main "$@"
