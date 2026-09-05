# U82–U85 — Model truth, without a second registry

Status: implemented candidate; repository tests pass; not shipped or versioned yet.

## Premises proved before implementation

- The live LM Studio CLI (`lms ls --json`, CLI commit `07b7252`) reports eight LLMs
  and one embedding. M.O.T's persisted registry contains eleven `lmstudio-import`
  chat rows. A filesystem walk therefore cannot answer whether LM Studio still owns
  a model when the manager leaves its bytes behind.
- LM Studio's observed LLM contract uses `type`, `format`, `modelKey`, `path`, and
  optional display/capability metadata. Paths are relative to its configured model
  root. Embeddings are not chat models and are ignored.
- Unsloth Studio does not supply the missing authority: its local inventory also
  walks LM Studio's storage directories. It is useful evidence for a provider-based
  design (LM Studio, Hugging Face, Ollama, and custom folders are separate sources),
  but it cannot detect a model removed from LM Studio while its bytes remain.
- Filesystem structure and manager membership answer different questions. Neither
  signal is allowed to impersonate the other.

## Contract

1. `data/models.json` remains the only persisted M.O.T registry. There is no catalog
   snapshot or second transaction boundary.
2. Explicit Rescan asks each supported manager adapter for one whole-catalog
   observation. Only a completely validated `available` observation has membership
   authority for rows owned by that manager.
3. LM Studio membership affects only `source: lmstudio-import`. It never removes a
   local, download, Jan, audio, Hugging Face, or future-manager row.
4. CLI absence, timeout, non-zero exit, malformed JSON, unknown LLM format/schema,
   duplicate artifact identity, path traversal, or symlink escape makes the entire
   observation unavailable/unsupported. Existing rows survive and the UI says the
   Rescan was partial.
5. A catalog-listed row survives even when its bytes are missing or structurally
   invalid, so Models can explain both facts. It is not offered for a fresh load.
6. A catalog-removed live/pinned row survives as `unlisted` only so the user can see
   and eject it. It cannot be switched to, pinned afresh, assigned to Aux, or seeded
   into dependent catalogs. Other removed rows leave only `models.json`; no weight
   file is deleted.
7. Ordinary startup never queries LM Studio when a registry already exists. This
   prevents automatic seeding from resurrecting or deleting rows outside an explicit
   Rescan.
8. Legacy missing-row consent is an opaque SHA-256 digest over the complete registry
   revision and exact observed rows, including their canonical paths and evidence.
   Confirmation re-probes under the same registry lock and fails closed if anything
   changed. IDs are display text, not authority.
9. The shared artifact probe now verifies GGUF magic/version, every required GGUF
   shard/projector header, minimally meaningful MLX architecture metadata, and every
   required safetensors header/tensor interval. Its verdict is *structurally ready*,
   not proof that an engine can load or run the model.
10. Audio identity recognizes both current `kind: audio` rows and the supported
    legacy `format: tts-*` / `stt-*` spelling.

## Scope boundary and future adapters

M.O.T currently has a manager-membership adapter only for LM Studio because that is
the manager-backed chat source it imports and can launch in both GGUF and MLX form.
Jan and M.O.T-local folders remain filesystem sources; Hugging Face discovery is
currently audio-specific. Ollama manifests and arbitrary Hugging Face chat caches
must not be surfaced merely because files exist: M.O.T first needs a launch adapter
and a stable identity contract for their native representations. That follow-up is
ledgered rather than silently implied by the LM Studio fix.

## Permanent counterexamples

- eleven structurally valid files, only eight manager rows → eight listed rows;
  all eleven files remain untouched;
- manager command unavailable after a successful observation → no membership
  deletion and a visible partial warning;
- manager removes a row but leaves its valid bytes → registry row leaves on explicit
  Rescan;
- protected removed row → visible `unlisted`, unavailable to every fresh action;
- preview missing path A, replace with missing path B under the same ID → old token is
  rejected and path B survives;
- one-byte GGUF/safetensors and `{}` MLX config → structurally incomplete;
- manager path traversal/symlink escape or unknown format → reject the whole catalog;
- format-only legacy audio row plus current local row at the same real path → one row.

## Release boundary

Passing unit/contract gates makes this a candidate only. Closure requires a clean
real-stack explicit Rescan, independent comparison with `lms ls --json`, proof that
the unnamed screenshot rows no longer return after bridge/app restart, verification
of every dependent picker, and confirmation that no model file changed.
