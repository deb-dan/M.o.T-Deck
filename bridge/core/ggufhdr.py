"""CORE — THE GGUF HEADER READER, and the shapes it is allowed to hand on.

Split out of bridge/core/fit.py (U23) when the fit engine crossed the app layer's
1500-line fence. It is one concern and it always was: turn the first megabytes of a
.gguf into the handful of architecture numbers the fit arithmetic needs, bounded and
forward-only, and say honestly when a value arrives in a shape we cannot price.

fit.py re-exports every public name here, so `bridge.core.fit.gguf_hparams` and
`_fit.gguf_hparams_bytes` (routers/hf.py) still resolve exactly as before.
"""
from __future__ import annotations

import os
import struct

# ── GGUF header reading ──────────────────────────────────────────────────────
# Same bounded, forward-only, seek-don't-read discipline as bridge/modeltools.py's
# chat-template cursor (which this reuses): the tokenizer arrays are megabytes and are
# SKIPPED, never materialised. What is new here is that we keep VALUES, not just one
# string — and that we record the LENGTH of `tokenizer.ggml.tokens` as we skip it,
# because n_vocab is an input to the compute-buffer estimate and most GGUFs do not
# publish it as a scalar.
_FIXED_FMT = {0: ("B", 1), 1: ("b", 1), 2: ("H", 2), 3: ("h", 2), 4: ("I", 4),
              5: ("i", 4), 6: ("f", 4), 7: ("?", 1), 10: ("Q", 8), 11: ("q", 8),
              12: ("d", 8)}
_T_STRING = 8
_T_ARRAY = 9
MAX_META_BYTES = 96 * 1024 * 1024
MAX_KV_COUNT = 100_000
MAX_STRING_BYTES = 8 * 1024 * 1024
MAX_KEPT_ARRAY = 4096          # per-layer kv-head arrays are ~100 entries; a tokenizer
                               # array is millions. Keep the small ones, skip the rest.

# Header keys we care about, WITHOUT the architecture prefix. Everything else is
# skipped. (Sourced from the fit-math research §8 "Inputs we already can read".)
_WANTED = (
    "block_count", "context_length", "embedding_length", "feed_forward_length",
    "vocab_size", "expert_count", "nextn_predict_layers", "shared_kv_layers",
    "full_attention_interval", "attention.head_count", "attention.head_count_kv",
    "attention.key_length", "attention.value_length",
    # ⚠️ THE SWA HEAD DIMENSIONS ARE THEIR OWN KEYS AND THEY ARE NOT THE GLOBAL ONES.
    # Gemma-4 here: key_length 512 on the global layers, key_length_swa 256 on the
    # sliding ones. Reusing the global figure for both prices the window layers at
    # exactly 2× and put our estimate 65% over the oracle at 8k context — measured,
    # not theorised. (Research §8 lists the key as `key_length[,_swa]`; the first
    # draft read the bracket as optional rather than as a second key.)
    "attention.key_length_swa", "attention.value_length_swa",
    "attention.sliding_window",
    "attention.sliding_window_pattern", "attention.kv_lora_rank",
    "rope.dimension_count", "rope.scaling.factor",
    "ssm.conv_kernel", "ssm.state_size", "ssm.group_count", "ssm.inner_size",
    "ssm.time_step_rank",
)


class _Cur:
    """Forward-only reader with a hard byte budget. ValueError on anything malformed,
    which the caller turns into "unknown" — never a crash, never an unbounded read."""

    def __init__(self, fh, budget=MAX_META_BYTES):
        self.fh, self.left = fh, int(budget)
        self.cur_key = ""
        self.last_array_len, self.last_array_key = 0, ""

    def take(self, n):
        n = int(n)
        if n < 0 or n > self.left:
            raise ValueError("read past the metadata budget")
        b = self.fh.read(n)
        if len(b) != n:
            raise ValueError("truncated file")
        self.left -= n
        return b

    def skip(self, n):
        n = int(n)
        if n < 0 or n > self.left:
            raise ValueError("skip past the metadata budget")
        self.fh.seek(n, os.SEEK_CUR)
        self.left -= n

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def string(self):
        n = self.u64()
        if n > MAX_STRING_BYTES:
            raise ValueError("implausible string length")
        return self.take(n).decode("utf-8", errors="replace")

    def value(self, vtype, keep: bool):
        """Read one value. `keep` False = skip it (but still report array lengths)."""
        if vtype in _FIXED_FMT:
            fmt, size = _FIXED_FMT[vtype]
            if not keep:
                self.skip(size)
                return None
            return struct.unpack("<" + fmt, self.take(size))[0]
        if vtype == _T_STRING:
            n = self.u64()
            if n > MAX_STRING_BYTES:
                raise ValueError("implausible string length")
            if not keep:
                self.skip(n)
                return None
            return self.take(n).decode("utf-8", errors="replace")
        if vtype == _T_ARRAY:
            et = self.u32()
            n = self.u64()
            # ⚠️ RECORDED BEFORE THE PAYLOAD IS WALKED, and that is the whole point on
            # the S2 range-read path: `tokenizer.ggml.tokens` is where a 2 MB prefix
            # runs out, and its COUNT — which is n_vocab, an input to the compute-buffer
            # term — is already known here. Losing it made every remote estimate ~0.27
            # GB light (a 32k default standing in for a 152k vocab), in the direction
            # that says "fits".
            self.last_array_len, self.last_array_key = n, getattr(self, "cur_key", "")
            if et == _T_ARRAY:
                raise ValueError("nested gguf array")
            if et in _FIXED_FMT:
                fmt, size = _FIXED_FMT[et]
                if keep and n <= MAX_KEPT_ARRAY:
                    raw = self.take(size * n)
                    return list(struct.unpack("<" + fmt * n, raw))
                self.skip(size * n)
                return {"_len": n}
            if et == _T_STRING:
                for _ in range(n):
                    ln = self.u64()
                    if ln > MAX_STRING_BYTES:
                        raise ValueError("implausible string length")
                    self.skip(ln)
                return {"_len": n}
            raise ValueError("unknown gguf array element type")
        raise ValueError("unknown gguf value type")


_HP_CACHE: dict = {}
_HP_CACHE_MAX = 128


def gguf_hparams(path: str) -> "dict | None":
    """Architecture hyper-parameters for one .gguf, or None when unreadable.

    None is a first-class answer and the caller MUST treat it as "no estimate" rather
    than as a small model: the honest chip is 'No estimate', never a silent green.

    Cached by (path, mtime, size): a remedy panel re-prices the same model at four
    context sizes while the user drags a slider, and re-walking a 17 GB file's header
    for each one turns an instant recalculation into a stutter."""
    try:
        st = os.stat(path)
        ck = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    hit = _HP_CACHE.get(ck)
    if hit is not None:
        return dict(hit) if hit else None
    got = _gguf_hparams_read(path)
    if len(_HP_CACHE) > _HP_CACHE_MAX:
        _HP_CACHE.clear()
    _HP_CACHE[ck] = dict(got) if got else {}
    return got


def gguf_hparams_bytes(blob: bytes) -> "dict | None":
    """The same header read, over a byte PREFIX instead of a file (S2).

    The HF browser prices quants that are not on this disk: the first megabytes of a
    remote .gguf are fetched with one HTTP range request and parsed here. Same parser,
    same keys, same None-means-no-estimate contract — a browser badge computed by a
    second implementation is exactly the drift this engine exists to prevent.

    A prefix that stops inside the metadata raises inside _Cur and comes back None, so
    the caller can widen the range and try once more rather than guess."""
    import io
    if not blob:
        return None
    return _gguf_hparams_parse(io.BytesIO(blob), partial_ok=True)


def _gguf_hparams_read(path: str) -> "dict | None":
    try:
        with open(path, "rb") as fh:
            return _gguf_hparams_parse(fh)
    except OSError:
        return None


# What the KV/compute arithmetic actually needs before a PARTIAL header may be used.
# Without this guard a prefix that stopped early would return {architecture, block_count}
# and the formula would price a model with no attention shape at all — a small, precise,
# entirely fictional number, which is the failure mode this whole engine is against.
_MIN_HP = ("block_count",)


def _hp_priceable(hp: "dict | None") -> bool:
    """⚠️ A HEADER THAT PARSED IS NOT A HEADER WE CAN PRICE. Caught by the new gate on
    a hand-built body: `GGUF` + version 3 + a zero tensor/kv count parses PERFECTLY —
    zero keys, no exception — and formula_estimate then prices it as weights with a
    zero KV cache and a zero compute buffer, i.e. a cheerful "Fits" for a model whose
    shape we never read. The honest answer to a shapeless header is No estimate.

    ⚠️ AND IT IS NOT "MUST HAVE ATTENTION HEADS". A pure state-space model legitimately
    has none, and its cache IS the recurrent state — refusing it would turn a correct
    verdict into a blank chip. Either shape counts."""
    if not hp or not hp.get("block_count"):
        return False
    has_attn = bool((hp.get("attention.head_count_kv") or hp.get("attention.head_count"))
                    and (hp.get("attention.key_length") or hp.get("embedding_length")))
    has_ssm = bool(hp.get("ssm.state_size") or hp.get("ssm.inner_size"))
    return has_attn or has_ssm


def _hp_usable(hp: dict) -> bool:
    """⚠️ THE ORDERING INVARIANT IS THE LOAD-BEARING CHECK HERE, not the key list.

    llama.cpp writes general.* → <arch>.* → tokenizer.*, so a parse that reached
    `tokenizer.ggml.tokens` has ALREADY read every architecture key this file has. A
    parse that stopped earlier may be missing exactly the key that matters most — this
    engine's own headline correction is `full_attention_interval`, whose absence prices
    33 hybrid-Mamba layers where 8 hold KV (4.1× out). Missing it does not read as
    missing: it reads as a confident, precise, wrong verdict. So a partial header is
    accepted ONLY past the tokens array, and anything earlier falls to the wider read.
    Measured: this rule rejects Qwen3.5-9B's 2 MB and 8 MB prefixes (its header needs
    ~24 MB) and accepts Qwen3-4B's 2 MB one, which is exactly the split we want."""
    return bool(hp and hp.get("_past_tokens") and _hp_priceable(hp))


def _gguf_hparams_parse(fh, partial_ok: bool = False) -> "dict | None":
    """`partial_ok` exists for the S2 range read and ONLY for it.

    A remote GGUF's architecture keys are written before its tokenizer arrays, and the
    tokenizer arrays are most of the header's bytes — so a 2 MB prefix reliably carries
    everything the arithmetic needs and then runs out of file inside a token list we
    were skipping anyway. Reading 8 MB per repo to avoid that cost 34 seconds on this
    connection, measured; keeping the keys we already have costs 8. The guard on the way
    out (_hp_usable) is what makes it safe: partial is allowed to mean 'less', never
    'guess'. n_vocab survives too — an array's element count is read from its header,
    before the payload we could not reach."""
    raw, arch, n_vocab = {}, None, None
    try:
        c = _Cur(fh)
        if c.take(4) != b"GGUF":
            return None
        version = c.u32()
        if version == 1:
            c.u32()
            kv = c.u32()
        elif version in (2, 3):
            c.u64()
            kv = c.u64()
        else:
            return None
        if kv > MAX_KV_COUNT:
            return None
        for _ in range(kv):
            key = c.string()
            c.cur_key = key
            vtype = c.u32()
            if key == "general.architecture":
                arch = c.value(vtype, True)
                continue
            if key == "tokenizer.ggml.tokens":
                got = c.value(vtype, False)
                if isinstance(got, dict):
                    n_vocab = int(got.get("_len") or 0)
                continue
            short = key.split(".", 1)[1] if "." in key else key
            keep = short in _WANTED and not key.startswith("general.")
            val = c.value(vtype, keep)
            if keep and val is not None:
                raw[short] = val
    except (ValueError, OSError, struct.error):
        if not partial_ok:
            return None
        past = (c.last_array_key == "tokenizer.ggml.tokens")
        if n_vocab is None and past:
            n_vocab = int(c.last_array_len or 0)
        hp = dict(raw)
        hp["architecture"] = arch or ""
        if n_vocab and not hp.get("vocab_size"):
            hp["vocab_size"] = n_vocab
        hp["partial_header"] = True
        hp["_past_tokens"] = past
        if not _hp_usable(hp):
            return None
        hp.pop("_past_tokens", None)
        return hp
    hp = dict(raw)
    hp["architecture"] = arch or ""
    if n_vocab and not hp.get("vocab_size"):
        hp["vocab_size"] = n_vocab
    return hp if _hp_priceable(hp) else None



def _as_list(v, n: int):
    """A GGUF value that may be a scalar OR a per-layer array (hybrid archs use 0 for
    layers that hold no KV). Edge case #2 of the research table: reading a per-layer
    array as a scalar is a 3.9× error on Kimi-class models.

    ⚠️ NEVER RAISES. Every element is coerced defensively and an unusable shape comes
    back as None, because this helper sits between a FILE WE DID NOT WRITE and the
    arithmetic: a header value's Python type is the producer's choice, not ours."""
    if isinstance(v, bool):
        return [int(v)] * n
    if isinstance(v, (int, float)):
        return [int(v)] * n
    if isinstance(v, list):
        out = []
        for x in v:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                out.append(0)
        if len(out) < n:
            out += [out[-1] if out else 0] * (n - len(out))
        return out[:n]
    return None


def _num(hp: dict, key: str, default: float = 0) -> float:
    """One header field as a NUMBER, or `default` for any other shape — never a raise.

    ⚠️ EXISTS BECAUSE `int(hp.get("attention.head_count") or 0)` CRASHED ON A REAL
    INSTALLED MODEL (U23): Laguna-XS-2.1-APEX publishes that key as a 40-entry
    per-layer array, which llama.cpp reads with `get_key_or_arr` — so the array is the
    LEGAL shape and the bare int() was the bug. The class is wider than the one key:
    every value here was written by a file we did not produce, so a scalar read that
    assumes a scalar is a crash waiting for the next architecture. This is the guard
    half; `header_shape_problem()` is the honest-refusal half of the same rule."""
    v = hp.get(key) if isinstance(hp, dict) else None
    if v is None or isinstance(v, bool):
        return default
    return v if isinstance(v, (int, float)) else default


# ── WHICH HEADER FIELDS MAY LEGALLY BE PER-LAYER ARRAYS ──────────────────────
# Transcribed from llama.cpp's loader (b10662): `get_key_or_arr` accepts either shape
# and these are the keys it is used on that we read. Everything else the arithmetic
# touches is `get_key`, i.e. scalar-only — and a scalar key arriving as an array is a
# shape we have never seen and must NOT guess at.
_PER_LAYER_KEYS = ("attention.head_count", "attention.head_count_kv",
                   "feed_forward_length", "attention.sliding_window_pattern")
_SCALAR_KEYS = (
    "block_count", "context_length", "embedding_length", "vocab_size",
    "expert_count", "nextn_predict_layers", "shared_kv_layers",
    "full_attention_interval", "attention.key_length", "attention.value_length",
    "attention.key_length_swa", "attention.value_length_swa",
    "attention.sliding_window", "attention.kv_lora_rank", "rope.dimension_count",
    "rope.scaling.factor", "ssm.conv_kernel", "ssm.state_size", "ssm.group_count",
    "ssm.inner_size", "ssm.time_step_rank",
)


def _shape_word(v) -> str:
    if isinstance(v, dict):
        return f"an array of {int(v.get('_len') or 0)} entries, too long to keep"
    if isinstance(v, list):
        return f"a per-layer array of {len(v)} entries"
    if isinstance(v, str):
        return "text"
    return f"a {type(v).__name__}"


def header_shape_problem(hp: "dict | None") -> str:
    """"" if every field the arithmetic reads has a shape we can price, else a plain
    sentence naming the offending key AND its shape.

    ⚠️ THE HONEST HALF OF THE U23 FIX. A value we cannot price must produce "No
    estimate (unsupported header shape: …)" — a sentence a user can report and we can
    act on — and never a zero quietly coerced into a total. The silently-zeroed field
    is the lie class: it always errs toward "fits" and looks exactly like a real
    number. Doctrine 6b: the class is "a header field whose Python type the arithmetic
    assumed", not "head_count is sometimes a list"."""
    if not isinstance(hp, dict):
        return ""
    for key in _PER_LAYER_KEYS:
        v = hp.get(key)
        if v is None or isinstance(v, (int, float, bool)):
            continue
        if isinstance(v, list) and all(isinstance(x, (int, float, bool)) for x in v):
            continue
        return f"{key} is {_shape_word(v)}"
    for key in _SCALAR_KEYS:
        v = hp.get(key)
        if v is None or isinstance(v, (int, float)) and not isinstance(v, bool):
            continue
        return f"{key} is {_shape_word(v)}"
    return ""


# ── the per-arch sliding-window pattern, when the header does not spell it ───
# llama.cpp resolves is_swa(il) in TWO steps: an explicit per-layer boolean array in
# `attention.sliding_window_pattern` if the file has one, otherwise a PER-ARCH DEFAULT
# PERIOD applied by `llama_hparams::set_swa_pattern(n_pattern, dense_first)`
# (src/llama-hparams.cpp): dense_first ⇒ full attention at il % p == 0, else at
# il % p == p-1. Transcribed key-by-key from src/models/*.cpp at our pinned build.
# Archs that set a pattern ONLY when the key is present (muse-glimmer, cohere2moe,
# gemma4) are deliberately absent — for them "no key" means "no arch default".
#
# ⚠️ WITHOUT THIS, LAGUNA'S CACHE READ 94% LIGHT — 160 MiB against the oracle's 2680.
# Its 40 layers are 10 global + 30 windowed and it publishes no pattern key at all, so
# the old "sliding_window set ⇒ every layer windowed" fallback priced all 40 at a
# 1024-cell window. Measured, in the direction that says "fits".
SWA_PATTERN_DEFAULT = {
    "gemma2": (2, False), "gemma3": (6, False), "gemma3n": (5, False),
    "gemma-embedding": (6, False), "cohere2": (4, False), "olmo2": (4, False),
    "llama4": (4, False), "mellum": (4, False), "afmoe": (4, False),
    "exaone4": (4, False), "exaone-moe": (4, False), "plamo3": (8, False),
    "gpt-oss": (2, False), "smallthinker": (4, True), "modern-bert": (3, True),
    "laguna": (4, True),
}
# llama.cpp DISABLES Phi's sliding window outright (n_swa = 0, swa_type NONE, citing
# ggml-org/llama.cpp#13676 — the conversion scripts populate it wrongly). Believing the
# header there would under-price every Phi layer.
SWA_DISABLED_ARCH = ("phi3",)


def _swa_layer(i: int, period: int, dense_first: bool) -> bool:
    """llama_hparams::set_swa_pattern, transcribed. period 0 ⇒ every layer windowed;
    period 1 ⇒ none (which is how llama.cpp expresses 'switched off')."""
    if period <= 0:
        return True
    if dense_first:
        return (i % period) != 0
    return (i % period) < (period - 1)


