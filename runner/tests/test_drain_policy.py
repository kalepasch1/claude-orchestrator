import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import drain_policy


class DrainPolicyTest(unittest.TestCase):
    def test_explicit_drain_skips_improve_but_allows_prewarm(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertTrue(drain_policy.should_skip("spec"))
            self.assertFalse(drain_policy.should_skip("prewarm"))

    def test_auto_mode_uses_queue_floor(self):
        with patch.dict(
            os.environ,
            {"ORCH_DRAIN_MODE": "auto", "ORCH_DRAIN_QUEUE_FLOOR": "10"},
            clear=False,
        ):
            self.assertFalse(drain_policy.should_skip("spec", queue_depth=9))
            self.assertTrue(drain_policy.should_skip("spec", queue_depth=10))

    def test_non_generator_is_not_skipped(self):
        with patch.dict(os.environ, {"ORCH_DRAIN_MODE": "true"}, clear=False):
            self.assertFalse(drain_policy.should_skip("merge_train.py"))


if __name__ == "__main__":
    unittest.main()
