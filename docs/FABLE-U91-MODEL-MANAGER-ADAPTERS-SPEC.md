# U91 — add model sources only with an inventory and launch contract

**Date:** 2026-09-05  
**Status:** researched; conditionally open for a future supported manager.

## Existing architecture

M.O.T already separates two facts:

- filesystem structure says whether bytes at a path look structurally usable;
- a manager adapter says whether that manager still lists an item in its library.

LM Studio has both a public local catalog (`lms ls --json`) and existing M.O.T launch
paths for its GGUF/MLX entries, so source-specific membership is justified there. Jan
is currently a filesystem import source whose paths M.O.T knows how to launch. Local
M.O.T downloads and recognized audio Hugging Face cache entries have their own launch
contracts. No manager is global truth.

## Current machine evidence

- LM Studio CLI is installed and already has a validated adapter.
- Jan CLI is installed, but its inspected model directories contain no current model
  inventory to use as a black-box manager-removal counterexample.
- Ollama is not installed.
- Hugging Face cache directories exist, but a cache is a download cache—not an
  authoritative list of models a particular application manages or can launch.

Adding speculative adapters now would advertise found bytes without proving identifier,
removal, availability and launch semantics. That is the same shortcut U82 rejected.

## Required slice for any new source

For each manager independently:

1. identify a documented or black-box-stable whole-catalog API and unavailable/error
   behavior;
2. define stable manager identity separately from mutable path/display name;
3. prove managed removal, retained bytes, moved bytes, unplugged volume, path reuse and
   catalog-schema drift;
4. implement the corresponding M.O.T engine/format launch contract before displaying
   the row as runnable;
5. reconcile into existing `models.json` under the shared registry transaction—never a
   second catalog file;
6. preserve hide/pin/sampling/user metadata and fail closed on ambiguous legacy rows;
7. walk import, load, switch, restart, removal and repeated rescan on the real manager.

## Current decision

No new adapter is added in this wave because no additional installed manager currently
supplies both a provable inventory and a M.O.T launch contract. U91 remains deliberately
conditional, with this evidence preventing “scan more folders” from masquerading as
provider support.
