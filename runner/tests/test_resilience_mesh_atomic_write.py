"""Two concurrent writers must not race on one temp file.

`_write_json` used a fixed `"<path>.tmp"`. Two overlapping runs create the SAME
temp file; the first `os.replace()` consumes it and the second dies on a file it
had just written itself. resilience_mesh runs on a 60-second interval
(runner.py, "resmesh-60") and also standalone, so overlap is routine — and the
crash was the last line of .runtime/logs/resilience-mesh.err:

    File "runner/resilience_mesh.py", line 91, in _write_json
        os.replace(tmp, path)
    FileNotFoundError: [Errno 2] No such file or directory:
      '.runtime/db_health.json.tmp' -> '.runtime/db_health.json'

db_recovery_sprint._write_json was fixed for exactly this in 2026-08, and its
comment names THIS module as the casualty: "that is what kept db_health.json
missing, which in turn made resilience_mesh fail on every cycle." The one-line
change was never applied here, so the file the note is about kept crashing.
"""

import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resilience_mesh as rm


class TempNameIsUniquePerCall(unittest.TestCase):
    def test_the_temp_name_carries_the_pid(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db_health.json")
            seen = {}
            real_replace = os.replace

            def spy(src, dst):
                seen["src"] = src
                return real_replace(src, dst)

            os.replace = spy
            try:
                rm._write_json(path, {"ok": True})
            finally:
                os.replace = real_replace

            # Unique per CALL, not merely per process: threads share a pid.
            self.assertNotEqual(seen["src"], path + ".tmp",
                                "a shared temp name is what two writers collide on")
            self.assertTrue(seen["src"].startswith(path + "."))
            self.assertTrue(seen["src"].endswith(".tmp"))
            self.assertEqual(os.path.dirname(seen["src"]), os.path.dirname(path),
                             "the temp must share a filesystem with the target for atomic replace")


class ConcurrentWritersBothSucceed(unittest.TestCase):
    def test_many_threads_writing_the_same_path_do_not_raise(self):
        """The reproduction. Against a fixed temp name this raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db_health.json")
            errors = []
            start = threading.Barrier(8)

            def writer(i):
                try:
                    start.wait(timeout=10)
                    for _ in range(25):
                        rm._write_json(path, {"writer": i})
                except Exception as exc:                 # noqa: BLE001
                    errors.append(repr(exc))

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            self.assertEqual(errors, [], "concurrent writers must not race on the temp file")
            with open(path, encoding="utf-8") as fh:
                self.assertIn("writer", json.load(fh), "last writer wins, and the file is valid")

    def test_no_temp_files_are_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            rm._write_json(path, {"a": 1})
            leftovers = [f for f in os.listdir(d) if ".tmp" in f]
            self.assertEqual(leftovers, [], "a stale temp file is litter that accumulates forever")


class WriteStillWorks(unittest.TestCase):
    def test_it_creates_the_directory_and_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "nested", "deeper", "state.json")
            rm._write_json(path, {"hello": "world", "n": 2})
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {"hello": "world", "n": 2})

    def test_non_serialisable_values_do_not_leave_a_temp_behind(self):
        import datetime
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")
            # default=str handles this; the point is the finally clause runs either way.
            rm._write_json(path, {"when": datetime.datetime(2026, 1, 1)})
            self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [])

    def test_a_write_failure_still_clears_the_temp(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state.json")

            class Unserialisable:
                def __repr__(self):
                    raise RuntimeError("boom")

            with self.assertRaises(Exception):
                rm._write_json(path, {"bad": Unserialisable()})
            self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [],
                             "a failed write must not leave a temp file behind")


if __name__ == "__main__":
    unittest.main()
