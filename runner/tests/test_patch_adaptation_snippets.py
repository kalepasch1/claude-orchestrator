#!/usr/bin/env python3
"""Reusable-snippet abstraction in patch_adaptation.

`extract_patterns` records that a prior merged diff *defined* a symbol, but a
bare name does not carry the shape of the change, so a coder handed only names
redrafts the abstraction instead of adapting it. `reusable_snippets` lifts the
added body of each top-level definition out of the diff so the concrete code
change survives into the patch template.

These tests pin the contract that makes the abstraction safe to inject:
only added lines are read, bodies are dedented and truncated, snippet count is
bounded, and every entry point stays fail-soft on garbage input.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import patch_adaptation as pa


PY_DIFF = """diff --git a/runner/thing.py b/runner/thing.py
--- a/runner/thing.py
+++ b/runner/thing.py
@@ -1,3 +1,9 @@
 import os
+
+def normalize_slug(slug):
+    \"\"\"Strip separators so the slug is path-inert.\"\"\"
+    cleaned = slug.strip().lower()
+    return cleaned.replace("/", "-")
+
 EXISTING = 1
"""

TS_DIFF = """diff --git a/app/util.ts b/app/util.ts
+++ b/app/util.ts
@@ -0,0 +1,6 @@
+export interface ClaimResult {
+  ok: boolean;
+}
+export async function claimTask(id: string) {
+  return fetch(`/api/claim/${id}`);
+}
"""


class ReusableSnippetsTests(unittest.TestCase):
    def test_lifts_python_function_with_signature_and_body(self):
        snippets = pa.reusable_snippets(PY_DIFF)
        self.assertEqual([s["name"] for s in snippets], ["normalize_slug"])
        snip = snippets[0]
        self.assertEqual(snip["kind"], "function")
        self.assertEqual(snip["language"], "python")
        self.assertTrue(snip["signature"].startswith("def normalize_slug("))
        self.assertIn('cleaned = slug.strip().lower()', snip["body"])

    def test_body_is_dedented_to_read_as_standalone_code(self):
        body = pa.reusable_snippets(PY_DIFF)[0]["body"]
        code_lines = [ln for ln in body.splitlines() if ln.strip()]
        self.assertTrue(code_lines)
        # Original body was indented four spaces inside the def; dedent removes it.
        self.assertFalse(any(ln.startswith("    ") for ln in code_lines), body)

    def test_lifts_typescript_interface_and_function(self):
        snippets = pa.reusable_snippets(TS_DIFF)
        by_name = {s["name"]: s for s in snippets}
        self.assertIn("ClaimResult", by_name)
        self.assertIn("claimTask", by_name)
        self.assertEqual(by_name["ClaimResult"]["kind"], "type")
        self.assertEqual(by_name["claimTask"]["kind"], "function")
        self.assertEqual(by_name["claimTask"]["language"], "typescript")

    def test_ignores_context_and_removed_lines(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1,4 +1,4 @@\n"
            " def context_only(x):\n"
            "-def removed_helper(x):\n"
            "+def added_helper(x):\n"
            "+    return x\n"
        )
        names = [s["name"] for s in pa.reusable_snippets(diff)]
        self.assertEqual(names, ["added_helper"])

    def test_context_line_terminates_the_collected_body(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@\n"
            "+def added(x):\n"
            "+    kept = 1\n"
            " untouched_context = 2\n"
            "+    not_part_of_body = 3\n"
        )
        body = pa.reusable_snippets(diff)[0]["body"]
        self.assertIn("kept = 1", body)
        self.assertNotIn("untouched_context", body)
        self.assertNotIn("not_part_of_body", body)

    def test_hunk_header_terminates_the_collected_body(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            "@@ -1 +1 @@\n"
            "+def added(x):\n"
            "+    kept = 1\n"
            "@@ -40 +40 @@\n"
            "+    other_hunk = 2\n"
        )
        body = pa.reusable_snippets(diff)[0]["body"]
        self.assertIn("kept = 1", body)
        self.assertNotIn("other_hunk", body)

    def test_snippet_count_is_bounded(self):
        diff = "diff --git a/a.py b/a.py\n@@\n" + "".join(
            f"+def fn_{i}(x):\n+    return {i}\n" for i in range(pa.MAX_SNIPPETS + 6)
        )
        self.assertEqual(len(pa.reusable_snippets(diff)), pa.MAX_SNIPPETS)

    def test_explicit_limit_is_respected(self):
        diff = "diff --git a/a.py b/a.py\n@@\n" + "".join(
            f"+def fn_{i}(x):\n+    return {i}\n" for i in range(5)
        )
        self.assertEqual(len(pa.reusable_snippets(diff, limit=2)), 2)

    def test_fail_soft_on_empty_and_garbage_input(self):
        for value in ("", None, 12345, "not a diff at all", {"a": 1}):
            self.assertEqual(pa.reusable_snippets(value), [])


class ProfileIntegrationTests(unittest.TestCase):
    def test_extract_patterns_exposes_snippets(self):
        profile = pa.extract_patterns(PY_DIFF)
        self.assertEqual([s["name"] for s in profile["snippets"]], ["normalize_slug"])
        # Existing keys must keep working — this is an additive abstraction.
        self.assertIn("normalize_slug", profile["defines"])
        self.assertEqual(profile["language"], "python")

    def test_empty_profile_still_has_snippets_key(self):
        self.assertEqual(pa.extract_patterns("")["snippets"], [])
        self.assertEqual(pa.merge_patterns([])["snippets"], [])

    def test_merge_patterns_dedupes_snippets_by_name_and_kind(self):
        a = pa.extract_patterns(PY_DIFF)
        b = pa.extract_patterns(PY_DIFF)
        merged = pa.merge_patterns([a, b])
        self.assertEqual(len(merged["snippets"]), 1)

    def test_merge_patterns_unions_across_languages(self):
        merged = pa.merge_patterns([pa.extract_patterns(PY_DIFF),
                                    pa.extract_patterns(TS_DIFF)])
        names = {s["name"] for s in merged["snippets"]}
        self.assertEqual(names, {"normalize_slug", "ClaimResult", "claimTask"})

    def test_merge_patterns_bounds_total_snippets(self):
        many = [pa.extract_patterns(
            f"diff --git a/a{i}.py b/a{i}.py\n@@\n+def fn_{i}(x):\n+    return {i}\n"
        ) for i in range(pa.MAX_SNIPPETS + 5)]
        self.assertEqual(len(pa.merge_patterns(many)["snippets"]), pa.MAX_SNIPPETS)

    def test_merge_patterns_skips_non_dict_snippets(self):
        merged = pa.merge_patterns([{"snippets": ["not-a-dict", None, 7]}])
        self.assertEqual(merged["snippets"], [])


class RenderingTests(unittest.TestCase):
    def test_preliminary_diff_includes_lifted_abstractions(self):
        profile = pa.extract_patterns(PY_DIFF)
        rendered = pa.preliminary_diff(profile, target_hint="my-task")
        self.assertIn("reusable abstractions lifted from prior merged diffs", rendered)
        self.assertIn("normalize_slug", rendered)

    def test_every_rendered_line_stays_diff_shaped(self):
        rendered = pa.preliminary_diff(pa.extract_patterns(PY_DIFF), "t")
        for line in rendered.splitlines():
            self.assertTrue(
                line.startswith(("+", "-", "diff --git", "@@")),
                f"non-diff-shaped line leaked into scaffold: {line!r}",
            )

    def test_snippet_body_is_truncated(self):
        long_body = "".join(f"+    step_{i} = {i}\n" for i in range(40))
        diff = "diff --git a/a.py b/a.py\n@@\n+def big(x):\n" + long_body
        rendered = pa.preliminary_diff(pa.extract_patterns(diff), "t")
        self.assertIn("step_0", rendered)
        self.assertNotIn("step_39", rendered)

    def test_render_snippets_skips_malformed_entries(self):
        self.assertEqual(pa._render_snippets([{"kind": "function"}, None, "x"]), [])
        self.assertEqual(pa._render_snippets(None), [])

    def test_directive_lists_available_abstractions(self):
        directive = pa.directive({"slug": "task"},
                                 [{"project": "p", "slug": "s", "diff": PY_DIFF}])
        self.assertIn("reusable abstractions available below", directive)
        self.assertIn("normalize_slug (function)", directive)

    def test_directive_still_empty_when_nothing_was_learned(self):
        self.assertEqual(pa.directive({"slug": "task"}, []), "")


if __name__ == "__main__":
    unittest.main()
