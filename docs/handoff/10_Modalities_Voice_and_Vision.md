# 10 — Modalities: Voice (Voicebox) and Vision/Image-Video (ComfyUI)

**Written:** 2026-07-21 (Claude Opus 4.8, from Debi's direction). **Status:** decision + direction, captured from discussion. **Not on any milestone yet** — these are future optional components, sequenced *after* the core handshake is green. No code changed. Personal-first framing applies (00/01).

**One-line summary:** **Voicebox → adopt** (light, near-perfect fit, completes the voice loop). **ComfyUI → much later / maybe** (right engine for image+video, but heaviest component in the plan; run it **headless under the hood behind a new UI**; gated on model-memory scheduling). Both are **optional, off-by-default managed components** in the compose model — adding them costs the core nothing.

> **Design governance reminder (doc 08):** any *new UI* built over headless ComfyUI (or a voice surface) is design work owned by the orchestrator (Fable 5). This doc records the decision and technical direction, not the visual design.

---

## Why these two (the thesis)

Voice + vision turn the harness from *a text tool* into *a full multimodal local assistant that hears, speaks, sees, and creates* — under one supervised shell, which almost nothing else in the local-AI space does. That's a genuinely differentiated **destination**. Guardrail: it's the destination, not the **door** — if this is ever shipped, lead with a sharp wedge (see `09` §demand), and let modalities be the depth users discover later. For a personal tool, "encompassing for me" is a legitimate goal on its own.

The compose architecture makes this cheap **as long as they stay optional**: each is one more one-switch component the Bridge supervises, off by default, flipped on when wanted. No impact on core identity or default provisioning weight.

---

## Voicebox — ADOPT ✅

**Repo:** https://github.com/jamiepine/voicebox (Jamie Pine, of Spacedrive). **Verified 2026-07-21.**

**What it is:** a local-first AI *voice studio* — STT + TTS in one app. Global-hotkey dictation, speech generation, voice cloning, and **agent voice output**. Bridges both halves of the voice loop.

**Why it gels almost perfectly (the reasons this is a near-ideal fit):**
- **License: MIT** — the cleanest in the whole stack (cleaner than Odysseus/Hermes MIT even in spirit; no AGPL/GPL concerns). Code may be lifted with attribution if ever useful.
- **Identical stack to the harness:** **FastAPI (Python) + Tauri (Rust) + MLX** for Apple-Silicon inference ("4-5x via Neural Engine"). Practically a sibling project; low integration risk.
- **Composability is a gift:** exposes a **REST API on `:17493`** *and* ships an **MCP server**. So it slots in two ways at once:
  1. As a **Bridge-managed component** (native Python venv, no Docker — fits the locked decision), with a status card + one-switch provisioning like the others.
  2. As **MCP tools consumed by Hermes/Odysseus** → agents gain **voice output** for free, and the harness gains **dictation input**.
- **Local + native:** runs entirely on-device; MLX/Metal on Apple Silicon.
- **Mature:** ~45k★, v0.5.0 (Apr 2026), active.
- **Models:** STT = Whisper (Base→Turbo); TTS = 7 engines (Qwen3-TTS, Kokoro, Chatterbox, etc.); a small Qwen3 (0.6–4B) for personality/refinement.

**What it completes:** the input/output loop — talk to the harness, it talks back, agents speak. A real UX leap for a personal cockpit, not a gimmick. It also *strengthens the core* (assistant feel), unlike ComfyUI which *expands capability*.

**Integration sketch (for whoever builds it):**
- Add a `voicebox` component manifest (repo pin, venv, `:17493` health = REST ping, `verify` = one STT or TTS round-trip).
- Register its MCP server in the shared MCP list fanned out to hosts (see `09` / `05` §2) so Hermes/Odysseus can call it.
- Dictation hotkey → text into the active chat surface; TTS toggle on assistant replies.
- **Model-memory note:** its Whisper + TTS + small-LLM models add to the memory pool — see "shared consequence" below, though individually it's light.

**Sequencing:** soon-ish — **after M0 is green.** It's light enough that it doesn't need the heavy scheduling ComfyUI forces. Reasonable as an early post-M2/M3 add, or even folded into the "unified surface" work if voice-first appeals.

**Verdict:** **Do it.** Lowest-risk, highest-fit addition on the table.

---

## ComfyUI — MUCH LATER / MAYBE ⏳ (headless engine + new UI)

**Repo:** https://github.com/comfy-org/comfyui. **Verified 2026-07-21.**

**What it is:** "the most powerful, modular AI engine for content creation" — a node-graph system generating **images (SDXL, Flux), video (Mochi, Hunyuan, LTX-Video), audio, and 3D.** The de-facto standard backend for open image/video generation.

**Debi's stance (2026-07-21):** for much later, or a *maybe even*. Its node-graph UI is "a mess" — would want to **redo it / run it under the hood and build a new UI over the API**. Wary of touching ComfyUI's internals (it's complex — don't risk breaking it; wrap it, don't fork it). But **"performance beats looks" for ComfyUI** — its value is the engine, not the graph — so *it all depends*.

**Why it's the right *choice* if/when added:** de-facto standard, API-first, massive model/node ecosystem, runs native Python (no Docker — fits), composable via **REST + WebSocket** (`/prompt`, `/history`, ws progress) → can be driven **fully headless** while you present your own surface. This directly matches Debi's "under the hood + new UI" instinct, and mirrors the Odysseus webview pattern but leaning *harder to headless* (drive the API, optionally expose the raw node graph as a "power tab").

**The three frictions, in descending importance:**
1. **Resource contention — the serious one (and the real gate).** On 64GB *unified* memory, a ~30B LLM and a Flux/video model draw from the **same pool**; video models are huge. You can't keep both hot. This forces **VRAM-aware model lifecycle** in the Bridge (load diffusion on demand, park the LLM, swap back) — logic the harness doesn't have (it treats components as independent). *This*, not licensing, is why ComfyUI waits.
2. **UI clash.** Node graph = opposite of the calm editorial aesthetic; Debi already disliked Odysseus's arrangement. Resolution = **headless + a new bespoke surface** (Fable-designed), node graph optional/hidden. Do **not** modify ComfyUI's own UI (complex, fragile, and forking breaks one-click updates — compose-not-fork rule).
3. **License + platform.** **GPL-3.0** → zero obligations for personal use (like SearXNG's AGPL); arm's-length API-wrapping keeps it clean even for a future ship — but copyleft means **ideas/API only, never lift code**. Apple Silicon works via **MPS but needs nightly PyTorch**, and **some CUDA-only nodes/models won't run** — it's not ComfyUI's strongest platform (Draw Things is more Mac-optimized, but ComfyUI's ecosystem + clean API win for a composable backend).

**Sequencing:** future — think **"M5: Senses,"** and only after the model-memory scheduler exists. Legitimately a "maybe." If added, day one is: run headless, drive via REST/WS, build a small "generate" surface; skip the node graph unless wanted.

**Verdict:** **Yes-but, deliberately and later.** Right engine, real upside, heaviest lift. Wrap it headless, never fork it, and don't start until model-memory scheduling is real.

---

## The shared architectural consequence (the real thing these force)

The moment **LLM + Voicebox + ComfyUI** can all be loaded, **model-memory scheduling becomes a first-class Bridge concern.** Today the Bridge treats each component as an independent process with its own lifecycle. Multimodal-on-unified-memory breaks that assumption: something must decide *what's resident when*, on a shared 64GB pool.

This is a **new capability the Bridge will need** (not currently in any milestone — genuine new work, cf. `09` §gaps):
- Track resident model memory across the runner + any modality components.
- Load/park on demand (e.g., free the LLM's KV/weights while a video render runs, restore after).
- Surface it in Mission Control (a memory/VRAM gauge — overlaps the cost/analytics idea in `09` §3.3).
- Relates to the KV-cache/slot-pinning idea (`09` §3.1): both are about being deliberate with the memory pool.

**Practical takeaway:** Voicebox is light enough to add without this. **ComfyUI should not be attempted until this scheduler exists.** So the honest dependency chain is: core handshake (M0) → runner slot + one-switch (M1) → unified surface (M2) → *model-memory scheduler* → ComfyUI.

---

## Sources
- Voicebox — https://github.com/jamiepine/voicebox (MIT; FastAPI+Tauri+MLX; REST :17493 + MCP; Whisper STT + 7 TTS engines; ~45k★, v0.5.0)
- ComfyUI — https://github.com/comfy-org/comfyui (GPL-3.0; Python/PyTorch; REST+WS API; image/video/audio/3D; MPS on Apple Silicon w/ nightly-PyTorch + CUDA-only caveats; ~122k★)
- Related: `09_Ideas_StealList_and_Gaps.md` (KV-cache, analytics, gaps), `02_Architecture.md` (component manifests, one-switch), `08_Interface_Strategy.md` (design governance), `04_Roadmap.md` (M0→M4).

*Facts verified by reading each repo's GitHub page 2026-07-21; nothing was run. Personal-first: nothing here creates shipping obligations today.*
