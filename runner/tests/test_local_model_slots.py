import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import local_model_slots as lms


class WaitForRamTest(unittest.TestCase):
    """Regression: heavy models were admitted regardless of free RAM, so a 24GB coder
    loaded into a full box, got ram-clamped mid-generation, and reloaded on retry."""

    def _clock(self):
        t = {"now": 0.0}

        def now():
            return t["now"]

        def sleep(s):
            t["now"] += s

        return now, sleep

    def test_admits_immediately_when_ram_is_free(self):
        now, sleep = self._clock()
        ok, waited = lms.wait_for_ram("qwen3-coder:30b", free_fn=lambda: 40.0,
                                      sleep_fn=sleep, now_fn=now)
        self.assertTrue(ok)
        self.assertEqual(waited, 0.0)

    def test_waits_until_ram_frees(self):
        now, sleep = self._clock()
        reads = iter([5.0, 5.0, 30.0])
        ok, waited = lms.wait_for_ram("qwen3-coder:30b", free_fn=lambda: next(reads),
                                      sleep_fn=sleep, now_fn=now)
        self.assertTrue(ok)
        self.assertGreater(waited, 0.0)

    def test_times_out_fail_soft(self):
        now, sleep = self._clock()
        ok, waited = lms.wait_for_ram("qwen3-coder:30b", free_fn=lambda: 1.0,
                                      sleep_fn=sleep, now_fn=now)
        self.assertFalse(ok)  # not admitted clean — caller logs, still proceeds
        self.assertGreaterEqual(waited, 90.0)

    def test_unreadable_ram_admits(self):
        now, sleep = self._clock()
        ok, _ = lms.wait_for_ram("qwen3-coder:30b", free_fn=lambda: None,
                                 sleep_fn=sleep, now_fn=now)
        self.assertTrue(ok)

    def test_disabled_by_env(self):
        now, sleep = self._clock()
        with patch.dict(os.environ, {"ORCH_OLLAMA_ADMIT_WAIT_S": "0"}, clear=False):
            ok, waited = lms.wait_for_ram("qwen3-coder:30b", free_fn=lambda: 0.0,
                                          sleep_fn=sleep, now_fn=now)
        self.assertTrue(ok)
        self.assertEqual(waited, 0.0)

    def test_light_model_needs_little(self):
        now, sleep = self._clock()
        ok, _ = lms.wait_for_ram("tinyllama", free_fn=lambda: 10.0,
                                 sleep_fn=sleep, now_fn=now)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
