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
import tempfile
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
                "Hermes3.6-35B", "DECKARD",
                # U23 (v1.5.3x): laguna — a PER-LAYER `attention.head_count` array
                # (40 entries of {48,64}) plus an arch-default sliding-window pattern
                # the header never spells. Both were wrong before this row existed:
                # the array CRASHED the engine, and the missing pattern priced all 40
                # layers as windowed — 160 MiB against the oracle's 2680.
                "Laguna-XS-2.1-APEX")
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
    snap = (Path.home() / "Library" / "Application Support" / "MOT Deck"
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


# ── U23: `attention.head_count` IS A PER-LAYER SHAPE TOO ─────────────────────
# The crash Debi's own registry produced: Laguna-XS-2.1-APEX-I-Compact publishes
# `attention.head_count` as 40 entries of {48, 64}. `int()` on it raised TypeError,
# the router swallowed that into a silent "No estimate", and this FILE died at the
# partial-header sweep so ~150 later checks never ran. llama.cpp reads the key with
# `get_key_or_arr` — the array is the LEGAL shape, and the bare int() was the bug.
print("\n── 2b. U23: per-layer header arrays, and shapes we refuse honestly ──")

QARR = dict(GQA, **{"attention.head_count": [32, 32, 32, 32]})
check("a per-layer `attention.head_count` array does not crash — and prices exactly as "
      "the scalar does when head_count_kv carries the cache",
      F.kv_cache_bytes(QARR, 1024) == F.kv_cache_bytes(GQA, 1024))
check("…and neither does a MIXED one (Laguna's real {48,64} shape)",
      F.kv_cache_bytes(dict(GQA, **{"attention.head_count": [48, 64, 64, 64]}), 1024)
      == F.kv_cache_bytes(GQA, 1024))

# MHA: no head_count_kv at all, so the per-layer QUERY heads ARE the cache heads, and
# the head dimension falls back to embd/heads — per layer, because the divisor is.
MHA = {"block_count": 2, "embedding_length": 4096,
       "attention.head_count": [32, 16]}
check("with no head_count_kv, a per-layer head_count sets BOTH the cache heads and the "
      "per-layer head dimension (a single 'first head count wins' prices layer 1 at "
      "layer 0's shape)",
      F.kv_cache_bytes(MHA, 1024)
      == (32 * ((4096 // 32) * 2 + (4096 // 32) * 2)
          + 16 * ((4096 // 16) * 2 + (4096 // 16) * 2)) * 1024)

# THE ARCH-DEFAULT SLIDING-WINDOW PATTERN. llama.cpp resolves is_swa(il) from a
# per-layer array if the file has one and otherwise from a PER-ARCH default period +
# dense_first flag (llama_hparams::set_swa_pattern). Laguna publishes neither, so the
# old "sliding_window set ⇒ every layer windowed" fallback was 94% light.
LAG = {"block_count": 8, "architecture": "laguna", "attention.head_count_kv": 8,
       "attention.key_length": 128, "attention.value_length": 128,
       "attention.sliding_window": 512, "embedding_length": 2048}
_lag_swa = F._pad(512 + 512)
check("laguna: full attention at every 4th layer from 0 (dense-first), windowed between",
      F.kv_cache_bytes(LAG, 65536)
      == 2 * 8 * (128 * 2 + 128 * 2) * 65536 + 6 * 8 * (128 * 2 + 128 * 2) * _lag_swa)
check("…and a dense-LAST arch (gemma3, period 6) puts the global layer at the END of "
      "each run instead — the flag is the arch's, not the header's",
      F.kv_cache_bytes(dict(LAG, architecture="gemma3"), 65536)
      != F.kv_cache_bytes(LAG, 65536))
check("an architecture with no default pattern keeps the old conservative fallback: "
      "every layer windowed",
      F.kv_cache_bytes(dict(LAG, architecture="brand-new-arch"), 65536)
      == 8 * 8 * (128 * 2 + 128 * 2) * _lag_swa)
check("an explicit per-layer pattern array still wins over the arch default",
      F.kv_cache_bytes(dict(LAG, **{"attention.sliding_window_pattern":
                                    [True] * 8}), 65536)
      == 8 * 8 * (128 * 2 + 128 * 2) * _lag_swa)
check("phi3's sliding window is DISABLED by llama.cpp (#13676), so we do not price a "
      "window it will not use",
      F.kv_cache_bytes(dict(LAG, architecture="phi3"), 65536)
      == 8 * 8 * (128 * 2 + 128 * 2) * 65536)

# ── the honest refusal, and the no-crash floor under it (doctrine 6b) ────────
_GOOD = {"block_count": 32, "embedding_length": 4096, "attention.head_count": 32,
         "attention.head_count_kv": 8, "attention.key_length": 128,
         "attention.value_length": 128, "vocab_size": 32000, "architecture": "llama",
         "context_length": 8192}
check("a header whose shapes we CAN price reports no problem",
      F.header_shape_problem(_GOOD) == ""
      and F.header_shape_problem(dict(_GOOD, **{"attention.head_count": [32] * 32})) == ""
      and F.header_shape_problem(None) == "")
_bad = F.header_shape_problem(dict(_GOOD, **{"attention.key_length": [128] * 32}))
check(f"a SCALAR-ONLY key arriving as an array is named, not guessed at — got: {_bad!r}",
      "attention.key_length" in _bad and "array" in _bad)
_bad2 = F.header_shape_problem(dict(_GOOD, block_count="thirty-two"))
check(f"…and so is a numeric key arriving as text — got: {_bad2!r}",
      "block_count" in _bad2 and "text" in _bad2)
_bad3 = F.header_shape_problem(dict(_GOOD, **{"attention.head_count":
                                              {"_len": 100000}}))
check("…and an array our parser had to SKIP for length is a refusal, not a 0 (the "
      "coerced zero is the lie: it looks like a number and always says 'fits')",
      "too long to keep" in _bad3)

# THE NO-CRASH FLOOR. Every value in a GGUF header was written by somebody else, so
# the arithmetic must survive ANY shape — the honest refusal is the product answer,
# but a raise is never one. This is the class, swept: every key the engine reads,
# against every wrong-shaped value we can think of.
_shapes = ([1, 2, 3], {"_len": 999999}, "text", True, -1, 0.5, [], [None, "x"], None)
_crashers = []
for _k in set(F._PER_LAYER_KEYS + F._SCALAR_KEYS + ("architecture",)):
    for _v in _shapes:
        _h = dict(_GOOD); _h[_k] = _v
        try:
            F.kv_cache_bytes(_h, 8192)
            F.recurrent_state_bytes(_h)
            F.compute_buffer_bytes(_h, 8192)
            F.attention_layers(_h)
            F.header_shape_problem(_h)
            F.formula_estimate(_h, 5 * F.GIB,
                               {"ctx": 8192, "kv_quant": "off", "parallel": 1})
            F.remote_fit(_h, 5 * F.GIB, {"budget_bytes": 60 * F.GIB})
        except Exception as _e:                                    # noqa: BLE001
            _crashers.append(f"{_k}={_v!r}: {type(_e).__name__}")
check(f"NO header field shape can raise out of the engine — "
      f"{len(set(F._PER_LAYER_KEYS + F._SCALAR_KEYS)) + 1} keys × {len(_shapes)} "
      f"hostile shapes", not _crashers)
for _c in _crashers[:8]:
    print("     crashed:", _c)
# THE SAME CLASS ON THE MLX SIDE. config.json is written by somebody else too, and
# `num_key_value_heads` is a per-layer list in more than one published repo — the
# mlx reader's except tuple did not carry TypeError.
_mlxcrash = []
for _v in ([8, 8, 4], "eight", {"a": 1}, None):
    for _k in ("num_hidden_layers", "num_key_value_heads", "num_attention_heads",
               "head_dim", "hidden_size", "max_position_embeddings"):
        _c = {"num_hidden_layers": 32, "num_key_value_heads": 8,
              "num_attention_heads": 32, "head_dim": 128, "hidden_size": 4096}
        _c[_k] = _v
        try:
            F.remote_mlx_fit(_c, 5 * F.GIB, {"budget_bytes": 60 * F.GIB})
        except Exception as _e:                                    # noqa: BLE001
            _mlxcrash.append(f"{_k}={_v!r}: {type(_e).__name__}")
check(f"…and the MLX config reader survives the same shapes (its except tuple was "
      f"missing TypeError) — {len(_mlxcrash)} crashers", not _mlxcrash)
_nested = {
    "text_config": {
        "num_hidden_layers": 64, "num_attention_heads": 24,
        "num_key_value_heads": 4, "head_dim": 256, "hidden_size": 5120,
        "max_position_embeddings": 262144,
        "layer_types": ["linear_attention"] * 3 + ["full_attention"],
        "linear_num_key_heads": 16, "linear_num_value_heads": 48,
        "linear_key_head_dim": 128, "linear_value_head_dim": 128,
        "linear_conv_kernel_dim": 4,
    }
}
_nested["text_config"]["layer_types"] *= 16
_nfit = F.remote_mlx_fit(_nested, 14 * F.GIB, {"budget_bytes": 60 * F.GIB},
                         ctx=4096)
_expected_kv = (16 * 4 * 256 * 2 * 2 * 4096
                + 48 * (48 * 128 * 128 * 4
                        + 3 * (2 * 16 * 128 + 48 * 128) * 2))
check("a nested Qwen 3.5 MLX config prices only its 16 full-attention KV layers "
      "plus all 48 recurrent states, rather than pricing zero or 64 KV layers",
      _nfit["breakdown"]["kv_bytes"] == _expected_kv)
_incomplete_linear = json.loads(json.dumps(_nested))
del _incomplete_linear["text_config"]["linear_value_head_dim"]
_fallback_fit = F.remote_mlx_fit(_incomplete_linear, 14 * F.GIB,
                                 {"budget_bytes": 60 * F.GIB}, ctx=4096)
check("a mixed-attention config missing one state dimension prices every layer as "
      "ordinary attention rather than silently pricing its 48 linear layers as zero",
      _fallback_fit["breakdown"]["kv_bytes"]
      == 64 * 4 * 256 * 2 * 2 * 4096)
check("MLX prefill work is bounded by the pinned server's 2,048-token chunk and is "
      "added to—not substituted for—the cross-architecture headroom",
      _nfit["breakdown"]["compute_bytes"]
      == int(14 * F.GIB * 0.10) + 2048 * 64 * 5120 * 2)
with tempfile.TemporaryDirectory() as _bad_mlx_tmp:
    _bad_mlx = Path(_bad_mlx_tmp)
    (_bad_mlx / "config.json").write_text("{not-json")
    (_bad_mlx / "weights.safetensors").write_bytes(b"x" * 4096)
    _bad_fit = F.mlx_estimate(str(_bad_mlx), {"ctx": 4096})
    check("a malformed MLX config degrades to weights plus the labelled conservative "
          "headroom instead of raising from an uninitialized architecture breakdown",
          _bad_fit is not None
          and _bad_fit["kv_bytes"] == 0
          and _bad_fit["compute_bytes"] == int(4096 * 0.10))
_MLXSRC = (ROOT / "bridge" / "core" / "fit.py").read_text()
check("mlx_estimate catches TypeError too, so a list in config.json is a KV of 0 and "
      "not a 500 on the models page",
      "except (OSError, TypeError, ValueError, _json.JSONDecodeError)" in _MLXSRC)

_unp = F.remote_fit(dict(_GOOD, **{"attention.key_length": [128] * 32}), 5 * F.GIB,
                    {"budget_bytes": 60 * F.GIB})
check("…and a shape we refuse lands on 'No estimate' that NAMES the field, never on a "
      "cheerful number",
      _unp["verdict"] == "unknown" and _unp["need_bytes"] is None
      and "unsupported header shape" in _unp["reason"]
      and "attention.key_length" in _unp["copy"]["line"])


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
      "OVERCOMMIT_ENV" in _src and F.OVERCOMMIT_ENV == "MOT_DECK_ALLOW_METAL_OVERCOMMIT")

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
    # v1.5.33 — the two NEW copy surfaces (audio verdicts, remote/per-quant verdicts)
    # go through the same collision check as the rest. A provenance check that only
    # covers the copy it was written for is a provenance check with a hole in it.
    for res, peak in ((0, 0), (3 * 1024 ** 3, 4 * 1024 ** 3)):
        a = F.audio_fit({"id": "voice-x", "size_bytes": 2 * 1024 ** 3, "role": "tts"},
                        {"budget_bytes": 6 * 1024 ** 3},
                        resident_bytes=res, resident_peak=peak)
        out += [str(v) for v in (a.get("copy") or {}).values() if v]
    _hp = {"block_count": 32, "embedding_length": 4096, "attention.head_count": 32,
           "attention.head_count_kv": 8, "attention.key_length": 128,
           "attention.value_length": 128, "vocab_size": 32000, "architecture": "llama"}
    for _b in (6 * 1024 ** 3, 60 * 1024 ** 3):
        r = F.remote_fit(_hp, 5 * 1024 ** 3, {"budget_bytes": _b})
        out += [str(v) for v in (r.get("copy") or {}).values() if v]
    out += [str(v) for v in (F.remote_fit(None, 0, {"budget_bytes": 1})
                             .get("copy") or {}).values() if v]
    # the strings the panel spells itself
    block = (ROOT / "bridge" / "panel" / "assets" / "fit-advisor.js").read_text()
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

for mod in ("core/memory.py", "core/fit.py", "core/memoryprefs.py",
            "core/runnermeasure.py", "routers/memory.py"):
    check(f"appsrc.FILES carries {mod} (without it every `not in` assertion about it "
          f"passes vacuously)", mod in appsrc.FILES)
for lane in ("core.memory", "core.fit", "core.memoryprefs", "core.runnermeasure",
             "routers.memory"):
    check(f"app.py's _LANES imports {lane}", f'"{lane}"' in LANES)

for route in ("/api/memory", "/api/memory/fit", "/api/memory/fits",
              "/api/memory/advisor"):
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
check("S6 applies one persisted speaking policy to main and aux model loads",
      'needs_confirmation(_adv.get("verdict"), new_id)' in APP
      and 'needs_confirmation(\n            _adv.get("verdict"), model)' in APP
      and "memoryprefs.acknowledge(new_id)" in APP
      and "_memoryprefs.acknowledge(model)" in APP)
check("the kernel-panic stop is NOT clearable by `confirm: true` — only by the env "
      "(a consent click answers 'this will be slow', not 'this may panic')",
      re.search(r'_refuse = _adv\.get\("refuse"\)\s*\n\s*if _refuse:', APP) is not None)
check("a fit advisory that cannot be computed never becomes a refusal",
      "advisory unavailable for" in APP)

PANEL_HTML = (ROOT / "bridge" / "panel" / "index.html").read_text()
FIT_PANEL = (ROOT / "bridge" / "panel" / "assets" / "fit-advisor.js").read_text()
PANEL = PANEL_HTML + "\n" + FIT_PANEL
check("the panel has a memory strip", 'id="mem-strip"' in PANEL)
check("…a verdict chip placeholder on every installed row", 'fitpill mfit' in PANEL)
check("…the need-vs-free line in the detail pane", "fitDetailHtml(m.id)" in PANEL)
check("…the consent panel with a plain, visible Load anyway",
      "fitConsentHtml()" in PANEL and ">Load anyway<" in PANEL)
check("…which is never gated behind a modifier key", "altKey" not in FIT_PANEL)
check("…warn-once: an acknowledged model is not re-litigated", "fitAcked" in PANEL)
check("…and its speaking policy is user-owned without adding a blocking mode",
      all(word in FIT_PANEL for word in ("Quiet · chips only", "Advise · when over",
                                         "Advise early · tight or over",
                                         "Custom headroom", "Load anyway",
                                         "don't warn again for models I've overridden")))
check("the extracted fit asset loads synchronously before its first consumer",
      '<script src="/assets/fit-advisor.js"></script>' in PANEL_HTML
      and PANEL_HTML.index('/assets/fit-advisor.js') < PANEL_HTML.index('function modelRowHtml')
      and 'async src="/assets/fit-advisor.js"' not in PANEL_HTML
      and 'defer src="/assets/fit-advisor.js"' not in PANEL_HTML)
check("runner allocation and process footprint are named as different truths",
      "Engine-reported allocation, not footprint" in FIT_PANEL
      and "process footprint above" in FIT_PANEL)
check("…the MOT Deck tile", "Memory for a model" in PANEL)
check("…and the ledger's SSE kind is dispatched", "kind === 'memory'" in PANEL)
check("the ledger tile does not pin the sampler fast just by existing",
      "/api/memory?watch=0" in PANEL)


# ══ 7. S2 — VERDICTS FOR FILES THAT ARE NOT ON THIS DISK, AND THE 2026-08-29 ══
#         DESIGN REVIEW (v1.5.33)
print("\n── 7. S2: remote per-quant verdicts, audio verdicts, chip-first UX ──")

# ---- 7a. THE PARTIAL HEADER. The HF browser reads a 2 MB PREFIX of a remote .gguf
# instead of the whole file. The property that makes that safe is not "it usually
# works": it is that a prefix which stopped before the tokenizer arrays is REFUSED,
# because llama.cpp writes general.* → <arch>.* → tokenizer.*, so anything that
# reached the token list has already read every architecture key — including
# `full_attention_interval`, whose absence prices 33 hybrid-Mamba layers where 8 hold
# KV. This is the 4.1× error the whole engine exists to avoid, arriving by a new door.
_prefix_checked = 0
for _m in _registry():
    _p = str(_m.get("path") or "")
    if not _p.endswith(".gguf") or not os.path.isfile(_p):
        continue
    _full = F.gguf_hparams(_p)
    if not _full:
        continue
    _s = {"ctx": 65536, "kv_quant": "off", "flash_attn": "auto", "parallel": 1}
    _sz = os.path.getsize(_p)
    _want = F.formula_estimate(_full, _sz, _s)["total_bytes"]
    for _n in (2, 8, 24):
        with open(_p, "rb") as _fh:
            _blob = _fh.read(_n * 1024 * 1024)
        _part = F.gguf_hparams_bytes(_blob)
        if not _part:
            continue                      # refused: the wider read is the answer
        _got = F.formula_estimate(_part, _sz, _s)["total_bytes"]
        check(f"{_m.get('id','?')[:38]}: the {_n} MB prefix prices it EXACTLY as the "
              f"whole header does ({_got / F.GIB:.3f} vs {_want / F.GIB:.3f} GB)",
              _got == _want)
        _prefix_checked += 1
        break
if not _prefix_checked:
    skip("partial-header equivalence", "no readable .gguf in this registry")

check("a prefix too short to reach ANY architecture key is refused, not guessed",
      F.gguf_hparams_bytes(b"GGUF" + b"\x03\x00\x00\x00" + b"\x00" * 32) is None)
check("…and a prefix that is not a GGUF at all is refused",
      F.gguf_hparams_bytes(b"NOTGGUF" + b"\x00" * 4096) is None)
check("…and an empty body is refused (an offline hub must not become a green chip)",
      F.gguf_hparams_bytes(b"") is None)

# ---- 7b. THE REMOTE VERDICT ITSELF
_hp = {"block_count": 32, "embedding_length": 4096, "attention.head_count": 32,
       "attention.head_count_kv": 8, "attention.key_length": 128,
       "attention.value_length": 128, "vocab_size": 32000, "architecture": "llama",
       "context_length": 8192}
_rf = F.remote_fit(_hp, 5 * F.GIB, {"budget_bytes": 60 * F.GIB})
check("a remote quant gets a real verdict, not a size", _rf["verdict"] == "fits"
      and "Fits" in _rf["copy"]["chip"])
check("…priced at the context it would actually load with, clamped by the model's own "
      "trained ceiling (so the browser chip and the installed-row chip are the same "
      "sentence about the same configuration)", _rf["settings"]["ctx"] == 8192)
check("…labelled an ESTIMATE, because there is no local file for the oracle to read",
      _rf["estimate"] is True and _rf["oracle"] is False
      and _rf["copy"]["provenance"] == "estimate")
_over = F.remote_fit(_hp, 5 * F.GIB, {"budget_bytes": 2 * F.GIB})
check("…with the GAP on the chip when it does not fit",
      _over["verdict"] == "over" and _over["copy"]["chip"].startswith("Over by ~"))
# The remedy leg needs a model whose default context is ABOVE the ladder's rungs — at
# 8k there is no smaller context to offer and an empty list is the honest answer, which
# is what the first version of this check got wrong about its own fixture.
_big = dict(_hp, context_length=262144)
_rem = F.remote_fit(_big, 5 * F.GIB, {"budget_bytes": 9 * F.GIB})
check(f"…and a REMEDY computed at a smaller context ('at 16k ctx: fits'), the half LM "
      f"Studio's badge leaves out — got: "
      f"{(_rem['remedies'] or [{}])[0].get('text', 'none')}",
      any(r["kind"] == "ctx" and r.get("fits_after") for r in _rem["remedies"]))
check("…and a model with no smaller context to offer gets an EMPTY remedy list, not a "
      "suggestion that does not close the gap",
      _over["settings"]["ctx"] == 8192
      and not any(r["kind"] == "ctx" for r in _over["remedies"]))
check("NOTHING on the download path can refuse: a remote verdict has no `refuse` and "
      "no verdict value that a caller could read as a block (download ≠ run)",
      _over.get("refuse") is None and _rf.get("refuse") is None)
check("an unreadable remote header is 'No estimate', never a cheerful default",
      F.remote_fit(None, 5 * F.GIB, {"budget_bytes": 60 * F.GIB})["verdict"] == "unknown")
check("…and so is a file the hub gave no size for",
      F.remote_fit(_hp, 0, {"budget_bytes": 60 * F.GIB})["verdict"] == "unknown")

from bridge.routers import hf as _HFR                                # noqa: E402
check("every quant of a repo shares ONE header read (the quant token is stripped) — "
      "keying the cache per FILENAME cost 27 s on a 26-quant repo, measured, where "
      "one read costs 1.2 s",
      _HFR._quant_family("Qwen3-4B-Instruct-2507-UD-Q4_K_XL.gguf")
      == _HFR._quant_family("Qwen3-4B-Instruct-2507-IQ4_NL.gguf")
      == "Qwen3-4B-Instruct-2507")
check("…but two SIZES in one repo stay two reads (pricing an 8B's KV with a 4B's shape "
      "would be a precise, confident, wrong number)",
      _HFR._quant_family("Qwen3-8B-Q8_0.gguf") != _HFR._quant_family("Qwen3-4B-Q8_0.gguf"))
check("a multi-part GGUF is ONE model, summed — nine shards would be nine chips, each "
      "wrong by a factor of nine",
      _HFR._part_family("m-00002-of-00009.gguf") == "m")
check("the remote read is STREAMED and capped, so a hub that ignores Range cannot hand "
      "us a 40 GB body", "aiter_bytes" in _HFR._hf_prefix.__doc__.lower()
      or "aiter_bytes" in (ROOT / "bridge" / "routers" / "hf.py").read_text())

# ---- 7c. AUDIO VERDICTS (the tab shipped with none at all)
_abud = {"budget_bytes": 6 * F.GIB}
_live = F.audio_fit({"id": "v", "size_bytes": 2 * F.GIB, "role": "tts"}, _abud,
                    resident_bytes=int(4.8 * F.GIB), resident_peak=int(5.1 * F.GIB))
check("a RESIDENT voice model reports its measurement, not a prediction",
      _live["provenance"] == "measured-now" and _live["copy"]["chip"].startswith("Live"))
_est = F.audio_fit({"id": "never-run", "size_bytes": 2 * F.GIB, "role": "tts"}, _abud)
check("one that has never run here is an ESTIMATE, and says so in its own hedge",
      _est["provenance"] == "estimate" and "Estimated" in _est["copy"]["hedge"])
# ⚠️ THE INCIDENT THIS NUMBER RECORDS. The first factor was 1.25, taken from published
# envelopes. The first live render on this Mac measured OmniVoice-bfloat16 at 4.81 GB
# resident against 2.04 GB of weights — 2.36×. The chip had said "Fits · ~2.4 GB" for
# a thing that costs 4.8, on the tab whose job is to stop exactly that.
check("the audio overhead factor is the MEASURED one, not the published 1.25 that made "
      "a 4.8 GB worker read as 2.4 GB", F.AUDIO_RUNTIME_FACTOR >= 2.0)
check("…and it is derived from this machine wherever a worker has actually run",
      isinstance(F._audio_factor(), tuple) and F._audio_factor()[0] >= F.AUDIO_FACTOR_MIN)
check("a size we do not know is 'No estimate' — silence is not a verdict",
      F.audio_fit({"id": "x", "role": "tts"}, _abud)["verdict"] == "unknown")
_MEMR = (ROOT / "bridge" / "routers" / "memory.py").read_text()
check("AN AUDIO WORKER SITS BESIDE THE RUNNER: the audio verdicts are priced against "
      "the plain budget, never budget_after_eject (nothing is freed by loading one, and "
      "crediting the chat model's memory would be a cheerful lie)",
      "_audio_fits(_bud)" in _MEMR and "_audio_fits(_fit.budget(freeing_bytes" not in _MEMR)
check("…and the measured peak is REMEMBERED, so the estimate becomes a measurement",
      "record_audio_peak" in _MEMR and "def record_audio_peak" in
      (ROOT / "bridge" / "core" / "fit.py").read_text())
check("/api/models/hf/fit is registered", '@app.get("/api/models/hf/fit")' in
      (ROOT / "bridge" / "routers" / "hf.py").read_text())

# ---- 7d. THE UX RULING: chip on the row, words on demand, reachable without a mouse
_P = ((ROOT / "bridge" / "panel" / "index.html").read_text() + "\n" +
      (ROOT / "bridge" / "panel" / "assets" / "fit-advisor.js").read_text())
check("THE ROW CARRIES THE CHIP AND NOTHING ELSE — paintFitChips writes the chip and "
      "binds a tooltip; it no longer prints copy.line into the row",
      "chip.textContent = v.copy.chip" in _P
      and "tipBind(chip, fitTipHtml(v), fitTipPlain(v));" in _P
      and "chip.title = (v.copy.line" not in _P)
check("…and the tooltip is NOT hover-only: click and keyboard open it too (WKWebView "
      "does not reliably render `title`, and a tap has no hover)",
      "addEventListener('mouseenter'" in _P and "addEventListener('click'" in _P
      and "addEventListener('focus'" in _P and "tabindex" in _P)
check("…closed by Escape, by scroll and by resize, so it can never be stranded",
      "e.key === 'Escape') tipHide()" in _P and "'scroll', () => tipHide()" in _P)
check("…and BOTH the chip and its hover come off ONE verdict object, so a green chip "
      "cannot carry a red sentence", "function fitTipHtml(v)" in _P
      and "function fitTipPlain(v)" in _P)
check("the detail pane discloses the arithmetic instead of printing it",
      "function fitToggleMath()" in _P and "Show the arithmetic" in _P)
check("the strip's headline is STATUS + DELTA, in Debi's grammar",
      "Free now: ~${memGB(freeNow)} GB" in _P and "GB on eject" in _P)
check("…with the INTENT pair one level down, on its hover and in Details",
      "Run alongside: ~" in _P and "Replace active (eject " in _P)
check("the composer's model picker carries the same chips (a switch is CHOSEN there)",
      "const fv = memFits[m.id];" in _P and "positionModelPop()" in _P)
check("the Audio tab has verdict chips and a painter for them",
      "fitpill afit fit-unk" in _P and "function paintAudioFitChips()" in _P)
check("the HF browser's chips come from the engine, and the hardcoded 64 GB divisor is "
      "GONE (it would have said 'Fits' just as confidently on a 16 GB Mac)",
      "paintHfFits(repo, box)" in _P and "gb / 64" not in _P)
# THE DOWNLOAD BUTTON, IN THE PANEL'S OWN MARKUP. A verdict may colour a chip; it may
# never reach the Get. This asserts the Get is rendered with no state that a verdict
# could set — the chip and the button are built in the same template, so a future
# "disable it when it's red" edit lands right here.
_getline = _P.split("class=\"hfget\"")[1][:120] if 'class="hfget"' in _P else ""
check("Get is never disabled by a verdict: download ≠ run, and both are facts",
      bool(_getline) and "disabled" not in _getline)


print(f"\n{PASS} passed, {len(FAILS)} failed, {len(SKIPS)} skipped")
for f in FAILS:
    print("  FAILED:", f)
sys.exit(1 if FAILS else 0)
