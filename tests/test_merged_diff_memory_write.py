"""A failed memory write must be reported, not swallowed.

_write_memory caught every exception and returned None, so a merge that never
reached disk was indistinguishable from one that did -- the recovery memory
could be arbitrarily stale while looking healthy. These tests pin the
True/False contract, the logging.warning on failure, and the atomic replace.
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))
import merged_diff_memory as mdm


@pytest.fixture()
def memfile(tmp_path, monkeypatch):
    """Point the module at a throwaway memory file."""
    d = tmp_path / "memory"
    monkeypatch.setattr(mdm, "MEMORY_DIR", d)
    monkeypatch.setattr(mdm, "MERGED_DIFF_FILE", d / "merged_diff_memory.json")
    return d / "merged_diff_memory.json"


def test_returns_true_and_persists_on_success(memfile):
    data = [{"commit": "abc123", "branch": "agent/x"}]
    assert mdm.write_memory_file(data) is True
    assert json.loads(memfile.read_text())["merges"] == data


def test_returns_false_on_write_error(memfile, monkeypatch):
    monkeypatch.setattr(mdm.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert mdm.write_memory_file([{"commit": "abc"}]) is False


def test_failure_is_logged_as_a_warning(memfile, monkeypatch, caplog):
    monkeypatch.setattr(mdm.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with caplog.at_level(logging.WARNING):
        mdm.write_memory_file([{"commit": "abc"}])
    assert any(r.levelno == logging.WARNING and "disk full" in r.getMessage()
               for r in caplog.records)


def test_failed_write_leaves_no_temp_file_behind(memfile, monkeypatch):
    monkeypatch.setattr(mdm.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    mdm.write_memory_file([{"commit": "abc"}])
    leftovers = list(memfile.parent.glob("*.tmp")) if memfile.parent.exists() else []
    assert leftovers == []


def test_failed_write_does_not_corrupt_the_previous_file(memfile, monkeypatch):
    """Atomic replace: a good file survives a later failed write intact."""
    good = [{"commit": "good", "branch": "b"}]
    assert mdm.write_memory_file(good) is True

    monkeypatch.setattr(mdm.json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert mdm.write_memory_file([{"commit": "bad"}]) is False
    assert json.loads(memfile.read_text())["merges"] == good


def test_history_is_capped(memfile):
    data = [{"commit": f"c{i}"} for i in range(mdm.MAX_STORED_MERGES + 25)]
    assert mdm.write_memory_file(data) is True
    stored = json.loads(memfile.read_text())["merges"]
    assert len(stored) == mdm.MAX_STORED_MERGES
    assert stored[-1]["commit"] == data[-1]["commit"]


def test_entry_missing_commit_key_does_not_abort_capture(memfile, monkeypatch):
    """Previously m["commit"] raised KeyError and dropped the whole capture."""
    mdm.write_memory_file([{"branch": "orphan"}])
    monkeypatch.setattr(mdm, "_safe_run", lambda *a, **k: "x")
    assert mdm.capture_merge("newsha", "agent/y", ".") is True
    assert any(m.get("commit") == "newsha"
               for m in json.loads(memfile.read_text())["merges"])


def test_capture_merge_reports_a_failed_write(memfile, monkeypatch):
    monkeypatch.setattr(mdm, "_safe_run", lambda *a, **k: "x")
    monkeypatch.setattr(mdm, "_write_memory", lambda merges: False)
    assert mdm.capture_merge("sha", "agent/z", ".") is False


def test_duplicate_capture_is_idempotent_and_reports_true(memfile, monkeypatch):
    monkeypatch.setattr(mdm, "_safe_run", lambda *a, **k: "x")
    assert mdm.capture_merge("dupe", "agent/a", ".") is True
    assert mdm.capture_merge("dupe", "agent/a", ".") is True
    merges = json.loads(memfile.read_text())["merges"]
    assert [m["commit"] for m in merges].count("dupe") == 1


def test_invalidate_reports_success(memfile):
    mdm.write_memory_file([{"commit": "x"}])
    assert mdm.invalidate() is True
    assert json.loads(memfile.read_text())["merges"] == []
