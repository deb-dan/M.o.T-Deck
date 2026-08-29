"""ODYSSEUS SEED contract — pin-bump gate for scripts/seed_odysseus_jan.py.

Our side of this seam is bridge/tests/test_odysseus_seed.py. THIS file pins the four
UPSTREAM facts the seed now DEPENDS ON, none of which Odysseus promises to keep:

  1. `ModelEndpoint.pinned_models` exists and means "admin-pinned model IDs (manual,
     MAY NOT APPEAR IN /v1/models)". That column is the ONLY reason Odysseus's own
     picker can be populated from OUR registry in isolation — with the runner down,
     on a fresh DB, before any probe has ever run. If it goes, full-registry seeding
     goes with it and the picker is back to whatever a live /v1/models call returns.
  2. The picker MERGES it: `_visible_models` = cached ∪ pinned − hidden, and a LOCAL
     endpoint takes that branch (`_picker_models_for_endpoint`) rather than the
     API-provider allow-list branch. Executed here, not grepped.
  3. `hidden_models` still WINS over pinned in that merge — the seed never writes
     hidden_models precisely because that is how a human hides a model, and their
     choice has to keep beating our re-seeded list.
  4. A row whose primary key is `local-jan` can only be OURS: Odysseus's own
     "add endpoint" form mints a RANDOM id, and it DEDUPES BY base_url rather than
     inserting a second row for the same address. Both facts are what let the seed
     update a row at all (ownership proof) and adopt instead of duplicate.

Method: the pure model-list helpers are ast-extracted from the vendored source and
EXECUTED (no fastapi, no DB), the way bridge/tests/test_ody_vlshim.py does it — a
behavioural pin survives a rename that a grep would miss, and vice versa, so both are
here. Skips cleanly when vendor/odysseus is absent (repo checkout without vendors).

Run: pytest bridge/contract_tests/
"""
import ast
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
ODY = ROOT / "vendor" / "odysseus"
MODEL_ROUTES = ODY / "routes" / "model_routes.py"
DATABASE = ODY / "core" / "database.py"

# The seed's own constants, spelled once here so a drift in either direction shows up.
OUR_PK = "local-jan"
OUR_BASE = "http://127.0.0.1:6767/v1"


def _read(p: Path) -> str:
    return p.read_text(errors="replace")


def _extract(src: str, names, consts=()):
    """The pure helpers, executed out of the vendored file — no imports of it."""
    tree = ast.parse(src)
    body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    missing = set(names) - {n.name for n in body}
    assert not missing, (
        f"Odysseus renamed or removed these picker helpers: {sorted(missing)} — the "
        f"seed's full-registry pinning is built on their behaviour")
    ns = {"json": json, "re": re, "urlparse": urlparse, "ipaddress": ipaddress,
          "Any": object, "List": list, "Optional": object}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) \
                and n.targets[0].id in consts:
            ns[n.targets[0].id] = eval(  # noqa: S307 — vendored literal, not input
                compile(ast.Expression(n.value), "consts", "eval"), dict(ns))
    for c in consts:
        assert c in ns, f"constant {c} vanished from Odysseus's model routes"
    exec(compile(ast.Module(body=body, type_ignores=[]), "ody", "exec"), ns)
    return ns


HELPERS = ("_normalize_model_ids", "_merge_model_ids", "_visible_models",
           "_is_mlx_deepseek_v4_repo_id", "_is_mlx_deepseek_v4_shim_id",
           "_filter_mlx_deepseek_v4_repo_when_shimmed", "_has_explicit_pinned_models",
           "_picker_models_for_endpoint", "_legacy_visible_api_models",
           "_picker_requires_pinning",
           "_cached_model_ids", "_parse_model_list", "_classify_endpoint",
           "_normalize_endpoint_kind", "_local_ip_literal")
CONSTS = ("_LOCAL_HOSTS", "_PRIVATE_NETWORKS", "_TAILSCALE_CGNAT", "_ENDPOINT_KINDS")


class _Row:
    def __init__(self, **kw):
        self.cached_models = kw.get("cached")
        self.hidden_models = kw.get("hidden")
        self.pinned_models = kw.get("pinned")
        self.base_url = kw.get("base_url", OUR_BASE)
        self.endpoint_kind = kw.get("kind", "local")


# ── 1. the column, and what its own docstring says it is for ────────────────
def test_model_endpoint_still_carries_the_admin_pin_column():
    if not DATABASE.exists():
        return
    src = _read(DATABASE)
    assert "class ModelEndpoint" in src
    assert "pinned_models = Column(Text" in src, (
        "ModelEndpoint.pinned_models is GONE — scripts/seed_odysseus_jan.py writes the "
        "whole model registry there so Odysseus's picker holds facts, not probe "
        "results. Without it, isolation-mode model selection has no config-resident "
        "home in Odysseus's schema at all.")
    assert "may not appear in /v1/models" in src, (
        "the pinned_models column no longer promises to survive a model the live "
        "endpoint does not list — that promise IS the feature we rely on")
    for col in ("cached_models = Column(Text", "hidden_models = Column(Text",
                "is_enabled = Column(Boolean", "api_key = Column(EncryptedText",
                "endpoint_kind = Column(String", "model_refresh_mode = Column(String",
                "supports_tools = Column(Boolean", "owner = Column(String"):
        assert col in src, f"ModelEndpoint lost a column the seed writes: {col}"


# ── 2. the merge, EXECUTED ──────────────────────────────────────────────────
def test_pinned_models_reach_the_picker_without_any_probe():
    if not MODEL_ROUTES.exists():
        return
    ns = _extract(_read(MODEL_ROUTES), HELPERS, CONSTS)
    # A brand-new endpoint: nothing cached (no probe has ever run), our registry pinned.
    ours = ["big-27b", "small-4b", "/models/mlx-9b"]
    visible = ns["_visible_models"](None, None, json.dumps(ours))
    assert visible == ours, (
        "pinned models no longer show without a cached list — the seed's whole "
        "isolation guarantee (picker populated with the runner DOWN) rests on this")
    # …and the local-endpoint picker takes the merge branch, not the allow-list branch.
    row = _Row(cached=None, pinned=json.dumps(ours), kind="local")
    models, _pinned = ns["_picker_models_for_endpoint"](row, OUR_BASE, "local")
    assert models == ours
    assert ns["_classify_endpoint"](OUR_BASE, "local") == "local", (
        "our endpoint must classify LOCAL — the 'api' branch turns pinned_models into "
        "an exclusive allow-list with different semantics")


def test_the_merge_is_cached_union_pinned():
    if not MODEL_ROUTES.exists():
        return
    ns = _extract(_read(MODEL_ROUTES), HELPERS, CONSTS)
    got = ns["_visible_models"](json.dumps(["live-a"]), None, json.dumps(["seeded-b"]))
    assert got == ["live-a", "seeded-b"], (
        "a live probe must ADD to our pinned list, not replace it")


# ── 3. the human's hide still wins ──────────────────────────────────────────
def test_hidden_beats_pinned():
    if not MODEL_ROUTES.exists():
        return
    ns = _extract(_read(MODEL_ROUTES), HELPERS, CONSTS)
    got = ns["_visible_models"](None, json.dumps(["small-4b"]),
                                json.dumps(["big-27b", "small-4b"]))
    assert got == ["big-27b"], (
        "hidden no longer beats pinned — the seed would start un-hiding models a human "
        "deliberately hid, which is the U11 class of bug all over again")


# ── 4. why `local-jan` is provably ours, and why we adopt instead of duplicate ──
def test_user_added_endpoints_get_a_random_id_not_a_readable_one():
    if not MODEL_ROUTES.exists():
        return
    src = _read(MODEL_ROUTES)
    assert re.search(r"uuid\.uuid4\(\)[^\n]*\[:8\]", src), (
        "Odysseus's own add-endpoint form no longer mints a random 8-char id. The seed "
        "treats a row whose PK is 'local-jan' as PROOF that it created it (that is what "
        "licenses updating the row's fields at all) — if users can now choose ids, that "
        "proof is gone and the ownership rules need rewriting.")


def test_odysseus_still_dedupes_endpoints_by_base_url():
    if not MODEL_ROUTES.exists():
        return
    src = _read(MODEL_ROUTES)
    assert "Dedupe" in src and "same base_url already exists" in src, (
        "the create route no longer dedupes by base_url — the seed adopts a user-made "
        "row at our runner's address for the same reason, and a second row for one "
        "address is exactly the mess both behaviours exist to prevent")


# ── 4b. WHY offering 16 models against a 1-model runner is not a lie ────────
def test_odysseus_still_labels_a_substituted_model_on_the_message():
    """MEASURED 2026-08-29: llama.cpp IGNORES the request's `model` field and answers
    with whatever is loaded (a bogus id returned a normal completion stamped with the
    resident model). Seeding the whole registry into the picker is therefore only
    honest because ODYSSEUS ITSELF shows the substitution: it reads the served model
    back off the response and renders `requested -> actual` on the message header, with
    the full pair in the title. If that goes, the picker starts silently lying about
    which model answered — the LIE-TO-USER class — and the seeded list needs rethinking.
    """
    if not ODY.exists():
        return
    renderer = _read(ODY / "static" / "js" / "chatRenderer.js")
    assert "export function modelRouteLabel" in renderer
    assert "shortModel(requested) + ' -> ' + shortModel(actual)" in renderer, (
        "Odysseus no longer labels a substituted model as `requested -> actual`")
    chat = _read(ODY / "static" / "js" / "chat.js")
    assert "_setRoleModelLabel" in chat and "roleEl.title = req + ' -> ' + actual" in chat
    # and the server still reports BOTH halves on the metrics event we saw live
    routes = _read(ODY / "routes" / "chat_routes.py")
    assert "requested_model" in routes, (
        "the stream no longer carries requested_model — the UI has nothing to compare")


# ── 5. the settings keys the seed writes ────────────────────────────────────
def test_global_settings_still_carry_the_default_chat_keys():
    if not ODY.exists():
        return
    src = _read(ODY / "src" / "settings.py")
    assert "def load_settings" in src and "def save_settings" in src
    consts = _read(ODY / "src" / "settings.py") + _read(ODY / "src" / "constants.py")
    assert "SETTINGS_FILE" in consts
    routes = _read(MODEL_ROUTES)
    for key in ("default_endpoint_id", "default_model"):
        assert key in routes, (
            f"Odysseus stopped reading {key} — the seed sets it (only when absent or "
            f"dangling) so a fresh login can chat with no configuration")


def test_a_disabled_endpoint_is_still_a_reason_to_reassign_the_default():
    if not MODEL_ROUTES.exists():
        return
    src = _read(MODEL_ROUTES)
    assert "_default_endpoint_needs_assignment" in src, (
        "Odysseus's own dangling-default repair is gone; the seed's settings_plan "
        "mirrors its rules and would be the only thing left doing it")
