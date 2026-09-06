**Submitted:** 2026-09-06 at
https://github.com/NousResearch/hermes-agent/pull/39004#issuecomment-5555854326

**Correction required:** the candidate described below was subsequently rejected. A
pre-existing hard link under an allowed root can mutate the same inode through its name
outside that root. The authored test covered creating a hard link after confinement, not
this pre-existing alias. Do not offer or submit the patch; post this correction to the
upstream thread before proposing any replacement.

## Correction comment prepared for the upstream thread

Correction to my earlier macOS candidate note: adversarial testing found that the
Seatbelt predicate I described is not a sufficient direct-write boundary. If a hard link
already exists under an allowed root and points to the same inode as a path outside that
root, writing through the allowed name changes the protected path too. My original test
only proved that a confined child could not create a new hard link; it missed this
pre-existing alias. I reproduced the failure on macOS and have rejected the candidate.
Please do not treat my earlier test summary as evidence for a native-local adapter. The
four-spawn-seam requirement still stands, but a replacement must eliminate this inode
alias class or claim and enforce a materially narrower boundary.

I reproduced #36645 on macOS across four distinct local child-spawn shapes:
foreground shell, background pipe, background PTY, and the persistent
`execute_code` kernel.

#39004 is the best existing direction I found: it establishes an explicit
execution-write policy and correctly refuses unsupported environments instead of
falling back. Its current scope is Docker, however, and its PR description explicitly
leaves native local execution unsupported.

I have a tested macOS Seatbelt provider candidate against current main that wraps the
exact argv immediately before all four local spawn shapes. It denies `file-write*`
outside canonical writable roots, closes inherited descriptors at the subprocess/PTY
boundaries, denies outbound Unix sockets, and fails closed if the policy cannot be
activated. Real-host tests cover shell/Python/subprocess/background/symlink/hard-link
escapes, pipe and PTY children, the persistent kernel, allowed-root writes, and loopback
TCP. It deliberately does not claim read isolation, process isolation, or protection
against mutation through reachable IP services. `sandbox-exec` is deprecated, so the
provider seam—not Seatbelt—is the durable part of the design.

Because #39004 already owns the issue and touches the generic policy shape, I do not
want to open a competing PR. Would maintainers prefer the macOS adapter as a focused
follow-up after #39004, or a supplement rebased onto that PR once its generic seam is
settled? I can provide the current patch and exact test matrix in whichever form is
easier to review.
