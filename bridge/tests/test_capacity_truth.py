"""A measured full disk must be reported as full."""
from bridge.core import comfycur


def test_full_disk_is_reported_as_full():
    assert comfycur.disk_verdict(1024, 0)["level"] == "no"
    assert comfycur.disk_verdict(1024, None)["level"] == "unknown"
