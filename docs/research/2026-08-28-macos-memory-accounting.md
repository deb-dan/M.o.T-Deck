# macOS Memory Accounting for the RAM Fit Advisor (Apple Silicon)

**Date:** 2026-08-28 · **Machine verified against:** Apple M5 Pro (`Mac17,8`), 64 GB unified, macOS 26.6.1 (25G76), 16 KB pages.
**Live stack at measurement time:** llama-server (runner, 16 GB Q4_K_S gguf + 1.7 GB F32 mmproj, 65k ctx), two bridges, Hermes, Harness.app shell + WebKit XPC helpers, unsloth studio, voicestudio, searxng. Swap was under real load: 18.1 GB used of 19.4 GB.

Everything below marked **[verified]** was measured on this machine today with read-only probes.

---

## 1. The right per-process metric: `phys_footprint`, not RSS

**Use `proc_pid_rusage(pid, RUSAGE_INFO_V4/V6, …)` → `ri_phys_footprint`.** This is the number Activity Monitor's "Memory" column shows and what the `footprint(1)` CLI reports. The kernel maintains it as a ledger:

```
phys_footprint = (internal − alternate_accounting)
              + (internal_compressed − alternate_accounting_compressed)
              + iokit_mapped + purgeable_nonvolatile
              + purgeable_nonvolatile_compressed + page_table
```

(osfmk/kern/task.c ledger; see bazhenov.me anatomy post and WWDC22 10106.)

Why it is the honest metric, per property:

| Memory kind | RSS (`ri_resident_size`) | `phys_footprint` |
|---|---|---|
| Dirty anonymous pages in RAM | counted | counted |
| **Compressed pages** (in compressor) | **not counted** | **counted** (at uncompressed size) |
| **Swapped-out pages** | **not counted** | **counted** |
| Clean mmap'd file pages (model weights not dirtied) | counted while resident → double-counts shared files | **not counted** (reclaimable at zero cost — fair) |
| Shared dyld cache / frameworks | partially counted per process → sums over 100% | only dirty portions counted |
| IOKit/graphics memory mapped for the process | mostly invisible | counted (`iokit_mapped`, "Owned physical footprint (graphics)") |
| Page tables | not counted | counted |

### The critical test on the live runner **[verified]**

llama-server serving the 16 GB gguf (+1.7 GB mmproj), two snapshots ~20 min apart:

| snapshot | phys_footprint | RSS | delta (RSS lie) |
|---|---|---|---|
| idle-ish | 13,795 MB | 5,107 MB | **−8.7 GB** |
| during inference | 15,427 MB | 7,244 MB | **−8.2 GB** |
| lifetime peak (`ri_lifetime_max_phys_footprint`) | 18,591 MB | — | — |

Under swap pressure (this machine had 18 GB swapped), **RSS understated the runner by ~8.5 GB** because compressed/swapped pages leave the resident set but remain in the footprint. An advisor built on RSS would happily tell the user "the 16 GB model is using 5 GB" — a confident lie that inverts the fit verdict.

### The mmap story **[verified]**

`footprint 64588` region breakdown for the runner:

```
Dirty      Clean     Category
7531 MB    0 B       MALLOC_LARGE
6102 MB    0 B       untagged (VM_ALLOCATE)
  64 MB    0 B       Owned physical footprint (unmapped) (graphics)
8272 KB    0 B       IOAccelerator (graphics)
   0 B     3662 MB   mapped file          ← the gguf's resident clean pages
─────────────────────
13 GB dirty + 3668 MB clean; phys_footprint = 13 GB (dirty only)
```

Two honest facts fall out:

1. **Clean mmap'd weight pages are NOT in phys_footprint.** The 3.66 GB of the gguf that was resident showed up as *clean mapped file*, excluded from the footprint. That is *correct* accounting — those pages are evictable for free and re-readable from disk — but it means a runner using pure mmap'd CPU inference can show a small footprint while still occupying RAM as file cache. If you want to show "RAM touched by this model right now", footprint alone under-shows the file-cache share; `footprint(1)`'s clean column (or `ri_resident_size − dirty`) reveals it.
2. This LM Studio-built runner (Metal) held most weights as **dirty anonymous memory** (MALLOC_LARGE + VM_ALLOCATE ≈ 13.6 GB ≈ weights + mmproj + 65k-ctx KV cache), which footprint counts fully — including the ~8.5 GB of it that was compressed/swapped at the time. Note for other builds: llama.cpp's Metal path can also wrap the mmap'd region in no-copy `MTLBuffer`s, in which case pages wire (and enter footprint) when the GPU working set touches them — the entire mmap'd shard containing GPU tensors gets wired together (ggml-org discussion #9999).

### Getting it cheaply for a pid list **[verified]**

`proc_pid_rusage` is a single syscall per pid, no privileges needed for same-user pids: **0.08–0.18 ms for 12–17 pids total (~7–10 µs/pid)** via ctypes/direct call. Fields (RUSAGE_INFO_V4, after 16-byte uuid): `ri_phys_footprint` (offset 7), `ri_resident_size` (6), `ri_lifetime_max_phys_footprint` (28) — the peak field is gold for "this component spiked to 7.3 GB once" (voicestudio: current 817 MB, peak 7,347 MB **[verified]**).

The `footprint(1)` CLI: **34–91 ms per pid [verified]** (full VM-region walk), `footprint -a` **requires root [verified]**. Use it as a debug drill-down ("explain this number"), never in the sampling loop.

Failure mode **[verified]**: `proc_pid_rusage` returns non-zero only for exited pids (and other-user/system pids). Treat error = "component gone", resample the pid list.

---

## 2. GPU/Metal memory on unified memory

- Metal buffer allocations land in the owning process's **phys_footprint** (as IOAccelerator / "Owned physical footprint (graphics)" / wired-when-in-use regions) and, while the GPU working set holds them, in **system wired memory**. There is no separate VRAM pool to account — which is exactly why per-process footprint stays honest on Apple Silicon: the runner's Metal weights are *its* footprint.
- **[verified]** This machine: `iogpu.wired_limit_mb = 0` and `iogpu.wired_lwm_mb = 0` (0 = "system default policy", not unlimited; `iogpu.wired_limit_mb` superseded `debug.iogpu.wired_limit`). The effective ceiling is what Metal reports: `MTLDevice.recommendedMaxWorkingSetSize` = **55,662,788,608 B = 53,084 MB = 81% of 64 GB [verified via swift -e]**. The folk "75%" figure is model-dependent; measure, don't assume.
- **At the limit:** Metal allocations beyond the wired ceiling fail (`newBufferWithLength` returns nil / llama.cpp aborts or falls back); the kernel does not swap wired GPU memory. So the fit advisor's GPU bound is `recommendedMaxWorkingSetSize` (readable once at startup via a trivial Metal call, or parse `ggml_metal_init: recommendedMaxWorkingSetSize` from runner logs), *not* hw.memsize.
- Raising the ceiling with `sysctl iogpu.wired_limit_mb=N` is possible but eats into the kernel's wired headroom; if the advisor detects a non-zero override, show it and use it as the bound.
- System-wide wired at measurement time: 1,742,860 pages = **26.6 GB [verified]** — dominated by GPU working sets (runner + LM Studio). Wired is unreclaimable and uncompressible; treat it as a hard floor in the system view.

---

## 3. System-level truth

`host_statistics64(HOST_VM_INFO64)` — same numbers as `vm_stat` **[verified snapshot]** (16 KB pages): free 57,308 · active 858,092 · inactive 829,809 · speculative 33,205 · wired 1,742,860 · purgeable 20,750 · compressor-occupied 611,016 holding 2,889,283 stored pages · file-backed 232,947 · anonymous 1,488,159.

**What to compute (Activity Monitor semantics, mirrored by exelban/stats):**

- `memory_used = active + inactive + speculative + wired + compressor_occupied − purgeable − external(file-backed)`
- `app_memory = memory_used − wired − compressed`
- `cached_files = external (file-backed) + purgeable` — reclaimable, honest to show as *available-ish*, dishonest to show as *used*
- `compressed (as displayed) = pages occupied by compressor` (611,016 pg = 9.3 GB **[verified]**, matching `vm.compressor_bytes_used` = 9,749,446,656)
- **Compression ratio [verified]:** stored/occupied = 2,889,283 / 611,016 = **4.73:1** — visible, and worth showing: it's why 44 GB of "footprint" fit in 9.3 GB of RAM.
- `swap`: `sysctl vm.swapusage` → total 19,456 MB / used 18,122 MB **[verified]**; also pageouts/swapins deltas from vm_stat for rate.

**"Available" honestly means** `free + purgeable + file-backed cache + (most of) inactive` — but don't invent your own formula for the headline. Apple exposes the canonical one: **`kern.memorystatus_level`** = "System-wide memory free percentage" (this machine: **40–42% [verified]**, i.e. ~26 GB effectively available *while raw free was only 0.9 GB*). Raw free is meaningless on macOS — the pager keeps it near zero by design.

**Pressure beats free.** The kernel's own signal:

- `sysctl kern.memorystatus_vm_pressure_level`: 1 = normal **[verified now]**, 2 = warn, 4 = critical (exelban/stats uses exactly this mapping).
- Event-driven: `DISPATCH_SOURCE_TYPE_MEMORYPRESSURE` (NORMAL/WARN/CRITICAL) — subscribe instead of polling; this is what should flip the advisor's banner.
- `memory_pressure -Q` for a one-shot ("free percentage: 42%").
- Why it beats raw-free: pressure is the kernel's composite of free, compressor fill, swap rate, and reclaim cost — it goes WARN while "free" still looks fine, and stays NORMAL when free is tiny but caches are reclaimable (exactly this machine's state: 0.9 GB free, 18 GB swapped, yet pressure = normal and the system is fine).

---

## 4. Child processes, trees, and the WebKit problem

**Summing a tree:** enumerate pids (supervisor already knows them; for strays use ppid walk of `proc_listchildpids`/`ps -axo pid,ppid`) and **sum phys_footprint per pid**. Because footprint counts only dirty/compressed/owned memory, summing does **not** double-count shared libraries or clean shared mmaps — this is the property RSS lacks. Genuinely shared *dirty* memory (rare: explicit shm) is the only double-count risk; negligible for our stack. **[verified]** runner has no child processes (threads only); bridge spawns short-lived python children — sample at 1–2 s cadence and accept that sub-second children are missed (footprint of exited children is gone; `ri_child_*` fields in rusage only cover reaped direct children's CPU, not memory).

**The WebKit XPC problem — solved by "responsible pid":** Harness.app's WKWebViews live in `com.apple.WebKit.WebContent/GPU/Networking.xpc` processes whose **ppid is 1 (launchd)** — invisible to any ppid walk **[verified]**. But the private-but-stable libSystem call **`responsibility_get_pid_responsible_for_pid(pid)`** (same mechanism Activity Monitor and exelban/stats use to group processes) returns the app shell's pid for all of them **[verified]**:

```
Harness.app shell = 69447 (30–36 MB footprint — the UI is NOT here)
responsible→69447: WebKit.GPU 151 MB · WebKit.Networking 10 MB ·
                   3× WebKit.WebContent 45/45/730 MB · audio.SandboxHelper 3 MB ·
                   SafariPlatformSupport.Helper 9 MB · bridge python (also a child)
```

The main web-content process was **730 MB** vs the shell's 36 MB — without responsible-pid grouping the ledger would under-report the app shell by ~20×. Implementation: one pass over `proc_listallpids()`, filter `responsible == shell_pid`, union with the supervisor's known pid set, **dedupe by pid** (bridge appears both as supervised component and as responsible-child — primary key must be pid, display grouping by responsible pid).

Fallback honesty: if the responsibility call is ever unavailable (it's unexported/private; link via dlsym and feature-detect), show a labeled "App UI (WebKit helpers) — not attributable" row rather than silently omitting ~1 GB.

### Verified component ledger (this machine, live, footprint vs RSS in MB)

| component | pid | phys_footprint | RSS | lifetime peak |
|---|---|---|---|---|
| llama-server (runner, 16 GB gguf) | 64588 | **15,427** | 7,244 | 18,591 |
| bridge :8700 | 69453 | 60 | 69 | 60 |
| bridge :8791 | 41621 | 56 | 34 | 58 |
| hermes | 80152 | 243 | 163 | 243 |
| Harness.app shell | 69447 | 36 | 114 | 37 |
| — WebKit.WebContent (main UI) | 70137 | 730 | 764 | 945 |
| — WebKit.GPU | 69451 | 151 | 71 | 164 |
| — WebKit.WebContent ×2, Networking, helpers | | ~113 | ~196 | |
| unsloth studio | 5151 | 227 | 54 | 247 |
| voicestudio | 63160 | 817 | 39 | **7,347** |
| searxng | 37692 | 72 | 13 | 89 |
| **Total attributed** | | **≈18.1 GB** | | |

Query cost for the whole table: **0.18 ms [verified]**.

---

## 5. How the reference apps present it

- **Activity Monitor:** "Memory" column = `ri_phys_footprint`; "Real Memory" = `ri_resident_size` (hidden by default — Apple demoted RSS deliberately). Bottom pane: Memory Used (App + Wired + Compressed), Cached Files, Swap Used, and the **pressure graph** — which charts kernel pressure, not used/total; green/yellow/red = normal/warn/critical. Grouping "by responsibility" uses the responsible-pid mechanism above.
- **exelban/stats (open source, read):** `Modules/RAM/readers.swift` — `used = active+inactive+speculative+wired+compressed−purgeable−external`; `free = total − used`; `app = used − wired − compressed`; pressure from `kern.memorystatus_vm_pressure_level` (2→warning, 4→critical); per-process list shells out to `top` and groups children via `responsibility_get_pid_responsible_for_pid`. Same doctrine we're adopting, independently converged.
- **iStat Menus:** same Activity-Monitor-style split (App/Wired/Compressed + pressure); closed source, no new mechanism.
- **htop/btop on macOS caveats:** both display RES/`resident_size` per process — they inherit every RSS lie above (our runner would show 5–7 GB, not 15 GB), and their "used" bars typically count file cache as used. Fine for CPU, do not copy their memory model.
- **LM Studio:** hardware tab shows total unified RAM and "VRAM" = the Metal working-set ceiling (recommendedMaxWorkingSetSize-derived), plus per-model estimated-fit badges before load — the fit-advisor UX to beat; it runs a dedicated `systemresourcesworker` helper process for sampling **[observed live]**.
- **Ollama `ollama ps`:** shows per-loaded-model **SIZE** = ollama's own *estimate* of memory needed (weights+KV), not a measured footprint, plus a "100% GPU / 48%/52% CPU/GPU" split — honest about placement, silent about actual system impact. Useful pattern: show *planned* vs *measured* side by side; we can do both.

---

## 6. Sampling discipline and emit policy

**Cost ladder [verified]:**
1. `proc_pid_rusage` — ~7–10 µs/pid. Free at any sane cadence.
2. `host_statistics64` + `sysctl` (swapusage, memorystatus_level, pressure_level) — a few µs each. Free.
3. `footprint(1)` — 34–91 ms/pid, spawns a process, walks VM regions. Debug drill-down only, on explicit user click ("explain this number"), never periodic.
4. `footprint -a` — root-only. Never.

**Recommended design:**
- Supervisor keeps the pid set (components + responsible-children rescan). Responsible-children rescan (full `proc_listallpids` + responsibility filter) every 30 s or on component start/stop events — it's the only O(all-pids) step.
- Sample tier 1+2 every **2 s while the ledger UI is visible or a load/fit operation is in flight; 15 s otherwise; 0 when no SSE subscriber** — never wake idle CPUs for an unwatched dashboard.
- Subscribe to `DISPATCH_SOURCE_TYPE_MEMORYPRESSURE` (or poll `kern.memorystatus_vm_pressure_level` on the tier-2 tick as the portable fallback): pressure transitions emit **immediately**, bypassing cadence.
- **Emit policy on the events bus (delta-suppressed push):** emit a `memory.snapshot` event only when (a) a subscriber exists AND (b) any component footprint moved >2% or >32 MB, or system pressure/swap-used/memorystatus_level changed, or a pid appeared/died; hard max one emit per 2 s, hard min one keepalive per 60 s so clients can detect staleness. Pressure-level changes and component OOM-deaths are separate, uncoalesced events (`memory.pressure`, `component.exit`).
- Cache `ri_lifetime_max_phys_footprint` per component and persist per model+config: it is the empirical "what this model really peaked at" that makes the fit advisor learn (runner peak 18.6 GB for this 16 GB model at 65k ctx — the number the advisor should quote next time, not the file size).

## Presentation rules (so users aren't lied to)

1. Call the per-process number **"Memory footprint"** (matches Activity Monitor's Memory column). Never label it RAM/RSS: it includes compressed & swapped pages. Optional detail row: "of which in RAM: X · compressed/swapped: footprint−RSS".
2. Show **peak** next to current for every component (`ri_lifetime_max`), especially the runner.
3. System headline = **pressure state + memorystatus "free %"**, never `free bytes`. Words: "Memory pressure: normal · ~40% effectively available". Show swap-used and compression ratio as secondary facts, styled neutral (swap in use ≠ emergency when pressure is normal — this machine proves it).
4. Never sum RSS; never show a used/total bar that counts cached files as used.
5. GPU bound: "GPU-wireable ceiling: 53.1 GB of 64 GB (Metal recommended working set)"; flag if `iogpu.wired_limit_mb` is overridden.
6. mmap caveat on runners loaded with mmap + CPU: add a "＋ N GB cached model file" chip (clean mapped-file resident pages from `footprint` drill-down or file-cache heuristics) so a small footprint isn't mistaken for a small RAM impact.
7. Group UI helper processes under the app shell via responsible-pid, labeled "App UI (WebKit)".

## Honest-limits list (cannot be attributed — label, don't hide)

- **Kernel/driver wired overhead** (GPU page tables, compressor metadata, kernel itself): visible only in system wired total, not per-process. Label: "System wired (kernel + GPU driver): N GB".
- **Shared file cache** (model weights as clean pages benefit *every* process mapping them): attributable to no one; shown as Cached Files.
- **Sub-second child processes** between samples: invisible; note in docs, not UI.
- **Other-user / hardened system processes**: `proc_pid_rusage` fails; they live only in the "everything else" = `memory_used − Σ(attributed)` residual row — always show that residual so the ledger visibly sums to the system view.
- **Dirty shared memory** across our components (explicit shm/IOSurface sharing): double-counted if summed; negligible today, revisit if we add shared-memory IPC.
- **`responsibility_get_pid_responsible_for_pid` is private API** — feature-detect via dlsym; degrade to the labeled unattributed row.

---

## Sources

- Apple, [Activity Monitor user guide — memory pane](https://support.apple.com/en-lb/guide/activity-monitor/actmntr1001/mac)
- Apple, [WWDC22 §10106 "Profile and optimize your game's memory"](https://developer.apple.com/videos/play/wwdc2022/10106/) (footprint = dirty+compressed+swapped; Real Memory vs footprint)
- Denis Bazhenov, [Activity Monitor Anatomy](https://www.bazhenov.me/posts/activity-monitor-anatomy/) (ri_phys_footprint ledger formula, Real Memory = phys_mem ledger)
- [exelban/stats — Modules/RAM/readers.swift](https://github.com/exelban/stats/blob/master/Modules/RAM/readers.swift) (used/app formulas, pressure sysctl mapping, responsible-pid grouping)
- [HN discussion: Activity Monitor & footprint(1) both read phys_footprint](https://news.ycombinator.com/item?id=27242590)
- [ggml-org/llama.cpp discussion #9999 — mmap'd weights and Metal wiring](https://github.com/ggml-org/llama.cpp/discussions/9999); [DeepWiki: model loading/mmap](https://deepwiki.com/ggml-org/llama.cpp/3.2-model-loading-and-representation)
- iogpu wired limit: [ModelPiper](https://modelpiper.com/blog/iogpu-wired-limit-mb-mac), [ivanopcode dev note](https://github.com/ivanopcode/devnote-override-macos-metal-vram-cap), [Peddals](https://blog.peddals.com/en/fine-tune-vram-size-of-mac-for-llm/), [OSXDaily](https://osxdaily.com/2025/05/07/how-to-increase-vram-allocation-on-apple-silicon-mac/)
- Local verification (this machine, 2026-08-28): `proc_pid_rusage` RUSAGE_INFO_V4 via ctypes; `footprint(1)`; `vm_stat`; `memory_pressure -Q`; `sysctl iogpu vm.swapusage kern.memorystatus*`; `swift -e` Metal `recommendedMaxWorkingSetSize`; `responsibility_get_pid_responsible_for_pid` via libSystem.
