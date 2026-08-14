"""merged-diff-memory: the diffs must survive the merges that come after them.

The existing suites test the two halves separately — `test_merged_diff_memory.py` covers
the persisted merge metadata, `test_merged_diff_memory_spec.py` covers the in-memory diff
cache — but nothing exercises the property the feature is actually named for: a diff
remembered at merge N is still there at merge N+k, and the record of merge N is still
there until rotation legitimately evicts it.

Each test below pins a behaviour whose docstring in `merged_diff_memory.py` records it as
a fixed defect, so each fails against the pre-fix implementation:

  * `get_recent_merges(0)` returning everything, because `merges[-0:]` is `merges[0:]`;
  * `capture_merge` aborting with KeyError on a hand-edited record missing "commit";
  * a torn `_write_memory` leaving a truncated file that `_read_memory` discards whole;
  * rotation past MAX_STORED_MERGES dropping something other than the oldest.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merged_diff_memory as mdm


@pytest.fixture
def temp_memory():
    """Redirect the metadata file to a tmpdir and start from an empty diff cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir, original_file = mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE
        mdm.MEMORY_DIR = Path(tmpdir)
        mdm.MERGED_DIFF_FILE = Path(tmpdir) / "merged_diff_memory.json"
        mdm._pool.invalidate()
        try:
            yield Path(tmpdir)
        finally:
            mdm._pool.invalidate()
            mdm.MEMORY_DIR, mdm.MERGED_DIFF_FILE = original_dir, original_file


def _record(n):
    return {"commit": f"sha{n:03d}", "branch": f"agent/b{n}", "author": "a",
            "date": "2026-08-13T00:00:00Z", "message": f"merge {n}",
            "files_affected": [f"f{n}.py"]}


class TestDiffsSurviveLaterMerges:
    def test_a_cached_diff_is_still_readable_after_further_merges(self, temp_memory):
        mdm.put_diff("main", "agent/first", "sha001", "diff --git a/one.py b/one.py")
        for n in range(2, 12):
            mdm.write_memory_file([_record(i) for i in range(1, n + 1)])
            mdm.put_diff("main", f"agent/b{n}", f"sha{n:03d}", f"diff {n}")

        assert mdm.get_diff("main", "agent/first", "sha001") == \
            "diff --git a/one.py b/one.py"

    def test_each_merges_diff_stays_addressable_by_its_own_key(self, temp_memory):
        for n in range(1, 6):
            mdm.put_diff("main", f"agent/b{n}", f"sha{n:03d}", f"diff-body-{n}")
        for n in range(1, 6):
            assert mdm.get_diff("main", f"agent/b{n}", f"sha{n:03d}") == f"diff-body-{n}"

    def test_a_diff_is_not_returned_for_a_different_merge(self, temp_memory):
        mdm.put_diff("main", "agent/b1", "sha001", "body-1")
        assert mdm.get_diff("main", "agent/b1", "sha002") == ""
        assert mdm.get_diff("main", "agent/b2", "sha001") == ""
        assert mdm.get_diff("dev", "agent/b1", "sha001") == ""


class TestMetadataSurvivesLaterMerges:
    def test_the_first_merge_is_still_recorded_after_later_ones(self, temp_memory):
        mdm.write_memory_file([_record(n) for n in range(1, 11)])
        recorded = mdm.get_recent_merges(limit=50)
        assert [m["commit"] for m in recorded][0] == "sha001"
        assert len(recorded) == 10

    def test_recent_merges_come_back_oldest_first_within_the_window(self, temp_memory):
        mdm.write_memory_file([_record(n) for n in range(1, 11)])
        assert [m["commit"] for m in mdm.get_recent_merges(limit=3)] == \
            ["sha008", "sha009", "sha010"]

    def test_rotation_drops_the_oldest_not_the_newest(self, temp_memory):
        over = mdm.MAX_STORED_MERGES + 5
        mdm.write_memory_file([_record(n) for n in range(1, over + 1)])
        kept = [m["commit"] for m in mdm.get_recent_merges(limit=over)]
        assert len(kept) == mdm.MAX_STORED_MERGES
        assert kept[-1] == f"sha{over:03d}"          # newest survives
        assert kept[0] == f"sha{over - mdm.MAX_STORED_MERGES + 1:03d}"
        assert "sha001" not in kept                   # oldest evicted

    def test_limit_zero_means_none_not_everything(self, temp_memory):
        """`merges[-0:]` is `merges[0:]`, so 0 used to mean 'give me all of them'."""
        mdm.write_memory_file([_record(n) for n in range(1, 6)])
        assert mdm.get_recent_merges(limit=0) == []
        assert mdm.get_recent_merges(limit=-3) == []

    def test_a_garbage_limit_falls_back_to_the_default(self, temp_memory):
        mdm.write_memory_file([_record(n) for n in range(1, 6)])
        assert len(mdm.get_recent_merges(limit="not-a-number")) == 5
        assert len(mdm.get_recent_merges(limit=None)) == 5


class TestMemoryIsNotCorruptedByBadInput:
    def test_a_record_missing_its_commit_key_does_not_abort_capture(self, temp_memory):
        """A hand-edited or half-written entry used to raise KeyError out of capture."""
        mdm.write_memory_file([{"branch": "agent/hand-edited"}, _record(1)])
        assert mdm.capture_merge("sha001", "agent/b1", str(temp_memory)) is True
        assert len(mdm.get_recent_merges(limit=50)) == 2  # no duplicate appended

    def test_a_corrupt_memory_file_reads_as_empty_rather_than_raising(self, temp_memory):
        mdm.MERGED_DIFF_FILE.write_text("{not json at all", encoding="utf-8")
        assert mdm._read_memory() == []
        assert mdm.get_recent_merges(limit=10) == []

    def test_the_write_is_atomic_and_leaves_no_temp_file_behind(self, temp_memory):
        assert mdm.write_memory_file([_record(1)]) is True
        leftovers = list(temp_memory.glob("*.tmp"))
        assert leftovers == []
        assert json.loads(mdm.MERGED_DIFF_FILE.read_text())["merges"][0]["commit"] == "sha001"

    def test_an_unwritable_directory_reports_failure_instead_of_lying(self, temp_memory):
        mdm.MERGED_DIFF_FILE = temp_memory / "nope" / "\0bad" / "m.json"
        mdm.MEMORY_DIR = temp_memory / "nope" / "\0bad"
        assert mdm.write_memory_file([_record(1)]) is False


class TestTheTwoMemoriesAreIndependent:
    def test_stats_reports_both_halves_without_key_collisions(self, temp_memory):
        mdm.put_diff("main", "agent/b1", "sha001", "body")
        mdm.write_memory_file([_record(1), _record(2)])
        s = mdm.stats()
        for key in ("entries", "bytes_used", "hits", "misses",
                    "total_tracked", "max_capacity", "file_exists"):
            assert key in s, key
        assert s["entries"] == 1
        assert s["total_tracked"] == 2

    def test_invalidate_clears_both_and_is_idempotent(self, temp_memory):
        mdm.put_diff("main", "agent/b1", "sha001", "body")
        mdm.write_memory_file([_record(1)])
        assert mdm.invalidate() is True
        assert mdm.get_diff("main", "agent/b1", "sha001") == ""
        assert mdm.get_recent_merges(limit=10) == []
        assert mdm.invalidate() is True
