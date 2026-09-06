# U72 — an OS execution boundary, not command-string theatre

**Date:** 2026-09-05; upstream rechecked 2026-09-06
**Status:** current-main Seatbelt candidate rejected after adversarial hard-link testing;
not released, pinned or shipped.

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

The rejected Seatbelt experiment proves that a path allow-list over an ordinary host
workspace is not a viable provider: pre-existing hard-link aliases defeat the write
claim. A replacement must first provide an ownership boundary that removes that alias
class—for example, a genuinely distinct writable filesystem with an explicit publication
broker—or enforce and name a materially narrower contract. That is an architectural
requirement, not permission to introduce Docker: M.O.T's Docker-free decision remains
binding. Apple's `sandbox-exec` CLI is also deprecated, so a future provider must be
replaceable behind the common spawn seam. The optional DeepSeek package is not a
security dependency.

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

## Rejected current-main candidate

An isolated candidate against Hermes main `ee5b5ec21e…` added the missing provider at all
four spawn seams without editing M.O.T's pinned vendor. Its first provider was macOS
Seatbelt. It canonicalized existing writable roots, rejected `/`, denied path-addressed
filesystem writes elsewhere, denied outbound Unix-domain sockets, preserved ordinary IP
networking and host reads, closed inherited descriptors at the subprocess/PTY boundaries,
and reported `execution_confinement: macos-seatbelt` in foreground, background and kernel
results.

That predicate is **rejected**. A hard link created *before* the child starts gives one
inode two names. If one name is under an allowed root and the other is outside it,
Seatbelt authorizes a write through the allowed name and the protected name changes too.
The original invariant only tried to create the hard link from inside the sandbox; it
proved that post-start link creation was blocked but did not test a pre-existing alias.
The counterexample was reproduced on the real Mac: both paths had the same inode and a
write through the allowed path changed the protected file from `original` to `mutated`.
Therefore this path-filtering Seatbelt profile cannot honestly be called a complete
direct-filesystem-write boundary for arbitrary existing writable roots.

Two real-host invariant tests covered direct shell/Python writes, symlink and new hard-link
escapes, subprocesses, delayed background children, background pipe and PTY paths, the
persistent `execute_code` kernel, Unix-socket denial, allowed loopback TCP and allowed-root
writes. A broad 16-file footprint comparison also caught an unacceptable first draft:
checking the disabled default initialized `HERMES_HOME` and broke 16 existing environment
tests. The corrected lookup is side-effect-free when neither user nor managed config exists,
and the invariant test now writes a real temporary `config.yaml` instead of mocking the
configuration result. The candidate footprint was 294 passes, ten failures and seven
platform skips; the same ten host-sensitive failures occur on the untouched upstream
baseline, while both new real-boundary invariants pass.

Those passes no longer establish the claimed boundary because the test oracle omitted
the stronger pre-existing-hard-link case. A later rerun also produced nine rather than
ten baseline failures because `test_timeout_kill_reaps_setsid_grandchild` passed on that
run, confirming it is timing-sensitive. The other nine signatures remained identical.

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

This was intended as a direct-filesystem-write boundary rather than full host isolation.
Host reads, ordinary IP networking, process creation, required IPC and reachable mutation
services were already explicit non-claims. The pre-existing-hard-link result defeats even
that narrower write claim. `sandbox-exec` is also deprecated; neither the provider seam nor
its label makes the rejected Seatbelt predicate sufficient.

## Current honest boundary

U72 remains open in M.O.T. The current shipped file-tool guard is valuable but is not a
shell execution boundary. The Seatbelt candidate is rejected, not merely waiting for an
upstream release. A replacement must eliminate the hard-link alias class or state and
enforce a materially narrower contract; renaming the same path predicate is not a fix. A
local patch to vendored Hermes would also violate the zero-fork doctrine. Any replacement
still needs upstream acceptance, release, a pin bump and a real M.O.T Hermes lane walk
before the app may enable or claim it.

The upstream recheck did not change that result. M.O.T's pinned Hermes tag resolves to
`bbc20510676c…`; upstream main resolved to `ee5b5ec21e…` on 2026-09-06. Both expose
`pre_tool_call` policy hooks and `check_execute_code_guard`, but those are approval and
policy decisions—not an OS boundary. Foreground, background-pipe, PTY and session-kernel
children still spawn with the Hermes process's host authority. The terminal environment
registry still offers only local, Docker, Singularity, Modal, Daytona,
Vercel Sandbox and SSH; it has no supported macOS local-confinement provider seam.

Therefore there is still no code-only M.O.T release fix without either forking Hermes or
pretending command filtering is confinement. The rejected implementation remains in
`docs/upstream-candidates/U72-hermes-local-confinement.patch` as forensic evidence only;
it is not a candidate to apply. The shipped row is blocked on a replacement architecture,
then upstream acceptance, a release and a real M.O.T lane walk.

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
link are preserved at `docs/upstream-candidates/U72-HERMES-PR-COMMENT.md`. That comment
predates the hard-link counterexample and must be corrected upstream before any further
candidate is offered.
