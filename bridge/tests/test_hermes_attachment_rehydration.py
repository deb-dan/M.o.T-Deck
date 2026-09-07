from __future__ import annotations

import os

from bridge.core import hermesattachments as H


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "0557bfabd40000000049454e44ae426082")


def test_managed_image_is_projected_without_exposing_its_path(monkeypatch, tmp_path):
    home = tmp_path / "Hermes Home"
    images = home / "images"
    images.mkdir(parents=True)
    picture = images / "one.png"
    picture.write_bytes(PNG)
    monkeypatch.setenv("HERMES_HOME", str(home))

    text, attachments, unavailable = H.project_message(
        f"caption\n@image:`{picture}`")
    assert text == "caption" and unavailable == []
    assert len(attachments) == 1 and attachments[0]["name"] == "one.png"
    assert str(picture) not in repr(attachments)
    raw, mime, name = H.open_image(attachments[0]["hermes_id"])
    assert raw == PNG and mime == "image/png" and name == "one.png"


def test_outside_missing_and_symlink_refs_never_become_host_reads(monkeypatch, tmp_path):
    home = tmp_path / "home"
    images = home / "images"
    images.mkdir(parents=True)
    outside = tmp_path / "private.png"
    outside.write_bytes(PNG)
    link = images / "link.png"
    link.symlink_to(outside)
    monkeypatch.setenv("HERMES_HOME", str(home))

    text, attachments, unavailable = H.project_message(
        f"hello\n@image:{outside}\n@image:{link}\n@image:{images / 'gone.png'}")
    assert text == "hello" and attachments == []
    assert unavailable == ["private.png", "link.png", "gone.png"]


def test_registered_inode_change_fails_closed(monkeypatch, tmp_path):
    home = tmp_path / "home"
    images = home / "images"
    images.mkdir(parents=True)
    picture = images / "one.png"
    picture.write_bytes(PNG)
    monkeypatch.setenv("HERMES_HOME", str(home))
    _text, attachments, _missing = H.project_message(f"@image:{picture}")
    token = attachments[0]["hermes_id"]
    replacement = images / "replacement.png"
    replacement.write_bytes(PNG + b"changed")
    os.replace(replacement, picture)
    assert H.open_image(token) is None


def test_hard_links_and_fake_image_bytes_are_refused(monkeypatch, tmp_path):
    home = tmp_path / "home"
    images = home / "images"
    images.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    hard = images / "hard.png"
    os.link(outside, hard)
    fake = images / "fake.png"
    fake.write_bytes(b"this is not a png")
    monkeypatch.setenv("HERMES_HOME", str(home))
    _text, attachments, unavailable = H.project_message(
        f"@image:{hard}\n@image:{fake}")
    assert [row["name"] for row in attachments] == ["fake.png"]
    assert unavailable == ["hard.png"]
    assert H.open_image(attachments[0]["hermes_id"]) is None
