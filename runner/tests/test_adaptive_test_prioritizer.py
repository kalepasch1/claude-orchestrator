"""Tests for adaptive_test_prioritizer — risk-based test ordering."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from adaptive_test_prioritizer import (
    AdaptiveTestPrioritizer, TestRecord, TestRiskProfile, PrioritizationResult,
)


@pytest.fixture
def prioritizer():
    return AdaptiveTestPrioritizer(history_window=20, anomaly_threshold=2.0)


def _make_record(name, passed=True, duration=1.0, age=0, files=None):
    return TestRecord(
        test_name=name, passed=passed, duration_s=duration,
        timestamp=time.time() - age, changed_files=files or [],
    )


class TestTestRecord:
    def test_defaults(self):
        r = TestRecord(test_name="test_foo", passed=True, duration_s=1.5)
        assert r.test_name == "test_foo"
        assert r.timestamp > 0
        assert r.changed_files == []


class TestTestRiskProfile:
    def test_defaults(self):
        p = TestRiskProfile(test_name="test_bar")
        assert p.failure_rate == 0.0
        assert p.is_anomalous is False
        assert p.priority_score == 0.0


class TestAdaptiveTestPrioritizer:
    def test_empty_prioritize(self, prioritizer):
        result = prioritizer.prioritize(["test_a", "test_b"])
        assert result.total_tests == 2
        assert len(result.ordered_tests) == 2

    def test_failure_rate_increases_priority(self, prioritizer):
        """Tests with higher failure rates should be prioritized first."""
        # test_flaky fails 80%, test_stable never fails
        for _ in range(10):
            prioritizer.record(_make_record("test_flaky", passed=False))
            prioritizer.record(_make_record("test_stable", passed=True))
        # Add 2 passing for flaky to make rate 80%
        for _ in range(2):
            prioritizer.record(_make_record("test_flaky", passed=True))

        result = prioritizer.prioritize(["test_flaky", "test_stable"])
        assert result.ordered_tests[0] == "test_flaky"
        assert result.profiles["test_flaky"].failure_rate > 0.5
        assert result.profiles["test_stable"].failure_rate == 0.0

    def test_recent_failure_boosts_priority(self, prioritizer):
        """Tests that failed recently get a recency bonus."""
        # test_recent_fail: failed just now
        prioritizer.record(_make_record("test_recent_fail", passed=False, age=0))
        # test_old_fail: failed a month ago
        prioritizer.record(_make_record("test_old_fail", passed=False, age=2592000))

        result = prioritizer.prioritize(["test_recent_fail", "test_old_fail"])
        assert (result.profiles["test_recent_fail"].priority_score >
                result.profiles["test_old_fail"].priority_score)

    def test_anomaly_detection(self, prioritizer):
        """Detects anomalous test durations."""
        # Record 10 runs at ~1.0s, then one at 10.0s
        for _ in range(10):
            prioritizer.record(_make_record("test_perf", duration=1.0))
        prioritizer.record(_make_record("test_perf", duration=10.0))

        result = prioritizer.prioritize(["test_perf"])
        profile = result.profiles["test_perf"]
        assert profile.is_anomalous is True
        assert "z=" in profile.anomaly_reason
        assert len(result.anomalies) == 1

    def test_no_anomaly_normal_variation(self, prioritizer):
        """Normal variation should not trigger anomaly."""
        for i in range(10):
            prioritizer.record(_make_record("test_normal", duration=1.0 + i * 0.01))

        result = prioritizer.prioritize(["test_normal"])
        assert result.profiles["test_normal"].is_anomalous is False

    def test_blast_radius_scoring(self, prioritizer):
        """Tests covering changed files get higher priority."""
        prioritizer.record(_make_record("test_covers", files=["src/main.py"]))
        prioritizer.record(_make_record("test_unrelated", files=["src/other.py"]))

        result = prioritizer.prioritize(
            ["test_covers", "test_unrelated"],
            changed_files=["src/main.py"],
        )
        assert (result.profiles["test_covers"].files_at_risk >
                result.profiles["test_unrelated"].files_at_risk)

    def test_record_batch(self, prioritizer):
        records = [_make_record(f"test_{i}") for i in range(5)]
        prioritizer.record_batch(records)
        assert prioritizer.stats()["tests_tracked"] == 5

    def test_stats(self, prioritizer):
        prioritizer.record(_make_record("test_a"))
        s = prioritizer.stats()
        assert s["tests_tracked"] == 1
        assert s["total_records"] == 1

    def test_clear(self, prioritizer):
        prioritizer.record(_make_record("test_a"))
        prioritizer.clear()
        assert prioritizer.stats()["tests_tracked"] == 0

    def test_history_window_trimming(self):
        p = AdaptiveTestPrioritizer(history_window=5)
        for i in range(10):
            p.record(_make_record("test_a", duration=float(i)))
        assert len(p._history["test_a"]) == 5
