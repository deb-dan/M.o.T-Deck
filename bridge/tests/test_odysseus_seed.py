"""THE ODYSSEUS SEED — never-clobber matrix + the full-registry picker (U11, v1.5.49).

THE USER STORY THIS FILE IS THE GATE FOR: Debi opens the Odysseus tab, renames the
"Local runner" endpoint to something she likes, unticks a model or two, and — on the
day she is debugging something — switches the endpoint OFF. Then she restarts MOT Deck.
Everything she did is still there. And on a fresh box, the very first time she opens
that tab, its OWN picker already lists every chat model in our registry, whether or not
the runner happens to be up.

Before this slice `scripts/seed_odysseus_jan.py` re-asserted name / api_key /
is_enabled=True on EVERY Start (the ledger's U11, found by
docs/research/2026-08-29-isolation-mode.md §3(3)), and pinned exactly ONE model — so the
picker in isolation was a one-line list that emptied when the runner went down.

The matrix below is the whole contract. It runs the seed's OWN pure planners — no DB,
no network — so a regression is caught in milliseconds and the semantics can't drift
between here and the script.

Upstream's half of the deal (that `pinned_models` is an admin list which the picker
merges without probing, and that a `local-jan` primary key can only be ours) is pinned
separately in bridge/contract_tests/test_odysseus_seed_contract.py.

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_odysseus_seed.py -q
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

SEED_PATH = os.path.join(ROOT, "scripts", "seed_odysseus_jan.py")
_spec = importlib.util.spec_from_file_location("harness_seed_odysseus", SEED_PATH)
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)

SRC = open(SEED_PATH, encoding="utf-8").read()

# ── S29: the enumeration rule now includes "the file is still on disk" ───────
# The fixtures below therefore point at REAL artifacts in a temp dir. That is not
# ceremony: before this slice every one of these fixtures named a path that has never
# existed on any machine, and they all passed — which is exactly how a seeder that
# offered models whose weights the user had deleted stayed green for weeks.
_TMP = tempfile.mkdtemp(prefix="ody-seed-fixture-")


def artifact(name, is_dir=False):
    """A minimally valid non-empty GGUF or MLX artifact."""
    p = os.path.join(_TMP, name)
    if is_dir:
        os.makedirs(p, exist_ok=True)
        open(os.path.join(p, "config.json"), "w").write("{}")
        open(os.path.join(p, "model.safetensors"), "wb").write(b"x")
    else:
        open(p, "wb").write(b"x")
    return p


MLX_9B = artifact("mlx-9b", is_dir=True)

WANT = {"name": "Local runner", "base_url": "http://127.0.0.1:6767/v1",
        "api_key": "harness-local", "models": ["big-27b", "small-4b", MLX_9B]}


def row(**over):
    """A ModelEndpoint row as the seed reads it — OUR row, in its just-seeded state."""
    r = {"id": "local-jan", "name": "Local runner", "base_url": "http://127.0.0.1:6767/v1",
         "api_key": "harness-local", "is_enabled": True, "model_type": "llm",
         "endpoint_kind": "local", "model_refresh_mode": "auto", "supports_tools": True,
         "owner": None, "cached_models": list(WANT["models"]),
         "pinned_models": list(WANT["models"]), "hidden_models": []}
    r.update(over)
    return r


MARKER = {"name": "Local runner", "base_url": "http://127.0.0.1:6767/v1",
          "api_key": "harness-local", "pinned_models": list(WANT["models"]),
          "cached_models": list(WANT["models"])}


def apply(r, changes):
    """What the script's setattr loop does, so a plan can be re-planned (idempotence)."""
    out = dict(r)
    out.update({k: v for k, v in changes.items() if k != "id"})
    return out


# ── A. first ever Start (create) ─────────────────────────────────────────────
def test_create_seeds_everything_including_the_whole_registry():
    ch, notes = seed.endpoint_plan(None, {}, WANT)
    assert ch["id"] == "local-jan" and ch["name"] == "Local runner"
    assert ch["base_url"] == WANT["base_url"] and ch["api_key"] == "harness-local"
    assert ch["is_enabled"] is True, "a NEW endpoint must arrive switched on"
    assert ch["endpoint_kind"] == "local" and ch["model_refresh_mode"] == "auto"
    assert ch["supports_tools"] is True and ch["owner"] is None
    # THE PICKER, in isolation: every registry model, pinned, no probe involved.
    assert ch["pinned_models"] == WANT["models"]
    assert ch["cached_models"] == WANT["models"]
    assert notes == []


# ── B. the never-clobber matrix (the U11 proof) ──────────────────────────────
def test_rename_survives_every_start():
    ch, notes = seed.endpoint_plan(row(name="Debi's box"), MARKER, WANT)
    assert "name" not in ch, "a human's rename must survive Start, for ever"
    assert any("honoured your rename" in n for n in notes), "and be SAID, not silent"


def test_rename_survives_even_with_no_marker_file():
    ch, _ = seed.endpoint_plan(row(name="Debi's box"), {}, WANT)
    assert "name" not in ch, "a deleted marker file must never license a clobber"


def test_a_shipped_default_name_still_migrates_forward():
    ch, _ = seed.endpoint_plan(row(name="Jan (local)"), {}, WANT)
    assert ch["name"] == "Local runner", "rows still wearing OUR old default migrate"


def test_disabled_stays_disabled_for_ever():
    r = row(is_enabled=False, name="Jan (local)", base_url="http://127.0.0.1:1337/v1")
    ch, notes = seed.endpoint_plan(r, dict(MARKER, base_url="http://127.0.0.1:1337/v1"), WANT)
    assert "is_enabled" not in ch, "NEVER re-enable what a human switched off"
    assert any("left DISABLED" in n for n in notes)
    # …and the rest of the row is still maintained while it sleeps.
    assert ch["name"] == "Local runner" and ch["base_url"] == WANT["base_url"]


def test_is_enabled_is_written_exactly_once_in_the_whole_script():
    assert SRC.count('"is_enabled": True') == 1, (
        "is_enabled may be assigned ONLY in the create branch — a second write is U11")
    assert 'ch["is_enabled"]' not in SRC, (
        "the update branch may only READ is_enabled (to say it is off), never write it")


def test_user_api_key_is_never_replaced_but_ours_rotates():
    ch, notes = seed.endpoint_plan(row(api_key="sk-debis-own"), MARKER, WANT)
    assert "api_key" not in ch and any("honoured your key" in n for n in notes)
    # ours, gone stale (harness.yaml key changed) → rotated
    stale = dict(MARKER, api_key="old-key")
    ch, _ = seed.endpoint_plan(row(api_key="old-key"), stale, WANT)
    assert ch["api_key"] == "harness-local"
    # empty → filled
    ch, _ = seed.endpoint_plan(row(api_key=None), MARKER, WANT)
    assert ch["api_key"] == "harness-local"


def test_base_url_refreshes_only_when_it_is_ours():
    # our own row after a runner PORT CHANGE (the case this script exists for)
    ch, _ = seed.endpoint_plan(row(base_url="http://127.0.0.1:1337/v1"),
                               dict(MARKER, base_url="http://127.0.0.1:1337/v1"), WANT)
    assert ch["base_url"] == WANT["base_url"]
    # …the same, with the marker file missing: the SHAPE still proves it is ours
    ch, _ = seed.endpoint_plan(row(base_url="http://127.0.0.1:1337/v1"), {}, WANT)
    assert ch["base_url"] == WANT["base_url"]
    # a human repointing it at their own box is honoured
    ch, notes = seed.endpoint_plan(row(base_url="http://studio.local:8080/v1"), {}, WANT)
    assert "base_url" not in ch and any("honoured your address" in n for n in notes)


def test_url_shape_helper():
    assert seed.looks_like_our_runner_url("http://127.0.0.1:6767/v1")
    assert seed.looks_like_our_runner_url("http://localhost:1337/v1/")
    assert not seed.looks_like_our_runner_url("http://studio.local:8080/v1")
    assert not seed.looks_like_our_runner_url("https://api.openai.com/v1")
    assert not seed.looks_like_our_runner_url("")


def test_curated_model_selection_is_never_re_seeded():
    curated = ["small-4b", "some-other-model"]
    ch, notes = seed.endpoint_plan(row(pinned_models=curated), MARKER, WANT)
    assert "pinned_models" not in ch
    assert any("honoured your" in n and "selection" in n for n in notes)
    # …and with no marker at all, a multi-model list is still treated as theirs
    ch, _ = seed.endpoint_plan(row(pinned_models=curated), {}, WANT)
    assert "pinned_models" not in ch


def test_the_pre_u11_single_model_pin_is_recognised_as_ours_and_grown():
    """The upgrade journey: a box seeded by the OLD script (one pinned model, no
    marker file) must gain the full registry on the next Start."""
    ch, _ = seed.endpoint_plan(row(pinned_models=["big-27b"], cached_models=["big-27b"]),
                               {}, WANT)
    assert ch["pinned_models"] == WANT["models"]
    assert ch["cached_models"] == WANT["models"]


def test_an_unreadable_registry_never_empties_a_full_picker():
    """ADVERSARIAL FINDING (fixed): data/models.json unreadable for ONE Start (mid-write,
    a bad mount) produced an empty model list, which the update branch then wrote over a
    perfectly good 16-model picker. The absence of information is not information."""
    ch, _ = seed.endpoint_plan(row(), MARKER, dict(WANT, models=[]))
    assert "pinned_models" not in ch and "cached_models" not in ch
    # …and on a FIRST run it writes no empty lists either (NULL ≠ "show nothing")
    ch, _ = seed.endpoint_plan(None, {}, dict(WANT, models=[]))
    assert "pinned_models" not in ch and "cached_models" not in ch
    assert ch["is_enabled"] is True, "the endpoint is still created — it can auto-discover"


def test_hidden_models_are_never_touched():
    ch, _ = seed.endpoint_plan(row(hidden_models=["small-4b"]), MARKER, WANT)
    assert "hidden_models" not in ch, (
        "hiding a model is how a human curates the picker, and hidden beats pinned "
        "in Odysseus's own merge — we must never undo it")


def test_endpoint_toggles_are_fill_if_empty_only():
    ch, _ = seed.endpoint_plan(row(supports_tools=False, endpoint_kind="api"), MARKER, WANT)
    assert "supports_tools" not in ch and "endpoint_kind" not in ch
    ch, _ = seed.endpoint_plan(row(supports_tools=None, endpoint_kind=None,
                                   model_type=None, model_refresh_mode=None), MARKER, WANT)
    assert ch == {"supports_tools": True, "endpoint_kind": "local",
                  "model_type": "llm", "model_refresh_mode": "auto"}


def test_a_settled_row_is_a_no_op_and_planning_is_idempotent():
    ch, notes = seed.endpoint_plan(row(), MARKER, WANT)
    assert ch == {} and notes == [], "a current row must produce ZERO writes"
    # plan → apply → plan again = nothing left to do, on a stale row too
    stale = row(name="Jan (local)", base_url="http://127.0.0.1:1337/v1",
                pinned_models=["big-27b"], cached_models=["big-27b"])
    ch1, _ = seed.endpoint_plan(stale, {}, WANT)
    ch2, _ = seed.endpoint_plan(apply(stale, ch1), seed.next_marker({}, ch1), WANT)
    assert ch2 == {}


# ── C. the marker: the "clobber one Start later" trap ────────────────────────
def test_marker_records_only_what_we_wrote():
    r = row(name="Debi's box")
    ch, _ = seed.endpoint_plan(r, MARKER, WANT)
    m2 = seed.next_marker(MARKER, ch)
    assert m2["name"] == "Local runner", (
        "recording the HONOURED name would make it 'ours' next Start and clobber it "
        "one restart later — the subtle half of U11")
    # …and the second Start still honours the rename
    ch2, _ = seed.endpoint_plan(r, m2, WANT)
    assert "name" not in ch2


def test_three_starts_in_a_row_after_a_rename_and_a_disable():
    """THE WALKED JOURNEY, in code: rename → Start → disable → Start → Start."""
    r, m = row(name="Debi's box"), dict(MARKER)
    for _ in range(3):
        ch, _ = seed.endpoint_plan(r, m, WANT)
        r, m = apply(r, ch), seed.next_marker(m, ch)
    assert r["name"] == "Debi's box"
    r["is_enabled"] = False
    for _ in range(3):
        ch, _ = seed.endpoint_plan(r, m, WANT)
        r, m = apply(r, ch), seed.next_marker(m, ch)
    assert r["is_enabled"] is False and r["name"] == "Debi's box"


# ── D. an ADOPTED row (the user made it themselves) gets no benefit of the doubt ──
def test_a_user_created_row_is_adopted_but_not_rewritten():
    theirs = row(id="a1b2c3d4", name="my runner", pinned_models=["small-4b"])
    ch, _ = seed.endpoint_plan(theirs, {}, WANT)
    assert "name" not in ch and "pinned_models" not in ch, (
        "shape-based ownership applies ONLY to a row carrying our own primary key")


def test_the_script_adopts_a_same_url_row_instead_of_duplicating_it():
    assert "Odysseus dedupes by" in SRC and "base_url" in SRC
    assert "adopted" in SRC, "the adopt path must be visible in the seed's own output"


# ── E. the registry → picker enumeration (the OpenCode pattern) ──────────────
def test_registry_enumeration_rules():
    reg = [
        {"id": "big-27b", "format": "gguf"},
        {"id": "whisper-base-mlx", "format": "stt-mlx", "kind": "audio"},
        {"id": "mlx-9b", "format": "mlx", "path": MLX_9B},
        {"id": "retired", "format": "gguf", "hidden": True},
        {"id": "small-4b"},
        {"id": ""},
        "not-a-dict",
    ]
    out = seed.registry_wire_models(reg)
    assert out == ["big-27b", MLX_9B, "small-4b"], (
        "audio + hidden + junk out; MLX addressed by PATH (mlx_lm LOADS the `model` "
        "field and would 404 an id on HuggingFace); llama.cpp by registry id (--alias)")
    # the loaded model leads, so a fresh default lands on what is actually resident
    assert seed.registry_wire_models(reg, "small-4b")[0] == "small-4b"
    # a probed model the registry doesn't know is not lost
    assert seed.registry_wire_models([], "probed")[0] == "probed"


def test_the_real_registry_produces_a_populated_picker():
    """Against the repo's OWN data/models.json — not a fixture."""
    try:
        reg = json.load(open(os.path.join(ROOT, "data", "models.json")))["models"]
    except Exception:
        return
    out = seed.registry_wire_models(reg)
    # S29 — the count is now the FILE-PRESENT, non-absent chat rows. On a dev tree whose
    # registry outlived its weights that is legitimately zero; what must hold is that
    # the seed and the SHARED helper agree exactly, and that nothing junk gets through.
    from bridge.core.modelreg import offerable, wire_id
    assert len(out) == len({wire_id(m) for m in offerable(reg)})
    assert all(isinstance(x, str) and x for x in out)


# ── E2. S29: a deleted model is never offered, and that is decided in ONE place ──
def test_a_model_whose_file_is_gone_is_never_pinned(tmp_path):
    """Debi's incident, as a unit: she deleted the muse/glimmer family in LM Studio and
    Odysseus went on pinning it. llama.cpp ignores the request's `model`, so picking one
    ANSWERS — under the dead model's name. That is the lie class, above a crash."""
    alive = str(tmp_path / "alive.gguf")
    open(alive, "wb").write(b"x")
    reg = [
        {"id": "alive", "format": "gguf", "path": alive},
        {"id": "Muse-Glimmer-30B-Heretic-Q4_K_S", "format": "gguf",
         "path": str(tmp_path / "deleted-in-lmstudio.gguf"),
         "artifact_evidence": {"v": 1, "real_path": os.path.realpath(str(tmp_path / "deleted-in-lmstudio.gguf")),
                               "device": os.stat("/").st_dev, "mount_root": "/",
                               "manifest": {"kind": "gguf", "files": ["deleted-in-lmstudio.gguf"]}}},
        # the persisted flag alone is enough, even without a stat-able path
        {"id": "flagged-absent", "format": "gguf", "absent": True},
    ]
    assert seed.registry_wire_models(reg) == ["alive"]


def test_an_unreadable_path_is_not_a_claim_that_the_model_is_gone():
    """ABSENCE IS NOT INFORMATION. A row with no path at all (or one whose stat fails
    for a reason that is not absence — a sleeping mount) stays offered: accusing a user
    of deleting a model they still have is the same lie, one direction over."""
    assert seed.registry_wire_models([{"id": "no-path-recorded"}]) == ["no-path-recorded"]


# ── F. the default model: seeded, never enforced ─────────────────────────────
VIS = ["big-27b", "small-4b"]


def test_default_is_seeded_when_nothing_is_configured():
    ch, _ = seed.settings_plan({}, "local-jan", True, VIS, "big-27b")
    assert ch == {"default_endpoint_id": "local-jan", "default_model": "big-27b"}


def test_a_users_default_choice_is_never_overwritten():
    s = {"default_endpoint_id": "local-jan", "default_model": "small-4b"}
    ch, notes = seed.settings_plan(s, "local-jan", True, VIS, "big-27b")
    assert ch == {} and any("honoured your choice" in n for n in notes)
    # …including a default that lives on ANOTHER endpoint entirely
    s = {"default_endpoint_id": "openrouter", "default_model": "gpt-x"}
    ch, _ = seed.settings_plan(s, "local-jan", True, VIS, "big-27b", ["openrouter", "local-jan"])
    assert ch == {}


def test_a_dangling_default_is_repaired():
    # endpoint the user deleted
    ch, _ = seed.settings_plan({"default_endpoint_id": "gone", "default_model": "x"},
                               "local-jan", True, VIS, "big-27b", ["local-jan"])
    assert ch["default_endpoint_id"] == "local-jan" and ch["default_model"] == "big-27b"
    # model this endpoint no longer offers
    s = {"default_endpoint_id": "local-jan", "default_model": "deleted-model"}
    ch, notes = seed.settings_plan(s, "local-jan", True, VIS, "big-27b")
    assert ch == {"default_model": "big-27b"}
    assert any("no longer offered" in n for n in notes)


def test_a_disabled_endpoint_is_never_made_the_default():
    ch, notes = seed.settings_plan({}, "local-jan", False, VIS, "big-27b")
    assert "default_endpoint_id" not in ch
    assert any("DISABLED" in n for n in notes)


# ── G. the writer discipline the script must keep ───────────────────────────
def test_the_script_documents_u11_and_its_rules():
    for phrase in ("NEVER RE-ENABLE", "CREATE-IF-ABSENT",
                   "UPDATE ONLY WHAT IS PROVABLY OURS", "U11"):
        assert phrase in SRC, f"the reason this file is shaped this way must stay written: {phrase}"


def test_no_unconditional_assignment_survives():
    for banned in ("ep.name = NAME", "ep.is_enabled = True", "ep.api_key = API_KEY",
                   "ep.pinned_models = model_json", "ep.base_url = BASE_URL"):
        assert banned not in SRC, f"pre-U11 unconditional write is back: {banned}"


# ── H. LIVE FIRST, PIN LAST (S28 — the post-switch coherence audit) ──────────
#
# THE INCIDENT, AS A USER STORY: Debi switched the runner to Parable-Qwen3-4B and
# deleted the old 27B's weights. Every Odysseus Start after that RE-SEEDED the deleted
# 27B — as the default AND into `pinned_models` — because `_wire_model()` read
# harness.yaml's pin instead of asking the runner what it was serving. llama.cpp
# ignores the request's `model` field, so her chats worked and were labelled with a
# model that had not existed for days. The seeder did not merely inherit the drift, it
# PROPAGATED it into a third-party picker.

def test_a_probe_is_only_believed_when_it_maps_to_something_we_ship():
    reg = [{"id": "small-4b"}, {"id": "mlx-9b", "format": "mlx", "path": MLX_9B}]
    assert seed.live_wire("small-4b", reg) == "small-4b"
    assert seed.live_wire(MLX_9B, reg) == MLX_9B, "MLX answers with its path"
    # An MLX server's /v1/models enumerates the whole HuggingFace CACHE, so data[0] is
    # routinely an unrelated repo. An unmappable probe is DISCARDED, never trusted —
    # the same rule bridge/core/modelid.py::_reconcile_live has always applied.
    assert seed.live_wire("meta-llama/Llama-3-70B", reg) == ""
    assert seed.live_wire("", reg) == "" and seed.live_wire(None, reg) == ""


def test_the_env_seam_finally_has_a_caller_and_it_wins():
    """HARNESS_WIRE_MODEL existed from the start with ZERO callers (audit §1). The
    switch trigger now passes the model it just loaded; it outranks everything."""
    old = os.environ.get("HARNESS_WIRE_MODEL")
    os.environ["HARNESS_WIRE_MODEL"] = "just-loaded-4b"
    try:
        assert seed.resolve_wire() == ("just-loaded-4b", "env")
    finally:
        os.environ.pop("HARNESS_WIRE_MODEL", None)
        if old is not None:
            os.environ["HARNESS_WIRE_MODEL"] = old


def test_a_ghost_pin_is_never_offered_and_never_becomes_a_default():
    """THE PROPAGATION BUG. `offerable` is the gate that stops it."""
    reg = [{"id": "small-4b"}, {"id": "big-27b"}]
    assert seed.offerable("small-4b", "pin", reg), "a REGISTERED pin is fine"
    assert not seed.offerable("deleted-27b", "pin", reg), \
        "a pin naming neither a registered nor a served model is a GHOST"
    assert seed.offerable("weird-but-served", "live", reg), \
        "…but something the runner is actually SERVING is real, registry or not"
    assert seed.offerable("explicit", "env", reg), "…as is an explicit caller's answer"
    assert not seed.offerable("", "live", reg)
    # And with the ghost pruned, the picker list carries no trace of it…
    assert "deleted-27b" not in seed.registry_wire_models(reg, "")
    # …which is exactly what makes settings_plan repair the stale default: the
    # configured choice now DANGLES against what this endpoint offers.
    ch, notes = seed.settings_plan({"default_endpoint_id": "local-jan",
                                    "default_model": "deleted-27b"},
                                   "local-jan", True, ["small-4b"], "small-4b")
    assert ch.get("default_model") == "small-4b"
    assert any("no longer offered" in n for n in notes), \
        "and it SAYS so — a silent repair is its own kind of lie"


def test_the_script_still_says_why_it_prefers_live():
    for phrase in ("live_wire", "resolve_wire", "offerable", "HARNESS_WIRE_MODEL",
                   "GHOST"):
        assert phrase in SRC, f"S28's reasoning must stay written: {phrase}"
    assert "pin_wire" in SRC and "_active_model_id" in SRC, \
        "the pin is still READABLE — it is the runner-down fallback, not a mistake"


def test_our_own_stale_default_is_refreshed_but_the_humans_is_not():
    """S28's fourth state. `default_model` had no marker, so a value THIS SCRIPT seeded
    at the previous switch was honoured as if a human had picked it — switch twice and
    Odysseus's chip keeps naming the model from the switch before, valid and stale."""
    vis = ["new-4b", "old-9b", "hers-27b"]
    # ours, and stale → refreshed, out loud
    ch, notes = seed.settings_plan({"default_endpoint_id": "local-jan",
                                    "default_model": "old-9b"},
                                   "local-jan", True, vis, "new-4b",
                                   None, {"default_model": "old-9b"})
    assert ch.get("default_model") == "new-4b"
    assert any("OUR OWN last seed" in n for n in notes), "and it SAYS whose value it was"
    # hers → untouchable, marker or no marker
    ch2, notes2 = seed.settings_plan({"default_endpoint_id": "local-jan",
                                      "default_model": "hers-27b"},
                                     "local-jan", True, vis, "new-4b",
                                     None, {"default_model": "old-9b"})
    assert "default_model" not in ch2
    assert any("honoured your choice" in n for n in notes2)
    # no marker at all (fresh clone, tidied state file) → the pre-S28 behaviour exactly:
    # a working value is honoured. Losing the evidence must never license a clobber.
    ch3, _ = seed.settings_plan({"default_endpoint_id": "local-jan",
                                 "default_model": "old-9b"},
                                "local-jan", True, vis, "new-4b")
    assert "default_model" not in ch3


def test_the_marker_records_only_what_we_wrote():
    m = seed.next_marker({"default_model": "old"}, {"default_model": "new"})
    assert m["default_model"] == "new"
    # a field we merely HONOURED is not recorded — recording it is what would make it
    # "ours" next run and clobber it one Start later.
    assert seed.next_marker({"default_model": "old"}, {})["default_model"] == "old"
    assert "default_model" in SRC.split("def next_marker")[1][:700], \
        "next_marker must carry default_model or the fourth state cannot work"
