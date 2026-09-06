#!/usr/bin/env bash
# Stop bridge and any component processes MOT Deck started.
#
# ⛔ PROCESS-KILL RULE (CLAUDE.md; U19 echo sweep 2026-08-29). Everything stopped here
# is stopped because we can PROVE it is ours: a child PID plus birth fingerprint M.O.T
# recorded at launch. A matching path, CWD, name, pidfile, or port is not authority.
# Nothing is ever matched by product name — Debi runs standalone copies of
# the apps we embed, and `pkill -f "uvicorn bridge.app:app"` (what used to be the last
# line of this file) would also have stopped another motdeck root's bridge, or an
# unrelated project's, without ever saying so.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT_ABS="$(pwd)"
ONLY="${1:-}"
[[ -z "$ONLY" || "$ONLY" =~ ^[A-Za-z0-9_-]+$ ]] || {
  echo "[motdeck] invalid component name: $ONLY" >&2
  exit 2
}
FAILED=0

_proc_cmd() { ps -o command= -p "$1" 2>/dev/null | tr '\n' ' '; }
# The ownership rule and the signal are one locked operation. A check followed by a
# shell kill leaves a relaunch race between those two syscalls; this CLI keeps the
# claim lock held through verification, signal, and exact-claim cleanup.
_ownership_cli() {
  local py="$ROOT_ABS/data/bridge-venv/bin/python"
  [[ -x "$py" ]] || py="$(command -v python3 || true)"
  [[ -n "$py" ]] || return 2
  "$py" "$ROOT_ABS/bridge/core/ownership.py" "$@"
}

# Enumerate the UNION of authoritative owner claims and compatibility PID reports.
# Losing a `.pid` report cannot make a valid child unmanageable; conversely, a lone
# `.pid` never gains signal authority. Bash 3.2 has no associative arrays, so the
# newline-delimited seen set performs exact de-duplication.
_seen=$'\n'
for statefile in data/*.owner data/*.pid; do
  [[ -e "$statefile" || -L "$statefile" ]] || continue
  comp="$(basename "$statefile")"
  comp="${comp%.owner}"; comp="${comp%.pid}"
  case "$_seen" in *$'\n'"$comp"$'\n'*) continue ;; esac
  _seen="${_seen}${comp}"$'\n'
  [[ -z "$ONLY" || "$comp" == "$ONLY" ]] || continue
  claim="$(_ownership_cli claim "$ROOT_ABS" "$comp" 2>/dev/null || true)"
  pid="${claim%%$'\t'*}"; birth="${claim#*$'\t'}"
  if [[ "$claim" != *$'\t'* ]]; then
    detail="$(_ownership_cli signal "$ROOT_ABS" "$comp" 0 --birth "" 2>&1 || true)"
    echo "[motdeck] data/${comp}.{owner,pid} has no complete M.O.T launch record;"
    echo "[motdeck]   signalled nothing. ${detail:-Unsafe bookkeeping was left untouched.}"
    FAILED=1
    continue
  fi
  if [[ -n "$pid" ]]; then
    cmd="$(_proc_cmd "$pid")"
    group_arg=()
    [[ "$comp" == "goose" || "$comp" == "goose-ui" ]] && group_arg+=(--group)
    if detail="$(_ownership_cli signal "$ROOT_ABS" "$comp" "$pid" --birth "$birth" --keep-claim ${group_arg[@]+"${group_arg[@]}"} 2>&1)"; then
      for attempt in {1..50}; do
        _ownership_cli matches "$ROOT_ABS" "$comp" "$pid" >/dev/null 2>&1 || break
        sleep 0.1
      done
      if _ownership_cli matches "$ROOT_ABS" "$comp" "$pid" >/dev/null 2>&1; then
        echo "[motdeck] $comp pid $pid survived SIGTERM; its exact claim is retained and it was not replaced."
        FAILED=1
      else
        _ownership_cli retire "$ROOT_ABS" "$comp" "$pid" --birth "$birth" >/dev/null 2>&1 || true
        echo "[motdeck] stopped $comp (pid $pid)"
      fi
    else
      # Pids are recycled: a stale pidfile must never become a stranger's death warrant.
      echo "[motdeck] data/${comp}.owner names pid $pid ($cmd) without a matching live M.O.T launch record;"
      echo "[motdeck]   leaving it alone. ${detail:-The ownership check was unavailable.}"
      FAILED=1
    fi
  fi
done

# THE BRIDGE NOW HAS A PIDFILE (2026-08-30): it writes data/bridge.pid itself at boot
# (bridge/core/singleton.py), so the `data/*.pid` loop above already stops it by the
# same identity-verified rule as every component — and does so first, which is safe
# precisely because components no longer share the bridge's process group.
# A listener sweep is diagnostic only. Losing the launch record does not grant this
# script permission to reconstruct ownership from a path or port.
if [[ -z "$ONLY" || "$ONLY" == "bridge" ]]; then
  BR_PORT=$(awk '/^bridge:/{f=1} f && /^  port:/{print $2; exit}' motdeck.yaml 2>/dev/null || true)
  [[ "$BR_PORT" =~ ^[0-9]+$ ]] || BR_PORT=8700
  for pid in $(lsof -ti tcp:"$BR_PORT" -sTCP:LISTEN 2>/dev/null); do
    cmd="$(_proc_cmd "$pid")"
    [[ -z "$cmd" ]] && continue           # vanished between the probe and the check
    echo "[motdeck] :$BR_PORT is still held by pid $pid ($cmd) without a matching launch record; left alone."
    FAILED=1
  done
fi
if [[ "$FAILED" -eq 0 ]]; then
  echo "[motdeck] stopped${ONLY:+ $ONLY}."
else
  echo "[motdeck] one or more requested processes were left running." >&2
fi
exit "$FAILED"
