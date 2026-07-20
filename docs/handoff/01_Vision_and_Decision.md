# 01 — Vision and Decision

*Part of the Harness handoff set. Index: [00_START_HERE.md](00_START_HERE.md). Architecture: [02_Architecture.md](02_Architecture.md). Licensing: [03_Licensing.md](03_Licensing.md).*

---

## How the pieces fit (plain-language basics — read this first)

If the component names ever blur together, start here. There are six pieces. Two are yours; four are other people's projects that you install and use. Think of the whole thing as a restaurant:

- **Jan is the kitchen — the engine.** It is the *only* piece that actually loads an AI model into memory and generates text. Nothing else in the harness can "think." Every other component, when it needs intelligence, sends its question to Jan over a local connection and gets the model's answer back.
- **Odysseus and Hermes are specialist staff who order from that kitchen.** Odysseus is your research workspace (chat + DeepResearch); Hermes is your background coding agent. Neither runs a model itself — they are *apps that use the engine*. Two appliances plugged into one generator.
- **SearXNG is your private librarian.** It's a small search engine running on your own machine: when DeepResearch (or an MCP web-search tool) needs web results, it asks SearXNG, which queries the public search engines and hands back combined results. No accounts, no API keys, and only one copy of it needs to exist.
- **The Bridge (yours) is the manager.** It doesn't chat and doesn't run models. It installs the four components (git clone + Python venv), starts and stops them as background processes, checks their health, and writes their config files so every piece knows every other piece's address.
- **Mission Control (yours) is the dining room — the one window you actually look at.** It talks only to the Bridge, and shows you status cards, the activity feed, the ⌘K palette, and Odysseus's UI in a tab.

**What "the harness houses them" actually means.** The Bridge does not contain Jan, Odysseus, or Hermes inside itself — they are not compiled into one program. Each is a separate, ordinary program installed side by side in its own folder. "Houses" means the Bridge *supervises* them the way a manager supervises staff: it hires them (installs), schedules them (starts/stops), takes their pulse (health checks) — but never does their jobs and never absorbs them. That is the whole "compose, don't merge" idea in one sentence: several small programs cooperating over local connections, instead of one giant merged codebase. (It's also exactly why the licensing stays clean — see [03_Licensing.md](03_Licensing.md).)

**Ports and endpoints, demystified.** Your machine has an internal address, `127.0.0.1` (also called "localhost" — literally "this computer"). A **port** is like an apartment number at that address: Jan answers the door at 6767, Odysseus at 7860, SearXNG at 8080. An **endpoint** is just the full written-out address another program calls — e.g. `http://127.0.0.1:6767/v1`. So "point Hermes at the runner endpoint" means: put that one URL in Hermes's config file. All of this traffic stays inside your Mac; nothing touches the network.

**Who calls who — the whole graph in four lines:**
1. You → **Mission Control** (the only UI you ever open).
2. Mission Control → **Bridge** (install / start / stop / status).
3. Odysseus and Hermes → **the runner endpoint** (Jan, `:6767`) for every model answer.
4. Odysseus's DeepResearch and MCP search → **SearXNG** (`:8080`) for web results.

**What you see vs. what's hidden.** Only Mission Control has a window. Jan runs *headless* — meaning "no head," i.e. no window, just a background server (`jan serve --detach`). Odysseus is a local web page that appears *inside* a Mission Control tab. Hermes and SearXNG are invisible background processes. One window, five quiet workers. (Jan's desktop app stays installed as an occasional convenience — when you open it, its own API happens to live on `:1337` — but the harness's engine is the headless one on `:6767`.)

**No Docker — decided.** Every component installs the same way: git clone plus a Python venv, all handled by the Bridge. Docker (a tool that runs software inside pre-packaged mini-Linux boxes) is popular for servers, but it's a heavy extra layer you don't want on a personal Mac, and you've ruled it out. Native installs cover every component, including SearXNG — details in [02_Architecture.md](02_Architecture.md).

## The itch you're scratching

You want **one tool**: a single window, a single command surface (⌘K), a single model catalog, a single status view — for everything local-AI on your Mac. Today that capability is scattered across four excellent-but-separate projects:

- **LM Studio / Jan** — model runners (download, load, serve models).
- **Odysseus** — a synchronous workspace with local DeepResearch.
- **Hermes** — an asynchronous, self-directed coding-agent daemon.

Each has its own install, window, config, and vocabulary. The seams are the product problem. The instinct to unify is right.

## The core decision (settled, both of us agree)

**Unified PRODUCT, composed ARCHITECTURE.**

The unification you want lives in the **experience layer**, not the repo layer. You do not fork or merge any of these projects. You orchestrate them — over their standard APIs — from the thing you already built: the **Harness** (Bridge + Swift Mission Control). The Harness IS the product. Everything else is a managed component behind it.

The precedents are strong: VS Code doesn't fork compilers, it orchestrates language servers. Docker Desktop is a shell over an engine. Claude Desktop is a shell over MCP servers. In every case the orchestrating shell — not the engine — is where the product identity lives. Your editorial dark UI, your ⌘K verbs, your status cards: that's the product. Jan is a component.

## Why NOT fork Jan (the argument, preserved)

You originally considered forking Jan to close its gaps. The research showed the picture had changed, and you've since agreed:

1. **The gaps already closed upstream.** Everything you wanted to add to Jan already exists in Jan: built-in HF Hub model browser with hardware-fit pills and one-click GGUF download; native MLX backend since v0.7.7 (Feb 2026); MCP support since v0.7.3 with per-tool permission gating since v0.7.9; and it's Tauri/Rust, not Electron. A fork would buy you nothing you need and cost you everything below.
2. **Forks inherit merge debt forever.** You'd be rebasing against a fast-moving upstream to keep features you didn't even need to write. That's negative leverage.
3. **License trap — RETIRED (correction 2026-07-20).** This argument originally cited Jan's app as AGPLv3. Verified against the repo's root LICENSE and README: **Jan is Apache-2.0** (relicensed; the old AGPL-app/MIT-SDK split no longer exists). A fork would therefore NOT contaminate your licensing. The no-fork decision stands anyway — reasons 1, 2, and 4 carry it on their own. Kept here so the record shows which argument died and which survived. Full analysis in [03_Licensing.md](03_Licensing.md).
4. **The runner-slot abstraction dissolves the decision permanently.** Once the Bridge talks to "a runner" through one small interface (OpenAI-compatible endpoint + model-list + download mechanism), Jan vs. LM Studio vs. bare llama.cpp stops being an identity decision and becomes a quarterly consumption choice. See [02_Architecture.md](02_Architecture.md) §Runner slot.

**Fork tripwire (the only reversal condition):** fork Jan only if a concrete, named need is blocked upstream — a required PR rejected, hostile governance, or dead velocity. Until then, polish gaps get upstream PRs: influence without maintenance debt.

## The NEW decision: personal-first

You've now decided this is a **personal tool**. Possibly shipped to others someday — but not today, and today's work should not pay tomorrow's shipping costs. This changes the strategy in specific, liberating ways.

### What to do differently because it's personal-first

**Stop paying for (skip entirely, guilt-free):**
- **Distribution machinery.** No .dmg, no Apple code signing or notarization, no installers, no auto-update channel for *your* app. You build Mission Control locally; that was already the plan (thin launcher, not a frozen .dmg, because live git pin/rollback of upstreams is a core feature).
- **License compliance work.** AGPL imposes **zero obligations** while the software never leaves your machines and isn't served to others over a network. The only AGPL component is SearXNG (Odysseus is MIT, Jan is Apache-2.0 — corrections 2026-07-19/20); you can run, modify, and privately patch any of them with no source-publication duty. See [03_Licensing.md](03_Licensing.md).
- **Generality.** Hardcode your paths, your ports, your machine's RAM assumptions, your one-user config. No settings UI for preferences only you will ever set once. No cross-platform thought. No telemetry/privacy-policy questions.
- **Polish for strangers.** Error messages can be developer-grade. Onboarding flows can be a README. Empty states can be blunt.

**Start optimizing for (this is where the hours go instead):**
- **Your own capability per week.** The metric is "what can Debi do this week that he couldn't last week" — deep research on tap, an async agent working while you sleep, one ⌘K away from any model.
- **Iteration speed.** Prefer the crude thing that runs today over the elegant thing that runs next month. Webview-embed Odysseus rather than rebuilding its UI. Shell out to `jan` CLI rather than writing a download client.
- **Aesthetic joy.** The editorial UI is *for you* — it's a legitimate feature of a personal tool. Keep investing in it where it makes you want to open the app.
- **Embracing every component freely.** Licensing costs you nothing today: SearXNG (the one AGPL piece) has zero personal-use obligations, and Odysseus/Jan/Hermes are MIT/Apache anyway. Embed, configure, even patch locally if a bug blocks you (keep patches as git-managed diffs via your pin/rollback system so upstream updates stay clean).

**Cheap hygiene to keep future-ship optionality (do pay these — they're nearly free):**
1. **Repo separation.** Your Bridge and Mission Control stay in their own repos (or clearly separated modules), containing only code you wrote. AGPL components live in their own cloned repos, managed by the Bridge. Never copy AGPL source into your repos.
2. **Arm's-length boundaries.** All interaction with Jan/Odysseus/SearXNG happens over HTTP APIs, CLI invocation, or process spawning — never linking, importing, or vendoring their code. This is already your architecture; just don't erode it in a lazy moment.
3. **Lift patterns only from permissive code.** Hermes and Odysseus are MIT, Jan is Apache-2.0 — you may adopt conventions and copy code from any of them with attribution. SearXNG is AGPL — take *ideas*, not code. (Corrected 2026-07-20; the old "Odysseus = ideas only" restriction is lifted.)
4. **Write the interface down.** The runner-slot contract in [02_Architecture.md](02_Architecture.md) is the seam that makes a future productization a packaging exercise instead of a rewrite.

That's the whole tax. Four habits. Everything else about shipping can be deferred indefinitely.

## What success looks like

**Near-term (M0–M1 done):** One window shows Bridge, runner, Hermes, Odysseus, SearXNG — all green. Hermes is chatting with a local model through the runner endpoint. Odysseus answers a DeepResearch query using the shared SearXNG. You didn't open a terminal to get there.

**Mid-term (M2–M3 done):** You browse and download models in a native, editorial-styled browser that's *better than LM Studio's* because it's runner-agnostic and yours. ⌘K verbs span components: "download model…", "deep research…", "assign to Hermes…". Hermes tasks show in the activity feed; Hermes uses DeepResearch and the runner as tools; one SKILL.md corpus serves everything.

**Long-term (open option, not a commitment):** If the harness becomes something others want, the composed architecture means shipping is a packaging-and-licensing exercise on code you fully own — not an untangling.

## What this project is NOT

- Not a Jan fork or a Jan competitor. Jan is a supplier.
- Not a startup (today). No users, no roadmap pressure, no compliance work.
- Not a research project. Every milestone ends with something you personally use that week.

---

*Next: [02_Architecture.md](02_Architecture.md) for how the pieces fit; [04_Roadmap.md](04_Roadmap.md) for the order of work.*
