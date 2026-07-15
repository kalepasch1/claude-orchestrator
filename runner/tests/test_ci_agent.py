"""Tests for CI agent dispatch — payload build, sensitivity exclusion, status polling."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub dependencies
for mod_name in ("db", "kill_switch", "subscription_guard", "privacy", "provider_terms"):
    if mod_name not in sys.modules:
        m = types.ModuleType(mod_name)
        if mod_name == "privacy":
            m.sensitivity = lambda text: "standard"
        if mod_name == "provider_terms":
            m.allowed = lambda name, sens: sens in ("standard", "public", "routine")
        sys.modules[mod_name] = m

import ci_dispatch
import ci_workflows


class TestCIDispatchEligibility(unittest.TestCase):
    def test_docs_eligible(self):
        task = {"kind": "docs", "slug": "update-readme", "prompt": "update readme"}
        self.assertTrue(ci_dispatch.is_eligible(task))

    def test_chore_eligible(self):
        task = {"kind": "chore", "slug": "cleanup-imports", "prompt": "clean"}
        self.assertTrue(ci_dispatch.is_eligible(task))

    def test_test_kind_eligible(self):
        task = {"kind": "test", "slug": "add-tests", "prompt": "add tests"}
        self.assertTrue(ci_dispatch.is_eligible(task))

    def test_mechanical_eligible(self):
        task = {"kind": "mechanical", "slug": "rename-var", "prompt": "rename"}
        self.assertTrue(ci_dispatch.is_eligible(task))

    def test_lint_eligible(self):
        task = {"kind": "lint", "slug": "lint-fix", "prompt": "fix lint"}
        self.assertTrue(ci_dispatch.is_eligible(task))

    def test_build_not_eligible(self):
        task = {"kind": "build", "slug": "new-feature", "prompt": "build feature"}
        self.assertFalse(ci_dispatch.is_eligible(task))

    def test_feature_not_eligible(self):
        task = {"kind": "feature", "slug": "big-change", "prompt": "big"}
        self.assertFalse(ci_dispatch.is_eligible(task))

    def test_sensitive_task_excluded(self):
        """Tasks with non-standard sensitivity must be rejected."""
        task = {"kind": "docs", "slug": "secret-docs", "prompt": "doc",
                "sensitivity": "crown_jewel"}
        self.assertFalse(ci_dispatch.is_eligible(task))


class TestDispatchPayload(unittest.TestCase):
    def test_payload_structure(self):
        task = {"kind": "docs", "slug": "update-readme", "prompt": "update", "id": "abc123"}
        payload = ci_dispatch.build_dispatch_payload(task)
        self.assertEqual(payload["event_type"], "orch-agent-task")
        cp = payload["client_payload"]
        self.assertEqual(cp["slug"], "update-readme")
        self.assertEqual(cp["task_id"], "abc123")

    def test_payload_no_secrets(self):
        """Payload must never contain secret-like fields."""
        task = {"kind": "docs", "slug": "t", "prompt": "p", "api_key": "SHOULD_NOT_APPEAR"}
        payload = ci_dispatch.build_dispatch_payload(task)
        payload_str = str(payload)
        self.assertNotIn("SHOULD_NOT_APPEAR", payload_str)

    def test_prompt_truncated(self):
        task = {"kind": "docs", "slug": "t", "prompt": "x" * 5000}
        payload = ci_dispatch.build_dispatch_payload(task)
        self.assertLessEqual(len(payload["client_payload"]["prompt"]), 2000)


class TestDispatchAndPoll(unittest.TestCase):
    def setUp(self):
        ci_dispatch._in_flight.clear()

    def test_dispatch_eligible_task(self):
        task = {"kind": "docs", "slug": "readme", "prompt": "update"}
        result = ci_dispatch.dispatch(task)
        self.assertIsNotNone(result)
        self.assertIn("readme", ci_dispatch._in_flight)

    def test_dispatch_ineligible_returns_none(self):
        task = {"kind": "build", "slug": "big", "prompt": "build"}
        result = ci_dispatch.dispatch(task)
        self.assertIsNone(result)

    def test_poll_in_progress(self):
        task = {"kind": "docs", "slug": "t1", "prompt": "p"}
        ci_dispatch.dispatch(task)
        self.assertEqual(ci_dispatch.poll_status("t1"), "in_progress")

    def test_poll_unknown(self):
        self.assertEqual(ci_dispatch.poll_status("nonexistent"), "unknown")

    def test_complete_removes_from_inflight(self):
        task = {"kind": "docs", "slug": "t2", "prompt": "p"}
        ci_dispatch.dispatch(task)
        ci_dispatch.complete("t2")
        self.assertNotIn("t2", ci_dispatch._in_flight)

    def test_max_concurrent_cap(self):
        ci_dispatch._in_flight.clear()
        for i in range(ci_dispatch.MAX_CONCURRENT):
            ci_dispatch.dispatch({"kind": "docs", "slug": f"t{i}", "prompt": "p"})
        result = ci_dispatch.dispatch({"kind": "docs", "slug": "overflow", "prompt": "p"})
        self.assertIsNone(result)


class TestCIWorkflowGeneration(unittest.TestCase):
    def test_generate_contains_dispatch(self):
        yml = ci_workflows.generate()
        self.assertIn("repository_dispatch", yml)
        self.assertIn("orch-agent-task", yml)

    def test_generate_uses_secrets(self):
        yml = ci_workflows.generate()
        self.assertIn("secrets.ANTHROPIC_API_KEY", yml)

    def test_generate_valid_yaml(self):
        import json
        parsed = json.loads(ci_workflows.generate())
        self.assertIn("jobs", parsed)
        self.assertIn("agent", parsed["jobs"])


if __name__ == "__main__":
    unittest.main()
