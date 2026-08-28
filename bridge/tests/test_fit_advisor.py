"""THE RAM FIT ADVISOR'S GATE — bridge/core/fit.py + bridge/core/memory.py (v1.5.30).

The feature's whole claim is that a verdict can be TRUSTED. The way it stops being
true is never a crash — it is a number that is quietly wrong in the direction that
says "fits". So the sections below are ordered by how badly each failure lies:

  1. THE VALIDATION TABLE (spec V2-4). Our formulas vs llama.cpp's own fitter, on the
     real models installed on this machine, at four context sizes and two KV types.
     PINNED: every architecture family here — hybrid-Mamba (qwen35), hybrid MoE
     (qwen35moe), plain GQA (qwen3), muse-glimmer, and sliding-window (gemma4) — must
     stay within 15% of the oracle, and today every one of them is inside 0.4%. This
     is the section that catches "a new llama.cpp changed the KV layout" before a user
     does. It SKIPS models it cannot find rather than failing: a gate that depends on
     one person's disk is a gate that fails for everyone else.

  2. THE ARITHMETIC ITSELF, on synthetic headers — GQA, per-layer kv-head arrays,
     hybrid, SWA (including the separate `key_length_swa`), MLA, the KV element table,
     256-cell padding, and the no-flash-attention V floor. Pure, no files, no binary.

  3. THE BANDS AND THE ONE HARD STOP. fits/tight/over at 80%/100% of budget; nothing
     but a hand-set Metal over-commit may refuse, and even that has an env override.

  4. COPY PROVENANCE (spec §3b). Every user-facing string we ship, checked against the
     LM Studio strings extracted in docs/research/2026-08-28-memory-ux-patterns.md.
     ZERO verbatim collisions is the requirement; this test is the receipt.

  5. THE LEDGER: phys_footprint and never RSS, the pid → component map, delta
     suppression, and — the crash class a field report handed us — a clean process
     EXIT under ctypes, asserted by running the module in a subprocess.

  6. THE WIRING, source-level over bridge/appsrc.py: the routes exist, the lanes are
     registered in BOTH lists, the switch gate is advisory rather than a wall, and the
     panel carries the surfaces this slice promised.

Run: data/bridge-venv/bin/python bridge/tests/test_fit_advisor.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for _k in [k for k in os.environ if k.lower().endswith("_proxy")]:
    os.environ.pop(_k, None)

from bridge.core import fit as F                                  # noqa: E402
from bridge.core import memory as M                               # noqa: E402

PASS = 0
FAILS = []
SKIPS = []


def check(name, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAILS.append(name)
        print(f"  FAIL {name}")


def skip(name, why):
    SKIPS.append(name)
    print(f"  --  {name}  (skipped: {why})")


MIB = 1024 * 1024


# ══ 1. THE VALIDATION TABLE — predicted vs the oracle, on real models ════════
print("\n── 1. validation: our formula vs llama.cpp's own fitter ──")

# (registry id fragment, architecture) — every family we can currently reach.
TABLE_MODELS = ("Qwen3.5-9B", "Fable-Fus-711", "Muse-Glimmer", "Parable-Qwen3-4B",
                "Hermes3.6-35B", "DECKARD")
TABLE_CTX = (8192, 16384, 32768, 65536)
TOLERANCE_PCT = 15.0          # the spec's gate; measured worst case today is 0.37%


def _registry():
    """Both registries: the repo's and the SNAPSHOT's.

    ⚠️ Reading only the repo's data/models.json skipped this entire section — the repo
    tree carries three placeholder entries and the real library lives in the snapshot
    the app actually runs from. A validation gate that silently skips is worse than no
    gate: it reports "0 failed" for a table it never computed."""
    out = []
    try:
        from bridge.core.procs import _registry_models
        out += _registry_models()
    except Exception:                                             # noqa: BLE001
        pass
    snap = (Path.home() / "Library" / "Application Support" / "Harness"
            / "data" / "models.json")
    try:
        out += json.loads(snap.read_text()).get("models", [])
    except Exception:                                             # noqa: BLE001
        pass
    return out


rows = []
for frag in TABLE_MODELS:
    entry = next((m for m in _registry()
                  if frag in str(m.get("id") or "")
                  and str(m.get("format") or "") == "gguf"
                  and os.path.isfile(str(m.get("path") or ""))), None)
    if entry is None:
        skip(f"validation row: {frag}", "not installed on this machine")
        continue
    path = entry["path"]
    hp = F.gguf_hparams(path)
    if not hp:
        check(f"{frag}: header reads", False)
        continue
    for ctx in TABLE_CTX:
        oracle = F.oracle_gguf(path, {"ctx": ctx})
        if oracle is None:
            skip(f"{frag} @ {ctx}", "llama-fit-params unavailable")
            continue
        ours = F.kv_cache_bytes(hp, ctx) + F.recurrent_state_bytes(hp)
        ref = oracle["kv_bytes"]
        off = 100.0 * (ours - ref) / max(1, ref)
        rows.append((entry["id"][:32], hp.get("architecture"), ctx, ref, ours, off))
        check(f"{hp.get('architecture')} {frag} @ {ctx}: KV within {TOLERANCE_PCT}% "
              f"of the oracle (off {off:+.2f}%)", abs(off) <= TOLERANCE_PCT)

if rows:
    print("\n  PINNED TABLE (KV cache, MiB) — regenerate this block when it moves:")
    print(f"  {'model':34}{'arch':13}{'ctx':>7}{'oracle':>9}{'ours':>9}{'off%':>8}")
    for r in rows:
        print(f"  {r[0]:34}{str(r[1]):13}{r[2]:7}{r[3]/MIB:9.1f}{r[4]/MIB:9.1f}{r[5]:+8.2f}")

# The KV-quant leg of the table: q8_0 must be priced at 34/32 bytes per element, not
# at 1.0 — an under-count of 6% that always errs toward "fits".
_nine = next((m for m in _registry() if "Qwen3.5-9B" in str(m.get("id") or "")
              and os.path.isfile(str(m.get("path") or ""))), None)
if _nine:
    _o = F.oracle_gguf(_nine["path"], {"ctx": 32768, "kv_quant": "q8_0"})
    if _o:
        _hp = F.gguf_hparams(_nine["path"])
        _ours = F.kv_cache_bytes(_hp, 32768, "q8_0", "q8_0") + F.recurrent_state_bytes(_hp)
        _off = 100.0 * (_ours - _o["kv_bytes"]) / max(1, _o["kv_bytes"])
        check(f"q8_0 KV at 32k matches the oracle (off {_off:+.2f}%)", abs(_off) <= 2.0)
    else:
        skip("q8_0 leg", "oracle unavailable")
else:
    skip("q8_0 leg", "the 9B is not installed")


# ══ 2. the arithmetic, on synthetic headers ══════════════════════════════════
print("\n── 2. the KV formulas, on hand-built headers ──")

GQA = {"block_count": 4, "attention.head_count": 32, "attention.head_count_kv": 8,
       "attention.key_length": 128, "attention.value_length": 128,
       "embedding_length": 4096}
check("GQA: layers × kv_heads × (k+v) × bytes × padded cells",
      F.kv_cache_bytes(GQA, 1024) == 4 * 8 * (128 * 2 + 128 * 2) * 1024)
check("GQA uses head_count_kv, NEVER head_count (8× on a 70B otherwise)",
      F.kv_cache_bytes(GQA, 1024) != F.kv_cache_bytes(
          dict(GQA, **{"attention.head_count_kv": 32}), 1024))
check("context is padded to 256 cells (GGML_PAD)",
      F.kv_cache_bytes(GQA, 1000) == F.kv_cache_bytes(GQA, 1024))

ARR = dict(GQA, **{"attention.head_count_kv": [8, 0, 8, 0]})
check("a per-layer kv-head array of 0 means that layer holds NO cache",
      F.kv_cache_bytes(ARR, 1024) == F.kv_cache_bytes(GQA, 1024) / 2)

HYB = {"block_count": 33, "nextn_predict_layers": 1, "full_attention_interval": 4,
       "attention.head_count_kv": 4, "attention.key_length": 256,
       "attention.value_length": 256, "embedding_length": 4096,
       "ssm.inner_size": 4096, "ssm.state_size": 128, "ssm.conv_kernel": 4,
       "ssm.group_count": 16}
check("hybrid-Mamba: 8 of 32 layers hold KV (the 4.1× correction)",
      F.attention_layers(HYB) == (8, 24))
check("hybrid-Mamba: 32 KiB per token, exactly as measured on the 9B",
      F.kv_cache_bytes(HYB, 1024) == 1024 * 32 * 1024)
check("recurrent state is CONSTANT in context and 50.25 MiB on the 9B's shape",
      F.recurrent_state_bytes(HYB) == 52690944
      and F.recurrent_state_bytes(HYB) == F.recurrent_state_bytes(HYB, 1) )
check("recurrent state scales with parallel slots",
      F.recurrent_state_bytes(HYB, 4) == 4 * F.recurrent_state_bytes(HYB, 1))

SWA = {"block_count": 6, "attention.head_count_kv": [16, 16, 16, 16, 16, 4],
       "attention.key_length": 512, "attention.value_length": 512,
       "attention.key_length_swa": 256, "attention.value_length_swa": 256,
       "attention.sliding_window": 1024, "embedding_length": 5376,
       "attention.sliding_window_pattern": [True, True, True, True, True, False]}
_swa_cells = 1024 + 512                       # window + ubatch, already 256-aligned
check("SWA: window layers cap their cells; only global layers pay full context",
      F.kv_cache_bytes(SWA, 65536)
      == 5 * 16 * (256 * 2 + 256 * 2) * _swa_cells + 1 * 4 * (512 * 2 + 512 * 2) * 65536)
check("SWA: the *_swa head dimensions are used on window layers (2× if ignored)",
      F.kv_cache_bytes(SWA, 8192) < F.kv_cache_bytes(
          {k: v for k, v in SWA.items()
           if k not in ("attention.key_length_swa", "attention.value_length_swa")}, 8192))
check("SWA KV grows ONLY with the global layers as context rises",
      (F.kv_cache_bytes(SWA, 65536) - F.kv_cache_bytes(SWA, 8192))
      == 1 * 4 * (512 * 2 + 512 * 2) * (65536 - 8192))

MLA = {"block_count": 2, "attention.kv_lora_rank": 512,
       "rope.dimension_count": 64, "attention.head_count_kv": 1,
       "attention.head_count": 128, "embedding_length": 7168}
check("MLA: one latent per token per layer, and no separate V",
      F.kv_cache_bytes(MLA, 1024) == (512 + 64) * 2 * 1024 * 2)

check("q8_0 is 34/32 bytes per element, not 1.0 (block scales are real)",
      F.kv_elem_bytes("q8_0") == 34 / 32 and F.kv_elem_bytes("q4_0") == 0.5625)
check("an unknown cache type falls back to f16 rather than to zero",
      F.kv_elem_bytes("nonsense") == 2.0)
check("without flash attention a quantised V cache is priced at f16 — the engine "
      "silently keeps it there (ollama #13337)",
      F.kv_cache_bytes(GQA, 1024, "q8_0", "q8_0", flash_attn=False)
      > F.kv_cache_bytes(GQA, 1024, "q8_0", "q8_0", flash_attn=True))
check("a header we cannot understand returns 0, never a guess",
      F.kv_cache_bytes({}, 4096) == 0)


# ══ 3. the bands, and the one hard stop ══════════════════════════════════════
print("\n── 3. bands, budget, and the single refusal ──")

B = 100 * 1024 ** 3
check("fits below 80% of budget", F.band(79 * 1024 ** 3, B) == "fits")
check("tight between 80% and 100%", F.band(95 * 1024 ** 3, B) == "tight")
check("over above 100%", F.band(101 * 1024 ** 3, B) == "over")
check("no budget → 'unknown', never a cheerful 'fits'", F.band(1, 0) == "unknown")
check("the Apple fraction is 0.85 and the fits band is Ollama's 80%",
      F.APPLE_FRACTION == 0.85 and F.BAND_FITS == 0.80)

_src = (ROOT / "bridge" / "core" / "fit.py").read_text()
check("`refuse` is set in exactly ONE place in the engine",
      len(re.findall(r"^\s+refuse = \{", _src, re.M)) == 1)
check("…and that place requires a HAND-SET context over the METAL ceiling",
      re.search(r"hand_set_ctx.*\n?.*need > ceiling", _src) is not None)
check("…and it is overridable by environment",
      "OVERCOMMIT_ENV" in _src and F.OVERCOMMIT_ENV == "HARNESS_ALLOW_METAL_OVERCOMMIT")

_settings = F.settings_for({"load": {"ctx": 262144}})
check("a context the user typed is marked hand-set", _settings["hand_set_ctx"] is True)
check("a context that came from the model is NOT hand-set — the engine may clamp its "
      "own default, but it may not refuse on it",
      F.settings_for({"ctx": 65536})["hand_set_ctx"] is False)

_bud = F.budget(freeing_bytes=8 * 1024 ** 3)
check("what a switch frees is added to the budget (a replacement is not an addition)",
      _bud["freeing_bytes"] == 8 * 1024 ** 3)
check("the budget is 0.85 × min(ceiling, available)",
      _bud["budget_bytes"] == int(min(_bud["ceiling_bytes"], _bud["available_bytes"])
                                  * F.APPLE_FRACTION))


# ══ 4. COPY PROVENANCE — zero verbatim collisions ════════════════════════════
print("\n── 4. copy provenance (spec §3b) ──")

# Verbatim from LM Studio's shipped renderer bundle, as extracted in
# docs/research/2026-08-28-memory-ux-patterns.md §1. RESEARCH EVIDENCE, NOT COPY:
# nothing we ship may equal any of these, and nothing here is adapted into our voice
# by rewording — our sentences were written from the grammar, not from the strings.
LMS_STRINGS = (
    "Full GPU Offload Possible",
    "Partial GPU Offload Possible",
    "Likely Fit",
    "Likely too large",
    "This model might fit entirely in your GPU's memory. This could considerably "
    "speed up inference.",
    "This model might fit partially in your GPU's memory. This could often "
    "considerably speed up inference.",
    "This model is likely to fit in your machine's memory.",
    "The memory requirements for successfully using this model file might exceed the "
    "available resources on your machine. Downloading this file is NOT recommended.",
    "There may be other factors that prevent it from loading, such as the model's "
    "architecture, model file integrity, or the amount of memory available on your "
    "computer.",
    "Not enough resources to load the model with the current settings",
    "It appears your system does not have enough memory to load this model.",
    "You can adjust the model loading guardrails in settings or hold ⌥ to load anyway.",
    "Loading a model that is too large may overload your system and cause it to freeze.",
    "(Not recommended) Always allow 'Load Anyway' without holding Alt/Option",
    "Setting a high value for context length can significantly impact memory usage",
    "Memory estimate unavailable for this model",
    "Estimated Memory Usage",
    "No precautions against system overload",
    "Mild precautions against system overload",
    "Moderate precautions against system overload",
    "Strong precautions against system overload",
    "Models will not load if loading them would exceed this limit.",
    "Loading models beyond system resource limits may cause system instability or "
    "freezing. Guardrails prevent accidental overloading. Adjust these limits here if "
    "necessary, but be aware that loading models near the system's limit may reduce "
    "stability.",
)

# Every user-facing sentence this slice can print, from the engine and the panel.
def _our_strings():
    out = []
    fake = {"id": "x", "path": "", "format": "gguf"}
    est = {"total_bytes": 20 * 1024 ** 3, "weights_bytes": 16 * 1024 ** 3,
           "kv_bytes": 3 * 1024 ** 3, "compute_bytes": 1024 ** 3,
           "vision_bytes": 1024 ** 3, "oracle": True}
    bud = {"budget_bytes": 18 * 1024 ** 3, "replaces": "Some-Model"}
    s = {"ctx": 65536}
    for verdict in ("fits", "tight", "over", "unknown"):
        c = F.copy_for(verdict, est["total_bytes"], bud, s, est, [])
        out += [str(v) for v in c.values() if v]
        c2 = F.copy_for(verdict, est["total_bytes"], dict(bud, replaces=""), s,
                        dict(est, oracle=False), [])
        out += [str(v) for v in c2.values() if v]
    # the strings the panel spells itself
    panel = (ROOT / "bridge" / "panel" / "index.html").read_text()
    block = panel.split("THE RAM FIT ADVISOR — panel side")[1].split("function modelRowHtml")[0]
    out += re.findall(r"'([A-Z][^'\\\\]{12,})'", block)
    out += re.findall(r'"([A-Z][^"\\\\]{12,})"', block)
    return [o.strip() for o in out if o and o.strip()]


OURS = _our_strings()
collisions = []
for mine in OURS:
    for theirs in LMS_STRINGS:
        if mine == theirs:
            collisions.append((mine, "identical"))
        elif len(theirs) > 40 and theirs.lower() in mine.lower():
            collisions.append((mine, "contains " + theirs[:40]))
check(f"ZERO verbatim collisions with the extracted LM Studio table "
      f"({len(OURS)} of our strings × {len(LMS_STRINGS)} of theirs)", not collisions)
for c in collisions:
    print("     collision:", c)

check("the gap is on the chip, with its magnitude (their badge reads the same at "
      "0.2 GB over and at 40 GB over)",
      F.copy_for("over", 25 * 1024 ** 3, {"budget_bytes": 18 * 1024 ** 3}, {"ctx": 8192},
                 {"total_bytes": 25 * 1024 ** 3, "oracle": True}, [])["chip"]
      == "Over by ~7.0 GB")
check("no shouting: nothing we print is in caps or ends in an exclamation",
      not any(re.search(r"\b(NOT|NEVER|MUST)\b", o) or o.endswith("!") for o in OURS))
check("every estimate is hedged with ~ or the word 'about'",
      all(("~" in o or "about" in o.lower()) for o in OURS
          if re.search(r"\d+\.\d+ GB", o)))


# ══ 5. the ledger ════════════════════════════════════════════════════════════
print("\n── 5. the ledger ──")

_msrc = (ROOT / "bridge" / "core" / "memory.py").read_text()
check("phys_footprint is field 7 and RSS is field 6 of rusage_info_v4",
      F is not None and M._RU_FOOTPRINT == 7 and M._RU_RESIDENT == 6)
check("the lifetime peak is read too (it is what a worker really cost)",
      M._RU_PEAK == 28)
check("nothing in the ledger can signal, suspend or kill a process",
      not re.search(r"os\.kill|SIGKILL|SIGTERM|\bpkill\b|kill -", _msrc))
check("the metric is named 'memory footprint', never 'RAM used'",
      "memory footprint" in M.snapshot().get("metric_note", "").lower())

_me = M.proc_footprint(os.getpid())
check("our own footprint reads, and exceeds zero", _me and _me["footprint"] > 0)
check("a pid that cannot exist returns None, not zero (a missing component must not "
      "silently shrink the ledger)", M.proc_footprint(0x7FFFFFF0) is None)

_sys = M.system_view()
check("the system view takes the MINIMUM of the kernel's and Activity Monitor's "
      "'available' — the optimistic one is 27 GB higher here, and believing it is how "
      "a 'fits' becomes a lie",
      _sys["available_bytes"] == min(x for x in (_sys["available_kernel_bytes"],
                                                 _sys["available_activity_bytes"]) if x))
check("pressure is a word from the kernel's own scale",
      _sys["pressure"] in ("normal", "warn", "critical"))
check("Metal's ceiling is read live, not hardcoded",
      "recommendedMaxWorkingSetSize" in _msrc and "55662788608" not in _msrc)

_a = {"system": {"pressure": "normal", "available_pct": 40, "swap_used_bytes": 1},
      "components": [{"name": "runner", "footprint_bytes": 1000 * 1024 * 1024}]}
_b = json.loads(json.dumps(_a))
check("delta suppression: an unchanged sample emits nothing", not M._changed(_a, _b))
_b["components"][0]["footprint_bytes"] += 4 * 1024 * 1024
check("…a 4 MB wobble is not news", not M._changed(_a, _b))
_b["components"][0]["footprint_bytes"] += 200 * 1024 * 1024
check("…a 200 MB move is", M._changed(_a, _b))
_c = json.loads(json.dumps(_a)); _c["system"]["pressure"] = "warn"
check("…and a pressure change always is", M._changed(_a, _c))
check("no subscribers means no sampling at all",
      "if subs <= 0:" in _msrc and "start_sampler" in _msrc)
# The subscriber count is read by NAME off the hub, and the name is the whole feature:
# a getattr default that never matches turns the push channel off in silence.
from bridge.core import events as _E                              # noqa: E402
check("…and the sampler asks the hub with a name the hub actually has",
      "HUB.subscribers" in _msrc.replace('getattr(HUB, "subscribers", 0)',
                                         "HUB.subscribers")
      and isinstance(_E.HUB.subscribers, int))

# THE CTYPES CRASH CLASS (field report, 2026-08-28): probes under Apple's CLT python
# segfaulted at INTERPRETER SHUTDOWN, after their work had finished, and the user saw
# a crash dialog. The work being correct is not the property we need — a clean exit is.
_p = subprocess.run([sys.executable, "-m", "bridge.core.memory"],
                    cwd=str(ROOT), capture_output=True, text=True, timeout=120)
check(f"the ledger module runs AND EXITS CLEANLY in a subprocess (rc={_p.returncode})",
      _p.returncode == 0)
check("…and it printed a real snapshot", '"system"' in (_p.stdout or ""))


# ══ 6. the wiring ════════════════════════════════════════════════════════════
print("\n── 6. wiring: lanes, routes, the advisory gate, the panel ──")

from bridge import appsrc                                          # noqa: E402
APP = appsrc.APP_SOURCE
LANES = (ROOT / "bridge" / "app.py").read_text()

for mod in ("core/memory.py", "core/fit.py", "routers/memory.py"):
    check(f"appsrc.FILES carries {mod} (without it every `not in` assertion about it "
          f"passes vacuously)", mod in appsrc.FILES)
for lane in ("core.memory", "core.fit", "routers.memory"):
    check(f"app.py's _LANES imports {lane}", f'"{lane}"' in LANES)

for route in ("/api/memory", "/api/memory/fit", "/api/memory/fits"):
    check(f"{route} is registered", f'@app.get("{route}")' in APP)

check("the switch route no longer walls off an over-budget load",
      "would exceed model-RAM budget" not in APP.split("api_switch_model")[1][:4000])
check("…it asks for consent instead, with the advisory attached",
      re.search(r'"needs_confirm": True,\s*\n\s*"advisory"', APP) is not None)
check("…and `confirm: true` works on the API, not only in the panel (the lms#499 "
      "lesson: an advisory GUI over a hard-blocking API)",
      "_wants_confirm(_body)" in APP and "def _wants_confirm" in APP)
check("the aux slot gets the same advisory, and is NOT credited the runner's memory",
      'slot="aux"' in APP and 'slot == "main" and live_up' in APP)
check("the kernel-panic stop is NOT clearable by `confirm: true` — only by the env "
      "(a consent click answers 'this will be slow', not 'this may panic')",
      re.search(r'_refuse = _adv\.get\("refuse"\)\s*\n\s*if _refuse:', APP) is not None)
check("a fit advisory that cannot be computed never becomes a refusal",
      "advisory unavailable for" in APP)

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the panel has a memory strip", 'id="mem-strip"' in PANEL)
check("…a verdict chip placeholder on every installed row", 'fitpill mfit' in PANEL)
check("…the need-vs-free line in the detail pane", "fitDetailHtml(m.id)" in PANEL)
check("…the consent panel with a plain, visible Load anyway",
      "fitConsentHtml()" in PANEL and ">Load anyway<" in PANEL)
check("…which is never gated behind a modifier key", "altKey" not in PANEL.split(
      "THE RAM FIT ADVISOR — panel side")[1].split("function modelRowHtml")[0])
check("…warn-once: an acknowledged model is not re-litigated", "fitAcked" in PANEL)
check("…the MOT Deck tile", "Memory for a model" in PANEL)
check("…and the ledger's SSE kind is dispatched", "kind === 'memory'" in PANEL)
check("the ledger tile does not pin the sampler fast just by existing",
      "/api/memory?watch=0" in PANEL)

print(f"\n{PASS} passed, {len(FAILS)} failed, {len(SKIPS)} skipped")
for f in FAILS:
    print("  FAILED:", f)
sys.exit(1 if FAILS else 0)
