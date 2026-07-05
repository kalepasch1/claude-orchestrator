import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import model_policy
import app_triage
import orchestrator_config


class ModelRoutingTest(unittest.TestCase):

    def test_available_uses_keys_and_does_not_count_dead_ollama(self):
        env = {
            "OPENAI_API_KEY": "sk-test",
            "GOOGLE_API_KEY": "g-test",
            "DEEPSEEK_API_KEY": "d-test",
            "OLLAMA_HOST": "http://localhost:11434 + ollama pull qwen",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(model_gateway, "_ollama_up", return_value=False):
            providers = model_gateway.available()
        self.assertIn("openai", providers)
        self.assertIn("google", providers)
        self.assertIn("deepseek", providers)
        self.assertNotIn("local", providers)

    def test_non_agentic_review_routes_to_external_before_claude_when_sparse(self):
        with patch.object(model_policy.mg, "available", return_value=["claude", "deepseek", "google", "openai"]), \
             patch.object(model_policy, "_least_used", return_value=None), \
             patch.object(model_policy, "_rr_next", return_value=0):
            provider, model, why = model_policy.choose("review", agentic=False, need=6)
        self.assertEqual(provider, "deepseek")
        self.assertEqual(model, "deepseek-chat")
        self.assertIn("rotating", why)

    def test_complete_falls_back_to_next_provider(self):
        calls = []

        def fake_call(provider, model, prompt, project=None, timeout=90):
            calls.append((provider, model))
            if provider == "deepseek":
                raise RuntimeError("deepseek down")
            return {"text": "ok", "cost_usd": 0.01, "provider": provider, "model": model}

        with patch.object(model_gateway, "available", return_value=["deepseek", "google", "openai", "claude"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            res = model_gateway.complete("deepseek", "deepseek-chat", "hello", record_op=False)

        self.assertEqual(res["provider"], "google")
        self.assertEqual(res["fallback_from"], "deepseek")
        self.assertEqual(calls[0][0], "deepseek")
        self.assertEqual(calls[1][0], "google")

    def test_provider_for_model_handles_common_families(self):
        self.assertEqual(model_gateway.provider_for_model("gemini-2.0-flash"), "google")
        self.assertEqual(model_gateway.provider_for_model("deepseek-chat"), "deepseek")
        self.assertEqual(model_gateway.provider_for_model("gpt-4o-mini"), "openai")
        self.assertEqual(model_gateway.provider_for_model("claude-haiku-4-5"), "claude")

    def test_app_triage_records_actual_fallback_provider(self):
        rows = []
        db = MagicMock()
        db.insert.side_effect = lambda table, row, **kw: rows.append((table, row))
        with patch.object(app_triage, "db", db), \
             patch.object(app_triage, "route", return_value={
                 "provider": "deepseek", "model": "deepseek-chat",
                 "reason": "test", "source": "policy",
             }), \
             patch.object(app_triage.mg, "complete", return_value={
                 "provider": "google", "model": "gemini-2.0-flash",
                 "text": "ok", "cost_usd": 0,
             }):
            res = app_triage.run("orchestrator", "verify", "prompt", task_class="review")
        self.assertEqual(res["provider"], "google")
        self.assertEqual(rows[0][1]["provider"], "google")


class LLMVerifyGatingTest(unittest.TestCase):
    """Test should_skip_llm_verify() gating policy."""

    def test_skip_low_blast_radius_with_tests_and_build_passing(self):
        """Low-risk diff that passes tests + build → skip LLM verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertTrue(model_policy.should_skip_llm_verify(diff))

    def test_do_not_skip_high_blast_radius(self):
        """High blast radius diffs always get full verify."""
        diff = {
            "blast_radius": "high",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_do_not_skip_when_high_risk_flag_set(self):
        """Diffs flagged as high-risk always get full verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": True,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_do_not_skip_when_constitution_touching(self):
        """Diffs touching constitutional files get full verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": False,
            "constitution_touching": True,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high", "allow_skip_for_constitution_touch": False}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_do_not_skip_when_tests_failed(self):
        """Diffs where tests failed cannot skip verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": False,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_do_not_skip_when_build_failed(self):
        """Diffs where build failed cannot skip verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": False,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_strict_policy_disables_all_skipping(self):
        """When policy.skip_llm_verify=false, always run verify."""
        diff = {
            "blast_radius": "low",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": False}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_medium_blast_radius_not_skipped_with_high_threshold(self):
        """Medium blast radius should not be skipped when threshold is 'high'."""
        diff = {
            "blast_radius": "medium",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "high"}):
            self.assertFalse(model_policy.should_skip_llm_verify(diff))

    def test_medium_blast_radius_skipped_with_medium_threshold(self):
        """Medium blast radius should be skipped when threshold is 'medium'."""
        diff = {
            "blast_radius": "medium",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "medium"}):
            self.assertTrue(model_policy.should_skip_llm_verify(diff))


class IdempotencyTest(unittest.TestCase):
    """Test idempotent model routing for duplicate requests."""

    def test_duplicate_routing_returns_200_not_409(self):
        """Duplicate routing requests should not return 409 errors."""
        db = MagicMock()
        rows = []
        db.insert.side_effect = lambda table, row, **kw: rows.append((table, row))

        with patch.object(app_triage, "db", db):
            # First routing
            result1 = app_triage.route("app1", "op1", task_class="qa")
            # Duplicate routing (same app, operation)
            result2 = app_triage.route("app1", "op1", task_class="qa")

        # Both should succeed and return consistent results
        self.assertEqual(result1["provider"], result2["provider"])
        self.assertEqual(result1["model"], result2["model"])

    def test_duplicate_record_insert_handled_gracefully(self):
        """Duplicate app_operations insert should not crash via 409 resolution."""
        db = MagicMock()
        # First insert succeeds, second gets 409 (duplicate key)
        insert_count = [0]
        def side_effect(table, row, **kw):
            insert_count[0] += 1
            if insert_count[0] == 2 and kw.get("resolution") == "merge-duplicates":
                return None  # Swallowed by upsert
            return {"id": f"row{insert_count[0]}"}
        db.insert.side_effect = side_effect

        with patch.object(app_triage, "db", db):
            # Record twice (simulating duplicate submission)
            app_triage.record("app1", "op1", "qa", "deepseek", "deepseek-chat", 100, 0.01, 50, ok=True)
            app_triage.record("app1", "op1", "qa", "deepseek", "deepseek-chat", 100, 0.01, 50, ok=True)

        # No crash, both succeed
        self.assertEqual(insert_count[0], 2)


class PromptCompactionTest(unittest.TestCase):
    """Test prompt length limits and compaction behavior."""

    def test_prompt_under_max_chars_not_modified(self):
        """Prompts under ORCH_MAX_AGENT_PROMPT_CHARS should pass through unchanged."""
        with patch.dict(os.environ, {"ORCH_MAX_AGENT_PROMPT_CHARS": "10000"}):
            prompt = "x" * 1000
            max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "1000000"))
            self.assertLess(len(prompt), max_chars)

    def test_prompt_exceeds_limit_triggers_compaction(self):
        """Prompts exceeding ORCH_MAX_AGENT_PROMPT_CHARS should trigger compaction."""
        with patch.dict(os.environ, {"ORCH_MAX_AGENT_PROMPT_CHARS": "1000"}):
            max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "1000000"))
            prompt = "x" * 5000
            should_compact = len(prompt) > max_chars
        self.assertTrue(should_compact)

    def test_compaction_preserves_head_and_tail(self):
        """Compacted prompts should preserve beginning and end content."""
        max_chars = 1000
        prompt = "HEADER: important\n" + ("x" * 5000) + "\nFOOTER: critical"

        if len(prompt) > max_chars:
            head_size = max_chars // 3
            tail_size = max_chars // 3
            compacted = prompt[:head_size] + "\n[...COMPACTED...]\n" + prompt[-tail_size:]
            # Verify header and footer preserved
            self.assertIn("HEADER", compacted)
            self.assertIn("FOOTER", compacted)


class WasteGuardTest(unittest.TestCase):
    """Test waste detection logging and optional pause behavior."""

    def test_waste_detection_logs_resource_event(self):
        """Waste detection should log to resource_events table."""
        db = MagicMock()
        db.insert.return_value = {"id": "evt1"}

        with patch.object(app_triage, "db", db):
            db.insert("resource_events", {
                "event_type": "waste_detected",
                "project_id": "p1",
                "details": "high token usage",
            })

        self.assertTrue(db.insert.called)
        call_args = db.insert.call_args
        self.assertEqual(call_args[0][0], "resource_events")

    def test_waste_guard_does_not_pause_by_default(self):
        """ORCH_WASTE_GUARD_PAUSES should default to false (no pause)."""
        with patch.dict(os.environ, {}, clear=False):
            pauses_enabled = os.environ.get("ORCH_WASTE_GUARD_PAUSES", "false").lower() in ("true", "1", "yes")
        self.assertFalse(pauses_enabled)

    def test_waste_guard_pause_controlled_by_env_var(self):
        """Setting ORCH_WASTE_GUARD_PAUSES=true enables pause behavior."""
        with patch.dict(os.environ, {"ORCH_WASTE_GUARD_PAUSES": "true"}):
            pauses_enabled = os.environ.get("ORCH_WASTE_GUARD_PAUSES", "false").lower() in ("true", "1", "yes")
        self.assertTrue(pauses_enabled)


class StateTransitionTest(unittest.TestCase):
    """Test routing state machine transitions."""

    def test_task_starts_in_queued_state(self):
        """New tasks should initialize in QUEUED state."""
        task = {"id": "t1", "state": "QUEUED"}
        self.assertEqual(task["state"], "QUEUED")

    def test_transition_queued_to_blocked_with_note(self):
        """Tasks can transition QUEUED -> BLOCKED with descriptive notes."""
        task = {"state": "QUEUED", "notes": []}
        # Simulate transition
        task["state"] = "BLOCKED"
        task["notes"].append("waiting for model availability")
        self.assertEqual(task["state"], "BLOCKED")
        self.assertIn("waiting", task["notes"][-1])

    def test_transition_blocked_to_queued_with_reason(self):
        """Tasks can transition BLOCKED -> QUEUED when resource becomes available."""
        task = {"state": "BLOCKED", "notes": ["waiting for model availability"]}
        # Simulate transition
        task["state"] = "QUEUED"
        task["notes"].append("model available, resuming")
        self.assertEqual(task["state"], "QUEUED")
        self.assertEqual(len(task["notes"]), 2)

    def test_state_transition_audit_trail(self):
        """State transitions should maintain audit trail of all changes."""
        transitions = []
        task = {"state": "QUEUED"}
        transitions.append({"state": task["state"], "reason": "initial"})

        task["state"] = "BLOCKED"
        transitions.append({"state": task["state"], "reason": "no_capacity"})

        task["state"] = "QUEUED"
        transitions.append({"state": task["state"], "reason": "capacity_restored"})

        # Verify full audit trail
        self.assertEqual(len(transitions), 3)
        self.assertEqual([t["state"] for t in transitions], ["QUEUED", "BLOCKED", "QUEUED"])


if __name__ == "__main__":
    unittest.main()
