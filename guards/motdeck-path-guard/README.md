# motdeck-path-guard

Fences Hermes **file writes** behind the same human-approval gate that dangerous
shell commands use. Upstream Hermes leaves `write_file` / `patch` approval-ungated by
design; this plugin escalates writes that land outside an allowlist and hard-blocks a
small set of secret directories.

* **Source of truth:** `guards/motdeck-path-guard/` in MOT Deck repo.
  `scripts/start_component.sh` seeds it to `~/.hermes/plugins/motdeck-path-guard/` on
  every Hermes start (copy-if-changed) and ensures `plugins.enabled` in
  `~/.hermes/config.yaml` contains `motdeck-path-guard`. **Never hand-edit the seeded
  copy** — the next start overwrites it.
* **Mechanism:** the upstream `pre_tool_call` hook. `{"action":"approve"}` routes the
  call through `tools.approval.request_tool_approval` (the identical gate used for
  Tier-2 dangerous commands), so the MOT Deck panel renders its existing approval card
  with no UI work. `{"action":"block"}` vetoes the call outright.
* **Policy:** `policy.yaml` (re-read on every gated call — edits apply without a
  restart). `allow` = session workspace `{HERMES_CWD}`, `~/.hermes`,
  `{MOT_DECK_ROOT}/data`, `/tmp`, `{TMPDIR}`. `deny` = `~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/Library/Keychains`, `~/.hermes/config.yaml`. deny is checked first and wins.
* **Matching:** `os.path.commonpath([target, root]) == root` on realpath'd absolute
  paths. Never string prefixes (`/Users/testuserEvil` must not match `/Users/testuser`).
* **Fail-closed:** unresolvable target (V4A multi-file patch), missing/unparseable
  policy, or any internal exception → escalate to the human gate. Never a silent allow.

## Honest limits

* Covers `write_file` and `patch` **only**. A write performed by a shell command
  (`terminal` redirect, `execute_code`) is not seen here — those ride upstream's
  dangerous-pattern gating. Full shell coverage needs an OS sandbox (`sandbox-exec`),
  deliberately deferred.
* Reads and exfiltration are out of scope.
* The bridge's independent audit tier emits a `guard_flag` frame (panel: a faint
  `⚠ wrote outside workspace: <path>` line) whenever a completed write lands outside
  the same allowlist — so a disabled or misconfigured plugin is still visible.

Tests: `bridge/tests/test_path_guard.py` (pure matcher) and the pin-bump gate in
`bridge/contract_tests/test_hermes_ws_contract.py::test_path_guard_hook_contract`.
