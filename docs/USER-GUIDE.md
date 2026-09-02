# The MOT Deck Guide

> The app is **MOT Deck** — *Mixture of Tools*. Its home screen is **MOT Main**.
> (Both were renamed on 2026-08-21; older text may still say "the harness" and
> "Mission Control" — same thing.)

> **⟳ STALE (as of v1.5.72, 2026-09-02):** the "one window with three tabs" tour below
> describes an early state. The app now runs nine components on Mission Control (Bridge,
> runner, Hermes, Odysseus, SearXNG, VoiceStudio, Voicebox, ComfyUI, Unsloth, OpenCode)
> plus Goose (two lanes), LOffice, Music/Compose, and a sidebar API page — see
> `docs/USER-EXPLAINERS.md` for the current, per-feature guide (it is what the in-app
> Help view serves) and `docs/ROADMAP.md` for what's shipped and what's next. This file
> is kept for its still-accurate general framing but is not reliable for specifics below.

Everything here runs on your Mac. The models, the conversations, the search engine,
the files — all of it lives on your disk and answers to you. This guide is organized
around what you'll want to do, not around how the software is built. Read the first
two sections and you can use the app; the rest is there when you need it.

---

## The one-minute tour

Harness is one window with three tabs at the top:

**Mission Control** is home. Chat, models, settings, health, logs — you can live here.

**Odysseus** and **Hermes** are the two engines Harness is built around, each with its
own full interface. Odysseus is a web workspace (documents, research, memory);
Hermes is an agent platform (tools, skills, scheduled jobs). Mission Control drives
both of them for you, so think of these tabs as the engine rooms: you visit when you
want the deep controls, not for everyday use.

Inside Mission Control, the left sidebar switches views: the chat, the switch/status
dashboard, the model library, capabilities, and logs. **⌘K** opens a command palette
that jumps anywhere and runs most actions by name — when in doubt, ⌘K and type.
**⌘R** reloads the current tab.

---

## Getting to green

Everything in Harness is a component with a card on the dashboard: the **Runner**
(the process that actually serves your model), **Hermes**, **Odysseus**, and
**SearXNG** (your private search engine). Green dot = running.

You almost never have to sequence anything yourself. Components know what they need —
start Odysseus and Harness will show you a short plan ("this will also start: runner,
searxng"), wait for your approval, and bring the chain up in order while the cards
animate through *starting… → online*.

Two states are worth telling apart. **Stopped** means you turned it off. **Degraded**
(red) means it *should* be running but stopped answering — the card offers Restart
and a View-log link so you can see why.

On a brand-new machine, a setup checklist walks each component from Install to Start
without you touching a terminal. Once everything is green it gets out of your way
(you can always reopen it, and a short interface tour, from ⌘K).

---

## Talking to it

The chat is one conversation box with a choice of **who handles your message**. The
chips above the composer pick the route:

**Chat** goes straight to the loaded model. No tools, no web, no middlemen — just the
model, which makes it the fastest mode and the right default for writing, questions,
and thinking out loud. It's also the only mode that can look at images (next section).

**Agent** hands your message to Odysseus, which can search the web, fetch pages, run
deep research, and use its memory and documents. You'll see a live status line while
it works (`▸ searching the web…` → `✓ web_search — 2 steps`), sources arrive as
clickable pills, and an `INSPECT` disclosure holds the raw play-by-play if you're
curious what actually happened.

**Hermes** hands your message to the full agent — the one that can *do* things:
run commands, read and write files, use skills. Because it acts on your machine, it
has real guardrails, described in "Letting it act" below.

**Browse** is a toggle, not a mode: switched on, Agent and Hermes can drive your
Chrome browser through an extension — navigate, click, read pages. It takes effect on
new conversations.

A quick map of what works where:

| | Chat | Agent | Hermes |
|---|---|---|---|
| Speed | fastest | slower | slower |
| Web search / research | — | ✓ | ✓ |
| Images in | ✓ | — | — |
| Acts on your machine (files, commands) | — | — | ✓ |
| Approval cards + path guard | — | — | ✓ |
| Artifacts | ✓ | ✓ | ✓ |
| Thinking shown & restored on reopen | ✓ | ✓ | ✓ |

**Thinking models.** If your model reasons before answering, the reasoning streams
into a *thinking* section that folds away when the answer starts (with its elapsed
time stamped on it). It isn't thrown away: reopen the conversation next week and a
collapsed `thinking · restored` section is still there to unfold.

**Conversations** live in the rail on the left — each mode keeps its own list. Chats
title themselves after your first message; you can rename inline (click the name),
delete (✕, then confirm), or duplicate one. While any turn is running, the Send
button becomes **Stop**, and Stop genuinely stops it.

### The note under the chips

In Chat mode a faint line reads *direct to runner — no tools, fastest*. That's the
whole difference between the three routes said in five words: **Chat** is a straight
line to the model you loaded (nothing between you and it), **Agent** goes the long way
round through Odysseus so it can search and research, and **Hermes** goes the long way
round through the agent so it can actually do things. Slower modes are slower because
they can do more.

### Speaking and listening

Once you've set a voice model in **Models → Audio**, four small controls appear:

- **▶ speak** sits under every assistant reply and reads it aloud in the pinned voice.
  Press it again on the same reply and it plays instantly — renders are cached.
- **● talk** records you and drops the transcript into the message box. It never sends
  by itself, so a misheard word stays editable.
- **auto** is hands-free dictation: it listens, and each time you stop speaking the
  transcript is appended to the box. Still never sent.
- **conv** is a full conversation: you speak, it sends, the reply streams and is read
  back to you, then it listens again. It only appears when you've set **both** a
  text-to-speech and a speech-to-text default — half of the loop is no loop.

Click a lit chip again to stop. When the mic is released the macOS microphone
indicator goes out — that's the honest signal that nothing is listening.

---

## Giving it eyes

Load a model that can see — you'll know because a green `VISION` pill appears by the
composer — then, **in Chat mode**, either click the **⊕** button or just drag an
image onto the chat. A gold dashed outline confirms you're over the drop zone, and
the attached image shows as a thumbnail you can remove before sending. PNG, JPEG, or
WebP, up to 8 MB.

Two rules cover every "why isn't this working":

1. **The model must be vision-capable.** No `VISION` pill, no image — the model
   simply can't see. Vision-capable models are marked in the library too, so you know
   before you load.
2. **Only Chat mode takes images.** Agent and Hermes route through machinery that has
   no image path. Harness reminds you: with a vision model loaded in another mode the
   pill reads `vision · chat mode`, and dropping an image there explains instead of
   silently ignoring you.

---

## Letting it act

Hermes mode is where conversation turns into work — and where Harness is deliberately
strict, because an agent that can write files and run commands should have to look
you in the eye first.

**Approvals.** When Hermes wants to do something dangerous, the turn pauses on an
`⚠ APPROVAL REQUIRED` card showing the exact command. You answer **Once**, **This
session** (the rest of that conversation), **Always** (that exact command,
permanently), or **Deny**. The card stamps the outcome and the turn moves on. If you
hit Stop while a card is open, it counts as a deny — nothing runs by default.

*Do this once:* out of the box Hermes uses a "smart" mode where a second model can
approve things on your behalf. If you'd rather see every card yourself — recommended —
open the Hermes tab → Config → Security and set approvals to **manual**.

**The path guard** fences where files can be written, by geography:

- **Never:** credential territory — SSH keys, cloud credentials, GPG, the macOS
  Keychain. Blocked outright, no card, no override.
- **Freely:** your workspace, the app's own data, temp folders.
- **Everywhere else** — Desktop, Documents, the rest of your home folder — **asks
  first**, with the exact path on the approval card.

The guard fails closed: anything it can't make sense of is refused, not waved
through. Honest limit: it fences the agent's file-writing *tools*; a file written via
a raw shell command rides the command approvals above instead, and reading files
isn't restricted.

**After the write**, you get a file card with **Open** and **Show in Folder**. If the
file landed outside your workspace, a `⚠ wrote outside workspace` note appears in the
turn, and the write goes into the guard log — a plain list under Logs of every
outside write with when, what, and where, plus buttons to reveal the file or jump
back to the conversation that did it.

---

## Getting and running models

The **Models** view is a library on the left, details on the right. Every installed
model shows pills at a glance: `live` (gold — what's loaded now), `VISION`, the
format (`gguf`/`mlx`), quantisation, and size. Click a row for details and actions —
**Load** when nothing's running, **Switch** to swap, **Eject** to unload and free
the RAM.

**Finding new ones.** The `SEARCH / DOWNLOAD` chip browses HuggingFace from inside
the app. Results open with the model card, the file list, and a fit verdict per file
— *Fits / May be slow / Won't fit* — judged against your machine before you commit
to a 30 GB download. **Get** starts the download: a live progress bar with pause,
resume, and cancel, and it keeps running wherever you go in the app. Finished models
appear in the library selected and ready to load.

**Switching takes ~60–90 seconds** — that's the weights loading, not a hang. The
button shows *Loading…* with progress, and the dashboard shows the runner amber
until it's up.

**The RAM budget.** The library stamps something like `RAM 18 / 48 GB`. Harness
counts what's loaded and refuses a load that would blow the budget, telling you to
eject something first — better than watching your Mac grind into swap.

**The aux model.** Background chores — naming chats, writing search queries, memory
upkeep — normally queue against your main model and slow your answers. Point them at
a small second model instead: pick **Aux** on any model, start the aux runner, done.

**Without leaving the chat:** the model chip next to the mode buttons opens a picker
listing every installed model with full, untruncated names and their pills. **Switch**
sits on every row, **Eject** on the live one, **Aux** on all. The list scrolls; Esc
or a click elsewhere closes it.

---

## Keeping what it makes

When a reply contains something worth more than a code fence — a web page, an SVG, a
React component, Markdown, CSV, JSON, a Mermaid diagram, a substantial block of code
— an **⧉ Open** button appears under it. That's an **artifact**: it renders live in
a panel beside the chat.

HTML, SVG, and React render as real interactive pages (in a sealed sandbox with no
network access — an artifact can't phone home or touch the app). Markdown renders
formatted, CSV becomes a sortable table, JSON a collapsible tree, Mermaid a diagram,
and code gets highlighting and a Copy button.

From the viewer you can drag the divider to resize (remembered), expand to full
window, or hit **✎ Edit** for a live canvas — editor above, preview below, re-rendering
as you type — with Copy, Revert, and **Save to file** (files land in
`Downloads/harness-artifacts`, never overwriting an existing one).

Artifacts follow the conversation: open a different chat and the panel closes — unless
you **⌖ pin** it, in which case it stays put while you move around. Open buttons
appear when the reply finishes streaming; that's deliberate, one clean render.

---

## Tuning what it can do

The **⚙ Tools** chip (or Capabilities in the sidebar) is mission settings for your
agents, in four pages:

**General** holds the big switches — web search, fetching, deep research, memory,
document tools — plus the search backend (your SearXNG, with fallbacks), safe-search,
result count, and caps on how many rounds and tool calls a turn may use.

**Tools** lists every built-in agent tool with per-category and per-tool switches,
and below them your **MCP servers** — external tool providers you can add, remove,
or partially enable.

**Skills** shows what the agent knows how to do, with editable descriptions.

**Models** picks which model handles background and utility jobs — this is where the
aux model gets its assignments.

Changes apply immediately. Secrets are deliberately not editable from here.

---

## What you're trusting

Short version: your own hardware, and nothing else.

Models execute on your Mac. Conversations are stored on your Mac. Web searches go
through SearXNG running on your Mac, so not even your queries leak to a search
company. Every service binds to the machine itself — nothing listens for the outside
world. With Wi-Fi off, everything except web search and downloads keeps working.

When you want receipts, the **Logs** view has them: the bridge, every component, the
runner, and the guard log, each with Copy, Export (to `Downloads/harness-logs`), and
Clear. The guard log in particular is the audit trail for "what did the agent touch
outside its lane" — readable rows, not stack traces.

---

## When something looks off

**A change or update isn't showing** → ⌘R the tab. Webviews cache; a reload settles it.

**Chat won't take an image** → two checks, in order: is the `VISION` pill on (the
loaded model must see), and are you in **Chat** mode (the pill saying
`vision · chat mode` means "right model, wrong mode").

**A switch sits on "Loading…"** → normal for 60–90 seconds on big models. Amber
runner card = still loading. Don't click again.

**Hermes tab shows "events feed disconnected" / "code 1005"** → harmless; macOS put
the backgrounded tab's connection to sleep. ⌘R brings it back.

**A "dangerous" command ran without a card** → approvals are still on the automatic
setting. Hermes tab → Config → Security → **manual**.

**Same Hermes chat open in Mission Control *and* the Hermes tab** → whichever
surface you typed in last owns the live stream; the other goes quiet. One surface
per conversation.

**Agent replies feel sluggish** → that's real work (search, memory, titling), not a
fault. Use Chat mode when you don't need tools, and set an **aux model** so the
chores stop queueing against your conversation.

**A download "disappeared"** → it didn't; it's still running in the Models view.

**Hermes offers "Update now"** → decline. Harness pins the version it ships and
manages updates itself; updating from inside would desynchronize the pair.

---

## Going deeper

The engineering reference — architecture, ports, APIs, registries, the guard's
internals, the test suite — is `docs/HARNESS-INTERNALS.md`. This guide tells you how
to drive; that one tells you how the engine is built.
