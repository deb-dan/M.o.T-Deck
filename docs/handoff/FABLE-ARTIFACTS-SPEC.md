# FABLE 5 — ARTIFACTS + ROOMIER CHAT (§F and chat-workspace) — decision-free spec for Opus 4.8
Date 2026-07-31. Authority: Fable orchestrator (this is UI + a security surface — design decisions here are Fable's; Opus implements them). Build FUNCTION in the EXISTING dark editorial system — reuse `:root` tokens (serif/mono/cream/gold), no new colors or type scales. Leave `<!-- FABLE: style pass -->` markers where aesthetics need a later Fable touch. Never edit vendor/. Do NOT commit/push. Validate each phase. Everything MUST work fully OFFLINE — self-host every asset, no runtime CDN.

## Goal
When a chat produces a file (HTML, React/JSX, JS, SVG, Markdown, code, PDF, image), show it as a **card** in the transcript; clicking it opens a **live/interactive viewer** (HTML renders as a page, React/JS runs, code is highlighted + optionally runnable, md rendered). Plus: make the **Chat workspace roomier** (LM-Studio-like) so there's space for the viewer side-by-side or full-page. Existing `/api/open` path-allowlist stays as the "open in system app / show in folder" escape hatch.

Files in scope: `bridge/app.py`, `bridge/panel/index.html`, possibly a new `bridge/panel/assets/vendor/` for self-hosted libs, `scripts/` (an installer step to fetch the vendor JS once), `harness.yaml` if a version/asset pin is needed. NO Swift change required (all inside the existing Mission Control WKWebView) — if a Swift change seems needed, STOP and flag it.

Build in 3 phases; each independently Mac-verifiable (panel+bridge only, no app rebuild). Validate per phase: `python3 -c ast.parse` on app.py; `node --check` on EACH `<script>` block in index.html separately; CSS brace balance; small unit tests for pure logic (type-detection, path-allowlist).

---

## PHASE 1 — Roomier Chat workspace (layout only; LM-Studio-like)
Fable decisions — implement exactly:
1. **Collapse the left rail on the Chat view.** When the Chat view is active, add a root class (e.g. `body.chat-mode` or on the panel container) that CSS uses to collapse the left `aside` (WORKSPACE + COMPONENTS nav) to a **slim icon rail** (~56px): show only the glyphs, hide the text labels. Other views keep the full sidebar. A small toggle (chevron) lets the user expand it back manually; default = collapsed on Chat, full elsewhere. Persist the manual choice in `localStorage['harness-chat-rail']`.
2. **Hover tooltips everywhere (Debi request).** Every icon-only / glyph control in the panel (the collapsed rail items AND existing icon buttons) gets a native `title=""` (and `aria-label`) so hovering shows what it does ("Mission Control", "Models", "Eject", "Set aux", etc.). This is the "show the word on hover" ask — apply it broadly, not just the rail.
3. **Widen the chat column.** On Chat view, drop the narrow centered max-width; let the chat use the reclaimed width. Keep the session rail, but give it a collapse chevron too (`localStorage['harness-sessions-rail']`).
4. No functional change to chat behavior — layout/affordance only. Reuse existing tokens; leave `<!-- FABLE: style pass -->` on new structural bits.
Mac-verify: open Chat → left rail is slim icons (hover shows labels), chat is wider; other tabs unchanged; toggles persist across reloads.

---

## PHASE 2 — Artifact rendering engine + viewer (offline, sandboxed)
**Self-hosted assets (no CDN).** Add `bridge/panel/assets/vendor/` served by the bridge, containing (all MIT/Apache/BSD): `babel.min.js` (@babel/standalone), `react.production.min.js` + `react-dom.production.min.js` (UMD), a highlighter (**Prism** — small; or Shiki if you prefer fidelity), `markdown-it.min.js`, `dompurify.min.js`. Add a `scripts/fetch_vendor_assets.sh` that downloads these once at build/install time into that dir (so the repo can stay lean OR commit them — Fable decision: **fetch at install, gitignore the dir**, mirroring how other runtime assets work; the FAT build must bundle them into the seed so offline installs have them). ⚠️ tag if any asset can't be self-hosted.

**The viewer** (new right-side pane + full-page mode):
- A viewer container that can render in TWO modes (Debi wants BOTH): (a) **split pane** — opens on the right half of the Chat view, chat reflows to the left; (b) **expand** button → viewer takes the full panel area (overlay), with a close/restore back to split. A close button returns to chat-only.
- Type → renderer mapping (detect by extension, then by content sniff):
  - **html, htm** → sandboxed `<iframe srcdoc sandbox="allow-scripts">` (NO `allow-same-origin`) with a strict CSP `<meta>` injected into the srcdoc head (default-src 'none'; script-src 'unsafe-inline' plus the self-hosted asset origin only; style-src 'unsafe-inline'; img-src data: blob:). Renders as a page.
  - **svg** → same sandboxed iframe (SVG can carry script — treat as untrusted HTML).
  - **jsx, tsx, react** (or js/html that imports React) → sandboxed iframe whose srcdoc loads the self-hosted React+ReactDOM UMD + Babel-standalone, wraps the artifact in a `<script type="text/babel">`, mounts to `#root`; a small `postMessage` shim forwards `console.*` + window.onerror to the host, shown in a collapsible "console" strip under the viewer.
  - **js, mjs** → sandboxed iframe running the script; console piped out as above.
  - **md, markdown** → `markdown-it` → `DOMPurify.sanitize` → render inline in the editorial style (upgrade of the current minimal md renderer; keep code blocks highlighted via Prism).
  - **py, ts, go, rs, sh, json, yaml, other code** → Prism read-only highlight + a Copy button + "Open in default app" (via `/api/open`). Not run.
  - **pdf** → hand off to the existing pdf-viewer plugin/PDF.js.
  - **png, jpg, gif, webp, svg-as-image** → `<img>` (for svg prefer the sandboxed iframe if it may contain script).
- **Security (non-negotiable):** iframes ALWAYS `sandbox="allow-scripts"` WITHOUT `allow-same-origin`; never inject artifact HTML into the host DOM (only via iframe srcdoc); DOMPurify for any md/HTML that must be inlined into the host; no `eval` in the host; the CSP blocks network egress from artifacts by default (script-src limited to inline + our asset origin; connect-src 'none' unless Fable later relaxes). Document these in comments.
- Reference projects to STUDY (not embed), evaluate only if MIT + fully offline + small: Open WebUI artifacts, 13point5/open-artifacts, webllm/renderify (the dev.to "Renderify" runtime engine), svcvit/dify-plugin-artifacts. Baseline = our own Babel+iframe pipeline; adopt a lib only if it's a clear, offline, permissively-licensed win — tag the choice for Fable QA.
Mac-verify: feed the viewer a sample of each type (a static HTML, a small React counter, a markdown doc, a python file) → each renders correctly; React counter is interactive; console strip shows logs; split ⇄ expand ⇄ close all work; nothing reaches the network.

---

## PHASE 3 — File/artifact cards in the transcript
- Detect artifacts to card: (a) files the assistant writes into the harness output/workspace dir during a turn, and/or (b) fenced code blocks the model emits that are artifact-worthy (html/jsx/svg/full code files). Fable decision: start with **(a) real files on disk produced this turn** (reliable) + **(b) large fenced blocks** rendered as an inline "Open as artifact" affordance; keep it best-effort, never break the chat stream.
- Card UI (reuse existing card/token primitives; `<!-- FABLE: style pass -->`): type icon + filename + type + size + actions: **Open** (→ Phase-2 viewer, split by default), **Open in app** / **Show in Folder** (→ `/api/open` with the existing path-allowlist: realpath must exist AND be under `$HOME`; `action: "open"|"reveal"`; never accept `file://` in the url field; log rejections).
- Cards render inline in the chat transcript at the point the file was produced.
Mac-verify: a turn that writes an .html and a .py file shows two cards; Open renders in the split viewer; "Show in Folder" reveals it in Finder; a path outside $HOME is rejected.

## DELIVERABLE / REPORT
Per phase: what changed (files/functions), validation + test results, ⚠️ PENDING FABLE QA judgment calls, Mac-verify steps. Do NOT commit/push. Keep the FAT build working — if you add vendor assets, ensure `build_app.sh --fat` bundles `bridge/panel/assets/vendor/` into the seed (offline installs need them) and that `fetch_vendor_assets.sh` runs at build time.

## PHASE 1.5 — Chat chrome, center-stage (Debi feedback 2026-07-31; Fable decisions)
The Chat view still feels squeezed — the oversized hero + worded topbar buttons waste the top band. Make chat center-stage like LM Studio. Chat-view-only (scope via `body.chat-mode`); other views unchanged.
1. **Collapse the hero on Chat.** The eyebrow ("II. CHAT"), the huge serif "Chat" title, the subtitle, and the model/private line collapse into a **compact single-line header** on the Chat view (e.g. a slim strip: `Chat · <model> · private`), reclaiming the tall vertical band for messages. Keep the full hero on all other views.
2. **Icon-ify the topbar controls globally.** Theme (◐), Command palette (⌘K), Refresh (↻) become compact **icon-only** buttons with native `title`/`aria-label` tooltips (hover shows the word). Less prominent, LM-Studio-like. Functionality unchanged.
3. **Reclaim the top-right space on Chat** — the chat column/messages extend up into the freed area; the compact header sits near the topbar level. Net: much more room for output.
4. Editorial tokens only; `<!-- FABLE: style pass -->` on new structure.

## PHASE 3 note (primary trigger = fenced code blocks in chat)
The main real-world trigger is the model emitting a fenced ```html / ```jsx / ```svg / large code block in a reply (e.g. the warehouse-page case). So Phase 3 MUST: detect artifact-worthy fenced blocks in assistant messages as they render and attach a compact **Open** affordance (type-labeled) that calls `openArtifact()` → the Phase-2 split viewer; markdown keeps rendering inline. Real files written to the output dir get the fuller card (Open + Open-in-app/Show-in-Folder via /api/open). Start with fenced-block detection — that's what makes a normal chat reply renderable.

## EXECUTION ORDER: Phase 1 ✅ → Phase 2 ✅ → **Phase 1.5 (chat chrome) + Phase 3 (cards/fenced-block render) together** (both chat-view UI). Then Fable QA.
