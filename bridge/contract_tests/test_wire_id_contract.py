"""WIRE-ID contract — ONE rule, one implementation, pinned equal forever (S33/F5).

THE DEFECT THIS CLOSES (adherence audit rank 6, docs/research/
2026-08-29-api-adherence-audit.md): the registry-id → wire-identifier rule was
written out TWICE — bridge/core/modelreg.py::wire_id and
bridge/core/modelid.py::wire_model_id — hand-synced, with modelreg's own docstring
saying so and nothing anywhere pinning them equal. Cost while they agree: zero.
Cost the day they drift: exactly the class both docstrings were written to kill —
an MLX server handed a registry id resolves it on HuggingFace, 404s, and answers
400; llama.cpp instead ignores the field and answers UNDER THE WRONG MODEL'S NAME,
which is the LIE class the doctrine ranks above crashes.

modelid now DELEGATES to modelreg (which is the one that must stay import-free:
three of its five consumers are standalone scripts that load it by path). This file
is the fence that keeps the delegation real:

  1. the two functions agree over a hostile corpus INCLUDING the live registry;
  2. modelid does not restate the format branch in its own body;
  3. modelreg is still stdlib-only, because moving the rule there is only safe
     while that stays true.

Static + pure. Run: pytest bridge/contract_tests/
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bridge.core import modelreg                                  # noqa: E402


def _wire_model_id():
    """modelid.wire_model_id WITHOUT importing bridge.core.modelid as a module —
    it pulls in appctx/procs (and an httpx client) at import time, which a contract
    test has no business doing. AST-extracted and exec'd against a namespace
    holding the real modelreg."""
    import ast
    src = (ROOT / "bridge" / "core" / "modelid.py").read_text()
    tree = ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
               and n.name == "wire_model_id"), None)
    assert fn is not None, "core/modelid.py no longer defines wire_model_id"
    ns = {"modelreg": modelreg}
    # `from .modelreg import wire_id` inside the function body — give the exec'd
    # copy the same name it would resolve at runtime.
    code = ast.unparse(fn).replace("from .modelreg import wire_id",
                                   "wire_id = modelreg.wire_id")
    exec(compile(code, "modelid", "exec"), ns)                    # noqa: S102
    return ns["wire_model_id"]


# The corpus: every shape the registry has ever held, plus the ones that broke it.
CORPUS = [
    {"id": "qwen-35b", "format": "gguf", "path": "/m/qwen.gguf"},
    {"id": "no-format", "path": "/m/x.gguf"},
    {"id": "mlx-one", "format": "mlx", "path": "/m/mlx-one"},
    {"id": "mlx-upper", "format": "MLX", "path": "/m/mlx-upper"},
    {"id": "mlx-spaced", "format": "  mlx  ", "path": "/m/mlx-spaced"},
    {"id": "mlx-nopath", "format": "mlx"},
    {"id": "mlx-emptypath", "format": "mlx", "path": "   "},
    {"id": "tts-thing", "format": "tts-kokoro", "path": "/m/tts"},
    {"id": "stt-thing", "format": "stt-whisper", "path": "/m/stt"},
    {"id": "weird-format", "format": 7, "path": "/m/w"},
    {"id": "path-none", "format": "mlx", "path": None},
]


def _live_registry() -> list:
    """The user's REAL registry when there is one — the corpus that actually
    matters, and the one a synthetic list cannot anticipate."""
    for p in (ROOT / "data" / "models.json",
              Path.home() / "Library" / "Application Support" / "MOT Deck"
              / "data" / "models.json"):
        try:
            rows = json.loads(p.read_text()).get("models") or []
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict) and r.get("id")]
        except Exception:                                         # noqa: BLE001
            continue
    return []


def test_the_two_wire_id_functions_agree_on_every_row():
    wire_model_id = _wire_model_id()
    rows = CORPUS + _live_registry()
    for m in rows:
        got = wire_model_id(m.get("id"), rows)
        want = modelreg.wire_id(m) or str(m.get("id") or "").strip()
        assert got == want, (
            f"THE WIRE-ID RULE HAS DRIFTED on {m.get('id')!r}: "
            f"modelid.wire_model_id said {got!r}, modelreg.wire_id said {want!r}. "
            "These must be one rule — an MLX server given a registry id answers "
            "400, and llama.cpp answers under the wrong model's name")


def test_the_lookup_half_still_behaves():
    """The half modelid keeps for itself: id → row, and the honest fallbacks."""
    wire_model_id = _wire_model_id()
    assert wire_model_id("", CORPUS) == ""
    assert wire_model_id(None, CORPUS) == ""
    assert wire_model_id("  ", CORPUS) == ""
    # An id that is not in the registry is returned UNCHANGED — the safe fallback,
    # and the reason a stale pin degrades to a mislabel rather than to an exception.
    assert wire_model_id("never-heard-of-it", CORPUS) == "never-heard-of-it"
    assert wire_model_id("qwen-35b", []) == "qwen-35b"
    assert wire_model_id("mlx-one", CORPUS) == "/m/mlx-one"
    assert wire_model_id("mlx-nopath", CORPUS) == "mlx-nopath"


def test_modelid_does_not_restate_the_rule():
    """The delegation must stay a delegation. A copy-paste back into modelid would
    pass the equality test above on the day it was written and rot afterwards —
    which is precisely the history this contract exists to end."""
    src = (ROOT / "bridge" / "core" / "modelid.py").read_text()
    body = src[src.index("def wire_model_id"):]
    body = body[:body.index("def display_model_id")]
    assert "from .modelreg import wire_id" in body, (
        "core/modelid.py::wire_model_id no longer delegates to modelreg.wire_id — "
        "the rule is duplicated again (adherence audit rank 6)")
    assert '"mlx"' not in body, (
        "core/modelid.py::wire_model_id names the mlx format itself again: the "
        "format branch belongs to modelreg.wire_id and to nowhere else")


def test_modelreg_stays_importable_by_the_standalone_seeders():
    """Moving the rule INTO modelreg is only safe while modelreg keeps its own
    hard rule: stdlib only, no intra-package imports. Three seeders load it BY
    PATH under other interpreters (one under Odysseus's venv); an import of
    bridge.core.* here breaks all of them at once, silently, at seed time."""
    import ast
    src = (ROOT / "bridge" / "core" / "modelreg.py").read_text()
    # AST, not grep: the module's own docstring EXPLAINS the rule ("an import from
    # bridge.core.* here breaks all of them"), so a substring test reads the prose.
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert node.level == 0 and not mod.startswith("bridge"), (
                f"core/modelreg.py now imports {'.' * node.level}{mod} — it is "
                "loaded BY PATH by scripts/seed_registry.py, seed_odysseus_jan.py "
                "and seed_opencode_config.py (one under Odysseus's own venv), "
                "which cannot import the bridge package")
        elif isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.startswith("bridge"), (
                    f"core/modelreg.py now imports {a.name} — see above")
    assert "def wire_id" in src, (
        "modelreg.wire_id is gone — it is now the ONLY copy of the wire-id rule "
        "and core/modelid.py delegates to it")
