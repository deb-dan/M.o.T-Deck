# U24/U25/U66 — launch provenance is the only signal authority

Status: implementation candidate; not shipped or versioned.

## Rejected premise

The first draft said a command path or process CWD beneath the project could prove
ownership. It cannot: a user can manually start a server from that directory. It also
preserved `HARNESS_PORT_TAKEOVER=1`, which let a configured port override the process
kill doctrine. Both decisions are rejected.

## Binding rule

M.O.T may signal only either:

1. a process object it just spawned and still holds directly; or
2. a PID for which M.O.T wrote an ownership record at spawn time, whose recorded PID
   and kernel process-start fingerprint still match while the shared ownership lock is
   held through the signal and exact-claim cleanup.

A process name, command substring, executable path, CWD, configured port, matching
service response, plain PID file, or combination of those facts may explain a refusal
but cannot establish launch provenance. A vanished recorded PID permits record cleanup,
not a signal. An unreadable or legacy record fails closed.

## Record and lifecycle

- Every shell `_detached` launch and every Python `Popen` launch calls the same
  stdlib-only `bridge/core/ownership.py` primitive from the actual child handle.
  `data/<component>.owner` (`v1`, PID, high-resolution kernel birth identity) is the authority;
  the compatibility `data/<component>.pid` is reporting only.
- On macOS the birth identity comes from `proc_pidinfo(PROC_PIDTBSDINFO)` as
  seconds plus microseconds; on Linux it is `/proc/<pid>/stat`'s start tick. The
  tempting `ps lstart` value is rejected because it has only one-second resolution:
  adjacent processes can share it. If the platform cannot provide a strong birth
  identity, ownership recording and signalling fail closed.
- Record, signal, release, and stale cleanup share one per-component advisory lock.
  Writes use unique same-directory temporary files and replace. If a new child cannot
  be fingerprinted/recorded, the code stops that exact child handle and reports the
  failure; it does not leave an unmanageable process behind.
- Reaping reads the authoritative claim, confirms the live kernel start stamp, and
  signals before releasing the exclusive claim lock. PID reuse, a planted PID,
  missing owner file, mismatched owner file, and malformed records all refuse. Stale
  bookkeeping is removed only while the same lock excludes a concurrent relaunch.
- Port clearing never adopts a listener. It signals only when the listener PID is the
  exact currently verified ownership record for that component. Otherwise Start/Stop
  reports the collision and asks the user to stop that application explicitly.
- Runner readiness verifies that the sole listener is the exact child already recorded.
  It no longer rewrites the PID file from a path/name-based port observation.
- `HARNESS_PORT_TAKEOVER` is removed from production and tests. There is no hidden
  override that means “kill the stranger anyway.”
- Force changes only TERM to KILL after ownership succeeds; it never weakens identity.

## Deployment boundary

Pre-candidate processes carry legacy PID files but no birth records. New code must not
adopt them. Before first ship, QA will inventory every live listener and legacy PID file,
then stop the verified old stack while the old release is still in control. After ship,
components start fresh and create v1 ownership records. If the pre-ship inventory is
ambiguous, deployment stops for user direction rather than guessing.

## Permanent adversarial matrix

- same engine/product name on the configured port, no record → no signal;
- manually started from M.O.T's CWD/path, no record → no signal;
- plain PID file planted with a stranger's PID → no signal;
- owner record copied to a different PID or birth stamp → no signal;
- PID reused after recorded process exits → no signal;
- exact recorded child, including an external runner binary → signal permitted;
- exact record but listener belongs to another PID → neither listener is signalled;
- a new child records while an old stop is between signal and cleanup → the recorder
  waits, then its new claim survives intact;
- unreadable `ps`/record, malformed file, permission error → no signal;
- multiple listeners → only exact recorded child could qualify, but ambiguous launch
  readiness fails rather than adopting any listener;
- Bash 3.2, spaces in paths, detached process groups, graceful/force signals, and
  component-specific refusal messages remain gated.

Live tests may spawn and signal only their own scratch children. They never place an
existing machine PID into a test record and never exercise a port takeover.
