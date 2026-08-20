"""Model settings v2 — LOAD group + engine SAMPLING FLOORS (2026-08-20).

What is pinned here, and why each one is load-bearing:

1. FLOORS (Debi ruling). The Agent (Odysseus) and Hermes lanes build their own
   request bodies and send NO sampling at all, so the only way a user's choice can
   reach them is the engine LAUNCH LINE. The rule that keeps that safe is
   **explicit-only**: nothing saved ⇒ nothing emitted ⇒ the launch line is
   byte-identical to pre-v2. The harness's own 0.7 default is deliberately NOT
   pushed onto lanes that never had it.
2. No double-emit. `--repeat-penalty 1.1 --repeat-last-n 256` was a hardcoded pair;
   it is now the FALLBACK of the same single emission site. Emitting it twice (once
   hardcoded, once from the saved value) would hand llama-server two values.
3. Evidence-gating. Every flag emitted is one this engine documents:
   llama.cpp against its own captured --help, MLX against the installed server
   SOURCE. `mlx_vlm.server` has NO sampler launch flags (only --max-tokens), so a
   temperature must never reach it.
4. LOAD storage/merge/view — the same grammar as v1 `settings` (None removes the
   key, junk is dropped, engine-conditional fields are ABSENT not greyed out), plus
   the three-state `applied` claim (None = the bridge never launched it and has no
   opinion — it must not tell the user their change is unapplied when it cannot know).
5. USER_KEYS: `load` must survive a RESCAN — the recorded defect class that
   un-pinned every voice once and would have reset every tuned model in v1.
6. Wiring greps: start_component.sh really reads both dicts, the panel really has
   the group + the Apply & reload path, and the read side really rides /api/models.

Run: python3 bridge/tests/test_model_load.py
"""
import ast
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


def ok(name, cond, why=""):
    if not cond:
        fails.append(f"{name}{(' — ' + why) if why else ''}")


# ── extract the pure half out of app.py (importing it opens network clients) ──
APP = os.path.join(ROOT, "bridge", "app.py")
src = open(APP).read()
tree = ast.parse(src)
WANT_FN = ("sampling_engine", "_load_val", "load_saved", "load_view")
WANT_CONST = ("LOAD_ORDER", "LOAD_WIRE", "LOAD_DEFAULTS", "LOAD_RANGES",
              "LOAD_KV_TYPES", "LOAD_NOTE", "SAMPLING_FLOOR_WIRE")
ns = {}
for node in tree.body:
    take = False
    if isinstance(node, ast.FunctionDef) and node.name in WANT_FN:
        take = True
    elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in WANT_CONST for t in node.targets):
        take = True
    if take:
        exec(compile(ast.Module(body=[node], type_ignores=[]), APP, "exec"), ns)
for n in WANT_FN + WANT_CONST:
    ok(f"extracted {n}", n in ns)
if fails:
    print("FAIL (extraction):", fails)
    sys.exit(1)

lval, saved, view = ns["_load_val"], ns["load_saved"], ns["load_view"]
LOAD_ORDER, LOAD_WIRE = ns["LOAD_ORDER"], ns["LOAD_WIRE"]
LOAD_KV_TYPES, LOAD_RANGES = ns["LOAD_KV_TYPES"], ns["LOAD_RANGES"]
FLOOR_WIRE = ns["SAMPLING_FLOOR_WIRE"]

GGUF = {"id": "g", "format": "gguf"}
MLXLM = {"id": "m", "format": "mlx"}
MLXVLM = {"id": "v", "format": "mlx", "vision": True}

# ── 1. _load_val decision table (total: any input type is safe) ──────────────
check("ctx in range", lval("ctx", 32768), 32768)
check("ctx as a string coerces", lval("ctx", "32768"), 32768)
check("ctx below the floor is refused", lval("ctx", 512), None)
check("ctx above the ceiling is refused", lval("ctx", 999999999), None)
check("ctx boundary lo is inclusive", lval("ctx", 1024), 1024)
check("ctx boundary hi is inclusive", lval("ctx", 262144), 262144)
check("ctx True is not 1", lval("ctx", True), None)
check("ctx junk string", lval("ctx", "big"), None)
check("ctx None", lval("ctx", None), None)
check("ctx list", lval("ctx", [1]), None)
check("ctx NaN", lval("ctx", float("nan")), None)
check("ctx inf", lval("ctx", float("inf")), None)
check("gpu_layers -1 is allowed (the 'all layers' convention)",
      lval("gpu_layers", -1), -1)
check("gpu_layers 0 allowed", lval("gpu_layers", 0), 0)
check("gpu_layers -2 refused", lval("gpu_layers", -2), None)
check("gpu_layers 1000 refused", lval("gpu_layers", 1000), None)
check("flash_attn True", lval("flash_attn", True), True)
check("flash_attn False stays False, not None", lval("flash_attn", False), False)
check("flash_attn 'on'", lval("flash_attn", "on"), True)
check("flash_attn 'OFF' case-insensitive", lval("flash_attn", "OFF"), False)
check("flash_attn 'auto' is not a stored value", lval("flash_attn", "auto"), None)
check("flash_attn junk", lval("flash_attn", 7), None)
for t in LOAD_KV_TYPES:
    check(f"kv_quant {t}", lval("kv_quant", t), t)
check("kv_quant uppercase normalises", lval("kv_quant", "Q8_0"), "q8_0")
check("kv_quant f16 is not offered (it IS the default — 'off' means that)",
      lval("kv_quant", "f16"), None)
check("kv_quant junk", lval("kv_quant", "bogus"), None)
check("kv_quant bool", lval("kv_quant", True), None)
check("an unknown key is never a value", lval("nonsense", 1), None)

# ── 2. load_saved: junk totality ─────────────────────────────────────────────
check("no load key", saved(GGUF), {})
check("load is not a dict", saved(dict(GGUF, load="x")), {})
check("load is None", saved(dict(GGUF, load=None)), {})
check("entry itself is junk", saved("nope"), {})
check("a good key survives beside a bad one",
      saved(dict(GGUF, load={"ctx": 4096, "gpu_layers": "lots"})), {"ctx": 4096})
check("unknown keys are dropped",
      saved(dict(GGUF, load={"ctx": 4096, "mlock": True})), {"ctx": 4096})
check("flash_attn False is KEPT (it is a real choice, not an absence)",
      saved(dict(GGUF, load={"flash_attn": False})), {"flash_attn": False})
check("full set", saved(dict(GGUF, load={"ctx": 8192, "gpu_layers": 40,
                                         "flash_attn": True, "kv_quant": "q8_0"})),
      {"ctx": 8192, "gpu_layers": 40, "flash_attn": True, "kv_quant": "q8_0"})

# ── 3. load_view: engine-conditional fields, three-state `applied` ───────────
v = view(GGUF)
check("gguf gets all four rows", [f["key"] for f in v["fields"]], list(LOAD_ORDER))
check("gguf engine", v["engine"], "llamacpp")
check("nothing saved ⇒ nothing changed", v["changed"], 0)
check("no launch record ⇒ NO claim", v["applied"], None)
ok("every row carries a kind the panel can render",
   all(f["kind"] in ("int", "bool", "enum") for f in v["fields"]))
ok("the enum row carries its choices",
   [f for f in v["fields"] if f["key"] == "kv_quant"][0]["choices"] == list(LOAD_KV_TYPES))
ok("the int rows carry their range",
   all("min" in f and "max" in f for f in v["fields"] if f["kind"] == "int"))
check("mlx-lm has NO load fields (no ctx/gpu/kv/fa flag exists there)",
      view(MLXLM)["fields"], [])
check("mlx-vlm likewise — its KV suite is a bit-count API, not our enum",
      view(MLXVLM)["fields"], [])
check("mlx engines still name themselves honestly", view(MLXVLM)["engine"], "mlxvlm")
e = dict(GGUF, load={"ctx": 8192})
check("a saved value shows as changed", view(e)["changed"], 1)
check("...and is carried on the row",
      [f["value"] for f in view(e)["fields"] if f["key"] == "ctx"], [8192])
check("applied True when the launch record matches",
      view(e, {"ctx": 8192})["applied"], True)
check("applied False when it differs", view(e, {"ctx": 4096})["applied"], False)
check("applied False when the user added a field since launch",
      view(e, {})["applied"], False)
check("a launch record with foreign keys is filtered before comparing",
      view(e, {"ctx": 8192, "junk": 1})["applied"], True)
check("a junk launch record makes NO claim", view(e, "nope")["applied"], None)
ok("the view always carries the reload warning", "Apply & reload" in view(GGUF)["note"])

# ── 4. FLOOR wire table — evidence-gated, never a flag an engine lacks ───────
check("llama.cpp floors cover every sampler it documents",
      sorted(FLOOR_WIRE["llamacpp"]),
      sorted(["temperature", "top_p", "top_k", "min_p",
              "repeat_penalty", "repeat_last_n", "seed"]))
check("mlx-lm floors are the four samplers + max_tokens",
      sorted(FLOOR_WIRE["mlxlm"]),
      sorted(["temperature", "top_p", "top_k", "min_p", "max_tokens"]))
check("mlx-vlm has NO sampler launch flag — only max_tokens",
      sorted(FLOOR_WIRE["mlxvlm"]), ["max_tokens"])
ok("no MLX engine claims a seed or a repetition launch flag",
   not any(k in FLOOR_WIRE[e] for e in ("mlxlm", "mlxvlm")
           for k in ("seed", "repeat_penalty", "repeat_last_n")))
ok("llama.cpp does NOT put max_tokens on the launch line",
   "max_tokens" not in FLOOR_WIRE["llamacpp"],
   "-n/--predict already defaults to unbounded there")
ok("every floor flag is a real flag name", all(
    f.startswith("--") for eng in FLOOR_WIRE.values() for f in eng.values()))

# ── 5. the shell's own extraction, EXECUTED (explicit-only + junk totality) ──
SC = os.path.join(ROOT, "scripts", "start_component.sh")
sc = open(SC).read()
pyr = sc.split("<<'PYRESOLVE'\n", 1)[1].split("\nPYRESOLVE\n", 1)[0]
ok("the resolver still parses", bool(ast.parse(pyr)))


def resolve(entry):
    """Run the REAL in-script resolver against a temp registry; return its 8 lines."""
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "data"))
        gguf = os.path.join(td, "data", "m.gguf")
        open(gguf, "w").write("x")
        e = dict(entry, path=gguf)
        with open(os.path.join(td, "data", "models.json"), "w") as f:
            json.dump({"models": [e]}, f)
        p = os.path.join(td, "r.py")
        open(p, "w").write(pyr)
        r = subprocess.run([sys.executable, p], cwd=td, capture_output=True, text=True,
                           env=dict(os.environ, R_MODEL=e["id"]))
        return r.stdout.splitlines()


base = {"id": "g", "format": "gguf"}
lines = resolve(base)
check("a model with NOTHING saved emits an empty sampling line", lines[6], "")
check("...and an empty load line", lines[7], "")
lines = resolve(dict(base, settings={"temperature": 0.2, "top_k": 30}))
check("only the saved sampling values travel", lines[6], "temperature=0.2 top_k=30")
lines = resolve(dict(base, settings={"temperature": "hot", "top_p": [1], "min_p": 9,
                                     "top_k": True, "top_k2": 1, "seed": 12}))
check("junk sampling values are dropped before they can reach a launch line",
      lines[6], "seed=12")
lines = resolve(dict(base, load={"ctx": 32768, "flash_attn": True,
                                 "kv_quant": "q8_0", "gpu_layers": -1}))
check("load values travel as one-word tokens",
      lines[7], "ctx=32768 gpu_layers=-1 flash_attn=on kv_quant=q8_0")
lines = resolve(dict(base, load={"kv_quant": "bogus", "ctx": 10, "flash_attn": "maybe"}))
check("junk load values are dropped too", lines[7], "")
lines = resolve(dict(base, load="not a dict", settings=None))
check("a non-dict load is safe", lines[7], "")
ok("no emitted token can ever contain a space (it would split the shell loop)",
   all(" " not in tok.split("=", 1)[1]
       for tok in resolve(dict(base, load={"kv_quant": "q4_0"}))[7].split()))

# ── 6. shell wiring: explicit-only, gated, and emitted exactly once ──────────
ok("the shell reads both saved dicts off the resolver",
   'SAMP_KV=$(sed -n \'7p\'' in sc and 'LOAD_KV=$(sed -n \'8p\'' in sc)
ok("there are lookup helpers for each", "_sv() {" in sc and "_lv() {" in sc)
ok("the repetition pair is emitted from exactly ONE site",
   sc.count("--repeat-penalty") == 2,   # the emission + the support grep
   "a second hardcoded emission would hand llama-server two values")
ok("...with the old constants as the FALLBACK, not a second pair",
   '"${S_RP:-1.1}"' in sc and '"${S_RL:-256}"' in sc)
ok("llama.cpp floors are gated on the binary's OWN --help",
   'grep -q -- "$1" data/llama-server.help.txt || return 0' in sc)
ok("a floor with no saved value emits nothing",
   '[[ -n "$2" ]] || return 0' in sc)
for flag in ("--temp", "--top-p", "--top-k", "--min-p"):
    ok(f"llama.cpp floor emits {flag}", f'_floor {flag}' in sc.replace("  ", " "))
ok("a negative seed is never pinned (it IS the engine default)",
   'S_SEED" =~ ^[0-9]+$' in sc)
ok("gpu_layers -1 is translated to the engine's own documented token",
   '[[ "$L_NGL" == "-1" ]] && L_NGL=all' in sc)
ok("kv_quant 'off' means: leave the engine default alone",
   '"$L_KV" != "off"' in sc)
ok("kv_quant sets BOTH halves of the cache",
   "--cache-type-k \"$L_KV\" --cache-type-v \"$L_KV\"" in sc)
ok("flash_attn only ever emits on|off", '"$L_FA" == "on" || "$L_FA" == "off"' in sc)
ok("saved ctx wins over the registry preset",
   'L_CTX" =~ ^[0-9]+$ ]]; then CTX="$L_CTX"' in sc)
ok("...but the registry/yaml/65536 chain is still behind it",
   'REG_CTX" =~ ^[0-9]+$ ]]; then CTX="$REG_CTX"' in sc and "CTX=65536" in sc)
ok("every load flag is gated on the binary supporting it",
   sc.count("data/llama-server.help.txt") >= 6)
# MLX side
mlx = sc[sc.index("MLX_FLOOR=()"):sc.index("# Cleanup: kill both MLX servers")]
ok("MLX floors are gated on the installed server SOURCE, not a guess",
   'grep -q -- "\\"$1\\"" "$MLX_ARGSRC"' in mlx)
ok("only mlx-lm gets the four samplers",
   'if [[ "$ENGINE" == "mlxlm" ]]; then' in mlx and "_mfloor --temp" in mlx)
ok("...and mlx-vlm therefore gets none of them",
   mlx.index("_mfloor --temp") > mlx.index('"$ENGINE" == "mlxlm"'))
ok("max_tokens rides BOTH mlx engines (the 512/2048 truncation)",
   mlx.rstrip().endswith('_mfloor --max-tokens "$(_sv max_tokens)"'))
ok("no MLX floor ever emits a seed or repetition flag",
   "--seed" not in mlx and "repeat" not in mlx and "repetition" not in mlx)
ok("the MLX launch line passes the floor array safely",
   '${MLX_FLOOR[@]+"${MLX_FLOOR[@]}"}' in sc)

# ── 7. USER_KEYS: `load` must survive a RESCAN ───────────────────────────────
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import seed_registry as SR  # noqa: E402

ok("`load` is a USER_KEY", "load" in SR.USER_KEYS)
ok("`settings` still is too (v1's half)", "settings" in SR.USER_KEYS)
existing = [{"id": "keepme", "format": "gguf", "source": "local",
             "load": {"ctx": 8192}, "settings": {"temperature": 0.2}},
            {"id": "lms", "format": "gguf", "source": "lmstudio-import",
             "load": {"kv_quant": "q8_0"}}]
fresh_local = [{"id": "keepme", "format": "gguf", "source": "local", "path": "/x"}]
fresh_lms = [{"id": "lms", "format": "gguf", "source": "lmstudio-import", "path": "/y"}]
merged = SR.merge(existing, [], fresh_lms, fresh_local)
by_id = {m["id"]: m for m in merged}
check("a rescan keeps a local model's load overrides",
      by_id["keepme"].get("load"), {"ctx": 8192})
check("...and its sampling overrides (v1 regression guard)",
      by_id["keepme"].get("settings"), {"temperature": 0.2})
check("a rescan keeps an lmstudio import's load overrides",
      by_id["lms"].get("load"), {"kv_quant": "q8_0"})
check("a fresh scan can never INVENT the key",
      "load" in SR.merge([], [], [], fresh_local)[0], False)

# ── 8. endpoint + read-side wiring ───────────────────────────────────────────
ep = src[src.index('@app.post("/api/models/load-settings")'):]
ep = ep[:ep.index('@app.post("/api/chat/direct")')]
ok("endpoint writes through _registry_update", '_registry_update(mid, {"load"' in ep)
ok("endpoint removes the key when nothing is left", "new or None" in ep)
ok("endpoint supports a full reset", '{"load": None}' in ep)
ok("endpoint refuses an unknown model", "is not in the registry" in ep)
ok("endpoint refuses a voice model", "is_audio_entry" in ep)
ok("endpoint refuses a field this engine cannot honour", "can honour" in ep)
ok("endpoint refuses an out-of-range int", "whole number between" in ep)
ok("endpoint refuses a bad enum", "kv_quant must be one of" in ep)
ok("endpoint returns the refreshed view", "load_view(upd" in ep)
ok("endpoint reports the launch record with the view", "_LOAD_AT_LAUNCH.get(mid)" in ep)
models_h = src[src.index("def api_models("):src.index("def api_models(") + 6000]
ok("/api/models carries the rendered view", '"loadview": load_view(' in models_h)
ok("/api/models carries the raw pin", '"load": (m.get("load")' in models_h)
ok("the launch record is written where WE launch the runner",
   src.count("_record_load_launch(") == 3)   # def + switch + start closure
_sw = src[src.index("def _do_switch"):src.index('@app.post("/api/models/switch")')]
ok("...on the SWITCH path only after a successful load",
   _sw.index("_record_load_launch(new_id)") > _sw.index("reverted to"))
ok("...and never claims anything it did not launch",
   "if not isinstance(launched, dict)" in src)

# ── 9. panel: the group renders the BRIDGE's field list ──────────────────────
panel = open(os.path.join(ROOT, "bridge", "panel", "index.html")).read()
ok("panel renders the load section", 'id="md-load"' in panel)
ok("panel calls renderLoad from the detail pane", "renderLoad(m);" in panel)
ok("panel omits the wrapper when the engine has no load flags",
   'ld ? `<div class="md-sec" id="md-load">' in panel)
ok("panel reads m.loadview.fields", "lv.fields" in panel)
body = panel.split("function renderLoad")[1].split("function toggleLoad")[0]
ok("panel does NOT hardcode a field list",
   "'ctx'" not in body and "'kv_quant'" not in body)
ok("panel labels rows with the engine's flag name", "esc(f.label)" in body)
ok("panel posts to the load endpoint", "'/api/models/load-settings'" in panel)
ok("panel empty box / 'default' option = reset (null, never a stored zero)",
   "let val = null;" in panel.split("async function loadSet")[1][:400])
ok("panel has a reset-all", "loadResetAll" in panel)
ok("panel has an Apply & reload chip", "Apply &amp; reload" in panel)
ok("Apply goes through the EXISTING switch path on the same id",
   "switchModel(id," in panel.split("function loadApply")[1][:400])
ok("...and is a no-op while another load is in flight",
   "if (!id || modelsBusy) return;" in panel.split("function loadApply")[1][:300])
ok("panel shows the not-applied-yet pill only when the bridge says so",
   "lv.applied === false" in panel and "not applied yet" in panel)
ok("panel prints the reload warning", "esc(lv.note)" in panel)
ok("panel group is collapsed by default", "let loadOpen = false;" in panel)
ok("a background re-render cannot wipe a half-typed load value",
   "f.closest('#md-load')" in panel)
ok("the model id is read from mSel, never interpolated into a handler",
   "mSel.kind === 'installed') ? mSel.id" in panel.split("async function loadPost")[1][:300])
# zero new CSS: the section reuses the Capabilities grammar
for cls in ("cap-card", "cap-row", "cap-name", "cap-desc", "cap-inp", "cap-btn",
            "cap-count", "cap-pill"):
    ok(f"reuses .{cls}", ("." + cls) in panel)

# ── 10. the lane note tells the new truth ────────────────────────────────────
ok("the sampling note now names the floors",
   "also become" in ns.get("LOAD_NOTE", "") + src)
ok("the sampling note no longer claims the other lanes are unaffected",
   "build their own requests and use their own engines' settings" not in src)
ok("the sampling note says values land on the next message for CHAT",
   "Applies to CHAT immediately" in src)

if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_model_load: all checks passed")
