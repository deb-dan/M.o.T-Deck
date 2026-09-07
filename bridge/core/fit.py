"""CORE — THE FIT ENGINE. Will this model run on this machine, at these settings?

One source of truth for every fit verdict in the app (docs/FABLE-RAM-FIT-ADVISOR-SPEC.md,
SPEC v2). Three research documents are its BINDING sources and they are cited inline:
docs/research/2026-08-28-fit-math-oss.md (the formulas + the oracle),
docs/research/2026-08-28-macos-memory-accounting.md (the budget's "have" side),
docs/research/2026-08-28-memory-ux-patterns.md (the copy grammar).

⚠️ WE DO NOT RE-DERIVE KV MATH BY HAND, AND THE REASON IS MEASURED. The naive
"every layer holds KV" formula is **4.1× wrong** on our own resident models: Qwen3.5/3.6
are hybrid-Mamba, so only ceil(layers / full_attention_interval) layers hold a KV cache
at all (8 of 32 on the 9B; 16 of 64 on the 27B). A confidently wrong "fits" is the worst
bug this feature can ship, so:

  1. **The ORACLE decides for GGUF.** llama.cpp b10662 ships its own fitter, and we
     already have the standalone binary (`data/llamacpp/build/bin/llama-fit-params`).
     It loads the model with `no_alloc` — it reads real tensor and buffer sizes without
     allocating a byte — and prints the projection in ~0.3 s. It is llama.cpp's own
     accounting of what llama.cpp will do, which is the only ground truth that cannot
     drift from the runner. Results are cached by model × ctx × kv-quant × build.
  2. **Our formulas are the CROSS-CHECK and the instant estimate**, for the UI to paint
     before the oracle returns, for models the oracle cannot answer for (MLX has no
     oracle at all), and for the "what if I halve the context" arithmetic the remedies
     need to do dozens of times. They are the corrected set (GQA / SWA / hybrid-Mamba /
     MLA / recurrent state), validated to the MiB against the oracle on both resident
     models — see bridge/tests/test_fit_advisor.py's pinned table.
  3. **A disagreement is logged and the ORACLE WINS.** Never the other way round.

⚠️ THE VERDICT NEVER DISABLES A BUTTON. Debi's advisory-gates ruling: gates inform and
recommend. Downloads stay downloadable, loads stay attemptable through consent. There is
exactly ONE refusal in this file — a HAND-SET context that over-commits Metal's wired
ceiling — because that specific failure is a documented kernel PANIC, not an OOM error
(Unsloth refuses it too, vendored core/inference/llama_cpp.py:9954-10044, citing an
M1 Max report). A warning that precedes a kernel panic is not a warning. It carries an
env override, and it is the only thing here that can say no.

⚠️ ESTIMATES ARE LABELLED ESTIMATES. Every number this module returns carries `source`
("oracle" | "formula") and every formula number carries a band. No false precision: an
exact-looking byte count that is quietly a guess is how an estimator earns the user's
contempt the first time it is wrong.
"""
from __future__ import annotations

import math
import os
import subprocess
import threading
import time

from .appctx import ROOT

GIB = 1024 ** 3
MIB = 1024 ** 2

# ── the GGUF header, its cache, and its shape rules ──────────────────────────
# Lifted whole into core/ggufhdr.py (U23) when this file crossed the app layer's
# 1500-line fence; RE-EXPORTED here because `fit.gguf_hparams` is the name every caller
# and ~20 gate assertions already spell. Reading a header and pricing one are two
# concerns, and this is where the seam always was.
from .ggufhdr import (                                             # noqa: F401
    MAX_KEPT_ARRAY, MAX_KV_COUNT, MAX_META_BYTES, MAX_STRING_BYTES, SWA_DISABLED_ARCH,
    SWA_PATTERN_DEFAULT, _Cur, _WANTED, _as_list, _gguf_hparams_parse,
    _gguf_hparams_read, _hp_priceable, _hp_usable, _num, _PER_LAYER_KEYS,
    _SCALAR_KEYS, _shape_word, _swa_layer, gguf_hparams, gguf_hparams_bytes,
    header_shape_problem,
)

# ── the KV element table (block quants carry their scale bytes) ──────────────
# From llama.cpp's own type sizes. Ollama's "q8_0 = 1 byte" is an UNDER-count: q8_0 is
# 34 bytes per 32 elements = 1.0625. Getting this wrong under-predicts a long-context
# cache by 6%, silently, in the direction that says "fits".
KV_BYTES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q5_1": 0.75,
            "q5_0": 0.6875, "q4_1": 0.625, "q4_0": 0.5625, "iq4_nl": 0.5625}
KV_DEFAULT = "f16"


def kv_elem_bytes(kind: str) -> float:
    return KV_BYTES.get(str(kind or "").strip().lower(), KV_BYTES[KV_DEFAULT])


def _pad(n: int, to: int = 256) -> int:
    """llama-context.cpp: cparams.n_ctx = GGML_PAD(cparams.n_ctx, 256)."""
    return int(math.ceil(n / to) * to)


def attention_layers(hp: dict) -> "tuple[int, int]":
    """(layers that hold a KV cache, layers that hold recurrent state).

    THE HYBRID-MAMBA CORRECTION, and it is the single most consequential line in this
    file: on Qwen3.5/3.6 only every `full_attention_interval`-th layer holds KV. Naive
    math prices 33 layers where 8 are real — a 4.1× over-estimate that would have made
    the advisor cry wolf on models that fit with room to spare."""
    blocks = int(_num(hp, "block_count"))
    target = max(0, blocks - int(_num(hp, "nextn_predict_layers")))
    fai = int(_num(hp, "full_attention_interval"))
    if fai > 1 and _num(hp, "ssm.inner_size"):
        attn = target // fai
        return attn, max(0, target - attn)
    return target, 0


def recurrent_state_bytes(hp: dict, n_parallel: int = 1) -> int:
    """Mamba2 conv + ssm state, which is CONSTANT in context (that is the point of a
    recurrent layer) and per parallel slot.

    Validated exactly against the runner's own `RS buffer size` line: 50.25 MiB on the
    9B (24 recurrent layers) and 149 MiB on the 27B (48 layers)."""
    inner = int(_num(hp, "ssm.inner_size"))
    state = int(_num(hp, "ssm.state_size"))
    conv = int(_num(hp, "ssm.conv_kernel"))
    groups = int(_num(hp, "ssm.group_count"))
    _, rec_layers = attention_layers(hp)
    if not (inner and state and conv and rec_layers):
        return 0
    per_layer = ((conv - 1) * (inner + 2 * groups * state) + inner * state) * 4
    return int(per_layer * rec_layers * max(1, int(n_parallel)))


def kv_cache_bytes(hp: dict, n_ctx: int, kv_k: str = KV_DEFAULT, kv_v: str = KV_DEFAULT,
                   n_parallel: int = 1, unified: bool = False,
                   flash_attn: bool = True, n_ubatch: int = 512) -> int:
    """The KV cache, by the 5-path dispatch of the research (§6.1 / §7).

    Paths, in the order they are tested: MLA (one compressed latent, no separate V) →
    SWA (window-capped cells on the sliding layers) → hybrid/GQA per-layer (the common
    case here) → legacy embd/heads fallback."""
    blocks = int(_num(hp, "block_count"))
    if not blocks:
        return 0
    attn, _ = attention_layers(hp)
    if attn <= 0:
        return 0
    n_embd = int(_num(hp, "embedding_length"))
    # head_count IS A PER-LAYER SHAPE, exactly like head_count_kv (U23, measured on
    # Laguna-XS-2.1-APEX-I-Compact: 40 entries of {48,64}). llama.cpp reads it with
    # get_key_or_arr into n_head_arr, so a scalar is the common case, not the contract.
    heads_q = _as_list(hp.get("attention.head_count"), blocks)
    heads_kv = _as_list(hp.get("attention.head_count_kv"), blocks)
    bk, bv = kv_elem_bytes(kv_k), kv_elem_bytes(kv_v)
    if not flash_attn:
        # llama-context.cpp throws on a quantised V cache without flash attention; the
        # runtime silently keeps V at f16. Predicting the quantised size there would be
        # an under-estimate presented as a fact — exactly the failure ollama #13337
        # shipped. Price what the engine will ACTUALLY allocate.
        bv = max(bv, KV_BYTES["f16"])
    streams = 1 if unified else max(1, int(n_parallel))
    cells = _pad(int(n_ctx) if unified else int(n_ctx))

    lora = int(_num(hp, "attention.kv_lora_rank"))
    if lora:                                                     # ── MLA
        rope = int(_num(hp, "rope.dimension_count"))
        per_tok = (lora + rope) * bk
        return int(per_tok * cells * streams * attn)

    # The head DIMENSION falls back to embd/heads only when the file omits it — and
    # that division is now per-layer too, because the divisor can be per-layer. A
    # single "first head count wins" would price 40 layers at one layer's shape.
    k_pub = int(_num(hp, "attention.key_length"))
    v_pub = int(_num(hp, "attention.value_length"))
    k_by_layer = ([k_pub] * blocks if k_pub else
                  ([(n_embd // h) if (n_embd and h) else 0 for h in heads_q]
                   if heads_q else None))
    if not k_by_layer or not any(k_by_layer):
        return 0
    v_by_layer = [v_pub] * blocks if v_pub else list(k_by_layer)
    kv_heads = heads_kv if heads_kv is not None else heads_q
    if kv_heads is None:
        return 0

    # ── PER-LAYER, NOT PER-MODEL, AND THAT IS THE WHOLE POINT ────────────────
    # Gemma-4 (measured here) publishes BOTH shapes as arrays: 16 kv-heads on its
    # sliding-window layers and 4 on the one global layer in six, with an explicit
    # per-layer `sliding_window_pattern` of booleans. A single "heads × layers"
    # multiply cannot express that — an earlier draft took the first non-zero head
    # count and priced all 60 layers at 16 heads with full context, which is ~9× the
    # real cache. (It also CRASHED reading the boolean array as a scalar, which the
    # router turned into an honest "No estimate" rather than a wrong number — the
    # right failure direction, but a defect either way. Found in the adversarial pass.)
    arch = str(hp.get("architecture") or "").strip().lower()
    swa = 0 if arch in SWA_DISABLED_ARCH else int(_num(hp, "attention.sliding_window"))
    pat = hp.get("attention.sliding_window_pattern")
    # An explicit per-layer boolean array wins; a scalar key gives the PERIOD; with
    # neither, the architecture's own default period applies (see SWA_PATTERN_DEFAULT).
    # The dense_first convention is the arch's in every case — it is not encoded in the
    # header at all, which is why reading a scalar period without it put every global
    # layer in the wrong place on the dense-first architectures.
    arch_period, dense_first = SWA_PATTERN_DEFAULT.get(arch, (0, False))
    period = arch_period
    if isinstance(pat, (int, float)) and not isinstance(pat, bool):
        period = int(pat)
    swa_cells = _pad(min(cells, swa * streams + n_ubatch)) if swa else cells
    k_swa = int(_num(hp, "attention.key_length_swa"))
    v_swa = int(_num(hp, "attention.value_length_swa"))
    fai = int(_num(hp, "full_attention_interval"))
    hybrid = bool(fai > 1 and _num(hp, "ssm.inner_size"))
    shared = int(_num(hp, "shared_kv_layers"))
    total = 0
    target = blocks - int(_num(hp, "nextn_predict_layers"))
    for i in range(max(0, target - max(0, shared))):
        heads = int(kv_heads[i]) if i < len(kv_heads) else 0
        if heads <= 0:
            continue                      # this layer holds no KV at all
        if hybrid and ((i + 1) % fai) != 0:
            continue                      # recurrent layer: state, not cache
        k_len = k_by_layer[i] if i < len(k_by_layer) else 0
        v_len = v_by_layer[i] if i < len(v_by_layer) else k_len
        if not k_len:
            continue
        if isinstance(pat, list) and i < len(pat):
            is_swa = bool(pat[i])
        else:
            is_swa = bool(swa) and _swa_layer(i, period, dense_first)
        if is_swa:
            lk = k_swa or k_len
            lv = v_swa or v_len
            layer_cells = swa_cells
        else:
            lk, lv, layer_cells = k_len, v_len, cells
        total += heads * (lk * bk + lv * bv) * layer_cells * streams
    return int(total)


def compute_buffer_bytes(hp: dict, n_ctx: int, n_ubatch: int = 512,
                         kv_quantised: bool = False) -> int:
    """Graph scratch. A DELIBERATELY ROUGH term, and labelled as such.

    The flat part (logits + scratch) is exact in shape but the engine reserves a
    worst-case graph we do not model, so it under-reads by ~25% on our own models
    (measured 379 MiB predicted vs 501 MiB reserved on the 9B). The context-linear part
    is the one that matters for a fit decision — it is what turns a comfortable 65k into
    a 262k that no longer fits (measured +836 MiB). The ORACLE carries this term for
    GGUF; this exists for MLX and for instant recalculation."""
    n_vocab = int(_num(hp, "vocab_size")) or 32000
    n_embd = int(_num(hp, "embedding_length")) or 4096
    flat = (n_vocab * n_ubatch * 4 + 4 * n_embd * n_ubatch * 4) * 1.1
    if kv_quantised:
        per_tok = 2.25 * n_embd * (n_ubatch / 512.0)
    else:
        per_tok = n_ubatch * 2 * 1.5
    return int(flat + per_tok * int(n_ctx))


# ── the oracle ───────────────────────────────────────────────────────────────
ORACLE_REL = os.path.join("data", "llamacpp", "build", "bin", "llama-fit-params")
ORACLE_TIMEOUT_S = 45
_ORACLE_CACHE: dict = {}
_ORACLE_LOCK = threading.Lock()
ORACLE_CACHE_MAX = 256


def oracle_path() -> "str | None":
    """The llama-fit-params binary, or None.

    Graceful absence is a requirement, not a nicety: an MLX-only install, a snapshot
    restored without data/llamacpp, or a pin bump that renames the binary must all
    degrade to the formula path with the estimate LABELLED, never to an error."""
    p = ROOT / ORACLE_REL
    try:
        return str(p) if p.is_file() and os.access(str(p), os.X_OK) else None
    except OSError:
        return None


def _oracle_key(path: str, s: dict, binary: str) -> tuple:
    try:
        st = os.stat(path)
        bst = os.stat(binary)
    except OSError:
        return ()
    return (path, st.st_mtime_ns, st.st_size, bst.st_mtime_ns,
            int(s.get("ctx") or 0), str(s.get("kv_quant") or ""),
            int(s.get("parallel") or 1), str(s.get("flash_attn") or "auto"))


def oracle_cached(path: str, settings: dict) -> "dict | None":
    """The oracle's answer IF WE ALREADY HAVE IT, without ever running the binary."""
    binary = oracle_path()
    if not binary or not path:
        return None
    key = _oracle_key(path, settings, binary)
    if not key:
        return None
    with _ORACLE_LOCK:
        hit = _ORACLE_CACHE.get(key)
    return dict(hit) if hit is not None else None


def warm_oracle(items: list) -> None:
    """Fill the oracle cache for (path, settings) pairs on a background thread.

    ⚠️ THIS EXISTS BECAUSE THE FIRST DRAFT MADE THE MODELS PAGE WAIT 4.6 SECONDS.
    Sixteen installed models × one 0.3 s oracle run each, in series, inside the
    request that paints the list. The spec called for this shape and the first
    implementation ignored it: the FORMULA is the instant answer, the oracle upgrades
    it, and the SSE tick carries the upgrade to a page that is already drawn. One
    warm-up at a time, so a page of models cannot fork sixteen processes at once."""
    def _run():
        got = 0
        for path, s in items:
            try:
                if oracle_gguf(path, s):
                    got += 1
            except Exception:                                    # noqa: BLE001
                continue
        if got:
            # Tell the panel its estimates just got better. Fire-and-forget, like every
            # publish site: a dead hub costs a repaint, never a wedged thread.
            try:
                from .events import publish
                publish("memory", reason="oracle")
            except Exception:                                    # noqa: BLE001
                pass
    with _ORACLE_LOCK:
        t = _WARM.get("thread")
        if t is not None and t.is_alive():
            return
        t = threading.Thread(target=_run, name="fit-oracle-warm", daemon=True)
        _WARM["thread"] = t
    t.start()


_WARM: dict = {"thread": None}


def oracle_gguf(path: str, settings: dict) -> "dict | None":
    """llama.cpp's own projection for this model at these settings, in BYTES.

    Returns {'device','host','weights','kv','compute','total','source':'oracle'} or
    None when the binary is missing, the model is unreadable, or it takes too long.
    ~0.3 s cold, cached by model × ctx × kv-quant × build afterwards."""
    binary = oracle_path()
    if not binary or not path:
        return None
    key = _oracle_key(path, settings, binary)
    if key:
        with _ORACLE_LOCK:
            hit = _ORACLE_CACHE.get(key)
        if hit is not None:
            return dict(hit)
    ctx = int(settings.get("ctx") or 0)
    argv = [binary, "-m", path, "--verbose"]
    if ctx:
        argv += ["-c", str(ctx)]
    kvq = str(settings.get("kv_quant") or "").strip().lower()
    if kvq and kvq != "off":
        argv += ["-ctk", kvq, "-ctv", kvq, "-fa", "on"]
    par = int(settings.get("parallel") or 0)
    if par > 1:
        argv += ["--parallel", str(par)]
    try:
        res = subprocess.run(argv, capture_output=True, text=True,
                             timeout=ORACLE_TIMEOUT_S)
    except Exception:                                            # noqa: BLE001
        return None
    out = (res.stderr or "") + "\n" + (res.stdout or "")
    got = parse_oracle(out)
    if got is None:
        return None
    if key:
        with _ORACLE_LOCK:
            if len(_ORACLE_CACHE) > ORACLE_CACHE_MAX:
                _ORACLE_CACHE.clear()
            _ORACLE_CACHE[key] = dict(got)
    return got


def parse_oracle(text: str) -> "dict | None":
    """PURE. Pull the projection out of llama-fit-params --verbose output.

    Two lines carry it, and we want both: the device row of `common_memory_breakdown_print`
    (which ITEMISES weights / context / compute — the arithmetic the consent panel shows)
    and the `projected to use N MiB` summary. The Host row is added because host-side
    tensors (token embeddings, MTP blocks) are real unified memory too — on our 9B that
    is 545 MiB the device row never mentions.

    ⚠️ We deliberately IGNORE the oracle's own "free device memory" figure. Metal's free
    is PER-PROCESS (recommendedMaxWorkingSetSize − this process's allocations), so it
    reads ~53 GB even while another process holds a 20 GB model. Believing it would
    produce a confident "fits" with the machine already full. The 'have' side comes from
    the ledger; only the 'need' side comes from here."""
    import re
    dev = re.search(
        r"\|\s*-\s*[^|]*?\|\s*(\d+)\s*=\s*(\d+)\s*\+\s*\(\s*(\d+)\s*=\s*(\d+)\s*\+\s*"
        r"(\d+)\s*\+\s*(\d+)\s*\)", text)
    host = re.search(r"\|\s*-\s*Host\s*\|\s*(\d+)\s*=\s*(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)",
                     text)
    proj = re.search(r"projected to use\s+(\d+)\s*MiB", text)
    if dev is None and proj is None:
        return None
    if dev is not None:
        total_dev = int(dev.group(3)) * MIB
        weights = int(dev.group(4)) * MIB
        kv = int(dev.group(5)) * MIB
        comp = int(dev.group(6)) * MIB
    else:
        total_dev = int(proj.group(1)) * MIB
        weights = kv = comp = 0
    host_total = int(host.group(1)) * MIB if host else 0
    host_w = int(host.group(2)) * MIB if host else 0
    host_c = int(host.group(4)) * MIB if host else 0
    return {"device_bytes": total_dev, "host_bytes": host_total,
            "weights_bytes": weights + host_w, "kv_bytes": kv,
            "compute_bytes": comp + host_c,
            "total_bytes": total_dev + host_total, "source": "oracle"}


# ── MLX ──────────────────────────────────────────────────────────────────────
def mlx_estimate(path: str, settings: dict) -> "dict | None":
    """Weights + KV + lazy-eval headroom for an MLX model directory.

    There is no oracle on this side — mlx allocates lazily toward a soft memory limit
    and nothing can be asked in advance. Two honest consequences the UI must carry:
    the estimate is a FORMULA (banded), and MLX weights get NO mmap relief — an N-GB
    MLX model is N GB of dirty resident memory for its whole life, where a GGUF's clean
    mapped pages are evictable. Same size, different truth."""
    import json as _json
    d = path
    if not d or not os.path.isdir(d):
        return None
    weights = 0
    try:
        for name in os.listdir(d):
            if name.endswith(".safetensors"):
                weights += os.path.getsize(os.path.join(d, name))
    except OSError:
        return None
    if not weights:
        return None
    cfgp = os.path.join(d, "config.json")
    kv = 0
    try:
        with open(cfgp, "r", encoding="utf-8") as fh:
            conf = _json.load(fh)
        layers = int(conf.get("num_hidden_layers") or 0)
        kvh = int(conf.get("num_key_value_heads") or conf.get("num_attention_heads") or 0)
        hd = int(conf.get("head_dim") or 0) or (
            int(conf.get("hidden_size") or 0) // max(1, int(conf.get("num_attention_heads") or 1)))
        ctx = int(settings.get("ctx") or 8192)
        kvq = str(settings.get("kv_quant") or "").lower()
        elem = 1.0625 if kvq in ("q8_0", "q4_0") else 2.0
        kv = int(layers * kvh * hd * 2 * elem * ctx)
    except (OSError, TypeError, ValueError, _json.JSONDecodeError):
        # TypeError is the U23 class arriving on the MLX side: config.json is written
        # by somebody else too, and `num_key_value_heads` is a per-layer list in more
        # than one published repo. A KV of 0 is honest here — the weights term still
        # carries the number, and mlx_estimate is already labelled a formula.
        kv = 0
    head = int(weights * 0.10)
    return {"weights_bytes": weights, "kv_bytes": kv, "compute_bytes": head,
            "total_bytes": weights + kv + head, "source": "formula",
            "note": "MLX weights stay fully resident — no memory-mapped relief."}


# ── the budget ───────────────────────────────────────────────────────────────
# 0.85 × min(Metal's working-set ceiling, what the ledger says is available now).
# The 0.85 is Unsloth's measured Apple constant (_APPLE_UNIFIED_MEMORY_FRACTION,
# "Apple unified memory is shared with the OS, so tighter than VRAM"); it does two jobs
# at once — the OS's share, and the drift between deciding and finishing a load.
APPLE_FRACTION = 0.85
BAND_FITS = 0.80                # Ollama's admission rule: don't start a load whose
                                # prediction exceeds 80% of what is free.
OVERCOMMIT_ENV = "MOT_DECK_ALLOW_METAL_OVERCOMMIT"


def budget(freeing_bytes: int = 0) -> dict:
    """{'ceiling','available','budget','freeing'} in bytes, with what each one means.

    `freeing_bytes` is what this action itself releases — switching the runner's model
    frees the resident one — so a switch is not asked to fit BESIDE the model it
    replaces. Getting this wrong is how a fit advisor tells you a smaller model does
    not fit."""
    from . import memory as _mem
    sysv = _mem.system_view()
    ceiling = sysv.get("metal_ceiling_bytes") or 0
    avail = sysv.get("available_bytes") or 0
    avail = int(avail) + max(0, int(freeing_bytes or 0))
    base = min(ceiling, avail) if (ceiling and avail) else (ceiling or avail)
    raw = {"ceiling_bytes": ceiling, "available_bytes": avail,
           "freeing_bytes": int(freeing_bytes or 0),
           "budget_bytes": int(base * APPLE_FRACTION),
           "fraction": APPLE_FRACTION,
           "pressure": sysv.get("pressure"),
           "available_pct": sysv.get("available_pct")}
    # S6: only Custom headroom changes the arithmetic, and it does so here—the same
    # budget constructor used by chips, detail, API and load gate.  Quiet/Advise/Early
    # never touch a number; they decide only when to surface the consent explanation.
    from .memoryprefs import apply_headroom
    return apply_headroom(raw)


def band(total: int, budget_bytes: int) -> str:
    """fits / tight / over — advisory, always."""
    if not budget_bytes:
        return "unknown"
    if total <= BAND_FITS * budget_bytes:
        return "fits"
    if total <= budget_bytes:
        return "tight"
    return "over"


# ── settings resolution ──────────────────────────────────────────────────────
DEFAULT_CTX = 65536


MIN_CTX = 256
MAX_CTX = 1024 * 1024            # nothing this engine runs goes past 1M cells


def _clean_ctx(raw, cap: int = 0) -> "int | None":
    """A context we are willing to price, or None.

    ⚠️ EVERY VALUE HERE CAME BACK FROM A HOSTILE PROBE OF THE LIVE ROUTE. `ctx=-5`
    produced a cheerful "Fits · ~5.8 GB" for a context that cannot exist;
    `ctx=999999999` produced a 31 TB requirement and a refusal for a context the model
    caps at 262k anyway; `ctx=abc` was silently ignored (that one was fine). Junk in a
    query string must land on the honest default, not on a verdict — and a request past
    what the model was built for is clamped to the model's own ceiling rather than
    priced as if it were real."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return None
    if v < MIN_CTX:
        return None
    limit = min(MAX_CTX, cap) if cap else MAX_CTX
    return min(v, limit)


def settings_for(entry: dict, override: "dict | None" = None) -> dict:
    """The load settings a fit question is asked AT, and where each one came from.

    `hand_set` is not decoration: it is the input to the ONE refusal in this engine.
    A context the engine chose for you may be clamped; a context you typed is a
    decision, and over-committing Metal with it is the kernel-panic case."""
    e = entry if isinstance(entry, dict) else {}
    load = e.get("load") if isinstance(e.get("load"), dict) else {}
    over = override if isinstance(override, dict) else {}
    cap = 0
    try:
        hp = gguf_hparams(str(e.get("path") or "")) or {}
        cap = int(_num(hp, "context_length"))
    except Exception:                                            # noqa: BLE001
        cap = 0
    asked = _clean_ctx(over.get("ctx"), cap)
    saved = _clean_ctx(load.get("ctx"), cap)
    ctx = asked or saved or _clean_ctx(e.get("ctx"), cap) or DEFAULT_CTX
    # ⚠️ THE SAME CLASS AS U23, ONE FUNCTION LATER, and the adversarial pass caught it:
    # `?ctx=abc` on the live route raised ValueError here. `_clean_ctx` above already
    # answers junk with None — this line then re-read the RAW value with a bare int()
    # and crashed on exactly the input the docstring says is handled. A number that
    # came from a query string or a saved JSON blob is never known to be a number.
    def _asked(v) -> int:
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0
    clamped = bool(cap and (_asked(over.get("ctx")) > cap
                            or _asked(load.get("ctx")) > cap))
    # A cache type we do not have a byte size for is NOT passed through: the oracle
    # rejects it and we would silently fall back to a formula estimate wearing the
    # oracle's confidence. Unknown → the saved value, or off.
    raw_kv = str(over.get("kv_quant") or load.get("kv_quant") or "off").strip().lower()
    kvq = raw_kv if (raw_kv in KV_BYTES or raw_kv == "off") else "off"
    return {"ctx": int(ctx), "kv_quant": kvq,
            "flash_attn": load.get("flash_attn", "auto"),
            "parallel": max(1, _asked(load.get("parallel"))) or 1,
            "ctx_capped_at": cap if clamped else 0,
            "hand_set_ctx": bool(saved or asked),
            "ctx_source": ("you set it" if saved else
                           ("this question" if asked else
                            ("the model" if e.get("ctx") else "the default")))}


# ── the whole verdict ────────────────────────────────────────────────────────
MMPROJ_RUNTIME = 0.4            # encoder buffers on top of the projector file
                                # (Unsloth's measured 1.4× total; ollama flats +1 GiB)


def formula_estimate(hp: dict, file_bytes: int, settings: dict) -> dict:
    """weights + KV (+ recurrent state) + compute buffer, from a HEADER alone.

    Lifted out of estimate() unchanged so that the HF browser can price a quant that
    is not on this disk (S2): its header is read over an HTTP range request and THIS
    function does the arithmetic. One formula, two callers — a browser badge computed
    by a second implementation is LM Studio's documented defect, and the way to not
    have it is to not write the arithmetic twice."""
    kvq = str(settings.get("kv_quant") or "off").lower()
    kind = KV_DEFAULT if kvq in ("", "off") else kvq
    fa = str(settings.get("flash_attn", "auto")).lower() != "off"
    kv = kv_cache_bytes(hp, settings["ctx"], kind, kind,
                        n_parallel=settings.get("parallel", 1),
                        flash_attn=fa)
    rs = recurrent_state_bytes(hp, settings.get("parallel", 1))
    comp = compute_buffer_bytes(hp, settings["ctx"],
                                kv_quantised=(kind != KV_DEFAULT))
    fb = int(file_bytes or 0)
    return {"weights_bytes": fb, "kv_bytes": kv + rs, "compute_bytes": comp,
            "total_bytes": fb + kv + rs + comp, "source": "formula"}


def estimate(entry: dict, settings: dict, cached_oracle: bool = False) -> dict:
    """need, itemised, oracle-first with the formula as cross-check.

    The divergence is COMPUTED, not assumed: when the two disagree by more than 10% the
    fact is recorded on the result (`divergence`) and the oracle's number is the one
    used. That field is the early-warning that a new architecture has outrun our
    formulas — the shape of every estimator bug in ollama's tracker."""
    path = str(entry.get("path") or "")
    fmt = str(entry.get("format") or "").lower()
    if fmt.startswith("mlx") or (not fmt.endswith("gguf") and os.path.isdir(path)):
        got = mlx_estimate(path, settings)
        if got is None:
            return {"known": False, "reason": "no readable MLX weights"}
        got.update(known=True, engine="mlx")
        return got

    hp = gguf_hparams(path)
    # ⚠️ A SHAPE WE CANNOT PRICE IS A SENTENCE, NOT A ZERO. If some field the
    # arithmetic reads arrives in a shape this engine does not know, the answer is an
    # honest "No estimate" that NAMES the field — never a coerced 0 folded into a
    # total, which would look exactly like a real number and always err toward "fits".
    bad = header_shape_problem(hp)
    if bad:
        return {"known": False,
                "reason": f"unsupported header shape: {bad}"}
    file_bytes = 0
    try:
        file_bytes = os.path.getsize(path)
    except OSError:
        file_bytes = int(entry.get("size_bytes") or 0)
    formula = formula_estimate(hp, file_bytes, settings) if hp else None
    got = (oracle_cached(path, settings) if cached_oracle
           else oracle_gguf(path, settings))
    if got is None:
        if formula is None:
            return {"known": False, "reason": "the model header could not be read"}
        out = dict(formula)
        out["oracle"] = False
        out["note"] = ("Estimated from the model's own header — llama.cpp's fitter "
                       "is not installed, so this is arithmetic, not a measurement.")
    else:
        out = dict(got)
        out["oracle"] = True
        if formula:
            a, b = formula["total_bytes"], got["total_bytes"]
            if b and abs(a - b) / b > 0.10:
                out["divergence"] = {"formula_bytes": a, "oracle_bytes": b,
                                     "pct": round(100.0 * (a - b) / b, 1)}
    mm = str(entry.get("mmproj") or "")
    if mm:
        try:
            mmb = os.path.getsize(mm)
        except OSError:
            mmb = 0
        if mmb:
            out["vision_bytes"] = int(mmb * (1 + MMPROJ_RUNTIME))
            out["total_bytes"] = int(out["total_bytes"]) + out["vision_bytes"]
    out["known"] = True
    out["engine"] = "gguf"
    return out


def _band_of_estimate(total: int, budget_bytes: int, source: str) -> "tuple[str, int]":
    return band(total, budget_bytes), (total - budget_bytes)


def live_verdict(footprint: int, peak: int) -> dict:
    """THE MODEL THAT IS ALREADY RUNNING DOES NOT GET A PREDICTION. It gets its
    MEASUREMENT.

    ⚠️ THIS EXISTS BECAUSE THE LIVE 27B READ "Over by ~7.5 GB" IN THE FIRST WALK — a
    model visibly serving requests, well, on the very machine being asked whether it
    fits. Both numbers were honest and they measure different things: the prediction
    (23.2 GB) is everything llama.cpp will map, while the ledger's footprint (12.7 GB)
    excludes the clean memory-mapped weight pages the kernel can drop for free. Neither
    is wrong; putting a red chip on a running model is. A prediction is what you show
    before the fact — afterwards there is a real number, and the real number wins."""
    return {"verdict": "live", "need_bytes": int(footprint), "gap_bytes": 0,
            "remedies": [], "refuse": None, "oracle": False,
            "copy": {"chip": f"Live · ~{_gb(footprint)} GB",
                     "line": (f"Running now, holding ~{_gb(footprint)} GB of memory "
                              f"footprint"
                              + (f" (its highest so far: ~{_gb(peak)} GB)."
                                 if peak and peak > footprint else ".")),
                     "hedge": ("Measured, not estimated — this is the process's own "
                               "footprint, the figure Activity Monitor shows."),
                     "caveat": ("Ejecting it returns roughly this much, and frees the "
                                "GPU-wired weights on top.")}}


def fit(entry: dict, override: "dict | None" = None,
        freeing_bytes: int = 0, holders: "list | None" = None,
        cached_oracle: bool = False, replaces: str = "") -> dict:
    """THE call. One verdict, its arithmetic, and the settings that would change it.

    Shape: {verdict, need_bytes, budget, breakdown, remedies, refuse, copy}. `verdict`
    is advisory in every case but `refuse`, which is set ONLY for a hand-set context
    that over-commits Metal's wired ceiling (see the module docstring)."""
    s = settings_for(entry, override)
    est = estimate(entry, s, cached_oracle=cached_oracle)
    bud = budget(freeing_bytes)
    if not est.get("known"):
        why = str(est.get("reason") or "no estimate")
        # Name the shape when we know it. "We could not read this model's shape" is
        # true but unactionable; "unsupported header shape: attention.head_count is a
        # per-layer array of 40 entries" is a line the user can report and we can fix.
        line = (f"No estimate: this model's header uses a shape we cannot price yet "
                f"({why.split(': ', 1)[1]})." if why.startswith("unsupported header ")
                else "We could not read this model's shape, so there is no honest "
                     "number to show.")
        return {"verdict": "unknown", "settings": s, "budget": bud,
                "reason": why,
                "need_bytes": None, "remedies": [], "refuse": None,
                "copy": {"chip": "No estimate", "line": line}}
    need = int(est["total_bytes"])
    verdict = band(need, bud["budget_bytes"])
    gap = need - bud["budget_bytes"]

    # ── THE ONE HARD STOP ────────────────────────────────────────────────────
    # Not "over budget" — over METAL'S CEILING, with a context the user typed. Beyond
    # the wired ceiling the kernel cannot swap and the documented failure is a panic,
    # so this is the one place a warning would be dishonest.
    refuse = None
    ceiling = bud.get("ceiling_bytes") or 0
    if (ceiling and s.get("hand_set_ctx") and need > ceiling
            and not os.environ.get(OVERCOMMIT_ENV)):
        refuse = {
            "reason": (f"At {_ctx_label(s['ctx'])} context this needs about "
                       f"{_gb(need)} GB, past what this Mac can wire for the GPU "
                       f"({_gb(ceiling)} GB). Past that line macOS cannot page the "
                       f"memory out, and the failure is a kernel panic rather than an "
                       f"error — so this is the one setting we do not let through."),
            "remedy": "Lower the context, or quantise the KV cache to q8_0.",
            "override_env": OVERCOMMIT_ENV,
        }

    bud["replaces"] = replaces or ""
    rem = remedies(entry, s, est, bud, holders or [])
    return {"verdict": verdict, "need_bytes": need, "gap_bytes": gap,
            "settings": s, "budget": bud, "breakdown": est,
            "source": est.get("source"), "oracle": bool(est.get("oracle")),
            "remedies": rem, "refuse": refuse,
            "copy": copy_for(verdict, need, bud, s, est, rem)}


def _gb(b) -> str:
    try:
        return f"{float(b) / GIB:.1f}"
    except (TypeError, ValueError):
        return "?"


def _short(name: str, cap: int = 26) -> str:
    name = str(name or "")
    return name if len(name) <= cap else (name[: cap - 1] + "…")


def _ctx_label(n: int) -> str:
    n = int(n or 0)
    return f"{n // 1024}k" if n >= 1024 else str(n)


def remedies(entry: dict, s: dict, est: dict, bud: dict, holders: list,
             price=None) -> list:
    """The settings that change the answer — COMPUTED, never generic.

    This is the half of the grammar the field leaves out: LM Studio says "not enough
    resources" and points at a settings page; Ollama's error names two numbers and no
    way out. Every remedy here carries its own post-remedy figure, because a suggestion
    you cannot price is a suggestion you cannot act on.

    `price(settings) -> estimate` lets a caller that has no local FILE (the HF browser's
    per-quant verdicts) re-price at another context through the same loop, so the hover
    hint the browser shows is computed by this function and not by a second one."""
    out = []
    if price is None:
        def price(st):
            return estimate(entry, st)
    need = int(est.get("total_bytes") or 0)
    b = int(bud.get("budget_bytes") or 0)
    if not b or need <= BAND_FITS * b:
        return out
    # 1. a smaller context (the cheapest, most reversible knob)
    for ctx in (32768, 16384, 8192, 4096):
        if ctx >= int(s["ctx"]):
            continue
        alt = price({**s, "ctx": ctx})
        if not alt.get("known"):
            break
        tot = int(alt["total_bytes"])
        if tot <= BAND_FITS * b:
            out.append({"kind": "ctx", "value": ctx,
                        "label": f"{_ctx_label(ctx)} context",
                        "need_bytes": tot, "saves_bytes": need - tot,
                        "fits_after": True,
                        "text": (f"At {_ctx_label(ctx)} context it needs about "
                                 f"{_gb(tot)} GB — that fits.")})
            break
    # 2. quantise the KV cache
    if str(s.get("kv_quant") or "off").lower() in ("", "off"):
        alt = price({**s, "kv_quant": "q8_0"})
        if alt.get("known"):
            tot = int(alt["total_bytes"])
            if tot < need:
                out.append({"kind": "kv_quant", "value": "q8_0",
                            "label": "q8_0 KV cache", "need_bytes": tot,
                            "saves_bytes": need - tot,
                            "fits_after": tot <= b,
                            "text": (f"A q8_0 KV cache saves about "
                                     f"{_gb(need - tot)} GB, for a slight quality cost.")})
    # 3. free what somebody else is holding — BY NAME, from the live ledger
    for h in sorted(holders, key=lambda x: -int(x.get("footprint_bytes") or 0))[:2]:
        held = int(h.get("footprint_bytes") or 0)
        if held < 512 * MIB:
            continue
        who = h.get("title") or h.get("label") or h.get("name")
        out.append({"kind": "eject", "value": h.get("name"),
                    "label": f"eject {who}", "saves_bytes": held,
                    "fits_after": (need - held) <= b,
                    "text": f"Ejecting {who} frees about {_gb(held)} GB."})
    # A remedy that CLOSES the gap outranks one that merely narrows it. Offering
    # "save 1.9 GB" first against a 5.4 GB shortfall reads as an answer and is not
    # one — the near-miss suggestion is the shape that teaches users to ignore us.
    out.sort(key=lambda r: (not r.get("fits_after"), -int(r.get("saves_bytes") or 0)))
    return out


def copy_for(verdict: str, need: int, bud: dict, s: dict, est: dict,
             rem: list) -> dict:
    """OUR words. Verdict → reason → remedy, gap on the chip.

    ⚠️ COPY PROVENANCE (spec §3b): every string below is written for this product and
    was checked, line by line, against the LM Studio string table extracted in
    docs/research/2026-08-28-memory-ux-patterns.md §1. Zero verbatim collisions, and
    the differences are deliberate, not cosmetic: we put the MAGNITUDE on the chip
    ("Over by ~7 GB", where theirs reads identically at 0.2 GB and 40 GB over), we
    never shout, we never call a download "not recommended", and the remedy travels in
    the same breath as the verdict. bridge/tests/test_fit_advisor.py pins that."""
    b = int(bud.get("budget_bytes") or 0)
    approx = "" if est.get("oracle") else "about "
    if verdict == "unknown":
        return {"chip": "No estimate",
                "line": "No estimate for this one — its shape did not read."}
    # ⚠️ SAY WHERE THE ROOM COMES FROM. A row can read "Fits · ~21.5 GB" while the
    # strip above it says 19.5 GB usable, and both are true — the load EJECTS the
    # resident model first, so its memory is part of this row's budget and not part of
    # the strip's. Two true numbers that look like a contradiction are read as a bug,
    # and a user who concludes the advisor cannot add up stops reading it. So the
    # denominator names its own source whenever a replacement is what pays for it.
    # Model ids in this registry run to 60 characters; a sentence that carries one
    # whole stops being readable. Trim for PROSE only — every id the user can act on
    # is still spelled in full on the row it belongs to.
    swap = _short(bud.get("replaces") or "")
    usable = (f"~{_gb(b)} GB usable once {swap} is ejected" if swap
              else f"~{_gb(b)} GB usable")
    if verdict == "over":
        gap = need - b
        chip = f"Over by ~{_gb(gap)} GB"
        line = (f"Needs ~{_gb(need)} GB at {_ctx_label(s['ctx'])} context; "
                f"{usable}.")
    elif verdict == "tight":
        chip = f"Tight · ~{_gb(need)} GB"
        line = (f"Needs ~{_gb(need)} GB, and there is {usable} — it loads, with "
                f"little room left for anything else.")
    else:
        chip = f"Fits · ~{_gb(need)} GB"
        line = (f"Needs ~{_gb(need)} GB at {_ctx_label(s['ctx'])} context; "
                f"{usable}.")
    parts = []
    if est.get("weights_bytes"):
        parts.append(f"weights {_gb(est['weights_bytes'])}")
    if est.get("kv_bytes"):
        parts.append(f"context {_gb(est['kv_bytes'])}")
    if est.get("vision_bytes"):
        parts.append(f"vision {_gb(est['vision_bytes'])}")
    if est.get("compute_bytes"):
        parts.append(f"working {_gb(est['compute_bytes'])}")
    math_line = (" + ".join(parts) + f" = ~{_gb(need)} of ~{_gb(b)} GB usable"
                 + (f" (after ejecting {swap})" if swap else "")) if parts else ""
    hedge = ("Measured with llama.cpp's own fitter." if est.get("oracle")
             else "Estimated from the model's header — treat it as a band, not a figure.")
    return {"chip": chip, "line": line, "math": math_line, "hedge": hedge,
            "approx": approx,
            "remedy": (rem[0]["text"] if rem else ""),
            "caveat": ("What else is running moves this number; the verdict is a "
                       "recommendation, never a lock.")}


# ══ S2: PRICING A FILE THAT IS NOT ON THIS DISK ══════════════════════════════
# The HF browser's chips. Everything above prices a model the user HAS; this prices
# one they are looking at. Two facts are kept apart on purpose, because conflating
# them is the field's most common download-time lie:
#
#   DOWNLOAD ≠ RUN. A file that will not fit in memory downloads perfectly well, and
#   nothing here may disable a Get. LM Studio prints "Downloading this file is NOT
#   recommended" on a red badge; disk is cheap, the verdict belongs to the load, and
#   a user who wants the file for later is not making a mistake.
#
# There is no oracle on this path (llama-fit-params needs the file), so every verdict
# here is FORMULA, hedged as such by copy_for's own non-oracle wording.
# MEASURED, not guessed: 8 MB took 34 s against the hub on this connection and 2 MB
# takes ~8 s, and 2 MB already carries every architecture key (the tokenizer arrays that
# make up the rest are skipped anyway — see _gguf_hparams_parse's partial_ok).
REMOTE_META_BYTES = 2 * MIB          # first pass: the architecture keys
REMOTE_META_BYTES_WIDE = 24 * MIB    # second pass, only when the first yields nothing


def remote_fit(hp: "dict | None", file_bytes: int, bud: dict,
               ctx: int = 0, replaces: str = "") -> dict:
    """One verdict for a remote GGUF, from its header prefix and its size.

    The context is the one this model WOULD load at here — our default, clamped by the
    model's own trained ceiling — so the chip in the browser and the chip on the row
    after downloading are the same sentence about the same configuration. A browser
    that prices at a context the loader will not use is a browser that changes its mind
    after you commit, which is the drift this engine exists to prevent."""
    b = dict(bud or {})
    b["replaces"] = replaces or ""
    fb = int(file_bytes or 0)
    if not hp or not fb:
        return {"verdict": "unknown", "need_bytes": None, "gap_bytes": None,
                "oracle": False, "estimate": True, "remedies": [],
                "copy": {"chip": "No estimate",
                         "line": "We could not read this file's header from the hub, so "
                                 "there is no honest number to show — the download is "
                                 "unaffected."}}
    bad = header_shape_problem(hp)
    if bad:
        return {"verdict": "unknown", "need_bytes": None, "gap_bytes": None,
                "oracle": False, "estimate": True, "remedies": [],
                "reason": f"unsupported header shape: {bad}",
                "copy": {"chip": "No estimate",
                         "line": (f"No estimate: this file's header uses a shape we "
                                  f"cannot price yet ({bad}). The download is "
                                  f"unaffected.")}}
    cap = int(_num(hp, "context_length"))
    want = int(ctx or DEFAULT_CTX)
    use = min(want, cap) if cap else want
    s = {"ctx": int(use), "kv_quant": "off", "flash_attn": "auto", "parallel": 1,
         "ctx_capped_at": (cap if (cap and want > cap) else 0),
         "hand_set_ctx": False, "ctx_source": "the default"}
    est = dict(formula_estimate(hp, fb, s), oracle=False, known=True)
    need = int(est["total_bytes"])
    verdict = band(need, int(b.get("budget_bytes") or 0))

    def _price(st):
        return dict(formula_estimate(hp, fb, st), known=True)

    rem = remedies({}, s, est, b, [], price=_price)
    copy = copy_for(verdict, need, b, s, est, rem)
    # The chip says ESTIMATE in its own words, once, where the number is — not only in
    # fine print. There is no local file, so nothing on this path was measured.
    copy["provenance"] = "estimate"
    copy["hedge"] = ("Estimated from this file's own header — no local copy exists yet, "
                     "so nothing here was measured.")
    copy["at_ctx"] = _ctx_label(int(use))
    return {"verdict": verdict, "need_bytes": need,
            "gap_bytes": need - int(b.get("budget_bytes") or 0),
            "settings": s, "budget": b, "breakdown": est, "source": "formula",
            "oracle": False, "estimate": True, "remedies": rem, "refuse": None,
            "copy": copy}


def remote_mlx_fit(conf: "dict | None", total_bytes: int, bud: dict,
                   ctx: int = 0, replaces: str = "") -> dict:
    """The same, for an MLX repo: config.json is a small JSON the hub serves whole,
    so this path needs no range read at all. MLX weights stay fully resident (no
    memory-mapped relief), which mlx_estimate already says and this repeats."""
    b = dict(bud or {})
    b["replaces"] = replaces or ""
    tb = int(total_bytes or 0)
    if not tb:
        return {"verdict": "unknown", "need_bytes": None, "oracle": False,
                "estimate": True, "remedies": [],
                "copy": {"chip": "No estimate",
                         "line": "The hub did not list this repo's weight sizes, so "
                                 "there is no honest number to show."}}
    c = conf if isinstance(conf, dict) else {}
    use = int(ctx or DEFAULT_CTX)
    cap = 0
    for k in ("max_position_embeddings", "max_seq_len"):
        try:
            cap = int(c.get(k) or 0) or cap
        except (TypeError, ValueError):
            pass
    if cap:
        use = min(use, cap)
    kv = 0
    try:
        layers = int(c.get("num_hidden_layers") or 0)
        kvh = int(c.get("num_key_value_heads") or c.get("num_attention_heads") or 0)
        hd = int(c.get("head_dim") or 0) or (
            int(c.get("hidden_size") or 0) // max(1, int(c.get("num_attention_heads") or 1)))
        kv = int(layers * kvh * hd * 2 * 2.0 * use)
    except (TypeError, ValueError, ZeroDivisionError):
        kv = 0
    head = int(tb * 0.10)
    est = {"weights_bytes": tb, "kv_bytes": kv, "compute_bytes": head,
           "total_bytes": tb + kv + head, "source": "formula", "oracle": False,
           "known": True}
    need = int(est["total_bytes"])
    verdict = band(need, int(b.get("budget_bytes") or 0))
    s = {"ctx": int(use), "kv_quant": "off"}
    copy = copy_for(verdict, need, b, s, est, [])
    copy["provenance"] = "estimate"
    copy["hedge"] = ("Estimated from this repo's config and file sizes — MLX weights "
                     "stay fully resident, so none of this is memory-mapped relief.")
    copy["at_ctx"] = _ctx_label(int(use))
    return {"verdict": verdict, "need_bytes": need,
            "gap_bytes": need - int(b.get("budget_bytes") or 0),
            "settings": s, "budget": b, "breakdown": est, "source": "formula",
            "oracle": False, "estimate": True, "remedies": [], "refuse": None,
            "copy": copy}


# ══ AUDIO WORKERS ════════════════════════════════════════════════════════════
# The Audio tab shipped with NO verdicts at all, which is its own small lie: every
# chat row carries a number and the voice rows carried none, so the tab read as
# "these cost nothing". They do — a resident TTS worker held 2.6 GB on this machine.
#
# ⚠️ AN AUDIO WORKER SITS *BESIDE* THE RUNNER. It does not replace the chat model, so
# NOTHING is freed by loading one and its budget is the plain `budget()` — never
# `budget_after_eject`. Getting this backwards is how an advisor tells you that a
# second model fits when what it priced was the first one leaving.
#
# PROVENANCE IS THE POINT HERE. There is no oracle and no header arithmetic for these
# engines, so a verdict is one of exactly three things and the copy always says which:
#   measured-now   — the resident worker's OWN footprint, read from the ledger
#   measured-here  — the highest this model's worker has ever reached on this Mac,
#                    recorded below the first time it ran (data/audio_peaks.json)
#   estimate       — weights on disk × a stated runtime factor, for one never run here
# ⚠️ THE FIRST NUMBER HERE WAS 1.25 AND IT WAS A LIE, CAUGHT BY DRIVING IT. That figure
# came from the S2S research's published envelopes (9.18 GB of weights → an 11 GB
# envelope; 21.84 → 24), i.e. from models that report their own weights honestly. The
# first live render on this machine — OmniVoice-bfloat16, 2.04 GB on disk — put the
# worker at a MEASURED 4.81 GB footprint: a 2.36× overhead, because an mlx-audio worker
# carries a Python interpreter, MLX's own allocator and a vocoder that no weight file
# lists. The chip had said "Fits · ~2.4 GB" for a thing that costs 4.8, which is the
# direction that lies, on a tab whose whole job is to stop that.
#
# So the factor is now DERIVED FROM THIS MACHINE where it can be, and only falls back
# to a constant when nothing has ever run here — and the fallback is the measured 2.4,
# not the published 1.25. An estimate is allowed to be wide; it is not allowed to be
# cheerful.
AUDIO_RUNTIME_FACTOR = 2.4     # fallback only; see _audio_factor()
AUDIO_FACTOR_MIN = 1.2
AUDIO_FACTOR_MAX = 4.0
AUDIO_RUNTIME_FLOOR = 384 * MIB
AUDIO_PEAKS_PATH = ROOT / "data" / "audio_peaks.json"
_AUDIO_PEAKS: "dict | None" = None


def _audio_peaks() -> dict:
    global _AUDIO_PEAKS
    if _AUDIO_PEAKS is None:
        import json as _json
        try:
            with open(AUDIO_PEAKS_PATH, "r", encoding="utf-8") as fh:
                got = _json.load(fh)
            _AUDIO_PEAKS = got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            _AUDIO_PEAKS = {}
    return _AUDIO_PEAKS


def _audio_factor() -> tuple:
    """(factor, source) — the runtime overhead an audio worker adds over its weights.

    Measured on THIS machine wherever a worker has actually run (peak ÷ weights, the
    median across models so one odd checkpoint cannot set the rule), clamped to a sane
    band, and only otherwise the constant. This is the contextual-inference rule the
    doctrine asks for in its smallest useful form: the number improves every time the
    machine is used, instead of being a table somebody has to remember to update."""
    ratios = []
    for rec in _audio_peaks().values():
        try:
            w = int(rec.get("weights_bytes") or 0)
            p = int(rec.get("peak_bytes") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if w > 0 and p > 0:
            ratios.append(p / w)
    if not ratios:
        return AUDIO_RUNTIME_FACTOR, "published envelopes for this class of worker"
    ratios.sort()
    med = ratios[len(ratios) // 2]
    med = max(AUDIO_FACTOR_MIN, min(AUDIO_FACTOR_MAX, med))
    return med, (f"the {len(ratios)} voice worker"
                 f"{'s' if len(ratios) != 1 else ''} measured on this Mac")


def record_audio_peak(model_id: str, peak_bytes: int, weights_bytes: int = 0) -> bool:
    """Remember the highest footprint a voice worker reached for this model.

    Monotonic per model, written only when it GROWS, so the file is stable and a
    render that happened to be short cannot talk the number back down. This is what
    upgrades a row from 'estimate' to 'measured here' — the advisor gets more honest
    the more the machine is used, which is the opposite of a hardcoded requirement
    table (GPT4All's 'RAM required: 8 GB' is quant-, context- and machine-blind)."""
    mid = str(model_id or "").strip()
    val = int(peak_bytes or 0)
    if not mid or val <= 0:
        return False
    peaks = _audio_peaks()
    old = peaks.get(mid) or {}
    prev = int(old.get("peak_bytes") or 0)
    w = int(weights_bytes or 0) or int(old.get("weights_bytes") or 0)
    if val <= prev and w == int(old.get("weights_bytes") or 0):
        return False
    peaks[mid] = {"peak_bytes": max(val, prev), "weights_bytes": w,
                  "at": int(time.time())}
    import json as _json
    try:
        AUDIO_PEAKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(AUDIO_PEAKS_PATH) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            _json.dump(peaks, fh, indent=1, sort_keys=True)
        os.replace(tmp, str(AUDIO_PEAKS_PATH))
    except OSError:
        return False
    return True


def audio_fit(entry: dict, bud: dict, resident_bytes: int = 0,
              resident_peak: int = 0) -> dict:
    """A voice model's verdict, with its provenance in its own sentence."""
    e = entry if isinstance(entry, dict) else {}
    mid = str(e.get("id") or "")
    weights = int(e.get("size_bytes") or 0)
    b = int((bud or {}).get("budget_bytes") or 0)
    role = str(e.get("role") or "tts")
    if resident_bytes:
        chip = f"Live · ~{_gb(resident_bytes)} GB"
        line = (f"Loaded now — the {role.upper()} worker's own footprint is "
                f"~{_gb(resident_bytes)} GB"
                + (f", and its highest so far is ~{_gb(resident_peak)} GB."
                   if resident_peak and resident_peak > resident_bytes else "."))
        return {"verdict": "live", "need_bytes": int(resident_bytes),
                "gap_bytes": 0, "provenance": "measured-now", "remedies": [],
                "copy": {"chip": chip, "line": line,
                         "math": (f"weights on disk ~{_gb(weights)} GB → resident "
                                  f"~{_gb(resident_bytes)} GB" if weights else ""),
                         "hedge": ("Measured, not estimated — the worker process's own "
                                   "footprint, the figure Activity Monitor shows."),
                         "caveat": ("Unload returns roughly this much; nothing here "
                                    "competes with the chat model's slot.")}}
    rec = int((_audio_peaks().get(mid) or {}).get("peak_bytes") or 0)
    if rec:
        need, prov = rec, "measured-here"
        hedge = ("Measured on this Mac the last time it ran, not predicted — the "
                 "highest its worker reached.")
    elif weights:
        fac, src = _audio_factor()
        need = max(int(weights * fac), weights + AUDIO_RUNTIME_FLOOR)
        prov = "estimate"
        hedge = (f"Estimated: ~{_gb(weights)} GB of weights on disk × {fac:.1f} for the "
                 f"interpreter, the allocator and the vocoder a weight file does not "
                 f"list — the overhead from {src}. Running it here once replaces this "
                 f"with its own measurement.")
    else:
        return {"verdict": "unknown", "need_bytes": None, "gap_bytes": None,
                "provenance": "none", "remedies": [],
                "copy": {"chip": "No estimate",
                         "line": "We do not know this model's size on disk, so there is "
                                 "no honest number to show."}}
    verdict = band(need, b) if b else "unknown"
    if verdict == "over":
        chip = f"Over by ~{_gb(need - b)} GB"
        line = (f"Needs ~{_gb(need)} GB and there is ~{_gb(b)} GB usable beside what is "
                f"already loaded.")
    elif verdict == "tight":
        chip = f"Tight · ~{_gb(need)} GB"
        line = (f"Needs ~{_gb(need)} GB of the ~{_gb(b)} GB usable beside what is "
                f"already loaded — it runs, with little room left.")
    elif verdict == "fits":
        chip = f"Fits · ~{_gb(need)} GB"
        line = (f"Needs ~{_gb(need)} GB and there is ~{_gb(b)} GB usable beside what is "
                f"already loaded.")
    else:
        chip, line = "No estimate", "We could not read this machine's free memory."
    return {"verdict": verdict, "need_bytes": int(need),
            "gap_bytes": int(need - b) if b else None, "provenance": prov,
            "remedies": [],
            "copy": {"chip": chip, "line": line, "hedge": hedge,
                     "caveat": ("A voice worker runs BESIDE the chat model — loading "
                                "one frees nothing, so this is priced against what is "
                                "free right now.")}}
