# U91 — add model sources only with an inventory and launch contract

**Date:** 2026-09-05; installed-source recheck 2026-09-06
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
- M.O.T's isolated Unsloth Studio on port 8899 exposes authenticated inventory routes
  (`/api/models/local`, `/api/models/list`, `/api/inference/models`) and load/validate/
  unload routes. That makes it a legitimate candidate, unlike scanning its folders.
- The same machine also has a standalone Unsloth installation on port 8888. Its
  `~/.unsloth` state is explicitly outside M.O.T authority; an adapter may query only
  M.O.T's isolated `data/unsloth-home` service and may never merge the two by product
  name or a common filesystem shape.

The installed M.O.T Unsloth API currently requires its user-owned bearer session. M.O.T
has no machine-owned API key or supported server-to-server authentication handoff for
those inventory routes. Reusing a browser cookie, reading the auth database, or copying
the user's password would violate the source's ownership boundary. An inventory API
that the bridge cannot authenticate to safely is not yet an adapter contract.

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

No new adapter is added in this wave. Unsloth is now the first evidence-backed candidate
because it supplies both inventory and launch operations, but it still lacks a safe
M.O.T-owned machine-auth contract. A future slice must first create an API credential
through an upstream-supported user-visible action, store it in M.O.T's protected local
store, prove it is scoped to the isolated :8899 instance, and revoke/rotate it without
touching the standalone :8888 installation. Only then may the adapter map inventory
rows to exact Unsloth load semantics and walk import, load, unload, restart and removal.

Jan remains a retired architecture whose empty application-support residue and installed
CLI do not justify resurrecting a manager adapter. Ollama remains absent. Hugging Face
cache scanning remains cache discovery, never manager membership. This evidence keeps
“scan more folders” from masquerading as provider support.
