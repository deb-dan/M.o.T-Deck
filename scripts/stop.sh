#!/usr/bin/env bash
# Stop bridge and any component processes the harness started.
#
# ⛔ PROCESS-KILL RULE (CLAUDE.md; U19 echo sweep 2026-08-29). Everything stopped here
# is stopped because we can PROVE it is ours: a pid we wrote to data/<comp>.pid whose
# identity still checks out, or a listener on OUR bridge port whose command line names
# THIS tree. Nothing is ever matched by product name — Debi runs standalone copies of
# the apps we embed, and `pkill -f "uvicorn bridge.app:app"` (what used to be the last
# line of this file) would also have stopped another harness root's bridge, or an
# unrelated project's, without ever saying so.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_ABS="$(pwd)"

_proc_cmd() { ps -o command= -p "$1" 2>/dev/null | tr '\n' ' '; }
# The ownership rule lives in ONE place — start_component.sh's `--owner-check` seam —
# so stop.sh can never drift from the rule Start enforces.
_owner_ok() { bash scripts/start_component.sh --owner-check "$1" "$2" >/dev/null 2>&1; }

for pidfile in data/*.pid; do
  [[ -e "$pidfile" ]] || continue
  comp="$(basename "$pidfile" .pid)"
  pid="$(tr -cd '0-9' < "$pidfile" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    cmd="$(_proc_cmd "$pid")"
    if _owner_ok "$comp" "$cmd"; then
      echo "[harness] stopping $comp (pid $pid)"
      kill "$pid" || true
    else
      # Pids are recycled: a stale pidfile must never become a stranger's death warrant.
      echo "[harness] $pidfile names pid $pid ($cmd) — that is NOT our $comp (recycled pid?);"
      echo "[harness]   leaving it alone and discarding the stale pidfile."
    fi
  fi
  rm -f "$pidfile"
done

# The bridge has no pidfile: the app spawns it as its own child and stops what it
# started. Reap only a listener on OUR bridge port whose command line names this tree.
BR_PORT=$(awk '/^bridge:/{f=1} f && /^  port:/{print $2; exit}' harness.yaml 2>/dev/null || true)
[[ "$BR_PORT" =~ ^[0-9]+$ ]] || BR_PORT=8700
for pid in $(lsof -ti tcp:"$BR_PORT" -sTCP:LISTEN 2>/dev/null); do
  cmd="$(_proc_cmd "$pid")"
  [[ -z "$cmd" ]] && continue           # vanished between the probe and the check
  if [[ "$cmd" == *"$ROOT_ABS"* ]]; then
    echo "[harness] stopping bridge (pid $pid, :$BR_PORT)"
    kill "$pid" 2>/dev/null || true
  else
    echo "[harness] :$BR_PORT is held by pid $pid ($cmd) — not this harness; left alone."
  fi
done
echo "[harness] stopped."
