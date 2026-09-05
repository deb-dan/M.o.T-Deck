# U72 — an OS execution boundary, not command-string theatre

**Date:** 2026-09-05; upstream rechecked 2026-09-06
**Status:** upstream execution seam required; no local implementation is permitted yet.

## Proven premise

`guards/harness-path-guard` controls declared file-tool operations. Hermes's local
terminal calls host Bash from `LocalEnvironment._run_bash`, and `execute_code` launches
host Python from its own `Popen` path. Redirection, `tee`, Python `open`, child
subprocesses, and other writes therefore bypass a file-tool-only guard.

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
immediately before both local child spawns:

1. `LocalEnvironment._run_bash`;
2. the local child in `code_execution_tool.py`.

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

## Current honest boundary

U72 remains open. The current file-tool guard is valuable but is not a shell execution
boundary. A local patch to vendored Hermes would violate the zero-fork doctrine; the
correct next action is an upstream confinement-provider contribution, followed by a
pinned update and the matrix above.

The upstream recheck did not change that result. M.O.T's pinned Hermes tag resolves to
`bbc20510676c…`; upstream main resolved to `ee5b5ec21e…` on 2026-09-06. Both expose
`pre_tool_call` policy hooks and `check_execute_code_guard`, but those are approval and
policy decisions—not an OS boundary. `LocalEnvironment._run_bash` and the local
`execute_code` child still spawn with the Hermes process's host authority. The terminal
environment registry still offers only local, Docker, Singularity, Modal, Daytona,
Vercel Sandbox and SSH; it has no supported macOS local-confinement provider seam.

Therefore there is no code-only M.O.T fix to ship without either forking Hermes or
pretending command filtering is confinement. This row is blocked on that exact upstream
seam, not on missing implementation effort.
