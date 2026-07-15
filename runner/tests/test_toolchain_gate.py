import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import toolchain_gate


class ToolchainGateCachedTest(unittest.TestCase):
    def setUp(self):
        fd, self._tmp = tempfile.mkstemp(prefix="toolchain_state_test_", suffix=".json")
        os.close(fd)
        os.remove(self._tmp)
        toolchain_gate.STATE_FILE = self._tmp

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_no_cache_entry_fails_open(self):
        self.assertTrue(toolchain_gate.is_ready_cached("unknown-project"))

    def test_cached_not_ready_blocks(self):
        os.makedirs(os.path.dirname(self._tmp), exist_ok=True)
        with open(self._tmp, "w") as f:
            json.dump({"proj-1": {"ready": False, "checked_at": 0}}, f)
        self.assertFalse(toolchain_gate.is_ready_cached("proj-1"))

    def test_cached_ready_passes(self):
        os.makedirs(os.path.dirname(self._tmp), exist_ok=True)
        with open(self._tmp, "w") as f:
            json.dump({"proj-1": {"ready": True, "checked_at": 0}}, f)
        self.assertTrue(toolchain_gate.is_ready_cached("proj-1"))

    def test_corrupt_state_file_fails_open(self):
        os.makedirs(os.path.dirname(self._tmp), exist_ok=True)
        with open(self._tmp, "w") as f:
            f.write("{not valid json")
        self.assertTrue(toolchain_gate.is_ready_cached("proj-1"))

    def test_missing_repo_path_is_ready(self):
        result = toolchain_gate.check_project("proj-1", "/nonexistent/path/xyz")
        self.assertTrue(result["ready"])

    def test_package_json_without_node_modules_flags_not_ready(self):
        import tempfile
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write('{"scripts": {}}')
            result = toolchain_gate.check_project("proj-1", d)
            tools = [f["tool"] for f in result["failures"]]
            self.assertIn("node_modules", tools)
            self.assertFalse(result["ready"])
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
