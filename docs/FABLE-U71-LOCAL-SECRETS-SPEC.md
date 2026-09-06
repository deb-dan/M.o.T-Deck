# U71 — local secret storage and explicit existing-install cutover

**Date:** 2026-09-05  
**Status:** done-verified for M.O.T-managed credentials; auxiliary rotation is U142.

## Proven premise

The tracked manifest historically carried the Odysseus administrator password and
fixed runner/Aux API keys. Copying, committing, restoring, or comparing that manifest
therefore copied credentials as though they were configuration. The U74 incident also
proved that the live manifest is operational state and must not be rewritten wholesale.

## Authority and non-goals

- `data/.env.local` is the one local launch-secret store. It is a no-follow regular
  file, mode `0600`, atomically replaced and directory-fsynced.
- `motdeck.yaml` retains the four keys as blank documented schema fields. It is not a
  secret fallback after migration.
- The store contains runner and Aux API keys plus the Odysseus administrator user and
  password. Values use lossless base64url encoding so punctuation is data, not shell
  syntax. Newline, carriage return, NUL, duplicate, unknown, partial, symlink, special
  file, oversized, and group/world-readable inputs fail closed.
- Minted end-user API keys remain in their existing key store. The Hermes dashboard
  token remains in its existing generated token file. Neither is silently merged here.
- Shipping code never silently rotates credentials. Existing-install migration is an
  explicit, redacted operator action.

## Fresh install

Bootstrap provisions all four high-entropy values before a dependent component is
installed. Installers call the idempotent provisioner and never replace an already
complete store. Every launch consumer reads the typed manifest overlay through the
same semantic reader and refuses a missing/partial secret instead of launching with an
empty key.

## Existing-install transaction

`scripts/migrate_local_secrets.py plan <snapshot>` prints only states and affected
components. `apply` performs this order:

1. Parse and validate the complete current YAML/store state without printing a value.
2. If Odysseus is installed, require it to be reachable and authenticate with either
  the current or already-staged credential. A requested rotation preserves the
   administrator username and generates a new password and managed runner API key.
   It preserves an existing Aux key: that value may already be copied into a
   user-owned Odysseus Background Tasks endpoint which M.O.T cannot yet update
   transactionally.
3. Atomically create and verify the complete `0600` store.
4. Change the Odysseus password using its authenticated API, then verify the new login
   through an independent client before removing the previous plaintext copy.
5. Blank only the four YAML scalar spans through the shared locked, atomic,
   line-preserving writer. Every unrelated byte and comment must survive.
6. Report the exact installed consumers that require restart; do not restart anything
   implicitly.

Before a successful Odysseus cutover, failure removes only the store created by that
invocation and leaves YAML unchanged. After the password is changed and independently
verified, failure retains the new store: deleting the only working credential would
lock M.O.T out. The next run must be able to resume safely.

Runner-key rotation is not complete until every managed consumer is quiesced or
rebound. Aux is launched through the Models API, not `start_component.sh`, and M.O.T
does not own the Background Tasks endpoint configuration which consumes its key.
Migration therefore relocates that key without rotating or restarting Aux. A future
Aux rotation requires a read/update/verify/rollback adapter for that endpoint and must
not start an intentionally stopped model. A live release requires old-runner-key
rejection and new-key success at runner, Odysseus, Hermes, OpenCode, DeepSeek,
VoiceStudio, and newly opened Goose/Aider sessions; the preserved Aux key must still
work if Aux was active.

## Permanent evidence

- fresh weak-default replacement and custom-value preservation;
- punctuation round trip and no plaintext value in the store;
- partial/corrupt/duplicate/symlink/special/insecure store refusal;
- failed atomic replacement leaves the old store byte-identical;
- exact manifest-byte preservation outside the four scalars;
- old/new Odysseus login preflight, failed change rollback, and post-change verification;
- installed-component restart plan and active-Aux handling;
- every production launch path refuses an absent required secret;
- no historical weak literal remains in tracked production configuration.

## Release ceiling

Repository tests prove only the parser, migration transaction, and launch wiring.
U71 closes only after the canonical installed snapshot is migrated explicitly, all
installed consumers restart through their proven ownership paths, old credentials are
rejected, new credentials work, the YAML contains no secret, and a second migration is
idempotent.

## Installed-stack closure evidence

The canonical snapshot was migrated explicitly. The four live manifest secret fields
are blank, `data/.env.local` is a no-follow `0600` store, the runner secret no longer
appears in its process arguments, and the migration is idempotent. Old managed runner
credentials were rejected after restart; the protected key completed real Hermes-tool,
Odysseus Agent, OpenCode, DeepSeek, VoiceStudio, and Goose UI requests. The Goose control
used one newly minted temporary key/provider, received exactly `U51-GOOSE-KEY-OK`, then
removed only that provider/key, restarted the runner, and proved zero remaining minted
keys while restoring `MOT Deck (local)` on the original live model.

The preserved auxiliary key was relocated, not rotated. M.O.T does not own the user's
Odysseus Background Tasks endpoint row, so rotating that key without an update/verify/
rollback adapter would be another partial transaction. That separate, explicit scope is
recorded as U142; it does not reopen the completed M.O.T-managed secret migration.

Post-journey cleanup found one non-secret upstream Goose residue: its confirmed provider
deletion removed the temporary provider definition but left that provider's inert
enable/model stanza in Goose's own `config.yaml`. The exact temporary stanza was removed;
the original provider/model remained active, its definition remained intact, Goose's
secret store was empty, and M.O.T still reported zero minted keys. The repeatable
upstream cleanup gap is recorded separately as U144 rather than hidden beneath U51.
