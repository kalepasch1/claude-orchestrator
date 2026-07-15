import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import patch_fabric


def run(repo, *args):
    return subprocess.run(args, cwd=repo, check=True, capture_output=True, text=True)


@unittest.skipUnless(shutil.which("git"), "git required")
class PatchFabricTests(unittest.TestCase):
    def test_materializes_tests_commits_and_reuses_content_addressed_patch(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            run(repo, "git", "init", "-b", "main")
            run(repo, "git", "config", "user.email", "test@example.com")
            run(repo, "git", "config", "user.name", "Test")
            with open(os.path.join(repo, "a.txt"), "w") as f:
                f.write("old\n")
            run(repo, "git", "add", "a.txt")
            run(repo, "git", "commit", "-m", "base")
            with open(os.path.join(repo, "a.txt"), "w") as f:
                f.write("new\n")
            diff = run(repo, "git", "diff", "--binary").stdout
            run(repo, "git", "checkout", "--", "a.txt")
            runtime = os.path.join(td, "runtime")
            with mock.patch.dict(os.environ, {"CLAUDE_ORCH_HOME": runtime}):
                result = patch_fabric.materialize(
                    {"id": "t1", "slug": "change-a"}, repo, "main",
                    "```diff\n" + diff + "```", "grep -q new a.txt",
                )
                reused = patch_fabric.materialize(
                    {"id": "t1", "slug": "change-a"}, repo, "main",
                    diff, "grep -q new a.txt",
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["branch"], "agent/change-a")
            self.assertTrue(result["commit"])
            self.assertTrue(reused["ok"])
            self.assertTrue(reused.get("reused"))

    def test_rejects_non_patch_output(self):
        result = patch_fabric.materialize(
            {"slug": "x"}, "/does/not/matter", "main", "Looks good!", "true"
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "extract")

    def test_repairs_markdown_indented_model_patch(self):
        text = """ diff --git a/x.txt b/x.txt
   new file mode 100644
   index 0000000..1111111
   --- /dev/null
   +++ b/x.txt
   @@ -0,0 +1 @@
   +hello
"""
        out = patch_fabric.extract_diff(text)
        self.assertIn("\nnew file mode", out)
        self.assertIn("\n+hello\n", out)


if __name__ == "__main__":
    unittest.main()
