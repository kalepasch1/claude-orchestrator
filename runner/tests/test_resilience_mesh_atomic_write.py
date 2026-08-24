"""Regression test for the resilience_mesh _write_json crashloop.

The temp file was a fixed "<path>.tmp", so two overlapping writers created the same
name, the first os.replace() consumed it, and the second raised

    FileNotFoundError: '<...>/db_health.json.tmp' -> '<...>/db_health.json'

on every cycle of a 60s job. Nothing asserted on the write path, so it stayed broken for
three weeks while the identical fix sat in db_recovery_sprint.
"""
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import resilience_mesh as rm  # noqa: E402


class AtomicWriteTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="resmesh-test-")
        self.path = os.path.join(self.dir, "nested", "db_health.json")

    def test_writes_and_reads_back(self):
        rm._write_json(self.path, {"ok": True, "n": 3})
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"ok": True, "n": 3})

    def test_creates_missing_parent_directory(self):
        self.assertFalse(os.path.exists(os.path.dirname(self.path)))
        rm._write_json(self.path, {"a": 1})
        self.assertTrue(os.path.isfile(self.path))

    def test_concurrent_writers_do_not_raise(self):
        # The exact shape of the crashloop: many writers, one destination.
        errors = []

        def write(n):
            try:
                rm._write_json(self.path, {"writer": n})
            except Exception as exc:          # pragma: no cover - the bug being fixed
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"concurrent writers raised: {errors}")
        # The destination is always a complete, parseable document — never a partial
        # write and never absent.
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("writer", json.load(handle))

    def test_no_temp_files_are_left_behind(self):
        for i in range(5):
            rm._write_json(self.path, {"i": i})
        leftovers = [n for n in os.listdir(os.path.dirname(self.path)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_unserialisable_payload_is_fail_soft(self):
        # default=str handles most things; anything it cannot handle must not raise out
        # of a job that runs every 60 seconds.
        class Exploding:
            def __str__(self):
                raise RuntimeError("nope")

        try:
            rm._write_json(self.path, {"bad": Exploding()})
        except Exception as exc:
            self.fail(f"_write_json raised instead of failing soft: {exc}")
        leftovers = [n for n in os.listdir(os.path.dirname(self.path)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
