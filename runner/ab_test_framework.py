#!/usr/bin/env python3
"""
A/B testing framework: schema, deterministic variant assignment, traffic splitting, metric recording.

Design:
- Test schema: JSON-serializable config with name, variants (list), rollout_pct (0-100), metrics (list of metric names)
- Variant assignment: session-based hashing (sha256) ensures repeatable assignment per user across requests
- Traffic splitting: rollout_pct applied globally; same user always sees same variant
- Metric storage: in-memory dict with thread-safe recording (fail-soft on errors)
- Thread-safety: Lock-based protection of shared metrics state; minimal critical section
- Fail-soft: Errors during metric recording or assignment do not raise; return sensible defaults

Env vars (all optional, with defaults):
- AB_METRICS_TTL_SEC: max seconds to keep metrics before clearing (default: 3600)
- AB_MAX_METRICS_ENTRIES: max number of metric entries before eviction (default: 10000)
"""
import hashlib
import json
import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field


@dataclass
class TestSchema:
    """Test configuration schema."""
    name: str
    variants: List[str]  # e.g. ["control", "variant_a", "variant_b"]
    rollout_pct: int  # 0-100: what % of traffic gets variant assignment
    metrics: List[str]  # e.g. ["conversion", "click", "time_spent_ms"]

    def validate(self) -> bool:
        """Validate schema constraints."""
        if not self.name or not isinstance(self.name, str):
            return False
        if not self.variants or len(self.variants) < 2:
            return False
        if not (0 <= self.rollout_pct <= 100):
            return False
        if not self.metrics or not all(isinstance(m, str) for m in self.metrics):
            return False
        return True


@dataclass
class MetricRecord:
    """Single metric event."""
    test_name: str
    variant: str
    metric_name: str
    value: float
    timestamp: float = field(default_factory=time.time)


# Thread-safe singleton for metrics storage
_metrics_lock = threading.Lock()
_metrics_store: Dict[str, List[MetricRecord]] = {}
_metrics_last_gc = time.time()

# Configuration
import os
METRICS_TTL_SEC = int(os.environ.get("AB_METRICS_TTL_SEC", "3600"))
MAX_METRICS_ENTRIES = int(os.environ.get("AB_MAX_METRICS_ENTRIES", "10000"))


def _get_deterministic_variant(
    test_name: str, user_id: str, variants: List[str], rollout_pct: int
) -> Optional[str]:
    """
    Deterministically assign a variant to a user.

    Same user_id + test_name always produces same variant.
    Returns None if user not in rollout (rollout_pct < 100 and user is in the excluded %).
    """
    if not user_id or rollout_pct < 1:
        return None

    # Hash user_id + test_name to deterministic 0-99 value
    hash_input = f"{test_name}:{user_id}".encode()
    hash_val = int(hashlib.sha256(hash_input).hexdigest(), 16)
    user_bucket = (hash_val % 100)

    # Check if user is in rollout
    if user_bucket >= rollout_pct:
        return None

    # Assign variant deterministically based on hash
    variant_idx = (hash_val % len(variants))
    return variants[variant_idx]


def assign_variant(
    test_name: str, user_id: str, test_schema: TestSchema
) -> Optional[str]:
    """
    Assign a variant for the given test and user.

    Args:
        test_name: Name of the test (must match schema.name)
        user_id: Unique user identifier (ensures repeatable assignment)
        test_schema: TestSchema instance

    Returns:
        Variant name if assigned, None if user not in rollout
    """
    if not test_schema.validate():
        return None
    if not user_id:
        return None

    return _get_deterministic_variant(
        test_schema.name, user_id, test_schema.variants, test_schema.rollout_pct
    )


def record_metric(test_name: str, variant: str, metric_name: str, value: float) -> bool:
    """
    Record a metric for a test variant.

    Thread-safe. Fails gracefully (returns False) on error.
    Automatically evicts old entries when store exceeds size limit.

    Args:
        test_name: Name of test
        variant: Assigned variant
        metric_name: Metric name (should match schema.metrics)
        value: Numeric value (e.g. 1 for conversion, ms for latency)

    Returns:
        True if recorded, False on error
    """
    if not test_name or not variant or not metric_name or not isinstance(value, (int, float)):
        return False

    try:
        with _metrics_lock:
            key = f"{test_name}:{variant}:{metric_name}"
            if key not in _metrics_store:
                _metrics_store[key] = []

            record = MetricRecord(
                test_name=test_name,
                variant=variant,
                metric_name=metric_name,
                value=float(value)
            )
            _metrics_store[key].append(record)

            # Periodically garbage collect old entries and excess
            _try_gc()

            return True
    except Exception:
        return False


def _try_gc() -> None:
    """Garbage collect metrics: remove old entries and trim if over limit."""
    global _metrics_last_gc

    now = time.time()

    # GC every 60 seconds to avoid excessive work
    if now - _metrics_last_gc < 60:
        return

    _metrics_last_gc = now
    ttl_cutoff = now - METRICS_TTL_SEC

    # Remove old entries
    for key in list(_metrics_store.keys()):
        _metrics_store[key] = [
            r for r in _metrics_store[key] if r.timestamp > ttl_cutoff
        ]
        if not _metrics_store[key]:
            del _metrics_store[key]

    # If still over limit, evict oldest entries globally
    total_entries = sum(len(v) for v in _metrics_store.values())
    if total_entries > MAX_METRICS_ENTRIES:
        # Collect all records, sort by time, drop oldest
        all_records = []
        for key, records in _metrics_store.items():
            for r in records:
                all_records.append((key, r))

        all_records.sort(key=lambda x: x[1].timestamp)
        to_remove = total_entries - MAX_METRICS_ENTRIES + 1000  # keep some headroom

        removed_records = all_records[:to_remove]
        remaining_records = {r[0]: [] for r in all_records}

        for key, record in all_records[to_remove:]:
            remaining_records[key].append(record)

        _metrics_store.clear()
        for key, records in remaining_records.items():
            if records:
                _metrics_store[key] = records


def get_metrics(test_name: str, variant: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retrieve recorded metrics for a test (optionally filtered by variant).

    Returns dict mapping "metric_name" -> list of recorded values (as dicts).
    """
    result = {}
    try:
        with _metrics_lock:
            for key, records in _metrics_store.items():
                t, v, m = key.split(":", 2)
                if t != test_name:
                    continue
                if variant is not None and v != variant:
                    continue
                if m not in result:
                    result[m] = []
                result[m].extend([asdict(r) for r in records])
    except Exception:
        pass
    return result


def clear_metrics() -> None:
    """Clear all recorded metrics. Useful for testing."""
    with _metrics_lock:
        _metrics_store.clear()


def stats() -> Dict[str, Any]:
    """Return internal stats for monitoring and testing."""
    with _metrics_lock:
        total_keys = len(_metrics_store)
        total_records = sum(len(v) for v in _metrics_store.values())
        return {
            "total_metric_keys": total_keys,
            "total_records": total_records,
            "ttl_sec": METRICS_TTL_SEC,
            "max_entries": MAX_METRICS_ENTRIES,
        }


def invalidate_user_cache() -> None:
    """
    Placeholder for future session/user cache invalidation.
    (Currently assignment is stateless so no cache to invalidate.)
    """
    pass
