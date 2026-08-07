# 03 — Licensing

## ⟳ STATE UPDATE — 2026-08-07 (supersedes sections below where they conflict)

Licensing posture is unchanged and still correct; only the component list moved. Living
references: `CLAUDE.md`, `docs/HARNESS-INTERNALS.md`.

- **Jan (Apache-2.0) is no longer part of the harness at all** — removed July 2026. Its licensing
  analysis below is now moot. In its place we run **llama.cpp** (MIT, pinned binary release) and
  **Apple MLX / mlx-lm / mlx-vlm** (MIT, pip-pinned in our own venv) — both permissive, both used
  as separate processes, neither forked.
- **Still AGPL: SearXNG only**, still run as an unmodified separate process, still zero obligation
  for personal use.
- Hermes (MIT) and Odysseus (MIT) remain pinned submodules; the never-edit-`vendor/` rule is
  enforced in practice — our Hermes path-guard ships as an **external plugin** seeded into
  `~/.hermes/plugins/`, not as a vendor patch.
- Distribution note: a fat, offline `.dmg` installer now exists and bundles wheels plus the pinned
  `llama-server` binary. It is **ad-hoc codesigned, not notarized**, and is used personally. If
  distribution is ever contemplated, redo this analysis for the bundled binaries first.
---


*Part of the Harness handoff set. Index: [00_START_HERE.md](00_START_HERE.md). Architecture these rules protect: [02_Architecture.md](02_Architecture.md).*

**Framing note:** this is engineering-grade license reasoning, not legal advice. For personal use it's more than sufficient; if you ever actually ship commercially, spend an hour with a lawyer then.

**CORRECTION (2026-07-19, second research pass):** Odysseus is **MIT, not AGPL** — verified against its LICENSE file on `main` ([raw](https://raw.githubusercontent.com/pewdiepie-archdaemon/odysseus/main/LICENSE); repo now `odysseus-dev/odysseus`). The table and reasoning below still list it as AGPL in places — read those as superseded. Practical upshot: Odysseus joins Hermes as a component whose **patterns AND code you may lift with attribution**; the "ideas not code" restriction applied to it earlier is lifted. The only AGPL components left in the harness are ~~Jan's app and~~ **SearXNG** only (Jan turned out to be Apache-2.0 — see the 2026-07-20 correction below), touched only over APIs. Details in [06_Landscape_and_PriorArt.md](06_Landscape_and_PriorArt.md). (One new AGPL cousin appears in that doc — **Cherry Studio** — but only as an optional *user-facing* chat client you'd talk to over its endpoint, never link; same posture as Jan.)

**CORRECTION (2026-07-20, fourth pass):** **Jan is Apache-2.0, not AGPLv3** — verified against the root LICENSE ("Copyright 2025 Menlo Research … Licensed under the Apache License, Version 2.0") and README ("Apache 2.0 — Because sharing is caring") in a fresh clone of `janhq/jan`. The earlier "AGPL app / MIT SDK" split is retired. Consequences: (a) the "license trap" argument against forking Jan is void — the no-fork decision rests entirely on merge debt and gaps-closed-upstream, which are sufficient; (b) the only AGPL component in the harness is now **SearXNG**; (c) Jan joins Hermes/Odysseus as pattern-AND-code donors (Apache-2.0 requires attribution + NOTICE preservation). Table and reasoning below updated in place.

---

## Per-component license table

| Component | License | What that means for you |
|---|---|---|
| **Bridge** (yours) | Yours to choose | Keep private for now; MIT/commercial/anything later. |
| **Mission Control** (yours) | Yours to choose | Same. |
| **Jan** (whole repo) | Apache-2.0 (corrected 2026-07-20; formerly AGPL app / MIT SDK) | Permissive. You interact over its API/CLI anyway; code-lifting with attribution now also allowed. |
| **LM Studio** | Proprietary (closed) | Free for personal use; fine as a fallback runner you merely talk to. |
| **Hermes** (NousResearch hermes-agent) | MIT | Permissive. You may lift patterns AND code (with attribution) into your own layers — e.g., SKILL.md conventions. |
| **Odysseus** | MIT (corrected 2026-07-19) | Permissive: use fully, lift patterns AND code with attribution. |
| **SearXNG** | AGPLv3 — **the only AGPL component left** | Infrastructure you run; you're a user, not a deriver. Ideas only, never code. |
| **Tongyi DeepResearch pipeline** (inside Odysseus) | Apache-2.0 (origin) | Odysseus's adaptation lives under Odysseus's MIT; the upstream Apache code is also separately available. |

## The core AGPL reasoning (why compose, not merge)

- **Fork-and-merge = one-way door — argument RETIRED for Jan (2026-07-20).** This bullet originally argued a Jan fork would AGPL your combined work forever. With Jan verified Apache-2.0, that's no longer true: an Apache fork keeps your code under your own terms. The principle stays valid for any *AGPL* component (currently only SearXNG, which nobody proposes forking). The compose-not-merge decision now rests on engineering grounds alone — merge debt and gaps-closed-upstream — which were always the stronger half of the argument.
- **Arm's-length interaction ≠ derivative work.** Talking to a program over standard interfaces — HTTP, the OpenAI wire protocol, CLI invocation, process spawning — does not make your program a derivative of it. This is the settled mainstream reading (it's how every proprietary app that talks to a GPL database or spawns GPL tools operates). So the Bridge and Mission Control, which only ever talk to Jan/Odysseus/SearXNG over APIs and CLIs, remain 100% yours: private, MIT-able, or commercializable later.
- **This is the license reason to compose.** It happens to coincide exactly with the engineering reason ([01_Vision_and_Decision.md](01_Vision_and_Decision.md)) — that's why the decision was easy once the picture was complete.

## Personal-use-now: you have ZERO obligations today

AGPL's obligations trigger on **distribution** (giving the software to others) or **network interaction** (letting others use it over a network — the clause that distinguishes AGPL from GPL). While the harness:
- runs only on your machines,
- binds only to 127.0.0.1,
- and is used only by you,

**no AGPL obligation exists at all.** You may run, modify, privately patch, and combine anything however you like. (Since the 2026-07-20 correction this paragraph only governs SearXNG — Jan and Odysseus are permissive, so for them even distribution carries only attribution duties.) Obligations appear only IF you later distribute AGPL software or host it for others over a network.

Practical corollary: **embrace the AGPL components fully.** Embed Odysseus's UI in a webview, run SearXNG as shared infrastructure, patch Odysseus locally if a bug blocks you. None of it creates duties while it stays personal.

## The cheap hygiene rules (preserve future-ship optionality)

These four habits cost minutes and keep a future ship from being a rewrite or a license audit:

1. **Repo separation.** Bridge and Mission Control live in their own repos containing only code you wrote (or permissively-licensed code with attribution). AGPL components are separate clones managed by the Bridge's pin/rollback machinery.
2. **Never copy AGPL code into your repos.** Not a function, not a file. Ideas, pipeline shapes, and UX patterns are free; source is not. (MIT sources like Hermes: copying is fine with attribution.)
3. **Interact only over APIs/CLIs/process boundaries.** Already the architecture ([02_Architecture.md](02_Architecture.md) §Data & API boundaries). The risk is erosion in a lazy moment — e.g., importing an Odysseus Python module into a Bridge helper because it's *right there*. Don't.
4. **Keep local patches to upstreams as separate git-managed diffs**, applied by the Bridge after updates — never mingled with your own code, and trivially publishable if a future ship requires releasing modifications to AGPL components you distribute.

If you one day ship: your code ships under your terms; unmodified AGPL components can be depended-on/downloaded rather than redistributed (or redistributed with source offers); any patches to them get published. All of that is a packaging exercise **because** of these four habits.

## The fork tripwire (unchanged, restated)

Fork Jan **only if** a concrete, named need is blocked upstream:
- a PR you require is rejected,
- governance turns hostile to your use case,
- or upstream velocity dies.

Otherwise: contribute upstream PRs for polish gaps — influence without maintenance debt. Log candidate PRs as you hit annoyances (M4 in [04_Roadmap.md](04_Roadmap.md)).

## Quick answers to questions future-you will ask

- **"Can I lift Hermes's SKILL.md loader code into the Bridge?"** Yes — MIT, keep the copyright notice.
- **"Can I screenshot/embed Odysseus's UI in my app window?"** Yes — embedding a locally-served web UI in a webview is use, not derivation.
- **"Can I ship Mission Control to a friend?"** Your code, yes, any terms. Bundling Jan (Apache-2.0) or Odysseus (MIT) needs only license/notice preservation. Bundling SearXNG (AGPL) triggers its source-availability terms *for it*, not for your code. Simplest either way: your installer downloads upstreams at install time, like today's Bridge behavior.
- **"Does pointing Hermes (MIT) at Jan (Apache-2.0) or SearXNG (AGPL) contaminate anything?"** No. Wire-protocol use, both directions, always fine.
- **"What about model weights?"** Separate regime entirely (each model's own license — Apache/MIT/Llama-community/etc.). Irrelevant for personal use; check per-model only if you ever ship outputs-at-scale or redistribute weights.

---

*Next: [04_Roadmap.md](04_Roadmap.md).*
