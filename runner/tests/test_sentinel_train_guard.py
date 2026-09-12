#!/usr/bin/env python3
"""PROOF #4 of the fleet-immune-system operator directive.

"Delete pressure file: consistency test flags within 1h."

2026-08-02 incident item #5: sentinel.train_guard() read ONLY the file marker
while the merge train writes its pressure to the DB. A missing file scored
age=1e9, so every sentinel tick logged train-stale and spawned another
merge_train.py. The false alarm ran for days.

pipeline_selftest.check_pressure_consistency already classifies that state as
"fix_consumer" — these tests assert the consumer was actually fixed.
"""
import datetime
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentinel  # noqa: E402


class _GuardHarness(unittest.TestCase):
    def setUp(self):
        self.spawned = []
        self.logged = []
        self._saved = {
            "popen": sentinel.subprocess.Popen,
            "log": sentinel.log,
            "db_age": sentinel._train_pressure_db_age,
            "getmtime": sentinel.os.path.getmtime,
        }
        sentinel.subprocess.Popen = lambda *a, **k: self.spawned.append(a) or None
        sentinel.log = lambda action, detail="": self.logged.append((action, str(detail)))

    def tearDown(self):
        sentinel.subprocess.Popen = self._saved["popen"]
        sentinel.log = self._saved["log"]
        sentinel._train_pressure_db_age = self._saved["db_age"]
        sentinel.os.path.getmtime = self._saved["getmtime"]

    def setFileAge(self, seconds):
        """seconds=None simulates a DELETED pressure file."""
        if seconds is None:
            def _missing(_p):
                raise OSError("no such file")
            sentinel.os.path.getmtime = _missing
        else:
            sentinel.os.path.getmtime = lambda _p: time.time() - seconds

    def setDbAge(self, seconds):
        sentinel._train_pressure_db_age = lambda: seconds

    def actions(self):
        return [a for a, _ in self.logged]


class DeletedPressureFileTests(_GuardHarness):
    def test_deleted_file_with_fresh_db_does_not_fire_the_train(self):
        # THE regression. Before the fix this spawned merge_train.py every tick.
        self.setFileAge(None)
        self.setDbAge(60)
        sentinel.train_guard()
        self.assertEqual(self.spawned, [], "false train-stale fired on a deleted file")

    def test_deleted_file_with_fresh_db_is_flagged(self):
        self.setFileAge(None)
        self.setDbAge(60)
        sentinel.train_guard()
        self.assertIn("train-pressure-inconsistent", self.actions())
        self.assertNotIn("train-stale", self.actions())

    def test_stale_file_with_fresh_db_is_flagged_and_suppressed(self):
        self.setFileAge(sentinel.TRAIN_STALE_S + 500)
        self.setDbAge(30)
        sentinel.train_guard()
        self.assertEqual(self.spawned, [])
        self.assertIn("train-pressure-inconsistent", self.actions())


class GenuinelyStaleTests(_GuardHarness):
    def test_both_stale_still_fires_the_train(self):
        # The guard must not be defanged: a real stall still fires.
        self.setFileAge(sentinel.TRAIN_STALE_S + 500)
        self.setDbAge(sentinel.TRAIN_STALE_S + 500)
        sentinel.train_guard()
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("train-stale", self.actions())

    def test_db_stale_reports_db_as_the_source(self):
        self.setFileAge(sentinel.TRAIN_STALE_S + 500)
        self.setDbAge(sentinel.TRAIN_STALE_S + 500)
        sentinel.train_guard()
        detail = dict(self.logged)["train-stale"]
        self.assertIn("source=db", detail)

    def test_missing_file_and_missing_db_row_fires(self):
        self.setFileAge(None)
        self.setDbAge(None)
        sentinel.train_guard()
        self.assertEqual(len(self.spawned), 1)


class HealthyAndDegradedTests(_GuardHarness):
    def test_both_fresh_is_silent(self):
        self.setFileAge(10)
        self.setDbAge(10)
        sentinel.train_guard()
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.logged, [])

    def test_db_unreachable_falls_back_to_the_file_when_fresh(self):
        # Fail-soft: a DB outage must not turn the guard into a spawn loop.
        self.setFileAge(10)
        self.setDbAge(None)
        sentinel.train_guard()
        self.assertEqual(self.spawned, [])

    def test_db_unreachable_falls_back_to_the_file_when_stale(self):
        self.setFileAge(sentinel.TRAIN_STALE_S + 500)
        self.setDbAge(None)
        sentinel.train_guard()
        self.assertEqual(len(self.spawned), 1)
        self.assertIn("source=file", dict(self.logged)["train-stale"])

    def test_db_stale_but_file_fresh_still_fires(self):
        # The DB is authoritative, so a stale DB row means stale.
        self.setFileAge(10)
        self.setDbAge(sentinel.TRAIN_STALE_S + 500)
        sentinel.train_guard()
        self.assertEqual(len(self.spawned), 1)


class DbAgeHelperTests(unittest.TestCase):
    def tearDown(self):
        sys.modules.pop("_fake_db_for_sentinel", None)

    def _with_fake_db(self, rows):
        import types
        fake = types.SimpleNamespace(select=lambda *_a, **_k: rows)
        real_db = sys.modules.get("db")
        sys.modules["db"] = fake
        self.addCleanup(lambda: sys.modules.__setitem__("db", real_db)
                        if real_db is not None else sys.modules.pop("db", None))

    def test_parses_an_iso_timestamp(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        stamp = (now - datetime.timedelta(seconds=120)).isoformat()
        self._with_fake_db([{"updated_at": stamp}])
        age = sentinel._train_pressure_db_age()
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 120, delta=30)

    def test_naive_timestamp_is_treated_as_utc(self):
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        stamp = (now - datetime.timedelta(seconds=60)).isoformat()
        self._with_fake_db([{"updated_at": stamp}])
        age = sentinel._train_pressure_db_age()
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 60, delta=30)

    def test_no_row_returns_none(self):
        self._with_fake_db([])
        self.assertIsNone(sentinel._train_pressure_db_age())

    def test_unparseable_timestamp_returns_none(self):
        self._with_fake_db([{"updated_at": "not-a-timestamp"}])
        self.assertIsNone(sentinel._train_pressure_db_age())

    def test_db_error_returns_none_rather_than_raising(self):
        import types

        def _boom(*_a, **_k):
            raise RuntimeError("supabase down")

        real_db = sys.modules.get("db")
        sys.modules["db"] = types.SimpleNamespace(select=_boom)
        self.addCleanup(lambda: sys.modules.__setitem__("db", real_db)
                        if real_db is not None else sys.modules.pop("db", None))
        self.assertIsNone(sentinel._train_pressure_db_age())


if __name__ == "__main__":
    unittest.main()
