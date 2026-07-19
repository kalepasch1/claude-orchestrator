#!/usr/bin/env python3
"""
adaptive_test_prioritizer.py — AI-driven test prioritization and anomaly detection.

Provides risk-based test ordering that adapts to codebase changes:
- Prioritizes tests by historical failure rate, recency of code changes, and blast radius
- Detects anomalous test durations indicating performance regressions
- Dynamically adjusts test execution order to maximize defect-finding speed

Env vars:
    ORCH_TEST_PRIORITY_ENABLED     "true" to enable (default "true")
    ORCH_TEST_ANOMALY_THRESHOLD    z-score threshold for anomaly detection (default 2.0)
    ORCH_TEST_HISTORY_WINDOW       number of recent runs to consider (default 50)
"""
import math
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("adaptive_test_prioritizer")

ENABLED = os.environ.get("ORCH_TEST_PRIORITY_ENABLED", "true").lower() in ("1", "true", "yes")
ANOMALY_THRESHOLD = float(os.environ.get("ORCH_TEST_ANOMALY_THRESHOLD", "2.0"))
HISTORY_WINDOW = int(os.environ.get("ORCH_TEST_HISTORY_WINDOW", "50"))


@dataclass
class TestRecord:
    """A single test execution record."""
    test_name: str
    passed: bool
    duration_s: float
    timestamp: float = field(default_factory=time.time)
    changed_files: List[str] = field(default_factory=list)


@dataclass
class TestRiskProfile:
    """Risk assessment for a single test."""
    test_name: str
    failure_rate: float = 0.0       # 0.0 - 1.0
    avg_duration_s: float = 0.0
    last_failure_age_s: float = float('inf')
    files_at_risk: int = 0          # number of recently changed files this test covers
    priority_score: float = 0.0     # composite score, higher = run first
    is_anomalous: bool = False
    anomaly_reason: str = ""


@dataclass
class PrioritizationResult:
    """Result of test prioritization."""
    ordered_tests: List[str] = field(default_factory=list)
    profiles: Dict[str, TestRiskProfile] = field(default_factory=dict)
    anomalies: List[TestRiskProfile] = field(default_factory=list)
    total_tests: int = 0
    estimated_time_s: float = 0.0


class AdaptiveTestPrioritizer:
    """Risk-based test prioritizer with anomaly detection.

    Maintains a history of test runs and uses it to:
    1. Rank tests by likelihood of failure (failure rate + recency)
    2. Detect anomalous durations (potential perf regressions)
    3. Weight tests by blast radius (how many changed files they cover)
    """

    def __init__(self, history_window: int = None, anomaly_threshold: float = None):
        self.history_window = history_window or HISTORY_WINDOW
        self.anomaly_threshold = anomaly_threshold or ANOMALY_THRESHOLD
        self._history: Dict[str, List[TestRecord]] = {}  # test_name -> records
        self._file_test_map: Dict[str, List[str]] = {}   # file -> test_names

    def record(self, rec: TestRecord):
        """Record a test execution result."""
        if rec.test_name not in self._history:
            self._history[rec.test_name] = []
        records = self._history[rec.test_name]
        records.append(rec)
        # Trim to window
        if len(records) > self.history_window:
            self._history[rec.test_name] = records[-self.history_window:]
        # Update file→test mapping
        for f in rec.changed_files:
            if f not in self._file_test_map:
                self._file_test_map[f] = []
            if rec.test_name not in self._file_test_map[f]:
                self._file_test_map[f].append(rec.test_name)

    def record_batch(self, records: List[TestRecord]):
        """Record multiple test results."""
        for r in records:
            self.record(r)

    def _compute_profile(self, test_name: str,
                         changed_files: Optional[List[str]] = None) -> TestRiskProfile:
        """Compute risk profile for a single test."""
        profile = TestRiskProfile(test_name=test_name)
        records = self._history.get(test_name, [])
        if not records:
            return profile

        # Failure rate
        failures = sum(1 for r in records if not r.passed)
        profile.failure_rate = failures / len(records)

        # Average duration
        durations = [r.duration_s for r in records]
        profile.avg_duration_s = sum(durations) / len(durations)

        # Last failure recency
        failed_records = [r for r in records if not r.passed]
        if failed_records:
            profile.last_failure_age_s = time.time() - max(r.timestamp for r in failed_records)

        # Blast radius: count changed files this test covers
        if changed_files:
            for f in changed_files:
                if test_name in self._file_test_map.get(f, []):
                    profile.files_at_risk += 1

        # Anomaly detection on duration (z-score)
        if len(durations) >= 5:
            mean = sum(durations) / len(durations)
            variance = sum((d - mean) ** 2 for d in durations) / len(durations)
            std = math.sqrt(variance) if variance > 0 else 0
            if std > 0:
                latest = durations[-1]
                z = (latest - mean) / std
                if abs(z) > self.anomaly_threshold:
                    profile.is_anomalous = True
                    profile.anomaly_reason = (
                        f"duration {latest:.1f}s vs avg {mean:.1f}s (z={z:.1f})"
                    )

        # Composite priority score
        # Higher = should run first
        recency_bonus = 0.0
        if profile.last_failure_age_s < 86400:  # failed in last 24h
            recency_bonus = 3.0
        elif profile.last_failure_age_s < 604800:  # failed in last week
            recency_bonus = 1.0

        profile.priority_score = (
            profile.failure_rate * 5.0
            + recency_bonus
            + profile.files_at_risk * 2.0
            + (1.0 if profile.is_anomalous else 0.0)
        )

        return profile

    def prioritize(self, test_names: List[str],
                   changed_files: Optional[List[str]] = None) -> PrioritizationResult:
        """Prioritize tests by risk score. Returns ordered list with profiles."""
        result = PrioritizationResult(total_tests=len(test_names))

        for name in test_names:
            profile = self._compute_profile(name, changed_files)
            result.profiles[name] = profile
            if profile.is_anomalous:
                result.anomalies.append(profile)
            result.estimated_time_s += profile.avg_duration_s

        # Sort by priority descending (highest risk first)
        sorted_profiles = sorted(
            result.profiles.values(),
            key=lambda p: p.priority_score,
            reverse=True,
        )
        result.ordered_tests = [p.test_name for p in sorted_profiles]
        return result

    def stats(self) -> Dict:
        """Return prioritizer statistics."""
        return {
            "tests_tracked": len(self._history),
            "total_records": sum(len(r) for r in self._history.values()),
            "files_mapped": len(self._file_test_map),
            "history_window": self.history_window,
        }

    def clear(self):
        """Reset all history."""
        self._history.clear()
        self._file_test_map.clear()
