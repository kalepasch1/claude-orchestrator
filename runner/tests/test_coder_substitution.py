#!/usr/bin/env python3
"""`_pick_raw` ends ~8 branches with `return ranked[0]["name"] if ranked else "claude"`.

Each of those fires exactly when the health-filtered candidate list came back
empty — so the sicker the fleet got, the more reliably routing fell through to
Claude. On 2026-08-24 that stamped six of seven canary tasks with
"agentic coder: claude" while Claude was demoted for hitting its weekly
subscription limit.

`_substitute_if_dead` is the single seam that catches all eight.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agentic_coders as ac  # noqa: E402

POOL = [
    {"name": "claude", "cmd": "", "cost": 3, "cap": 10, "daily_usd": 0},
    {"name": "codex", "cmd": "codex exec --full-auto", "cost": 2, "cap": 8,
     "daily_usd": 0},
    {"name": "ollama", "cmd": "aider --model ollama/deepseek-coder-v2:16b",
     "cost": 0, "cap": 8, "daily_usd": 0},
    {"name": "ollama-2", "cmd": "aider --model ollama/gemma3:12b",
     "cost": 0, "cap": 7, "daily_usd": 0},
]


def _env(pool=POOL, demoted=("claude",)):
    """Pin the pool and the demote registry so routing is deterministic."""
    fake_sla = mock.Mock()
    fake_sla.is_demoted = lambda p: p in demoted
    return [
        mock.patch.object(ac, "_pool", lambda: list(pool)),
        mock.patch.dict(sys.modules, {"provider_failover_sla": fake_sla}),
        mock.patch.object(ac, "_within_cap", lambda c: True),
        mock.patch.object(ac, "_allowed_by_terms", lambda c, s: True),
        mock.patch.object(ac, "_heavy_ollama_saturated", lambda c: False),
    ]


class _Ctx:
    def __init__(self, patches):
        self._p = patches

    def __enter__(self):
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in reversed(self._p):
            p.stop()
        return False


class TestSubstitution(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("ORCH_CODER_PROVIDER_HEALTH_GATE")
        os.environ["ORCH_CODER_PROVIDER_HEALTH_GATE"] = "true"

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("ORCH_CODER_PROVIDER_HEALTH_GATE", None)
        else:
            os.environ["ORCH_CODER_PROVIDER_HEALTH_GATE"] = self._prev

    def test_demoted_claude_is_replaced(self):
        with _Ctx(_env()):
            got = ac._substitute_if_dead("claude", {"slug": "t", "kind": "build"})
        self.assertNotEqual(got, "claude")
        self.assertTrue(got.startswith("ollama"), got)

    def test_healthy_choice_is_left_alone(self):
        with _Ctx(_env(demoted=())):
            self.assertEqual(
                ac._substitute_if_dead("claude", {"slug": "t"}), "claude")

    def test_cheapest_qualifying_survivor_wins(self):
        # ollama (cost 0, cap 8) beats codex (cost 2) even though both qualify.
        with _Ctx(_env(demoted=("claude",))):
            self.assertEqual(
                ac._substitute_if_dead("claude", {"slug": "t", "_need": 8}),
                "ollama")

    def test_will_not_downgrade_below_the_capability_need(self):
        """Reversed. This first asserted the opposite, and was wrong.

        The original read: "need=10 is met by nobody once claude is out; do not
        stall — take the strongest survivor rather than returning a dead
        coder." tests/test_coder_routing_selection.py disagreed, and it was
        right: a critical task landed on a cap-8 local coder.

        Under-capable output is not a smaller version of the work. It is
        plausible-but-wrong output that then needs review capacity which — in
        exactly the situation that triggers this path — does not exist either.
        A stalled queue is visible; a queue full of confident wrong merges is
        not, and that is what this whole incident was made of.
        """
        with _Ctx(_env(demoted=("claude",))):
            got = ac._substitute_if_dead("claude", {"slug": "t", "_need": 10})
        self.assertEqual(got, "claude",
                         "no survivor clears need=10, so nothing may be substituted")

    def test_substitutes_when_a_survivor_does_clear_the_need(self):
        with _Ctx(_env(demoted=("claude",))):
            got = ac._substitute_if_dead("claude", {"slug": "t", "_need": 8})
        self.assertEqual(got, "ollama")

    def test_no_healthy_alternative_returns_original(self):
        # Fail-open: the caller has no None branch, so a dead coder still beats
        # returning nothing.
        with _Ctx(_env(demoted=("claude", "openai", "ollama"))):
            self.assertEqual(
                ac._substitute_if_dead("claude", {"slug": "t"}), "claude")

    def test_avoided_names_are_not_substituted_in(self):
        with _Ctx(_env(demoted=("claude",))):
            got = ac._substitute_if_dead(
                "claude", {"slug": "t", "_need": 7,
                           "_avoid_coders": ["ollama", "ollama-2"]})
        self.assertEqual(got, "codex")

    def test_unknown_coder_name_is_passed_through(self):
        # cowork-skill / swarm:* are not pool entries; never rewrite them.
        with _Ctx(_env()):
            self.assertEqual(
                ac._substitute_if_dead("cowork-skill", {"slug": "t"}),
                "cowork-skill")
            self.assertEqual(
                ac._substitute_if_dead("swarm:google", {"slug": "t"}),
                "swarm:google")

    def test_gate_disabled_is_a_passthrough(self):
        os.environ["ORCH_CODER_PROVIDER_HEALTH_GATE"] = "false"
        with _Ctx(_env()):
            self.assertEqual(
                ac._substitute_if_dead("claude", {"slug": "t"}), "claude")

    def test_empty_name_is_returned_unchanged(self):
        with _Ctx(_env()):
            self.assertEqual(ac._substitute_if_dead("", {"slug": "t"}), "")
            self.assertIsNone(ac._substitute_if_dead(None, {"slug": "t"}))

    def test_never_raises(self):
        with mock.patch.object(ac, "_pool", side_effect=RuntimeError("boom")):
            self.assertEqual(
                ac._substitute_if_dead("claude", {"slug": "t"}), "claude")


class TestPickAppliesSubstitution(unittest.TestCase):
    """The wrapper must apply on BOTH of pick()'s return paths."""

    def setUp(self):
        os.environ["ORCH_CODER_PROVIDER_HEALTH_GATE"] = "true"

    def test_normal_path(self):
        with _Ctx(_env()), mock.patch.object(ac, "_pick_raw",
                                             lambda t, s=0: "claude"):
            self.assertNotEqual(ac.pick({"slug": "t", "kind": "build"}), "claude")

    def test_avoid_path(self):
        with _Ctx(_env()), mock.patch.object(ac, "_pick_raw",
                                             lambda t, s=0: "claude"):
            got = ac.pick({"slug": "t", "kind": "build",
                           "_avoid_coders": ["ollama-2"]})
        self.assertNotEqual(got, "claude")
        self.assertNotEqual(got, "ollama-2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
