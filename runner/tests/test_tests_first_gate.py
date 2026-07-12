"""
test_tests_first_gate.py - covering:
  - A proof naming a MISSING test file splits into two tasks
  - A proof naming an EXISTING test file does NOT split
  - A proof that is a build command (no test file) does NOT split
  - An empty proof does NOT split
"""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tests_first_gate


def _task(**overrides):
    t = {"slug": "my-feature", "prompt": "implement X", "kind": "build",
         "deps": [], "proof": ""}
    t.update(overrides)
    return t


class TestExtractTestFile(unittest.TestCase):

    def test_extracts_test_path(self):
        proof = "`python -m pytest runner/tests/test_foo.py` exits 0"
        self.assertEqual(tests_first_gate._extract_test_file(proof), "runner/tests/test_foo.py")

    def test_no_test_file_in_build_command(self):
        proof = "`npm test` exits 0"
        self.assertIsNone(tests_first_gate._extract_test_file(proof))

    def test_empty_proof(self):
        self.assertIsNone(tests_first_gate._extract_test_file(""))

    def test_none_proof(self):
        self.assertIsNone(tests_first_gate._extract_test_file(None))


class TestSplitIfNeeded(unittest.TestCase):

    def test_missing_test_file_splits(self):
        """Proof naming a test file that doesn't exist => split into 2 tasks."""
        repo = tempfile.mkdtemp()
        # test file does NOT exist
        t = _task(proof="`python -m pytest runner/tests/test_new.py` exits 0")
        result = tests_first_gate.split_if_needed(t, repo_path=repo)
        self.assertEqual(len(result), 2)
        test_task, impl_task = result
        self.assertEqual(test_task["slug"], "my-feature-write-tests")
        self.assertEqual(test_task["kind"], "test")
        self.assertIn("my-feature-write-tests", impl_task["deps"])

    def test_existing_test_file_no_split(self):
        """Proof naming a test file that DOES exist => no split."""
        repo = tempfile.mkdtemp()
        os.makedirs(os.path.join(repo, "runner", "tests"), exist_ok=True)
        with open(os.path.join(repo, "runner", "tests", "test_existing.py"), "w") as f:
            f.write("# test\n")
        t = _task(proof="`python -m pytest runner/tests/test_existing.py` exits 0")
        result = tests_first_gate.split_if_needed(t, repo_path=repo)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slug"], "my-feature")

    def test_build_command_no_split(self):
        """Proof that's a build command (no test file path) => no split."""
        t = _task(proof="`npm run build` exits 0")
        result = tests_first_gate.split_if_needed(t, repo_path=tempfile.mkdtemp())
        self.assertEqual(len(result), 1)

    def test_empty_proof_no_split(self):
        t = _task(proof="")
        result = tests_first_gate.split_if_needed(t)
        self.assertEqual(len(result), 1)

    def test_test_task_inherits_original_deps(self):
        repo = tempfile.mkdtemp()
        t = _task(deps=["contracts"], proof="`pytest test_x.py`")
        result = tests_first_gate.split_if_needed(t, repo_path=repo)
        self.assertEqual(len(result), 2)
        self.assertIn("contracts", result[0]["deps"])


class TestApplyGate(unittest.TestCase):

    def test_multiple_tasks(self):
        repo = tempfile.mkdtemp()
        tasks = [
            _task(slug="a", proof="`pytest test_a.py`"),
            _task(slug="b", proof="`npm test`"),
        ]
        result = tests_first_gate.apply_gate(tasks, repo_path=repo)
        # 'a' splits (test file missing), 'b' does not
        self.assertEqual(len(result), 3)
        slugs = [t["slug"] for t in result]
        self.assertIn("a-write-tests", slugs)
        self.assertIn("a", slugs)
        self.assertIn("b", slugs)


if __name__ == "__main__":
    unittest.main()
