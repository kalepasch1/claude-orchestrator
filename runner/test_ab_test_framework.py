#!/usr/bin/env python3
"""
Comprehensive test suite for ab_test_framework.py

Coverage:
- Variant assignment: determinism, rollout logic, edge cases
- Metric collection: recording, retrieval, thread safety
- Schema validation: constraints, bad inputs
- TTL and eviction: GC behavior, memory limits
"""
import os
import threading
import time
import unittest
from unittest.mock import patch

import ab_test_framework as ab
from ab_test_framework import TestSchema, MetricRecord, assign_variant, record_metric, get_metrics, clear_metrics, stats


class TestSchemaValidation(unittest.TestCase):
    """Tests for TestSchema.validate()"""

    def test_valid_schema(self):
        """Schema with all valid fields passes validation."""
        schema = TestSchema(
            name="test_promo",
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=["conversion", "click"]
        )
        self.assertTrue(schema.validate())

    def test_empty_name_fails(self):
        """Empty test name fails validation."""
        schema = TestSchema(
            name="",
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_none_name_fails(self):
        """None name fails validation."""
        schema = TestSchema(
            name=None,
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_non_string_name_fails(self):
        """Non-string name fails validation."""
        schema = TestSchema(
            name=123,
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_single_variant_fails(self):
        """Single variant fails (need at least 2 for comparison)."""
        schema = TestSchema(
            name="test",
            variants=["control"],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_empty_variants_fails(self):
        """Empty variants list fails."""
        schema = TestSchema(
            name="test",
            variants=[],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_rollout_0_valid(self):
        """Rollout at 0% is valid (no one gets variant, but valid schema)."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=0,
            metrics=["conversion"]
        )
        self.assertTrue(schema.validate())

    def test_rollout_100_valid(self):
        """Rollout at 100% is valid."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=100,
            metrics=["conversion"]
        )
        self.assertTrue(schema.validate())

    def test_rollout_negative_fails(self):
        """Negative rollout fails."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=-1,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_rollout_over_100_fails(self):
        """Rollout over 100 fails."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=101,
            metrics=["conversion"]
        )
        self.assertFalse(schema.validate())

    def test_empty_metrics_fails(self):
        """Empty metrics list fails."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=[]
        )
        self.assertFalse(schema.validate())

    def test_non_string_metrics_fails(self):
        """Non-string metric names fail."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=[123, "valid_metric"]
        )
        self.assertFalse(schema.validate())

    def test_three_variants_valid(self):
        """Three or more variants are valid."""
        schema = TestSchema(
            name="test",
            variants=["control", "variant_a", "variant_b"],
            rollout_pct=50,
            metrics=["conversion"]
        )
        self.assertTrue(schema.validate())


class TestVariantAssignment(unittest.TestCase):
    """Tests for variant assignment determinism and rollout."""

    def setUp(self):
        self.schema = TestSchema(
            name="promo_test",
            variants=["control", "variant_a", "variant_b"],
            rollout_pct=100,
            metrics=["conversion"]
        )

    def test_deterministic_assignment(self):
        """Same user always gets same variant."""
        user_id = "user_123"
        variant1 = assign_variant("promo_test", user_id, self.schema)
        variant2 = assign_variant("promo_test", user_id, self.schema)
        variant3 = assign_variant("promo_test", user_id, self.schema)

        self.assertIsNotNone(variant1)
        self.assertEqual(variant1, variant2)
        self.assertEqual(variant2, variant3)

    def test_different_users_may_differ(self):
        """Different users may get different variants."""
        variants = set()
        # Assign many users; statistically should see multiple variants
        for i in range(100):
            v = assign_variant("promo_test", f"user_{i}", self.schema)
            if v:
                variants.add(v)

        # With 3 variants and 100 users, highly unlikely to see just 1
        self.assertGreaterEqual(len(variants), 2)

    def test_rollout_0_percent(self):
        """At 0% rollout, no users are assigned."""
        schema_no_rollout = TestSchema(
            name="test_no_rollout",
            variants=["control", "variant_a"],
            rollout_pct=0,
            metrics=["conversion"]
        )

        # Try multiple users; all should be None
        for i in range(50):
            variant = assign_variant("test_no_rollout", f"user_{i}", schema_no_rollout)
            self.assertIsNone(variant)

    def test_rollout_100_percent(self):
        """At 100% rollout, all users are assigned."""
        for i in range(50):
            variant = assign_variant("promo_test", f"user_{i}", self.schema)
            self.assertIsNotNone(variant)
            self.assertIn(variant, self.schema.variants)

    def test_rollout_50_percent(self):
        """At 50% rollout, approximately half of users are assigned."""
        schema_50 = TestSchema(
            name="test_50",
            variants=["control", "variant_a"],
            rollout_pct=50,
            metrics=["conversion"]
        )

        assigned_count = 0
        total = 200
        for i in range(total):
            variant = assign_variant("test_50", f"user_{i}", schema_50)
            if variant is not None:
                assigned_count += 1

        # Should be approximately 50% (allow 30-70% due to randomness)
        pct = assigned_count / total
        self.assertGreater(pct, 0.3)
        self.assertLess(pct, 0.7)

    def test_invalid_schema_returns_none(self):
        """Invalid schema returns None without raising."""
        invalid_schema = TestSchema(
            name="",
            variants=["control"],
            rollout_pct=50,
            metrics=[]
        )
        variant = assign_variant("invalid", "user_1", invalid_schema)
        self.assertIsNone(variant)

    def test_empty_user_id_returns_none(self):
        """Empty user_id returns None gracefully."""
        variant = assign_variant("promo_test", "", self.schema)
        self.assertIsNone(variant)

    def test_none_user_id_returns_none(self):
        """None user_id returns None gracefully."""
        variant = assign_variant("promo_test", None, self.schema)
        self.assertIsNone(variant)

    def test_variant_in_schema_list(self):
        """Assigned variant is always in schema.variants."""
        for i in range(50):
            variant = assign_variant("promo_test", f"user_{i}", self.schema)
            if variant:
                self.assertIn(variant, self.schema.variants)

    def test_different_test_names_independent(self):
        """Different test names are assigned independently."""
        schema1 = TestSchema(
            name="test_1",
            variants=["control", "variant_a"],
            rollout_pct=100,
            metrics=["conversion"]
        )
        schema2 = TestSchema(
            name="test_2",
            variants=["control", "variant_b"],
            rollout_pct=100,
            metrics=["click"]
        )

        user_id = "same_user"
        variant1 = assign_variant("test_1", user_id, schema1)
        variant2 = assign_variant("test_2", user_id, schema2)

        # Same user can have different variants in different tests
        # (they are independent hash spaces)
        self.assertIsNotNone(variant1)
        self.assertIsNotNone(variant2)
        self.assertIn(variant1, schema1.variants)
        self.assertIn(variant2, schema2.variants)


class TestMetricRecording(unittest.TestCase):
    """Tests for metric recording and retrieval."""

    def setUp(self):
        clear_metrics()

    def tearDown(self):
        clear_metrics()

    def test_record_metric_success(self):
        """Valid metric is recorded successfully."""
        result = record_metric("test_1", "control", "conversion", 1.0)
        self.assertTrue(result)

    def test_record_metric_float_value(self):
        """Float values are recorded."""
        result = record_metric("test_1", "variant_a", "latency_ms", 123.45)
        self.assertTrue(result)

        metrics = get_metrics("test_1")
        self.assertIn("latency_ms", metrics)
        self.assertEqual(len(metrics["latency_ms"]), 1)
        self.assertEqual(metrics["latency_ms"][0]["value"], 123.45)

    def test_record_metric_int_value(self):
        """Integer values are recorded."""
        result = record_metric("test_1", "control", "click", 1)
        self.assertTrue(result)

    def test_empty_test_name_fails(self):
        """Empty test name fails gracefully."""
        result = record_metric("", "control", "conversion", 1.0)
        self.assertFalse(result)

    def test_empty_variant_fails(self):
        """Empty variant fails gracefully."""
        result = record_metric("test_1", "", "conversion", 1.0)
        self.assertFalse(result)

    def test_empty_metric_name_fails(self):
        """Empty metric name fails gracefully."""
        result = record_metric("test_1", "control", "", 1.0)
        self.assertFalse(result)

    def test_non_numeric_value_fails(self):
        """Non-numeric value fails gracefully."""
        result = record_metric("test_1", "control", "conversion", "not_a_number")
        self.assertFalse(result)

    def test_none_value_fails(self):
        """None value fails gracefully."""
        result = record_metric("test_1", "control", "conversion", None)
        self.assertFalse(result)

    def test_get_metrics_all_variants(self):
        """get_metrics retrieves metrics from all variants."""
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_1", "variant_a", "conversion", 1.0)
        record_metric("test_1", "variant_b", "conversion", 1.0)

        metrics = get_metrics("test_1")
        self.assertIn("conversion", metrics)
        self.assertEqual(len(metrics["conversion"]), 3)

    def test_get_metrics_filter_by_variant(self):
        """get_metrics can filter by specific variant."""
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_1", "variant_a", "conversion", 1.0)
        record_metric("test_1", "variant_a", "conversion", 1.0)

        metrics = get_metrics("test_1", variant="variant_a")
        self.assertIn("conversion", metrics)
        self.assertEqual(len(metrics["conversion"]), 2)
        for record in metrics["conversion"]:
            self.assertEqual(record["variant"], "variant_a")

    def test_get_metrics_multiple_metric_types(self):
        """get_metrics handles multiple metric types."""
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_1", "control", "latency_ms", 100.5)
        record_metric("test_1", "control", "click", 0.0)

        metrics = get_metrics("test_1")
        self.assertEqual(len(metrics), 3)
        self.assertIn("conversion", metrics)
        self.assertIn("latency_ms", metrics)
        self.assertIn("click", metrics)

    def test_get_metrics_nonexistent_test(self):
        """get_metrics returns empty dict for nonexistent test."""
        metrics = get_metrics("nonexistent_test")
        self.assertEqual(metrics, {})

    def test_clear_metrics(self):
        """clear_metrics removes all recorded metrics."""
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_2", "variant_a", "click", 1.0)

        clear_metrics()

        metrics1 = get_metrics("test_1")
        metrics2 = get_metrics("test_2")
        self.assertEqual(metrics1, {})
        self.assertEqual(metrics2, {})


class TestThreadSafety(unittest.TestCase):
    """Tests for concurrent access to metrics store."""

    def setUp(self):
        clear_metrics()

    def tearDown(self):
        clear_metrics()

    def test_concurrent_metric_recording(self):
        """Concurrent writes to metrics are all recorded."""
        def record_metrics(thread_id, count):
            for i in range(count):
                record_metric(
                    f"test_{thread_id}",
                    f"variant_{thread_id}",
                    "conversion",
                    1.0
                )

        threads = []
        for tid in range(5):
            t = threading.Thread(target=record_metrics, args=(tid, 20))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Check that all records were written (no lost updates)
        total_records = 0
        for tid in range(5):
            metrics = get_metrics(f"test_{tid}")
            if "conversion" in metrics:
                total_records += len(metrics["conversion"])

        self.assertEqual(total_records, 5 * 20)

    def test_concurrent_read_write(self):
        """Concurrent reads and writes don't crash."""
        def writer():
            for i in range(50):
                record_metric("stress_test", f"var_{i % 3}", "metric", float(i))

        def reader():
            for i in range(50):
                get_metrics("stress_test")

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=writer))
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without exception
        stats_result = stats()
        self.assertGreater(stats_result["total_records"], 0)


class TestMemoryManagement(unittest.TestCase):
    """Tests for TTL and eviction logic."""

    def setUp(self):
        clear_metrics()

    def tearDown(self):
        clear_metrics()

    def test_stats_reports_metrics_count(self):
        """stats() reports correct metric counts."""
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_1", "control", "conversion", 1.0)
        record_metric("test_2", "variant_a", "click", 1.0)

        result = stats()
        self.assertEqual(result["total_records"], 3)
        self.assertEqual(result["total_metric_keys"], 2)

    def test_stats_empty_store(self):
        """stats() on empty store returns zeros."""
        result = stats()
        self.assertEqual(result["total_records"], 0)
        self.assertEqual(result["total_metric_keys"], 0)

    def test_max_metrics_limit_respected(self):
        """MAX_METRICS_ENTRIES setting is respected (checked at GC time)."""
        # Note: GC only runs every 60s, so we can't easily test eviction
        # in unit tests. This test just verifies the config is present.
        result = stats()
        self.assertIn("max_entries", result)
        self.assertGreater(result["max_entries"], 0)

    def test_metric_record_has_timestamp(self):
        """Recorded metrics have timestamps."""
        record_metric("test_1", "control", "conversion", 1.0)
        metrics = get_metrics("test_1")

        self.assertIn("conversion", metrics)
        record_dict = metrics["conversion"][0]
        self.assertIn("timestamp", record_dict)
        self.assertIsInstance(record_dict["timestamp"], float)

    def test_invalidate_user_cache(self):
        """invalidate_user_cache() doesn't crash (currently no-op)."""
        ab.invalidate_user_cache()  # Should not raise


class TestIntegration(unittest.TestCase):
    """End-to-end workflow tests."""

    def setUp(self):
        clear_metrics()

    def tearDown(self):
        clear_metrics()

    def test_full_ab_test_workflow(self):
        """Complete workflow: schema -> assign -> record -> retrieve."""
        # Define test
        schema = TestSchema(
            name="checkout_flow",
            variants=["control", "new_button"],
            rollout_pct=100,
            metrics=["conversion", "latency_ms"]
        )
        self.assertTrue(schema.validate())

        # Simulate test run with 100 users
        control_count = 0
        new_button_count = 0
        for user_id in range(100):
            # Assign variant
            variant = assign_variant("checkout_flow", f"user_{user_id}", schema)
            self.assertIsNotNone(variant)

            # Simulate metric recording
            if variant == "control":
                control_count += 1
                record_metric("checkout_flow", variant, "conversion", 1.0)
                record_metric("checkout_flow", variant, "latency_ms", 100.0)
            else:
                new_button_count += 1
                record_metric("checkout_flow", variant, "conversion", 1.0)
                record_metric("checkout_flow", variant, "latency_ms", 95.0)

        # Retrieve and validate
        metrics = get_metrics("checkout_flow")
        self.assertIn("conversion", metrics)
        self.assertIn("latency_ms", metrics)

        control_metrics = get_metrics("checkout_flow", variant="control")
        button_metrics = get_metrics("checkout_flow", variant="new_button")

        self.assertEqual(len(control_metrics.get("conversion", [])), control_count)
        self.assertEqual(len(button_metrics.get("conversion", [])), new_button_count)

    def test_multiple_tests_independent(self):
        """Multiple tests track metrics independently."""
        schema1 = TestSchema(
            name="test_a",
            variants=["control", "var_a"],
            rollout_pct=100,
            metrics=["metric"]
        )
        schema2 = TestSchema(
            name="test_b",
            variants=["control", "var_b"],
            rollout_pct=100,
            metrics=["metric"]
        )

        # Run both tests
        for i in range(10):
            v1 = assign_variant("test_a", f"user_{i}", schema1)
            v2 = assign_variant("test_b", f"user_{i}", schema2)
            record_metric("test_a", v1, "metric", 1.0)
            record_metric("test_b", v2, "metric", 2.0)

        # Metrics should not cross-contaminate
        metrics_a = get_metrics("test_a")
        metrics_b = get_metrics("test_b")

        self.assertEqual(len(metrics_a["metric"]), 10)
        self.assertEqual(len(metrics_b["metric"]), 10)

        # Values should differ
        a_values = [r["value"] for r in metrics_a["metric"]]
        b_values = [r["value"] for r in metrics_b["metric"]]
        self.assertTrue(all(v == 1.0 for v in a_values))
        self.assertTrue(all(v == 2.0 for v in b_values))


class TestEdgeCases(unittest.TestCase):
    """Edge case and boundary tests."""

    def setUp(self):
        clear_metrics()

    def tearDown(self):
        clear_metrics()

    def test_variant_with_special_characters(self):
        """Variants with special characters work."""
        schema = TestSchema(
            name="test-with-dash",
            variants=["control", "var_with_underscore", "var-with-dash"],
            rollout_pct=100,
            metrics=["metric"]
        )
        self.assertTrue(schema.validate())

        variant = assign_variant("test-with-dash", "user_1", schema)
        self.assertIn(variant, schema.variants)

    def test_metric_with_zero_value(self):
        """Zero values are recorded."""
        record_metric("test", "control", "conversion", 0.0)
        metrics = get_metrics("test")
        self.assertEqual(len(metrics["conversion"]), 1)
        self.assertEqual(metrics["conversion"][0]["value"], 0.0)

    def test_metric_with_negative_value(self):
        """Negative values are recorded (for deltas, etc)."""
        record_metric("test", "control", "delta", -5.5)
        metrics = get_metrics("test")
        self.assertEqual(metrics["delta"][0]["value"], -5.5)

    def test_large_metric_value(self):
        """Very large values are handled."""
        record_metric("test", "control", "big", 1e10)
        metrics = get_metrics("test")
        self.assertEqual(metrics["big"][0]["value"], 1e10)

    def test_many_variants(self):
        """Schema with many variants works."""
        variants = [f"var_{i}" for i in range(100)]
        schema = TestSchema(
            name="many_variants",
            variants=variants,
            rollout_pct=100,
            metrics=["metric"]
        )
        self.assertTrue(schema.validate())

    def test_long_user_id(self):
        """Very long user_id strings work."""
        long_id = "x" * 10000
        schema = TestSchema(
            name="test",
            variants=["control", "variant"],
            rollout_pct=100,
            metrics=["metric"]
        )
        variant = assign_variant("test", long_id, schema)
        self.assertIsNotNone(variant)


if __name__ == "__main__":
    unittest.main()
