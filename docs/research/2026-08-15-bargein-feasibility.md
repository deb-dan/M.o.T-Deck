# Barge-in feasibility — can the user interrupt the assistant by speaking?

**Spec:** FABLE-SPECS-2026-08-15 **B5** (research report, no code).
**Date:** 2026-08-15 · **Author:** research agent (Opus 5) · **Status:** ⚠️ PENDING FABLE QA
**Scope:** conversation mode (`conv`) in `bridge/panel/index.html`. No code was changed by this report.

---

## ▣ RECOMMENDATIONS

> **GREEN-LIGHT (1) — the measurement, first, before anything else.** §4 is a ~50-line
> `⌘K → AEC probe (voice dev)` in the exact shape of the shipped `audioWorkletSpike`
> (`index.html:4517`), plus a two-minute Safari cross-check that costs zero code. It
> answers the one question the whole feature turns on — *does WebKit's echo canceller
> remove our own `<audio>` TTS from the mic signal in THIS webview* — and the answer is
> **genuinely undocumented**. Every §3 option is gated on its result. Building anything
> before running it would be building on an assumption.
>
> **GREEN-LIGHT (2) — push-to-interrupt as a real, keyboard-bound feature (Option A).**
> Panel-only, ~20 lines, no mic involved, no new dependency, unit-testable without
> audio, and it cannot regress the feedback-loop invariant because it does not touch
> the gate. We already ship the *mechanism* (`■ stop` funnels through `stopSpeaking`
> → `onDone` → `convEvent('speak_ok')` → grace → listening, `index.html:4368-4381`);
> what is missing is a key binding and a visible hint. This is the honest baseline and
> it should ship regardless of what §4 says.
>
> **CONDITIONAL — acoustic barge-in (Option B), ONLY if §4 measures the residual below
> our own VAD floor.** If the probe shows our TTS arriving at the mic below
> `VAD_FLOOR` (0.006) with echo cancellation on, un-gate the segmenter for the
> `speaking` phase alone, behind a raised threshold, a longer open requirement, a
> frozen noise floor, and an **echo-text guard** (§3 Option B). If the probe shows the
> residual anywhere near `VAD_THR_MAX` (0.12), refuse — a false trigger in conv mode
> does not merely cut the reply off, it **auto-sends a message made of our own voice**,
> which is precisely the self-sustaining loop the current gate exists to abolish.
>
> **REFUSE — WASM AEC in the panel (Option D).** speexdsp/`aec-rs` are real, small and
> MIT/BSD, but an adaptive filter needs the reference stream *frame-aligned* with the
> capture stream, and we do not have that alignment: `new Audio(blobUrl)`
> (`index.html:4423`) plays outside the capture `AudioContext`, so the mic-vs-speaker
> delay is unknown and drifting. Acquiring the alignment means rebuilding TTS playback
> inside the capture graph — a bigger slice than the feature, plus a new vendored wasm
> artifact. Not worth it while a one-line constraint change might do the same job.
>
> **REFUSE for now — WebRTC loopback (Option C).** It is the documented industry
> workaround and it would make the guarantee unconditional, but it is only *necessary*
> if §4 fails, it costs a live `RTCPeerConnection` whose availability in this WKWebView
> is **unverified** (there are real reports of `RTCPeerConnection` being undefined in
> WKWebView on Mac Catalyst), and its failure mode is **silence** — worse than today.
> Hold it as the fallback that §4 may promote, not as the plan.
>
> **NOTHING ACTIONABLE at the OS level.** `WKWebViewConfiguration` exposes no echo
> knob; the host app's `AVAudioEngine` is a different audio graph from the webview's;
> the shell's only useful contribution is `isInspectable` (which would give us a
> console for measuring — see §4.4) and the mic grant it already ships
> (`app/main.swift:1621-1628`).

---

## 0. What the app does today, precisely

Conversation mode is a six-phase pure state machine with one invariant: **the mic must
never hear the assistant.**

| Anchor | Fact |
|---|---|
| `index.html:5206-5208` | `convGated(st)` returns `true` in every phase except `listening` — fail-closed by construction. |
| `index.html:5069` | `autoFrame` drops the block **before** it is buffered or measured: `if (a.mode === 'conv' && convGated(convSt)) return;` |
| `index.html:5192` | `CONV_GRACE_MS = 300` — a grace window after playback before the segmenter re-arms. |
| `index.html:5383-5387` | On re-arm the segmenter is **reset** (`vadRearm`) and the frame buffer cleared, so it can never resume mid-utterance from before the gate. |
| `index.html:4845-4849` | `vadRearm` carries the learned noise floor forward but resets the machine. |
| `index.html:5012` | Capture is `getUserMedia({ audio: true })` — **no `echoCancellation` constraint is set anywhere in the panel** (all four call sites are bare `{audio:true}`: 4530, 4601, 5012, 6804). We therefore get WebKit's *default*, which is `true`, and nobody has ever measured what that default actually removes. |
| `index.html:5047` | The capture graph is `createMediaStreamSource(stream).connect(node)` — deliberately never connected to output. |
| `index.html:4423` | TTS plays through `new Audio(url)` on a blob — an `<audio>` element, entirely outside the capture `AudioContext`. |
| `index.html:5186-5190` | The code already states barge-in is out of scope v1 and names the reason: "would require echo cancellation good enough to subtract our own output". |

The VAD thresholds that any barge-in proposal has to clear (`index.html:4745-4758`):

```
VAD_OPEN_FRAMES = 3        (~32ms of continuous above-threshold audio opens an utterance)
VAD_FLOOR       = 0.006    (threshold never goes below this)
VAD_MULT        = 3        (threshold = 3 × median noise floor …)
VAD_THR_MAX     = 0.12     (… and never above this)
VAD_MIN_MS      = 400      (shorter than this is a cough)
```

Ordinary speech at the mic sits around **RMS 0.05–0.4**. So the operative question is
numeric, not philosophical: **with EC on, what RMS does our own TTS produce at the mic?**
Below ~0.006 and barge-in is easy. Above ~0.12 and it is impossible without a different
architecture.

One structural trap that any un-gating must handle, and that is easy to miss:
`vadStep` **teaches the noise floor from every non-speech block**
(`index.html:4887-4894`). If the segmenter runs during playback, our own voice's quiet
passages get learned as "room noise", the threshold is pushed toward `VAD_THR_MAX`, and
the VAD goes **deaf for the following listening window**. The floor must be frozen
during a barge-in window, not merely thresholded differently.

---

## 1. AEC viability in WKWebView on macOS

### 1.1 The three layers, kept separate

The question "does `echoCancellation: true` cancel our own playback" has three different
answers depending on which layer you ask, and conflating them is how this gets got wrong:

1. **The spec** — what a conforming user agent must do. Normative, checkable.
2. **WebKit's implementation** — what Safari on macOS actually does. Partially documented.
3. **The WKWebView-embedded case** — our situation. Effectively undocumented.

### 1.2 What the spec guarantees: the floor is `remote-only`, not "everything"

This is the decisive normative fact and it is unambiguous. The Media Capture and Streams
spec now defines `echoCancellation` as `(boolean or EchoCancellationModeEnum)`, and the
explainer states the semantics of each value plainly:

> * `false`: echo cancellation is disabled.
> * `"all"`: The user agent **must attempt to cancel all audio played out by the system**, including audio output from `RTCPeerConnections`, screen readers and system notifications.
> * `"remote-only"`: The user agent must attempt to cancel **only** played out audio from incoming `RTCPeerConnections`.
> * `true`: The user agent decides what to cancel. It **must attempt to cancel at least played out audio from incoming `RTCPeerConnections`**, but it *may* also cancel other played out audio.
>
> — [explainer-echo-cancellation-mode.md](https://github.com/guidou/mediacapture-main/blob/master/explainer-echo-cancellation-mode.md)

**`true` therefore guarantees us nothing.** A fully conforming browser may cancel only
WebRTC peer audio, and our TTS is not WebRTC peer audio — it is an `<audio>` element
playing a blob. The explainer even says so of the current state of the world: *"All
existing implementations are compliant, provided they do not report `all` and
`remote-only` as capabilities."*

MDN mirrors this wording on
[`MediaTrackConstraints.echoCancellation`](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation).

The mode enum was proposed by Google (Olga Sharanova, Guido Urdaneta),
[shipped in Chrome 141](https://www.mail-archive.com/blink-dev@chromium.org/msg14454.html)
(Finch flag `GetUserMediaEchoCancellationModes`), and filed at WebKit as
[standards-positions #507](https://github.com/WebKit/standards-positions/issues/507)
where it currently reads **"No signal"** — i.e. **Safari has not shipped it**, and the
`getCapabilities()` probe for `"all"` will almost certainly come back empty on Debi's
Mac. We cannot *ask* for what we want; we can only measure what we get.

### 1.3 What the reference signal actually is, per engine

An echo canceller subtracts a *reference*: a copy of what is being played. Where that
copy is tapped decides everything.

**Chrome, software AEC — internal loopback of the browser's own playout.** From Google's
own post:

> Chrome's software echo canceller has not been affected by this lack of functionality, **as it uses an internal loopback to get the playout audio to cancel**.
>
> — [More native echo cancellation](https://github.com/GoogleChrome/developer.chrome.com/blob/main/site/en/blog/more-native-echo-cancellation/index.md)

**Chrome, native macOS AEC — tapped at the output *device*.** The same post records that
the first macOS implementation "lacked the ability to correctly track which output device
was being used", which was fixed in M68. A canceller that has to *track the output device*
is one whose reference is the device render mix — not a per-stream tap.

**Chromium's practical behaviour is nonetheless remote-only**, and this is one of the
best-documented facts in the area. [Chromium issue
687574](https://bugs.chromium.org/p/chromium/issues/detail?id=687574): echo cancellation
works for peer-connection audio, but *"as soon as audio is processed locally by the Web
Audio API, it will not be considered by the echo cancellation"* — reproduced and written
up independently by [Focused Labs](https://focused.io/lab/echo-cancellation-with-web-audio-api-and-chromium)
and by [Twilio](https://github.com/twilio/twilio-video.js/issues/323).

**WebKit on macOS** uses CoreAudio's `kAudioUnitSubType_VoiceProcessingIO` (VPIO) for
voice-processed capture. VPIO is an OS component sitting near the hardware; a documented
side effect is that it **forces input and output to mono** and ducks other system audio
while active. A canceller placed there cannot, in principle, distinguish "audio from a
peer connection" from "audio from an `<audio>` element" — both are in the same device
render mix. That is a *mechanism argument* that WebKit on macOS is effectively `"all"`,
and it is the strongest reason to think barge-in might just work here.

### 1.4 The contradictory evidence, read adversarially

This is where the honest answer is "nobody knows, measure it", and I want to be explicit
about why rather than pick the answer I like.

**Evidence that Safari cancels ALL browser playout** (would make barge-in easy):

- Agora's known-issues documentation states flatly: *"Firefox, Safari, and Edge consider
  all audio being played from the browser for echo cancellation, however Chrome only
  considers audio being played from the WebRTC remote peer connection."*
  ([docs-legacy.agora.io](https://docs-legacy.agora.io/en/All/web_sdk_known_issues?platform=Web),
  surfaced via search; the page itself would not render for me — **I could not read the
  primary source directly, and it is a legacy vendor doc that may be years stale**.)
- The VPIO mechanism argument in §1.3.
- Practitioner consensus that Safari's AEC is strong on Apple hardware
  ([Coval](https://www.coval.ai/blog/voice-ai-echo-cancellation/): *"Generally strong AEC,
  especially on Apple devices where hardware and software are tightly integrated"*) —
  though note this speaks to *quality*, not *scope*, and quality claims are exactly the
  kind of vendor-adjacent statement that should not be read as a scope guarantee.

**Evidence that it does not, or may not** (would make barge-in hard):

- The spec floor is `remote-only` (§1.2). Safari is compliant either way.
- The widely-circulated framing in the barge-in community is the blunt one:
  *"Browser's built-in echo cancellation only works with audio arriving through WebRTC
  connections, not locally generated audio."*
  ([nguyenvulebinh/browser-aec](https://github.com/nguyenvulebinh/browser-aec)) — a
  general claim whose Chrome half is verified and whose Safari half is not.
- WebKit's `echoCancellation` support is comparatively young: the constraint was a
  **complete no-op** until [WebKit bug 179411](https://bugs.webkit.org/show_bug.cgi?id=179411)
  landed in r252681 (Nov 2019); before that `getSupportedConstraints()` did not even list
  it. The bug is also where WebKit records that `echoCancellation:false` disables **AGC as
  well** — the two are one switch on this platform, which matters if we ever want to turn
  EC off for a raw signal.
- Real-world reports of macOS Safari perturbing the audio system while the mic is live
  ([Apple discussions 255553361](https://discussions.apple.com/thread/255553361),
  [255558235](https://discussions.apple.com/thread/255558235)) suggest voice-processing is
  being engaged system-wide — consistent with VPIO, but also a reminder that this path has
  rough edges.

**Verdict: undocumented for our case; must be measured.** I am not willing to write
"Safari cancels our TTS" into a spec on the strength of a legacy vendor doc and a
mechanism inference, and I am not willing to write it off either when the mechanism
argument is this strong and the test is this cheap.

### 1.5 The WKWebView layer adds its own unknowns

Even a confident answer about Safari would not settle our case:

- The panel runs in an **embedded `WKWebView` in an AppKit app**, not Safari. Media
  capture only works at all because the host answers
  `requestMediaCapturePermissionFor` (`app/main.swift:1621-1628`) — the recorded
  silent-no-op class this project has been bitten by three times (⊕ attach, ● talk,
  downloads). Whether the *content process's* capture unit is configured identically to
  Safari's is not something Apple documents.
- **`RTCPeerConnection` availability is unverified here.** There are direct reports of it
  being undefined in WKWebView under Mac Catalyst
  ([Apple forums 695871](https://developer.apple.com/forums/thread/695871),
  [751489](https://developer.apple.com/forums/thread/751489)). We are AppKit, not
  Catalyst, so it is probably present — but "probably" is what the §4 probe is for, and
  it is a one-line check (`typeof RTCPeerConnection`).
- The panel is served over **plain HTTP on 127.0.0.1**. That is a secure context by spec,
  and `getUserMedia` demonstrably already works, so this is not a blocker — noted only so
  nobody re-derives it.

---

## 2. The alternatives, if AEC does not cover us

### 2a. Half-duplex heuristics — re-arm the VAD during playback, but make it hard to trip

Keep the mic listening while the assistant speaks, but require far more evidence before
believing it. Three levers, all inside code we already own:

- **Raise the threshold during `speaking`.** The residual after whatever EC we have is,
  by hypothesis, quieter than a person leaning in to interrupt. A multiplier on the
  learned threshold (or a fixed floor above the measured residual from §4) turns barge-in
  into "you must speak up".
- **Lengthen the open requirement.** `VAD_OPEN_FRAMES = 3` is ~32ms; a barge-in window
  can demand ~100-150ms of *continuous* above-threshold audio. Our own TTS has pauses
  between words; a real interruption does not, for the first syllable at least.
- **Freeze the noise floor.** Mandatory, per §0 — otherwise the residual is learned as
  room noise and the *next* listening window is deaf.

**What this cannot do:** distinguish loud TTS from a person. It trades false-negatives
(you have to speak up) for false-positives (the assistant cuts itself off). Its honesty
depends entirely on the §4 number: if the residual is 0.01 and speech is 0.15, a
threshold at 0.05 is a real separation; if the residual is 0.1, there is no threshold
that works.

**Keyword spotting ("stop") is the sophisticated version and I recommend against it.** It
needs a resident wake-word model (openWakeWord, Porcupine, or a small always-on
classifier) — a *second* always-on inference and a new vendored asset, in a project that
has not yet built even a persistent STT worker (B3) and is still deciding whether to
vendor 2.2 MB of silero (B4). Wrong order.

### 2b. Subtract our own signal

**The WebRTC loopback trick — the real, documented industry workaround.** Because
browsers *do* cancel peer-connection audio, you make your local audio *look like* peer
audio: route the TTS through `AudioContext → createMediaStreamDestination() → pc1 →
pc2 → <audio>`, with both peer connections in the same page. The AEC then sees it as a
remote participant and cancels it.

```
Local Audio → Web Audio API → MediaStream → WebRTC → Browser AEC → Clean Microphone
```
— [nguyenvulebinh/browser-aec](https://github.com/nguyenvulebinh/browser-aec) (MIT, with a
[live demo](https://nguyenvulebinh.github.io/browser-aec/) and a compatibility table
listing **Safari: ✅ AEC**), and independently
[Focused Labs' write-up](https://focused.io/lab/echo-cancellation-with-web-audio-api-and-chromium),
whose step 2 is exactly this. Note the sharp edge they record: use
`audioContext.createMediaStreamDestination()`, **not** `audioContext.destination`, and
`addTrack` not the deprecated `addStream`.

This is architecturally attractive — it uses the browser's own tuned AEC, adds no
dependency, and turns "does EC cover us?" from a question into a guarantee. It is also
the option with the worst failure mode (§3 Option C).

**A software AEC in the panel (wasm).** The libraries exist and are appropriately
licensed: [`speexdsp`](https://github.com/xiph/speexdsp) (BSD) is the canonical small
AEC, [`aec-rs`](https://github.com/thewh1teagle/aec) is an MIT Rust wrapper around it
that explicitly lists **`wasm32` as a supported target**, and `@sapphi-red/web-noise-suppressor`
demonstrates the speexdsp→wasm→`AudioWorkletNode` pattern in a browser. Realistic size:
speexdsp's MDF canceller is a few tens of KB of C, so the wasm artifact would be small
next to silero's 2.2 MB — **but I did not verify a built artifact's size and will not
quote one.**

**Why it still fails for us, and this is the load-bearing objection:** an adaptive filter
needs the reference frames *time-aligned* with the capture frames, within a few
milliseconds and stably. We know the reference *content* perfectly (we fetched the wav
from `/api/voice/tts`), but we do not know its *arrival time at the mic*: playback goes
through `new Audio(blobUrl)` (`index.html:4423`), a completely separate audio path from
the capture `AudioContext`, with an unknown and device-dependent output latency that can
drift. Acquiring the alignment means playing the TTS *inside* the capture graph (decode →
`AudioBufferSourceNode` → an `AudioWorklet` that both renders and tees the reference),
i.e. rewriting playback and giving up `stopSpeaking`'s single clean funnel. That is a
larger and riskier slice than the feature it enables. Note also that server-side AEC —
the option the industry reaches for here ([Coval](https://www.coval.ai/blog/voice-ai-echo-cancellation/))
— is not available to us in any cheap form: our mic audio never streams to the bridge
continuously, it is posted per-utterance as a finished wav.

### 2c. Push-to-interrupt — the honest baseline we already ship

We already have this, in two places: `■ stop` on the reply, and the `conv` chip. Both
funnel through `stopSpeaking()` (`index.html:4368-4381`), whose `onDone` callback fires
`convEvent('speak_ok')` → `grace` → `listening`. So **stopping playback already resumes
listening immediately**; the code comment at `index.html:5188-5190` says exactly this.

What is missing is discoverability and hands-free-ness: you have to find and click a
button, which is a strange thing to demand of a hands-free mode. A keyboard binding fixes
that for ~20 lines and no acoustic risk at all. This is Option A in §3.

### 2d. OS-level options exposed to a WKWebView host

Honestly: **there are none that matter.**

- `WKWebViewConfiguration` / `WKPreferences` expose no echo-cancellation or
  voice-processing knob. The only media-capture surface the host has is the
  permission decision it already implements.
- The host *could* run its own `AVAudioEngine` with `setVoiceProcessingEnabled(true)`, but
  Apple's own guidance is that **voice processing only works when input and output are
  routed through the same engine** ([Apple forums 733733](https://developer.apple.com/forums/thread/733733),
  [66953](https://forums.developer.apple.com/thread/66953)) — and the webview's audio is
  not in the host's engine. Building a host-side capture path and injecting PCM into the
  page would mean abandoning the AudioWorklet capture that GATE 1 was run to validate.
- **VPIO forces mono I/O and ducks other system audio** while active — worth knowing
  because if §4 shows our TTS *is* being cancelled, that is also the explanation for any
  playback-quality change Debi notices while the mic is live.
- The one genuinely useful host-side line is **`webView.isInspectable = true`** (macOS
  13.3+). It is not set anywhere in `app/main.swift`, which is why there is no console in
  the app and why §4 is written as a ⌘K command rather than a paste-into-devtools block.

---

## 3. What a v1 could be, ranked by risk

### Option A — Push-to-interrupt, keyboard-bound · **RISK: LOW · RECOMMENDED NOW**

**Change surface (panel only):** one pure predicate + one listener + one label.
- New pure `bargeKey(ev, phase, activeTagName)` → boolean. Fires only when
  `phase === 'speaking' || phase === 'grace'`, the key is Space or Escape, no modifier is
  held, and the focused element is **not** the composer (`TEXTAREA`/`INPUT`) — otherwise
  we steal the space bar from typing, which would be a worse bug than the one we are
  fixing.
- One `keydown` listener that calls the existing `stopSpeaking()`. **No new state**:
  `stopSpeaking` already funnels to `onDone` → `convEvent('speak_ok')` → grace →
  listening (`index.html:4380`, `5279-5284`).
- `convLabel()` (`index.html:5314`) gains a hint on the speaking state, e.g.
  `▸ speaking · space to interrupt`. Zero new CSS — the chip already renders a dot span
  plus a text span.

**Shell involvement:** none. **New assets:** none.

**Failure mode:** a stray Space keypress cuts the reply short. Recoverable in one click
(▶ speak replays from cache — the replay cache makes a re-listen instant), and it
**cannot send a message**, because nothing enters the composer. This is the entire reason
it is the low-risk option.

**How to test without a mic:** `bargeKey` is pure — a decision table over
{phase} × {key} × {modifiers} × {focused element}, in the style of
`test_conv_mode.js` (which already exercises `convStep`/`convGated` 56 times). Plus a
wiring grep that the listener calls `stopSpeaking` and never `sendChat`.

---

### Option B — Acoustic barge-in behind a measured margin · **RISK: MEDIUM · GATED ON §4**

Only if §4 reports the TTS residual **below `VAD_FLOOR` (0.006)** with EC on, and ideally
an order of magnitude below normal speech.

**Change surface (panel only, but in the most delicate code we own):**
- `convGated(st)` (`index.html:5206`) gains a second argument or a sibling
  `convBargeOpen(st, enabled)`; it must keep failing **closed** for unknown phases —
  that property is explicitly why the predicate exists and a test already pins it.
- `autoFrame` (`index.html:5069`) stops returning early in `speaking`, and instead routes
  the block into a **separate barge segmenter state** (`a.bargeSt`), never `a.st`. Keeping
  them separate is what prevents the playback residual from being learned into the
  listening floor.
- A new pure `vadInitBarge(frameMs, thr)` producing a state with a **frozen** floor
  (`noise` pre-filled to `noiseCap` so `vadStep`'s warm-up gate is satisfied and the
  learning branch is a no-op), `open` raised from 3 to ~10 frames (~107 ms), and
  `thr = max(VAD_THR_MAX_BARGE, measuredResidual × margin)` where the constant comes out
  of §4's number rather than a builder's intuition.
- On a barge open: `stopSpeaking()` (→ grace → listening) and let the *existing* pipeline
  take the utterance. Do **not** invent a second transcription path.
- **Required companion — the echo-text guard.** Before `convSend` fires, compare the
  transcript against the text currently being spoken (we have it: `speakText(msgRaw(wrap))`,
  `index.html:4402`). If the transcript is a high-similarity subsequence of our own
  output, drop it as echo and return to listening. Pure function, no dependency, and it
  directly kills the documented failure signature — *"the user's transcribed speech
  closely matches the agent's immediately preceding output"*
  ([Coval](https://www.coval.ai/blog/voice-ai-echo-cancellation/)). This should not be
  optional.

**Shell involvement:** none. **New assets:** none.

**Failure mode — the bad one.** A false trigger does two things at once: it cuts the
assistant off mid-sentence, **and** it auto-sends a message. If the audio that triggered
it was our own voice, the transcript *is* our own words, the model answers its own
sentence, and the loop the current gate abolishes is back. The echo-text guard is the
second line of defence; the measured margin is the first. If either is missing, refuse.

**Second failure mode, less obvious:** double-talk. Even a good AEC degrades sharply when
both sides speak at once, and *"false suppression of user speech during double-talk is a
common AEC failure mode"* ([Coval](https://www.coval.ai/blog/voice-ai-echo-cancellation/)).
The user's interrupting words may be partly eaten — so the first word of a barge-in
utterance is likely to be lost. Our 300 ms pre-roll (`VAD_PREROLL_MS`) helps but is not a
fix. Expect "sorry, say that again" to be part of the UX.

**Third, worth stating:** AEC needs 3-4 seconds to converge on a fresh acoustic path, so
the *first* reply of a session is the most likely to leak. Our own `VAD_WARMUP_MS = 600`
does not cover this.

**How to test without a mic:** all of it, because all of it is pure. Feed `vadStep`
synthetic RMS sequences representing (i) silence, (ii) measured playback residual,
(iii) residual + speech, (iv) residual alone for 30 s (must **never** open), and assert
the barge state's floor never moves. The echo-text guard is a pure string function with
its own table. The only untestable part is the real acoustic residual — which is exactly
what §4 supplies as an input constant.

---

### Option C — WebRTC loopback so the AEC definitely covers us · **RISK: HIGH · HOLD**

**Change surface:** `msgSpeak` (`index.html:4399-4440`) — the single place that creates
`new Audio(url)` — plus a new loopback module (~80 lines): `AudioContext` →
`decodeAudioData` on the fetched wav → `AudioBufferSourceNode` →
`createMediaStreamDestination()` → `pc1.addTrack` → `pc2.ontrack` → a second `<audio>`
whose `srcObject` is the remote stream. Both PCs local, offer/answer exchanged in-page,
no signalling server, no network.

**Shell involvement:** none, *if* `RTCPeerConnection` exists in this WKWebView — unverified
(§1.5). **New assets:** none.

**Why it is high risk despite being the "right" answer:**
- **Failure mode is silence.** If the peer connection never reaches `connected`, the
  reply does not play at all. Today's worst case is "the assistant is heard by the mic";
  this option's worst case is "the assistant is heard by nobody". Any build must fail
  **open**, i.e. fall back to plain `<audio>` on a timeout — which means carrying two
  playback paths and testing both.
- It perturbs the one audio path that currently works, and `stopSpeaking`'s single-funnel
  discipline (`index.html:4364-4381` — one clip app-wide, object URL revoked on every
  exit, `onDone` fired last) would need re-establishing over a materially more complex
  teardown (two PCs, two tracks, a context, an element).
- It adds latency to every spoken reply, including the non-conv `▶ speak` path if the
  paths are shared.
- **It is only needed if §4 fails.** Building it first would be paying its whole cost to
  buy a guarantee we may already have for free.

**How to test without a mic:** the wiring (connection established, track received,
fallback fires on timeout, teardown revokes and closes) is testable headlessly in a
browser harness; the *cancellation* is not testable at all without the acoustic loop.

---

### Option D — WASM AEC in the panel · **RISK: HIGH, POOR RATIO · REFUSE**

Covered in §2b. Real libraries (`speexdsp` BSD, `aec-rs` MIT with wasm32), but the
blocker is alignment, not licensing or size, and fixing alignment means rewriting
playback into the capture graph. Refuse for v1; revisit only if Options A-C are all
exhausted and barge-in is still wanted.

---

### Ranked summary

| # | Option | Risk | Panel | Shell | New assets | Gated on |
|---|---|---|---|---|---|---|
| A | Push-to-interrupt (key-bound) | **Low** | ~20 lines | — | — | nothing — ship it |
| B | Acoustic barge-in, measured margin | Medium | ~80 lines, delicate | — | — | §4 residual < `VAD_FLOOR` |
| C | WebRTC loopback | High | ~120 lines + fallback | — | — | §4 fails **and** `RTCPeerConnection` exists |
| D | WASM AEC | High | rewrite of playback | — | wasm blob | — (refuse) |

---

## 4. The decisive 10-minute measurement

The question: **with echo cancellation on, at what RMS does our own TTS arrive at the
microphone?** Everything above turns on that one number, expressed in the same units as
`VAD_FLOOR` / `VAD_THR_MAX`.

The probe includes a **control leg with `echoCancellation:false`**. Without it, a low
number during playback is ambiguous — it could mean "the AEC worked" or "the speakers
were quiet". The control removes that ambiguity, and it is the reason this measurement is
decisive rather than suggestive.

### 4.1 Stage 1 — zero code, ~3 minutes: does WebKit do it at all?

The panel is served on `http://127.0.0.1:8700`, which Safari can open and which is a
secure context, so `getUserMedia` works there and Safari has a real console.

1. Make sure MOT Deck is running and a **TTS default is set** (Models → Audio).
2. In **Safari**: open `http://127.0.0.1:8700`, then Develop → Show JavaScript Console
   (enable the Develop menu in Safari → Settings → Advanced if needed).
3. **Turn the speakers up to the volume you would actually use for conversation mode,
   and do not wear headphones.** Headphones make this test pass trivially and mean nothing.
4. Paste the block in §4.3. It runs two 6-second legs and prints one line.
5. **Say nothing during the whole run.** The only sound should be the assistant's voice.

This measures **Safari/WebKit on macOS**. It does not yet prove anything about the app's
WKWebView — but if Safari itself does not cancel our playback, WKWebView almost certainly
does not either, and Option B is dead without any further work.

### 4.2 Stage 2 — the same block as a ⌘K command, in the app

Because the app's webviews are not `isInspectable`, the in-app run needs the same
affordance GATE 1 used: a palette entry. Drop `aecProbe` (below) next to
`audioWorkletSpike` (`index.html:4517`) and add one row to `commands()`
(`index.html:4691`, immediately after the existing spike row):

```js
{t:'AEC probe (voice dev)', k:'⊚', f:aecProbe},
```

Then `./scripts/ship.sh`, ⌘K → **AEC probe (voice dev)**, and read the verdict in the
**activity feed** on Mission Control (`alert()` is a recorded silent no-op in this
webview). Same rules: speakers up, no headphones, stay silent.

### 4.3 The block

Self-contained. Works pasted into Safari's console *or* dropped into the panel as a
function. It fetches a real TTS render from our own `/api/voice/tts`, so it measures the
exact signal conversation mode plays, at the exact volume.

```js
async function aecProbe(){
  // Verdict goes to the activity feed (alert() is a silent no-op in the app webview),
  // the console, and alert() as a browser-only bonus — same shape as audioWorkletSpike.
  const say = (m) => { try{feed('voice',m);}catch(_){} console.log(m);
                       try{alert(m);}catch(_){} try{showView('mc');}catch(_){} };
  const PHRASE = 'Testing one two three. This is the assistant speaking a long enough ' +
                 'sentence for the microphone to hear it clearly.';

  // rolling RMS of the mic, in the SAME units as VAD_FLOOR / VAD_THR_MAX
  async function leg(ec, play){
    const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation: ec}});
    const tr  = stream.getAudioTracks()[0];
    const set = (tr.getSettings && tr.getSettings()) || {};
    const ctx = new (window.AudioContext||window.webkitAudioContext)();
    if (ctx.state === 'suspended') await ctx.resume();
    const an = ctx.createAnalyser(); an.fftSize = 2048;
    ctx.createMediaStreamSource(stream).connect(an);      // never connect to output
    const buf = new Float32Array(an.fftSize);
    const rms = () => { an.getFloatTimeDomainData(buf);
      let s=0; for (let i=0;i<buf.length;i++) s += buf[i]*buf[i];
      return Math.sqrt(s/buf.length); };
    const sample = async (ms) => { const v=[]; const t0=performance.now();
      while (performance.now()-t0 < ms){ v.push(rms()); await new Promise(r=>setTimeout(r,50)); }
      v.sort((a,b)=>a-b); return { med:v[v.length>>1]||0, max:v[v.length-1]||0 }; };

    const quiet = await sample(2000);                      // room floor, nothing playing
    let loud = {med:0,max:0};
    if (play){
      const a = new Audio(URL.createObjectURL(play));
      a.play();
      await new Promise(r=>setTimeout(r,400));             // let it get going
      loud = await sample(4000);
      try{ a.pause(); }catch(_){}
    }
    stream.getTracks().forEach(t=>t.stop());
    try{ await ctx.close(); }catch(_){}
    return { quiet, loud, ecSetting: set.echoCancellation,
             ch: set.channelCount, rate: set.sampleRate,
             caps: (tr.getCapabilities && JSON.stringify(tr.getCapabilities().echoCancellation)) || 'n/a' };
  }

  try {
    // 0 — capability introspection, instant, no audio
    const sc = navigator.mediaDevices.getSupportedConstraints();
    const rtc = (typeof RTCPeerConnection !== 'undefined');

    // 1 — one real TTS render, the exact signal conv mode plays
    const res = await fetch('/api/voice/tts', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: PHRASE})});
    if (!res.ok) return say('AEC probe: FAIL — /api/voice/tts returned ' + res.status +
                            ' (set a default TTS model first)');
    const wav = await res.blob();

    const on  = await leg(true,  wav);      // the measurement
    const off = await leg(false, wav);      // the control

    const f = (x) => x.toFixed(4);
    const verdict =
      (on.loud.med < 0.006) ? 'PASS — residual below VAD_FLOOR: barge-in is viable' :
      (on.loud.med < 0.03 && on.loud.med < off.loud.med/4)
                            ? 'PARTIAL — AEC is working but the residual is above the floor: ' +
                              'barge-in needs a raised threshold (Option B with a margin)' :
      (on.loud.med >= off.loud.med/2)
                            ? 'FAIL — EC on ≈ EC off: our <audio> playback is NOT in the ' +
                              'AEC reference. Option C (WebRTC loopback) or half-duplex.' :
                              'INCONCLUSIVE — see the numbers';

    say('AEC probe: ' + verdict +
        ' | EC ON  quiet=' + f(on.quiet.med)  + ' playing=' + f(on.loud.med)  + ' (max ' + f(on.loud.max) + ')' +
        ' | EC OFF quiet=' + f(off.quiet.med) + ' playing=' + f(off.loud.med) + ' (max ' + f(off.loud.max) + ')' +
        ' | VAD_FLOOR=0.006 VAD_THR_MAX=0.12' +
        ' | settings ec=' + on.ecSetting + ' ch=' + on.ch + ' rate=' + on.rate +
        ' | capabilities.echoCancellation=' + on.caps +
        ' | supportedConstraints.echoCancellation=' + sc.echoCancellation +
        ' | RTCPeerConnection=' + rtc);
  } catch (e){ say('AEC probe: FAIL — ' + ((e && e.message) || String(e))); }
}
```

### 4.4 What each result means — decide from this table, not from intuition

| Result | Reading | Decision |
|---|---|---|
| `EC ON playing` **< 0.006** and `EC OFF playing` clearly higher | WebKit's AEC removes our own `<audio>` playback below our own VAD floor. | **Build Option B.** Set the barge threshold from the measured residual, keep the echo-text guard, keep the frozen floor. |
| `EC ON playing` 0.006–0.03, and ≥4× lower than `EC OFF` | AEC is working but leaking. | **Option B with a real margin** — threshold at ~3-5× the residual, `open` at ~10 frames. Expect the user to have to speak up. Re-measure in Debi's actual room, not a quiet one. |
| `EC ON playing` ≈ `EC OFF playing` (within 2×) | Our playback is **not** in the AEC reference — WebKit is behaving `remote-only` for us. | **Refuse Option B.** Either Option C (if `RTCPeerConnection=true`) or stay half-duplex with Option A. |
| `EC OFF playing` itself ≈ `quiet` | The mic never heard the speaker — volume too low, or headphones, or output on another device. | **Invalid run.** Turn it up, remove headphones, check the output device, re-run. This leg exists precisely to catch a false PASS. |
| `capabilities.echoCancellation` contains `"all"` | Safari shipped the mode enum (currently "No signal" at WebKit). | Then we can *ask* for `{echoCancellation:{exact:"all"}}` and Option B becomes a supported guarantee rather than an observation. |
| `RTCPeerConnection=false` | Option C is dead in this webview. | Option A or B only. |
| `ch=1` and a lowered `rate` with EC on | Voice-processing (VPIO) is engaged — consistent with a device-level canceller. | Corroborates a PASS; also explains any playback quality change while the mic is live. |

**Run it twice** — once with EC on/off as written, and once again after ~30 seconds of
conversation-mode use, because AEC adaptive filters take 3-4 s to converge and the *first*
reply of a session is the worst case. If the two runs disagree, the honest number is the
**worse** one.

---

## 5. Uncertainty flags — what I could not settle

1. **Whether WebKit's macOS AEC includes non-WebRTC playout is genuinely unresolved.**
   The mechanism (VPIO at the device level) argues yes; the spec floor and the general
   barge-in-community framing argue no; the one source that states "Safari cancels all
   browser audio" is a **legacy vendor doc I could not open directly**. This is the whole
   reason §4 exists and the reason no option above is recommended unconditionally.
2. **I could not read WebKit's own source.** `CoreAudioSharedUnit.mm` / `CoreAudioCaptureSource.mm`
   would settle the reference-signal question definitively; every fetch route available to
   me returned an empty body, and the sandbox has no outbound network for `curl`. A
   session with working access should read those two files before Option B is specified —
   it may make the measurement a confirmation rather than a discovery.
3. **`RTCPeerConnection` in this WKWebView is unverified** (§1.5), so Option C's cost is
   not fully known. The probe answers it in one line.
4. **Nothing here is run-verified.** No mic was available; no numbers in this report were
   measured; the VAD constants and the code anchors are read out of the source, and the
   acoustic claims are all conditional on §4.
5. **The wasm AEC artifact size is unverified.** `aec-rs` declares wasm32 support and
   speexdsp is small, but I did not build one and refuse to quote a figure.
6. **Double-talk degradation is stated from practitioner literature, not measured here.**
   Even a PASS in §4 does not mean the user's first interrupting word survives — the probe
   measures the residual with the user *silent*, which is the easy case.
7. **Room-dependence.** A PASS measured in a quiet room may become a PARTIAL near a hard
   wall or at higher volume. If Option B ships, its threshold should be derived from the
   measurement *and* carry a margin, and the failure should be a missed interruption
   (recoverable) rather than a false one (sends a message).

---

## Sources

- [Echo Cancellation Mode explainer — Sharanova & Urdaneta (W3C/Google)](https://github.com/guidou/mediacapture-main/blob/master/explainer-echo-cancellation-mode.md)
- [MDN — `MediaTrackConstraints.echoCancellation`](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints/echoCancellation)
- [W3C Media Capture and Streams](https://www.w3.org/TR/mediacapture-streams/)
- [w3c/mediacapture-main #577 — echo cancellation scope](https://github.com/w3c/mediacapture-main/issues/577)
- [WebKit standards-positions #507 — Echo Cancellation Mode (No signal)](https://github.com/WebKit/standards-positions/issues/507)
- [blink-dev — Intent to Ship: echoCancellationMode (Chrome 141)](https://www.mail-archive.com/blink-dev@chromium.org/msg14454.html)
- [Chrome for Developers — macOS native echo cancellation](https://github.com/GoogleChrome/developer.chrome.com/blob/main/site/en/blog/macos-native-echo-cancellation/index.md)
- [Chrome for Developers — More native echo cancellation](https://github.com/GoogleChrome/developer.chrome.com/blob/main/site/en/blog/more-native-echo-cancellation/index.md)
- [WebKit bug 179411 — getUserMedia echoCancellation constraint has no affect](https://bugs.webkit.org/show_bug.cgi?id=179411)
- [Chromium issue 687574 — Echo cancellation not working when using Web Audio](https://bugs.chromium.org/p/chromium/issues/detail?id=687574)
- [twilio-video.js #323 — Chromium 687574](https://github.com/twilio/twilio-video.js/issues/323)
- [Focused Labs — Echo Cancellation with Web Audio API and Chromium](https://focused.io/lab/echo-cancellation-with-web-audio-api-and-chromium)
- [nguyenvulebinh/browser-aec — WebRTC loopback AEC demo (MIT)](https://github.com/nguyenvulebinh/browser-aec) · [live demo](https://nguyenvulebinh.github.io/browser-aec/)
- [Coval — Voice AI Echo Cancellation: Causes, Fixes, and Best Practices](https://www.coval.ai/blog/voice-ai-echo-cancellation/)
- [Agora — Web SDK known issues (legacy)](https://docs-legacy.agora.io/en/All/web_sdk_known_issues?platform=Web)
- [Apple — `kAudioUnitSubType_VoiceProcessingIO`](https://developer.apple.com/documentation/audiotoolbox/kaudiounitsubtype_voiceprocessingio)
- [Apple Developer Forums 733733 — macOS echo cancellation (AUVoiceProcessing)](https://developer.apple.com/forums/thread/733733)
- [Apple Developer Forums 66953 — Using VoiceProcessingIO for echo cancellation on macOS](https://forums.developer.apple.com/thread/66953)
- [Apple Developer Forums 695871 — RTCPeerConnection is undefined on WKWebView (Catalyst)](https://developer.apple.com/forums/thread/695871)
- [Apple Developer Forums 751489 — RTC Peer connection error in WKWebView (Mac Catalyst)](https://developer.apple.com/forums/thread/751489)
- [xiph/speexdsp (BSD)](https://github.com/xiph/speexdsp) · [`speex_echo.h`](https://github.com/xiph/speexdsp/blob/master/include/speex/speex_echo.h)
- [thewh1teagle/aec — `aec-rs`, MIT, wasm32 supported](https://github.com/thewh1teagle/aec)
- [sapphi-red/web-noise-suppressor — speexdsp→wasm→AudioWorklet precedent](https://github.com/sapphi-red/web-noise-suppressor)
