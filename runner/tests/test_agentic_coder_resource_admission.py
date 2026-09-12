"""Hermetic local coder admission: no DB, coder, model, or real telemetry."""
import ast
import contextlib
import datetime
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch


RUNNER = Path(__file__).resolve().parents[1]


class CapacityError(RuntimeError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("untrusted exception details must not be copied")


class LocalCoderResourceAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch.object(sys, "path", list(sys.path)))
        self.lane = Mock(return_value={"returncode": 0, "stdout": "done", "stderr": ""})
        self.claude = types.SimpleNamespace(
            _effective_project=lambda project: project,
            _paused=Mock(return_value=False), run=Mock(),
        )
        self.guard = types.SimpleNamespace(
            LocalCapacityError=CapacityError,
            slot=Mock(side_effect=lambda *a, **k: contextlib.nullcontext(
                {"admitted": True, "locked": True})),
        )
        self.stack.enter_context(patch.dict(sys.modules, {
            "lane_guard": types.SimpleNamespace(run_supervised=self.lane),
            "claude_cli": self.claude, "local_model_slots": self.guard,
        }))
        spec = importlib.util.spec_from_file_location(
            "isolated_agentic_coder_admission", RUNNER / "agentic_coders.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.spec = Mock(return_value={"name": "local-coder", "cmd":
            "aider --model ollama_chat/tiny:3b --message {prompt}", "est_usd": 2})
        self.stack.enter_context(patch.object(self.module, "_spec", self.spec))
        self.event = self.stack.enter_context(patch.object(self.module, "_agentic_event"))
        self.failure = self.stack.enter_context(patch.object(self.module, "record_run_failure",
                                                           return_value=None))
        self.log = self.stack.enter_context(patch.object(self.module.logging, "getLogger"))

    def run_local(self, **kwargs):
        return self.module.run("local-coder", "private coding task", "ollama_chat/tiny:3b",
                               project="example", **kwargs)

    def assert_deferred(self, result, reason):
        self.assertIs(result["deferred"], True)
        self.assertEqual(result["status"], "deferred")
        self.assertEqual(result["skipped"], "local_capacity")
        self.assertEqual(result["reason"], reason)
        self.assertEqual(result["returncode"], 75)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["cost_usd"], 0)
        self.assertEqual(result["input_tokens"], 0)
        self.assertEqual(result["output_tokens"], 0)
        self.assertIs(result["retryable"], False)
        self.assertIs(result["requires_configuration"], True)
        self.lane.assert_not_called()
        self.claude.run.assert_not_called()
        self.failure.assert_not_called()

    def test_admitted_slot_is_not_a_per_request_cli_contract(self):
        result = self.run_local()
        self.assert_deferred(result, "local_coder_policy_unverified")
        self.assertEqual(result["model"], "ollama/tiny:3b")
        self.guard.slot.assert_called_once_with("tiny:3b", operation="agentic:local-coder")

    def test_missing_guard_defers(self):
        with patch.dict(sys.modules, {"local_model_slots": None}):
            self.assert_deferred(self.run_local(), "guard_unavailable")

    def test_missing_guard_api_defers(self):
        for guard in (types.SimpleNamespace(), types.SimpleNamespace(LocalCapacityError=CapacityError)):
            with self.subTest(guard=guard), patch.dict(sys.modules, {"local_model_slots": guard}):
                self.assert_deferred(self.run_local(), "guard_unavailable")

    def test_capacity_denial_at_slot_creation_is_preserved(self):
        self.guard.slot.side_effect = CapacityError("slot_busy")
        self.assert_deferred(self.run_local(), "slot_busy")

    def test_capacity_denial_at_context_entry_is_preserved(self):
        @contextlib.contextmanager
        def denied(*args, **kwargs):
            raise CapacityError("memory_pressure")
            yield  # pragma: no cover
        self.guard.slot.side_effect = denied
        self.assert_deferred(self.run_local(), "memory_pressure")

    def test_all_resource_denials_do_not_launch_or_fallback(self):
        for reason in ("host_headroom", "host_load", "telemetry_unknown", "model_budget",
                       "model_unknown", "other_model_resident", "slot_unavailable"):
            with self.subTest(reason=reason):
                self.guard.slot.side_effect = CapacityError(reason)
                self.assert_deferred(self.run_local(), reason)

    def test_malformed_or_legacy_slot_metadata_does_not_admit(self):
        for metadata in (None, {}, {"locked": True}, {"admitted": True},
                         {"admitted": "true", "locked": True},
                         {"admitted": True, "locked": 1},
                         {"admitted": False, "locked": True}):
            with self.subTest(metadata=metadata):
                self.guard.slot.side_effect = lambda *a, **k: contextlib.nullcontext(metadata)
                self.assert_deferred(self.run_local(), "guard_unavailable")

    def test_unexpected_guard_error_is_fail_soft_without_private_details(self):
        self.guard.slot.side_effect = RuntimeError("private coding task and secret path")
        result = self.run_local()
        self.assert_deferred(result, "guard_unavailable")
        self.assertNotIn("private", result["stderr"])

    def test_untrusted_reason_is_not_reflected(self):
        for reason in ("PRIVATE input", "x" * 81, None, 123, "host_load\npassword"):
            with self.subTest(reason=reason):
                self.guard.slot.side_effect = CapacityError(reason)
                result = self.run_local()
                self.assert_deferred(result, "capacity_unavailable")
                self.assertNotIn("password", result["stderr"])

    def test_local_deferral_logs_no_start_finish_or_prompt(self):
        self.run_local()
        self.assertEqual(self.event.call_count, 1)
        self.assertEqual(self.event.call_args.args[0], "agentic_coder_deferred")
        self.assertNotIn("private coding task", str(self.event.call_args))
        self.assertNotIn("private coding task", str(self.log.mock_calls))

    def test_cli_environment_cannot_opt_out_of_contract(self):
        with patch.dict(os.environ, {"ORCH_DISABLE_LOCAL_MODEL_SLOTS": "true",
                                     "ORCH_ALLOW_UNSAFE_LOCAL_CODER": "true"}):
            self.assert_deferred(self.run_local(env={"OLLAMA_CONTEXT_LENGTH": "131072"}),
                                 "local_coder_policy_unverified")

    def test_existing_pause_guard_still_runs_first(self):
        self.claude._paused.return_value = True
        result = self.run_local()
        self.assertEqual(result["skipped"], "kill_switch")
        self.guard.slot.assert_not_called()
        self.lane.assert_not_called()

    def test_recognizes_both_local_provider_prefixes(self):
        for model in ("ollama/tiny:3b", "ollama_chat/tiny:3b"):
            with self.subTest(model=model):
                self.assertEqual(self.module._ollama_model_for({}, model), "tiny:3b")

    def test_local_command_forms_and_secondary_models_cannot_bypass(self):
        for cmd in ("aider --model ollama/tiny:3b", "aider --model=ollama_chat/tiny:3b",
                    "aider --model 'ollama_chat/tiny:3b'",
                    'aider --model="ollama/tiny:3b"',
                    "aider --model openai/foo --weak-model ollama/tiny:3b",
                    "aider --editor-model=ollama_chat/tiny:3b",
                    "ollama run tiny:3b", "/opt/homebrew/bin/ollama run tiny:3b"):
            with self.subTest(cmd=cmd):
                self.assertEqual(self.module._ollama_model_for({"cmd": cmd}, "other"), "tiny:3b")
                self.spec.return_value = {"name": "local-coder", "cmd": cmd}
                result = self.module.run("local-coder", "private", "other")
                self.assert_deferred(result, "local_coder_policy_unverified")

    def test_nonlocal_provider_retains_normal_lane_behavior(self):
        self.spec.return_value = {"name": "remote", "cmd": "aider --model openai/example --message {prompt}",
                                  "est_usd": 0.02}
        with patch.dict(sys.modules, {"local_model_slots": None}):
            result = self.module.run("remote", "discuss ollama/example", "openai/example",
                                     cwd="/safe/worktree", env={"EXAMPLE": "value"}, timeout=17)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["text"], "done")
        self.assertEqual(result["cost_usd"], 0.02)
        self.assertNotIn("deferred", result)
        self.guard.slot.assert_not_called()
        self.lane.assert_called_once()
        self.assertEqual(self.lane.call_args.kwargs["cwd"], "/safe/worktree")
        self.assertEqual(self.lane.call_args.kwargs["env"]["EXAMPLE"], "value")
        self.assertEqual(self.lane.call_args.kwargs["timeout"], 17)

    def test_nonlocal_timeout_behavior_is_unchanged(self):
        self.spec.return_value = {"cmd": "remote-coder --message {prompt}"}
        self.lane.side_effect = subprocess.TimeoutExpired("remote-coder", 17)
        result = self.module.run("remote", "private", "openai/example", timeout=17)
        self.assertEqual(result["returncode"], 124)
        self.assertNotIn("deferred", result)


class RunnerCapacityConsumerTest(unittest.TestCase):
    """Execute the real branch AST without importing the live runner daemon."""
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse((RUNNER / "runner.py").read_text())
        cls.run_task = next(node for node in cls.tree.body
                            if isinstance(node, ast.FunctionDef) and node.name == "run_task")
        cls.branch = next(node for node in ast.walk(cls.run_task)
                          if isinstance(node, ast.If) and "'local_capacity'" in ast.unparse(node.test))

    def setUp(self):
        self.state = Mock()
        self.repair = Mock()
        harness = ast.parse("def consume(t, r, coder, model='caller-model'):\n    pass\n").body[0]
        harness.body = [self.branch, *ast.parse("repair()\nreturn 'continued'\n").body]
        module = ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[]))
        self.namespace = {"set_state": self.state, "repair": self.repair, "re": re}
        exec(compile(module, str(RUNNER / "runner.py"), "exec"), self.namespace)
        self.consume = self.namespace["consume"]

    def test_capacity_returns_without_repair_or_false_completion(self):
        result = {"deferred": True, "skipped": "local_capacity", "reason": "model_budget",
                  "returncode": 75, "model": "ollama/tiny:3b"}
        self.assertIsNone(self.consume({"id": "task-id"}, result, "local-coder"))
        self.state.assert_called_once_with("task-id", state="BLOCKED", force_coder="local-coder",
            model="ollama/tiny:3b", note="local inference deferred: model_budget; no coder ran; "
                 "awaiting verified local-coder transport before operator requeue")
        self.repair.assert_not_called()

    def test_other_provider_results_continue_unchanged(self):
        for result in ({"returncode": 0}, {"returncode": 1}, {"deferred": "true", "skipped": "local_capacity"},
                       {"deferred": True, "skipped": "different_policy"}):
            with self.subTest(result=result):
                self.assertEqual(self.consume({"id": "task-id"}, result, "remote"), "continued")
        self.state.assert_not_called()
        self.assertEqual(self.repair.call_count, 4)

    def test_consumer_sanitizes_reason_only_diagnostics(self):
        self.consume({"id": "task-id"}, {"deferred": True, "skipped": "local_capacity",
                     "reason": "private request\nsecret"}, "local-coder")
        self.assertEqual(self.state.call_args.kwargs["note"],
                         "local inference deferred: capacity_unavailable; no coder ran; "
                         "awaiting verified local-coder transport before operator requeue")

    def test_branch_precedes_cost_feedback_and_repairs(self):
        code = ast.unparse(self.run_task)
        position = code.index("r.get('skipped') == 'local_capacity'")
        for later in ("rc = r['returncode']", "feedback.extract_and_store(out",
                      "tests_ok = rc == 0", "credential_broker.detect_from_output(out"):
            self.assertLess(position, code.index(later))

    def test_configuration_hold_releases_existing_lease_and_reservations(self):
        set_state_node = next(node for node in self.tree.body
                              if isinstance(node, ast.FunctionDef) and node.name == "set_state")
        db = types.SimpleNamespace(update=Mock())
        lease = types.SimpleNamespace(release=Mock())
        reservation = types.SimpleNamespace(release=Mock())
        namespace = {"db": db, "branch_lease": lease}
        module = ast.fix_missing_locations(ast.Module(body=[set_state_node], type_ignores=[]))
        exec(compile(module, str(RUNNER / "runner.py"), "exec"), namespace)
        with patch.dict(sys.modules, {"file_reservation": reservation}):
            namespace["set_state"]("task-id", state="BLOCKED", force_coder="local-coder")
        lease.release.assert_called_once_with("task-id")
        reservation.release.assert_called_once_with({"id": "task-id"})
        self.assertEqual(db.update.call_args.args[2]["state"], "BLOCKED")

    def test_retry_promoter_does_not_select_configuration_holds(self):
        reaper = next(node for node in self.tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_reap_zombie_tasks")
        db = types.SimpleNamespace(select=Mock(return_value=[]), update=Mock())
        namespace = {"db": db, "_ZOMBIE_REAP_T": 0,
                     "time": types.SimpleNamespace(time=lambda: 1000),
                     "datetime": datetime, "os": types.SimpleNamespace(environ={})}
        module = ast.fix_missing_locations(ast.Module(body=[reaper], type_ignores=[]))
        exec(compile(module, str(RUNNER / "runner.py"), "exec"), namespace)
        namespace["_reap_zombie_tasks"]()
        task_queries = [call.args[1] for call in db.select.call_args_list if call.args[0] == "tasks"]
        self.assertEqual({query["state"] for query in task_queries}, {"eq.RUNNING", "eq.RETRY"})
        db.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
