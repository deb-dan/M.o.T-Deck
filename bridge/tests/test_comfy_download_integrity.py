import asyncio
from types import SimpleNamespace

from bridge.core import comfycur
from bridge.routers import comfy
from bridge.routers.comfy import _hf_lfs_metadata


def _response(url, headers, history=None):
    return SimpleNamespace(
        request=SimpleNamespace(url=url), headers=headers, history=history or [],
    )


def test_huggingface_lfs_headers_are_content_evidence_not_the_cdn_etag():
    content_sha = "a" * 64
    origin = _response(
        "https://huggingface.co/org/repo/resolve/main/model.safetensors",
        {"x-linked-etag": f'"{content_sha}"', "x-linked-size": "1234",
         "x-xet-hash": "b" * 64},
    )
    final = _response(
        "https://cdn.example/model", {"etag": '"' + "c" * 64 + '"'}, [origin],
    )
    assert _hf_lfs_metadata(final, str(origin.request.url)) == {
        "bytes": 1234, "sha256": content_sha, "source": "huggingface-lfs",
    }


def test_digest_evidence_is_rejected_from_non_hf_or_incomplete_headers():
    forged = _response(
        "https://example.invalid/model", {"x-linked-etag": "a" * 64,
                                           "x-linked-size": "1234"},
    )
    assert _hf_lfs_metadata(forged, str(forged.request.url)) is None
    incomplete = _response(
        "https://huggingface.co/org/repo/resolve/main/model",
        {"x-linked-etag": "a" * 64},
    )
    assert _hf_lfs_metadata(incomplete, str(incomplete.request.url)) is None


def test_richer_metadata_reuses_the_existing_size_cache():
    url = "https://huggingface.co/org/repo/resolve/main/model"
    old = comfycur.SIZES.get(url)
    try:
        comfycur.SIZES[url] = {"bytes": 456, "sha256": "d" * 64,
                               "source": "huggingface-lfs"}
        assert comfycur.size_known(url) == 456
        assert comfycur.digest_known(url) == "d" * 64
        comfycur.SIZES[url] = 789
        assert comfycur.size_known(url) == 789
        assert comfycur.digest_known(url) is None
    finally:
        if old is None:
            comfycur.SIZES.pop(url, None)
        else:
            comfycur.SIZES[url] = old


def test_download_rechecks_mutable_hf_identity_before_writing(tmp_path, monkeypatch):
    url = "https://huggingface.co/org/repo/resolve/main/model"
    origin = _response(url, {"x-linked-etag": "b" * 64,
                             "x-linked-size": "1234"})

    class Transfer:
        status_code = 200
        headers = {"content-length": "1234"}
        request = SimpleNamespace(url="https://cdn.example/model")
        history = [origin]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def aiter_bytes(self, _size):
            raise AssertionError("changed source must be rejected before its first byte")
            yield b""  # pragma: no cover

    monkeypatch.setattr(comfy, "_DL", SimpleNamespace(stream=lambda *_a, **_k: Transfer()))
    monkeypatch.setattr(comfy, "publish", lambda *_a, **_k: None)
    dest = tmp_path / "model"
    entry = {
        "id": "d1", "pick": "wf:test", "title": "test", "state": "downloading",
        "error": None, "files": [{
            "directory": "diffusion_models", "name": "model", "url": url,
            "dest": str(dest), "bytes": 1234, "sha256": "a" * 64,
            "done": 0, "state": "queued", "verify": "size + Hugging Face LFS sha256",
        }],
    }
    monkeypatch.setitem(comfy.CDL, "d1", entry)
    asyncio.run(comfy._run_cdl("d1"))
    assert entry["state"] == "error"
    assert "current content digest" in entry["error"]
    assert not dest.exists() and not (tmp_path / "model.part").exists()
