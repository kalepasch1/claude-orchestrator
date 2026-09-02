#!/usr/bin/env python3
"""Persistence, counter and thread-safety tests for counterfactual_replay.

SUITE OWNERSHIP: this file owns
    * ReplayStorage (the sqlite replay ledger)
    * RouteStorage (the JSON route-update ledger)
    * the module counters — stats() / invalidate()
    * thread-safety of the shared state
Per-decision units are owned by runner/test_counterfactual_replay_comprehensive.py,
the spec contract by runner/test_counterfactual_replay_spec.py, the batch and
route-table surface by runner/test_counterfactual_replay_impl.py, and the
assembled flow by tests/test_counterfactual_replay_e2e.py.

This file previously tested store_decision / replay_past_decisions /
add_divergence / get_divergence_log / a `_replay` singleton with `_hash_text`,
none of which exist in counterfactual_replay.py and none of which any caller in
the fleet references. Each test was retargeted onto the real persistence and
counter API; where a fictional concept had a real counterpart (a stored decision
-> a saved replay row, a divergence log -> the policy_changed query) the
substitution is named in the class docstring.
"""

import json
import os
import sys
import threading

import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay


@pytest.fixture(autouse=True)
def reset_replay():
    """Counters and the storage singleton are module-global; reset around tests."""
    counterfactual_replay.invalidate()
    yield
    counterfactual_replay.invalidate()


@pytest.fixture
def storage(tmp_path):
    return counterfactual_replay.ReplayStorage(str(tmp_path))


class FakeModel:
    def __init__(self, model_id="opus", version="2.0", decision="opus",
                 confidence=0.9, raises=None):
        self.model_id = model_id
        self.version = version
        self._decision = decision
        self._confidence = confidence
        self._raises = raises

    def evaluate(self, input_data, task_type):
        if self._raises:
            raise self._raises
        return {"decision": self._decision, "confidence": self._confidence}


def _replay_row(task_id, model="opus", decision="route_a", policy_changed=False):
    return {
        "task_id": task_id,
        "model": model,
        "decision": decision,
        "policy_changed": policy_changed,
        "timestamp": "2026-08-18T10:00:00Z",
    }


class TestSaveReplay:
    """ReplayStorage.save_replay() — the replay ledger.

    Substitution: the original TestStoreDecision drove a store_decision()
    function that never existed. save_replay() is the module's real "record this
    decision" entry point and is asserted in its place.
    """

    def test_save_replay_persists_a_row(self, storage):
        storage.save_replay(_replay_row("task-1"))
        assert storage.count_replays() == 1

    def test_saved_row_is_retrievable_in_full(self, storage):
        row = _replay_row("task-1")
        row["metadata"] = {"source": "test", "version": "1.0"}
        storage.save_replay(row)
        assert storage.get_replays("task-1")[0]["metadata"] == {
            "source": "test", "version": "1.0"}

    def test_decision_type_round_trips(self, storage):
        storage.save_replay(_replay_row("task-1", decision="classification"))
        assert storage.get_replays("task-1")[0]["decision"] == "classification"

    def test_row_without_task_id_is_not_saved(self, storage):
        """A row with no task id cannot be reconciled, so it is dropped."""
        storage.save_replay({"model": "opus", "decision": "route_a"})
        assert storage.count_replays() == 0

    def test_row_with_none_task_id_is_not_saved(self, storage):
        storage.save_replay(_replay_row(None))
        assert storage.count_replays() == 0

    def test_save_is_idempotent_per_task(self, storage):
        """Re-saving a task replaces its row rather than appending a duplicate."""
        storage.save_replay(_replay_row("task-1", decision="first"))
        storage.save_replay(_replay_row("task-1", decision="second"))
        assert storage.count_replays("task-1") == 1
        assert storage.get_replays("task-1")[0]["decision"] == "second"

    def test_empty_decision_is_saved(self, storage):
        """An empty decision is a recorded outcome, not a missing row."""
        storage.save_replay(_replay_row("task-1", decision=""))
        assert storage.count_replays("task-1") == 1

    def test_many_tasks_each_get_a_row(self, storage):
        for i in range(5):
            storage.save_replay(_replay_row(f"task-{i}"))
        assert storage.count_replays() == 5

    def test_non_serialisable_values_are_stringified(self, storage):
        """default=str keeps an exotic value from losing the whole row."""
        row = _replay_row("task-1")
        row["model_handle"] = object()
        storage.save_replay(row)
        assert storage.count_replays("task-1") == 1
        assert isinstance(storage.get_replays("task-1")[0]["model_handle"], str)

    def test_numeric_task_id_is_accepted(self, storage):
        """Task ids are stored as text; a numeric id reads back as its digits."""
        storage.save_replay(_replay_row(123))
        assert storage.count_replays() == 1
        assert storage.get_replays("123")[0]["task_id"] == 123


class TestRetrieveReplays:
    """ReplayStorage.get_replays() / count_replays().

    Substitution: the original TestReplayPastDecisions drove
    replay_past_decisions(); reading back a stored replay is the real behaviour
    that intent maps onto.
    """

    def test_get_replays_for_unknown_task_is_empty(self, storage):
        assert storage.get_replays("nope") == []

    def test_get_replays_returns_only_that_task(self, storage):
        storage.save_replay(_replay_row("task-1"))
        storage.save_replay(_replay_row("task-2"))
        rows = storage.get_replays("task-1")
        assert [r["task_id"] for r in rows] == ["task-1"]

    def test_count_replays_scopes_to_a_task(self, storage):
        storage.save_replay(_replay_row("task-1"))
        storage.save_replay(_replay_row("task-2"))
        assert storage.count_replays("task-1") == 1
        assert storage.count_replays() == 2

    def test_count_on_empty_ledger_is_zero(self, storage):
        assert storage.count_replays() == 0

    def test_ledger_survives_reopen(self, tmp_path):
        """The ledger is on disk: a fresh handle sees earlier rows."""
        first = counterfactual_replay.ReplayStorage(str(tmp_path))
        first.save_replay(_replay_row("task-1"))
        second = counterfactual_replay.ReplayStorage(str(tmp_path))
        assert second.count_replays("task-1") == 1

    def test_ledger_file_is_created_under_base_dir(self, tmp_path):
        counterfactual_replay.ReplayStorage(str(tmp_path))
        assert (tmp_path / "replay_results.db").exists()


class TestDivergenceQuery:
    """ReplayStorage.query() — the divergence log.

    Substitution: add_divergence()/get_divergence_log() never existed. A replay
    row carries policy_changed, and query(policy_changed=True) is the real
    divergence log.
    """

    def test_query_policy_changed_returns_divergences(self, storage):
        storage.save_replay(_replay_row("task-1", policy_changed=True))
        storage.save_replay(_replay_row("task-2", policy_changed=False))
        diverged = storage.query(policy_changed=True)
        assert [r["task_id"] for r in diverged] == ["task-1"]

    def test_query_policy_unchanged_returns_the_rest(self, storage):
        storage.save_replay(_replay_row("task-1", policy_changed=True))
        storage.save_replay(_replay_row("task-2", policy_changed=False))
        assert [r["task_id"] for r in storage.query(policy_changed=False)] == ["task-2"]

    def test_query_by_model(self, storage):
        storage.save_replay(_replay_row("task-1", model="opus"))
        storage.save_replay(_replay_row("task-2", model="haiku"))
        assert [r["task_id"] for r in storage.query(model="opus")] == ["task-1"]

    def test_query_combines_filters(self, storage):
        storage.save_replay(_replay_row("task-1", model="opus", policy_changed=True))
        storage.save_replay(_replay_row("task-2", model="opus", policy_changed=False))
        rows = storage.query(model="opus", policy_changed=True)
        assert [r["task_id"] for r in rows] == ["task-1"]

    def test_unfiltered_query_returns_everything(self, storage):
        for i in range(3):
            storage.save_replay(_replay_row(f"task-{i}"))
        assert len(storage.query()) == 3

    def test_divergence_log_is_empty_initially(self, storage):
        assert storage.query(policy_changed=True) == []


class TestRouteStorage:
    """RouteStorage — the persisted route-update ledger."""

    def test_persist_then_read_back(self, tmp_path):
        store = counterfactual_replay.RouteStorage(str(tmp_path))
        update = {"operation": "build", "new_model": "opus", "updated": True}
        store.persist_route_update(update)
        assert store.get_route_update("build") == update

    def test_unknown_operation_returns_none(self, tmp_path):
        assert counterfactual_replay.RouteStorage(str(tmp_path)).get_route_update("x") is None

    def test_update_without_operation_is_filed_under_unknown(self, tmp_path):
        store = counterfactual_replay.RouteStorage(str(tmp_path))
        store.persist_route_update({"new_model": "opus"})
        assert store.get_route_update("unknown") == {"new_model": "opus"}

    def test_latest_update_per_operation_wins(self, tmp_path):
        store = counterfactual_replay.RouteStorage(str(tmp_path))
        store.persist_route_update({"operation": "build", "new_model": "haiku"})
        store.persist_route_update({"operation": "build", "new_model": "opus"})
        assert store.get_route_update("build")["new_model"] == "opus"

    def test_updates_survive_reopen(self, tmp_path):
        counterfactual_replay.RouteStorage(str(tmp_path)).persist_route_update(
            {"operation": "build", "new_model": "opus"})
        reopened = counterfactual_replay.RouteStorage(str(tmp_path))
        assert reopened.get_route_update("build")["new_model"] == "opus"

    def test_corrupted_ledger_reads_as_empty(self, tmp_path):
        """A truncated JSON ledger degrades to 'no updates', not a crash."""
        store = counterfactual_replay.RouteStorage(str(tmp_path))
        (tmp_path / "route_updates.json").write_text("{not json")
        assert store.get_route_update("build") is None

    def test_persist_over_corrupted_ledger_recovers(self, tmp_path):
        store = counterfactual_replay.RouteStorage(str(tmp_path))
        (tmp_path / "route_updates.json").write_text("{not json")
        store.persist_route_update({"operation": "build", "new_model": "opus"})
        assert json.loads((tmp_path / "route_updates.json").read_text())["build"][
            "new_model"] == "opus"


class TestStats:
    """stats() — the module counters.

    Substitution: the original tests expected a "stored" counter. The module
    counts replayed / changed / errors; those are asserted instead.
    """

    def test_initial_state_is_zero(self):
        assert counterfactual_replay.stats() == {
            "replayed": 0, "changed": 0, "errors": 0}

    def test_replay_increments_replayed(self):
        counterfactual_replay.replay_decision("t1", {"input": {"q": 1}}, FakeModel())
        assert counterfactual_replay.stats()["replayed"] == 1

    def test_skipped_decision_is_not_counted_as_replayed(self):
        """A decision with nothing to replay is a skip, not a replay."""
        counterfactual_replay.replay_decision("t1", {}, FakeModel())
        assert counterfactual_replay.stats()["replayed"] == 0

    def test_model_failure_increments_errors(self):
        counterfactual_replay.replay_decision(
            "t1", {"input": {"q": 1}}, FakeModel(raises=RuntimeError("down")))
        stats = counterfactual_replay.stats()
        assert stats["errors"] == 1
        assert stats["replayed"] == 0

    def test_batch_summary_increments_changed(self):
        decisions = [{"task_id": "t1", "input": {"q": 1}, "output": {"route": "haiku"}}]
        counterfactual_replay.replay_batch_with_summary(
            decisions, FakeModel(decision="opus"))
        assert counterfactual_replay.stats()["changed"] == 1

    def test_stats_returns_a_copy(self):
        counterfactual_replay.replay_decision("t1", {"input": {"q": 1}}, FakeModel())
        snapshot = counterfactual_replay.stats()
        snapshot["replayed"] = 999
        assert counterfactual_replay.stats()["replayed"] == 1


class TestInvalidate:
    """invalidate() — clear counters and the storage singleton."""

    def test_invalidate_clears_counters(self):
        counterfactual_replay.replay_decision("t1", {"input": {"q": 1}}, FakeModel())
        counterfactual_replay.invalidate()
        assert counterfactual_replay.stats()["replayed"] == 0

    def test_invalidate_clears_errors(self):
        counterfactual_replay.replay_decision(
            "t1", {"input": {"q": 1}}, FakeModel(raises=ValueError("x")))
        counterfactual_replay.invalidate()
        assert counterfactual_replay.stats()["errors"] == 0

    def test_invalidate_is_repeatable(self):
        counterfactual_replay.replay_decision("t1", {"input": {"q": 1}}, FakeModel())
        counterfactual_replay.invalidate()
        counterfactual_replay.invalidate()
        assert counterfactual_replay.stats() == {
            "replayed": 0, "changed": 0, "errors": 0}

    def test_invalidate_does_not_erase_persisted_replays(self, storage):
        """Counters are in-memory; the ledger on disk is not touched."""
        storage.save_replay(_replay_row("task-1"))
        counterfactual_replay.invalidate()
        assert storage.count_replays("task-1") == 1


class TestThreadSafety:
    """Shared module state is guarded by locks."""

    def test_concurrent_replays_count_exactly_once_each(self):
        def replay_many(worker):
            for i in range(10):
                counterfactual_replay.replay_decision(
                    f"t-{worker}-{i}", {"input": {"q": i}}, FakeModel())

        threads = [threading.Thread(target=replay_many, args=(w,)) for w in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert counterfactual_replay.stats()["replayed"] == 30

    def test_concurrent_stats_reads_are_consistent(self):
        counterfactual_replay.replay_decision("t1", {"input": {"q": 1}}, FakeModel())
        results = []

        def read_stats():
            results.append(counterfactual_replay.stats())

        threads = [threading.Thread(target=read_stats) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r["replayed"] == 1 for r in results)

    def test_concurrent_saves_land_in_the_ledger(self, storage):
        def save_many(worker):
            for i in range(5):
                storage.save_replay(_replay_row(f"task-{worker}-{i}"))

        threads = [threading.Thread(target=save_many, args=(w,)) for w in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert storage.count_replays() == 15

    def test_concurrent_route_updates_do_not_lose_operations(self):
        config = counterfactual_replay.RouteConfig()

        def update_many(worker):
            for i in range(5):
                config.update_route(f"op-{worker}-{i}", "opus", q_score=0.5)

        threads = [threading.Thread(target=update_many, args=(w,)) for w in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(config._routes) == 15


class TestEdgeCases:
    """Edge cases in the persistence layer."""

    def test_very_long_payload_round_trips(self, storage):
        row = _replay_row("task-1")
        row["input"] = "x" * 10000
        storage.save_replay(row)
        assert len(storage.get_replays("task-1")[0]["input"]) == 10000

    def test_special_characters_round_trip(self, storage):
        row = _replay_row("task-1")
        row["input"] = "special chars: \n\t\r"
        row["output"] = "unicode: 你好世界"
        storage.save_replay(row)
        stored = storage.get_replays("task-1")[0]
        assert stored["input"] == "special chars: \n\t\r"
        assert stored["output"] == "unicode: 你好世界"

    def test_row_missing_optional_columns_is_still_saved(self, storage):
        storage.save_replay({"task_id": "task-1"})
        assert storage.get_replays("task-1") == [{"task_id": "task-1"}]

    def test_missing_policy_changed_defaults_to_not_diverged(self, storage):
        storage.save_replay({"task_id": "task-1"})
        assert [r["task_id"] for r in storage.query(policy_changed=False)] == ["task-1"]

    def test_corrupted_ledger_file_fails_soft(self, tmp_path):
        """A garbage .db file yields empty reads instead of raising."""
        store = counterfactual_replay.ReplayStorage(str(tmp_path))
        (tmp_path / "replay_results.db").write_bytes(b"not a database")
        assert store.count_replays() == 0
        assert store.get_replays("task-1") == []
        assert store.query() == []

    def test_save_into_corrupted_ledger_fails_soft(self, tmp_path):
        store = counterfactual_replay.ReplayStorage(str(tmp_path))
        (tmp_path / "replay_results.db").write_bytes(b"not a database")
        store.save_replay(_replay_row("task-1"))

    def test_nested_base_dir_is_created(self, tmp_path):
        store = counterfactual_replay.ReplayStorage(str(tmp_path / "a" / "b"))
        store.save_replay(_replay_row("task-1"))
        assert (tmp_path / "a" / "b" / "replay_results.db").exists()

    def test_two_ledgers_are_isolated(self, tmp_path):
        first = counterfactual_replay.ReplayStorage(str(tmp_path / "one"))
        second = counterfactual_replay.ReplayStorage(str(tmp_path / "two"))
        first.save_replay(_replay_row("task-1"))
        assert second.count_replays() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
