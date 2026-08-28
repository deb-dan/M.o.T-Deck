#!/usr/bin/env python3
"""LOFFICE — the IN-RIBBON AI TAB (2026-08-28, loffice-2026-08-29a).

ONLYOFFICE's OWN AI plugin, vendored unmodified and pointed at THIS machine's runner.
Read bridge/ooai.py's header first: it records the six measurements this slice is built
on, four of which are workarounds for upstream behaviour that fails SILENTLY. Those are
exactly what this file exists to pin, because every one of them looks like "nothing
happened" rather than like an error:

1. THE INSTALLER'S PINS AND ITS TWO LAYOUT GUARDS. The pin is a repository COMMIT plus
   a sha256 per file (upstream publishes from a branch, so a tag cannot be the pin).
   And the two `die` guards are load-bearing, not paranoia: the plugin can only be
   served UNMODIFIED because its DEPLOY archive references the shared SDK RELATIVELY,
   and it can only find that SDK if it is unzipped as `<dest>/ai/` NEXT TO
   `<dest>/v1/`. Both were learned the hard way and both fail silently if broken.

2. THE MODULE'S DECISIONS, PURE. install_state's honest "not installed" reasons,
   realpath containment for /ooplug/*, and the SEED — including the two shapes whose
   absence produced a working-looking AI tab that could not answer: an empty
   `provider.models` (crash before any request) and a `/v1` in `addon` instead of in
   `url` (POSTs to the server root after the plugin's first self-save).

3. THE GATE. Plugin missing, runner down, or runner loaded with nothing ⇒ `enabled`
   false, NO seed, NO plugins config, a sentence saying why. A configured-looking AI
   tab with nothing behind it is the LIE-TO-USER this lane keeps being told not to
   ship, and it is cheaper to pin than to re-litigate.

4. THE ROUTES. Same three isolation headers as the rest of the lane — the plugin runs
   in an iframe INSIDE the cross-origin-isolated editor frame, so a plugin asset
   without CORP does not load slowly, it does not load at all.

5. THE GLUE PAGE. `customization.plugins` must be COMPUTED (it was a hard `false` for
   the whole life of the embed, which is why nothing loaded), the seed must be written
   BEFORE the editor is constructed, the pluginsData list must carry BOTH entries, and
   a gated tab must pass no plugins config at all.

6. ⚖️ THE AGPL ATTRIBUTION for a SECOND vendored artefact — named on the editor
   footer and in LOffice's Help → About, single-sourced from ooai.ATTRIBUTION.

Run: python3 bridge/tests/test_oo_ai_lane.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from bridge import ooai                                          # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name + ((" | " + str(extra)[:300]) if extra else ""))


def eq(name, got, want):
    check(name, got == want, f"got {got!r} want {want!r}")


# ══ 1. THE INSTALLER ═════════════════════════════════════════════════════════
SCRIPT = ROOT / "scripts" / "install_oo_ai_plugin.sh"
check("scripts/install_oo_ai_plugin.sh exists", SCRIPT.is_file())
check("…and is executable (a scripts/*.sh at mode 644 is how the Aider Install "
      "button did nothing at all)", os.access(SCRIPT, os.X_OK))
r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
check("…and is syntactically clean under bash -n", r.returncode == 0, r.stderr)

SRC = SCRIPT.read_text()
eq("the module and the script agree on the installer path",
   ooai.INSTALLER, "scripts/install_oo_ai_plugin.sh")
check("it is NOT a component — no port, no manifest key, no venv, no registry row",
      "flip_installed" not in SRC and "uv venv" not in SRC
      and "harness.yaml" not in SRC)
check("it is its OWN installer, not folded into install_onlyoffice.sh — separate "
      "upstream, separate pin, separate licence line",
      "install_onlyoffice.sh" in SRC and "PLUGIN_SHA256=" in SRC)

# The pin: a commit AND a hash for every file. A tag cannot be the pin here because
# upstream publishes the plugin from a branch.
PLUGIN_SHA = "5e98cc51659cdf3fd0edcdf076137893575f4840a5fa6dcb2f460f93c8669c43"
check("the plugin archive is pinned by sha256", f'PLUGIN_SHA256="{PLUGIN_SHA}"' in SRC)
check("…and by the repository COMMIT it was taken from, not by a branch name",
      'COMMIT="799b28724a69d29bcb0a31bffc00c9b173867b54"' in SRC
      and "${COMMIT}" in SRC)
check("every one of the three shared-SDK files is pinned by sha256 too",
      SRC.count("SDK_SHA_plugins") >= 6)
check("an unpinned SDK file is refused rather than fetched",
      'no pinned hash for SDK file' in SRC)
check("the sha256 is verified BEFORE the unzip, not after",
      SRC.index("fetch_verified ") < SRC.index("unzip -q -o"))
check("a mismatch is a hard failure, never a warning",
      'die "sha256 MISMATCH' in SRC)
check("OOP_OFFLINE means a missing or mismatching file is an ERROR, never a download",
      "OOP_OFFLINE" in SRC and SRC.count("OOP_OFFLINE") >= 3)

# ⚠️ THE TWO GUARDS. Both encode a measurement; both prevent a SILENT failure.
check("GUARD 1: an index.html that loads the SDK from onlyoffice.github.io is REFUSED "
      "— a COEP page cannot load it and an offline Mac cannot reach it",
      'grep -q "onlyoffice\\.github\\.io"' in SRC and "Do not ship this pin" in SRC)
check("GUARD 2: an index.html that does not reference ./../v1/plugins.js is REFUSED — "
      "the served layout would no longer match the plugin",
      "v1/plugins\\.js" in SRC and "no longer matches the plugin" in SRC)
check("the guards explain that the deploy archive is what makes UNMODIFIED possible",
      "UNMODIFIED" in SRC and "deploy" in SRC)
check("the layout is <dest>/ai next to <dest>/v1, and the reason is written down",
      'PLUGIN_CONFIG_REL="ai/config.json"' in SRC
      and 'AIDIR="$DEST/ai"' in SRC
      and "ONE level above" in SRC)
check("the guid the glue page autostarts on is verified against the vendored "
      "config.json rather than trusted", "got_guid" in SRC and "PLUGIN_GUID" in SRC)
check("⚖️ AGPL: SOURCES.txt is written NEXT TO the vendored plugin, with the licence, "
      "the upstream URLs and the hashes",
      "SOURCES.txt" in SRC and "AGPL-3.0" in SRC and "sha256" in SRC
      and "CC-BY-SA" in SRC)

# EXECUTED. A decoy archive with real zip bytes and the wrong content: the gate must
# reject on the HASH, not on the format — and with OOP_OFFLINE set, a mismatch can
# never turn into a download inside a test.
work = tempfile.mkdtemp(prefix="ooai-lane-")
try:
    cache = os.path.join(work, "zips")
    fake_root = os.path.join(work, "root")
    dest = os.path.join(fake_root, "data", "onlyoffice-plugins")
    os.makedirs(cache)
    os.makedirs(dest)
    with zipfile.ZipFile(os.path.join(cache, "ai.plugin"), "w") as z:
        z.writestr("decoy.txt", "not the vendored plugin")
    env = dict(os.environ, OOP_DEST=dest, OOP_ZIP_DIR=cache, OOP_OFFLINE="1")
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
    check("EXECUTED: a wrong-hash ai.plugin is REFUSED", r.returncode != 0,
          (r.stdout + r.stderr)[-300:])
    check("…and the refusal names the hash mismatch, not the format",
          "MISMATCH" in (r.stdout + r.stderr))
    check("…and nothing was unzipped", not os.path.isdir(os.path.join(dest, "ai")))
    check("…and no INSTALLED stamp was written",
          not os.path.isfile(os.path.join(dest, "INSTALLED")))

    # --check on a dir with no stamp must EXIT NON-ZERO and say so, because the panel
    # and ship.sh both branch on that.
    r = subprocess.run(["bash", str(SCRIPT), "--check"], capture_output=True,
                       text=True, env=env)
    check("--check on a plugin-less directory exits non-zero and says 'not installed'",
          r.returncode != 0 and "not installed" in r.stdout, r.stdout[-200:])

    # ══ 2. install_state — the honest "not installed" ladder ═════════════════
    st = ooai.install_state(fake_root)
    check("a directory with no stamp is NOT installed", st["installed"] is False)
    check("…and the reason says the install did not finish",
          "did not finish" in st["reason"], st["reason"])
    check("…and it always carries the installer command",
          st["installer"] == ooai.INSTALLER)
    check("…and the AGPL attribution is there whether or not it is installed",
          st["attribution"]["licence"] == "AGPL-3.0")

    shutil.rmtree(dest)
    st = ooai.install_state(fake_root)
    check("no directory at all is NOT installed", st["installed"] is False)
    check("…and the reason says it has not been installed yet",
          "not been installed" in st["reason"], st["reason"])

    # A stamp plus a PARTIAL tree is a half install, and must not read as installed.
    os.makedirs(os.path.join(dest, "ai"))
    with open(os.path.join(dest, "INSTALLED"), "w") as fh:
        fh.write("schema 1\nplugin_guid asc.{X}\n")
    st = ooai.install_state(fake_root)
    check("a stamp with a HALF tree is NOT installed (checked on disk, not trusted)",
          st["installed"] is False)
    check("…and the reason names the first missing file",
          "required file" in st["reason"] and "config.json" in st["reason"],
          st["reason"])

    # Now a complete fake tree: installed, and the stamp values surface.
    for rel in ooai.REQUIRED:
        p = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write("x")
    with open(os.path.join(dest, "INSTALLED"), "w") as fh:
        fh.write("schema 1\nplugin_guid asc.{GUID}\nplugin_version 9.9.9\n"
                 "commit deadbeef\nplugin_sha256 abc\ndate 2026-01-01T00:00:00Z\n")
    st = ooai.install_state(fake_root)
    check("a complete tree with a stamp IS installed", st["installed"] is True)
    eq("…and the reason is empty", st["reason"], "")
    eq("…and the guid comes from the stamp", st["guid"], "asc.{GUID}")
    eq("…and the config URL is the one the editor is given",
       st["config_url"], "/ooplug/ai/config.json")
    eq("…and the companion-entry URL rides along",
       st["shim_url"], "/api/oo/ai/shim/config.json")

    # ══ containment ══════════════════════════════════════════════════════════
    TRAV = ["../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "/etc/passwd",
            "ai/../../../../etc/passwd", "", "   ", None, 17, "x\x00y"]
    for bad in TRAV:
        got, reason = ooai.plugin_target(fake_root, bad)
        check(f"plugin_target refuses {bad!r}", got is None and bool(reason))
    good, reason = ooai.plugin_target(fake_root, "v1/plugins.js")
    check("plugin_target resolves a real file in the plugin bundle",
          bool(good) and reason is None)
    check("…and a leading slash is tolerated, not treated as absolute",
          ooai.plugin_target(fake_root, "/v1/plugins.js")[0] == good)
    check("a directory is refused — there is no listing and no index",
          ooai.plugin_target(fake_root, "v1")[0] is None)
    secret = os.path.join(work, "secret.txt")
    with open(secret, "w") as fh:
        fh.write("nope")
    try:
        os.symlink(secret, os.path.join(dest, "escape.js"))
        check("a symlink out of the plugin bundle is refused (realpath, not prefix)",
              ooai.plugin_target(fake_root, "escape.js")[0] is None)
    except OSError as e:                                          # noqa: BLE001
        print(f"  (symlink check skipped: {e})")
finally:
    shutil.rmtree(work, ignore_errors=True)


# ══ 3. THE SEED — pure, and every field is a measurement ═════════════════════
UP = {"ok": True, "base_url": "http://127.0.0.1:6767/v1", "key": "k",
      "model": "some-model", "ctx_size": 65536, "reason": ""}
s = ooai.seed(UP)
eq("the seed writes the plugin's OWN storage key, not one of ours",
   s["storage_key"], "onlyoffice_ai_plugin_storage_key")
eq("…and the plugin's own actions key",
   s["actions_key"], "onlyoffice_ai_actions_key")
eq("the storage version is the fence the plugin checks",
   s["storage"]["version"], ooai.STORAGE_VERSION)
prov = s["storage"]["providers"][ooai.PROVIDER_NAME]
eq("the provider URL carries /v1 IN THE URL", prov["url"], "http://127.0.0.1:6767/v1")
check("…and NOT in an `addon` field, which the plugin drops for a custom provider "
      "name and never persists",
      "addon" not in prov)
check("⚠️ the provider's own models list is NON-EMPTY — an empty one makes "
      "AI.Request leave this.model null and the next line throws on model.id",
      len(prov["models"]) == 1)
eq("…and the model id in it is the one the runner reported",
   prov["models"][0]["id"], "some-model")
eq("…with an empty endpoints list, i.e. 'no opinion' → /chat/completions",
   prov["models"][0]["endpoints"], [])
check("…and an input cap the engine can chunk against",
      prov["models"][0]["options"]["max_input_tokens"] > 0)
eq("the UI model list names the same id", s["storage"]["models"][0]["id"], "some-model")
eq("…and points at our provider", s["storage"]["models"][0]["provider"],
   ooai.PROVIDER_NAME)
eq("capabilities are chat+code — NOT image, NOT vision, NOT OCR, because a local "
   "text model cannot do those", s["storage"]["models"][0]["capabilities"],
   ooai.CAP_CHAT | ooai.CAP_CODE)
eq("exactly the four text actions are bound", sorted(s["actions"].keys()),
   sorted(ooai.SEED_ACTIONS))
check("…and image generation / OCR / vision are deliberately left UNBOUND",
      not any(k in s["actions"] for k in ("ImageGeneration", "OCR", "Vision")))
check("every bound action names the runner's model",
      all(v["model"] == "some-model" for v in s["actions"].values()))
check("the seed is PURE — calling it twice gives the same thing and mutates nothing",
      ooai.seed(UP) == s and UP["model"] == "some-model")

# The input cap: half the runner's window, floored to one of the plugin's buckets.
eq("ctx 65536 → a 32k input cap (half the window, the plugin's own default)",
   ooai.max_input_tokens({"ctx_size": 65536}), 32768)
eq("ctx 8192 → 4k", ooai.max_input_tokens({"ctx_size": 8192}), 4096)
eq("ctx 262144 → 131072", ooai.max_input_tokens({"ctx_size": 262144}), 131072)
eq("an unknown ctx falls back to the plugin's own 32k default",
   ooai.max_input_tokens({}), 32768)
eq("…and so does junk", ooai.max_input_tokens({"ctx_size": "banana"}), 32768)
check("the input cap is never larger than the window it came from",
      all(ooai.max_input_tokens({"ctx_size": c}) <= c
          for c in (4096, 8192, 16384, 32768, 65536, 131072, 262144)))

# ══ 4. THE GATE — the whole point ════════════════════════════════════════════
for name, runner in (
        ("the runner is DOWN", {"ok": False, "base_url": "u", "key": "k", "model": "",
                                "reason": "not answering"}),
        ("the runner is up with NOTHING loaded", {"ok": True, "base_url": "u",
                                                  "key": "k", "model": ""}),
        ("the runner state is junk", {}),
):
    g = ooai.seed(runner)
    check(f"{name}: the seed writes NOTHING", g["storage"] is None
          and g["actions"] is None)
    check(f"{name}: …but the key names are still there so the caller can clear them",
          bool(g["storage_key"]) and bool(g["actions_key"]))


def cfg_ok():
    return {"runner": {"port": 6767, "api_key": "kk", "ctx_size": 65536}}


st = ooai.status(ROOT / "nowhere", cfg_ok, lambda p: "m1")
check("plugin NOT installed ⇒ enabled false", st["enabled"] is False)
check("…and the gate sentence is the install reason", st["gate"] == st["reason"])
check("…and it names the installer, so the gate is actionable",
      st["installer"] == ooai.INSTALLER)

# A runner-down gate against a plugin that IS installed, using the real tree when it
# is there — this is the sentence Debi actually reads.
real = ooai.install_state(ROOT)
snap = Path(os.path.expanduser("~/Library/Application Support/Harness"))
base = ROOT if real["installed"] else (snap if ooai.install_state(snap)["installed"]
                                       else None)
if base is not None:
    st = ooai.status(base, cfg_ok, lambda p: None)
    check("plugin installed but runner DOWN ⇒ enabled false", st["enabled"] is False)
    check("…and installed stays TRUE — the two are different facts",
          st["installed"] is True)
    check("…and the gate says the runner is not answering AND what to do",
          "not answering" in st["gate"] and "Start the runner" in st["gate"], st["gate"])
    check("…and the gate promises the tab is LEFT OUT rather than shown broken",
          "left out" in st["gate"], st["gate"])
    check("…and the seed is empty", st["seed"]["storage"] is None)

    st = ooai.status(base, cfg_ok, lambda p: "live-model")
    check("plugin installed AND runner live ⇒ enabled true", st["enabled"] is True)
    eq("…and the gate sentence is empty", st["gate"], "")
    check("…and the seed carries the LIVE model id, not harness.yaml's intent",
          st["seed"]["storage"]["models"][0]["id"] == "live-model")

    # ⚠️ THE FENCE AGAINST A SILENT PLUGIN BUMP. AI.Storage.load throws our whole seed
    # away when `version` differs, and the symptom is an unconfigured AI tab with no
    # error anywhere. So the constant is checked against the VENDORED file.
    v = ooai.vendored_storage_version(base)
    eq("the vendored plugin's AI.Storage.Version is the one the seed writes",
       v, ooai.STORAGE_VERSION)
    # Same reasoning for the guid the autostart list is keyed on.
    check("the guid in the stamp is the guid in the vendored config.json",
          ooai.plugin_guid(base) == ooai.install_state(base)["guid"],
          f"{ooai.plugin_guid(base)!r} vs {ooai.install_state(base)['guid']!r}")
    # And the two things the layout finding turned into an invariant.
    idx = Path(ooai.plug_dir(base)) / "ai" / "index.html"
    if idx.is_file():
        t = idx.read_text(errors="replace")
        check("the VENDORED index.html loads the SDK relatively, never from "
              "onlyoffice.github.io (offline + COEP)",
              "./../v1/plugins.js" in t and "onlyoffice.github.io" not in t)
        check("…and the SDK really is a sibling of the plugin folder on disk",
              (Path(ooai.plug_dir(base)) / "v1" / "plugins.js").is_file())
else:
    print("  (the AI plugin is not installed anywhere reachable — the vendored-file "
          "cross-checks are SKIPPED; run ./scripts/install_oo_ai_plugin.sh)")

# ══ 5. THE COMPANION ENTRY (the upstream crash workaround) ═══════════════════
shim = ooai.shim_config()
eq("the companion entry has its own guid, never the AI plugin's",
   shim["guid"], ooai.SHIM_GUID)
check("…which is NOT ONLYOFFICE's AI guid",
      "9DC93CDB" not in shim["guid"])
eq("⚠️ its EditorsSupport is EMPTY — that is what makes it invisible, which is what "
   "keeps a junk button out of the ribbon",
   shim["variations"][0]["EditorsSupport"], [])
check("…and it is NOT a background plugin, which is the whole reason it exists",
      shim["variations"][0]["type"] != "background")
check("its description explains that it is not a feature",
      "Not a feature" in shim["variations"][0]["description"])
check("…and names the upstream behaviour it works around",
      "Background plugins" in shim["variations"][0]["description"])

body = ooai.server_plugins_json(True, "asc.{G}", "http://h/ooplug/ai/config.json",
                                "http://h/api/oo/ai/shim/config.json")
eq("the generated plugins.json lists BOTH entries", len(body["pluginsData"]), 2)
check("…the AI plugin first", "ooplug/ai/config.json" in body["pluginsData"][0])
check("…the companion second", "shim/config.json" in body["pluginsData"][1])
eq("…and it autostarts the AI plugin", body["autostart"], ["asc.{G}"])
check("every pluginsData URL ends in config.json — the loader derives baseUrl by "
      "cutting at that literal",
      all(u.endswith("config.json") for u in body["pluginsData"]))
check("with the tab gated off, plugins.json is NOT served — an empty pluginsData "
      "would still switch the ribbon's Plugins tab on",
      ooai.server_plugins_json(False, "asc.{G}") is None)
eq("the served path is the one the vendored bundle asks for",
   ooai.SERVER_LIST_REL, "dist/v9/plugins.json")
check("ooai.py explains WHY that second channel exists (the merge race), because it "
      "reads like belt-and-braces and is not",
      "RACE" in Path(ROOT / "bridge" / "ooai.py").read_text())


# ══ 6. THE ROUTES ════════════════════════════════════════════════════════════
ISO = {"Cross-Origin-Opener-Policy": "same-origin",
       "Cross-Origin-Embedder-Policy": "require-corp",
       "Cross-Origin-Resource-Policy": "same-origin"}


def iso_ok(resp):
    return all(resp.headers.get(k) == v for k, v in ISO.items())


try:
    from fastapi.testclient import TestClient
    from bridge.app import app
    cl = TestClient(app, raise_server_exceptions=False)

    r = cl.get("/api/oo/ai/status")
    eq("GET /api/oo/ai/status answers 200 installed or not", r.status_code, 200)
    b = r.json()
    for k in ("installed", "enabled", "gate", "installer", "runner", "seed",
              "attribution", "config_url", "shim_url"):
        check(f"…and the body carries {k}", k in b, sorted(b.keys()))
    check("…and the three headers — the plugin frame lives INSIDE the isolated "
          "editor frame, so an asset without CORP does not load at all", iso_ok(r),
          dict(r.headers))
    check("…and it is never cached (the runner probe is a live fact)",
          "no-store" in (r.headers.get("cache-control") or ""))
    check("…and enabled false ALWAYS comes with a gate sentence",
          b["enabled"] or bool(b["gate"]))
    check("…and the runner block never leaks a key when it is not usable",
          b["runner"]["ok"] or b["runner"]["model"] == "")
    check("⚖️ …and the AGPL attribution for the plugin is there, installed or not",
          b["attribution"]["licence"] == "AGPL-3.0"
          and any("onlyoffice.github.io" in s["url"]
                  for s in b["attribution"]["sources"]))

    r = cl.get("/api/oo/ai/shim/config.json")
    eq("GET the companion entry answers 200", r.status_code, 200)
    check("…with the three headers", iso_ok(r), dict(r.headers))
    eq("…and it is our guid", r.json()["guid"], ooai.SHIM_GUID)

    r = cl.get("/ooplug/definitely/not/here.js")
    eq("a missing plugin file is a 404", r.status_code, 404)
    check("…and even the 404 carries the headers", iso_ok(r), dict(r.headers))
    for bad in ("/ooplug/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                "/ooplug/../onlyoffice/INSTALLED",
                "/ooplug/ai/../../../../etc/passwd"):
        r = cl.get(bad)
        check(f"{bad} is refused", r.status_code in (404, 400), r.status_code)
        check("…and says nothing about what is outside the bundle",
              "passwd" not in r.text and "INSTALLED" not in r.text)

    if b["installed"]:
        r = cl.get("/ooplug/ai/config.json")
        eq("the vendored config.json is served", r.status_code, 200)
        check("…as application/json", "json" in (r.headers.get("content-type") or ""))
        check("…with the three headers", iso_ok(r), dict(r.headers))
        r = cl.get("/ooplug/v1/plugins.js")
        eq("the shared SDK is served as a SIBLING of the plugin folder — the path the "
           "plugin's own relative script tag resolves to", r.status_code, 200)
        check("…as text/javascript", "javascript" in (r.headers.get("content-type") or ""))
        # The generated server list. Only when the tab is genuinely usable.
        r = cl.get("/oo/dist/v9/plugins.json")
        if b["enabled"]:
            eq("with the tab enabled, the bundle's plugins.json is GENERATED",
               r.status_code, 200)
            check("…and lists both entries", len(r.json()["pluginsData"]) == 2,
                  r.text[:200])
            check("…with the three headers", iso_ok(r), dict(r.headers))
        else:
            eq("with the tab gated off, the bundle's plugins.json 404s as before",
               r.status_code, 404)
except Exception as e:                                            # noqa: BLE001
    check(f"the route checks could run ({type(e).__name__}: {e})", False)


# ══ 7. THE GLUE PAGE + THE ABOUT SHEET ═══════════════════════════════════════
OO = (ROOT / "bridge" / "panel" / "oo.html").read_text()
PAGE = (ROOT / "bridge" / "panel" / "office.html").read_text()

check("the glue page asks the bridge whether the AI tab can work",
      "/api/oo/ai/status" in OO and "aiPrepare" in OO)
check("…ONCE per page, not per document swap (the runner probe is a round trip)",
      "aiPrepare" in OO.split("let onceDone")[1].split("function openDoc")[0])
check("…and a 404 from an older snapshot is treated as 'no AI tab', not as an error",
      "r.status === 404" in OO and "this build has no in-ribbon AI tab" in OO)
check("⚠️ customization.plugins is COMPUTED, not the hard `false` it was for the "
      "whole life of the embed — the controller reads it first and skips loading "
      "entirely when it is false",
      "plugins: !!aiPluginsConfig()" in OO and "plugins: false," not in OO)
check("the plugins config carries BOTH pluginsData entries",
      "pluginsData: [url, shim]" in OO)
check("…and an autostart, because a background plugin never runs without one",
      "cfg.autostart = [aiStatus.guid]" in OO and "autostart" in OO)
check("a gated tab passes NO plugins config at all — an empty pluginsData would still "
      "turn the ribbon's Plugins tab on",
      "aiPluginsConfig() ? {plugins: aiPluginsConfig()} : {}" in OO)
check("the seed is written BEFORE the editor is constructed",
      OO.index("localStorage.setItem(seed.storage_key") < OO.index("new DocsAPI.DocEditor"))
check("…and a localStorage that throws costs the AI tab and NOTHING else",
      "would not let us store the AI settings" in OO)
check("the page never invents the model name — it uses the one the bridge reports",
      "aiStatus.runner" in OO and "runner.model" in OO)
check("the reason the tab is off is readable by a probe, not only by a human",
      "ai: {enabled:" in OO and "gate: aiGate" in OO)
check("…and is told to the LOffice host as well",
      "tell('ai'" in OO)
check("⚖️ the editor footer names the AI plugin + its licence when it is live, from "
      "the bridge's own ATTRIBUTION rather than retyped",
      "AI tab by" in OO and "at.licence" in OO)
check("⚖️ LOffice's Help → About names the AI plugin, its licence and its source",
      "The in-ribbon AI tab" in PAGE and "/api/oo/ai/status" in PAGE)
check("…states the licence even when the plugin is NOT installed",
      PAGE.count("not installed on this Mac") >= 2)
check("…and when the tab is OFF, About is where the reason lands",
      "Status: OFF" in PAGE and "left out of the ribbon" in PAGE)
check("…with the command that fixes it, because a limit nobody can act on is the "
      "dead-click shape one layer up",
      "Install it once with" in PAGE and "ai.installer" in PAGE)
check("…and when it is ON, About says which model answers and what is NOT bound",
      "Status: ON" in PAGE and "image generation, OCR and vision are NOT" in PAGE)
check("the old 'no plugins' limit sentence is gone — it stopped being true",
      "no chat and no plugins" not in PAGE)
check("About still says the AI PANEL is untouched and still owns the agent tools",
      "panel is unchanged" in PAGE or "AI panel on the right is unaffected" in PAGE)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("oo AI lane OK — all checks passed")
