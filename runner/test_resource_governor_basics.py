"""Tests for resource_governor basic functions — verify disk_pct, effective_floor_gb, can_claim."""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock db module before importing resource_governor
mock_db = types.ModuleType("db")
mock_db.select = lambda *a, **kw: []
mock_db.insert = lambda *a, **kw: None
sys.modules.setdefault("db", mock_db)

import resource_governor  # noqa: E402


def test_disk_pct_returns_tuple():
    """disk_pct() should return a (used_pct, free_gb) tuple."""
    result = resource_governor.disk_pct("/")
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2
    used_pct, free_gb = result
    assert 0 <= used_pct <= 100, f"Used pct out of range: {used_pct}"
    assert free_gb >= 0, f"Free GB negative: {free_gb}"


def test_effective_floor_gb_reads_env(monkeypatch=None):
    """effective_floor_gb() should respect RAM_FLOOR_GB env var."""
    old = os.environ.get("RAM_FLOOR_GB")
    try:
        os.environ["RAM_FLOOR_GB"] = "4.5"
        assert resource_governor.effective_floor_gb() == 4.5
    finally:
        if old is None:
            os.environ.pop("RAM_FLOOR_GB", None)
        else:
            os.environ["RAM_FLOOR_GB"] = old


def test_can_claim_returns_tuple():
    """can_claim() should return (bool, str) tuple."""
    ok, reason = resource_governor.can_claim(0)
    assert isinstance(ok, bool)
    assert isinstance(reason, str)


if __name__ == "__main__":
    test_disk_pct_returns_tuple()
    test_effective_floor_gb_reads_env()
    test_can_claim_returns_tuple()
    print("All resource_governor basic tests passed.")
