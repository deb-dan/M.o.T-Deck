# U75 — One shared model-artifact integrity verdict

Decision-complete build brief. U75 closes the current “directory exists, therefore an
MLX model can load” lie across discovery, every catalog, both launchers, switch
preflight/rollback, and the UI. U76 remains a separate persistence/evidence slice.

## Destination

Every chat-model decision uses one stdlib-only structured probe in
`bridge/core/modelreg.py`:

```python
artifact_probe(entry) -> {
  "state": "ready" | "missing" | "incomplete" | "unknown",
  "reason": "stable-machine-readable-reason",
  "detail": "short user-facing fact",
  "evidence": { ...cheap observed identity/manifest facts... },
}
```

No recursive size walk and no hashing multi-GB weights. The probe reads one directory
listing, small JSON metadata, and direct-file stats only. It never changes files.

`path_present(path, fmt)` remains a three-valued compatibility wrapper. For chat GGUF
and MLX it delegates to the structured probe (`ready=True`, `missing/incomplete=False`,
`unknown=None`). For audio formats it retains the existing type-only behavior; audio
has separate engine-specific validators and U75 must not silently redefine them.
`entry_present()` is the same compatibility mapping for a row. New decision sites use
`artifact_probe()` itself so `missing` and `incomplete` remain distinguishable.

## Integrity rules

### GGUF

- The row path must be a non-empty regular file; a zero-byte file is `incomplete`.
- If its basename matches `NAME-00001-of-000NN.gguf` (or any numbered member of that
  group), require every sibling `1..NN`, all non-empty regular files. Evidence lists the
  required basenames in order. Missing member = `incomplete: missing-shard`; zero/wrong
  member = `incomplete: invalid-shard`.
- A declared `mmproj` must also be a non-empty regular file. A missing/empty declared
  projection makes the row incomplete because the launch line will pass it.
- `scan_lmstudio()` registers one split GGUF group, pointing at part 1 and using the
  suffix-free id; it does not register every shard as a separate model. Size is the sum
  of required shards.

### MLX

- Path must be a directory.
- Direct `config.json` must be a non-empty regular file containing a JSON object.
- At least one direct `.safetensors` file must be a non-empty regular file.
- For every direct `*.safetensors.index.json`, parse a JSON-object `weight_map`; it must
  be a non-empty object. Each referenced value must be a direct basename ending in
  `.safetensors` (no slash, backslash, `.`/`..`, absolute path, or traversal) and every
  unique referenced file must exist as a non-empty direct regular file.
- Without an index, any basename group matching
  `NAME-00001-of-000NN.safetensors` must contain the complete non-empty sequence.
  Ordinary non-sharded multi-file layouts remain valid.
- Malformed config/index, missing/empty required weights, wrong file kind, or partial
  shard set is `incomplete`, not `missing`.

### Unknown versus definite state

- No usable path, permission denial, symlink loop, timeout-like filesystem error,
  unreadable directory/index/config, or any non-absence OS error is `unknown`.
- ENOENT/ENOTDIR at the artifact root is `missing` under U75's existing semantics.
  U76 later uses persisted device/mount evidence to distinguish deletion from a
  detached library; do not pretend U75 can solve that legacy ambiguity.
- Evidence on a `ready` result includes version `v:1`, `real_path`, `device`, and a
  names-only manifest (`kind` plus required direct basenames). Add `mount_root` only if
  it can be derived cheaply and deterministically; U75 does not persist evidence.

## Every consumer that must converge

1. `scripts/seed_registry.py`: Jan/local/LM Studio chat discovery accepts only `ready`;
   correct split grouping and sizes. Scanner errors remain nonfatal and never turn an
   unavailable source into an invented empty/deleted claim.
2. `modelreg.offerable()`: `incomplete` is always excluded. `unknown` remains offered.
   Preserve the all-missing external-volume fallback for U76, but it may fire only when
   every otherwise-eligible row is `missing`; it must never resurrect an incomplete
   artifact or an `absent:true` row.
3. `scripts/start_component.sh` main runner resolver: load `modelreg.py` by path and
   call the shared probe before emitting any launch command. Refuse `missing`,
   `incomplete`, or `unknown` with model id + probe detail and the “Rescan or pick
   another model” cure. A missing helper is a packaging error and fails loud; do not
   fall back to the weak directory/file check.
4. `routers/aux.py::aux_start`: same shared probe before fit advice, kill, log open, or
   process spawn. Return 400 for unavailable artifact with the shared detail.
5. `routers/models.py::api_switch_model`: preflight the selected row before changing
   `runner.model`, setting `_SWITCH.busy`, stopping/restarting anything, or spawning a
   thread. Missing/unregistered is 400; incomplete is 409 with shared detail; unknown is
   409 (safe refusal at a one-shot launch decision, not a deletion claim).
6. `model_file_alive()` and failed-switch rollback accept only `ready`.
7. `core/health.py::file_state_track`: accept a row/structured probe without breaking
   existing path-only callers. Missing keeps the current two-strike
   `checking -> gone` debounce. Incomplete is an immediate stable `incomplete` state
   because the artifact root is observable and structurally broken. Unknown clears the
   streak. A return includes `reason`/`detail`.
8. `components.runner_model_view` and `/api/models`: pass the complete row, surface
   `incomplete`, and use the shared detail. The runner may remain amber/serving if its
   mmap'd weights are live, but the card must say the on-disk artifact will not restart.
9. `bridge/panel/index.html`: exclude `incomplete` everywhere that offers a new load
   (composer picker and aux-setting/load actions), sort it with unavailable rows, and
   show an amber/red “model incomplete” chip with the bridge's specific detail. Keep a
   currently live row visible/ejectable but never offer it as a fresh target. Empty
   picker copy says models are missing or incomplete, not only missing.
10. All catalog seeders continue to consume `modelreg.offerable()`; no per-seeder
    integrity copy is allowed.

## Permanent journey matrix

1. non-zero single GGUF ready/discovered/offered/main+aux launchable;
2. zero-byte GGUF incomplete/excluded/refused before process work;
3. complete split GGUF one row and ready; missing/zero part incomplete;
4. valid MLX config + non-zero weight ready everywhere;
5. empty dir, config-only, missing config, empty/malformed/non-object config, zero-byte
   weight each incomplete everywhere;
6. valid indexed MLX ready; missing/zero indexed shard, empty/malformed weight_map,
   traversal/absolute/nested index target each incomplete;
7. valid non-indexed numbered MLX ready; omitted/zero member incomplete;
8. ordinary several-file non-sharded MLX remains valid;
9. unreadable/stat error becomes unknown, never absent/pruned;
10. an all-incomplete registry produces no offers (the U76 guard cannot resurrect it);
11. an all-missing legacy registry retains U76's current fallback in this slice;
12. main start, aux start, and switch preflight all reject the same broken fixture
    before YAML mutation, port clearing, log creation, or spawn;
13. failed switch refuses rollback to an incomplete prior model;
14. `/api/models`, runner card and composer distinguish incomplete from missing and
    never offer the incomplete row;
15. Hermes, Odysseus, OpenCode, DeepSeek, Goose CLI/UI seeders all receive the same
    ready-only catalog from the shared predicate.

Repair existing fixtures that use empty files/directories as shorthand so they create
minimal valid non-empty artifacts. Do not weaken assertions or special-case tests.

Run focused registry/health/model-load/aux/switch/catalog/panel tests, the complete
contract gate, all pytest-compatible and standalone Python suites, JavaScript suites,
script hygiene, Bash 3.2 syntax, and `git diff --check`. The builder is bound by
`CLAUDE.md` and `docs/DOCTRINE-PROACTIVE-BUILD.md`; no live model/state, app/snapshot,
vendor/archive, VERSION/docs/commit/push/ship mutation. Sol owns independent review,
real-stack journeys, versioning and release.
