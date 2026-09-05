"""OUR side of the Hermes named-provider seam — scripts/seed_hermes_provider.py.

(UPSTREAM's side is bridge/contract_tests/test_hermes_provider_contract.py.)

Isolation mode, S-ISO-3: Hermes's OWN "Set main model" picker must show a
"MOT Deck (local)" row carrying our whole registry, with the runner up OR down,
instead of the anonymous `custom` row whose model list is a live probe.

Every test here is a WALKED JOURNEY pinned as a test — the seeding is run for real
against a temp config file, exactly as start_component.sh runs it:

  first Start · a second Start (idempotent, so the yaml round-trip is paid once)
  · the user renames the row in Hermes's own Config page and restarts (the edit
  survives AND the main slot follows it) · the user adds a model / an api_mode /
  a key_env by hand · Hermes's own auto-registered row is ADOPTED, not duplicated
  · the config is unparseable or malformed (refuse, never half-write) · the
  registry is empty (the row still names the served model).

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_hermes_provider_seed.py -q
"""
import json
import os
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SEED = os.path.join(ROOT, "scripts", "seed_hermes_provider.py")
START = open(os.path.join(ROOT, "scripts", "start_component.sh"),
             encoding="utf-8", errors="replace").read()

BASE = "http://127.0.0.1:6767/v1"
KEY = "harness-local"
WIRE = "gemma-4-31B-it-uncensored-biproj-q4_k_m"

# ── S29: the enumeration rule now includes "the file is still on disk" ───────
# So the MLX fixture points at a REAL directory. Before this slice it named a path that
# has never existed on any machine and the test passed — which is precisely how a
# seeder that offered deleted models stayed green.
_TMP = tempfile.mkdtemp(prefix="hermes-seed-fixture-")
MLX_ONE = os.path.join(_TMP, "mlx-one")
os.makedirs(MLX_ONE, exist_ok=True)
open(os.path.join(MLX_ONE, "config.json"), "w").write("{}")
open(os.path.join(MLX_ONE, "model.safetensors"), "wb").write(b"x")

REGISTRY = {"models": [
    {"id": "chat-a", "format": "gguf", "ctx": 32768},
    {"id": "chat-b", "format": "gguf"},
    {"id": "mlx-one", "format": "mlx", "path": MLX_ONE, "ctx": 8192},
    {"id": "whisper-x", "format": "stt-mlx", "kind": "audio"},
    {"id": "hidden-one", "format": "gguf", "hidden": True},
]}


# ── harness ──────────────────────────────────────────────────────────────────
def _root_with_registry(tmp_path, registry=REGISTRY):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True, exist_ok=True)
    if registry is not None:
        (root / "data" / "models.json").write_text(json.dumps(registry))
    return root


def _seed(cfg_path, root, model=WIRE, base=BASE, key=KEY, ctx="65536"):
    env = dict(os.environ, HERMES_CFG=str(cfg_path), BASE_URL=base, KEY=key,
               MODEL=model, CTXLEN=ctx, HARNESS_ROOT=str(root))
    p = subprocess.run([sys.executable, SEED], capture_output=True, text=True, env=env)
    assert p.returncode == 0, p.stderr
    return p.stdout


def _cfg(path):
    return yaml.safe_load(open(path, encoding="utf-8").read()) or {}


def _entry(path):
    entries = _cfg(path).get("custom_providers") or []
    ours = [e for e in entries
            if str(e.get("base_url", "")).rstrip("/") == BASE.rstrip("/")]
    assert len(ours) == 1, (
        "expected EXACTLY ONE entry for the runner endpoint, found %d — the "
        "double-row trap" % len(ours))
    return ours[0]


def _slugfile(root):
    return json.load(open(os.path.join(str(root), "data", "hermes-provider.json")))


# ── journey 1: first-ever Start ──────────────────────────────────────────────
def test_first_start_writes_one_named_row_with_the_whole_registry(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  default: old\n  provider: custom\n"
                   "  base_url: %s\n" % BASE)
    out = _seed(cfg, root)
    e = _entry(cfg)
    assert e["name"] == "MOT Deck (local)"
    assert e["api_key"] == KEY
    # the catalog: chat models only, keyed by the WIRE id (MLX = its path)
    assert set(e["models"]) == {"chat-a", "chat-b", MLX_ONE, WIRE}, (
        "audio and hidden registry rows must not reach a chat picker, and the "
        "model the runner is serving must always be offered")
    assert e["models"]["chat-a"]["context_length"] == 32768
    assert e["models"][MLX_ONE]["context_length"] == 8192
    # config-resident, not probed — this is what keeps the picker populated when
    # the runner is down (and stops it collapsing to the one served model when up)
    assert e["discover_models"] is False
    assert '"MOT Deck (local)" -> %s · 4 model(s)' % BASE in out, (
        "the verdict line must name the row, the endpoint and the model COUNT — "
        "that line is the only thing a human reads at Start time")


def test_first_start_decides_the_slug_the_start_script_writes(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    assert _slugfile(root)["slug"] == "custom:mot-deck-(local)"
    assert "provider" in _slugfile(root)["wrote"], (
        "the verdict file must say which managed values this Start actually wrote")


def test_first_start_migrates_the_anonymous_main_slot_to_the_named_slug(tmp_path):
    """THE MIGRATION. Bootstrap (no marker): the main slot was re-asserted by every
    Start until now, so it IS ours — it is refreshed once, and that records the
    marker that protects the user's edits from here on."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  default: old-model\n  provider: custom\n"
                   "  base_url: %s\n  api_key: k\n" % BASE)
    _seed(cfg, root)
    m = _cfg(cfg)["model"]
    assert m["provider"] == "custom:mot-deck-(local)"
    assert m["default"] == WIRE and m["base_url"] == BASE
    assert m["api_key"] == KEY and m["context_length"] == 65536
    marker = json.load(open(os.path.join(str(root), "data", "hermes_seed_state.json")))
    assert marker["provider"] == "custom:mot-deck-(local)" and marker["default"] == WIRE


# ── journey 2: every later Start ─────────────────────────────────────────────
def test_second_start_does_not_rewrite_the_file(tmp_path):
    """Strict idempotency is what makes the yaml round-trip's cost (comments, key
    order) a ONE-TIME price instead of one paid on every restart."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    first = cfg.read_text()
    mtime = os.stat(cfg).st_mtime_ns
    out = _seed(cfg, root)
    assert cfg.read_text() == first
    assert os.stat(cfg).st_mtime_ns == mtime, "the file was rewritten with no change"
    assert "already current" in out
    assert _slugfile(root)["changed"] is False


def test_a_comment_the_user_added_survives_when_nothing_changes(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    cfg.write_text("# Debi's note\n" + cfg.read_text())
    _seed(cfg, root)
    assert "# Debi's note" in cfg.read_text()


# ── journey 3: the user edits the row in Hermes's own Config page ────────────
def test_a_rename_survives_a_restart_and_the_main_slot_follows_it(tmp_path):
    """THE never-clobber walk. Identity is the base_url, never the name — so a
    renamed row keeps its name, and the dangling `model.provider` WE wrote is
    repaired to the new slug in the same pass (otherwise the rename silently breaks
    every new chat)."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["custom_providers"][0]["name"] = "Debi's rig"
    data["model"]["provider"] = "custom:mot-deck-(local)"     # what the shell wrote
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    out = _seed(cfg, root)
    assert _entry(cfg)["name"] == "Debi's rig", "the rename was clobbered"
    assert _slugfile(root)["slug"] == "custom:debi's-rig"
    assert _cfg(cfg)["model"]["provider"] == "custom:debi's-rig", (
        "the main slot must follow the rename — the old slug now resolves to nothing")
    assert "kept your name" in out


def test_hand_added_models_and_settings_are_preserved(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["custom_providers"][0]["models"]["my-own-model"] = {"context_length": 4096}
    data["custom_providers"][0]["api_mode"] = "chat_completions"
    data["custom_providers"][0]["extra_headers"] = {"X-Tenant": "debi"}
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    e = _entry(cfg)
    assert e["models"]["my-own-model"] == {"context_length": 4096}
    assert e["api_mode"] == "chat_completions"
    assert e["extra_headers"] == {"X-Tenant": "debi"}
    assert "chat-a" in e["models"], "our own registry rows must still be refreshed"


def test_a_model_we_seeded_that_left_the_registry_is_dropped(tmp_path):
    """FOUND LIVE: the row still offered a 27B whose file Debi had deleted (it was gone
    from data/models.json — ledger U15) plus six other ids from older registries,
    because a union-merge never shrinks. A picker promising models MOT Deck does not
    have is exactly the lie this slice removes. Two Starts by design: the first records
    what we wrote, the second can prove the id was ours before dropping it."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    assert "chat-a" in _entry(cfg)["models"]
    smaller = {"models": [m for m in REGISTRY["models"] if m["id"] != "chat-a"]}
    (root / "data" / "models.json").write_text(json.dumps(smaller))
    out = _seed(cfg, root)
    assert "chat-a" not in _entry(cfg)["models"], (
        "a model we seeded is still offered after the registry dropped it")
    assert "dropped 1 model(s) we seeded" in out and "chat-a" in out
    assert "chat-b" in _entry(cfg)["models"]


def test_a_model_the_user_added_is_never_pruned(tmp_path):
    """The other side: only ids the MARKER proves we wrote are droppable. Anything the
    user (or an older Hermes probe) put in the row stays, registry or no registry."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["custom_providers"][0]["models"]["their-own-model"] = {"context_length": 4096}
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    _seed(cfg, root)
    assert "their-own-model" in _entry(cfg)["models"]
    marker = json.load(open(os.path.join(str(root), "data", "hermes_seed_state.json")))
    assert "their-own-model" not in marker["models"], (
        "recording it as ours would prune it the moment the registry changed")


def test_the_first_marker_without_a_catalog_list_is_reconciled_once(tmp_path):
    """MEASURED on the live config: the marker written before the catalog was tracked
    left 21 models against a 14-model registry, and none of them were provably ours, so
    the dead ids would have sat in the picker for ever. On a row carrying OUR
    fingerprint (`discover_models: false`) that first marker is reconciled once."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    mpath = os.path.join(str(root), "data", "hermes_seed_state.json")
    marker = json.load(open(mpath))
    marker.pop("models")                                # the pre-change marker shape
    json.dump(marker, open(mpath, "w"))
    data = _cfg(cfg)
    data["custom_providers"][0]["models"]["gone-from-the-registry"] = {}
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    out = _seed(cfg, root)
    assert "gone-from-the-registry" not in _entry(cfg)["models"]
    assert "dropped 1 model(s) we seeded" in out
    # and it really is one-shot: with no marker at all, nothing is inferred
    data = _cfg(cfg)
    data["custom_providers"][0]["models"]["theirs"] = {}
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    os.remove(mpath)
    _seed(cfg, root)
    assert "theirs" in _entry(cfg)["models"]


def test_the_served_model_is_offered_even_when_the_registry_dropped_it(tmp_path):
    """The prune must never empty the one row that has to answer: the model the runner
    is actually serving is always offered, registry or not."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root, model="chat-a")
    (root / "data" / "models.json").write_text(json.dumps({"models": []}))
    _seed(cfg, root, model="chat-a")
    assert "chat-a" in _entry(cfg)["models"]


def test_the_model_the_user_picked_is_never_pruned_from_the_row(tmp_path):
    """WALKED LIVE: the prune dropped the model picked inside Hermes (its id had left
    the registry), so the main slot pointed at a model its own row no longer listed —
    Hermes rendered it anyway and the picker count disagreed with the config. Honouring
    a pick means keeping it offered."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"]["default"] = "chat-a"                 # the user's pick
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    smaller = {"models": [m for m in REGISTRY["models"] if m["id"] != "chat-a"]}
    (root / "data" / "models.json").write_text(json.dumps(smaller))
    _seed(cfg, root)
    assert _cfg(cfg)["model"]["default"] == "chat-a"
    assert "chat-a" in _entry(cfg)["models"], "the picked model vanished from its row"
    # …and the id we put back is OURS: once the pick moves on and the registry still
    # does not know it, it is dropped instead of becoming permanent junk (WALKED: the
    # re-offer rule was adding ids the prune could never touch).
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    assert "chat-a" not in _entry(cfg)["models"]
    # …and a pick made through ANOTHER provider is not smuggled into our catalog
    data = _cfg(cfg)
    data["model"]["provider"] = "openrouter"
    data["model"]["default"] = "anthropic/claude-opus-4.6"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    assert "anthropic/claude-opus-4.6" not in _entry(cfg)["models"]


def test_key_env_outranks_our_inline_key(tmp_path):
    """A key_env is a deliberate choice about where the secret lives; an inline
    api_key would silently outrank it in upstream's candidate order."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["custom_providers"][0].pop("api_key", None)
    data["custom_providers"][0]["key_env"] = "MY_RUNNER_KEY"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    out = _seed(cfg, root)
    e = _entry(cfg)
    assert "api_key" not in e and e["key_env"] == "MY_RUNNER_KEY"
    assert "key_env kept" in out


def test_a_row_hermes_auto_registered_is_adopted_not_duplicated(tmp_path):
    """POST /api/model/set registers a bare custom endpoint itself, naming it
    `Local (127.0.0.1:6767)`. That is a DEFAULT name, so we adopt the row (one
    endpoint, one row) instead of adding ours beside it."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "model": {"provider": "custom", "base_url": BASE},
        "custom_providers": [{"name": "Local (127.0.0.1:6767)", "base_url": BASE,
                              "api_key": KEY, "model": WIRE}],
    }, sort_keys=False))
    _seed(cfg, root)
    e = _entry(cfg)                       # asserts there is exactly ONE
    assert e["name"] == "MOT Deck (local)"
    assert e["model"] == WIRE, "keys we do not manage must survive adoption"


def test_a_probe_written_model_list_becomes_our_dict_catalog(tmp_path):
    """Upstream's own discovery cache writes `models:` as a LIST, which it then reads
    back as an allowlist — the self-pinning trap. Our dict catalog replaces it while
    keeping every id it had."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump({
        "model": {"provider": "custom", "base_url": BASE},
        "custom_providers": [{"name": "MOT Deck (local)", "base_url": BASE,
                              "models": ["probed-1", "probed-2"]}],
    }, sort_keys=False))
    _seed(cfg, root)
    models = _entry(cfg)["models"]
    assert isinstance(models, dict)
    assert {"probed-1", "probed-2", "chat-a"} <= set(models)


# ── journey 3b: the main slot, seeded and then the user's (ledger U12) ───────
def test_a_model_picked_inside_hermes_survives_the_next_start(tmp_path):
    """U12(a), the whole point: Start used to re-assert model.* every time, so a
    model chosen in Hermes's own SET MAIN MODEL was silently reset by the next
    restart. Now it stays — and the log says which model the deck actually has
    loaded, because llama.cpp answers from the resident one regardless."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)                                   # bootstrap Start
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"                # the user's pick, in Hermes
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    out = _seed(cfg, root)                             # the next Start
    assert _cfg(cfg)["model"]["default"] == "chat-b", "the user's pick was clobbered"
    assert "honoured your model (chat-b)" in out
    assert "MOT Deck has %r loaded" % WIRE in out, (
        "silently keeping the pick would hide that another model answers the turn")


def test_the_marker_never_records_a_value_we_only_honoured(tmp_path):
    """The subtle half: recording an honoured value would make it 'ours' next run
    and clobber it one Start later. Three Starts, still the user's."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    _seed(cfg, root)
    assert _cfg(cfg)["model"]["default"] == "chat-b"
    marker = json.load(open(os.path.join(str(root), "data", "hermes_seed_state.json")))
    assert marker["default"] == WIRE, "the marker recorded a value we never wrote"


def test_a_no_op_start_still_records_the_marker(tmp_path):
    """WALKED BUG (found live, on the real dashboard). The marker used to record only
    the keys CHANGED that run, so a Start where everything already matched wrote an
    EMPTY marker — bootstrap for ever, and bootstrap treats the block as ours. The
    model picked in Hermes's picker was then reset by the very next restart: exactly
    the U12 defect this slice exists to kill."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    out = _seed(cfg, root)                              # the no-op Start
    assert "already current" in out
    marker = json.load(open(os.path.join(str(root), "data", "hermes_seed_state.json")))
    assert marker.get("default") == WIRE and marker.get("provider")
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"                 # now the user picks one
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    assert _cfg(cfg)["model"]["default"] == "chat-b"


def test_a_model_we_wrote_is_refreshed_when_the_deck_loads_another(tmp_path):
    """The other side of the same rule: an UNTOUCHED main slot still follows the
    model MOT Deck has loaded — otherwise 'seed, never enforce' becomes 'freeze'."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    _seed(cfg, root, model="chat-a")                   # the deck loaded another model
    assert _cfg(cfg)["model"]["default"] == "chat-a"


def test_a_provider_the_user_chose_elsewhere_is_honoured(tmp_path):
    """A main slot pointing at a real other provider is a decision. Start used to
    overwrite it with `custom` on every restart."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"]["provider"] = "openrouter"
    data["model"]["default"] = "anthropic/claude-opus-4.6"
    data["model"]["base_url"] = "https://openrouter.ai/api/v1"
    data["model"]["api_key"] = "sk-or-theirs"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    out = _seed(cfg, root)
    m = _cfg(cfg)["model"]
    assert m["provider"] == "openrouter" and m["base_url"] == "https://openrouter.ai/api/v1"
    assert m["api_key"] == "sk-or-theirs"
    assert "honoured your choice (openrouter)" in out
    # …and the provider ROW is still seeded, so the picker can offer the way back
    assert _entry(cfg)["name"] == "MOT Deck (local)"


def test_a_deleted_marker_does_not_hand_the_users_edits_back_to_us(tmp_path):
    """Bootstrap's benefit of the doubt is bounded by SHAPE: with the marker gone, a
    provider/base_url that is plainly not ours is still honoured."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"]["provider"] = "openrouter"
    data["model"]["base_url"] = "https://openrouter.ai/api/v1"
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    os.remove(os.path.join(str(root), "data", "hermes_seed_state.json"))
    _seed(cfg, root)
    m = _cfg(cfg)["model"]
    assert m["provider"] == "openrouter"
    assert m["base_url"] == "https://openrouter.ai/api/v1"


def test_a_deleted_marker_does_not_hand_back_the_users_MODEL_either(tmp_path):
    """The hole the bound closes (found reviewing the inherited planner): bootstrap
    treated `default`/`api_key`/`context_length` as ours whenever the marker was
    missing — so `rm data/hermes_seed_state.json` (a tidy-up, a fresh snapshot's data
    dir) put U12 straight back: the model picked inside Hermes was clobbered by the
    next Start. The config's own evidence now outranks the missing marker."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)                                    # the real bootstrap Start
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"                 # the user's pick, in Hermes
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    os.remove(os.path.join(str(root), "data", "hermes_seed_state.json"))
    out = _seed(cfg, root)
    assert _cfg(cfg)["model"]["default"] == "chat-b", (
        "a deleted marker re-opened bootstrap and clobbered the user's model")
    assert "honoured your model (chat-b)" in out


def test_the_evidence_is_the_row_itself_not_only_the_slot(tmp_path):
    """Second evidence source: our row carries `discover_models: false`, which none of
    Hermes's own writers emit. So even a user who ALSO repointed the main slot at
    another provider and back keeps their model across a marker loss."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"]["default"] = "chat-b"
    data["model"]["provider"] = "custom"                # back to the anonymous shape
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    os.remove(os.path.join(str(root), "data", "hermes_seed_state.json"))
    _seed(cfg, root)
    assert _cfg(cfg)["model"]["default"] == "chat-b"
    # …and the slot is still migrated to the named slug (that half is provably ours)
    assert _cfg(cfg)["model"]["provider"] == "custom:mot-deck-(local)"


def test_a_pre_slice_config_still_gets_its_one_bootstrap(tmp_path):
    """The bound must not break the migration it exists beside: a config written by the
    OLD text patcher (anonymous shape, no row of ours, no marker) is still refreshed
    once — otherwise every existing install would freeze on its old model."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  default: something-old\n  provider: custom\n"
                   "  base_url: %s\n  api_key: %s\n" % (BASE, KEY))
    _seed(cfg, root)
    m = _cfg(cfg)["model"]
    assert m["default"] == WIRE and m["provider"] == "custom:mot-deck-(local)"


def test_context_length_deleted_by_hermes_is_re_seeded(tmp_path):
    """Hermes's own picker pops model.context_length on every switch — an absent key
    is create-if-absent, not a user decision."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    data = _cfg(cfg)
    data["model"].pop("context_length")
    open(cfg, "w").write(yaml.safe_dump(data, sort_keys=False))
    _seed(cfg, root)
    assert _cfg(cfg)["model"]["context_length"] == 65536


def test_the_planner_is_pure_and_covers_the_matrix():
    """The never-clobber matrix, exercised directly (no file, no Hermes)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import importlib
    seed = importlib.import_module("seed_hermes_provider")
    want = {"default": "m2", "provider": "custom:mot-deck-(local)",
            "base_url": BASE, "api_key": KEY, "context_length": 65536}
    aliases = seed.custom_provider_aliases("MOT Deck (local)")
    # ours + stale -> written; the user's -> honoured with a note
    ch, notes = seed.model_block_plan(
        {"default": "m1", "provider": "custom", "base_url": BASE, "api_key": KEY,
         "context_length": 65536},
        {"default": "m1"}, want, aliases)
    assert ch["default"] == "m2" and ch["provider"] == want["provider"] and not notes
    ch, notes = seed.model_block_plan(
        {"default": "theirs", "provider": "custom:mot-deck-(local)"},
        {"default": "m1"}, want, aliases)
    assert "default" not in ch and any("honoured" in n for n in notes)
    # a dangling custom: slug is OUR pointer and is repaired
    ch, notes = seed.model_block_plan(
        {"provider": "custom:old-name"}, {"provider": "custom:old-name"},
        want, aliases)
    assert ch["provider"] == want["provider"]
    # the marker records what is OURS afterwards, never a value we honoured
    assert seed.next_marker({"default": "m1"},
                            {"default": "theirs", "provider": want["provider"]},
                            want) == {"default": "m1",
                                      "provider": want["provider"]}


# ── journey 4: the error paths — refuse, never half-write ────────────────────
def test_an_unparseable_config_is_never_rewritten(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model: [broken\n")
    out = _seed(cfg, root)
    assert cfg.read_text() == "model: [broken\n"
    assert "could not parse" in out and "NOT seeded" in out


def test_a_dict_shaped_custom_providers_is_left_for_the_user_to_fix(tmp_path):
    """The documented user mistake (missing '-' on each entry). Overwriting it would
    delete configuration that is one dash away from working."""
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("custom_providers:\n  name: oops\n")
    out = _seed(cfg, root)
    assert _cfg(cfg)["custom_providers"] == {"name": "oops"}
    assert "not a list" in out


def test_no_endpoint_means_no_write(tmp_path):
    root = _root_with_registry(tmp_path)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model: {}\n")
    out = _seed(cfg, root, base="")
    assert _cfg(cfg) == {"model": {}}
    assert "NOT seeded" in out


def test_an_unreadable_registry_still_offers_the_served_model(tmp_path):
    """Graceful absence: a row with no models is a row that cannot explain itself."""
    root = _root_with_registry(tmp_path, registry=None)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model:\n  provider: custom\n  base_url: %s\n" % BASE)
    _seed(cfg, root)
    assert list(_entry(cfg)["models"]) == [WIRE]


# ── the wiring in start_component.sh ─────────────────────────────────────────
def _hermes_branch() -> str:
    i = START.index("\n  hermes)")
    j = START.index("\n  *) echo \"usage:", i)
    return START[i:j]


def test_start_runs_the_seed_and_writes_the_slug_it_decided():
    b = _hermes_branch()
    assert 'H_PY="$(_yaml_python || true)"' in b, (
        "the Hermes YAML seeder must use the shared interpreter resolver")
    assert '"$H_PY" scripts/seed_hermes_provider.py' in b
    assert "python3 scripts/seed_hermes_provider.py" not in b, (
        "a bare python3 can lack PyYAML, leaving the provider unseeded")
    assert "rm -f data/hermes-provider.json" in b, (
        "a slug from a PREVIOUS Start must never be read as this one's answer")
    assert 'HPROV=$("$H_PY" - <<\'PYSLUG\'' in b, (
        "the post-start picker check must read the slug decided by this seed")
    assert "hermes-provider.json" in b
    assert "PYPATCH" not in b, (
        "the old text patcher re-asserted model.* on every Start (ledger U12) — the "
        "seed is now the ONE writer of that block, marker-guarded")


def test_start_verifies_the_row_through_hermes_own_picker_api():
    b = _hermes_branch()
    assert "/api/model/options?include_unconfigured=1" in b
    assert "hermes provider check:" in b, (
        "the one-line verdict that makes an empty picker decidable at Start time")


def _picker_check(tmp_path, rows, hprov):
    """RUN the post-start verdict block out of start_component.sh itself.

    Asserting on its source text would pin the words, not the behaviour — and the
    two defects below (a fallback slug that always matches, a precedence bug that
    made an else-branch unreachable) both read fine as text.
    """
    body = START.split("<<'PYHCHK'", 1)[1].split("\n", 1)[1].split("\nPYHCHK", 1)[0]
    src = tmp_path / "hchk.py"
    src.write_text(body)
    payload = tmp_path / "options.json"
    payload.write_text(json.dumps({"providers": rows}) if rows is not None else "{")
    p = subprocess.run([sys.executable, str(src), str(payload)],
                       capture_output=True, text=True,
                       env=dict(os.environ, HPROV=hprov, HCFG="/tmp/config.yaml"))
    assert p.returncode == 0, p.stderr
    return p.stdout


OURS = {"slug": "custom:mot-deck-(local)", "name": "MOT Deck (local)",
        "models": ["chat-a", "chat-b"], "is_current": True}
BARE = {"slug": "custom", "name": "Custom endpoint", "models": [], "is_current": False}


def test_the_picker_check_says_it_when_our_row_reached_hermes(tmp_path):
    out = _picker_check(tmp_path, [BARE, OURS], OURS["slug"])
    assert '"MOT Deck (local)" IS in its own model picker — 2 model(s)' in out
    assert "currently selected" in out


def test_the_picker_check_never_reassures_about_a_row_that_is_not_ours(tmp_path):
    """WALKED-BUG CLASS (lie-to-user, found reviewing the inherited arm): the slug
    read-back fell back to bare `custom` when the seed wrote no verdict — and Hermes
    lists a `custom` row ALWAYS (every unconfigured canonical provider is included).
    A Start where the seeding refused (no PyYAML, an unparseable config) therefore
    printed 'IS in its own model picker' about a row with none of our models in it."""
    out = _picker_check(tmp_path, [BARE], "")
    assert "IS in its own model picker" not in out
    assert "NOT verified" in out


def test_the_picker_check_flags_a_row_that_lists_no_models(tmp_path):
    """A row that reached Hermes but carries nothing is a picker the user finds
    empty — the whole point of the slice. 'IS there' would be true and useless."""
    out = _picker_check(tmp_path, [dict(OURS, models=[])], OURS["slug"])
    assert "lists NO models" in out
    assert "IS in its own model picker" not in out


def test_the_picker_check_names_the_rows_it_did_see(tmp_path):
    """The missing-row branch listed the alternatives — but `"…%s" % join or "(none)"`
    binds as `(fmt % join) or "(none)"`, so the fallback was unreachable and an empty
    payload printed a dangling 'rows it does list:'."""
    out = _picker_check(tmp_path, [BARE], OURS["slug"])
    assert "NOT in the picker" in out and "custom" in out
    assert "rows it does list: (none)" in _picker_check(tmp_path, [], OURS["slug"])
    assert "could not read" in _picker_check(tmp_path, None, OURS["slug"])


def test_the_loffice_fence_is_re_asserted_and_the_rest_is_honoured():
    """U12(b): `trust: untrusted` is the approval switch, so it IS re-asserted (the
    one documented exception, with a printed line); a hand-set timeout is honoured."""
    b = _hermes_branch()
    assert "trust: RE-ASSERTED untrusted" in b
    assert "timeout: honoured your" in b
    assert "documented exception" in b or "DOCUMENTED EXCEPTION" in b
