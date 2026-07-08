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
        # exactly the periodic-only ids for colosseum / cade tournaments / agent market /
        # committees — NOT arbitrary other jobs, and NOT the inline hot-path functions
        # (those live in the same modules but are called directly from run_task(), never
        # through this scheduler, so lean mode cannot touch them).
        expected = {"colosseum.py", "cade_tournaments.py", "agentmarket",
                    "committees", "committeecal", "committeedocket", "committeedigest",
                    "committeerollout", "committeeboard", "committeewatch",
                    "committeeminutes", "committeekg", "committeemeta"}
        self.assertEqual(runner_entrypoint._LEAN_MODE_SKIP, expected)
        self.assertNotIn("merge_train.py", runner_entrypoint._LEAN_MODE_SKIP)
        self.assertNotIn("build_daemon.py", runner_entrypoint._LEAN_MODE_SKIP)


if __name__ == "__main__":
    unittest.main()
