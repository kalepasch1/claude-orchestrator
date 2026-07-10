"""Tests for model_scout — discovery, eval scoring, auto-adopt-if-better, rollback. All network
and gateway calls are mocked."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_scout as ms


class DiscoveryTest(unittest.TestCase):
    def test_openai_style_and_skip_missing_keys(self):
        def fake_get(url, headers=None, timeout=25):
            if "openai.com" in url:
                return {"data": [{"id": "gpt-5.6"}, {"id": "gpt-5.4-mini"}, {"id": "text-embedding-3"}]}
            raise Exception("no key path shouldn't reach here")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x"}, clear=True), \
             patch.object(ms, "_get", side_effect=fake_get):
            found = ms.discover()
        self.assertIn("openai", found)
        self.assertIn("gpt-5.6", found["openai"])
        self.assertNotIn("xai", found)  # no key -> skipped

    def test_chat_coding_filter(self):
        self.assertTrue(ms._is_chat_coding_model("openai", "gpt-5.6"))
        self.assertFalse(ms._is_chat_coding_model("openai", "text-embedding-3-large"))
        self.assertFalse(ms._is_chat_coding_model("openai", "whisper-1"))


class TierClassifyTest(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(ms._classify_tier("openai", "gpt-5.6-nano"), "cheap")
        self.assertEqual(ms._classify_tier("openai", "gpt-5.6-mini"), "fast")
        self.assertEqual(ms._classify_tier("google", "gemini-3-pro"), "strong")


class EvaluateTest(unittest.TestCase):
    def test_perfect_model_scores_high(self):
        gw = MagicMock()
        gw.complete.side_effect = [
            {"text": "sum(x for x in xs if x % 2 == 0)", "cost_usd": 0.0},
            {"text": "negative", "cost_usd": 0.0},
            {"text": "3:30", "cost_usd": 0.0},
        ]
        with patch.dict("sys.modules", {"model_gateway": gw}):
            r = ms.evaluate("openai", "gpt-5.6")
        self.assertEqual(r["passes"], 3)
        self.assertGreater(r["score"], 0.7)

    def test_bad_model_scores_low(self):
        gw = MagicMock()
        gw.complete.return_value = {"text": "I cannot help", "cost_usd": 0.01}
        with patch.dict("sys.modules", {"model_gateway": gw}):
            r = ms.evaluate("openai", "dud")
        self.assertEqual(r["passes"], 0)
        self.assertLess(r["quality"], 0.34)


class AdoptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ms.JOURNAL = os.path.join(self.tmp.name, "j.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_adopts_when_better(self):
        # new model scores higher than incumbent -> env var set fleet-wide + card
        evals = {"gpt-5.6": {"score": 0.9, "quality": 1.0, "latency_ms": 200, "cost": 0.0, "passes": 3, "n": 3},
                 "gpt-5.4-mini": {"score": 0.7, "quality": 0.66, "latency_ms": 400, "cost": 0.0, "passes": 2, "n": 3}}
        with patch.dict(os.environ, {"OPENAI_FAST_MODEL": "gpt-5.4-mini"}), \
             patch.object(ms, "evaluate", side_effect=lambda p, m: evals.get(m)), \
             patch.object(ms, "_set_fleet_config", return_value=True) as setcfg, \
             patch.object(ms, "_escalate") as esc:
            st = {}
            ms.consider_adopt("openai", "gpt-5.6", st)
            setcfg.assert_any_call("OPENAI_FAST_MODEL", "gpt-5.6")
            esc.assert_called()
            self.assertIn("OPENAI_FAST_MODEL", st["adopted"])
            self.assertEqual(st["adopted"]["OPENAI_FAST_MODEL"]["prev"], "gpt-5.4-mini")

    def test_shelves_when_not_better(self):
        evals = {"gpt-5.6": {"score": 0.68, "quality": 0.66, "latency_ms": 500, "cost": 0.0, "passes": 2, "n": 3},
                 "gpt-5.4-mini": {"score": 0.72, "quality": 0.66, "latency_ms": 300, "cost": 0.0, "passes": 2, "n": 3}}
        with patch.dict(os.environ, {"OPENAI_FAST_MODEL": "gpt-5.4-mini"}), \
             patch.object(ms, "evaluate", side_effect=lambda p, m: evals.get(m)), \
             patch.object(ms, "_set_fleet_config", return_value=True) as setcfg:
            ms.consider_adopt("openai", "gpt-5.6", {})
            adopt_calls = [c for c in setcfg.call_args_list if c.args and c.args[0] == "OPENAI_FAST_MODEL"]
            self.assertFalse(adopt_calls)

    def test_unroutable_vendor_pending_gateway(self):
        with patch.object(ms, "_escalate") as esc, patch.object(ms, "evaluate") as ev:
            ms.consider_adopt("xai", "grok-5", {})
            ev.assert_not_called()  # not evaluated (can't route)
            esc.assert_called()


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ms.JOURNAL = os.path.join(self.tmp.name, "j.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reverts_on_live_regression(self):
        import time as _t
        st = {"adopted": {"OPENAI_FAST_MODEL": {"new": "gpt-5.6", "prev": "gpt-5.4-mini",
              "watch_until": _t.time() + 3600}}}
        db = MagicMock()
        db.select.return_value = [{"ok": False}] * 10 + [{"ok": True}] * 2  # 17% ok -> regression
        with patch.dict("sys.modules", {"db": db}), \
             patch.object(ms, "_set_fleet_config", return_value=True) as setcfg, \
             patch.object(ms, "_escalate") as esc:
            ms.rollback_watch(st)
            setcfg.assert_any_call("OPENAI_FAST_MODEL", "gpt-5.4-mini")  # reverted
            esc.assert_called()
            self.assertNotIn("OPENAI_FAST_MODEL", st["adopted"])


class ColdStartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ms.KNOWN = os.path.join(self.tmp.name, "known.json")
        ms.STATE = os.path.join(self.tmp.name, "state.json")
        ms.JOURNAL = os.path.join(self.tmp.name, "j.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_evaluates_tier_best(self):
        # cold start must still catch the CURRENT newest release per tier (gpt-5.6 vs gpt-5.4)
        with patch.dict(os.environ, {"OPENAI_FAST_MODEL": "gpt-5.4"}), \
             patch.object(ms, "discover", return_value={"openai": ["gpt-5.6", "gpt-5.4"]}), \
             patch.object(ms, "consider_adopt") as ca, patch.object(ms, "rollback_watch"):
            ms.main()
            ca.assert_called()  # evaluated the newest tier candidate
            self.assertEqual(ca.call_args.args[1], "gpt-5.6")
        self.assertTrue(os.path.exists(ms.KNOWN))

    def test_second_run_evaluates_new(self):
        json.dump({"openai": ["gpt-5.4"]}, open(ms.KNOWN, "w"))
        with patch.object(ms, "discover", return_value={"openai": ["gpt-5.4", "gpt-5.6"]}), \
             patch.object(ms, "consider_adopt") as ca, patch.object(ms, "rollback_watch"):
            ms.main()
            ca.assert_called()  # gpt-5.6 is new -> evaluated
            self.assertEqual(ca.call_args.args[1], "gpt-5.6")


if __name__ == "__main__":
    unittest.main()
