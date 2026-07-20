#!/usr/bin/env bash
# M0 tool-calling proof: make Hermes drive the configured model through one shell tool call.
set -uo pipefail
cd "$(dirname "$0")/.."
[[ -d data/hermes-venv ]] || { echo "hermes not installed"; exit 1; }
# shellcheck disable=SC1091
source data/hermes-venv/bin/activate
echo "[harness] Hermes tool-calling smoke test (this runs one real agent task; may take ~30-60s)..."
OUT=$(hermes -z "Use your shell tool to run exactly this command: echo HERMES_TOOLCALL_OK — then reply with only the command's output." 2>&1)
echo "----- hermes output -----"; echo "$OUT"; echo "-------------------------"
if echo "$OUT" | grep -q "HERMES_TOOLCALL_OK"; then
  echo "[harness] PASS — Hermes executed a tool call through the model endpoint. M0 Hermes criterion met."
else
  echo "[harness] FAIL — marker not found. Model may not tool-call reliably, or endpoint misconfigured."
  exit 1
fi
