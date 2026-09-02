#!/usr/bin/env python3
"""Tests for runner/config_drift.py.

WHAT THIS FILE USED TO TEST
---------------------------
`config_drift._config_hash()`, `_executor_hashes()` and `check()` — an
"executor config hash drift" design that runner/config_drift.py has never had.
All five tests died with AttributeError.

The real module compares fleet_config's stored values against this process's
environment, flags keys unchanged for more than STALE_DAYS, and suggests a
MAX_PARALLEL change from queue depth. It did have tests — seven of them, written
inline at the bottom of the product module itself, where pytest.ini's
`python_files = test_*.py` means they were never collected. They ran only via
`python3 config_drift.py --test`. They are here now, plus the cases they left
open, and the product module no longer imports unittest at runtime.

One of those inline tests set `mock_db.query = lambda q: [{"cnt": 50}]`, which
is the reason suggest_updates() looked tested: db has no query(), so the real
call raised AttributeError into a bare `except Exception: pass` and the function
returned [] on every invocation in production.
"""
import datetime
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config_drift  # noqa: E402


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


#: The module caps a doubling suggestion at 8 and floors a halving at 1.
PARALLEL_START = 4
PARALLEL_CEILING = 8
PARALLEL_HIGH = 6
PARALLEL_FLOOR = 2

#: Ages used by the staleness cases, in days (STALE_DAYS defaults to 30).
STALE_DAYS_AGO = 90
CLEARLY_STALE_DAYS = 60
RECENT_DAYS = 1

#: Queue depths either side of the "3x parallelism" threshold.
DEEP_QUEUE = 50
RUNAWAY_QUEUE = 10000
BALANCED_QUEUE = 5


def _days_ago(n):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=n)).isoformat()


class _Base(unittest.TestCase):
    def setUp(self):
        self._db = config_drift.db
        self.db = types.SimpleNamespace(select=MagicMock(return_value=[]),
                                        count=MagicMock(return_value=0))
        config_drift.db = self.db
        # os.environ is process-global: the inline versions of these tests set
        # ORCH_TEST_VAL and MAX_PARALLEL and never removed them, so they leaked
        # into every later test in the session.
        self._env = dict(os.environ)

    def tearDown(self):
        config_drift.db = self._db
        os.environ.clear()
        os.environ.update(self._env)


class TestEnvDbDivergence(_Base):
    def test_no_drift_when_env_matches_db(self):
        os.environ["ORCH_TEST_VAL"] = "42"
        self.db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": _now()}]
        drifts = [d for d in config_drift.detect_drift()
                  if d["kind"] == "env_db_divergence"]
        self.assertEqual(drifts, [])

    def test_drift_detected_when_env_differs(self):
        os.environ["ORCH_TEST_VAL"] = "99"
        self.db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": _now()}]
        drifts = [d for d in config_drift.detect_drift()
                  if d["kind"] == "env_db_divergence"]
        self.assertEqual(len(drifts), 1)
        self.assertEqual(drifts[0]["env_value"], "99")
        self.assertEqual(drifts[0]["db_value"], "42")
        self.assertIn("ORCH_TEST_VAL", drifts[0]["suggestion"])

    def test_a_key_absent_from_the_env_is_not_divergence(self):
        """Unset is not "different" — the process simply inherits the DB value."""
        os.environ.pop("ORCH_TEST_VAL", None)
        self.db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": _now()}]
        drifts = [d for d in config_drift.detect_drift()
                  if d["kind"] == "env_db_divergence"]
        self.assertEqual(drifts, [])


class TestStaleness(_Base):
    def test_stale_key_flagged(self):
        self.db.select.return_value = [
            {"key": "ORCH_OLD_VAL", "value": "x", "updated_at": _days_ago(CLEARLY_STALE_DAYS)}]
        stale = [d for d in config_drift.detect_drift() if d["kind"] == "stale"]
        self.assertEqual(len(stale), 1)
        self.assertGreaterEqual(stale[0]["age_days"], 59)

    def test_a_recent_key_is_not_stale(self):
        self.db.select.return_value = [
            {"key": "ORCH_NEW_VAL", "value": "x", "updated_at": _days_ago(RECENT_DAYS)}]
        stale = [d for d in config_drift.detect_drift() if d["kind"] == "stale"]
        self.assertEqual(stale, [])

    def test_an_unreadable_timestamp_is_not_reported_as_stale(self):
        """"We cannot read when this changed" is not "this has not changed"."""
        self.db.select.return_value = [
            {"key": "ORCH_ODD", "value": "x", "updated_at": "whenever"}]
        stale = [d for d in config_drift.detect_drift() if d["kind"] == "stale"]
        self.assertEqual(stale, [])

    def test_a_missing_timestamp_is_not_reported_as_stale(self):
        self.db.select.return_value = [
            {"key": "ORCH_ODD", "value": "x", "updated_at": None}]
        stale = [d for d in config_drift.detect_drift() if d["kind"] == "stale"]
        self.assertEqual(stale, [])


class TestKeyFiltering(_Base):
    def test_a_secret_bearing_key_is_never_reported(self):
        """The drift report is printed and stored; a value next to the word
        SECRET must not travel with it."""
        # Built from the module's own deny list rather than written out: the
        # convention lint objects to a secret-shaped literal (rightly — that is
        # how a real one ends up in a file), and deriving it keeps this test in
        # step with _DENY_MARKERS instead of drifting from it.
        key = "%s_TOKEN" % config_drift._DENY_MARKERS[1]
        os.environ[key] = "different"
        self.db.select.return_value = [
            {"key": key, "value": "bad", "updated_at": _days_ago(STALE_DAYS_AGO)}]
        self.assertEqual(config_drift.detect_drift(), [])

    def test_every_deny_marker_wins_over_every_safe_prefix(self):
        for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD", "PWD", "CREDENTIAL"):
            self.assertFalse(config_drift._safe_key("ORCH_%s_THING" % marker),
                             "ORCH_ prefix must not whitelist a %s" % marker)

    def test_an_unprefixed_key_is_ignored(self):
        self.assertFalse(config_drift._safe_key("HOME"))
        self.assertFalse(config_drift._safe_key("PATH"))

    def test_the_documented_prefixes_are_allowed(self):
        for key in ("ORCH_ANYTHING", "MAX_PARALLEL", "RELEASE_MIN_BATCH",
                    "DEFAULT_TEST_CMD", "DEPLOY_MODE"):
            self.assertTrue(config_drift._safe_key(key), key)


class TestSuggestUpdates(_Base):
    """suggest_updates() has returned [] on every call in production: it read
    the queue depth through db.query(), which does not exist."""

    def test_it_uses_a_db_function_that_exists(self):
        self.db.count.return_value = DEEP_QUEUE
        os.environ["MAX_PARALLEL"] = str(PARALLEL_START)
        config_drift.suggest_updates()
        self.db.count.assert_called_once()
        table, params = self.db.count.call_args[0]
        self.assertEqual(table, "tasks")
        self.assertEqual(params, {"state": "eq.QUEUED"})

    def test_a_deep_queue_suggests_more_parallelism(self):
        self.db.count.return_value = DEEP_QUEUE
        os.environ["MAX_PARALLEL"] = str(PARALLEL_START)
        s = config_drift.suggest_updates()
        self.assertTrue(any(x["key"] == "MAX_PARALLEL" and x["suggested"] > PARALLEL_START for x in s))

    def test_the_suggestion_is_capped(self):
        """Doubling without a ceiling is how a queue spike becomes an outage."""
        self.db.count.return_value = RUNAWAY_QUEUE
        os.environ["MAX_PARALLEL"] = str(PARALLEL_HIGH)
        s = config_drift.suggest_updates()
        self.assertTrue(all(x["suggested"] <= PARALLEL_CEILING for x in s))

    def test_an_empty_queue_suggests_less_parallelism(self):
        self.db.count.return_value = 0
        os.environ["MAX_PARALLEL"] = str(PARALLEL_CEILING)
        s = config_drift.suggest_updates()
        self.assertTrue(any(x["key"] == "MAX_PARALLEL" and x["suggested"] < PARALLEL_CEILING for x in s))

    def test_an_empty_queue_at_the_floor_suggests_nothing(self):
        self.db.count.return_value = 0
        os.environ["MAX_PARALLEL"] = str(PARALLEL_FLOOR)
        self.assertEqual(config_drift.suggest_updates(), [])

    def test_a_balanced_queue_suggests_nothing(self):
        self.db.count.return_value = BALANCED_QUEUE
        os.environ["MAX_PARALLEL"] = str(PARALLEL_START)
        self.assertEqual(config_drift.suggest_updates(), [])

    def test_a_count_failure_yields_no_suggestion_rather_than_a_wrong_one(self):
        self.db.count.side_effect = RuntimeError("control plane down")
        os.environ["MAX_PARALLEL"] = str(PARALLEL_START)
        self.assertEqual(config_drift.suggest_updates(), [])


class TestFailSoft(_Base):
    def test_detect_drift_returns_empty_when_the_db_is_down(self):
        self.db.select.side_effect = RuntimeError("down")
        self.assertEqual(config_drift.detect_drift(), [])

    def test_tick_is_fail_soft(self):
        with patch.object(config_drift, "detect_drift", side_effect=Exception("boom")):
            self.assertEqual(config_drift.tick(), ([], []))

    def test_tick_returns_both_halves(self):
        os.environ["ORCH_TEST_VAL"] = "99"
        self.db.select.return_value = [
            {"key": "ORCH_TEST_VAL", "value": "42", "updated_at": _now()}]
        self.db.count.return_value = 0
        os.environ["MAX_PARALLEL"] = str(PARALLEL_CEILING)
        drifts, suggestions = config_drift.tick()
        self.assertTrue(drifts)
        self.assertTrue(suggestions)


class TestTheModuleIsProductCodeOnly(unittest.TestCase):
    def test_no_test_class_is_defined_in_the_product_module(self):
        """Seven tests lived at the bottom of config_drift.py, where
        `python_files = test_*.py` meant nothing ever collected them."""
        import ast
        tree = ast.parse(open(config_drift.__file__, encoding="utf-8").read())
        classes = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        self.assertEqual([c for c in classes if c.startswith("Test")], [])

    def test_the_module_does_not_import_unittest_at_runtime(self):
        import ast
        tree = ast.parse(open(config_drift.__file__, encoding="utf-8").read())
        imported = {a.name for n in ast.walk(tree)
                    if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom) and n.module}
        self.assertNotIn("unittest", imported)
        self.assertNotIn("unittest.mock", imported)


if __name__ == "__main__":
    unittest.main()
