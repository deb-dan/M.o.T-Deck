"""Per-model sampling settings (MODEL SAMPLING SETTINGS v1, 2026-08-20).

What is pinned here, and why each one is load-bearing:

1. `sampling_merge` — the pure defaults→override→engine-key pipeline. The ONE
   invariant that matters most: **every merge carries an explicit `max_tokens`**,
   for every engine, with or without saved overrides. `mlx_lm.server` defaults it
   to 512 and `mlx_vlm` to 2048 when the body omits it, so omitting it silently
   truncated every MLX reply (llama.cpp's -1 is unbounded, which is why the gguf
   lane never showed the bug).
2. Engine key translation: the MLX servers name the two penalty fields
   `repetition_penalty` / `repetition_context_size`. A body carrying llama.cpp's
   names would be silently ignored there — so the wire names are asserted in both
   directions (present under the right name, ABSENT under the wrong one).
3. Junk totality: a hand-edited registry (or a future scan) must never be able to
   break a turn. Every surprise type/range falls back to the harness default.
4. USER_KEYS: `settings` must survive a RESCAN. This is the recorded defect class
   (a rescan reads FILES, so a user decision that lives nowhere on disk is erased)
   — it un-pinned voices once already.
5. Wiring greps: the direct lane really merges the fragment into its body, the
   read side really rides /api/models, and the panel really renders the bridge's
   field list rather than one of its own.

Run: python3 bridge/tests/test_model_settings.py
"""
import ast
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
import sys as _sys                                          # noqa: E402
_sys.path.insert(0, str(ROOT))                              # noqa: E402
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")


def ok(name, cond, why=""):
    if not cond:
        fails.append(f"{name}{(' — ' + why) if why else ''}")


# ── extract the pure half out of app.py (importing it opens network clients) ──
APP = os.path.join(ROOT, "bridge", "appsrc.py")   # compile() label only
src = _APP_SOURCE
tree = ast.parse(src)
WANT_FN = ("sampling_engine", "_sampling_num", "_sampling_stop", "sampling_saved",
           "sampling_merge", "sampling_view")
WANT_CONST = ("SAMPLING_HELP",
              "SAMPLING_DEFAULTS", "SAMPLING_ORDER", "_S_MLX", "SAMPLING_WIRE",
              "SAMPLING_RANGES", "SAMPLING_STOP_MAX", "SAMPLING_LANE_NOTE")
ns = {}
for node in tree.body:
    take = False
    if isinstance(node, ast.FunctionDef) and node.name in WANT_FN:
        take = True
    elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in WANT_CONST for t in node.targets):
        take = True
    if take:
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<app>", "exec"), ns)

for n in WANT_FN + WANT_CONST:
    ok(f"extracted {n}", n in ns, "not found in bridge/app.py")
if fails:
    print("\n".join(fails))
    sys.exit(1)

merge = ns["sampling_merge"]
view = ns["sampling_view"]
engine = ns["sampling_engine"]
saved = ns["sampling_saved"]
num = ns["_sampling_num"]
DEF = ns["SAMPLING_DEFAULTS"]
ORDER = ns["SAMPLING_ORDER"]
WIRE = ns["SAMPLING_WIRE"]
RANGES = ns["SAMPLING_RANGES"]

GGUF = {"id": "m", "format": "gguf"}
MLX = {"id": "m", "format": "mlx"}
MLXV = {"id": "m", "format": "mlx", "vision": True}

# ── 1. the constant table itself ─────────────────────────────────────────────
check("defaults temperature", DEF["temperature"], 0.7)
check("defaults top_p", DEF["top_p"], 0.95)
check("defaults top_k", DEF["top_k"], 40)
check("defaults min_p", DEF["min_p"], 0.05)
# the two numbers promoted verbatim out of start_component.sh's argv constant
check("defaults repeat_penalty", DEF["repeat_penalty"], 1.1)
check("defaults repeat_last_n", DEF["repeat_last_n"], 256)
check("defaults max_tokens", DEF["max_tokens"], 4096)
check("defaults seed", DEF["seed"], -1)
check("order covers defaults", sorted(ORDER), sorted(DEF.keys()))
check("no duplicate order keys", len(set(ORDER)), len(ORDER))
check("every ordered key has a range", sorted(RANGES.keys()), sorted(ORDER))
for k, v in DEF.items():
    lo, hi, _c = RANGES[k]
    ok(f"default {k} inside its own range", lo <= v <= hi, f"{v} not in [{lo},{hi}]")
# 1.0 is "off" on BOTH penalty scales; the MLX 0.0 sentinel must be unreachable so
# we can never write a value that means different things to the two engines.
check("repeat_penalty floor is 1.0 (never MLX's 0.0 'off')", RANGES["repeat_penalty"][0], 1.0)
ok("max_tokens can never be 0/-1", RANGES["max_tokens"][0] >= 1)

# ── 2. engine detection (mirrors start_component.sh:64-66) ───────────────────
check("gguf → llamacpp", engine(GGUF), "llamacpp")
check("mlx text → mlxlm", engine(MLX), "mlxlm")
check("mlx vision → mlxvlm", engine(MLXV), "mlxvlm")
check("mlx + mmproj → mlxvlm", engine({"format": "mlx", "mmproj": "/p/mm.gguf"}), "mlxvlm")
check("MLX uppercase", engine({"format": "MLX"}), "mlxlm")
check("no format → llamacpp", engine({}), "llamacpp")
check("None → llamacpp", engine(None), "llamacpp")
check("junk entry → llamacpp", engine("nonsense"), "llamacpp")
check("junk format → llamacpp", engine({"format": 7}), "llamacpp")

# ── 3. THE bug fix: max_tokens is always present ─────────────────────────────
for label, e in (("gguf", GGUF), ("mlxlm", MLX), ("mlxvlm", MLXV),
                 ("unknown", {}), ("none", None), ("junk", 42)):
    b = merge(e)
    ok(f"{label}: max_tokens always sent", "max_tokens" in b, repr(b))
    check(f"{label}: max_tokens value", b.get("max_tokens"), 4096)
check("no-settings merge is a full default body",
      merge(GGUF), {"temperature": 0.7, "top_p": 0.95, "top_k": 40, "min_p": 0.05,
                    "repeat_penalty": 1.1, "repeat_last_n": 256, "max_tokens": 4096})

# ── 4. engine key translation, asserted in BOTH directions ──────────────────
g = merge(GGUF)
m = merge(MLX)
v = merge(MLXV)
ok("gguf uses repeat_penalty", "repeat_penalty" in g)
ok("gguf uses repeat_last_n", "repeat_last_n" in g)
ok("gguf does NOT use repetition_penalty", "repetition_penalty" not in g)
ok("mlxlm uses repetition_penalty", "repetition_penalty" in m)
ok("mlxlm uses repetition_context_size", "repetition_context_size" in m)
ok("mlxlm does NOT use repeat_penalty", "repeat_penalty" not in m,
   "llama.cpp's name is silently ignored by mlx_lm.server")
ok("mlxlm does NOT use repeat_last_n", "repeat_last_n" not in m)
check("mlxvlm speaks the same dialect as mlxlm", v, m)
check("mlx penalty value carries across unchanged", m["repetition_penalty"], 1.1)
check("mlx penalty window", m["repetition_context_size"], 256)
# the shared keys must be identical between engines (same personality per engine)
for k in ("temperature", "top_p", "top_k", "min_p", "max_tokens"):
    check(f"shared key {k}", g[k], m[k])

# ── 5. seed: -1 means "random", and is never put on the wire ────────────────
ok("default seed omitted (gguf)", "seed" not in merge(GGUF))
ok("default seed omitted (mlx)", "seed" not in merge(MLX))
check("seed 0 IS sent", merge(dict(GGUF, settings={"seed": 0})).get("seed"), 0)
check("seed 1234 IS sent", merge(dict(MLX, settings={"seed": 1234})).get("seed"), 1234)
ok("explicit -1 still omitted", "seed" not in merge(dict(GGUF, settings={"seed": -1})))

# ── 6. overrides win over defaults, per field ───────────────────────────────
b = merge(dict(GGUF, settings={"temperature": 0.2}))
check("override applied", b["temperature"], 0.2)
check("other fields still default", b["top_p"], 0.95)
check("override in mlx dialect", merge(dict(MLX, settings={"repeat_penalty": 1.25}))
      ["repetition_penalty"], 1.25)
check("int override coerced to float", merge(dict(GGUF, settings={"temperature": 1}))
      ["temperature"], 1.0)
check("string override coerced", merge(dict(GGUF, settings={"temperature": "0.35"}))
      ["temperature"], 0.35)
check("float override coerced to int", merge(dict(GGUF, settings={"top_k": 20.0}))
      ["top_k"], 20)

# ── 7. junk totality — a bad registry can never break a turn ────────────────
JUNK = [
    ("settings not a dict", {"settings": "hot"}),
    ("settings is a list", {"settings": [1, 2]}),
    ("settings null", {"settings": None}),
    ("unknown key", {"settings": {"mirostat": 2}}),
    ("temperature out of range", {"settings": {"temperature": 99}}),
    ("temperature negative", {"settings": {"temperature": -1}}),
    ("temperature is a bool", {"settings": {"temperature": True}}),
    ("temperature is a dict", {"settings": {"temperature": {"a": 1}}}),
    ("temperature is a list", {"settings": {"temperature": [0.5]}}),
    ("temperature is text", {"settings": {"temperature": "warm"}}),
    ("temperature is empty", {"settings": {"temperature": ""}}),
    ("temperature is nan", {"settings": {"temperature": float("nan")}}),
    ("temperature is inf", {"settings": {"temperature": float("inf")}}),
    ("top_p above 1", {"settings": {"top_p": 1.5}}),
    ("max_tokens zero", {"settings": {"max_tokens": 0}}),
    ("max_tokens negative", {"settings": {"max_tokens": -1}}),
    ("penalty below the shared floor", {"settings": {"repeat_penalty": 0.0}}),
    ("None value", {"settings": {"temperature": None}}),
]
for label, patch in JUNK:
    try:
        b = merge(dict(GGUF, **patch))
    except Exception as e:                                        # noqa: BLE001
        fails.append(f"junk '{label}' RAISED {e!r}")
        continue
    check(f"junk '{label}' → defaults", b, merge(GGUF))
# one good key beside a bad one: the good one survives
b = merge(dict(GGUF, settings={"temperature": 0.3, "top_p": 42, "nope": 1}))
check("good key survives beside junk (temp)", b["temperature"], 0.3)
check("bad key falls back (top_p)", b["top_p"], 0.95)
ok("unknown key never reaches the wire", "nope" not in b)
# boundary values are ACCEPTED (the range is inclusive)
check("temperature 0 accepted", merge(dict(GGUF, settings={"temperature": 0}))["temperature"], 0.0)
check("temperature 2 accepted", merge(dict(GGUF, settings={"temperature": 2}))["temperature"], 2.0)
check("top_p 1 accepted", merge(dict(GGUF, settings={"top_p": 1}))["top_p"], 1.0)
check("repeat_last_n -1 accepted", merge(dict(GGUF, settings={"repeat_last_n": -1}))
      ["repeat_last_n"], -1)

# ── 8. stop strings (storage/merge only — no UI row in v1) ──────────────────
check("stop list", merge(dict(GGUF, settings={"stop": ["</s>", "User:"]}))["stop"],
      ["</s>", "User:"])
check("stop single string is wrapped", merge(dict(GGUF, settings={"stop": "END"}))["stop"], ["END"])
ok("stop absent by default", "stop" not in merge(GGUF))
ok("junk stop dropped", "stop" not in merge(dict(GGUF, settings={"stop": {"a": 1}})))
ok("empty stop dropped", "stop" not in merge(dict(GGUF, settings={"stop": []})))
ok("blank stop entries dropped", "stop" not in merge(dict(GGUF, settings={"stop": ["", "  "]})))
check("stop capped", len(merge(dict(GGUF, settings={"stop": list("abcdefgh")}))["stop"]),
      ns["SAMPLING_STOP_MAX"])

# ── 9. sampling_saved is the cleaned pin (what the UI shows as "changed") ───
check("saved: clean", saved(dict(GGUF, settings={"temperature": 0.2})), {"temperature": 0.2})
check("saved: junk dropped", saved(dict(GGUF, settings={"temperature": 9, "top_k": 10})),
      {"top_k": 10})
check("saved: no settings", saved(GGUF), {})
check("saved: junk entry", saved(None), {})

# ── 10. sampling_view — what the panel draws ────────────────────────────────
vg = view(GGUF)
check("view engine gguf", vg["engine"], "llamacpp")
check("view field count", len(vg["fields"]), len(ORDER))
check("view labels are the WIRE names", [f["label"] for f in vg["fields"]],
      [WIRE["llamacpp"][k] for k in ORDER])
check("view nothing changed", vg["changed"], 0)
ok("view value is None when running the default",
   all(f["value"] is None for f in vg["fields"]))
ok("every field carries its range", all(("min" in f and "max" in f) for f in vg["fields"]))
# v2.1 (Debi ask): every drawn row must explain itself. Pinned as a TOTALITY over
# the rendered field list, not over the table — a field added without a help string
# would fail here, which is the whole point of single-sourcing the prose.
HELP = ns["SAMPLING_HELP"]
for _e, _lbl in ((GGUF, "gguf"), (MLX, "mlx-lm"), (MLXV, "mlx-vlm")):
    _f = view(_e)["fields"]
    ok(f"{_lbl}: every rendered field carries a non-empty help",
       all(isinstance(f.get("help"), str) and f["help"].strip() for f in _f),
       repr([f["key"] for f in _f if not f.get("help")]))
ok("help is prose, not a repeat of the key",
   all(len(v) > 30 for v in HELP.values()))
ok("the help table covers exactly the canonical sampling keys",
   sorted(HELP) == sorted(ORDER))
ok("max_tokens' help says what it is NOT (the recurring confusion)",
   "context window" in HELP["max_tokens"])
ok("seed's help explains that -1 sends nothing", "-1" in HELP["seed"])
# v2.1: the ceiling moved (1..262144); the DEFAULT deliberately did not.
check("max_tokens ceiling widened", RANGES["max_tokens"], (1, 262144, int))
check("max_tokens default is still the MLX truncation fix", DEF["max_tokens"], 4096)
ok("the lane note names the CHAT lane", "CHAT" in vg["note"])
ok("the lane note names the other two lanes",
   "Agent" in vg["note"] and "Hermes" in vg["note"])
# v2 (2026-08-20): the note said "no model reload" because the direct lane was the
# ONLY lane. It still needs no reload for CHAT — but the same values now also become
# the engine's launch defaults, so the honest sentence names the reload for the OTHER
# two lanes. Assertion updated to the new truth rather than deleted.
ok("the lane note says CHAT is immediate", "immediately" in vg["note"].lower())
ok("the lane note says the other lanes pick it up on the next model load",
   "next time the model loads" in vg["note"])
vm = view(dict(MLX, settings={"temperature": 0.2, "repeat_penalty": 1.2}))
check("view engine mlx", vm["engine"], "mlxlm")
check("view changed count", vm["changed"], 2)
lbl = {f["key"]: f["label"] for f in vm["fields"]}
check("view mlx penalty label", lbl["repeat_penalty"], "repetition_penalty")
check("view mlx window label", lbl["repeat_last_n"], "repetition_context_size")
val = {f["key"]: f["value"] for f in vm["fields"]}
check("view carries the override", val["temperature"], 0.2)
ok("view leaves untouched fields None", val["top_p"] is None)
check("view: junk override is not shown as changed",
      view(dict(GGUF, settings={"temperature": 500}))["changed"], 0)
for bad in (None, "x", 5, {"settings": 1}):
    try:
        view(bad if isinstance(bad, dict) else {"format": bad})
    except Exception as e:                                        # noqa: BLE001
        fails.append(f"view junk {bad!r} RAISED {e!r}")
# the view and the merge can never disagree about which fields exist
for e, name in ((GGUF, "gguf"), (MLX, "mlx")):
    vf = {f["label"] for f in view(e)["fields"]}
    mf = set(merge(e).keys()) | {"seed"}      # seed is view-only until set >= 0
    ok(f"view/merge field sets agree ({name})", mf <= vf, f"{mf - vf}")

# ── 11. USER_KEYS: settings must survive a RESCAN ───────────────────────────
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import seed_registry as sr                                        # noqa: E402

ok("settings is in USER_KEYS", "settings" in sr.USER_KEYS,
   "one Rescan click would reset every tuned model")
existing = [{"id": "keepme", "source": "local", "path": "/m/keepme",
             "settings": {"temperature": 0.2, "max_tokens": 8192}, "ctx": 65536},
            {"id": "voiced", "source": "lmstudio-import", "settings": {"top_k": 12}}]
fresh_local = [{"id": "keepme", "source": "local", "path": "/m/keepme", "ctx": None}]
fresh_lms = [{"id": "voiced", "source": "lmstudio-import"}]
merged = sr.merge(existing, [], fresh_lms, fresh_local)
by = {x["id"]: x for x in merged}
check("local settings survive a rescan", by["keepme"].get("settings"),
      {"temperature": 0.2, "max_tokens": 8192})
check("ctx still carried too", by["keepme"].get("ctx"), 65536)
check("lmstudio settings survive a rescan", by["voiced"].get("settings"), {"top_k": 12})
# a fresh scan can never invent settings, and a model with none stays clean
clean = sr.merge([{"id": "plain", "source": "local", "path": "/m/plain"}], [], [],
                 [{"id": "plain", "source": "local", "path": "/m/plain"}])
ok("no settings key invented", "settings" not in clean[0])
# download-sourced entries are kept WHOLE (never rescanned) — settings safe by default
keptwhole = sr.merge([{"id": "dl", "source": "download", "settings": {"min_p": 0.02}}],
                     [], [], [])
check("download entry keeps its settings", keptwhole[0]["settings"], {"min_p": 0.02})

# ── 12. wiring: the direct lane, the read side, the endpoint ────────────────
i_direct = src.index('@app.post("/api/chat/direct")')
relay = src[i_direct:i_direct + 6000]
ok("direct lane computes the fragment", "sampling_merge(" in relay)
ok("direct lane merges it into the request body", "**sampling}" in relay)
ok("the fragment is built from the REGISTRY entry",
   'm.get("id") == model' in relay and "_reg" in relay)
# the read side rides /api/models rather than a second GET route
ok("no GET /api/models/settings route", '@app.get("/api/models/settings' not in src)
ok("POST /api/models/settings exists", '@app.post("/api/models/settings")' in src)
i_models = src.index('@app.get("/api/models")')
# 6000, widened from 4000 when U15 added the per-row `file` liveness field and its
# comment to api_models (2026-08-29). The window is a crude 'inside this function'
# proxy; the two assertions below still name the exact keys they care about, so a
# wider window loses no precision — a narrow one only produces false reds.
models_h = src[i_models:i_models + 6000]
ok("/api/models carries the rendered view", '"sampling": sampling_view(m)' in models_h)
ok("/api/models carries the raw pin", '"settings":' in models_h)
ep = src[src.index('@app.post("/api/models/settings")'):]
ep = ep[:ep.index('@app.post("/api/chat/direct")')]
ok("endpoint writes through _registry_update", "_registry_update(mid, {\"settings\"" in ep)
ok("endpoint removes the key when nothing is left", "new or None" in ep)
ok("endpoint supports a full reset", '"settings": None' in ep)
ok("endpoint refuses an unknown model", "is not in the registry" in ep)
ok("endpoint refuses a voice model", "is_audio_entry" in ep)
ok("endpoint refuses an out-of-range value", "must be a number between" in ep)
ok("endpoint refuses a field this engine cannot honour", "can honour" in ep)
ok("endpoint returns the refreshed view", "sampling_view(upd)" in ep)

# the argv floor is untouched, and now explains itself
sc = open(os.path.join(ROOT, "scripts", "start_component.sh")).read()
# v2 (2026-08-20): the two numbers are still the floor, but a SAVED value now wins —
# so the assertion changed honestly from a literal pair to "the fallback is those two
# numbers, emitted from ONE site". The no-double-emit rule is pinned in
# test_model_load.py, which owns the floors.
ok("argv repetition floor still present, now as the fallback",
   '--repeat-penalty "${S_RP:-1.1}" --repeat-last-n "${S_RL:-256}"' in sc)
ok("argv floor points at the research doc", "2026-08-20-model-settings.md" in sc)
ok("argv floor names the lanes it is for", "Hermes lanes build their own" in sc)

# panel: renders the BRIDGE's field list, invents no field names of its own
panel = open(os.path.join(ROOT, "bridge", "panel", "index.html")).read()
ok("panel renders the sampling section", 'id="md-sampling"' in panel)
ok("panel calls renderSampling from the detail pane", "renderSampling(m);" in panel)
ok("panel omits the wrapper when the bridge sent no sampling",
   'samp ? `<div class="md-sec" id="md-sampling">' in panel)
ok("panel reads m.sampling.fields", "sv.fields" in panel)
ok("panel does NOT hardcode a field list",
   "'temperature'" not in panel.split("function renderSampling")[1].split(
       "function toggleSampling")[0])
ok("panel labels rows with the wire name", "esc(f.label)" in panel)
ok("panel shows the default inline", "default ${esc(String(f.default))}" in panel)
ok("panel posts to the settings endpoint", "'/api/models/settings'" in panel)
ok("panel empty box = reset (null, not a stored zero)",
   "let val = null;" in panel and "patch[key] = val" in panel)
ok("panel has a reset-all", "samplingResetAll" in panel)
ok("panel prints the honesty note", "esc(sv.note)" in panel)
ok("panel group is collapsed by default", "let samplingOpen = false;" in panel)
ok("a background re-render cannot wipe a half-typed value",
   "if (!samplingTyping()) renderDetail();" in panel)
ok("the model id is read from mSel, never interpolated into a handler",
   "mSel.kind === 'installed') ? mSel.id" in panel)
# zero new CSS: the section reuses the Capabilities grammar
for cls in ("cap-card", "cap-row", "cap-name", "cap-desc", "cap-inp", "cap-btn", "cap-count"):
    ok(f"reuses .{cls}", panel.count("." + cls + " ") >= 1 or ("." + cls) in panel)

# ── 13. the endpoint logic, executed against a temp registry ────────────────
# (the handler itself needs the app; the storage grammar is what matters and it is
#  _registry_update, already covered elsewhere — here we prove the round trip of
#  merge-then-read against a file written the way the endpoint writes it.)
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "models.json")
    with open(p, "w") as f:
        json.dump({"models": [dict(GGUF, settings={"temperature": 0.2})]}, f)
    e = json.load(open(p))["models"][0]
    check("round trip: merge sees the stored pin", merge(e)["temperature"], 0.2)
    check("round trip: view reports it changed", view(e)["changed"], 1)
    # "reset" is the ABSENCE of the key, never a stored null
    e2 = {k: v for k, v in e.items() if k != "settings"}
    check("round trip: absence = default", merge(e2)["temperature"], 0.7)
    check("round trip: a stored null is also harmless",
          merge(dict(GGUF, settings=None))["temperature"], 0.7)

if fails:
    print(f"FAIL ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("test_model_settings: all checks passed")
