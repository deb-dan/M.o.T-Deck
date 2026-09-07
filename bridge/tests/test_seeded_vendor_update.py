"""Seeded vendor upgrades mutate only Git-owned, unchanged paths."""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import scripts.update_seeded_vendor as updater
from scripts.update_seeded_vendor import Refusal, apply


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _fixture(tmp_path: Path):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", repo], check=True)
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "same.txt").write_text("same\n")
    (repo / "change.txt").write_text("old\n")
    (repo / "retire.txt").write_text("retire\n")
    (repo / "bin.sh").write_text("#!/bin/sh\n")
    (repo / "bin.sh").chmod(0o755)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "old")
    old = _git(repo, "rev-parse", "HEAD")
    (repo / "change.txt").write_text("new\n")
    (repo / "retire.txt").unlink()
    (repo / "added.txt").write_text("added\n")
    (repo / "bin.sh").chmod(0o644)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "new")
    new = _git(repo, "rev-parse", "HEAD")
    live = tmp_path / "live"
    subprocess.run(["git", "-C", str(repo), "archive", old, "-o", str(tmp_path / "old.tar")], check=True)
    live.mkdir()
    subprocess.run(["tar", "-xf", str(tmp_path / "old.tar"), "-C", str(live)], check=True)
    return repo, live, old, new


def test_check_is_read_only_and_apply_preserves_untracked(tmp_path):
    repo, live, old, new = _fixture(tmp_path)
    (live / "data").mkdir()
    (live / "data" / "user.db").write_text("mine")
    before = sorted(p.relative_to(live) for p in live.rglob("*"))
    summary, backup = apply(repo, live, old, new, tmp_path / "backups", True)
    assert backup is None and summary["changed_paths"] == 4
    assert (live / "change.txt").read_text() == "old\n"
    assert before == sorted(p.relative_to(live) for p in live.rglob("*"))

    summary, backup = apply(repo, live, old, new, tmp_path / "backups", False)
    assert summary == {"old": old, "new": new, "changed_paths": 4,
                       "replaced": 2, "added": 1, "retired": 1}
    assert backup and (backup / "manifest.json").is_file()
    assert (live / "change.txt").read_text() == "new\n"
    assert not (live / "retire.txt").exists()
    assert (live / "added.txt").read_text() == "added\n"
    assert not ((live / "bin.sh").stat().st_mode & 0o111)
    assert (live / "data" / "user.db").read_text() == "mine"


def test_modified_tracked_path_refuses_before_any_write(tmp_path):
    repo, live, old, new = _fixture(tmp_path)
    (live / "change.txt").write_text("operator edit\n")
    with pytest.raises(Refusal, match="change.txt"):
        apply(repo, live, old, new, tmp_path / "backups", False)
    assert (live / "change.txt").read_text() == "operator edit\n"
    assert (live / "retire.txt").read_text() == "retire\n"
    assert not (live / "added.txt").exists()


def test_new_upstream_path_cannot_overwrite_untracked_file(tmp_path):
    repo, live, old, new = _fixture(tmp_path)
    (live / "added.txt").write_text("user file\n")
    with pytest.raises(Refusal, match="added.txt"):
        apply(repo, live, old, new, tmp_path / "backups", False)
    assert (live / "added.txt").read_text() == "user file\n"


def test_symlink_parent_escape_refuses(tmp_path):
    repo, live, old, _new = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "nested").mkdir()
    (repo / "nested" / "owned.txt").write_text("new\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "nested")
    new = _git(repo, "rev-parse", "HEAD")
    (live / "nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Refusal, match="symlink parent"):
        apply(repo, live, old, new, tmp_path / "backups", False)
    assert not (outside / "owned.txt").exists()


def test_postcondition_failure_rolls_back_every_planned_path(tmp_path, monkeypatch):
    repo, live, old, new = _fixture(tmp_path)
    (live / "data").mkdir()
    (live / "data" / "user.db").write_text("mine")
    real_read = updater._read_live
    new_tree = updater._tree(repo, new)
    injected = False

    def fail_one_postcondition(path):
        nonlocal injected
        value = real_read(path)
        if (not injected and path.name == "change.txt"
                and updater._same(value, new_tree["change.txt"])):
            injected = True
            return {"kind": "file", "mode": 0o644, "data": b"not-the-new-tree\n"}
        return value

    monkeypatch.setattr(updater, "_read_live", fail_one_postcondition)
    with pytest.raises(Refusal, match="post-write verification failed"):
        apply(repo, live, old, new, tmp_path / "backups", False)

    assert injected
    assert (live / "change.txt").read_text() == "old\n"
    assert (live / "retire.txt").read_text() == "retire\n"
    assert not (live / "added.txt").exists()
    assert (live / "bin.sh").stat().st_mode & 0o111
    assert (live / "data" / "user.db").read_text() == "mine"
