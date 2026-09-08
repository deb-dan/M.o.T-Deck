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
      and "motdeck.yaml" not in SRC)
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
      and 'AIDIR="$CANDIDATE/ai"' in SRC
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
for ctx in (1024, 2048, 4096, 6000):
    eq(f"ctx {ctx} leaves half for completion below the first bucket",
       ooai.max_input_tokens({"ctx_size": ctx}), ctx // 2)
eq("ctx 262144 → 131072", ooai.max_input_tokens({"ctx_size": 262144}), 131072)
eq("an unknown ctx falls back to the plugin's own 32k default",
   ooai.max_input_tokens({}), 32768)
eq("…and so does junk", ooai.max_input_tokens({"ctx_size": "banana"}), 32768)
eq("…and nonfinite context", ooai.max_input_tokens({"ctx_size": float("inf")}), 32768)
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

for malformed in ([], "broken", {"port": float("inf")}, {"port": -1}, {"port": 65536}):
    probes = []
    state = ooai.runner_state(lambda: {"runner": malformed}, lambda p: probes.append(p))
    check(f"malformed runner {malformed!r} is unavailable without a probe",
          not state["ok"] and not probes)


st = ooai.status(ROOT / "nowhere", cfg_ok, lambda p: "m1")
check("plugin NOT installed ⇒ enabled false", st["enabled"] is False)
check("…and the gate sentence is the install reason", st["gate"] == st["reason"])
check("…and it names the installer, so the gate is actionable",
      st["installer"] == ooai.INSTALLER)

# A runner-down gate against a plugin that IS installed, using the real tree when it
# is there — this is the sentence Debi actually reads.
real = ooai.install_state(ROOT)
snap = Path(os.path.expanduser("~/Library/Application Support/MOT Deck"))
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
    check("…and the seed carries the LIVE model id, not motdeck.yaml's intent",
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


# ══ 8. THE IN-RIBBON CHAT SURVIVES A DOCUMENT SWAP, PER FILE ═════════════════
#
# Debi's finding: chat in the ribbon's Chatbot, switch file, the conversation is gone.
# Root cause is in the VENDORED plugin and it is NOT "in-memory state": chat.js DOES
# persist to localStorage, but its setState() is reachable from exactly ONE event
# (`onUpdateState`) which exactly ONE caller commands (`onDockedChanged`). A swap
# destroys the frame without ever passing through it. Our fix commands that same
# published event before destroying the editor, then MOVES the blob to a per-file key
# of ours — because the plugin's key is GLOBAL and would otherwise show A's
# conversation inside B.
#
# Every check below is a fence over something that fails SILENTLY on a plugin bump.
AI_CHAT_KEY = "onlyoffice_ai_chat_state"

check("the glue page pins the plugin's own chat key, and only that key",
      f"AI_CHAT_KEY = '{AI_CHAT_KEY}'" in OO)
check("…with the plugin version it was read from, as a fence",
      "AI_CHAT_PLUGIN_VER = '3.2.2'" in OO)
check("…and a per-FILE namespace of our own, distinct from the plugin's global key",
      "AI_CHAT_MINE = 'mot.ooai.chat.'" in OO)

check("⚠️ the conversation is flushed while the OLD editor is still alive — the plugin "
      "frame is a CHILD of the editor iframe, so one line later there is nothing to ask",
      OO.index("await aiChatHandover(wasDoc, '')")
      < OO.index("try { editor.destroyEditor(); } catch (e) { console.log"))
check("…and the INCOMING file's conversation is planted before the editor is built, "
      "because the plugin reads that key once, from its chat window's init",
      OO.index("await aiChatHandover('', want)") < OO.index("new DocsAPI.DocEditor"))
check("the flush uses the plugin's OWN published event, not a reach into its internals",
      "command('onUpdateState')" in OO)
check("⚠️ …by COMMAND + poll, never attachEvent('onUpdateState') — attaching would "
      "REPLACE the plugin's own dock-change handler, i.e. break a feature to fix one",
      "cw.attachEvent(" not in OO and "chatWindow.attachEvent(" not in OO)
check("…and it is bounded, so a plugin that never answers costs the swap and not the "
      "editor", "AI_CHAT_FLUSH_MS" in OO)
# ⚠️ A MEASURED HANG, PINNED. The first draft bounded the flush by TICK COUNT ("14
# times, 50ms apart") and called that 700ms. WebKit clamps timers hard in a window
# that is not on screen: those fourteen ticks took over THIRTY SECONDS in a live
# WKWebView, and since the swap awaits the flush, the document switch stopped dead at
# "converted to the editor format". A background tab, an occluded window and a Mac on
# battery all reach that state. Timers promise ORDER, not DURATION.
check("⚠️ …and bounded by the CLOCK, not by a tick count — a throttled timer turned a "
      "'700ms' poll into a 30-SECOND swap hang, measured live",
      "Date.now() - t0 < AI_CHAT_FLUSH_MS" in OO
      and "for (let i = 0; i < 14; i++)" not in OO)
check("…with the reason written down where the next person will edit it",
      "CLAMPS timers" in OO or "clamps timers" in OO.lower())

# ⚠️ TRAP FIVE — the one that actually destroys the conversation.
check("⚠️ the plant is HELD, not done once: the plugin's own init DELETES the chat key, "
      "so a single pre-construction write is erased by the editor it was written for",
      "function aiChatArm" in OO and "aiChatArm(want)" in OO)
check("…and the hold stops as soon as the plugin owns the key again (a chat window "
      "exists) or the document changes under it",
      "if (DOC !== name || aiChatWindow() || planted >= AI_CHAT_HOLD_MAX)" in OO)
check("…and it only ever WRITES when the key is missing — one write per wipe",
      "if (aiChatRead() !== null) return;" in OO)
# MEASURED: the wipe repeats (54 re-plants in 100 seconds with the Chatbot shut), so
# the hold is standing rather than one-shot — and therefore has to be capped.
check("…is CAPPED, so a pathological wipe loop cannot run for ever",
      "AI_CHAT_HOLD_MAX" in OO and "planted >= AI_CHAT_HOLD_MAX" in OO)
check("…and its housekeeping re-plants are counted apart from real restores — a metric "
      "that counts housekeeping as work cannot answer 'did the swap restore it'",
      "aiChatHolds" in OO and "aiChatRestores = was" in OO and "holds: aiChatHolds" in OO)
check("…and clearChatState is named in the glue page so the next reader knows why",
      "clearChatState" in OO)

check("⚠️ THE LIE-TO-USER GUARD: a file with no saved conversation CLEARS the plugin's "
      "key rather than leaving the previous file's chat in it",
      "window.localStorage.removeItem(AI_CHAT_KEY)" in OO)
check("…and a blob written by a DIFFERENT plugin version is not replayed into this one",
      "o.v === AI_CHAT_PLUGIN_VER" in OO)

check("the store is bounded by conversation size…", "AI_CHAT_MAX_BYTES" in OO)
check("…by number of documents (LRU)…", "AI_CHAT_MAX_FILES" in OO and "idx.pop()" in OO)
check("…and survives a quota, because a full localStorage would cost the PROVIDER SEED "
      "that shares it — i.e. the AI tab itself",
      "attempt < 3" in OO and "aiChatDrops" in OO)
check("a hard quit is covered too — the conversation is checkpointed on a timer while "
      "the chat is open", "AI_CHAT_AUTOSAVE_MS" in OO and "setInterval" in OO)
check("…and the residual window is five seconds, not the old twenty-second gap",
      "const AI_CHAT_AUTOSAVE_MS = 5000;" in OO
      and "every\\n'\n             + '  5 seconds" in PAGE)
check("…while every asynchronous tick remains serialised through the same handover "
      "queue as document swaps",
      "aiChatQueue = aiChatQueue.then" in OO
      and "aiChatHandover(DOC, '').catch" in OO)
check("…and only while a chat window actually exists (no idle churn)",
      "!aiChatWindow()) return" in OO)
check("the frame walk is depth-bounded and a cross-origin frame is skipped, never fatal",
      "depth > 6" in OO and OO.count("/* cross-origin */") >= 3)
check("a probe can PROVE the handover ran, instead of inferring it from a screenshot",
      "saves: aiChatSaves" in OO and "restores: aiChatRestores" in OO
      and "drops: aiChatDrops" in OO)
check("the host teardown path saves too — a swap is not the only way the frame dies",
      "destroy: async () =>" in OO and "await aiChatHandover(DOC, '')" in OO)

check("⚠️ a RENAME carries the conversation with the file — the key is the file name, "
      "so without this the user's own words are orphaned under the old one",
      "function aiChatRename" in OO
      and OO.index("aiChatRename(from, want)") > OO.index("function renameTo(to)"))
check("…and the hold is re-armed on the new name (the old one has just retired)",
      "aiChatRename(from, want); aiChatArm(want);" in OO.split("function renameTo(to)")[1])

check("Help → About tells the user the conversation is kept per file",
      "kept per file" in PAGE)
check("…and states the residual limit rather than hiding it",
      "hard quit can still cost" in PAGE)

# ── the version fence, against the VENDORED bytes ────────────────────────────
if base is not None:
    pdir = Path(ooai.plug_dir(base))
    chat_js = pdir / "ai" / "scripts" / "chat.js"
    reg_js = pdir / "ai" / "scripts" / "engine" / "register.js"
    if chat_js.is_file() and reg_js.is_file():
        CJ, RJ = chat_js.read_text(errors="replace"), reg_js.read_text(errors="replace")
        check("⚠️ the VENDORED chat.js still uses the key our handover moves",
              f'localStorageKey = "{AI_CHAT_KEY}"' in CJ, "a plugin bump renamed it")
        check("…and still restores it from its own init (which is what makes the "
              "planted blob appear)",
              "restoreState();" in CJ and "Asc.plugin.init" in CJ)
        check("⚠️ …and setState is STILL only reachable from onUpdateState — the whole "
              "reason a swap loses the chat",
              CJ.count("setState({") == 1 and 'attachEvent("onUpdateState"' in CJ)
        # ⚠️ TRAP FIVE, fenced against the vendored bytes. If a bump ever REMOVES this
        # line, the hold becomes unnecessary — harmless, but the comment in oo.html
        # would then be a lie about the current plugin, which is its own kind of debt.
        code_js = pdir / "ai" / "scripts" / "code.js"
        if code_js.is_file():
            KJ = code_js.read_text(errors="replace")
            check("⚠️ the VENDORED plugin STILL deletes its own chat state on init — the "
                  "actual cause of 'the chat vanished when I switched file'",
                  "function clearChatState()" in KJ
                  and "localStorage.removeItem(key)" in KJ
                  and "clearChatState();" in KJ)
        check("the VENDORED register.js still publishes window.chatWindow (our handle)",
              "window.chatWindow = chatWindow" in RJ)
        check("…and still commands onUpdateState itself, so we are using a path the "
              "plugin already uses on its own",
              'chatWindow.command("onUpdateState")' in RJ)
        eq("the version our glue page pins is the version actually installed",
           ooai.install_state(base)["version"], "3.2.2")
    # NOT ONE VENDORED BYTE. The whole mechanism is our key namespace plus the plugin's
    # own published event; nothing of ours may appear inside the vendored tree.
    ours = 0
    for p in pdir.rglob("*.js"):
        try:
            if "mot.ooai" in p.read_text(errors="replace"):
                ours += 1
        except OSError:
            pass
    eq("⚠️ the vendored plugin carries NONE of our identifiers — still unmodified",
       ours, 0)


# ══ 9. PROMPT CACHING — WHAT WAS MEASURED, AND WHAT THEREFORE WAS NOT BUILT ══
#
# Measured live against llama.cpp b10662 (2026-08-28); oracle = the runner's own
# `prompt eval time = X ms / N tokens` line; 29,624-token sheet prefix; three
# consecutive asks each time:
#     cache_prompt OMITTED  116.1s / 29,624 tok → 3.71s / 516 → 3.80s / 517
#     cache_prompt: true      3.68s /    515    → 3.71s / 515 → 3.69s / 516
#     cache_prompt: false   115.0s / 29,624    → 116.6s / 29,624 → 122.7s / 29,625
# OMITTED behaves identically to TRUE: prompt caching is ON BY DEFAULT at this pin.
# So injecting cache_prompt into the plugin's request body — which would have needed a
# bridge proxy, because the plugin's base Provider builds {model, messages} and its
# getRequestBodyOptions() returns {} with no data hook — was NOT built: it would have
# been a no-op wearing a proxy, and a proxy is a second place for the key and the URL
# to drift. What IS pinned is the control: the direct lane keeps sending it explicitly,
# because `false` is a real setting and a future default flip must not silently cost
# that lane two minutes a turn.
CHATPY = (ROOT / "bridge" / "routers" / "chat.py").read_text()
check("the Quick (direct) lane still sends cache_prompt explicitly",
      '"cache_prompt": True' in CHATPY)
START = (ROOT / "scripts" / "start_component.sh").read_text()
check("⚠️ the runner argv was NOT changed for caching — measurement said no flag was "
      "required, and that argv is contract-pinned",
      "--no-cont-batching --cache-ram -1" in START and "--cache-reuse" not in START)
check("…and the host-memory prompt cache stays unbounded (--cache-ram -1), which is "
      "what lets another lane's turn not evict the sheet's prefix",
      "--cache-ram -1" in START)

# ══ 10. THE RIBBON'S BLOCKING MODAL — STREAMED, AND ONLY RELEASED WHEN SAFE ══
#
# v1.5.31. The sixth upstream trap. Debi's finding: AI → Summarization / Translation
# puts the whole editor behind a centred "AI (model)" spinner for the ENTIRE
# generation. MEASURED live (WKWebView, real sheet, real runner, 2026-08-28): the
# `asc-loadmask` appears 0.5s after the click and is STILL up 120s later.
#
# It is the EDITOR's BlockInteraction long action, asked for by the plugin, and the
# plugin already contains the cure it does not use from the ribbon:
#     chatRequest(content, block, streamFunc) → _wrapRequest(..., block !== false, …)
#     _chatRequest: isStreaming = (undefined !== streamFunc); returns `allChunks`
#     register.js:186-212 — the CHATBOT: own StartAction, block=false, EndAction on
#                           the first streamed chunk.
#     the ribbon/context sites — chatRequest(prompt): blocking, no streamFunc.
# So oo.html wraps the prototype in the plugin's own same-origin frame. Zero vendored
# bytes; the version fence is what makes that safe.
check("the glue page pins the plugin version the streaming seam was read from",
      "AI_STREAM_PLUGIN_VER = '3.2.2'" in OO)
check("…and the EDITOR build the modal-detection selector was read from — two pins, "
      "because the shim reads one class pair out of each",
      "AI_STREAM_EDITOR_TAG = 'v9.2.0.119+5'" in OO
      and "AI_STREAM_MODAL_SEL = '.asc-window.modal'" in OO)
check("⚠️ THE FENCE: a plugin that is not the pinned version is NOT wrapped, so the "
      "ribbon degrades to exactly today's behaviour rather than to a broken action",
      "aiStatus.version !== AI_STREAM_PLUGIN_VER) return false" in OO)
check("…and the seam is checked STRUCTURALLY too — the arity of the method we are "
      "about to replace, and the private helper it delegates to",
      "proto.chatRequest.length !== 3" in OO
      and "typeof proto._wrapRequest !== 'function'" in OO)
check("…and an unknown EDITOR build never releases the Block (the modal selector is "
      "the only thing standing between a release and a wrong-target paste)",
      "editorTag !== AI_STREAM_EDITOR_TAG) return false" in OO)

check("the wrap point is AI.Request.prototype.chatRequest, and nothing else",
      "proto.chatRequest = async function (content, block, streamFunc)" in OO
      and "AI.Request.prototype.chatRequestAgent" not in OO)
check("⚠️ …and it takes over ONLY the blocking, non-streaming shape — every call that "
      "already passes block=false or a streamFunc (the agent loop, the helpers, the "
      "annotators) is passed through byte for byte",
      "if (block === false || streamFunc !== undefined) {" in OO
      and "return await orig.call(this, content, block, streamFunc);" in OO)
check("…calling through with block=false plus a streamFunc of ours — the Chatbot's "
      "own pattern", "orig.call(this, content, false, async function (chunk)" in OO)
check("⚠️ …bracketed by our OWN StartAction, with EndAction in a `finally` so the "
      "Block comes down on EVERY path — an editor left blocked for ever would be "
      "strictly worse than the modal this exists to shorten",
      "callMethod('StartAction', ['Block', label])" in OO
      and "callMethod('EndAction', ['Block', label])" in OO
      and OO.index("} finally {") < OO.index("aiStreamChipHide();"))
check("…and EndAction is idempotent and never fires without a StartAction that landed",
      "if (!started || ended) return;" in OO)

# ⚠️ THE FINDING THAT SHAPED THE SLICE, AND IT IS A LIE-TO-USER THE FIX ITSELF WOULD
# HAVE CAUSED. register.js:901 pastes the answer over the CURRENT selection the moment
# it arrives. Release the Block for 70 seconds and the user clicks another cell — and
# the translation of the FIRST selection lands on the SECOND one, destroying it. So
# the release is conditional on the document being unreachable anyway.
check("⚠️ the Block is released ONLY while a plugin MODAL is up — the one state in "
      "which the answer cannot land on a selection the user has moved",
      "function aiStreamModal" in OO and "const mayRelease = aiStreamModal();" in OO
      and "if (mayRelease) { job.released = true; aiStreamReleases++; await end(); }" in OO)
check("…and that is decided by TWO independent signals: the editor's own modal element "
      "AND a plugin WINDOW frame — a docked Chatbot alone leaves the ribbon usable and "
      "must not count as safe",
      "indexOf('/ooplug/') !== -1 && h.indexOf('windowID=') !== -1" in OO)
check("…taken ONCE, when the action starts, not re-read while the answer streams",
      "// The release decision is taken ONCE" in OO)

# ⚠️ TAIL INTEGRITY. Upstream's processResult passes `isTrim = isStreaming ? false :
# true`, so the streaming path skips the trim and the `<think>` strip the blocking path
# applies. Without this the SAME action, streamed, would put a DIFFERENT string into
# the document than blocked — a silent content difference caused by our own change.
check("⚠️ the streamed answer is put back into the shape the BLOCKING path would have "
      "produced — upstream's own <think> strip and newline trim, over the accumulated "
      "text", "function aiStreamNormalize" in OO
      and "0 === s.indexOf('<think>')" in OO
      and "s.charCodeAt(iStart) === 10" in OO
      and "return aiStreamNormalize(out);" in OO)
check("…and the trim mirrors upstream's own guard, so a string that needs no trim is "
      "returned untouched",
      "if (iEnd > iStart && (iStart !== 0 || iEnd !== (s.length - 1)))" in OO)
check("Stop returns '' rather than the partial text — every ribbon call site does "
      "`if (!result) return;`, so a stopped action writes NOTHING. A half-translation "
      "pasted into the sheet is the lie this whole slice exists to avoid",
      "return job.stopped === true;" in OO
      and "aiStreamLast = 'stopped after '" in OO
      and "return '';" in OO)

check("the shim is re-armed on every open — the plugin frame dies with the editor, so "
      "a swap that quietly went back to the whole-generation modal would be invisible "
      "and only on the SECOND file",
      "function aiStreamArm" in OO
      and OO.index("aiStreamArm();") > OO.index("aiChatArm(want);"))
check("…the arming poll is CAPPED, like the chat hold", "AI_STREAM_ARM_MAX" in OO)
check("…and it does nothing at all when the AI tab is gated off",
      "if (!aiSeeded) return;                  // no AI tab this session" in OO)
check("…and the chip is torn down with the editor it was reporting on",
      "aiStreamDisarm();   // the chip must not outlive" in OO)
check("a probe can PROVE the wrap took, that a run released (or held) the Block, and "
      "what the first chunk cost — instead of inferring any of it from a screenshot",
      "stream: {pinned: AI_STREAM_PLUGIN_VER, wrapped: aiStreamWrapped" in OO
      and "releases: aiStreamReleases" in OO and "ttft: aiStreamTTFT" in OO)

# The chip — the only new pixels in the slice.
check("the progress chip is OUR element, over the editor iframe, because the thing it "
      "must be legible on top of is the editor's own full-frame block overlay",
      "<div id=\"aichip\">" in OO and "#aichip{position:absolute" in OO
      and "z-index:6" in OO)
check("⚠️ …at the BOTTOM: at the top it covered the ribbon tab row the user had just "
      "used (screenshot finding, 2026-08-28)",
      "bottom:52px" in OO and "top:12px;left:50%" not in OO)
check("…and it says which of the two states the editor is actually in, because a user "
      "told 'you can keep working' while the editor is blocked has been lied to",
      "'the editor is free again'" in OO
      and "'the editor is held until this lands in the document'" in OO)
check("…and it distinguishes a model that is THINKING from one that is WRITING — which "
      "is only knowable because we stream now",
      "'AI is thinking'" in OO and "'AI is writing — '" in OO
      and "'AI is working — nothing has come back yet'" in OO)
check("…with explicit LIGHT colours, like body.embed above: the editor is pinned to "
      "default-light under every motdeck design, so a chip on our dark tokens would be "
      "the one dark object on a white sheet",
      "#aichip{" in OO and "background:#ffffff" in OO and "var(--bg)" not in OO.split(
          "#aichip{")[1].split("}")[0])
check("…and its pulse respects prefers-reduced-motion",
      "prefers-reduced-motion:reduce" in OO and "#aichip .dot{animation:none" in OO)

# ── the streaming seam, against the VENDORED bytes ───────────────────────────
if base is not None:
    pdir = Path(ooai.plug_dir(base))
    eng_js = pdir / "ai" / "scripts" / "engine" / "engine.js"
    reg_js = pdir / "ai" / "scripts" / "engine" / "register.js"
    code_js = pdir / "ai" / "scripts" / "code.js"
    if eng_js.is_file() and reg_js.is_file():
        EJ, RJ = eng_js.read_text(errors="replace"), reg_js.read_text(errors="replace")
        check("⚠️ the VENDORED chatRequest still takes (content, block, streamFunc) and "
              "still defaults block to TRUE — the whole reason the ribbon blocks",
              "AI.Request.prototype.chatRequest = async function(content, block, streamFunc)"
              in EJ and "this._wrapRequest(this._chatRequest, content, block !== false, streamFunc)"
              in EJ, "a plugin bump changed the seam this shim wraps")
        check("…and _wrapRequest still brackets it with StartAction/EndAction ONLY when "
              "block is true, which is what makes block=false ours to bracket",
              'if (block)\n\t\t\tawait Asc.Editor.callMethod("StartAction", ["Block"' in EJ)
        check("…and streaming is still switched on by the mere PRESENCE of a streamFunc",
              "let isStreaming = (undefined !== streamFunc);" in EJ)
        check("⚠️ …and the streamed request still returns the WHOLE accumulated answer "
              "(`allChunks`), not the last chunk — this is the tail-integrity claim",
              "allChunks += dataChunk;" in EJ and "return allChunks;" in EJ)
        check("…and a streamFunc returning true is still upstream's own documented abort, "
              "which is what our Stop uses",
              "if (isBreak === true) {" in EJ and "await readerAsync.abort();" in EJ)
        check("⚠️ …and the trim our normalize reproduces is still conditional on "
              "streaming — the reason a streamed answer would otherwise differ",
              "provider.getChatCompletionsResult(data, model, isStreaming ? false : true)"
              in EJ)
        check("the VENDORED ribbon Translation still calls chatRequest with NO block "
              "flag and NO streamFunc, and still pastes over the live selection",
              "let result = await requestEngine.chatRequest(prompt);" in RJ
              and "await Asc.Library.PasteText(result);" in RJ)
        check("…and every ribbon/context call site still bails on a falsy result, which "
              "is what makes Stop write nothing",
              RJ.count("if (!result) return;") >= 8)
        check("the CHATBOT is still on the other method (chatRequestAgent), so nothing "
              "this shim does can reach it",
              "requestEngine.chatRequestAgent(requestData, false, async function(chunk)"
              in RJ)
        if code_js.is_file():
            KJ = code_js.read_text(errors="replace")
            check("…and the ribbon SUMMARIZATION still asks from inside its own MODAL — "
                  "which is why releasing the Block there cannot land on a moved "
                  "selection",
                  "summarizationWindow.attachEvent(\"Summarize\"" in KJ
                  and "isModal : true" in KJ
                  and "let result = await requestEngine.chatRequest(prompt);" in KJ)

# ── the Help copy, which had to change because the behaviour did ─────────────
check("⚠️ Help → About no longer carries v1.5.29's 'the ribbon holds it until the whole "
      "answer is finished' line — it stopped being true, and a Help sheet describing "
      "last week's behaviour is a lie with a footnote",
      "hold it until the whole answer is finished" not in PAGE
      and "for anything long, ask in the Chatbot" not in PAGE)
check("…and says PER ACTION which streams and which still blocks",
      "SUMMARIZATION (ribbon)" in PAGE and "TRANSLATION" in PAGE
      and "clears at the first word too" in PAGE)
check("…and gives the REASON the blocking ones still block, in the user's own terms",
      "pasted straight" in PAGE and "on top of the SECOND one" in PAGE)
check("…and names the chip and what Stop does",
      "a chip over the sheet" in PAGE and "stopping writes NOTHING" in PAGE)


print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("oo AI lane OK — all checks passed")
