# OpenCode: how it discovers providers, why ours was invisible, and how to check

Read out of `sst/opencode` at our pin **1.18.19** (`2b72179c663cadcb54f54d9f19221b3fb3d11fb6`),
cloned and read this session. Every claim below carries a `file:line`. Nothing here was
executed against the real binary — it is darwin-arm64 and the sandbox is Linux.

---

## 1. Which server the tab talks to, and therefore which routes matter

`opencode serve` starts the **v1** server (`packages/opencode/src/server/…`), not the
newer effect `packages/server` one. The embedded SPA decides which protocol it is
speaking by probing:

> `packages/app/src/utils/server-protocol.ts:27-30`
> ```ts
> const legacy = await probe(server, fetch, "/global/health")
> if (legacy && "healthy" in legacy && legacy.healthy === true) return "v1"
> ```

`/global/health` is defined at `packages/opencode/src/server/routes/instance/httpapi/groups/global.ts:66`
(`health: "/global/health"`), so our tab is always on **v1**. That matters: on v1 the
provider list is fetched from **`GET /provider`**, not the v2 `/api/provider`:

> `packages/app/src/context/global-sync/bootstrap.ts:232-234`
> ```ts
> if ((await protocol) === "v1" && legacy) {
>   const result = await legacy.provider.list()
>   return normalizeProviderList(result.data!)
> ```
> `packages/sdk/js/src/gen/sdk.gen.ts:759` → `url: "/provider"`

Note it is called with **no `directory`** — the server resolves it to its own cwd, which
is why we `cd` into `data/opencode-workspace` before launching.

## 2. What "connected" means — the exact predicate

> `packages/opencode/src/server/routes/instance/httpapi/handlers/provider.ts:51-60`
> ```ts
> const connected = yield* provider.list()
> const credentials = yield* authStore.all().pipe(Effect.orDie)
> const providers = Object.assign(
>   mapValues(filtered, (item) => Provider.fromModelsDevProvider(item)),
>   connected,
> )
> return {
>   all: Object.values(providers).map(Provider.toPublicInfo),
>   default: Provider.defaultModelIDs(providers),
>   connected: Object.keys(providers).filter((id) => id in connected || credentials[id]),
> }
> ```

So **a provider is "connected" iff it is in the runtime provider map** (`provider.list()`)
**or** it has a stored credential. There is *no* auth entry, no `auth.json` row and no
OAuth step required for a config-declared provider — the Connect buttons Debi saw are
only for the `popularProviders` list (`app/src/hooks/use-providers.ts:8-17`), and the
Settings page renders `connected` verbatim
(`app/src/components/settings-v2/providers.tsx:50-54, 145-165`).

A **config** provider reaches that runtime map here:

> `packages/opencode/src/provider/provider.ts:1613-1619`
> ```ts
> // load config - re-apply with updated data
> for (const [id, provider] of configProviders) {
>   const providerID = ProviderV2.ID.make(id)
>   const partial: Partial<Info> = { source: "config" }
>   …
>   mergeProvider(providerID, partial)
> }
> ```

with one hard precondition, which is worth knowing:

> `provider.ts:1684-1687`
> ```ts
> if (Object.keys(provider.models).length === 0) {
>   delete providers[providerID]
>   continue
> }
> ```
> **A provider whose `models` map is empty is deleted outright.**

## 3. Which config files are read

`Global.Path.config = path.join(xdgConfig!, "opencode")` (`packages/core/src/global.ts:10-13`),
so `XDG_CONFIG_HOME` — which `start_component.sh` exports — is exactly what redirects it.
Three global candidates are merged, in this order:

> `packages/opencode/src/config/config.ts:258-260`
> ```ts
> result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "config.json"), env))
> result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.json"), env))
> result = mergeConfig(result, yield* loadFile(path.join(Global.Path.config, "opencode.jsonc"), env))
> ```

and then the **project** file, walking up from the instance directory, merged *after*
the global one:

> `config.ts:406-409` → `ConfigPaths.files("opencode", ctx.directory, ctx.worktree)`
> `packages/opencode/src/config/paths.ts:10-21` → `targets: ["opencode.jsonc", "opencode.json"]`

Excess keys are ignored, but a **type error throws** and takes the whole global config
down to `{}` (`config/parse.ts:40-60`, caught at `config.ts:283-285`), so the file must be
schema-clean. The provider schema that governs it is
`packages/core/src/v1/config/provider.ts:82-126` — `api`, `name`, `env`, `id`, `npm`,
`whitelist`, `blacklist`, `options{apiKey,baseURL,…}`, `models`.

Upstream documents the exact provider shape we write, for llama.cpp specifically:

> `packages/web/src/content/docs/providers.mdx:1355-1376` — `npm: "@ai-sdk/openai-compatible"`,
> `name`, `options.baseURL`, `models: { "<id>": { "name": … } }`.

## 4. Two identifiers, and conflating them was a real defect

The **key** of the `models` map is the id used in every `provider/model` string; the
entry's **`id`** becomes the name sent on the wire:

> `provider.ts:1465` `const apiID = model.id ?? existingModel?.api.id ?? modelID`
> `provider.ts:1886` `sdk.languageModel(model.api.id)`
> `provider.ts:1731` `options["baseURL"] … ? options["baseURL"] : model.api.url`
> (so `options.baseURL` wins — our placement is right)

and the desktop splits `provider/model` with a **bare destructure**:

> `app/src/hooks/provider-catalog.ts:31-36`
> ```ts
> const [providerID, modelID] = legacy.split("/")
> ```

We previously keyed the map by the **wire** id. For gguf that is the registry id and it
worked; for **MLX the wire id is an absolute path**, so the key became
`/Users/…/model` and the default string `llama.cpp//Users/…` destructured to an **empty
model id**. Fixed: the key is now the (slash-free) registry id and the path lives in
`id`.

## 5. Where "Big Pickle" comes from

It is one of OpenCode's own Zen models, and it is hard-coded into the fallback sort:

> `provider.ts:2016` `const priority = ["gpt-5", "claude-sonnet-4", "big-pickle", "gemini-3-pro"]`
> `provider.ts:2002-2006`
> ```ts
> const configured = Object.keys(cfg.provider ?? {})
> const provider = Object.values(s.providers).find((p) => configured.length === 0 || configured.includes(p.id))
> ```

If `cfg.provider` had contained our entry, `configured` would be `["llama.cpp"]` and the
default would have been ours. **A composer chip reading "Big Pickle" therefore means
`cfg.provider` was empty for the server that tab was talking to** — the same single cause
as "No connected providers". The two symptoms are one fact, not two.

## 6. The Servers list, and how to recover it

It is **client state**, not ours: `Persist.global("server", …)` into localStorage
`opencode.global.dat` (`app/src/context/server.tsx:263-274`, `utils/persist.ts:28`).
But removing the current server cannot strand the page, because the served build passes
it in as a prop and `resolveServerList` seeds from props *before* merging storage:

> `app/src/entry.tsx:156-172` — `servers={[server]}` with `http.url = getCurrentUrl()`
> `app/src/context/server.tsx:148-177` — props first, stored merged over them

**Recovery: reload the tab (⌘R).** To re-add by hand, `Add server` asks for
"Server address" (placeholder `http://localhost:4096`) plus optional name / username /
password (`i18n/en.ts:354-365`) — for us the address is `http://127.0.0.1:4096` and the
other three stay **empty**: `serve` runs with no password
(`packages/server/src/routes.ts:48`, `password: Option.none()`).

## 7. Diagnostics — real routes, for Debi to run

```bash
# 1. is it even up, and which protocol will the tab pick? (expects {"healthy":true,...})
curl -s http://127.0.0.1:4096/global/health | python3 -m json.tool

# 2. THE ONE THAT MATTERS — is our provider CONNECTED?  (handlers/provider.ts:51-60)
curl -s http://127.0.0.1:4096/provider | python3 -c \
  'import json,sys; d=json.load(sys.stdin); print("connected:", d.get("connected")); \
   print("models:", list(((next((p for p in d["all"] if p["id"]=="llama.cpp"), {})) or {}).get("models", {})))'

# 3. did our config file actually reach it?  (groups/global.ts:66)
curl -s http://127.0.0.1:4096/global/config | python3 -m json.tool | head -40

# 4. the same question for the merged (global + project) config
curl -s http://127.0.0.1:4096/config | python3 -m json.tool | head -40

# 5. and what the two files on disk say
python3 -m json.tool < ~/Library/Application\ Support/MOT Deck/data/opencode/xdg/config/opencode/opencode.json | head -30
python3 -m json.tool < ~/Library/Application\ Support/MOT Deck/data/opencode-workspace/opencode.json | head -30
```

Reading them: if **(5)** shows `llama.cpp` but **(3)** does not, the XDG redirect is not
reaching the running process. If **(3)** shows it but **(2)** does not list it under
`connected`, the provider was dropped after loading — check `disabled_providers` in (3),
which is what OpenCode's own *Disconnect* button writes
(`app/src/components/settings-v2/providers.tsx:97-101`).
