#!/usr/bin/env python3
"""End-to-end integration tests for counterfactual_replay.

SUITE OWNERSHIP: this file owns the assembled pipeline — window selection ->
batch replay -> divergence detection -> route update -> persistence -> fleet
config push. Each individual function is unit-tested elsewhere:
    * per-decision units: runner/test_counterfactual_replay_comprehensive.py
    * spec contract / fleet push rules: runner/test_counterfactual_replay_spec.py
    * batch + RouteConfig: runner/test_counterfactual_replay_impl.py
    * persistence + counters: tests/test_counterfactual_replay.py
The assertions here deliberately re-exercise those functions in combination;
that is the only intentional duplication in the cluster.

This file previously drove load_decisions / _load_model_roster / update_policies /
commit_package / run_replay — a design counterfactual_replay.py has never had
(it defines none of them and imports no `db`). Every test was rewritten against
the real pipeline; substitutions are named where the original intent had no
direct counterpart.
"""

import json
import os
import sys

import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay as cfr
import fleet_control


class UpgradedModel:
    """The 'current' model: always routes to opus with high confidence."""

    model_id = "claude-opus-4"
    version = "4.0"

    def __init__(self, decision="claude-opus-4", confidence=0.95, raises=None):
        self._decision = decision
        self._confidence = confidence
        self._raises = raises
        self.calls = 0

    def evaluate(self, input_data, task_type):
        self.calls += 1
        if self._raises:
            raise self._raises
        return {"decision": self._decision, "confidence": self._confidence}


def _history():
    """A week of past routing decisions, as the replay window would see them."""
    return [
        {
            "task_id": "task-1", "type": "routing", "timestamp": "2026-08-18",
            "model": "claude-haiku", "model_version": "3.0",
            "input": {"kind": "build"},
            "output": {"route": "claude-haiku", "confidence": 0.60},
        },
        {
            "task_id": "task-2", "type": "routing", "timestamp": "2026-08-19",
            "model": "claude-sonnet", "model_version": "3.5",
            "input": {"kind": "review"},
            "output": {"route": "claude-sonnet", "confidence": 0.80},
        },
        {
            "task_id": "task-3", "type": "routing", "timestamp": "2026-08-20",
            "model": "claude-opus-4", "model_version": "4.0",
            "input": {"kind": "build"},
            "output": {"route": "claude-opus-4", "confidence": 0.95},
        },
    ]


@pytest.fixture(autouse=True)
def reset_counters():
    cfr.invalidate()
    yield
    cfr.invalidate()


class TestCounterfactualReplayE2E:
    """The replay pipeline, assembled from the module's real parts."""

    def test_e2e_window_selection_feeds_the_batch(self):
        """Filter a history down to the replay window, then replay all of it."""
        history = _history() + [
            {"task_id": "task-0", "type": "routing", "timestamp": "2026-07-01",
             "input": {"kind": "build"}},
            {"task_id": "task-9", "type": "build", "timestamp": "2026-08-19",
             "input": {"kind": "build"}},
        ]
        window = cfr.filter_decisions(
            history, task_type="routing", start_date="2026-08-18", end_date="2026-08-21")
        assert [d["task_id"] for d in window] == ["task-1", "task-2", "task-3"]

        model = UpgradedModel()
        results, summary = cfr.replay_batch_with_summary(window, model)

        assert model.calls == 3
        assert summary["total_replayed"] == 3
        assert summary["models_tested"] == ["claude-opus-4"]
        # task-1 and task-2 rerouted; task-3 already routed to opus.
        assert summary["policy_changes"] == 2
        assert [r["original_task_id"] for r in results] == ["task-1", "task-2", "task-3"]

    def test_e2e_divergences_repoint_the_route_table(self):
        """A detected divergence becomes a route update in the live table."""
        config = cfr.RouteConfig()
        config.set_route("routing", "claude-haiku", q_score=0.60)

        decision = _history()[0]
        replay = cfr.replay_decision(decision["task_id"], decision, UpgradedModel())
        change = cfr.detect_policy_change(
            decision["output"],
            {"route": replay["decision"], "confidence": replay["confidence"]},
        )
        assert change["changed"] is True
        assert change["reason"] == "confidence_improvement"

        update = cfr.update_route_policy("routing", config.get_route("routing"), change)
        assert update["prior_model"] == "claude-haiku"
        assert update["new_model"] == "claude-opus-4"

        config.apply_counterfactual_update("routing", update)
        assert config.get_route("routing")["model"] == "claude-opus-4"

    def test_e2e_stable_decision_produces_no_route_change(self):
        """A decision the new model reproduces leaves routing alone."""
        config = cfr.RouteConfig()
        config.set_route("routing", "claude-opus-4", q_score=0.95)

        decision = _history()[2]
        replay = cfr.replay_decision(decision["task_id"], decision, UpgradedModel())
        change = cfr.detect_policy_change(
            decision["output"],
            {"route": replay["decision"], "confidence": replay["confidence"]},
        )
        assert change["changed"] is False

        update = cfr.update_route_policy("routing", config.get_route("routing"), change)
        assert update["updated"] is False
        assert config.get_route("routing")["model"] == "claude-opus-4"

    def test_e2e_route_updates_are_persisted_as_an_artifact(self, tmp_path):
        """Route updates land in route_updates.json for the audit trail.

        Substitution: the original test expected a `commit_package()` JSON
        artifact writer. RouteStorage is the module's real artifact writer.
        """
        store = cfr.RouteStorage(str(tmp_path))
        update = cfr.update_route_policy(
            "routing", {"model": "claude-haiku"},
            {"changed": True, "new_route": "claude-opus-4", "confidence_delta": 0.35})
        store.persist_route_update(update)

        artifact = json.loads((tmp_path / "route_updates.json").read_text())
        assert artifact["routing"]["new_model"] == "claude-opus-4"
        assert artifact["routing"]["updated"] is True
        assert "T" in artifact["routing"]["timestamp"]
        assert store.get_route_update("routing") == update

    def test_e2e_replays_are_persisted_and_queryable(self, tmp_path):
        """Every replay row lands in the ledger and divergences are queryable."""
        storage = cfr.ReplayStorage(str(tmp_path))
        history = _history()
        results, _ = cfr.replay_batch_with_summary(history, UpgradedModel())

        by_task = {d["task_id"]: d for d in history}
        for result in results:
            result["policy_changed"] = cfr.has_policy_change(
                by_task[result["original_task_id"]], result)
            storage.save_replay(result)

        assert storage.count_replays() == 3
        diverged = {r["original_task_id"] for r in storage.query(policy_changed=True)}
        assert diverged == {"task-1", "task-2"}

    def test_e2e_policy_updates_reach_fleet_config(self, monkeypatch):
        """Diverged routes are pushed through the fleet_control gateway."""
        pushed = {}
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: pushed.__setitem__(k, v))

        history = _history()
        results, summary = cfr.replay_batch_with_summary(history, UpgradedModel())
        by_task = {d["task_id"]: d for d in history}

        updates = {}
        for result in results:
            if cfr.has_policy_change(by_task[result["original_task_id"]], result):
                kind = by_task[result["original_task_id"]]["input"]["kind"]
                updates[f"ORCH_RUNNER_ROUTE_{kind.upper()}"] = result["decision"]
        cfr.push_config_updates(updates)

        assert summary["policy_changes"] == 2
        assert pushed == {
            "ORCH_RUNNER_ROUTE_BUILD": "claude-opus-4",
            "ORCH_RUNNER_ROUTE_REVIEW": "claude-opus-4",
        }

    def test_e2e_secret_bearing_updates_never_leave_the_replay(self, monkeypatch):
        """The preservation rule holds on the assembled path, not just in unit tests."""
        pushed = []
        monkeypatch.setattr(fleet_control, "update_fleet_config",
                            lambda k, v: pushed.append(k))
        cfr.push_config_updates({
            "ORCH_RUNNER_ROUTE_BUILD": "claude-opus-4",
            "ORCH_RUNNER_POLICY_TOKEN": "should-never-be-pushed",
        })
        assert pushed == ["ORCH_RUNNER_ROUTE_BUILD"]

    def test_e2e_malformed_records_are_skipped_not_fatal(self):
        """A window containing junk still replays every usable record."""
        history = [
            _history()[0],
            {"task_id": "task-2"},          # nothing to replay
            None,                            # null record
            "not-a-decision",                # wrong type
            {"task_id": "task-4", "input": None},  # explicit null input
            _history()[1],
        ]
        results, summary = cfr.replay_batch_with_summary(history, UpgradedModel())
        assert [r["original_task_id"] for r in results] == ["task-1", "task-2"]
        assert summary["total_replayed"] == 2

    def test_e2e_model_outage_degrades_and_is_counted(self):
        """A model outage yields skipped replays and a non-zero error count."""
        history = _history()
        results = [
            cfr.replay_decision_safe(d["task_id"], d,
                                     UpgradedModel(raises=RuntimeError("provider down")))
            for d in history
        ]
        assert [r["status"] for r in results] == ["skipped"] * 3
        assert cfr.stats() == {"replayed": 0, "changed": 0, "errors": 3}

    def test_e2e_context_evolution_is_recorded_with_the_replay(self, tmp_path):
        """Replaying against evolved context records both generations."""
        storage = cfr.ReplayStorage(str(tmp_path))
        decision = {
            "task_id": "task-1",
            "model": "claude-haiku",
            "input": {"data": "week-old-snapshot", "version": 1},
        }
        new_context = {"data": "fresh-snapshot", "version": 2, "context_version": 2}

        result = cfr.replay_decision_with_context(
            "task-1", decision, UpgradedModel(), new_context)
        storage.save_replay(result)

        stored = storage.get_replays("task-1")[0]
        assert stored["context_version"] == 2
        assert stored["data_evolution"] == {
            "old": "week-old-snapshot", "new": "fresh-snapshot"}
        evolution = cfr.track_data_evolution(decision["input"], new_context)
        assert evolution["changes"] == ["context_version", "data"]

    def test_e2e_rerunning_the_window_is_idempotent(self, tmp_path):
        """Replaying the same window twice leaves one ledger row per task."""
        storage = cfr.ReplayStorage(str(tmp_path))
        config = cfr.RouteConfig()
        config.set_route("routing", "claude-haiku", q_score=0.60)

        for _ in range(2):
            results, _ = cfr.replay_batch_with_summary(_history(), UpgradedModel())
            for result in results:
                storage.save_replay(result)
            config.apply_counterfactual_update("routing", results[0])

        assert storage.count_replays() == 3
        assert storage.count_replays("task-1") == 1
        assert config.get_route("routing")["model"] == "claude-opus-4"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
