"""bot_commit_verifier: the hisanta failure mode — a bot commit that does not parse."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot_commit_verifier

# The exact damage ssw-quality-bot did in hisanta 74b0cfd9: it REMOVED a backslash escape.
BROKEN_TSX = "export const fr = ['Réglages de langue', 'Centre d'aide']\n"
FIXED_TSX = "export const fr = ['Réglages de langue', 'Centre d\\'aide']\n"


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


class BotCommitVerifierTest(unittest.TestCase):

    def setUp(self):
        self.roots = []

    def tearDown(self):
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def _repo(self):
        root = tempfile.mkdtemp(prefix="bcv-test-")
        self.roots.append(root)
        _git(root, "init", "-q", ".")
        _git(root, "config", "user.email", "t@t")
        _git(root, "config", "user.name", "t")
        return root

    def _commit(self, root, files, message):
        for rel, body in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path) or root, exist_ok=True)
            with open(path, "w") as f:
                f.write(body)
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", message)
        return _git(root, "rev-parse", "HEAD").stdout.strip()

    # ── convention detection ────────────────────────────────────────────────
    def test_recognises_this_fleets_bot_conventions(self):
        for subject in ("bot: auto-fix TypeScript errors [ssw-quality-bot]",
                        "bot: polish log [ssw-polish-bot]",
                        "agent: remediate-weekly-lint-santas-secret-workshop-21ba53",
                        "chore: update ssw-bot-log for game-bot run [ssw-game-bot]",
                        "Merge branch 'agent/tomorrow-judgment-compression'"):
            self.assertTrue(bot_commit_verifier.is_bot_commit(subject), subject)

    def test_does_not_flag_ordinary_human_commits(self):
        for subject in ("feat: showcase complete HiSanta growth loop",
                        "fix: preserve HiSanta logo hat in header",
                        "chore: bump deps"):
            self.assertFalse(bot_commit_verifier.is_bot_commit(subject), subject)

    def test_bot_author_email_alone_is_enough(self):
        self.assertTrue(bot_commit_verifier.is_bot_commit(
            "chore: nightly", "ssw-bot <bot@example.com>"))

    # ── syntax checking ─────────────────────────────────────────────────────
    def test_broken_javascript_is_caught_by_node_check(self):
        root = self._repo()
        sha = self._commit(root, {"a.js": "const s = 'Centre d'aide';\n"},
                           "bot: auto-fix [ssw-quality-bot]")
        result = bot_commit_verifier.verify_commit(root, sha, force=True)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["problems"][0]["checker"], "node --check")

    def test_broken_python_is_caught(self):
        root = self._repo()
        sha = self._commit(root, {"a.py": "def f(:\n    pass\n"}, "bot: tidy [ssw-quality-bot]")
        result = bot_commit_verifier.verify_commit(root, sha, force=True)
        self.assertFalse(result["ok"], result)

    def test_broken_json_is_caught(self):
        root = self._repo()
        sha = self._commit(root, {"a.json": '{"a": 1,,}\n'}, "bot: config [ssw-quality-bot]")
        result = bot_commit_verifier.verify_commit(root, sha, force=True)
        self.assertFalse(result["ok"], result)

    def test_valid_commit_passes(self):
        root = self._repo()
        sha = self._commit(root, {"a.js": "const s = 'ok';\n"}, "bot: fine [ssw-quality-bot]")
        with patch.object(bot_commit_verifier, "proof_graph", MagicMock()):
            result = bot_commit_verifier.verify_commit(root, sha, force=True)
        self.assertTrue(result["ok"], result)

    def test_the_hisanta_escape_regression_in_tsx(self):
        """Skips cleanly when no tsc is reachable; asserts the catch when one is."""
        root = self._repo()
        sha = self._commit(root, {"c.tsx": BROKEN_TSX}, "bot: auto-fix TypeScript errors [ssw-quality-bot]")
        result = bot_commit_verifier.verify_commit(root, sha, force=True)
        if result["problems"] and result["problems"][0].get("skipped"):
            self.skipTest("no typescript available on this machine")
        self.assertFalse(result["ok"], result)
        self.assertIn("TS1", result["problems"][0]["error"])

    def test_compiler_flag_diagnostics_are_not_treated_as_parse_errors(self):
        """TS1343 (import.meta needs --module) is config noise, not bot damage."""
        root = self._repo()
        sha = self._commit(root, {"c.ts": "export const u = import.meta.url\n"},
                           "agent: weekly-lint")
        with patch.object(bot_commit_verifier, "proof_graph", MagicMock()):
            result = bot_commit_verifier.verify_commit(root, sha, force=True)
        real = [p for p in result["problems"] if not p.get("skipped")]
        self.assertEqual(real, [])

    def test_a_tsc_that_cannot_run_is_unchecked_not_clean(self):
        """Regression: a broken node_modules/.bin/tsc symlink emits no diagnostics. Treating
        that silence as 'parses fine' would turn the whole gate into a no-op."""
        root = self._repo()
        with patch.object(bot_commit_verifier, "_run",
                          return_value=(1, "Error: Cannot find module '/x/typescript/bin/tsc'")):
            problems = bot_commit_verifier.syntax_check_paths(["a.tsx"], tsc="/x/tsc")
        self.assertEqual(len(problems), 1)
        self.assertIn("could not run", problems[0]["skipped"])

    def test_tsc_discovery_rejects_a_binary_that_does_not_execute(self):
        root = self._repo()
        os.makedirs(os.path.join(root, "node_modules", ".bin"))
        fake = os.path.join(root, "node_modules", ".bin", "tsc")
        with open(fake, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(fake, 0o755)
        self.assertEqual(bot_commit_verifier._tsc_in(root), "")

    def test_commits_with_no_source_files_are_skipped(self):
        root = self._repo()
        sha = self._commit(root, {"LOG.md": "# log\n"}, "bot: quality log update")
        result = bot_commit_verifier.verify_commit(root, sha, force=True)
        self.assertIsNotNone(result["skipped"])

    # ── gate behaviour ──────────────────────────────────────────────────────
    def test_gate_is_fail_closed_on_a_broken_bot_commit(self):
        root = self._repo()
        self._commit(root, {"base.js": "1\n"}, "feat: base")
        _git(root, "branch", "base")
        self._commit(root, {"a.js": "const s = 'Centre d'aide';\n"},
                     "bot: auto-fix [ssw-quality-bot]")
        with patch.object(bot_commit_verifier, "db", MagicMock()):
            ok, log = bot_commit_verifier.gate("test", "HEAD", base="base", repo=root)
        self.assertFalse(ok)
        self.assertIn("do NOT parse", log)

    def test_gate_passes_a_branch_whose_bot_commits_parse(self):
        root = self._repo()
        self._commit(root, {"base.js": "1\n"}, "feat: base")
        _git(root, "branch", "base")
        self._commit(root, {"a.js": "const s = 'ok';\n"}, "bot: auto-fix [ssw-quality-bot]")
        with patch.object(bot_commit_verifier, "db", MagicMock()), \
             patch.object(bot_commit_verifier, "proof_graph", MagicMock()):
            ok, log = bot_commit_verifier.gate("test", "HEAD", base="base", repo=root)
        self.assertTrue(ok, log)

    def test_gate_ignores_human_commits(self):
        root = self._repo()
        self._commit(root, {"base.js": "1\n"}, "feat: base")
        _git(root, "branch", "base")
        self._commit(root, {"a.js": "const s = 'Centre d'aide';\n"}, "feat: human change")
        with patch.object(bot_commit_verifier, "db", MagicMock()):
            ok, log = bot_commit_verifier.gate("test", "HEAD", base="base", repo=root)
        self.assertTrue(ok)
        self.assertIn("no bot-authored commits", log)

    def test_check_paths_at_reads_the_ref_not_the_working_tree(self):
        root = self._repo()
        self._commit(root, {"a.js": "const s = 'ok';\n"}, "bot: fine [ssw-quality-bot]")
        with open(os.path.join(root, "a.js"), "w") as f:
            f.write("const s = 'Centre d'aide';\n")   # broken on disk only, never committed
        problems = bot_commit_verifier.check_paths_at(root, "HEAD", ["a.js"])
        self.assertEqual([p for p in problems if not p.get("skipped")], [])


if __name__ == "__main__":
    unittest.main()
