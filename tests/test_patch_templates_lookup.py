"""Contract tests for patch_templates.lookup(template_id).

The prior canary run tried to write this via aider and produced a garbage
file (undefined-name F821, no valid filename). This is the recovered intent:
lookup() exists, honors the fail-soft contract ({} on any miss/error, never
raises), and the JSONL fallback resolves newest-matching-entry-wins.
"""
import json
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner"))

# Mock db before importing patch_templates so no network/Supabase is touched.
mock_db = types.ModuleType("db")
mock_db.select = lambda *a, **kw: []
mock_db.insert = lambda *a, **kw: None
sys.modules["db"] = mock_db

import patch_templates  # noqa: E402


class LookupContractTest(unittest.TestCase):
    """lookup() exists and honors the fail-soft contract."""

    def test_lookup_is_exposed(self):
        self.assertTrue(callable(getattr(patch_templates, "lookup", None)),
                        "patch_templates.lookup(template_id) must exist")

    def test_blank_and_none_ids_return_empty_dict(self):
        self.assertEqual(patch_templates.lookup(""), {})
        self.assertEqual(patch_templates.lookup(None), {})
        self.assertEqual(patch_templates.lookup("   "), {})

    def test_unknown_id_fails_soft(self):
        # No JSONL fallback file + empty db → {} rather than an exception.
        original = patch_templates._fallback_path
        patch_templates._fallback_path = lambda: "/nonexistent/patch_templates.jsonl"
        try:
            self.assertEqual(patch_templates.lookup("no-such-template"), {})
        finally:
            patch_templates._fallback_path = original

    def test_db_errors_fail_soft(self):
        def boom(*a, **kw):
            raise RuntimeError("db unavailable")
        original_select = mock_db.select
        mock_db.select = boom
        try:
            self.assertEqual(patch_templates.lookup("any-id"), {})
        finally:
            mock_db.select = original_select


import tempfile  # noqa: E402


class LookupJsonlFallbackTest(unittest.TestCase):
    def test_newest_matching_jsonl_entry_wins_and_garbage_lines_skip(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write("not json at all\n")
            f.write(json.dumps({"template_id": "t1", "body": "old"}) + "\n")
            f.write(json.dumps({"template_id": "t2", "body": "other"}) + "\n")
            f.write(json.dumps({"template_id": "t1", "body": "new"}) + "\n")
            path = f.name
        original = patch_templates._fallback_path
        patch_templates._fallback_path = lambda: path
        try:
            row = patch_templates.lookup("t1")
            self.assertEqual(row.get("body"), "new")
            self.assertEqual(patch_templates.lookup("t3"), {})
        finally:
            patch_templates._fallback_path = original
            os.unlink(path)



if __name__ == "__main__":
    unittest.main()
