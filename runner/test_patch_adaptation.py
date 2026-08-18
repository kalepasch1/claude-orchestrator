#!/usr/bin/env python3
"""Tests for runner/patch_adaptation.py — prior-diff → adaptation scaffold."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_adaptation as pa

PY_DIFF = """diff --git a/runner/lease_manager.py b/runner/lease_manager.py
--- a/runner/lease_manager.py
+++ b/runner/lease_manager.py
@@ -1,3 +1,12 @@
+import db
+from runner.telemetry import emit
+
+class LeaseManager:
+    def acquire_lease(self, slug):
+        row = db.select("leases", {"slug": slug})
+        emit("lease.acquire", slug)
+        return row
diff --git a/runner/tests/test_lease_manager.py b/runner/tests/test_lease_manager.py
--- /dev/null
+++ b/runner/tests/test_lease_manager.py
@@ -0,0 +1,4 @@
+def test_acquire():
+    assert acquire_lease("x")
"""

TS_DIFF = """diff --git a/web/server/utils/sessionStore.ts b/web/server/utils/sessionStore.ts
--- a/web/server/utils/sessionStore.ts
+++ b/web/server/utils/sessionStore.ts
@@ -0,0 +1,8 @@
+import { useTypedClient } from '~/server/utils/client'
+export interface SessionShard { id: string }
+export function readShard(id: string) {
+  return useTypedClient().from('shards')
+}
"""


class TestText(unittest.TestCase):
    def test_coerces_bytes_none_and_objects(self):
        self.assertEqual(pa._text(b"hi"), "hi")
        self.assertEqual(pa._text(None), "")
        self.assertEqual(pa._text(12), "12")


class TestChangedFiles(unittest.TestCase):
    def test_reads_diff_git_headers(self):
        self.assertEqual(
            pa.changed_files(PY_DIFF),
            ["runner/lease_manager.py", "runner/tests/test_lease_manager.py"],
        )

    def test_falls_back_to_plus_plus_plus_headers(self):
        diff = "--- a/x.py\n+++ b/pkg/x.py\n@@ -1 +1 @@\n+pass\n"
        self.assertEqual(pa.changed_files(diff), ["pkg/x.py"])

    def test_bad_input_is_empty(self):
        for bad in (None, "", 5, b""):
            self.assertEqual(pa.changed_files(bad), [])


class TestExtractPatterns(unittest.TestCase):
    def test_python_defines_and_reuses(self):
        p = pa.extract_patterns(PY_DIFF)
        self.assertIn("LeaseManager", p["defines"])
        self.assertIn("acquire_lease", p["defines"])
        # helpers called but not defined by this diff are the reusable ones
        self.assertIn("select", p["reuses"])
        self.assertIn("emit", p["reuses"])
        self.assertNotIn("acquire_lease", p["reuses"])
        self.assertEqual(p["language"], "python")
        self.assertEqual(p["naming"], "snake_case")

    def test_python_imports_and_dirs_and_tests(self):
        p = pa.extract_patterns(PY_DIFF)
        self.assertIn("db", p["imports"])
        self.assertIn("runner.telemetry", p["imports"])
        self.assertIn("runner", p["dirs"])
        self.assertEqual(p["tests"], ["runner/tests/test_lease_manager.py"])

    def test_typescript_diff(self):
        p = pa.extract_patterns(TS_DIFF)
        self.assertIn("SessionShard", p["defines"])
        self.assertIn("readShard", p["defines"])
        self.assertIn("~/server/utils/client", p["imports"])
        self.assertEqual(p["language"], "typescript")

    def test_noise_calls_are_not_reported_as_helpers(self):
        p = pa.extract_patterns("diff --git a/a.py b/a.py\n+x = sorted(list(range(3)))\n")
        for noise in ("sorted", "list", "range"):
            self.assertNotIn(noise, p["reuses"])

    def test_fail_soft_on_bad_input(self):
        for bad in (None, "", 0, b"", []):
            p = pa.extract_patterns(bad)
            self.assertEqual(p["defines"], [])
            self.assertEqual(p["naming"], "unknown")

    def test_explicit_files_override_diff_headers(self):
        p = pa.extract_patterns("+x = 1\n", files=["web/a.ts", "web/a.test.ts"])
        self.assertEqual(p["dirs"], ["web"])
        self.assertEqual(p["tests"], ["web/a.test.ts"])


class TestNaming(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(pa._naming_convention(["read_shard", "write_shard"]), "snake_case")
        self.assertEqual(pa._naming_convention(["readShard", "writeShard"]), "camelCase")
        self.assertEqual(pa._naming_convention(["ReadShard", "WriteShard"]), "PascalCase")
        self.assertEqual(pa._naming_convention([]), "unknown")


class TestMergePatterns(unittest.TestCase):
    def test_unions_without_duplicates(self):
        merged = pa.merge_patterns([
            pa.extract_patterns(PY_DIFF),
            pa.extract_patterns(PY_DIFF),
            "not-a-dict",
            None,
        ])
        self.assertEqual(merged["reuses"].count("select"), 1)
        self.assertEqual(merged["language"], "python")

    def test_empty_list_is_safe(self):
        merged = pa.merge_patterns([])
        self.assertEqual(merged["defines"], [])
        self.assertEqual(merged["naming"], "unknown")

    def test_none_is_safe(self):
        self.assertEqual(pa.merge_patterns(None)["dirs"], [])


class TestPreliminaryDiff(unittest.TestCase):
    def test_scaffold_names_dirs_and_helpers(self):
        profile = pa.extract_patterns(PY_DIFF)
        out = pa.preliminary_diff(profile, "session-recon")
        self.assertIn("diff --git a/runner/session-recon.py", out)
        self.assertIn("reuse existing helper: select(...)", out)
        self.assertIn("naming convention in this area: snake_case", out)

    def test_empty_profile_yields_nothing(self):
        self.assertEqual(pa.preliminary_diff({}, "x"), "")
        self.assertEqual(pa.preliminary_diff(None, "x"), "")

    def test_target_hint_is_sanitized(self):
        profile = pa.extract_patterns(PY_DIFF)
        out = pa.preliminary_diff(profile, "../../etc/passwd; rm -rf /")
        self.assertNotIn("..", out.split("diff --git")[1].split("\n")[0])
        self.assertNotIn(";", out)


class TestAdaptAndDirective(unittest.TestCase):
    def _hits(self):
        return [{"project": "beethoven", "slug": "relfix-07071626", "diff": PY_DIFF},
                {"project": "pareto-2080", "slug": "qafix-07062319", "diff": TS_DIFF}]

    def test_adapt_collects_sources_and_profile(self):
        r = pa.adapt({"slug": "slice-5"}, self._hits())
        self.assertIn("beethoven/relfix-07071626", r["sources"])
        self.assertIn("pareto-2080/qafix-07062319", r["sources"])
        self.assertIn("select", r["profile"]["reuses"])
        self.assertTrue(r["diff"])

    def test_adapt_is_fail_soft(self):
        for bad in (None, [], ["junk"], [None]):
            r = pa.adapt({"slug": "s"}, bad)
            self.assertIsInstance(r, dict)
            self.assertIn("profile", r)

    def test_directive_mentions_sources_and_helpers(self):
        text = pa.directive({"slug": "slice-5"}, self._hits())
        self.assertIn("Adapted prior structure", text)
        self.assertIn("beethoven/relfix-07071626", text)
        self.assertIn("project helpers to call", text)

    def test_directive_empty_when_no_hits(self):
        self.assertEqual(pa.directive({"slug": "s"}, []), "")


class TestTemplateIntegration(unittest.TestCase):
    def test_build_appends_adaptation_when_hits_exist(self):
        import patch_templates
        original = None
        try:
            import merged_diff_library
            original = merged_diff_library.find
            merged_diff_library.find = lambda task, limit=2: [
                {"project": "beethoven", "slug": "prior", "similarity": 0.5,
                 "summary": "prior work", "diff": PY_DIFF}
            ]
        except Exception:
            self.skipTest("merged_diff_library unavailable")
        try:
            _tid, body = patch_templates.build({"slug": "s", "prompt": "adapt prior patch"})
            self.assertIn("Prior merged patterns to adapt", body)
            self.assertIn("Adapted prior structure", body)
        finally:
            if original is not None:
                merged_diff_library.find = original


if __name__ == "__main__":
    unittest.main()
