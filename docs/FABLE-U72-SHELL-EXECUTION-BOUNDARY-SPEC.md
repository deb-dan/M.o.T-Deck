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
