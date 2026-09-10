"""REGISTRY HYGIENE — dead models leave, everywhere, from one place (S29, U15 follow-on).

THE USER STORY THIS FILE IS THE GATE FOR, in Debi's own words (2026-08-29):

    "I deleted those models days ago… OpenCode is still offering very old deleted
     models. Isn't there a way to make the different apps scan?"

She had deleted gemma-4 and the muse/glimmer family in LM Studio. MOT Deck's own fit
chips said "file missing" honestly — and every LIST in the building went on offering
them: OpenCode's provider catalog (measured: 16 models, last written 2026-08-28 01:49,
including `Muse-Glimmer-30B-Heretic-Q4_K_S` and `dflash-Muse-Glimmer-30B-Abliterated`),
and, structurally, our own composer picker, goose's provider file, Hermes's row and
Odysseus's `pinned_models`.

Picking one of those does not error. llama.cpp IGNORES the request's `model` field, so
the turn works and answers under the dead model's name — the LIE class, which the
doctrine ranks above crashes. And the answer to her question is that the apps should
never have to scan: they do not own the registry, we do.

The three properties this suite fences:

  A. ONE DEFINITION of "a model that may be offered" (core/modelreg.offerable) — chat,
     not hidden, not flagged absent, file not provably gone — and every enumerator
     going through it. Before S29 that sentence existed in five near-copies and NONE of
     them knew about the file.
  B. RESCAN IS THE PRUNE: a row whose file is gone is REMOVED with a printed line,
     unless it is the pin/live model, which is FLAGGED and kept. Model FILES are never
     touched. An unreadable path is never a claim in either direction.
  C. THE PICKERS AGREE: the composer picker excludes what the catalogs exclude; the
     Models view keeps those rows, sorted last, wearing the chip.

Run: data/bridge-venv/bin/python -m pytest bridge/tests/test_registry_hygiene.py -q
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.core import modelreg as MR                          # noqa: E402
from bridge.tests.model_fixture import gguf_bytes               # noqa: E402

PANEL = (ROOT / "bridge" / "panel" / "index.html").read_text(errors="replace")
START = (ROOT / "scripts" / "start_component.sh").read_text(errors="replace")

_spec = importlib.util.spec_from_file_location(
    "motdeck_seed_registry", str(ROOT / "scripts" / "seed_registry.py"))
SR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SR)

# Debi's actual dead models — used as fixture ids throughout, so a future reader can
# see which incident this suite is about without leaving the file.
DEAD = ["Muse-Glimmer-30B-Heretic-Q4_K_S",
        "dflash-Muse-Glimmer-30B-Abliterated-Q4_K_M",
        "gemma-4-31B-it-The-DECKARD-HERETIC-UNCENSORED-Thinking.i1-Q4_K_S"]


def _alive(tmp_path, name="alive.gguf"):
    p = tmp_path / name
    p.write_bytes(gguf_bytes())
    return str(p)


def _mlx(tmp_path, name="mlx-model"):
    p = tmp_path / name
    p.mkdir()
    (p / "config.json").write_text('{"model_type":"unit-test"}')
    header = json.dumps({"w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
    (p / "model.safetensors").write_bytes(len(header).to_bytes(8, "little") + header + b"\0" * 4)
    return p


def _evidence(path):
    return {"v": 1, "real_path": str(path), "device": os.stat("/").st_dev,
            "mount_root": "/", "manifest": {"kind": "gguf", "files": [Path(path).name]}}


# ══ A. ONE DEFINITION ════════════════════════════════════════════════════════
def test_the_one_rule_keeps_only_models_that_are_real(tmp_path):
    alive, mlx = _alive(tmp_path), _mlx(tmp_path)
    reg = [
        {"id": "keep-gguf", "format": "gguf", "path": alive},
        {"id": "keep-mlx", "format": "mlx", "path": str(mlx)},
        {"id": "keep-no-path-recorded"},                 # unknown ⇒ kept, see below
        {"id": DEAD[0], "format": "gguf", "path": str(tmp_path / "deleted.gguf"), "artifact_evidence": _evidence(tmp_path / "deleted.gguf")},
        {"id": "flagged", "format": "gguf", "path": alive, "absent": True},
        {"id": "hidden-one", "format": "gguf", "path": alive, "hidden": True},
        {"id": "voice", "kind": "audio", "format": "stt-mlx", "path": str(mlx)},
        {"id": "voice-by-format", "format": "tts-mlx", "path": str(mlx)},
        {"id": "", "path": alive},
        "not-a-dict",
    ]
    assert [m["id"] for m in MR.offerable(reg)] == [
        "keep-gguf", "keep-mlx", "keep-no-path-recorded"]


def test_an_mlx_row_is_addressed_by_path_and_a_gguf_row_by_id(tmp_path):
    """The two-identifier rule, once, for all five enumerators. An MLX server treats
    the request's `model` as a model to LOAD; a bare id would be resolved on
    HuggingFace → 404 → runner 400."""
    mlx = tmp_path / "m"
    mlx.mkdir()
    assert MR.wire_id({"id": "x", "format": "mlx", "path": str(mlx)}) == str(mlx)
    assert MR.wire_id({"id": "x", "format": "gguf", "path": "/p"}) == "x"
    # an MLX row with no path recorded falls back to its id rather than to ""
    assert MR.wire_id({"id": "x", "format": "mlx"}) == "x"


def test_absence_is_not_information(tmp_path):
    """★ THE GUARD THAT KEEPS THIS FROM BECOMING ITS OWN LIE. os.stat on a sleeping
    SMB/NFS mount or a spun-down external disk answers ENOENT rather than raising, and
    a permission error is not absence either. Telling a user their models are gone
    because a cable is out is the same lie class, one direction over."""
    assert MR.path_present("", "gguf") is None
    assert MR.path_present(None) is None
    assert MR.path_present(_alive(tmp_path)) is True
    assert MR.path_present("/definitely/not/here.gguf") is False
    # kind matters: a FILE is not an mlx model dir, and a DIR is not a gguf
    assert MR.path_present(str(_mlx(tmp_path)), "mlx") is True
    assert MR.path_present("/etc", "gguf") is False
    # a row with no path at all is unknown, and unknown is always KEPT
    assert [m["id"] for m in MR.offerable([{"id": "u"}])] == ["u"]


def test_an_unplugged_disk_does_not_empty_every_picker(tmp_path):
    """★ THE ADVERSARIAL FINDING OF THIS SLICE. Debi keeps models in LM Studio's library
    and on an external volume: pull the cable and EVERY path answers ENOENT at once.
    Without a guard, one enumeration would empty Hermes's row, collapse OpenCode's
    catalog to its placeholder and strip Odysseus's pins — over a cable. 'Every model in
    the registry vanished simultaneously' is not a user deleting models; it is us losing
    sight of the disk, and what we cannot see we do not claim."""
    reg = [{"id": "a", "format": "gguf", "path": str(tmp_path / "a.gguf")},
           {"id": "b", "format": "gguf", "path": str(tmp_path / "b.gguf")}]
    assert [m["id"] for m in MR.offerable(reg)] == ["a", "b"], (
        "the FILE clause abstains when it would drop everything")
    # …but a missing model with evidence on the still-available source is dropped.
    reg.append({"id": "c", "format": "gguf", "path": _alive(tmp_path, "c.gguf")})
    reg[0]["artifact_evidence"] = _evidence(reg[0]["path"])
    reg[1]["artifact_evidence"] = _evidence(reg[1]["path"])
    assert [m["id"] for m in MR.offerable(reg)] == ["c"]
    # …and the guard never resurrects a recorded fact: audio/hidden/absent still apply
    assert MR.offerable([{"id": "x", "format": "gguf", "path": "/gone", "hidden": True}]) == []
    assert MR.offerable([{"id": "x", "format": "gguf", "path": "/gone",
                          "absent": True}]) == []
    # a genuinely empty registry stays empty (the guard needs candidates to fire)
    assert MR.offerable([]) == []


def test_the_bridge_decides_absence_per_source_not_by_a_blanket_count():
    from bridge.appsrc import APP_SOURCE as APP
    body = APP[APP.index("def _persist_absent"):APP.index("@app.get(\"/api/models\")")]
    assert "probe = artifact_probe(m)" in body
    assert "source_availability(m, probe)" in body
    assert 'probe.get("state") == "missing" and source == "available"' in body


def test_the_running_model_is_never_hidden_from_the_picker():
    """★ SECOND ADVERSARIAL FINDING. If the LIVE model's file disappears, its weights
    are still in RAM — the turn works. Dropping its row would leave the composer chip
    naming a model the popover does not list, with no way to Eject it."""
    i = PANEL.index("function renderModelPop()")
    body = PANEL[i:i + 2200]
    assert "(modelLiveId && m.id === modelLiveId)" in body


def test_the_active_model_leads_the_wire_list(tmp_path):
    alive = _alive(tmp_path)
    reg = [{"id": "a", "path": alive}, {"id": "b", "path": alive}]
    assert MR.offerable_wire_ids(reg, "b") == ["b", "a"]
    # a probed model the registry does not know is not lost
    assert MR.offerable_wire_ids([], "probed") == ["probed"]


def test_every_enumerator_goes_through_the_one_definition():
    """THE ECHO FENCE (doctrine 6b). S29 exists because the sentence "which models may
    we offer" lived in five places. This test is what stops a sixth appearing: each
    enumerator must NAME the shared helper, and the old inline audio/hidden pair must
    not be re-derived beside it."""
    for rel in ("bridge/gooseprov.py", "bridge/gooseui.py",
                "scripts/seed_odysseus_jan.py", "scripts/seed_hermes_provider.py",
                "scripts/seed_opencode_config.py", "scripts/seed_deepseek_config.py"):
        src = (ROOT / rel).read_text(errors="replace")
        assert ("modelreg" in src or "offerable" in src
                or (rel == "bridge/gooseui.py" and "gooseprov as _prov" in src)), (
            f"{rel} enumerates models without the shared rule — that is how OpenCode "
            f"kept offering models deleted days earlier")
    # the OpenCode arm no longer carries its own copy at all
    assert "<<'PYOC'" not in START, "the opencode heredoc must be gone, not bypassed"
    assert "scripts/seed_opencode_config.py" in START
    # and the FILE half has exactly one implementation
    assert "artifact_probe" in (
        ROOT / "bridge" / "core" / "health.py").read_text(), (
        "health.py must re-export the shared path check, never re-implement it")


def test_an_empty_enumeration_is_never_written_through(tmp_path):
    """★ FOUND IN THIS SLICE'S OWN ADVERSARIAL PASS. Adding the file clause created a
    second way for the list to come back empty: every artifact answering 'gone' at
    once, which is exactly what an UNPLUGGED EXTERNAL DISK looks like for one poll.
    Writing that through would empty goose's picker over a cable."""
    from bridge import gooseprov as P
    existing = {"name": P.PROVIDER_NAME, "models": [{"name": "still-here"}],
                "display_name": "MOT Deck (local)"}
    ours = P.provider_doc("http://127.0.0.1:6767", [])          # learned nothing
    merged = P.merge_provider(existing, ours)
    assert merged["models"] == [{"name": "still-here"}], (
        "when we learned nothing, we change nothing — the previous list stands")
    # …but a real, non-empty list DOES replace the old one (the prune must still work)
    fresh = P.provider_doc("http://127.0.0.1:6767", [{"name": "new-one"}])
    assert P.merge_provider(existing, fresh)["models"] == [{"name": "new-one"}]


# ══ B. RESCAN IS THE PRUNE ═══════════════════════════════════════════════════
def test_a_deleted_model_is_removed_and_the_removal_is_printed(tmp_path):
    alive = _alive(tmp_path)
    reg = [{"id": "keeper", "format": "gguf", "path": alive, "source": "download"}] + [
        {"id": d, "format": "gguf", "path": str(tmp_path / (d + ".gguf")),
         "source": "download", "artifact_evidence": _evidence(tmp_path / (d + ".gguf"))} for d in DEAD]
    kept, removed, flagged = SR.prune_absent(reg)
    assert [m["id"] for m in kept] == ["keeper"]
    assert removed == DEAD and flagged == []


def test_the_pinned_or_live_model_is_flagged_and_kept_never_removed(tmp_path):
    """The runner card's honest 'Online — pinned model missing' needs the row it is
    talking about. Removing it would swap one honest sentence for a vaguer one."""
    reg = [{"id": "the-pin", "format": "gguf", "path": str(tmp_path / "gone.gguf"), "artifact_evidence": _evidence(tmp_path / "gone.gguf")},
           {"id": "other", "format": "gguf", "path": str(tmp_path / "gone2.gguf"), "artifact_evidence": _evidence(tmp_path / "gone2.gguf")}]
    kept, removed, flagged = SR.prune_absent(reg, protect=["the-pin"])
    assert [m["id"] for m in kept] == ["the-pin"]
    assert kept[0]["absent"] is True and flagged == ["the-pin"] and removed == ["other"]


def test_a_row_we_cannot_check_is_left_exactly_as_it_was(tmp_path):
    """A detached volume must never cost a registry row. Unknown ⇒ untouched."""
    reg = [{"id": "no-path", "format": "gguf", "voice": "af_heart", "ctx": 32768}]
    kept, removed, flagged = SR.prune_absent(reg)
    assert kept == reg and removed == [] and flagged == []


def test_a_returning_file_clears_the_flag(tmp_path):
    """The volume comes back. Nothing asks the user to do anything."""
    alive = _alive(tmp_path)
    kept, removed, flagged = SR.prune_absent(
        [{"id": "back", "format": "gguf", "path": alive, "absent": True}])
    assert "absent" not in kept[0] and removed == [] and flagged == []


def test_the_prune_turns_itself_off_rather_than_guess(monkeypatch):
    """If the shared helper could not be loaded, 'we cannot check' must never become
    'everything is gone' — the whole registry would be deleted by a broken import."""
    monkeypatch.setattr(SR, "MODELREG", None)
    reg = [{"id": "x", "format": "gguf", "path": "/definitely/not/here.gguf"}]
    kept, removed, flagged = SR.prune_absent(reg)
    assert kept == reg and removed == [] and flagged == []


def test_the_user_decision_keys_survive_a_prune(tmp_path):
    """A pinned voice, a tuned sampling block and a known ctx live NOWHERE on disk. The
    prune stats files; it must not be a second way to lose them."""
    alive = _alive(tmp_path)
    row = {"id": "k", "format": "gguf", "path": alive, "voice": "af_heart",
           "ctx": 95536, "settings": {"temp": 0.4}, "load": {"kv_quant": "q8_0"}}
    kept, _, _ = SR.prune_absent([row])
    assert kept[0] == row


def test_rescan_end_to_end_uses_manager_membership_not_leftover_files(tmp_path):
    """★ THE WHOLE JOURNEY, on the real script, over a real temp tree.

    LM Studio membership and filesystem structure are independent evidence. Removing
    a manager row must propagate even when the manager leaves the bytes behind."""
    import shutil
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    lms = tmp_path / "lmstudio"
    for pub, fname in (("Parable-4B", "Parable-4B.gguf"),
                       ("Muse-Glimmer-30B", DEAD[0] + ".gguf")):
        (lms / "pub" / pub).mkdir(parents=True)
        (lms / "pub" / pub / fname).write_bytes(gguf_bytes())
    catalog = tmp_path / "catalog.json"
    fake_lms = tmp_path / "fake-lms"
    fake_lms.write_text('#!/bin/sh\ncat "$FAKE_LMS_CATALOG"\n')
    fake_lms.chmod(0o755)

    def set_catalog(items):
        catalog.write_text(json.dumps([
            {"type": "llm", "format": "gguf", "modelKey": model_dir,
             "displayName": model_dir, "path": f"pub/{model_dir}/{filename}"}
            for model_dir, filename in items]))

    set_catalog([("Parable-4B", "Parable-4B.gguf"),
                 ("Muse-Glimmer-30B", DEAD[0] + ".gguf")])
    (root / "motdeck.yaml").write_text("runner:\n  model: Parable-4B\n  port: 6767\n")
    # A source 'download' row whose weights are long gone — the class merge() preserves
    # untouched by design and therefore can never prune on its own.
    (root / "data" / "models.json").write_text(json.dumps({"models": [
        {"id": "old-download", "source": "download", "format": "gguf",
         "path": str(tmp_path / "long-gone.gguf"), "voice": "af_heart",
         "artifact_evidence": _evidence(tmp_path / "long-gone.gguf")}]}))

    def rescan(protect=""):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_registry.py"), "--json"],
            cwd=str(root), capture_output=True, text=True, timeout=120,
            env=dict(os.environ, MOT_DECK_LMSTUDIO_DIR=str(lms),
                     MOT_DECK_LMS_BIN=str(fake_lms), FAKE_LMS_CATALOG=str(catalog),
                     MOT_DECK_JAN_MODELS_DIR=str(tmp_path / "no-jan"),
                     MOT_DECK_PROTECT_MODELS=protect))
        assert r.returncode == 0, r.stderr
        reg = json.loads((root / "data" / "models.json").read_text())["models"]
        return json.loads(r.stdout), {m["id"] for m in reg}

    out, ids = rescan()
    assert ids == {"Parable-4B", DEAD[0]}, "both LM Studio models are on disk here"
    assert "old-download" in out["pruned"], (
        "the stat pass prunes the source 'download' row merge() preserves — and SAYS SO")

    # Manager removal is authoritative even though its storage directory remains.
    set_catalog([("Parable-4B", "Parable-4B.gguf")])
    out, ids = rescan()
    assert ids == {"Parable-4B"}, (
        "manager-level removal propagates without guessing from leftover files")
    assert (lms / "pub" / "Muse-Glimmer-30B" / (DEAD[0] + ".gguf")).exists()

    # And the PIN's own row is flagged, never removed, so the runner card keeps its
    # subject: delete Parable's weights too and rescan protecting it.
    shutil.rmtree(lms / "pub" / "Parable-4B")
    set_catalog([])
    (root / "data" / "models.json").write_text(json.dumps({"models": [
        {"id": "Parable-4B", "source": "download", "format": "gguf",
             "path": str(lms / "pub" / "Parable-4B" / "Parable-4B.gguf"),
             "artifact_evidence": _evidence(lms / "pub" / "Parable-4B" / "Parable-4B.gguf")}]}))
    out, ids = rescan()
    assert ids == {"Parable-4B"} and "Parable-4B" in out["flagged"]
    row = json.loads((root / "data" / "models.json").read_text())["models"][0]
    assert row["absent"] is True


def test_the_rescan_never_deletes_a_model_file(tmp_path):
    """NON-NEGOTIABLE. The prune edits data/models.json and nothing else; removing
    weights is /api/models/delete's job and a different consent."""
    src = (ROOT / "scripts" / "seed_registry.py").read_text()
    body = src[src.index("def prune_absent"):src.index("def write(")]
    for danger in ("os.remove", "os.unlink", "shutil.rmtree", "rmdir"):
        assert danger not in body, f"the prune must never call {danger}"


def test_the_protect_set_reads_the_pin_and_the_env(tmp_path, monkeypatch):
    (tmp_path / "motdeck.yaml").write_text(
        "components:\n  hermes:\n    model: not-the-runner\n"
        "runner:\n  model: the-pin  # a trailing comment\n  port: 6767\n")
    monkeypatch.setenv("MOT_DECK_PROTECT_MODELS", "live-one\nanother,third")
    got = MR.protected_ids(str(tmp_path))
    assert got == {"the-pin", "live-one", "another", "third"}, (
        "the pin is read without pyyaml (the seeders have no dependency), comments are "
        "stripped, and the bridge hands the LIVE model down through the env")


# ══ C. THE PICKERS AGREE ═════════════════════════════════════════════════════
def test_the_composer_picker_excludes_what_cannot_load():
    """A picker that offers a model which cannot load is the lie class: clicking Switch
    spends 60-90s to fail, and listing it is the invitation to do that."""
    i = PANEL.index("function renderModelPop()")
    body = PANEL[i:i + 3000]
    assert "m.file === 'incomplete'" in body and "m.file === 'gone'" in body, (
        "the composer picker must enumerate exactly what the app catalogs enumerate")
    assert "No loadable models" in body, (
        "graceful absence: every state the user can reach lands on something usable")
    assert "checking" in body, (
        "the two-strike discipline must be argued here too — one missed stat (a "
        "sleeping volume) may not remove a model from the picker")


def test_the_models_view_keeps_them_but_sorts_them_last():
    """The Models view is the pane that owes the user the bad news AND the RESCAN
    button, so it must not hide these rows — only stop putting them first."""
    i = PANEL.index("function renderList(r)")
    body = PANEL[i:i + 2400]
    assert "sort(" in body and "a.file === 'gone'" in body
    assert "for (const m of rows)" in body, "the sorted list is what is rendered"
    # the chip is drawn from EITHER the live debounce or the persisted flag
    assert "m.file === 'gone' || m.absent" in PANEL


def test_a_rescan_that_shrinks_the_list_says_why():
    assert "REMOVED " in PANEL and "j2.pruned" in PANEL, (
        "a library that silently shrank is indistinguishable from one that broke")
    assert "APP CATALOGS" in PANEL, (
        "and the answer to 'can the apps scan?' has to be VISIBLE when it happens")


def test_the_bridge_publishes_the_persisted_flag():
    from bridge.appsrc import APP_SOURCE as APP
    assert '"absent": m.get("absent") is True,' in APP, (
        "the panel needs the PERSISTED verdict, not only this process's debounce — it "
        "is what every other enumerator will act on")
    assert "def _persist_absent" in APP
    i = APP.index("def _persist_absent")
    body = APP[i:i + 2000]
    assert 'st == "gone"' in body and 'st == "ok"' in body, (
        "only a DEBOUNCED verdict may write: 'checking' and 'unknown' change nothing")
    assert "if not dirty:" in body, (
        "this runs inside a polled GET — it may only write when something changed")


def test_opencode_is_in_the_fan_out():
    """v1.5.62 wired Hermes/Odysseus/goose and left OpenCode out; OpenCode is the one
    Debi named. Both triggers now reach it: a model switch and a RESCAN."""
    from bridge.appsrc import APP_SOURCE as APP
    assert "def _rebind_opencode" in APP
    i = APP.index("def _rebind_dependents")
    assert "_rebind_opencode(wire)" in APP[i:i + 2500], (
        "the switch fan-out must reach OpenCode")
    j = APP.index("def _rescan_fanout")
    fan = APP[j:APP.index("def _rebind_dependents", j)]
    for who in ("_rebind_opencode", "_rebind_hermes_file", "_rebind_goose"):
        assert who in fan, f"the rescan fan-out must reach {who}"
    ody = APP[APP.index("async def _rebind_odysseus_after_rescan"):]
    ody = ody[:ody.index("\n\n\ndef ")]
    assert "_rebind_odysseus_offline" in ody
    assert '"PATCH", f"/api/model-endpoints/{plan[\'id\']}/models"' in ody, (
        "a running Odysseus must use its authenticated live model-list operation")
    assert "NO RESTARTS HERE" in fan, (
        "a rescan is a read-the-disk button; killing a live agent session to refresh a "
        "picker would be a worse surprise than a stale list")


def test_the_fan_out_never_claims_work_it_did_not_do():
    """★ FOUND IN THE LIVE WALK. Every seed here returns '' on a clean run AND on
    'that component is not installed'. The first summary therefore said "Odysseus:
    picker rebuilt" on a machine with no Odysseus — a claim about work that did not
    happen, which is the lie class in miniature. Installed-ness is now checked BEFORE
    anything is claimed, and a lane that is absent says nothing at all (S23)."""
    from bridge.appsrc import APP_SOURCE as APP
    fan = APP[APP.index("def _rescan_fanout"):APP.index("def _rebind_dependents")]
    assert "if not present:" in fan and "continue" in fan
    assert "no file-backed dependent catalogs present" in fan, (
        "and with no file-backed lane the summary must say so rather than be blank")
    ody = APP[APP.index("async def _rebind_odysseus_after_rescan"):]
    ody = ody[:ody.index("\n\n\ndef ")]
    assert '(ROOT / "vendor" / "odysseus").is_dir()' in ody
    assert 'return ""' in ody, "an absent Odysseus must still produce no claim"


def test_the_opencode_restart_requirement_is_recorded_as_measured():
    """★ THE FACT THIS SLICE GOT WRONG FIRST. The initial implementation asserted that
    a running OpenCode re-reads its config, so a file write was the whole fix. MEASURED
    2026-08-29: after the rewrite, `GET :4096/provider` still returned the sixteen OLD
    models — it caches at boot. Shipping that draft would have been a fix that reported
    success and changed nothing the user can see. The correction is pinned here so it
    cannot be quietly reverted to the comfortable belief."""
    from bridge.appsrc import APP_SOURCE as APP
    doc = APP[APP.index("def _rebind_opencode"):APP.index("def _rebind_hermes_file")]
    assert "reads its config at BOOT" in doc
    assert "RESTART OpenCode to load it" in doc, (
        "the returned line must tell the user the one thing left to do")
