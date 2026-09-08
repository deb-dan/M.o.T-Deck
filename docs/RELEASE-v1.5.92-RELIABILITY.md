# Existing-feature reliability release — 2026-09-08

v1.5.91 is installed and verified. v1.5.92 is the prepared follow-up for two newly
reproduced session defects; the final installation receipt below will distinguish
preparation from shipping. This report supersedes the unshipped and native-coverage
statements in the earlier `REVIEW-2026-09-08-EXISTING-FEATURES.md`, whose initial
source-review evidence is retained as history.

## Changes

The v1.5.91 release contains the earlier Direct reasoning/completion/Stop fixes,
serialized download controls, storage parent-identity and rollback protection,
partial-clear receipts, stale-dialog response protection and captured-selection
model settings. Its release self-review additionally serialized settings writes per
model, so an older save cannot overtake Reset, and disabled Install selected when
no eligible optional tool is selected. No feature, design, theme or control was
removed, no upstream source was patched, and no pending roadmap feature was started.

The v1.5.92 corrections are confined to the existing Odysseus integration:

- Failed single-conversation deletion previously erased local attachment and
  reasoning sidecars despite upstream refusal. Cleanup now requires successful
  deletion. Tests use actual SQLite sidecars, readable PNG bytes and a neighboring
  conversation; 403, 404, 500 and disconnected requests preserve them, while a
  successful deletion clears only the target. The upstream's protected/starred
  session refusal is therefore respected too.
- Odysseus stores UTC timestamps without an offset. JavaScript interpreted those as
  local time, making a new conversation say “3h” in Tallinn. The provider adapter
  now makes UTC explicit. Tests execute the actual panel formatter against API
  responses in UTC, Tallinn and New York, with fractional seconds and an already
  explicit offset. No global date parser or upstream timestamp implementation was
  changed.

The first session regression run reproduced four failures (two data-loss cases and
two Tallinn timestamps). The expanded focused run passed all 14 session cases and
the real HTTP download journey. The download test is now a permanent repository
test: a disposable loopback server stalls a real httpx transfer, pause closes the
old writer, concurrent resume calls make one Range request, and the final 2 MiB
payload is byte-exact with one registration. It does not download real model files.

## Installed v1.5.91 evidence

The clean FAT build was bound to `65f356b`, version 1.5.91, with zero dirty files.
Both the built app and the read-only mounted DMG passed deep strict signature,
identity and version checks. Every one of the 12,544 seed-owned regular files
matched its manifest; test directories were absent. The installed v1.5.90 bundle
and live code were backed up before the recoverable bundle replacement and standard
`scripts/ship.sh` deployment.

The installed app and bridge reported 1.5.91. All ten components retained their
installed/running state and pins. The live manifest, actual protected secret file,
model registry and navigation file were byte-identical across deployment. A native
sampling edit and Reset later restored the registry to its original bytes.

Native Swift/WebKit journeys used the exact `/Applications/MOT Deck.app`:

- A disposable chat streamed numbers 1–60 through a native reload and return to
  Chat, with exactly one user prompt and one answer. Reload lands on Main; this
  does not claim persistence of the selected top-level view.
- A second disposable turn was stopped with the actual Stop button. The bridge
  recorded terminal state `stopped` and one partial answer (numbers 1–17), which
  remained in history. This was partial-answer cancellation, not reasoning-only
  cancellation.
- An inactive GGUF model's sampling value was saved and reset; another MLX model
  displayed its own fields. The load-settings overlay opened. The running model
  was never switched, ejected or reloaded for these checks.
- Factory reset preview showed a matching seed and only the canonical support
  root, preserving external/shared stores. Its typed-confirmation Apply stayed
  disabled. Preview/cancel was visually checked in Editorial, Warm Paper, Luxury
  Gold, Cyber, Studio dark and Studio light; the original appearance was restored.
- Install selected was visibly disabled when all available optional tools were
  already installed. Dialog close/Escape paths were exercised.

The reported app-opening issue was clarified by the user as temporary interference
while this native automation was using the app. No speculative shell change was
made for it.

The v1.5.91 final gate passed 583 contracts (four optional checkout skips), 775
repository Python tests and all 53 JavaScript programs. The four skipped Aider
contracts were separately executed against the installed supported Aider runtime,
including valid and invalid edit-format parsing, and passed. The follow-up output
bundle records that execution in `aider-runtime.log`.

## Reproduction and release procedure

From the canonical repository:

```sh
data/bridge-venv/bin/python -m pytest bridge/tests/test_session_integrity.py bridge/tests/test_download_http.py -q
./scripts/verify.sh
./scripts/build_app.sh --fat
./scripts/ship.sh
```

Build from a clean versioned commit; verify the app and mounted DMG before replacing
the installed bundle. Preserve the previous signed app and code snapshot first.
Never copy the repository's YAML template or data directory over live state.

Evidence and rollback artifacts are outside the repository in the sibling
`outputs/motdeck-release-v1.5.91/` and `outputs/motdeck-release-v1.5.92/` directories.
The previous `outputs/motdeck-review-2026-09-08/` bundle covers only the original
source candidate through `d497539`; use the newer release rollback instructions for
the installed release.

## Coverage limits

This is a verified correction of existing behavior, not a completed line-by-line
review of approximately 181,000 first-party lines. U170 remains the sole remaining
assurance record. Destructive native reset/uninstall/recovery, every load-settings
interaction under every design, and real remote model-download interruption were
not executed against user data. The corresponding isolated regression tests and
preview evidence must not be described as those destructive installed journeys.
Existing U139 history-idempotency limits remain unchanged. Two existing non-failing
Starlette/httpx test deprecation warnings remain; no dependency upgrade was added.

All changes are local commits, with recoverable prior installed bundles and code
snapshots. There is no schema migration, upstream fork or user-state replacement.
