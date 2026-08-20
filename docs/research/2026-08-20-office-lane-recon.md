# Office lane recon — how to get docx/xlsx editing INSIDE the harness

Date: 2026-08-20 · Method: shallow `git clone` of every candidate + vendor-doc fetches.
Sandbox limits: `api.github.com` blocked (⚠️ no star/release counts), release CDNs blocked.
file:line refs are from the checkouts named in each section.

## 0. TL;DR — ranked

1. **Univer, served BY OUR BRIDGE from `/assets/vendor` (no new process).** Apache-2.0, alive
   (HEAD `6ac9953` dated **2026-08-20**), ships **UMD builds** designed to be self-hosted. Doctrine-pure.
   ⚠️ Its `.xlsx/.docx` import-export is **Univer Pro + a server + a commercial licence** — so *we*
   own the round-trip (LibreOffice headless, or python-docx/openpyxl in the bridge).
2. **Scoped fork of genoffice's `apps/docs`** — much less of a swamp than expected (its docx engine is
   browser-safe and its renderer touches Electron only through ONE preload object), but it is still a
   fork of a repo we rejected, with a ~60-method shim to write. Plan B.
3. **ONLYOFFICE Docs CE** — ❌ **FAILS DOCTRINE.** Linux/Docker/Windows only, AGPL, needs nginx+services.
4. **Collabora Online (CODE)** — ❌ **FAILS DOCTRINE.** Linux server; the macOS target is a *desktop app*.
5. **Extend Odysseus/artifacts** — the wrong frame: we don't lack an editor, we lack *format fidelity*.

## 1. What the harness already has — the honest gap

`bridge/app.py:63` already mounts `/assets` (`StaticFiles`) and `scripts/fetch_vendor_assets.sh:17`
vendors 12 third-party libs into `bridge/panel/assets/vendor/` (babel, react+react-dom UMD, mermaid,
CodeMirror 5, tailwind…) — **a proven "self-host a JS SDK and serve it ourselves" path**.
The artifact/canvas system already edits + saves files (`/api/artifact/save`, `bridge/app.py:5685`).
But `artifactKind()` knows exactly: `code, csv, html, image, js, json, markdown, mermaid, pdf, react, svg`.
**No office format anywhere.** Odysseus's doc editor is a rich-text/canvas surface, not an OOXML one
(`vendor/odysseus` has no `python-docx`/`openpyxl` in requirements).

So the gap is **`.docx`/`.xlsx` round-trip fidelity**, not "an editor". Any plan that ships a beautiful
web grid but writes CSV has solved nothing. **Every option below should be judged on the round-trip.**

## 2. ONLYOFFICE Docs Community — ❌ REJECT (Docker/Linux only)

- **No macOS anywhere.** The Community install index lists exactly: Docker, Linux, Windows, Cloudron,
  hosted (DigitalOcean/Vultr) — `helpcenter.onlyoffice.com/docs/installation/community`, fetched today.
  `Readme.md` in `ONLYOFFICE/DocumentServer` has **zero** matches for macos/darwin.
- **Source build is Linux-only.** `ONLYOFFICE/build_tools/README.md:3` — *"compiling ONLYOFFICE products
  from source **on Linux**"*, verified on Ubuntu 24.04 amd64 / 100 GB SSD. `tools/` has `android linux
  mac win` but **`tools/mac/` contains only `7za` and `toolchain.prf`** — no `automate.py`: no mac
  product build at all; those bits serve the Qt *desktop* editors, not the server.
- **Even on Linux it is not one process:** nginx + `FileConverter` + `DocService` started separately,
  plus font/theme generation steps (build_tools README, "Step 1-3").
- **Licence: AGPL-3.0** (`DocumentServer/LICENSE:1`). Arm's-length is fine for us, but moot.
  ⚠️ **UNVERIFIED: the AI plugin's base_url** — `ONLYOFFICE/plugin-ai` was not clonable from this
  sandbox (404 → credential prompt); irrelevant while the server cannot run.
- **Verdict: fails the no-Docker rule outright. Say it plainly to Debi: ONLYOFFICE Docs cannot be a
  harness component on a Mac.**

## 3. Collabora Online / CODE — ❌ REJECT (Linux server; the Mac target is a desktop app)

Clone: `CollaboraOnline/online` is now **only** docker/ + kubernetes/ + issues — *"Active development …
has moved to our Gerrit instance"* (`README.md:3-13`). Source mirror = `online.mirror`.
- **The server jails with Linux primitives.** `wsd/COOLWSD.cpp:3699` picks `"namespace"` vs `"chroot"`;
  `kit/` is documented as *"The client which lives in its own **chroot** and renders documents"*
  (mirror `README.md`, Development bits). Neither exists on macOS.
- **There IS a macOS target — and it is not the server.** `configure.ac:190` `--enable-macosapp`
  *"Use on a Mac where you will build the macOS app"*, grouped at `:100` with the iOS/Android/Windows
  **apps**. `macos/README.md` builds **"the Collabora Office macOS desktop app"** via
  `--with-distro=CPMacOS-LOKit`, requiring **Homebrew + Xcode CLT + Node 20 + a full LibreOffice core
  build**, then `xcodebuild` on `macos/coda/coda.xcodeproj`. (`macos/coolwsd/coolwsd.xcodeproj` exists —
  the wsd machinery is embedded *inside that app bundle*, not exposed as a loopback service.)
- Even if it ran, integration is **WOPI**: you must host a WOPI storage backend (their own docs point at
  Nextcloud/ownCloud + `richdocuments`, mirror README "Test running with integration").
  Licence MPL-2.0 (mirror README, Key features) — fine, again moot.
- **Verdict: no server-shaped macOS build without Docker; a multi-hour LibreOffice-core Xcode build that
  yields a .app Collabora already ships prebuilt. Reject.** If Debi wants that, she installs Collabora
  Office for Mac like any other app.

## 4. genoffice fork — smaller than feared, but still a fork of a rejected repo

Clone: `genspark-ai/genoffice` (Apache-2.0; `ee/` carve-out per the HermesOffice recon). Two findings
that materially change the earlier "swamp" estimate:
- **The docx engine is browser-safe.** `packages/docx-engine/package.json` deps are exactly
  `fast-xml-parser`, `jszip`, `utif2` — **zero `node:`/`fs` imports in `src/`** (grepped). Its own
  description: *"docx parsing (Block tree with docxIndex anchors), OOXML fragment generation,
  **paragraph-patch save**"* — i.e. **byte-preserving round-trip, running in a browser.** That is the
  single most valuable asset in this whole recon and the thing no other OSS web editor gives us.
- **The renderer is barely Electron-coupled.** Across 96 `.ts/.tsx` files in `apps/docs/src/renderer`,
  **0** reference `ipcRenderer`/`window.electron`; everything goes through `window.desktop` (59 uses) and
  `window.projectApi` (3), both `contextBridge.exposeInMainWorld` at `apps/docs/src/preload/index.ts:162-163`.
- **The cost is that shim.** That preload exposes **~60 methods** (`openDocx`, `saveDocx`, `saveDocxAs`,
  `fontMetrics`, `exportPdf`, `pickImage`, `readAttachment`, `aiChat`/`aiStream`, `webSearch`,
  `listProjects`, tab/menu/close-check callbacks…). Serving `apps/docs` as a web tab = build the Vite
  renderer + reimplement `window.desktop` against bridge HTTP endpoints. Realistically **10-15 matter**
  for editing (open/save/saveAs/fontMetrics/exportPdf/images), AI rewires to `:6767` (our own code, not
  theirs), and the menu/tab/project half is an Electron-only concern we'd drop.
- **Sheets is a different story: `apps/sheets/native/xlsx-engine` is a Rust sidecar** — so a "convert
  genoffice" project is *docs only* unless you take a Rust toolchain too. Slides = its own pptx engine.
- **Verdict: a scoped fork of ONE editor (docs) is a real 2-3 slice project, not a swamp — but it is a
  fork of a bus-factor-1-adjacent upstream we rejected, we'd own the shim forever, and it inherits their
  React/Vite build. Keep as Plan B; prefer taking the *idea* (browser-side OOXML patching) over the code.**

## 5. Univer — the doctrine-pure winner, with one caveat that shapes the whole build

Clone `dream-num/univer`: **Apache-2.0** (`LICENSE:1`, `package.json:10`, and every package's
`"license"` sampled — core, sheets, docs-ui, presets). HEAD **`6ac9953`, 2026-08-20** — alive today.
Node ≥22.18 to *develop*; nothing to run.
- **Docs + Sheets + Slides in one SDK** (`packages/` has `docs-ui`, `sheets-ui`, `slides-ui`, plus
  `engine-formula`, conditional formatting, data validation, find/replace, comments, drawing, tables).
- **It is servable from our bridge with zero new process.** UMD global builds exist per package:
  `unpkg.com/@univerjs/presets/lib/umd/index.js` + `@univerjs/preset-sheets-core/lib/umd/index.js`
  + `lib/index.css`, and the docs say outright *"or **download them for distribution via your own
  server**"* (docs.univer.ai → Import Univer via CDN). Preset mode = **~6 script tags**
  (react 18.3.1, react-dom, rxjs, echarts, presets, preset-*) — every one of which
  `fetch_vendor_assets.sh` already knows how to vendor (react 18.3.1 **is already in
  `bridge/panel/assets/vendor/`**). ⚠️ pin exact versions: the UMD page warns React 19 needs shims.
- **⚠️ THE CAVEAT — import/export is Pro.** docs.univer.ai → *Import & Export*: *"requires support from
  the **Univer server** … refer to Upgrading to Pro"*; the packages are `@univerjs-pro/exchange-client`
  and config points at a `universerEndpoint` (`http://localhost:3010`). Univer Server is Docker-shaped +
  commercially licensed → **we cannot use it, and must not pretend to.**
- **But Univer itself names the escape hatch** (same page): *"You can use **open-source DOCX parsing
  libraries** to parse files into data structures that conform to the `IDocumentData` interface, and
  then use the Facade API to import data into Univer."* Snapshot-path APIs are public
  (`createWorkbook(snapshot)`, `getSnapshot()`), and collaboration is not required.
  → **We supply the round-trip; Univer supplies the surface.**

## 6. Others considered

- **FortuneSheet** (`ruilisi/fortune-sheet`) — MIT, Luckysheet successor, drop-in React grid. But
  sheets-only, pre-1.0 (*"input data structure and APIs may change"*), docs self-described *"outdated"*,
  and xlsx import/export is a **third-party plugin** (`corbe30/fortuneexcel`). A weaker Univer.
- **SheetJS CE** — Apache-2.0, real xlsx read/write in-browser; the pragmatic converter if we want
  sheets round-trip with no LibreOffice. ⚠️ npm channel is stale; they distribute from their own CDN.
- **Etherpad** — Apache-2.0, tab-shaped, but plain text/HTML. Nothing for OOXML.
- **LibreOffice headless as OUR converter — the fidelity workhorse.** `/Applications/LibreOffice.app/
  Contents/MacOS/soffice --headless --convert-to docx` is a one-shot local process, MPL-2.0, no Docker,
  no server. `unoserver` (LibreOffice listener over loopback XML-RPC :2003) is the persistent variant —
  ⚠️ its README says outright *"Windows and Mac support is as of yet **untested**"*, though it documents
  the Mac python path (`/Applications/LibreOffice.app/Contents/Resources/python`). **Start with one-shot
  `soffice`; treat unoserver as an optimisation.** Cost: LibreOffice is a ~700 MB user-installed app —
  a dependency we'd *detect*, never auto-install (the `ensure_ffmpeg`/`ensure_bun` precedent).
- **python-docx / openpyxl** (both MIT, pure-python, bridge-venv friendly) — the no-LibreOffice fallback:
  good for content-level round-trip, lossy on layout/charts. LibreOffice = fidelity, python = the floor.

## 7. Recommendation + build shape

**Build an Office lane the way the Music lane was built: our own page, our own bridge module, an SDK we
vendor — not a component tab.** Rank: (1) bridge-served Univer, (2) scoped genoffice-docs fork,
(3) extend artifacts, (4)/(5) ONLYOFFICE + Collabora are non-starters on macOS-without-Docker.

Sketch (mirrors the `voice.py`/`music.py` precedent, so nothing here is a new pattern):
- `scripts/fetch_vendor_assets.sh` +6 pinned Univer UMD/CSS assets → `assets/vendor/univer/`; **pin
  exact versions** in `harness.yaml` `build.univer_pin` (existing pin discipline).
- New panel view **📄 Office** (sidebar entry), two surfaces (Document / Sheet) over one Univer instance,
  rendered same-origin from `/assets` — **no new port, no `/health` card, no component**.
- New `bridge/office.py` (ship.sh already copies `bridge/*.py`):
  `GET /api/office/files` (a configurable folder — `music_settings.json` precedent),
  `POST /api/office/open {path}` → convert `.docx/.xlsx` → `IDocumentData`/`IWorkbookData` snapshot,
  `POST /api/office/save {path, snapshot}` → write OOXML back. Containment via `realpath` + the
  configured base dir, exactly like `library_target`/music.
- **Round-trip resolver, honest about tiers:** LibreOffice-if-present (probe an explicit path list —
  the Finder-minimal-PATH rule) → else python-docx/openpyxl → else refuse *loudly* naming what's missing.
  The panel must **say which tier it used** — a silently lossy save is the worst possible bug here.
- AI side-panel calls the **existing** `/api/chat/direct` (`:6767`) with the selection as context —
  we already own that lane; nothing new is registered anywhere.

**Two decisions before building (Fable-lane):** (a) the fidelity contract — do we promise "round-trips
your .docx" or "opens it, edits, saves an equivalent"? Only LibreOffice earns the first, and it is a
user-installed dependency. (b) whether slice 1 is **Sheets only** — I'd say yes: Univer's strongest
surface, and openpyxl/SheetJS make xlsx the cheaper round-trip; learn the fidelity tiers on the easier
format, then do Documents.
