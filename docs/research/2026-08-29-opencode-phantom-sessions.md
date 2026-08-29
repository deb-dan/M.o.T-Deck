# OpenCode phantom "New session" tabs — diagnosis (2026-08-29)

**Bug (Debi, intermittent):** opening the app — or sometimes just clicking the OpenCode
tab — shows 1–2 additional empty "New session" entries she never created; her screenshot
shows FIVE. Sometimes none appear.

**Verdict: root cause found, with direct on-disk and live-API evidence. It is a
client-side draft-tab accumulation caused by the interaction of our bridge landing
route (`GET /opencode` → 307 → `/:dir/session`) with OpenCode 1.18.23's new-layout
SPA, which mints and PERSISTS a fresh draft tab on every boot of that route. Nothing
is being created server-side. All investigation was read-only.**

---

## 1. The decisive evidence

### 1a. Zero sessions exist server-side

* OpenCode's sqlite (`~/Library/Application Support/Harness/data/opencode/xdg/data/opencode/opencode.db`,
  inspected on a **copy** in the session scratchpad): `select count(*) from session` → **0**.
  `message`, `session_input`, `workspace`: all **0** rows. WAL was empty (0 bytes).
* Live API (GET only): `GET http://127.0.0.1:4096/session` → `[]`.
  `GET /global/health` → `{"healthy":true,"version":"1.18.23"}`.
* OpenCode's own server log (`data/opencode/xdg/data/opencode/log/opencode.log`, 487 lines
  since 2026-08-21) contains **no session-creation line at all** — only bursts of
  `global event connected` + `booting location services` (= an SPA instance booting and
  attaching its SSE stream). 52 such bursts since 08-21, i.e. ~52 SPA boots, 0 sessions.

So hypothesis "a (re)load eagerly POSTs a new session" is **false as stated** — nothing
touches the server. The phantoms live entirely in the webview.

### 1b. The phantoms are persisted client-side draft tabs

WKWebView localStorage for the 127.0.0.1:4096 origin
(`~/Library/WebKit/local.harness.app/WebsiteData/Default/pnzjpC5Z…/LocalStorage/localstorage.sqlite3`,
again read from a copy) holds:

```
opencode.window.browser.dat:tabs =
  [ {"type":"draft","server":"http://127.0.0.1:4096",
     "draftID":"d15db83e-…","directory":"…/data/opencode-workspace"},
    … four more, identical except draftID … ]        ← exactly FIVE = the screenshot
opencode.window.browser.dat:tabs.recent = {"key":"draft:e518f303-…"}
```

Five `type:"draft"` entries, unique `draftID`s, all for our workspace, zero
`type:"session"` entries. The "session strip" in the screenshot is this persisted
tab strip.

### 1c. The minting code, read from the served bundle at the pin

From `GET /assets/index-DonkoK44.js` (the SPA the running 1.18.23 binary actually
serves; saved to scratchpad and grepped — the deep-link route component, `wtt` in the
minified bundle):

```js
te(() => { e.general.newLayoutDesigns() &&
  (t.id || n.draftId || !s.ready() || !r().directory ||
   s.newDraft({server: i.key, directory: r().directory}, n.prompt)) })
```

i.e. **on every mount of `/:dir/session` with no session id and no `draftId` query
param, it calls `newDraft(...)`** — and `newDraft` (a) mints a fresh UUID, (b)
**pushes a new draft entry into the persisted `tabs` store**, (c) navigates to
`/new-session?draftId=<uuid>`. There is no reuse of an existing empty draft for the
same directory. The gate `general.newLayoutDesigns()` is **true** in Debi's persisted
`settings.v3` (verified in the same localStorage).

The route parser (`FSe` in the bundle) confirms `/:dir/session` without a session id is
`{type:"dir-new-sesssion"}` (upstream's own typo) — the exact URL our bridge's
`/opencode` 307 lands on (`bridge/routers/models.py::opencode_landing_url`, landed
2026-08-21 in commit `c5a4380`, the same day the drafts start).

## 2. Why "1 or 2, sometimes none" — the shell's load paths (app/main.swift)

The shell **never reloads a tab on switch** (lazy-load once via `ensureLoaded`,
`loadedTabs` set; only Hermes has staleness/config-generation reloads). So:

* **Switch to an already-loaded OpenCode tab → 0 new drafts.** ("Sometimes not.")
* **Every app relaunch → +1**: webviews don't survive the process, so the first click
  on the tab boots the SPA at the landing URL again.
* **Ghost (split view / tab drag) → +1 more**: `ghostFor()` creates a second WKWebView
  and loads `urlForTab(idx)` — a second independent SPA boot at the landing route.
  This is the "sometimes 2".
* **Failed-load retry → +1 per recovery**: `retryIfFailed` / ⌘R on the placeholder go
  back to `urlFor(wv)` = the bridge landing URL (e.g. clicking the tab before OpenCode
  finished starting, then again after).
* Benign non-source: the crash-recovery path (`webViewWebContentProcessDidTerminate`)
  and plain ⌘R reload the webview's **current** URL, which after boot is already
  `/new-session?draftId=<uuid>` — same draftId, **no** new draft.

52 SPA boots vs 5 surviving drafts simply means Debi has been closing them.

## 3. Hypotheses scored

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Tab reload spawns a fresh UI boot which eagerly creates a session | **TRUE in mechanism, but client-side**: each boot of the landing route mints a persisted draft *tab*, not a server session | §1b, §1c, `GET /session` = `[]` |
| Our degraded-check probe creates one | **False** — the health probe is a bare TCP handshake, deliberately not even an HTTP GET (`bridge/core/health.py`, `PROBE_TIMEOUT_S["opencode"]`); start_component.sh's readiness poll GETs `/global/health` and `/` only | code read; 0 server sessions anyway |
| Multiple webviews (ghost + primary) each boot one | **True as an amplifier** — explains "2" | `ghostFor()` in app/main.swift |
| A "restore last session" setting we're not passing | **No such upstream setting.** The SPA *does* restore its tab strip (`tabs` + `tabs.recent` in localStorage) — the defect is that the entry route mints a new draft *in addition to* the restored strip | §1c |

## 4. Minimal fix proposal

**Ours, one line of intent in `bridge/routers/models.py::opencode_landing_url`:**
append a **stable** `draftId` query parameter derived deterministically from the
workspace path (e.g. `uuid5(NAMESPACE_URL, ws)`), i.e. redirect to
`/{b64}/session?draftId=<stable-uuid>`.

Why this works at the pin: the minting effect short-circuits on `n.draftId`
(`t.id || n.draftId || … || s.newDraft(…)` — §1c), so a boot with a `draftId` present
**never calls `newDraft`** and therefore never appends to the persisted strip; the
draft-scoped prompt store keys off the id (`SSe`: `"draftID" in t → draft(t.draftID,…)`),
so a stable id also means a half-typed prompt survives an app restart — a small bonus.
Every boot lands on the same single composer instead of a new one.

Caveats (must be verified live before shipping — this is a deep link into a
third-party SPA's internal shape, same class of risk the existing landing already
carries and documents):
1. Confirm on the real tab that `/:dir/session?draftId=X` renders the composer and
   that sending a message promotes the draft correctly (`promoteDraft` matches on
   `pathname === "/new-session"` for its navigation nicety — worst case the nicety is
   skipped, not broken; verify).
2. Update the contract test that pins the landing route
   (`bridge/tests/test_opencode_lane.py` pins pieces of this lane; models.py's
   comment says a contract test pins the route+encoder).
3. Keep the no-param behaviour as documented fallback: if a future pin changes the
   query handling, the worst case is today's behaviour (one draft per boot), not
   breakage.

**Upstream config: nothing to pass.** There is no setting that disables the minting;
`newLayoutDesigns` is a localStorage UI flag inside the webview, not ours to write,
and turning it off would revert Debi's whole OpenCode UI. (Upstream's real fix would
be "reuse an existing empty draft for the same directory before minting" — worth an
issue against sst/opencode, but our redirect fix is independent of it.)

**Not recommended:** shell-side mitigation (suppressing reloads) cannot eliminate the
+1-per-app-open, and injecting JS into OpenCode's webview to dedupe the strip crosses
the arm's-length line.

## 5. Can the old empty "sessions" be pruned?

**Yes, trivially and safely — they are not sessions.** Server-side there is nothing to
prune (`session` table empty, `GET /session` = `[]`, no files). The five entries are
draft tabs in the webview's own localStorage; closing each one with its ✕ in
OpenCode's tab strip removes it from the persisted store (`removeTab` splices the
array and clears the draft's prompt state). No data of any kind is lost — every draft
is an empty composer (0 messages ever sent through this lane). Do **not** hand-edit
the WebKit localStorage sqlite; the UI close is the honest path, and once the fix
lands the strip stops regrowing.

---
*Method note: read-only throughout — sqlite files copied to the session scratchpad
before opening; live checks were GETs only (`/global/health`, `/`, `/session`,
`/project`, the JS bundle). No process was signalled, no OpenCode data written.*
