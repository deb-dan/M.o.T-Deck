#!/usr/bin/env bash
# verify.sh — THE contract gate. Run the pinned-upstream contract suite and say
# clearly whether it passed, failed, or could not be run at all.
#
# Exists because the gate was skippable by accident: on 2026-08-15 a vendored pin
# bump shipped with `python -m pytest bridge/contract_tests/` printing "No module
# named pytest" and the ship continuing anyway (the suite, run later, caught three
# real failures — one behavioural). A gate that silently does not run is not a gate.
#
#   ./scripts/verify.sh
#
# Exit codes are DISTINCT on purpose (ship.sh branches on them):
#   0  PASS        — the suite ran and every test passed
#   1  FAIL        — the suite ran and something failed
#   2  CANNOT RUN  — no interpreter with pytest, or no suite on disk
#
# Runs against the suite that sits NEXT TO THIS COPY of the script: run the repo's
# copy and you verify the repo; run the snapshot's copy and you verify the snapshot.
set -uo pipefail   # deliberately NOT -e: this script's job is to REPORT, not to die

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUITE="$ROOT/bridge/contract_tests"

if [[ ! -d "$SUITE" ]]; then
  echo "[verify] CANNOT RUN: no contract suite at ${SUITE}"
  exit 2
fi

# pytest is declared in bridge/requirements.txt, so the bridge venv has it after any
# bootstrap/provision. The snapshot's venv is tried too (a repo checkout on a machine
# whose venv lives only in the fat snapshot still gets a gate), then a system python3.
SNAP_PY="${HOME}/Library/Application Support/Harness/data/bridge-venv/bin/python"
PY=""
for _c in "${ROOT}/data/bridge-venv/bin/python" "$SNAP_PY" python3; do
  if "$_c" -c "import pytest" >/dev/null 2>&1; then PY="$_c"; break; fi
done

if [[ -z "$PY" ]]; then
  echo "[verify] CANNOT RUN: no python with pytest was found."
  echo "[verify]   tried: ${ROOT}/data/bridge-venv/bin/python"
  echo "[verify]          ${SNAP_PY}"
  echo "[verify]          python3 (whatever is on PATH)"
  echo "[verify]   pytest IS declared in bridge/requirements.txt, so a fresh bootstrap"
  echo "[verify]   or component install already has it. To fix an EXISTING venv"
  echo "[verify]   (bootstrap creates it with 'uv venv', so it has no pip module and"
  echo "[verify]   'python -m pip install' cannot work there):"
  echo "[verify]     source \"${ROOT}/data/bridge-venv/bin/activate\" && uv pip install pytest && deactivate"
  exit 2
fi

echo "[verify] python: ${PY}"
echo "[verify] suite : ${SUITE}"
if ( cd "$ROOT" && "$PY" -m pytest bridge/contract_tests/ -q ); then
  echo "[verify] PASS - the contract gate is green."
  exit 0
fi

echo "[verify] FAIL - the contract gate did NOT pass (pytest output above)."
echo "[verify]   These tests pin our integration surface against the VENDORED pins."
echo "[verify]   A failure here usually means an upstream moved under us."
exit 1
