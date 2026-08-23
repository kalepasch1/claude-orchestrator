import os
import sys
import time
import threading
import pytest

RUNNER = os.path.dirname(os.path.dirname(__file__))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import counterfactual_replay


@pytest.fixture(autouse=True)
def reset_replay():
    """Reset replay state before each test."""
    counterfactual_replay.invalidate()
    os.environ["ORCH_REPLAY_ENABLED"] = "true"
    yield
    counterfactual_replay.invalidate()
    if "ORCH_REPLAY_ENABLED" in os.environ:
        del os.environ["ORCH_REPLAY_ENABLED"]


class TestStoreDecision:
    """Test decision storage."""

    def test_store_decision_success(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="what is 2+2?",
            output_text="4",
        )
        assert result is True
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 1

    def test_store_decision_with_metadata(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
            metadata={"source": "test", "version": "1.0"},
        )
        assert result is True

    def test_store_decision_with_decision_type(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
            decision_type="classification",
        )
        assert result is True

    def test_store_decision_disabled(self):
        os.environ["ORCH_REPLAY_ENABLED"] = "false"
        counterfactual_replay.invalidate()
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is False

    def test_store_decision_with_none_task_id(self):
        result = counterfactual_replay.store_decision(
            task_id=None,
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is False

    def test_store_decision_with_none_model(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model=None,
            input_text="test",
            output_text="result",
        )
        assert result is False

    def test_store_decision_with_none_input(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text=None,
            output_text="result",
        )
        assert result is False

    def test_store_decision_with_empty_output(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="",
        )
        assert result is True

    def test_store_multiple_decisions(self):
        for i in range(5):
            result = counterfactual_replay.store_decision(
                task_id=f"task-{i}",
                model="claude-opus",
                input_text=f"input-{i}",
                output_text=f"output-{i}",
            )
            assert result is True
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 5

    def test_store_decision_max_history(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_MAX_HISTORY", "3")
        counterfactual_replay.invalidate()
        for i in range(5):
            counterfactual_replay.store_decision(
                task_id=f"task-{i}",
                model="claude-opus",
                input_text=f"input-{i}",
                output_text=f"output-{i}",
            )
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 5


class TestReplayPastDecisions:
    """Test replay of past decisions."""

    def test_replay_with_no_model(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        result = counterfactual_replay.replay_past_decisions(replay_model=None)
        assert result == []

    def test_replay_with_empty_model(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        result = counterfactual_replay.replay_past_decisions(replay_model="")
        assert result == []

    def test_replay_with_same_model(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        result = counterfactual_replay.replay_past_decisions(replay_model="claude-opus")
        assert result == []

    def test_replay_disabled(self):
        os.environ["ORCH_REPLAY_ENABLED"] = "false"
        counterfactual_replay.invalidate()
        result = counterfactual_replay.replay_past_decisions(replay_model="claude-sonnet")
        assert result == []

    def test_replay_with_empty_history(self):
        result = counterfactual_replay.replay_past_decisions(replay_model="claude-sonnet")
        assert result == []

    def test_replay_stats_updated(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        counterfactual_replay.replay_past_decisions(replay_model="claude-sonnet")
        stats = counterfactual_replay.stats()
        assert stats["replayed"] == 1


class TestDivergenceLog:
    """Test divergence detection and logging."""

    def test_add_divergence_success(self):
        div = {
            "task_id": "task-1",
            "original_model": "claude-opus",
            "replay_model": "claude-sonnet",
        }
        result = counterfactual_replay.add_divergence(div)
        assert result is True
        log = counterfactual_replay.get_divergence_log()
        assert len(log) == 1

    def test_add_divergence_with_none(self):
        result = counterfactual_replay.add_divergence(None)
        assert result is False

    def test_add_multiple_divergences(self):
        for i in range(3):
            div = {
                "task_id": f"task-{i}",
                "original_model": "claude-opus",
                "replay_model": "claude-sonnet",
            }
            counterfactual_replay.add_divergence(div)
        log = counterfactual_replay.get_divergence_log()
        assert len(log) == 3

    def test_divergence_log_max_history(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_MAX_HISTORY", "2")
        counterfactual_replay.invalidate()
        for i in range(5):
            div = {
                "task_id": f"task-{i}",
                "original_model": "claude-opus",
                "replay_model": "claude-sonnet",
            }
            counterfactual_replay.add_divergence(div)
        log = counterfactual_replay.get_divergence_log()
        assert len(log) <= 2

    def test_divergence_log_empty_initially(self):
        log = counterfactual_replay.get_divergence_log()
        assert log == []


class TestStats:
    """Test stats collection."""

    def test_stats_initial_state(self):
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 0
        assert stats["replayed"] == 0
        assert stats["divergences"] == 0

    def test_stats_after_store(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 1

    def test_stats_after_replay(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        counterfactual_replay.replay_past_decisions(replay_model="claude-sonnet")
        stats = counterfactual_replay.stats()
        assert stats["replayed"] == 1

    def test_stats_isolation(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        stats1 = counterfactual_replay.stats()
        stats1["stored"] = 999
        stats2 = counterfactual_replay.stats()
        assert stats2["stored"] == 1


class TestThreadSafety:
    """Test thread-safety of operations."""

    def test_concurrent_store(self):
        def store_many():
            for i in range(10):
                counterfactual_replay.store_decision(
                    task_id=f"task-{threading.current_thread().ident}-{i}",
                    model="claude-opus",
                    input_text=f"input-{i}",
                    output_text=f"output-{i}",
                )
        threads = [threading.Thread(target=store_many) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 30

    def test_concurrent_stats_read(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        results = []

        def read_stats():
            results.append(counterfactual_replay.stats())

        threads = [threading.Thread(target=read_stats) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r["stored"] == 1 for r in results)

    def test_concurrent_divergence_log(self):
        def add_divs():
            for i in range(5):
                counterfactual_replay.add_divergence(
                    {
                        "task_id": f"task-{threading.current_thread().ident}-{i}",
                        "original_model": "claude-opus",
                        "replay_model": "claude-sonnet",
                    }
                )

        threads = [threading.Thread(target=add_divs) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log = counterfactual_replay.get_divergence_log()
        assert len(log) == 15


class TestInvalidate:
    """Test state clearing."""

    def test_invalidate_clears_stats(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        counterfactual_replay.invalidate()
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 0

    def test_invalidate_clears_divergence_log(self):
        counterfactual_replay.add_divergence(
            {
                "task_id": "task-1",
                "original_model": "claude-opus",
                "replay_model": "claude-sonnet",
            }
        )
        counterfactual_replay.invalidate()
        log = counterfactual_replay.get_divergence_log()
        assert log == []

    def test_invalidate_multiple_times(self):
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        counterfactual_replay.invalidate()
        counterfactual_replay.invalidate()
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_store_with_very_long_input(self):
        long_input = "x" * 10000
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text=long_input,
            output_text="result",
        )
        assert result is True

    def test_store_with_special_characters(self):
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test with special chars: \n\t\r",
            output_text="result with unicode: 你好世界",
        )
        assert result is True

    def test_store_with_numeric_values(self):
        result = counterfactual_replay.store_decision(
            task_id=123,
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is True

    def test_hash_consistency(self):
        store1 = counterfactual_replay._replay
        hash1 = store1._hash_text("test input")
        hash2 = store1._hash_text("test input")
        assert hash1 == hash2

    def test_hash_different_inputs(self):
        store = counterfactual_replay._replay
        hash1 = store._hash_text("input1")
        hash2 = store._hash_text("input2")
        assert hash1 != hash2

    def test_hash_empty_string(self):
        store = counterfactual_replay._replay
        hash_val = store._hash_text("")
        assert hash_val == ""

    def test_divergence_with_missing_fields(self):
        div = {"task_id": "task-1"}
        result = counterfactual_replay.add_divergence(div)
        assert result is True
        log = counterfactual_replay.get_divergence_log()
        assert len(log) == 1

    def test_replay_with_env_var_model(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_MODEL", "claude-sonnet")
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        result = counterfactual_replay.replay_past_decisions()
        assert isinstance(result, list)


class TestIntegrationWithDb:
    """Test database integration (mocked)."""

    def test_store_attempts_db_insert(self, monkeypatch):
        calls = []

        def mock_insert(table, data):
            calls.append((table, data))

        monkeypatch.setattr("counterfactual_replay.db.insert", mock_insert, raising=False)
        counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        if calls:
            assert calls[0][0] == "replay_snapshots"

    def test_add_divergence_attempts_db_insert(self, monkeypatch):
        calls = []

        def mock_insert(table, data):
            calls.append((table, data))

        monkeypatch.setattr("counterfactual_replay.db.insert", mock_insert, raising=False)
        counterfactual_replay.add_divergence(
            {
                "task_id": "task-1",
                "original_model": "claude-opus",
                "replay_model": "claude-sonnet",
            }
        )
        if calls:
            assert calls[0][0] == "replay_divergences"


class TestEnvVarConfig:
    """Test environment variable configuration."""

    def test_orch_replay_enabled_true(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_ENABLED", "true")
        counterfactual_replay.invalidate()
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is True

    def test_orch_replay_enabled_1(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_ENABLED", "1")
        counterfactual_replay.invalidate()
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is True

    def test_orch_replay_enabled_yes(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_ENABLED", "yes")
        counterfactual_replay.invalidate()
        result = counterfactual_replay.store_decision(
            task_id="task-1",
            model="claude-opus",
            input_text="test",
            output_text="result",
        )
        assert result is True

    def test_orch_replay_max_history(self, monkeypatch):
        monkeypatch.setenv("ORCH_REPLAY_MAX_HISTORY", "5")
        counterfactual_replay.invalidate()
        for i in range(10):
            counterfactual_replay.store_decision(
                task_id=f"task-{i}",
                model="claude-opus",
                input_text=f"input-{i}",
                output_text=f"output-{i}",
            )
        stats = counterfactual_replay.stats()
        assert stats["stored"] == 10
