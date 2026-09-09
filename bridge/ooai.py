"""LOFFICE IN-RIBBON AI — ONLYOFFICE's own AI plugin, pointed at OUR local runner.

WHAT THIS IS. `scripts/install_oo_ai_plugin.sh` unzips ONLYOFFICE's own `ai.plugin`
deploy archive into `data/onlyoffice-plugins/` (`ai/` = the plugin, `v1/` = the
shared plugin SDK it loads as `./../v1/*`, a SIBLING). This module is the ONLY
thing that reads that directory: it decides whether the plugin is installed,
resolves a request path inside it with the same containment discipline as `oo.py`,
and — the interesting half — computes the SEED that makes the plugin talk to our
runner instead of to OpenAI.

⚠️ THE FOUR THINGS THAT MAKE THIS WORK AT ALL, ALL FOUR MEASURED, NOT ASSUMED
(2026-08-28; the recon that scoped this slice left every one of them open).

1. THE VENDORED CRYPTPAD BUNDLE STILL HAS ITS PLUGIN MACHINERY. The recon's blocking
   question was whether the CryptPad editor build strips plugin loading. It does not:
   `web-apps/apps/*/main/app.js` carries `pluginsData`, `getPlugins`,
   `asc_pluginsRegister`, `onPluginToolbarMenu` and
   `Common.UI.LayoutManager.addCustomControls` (the thing that draws a plugin's own
   ribbon tab), and `sdkjs/*/sdk-all-min.js` carries `pluginMethod_AddToolbarMenuItem`
   plus the three events this plugin declares (`onAIPluginSettings`,
   `onContextMenuShow`, `onToolbarMenuClick`). CryptPad's `api.js` wrapper deep-merges
   our config and hands it to the real `api-orig.js`, whose `_init` posts the WHOLE
   `editorConfig` into the editor iframe. So `editorConfig.plugins.pluginsData` is a
   live surface in OUR build. Nothing was patched to get there.

2. THE DEPLOY ZIP IS RELATIVE; THE REPO WORKING COPY IS NOT. The repo's
   `content/ai/index.html` loads `https://onlyoffice.github.io/sdkjs-plugins/v1/plugins.js`. Under
   COOP/COEP (which the editor REQUIRES — see oo.py) a cross-origin subresource with
   no CORP is refused, and on an offline machine it is unreachable regardless. The
   `deploy/ai.plugin` archive of the same plugin uses `./../v1/plugins.js`. That single
   difference is why this can be served UNMODIFIED, and the installer fails loudly if
   a future pin regresses it.

3. `Asc.plugin.info.aiPluginSettings` IS NOT OUR ROUTE. The plugin does support a
   host-provided settings blob — but sdkjs only ever fills it from a DocumentServer
   licence message and then FORCES `data.proxy = <baseUrl>/../../../../ai-proxy`, i.e.
   every AI request would be posted to a proxy endpoint that does not exist in a
   serverless bundle. Using it would produce a plugin that looks configured and cannot
   answer. So we do not.

4. THE PLUGIN IFRAME IS SAME-ORIGIN WITH US, SO ITS OWN SETTINGS STORE IS WRITABLE.
   The plugin persists providers/models in `window.localStorage` under two keys
   (`onlyoffice_ai_plugin_storage_key`, `onlyoffice_ai_actions_key`) — that is what its
   Settings UI writes too. We serve the plugin from the bridge, so its iframe shares
   our origin and our glue page can write those keys BEFORE the editor starts. That is
   the registration path: published storage format, no plugin bytes touched, and no
   asking sample to upload a provider file through a Settings dialog.

⚠️ THE `/v1` GOES IN THE URL, NOT IN THE ADDON, AND THAT IS A BUG WE ROUTE AROUND.
The plugin's provider model is `(name, url, key, addon)` and it appends `"/" + addon`
when building an endpoint. But `AI.Storage.save` never persists `addon`, and
`AI.createProviderInstance` DROPS the addon argument for a provider whose name is not
one of its built-ins (`return new AI.Provider(name, url, key)` — three arguments). A
seed that put `v1` in `addon` would therefore work until the plugin next saved its own
settings and then quietly start POSTing to `/chat/completions` at the server root.
So the seed bakes `/v1` into `url` and leaves `addon` empty, which is stable across
the plugin's own save/load cycle. `AI.Endpoints`/`getEndpointUrl` then produce
`<url>/chat/completions`, `<url>/models`, … — the OpenAI wire llama.cpp serves.

HONESTY. `runner_state()` probes the runner and the seed carries a model id ONLY when
the runner actually answered with one. When it did not, `installed` may still be true
(the plugin IS vendored) but `runner.ok` is false with a reason, the seed carries NO
action bindings, and the glue page says so instead of loading a tab whose every button
would fail. A configured-looking AI tab with no working model is exactly the
LIE-TO-USER this lane keeps being asked not to ship.
"""
from __future__ import annotations

import json
import os

# ── the vendored layout ──────────────────────────────────────────────────────
STAMP_NAME = "INSTALLED"
SOURCES_NAME = "SOURCES.txt"
INSTALLER = "scripts/install_oo_ai_plugin.sh"

PLUGIN_DIR_NAME = "onlyoffice-plugins"
# ⚠️ `ai/` DIRECTLY UNDER THE SERVED ROOT, NEXT TO `v1/` — FORCED BY THE PLUGIN, not
# a mirror of the repository path (`sdkjs-plugins/content/ai`). index.html loads the
# SDK as `./../v1/plugins.js`, which resolves ONE level above the plugin folder, so a
# `content/ai/` layout makes the editor ask for `/ooplug/content/v1/plugins.js`. That
# 404s, `window.Asc.plugin` is then undefined inside the plugin frame, the plugin's
# init throws where nobody can see it, and the AI tab never appears. Measured live.
CONFIG_REL = "ai/config.json"

# The files the editor cannot load the plugin without. Checked on disk rather than
# trusted from the stamp — a stamp with no index.html beside it is a half install.
REQUIRED = (
    CONFIG_REL,
    "ai/index.html",
    "ai/scripts/engine/local_storage.js",
    "ai/scripts/engine/providers/provider.js",
    "v1/plugins.js",
    "v1/plugins-ui.js",
    "v1/plugins.css",
)

# ── the plugin's own published storage contract ──────────────────────────────
# Read out of the vendored source, not invented:
#   scripts/engine/storage.js      AI.Storage.Version = 4
#   scripts/engine/local_storage.js  localStorageKey, and the exact save() shape
#   scripts/engine/register.js     actions_key, AI.ActionType, ActionsLoad reads .model
#   scripts/engine/providers/base.js  AI.CapabilitiesUI bit flags
# ⚠️ STORAGE_VERSION IS A FENCE, NOT A DECORATION. `AI.Storage.load` throws the whole
# object away when `version` differs, so a plugin bump that changes it makes our seed
# inert — which is the SAFE failure (the plugin comes up unconfigured and says so)
# rather than the dangerous one. test_oo_ai_lane.py asserts this constant against the
# vendored file when the plugin is installed, so a bump cannot pass unnoticed.
STORAGE_KEY = "onlyoffice_ai_plugin_storage_key"
ACTIONS_KEY = "onlyoffice_ai_actions_key"
STORAGE_VERSION = 4

CAP_CHAT = 0x01
CAP_CODE = 0x40
# What a local llama.cpp text model can honestly do through this plugin: chat and
# code. NOT image generation, NOT vision, NOT OCR — those actions are deliberately
# left unbound so the plugin's own UI shows them as having no model.
SEED_CAPABILITIES = CAP_CHAT | CAP_CODE
SEED_ACTIONS = ("Chat", "Summarization", "Translation", "TextAnalyze")

# The provider name the user sees in the plugin's model list. Ours, deliberately —
# calling it "LM Studio" (a built-in whose class we could have borrowed) would have
# saved nothing and lied about what is answering.
PROVIDER_NAME = "MOT Deck (local)"

ATTRIBUTION = {
    "name": "ONLYOFFICE AI plugin (sdkjs-plugins/content/ai)",
    "licence": "AGPL-3.0",
    "licence_url": "https://www.gnu.org/licenses/agpl-3.0.html",
    "note": ("The in-ribbon AI tab is unmodified upstream ONLYOFFICE, vendored from "
             "their own deploy archive and served read-only. MOT Deck configures it "
             "through its published settings storage and points it at this machine's "
             "own runner; no request leaves the machine."),
    "sources": [
        {"what": "the plugin (vendored deploy archive)",
         "url": "https://github.com/ONLYOFFICE/onlyoffice.github.io"},
        {"what": "ONLYOFFICE plugin SDK (sdkjs-plugins/v1)",
         "url": "https://github.com/ONLYOFFICE/onlyoffice.github.io/tree/master/sdkjs-plugins/v1"},
    ],
}


# ── paths + containment ──────────────────────────────────────────────────────
def plug_dir(root) -> str:
    """Where the vendored plugin lives. NOT created on demand: its absence is the
    signal that the installer has not run."""
    return os.path.join(str(root), "data", PLUGIN_DIR_NAME)


def stamp_path(root) -> str:
    return os.path.join(plug_dir(root), STAMP_NAME)


def read_stamp(root) -> dict:
    """The installer's `key value` lines as a dict. Total — never raises."""
    out = {}
    try:
        with open(stamp_path(root), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or " " not in line:
                    continue
                key, _, value = line.partition(" ")
                if key and key.isascii() and len(out) < 64:
                    out[key] = value.strip()[:400]
    except OSError:
        return {}
    return out


def plugin_target(root, rel):
    """(abs_path, None) or (None, reason) for a /ooplug/* request.

    Identical rule to oo.bundle_target, for the identical reason: the path comes off
    the wire. realpath containment strictly under data/onlyoffice-plugins, so neither
    `..` nor a symlink planted in the archive can address a byte outside it.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None, "no file requested"
    if "\x00" in rel:
        return None, "refused: that is not a file name"
    rel = rel.lstrip("/")
    base = os.path.realpath(plug_dir(root))
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        return None, "refused: that path is outside the plugin bundle"
    if not os.path.isfile(target):
        return None, "no such file in the plugin bundle"
    return target, None


def install_state(root) -> dict:
    """Is the in-ribbon AI plugin available, at which pin, and how do I install it?

    Same shape discipline as oo.install_state: `installed` false ALWAYS carries a
    reason a human can act on plus the command that fixes it, because the glue page
    branches on this and a dead ribbon tab is worse than no ribbon tab.
    """
    base = plug_dir(root)
    stamp = read_stamp(root)
    missing = [rel for rel in REQUIRED if not os.path.isfile(os.path.join(base, rel))]
    if not os.path.isdir(base):
        reason = "the ONLYOFFICE AI plugin has not been installed yet"
    elif not stamp:
        reason = ("the plugin directory exists but there is no INSTALLED stamp — "
                  "the install did not finish")
    elif missing:
        reason = (f"the stamp is there but {len(missing)} required file(s) are not, "
                  f"starting with {missing[0]}")
    else:
        reason = ""
    return {
        "installed": not reason,
        "reason": reason,
        "installer": INSTALLER,
        "dir": base,
        "config_url": "/ooplug/" + CONFIG_REL,
        # The companion entry that keeps upstream's toolbar code from throwing — see
        # the SHIM block below. It rides in the same pluginsData list.
        "shim_url": "/api/oo/ai/" + SHIM_REL,
        "guid": stamp.get("plugin_guid", ""),
        "version": stamp.get("plugin_version", ""),
        "commit": stamp.get("commit", ""),
        "plugin_sha256": stamp.get("plugin_sha256", ""),
        "installed_at": stamp.get("date", ""),
        "files": stamp.get("files", ""),
        "attribution": ATTRIBUTION,
    }


# ── the runner, and the model it is ACTUALLY serving ─────────────────────────
def runner_state(cfg_fn, probe_fn) -> dict:
    """{ok, reason, base_url, key, model} for the local runner.

    Both dependencies are INJECTED — `cfg_fn()` returns the parsed motdeck.yaml and
    `probe_fn(port)` answers with the model id the runner reports (or None). That is
    not ceremony: it is what lets test_oo_ai_lane.py exercise "runner down", "runner
    up with nothing loaded" and "runner up" without a runner, and it keeps this file
    from importing the model lane (which imports the world).

    ⚠️ THE MODEL ID IS THE ONE THE RUNNER REPORTS, NOT motdeck.yaml's. `runner.model`
    records INTENT — the same distinction core/modelid.py was written for. Putting the
    intended id on the wire is how you get a 404 from a runner that is serving
    something else, and the plugin would surface that as an opaque failure inside a
    ribbon dropdown.
    """
    try:
        cfg = cfg_fn() or {}
    except Exception:                                             # noqa: BLE001
        cfg = {}
    rc = (cfg.get("runner") or {}) if isinstance(cfg, dict) else {}
    if not isinstance(rc, dict):
        rc = {}
    try:
        port = int(rc.get("port") or 0)
    except (TypeError, ValueError, OverflowError):
        port = 0
    key = str(rc.get("api_key") or "")
    if not 1 <= port <= 65535:
        return {"ok": False, "base_url": "", "key": "", "model": "",
                "reason": "motdeck.yaml does not give the runner a port"}
    base_url = f"http://127.0.0.1:{port}/v1"
    try:
        model = probe_fn(port)
    except Exception:                                             # noqa: BLE001
        model = None
    if not model:
        return {"ok": False, "base_url": base_url, "key": key, "model": "",
                "reason": ("the local runner is not answering on "
                           f"127.0.0.1:{port} (or has no model loaded)")}
    try:
        ctx = int(rc.get("ctx_size") or 0)
    except (TypeError, ValueError, OverflowError):
        ctx = 0
    return {"ok": True, "base_url": base_url, "key": key, "model": str(model),
            "ctx_size": ctx, "reason": ""}


# ── the seed ─────────────────────────────────────────────────────────────────
# The plugin's own input buckets (scripts/engine/providers/base.js AI.InputMaxTokens).
# It chops a long document into chunks against this number, so a value larger than the
# runner's real window turns a long summarization into a context overflow rather than
# into more chunks.
_INPUT_BUCKETS = (4096, 8192, 16384, 32768, 65536, 131072, 204800, 262144)


def max_input_tokens(runner: dict) -> int:
    """PURE. The INPUT cap to declare for the seeded model.

    ⚠️ HALF THE RUNNER'S CONTEXT, FLOORED TO ONE OF THE PLUGIN'S BUCKETS, and the
    halving is the honest part: `ctx_size` is the WHOLE window, shared by the prompt
    AND the completion, while this number is what the plugin will happily fill with
    input alone. Declaring the full window would make a long "Summarize" request
    overflow instead of chunking. With motdeck.yaml's 65536 this lands on 32768, which
    is also the plugin's own default — so today it changes nothing and it stops being
    a lie the moment the runner is started with a different window.
    """
    try:
        ctx = int((runner or {}).get("ctx_size") or 0)
    except (TypeError, ValueError, OverflowError):
        ctx = 0
    if ctx <= 0:
        return _INPUT_BUCKETS[3]        # 32k — the plugin's own default
    half = ctx // 2
    # Small supported windows (1024+) need a smaller cap than the first bucket.
    # The pinned plugin reserves 500 tokens for chunk headers; <=500 can reset
    # its cap or produce zero-length chunks. Keep the cap above that boundary.
    best = max(501, min(_INPUT_BUCKETS[0], half))
    for b in _INPUT_BUCKETS:
        if b <= half:
            best = b
    return best
def seed(runner: dict, provider_name: str = PROVIDER_NAME) -> dict:
    """PURE. The two localStorage values that register our runner with the plugin.

    Returns {"storage_key", "storage", "actions_key", "actions"} — or, when the runner
    is not usable, storage/actions of None, which the glue page must treat as "do not
    write anything and tell the user why". Writing a provider with an empty model id
    would give the plugin a model called "" in its dropdown: a configured-looking
    surface that answers every request with a 400.
    """
    model = str((runner or {}).get("model") or "")
    if not (runner or {}).get("ok") or not model:
        return {"storage_key": STORAGE_KEY, "storage": None,
                "actions_key": ACTIONS_KEY, "actions": None}
    prov = {
        "name": provider_name,
        # /v1 baked in — see this module's header for why it cannot live in `addon`.
        "url": str(runner.get("base_url") or ""),
        "key": str(runner.get("key") or ""),
        # ⚠️ THE PROVIDER'S OWN `models` LIST IS NOT OPTIONAL, AND AN EMPTY ONE IS A
        # CRASH. `AI.Request`'s constructor sets `this.model` ONLY by matching the
        # chosen model id against `provider.models`; left empty it stays null, and the
        # next line of the request path — `provider.getChatCompletions(body, model)` →
        # `model.id` — throws "null is not an object". MEASURED LIVE: the chat window
        # said "Error: [provider]" and NO request ever reached the runner, because
        # upstream's `_wrapRequest` swallows that throw. The plugin's Settings UI fills
        # this list from a real GET /v1/models; we fill it with the one model the runner
        # reported, in the shape `AI.getModels` produces.
        "models": [{
            "id": model,
            "name": model,
            # Empty on purpose. The engine reads this only to decide whether a model
            # wants /completions INSTEAD OF /chat/completions; "no opinion" is the
            # right answer for an OpenAI-compatible llama.cpp, and it then uses
            # /chat/completions, which is what the runner serves.
            "endpoints": [],
            "options": {"max_input_tokens": max_input_tokens(runner)},
        }],
    }
    storage = {
        "version": STORAGE_VERSION,
        "providers": {provider_name: prov},
        "models": [{"name": model, "id": model, "provider": provider_name,
                    "capabilities": SEED_CAPABILITIES}],
        "customProviders": {},
    }
    actions = {name: {"model": model} for name in SEED_ACTIONS}
    return {"storage_key": STORAGE_KEY, "storage": storage,
            "actions_key": ACTIONS_KEY, "actions": actions}


def status(root, cfg_fn, probe_fn) -> dict:
    """The whole /api/oo/ai/status body: install state + runner + seed, one call.

    One route rather than three because the glue page needs all of it before it may
    construct the editor, and three round trips is three chances to open an editor
    with half a decision made.
    """
    state = install_state(root)
    runner = runner_state(cfg_fn, probe_fn)
    body = dict(state)
    body["runner"] = runner
    body["seed"] = seed(runner)
    # The single sentence the glue page shows when the tab is NOT going to work.
    if not state["installed"]:
        body["gate"] = state["reason"]
    elif not runner["ok"]:
        body["gate"] = (runner["reason"]
                        + " — the AI tab is left out rather than shown with nothing "
                          "behind it. Start the runner and reopen the document.")
    else:
        body["gate"] = ""
    body["enabled"] = bool(state["installed"] and runner["ok"])
    return body


# ── THE SECOND CHANNEL, AND IT IS NOT BELT-AND-BRACES: IT IS THE RACE FIX ────
#
# ⚠️ MEASURED UPSTREAM RACE (live WKWebView, 2026-08-28). `editorConfig.plugins`
# alone is NOT enough, and the failure is silent. The plugins controller loads two
# lists and merges them:
#
#     loadPlugins: configPlugins.plugins = serverPlugins.plugins = undefined
#                  if (config)  getPlugins(config.pluginsData).then(→ mergePlugins)
#                  loadConfig("../../../../plugins.json", cb)
#                      cb: ok    → getPlugins(...).then(→ mergePlugins)
#                          error → serverPlugins.plugins = false   ← NO mergePlugins
#
# and `mergePlugins` no-ops while EITHER list is still `undefined`. So when the
# config list resolves BEFORE the server fetch fails, mergePlugins runs too early,
# the error branch never calls it again, and the plugin is fetched, parsed, and then
# never registered. Measured exactly that: `configPlugins.plugins` a 1-element array,
# `serverPlugins.plugins === false`, `autostart === []`, the Plugins collection EMPTY,
# ZERO console errors, and a hidden `plugins` ribbon tab that never becomes visible.
# Calling mergePlugins by hand in the same session registered the plugin, which is the
# proof that nothing else was wrong.
#
# The fix is to make the server list SUCCEED instead of erroring, because then
# whichever of the two resolves LAST calls mergePlugins with both defined — and both
# orders are then correct. `plugins.json` is upstream's own documented server-side
# plugin list; the vendored bundle simply does not ship one (CryptPad has no plugins),
# so the request 404s. We answer it, with generated JSON, from the route.
#
# ⚠️ AND IT IS STILL AN UNMODIFIED BUNDLE. Not one vendored byte changes: the file is
# not written to disk, so `install_onlyoffice.sh`'s `rm -rf` cannot lose it and a
# checksum of data/onlyoffice still matches the pin. This is the editor asking its
# host for configuration and the host answering — the same character as
# `editorConfig`, over a different transport. The route serves it ONLY when the
# vendored bundle has no plugins.json of its own (a future bump that ships one wins),
# and ONLY when the AI tab is actually enabled.
SERVER_LIST_REL = "dist/v9/plugins.json"


# ── THE COMPANION ENTRY, AND IT IS AN UPSTREAM CRASH WORKAROUND ──────────────
#
# ⚠️ SECOND MEASURED UPSTREAM BUG (live WKWebView, 2026-08-28), and this one throws.
# `Common.Controllers.Plugins.onResetPlugins` sorts each plugin into one of three
# branches — background / has-its-own-tab / ordinary — and creates the ribbon's
# "Background plugins" button ONLY from inside the ORDINARY branch:
#
#     collection.each(plugin => {
#        if (plugin.isBackgroundPlugin)  backgroundPlugins.push(plugin)     ← AI plugin
#        else if (plugin.tab)            …its own tab…
#        else { …|| (group = addBackgroundPluginsButton(group)) …           ← the ONLY
#               createPluginButton(plugin) … }                               creator
#     })
#     if (backgroundPlugins.length > 0) viewPlugins.backgroundBtn.show();   ← THROWS
#
# The ONLYOFFICE AI plugin is `"type": "background"`, so a plugin list containing ONLY
# it takes the first branch every time, `backgroundBtn` is never created, and the
# `.show()` on the last line is a TypeError. That aborts `collection.reset()` — and
# therefore aborts `parsePlugins` BEFORE it reaches `asc_pluginsRegister`, so sdkjs
# never learns the plugin exists and the autostart runs against an empty manager.
#
# ⚠️ AND IT IS COMPLETELY SILENT. The throw happens inside a `.then()` whose chain ends
# in `.catch(e => serverPlugins.plugins = false)` — upstream's own catch swallows it.
# Measured symptom set: collection length 1, `isBackgroundPlugin: true`,
# `autostart` populated, `g_asc_plugins.plugins` EMPTY, no plugin iframe, no AI tab,
# and ZERO console errors in the editor frame. This cost the slice four probe runs to
# corner, which is why all of it is written down here.
#
# Upstream never hits it because ONLYOFFICE's marketplace list always carries ordinary
# plugins next to the AI one. So we supply exactly what the code needs and nothing
# more: ONE ordinary (non-background, no-tab) entry, whose `EditorsSupport` is EMPTY so
# that upstream's own visibility rule (`_.contains(EditorsSupport, editorType)`) makes
# it INVISIBLE — `createPluginButton` returns null for an invisible plugin, and it is
# called AFTER `addBackgroundPluginsButton`. Net effect: the button gets created, no
# junk button appears in the ribbon, the AI plugin registers, and the crash is gone.
#
# THIS IS OUR OWN FILE, NOT A PATCHED ONE. It is generated here and served from our own
# route; nothing in the vendored bundle or the vendored plugin is touched, and no
# second plugin is downloaded from anywhere. Its `url` is never fetched (an invisible
# plugin is never run), which is why it can name an index.html that does not exist.
SHIM_GUID = "asc.{6D0F5B2A-4C1E-4E7B-9F2A-7C4A5B3D8E01}"
SHIM_REL = "shim/config.json"


def shim_config() -> dict:
    """PURE. The companion plugin descriptor. See the block above for WHY it exists.

    `description` is written for a human reading a network log or the plugin manager,
    because that is the only place it can ever appear.
    """
    return {
        "name": "MOT Deck plugin host",
        "guid": SHIM_GUID,
        "version": "1.0.0",
        "minVersion": "8.2.0",
        "variations": [{
            "description": ("Not a feature. MOT Deck registers this invisible entry so "
                            "that ONLYOFFICE's own toolbar code creates its "
                            "'Background plugins' button, which it otherwise only does "
                            "when the plugin list contains a non-background plugin — "
                            "and the AI plugin is a background plugin. Without it the "
                            "editor throws while registering plugins and the AI tab "
                            "never appears."),
            "url": "index.html",
            "icons": "",
            "isViewer": False,
            # EMPTY ON PURPOSE: this is what makes the entry invisible in every editor.
            "EditorsSupport": [],
            "type": "window",
            "initDataType": "none",
            "buttons": [],
            "events": [],
        }],
    }


def server_plugins_json(enabled: bool, guid: str, config_url: str = "",
                        shim_url: str = "") -> "dict | None":
    """PURE. The body for the vendored bundle's own `plugins.json` request, or None.

    None means "let the 404 happen": with the AI tab gated off there is nothing to
    register, and an empty pluginsData would still switch the ribbon's Plugins tab on.
    """
    if not enabled:
        return None
    url = config_url or ("/ooplug/" + CONFIG_REL)
    body = {"pluginsData": [url, shim_url or ("/api/oo/ai/" + SHIM_REL)]}
    if guid:
        # ⚠️ THE GUID IS ALSO IN editorConfig.plugins.autostart, so mergePlugins ends up
        # with it TWICE. Harmless and checked: runAutoStartPlugins() shifts ONE guid per
        # call, and a second run() of an already-running background plugin returns false
        # without closing it. Both channels keep their own autostart so that either can
        # be removed without a silent regression.
        body["autostart"] = [guid]
    return body


def vendored_storage_version(root) -> "int | None":
    """The `AI.Storage.Version` the VENDORED plugin actually uses, or None.

    Exists so the suite can catch a plugin bump that moves the fence out from under
    STORAGE_VERSION — the failure mode that would silently un-register the runner.
    Deliberately a dumb scan of one small file rather than a parser.
    """
    path = os.path.join(plug_dir(root), "ai", "scripts", "engine", "storage.js")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    marker = "AI.Storage.Version"
    at = text.find(marker)
    if at < 0:
        return None
    tail = text[at + len(marker):at + len(marker) + 32]
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def plugin_guid(root) -> str:
    """The guid out of the VENDORED config.json (empty when unreadable).

    The autostart list is keyed on it, and a stale guid means a plugin that loads and
    never starts — so the value comes from the file, never from a constant here.
    """
    try:
        with open(os.path.join(plug_dir(root), CONFIG_REL),
                  encoding="utf-8", errors="replace") as fh:
            return str(json.load(fh).get("guid") or "")
    except (OSError, ValueError):
        return ""
