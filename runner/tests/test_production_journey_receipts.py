#!/usr/bin/env python3
"""Regression suite for task-defined production journeys and their receipts.

Proof: python3 -m unittest runner.tests.test_production_journey_receipts -v

The headline regression is `HttpTwoHundredCannotPromoteTest`: a release that is
demonstrably healthy (HTTP 200 + live SHA) must not promote a task on that basis alone.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import production_journey as pj  # noqa: E402


def _clock():
    """Deterministic monotonic clock: 0.1s per call."""
    state = {"t": 0.0}

    def tick():
        state["t"] += 0.1
        return state["t"]
    return tick


def http_stub(*responses):
    """Return an http callable yielding the given (status, body, headers) in order.

    The last response repeats forever, so a single response models a stable service.
    """
    calls = {"n": 0}

    def fetch(url, timeout=20, headers=None):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        r = responses[i]
        return (r[0], r[1], r[2] if len(r) > 2 else {})
    fetch.calls = calls
    return fetch


HTML = "<html><body><h1>Checkout complete</h1><span id='order-total'>$42.00</span></body></html>"

CHECKOUT_JOURNEY = {
    "probe": "http",
    "steps": [
        {"name": "checkout", "path": "/checkout/success", "expect_status": 200,
         "expect_body_contains": ["Checkout complete", "order-total"]},
    ],
}


class SpecBoundsTest(unittest.TestCase):

    def test_accepts_a_well_formed_journey(self):
        spec = pj.parse_spec(CHECKOUT_JOURNEY, slug="t1")
        self.assertEqual(spec["probe"], "http")
        self.assertEqual(len(spec["steps"]), 1)
        self.assertTrue(spec["required"])

    def test_accepts_json_string_form(self):
        spec = pj.parse_spec(json.dumps(CHECKOUT_JOURNEY), slug="t1")
        self.assertEqual(spec["steps"][0]["name"], "checkout")

    def test_rejects_http_step_that_only_asserts_status_200(self):
        """The whole point: 'it returned 200' is not an assertion about behaviour."""
        with self.assertRaises(pj.JourneySpecError) as ctx:
            pj.parse_spec({"probe": "http", "steps": [{"path": "/", "expect_status": 200}]})
        self.assertIn("beyond", str(ctx.exception))

    def test_journey_is_bounded_by_max_steps(self):
        many = {"probe": "http", "steps": [
            {"path": f"/{i}", "expect_body_contains": "x"} for i in range(9)]}
        with patch.dict(os.environ, {"ORCH_JOURNEY_MAX_STEPS": "8"}):
            with self.assertRaises(pj.JourneySpecError):
                pj.parse_spec(many)

    def test_step_timeout_is_clamped_to_the_bound(self):
        with patch.dict(os.environ, {"ORCH_JOURNEY_STEP_TIMEOUT": "5"}):
            spec = pj.parse_spec({"probe": "http", "steps": [
                {"path": "/", "expect_body_contains": "x", "timeout_s": 9000}]})
        self.assertEqual(spec["steps"][0]["timeout_s"], 5)

    def test_probe_none_requires_a_justification(self):
        with self.assertRaises(pj.JourneySpecError):
            pj.parse_spec({"probe": "none"})
        with self.assertRaises(pj.JourneySpecError):
            pj.parse_spec({"probe": "none", "justification": "n/a"})

    def test_unknown_probe_kind_is_rejected(self):
        with self.assertRaises(pj.JourneySpecError):
            pj.parse_spec({"probe": "vibes", "steps": [{"path": "/"}]})

    def test_no_declared_journey_is_none_not_a_pass(self):
        self.assertIsNone(pj.spec_for_task({"slug": "t"}))


class HttpJourneyTest(unittest.TestCase):

    def _run(self, journey, responses, **kw):
        spec = pj.parse_spec(journey, slug="t1")
        return pj.run_journey(spec, base_url="https://app.example.com", sha="abc123def456",
                              http=http_stub(*responses), sleep=lambda s: None,
                              clock=_clock(), **kw)

    def test_core_scenario_passes_and_records_a_receipt(self):
        r = self._run(CHECKOUT_JOURNEY, [(200, HTML)])
        self.assertEqual(r["verdict"], pj.PASS)
        self.assertEqual(r["url"], "https://app.example.com")
        self.assertEqual(r["sha"], "abc123def456")
        self.assertEqual(r["environment"], "production")
        self.assertEqual(len(r["steps"]), 1)
        self.assertEqual(r["steps"][0]["attempts"], 1)
        self.assertEqual(r["failed_assertions"], [])
        self.assertGreaterEqual(r["assertion_count"], 2)
        self.assertTrue(r["id"])

    def test_http_200_with_wrong_body_fails(self):
        """EDGE CASE: the service is up and returns 200, but the behaviour is absent."""
        r = self._run(CHECKOUT_JOURNEY, [(200, "<html>Maintenance</html>")])
        self.assertEqual(r["verdict"], pj.FAIL)
        self.assertTrue(r["failed_assertions"])
        self.assertEqual(r["failed_assertions"][0]["assertion"], "body_contains")

    def test_expect_body_absent_catches_error_pages(self):
        journey = {"probe": "http", "steps": [
            {"name": "no-500", "path": "/", "expect_body_absent": "Application error"}]}
        r = self._run(journey, [(200, "Application error: a client-side exception")])
        self.assertEqual(r["verdict"], pj.FAIL)

    def test_header_assertion(self):
        journey = {"probe": "http", "steps": [
            {"name": "hdr", "path": "/", "expect_header": {"content-type": "text/html"}}]}
        self.assertEqual(self._run(journey, [(200, "x", {"content-type": "text/html"})])["verdict"],
                         pj.PASS)
        self.assertEqual(self._run(journey, [(200, "x", {"content-type": "application/pdf"})])["verdict"],
                         pj.FAIL)

    def test_transport_error_is_a_failure_not_a_crash(self):
        r = self._run(CHECKOUT_JOURNEY, [(None, "transport error: timed out")])
        self.assertEqual(r["verdict"], pj.FAIL)

    def test_timing_is_recorded(self):
        r = self._run(CHECKOUT_JOURNEY, [(200, HTML)])
        self.assertGreater(r["duration_ms"], 0)
        self.assertGreaterEqual(r["steps"][0]["duration_ms"], 0)


class RetryAndFlakyTest(unittest.TestCase):

    def _run(self, responses, retries="2"):
        spec = pj.parse_spec(CHECKOUT_JOURNEY, slug="t1")
        with patch.dict(os.environ, {"ORCH_JOURNEY_RETRIES": retries,
                                     "ORCH_JOURNEY_BACKOFF_S": "0"}):
            return pj.run_journey(spec, base_url="https://app.example.com", sha="abc",
                                  http=http_stub(*responses), sleep=lambda s: None,
                                  clock=_clock())

    def test_retry_recovers_but_the_verdict_is_flaky_not_pass(self):
        r = self._run([(503, "down"), (200, HTML)])
        self.assertEqual(r["verdict"], pj.FLAKY)
        self.assertEqual(r["steps"][0]["attempts"], 2)

    def test_exhausted_retries_fail(self):
        r = self._run([(503, "down")])
        self.assertEqual(r["verdict"], pj.FAIL)
        self.assertEqual(r["steps"][0]["attempts"], 3)

    def test_backoff_is_exponential(self):
        slept = []
        spec = pj.parse_spec(CHECKOUT_JOURNEY, slug="t1")
        with patch.dict(os.environ, {"ORCH_JOURNEY_RETRIES": "3", "ORCH_JOURNEY_BACKOFF_S": "1"}):
            pj.run_journey(spec, base_url="https://x", sha="abc", http=http_stub((500, "")),
                           sleep=slept.append, clock=_clock())
        self.assertEqual(slept, [1.0, 2.0, 4.0])

    def test_zero_retries_means_one_attempt(self):
        r = self._run([(503, "down")], retries="0")
        self.assertEqual(r["steps"][0]["attempts"], 1)


class BudgetTest(unittest.TestCase):

    def test_journey_stops_at_its_wall_clock_budget(self):
        journey = {"probe": "http", "steps": [
            {"name": f"s{i}", "path": f"/{i}", "expect_body_contains": "ok"} for i in range(4)]}
        spec = pj.parse_spec(journey, slug="t1")
        with patch.dict(os.environ, {"ORCH_JOURNEY_BUDGET_S": "0.25", "ORCH_JOURNEY_RETRIES": "0"}):
            r = pj.run_journey(spec, base_url="https://x", sha="abc",
                               http=http_stub((200, "ok")), sleep=lambda s: None, clock=_clock())
        verdicts = [s["verdict"] for s in r["steps"]]
        self.assertIn(pj.SKIPPED, verdicts)
        self.assertEqual(r["verdict"], pj.FAIL)


class AlternateProbeTest(unittest.TestCase):
    """Non-web changes must declare an explicit alternate probe."""

    def test_command_probe_passes_on_expected_exit_and_output(self):
        spec = pj.parse_spec({"probe": "command", "steps": [
            {"name": "cli", "command": ["orchctl", "--version"],
             "expect_output_contains": "1.2.3"}]}, slug="cli-task")
        r = pj.run_journey(spec, base_url="", sha="abc",
                           command=lambda cmd, timeout=20, cwd=None: (0, "orchctl 1.2.3"),
                           sleep=lambda s: None, clock=_clock())
        self.assertEqual(r["verdict"], pj.PASS)
        self.assertEqual(r["probe"], "command")

    def test_command_probe_fails_on_nonzero_exit(self):
        spec = pj.parse_spec({"probe": "command", "steps": [
            {"name": "cli", "command": ["orchctl", "migrate"]}]}, slug="cli-task")
        with patch.dict(os.environ, {"ORCH_JOURNEY_RETRIES": "0"}):
            r = pj.run_journey(spec, base_url="", sha="abc",
                               command=lambda cmd, timeout=20, cwd=None: (1, "boom"),
                               sleep=lambda s: None, clock=_clock())
        self.assertEqual(r["verdict"], pj.FAIL)

    def test_command_probe_refuses_shell_strings(self):
        with self.assertRaises(pj.JourneySpecError):
            pj._default_command("rm -rf /", timeout=1)

    def test_artifact_probe(self):
        with tempfile.NamedTemporaryFile("w", suffix=".whl", delete=False) as f:
            f.write("wheel-bytes")
            path = f.name
        try:
            spec = pj.parse_spec({"probe": "artifact", "steps": [
                {"name": "wheel", "path": path, "min_bytes": 5}]}, slug="lib-task")
            r = pj.run_journey(spec, base_url="", sha="abc", sleep=lambda s: None, clock=_clock())
            self.assertEqual(r["verdict"], pj.PASS)
        finally:
            os.unlink(path)

    def test_justified_none_probe_passes_without_steps(self):
        spec = pj.parse_spec({"probe": "none",
                              "justification": "docs-only change, no runtime surface"},
                             slug="docs-task")
        r = pj.run_journey(spec, base_url="", sha="abc", sleep=lambda s: None, clock=_clock())
        self.assertEqual(r["verdict"], pj.PASS)
        self.assertIn("docs-only", r["note"])


class RedactionTest(unittest.TestCase):

    def test_bearer_tokens_and_query_secrets_are_scrubbed(self):
        dirty = ("GET https://app.example.com/x?token=abcd1234secret&page=2 "
                 "Authorization: Bearer sk-live-AAAABBBBCCCCDDDD")
        clean = pj.redact(dirty)
        self.assertNotIn("abcd1234secret", clean)
        self.assertNotIn("AAAABBBBCCCCDDDD", clean)
        self.assertIn("page=2", clean)

    def test_basic_auth_and_email_are_scrubbed(self):
        clean = pj.redact("https://admin:hunter2@app.example.com sent to kale@heretomorrow.us")
        self.assertNotIn("hunter2", clean)
        self.assertNotIn("kale@heretomorrow.us", clean)

    def test_receipts_are_redacted_before_storage(self):
        journey = {"probe": "http", "steps": [
            {"name": "auth", "path": "/x?api_key=SUPERSECRETVALUE",
             "expect_body_contains": "ok"}]}
        spec = pj.parse_spec(journey, slug="t1")
        r = pj.run_journey(spec, base_url="https://app.example.com", sha="abc",
                           http=http_stub((200, "ok")), sleep=lambda s: None, clock=_clock())
        self.assertNotIn("SUPERSECRETVALUE", json.dumps(r))

    def test_redaction_is_recursive_over_nested_structures(self):
        out = pj.redact({"a": [{"b": "Bearer tok_abcdefghijkl"}]})
        self.assertNotIn("tok_abcdefghijkl", json.dumps(out))


class GateTest(unittest.TestCase):

    def _receipt(self, verdict, required=True):
        return {"verdict": verdict, "required": required, "failed_assertions":
                [{"step": "checkout", "assertion": "body_contains",
                  "expected": "Checkout complete", "actual": "absent"}]}

    def test_pass_promotes(self):
        ok, why = pj.gate(self._receipt(pj.PASS))
        self.assertTrue(ok)

    def test_fail_does_not_promote_and_names_the_assertion(self):
        ok, why = pj.gate(self._receipt(pj.FAIL))
        self.assertFalse(ok)
        self.assertIn("body_contains", why)

    def test_flaky_does_not_promote_by_default(self):
        ok, why = pj.gate(self._receipt(pj.FLAKY))
        self.assertFalse(ok)
        self.assertIn("flaky", why)

    def test_flaky_promotes_only_when_explicitly_allowed(self):
        with patch.dict(os.environ, {"ORCH_JOURNEY_ALLOW_FLAKY": "1"}):
            ok, _ = pj.gate(self._receipt(pj.FLAKY))
        self.assertTrue(ok)

    def test_missing_receipt_does_not_promote(self):
        ok, why = pj.gate(None, required=True)
        self.assertFalse(ok)
        self.assertEqual(why, pj.HTTP_200_ONLY_REASON)

    def test_optional_journey_may_be_absent(self):
        ok, _ = pj.gate(None, required=False)
        self.assertTrue(ok)

    def test_kill_switch_disables_the_gate(self):
        with patch.dict(os.environ, {"ORCH_JOURNEY_ENABLED": "0"}):
            ok, why = pj.gate(None, required=True)
        self.assertTrue(ok)
        self.assertIn("disabled", why)

    def test_rollback_only_on_a_required_failure(self):
        self.assertTrue(pj.should_roll_back(self._receipt(pj.FAIL)))
        self.assertFalse(pj.should_roll_back(self._receipt(pj.FAIL, required=False)))
        self.assertFalse(pj.should_roll_back(self._receipt(pj.FLAKY)))
        self.assertFalse(pj.should_roll_back(pj.receipt_missing(sha="abc")))
        self.assertFalse(pj.should_roll_back(None))


class ReceiptStoreTest(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.home.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.home.cleanup()

    def _store(self, slug, sha, verdict=pj.PASS):
        spec = pj.parse_spec(CHECKOUT_JOURNEY, slug=slug)
        body = HTML if verdict == pj.PASS else "nope"
        with patch.dict(os.environ, {"ORCH_JOURNEY_RETRIES": "0"}):
            r = pj.run_journey(spec, base_url="https://app.example.com", sha=sha,
                               http=http_stub((200, body)), sleep=lambda s: None, clock=_clock())
        pj.store(r)
        return r

    def test_store_and_find_by_sha_and_slug(self):
        self._store("task-a", "sha-aaaaaaaaaaaa")
        self._store("task-b", "sha-bbbbbbbbbbbb")
        found = pj.find("sha-aaaaaaaaaaaa", "task-a")
        self.assertIsNotNone(found)
        self.assertEqual(found["slug"], "task-a")
        self.assertIsNone(pj.find("sha-aaaaaaaaaaaa", "task-b"))

    def test_receipt_is_valid_json_on_disk_with_the_required_fields(self):
        r = self._store("task-a", "sha-aaaaaaaaaaaa")
        path = os.path.join(self.home.name, "journey-receipts", r["id"] + ".json")
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        for field in ("url", "environment", "sha", "steps", "duration_ms", "verdict",
                      "assertion_count", "failed_assertions"):
            self.assertIn(field, saved)

    def test_summary_counts_verdicts_for_the_proof_ui(self):
        self._store("task-a", "sha-aaaaaaaaaaaa", pj.PASS)
        self._store("task-b", "sha-bbbbbbbbbbbb", pj.FAIL)
        s = pj.summary()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["verdicts"][pj.PASS], 1)
        self.assertEqual(s["verdicts"][pj.FAIL], 1)
        self.assertEqual(len(s["recent"]), 2)

    def test_verify_task_records_missing_when_nothing_is_declared(self):
        r = pj.verify_task({"slug": "undeclared"}, base_url="https://x", sha="sha-cccccccccccc")
        self.assertEqual(r["verdict"], pj.MISSING)
        self.assertIsNotNone(pj.find("sha-cccccccccccc", "undeclared"))

    def test_verify_task_records_missing_for_a_malformed_spec(self):
        r = pj.verify_task({"slug": "bad", "journey": "{not json"},
                           base_url="https://x", sha="sha-dddddddddddd")
        self.assertEqual(r["verdict"], pj.MISSING)
        self.assertIn("invalid journey spec", r["note"])


class ManifestJourneyTest(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.home.name})
        self.env.start()
        import release_manifest
        self.rm = release_manifest
        self.repo = tempfile.TemporaryDirectory()
        self.manifest = self.rm.create("demo", self.repo.name, "base1", "cand1",
                                       tasks=[{"slug": "task-a"}, {"slug": "task-b"}])

    def tearDown(self):
        self.env.stop()
        self.home.cleanup()
        self.repo.cleanup()

    def test_manifest_is_not_ok_until_every_required_journey_passes(self):
        m = self.rm.record_journey(self.manifest["id"],
                                   {"slug": "task-a", "verdict": pj.PASS, "required": True})
        self.assertTrue(m["journeys_ok"])
        self.assertEqual(self.rm.required_journey_slugs(m), ["task-b"])
        m = self.rm.record_journey(self.manifest["id"],
                                   {"slug": "task-b", "verdict": pj.FAIL, "required": True})
        self.assertFalse(m["journeys_ok"])
        self.assertEqual(self.rm.required_journey_slugs(m), ["task-b"])

    def test_optional_journeys_do_not_block_the_manifest(self):
        m = self.rm.record_journey(self.manifest["id"],
                                   {"slug": "task-a", "verdict": pj.FAIL, "required": False})
        self.assertTrue(m["journeys_ok"])


class HttpTwoHundredCannotPromoteTest(unittest.TestCase):
    """THE REGRESSION: a green release must not promote a task on HTTP 200 alone."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CLAUDE_ORCH_HOME": self.home.name})
        self.env.start()
        import deployment_terminal
        self.dt = deployment_terminal
        # A release that is as healthy as the old code could ever observe.
        self.verify = {"project": "demo", "sha": "cafebabecafe", "url": "https://demo.example.com",
                       "http_status": 200, "http_ok": True, "sha_live": True,
                       "sha_reason": "sha cafebabecafe live", "ok": True,
                       "release_health_only": True, "reason": "release healthy"}

    def tearDown(self):
        self.env.stop()
        self.home.cleanup()

    def test_verify_release_labels_itself_release_health_only(self):
        self.assertTrue(self.verify["release_health_only"])

    def test_task_without_a_journey_is_not_promotable_despite_http_200(self):
        receipt, ok, why = self.dt._journey_verdict({"slug": "no-journey"}, self.verify)
        self.assertFalse(ok)
        self.assertEqual(why, pj.HTTP_200_ONLY_REASON)
        self.assertEqual(receipt["verdict"], pj.MISSING)

    def test_task_whose_journey_fails_is_not_promotable_despite_http_200(self):
        pj.store(pj._finalise({"slug": "broken", "probe": "http", "required": True},
                              [{"name": "checkout", "verdict": pj.FAIL, "attempts": 3,
                                "duration_ms": 5, "assertions": [
                                    {"name": "body_contains", "expected": "Checkout complete",
                                     "actual": "absent", "ok": False}], "detail": ""}],
                              pj.FAIL, "cafebabecafe", "https://demo.example.com", "production", 5))
        receipt, ok, why = self.dt._journey_verdict({"slug": "broken"}, self.verify)
        self.assertFalse(ok)
        self.assertIn("journey failed", why)

    def test_task_whose_journey_passes_is_promotable(self):
        pj.store(pj._finalise({"slug": "good", "probe": "http", "required": True},
                              [{"name": "checkout", "verdict": pj.PASS, "attempts": 1,
                                "duration_ms": 5, "assertions": [
                                    {"name": "body_contains", "expected": "Checkout complete",
                                     "actual": "present", "ok": True}], "detail": ""}],
                              pj.PASS, "cafebabecafe", "https://demo.example.com", "production", 5))
        receipt, ok, why = self.dt._journey_verdict({"slug": "good"}, self.verify)
        self.assertTrue(ok, why)

    def test_journey_unproven_is_its_own_funnel_bucket(self):
        self.assertEqual(self.dt.BUCKET_JOURNEY_UNPROVEN, "skipped_journey_unproven")

    def test_journey_failed_release_is_red_for_backpressure(self):
        self.assertIn("journey_failed", self.dt.FAILED_RELEASE_STATES)

    def test_promotion_requires_the_journey_even_when_the_commit_is_an_ancestor(self):
        """End-to-end through promote_release with git ancestry forced to promotable."""
        rows = [{"id": "1", "slug": "no-journey", "state": "MERGED",
                 "artifact_commit": "deadbeefdead"}]
        updates = []
        with patch.object(self.dt, "verify_release", return_value=self.verify), \
             patch.object(self.dt, "_select_all_merged_with_commit", return_value=rows), \
             patch.object(self.dt, "_classify_candidate",
                          return_value=self.dt.BUCKET_PROMOTABLE), \
             patch.object(self.dt.db, "select",
                          return_value=[{"id": "p1", "repo_path": "/tmp/demo-repo"}]), \
             patch.object(self.dt.db, "update",
                          side_effect=lambda *a, **k: updates.append((a, k))):
            out = self.dt.promote_release({"project": "demo", "to_sha": "cafebabecafe"})
        self.assertEqual(out["promoted"], 0)
        self.assertEqual(out["journey_unproven"], 1)
        self.assertEqual(out["funnel"][self.dt.BUCKET_JOURNEY_UNPROVEN], 1)
        self.assertEqual(updates, [], "no task may be promoted on HTTP 200 alone")


if __name__ == "__main__":
    unittest.main()
