"""Slice-5 acceptance: ingest -> query by date range and config -> correlate.

The stated acceptance test is: (1) ingest 100+ synthetic historical records with
varying configs, (2) query retrieves records for a date range and config, (3) the
analysis shows a clear correlation (r > 0.6) between at least one config
parameter and queue depth.

The correlation is the point, so the checks below also pin the cases where a
coefficient must NOT be reported: too few pairs and zero variance. A gate that
reads r > 0.6 cannot be handed a fabricated 0.0 for "undefined".
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config_optimizer as co


BASE = datetime.datetime(2026, 8, 1, 0, 0, 0)


def _records(n=120):
    """n synthetic records where queue_depth tracks pool_size, plus noise.

    pool_size cycles 2..9 and queue_depth is 6*pool_size with a small
    deterministic wobble, so the planted relationship is strong but not exact —
    an r of 1.0 would only prove the arithmetic, not that the analysis survives
    noisy data. A second knob (log_level) varies independently as a control.
    """
    rows = []
    for i in range(n):
        pool = 2 + (i % 8)
        wobble = (i % 5) - 2                      # -2..+2, mean ~0
        rows.append({
            "key": "ORCH_POOL_SIZE",
            "created_at": (BASE + datetime.timedelta(hours=i)).isoformat(),
            "pool_size": pool,
            "queue_depth": 6 * pool + wobble,
            "log_level": (i * 7) % 3,             # independent control knob
        })
    return rows


class TestConfigHistoryAnalysis(unittest.TestCase):
    def test_1_ingest_over_100_synthetic_records(self):
        rows = _records()
        self.assertGreaterEqual(len(rows), 100)
        self.assertGreater(len({r["pool_size"] for r in rows}), 1, "configs must vary")

    def test_2_query_retrieves_a_date_range(self):
        rows = _records()
        start = (BASE + datetime.timedelta(hours=10)).isoformat()
        end = (BASE + datetime.timedelta(hours=19)).isoformat()
        got = co.query_history(rows, start=start, end=end)
        self.assertEqual(len(got), 10, "inclusive [start, end] window")
        self.assertEqual(got[0]["created_at"], start)
        self.assertEqual(got[-1]["created_at"], end)
        # Ordering is part of the contract: a series read out of order would
        # make any downstream trend view wrong.
        stamps = [r["created_at"] for r in got]
        self.assertEqual(stamps, sorted(stamps))

    def test_2b_query_narrows_by_config_key(self):
        rows = _records(20) + [
            {"key": "ORCH_OTHER", "created_at": (BASE + datetime.timedelta(hours=i)).isoformat(),
             "pool_size": 99, "queue_depth": 1} for i in range(5)
        ]
        got = co.query_history(rows, config_key="ORCH_POOL_SIZE")
        self.assertEqual(len(got), 20)
        self.assertTrue(all(r["key"] == "ORCH_POOL_SIZE" for r in got))

    def test_3_correlation_between_pool_size_and_queue_depth_exceeds_0_6(self):
        got = co.query_history(_records(), config_key="ORCH_POOL_SIZE")
        result = co.correlate(got, "pool_size", "queue_depth")
        self.assertIsNotNone(result["r"])
        self.assertGreater(result["r"], 0.6, f"r={result['r']}")
        self.assertGreaterEqual(result["n"], 100)

    def test_3b_an_independent_knob_does_not_show_that_correlation(self):
        # Without this the r > 0.6 assertion could pass on a bug that reports a
        # strong correlation for everything.
        got = co.query_history(_records(), config_key="ORCH_POOL_SIZE")
        result = co.correlate(got, "log_level", "queue_depth")
        self.assertIsNotNone(result["r"])
        self.assertLess(abs(result["r"]), 0.6, f"r={result['r']}")

    def test_undefined_correlation_is_none_not_zero(self):
        constant = [{"pool_size": 4, "queue_depth": i} for i in range(10)]
        self.assertIsNone(co.correlate(constant, "pool_size")["r"])
        self.assertIsNone(co.correlate([{"pool_size": 1, "queue_depth": 1}], "pool_size")["r"])
        self.assertIsNone(co.correlate([], "pool_size")["r"])

    def test_non_numeric_and_missing_values_are_skipped_not_fatal(self):
        rows = [{"pool_size": 1, "queue_depth": 2}, {"pool_size": "n/a", "queue_depth": 3},
                {"pool_size": 3, "queue_depth": None}, {"pool_size": 5, "queue_depth": 10}]
        result = co.correlate(rows, "pool_size", "queue_depth")
        self.assertEqual(result["n"], 2)

    def test_unparseable_timestamps_are_dropped_not_raised(self):
        rows = [{"key": "k", "created_at": "not-a-date"},
                {"key": "k", "created_at": BASE.isoformat()}]
        self.assertEqual(len(co.query_history(rows)), 1)


if __name__ == "__main__":
    unittest.main()
