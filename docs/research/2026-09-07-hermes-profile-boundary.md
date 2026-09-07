# U2 — Hermes shared-home versus isolated-profile decision

Status: product decision recorded; no runtime behavior changes in this wave.

## What is intentionally true today

MOT Deck and standalone Hermes share `~/.hermes`. That preserves the user's existing
sessions, memory, skills, configuration, channel state and WhatsApp connection. The
continuity is deliberate, not an accidental missing sandbox.

The cost is also real: MOT Deck's managed provider/MCP/channel reconciliation and a
standalone Hermes process can observe or update the same state. Backup, upgrade and
ownership boundaries are therefore less deterministic than an isolated product home.

## Upstream-supported isolation seam

Hermes already supports named profiles and `HERMES_HOME`; `hermes profile create`
supports cloning a selected set or all profile state, and `hermes -p <profile>` selects
the profile. A profile separates configuration, API keys, SOUL, memory, sessions,
skills and gateway/channel state without forking Hermes.

Hermes separately controls tool-process homes. Its automatic terminal mode uses the
real OS home for host CLIs and the profile home for containers; strict profile mode can
hide SSH, Git/GitHub, npm and Codex state until explicitly initialized. Product profile
isolation and tool-home isolation are therefore separate choices and must not be
collapsed into one switch.

Primary upstream references:

- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/profiles.md>
- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md>

## Decision

Keep **Shared** as the default for this existing installation. Do not silently split the
real WhatsApp/session history the user already relies on.

A future opt-in mode may offer **MOT Deck isolated** by using Hermes's own profile
contract. It must include:

1. A preview naming exactly which configuration, sessions, memory, skills and channel
   state would be copied.
2. Copy/import only—never a destructive move or merge into the shared home.
3. Explicit conflict and credential handling; no silent channel reconnection.
4. A rollback switch to the unchanged Shared profile.
5. A separate tool-home choice: **Compatible** keeps normal host CLI homes, while
   **Strict** uses the isolated profile home and clearly names which host credentials and
   tools become unavailable.
6. Proven single-owner launch/reconciliation behavior for both modes before shipping.

This closes the undecided product ruling, not the future implementation. The feature
remains later work and requires its own specification and real shared→isolated→shared
journey.
