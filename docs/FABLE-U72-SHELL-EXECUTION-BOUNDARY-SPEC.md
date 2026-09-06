# U72 — an OS execution boundary, not command-string theatre

**Date:** 2026-09-05; upstream rechecked 2026-09-06
**Status:** current-main upstream candidate prepared; not released, pinned or shipped.

## Proven premise

`guards/harness-path-guard` controls declared file-tool operations. Hermes's foreground
local terminal calls host Bash from `LocalEnvironment._run_bash`, while background pipe
and PTY terminal calls spawn separately in `ProcessRegistry.spawn_local` and
`_spawn_local_pty`. Current upstream `execute_code` does not spawn per call: it acquires
a persistent session kernel and launches host Python from `tools.code_kernel._spawn`.
Redirection, `tee`, Python `open`, child subprocesses, and other writes therefore bypass
a file-tool-only guard on all four local execution shapes.

## Rejected shortcuts

- Do not parse shell command strings for `>`, `tee`, `rm`, or known write verbs. Shell
  grammar, expansion, interpreters and subprocesses make a denylist bypassable.
- Do not rename an approval prompt “sandboxing.” Consent and confinement are different.
- Do not wrap only the terminal plugin path; that leaves `execute_code` outside the
  boundary and changes approval ordering through a brittle internal hook.
- Do not wrap the whole Hermes daemon. It legitimately writes sessions, config, caches
  and state; granting those roots would also let model-controlled shell commands write
  them, while denying them would break Hermes.
- Do not treat Docker as transparent parity. It changes terminal semantics and a Docker
  socket, privileged option, host namespace or broad volume invalidates containment.

## Required upstream seam

Hermes needs one supported execution-confinement provider invoked on the exact argv
immediately before every local child spawn:

1. `LocalEnvironment._run_bash`;
2. `ProcessRegistry.spawn_local`'s background pipe child;
3. `ProcessRegistry._spawn_local_pty`'s PTY child; and
4. the persistent local child in `tools.code_kernel._spawn`.

The provider must receive canonical working/writable roots, close inherited writable
file descriptors, return the final argv/environment, fail closed when unavailable, and
expose active enforcement in the tool result/audit. It may not fall back to an
unconfined spawn after a setup failure.

On this Mac, a narrowly scoped Seatbelt profile is a viable first provider:
deny `file-write*` by default, allow only canonical project workspaces plus required
canonical temporary roots, and functionally probe the policy before use. Apple's
`sandbox-exec` CLI is deprecated, so the provider must be isolated behind this seam and
have an explicit replacement path. The optional DeepSeek package is not a security
dependency.

User-typed TUI shell commands are host subprocesses today and are outside the current
model-controlled-agent claim. If they are later included, that must be a visible
operator-selected sandbox mode, not a silent behavior change.

## Hostile acceptance matrix

- shell redirection, append, `tee`, heredocs and command substitution;
- Python `open`, `os.open`, `pathlib`, rename/replace, and subprocess writers;
- symlinks, hard links, path traversal and `/tmp` versus `/private/tmp` aliases;
- background/daemonized children continuing after the parent exits;
- `execute_code` and terminal paths receive the same effective policy;
- allowed project/temp writes still work; existing file-tool path guard still works;
- missing/deprecated/failed policy runner refuses without an unconfined fallback;
- pre-open writable descriptors and inherited handles are closed or explicitly denied;
- full Hermes tool/approval/session smoke with the provider enabled.

## Current-main candidate

An isolated candidate against Hermes main `ee5b5ec21e…` now adds the missing provider
at all four spawn seams without editing M.O.T's pinned vendor. The first provider is
macOS Seatbelt. It canonicalizes existing writable roots, rejects `/`, denies filesystem
writes elsewhere, denies outbound Unix-domain sockets (so a Docker socket cannot become
an indirect filesystem escape), preserves ordinary IP networking and host reads, closes
inherited descriptors at the subprocess/PTY boundaries, and reports
`execution_confinement: macos-seatbelt` in foreground, background and kernel results.

Two real-host invariant tests cover direct shell/Python writes, symlink and hard-link
escapes, subprocesses, delayed background children, background pipe and PTY paths, the
persistent `execute_code` kernel, Unix-socket denial, allowed loopback TCP and allowed-root
writes. A broad 16-file footprint comparison also caught an unacceptable first draft:
checking the disabled default initialized `HERMES_HOME` and broke 16 existing environment
tests. The corrected lookup is side-effect-free when neither user nor managed config exists,
and the invariant test now writes a real temporary `config.yaml` instead of mocking the
configuration result. The final candidate footprint is 294 passes, ten failures and seven
platform skips; the same ten host-sensitive failures occur on the untouched upstream
baseline, while both new real-boundary invariants pass.

### Exact baseline and platform classification

The untouched baseline produced **292 passed, 10 failed, 7 skipped**; the candidate
produced **294 passed, 10 failed, 7 skipped**. The two additional passing tests are the
new U72 macOS boundary invariants. None of the ten failures or seven skips is a U72 test.

The ten failures remain unresolved upstream test/portability findings; “baseline-identical”
means only that this patch did not introduce them:

- `test_timeout_kill_reaps_setsid_grandchild`: the helper grandchild did not create its
  PID file before the cleanup assertion could run on this host.
- `test_parallel_cells_share_one_kernel_process`: its `pgrep -fc` process-count check
  yielded no BSD/macOS output.
- eight `TestSystemdCgroupIsolation` cases exercise Linux systemd behavior on macOS:
  `test_wraps_in_systemd_scope_when_supervisor_and_available`,
  `test_systemd_post_spawn_failure_never_kills_gateway_process_group`,
  `test_pty_spawn_is_wrapped_in_systemd_scope`,
  `test_pty_spawn_failure_reaps_scope_before_distinct_pipe_fallback`,
  `test_pty_spawn_failure_does_not_fallback_when_scope_reap_fails`,
  `test_systemd_run_user_scope_available_caches_after_probe`,
  `test_systemd_scope_first_probe_is_serialized`, and
  `test_failed_systemd_probe_retries_after_cache_ttl`. The class excludes Windows but
  does not exclude non-systemd macOS.

The seven skips are deliberate opposite-platform branches on this Mac: six Windows-only
cases (`test_windows_hermes_owned_paths_stripped`,
`test_make_run_env_preserves_windows_mixed_case_path_key`,
`test_write_stdin_uses_str_for_windows_pty`,
`test_submit_stdin_uses_crlf_for_windows_pty`,
`test_submit_stdin_keeps_lf_for_windows_pipe`, and
`test_windows_invokes_taskkill_with_tree_and_force_flags`) plus the Linux/POSIX PTY-byte
case `test_write_stdin_uses_bytes_for_posix_pty`. Those branches still require their
native CI platforms; they are not evidence from this Mac run.

The supported `scripts/run_tests.sh` invocation completed with the totals above. A second
direct sequential pytest diagnostic reached 100% but did not complete teardown after
roughly eight minutes and was terminated by exact PID. That teardown behavior is also
unresolved upstream harness evidence; it is not hidden as a successful run.

This is a direct-filesystem-write boundary, not a claim of full host isolation. It still
allows host reads, ordinary IP networking, process creation and required IPC; a reachable
HTTP service with mutation authority remains outside the filesystem predicate. The upstream
documentation in the candidate states those limits explicitly. `sandbox-exec` is deprecated,
so the provider seam—not Seatbelt itself—is the durable design.

## Current honest boundary

U72 remains open in M.O.T. The current shipped file-tool guard is valuable but is not a
shell execution boundary. A local patch to vendored Hermes would violate the zero-fork
doctrine; the candidate must be accepted upstream, released, pin-bumped and re-walked on
the real M.O.T Hermes lane before the app may enable or claim it.

The upstream recheck did not change that result. M.O.T's pinned Hermes tag resolves to
`bbc20510676c…`; upstream main resolved to `ee5b5ec21e…` on 2026-09-06. Both expose
`pre_tool_call` policy hooks and `check_execute_code_guard`, but those are approval and
policy decisions—not an OS boundary. Foreground, background-pipe, PTY and session-kernel
children still spawn with the Hermes process's host authority. The terminal environment
registry still offers only local, Docker, Singularity, Modal, Daytona,
Vercel Sandbox and SSH; it has no supported macOS local-confinement provider seam.

Therefore there is still no code-only M.O.T release fix without either forking Hermes or
pretending command filtering is confinement. The direct-write portion has been advanced
to a reviewable upstream candidate in
`docs/upstream-candidates/U72-hermes-local-confinement.patch`; it is not called complete
confinement because host reads, IP-reachable mutation services and broader process
authority remain outside its predicate. The shipped row remains blocked on upstream
acceptance, a release, and a real M.O.T lane walk.

## Upstream submission route

The required duplicate search found Hermes issue
[#36645](https://github.com/NousResearch/hermes-agent/issues/36645) and open PR
[#39004](https://github.com/NousResearch/hermes-agent/pull/39004). That PR is the best
existing general direction: it replaces command parsing with an explicit
`terminal.execution_write_scope` and a Docker-backed boundary, and it fails closed on
unsupported environments. Its own scope explicitly excludes native local execution,
however, so it does not provide the macOS boundary M.O.T needs.

Opening the Seatbelt candidate as a competing PR would violate Hermes's search-first
rule and risk creating two generic policy seams. A focused coordination comment was
therefore posted on #39004 asking whether maintainers want the macOS provider rebased as
a supplement or as a follow-up after its policy seam settles. The submitted text and
link are preserved at `docs/upstream-candidates/U72-HERMES-PR-COMMENT.md`.
