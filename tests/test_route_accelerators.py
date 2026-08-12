#!/usr/bin/env python3
"""Tests for runner/route_accelerators.py + its wiring into model_policy.choose (§3)."""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import route_accelerators as ra  # noqa: E402


class WeakRouteTests(unittest.TestCase):
    def test_local_and_ollama_providers_are_weak(self):
        self.assertTrue(ra.is_weak_route("local", "llama3.2:3b"))
        self.assertTrue(ra.is_weak_route("ollama", "deepseek-coder-v2:16b"))

    def test_small_model_names_are_weak_whatever_the_provider(self):
        for model in ("claude-haiku-4-5-20251001", "gemini-4.0-flash", "gpt-4o-mini"):
            self.assertTrue(ra.is_weak_route("someprovider", model), model)

    def test_top_tier_models_are_not_weak(self):
        self.assertFalse(ra.is_weak_route("claude", "claude-opus-4-8"))
        self.assertFalse(ra.is_weak_route("claude", "claude-sonnet-4-6"))

    def test_junk_input_is_fail_soft(self):
        self.assertFalse(ra.is_weak_route(None, None))


class EnforceRouteTests(unittest.TestCase):
    def test_legal_class_never_gets_a_weak_coder(self):
        """The observed 0/12-merged shape."""
        prov, model, reason = ra.enforce_route("local", "llama3.2:3b", task_class="legal", need=9)
        self.assertEqual(prov, "claude")
        self.assertNotIn("llama", model)
        self.assertIn("0/12 merged", reason)

    def test_two_failed_attempts_force_the_strongest_route(self):
        prov, model, reason = ra.enforce_route("claude", "claude-haiku-4-5-20251001",
                                               task_class="build", need=6, attempt=2)
        self.assertEqual((prov, model), ra.STRONGEST_ROUTE)
        self.assertIn("route-escalation", reason)

    def test_escalation_ignores_the_cost_score_entirely(self):
        prov, model, _ = ra.enforce_route("local", "llama3.2:3b", task_class="build",
                                          need=3, attempt=5)
        self.assertEqual((prov, model), ra.STRONGEST_ROUTE)

    def test_first_attempt_on_cheap_work_is_left_alone(self):
        self.assertEqual(
            ra.enforce_route("local", "llama3.2:3b", task_class="build", need=4, attempt=0)[:2],
            ("local", "llama3.2:3b"))

    def test_one_failed_attempt_does_not_escalate_yet(self):
        self.assertEqual(
            ra.enforce_route("local", "llama3.2:3b", task_class="build", need=4, attempt=1)[:2],
            ("local", "llama3.2:3b"))

    def test_triage_and_qa_stages_stay_cheap(self):
        """Only the coder stage is gated — cheap triage is the point of triage."""
        for stage in ("triage", "qa"):
            self.assertEqual(
                ra.enforce_route("local", "llama3.2:3b", task_class="legal", need=9,
                                 attempt=9, stage=stage)[:2],
                ("local", "llama3.2:3b"), stage)

    def test_strong_route_on_legal_class_is_left_alone(self):
        self.assertEqual(
            ra.enforce_route("claude", "claude-opus-4-8", task_class="legal", need=9)[:2],
            ("claude", "claude-opus-4-8"))

    def test_enforcement_is_fail_soft(self):
        self.assertEqual(ra.enforce_route("p", "m", need="junk")[:2], ("p", "m"))


class RouteViolationTests(unittest.TestCase):
    def test_query_proof_flags_legal_class_runs_on_weak_routes(self):
        """§PROOFS: 'no legal-class coder runs on local small models' as an assertion."""
        violations = ra.route_violations([
            {"slug": "a", "need": 9, "provider": "local", "model": "llama3.2:3b"},
            {"slug": "b", "need": 9, "provider": "claude", "model": "claude-opus-4-8"},
            {"slug": "c", "need": 4, "provider": "local", "model": "llama3.2:3b"},
        ])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].detail["slug"], "a")
        self.assertEqual(violations[0].action, "demote_route")

    def test_non_coder_stages_are_not_violations(self):
        self.assertEqual(ra.route_violations([
            {"slug": "a", "need": 9, "provider": "local", "model": "llama3.2:3b", "stage": "qa"},
        ]), [])

    def test_garbage_records_are_skipped(self):
        self.assertEqual(ra.route_violations([None, "x", {}]), [])


def _task(project, route, queued=0, claimed=None, coder=None, qa=None, merged=None,
          released=None, attempt=0):
    return {"project": project, "route": route, "queued_at": queued, "claimed_at": claimed,
            "coder_done_at": coder, "qa_at": qa, "merged_at": merged,
            "released_at": released, "attempt": attempt}


class StageCycleTests(unittest.TestCase):
    def test_stage_durations_are_computed_per_stage(self):
        d = ra.stage_durations(_task("p", "r", 0, 10, 70, 80, 100, 130))
        self.assertEqual(d["queued_to_claimed"], 10)
        self.assertEqual(d["claimed_to_coder_done"], 60)
        self.assertEqual(d["merged_to_released"], 30)

    def test_missing_timestamps_yield_none_not_zero(self):
        d = ra.stage_durations(_task("p", "r", 0, 10))
        self.assertIsNone(d["claimed_to_coder_done"],
                          "an unfinished stage must not read as instantaneous")

    def test_negative_durations_are_discarded(self):
        self.assertIsNone(ra.stage_durations(_task("p", "r", 100, 10))["queued_to_claimed"])

    def test_p50_and_p90_are_reported_per_project_and_route(self):
        records = [_task("apparently", "claude", 0, i, i + 10, i + 20, i + 30, i + 40)
                   for i in range(1, 11)]
        stats = ra.stage_cycle_stats(records)
        self.assertEqual(stats["overall"]["n"], 10)
        self.assertIn("apparently", stats["by"]["project"])
        self.assertIn("claude", stats["by"]["route"])
        stage = stats["overall"]["stages"]["queued_to_claimed"]
        self.assertLessEqual(stage["p50"], stage["p90"])

    def test_first_pass_merge_rate_counts_every_task_seen(self):
        """A route that merges 2 of 12 on the first try is at 17%, not 100%."""
        records = ([_task("p", "weak", 0, 1, 2, 3, 4, 5, attempt=0) for _ in range(2)]
                   + [_task("p", "weak", 0, 1, 2, 3, attempt=0) for _ in range(10)])
        stats = ra.stage_cycle_stats(records)
        self.assertAlmostEqual(stats["by"]["route"]["weak"]["first_pass_merge_rate"], 2 / 12)

    def test_repaired_merges_do_not_count_as_first_pass(self):
        records = [_task("p", "r", 0, 1, 2, 3, 4, 5, attempt=2)]
        self.assertEqual(ra.stage_cycle_stats(records)["overall"]["first_pass_merge_rate"], 0.0)
        self.assertEqual(ra.stage_cycle_stats(records)["overall"]["merge_rate"], 1.0)

    def test_slowest_stage_is_identified(self):
        records = [_task("p", "r", 0, 1, 500, 501, 502, 503)]
        self.assertEqual(ra.slowest_stage(ra.stage_cycle_stats(records)["overall"]),
                         "claimed_to_coder_done")

    def test_route_leaderboard_puts_the_worst_route_first_and_demotes_it(self):
        records = ([_task("p", "weak", 0, 1, 2, 3, attempt=0) for _ in range(12)]
                   + [_task("p", "claude", 0, 1, 2, 3, 4, 5, attempt=0) for _ in range(12)])
        board = ra.route_leaderboard(ra.stage_cycle_stats(records))
        self.assertEqual(board[0]["route"], "weak")
        self.assertEqual(board[0]["action"], "demote_route")
        self.assertEqual(board[-1]["route"], "claude")
        self.assertEqual(board[-1]["action"], "")

    def test_a_route_with_too_few_samples_is_not_demoted(self):
        records = [_task("p", "new", 0, 1, 2, 3, attempt=0) for _ in range(2)]
        board = ra.route_leaderboard(ra.stage_cycle_stats(records))
        self.assertEqual(board[0]["action"], "")

    def test_empty_input_is_fail_soft(self):
        stats = ra.stage_cycle_stats([])
        self.assertEqual(stats["overall"]["n"], 0)
        self.assertIsNone(stats["overall"]["first_pass_merge_rate"])
        self.assertEqual(ra.route_leaderboard(stats), [])
        self.assertIsInstance(ra.render(stats), str)
        self.assertIsInstance(ra.render(None), str)


class ModelPolicyWiringTests(unittest.TestCase):
    """The floors must be unbypassable through the real entry point."""

    def setUp(self):
        import model_policy
        self.mp = model_policy
        self._raw = model_policy._choose_raw

    def tearDown(self):
        self.mp._choose_raw = self._raw

    def _stub(self, provider, model):
        self.mp._choose_raw = lambda **k: (provider, model, "stubbed cheapest capable")

    def test_choose_upgrades_a_weak_legal_class_selection(self):
        self._stub("local", "llama3.2:3b")
        provider, model, reason = self.mp.choose(task_class="legal", need=9)
        self.assertEqual(provider, "claude")
        self.assertIn("legal-class floor", reason)

    def test_choose_escalates_a_twice_failed_task(self):
        self._stub("claude", "claude-haiku-4-5-20251001")
        provider, model, reason = self.mp.choose(task_class="build", need=6,
                                                 task={"attempt": 2})
        self.assertEqual((provider, model), ra.STRONGEST_ROUTE)
        self.assertIn("route-escalation", reason)

    def test_choose_leaves_cheap_first_attempts_alone(self):
        self._stub("local", "llama3.2:3b")
        provider, model, _ = self.mp.choose(task_class="build", need=4, task={"attempt": 0})
        self.assertEqual((provider, model), ("local", "llama3.2:3b"))

    def test_choose_keeps_triage_cheap(self):
        self._stub("local", "llama3.2:3b")
        provider, model, _ = self.mp.choose(task_class="triage", need=9, task={"attempt": 5})
        self.assertEqual((provider, model), ("local", "llama3.2:3b"))

    def test_choose_still_returns_a_triple_when_the_guard_is_unavailable(self):
        self._stub("local", "llama3.2:3b")
        real = sys.modules.pop("route_accelerators")
        sys.modules["route_accelerators"] = None  # force the import to fail
        try:
            result = self.mp.choose(task_class="legal", need=9)
            self.assertEqual(len(result), 3)
        finally:
            sys.modules["route_accelerators"] = real


if __name__ == "__main__":
    unittest.main()
