# FABLE SPEC — MUSIC "STUDIO VIEW" (the per-page deep theme) + v1.2 fixes
2026-08-20 · Fable 5 · decision-free. Reference = Debi's VoiceStudio Launchpad
screenshot: near-black canvas, big serif hero with ONE gradient-tinted phrase, large
feature CARDS (tinted icon tile, small-caps title, two-line description, a little
waveform motif in the card's accent hue), numbered shortcuts, a recent-files strip.
Clean like Unsloth/LM Studio. Debi: "a new button just for the Music page that totally
revamps everything when clicked" — classic stays the default.

## A. The toggle
A `✦ Studio view` chip at the top of #view-music (and `▤ Classic` to come back).
`#view-music` gains `data-mview="studio"`; persisted `localStorage['motdeck-music-view']`
('classic' default). ALL new CSS lives in ONE contiguous sanctioned block, every
selector prefixed `#view-music[data-mview="studio"]` (the studio-chrome discipline:
block appears once, depth 0, counted in the test). Tokens namespaced `--mv-*`.
It must COMPOSE with light/dark and with the global ▣ studio chrome.

## B. Studio view layout (top → bottom)
1. **Hero**: small-caps kicker `♫ MUSIC STUDIO`; serif display ~34px:
   `Make music that moves you.` with "moves you" in a gradient (gold → rose:
   #d9b36c → #c96c8e; light theme: #9c7327 → #a04e6b); one sub-line:
   `Two local engines · <N> tracks · describe it, get a song.` Engine state as two
   small pills (installed/missing per engine).
2. **Template gallery**: grid of cards (auto-fill, min 240px). Each card: a 34px
   rounded icon tile tinted with the template's accent at 18% alpha + its glyph
   (♫/⚡/☾/🎬-class text glyphs — no image assets), small-caps name, tag pill
   (VOCAL/INSTRUMENTAL · BPM), two-line prompt excerpt, and a 5-bar waveform motif
   in the accent colour (CSS: five inline-block bars of varying height). Accents,
   fixed per built-in: neo-soul #c96c8e · rock #e06565 · lo-fi #8b93f8 · cinematic
   #46c99a · EDM #d9b36c · folk #e0a458; user templates cycle the same six.
   Hover: 1px lift + border brightens. Click = prefill + SMOOTH-SCROLL to Create
   (this scroll-on-Use applies in classic view too). `use & generate` stays a small
   secondary on the card. User-template ✕ keeps the two-step arm.
3. **Create card**: one bordered card. Engine choice = two mini-cards (not chips):
   engine name, one-line trade-off (`highest quality · ~2 min/min of song` /
   `fast · ~25s per song`), RAM need; selected = accent border + tick. Fields inside
   in a 2-col grid where sensible (Length | Steps | Seed on one row). BIG primary
   Generate (full-width on narrow, right-aligned otherwise, 34px tall, gold fill).
   Progress replaces the button row while rendering (bar + phase + elapsed/ETA + the
   new Cancel).
4. **Library**: strip header `LIBRARY · saving to: <path> · change`. Rows are the
   NEW COMPACT rows (see C3) — same DOM in both views, studio view only restyles.

## C. v1.2 fixes (apply to BOTH views — these are functional)
1. **Auto-growing textareas**: prompt + lyrics reuse the chat composer's growInput
   pattern (extract/share, don't duplicate): start ~3 rows, grow with content to a
   max of ~2× today's height, then scroll internally.
2. **Layout order (classic)**: Templates become a COLLAPSED disclosure
   (`▸ Templates · 6`) once ≥1 track exists (open by default only on a fresh
   install), so Create sits near the top and Generate is visible without scrolling.
3. **Compact library rows (3 lines)**: line 1 = name + engine/fmt pills + actions
   (convert chips, Reveal, ✕); line 2 = `date · Ns · rendered in Ns · seed N ·
   steps N · size` (steps now recorded AND displayed — backfill: sidecars already
   store steps since v1; if absent show nothing); line 3 = player (lazy as today).
   The prompt/lyrics move behind a faint `prompt` chip → expands an excerpt panel
   with the full prompt + lyrics and a `re-use` button that prefills the whole form
   (prompt, lyrics, seconds, steps, seed, engine) — the replication affordance.
4. **Seed help**: tooltip + sub-line: "Any whole number from 0 to 4294967295. The
   same seed + same settings + same engine = the same song again. Leave empty to
   roll a new one (it's recorded with the track)." Verify the upper bound against
   generate.py's parser; if it's plain int, keep the stated range as OUR validation.
5. **CANCEL — build it for real.** Renders start with `start_new_session=True`;
   `POST /api/music/cancel {id}` sends SIGTERM to the process GROUP, escalates to
   SIGKILL after 5s, marks the job `cancelled`, deletes partial output files, logs
   `[music] render cancelled by the user`. Panel: a `Cancel` chip beside the bar
   with a two-step arm (`sure?`). Remove the "cannot be stopped" copy everywhere.
   ⚠️ tag any platform caveat honestly, but killing a process group is the correct
   mechanism — the earlier fear was over-cautious.
6. **Progress honesty** (Debi: the bar shoots to ~half and sticks; phase text stuck
   on "Loading … decoder"; ETA said 1m32s left at 12m elapsed on a 220s song):
   - Parse PHASE-AWARE: a tqdm bar whose total ≈ the requested step count is the
     RENDER phase; loader bars (file counts, shard loads) are SETUP. Never take a
     global MAX across phases.
   - Overall progress = setup 0→0.15 (indeterminate-ish: advance with elapsed
     against a fixed 60s setup allowance, capped), render 0.15→1.0 by step fraction.
   - ETA: while setup, history/calibration estimate for the FULL job; once render
     steps are real, `eta = elapsed_render * (1-p)/p` re-blended each poll. Cap the
     displayed bar at 0.95 until done (kept).
   - Fix the calibration for superlinearity: with two history points fit
     wall = a·seconds^b (log-log through the points) instead of proportional.
7. **Global ▣ studio chrome must reach this page**: audit why music controls don't
   restyle (likely inline styles or a non-button element); fix by using the standard
   control classes, NOT by widening the studio block. Verify via the existing
   resolver test — add the music buttons to its representative elements.
8. **Policies sidebar stub**: remove the dead `Policies` nav entry (its alert is a
   silent no-op in WKWebView). Record in the roadmap that a Policies view (path-guard
   policy display) is future work.
9. **Activity-feed lines**: music feed entries currently render `undefined` as the
   tag/detail column (Debi screenshot). Find the feed() call shape mismatch and fix.

## D. Tests
Extend test_music_lane.py + the panel js test: view toggle persistence, the CSS
block discipline (once, prefixed, counted), phase-aware progress table (loader bars
never move the render fraction; step bars matching the requested count do; the
power-law fit through (60,115.5) and (145,675.6) predicts 220s in a sane band and
NEVER less than elapsed), cancel state machine (SIGTERM path, partial-file cleanup,
cancelled jobs excluded from ETA history), compact-row rendering + reuse prefill
totality, seed-range validation, growInput sharing (one implementation), Policies
nav absent, feed lines carry real text. All suites + contract green; CSS delta =
exactly the one sanctioned block (report rule count).
