#!/usr/bin/env python3
"""Acceptance tests for the counterfactual-replay spec (SPEC-RUNNER-COUNTERFACTUAL-REPLAY.md).

SUITE OWNERSHIP: this file owns the spec-level contract —
    * divergence detection (detect_policy_change / has_policy_change)
    * policy application (update_route_policy / resolve_policy_conflict)
    * the fleet_control push path, including the "never push SECRET/PASSWORD/
      TOKEN keys" preservation rule
    * the ORCH_COUNTERFACTUAL_* configuration contract
    * the replay-only guarantee (no task re-execution, no mutation of history)
Per-decision unit coverage lives in test_counterfactual_replay_comprehensive.py;
batch mechanics in test_counterfactual_replay_impl.py; persistence in
tests/test_counterfactual_replay.py; the assembled flow in tests/..._e2e.py.

NOTE ON THE SPEC ITSELF: the spec document (and this module's docstring) describe
a design — `_fetch_recent_decisions()` reading the tasks table, a model roster,
`run_replay()`, `fleet_control.apply_config_batch()` — that was never built. The
shipped module is a decision-comparison library plus a fleet_control push helper
(`push_config_updates`), and `fleet_control` exposes `update_fleet_config`, not
`apply_config_batch`. These tests assert the spec's *intent* against the code
that actually exists; each substitution is named where it is made.
"""

import importlib
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr
import fleet_control


class RecordingModel:
    """Model handle that records every evaluate() call."""

    def __init__(self, model_id="opus", version="2.0", decision="route_b", confidence=0.9):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self.calls = []

    def evaluate(self, input_data, task_type):
        self.calls.append((input_data, task_type))
        return {"decision": self._decision, "confidence": self._confidence}


# =============================================================================
# Divergence detection
# =============================================================================

class TestDetectPolicyChange:
    """detect_policy_change() — 'would the runner route differently today?'"""

    def test_different_route_is_a_change(self):
        """A different route is the divergence the spec is about."""
        change = cfr.detect_policy_change({"route": "haiku"}, {"route": "opus"})
        assert change["changed"] is True
        assert change["old_route"] == "haiku"
        assert change["new_route"] == "opus"

    def test_same_route_is_stable(self):
        """An unchanged route reports stability, with a reason."""
        change = cfr.detect_policy_change({"route": "opus"}, {"route": "opus"})
        assert change["changed"] is False
        assert change["reason"] == "decision_stable"

    def test_stable_decision_still_reports_confidence_delta(self):
        """Confidence can move even when the route does not."""
        change = cfr.detect_policy_change(
            {"route": "opus", "confidence": 0.6}, {"route": "opus", "confidence": 0.9})
        assert change["changed"] is False
        assert change["confidence_delta"] == 0.3

    def test_change_with_more_confidence_is_an_improvement(self):
        """A reroute the new model is more sure of is an improvement."""
        change = cfr.detect_policy_change(
            {"route": "haiku", "confidence": 0.5}, {"route": "opus", "confidence": 0.9})
        assert change["reason"] == "confidence_improvement"
        assert change["confidence_delta"] == 0.4

    def test_change_with_less_confidence_is_a_decline(self):
        """A reroute the new model is less sure of is flagged as a decline."""
        change = cfr.detect_policy_change(
            {"route": "haiku", "confidence": 0.9}, {"route": "opus", "confidence": 0.4})
        assert change["reason"] == "confidence_decline"
        assert change["confidence_delta"] == -0.5

    def test_equal_confidence_reroute_reads_as_decline(self):
        """A reroute with no confidence gain is not counted as an improvement.

        The reason is derived from a strictly-positive delta, so a zero delta
        falls to 'confidence_decline'. Documented here because the reason string
        drives operator triage.
        """
        change = cfr.detect_policy_change(
            {"route": "haiku", "confidence": 0.7}, {"route": "opus", "confidence": 0.7})
        assert change["changed"] is True
        assert change["reason"] == "confidence_decline"

    def test_missing_confidence_defaults_to_neutral(self):
        """Outputs with no confidence are compared at the 0.5 neutral point."""
        change = cfr.detect_policy_change({"route": "a"}, {"route": "a"})
        assert change["confidence_delta"] == 0.0

    def test_non_dict_outputs_are_not_a_change(self):
        """Two unreadable outputs give no evidence of divergence."""
        change = cfr.detect_policy_change("corrupt", None)
        assert change["changed"] is False


class TestHasPolicyChange:
    """has_policy_change() — divergence between a stored decision and its replay."""

    def test_replay_choosing_another_route_is_a_change(self):
        """The replay's 'decision' is compared against the stored 'route'."""
        old = {"output": {"route": "haiku", "confidence": 0.5}}
        replay = {"decision": "opus", "confidence": 0.9}
        assert cfr.has_policy_change(old, replay) is True

    def test_replay_reproducing_the_route_is_not_a_change(self):
        """Reproducing the stored route is the no-divergence case.

        This is the regression guard for the field-name mismatch: the replay
        result names its choice 'decision' while the stored output names it
        'route', and comparing 'route' to 'route' made every replay look like a
        divergence.
        """
        old = {"output": {"route": "opus", "confidence": 0.8}}
        replay = {"decision": "opus", "confidence": 0.8}
        assert cfr.has_policy_change(old, replay) is False

    def test_route_shaped_replay_still_supported(self):
        """A replay that already speaks 'route' is compared on that key."""
        old = {"output": {"route": "opus"}}
        assert cfr.has_policy_change(old, {"route": "opus"}) is False

    def test_unusable_decision_reports_no_change(self):
        """A decision that cannot be read claims no divergence."""
        assert cfr.has_policy_change(None, {"decision": "opus"}) is False


# =============================================================================
# Policy application
# =============================================================================

class TestUpdateRoutePolicy:
    """update_route_policy() — turn a detected divergence into a route update."""

    def test_carries_operation_and_models(self):
        """The update names the operation, the prior model and the new one."""
        change = {"changed": True, "new_route": "opus", "confidence_delta": 0.4}
        update = cfr.update_route_policy("build", {"model": "haiku"}, change)
        assert update["operation"] == "build"
        assert update["prior_model"] == "haiku"
        assert update["new_model"] == "opus"
        assert update["confidence_delta"] == 0.4

    def test_unchanged_policy_produces_no_update(self):
        """A stable decision yields updated=False."""
        change = {"changed": False, "reason": "decision_stable"}
        update = cfr.update_route_policy("build", {"model": "haiku"}, change)
        assert update["updated"] is False

    def test_changed_policy_marks_updated(self):
        """A divergence marks the update as applied."""
        change = {"changed": True, "new_route": "opus"}
        assert cfr.update_route_policy("build", {}, change)["updated"] is True

    def test_update_is_timestamped_for_audit(self):
        """Every update carries an ISO timestamp — the spec's audit trail."""
        update = cfr.update_route_policy("build", {}, {"changed": True})
        assert "T" in update["timestamp"]

    def test_bad_inputs_fail_soft(self):
        """A malformed policy change still returns a well-formed update."""
        update = cfr.update_route_policy("build", None, None)
        assert update == {"operation": "build", "updated": False}


class TestResolvePolicyConflict:
    """resolve_policy_conflict() — two machines proposing different policies."""

    def test_identical_policies_keep_existing(self):
        """Nothing to reconcile means the existing policy stands."""
        policy = {"preferred_model": "opus", "priority": "quality"}
        resolution = cfr.resolve_policy_conflict(policy, dict(policy))
        assert resolution["conflict"] is False
        assert resolution["resolution"] == "keep_existing"

    def test_differing_values_are_reported_per_key(self):
        """Each conflicting key reports both sides for the operator."""
        resolution = cfr.resolve_policy_conflict(
            {"preferred_model": "haiku", "priority": "cost"},
            {"preferred_model": "opus", "priority": "cost"},
        )
        assert resolution["conflict"] is True
        assert resolution["conflicts"] == {
            "preferred_model": {"existing": "haiku", "new": "opus"}
        }

    def test_conflict_resolves_to_merge(self):
        """The resolution strategy for a real conflict is merge."""
        resolution = cfr.resolve_policy_conflict({"a": 1}, {"a": 2})
        assert resolution["resolution"] == "merge"

    def test_key_present_on_only_one_side_is_a_conflict(self):
        """A key added by one side is a difference the operator must see."""
        resolution = cfr.resolve_policy_conflict({"a": 1}, {"a": 1, "b": 2})
        assert resolution["conflicts"] == {"b": {"existing": None, "new": 2}}

    def test_bad_inputs_fail_soft(self):
        """Unreadable policies resolve to merge instead of raising."""
        assert cfr.resolve_policy_conflict(None, None) == {
            "conflict": False, "resolution": "merge"}


# =============================================================================
# Fleet config push (the spec's "update policies via fleet_control" clause)
# =============================================================================

class TestPushConfigUpdates:
    """push_config_updates() — the only path from replay to fleet config.

    Substitution: the spec names `fleet_control.apply_config_batch()`, which does
    not exist. `update_fleet_config(key, value)` is the real gateway and is what
    push_config_updates() calls, once per key.
    """

    def test_pushes_each_key_through_fleet_control(self, monkeypatch):
        """Every accepted key is pushed via the fleet_control gateway."""
        pushed = []
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: pushed.append((k, v)))
        cfr.push_config_updates({
            "ORCH_RUNNER_ROUTE_BUILD": "opus",
            "ORCH_RUNNER_POLICY_RETRY": 3,
        })
        assert sorted(pushed) == [
            ("ORCH_RUNNER_POLICY_RETRY", "3"),
            ("ORCH_RUNNER_ROUTE_BUILD", "opus"),
        ]

    def test_values_are_stringified(self):
        """fleet_config stores strings, so values are coerced on the way out."""
        pushed = []
        original = fleet_control.update_fleet_config
        fleet_control.update_fleet_config = lambda k, v: pushed.append((k, v))
        try:
            cfr.push_config_updates({"ORCH_RUNNER_POLICY_MAX": 7})
        finally:
            fleet_control.update_fleet_config = original
        assert pushed == [("ORCH_RUNNER_POLICY_MAX", "7")]

    def test_secret_bearing_keys_are_never_pushed(self, monkeypatch):
        """The spec's preservation rule: SECRET/PASSWORD/TOKEN keys are dropped."""
        pushed = []
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: pushed.append(k))
        cfr.push_config_updates({
            "ORCH_RUNNER_ROUTE_SECRET": "x",
            "ORCH_API_TOKEN": "x",
            "ORCH_DB_PASSWORD": "x",
            "ORCH_RUNNER_ROUTE_BUILD": "opus",
        })
        assert pushed == ["ORCH_RUNNER_ROUTE_BUILD"]

    def test_non_orch_keys_are_rejected(self, monkeypatch):
        """Keys outside the fleet-config namespace are not pushed."""
        pushed = []
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: pushed.append(k))
        cfr.push_config_updates({"RANDOM_KEY": "x", "": "y"})
        assert pushed == []

    def test_push_failure_is_fail_soft(self, monkeypatch):
        """A gateway failure is wrapped, not raised at the replay loop."""
        def boom(key, value):
            raise RuntimeError("fleet unreachable")
        monkeypatch.setattr(fleet_control, "update_fleet_config", boom)
        cfr.push_config_updates({"ORCH_RUNNER_ROUTE_BUILD": "opus"})

    def test_empty_update_set_is_a_noop(self, monkeypatch):
        """Nothing to push means no gateway calls at all."""
        calls = []
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: calls.append(k))
        cfr.push_config_updates({})
        assert calls == []

    def test_safe_config_key_delegates_to_fleet_control(self):
        """Key safety is decided by fleet_control, not re-implemented here."""
        assert cfr._safe_config_key("ORCH_RUNNER_ROUTE_BUILD") is True
        assert cfr._safe_config_key("ORCH_RUNNER_ROUTE_TOKEN") is False
        assert cfr._safe_config_key("NOT_AN_ORCH_KEY") is False


# =============================================================================
# Configuration contract
# =============================================================================

class TestConfiguration:
    """ORCH_COUNTERFACTUAL_* env contract.

    Substitution: the spec names ORCH_RUNNER_REPLAY_* / ORCH_REPLAY_* env vars.
    The module reads ORCH_COUNTERFACTUAL_DAYS_BACK / _BATCH_SIZE / _ENABLED, and
    those are what these tests pin.
    """

    @staticmethod
    def _reload(monkeypatch, **env):
        """Reload the module under a temporary environment, then restore it."""
        saved_path = list(sys.path)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        try:
            return importlib.reload(cfr)
        finally:
            sys.path[:] = saved_path

    def test_defaults_match_the_documented_values(self, monkeypatch):
        """Undefined env means 7 days back, batch of 50, replay enabled."""
        for key in ("ORCH_COUNTERFACTUAL_DAYS_BACK", "ORCH_COUNTERFACTUAL_BATCH_SIZE",
                    "ORCH_COUNTERFACTUAL_ENABLED"):
            monkeypatch.delenv(key, raising=False)
        module = self._reload(monkeypatch)
        try:
            assert module.DAYS_BACK == 7
            assert module.BATCH_SIZE == 50
            assert module.ENABLED is True
        finally:
            self._reload(monkeypatch)

    def test_days_back_read_from_env(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_DAYS_BACK widens the replay window."""
        module = self._reload(monkeypatch, ORCH_COUNTERFACTUAL_DAYS_BACK="30")
        try:
            assert module.DAYS_BACK == 30
        finally:
            monkeypatch.delenv("ORCH_COUNTERFACTUAL_DAYS_BACK")
            self._reload(monkeypatch)

    def test_batch_size_read_from_env(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_BATCH_SIZE sets the replay batch size."""
        module = self._reload(monkeypatch, ORCH_COUNTERFACTUAL_BATCH_SIZE="5")
        try:
            assert module.BATCH_SIZE == 5
        finally:
            monkeypatch.delenv("ORCH_COUNTERFACTUAL_BATCH_SIZE")
            self._reload(monkeypatch)

    def test_kill_switch_is_case_insensitive(self, monkeypatch):
        """ORCH_COUNTERFACTUAL_ENABLED=FALSE disables replay."""
        module = self._reload(monkeypatch, ORCH_COUNTERFACTUAL_ENABLED="FALSE")
        try:
            assert module.ENABLED is False
        finally:
            monkeypatch.delenv("ORCH_COUNTERFACTUAL_ENABLED")
            self._reload(monkeypatch)

    def test_only_the_word_true_enables_replay(self, monkeypatch):
        """The kill switch is strict: '1'/'yes' do not enable replay."""
        module = self._reload(monkeypatch, ORCH_COUNTERFACTUAL_ENABLED="1")
        try:
            assert module.ENABLED is False
        finally:
            monkeypatch.delenv("ORCH_COUNTERFACTUAL_ENABLED")
            self._reload(monkeypatch)

    def test_no_hardcoded_config_after_reload(self, monkeypatch):
        """Config is re-read from the environment, never frozen at first import."""
        module = self._reload(monkeypatch, ORCH_COUNTERFACTUAL_DAYS_BACK="14")
        try:
            assert module.DAYS_BACK == 14
        finally:
            monkeypatch.delenv("ORCH_COUNTERFACTUAL_DAYS_BACK")
            restored = self._reload(monkeypatch)
            assert restored.DAYS_BACK == 7


# =============================================================================
# Replay-only guarantee
# =============================================================================

class TestReplayOnlyGuarantee:
    """The spec's hard rule: replay re-decides, it never re-executes."""

    def test_replay_does_not_mutate_the_stored_decision(self):
        """History is read-only; the replay result is a new object."""
        decision = {"task_id": "t1", "input": {"q": 1}, "output": {"route": "haiku"}}
        snapshot = {"task_id": "t1", "input": {"q": 1}, "output": {"route": "haiku"}}
        result = cfr.replay_decision("t1", decision, RecordingModel())
        assert decision == snapshot
        assert result is not decision

    def test_replay_invokes_the_model_exactly_once_per_decision(self):
        """One decision, one evaluation — no retries, no re-runs."""
        model = RecordingModel()
        decisions = [{"task_id": f"t{i}", "input": {"q": i}} for i in range(4)]
        cfr.replay_batch(decisions, model)
        assert len(model.calls) == 4

    def test_worktree_path_is_derived_not_created(self, tmp_path, monkeypatch):
        """A replay names a worktree path but must not materialise one."""
        monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
        path = cfr.get_worktree_path("task-1")
        assert path.endswith("wt/replay-task-1")
        assert not os.path.exists(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
