# ONLYOFFICE static-editors probe — 30-minute runbook

**Date:** 2026-08-21 · **For:** Debi (runs it) → Fable (decides) · **Status:** kit built, NOT run
**Source of the shortlist:** `docs/research/2026-08-21-office-alternatives-deep.md` §0, §7, §9
**Script:** `scripts/probe_onlyoffice.sh` · **Everything lands in** `data/office-probe/` (gitignored)

---

## The question this answers

The deep sweep found that **ONLYOFFICE's editors are pure client-side static files** —
`x2t.wasm` for OOXML conversion plus `sdkjs` + `web-apps` for the real ribbon. No
DocumentServer, no Docker, no Linux, no second process. CryptPad has shipped exactly that
since 2021. If it works, our job in the office lane shrinks from *owning an app shell
forever* to *serving `/assets` and listing files* — and the sentence **"it round-trips your
.docx"** becomes true for the first time.

But the report is honest about its own limit, verbatim:

> **Nothing here was executed on macOS. No document was round-tripped.**

So: **thirty minutes before another session.** Exactly the shape of the music-engine
measurement, and for the same reason — one real run on the real machine settles what a
week of reading cannot.

⚠️ **Two things this probe deliberately does NOT decide.**
1. **The AGPL-3.0 ruling.** ONLYOFFICE's editors and x2t are AGPL-3.0, and serving AGPL
   JS/WASM from our own bridge inside our own page is a *closer* coupling than
   SearXNG-over-HTTP. That is a **Fable call, not a builder call, and it has not been
   made.** A pass here means "it works", not "we may ship it".
2. **Whether we switch.** Tier 1 (our own grid) is browser-verified and stays either way.

---

## Step 0 — sixty seconds, zero download

Before you install anything, open this in **Safari**:

<https://fernfei.github.io/OnlyofficePersonal/office.html>

That is the same client-side ONLYOFFICE stack, hosted by its author. If the ribbon renders
there, WebKit can run it and the rest of this runbook is worth the disk. If it dies on the
spot, say so and stop — we go straight to the converter-only fallback.

⚠️ It is a *remote* page, so it proves WebKit can run the editors; it does not prove our
offline serving works. That is what the rest of the probe is for.

---

## Step 1 — make the script executable

**Do this first.** The script was written by an agent with no shell, so it arrives without
its execute bit — and a `scripts/*.sh` at mode 644 is precisely how the Aider tab's Install
button did nothing at all. `bridge/tests/test_script_hygiene.py` will fail (and therefore
`ship.sh` will refuse) until this is run:

```
cd ~/"Claude Proj Rootz/New Harness/harness" && chmod +x scripts/probe_onlyoffice.sh
```

## Step 2 — fetch both tracks

```
cd ~/"Claude Proj Rootz/New Harness/harness" && ./scripts/probe_onlyoffice.sh personal
```

```
cd ~/"Claude Proj Rootz/New Harness/harness" && ./scripts/probe_onlyoffice.sh cryptpad
```

**Track A — `personal`** clones [`fernfei/OnlyofficePersonal`](https://github.com/fernfei/OnlyofficePersonal),
a *finished* static ONLYOFFICE site (`office.html`: new document / open a local file / edit /
save back; Word, Excel, PPT, PDF). This is the go/no-go, because it is already wired — we
are measuring WebKit, not our own integration skill.

**Track B — `cryptpad`** downloads the two release zips CryptPad's own installer uses —
`onlyoffice-editor.zip` and `x2t.zip` — records their sha256/sha512, **checks those hashes
against CryptPad's live `install-onlyoffice.sh`**, unzips them into CryptPad's documented
layout (`dist/v9/` and `dist/x2t/`), and reports what actually landed. These are the
artifacts we would really vendor; their lineage is clean, unlike Track A's.

Either command can be re-run; both skip work already done.

## Step 3 — serve it

```
cd ~/"Claude Proj Rootz/New Harness/harness" && ./scripts/probe_onlyoffice.sh serve
```

Then open **<http://127.0.0.1:8787/>** in **Safari**.

> **Why Safari and not Chrome.** Safari and the harness's tabs are both WebKit. Every single
> bug in six sessions of office-lane pain has lived in WebKit and in nothing else. A pass in
> Chrome would decide nothing.
>
> ⚠️ **Honest delta:** Safari is WebKit but it is not literally our `WKWebView` — process
> model, JIT policy and some resource limits differ slightly, and our tabs additionally have
> app-level delegates (downloads, file pickers, media capture) that a browser has natively.
> Safari is the right *go/no-go* instrument; a full pass would be re-confirmed in an actual
> tab during the adoption slice. Do **not** skip Safari in favour of Chrome to save time.

If the console asks for `SharedArrayBuffer`, stop the server and start it with cross-origin
isolation on:

```
cd ~/"Claude Proj Rootz/New Harness/harness" && OO_ISOLATE=1 ./scripts/probe_onlyoffice.sh serve
```

The probe ships **its own** static server (`data/office-probe/serve.py`) rather than
`python3 -m http.server`, for three reasons that would each turn a pass into a false fail:
`.wasm` must be served as `application/wasm` or `instantiateStreaming` refuses it;
everything is `no-store` (we have already lost hours to one stale cached document); and the
bundle is thousands of files, so it is threaded and keep-alive. Requests are logged — **a
line marked `NOT OK` is evidence**, and a request with no response at all is the good kind
of evidence.

---

## The pass bar — do these in order

| # | Check | Where | Result |
|---|---|---|---|
| 1 | The real ONLYOFFICE **ribbon** renders (File / Home / Insert tabs, formula bar, sheet tabs) | Track A | |
| 2 | **New sheet**: type numbers, type `=SUM(...)`. Does it calculate? | Track A | |
| 3 | **Save / export .xlsx.** Does a real file come out? Open it in Excel/Numbers | Track A | |
| 4 | **Import your own .xlsx** (see below). Do formulas, merges, number formats, bold/fill survive? | Track A | |
| 5 | Same for a **.docx**, if the bundle carries the documents editor | Track A | |
| 6 | **x2t self-test** — does the converter instantiate and expose its `FS`? | `/probe-x2t.html` | |
| 7 | **Load time** (first paint of the ribbon) and **RAM** in Activity Monitor | both | |
| 8 | **Web Inspector console** (Develop menu): anything red? | both | |

Your own spreadsheets, made by LOffice, are here — use a real one, not a fresh blank:

```
open ~/"Library/Application Support/Harness/data/office"
```

⚠️ **Copy a file before importing it.** Nothing in this probe writes to `data/office/`, but
the whole point is to see what a foreign editor does to a real document — do that to a copy.

---

## The table to fill in

| | Track A (OnlyofficePersonal) | Track B (CryptPad zips) |
|---|---|---|
| Ribbon renders | | n/a — raw editor shells only |
| New sheet + formula works | | |
| Export .xlsx opens in Excel | | |
| Import of my own .xlsx — fidelity (1 line) | | |
| .docx round-trip (1 line) | | |
| x2t.wasm instantiates | | |
| Time to a usable ribbon (seconds) | | |
| RAM in Activity Monitor (Safari, GB) | | |
| Console errors | | |

Also record, because they make it reproducible — the script prints all of them:

- OnlyofficePersonal commit: `cat data/office-probe/personal.sha` → ______________
- Editor tag actually downloaded: ______________ (default `v9.2.0.119+3`)
- x2t tag actually downloaded: ______________ (default `v7.3+1`)
- Did the sha512 **match CryptPad's installer**? `cat data/office-probe/CHECKSUMS.txt` → ______
- Unzipped size on disk: ______________
- Mac model + RAM + macOS version: ______________

The discovered bundle layout is written to `data/office-probe/layout.json` and rendered at
the bottom of the probe index page. **That file is itself a deliverable** — the layout could
not be read from the sandbox, so whatever it shows is new information for the adoption slice.

---

## The decision rule (pre-ruled, from the research §9)

> **PASS** — the ribbon renders, a real `.xlsx` survives an open→edit→save→reopen, and the
> load time and RAM are tolerable → **adopt the ONLYOFFICE static bundle as LOffice tier 2**,
> replacing the lazy Univer loader we already built for exactly that slot. Tier 1 (our own
> instant-boot grid, zero third-party JS) **stays** as the default. `x2t.wasm` becomes the
> conversion engine for both, retiring the openpyxl fidelity ceiling.
>
> **FAIL** — the editors are too much for WebKit → **`x2t.wasm` as converter only**, behind
> our own tier-1 grid. Still a strict upgrade on openpyxl (charts, images, pivots, conditional
> formatting and everything else we currently drop and warn about). **SuperDoc** stays on the
> shelf for `.docx`.

Partial results are useful and expected. The most likely mixed outcome is **item 6 passes
while items 1–5 struggle** — that is exactly the FAIL branch, and it is a good outcome, not a
wasted afternoon.

Two things worth doing regardless of the verdict, both cheap:
1. **"Open in ONLYOFFICE"** escape hatch — `brew install --cask onlyoffice`, detect-never-install
   (the `ensure_ffmpeg` precedent), `open -a ONLYOFFICE <file>`. Guaranteed fidelity, about an
   hour. ⚠️ its CLI/URL-scheme surface is UNVERIFIED.
2. **`unoserver` + the LibreOffice cask** as an optional third tier for `.odt`/`.pdf`/legacy
   `.doc` — with the macOS `open -W -n -a` SIGABRT fallback pre-budgeted (research §4).

---

## Cleanup

```
rm -rf ~/"Claude Proj Rootz/New Harness/harness/data/office-probe"
```

or `./scripts/probe_onlyoffice.sh clean`. That removes every byte: the clone, both zips,
the unzipped bundle, the server and the probe pages. Nothing else on the machine was
touched — no component, no port, no manifest key, no venv, no `vendor/`, and nothing in
`bridge/panel/assets`.

---

## Honest limits of this measurement

- **Safari is not `WKWebView`** (see Step 3). Right instrument for go/no-go, not a
  substitute for one confirmation inside a real tab at adoption time.
- **Track A's bundled ONLYOFFICE copies are of unverified provenance.** The research flags
  this exact class — assets exported from a Developer-Edition Docker image — as a licensing
  hazard. Track A is a **measurement vehicle only**; adoption vendors Track B's zips, whose
  lineage through CryptPad is clean and checksummed.
- **The pins are ⚠️ unresolved between two readings.** The research read CryptPad's installer
  as pinning editor `v9.2.0.119+5` with a newer x2t at `v9.3.0+0`; a second reading of the
  same file says `v9.2.0.119+3` and `v7.3+1`. `api.github.com` and `raw.githubusercontent.com`
  were both unreachable from the sandbox, so neither could be settled. The script **defaults
  to the +3 / v7.3+1 pair** (the combination CryptPad ships and tests together), **asks GitHub
  at run time what the latest tag is and prints it without switching**, and **records the tag
  and hashes it actually got**. Those recorded values are the pin if this passes — exactly how
  `measure_music.sh` handled the unresolvable acestep sha. Override deliberately with
  `OO_EDITOR_TAG=` / `OO_X2T_TAG=`.
- **Track B's editor shells may well stall at a loading screen.** They are raw ONLYOFFICE
  entry points that normally expect a document server to answer. That is *information* about
  what integration would cost, not a failure of the probe — note how far each gets and what
  the console says. Track A is where the pass/fail lives.
- **The x2t self-test is discovery-shaped, not assertion-shaped.** The exported module symbol
  could not be read offline, so the page loads `x2t.js`, lists every global that appeared,
  tries each plausible factory and reports what it finds — including finding nothing. Read
  its log rather than trusting a green line.
- **One run, one machine, one document.** This measures feasibility, not throughput.
- **Nothing here is adoption.** No component entry, no port, no manifest key, no registry row.

---

## ✅ RESULTS — 2026-08-27, run by Fable 5 in a REAL WKWebView (stronger instrument than Safari)

**Instrument:** not Safari — a purpose-built headless `WKWebView` harness (1440×900, console-error
hook injected at documentStart, JS checks, PNG snapshots). This is literally the engine the
harness's tabs use, so the go/no-go is measured on the real thing. Snapshots reviewed by Fable.

**THE HEADLINE FINDING — `OO_ISOLATE=1` is REQUIRED, not optional.** Without COOP/COEP the
spreadsheet editor renders its full frame and then hangs at "Loading spreadsheet" forever
(`SharedArrayBuffer` absent; zero console errors — it fails silently). With
`Cross-Origin-Opener-Policy: same-origin` + `Cross-Origin-Embedder-Policy: require-corp` +
`Cross-Origin-Resource-Policy: same-origin` it loads completely. **Adoption consequence: the
bridge must serve the editor bundle with those three headers — and everything embedded in
that page must be same-origin** (a COEP page refuses cross-origin subresources without CORP).
WKWebView honors all of it (`crossOriginIsolated === true` measured in-page).

| # | Check | Result |
|---|---|---|
| 1 | Real ribbon renders | **PASS** — File/Home/Insert/Draw/Layout/Formula/Data/Collaboration/Protection/View, formula bar, name box, styles gallery, sheet tabs, zoom |
| 2 | Formulas calculate | **PASS** — `=SUM(B2:B5)`/`=SUM(C2:C5)` in the imported file computed to 22200/13100 on open |
| 3 | Save/export .xlsx | **NOT PROVEN headless** — the probe harness has no download delegate (same gap our tabs already solved for VoiceStudio); queue for the adoption slice or a 2-min Safari click |
| 4 | Import a real .xlsx | **PASS, high fidelity** — bold+gold-fill header, `#,##0.00` number formats, italic, merged+centered A8:C8, column width, BOTH sheets (Budget/Notes), all values. Served via `docConfig.document.url`; x2t.wasm did the conversion client-side |
| 5 | .docx editor | **PASS** — Word editor loads: full ribbon, page canvas, rulers, styles gallery, page/word count. (Slides untested, same bundle.) |
| 6 | x2t instantiates | **PASS de facto** — check 4 IS x2t doing a real xlsx→editor conversion (stronger than the discovery page) |
| 7 | Load time | Frame ~5s; fully interactive grid 40–75s COLD (includes first wasm compile + AllFonts.js over localhost, no HTTP cache). Warm-cache + precompiled expectations much lower — measure in the adoption slice |
| 8 | Console errors | **ZERO** across landing, spreadsheet (cold+warm), rich import, and docx runs |

**Recorded pins:** OnlyofficePersonal commit `0cb5e083cf7de6078c6230a2abacaf9447e6ff68` ·
editor `cryptpad/onlyoffice-editor @ v9.2.0.119+3` (sha256 `68ae8f0f…30f`, sha512 recorded in
CHECKSUMS.txt — ⚠️ **NOT FOUND in CryptPad's live install-onlyoffice.sh**, the runbook's
predicted pin drift; the recorded hashes ARE the pin now) · x2t `v7.3+1` · 3.2 GB on disk
unzipped · Mac: Debi's Apple-Silicon MacBook Pro, macOS 25.6.0.

**VERDICT per the pre-ruled decision rule: PASS → adopt the ONLYOFFICE static bundle as
LOffice tier 2, replacing the Univer lazy-loader; tier-1 grid stays; x2t.wasm becomes the
converter for both.** Still open before shipping, exactly as the runbook fenced: (a) the
AGPL-3.0-served-from-our-page ruling — Fable call, NOT yet made; (b) save-back proof (check 3);
(c) Track B (CryptPad zips) is what gets vendored — Track A was the measurement vehicle only;
(d) RAM under a real tab; (e) the COOP/COEP serving requirement lands in the bridge.

## ⚖️ THE AGPL RULING (Fable 5, 2026-08-27) — GO for personal use, with distribution conditions

ONLYOFFICE's editors and x2t are AGPL-3.0. The AGPL's obligations attach to **conveying**
the software or offering it as a **network service to others** — neither of which a
loopback-only personal harness does. Serving the unmodified bundle from the bridge to the
same machine's own user is private use; running it is unconditionally permitted.

**Ruling: GO for LOffice tier-2 adoption, on four standing conditions:**
1. **Vendor Track B only** (CryptPad-lineage zips), UNMODIFIED, with the recorded hashes and
   upstream source URLs kept beside them — the hashes in CHECKSUMS.txt are the provenance.
2. **Arm's length**: served as its own static bundle under its own route; no intermixing of
   its code with ours (the SearXNG conveyance posture, one step closer but same shape).
3. **If the harness is ever distributed** (the fat dmg to anyone else): the About/Help
   surface must name ONLYOFFICE + AGPL-3.0 and link the exact source of the vendored
   version; any modification we ever make to the bundle must be published. This line item
   goes into the fat-installer checklist NOW so it cannot be forgotten later.
4. Track A (fernfei) is **never** shipped — measurement vehicle only, provenance unverified.
