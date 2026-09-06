# FABLE SPEC — U61/U62 atomic configuration and truthful bridge ownership

**Date:** 2026-09-05 · **Orchestrator:** GPT-5.6 Sol · **Builder:** GPT-5.6 Terra
**Binding:** `CLAUDE.md`, `docs/DOCTRINE-PROACTIVE-BUILD.md`, live-state, process-kill,
app-layer registration and reporting doctrines.

## Destination

A reader of `motdeck.yaml` sees either the complete old document or complete new one,
never a truncated intermediate. Concurrent writers cannot silently erase each other's
key changes. `data/bridge.pid` names a live owning bridge and is removed on every clean
shutdown path without deleting a newer bridge's claim.

## U61 — one locked atomic writer

In `bridge/core/yamlset.py`, add one private transaction helper used by
`_set_yaml_model`, `_set_runner_model`, and `_set_yaml_scalar`:

1. Acquire a process-local lock and an advisory `fcntl.flock` on a sibling lock file.
2. Read the latest YAML bytes only after the lock is held.
3. Apply a supplied line-preserving transformation. Do not round-trip through PyYAML;
   comments, ordering, blank/null semantics, final-newline shape and unrelated bytes
   remain intact.
4. Write a uniquely named tempfile in the same directory; preserve the target mode;
   flush and `fsync`; `os.replace` onto the target; best-effort fsync the directory.
5. On any exception, unlink only the transaction's tempfile and leave the original
   bytes untouched. Release locks in `finally`.
6. Byte-identical transformations do not replace the inode or alter mtime.

Do not use a shared fixed `motdeck.yaml.tmp`, which makes concurrent writers collide.
Do not lock readers: atomic replacement is what makes shell `awk` and `cfg()` safe.
Writer serialization is required because atomic individual writes alone still permit
lost updates when two routes read the same old document.

Tests: thousands of concurrent scalar/model writes with a simultaneous reader that
must parse every observation; unrelated keys/comments survive; spaces/empty values;
missing block/key; simulated write/fsync/replace failures preserve original; mode
preserved; no temp leak; no-op byte/mtime stable; two subprocess writers retain both
changes.

Echo-sweep every `motdeck.yaml` writer in Python/shell. Either route each legitimate
writer through this helper/its equivalent transaction or prove it already uses a safe
targeted atomic writer. Whole-file repo→snapshot copies remain forbidden.

## U62 — explicit lifecycle release

Refactor `bridge/core/singleton.py` so claim ownership exposes one idempotent
`release_claim(root,pid=None)` function. It removes the pidfile only when its complete
contents still equal this process's PID. `atexit` remains belt-and-braces but calls the
same function.

After FastAPI exists, register `release_claim` in `app.router.on_shutdown` (matching the
project's non-deprecated startup-list precedent). `routers/quitall.py`'s hard-exit
fallback and any other bridge-specific cleanup route call the same helper rather than
duplicating unlink logic. `ship.sh` may clean after a dead bridge, but only after
identity/death verification; it must never blindly delete a claim now owned by a new
bridge.

Tests:

- shutdown callback removes own claim;
- replaced/newer claim survives old callback and atexit;
- repeated release is harmless;
- stand-down newcomer never removes incumbent claim;
- hard-exit preparation calls the shared release;
- real scratch uvicorn SIGTERM exits and leaves no pidfile;
- shutdown timeout/hard exit leaves no own pidfile;
- stale/recycled/permission-denied PIDs never authorize a signal or foreign unlink.

## Boundaries/report

No live app/snapshot/YAML, vendor, version, commit or push. Tests use temporary roots
and a self-owned scratch uvicorn only. Report echo sweep, concurrency evidence, lifecycle
journeys, adversarial findings, unwalked live journey, and **HONEST LIMITS**. Sol owns
live QA, docs, version and ship.
