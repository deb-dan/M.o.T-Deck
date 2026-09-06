> **DONE — implemented and shipped (marked 2026-08-20).**

# FABLE SPEC — Split-screen + cross-app voice drop (v1, 2026-08-14)

Author: Fable 5. Builder: Opus 5. Decision-free; deviations get ⚠️ PENDING FABLE QA tags.
Debi's asks: (1) any two app tabs side by side (e.g. Mission Control + Hermes,
Voicebox + Odysseus); (2) drag a voice file from one app into MOT Deck's voice
controls; (3) LM-Studio-style split *chat* — Phase 3, GATED, design only for now.

## Phase 1 — side-by-side tabs (app/main.swift)

Mental model: the window has ONE tab strip and one or two PANES. Each webview
exists exactly once (today's array stays); a pane *borrows* a webview.

1. Tab strip gains one extra segment-like button at its right end: `⫽` (tooltip
   "Split view"). Toggles split mode. Persist `motdeck.split.on` +
   `motdeck.split.right` in UserDefaults.
2. Split OFF: exactly today's behaviour, byte-compatible. Split ON: content =
   `NSSplitView` (vertical divider, autosaveName `motdeck-split`), LEFT pane =
   the main tab strip's selection (unchanged semantics), RIGHT pane = its own
   selection via a compact overlay strip at the TOP of the right pane (same five
   titles, smaller font; build it from the same titles array — no duplicated
   string literals).
3. A webview can only be in one pane. If the right pane selects the tab the left
   is showing, the right shows the existing "Not reachable yet"-style placeholder
   text: "Already open in the left pane." (reuse the placeholder mechanism, new
   string). If the LEFT strip later selects the tab the right holds, the right
   pane falls back to that placeholder and releases the webview to the left
   (left wins, always — one rule, no negotiation).
4. Min pane width 420. Lazy-load rule unchanged (a webview loads on first
   borrow). DropOverlay: it currently sits above the window for the panel tab
   only — it must track the panel's CURRENT pane frame (or cover the window and
   forward only over the panel pane's rect; pick the smaller diff, tag it).
5. ⌘R reloads the pane that was most recently clicked (track "focused pane" by
   last mouseDown/tab interaction; default left). Keep it simple; tag it.
6. No swiftc in the sandbox: string-aware brace/paren balance + careful review;
   Debi's ship.sh recompile is the compile check. Keep the diff minimal and
   heavily commented; do NOT restructure existing tab code beyond what borrowing
   requires.

## Phase 2 — audio-file drop = voice clip (main.swift + panel + zero new endpoints)

Today DropOverlay accepts images onto the Chat composer. Extend:
1. DropWebView/DropOverlay accept audio files (wav/mp3/flac/m4a, ≤15MB) over the
   PANEL pane. On drop: read bytes → `window.motdeckNativeAudioDrop(name, dataURL)`.
2. Panel handler: decode the dataURL → POST the RAW bytes to the EXISTING
   `/api/voice/library/save?name=<stem>&fmt=<ext>` → feed('voice', "clip <name>
   added to the voice library") → if the Models→Audio detail pane is currently
   showing a cloning model's clip picker, refresh it (the new clip appears as a
   chip; do NOT auto-pin on drop — a drop is an import, not a choice).
3. Image drops keep today's behaviour untouched; type sniffing by extension +
   UTI. A file that is neither image nor audio keeps today's behaviour (ignored).
This gives Debi: VoiceStudio history → download (now works) → drag the file from
Finder/dock straight onto MOT Deck → it's a pinnable voice. TRUE
webview-to-webview drag (no Finder hop) stays a stretch goal — record as a
watch-item, do not attempt in v1.

## Phase 3 — split CHAT (GATED — do not build)

Direction for the record: two chat columns inside #view-chat, each with its own
lane chips + session + stream state. Blocked on refactoring the chat singletons
(currentSid, streaming state, stampLiveTurn, conv/auto machinery are all
one-instance). Needs a Fable-authored state-isolation spec first. Anyone
building this ahead of that spec is wrong.

## Tests
Swift: none possible — review-only discipline. Panel: wiring greps (audio-drop
handler exists, uses library/save, no auto-pin), suite sweep stays green.
