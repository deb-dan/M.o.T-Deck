#!/usr/bin/env bash
# Migrate GGUF models out of Jan's data folder into harness ownership (data/models/),
# then re-seed the registry. Part of the "make the harness Jan-free" cleanup slice.
#
# For each  ~/Library/Application Support/Jan/data/llamacpp/models/<id>/  that holds a
# model.gguf, move the WHOLE folder to  data/models/<id>/  (same volume = instant rename;
# no copy). Then run scripts/seed_registry.py, which now scans data/models/ as source
# "local" (Jan's folder yields nothing once empty) and carries each model's existing
# ctx forward (so the 35B's 95536 from Jan's router.preset.ini survives the move).
#
# Idempotent-ish: a folder already present at the destination is SKIPPED (never
# clobbered) and reported, so a re-run after a partial migration is safe.
set -euo pipefail
cd "$(dirname "$0")/.."

JAN_MODELS="$HOME/Library/Application Support/Jan/data/llamacpp/models"
DEST="data/models"
mkdir -p "$DEST"

if [[ ! -d "$JAN_MODELS" ]]; then
  echo "[harness] no Jan models dir at: $JAN_MODELS"
  echo "[harness] nothing to migrate — re-seeding registry from data/models/ only."
  python3 scripts/seed_registry.py
  exit 0
fi

moved=0 skipped=0
for folder in "$JAN_MODELS"/*/; do
  [[ -d "$folder" ]] || continue
  id=$(basename "$folder")
  # Only migrate folders that actually contain a model.gguf.
  [[ -f "$folder/model.gguf" ]] || { echo "[harness] skip (no model.gguf): $id"; continue; }
  target="$DEST/$id"
  if [[ -e "$target" ]]; then
    echo "[harness] skip (already in data/models): $id"
    skipped=$((skipped+1))
    continue
  fi
  echo "[harness] migrating: $id"
  mv "$folder" "$target"
  moved=$((moved+1))
done

echo "[harness] migrated $moved model(s), skipped $skipped."
echo "[harness] re-seeding registry…"
python3 scripts/seed_registry.py
echo "[harness] done. Verify data/models.json, then start the Runner (panel → Runner → Start)."
