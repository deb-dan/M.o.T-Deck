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

## Window and layout

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
3. **A turn seems stuck** → press Stop; it force-ends within ~3s and names the stage it
   died in. Hermes turns that generate for a very long time with no tool call are
   stopped automatically (`hermes.max_turn_s`, default 600s, `0` disables).
4. **Logs** in the sidebar shows every component's log, including `voice worker` and
   `guard`.
