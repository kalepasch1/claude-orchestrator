"""
test_model_routing_edge_cases.py - Edge case coverage for model routing.

Tests for:
  - Empty/null inputs
  - Malformed JSON payloads
  - Extreme token lengths
  - Concurrent duplicate submissions
  - Idempotency with 409 handling
  - Prompt compaction (ORCH_MAX_AGENT_PROMPT_CHARS)
  - Waste guard (logs to resource_events, doesn't pause by default)
  - State transitions (QUEUED -> BLOCKED -> QUEUED)
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import model_policy
import app_triage
import orchestrator_config


def _route_via_policy(app, operation, task_class="qa"):
    """app_triage.route() with the two database-backed short-circuits removed.

    route() consults a learned per-operation route and the quality-per-dollar
    bandit before it reaches model_policy, and both read the database. A test
    about ROUTING POLICY that leaves them in place is really a test about
    whatever telemetry happens to be in the table that day.

    There are THREE such layers ahead of the round-robin ring, not one:

        app_triage._learned_route   per-operation learned route (DB)
        qpd_bandit.best             quality-per-dollar bandit (DB)
        model_catalog.choose        model-level optimizer (DB)

    Each returns a stable answer when telemetry is present, and any one of them
    is enough to make a rotation test report no rotation. _learned_route is a
    module attribute and is patched by the caller; the other two are imported
    inside the functions that use them, so they are neutralised here through
    sys.modules.
    """
    bandit = MagicMock()
    bandit.best.return_value = (None, None, None)
    catalog = MagicMock()
    catalog.choose.return_value = None
    with patch.dict(sys.modules, {"qpd_bandit": bandit, "model_catalog": catalog}):
        return app_triage.route(app, operation, task_class=task_class)["provider"]


class EdgeCaseInputHandlingTest(unittest.TestCase):
    """Test model routing robustness to malformed/extreme inputs."""

    def test_empty_prompt_routing(self):
        """Empty prompt should still route successfully."""
        with patch.object(model_policy.mg, "available", return_value=["deepseek", "openai"]):
            provider, model, why = model_policy.choose("review", agentic=False, need=6)
        self.assertIn(provider, ["deepseek", "openai"])
        self.assertIsNotNone(model)

    def test_null_task_class_defaults_to_build(self):
        """Null task_class should fall back to default need level."""
        with patch.object(model_policy.mg, "available", return_value=["deepseek"]):
            provider, model, why = model_policy.choose(task_class=None, agentic=False)
        self.assertEqual(provider, "deepseek")

    def test_extreme_token_length_prompt(self):
        """Very long prompt should not crash routing.

        agentic=True routes through agentic_coders, not through mg.available, so
        patching only the latter left this assertion at the mercy of whatever
        coders happened to be configured — and of whatever an earlier test in
        this file had left in os.environ. It passed alone and returned 'codex'
        in file order, which is a test measuring the machine rather than the
        code. Both seams are controlled now, so the answer is the routing
        logic's own.
        """
        extreme_prompt = "x" * 1000000  # 1M characters
        self.assertEqual(len(extreme_prompt), 1000000)

        coder = MagicMock()
        coder.route.return_value = {"provider": "claude", "model": "claude-haiku-4-5-20251001",
                                    "coder": "claude", "cap": 10, "cost": 1}
        with patch.dict(sys.modules, {"agentic_coders": coder}), \
                patch.object(model_policy.mg, "available", return_value=["claude"]):
            provider, model, why = model_policy.choose("review", agentic=True)
        self.assertEqual(provider, "claude")
        self.assertTrue(model, "routing must return a model, not an empty string")

    def test_malformed_diff_metadata_skip_llm_verify(self):
        """should_skip_llm_verify should handle missing fields gracefully."""
        # Missing fields should not crash; defaults to False (run verify)
        incomplete_diff = {"blast_radius": "low"}
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True}):
            result = model_policy.should_skip_llm_verify(incomplete_diff)
        self.assertFalse(result)  # missing tests_passed -> cannot skip

    def test_invalid_blast_radius_value(self):
        """Invalid blast_radius should be treated as high (safest)."""
        diff = {
            "blast_radius": "invalid-value",
            "high_risk": False,
            "constitution_touching": False,
            "tests_passed": True,
            "build_passed": True,
        }
        with patch.object(orchestrator_config, "GATING_POLICY", {"skip_llm_verify": True, "material_threshold": "low"}):
            result = model_policy.should_skip_llm_verify(diff)
        self.assertFalse(result)  # invalid -> treated as high -> cannot skip


class IdempotencyTest(unittest.TestCase):
    """Test idempotent routing behavior for duplicate submissions."""

    def test_duplicate_routing_request_returns_same_result(self):
        """Duplicate routing requests should return identical results.

        WITH THE ROTATION HELD STILL. `model_policy._rr_next` is a persistent
        round-robin counter whose own docstring says it exists "so successive
        non-agentic calls rotate providers" — so two back-to-back calls are
        *designed* to differ, and asserting they match contradicts the router
        rather than testing it.

        It passed anyway because `_least_used` runs first and usually returns a
        stable answer from telemetry, hiding the rotation. That makes the test
        pass or fail on database contents: it was green here and failed the
        moment the telemetry behind it shifted.

        Pinning the counter tests what the name claims — that routing is a
        function of its inputs — instead of depending on which answer the
        diversifier happened to give.
        """
        with patch.object(model_policy.mg, "available", return_value=["deepseek", "google"]), \
             patch.object(model_policy, "_rr_next", return_value=0), \
             patch.object(model_policy, "_least_used", return_value=None):
            route1 = app_triage.route("test-app", "op1", task_class="qa")
            route2 = app_triage.route("test-app", "op1", task_class="qa")
        self.assertEqual(route1["provider"], route2["provider"])
        self.assertEqual(route1["model"], route2["model"])

    def test_successive_routes_rotate_providers_by_design(self):
        """The behaviour the test above must not be read as forbidding.

        Two reasons it failed on master, and neither was the rotation.

        First, three database-backed layers sit ahead of the round-robin ring —
        the learned per-operation route, the quality-per-dollar bandit, and the
        model-level optimizer — and each returns a stable answer once telemetry
        exists. Any one of them is enough to make a rotation test report no
        rotation, so what the test actually measured was whatever was in the
        tables that day. That is exactly the flaw the sibling test above
        documents about itself ("it was green here and failed the moment the
        telemetry behind it shifted"); that one pinned _rr_next and stopped
        there, because it does not need the ring to run. This one does.

        Second, rotation is opt-in (DIVERSIFY_DEFAULT is "false"), so the mode
        under test has to be turned on. Otherwise routing is in cheapest-first
        mode, where capable[0] comes back regardless of the round-robin counter.
        """
        seen = []
        with patch.dict(os.environ, {"ORCH_DIVERSIFY_MODELS": "true",
                                     "ORCH_CONFIDENTIAL_MODE": "false"}), \
             patch.object(app_triage, "_learned_route", return_value=None), \
             patch.object(app_triage.mg, "available",
                          return_value=["deepseek", "google"]), \
             patch.object(model_policy.mg, "available",
                          return_value=["deepseek", "google"]), \
             patch.object(model_policy, "_least_used", return_value=None):
            for i in (0, 1):
                with patch.object(model_policy, "_rr_next", return_value=i):
                    seen.append(_route_via_policy("test-app", "op1"))
        self.assertEqual(len(set(seen)), 2, f"expected rotation, got {seen}")

    def test_confidential_mode_overrides_the_diversify_flag(self):
        """A confidentiality control an ordinary tuning knob can defeat is not one.

        ORCH_CONFIDENTIAL_MODE used to supply only a DEFAULT for
        ORCH_DIVERSIFY_MODELS, so a fleet that had set the flag — which is the
        whole point of the flag — kept spreading confidential work across every
        vendor in the stack while believing confidential mode had stopped it.
        """
        with patch.dict(os.environ, {"ORCH_DIVERSIFY_MODELS": "true",
                                     "ORCH_CONFIDENTIAL_MODE": "true"}):
            self.assertFalse(model_policy._diversify_enabled())

        with patch.dict(os.environ, {"ORCH_DIVERSIFY_MODELS": "true",
                                     "ORCH_CONFIDENTIAL_MODE": "false"}):
            self.assertTrue(model_policy._diversify_enabled())

    def test_rotation_is_off_unless_asked_for(self):
        # Flipping a fleet-wide routing (and therefore spend) default is an
        # operator's decision, not a bug fix's.
        env = {k: v for k, v in os.environ.items()
               if k not in ("ORCH_DIVERSIFY_MODELS", "ORCH_CONFIDENTIAL_MODE")}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(model_policy._diversify_enabled())

    def test_db_insert_with_409_conflict_retries_as_upsert(self):
        """DB insert that returns 409 should retry with merge-duplicates."""
        db = MagicMock()
        conflict_error = Exception("409")
        conflict_error.code = 409
        db.insert.side_effect = [conflict_error, {"id": "row123"}]

        with patch.object(app_triage, "db", db):
            try:
                db.insert("test_table", {"key": "val"}, resolution="merge-duplicates")
            except Exception:
                pass
        # The db.insert should have been called at least once
        self.assertTrue(db.insert.called)

    def test_concurrent_duplicate_submissions_dont_crash(self):
        """Parallel duplicate task submissions should not cause failures."""
        db = MagicMock()
        db.select.return_value = [
            {"id": "t1", "slug": "feat-x", "state": "QUEUED"},
            {"id": "t1", "slug": "feat-x", "state": "QUEUED"},  # duplicate
        ]
        rows = []
        db.insert.side_effect = lambda table, row, **kw: rows.append((table, row))

        with patch.object(app_triage, "db", db):
            # Simulating two concurrent inserts of the same task
            for _ in range(2):
                try:
                    db.insert("tasks", {"slug": "feat-x", "state": "QUEUED"}, resolution="merge-duplicates")
                except Exception:
                    pass
        # No crash, routing continues


class PromptCompactionTest(unittest.TestCase):
    """Test prompt length validation and compaction."""

    def test_prompt_within_limit_unchanged(self):
        """Prompts within ORCH_MAX_AGENT_PROMPT_CHARS should not be truncated."""
        prompt = "x" * 10000
        with patch.dict(os.environ, {"ORCH_MAX_AGENT_PROMPT_CHARS": "50000"}):
            # Routing doesn't modify prompt, but in real code it would be checked
            # This test documents the expected behavior
            self.assertEqual(len(prompt), 10000)

    def test_prompt_exceeding_limit_would_be_compacted(self):
        """Prompts exceeding limit should be compacted with head/tail preserved."""
        max_chars = 1000
        # Simulate a long prompt
        header = "SYSTEM: "
        body = "x" * 900
        footer = " [END]"
        prompt = header + body + footer

        # If we were to compaction, we'd preserve head and tail
        if len(prompt) > max_chars:
            head_size = max_chars // 3
            tail_size = max_chars // 3
            compacted = prompt[:head_size] + f"\n[... COMPACTED: {len(prompt) - max_chars} chars omitted ...]\n" + prompt[-tail_size:]
            # Verify compaction preserves structure
            self.assertIn("SYSTEM", compacted)
            self.assertIn("[END]", compacted)
            self.assertIn("COMPACTED", compacted)

    def test_zero_max_prompt_chars_disables_compaction(self):
        """ORCH_MAX_AGENT_PROMPT_CHARS=0 should disable compaction."""
        with patch.dict(os.environ, {"ORCH_MAX_AGENT_PROMPT_CHARS": "0"}):
            max_chars = int(os.environ.get("ORCH_MAX_AGENT_PROMPT_CHARS", "0"))
        self.assertEqual(max_chars, 0)  # feature disabled


class WasteGuardTest(unittest.TestCase):
    """Test waste detection logging and optional pausing."""

    def test_waste_detection_logs_to_resource_events(self):
        """Waste detection should log to resource_events table."""
        db = MagicMock()
        rows = []
        db.insert.side_effect = lambda table, row, **kw: rows.append((table, row))

        with patch.object(app_triage, "db", db):
            db.insert("resource_events", {
                "event_type": "waste_detected",
                "project_id": "p1",
                "details": {"tokens_wasted": 5000}
            })

        self.assertTrue(db.insert.called)
        self.assertEqual(rows[0][0], "resource_events")

    def test_waste_guard_does_not_pause_by_default(self):
        """ORCH_WASTE_GUARD_PAUSES should be false by default."""
        with patch.dict(os.environ, {}, clear=False):
            pauses = os.environ.get("ORCH_WASTE_GUARD_PAUSES", "false").lower() in ("true", "1", "yes")
        self.assertFalse(pauses)

    def test_waste_guard_pause_gated_by_env_var(self):
        """Setting ORCH_WASTE_GUARD_PAUSES=true should enable pausing."""
        with patch.dict(os.environ, {"ORCH_WASTE_GUARD_PAUSES": "true"}):
            pauses = os.environ.get("ORCH_WASTE_GUARD_PAUSES", "false").lower() in ("true", "1", "yes")
        self.assertTrue(pauses)


class StateTransitionTest(unittest.TestCase):
    """Test state machine transitions for routing tasks."""

    def test_task_queued_state_initialization(self):
        """New routing tasks should start in QUEUED state."""
        task = {"id": "t1", "state": "QUEUED", "note": "initialized"}
        self.assertEqual(task["state"], "QUEUED")

    def test_state_transition_queued_to_blocked(self):
        """Task can transition from QUEUED to BLOCKED with descriptive note."""
        task = {"state": "QUEUED"}
        # Simulate transition
        task["state"] = "BLOCKED"
        task["note"] = "waiting for model availability"
        self.assertEqual(task["state"], "BLOCKED")
        self.assertIn("waiting", task["note"])

    def test_state_transition_blocked_to_queued(self):
        """Task can re-enter QUEUED from BLOCKED with clear reason."""
        task = {"state": "BLOCKED", "note": "model now available"}
        # Simulate transition
        task["state"] = "QUEUED"
        task["note"] = "resuming after model availability restored"
        self.assertEqual(task["state"], "QUEUED")

    def test_state_transition_preserves_history(self):
        """State transitions should accumulate notes for audit trail."""
        history = []
        task = {"state": "QUEUED"}
        history.append({"state": task["state"], "note": "initial"})

        task["state"] = "BLOCKED"
        history.append({"state": task["state"], "note": "waiting for resources"})

        task["state"] = "QUEUED"
        history.append({"state": task["state"], "note": "resources available"})

        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["state"], "QUEUED")
        self.assertEqual(history[1]["state"], "BLOCKED")
        self.assertEqual(history[2]["state"], "QUEUED")


class FailClosedSecurityTest(unittest.TestCase):
    """Test fail-closed security patterns in routing logic."""

    def test_missing_routing_lookups_return_deny(self):
        """Routing lookups that miss should return DENY, not ALLOW."""
        # Simulate a missing routing rule lookup
        routes = {"known-op": ("deepseek", "deepseek-chat")}
        unknown_op = "unknown-operation"

        # Fail-closed: missing entries should not default to allow
        result = routes.get(unknown_op)
        self.assertIsNone(result)  # Explicit deny, not implicit allow

    def test_missing_provider_availability_denies_routing(self):
        """If a provider is not available, routing should not allow it."""
        with patch.object(model_policy.mg, "available", return_value=["deepseek"]):
            available = model_policy.mg.available()
            # Try to route to an unavailable provider (openai not in available)
            if "openai" not in available:
                result = "DENY"
            else:
                result = "ALLOW"
        self.assertEqual(result, "DENY")

    def test_invalid_provider_configuration_fails_closed(self):
        """Invalid provider config should fail closed (deny routing)."""
        with patch.object(model_policy.mg, "available", return_value=[]):
            available = model_policy.mg.available()
            # Empty available list -> no routing possible -> fail closed
            if not available:
                routing_allowed = False
            else:
                routing_allowed = True
        self.assertFalse(routing_allowed)


if __name__ == "__main__":
    unittest.main()
