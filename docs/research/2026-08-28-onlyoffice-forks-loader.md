# ONLYOFFICE upstream + forks recon — updates, and can a fork/patch fix the blocking modal? (2026-08-28, Fable)

**Questions asked:** (1) newer CryptPad editor/x2t releases than our pins? Upstream AI-plugin
commits since our pin — chat-state fix? streaming ribbon actions? security? (2) do the top
forks of the AI-plugin repo or of sdkjs solve the blocking-modal behavior? (3) if something
does, is it adoptable under the AGPL ruling?

**Answers, one line each:**
1. **Editor/x2t: newer tags exist, but CryptPad's released installer still pins EXACTLY our
   pair — no update to take.** AI plugin: our pin **IS master HEAD**; zero commits since;
   the chat-wipe (`clearChatState` in init) is **still unfixed upstream** (present in the
   3.2.3 working copy too). Nothing security-relevant for our static bundle.
2. **The GitHub fork networks are trivial/stale — negative result** — with one giant
   *detached* exception, **Euro-Office**, which forks the whole ONLYOFFICE stack but does
   **not ship the AI plugin at all**, so it does not solve the modal either.
3. **No fork or upstream commit solves the loader.** It *is* solvable by us: the diff is
   ~20 lines (the plugin already contains the exact release-at-first-chunk pattern the
   ribbon actions fail to use), via either a runtime shim (no vendored byte touched —
   needs a doctrine ruling) or a pinned patch (breaks "UNMODIFIED", triggers AGPL
   publish duty if distributed). Details in §3.

---

## 1. Upstream updates

### 1a. cryptpad/onlyoffice-editor and cryptpad/onlyoffice-x2t-wasm

Releases newer than our pins exist in both repos (checked live 2026-08-28):

| repo | our pin | newest release | date |
|---|---|---|---|
| [cryptpad/onlyoffice-editor](https://github.com/cryptpad/onlyoffice-editor/releases) | `v9.2.0.119+5` (2026-03-12) | `v9.3.2+2` (Latest) | 2026-08-25 |
| | | `v9.3.2+1` / `v9.3.2+0` | 2026-08-18 / 08-13 |
| | | `v9.3.0.140+2` / `+0` | 2026-05-15 / 04-23 |
| [cryptpad/onlyoffice-x2t-wasm](https://github.com/cryptpad/onlyoffice-x2t-wasm/releases) | `v7.3+1` | `v9.3.0+0` (Latest, "x2t 9.3.0.140") | 2026-04-24 |

**But the pin rule is CryptPad's *released* installer, not the newest tag — and CryptPad's
live `install-onlyoffice.sh` on `main` still pins exactly our pair,** verified 2026-08-28
against `https://raw.githubusercontent.com/cryptpad/cryptpad/main/install-onlyoffice.sh`:

```
install_version v9 v9.2.0.119+5  1f1184fb04cf72a7eb2a49a9740074b5419486c79e1fd713e1f8c09b8594a826050ae941fed6ac6a96807ba73cc751d7c807bd7e6b73de9e4f8e74cd5ed04cfa
install_x2t v7.3+1 ab0c05b0e4c81071acea83f0c6a8e75f5870c360ec4abc4af09105dd9b52264af9711ec0b7020e87095193ac9b6e20305e446f2321a541f743626a598e5318c1
```

Both sha512s are byte-identical to the ones in our `scripts/install_onlyoffice.sh`.
**Verdict: no editor/x2t update available under our own pin rule. Nothing to do.**

**Strategic note — the 9.3.x line is a different animal than the runbook thought.** The
`v9.3.2+x` releases are not just "a newer ONLYOFFICE": the release notes reference
**Euro-Office** ("Fix link to Euro-Office"), the Nextcloud/IONOS-led FOSS fork of
ONLYOFFICE launched **March 2026** after ONLYOFFICE suspended the Nextcloud partnership
(see [CryptPad forum: "Moving OnlyOffice to Euro-Office"](https://forum.cryptpad.org/d/2572-moving-onlyoffice-to-euro-office),
[Slashdot](https://news.slashdot.org/story/26/04/01/1516246/onlyoffice-suspends-nextcloud-partnership-for-forking-its-project-without-approval),
[TechRadar](https://www.techradar.com/pro/watch-out-microsoft-365-european-giants-launch-euro-office-a-true-sovereign-office-suite)).
CryptPad is building its next editor line **from Euro-Office sources**. When CryptPad
releases the 9.3.x pair, our next bump is effectively a switch of editor upstream from
ONLYOFFICE to Euro-Office (still AGPL-3.0), plus the already-flagged x2t re-measurement
(PDF format codes + `m_bIsNoBase64`) — AND a re-check of whether the ONLYOFFICE AI plugin
still loads in a Euro-Office-based build (Euro-Office does not ship it; the pluginsData
surface may or may not survive their changes). This confirms the installer's "deliberately
NOT taken" stance and raises its cost: the 9.3 bump should be scoped as its own slice, not
a pin edit.

### 1b. The AI plugin (ONLYOFFICE/onlyoffice.github.io)

**Our pinned commit `799b28724a69d29bcb0a31bffc00c9b173867b54` IS the current master HEAD**
(merge of PR #653 `feature/antidote`, 2026-08-26; checked 2026-08-28). **Zero commits since
the pin**, on the whole repo and a fortiori on `sdkjs-plugins/content/ai`. The newest commit
touching the AI plugin at all is `905ea65` ("Update for new server settings", 2026-05-19) —
already inside our pin.

Checked specifically against master (raw files fetched 2026-08-28):

- **Chat wipe: NOT fixed upstream.** `sdkjs-plugins/content/ai/scripts/code.js` on master
  (the 3.2.3 working copy) still contains `clearChatState()` removing
  `onlyoffice_ai_chat_state` and still calls it from `window.Asc.plugin.init`. Our
  outside-the-plugin fix in `bridge/panel/oo.html` (per-file `mot.ooai.chat.<file>` keys,
  hold-until-Chatbot-opens) remains necessary and remains the only fix in existence.
- **Ribbon blocking: NOT changed upstream.** Master's
  `sdkjs-plugins/content/ai/scripts/engine/register.js` is behaviorally identical to our
  vendored copy: the Chatbot loop calls `StartAction ["Block", …]`, passes
  `chatRequestAgent(data, /*block*/ false, streamFunc)` and fires `EndAction` on the first
  chunk (`checkEndAction`, register.js:189-206 in our vendored bytes); the ten ribbon call
  sites (`register.js` 455/483/501/519/544/563/583/603/635/901) still call
  `chatRequest(prompt)` with no block flag and no streamFunc — and
  `AI.Request.prototype.chatRequest` (engine.js:512) defaults `block !== false` → the
  editor modal holds for the whole generation. No knob was added.
- **No new public dev channel to watch:** the `feature/AI` PRs come from the
  `ONLYOFFICE-PLUGINS` org, which has **no public repositories** — in-flight plugin work is
  invisible until it merges to `onlyoffice.github.io` master.
- **Security:** nothing relevant to us since the pin (there are no commits since the pin).
  For the editor bundle generally: the known ONLYOFFICE CVE trail (macro-XSS chain
  CVE-2021-43446 → CVE-2023-50883 → fixed properly in Docs 8.1.0; SEC Consult's reflected
  XSS in `editor-wopi.ejs`) targets **DocumentServer server-side endpoints and pre-8.1
  editors** — our bundle is the static 9.2 editor with no DocumentServer, no wopi endpoint,
  served same-origin behind COOP/COEP. No action.

**Verdict: no plugin update available (we ARE HEAD), no upstream fix for either pain point.**

## 2. Forks — negative result, with one detached exception

Method: GitHub fork lists sorted by stars + `compare` API `ahead_by`/`behind_by` for every
fork with any recent push or any stars (unauthenticated API + web compare pages, 2026-08-28).

### 2a. ONLYOFFICE/sdkjs fork network (296 forks) — trivial

Top of the network by stars/recency, with commits ahead of upstream master:

| fork | stars | pushed | ahead / behind |
|---|---|---|---|
| [fernfei/sdkjs](https://github.com/fernfei/sdkjs) | 2 | 2025-02-25 | **0** / 5233 |
| SuperJeffrey/sdkjs | 1 | 2026-04-23 | **0** (identical) |
| liyunfei2006/sdkjs | 1 | 2025-06-04 | not ahead (stale) |
| thirdthoughts/sdkjs | 0 | 2026-08-16 | **0** / 0 |
| MarDream/sdkjs, tzspia/sdkjs, cgb-online-office/… | 0 | 2025-2026 | **0** ahead |

fernfei's fork — the OnlyofficePersonal author, already banned from shipping by AGPL ruling
#4 — carries **nothing on master**; his patches live in his separate patched-bundle repo,
which we cannot use anyway. **No sdkjs fork in the network is meaningfully ahead, and none
touches `StartAction`/long-action behavior.** (The modal is invoked *by the plugin*; sdkjs
just obeys `StartAction` — a sdkjs fork was always the wrong layer for this fix.)

### 2b. ONLYOFFICE/onlyoffice.github.io fork network (485 forks) — trivial

| fork | stars | pushed | ahead / behind | what the ahead commits are |
|---|---|---|---|---|
| [Rayen21/onlyoffice.github.io--float-view-pic](https://github.com/Rayen21/onlyoffice.github.io--float-view-pic) | 0 | 2026-07-29 | **6** / 584 | a new picture-float-view plugin; AI untouched |
| Nsenz/onlyoffice.github.io | 0 | 2026-08-26 | **1** / 215 | "chore: pr" |
| Chenaters/onlyoffice.github.io | 0 | 2026-08-27 | **0** (identical) | — |
| Princee215 (1★), dev-ittechca-com (1★), L-w-p-999 (1★) | 1 | 2025-2026 | 0 / stale (dev-ittechca-com compare page would not render; Dec-2025 push, pre-dates our pin) | — |

**No fork of the plugin repo modifies the AI plugin at all**, let alone its blocking/
streaming behavior. Web searches for third-party forks addressing the modal
("streaming summarization", "blocking modal") surface only upstream docs, the
[custom-features blog](https://www.onlyoffice.com/blog/2025/12/how-to-add-custom-features-to-the-onlyoffice-ai-plugin)
(which is a fork-and-rebuild workflow, below), and toy repos (e.g. Serg-Kv/ONLYOFFICE-AI-plugin,
a from-scratch sample).

### 2c. The exception that proves the rule: Euro-Office (detached, very active, no AI plugin)

[github.com/Euro-Office](https://github.com/Euro-Office) (primary development on Codeberg)
is the Nextcloud/IONOS-led AGPL-3.0 fork of the entire ONLYOFFICE stack:
[sdkjs](https://github.com/Euro-Office/sdkjs) (11★), web-apps (81★), core (118★),
DocumentServer (1.7k★), DesktopEditors (453★) — **all pushed 2026-08-26…28**, i.e. the only
genuinely active "fork" of sdkjs in existence. It is *detached* (not in GitHub's fork
network), which is why the fork listings miss it. **It does not carry the AI plugin**
(their only AI repo is `plugin-aiautofill`, 2★, a different thing) — one of the fork's
stated motivations is distance from ONLYOFFICE's Russian ownership, and the AI plugin went
with it. **So Euro-Office does not solve the modal, and adopting its sdkjs would cost us
CryptPad's build/provenance chain for nothing.** Its relevance is §1a: it is what our
*next editor bump* will be made of, via CryptPad's 9.3.x releases.

## 3. Is the loader solvable anyway? Yes — by us, and the diff is tiny

Nobody upstream or in any fork has done it, but the plugin **already contains the exact
pattern needed**, fully working, in the Chatbot path:

- `AI.Request.prototype._chatRequest` (vendored `engine.js:521`, line 577:
  `let isStreaming = (undefined !== streamFunc)`) — **the shared request path already
  streams for any provider** whenever a `streamFunc` is passed; our local provider streams
  fine through it today (that is how the Chatbot answers).
- The release-at-first-chunk dance is 12 lines in `register.js:186-212`: own
  `StartAction ["Block"]` → `chatRequest*(data, false, chunk => { on first chunk:
  EndAction })`.
- The ten ribbon call sites just… don't do that: `let result = await
  requestEngine.chatRequest(prompt);` (register.js:455 etc.).

Three options, in doctrine order:

**(a) Accept, keep the honest Help→About lines (status quo).** The modal length is TTFT +
generation; with prompt caching the repeat asks are seconds. Zero risk, zero cost. This is
what shipped in v1.5.28.

**(b) Runtime shim from OUR glue page — no vendored byte changed.** The plugin iframe is
same-origin (`/ooplug/*`), and `bridge/panel/oo.html` already reaches its localStorage.
After plugin load, wrap `AI.Request.prototype.chatRequest` inside the plugin frame: call
through with `block=false` plus a first-chunk-EndAction streamFunc, bracketed by our own
StartAction/EndAction (mirroring register.js:186-212). ~25 lines of our code, version-fenced
on plugin 3.2.2 like the chat-state fix. **Caveat that needs a ruling:** the standing
posture is "driven only through published surfaces" (SOURCES.txt wording); a prototype wrap
is our code *reaching into* their runtime, not a published surface — legally fine under
AGPL (nothing distributed is modified; runtime combination is the AGPL's normal case), but
it loosens the project's own stricter line. Also to verify in-slice: that `_chatRequest`
returns the full accumulated text when a streamFunc is passed (the Chatbot's
`fullResponse` says yes for `chatRequestAgent`; assert it for `chatRequest`).

**(c) Pinned patch in `install_oo_ai_plugin.sh` — possible, small, but expensive in
principle.** A recorded, sha-pinned patch to `register.js` adding the streamFunc pattern to
the ten call sites (~20-40 line diff; upstream's own
[custom-features workflow](https://www.onlyoffice.com/blog/2025/12/how-to-add-custom-features-to-the-onlyoffice-ai-plugin)
confirms fork-and-rebuild is the sanctioned route). License-compatible (AGPL-3.0 both
sides), but it **breaks AGPL-ruling condition #1 ("NOT ONE BYTE IS PATCHED")**, converts
the bundle from "unmodified upstream" to "our derivative" (publish duty if ever
distributed), and makes every future plugin bump a rebase instead of a hash edit. Not
worth it while (b) exists.

**Recommendation:** update available **NO** (we are at CryptPad's released editor pins and
at the plugin repo's HEAD; re-check after CryptPad releases a 9.3.x pair, which is also the
Euro-Office switch and an x2t re-measurement). Loader solvable via fork **NO** / via patch
**YES** — prefer **(b)** the same-origin runtime shim if Debi wants the ribbon modal to
release at first token; it needs one explicit ruling that a prototype wrap from our glue
page is an acceptable extension of the "published surfaces" line (precedent: the chat-state
fix already drives the plugin's localStorage keys from outside). Otherwise **(a)** stands.

---
*Method/provenance: CryptPad release pages + raw `install-onlyoffice.sh` (main), GitHub
API fork listings + compare endpoints (unauthenticated), raw master files of
`onlyoffice.github.io`, our vendored bytes under `data/onlyoffice-plugins/ai/` (register.js,
engine.js, code.js), web search for Euro-Office coverage. All checks 2026-08-28.*
