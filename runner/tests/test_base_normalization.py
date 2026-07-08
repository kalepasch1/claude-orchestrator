import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prewarm


class TestBaseNormalization(unittest.TestCase):
    def test_prewarm_uses_existing_project_default_over_missing_main(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-b", "master"], cwd=d, check=True, capture_output=True)
            subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=d, check=True,
                           capture_output=True, env={**os.environ,
                                                     "GIT_AUTHOR_NAME": "Test",
                                                     "GIT_AUTHOR_EMAIL": "test@example.com",
                                                     "GIT_COMMITTER_NAME": "Test",
                                                     "GIT_COMMITTER_EMAIL": "test@example.com"})
            base = prewarm._normalize_base(d, {"default_base": "master"}, "main")
            self.assertEqual(base, "master")


if __name__ == "__main__":
    unittest.main(verbosity=2)
