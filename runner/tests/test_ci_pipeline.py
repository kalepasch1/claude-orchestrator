"""Tests for CI pipeline — verify GitHub Actions workflow exists."""
import os
import unittest


class TestCIPipeline(unittest.TestCase):
    def test_ci_yaml_exists(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        ci_path = os.path.join(repo_root, ".github", "workflows", "ci.yml")
        self.assertTrue(os.path.isfile(ci_path),
                        f"ci.yml not found at {ci_path}")
        with open(ci_path) as f:
            content = f.read()
        self.assertIn("pytest", content)


if __name__ == "__main__":
    unittest.main()
