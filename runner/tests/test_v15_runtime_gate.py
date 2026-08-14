import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import v15_runtime_gate as gate


class FlagEnv:
    """Set ORCH_ flags and always restore them, even if an assertion throws."""

    def __init__(self, **flags):
        self.flags = flags
        self.saved = {}

    def __enter__(self):
        for k, v in self.flags.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
        return False


class TestCapabilityCoverage(unittest.TestCase):
    def test_all_ten_capabilities_are_declared(self):
        self.assertEqual(len(gate.CAPABILITIES), 10)
        self.assertEqual(len(set(gate.CAPABILITIES)), 10)

    def test_status_covers_every_capability(self):
        self.assertEqual(sorted(gate.status("orchestrator")), sorted(gate.CAPABILITIES))


class TestLegacyBehaviourWhenDisabled(unittest.TestCase):
    """The property the rollout is judged on."""

    def test_every_capability_is_off_by_default(self):
        for capability in gate.CAPABILITIES:
            self.assertFalse(gate.is_enabled(capability, "orchestrator"), capability)
        self.assertFalse(gate.any_enabled("orchestrator"))

    def test_disabled_returns_the_legacy_value_by_identity(self):
        for capability in gate.CAPABILITIES:
            legacy_value = {"capability": capability, "marker": "legacy"}
            result = gate.gated(capability, "orchestrator",
                                legacy=lambda v=legacy_value: v,
                                v15=lambda: {"marker": "v15"})
            self.assertIs(result, legacy_value, capability)

    def test_disabled_calls_legacy_once_and_v15_never(self):
        calls = {"legacy": 0, "v15": 0}

        def legacy():
            calls["legacy"] += 1
            return "legacy"

        def v15():
            calls["v15"] += 1
            return "v15"

        gate.gated("speculative_chains", "orchestrator", legacy, v15)
        self.assertEqual(calls, {"legacy": 1, "v15": 0})

    def test_disabled_propagates_a_legacy_error_unchanged(self):
        def legacy():
            raise RuntimeError("legacy failure")

        with self.assertRaises(RuntimeError):
            gate.gated("causal_attention", "orchestrator", legacy)

    def test_an_unrecognised_flag_value_is_off(self):
        with FlagEnv(**{gate.flag_key("metabolic_budget"): "maybe"}):
            self.assertFalse(gate.is_enabled("metabolic_budget", "orchestrator"))

    def test_an_unknown_capability_is_off(self):
        self.assertFalse(gate.is_enabled("not_a_capability", "orchestrator"))


class TestCanaryMode(unittest.TestCase):
    def test_canary_flag_enables_the_v15_path(self):
        with FlagEnv(**{gate.flag_key("holographic_retrieval"): "canary"}):
            result = gate.gated("holographic_retrieval", "orchestrator",
                                legacy=lambda: "legacy", v15=lambda: "v15")
            self.assertEqual(result, "v15")

    def test_a_missing_v15_path_still_runs_legacy(self):
        with FlagEnv(**{gate.flag_key("query_topologies"): "on"}):
            self.assertEqual(
                gate.gated("query_topologies", "orchestrator", legacy=lambda: "legacy"),
                "legacy")

    def test_a_throwing_v15_path_falls_back_to_legacy(self):
        gate.reset_metrics()

        def boom():
            raise ValueError("v15 exploded")

        with FlagEnv(**{gate.flag_key("anomaly_curriculum"): "on"}):
            result = gate.gated("anomaly_curriculum", "orchestrator",
                                legacy=lambda: "legacy", v15=boom)
        self.assertEqual(result, "legacy")

    def test_project_scoped_flag_does_not_leak_to_other_projects(self):
        with FlagEnv(**{gate.flag_key("zero_copy_federation", "tomorrow"): "on"}):
            self.assertTrue(gate.is_enabled("zero_copy_federation", "tomorrow"))
            self.assertFalse(gate.is_enabled("zero_copy_federation", "galop"))

    def test_project_off_overrides_a_global_on(self):
        with FlagEnv(**{gate.flag_key("topology_distillation"): "on",
                        gate.flag_key("topology_distillation", "galop"): "off"}):
            self.assertTrue(gate.is_enabled("topology_distillation", "tomorrow"))
            self.assertFalse(gate.is_enabled("topology_distillation", "galop"))


class TestQueueInvariants(unittest.TestCase):
    def test_observe_is_a_noop_when_disabled(self):
        gate.reset_metrics()
        self.assertIsNone(gate.observe_task_gated({"project": "orchestrator", "kind": "x"}))
        self.assertEqual(gate.metrics["observe:skipped"], 1)

    def test_observe_never_mutates_the_task_row(self):
        row = {"project": "orchestrator", "kind": "build", "prompt": "p", "id": "t1"}
        snapshot = dict(row)
        with FlagEnv(**{gate.flag_key("query_topologies"): "on"}):
            gate.observe_task_gated(row)
        self.assertEqual(row, snapshot)

    def test_observe_returns_none_rather_than_raising_on_failure(self):
        gate.reset_metrics()

        class Boom:
            @staticmethod
            def observe_task(_):
                raise RuntimeError("learning hook broke")

        original = gate.hivemind_v15
        gate.hivemind_v15 = Boom
        try:
            with FlagEnv(**{gate.flag_key("query_topologies"): "on"}):
                self.assertIsNone(gate.observe_task_gated({"project": "orchestrator"}))
        finally:
            gate.hivemind_v15 = original
        # Fail-soft, but the breakage is COUNTED rather than silently swallowed.
        self.assertEqual(gate.metrics["observe:error"], 1)

    def test_observe_handles_a_row_with_no_project(self):
        self.assertIsNone(gate.observe_task_gated({"kind": "x"}))


class TestSingleInstance(unittest.TestCase):
    def test_runtime_resolves_to_one_instance(self):
        if gate.hivemind_v15 is None:
            self.skipTest("hivemind_v15 unavailable")
        self.assertTrue(gate.assert_single_instance())

    def test_fingerprint_is_stable_across_calls(self):
        if gate.hivemind_v15 is None:
            self.skipTest("hivemind_v15 unavailable")
        self.assertEqual(gate.runtime_fingerprint(), gate.runtime_fingerprint())

    def test_absent_runtime_reports_false_rather_than_raising(self):
        original = gate.hivemind_v15
        gate.hivemind_v15 = None
        try:
            self.assertIsNone(gate.runtime_fingerprint())
            self.assertFalse(gate.assert_single_instance())
        finally:
            gate.hivemind_v15 = original


class TestRollbackAndReporting(unittest.TestCase):
    def test_rollback_returns_a_config_write_rather_than_applying_one(self):
        plan = gate.rollback_plan("speculative_chains", "tomorrow")
        self.assertEqual(list(plan["set"].values()), ["off"])
        self.assertIn("owns no deploy path", plan["note"])

    def test_rollback_of_an_unknown_capability_raises(self):
        with self.assertRaises(KeyError):
            gate.rollback_plan("nope")

    def test_flag_keys_are_orch_prefixed_and_project_scoped(self):
        self.assertTrue(gate.flag_key("causal_attention").startswith("ORCH_V15_"))
        self.assertNotEqual(gate.flag_key("causal_attention"),
                            gate.flag_key("causal_attention", "tomorrow"))

    def test_report_lists_enabled_and_disabled_capabilities(self):
        with FlagEnv(**{gate.flag_key("metabolic_budget"): "on"}):
            report = gate.report("orchestrator")
        self.assertIn("metabolic_budget", report["enabled"])
        self.assertEqual(len(report["enabled"]) + len(report["disabled"]), 10)


if __name__ == "__main__":
    unittest.main()
