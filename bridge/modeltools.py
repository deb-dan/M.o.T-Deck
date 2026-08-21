"""TOOL-CALLING CAPABILITY per chat model (2026-08-21, the OpenCode slice).

The harness had no idea which of its models can emit tool calls, and it now needs
one: OpenCode requires tool-calling and has **no text-edit fallback** — on a model
that cannot emit a well-formed call it looks *broken*, not *worse*
(docs/research/2026-08-21-opencode-omnigent-recon.md §1). So the panel gates on a
`tools` pill, LM-Studio style, and this module is where that verdict comes from.

THE EVIDENCE IS THE CHAT TEMPLATE, not the model's name. Neither engine we run
advertises tool support per model, but a model that can be *prompted* for tools
ships a Jinja chat template that knows how to render them — `{% if tools %}`,
`<tool_call>`, `[AVAILABLE_TOOLS]`. A template with none of those markers renders
a tool list nowhere, so the model never sees the tools at all.

  MLX  : the template lives in `tokenizer_config.json` (key `chat_template`), or in
         a sibling `chat_template.jinja` (newer transformers exports).
  GGUF : the template is GGUF METADATA — the key `tokenizer.chat_template` in the
         file header. `gguf_chat_template` below is a minimal, bounded reader for
         exactly that: it walks the KV section and stops at the key or at the cap.
         It never reads a tensor and never loads the model.

THE VERDICT IS THREE-VALUED and the third value matters:
    True   the template renders tools
    False  there IS a template and it does not mention them
    None   we could not tell (no template, unreadable file, a shape we do not know)
A `None` must never be drawn as "no tools": absent-not-greyed. The panel shows a
pill for True, nothing otherwise, and the OpenCode start gate WARNS (never refuses)
— a heuristic may not stop a user from launching a program.

⚠️ HONEST LIMIT: this is a template-text heuristic, not a capability negotiation.
A template that merely mentions the word "tools" in prose would read as True, and a
model whose template supports tools under a marker we do not list would read as
False. Both are informational-only failures by construction (see the gate above).
Nothing here is a promise that a given quant will emit a *well-formed* call — that
is a property of the quant and the sampler, and it is unmeasurable from here.

Pure + stdlib only. `scripts/seed_registry.py` loads this file by path (it is not a
package for that script) and degrades to `tools: None` if it cannot; the bridge
imports it normally.
"""
import json
import os
import struct

# ── the marker rule ──────────────────────────────────────────────────────────
# Lowercase substrings. Deliberately narrow and concrete: every one of these is a
# token a template EMITS or BRANCHES ON, not a word a system prompt would use in
# passing. (`functions` is deliberately absent — it is ordinary English.)
TOOL_MARKERS = (
    "tool_call",          # qwen / hermes / llama-3.1 / deepseek …
    "tool_calls",         # the message-history field name
    "tool_response",      # qwen's result block
    "available_tools",    # mistral's [AVAILABLE_TOOLS]
    "tool_use",           # anthropic-style, and HF's named-template variant
    "tools|",             # jinja filter chains: {{ tools | tojson }}
    "if tools",           # {% if tools %} — the branch itself
    "for tool in",        # {% for tool in tools %}
    "tools is not none",
    "<tools>",
)


def _template_text(value) -> str:
    """Flatten whatever `chat_template` turned out to be into one searchable string.

    HuggingFace allows THREE shapes and the third is itself evidence: a LIST of
    `{"name": ..., "template": ...}` — and the conventional name for the second
    entry is `tool_use`. So the names are folded in alongside the bodies.
    TOTAL: any surprise type contributes nothing rather than raising.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append(str(k))
            parts.append(_template_text(v))
        return "\n".join(parts)
    if isinstance(value, (list, tuple)):
        return "\n".join(_template_text(v) for v in value)
    return ""


def template_supports_tools(value):
    """True / False / None for one chat template value. PURE."""
    text = _template_text(value)
    if not text.strip():
        return None                      # no template ⇒ no evidence either way
    low = text.lower()
    return any(m in low for m in TOOL_MARKERS)


# ── GGUF: a bounded metadata reader ──────────────────────────────────────────
# Format (ggml-org/llama.cpp docs/gguf.md): "GGUF" magic, u32 version, then the
# tensor and KV counts (u32 each at v1, u64 from v2), then `kv_count` pairs of
#   key   : u64 length + UTF-8 bytes
#   type  : u32 enum
#   value : per the enum below; ARRAY carries its own element type + u64 count.
# We only ever READ the one string we want and SKIP everything else, so the vocab
# array (which is megabytes) costs seeks, not memory.
GGUF_MAGIC = b"GGUF"
GGUF_CHAT_TEMPLATE_KEY = "tokenizer.chat_template"
_FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_T_STRING = 8
_T_ARRAY = 9
# Caps. A metadata section is normally 2-12MB (the tokenizer's tokens + merges); a
# file claiming more than this, or more KV pairs than any real model has, is either
# corrupt or something we do not understand — and either way the answer is "unknown",
# never a crash and never an unbounded read.
MAX_META_BYTES = 96 * 1024 * 1024
MAX_KV_COUNT = 100_000
MAX_STRING_BYTES = 8 * 1024 * 1024


class _Cursor:
    """A forward-only reader over a binary file object with a hard byte budget.
    Raises ValueError on anything malformed, which the caller turns into None."""

    def __init__(self, fh, budget=MAX_META_BYTES):
        self.fh = fh
        self.left = int(budget)

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
        # seek, not read: skipping the vocab must not materialise it.
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

    def skip_string(self):
        n = self.u64()
        if n > MAX_STRING_BYTES:
            raise ValueError("implausible string length")
        self.skip(n)

    def skip_value(self, vtype):
        if vtype in _FIXED:
            self.skip(_FIXED[vtype])
            return
        if vtype == _T_STRING:
            self.skip_string()
            return
        if vtype == _T_ARRAY:
            et = self.u32()
            n = self.u64()
            if et == _T_ARRAY:
                # Nested arrays are legal in the spec and absent from every model we
                # have seen. Refusing is honest; guessing would desync the cursor.
                raise ValueError("nested gguf array")
            if et in _FIXED:
                self.skip(_FIXED[et] * n)
                return
            if et == _T_STRING:
                for _ in range(n):
                    self.skip_string()
                return
            raise ValueError("unknown gguf array element type")
        raise ValueError("unknown gguf value type")


def gguf_chat_template(fh):
    """The `tokenizer.chat_template` string from an OPEN gguf file, or None.

    None covers every "we cannot tell" case: not a GGUF, an unsupported version, a
    corrupt header, the key absent, or the metadata larger than the cap. Takes a
    file OBJECT so a test can hand it BytesIO.
    """
    try:
        c = _Cursor(fh)
        if c.take(4) != GGUF_MAGIC:
            return None
        version = c.u32()
        if version == 1:
            c.u32()                       # tensor count
            kv = c.u32()
        elif version in (2, 3):
            c.u64()                       # tensor count
            kv = c.u64()
        else:
            return None
        if kv > MAX_KV_COUNT:
            return None
        for _ in range(kv):
            key = c.string()
            vtype = c.u32()
            if key == GGUF_CHAT_TEMPLATE_KEY:
                if vtype != _T_STRING:
                    return None
                return c.string()
            c.skip_value(vtype)
    except (ValueError, OSError, struct.error):
        return None
    return None


def gguf_tools_flag(path):
    """True / False / None for one .gguf file on disk."""
    try:
        with open(path, "rb") as fh:
            tpl = gguf_chat_template(fh)
    except OSError:
        return None
    return template_supports_tools(tpl)


# ── MLX: tokenizer_config.json (or a sibling chat_template.jinja) ─────────────
MLX_TOKENIZER_CONFIG = "tokenizer_config.json"
MLX_TEMPLATE_FILE = "chat_template.jinja"


def mlx_tools_flag(folder):
    """True / False / None for one MLX model DIRECTORY."""
    try:
        with open(os.path.join(folder, MLX_TOKENIZER_CONFIG),
                  encoding="utf-8", errors="replace") as fh:
            cfg = json.load(fh)
        if isinstance(cfg, dict):
            v = template_supports_tools(cfg.get("chat_template"))
            if v is not None:
                return v
    except (OSError, ValueError):
        pass
    # transformers >= 4.43 may export the template as its own file instead.
    try:
        with open(os.path.join(folder, MLX_TEMPLATE_FILE),
                  encoding="utf-8", errors="replace") as fh:
            return template_supports_tools(fh.read())
    except (OSError, ValueError):
        return None


def tools_for_entry(entry):
    """True / False / None for ONE registry entry. Never raises.

    AUDIO entries are skipped outright (a TTS model has no tool surface and its
    `path` may be a directory of a shape neither reader understands)."""
    if not isinstance(entry, dict):
        return None
    if entry.get("kind") == "audio":
        return None
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        return None
    fmt = str(entry.get("format") or "gguf").strip().lower()
    try:
        if fmt == "mlx":
            return mlx_tools_flag(path if os.path.isdir(path)
                                  else os.path.dirname(path))
        return gguf_tools_flag(path)
    except Exception:                                          # noqa: BLE001
        return None


def annotate_tools(models, probe=tools_for_entry):
    """Fill `tools` on every chat entry that has no verdict yet, IN PLACE, and
    return the list. `probe` is injected so the pure decision can be tested with
    no filesystem.

    Deliberately only fills a MISSING key: `tools` is derived from files, so a
    rescan may legitimately recompute it — but an entry that already carries a
    verdict is left alone within one pass, which keeps the pass idempotent and
    cheap (a GGUF header read per model, per rescan, is the cost)."""
    if not isinstance(models, list):
        return models
    for m in models:
        if not isinstance(m, dict) or m.get("kind") == "audio":
            continue
        if "tools" in m and m.get("tools") is not None:
            continue
        m["tools"] = probe(m)
    return models
