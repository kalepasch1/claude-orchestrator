#!/usr/bin/env python3
"""`merged_diff_memory.write_memory_file` — True when the write lands, False on any error.

The function is the public entry point "for callers that need to know whether the write
actually landed (e.g. before reporting a merge as recorded)", and its own docstring
explains why the boolean exists: a silently-dropped write left the recovery memory looking
populated while it was actually stale, which is worse than an empty one.

Nothing tested it. `grep -rl write_memory_file runner/tests/` returned nothing, so the
return value that callers branch on — and the fail-soft promise underneath it — were
unpinned. These pin both, plus the atomic-replace behaviour that stops a crash mid-write
leaving a truncated file `_read_memory` would discard wholesale.

pytest, per the task.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_memory as mdm


@pytest.fixture
def memory_in(tmp_path, monkeypatch):
    """Point the module's memory file at a temp dir. Returns the file path."""
    target = tmp_path / "merged_diffs.json"
    monkeypatch.setattr(mdm, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", target)
    return target


VALID = [{"commit": "abc123", "branch": "agent/x", "files": ["a.py"]}]


# ── success ───────────────────────────────────────────────────────────────────────────

def test_returns_true_for_valid_memory_data(memory_in):
    assert mdm.write_memory_file(VALID) is True
    assert memory_in.exists()


def test_the_data_is_actually_readable_back(memory_in):
    # True must mean the bytes landed, not merely that nothing raised.
    mdm.write_memory_file(VALID)
    stored = json.loads(memory_in.read_text())
    assert stored["merges"][0]["commit"] == "abc123"


def test_an_empty_list_is_a_legitimate_write(memory_in):
    # _invalidate_tracking() clears memory by writing []; that is success, not failure.
    assert mdm.write_memory_file([]) is True
    assert json.loads(memory_in.read_text())["merges"] == []


def test_missing_parent_directory_is_created(memory_in, tmp_path, monkeypatch):
    nested = tmp_path / "deep" / "nested"
    monkeypatch.setattr(mdm, "MEMORY_DIR", nested)
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", nested / "merged_diffs.json")
    assert mdm.write_memory_file(VALID) is True


def test_the_store_is_capped(memory_in):
    # Unbounded growth is its own outage; the cap is part of the contract.
    assert mdm.write_memory_file([{"commit": str(i)} for i in range(mdm.MAX_STORED_MERGES + 50)])
    assert len(json.loads(memory_in.read_text())["merges"]) == mdm.MAX_STORED_MERGES


def test_no_temp_file_is_left_behind(memory_in):
    mdm.write_memory_file(VALID)
    assert not list(memory_in.parent.glob("*.tmp"))


# ── failure ───────────────────────────────────────────────────────────────────────────

def test_returns_false_when_the_write_fails(memory_in, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr("builtins.open", boom)
    assert mdm.write_memory_file(VALID) is False


def test_returns_false_when_the_data_is_not_serialisable(memory_in):
    assert mdm.write_memory_file([{"commit": object()}]) is False


def test_returns_false_when_the_replace_fails(memory_in, monkeypatch):
    # The bytes are written but the atomic move fails — the caller must not be told it
    # succeeded, because the real file is still the old one.
    monkeypatch.setattr(mdm.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert mdm.write_memory_file(VALID) is False


def test_a_failed_write_is_logged_as_a_warning(memory_in, monkeypatch, caplog):
    """Fail-soft, but never silent — the whole point of the boolean."""
    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    with caplog.at_level("WARNING", logger=mdm.logger.name):
        assert mdm.write_memory_file(VALID) is False
    assert any("could not write" in r.message or "could not write" in r.getMessage()
               for r in caplog.records), caplog.text


def test_it_never_raises_whatever_it_is_handed(memory_in):
    # Fail-soft is the module's stated contract: a memory write must not wedge the caller.
    for data in (None, "not-a-list", 42, [None], [{"a": {1, 2}}]):
        assert mdm.write_memory_file(data) in (True, False)


def test_a_failed_write_leaves_no_temp_file(memory_in, monkeypatch):
    monkeypatch.setattr(mdm.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    mdm.write_memory_file(VALID)
    assert not list(memory_in.parent.glob("*.tmp"))


def test_a_failed_write_does_not_corrupt_the_previous_file(memory_in, monkeypatch):
    # Atomic replace: the old memory survives a failed rewrite intact.
    mdm.write_memory_file(VALID)
    before = memory_in.read_text()
    monkeypatch.setattr(mdm.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert mdm.write_memory_file([{"commit": "later"}]) is False
    assert memory_in.read_text() == before
