#!/usr/bin/env python3
"""The local patch-template fallback must be bounded, and its use must be visible.

When the `knowledge` table write fails, `_store` appends the template to a local JSONL at
`.runtime/patch_templates.jsonl`. Two problems with how that was done:

1. UNBOUNDED. The file is append-only and BOTH `lookup()` and `find_template()` scan it
   end to end, so every DB outage grew a file that every subsequent dependency-recovery
   read walks in full. That is the slow leak plus O(n)-read shape CLAUDE.md already calls
   out for the diff cache.

2. SILENT. The fallback swallowed the exception and returned as if the write had
   succeeded. A template that reached only local disk is invisible to every other host,
   so a recovery pass on another Mac does not find it and rebuilds the work — and nothing
   anywhere said so. It is the same defect development_session_store.py exists to remove.

Proof: python3 -m pytest runner/tests/test_patch_template_fallback_store.py -q
"""
import json
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_templates as pt  # noqa: E402


def _write(path, n, prefix="slug"):
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"ts": i, "task": f"{prefix}-{i:04d}",
                                 "template_id": f"t{i:04d}", "body": "x"}) + "\n")
    return path


class TestPrune(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "patch_templates.jsonl")

    def test_a_small_file_is_left_alone(self):
        _write(self.path, 5)
        self.assertFalse(pt._prune_fallback(self.path, keep=10))
        self.assertEqual(sum(1 for _ in open(self.path)), 5)

    def test_an_oversized_file_is_trimmed(self):
        _write(self.path, 50)
        self.assertTrue(pt._prune_fallback(self.path, keep=10))
        self.assertEqual(sum(1 for _ in open(self.path)), 10)

    def test_the_newest_entries_are_the_ones_kept(self):
        """Readers take the LAST matching line, so pruning must drop from the front."""
        _write(self.path, 50)
        pt._prune_fallback(self.path, keep=3)
        kept = [json.loads(line)["task"] for line in open(self.path)]
        self.assertEqual(kept, ["slug-0047", "slug-0048", "slug-0049"])

    def test_exactly_at_the_limit_is_not_rewritten(self):
        _write(self.path, 10)
        self.assertFalse(pt._prune_fallback(self.path, keep=10))

    def test_a_missing_file_is_not_an_error(self):
        self.assertFalse(pt._prune_fallback(os.path.join(self.dir, "nope.jsonl")))

    def test_a_failed_prune_leaves_the_file_intact(self):
        """An oversized file is a slow problem; a truncated one loses templates."""
        _write(self.path, 50)
        with patch("builtins.open", side_effect=OSError("disk full")):
            self.assertFalse(pt._prune_fallback(self.path, keep=5))
        self.assertEqual(sum(1 for _ in open(self.path)), 50)

    def test_no_temp_file_is_left_behind(self):
        _write(self.path, 50)
        pt._prune_fallback(self.path, keep=5)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_keep_is_floored_at_one(self):
        _write(self.path, 20)
        pt._prune_fallback(self.path, keep=0)
        self.assertEqual(sum(1 for _ in open(self.path)), 1)

    def test_the_limit_is_configurable_and_positive(self):
        self.assertGreaterEqual(pt.FALLBACK_MAX_ENTRIES, 1)


class TestStoreFallback(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "patch_templates.jsonl")
        self.task = {"slug": "fix-thing", "prompt": "make the thing work", "kind": "build"}

    def _store_with_failing_db(self):
        class _DB:
            @staticmethod
            def insert(*a, **k):
                raise RuntimeError("knowledge table unavailable")

        with patch.object(pt, "db", _DB), \
             patch.object(pt, "_fallback_path", return_value=self.path):
            with self.assertLogs(pt.log, level=logging.WARNING) as captured:
                pt._store(self.task, "abc123456789", "PATCH TEMPLATE abc123456789")
        return captured.output

    def test_a_local_only_write_is_logged_loudly(self):
        output = self._store_with_failing_db()
        joined = " ".join(output)
        self.assertIn("LOCAL-ONLY", joined)
        self.assertIn("invisible to other hosts", joined)

    def test_the_template_is_still_written_locally(self):
        self._store_with_failing_db()
        rows = [json.loads(line) for line in open(self.path)]
        self.assertEqual(rows[-1]["template_id"], "abc123456789")
        self.assertEqual(rows[-1]["task"], "fix-thing")

    def test_the_fallback_is_pruned_on_write(self):
        _write(self.path, 40)
        with patch.object(pt, "FALLBACK_MAX_ENTRIES", 5):
            self._store_with_failing_db()
        self.assertLessEqual(sum(1 for _ in open(self.path)), 5)

    def test_a_successful_knowledge_write_touches_no_local_file(self):
        class _DB:
            @staticmethod
            def insert(*a, **k):
                return {}

        with patch.object(pt, "db", _DB), \
             patch.object(pt, "_fallback_path", return_value=self.path):
            pt._store(self.task, "abc123456789", "body")
        self.assertFalse(os.path.exists(self.path))

    def test_an_unwritable_fallback_does_not_raise(self):
        class _DB:
            @staticmethod
            def insert(*a, **k):
                raise RuntimeError("down")

        with patch.object(pt, "db", _DB), \
             patch.object(pt, "_fallback_path",
                          return_value="/proc/definitely/not/writable/x.jsonl"):
            pt._store(self.task, "abc123456789", "body")


class TestReadersStillWork(unittest.TestCase):
    """Pruning must not change what a reader returns."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "patch_templates.jsonl")

    def test_find_template_still_resolves_a_kept_entry(self):
        _write(self.path, 50)
        pt._prune_fallback(self.path, keep=5)

        class _DB:
            @staticmethod
            def select(*a, **k):
                return []

        with patch.object(pt, "db", _DB), \
             patch.object(pt, "_fallback_path", return_value=self.path):
            got = pt.find_template("slug-0049")
        self.assertEqual(got.get("template_id"), "t0049")

    def test_find_template_misses_cleanly_on_a_pruned_entry(self):
        _write(self.path, 50)
        pt._prune_fallback(self.path, keep=5)

        class _DB:
            @staticmethod
            def select(*a, **k):
                return []

        with patch.object(pt, "db", _DB), \
             patch.object(pt, "_fallback_path", return_value=self.path):
            self.assertEqual(pt.find_template("slug-0000"), {})

    def test_find_template_is_fail_soft_on_junk(self):
        for bad in (None, "", "   ", 7):
            self.assertEqual(pt.find_template(bad), {}, bad)


if __name__ == "__main__":
    unittest.main()
