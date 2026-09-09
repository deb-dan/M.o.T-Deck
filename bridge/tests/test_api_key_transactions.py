"""Named-key edits preserve concurrent requests and private on-disk state."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from bridge.routers import apikeys as K


@pytest.fixture
def key_root(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    return tmp_path / "data"


def test_concurrent_mints_keep_every_returned_key(key_root, monkeypatch):
    original = K.read_store
    def slow_read():
        value = original()
        time.sleep(.03)
        return value
    monkeypatch.setattr(K, "read_store", slow_read)
    start = threading.Barrier(4)
    def mint(index):
        start.wait(timeout=2)
        return K.api_keys_mint(K.MintBody(name=f"client-{index}"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        issued = list(pool.map(mint, range(4)))
    stored = original()["keys"]
    assert {row["id"] for row in stored} == {row["id"] for row in issued}
    assert {row["key"] for row in stored} == {row["key"] for row in issued}
    assert set(K.keyfile_text().splitlines()[2:]) == {row["key"] for row in issued}


def test_stale_temporary_symlink_cannot_receive_a_secret(key_root):
    outside = key_root.parent / "external"
    outside.write_text("untouched")
    (key_root / "api_keys.json.tmp").symlink_to(outside)
    K.api_keys_mint(K.MintBody(name="client"))
    assert outside.read_text() == "untouched"
    assert (key_root / "api_keys.json").stat().st_mode & 0o777 == 0o600


def test_failed_authoritative_commit_keeps_previous_key_set(key_root, monkeypatch):
    first = K.api_keys_mint(K.MintBody(name="existing"))
    original = K._atomic_secret
    def reject_store(path, text):
        if path.name == "api_keys.json":
            raise OSError("simulated storage failure")
        return original(path, text)
    monkeypatch.setattr(K, "_atomic_secret", reject_store)
    with pytest.raises(OSError, match="simulated"):
        K.api_keys_mint(K.MintBody(name="never issued"))
    assert [row["id"] for row in K.read_store()["keys"]] == [first["id"]]
    assert K.keyfile_text() == (key_root / "api_keys.keys").read_text()


def test_failed_derived_write_does_not_create_an_unrevealed_key(key_root, monkeypatch):
    first = K.api_keys_mint(K.MintBody(name="existing"))
    before = (key_root / "api_keys.json").read_bytes()
    original = K._atomic_secret
    def reject_keyfile(path, text):
        if path.name == "api_keys.keys":
            raise OSError("simulated storage failure")
        return original(path, text)
    monkeypatch.setattr(K, "_atomic_secret", reject_keyfile)
    with pytest.raises(OSError, match="simulated"):
        K.api_keys_mint(K.MintBody(name="never issued"))
    assert (key_root / "api_keys.json").read_bytes() == before
    assert [row["id"] for row in K.read_store()["keys"]] == [first["id"]]


def test_full_length_duplicate_names_keep_numeric_suffix():
    name = "x" * K.NAME_MAX
    assert K._clean_name(name, [name]) == "x" * (K.NAME_MAX - 4) + " (2)"


@pytest.mark.parametrize("unavailable", ["NaN", "+Inf", "-Inf"])
def test_nonfinite_metrics_do_not_hide_valid_counters(unavailable):
    assert K.parse_metrics(f"llamacpp:predicted_tokens_seconds {unavailable}\n"
                           "llamacpp:prompt_tokens_total 37\n") == {"prompt_tokens": 37}
