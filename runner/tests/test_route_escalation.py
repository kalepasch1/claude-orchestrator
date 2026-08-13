#!/usr/bin/env python3
"""Coder-route escalation — diagnosis (7) of the 2026-08-02 incident.

    weak-coder routes produced "0/12 merged" cycles on legal-class tasks

`fleet_immune_contracts` defined RouteQuality and classify_route for exactly this and said
the siblings would own the actuators. None existed — grepping runner/ for `classify_route`
returned only the contracts module — so the fleet could describe a failing route and had
nothing that would stop using it. These pin the actuator.

The negative cases matter as much as the positive ones: an escalator that fires too eagerly
sends every cheap task to the most expensive model, which is its own outage.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import route_escalation as re_mod


class TestAttemptEscalation(unittest.TestCase):
    def test_first_attempt_is_left_alone(self):
        out = re_mod.decide_route({}, route="local:qwen", attempts=0, need=3)
        self.assertFalse(out["escalated"])
        self.assertEqual(out["route"], "local:qwen")

    def test_second_attempt_still_left_alone(self):
        # "after 2 failed attempts" — attempt 1 has failed once.
        self.assertFalse(re_mod.decide_route({}, route="local:qwen", attempts=1, need=3)["escalated"])

    def test_third_attempt_forces_the_strongest_route(self):
        out = re_mod.decide_route({}, route="local:qwen", attempts=2, need=3)
        self.assertTrue(out["escalated"])
        self.assertEqual(out["reason"], re_mod.REASON_ATTEMPTS)
        self.assertEqual(out["route"], re_mod.STRONGEST_CODER)

    def test_escalation_ignores_cost_score_and_task_class(self):
        # The directive says "regardless of qpd cost score" — a cheap, low-need task that
        # has failed twice still escalates.
        out = re_mod.decide_route({}, route="local:tiny", attempts=5, need=1)
        self.assertTrue(out["escalated"])
        self.assertEqual(out["reason"], re_mod.REASON_ATTEMPTS)

    def test_attempts_are_read_from_the_task_when_not_passed(self):
        out = re_mod.decide_route({"attempt": 4, "force_coder": "ollama"}, need=2)
        self.assertTrue(out["escalated"])

    def test_threshold_is_configurable(self):
        self.assertFalse(
            re_mod.decide_route({}, route="local", attempts=2, need=1, escalate_after=5)["escalated"])


class TestLegalClassFloor(unittest.TestCase):
    def test_legal_class_never_gets_a_weak_coder(self):
        out = re_mod.decide_route({}, route="local:qwen2.5-coder:32b", attempts=0, need=9)
        self.assertTrue(out["escalated"])
        self.assertEqual(out["reason"], re_mod.REASON_LEGAL_FLOOR)
        self.assertEqual(out["route"], re_mod.STRONGEST_CODER)

    def test_the_boundary_need_counts_as_legal_class(self):
        self.assertTrue(re_mod.decide_route({}, route="ollama", attempts=0, need=8)["escalated"])
        self.assertFalse(re_mod.decide_route({}, route="ollama", attempts=0, need=7)["escalated"])

    def test_legal_class_with_a_strong_coder_is_untouched(self):
        # The floor is about capability, not about always escalating.
        out = re_mod.decide_route({}, route="claude", attempts=0, need=9)
        self.assertFalse(out["escalated"])
        self.assertEqual(out["route"], "claude")

    def test_weak_coder_on_a_low_need_task_is_allowed(self):
        # Cheap models on cheap work is the point of the router; do not break it.
        self.assertFalse(re_mod.decide_route({}, route="local:qwen", attempts=0, need=4)["escalated"])

    def test_swarm_ollama_is_recognised_as_weak(self):
        self.assertTrue(re_mod.is_weak_coder("swarm:ollama:qwen"))

    def test_an_unknown_provider_is_not_treated_as_weak(self):
        # Failing the other way would escalate every task whose route spelling we do not
        # recognise — an expensive silent default.
        self.assertFalse(re_mod.is_weak_coder("some-new-provider"))
        self.assertFalse(re_mod.is_weak_coder(""))
        self.assertFalse(re_mod.is_weak_coder(None))

    def test_route_spellings_are_all_understood(self):
        for route in ("local", "local:qwen2.5-coder:32b", ("local", "qwen")):
            with self.subTest(route=route):
                self.assertTrue(re_mod.is_weak_coder(route))


class TestPrecedenceAndFailSoft(unittest.TestCase):
    def test_attempts_escalation_wins_over_the_legal_floor(self):
        # Both apply; the attempts reason is the more actionable signal.
        out = re_mod.decide_route({}, route="local", attempts=3, need=9)
        self.assertEqual(out["reason"], re_mod.REASON_ATTEMPTS)

    def test_escalation_only_ever_moves_a_route_up(self):
        # There is no path that returns a weaker route than the caller proposed.
        for attempts in range(0, 6):
            for need in (1, 5, 8, 10):
                out = re_mod.decide_route({}, route="claude", attempts=attempts, need=need)
                self.assertIn(out["route"], ("claude", re_mod.STRONGEST_CODER))

    def test_garbage_input_never_raises(self):
        for bad in (None, "nonsense", {"attempt": "x", "need": None}, {"attempt": -1}):
            with self.subTest(task=bad):
                out = re_mod.decide_route(bad if isinstance(bad, dict) else None, route=bad)
                self.assertIn("route", out)

    def test_unparseable_need_does_not_claim_legal_class(self):
        self.assertFalse(re_mod.is_legal_class("high"))
        self.assertFalse(re_mod.is_legal_class(None))


class TestRouteHealthIsAdvisory(unittest.TestCase):
    def test_the_incident_ratio_is_flagged(self):
        # 0/12 merged — the exact figure from diagnosis (7).
        out = re_mod.route_health(samples=12, merged=0, route="ollama", task_class="legal")
        self.assertEqual(out["verdict"], "demote")
        self.assertEqual(out["merge_rate"], 0.0)

    def test_a_healthy_route_is_not_flagged(self):
        self.assertEqual(re_mod.route_health(12, 9, "claude", "legal")["verdict"], "healthy")

    def test_too_few_samples_is_not_a_verdict(self):
        # Judging a route on 2 pulls is how a good route gets demoted by noise.
        self.assertEqual(re_mod.route_health(2, 0, "ollama", "legal")["verdict"], "healthy")

    def test_health_is_advisory_only_and_never_downgrades_a_live_route(self):
        # decide_route must not consult route_health to pick something cheaper.
        import inspect
        self.assertNotIn("route_health", inspect.getsource(re_mod.decide_route))


if __name__ == "__main__":
    unittest.main(verbosity=2)
