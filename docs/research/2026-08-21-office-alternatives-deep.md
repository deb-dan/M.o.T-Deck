# Office lane — deep alternatives sweep (re-examining everything, including the rejects)

Date: 2026-08-21 · Method: `git clone --depth 1` of candidates, npm registry reads, raw.githubusercontent
fetches, vendor docs. `api.github.com` blocked throughout ⇒ **every release-asset byte size below is
⚠️ UNVERIFIED**. One sandbox exhausted its disk mid-run (a blobless clone of `cryptpad/onlyoffice-builds`);
findings after that point are doc/source-read only. **Nothing here was executed on macOS. No document was
round-tripped.** Supersedes nothing in `2026-08-20-office-lane-recon.md` — it *corrects* it.

---

## 0. TL;DR — the thing the first recon got wrong

The first recon rejected ONLYOFFICE by testing **ONLYOFFICE Docs (DocumentServer)**, the Linux/C++/Node
server. That rejection is correct and stands. But it tested the wrong artifact.

**ONLYOFFICE's editors run 100% client-side. No DocumentServer. No Docker. No Linux. No second process.**
CryptPad has shipped exactly that since 2021, and at least four independent projects have generalised it
into a static, backend-free bundle. The architecture:

```
.docx/.xlsx --x2t.wasm--> ONLYOFFICE .bin --sdkjs + web-apps (the real ribbon)--> edit
                                          --x2t.wasm--> .docx/.xlsx back out
```

Both halves are **static files served over plain HTTP** — the exact thing `bridge/app.py:63`'s `/assets`
mount and `scripts/fetch_vendor_assets.sh` already do twelve times over. Conversion is ONLYOFFICE's *own*
OOXML pipeline, i.e. the best `.docx`/`.xlsx` fidelity in open source (ONLYOFFICE is OOXML-native;
LibreOffice round-trips *through* ODF's model and loses things on the way).

Evidence — `cryptpad/cryptpad/install-onlyoffice.sh` at HEAD is `curl` + `unzip` + `sha512sum` + `git`,
nothing else (`ensure_command_available` list: git, curl, sha512sum, unzip, less — **no compiler, no
Docker, no apt**):
- `install_version()` → `github.com/cryptpad/onlyoffice-editor/releases/download/$VERSION/onlyoffice-editor.zip`,
  sha512-verified, unzipped to `www/common/onlyoffice/dist/v9/`. Pin: **`v9.2.0.119+5`**.
- `install_x2t()` → `github.com/cryptpad/onlyoffice-x2t-wasm/releases/download/$VERSION/x2t.zip`,
  sha512-verified. CryptPad pins `v7.3+1`; **latest is `v9.3.0+0` (2026-04-24, x2t 9.3.0.140)**.
- CryptPad FAQ, verbatim: *"CryptPad's Document, Presentation & Spreadsheet applications are an OnlyOffice
  Docs integration that only concerns the client-side code, as CryptPad **does not make use of the
  OnlyOffice Document Server**."* (docs.cryptpad.org/en/FAQ.html)

x2t.wasm is **library-shaped and usable alone**, without the editor UI. From `onlyoffice-x2t-wasm/test.js`:
format IDs `xlsx 257, xls 258, ods 259, csv 260, pdf 513, docx 65, doc 66, odt 67, txt 69, html 70,
pptx 129, ppt 130, odp 131`; API is a `TaskQueueDataConvert` XML blob plus an Emscripten in-memory FS
(`x2t.FS.open/write/readFile`) and a `/working/fonts/` dir. `pre-js.js` sets `noInitialRun`/`noExitRuntime`
+ a `locateFile` shim. Its own build needs emscripten+qmake in Docker — **build-time only; prebuilt zips
exist**, so we never touch Docker.

Independent generalisations (this is not a CryptPad-only trick):

| Project | Shape | License |
|---|---|---|
| [fernfei/OnlyofficePersonal](https://github.com/fernfei/OnlyofficePersonal) | static site: `python -m http.server` → `office.html` → Word/Excel/PPT/**PDF**, offline, macOS named | **AGPL-3.0** |
| [electroluxcode/onlyoffice-web-comp](https://github.com/electroluxcode/onlyoffice-web-comp) | React wrapper + `OnlyOfficeManager` (`openDocument`, `downloadExport`, `toggleReadOnly`) | ⚠️ unverified; ⚠️ uses **Developer-Edition** Docker-exported assets → licensing hazard. Copy the API, not the assets |
| [sweetwisdom/onlyoffice-web-local](https://github.com/sweetwisdom/onlyoffice-web-local), [badnotes/freeoffice](https://github.com/badnotes/freeoffice) | same pattern, Vue | ⚠️ unverified |

**The two real gates**, both decidable, neither a dead end:
- ⚠️ **AGPL-3.0** (`ONLYOFFICE/web-apps/LICENSE.txt`, fetched by the installer's `ask_for_license`). Unlike
  SearXNG/VoiceStudio the arm's-length argument is **weaker** — this is JS/WASM we would serve from our own
  bridge inside our own page, not a separate process we talk to over HTTP. **Fable call, not a builder call.**
  Also ⚠️ ONLYOFFICE published a [license-and-trademark policy](https://www.onlyoffice.com/blog/2026/05/onlyoffice-license-and-trademark-policy) (May 2026) and
  [publicly flagged Nextcloud/IONOS's "Euro-Office"](https://www.onlyoffice.com/blog/2026/03/onlyoffice-flags-license-violations-in-euro-office-project-by-nextcloud-and-ionos) (Mar 2026): don't rebrand it, keep attribution.
- ⚠️ **Size**: CryptPad's docs quote **~830 MB** additional disk for a full v8.3 install (all editors,
  dictionaries, fonts, help). Their own script `rm -rf`s `main/resources/help`; trimming to sheets+docs cuts
  it further. Budget **several hundred MB**. ⚠️ exact zip sizes unverified.
- ⚠️ **Unmeasured in WKWebView.** A ~100 MB WASM module in the engine that has already burned six sessions.

---

## 1. CryptPad as a component app — runs, but the storage model disqualifies it

- **License** AGPL-3.0. **Runs on macOS without Docker: yes, mechanically.** Install is `git clone` a tag →
  `npm ci` → `npm run install:components` → `node server` (docs.cryptpad.org/en/admin_guide/installation.html).
  Pure Node, Active LTS, no database (flat files). Docs recommend Debian 12 / 2 GB RAM / 2 CPU / **20 GB**;
  macOS is not a named target ⚠️.
- **The two-domain problem is not a blocker on loopback.** CryptPad needs `httpUnsafeOrigin` ≠
  `httpSafeOrigin` for its iframe sandbox; the documented dev mode uses **`localhost:3000` + `localhost:3001`**
  via `httpSafePort` (different port = different origin). Their "not appropriate in production" caveat is
  about networks filtering odd ports — irrelevant here. So *two loopback ports*, not two DNS names.
- **It would give the full recognizable office UX** — because it is the ONLYOFFICE editors of §0, wrapped in
  a finished Drive app. That is the whole appeal.
- ❌ **Disqualifier: CryptPad stores end-to-end-encrypted blobs, not files.** There is no `data/office/`
  full of real `.xlsx`. Every document enters and leaves through *its* import/export UI. That breaks: the
  harness files-on-disk model, `bridge/office.py` containment, the AI side panel's sheet context, agent/tool
  access to spreadsheets, and any future "Hermes, edit this sheet". We'd have an office suite the rest of the
  harness cannot see. **Reject as a component; harvest its asset pipeline instead** — which is §0.

---

## 2. Grist — the best-behaved component candidate, wrong product

- **Apache-2.0** (`LICENSE.txt:1-3`, `package.json`), ⚠️ **but `yarn install` defaults to the *full*
  edition and downloads non-OSS code into `ext/`** (`buildtools/install_edition.sh:26-30`; README.md:298-300).
  Clean path: `yarn run set-community-edition` / `GRIST_EDITION=community`.
- **macOS without Docker: YES, and it is the only candidate with a *native* sandbox.** README.md:291-297
  `yarn install && yarn install:python && yarn build && yarn start` → `localhost:8484`. Sandbox flavors
  (`app/server/lib/NSandbox.ts:523-538`): `gvisor | unsandboxed | docker | macSandboxExec | pyodide` —
  `macSandboxExec` shells macOS's own `sandbox-exec` (`NSandbox.ts:1068`, detected `:629`, auto-picked `:772`).
  ⚠️ README.md:561 still documents a `pynbox` flavor that no longer exists — stale doc.
- Binds loopback already: `FlexServer.ts:131 GRIST_HOST || "localhost"`; health `GET /status` (`:617`).
  Python3 venv from `sandbox/requirements.txt` (openpyxl 3.0.10 …). Node 22 (`.nvmrc`).
- ❌ **xlsx is data-in / different-data-out, not a round-trip.** Import
  (`sandbox/grist/imports/import_xls.py:43`) is `openpyxl.load_workbook(..., data_only=True)` — **formulas
  discarded, cached values only**, no styles/merges/number-formats, then it *guesses headers*. Export is
  `exceljs` re-rendering **Grist's own** styling (`workerExporter.ts:198-245`). ❌ **docx: zero hits** in the
  whole tree.
- **Verdict: an excellent macOS citizen and a genuinely polished UI — but it is a relational Airtable, not a
  spreadsheet.** It will never hand back the file Debi opened. Same category error as NocoDB/Teable/Baserow/
  SeaTable (all Airtable-shaped, all export computed rectangles).

---

## 3. Etherpad + EtherCalc — both live, both surprising, both wrong-shaped

- **Etherpad** (Apache-2.0, v3.3.3, last commit **2026-08-20**): trivially macOS/no-Docker, Node ≥24 + pnpm,
  port 9001 ⚠️ default binds `0.0.0.0` (`settings.json.template:195`), `/health` (`specialpages.ts:52`).
  **Now does .docx natively without LibreOffice** — `html-to-docx`, `mammoth`, `pdfkit` in `src/package.json`;
  `settings.json.template:497-505` says soffice is optional and *"pixel-perfect PDF fidelity is a non-goal"*
  (`docs/superpowers/specs/2026-05-08-native-docx-pdf-export-import-design.md`). ❌ **Structural fidelity
  only, and it is a collaborative *notepad*** — no pagination, no sheets. README.md:27: *"We are actively
  looking for maintainers."*
- **EtherCalc** — ⚠️ **the "it's stale" premise is refuted**: `package.json` version `0.20260717.0`, last
  commit 2026-08-11, rewritten as *"TypeScript rewrite (Cloudflare fullstack)"*. Real xlsx via
  `@e965/xlsx` with REST `GET /{id}.xlsx` (API.md:240-266). ❌ But the runtime is now **Bun + `bunx wrangler`
  (a Cloudflare Workers emulator)** — `engines: {bun}`, `bin/ethercalc` is `#!/usr/bin/env bun`, docker-compose
  is the documented path. ⚠️ license is mixed (`package.json` CC0-1.0 vs `LICENSE.txt` CPAL + Artistic-2.0).
  A Workers emulator as a long-lived macOS service is a worse dependency than anything else here. **Reject.**
- **la Suite Docs** (MIT) — ❌ Django + Postgres 16 + Redis + MinIO + Celery + nginx ×2 + **Keycloak** +
  a separate Yjs `y-provider` + a `docspec` conversion container (`compose.yml:5,20,29,99,119,137,190,231,262`),
  with `mozilla-django-oidc` structural. Right category, five-service platform. **Reject.**

---

## 4. Collabora / LibreOffice, re-examined — the rejection is structural, not packaging

- **CODE on macOS: permanently no.** `--enable-macosapp` is gated *inside* `if ENABLE_MOBILEAPP`
  (`Makefile.am:31-33`); `coolwsd`/`coolforkit` build only in the `!ENABLE_MOBILEAPP` branch. The Mac target
  is the bundled Cocoa app (LOK + JS UI in a webview), **not** the WOPI server. No brew formula; the only
  request ([online#15168](https://github.com/CollaboraOnline/online/issues/15168), 2026-03-23) is open,
  `unconfirmed`, and asks for the desktop app anyway. **Nextcloud Office** doesn't rescue it (it's a frontend
  over a Collabora/ONLYOFFICE backend; the bundled CODE binary is Linux).
- **unoserver is the real conversion daemon** (MIT, **v3.7, 2026-06-10**, 7 releases/12mo): resident
  LibreOffice + XML-RPC, defaults `127.0.0.1` on both ports, README says outright the ports *"must not be
  accessible outside the server stack"* — matches loopback-only exactly. ⚠️ *"Windows and Mac support is as of
  yet untested"*; `pyproject.toml` classifies Linux only; `server.py:689-704` finds soffice via
  `shutil.which` (**PATH only** — a hand-dragged `.app` is invisible, so `brew install --cask libreoffice`
  matters: it installs a `command_wrapper "soffice"`; cask v26.2.5, `arch arm: aarch64`, ~284 MB).
  ⚠️ **Known macOS abort at our exact versions**: [CLI-Anything#221](https://github.com/HKUDS/CLI-Anything/issues/221)
  (macOS 26.0.1 / Apple Silicon / LO 26.2.1.2) — identical argv works in a shell, exits **−6 SIGABRT** under
  `subprocess.run()` with `NSApplication sharedApplication` in the stack *despite* `--headless`;
  [PR#290](https://github.com/HKUDS/CLI-Anything/pull/290) fixes it with an isolated `-env:UserInstallation`,
  `--nolockcheck`, and a macOS-only `open -W -n -a` fallback. **Budget that fallback before the first Mac test.**
  Always pass an isolated profile or we collide with Debi's own LibreOffice via its single-instance lock.
- Other drivers: **JODConverter** (Apache-2.0, v4.4.11, genuinely mac-aware — `LocalOfficeUtils.java:59-62`
  hardcodes `/Applications/LibreOffice.app/Contents`) is the best-engineered but **needs a JVM** → reject.
  **unoconv** archived 2025-03-31 → dead. **pylokit** 2016, Linux `.so` → dead. **LibreOfficeKit** real, mac
  contemplated upstream, no maintained Python binding.
- **LibreOffice WASM / ZetaOffice** — `allotropia/zetajs` wrapper MIT, blobs MPL-2.0, 100% client-side,
  perfect fidelity *by construction*. ❌ **~250 MB** (`soffice.wasm` ~154 MB + `soffice.data` ~95 MB), cold
  start 20-90 s, **cached start still 10-30 s**, still beta on a LibreOffice 24.2 vintage, and self-hosting is
  *"see the Contact section"* — no DIY docs. ⚠️ the site footer now reads **Collabora Productivity Germany
  GmbH** (allotropia appears absorbed → no independent second source). ⚠️ sizes secondary-source, CDN 403'd.
  **It solves the same problem as §0 and loses on every axis: bigger, slower, beta, not prebuilt, worse OOXML.**

---

## 5. ONLYOFFICE's other artifacts

| Item | License | Mac/no-Docker | Verdict |
|---|---|---|---|
| **DocumentServer native mac build** | AGPL-3.0 | **NO** | Confirmed dead end; every thread routes to Docker or a Linux VM; `document-server-package` = deb/rpm only |
| **Desktop Editors** | AGPL-3.0 | **YES** — `brew install --cask onlyoffice`, v9.4.0, native Apple Silicon since 6.1/6.4 | **app, not a tab.** Viable as an escape hatch: `open -a ONLYOFFICE <file>` (it registers the OOXML doc types). ⚠️ no CLI flags/URL scheme documented — UNVERIFIED. **Notable: its AI plugin ships LM Studio + Ollama as named providers with custom base_url** ([docs](https://api.onlyoffice.com/docs/plugin-and-macros/ai/custom-providers/)) → it would talk to `:6767` with zero work |
| **Document Builder** | ⚠️ **commercial gate** | YES — `onlyoffice-documentbuilder-macos-arm64.tar.xz`, `pip3 install document-builder` | ❌ **REJECT — the tempting near-miss.** Install docs: *"The free version … includes a **watermark on all generated documents**."* Disqualified as a fidelity engine |
| **x2t standalone native** | AGPL-3.0 | ⚠️ unverified | No brew formula, no prebuilt mac binary; building `ONLYOFFICE/core` is a large Qt/C++ job. **The WASM build is strictly easier and is prebuilt** |
| **DocSpace** | AGPL-3.0 | **NO** — *"Linux server only, DEB/RPM or Docker"* | Reject |

---

## 6. The SDK shelf, if we keep owning the shell

**Univer is a dead end for fidelity, verified three ways** — and this retroactively *validates* the LOffice
tier-1 architecture rather than indicting it. OSS `@univerjs/*` is Apache-2.0 and alive, but xlsx I/O lives in
**`@univerjs-pro/exchange-client`, whose npm `license` field is literally `Proprietary`**; it is
**server-required** (*"requires support from the Univer server"*, whose documented environment is
**Docker 23+ / Compose / MySQL / Redis**); unlicensed use gets *"watermark, import size, and collaboration
quotas"*. Univer's own docs concede it: *"You can use open-source DOCX parsing libraries … and then use the
Facade API to import."* **Univer buys us a grid and nothing else.**

| Engine | License | Verdict |
|---|---|---|
| **SuperDoc** (`superdoc-dev/superdoc`) | **AGPL-3.0** + commercial | ⭐ **The only browser DOCX editor built for round-trip.** v2 uses an *"OOXML-backed document model … edits write back to the XML without an HTML conversion step"*; pagination/sections/headers/footers/tables stay document structures; *"needs no server of its own"*; npm `superdoc` v2.7.1-next.9, modified **2026-08-20** — the most active thing in this report. ❌ **DOCX only** — zero xlsx/spreadsheet hits across the monorepo |
| **umya-spreadsheet** (Rust) | MIT | ⭐ Best-maintained xlsx fidelity engine found (v3.1.0, commit 2026-08-18); models styles/charts/images; native arm64 **or WASM** |
| **@office-kit/xlsx** | MIT | ⭐ **WATCH** — explicitly targets our problem (*"…need them preserved byte-for-byte"*), byte-identical passthrough of unmodelled parts, ECMA-376 XSD validation in CI. ⚠️ pre-1.0, ~1 commit since May 2026, bus-factor-1 |
| **SheetJS CE** | Apache-2.0 | ❌ CE *deliberately omits styling, charts, images, pivots, conditional formatting on write*; npm `xlsx` frozen at 0.18.5, real dist is their own CDN (breaks pin discipline) |
| **ExcelJS** | MIT | ❌ stalled (npm 2024-12), drops pivot tables on read |
| **Fortune-sheet** + `@corbe30/fortune-excel` | MIT | ❌ plugin more serious than expected, but sits on stale ExcelJS *and* must survive fortune-sheet's cell model → lossy. Host last commit 2025-11 |
| **Luckysheet / x-spreadsheet** | MIT | ❌ abandoned (npm 2022) |
| **jspreadsheet-ce** | MIT | ❌ alive but thin xlsx; the money is in Pro |
| **Handsontable / Syncfusion / DHTMLX** | non-OSS | ❌ fails "open source" |
| **Quadratic** | ⚠️ **closed-source since Mar 2026** ("Source Available", self-host needs a license key) | ❌ |
| **BlockNote** | MPL-2.0 core; exporters GPL-3.0-OR-PROPRIETARY | ❌ export only — `@blocknote/xl-docx-importer` **404s on npm** |
| **Tiptap** | MIT core; **DOCX = Tiptap Pro, paid** | ❌ legacy import/export extensions sunsetting 2026 |
| **AFFiNE / AppFlowy / Outline** | MIT / AGPL / **BSL-1.1 (not OSS)** | ❌ none does docx fidelity; AppFlowy is a desktop app, Outline a markdown wiki |
| `docx`, `mammoth`, `docx-preview`, `docxtemplater` | MIT/BSD/Apache | ❌ generate-only / one-way→HTML / render-only / template-fill |

---

## 7. Ranked verdict

| Candidate | License | Mac, no Docker | Tab shape | xlsx | docx | UX recognizability | Integration cost | Verdict |
|---|---|---|---|---|---|---|---|---|
| **ONLYOFFICE static bundle (x2t.wasm + sdkjs/web-apps)** | AGPL-3.0 ⚠️ | **YES** (static files) | ✅ our page, no process | ⭐⭐⭐ native OOXML | ⭐⭐⭐ native OOXML | ⭐⭐⭐ **the actual ONLYOFFICE ribbon** | ~1-2 slices + a vendor-assets fetch | **★ ADOPT (pending 30-min measurement + AGPL ruling)** |
| **x2t.wasm alone, our grid** | AGPL-3.0 ⚠️ | YES | ✅ | ⭐⭐⭐ conversion only | ⭐⭐⭐ conversion only | ⭐ (ours) | ~1 slice | **★ the low-risk half-step** |
| **unoserver + LibreOffice cask** | MIT / MPL | YES ⚠️ untested-on-mac + known SIGABRT | ✅ (backend only) | ⭐⭐ | ⭐⭐ | n/a | 1 slice | ✅ keep as the fidelity backstop |
| **SuperDoc** | AGPL-3.0 | YES (npm lib) | ✅ | ❌ | ⭐⭐⭐ | ⭐⭐ | 1-2 slices | ✅ best docx-only fallback |
| **ONLYOFFICE Desktop Editors** | AGPL-3.0 | YES (brew cask) | ❌ app | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ~1 hour (`open -a`) | ✅ ship as an "Open in ONLYOFFICE" escape hatch regardless |
| **Univer (status quo)** | Apache-2.0; **I/O is Proprietary + Docker** | YES | ✅ | ⭐ (ours) | ⭐ (ours) | ⭐⭐ | already built | ◐ works, permanently capped |
| **Grist** | Apache-2.0 ⚠️ ext/ | YES ⭐ | ✅ :8484 | ❌ data-only | ❌ | ⭐⭐⭐ | 1 slice | ❌ wrong product (Airtable) |
| **CryptPad** | AGPL-3.0 | YES (2 loopback ports) | ✅ :3000/:3001 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | 1-2 slices | ❌ **encrypted blobs, not files** |
| **Etherpad** | Apache-2.0 | YES | ✅ :9001 | ❌ | ⭐ structural | ⭐ | 1 slice | ❌ notepad |
| **EtherCalc** | ⚠️ mixed | painful (Bun+wrangler) | ◐ | ⭐⭐ | ❌ | ⭐ | high | ❌ |
| **la Suite Docs** | MIT | **NO** | — | ❌ | ⭐⭐ | ⭐⭐⭐ | — | ❌ 5-service platform |
| **ZetaOffice / LO-WASM** | MIT+MPL | YES | ✅ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | high | ❌ 250 MB, 10-30 s cached start, beta, no self-host docs |
| **ONLYOFFICE Docs / DocSpace / Collabora CODE** | AGPL / MPL | **NO** | — | — | — | — | — | ❌ structural (confirmed again) |
| **Document Builder** | ⚠️ watermark | YES | — | — | — | — | — | ❌ watermark on every save |
| **Quadratic / Handsontable / Tiptap-DOCX / BlockNote** | non-OSS or export-only | — | — | — | — | — | — | ❌ |

---

## 8. Stay, switch, or hybrid — the honest paragraph

**Univer works today and switching has a real cost**: tier-1 is browser-verified, `bridge/office.py`'s
openpyxl mappers round-trip, the AI panel is wired, and `test_office_lane`/`test_office_grid` pin it. Nothing
below deletes that. **But the six sessions of pain were not bad luck — they were the predictable tax of
assembling an application out of an SDK.** Every bug was ours because every line was ours: the invisible
`#msg`, the 0×0 canvas, the leaking `header{}`/`button{}` selectors, the render-blocking stylesheet, the
caret. Univer's own docs then cap the ceiling: the import/export that would justify all that ownership is
`Proprietary` and Docker-only. So the choice is not "Univer vs a rewrite" — it is **"keep owning an app
shell forever, or host a finished one."** The ONLYOFFICE static bundle is the only option that *reduces*
owned surface: the ribbon, menus, formula bar, pagination and the format converter all arrive as vendored
artifacts, and our job shrinks to what the harness is already good at — serving `/assets`, listing files
under `data/office/`, and taking POSTed bytes. A component app (CryptPad/Grist class) is the *wrong* trade:
Grist can't give the file back, and CryptPad — which has exactly the editors we want — keeps everything as
encrypted blobs the rest of the harness can never read. **The hybrid is real and is the de-risked path:
adopt `x2t.wasm` alone first** (a self-contained ~tens-of-MB converter with a clean `FS` JS API, no editor
UI), keep tier-1's grid, and get ONLYOFFICE-grade `.xlsx`/`.docx` conversion immediately; the full editor
bundle then becomes a *tier-2 opt-in* that replaces the lazy Univer loader we already built for exactly that
slot.

## 9. The recommendation I would defend

**Spend thirty minutes before spending another session.** Unzip `x2t.zip` + `onlyoffice-editor.zip` into a
folder, `python3 -m http.server`, open it in **a WKWebView** (not Chromium — WKWebView is where every one of
these bugs has lived), and put one of Debi's real `.xlsx` files through open → edit → save → reopen in Excel.
That single measurement decides everything, exactly the way the music-engine measurement did.

If it passes: **adopt the ONLYOFFICE static bundle as LOffice tier 2, keep our tier-1 grid as the instant-boot
layer, and vendor `x2t.wasm` as the conversion engine for both.** Ship "Open in ONLYOFFICE" (`brew install
--cask onlyoffice`, detect-never-install, per the `ensure_ffmpeg` precedent) the same day — it costs an hour,
gives a guaranteed-fidelity escape hatch, and its AI plugin already speaks to `:6767`. Keep `unoserver` +
LibreOffice as the optional third tier for `.odt`/`.pdf`/legacy `.doc`, with the `open -W -n -a` fallback
pre-budgeted. If it fails in WKWebView: fall back to **x2t.wasm-as-converter-only** behind our own grid —
still a strict upgrade on openpyxl — and keep **SuperDoc** on the shelf for documents.

**Two things must be decided before any of it, and neither is a builder's call:** (a) **AGPL-3.0 JS/WASM
served from our own page** is a closer coupling than SearXNG-over-HTTP — Fable rules, and the answer likely
also settles SuperDoc; (b) the **fidelity contract wording** — with ONLYOFFICE's own converter we can finally
promise "round-trips your .docx", which is the first time that sentence would be true.

**Could not verify:** all release-asset byte sizes (api.github.com blocked); `cryptpad/onlyoffice-builds`
contents (clone exhausted the sandbox disk); licenses of `onlyoffice-web-comp`/`onlyoffice-web-local`/
`freeoffice`; any DesktopEditors CLI/URL scheme; EtherCalc's export being true OOXML vs SpreadsheetML-2003;
Grist's real installed footprint. **And, decisively: nothing here was run on macOS and no document was
round-tripped through anything.** Every fidelity claim above is read from source and vendor docs.
