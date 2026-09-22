"""Hermetic Consilium admission tests: no real DB, job, model, or telemetry calls."""
import builtins
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / "consilium_tick.py"
DEFAULT_KEYS = (
    "ORCH_CONSILIUM_V2", "ORCH_FRONTIER_ENABLED", "OLLAMA_STRONG_MODEL", "OLLAMA_MODEL",
    "ORCH_OLLAMA_NUM_CTX", "LEGAL_DOCKET_BATCH", "ORCH_EXPERT_RESEARCH_PER_TICK",
    "ORCH_NIGHT_RESEARCH_MULT", "PUBCOM_BATCH",
)


class ConsiliumResourceAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.home = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="consilium-test-"))
        self.stack.enter_context(patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.home}))
        self.stack.enter_context(patch.object(sys, "path", list(sys.path)))
        for key in DEFAULT_KEYS:
            os.environ.pop(key, None)
        self.db = types.SimpleNamespace(upsert=Mock())
        self.host_gate = Mock(return_value={"admitted": True, "reason": "ok", "free_gb": 20})
        self.stack.enter_context(patch.dict(sys.modules, {
            "db": self.db,
            "frontier": types.SimpleNamespace(budget=lambda: {}, status=lambda: {}),
            "kill_switch": types.SimpleNamespace(is_paused=lambda _: False),
            "local_model_slots": types.SimpleNamespace(host_admission_status=self.host_gate),
        }))
        self.t = self.load_tick()
        self.process = types.SimpleNamespace(returncode=0, stdout="completed\n", stderr="")
        self.run = self.stack.enter_context(patch.object(self.t.subprocess, "run", return_value=self.process))
        self.output = self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.t.JOBS = [("expert_corps", "expert_corps.py", ["tick"], 3600, 2400)]

    def load_tick(self, config=None):
        normal_import = builtins.__import__

        def import_with_config(name, *args, **kwargs):
            if name == "db":
                for key, value in (config or {}).items():
                    os.environ.setdefault(key, value)
            return normal_import(name, *args, **kwargs)

        spec = importlib.util.spec_from_file_location("consilium_resource_test_tick", SOURCE)
        module = importlib.util.module_from_spec(spec)
        with patch("builtins.__import__", side_effect=import_with_config):
            spec.loader.exec_module(module)
        return module

    def deny(self, reason="host_load"):
        self.host_gate.return_value = {"admitted": False, "reason": reason}

    def test_unknown_telemetry_and_saturated_host_never_launch(self):
        for reason in ("telemetry_unknown", "memory_pressure", "host_headroom", "host_load"):
            with self.subTest(reason=reason):
                self.deny(reason)
                result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
                self.assertTrue(result["deferred"])
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["rc"])
                self.assertIn(reason, self.output.getvalue())
        self.run.assert_not_called()

    def test_unknown_gate_errors_and_malformed_results_fail_closed(self):
        for response in (None, {}, {"admitted": "true"}, {"admitted": 1}):
            self.host_gate.return_value = response
            self.assertTrue(self.t.run_job("x", "x.py", [], 1)["deferred"])
        self.host_gate.side_effect = RuntimeError("must not expose error payload")
        result = self.t.run_job("x", "x.py", [], 1)
        self.assertEqual(result["reason"], "host_telemetry_unavailable")
        self.assertNotIn("must not expose", self.output.getvalue())
        self.run.assert_not_called()

    def test_missing_host_gate_fails_closed(self):
        with patch.dict(sys.modules, {"local_model_slots": types.SimpleNamespace()}):
            result = self.t.run_job("x", "x.py", [], 1)
        self.assertEqual(result["reason"], "host_telemetry_unavailable")
        self.run.assert_not_called()

    def test_healthy_host_runs_once_without_admitting_a_particular_model(self):
        result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
        self.host_gate.assert_called_once_with()
        self.run.assert_called_once()
        self.assertEqual(result["rc"], 0)
        self.assertNotIn("deferred", result)
        self.assertEqual(os.environ["OLLAMA_STRONG_MODEL"], "qwen3.5:27b-mlx")
        self.assertEqual(os.environ["ORCH_FRONTIER_ENABLED"], "true")

    def test_tick_deferral_preserves_last_run_and_due_work(self):
        original = {"at": 1, "rc": 0, "secs": 12, "tail": ["previous success"]}
        self.t._save({"expert_corps": original})
        self.deny("memory_pressure")
        self.assertIsNone(self.t.tick())
        state = self.t._load()
        for key, value in original.items():
            self.assertEqual(state["expert_corps"][key], value)
        self.assertEqual(state["expert_corps"]["last_attempt"]["reason"], "memory_pressure")
        self.assertIsNone(self.t.next_due(state))
        self.assertEqual(self.t.next_due(state, now=state["expert_corps"]["last_attempt"]["retry_after"])[0], "expert_corps")
        self.host_gate.assert_called_once_with()
        self.run.assert_not_called()
        payload = json.loads(self.db.upsert.call_args.args[1]["value"])
        self.assertEqual(payload["last_runs"]["expert_corps"]["last_attempt"]["status"], "deferred")

    def test_never_run_job_remains_never_run_after_deferral(self):
        self.deny()
        self.t.tick()
        state = self.t._load()
        self.assertNotIn("at", state["expert_corps"])
        row = self.t.status()["jobs"][0]
        self.assertIsNone(row["last_run"])
        self.assertEqual(row["due_in_min"], 0)
        self.assertEqual(row["last_attempt"]["status"], "deferred")

    def test_manual_once_uses_same_gate_and_keeps_job_due(self):
        self.deny("host_headroom")
        self.t.main(["--once", "expert_corps", "manual-argument"])
        self.host_gate.assert_called_once_with()
        self.run.assert_not_called()
        self.assertNotIn("at", self.t._load()["expert_corps"])
        self.assertIn('"deferred": true', self.output.getvalue())
        self.assertIn("host_headroom", self.output.getvalue())

    def test_healthy_manual_once_preserves_arguments_and_clears_deferral(self):
        self.t._save({"expert_corps": {"last_attempt": {"status": "deferred"}}})
        self.t.main(["--once", "expert_corps", "manual-argument"])
        self.assertEqual(self.run.call_args.args[0][-1], "manual-argument")
        self.assertEqual(self.run.call_args.kwargs["timeout"], 2400)
        state = self.t._load()["expert_corps"]
        self.assertGreater(state["at"], 0)
        self.assertNotIn("last_attempt", state)
        self.assertEqual(state["rc"], 0)

    def test_manual_once_respects_kill_switch_without_overwriting_schedule(self):
        original = {"expert_corps": {"at": 1, "rc": 0}}
        self.t._save(original)
        with patch.object(self.t, "_paused", return_value=True):
            self.t.main(["--once", "expert_corps"])
        self.assertEqual(self.t._load(), original)
        self.assertIn('"status": "paused"', self.output.getvalue())
        self.host_gate.assert_not_called()
        self.run.assert_not_called()

    def test_no_due_job_does_not_probe_or_loop(self):
        self.t._save({"expert_corps": {"at": self.t.time.time()}})
        self.assertIsNone(self.t.tick())
        self.host_gate.assert_not_called()
        self.run.assert_not_called()

    def test_existing_kill_switch_still_prevents_scheduled_work(self):
        with patch.object(self.t, "_paused", return_value=True):
            self.assertIsNone(self.t.tick())
        self.host_gate.assert_not_called()
        self.run.assert_not_called()

    def test_central_config_precedes_defaults_and_environment_precedes_config(self):
        for key in DEFAULT_KEYS:
            os.environ.pop(key, None)
        os.environ["ORCH_OLLAMA_NUM_CTX"] = "2048"
        t = self.load_tick({"ORCH_OLLAMA_NUM_CTX": "8192", "OLLAMA_STRONG_MODEL": "chosen-strong",
                            "ORCH_FRONTIER_ENABLED": "false", "LEGAL_DOCKET_BATCH": "7"})
        self.assertEqual(os.environ["ORCH_OLLAMA_NUM_CTX"], "2048")
        self.assertEqual(os.environ["OLLAMA_STRONG_MODEL"], "chosen-strong")
        self.assertEqual(os.environ["ORCH_FRONTIER_ENABLED"], "false")
        self.assertEqual(t.JOBS[0][2], ["7"])
        os.environ.pop("ORCH_OLLAMA_NUM_CTX")
        self.load_tick({"ORCH_OLLAMA_NUM_CTX": "8192"})
        self.assertEqual(os.environ["ORCH_OLLAMA_NUM_CTX"], "8192")

    def test_absent_context_defaults_to_4096_without_changing_model_choice(self):
        self.assertEqual(os.environ["ORCH_OLLAMA_NUM_CTX"], "4096")
        self.assertEqual(os.environ["OLLAMA_STRONG_MODEL"], "qwen3.5:27b-mlx")

    def receipt_child(self, receipt, returncode=0):
        def run(_cmd, **kwargs):
            path = Path(kwargs["env"]["ORCH_LOCAL_CAPACITY_RECEIPT"])
            self.assertTrue(path.name.startswith("orch-local-capacity-"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            with path.open("w") as f:
                json.dump(receipt, f)
            return types.SimpleNamespace(returncode=returncode, stdout="private job output", stderr="")
        return run

    def test_swallowed_local_denial_is_partial_not_success(self):
        self.run.side_effect = self.receipt_child({"deferred": True, "reason": "model_budget"})
        self.assertIsNone(self.t.tick())
        state = self.t._load()["expert_corps"]
        self.assertNotIn("at", state)
        self.assertEqual(state["last_attempt"]["status"], "deferred")
        self.assertTrue(state["last_attempt"]["partial"])
        self.assertEqual(state["last_attempt"]["reason"], "model_budget")
        self.assertNotIn("private job output", self.output.getvalue())
        receipt_path = self.run.call_args.kwargs["env"]["ORCH_LOCAL_CAPACITY_RECEIPT"]
        self.assertFalse(Path(receipt_path).exists())
        self.assertNotEqual(os.environ.get("ORCH_LOCAL_CAPACITY_RECEIPT"), receipt_path)

    def test_real_capacity_error_receipt_is_consumed_without_inference(self):
        spec = importlib.util.spec_from_file_location("consilium_test_capacity_producer", SOURCE.with_name("local_model_slots.py"))
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)

        def run(_cmd, **kwargs):
            with patch.dict(os.environ, {"ORCH_LOCAL_CAPACITY_RECEIPT": kwargs["env"]["ORCH_LOCAL_CAPACITY_RECEIPT"]}):
                # Emulate an expert swallowing the typed error, not an actual model call.
                try:
                    raise producer.LocalCapacityError("model_budget")
                except producer.LocalCapacityError:
                    pass
            return self.process

        self.run.side_effect = run
        result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
        self.assertTrue(result["partial"])
        self.assertTrue(result["deferred"])
        self.assertEqual(result["reason"], "model_budget")

    def test_nonzero_exit_with_capacity_receipt_preserves_real_failure(self):
        self.run.side_effect = self.receipt_child({"deferred": True, "reason": "memory_pressure"}, 7)
        self.t.tick()
        state = self.t._load()["expert_corps"]
        self.assertNotIn("at", state)
        self.assertEqual(state["last_attempt"]["status"], "failed")
        self.assertEqual(state["last_attempt"]["rc"], 7)

    def test_timeout_after_capacity_denial_keeps_failure_and_due_work(self):
        def run(_cmd, **kwargs):
            self.receipt_child({"deferred": True, "reason": "model_budget"})(_cmd, **kwargs)
            raise self.t.subprocess.TimeoutExpired(_cmd, kwargs["timeout"])

        self.run.side_effect = run
        self.t.tick()
        state = self.t._load()["expert_corps"]
        self.assertNotIn("at", state)
        self.assertEqual(state["last_attempt"]["status"], "failed")
        self.assertEqual(state["last_attempt"]["rc"], -1)
        self.assertEqual(state["last_attempt"]["reason"], "model_budget")
        self.assertEqual(state["last_attempt"]["secs"], 2400)

    def test_timeout_without_capacity_receipt_remains_a_real_failure(self):
        self.run.side_effect = self.t.subprocess.TimeoutExpired(["hermetic"], 2400)
        result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
        self.assertEqual(result["rc"], -1)
        self.assertNotIn("deferred", result)

    def test_exception_after_capacity_denial_does_not_erase_receipt(self):
        def run(_cmd, **kwargs):
            self.receipt_child({"deferred": True, "reason": "memory_pressure"})(_cmd, **kwargs)
            raise RuntimeError("private child content")

        self.run.side_effect = run
        result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
        self.assertTrue(result["deferred"])
        self.assertEqual(result["rc"], -2)
        self.assertEqual(result["reason"], "memory_pressure")
        self.assertNotIn("private child content", self.output.getvalue())

    def test_free_form_receipt_and_telemetry_content_never_leak(self):
        self.run.side_effect = self.receipt_child({"deferred": True, "reason": "private legal request"})
        result = self.t.run_job("x", "x.py", [], 1)
        self.assertEqual(result["reason"], "local_capacity_receipt_invalid")
        self.deny("private legal request")
        result = self.t.run_job("x", "x.py", [], 1)
        self.assertEqual(result["reason"], "host_telemetry_unavailable")
        self.assertNotIn("private legal request", self.output.getvalue())

    def test_invalid_receipt_fails_closed_without_advancing_schedule(self):
        for receipt in ({}, [], {"deferred": True}, {"deferred": True, "reason": 5}):
            with self.subTest(receipt=receipt):
                self.run.side_effect = self.receipt_child(receipt)
                self.t.tick()
                state = self.t._load()["expert_corps"]
                self.assertNotIn("at", state)
                self.assertEqual(state["last_attempt"]["reason"], "local_capacity_receipt_invalid")

    def test_missing_and_oversized_receipts_cannot_be_treated_as_success(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                def run(_cmd, **kwargs):
                    path = Path(kwargs["env"]["ORCH_LOCAL_CAPACITY_RECEIPT"])
                    if missing:
                        path.unlink()
                    else:
                        with path.open("wb") as f:
                            f.write(b" " * 4097)
                    return self.process
                self.run.side_effect = run
                result = self.t.run_job("x", "x.py", [], 1)
                self.assertTrue(result["deferred"])
                self.assertEqual(result["reason"], "local_capacity_receipt_invalid")

    def test_existing_most_overdue_schedule_selection_is_unchanged(self):
        t = self.load_tick()
        now = 1_000_000.0
        state = {"legal_docket": {"at": now - 1300}, "publication_commission": {"at": now - 1900},
                 "paper_drafter": {"at": now - 100}}
        self.assertEqual(t.next_due(state, now=now)[0], "expert_corps")
        full = {name: {"at": now - 10} for name, *_ in t.JOBS}
        full["legal_docket"] = {"at": now - 1300}
        full["publication_commission"] = {"at": now - 3700}
        self.assertEqual(t.next_due(full, now=now)[0], "publication_commission")
        self.assertIsNone(t.next_due({name: {"at": now} for name, *_ in t.JOBS}, now=now))

    def test_deferred_never_run_job_cannot_starve_other_due_jobs(self):
        now = 1_000_000.0
        self.t.JOBS = [("blocked", "blocked.py", [], 3600, 10),
                       ("useful", "useful.py", [], 3600, 10)]
        state = {}
        deferred = {"deferred": True, "status": "deferred", "reason": "model_budget", "rc": 0}
        with patch.object(self.t.time, "time", return_value=now):
            self.t._record_result(state, "blocked", deferred)
        self.assertEqual(self.t.next_due(state, now=now)[0], "useful")
        # Fairness survives a long launchd gap: an expired retry must not restore infinity.
        self.assertEqual(self.t.next_due(state, now=now + 7200)[0], "useful")
        with patch.object(self.t.time, "time", return_value=now + 7200):
            self.t._record_result(state, "useful", {"rc": 0})
        self.assertEqual(self.t.next_due(state, now=now + 7201)[0], "blocked")
        self.assertNotIn("at", state["blocked"])

    def test_deferred_previously_run_job_yields_to_other_due_work(self):
        now = 1_000_000.0
        self.t.JOBS = [("blocked", "blocked.py", [], 3600, 10),
                       ("useful", "useful.py", [], 3600, 10)]
        state = {"blocked": {"at": 1, "rc": 0}, "useful": {"at": now - 7200, "rc": 0}}
        with patch.object(self.t.time, "time", return_value=now):
            self.t._record_result(state, "blocked", {"deferred": True, "reason": "model_budget"})
        self.assertEqual(self.t.next_due(state, now=now + 7200)[0], "useful")
        self.assertEqual(state["blocked"]["at"], 1)

    def test_deferral_backoff_is_bounded_and_completion_clears_it(self):
        now = 1_000_000.0
        state = {}
        with patch.dict(os.environ, {"ORCH_CONSILIUM_CAPACITY_RETRY_SECONDS": "600"}):
            for attempt in range(1, 12):
                with patch.object(self.t.time, "time", return_value=now):
                    self.t._record_result(state, "expert_corps", {"deferred": True, "reason": "model_budget"})
                delay = state["expert_corps"]["last_attempt"]["retry_after"] - now
                self.assertEqual(delay, min(3600, 600 * 2 ** (attempt - 1)))
                self.assertNotIn("at", state["expert_corps"])
                self.assertIsNone(self.t.next_due(state, now=now + delay - 1))
                self.assertEqual(self.t.next_due(state, now=now + delay)[0], "expert_corps")
            with patch.object(self.t.time, "time", return_value=now + 3600):
                self.t._record_result(state, "expert_corps", {"rc": 0})
        self.assertNotIn("last_attempt", state["expert_corps"])
        self.assertEqual(state["expert_corps"]["at"], now + 3600)

    def test_invalid_backoff_config_cannot_disable_bounds(self):
        for value, expected in (("nan", 600), ("inf", 600), ("bad", 600), ("-1", 600), ("0", 60), ("999999", 3600)):
            with self.subTest(value=value), patch.dict(os.environ, {"ORCH_CONSILIUM_CAPACITY_RETRY_SECONDS": value}):
                self.assertEqual(self.t._retry_delay(1), expected)

    def test_unaffected_job_failure_retains_existing_exit_code(self):
        self.process.returncode = 3
        result = self.t.run_job("expert_corps", "expert_corps.py", ["tick"], 2400)
        self.assertEqual(result["rc"], 3)
        self.assertNotIn("deferred", result)


if __name__ == "__main__":
    unittest.main()
