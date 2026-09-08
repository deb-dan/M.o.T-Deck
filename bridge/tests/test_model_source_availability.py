"""U76 journeys: evidence distinguishes deletion from an unavailable model source."""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge.core import modelreg as MR
from bridge.tests.model_fixture import gguf_bytes

_spec = importlib.util.spec_from_file_location("u76_seed", os.path.join(ROOT, "scripts", "seed_registry.py"))
SR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SR)


def row(tmp_path, name="model.gguf"):
    p = tmp_path / name
    p.write_bytes(gguf_bytes())
    return {"id": p.stem, "format": "gguf", "path": str(p), "source": "download"}


def evidence(r):
    got = MR.artifact_evidence(r)
    assert got and got["v"] == 1
    return got


def test_01_ready_gguf_evidence_is_v1_names_only_and_idempotent(tmp_path):
    r = row(tmp_path)
    a, b = evidence(r), evidence(r)
    assert a == b and a["manifest"] == {"kind": "gguf", "files": ["model.gguf"]}
    assert "artifact_evidence" not in r
    assert SR.apply_artifact_evidence([r])[0]["artifact_evidence"] == a


def test_02_missing_on_available_mount_is_confirmed_deletion(tmp_path):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    assert MR.source_availability(r)["state"] == "available"
    assert MR.offerable([r]) == []


def test_03_protected_confirmed_deletion_is_absent_not_removed(tmp_path):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    kept, removed, flagged = SR.prune_absent([r], protect=[r["id"]])
    assert kept[0]["absent"] is True and not removed and flagged == [r["id"]]


def test_04_missing_external_root_is_unavailable_not_deletion(tmp_path):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    r["path"] = "/Volumes/U76-not-present/model.gguf"
    r["artifact_evidence"] = dict(r["artifact_evidence"], real_path=r["path"], mount_root="/Volumes/U76-not-present")
    assert MR.source_availability(r)["state"] == "unavailable"
    assert MR.offerable([r]) == [r]


def test_05_mountpoint_device_fallback_is_unavailable(tmp_path, monkeypatch):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    ev = dict(r["artifact_evidence"], mount_root="/Volumes/U76", real_path="/Volumes/U76/a.gguf", device=10)
    r.update(path="/Volumes/U76/a.gguf", artifact_evidence=ev)
    monkeypatch.setattr(MR.os, "stat", lambda *_, **__: SimpleNamespace(st_mode=0o040755, st_dev=11))
    monkeypatch.setattr(MR.os.path, "ismount", lambda _: True)
    assert MR.source_availability(r, {"state": "missing"})["state"] == "unavailable"


def test_06_reappeared_ready_refreshes_evidence_and_clears_absent(tmp_path):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); r["absent"] = True
    kept, _, _ = SR.prune_absent([r])
    assert "absent" not in kept[0] and MR.artifact_evidence(r)["real_path"] == os.path.realpath(r["path"])


def test_07_mixed_local_deletion_and_unavailable_external_are_per_row(tmp_path):
    local = row(tmp_path, "local.gguf"); local["artifact_evidence"] = evidence(local); os.unlink(local["path"])
    ext = row(tmp_path, "external.gguf"); ext["artifact_evidence"] = evidence(ext); os.unlink(ext["path"])
    ext["path"] = "/Volumes/U76-missing/external.gguf"
    ext["artifact_evidence"] = dict(ext["artifact_evidence"], real_path=ext["path"], mount_root="/Volumes/U76-missing")
    kept, removed, _ = SR.prune_absent([local, ext])
    assert removed == ["local"] and [m["id"] for m in kept] == ["external"]


@pytest.mark.parametrize("bad", [{}, {"v": 1, "real_path": "relative", "mount_root": "/", "device": 1, "manifest": {}},
                                  {"v": 1, "real_path": "/x", "mount_root": "/", "device": True, "manifest": {"kind": "gguf", "files": []}},
                                  {"v": 1, "real_path": "/x", "mount_root": "/", "device": 1, "manifest": {"kind": "gguf", "files": ["."]}},
                                  {"v": 1, "real_path": "/x", "mount_root": "/", "device": 1, "manifest": {"kind": "gguf", "files": [".."]}}])
def test_08_malformed_evidence_is_unknown_and_never_destructive(tmp_path, bad):
    r = row(tmp_path); os.unlink(r["path"]); r["artifact_evidence"] = bad
    assert MR.source_availability(r)["state"] == "unknown"
    assert SR.prune_absent([r])[0] == [r]


def test_09_incomplete_is_not_rescued_as_cable_loss(tmp_path):
    r = row(tmp_path); open(r["path"], "wb").close(); r["artifact_evidence"] = {"bad": True}
    assert MR.artifact_probe(r)["state"] == "incomplete" and MR.offerable([r]) == []


def test_10_all_confirmed_deletions_do_not_resurrect(tmp_path):
    rows = [row(tmp_path, "a.gguf"), row(tmp_path, "b.gguf")]
    for r in rows: r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    assert MR.offerable(rows) == [] and SR.prune_absent(rows)[1] == ["a", "b"]


def test_11_legacy_unknown_preview_has_no_write_and_exact_ids(tmp_path, monkeypatch, capsys):
    r = {"id": "legacy", "format": "gguf", "path": str(tmp_path / "gone.gguf"), "source": "download"}
    registry = tmp_path / "models.json"; registry.write_text('{"models":[{"id":"legacy","format":"gguf","path":"' + r["path"] + '","source":"download"}]}\n')
    before = registry.read_bytes()
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "scan_jan", lambda _: [])
    monkeypatch.setattr(SR, "scan_lmstudio", lambda _: [])
    monkeypatch.setattr(SR, "local_entries_for", lambda _: [])
    monkeypatch.setattr(SR, "scan_audio_hf_cache", lambda _: [])
    monkeypatch.setattr(SR, "MODEL_SOURCES", None)
    assert SR.main([]) == 0                 # ordinary startup cannot grant evidence authority
    assert SR.main(["--json"]) == 3
    lines = [x for x in capsys.readouterr().out.splitlines() if x]
    preview = __import__("json").loads(lines[0])
    assert len(lines) == 1 and preview["ambiguous_missing"] == ["legacy"]
    assert len(preview["confirmation_token"]) == 64
    assert registry.read_bytes() == before


def test_12_confirmation_requires_exact_reprobed_legacy_ids(tmp_path):
    r = {"id": "legacy", "format": "gguf", "path": str(tmp_path / "gone.gguf")}
    kept, removed, _, ambiguous = SR.prune_absent([r], details=True)
    assert kept == [r] and ambiguous == ["legacy"]
    kept, removed, _, ambiguous = SR.prune_absent([r], confirm_missing=["legacy"], details=True)
    assert kept == [] and removed == ["legacy"] and ambiguous == ["legacy"]


def test_12b_confirmation_token_rejects_same_id_with_a_different_path(tmp_path, monkeypatch, capsys):
    registry = tmp_path / "models.json"
    original = {"id": "same", "format": "gguf", "path": str(tmp_path / "missing-a.gguf"),
                "source": "download"}
    registry.write_text(json.dumps({"models": [original]}) + "\n")
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "scan_jan", lambda _: [])
    monkeypatch.setattr(SR, "scan_lmstudio", lambda _: [])
    monkeypatch.setattr(SR, "local_entries_for", lambda _: [])
    monkeypatch.setattr(SR, "scan_audio_hf_cache", lambda _: [])
    monkeypatch.setattr(SR, "MODEL_SOURCES", None)
    assert SR.main(["--json"]) == 3
    token = json.loads(capsys.readouterr().out)["confirmation_token"]
    replacement = dict(original, path=str(tmp_path / "missing-b.gguf"))
    registry.write_text(json.dumps({"models": [replacement]}) + "\n")
    before = registry.read_bytes()
    assert SR.main(["--json", "--confirm-missing-token", token]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "missing-entry confirmation changed"
    assert registry.read_bytes() == before


def test_13_audio_is_outside_the_chat_artifact_planner_even_with_confirmation(tmp_path):
    r = row(tmp_path); r.update(kind="audio", format="tts-gguf")
    os.unlink(r["path"])
    assert MR.artifact_evidence(r) is None
    assert SR.apply_artifact_evidence([r]) == [r]
    kept, removed, flagged, ambiguous = SR.prune_absent(
        [r], confirm_missing=[r["id"]], details=True)
    assert kept == [r] and removed == flagged == ambiguous == []


def test_13b_json_rescan_keeps_missing_download_audio_out_of_preview_and_confirmation(tmp_path, monkeypatch, capsys):
    audio = {"id": "voice", "kind": "audio", "format": "tts-gguf",
             "source": "download", "path": str(tmp_path / "missing.gguf")}
    registry = tmp_path / "models.json"
    registry.write_text(json.dumps({"models": [audio]}) + "\n")
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "scan_jan", lambda _: [])
    monkeypatch.setattr(SR, "scan_lmstudio", lambda _: [])
    monkeypatch.setattr(SR, "local_entries_for", lambda _: [])
    monkeypatch.setattr(SR, "scan_audio_hf_cache", lambda _: [])
    monkeypatch.setattr(SR, "MODEL_SOURCES", None)
    assert SR.main(["--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ambiguous_missing"] == [] and json.loads(registry.read_text())["models"] == [audio]
    before = registry.read_bytes()
    assert SR.main(["--json", "--confirm-missing-token", "0" * 64]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "missing-entry confirmation changed"
    assert registry.read_bytes() == before


def test_14_confirmation_body_is_exact_token_and_rejects_read_errors_or_extra_keys():
    from bridge.routers import model_rescan as R
    class Req:
        def __init__(self, raw): self.raw = raw
        async def body(self): return self.raw
    token = "a" * 64
    assert asyncio.run(R._rescan_body(Req(
        ('{"confirm_missing":true,"token":"' + token + '"}').encode())))[0] == token
    for raw in (b'{"confirm_missing":true,"token":"a"}',
                b'{"confirm_missing":true,"token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","extra":1}',
                b'{"confirm_missing":true,"ids":["a"]}'):
        assert asyncio.run(R._rescan_body(Req(raw)))[1].status_code == 400
    class BrokenReq:
        async def body(self): raise OSError("body unavailable")
    assert asyncio.run(R._rescan_body(BrokenReq()))[1].status_code == 400


def test_14b_router_only_maps_a_valid_preview_or_changed_confirmation_to_409(monkeypatch):
    from bridge.routers import model_rescan as R
    class Req:
        async def body(self): return b""
    monkeypatch.setattr(R, "_rescan_fanout", lambda: pytest.fail("preview fanned out"))
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=3, stdout='{"ok":false,"requires_confirmation":true,"ambiguous_missing":["a"],'
        '"confirmation_token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}', stderr=""))
    assert asyncio.run(R.api_models_rescan(Req())).status_code == 409
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3, stdout="not json", stderr=""))
    assert asyncio.run(R.api_models_rescan(Req())).status_code == 500


def test_14c_rescan_subprocess_does_not_block_the_asgi_event_loop(monkeypatch):
    from bridge.routers import model_rescan as R
    started, release = threading.Event(), threading.Event()
    fanout_started, fanout_release = threading.Event(), threading.Event()
    class Req:
        async def body(self): return b""
    def held_protect():
        started.set()
        assert release.wait(1)
        return []
    def held_run(*_, **__):
        return SimpleNamespace(returncode=0, stdout=(
            '{"ok":true,"count":0,"pruned":[],"flagged":[],'
            '"requires_confirmation":false,"ambiguous_missing":[]}'), stderr="")
    monkeypatch.setattr(R.subprocess, "run", held_run)
    monkeypatch.setattr(R, "_protect_ids", held_protect)
    monkeypatch.setattr(R, "file_state_forget", lambda: None)
    def held_fanout():
        fanout_started.set()
        assert fanout_release.wait(1)
        return "ok"
    monkeypatch.setattr(R, "_rescan_fanout", held_fanout)
    async def journey():
        pending = asyncio.create_task(R.api_models_rescan(Req()))
        assert await asyncio.to_thread(started.wait, 1)
        progressed = False
        async def other_request():
            nonlocal progressed
            await asyncio.sleep(0)
            progressed = True
        await other_request()
        assert progressed                         # would not run behind synchronous subprocess.run
        release.set()
        assert await asyncio.to_thread(fanout_started.wait, 1)
        progressed = False
        await other_request()
        assert progressed                         # fanout is also isolated from the ASGI loop
        fanout_release.set()
        return await pending
    assert asyncio.run(journey()).status_code == 200
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='{"ok":false,"error":"missing-entry confirmation changed"}', stderr=""))
    assert asyncio.run(R.api_models_rescan(Req())).status_code == 409
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"ok":true}', stderr=""))
    assert asyncio.run(R.api_models_rescan(Req())).status_code == 500


def test_15_panel_confirmation_is_exact_second_action_and_clears_stale_state():
    panel = open(os.path.join(ROOT, "bridge", "panel", "index.html")).read()
    assert "Remove missing entries" in panel and "JSON.stringify({confirm_missing:true,token:consent.token})" in panel
    assert "if(!confirm)rescanConsent=null" in panel and "rescanConsent=null;" in panel


def test_16_mlx_evidence_and_root_device_rules(tmp_path, monkeypatch):
    d = tmp_path / "mlx"; d.mkdir(); (d / "config.json").write_text('{"model_type":"unit-test"}')
    header = json.dumps({"w": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]}}).encode()
    (d / "model.safetensors").write_bytes(len(header).to_bytes(8, "little") + header + b"\0" * 4)
    r = {"id": "mlx", "format": "mlx", "path": str(d)}
    ev = evidence(r)
    assert ev["manifest"] == {"kind": "mlx", "files": ["config.json", "model.safetensors"]}
    r["artifact_evidence"] = ev; (d / "model.safetensors").unlink()
    assert MR.source_availability(r)["state"] == "available"  # root / same device
    monkeypatch.setattr(MR.os.path, "ismount", lambda _: False)
    assert MR.source_availability(r, {"state": "missing"})["state"] == "available"  # / is special


def test_17_source_permission_and_loop_are_unknown(tmp_path, monkeypatch):
    r = row(tmp_path); r["artifact_evidence"] = evidence(r); os.unlink(r["path"])
    monkeypatch.setattr(MR.os, "stat", lambda _: (_ for _ in ()).throw(PermissionError()))
    assert MR.source_availability(r, {"state": "missing"})["state"] == "unknown"
    monkeypatch.setattr(MR.os, "stat", lambda _: (_ for _ in ()).throw(OSError("loop")))
    assert MR.source_availability(r, {"state": "missing"})["state"] == "unknown"


def test_18_merge_evidence_is_source_and_path_identity_safe(tmp_path):
    old = row(tmp_path, "old.gguf"); old.update(source="local", artifact_evidence=evidence(old))
    same = dict(old); same.pop("artifact_evidence")
    other = row(tmp_path, "other.gguf"); other.update(id="old", source="local")
    foreign = dict(same, source="lmstudio-import")
    assert SR.merge([old], [], [], [same])[0]["artifact_evidence"] == old["artifact_evidence"]
    assert "artifact_evidence" not in SR.merge([old], [], [], [other])[0]
    assert "artifact_evidence" not in SR.merge([old], [], [foreign], [])[0]


def test_19_atomic_write_failure_preserves_original_bytes(tmp_path, monkeypatch):
    path = tmp_path / "models.json"; path.write_bytes(b'{"models":[{"id":"old"}]}\n'); before = path.read_bytes()
    monkeypatch.setattr(SR.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no replace")))
    with pytest.raises(OSError): SR.write(str(path), [])
    assert path.read_bytes() == before


def test_20_audio_and_live_yaml_are_outside_transaction(tmp_path):
    audio = {"id": "voice", "kind": "audio", "format": "tts-gguf", "path": str(tmp_path / "missing")}
    yaml = tmp_path / "motdeck.yaml"; yaml.write_text("runner:\n  model: keep\n")
    assert SR.prune_absent([audio])[0] == [audio]
    assert yaml.read_text() == "runner:\n  model: keep\n"


def test_21_stale_gone_debounce_cannot_flag_a_reappeared_artifact(tmp_path, monkeypatch):
    from bridge.routers import models as R
    data = tmp_path / "data"; data.mkdir()
    registry = data / "models.json"
    registry.write_text(json.dumps({"models": [{"id": "back", "format": "gguf", "path": "/returned.gguf"}]}) + "\n")
    monkeypatch.setattr(R, "ROOT", tmp_path)
    monkeypatch.setattr(R, "artifact_probe", lambda _: {"state": "ready"})
    monkeypatch.setattr(R, "source_availability", lambda *_: {"state": "available"})
    R._persist_absent({"back": "gone"})
    assert "absent" not in json.loads(registry.read_text())["models"][0]


def test_22_evidence_must_match_the_current_path_and_format_before_authorizing_deletion(tmp_path):
    r = row(tmp_path, "observed.gguf")
    observed_probe = MR.artifact_probe(r)
    r["artifact_evidence"] = MR.artifact_evidence(r, observed_probe)
    os.unlink(r["path"])
    r["path"] = str(tmp_path / "other-missing.gguf")
    verdict = MR.source_availability(r, {"state": "missing"})
    assert verdict["state"] == "unknown" and verdict["reason"] == "identity-mismatch"
    assert MR.artifact_evidence(r, observed_probe) is None
    r["path"] = r["artifact_evidence"]["real_path"]
    r["format"] = "mlx"
    verdict = MR.source_availability(r, {"state": "missing"})
    assert verdict["state"] == "unknown" and verdict["reason"] == "identity-mismatch"
    assert MR.artifact_evidence(r, observed_probe) is None


def test_23_registry_lock_serializes_cross_process_read_modify_replace(tmp_path):
    registry = tmp_path / "models.json"; registry.write_text('{"models": []}\n')
    marker = tmp_path / "entered"
    program = '''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from bridge.core.modelreg import registry_lock
path, ident, marker, delay = sys.argv[2:]
with registry_lock(path):
    if marker: open(marker, "w").close()
    data = json.load(open(path))
    time.sleep(float(delay))
    data["models"].append({"id": ident})
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w"))
    os.replace(tmp, path)
'''
    env = dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path / "pycache"))
    first = subprocess.Popen([sys.executable, "-c", program, ROOT, str(registry), "one", str(marker), ".15"], env=env)
    for _ in range(100):
        if marker.exists(): break
        time.sleep(.01)
    assert marker.exists()
    second = subprocess.Popen([sys.executable, "-c", program, ROOT, str(registry), "two", "", "0"], env=env)
    assert first.wait(3) == second.wait(3) == 0
    assert {m["id"] for m in json.loads(registry.read_text())["models"]} == {"one", "two"}
    for source in ("scripts/seed_registry.py", "bridge/routers/models.py", "bridge/routers/downloads.py"):
        assert "registry_lock" in open(os.path.join(ROOT, source)).read()


def test_24_second_unchanged_explicit_rescan_is_byte_stable_after_evidence(tmp_path, monkeypatch, capsys):
    r = row(tmp_path, "stable.gguf")
    registry = tmp_path / "models.json"
    registry.write_text(json.dumps({"models": [r]}) + "\n")
    monkeypatch.setattr(SR, "REGISTRY_PATH", str(registry))
    monkeypatch.setattr(SR, "scan_jan", lambda _: [])
    monkeypatch.setattr(SR, "scan_lmstudio", lambda _: [])
    monkeypatch.setattr(SR, "local_entries_for", lambda _: [])
    monkeypatch.setattr(SR, "scan_audio_hf_cache", lambda _: [])
    assert SR.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    first = registry.read_bytes()
    assert json.loads(first)["models"][0]["artifact_evidence"]["v"] == 1
    assert SR.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert registry.read_bytes() == first


def test_25_corrupt_utf8_registry_cannot_authorize_replacement(tmp_path):
    registry = tmp_path / "models.json"
    registry.write_bytes(b'{"models": \xff}')
    before = registry.read_bytes()
    with pytest.raises(UnicodeError):
        SR.write(str(registry), [])
    assert registry.read_bytes() == before
