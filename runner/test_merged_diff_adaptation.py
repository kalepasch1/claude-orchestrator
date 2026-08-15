#!/usr/bin/env python3
"""Tests for the merged-diff adaptation stage (canary-xai-6-adapt-proven-diffs).

Acceptance: a proven prior diff is adapted onto the current task's paths before
any net-new code is drafted, and the adapted code is verified against the
current task's acceptance criteria. Security class: the adaptation must never
transplant a credential across the reuse boundary (fails CLOSED).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import merged_diff_library as mdl  # noqa: E402

PROVEN_DIFF = """diff --git a/src/legacy/handler.py b/src/legacy/handler.py
index 1111111..2222222 100644
--- a/src/legacy/handler.py
+++ b/src/legacy/handler.py
@@ -1,4 +1,7 @@
 def handle(request):
-    return request
+    if request is None:
+        return {"status": 400, "error": "missing request"}
+    return {"status": 200, "body": request}
"""

SECRET_DIFF = """diff --git a/src/legacy/config.py b/src/legacy/config.py
--- a/src/legacy/config.py
+++ b/src/legacy/config.py
@@ -1 +1,2 @@
 import os
+API_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"
"""


class ContainsSecretTest(unittest.TestCase):
    def test_detects_common_credential_shapes(self):
        self.assertTrue(mdl.contains_secret('api_key = "abcdefghijkl"'))
        self.assertTrue(mdl.contains_secret("sk-abcdefghijklmnopqrstuvwxyz01"))
        self.assertTrue(mdl.contains_secret("ghp_abcdefghijklmnopqrstuvwxyz01"))
        self.assertTrue(mdl.contains_secret("-----BEGIN RSA PRIVATE KEY-----"))
        self.assertTrue(mdl.contains_secret("AKIAIOSFODNN7EXAMPLE"))

    def test_clean_code_is_not_flagged(self):
        self.assertFalse(mdl.contains_secret("def handle(request):\n    return request"))
        self.assertFalse(mdl.contains_secret("API_KEY = os.environ['API_KEY']"))

    def test_fail_soft_on_bad_input(self):
        self.assertFalse(mdl.contains_secret(None))
        self.assertFalse(mdl.contains_secret(42))
        self.assertFalse(mdl.contains_secret(""))


class AdaptDiffTest(unittest.TestCase):
    def test_retargets_paths_onto_current_task_files(self):
        result = mdl.adapt_diff(
            {"prompt": "harden the handler"}, PROVEN_DIFF, ["src/interfaces/handler.py"]
        )
        self.assertIn("diff --git a/src/interfaces/handler.py", result["patch"])
        self.assertNotIn("src/legacy/handler.py", result["patch"])
        self.assertEqual(result["adapted_files"], ["src/interfaces/handler.py"])

    def test_same_extension_fallback_when_no_basename_match(self):
        result = mdl.adapt_diff({}, PROVEN_DIFF, ["src/interfaces/controller.py"])
        self.assertIn("src/interfaces/controller.py", result["patch"])

    def test_section_without_counterpart_is_dropped_not_guessed(self):
        result = mdl.adapt_diff({}, PROVEN_DIFF, ["web/app.ts"])
        self.assertEqual(result["patch"], "")
        self.assertEqual(len(result["dropped"]), 1)
        self.assertIn("no counterpart", result["dropped"][0][1])

    def test_secret_bearing_section_is_refused_whole(self):
        combined = PROVEN_DIFF + SECRET_DIFF
        result = mdl.adapt_diff({}, combined, ["src/x/handler.py", "src/x/config.py"])
        self.assertEqual(result["secrets_blocked"], 1)
        self.assertNotIn("sk-abcdefghij", result["patch"])
        self.assertIn("handler.py", result["patch"])

    def test_stale_blob_hashes_are_stripped(self):
        result = mdl.adapt_diff({}, PROVEN_DIFF, ["src/x/handler.py"])
        self.assertNotIn("index 1111111", result["patch"])

    def test_hunk_budget_is_respected(self):
        original = mdl.ORCH_ADAPT_MAX_HUNKS
        mdl.ORCH_ADAPT_MAX_HUNKS = 0
        try:
            result = mdl.adapt_diff({}, PROVEN_DIFF, ["src/x/handler.py"])
            self.assertEqual(result["patch"], "")
        finally:
            mdl.ORCH_ADAPT_MAX_HUNKS = original

    def test_fail_soft_on_bad_input(self):
        for bad in (None, "", 42, "   "):
            result = mdl.adapt_diff({}, bad, ["a.py"])
            self.assertEqual(result["patch"], "")
        self.assertEqual(mdl.adapt_diff("not-a-dict", PROVEN_DIFF, [])["patch"], "")

    def test_target_files_read_from_task_when_not_passed(self):
        task = {"prompt": "x", "files": ["src/x/handler.py"]}
        self.assertIn("src/x/handler.py", mdl.adapt_diff(task, PROVEN_DIFF)["patch"])


class VerifyAcceptanceTest(unittest.TestCase):
    def test_empty_patch_fails(self):
        verdict = mdl.verify_acceptance({"prompt": "handle request status"}, "")
        self.assertFalse(verdict["meets_acceptance"])
        self.assertIn("empty patch", verdict["reasons"])

    def test_secret_bearing_patch_fails_closed(self):
        verdict = mdl.verify_acceptance({"prompt": "handle request"}, SECRET_DIFF)
        self.assertFalse(verdict["meets_acceptance"])
        self.assertIn("credential", verdict["reasons"][0])

    def test_aligned_patch_meets_acceptance(self):
        task = {"prompt": "return status error missing request handler"}
        patch = mdl.adapt_diff(task, PROVEN_DIFF, ["src/x/handler.py"])["patch"]
        verdict = mdl.verify_acceptance(task, patch)
        self.assertTrue(verdict["meets_acceptance"])
        self.assertGreater(verdict["coverage"], 0.0)

    def test_unrelated_patch_is_reported_below_threshold(self):
        task = {"prompt": "kubernetes autoscaling telemetry pipeline throughput"}
        patch = mdl.adapt_diff(task, PROVEN_DIFF, ["src/x/handler.py"])["patch"]
        verdict = mdl.verify_acceptance(task, patch)
        self.assertFalse(verdict["meets_acceptance"])
        self.assertIn("below threshold", verdict["reasons"][0])

    def test_no_extractable_intent_is_reported(self):
        verdict = mdl.verify_acceptance({"prompt": "a b c"}, PROVEN_DIFF)
        self.assertFalse(verdict["meets_acceptance"])
        self.assertIn("acceptance intent", verdict["reasons"][0])

    def test_fail_soft_on_bad_input(self):
        self.assertFalse(mdl.verify_acceptance(None, None)["meets_acceptance"])
        self.assertFalse(mdl.verify_acceptance("nope", 42)["meets_acceptance"])


class AdaptBestTest(unittest.TestCase):
    def setUp(self):
        self._find = mdl.find

    def tearDown(self):
        mdl.find = self._find

    def test_returns_first_adaptation_meeting_acceptance(self):
        mdl.find = lambda task, limit=3: [
            {"project": "p", "slug": "old", "similarity": 0.9, "diff": PROVEN_DIFF}
        ]
        task = {"prompt": "return status error missing request handler"}
        outcome = mdl.adapt_best(task, target_files=["src/x/handler.py"])
        self.assertTrue(outcome["adapted"])
        self.assertEqual(outcome["source"], "p/old")
        self.assertIn("src/x/handler.py", outcome["patch"])

    def test_reports_best_near_miss_when_nothing_clears(self):
        mdl.find = lambda task, limit=3: [
            {"project": "p", "slug": "old", "similarity": 0.3, "diff": PROVEN_DIFF}
        ]
        task = {"prompt": "kubernetes autoscaling telemetry pipeline throughput"}
        outcome = mdl.adapt_best(task, target_files=["src/x/handler.py"])
        self.assertFalse(outcome["adapted"])
        self.assertIsNotNone(outcome["verdict"])
        self.assertEqual(outcome["source"], "p/old")

    def test_no_hits_is_fail_soft(self):
        mdl.find = lambda task, limit=3: []
        outcome = mdl.adapt_best({"prompt": "anything"})
        self.assertFalse(outcome["adapted"])
        self.assertIn("no proven diffs", outcome["attempts"][0]["reason"])

    def test_find_raising_is_fail_soft(self):
        def boom(task, limit=3):
            raise RuntimeError("db down")

        mdl.find = boom
        self.assertFalse(mdl.adapt_best({"prompt": "anything"})["adapted"])

    def test_directive_wording_reflects_outcome(self):
        mdl.find = lambda task, limit=3: [
            {"project": "p", "slug": "old", "similarity": 0.9, "diff": PROVEN_DIFF}
        ]
        task = {"prompt": "return status error missing request handler"}
        self.assertIn(
            "ADAPTED PROVEN DIFF",
            mdl.adaptation_directive(task, target_files=["src/x/handler.py"]),
        )
        mdl.find = lambda task, limit=3: []
        self.assertIn("NO REUSABLE DIFF", mdl.adaptation_directive(task))


if __name__ == "__main__":
    unittest.main()
