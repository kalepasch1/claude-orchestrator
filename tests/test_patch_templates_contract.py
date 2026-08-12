#!/usr/bin/env python3
"""Contract tests for runner/patch_templates.lookup(), plus a guard against the defect that
produced this file.

Provenance. This slice's own earlier run committed three files to the repo ROOT:

    Step 5: Write a Minimal Test     <- a markdown heading used as a filename
    unittest.main()                  <- a line of code used as a filename (0 bytes)
    test_template_95fc17a.py         <- contained only its own filename as its body

An agent parsed the prose and code lines of a "write a minimal test" template as if they were
file paths, and the result reached master. The intended test lived inside the file named
`Step 5: Write a Minimal Test` and did not run — it imported `lookup` but then referenced
`patch_templates`, which was never imported.

This file is that test, recovered and made to actually run, plus `RootHygieneTest`, which fails
if the repo root gains another prose-named file. A defect that ships its own artifact into the
tree is worth a regression test, not just a cleanup.
"""
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "runner"))

import patch_templates  # noqa: E402


class LookupContractTest(unittest.TestCase):
    """lookup() exists and honors the documented fail-soft contract."""

    def test_lookup_is_exposed(self):
        self.assertTrue(callable(getattr(patch_templates, "lookup", None)),
                        "patch_templates.lookup(template_id) must exist")

    def test_empty_id_returns_empty_mapping_and_does_not_raise(self):
        for empty in ("", "   ", None):
            self.assertEqual(patch_templates.lookup(empty), {})

    def test_unknown_id_returns_empty_mapping(self):
        self.assertEqual(patch_templates.lookup("definitely-not-a-real-template-id-000"), {})

    def test_lookup_always_returns_a_mapping(self):
        for candidate in ("", "nope", 12345, ["not", "a", "string"]):
            self.assertIsInstance(patch_templates.lookup(candidate), dict)

    def test_lookup_is_fail_soft_when_the_fallback_file_is_unreadable(self):
        """A missing or unreadable store is a miss, never an exception."""
        original = patch_templates._fallback_path
        patch_templates._fallback_path = lambda: "/nonexistent-dir-xyz/templates.jsonl"
        try:
            self.assertEqual(patch_templates.lookup("anything"), {})
        finally:
            patch_templates._fallback_path = original


class RootHygieneTest(unittest.TestCase):
    """The repo root must not accumulate prose-named files from template regeneration."""

    # Characters that never belong in a tracked root filename but are common in prose and code
    # lines: spaces, colons, and call parentheses.
    PROSE_NAME = re.compile(r"[ :()]")
    # Legitimate exceptions, if any are ever added, go here with a reason.
    ALLOWED = set()

    def _tracked_root_files(self):
        out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest("not a git checkout")
        return [p for p in out.stdout.splitlines() if p and "/" not in p]

    def test_no_prose_named_files_in_repo_root(self):
        offenders = [p for p in self._tracked_root_files()
                     if self.PROSE_NAME.search(p) and p not in self.ALLOWED]
        self.assertEqual(offenders, [], (
            "Prose-named files in the repo root. These are almost always a template "
            "regeneration writing a markdown heading or a line of code as a filename: "
            f"{offenders}"))

    def test_no_root_file_whose_body_is_just_its_own_name(self):
        """`test_template_95fc17a.py` contained only the string `test_template_95fc17a.py`."""
        offenders = []
        for name in self._tracked_root_files():
            path = os.path.join(REPO, name)
            try:
                if os.path.getsize(path) > 200:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read().strip()
            except OSError:
                continue
            if body and body == name.strip():
                offenders.append(name)
        self.assertEqual(offenders, [],
                         f"Root files whose entire content is their own filename: {offenders}")


if __name__ == "__main__":
    unittest.main()
