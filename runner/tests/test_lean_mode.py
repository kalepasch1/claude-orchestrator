import os
import sys
import unittest
import importlib.util
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "runner_entrypoint_lean_mode",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner.py"),
)
runner_entrypoint = importlib.util.module_from_spec(_RUNNER_SPEC)
_RUNNER_SPEC.loader.exec_module(runner_entrypoint)


class LeanModeTest(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORCH_LEAN_MODE", None)
            self.assertFalse(runner_entrypoint._LEAN_MODE_ON())

    def test_on_when_set(self):
        with patch.dict(os.environ, {"ORCH_LEAN_MODE": "true"}):
            self.assertTrue(runner_entrypoint._LEAN_MODE_ON())

    def test_skip_set_covers_named_subsystems_periodic_jobs_only(self):
        """The skip set is pinned exactly, so it cannot grow without a decision.

        That is the point of the exact comparison and it worked: four ids were
        added to _LEAN_MODE_SKIP — expert_corps.py, legal_docket.py,
        benchmark_redlines.py, corpus_forecaster.py — and this test went red
        until someone looked at them. They belong: runner.py records the reason
        beside them ("the most token-hungry subsystems in the fleet. Lean mode
        must be able to stop them, or a cost incident has no off switch"), all
        four are periodic-only jobs, and none is on the merge or build path.

        Listed here in the same two groups as the source, so the next addition
        lands as a deliberate edit in both places rather than as a mystery.
        """
        # The self-play subsystems the flag was introduced for.
        self_play = {"colosseum.py", "cade_tournaments.py", "agentmarket",
                     "committees", "committeecal", "committeedocket", "committeedigest",
                     "committeerollout", "committeeboard", "committeewatch",
                     "committeeminutes", "committeekg", "committeemeta"}
        # The token-hungry corps/gauntlet jobs added so a cost incident has an off switch.
        cost_sinks = {"expert_corps.py", "legal_docket.py",
                      "benchmark_redlines.py", "corpus_forecaster.py"}
        self.assertEqual(runner_entrypoint._LEAN_MODE_SKIP, self_play | cost_sinks)
        # NOT arbitrary other jobs, and NOT the inline hot-path functions (those live in
        # the same modules but are called directly from run_task(), never through this
        # scheduler, so lean mode cannot touch them).
        self.assertNotIn("merge_train.py", runner_entrypoint._LEAN_MODE_SKIP)
        self.assertNotIn("build_daemon.py", runner_entrypoint._LEAN_MODE_SKIP)

    def test_lean_mode_never_skips_a_delivery_path_job(self):
        """A cost switch must not become a delivery switch.

        The exact-set assertion above catches any change; this says WHY a change
        would be wrong for the jobs that actually ship work, so the next person
        adding an id has the rule in front of them rather than a diff.
        """
        for job in ("merge_train.py", "build_daemon.py", "release_train.py",
                    "integration_sweeper.py", "deploy_watch.py"):
            self.assertNotIn(job, runner_entrypoint._LEAN_MODE_SKIP,
                             f"{job} is on the delivery path; lean mode must not stop it")


if __name__ == "__main__":
    unittest.main()
