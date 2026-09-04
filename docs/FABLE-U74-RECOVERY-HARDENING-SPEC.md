# FABLE SPEC — U74 recovery hardening (unshipped candidate after v1.5.76)

**Authority:** Debi's 2026-09-05 authorization to repair the project.
**Orchestrator:** GPT-5.6 Sol (the current Fable role).
**Builder:** GPT-5.6 Terra, only from this decision-complete brief.
**Binding:** `CLAUDE.md`, `docs/DOCTRINE-PROACTIVE-BUILD.md`, the live-state rule,
the process-kill rule, and the model-identity/delegation protocol preserved in
`docs/handoff/archive/CLAUDE-ARCHIVE-2026-07--08.md`.

## 0. Destination

A repository candidate that cannot repeat either half of the U74 incident:

1. a YAML null spelling can never be mistaken for an executable/model path by the
   runner launcher; and
2. YAML-dependent component seeders select an interpreter that actually imports
   PyYAML, with one shared resolution rule and a loud, actionable absence verdict.

The ship command must also refuse to print a green bridge verdict unless the control
API itself answers. Static panel HTML is not health.

This slice changes the repository copy only. It MUST NOT read, copy, edit, start,
stop, or inspect the installed snapshot under `~/Library/Application Support/Harness`,
`/Applications/{Harness,M.O.T}.app`, or any original project/app directory. It must not run
`scripts/ship.sh`, because that command targets those live locations. Validation uses
temporary fixtures and repository tests only. Therefore the final report must say
**implemented and slice-verified, not shipped to the live app**. The full-suite baseline
has one unrelated known red (U77), so “repository-verified” is not available yet.

## 1. Root cause and conservation laws

- The repository `harness.yaml` is a template. A provisioned snapshot's
  `harness.yaml` is live state. Whole-file repo-to-snapshot copies are forbidden.
- The manual recovery used ordinary `yaml.safe_dump`, which emitted an empty value as
  literal `null`. `scripts/start_component.sh` parsed the file with `awk`; the string
  `null` was non-empty, selected the explicit `runner.binary` branch, and failed with
  `runner.binary is not executable: null`.
- `scripts/ship.sh` already registers a representer that emits Python `None` as an
  empty scalar. Keep it. Writer-side normalization is useful but cannot be the only
  defense: hand edits and other valid YAML writers exist.
- A YAML null scalar has these standard spellings for this boundary: an empty value,
  `~`, and case-insensitive `null`. Quoted `"null"` is real text, but the current shell
  parser does not preserve quote semantics. Do not pretend it does. This slice may
  conservatively normalize the unquoted scalar spellings the template/runtime use;
  replacing every shell YAML read with a full parser is a separate architectural
  migration, not a recovery patch.
- Never touch `vendor/`. Never terminate a process. Never bind a live component port.

## 2. Implementation — exact decisions

### A. One shell scalar normalizer

In `scripts/start_component.sh`, add a small pure helper near the other shared shell
helpers:

- input: one already-extracted scalar;
- output: empty for whitespace-only, `~`, or case-insensitive `null`;
- otherwise: the original value unchanged;
- no file writes and no subprocesses.

Apply it to every path/model-like value read from `harness.yaml` where an empty value
has semantic meaning, not just `runner.binary`. At minimum cover:

- `runner.binary`;
- `runner.model`;
- `aux.model` and any equivalent optional model selector;
- component token/path values whose empty form triggers generation or discovery.

The builder must first enumerate all `awk`/`sed` scalar reads in this script and include
an audit table in the report: location, key, whether null normalization is required,
and why. Do not mechanically normalize numeric or boolean fields whose existing
validation already rejects/falls back safely.

### B. One YAML-capable Python resolver

Extract the DeepSeek `DS_PY` search into a shared shell helper. Its output is an
interpreter path and success/failure is explicit. Candidate order remains:

1. this root's bridge venv;
2. the provisioned snapshot bridge venv (compatibility only; tests must not touch it);
3. the currently active `python3`;
4. the currently active `python` where present.

Each candidate must pass `import yaml`. Paths containing spaces remain one argv item.
Use the helper in:

- the DeepSeek seeder and its independent read-back check;
- the Hermes provider seeder and YAML-dependent follow-up snippets.

If no candidate exists, both components may continue starting, but they must print one
decidable warning naming the missing provider/config consequence and the cure. A seeder
that prints a warning and exits zero is not enough by itself.

**Explicit exclusion:** do not route `seed_odysseus_jan.py` through this helper. That
script does not import YAML and must retain Odysseus's activated Python because it
imports `core.database` and `src.settings` from the vendored application.

### C. Ship health verdict

In `scripts/ship.sh`:

- the health wait must succeed only on `GET /api/status`;
- `/` or `/status` static/page availability is not a substitute;
- exhaustion must return non-zero with an actionable sentence;
- do not open/restart the app after the first `/api/status` wait has already failed;
- preserve the existing 90-second cold-start allowance unless tests prove a safer
  equivalent.

Do not change snapshot-copy semantics, backup rotation, process shutdown/startup, app
launching, or component restart behavior in this slice.

## 3. Permanent gates

Add repository tests that execute or source isolated helper logic without starting a
component:

1. scalar matrix: empty, whitespace, `~`, `null`, `Null`, `NULL` become empty; ordinary
   model ids and executable paths survive byte-for-byte;
2. a temporary harness fixture with `runner.binary: null` follows auto-discovery rather
   than the explicit path failure;
3. `runner.model: null` produces the existing honest “model not set” refusal, never a
   lookup for a model literally named `null`;
4. the Python resolver selects the first candidate that can import YAML, skips an
   executable Python without YAML, and fails loudly when none qualifies;
5. Hermes and DeepSeek call the shared resolver; no bare YAML-dependent seeder call
   remains;
6. Odysseus retains its own activated `python` path;
7. ship health source contract: only `/api/status` can set the green variable and the
   timeout has a non-zero exit path.

Run all directly affected suites, the script hygiene test, the entire
`bridge/contract_tests/` gate, and the entire `bridge/tests/` suite. A suite command
whose exit code masks failures is itself a failure; capture pytest's real exit code.

## 4. Adversarial and bug-echo pass

- Search every first-party YAML writer for `safe_dump` and record whether it preserves
  blank scalars, writes files consumed by shell parsing, and writes atomically.
- Search every shell YAML scalar reader for null-as-text exposure.
- Search every Python-script launch in component arms for dependency/interpreter drift;
  fix only YAML-dependent instances in this slice and ledger distinct classes.
- Search every green/readiness verdict in `ship.sh` for a page-response-as-health
  shortcut.
- Verify the repository template and fixtures are unchanged except deliberate test
  additions. No live-state file enters the diff.

## 5. Version, ledger, commit, and acceptance

- Do not bump `VERSION` in this repository-only slice. `CLAUDE.md` defines a versioned
  slice as gate + `ship.sh`; live shipping is forbidden here. The eventual authorized
  live ship may become `1.5.77` only after its real-stack journey passes.
- Update U74 with the code closure and accurate verification boundary. Correct U69 so
  it no longer proposes moving Odysseus to the wrong interpreter; close only the
  Hermes/DeepSeek YAML-interpreter class actually fixed.
- Preserve the pre-existing U74 coda deliberately; it is relevant incident evidence.
- The repository-candidate commit must not claim a `v1.5.77:` release.
- Commit explicit paths only. Do not stage or modify `vendor/hermes` or unrelated dirty
  files.
- Push only after Sol/Fable reviews the complete diff and test evidence.

Acceptance states are exact:

- **slice-verified:** affected suites, contract tests, adversarial fixtures, script
  hygiene, and syntax are green; the full sweep has only a proven unchanged baseline red;
- **repository-verified:** every full gate is green against this copy (not achieved in
  this candidate because the pre-existing U77 modularity fence remains red);
- **shipped:** forbidden to claim until Debi separately authorizes touching the live
  snapshot and the real restart/model-selection journey is walked to a final authenticated
  `/api/status` truth.

## 6. Builder report

Return: files changed; the scalar-reader audit table; the YAML-writer echo table; tests
and exact counts/exit codes; any oddity or spec mismatch; honest limits. Make no commit,
push, live-app action, or version bump—the Sol/Fable acceptance pass owns those.
