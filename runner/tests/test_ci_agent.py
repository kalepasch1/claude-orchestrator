"""Tests for CI agent dispatch — payload build, sensitivity exclusion, status polling."""
import os
import sys
import types
import unittest
import unittest.mock

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
        # `db` here is the REAL client whenever anything imported it before this
        # file (the module-scope stub loop only fills names that are absent), so
        # this call used to reach the control plane for real.
        with unittest.mock.patch.object(ci_dispatch.db, "update") as mock_update:
            ci_dispatch.complete("t2")
            mock_update.assert_not_called()
        self.assertNotIn("t2", ci_dispatch._in_flight)

    def test_completing_a_task_with_no_id_writes_nothing(self):
        """The fixture above is the common shape, so the guard gets its own test.

        dispatch() records str(task.get("id", "")), so a task with no id is
        tracked with task_id "". complete() then issued
        PATCH /rest/v1/tasks?id=eq. with {"state": "done"} -- a live write with
        no usable filter. The slot must still be released.
        """
        ci_dispatch.dispatch({"kind": "docs", "slug": "no-id", "prompt": "p"})
        with unittest.mock.patch.object(ci_dispatch.db, "update") as mock_update:
            self.assertEqual(ci_dispatch.complete("no-id"), "done")
            mock_update.assert_not_called()
        self.assertNotIn("no-id", ci_dispatch._in_flight)

    def test_a_task_that_has_an_id_still_gets_its_state_written(self):
        """The other half: the guard must not silence a legitimate update."""
        ci_dispatch.dispatch({"kind": "docs", "slug": "with-id", "prompt": "p",
                              "id": "abc-123"})
        with unittest.mock.patch.object(ci_dispatch.db, "update") as mock_update:
            self.assertEqual(ci_dispatch.complete("with-id"), "done")
            mock_update.assert_called_once_with(
                "tasks", {"id": "abc-123"}, {"state": "done"})

    def test_max_concurrent_cap(self):
        ci_dispatch._in_flight.clear()
        for i in range(ci_dispatch.MAX_CONCURRENT):
            ci_dispatch.dispatch({"kind": "docs", "slug": f"t{i}", "prompt": "p"})
        result = ci_dispatch.dispatch({"kind": "docs", "slug": "overflow", "prompt": "p"})
        self.assertIsNone(result)
        self.assertNotIn("overflow", ci_dispatch._in_flight,
                         "a deferred dispatch must not occupy a slot")

    def test_the_cap_applies_to_every_slug_not_one(self):
        """The cap used to return None only for one hardcoded slug.

        `if len(_in_flight) >= MAX_CONCURRENT: if slug == 'canary-self-deploy-
        orchestrator-split-the-build-ta-slice-2': return None` -- so the limit
        this module advertises (ORCH_CI_MAX_CONCURRENT, default 2) stopped
        exactly one task and let every other one through. Three unrelated slugs,
        because a per-slug allowlist passes a one-slug test.
        """
        ci_dispatch._in_flight.clear()
        for i in range(ci_dispatch.MAX_CONCURRENT):
            ci_dispatch.dispatch({"kind": "docs", "slug": f"filler{i}", "prompt": "p"})
        for slug in ("alpha-task", "beta-task", "gamma-task"):
            self.assertIsNone(
                ci_dispatch.dispatch({"kind": "docs", "slug": slug, "prompt": "p"}),
                f"{slug} was dispatched past a full in-flight table")

    def test_a_slug_already_in_flight_is_not_dispatched_twice(self):
        """Re-dispatch duplicates a CI run rather than adding one, cap or no cap."""
        ci_dispatch._in_flight.clear()
        first = ci_dispatch.dispatch({"kind": "docs", "slug": "dupe", "prompt": "p"})
        self.assertIsNotNone(first)
        self.assertIsNone(ci_dispatch.dispatch({"kind": "docs", "slug": "dupe",
                                                "prompt": "p"}))
        self.assertEqual(len(ci_dispatch._in_flight), 1)


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
