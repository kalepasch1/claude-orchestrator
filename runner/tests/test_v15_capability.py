import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import v15_capability as cap


class EnvFlag:
    """Set ORCH_ flags the way load_config would have, and always clean up."""

    def __init__(self, **flags):
        self.flags = flags
        self.saved = {}

    def __enter__(self):
        for k, v in self.flags.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


class TestNoSecondSystem(unittest.TestCase):
    """The binding constraint: reuse fleet-control, do not replace it."""

    def test_flags_are_read_through_the_existing_fleet_control_accessor(self):
        m = cap.default_manifest()
        with EnvFlag(ORCH_V15_SPECULATIVE_CHAINS="general"):
            self.assertEqual(m.stage("speculative_chains"), cap.Stage.GENERAL)

    def test_module_owns_no_scheduler_or_deploy_entry_point(self):
        for forbidden in ("tick", "run_forever", "deploy", "main", "schedule"):
            self.assertFalse(hasattr(cap, forbidden),
                             f"v15_capability must not expose {forbidden}()")

    def test_rollback_returns_a_config_write_rather_than_performing_one(self):
        m = cap.default_manifest()
        plan = m.rollback_plan("speculative_chains")
        self.assertEqual(list(plan["set"].values()), [cap.Stage.OFF])
        self.assertIn("no separate deploy path", plan["note"])

    def test_rollback_of_an_unknown_capability_raises(self):
        with self.assertRaises(KeyError):
            cap.default_manifest().rollback_plan("nope")


class TestConfigKeySafety(unittest.TestCase):
    def test_keys_are_orch_prefixed(self):
        self.assertTrue(cap.capability_flag_key("speculative_chains").startswith("ORCH_V15_"))

    def test_per_project_keys_are_distinct(self):
        self.assertNotEqual(cap.capability_flag_key("x"), cap.capability_flag_key("x", "tomorrow"))

    def test_a_credential_shaped_name_is_refused(self):
        for bad in ("github_pat", "vercel_token", "api_secret", "db_password"):
            with self.assertRaises(cap.UnsafeConfigKey):
                cap.capability_flag_key(bad)

    def test_registration_validates_the_key_up_front(self):
        m = cap.Manifest()
        with self.assertRaises(cap.UnsafeConfigKey):
            m.register(cap.Capability("service_token", "1.0.0"))


class TestCompatibilityNegotiation(unittest.TestCase):
    def test_incompatible_capability_is_refused(self):
        m = cap.Manifest(runner_schema=1)
        with self.assertRaises(cap.IncompatibleCapability):
            m.register(cap.Capability("future", "2.0.0", min_schema=5, max_schema=9))

    def test_negotiate_reports_without_raising(self):
        m = cap.Manifest(runner_schema=1)
        report = m.negotiate(cap.Capability("future", "2.0.0", min_schema=5, max_schema=9))
        self.assertFalse(report["compatible"])
        self.assertEqual(report["runner_schema"], 1)

    def test_migrations_are_listed_only_where_genuinely_required(self):
        m = cap.Manifest()
        m.register(cap.Capability("needs_table", "1.0.0", requires_migration=True))
        m.register(cap.Capability("pure_logic", "1.0.0"))
        self.assertEqual(m.pending_migrations(), ["needs_table"])


class TestCohorts(unittest.TestCase):
    def test_cohort_assignment_is_deterministic(self):
        a = cap.Manifest.cohort_position("speculative_chains", "tomorrow")
        b = cap.Manifest.cohort_position("speculative_chains", "tomorrow")
        self.assertEqual(a, b)
        self.assertTrue(0.0 <= a < 1.0)

    def test_cohort_is_salted_per_capability(self):
        self.assertNotEqual(cap.Manifest.cohort_position("a", "tomorrow"),
                            cap.Manifest.cohort_position("b", "tomorrow"))

    def test_zero_percent_canary_includes_nobody(self):
        m = cap.default_manifest()
        for project in ("tomorrow", "galop", "smarter", "vigil"):
            self.assertFalse(m.in_canary("speculative_chains", project, percent=0))

    def test_hundred_percent_canary_includes_everybody(self):
        m = cap.default_manifest()
        for project in ("tomorrow", "galop", "smarter", "vigil"):
            self.assertTrue(m.in_canary("speculative_chains", project, percent=100))

    def test_canary_share_is_roughly_the_requested_percentage(self):
        m = cap.default_manifest()
        projects = [f"project-{i}" for i in range(1000)]
        share = sum(m.in_canary("speculative_chains", p, percent=10) for p in projects) / 1000
        self.assertGreater(share, .05)
        self.assertLess(share, .16)

    def test_out_of_range_percentages_are_clamped(self):
        m = cap.default_manifest()
        self.assertTrue(m.in_canary("speculative_chains", "tomorrow", percent=999))
        self.assertFalse(m.in_canary("speculative_chains", "tomorrow", percent=-5))


class TestFlagResolution(unittest.TestCase):
    def test_unknown_capability_is_off(self):
        self.assertEqual(cap.default_manifest().stage("not_registered"), cap.Stage.OFF)

    def test_unset_flag_defaults_to_off(self):
        m = cap.default_manifest()
        self.assertEqual(m.stage("holographic_memory"), cap.Stage.OFF)
        self.assertFalse(m.enabled_for("holographic_memory", "tomorrow"))

    def test_project_flag_overrides_the_global_one(self):
        m = cap.default_manifest()
        with EnvFlag(ORCH_V15_CHANNEL_ECC="off",
                     ORCH_V15_CHANNEL_ECC_TOMORROW="general"):
            self.assertEqual(m.stage("channel_ecc", "tomorrow"), cap.Stage.GENERAL)
            self.assertEqual(m.stage("channel_ecc", "galop"), cap.Stage.OFF)

    def test_garbage_flag_value_is_treated_as_off(self):
        m = cap.default_manifest()
        with EnvFlag(ORCH_V15_CHANNEL_ECC="yes-please"):
            self.assertEqual(m.stage("channel_ecc"), cap.Stage.OFF)

    def test_general_stage_enables_every_project(self):
        m = cap.default_manifest()
        with EnvFlag(ORCH_V15_QUERY_TOPOLOGIES="general"):
            self.assertTrue(m.enabled_for("query_topologies", "anything"))


class TestGuardedExecution(unittest.TestCase):
    def test_disabled_capability_runs_the_fallback_not_the_capability(self):
        m = cap.default_manifest()
        ran = []
        result = m.run("speculative_chains", "tomorrow",
                       fn=lambda: ran.append("capability"),
                       fallback=lambda: "fallback")
        self.assertEqual(result, "fallback")
        self.assertEqual(ran, [])

    def test_enabled_capability_runs(self):
        m = cap.default_manifest()
        with EnvFlag(ORCH_V15_METABOLIC_BUDGET="general"):
            self.assertEqual(m.run("metabolic_budget", "tomorrow", fn=lambda: "ran"), "ran")


class TestTelemetryAndPromotion(unittest.TestCase):
    def _load(self, m, name, n=60, ok=True, latency=.1):
        for i in range(n):
            m.record(name, f"project-{i % 4}", ok, latency)

    def test_slo_summarises_recorded_runs(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc")
        stats = m.slo("channel_ecc")
        self.assertEqual(stats["samples"], 60)
        self.assertEqual(stats["error_rate"], 0.0)
        self.assertEqual(stats["projects"], 4)

    def test_no_telemetry_reports_none_rather_than_a_flattering_zero(self):
        stats = cap.default_manifest().slo("channel_ecc")
        self.assertEqual(stats["samples"], 0)
        self.assertIsNone(stats["error_rate"])

    def test_insufficient_samples_blocks_promotion(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=5)
        decision = m.promotion_decision("channel_ecc", min_samples=50)
        self.assertFalse(decision["promote"])
        self.assertTrue(any(b.startswith("insufficient_samples") for b in decision["blockers"]))

    def test_error_rate_blocks_promotion(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=100, ok=False)
        decision = m.promotion_decision("channel_ecc")
        self.assertFalse(decision["promote"])
        self.assertTrue(any(b.startswith("error_rate") for b in decision["blockers"]))

    def test_latency_blocks_promotion(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=100, latency=5.0)
        decision = m.promotion_decision("channel_ecc", max_p95_s=1.0)
        self.assertFalse(decision["promote"])
        self.assertTrue(any(b.startswith("p95_latency") for b in decision["blockers"]))

    def test_clean_slos_promote_exactly_one_stage(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=100)
        with EnvFlag(ORCH_V15_CHANNEL_ECC="canary"):
            decision = m.promotion_decision("channel_ecc")
        self.assertTrue(decision["promote"])
        self.assertEqual(decision["current_stage"], cap.Stage.CANARY)
        self.assertEqual(decision["next_stage"], cap.Stage.ROLLOUT)

    def test_promotion_never_considers_a_speed_multiplier(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=100)
        decision = m.promotion_decision("channel_ecc")
        # Inspect the DATA, not the prose -- the note deliberately says the word.
        self.assertNotIn("speedup", decision)
        self.assertNotIn("multiplier", json_dump({k: v for k, v in decision.items()
                                                  if k != "note"}))
        self.assertEqual(set(decision["slo"]) & {"speedup", "multiplier", "throughput"}, set())
        self.assertIn("never on a speed multiplier", decision["note"])

    def test_general_stage_cannot_promote_further(self):
        m = cap.default_manifest()
        self._load(m, "channel_ecc", n=100)
        with EnvFlag(ORCH_V15_CHANNEL_ECC="general"):
            decision = m.promotion_decision("channel_ecc")
        self.assertFalse(decision["promote"])
        self.assertEqual(decision["next_stage"], cap.Stage.GENERAL)


class TestQueueDedupe(unittest.TestCase):
    def test_duplicate_job_inside_the_window_is_refused(self):
        m = cap.default_manifest()
        payload = {"task": "recompute", "n": 1}
        self.assertTrue(m.claim_job("channel_ecc", "tomorrow", payload, now=1000))
        self.assertFalse(m.claim_job("channel_ecc", "tomorrow", payload, now=1001))
        self.assertEqual(m.metrics["deduped"], 1)

    def test_the_same_job_is_claimable_again_after_the_window(self):
        m = cap.default_manifest()
        payload = {"task": "recompute"}
        m.claim_job("channel_ecc", "tomorrow", payload, window_s=300, now=1000)
        self.assertTrue(m.claim_job("channel_ecc", "tomorrow", payload, window_s=300, now=1400))

    def test_job_key_is_payload_order_independent(self):
        a = cap.Manifest.job_key("c", "p", {"a": 1, "b": 2})
        b = cap.Manifest.job_key("c", "p", {"b": 2, "a": 1})
        self.assertEqual(a, b)

    def test_different_projects_are_different_jobs(self):
        m = cap.default_manifest()
        payload = {"task": "recompute"}
        self.assertTrue(m.claim_job("channel_ecc", "tomorrow", payload, now=1000))
        self.assertTrue(m.claim_job("channel_ecc", "galop", payload, now=1000))


def json_dump(obj):
    import json
    return json.dumps(obj, default=str)


if __name__ == "__main__":
    unittest.main()
