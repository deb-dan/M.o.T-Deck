# Music engine measurement runbook

**Date:** 2026-08-20 · **For:** Debi (runs it) → Fable (decides) · **Status:** prepared, NOT run
**Source of the shortlist:** `docs/research/(done) 2026-08-20-music-video-gen.md`
**Script:** `scripts/measure_music.sh`

---

## The question this answers

Music generation is green-lit, **measurement-first**. Two candidates survived the research,
and the research could not separate them because **neither has a single published
Apple-Silicon timing anywhere**:

| | **MiniMax-Music3** via `PocketAiHub/MiniMax-Music3-MLX` | **acestep.cpp** (`ServeurpersoCom/acestep.cpp`) |
|---|---|---|
| Shape | pure MLX, one-shot `generate.py` CLI — **exactly the voice lane** | C++/GGML + Metal, zero Python at runtime — **the llama.cpp of ACE-Step** |
| Weights | 11.9GB int8, pinned repack + SHA-256 manifest | ~7.7GB GGUF (LM-4B Q8_0 + emb + DiT turbo + VAE) |
| Licence | 🟠 MiniMax-Music3 Community (amber; badged in `LICENSE_OVERRIDES`) | ✅ MIT code, MIT weights |
| Claimed speed | *"several minutes"* for 60s at 30 steps — **no table, no number** | **nothing published at all** |
| Risk | bus factor 1, self-labelled "Experimental" | bus factor 1, no CI, no releases |
| Quality prior | the demo Debi actually liked | good, but a step below Music3 on vocals |

**Whichever wins becomes MOT Deck's own music lane** — our page, our controls, our
registry entry, in the shape the voice lane already established. This is **not** ComfyUI
and not the Video/Audio tab milestone; it is a native lane like `▶ speak`.

⚠️ **Before either run: eject the chat model.** A Music3 render wants 32GB minimum /
48GB recommended, and `memory.budget_gb` is 48 — one render can claim the entire ledger.
This script sits *outside* the ledger (deliberately — it adopts nothing), so the only
thing preventing a swap storm is the click:
**MOT Deck panel → Models → the row with the gold `live` pill → Eject**
(and Models → Aux runner → Stop, if it is up).

---

## Paste block 1 — MiniMax-Music3 (MLX)

Downloads ~11.9GB, builds a throwaway venv, renders a 60-second song at 30 flow steps.
Expect a long first run: most of it is the download.

```
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck" && ./scripts/measure_music.sh minimax
```

## Paste block 2 — acestep.cpp (GGML/Metal)

Clones + builds with cmake (Metal and Accelerate auto-enable on macOS), downloads
~7.7GB of GGUF, renders the SAME 60-second song at the turbo DiT's 8 steps.
Needs `cmake` (`brew install cmake`) and Xcode command line tools.

```
cd "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck" && ./scripts/measure_music.sh acestep
```

Each run ends with a `RESULT` line carrying wall seconds, max RSS in GB, and the path
to the audio. Open the file and **listen** — the subjective column matters as much as
the numbers.

## Cleanup, after both

```
rm -rf "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck/data/music-trial" "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck/data/music-trial-venv" "/Users/debik/GemiAntigravity/September 3rd new check harness/New Harness/MOT Deck/data/tmp/music-trial"
```

The weights stay in `~/.cache/huggingface` on purpose, so adopting the winner does not
re-download 12GB. Delete that separately if you want the space back.

---

## The table to fill in

| Engine | Song length | Wall seconds | Max RSS (GB) | Subjective quality (1 line) |
|---|---|---|---|---|
| MiniMax-Music3-MLX int8, 30 steps | 60s | | | |
| acestep.cpp GGUF Q8_0 turbo, 8 steps | 60s | | | |

Also record, because they make the numbers reproducible:

- acestep.cpp commit sha: `cat data/music-trial/acestep.cpp.sha` → ______________
- MiniMax-Music3-MLX revision: `0505e3f04ddfb883e0a2fbd8ad1a34c2f313e514` (pinned in the script)
- Mac model + unified RAM: ______________
- Was the chat model ejected? ______________

Raw logs, if anything needs diagnosing: `data/tmp/music-trial/*.log` (each holds the
engine's own stderr **and** its `/usr/bin/time -l` block).

---

## The decision rule (Fable, pre-ruled)

> **If Music3 renders a 60-second song in single-digit minutes and stays inside the
> ledger, it wins on quality and becomes the lane.** If it does not — too slow, or a
> peak that cannot coexist with anything else — **acestep.cpp / ACE-Step 1.5 takes the
> lane** on its MIT-everything licence, smaller footprint and hot-swap semantics that
> already match our Eject.

Two tiebreakers if the numbers land close:

1. **Licence.** ACE-Step is MIT code *and* MIT weights; Music3 is a Community licence
   that needs an amber badge and an attribution line on any commercial surface. For a
   personal machine both are fine; for anything shipped, MIT is strictly less work.
2. **Runtime shape.** acestep.cpp is zero-Python at runtime and loads on first request —
   it is closer to how our runner already behaves. Music3 is a one-shot subprocess —
   it is closer to how our *voice* lane already behaves. Both are honest fits; prefer
   the one whose failure modes we can already debug.

---

## Honest limits of the measurement

- **One prompt, one seed, one duration, one run each.** This measures order-of-magnitude
  feasibility, not throughput. Do not derive a tok/s-style figure from it.
- **The step counts are NOT the same knob.** Music3's 30 is the top of its own supported
  flow-step range and its acceptance setting; acestep's 8 is the turbo DiT's design
  point. Comparing 30-vs-8 is comparing *each engine at its intended setting*, which is
  the honest comparison for "which lane do we build" — but it is not an
  algorithm-vs-algorithm benchmark.
- **acestep.cpp is measured as two processes** (`ace-lm` then `ace-synth`). The wall
  clock in the table is their **sum**; the RSS is the **max**, because their peaks never
  coexist. Music3 is one process, so its two figures are simply that process.
- **First-run wall clock includes Metal shader compilation**, which a second run would
  not pay. If a number looks bad, re-run before believing it.
- **The acestep.cpp pin is a branch HEAD, not a chosen sha** — `api.github.com` and
  `github.com` were unreachable from the sandbox that wrote the script (only
  `raw.githubusercontent.com` answered), so no commit could be verified ahead of time.
  The script records whatever sha it cloned; that recorded value is the pin if this
  engine wins.
- **Nothing about this is adoption.** No component entry, no port, no manifest key, no
  registry row. If both engines disappoint, deleting three directories removes every
  trace.

## MEASURED (Debi's Mac, 2026-08-20 — both engines PASS feasibility)
| engine | song | wall | max RSS | notes |
|---|---|---|---|---|
| MiniMax-Music3-MLX int8, 30 steps (0505e3f) | 60s | **115.55s** | 2.2GB* | ~2× realtime |
| acestep.cpp GGUF Q8_0 turbo, 8 steps (9761469d95fc) | 60s | **24.45s** (lm 15.69 + synth 8.76) | 8.4GB | ~0.4× realtime |

*The MiniMax RSS is almost certainly UNDERSTATED — MLX's Metal buffers are wired GPU
allocations that /usr/bin/time -l's maxRSS does not fully capture. The practical fact
stands: the render completed in under 2 minutes with no swap storm on a 64GB machine
with the chat model ejected. The 32–48GB upstream guidance stays the planning number.

Ear verdict (Debi): PENDING — listen to both wavs before the engine ruling.
