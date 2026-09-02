#!/usr/bin/env python3
"""
test_canary_ollama_23.py — Canary test for coder routing (learned per-app/operation routes).

WHY THIS FILE WAS REWRITTEN (2026-08-24)
----------------------------------------
The previous version of this file asserted a "percentile-based routing" contract:
p50/p95/p99 response-time columns on `app_op_routes`, a stricter p95 SLO for
remediation than for generic work, and env knobs `ORCH_ENABLE_PERCENTILE_ROUTING`,
`ORCH_REMEDIATION_SLO_P95_MS`, `ORCH_GENERIC_RESPONSE_TIME_THRESHOLD_MS`.

None of that exists. `grep -rn 'p95_response_time_ms|ORCH_ENABLE_PERCENTILE_ROUTING|
REMEDIATION_SLO'` over the whole repo (py/md/sql/json) matches nothing outside that
file: no column, no constant, no env var, no migration, no reader. 19 of its 24 tests
failed, and almost all of them failed with "unexpectedly None" — not because a latency
gate rejected the route, but because `model_gateway._learned_route` skips any row whose
`avg_quality` is under `ORCH_LEARNED_ROUTE_MIN_QUALITY` (default 6.5) and those rows
carried no quality at all. The tests were passing latency fixtures to a function that
scores on quality, availability and provider terms, and never reads latency.

Two of the five that "passed" passed vacuously: `self.assertIsNone(result) or
self.assertNotEqual(...)` runs the first assertion and then evaluates the second one
only if the first returned truthy — which `assertIsNone` never does. So the second
half of that expression was dead in both places it appeared.

The percentile contract cannot survive against the real API, so each test below is a
substitution: same slot, same routing-canary intent, asserting the gate that
`_learned_route` ACTUALLY applies. Every test names what it used to assert.

THE REAL CONTRACT under test (runner/model_gateway.py::_learned_route):
  - off entirely unless ORCH_USE_LEARNED_APP_ROUTES is truthy (defaults on)
  - app = project or "orchestrator"
  - tries operation, then task_class, then "completion" — first qualifying row wins
  - query: app=eq.<app>, operation=eq.<op>, order=updated_at.desc, limit=1
  - rejects a row whose provider is not in available()
  - rejects a row whose provider is not allowed for the prompt's sensitivity
  - rejects a row with avg_quality < ORCH_LEARNED_ROUTE_MIN_QUALITY (default 6.5)
  - returns (provider, model, reason) or None; any exception returns None
and (runner/app_triage.py::route) which layers learned -> bandit -> policy.

No test here makes a network call or touches a real database: `db.select` is patched on
the real module object, which is the same object `_learned_route`'s inner `import db`
resolves to. The old file injected a MagicMock via `patch.dict(sys.modules, {"db": ...})`
FROM FIVE CONCURRENT THREADS; `patch.dict` restores by clearing and re-filling the dict,
so interleaved restores left a MagicMock parked in `sys.modules["db"]` for the rest of
the session. That is why runner/test_db_query_optimization.py passed alone and failed
whenever this file ran first — its `@patch("db.select")` was patching the leftover mock
while the real db module ran unpatched and tried to reach the network.
"""
import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402  — patched, never called for real
import model_gateway  # noqa: E402
import app_triage  # noqa: E402
import prompt_result_cache  # noqa: E402

# The real knobs this module reads, and their shipped defaults.
DEFAULT_MIN_QUALITY = 6.5           # ORCH_LEARNED_ROUTE_MIN_QUALITY
ROUTE_OPS_TRIED = 3                 # operation, task_class, "completion"


def route_row(**over):
    """A row shaped like app_op_routes. Quality clears the default bar unless overridden."""
    base = {
        "provider": "local",
        "model": "llama3.2:3b",
        "app": "orchestrator",
        "operation": "completion",
        "avg_quality": 7.0,
        "avg_cost": 0.0,
        "updated_at": "2026-08-24T00:00:00Z",
    }
    base.update(over)
    return base


class CoderRoutingLearnedRouteCanary(unittest.TestCase):
    """Canary for the learned per-(app, operation) route path used by the remediation loop."""

    ENV_KEYS = (
        "ORCH_USE_LEARNED_APP_ROUTES",
        "ORCH_LEARNED_ROUTE_MIN_QUALITY",
        "ORCH_CONFIDENTIAL_MODE",
    )

    def setUp(self):
        """Clear the routing knobs so every test observes the shipped defaults, then restore."""
        saved = {k: os.environ[k] for k in self.ENV_KEYS if k in os.environ}
        for key in self.ENV_KEYS:
            os.environ.pop(key, None)

        def restore():
            for key in self.ENV_KEYS:
                os.environ.pop(key, None)
            os.environ.update(saved)

        self.addCleanup(restore)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _route(self, rows, providers=("local",), **kw):
        """Run _learned_route with db.select stubbed. Returns (result, select_mock)."""
        select = MagicMock(return_value=list(rows))
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=list(providers)):
            result = model_gateway._learned_route(
                kw.get("project", "orchestrator"),
                kw.get("operation", "completion"),
                kw.get("task_class", "qa"),
                kw.get("sensitivity", "standard"),
            )
        return result, select

    # ── the returned decision ────────────────────────────────────────────────
    def test_a_qualifying_row_returns_provider_model_and_reason(self):
        # WAS: test_percentile_p95_tracked_separate_from_average — asserted a route with
        # p95=520 was rejected against a 400ms SLO. There is no p95 column and no SLO; the
        # test only "passed" because a vacuous `assertIsNone(...) or assertNotEqual(...)`
        # hid that the row was dropped for having no avg_quality at all.
        result, _ = self._route([route_row()])
        self.assertIsNotNone(result)
        provider, model, reason = result
        self.assertEqual(provider, "local")
        self.assertEqual(model, "llama3.2:3b")
        self.assertIsInstance(reason, str)

    def test_the_reason_names_the_app_operation_and_quality(self):
        # WAS: test_p50_used_for_fast_path_estimate — asserted p50 was surfaced as a UX
        # latency estimate. Nothing is surfaced but the reason string, which is what
        # complete() attaches to the result as `learned_route` and what operators read.
        result, _ = self._route([route_row(avg_quality=7.25)])
        _, _, reason = result
        self.assertIn("orchestrator", reason)
        self.assertIn("completion", reason)
        self.assertIn("7.25", reason)

    # ── the quality gate (the gate that actually exists) ─────────────────────
    def test_a_route_below_the_quality_bar_is_refused(self):
        # WAS: test_tail_latency_bottleneck_detection_catches_what_average_misses — asserted
        # a route with avg=300 but p99=900 was rejected for tail latency. Latency is never
        # read; quality is the gate that keeps bad routes out of the remediation loop.
        result, _ = self._route([route_row(avg_quality=DEFAULT_MIN_QUALITY - 0.05)])
        self.assertIsNone(result)

    def test_a_route_exactly_at_the_quality_bar_is_accepted(self):
        # WAS: test_p95_zero_treated_as_measurement_artifact. The boundary that really
        # exists is `avg_quality < min_q` — strictly less — so equality must pass.
        result, _ = self._route([route_row(avg_quality=DEFAULT_MIN_QUALITY)])
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_a_missing_quality_score_is_read_as_zero_and_refused(self):
        # WAS: test_p95_none_treated_as_missing_falls_back_to_average — asserted a None
        # percentile degraded to the average. The real None-handling is `or 0` on
        # avg_quality: an unrated route is worth nothing, not worth the benefit of the doubt.
        for missing in (None, 0, ""):
            with self.subTest(avg_quality=missing):
                result, _ = self._route([route_row(avg_quality=missing)])
                self.assertIsNone(result)

    def test_the_quality_bar_is_configurable(self):
        # WAS: test_p95_negative_handled_gracefully — asserted a negative percentile was
        # ignored. The knob that exists is ORCH_LEARNED_ROUTE_MIN_QUALITY: lowering it
        # admits exactly the legacy q=6.45 route the default bar refuses.
        legacy = route_row(avg_quality=6.45)
        self.assertIsNone(self._route([legacy])[0], "6.45 must fail the 6.5 default")
        with patch.dict(os.environ, {"ORCH_LEARNED_ROUTE_MIN_QUALITY": "6.0"}, clear=False):
            result, _ = self._route([legacy])
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.2:3b")

    def test_a_non_numeric_quality_fails_soft_to_no_route(self):
        # WAS: test_p95_non_numeric_string_fails_soft — same intent, real column. float("slow")
        # raises inside the guarded block, so the whole lookup returns None rather than
        # propagating. NOTE: the raise aborts the remaining operation lookups too, so one
        # corrupt row costs the task_class/"completion" fallbacks as well.
        result, _ = self._route([route_row(avg_quality="slow")])
        self.assertIsNone(result)

    # ── the availability and terms gates ─────────────────────────────────────
    def test_a_route_to_an_unavailable_provider_is_refused(self):
        # WAS: test_remediation_fallback_when_p95_exceeds_slo's rejection half. The real
        # reason a learned route gets dropped mid-incident is that its provider is not in
        # available() — e.g. demoted by provider_failover_sla.
        result, _ = self._route([route_row(provider="local")], providers=("deepseek",))
        self.assertIsNone(result)

    def test_a_provider_barred_for_the_prompt_sensitivity_is_refused(self):
        # WAS: test_p99_indicates_worst_case_tail_latency, which asserted nothing at all
        # beyond assertIsNotNone. The provider-terms gate is the one hard constraint here:
        # a confidential prompt must not leak to a vendor whose terms disallow it.
        select = MagicMock(return_value=[route_row()])
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]), \
             patch.object(model_gateway, "_provider_allowed", return_value=False):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "confidential")
        self.assertIsNone(result)

    def test_latency_columns_on_the_row_do_not_change_the_decision(self):
        # WAS: test_missing_percentile_data_uses_average_gracefully. Inverted into an
        # anti-regression: routing is quality/availability-based ONLY. If someone later adds
        # a latency gate, this test must be updated deliberately rather than silently.
        fast, _ = self._route([route_row(avg_response_time_ms=50, p95_response_time_ms=60)])
        slow, _ = self._route([route_row(avg_response_time_ms=9000, p95_response_time_ms=99000)])
        self.assertEqual(fast, slow)
        self.assertIsNotNone(fast)

    # ── the kill switch ──────────────────────────────────────────────────────
    def test_the_kill_switch_disables_learned_routing_without_querying(self):
        # WAS: test_percentile_routing_disabled_falls_back_to_average. The real switch is
        # ORCH_USE_LEARNED_APP_ROUTES, and it must short-circuit BEFORE the db read —
        # otherwise turning it off still costs a query per call.
        select = MagicMock(return_value=[route_row()])
        with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": "false"}, clear=False), \
             patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNone(result)
        select.assert_not_called()

    def test_the_kill_switch_is_on_by_default_and_honours_the_usual_spellings(self):
        # WAS: test_build_fix_respects_higher_threshold_than_remediation, whose assertion
        # (`assertIsNotNone(result) or assertEqual(...)`) was the vacuous `or` idiom.
        for truthy in ("1", "true", "yes", "on", "TRUE"):
            with self.subTest(value=truthy):
                with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": truthy}, clear=False):
                    self.assertIsNotNone(self._route([route_row()])[0])
        for falsy in ("0", "false", "no", "off", ""):
            with self.subTest(value=falsy):
                with patch.dict(os.environ, {"ORCH_USE_LEARNED_APP_ROUTES": falsy}, clear=False):
                    self.assertIsNone(self._route([route_row()])[0])
        self.assertIsNotNone(self._route([route_row()])[0], "learned routing defaults ON")

    # ── the operation lookup chain ───────────────────────────────────────────
    def test_lookup_order_is_operation_then_task_class_then_completion(self):
        # WAS: test_remediation_priority_uses_stricter_slo_than_generic_tasks — asserted
        # remediation carried a stricter threshold than generic work. It does not; what is
        # special about the operation name is only its position in this lookup chain.
        _, select = self._route([], operation="remediation", task_class="bugfix")
        ops = [call.args[1]["operation"] for call in select.call_args_list]
        self.assertEqual(ops, ["eq.remediation", "eq.bugfix", "eq.completion"])

    def test_the_task_class_route_is_used_when_the_operation_has_none(self):
        # WAS: test_completion_operation_uses_generic_threshold_not_remediation_slo.
        # Substituted for the real fallback: an unseen operation inherits its task_class's route.
        def by_op(_table, params):
            return [route_row(operation="bugfix", model="llama3.1")] \
                if params["operation"] == "eq.bugfix" else []

        select = MagicMock(side_effect=by_op)
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "brand-new-op", "bugfix", "standard")
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "llama3.1")

    def test_completion_is_the_last_resort_route(self):
        # WAS: test_same_route_rejects_remediation_with_p95_above_slo. Substituted for the
        # end of the same chain: when neither operation nor task_class is known, the app's
        # generic "completion" route is what the remediation loop falls back onto.
        def by_op(_table, params):
            return [route_row(model="codestral:22b")] if params["operation"] == "eq.completion" else []

        select = MagicMock(side_effect=by_op)
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "unseen-op", "unseen-class", "standard")
        self.assertEqual(result[1], "codestral:22b")
        self.assertEqual(len(select.call_args_list), ROUTE_OPS_TRIED)

    def test_a_qualifying_row_short_circuits_the_remaining_lookups(self):
        # WAS: test_multiple_routes_ranked_by_p95_quality_tradeoff — asserted client-side
        # ranking across routes by p95 and quality. No ranking happens: the FIRST qualifying
        # operation wins and the later lookups are never issued.
        _, select = self._route([route_row()], operation="completion", task_class="qa")
        self.assertEqual(len(select.call_args_list), 1)

    # ── the query itself ─────────────────────────────────────────────────────
    def test_the_query_asks_for_the_single_most_recent_row(self):
        # WAS: test_percentile_ordering_p50_le_p95_le_p99, which asserted nothing beyond
        # assertIsNotNone. Staleness is handled here, by ordering — not by a 300s window.
        _, select = self._route([route_row()], operation="remediation")
        table, params = select.call_args_list[0].args
        self.assertEqual(table, "app_op_routes")
        self.assertEqual(params["app"], "eq.orchestrator")
        self.assertEqual(params["operation"], "eq.remediation")
        self.assertEqual(params["order"], "updated_at.desc")
        self.assertEqual(params["limit"], "1")

    def test_only_the_first_row_of_a_result_is_considered(self):
        # WAS: test_percentile_computation_over_300s_rolling_window. Substituted for the
        # real consequence of `rows[0]`: if the db ever returns more than one row, the extra
        # rows are ignored outright — a higher-quality row further down does NOT win.
        rows = [route_row(model="first", avg_quality=6.6),
                route_row(model="second", avg_quality=9.9)]
        result, _ = self._route(rows)
        self.assertEqual(result[1], "first")

    def test_the_app_defaults_to_the_orchestrator_when_no_project_is_given(self):
        # WAS: test_backward_compat_routes_without_percentile_data_still_work, which failed
        # only because its legacy fixture had q=6.45. The real defaulting rule
        # (`app = project or "orchestrator"`) is what keeps project-less callers routable.
        for project in (None, ""):
            with self.subTest(project=project):
                _, select = self._route([], project=project)
                self.assertEqual(select.call_args_list[0].args[1]["app"], "eq.orchestrator")

    def test_no_route_is_cached_between_calls(self):
        # WAS: test_percentile_data_stale_after_300s_window_expires, which asserted a 300s
        # staleness window and got 6 calls where it expected 2 (it did not know about the
        # three-op chain). The real property is simpler and stronger: _learned_route holds no
        # state, so an operator's route update takes effect on the very next call.
        select = MagicMock(return_value=[])
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]):
            model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
            first = select.call_count
            model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertEqual(first, ROUTE_OPS_TRIED)
        self.assertEqual(select.call_count, 2 * ROUTE_OPS_TRIED)

    def test_a_db_failure_returns_no_route_instead_of_raising(self):
        # Unchanged in intent from test_percentile_db_lookup_exception_returns_none_fail_soft,
        # but it no longer injects a mock module into sys.modules, and it now proves the
        # lookup was actually attempted rather than short-circuited by a stale kill switch.
        select = MagicMock(side_effect=RuntimeError("db connection failed"))
        with patch.object(db, "select", select), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = model_gateway._learned_route("orchestrator", "completion", "qa", "standard")
        self.assertIsNone(result)
        select.assert_called_once()

    def test_concurrent_lookups_all_reach_the_same_decision(self):
        # WAS: test_concurrent_percentile_updates_dont_corrupt_state, which ran
        # `patch.dict(sys.modules, {"db": MagicMock()})` inside five threads and asserted
        # `all(p >= 0 for p in [])` — vacuously true over an always-empty list, while the
        # interleaved patch.dict restores corrupted sys.modules for the whole test session.
        # _learned_route is pure over (env, db rows), so the real property is that
        # concurrent callers agree; the patching now happens once, on the main thread.
        results, errors = [], []
        lock = threading.Lock()

        def worker():
            try:
                out = model_gateway._learned_route("orchestrator", "remediation", "bugfix", "standard")
            except Exception as exc:                      # pragma: no cover - failure path
                with lock:
                    errors.append(exc)
                return
            with lock:
                results.append(out)

        with patch.object(db, "select", MagicMock(return_value=[route_row(avg_quality=7.4)])), \
             patch.object(model_gateway, "available", return_value=["local"]):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 8)
        self.assertEqual(set(results), {("local", "llama3.2:3b", results[0][2])})

    # ── the route as complete() applies it ───────────────────────────────────
    def test_complete_reroutes_the_caller_onto_the_learned_route(self):
        # WAS: test_remediation_fallback_when_p95_exceeds_slo, which expected the fallback to
        # be triggered by p95 > SLO. The real mechanism that moves a remediation call off a
        # slow local model is the learned route overriding the caller's provider/model.
        calls = []

        def fake_call(provider, model, prompt, project=None, timeout=90):
            calls.append((provider, model))
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        learned = route_row(provider="deepseek", model="deepseek-v4-flash", avg_quality=7.4)
        with patch.object(db, "select", MagicMock(return_value=[learned])), \
             patch.object(model_gateway, "available", return_value=["deepseek", "local"]), \
             patch.object(prompt_result_cache, "lookup", return_value=None), \
             patch.object(prompt_result_cache, "store"), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("local", "llama3.1", "test prompt",
                                            project="orchestrator", operation="remediation",
                                            task_class="bugfix", record_op=False, fallback=True)

        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["model"], "deepseek-v4-flash")
        self.assertEqual(calls, [("deepseek", "deepseek-v4-flash")],
                         "the slow local model must not be called at all")
        self.assertIn("learned_route", result)

    def test_complete_leaves_the_caller_alone_when_no_route_qualifies(self):
        # WAS: test_percentile_routing_disabled_falls_back_to_average (complete() half).
        # The design rule in app_triage's docstring — "this NEVER makes an app more
        # expensive" — depends on an unusable learned route being a no-op, not a redirect.
        def fake_call(provider, model, prompt, project=None, timeout=90):
            return {"text": "ok", "cost_usd": 0.0, "provider": provider, "model": model}

        with patch.object(db, "select", MagicMock(return_value=[route_row(avg_quality=1.0)])), \
             patch.object(model_gateway, "available", return_value=["deepseek", "local"]), \
             patch.object(prompt_result_cache, "lookup", return_value=None), \
             patch.object(prompt_result_cache, "store"), \
             patch.object(model_gateway, "_call_provider", side_effect=fake_call):
            result = model_gateway.complete("local", "llama3.1", "test prompt",
                                            project="orchestrator", operation="remediation",
                                            task_class="bugfix", record_op=False, fallback=False)

        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["model"], "llama3.1")
        self.assertNotIn("learned_route", result)

    # ── app_triage, the app-facing wrapper ───────────────────────────────────
    def test_app_triage_route_reports_the_learned_source(self):
        # WAS: test_app_triage_route_includes_percentile_metadata, which asserted only that
        # "provider" and "model" were keys — true of every branch, so it could not tell a
        # learned route from a policy default. `source` is the field that distinguishes them.
        with patch.object(db, "select", MagicMock(return_value=[route_row()])), \
             patch.object(model_gateway, "available", return_value=["local"]):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertEqual(result["source"], "learned")
        self.assertEqual(result["provider"], "local")
        self.assertEqual(result["model"], "llama3.2:3b")

    def test_app_triage_falls_back_to_policy_when_the_learned_provider_is_gone(self):
        # New sibling of the above, replacing the old file's dead
        # test_remediation_operation_identified_by_name_not_just_class (whose assertion,
        # `result is None or result[0] == "deepseek"`, was satisfied by None and so could
        # never fail). app_triage.route must still return a usable provider when the learned
        # one is unavailable — that is the "never leave an app unroutable" half of §Design rule.
        with patch.object(db, "select", MagicMock(return_value=[route_row(provider="local")])), \
             patch.object(model_gateway, "available", return_value=["claude"]), \
             patch.object(app_triage.model_policy, "choose",
                          return_value=("claude", "claude-haiku", "cheapest capable")):
            result = app_triage.route("orchestrator", "completion", task_class="qa")
        self.assertEqual(result["source"], "policy")
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["model"], "claude-haiku")


if __name__ == "__main__":
    unittest.main()
