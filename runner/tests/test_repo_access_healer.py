"""Tests for repo_access_healer — self-healing for repo not found / PAT access failures."""
import unittest


class TestRepoAccessHealer(unittest.TestCase):

    def test_is_repo_access_failure_patterns(self):
        from runner.repo_access_healer import is_repo_access_failure
        self.assertTrue(is_repo_access_failure("repo not found / PAT lacks access"))
        self.assertTrue(is_repo_access_failure("fatal: repository 'https://...' not found"))
        self.assertTrue(is_repo_access_failure("remote: Repository not found."))
        self.assertTrue(is_repo_access_failure("could not read from remote repository"))
        self.assertTrue(is_repo_access_failure("Authentication failed for 'https://...'"))
        self.assertFalse(is_repo_access_failure("syntax error in line 42"))
        self.assertFalse(is_repo_access_failure(""))
        self.assertFalse(is_repo_access_failure(None))

    def test_diagnose_repo_missing_path(self):
        from runner.repo_access_healer import diagnose_repo
        healthy, msg = diagnose_repo(None)
        self.assertFalse(healthy)
        self.assertIn("no repo path", msg)

    def test_diagnose_repo_nonexistent_dir(self):
        from runner.repo_access_healer import diagnose_repo
        healthy, msg = diagnose_repo("/tmp/nonexistent-repo-abc123")
        self.assertFalse(healthy)
        self.assertIn("does not exist", msg)

    def test_diagnose_repo_not_git(self):
        import tempfile, os
        from runner.repo_access_healer import diagnose_repo
        with tempfile.TemporaryDirectory() as d:
            healthy, msg = diagnose_repo(d)
            self.assertFalse(healthy)
            self.assertIn("not a git repo", msg)


if __name__ == "__main__":
    unittest.main()
