# Top 40 MCP Servers — A Practical Reference (2026)

> **⟳ 2026-08-07 note:** reference material, still valid as an MCP catalogue. In MOT Deck, MCP
> servers are registered **into the components**, not into a desktop app: Odysseus via
> `POST /api/mcp/servers` (surfaced in the panel's Capabilities → Tools, with Add/Remove) and
> Hermes via a YAML round-trip into `~/.hermes/config.yaml` `mcp_servers`. The only one wired by
> default is browsermcp.io behind the chat **Browse** toggle. Current state → `CLAUDE.md`;
> mechanics → `docs/MOT-DECK-INTERNALS.md` §5.4 and §9.


Legend: 🟢 no key needed · 🔑 needs API key/account · 🌐 remote/hosted (no local runtime) · ⚙️ local (needs Node `npx` or Python `uvx`)

> Note for LM Studio: MCP servers built for cloud models (Notion, Salesforce, Google Workspace, etc.) can return large payloads that overflow a small local model's context. Prefer lightweight servers and models with bigger context windows for the heavy ones.

## Already in your two configs
filesystem, fetch, duckduckgo, wikipedia, sequential-thinking, memory, time, git, sqlite, playwright, context7, everything, brave-search, tavily, huggingface, github. Everything below is *additional*.

## Search & web
1. **Exa** 🔑🌐 — the most-used search server in 2026; neural/semantic web search built for AI.
2. **Perplexity (Sonar)** 🔑 — answer-engine style search with citations.
3. **Firecrawl** 🔑⚙️ — scrape/crawl sites into clean markdown; great for RAG ingestion.
4. **Bright Data Web MCP** 🔑 — large-scale web scraping / unblocking.
5. **Kagi Search** 🔑 — high-quality, ad-free search for those with a Kagi account.

## Browser & automation
6. **Puppeteer** 🟢⚙️ — headless Chrome automation (lighter alternative to Playwright).
7. **Browserbase / Stagehand** 🔑 — cloud browsers with AI-driven actions.
8. **Apify** 🔑 — thousands of prebuilt "Actors" for scraping and automation.

## Developer & version control
9. **GitLab** 🔑 — GitLab equivalent of the GitHub server.
10. **Sentry** 🔑 — pull error reports and stack traces into the model.
11. **Docker / Docker Hub** 🔑⚙️ — manage containers and images.
12. **Sequential filesystem alt — `desktop-commander`** 🟢⚙️ — run shell commands + file edits (powerful; use with care).
13. **E2B** 🔑 — secure cloud sandboxes to run model-generated code.
14. **Terraform** 🔑 — infrastructure-as-code operations.

## Databases & data
15. **PostgreSQL** ⚙️ — query Postgres with natural language → SQL (official reference server).
16. **MySQL** ⚙️ — same for MySQL.
17. **MongoDB** 🔑⚙️ — official MongoDB server for document databases.
18. **Redis** ⚙️ — key/value cache access.
19. **Supabase** 🔑 — Postgres + auth + storage backend.
20. **ClickHouse** 🔑 — fast analytics database queries.
21. **Chroma** 🟢⚙️ — local vector DB for building RAG.
22. **Qdrant** 🔑⚙️ — vector search engine for embeddings/RAG.

## Productivity & docs
23. **Notion** 🔑 — read/write Notion pages and databases.
24. **Obsidian** 🟢⚙️ — work with your local Obsidian vault (markdown notes).
25. **Google Workspace** 🔑 — Gmail, Docs, Sheets, Drive, Calendar (OAuth).
26. **Todoist** 🔑 — task management.
27. **Linear** 🔑 — issue tracking for product/eng teams.
28. **Jira** 🔑 — Atlassian issues and projects.
29. **Confluence** 🔑 — Atlassian wiki/docs.

## Communication
30. **Slack** 🔑 — read/post messages, search channels (official reference server).
31. **Discord** 🔑 — bot-driven messaging.
32. **Resend / SMTP email** 🔑 — send email programmatically.

## Cloud & storage
33. **AWS (various official servers)** 🔑 — S3, Lambda, cost, docs, etc.
34. **Cloudflare** 🔑 — Workers, KV, R2, DNS.
35. **Google Drive** 🔑 — file search and retrieval.

## Business / CRM / marketing
36. **HubSpot** 🔑 — CRM contacts, deals, marketing data.
37. **Stripe** 🔑 — payments, customers, invoices.
38. **Ahrefs** 🔑 — SEO metrics and keyword data.

## Knowledge, reasoning & utility
39. **Zapier MCP** 🔑🌐 — bridges to 6,000+ apps via one server (huge breadth, no local install).
40. **Wolfram Alpha** 🔑 — computational knowledge, math, unit conversions, facts.

## Honorable mentions
- **arXiv / PubMed** 🟢 — academic paper search.
- **YouTube transcript** 🟢⚙️ — pull video transcripts for summarizing.
- **Home Assistant** 🔑 — control smart-home devices.
- **Google Maps** 🔑 — places, directions, geocoding.
- **Pandoc** 🟢⚙️ — convert documents between formats.

## Where to browse the full ecosystem
- **mcpservers.org** (Awesome MCP Servers) and the official **github.com/modelcontextprotocol/servers**
- Directories: **PulseMCP** (curated), **Glama**, **Smithery**, **MCP.so**, **mcpmarket.com**

## Practical picks for a local LM Studio setup
If you just want a strong, mostly no-key daily driver on top of what you have: add **Puppeteer** (🟢 browsing), **Obsidian** or **desktop-commander** (🟢 local files/commands), **Chroma** (🟢 local RAG), **PostgreSQL/SQLite** (data), and one good keyed search like **Exa** or **Firecrawl**. Keep the total modest — each server adds tools and prompt overhead your local model has to reason over.
