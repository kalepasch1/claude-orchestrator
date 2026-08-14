#!/usr/bin/env python3
"""Regression: get_recent_merges() limit boundary + _prune_old_entries locking.

`merges[-limit:]` is a trap at zero — Python has no negative zero, so `[-0:]` is
`[0:]` and `get_recent_merges(0)` returned the ENTIRE history instead of nothing.
A negative limit likewise meant "all but the first N". `recent()` already clamped
its limit, so the same argument meant different things in the two entry points.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_memory as mdm  # noqa: E402


class GetRecentMergesLimitTest(unittest.TestCase):
    def setUp(self):
        self.rows = [{"commit": f"sha{i}"} for i in range(5)]
        patcher = patch.object(mdm, "_read_memory", lambda: list(self.rows))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_zero_limit_returns_nothing(self):
        assert mdm.get_recent_merges(0) == []

    def test_negative_limit_returns_nothing(self):
        assert mdm.get_recent_merges(-3) == []

    def test_positive_limit_returns_tail(self):
        assert mdm.get_recent_merges(2) == [{"commit": "sha3"}, {"commit": "sha4"}]

    def test_limit_larger_than_history_returns_all(self):
        assert len(mdm.get_recent_merges(500)) == 5

    def test_non_numeric_limit_falls_back_to_default(self):
        assert len(mdm.get_recent_merges("nope")) == 5
        assert len(mdm.get_recent_merges(None)) == 5

    def test_numeric_string_limit_is_honoured(self):
        assert len(mdm.get_recent_merges("2")) == 2


class PruneOldEntriesTest(unittest.TestCase):
    def _index(self, text):
        fd, path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def test_prunes_dated_lines_past_cutoff_and_keeps_recent(self):
        from datetime import datetime, timedelta

        recent_day = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        old_day = (datetime.utcnow().date() - timedelta(days=400)).isoformat()
        path = self._index(f"- {recent_day} keep me\n- {old_day} drop me\n- undated line\n")

        mdm._prune_old_entries(path, days=90)

        with open(path) as fh:
            out = fh.read()
        assert "keep me" in out
        assert "drop me" not in out
        assert "undated line" in out, "lines without a date must be preserved"

    def test_holds_the_lock_across_read_and_write(self):
        """A lost-update race: the read used to sit outside the lock the write took."""
        path = self._index("- 2099-01-01 keep\n")
        events = []

        class TracingLock:
            def __enter__(inner):
                events.append("acquire")
                return inner

            def __exit__(inner, *exc):
                events.append("release")
                return False

        real_open = open

        def tracing_open(*args, **kwargs):
            mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
            events.append(f"open:{mode}")
            return real_open(*args, **kwargs)

        with patch.object(mdm, "_lock", TracingLock()), \
             patch("builtins.open", tracing_open):
            mdm._prune_old_entries(path, days=90)

        assert events[0] == "acquire", f"read must happen under the lock, got {events}"
        assert events[-1] == "release", f"write must finish under the lock, got {events}"
        assert events.count("acquire") == 1, "one critical section, not two"
        # both the read and the write live inside the single acquire/release pair
        assert "open:r" in events and "open:w" in events

    def test_missing_file_is_fail_soft(self):
        mdm._prune_old_entries("/nonexistent/MEMORY.md", days=90)  # must not raise


if __name__ == "__main__":
    unittest.main()
