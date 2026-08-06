# Harness — User Guide

A plain-language guide to using the app. No setup knowledge required.

---

## 1. What Harness is

Harness is a private AI workstation that runs entirely on your Mac.

The models live on your disk. Your conversations live on your disk. Even web search
runs through your own private search engine. Nothing is sent to a cloud service, and
the app works with the Wi-Fi off (apart from searching the web or downloading a new
model, which obviously need a connection).

Inside one window you get:

- **Your own models** — download them, load them, swap between them.
- **Chat** — fast, direct conversations with the model that's loaded.
- **Agents** — assistants that can search the web, research topics, use tools, read
  and write files, and run tasks for you.
- **Files and artifacts** — things the assistant produces (web pages, charts, tables,
  diagrams, code) render live next to the chat, and you can edit and save them.

Harness is one window with **three tabs** along the top. That's the whole app.

---

## 2. The three tabs

**Mission Control** — Harness's own control panel. This is home. It has the chat, the
model library, the settings, the health cards for everything that's running, and the
logs. Most of the time this is the only tab you need.

**Odysseus** — the full web workspace that Harness wraps: chat, documents, sessions,
web search, deep research. Use it when you want its own richer document and research
surface rather than the streamlined chat in Mission Control.

**Hermes** — the full agent dashboard that Harness wraps: tools, skills, memory,
scheduled jobs, configuration. Use it when you want to configure the agent in depth or
watch a long agent run in its native interface.

Mission Control can talk to both of the others, so you rarely *have* to leave it — the
tabs are there for the times you want the full original surface.

---

## 3. Chatting — the four modes

The chat sits in Mission Control. Above the message box are small chips that choose
**how** your message is handled: **Agent**, **Chat**, **Hermes**, plus a **Browse**
toggle. Your conversation list is in the rail on the left; the rail always shows the
chats belonging to the mode you're in.

Chats name themselves after your first message. In the rail you can **rename** (click
the name, type, Enter), **delete** (✕, then confirm), and **duplicate** a conversation.
The rail can be collapsed to give the chat more room.

### What works where

| | Chat | Agent | Hermes |
|---|---|---|---|
| Images in / attach | **Yes** | No | No |
| Web search & research | No | **Yes** | Yes (its own tools) |
| Tools & file access | No | Yes (Odysseus tools) | **Yes, full** |
| Approval cards | — | — | **Yes** |
| Path guard on file writes | — | — | **Yes** |
| Thinking restored on reopen | **Yes** | **Yes** | **Yes** |
| Artifacts (⧉ Open) | **Yes** | **Yes** | **Yes** |
| File cards | — | — | **Yes** |
| Speed | Fastest | Slower (more machinery) | Slower (more machinery) |

### Chat

The most direct mode: your message goes straight to the loaded model and back. Nothing
sits in between, so it's the fastest option and the one to use for ordinary
conversation, writing, and thinking out loud. It has no tools and no web access —
answers come from the model itself.

**Chat is the only mode that takes images.** Attach one with the **⊕** button beside
the message box, or simply **drag an image onto the chat** — the message bar shows a
gold dashed outline when you're over the drop zone. PNG, JPEG and WebP up to 8 MB.

Images need a **vision-capable model**. When one is loaded you'll see a `VISION` pill
by the composer and the ⊕ button appears. If a vision model is loaded but you're in
Agent or Hermes mode, the pill reads `vision · chat mode` — that's the app telling you
to switch to Chat to use it. (Drop an image while in Agent mode and you'll get a short
note explaining the same thing.)

If the model thinks before answering, its reasoning streams into a **thinking** section
that collapses once the real answer begins — click it open any time. Harness keeps that
reasoning, so reopening the conversation later shows a `thinking · restored` section
rather than losing it.

### Agent

Agent mode routes your message through Odysseus, which brings the research tooling:
**web search, page fetching, deep research, memory, and documents**.

While it works, a single status line shows what it's doing (`▸ searching the web…` →
`✓ web_search — 3 steps`), and there's an `INSPECT` disclosure underneath if you want
the raw play-by-play. Sources come back as small pills you can click. Tool-heavy turns
sometimes put the real output into a document rather than the chat bubble — that's
Odysseus's normal behaviour; look in its Library.

No images in this mode.

### Hermes

Hermes is the full agent: tools, skills, terminal access, file reading and writing. Use
it when you want work *done* rather than discussed.

Because it can act on your machine, two safety surfaces appear here:

**Approval cards.** When Hermes wants to run something dangerous, the turn pauses and
an `⚠ APPROVAL REQUIRED` card appears inline showing exactly what it wants to do. You
choose **Once**, **This session**, **Always**, or **Deny**. The card stamps itself
`✓ approved · once` or `✗ denied` and the turn continues. Stopping a turn with a card
open denies it automatically.

> One-time setup worth knowing: Hermes ships with an automatic approval mode where
> another model can wave things through. In the Hermes tab, under Config → Security,
> set approvals mode to **manual** so every dangerous action actually shows you a card.

**The path guard.** File writes are fenced by folder:

- Sensitive folders — your SSH keys, cloud credentials, GPG keys, the macOS Keychain —
  are **blocked outright**. No card, no override; the agent is simply told no.
- Your workspace, the app's own data folder, and temporary folders are **allowed**
  silently.
- **Anything else** — your Desktop, Documents, anywhere else in your home folder —
  **asks first** with an approval card showing the exact path.

When Hermes writes a file you get a **file card** with **Open** and **Show in Folder**
buttons. If the file landed outside your workspace, a faint
`⚠ wrote outside workspace: …` note appears too, and the write is recorded in the guard
log (see §7).

You can press **Stop** at any point during a Hermes turn — the Send button becomes Stop
while it's working.

No images in this mode.

### Browse

Browse isn't a mode, it's a switch. Flip it on and both Agent and Hermes gain the
ability to **drive your Chrome browser** — clicking, typing, navigating, reading pages.

It needs the Browser MCP Chrome extension installed and a tab connected. One flip wires
it into both agents; flipping it off removes it from both. Hermes picks up the change
on new conversations.

---

## 4. Models

Open the **Models** pane from the sidebar.

**Your library** is the list on the left. Each row shows the model's name plus small
pills: `VISION` if it can see images, the format (`gguf` or `mlx`), the quantisation,
the size in GB, and a gold `live` pill on whichever model is currently loaded. Click a
row and the right-hand panel fills with the details — size, context length, where it
came from, its file path — and the action buttons.

**Actions** depend on state, and the button always tells you what will happen:

- **Load** — nothing is loaded yet; bring this one up.
- **Switch** — something else is loaded; swap to this one.
- **Eject** — this is the live model; unload it and free the memory.

**Switching takes about 60–90 seconds** while the weights load. The button goes to
`Loading…` with a progress line, and Mission Control shows the runner as amber. That's
normal — don't click twice.

**Getting new models.** Hit the `SEARCH / DOWNLOAD ⌄` chip to browse HuggingFace.
Search, click a result, and you get its model card plus a list of files with a **fit**
indicator (Fits / May be slow / Won't fit for your machine). Press **Get** on the file
you want. Downloads show a live progress bar with **pause / resume / cancel**, and they
keep running while you navigate elsewhere in the app. `← LIBRARY` takes you back.

**RAM budget.** The pane stamps `· RAM 18 / 48 GB`. Harness reserves headroom for the
rest of your Mac, so if loading a model would blow the budget it refuses and tells you
to eject something first.

**The aux model** is an optional second, small model that handles background chores —
generating chat titles, search queries, memory extraction — so they stop competing with
your main model and slowing your replies down. Set one with the **Aux** action on any
model row, then start the aux runner.

**Housekeeping.** Models the app downloaded can be **deleted** from here (two-step
confirm). Models imported read-only from LM Studio show as such and are managed there.
**Rescan** refreshes the library if you've added or removed things outside the app.

### The in-chat model picker

You don't have to leave the chat to change models. Next to the mode chips there's a
**model chip** showing what's live. Click it and a popover opens listing every installed
model with its **full name** (never truncated) and its pills — live, vision, format,
size, aux.

Each row carries its own actions: **Switch** on the others, **Eject** on the live one,
and **Aux** on all of them (it flashes `aux ✓` to confirm). Clicking a row switches to
that model. Press Esc, click outside, or scroll to close.

---

## 5. Artifacts

When a reply contains something that isn't just prose — an HTML page, an SVG, a React
component, Markdown, a CSV table, JSON, a Mermaid diagram, or a decent-sized block of
code — a small **⧉ Open** button appears under it.

Click it and the thing renders live in a **viewer panel** beside the chat:

- Web pages, SVGs and React components render as real, interactive pages.
- Markdown renders formatted with syntax-highlighted code.
- CSV becomes a **sortable table** (click a column header).
- JSON becomes a collapsible tree.
- Mermaid becomes a proper diagram.
- Code gets highlighting and a Copy button.

Artifacts render in a sealed frame with no network access, so nothing they contain can
reach out or interfere with the app.

**What you can do with it:**

- **Drag the divider** to resize the viewer; the width is remembered.
- **Expand** to fill the window.
- **✎ Edit** turns it into a live canvas — an editor on top, the preview below, updating
  as you type. Copy, Revert, or **Save** to a file (saved files land in
  `Downloads/harness-artifacts`, and you get a Show-in-Folder button).
- **⌖ Pin** keeps the artifact open across chats. Unpinned artifacts close when you
  switch conversations or leave the chat view.

The Open buttons appear when the reply finishes streaming, not mid-sentence — that's
deliberate, so the page renders once and cleanly.

---

## 6. Capabilities

The **⚙ Tools** chip beside the mode chips (or **Capabilities** in the sidebar) opens
the settings for what your agents can actually do. It's split into four sub-tabs:

**General** — the big switches. Web search, web fetch, deep research, memory, the
document editor, retrieval over your documents, the sensitive-content filter, the image
gallery. Plus the search backend (your private SearXNG or a fallback), safe-search
level, how many results to fetch, and the agent's limits on rounds and tool calls.

**Tools** — every built-in agent tool, grouped by category, with a switch per group and
per tool. Below that, your **MCP servers** (connected external tool providers): enable
or disable a whole server, or individual tools within it, and **add or remove** servers.

**Skills** — the agent's built-in and learned skills, with their descriptions. Built-in
skills can have their text customised and reset.

**Models** — pick which endpoint and model handle **background** and **utility** jobs
(this is where you point those chores at your aux model).

Everything you change here applies immediately. API keys are deliberately not editable
from this panel.

---

## 7. Safety & privacy

**It's all local.** The models run on your Mac. Chat history is stored on your Mac. Web
search goes through SearXNG, your own private search engine, running on your Mac.
Everything binds to your machine only — nothing is exposed to your network.

**Approvals are manual by design.** Set Hermes to manual approvals (§3) and no dangerous
action happens without you clicking a chip. The scope you pick is honoured: "Once" means
once, "This session" covers the rest of that conversation, "Always" is remembered
permanently for that exact command.

**The path guard** fences the agent's file writes, as described in §3: sensitive folders
blocked outright, workspace allowed, everything else asks. It fails *closed* — if
anything about a write can't be resolved, it's refused rather than waved through.

**The guard log** keeps a permanent record. Open **Logs** in the sidebar and choose
`guard`: every file the agent wrote outside your workspace is listed as a readable row
— time, tool, file — with a **Reveal** button to show it in Finder and a button to jump
straight back to the conversation where it happened.

**All logs are viewable** the same way — the bridge, each component, the runner — with
**Copy**, **Export** (to `Downloads/harness-logs`), and **Clear**.

**Honest limits.** The path guard covers the agent's file-writing tools. An agent that
writes a file by running a shell command instead rides Hermes's own dangerous-command
approvals rather than the guard. Reading files is not restricted.

---

## 8. Starting, stopping, and health

**Mission Control** is the dashboard. Each moving part gets a card:

- **Runner** — the process serving your model.
- **Hermes** — the agent.
- **Odysseus** — the web workspace.
- **SearXNG** — private web search.

Each card shows a status dot and Start / Stop buttons, plus a link to that component's
log. Everything binds to your Mac only.

**Dependencies are handled for you.** Starting Odysseus needs the runner and SearXNG, so
clicking Start shows you a short plan ("this will also start: runner, searxng") and, once
you approve, brings the whole chain up in order with live per-step progress on the cards.

**Degraded** means something that should be running has stopped answering — the card goes
red and offers **Restart** and **View log**. That's different from **Stopped**, which
means you stopped it on purpose.

**The metric strip** at the top shows tokens used today, turns, speed in tokens/second,
and (when your model reports it) cache-hit rate.

**First run.** A **setup checklist** appears listing each component with an Install or
Start button, so you can get to green without touching a terminal. Once everything's up
it stops appearing.

**⌘K** opens the command palette from anywhere — jump to any view, run a task, reopen the
**setup checklist**, or start the **walkthrough tour** that points out the main parts of
the interface. **⌘R** reloads the current tab.

There's also a **light theme** — the `◐ THEME` chip in the top bar toggles it, and your
choice is remembered.

---

## 9. Tips & troubleshooting

**The panel looks stale or a change didn't appear** → press **⌘R** to reload the tab.

**The Hermes tab says "events feed disconnected" or "session ended (code 1005)"** →
harmless. It happens when the Hermes tab has been sitting in the background and macOS
tidied up its connection. **⌘R** the tab (or press its reconnect button).

**A model switch seems stuck on "Loading…"** → give it 60–90 seconds. Large models take
time to load. The runner card shows amber while it happens.

**Don't drive the same Hermes conversation from Mission Control and the Hermes tab at
the same time** — whichever one you typed in last owns the stream, and the other goes
quiet. Pick a surface per conversation.

**The chat won't take an image** → check two things: you're in **Chat** mode (Agent and
Hermes don't accept images), and the `VISION` pill is showing (the loaded model must be
vision-capable). If the pill reads `vision · chat mode`, just switch to Chat.

**A download seems to have vanished** → it hasn't. Downloads live in the Models pane and
keep running while you use the rest of the app. Go back to Models to see the progress bar.

**Hermes offers an in-app "Update now"** → dismiss it. Harness manages Hermes's version
itself; updating from inside would break the pairing.

**A dangerous command ran without asking** → Hermes's approvals mode is probably still on
its automatic setting. Hermes tab → Config → Security → set approvals to **manual**.

**Chat replies feel slow in Agent mode** → that's the extra machinery (search, memory,
titling) doing its work. Use **Chat** mode for speed, and set an **aux model** (§4) so
background chores stop competing with your main model.

---

## 10. For developers

The technical reference — architecture, ports, APIs, the model registry, the path guard's
internals, and the test suite — is in **`docs/HARNESS-INTERNALS.md`**.
