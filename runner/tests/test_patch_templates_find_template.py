#!/usr/bin/env python3
"""patch_templates.find_template(slug) — resolve a reusable patch by task slug.

`dependency_stub._try_patch_template` guards its call with
`hasattr(patch_templates, "find_template")`. The attribute did not exist, so
that whole recovery path returned None every time it ran: dead code hidden
behind a hasattr. These cases pin the contract the caller already assumes —
an applicable hit carries `diff`, an inapplicable one does not, and nothing
raises.

Proof: python3 -m unittest runner.tests.test_patch_templates_find_template -v
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import patch_templates as pt

SLUG = "recover-missing-branch-toolchain-repair-6096aa2b"
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"


def _jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


class CallerContractTest(unittest.TestCase):
    """The exact shape dependency_stub._try_patch_template consumes."""

    def test_find_template_is_exposed(self):
        self.assertTrue(callable(getattr(pt, "find_template", None)),
                        "dependency_stub gates on hasattr(patch_templates, 'find_template')")

    def test_none_slug_returns_empty_dict(self):
        self.assertEqual(pt.find_template(None), {})

    def test_empty_slug_returns_empty_dict(self):
        self.assertEqual(pt.find_template(""), {})
        self.assertEqual(pt.find_template("   "), {})

    def test_never_raises_when_db_is_down(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", side_effect=RuntimeError("db down")):
                self.assertEqual(pt.find_template(SLUG), {})


class MergedDiffHitTest(unittest.TestCase):
    """A merged_diffs row is applicable, so the `diff` key must be present."""

    def test_diff_is_returned_for_a_known_slug(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select",
                              return_value=[{"slug": SLUG, "diff": DIFF, "project": "beethoven"}]):
                row = pt.find_template(SLUG)
        self.assertEqual(row.get("diff"), DIFF)
        self.assertEqual(row.get("source"), "merged_diffs")

    def test_blank_diff_is_not_treated_as_a_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=[{"slug": SLUG, "diff": "   "}]):
                self.assertEqual(pt.find_template(SLUG), {})

    def test_lookup_is_scoped_to_the_requested_slug(self):
        seen = {}

        def fake_select(table, params=None):
            seen.update(params or {})
            return []
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", fake_select):
                pt.find_template(SLUG)
        self.assertEqual(seen.get("slug"), f"eq.{SLUG}")
        self.assertEqual(seen.get("order"), "created_at.desc")


class JsonlFallbackTest(unittest.TestCase):
    """A scaffold body is NOT applicable: no `diff` key, so the caller no-ops."""

    def test_scaffold_hit_carries_no_diff_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "task": SLUG, "template_id": "abc123456789",
                           "body": "PATCH TEMPLATE abc123456789"}])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", return_value=[]):
                row = pt.find_template(SLUG)
        self.assertEqual(row.get("source"), "jsonl")
        self.assertNotIn("diff", row)
        self.assertFalse(row.get("diff"))  # the caller's guard makes this a no-op

    def test_newest_matching_entry_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [
                {"ts": 1.0, "task": SLUG, "template_id": "old000000000", "body": "old"},
                {"ts": 2.0, "task": "unrelated", "template_id": "xxx000000000", "body": "x"},
                {"ts": 3.0, "task": SLUG, "template_id": "new000000000", "body": "new"},
            ])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", return_value=[]):
                row = pt.find_template(SLUG)
        self.assertEqual(row.get("template_id"), "new000000000")

    def test_corrupt_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, ["{not json", "", {"ts": 1.0, "task": SLUG, "body": "survives"}, "[1,2]"])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", return_value=[]):
                row = pt.find_template(SLUG)
        self.assertEqual(row.get("body"), "survives")

    def test_merged_diff_takes_precedence_over_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "task": SLUG, "body": "scaffold"}])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", return_value=[{"slug": SLUG, "diff": DIFF}]):
                row = pt.find_template(SLUG)
        self.assertEqual(row.get("source"), "merged_diffs")

    def test_unknown_slug_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "task": "something-else", "body": "b"}])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", return_value=[]):
                self.assertEqual(pt.find_template(SLUG), {})


class DependencyStubIntegrationTest(unittest.TestCase):
    """The caller's hasattr gate now opens."""

    def test_dependency_stub_sees_the_attribute(self):
        import dependency_stub
        self.assertIsNotNone(dependency_stub.patch_templates)
        self.assertTrue(hasattr(dependency_stub.patch_templates, "find_template"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
