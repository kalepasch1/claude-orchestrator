import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skip_visibility as sv


class ClassifyTest(unittest.TestCase):
    def test_drain_reason_from_drain_policy(self):
        self.assertEqual(sv.classify("drain_mode=auto queue>=800"), sv.CATEGORY_DRAIN)

    def test_lean_mode_reason(self):
        self.assertEqual(sv.classify("ORCH_LEAN_MODE=true"), sv.CATEGORY_LEAN)

    def test_velocity_beats_paused(self):
        # "paused by queue-velocity PID controller" mentions both; velocity is
        # the specific, actionable one.
        reason = "paused by queue-velocity PID controller"
        self.assertEqual(sv.classify(reason), sv.CATEGORY_VELOCITY)

    def test_kill_switch_reason(self):
        self.assertEqual(sv.classify("kill-switch engaged"), sv.CATEGORY_PAUSED)

    def test_throttle_reason(self):
        self.assertEqual(
            sv.classify("throttled - queue depth > 400"), sv.CATEGORY_THROTTLE
        )

    def test_disabled_flag_reason(self):
        self.assertEqual(sv.classify("disabled"), sv.CATEGORY_DISABLED)

    def test_dependency_reason(self):
        self.assertEqual(sv.classify("no project"), sv.CATEGORY_DEPENDENCY)

    def test_budget_reason(self):
        self.assertEqual(sv.classify("budget exhausted"), sv.CATEGORY_BUDGET)

    def test_empty_reason_is_unknown(self):
        self.assertEqual(sv.classify(""), sv.CATEGORY_UNKNOWN)
        self.assertEqual(sv.classify(None), sv.CATEGORY_UNKNOWN)

    def test_unrecognised_reason_is_unknown(self):
        self.assertEqual(sv.classify("the moon was in retrograde"), sv.CATEGORY_UNKNOWN)

    def test_case_insensitive(self):
        self.assertEqual(sv.classify("DRAIN_MODE=TRUE"), sv.CATEGORY_DRAIN)


class RemedyTest(unittest.TestCase):
    def test_every_category_has_an_actionable_remedy(self):
        categories = [
            sv.CATEGORY_DRAIN, sv.CATEGORY_LEAN, sv.CATEGORY_PAUSED,
            sv.CATEGORY_THROTTLE, sv.CATEGORY_DISABLED, sv.CATEGORY_VELOCITY,
            sv.CATEGORY_BUDGET, sv.CATEGORY_DEPENDENCY, sv.CATEGORY_UNKNOWN,
        ]
        for category in categories:
            remedy = sv.remedy_for(category)
            self.assertTrue(remedy.strip(), "no remedy for %s" % category)

    def test_unknown_category_falls_back(self):
        self.assertEqual(sv.remedy_for("not-a-category"), sv.remedy_for(sv.CATEGORY_UNKNOWN))
        self.assertEqual(sv.remedy_for(None), sv.remedy_for(sv.CATEGORY_UNKNOWN))


class BuildRecordTest(unittest.TestCase):
    def test_record_carries_category_and_remedy(self):
        rec = sv.build_record("scout", "drain_mode=auto queue>=800")
        self.assertEqual(rec.job, "scout")
        self.assertEqual(rec.category, sv.CATEGORY_DRAIN)
        self.assertIn("ORCH_DRAIN", rec.remedy)
        self.assertTrue(rec.at)

    def test_drain_detail_extracts_queue_floor(self):
        rec = sv.build_record("scout", "drain_mode=auto queue>=800")
        self.assertIn("800", rec.detail)

    def test_missing_reason_still_produces_a_usable_record(self):
        rec = sv.build_record("scout", None)
        self.assertEqual(rec.category, sv.CATEGORY_UNKNOWN)
        self.assertIn("no reason", rec.detail)

    def test_missing_job_is_defaulted_not_raised(self):
        rec = sv.build_record("", "disabled")
        self.assertEqual(rec.job, "unknown-job")

    def test_context_is_stringified(self):
        rec = sv.build_record("scout", "disabled", context={"queue_depth": 812})
        self.assertEqual(rec.context["queue_depth"], "812")

    def test_as_dict_is_json_safe(self):
        import json
        rec = sv.build_record("scout", "disabled", context={"a": 1})
        json.dumps(rec.as_dict())  # must not raise


class LedgerTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_record_then_recent(self):
        sv.record("scout", "drain_mode=auto queue>=800")
        items = sv.recent()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].job, "scout")

    def test_filter_by_job(self):
        sv.record("scout", "disabled")
        sv.record("spec", "disabled")
        self.assertEqual(len(sv.recent(job="scout")), 1)

    def test_filter_by_category(self):
        sv.record("scout", "drain_mode=true")
        sv.record("spec", "disabled")
        self.assertEqual(len(sv.recent(category=sv.CATEGORY_DRAIN)), 1)

    def test_limit_returns_most_recent(self):
        for i in range(5):
            sv.record("job%d" % i, "disabled")
        items = sv.recent(2)
        self.assertEqual([r.job for r in items], ["job3", "job4"])

    def test_ring_buffer_bounds_memory(self):
        ledger = sv.SkipLedger(max_records=3)
        for i in range(10):
            ledger.record("job%d" % i, "disabled")
        self.assertEqual(len(ledger), 3)
        self.assertEqual(ledger.recent()[0].job, "job7")

    def test_max_records_from_env(self):
        with patch.dict(os.environ, {"ORCH_SKIP_LEDGER_MAX": "2"}, clear=False):
            ledger = sv.SkipLedger()
        for i in range(5):
            ledger.record("job%d" % i, "disabled")
        self.assertEqual(len(ledger), 2)

    def test_garbage_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"ORCH_SKIP_LEDGER_MAX": "banana"}, clear=False):
            ledger = sv.SkipLedger()
        self.assertEqual(ledger._max, 200)

    def test_record_is_fail_soft(self):
        with patch.object(sv, "_ledger") as bad:
            bad.record.side_effect = RuntimeError("boom")
            self.assertIsNone(sv.record("scout", "disabled"))

    def test_recent_is_fail_soft(self):
        with patch.object(sv, "_ledger") as bad:
            bad.recent.side_effect = RuntimeError("boom")
            self.assertEqual(sv.recent(), [])


class SummarizeTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_empty_summary(self):
        summary = sv.summarize([])
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["by_category"], {})
        self.assertEqual(summary["dominant_category"], "")

    def test_counts_by_category_and_job(self):
        sv.record("scout", "drain_mode=true")
        sv.record("scout", "drain_mode=true")
        sv.record("spec", "disabled")
        summary = sv.summarize()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["by_category"][sv.CATEGORY_DRAIN], 2)
        self.assertEqual(summary["by_job"]["scout"], 2)
        self.assertEqual(summary["dominant_category"], sv.CATEGORY_DRAIN)
        self.assertIn("ORCH_DRAIN", summary["dominant_remedy"])


class RenderBuildSummaryTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_no_skips_states_so_explicitly(self):
        text = sv.render_build_summary([])
        self.assertIn("none", text)
        self.assertTrue(text.strip())

    def test_reason_is_prominent_and_actionable(self):
        sv.record("scout", "drain_mode=auto queue>=800")
        text = sv.render_build_summary()
        self.assertIn("SKIPPED STEPS", text)
        self.assertIn("scout", text)
        self.assertIn("drain_mode=auto queue>=800", text)
        self.assertIn("fix:", text)

    def test_breakdown_line_lists_categories(self):
        sv.record("scout", "drain_mode=true")
        sv.record("spec", "disabled")
        text = sv.render_build_summary()
        self.assertIn("by reason:", text)
        self.assertIn(sv.CATEGORY_DRAIN, text)
        self.assertIn(sv.CATEGORY_DISABLED, text)

    def test_limit_truncates_and_says_so(self):
        for i in range(5):
            sv.record("job%d" % i, "disabled")
        text = sv.render_build_summary(limit=2)
        self.assertIn("and 3 earlier skip(s)", text)


class ApiPayloadTest(unittest.TestCase):
    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_payload_is_json_serialisable(self):
        import json
        sv.record("scout", "drain_mode=auto queue>=800")
        payload = sv.api_payload()
        json.dumps(payload)  # must not raise
        self.assertEqual(len(payload["skipped"]), 1)
        self.assertEqual(payload["skipped"][0]["category"], sv.CATEGORY_DRAIN)

    def test_payload_carries_summary_and_rendered_text(self):
        sv.record("scout", "disabled")
        payload = sv.api_payload()
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertIn("SKIPPED STEPS", payload["rendered"])

    def test_empty_payload_is_still_well_formed(self):
        payload = sv.api_payload()
        self.assertEqual(payload["skipped"], [])
        self.assertEqual(payload["summary"]["total"], 0)
        self.assertIn("none", payload["rendered"])


class DrainPolicyIntegrationTest(unittest.TestCase):
    """The real reason strings drain_policy emits must classify correctly."""

    def setUp(self):
        sv.clear()

    def tearDown(self):
        sv.clear()

    def test_real_drain_policy_reason_is_classified(self):
        import drain_policy
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            reason = drain_policy.skip_reason("scout")
        self.assertTrue(reason)
        rec = sv.build_record("scout", reason)
        self.assertEqual(rec.category, sv.CATEGORY_DRAIN)
        self.assertIn("ORCH_DRAIN", rec.remedy)

    def test_allowed_job_produces_no_reason_and_nothing_to_show(self):
        import drain_policy
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertEqual(drain_policy.skip_reason("prewarm"), "")
        self.assertIn("none", sv.render_build_summary())


if __name__ == "__main__":
    unittest.main()
