"""ROUTER — per-model SAMPLING settings, per-model LOAD settings, the launch snapshot."""
from __future__ import annotations

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from ..core.appctx import _voice, app
from ..core.procs import _registry_models
from .downloads import _registry_update


# ── Direct chat lane (Fable, 2026-07-23) ─────────────────────────────────────
# Chat mode goes straight to the runner (Jan :6767), bypassing Odysseus's per-turn
# machinery AND its in-process model lock — root-caused: Odysseus fires auxiliary
# LLM calls (titles/memory/search-queries, logged 5-38s each) at the same single-slot
# runner, so chat turns queue behind them and lose the prompt cache. Agent mode
# still routes via Odysseus (tools live there). History is read from and persisted
# back to the Odysseus session, so the rail/history stay coherent.
_RUNNER = httpx.AsyncClient(timeout=httpx.Timeout(20, read=None))

# ── Vision attachments (direct lane only) ────────────────────────────────────
# Both serving engines accept OpenAI-style image parts on /v1/chat/completions:
# llama-server with an mmproj projector, and mlx-vlm. The registry already knows
# which models are vision-capable (mmproj sibling for gguf, vision_config /
# image_token_id for mlx — see _gguf_registry_entry / _mlx_registry_entry), so the
# gate below is a registry lookup, never a probe of the model itself.
IMAGE_MAX_CHARS = 12 * 1024 * 1024   # dataURL length cap (~9MB of image bytes)


def build_user_content(text: str, image, vision: bool):
    """PURE: the user turn's `content` for the runner. Returns (content, error).

    no image                 → the plain string (legacy shape, byte-identical)
    image + vision model     → OpenAI parts [{text}, {image_url}]
    image + non-vision model → (None, reason)  → caller streams one proxy_error
    malformed / oversize     → (None, reason)

    Order matters: a malformed or oversize payload is reported as such even on a
    vision model, so the user learns what is actually wrong.
    """
    if not image:
        return text, None
    if not isinstance(image, str) or not image.startswith("data:image/"):
        return None, "attachment is not an image data URL — attach removed"
    if len(image) > IMAGE_MAX_CHARS:
        return None, "image too large — attach removed"
    if not vision:
        return None, "active model has no vision — attach removed"
    return ([{"type": "text", "text": text},
             {"type": "image_url", "image_url": {"url": image}}], None)


def _vision_capable(mid: str) -> bool:
    """Registry truth for one model id — the same flag the Models pane's VISION
    pill and the mlx-vlm engine dispatch read."""
    m = next((x for x in _registry_models() if x.get("id") == mid), None)
    return bool(m and (m.get("vision") or m.get("mmproj")))


def turn_metadata(model, usage, timings, elapsed=None):
    """Pure: the per-message metadata the DIRECT lane stamps on its assistant turn.

    The Agent lane gets server-written metrics for free (Odysseus writes
    response_time / input_tokens / output_tokens / tokens_per_second into the
    message row), so a reopened agent transcript can show per-reply stats. The
    direct lane persists via inject_messages, which accepts an optional
    per-message `metadata` — so the SAME keys, from the same usage/timings frame
    the analytics capture already parses, give the direct lane parity.

    Only keys we actually know are included (a runner build that reports no
    timings simply yields fewer stats, never zeros or nulls). Never raises.
    """
    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    u = usage if isinstance(usage, dict) else {}
    tm = timings if isinstance(timings, dict) else {}
    out = {}
    if model:
        out["model"] = model
    tps = _num(tm.get("predicted_per_second"))
    if tps is not None:
        out["tokens_per_second"] = round(tps, 2)
    el = _num(elapsed)
    if el is not None:
        out["response_time"] = round(el, 2)
    itok = _num(u.get("prompt_tokens"))
    if itok is not None:
        out["input_tokens"] = int(itok)
    otok = _num(u.get("completion_tokens"))
    if otok is not None:
        out["output_tokens"] = int(otok)
    return out


# ── Model sampling settings (per-model, DIRECT LANE) ─────────────────────────
# Spec basis: docs/research/2026-08-20-model-settings.md §0.1-0.5.
#
# THREE facts shape this block:
#  (1) Until now the direct lane sent NO sampling fields at all — every generation
#      ran on whatever the engine's own defaults were, and those differ per engine.
#  (2) mlx_lm.server defaults `max_tokens` to 512 and mlx_vlm to 2048 when the body
#      omits it, so every MLX reply was SILENTLY TRUNCATED. llama.cpp's -1 is
#      unbounded, which is why the gguf lane never showed it. `max_tokens` is
#      therefore ALWAYS sent now, for every model, whether or not it has overrides.
#  (3) `--repeat-penalty 1.1 --repeat-last-n 256` on the llama-server launch line
#      (scripts/start_component.sh) was a buried constant. It STAYS as the engine
#      default floor — that is the only thing reaching the Agent/Hermes lanes, which
#      build their own request bodies — but the same two numbers are now the VISIBLE
#      defaults here, and a request body overrides argv (Fable D2: body wins).
#
# LANE HONESTY (Fable D1): this is a DIRECT-LANE feature. Odysseus sends only
# temperature (from its own global admin preset) and Hermes structurally cannot send
# a temperature at all, so there is deliberately no fan-out. The panel says so.
SAMPLING_DEFAULTS = {
    "temperature": 0.7,       # llama.cpp's own is 0.8 (creative-completion tuned);
    "top_p": 0.95,            # 0.7 is the conventional assistant setting and is
    "top_k": 40,              # gentler on heavily-quantized local models.
    "min_p": 0.05,
    "repeat_penalty": 1.1,    # promoted verbatim from the argv constant (2026-08-06
    "repeat_last_n": 256,     # loop incident) — the one number here with evidence.
    "max_tokens": 4096,       # see (2): omitting this truncated every MLX reply.
    "seed": -1,               # -1 = random; never sent (MLX has no -1 convention).
}
# Display order for the UI (dict order is stable, but the UI must not depend on it).
SAMPLING_ORDER = ("temperature", "top_p", "top_k", "min_p",
                  "repeat_penalty", "repeat_last_n", "max_tokens", "seed")
# canonical key -> the BODY key that engine actually reads. The two penalty keys are
# genuinely named differently on the MLX servers; the numeric meaning is the same
# (logits of repeated tokens divided by the value, 1.0 = no-op), only the "disabled"
# sentinel differs (llama.cpp 1.0, MLX 0.0) — which is why we never write 0 here.
_S_MLX = {"temperature": "temperature", "top_p": "top_p", "top_k": "top_k",
          "min_p": "min_p", "repeat_penalty": "repetition_penalty",
          "repeat_last_n": "repetition_context_size",
          "max_tokens": "max_tokens", "seed": "seed"}
SAMPLING_WIRE = {
    "llamacpp": {k: k for k in SAMPLING_ORDER},
    "mlxlm": dict(_S_MLX),
    "mlxvlm": dict(_S_MLX),
}
# (min, max, coercer). Ranges are the union of what both engines accept; MLX
# publishes its own in mlx_lm/server.py:1229-1251 and these sit inside them.
SAMPLING_RANGES = {
    "temperature": (0.0, 2.0, float),
    "top_p": (0.0, 1.0, float),
    "top_k": (0, 500, int),          # 0 = off
    "min_p": (0.0, 1.0, float),      # 0 = off
    "repeat_penalty": (1.0, 2.0, float),   # 1.0 = off on BOTH scales
    "repeat_last_n": (-1, 8192, int),      # llama.cpp: -1 = whole ctx, 0 = off
    "max_tokens": (1, 262144, int),        # v2.1: no default change (4096 IS the MLX
    "seed": (-1, 2147483647, int),         # truncation fix) — only the ceiling moved.
}
# v2.1 (Debi ask, LM Studio reference): every row explains itself on hover. ONE source
# — the bridge computes the string, the panel only prints it — so a field can never be
# drawn without an explanation, and the explanation can never disagree with the range.
SAMPLING_HELP = {
    "temperature": ("Randomness. Lower is more predictable and repetitive, higher is "
                    "more varied. Near 0 is almost deterministic."),
    "top_p": ("Nucleus sampling — only consider the most likely tokens whose "
              "probabilities add up to this. 1.0 considers everything."),
    "top_k": "Only consider this many candidates per token. 0 = no limit.",
    "min_p": ("Drop candidates less likely than this fraction of the best one — "
              "a gentler filter than top_p."),
    "repeat_penalty": ("Divides the score of tokens already used, to break loops. "
                       "1.0 = off. 1.1 is the value that fixed the 'C-C-C…' loop here."),
    "repeat_last_n": ("How many recent tokens the repeat penalty looks back over. "
                      "-1 = the whole context."),
    "max_tokens": ("Longest single reply, in tokens — NOT the context window. The cap "
                   "exists because MLX otherwise silently stops replies at 512."),
    "seed": ("Fixes the random draw so the same prompt gives the same reply. "
             "-1 = random every time (nothing is sent to the engine)."),
}
SAMPLING_STOP_MAX = 4          # stop strings, storage/merge only — no UI row in v1
# v2 (2026-08-20, Debi ruling): the same saved values ALSO become the engine's launch
# defaults (scripts/start_component.sh, SAMPLING_FLOOR_WIRE below), so the Agent and
# Hermes lanes — which build their own bodies and send no sampling at all — inherit
# them. Only EXPLICIT overrides travel: a model with nothing saved keeps the engine's
# own defaults on those lanes, exactly as before.
SAMPLING_LANE_NOTE = ("Applies to CHAT immediately. Values you set here also become "
                      "the model's launch defaults for the Agent and Hermes lanes — "
                      "those pick them up the next time the model loads.")
# Which canonical sampling keys the engine accepts on its LAUNCH LINE (a different
# question from the request body: SAMPLING_WIRE). Evidence, re-read this session:
#   llama.cpp b10427 data/llama-server.help.txt:234,240,241,243,244,249,251
#   mlx_lm.server  data/mlx-venv/.../mlx_lm/server.py:1818-1848 (--temp/--top-p/
#                  --top-k/--min-p/--max-tokens; NO seed, NO repeat flags)
#   mlx_vlm.server mlx_vlm/server/cli.py:105 — --max-tokens ONLY of this set.
# Documentation of the seam; start_component.sh does the emitting (it owns the
# per-flag support gate). A flag that cannot be evidenced is never emitted.
SAMPLING_FLOOR_WIRE = {
    "llamacpp": {"temperature": "--temp", "top_p": "--top-p", "top_k": "--top-k",
                 "min_p": "--min-p", "repeat_penalty": "--repeat-penalty",
                 "repeat_last_n": "--repeat-last-n", "seed": "--seed"},
    "mlxlm": {"temperature": "--temp", "top_p": "--top-p", "top_k": "--top-k",
              "min_p": "--min-p", "max_tokens": "--max-tokens"},
    "mlxvlm": {"max_tokens": "--max-tokens"},
}


def sampling_engine(entry: dict) -> str:
    """PURE. Which request dialect this registry entry's server speaks. Mirrors
    start_component.sh:64-66 (format mlx + vision → mlx-vlm, mlx → mlx-lm, else
    llama.cpp). Anything unrecognisable falls back to llamacpp, whose key names are
    the OpenAI-ish ones every engine here tolerates."""
    e = entry if isinstance(entry, dict) else {}
    if str(e.get("format") or "").strip().lower() == "mlx":
        return "mlxvlm" if (e.get("vision") or e.get("mmproj")) else "mlxlm"
    return "llamacpp"


def _sampling_num(key: str, raw):
    """PURE. Coerce one value, or None when it is junk / out of range. Total: any
    input type is safe. Booleans are rejected (True == 1 would silently pass)."""
    spec = SAMPLING_RANGES.get(key)
    if spec is None or isinstance(raw, bool) or raw is None:
        return None
    lo, hi, cast = spec
    try:
        v = cast(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):     # NaN / inf
        return None
    if v < lo or v > hi:
        return None
    return v


def _sampling_stop(raw):
    """PURE. A stop list, or None. Accepts a list/tuple of strings or one string."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None
    out = [s[:64] for s in raw if isinstance(s, str) and s.strip()][:SAMPLING_STOP_MAX]
    return out or None


def sampling_saved(entry: dict) -> dict:
    """PURE. The per-model overrides, cleaned. Junk keys and junk values are dropped
    rather than surfaced — a hand-edited registry can never break a turn."""
    e = entry if isinstance(entry, dict) else {}
    raw = e.get("settings")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k, v in raw.items():
        if k == "stop":
            s = _sampling_stop(v)
            if s:
                out["stop"] = s
            continue
        n = _sampling_num(k, v)
        if n is not None:
            out[k] = n
    return out


def sampling_merge(entry: dict) -> dict:
    """PURE. harness defaults → per-model overrides → engine key translation.
    Returns the request-body fragment the direct lane merges in. NEVER raises, and
    ALWAYS contains a `max_tokens` (that absence is the MLX truncation bug).

    `seed` is omitted unless explicitly set to >= 0: -1 means "random" to
    llama.cpp but is not a documented MLX sentinel, so we send nothing instead."""
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    vals = dict(SAMPLING_DEFAULTS)
    vals.update(sampling_saved(entry))
    out = {}
    for canon in SAMPLING_ORDER:
        if canon not in wire:
            continue                     # engine cannot honour it — send nothing
        v = vals.get(canon)
        if v is None:
            continue
        if canon == "seed" and v < 0:
            continue
        out[wire[canon]] = v
    stop = vals.get("stop")
    if stop:
        out["stop"] = list(stop)
    return out


def sampling_view(entry: dict) -> dict:
    """PURE. What the Models detail pane renders: the engine, and one row per field
    this engine can actually honour, carrying its wire name (the honest label), the
    harness default, and the per-model override (None = running the default).

    Engine-conditional by construction: a field the engine cannot honour is ABSENT,
    not greyed out — a control that cannot work must not be drawn."""
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    saved = sampling_saved(entry)
    fields = []
    for canon in SAMPLING_ORDER:
        if canon not in wire:
            continue
        lo, hi, _c = SAMPLING_RANGES[canon]
        fields.append({"key": canon, "label": wire[canon],
                       "default": SAMPLING_DEFAULTS.get(canon),
                       "value": saved.get(canon), "min": lo, "max": hi,
                       # v2.1: plain-language tooltip, single-sourced here.
                       "help": SAMPLING_HELP.get(canon, "")})
    return {"engine": eng, "fields": fields,
            "changed": sum(1 for f in fields if f["value"] is not None),
            "note": SAMPLING_LANE_NOTE}


@app.post("/api/models/settings")
async def api_model_settings(req: Request) -> JSONResponse:
    """{id, settings:{key: value|null}} → per-model sampling overrides.

    ⚠️ SEAM CHOICE: there is deliberately no GET here. `/api/models` already
    carries every installed entry and the panel already polls it, so the read side
    is one extra key on that payload (`sampling`) rather than a second route.

    A null value REMOVES that key (the _registry_update grammar the voice pins
    established: a reset is the ABSENCE of a key, never a stored null), and an
    empty result removes `settings` entirely. `{id, reset:true}` resets all."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    if _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse({"ok": False, "error": f"'{mid}' is a voice model — "
                                                   f"sampling settings are for chat models"},
                            status_code=400)
    if body.get("reset"):
        _registry_update(mid, {"settings": None})
        print(f"[models] sampling reset {mid}", flush=True)
        upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
        return JSONResponse({"ok": True, "id": mid, "settings": {},
                             "sampling": sampling_view(upd),
                             "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})
    patch = body.get("settings")
    if not isinstance(patch, dict) or not patch:
        return JSONResponse({"ok": False, "error": "settings must be a non-empty object"},
                            status_code=400)
    eng = sampling_engine(entry)
    wire = SAMPLING_WIRE.get(eng) or SAMPLING_WIRE["llamacpp"]
    new = sampling_saved(entry)
    for k, v in patch.items():
        if k == "stop":
            if v is None:
                new.pop("stop", None)
                continue
            s = _sampling_stop(v)
            if s is None:
                return JSONResponse({"ok": False, "error": "stop must be a list of strings"},
                                    status_code=400)
            new["stop"] = s
            continue
        if k not in SAMPLING_RANGES or k not in wire:
            return JSONResponse(
                {"ok": False, "error": f"'{k}' is not a sampling field this engine "
                                       f"({eng}) can honour"}, status_code=400)
        if v is None or v == "":
            new.pop(k, None)
            continue
        n = _sampling_num(k, v)
        if n is None:
            lo, hi, _c = SAMPLING_RANGES[k]
            return JSONResponse({"ok": False,
                                 "error": f"{k} must be a number between {lo} and {hi}"},
                                status_code=400)
        new[k] = n
    _registry_update(mid, {"settings": new or None})
    print(f"[models] sampling {mid} -> {new or 'defaults'}", flush=True)
    upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
    return JSONResponse({"ok": True, "id": mid, "settings": new,
                         "sampling": sampling_view(upd),
                         # A sampling change can move the LAUNCH claim too (floors).
                         "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})


# ── Model LOAD settings (per-model, LAUNCH LINE) ──────────────────────────────
# Sampling v1 was deliberately request-body only (Fable D3) because every field here
# costs a 60-90s model reload. That is the whole difference: these are written the
# same way (an optional `load` dict on the registry entry, through _registry_update,
# None removes the key, carried across a RESCAN via seed_registry.USER_KEYS), but
# they only take effect when the runner relaunches — which is what the panel's
# "Apply & reload" chip does, via the EXISTING /api/models/switch on the same id.
#
# ENGINE HONESTY: all four are llama.cpp launch flags. `mlx_lm.server` has no
# context, gpu-layer, flash-attn or KV-quant flag at all (research §1.3: "Confirmed
# absent: --api-key and any --ctx-size"), and `mlx_vlm.server`'s KV suite is a
# BIT-COUNT/scheme API (--kv-bits/--kv-quant-scheme), not llama.cpp's `q8_0` type
# names — mapping one onto the other would be inventing a translation, so an MLX
# model's Load group is simply ABSENT rather than drawn with dead controls.
#
# v2.1 (2026-08-20, Debi ask): the group is filled out with the rest of llama.cpp's
# load-time surface. EVERY new flag was read out of this pinned binary's own
# `data/llama-server.help.txt` before it was added (line refs on each row below) —
# the same evidence discipline as the MTP flags. Nothing was added for MLX, because
# nothing exists there to add.
LOAD_ORDER = ("ctx", "gpu_layers", "flash_attn", "kv_quant", "threads",
              "batch", "ubatch", "mlock", "mmap",
              "rope_freq_base", "rope_freq_scale")
# canonical key -> the LAUNCH FLAG that engine reads. Empty dict = no Load group.
#   help refs: --ctx-size :23, -ngl/--n-gpu-layers :117, -fa/--flash-attn :39,
#   -ctk/-ctv :75-82, -t/--threads :7, -b/--batch-size :29, -ub/--ubatch-size :31,
#   --mlock :87, --mmap/--no-mmap :89, --rope-freq-base :51, --rope-freq-scale :54.
LOAD_WIRE = {
    "llamacpp": {"ctx": "--ctx-size", "gpu_layers": "--n-gpu-layers",
                 "flash_attn": "--flash-attn", "kv_quant": "--cache-type-k/v",
                 "threads": "--threads", "batch": "--batch-size",
                 "ubatch": "--ubatch-size", "mlock": "--mlock",
                 "mmap": "--mmap/--no-mmap",
                 "rope_freq_base": "--rope-freq-base",
                 "rope_freq_scale": "--rope-freq-scale"},
    "mlxlm": {},
    "mlxvlm": {},
}
# Displayed as the "default" beside each row. These are what the runner does TODAY
# with nothing saved, not a harness opinion: ctx falls back to the registry entry's
# own ctx (start_component.sh:89-91), and the rest are llama.cpp's own documented
# defaults (help :117 auto, :39 auto, :75-82 f16, :7 -1/auto, :29 2048, :31 512,
# :87 off, :89 enabled, :51/:54 loaded from the model).
LOAD_DEFAULTS = {"ctx": "registry / 65536", "gpu_layers": "auto",
                 "flash_attn": "auto", "kv_quant": "f16", "threads": "auto",
                 "batch": "2048", "ubatch": "512", "mlock": "off", "mmap": "on",
                 "rope_freq_base": "from the model",
                 "rope_freq_scale": "from the model"}
LOAD_RANGES = {"ctx": (1024, 262144, int), "gpu_layers": (-1, 999, int),
               "threads": (1, 32, int), "batch": (1, 32768, int),
               "ubatch": (1, 32768, int),
               "rope_freq_base": (0.0, 10000000.0, float),
               "rope_freq_scale": (0.0, 100.0, float)}
# ⚠️ -1 is the conventional "all layers" value users type; start_component.sh
# translates it to llama.cpp's own documented `all` token at the argv seam.
LOAD_BOOLS = ("flash_attn", "mlock", "mmap")
# Which int rows deserve an LM-Studio-style slider beside the box (step, in the
# field's own unit). Only the three a user genuinely drags; the rest stay numbers.
LOAD_SLIDER_STEP = {"ctx": 1024, "gpu_layers": 1, "threads": 1}
LOAD_KV_TYPES = ("off", "q8_0", "q4_0")   # a SUBSET of the 9 the engine accepts —
# the three that are actually useful decisions (off = leave the f16 default alone).
LOAD_NOTE = ("These change how the model is LOADED — Apply & reload restarts the "
             "runner (60–90s). Your sampling values are applied on the same reload.")
LOAD_HELP = {
    "ctx": ("How much conversation the model can see at once, in tokens. "
            "Bigger = more RAM, and a slower first reply on a long chat."),
    "gpu_layers": ("How many layers run on the GPU. -1 = all of them — on Apple "
                   "unified memory that is almost always what you want."),
    "flash_attn": ("Faster, lower-memory attention. 'auto' lets the engine decide; "
                   "turn it off only if a model misbehaves with it on."),
    "kv_quant": ("Compresses the attention cache — much less RAM at long context, "
                 "for a slight quality cost. q8_0 is the safe one, q4_0 the small one."),
    "threads": ("CPU threads used for generation. The engine picks a sensible number "
                "on its own; set this only to leave cores free for other work."),
    "batch": ("How many prompt tokens are queued for processing at a time. Bigger can "
              "prefill a long prompt faster and uses more memory."),
    "ubatch": ("How many tokens are actually computed in one pass. Lower it if a very "
               "long prompt runs the machine out of memory."),
    "mlock": ("Keep the whole model pinned in RAM so macOS can never swap it out. "
              "Costs the model's full size in RAM the entire time it is loaded."),
    "mmap": ("Memory-map the weights instead of reading them in. On = faster start "
             "(the default); off = slower load but fewer page-outs."),
    "rope_freq_base": ("Advanced: RoPE base frequency, used to stretch a model past "
                       "the context it was trained on. Leave empty unless the model "
                       "card gives you a number."),
    "rope_freq_scale": ("Advanced: RoPE frequency scale — 0.5 doubles the usable "
                        "context. Leave empty unless the model card gives you a "
                        "number."),
}


def _load_val(key: str, raw):
    """PURE. Coerce one load value, or None when it is junk / out of range. Total:
    any input type is safe. Mirrors _sampling_num, plus the two non-numeric kinds."""
    if raw is None:
        return None
    if key in LOAD_BOOLS:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("on", "true", "1", "yes"):
            return True
        if s in ("off", "false", "0", "no"):
            return False
        return None
    if key == "kv_quant":
        s = str(raw).strip().lower() if not isinstance(raw, bool) else ""
        return s if s in LOAD_KV_TYPES else None
    spec = LOAD_RANGES.get(key)
    if spec is None or isinstance(raw, bool):
        return None
    lo, hi, cast = spec
    try:
        v = cast(raw)                       # OverflowError: int(inf); ValueError: int(nan)
    except (TypeError, ValueError, OverflowError):
        return None
    if v != v:
        return None
    return None if (v < lo or v > hi) else v


def load_saved(entry: dict) -> dict:
    """PURE. The per-model load overrides, cleaned. Junk keys and junk values are
    dropped rather than surfaced — a hand-edited registry can never fail a launch."""
    e = entry if isinstance(entry, dict) else {}
    raw = e.get("load")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for k in LOAD_ORDER:
        if k not in raw:
            continue
        v = _load_val(k, raw.get(k))
        if v is not None:
            out[k] = v
    return out


def load_view(entry: dict) -> dict:
    """PURE. One row per field THIS engine can honour — absent, never greyed out.

    ⚠️ v2.1: the `applied` claim MOVED OUT of here to `launch_view`. It never
    belonged to the Load group alone: an MLX model has no load fields at all, yet
    its saved sampling values DO ride its launch line, so it had pending-launch
    changes with no group to host the Apply chip. See launch_saved/launch_view."""
    eng = sampling_engine(entry)
    wire = LOAD_WIRE.get(eng, {})
    saved = load_saved(entry)
    fields = []
    for canon in LOAD_ORDER:
        if canon not in wire:
            continue
        row = {"key": canon, "label": wire[canon],
               "default": LOAD_DEFAULTS.get(canon), "value": saved.get(canon),
               "help": LOAD_HELP.get(canon, "")}
        if canon in LOAD_RANGES:
            row["min"], row["max"], cast = LOAD_RANGES[canon]
            row["kind"] = "int" if cast is int else "float"
            if canon in LOAD_SLIDER_STEP:
                row["slider"] = LOAD_SLIDER_STEP[canon]
        elif canon in LOAD_BOOLS:
            row["kind"] = "bool"
        else:
            row["kind"] = "enum"
            row["choices"] = list(LOAD_KV_TYPES)
        fields.append(row)
    return {"engine": eng, "fields": fields,
            "changed": sum(1 for f in fields if f["value"] is not None),
            "note": LOAD_NOTE}


# ── The UNIFIED launch snapshot (v2.1) ───────────────────────────────────────
# What a relaunch would change is NOT only the Load group: the sampling FLOORS ride
# the same launch line (SAMPLING_FLOOR_WIRE), and on an MLX model they are the ONLY
# thing that does. So the record of "what the runner was actually started with" is
# both halves together, and the Apply & reload affordance hangs off THAT — which is
# what makes it appear for an MLX model, whose Load group is empty by construction.
LAUNCH_NOTE = ("Sampling applies to CHAT on your next message. Apply & reload "
               "restarts the runner (60–90s) so these also become the launch "
               "defaults the Agent and Hermes lanes inherit.")


def floor_saved(entry: dict) -> dict:
    """PURE. The saved sampling values that actually reach THIS engine's launch
    line — the rest cannot change a relaunch and must not make it look pending."""
    wire = SAMPLING_FLOOR_WIRE.get(sampling_engine(entry), {})
    return {k: v for k, v in sampling_saved(entry).items() if k in wire}


def launch_saved(entry: dict) -> dict:
    """PURE. Everything a relaunch would carry, in one comparable record."""
    return {"load": load_saved(entry), "floors": floor_saved(entry)}


def launch_view(entry: dict, launched=None) -> dict:
    """PURE. The shared Apply & reload row.

    `applied` is a three-state claim, and the third state matters: None means the
    bridge never launched this model itself and therefore has NO opinion (it must
    not tell the user their change is unapplied when it cannot know). False = the
    saved set differs from what the runner was actually launched with."""
    saved = launch_saved(entry)
    eng = sampling_engine(entry)
    applied = None
    if isinstance(launched, dict):
        prev = {"load": launched.get("load") if isinstance(launched.get("load"), dict) else {},
                "floors": launched.get("floors") if isinstance(launched.get("floors"), dict) else {}}
        applied = (saved == prev)
    return {"engine": eng, "applied": applied, "note": LAUNCH_NOTE,
            # How many saved values a relaunch would actually carry — the honest
            # count for "there is something to apply here".
            "changed": len(saved["load"]) + len(saved["floors"]),
            # Whether this engine has ANY launch-line surface at all. True for all
            # three today (mlx-vlm still takes --max-tokens), but the panel asks
            # rather than assumes, so a future engine with none draws no chip.
            "appliable": bool(LOAD_WIRE.get(eng, {})
                              or SAMPLING_FLOOR_WIRE.get(eng, {}))}


# Process-lifetime record of the launch set the runner was ACTUALLY launched with,
# written only where WE launch it (_do_switch / the runner start path). A model the
# bridge never started has no entry — and therefore launch_view makes no claim.
_LOAD_AT_LAUNCH: dict = {}


def _record_load_launch(model_id: str) -> None:
    """Best-effort: never raises into a start path."""
    try:
        if not model_id:
            return
        e = next((m for m in _registry_models() if m.get("id") == model_id), None)
        _LOAD_AT_LAUNCH[model_id] = launch_saved(e or {})
    except Exception:
        pass


@app.post("/api/models/load-settings")
async def api_model_load_settings(req: Request) -> JSONResponse:
    """{id, load:{key: value|null}} → per-model LOAD overrides (+ {id, reset:true}).

    Same seam choice as sampling: no GET — `/api/models` already carries `load`
    (the raw pin) and `loadview` (the rendered, engine-filtered view)."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mid = str(body.get("id") or "").strip()
    if not mid:
        return JSONResponse({"ok": False, "error": "no model id given"}, status_code=400)
    entry = next((m for m in _registry_models() if m.get("id") == mid), None)
    if entry is None:
        return JSONResponse({"ok": False, "error": f"'{mid}' is not in the registry"},
                            status_code=400)
    if _voice is not None and _voice.is_audio_entry(entry):
        return JSONResponse({"ok": False, "error": f"'{mid}' is a voice model — "
                                                   f"load settings are for chat models"},
                            status_code=400)
    if body.get("reset"):
        _registry_update(mid, {"load": None})
        print(f"[models] load reset {mid}", flush=True)
        upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
        return JSONResponse({"ok": True, "id": mid, "load": {},
                             "loadview": load_view(upd),
                             "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})
    patch = body.get("load")
    if not isinstance(patch, dict) or not patch:
        return JSONResponse({"ok": False, "error": "load must be a non-empty object"},
                            status_code=400)
    eng = sampling_engine(entry)
    wire = LOAD_WIRE.get(eng, {})
    new = load_saved(entry)
    for k, v in patch.items():
        if k not in LOAD_ORDER or k not in wire:
            return JSONResponse(
                {"ok": False, "error": f"'{k}' is not a load setting this engine "
                                       f"({eng}) can honour"}, status_code=400)
        if v is None or v == "":
            new.pop(k, None)
            continue
        val = _load_val(k, v)
        if val is None:
            if k == "kv_quant":
                msg = f"kv_quant must be one of {', '.join(LOAD_KV_TYPES)}"
            elif k in LOAD_BOOLS:
                msg = f"{k} must be on or off"
            else:
                lo, hi, cast = LOAD_RANGES[k]
                kind = "a whole number" if cast is int else "a number"
                msg = f"{k} must be {kind} between {lo} and {hi}"
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        new[k] = val
    _registry_update(mid, {"load": new or None})
    print(f"[models] load {mid} -> {new or 'engine defaults'}", flush=True)
    upd = next((m for m in _registry_models() if m.get("id") == mid), entry)
    return JSONResponse({"ok": True, "id": mid, "load": new,
                         "loadview": load_view(upd),
                         "launch": launch_view(upd, _LOAD_AT_LAUNCH.get(mid))})
