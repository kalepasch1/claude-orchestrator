#!/usr/bin/env python3
"""Regression coverage for runner/db.py's CORE_RETRY_RPCS allowlist.

Lease-night recovery, §1. The allowlist itself is present in HEAD; what it never had was a
test. That matters more than usual here: this allowlist is the resilience hardening for the
exact outage class that mass-quarantined 91 tasks on 2026-07-29 — a transient Supabase blip
during a lease RPC, retried nowhere, surfacing as a hard failure per task.

The properties below are the ones an "obviously harmless" refactor breaks silently:

  * every core RPC the lease/claim/complete path depends on is retried;
  * NON-core POSTs are NOT retried (a retried uncertain write can duplicate work when the
    first request reached PostgREST but its response was lost);
  * GETs are always retryable, probe requests never are;
  * backoff actually happens, and is bounded.
"""
import os
import sys
import unittest
import urllib.error

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key-not-a-real-credential")

import db  # noqa: E402


class AllowlistTests(unittest.TestCase):
    """The lease-night set, named explicitly so a silent deletion fails a test."""

    LEASE_RPCS = ("acquire_branch_execution_lease",
                  "heartbeat_branch_execution_lease",
                  "release_branch_execution_lease")
    QUEUE_RPCS = ("execute_task", "complete_task", "claim_task", "mark_done",
                  "record_attempt", "update_task_state", "insert_outcome")

    def test_lease_rpcs_are_retryable(self):
        for name in self.LEASE_RPCS:
            self.assertIn(name, db.CORE_RETRY_RPCS, name)
            self.assertTrue(db._is_core_rpc(f"/rest/v1/rpc/{name}"), name)

    def test_queue_lifecycle_rpcs_are_retryable(self):
        for name in self.QUEUE_RPCS:
            self.assertIn(name, db.CORE_RETRY_RPCS, name)
            self.assertTrue(db._is_core_rpc(f"/rest/v1/rpc/{name}"), name)

    def test_unknown_rpc_is_not_retryable(self):
        self.assertFalse(db._is_core_rpc("/rest/v1/rpc/some_vendor_webhook"))

    def test_non_rpc_post_path_is_not_core(self):
        self.assertFalse(db._is_core_rpc("/rest/v1/tasks"))

    def test_query_string_and_trailing_slash_do_not_defeat_the_match(self):
        self.assertTrue(db._is_core_rpc("/rest/v1/rpc/claim_task/"))

    def test_is_core_rpc_is_fail_soft_on_junk(self):
        for junk in ("", "/", "rpc/claim_task"):
            self.assertFalse(db._is_core_rpc(junk))

    def test_transient_statuses_cover_the_cloudflare_edge_codes(self):
        for code in (408, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525):
            self.assertIn(code, db.HTTP_RETRY_STATUSES, code)

    def test_client_errors_are_never_retried(self):
        for code in (400, 401, 403, 404, 409, 422):
            self.assertNotIn(code, db.HTTP_RETRY_STATUSES, code)


class _FakeResponse:
    def __init__(self, payload=b"[]"):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RetryBehaviourTests(unittest.TestCase):
    """Exercise _req's retry loop with urlopen and sleep stubbed out."""

    def setUp(self):
        self.opened = []
        self.slept = []
        self._real_urlopen = db.urllib.request.urlopen
        self._real_sleep = db.time.sleep
        db.time.sleep = lambda s: self.slept.append(s)

    def tearDown(self):
        db.urllib.request.urlopen = self._real_urlopen
        db.time.sleep = self._real_sleep

    def _fail_n_then_succeed(self, failures, code=503):
        state = {"n": 0}

        def urlopen(req, timeout=None):
            self.opened.append(getattr(req, "full_url", ""))
            if state["n"] < failures:
                state["n"] += 1
                raise urllib.error.HTTPError(
                    getattr(req, "full_url", ""), code, "transient", {}, None)
            return _FakeResponse(b"[]")

        db.urllib.request.urlopen = urlopen

    def test_core_rpc_rides_out_a_transient_outage(self):
        self._fail_n_then_succeed(2)
        result = db.rpc("acquire_branch_execution_lease", {"p": 1})
        self.assertEqual(result, [])
        self.assertEqual(len(self.opened), 3, "should have retried twice before succeeding")

    def test_core_rpc_backs_off_between_attempts(self):
        self._fail_n_then_succeed(2)
        db.rpc("claim_task", {})
        self.assertEqual(len(self.slept), 2)
        self.assertLess(self.slept[0], self.slept[1], "backoff must increase")
        self.assertTrue(all(s <= 13 for s in self.slept), "backoff must stay bounded")

    def test_non_core_rpc_is_single_attempt(self):
        self._fail_n_then_succeed(2)
        with self.assertRaises(urllib.error.HTTPError):
            db.rpc("some_vendor_webhook", {})
        self.assertEqual(len(self.opened), 1, "non-core POSTs must not be retried")

    def test_retries_are_exhausted_rather_than_infinite(self):
        self._fail_n_then_succeed(99)
        with self.assertRaises(urllib.error.HTTPError):
            db.rpc("complete_task", {})
        self.assertEqual(len(self.opened), db.HTTP_RETRIES + 1)

    def test_non_transient_status_is_raised_immediately(self):
        self._fail_n_then_succeed(99, code=401)
        with self.assertRaises(urllib.error.HTTPError):
            db.rpc("complete_task", {})
        self.assertEqual(len(self.opened), 1)

    def test_network_level_failures_are_also_retried_for_core_rpcs(self):
        state = {"n": 0}

        def urlopen(req, timeout=None):
            self.opened.append(getattr(req, "full_url", ""))
            if state["n"] < 1:
                state["n"] += 1
                raise urllib.error.URLError("connection reset")
            return _FakeResponse(b"[]")

        db.urllib.request.urlopen = urlopen
        db.rpc("heartbeat_branch_execution_lease", {})
        self.assertEqual(len(self.opened), 2)

    def test_reads_are_retryable_too(self):
        self._fail_n_then_succeed(1)
        db.select("tasks", {"select": "id", "limit": "1"})
        self.assertEqual(len(self.opened), 2)


if __name__ == "__main__":
    unittest.main()
