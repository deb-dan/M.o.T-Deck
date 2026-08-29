# MOT Deck explainers

> The app is **MOT Deck** (*Mixture of Tools*). Its home screen is the deck itself —
> the page the sidebar calls **MOT Deck** and the page heading calls **MOT Main**.

Every entry here answers a question that has actually cost time to figure out. This
file **is** the in-app Help view (sidebar, under Logs): Help renders it live, so
editing this file is the only step needed to change what the app shows. Keep entries
short, plain, and honest about limits — no marketing voice.

---

## Chat lanes — the three chips above the composer

| Chip | What happens | When to use it |
|---|---|---|
| **Agent** | Your message goes through Odysseus, which can use tools: web search, deep research, memory, documents. | Anything needing the web or multi-step work. |
| **Chat** | Straight to the local model on the runner. No tools, no web, nothing in between. This is what *"direct to runner — no tools, fastest"* beside the chips means. | Quick questions, drafting, anything self-contained. Fastest by a wide margin. |
| **Hermes** | Goes to the Hermes agent, which has its own tools, skills, approvals and file access. | Real agent work on your machine: writing files, running commands, multi-tool tasks. |

**Browse** toggles a browser-automation tool for the agent lanes. **Tools** opens
Capabilities.

Why Hermes turns can feel slow: Hermes hands the model a large system prompt (tool
schemas + a skill index). A small local model has to read all of it before it says a
word. That is what the Hermes tools lever (below) exists to shrink.

---

## Hermes tools — what those switches actually control

- The switches control **the lane this app's chat uses** (Hermes calls it the `cli`
  platform). That is the same lane the Hermes tab's chat uses.
- **"Hermes's defaults"** restores what a fresh Hermes gives that lane — which is
  *not* every toolset. Hermes deliberately ships seven off (video analysis, video
  generation, X search, Home Assistant, Spotify, and the two Discord ones). You can
  still turn any of them on individually; they just aren't part of "defaults".
- **"Minimal preset"** keeps file + terminal + clarify: enough to read, write, run
  things, and ask you a question.
- **Check** answers the only question that matters — *what will Hermes actually hand
  the model?* It reads live from Hermes and lists the tools by name. It cannot see
  tools from connected MCP servers, and it says so.
- Rows that need one-time setup inside Hermes (API keys, a provider install) carry a
  **needs setup in Hermes** pill. Rows that aren't prompt toolsets at all (speech-to-
  text config, Discord-only) say so and are never moved by a preset.

### Toolsets vs. skills — two different layers
Hermes's own Skills page has an **ALL** tab showing "78/78 enabled" and a **TOOLSETS**
tab. They are different things:
- **Skills library** (the ALL tab) = the skills installed on disk. Ours doesn't touch it.
- **Skills toolset** (one switch on our page) = whether the *index of those skills* is
  put into the model's prompt. Turning it off leaves all 78 installed and removes the
  whole index from the prompt — the single biggest prompt saving available.
- **Per-skill trimming** (`▸ per-skill` under that row) removes individual skills from
  the index. Note: Hermes stores this **globally**, so a skill switched off here is off
  on every Hermes surface, not just this app's lane.

### Why Hermes's own page used to disagree
Hermes's Skills page fetches its list once when the tab opens and never refreshes
itself. Changing something here and then looking there showed a stale page. The app
now reloads that tab for you when you switch to it after a change. (Exception: a
Hermes pane already open *beside* the panel in split view never "becomes visible", so
press ⌘R there.)

---

## Voice

| Control | What it does |
|---|---|
| **▶ speak** (under a reply) | Reads that reply aloud with your default TTS voice. |
| **● talk** (the mic, inside the message box beside Send) | Records, transcribes, and **appends into the message box** — never auto-sends. |
| **auto** (top of the switch beside Send) | Hands-free dictation: speak, pause, the text appears. Still never auto-sends. |
| **off** (middle of the switch) | The resting position. The mic only listens while you use ● talk. |
| **conv** (bottom of the switch) | Full conversation: speak → auto-sends → reply streams → reply is read aloud → listening resumes. Needs **both** a TTS and an STT default set. |

**auto** and **conv** are the two ends of one vertical three-position switch at the
right edge of the message box; the middle is **off**. Clicking the engaged end again,
or the middle, returns to off. ↑ / ↓ / Home / End move between the three.

- The mic is switched off while the assistant is thinking or speaking, so it can never
  transcribe itself. You cannot interrupt playback by talking (yet) — press ■ stop.
- **First render of a new reply is slow** (the model generates audio); **repeats are
  instant** (cached). A pinned reference clip is transcribed once when you pin it.
- **Cloning models** (e.g. OmniVoice) have no named voices — they copy the voice in a
  reference clip. Pin one, or every render is a different random voice. **Named-voice
  models** (e.g. Kokoro, Qwen3-TTS CustomVoice) list their voices as chips instead.
- Long clips are trimmed to ~12s: the model only listens to the first ~10 seconds.
- Speech-to-text engines are selectable: whisper (broad language coverage) or Parakeet
  (doesn't hallucinate phrases out of silence, which matters in conv mode).

---

## Models

- **Runner** = the one model serving chat. **Aux** = an optional second model for
  Odysseus's background tasks (titles, search queries, memory).
- **Load / Switch / Eject**: Eject frees the RAM and forgets the choice; Stop on the
  runner card pauses the process but remembers it.
- The **RAM figure** under the model list counts model files against a budget, so a
  switch that would not fit is refused instead of thrashing.
- **Chat models** and **Audio** are separate tabs; audio models never appear in chat
  pickers. **Rescan** re-reads what is on disk (including other apps' HuggingFace
  cache, read-only) — use it after deleting a model elsewhere.
- Provenance pills: `downloaded`/`local` are app-owned and deletable here;
  `lmstudio`/`jan`/`hf cache` are managed by those apps — use **hide from list**.

---

## Music — making songs

- **One door, two looks.** The sidebar has a single **Music** row and the app a single
  **Music** tab. It opens **Music Studio** — the latest song big at the top, playing in
  place. The dropdown beside the page's title switches to **Music Classic**, the
  original page with everything on one screen; the same switcher sits in Classic's own
  header to bring you back. They drive the same engines and the same library, and
  neither keeps its own copy of anything — rename or delete a track in one and the other
  sees it immediately.
- **What a render actually is:** a one-shot process. Nothing runs in the background, no
  port is opened, and no model stays in memory afterwards. One render happens at a time
  on purpose — two would fight over the GPU. You can leave the tab; the song is waiting
  when you come back.
- **Two engines, a real trade-off.** *acestep.cpp* renders a song in roughly 25 seconds
  and is the fast one; *MiniMax-Music3* takes about two minutes per minute of song and
  is the high-quality one. Each is a download (7.6 GB and 11.1 GB here); acestep is
  also **built** on your machine, which needs `cmake` — the app says so before it spends
  a byte.
- **How much memory a render wants** (about 9 GB for acestep, 14 GB for MiniMax) is a
  *planning* figure — the weights plus working set, not a measured peak. If a render
  would not fit alongside the models already loaded you get the numbers and a **Generate
  anyway**. It is advice, never a wall: being wrong costs swap, not your song.
- **The prompt is the biggest lever.** Both engines were trained on structured
  descriptions: genre, tempo, key, instrumentation, vocal character, section by section,
  mix. That is why the **presets** are long — they are examples of a good caption, and
  clicking one only fills the fields; it never renders by itself.
- **Lyrics are optional.** Leave the field empty and you get an instrumental (MiniMax is
  explicitly told `[Instrumental]`). Section tags — `[Verse]`, `[Chorus]`, `[Bridge]` —
  shape the arrangement rather than being sung.
- **Length** is 10 to 300 seconds. Render time grows *faster* than length on MiniMax (60
  seconds of song cost 115s here, 145 seconds cost 676s), which is why any
  remaining-time figure comes from renders measured on this Mac — and is left out
  entirely when it cannot be said honestly.
- **Steps** default to each engine's own design point (30 for MiniMax, 8 for acestep)
  and mean different things in each; they are not a shared knob. Leave the field empty
  to use the default.
- **Seeds make a song repeatable.** The same seed with the same settings and the same
  engine gives the same song again. If you leave the seed empty one is drawn for you and
  **recorded with the track**, so a song you like can always be made again — click the
  seed on a finished track to put it back in the field.
- **A track's name is yours, and it is not the filename.** Files are written with a
  timestamp name (`minimax-20260820-235921.wav`) and are **never renamed**: a name you
  give a track is stored beside it, so the list and the folder can never disagree. Clear
  the name and the track falls back to the start of its prompt.
- **Nothing is deleted automatically.** Tracks are kept until you delete them; *Reveal*
  opens the file in Finder. A finished track can be converted to MP3 or M4A beside
  itself — only the formats your ffmpeg can actually write are offered, and only when
  that sibling does not exist yet. A conversion shares one record with the original, so
  both carry the same name, prompt and seed.
- **Where songs are saved** can be changed (type a path — this window has no folder
  picker). The library then lists that folder only; tracks in the old one are untouched
  and reappear if you set it back.
- **Stopping a render leaves nothing behind** — no half-written file, and no false entry
  in the measured history. A failed render says what the engine said.

---

## Generate — pictures and video clips

### What you see, and where everything else went

- The **Generate** page turns a sentence into a still image or a short clip, on this
  Mac, offline. It drives the ComfyUI engine that is already installed here, so you
  never have to touch a node graph — the **ComfyUI** tab stays there for that.
- **At rest the page is seven things:** the two status chips (the engine, and free
  disk), the big result stage, the strip of recent results, the prompt box, the
  Image/Clip switch, the model chip, and **Generate**. That is deliberate. Everything
  else — licences, file paths, verification mechanics, the security rationale, the
  measured numbers — is still there, and this section is where it lives in full.
- **Hover (or tap, or focus and press Enter on) any chip.** Every chip on the page is
  a control: the sentence behind it, the arithmetic, and the caveat are all in its
  tooltip. Chip and tooltip come off one object, so they can never disagree.
- **Nothing here is a paragraph you have to read to use the page.** If the page ever
  stands a sentence in front of you, it is because something is true right now and
  wants a decision — the engine is off, a file is missing, or you have not downloaded
  a model yet.

### The model / workflow picker — every model on this Mac, and what each one can do

- **Between the prompt and Generate there are two menus: a MODEL and a TYPE.** The model
  list is not a list anyone typed into MOT Deck. It is read, every time you open the
  page, from ComfyUI's own vendored workflow templates crossed against what is actually
  in your models folder. **Download a model and it appears with its workflows; delete
  one and it drops off.** Nothing needs to be told, refreshed or reinstalled.
- **A model carries several types**, because one set of weights usually drives more than
  one workflow — text-to-video, image-to-video, video-to-video, a still. Each TYPE is a
  separate row with **its own required files, its own controls and its own graph**. Two
  types of the same model can therefore disagree about whether they are ready, and they
  are allowed to: the one that needs an extra 1.26 GB companion says so and the other
  one runs.
- **The chip after the two menus is the whole answer.** `ready` means every file that
  workflow loads is on disk and pressing Generate runs it. Otherwise it reads
  `Get 4.39 GB` — press it and only *that workflow's* missing files are fetched, not the
  whole family. Its hover names each missing file. A size we have not confirmed with the
  server is shown as unknown rather than guessed.
- **The controls on the left follow the type you picked.** A workflow with no negative
  prompt shows no negative-prompt box; one that makes stills shows no frame count. They
  are read off the graph that will actually run, so what you see is what it takes.
- **A type that starts from a picture shows a SOURCE menu**, listing your own results
  (anything in the results rail) and anything already in ComfyUI's input folder. Make a
  still with an image model, then feed it to an image-to-video workflow — that is the
  whole loop, and neither step leaves the tab.
- **Some workflows say `not runnable here`.** That is honest rather than broken: the
  newest templates are built out of *subgraphs*, which this page does not expand. Their
  files are fine, and the ⋯ menu's **Open template in ComfyUI** puts them in the ComfyUI
  tab, where they run exactly as their authors wrote them.
- **The two curated models still go through their own pinned path.** SDXL and Wan 2.1
  were sha256-pinned, licence-read and measured on this Mac; picking one of their
  templates runs that verified builder rather than the generic converter, which is why
  their measured times and the Wan colour warning still apply.
- **Downloads from the catalogue get a weaker check, and say so.** A curated model is
  verified against a pinned sha256. A model discovered from the registry has no
  published hash, so it is verified against the size the server declares — the chip's
  hover states which of the two checks the file got.
- **Both side panes drag.** The 8px gutters either side of the picture are the handles
  (← → nudges them from the keyboard); the results rail's thumbnails grow as you widen
  it, and the picture's own handle, dragged upward, hands the height to the prompt.
  Widths, the split, and the model you were working with come back next time.

### Models — the sheet behind the model chip

- **Click the model chip** (next to Image/Clip) to open the models sheet. One row per
  model: name · what it is for · size · licence chip · any measured health verdict ·
  the state chip that does the work.
- **The state chip is the action and the truth**: `Get 6.94 GB` → `Downloading 42%`
  (with a progress line under the row) → `Verifying…` → `On disk ✓`. If a download is
  interrupted it becomes `Resume · 212 MB of 254 MB` — counted against what is *left
  to fetch*, not against the whole model — and the part-file survives a bridge restart.
- **The starter set is two downloads**, one per job: *SDXL base 1.0* (6.94 GB,
  CreativeML Open RAIL++-M) for stills and *Wan 2.1 T2V 1.3B* (9.83 GB, Apache-2.0)
  for clips. Take either on its own. Together they are **16.77 GB, which is 2.77 GB
  over the 14 GB budget**, and the sheet says so rather than quietly dropping one.
  One model would have covered both — the video model can be asked for a single frame
  — but that was tried on this Mac and the picture came out unusable, so it is not
  offered as the image answer.
- **The licence chip's hover carries the licence note and the link to the full text.**
  That link exists there and nowhere else: it is a legal document, not a button that
  competes with Download.
- **Every downloaded file is checked against a pinned size and sha256.** A file that
  fails either check keeps its `.part` name and is **never** reported as downloaded.
  The `On disk ✓` chip's hover says exactly this.
- **The file manifest** — each weight file, its folder, its size and its state, plus
  which files are shared between models (the umt5/T5 encoders) — is under the row's
  **⋯ → Show the file list**. It is an installer's manifest; it appears when you ask.
- **Where the files go** is not printed anywhere on the page, on purpose. Use
  **⋯ → Reveal the models folder** and **Reveal** on a result: showing you the place
  beats printing a path you cannot click.
- **The model chip picks itself.** Choosing Image or Clip selects the model measured to
  be good at that job; if you disagree, click a model's name in the sheet.

### Honesty, measurement and refusals

- **Disk warnings never block a download.** The `Get` chip's hover states what it needs,
  what is free and what would be left; the decision stays yours. The disk chip in the
  header is always on and turns gold while a download is spending the space.
- **Speed and memory are measured, never predicted.** The first run of a model in a
  given mode is the measurement, and until it happens the page says
  `first run = measurement` rather than inventing a time. Afterwards the numbers ride
  on the model chip's hover and on the finished result's caption chips
  (`36s · peak 14.29 GB`), worded as what they are: the measured phys_footprint of the
  ComfyUI process on this Mac.
- **A curated model is not a promise that its output is good on your machine.** Where a
  model has been run here and found wanting, its row wears one amber chip — today
  `colour shift here` on Wan 2.1 — and when that model is the one selected, **the model
  chip beside Generate turns amber and carries the same mark**. The full measured
  verdict, with dates and numbers, is in the hover. Same words, same object, both places.
- **If a model file is missing**, the page names the file and its size in one line and
  puts a `Get 254 MB` button next to it. If a download for it is already running it says
  *that* instead, rather than offering a button that would start nothing.
- **If ComfyUI is not running**, the engine chip goes red and reads `engine off`,
  Generate is disabled, and one line points at MOT Deck → Components. The page keeps
  polling and recovers on its own once the engine is back — no refresh needed.
- **One job at a time.** ComfyUI runs them in order; you can leave the tab and the
  result is waiting when you come back. While a job runs the stage becomes the progress
  surface (`step 14 of 30`), and if the live progress feed drops you see `(polling)` —
  the *result* never depended on that feed.

### Results

- **The gallery keeps everything.** Recent results are the strip under the stage;
  **All results ▸** expands the full grid in place. Per-item and total sizes are shown
  and nothing is ever deleted automatically — pruning is a deliberate act you do in
  Finder via **Reveal**.
- A result whose file has been removed, or whose size changed since it was made, or
  which was found on disk with no record of being made, is still listed, with an amber
  or red chip saying which.
- **The caption chips under the stage are the run.** Size, seed, wall time, peak memory,
  file size. **Click the seed chip** to put that seed back in the field and make the
  same picture again.
- **A finished run writes its real values back into More ▸** — the resolved size, the
  steps, and the frame count after it snaps to 4n+1 — so what you are looking at is what
  you can edit and re-run. The **seed field is the exception**: it resets to random after
  every run on purpose, and the seed that was actually drawn lives on the caption chip.
- **⋯ on a result** gives you the exact API-format graph that produced it, Reveal in
  Finder, and a link to the ComfyUI tab. Job records live in the bridge's memory, so the
  graph for a result made before the last bridge restart is no longer on record — the
  page says that rather than failing cryptically.
- **More ▸ is the one disclosure gate**: width, height, steps, seed, negative prompt,
  and for clips frames and fps. It carries a dot when anything under it differs from the
  template's defaults, so a hidden edit is never silent. **Frame counts snap to 4n+1**
  because this model's latents move four frames at a time; the number actually used is
  written back after the run.

### The fence

- Only **stock ComfyUI nodes** are used, and no third-party node packs are installed by
  this page. Those are arbitrary code loaded into the engine at startup and have twice
  been used to ship credential stealers. When `custom_nodes/` is empty — the normal case
  — the page says nothing about it at all; if packs appear, an amber chip appears in the
  header naming how many, with this sentence in its hover.

---


## Goose — two lanes: Goose CLI and Goose UI

- **There are two Goose tabs and they are both real.** **Goose CLI** is the agent in a
  terminal. **Goose UI** is the same agent behind goose's own graphical app, embedded in
  a tab here. Same program, same models, two surfaces — use whichever suits the job.
- **They do not share a conversation.** Each keeps its own home and its own session
  history (`data/goose/` for the CLI, `data/goose/ui-home/` for the UI), so a session
  started in one does not appear in the other. Both can be open and working at the same
  time.
- **They do share your files.** Both are pointed at the same `data/goose-workspace`
  folder, deliberately: that is your project directory, not lane state, and two of them
  would give you two different "my files" for one product.
- Everything below about installing, the model, approvals, the workspace and telemetry
  applies to **both lanes** unless a bullet says otherwise.

### Goose CLI — the agent in a terminal

- **Goose CLI** is a coding/ops agent that runs *in a terminal inside its own tab*. It is
  not a service: there is no card on MOT Deck to start or stop, because it exists only
  while that tab holds it. Close the tab and the session ends; press **Start** and you
  get a new one.
- It is **not installed until you ask**. The first time you open the tab it offers
  **Install goose** — one 90 MB download, checked against a **pinned sha256 before
  anything is unpacked**, and checked again on the file it unpacked. If either check
  fails nothing is installed and the log says which one.
- It talks to **the model loaded on this Mac**, at the runner this app already runs.
  The header shows the exact URL it will call, so a wrong port is visible without
  reading a log. Nothing goes to a cloud.
- **It needs a model that can call tools.** Goose has no fallback for one that cannot —
  it will look broken rather than merely slow. The tab says so *before* you type if the
  loaded model lacks the green **tools** pill in Models. It still lets you try: that is
  a warning, not a wall.
- **It asks in the terminal before it writes a file or runs a command.** That prompt is
  the approval step, it appears in the terminal, and it is switched *on* by this app —
  goose on its own would have done those things without asking. Read it, then answer it.
- **What it can touch is one folder:** `data/goose-workspace`. That is the directory it
  is started in and the only boundary on what it edits — so put the files you want it
  to work on there.
- **Everything it remembers stays under `data/goose/`** — its settings, its session
  history, its logs. It never writes to your home folder's usual hidden config
  directories, which is what makes the whole lane removable by deleting one folder.
- **Telemetry is off, twice.** Goose's own analytics are opt-in upstream; this app
  additionally switches them off in its environment *and* in its config file, and a
  test checks both on every release.
- The terminal keeps a **dark background in every theme**. The colours in it are
  goose's own — its banner, its diffs, its prompts — and they were drawn for a dark
  terminal. The frame around it follows whatever theme you picked.
- Both goose rows are on the **sidebar** by default rather than pinned to the tab strip.
  Clicking a sidebar row opens its tab — and that tab then takes one of the strip's three
  swappable slots (see *Window and layout*), so it is there while you are using it. Pin
  either one in **Capabilities → Appearance** if you want it there permanently.
- Sessions are named by time, not by a generated title, and that is deliberate: asking
  the model for a title costs a whole second request, and on a thinking model that
  request can outlive the answer you were waiting for.

### Goose UI — the same agent, graphical

- **Goose UI** is goose's own desktop app interface, running inside a tab here. The
  interface is upstream's, unmodified; what this app supplies is the page it is served
  from and the goose process behind it, which it starts for you when you open the tab.
- **It installs itself, once, and tells you the cost first.** The tab's first screen is
  an **Install** button that names the download — about 209 MB, of which roughly 7 MB is
  kept — because a button that quietly starts a quarter-gigabyte download is not a thing
  this app ships. Every piece is checked against a pinned digest before it is used; if a
  check fails, nothing is installed and the page says which one.
- **If it cannot start, it says so in words.** A tab that loaded the interface with a
  dead connection behind it would read as "goose is broken"; instead you get a page
  naming what failed, the command that fixes it, the log to look at, and a link to the
  terminal lane, which is unaffected.
- **What is missing in a tab, and why.** The interface is built for a desktop app with
  native windows and file dialogs; a tab has neither. So: **"open in a new window" opens
  in this same tab**; there is **no native file, folder, recipe or session-import
  picker** and **no save dialog** — the working directory is fixed to the goose
  workspace; a **file you drag in has no path attached**, though dropped text still
  works; the **`.goosehints` editor cannot read or save**; and **"reveal in Finder"** and
  the file-mention autocomplete that lists your folders **do nothing**. Everything else
  — chat, models and providers, sessions, recipes, the scheduler, extensions — is the
  real thing. Each of these thirteen also says so in the browser console when the
  interface asks for it, so nothing degrades silently.
- **It is one goose process, supervised.** Opening the tab starts it; closing the app
  stops it. It appears in **MOT Deck's memory ledger by name** ("Goose UI") for as long
  as it runs, so the RAM it holds is never quietly filed under something else. It also
  refuses to touch any goose process it cannot prove it started — if you run goose
  Desktop yourself, this app will not close it.

---

## OpenCode — the tabs called "runner auto session"

- **Every launch of the app adds one empty draft tab to OpenCode, and that is normal.**
  The OpenCode tab opens straight onto a new-session composer for your workspace, and
  OpenCode's own interface remembers each composer you land on as a **draft tab** in its
  strip. Open the app tomorrow and there is one more. It is a quirk of how OpenCode
  restores its strip, not something you did.
- **They are labelled "runner auto session" so you can tell them apart from your work.**
  OpenCode calls them "New session"; MOT Deck renames them on screen so a tab you never
  opened does not read like a conversation you started and abandoned. Only the *label*
  is changed — nothing inside OpenCode is edited, and if OpenCode is ever updated past
  the version this app pins, the rename quietly stops and you see its own wording again.
- **A draft *you* start keeps OpenCode's own "New session".** Only the one draft the app
  lands on by itself when the tab boots is renamed. Click **+** in OpenCode and the tab it
  creates is yours: it reads "New session", it stays that way through a reload and a
  restart, and MOT Deck never puts its own words on it. (Drafts already in the strip from
  before this rule arrived read "New session" too — closing them with **✕** is enough.)
- **Nothing is stored in them and nothing is lost by closing them.** They are empty
  composers: no message was ever sent, and there is no session on the server behind them
  (OpenCode's own session list is empty). Close each one with its **✕** in OpenCode's own
  tab strip whenever the strip gets long — that is the honest way to prune them.
- **A tab you have actually used is safe.** Sending a message turns that draft into a
  real session on the spot, with its own title. Real sessions are never relabelled and
  are never created for you.

---

## Window and layout

- **The tab strip holds twelve tabs: nine you pin, then three that follow you.** The
  first nine are yours — set them in **Capabilities → Appearance**, and they never move.
  The last three hold whatever you opened most recently: open something from the **⋯**
  menu at the right of the strip (or click its sidebar row) and it takes a slot, pushing
  the oldest of the three back into **⋯**. Nothing is lost either way — **⋯** always
  lists every tab that is not on the strip.
- **⫽** splits the window. The **gold rail** marks the focused pane; the tab strip
  always changes the focused pane. Picking the tab the other pane holds **swaps** them.
  Each pane has its own **✕**.
- **Drag a tab label** onto a pane to send it there. Drag the tab the *other* pane is
  showing to get a **second live copy** of that app side by side (copies are discarded
  when the split closes).
- **◐** cycles the four themes: Editorial (dark), Warm Paper (light), Luxury Gold,
  Cyber. **▣** is an optional denser button chrome (opt-in). **✦** is a separate axis
  again — it flips the whole panel to the Studio design, and one more click puts
  Editorial back exactly as it was.
- Drop an **image** on the Chat view to attach it; drop a **wav/mp3** on the panel to
  add it to the voice clip library.

---

## Cards that appear mid-turn

- **⚠ approval required** — Hermes wants to run something dangerous. Once / this
  session / always / deny.
- **⚠ answer needed** — the model asked you a question (Hermes's `clarify` tool).
  Pick a chip, type an answer, or cancel. Multi-select questions let you toggle
  several and confirm.
- A turn that ends while a card is open stamps it `expired` — nothing was answered.

---

## When something looks wrong

1. **A component card is red/degraded** → Stop, then Start it on MOT Deck.
2. **A tab shows "Not reachable yet"** → that component isn't running; start it, then
   re-select the tab (or ⌘R).
3. **A thin gold strip appears above a tab** → that app is running but something it
   depends on isn't, so its own page looks fine while everything inside it fails. The
   strip says exactly what is missing and offers the one button that fixes it — *Start
   the Runner*, *Restart Hermes*, *Open MOT Deck* to load a model. It is only ever
   advice: it never blocks the tab, it sits **above** the page rather than over it, and
   it disappears by itself once the problem is gone. **✕** hides that particular
   sentence; a different one still speaks up. The commonest case is a model swap —
   an app is wired to whichever model was loaded when it started, and restarting it is
   what re-points it at the current one.
4. **A turn seems stuck** → press Stop; it force-ends within ~3s and names the stage it
   died in. Hermes turns that generate for a very long time with no tool call are
   stopped automatically (`hermes.max_turn_s`, default 600s, `0` disables).
5. **Logs** in the sidebar shows every component's log, including `voice worker` and
   `guard`.
