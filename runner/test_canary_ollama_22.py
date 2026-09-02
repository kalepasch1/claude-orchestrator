#!/usr/bin/env python3
"""
test_canary_ollama_22.py — Canary test for the coder routing contract in model_gateway/app_triage.

WHAT THIS FILE USED TO BE, AND WHY IT WAS REPLACED
--------------------------------------------------
Every test here previously asserted a "bottleneck-aware routing" feature that does not exist and
never has. Specifically it assumed:

  * app_op_routes rows carry an `avg_response_time_ms` column — the table has exactly
    (app, operation, provider, model, reason, avg_cost, avg_quality, n_samples, updated_at);
    see supabase/migrations/20260701164335_0012_app_operations_triage.sql. Nothing in the repo
    writes or reads such a column.
  * model_gateway._learned_route() compares that column against
    ORCH_REMEDIATION_RESPONSE_TIME_THRESHOLD_MS and falls back to a faster model when it is
    exceeded, gated by ORCH_ENABLE_BOTTLENECK_DETECTION. Neither environment variable is read
    anywhere in the repository — the only occurrences were in this file. _learned_route gates on
    quality, availability and provider terms, and on nothing else.
  * model_gateway.complete() returns `response_time_ms` in its result dict. It does not; it
    measures latency and hands it to _record_operation() as the app_operations.latency_ms column.
  * _learned_route() maintains a time-bounded cache ("response time window"). It has no cache at
    all; every call re-queries.

Because the invented column was simply ignored by the real code, roughly half these tests passed
for a reason that had nothing to do with what their names claimed, and the other half failed. The
file has been retargeted at the routing behaviour that actually exists, keeping each original
test's INTENT where the real API can carry it. Each test below carries a comment naming what it
used to assert and why that was wrong.

Also fixed: the concurrency test ran `patch.dict(sys.modules, {"db": MagicMock()})` inside five
threads. patch.dict restores by clearing and re-filling the dict, so interleaved restores parked
a MagicMock in sys.modules["db"] for the remainder of the pytest session and broke unrelated
files much later (see the repo-root conftest's _evict_leaked_doubles). Nothing here touches
sys.modules any more: the real module objects are patched with patch.object, on the main thread.

Routing contract actually under test:
  A) _learned_route() honours the app_op_routes quality floor, provider availability and
     provider terms, and falls through operation -> task_class -> "completion".
  B) complete() applies a learned route, falls back down FALLBACK_ORDER, and never raises.
  C) Latency is measured per attempt and recorded to app_operations.
  D) Confidential mode disables both learned routes and fallback.
  E) app_triage.route() prefers a learned route and degrades to the policy chooser.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app_triage
import db
import model_gateway
import prompt_result_cache

# The real defaults the module reads, so a change to either is a visible failure here.
DEFAULT_MIN_QUALITY = 6.5
ROUTES_TABLE = "app_op_routes"


def _route_row(provider="local", model="llama3.2:3b", operation="completion", quality=7.0, **extra):
    """One app_op_routes row, with only columns the migration actually defines."""
    row = {"app": "orchestrator", "operation": operation, "provider": provider, "model": model,
           "reason": "prior review loop", "avg_cost": 0.0, "avg_quality": quality,
           "n_samples": 12, "updated_at": "2026-07-16T00:00:00Z"}
    row.update(extra)
    return row


class _Recorder:
    """Thread-safe stand-in for db.select/db.insert that keeps the calls for assertions."""

    def __init__(self, rows=None, select_fn=None):
        self._rows = rows
        self._select_fn = select_fn
        self._lock = threading.Lock()
        self.selects = []
        self.inserts = []

    def select(self, table, params=None):
        with self._lock:
            self.selects.append((table, dict(params or {})))
        if self._select_fn is not None:
            return self._select_fn(table, params or {})
        return list(self._rows or [])

    def insert(self, table, row, **kw):
        with self._lock:
            self.inserts.append((table, dict(row)))
        return row

    @property
    def routed_operations(self):
        return [p.get("operation") for t, p in self.selects if t == ROUTES_TABLE]


def _patch_db(rec):
    """Patch the REAL db module object (never sys.modules) — model_gateway does `import db`
    inside the function body, so it resolves to this same object."""
    return [patch.object(db, "select", side_effect=rec.select),
            patch.object(db, "insert", side_effect=rec.insert)]


class _Patches:
    """Enter a list of patchers as one context manager, on the calling (main) thread."""

    def __init__(self, *patchers):
        self._patchers = [p for p in patchers if p is not None]

    def __enter__(self):
        self._started = [p.start() for p in self._patchers]
        return self._started

    def __exit__(self, *exc):
        for p in reversed(self._patchers):
            p.stop()
        return False


def _no_cache():
    """Keep prompt_result_cache out of the way without touching sys.modules or the cache file."""
    return [patch.object(prompt_result_cache, "lookup", return_value=None),
            patch.object(prompt_result_cache, "store", return_value=False)]


class LearnedRouteCanary(unittest.TestCase):
    """model_gateway._learned_route(project, operation, task_class, sensitivity)."""

    def test_learned_route_returns_provider_model_and_reason(self):
        # WAS test_pipeline_scout_routes_to_llama32_3b_with_quality_and_timing, which fed
        # avg_quality=4.7 plus an invented avg_response_time_ms and asserted a route came back.
        # 4.7 is below the ORCH_LEARNED_ROUTE_MIN_QUALITY floor of 6.5, so the real function
        # correctly returns None — the test only "passed" in the author's imagination. Asserting
        # the real three-part return value instead.
        rec = _Recorder([_route_row(operation="pipeline_scout", quality=7.4)])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            result = model_gateway._learned_route("orchestrator", "pipeline_scout", "plan", "standard")
        self.assertEqual(result[:2], ("local", "llama3.2:3b"))
        self.assertEqual(result[2], "learned orchestrator/pipeline_scout route q=7.4")
        table, params = rec.selects[0]
        self.assertEqual(table, ROUTES_TABLE)
        self.assertEqual(params["app"], "eq.orchestrator")
        self.assertEqual(params["operation"], "eq.pipeline_scout")
        self.assertEqual(params["order"], "updated_at.desc")

    def test_quality_below_the_floor_is_rejected_and_the_floor_is_configurable(self):
        # WAS test_completion_routes_to_llama32_3b_with_fast_response_time: avg_quality=6.45 with
        # a 450ms "threshold", asserting the route was returned. It fails against the real code
        # for a reason the test never mentions — 6.45 < the 6.5 quality floor. That floor is the
        # actual gate, so test it directly, in both directions.
        rec = _Recorder([_route_row(quality=6.45)])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "completion", "qa", "standard"))
        rec2 = _Recorder([_route_row(quality=6.45)])
        with _Patches(*_patch_db(rec2),
                      patch.object(model_gateway, "available", return_value=["local"]),
                      patch.dict(os.environ, {"ORCH_LEARNED_ROUTE_MIN_QUALITY": "6.0"}, clear=False)):
            self.assertEqual(
                model_gateway._learned_route("orchestrator", "completion", "qa", "standard")[:2],
                ("local", "llama3.2:3b"))

    def test_quality_exactly_at_the_floor_is_accepted(self):
        # WAS test_threshold_comparison_uses_correct_operator, which claimed to pin down whether
        # the (nonexistent) response-time comparison was > or >=. The real boundary is the
        # quality floor, compared as `< min_q: continue` — i.e. exactly at the floor is IN.
        rec = _Recorder([_route_row(quality=DEFAULT_MIN_QUALITY)])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertEqual(result[:2], ("local", "llama3.2:3b"))

    def test_missing_or_unparsable_quality_is_treated_as_zero_and_rejected(self):
        # WAS three tests asserting that avg_response_time_ms of None / 0 / -5 "doesn't wedge
        # routing" — all of which passed trivially because the column is never read. The column
        # that IS read and can genuinely be absent or junk is avg_quality; an unreadable quality
        # must not be silently promoted into a route. (None and "" hit the explicit `< min_q`
        # gate; a non-numeric string trips float() and the function's outer fail-soft. Both must
        # end at None, and neither may end at a route.)
        for bad in (None, "", "unrated"):
            rec = _Recorder([_route_row(quality=bad)])
            with _Patches(*_patch_db(rec),
                          patch.object(model_gateway, "available", return_value=["local"])):
                self.assertIsNone(
                    model_gateway._learned_route("orchestrator", "completion", "qa", "standard"),
                    "avg_quality=%r must not yield a route" % (bad,))

    def test_unknown_columns_on_the_row_are_ignored(self):
        # WAS test_backward_compatibility_learned_route_without_response_time_field. Inverted to
        # the direction that is actually load-bearing: the review loop may add columns to
        # app_op_routes, and _learned_route reads "select": "*", so an unrecognised column must
        # not change the decision.
        rec = _Recorder([_route_row(quality=7.0, some_future_column=123, n_samples=None)])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertEqual(result[:2], ("local", "llama3.2:3b"))

    def test_a_provider_that_is_not_available_is_skipped(self):
        # ADDED (the old file never covered the availability gate, though every one of its
        # scenarios silently depended on it via a patched available()).
        rec = _Recorder([_route_row(provider="local")])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["deepseek"])):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "completion", "qa", "standard"))

    def test_a_provider_the_terms_gate_refuses_is_skipped(self):
        # ADDED: a learned route must not be able to route a sensitive prompt to a provider
        # provider_terms disallows. Verifies the gate is consulted with the sensitivity argument.
        rec = _Recorder([_route_row(provider="local")])
        allowed = MagicMock(return_value=False)
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"]),
                      patch.object(model_gateway, "_provider_allowed", allowed)):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "completion", "qa", "confidential"))
        allowed.assert_any_call("local", "confidential")

    def test_operation_then_task_class_then_completion_are_tried_in_order(self):
        # WAS test_multiple_operations_have_independent_thresholds, whose db double branched on
        # `str(kwargs)` — but _learned_route passes its params POSITIONALLY, so kwargs was always
        # {} and both branches were dead; both lookups returned [] and both results were None.
        # The real fallthrough order is the thing worth pinning: operation, then task_class, then
        # the generic "completion" bucket.
        rec = _Recorder([])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "build_fix", "bugfix", "standard"))
        self.assertEqual(rec.routed_operations,
                         ["eq.build_fix", "eq.bugfix", "eq.completion"])

    def test_the_first_acceptable_operation_bucket_wins(self):
        # ADDED companion: the fallthrough must stop at the first usable row, not keep going.
        def select_fn(table, params):
            if params.get("operation") == "eq.meta_loop_improvement":
                return [_route_row(operation="meta_loop_improvement", model="codestral:22b", quality=7.7)]
            return [_route_row(model="llama3.2:3b", quality=9.9)]
        rec = _Recorder(select_fn=select_fn)
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            result = model_gateway._learned_route("orchestrator", "meta_loop_improvement", "plan", "standard")
        self.assertEqual(result[:2], ("local", "codestral:22b"))
        self.assertEqual(rec.routed_operations, ["eq.meta_loop_improvement"])

    def test_learned_route_is_not_cached_between_calls(self):
        # WAS test_response_time_window_respects_time_bounds, which asserted db.select is called
        # exactly twice across two _learned_route calls — i.e. that a 5-minute "response time
        # window" cache existed. There is no cache and no window in the module; the second call
        # made three selects (operation, task_class, "completion") for a total of four, which is
        # why it failed. The real, and more useful, property is that routing decisions are never
        # served from a stale memo: a row written by the review loop takes effect immediately.
        state = {"rows": [_route_row(model="llama3.2:3b", quality=7.0)]}
        rec = _Recorder(select_fn=lambda t, p: list(state["rows"]))
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            first = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
            state["rows"] = [_route_row(model="codestral:22b", quality=8.1)]
            second = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertEqual(first[1], "llama3.2:3b")
        self.assertEqual(second[1], "codestral:22b")
        self.assertEqual(len(rec.selects), 2)

    def test_learned_routes_can_be_switched_off_by_env(self):
        # WAS test_bottleneck_detection_disabled_skips_threshold_checks, which flipped the
        # invented ORCH_ENABLE_BOTTLENECK_DETECTION. The real kill switch on this code path is
        # ORCH_USE_LEARNED_APP_ROUTES, and when it is off the db must not be touched at all.
        rec = _Recorder([_route_row(quality=9.0)])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"]),
                      patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "false"}, clear=False)):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "completion", "qa", "standard"))
        self.assertEqual(rec.selects, [])

    def test_project_none_defaults_to_the_orchestrator_app(self):
        # ADDED: `app = project or "orchestrator"` is what keeps an unlabelled caller's telemetry
        # and its routes on the same key.
        rec = _Recorder([])
        with _Patches(*_patch_db(rec),
                      patch.object(model_gateway, "available", return_value=["local"])):
            model_gateway._learned_route(None, "completion", "qa", "standard")
        self.assertTrue(rec.selects)
        self.assertEqual(rec.selects[0][1]["app"], "eq.orchestrator")

    def test_db_exception_returns_none_fail_soft(self):
        # Kept from the original (it was already asserting real behaviour), with the sys.modules
        # MagicMock swapped for a patch on the real db module.
        with _Patches(patch.object(db, "select", side_effect=RuntimeError("db connection failed"))):
            self.assertIsNone(
                model_gateway._learned_route("orchestrator", "completion", "qa", "standard"))


class CompleteRoutingCanary(unittest.TestCase):
    """model_gateway.complete() — routing, fallback, telemetry."""

    def test_latency_is_measured_and_recorded_to_app_operations(self):
        # WAS test_response_time_tracked_for_normal_completion_operation, asserting
        # `response_time_ms` in complete()'s result. complete() returns exactly what
        # _call_provider returned plus optional fallback/learned_route keys — the timing it
        # measures goes to telemetry as app_operations.latency_ms. That is the real artefact a
        # bottleneck analysis would read, so assert it there.
        rec = _Recorder([])

        def fake_call(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.05)
            return {"text": "response", "cost_usd": 0.0, "provider": provider, "model": model}

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek"]),
                      patch.object(model_gateway, "_call_provider", side_effect=fake_call)):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=True)
        self.assertEqual(result["text"], "response")
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertEqual(len(ops), 1)
        self.assertGreaterEqual(ops[0]["latency_ms"], 40)
        self.assertEqual((ops[0]["provider"], ops[0]["model"]), ("deepseek", "deepseek-chat"))
        self.assertEqual((ops[0]["app"], ops[0]["operation"], ops[0]["task_class"]),
                         ("orchestrator", "completion", "qa"))
        self.assertTrue(ops[0]["ok"])

    def test_a_slow_call_is_recorded_with_its_full_latency(self):
        # WAS test_remediation_loop_detects_bottleneck_on_slow_consecutive_calls, asserting
        # result["response_time_ms"] > 500. There is no bottleneck detector on this path and no
        # such key; SUBSTITUTION — the nearest real behaviour is that a slow provider call is
        # measured honestly rather than clipped or dropped, which is the measurement any
        # downstream bottleneck analysis would depend on. Sleep shortened from 600ms because the
        # assertion is about fidelity of the measurement, not about a specific threshold.
        rec = _Recorder([])

        def slow_call(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.15)
            return {"text": "response", "cost_usd": 0.0, "provider": provider, "model": model}

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek"]),
                      patch.object(model_gateway, "_call_provider", side_effect=slow_call)):
            model_gateway.complete("deepseek", "deepseek-chat", "test1",
                                   project="orchestrator", operation="remediation",
                                   task_class="bugfix", record_op=True)
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["operation"], "remediation")
        self.assertGreaterEqual(ops[0]["latency_ms"], 140)

    def test_a_learned_route_overrides_the_callers_provider(self):
        # WAS test_response_time_below_threshold_allows_route_selection: same expected outcome,
        # but it attributed the override to an avg_response_time_ms of 400 being under a 500ms
        # threshold. The override happens because the row's avg_quality clears the floor and its
        # provider is available; the reason string is also attached to the result, which the old
        # test never checked.
        rec = _Recorder([_route_row(provider="local", model="llama3.2:3b", quality=7.0)])

        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["local", "deepseek"]),
                      patch.object(model_gateway, "_call_provider", side_effect=fake_call)):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=False)
        self.assertEqual((result["provider"], result["model"]), ("local", "llama3.2:3b"))
        self.assertEqual(result["learned_route"], "learned orchestrator/completion route q=7.0")

    def test_a_failing_provider_falls_back_to_the_next_available_one(self):
        # WAS test_response_time_above_threshold_triggers_fallback_to_faster_route, which expected
        # complete() to abandon a *successful* local call for deepseek because a fabricated
        # avg_response_time_ms of 800 exceeded a fabricated threshold. complete() only leaves a
        # provider when the call RAISES, walking FALLBACK_ORDER over available(). That real
        # fallback — and the fallback_from/fallback_error breadcrumbs it leaves — is asserted
        # here instead.
        rec = _Recorder([])
        seen = []

        def flaky(provider, model, prompt, project=None, timeout=90):
            seen.append((provider, model))
            if provider == "local":
                raise RuntimeError("ollama not reachable")
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek", "local"]),
                      patch.object(model_gateway, "_call_provider", side_effect=flaky)):
            result = model_gateway.complete("local", "llama3.1", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=True, fallback=True)
        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["model"], model_gateway.DEFAULT_MODELS["deepseek"]())
        self.assertEqual(result["fallback_from"], "local")
        self.assertIn("ollama not reachable", result["fallback_error"])
        self.assertEqual([p for p, _ in seen], ["local", "deepseek"])
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertEqual([(r["provider"], r["ok"]) for r in ops],
                         [("local", False), ("deepseek", True)])

    def test_fallback_disabled_returns_the_error_without_trying_another_provider(self):
        # ADDED: the counterpart of the above. A caller that opts out of fallback must get the
        # error back rather than a silent provider swap.
        rec = _Recorder([])
        seen = []

        def always_fails(provider, model, prompt, project=None, timeout=90):
            seen.append(provider)
            raise RuntimeError("boom")

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek", "local"]),
                      patch.object(model_gateway, "_call_provider", side_effect=always_fails)):
            result = model_gateway.complete("local", "llama3.1", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=False, fallback=False)
        self.assertEqual(seen, ["local"])
        self.assertEqual(result["text"], "")
        self.assertIn("boom", result["error"])

    def test_complete_never_raises_when_every_provider_fails(self):
        # WAS test_response_time_measurement_fails_soft_on_timing_error, a try/except around a
        # call that could not fail, ending in assertIsNotNone — it asserted nothing. Rebuilt as
        # the real fail-soft contract: with every attempt raising, complete() still returns a
        # shaped dict carrying the last error, and records each failed attempt.
        rec = _Recorder([])

        def broken(provider, model, prompt, project=None, timeout=90):
            raise RuntimeError("provider %s exploded" % provider)

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek", "local"]),
                      patch.object(model_gateway, "_call_provider", side_effect=broken)):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=True)
        self.assertEqual(result["text"], "")
        self.assertEqual(result["cost_usd"], 0)
        self.assertIn("exploded", result["error"])
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertTrue(ops)
        self.assertTrue(all(r["ok"] is False for r in ops))

    def test_confidential_mode_disables_both_learned_routes_and_fallback(self):
        # WAS test_bottleneck_detection_disabled_skips_threshold_checks (the "feature flag off"
        # scenario) built on ORCH_ENABLE_BOTTLENECK_DETECTION, which nothing reads. The real
        # environment flag that suppresses route substitution on this path is
        # ORCH_CONFIDENTIAL_MODE, and it is stricter: a prompt scoped to one vendor must not be
        # re-sent to a second one, so learned routing AND fallback are both switched off.
        rec = _Recorder([_route_row(provider="local", model="llama3.2:3b", quality=9.0)])
        seen = []

        def fake_call(provider, model, prompt, project=None, timeout=90):
            seen.append(provider)
            raise RuntimeError("nope")

        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["local", "deepseek"]),
                      patch.object(model_gateway, "_call_provider", side_effect=fake_call),
                      patch.dict(os.environ, {"ORCH_CONFIDENTIAL_MODE": "true"}, clear=False)):
            result = model_gateway.complete("deepseek", "deepseek-chat", "secret work",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=False, fallback=True)
        self.assertEqual(seen, ["deepseek"])
        self.assertEqual(result["provider"], "deepseek")
        self.assertNotIn("learned_route", result)

    def test_a_cached_prompt_result_short_circuits_the_provider_call(self):
        # ADDED: the old file disabled prompt_result_cache in every test by shoving None into
        # sys.modules, so the cache branch of complete() — which returns early, still records the
        # operation, and re-attaches the learned-route reason — was never exercised at all.
        rec = _Recorder([])
        cached = {"text": "from cache", "cost_usd": 0.0, "provider": "deepseek",
                  "model": "deepseek-chat", "cached": True}
        call = MagicMock()
        with _Patches(*_patch_db(rec),
                      patch.object(prompt_result_cache, "lookup", return_value=cached),
                      patch.object(prompt_result_cache, "store", return_value=False),
                      patch.object(model_gateway, "available", return_value=["deepseek"]),
                      patch.object(model_gateway, "_call_provider", call)):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=True)
        call.assert_not_called()
        self.assertEqual(result["text"], "from cache")
        self.assertTrue(result["cached"])
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["latency_ms"], 0)
        self.assertEqual(ops[0]["cost_usd"], 0.0)
        # A cache hit is also booked as avoided work; that resource_events row is the only place
        # the saving is visible, so a regression that stopped recording it would be silent.
        saved = [row for table, row in rec.inserts if table == "resource_events"]
        self.assertEqual(len(saved), 1)
        self.assertIn("prompt_result_cache", saved[0]["detail"])

    def test_concurrent_completions_each_get_their_own_result_and_telemetry_row(self):
        # WAS test_concurrent_response_time_recordings_dont_corrupt_state. Two problems. (1) It
        # asserted `all(rt >= 0 ...)` on result.get("response_time_ms", 0) — a key complete()
        # never sets, so the default 0 made the assertion vacuously true no matter what the
        # threads did. (2) It ran patch.dict(sys.modules, {"db": MagicMock()}) INSIDE each of the
        # five threads; patch.dict restores by clearing and refilling the dict, so interleaved
        # restores left a MagicMock parked at sys.modules["db"] for the rest of the session and
        # broke unrelated test files much later. All patching now happens once, on the main
        # thread, against the real module objects, and the assertion is that each concurrent
        # call's own operation label survives round-trip into its own telemetry row.
        rec = _Recorder([])
        results = {}
        lock = threading.Lock()

        def fake_call(provider, model, prompt, project=None, timeout=90):
            time.sleep(0.01)
            return {"text": prompt, "cost_usd": 0.0, "provider": provider, "model": model}

        def thread_target(op_name):
            res = model_gateway.complete("deepseek", "deepseek-chat", op_name,
                                         project="orchestrator", operation=op_name,
                                         task_class="qa", record_op=True)
            with lock:
                results[op_name] = res

        names = ["op_%d" % i for i in range(5)]
        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek"]),
                      patch.object(model_gateway, "_call_provider", side_effect=fake_call)):
            threads = [threading.Thread(target=thread_target, args=(n,), name=n) for n in names]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        self.assertEqual(sorted(results), names)
        # Each call's own prompt came back to it — no cross-thread result bleed.
        for name in names:
            self.assertEqual(results[name]["text"], name)
        ops = [row for table, row in rec.inserts if table == "app_operations"]
        self.assertEqual(sorted(r["operation"] for r in ops), names)
        self.assertTrue(all(r["latency_ms"] >= 0 for r in ops))

    def test_no_provider_allowed_for_the_sensitivity_returns_a_shaped_error(self):
        # ADDED: the terms gate is applied to the attempt list too, and the empty-attempts branch
        # of complete() had no coverage.
        rec = _Recorder([])
        with _Patches(*_patch_db(rec), *_no_cache(),
                      patch.object(model_gateway, "available", return_value=["deepseek"]),
                      patch.object(model_gateway, "_provider_allowed", return_value=False),
                      patch.object(model_gateway, "_call_provider",
                                   side_effect=AssertionError("must not call a provider"))):
            result = model_gateway.complete("deepseek", "deepseek-chat", "test",
                                            project="orchestrator", operation="completion",
                                            task_class="qa", record_op=False)
        self.assertEqual(result["text"], "")
        self.assertIn("no provider allowed", result["error"])


class AppTriageRouteCanary(unittest.TestCase):
    """app_triage.route() — decide without executing."""

    def test_route_prefers_the_learned_app_operation_route(self):
        # WAS test_app_triage_route_includes_response_time_in_metadata, which asserted only that
        # "provider"/"model" were present and that result.get("provider") was not None — true of
        # every possible return value, so it could not fail. It also patched sys.modules["db"],
        # which app_triage never consults: app_triage binds `db` as a module-level attribute at
        # import time, so the mock was never reached and the assertions were really describing
        # the model_policy default. Patching app_triage.db is what actually drives this code.
        fake_db = MagicMock()
        fake_db.select.return_value = [{"provider": "local", "model": "llama3.2:3b",
                                        "avg_cost": 0.0, "avg_quality": 7.0}]
        with _Patches(patch.object(app_triage, "db", fake_db),
                      patch.object(model_gateway, "available", return_value=["local"])):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertEqual(result["source"], "learned")
        self.assertEqual((result["provider"], result["model"]), ("local", "llama3.2:3b"))
        self.assertIn("learned route", result["reason"])
        fake_db.select.assert_called_once_with(
            "app_op_routes", {"select": "*", "app": "eq.orchestrator", "operation": "eq.completion"})

    def test_route_ignores_a_learned_route_whose_provider_is_unavailable(self):
        # WAS test_threshold_just_above_limit_triggers_fallback, which set a 501ms
        # avg_response_time_ms "just over 500" and then asserted only assertIsNotNone(result) —
        # route() always returns a dict, so it could not fail either. The genuine
        # don't-use-the-learned-route condition in app_triage.route is `learned[0] in avail`;
        # when it does not hold the decision must come from the bandit/policy chain instead, and
        # must still name an available provider.
        fake_db = MagicMock()
        fake_db.select.return_value = [{"provider": "local", "model": "llama3.1",
                                        "avg_cost": 0.0, "avg_quality": 7.0}]
        with _Patches(patch.object(app_triage, "db", fake_db),
                      patch.object(model_gateway, "available", return_value=["claude"])):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertNotEqual(result["source"], "learned")
        self.assertEqual(result["provider"], "claude")
        self.assertTrue(result["model"])

    def test_route_is_fail_soft_when_the_control_plane_is_unreachable(self):
        # ADDED: app_triage._learned_route swallows db errors and returns None so a control-plane
        # outage degrades routing to the policy chooser instead of taking every app call down.
        fake_db = MagicMock()
        fake_db.select.side_effect = RuntimeError("set SUPABASE_URL and SUPABASE_SERVICE_KEY")
        with _Patches(patch.object(app_triage, "db", fake_db),
                      patch.object(model_gateway, "available", return_value=["claude"])):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertNotEqual(result["source"], "learned")
        self.assertEqual(result["provider"], "claude")


if __name__ == "__main__":
    unittest.main()
