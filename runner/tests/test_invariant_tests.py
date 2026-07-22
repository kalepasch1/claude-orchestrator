"""
test_invariant_tests.py - tests for invariant_tests.py.

Tests assert_invariant helper, grep utility, and each invariant check.
All hermetic — no live DB, uses mocks.
"""
import os, sys, json, unittest, tempfile, shutil
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import invariant_tests


class TestAssertInvariant(unittest.TestCase):

    def test_passing_invariant(self):
        self.assertTrue(invariant_tests.assert_invariant("test", True))

    def test_failing_invariant_returns_false(self):
        with patch("invariant_tests.db", create=True) as mock_db:
            mock_db.insert = MagicMock()
            result = invariant_tests.assert_invariant("test_fail", False, "detail")
            self.assertFalse(result)

    def test_failing_invariant_logs(self):
        mock_insert = MagicMock()
        with patch.object(invariant_tests.db, "insert", mock_insert):
            invariant_tests.assert_invariant("test_log", False, "some detail")
        mock_insert.assert_called_once()
        args = mock_insert.call_args
        self.assertEqual(args[0][0], "resource_events")
        payload = json.loads(args[0][1]["payload"])
        self.assertEqual(payload["invariant"], "test_log")

    @patch("invariant_tests.db", create=True)
    def test_failsoft_on_db_error(self, mock_db):
        mock_db.insert.side_effect = Exception("db down")
        result = invariant_tests.assert_invariant("test_err", False)
        self.assertFalse(result)  # returns False but doesn't raise


class TestGrepFiles(unittest.TestCase):

    def test_finds_pattern(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("db.insert('tasks', data)\nother line\n")
            matches = invariant_tests._grep_files(r"db\.insert", tmpdir)
            self.assertEqual(len(matches), 1)
            self.assertIn("db.insert", matches[0][2])
        finally:
            shutil.rmtree(tmpdir)

    def test_no_match(self):
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("nothing here\n")
            matches = invariant_tests._grep_files(r"db\.insert", tmpdir)
            self.assertEqual(len(matches), 0)
        finally:
            shutil.rmtree(tmpdir)


class TestInvariantChecks(unittest.TestCase):

    def test_invariant_map_complete(self):
        """All checks in INVARIANT_MAP have corresponding check functions."""
        for name, fn_name in invariant_tests.INVARIANT_MAP.items():
            self.assertTrue(hasattr(invariant_tests, fn_name),
                           f"Missing check function for {name}: {fn_name}")

    def test_run_all_returns_dict(self):
        """run_all should return results for all invariants."""
        results = invariant_tests.run_all()
        self.assertIsInstance(results, dict)
        self.assertTrue(len(results) >= 4)
        for name, r in results.items():
            self.assertIn("passed", r)
            self.assertIn("violations", r)

    def test_run_all_doesnt_raise(self):
        """run_all must be fail-soft — no exceptions escape."""
        try:
            invariant_tests.run_all()
        except Exception as e:
            self.fail(f"run_all() raised {e}")


class TestLaunchdCheck(unittest.TestCase):

    def test_missing_dir_ok(self):
        """If launchd dir doesn't exist, check returns empty."""
        old = invariant_tests.RUNNER_DIR
        invariant_tests.RUNNER_DIR = "/nonexistent/path"
        try:
            result = invariant_tests.check_launchd_env_vars()
            self.assertEqual(result, [])
        finally:
            invariant_tests.RUNNER_DIR = old


if __name__ == "__main__":
    unittest.main()
