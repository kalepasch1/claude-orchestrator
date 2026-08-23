"""Tests for resource_medic.py autonomous remediation bots.

Covers: memory_guard (predictive OOM), thrash_hunter (durable fixes),
process_hygiene (log rotation), loop_breaker (restart oscillation).
"""

import datetime
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class ResourceMedicHelperTests(unittest.TestCase):
    """Tests for core helper functions: time, state, subprocess."""

    def test_now_returns_utc_timezone_aware(self):
        import resource_medic
        now = resource_medic._now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.tzinfo, datetime.timezone.utc)

    def test_now_timestamp_format_compact_z_suffix(self):
        import resource_medic
        now = resource_medic._now()
        iso_str = now.isoformat().replace("+00:00", "Z")
        self.assertTrue(iso_str.endswith("Z"))
        self.assertNotIn("+00:00", iso_str)

    def test_load_state_empty_on_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "medic_state.json")
            with patch("resource_medic.STATE", state_file):
                import resource_medic
                st = resource_medic.load_state()
                self.assertEqual(st, {})

    def test_load_state_returns_dict_on_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "medic_state.json")
            test_state = {"mem_warn_streak": 3, "last_run": "2026-08-18T12:00:00Z"}
            with open(state_file, "w") as f:
                json.dump(test_state, f)
            with patch("resource_medic.STATE", state_file):
                import resource_medic
                st = resource_medic.load_state()
                self.assertEqual(st, test_state)

    def test_load_state_empty_on_corrupted_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "medic_state.json")
            with open(state_file, "w") as f:
                f.write("{ not valid json }")
            with patch("resource_medic.STATE", state_file):
                import resource_medic
                st = resource_medic.load_state()
                self.assertEqual(st, {})

    def test_save_state_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "medic_state.json")
            runtime_dir = os.path.join(tmpdir, ".runtime")
            test_state = {"mem_warn_streak": 5}
            with patch("resource_medic.STATE", state_file), \
                 patch("resource_medic.RUNTIME", runtime_dir):
                import resource_medic
                resource_medic.save_state(test_state)
                self.assertTrue(os.path.exists(state_file))
                with open(state_file) as f:
                    saved = json.load(f)
                self.assertEqual(saved, test_state)

    def test_save_state_fails_soft_on_permission_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "medic_state.json")
            with patch("resource_medic.STATE", state_file), \
                 patch("builtins.open", side_effect=OSError("permission denied")):
                import resource_medic
                try:
                    resource_medic.save_state({"test": "state"})
                except OSError:
                    self.fail("save_state should not raise on OSError")

    @patch("subprocess.run")
    def test_sh_runs_command_with_timeout(self, mock_run):
        mock_run.return_value = Mock(stdout="output", stderr="", returncode=0)
        import resource_medic
        result = resource_medic.sh("echo", "hello", timeout=30)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertEqual(kwargs["timeout"], 30)
        self.assertTrue(kwargs["capture_output"])
        self.assertTrue(kwargs["text"])

    @patch("subprocess.run")
    def test_sh_default_timeout(self, mock_run):
        mock_run.return_value = Mock(stdout="", stderr="", returncode=0)
        import resource_medic
        resource_medic.sh("ls")
        args, kwargs = mock_run.call_args
        self.assertEqual(kwargs["timeout"], 60)


class JournalTests(unittest.TestCase):
    """Tests for medic event journaling."""

    def test_journal_writes_json_row_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_file = os.path.join(tmpdir, "medic.jsonl")
            runtime_dir = tmpdir
            with patch("resource_medic.JOURNAL", journal_file), \
                 patch("resource_medic.RUNTIME", runtime_dir):
                import resource_medic
                resource_medic.journal("test_bot", "test_action", "test detail")
                self.assertTrue(os.path.exists(journal_file))
                with open(journal_file) as f:
                    row = json.loads(f.readline())
                self.assertEqual(row["bot"], "test_bot")
                self.assertEqual(row["action"], "test_action")
                self.assertEqual(row["detail"], "test detail")
                self.assertFalse(row["durable"])

    def test_journal_truncates_detail_to_300_chars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_file = os.path.join(tmpdir, "medic.jsonl")
            runtime_dir = tmpdir
            long_detail = "x" * 500
            with patch("resource_medic.JOURNAL", journal_file), \
                 patch("resource_medic.RUNTIME", runtime_dir):
                import resource_medic
                resource_medic.journal("bot", "action", long_detail)
                with open(journal_file) as f:
                    row = json.loads(f.readline())
                self.assertEqual(len(row["detail"]), 300)

    def test_journal_marks_durable_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal_file = os.path.join(tmpdir, "medic.jsonl")
            runtime_dir = tmpdir
            with patch("resource_medic.JOURNAL", journal_file), \
                 patch("resource_medic.RUNTIME", runtime_dir):
                import resource_medic
                resource_medic.journal("bot", "action", "detail", durable=True)
                with open(journal_file) as f:
                    row = json.loads(f.readline())
                self.assertTrue(row["durable"])

    def test_journal_fails_soft_on_write_error(self):
        with patch("resource_medic.JOURNAL", "/nonexistent/path/medic.jsonl"), \
             patch("resource_medic.RUNTIME", "/nonexistent/runtime"):
            import resource_medic
            try:
                resource_medic.journal("bot", "action", "detail")
            except OSError:
                self.fail("journal should not raise on OSError")


class MemoryGuardTests(unittest.TestCase):
    """Tests for memory_guard bot (predictive OOM prevention)."""

    def setUp(self):
        self.runtime_dir = tempfile.mkdtemp(prefix="medic-test-")
        self.journal_file = os.path.join(self.runtime_dir, "medic.jsonl")

    def tearDown(self):
        import shutil
        if os.path.exists(self.runtime_dir):
            shutil.rmtree(self.runtime_dir)

    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic.JOURNAL")
    @patch("resource_medic.RUNTIME")
    def test_memory_guard_does_nothing_when_memory_healthy(self, mock_runtime,
                                                           mock_journal,
                                                           mock_free_pct):
        mock_free_pct.return_value = 50
        import resource_medic
        st = {}
        resource_medic.memory_guard(st)
        self.assertEqual(st.get("mem_warn_streak", 0), 0)

    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic._unload_heaviest_model")
    @patch("resource_medic.journal")
    @patch("resource_medic.RUNTIME")
    def test_memory_guard_unloads_model_on_warn_level(self, mock_runtime,
                                                       mock_journal,
                                                       mock_unload,
                                                       mock_free_pct):
        mock_free_pct.return_value = 20  # below PRESSURE_WARN (25)
        mock_unload.return_value = "model:7b (9.0GB)"
        import resource_medic
        st = {}
        resource_medic.memory_guard(st)
        self.assertEqual(st["mem_warn_streak"], 1)
        mock_unload.assert_called_once()

    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic._unload_heaviest_model")
    @patch("resource_medic._reap_oldest_agent")
    @patch("resource_medic.journal")
    @patch("resource_medic.RUNTIME")
    def test_memory_guard_reaps_agent_at_critical_level(self, mock_runtime,
                                                        mock_journal,
                                                        mock_reap,
                                                        mock_unload,
                                                        mock_free_pct):
        mock_free_pct.return_value = 10  # below PRESSURE_CRIT (12)
        mock_unload.return_value = "model:7b"
        mock_reap.return_value = "pid=1234 age=120min"
        import resource_medic
        st = {}
        resource_medic.memory_guard(st)
        mock_reap.assert_called_once()

    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic._set_fleet_config")
    @patch("resource_medic._escalate")
    @patch("resource_medic.journal")
    @patch("resource_medic.RUNTIME")
    def test_memory_guard_lowers_lanes_on_sustained_pressure(self, mock_runtime,
                                                             mock_journal,
                                                             mock_escalate,
                                                             mock_config,
                                                             mock_free_pct):
        mock_free_pct.return_value = 20
        mock_config.return_value = True
        import resource_medic
        os.environ["MAX_PARALLEL"] = "10"
        st = {"mem_warn_streak": 5}
        resource_medic.memory_guard(st)
        self.assertTrue(mock_config.called)
        self.assertTrue(mock_escalate.called)
        self.assertEqual(st["mem_warn_streak"], 0)

    @patch("resource_medic.memory_free_pct")
    def test_memory_guard_handles_memory_free_pct_none(self, mock_free_pct):
        mock_free_pct.return_value = None
        import resource_medic
        st = {}
        resource_medic.memory_guard(st)
        self.assertEqual(st, {})


class LoadedModelsTests(unittest.TestCase):
    """Tests for _loaded_models() model enumeration."""

    @patch("resource_medic.sh")
    def test_loaded_models_parses_ollama_ps_output(self, mock_sh):
        # ollama ps output format: NAME MODELID PROCESSOR SIZE DETAILS
        mock_sh.return_value = Mock(stdout="NAME         MODELID    PROCESSOR  9.2GB      1234567\nmodel:13b    abc123def  cpu        20.5GB     abcdef\n")
        import resource_medic
        models = resource_medic._loaded_models()
        self.assertGreaterEqual(len(models), 1)

    @patch("resource_medic.sh")
    def test_loaded_models_returns_empty_on_error(self, mock_sh):
        mock_sh.side_effect = Exception("timeout")
        import resource_medic
        models = resource_medic._loaded_models()
        self.assertEqual(models, [])

    @patch("resource_medic.sh")
    def test_loaded_models_skips_unparseable_lines(self, mock_sh):
        # ollama ps format: NAME ID PROCESSOR SIZE (size as float)
        mock_sh.return_value = Mock(stdout="NAME         ID       PROC  SIZE\nmodel:7b     123      gpu   9.2\nmodel:13b    456      gpu   20.5\n")
        import resource_medic
        models = resource_medic._loaded_models()
        self.assertGreaterEqual(len(models), 1)

    @patch("resource_medic.sh")
    def test_loaded_models_handles_empty_output(self, mock_sh):
        mock_sh.return_value = Mock(stdout="NAME         SIZE     DIGEST\n")
        import resource_medic
        models = resource_medic._loaded_models()
        self.assertEqual(models, [])


class UnloadModelTests(unittest.TestCase):
    """Tests for _unload_heaviest_model()."""

    @patch("resource_medic._loaded_models")
    @patch("resource_medic.sh")
    @patch.dict(os.environ, {"MEDIC_UNLOAD_MIN_GB": "8"})
    def test_unload_heaviest_model_stops_large_model(self, mock_sh, mock_loaded):
        mock_loaded.return_value = [(9.2, "model:7b"), (5.0, "small:1b")]
        mock_sh.return_value = Mock(stdout="", returncode=0)
        import resource_medic
        result = resource_medic._unload_heaviest_model()
        self.assertIn("model:7b", result)
        self.assertIn("9.2GB", result)

    @patch("resource_medic._loaded_models")
    @patch("resource_medic.sh")
    @patch.dict(os.environ, {"MEDIC_UNLOAD_MIN_GB": "10"})
    def test_unload_heaviest_model_skips_below_threshold(self, mock_sh, mock_loaded):
        mock_loaded.return_value = [(5.0, "model:1b")]
        import resource_medic
        result = resource_medic._unload_heaviest_model()
        self.assertIsNone(result)

    @patch("resource_medic._loaded_models")
    def test_unload_heaviest_model_handles_empty_list(self, mock_loaded):
        mock_loaded.return_value = []
        import resource_medic
        result = resource_medic._unload_heaviest_model()
        self.assertIsNone(result)

    @patch("resource_medic._loaded_models")
    @patch("resource_medic.sh")
    def test_unload_heaviest_model_returns_none_on_stop_failure(self, mock_sh, mock_loaded):
        mock_loaded.return_value = [(9.0, "model:7b")]
        mock_sh.side_effect = Exception("ollama not running")
        import resource_medic
        result = resource_medic._unload_heaviest_model()
        self.assertIsNone(result)


class AgentProcsTests(unittest.TestCase):
    """Tests for _agent_procs() agent process enumeration."""

    @patch("resource_medic.sh")
    def test_agent_procs_finds_coding_agent_processes(self, mock_sh):
        ps_output = """  123  600  /gemini/bin/codex exec agent-slug
  456  300  /path/to/claude exec agent
  789  150  /some/other/process
"""
        mock_sh.return_value = Mock(stdout=ps_output)
        import resource_medic
        procs = resource_medic._agent_procs()
        self.assertGreaterEqual(len(procs), 1)
        pids = [p[1] for p in procs]
        self.assertIn("123", pids)

    @patch("resource_medic.sh")
    def test_agent_procs_filters_out_runner_and_sentinel(self, mock_sh):
        ps_output = """  123  600  /gemini/bin/codex exec agent
  200  400  /path/to/runner.py
  300  500  /path/to/sentinel.py
"""
        mock_sh.return_value = Mock(stdout=ps_output)
        import resource_medic
        procs = resource_medic._agent_procs()
        pids = [p[1] for p in procs]
        self.assertNotIn("200", pids)
        self.assertNotIn("300", pids)

    @patch("resource_medic.sh")
    def test_agent_procs_sorts_by_age_descending(self, mock_sh):
        ps_output = """  100  100  /gemini exec agent-a
  200  500  /claude exec agent-b
  300  50   /aider exec agent-c
"""
        mock_sh.return_value = Mock(stdout=ps_output)
        import resource_medic
        procs = resource_medic._agent_procs()
        self.assertGreater(procs[0][0], procs[1][0])

    @patch("resource_medic.sh")
    def test_agent_procs_handles_ps_error_gracefully(self, mock_sh):
        mock_sh.side_effect = Exception("ps timeout")
        import resource_medic
        procs = resource_medic._agent_procs()
        self.assertEqual(procs, [])

    @patch("resource_medic.sh")
    def test_agent_procs_skips_malformed_lines(self, mock_sh):
        ps_output = """  100  200  valid /gemini command
bad line with no spaces
  200  300  another /claude agent
"""
        mock_sh.return_value = Mock(stdout=ps_output)
        import resource_medic
        procs = resource_medic._agent_procs()
        self.assertGreaterEqual(len(procs), 1)


class ReapAgentTests(unittest.TestCase):
    """Tests for _reap_oldest_agent()."""

    @patch("resource_medic._agent_procs")
    @patch("resource_medic.sh")
    @patch("resource_medic.journal")
    def test_reap_oldest_agent_kills_oldest_process(self, mock_journal, mock_sh, mock_procs):
        mock_procs.return_value = [(3600, "1234", "gemini exec old-agent")]
        mock_sh.return_value = Mock(stdout="", returncode=0)
        import resource_medic
        result = resource_medic._reap_oldest_agent()
        self.assertIn("1234", result)
        self.assertIn("60min", result)
        mock_sh.assert_called_with("kill", "-9", "1234")

    @patch("resource_medic._agent_procs")
    def test_reap_oldest_agent_returns_none_if_no_procs(self, mock_procs):
        mock_procs.return_value = []
        import resource_medic
        result = resource_medic._reap_oldest_agent()
        self.assertIsNone(result)


class ThrashHunterTests(unittest.TestCase):
    """Tests for thrash_hunter bot (durable fixes on recurrence)."""

    @patch("resource_medic._recent_events")
    @patch("resource_medic._set_fleet_config")
    @patch("resource_medic.journal")
    @patch("resource_medic._escalate")
    def test_thrash_hunter_excludes_thrashing_models(self, mock_escalate,
                                                     mock_journal,
                                                     mock_config,
                                                     mock_events):
        events = [
            ("memory_guard", "ram-clamp", "model:7b"),
            ("memory_guard", "ram-clamp", "model:7b"),
            ("memory_guard", "ram-clamp", "model:7b"),
            ("memory_guard", "ram-clamp", "model:7b"),
        ]
        mock_events.return_value = events
        mock_config.return_value = True
        import resource_medic
        os.environ["ORCH_CANARY_ONLY_OLLAMA_MODELS"] = ""
        st = {}
        resource_medic.thrash_hunter(st)
        self.assertTrue(mock_config.called)

    @patch("resource_medic._recent_events")
    @patch("resource_medic._set_fleet_config")
    @patch("resource_medic.journal")
    def test_thrash_hunter_lowers_lanes_on_restart_storm(self, mock_journal,
                                                         mock_config,
                                                         mock_events):
        events = [
            ("sentinel", "runner-cycled", "cycle 1"),
            ("sentinel", "runner-cycled", "cycle 2"),
            ("sentinel", "runner-wedged", "wedge 1"),
            ("sentinel", "runner-wedged", "wedge 2"),
            ("sentinel", "runner-cycled", "cycle 3"),
            ("sentinel", "runner-cycled", "cycle 4"),
        ]
        mock_events.return_value = events
        mock_config.return_value = True
        import resource_medic
        os.environ["MAX_PARALLEL"] = "10"
        st = {}
        resource_medic.thrash_hunter(st)
        self.assertTrue(mock_config.called)

    @patch("resource_medic._recent_events")
    @patch("resource_medic._escalate")
    @patch("resource_medic.journal")
    def test_thrash_hunter_escalates_recurring_dedupe(self, mock_journal,
                                                      mock_escalate,
                                                      mock_events):
        events = [
            ("sentinel", "dedupe", "dup1"),
            ("sentinel", "dedupe", "dup2"),
            ("sentinel", "dedupe", "dup3"),
            ("sentinel", "dedupe", "dup4"),
            ("sentinel", "dedupe", "dup5"),
        ]
        mock_events.return_value = events
        import resource_medic
        st = {}
        resource_medic.thrash_hunter(st)
        self.assertTrue(mock_escalate.called)

    @patch("resource_medic._recent_events")
    @patch("resource_medic.journal")
    def test_thrash_hunter_does_nothing_on_no_thrash(self, mock_journal, mock_events):
        mock_events.return_value = []
        import resource_medic
        st = {"mem_warn_streak": 1}
        resource_medic.thrash_hunter(st)
        self.assertFalse(mock_journal.called)


class ProcessHygieneTests(unittest.TestCase):
    """Tests for process_hygiene bot (log rotation and cleanup)."""

    @patch("resource_medic._agent_procs")
    @patch("resource_medic.sh")
    @patch("resource_medic.journal")
    @patch.dict(os.environ, {"MEDIC_AGENT_MAX_MIN": "150"})
    def test_process_hygiene_reaps_zombie_agents(self, mock_journal, mock_sh, mock_procs):
        old_age_secs = 150 * 60 + 60  # past the 150-min threshold
        mock_procs.return_value = [(old_age_secs, "1234", "gemini exec old")]
        import resource_medic
        resource_medic.process_hygiene()
        mock_sh.assert_called()

    @patch("resource_medic.sh")
    @patch("resource_medic.journal")
    @patch("resource_medic.RUNTIME")
    def test_process_hygiene_rotates_oversized_logs(self, mock_runtime, mock_journal, mock_sh):
        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = os.path.join(tmpdir, "logs")
            os.makedirs(logs_dir)
            log_file = os.path.join(logs_dir, "test.log")
            # Create an oversized log (larger than default cap)
            with open(log_file, "wb") as f:
                f.write(b"x" * (21 * 1024 * 1024))  # 21MB, cap is 20MB

            mock_sh.return_value = Mock(stdout="", returncode=0)

            with patch("resource_medic.RUNTIME", tmpdir), \
                 patch.dict(os.environ, {"MEDIC_LOG_CAP_MB": "20"}):
                import resource_medic
                resource_medic.process_hygiene()
                # Check that log was rotated
                with open(log_file, "rb") as f:
                    content = f.read()
                self.assertIn(b"[medic: log rotated]", content)

    @patch("resource_medic._agent_procs")
    def test_process_hygiene_ignores_young_agents(self, mock_procs):
        young_age_secs = 60  # much less than 150 min
        mock_procs.return_value = [(young_age_secs, "9999", "gemini exec young")]
        import resource_medic
        with patch("resource_medic.sh") as mock_sh:
            resource_medic.process_hygiene()
            # sh should not be called with kill
            kill_calls = [c for c in mock_sh.call_args_list if "kill" in str(c)]
            self.assertEqual(len(kill_calls), 0)


class LoopBreakerTests(unittest.TestCase):
    """Tests for loop_breaker bot (restart oscillation prevention)."""

    @patch("resource_medic._recent_events")
    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic.journal")
    @patch.dict(os.environ, {"MEDIC_RESTART_STORM_N": "6", "MEDIC_COOLDOWN_S": "1800"})
    def test_loop_breaker_sets_cooldown_on_restart_storm_healthy_ram(self, mock_journal,
                                                                      mock_free_pct,
                                                                      mock_events):
        events = [
            ("sentinel", "runner-cycled", "c1"),
            ("sentinel", "runner-cycled", "c2"),
            ("sentinel", "runner-wedged", "w1"),
            ("sentinel", "runner-wedged", "w2"),
            ("sentinel", "runner-cycled", "c3"),
            ("sentinel", "runner-cycled", "c4"),
        ]
        mock_events.return_value = events
        mock_free_pct.return_value = 50  # healthy
        import resource_medic
        st = {}
        before = time.time()
        resource_medic.loop_breaker(st)
        after = time.time()
        self.assertIn("restart_cooldown_until", st)
        self.assertGreater(st["restart_cooldown_until"], before)
        self.assertLess(st["restart_cooldown_until"], after + 2000)

    @patch("resource_medic._recent_events")
    @patch("resource_medic.memory_free_pct")
    @patch("resource_medic.journal")
    def test_loop_breaker_ignores_storm_during_memory_pressure(self, mock_journal,
                                                                mock_free_pct,
                                                                mock_events):
        events = [
            ("sentinel", "runner-cycled", "c1"),
            ("sentinel", "runner-cycled", "c2"),
            ("sentinel", "runner-wedged", "w1"),
            ("sentinel", "runner-wedged", "w2"),
        ]
        mock_events.return_value = events
        mock_free_pct.return_value = 10  # critical
        import resource_medic
        st = {}
        resource_medic.loop_breaker(st)
        self.assertNotIn("restart_cooldown_until", st)

    @patch("resource_medic._recent_events")
    @patch("resource_medic.journal")
    def test_loop_breaker_does_nothing_on_no_restarts(self, mock_journal, mock_events):
        mock_events.return_value = []
        import resource_medic
        st = {}
        resource_medic.loop_breaker(st)
        self.assertEqual(st, {})


class RecentEventsTests(unittest.TestCase):
    """Tests for _recent_events() journal aggregation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="medic-events-")
        self.journal_file = os.path.join(self.tmpdir, "medic.jsonl")
        self.sentinel_log = os.path.join(self.tmpdir, "sentinel.log")

    def tearDown(self):
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    def test_recent_events_reads_medic_journal(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        past = (now - datetime.timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        row = {"at": past, "bot": "memory_guard", "action": "test", "detail": "d"}
        with open(self.journal_file, "w") as f:
            f.write(json.dumps(row) + "\n")

        with patch("resource_medic.JOURNAL", self.journal_file), \
             patch("resource_medic.SENTINEL_LOG", self.sentinel_log):
            import resource_medic
            events = resource_medic._recent_events(10)
            self.assertGreater(len(events), 0)

    def test_recent_events_filters_by_time_window(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        row = {"at": old, "bot": "memory_guard", "action": "old", "detail": "d"}
        with open(self.journal_file, "w") as f:
            f.write(json.dumps(row) + "\n")

        with patch("resource_medic.JOURNAL", self.journal_file), \
             patch("resource_medic.SENTINEL_LOG", self.sentinel_log):
            import resource_medic
            events = resource_medic._recent_events(10)
            self.assertEqual(len(events), 0)

    def test_recent_events_reads_sentinel_log(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = now.isoformat().replace("+00:00", "Z")
        sentinel_line = f"{ts} runner-cycled pid=123"
        with open(self.sentinel_log, "w") as f:
            f.write(sentinel_line + "\n")

        with patch("resource_medic.JOURNAL", self.journal_file), \
             patch("resource_medic.SENTINEL_LOG", self.sentinel_log):
            import resource_medic
            events = resource_medic._recent_events(10)
            self.assertGreater(len(events), 0)

    def test_recent_events_handles_missing_files(self):
        with patch("resource_medic.JOURNAL", "/nonexistent/j.jsonl"), \
             patch("resource_medic.SENTINEL_LOG", "/nonexistent/s.log"):
            import resource_medic
            events = resource_medic._recent_events(10)
            self.assertEqual(events, [])


class MainTests(unittest.TestCase):
    """Integration tests for main() cycle."""

    @patch("resource_medic.memory_guard")
    @patch("resource_medic.thrash_hunter")
    @patch("resource_medic.process_hygiene")
    @patch("resource_medic.loop_breaker")
    @patch("resource_medic.load_state")
    @patch("resource_medic.save_state")
    @patch("resource_medic.journal")
    def test_main_runs_all_bots(self, mock_journal, mock_save, mock_load,
                                mock_breaker, mock_hygiene, mock_hunter,
                                mock_guard):
        mock_load.return_value = {}
        import resource_medic
        resource_medic.main()
        mock_guard.assert_called_once()
        mock_hunter.assert_called_once()
        mock_hygiene.assert_called_once()
        mock_breaker.assert_called_once()

    @patch("resource_medic.memory_guard")
    @patch("resource_medic.thrash_hunter")
    @patch("resource_medic.process_hygiene")
    @patch("resource_medic.loop_breaker")
    @patch("resource_medic.load_state")
    @patch("resource_medic.save_state")
    @patch("resource_medic.journal")
    def test_main_catches_bot_exceptions(self, mock_journal, mock_save, mock_load,
                                         mock_breaker, mock_hygiene, mock_hunter,
                                         mock_guard):
        mock_load.return_value = {}
        mock_guard.side_effect = Exception("bot crash")
        import resource_medic
        try:
            resource_medic.main()
        except Exception:
            self.fail("main should not raise on bot exception")
        mock_journal.assert_called()

    @patch("resource_medic.memory_guard")
    @patch("resource_medic.thrash_hunter")
    @patch("resource_medic.process_hygiene")
    @patch("resource_medic.loop_breaker")
    @patch("resource_medic.load_state")
    @patch("resource_medic.save_state")
    def test_main_records_timings(self, mock_save, mock_load, mock_breaker,
                                  mock_hygiene, mock_hunter, mock_guard):
        mock_load.return_value = {}
        import resource_medic
        resource_medic.main()
        saved_state = mock_save.call_args[0][0]
        self.assertIn("last_timings", saved_state)
        self.assertIn("memory_guard", saved_state["last_timings"])
        self.assertIn("thrash_hunter", saved_state["last_timings"])


class EnvironmentVarsTests(unittest.TestCase):
    """Tests for environment variable configuration."""

    def test_default_thresholds_are_set(self):
        import resource_medic
        self.assertEqual(resource_medic.THRASH_WINDOW_MIN, 60)
        self.assertEqual(resource_medic.MODEL_CLAMP_THRASH_N, 4)
        self.assertEqual(resource_medic.RESTART_STORM_N, 6)
        self.assertEqual(resource_medic.AGENT_MAX_MIN, 150)
        self.assertEqual(resource_medic.LOG_CAP_MB, 20)
        self.assertEqual(resource_medic.PRESSURE_WARN, 25)
        self.assertEqual(resource_medic.PRESSURE_CRIT, 12)

    @patch.dict(os.environ, {"MEDIC_THRASH_WINDOW_MIN": "120"})
    def test_env_override_thrash_window(self):
        # Force reload to pick up env change
        import importlib
        import resource_medic
        importlib.reload(resource_medic)
        self.assertEqual(resource_medic.THRASH_WINDOW_MIN, 120)


if __name__ == "__main__":
    unittest.main()
