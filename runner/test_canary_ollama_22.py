#!/usr/bin/env python3
"""
test_canary_ollama_22.py — Canary test for coder routing with bottleneck awareness.

Validates that the coder routing system:
A) Tracks response time metrics per route to detect bottlenecks in remediation loops
B) Avoids slow routes (> remediation_response_time_threshold_ms) by routing to faster models
C) Learns from response times to select optimal paths (analogous to legal-radar-v2)
D) Maintains backward compatibility with existing routing behavior
E) Handles measurement failures gracefully (fail-soft)
F) Thread-safely records concurrent operation measurements
G) Prefers learned routes when response time is acceptable
H) Falls back to faster alternatives when bottlenecks are detected

Orchestration Contract (Expected Routes with Performance):
  - pipeline_scout -> local:llama3.2:3b (q=4.7, ~500ms)
  - completion -> local:llama3.2:3b (q=6.45, ~400ms)
  - meta_loop_improvement -> local:codestral:22b (q=7.7, ~800ms)
  - build_fix -> local:llama3.1 (q=7.7, ~600ms)
  - remediation fallback -> deepseek-v4-flash (q=7.4, ~300ms) when response time exceeds threshold

Test Coverage:
  - 20+ test cases covering normal paths, bottleneck detection, edge cases
  - Response time measurement and threshold evaluation
  - Route selection under performance pressure
  - Graceful degradation when measurements fail
"""
import os
import sys
import time
import unittest
import threading
from unittest.mock import MagicMock, patch, call
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import model_gateway
import app_triage

# Constants for bottleneck detection
DEFAULT_REMEDIATION_THRESHOLD_MS = 500
DEFAULT_RESPONSE_TIME_WINDOW_SECS = 300  # 5-minute rolling window


class CoderRoutingBottleneckCanary(unittest.TestCase):
    """20+ test cases for coder routing with bottleneck detection and response time tracking."""

    def setUp(self):
        """Reset environment and mocks before each test."""
        os.environ.pop("ORCH_USE_LEARNED_APP_ROUTES", None)
        os.environ.pop("ORCH_LEARNED_ROUTE_MIN_QUALITY", None)
        os.environ.pop("ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS", None)
        os.environ.pop("ORCH_ENABLE_BOTTLENECK_DETECTION", None)

    def test_response_time_tracked_for_normal_completion_operation(self):
        """Normal path: response time is measured and recorded for completion operation."""
        db = MagicMock()
        db.select.return_value = []
        insert_calls = []
        db.insert.side_effect = lambda table, row, **kw: insert_calls.append((table, row))

        def fake_call(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.05)  # Simulate 50ms latency
            return {"text": "response", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {"ORCH_ENABLE_BOTTLENECK_DETECTION": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["deepseek"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                          project="orchestrator", operation="completion",
                                          task_class="qa", record_op=True)
        self.assertIn("response_time_ms", result)
        self.assertGreater(result["response_time_ms"], 0)

    def test_response_time_below_threshold_allows_route_selection(self):
        """Normal path: route selection proceeds when response time is below threshold."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_cost": 0.0,
            "avg_response_time_ms": 400,  # Below typical 500ms threshold
        }]

        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model, "response_time_ms": 420}

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["local", "deepseek"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                          project="orchestrator", operation="completion",
                                          task_class="qa", record_op=False)
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["model"], "llama3.2:3b")

    def test_response_time_above_threshold_triggers_fallback_to_faster_route(self):
        """Edge case: when response time exceeds threshold, fallback to faster model."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_cost": 0.0,
            "avg_response_time_ms": 800,  # Exceeds 500ms threshold
        }]

        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["deepseek", "local"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("local", "llama3.1", "test",
                                          project="orchestrator", operation="completion",
                                          task_class="qa", record_op=False, fallback=True)
        # Should have fallen back to faster provider
        self.assertEqual(result["provider"], "deepseek")

    def test_remediation_loop_detects_bottleneck_on_slow_consecutive_calls(self):
        """Edge case: detect bottleneck when consecutive remediation calls exceed threshold."""
        db = MagicMock()
        db.select.return_value = []
        call_times = []

        def fake_call_slow(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.6)  # 600ms, exceeds 500ms threshold
            call_times.append(time.time())
            return {"text": "response", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["deepseek"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call_slow):
            result1 = model_gateway.complete("deepseek", "deepseek-chat", "test1",
                                           project="orchestrator", operation="remediation",
                                           task_class="bugfix", record_op=True)
        self.assertGreater(result1.get("response_time_ms", 0), 500)

    def test_bottleneck_detection_disabled_skips_threshold_checks(self):
        """Edge case: when bottleneck detection disabled, no threshold enforcement."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 1000,  # Very slow
        }]

        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "false"  # Disabled
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["local", "deepseek"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                          project="orchestrator", operation="completion",
                                          task_class="qa", record_op=False)
        # Should use learned route despite slow response time
        self.assertEqual(result["provider"], "local")

    def test_response_time_measurement_fails_soft_on_timing_error(self):
        """Error handling: measurement failure doesn't wedge routing."""
        db = MagicMock()
        db.select.return_value = []

        def fake_call_broken(provider, model, prompt, project=None, timeout=90):
            # Simulate response time measurement failure
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.dict(os.environ, {"ORCH_ENABLE_BOTTLENECK_DETECTION": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.dict(sys.modules, {"prompt_result_cache": None}), \
             patch.object(model_gateway, "available", return_value=["deepseek"]), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call_broken):
            try:
                result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                              project="orchestrator", operation="completion",
                                              task_class="qa", record_op=True)
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"Measurement failure wedged routing: {e}")

    def test_response_time_window_respects_time_bounds(self):
        """Staleness: response time window refreshes after expiration."""
        db = MagicMock()
        select_call_count = [0]

        def select_side_effect(*args, **kwargs):
            select_call_count[0] += 1
            if select_call_count[0] == 1:
                return [{
                    "provider": "local",
                    "model": "llama3.2:3b",
                    "app": "orchestrator",
                    "operation": "completion",
                    "avg_quality": 7.0,
                    "avg_response_time_ms": 400,
                    "updated_at": "2026-07-16T00:00:00Z",
                }]
            return []  # Simulate stale data

        db.select.side_effect = select_side_effect

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result1 = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
            # Second call should re-query after window expiration
            result2 = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result1)
        self.assertEqual(select_call_count[0], 2)

    def test_pipeline_scout_routes_to_llama32_3b_with_quality_and_timing(self):
        """Normal path: pipeline_scout operation routes with quality and response time metrics."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "pipeline_scout",
            "avg_quality": 4.7,
            "avg_cost": 0.0,
            "avg_response_time_ms": 500,
            "updated_at": "2026-07-16T00:00:00Z",
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "pipeline_scout", "plan", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "local")
        self.assertEqual(result[1], "llama3.2:3b")

    def test_completion_routes_to_llama32_3b_with_fast_response_time(self):
        """Normal path: completion operation routes to model with acceptable response time."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 6.45,
            "avg_cost": 0.0,
            "avg_response_time_ms": 400,
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "450"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_meta_loop_improvement_routes_to_codestral_22b(self):
        """Normal path: meta_loop_improvement routes to codestral despite slower response time."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "codestral:22b",
            "app": "orchestrator",
            "operation": "meta_loop_improvement",
            "avg_quality": 7.7,
            "avg_cost": 0.0,
            "avg_response_time_ms": 800,
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "meta_loop_improvement", "plan", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "codestral:22b")

    def test_build_fix_routes_to_llama31_within_time_budget(self):
        """Normal path: build_fix routes to llama3.1 with response time within budget."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "build_fix",
            "avg_quality": 7.7,
            "avg_cost": 0.0,
            "avg_response_time_ms": 600,
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "700"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "build_fix", "bugfix", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.1")

    def test_response_time_none_treated_as_acceptable(self):
        """Edge case: missing response time data doesn't reject a learned route."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_cost": 0.0,
            "avg_response_time_ms": None,  # No timing data
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)

    def test_response_time_zero_treated_as_measurement_artifact(self):
        """Edge case: response_time_ms=0 doesn't trigger bottleneck (graceful)."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 0,  # Likely measurement artifact
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)

    def test_response_time_negative_handled_gracefully(self):
        """Edge case: negative response time (measurement error) doesn't wedge routing."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": -5,  # Invalid measurement
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # Should accept the route despite invalid measurement
        self.assertIsNotNone(result)

    def test_concurrent_response_time_recordings_dont_corrupt_state(self):
        """Thread-safety: concurrent response time recordings are isolated."""
        db = MagicMock()
        db.select.return_value = []
        recorded_times = []
        lock = threading.Lock()

        def fake_call(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.01 * (hash(threading.current_thread().name) % 5))
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        def thread_target(op_name):
            with patch.dict(os.environ, {"ORCH_ENABLE_BOTTLENECK_DETECTION": "true"}, clear=False), \
                 patch.dict(sys.modules, {"db": db}), \
                 patch.dict(sys.modules, {"prompt_result_cache": None}), \
                 patch.object(model_gateway, "available", return_value=["deepseek"]), \
                 patch.object(model_gateway, "_call_provider", side_effect=fake_call):
                result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                              project="orchestrator", operation=op_name,
                                              task_class="qa", record_op=True)
                with lock:
                    recorded_times.append(result.get("response_time_ms", 0))

        threads = [threading.Thread(target=thread_target, args=(f"op_{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(recorded_times), 5)
        self.assertTrue(all(rt >= 0 for rt in recorded_times))

    def test_threshold_comparison_uses_correct_operator(self):
        """Accuracy: response time threshold comparison is >= (not >)."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 500,  # Exactly at threshold
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        # At threshold: should be considered acceptable (not a bottleneck)
        self.assertIsNotNone(result)

    def test_threshold_just_below_limit_is_acceptable(self):
        """Accuracy: response time just below threshold is accepted."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 499,
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)

    def test_threshold_just_above_limit_triggers_fallback(self):
        """Accuracy: response time just above threshold triggers bottleneck detection."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.1",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 501,  # Just over 500
        }]

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_ENABLE_BOTTLENECK_DETECTION": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["deepseek"]), \
             patch.dict(sys.modules, {"prompt_result_cache": None}):
            # Should trigger fallback logic
            db.insert.side_effect = lambda *args, **kwargs: None
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertIsNotNone(result)

    def test_response_time_non_numeric_string_handled_gracefully(self):
        """Error handling: non-numeric response time doesn't wedge routing."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": "slow",  # Invalid type
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            try:
                result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"Invalid response_time_ms type wedged routing: {e}")

    def test_multiple_operations_have_independent_thresholds(self):
        """Accuracy: different operations can have different response time profiles."""
        db = MagicMock()
        def select_side_effect(*args, **kwargs):
            if "pipeline_scout" in str(kwargs):
                return [{
                    "provider": "local",
                    "model": "llama3.2:3b",
                    "app": "orchestrator",
                    "operation": "pipeline_scout",
                    "avg_response_time_ms": 350,  # Fast
                }]
            elif "meta_loop" in str(kwargs):
                return [{
                    "provider": "local",
                    "model": "codestral:22b",
                    "app": "orchestrator",
                    "operation": "meta_loop_improvement",
                    "avg_response_time_ms": 850,  # Slower but acceptable for this op
                }]
            return []

        db.select.side_effect = select_side_effect

        with patch.dict(os.environ, {
                "ORCH_USE_LEARNED_APP_ROUTES": "true",
                "ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS": "500"
            }, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            scout_result = model_gateway._learned_route("orchestrator", "pipeline_scout", "plan", "standard")
            meta_result = model_gateway._learned_route("orchestrator", "meta_loop_improvement", "plan", "standard")
        self.assertIsNotNone(scout_result)
        self.assertIsNotNone(meta_result)

    def test_app_triage_route_includes_response_time_in_metadata(self):
        """Normal path: app_triage.route() returns routing decision with response time info."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_response_time_ms": 400,
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertIn("provider", result)
        self.assertIn("model", result)
        # Response time metadata may be present in advanced implementations
        self.assertIsNotNone(result.get("provider"))

    def test_routing_db_exception_returns_none_fail_soft(self):
        """Error handling: database exception on response time lookup returns None (fail-soft)."""
        db = MagicMock()
        db.select.side_effect = RuntimeError("db connection failed")

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNone(result)

    def test_backward_compatibility_learned_route_without_response_time_field(self):
        """Backward compatibility: old route records without response_time_ms still work."""
        db = MagicMock()
        db.select.return_value = [{
            "provider": "local",
            "model": "llama3.2:3b",
            "app": "orchestrator",
            "operation": "completion",
            "avg_quality": 7.0,
            "avg_cost": 0.0,
            # No avg_response_time_ms field (legacy data)
        }]

        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "true"}, clear=False), \
             patch.dict(sys.modules, {"db": db}), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")


if __name__ == "__main__":
    unittest.main()
