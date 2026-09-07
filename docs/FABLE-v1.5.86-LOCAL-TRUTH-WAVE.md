# v1.5.86 local truth, lifecycle and media-compatibility wave

**State:** implemented release candidate; not shipped or closed until the checklist at
the end passes. **Canonical root only:** `New Harness/MOT Deck`. The protected former
project is read-only context and is never an edit, cleanup or migration source.

This file is the decision and evidence record for U153. It prevents the many small
changes in this wave from collapsing into a vague “polish” release and records what was
intentionally not changed.

## 1. Measured memory and advisory policy — S5 / S6

- The runner's own successful startup segment is parsed for model, KV, recurrent-state,
  compute and output allocations. Ownership evidence binds a sample to the exact launched
  runner rather than to whatever happens to write the log.
- Per-model predicted-versus-measured records are bounded and written atomically at mode
  `0600`. A malformed or stale segment produces no invented measurement.
- Guardrail preferences are Quiet, Advise, Advise early and Custom headroom. Main and Aux
  consult the same preference. The default remains Advise and no mode becomes a hard
  blocker.
- Custom headroom changes the fit calculation itself; it is not copy pasted on top of a
  contradictory backend verdict. “Accepted” warnings are remembered per model.
- This closes the requested S5/S6 scope. A6 remains open for real MLA, non-Gemma SWA, MLX
  and projector calibration inputs that do not exist on this machine.

## 2. Restored and compacted UI surfaces — S10 / S13 / S17 / S18 / S20

- Aider follows the shared app theme/design keys without recolouring xterm's terminal
  canvas into an unreadable light terminal.
- Old Comfy gallery rows expose Graph only when the persisted row proves a graph exists.
  Nothing fabricates a missing graph and no 404 button is knowingly painted.
- The seven Audio explanation cards are compact rows with contextual detail. Their
  dependency facts remain available rather than being deleted for visual neatness.
- LOffice's empty AI state is one invitation plus a Help route; the detailed policy stays
  in Help.
- Goose UI's three already-produced logs are reachable through a narrow allowlist. This
  adds read access only and does not broaden arbitrary-path log access.

## 3. Event-led Music and explicit runner semantics — S19 / S30

- Music/Compose receive the existing bridge event shape. One-second progress observation
  remains while a job is active, and a 20-second fallback remains for missed events;
  “event-led” is not falsely described as “no polling whatsoever.” Job-state snapshots
  transition atomically and job IDs use collision-resistant random identifiers.
- Zero/one/many track copy is grammatically correct.
- Runner status publishes `served_id` as the explicit actually-served model while
  `pin_intent` remains the configured choice. Readers were migrated without changing
  the single-model loading behavior.

## 4. Hermes and Agent input truth — A3 / A5

- Hermes stored image markers rehydrate through opaque attachment tokens. The projector
  revalidates exact file identity and returns an unavailable marker rather than leaking a
  path or guessing when bytes moved.
- Agent has a persisted per-turn web-search choice. It remains separate from Browse and
  cannot turn search on when the global capability is unavailable. Direct Chat and Hermes
  never receive the Agent-only flag.
- The installed attachment journey exposed U154: an empty-session Hermes request created
  valid durable IDs but failed inside the stream producer before submission because one
  Python closure name was shared with the stale-session retry branch. Creation and retry
  results are now distinct. The regression fence proves one create, one submit, both IDs,
  a terminal frame and no hidden error; a nominal HTTP 200 alone is explicitly insufficient.

## 5. LOffice durability and human ribbon journey — U7 / U33 / U41

- ONLYOFFICE in-ribbon chat checkpoints move from 20 seconds to 5 seconds through the
  existing serialized writer. This reduces, but does not claim to eliminate, the window
  of loss on hard termination.
- LOffice Quick/Agent turns have an exact per-turn Stop control. Quick honestly stops the
  browser wait without claiming upstream cancellation; Agent also sends Hermes's existing
  exact-session stop and reports acknowledgement or failure. Intentional abort is not
  painted as a transport error.
- Human U7 proof used one uniquely named temporary `.docx`: entered an intentionally
  flawed sentence, selected it, invoked AI → Grammar & Spelling → Check current text,
  observed two successful runner inference tasks and visible spelling/grammar annotations,
  then closed the test tab and deleted only that temporary file and its test backups.
  No existing Office document was changed.
- The plain-DOM Tier-1 workbook interstitial and Univer rollback assets are explicitly
  preserved. S3 grants no deletion authority.

## 6. Exact process lifecycle — U36 / U65

- A restarted bridge may adopt a Goose daemon only from an exact launch-provenance record,
  revalidated against PID plus kernel birth identity. Name, port, executable path and CWD
  remain corroboration at most, never ownership.
- Aux retains the actual child handle where available and reaps that exact owned child.
  Forced PTY termination gets the same reap discipline. No name-based or port-owner kill
  was reintroduced.

## 7. Live Odysseus picker update — U39

- Registry fan-out uses one path: authenticated live PATCH while Odysseus is running,
  offline seeding while it is stopped.
- A live update is allowed only for stable ID `local-jan`, the current runner base URL,
  and a current pinned list matching the prior app marker. A renamed, repointed, disabled
  or hand-curated endpoint is left alone.
- The marker advances only after exact PATCH acknowledgement and authenticated GET
  read-back. This is a catalogue refresh, not Aux creation or U142 key rotation.

## 8. Stock Comfy subgraphs and download truth — S26 / S27

- The converter expands nested `definitions.subgraphs`, array/object links, promoted
  inputs, fan-out and stock DynamicCombo V3 positional children with cycle and resource
  caps. Bypassed/muted subgraphs remain unexpanded.
- All seven previously refused stock templates convert: Basic Switch Node, Flux.2 Klein
  image edit, HiDream O1/dev, Qwen inpainting ControlNet, SD3.5 depth and Wan 2.2 S2V.
  Comfy's own prompt validator found only absent model/media requirements, not subgraph,
  node or dynamic-input errors.
- The existing size metadata store evolved in place; no second registry was created.
  Exact Hugging Face origin `X-Linked-ETag` plus `X-Linked-Size` may provide an LFS
  content SHA-256. CDN ETags and Xet object hashes are not treated as file identity.
  Mutable `/resolve/main` identity is rechecked on GET before writing. Other sources
  remain explicitly size-only.

## 9. U47 local residual and intentional non-closures

- User-controlled Office filenames were removed from model-facing APPLIED/DISMISSED/
  UNDONE/EVICTED outcome lines. Human/API receipts still carry the real name.
- U47 remains open: prompt fences cannot guarantee model compliance, vision fence text is
  visibly noisy, and the upstream authority design remains broader than ideal.
- Pinned Goose v1.48.0 still has no supported session-preview field, database vacuum, or
  REST deletion path. Therefore U26, U28 and U45 remain open; MOT Deck does not read/write
  more private upstream state to manufacture closure.
- U57 remains open. The active Hermes venv is v2026.8.16 / 0.20.2. The 0.20.6
  rolled-forward venv is a retained future retry asset but has a stale pre-rename Python
  symlink and must be rebuilt/repaired before reuse. A separate pre-v2026.8.16 venv has
  the same launcher issue. Neither was deleted.
- U58 remains open. Git currently registers four auxiliary worktrees: two temporary
  Hermes audit trees at commit `e2228c` (already an ancestor of main) with untracked/
  generated contents of unproven ownership, plus two protected former-project worktrees.
  One protected tree is dirty and the other carries a commit not on main. None was edited,
  removed, pruned or used as a source.

## 10. Release acceptance checklist

- [x] Focused adversarial suites for every implementation slice.
- [x] U7 real `.docx` ribbon action and visible result; exact temporary file removed.
- [ ] Full supported `scripts/verify.sh` passes after all candidate/docs changes.
- [ ] `ship.sh` updates the installed app without overwriting live YAML, registries,
      secrets, user files, component state or navigation state.
- [ ] Affected installed surfaces are walked: memory preferences/measurement, Aider
      theme, Audio density, Goose logs, LOffice Stop, Music event/status, Comfy Graph and
      subgraph/download wording, Agent search, Hermes attachment recovery, Odysseus
      catalogue refresh and runner served-ID wording.
- [ ] All ten components and the bridge are healthy; runner pin and served model are
      reported explicitly; optional Aux remains optional.
- [ ] Clean FAT DMG has the correct MOT Deck identity, signature, seed ownership,
      `dirty_files=0`, no test roots, and exact archive/manifest path+digest equality.
- [ ] Only then mark U153 and its completed constituent rows closed, update the current
      indexes, commit, push, and call v1.5.86 shipped.
