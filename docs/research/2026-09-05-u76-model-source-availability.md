# U76 — Distinguish deleted artifacts from an unavailable model library

Status: shipped in v1.5.79 on 2026-09-05 after the complete fixture and real-stack
journeys below passed. The live walk also exposed first-to-second Rescan key-order churn;
deterministic atomic serialization plus a byte-equality fast path fixed it, and a
corrupt-UTF-8 recovery regression found during echo review is permanently covered.

Decision-complete build brief. U75 supplies one structured, read-only artifact probe;
U76 persists the minimum evidence needed to decide whether a later `missing` result
means the artifact was deleted from an available filesystem or its whole filesystem is
currently unavailable. The unplugged-volume protection remains, but it may no longer
resurrect confirmed deletions merely because every model was deleted.

## One persisted evidence shape

On a `ready` U75 probe, persist this optional row field during an explicit Rescan:

```json
"artifact_evidence": {
  "v": 1,
  "real_path": "/absolute/path/observed/while/ready",
  "device": 16777234,
  "mount_root": "/Volumes/Models",
  "manifest": {"kind": "gguf", "files": ["model.gguf"]}
}
```

Use the probe's existing names-only manifest; do not hash or recursively size weights.
`mount_root` is the deepest mounted ancestor of the ready artifact, derived by walking
parents with `os.path.ismount`/device boundaries. `/` is a valid mount root. Evidence is
identity/availability metadata, never authority to move, delete, or rewrite an artifact.
Unknown or incomplete probes do not replace prior ready evidence.

`scripts/seed_registry.py` is the only evidence writer. Rescan already owns the atomic
registry rewrite and is the explicit user action that prunes; ordinary GET/status polls
must not add another writer. Preserve `artifact_evidence` across scanner merges with the
same user-owned carry-forward discipline as hidden, voice, and settings fields. A fresh
ready observation replaces it with v1 evidence. Audio rows remain outside this slice.

## Source-availability verdict

Add a stdlib-only pure/read-only helper beside `artifact_probe`:

```python
source_availability(entry, probe=None) -> {
  "state": "available" | "unavailable" | "unknown",
  "reason": "...",
  "detail": "..."
}
```

Rules:

1. A non-`missing` artifact probe does not need source inference; return `available`
   for `ready`/`incomplete`, `unknown` for `unknown`.
2. Missing artifact + valid v1 evidence: stat `mount_root` only. It is `available` when
   the root exists as a directory, is still a mount point (except `/`, which is always
   the root mount), and its `st_dev` equals persisted `device`.
3. Missing mount root, no longer a mount, or a different device at the same path is
   `unavailable`. This covers an unplugged external disk and a disconnected mount whose
   old mountpoint has fallen back to the system volume. Do not call that deletion.
4. Permission, timeout, symlink-loop, malformed evidence, non-integer device, relative
   paths, or any other uncertain observation is `unknown`.
5. A missing artifact on an available matching mount is a confirmed deletion for
   registry/catalog purposes. The exact prior file manifest need not still exist; that
   is the fact being decided.
6. A legacy row without evidence is `unknown`, not available. It receives the cautious
   migration path below.

## Replace the blanket all-missing guard

Both `modelreg.offerable()` and `routers.models._persist_absent()` currently abstain
when every otherwise eligible path is missing. Replace that count-based guess with the
source verdict:

- `ready` remains offerable and clears `absent` on Rescan;
- `incomplete` remains excluded under U75 and is never rescued by U76;
- `missing` on an `available` matching mount is excluded; Rescan removes it unless it
  is pinned/live, in which case it persists `absent:true` exactly as today;
- `missing` on an `unavailable` mount retains the old cable protection: keep the row,
  do not set `absent`, and do not prune it;
- `missing` with `unknown` legacy evidence also abstains for safety until a confirmed
  observation or explicit confirmation;
- probe `unknown` always abstains and clears debounce streaks.

This logic is per row, not “all rows at once”. One ready local model must not cause the
rows on an unplugged external volume to be declared deleted, and one unavailable volume
must not protect missing rows on an available system disk.

Catalog consumers still receive `modelreg.offerable()` as their one answer. When every
row is unavailable/legacy-unknown, seeders retain their existing non-empty configuration
under their established empty-registry guard. When confirmed deleted rows coexist with
ready rows, those deleted ids leave every generated catalog on that Rescan.

## Legacy migration and explicit confirmation

An old registry can first encounter U76 while all artifacts are already missing, so no
ready evidence exists to classify its mount. Preserve those rows and make Rescan return
an honest, non-success confirmation response listing only ambiguous ids. The response:

```json
{"ok": false, "requires_confirmation": true,
 "ambiguous_missing": ["id-a", "id-b"],
 "log": "…could be an unavailable library…"}
```

The panel shows that sentence and a deliberate `Remove missing entries` confirmation.
The confirmed POST carries `{"confirm_missing": true, "ids": [...]}`. The bridge passes
the exact ids to `seed_registry.py`; the script prunes only still-missing,
still-legacy-unknown, non-protected rows in that set. It must re-probe at execution time,
refuse ids not named by the preview, and retain pinned/live rows as `absent:true`.
No second-click, retry count, header, or blanket flag counts as consent.

If this UI/API addition exceeds the existing Rescan surface's safe scope, the minimum
acceptable migration is a CLI-only explicit `seed_registry.py --confirm-missing ID`
with the API returning the exact command; silently deleting legacy ambiguous rows is not
acceptable.

## Implementation protocol and module budget

The confirmation flow is transactional and machine-readable; do not make the router
scrape human prose:

- Preserve the current human-readable `seed_registry.py` invocation. Add `--json` for
  bridge use and repeatable `--confirm-missing ID` arguments for explicit consent.
- JSON mode emits one document with `ok`, `count`, `pruned`, `flagged`,
  `requires_confirmation`, and `ambiguous_missing`. A preview that needs consent exits
  with a distinct documented code (use 3), writes neither registry nor catalogs, and
  reports sorted unique ids. Ordinary failures remain nonzero and are not mislabeled as
  confirmation.
- `POST /api/models/rescan` continues accepting an empty body. It also accepts the exact
  confirmation object above, invokes JSON mode, maps the preview exit to HTTP 409, and
  runs the catalog fan-out only after a successful registry transaction.
- Confirmation is all-or-nothing. Recompute the plan and re-probe every supplied id.
  If any id is not in the current ambiguous set, refuse the whole write. A reappeared row
  survives; a protected still-ambiguous row is retained with `absent:true`; only named,
  still-missing, legacy-unknown, non-protected rows are pruned.
- Validate persisted evidence before any stat: `v == 1`; absolute `real_path` and
  `mount_root`; integer-but-not-bool device; mount root is an ancestor of real path; and
  a names-only manifest object. Malformed evidence is `unknown` and never authorizes a
  prune. Never follow a registry-provided relative mount path.
- Keep `bridge/routers/models.py` below the binding 1,500-line ceiling (it begins this
  slice at 1,461). If the route cannot stay comfortably below the fence, extract the
  complete Rescan route/planner seam into a purpose-named router module and register it
  through the existing facade/app-source machinery; do not compress unrelated code or
  raise the ceiling.
- The panel confirmation must render the exact preview ids, require a deliberate second
  action labelled `Remove missing entries`, send those exact ids, and clear stale consent
  after any new Rescan result. A failed/changed confirmation never claims removal.

## Permanent journeys

1. ready system-disk GGUF/MLX Rescan persists v1 evidence and is idempotent;
2. deleting it while `/` and the same device remain available excludes and prunes it;
3. a protected deleted row becomes `absent:true` and is not offered;
4. an external mount disappears: row/evidence remain, no absent flag, no prune;
5. the mountpoint falls back to another device: unavailable, not deletion;
6. replugging the same device + ready artifact refreshes evidence and clears absence;
7. mixed local deletion plus unplugged external rows decides each independently;
8. malformed/relative evidence and stat errors are unknown and never destructive;
9. incomplete artifacts are excluded and never rescued as cable-loss;
10. all confirmed deletions no longer trigger the old blanket resurrection;
11. all unavailable rows retain the established catalog-preservation behavior;
12. legacy all-missing Rescan previews exact ids and changes nothing;
13. explicit confirmation prunes only re-probed ambiguous ids, while a reappeared or
    protected id survives;
14. every downstream catalog drops confirmed deletions and preserves the no-empty-write
    contract for a wholly unavailable library;
15. audio, hidden rows, and live YAML remain byte/behavior unchanged.

Run focused registry/model/catalog/UI tests, the complete contract gate, all
pytest-compatible and standalone Python suites, all JavaScript suites, script hygiene,
Bash 3.2 syntax, and `git diff --check`. The builder is bound by `CLAUDE.md` and
`docs/DOCTRINE-PROACTIVE-BUILD.md`; no live registry/YAML/model/process/port,
snapshot/app/vendor/archive, VERSION/docs/commit/push/ship mutation. Sol owns independent
review, the live deletion/cable-safe simulation with temporary fixtures, versioning and
release.
