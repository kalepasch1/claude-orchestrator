import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import repo_hygiene


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


def _init_git_repo(repo):
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _write(repo, rel, content=""):
    full = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)
    return full


class RepoHygieneTest(unittest.TestCase):
    """2026-07-10: an untracked compiled .js shadowing its .ts source broke every test/build
    touching it in two separate projects the same day (10 files in one, 4106 in another).
    These tests cover the safety invariant that made manual cleanup safe both times: only
    remove files git doesn't track; never touch a tracked collision."""

    def test_esm_project_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            self.assertTrue(repo_hygiene._is_esm_project(tmp))

    def test_non_esm_project_not_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "package.json", json.dumps({"name": "x"}))
            self.assertFalse(repo_hygiene._is_esm_project(tmp))

    def test_missing_package_json_is_not_esm(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(repo_hygiene._is_esm_project(tmp))

    def test_untracked_stray_js_is_found_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            _write(tmp, "server/middleware/csrf.ts", "export default () => {}")
            stray = _write(tmp, "server/middleware/csrf.js", "module.exports = () => {}")
            _git(tmp, "add", "package.json", "server/middleware/csrf.ts")
            _git(tmp, "commit", "-q", "-m", "init")
            # csrf.js was never added -- untracked, exactly like tomorrow's 4106 files
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, ["server/middleware/csrf.js"])
            self.assertFalse(os.path.exists(stray))

    def test_tracked_collision_is_never_touched(self):
        """A .js/.ts pair that IS committed is a real content decision (e.g. beethoven's
        web/ case) -- must be left alone for a human, never auto-deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            _write(tmp, "web/nuxt.config.ts", "export default {}")
            tracked_js = _write(tmp, "web/nuxt.config.js", "exports.default = {}")
            _git(tmp, "add", "-A")
            _git(tmp, "commit", "-q", "-m", "init (both committed)")
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(tracked_js))

    def test_non_esm_project_is_never_touched_even_with_untracked_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"name": "x"}))  # no "type": "module"
            _write(tmp, "lib/util.ts", "export {}")
            stray = _write(tmp, "lib/util.js", "module.exports = {}")
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(stray))

    def test_js_without_ts_sibling_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            legit = _write(tmp, "scripts/build.js", "console.log('ok')")
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(legit))

    def test_node_modules_and_dist_are_never_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            _write(tmp, "node_modules/pkg/index.ts", "export {}")
            nm_js = _write(tmp, "node_modules/pkg/index.js", "module.exports = {}")
            _write(tmp, "dist/out.ts", "export {}")
            dist_js = _write(tmp, "dist/out.js", "module.exports = {}")
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(nm_js))
            self.assertTrue(os.path.exists(dist_js))

    def test_git_query_failure_fails_closed_no_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            _write(tmp, "server/x.ts", "export {}")
            stray = _write(tmp, "server/x.js", "module.exports = {}")
            with patch.object(repo_hygiene, "_tracked_files", return_value=None):
                removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(stray))

    def test_bulk_scale_matches_tomorrow_incident(self):
        """Regression scale-check: hundreds of untracked stray files across many nested
        directories (the actual shape of the tomorrow/ incident) are all found and removed,
        and nothing tracked gets caught in the sweep."""
        with tempfile.TemporaryDirectory() as tmp:
            _init_git_repo(tmp)
            _write(tmp, "package.json", json.dumps({"type": "module"}))
            _git(tmp, "add", "package.json")
            _git(tmp, "commit", "-q", "-m", "init")
            expected = []
            for i in range(50):
                _write(tmp, f"server/tasks/group{i}/job.ts", "export {}")
                _write(tmp, f"server/tasks/group{i}/job.js", "module.exports = {}")
                expected.append(f"server/tasks/group{i}/job.js")
            removed = repo_hygiene.clean_stray_js_duplicates(tmp)
            self.assertEqual(sorted(removed), sorted(expected))
            for rel in expected:
                self.assertFalse(os.path.exists(os.path.join(tmp, rel)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
