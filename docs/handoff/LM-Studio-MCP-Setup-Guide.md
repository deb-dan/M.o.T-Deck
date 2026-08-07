# LM Studio — Adding Tools with MCP Servers

> **⟳ 2026-08-07 note:** kept as an LM Studio reference. LM Studio is **not** part of the harness —
> it survives only as a read-only source of already-downloaded models (`~/.lmstudio/models` is
> scanned into `data/models.json`); its llama.cpp backends dir is a last-resort binary-discovery
> fallback. The harness registers MCP servers into Odysseus and Hermes, not into LM Studio's
> `mcp.json`. Current state → `CLAUDE.md`; mechanics → `docs/HARNESS-INTERNALS.md` §7.


## The key concept

LM Studio has **no built-in list of tools**. Tools ("web search", "read files", "browse", etc.) come entirely from **MCP servers** that you register in a single file: `mcp.json`.

- **Plugins** (`js-code-sandbox`, `rag-v1` in the sidebar) = LM Studio's own built-in extensions.
- **MCP → Edit mcp.json** = where you add everything else. Each server can expose one or more tools.

Requires LM Studio **0.3.17 or newer** (it acts as an "MCP Host"). It uses **Cursor's `mcp.json` notation**.

## One-time prerequisites

Most local MCP servers launch through one of these runners, so install both:

- **Node.js** → gives you `npx` — https://nodejs.org
- **uv** (Python) → gives you `uvx` — https://docs.astral.sh/uv/

You do **not** install each server manually. `npx -y ...` and `uvx ...` download and run them on first use.

## How to add servers

1. LM Studio → right sidebar → **Program** tab.
2. **Install → Edit mcp.json**.
3. Paste server entries inside `"mcpServers": { ... }`. Save.
4. LM Studio spawns a separate process per server automatically.
5. Load a **tool-capable model** (Qwen 2.5/3, Llama 3.1+, Mistral, etc.) and start chatting. You'll get a **confirmation dialog** each time the model calls a tool.

Tip: when copying a snippet from a project's README, copy only the content **inside** `"mcpServers": { ... }` and merge it with your existing servers — you can only have one `mcpServers` block.

## The 17 servers in the included `mcp.json`

Legend: **[Node]** = needs Node/npx · **[Py]** = needs uv/uvx · **[Remote]** = hosted URL, no local runtime · 🔑 = needs API key/token

### Web search & browsing
| Server | What it does | Notes |
|---|---|---|
| **duckduckgo** [Py] | Web search, no API key | Easiest search to start with |
| **searxng** [Py] | Private metasearch via your own SearXNG | Needs a running SearXNG (see below) |
| **brave-search** [Node] 🔑 | Brave's search API | Free key at brave.com/search/api |
| **tavily** [Node] 🔑 | Search built for LLMs (clean results) | Key at tavily.com |
| **fetch** [Py] | Fetches a URL and returns readable text | Great pair with any search server |
| **playwright** [Node] | Real browser automation (click, read pages) | Heavier; good for JS-rendered sites |

### Files, data & dev
| Server | What it does | Notes |
|---|---|---|
| **filesystem** [Node] | Read/write files in folders you allow | Edit the path in args — only that folder is exposed |
| **git** [Py] | Inspect/commit a local git repo | Set `--repository` path |
| **sqlite** [Py] | Query a local SQLite database | Set `--db-path` |
| **github** [Remote] 🔑 | Issues, PRs, repos on GitHub | Uses a GitHub Personal Access Token |

### Knowledge & reasoning
| Server | What it does | Notes |
|---|---|---|
| **wikipedia** [Py] | Search & read Wikipedia | No key |
| **context7** [Node] | Up-to-date library/framework docs | No key |
| **huggingface** [Remote] 🔑 | Search models & datasets | HF token |
| **sequential-thinking** [Node] | Structured step-by-step reasoning scratchpad | No key |
| **memory** [Node] | Persistent knowledge-graph memory across chats | No key |
| **time** [Py] | Current time / timezone conversions | No key |
| **everything** [Node] | Reference/test server (demo tools) | Good for verifying MCP works |

That's 17 servers exposing well over 20 individual tools. Start with the no-key ones (**duckduckgo, fetch, filesystem, wikipedia, time, sequential-thinking, memory, everything**), confirm they work, then add keyed ones.

## Setting up SearXNG (for the private-search option)

SearXNG is a self-hosted metasearch engine — results stay on your machine.

> **Superseded (2026-07-19):** the harness decision is **no Docker anywhere**. Run SearXNG natively from source instead — recipe in [02_Architecture.md](02_Architecture.md) §SearXNG — and let the Bridge manage the one shared instance on :8080. The Docker one-liner below is kept only for historical reference.

```bash
# historical / not used: docker run -d --name searxng -p 8080:8080 searxng/searxng
```

Then the `searxng` entry's `SEARXNG_URL` (`http://localhost:8080`) points at it. Enable the JSON output format in SearXNG's `settings.yml` if search calls come back empty.

## Where to find more servers

- **LM Studio deeplinks** — many project READMEs have an "Add to LM Studio" button that fills in the config for you.
- Directories: **glama.ai/mcp/servers**, **pulsemcp.com**, **mcpmarket.com**, and the official **github.com/modelcontextprotocol/servers**.

## Troubleshooting

- **Server won't start** → make sure `npx`/`uvx` work in your terminal; check the path/arg values you edited.
- **Model ignores tools** → the model isn't tool-capable, or tool use is off. Use a recent instruct model and confirm tools are enabled for the chat.
- **Context overflows / slow** → some servers (built for cloud models) return huge payloads. Disable the noisy ones or use a model with a larger context.
- **Security** → only add servers from sources you trust; filesystem/git/code servers can touch your machine.
