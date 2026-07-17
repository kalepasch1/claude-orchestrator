"""Tests for resource_governor set_throttle / current_limit — no real disk I/O."""

import sys
import os
import types

# Ensure runner/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))

# Stub modules that resource_governor imports at top level
for mod_name in ("db", "events"):
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        stub.select = lambda *a, **kw: []
        stub.insert = lambda *a, **kw: None
        stub.emit = lambda *a, **kw: None
        sys.modules[mod_name] = stub

import resource_governor  # noqa: E402


def test_set_throttle_clamps_to_ceiling(tmp_path, monkeypatch):
    tf = str(tmp_path / "throttle")
    monkeypatch.setattr(resource_governor, "THROTTLE_FILE", tf)
    monkeypatch.setenv("MAX_PARALLEL_CEILING", "8")

    result = resource_governor.set_throttle(999)
    assert result == 8, "should clamp to ceiling"


def test_set_throttle_clamps_floor_to_one(tmp_path, monkeypatch):
    tf = str(tmp_path / "throttle")
    monkeypatch.setattr(resource_governor, "THROTTLE_FILE", tf)
    monkeypatch.setenv("MAX_PARALLEL_CEILING", "8")

    result = resource_governor.set_throttle(-5)
    assert result == 1, "should clamp minimum to 1"


def test_current_limit_reads_persisted_value(tmp_path, monkeypatch):
    tf = str(tmp_path / "throttle")
    monkeypatch.setattr(resource_governor, "THROTTLE_FILE", tf)
    monkeypatch.setenv("MAX_PARALLEL_CEILING", "12")

    resource_governor.set_throttle(4)
    assert resource_governor.current_limit() == 4


def test_current_limit_falls_back_to_ceiling(tmp_path, monkeypatch):
    tf = str(tmp_path / "nonexistent" / "throttle")
    monkeypatch.setattr(resource_governor, "THROTTLE_FILE", tf)
    monkeypatch.setenv("MAX_PARALLEL_CEILING", "10")

    assert resource_governor.current_limit() == 10, "missing file -> ceiling"
