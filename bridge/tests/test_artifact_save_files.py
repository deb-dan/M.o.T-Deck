"""Canvas Save must preserve existing exports even at collision boundaries."""
import asyncio
import json
from pathlib import Path

import pytest

from bridge.routers import misc


class SaveRequest:
    def __init__(self, content="new content"):
        self.content = content

    async def json(self):
        return {"filename": "notes.txt", "content": self.content}


@pytest.fixture
def exports(tmp_path, monkeypatch):
    import os
    original = os.path.expanduser
    monkeypatch.setattr(os.path, "expanduser",
                        lambda path: str(tmp_path) if path == "~" else original(path))
    directory = tmp_path / "Downloads" / "motdeck-artifacts"
    directory.mkdir(parents=True)
    return directory


def test_exhausted_suffixes_never_overwrite_prior_exports(exports):
    originals = [exports / "notes.txt"] + [exports / f"notes ({n}).txt" for n in range(1, 100)]
    for index, path in enumerate(originals):
        path.write_text(f"previous export {index}")
    response = asyncio.run(misc.artifact_save(SaveRequest()))
    assert [p.read_text() for p in originals] == [f"previous export {i}" for i in range(100)]
    assert response.status_code == 409
    assert json.loads(response.body)["ok"] is False


def test_dangling_symlink_is_a_collision_not_an_export_target(exports):
    outside = exports.parent / "other-document.txt"
    (exports / "notes.txt").symlink_to(outside)
    response = asyncio.run(misc.artifact_save(SaveRequest()))
    assert not outside.exists()
    assert response.status_code == 200
    assert Path(json.loads(response.body)["path"]).read_text() == "new content"
    assert (exports / "notes.txt").is_symlink()


def test_invalid_unicode_does_not_leave_an_empty_export(exports):
    response = asyncio.run(misc.artifact_save(SaveRequest("broken\ud800")))
    assert response.status_code == 400
    assert not list(exports.iterdir())


def test_existing_export_retains_contents_and_next_suffix_is_reported(exports):
    (exports / "notes.txt").write_text("original")
    response = asyncio.run(misc.artifact_save(SaveRequest("Hello, café 🌿")))
    assert response.status_code == 200
    saved = Path(json.loads(response.body)["path"])
    assert saved == exports / "notes (1).txt"
    assert saved.read_text() == "Hello, café 🌿"
    assert (exports / "notes.txt").read_text() == "original"
