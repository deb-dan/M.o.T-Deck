"""bridge/modeltools.py — the per-model tool-calling verdict.

The GGUF half is exercised against REAL, handcrafted GGUF bytes rather than a mock,
because the whole point of that reader is that it walks a binary layout correctly:
a mocked cursor would prove nothing about the one thing that can go wrong (skipping
a 150k-entry token array without desyncing).

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_model_tools.py -q
"""
import io
import json
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from bridge import modeltools as mt                                    # noqa: E402

CHECKS = []


def ok(cond, label):
    CHECKS.append(label)
    assert cond, label


# ── a minimal GGUF writer, so the reader is tested against the real layout ────
T_U32, T_BOOL, T_STRING, T_ARRAY = 4, 7, 8, 9


def _s(text):
    b = text.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _val(vtype, v):
    if vtype == T_STRING:
        return _s(v)
    if vtype == T_U32:
        return struct.pack("<I", v)
    if vtype == T_BOOL:
        return struct.pack("<B", 1 if v else 0)
    if vtype == T_ARRAY:
        et, items = v
        out = struct.pack("<I", et) + struct.pack("<Q", len(items))
        for it in items:
            out += _val(et, it)
        return out
    raise AssertionError("unhandled type in the test writer")


def gguf(kvs, version=3, tensors=0):
    """kvs = [(key, vtype, value)] → the bytes of a GGUF header."""
    out = b"GGUF" + struct.pack("<I", version)
    out += (struct.pack("<II", tensors, len(kvs)) if version == 1
            else struct.pack("<QQ", tensors, len(kvs)))
    for key, vtype, value in kvs:
        out += _s(key) + struct.pack("<I", vtype) + _val(vtype, value)
    return out


TOOLY = ("{% if tools %}<tools>{{ tools | tojson }}</tools>{% endif %}"
         "{{ message.content }}")
PLAIN = "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}{% endfor %}"


def test_template_marker_rule():
    ok(mt.template_supports_tools(TOOLY) is True, "a tool-rendering template is True")
    ok(mt.template_supports_tools(PLAIN) is False, "a plain template is False")
    ok(mt.template_supports_tools("") is None, "an empty template is UNKNOWN, not False")
    ok(mt.template_supports_tools("   \n ") is None, "whitespace-only is UNKNOWN")
    ok(mt.template_supports_tools(None) is None, "absent is UNKNOWN")
    # THE THREE-VALUED RULE stated as a negative: nothing may ever be False by default.
    for junk in (0, 1, 3.5, True, [], {}, (), b"tools"):
        ok(mt.template_supports_tools(junk) is None,
           f"junk {junk!r} is UNKNOWN, never a verdict")


def test_template_shapes():
    # HuggingFace's LIST shape — and its conventional second entry is literally named
    # `tool_use`, so the NAMES are evidence as much as the bodies are.
    lst = [{"name": "default", "template": PLAIN},
           {"name": "tool_use", "template": PLAIN}]
    ok(mt.template_supports_tools(lst) is True,
       "a named `tool_use` template variant counts even when the body is plain")
    ok(mt.template_supports_tools([{"name": "default", "template": PLAIN}]) is False,
       "a list of plain templates is still False")
    ok(mt.template_supports_tools({"default": PLAIN}) is False, "dict shape works")
    ok(mt.template_supports_tools({"default": TOOLY}) is True, "dict shape finds markers")


def test_marker_list_is_specific():
    """Every marker must be a token a TEMPLATE emits, not an English word — otherwise
    a system prompt mentioning tools would forge a capability."""
    ok("functions" not in mt.TOOL_MARKERS, "`functions` is ordinary English — excluded")
    ok("tool" not in mt.TOOL_MARKERS, "the bare word `tool` is excluded")
    ok(mt.template_supports_tools("You are a helpful assistant with no tool access.")
       is False, "prose mentioning a tool is not a capability")


def test_gguf_reads_the_template():
    b = gguf([("general.architecture", T_STRING, "llama"),
              ("tokenizer.chat_template", T_STRING, TOOLY)])
    ok(mt.gguf_chat_template(io.BytesIO(b)) == TOOLY, "the template is read verbatim")
    b2 = gguf([("tokenizer.chat_template", T_STRING, PLAIN)])
    ok(mt.template_supports_tools(mt.gguf_chat_template(io.BytesIO(b2))) is False,
       "a plain gguf template is False")


def test_gguf_skips_everything_else():
    """The load-bearing case: the vocab array sits BEFORE the template in most real
    files, and skipping it wrong desyncs the cursor and loses the key."""
    vocab = [f"tok{i}" for i in range(5000)]
    b = gguf([
        ("general.name", T_STRING, "x"),
        ("llama.block_count", T_U32, 32),
        ("general.quantized", T_BOOL, True),
        ("tokenizer.ggml.tokens", T_ARRAY, (T_STRING, vocab)),
        ("tokenizer.ggml.token_type", T_ARRAY, (T_U32, list(range(5000)))),
        ("tokenizer.chat_template", T_STRING, TOOLY),
    ])
    ok(mt.gguf_chat_template(io.BytesIO(b)) == TOOLY,
       "the template is found AFTER a 5000-entry string array and a fixed-type array")


def test_gguf_version_1_layout():
    b = gguf([("tokenizer.chat_template", T_STRING, TOOLY)], version=1)
    ok(mt.gguf_chat_template(io.BytesIO(b)) == TOOLY, "v1's u32 counts are handled")


def test_gguf_totality():
    cases = {
        "not a gguf": b"NOPE" + b"\x00" * 64,
        "empty": b"",
        "magic only": b"GGUF",
        "unknown version": b"GGUF" + struct.pack("<I", 99) + b"\x00" * 32,
        "truncated header": b"GGUF" + struct.pack("<I", 3) + b"\x00" * 4,
        "junk": bytes(range(256)) * 4,
    }
    for label, raw in cases.items():
        ok(mt.gguf_chat_template(io.BytesIO(raw)) is None, f"{label} → None")
    # A truncated VALUE mid-walk must also be None, not a partial string.
    b = gguf([("tokenizer.chat_template", T_STRING, TOOLY)])
    ok(mt.gguf_chat_template(io.BytesIO(b[:-5])) is None, "a truncated value → None")
    # The key simply absent.
    ok(mt.gguf_chat_template(io.BytesIO(gguf([("general.name", T_STRING, "x")])))
       is None, "no chat template key → None")
    # An implausible kv count is refused BEFORE it can drive a huge loop.
    bad = b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 10 ** 9)
    ok(mt.gguf_chat_template(io.BytesIO(bad)) is None, "an absurd kv count → None")
    # An implausible string length is refused before allocating it.
    huge = (b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 1)
            + struct.pack("<Q", 1 << 40) + b"x")
    ok(mt.gguf_chat_template(io.BytesIO(huge)) is None, "an absurd key length → None")
    # A nested array is legal in the spec, absent from every model we have seen, and
    # REFUSED rather than guessed — a wrong guess would desync the cursor silently.
    nested = gguf([("a", T_ARRAY, (T_ARRAY, []))])
    ok(mt.gguf_chat_template(io.BytesIO(nested)) is None, "a nested array → None")
    # An unknown value type is refused for the same reason.
    unk = (b"GGUF" + struct.pack("<I", 3) + struct.pack("<QQ", 0, 1)
           + _s("k") + struct.pack("<I", 77))
    ok(mt.gguf_chat_template(io.BytesIO(unk)) is None, "an unknown value type → None")


def test_gguf_wrong_type_for_the_template_key():
    b = gguf([("tokenizer.chat_template", T_U32, 5)])
    ok(mt.gguf_chat_template(io.BytesIO(b)) is None,
       "a non-string chat_template is UNKNOWN rather than a coerced value")


def test_gguf_tools_flag_on_disk():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.gguf")
        with open(p, "wb") as fh:
            fh.write(gguf([("tokenizer.chat_template", T_STRING, TOOLY)]))
        ok(mt.gguf_tools_flag(p) is True, "a tool-capable gguf on disk is True")
        p2 = os.path.join(d, "n.gguf")
        with open(p2, "wb") as fh:
            fh.write(gguf([("tokenizer.chat_template", T_STRING, PLAIN)]))
        ok(mt.gguf_tools_flag(p2) is False, "a plain gguf on disk is False")
        ok(mt.gguf_tools_flag(os.path.join(d, "nope.gguf")) is None,
           "a missing file is UNKNOWN, never False")


def test_mlx_reads_tokenizer_config_then_the_jinja_file():
    with tempfile.TemporaryDirectory() as d:
        # 1. tokenizer_config.json wins when it carries a template.
        with open(os.path.join(d, "tokenizer_config.json"), "w") as fh:
            json.dump({"chat_template": TOOLY, "model_max_length": 4096}, fh)
        ok(mt.mlx_tools_flag(d) is True, "tokenizer_config's chat_template is read")
        with open(os.path.join(d, "tokenizer_config.json"), "w") as fh:
            json.dump({"chat_template": PLAIN}, fh)
        ok(mt.mlx_tools_flag(d) is False, "a plain MLX template is False")
    with tempfile.TemporaryDirectory() as d:
        # 2. transformers >= 4.43 may export the template as its own file instead.
        with open(os.path.join(d, "tokenizer_config.json"), "w") as fh:
            json.dump({"model_max_length": 4096}, fh)
        with open(os.path.join(d, "chat_template.jinja"), "w") as fh:
            fh.write(TOOLY)
        ok(mt.mlx_tools_flag(d) is True, "the sibling chat_template.jinja is the fallback")
    with tempfile.TemporaryDirectory() as d:
        ok(mt.mlx_tools_flag(d) is None, "an MLX dir with neither file is UNKNOWN")
        with open(os.path.join(d, "tokenizer_config.json"), "w") as fh:
            fh.write("{ not json")
        ok(mt.mlx_tools_flag(d) is None, "a corrupt tokenizer_config is UNKNOWN")


def test_tools_for_entry_routes_by_format():
    with tempfile.TemporaryDirectory() as d:
        gp = os.path.join(d, "m.gguf")
        with open(gp, "wb") as fh:
            fh.write(gguf([("tokenizer.chat_template", T_STRING, TOOLY)]))
        mdir = os.path.join(d, "mlxmodel")
        os.makedirs(mdir)
        with open(os.path.join(mdir, "tokenizer_config.json"), "w") as fh:
            json.dump({"chat_template": TOOLY}, fh)

        ok(mt.tools_for_entry({"format": "gguf", "path": gp}) is True, "gguf routed")
        ok(mt.tools_for_entry({"format": "mlx", "path": mdir}) is True, "mlx dir routed")
        # An mlx entry whose path points at a FILE inside the model dir still resolves
        # (defensive: nothing writes that today, but a path is a path).
        ok(mt.tools_for_entry({"format": "mlx",
                               "path": os.path.join(mdir, "config.json")}) is True,
           "an mlx path pointing at a file falls back to its directory")
        # AUDIO entries are never probed — a TTS checkpoint has no tool surface and its
        # `path` shape is not one either reader understands.
        ok(mt.tools_for_entry({"kind": "audio", "format": "tts-mlx", "path": mdir})
           is None, "audio entries are skipped")
        # Totality.
        for junk in (None, [], "x", 3, {}, {"path": None}, {"path": ""},
                     {"format": "gguf", "path": 7}):
            ok(mt.tools_for_entry(junk) is None, f"junk entry {junk!r} → None")
        ok(mt.tools_for_entry({"format": "gguf", "path": os.path.join(d, "gone.gguf")})
           is None, "a vanished file → None")
        # No `format` at all defaults to gguf, which is what the registry has always
        # meant by an absent format.
        ok(mt.tools_for_entry({"path": gp}) is True, "a missing format defaults to gguf")


def test_annotate_tools_fills_only_what_is_missing():
    seen = []

    def probe(e):
        seen.append(e.get("id"))
        return True

    models = [
        {"id": "a"},                                   # no verdict → probed
        {"id": "b", "tools": False},                   # a real False → left alone
        {"id": "c", "tools": True},                    # a real True → left alone
        {"id": "d", "tools": None},                    # a null → re-probed
        {"id": "e", "kind": "audio"},                  # audio → never probed
        "not a dict",                                  # junk → never probed
    ]
    out = mt.annotate_tools(models, probe=probe)
    ok(out is models, "annotate_tools returns the same list (it edits in place)")
    ok(sorted(seen) == ["a", "d"], f"only the unknown entries are probed (got {seen})")
    ok(models[1]["tools"] is False, "an explicit False survives")
    ok(models[2]["tools"] is True, "an explicit True survives")
    ok("tools" not in models[4], "an audio entry never gains a tools key")
    ok(models[0]["tools"] is True and models[3]["tools"] is True, "the unknowns are filled")
    # Idempotent: a second pass probes nothing.
    seen.clear()
    mt.annotate_tools(models, probe=probe)
    ok(seen == [], "a second pass is a no-op")
    ok(mt.annotate_tools("nope") == "nope", "a non-list is returned untouched")


def test_seed_registry_loads_the_same_module():
    """ONE implementation, not a replicated one: scripts/seed_registry.py loads
    bridge/modeltools.py BY PATH (resolved from its own file, never the cwd) so a
    change here reaches the rescan without a second copy to keep in sync."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "scripts", "seed_registry.py")).read()
    ok('"bridge", "modeltools.py"' in src, "the path is built from bridge/modeltools.py")
    ok("os.path.dirname(os.path.abspath(__file__))" in src,
       "resolved from THIS FILE, not the cwd (the snapshot runs it from elsewhere)")
    ok("merged = annotate_tools(merged)" in src,
       "annotation runs over the MERGED list, so preserved 'download' entries get it too")
    ok(src.index("merged = annotate_tools(merged)") < src.index("write(REGISTRY_PATH"),
       "…and before the registry is written")
    # And it must degrade rather than explode when the module cannot be loaded.
    ok("MODELTOOLS = _load_modeltools()" in src and "if MODELTOOLS is None:" in src,
       "a failed load leaves `tools` absent instead of breaking the rescan")


def test_seed_registry_really_annotates(tmp_path=None):
    """End-to-end through the REAL script module: a temp registry with one gguf gains
    a tools verdict."""
    import importlib.util
    p = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "seed_registry.py")
    spec = importlib.util.spec_from_file_location("seed_registry_under_test", p)
    sr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sr)
    ok(sr.MODELTOOLS is not None, "seed_registry could load bridge/modeltools by path")
    with tempfile.TemporaryDirectory() as d:
        gp = os.path.join(d, "m.gguf")
        with open(gp, "wb") as fh:
            fh.write(gguf([("tokenizer.chat_template", T_STRING, TOOLY)]))
        models = [{"id": "m", "format": "gguf", "path": gp, "source": "download"},
                  {"id": "voice", "kind": "audio", "format": "tts-mlx", "path": d}]
        sr.annotate_tools(models)
        ok(models[0]["tools"] is True, "a download-sourced gguf gains its verdict")
        ok("tools" not in models[1], "the audio entry is untouched")


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"modeltools OK — {len(CHECKS)} checks")
