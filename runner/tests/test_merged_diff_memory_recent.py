#!/usr/bin/env python3
"""Coverage for merged_diff_memory.recent() and the caller it unblocks.

self_authored_capabilities.scan_recent_diffs() calls mdm.recent(days=, limit=),
which no version of the module defined. Because the call is wrapped in a bare
`except Exception: diffs = []`, the missing function never surfaced as an error —
it just made pattern detection return nothing, forever. These tests pin both the
new function and the fact that the caller now actually sees diff content.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_memory as mdm  # noqa: E402


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True)


class TestRecent(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()
        _git(["init", "-q"], self.repo)
        _git(["config", "user.name", "Test"], self.repo)
        _git(["config", "user.email", "t@example.com"], self.repo)
        with open(os.path.join(self.repo, "mod.py"), "w") as f:
            f.write("import os\n"
                    "TIMEOUT = os.environ.get('ORCH_TIMEOUT', '5')\n"
                    "try:\n    pass\nexcept Exception:\n    pass\n")
        _git(["add", "-A"], self.repo)
        _git(["commit", "-q", "-m", "feat: add mod"], self.repo)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_exists_and_is_callable(self):
        self.assertTrue(callable(getattr(mdm, "recent", None)))

    def test_returns_records_with_diff_text(self):
        out = mdm.recent(days=30, limit=10, repo=self.repo)
        self.assertTrue(out, "expected at least one commit record")
        self.assertIn("diff", out[0])
        self.assertIn("ORCH_TIMEOUT", out[0]["diff"])

    def test_records_carry_commit_and_message(self):
        rec = mdm.recent(days=30, limit=10, repo=self.repo)[0]
        self.assertTrue(rec["commit"])
        self.assertIn("add mod", rec["message"])

    def test_limit_is_honoured(self):
        for i in range(4):
            with open(os.path.join(self.repo, f"f{i}.py"), "w") as f:
                f.write(f"x = {i}\n")
            _git(["add", "-A"], self.repo)
            _git(["commit", "-q", "-m", f"c{i}"], self.repo)
        self.assertLessEqual(len(mdm.recent(days=30, limit=2, repo=self.repo)), 2)

    def test_bad_args_do_not_raise(self):
        for kwargs in ({"days": "x"}, {"limit": None}, {"days": -5}, {"limit": 0}):
            with self.subTest(kwargs=kwargs):
                self.assertIsInstance(mdm.recent(repo=self.repo, **kwargs), list)

    def test_missing_repo_returns_empty(self):
        self.assertEqual(mdm.recent(days=7, limit=5, repo="/nonexistent/path/xyz"), [])

    def test_caller_now_sees_real_patterns(self):
        # The point of the fix: scan_recent_diffs is no longer a permanent no-op.
        import self_authored_capabilities as sac
        orig = sac.mdm
        try:
            sac.mdm = type("M", (), {
                "recent": staticmethod(
                    lambda days=14, limit=50: mdm.recent(days=days, limit=limit,
                                                         repo=self.repo))})
            with unittest.mock.patch.object(sac, "MIN_OCCURRENCES", 1):
                found = sac.scan_recent_diffs(days=30, limit=10)
            self.assertTrue(found, "scanner should detect at least one pattern")
        finally:
            sac.mdm = orig


class TestBothApisCoexist(unittest.TestCase):
    """The restore must not drop either half of the module."""

    def test_distillation_api_present(self):
        for name in ("MEMORY_ROOT", "HOME", "run", "_extract_rules",
                     "_save_to_memory", "_update_memory_index", "_prune_old_entries"):
            self.assertTrue(hasattr(mdm, name), f"missing {name}")

    def test_metadata_api_present(self):
        for name in ("capture_merge", "get_recent_merges", "stats", "invalidate",
                     "MEMORY_DIR", "MERGED_DIFF_FILE"):
            self.assertTrue(hasattr(mdm, name), f"missing {name}")


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
