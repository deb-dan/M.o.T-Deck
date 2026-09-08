"""Requirements follow every active loader input, not its first weight only."""
import pytest

from bridge.core import comfycur as C
from bridge.tests.model_fixture import safetensors_bytes


@pytest.mark.parametrize("loader,count", [("DualCLIPLoader", 2), ("TripleCLIPLoader", 3),
                                         ("QuadrupleCLIPLoader", 4)])
@pytest.mark.parametrize("keyed", [False, True])
def test_catalogue_keeps_missing_encoders_in_multifile_loaders(tmp_path, monkeypatch, loader, count, keyed):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    names = [f"encoder-{n}.safetensors" for n in range(count)]
    values = names + ["sd3", "default"]
    if keyed:
        values = {**{f"clip_name{n + 1}": name for n, name in enumerate(names)},
                  "type": "sd3", "device": "default"}
    graph = {"nodes": [{"id": 1, "type": loader, "widgets_values": values,
                         "properties": {"models": [{"name": name, "directory": "text_encoders",
                                                    "url": f"https://example.invalid/{name}"}
                                                   for name in names]}}], "links": []}
    directory = C.models_dir() / "text_encoders"
    directory.mkdir(parents=True)
    (directory / names[0]).write_bytes(safetensors_bytes())
    files = C.workflow_files("test-template", graph)
    assert [row["name"] for row in files] == names
    assert [row["name"] for row in files if not row["present"]] == names[1:]
    graph["nodes"][0]["mode"] = 2
    assert C.workflow_files("test-template", graph) == []
