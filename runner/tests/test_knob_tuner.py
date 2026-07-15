#!/usr/bin/env python3
"""Tests for knob_tuner.py"""
import json, os, sys, unittest
from unittest.mock import MagicMock, patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import knob_tuner as kt
class TestBounds(unittest.TestCase):
    def test_clamp_low(self): self.assertEqual(kt._clamp("ORCH_MICROBATCH_SIZE", 5), 10)
    def test_clamp_high(self): self.assertEqual(kt._clamp("ORCH_MICROBATCH_SIZE", 999), 50)
    def test_clamp_in_range(self): self.assertEqual(kt._clamp("ORCH_MICROBATCH_SIZE", 25), 25)
    def test_clamp_float(self): self.assertAlmostEqual(kt._clamp("ORCH_EASY_OFFLOAD_SHARE", 0.3), 0.5)
    def test_clamp_float_high(self): self.assertAlmostEqual(kt._clamp("ORCH_EASY_OFFLOAD_SHARE", 1.5), 1.0)
class TestStep(unittest.TestCase):
    def test_step_up(self): self.assertEqual(kt._step_value("ORCH_MICROBATCH_SIZE", 20, 1), 25)
    def test_step_down(self): self.assertEqual(kt._step_value("ORCH_MICROBATCH_SIZE", 20, -1), 15)
    def test_step_clamps_hi(self): self.assertEqual(kt._step_value("ORCH_MICROBATCH_SIZE", 50, 1), 50)
    def test_step_clamps_lo(self): self.assertEqual(kt._step_value("ORCH_MICROBATCH_SIZE", 10, -1), 10)
    def test_step_float(self): self.assertAlmostEqual(kt._step_value("ORCH_EASY_OFFLOAD_SHARE", 0.7, 1), 0.75)
class TestRevert(unittest.TestCase):
    def _pending(self, mpd=10, upm=1):
        return {"history": [], "last_knob": None, "pending": {"knob": "ORCH_MICROBATCH_SIZE", "old_value": 20, "new_value": 25, "direction": 1, "merged_per_day": mpd, "usd_per_merge": upm, "ts": "2025-01-01T00:00:00"}}
    @patch.object(kt, '_save_state')
    @patch.object(kt, '_load_state')
    @patch.object(kt, '_scoreboard_metrics')
    @patch.object(kt, '_write_knob')
    def test_revert_on_worse(self, wk, sm, ls, ss):
        ls.return_value = self._pending(10, 1); sm.return_value = {"merged_per_day": 1, "usd_per_merge": 10}
        r = kt.plan_adjustment(); wk.assert_called_with("ORCH_MICROBATCH_SIZE", 20); self.assertIsNone(r)
    @patch.object(kt, '_save_state')
    @patch.object(kt, '_load_state')
    @patch.object(kt, '_scoreboard_metrics')
    def test_accept_better(self, sm, ls, ss):
        ls.return_value = self._pending(10, 1); sm.return_value = {"merged_per_day": 15, "usd_per_merge": 1}
        self.assertIsNotNone(kt.plan_adjustment())
    @patch.object(kt, '_save_state')
    @patch.object(kt, '_load_state')
    @patch.object(kt, '_scoreboard_metrics')
    def test_accept_equal(self, sm, ls, ss):
        ls.return_value = self._pending(10, 1); sm.return_value = {"merged_per_day": 10, "usd_per_merge": 1}
        self.assertIsNotNone(kt.plan_adjustment())
class TestPick(unittest.TestCase):
    def test_avoids_last(self):
        for _ in range(20): self.assertNotEqual(kt._pick_knob({"last_knob": "ORCH_MICROBATCH_SIZE"}), "ORCH_MICROBATCH_SIZE")
    def test_returns_valid(self): self.assertIn(kt._pick_knob({"last_knob": None}), kt.KNOBS)
    def test_fallback(self): self.assertIn(kt._pick_knob({"last_knob": "nonexistent"}), kt.KNOBS)
class TestPlan(unittest.TestCase):
    @patch.object(kt, '_save_state')
    @patch.object(kt, '_load_state')
    @patch.object(kt, '_scoreboard_metrics')
    def test_fresh(self, sm, ls, ss):
        ls.return_value = {"history": [], "last_knob": None, "pending": None}; sm.return_value = {"merged_per_day": 5, "usd_per_merge": 2}
        r = kt.plan_adjustment(); self.assertIsNotNone(r); self.assertIn(r[0], kt.KNOBS)
    @patch.object(kt, '_save_state')
    @patch.object(kt, '_load_state')
    @patch.object(kt, '_scoreboard_metrics')
    def test_saves(self, sm, ls, ss):
        ls.return_value = {"history": [], "last_knob": None, "pending": None}; sm.return_value = {"merged_per_day": 5, "usd_per_merge": 2}
        kt.plan_adjustment(); ss.assert_called()
class TestRead(unittest.TestCase):
    def test_from_env(self):
        os.environ["ORCH_MICROBATCH_SIZE"] = "30"; self.assertEqual(kt._read_knob("ORCH_MICROBATCH_SIZE"), 30); del os.environ["ORCH_MICROBATCH_SIZE"]
    def test_missing(self):
        os.environ.pop("ORCH_MICROBATCH_SIZE", None); self.assertIsNone(kt._read_knob("ORCH_MICROBATCH_SIZE"))
if __name__ == "__main__": unittest.main()
