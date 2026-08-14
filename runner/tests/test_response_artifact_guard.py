"""Guard against an LLM reply being committed as a file tree.

Reconstructed from a real incident: commit 6f82f95d ("regen-from-cache(template)",
2026-08-05) landed three files in the beethoven repo root —

    "Step 5: Write a Minimal Test"    a prose heading, containing python
    "test_template_95fc17a.py"        content was the literal string of its own name
    "unittest.main()"                 an EMPTY file named after a line of code

— because a coder's prose reply was parsed as a file manifest. They reached
orchestrator/dev before being removed by hand, and the branch carrying them
(agent/...-recover-remaining--slice-1) then sat QUEUED behind a stale "merge would
DELETE or STUB code" regression note long after the content was gone.

The three real filenames are used verbatim below: a guard written against paraphrased
inputs proves nothing about the case that actually occurred.

Proof: python3 -m unittest runner.tests.test_response_artifact_guard -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import repo_hygiene


class ResponseArtifactGuardTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="artifact-guard-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.repo], check=False))
        self._git("init", "-q")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "test")

    def _git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo,
                              capture_output=True, text=True, timeout=30)

    def _write(self, rel, body=""):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(rel) else None
        with open(path, "w") as f:
            f.write(body)
        self._git("add", "-A")
        self._git("commit", "-qm", "add", "--no-verify")
        return rel

    # ── the incident, reproduced ─────────────────────────────────────────────
    def test_detects_the_three_files_from_the_real_incident(self):
        self._write("Step 5: Write a Minimal Test", "import unittest\n")
        self._write("test_template_95fc17a.py", "test_template_95fc17a.py")
        self._write("unittest.main()", "")
        found = repo_hygiene.find_response_artifacts(self.repo)
        self.assertEqual(
            sorted(found),
            sorted(["Step 5: Write a Minimal Test", "test_template_95fc17a.py",
                    "unittest.main()"]))

    def test_call_expression_filename_is_flagged(self):
        self._write("unittest.main()", "")
        self.assertIn("unittest.main()", repo_hygiene.find_response_artifacts(self.repo))

    def test_prose_heading_filename_is_flagged(self):
        self._write("Step 5: Write a Minimal Test", "x")
        self.assertIn("Step 5: Write a Minimal Test",
                      repo_hygiene.find_response_artifacts(self.repo))

    def test_python_file_containing_only_its_own_name_is_flagged(self):
        """The code-fence filename comment captured as though it were the body."""
        self._write("test_template_95fc17a.py", "test_template_95fc17a.py\n")
        self.assertIn("test_template_95fc17a.py",
                      repo_hygiene.find_response_artifacts(self.repo))

    def test_code_fence_filename_is_flagged(self):
        self._write("```python", "print(1)")
        self.assertIn("```python", repo_hygiene.find_response_artifacts(self.repo))

    # ── the far more important half: no false positives ──────────────────────
    def test_ordinary_source_files_are_not_flagged(self):
        for rel in ("runner/merge_train.py", "runner/tests/test_merge_train.py",
                    "README.md", "docs/recovery/notes.md", "package.json",
                    "runner/migrations/002_repository_delivery_leases.sql",
                    ".github/workflows/ci.yml", "web/app/[slug].vue"):
            self._write(rel, "real content\n")
        self.assertEqual(repo_hygiene.find_response_artifacts(self.repo), [])

    def test_a_python_file_named_after_its_subject_is_not_flagged(self):
        """Guard against the naive rule 'content mentions the filename'."""
        self._write("test_template.py",
                    "import unittest\n# tests for test_template.py\n"
                    "class T(unittest.TestCase):\n    pass\n")
        self.assertEqual(repo_hygiene.find_response_artifacts(self.repo), [])

    def test_human_filenames_with_parentheses_are_not_flagged(self):
        """Real false positive from the first draft, found on the smarter repo.

        Parentheses are ordinary in human filenames; a name ENDING in a call expression
        is not. This is the case that forced the paren rule to anchor to the end.
        """
        self._write("Kale Pasch Resume (6.23.2026) - Revised.docx", "content")
        self._write("report (final) (v2).pdf", "content")
        self.assertEqual(repo_hygiene.find_response_artifacts(self.repo), [])

    def test_prose_appended_after_an_extension_is_flagged(self):
        """Real true positive found on the apparently repo."""
        self._write("hive-ops-dashboards/candidate-list.vue (assuming this is a Vue component)",
                    "<template></template>")
        self.assertIn(
            "hive-ops-dashboards/candidate-list.vue (assuming this is a Vue component)",
            repo_hygiene.find_response_artifacts(self.repo))

    def test_a_whole_source_file_captured_as_a_filename_is_flagged(self):
        """Real true positive found on claude-orchestrator: the body became the path."""
        self.assertTrue(repo_hygiene._looks_like_response_artifact(
            "runner/utils/auto_branch_cleanup.py\\nimport os\\nENABLED = False", self.repo))

    def test_dotfiles_and_hyphenated_names_are_not_flagged(self):
        for rel in (".gitignore", ".env.example", "some-file.test.ts", "a_b-c.d.py"):
            self._write(rel, "content\n")
        self.assertEqual(repo_hygiene.find_response_artifacts(self.repo), [])

    def test_untracked_junk_is_ignored(self):
        """Only tracked files matter; untracked local mess is not this guard's business."""
        with open(os.path.join(self.repo, "unittest.main()"), "w") as f:
            f.write("")
        self.assertEqual(repo_hygiene.find_response_artifacts(self.repo), [])

    def test_fails_closed_when_git_is_unavailable(self):
        """Consistent with the rest of repo_hygiene: unverifiable means do nothing."""
        self.assertEqual(repo_hygiene.find_response_artifacts("/nonexistent/path"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
