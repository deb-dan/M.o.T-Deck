#!/usr/bin/env bash
# ship.sh — push current repo code into the FAT app snapshot and restart cleanly.
#
# Exists because the fat app serves a provisioned SNAPSHOT (~/Library/Application
# Support/Harness), not the repo, and the bridge is a separate process that can
# outlive the app (quit app ≠ restart bridge). Both traps have burned sessions.
# This script is THE way to ship: run it after any code change, done.
#
#   ./scripts/ship.sh                       ship + restart
#   ./scripts/ship.sh --restart hermes      ... and restart that COMPONENT afterwards
#   ./scripts/ship.sh --restart a,b         ... comma list, or repeat the flag
#   SHIP_SKIP_GATE=1 ./scripts/ship.sh      ship WITHOUT the contract gate (loud)
#
# What it does, in order:
#   0. run the contract gate (scripts/verify.sh) and REFUSE to ship when it fails or
#      cannot run — a vendored pin bump once shipped with the gate silently skipped
#   1. repo bridge/panel + bridge/*.py + bridge/{core,routers}/*.py + scripts/
#      + guards/ + policies/ → snapshot
#      (NEVER harness.yaml or data/ — those hold live state)
#   2. if app/main.swift is newer than the installed app binary → recompile the
#      Swift shell in place + ad-hoc re-sign (no full fat rebuild)
#   3. quit the app, kill the :8700 bridge LISTENER (components stay up),
#      relaunch, wait for the bridge, print a sanity check
#   4. optionally restart named COMPONENTS from the snapshot (--restart)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DST="$HOME/Library/Application Support/Harness"
APP="/Applications/Harness.app"

# ── args ──────────────────────────────────────────────────────────────────────
# --restart <name> is the sanctioned answer to the standing rule "shipping is NOT
# restarting a component": ship.sh deliberately leaves components up, so after a
# VENDORED upgrade the old process keeps serving and every verification against it
# is invalid (Hermes 0.20.1 shipped, 0.19.1 tested — a whole session lost).
RESTART=()
_add_restart() {   # accepts "a" or "a,b,c"
  local _p _old_ifs="$IFS"
  IFS=','
  for _p in $1; do [[ -n "$_p" ]] && RESTART+=("$_p"); done
  IFS="$_old_ifs"
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart)
      shift
      [[ $# -gt 0 ]] || { echo "[ship] ERROR: --restart needs a component name"; exit 1; }
      _add_restart "$1"; shift ;;
    --restart=*) _add_restart "${1#--restart=}"; shift ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "[ship] ERROR: unknown argument '$1' (see ./scripts/ship.sh --help)"; exit 1 ;;
  esac
done

# The cowork sandbox cannot unlink files under this mount, so an interrupted git
# operation there leaves .git/HEAD.lock / .git/index.lock behind and every later
# commit fails with "Unable to create ... File exists". They ARE removable from the
# Mac, which is the only place ship.sh runs — so clear them here, best-effort.
# ⚠️ PENDING FABLE QA — ops-path edit. Safe by construction (no git process runs
# during ship.sh, and failure is swallowed), but ship.sh is Fable-lane.
rm -f "$ROOT/.git/HEAD.lock" "$ROOT/.git/index.lock" 2>/dev/null || true

[[ -d "$DST" ]] || { echo "[ship] ERROR: no snapshot at $DST (fat app not provisioned?)"; exit 1; }
[[ -d "$APP" ]] || { echo "[ship] ERROR: $APP not found"; exit 1; }

# ── contract gate (runs BEFORE anything is copied) ────────────────────────────
# The gate used to be a manual step, which means it was a step that could be — and
# was — skipped. Now the ONLY way past a red gate is to say so out loud.
if [[ "${SHIP_SKIP_GATE:-0}" == "1" ]]; then
  echo "[ship] WARNING: SHIP_SKIP_GATE=1 — THE CONTRACT GATE WAS SKIPPED."
  echo "[ship]          You are shipping code whose upstream contracts are unverified."
else
  echo "[ship] contract gate: scripts/verify.sh"
  GATE_RC=0
  bash "$ROOT/scripts/verify.sh" || GATE_RC=$?
  if [[ "$GATE_RC" -eq 1 ]]; then
    echo "[ship] REFUSING TO SHIP - the contract gate FAILED (output above)."
    echo "[ship]   NOTHING was copied and the app was not touched."
    echo "[ship]   Fix the failures, or ship anyway with:  SHIP_SKIP_GATE=1 ./scripts/ship.sh"
    exit 1
  elif [[ "$GATE_RC" -ne 0 ]]; then
    echo "[ship] REFUSING TO SHIP - the contract gate COULD NOT RUN (reason above)."
    echo "[ship]   NOTHING was copied and the app was not touched."
    echo "[ship]   Fix that, or ship anyway with:  SHIP_SKIP_GATE=1 ./scripts/ship.sh"
    exit 1
  fi
fi

echo "[ship] repo → snapshot (panel, bridge, scripts, guards, policies)"
cp -R "$ROOT/bridge/panel/." "$DST/bridge/panel/"
# EVERY top-level bridge module, not just app.py: app.py now imports sibling modules
# (bridge/voice.py, Phase B) and copying only app.py would ship an app.py whose import
# target does not exist in the snapshot. app.py degrades gracefully if voice.py is
# missing, but the snapshot must simply carry the whole package.
# ⚠️ PENDING FABLE QA — ship.sh is the critical ops path and the manifest-merge note
# in CLAUDE.md makes changes here Fable-lane. This one is minimal and additive (same
# destination dir, no new semantics, subdirectories untouched), and the alternative
# was a bridge that cannot import on the first ship. Flagged, not assumed.
for _m in "$ROOT"/bridge/*.py; do
  cp "$_m" "$DST/bridge/$(basename "$_m")"
done
# ⚠️ AND THE TWO PACKAGE DIRECTORIES, WHICH THE GLOB ABOVE DOES NOT REACH. app.py is a
# FACADE since the router/core split (2026-08-28): the routes and the logic live in
# bridge/core/*.py and bridge/routers/*.py, and app.py imports them. Shipping only the
# top-level *.py would put a 250-line facade into the snapshot with nothing behind it —
# the bridge would not import at all, which is the loudest possible version of this
# failure and still worth spelling out, because the glob LOOKED complete for a year.
# Everything else under bridge/ (tests/, contract_tests/, __pycache__/) stays out, as
# it always has: the snapshot runs the bridge, it does not test it.
#
# ⚠️ RECURSIVE, NOT A FLAT GLOB — AND FENCED (bug-echo W-02). `cp "$pkg"/*.py` ships ONE
# LEVEL. The comment above says why the packages must be copied at all, but the glob
# itself repeated the shape of the near-miss it exists to fix: the day either package
# grows a SUBpackage (`bridge/core/foo/*.py`), the snapshot silently loses it and the
# bridge fails to import IN THE APP while the repo runs perfectly. So: every `*.py` at
# every depth, with its directory structure. __pycache__ still never travels.
_pkg_pys() {   # every .py under bridge/$1, relative to it, __pycache__ pruned
  ( cd "$ROOT/bridge/$1" 2>/dev/null \
    && find . -name '__pycache__' -prune -o -name '*.py' -print ) | sed 's|^\./||'
}
for _pkg in core routers; do
  [[ -d "$ROOT/bridge/$_pkg" ]] || continue
  mkdir -p "$DST/bridge/$_pkg"
  while IFS= read -r _f; do
    [[ -n "$_f" ]] || continue
    mkdir -p "$DST/bridge/$_pkg/$(dirname "$_f")"
    cp "$ROOT/bridge/$_pkg/$_f" "$DST/bridge/$_pkg/$_f"
  done < <(_pkg_pys "$_pkg")
done
# AND THE FENCE, because "recursive today" is not "recursive for ever": a future edit
# that reverts to a glob, or a single copy that fails, must STOP THE SHIP rather than
# leave a snapshot that cannot import. Every .py the repo's packages hold must be in the
# snapshot, by path. This is the assertion the flat glob never had.
_missing=""
for _pkg in core routers; do
  [[ -d "$ROOT/bridge/$_pkg" ]] || continue
  while IFS= read -r _f; do
    [[ -n "$_f" ]] || continue
    [[ -f "$DST/bridge/$_pkg/$_f" ]] || _missing="$_missing bridge/$_pkg/$_f"
  done < <(_pkg_pys "$_pkg")
done
if [[ -n "$_missing" ]]; then
  echo "[ship] ERROR: these package modules did not reach the snapshot:$_missing"
  echo "[ship]   The snapshot is INCOMPLETE — the bridge in the app would fail to"
  echo "[ship]   import. Nothing was restarted. Fix the copy above and ship again."
  exit 1
fi
for d in scripts guards policies; do
  [[ -d "$ROOT/$d" ]] && mkdir -p "$DST/$d" && cp -R "$ROOT/$d/." "$DST/$d/"
done

# ── the TOP-LEVEL docs/*.md, and only those ───────────────────────────────────
# ⚠️ PENDING FABLE QA — ops-path edit, flagged rather than assumed, per the note above.
#
# WHY IT IS HERE AT ALL. The panel's Help view (roadmap §2.4) renders
# docs/USER-EXPLAINERS.md through /api/help/explainers, which reads it off ROOT — and
# ROOT in the fat app is the SNAPSHOT. Nothing copied docs/ before this line, so Help
# would have been permanently empty in the only place it matters while working
# perfectly in the repo. That is the exact shape of the bridge/{core,routers} near-miss
# above, so it gets the same treatment: an explicit copy with the reason next to it.
#
# WHY `*.md` AT THE TOP LEVEL AND NOT `cp -R docs/`. docs/handoff (972K) and
# docs/research (596K) are session archaeology and internal briefs — they are not
# shipped product, and a recursive copy would put them in the user's Application
# Support folder for no reason. Seven files, ~136K, is what the app can actually use.
# A `docs/` subdirectory that becomes shippable later must be added deliberately.
#
# NOT FENCED like the package copy, and that is a judgement, not an omission: a missing
# bridge/core/*.py means the bridge cannot import, which must stop the ship; a missing
# explainer means the Help view shows its named empty state ("run ./scripts/ship.sh"),
# which is a degradation the user can read and act on. It must not block a ship.
if [[ -d "$ROOT/docs" ]]; then
  mkdir -p "$DST/docs"
  for _d in "$ROOT"/docs/*.md; do
    [[ -f "$_d" ]] && cp "$_d" "$DST/docs/$(basename "$_d")"
  done
fi

# Swift shell: recompile only when main.swift is newer than the installed binary.
if [[ "$ROOT/app/main.swift" -nt "$APP/Contents/MacOS/Harness" ]]; then
  echo "[ship] main.swift changed → recompiling the shell"
  if [[ ! -f "$ROOT/app/Config.swift" ]]; then
    cat > "$ROOT/app/Config.swift" <<EOF
// generated by ship.sh — do not edit
let harnessRoot = "$ROOT"
let fatBuild = true
EOF
  fi
  swiftc -O "$ROOT/app/main.swift" "$ROOT/app/Config.swift" -o "$APP/Contents/MacOS/Harness"
  codesign --force --sign - "$APP"
fi

# harness.yaml is NEVER copied wholesale (the snapshot's copy holds LIVE state:
# installed flags, runner.model, aux.model). But a NEW component or build pin added
# in the repo would then never reach the app — its card simply never appears. So:
# ADDITIVE merge only. Existing keys/values in the snapshot are never touched; new
# components arrive as installed:false (install state is per-machine).
# Pick a python that HAS pyyaml. The bridge venv always does; a bare system python3
# often does NOT — and skipping silently there would hide a missing component card
# (exactly the failure this merge exists to prevent), so a miss is loud.
MERGE_PY=""
for _c in "$DST/data/bridge-venv/bin/python" "$ROOT/data/bridge-venv/bin/python" python3; do
  if "$_c" -c "import yaml" >/dev/null 2>&1; then MERGE_PY="$_c"; break; fi
done
if [[ -z "$MERGE_PY" ]]; then
  echo "[ship] WARN: no python with pyyaml found — MANIFEST MERGE SKIPPED."
  echo "[ship]       New components will NOT get a Mission Control card until this is fixed."
else
"$MERGE_PY" - "$ROOT/harness.yaml" "$DST/harness.yaml" <<'PY'
import sys, shutil, datetime, yaml
# CRITICAL: safe_dump writes an EMPTY value as the literal `null`, and the shell
# readers (awk/sed in start_component.sh) then take the 4-char string "null" as a
# real value — e.g. `runner.binary:` (empty = auto-discover) became
# `runner.binary: null` and every model load died with "not executable: null".
# Emit None as a truly empty scalar so an empty key round-trips as an empty key.
yaml.add_representer(type(None),
                     lambda d, _v: d.represent_scalar('tag:yaml.org,2002:null', ''),
                     Dumper=yaml.SafeDumper)
src_p, dst_p = sys.argv[1], sys.argv[2]
try:
    src = yaml.safe_load(open(src_p)) or {}
    dst = yaml.safe_load(open(dst_p)) or {}
except Exception as e:
    print(f"[ship] WARN: could not read a harness.yaml ({e}) — manifest merge skipped")
    sys.exit(0)
added = []
for k, v in src.items():
    if k not in dst:
        dst[k] = v; added.append(k)
for section, force in (("components", True), ("build", False)):
    s, d = src.get(section), dst.get(section)
    if isinstance(s, dict) and isinstance(d, dict):
        for name, cfg in s.items():
            if name not in d:
                if force and isinstance(cfg, dict):
                    cfg = dict(cfg); cfg["installed"] = False; cfg["enabled"] = False
                d[name] = cfg; added.append(f"{section}.{name}")
if added:
    shutil.copy2(dst_p, dst_p + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    # keep only the 5 newest backups (Fable QA: unbounded .bak accumulation)
    import glob, os
    baks = sorted(glob.glob(dst_p + ".bak-*"))
    for old in baks[:-5]:
        try: os.remove(old)
        except OSError: pass
    with open(dst_p, "w") as f:
        yaml.safe_dump(dst, f, sort_keys=False, default_flow_style=False)
    print("[ship] manifest: added " + ", ".join(added) + " (snapshot backed up)")
else:
    print("[ship] manifest: up to date (" + str(len(dst.get("components") or {})) + " components)")
PY
fi

echo "[ship] restarting app + bridge (components stay up)"
pkill -x Harness 2>/dev/null || true
sleep 2
lsof -ti tcp:8700 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true
sleep 1
open "$APP"

# 90s, not 30: a cold snapshot bridge (imports + registry read) can legitimately
# take longer than 30s, and the old loop then FELL THROUGH and printed "bridge is
# up" regardless — a false green that reads as a successful ship.
SHIP_WAIT_S=90
UP=0
printf "[ship] waiting for the bridge"
for _ in $(seq 1 "$SHIP_WAIT_S"); do
  if curl -sf http://127.0.0.1:8700/status >/dev/null 2>&1 || \
     curl -sf http://127.0.0.1:8700/ >/dev/null 2>&1; then
    UP=1; break
  fi
  printf "."; sleep 1
done
echo

if [[ "$UP" -ne 1 ]]; then
  echo "[ship] BRIDGE DID NOT COME UP within ${SHIP_WAIT_S}s — check data/logs/bridge.log (tail below)"
  if [[ -f "$DST/data/logs/bridge.log" ]]; then
    tail -15 "$DST/data/logs/bridge.log" || true
  else
    echo "[ship] (no $DST/data/logs/bridge.log yet)"
  fi
  exit 1
fi

# An EMPTY curl body still hashes — to da39a3ee (sha1 of nothing). Printing that as
# a "fingerprint" alongside "bridge is up" is how a half-started bridge looked green.
API_JSON="$(curl -s http://127.0.0.1:8700/openapi.json 2>/dev/null || true)"
# ⚠️ THE SNAPSHOT FINGERPRINT IS OVER THE WHOLE APP LAYER, NOT app.py ALONE. It used
# to hash bridge/app.py, which WAS the app layer; since the router/core split
# (2026-08-28) app.py is a 250-line facade that a normal slice never touches, so that
# hash would have printed the same eight characters ship after ship — a "did my code
# actually land" signal that says yes to everything. Sorted so it is reproducible.
SNAP="$(python3 -c '
import hashlib, sys, pathlib
b = pathlib.Path(sys.argv[1]) / "bridge"
h = hashlib.sha1()
for p in sorted(list(b.glob("*.py")) + list(b.glob("core/*.py")) + list(b.glob("routers/*.py"))):
    h.update(p.name.encode()); h.update(p.read_bytes())
print(h.hexdigest()[:8])' "$DST" 2>/dev/null || echo none)"
if [[ -z "$API_JSON" ]]; then
  echo "[ship] bridge is up (fingerprint unavailable (bridge still starting?), snapshot app layer $SNAP)"
else
  MARK="$(printf '%s' "$API_JSON" | python3 -c 'import sys,hashlib; print(hashlib.sha1(sys.stdin.buffer.read()).hexdigest()[:8])' 2>/dev/null || echo none)"
  echo "[ship] bridge is up (api fingerprint $MARK, snapshot app layer $SNAP)"
fi
# ── optional component restarts, RUN FROM THE SNAPSHOT ────────────────────────
# From the snapshot, not the repo: the app's venv is the upgraded one and the repo's
# is a different install. start_component.sh is a full restart by construction (stop
# → listener-scoped port clear → re-seed guards → relaunch), so it does strictly more
# than the panel's Stop/Start buttons.
if [[ ${#RESTART[@]} -gt 0 ]]; then
  for _c in ${RESTART[@]+"${RESTART[@]}"}; do
    echo "[ship] restarting component '${_c}' FROM THE SNAPSHOT (${DST})"
    if bash "$DST/scripts/start_component.sh" "$_c"; then
      echo "[ship] restarted: ${_c}"
    else
      echo "[ship] WARN: restart of '${_c}' FAILED (output above) — check ${DST}/data/logs/${_c}.log"
    fi
  done
fi

echo "[ship] REMINDER: components stay up - a vendored upgrade needs: ./scripts/ship.sh --restart <name>"
echo "[ship] done — the served code now matches the repo. ⌘R open tabs if the panel looks stale."
