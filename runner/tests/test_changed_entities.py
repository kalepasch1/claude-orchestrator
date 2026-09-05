#!/usr/bin/env python3
"""Which functions, methods and classes a patch touched.

The task asked for a changed-entities.json of {file_path, entity_name, type,
line_numbers} derived from a patch. It also asked to run `git show 95fc17a356b7` — which
is not a commit: it is a PATCH-TEMPLATE id from runner/tests/PATCH_TEMPLATE_REGISTRY.md,
and `git cat-file -t` on it returns "Not a valid object name". Template ids and short
commit shas are both 12 hex characters in this repo and get confused constantly, so
resolve_ref() names that specific confusion instead of passing git's opaque error along.

Attribution is by AST over the post-image for Python, not by the `@@` section heading —
git fills that in heuristically and it is often wrong or empty, and every existing
consumer in this repo (the regression guard's file::symbol findings, merged_diff_library,
patch_adaptation) was relying on it.

Proof: python3 -m pytest runner/tests/test_changed_entities.py -q
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import changed_entities as ce  # noqa: E402

SOURCE = '''"""mod."""
import os


def alpha():
    return 1


class Widget:
    """A widget."""

    def method_one(self):
        return 2

    def method_two(self):
        return 3


TOP_LEVEL = 4
'''

DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
index 1111111..2222222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -3,7 +3,7 @@ import os


 def alpha():
-    return 0
+    return 1


 class Widget:
@@ -12,4 +12,4 @@ class Widget:
     def method_one(self):
-        return 0
+        return 2
"""


def _source_for(path):
    return SOURCE if path.endswith(".py") else None


class TestChangedLines(unittest.TestCase):
    def test_added_lines_are_collected_per_file(self):
        got = ce.changed_lines(DIFF)
        self.assertIn("pkg/mod.py", got)
        self.assertTrue(got["pkg/mod.py"])

    def test_deletions_do_not_invent_a_post_image_line(self):
        diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                "@@ -1,3 +1,2 @@\n line1\n-line2\n line3\n")
        self.assertEqual(ce.changed_lines(diff), {"a.py": []})

    def test_line_numbers_are_sorted_and_deduped(self):
        got = ce.changed_lines(DIFF)["pkg/mod.py"]
        self.assertEqual(got, sorted(set(got)))

    def test_a_new_file_is_handled(self):
        diff = ("diff --git a/new.py b/new.py\n--- /dev/null\n+++ b/new.py\n"
                "@@ -0,0 +1,2 @@\n+def x():\n+    return 1\n")
        self.assertEqual(ce.changed_lines(diff), {"new.py": [1, 2]})

    def test_it_is_fail_soft(self):
        for bad in (None, "", "   ", 7, [], {}):
            self.assertEqual(ce.changed_lines(bad), {}, bad)


class TestEntityAttribution(unittest.TestCase):
    def _by_name(self, rows):
        return {r["entity_name"]: r for r in rows}

    def test_a_function_change_is_attributed_to_the_function(self):
        rows = ce.analyze_diff(DIFF, source_for=_source_for)
        self.assertIn("alpha", self._by_name(rows))
        self.assertEqual(self._by_name(rows)["alpha"]["type"], "function")

    def test_a_method_is_typed_as_a_method_not_a_function(self):
        """'Restore the symbol' means something different for the two."""
        rows = ce.analyze_diff(DIFF, source_for=_source_for)
        self.assertEqual(self._by_name(rows)["method_one"]["type"], "method")

    def test_the_innermost_entity_wins(self):
        """A change inside a method belongs to the method, not the enclosing class."""
        rows = ce.analyze_diff(DIFF, source_for=_source_for)
        self.assertNotIn("Widget", self._by_name(rows))

    def test_every_row_has_the_requested_fields(self):
        for row in ce.analyze_diff(DIFF, source_for=_source_for):
            for field in ("file_path", "entity_name", "type", "line_numbers"):
                self.assertIn(field, row)
            self.assertIsInstance(row["line_numbers"], list)

    def test_module_level_change_is_typed_as_module_level_code(self):
        diff = ("diff --git a/pkg/mod.py b/pkg/mod.py\n--- a/pkg/mod.py\n"
                "+++ b/pkg/mod.py\n@@ -19,1 +19,1 @@\n-TOP_LEVEL = 3\n+TOP_LEVEL = 4\n")
        rows = ce.analyze_diff(diff, source_for=_source_for)
        self.assertEqual(rows[0]["type"], "module-level code")

    def test_a_non_python_file_falls_back_to_the_hunk_header(self):
        diff = ("diff --git a/app.ts b/app.ts\n--- a/app.ts\n+++ b/app.ts\n"
                "@@ -1,2 +1,2 @@ function handler() {\n-  return 0;\n+  return 1;\n")
        rows = ce.analyze_diff(diff, source_for=_source_for)
        self.assertEqual(rows[0]["entity_name"], "handler")

    def test_an_unparseable_python_file_degrades_instead_of_being_lost(self):
        diff = ("diff --git a/broken.py b/broken.py\n--- a/broken.py\n"
                "+++ b/broken.py\n@@ -1,1 +1,1 @@\n-x\n+y\n")
        rows = ce.analyze_diff(diff, source_for=lambda p: "def (((")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file_path"], "broken.py")

    def test_no_source_provider_still_produces_rows(self):
        rows = ce.analyze_diff(DIFF, source_for=None)
        self.assertTrue(rows)

    def test_analyze_diff_is_fail_soft(self):
        for bad in (None, "", 7, []):
            self.assertEqual(ce.analyze_diff(bad), [], bad)


class TestRefResolution(unittest.TestCase):
    def test_a_template_id_is_named_as_such(self):
        """The specific confusion in the request: a patch-template id, not a commit."""
        verdict = ce.resolve_ref("95fc17a356b7", repo=os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        self.assertFalse(verdict["ok"])
        self.assertIn("PATCH TEMPLATE", verdict["hint"])

    def test_a_real_commit_resolves(self):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        verdict = ce.resolve_ref("HEAD", repo=repo)
        self.assertTrue(verdict["ok"], verdict)

    def test_an_empty_ref_is_reported_not_guessed(self):
        self.assertFalse(ce.resolve_ref("")["ok"])
        self.assertFalse(ce.resolve_ref(None)["ok"])

    def test_a_non_hex_bad_ref_does_not_claim_template_confusion(self):
        verdict = ce.resolve_ref("no-such-branch-xyz")
        self.assertFalse(verdict["ok"])
        self.assertNotIn("PATCH TEMPLATE", verdict["hint"])

    def test_hex_id_shape(self):
        self.assertTrue(ce.looks_like_hex_id("95fc17a356b7"))
        self.assertFalse(ce.looks_like_hex_id("HEAD"))
        self.assertFalse(ce.looks_like_hex_id(None))


class TestAnalyzeAndReport(unittest.TestCase):
    def setUp(self):
        self.repo = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

    def test_a_bad_ref_returns_an_error_envelope_not_an_exception(self):
        result = ce.analyze("95fc17a356b7", repo=self.repo)
        self.assertFalse(result["ok"])
        self.assertEqual(result["changed_entities"], [])

    def test_head_analyzes(self):
        result = ce.analyze("HEAD", repo=self.repo)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIsInstance(result["changed_entities"], list)

    def test_the_report_file_is_the_bare_array(self):
        """A consumer reading the file must not mistake an envelope for zero entities."""
        path = os.path.join(tempfile.mkdtemp(), "changed-entities.json")
        ce.write_report({"ok": True, "changed_entities": [{"file_path": "a.py"}]}, path)
        with open(path) as fh:
            self.assertEqual(json.load(fh), [{"file_path": "a.py"}])

    def test_an_unwritable_report_path_returns_false(self):
        self.assertFalse(ce.write_report(
            {"changed_entities": []}, "/proc/definitely/not/writable/x.json"))

    def test_cli_reports_a_bad_ref_with_a_nonzero_exit(self):
        self.assertEqual(ce.main(["95fc17a356b7"]), 2)


if __name__ == "__main__":
    unittest.main()
