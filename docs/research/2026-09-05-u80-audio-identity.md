# U80 — One audio artifact, one registry row

Decision-complete build brief for the duplicate Parakeet row found in the live
post-ship acceptance walk.

## Measured defect

`parakeet-tdt-0.6b-v3` appears twice with the exact same on-disk directory: an existing
`source: download` row is preserved by `seed_registry.merge()`, then
`scan_audio_local()` re-derives the same directory as a new `source: local` row. The
HF-cache collision rule already drops its weaker rediscovery; the local scan lacks the
equivalent artifact-identity rule.

## Required behavior

Change only audio merge identity in `scripts/seed_registry.py` and its permanent tests.
Do not fold this into U75's chat artifact-integrity predicate.

Before adding a freshly scanned local audio row, compare it with already-kept
non-rescanned audio rows using a normalized absolute real path for the primary artifact.
If the path identifies the same file/directory, keep exactly the existing row and drop
the re-derived local row—even if the ids differ. The existing row is authoritative
because it can carry download provenance, verification context, voice/reference choices,
and other user keys a filesystem scan cannot reconstruct.

For an id collision whose canonical paths are genuinely different, do not discard a
real second artifact. Retain the existing row and give the fresh local row the same
deterministic `-local` collision suffix discipline that LM Studio rows receive, extending
the suffix if needed to remain unique. Keep its human name unchanged. This distinction
prevents path aliases/symlinks from duplicating one artifact while avoiding silent loss
of two separately stored copies that happen to share a folder/model id.

Path normalization is identity only, never permission to follow/delete/copy the target.
An absent/unresolvable path cannot be declared identical to a different row. Preserve
all current chat merge behavior, HF-cache precedence, user-key carry-forward, and
atomic writer behavior.

The reverse journey already enters through `downloads._registry_add`, which drops a
same-id local row and appends the richer completed download row. Add a contract test for
that direction rather than reimplementing it in the scanner.

## Permanent journey tests

1. existing downloaded Parakeet + local rescan of the same real directory → one
   untouched download row;
2. the local path is a symlink alias of the download path → one row;
3. same path but different ids → one authoritative existing row;
4. same id at two different real directories → both remain, fresh row gets deterministic
   `-local` id; a second identical merge is stable and adds no third row;
5. local-first then completed download through `_registry_add` → one download row and
   the local-only row's id is replaced;
6. chat rows and HF-cache audio collision behavior remain unchanged.

Run focused audio/registry/download tests, `scripts/verify.sh`, standalone suite sweep,
and `git diff --check`. The builder is bound by `CLAUDE.md` and
`docs/DOCTRINE-PROACTIVE-BUILD.md`; no live rescan, generated data, snapshot/app/YAML,
process, port, vendor/archive, VERSION/docs/commit/push/ship mutation. Sol owns the live
rescan and release proof.
