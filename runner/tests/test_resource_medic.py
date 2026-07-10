"""Tests for resource_medic autonomous remediation bots. Everything is mocked — no real
processes, DB, or ollama touched."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resource_medic as rm


class MemoryGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rm.JOURNAL = os.path.join(self.tmp.name, "medic.jsonl")
        rm.STATE = os.path.join(self.tmp.name, "medic_state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_healthy_memory_no_action(self):
        with patch.object(rm, "memory_free_pct", return_value=80), \
             patch.object(rm, "_unload_heaviest_model") as unload:
            st = {}
            rm.memory_guard(st)
            unload.assert_not_called()
            self.assertEqual(st.get("mem_warn_streak", 0), 0)

    def test_warn_unloads_and_clamps(self):
        gov = MagicMock(); gov.current_limit.return_value = 10
        with patch.object(rm, "memory_free_pct", return_value=20), \
             patch.object(rm, "_unload_heaviest_model", return_value="qwen3-coder:30b (24GB)"), \
             patch.dict("sys.modules", {"resource_governor": gov}):
            st = {}
            rm.memory_guard(st)
            gov.set_throttle.assert_called()  # clamped
            self.assertEqual(st["mem_warn_streak"], 1)

    def test_critical_reaps_agent(self):
        gov = MagicMock(); gov.current_limit.return_value = 4
        with patch.object(rm, "memory_free_pct", return_value=5), \
             patch.object(rm, "_unload_heaviest_model", return_value=None), \
             patch.object(rm, "_reap_oldest_agent", return_value="pid=999 age=200min") as reap, \
             patch.dict("sys.modules", {"resource_governor": gov}):
            rm.memory_guard({})
            reap.assert_called_once()

    def test_sustained_pressure_lowers_lanes_durably(self):
        with patch.object(rm, "memory_free_pct", return_value=20), \
             patch.object(rm, "_unload_heaviest_model", return_value=None), \
             patch.dict(os.environ, {"MAX_PARALLEL": "10"}), \
             patch.object(rm, "_set_fleet_config", return_value=True) as setcfg, \
             patch.object(rm, "_escalate") as esc:
            st = {"mem_warn_streak": 4}
            rm.memory_guard(st)  # streak hits 5
            setcfg.assert_any_call("MAX_PARALLEL", 8)
            esc.assert_called()
            self.assertEqual(st["mem_warn_streak"], 0)  # reset after durable fix


class ThrashHunterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rm.JOURNAL = os.path.join(self.tmp.name, "medic.jsonl")
        rm.SENTINEL_LOG = os.path.join(self.tmp.name, "sentinel.log")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_clamp_events(self, n, model="qwen3-coder:30b"):
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        with open(rm.JOURNAL, "w") as f:
            for _ in range(n):
                f.write(json.dumps({"at": now + "Z", "bot": "sentinel", "action": "ram-clamp",
                                    "detail": f"unloading {model} (24GB)"}) + "\n")

    def test_model_clamp_thrash_excludes_model_durably(self):
        self._write_clamp_events(5)
        with patch.dict(os.environ, {"ORCH_CANARY_ONLY_OLLAMA_MODELS": ""}), \
             patch.object(rm, "_set_fleet_config", return_value=True) as setcfg, \
             patch.object(rm, "_escalate") as esc:
            rm.thrash_hunter({})
            # the offending model must be added to the canary-only blocklist
            calls = [c for c in setcfg.call_args_list if c.args and c.args[0] == "ORCH_CANARY_ONLY_OLLAMA_MODELS"]
            self.assertTrue(calls)
            self.assertIn("qwen3-coder:30b", calls[-1].args[1])
            esc.assert_called()

    def test_below_threshold_no_exclude(self):
        self._write_clamp_events(2)
        with patch.object(rm, "_set_fleet_config", return_value=True) as setcfg:
            rm.thrash_hunter({})
            model_calls = [c for c in setcfg.call_args_list
                           if c.args and c.args[0] == "ORCH_CANARY_ONLY_OLLAMA_MODELS"]
            self.assertFalse(model_calls)

    def test_restart_storm_lowers_lanes(self):
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        with open(rm.JOURNAL, "w") as f:
            for _ in range(6):
                f.write(json.dumps({"at": now + "Z", "bot": "sentinel",
                                    "action": "runner-cycled", "detail": "x"}) + "\n")
        with patch.dict(os.environ, {"MAX_PARALLEL": "10"}), \
             patch.object(rm, "_set_fleet_config", return_value=True) as setcfg, \
             patch.object(rm, "_escalate"):
            rm.thrash_hunter({})
            setcfg.assert_any_call("MAX_PARALLEL", 8)


class ProcessHygieneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        rm.JOURNAL = os.path.join(self.tmp.name, "medic.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reaps_only_multihour_agents(self):
        # one 200-min agent, one 5-min agent
        procs = [(200 * 60, "111", "node /opt/homebrew/bin/gemini"),
                 (5 * 60, "222", "aider --message x")]
        killed = []
        with patch.object(rm, "_agent_procs", return_value=procs), \
             patch.object(rm, "sh", side_effect=lambda *a, **k: killed.append(a) or MagicMock(stdout="")):
            rm.process_hygiene()
        # only the 200-min agent's pid should be killed
        kill_pids = [a[2] for a in killed if len(a) >= 3 and a[0] == "kill"]
        self.assertIn("111", kill_pids)
        self.assertNotIn("222", kill_pids)


class MemPressureParseTest(unittest.TestCase):
    def test_parse_free_pct(self):
        out = "System-wide memory free percentage: 31%\n"
        with patch.object(rm, "sh", return_value=MagicMock(stdout=out)):
            self.assertEqual(rm.memory_free_pct(), 31)

    def test_missing_returns_none(self):
        with patch.object(rm, "sh", return_value=MagicMock(stdout="garbage")):
            self.assertIsNone(rm.memory_free_pct())


if __name__ == "__main__":
    unittest.main()
