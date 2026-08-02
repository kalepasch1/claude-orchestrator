#!/usr/bin/env python3
"""
test_write_guard.py - regression coverage for the agent write-path validator.

Anchored on the real 2026-08-02 incident (commits b91c80d0 / a31833c9): a single
LLM response left four files at the repo root, which `git add -A` committed -

    "Step 5: Write a Minimal Test"  (markdown heading used as a path)
    "unittest.main()"              (code fragment used as a path)
    "test_template_95fc17a.py"      (test at repo root; body == its own filename)

The third broke `pytest --collect-only` repo-wide with
`NameError: name 'test_template_95fc17a' is not defined`.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runner"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import write_guard  # noqa: E402


# The literal 13-line body the incident wrote to two different "paths".
INCIDENT_BODY = (
    "# test_template_95fc17a.py\n"
    "import unittest\n"
    "from patch_templates import lookup\n"
    "\n"
    "class LookupContractTest(unittest.TestCase):\n"
    '    """lookup() exists and honors the fail-soft contract."""\n'
    "\n"
    "    def test_lookup_is_exposed(self):\n"
    "        self.assertTrue(True)\n"
    "\n"
    'if __name__ == "__main__":\n'
    "    unittest.main()\n"
)


class IncidentArtifactsTest(unittest.TestCase):
    """Every artifact the 2026-08-02 incident produced must now be refused."""

    def test_markdown_heading_is_refused(self):
        reason = write_guard.check("Step 5: Write a Minimal Test", INCIDENT_BODY)
        self.assertIsNotNone(reason, "markdown heading must not be a valid path")
        self.assertIn("prose", reason.lower())

    def test_code_fragment_is_refused(self):
        reason = write_guard.check("unittest.main()", "")
        self.assertIsNotNone(reason, "code fragment must not be a valid path")
        self.assertIn("code fragment", reason.lower())

    def test_content_equal_to_own_filename_is_refused(self):
        """The exact a31833c9 failure: body is literally the file's own name."""
        reason = write_guard.check("runner/tests/test_template_95fc17a.py",
                                   "test_template_95fc17a.py")
        self.assertIsNotNone(reason)
        self.assertIn("identical to its own file name", reason)

    def test_test_file_at_repo_root_is_refused(self):
        """b91c80d0 put a real test suite at the root and broke collection."""
        reason = write_guard.check("test_template_95fc17a.py", INCIDENT_BODY)
        self.assertIsNotNone(reason)
        self.assertIn("repo root", reason)

    def test_the_real_suite_location_is_allowed(self):
        """runner/tests/test_template_95fc17a.py is the legitimate file."""
        self.assertIsNone(
            write_guard.check("runner/tests/test_template_95fc17a.py", INCIDENT_BODY))


class PathSafetyTest(unittest.TestCase):
    def test_absolute_paths_refused(self):
        self.assertIsNotNone(write_guard.check("/etc/passwd", "x"))

    def test_parent_traversal_refused(self):
        self.assertIsNotNone(write_guard.check("../../secrets.env", "x"))

    def test_dot_git_refused(self):
        self.assertIsNotNone(write_guard.check(".git/config", "x"))

    def test_control_characters_refused(self):
        self.assertIsNotNone(write_guard.check("a\nb.py", "x"))
        self.assertIsNotNone(write_guard.check("a\tb.py", "x"))

    def test_spaces_without_extension_refused(self):
        self.assertIsNotNone(write_guard.check("Write a Minimal Test", "x"))

    def test_trailing_whitespace_in_name_refused(self):
        self.assertIsNotNone(write_guard.check("module.py ", "x"))

    def test_overlong_path_refused(self):
        self.assertIsNotNone(write_guard.check("d/" + ("a" * 300) + ".py", "x"))


class LegitimateWritesTest(unittest.TestCase):
    """The guard must not get in the way of ordinary agent work."""

    def test_ordinary_source_file(self):
        self.assertIsNone(write_guard.check("runner/patch_templates.py", "x = 1\n"))

    def test_existing_runner_test_convention(self):
        """89 tracked files use runner/test_*.py - that convention must survive."""
        self.assertIsNone(write_guard.check("runner/test_tdd_gate.py", "x = 1\n"))

    def test_nested_tests_dir(self):
        self.assertIsNone(write_guard.check("runner/tests/e2e/test_thing.py", "x = 1\n"))

    def test_nextjs_dynamic_route_not_refused(self):
        """Square brackets are legitimate in this fleet's Next.js projects."""
        self.assertIsNone(write_guard.check("app/[slug]/page.tsx", "export default x\n"))

    def test_dotfiles_and_configs(self):
        self.assertIsNone(write_guard.check(".github/workflows/ci.yml", "on: push\n"))

    def test_content_check_is_optional(self):
        self.assertIsNone(write_guard.check("runner/thing.py"))


class PartitionTest(unittest.TestCase):
    def test_partition_splits_good_from_bad(self):
        paths = [
            "runner/good.py",
            "Step 5: Write a Minimal Test",
            "unittest.main()",
            "test_template_95fc17a.py",
        ]
        bodies = {
            "runner/good.py": "x = 1\n",
            "Step 5: Write a Minimal Test": INCIDENT_BODY,
            "unittest.main()": "",
            "test_template_95fc17a.py": "test_template_95fc17a.py",
        }
        ok, rejected = write_guard.partition(paths, read=bodies.get)
        self.assertEqual(ok, ["runner/good.py"])
        self.assertEqual(len(rejected), 3)
        self.assertTrue(all(isinstance(r, tuple) and r[1] for r in rejected))

    def test_partition_survives_unreadable_files(self):
        def boom(_):
            raise OSError("nope")
        ok, rejected = write_guard.partition(["runner/good.py"], read=boom)
        self.assertEqual(ok, ["runner/good.py"])
        self.assertEqual(rejected, [])

    def test_enforce_raises(self):
        with self.assertRaises(write_guard.WriteGuardError):
            write_guard.enforce("unittest.main()", "")
        self.assertEqual(write_guard.enforce("runner/ok.py", "x = 1\n"), "runner/ok.py")


class KillSwitchTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("ORCH_WRITE_GUARD", None)

    def test_guard_can_be_disabled(self):
        os.environ["ORCH_WRITE_GUARD"] = "off"
        self.assertIsNone(write_guard.check("unittest.main()", ""))

    def test_guard_on_by_default(self):
        self.assertIsNotNone(write_guard.check("unittest.main()", ""))


if __name__ == "__main__":
    unittest.main()
