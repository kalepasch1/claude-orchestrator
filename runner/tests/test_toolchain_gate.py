import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import toolchain_gate


class CachedReadTest(unittest.TestCase):

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(prefix="tc_test_", suffix=".json")
        os.close(fd)
        os.remove(self._tmp)
        self._orig = toolchain_gate.STATE_FILE
        toolchain_gate.STATE_FILE = self._tmp

    def tearDown(self):
        toolchain_gate.STATE_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_no_cache_file_fails_open(self):
        self.assertTrue(toolchain_gate.is_ready_cached("unknown"))

    def test_no_entry_for_project_fails_open(self):
        self._write({"other": {"ready": False, "checked_at": 0}})
        self.assertTrue(toolchain_gate.is_ready_cached("missing-proj"))

    def test_cached_ready_true(self):
        self._write({"p1": {"ready": True, "checked_at": 0}})
        self.assertTrue(toolchain_gate.is_ready_cached("p1"))

    def test_cached_ready_false_blocks(self):
        self._write({"p1": {"ready": False, "checked_at": 0}})
        self.assertFalse(toolchain_gate.is_ready_cached("p1"))

    def test_corrupt_json_fails_open(self):
        with open(self._tmp, "w") as f:
            f.write("{{{not valid")
        self.assertTrue(toolchain_gate.is_ready_cached("p1"))

    def test_empty_file_fails_open(self):
        with open(self._tmp, "w") as f:
            f.write("")
        self.assertTrue(toolchain_gate.is_ready_cached("p1"))

    def test_missing_ready_key_fails_open(self):
        self._write({"p1": {"checked_at": 0}})
        self.assertTrue(toolchain_gate.is_ready_cached("p1"))

    def _write(self, data):
        os.makedirs(os.path.dirname(self._tmp), exist_ok=True)
        with open(self._tmp, "w") as f:
            json.dump(data, f)


class CheckProjectTest(unittest.TestCase):

    def test_nonexistent_repo_is_ready(self):
        result = toolchain_gate.check_project("p1", "/nonexistent/xyz")
        self.assertTrue(result["ready"])
        self.assertEqual(result["failures"], [])

    def test_none_repo_is_ready(self):
        result = toolchain_gate.check_project("p1", None)
        self.assertTrue(result["ready"])

    def test_empty_dir_is_ready(self):
        d = tempfile.mkdtemp()
        try:
            result = toolchain_gate.check_project("p1", d)
            self.assertTrue(result["ready"])
        finally:
            shutil.rmtree(d)

    def test_package_json_without_node_modules_flags(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write("{}")
            result = toolchain_gate.check_project("p1", d)
            tools = [f["tool"] for f in result["failures"]]
            self.assertIn("node_modules", tools)
            self.assertFalse(result["ready"])
        finally:
            shutil.rmtree(d)

    def test_python_project_checks_python3(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "requirements.txt"), "w") as f:
                f.write("requests\n")
            result = toolchain_gate.check_project("p1", d)
            self.assertIsInstance(result["ready"], bool)
        finally:
            shutil.rmtree(d)

    def test_cargo_project_without_cargo(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "Cargo.toml"), "w") as f:
                f.write("[package]\nname = 'test'\n")
            result = toolchain_gate.check_project("p1", d)
            if not result["ready"]:
                tools = [f["tool"] for f in result["failures"]]
                self.assertIn("cargo", tools)
        finally:
            shutil.rmtree(d)


class StateFileTest(unittest.TestCase):

    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(prefix="tc_state_", suffix=".json")
        os.close(fd)
        os.remove(self._tmp)
        self._orig = toolchain_gate.STATE_FILE
        toolchain_gate.STATE_FILE = self._tmp

    def tearDown(self):
        toolchain_gate.STATE_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_save_then_load(self):
        data = {"proj-abc": {"ready": True, "checked_at": 12345}}
        toolchain_gate._save_state(data)
        loaded = toolchain_gate._load_state()
        self.assertEqual(loaded, data)

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(toolchain_gate._load_state(), {})

    def test_save_creates_parent_dirs(self):
        nested = os.path.join(self._tmp + "_nested", "sub", "state.json")
        toolchain_gate.STATE_FILE = nested
        toolchain_gate._save_state({"x": 1})
        self.assertTrue(os.path.isfile(nested))
        shutil.rmtree(self._tmp + "_nested", ignore_errors=True)


class ClaimPathBlockTest(unittest.TestCase):

    def test_is_ready_cached_is_called_from_runner(self):
        runner_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "runner.py"
        )
        if not os.path.isfile(runner_path):
            self.skipTest("runner.py not found")
        with open(runner_path) as f:
            src = f.read()
        self.assertIn("toolchain_gate", src)
        self.assertIn("is_ready_cached", src)

    def test_blocked_project_returns_false(self):
        fd, tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        orig = toolchain_gate.STATE_FILE
        try:
            toolchain_gate.STATE_FILE = tmp
            with open(tmp, "w") as f:
                json.dump({"blocked-proj": {"ready": False, "checked_at": time.time()}}, f)
            self.assertFalse(toolchain_gate.is_ready_cached("blocked-proj"))
        finally:
            toolchain_gate.STATE_FILE = orig
            os.remove(tmp)


class RecoveryQueueTest(unittest.TestCase):

    @patch("toolchain_gate.db")
    def test_recovery_task_queued(self, mock_db):
        toolchain_gate._queue_recovery("proj-1", [{"tool": "npm", "error": "not found"}])
        mock_db.insert.assert_called_once()
        args = mock_db.insert.call_args
        self.assertEqual(args[0][0], "tasks")
        self.assertIn("toolchain-repair", args[0][1].get("slug", ""))

    @patch("toolchain_gate.db")
    def test_recovery_handles_db_error(self, mock_db):
        mock_db.insert.side_effect = Exception("DB down")
        toolchain_gate._queue_recovery("proj-1", [{"tool": "npm", "error": "not found"}])


if __name__ == "__main__":
    unittest.main()
