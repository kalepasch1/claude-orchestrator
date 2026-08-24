#!/usr/bin/env python3
"""Implementation tests for counterfactual_replay.py's batch and routing surface.

SUITE OWNERSHIP: this file owns
    * replay_batch / replay_batch_with_summary (the batch surface)
    * detect_circular_dependencies
    * RouteConfig (the in-memory route table)
    * the runtime-path helpers (_get_runtime_dir / _acquire_storage)
Per-decision units are owned by test_counterfactual_replay_comprehensive.py, the
spec contract by test_counterfactual_replay_spec.py, persistence by
tests/test_counterfactual_replay.py, and the assembled flow by tests/..._e2e.py.

This file previously tested `_fetch_recent_decisions`, `_current_model_roster`,
`run_replay` and `_apply_policy_updates` against a `counterfactual_replay.db`
attribute. The module imports no `db` and defines none of those four functions;
they are from the spec document's unbuilt design. Each test below was retargeted
onto the batch/routing behaviour that the module actually implements.
"""

import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.abspath(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr


class FakeModel:
    """Model handle with a stable decision, or a per-call varying one."""

    def __init__(self, model_id="opus", version="2.0", decision="opus", confidence=0.9):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self.calls = 0

    def evaluate(self, input_data, task_type):
        self.calls += 1
        return {"decision": self._decision, "confidence": self._confidence}


def _decision(task_id, route="haiku", confidence=0.5):
    return {
        "task_id": task_id,
        "input": {"q": task_id},
        "output": {"route": route, "confidence": confidence},
    }


# =============================================================================
# replay_batch()
# =============================================================================

class TestReplayBatch:
    """replay_batch() — replay a window of decisions against one model."""

    def test_empty_batch_returns_empty_list(self):
        """No decisions in the window means no results."""
        assert cfr.replay_batch([], FakeModel()) == []
        assert cfr.replay_batch(None, FakeModel()) == []

    def test_replays_every_valid_decision(self):
        """Each replayable decision produces one result."""
        decisions = [_decision(f"t{i}") for i in range(3)]
        results = cfr.replay_batch(decisions, FakeModel())
        assert len(results) == 3

    def test_preserves_input_order(self):
        """Results come back in the order the decisions were given."""
        decisions = [_decision("t1"), _decision("t2"), _decision("t3")]
        results = cfr.replay_batch(decisions, FakeModel())
        assert [r["original_task_id"] for r in results] == ["t1", "t2", "t3"]

    def test_skips_malformed_entries(self):
        """None and non-dict entries are skipped without aborting the batch."""
        results = cfr.replay_batch([None, "junk", _decision("t1")], FakeModel())
        assert [r["original_task_id"] for r in results] == ["t1"]

    def test_drops_unreplayable_decisions(self):
        """Decisions with neither input nor output yield no result row."""
        results = cfr.replay_batch(
            [{"task_id": "t1", "state": "DONE"}, _decision("t2")], FakeModel())
        assert [r["original_task_id"] for r in results] == ["t2"]

    def test_missing_task_id_replays_as_unknown(self):
        """A decision with no task id is still replayed, tagged 'unknown'."""
        results = cfr.replay_batch([{"input": {"q": 1}}], FakeModel())
        assert results[0]["task_id"] == "unknown"


# =============================================================================
# replay_batch_with_summary()
# =============================================================================

class TestReplayBatchWithSummary:
    """replay_batch_with_summary() — batch plus the divergence report."""

    def test_returns_results_and_summary(self):
        """The call returns the result rows alongside the summary."""
        results, summary = cfr.replay_batch_with_summary(
            [_decision("t1")], FakeModel())
        assert len(results) == 1
        assert summary["total_replayed"] == 1

    def test_total_counts_only_replayed_decisions(self):
        """Skipped decisions are not counted as replayed."""
        decisions = [_decision("t1"), {"task_id": "t2"}, None]
        _, summary = cfr.replay_batch_with_summary(decisions, FakeModel())
        assert summary["total_replayed"] == 1

    def test_models_tested_is_sorted_and_deduplicated(self):
        """The summary names each model that produced a replay, once."""
        decisions = [_decision("t1"), _decision("t2")]
        _, summary = cfr.replay_batch_with_summary(decisions, FakeModel("opus"))
        assert summary["models_tested"] == ["opus"]

    def test_counts_policy_changes(self):
        """Divergent replays are counted, not just produced.

        Regression guard: policy_changes used to be initialised to 0 and never
        written, so the summary always reported zero divergences.
        """
        decisions = [_decision("t1", route="haiku"), _decision("t2", route="haiku")]
        _, summary = cfr.replay_batch_with_summary(
            decisions, FakeModel(decision="opus"))
        assert summary["policy_changes"] == 2

    def test_stable_replays_report_no_policy_changes(self):
        """Replays that reproduce the stored route are not divergences."""
        decisions = [_decision("t1", route="opus"), _decision("t2", route="opus")]
        _, summary = cfr.replay_batch_with_summary(
            decisions, FakeModel(decision="opus", confidence=0.5))
        assert summary["policy_changes"] == 0

    def test_confidence_delta_measured_against_stored_output(self):
        """The delta compares the replay to the decision it replays."""
        decisions = [_decision("t1", confidence=0.5)]
        _, summary = cfr.replay_batch_with_summary(
            decisions, FakeModel(confidence=0.9))
        assert summary["avg_confidence_delta"] == pytest.approx(0.4)

    def test_empty_batch_summary_is_all_zero(self):
        """An empty window summarises to zeros, not to missing keys."""
        results, summary = cfr.replay_batch_with_summary([], FakeModel())
        assert results == []
        assert summary == {
            "total_replayed": 0,
            "policy_changes": 0,
            "avg_confidence_delta": 0.0,
            "models_tested": [],
        }


# =============================================================================
# detect_circular_dependencies()
# =============================================================================

class TestDetectCircularDependencies:
    """detect_circular_dependencies() — guard against replay loops."""

    def test_detects_two_node_cycle(self):
        """A mutual dependency is a cycle and names its members."""
        detection = cfr.detect_circular_dependencies({
            "task_a": {"depends_on": "task_b"},
            "task_b": {"depends_on": "task_a"},
        })
        assert detection["has_cycle"] is True
        assert set(detection["cycle"]) <= {"task_a", "task_b"}

    def test_detects_self_dependency(self):
        """A task depending on itself is a cycle."""
        detection = cfr.detect_circular_dependencies({"a": {"depends_on": "a"}})
        assert detection["has_cycle"] is True

    def test_acyclic_chain_is_clean(self):
        """A plain chain reports no cycle and an empty cycle list."""
        detection = cfr.detect_circular_dependencies({
            "a": {"depends_on": "b"},
            "b": {"depends_on": "c"},
            "c": {},
        })
        assert detection == {"has_cycle": False, "cycle": []}

    def test_empty_graph_is_clean(self):
        """No decisions, no cycles."""
        assert cfr.detect_circular_dependencies({}) == {"has_cycle": False, "cycle": []}

    def test_unhashable_graph_fails_soft(self):
        """A list of decision dicts is not a graph; it reports no cycle."""
        detection = cfr.detect_circular_dependencies([{"task_id": "a"}, {"task_id": "b"}])
        assert detection == {"has_cycle": False, "cycle": []}


# =============================================================================
# RouteConfig
# =============================================================================

class TestRouteConfig:
    """RouteConfig — the in-memory operation -> model table."""

    def test_set_then_get_route(self):
        """A set route reads back with its model and score."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku", q_score=0.4)
        assert config.get_route("build") == {
            "operation": "build", "model": "haiku", "q_score": 0.4}

    def test_unknown_operation_returns_none(self):
        """An operation that was never routed has no entry."""
        assert cfr.RouteConfig().get_route("nope") is None

    def test_update_existing_route_keeps_score_when_omitted(self):
        """Re-pointing an operation leaves its score untouched."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku", q_score=0.4)
        config.update_route("build", "opus")
        assert config.get_route("build") == {
            "operation": "build", "model": "opus", "q_score": 0.4}

    def test_update_existing_route_can_set_score(self):
        """An explicit score replaces the old one."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku", q_score=0.4)
        config.update_route("build", "opus", q_score=0.9)
        assert config.get_route("build")["q_score"] == 0.9

    def test_update_unknown_operation_creates_it(self):
        """Updating an unrouted operation registers it."""
        config = cfr.RouteConfig()
        config.update_route("deploy", "opus", q_score=0.7)
        assert config.get_route("deploy") == {
            "operation": "deploy", "model": "opus", "q_score": 0.7}

    def test_counterfactual_update_prefers_new_model(self):
        """A replay naming new_model repoints the route to it."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku")
        config.apply_counterfactual_update(
            "build", {"new_model": "opus", "model": "sonnet", "q_score_delta": 0.3})
        assert config.get_route("build")["model"] == "opus"
        assert config.get_route("build")["q_score"] == 0.3

    def test_counterfactual_update_falls_back_to_model(self):
        """A replay result that only carries 'model' still repoints the route."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku")
        config.apply_counterfactual_update("build", {"model": "opus"})
        assert config.get_route("build")["model"] == "opus"
        # No q_score_delta means the score is reset to 0.0, not preserved.
        assert config.get_route("build")["q_score"] == 0.0

    def test_counterfactual_update_fails_soft(self):
        """An unusable replay result leaves the table untouched."""
        config = cfr.RouteConfig()
        config.set_route("build", "haiku", q_score=0.4)
        config.apply_counterfactual_update("build", None)
        assert config.get_route("build")["model"] == "haiku"


# =============================================================================
# Runtime paths
# =============================================================================

class TestRuntimeHelpers:
    """_get_runtime_dir() / _acquire_storage() — where replay state lands.

    ReplayStorage's own behaviour is owned by tests/test_counterfactual_replay.py;
    only the lookup and the singleton are asserted here.
    """

    def test_runtime_dir_follows_claude_orch_home(self, tmp_path, monkeypatch):
        """CLAUDE_ORCH_HOME is the runtime root when set."""
        monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
        assert cfr._get_runtime_dir() == str(tmp_path)

    def test_runtime_dir_defaults_next_to_the_runner(self, monkeypatch):
        """Without the env var the runtime dir sits beside runner/."""
        monkeypatch.delenv("CLAUDE_ORCH_HOME", raising=False)
        assert cfr._get_runtime_dir().endswith(".runtime")

    def test_acquire_storage_is_a_singleton(self, tmp_path):
        """Repeat calls hand back the same storage object."""
        cfr.invalidate()
        try:
            first = cfr._acquire_storage(str(tmp_path))
            second = cfr._acquire_storage(str(tmp_path / "ignored"))
            assert first is second
            assert isinstance(first, cfr.ReplayStorage)
        finally:
            cfr.invalidate()

    def test_invalidate_drops_the_storage_singleton(self, tmp_path):
        """invalidate() forces the next acquire to build fresh storage."""
        cfr.invalidate()
        try:
            first = cfr._acquire_storage(str(tmp_path))
            cfr.invalidate()
            assert cfr._acquire_storage(str(tmp_path)) is not first
        finally:
            cfr.invalidate()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
