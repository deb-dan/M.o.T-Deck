#!/usr/bin/env bash
# verify.sh — THE repository gate. Run the pinned-upstream contracts, repository
# Python corpus and every JavaScript suite, and say clearly whether the gate passed,
# failed, or could not be run at all.
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
CONTRACT_SUITE="$ROOT/bridge/contract_tests"
REPO_SUITE="$ROOT/bridge/tests"

if [[ ! -d "$CONTRACT_SUITE" || ! -d "$REPO_SUITE" ]]; then
  echo "[verify] CANNOT RUN: required test suites are missing."
  echo "[verify]   contracts: ${CONTRACT_SUITE}"
  echo "[verify]   repository: ${REPO_SUITE}"
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
echo "[verify] contracts : ${CONTRACT_SUITE}"
echo "[verify] repository: ${REPO_SUITE}"

# JavaScript suites are standalone Node programs. Prefer the runtime bundled for
# DeepSeek on an installed/fat tree, then the snapshot's, then PATH. A missing Node
# is CANNOT RUN rather than a silent partial pass (U49's original failure mode).
SNAP_NODE="${HOME}/Library/Application Support/Harness/data/node/bin/node"
NODE=""
for _n in "${ROOT}/data/node/bin/node" "$SNAP_NODE" node; do
  if "$_n" --version >/dev/null 2>&1; then NODE="$_n"; break; fi
done
if [[ -z "$NODE" ]]; then
  echo "[verify] CANNOT RUN: no Node.js runtime was found for bridge/tests/*.js."
  echo "[verify]   tried: ${ROOT}/data/node/bin/node"
  echo "[verify]          ${SNAP_NODE}"
  echo "[verify]          node (whatever is on PATH)"
  exit 2
fi
echo "[verify] node  : ${NODE} ($("$NODE" --version))"
_manifest_digest() {
  if [[ -f "$ROOT/harness.yaml" ]]; then
    shasum -a 256 "$ROOT/harness.yaml" | awk '{print $1}'
  else
    printf 'absent'
  fi
}
MANIFEST_BEFORE="$(_manifest_digest)"
TEST_RC=1
if ( cd "$ROOT" &&
     "$PY" -m pytest bridge/contract_tests/ -q &&
     "$PY" -m pytest bridge/tests/ -q &&
     for _js in bridge/tests/*.js; do
       echo "[verify] javascript: ${_js}"
       "$NODE" "$_js" || exit 1
     done ); then
  TEST_RC=0
fi
MANIFEST_AFTER="$(_manifest_digest)"
if [[ "$MANIFEST_AFTER" != "$MANIFEST_BEFORE" ]]; then
  echo "[verify] FAIL - the contract suite modified the tracked harness.yaml."
  echo "[verify]   Tests must redirect every state writer to a fixture; the changed"
  echo "[verify]   manifest has been left visible for forensic review, not concealed."
  exit 1
fi
if [[ "$TEST_RC" -eq 0 ]]; then
  echo "[verify] PASS - contracts, repository Python and JavaScript are green."
  exit 0
fi

echo "[verify] FAIL - the repository gate did NOT pass (test output above)."
echo "[verify]   Contracts pin vendored integration; repository suites pin product"
echo "[verify]   behavior, UI affordances, ceilings and incident echoes."
exit 1
