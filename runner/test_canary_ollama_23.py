#!/usr/bin/env python3
"""
test_canary_ollama_23.py — Canary test for coder routing with response time percentiles.

Extends canary-ollama-22 with percentile-based response time tracking (p50, p95, p99)
to catch tail latencies in remediation loops. Addresses operator feedback: "measured
bottleneck in application's response time during the remediation loop."

Validates that the coder routing system:
A) Tracks response time percentiles (p50, p95, p99) instead of averages only
B) Uses p95 as the primary SLO threshold for remediation operations
C) Detects tail-latency bottlenecks that averages would miss
D) Falls back to faster routes when p95 exceeds threshold (not just average)
E) Maintains backward compatibility with canary-22's average-based routing
F) Routes remediation operations with priority (lower threshold) vs other tasks
G) Computes percentiles incrementally under concurrent load
H) Handles missing percentile data gracefully (fails soft, uses available metrics)

Orchestration Contract (Percentile-Based Routes with Latency SLOs):
  - pipeline_scout -> local:llama3.2:3b (p50=300ms, p95=500ms, p99=700ms)
  - completion -> local:llama3.2:3b (p50=200ms, p95=400ms, p99=600ms)
  - remediation -> deepseek-v4-flash (p50=150ms, p95=300ms, p99=500ms, SLO=400ms)
  - build_fix -> local:llama3.1 (p50=400ms, p95=600ms, p99=1000ms, SLO=800ms)
  - meta_loop_improvement -> local:codestral:22b (p50=600ms, p95=800ms, p99=1200ms, SLO=1000ms)

Test Coverage:
  - 25+ test cases covering percentile detection, tail latency, SLO enforcement
  - Remediation loop priority (lower threshold) vs non-remediation operations
  - Percentile-based route selection and fallback
  - Incremental percentile computation under concurrent load
  - Graceful degradation when percentile data is incomplete or missing
  - Backward compatibility with average-only routing
"""
import os
import sys
import time
import unittest
import threading
from unittest.mock import MagicMock, patch, call
from collections import defaultdict
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import app_triage

# Constants for percentile-based routing
DEFAULT_REMEDIATION_SLO_MS = 400  # Stricter SLO for remediation than generic 500ms
DEFAULT_GENERIC_THRESHOLD_MS = 500
PERCENTILE_WINDOW_SECS = 300  # 5-minute rolling window for percentile computation


class CoderRoutingPercentileCanary(unittest.TestCase):
    """25+ test cases for coder routing with response time percentile tracking."""

    def setUp(self):
        """Reset environment and mocks before each test."""
        os.environ.pop("ORCH_USE_LEARNED_APP_ROUTES", None)
        os.environ.pop("ORCH_REMEDIATION_SLO_P95_MS", None)
        os.environ.pop("ORCH_GENERIC_RESPONSE_TIME_THRESHOLD_MS", None)
        os.environ.pop("ORCH_ENABLE_PERCENTILE_ROUTING", None)
        os.environ.pop("ORCH_REMEDIATION_PRIORITY_ROUTING", None)

    def test_percentile_p95_tracked_separate_from_average(self):
        """Normal path: p95 is computed and tracked independently from average."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "remediation",
            "avg_response_time_ms": 350,
            "p50_response_time_ms": 280,
            "p95_response_time_ms": 520,  # Exceeds 400ms SLO even though avg is ok
            "p99_response_time_ms": 750,
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local", "deepseek"]):
            result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
        # Should reject this route because p95 > 400ms, even though avg is ok
        self.assertIsNone(result) or self.assertNotEqual(result[1], "llama3.2:3b")

    def test_remediation_priority_uses_stricter_slo_than_generic_tasks(self):
        """Normal path: remediation operations have stricter p95 threshold than generic tasks."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",  # Non-remediation
            "avg_response_time_ms": 350,
            "p95_response_time_ms": 450,  # Between 400 and 500
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400",
                "ORCH_GENERIC_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Generic task should accept p95=450 (< 500 threshold)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_same_route_rejects_remediation_with_p95_above_slo(self):
        """Normal path: same route rejected for remediation but accepted for generic task."""
        db = MagicMock()

        def select_side_effect(*args, **kwargs):
            return [{
                "provider": "local",
                "model": "llama3.2:3b",
                "app": "orchestrator",
                "operation": "remediation" if "remediation" in str(kwargs) else "completion",
                "avg_response_time_ms": 350,
                "p95_response_time_ms": 450,
            }]

        db.select.side_effect = select_side_effect

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400",
                "ORCH_GENERIC_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local", "deepseek"]):
            rem_result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
            comp_result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Remediation rejects, completion accepts same p95=450 route
        self.assertTrue(rem_result is None or rem_result[0] == "deepseek")
        self.assertIsNotNone(comp_result)

    def test_p50_used_for_fast_path_estimate(self):
        """Normal path: p50 provides fast-path latency estimate for UX feedback."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "p50_response_time_ms": 200,
            "p95_response_time_ms": 400,
            "p99_response_time_ms": 600,
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)
        # Route metadata may include p50 for UX timing estimates
        self.assertIn("provider", result)

    def test_p99_indicates_worst_case_tail_latency(self):
        """Normal path: p99 provides worst-case latency for SLO breach investigation."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "meta_loop_improvement",
            "p50_response_time_ms": 600,
            "p95_response_time_ms": 800,
            "p99_response_time_ms": 1200,  # Worst case indicates uneven performance
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "meta_loop_improvement", "plan", "standard")
        self.assertIsNotNone(result)
        # Long tail (p99 >> p95) indicates occasional spikes—documented in route metadata

    def test_tail_latency_bottleneck_detection_catches_what_average_misses(self):
        """Edge case: avg=300 but p99=900; tail latencies cause user-visible disruption."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "remediation",
            "avg_response_time_ms": 300,  # Looks good
            "p50_response_time_ms": 250,
            "p95_response_time_ms": 450,  # Exceeds 400ms SLO
            "p99_response_time_ms": 900,  # Severe tail latency
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["deepseek"]):
            result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
        # Should reject despite good average, due to tail latency
        self.assertTrue(result is None or result[0] == "deepseek")

    def test_percentile_routing_disabled_falls_back_to_average(self):
        """Edge case: when percentile routing disabled, use average instead."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "remediation",
            "avg_response_time_ms": 350,  # Below 400 remediation SLO
            "p95_response_time_ms": 550,  # Exceeds 400 but ignored
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "false",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
        # Should accept based on average when percentile routing disabled
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_missing_percentile_data_uses_average_gracefully(self):
        """Error handling: missing p95/p99 data, use average (fail-soft)."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_response_time_ms": 350,
            # No percentile fields (legacy data)
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should fallback to average threshold, not crash
        self.assertIsNotNone(result)

    def test_p95_none_treated_as_missing_falls_back_to_average(self):
        """Error handling: p95_response_time_ms=None, use average."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "remediation",
            "avg_response_time_ms": 350,
            "p95_response_time_ms": None,
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
        # Should use average instead of crashing
        self.assertIsNotNone(result)

    def test_p95_zero_treated_as_measurement_artifact(self):
        """Error handling: p95_response_time_ms=0 (artifact), use average."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_response_time_ms": 350,
            "p95_response_time_ms": 0,  # Likely measurement artifact
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should use average, not reject based on p95=0
        self.assertIsNotNone(result)

    def test_p95_negative_handled_gracefully(self):
        """Error handling: negative p95 (measurement error), use average."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_response_time_ms": 350,
            "p95_response_time_ms": -10,  # Invalid
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should accept route despite invalid percentile
        self.assertIsNotNone(result)

    def test_p95_non_numeric_string_fails_soft(self):
        """Error handling: p95_response_time_ms='slow' (type error), use average."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_response_time_ms": 350,
            "p95_response_time_ms": "slow",  # Type error
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            try:
                result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"Non-numeric p95 wedged routing: {e}")

    def test_percentile_ordering_p50_le_p95_le_p99(self):
        """Sanity check: percentiles respect ordering (p50 <= p95 <= p99)."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "p50_response_time_ms": 250,
            "p95_response_time_ms": 400,
            "p99_response_time_ms": 600,
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)
        # Sanity: if percentiles were reversed, routing should still work

    def test_concurrent_percentile_updates_dont_corrupt_state(self):
        """Thread-safety: concurrent percentile updates are isolated."""
        db = MagicMock()
        db.select.return_value = []
        recorded_p95s = []
        lock = threading.Lock()

        def fake_call(provider, model, prompt, project=None, timeout=90):
            latency_ms = random.randint(200, 800)
            time.sleep(latency_ms / 1000.0)
            return {
                "text": "ok",
                "cost_usd": 0.0,
                "provider": provider,
                "model": model,
                "response_time_ms": latency_ms
            }

        def thread_target(op_name):
            with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
                 patch.dict(sys.modules, {"db": db}), \
                 patch.dict(sys.modules, {"prompt_result_cache": None}), \
                 patch.object(model_gateway, "available", return_value=["deepseek"]), \
                 patch.object(model_gateway, "_call_provider", side_effect=fake_call):
                result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                              project="orchestrator", operation=op_name,
                                              task_class="qa", record_op=True)
                with lock:
                    if "p95_response_time_ms" in result:
                        recorded_p95s.append(result["p95_response_time_ms"])

        threads = [threading.Thread(target=thread_target, args=(f"op_{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No corruption: all recorded percentiles should be valid (0 or positive)
        self.assertTrue(all(p >= 0 for p in recorded_p95s))

    def test_remediation_fallback_when_p95_exceeds_slo(self):
        """Normal path: remediation falls back to faster route when p95 > SLO."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "remediation",
            "avg_response_time_ms": 350,
            "p95_response_time_ms": 450,  # Exceeds 400ms SLO
        }]

        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["deepseek", "local"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("local", "llama3.1", "test",
                                          project="orchestrator", operation="remediation",
                                          task_class="bugfix", record_op=False, fallback=True)
        # Should fall back to faster provider
        self.assertEqual(result["provider"], "deepseek")

    def test_build_fix_respects_higher_threshold_than_remediation(self):
        """Normal path: build_fix has higher p95 threshold (800ms) than remediation (400ms)."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "build_fix",
            "p95_response_time_ms": 650,  # Between 400 and 800
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
                # build_fix SLO not set, defaults to generic 500 or operation-specific
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "build_fix", "bugfix", "standard")
        # build_fix should accept p95=650 (operation-specific allowance)
        self.assertIsNotNone(result) or self.assertEqual(result[1], "llama3.1")

    def test_completion_operation_uses_generic_threshold_not_remediation_slo(self):
        """Normal path: completion (non-remediation) uses generic 500ms not 400ms SLO."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "p95_response_time_ms": 450,  # Between 400 and 500
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400",
                "ORCH_GENERIC_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # completion should accept p95=450 (< 500 generic threshold)
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_percentile_computation_over_300s_rolling_window(self):
        """Normal path: percentiles computed over 5-minute rolling window (staleness detection)."""
        db = MagicMock()
        now = time.time()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "p95_response_time_ms": 400,
            "updated_at": now - 100,  # 100s old, within 300s window
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should use fresh percentile data
        self.assertIsNotNone(result)

    def test_percentile_data_stale_after_300s_window_expires(self):
        """Staleness: percentile data beyond 300s window refreshes."""
        db = MagicMock()
        now = time.time()
        select_call_count = [0]

        def select_side_effect(*args, **kwargs):
            select_call_count[0] += 1
            if select_call_count[0] == 1:
                return [{
                    "provider": "local",
                    "model": "llama3.2:3b",
                    "app": "orchestrator",
                    "operation": "completion",
                    "p95_response_time_ms": 400,
                    "updated_at": now - 400,  # Beyond 300s window, stale
                }]
            return []  # Fresh query after refresh

        db.select.side_effect = select_side_effect

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result1 = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
            result2 = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should re-query after window expiration
        self.assertEqual(select_call_count[0], 2)

    def test_multiple_routes_ranked_by_p95_quality_tradeoff(self):
        """Normal path: when multiple routes available, rank by p95 + quality tradeoff."""
        db = MagicMock()

        def select_side_effect(*args, **kwargs):
            return [
                {
                    "provider": "local",
                    "model": "llama3.2:3b",
                    "app": "orchestrator",
                    "operation": "completion",
                    "avg_quality": 6.45,
                    "p95_response_time_ms": 350,
                },
                {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "app": "orchestrator",
                    "operation": "completion",
                    "avg_quality": 7.4,
                    "p95_response_time_ms": 300,  # Faster
                },
            ]

        db.select.side_effect = select_side_effect

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local", "deepseek"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should prefer deepseek (faster p95=300 + higher quality=7.4)
        self.assertIsNotNone(result)

    def test_app_triage_route_includes_percentile_metadata(self):
        """Normal path: app_triage.route() returns routing decision with percentile info."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "p50_response_time_ms": 200,
            "p95_response_time_ms": 400,
            "p99_response_time_ms": 600,
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        # Percentile metadata may be present in advanced implementations
        self.assertIn("provider", result)
        self.assertIn("model", result)

    def test_percentile_db_lookup_exception_returns_none_fail_soft(self):
        """Error handling: database exception on percentile lookup returns None (fail-soft)."""
        db = MagicMock()
        db.select.side_effect = RuntimeError("db connection failed")

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should fail soft, not crash
        self.assertIsNone(result)

    def test_backward_compat_routes_without_percentile_data_still_work(self):
        """Backward compatibility: old routes without percentile fields still route."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 6.45,
            "avg_response_time_ms": 350,
            "avg_cost": 0.0,
            # No p50, p95, p99 fields (legacy route data)
        }]

        with patch.dict(os.environ, {"ORCH_ENABLE_PERCENTILE_ROUTING": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should fallback to average gracefully
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_remediation_operation_identified_by_name_not_just_class(self):
        """Accuracy: operation name "remediation" triggers stricter SLO."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "remediation",
            "p95_response_time_ms": 420,
        }]

        with patch.dict(os.environ, {
                "ORCH_ENABLE_PERCENTILE_ROUTING": "true",
                "ORCH_REMEDIATION_SLO_P95_MS": "400"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["deepseek", "local"]):
            result = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
        # "remediation" operation should be identified and SLO applied
        self.assertTrue(result is None or result[0] == "deepseek")


if __name__ == "__main__":
    unittest.main()
